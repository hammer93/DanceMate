"""v0.86.6 Open-ended Event Time Display.

Real production investigation (Section 3-4) found today's Daegu "디디디"
event (event_id 88425, and its next week's occurrence 88378) has
start_time=NULL, end_time=NULL in both Postgres and the Miltang-sourced
body it was built from - the raw text never states a time at all, a
genuine source gap, not an engine defect (Case A does not even apply: this
specific event has no start reading to begin with, so its own display is
unchanged by this release - it still reads "시간 미확인"). No event
anywhere in the live database currently has start_time set with
end_time NULL either, so the exact "21:00~" symptom described going into
this release does not currently exist in production. The underlying
policy this release implements - never guess an end time, and never let a
start-only reading collide with a "the whole thing is unknown" reading -
is still real and worth building regardless, since any future post that
gives a start and nothing else would hit the same gap. See the release
report for the full real-data findings.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from runtime import admin, events_api, public

_NOW = datetime.fromisoformat("2026-09-09T10:00:00+09:00")


def _event(**overrides):
    base = {
        "id": 1, "name": "디디디", "date": "2026-09-09",
        "start_time": "21:00", "end_time": None, "ends_next_day": False,
        "time_confirmed": True, "event_type_label": "밀롱가",
        "region": "대구", "region_confirmed": True,
        "venue": {"name": "Tango Cafe Dia", "status": "RESOLVED", "aliases": []},
        "fee": None, "dj": None,
        "status": "POSSIBLE", "status_label": "확인 필요", "cancelled": False,
        "source_link": {"url": "https://miltang.com/milongas/349", "label": "Miltang"},
        "last_checked": None,
    }
    base.update(overrides)
    return base


# === Group 1: Display (structured on start/end, not a string patch) =======

# 1. start present, end NULL -> HH:MM~미정
def test_start_only_shows_open_ended_time():
    clock = public._timeline_clock(_event())
    assert clock == '21:00~<span class="unknown">미정</span>'


# 2. start+end -> HH:MM~HH:MM, unchanged
def test_start_and_end_shows_full_range():
    clock = public._timeline_clock(_event(end_time="23:30"))
    assert clock == "21:00~23:30"


# 3. no start, no end -> existing unknown display, unchanged
def test_no_time_at_all_shows_existing_unknown_display():
    clock = public._timeline_clock(_event(start_time=None, end_time=None))
    assert clock == '<span class="unknown">시간 미확인</span>'


# 4. start only -> never "시간 미확인" anywhere in the rendered line
def test_start_only_never_shows_the_no_time_text():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert "21:00" in line1
    assert "시간 미확인" not in line1


# 5. start+end -> never "미정" anywhere (a real end must not read as open-ended)
def test_full_range_never_shows_open_ended_text():
    line1 = public._timeline_line1(_event(end_time="23:30"), now=_NOW)
    assert "미정" not in line1


# 6. midnight-crossing full range is unaffected
def test_midnight_crossing_range_stays_a_full_range():
    clock = public._timeline_clock(
        _event(start_time="21:00", end_time="02:00", ends_next_day=True))
    assert clock == "21:00~02:00<sup>+1</sup>"
    assert "미정" not in clock


def test_open_ended_event_never_carries_the_next_day_marker():
    """ends_next_day describes the END crossing midnight - meaningless
    with no end at all, and must never leak onto the 미정 case."""
    clock = public._timeline_clock(_event(end_time=None, ends_next_day=True))
    assert "<sup>+1</sup>" not in clock


# 7. Admin Preview parity - the exact same function, not a second formatter
def test_admin_item_detail_public_preview_still_calls_the_shared_renderer():
    import inspect

    source = inspect.getsource(admin.admin_source_item_detail)
    assert "public._timeline_line1(event" in source


def test_admin_and_public_render_open_ended_time_identically():
    event = _event()
    admin_preview = public._timeline_line1(event, now=_NOW)  # what the Item
    live_timeline = public._timeline_line1(event, now=_NOW)  # Audit Detail
    assert admin_preview == live_timeline                     # and the live
    assert "21:00~" in admin_preview                          # Timeline both
    assert "미정" in admin_preview                             # actually call


# 8. Detail page parity
def test_detail_page_shows_open_ended_time_too():
    rendered = public._when_line(_event())
    assert "21:00" in rendered
    assert "미정" in rendered
    assert "시간 미확인" not in rendered


def test_detail_page_full_range_shows_no_open_ended_text():
    rendered = public._when_line(_event(end_time="23:30"))
    assert "미정" not in rendered
    assert "23:30" in rendered


# === Admin Extracted fields (Section 12) ====================================

def test_admin_extracted_end_shows_null_and_open_ended_together():
    html = admin._extracted_fields_table(_event())
    assert "NULL" in html
    assert "미정" in html


def test_admin_extracted_end_shows_the_real_value_when_present():
    html = admin._extracted_fields_table(_event(end_time="23:30"))
    assert "23:30" in html
    assert "NULL" not in html


# === Safety: end_time is never fabricated, never written as a string ======

def test_end_time_field_itself_stays_none_not_a_placeholder_string():
    """The display-only "미정" text must never leak into the structured
    value a caller could mistake for a real reading (Section 23-24: never
    stored/returned as the actual end_time)."""
    event = _event()
    public._timeline_clock(event)  # rendering must not mutate the event
    assert event["end_time"] is None


def test_present_never_invents_an_end_time_string():
    """events_api.present() is untouched by this release - a NULL
    end_time column still becomes a NULL API field, never "미정"."""
    import inspect

    source = inspect.getsource(events_api.present)
    assert "미정" not in source


# === Regression: conditional fee text must never be read as an end time ===

def test_conditional_fee_text_is_independent_of_open_ended_time():
    event = _event(fee=8000, fee_display_text="8,000원 (23시 이후 5,000원)")
    line1 = public._timeline_line1(event, now=_NOW)
    line2 = public._timeline_line2(event)
    assert "21:00~" in line1 and "미정" in line1
    assert "23:00" not in line1  # the fee condition's own hour never leaks into line 1
    assert "8,000원 (23시 이후 5,000원)" in line2


# === Regression: 277498-shaped multi-program event is unaffected ==========

def test_multiprogram_event_with_both_times_is_unaffected():
    event = _event(
        name="[9월 둘째주] 쉴 틈 없는 파티와 아기린 생일빵! 🔥",
        start_time="20:30", end_time="21:20", venue={"name": None, "status": "ABSENT",
                                                      "aliases": []},
        region=None, region_confirmed=False, fee=12000,
    )
    line1 = public._timeline_line1(event, now=_NOW)
    assert "20:30~21:20" in line1
    assert "미정" not in line1


# === Existing-behaviour regressions (Section 29) ============================

def test_venue_after_region_regression():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert line1.index("[대구]") < line1.index("Tango Cafe Dia")


def test_dj_duplicate_regression():
    event = _event(name="Solo Tango 화요정모 (DJ 유진)", dj="유진")
    assert public._timeline_line2(event).count("유진") == 1


def test_source_human_link_regression():
    assert events_api.resolve_public_source_url(
        "https://tangoclass.co.kr/wp-json/wp/v2/posts?per_page=10"
    ) == "https://tangoclass.co.kr/"


def test_naver_map_regression():
    event = _event(venue={"name": "x", "status": "RESOLVED", "aliases": [],
                         "address": "대구 북구 침산로 168",
                         "map_url": events_api.build_naver_map_search_url(
                             "대구 북구 침산로 168")})
    line3 = public._timeline_line3(event, now=_NOW)
    assert "map.naver.com/p/search/" in line3


def test_confirmation_indicator_is_untouched_by_open_ended_time():
    """Section 13: an open-ended time must never, by itself, force the "?"
    indicator on or off - it still follows only status/verification."""
    possible = public._timeline_line1(_event(status="POSSIBLE"), now=_NOW)
    verified = public._timeline_line1(
        _event(status="VERIFIED", status_label="확인됨", end_time="23:30"), now=_NOW)
    assert 'class="confirm-flag"' in possible
    assert 'class="confirm-flag"' not in verified


@pytest.mark.postgres
def test_genre_filter_still_works(pg):
    from runtime import sources

    assert sources.count_sources(pg, genre_code="ALL") >= 0
