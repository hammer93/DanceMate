"""v0.96.40: a poster's clock is read off the poster's own rows.

Poster OCR text keeps the poster's layout - one line per printed row - and
three things in the clock grammar did not respect it. Measured over all 4,443
stored Production items (old and new engine side by side, the runtime's own
route): four readings change and nothing else does - no candidate, no
classification, no date, no venue, no fee. Each of the four was checked
against its poster image by eye; the answers below are what the posters
print, not what the OCR says.

* A Korean clock's minutes were joined across a line break. "12시" with a
  stray "9" two rows below became 00:09 (item 5601), "3시" with a "5" from
  the next row 03:05 (item 5859), and "1시" with the next row's fee
  "10,000원" 01:10 (item 3809).
* A lone "24:00" was taken as a start. It is the moment a day ends: K-TANGO
  CF's timetable (item 643) prints "PM 20:00 - PM 24:00" in one cell, the OCR
  splits the cell, and the night was stored at 00:00 on the day it ends.
* "7pm"'s marker was not required to be its own: "VIP 밀롱가1   PM 23:30 -"
  read as 13:00 - the milonga's number "1" taking the next column's PM.

And with those gone, item 643 still had no right answer: four days of
milongas, every clock beside a 밀롱가. A poster time the engine cannot place
is not taken (IMAGE_TIME_AMBIGUOUS, as for an hour with no meridiem); a post's
own body keeps v0.96.18's ranking, where "PM9:20~ 금요소셜파티 Showtime :
PM 10:30~" does open at 21:20 (item 6189 - that refusal in the body was
measured and lost three right hours, so it is not made there).
"""

from __future__ import annotations

import pytest

from src import extraction_rules
from src.extractor import extract_single, extract_with_image_fallback
from tests.fixture_v09640_poster_ocr import POSTERS


def _image(item: int, published: str | None = None):
    poster = POSTERS[item]
    return extract_with_image_fallback(
        poster["title"], "", event_type=poster["event_type"], published=published,
        image_texts=[(poster["image"], poster["ocr_text"])])


def _time_rows(ev):
    return [e for e in ev.evidences if e.field == "time"]


def _context(ev):
    return [(e.value, e.raw_text) for e in ev.evidences if e.field == "context"]


# --- the four posters, as Production stores their OCR ------------------------

@pytest.mark.parametrize("item, start, end, offset, raw", [
    # poster: 오후 9시 – 12시 (the "9" two rows below is not a minute)
    (5601, "21:00", "00:00", 1, "오후 9시 - 12시"),
    # poster: 저녁 9시~ 3시 (the "5" on the next row is not a minute)
    (5859, "21:00", "03:00", 1, "저녁 9시~ 3시"),
    # poster: 시간 오후 9시~1시, 입장료 10,000원 on the row below
    (3809, "21:00", "01:00", 1, "오후 9시~1시"),
])
def test_a_poster_clock_does_not_take_the_next_rows_digits(item, start, end, offset, raw):
    ev = _image(item)
    assert (ev.start_time, ev.end_time, ev.end_day_offset) == (start, end, offset)
    (row,) = _time_rows(ev)
    assert row.raw_text == raw
    assert row.inference == POSTERS[item]["image"]       # the image stays the evidence
    assert row.value["meridiem_evidence"] == "EXPLICIT" and row.value["ambiguous"] is False


def test_a_timetable_poster_with_lost_rows_gives_no_time():
    """K-TANGO CF 2025 (item 643, event 1597462): the 05.08 night is
    20:00-24:00 on the poster. The OCR text cannot say so - its rows are
    interleaved - so no clock is claimed, and what the poster did say is kept
    for a person."""
    ev = _image(643, published="2025-03-31")
    assert ev.start_time is None and ev.end_time is None
    assert _time_rows(ev) == []
    assert ("IMAGE_TIME_AMBIGUOUS", "PM 23:30") in _context(ev)
    assert ev.date == "2025-05-08"                       # the date it read is unchanged


def test_the_timetable_never_reads_24_00_or_a_milonga_number_as_a_start():
    text = POSTERS[643]["ocr_text"]
    reading = extraction_rules.parse_start_time(text, "MILONGA")
    assert reading is None or reading.start not in ("00:00", "13:00")
    assert extraction_rules.start_is_contested(text, "MILONGA")


# --- the brief's cases, each answered by what the text itself says ----------

@pytest.mark.parametrize("text, expected", [
    # same line, written out: the minutes are the text's own
    ("오후 9시 - 12시 9분", ("21:00", "00:09", 1)),
    ("저녁 9시~3시 5분", ("21:00", "03:05", 1)),
    ("오후 3시 5분~6시", ("15:05", "18:00", 0)),
    ("오후 8시 30 ~ 11시 30분", ("20:30", "23:30", 0)),     # "8시 30" on one line
    # the next line is something else the poster prints
    ("오후 9시 - 12시\n\n9\n\n오아시스 라틴학원", ("21:00", "00:00", 1)),
    ("저녁 9시~ 3시\n\n5   PHOTO 이작", ("21:00", "03:00", 1)),
    ("오후 9시~1시\n 10,000원 (온통대전 캐쉬백 가맹점)", ("21:00", "01:00", 1)),
    ("오후 9시~1시\n10월 3일", ("21:00", "01:00", 1)),          # a date on the next row
    ("오후 9시~1시\n3층", ("21:00", "01:00", 1)),                # an address on the next row
    # ranges with no marker that only a 24-hour clock can mean
    ("21:00~03:00", ("21:00", "03:00", 1)),
    ("20:00~00:00", ("20:00", "00:00", 1)),
    ("21:00 ~ 24:00", ("21:00", "00:00", 1)),
    ("12:09~14:00", ("12:09", "14:00", 0)),
])
def test_ranges_read_what_the_text_says(text, expected):
    reading = extraction_rules.parse_time_range(text, "SOCIAL")
    assert reading is not None, text
    assert (reading.start, reading.end, reading.end_day_offset) == expected


@pytest.mark.parametrize("text, start, evidence, ambiguous", [
    ("오후 9시 소셜", "21:00", "EXPLICIT", False),
    ("오전 12시 시작", "00:00", "EXPLICIT", False),
    ("12시 9분 시작", "12:09", "ABSENT", True),          # 12:09, not settled by a marker
    ("9 PM 밀롱가", "21:00", "EXPLICIT", False),         # "9 PM": the marker is its own
    ("7pm 소셜", "19:00", "EXPLICIT", False),
])
def test_lone_starts_read_what_the_text_says(text, start, evidence, ambiguous):
    reading = extraction_rules.parse_start_time(text, "SOCIAL")
    assert (reading.start, reading.meridiem_evidence, reading.ambiguous) == \
        (start, evidence, ambiguous)


@pytest.mark.parametrize("text", [
    "PM 24:00 밀롱가",                                 # 24:00 closes a night
    "밀롱가 24:00 시작",
    "밀롱가1         PM 23:30 -",                       # the "1" is not 1pm
])
def test_what_is_never_a_start(text):
    reading = extraction_rules.parse_start_time(text, "MILONGA")
    assert reading is None or reading.start not in ("00:00", "13:00"), text


def test_a_marker_followed_by_its_own_clock_is_not_borrowed():
    assert extraction_rules.parse_start_time("밀롱가 1 PM 23:30", "MILONGA").start == "23:30"
    reading = extraction_rules.parse_time_range("7 pm - 11 pm", "SOCIAL")
    assert (reading.start, reading.end) == ("19:00", "23:00")


def test_a_fee_or_date_on_the_same_line_is_not_a_minute_either_way():
    """Unchanged by this release: a fee or date after the clock on the same
    line was never a minute ("10,000" does not fit two digits)."""
    reading = extraction_rules.parse_time_range("오후 9시~1시 입장료 10,000원", "SOCIAL")
    assert (reading.start, reading.end) == ("21:00", "01:00")


# --- what a post's own body keeps --------------------------------------------

def test_a_bodys_own_ranking_is_unchanged():
    """Item 6189's body: two clocks beside the social's word, the first by
    position is when it opens. Refusing here was measured and lost three right
    hours (6181, 6189, 6434), so only a poster's time is refused this way."""
    body = ("일정정보 PM 9:20~ 장소 강턴 DJ 탄 ☑10월 16일(금) PM9:20~ 금요소셜파티"
            "(SSC 개강파티) Showtime : PM 10:30~")
    ev = extract_single("SSC 개강파티", body, event_type="SOCIAL_WITH_CLASS",
                        published="2026-10-14")
    assert ev.start_time == "21:20"
    assert not extraction_rules.start_is_contested(
        "오후 9시 소셜 오픈", "SOCIAL")


def test_a_body_time_is_never_replaced_by_the_poster():
    poster = POSTERS[5601]
    ev = extract_with_image_fallback(
        poster["title"], "2026-10-05 시간 오후 8시~11시", event_type="SOCIAL",
        published="2026-10-01", image_texts=[(poster["image"], poster["ocr_text"])])
    assert (ev.start_time, ev.end_time) == ("20:00", "23:00")
    assert all(row.evidence_type != "IMAGE_OCR" for row in _time_rows(ev))
