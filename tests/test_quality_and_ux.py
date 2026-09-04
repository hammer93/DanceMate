"""v0.78: what the numbers mean, what a reviewer sees first, what a reader gets.

Three questions this release exists to answer honestly:

    how good is the data we would show a dancer tonight
    what should a reviewer look at first
    what does a reader see when we do not know something
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from runtime import admin_pages, events_api, normalization, public, quality


# --- missing is not wrong ---------------------------------------------------

def test_the_wrong_time_rule_only_fires_where_the_post_said_afternoon():
    """A morning start is only wrong if the post carried a PM marker. A bare
    5시30 read as 05:30 is unconfirmed, not incorrect."""
    assert "time_evidence = 'EXPLICIT'" in quality.WRONG_TIME_SQL
    assert "start_time < TIME '12:00'" in quality.WRONG_TIME_SQL


def test_quality_is_measured_over_what_a_reader_can_reach():
    """Counting fixtures would flatter the numbers and say nothing about tonight."""
    for clause in (quality.LISTED, quality.LISTED_E):
        assert "LIVE" in clause
        assert "LISTED" in clause
        assert "canonical_event_id IS NULL" in clause


def test_no_events_and_none_of_the_events_are_different_answers():
    assert quality.percentage(0, 0) is None
    assert quality.percentage(0, 10) == 0
    assert quality.percentage(7, 10) == 70


# --- what a reviewer sees first ---------------------------------------------

def _row(**overrides):
    base = {
        "candidate_id": 1, "event_name": "밀롱가", "candidate_status": "POSSIBLE",
        "event_date": (events_api.today() + timedelta(days=14)).isoformat(),
        "start_time": "20:00", "venue": "PISTA", "fee": 13000,
        "review": {"review_state": "PENDING"}, "hints": [],
    }
    base.update(overrides)
    return base


def test_tonight_outranks_a_more_incomplete_event_three_weeks_out():
    """DanceMate exists to answer 'where can I dance tonight'."""
    tonight = _row(event_date=events_api.today().isoformat())
    distant = _row(start_time=None, venue=None, fee=None)
    ordered = sorted([distant, tonight], key=admin_pages.review_priority)
    assert ordered[0] is tonight


def test_a_value_that_contradicts_its_post_outranks_everything():
    wrong = _row(
        start_time="07:30",
        hints=[{"field": "start_time", "severity": "WARN", "message": "..."}],
    )
    tonight = _row(event_date=events_api.today().isoformat())
    ordered = sorted([tonight, wrong], key=admin_pages.review_priority)
    assert ordered[0] is wrong


def test_a_missing_time_outranks_a_missing_fee():
    no_time = _row(start_time=None)
    no_fee = _row(fee=None)
    ordered = sorted([no_fee, no_time], key=admin_pages.review_priority)
    assert ordered[0] is no_time


def test_a_conflict_sorts_above_a_complete_candidate():
    conflict = _row(candidate_status="CONFLICT")
    ordered = sorted([_row(), conflict], key=admin_pages.review_priority)
    assert ordered[0] is conflict


def test_an_undated_candidate_does_not_jump_the_queue():
    undated = _row(event_date=None)
    tonight = _row(event_date=events_api.today().isoformat())
    ordered = sorted([undated, tonight], key=admin_pages.review_priority)
    assert ordered[0] is tonight


@pytest.mark.parametrize("key", [
    "pending", "today", "conflict", "unknown_time", "unknown_venue",
    "unknown_fee", "reviewed", "all",
])
def test_every_filter_has_a_label_and_a_predicate(key):
    label, match = admin_pages.REVIEW_FILTERS[key]
    assert label
    assert callable(match)


def test_the_unknown_filters_select_what_they_claim():
    filters = admin_pages.REVIEW_FILTERS
    assert filters["unknown_time"][1](_row(start_time=None)) is True
    assert filters["unknown_time"][1](_row()) is False
    assert filters["unknown_venue"][1](_row(venue=None)) is True
    assert filters["unknown_fee"][1](_row(fee=None)) is True
    assert filters["today"][1](_row(event_date=events_api.today().isoformat())) is True
    assert filters["today"][1](_row()) is False


# --- what a reader is told --------------------------------------------------

def test_the_engines_vocabulary_is_translated_before_it_reaches_a_reader():
    """VERIFIED does not mean 'true'; it means the evidence gate passed. Neither
    phrase belongs on a page someone reads on the way out the door."""
    for status in ("VERIFIED", "POSSIBLE", "EXPECTED", "CONFLICT", "CANCELLED"):
        label = events_api.STATUS_LABELS[status]
        assert label
        assert label.isascii() is False  # Korean, not the enum


def test_an_unknown_status_still_gets_a_careful_label():
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": None, "end_time": None, "end_day_offset": 0,
        "engine_status": "SOMETHING_NEW", "review_state": "PENDING",
        "venue_status": "ABSENT", "fee": None,
    })
    assert presented["status_label"] == "확인 필요"


def test_a_human_review_is_shown_apart_from_the_evidence_gate():
    """An approval is not proof. Conflating the two would let one look like
    the other."""
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": None, "end_time": None, "end_day_offset": 0,
        "engine_status": "POSSIBLE", "review_state": "APPROVED",
        "venue_status": "ABSENT", "fee": None,
    })
    assert presented["status_label"] == "확인 필요"
    assert presented["human_reviewed"] is True
    rendered = public._status_line(presented)
    assert "확인 필요" in rendered
    assert "관리자 확인" in rendered


def test_a_cancelled_event_is_marked_rather_than_quietly_dropped():
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": None, "end_time": None, "end_day_offset": 0,
        "engine_status": "CANCELLED", "review_state": "PENDING",
        "venue_status": "ABSENT", "fee": None,
    })
    assert presented["cancelled"] is True
    assert "취소" in public._status_line(presented)
    assert "cancelled" in public._event_item({**presented, "venue": {"name": None}})


def test_the_last_check_is_a_timestamp_not_a_score():
    seen = datetime.now(timezone.utc) - timedelta(hours=2)
    rendered = public._checked_line({
        "last_checked": seen.isoformat(),
        "date": (events_api.today() + timedelta(days=7)).isoformat(),
    })
    assert "확인" in rendered
    assert "재확인 필요" not in rendered


def test_an_event_tonight_read_yesterday_asks_to_be_rechecked():
    stale = datetime.now(timezone.utc) - timedelta(hours=30)
    rendered = public._checked_line({
        "last_checked": stale.isoformat(),
        "date": events_api.today().isoformat(),
    })
    assert "재확인 필요" in rendered


def test_no_timestamp_means_no_claim():
    assert public._checked_line({"last_checked": None, "date": None}) == ""
    assert public._checked_line({"last_checked": "not a date", "date": None}) == ""


# --- SQL --------------------------------------------------------------------

def _live(pg, unique, suffix="1", **overrides):
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/v78/{unique}-{suffix}",
        "event_name": f"품질 테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": (events_api.today() + timedelta(days=3)).isoformat(),
        "start_time": "20:00", "end_time": "23:30", "end_day_offset": 0,
        "venue": f"품질홀 {unique}", "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
        "time_evidence": "EXPLICIT",
    }
    candidate.update(overrides)
    return normalization.normalize_candidate(pg, candidate)


def test_completeness_counts_what_is_missing_field_by_field(pg, unique):
    _live(pg, unique, "1")
    _live(pg, unique, "2", start_time=None, end_time=None,
          time_evidence=None, venue=None, fee=None)
    found = quality.completeness(pg, upcoming_only=True)
    assert found["events"] >= 2
    assert found["missing"]["time"] >= 1
    assert found["missing"]["venue"] >= 1
    assert found["missing"]["fee"] >= 1


def test_a_past_event_is_not_offered_to_a_reader(pg, unique):
    past = _live(pg, unique, "1",
                 event_date=(events_api.today() - timedelta(days=3)).isoformat())
    result = events_api.search(pg, limit=events_api.MAX_LIMIT)
    assert past["event_id"] not in [e["id"] for e in result["events"]]

    with_past = events_api.search(pg, limit=events_api.MAX_LIMIT, include_past=True)
    assert past["event_id"] in [e["id"] for e in with_past["events"]]


def test_a_cancelled_event_is_not_in_the_list_but_keeps_its_page(pg, unique):
    """Someone holding the link deserves to learn it is off, not a 404."""
    cancelled = _live(pg, unique, "1", candidate_status="CANCELLED")
    listed = events_api.search(pg, limit=events_api.MAX_LIMIT)
    assert cancelled["event_id"] not in [e["id"] for e in listed["events"]]

    page = events_api.get_event(pg, cancelled["event_id"])
    assert page is not None
    assert page["cancelled"] is True


def test_the_api_reports_when_the_post_was_last_collected(pg, unique):
    stored = _live(pg, unique, "1")
    shown = events_api.get_event(pg, stored["event_id"])
    assert "last_checked" in shown


def test_wrong_values_are_reported_separately_from_gaps(pg, unique):
    """A 07:30 milonga whose post said PM is a regression, not a gap."""
    _live(pg, unique, "1", start_time="07:30", end_time="11:30",
          time_evidence="EXPLICIT")
    found = quality.wrong_values(pg)
    assert any(unique in (w["event_name"] or "") for w in found)

    counts = quality.completeness(pg, upcoming_only=True)
    assert counts["wrong"]["time"] >= 1
    # ... and it is not double-counted as missing.
    assert counts["missing"]["time"] == counts["events"] - counts["time_known"]


def test_an_unconfirmed_time_is_not_counted_as_wrong(pg, unique):
    _live(pg, unique, "1", start_time="05:30", end_time="09:30",
          time_evidence="ABSENT")
    found = quality.wrong_values(pg)
    assert not any(unique in (w["event_name"] or "") for w in found)


def test_quality_breaks_down_by_region_and_genre(pg, unique):
    _live(pg, unique, "1")
    regions = quality.by_region(pg)
    genres = quality.by_genre(pg)
    assert regions and all("events" in r for r in regions)
    assert genres and all("events" in g for g in genres)


def test_freshness_counts_what_was_checked_in_the_last_day(pg, unique):
    _live(pg, unique, "1")
    found = quality.freshness(pg)
    assert found["upcoming"] >= 1
    assert found["checked_24h"] <= found["upcoming"]
