"""v0.96.56 - what a clock is for (P1-1 of the public launch audit).

The audit found eight upcoming public events listed at 5 to 9 in the morning.
Three different things were wrong, and only two of them in the engine:

* TIME-02, an end read as a start. PHU QUOC's festival listing (item 6807)
  states no start at all, only "Social Parties until 05:00 AM", and each of
  its five nights was stored as opening at 05:00. `parse_start_time()` already
  refused a clock followed by 까지/until; written in front, "until" was not
  seen. An end alone now yields no start, and no start is derived from it.
* TIME-03, a timetable slot read as the night. 스위티스윙's DDP notice (item
  6377) states "■ 일시 : 2026.11.4.수.7:00-10:00PM" and then a timetable whose
  "DJ 소셜" sits nearest the next row's "8:00 ~ 8:40 - Live set 1"; the only
  upcoming swing social was listed at 08:00-08:40. A labelled whole-event
  range now outranks a slot strictly inside it.
* TIME-01, a bare clock shown as a morning. That is the public pages' doing
  (`runtime/public.py`, tested there); the engine keeps the hour as written
  and says it is ambiguous. One thing here does change: a range whose other
  end is written in 24 hours ("11:00~14:00") is not ambiguous, so the real
  Sunday-morning practicas are not flagged for a doubt their posts do not
  leave.

Replayed over all 5,022 stored items (2026-10-26 04:33 KST backup, the
runtime's own re-extract route, cached poster OCR, no network): the values of
exactly two posts change - 6377 and 6807 - and the evidence of twelve 11:00
practicas goes ABSENT -> UNAMBIGUOUS. Nothing else reads differently.
"""

import pytest

from src.extraction_rules import parse_start_time, parse_time_range
from src.extractor import extract_single
from src.live_pipeline import process_discovered_post
from tests.fixture_v09650_date_time_roles import REAL_TIMEBAR, TIMEBAR_PUBLISHED
from tests.fixture_v09656_time_roles import (
    DDP_PUBLISHED,
    REAL_BACHATA_CLASS,
    REAL_DDP_SWING,
    REAL_DULCE_PRACTICA,
    REAL_LATIN_HALLOWEEN,
    REAL_MILONGA_TU,
    REAL_PHU_QUOC,
    REAL_SUNDAY_PRACTICA,
)


class _Post:
    def __init__(self, title, body, published_at=None):
        self.title, self.body, self.published_at = title, body, published_at
        self.acquisition_quality = "FULL"


def _events(post, published=None):
    return process_discovered_post(None, _Post(*post, published))["events"]


def _time(text, event_type):
    reading = parse_time_range(text, event_type) or parse_start_time(text, event_type)
    if reading is None:
        return None
    return (reading.start, reading.end, reading.end_day_offset,
            reading.meridiem_evidence, reading.ambiguous)


# --- the real posts ------------------------------------------------------------

def test_the_ddp_social_runs_at_its_stated_hours_not_a_timetable_slot():
    (event,) = _events(REAL_DDP_SWING, DDP_PUBLISHED)
    assert (event.date, event.start_time, event.end_time) == ("2026-11-04", "19:00", "22:00")
    (evidence,) = [e for e in event.evidences if e.field == "time"]
    assert evidence.value["meridiem_evidence"] == "EXPLICIT"
    assert evidence.raw_text == "7:00-10:00PM"


def test_phu_quoc_states_when_its_parties_end_and_never_when_they_start():
    text = " ".join(REAL_PHU_QUOC)
    assert parse_start_time(text, "SOCIAL_WITH_CLASS") is None
    event = extract_single(*REAL_PHU_QUOC, event_type="SOCIAL_WITH_CLASS")
    assert event.date is not None
    assert (event.start_time, event.end_time) == (None, None)


def test_a_bare_evening_class_keeps_its_hour_and_its_doubt():
    """Item 6971: "1교시 7:00~8:00" - no 오전/오후 in the body. The engine
    does not decide it is 19:00; it reports the hour as written and that it
    is ambiguous, and the public pages say so."""
    event = extract_single(*REAL_BACHATA_CLASS, event_type="SOCIAL_WITH_CLASS")
    (evidence,) = [e for e in event.evidences if e.field == "time"]
    assert (event.start_time, event.end_time) == ("07:00", "08:00")
    assert evidence.value["meridiem_evidence"] == "ABSENT"
    assert evidence.value["ambiguous"] is True


def test_a_bare_social_hour_is_not_given_a_half_of_the_day():
    events = _events(REAL_LATIN_HALLOWEEN)
    timed = [e for e in events if e.start_time]
    assert [(e.date, e.start_time) for e in timed] == [("2026-11-01", "09:30")]
    (evidence,) = [e for e in timed[0].evidences if e.field == "time"]
    assert (evidence.value["meridiem_evidence"], evidence.value["ambiguous"]) == ("ABSENT", True)


@pytest.mark.parametrize("post, end", [(REAL_DULCE_PRACTICA, "14:00"),
                                       (REAL_SUNDAY_PRACTICA, "13:00")],
                         ids=["dulce-6921", "sunday-6919"])
def test_a_real_morning_practica_keeps_its_hour_without_a_doubt(post, end):
    (event,) = _events(post)
    assert (event.start_time, event.end_time) == ("11:00", end)
    (evidence,) = [e for e in event.evidences if e.field == "time"]
    assert evidence.value["meridiem_evidence"] == "ABSENT"
    assert evidence.value["ambiguous"] is False


def test_the_same_hours_stated_twice_keep_the_marked_reading():
    """Item 1264 labels "시간: 20:00~00:00" and later writes "저녁 8시부터
    12시까지" beside 밀롱가. Same hours; the marked one stays the reading."""
    (event,) = _events(REAL_MILONGA_TU)
    assert (event.start_time, event.end_time, event.end_day_offset) == ("20:00", "00:00", 1)
    (evidence,) = [e for e in event.evidences if e.field == "time"]
    assert evidence.value["meridiem_evidence"] == "EXPLICIT"


def test_the_timebar_saturday_and_sunday_still_open_at_1930():
    """DATA-02 / DATA-06 (item 6826): the DJ's PM 8:15~10:15 is not the night;
    the stated 저녁 7시30분 is, on both days."""
    events = _events(REAL_TIMEBAR, TIMEBAR_PUBLISHED)
    assert sorted((e.date, e.start_time, e.end_time) for e in events) == [
        ("2026-10-24", "19:30", None), ("2026-10-25", "19:30", None)]


# --- time roles ----------------------------------------------------------------

@pytest.mark.parametrize("text, event_type", [
    ("Milonga until 05:00 AM", "MILONGA"),
    ("Social until 02:00", "SOCIAL"),
    ("Social Parties till 5am", "SOCIAL"),
    ("소셜 ~ 02:00", "SOCIAL"),
    ("행사는 새벽 3시까지", "SOCIAL"),
    ("공연은 22시까지 진행", "SOCIAL"),
    ("공연 신청은 10월 22일 23:59까지", "SOCIAL"),
    ("밀롱가 24:00", "MILONGA"),
])
def test_an_end_or_a_deadline_is_never_a_start(text, event_type):
    assert _time(text, event_type) is None


def test_the_whole_events_hours_outrank_its_dj_and_its_end():
    """The brief's mixed case: neither the DJ's 20:15 nor the 02:00 AM end is
    the start; the social's own 19:00 is, and no end is guessed."""
    assert _time("19:00 Social starts DJ 20:15–22:15 Until 02:00 AM", "SOCIAL")[:2] == ("19:00", None)
    assert _time("소셜 19:00 시작 DJ 20:15–22:15", "SOCIAL")[:2] == ("19:00", None)


def test_a_dj_set_alone_is_kept_as_before():
    """With no stated opening a one-DJ night's set very often is its hours."""
    assert _time("DJ set 20:15–22:15", "SOCIAL")[:3] == ("20:15", "22:15", 0)


def test_a_whole_event_range_is_read_as_the_event():
    assert _time("행사 19:00–22:00", "SOCIAL")[:2] == ("19:00", "22:00")
    assert _time("일시: 11/7 PM 7:00-10:00 / 타임테이블 7:30~8:00 소셜 공연", "SOCIAL")[:2] == ("19:00", "22:00")


def test_a_slot_outside_the_labelled_hours_keeps_its_place():
    """엘마르's shape: the label is the workshop's, the social runs after it."""
    assert _time("SOCIAL DAY PM 9:00 ~ 11:30 시간: PM 8:00 ~ 9:00 강습비 : 1만원", "SOCIAL")[:2] == ("21:00", "23:30")


@pytest.mark.parametrize("text, expected", [
    ("소셜 8시 시작", ("08:00", None, 0, "ABSENT", True)),
    ("오전 8시 시작 소셜", ("08:00", None, 0, "EXPLICIT", False)),
    ("소셜 8:00 AM", ("08:00", None, 0, "EXPLICIT", False)),
    ("소셜 오후 8시", ("20:00", None, 0, "EXPLICIT", False)),
    ("소셜 8:00 PM", ("20:00", None, 0, "EXPLICIT", False)),
    ("소셜 20:00", ("20:00", None, 0, "ABSENT", False)),
])
def test_a_half_of_the_day_is_read_only_where_the_post_writes_one(text, expected):
    assert _time(text, "SOCIAL") == expected


@pytest.mark.parametrize("text, expected", [
    ("밀롱가 21:00~00:00", ("21:00", "00:00", 1)),
    ("밀롱가 21:00~01:00", ("21:00", "01:00", 1)),
    ("밀롱가 21:00~03:00", ("21:00", "03:00", 1)),
    ("밀롱가 22:00~02:00", ("22:00", "02:00", 1)),
    ("밀롱가 PM 9:00 ~ 24:00", ("21:00", "00:00", 1)),
    ("밀롱가 11:00~14:00", ("11:00", "14:00", 0)),
])
def test_overnight_and_daytime_ranges(text, expected):
    assert _time(text, "MILONGA")[:3] == expected
