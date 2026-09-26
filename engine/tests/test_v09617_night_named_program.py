"""v0.96.17 - a dated programme that calls itself NIGHT / 나이트.

홍턴's 추석 run lists four days and details each: 바차타 파티, 키좀바 파티,
살사데이, and "추석 이벤트 LATIN NIGHT ... 오픈 오후 9시". Three named
themselves in a word the dated-programme vocabulary knew; the fourth did not, so
`extract_schedule()` kept fewer than two programmes and the whole run collapsed
to one candidate - on the wrong hour and the wrong price, because the single
reading took the 23rd's first workshop and the 23rd's ticket.

**The scope is one mapping.** `DATED_PROGRAM_WORDS` is read by
`extract_schedule()` and `extract_day_list()` and by nothing else.
`EVENT_WORDS` still answers its four other questions untouched, and the tests
below assert that rather than trusting it: which clock range is the event's
time, which lone clock is its start, which price is its fee, and which segment
of an ambiguous post is the reviewed candidate.

**Measured over all 2,489 stored items, this changes one item.** 홍턴 1 -> 4
candidates, 3 dates added, 0 removed, 0 classifications changed, nothing
upcoming lost. The broad alternative - the same words in the classifier's own
night vocabulary - changes two items instead, and both are false positives: a
free class (3778) and a workshop body (3803) become events.
"""

import re

import pytest

from src import extraction_rules
from src.classifier import classify_with_image_evidence
from src.extractor import extract_day_list, extract_schedule, extract_single

from tests.fixture_v09617_night_named_program import (
    ALREADY_MATCHED_BY_PARTY,
    COURSE_MENTIONING_A_NIGHT,
    FREE_CLASS_NIGHT,
    HAVANA_CLOSED,
    HAVANA_CLOSED_DAY,
    HONGTURN,
    HONGTURN_26_FEE,
    HONGTURN_26_START,
    HONGTURN_DATES,
    KOREAN_COMPOUNDS,
    KOREAN_FALSE_FRIEND,
    LARGO,
    NIGHT_NAMED_PROGRAMS,
    NOT_THE_WORD,
    POSTER_DAY_LIST_BODY,
    POSTER_SAYING_NIGHT,
    RECAP,
    ROUNDUP,
    ROUNDUP_NAMING_ANOTHER_CLUBS_NIGHT,
    SOCIAL,
    TRAVEL,
    WORKSHOP_ONLY,
    WORKSHOP_ONLY_DAYS,
)

NIGHT_TYPES = ("SOCIAL", "SOCIAL_WITH_CLASS", "PARTY", "MILONGA",
               "MILONGA_WITH_CLASS", "PRACTICA")


def _dated(event_type=SOCIAL):
    return extraction_rules.DATED_PROGRAM_WORDS[event_type]


def _dates(rows):
    return {e.date for e in rows}


# --- T1/T2/T3 a dated programme may call itself NIGHT --------------------

def test_the_run_whose_last_night_is_called_latin_night_expands():
    ref, title, body = HONGTURN
    rows = extract_schedule(title, body, event_type=SOCIAL)
    assert rows is not None, "the run still collapses to one candidate"
    assert _dates(rows) == HONGTURN_DATES


def test_that_run_collapsed_to_one_candidate_without_the_word():
    """The defect, stated as a test: with the old vocabulary only three of the
    four days name themselves, and `extract_schedule()` needs the day it is
    already read as to survive - so the whole expansion was refused."""
    ref, title, body = HONGTURN
    plain = dict(extraction_rules.DATED_PROGRAM_WORDS)
    try:
        extraction_rules.DATED_PROGRAM_WORDS.update(extraction_rules.EVENT_WORDS)
        assert extract_schedule(title, body, event_type=SOCIAL) is None
    finally:
        extraction_rules.DATED_PROGRAM_WORDS.clear()
        extraction_rules.DATED_PROGRAM_WORDS.update(plain)


def test_the_night_named_day_carries_its_own_hour_and_no_other_days_price():
    """Both of these are corrections. The single candidate advertised 19:00 -
    the 23rd's first workshop - and 20,000원, the 23rd's ticket. The 26th's own
    line says 오픈 오후 9시 and names no price at all."""
    ref, title, body = HONGTURN
    rows = extract_schedule(title, body, event_type=SOCIAL)
    night = next(e for e in rows if e.date == "2026-09-26")
    assert night.start_time == HONGTURN_26_START
    assert night.fee == HONGTURN_26_FEE


@pytest.mark.parametrize("label,title,body,expected", NIGHT_NAMED_PROGRAMS)
def test_both_spellings_and_any_case_name_a_dated_programme(
        label, title, body, expected):
    rows = extract_schedule(title, body, event_type=SOCIAL)
    assert rows is not None, label
    assert _dates(rows) == expected, label


# --- T4..T7 the negatives, each asserted against its real mechanism ------

def test_a_recap_of_a_night_that_already_happened_makes_no_event():
    """342. Its body is the blog's own title; it names no day and classifies
    OTHER, and neither of those is the vocabulary's doing."""
    ref, title, body = RECAP
    classification, _ = classify_with_image_evidence(title, body, published=None)
    assert classification == "OTHER"
    assert extract_schedule(title, body, event_type=SOCIAL) is None


def test_a_travel_blog_naming_a_hotel_makes_no_event():
    """2417, and the honest version of this test: the vocabulary *does* match
    `나이트 호텔`, because the Korean half cannot carry a word boundary. What
    keeps the post out is that it writes no date."""
    ref, title, body = TRAVEL
    assert re.search(_dated(), KOREAN_FALSE_FRIEND, re.I), \
        "the pattern matches the hotel name - that is the premise"
    assert extract_schedule(title, body, event_type=SOCIAL) is None
    assert extract_day_list(title, body, event_type=SOCIAL,
                            source_category="EVENT") is None


def test_a_roundup_never_takes_another_clubs_night_as_its_own():
    """1576's real body first - it lists other cities' 정모 and produces
    nothing - then the constructed case, because no roundup in the corpus names
    a NIGHT yet."""
    ref, title, body = ROUNDUP
    assert extract_schedule(title, body, event_type=SOCIAL) is None
    classification, _ = classify_with_image_evidence(
        title, body, published=None, source_category="EVENT")
    assert classification == "OTHER"

    title, body = ROUNDUP_NAMING_ANOTHER_CLUBS_NIGHT
    classification, _ = classify_with_image_evidence(
        title, body, published=None, source_category="EVENT")
    assert classification == "OTHER", \
        "a roundup of other venues' nights is not this venue's night"


def test_a_free_class_called_night_stays_a_class():
    """3778, filed EVENT by danceinfo and still a free lesson. This is one of
    the two items the broad alternative turned into an event."""
    ref, title, body = FREE_CLASS_NIGHT
    classification, _ = classify_with_image_evidence(
        title, body, published=None, source_category="EVENT")
    assert classification == "CLASS"
    assert extract_day_list(title, body, event_type=SOCIAL,
                            source_category="EVENT") is None


def test_a_course_that_mentions_a_night_in_passing_is_still_a_course():
    title, body = COURSE_MENTIONING_A_NIGHT
    assert extract_day_list(title, body, event_type=SOCIAL,
                            source_category="EVENT") is None
    assert extract_schedule(title, body, event_type=SOCIAL) is None


def test_item_3840_holds_the_line_it_was_given_in_v09613():
    ref, title, body = LARGO
    classification, _ = classify_with_image_evidence(
        title, body, published=None, source_category="CLASS")
    assert classification == "CLASS"
    assert extract_day_list(title, body, event_type=SOCIAL,
                            source_category="CLASS") is None


# --- T8 the word has to be the word --------------------------------------

@pytest.mark.parametrize("label,text,expected", NOT_THE_WORD)
def test_a_substring_is_not_the_word(label, text, expected):
    assert bool(re.search(_dated(), text, re.I)) is expected, label


def test_one_string_matches_for_a_reason_that_is_not_ours():
    """`#MidsummerNightLatinTangoParty` matches - on the bare `party` that
    `EVENT_WORDS` has always carried. Pinned so nobody later blames NIGHT."""
    assert re.search(extraction_rules.EVENT_WORDS[SOCIAL],
                     ALREADY_MATCHED_BY_PARTY, re.I)


@pytest.mark.parametrize("text", KOREAN_COMPOUNDS)
def test_the_korean_half_matches_compounds(text):
    """Korean has no word boundary, and a night is written as one word."""
    assert re.search(_dated(), text, re.I)


# --- T9 the scope: EVENT_WORDS itself must not move ----------------------

def test_event_words_is_not_widened():
    """The whole point of a third mapping. `EVENT_WORDS` decides which clock
    range is the event's time, which lone clock is its start, which price is
    its fee, and which segment of an ambiguous post is reviewed - none of which
    this release has any evidence about."""
    for event_type, pattern in extraction_rules.EVENT_WORDS.items():
        assert "night" not in pattern.lower(), event_type
        assert "나이트" not in pattern, event_type


def test_the_dated_programme_vocabulary_adds_the_word_to_night_types_only():
    for event_type in NIGHT_TYPES:
        if event_type not in extraction_rules.DATED_PROGRAM_WORDS:
            continue
        assert re.search(extraction_rules.DATED_PROGRAM_WORDS[event_type],
                         "LATIN NIGHT", re.I), event_type
    assert extraction_rules.DATED_PROGRAM_WORDS["CLASS"] == \
        extraction_rules.EVENT_WORDS["CLASS"], \
        "a class is not a night, and an evening course is not its own social"


def test_the_dated_programme_vocabulary_keeps_every_word_it_had():
    for event_type, pattern in extraction_rules.EVENT_WORDS.items():
        assert extraction_rules.DATED_PROGRAM_WORDS[event_type].startswith(pattern)


def test_a_time_beside_night_is_not_the_events_time():
    """`_pick_reading` still reads `EVENT_WORDS`, so a clock range sitting next
    to the word NIGHT is not thereby the event's own time."""
    reading = extraction_rules.parse_time_range(
        "16:45-18:15 LATIN NIGHT 20:00-22:30 소셜", event_type=SOCIAL)
    assert reading is not None and reading.start == "20:00"


TWO_PROGRAMMES = ("11월 6일(금) LATIN NIGHT 오후 7시~9시 DJ 쿵 "
                  "11월 7일(토) 토요 소셜 오후 9시~11시 DJ RICKY")


def test_widening_event_words_would_move_an_unrelated_posts_hour():
    """The measurable reason this release does not touch `EVENT_WORDS`.

    A post with two programmes, one called LATIN NIGHT and one called 소셜,
    reads as the 소셜's 21:00 today. Add the word to `EVENT_WORDS` and the same
    post reads 19:00 - the NIGHT segment's hour - because `_select_context` and
    `_pick_reading` would then find two matching programmes instead of one.
    Nothing in this release has any evidence about that post's hour, so the
    reading stays where it is.
    """
    shipped = extract_single("주말 안내", TWO_PROGRAMMES, event_type=SOCIAL)
    assert shipped.start_time == "21:00"

    original = dict(extraction_rules.EVENT_WORDS)
    try:
        for event_type in ("SOCIAL", "SOCIAL_WITH_CLASS"):
            extraction_rules.EVENT_WORDS[event_type] = (
                original[event_type] + "|" + extraction_rules._NIGHT_NAMED)
        widened = extract_single("주말 안내", TWO_PROGRAMMES, event_type=SOCIAL)
    finally:
        extraction_rules.EVENT_WORDS.clear()
        extraction_rules.EVENT_WORDS.update(original)
    assert widened.start_time == "19:00", \
        "if this stops differing, the two vocabularies have converged"


# --- T10/T11 v0.96.16's own protections, unmoved -------------------------

def test_a_day_the_post_closes_is_still_not_a_night():
    ref, title, body = HAVANA_CLOSED
    rows = extract_schedule(title, body, event_type=SOCIAL)
    produced = _dates(rows) if rows else {
        extract_single(title, body, event_type=SOCIAL).date}
    assert HAVANA_CLOSED_DAY not in produced


def test_a_workshop_only_day_is_still_not_a_night():
    ref, title, body = WORKSHOP_ONLY
    for rows in (extract_schedule(title, body, event_type=SOCIAL),
                 extract_day_list(title, body, event_type=SOCIAL,
                                  source_category="EVENT")):
        if rows:
            assert not (_dates(rows) & WORKSHOP_ONLY_DAYS)


def test_a_poster_saying_night_never_qualifies_a_listed_day():
    """A poster is evidence about the post, never a day's own line. Both of this
    post's days name only a lesson, and `ELMAR LATIN NIGHT` on its poster may
    not turn either of them into a night."""
    title, body = POSTER_DAY_LIST_BODY
    assert extract_day_list(title, body, event_type=SOCIAL,
                            source_category="EVENT",
                            image_texts=POSTER_SAYING_NIGHT) is None
