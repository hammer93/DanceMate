"""v0.96.56 - a clock the post never placed in the day is said to be so.

P1-1 of the public launch audit: eight upcoming public events read as starting
between 05:00 and 09:30 in the morning. Five were the engine's (an end read as
a start, a timetable slot read as the night - engine/tests/
test_v09656_time_roles.py). The other three were these pages: a bare "7:00"
with no 오전/오후 is stored as 07:00, the API has always said so
(``time_confirmed: false``), and since v0.86.4 the HTML showed "07:00~08:00"
with nothing beside it - a confirmed morning, to anybody reading it.

v0.86.4 had a reason: "20:30~23:30 시간 미확인" tells a reader a time and
that it is unknown in the same breath. That rule stands. What is unknown is
only the half of the day, so that is what the page says, and the clock is
shown as the post wrote it ("7:00", not "07:00"). A clock that is placed -
marked, written in 24 hours, or set by a person - is shown exactly as before.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from runtime import candidates, events_api, public

_NOW = datetime.fromisoformat("2026-10-27T07:30:00+09:00")


def _row(**overrides):
    row = {
        "event_id": 1629819, "event_name": "바차타 화요일 시즌5 이벤트 클래스",
        "event_date": date(2026, 10, 27), "start_time": time(7, 0), "end_time": time(8, 0),
        "end_day_offset": 0, "time_evidence": "ABSENT", "venue_status": "ABSENT",
        "fee": None, "engine_status": "POSSIBLE", "review_state": "PENDING",
    }
    row.update(overrides)
    return events_api.present(row)


def _both(event):
    return public._when_line(event), public._timeline_clock(event)


# --- AM/PM never stated ----------------------------------------------------------

def test_an_unplaced_clock_is_shown_as_written_and_said_to_be_unplaced():
    event = _row()
    assert event["time_confirmed"] is False
    for rendered in _both(event):
        assert "7:00" in rendered and "8:00" in rendered
        assert "07:00" not in rendered and "08:00" not in rendered
        assert "오전·오후 미표기" in rendered
        # v0.86.4's rule: never "unknown" beside a value that is shown.
        assert "시간 미확인" not in rendered


def test_an_unplaced_start_without_an_end():
    event = _row(event_id=1629732, start_time=time(9, 30), end_time=None)
    when, line = _both(event)
    assert "9:30–" in when and "미정" in when and "오전·오후 미표기" in when
    assert "9:30~" in line and "미정" in line and "오전·오후 미표기" in line
    assert "09:30" not in when + line


def test_an_unplaced_overnight_end_carries_no_next_day_mark():
    """Whether 9:00~1:00 crosses midnight depends on the half of the day
    nobody stated, so the +1 the morning reading implies is not shown."""
    event = _row(start_time=time(9, 0), end_time=time(1, 0), end_day_offset=1)
    for rendered in _both(event):
        assert "<sup>+1</sup>" not in rendered
        assert "오전·오후 미표기" in rendered


def test_an_unplaced_clock_is_never_in_progress():
    event = _row(start_time=time(7, 0), end_time=time(8, 0))
    assert public._in_progress(event, now=_NOW) is False
    placed = _row(start_time=time(7, 0), end_time=time(8, 0), time_evidence="EXPLICIT")
    assert public._in_progress(placed, now=_NOW) is True


# --- placed clocks are shown exactly as before -----------------------------------------

@pytest.mark.parametrize("evidence", ["EXPLICIT", "UNAMBIGUOUS", "PROPAGATED", "HUMAN"])
def test_a_placed_clock_is_unchanged(evidence):
    event = _row(start_time=time(19, 0), end_time=time(22, 0), time_evidence=evidence)
    assert event["time_confirmed"] is True
    when, line = _both(event)
    assert "19:00–22:00" in when and "19:00~22:00" in line
    assert "미표기" not in when + line


def test_a_real_morning_practica_is_not_flagged():
    """Miltang's "시간: 11:00~14:00" (1629770, 1614453): the engine now reads
    the 24-hour end as placing the start, so the row is UNAMBIGUOUS."""
    event = _row(event_id=1629770, start_time=time(11, 0), end_time=time(14, 0),
                 time_evidence=candidates.EVIDENCE_UNAMBIGUOUS)
    when, line = _both(event)
    assert "11:00–14:00" in when and "11:00~14:00" in line
    assert "미표기" not in when + line


def test_an_explicit_morning_is_shown_as_a_morning():
    event = _row(start_time=time(8, 0), end_time=None, time_evidence="EXPLICIT")
    when, line = _both(event)
    assert "08:00" in when and "08:00" in line and "미표기" not in when + line


def test_a_human_edit_is_shown_as_the_person_set_it():
    """DATA-02: 1629719, EDITED by the operator to 19:30 with no end."""
    event = _row(event_id=1629719, start_time=time(19, 30), end_time=None,
                 time_evidence="HUMAN", review_state="EDITED")
    when, line = _both(event)
    assert "19:30" in when and "미정" in when and "미표기" not in when + line


def test_a_placed_overnight_end_keeps_its_next_day_mark():
    event = _row(start_time=time(21, 0), end_time=time(2, 0), end_day_offset=1,
                 time_evidence="UNAMBIGUOUS")
    when, line = _both(event)
    assert "21:00–02:00<sup>+1</sup>" in when and "21:00~02:00<sup>+1</sup>" in line


def test_no_start_is_still_time_unknown():
    """PHU QUOC after the fix: no start was stated, so none is shown."""
    event = _row(event_id=1629705, start_time=None, end_time=None, time_evidence=None)
    assert event["time_confirmed"] is None
    for rendered in _both(event):
        assert "시간 미확인" in rendered and "미표기" not in rendered


def test_a_festival_period_is_unchanged():
    event = _row(event_type="FESTIVAL", start_time=None, end_time=None, time_evidence=None,
                 last_day=date(2026, 11, 2))
    when = public._when_line(event)
    assert "10/27(화)–11/2(월)" in when and "미표기" not in when


# --- the HTML and the API say the same thing -------------------------------------

@pytest.mark.parametrize("evidence, confirmed", [
    ("ABSENT", False), ("UNAMBIGUOUS", True), ("EXPLICIT", True),
    ("PROPAGATED", True), ("HUMAN", True)])
def test_the_page_flags_exactly_what_the_api_leaves_unconfirmed(evidence, confirmed):
    event = _row(start_time=time(9, 0), end_time=time(11, 0), time_evidence=evidence)
    assert event["time_confirmed"] is confirmed
    flagged = "오전·오후 미표기" in public._when_line(event)
    assert flagged is (not confirmed)


def test_the_engine_verdict_for_a_24_hour_range_reaches_the_api_as_confirmed():
    """`candidates._time_evidence_value()` turns the engine's ABSENT +
    ambiguous=False into UNAMBIGUOUS - the shape the engine now gives
    "11:00~14:00"."""
    verdict = candidates._time_evidence_value(
        {"inference": "ABSENT",
         "value": '{"start": "11:00", "end": "14:00", "meridiem_evidence": "ABSENT", "ambiguous": false}'})
    assert verdict == candidates.EVIDENCE_UNAMBIGUOUS
    ambiguous = candidates._time_evidence_value(
        {"inference": "ABSENT",
         "value": '{"start": "07:00", "end": "08:00", "meridiem_evidence": "ABSENT", "ambiguous": true}'})
    assert ambiguous == "ABSENT"
