"""Alpha Event Search: date windows in Asia/Seoul, and what never gets served."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from runtime import duplicates, events_api, normalization

UTC = ZoneInfo("UTC")


# --- date windows -----------------------------------------------------------

def test_today_is_today_in_seoul_not_in_utc():
    """At 23:00 KST a UTC-based 'today' is already showing tomorrow's list."""
    late_saturday_kst = datetime(2026, 9, 5, 23, 30, tzinfo=events_api.SEOUL)
    assert events_api.today(late_saturday_kst) == date(2026, 9, 5)
    # The same instant is still Saturday afternoon in UTC, and would be read as
    # the 5th either way -- so take the case that actually differs:
    early_sunday_kst = datetime(2026, 9, 6, 0, 30, tzinfo=events_api.SEOUL)
    assert events_api.today(early_sunday_kst) == date(2026, 9, 6)
    assert early_sunday_kst.astimezone(UTC).date() == date(2026, 9, 5)


@pytest.mark.parametrize("when,expected", [
    ("today", (date(2026, 9, 5), date(2026, 9, 5))),
    ("tomorrow", (date(2026, 9, 6), date(2026, 9, 6))),
    # Saturday the 5th: "this week" runs to Sunday the 6th.
    ("this_week", (date(2026, 9, 5), date(2026, 9, 6))),
    ("weekend", (date(2026, 9, 5), date(2026, 9, 6))),
])
def test_windows_on_a_saturday(when, expected):
    saturday = datetime(2026, 9, 5, 12, 0, tzinfo=events_api.SEOUL)
    assert events_api.window(when, now=saturday) == expected


def test_this_week_is_what_is_still_ahead_of_you():
    """On a Wednesday, 'this week' is Wednesday to Sunday -- not a calendar week
    half of which has already happened."""
    wednesday = datetime(2026, 9, 2, 12, 0, tzinfo=events_api.SEOUL)
    assert events_api.window("this_week", now=wednesday) == (date(2026, 9, 2), date(2026, 9, 6))


def test_weekend_from_a_weekday_points_forward():
    wednesday = datetime(2026, 9, 2, 12, 0, tzinfo=events_api.SEOUL)
    assert events_api.window("weekend", now=wednesday) == (date(2026, 9, 5), date(2026, 9, 6))


def test_an_unknown_when_is_an_error_not_an_empty_list():
    """Silently returning nothing would read as 'no events', which is a lie."""
    with pytest.raises(events_api.SearchError):
        events_api.window("next_year")


def test_no_when_means_no_window():
    assert events_api.window(None) is None


# --- presentation -----------------------------------------------------------

def test_missing_values_stay_missing():
    """A null fee is not 0 and a null venue is not 'TBD'."""
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": None, "end_time": None, "end_day_offset": 0,
        "venue_text": None, "venue_status": "ABSENT", "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
    })
    assert presented["fee"] is None
    assert presented["currency"] is None
    assert presented["start_time"] is None
    assert presented["venue"]["name"] is None


def test_an_unresolved_venue_says_so():
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": time(19, 30), "end_time": time(23, 30), "end_day_offset": 0,
        "venue_text": "미등록 스튜디오", "venue_status": "UNRESOLVED", "venue_id": None,
        "fee": 13000, "engine_status": "POSSIBLE", "review_state": "PENDING",
    })
    assert presented["venue"] == {
        "name": "미등록 스튜디오", "status": "UNRESOLVED", "address": None, "id": None,
    }
    assert presented["fee"] == 13000
    assert presented["currency"] == "KRW"


def test_crossing_midnight_is_reported_not_hidden():
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": time(20, 0), "end_time": time(0, 30), "end_day_offset": 1,
        "venue_status": "ABSENT", "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
    })
    assert presented["start_time"] == "20:00"
    assert presented["end_time"] == "00:30"
    assert presented["ends_next_day"] is True


# --- SQL --------------------------------------------------------------------

def _live(pg, unique, suffix, **overrides):
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/alpha/{unique}-{suffix}",
        "event_name": f"검색 테스트 밀롱가 {unique}",
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


def test_a_snapshot_event_is_never_served(pg, unique):
    """A replayed snapshot is how we test a parser. Showing one as a real
    Saturday night would be a lie told to someone making plans."""
    _live(pg, unique, "1", provenance=normalization.PROVENANCE_SNAPSHOT)
    result = events_api.search(pg, on="2026-09-05", limit=100)
    assert _mine(result, unique) == []


def test_an_untraceable_event_is_never_served(pg, unique):
    _live(pg, unique, "1", provenance=normalization.PROVENANCE_UNKNOWN)
    assert _mine(events_api.search(pg, on="2026-09-05", limit=100), unique) == []


def test_a_live_event_is_served(pg, unique):
    _live(pg, unique, "1")
    found = _mine(events_api.search(pg, on="2026-09-05", limit=100), unique)
    assert len(found) == 1
    assert found[0]["start_time"] == "19:30"
    assert found[0]["fee"] == 13000


def test_a_rejected_event_is_never_served(pg, unique):
    _live(pg, unique, "1", **{})
    normalization.normalize_candidate(
        pg,
        {
            "candidate_id": int(f"{unique[-6:]}1"),
            "post_id": 1,
            "source_url": f"https://cafe.daum.net/alpha/{unique}-1",
            "event_name": f"검색 테스트 밀롱가 {unique}",
            "event_type": "MILONGA", "event_date": "2026-09-05",
            "start_time": "19:30", "end_time": "23:30", "end_day_offset": 0,
            "venue": f"스튜디오 {unique}", "fee": 13000,
            "candidate_status": "POSSIBLE",
            "provenance": normalization.PROVENANCE_LIVE,
        },
        review_state={"review_state": "REJECTED"},
    )
    assert _mine(events_api.search(pg, on="2026-09-05", limit=100), unique) == []


def test_a_merged_duplicate_is_served_once(pg, unique):
    _live(pg, unique, "1")
    _live(pg, unique, "2")
    duplicates.scan(pg, on=date(2026, 9, 5))
    found = _mine(events_api.search(pg, on="2026-09-05", limit=100), unique)
    assert len(found) == 1


def test_the_detail_page_lists_every_post_behind_the_event(pg, unique):
    _live(pg, unique, "1")
    _live(pg, unique, "2")
    duplicates.scan(pg, on=date(2026, 9, 5))
    found = _mine(events_api.search(pg, on="2026-09-05", limit=100), unique)
    event = events_api.get_event(pg, found[0]["id"])
    assert len(event["sources"]) == 2


def test_a_hidden_event_has_no_detail_page(pg, unique):
    """Not served in the list and not reachable by guessing the id either."""
    first = _live(pg, unique, "1")
    _live(pg, unique, "2")
    duplicates.scan(pg, on=date(2026, 9, 5))
    if normalization.get(pg, first["event_id"])["canonical_event_id"] is not None:
        assert events_api.get_event(pg, first["event_id"]) is None


def test_events_are_ordered_soonest_first_with_unknown_times_last(pg, unique):
    _live(pg, unique, "1", start_time="22:00", venue=f"늦은 {unique}")
    _live(pg, unique, "2", start_time="19:00", venue=f"이른 {unique}")
    _live(pg, unique, "3", start_time=None, end_time=None, venue=f"미상 {unique}")
    found = _mine(events_api.search(pg, on="2026-09-05", limit=100), unique)
    assert [e["start_time"] for e in found] == ["19:00", "22:00", None]


def test_a_date_filter_excludes_other_days(pg, unique):
    _live(pg, unique, "1")
    _live(pg, unique, "2", event_date="2026-09-12", venue=f"다음주 {unique}")
    assert len(_mine(events_api.search(pg, on="2026-09-05", limit=100), unique)) == 1
    assert len(_mine(events_api.search(
        pg, date_from="2026-09-01", date_to="2026-09-30", limit=100), unique)) == 2


def test_a_bad_date_is_rejected(pg):
    with pytest.raises(events_api.SearchError):
        events_api.search(pg, on="5 September")


def test_the_limit_is_bounded(pg):
    with pytest.raises(events_api.SearchError):
        events_api.search(pg, limit=events_api.MAX_LIMIT + 1)


def test_the_response_says_what_it_was_asked(pg, unique):
    _live(pg, unique, "1")
    result = events_api.search(pg, on="2026-09-05", limit=10)
    assert result["query"]["timezone"] == "Asia/Seoul"
    assert result["query"]["from"] == "2026-09-05"
    assert result["query"]["to"] == "2026-09-05"


def test_the_api_says_whether_a_time_was_qualified_by_the_post():
    unmarked = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 12),
        "start_time": time(5, 30), "end_time": time(9, 30), "end_day_offset": 0,
        "time_evidence": "ABSENT", "venue_status": "ABSENT", "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
    })
    assert unmarked["start_time"] == "05:30"
    assert unmarked["time_confirmed"] is False

    marked = events_api.present({
        "event_id": 2, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": time(19, 30), "end_time": time(23, 30), "end_day_offset": 0,
        "time_evidence": "EXPLICIT", "venue_status": "ABSENT", "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
    })
    assert marked["time_confirmed"] is True


def test_no_time_means_no_claim_either_way():
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": None, "end_time": None, "end_day_offset": 0,
        "time_evidence": None, "venue_status": "ABSENT", "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
    })
    assert presented["time_confirmed"] is None
