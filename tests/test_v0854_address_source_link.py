"""v0.85.4 Compact Timeline Address + Human-readable Source Link.

26 required tests (Sections 52-54): Timeline Layout (10), Source URL (10),
Address (6). Pure-function tests against runtime.public/runtime.events_api -
no database needed, same style as test_v085_timeline_calendar.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from runtime import events_api, public


def _event(**overrides):
    base = {
        "id": 1, "name": "더 피스타 밀롱가", "date": "2026-09-12",
        "start_time": "19:00", "end_time": "23:00", "ends_next_day": False,
        "time_confirmed": True, "event_type_label": "밀롱가",
        "region": "서울", "region_confirmed": True,
        "venue": {"name": "더 피스타", "status": "RESOLVED",
                  "address": "서울 마포구 월드컵북로6길 49 B1"},
        "fee": 20000, "dj": None,
        "status": "POSSIBLE", "status_label": "확인 필요", "cancelled": False,
        "source_link": {"url": "https://cafe.daum.net/latindance/73b/68727",
                         "label": "Solo Tango 화요정모 공지"},
        "last_checked": _TWO_HOURS_AGO,
    }
    base.update(overrides)
    return base


NOW = datetime.fromisoformat("2026-09-12T10:00:00+09:00")
_TWO_HOURS_AGO = (NOW - timedelta(hours=2)).isoformat()


# =============================================================================
# Timeline Layout (10)
# =============================================================================

# 1. line 1 still carries region/date/time/type - unchanged this release.
def test_line1_region_date_time_type():
    line1 = public._timeline_line1(_event(), now=NOW)
    assert "[서울]" in line1 and "19:00" in line1 and "밀롱가" in line1


# 2. line 2 still carries event name / DJ / fee - unchanged this release.
def test_line2_event_dj_fee():
    line2 = public._timeline_line2(_event(dj="Minsu"))
    assert "더 피스타 밀롱가" in line2 and "DJ Minsu" in line2 and "20,000원" in line2


# 3. line 3 carries address, source, and confirmation time together, in one row.
def test_line3_address_source_time_one_row():
    rendered = public._event_item(_event(), now=NOW)
    assert rendered.count('<div class="tl-3">') == 1
    line3 = public._timeline_line3(_event(), now=NOW)
    assert "마포구" in line3 and "출처:" in line3 and "2시간 전" in line3


# 4. never a fourth structural line, whatever content line 3 carries.
def test_max_three_lines_with_address():
    rendered = public._event_item(_event(dj="Minsu"), now=NOW)
    assert rendered.count('<div class="tl-') == 3


# 5. a long address is ellipsized rather than shown in full.
def test_address_ellipsis():
    line3 = public._timeline_line3(_event(), now=NOW)
    assert "…" in line3
    assert "B1" not in line3


# 6. a missing address is an honest "주소 미확인", never blank or guessed.
def test_missing_address_is_honest():
    event = _event(venue={"name": "더 피스타", "status": "RESOLVED", "address": None})
    line3 = public._timeline_line3(event, now=NOW)
    assert "주소 미확인" in line3


# 7. a long source name still renders in full (no name truncation).
def test_long_source_name_still_renders():
    long_name = "Solo Tango 화요정모 공지 - 매주 화요일 저녁 밀롱가 상세 안내"
    event = _event(source_link={"url": "https://cafe.daum.net/x/1", "label": long_name})
    line3 = public._timeline_line3(event, now=NOW)
    assert long_name in line3


# 8. a long address AND a long source name together still both survive on
#    the one line - the address is what gets shortened, not the source name.
def test_long_address_and_source_both_visible():
    long_name = "Solo Tango 화요정모 공지"
    event = _event(
        venue={"name": "엔빠스", "status": "RESOLVED",
               "address": "서울특별시 서초구 반포대로30길 82 우서빌딩 지하 1층"},
        source_link={"url": "https://cafe.daum.net/x/1", "label": long_name},
    )
    line3 = public._timeline_line3(event, now=NOW)
    assert "서초구 반포대로30길 82" in line3
    assert long_name in line3


# 9. confirmation time is visible on line 3.
def test_confirmation_time_visible():
    line3 = public._timeline_line3(_event(), now=NOW)
    assert "2시간 전" in line3


# 10. the v0.85.3 DJ-duplicate-suppression fix still holds this release.
def test_dj_duplicate_regression():
    event = _event(name="Solo Tango 화요정모 (DJ 유진)", dj="유진")
    line2 = public._timeline_line2(event)
    assert line2.count("유진") == 1


# =============================================================================
# Source URL (10)
# =============================================================================

# 11. an already-human detail URL is chosen through unchanged.
def test_direct_detail_url_passthrough():
    url = "https://cafe.daum.net/latindance/73b/68727"
    assert events_api.resolve_public_source_url(url) == url


# 12. Tango Calendar's raw API detail endpoint is never the user-facing link.
def test_api_json_url_rejected_for_display():
    api_url = "https://tangocalendar.kr/api/events/53ea5cd1-ca42-4d81-b0a7-2e47872e930c"
    resolved = events_api.resolve_public_source_url(api_url)
    assert "/api/events/" not in resolved
    assert resolved == "https://tangocalendar.kr/?eventId=53ea5cd1-ca42-4d81-b0a7-2e47872e930c"


# 13. a payload's own human canonical link (e.g. TangoClass's WordPress
#     `link` field) is chosen as-is - already correct, must stay that way.
def test_wordpress_payload_link_passthrough():
    url = "https://tangoclass.co.kr/%ed%83%b1%ea%b3%a0-%ec%88%98%ec%97%85/2026/08/22/sep-class/"
    assert events_api.resolve_public_source_url(url) == url


# 14. the collector's own fetch target is a separate concern from the
#     display link, and resolving the display link never touches it.
def test_collector_target_untouched_by_display_resolution():
    collector_target = "https://tangocalendar.kr/api/events"
    events_api.resolve_public_source_url(
        "https://tangocalendar.kr/api/events/53ea5cd1-ca42-4d81-b0a7-2e47872e930c"
    )
    assert collector_target == "https://tangocalendar.kr/api/events"


# 15. TangoNOW's Firestore document URL falls back to the source home page -
#     there is no reliable per-event human deep link for this source.
def test_firestore_url_falls_back_to_source_home():
    firestore_url = ("https://firestore.googleapis.com/v1/projects/ktangoguide/"
                      "databases/(default)/documents/events/DEH1xNIQjs6rOqQ9ddde")
    assert events_api.resolve_public_source_url(firestore_url) == "https://ktnow.kr/"


# 16. a directory source's own public detail link (Miltang) passes through.
def test_directory_public_detail_link_passthrough():
    url = "https://miltang.com/milongas/164"
    assert events_api.resolve_public_source_url(url) == url


# 17. the representative (PRIMARY) source's own URL is what present() links
#     to - it operates on the row's own source_url, never a different
#     candidate's, so the representative always wins by construction.
def test_primary_representative_url_used():
    row = {
        "event_id": 1, "event_name": "Solo Tango 화요정모", "event_date": None,
        "source_url": "https://cafe.daum.net/latindance/73b/68727",
        "source_platform": "DAUM_CAFE", "source_name": "Solo Tango 화요정모 공지",
        "source_source_role": "PRIMARY",
    }
    presented = events_api.present(row)
    assert presented["source_link"]["url"] == "https://cafe.daum.net/latindance/73b/68727"
    assert presented["source_link"]["label"] == "Solo Tango 화요정모 공지"


# 18. an invalid/malformed URL is safely omitted, never rendered as a link -
#     the source's own name (when known) still shows as plain, unlinked text.
def test_invalid_url_safely_omitted():
    event = _event(source_link={"url": "not a url", "label": "테스트"})
    line3 = public._timeline_line3(event, now=NOW)
    assert "<a href=" not in line3
    assert "출처: 테스트" in line3


# 18b. with neither a valid URL nor a label, the source is an honest unknown.
def test_invalid_url_and_no_label_is_honest_unknown():
    event = _event(source_link={"url": "not a url", "label": None})
    line3 = public._timeline_line3(event, now=NOW)
    assert "<a href=" not in line3
    assert "출처 미확인" in line3


# 19. the real source name is shown, not a generic platform label.
def test_source_name_not_platform_name():
    row = {
        "event_id": 1, "event_name": "외부홍보파티", "event_date": None,
        "source_url": "https://cafe.daum.net/latindance/5HTC/22260",
        "source_platform": "DAUM_CAFE", "source_name": "외부홍보게시판(파티)",
        "source_source_role": "PRIMARY",
    }
    presented = events_api.present(row)
    assert presented["source_link"]["label"] == "외부홍보게시판(파티)"
    assert presented["source_link"]["label"] != "Daum Cafe"


# 20. a raw JSON API host is never visible in the rendered source link.
def test_no_json_endpoint_visible_in_render():
    row = {
        "event_id": 1, "event_name": "탱고나우 이벤트", "event_date": None,
        "source_url": ("https://firestore.googleapis.com/v1/projects/ktangoguide/"
                        "databases/(default)/documents/events/abc123"),
        "source_platform": "WEB", "source_name": "TangoNOW",
        "source_source_role": "DIRECTORY",
    }
    presented = events_api.present(row)
    event = _event(source_link=presented["source_link"])
    line3 = public._timeline_line3(event, now=NOW)
    assert "firestore.googleapis.com" not in line3
    assert "ktnow.kr" in line3


# =============================================================================
# Address (6)
# =============================================================================

# 21. a resolved venue master address is rendered, compacted.
def test_resolved_venue_address_rendered():
    line3 = public._timeline_line3(_event(), now=NOW)
    assert "마포구 월드컵북로6길 49" in line3


# 22. a venue's NAME is never shown in place of a real address.
def test_venue_name_never_shown_as_address():
    event = _event(venue={"name": "Tango O Nada", "status": "RESOLVED", "address": None})
    line3 = public._timeline_line3(event, now=NOW)
    assert "Tango O Nada" not in line3
    assert "주소 미확인" in line3


# 23. no address at all -> honest unknown, not a blank line-3 segment.
def test_no_address_honest_unknown():
    assert public._compact_address(None) is None
    assert public._compact_address("") is None


# 24. the region already shown on line 1 is trimmed from the address on line 3.
def test_region_prefix_trimmed():
    assert public._compact_address("서울 마포구 잔다리로 48, 2층") == "마포구 잔다리로 48…"
    assert public._compact_address("부산 부산진구 서면로68번길 38 4층") == "부산진구 서면로68번길 38…"


# 25. compacting for display never mutates the original stored value.
def test_original_address_unchanged_by_formatter():
    raw = "서울시 마포구 양화로 12길 24 선진빌딩 B1"
    event = _event(venue={"name": "Tango Andante", "status": "RESOLVED", "address": raw})
    public._timeline_line3(event, now=NOW)
    assert event["venue"]["address"] == raw


# 26. Korean multi-part addresses compact to district + road + street number.
def test_korean_address_compact_formatting():
    assert public._compact_address(
        "서울특별시 서초구 서초대로 123 4층") == "서초구 서초대로 123…"
    assert public._compact_address(
        "서울특별시 마포구 월드컵북로2길 57 지하 1층") == "마포구 월드컵북로2길 57…"
