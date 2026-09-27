"""v0.96.21 - read an English month's own day range.

`DATE_PATTERNS` spoke no English, so SEOUL lindyfest 2026's "DATE Oct 8-11,
2026" produced no date and no event even though the page is robots-permitted
and its whole body fetches. This adds that one grammar and follows the
multi-day contract v0.91.0 PHASE 5 already set for "9.18-20": the first day is
`event_date`, the span is a `MULTI_DAY_EVENT` evidence, and nothing expands
into one event per day.
"""

from __future__ import annotations

import pytest

from src import extractor
from src.extractor import _norm_date, extract_single

from tests.fixture_v09621_english_day_range import (
    EVERY_MONTH,
    EXISTING_RANGES,
    KOREAN_WINS,
    LINDYFEST_BODY,
    LINDYFEST_DATE,
    LINDYFEST_SPAN_RAW,
    LINDYFEST_TITLE,
    NOT_A_DATE,
    PARSED,
    REFUSED_AS_UNPLACEABLE,
)


# --- the grammar ----------------------------------------------------------

@pytest.mark.parametrize("text,expected", PARSED)
def test_an_english_month_day_range_resolves_to_its_first_day(text, expected):
    date, raw, provenance = _norm_date(text, published=None)
    assert date == expected, text
    assert provenance == extractor.EXPLICIT_YEAR, text
    assert raw, "the matched text is recorded as the date's evidence"


@pytest.mark.parametrize("name,number", EVERY_MONTH)
def test_every_month_name_and_abbreviation_is_understood(name, number):
    """Long and short, with and without the abbreviating full stop."""
    for written in (name, f"{name}."):
        date, _, provenance = _norm_date(f"{written} 10-12, 2026", published=None)
        assert date == f"2026-{number:02d}-10", written
        assert provenance == extractor.EXPLICIT_YEAR


def test_case_does_not_matter():
    for written in ("Oct", "OCT", "oct", "oCt", "October", "OCTOBER", "october"):
        date, _, _ = _norm_date(f"{written} 8-11, 2026", published=None)
        assert date == "2026-10-08", written


def test_september_is_not_read_as_sep_with_tember_left_over():
    """The month alternation is longest-first; the short forms must not eat the
    long one's letters and leave a tail that breaks the match."""
    for written in ("Sep", "Sept", "Sept.", "September"):
        date, _, _ = _norm_date(f"{written} 28-30, 2026", published=None)
        assert date == "2026-09-28", written


# --- validation -----------------------------------------------------------

@pytest.mark.parametrize("text", REFUSED_AS_UNPLACEABLE)
def test_a_range_that_cannot_exist_is_a_refusal_not_a_date(text):
    """Backwards, or naming a day the month has not. The text is recorded so
    the missing date reads as "we saw a date and could not place it" - the same
    answer an impossible numeric date already gives."""
    date, raw, provenance = _norm_date(text, published=None)
    assert date is None, text
    assert raw, "the attempt is still reported"
    assert provenance == extractor.UNKNOWN_YEAR, text


@pytest.mark.parametrize("text", NOT_A_DATE)
def test_text_that_is_not_a_date_matches_nothing_at_all(text):
    """Not even as an attempt: a month's name used as an ordinary word, or a
    day outside 1..31. Matching would block a later pattern from reading a real
    date from the same text."""
    date, raw, _ = _norm_date(text, published=None)
    assert date is None, text
    assert raw is None, f"{text!r} must not register as a date attempt"


def test_an_impossible_range_leaves_a_real_date_in_the_same_text_readable():
    """The reason the day bound lives in the pattern rather than the resolver."""
    date, raw, _ = _norm_date("Oct 8-99 tickets, 2026년 10월 3일 파티",
                              published=None)
    assert date == "2026-10-03"


def test_a_leap_day_is_judged_against_the_year_the_text_states():
    assert _norm_date("Feb 28-29, 2028", published=None)[0] == "2028-02-28"
    assert _norm_date("Feb 28-29, 2026", published=None)[0] is None


# --- the multi-day contract ----------------------------------------------

def test_the_span_is_flagged_and_never_expanded_into_one_event_per_day():
    event = extract_single("SEOUL lindyfest 2026", "Oct 8-11, 2026",
                           event_type="SOCIAL")
    assert event.date == "2026-10-08"
    span = [e for e in event.evidences if e.value == "MULTI_DAY_EVENT"]
    assert len(span) == 1, "exactly one span flag"
    assert span[0].field == "context"
    assert span[0].inference == "DATE_RANGE_START_ONLY"
    assert span[0].raw_text == "Oct 8-11"


def test_the_english_span_is_flagged_the_same_way_the_numeric_one_is():
    """v0.91.0's "9.18-20" and this must be indistinguishable downstream."""
    numeric = extract_single("BAL&HOP", "BAL&HOP 2026 - 9.18-20",
                             event_type="SOCIAL")
    english = extract_single("SLF", "Oct 8-11, 2026", event_type="SOCIAL")
    for event in (numeric, english):
        span = next(e for e in event.evidences if e.value == "MULTI_DAY_EVENT")
        assert span.field == "context"
        assert span.inference == "DATE_RANGE_START_ONLY"


def test_no_end_date_is_invented():
    event = extract_single("SLF", "Oct 8-11, 2026", event_type="SOCIAL")
    assert not hasattr(event, "end_date") or getattr(event, "end_date") is None


# --- the existing contract, unmoved --------------------------------------

@pytest.mark.parametrize("text,published,expected", EXISTING_RANGES)
def test_the_numeric_and_korean_ranges_read_exactly_as_before(
        text, published, expected):
    assert _norm_date(text, published=published)[0] == expected, text


def test_a_korean_date_earlier_in_date_patterns_still_wins():
    """`_norm_date()` stops at the first pattern that matches anywhere, so the
    new pattern sits second-to-last: a Korean date in a title must still beat
    an English range further down the body."""
    text, expected = KOREAN_WINS
    assert _norm_date(text, published=None)[0] == expected


def test_the_new_pattern_sits_second_to_last():
    """Only the loosest bare "m/d" fallback may come after it."""
    patterns = [p.pattern for p in extractor.DATE_PATTERNS]
    assert "?P<mon>" in patterns[-2]
    assert "?P<mon>" not in patterns[-1]
    assert sum("?P<mon>" in p for p in patterns) == 1


def test_a_single_english_day_is_still_not_a_date():
    """This release adds a *range*. "October 15, 2026" on its own is out of
    scope and must stay unread rather than half-read."""
    assert _norm_date("October 15, 2026", published=None)[0] is None


def test_a_cross_month_english_range_is_still_out_of_scope():
    """"Oct 30-Nov 2, 2026" is a separate gap, recorded as a next-release
    candidate. It must not be half-read as October the 30th by this pattern."""
    date, raw, _ = _norm_date("Oct 30-Nov 2, 2026", published=None)
    assert date is None
    assert raw is None


# --- SEOUL lindyfest, end to end -----------------------------------------

def test_seoul_lindyfest_reads_its_own_date():
    """The release's target, on the page's real visible text.

    v0.96.20 fetched this body in full and stored no date and no event. The
    only thing that changed is that `DATE_PATTERNS` now reads the sentence the
    page actually writes.
    """
    event = extract_single(LINDYFEST_TITLE, LINDYFEST_BODY, event_type="SOCIAL")
    assert event.date == LINDYFEST_DATE
    date_evidence = next(e for e in event.evidences if e.field == "date")
    assert date_evidence.inference == extractor.EXPLICIT_YEAR
    assert "Oct 8-11, 2026" in date_evidence.raw_text
    span = next(e for e in event.evidences if e.value == "MULTI_DAY_EVENT")
    assert span.raw_text == LINDYFEST_SPAN_RAW


def test_seoul_lindyfest_through_the_whole_pipeline():
    """Not the regex alone: discovery's own record shape, the classifier, and
    candidate construction, exactly as `live_pipeline` runs them."""
    from src import live_pipeline
    from src.collectors.base import RawPostRecord

    post = RawPostRecord(
        source_id="SRC-W-014", platform="WEB",
        source_url="https://seoullindyfest.com/", title=LINDYFEST_TITLE,
        body=LINDYFEST_BODY, published_at=None,
        acquisition_quality="FETCHED_PARTIAL",
        known_event_type="SOCIAL", class_event_opt_in=False,
        source_category=None, event_terms=None,
    )
    result = live_pipeline.process_discovered_post(
        None, post, source_role="PRIMARY",
        image_texts=None, trusted_classification_texts=None)
    dated = [e for e in result["events"] if e.date]
    assert len(dated) == 1, "one event, not one per day of the festival"
    assert dated[0].date == LINDYFEST_DATE
    assert dated[0].event_type in ("SOCIAL", "SOCIAL_WITH_CLASS")


def test_the_page_produced_nothing_before_this_release():
    """Pinned so the gap cannot silently come back: with the English pattern
    removed, the same body yields no date at all."""
    without = [p for p in extractor.DATE_PATTERNS if "?P<mon>" not in p.pattern]
    original = extractor.DATE_PATTERNS
    try:
        extractor.DATE_PATTERNS = without
        assert _norm_date(LINDYFEST_BODY, published=None) == (None, None, None)
    finally:
        extractor.DATE_PATTERNS = original
