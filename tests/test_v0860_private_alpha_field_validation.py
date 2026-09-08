"""v0.86.0 Private Alpha Field Validation.

"실제 사용자가 Timeline만 보고 판단할 때 틀리거나 헷갈리는 정보를 찾아 그것만
고친다" - a full-field production audit (148 upcoming events, every
Line1/2/3 dimension, every multi-tier duplicate group, fee/end-time/map/
source-link samples), not a pre-written feature list. Two real, confirmed
defects surfaced, both DJ-related; everything else audited clean (end
time, conditional fee, source priority, address/map consistency, source
link human-readability, line 3 structure) - see RELEASE_NOTES.md for the
full audit tally.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from runtime import events_api, public


_NOW = datetime.fromisoformat("2026-09-08T21:00:00+09:00")


def _event(**overrides):
    base = {
        "id": 1, "name": "화정 공지", "date": "2026-09-12",
        "start_time": "20:00", "end_time": "23:00", "ends_next_day": False,
        "time_confirmed": True, "event_type_label": "밀롱가",
        "region": "서울", "region_confirmed": True,
        "venue": {"name": "Solo Tango", "status": "RESOLVED",
                  "address": "서울 마포구 동교로 193 지하1층",
                  "map_url": events_api.build_naver_map_search_url(
                      "서울 마포구 동교로 193 지하1층")},
        "fee": None, "dj": "유진",
        "status": "POSSIBLE", "status_label": "확인 필요", "cancelled": False,
        "source_link": {"url": "https://cafe.daum.net/latindance/73b/68727",
                        "label": "Solo Tango 화요정모 공지"},
        "last_checked": (_NOW - timedelta(hours=7)).isoformat(),
    }
    base.update(overrides)
    return base


# --- DJ duplicate suppression: emoji-decorated titles (real production
# case, event_id 13693: "...5시30분🎉DJ네로🎉🎉", dj="네로") -----------------

def test_dj_name_immediately_followed_by_emoji_is_recognised_in_the_title():
    event = _event(
        name="\U0001f389분당러블리7주년파티\U0001f3899/12(토)5시30분\U0001f389DJ네로\U0001f389\U0001f389",
        dj="네로",
    )
    line2 = public._timeline_line2(event)
    assert line2.count("네로") == 1


def test_dj_name_followed_by_a_closing_paren_is_still_recognised():
    """Non-regression: the pre-existing stop-character path (v0.85.3)."""
    event = _event(name="Solo Tango 화요정모 (DJ 유진)", dj="유진")
    line2 = public._timeline_line2(event)
    assert line2.count("유진") == 1


def test_a_genuinely_different_dj_in_the_title_is_never_hidden():
    """Section 33 (no fuzzy matching): a real conflict between the title
    and the structured field must stay visible, decoration-stripping or
    not."""
    event = _event(name="\U0001f389DJ철수\U0001f389 파티", dj="영희")
    line2 = public._timeline_line2(event)
    assert "영희" in line2
    assert line2.count("(DJ 영희)") == 1


def test_no_dj_in_title_still_shows_the_structured_badge():
    event = _event(name="분당러블리 7주년 파티안내", dj="네로")
    line2 = public._timeline_line2(event)
    assert "(DJ 네로)" in line2


# --- everything else audited: regression pins for what the full
# production sweep confirmed already correct, so it stays that way -------

def test_end_time_still_shown_on_timeline():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert "20:00~23:00" in line1


def test_conditional_fee_still_shown_on_timeline():
    event = _event(fee=8000, fee_display_text="8,000원 (22시 이후 5,000원)")
    line2 = public._timeline_line2(event)
    assert "입장료: 8,000원 (22시 이후 5,000원)" in line2


def test_address_absent_means_no_map_link():
    event = _event(venue={"name": "Solo Tango", "status": "RESOLVED",
                          "address": None, "map_url": None})
    line2 = public._timeline_line2(event)
    line3 = public._timeline_line3(event, now=_NOW)
    assert "tl-2-addr" not in line2
    assert "지도보기" not in line3


def test_source_link_is_never_a_json_api_endpoint():
    """The transform itself (events_api.resolve_public_source_url(), also
    pinned in test_v0858_timeline_three_line_lock.py) - the production
    audit's own 0/148 JSON/API-exposed finding depends on this staying
    true, not on a new mechanism."""
    assert events_api.resolve_public_source_url(
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events/abc123"
    ) == "https://ktnow.kr/"
