"""v0.85.6 Human Venue Verification + Safe Address Completion.

15 required tests (Section 35). This release writes no new runtime code -
it uses venue_resolution.py's existing safe Human Venue Review workflow,
gated behind an explicit human decision (김프로's actual answers for CLUB
PAN TANGO/강남탱고 판 and 실루엣 분당정자동) rather than any automated
confidence score. These tests characterize that gate: nothing is ever
written without a human-provided venue_id/address, unrelated venues stay
untouched, and the same v0.85.4/v0.85.5 regressions (formatter, source
link, calendar identity) still hold against the new real values.
"""

from __future__ import annotations

import pytest

from runtime import events_api, master_data, normalization, public, venue_resolution


def _candidate(unique: str, suffix: str = "1", **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/venue/{unique}-{suffix}",
        "event_name": f"장소 테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"테스트홀 {unique}",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    base.update(overrides)
    return base


def _queued(con, venue_text: str) -> dict:
    return next(v for v in normalization.unresolved_venues(con)
                if v["venue_text"] == venue_text)


def _make_source_item(pg, *, unique: str, suffix: str):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (source_key, name, platform, source_role, url, "
            "authority_level, enabled) "
            "VALUES (%s, %s, 'WEB', 'DIRECTORY', %s, 'UNKNOWN', TRUE) "
            "ON CONFLICT (source_key) DO UPDATE SET source_role = EXCLUDED.source_role "
            "RETURNING source_id",
            (f"TEST-SRC-{unique}-{suffix}", f"test source {unique}-{suffix}",
             f"https://x.test/{unique}-{suffix}"),
        )
        source_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, content_hash) "
            "VALUES (%s, %s, %s, %s) RETURNING source_item_id",
            (source_id, f"ext-{unique}-{suffix}", f"https://x.test/{unique}-{suffix}",
             f"hash-{unique}-{suffix}"),
        )
        return cur.fetchone()[0]


# 1. a human-approved address is written exactly as approved - the
#    CLUB PAN TANGO shape: two raw strings, one human-confirmed identity
#    and address, merged onto one venue.
def test_human_approved_address_write(pg, unique, seoul_id):
    text_a = f"클럽테스트 {unique}"
    text_b = f"다른이름테스트 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1", venue=text_a))
    normalization.normalize_candidate(pg, _candidate(unique, "2", venue=text_b))
    entry_a = _queued(pg, text_a)
    entry_b = _queued(pg, text_b)

    approved_address = "서울 서초구 인간확인로 1"
    result = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry_a["unresolved_venue_id"],
        name=f"클럽테스트 {unique}", region_id=seoul_id, address=approved_address,
        reviewer="human-approved-tester")
    venue_resolution.link_existing(
        pg, unresolved_venue_id=entry_b["unresolved_venue_id"],
        venue_id=result["venue"]["venue_id"], reviewer="human-approved-tester")

    for text in (text_a, text_b):
        with pg.cursor() as cur:
            cur.execute(
                "SELECT venue_id FROM events WHERE lower(venue_text) = lower(%s) LIMIT 1",
                (text,))
            venue_id = cur.fetchone()[0]
        assert master_data.get_venue(pg, venue_id)["address"] == approved_address


# 2. without an approval, nothing is written - a venue that stays OPEN
#    (the KEEP_OPEN decision) keeps its events addressless.
def test_no_approval_means_no_write(pg, unique):
    venue_text = f"미승인홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    # No link_existing/create_and_link call at all - KEEP_OPEN.
    event = events_api.get_event(pg, stored["event_id"])
    assert event["venue"]["address"] is None
    assert event["venue"]["status"] == "UNRESOLVED"
    still_open = _queued(pg, venue_text)
    assert still_open["state"] == "OPEN"


# 3. link existing: a second raw string human-confirmed as the same place
#    resolves onto the already-created venue, no duplicate venue row.
def test_link_existing_to_human_confirmed_venue(pg, unique, seoul_id):
    primary_text = f"본체홀 {unique}"
    alias_text = f"별칭홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1", venue=primary_text))
    normalization.normalize_candidate(pg, _candidate(unique, "2", venue=alias_text))
    entry_primary = _queued(pg, primary_text)
    entry_alias = _queued(pg, alias_text)

    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry_primary["unresolved_venue_id"],
        name=primary_text, region_id=seoul_id, address="서울 마포구 본체로 1",
        reviewer="human-approved-tester")
    before_count = len(master_data.list_venues(pg))
    venue_resolution.link_existing(
        pg, unresolved_venue_id=entry_alias["unresolved_venue_id"],
        venue_id=created["venue"]["venue_id"], reviewer="human-approved-tester")
    assert len(master_data.list_venues(pg)) == before_count


# 4. create new: a brand new venue, human-confirmed address, the 실루엣
#    (분당정자동) shape.
def test_create_new_venue_with_human_confirmed_address(pg, unique, seoul_id):
    venue_text = f"신규확인홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    result = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"신규확인홀 (구분용) {unique}", region_id=seoul_id,
        address="경기 성남시 분당구 확인로 1", reviewer="human-approved-tester")
    assert result["venue"]["address"] == "경기 성남시 분당구 확인로 1"
    assert result["events_updated"] == 1


# 5. both raw strings a human confirms as the same place become
#    registered aliases of the one venue - the CLUB PAN TANGO / 강남탱고
#    판 shape.
def test_alias_registered_for_both_human_confirmed_names(pg, unique, seoul_id):
    text_a = f"에이명칭 {unique}"
    text_b = f"비명칭 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1", venue=text_a))
    normalization.normalize_candidate(pg, _candidate(unique, "2", venue=text_b))
    entry_a = _queued(pg, text_a)
    entry_b = _queued(pg, text_b)
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry_a["unresolved_venue_id"],
        name=text_a, region_id=seoul_id, address="서울 강남구 별칭로 1",
        reviewer="human-approved-tester")
    venue_resolution.link_existing(
        pg, unresolved_venue_id=entry_b["unresolved_venue_id"],
        venue_id=created["venue"]["venue_id"], reviewer="human-approved-tester")

    venue = master_data.list_venues(pg)
    aliases = next(v["aliases"] for v in venue if v["venue_id"] == created["venue"]["venue_id"])
    assert text_a in aliases
    assert text_b in aliases


# 6. region conflict: a same-sounding name in a different region/address
#    is never silently merged, human approval or not.
def test_region_conflict_still_blocks_auto_merge(pg, unique, seoul_id):
    existing = master_data.create_venue(
        pg, name=f"실루엣 {unique}", region_id=seoul_id, address="서울 마포구 실루엣로 1")
    assert venue_resolution._address_conflict(
        existing["address"], "경기 성남시 분당구 다른실루엣로 99") is True
    # A bare name match alone (no address given) is not a conflict signal -
    # it just means neither side names a place yet, still not license to merge.
    assert venue_resolution._address_conflict(existing["address"], None) is False


# 7. relocation-style disagreement across posts is a defer signal, not an
#    average or a pick-one - mirrors 실루엣's own investigation finding
#    three different addresses across sources.
def test_disagreeing_addresses_signal_relocation_defer(pg, unique):
    venue_text = f"이전가능홀 {unique}"
    item_a = _make_source_item(pg, unique=unique, suffix="a")
    item_b = _make_source_item(pg, unique=unique, suffix="b")
    item_c = _make_source_item(pg, unique=unique, suffix="c")
    with pg.cursor() as cur:
        for item, addr in ((item_a, "서울 강남구 옛주소로 1"),
                           (item_b, "서울 종로구 새주소로 2"),
                           (item_c, "서울 마포구 세번째주소로 3")):
            cur.execute(
                "INSERT INTO source_item_content (source_item_id, acquisition_status, "
                "extracted_text) VALUES (%s, 'FETCHED_FULL', %s)",
                (item, f"장소 : {venue_text} {addr}"),
            )
    for suffix, item, date in (("1", item_a, "2026-09-05"),
                               ("2", item_b, "2026-09-06"),
                               ("3", item_c, "2026-09-07")):
        normalization.normalize_candidate(
            pg, _candidate(unique, suffix, venue=venue_text, source_item_id=item,
                          event_date=date))
    # No human answer available for this hypothetical venue -> defer, never guess.
    assert venue_resolution.address_from_context(pg, venue_text) is None


# 8. historical safety: the current schema has one address field per
#    venue - linking a raw string updates EVERY event under it,
#    including past-dated ones. This is a real, documented limitation
#    (Section 19), not something silently hidden - a relocation-prone
#    venue must stay a human KEEP_OPEN/DEFER call, never an automated one.
def test_historical_events_share_the_new_venues_single_address(pg, unique, seoul_id):
    venue_text = f"과거이벤트홀 {unique}"
    past = normalization.normalize_candidate(
        pg, _candidate(unique, "1", venue=venue_text, event_date="2020-01-01"))
    future = normalization.normalize_candidate(
        pg, _candidate(unique, "2", venue=venue_text, event_date="2026-09-05"))
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="서울 마포구 현재주소로 1",
        reviewer="human-approved-tester")
    for stored in (past, future):
        updated = normalization.get(pg, stored["event_id"])
        assert updated["venue_id"] is not None
    # Same venue_id/address on both - the one-field limitation, made visible.
    past_v = normalization.get(pg, past["event_id"])["venue_id"]
    future_v = normalization.get(pg, future["event_id"])["venue_id"]
    assert past_v == future_v


# 9. preview affected events: the unresolved-venue queue's own counters
#    are what a human reviews before approving - upcoming and total must
#    be readable without writing anything.
def test_preview_counts_before_any_write(pg, unique):
    venue_text = f"미리보기홀 {unique}"
    normalization.normalize_candidate(
        pg, _candidate(unique, "1", venue=venue_text, event_date="2020-01-01"))
    normalization.normalize_candidate(
        pg, _candidate(unique, "2", venue=venue_text, event_date="2026-09-05"))
    entry = _queued(pg, venue_text)
    assert entry["event_count"] == 2
    # Nothing written yet - still UNRESOLVED, still OPEN.
    assert entry["state"] == "OPEN"


# 10. scoped allow-list: approving one venue never touches a second,
#     still-open one.
def test_scoped_allow_list_touches_only_approved_venue(pg, unique, seoul_id):
    approved_text = f"승인됨홀 {unique}"
    other_text = f"미승인홀2 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1", venue=approved_text))
    normalization.normalize_candidate(pg, _candidate(unique, "2", venue=other_text))
    entry = _queued(pg, approved_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=approved_text, region_id=seoul_id, address="서울 마포구 승인로 1",
        reviewer="human-approved-tester")
    still_open = _queued(pg, other_text)
    assert still_open["state"] == "OPEN"


# 11. the Timeline shows the human-approved address, compacted per
#     v0.85.4's own formatter - no regression. Lives on line 2 since
#     v0.85.8 (was line 3 through v0.85.7).
def test_timeline_shows_human_approved_address(pg, unique, seoul_id):
    venue_text = f"타임라인홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id,
        address="서울 서초구 강남대로595 경승빌딩 B1", reviewer="human-approved-tester")
    event = events_api.get_event(pg, stored["event_id"])
    line2 = public._timeline_line2(event)
    assert "서초구 강남대로595" in line2


# 12. calendar count is unchanged by a venue link/address approval.
def test_calendar_count_unchanged(pg, unique, seoul_id):
    """v0.86.1: same fix as test_v0855_venue_address_coverage.py's
    test_calendar_count_unchanged_by_venue_link - `search(when="upcoming")`
    reads the real clock without an explicit `now=`, and this fixture's
    own `event_date` ("2026-09-05") is fixed, so once the real calendar
    passed it the delta assertion below started passing vacuously (0==0)
    regardless of whether venue-linking actually left the calendar count
    alone. Pinning `now=` to a moment before the fixture's own date keeps
    it "upcoming" no matter what day this test actually runs."""
    from datetime import datetime

    now = datetime(2026, 9, 4, 12, 0, tzinfo=events_api.SEOUL)
    venue_text = f"캘린더홀6 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    before_total = events_api.search(pg, when="upcoming", limit=100, now=now)["total"]
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="서울 마포구 캘린더로 6",
        reviewer="human-approved-tester")
    after_total = events_api.search(pg, when="upcoming", limit=100, now=now)["total"]
    assert after_total == before_total


# 13. the v0.85.4 JSON/API link resolver is unaffected by this release.
def test_json_api_link_resolution_unchanged():
    assert events_api.resolve_public_source_url(
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events/abc123"
    ) == "https://ktnow.kr/"


# 14. approving a venue changes only venue_id/venue_status/region_id/
#     identity - the event's own name/date/fee/dj are untouched.
def test_raw_event_data_unchanged_except_approved_fields(pg, unique, seoul_id):
    venue_text = f"불변데이터홀 {unique}"
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, venue=venue_text, fee=17000, event_name=f"원본이름 {unique}"))
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="서울 마포구 불변로 1",
        reviewer="human-approved-tester")
    updated = normalization.get(pg, stored["event_id"])
    assert updated["event_name"] == f"원본이름 {unique}"
    assert updated["fee"] == 17000
    assert updated["event_date"] == stored["event_date"]


# 15. every human-approved write lands in the existing audit trail with
#     who/when/what - reused, not reinvented.
def test_audit_record_captures_human_reviewer(pg, unique, seoul_id):
    venue_text = f"감사기록홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="서울 마포구 감사로 1",
        reviewer="human-approved-v0.85.6-kimpro")
    record = venue_resolution.history(pg, limit=1)[0]
    assert record["reviewer"] == "human-approved-v0.85.6-kimpro"
    assert record["action"] == venue_resolution.CREATE_AND_LINK
    assert record["after_json"]["address"] == "서울 마포구 감사로 1"
    assert "created_at" in record
