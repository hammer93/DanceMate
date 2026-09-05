"""v0.82 Tango Source Expansion: migrations 021 (source registration) and 022
(venue alias seed), and the cross-source dedup they enable through the
*existing* pipeline (runtime.duplicates + runtime.normalization.resolve_venue)
rather than a new one.

Every test here runs only against the `pg` fixture, which is rolled back at
teardown and never committed - this release's own instruction is "production
DB를 수정하지 않는다", so migrations 021/022 are applied by executing their
SQL text directly on `pg`'s connection (exactly what `runtime.migrate.run()`
does internally, minus the `commit()` and the `schema_migrations` bookkeeping
that would make the effect durable) rather than by running the real
migration runner, which commits.
"""

from __future__ import annotations

import pytest

from runtime import duplicates, migrate, normalization


def _apply(pg, *versions: str) -> None:
    all_migrations = migrate.discover()
    for version in versions:
        migration = next(m for m in all_migrations if m.name.startswith(f"{version}_"))
        with pg.cursor() as cur:
            cur.execute(migration.sql)


@pytest.fixture
def seeded(pg):
    """Both new migrations applied, uncommitted, on `pg`'s own connection."""
    _apply(pg, "021", "022")
    return pg


# --- migration 021: source registration --------------------------------------

def test_registers_all_three_top3_immediate_sources(seeded):
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT source_key, platform, enabled, config->>'parser' AS parser "
            "FROM sources WHERE source_key IN ('SRC-W-002', 'SRC-W-003', 'SRC-W-004') "
            "ORDER BY source_key"
        )
        rows = cur.fetchall()
    assert [r[0] for r in rows] == ["SRC-W-002", "SRC-W-003", "SRC-W-004"]
    assert all(r[1] == "WEB" for r in rows)
    assert all(r[2] is False for r in rows), "new sources must register disabled"
    assert [r[3] for r in rows] == [
        "tangonow_firestore", "tangocalendar_json", "danceinfo_json",
    ]


def test_registration_is_idempotent(seeded):
    """Applying 021 a second time must not error or duplicate the rows."""
    _apply(seeded, "021")  # a second application on top of `seeded`'s first
    with seeded.cursor() as cur:
        cur.execute("SELECT count(*) FROM sources WHERE source_key = 'SRC-W-002'")
        assert cur.fetchone()[0] == 1


def test_existing_sources_are_never_touched(pg, unique):
    from runtime import sources

    before = sources.list_sources(pg)
    _apply(pg, "021", "022")
    after = sources.list_sources(pg)
    before_keys = {s["source_key"]: s for s in before}
    after_keys = {s["source_key"]: s for s in after}
    for key, row in before_keys.items():
        assert after_keys[key] == row, f"{key} was modified by the v0.82 migration"


def test_k_tango_is_preserved_untouched(seeded):
    with seeded.cursor() as cur:
        cur.execute("SELECT count(*) FROM sources WHERE source_key = 'SRC-W-001'")
        assert cur.fetchone()[0] == 1


def test_collection_targets_are_the_real_endpoint_not_a_homepage(seeded):
    with seeded.cursor() as cur:
        cur.execute("SELECT source_key, url FROM sources WHERE source_key = 'SRC-W-002'")
        _, url = cur.fetchone()
    assert url == (
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events?pageSize=300"
    )


# --- migration 022: venue alias seed -----------------------------------------

@pytest.mark.parametrize("alias,canonical", [
    ("PISTA", "PISTA"),
    ("피스타", "PISTA"),
    ("엔빠스", "EN PAZ Tango Studio"),
    ("탱고 엔빠스 스튜디오", "EN PAZ Tango Studio"),
    ("Andante", "Tango Andante"),
    ("탱고 안단테", "Tango Andante"),
    ("오나다", "Tango O Nada"),
    ("오초", "OCHO"),
    ("라 벤따나", "La Ventana"),
    ("아미고스튜디오", "Amigo Studio"),
    ("데땅고", "Cafe de Tango"),
])
def test_known_venue_aliases_resolve_to_the_same_venue(seeded, alias, canonical):
    from runtime import master_data

    found = master_data.resolve_venue(seeded, alias)
    assert found is not None, f"{alias!r} did not resolve to any venue"
    assert found["name"] == canonical


def test_venue_seed_is_idempotent(pg):
    _apply(pg, "021", "022")
    _apply(pg, "022")  # a second application must not error
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venue_aliases WHERE normalized_alias = 'pista'")
        assert cur.fetchone()[0] == 1


# --- cross-source dedup through the EXISTING pipeline ------------------------
#
# No new dedup module: resolve_venue() already resolves every candidate
# against venue_aliases, and duplicates.classify() already auto-merges two
# events sharing a date, start time and venue_id. Once the alias rows exist,
# a TangoNOW record naming "PISTA" and a DanceInfo record naming "피스타" for
# the same Saturday resolve to the same venue_id and merge with zero new code.

def _candidate(unique, **overrides):
    payload = {
        "candidate_id": int(f"{unique[-6:]}1"),
        "post_id": 1,
        "source_url": f"https://example.test/{unique}-a",
        "event_name": f"밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-06",
        "start_time": "14:00", "end_time": "18:00", "end_day_offset": 0,
        "venue": "PISTA", "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
        "time_evidence": "EXPLICIT",
    }
    payload.update(overrides)
    return payload


def test_two_sources_naming_the_same_venue_differently_share_one_venue_id(seeded, unique):
    tangonow = normalization.normalize_candidate(seeded, _candidate(unique, venue="PISTA"))
    danceinfo = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}2"),
                            source_url=f"https://example.test/{unique}-b", venue="피스타"),
    )
    assert tangonow["venue"]["venue_id"] == danceinfo["venue"]["venue_id"]
    assert tangonow["venue"]["status"] == normalization.VENUE_RESOLVED


def _refetch(con, event_id: int) -> dict:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE event_id = %s", (event_id,))
        columns = [c.name for c in cur.description]
        return dict(zip(columns, cur.fetchone()))


def test_the_existing_duplicate_scan_auto_merges_them(seeded, unique):
    """Scoped to this test's own two rows, not the scan's global count - the
    same real calendar date this test uses may carry unrelated production
    events that merge (or don't) independently of this test's own pair."""
    from datetime import date

    first = normalization.normalize_candidate(seeded, _candidate(unique, venue="PISTA"))
    second = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}2"),
                            source_url=f"https://example.test/{unique}-b", venue="피스타"),
    )
    duplicates.scan(seeded, on=date(2026, 9, 6))
    after_first = _refetch(seeded, first["event_id"])
    after_second = _refetch(seeded, second["event_id"])
    merged = (
        after_first["canonical_event_id"] == second["event_id"]
        or after_second["canonical_event_id"] == first["event_id"]
    )
    assert merged, "the two same-venue-alias candidates were not auto-merged"


def test_provenance_survives_the_merge_neither_row_is_deleted(seeded, unique):
    from datetime import date

    first = normalization.normalize_candidate(seeded, _candidate(unique, venue="PISTA"))
    second = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}2"),
                            source_url=f"https://example.test/{unique}-b", venue="피스타"),
    )
    duplicates.scan(seeded, on=date(2026, 9, 6))
    provenance = duplicates.sources_of(seeded, first["event_id"])
    ids = {row["event_id"] for row in provenance}
    assert first["event_id"] in ids and second["event_id"] in ids


def test_a_venue_with_no_alias_is_not_falsely_merged(seeded, unique):
    """Two events at genuinely different, unaliased venues on the same day
    and time must NOT merge - proves the seed narrows matching, it doesn't
    widen it into a fuzzy one. Scoped to this test's own pair, since the
    same real calendar date may carry unrelated production events."""
    from datetime import date

    first = normalization.normalize_candidate(seeded, _candidate(unique, venue="PISTA"))
    second = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}3"),
                            source_url=f"https://example.test/{unique}-c",
                            venue="난생처음보는장소"),
    )
    duplicates.scan(seeded, on=date(2026, 9, 6))
    after_first = _refetch(seeded, first["event_id"])
    after_second = _refetch(seeded, second["event_id"])
    assert after_first["canonical_event_id"] != second["event_id"]
    assert after_second["canonical_event_id"] != first["event_id"]
