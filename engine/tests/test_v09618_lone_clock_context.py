"""v0.96.18 - an event's start time after somebody else's clock range.

`parse_start_time()` decided two things by position and presence rather than by
what a word is near, and both cost an hour the post states in plain text:

* `_is_other_programme()` is an absolute veto over a symmetric window. BABARU's
  `PM 8:00~9:00 (워크샵), PM 9:00 START (소셜)` has the workshop's word four
  characters before the 9:00 and the social's one character after, and every
  candidate was vetoed - so the 21:00 could only come from a poster.
* where several lone clocks sat near the event's own word, the first by position
  won. 홍턴's 9/23 line put its 파티 heading beside three clocks and advertised
  the first workshop's 오후 7시 instead of the 오후 9시 it opens at.

Weighing distance then let through a clock the absolute veto had been catching
by accident - the tail of a range - so that is refused explicitly: BAYA's
`9:00-1:00 소셜` is not a social starting at 01:00.

Measured over all 2,504 stored items with a `git stash` baseline and a harness
that replays Production's own poster OCR: four posts change, 2 None->time, 5
time->time, 0 time->None, and no date, cardinality or classification change
anywhere. KET regression 0 of 682.
"""

import pytest

from src import extraction_rules
from src.classifier import classify_with_image_evidence
from src.extractor import extract_schedule, extract_single

from tests.fixture_v09618_lone_clock_context import (
    EVENT_CONTEXT_BODY,
    NO_MERIDIEM_STAYS_LITERAL,
    EVENT_CONTEXTS,
    MILONGA,
    N3_OTHER_CLUB,
    N3_REAL,
    N3_REAL_DATES,
    OPENING_VARIANTS,
    RANGE_STILL_WINS,
    RECOVERED,
    REFUSED,
    SOCIAL,
    UNFIXED_RANGE_SIDE,
    UNFIXED_TRUTH,
)


def _start(body, event_type=SOCIAL):
    reading = extraction_rules.parse_start_time(body, event_type=event_type)
    return reading.start if reading else None


# --- the hours this release recovers -------------------------------------

@pytest.mark.parametrize("label,body,event_type,expected", RECOVERED)
def test_an_event_clock_after_someone_elses_range_is_read(
        label, body, event_type, expected):
    assert _start(body, event_type) == expected, label


@pytest.mark.parametrize("label,body,expected", OPENING_VARIANTS)
def test_the_same_statement_in_every_notation_gives_the_same_hour(
        label, body, expected):
    assert _start(body) == expected, label


@pytest.mark.parametrize("word,event_type,expected", EVENT_CONTEXTS)
def test_the_rule_is_not_specific_to_one_scenes_word(word, event_type, expected):
    assert _start(EVENT_CONTEXT_BODY.format(word=word), event_type) == expected


@pytest.mark.parametrize("label,body,expected,ambiguous", NO_MERIDIEM_STAYS_LITERAL)
def test_a_bare_clock_is_not_promoted_to_the_evening(
        label, body, expected, ambiguous):
    """This release recovers clocks; it does not start guessing PM for them.
    `9:00 START` with no marker is 09:00 and says so."""
    reading = extraction_rules.parse_start_time(body, event_type=SOCIAL)
    assert reading is not None, label
    assert reading.start == expected, label
    assert reading.ambiguous is ambiguous, label


def test_babarus_start_no_longer_needs_a_poster():
    """The release's own point: 21:00 out of the text, with TEXT provenance.

    Production carried 20:00 on all three of BABARU's nights - the workshop
    hour, read off its poster - because the body yielded nothing at all.
    """
    label, body, event_type, expected = RECOVERED[0]
    event = extract_single("BABARU 소셜 OPEN!", body, event_type=SOCIAL)
    assert event.start_time == "21:00"
    time_evidence = next(e for e in event.evidences if e.field == "time")
    assert time_evidence.evidence_type == "TEXT"
    assert "9:00" in time_evidence.raw_text


# --- what must still give nothing ---------------------------------------

@pytest.mark.parametrize("label,body,event_type", REFUSED)
def test_a_clock_that_is_not_the_events_start_is_still_refused(
        label, body, event_type):
    assert _start(body, event_type) is None, label


def test_a_ranges_tail_is_never_an_independent_start():
    """The false positive that weighing distance introduced, stated on its own.

    `9:00-1:00 소셜` puts the event's word nearest the *end* of its range. Left
    alone, the social read as starting at 01:00.
    """
    assert _start("일정정보 8:00-9:00 워크샵, 9:00-1:00 소셜") is None
    assert _start("9:00-10:00 p.m.: Kizomba 파티") is None


def test_a_nearer_class_word_still_wins():
    """The veto is now comparative, not gone. When the class word is the nearer
    of the two, the clock is still the class's."""
    assert _start("소셜 안내 오후 7시 워크샵") is None
    assert _start("워크샵 오후 7시 소셜 안내") == "19:00", \
        "and when the event word is nearer, the clock is the event's"


# --- the range guard, unchanged -----------------------------------------

@pytest.mark.parametrize("label,body,event_type,start,end", RANGE_STILL_WINS)
def test_a_post_that_states_its_own_range_is_still_read_as_a_range(
        label, body, event_type, start, end):
    reading = extraction_rules.parse_time_range(body, event_type=event_type)
    assert reading is not None, label
    assert (reading.start, reading.end) == (start, end), label
    assert _start(body, event_type) is None, \
        "the lone-clock rule must not race parse_time_range()"


def test_the_range_guard_is_kept_deliberately():
    """Deleting it was measured over the whole stored corpus and changes
    nothing, so it stays: a stated range is better evidence than a lone clock.
    """
    body = "소셜 20:00-22:30"
    assert list(extraction_rules._readings(body)), "the body states a range"
    assert _start(body) is None


# --- v0.96.17's own behaviour, unmoved ----------------------------------

def test_v09617_night_named_programme_still_expands():
    """홍턴's four-night run still reads as four nights - and its 9/23 now
    carries the 21:00 it opens at instead of the first workshop's 19:00."""
    from tests.fixture_v09617_night_named_program import HONGTURN, HONGTURN_DATES

    ref, title, body = HONGTURN
    rows = extract_schedule(title, body, event_type=SOCIAL)
    assert rows is not None
    assert {e.date for e in rows} == HONGTURN_DATES
    by_date = {e.date: e for e in rows}
    assert by_date["2026-09-23"].start_time == "21:00"
    assert by_date["2026-09-26"].start_time == "21:00"


# --- v0.96.17 N3, fixtured at last (§4) --------------------------------

def test_a_post_naming_its_own_future_party_keeps_only_its_own_day():
    """3822 names `10월 24일 SNS 4주년 파티` in passing. v0.96.15's first guard -
    every programme day must be one the post wrote with a year - is what keeps
    October out, and this is the fixture v0.96.17 shipped without."""
    ref, title, body = N3_REAL
    rows = extract_schedule(title, body, event_type=SOCIAL)
    produced = ({e.date for e in rows} if rows
                else {extract_single(title, body, event_type=SOCIAL).date})
    assert produced == N3_REAL_DATES


def test_a_post_naming_another_clubs_night_does_not_adopt_it():
    """Constructed: a two-day run pointing at another club's NIGHT on a third
    day. Neither the day nor the night becomes this post's."""
    title, body = N3_OTHER_CLUB
    rows = extract_schedule(title, body, event_type=SOCIAL)
    produced = {e.date for e in rows} if rows else set()
    assert "2026-11-20" not in produced
    classification, _ = classify_with_image_evidence(
        title, body, published=None, source_category="EVENT")
    assert classification in ("CLASS", "OTHER", "SOCIAL", "SOCIAL_WITH_CLASS")


# --- the case this release did not fix, closed by the next one ----------

def test_the_range_side_of_the_defect_was_closed_by_v09619():
    """가또땅고 3199, kept as the hand-off it was written to be.

    v0.96.18 pinned this as the *range* side of the same defect: the milonga's
    own `9:00pm-12:30am 밀롱가` was rejected because 오픈특강 sits within sixteen
    characters before it, so only lone clocks were left and the post read 22:30 -
    the performance's hour. The test asserted that state and said it should start
    failing when the range side was fixed. v0.96.19 fixed it, by weighing the
    nearest class word against the nearest event word for a range too, so the
    assertion is inverted here rather than deleted: the range is now read, and
    the 22:30 it used to settle for is gone.
    """
    ref, title, body = UNFIXED_RANGE_SIDE
    reading = extraction_rules.parse_time_range(body, event_type=MILONGA)
    assert reading is not None, "v0.96.19 reads the milonga's own range"
    assert reading.start == UNFIXED_TRUTH
    # The lone-clock rule still finds the performance's 22:30 if asked in
    # isolation - it is the only clock in the body that is not inside a range.
    # What changed is that it is no longer asked: a range the event names is
    # better evidence, and `extract_single()` takes it.
    assert _start(body, MILONGA) == "22:30"
    event = extract_single(title, body, event_type=MILONGA)
    assert (event.start_time, event.end_time) == ("21:00", "00:30")
