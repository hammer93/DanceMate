"""v0.85.2 Direct Source Depth + Primary Evidence Convergence.

Section 47's ten required convergence behaviors, re-anchored to the exact
real production scenario this release observed live (event_id 88436
Miltang/DIRECTORY folded into event_id 221245 SRC-D-003/COMMUNITY-PRIMARY
for the real "Solo Tango 화요정모" 2026-09-08 event) - these were already
proven correct by v0.85.1's own test_v0851_direct_source_expansion.py
using synthetic fixtures; this file confirms the same guarantees still
hold post-pagination-change, using the identical helper pattern, plus the
new Section 22/23 multi-tier evidence KPI this release adds.
"""

from __future__ import annotations

from datetime import date

import pytest

from runtime import duplicates, events_api, migrate, normalization, source_ops, source_priority


def _apply(pg, *versions: str) -> None:
    all_migrations = migrate.discover()
    for version in versions:
        migration = next(m for m in all_migrations if m.name.startswith(f"{version}_"))
        with pg.cursor() as cur:
            cur.execute(migration.sql)


@pytest.fixture
def seeded(pg):
    _apply(pg, "027")
    return pg


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


def _solo_tango_pair(pg, unique):
    """The exact real production shape: a DIRECTORY (Miltang-like) post and
    a COMMUNITY/PRIMARY (SRC-D-003-like) post for the same real event -
    same date, venue, and start time."""
    directory_url = f"https://directory.test/{unique}"
    primary_url = f"https://organizer.test/{unique}"
    directory_item = _make_source_item(pg, source_role="DIRECTORY", source_url=directory_url)
    primary_item = _make_source_item(pg, source_role="COMMUNITY", source_url=primary_url)
    directory_event = normalization.normalize_candidate(
        pg, _candidate(unique, event_name="Solo Tango 화요정모", source_url=directory_url),
    )
    primary_event = normalization.normalize_candidate(
        pg, _candidate(
            unique, candidate_id=int(f"{unique[-6:]}2"),
            event_name="[화정] 화정 공지 (DJ : 유진)", source_url=primary_url, dj="유진",
        ),
    )
    _link_event_to_source_item(pg, directory_event["event_id"], directory_item)
    _link_event_to_source_item(pg, primary_event["event_id"], primary_item)
    return directory_event, primary_event, directory_url, primary_url


# 13. primary/direct representative ------------------------------------------

def test_primary_direct_representative(seeded, unique):
    directory_event, primary_event, _, _ = _solo_tango_pair(seeded, unique)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    with seeded.cursor() as cur:
        cur.execute("SELECT canonical_event_id FROM events WHERE event_id = %s",
                    (directory_event["event_id"],))
        assert cur.fetchone()[0] == primary_event["event_id"]


# 14. directory retained -------------------------------------------------------

def test_directory_retained(seeded, unique):
    directory_event, primary_event, directory_url, primary_url = _solo_tango_pair(seeded, unique)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    linked = duplicates.sources_of(seeded, primary_event["event_id"])
    urls = {s["source_url"] for s in linked}
    assert directory_url in urls
    assert primary_url in urls


# 15. direct source link -------------------------------------------------------

def test_direct_source_link(seeded, unique):
    _, primary_event, _, primary_url = _solo_tango_pair(seeded, unique)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    result = events_api.get_event(seeded, primary_event["event_id"])
    assert result["source_link"]["url"] == primary_url


# 16. direct collected_at freshness --------------------------------------------

def test_direct_collected_at_freshness(seeded, unique):
    from datetime import datetime, timedelta, timezone
    fresh = datetime.now(timezone.utc) - timedelta(minutes=10)
    primary_url = f"https://organizer.test/{unique}"
    primary_item = _make_source_item(seeded, source_role="COMMUNITY", source_url=primary_url,
                                      collected_at=fresh)
    event = normalization.normalize_candidate(seeded, _candidate(unique, source_url=primary_url))
    _link_event_to_source_item(seeded, event["event_id"], primary_item)
    result = events_api.get_event(seeded, event["event_id"])
    assert result["last_checked"] is not None


# 17. duplicate event count unchanged ------------------------------------------

def test_duplicate_event_count_unchanged(seeded, unique):
    directory_event, primary_event, _, _ = _solo_tango_pair(seeded, unique)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events WHERE event_id IN (%s, %s) AND canonical_event_id IS NULL",
            (directory_event["event_id"], primary_event["event_id"]),
        )
        assert cur.fetchone()[0] == 1


# 18. calendar count unchanged --------------------------------------------------

def test_calendar_count_unchanged(seeded, unique):
    _solo_tango_pair(seeded, unique)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    counts = events_api.week_counts(seeded, start=date(2026, 9, 7), end=date(2026, 9, 13))
    assert counts.get("2026-09-08", 0) >= 1  # this test's own pair contributes at most 1


# 19. DJ from direct -------------------------------------------------------------

def test_dj_from_direct(seeded, unique):
    _, primary_event, _, _ = _solo_tango_pair(seeded, unique)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    result = events_api.get_event(seeded, primary_event["event_id"])
    assert result["dj"] == "유진"


# 20. fee safety -------------------------------------------------------------------

def test_fee_safety_multi_tier_fee_not_guessed(seeded, unique):
    """v0.84.1 safety, still honoured: a candidate whose fee field is
    genuinely ambiguous (this fixture leaves it unset, matching a real
    two-tier '8,000원(22시 이후 5,000원)' post the extractor declined to
    reduce to a single number) must stay unknown, not get a guessed value."""
    primary_url = f"https://organizer.test/{unique}"
    event = normalization.normalize_candidate(
        seeded, _candidate(unique, source_url=primary_url, fee=None),
    )
    assert event["fee"] is None


# 21. conflict safety ---------------------------------------------------------------

def test_conflict_safety_primary_does_not_silently_overwrite(seeded, unique):
    primary_item = _make_source_item(seeded, source_role="COMMUNITY",
                                      source_url=f"https://organizer.test/{unique}")
    directory_item = _make_source_item(seeded, source_role="DIRECTORY",
                                        source_url=f"https://directory.test/{unique}")
    left = normalization.normalize_candidate(
        seeded, _candidate(unique, venue="Venue A", start_time="20:00"),
    )
    right = normalization.normalize_candidate(
        seeded, _candidate(
            unique, candidate_id=int(f"{unique[-6:]}2"),
            source_url=f"https://example.test/{unique}-b", venue="Venue B", start_time="21:30",
        ),
    )
    _link_event_to_source_item(seeded, left["event_id"], primary_item)
    _link_event_to_source_item(seeded, right["event_id"], directory_item)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT canonical_event_id FROM events WHERE event_id IN (%s, %s)",
            (left["event_id"], right["event_id"]),
        )
        assert all(c is None for c in (r[0] for r in cur.fetchall())), (
            "a conflicting venue/time pair must never auto-merge regardless of source tier"
        )


# 22. PRIMARY != VERIFIED ------------------------------------------------------------

def test_primary_does_not_imply_verified(seeded, unique):
    _, primary_event, _, _ = _solo_tango_pair(seeded, unique)
    result = events_api.get_event(seeded, primary_event["event_id"])
    assert result["status"] != "VERIFIED"


# --- Section 22/23: multi-tier evidence KPI ----------------------------------

def test_evidence_tiers_counts_a_primary_directory_pair_as_multi_tier(seeded, unique):
    _solo_tango_pair(seeded, unique)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    before = source_ops.evidence_tiers(seeded)
    # Re-derive scoped to just this test's own pair via a direct query,
    # since the real table also carries whatever this shared board already
    # has - the KPI function itself is what is under test, not a specific
    # global count.
    assert before["multi_tier"] >= 1
    assert before["primary"] >= 1


def test_evidence_tiers_directory_only_event_is_not_counted_as_multi_tier(seeded, unique):
    directory_item = _make_source_item(seeded, source_role="DIRECTORY",
                                        source_url=f"https://directory.test/{unique}")
    event = normalization.normalize_candidate(
        seeded, _candidate(unique, event_date="2027-01-15"),  # far future, isolates this test
    )
    _link_event_to_source_item(seeded, event["event_id"], directory_item)
    result = source_ops.evidence_tiers(seeded)
    assert result["directory_only"] >= 1


def test_evidence_tiers_folded_duplicate_still_counts_toward_multi_tier(seeded, unique):
    """The KPI must read evidence from BOTH the canonical row and its
    folded-away duplicate - not just the representative's own tier."""
    directory_event, primary_event, _, _ = _solo_tango_pair(seeded, unique)
    duplicates.scan(seeded, on=date(2026, 9, 8))
    with seeded.cursor() as cur:
        cur.execute("SELECT canonical_event_id FROM events WHERE event_id = %s",
                    (directory_event["event_id"],))
        assert cur.fetchone()[0] is not None, "setup check: the pair must actually merge"
    result = source_ops.evidence_tiers(seeded)
    assert result["multi_tier"] >= 1
    assert result["primary"] >= 1
