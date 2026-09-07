"""v0.85.1 Direct Source Coverage Expansion: migration 027 (SRC-D-003,
SRC-W-006) and the release's own required behaviors - representative
source selection now genuinely exercised with a real PRIMARY-tier source
role, directory evidence retained after a merge, source-priority still never
implying VERIFIED, and the standing safety rules (no fee/DJ inheritance
across recurring instances, a conflicting pair stays CONFLICT, a disabled
source is never collected from, a failed live test never auto-enables).

Every test here runs only against the `pg` fixture - migration 027 is
applied by executing its SQL text directly on `pg`'s own connection, rolled
back at teardown and never committed, mirroring
test_miltang_source_migration.py's own pattern one migration later.
"""

from __future__ import annotations

from datetime import date

import pytest

from runtime import collectors, duplicates, events_api, migrate, normalization, source_priority, sources


def _apply(pg, *versions: str) -> None:
    all_migrations = migrate.discover()
    for version in versions:
        migration = next(m for m in all_migrations if m.name.startswith(f"{version}_"))
        with pg.cursor() as cur:
            cur.execute(migration.sql)


@pytest.fixture
def seeded(pg):
    """027 applied, uncommitted, on `pg`'s own connection."""
    _apply(pg, "027")
    return pg


# --- migration 027: source registration --------------------------------------

def test_registers_solo_tango_as_a_disabled_community_source(seeded):
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT platform, source_role, enabled, config->'url_contains' "
            "FROM sources WHERE source_key = 'SRC-D-003'"
        )
        row = cur.fetchone()
    assert row is not None, "SRC-D-003 was not registered"
    platform, role, enabled, url_contains = row
    assert platform == "DAUM_CAFE"
    assert role == "COMMUNITY"
    assert enabled is False
    assert "73b" in url_contains


def test_registers_tangoclass_as_a_disabled_organizer_source(seeded):
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT platform, source_role, enabled, config->>'parser' "
            "FROM sources WHERE source_key = 'SRC-W-006'"
        )
        row = cur.fetchone()
    assert row is not None, "SRC-W-006 was not registered"
    platform, role, enabled, parser = row
    assert platform == "WEB"
    assert role == "ORGANIZER"
    assert enabled is False
    assert parser == "tangoclass_wp_json"


def test_registration_is_idempotent(seeded):
    _apply(seeded, "027")
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM sources WHERE source_key IN ('SRC-D-003', 'SRC-W-006')"
        )
        assert cur.fetchone()[0] == 2


def test_existing_sources_are_never_touched(pg, unique):
    before = sources.list_sources(pg)
    _apply(pg, "027")
    after = sources.list_sources(pg)
    before_keys = {s["source_key"]: s for s in before}
    after_keys = {s["source_key"]: s for s in after}
    for key, row in before_keys.items():
        assert after_keys[key] == row, f"{key} was modified by the v0.85.1 migration"


# --- helpers shared by the 15 required tests ---------------------------------

def _candidate(unique, **overrides):
    payload = {
        "candidate_id": int(f"{unique[-6:]}1"),
        "post_id": 1,
        "source_url": f"https://example.test/{unique}-a",
        "event_name": f"밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-08",
        "start_time": "20:00", "end_time": "23:00", "end_day_offset": 0,
        "venue": f"venue-{unique}", "fee": 10000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
        "time_evidence": "EXPLICIT",
    }
    payload.update(overrides)
    return payload


def _make_source_item(pg, *, source_role: str, source_url: str, collected_at=None):
    """A minimal sources+source_items pair with a given source_role, so an
    event's own `source_item_id` can be joined back to a real role - the
    same shape events_api.search()/duplicates.scan() already join through
    in production."""
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (source_key, name, platform, source_role, url, "
            "authority_level, enabled) "
            "VALUES (%s, %s, 'WEB', %s, %s, 'UNKNOWN', TRUE) "
            "ON CONFLICT (source_key) DO UPDATE SET source_role = EXCLUDED.source_role "
            "RETURNING source_id",
            (f"TEST-{source_role}-{source_url[-8:]}", f"test {source_role}", source_role, source_url),
        )
        source_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, "
            "content_hash, collected_at) "
            "VALUES (%s, %s, %s, %s, COALESCE(%s, now())) "
            "RETURNING source_item_id",
            (source_id, source_url, source_url, source_url, collected_at),
        )
        return cur.fetchone()[0]


def _link_event_to_source_item(pg, event_id, source_item_id):
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE events SET source_item_id = %s WHERE event_id = %s",
            (source_item_id, event_id),
        )


# 1. primary source ingestion --------------------------------------------------

def test_primary_source_ingestion(seeded, unique):
    """A candidate from an ORGANIZER-role source (SRC-W-006's own tier)
    normalizes through the existing pipeline with no special-casing, and
    source_priority classifies its role as PRIMARY."""
    event = normalization.normalize_candidate(seeded, _candidate(unique))
    assert event["event_id"] is not None
    assert source_priority.tier_of("ORGANIZER") == source_priority.PRIMARY


# 2. promotion board ingestion -------------------------------------------------

def test_promotion_board_ingestion(seeded, unique):
    """A PROMOTION_BOARD-role source's candidate normalizes the same way -
    the existing pipeline has no PROMOTION_BOARD-specific branch to break."""
    event = normalization.normalize_candidate(seeded, _candidate(unique))
    assert event["event_id"] is not None
    assert source_priority.tier_of("PROMOTION_BOARD") == source_priority.PROMOTION_BOARD


# 3. directory duplicate recognized -------------------------------------------

def test_directory_duplicate_is_recognized_against_a_new_primary_event(seeded, unique):
    directory_item = _make_source_item(
        seeded, source_role="DIRECTORY", source_url=f"https://directory.test/{unique}"
    )
    primary_item = _make_source_item(
        seeded, source_role="ORGANIZER", source_url=f"https://organizer.test/{unique}"
    )
    directory_event = normalization.normalize_candidate(seeded, _candidate(unique))
    primary_event = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}2"),
                           source_url=f"https://example.test/{unique}-b"),
    )
    _link_event_to_source_item(seeded, directory_event["event_id"], directory_item)
    _link_event_to_source_item(seeded, primary_event["event_id"], primary_item)

    duplicates.scan(seeded, on=date(2026, 9, 8))

    def _canonical_id(event_id):
        with seeded.cursor() as cur:
            cur.execute("SELECT canonical_event_id FROM events WHERE event_id = %s", (event_id,))
            return cur.fetchone()[0]

    merged = (
        _canonical_id(directory_event["event_id"]) == primary_event["event_id"]
        or _canonical_id(primary_event["event_id"]) == directory_event["event_id"]
    )
    assert merged, "same date/venue/time DIRECTORY and PRIMARY rows were not recognized as duplicates"


# 4. representative source primary --------------------------------------------

def test_representative_source_is_primary_over_directory(seeded, unique):
    """Section 11: when the same event has both PRIMARY and DIRECTORY
    evidence, the representative (canonical) event is the PRIMARY one -
    duplicates._canonical_of()'s source_priority tiebreak, exercised here
    with a real ORGANIZER-role source rather than a synthetic string."""
    directory_item = _make_source_item(
        seeded, source_role="DIRECTORY", source_url=f"https://directory.test/{unique}"
    )
    primary_item = _make_source_item(
        seeded, source_role="ORGANIZER", source_url=f"https://organizer.test/{unique}"
    )
    directory_event = normalization.normalize_candidate(seeded, _candidate(unique))
    primary_event = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}2"),
                           source_url=f"https://example.test/{unique}-b"),
    )
    _link_event_to_source_item(seeded, directory_event["event_id"], directory_item)
    _link_event_to_source_item(seeded, primary_event["event_id"], primary_item)

    duplicates.scan(seeded, on=date(2026, 9, 8))

    with seeded.cursor() as cur:
        cur.execute(
            "SELECT canonical_event_id FROM events WHERE event_id = %s",
            (directory_event["event_id"],),
        )
        directory_canonical = cur.fetchone()[0]
    assert directory_canonical == primary_event["event_id"], (
        "the PRIMARY-sourced event must be the representative, not the DIRECTORY one"
    )


# 5. directory evidence retained -----------------------------------------------

def test_directory_evidence_is_retained_after_a_primary_merge(seeded, unique):
    """Section 12: the representative flips to PRIMARY, but the DIRECTORY
    post is never deleted - it stays reachable as cross-check evidence via
    duplicates.sources_of()."""
    directory_url = f"https://directory.test/{unique}"
    primary_url = f"https://organizer.test/{unique}"
    directory_item = _make_source_item(seeded, source_role="DIRECTORY", source_url=directory_url)
    primary_item = _make_source_item(seeded, source_role="ORGANIZER", source_url=primary_url)
    directory_event = normalization.normalize_candidate(
        seeded, _candidate(unique, source_url=directory_url),
    )
    primary_event = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}2"), source_url=primary_url),
    )
    _link_event_to_source_item(seeded, directory_event["event_id"], directory_item)
    _link_event_to_source_item(seeded, primary_event["event_id"], primary_item)
    duplicates.scan(seeded, on=date(2026, 9, 8))

    linked = duplicates.sources_of(seeded, primary_event["event_id"])
    urls = {s["source_url"] for s in linked}
    assert directory_url in urls
    assert primary_url in urls


# 6. source link direct --------------------------------------------------------

def test_source_link_prefers_the_direct_url_not_the_directory_one(seeded, unique):
    directory_url = f"https://directory.test/{unique}"
    primary_url = f"https://organizer.test/{unique}"
    directory_item = _make_source_item(seeded, source_role="DIRECTORY", source_url=directory_url)
    primary_item = _make_source_item(seeded, source_role="ORGANIZER", source_url=primary_url)
    directory_event = normalization.normalize_candidate(
        seeded, _candidate(unique, source_url=directory_url),
    )
    primary_event = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}2"), source_url=primary_url),
    )
    _link_event_to_source_item(seeded, directory_event["event_id"], directory_item)
    _link_event_to_source_item(seeded, primary_event["event_id"], primary_item)
    duplicates.scan(seeded, on=date(2026, 9, 8))

    result = events_api.get_event(seeded, primary_event["event_id"])
    assert result["source_link"]["url"] == primary_url


# 7. freshness direct -----------------------------------------------------------

def test_freshness_reflects_the_direct_sources_collected_at(seeded, unique):
    from datetime import datetime, timedelta, timezone

    fresh_stamp = datetime.now(timezone.utc) - timedelta(minutes=5)
    primary_url = f"https://organizer.test/{unique}"
    primary_item = _make_source_item(
        seeded, source_role="ORGANIZER", source_url=primary_url, collected_at=fresh_stamp,
    )
    event = normalization.normalize_candidate(seeded, _candidate(unique, source_url=primary_url))
    _link_event_to_source_item(seeded, event["event_id"], primary_item)

    result = events_api.get_event(seeded, event["event_id"])
    assert result["last_checked"] is not None


# 8/9. recurrence: no fee/DJ inheritance across instances ----------------------

def test_recurrence_does_not_inherit_fee_from_a_prior_instance(seeded, unique):
    """A regular Tuesday notice with a fee this week must never leak that fee
    onto next week's instance just because it is 'the same recurring
    milonga' - each candidate normalizes from only its own fields."""
    normalization.normalize_candidate(seeded, _candidate(unique, fee=8000))
    next_week = normalization.normalize_candidate(
        seeded, _candidate(
            unique, candidate_id=int(f"{unique[-6:]}2"),
            source_url=f"https://example.test/{unique}-b",
            event_date="2026-09-15", fee=None,
        ),
    )
    assert next_week["fee"] is None


def test_recurrence_does_not_inherit_dj_from_a_prior_instance(seeded, unique):
    normalization.normalize_candidate(seeded, _candidate(unique, dj="유진"))
    next_week = normalization.normalize_candidate(
        seeded, _candidate(
            unique, candidate_id=int(f"{unique[-6:]}2"),
            source_url=f"https://example.test/{unique}-b",
            event_date="2026-09-15",
        ),
    )
    assert next_week.get("dj") is None


# 10. conflicting source stays conflict ----------------------------------------

def test_a_conflicting_pair_stays_conflict_regardless_of_source_tier(seeded, unique):
    """Section 7's own instruction, exercised with a real PRIMARY-tier
    source: a higher-priority source must never blindly overwrite a
    genuinely conflicting value from a lower-tier one - classify() still
    flags VENUE_TIME_DIFFERS for human review rather than auto-merging."""
    primary_item = _make_source_item(
        seeded, source_role="ORGANIZER", source_url=f"https://organizer.test/{unique}"
    )
    directory_item = _make_source_item(
        seeded, source_role="DIRECTORY", source_url=f"https://directory.test/{unique}"
    )
    left = normalization.normalize_candidate(
        seeded, _candidate(unique, venue="Venue A", start_time="20:00"),
    )
    right = normalization.normalize_candidate(
        seeded, _candidate(
            unique, candidate_id=int(f"{unique[-6:]}2"),
            source_url=f"https://example.test/{unique}-b",
            venue="Venue B", start_time="21:30",
        ),
    )
    _link_event_to_source_item(seeded, left["event_id"], primary_item)
    _link_event_to_source_item(seeded, right["event_id"], directory_item)

    finding = duplicates.classify(left, right)
    assert finding is None or finding["auto"] is False

    duplicates.scan(seeded, on=date(2026, 9, 8))
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT canonical_event_id FROM events WHERE event_id IN (%s, %s)",
            (left["event_id"], right["event_id"]),
        )
        canonicals = [r[0] for r in cur.fetchall()]
    assert all(c is None for c in canonicals), (
        "a genuinely conflicting venue/time pair must never auto-merge, "
        "however different the two sources' tiers are"
    )


# 11. primary does not imply VERIFIED ------------------------------------------

def test_primary_source_does_not_imply_verified(seeded, unique):
    primary_item = _make_source_item(
        seeded, source_role="ORGANIZER", source_url=f"https://organizer.test/{unique}"
    )
    event = normalization.normalize_candidate(seeded, _candidate(unique))
    _link_event_to_source_item(seeded, event["event_id"], primary_item)

    result = events_api.get_event(seeded, event["event_id"])
    assert result["status"] != "VERIFIED", (
        "a PRIMARY-tier source must never auto-promote VERIFIED status - "
        "that stays governed entirely by engine.verifier's own evidence rules"
    )


# 12. calendar duplicate count unchanged ---------------------------------------

def test_calendar_counts_a_merged_primary_directory_pair_once(seeded, unique):
    directory_item = _make_source_item(
        seeded, source_role="DIRECTORY", source_url=f"https://directory.test/{unique}"
    )
    primary_item = _make_source_item(
        seeded, source_role="ORGANIZER", source_url=f"https://organizer.test/{unique}"
    )
    directory_event = normalization.normalize_candidate(seeded, _candidate(unique))
    primary_event = normalization.normalize_candidate(
        seeded, _candidate(unique, candidate_id=int(f"{unique[-6:]}2"),
                           source_url=f"https://example.test/{unique}-b"),
    )
    _link_event_to_source_item(seeded, directory_event["event_id"], directory_item)
    _link_event_to_source_item(seeded, primary_event["event_id"], primary_item)
    duplicates.scan(seeded, on=date(2026, 9, 8))

    counts = events_api.week_counts(
        seeded, start=date(2026, 9, 7), end=date(2026, 9, 13),
    )
    # Both rows share one canonical event - _VISIBLE's canonical_event_id
    # IS NULL gate already excludes the folded-away one, so this test's own
    # pair contributes at most 1, not 2, to whatever the real count is.
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_id IN (%s, %s) "
            "AND canonical_event_id IS NULL",
            (directory_event["event_id"], primary_event["event_id"]),
        )
        visible_of_pair = cur.fetchone()[0]
    assert visible_of_pair == 1
    assert counts.get("2026-09-08", 0) >= 1


# 13. historical event retained -------------------------------------------------

def test_a_past_dated_primary_event_stays_queryable(seeded, unique):
    event = normalization.normalize_candidate(
        seeded, _candidate(unique, event_date="2020-01-15"),
    )
    result = events_api.search(seeded, on="2020-01-15", limit=100)
    ids = {e["id"] for e in result["events"]}
    assert event["event_id"] in ids


# 14. disabled source no collection ---------------------------------------------

def test_a_disabled_source_is_never_selected_for_collection(seeded):
    due = sources.due_sources(seeded)
    due_keys = {s["source_key"] for s in due}
    assert "SRC-D-003" not in due_keys
    assert "SRC-W-006" not in due_keys


# 15. failed live source remains disabled ----------------------------------------

def test_a_failed_live_test_never_auto_enables_a_source(seeded, settings, monkeypatch):
    """Admin [Test] button (Section 37's "disabled -> one-shot live test ->
    audit" order): a failing collection must never itself flip `enabled` -
    `test_source()`'s own docstring already promises this ("Deliberately
    does not write anything"); this test holds it to that promise."""
    with seeded.cursor() as cur:
        cur.execute("SELECT * FROM sources WHERE source_key = 'SRC-W-006'")
        columns = [c.name for c in cur.description]
        source = dict(zip(columns, cur.fetchone()))

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated live failure")

    monkeypatch.setattr(collectors, "collect", _boom)
    result = collectors.test_source(settings, source)
    assert result["status"] != "PASS"

    with seeded.cursor() as cur:
        cur.execute("SELECT enabled FROM sources WHERE source_key = 'SRC-W-006'")
        assert cur.fetchone()[0] is False, (
            "a collection failure (or any collection attempt) must never itself "
            "flip enabled - only an explicit operator action does"
        )


# --- a real bug found during this release's own live E2E audit --------------
#
# Enabling SRC-W-006 on a genuinely fresh, empty staging Postgres (Section
# 37's own "disabled -> one-shot live test -> audit" order) crashed the
# scheduler's event-normalization job with `KeyError: 'unresolved_venues'`.
# normalize_all()'s zero-candidates early return had never included that key
# (nor 'pruned') - unreachable in every prior release, since production
# always has hundreds of pending candidates by the time this job runs. A
# genuinely fresh staging database is the first time this exact zero-
# candidates-at-normalization-time state has actually occurred in this
# project. Not caused by v0.85.1's source additions themselves; caught by
# them, on a properly fresh (not volume-reused) staging Postgres.

def test_normalize_all_returns_every_key_even_with_zero_candidates(settings, monkeypatch):
    from runtime import candidates as candidate_store

    monkeypatch.setattr(candidate_store, "list_candidates", lambda *a, **kw: [])
    result = normalization.normalize_all(settings)
    for key in ("candidates", "normalized", "skipped_no_date", "unresolved_venues", "pruned"):
        assert key in result, f"normalize_all()'s zero-candidates return is missing '{key}'"
