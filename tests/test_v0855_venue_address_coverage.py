"""v0.85.5 Venue Address Coverage Improvement.

18 required tests (Section 51): the release itself writes no new runtime
code - it uses venue_resolution.py's existing, already-safe Human Venue
Review workflow (link_existing / create_and_link / address_in /
address_from_context / similar_venues / _address_conflict) to backfill two
well-evidenced venues (an exact-match link and one official-source-
confirmed new venue). These tests are regression/characterization coverage
for that existing machinery under this release's specific real scenarios,
plus the v0.85.4 display formatter's continued correctness against the
new real address values.
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
            "VALUES (%s, %s, 'WEB', 'COMMUNITY', %s, 'UNKNOWN', TRUE) "
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


# 1. venue address backfill: linking an unresolved venue string to an
#    existing venue immediately backfills the address on its events -
#    the exact "홍대 솔로땅고 -> Solo Tango" shape from this release.
def test_venue_address_backfill_via_link_existing(pg, unique, seoul_id):
    venue_text = f"홍대 테스트홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    existing = master_data.create_venue(
        pg, name=f"테스트홀 {unique}", region_id=seoul_id, address="서울 마포구 테스트로 1 지하1층")
    entry = _queued(pg, venue_text)

    result = venue_resolution.link_existing(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        venue_id=existing["venue_id"], reviewer="tester")

    assert result["events_updated"] == 1
    event = events_api.get_event(pg, stored["event_id"])
    assert event["venue"]["address"] == "서울 마포구 테스트로 1 지하1층"


# 2. address is only backfilled for events whose venue actually resolved -
#    an unrelated still-unresolved venue's events stay untouched.
def test_only_resolved_venue_gets_the_address(pg, unique, seoul_id):
    resolved_text = f"해결됨 {unique}"
    unresolved_text = f"미해결 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1", venue=resolved_text))
    other = normalization.normalize_candidate(pg, _candidate(unique, "2", venue=unresolved_text))
    entry = _queued(pg, resolved_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=resolved_text, region_id=seoul_id, address="서울 강남구 테스트로 2",
        reviewer="tester")

    other_event = events_api.get_event(pg, other["event_id"])
    assert other_event["venue"]["address"] is None
    assert other_event["venue"]["status"] == "UNRESOLVED"


# 3. region conflict: an address naming a different region than the
#    candidate is a real conflict, never silently accepted.
def test_region_conflict_detected():
    assert venue_resolution._address_conflict(
        "서울 마포구 잔다리로 68", "부산 부산진구 서면로 1") is True


# 4. same venue name, different region/address: a name match alone is not
#    license to copy the other one's address - the same brand can operate
#    in two different cities (Section 13's own "스튜디오 오초" example).
def test_same_name_other_region_address_not_copied(pg, unique, seoul_id):
    existing = master_data.create_venue(
        pg, name=f"오초 {unique}", region_id=seoul_id, address="서울 마포구 오초로 1")
    matches = venue_resolution.similar_venues(pg, name=f"오초 {unique}")
    assert any(m["venue_id"] == existing["venue_id"] for m in matches)
    assert venue_resolution._address_conflict(
        existing["address"], "부산 해운대구 오초로 99") is True


# 5. historical evidence that disagrees across posts is not a signal at
#    all - two different addresses for the same raw string defer, they
#    never average or pick one.
def test_disagreeing_historical_addresses_defer(pg, unique):
    venue_text = f"애매한홀 {unique}"
    item_a = _make_source_item(pg, unique=unique, suffix="a")
    item_b = _make_source_item(pg, unique=unique, suffix="b")
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_item_content (source_item_id, acquisition_status, extracted_text) "
            "VALUES (%s, 'FETCHED_FULL', %s)",
            (item_a, f"장소 : {venue_text} 서울 강남구 테스트로 1"),
        )
        cur.execute(
            "INSERT INTO source_item_content (source_item_id, acquisition_status, extracted_text) "
            "VALUES (%s, 'FETCHED_FULL', %s)",
            (item_b, f"장소 : {venue_text} 서울 종로구 테스트로 99"),
        )
    normalization.normalize_candidate(
        pg, _candidate(unique, "1", venue=venue_text, source_item_id=item_a))
    normalization.normalize_candidate(
        pg, _candidate(unique, "2", venue=venue_text, source_item_id=item_b,
                       event_date="2026-09-06"))
    assert venue_resolution.address_from_context(pg, venue_text) is None


# 6. a single, clean, official-source-confirmed address is accepted via
#    create_and_link - the Tango Brujo shape.
def test_official_exact_address_accepted(pg, unique, seoul_id):
    venue_text = f"공식확인홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    result = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"공식확인홀 {unique}", region_id=seoul_id,
        address="서울 마포구 확인로 68 확인빌딩 지하1층", reviewer="tester")
    assert result["venue"]["address"] == "서울 마포구 확인로 68 확인빌딩 지하1층"


# 7. raw address evidence: an address written immediately after the venue
#    name in a post body is extracted, never one that merely appears
#    somewhere else in the same post.
def test_raw_address_evidence_extraction():
    body = "발표회 장소 : 홍대 테스트홀 (서울 마포구 테스트로5길 57) 관람료 : 무료"
    assert venue_resolution.address_in(body, "홍대 테스트홀") == "서울 마포구 테스트로5길 57"
    # never picks up an address belonging to an unrelated later mention
    body2 = "오늘 공지 무주소 밀롱가입니다. 다음주 장소는 다른홀 (서울 종로구 딴주소로 9) 입니다"
    assert venue_resolution.address_in(body2, "무주소 밀롱가") is None


# 8. genuinely no address evidence anywhere: stays an honest unknown, not
#    a guess.
def test_no_evidence_stays_unknown(pg, unique):
    venue_text = f"근거없음 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    event = events_api.get_event(pg, stored["event_id"])
    assert event["venue"]["address"] is None
    line3 = public._timeline_line3(event)
    assert "주소 미확인" in line3


# 9. v0.85.4's compact-address formatter still works on this release's
#    own new real address values (Tango Brujo shape).
def test_compact_address_on_new_real_value():
    assert public._compact_address(
        "서울 마포구 잔다리로 68 YMCA빌딩 지하1층") == "마포구 잔다리로 68…"


# 10. region prefix trimming regression, exercised against the Solo Tango
#     exact-match shape from this release.
def test_region_prefix_trimming_regression():
    assert public._compact_address(
        "서울 마포구 홍익로 5길 57 지하1층") == "마포구 홍익로 5길 57…"


# 11. linking a venue does not change how many upcoming events exist.
def test_calendar_count_unchanged_by_venue_link(pg, unique, seoul_id):
    venue_text = f"캘린더홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    before_total = events_api.search(pg, when="upcoming", limit=200)["total"]
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="서울 마포구 캘린더로 1",
        reviewer="tester")
    after_total = events_api.search(pg, when="upcoming", limit=200)["total"]
    assert after_total == before_total


# 12. linking a venue never merges the event into a different canonical
#     event - identity stays this event's own.
def test_event_identity_unchanged_by_venue_link(pg, unique, seoul_id):
    venue_text = f"아이덴티티홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="서울 마포구 아이디로 1",
        reviewer="tester")
    updated = normalization.get(pg, stored["event_id"])
    assert updated["event_id"] == stored["event_id"]
    assert updated["canonical_event_id"] is None


# 13. the source link a reader sees is untouched by an address backfill.
def test_source_link_unchanged_by_address_backfill(pg, unique, seoul_id):
    venue_text = f"소스링크홀 {unique}"
    url = f"https://cafe.daum.net/venue/{unique}-src"
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, venue=venue_text, source_url=url))
    before = events_api.get_event(pg, stored["event_id"])["source_link"]
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="서울 마포구 소스로 1",
        reviewer="tester")
    after = events_api.get_event(pg, stored["event_id"])["source_link"]
    assert after["url"] == before["url"]


# 14. the v0.85.4 JSON/API link resolver is untouched by this release.
def test_json_api_link_resolution_regression():
    assert events_api.resolve_public_source_url(
        "https://tangocalendar.kr/api/events/53ea5cd1-ca42-4d81-b0a7-2e47872e930c"
    ) == "https://tangocalendar.kr/?eventId=53ea5cd1-ca42-4d81-b0a7-2e47872e930c"


# 15. a venue's own NAME is never displayed in place of a real address.
def test_venue_name_never_shown_as_address(pg, unique, seoul_id):
    venue_text = f"이름주소아님홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    venue_resolution.link_existing(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        venue_id=master_data.create_venue(pg, name=venue_text, region_id=seoul_id)["venue_id"],
        reviewer="tester")
    event = events_api.get_event(pg, stored["event_id"])
    assert event["venue"]["address"] is None
    line3 = public._timeline_line3(event)
    assert venue_text not in line3


# 16. a backfilled address keeps its floor information in storage - the
#     compact display formatter may still ellipsize it, but the stored
#     value is never truncated.
def test_floor_preserved_in_storage(pg, unique, seoul_id):
    venue_text = f"층정보홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    result = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id,
        address="서울 마포구 층로 68 층빌딩 지하1층", reviewer="tester")
    assert "지하1층" in result["venue"]["address"]


# 17. an empty or whitespace-only address is never stored as a value -
#     create_and_link normalises it to NULL, the same as no address at all.
def test_empty_or_whitespace_address_not_stored(pg, unique, seoul_id):
    venue_text = f"빈주소홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    result = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="   ", reviewer="tester")
    assert result["venue"]["address"] is None


# 18. applying a scoped fix to one venue never touches another venue's
#     address or another still-open unresolved-venue entry.
def test_scoped_update_touches_only_the_target_venue(pg, unique, seoul_id):
    untouched = master_data.create_venue(
        pg, name=f"안건드림홀 {unique}", region_id=seoul_id, address="서울 강북구 안건드림로 1")
    venue_text = f"타깃홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    other_text = f"다른미해결홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "2", venue=other_text))
    entry = _queued(pg, venue_text)

    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, address="서울 마포구 타깃로 1",
        reviewer="tester")

    reread = master_data.get_venue(pg, untouched["venue_id"])
    assert reread["address"] == "서울 강북구 안건드림로 1"
    still_open = _queued(pg, other_text)
    assert still_open["state"] == "OPEN"
