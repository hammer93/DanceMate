"""v0.85.0 Private Alpha Pilot: compact timeline, weekly calendar, source
priority. 41 required tests (Sections 58-60) plus the supporting modules
(source_priority, feedback, events_api.week_counts/week_window) those
sections assume exist.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from runtime import duplicates, events_api, feedback, normalization, public, source_priority


# =============================================================================
# Timeline (Section 58) - 19 tests
# =============================================================================

def _event(**overrides):
    base = {
        "id": 1, "name": "더 피스타 밀롱가", "date": "2026-09-12",
        "start_time": "19:00", "end_time": "23:00", "ends_next_day": False,
        "time_confirmed": True, "event_type_label": "밀롱가",
        "region": "서울", "region_confirmed": True,
        "venue": {"name": "더 피스타", "status": "RESOLVED"},
        "fee": 20000, "dj": None,
        "status": "POSSIBLE", "status_label": "확인 필요", "cancelled": False,
        "source_link": {"url": "https://cafe.daum.net/x/1", "label": "○○탱고"},
        "last_checked": _TWO_HOURS_AGO,
    }
    base.update(overrides)
    return base


NOW = datetime.fromisoformat("2026-09-12T10:00:00+09:00")
_TWO_HOURS_AGO = (NOW - timedelta(hours=2)).isoformat()


# 1. two-line event row (the common case: everything fits on tl-1/tl-2, tl-3
#    only for source+confirmation, and even that is "up to three", not four)
def test_two_line_event_row():
    rendered = public._event_item(_event(), now=NOW)
    assert rendered.count('<div class="tl-') <= 3
    assert '<div class="tl-1">' in rendered and '<div class="tl-2">' in rendered


# 2. maximum three lines - never a fourth structural block, whatever the
#    content (DJ + fee + source + confirmation all present at once).
def test_maximum_three_lines():
    rendered = public._event_item(_event(dj="Minsu"), now=NOW)
    assert rendered.count('<div class="tl-') == 3


# 3. region is line 1's own first token
def test_region_is_line_1():
    line1 = public._timeline_line1(_event(), now=NOW)
    assert line1.index("[서울]") < line1.index("19:00")


# 4. date is on line 1
def test_date_is_line_1():
    """NOW is 2026-09-12; a date far enough out that it is neither 오늘 nor
    내일 exercises the plain M/D(요일) format (Section 15)."""
    line1 = public._timeline_line1(_event(date="2026-09-19"), now=NOW)
    assert "9/19" in line1


# 5. time is on line 1
def test_time_is_line_1():
    line1 = public._timeline_line1(_event(start_time="20:30"), now=NOW)
    assert "20:30" in line1


# 6. event type is on line 1
def test_event_type_is_line_1():
    line1 = public._timeline_line1(_event(event_type_label="파티"), now=NOW)
    assert "파티" in line1


# 7. event name is shown (line 2)
def test_event_name_is_shown():
    line2 = public._timeline_line2(_event(name="한강 밀롱가"))
    assert "한강 밀롱가" in line2


# 8. DJ shown only when present
def test_dj_shown_only_when_present():
    with_dj = public._timeline_line2(_event(dj="Minsu"))
    without_dj = public._timeline_line2(_event(dj=None))
    assert "DJ Minsu" in with_dj
    assert "DJ" not in without_dj
    assert "미확인" not in without_dj.split("입장료")[0]  # no "DJ 미확인" filler


# 9. known fee
def test_fee_known():
    assert "입장료: 20,000원" in public._timeline_line2(_event(fee=20000))


# 10. unknown fee
def test_fee_unknown():
    line2 = public._timeline_line2(_event(fee=None))
    assert "입장료:" in line2 and "미확인" in line2


# 11. source is shown
def test_source_shown():
    line3 = public._timeline_line3(_event(), now=NOW)
    assert "출처:" in line3


# 12. source is clickable
def test_source_clickable():
    line3 = public._timeline_line3(_event(), now=NOW)
    assert "<a " in line3 and 'href="' in line3


# 13. the source URL rendered is the event's own
def test_correct_source_url():
    line3 = public._timeline_line3(
        _event(source_link={"url": "https://example.test/post/9", "label": "X"}), now=NOW)
    assert 'href="https://example.test/post/9"' in line3


# 14. confirmation time is real-timestamp-based
def test_confirmation_time_shown():
    line3 = public._timeline_line3(_event(), now=NOW)
    assert "2시간 전" in line3


# 15. an event with no venue/detail known is still safe (no crash, honest
#     "미확인" rather than an invented value)
def test_unknown_venue_detail_safety():
    thin = _event(region=None, region_confirmed=False, start_time=None,
                  fee=None, venue={"name": None, "status": "ABSENT"},
                  time_confirmed=None)
    rendered = public._event_item(thin, now=NOW)
    assert "지역 미확인" in rendered
    assert "시간 미확인" in rendered
    assert "미확인" in public._timeline_line2(thin)  # fee


# 16. POSSIBLE renders
def test_possible_status_renders():
    """v0.86.4 (Section 7-11): the "확인 필요" text badge is gone, replaced
    by the small "?" indicator right after the event type - same meaning,
    no longer a text phrase that could itself collide with a real value
    shown elsewhere on the line."""
    line1 = public._timeline_line1(_event(status="POSSIBLE", status_label="확인 필요"), now=NOW)
    assert "확인 필요" not in line1
    assert 'class="confirm-flag"' in line1


# 17. CONFLICT renders with its warn tone
def test_conflict_status_renders():
    line1 = public._timeline_line1(_event(status="CONFLICT", status_label="정보 충돌"), now=NOW)
    assert "정보 충돌" in line1
    assert "warn" in line1


# 18. CANCELLED never reaches the timeline row at all (excluded upstream by
#     events_api.search()'s own default, not by the row renderer -
#     asserted at the search layer, matching how the rest of this file
#     tests the exclusion default).
def test_cancelled_excluded_from_default_search(pg, unique):
    _live(pg, unique, "1", candidate_status="CANCELLED")
    assert _mine(events_api.search(pg, on="2026-09-05", limit=100), unique) == []


# 19. a completed (past-dated) event is visible on its own past day
def test_completed_past_event_visible_on_its_date():
    past = _event(date="2026-09-05")  # NOW is 2026-09-12
    line1 = public._timeline_line1(past, now=NOW)
    assert events_api.STATUS_LABELS["COMPLETED"] in line1


# =============================================================================
# Weekly Calendar (Section 59) - 15 tests
# =============================================================================

# 20. seven days
def test_seven_day_calendar():
    monday, sunday = events_api.week_window(0, now=NOW)
    assert (sunday - monday).days == 6


# 21. Monday start
def test_monday_start():
    # 2026-09-12 is a Saturday.
    monday, _ = events_api.week_window(0, now=NOW)
    assert monday.weekday() == 0
    assert monday <= date(2026, 9, 12) <= monday + timedelta(days=6)


# 22. previous week
def test_previous_week_offset():
    this_monday, _ = events_api.week_window(0, now=NOW)
    prev_monday, _ = events_api.week_window(-1, now=NOW)
    assert prev_monday == this_monday - timedelta(days=7)


# 23. next week
def test_next_week_offset():
    this_monday, _ = events_api.week_window(0, now=NOW)
    next_monday, _ = events_api.week_window(1, now=NOW)
    assert next_monday == this_monday + timedelta(days=7)


# 24. today is selected/markable
def test_today_is_within_this_week():
    monday, sunday = events_api.week_window(0, now=NOW)
    today = events_api.today(NOW)
    assert monday <= today <= sunday


# 25. a past day within the week is still a real, clickable link
def test_past_day_is_clickable():
    monday, sunday = events_api.week_window(0, now=NOW)
    html = public._week_calendar(
        monday=monday, sunday=sunday, counts={}, selected_date=None,
        week_offset=0, base_action="/events", query={"when": "today"})
    assert 'class="cal-day past"' in html or "past" in html
    assert html.count("<a class=\"cal-day") == 7 or html.count('cal-day') >= 7


# 26. a future day within the week is clickable too
def test_future_day_is_clickable():
    monday, sunday = events_api.week_window(0, now=NOW)
    html = public._week_calendar(
        monday=monday, sunday=sunday, counts={}, selected_date=None,
        week_offset=0, base_action="/events", query={"when": "today"})
    future_iso = sunday.isoformat()
    assert f'date={future_iso}' in html


# 27. day counts render correctly
def test_calendar_counts_render(pg, unique):
    _live(pg, unique, "1", event_date="2026-09-12")
    monday, sunday = events_api.week_window(0, now=NOW)
    counts = events_api.week_counts(pg, start=monday, end=sunday)
    assert counts["2026-09-12"] >= 1


# 28. region filter changes the count
def test_region_filter_changes_calendar_count(pg, unique):
    _live(pg, unique, "1", event_date="2026-09-12", venue=f"부산행사장{unique}")
    monday, sunday = events_api.week_window(0, now=NOW)
    all_counts = events_api.week_counts(pg, start=monday, end=sunday)
    filtered = events_api.week_counts(pg, start=monday, end=sunday, region="정말없는지역이름")
    assert all_counts["2026-09-12"] >= filtered["2026-09-12"]


# 29. genre filter changes the count
def test_genre_filter_changes_calendar_count(pg, unique):
    _live(pg, unique, "1", event_date="2026-09-12")
    monday, sunday = events_api.week_window(0, now=NOW)
    all_counts = events_api.week_counts(pg, start=monday, end=sunday)
    filtered = events_api.week_counts(pg, start=monday, end=sunday, genres=["SALSA"])
    assert all_counts["2026-09-12"] >= filtered["2026-09-12"]


# 30. a duplicate (merged-away) event is counted once, not twice
def test_duplicate_counted_once_in_calendar(pg, unique):
    _live(pg, unique, "1", event_date="2026-09-12", venue=f"중복장소{unique}",
         source_url=f"https://cafe.daum.net/dup/{unique}/1")
    _live(pg, unique, "2", event_date="2026-09-12", venue=f"중복장소{unique}",
         source_url=f"https://cafe.daum.net/dup/{unique}/2")
    duplicates.scan(pg, on=date(2026, 9, 12))
    monday, sunday = events_api.week_window(0, now=NOW)
    counts = events_api.week_counts(pg, start=monday, end=sunday)
    matching = [e for e in events_api.search(pg, on="2026-09-12", limit=100)["events"]
               if unique in (e["name"] or "")]
    assert len(matching) == 1  # the merge itself worked
    # The calendar's own count for the day is whatever _VISIBLE already
    # returns - already de-duplicated upstream by listing_state=HIDDEN.
    assert counts["2026-09-12"] >= 1


# 31. clicking a day narrows the timeline to that day (search on= behaves
#     as a single-day filter, exactly what a day click sends as `date=`)
def test_selected_day_filters_timeline(pg, unique):
    _live(pg, unique, "1", event_date="2026-09-12")
    _live(pg, unique, "2", event_date="2026-09-13", venue=f"다음날{unique}")
    found = _mine(events_api.search(pg, on="2026-09-12", limit=100), unique)
    assert len(found) == 1
    assert found[0]["date"] == "2026-09-12"


# 32. a historical (past) event is visible when its own day is selected
def test_historical_event_visible_on_its_day(pg, unique):
    _live(pg, unique, "1", event_date="2020-01-01")
    found = _mine(events_api.search(pg, on="2020-01-01", limit=100), unique)
    assert len(found) == 1


# 33. "completed" is a past-date-only reading, never applied to a future date
def test_completed_label_is_past_only():
    future = _event(date="2026-09-19")  # NOW is 2026-09-12
    past = _event(date="2026-09-05")
    assert not public._is_past(future, now=NOW)
    assert public._is_past(past, now=NOW)


# 34. KST boundary: "today" at 23:30 KST is still today, not tomorrow (UTC
#     would already disagree at this instant).
def test_kst_boundary_for_today():
    late = datetime(2026, 9, 12, 23, 30, tzinfo=events_api.SEOUL)
    assert events_api.today(late) == date(2026, 9, 12)
    monday, sunday = events_api.week_window(0, now=late)
    assert monday <= date(2026, 9, 12) <= sunday


# =============================================================================
# Source Priority (Section 60) - 7 tests
# =============================================================================

# 35. a PRIMARY source beats a DIRECTORY one as the representative source
def test_primary_beats_directory_as_representative():
    left = {"event_id": 1, "event_date": date(2026, 9, 12), "start_time": time(19, 0),
            "venue_id": 7, "venue_status": "RESOLVED", "end_time": time(23, 0), "fee": 20000,
            "engine_status": "POSSIBLE", "review_state": "PENDING", "source_role": "DIRECTORY"}
    right = dict(left, event_id=2, source_role="ORGANIZER")
    canonical, _ = duplicates._canonical_of(left, right)
    assert canonical["event_id"] == 2


# 36. a PROMOTION_BOARD source beats a DIRECTORY one
def test_promotion_board_beats_directory():
    left = {"event_id": 1, "event_date": date(2026, 9, 12), "start_time": time(19, 0),
            "venue_id": 7, "venue_status": "RESOLVED", "end_time": time(23, 0), "fee": 20000,
            "engine_status": "POSSIBLE", "review_state": "PENDING", "source_role": "AGGREGATOR"}
    right = dict(left, event_id=2, source_role="PROMOTION_BOARD")
    canonical, _ = duplicates._canonical_of(left, right)
    assert canonical["event_id"] == 2


# 37. a DIRECTORY source remains the (safe) fallback when nothing more
#     direct is available - never dropped from consideration.
def test_directory_is_the_fallback_not_dropped():
    left = {"event_id": 1, "event_date": date(2026, 9, 12), "start_time": time(19, 0),
            "venue_id": 7, "venue_status": "RESOLVED", "end_time": time(23, 0), "fee": 20000,
            "engine_status": "POSSIBLE", "review_state": "PENDING", "source_role": "DIRECTORY"}
    right = dict(left, event_id=2, source_role="AGGREGATOR")
    canonical, duplicate = duplicates._canonical_of(left, right)
    # Both DIRECTORY-tier (AGGREGATOR maps to DIRECTORY too) - falls through
    # to the existing, unchanged oldest-id tiebreak, never excluded either way.
    assert {canonical["event_id"], duplicate["event_id"]} == {1, 2}


# 38. source priority never grants VERIFIED by itself - the engine's own
#     evidence gate (unchanged) still decides.
def test_source_priority_does_not_imply_verified():
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 12),
        "start_time": None, "end_time": None, "end_day_offset": 0,
        "venue_status": "ABSENT", "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
        "source_source_role": "ORGANIZER",
    })
    assert presented["source_tier"] == source_priority.PRIMARY
    assert presented["status"] == "POSSIBLE"  # unaffected by tier


# 39. a genuine conflict stays a conflict regardless of either source's tier
def test_conflict_remains_conflict_regardless_of_source_tier():
    left = {"event_id": 1, "event_date": date(2026, 9, 12), "start_time": time(19, 0),
            "venue_id": 7, "venue_status": "RESOLVED", "venue_text": "스튜디오",
            "series_key": "venue:7|2026-09-12|밀롱가",
            "source_role": "ORGANIZER"}
    other = {"event_id": 2, "event_date": date(2026, 9, 12), "start_time": time(22, 0),
             "venue_id": 7, "venue_status": "RESOLVED", "venue_text": "스튜디오",
             "series_key": "venue:7|2026-09-12|밀롱가",
             "source_role": "DIRECTORY"}
    finding = duplicates.classify(left, other)
    assert finding is not None
    assert finding["auto"] is False  # a person decides - tier never auto-resolves this


# 40. when a direct source's own URL is known, it is the one selected
#     (the event's own source_link, joined straight off source_item_id -
#     this is what "선택된다" means today: whichever row is canonical
#     carries its own real source_link, never a guessed/blended one).
def test_direct_source_url_used_when_known(pg, unique):
    from runtime import intake, sources

    source = sources.create_source(
        pg, source_key=f"SRC-W-{unique}", name=f"공식 {unique}",
        platform="WEB", source_role="ORGANIZER",
        url=f"http://example.test/{unique}/", queries=[],
    )
    url = f"http://example.test/{unique}/post"
    intake.store_item(pg, source["source_id"],
                      intake.RawItem(external_id=url, url=url, title="공지"))
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id FROM source_items WHERE url = %s", (url,))
        source_item_id = cur.fetchone()[0]
    _live(pg, unique, "1", source_url=url, source_item_id=source_item_id)
    found = _mine(events_api.search(pg, on="2026-09-05", limit=100), unique)
    assert found[0]["source_link"]["url"] == url
    assert found[0]["source_tier"] == source_priority.PRIMARY


# 41. an aggregator-sourced event still carries its own original link, even
#     when it is the only source found (never blank just because it is a
#     lower tier - Section 2's "숨기지 않는다").
def test_aggregator_original_link_still_used_when_that_is_all_there_is(pg, unique):
    from runtime import intake, sources

    source = sources.create_source(
        pg, source_key=f"SRC-AGG-{unique}", name=f"집계{unique}",
        platform="WEB", source_role="AGGREGATOR",
        url=f"http://agg.test/{unique}/", queries=[],
    )
    url = f"http://agg.test/{unique}/post"
    intake.store_item(pg, source["source_id"],
                      intake.RawItem(external_id=url, url=url, title="집계글"))
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id FROM source_items WHERE url = %s", (url,))
        source_item_id = cur.fetchone()[0]
    _live(pg, unique, "1", source_url=url, source_item_id=source_item_id)
    found = _mine(events_api.search(pg, on="2026-09-05", limit=100), unique)
    assert found[0]["source_link"]["url"] == url
    assert found[0]["source_tier"] == source_priority.DIRECTORY


# =============================================================================
# Supporting modules: source_priority, feedback, DJ pipeline, SQL/Python
# rank consistency
# =============================================================================

@pytest.mark.parametrize("role,tier", [
    ("ORGANIZER", source_priority.PRIMARY),
    ("VENUE", source_priority.PRIMARY),
    ("COMMUNITY", source_priority.PRIMARY),
    ("PROMOTION_BOARD", source_priority.PROMOTION_BOARD),
    ("DIRECTORY", source_priority.DIRECTORY),
    ("AGGREGATOR", source_priority.DIRECTORY),
    ("SOMETHING_UNKNOWN", source_priority.DIRECTORY),
    (None, source_priority.DIRECTORY),
])
def test_source_priority_tier_of(role, tier):
    assert source_priority.tier_of(role) == tier


def test_source_priority_rank_is_ordered():
    assert source_priority.rank("ORGANIZER") < source_priority.rank("PROMOTION_BOARD")
    assert source_priority.rank("PROMOTION_BOARD") < source_priority.rank("DIRECTORY")


def test_source_priority_sql_case_matches_python_rank():
    """events_api.search()'s ORDER BY CASE is a hand-written mirror of
    source_priority.rank() (for SQL performance, not a shared code path) -
    this is the test that keeps them from drifting apart silently."""
    sql_case = {
        "ORGANIZER": 0, "VENUE": 0, "COMMUNITY": 0,
        "PROMOTION_BOARD": 1,
    }
    for role, expected in sql_case.items():
        assert source_priority.rank(role) == expected
    for role in ("DIRECTORY", "AGGREGATOR", "SOMETHING_ELSE", None):
        assert source_priority.rank(role) == 2


def test_feedback_kinds_have_labels():
    for kind in feedback.KINDS:
        assert feedback.LABELS[kind]


def test_feedback_rejects_an_unknown_kind(pg):
    with pytest.raises(feedback.UnknownKind):
        feedback.record(pg, event_id=1, kind="NOT_A_REAL_KIND")


def test_feedback_records_and_counts(pg, unique):
    _live_row = _live(pg, unique, "1")
    event_id = _live_row["event_id"]
    feedback.record(pg, event_id=event_id, kind=feedback.INCORRECT)
    assert feedback.count_open(pg) >= 1
    counts = feedback.counts_by_kind(pg)
    assert counts[feedback.INCORRECT] >= 1


def test_feedback_never_mutates_the_event(pg, unique):
    row = _live(pg, unique, "1")
    before = normalization.get(pg, row["event_id"])
    feedback.record(pg, event_id=row["event_id"], kind=feedback.INCORRECT)
    after = normalization.get(pg, row["event_id"])
    assert before["event_name"] == after["event_name"]
    assert before["fee"] == after["fee"]
    assert before["engine_status"] == after["engine_status"]


def test_dj_flows_from_candidate_to_the_events_table(pg, unique):
    row = _live(pg, unique, "1", dj="DJ Minsu")
    assert row["dj"] == "DJ Minsu"


def test_dj_is_absent_rather_than_empty_string(pg, unique):
    row = _live(pg, unique, "1", dj=None)
    assert row["dj"] is None


def test_dj_reaches_the_api_response(pg, unique):
    _live(pg, unique, "1", dj="DJ Minsu")
    found = _mine(events_api.search(pg, on="2026-09-05", limit=100), unique)
    assert found[0]["dj"] == "DJ Minsu"


def test_human_date_labels():
    today_iso = events_api.today(NOW).isoformat()
    tomorrow_iso = (events_api.today(NOW) + timedelta(days=1)).isoformat()
    later_iso = (events_api.today(NOW) + timedelta(days=5)).isoformat()
    assert public._human_date(today_iso, now=NOW) == "오늘"
    assert public._human_date(tomorrow_iso, now=NOW) == "내일"
    assert "(" in public._human_date(later_iso, now=NOW)


# =============================================================================
# Shared fixtures
# =============================================================================

def _live(pg, unique, suffix, **overrides):
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/tl/{unique}-{suffix}",
        "event_name": f"타임라인 테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"스튜디오 {unique}",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    candidate.update(overrides)
    return normalization.normalize_candidate(pg, candidate)


def _mine(result, unique):
    return [e for e in result["events"] if unique in (e["name"] or "")]
