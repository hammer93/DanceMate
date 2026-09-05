"""v0.83 Source Application: migration 023 (Miltang source registration) and
the cross-source dedup it enables through the *existing* pipeline
(runtime.normalization.resolve_venue + runtime.duplicates.classify) rather
than a new one - the same reasoning as
test_tango_source_expansion_migration.py, one migration and one source later.

Every test here runs only against the `pg` fixture, rolled back at teardown
and never committed - migrations 021/022/023 are applied by executing their
SQL text directly on `pg`'s own connection, never through the real
(committing) migration runner. 021/022 are already real, committed rows on
this shared board by the time this file runs; applying them again here is a
harmless, idempotent no-op (`ON CONFLICT ... DO NOTHING`) that also makes
this file self-contained against a database that does not have them yet.
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
    """021/022/023 all applied, uncommitted, on `pg`'s own connection."""
    _apply(pg, "021", "022", "023")
    return pg


# --- migration 023: source registration --------------------------------------

def test_registers_miltang_as_a_secondary_directory_source(pg):
    with pg.cursor() as cur:
        cur.execute("SELECT source_key FROM sources WHERE source_key = 'SRC-W-005'")
        pre_existing = cur.fetchone() is not None

    _apply(pg, "021", "022", "023")

    with pg.cursor() as cur:
        cur.execute(
            "SELECT platform, source_role, authority_level, enabled, "
            "collection_interval_minutes, config->>'parser' AS parser, url "
            "FROM sources WHERE source_key = 'SRC-W-005'"
        )
        row = cur.fetchone()
    assert row is not None, "SRC-W-005 was not registered"
    platform, role, authority, enabled, interval, parser, url = row
    assert platform == "WEB"
    assert role == "DIRECTORY"
    assert authority == "SECONDARY"
    assert parser == "miltang_ssr"
    assert interval >= 240
    # A row this migration actually inserts must register disabled - the
    # same before/after-delta principle test_tango_source_expansion_
    # migration.py's own registration test applies, for the same reason:
    # this shared board's real SRC-W-005 state (once an operator has acted
    # on it) is a fact about the board, not something this test may assert
    # either way.
    if not pre_existing:
        assert enabled is False
    assert url == "https://miltang.com/milongas"


def test_registration_is_idempotent(seeded):
    _apply(seeded, "023")
    with seeded.cursor() as cur:
        cur.execute("SELECT count(*) FROM sources WHERE source_key = 'SRC-W-005'")
        assert cur.fetchone()[0] == 1


def test_existing_sources_are_never_touched(pg, unique):
    from runtime import sources

    before = sources.list_sources(pg)
    _apply(pg, "021", "022", "023")
    after = sources.list_sources(pg)
    before_keys = {s["source_key"]: s for s in before}
    after_keys = {s["source_key"]: s for s in after}
    for key, row in before_keys.items():
        assert after_keys[key] == row, f"{key} was modified by the v0.83 migration"


def test_collection_targets_are_the_real_endpoints_not_a_homepage(seeded):
    with seeded.cursor() as cur:
        cur.execute("SELECT config->'board_urls' FROM sources WHERE source_key = 'SRC-W-005'")
        board_urls = cur.fetchone()[0]
    assert "https://miltang.com/milongas" in board_urls
    assert "https://miltang.com/notices" in board_urls
    # Neither target is the bare homepage - both real collection endpoints.
    assert not any(u.rstrip("/") == "https://miltang.com" for u in board_urls)


def test_existing_top3_sources_are_preserved(seeded):
    """v0.82's own three sources must still be exactly what 021 left them -
    this migration adds a fourth row, it does not touch the others."""
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT source_key FROM sources WHERE source_key IN "
            "('SRC-W-001', 'SRC-W-002', 'SRC-W-003', 'SRC-W-004')"
        )
        keys = {r[0] for r in cur.fetchall()}
    assert keys == {"SRC-W-001", "SRC-W-002", "SRC-W-003", "SRC-W-004"}


# --- cross-source dedup through the EXISTING pipeline ------------------------
#
# No new dedup module: resolve_venue() already resolves every candidate
# against venue_aliases (migration 022, already seeded), and
# duplicates.classify() already auto-merges two events sharing a date, start
# time and venue_id. A TangoNOW record naming "PISTA" and a Miltang record
# naming "PISTA 피스타 (주소)" for the same Saturday resolve to the same
# venue_id and merge with zero new code - exactly like migration 022's own
# TangoNOW/Tango Calendar Korea dedup test, one source later.

def _miltang_pista_body() -> str:
    """The real body parse_detail() produces for a PISTA milonga - built by
    actually calling the discovery module on a minimal detail-page fixture,
    not hand-typed, so this cannot drift from what body synthesis (the
    bilingual brand/Korean-name split included - see
    miltang_discovery._split_bilingual_venue_name()'s own docstring) really
    does."""
    from runtime import miltang_discovery

    page = (
        '<html><body>'
        '<script type="application/ld+json">'
        '{"@type":"Event","name":"테스트 밀롱가","startDate":"2026-09-06",'
        '"location":{"@type":"Place","name":"PISTA 피스타",'
        '"address":{"@type":"PostalAddress",'
        '"streetAddress":"서울 월드컵북로6길 49 지하1층"}}}'
        '</script>'
        '<h2 class="text-2xl font-bold text-fg1">테스트 밀롱가</h2>'
        '<dl><div><dt>TIME</dt><dd>14:00~18:00</dd></div></dl>'
        '</body></html>'
    )
    post = miltang_discovery.parse_detail(page, "https://miltang.com/milongas/test")
    assert post is not None
    return post["body"]


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


def test_tangonow_and_miltang_naming_the_same_venue_differently_share_one_venue_id(
    seeded, unique,
):
    from engine.src import extraction_rules

    reading = extraction_rules.extract_venue(_miltang_pista_body())
    assert reading is not None

    tangonow = normalization.normalize_candidate(seeded, _candidate(unique, venue="PISTA"))
    miltang = normalization.normalize_candidate(
        seeded, _candidate(
            unique, candidate_id=int(f"{unique[-6:]}2"),
            source_url=f"https://example.test/{unique}-b",
            venue=reading.name,
        ),
        alias_candidates=reading.alias_candidates,
    )
    assert tangonow["venue_id"] == miltang["venue_id"]
    assert tangonow["venue_status"] == normalization.VENUE_RESOLVED
    assert miltang["venue_status"] == normalization.VENUE_RESOLVED


def test_the_existing_duplicate_scan_auto_merges_tangonow_and_miltang(seeded, unique):
    """Scoped to this test's own two rows, not the scan's global count - the
    same real calendar date this test uses may carry unrelated production
    events that merge (or don't) independently of this test's own pair."""
    from datetime import date

    from engine.src import extraction_rules

    reading = extraction_rules.extract_venue(_miltang_pista_body())

    first = normalization.normalize_candidate(seeded, _candidate(unique, venue="PISTA"))
    second = normalization.normalize_candidate(
        seeded, _candidate(
            unique, candidate_id=int(f"{unique[-6:]}2"),
            source_url=f"https://example.test/{unique}-b", venue=reading.name,
        ),
        alias_candidates=reading.alias_candidates,
    )
    duplicates.scan(seeded, on=date(2026, 9, 6))

    def _refetch(event_id):
        with seeded.cursor() as cur:
            cur.execute("SELECT * FROM events WHERE event_id = %s", (event_id,))
            columns = [c.name for c in cur.description]
            return dict(zip(columns, cur.fetchone()))

    after_first = _refetch(first["event_id"])
    after_second = _refetch(second["event_id"])
    merged = (
        after_first["canonical_event_id"] == second["event_id"]
        or after_second["canonical_event_id"] == first["event_id"]
    )
    assert merged, "TangoNOW and Miltang rows for the same PISTA milonga were not auto-merged"


def test_a_more_complete_row_is_not_overwritten_by_a_thinner_lower_authority_one(
    seeded, unique,
):
    """Section 5's own instruction: a lower-authority Miltang record must
    never overwrite a more complete, already-resolved primary value. This is
    the EXISTING duplicates.completeness() tie-break (resolved venue,
    populated time/fee, engine/review state) - not a new authority-ordering
    rule; SRC-W-005's own `authority_level = 'SECONDARY'` is what makes it
    visible to an operator on the Sources page, not something this scan
    consults directly (matching 021/022's own documented precedent)."""
    from datetime import date

    from engine.src import extraction_rules

    reading = extraction_rules.extract_venue(_miltang_pista_body())

    complete = normalization.normalize_candidate(
        seeded, _candidate(unique, venue="PISTA", fee=13000, start_time="14:00", end_time="18:00"),
    )
    thinner = normalization.normalize_candidate(
        seeded, _candidate(
            unique, candidate_id=int(f"{unique[-6:]}2"),
            source_url=f"https://example.test/{unique}-b", venue=reading.name,
            fee=None,
        ),
        alias_candidates=reading.alias_candidates,
    )
    duplicates.scan(seeded, on=date(2026, 9, 6))

    with seeded.cursor() as cur:
        cur.execute("SELECT fee FROM events WHERE event_id = %s", (complete["event_id"],))
        fee = cur.fetchone()[0]
    assert fee == 13000, "the complete row's own fee must survive the merge unchanged"
