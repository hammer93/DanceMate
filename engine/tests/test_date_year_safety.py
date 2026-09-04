"""Which year a bare 9/25 belongs to.

A post says "9/25" and means the 25th of September near the time it was
written. The extractor used to attach a hardcoded 2026 instead, so a blog post
from 2024 became an event this week -- someone reading DanceMate would have
gone out on the wrong night for an event that happened two years ago.

Missing a date is recoverable. A wrong one is the failure this whole service
exists to avoid, so where the year cannot be settled, none is claimed.
"""

from datetime import date

import pytest

from src.extractor import (EXPLICIT_YEAR, MAX_DAYS_FROM_POST, SOURCE_YEAR,
                           UNKNOWN_YEAR, _norm_date, extract_single)


# --- 16: the case that started this -----------------------------------------

def test_a_two_year_old_post_does_not_become_this_weeks_event():
    """The real row: blog.naver.com/ira98/223597115302, collected 2026-09-04.

    Published 2024-09-26, body says 9/25, and it was listed as an upcoming
    event on 2026-09-25.
    """
    found, raw, provenance = _norm_date(
        "2024 서울 살사 위크! 서울 살사클럽에서 일주일 내내 ... 9/25",
        published=date(2024, 9, 26))
    assert found != "2026-09-25"
    assert found == "2024-09-25"
    assert provenance == SOURCE_YEAR
    assert raw


@pytest.mark.parametrize("text,published,expected", [
    # The other two the audit turned up on the board, same shape.
    ("10월 12일 전야제 밀롱가", date(2011, 6, 4), "2011-10-12"),
    ("[월간 슬로우 소셜파티_SlowJam 12월12일]", date(2025, 12, 8), "2025-12-12"),
])
def test_the_other_stale_posts_stay_in_their_own_year(text, published, expected):
    found, _, provenance = _norm_date(text, published=published)
    assert found == expected
    assert provenance == SOURCE_YEAR
    assert not found.startswith("2026")


# --- 17.1, 17.2: an explicit year is the post speaking for itself ------------

@pytest.mark.parametrize("text,expected", [
    ("2026년 9월 25일 밀롱가", "2026-09-25"),
    ("2026-09-25 밀롱가", "2026-09-25"),
    ("26년 09월 25일 밀롱가", "2026-09-25"),
])
def test_an_explicit_current_year_is_used_as_written(text, expected):
    found, _, provenance = _norm_date(text, published=date(2026, 9, 1))
    assert (found, provenance) == (expected, EXPLICIT_YEAR)


def test_an_explicit_year_wins_over_an_old_post():
    """A 2024 post announcing 2026 is announcing 2026. It said so."""
    found, _, provenance = _norm_date("2026년 9월 25일", published=date(2024, 9, 26))
    assert (found, provenance) == ("2026-09-25", EXPLICIT_YEAR)


def test_an_explicit_old_year_stays_old():
    found, _, provenance = _norm_date("2024-09-25 살사", published=date(2026, 9, 4))
    assert (found, provenance) == ("2024-09-25", EXPLICIT_YEAR)


# --- 17.3, 17.4: a recent post, forwards and backwards ----------------------

def test_a_recent_post_announcing_a_date_days_ahead():
    found, _, provenance = _norm_date("9/5 토요밀롱가", published=date(2026, 9, 1))
    assert (found, provenance) == ("2026-09-05", SOURCE_YEAR)


def test_a_recent_post_referring_to_a_date_days_behind():
    """Posts get written after the night as well as before it."""
    found, _, provenance = _norm_date("8월 30일 밀롱가", published=date(2026, 9, 2))
    assert (found, provenance) == ("2026-08-30", SOURCE_YEAR)


# --- 17.5, 17.6: the old post must not jump ---------------------------------

def test_the_same_month_and_day_resolves_to_the_posts_own_year():
    found, _, _ = _norm_date("9월 4일 밀롱가", published=date(2019, 9, 4))
    assert found == "2019-09-04"


@pytest.mark.parametrize("year", [2011, 2015, 2019, 2024, 2025])
def test_no_old_post_is_ever_pulled_into_the_current_year(year):
    found, _, _ = _norm_date("9월 25일 밀롱가", published=date(year, 9, 26))
    assert found is None or found.startswith(str(year)), found


# --- 17.7, 17.8: the turn of the year ---------------------------------------

def test_december_post_about_january_rolls_forward():
    """1/3 written on the 28th of December is next week, not eleven months ago."""
    found, _, provenance = _norm_date("1/3 신년 밀롱가", published=date(2025, 12, 28))
    assert (found, provenance) == ("2026-01-03", SOURCE_YEAR)


def test_january_post_about_december_rolls_back():
    found, _, _ = _norm_date("12월 28일 송년 밀롱가", published=date(2026, 1, 3))
    assert found == "2025-12-28"


def test_the_turn_of_the_year_is_not_a_rule_of_its_own():
    """Nothing here special-cases December. It is only ever nearest-to-the-post,
    which is why a June post about January does not roll anywhere silly."""
    found, _, _ = _norm_date("1월 3일 밀롱가", published=date(2026, 6, 15))
    assert found == "2026-01-03"


# --- 13: the distance guard, at both edges ----------------------------------

def test_the_distance_guard_sits_in_the_gap_the_data_left():
    """Measured on the board: real announcements land within -13..+22 days of
    their post, and the wrong-year cluster starts at 369. The threshold has to
    be clear of both."""
    assert 22 < MAX_DAYS_FROM_POST < 369


def test_the_year_chosen_is_the_one_nearest_the_post():
    """Not "the post's year" -- the nearest of the three around it.

    A post on New Year's Day mentioning 7월 4일 is nearer to last July than to
    the coming one, and that is the reading taken. This is the same mechanism
    that makes the December-to-January case work, stated as itself.
    """
    found, _, provenance = _norm_date("7월 4일 밀롱가", published=date(2026, 1, 1))
    assert (found, provenance) == ("2025-07-04", SOURCE_YEAR)
    assert abs((date(2025, 7, 4) - date(2026, 1, 1)).days) <         abs((date(2026, 7, 4) - date(2026, 1, 1)).days)


def test_a_date_no_nearby_year_can_place_is_refused_rather_than_guessed():
    """The guard, exercised where it actually bites.

    A day that is more than MAX_DAYS_FROM_POST from the post in every candidate
    year cannot happen for a real calendar date -- the years are 365 days apart,
    so one of them is always within half a year. So the guard is reached through
    a post whose date we do not have, and through the audit case below; this
    test pins the arithmetic that makes that true, so a future change to the
    threshold cannot quietly turn it into a filter that drops real events.
    """
    published = date(2026, 6, 15)
    worst = max(
        min(abs((date(y, m, 1) - published).days) for y in (2025, 2026, 2027))
        for m in range(1, 13)
    )
    assert worst <= 183
    assert MAX_DAYS_FROM_POST > worst, (
        "the guard must never reject a date that a real calendar could produce; "
        "it exists for posts with no usable date at all")


# --- 17.10, 17.11: nothing to anchor to -------------------------------------

def test_without_a_post_date_no_year_is_invented():
    """The bug in one line: this used to answer 2026 whatever the truth was."""
    found, raw, provenance = _norm_date("9월 25일 밀롱가", published=None)
    assert found is None
    assert provenance == UNKNOWN_YEAR
    assert raw  # we did see a date; we just cannot place it


def test_an_impossible_day_is_not_forced_into_a_month():
    found, _, provenance = _norm_date("2월 30일 밀롱가", published=date(2026, 2, 1))
    assert (found, provenance) == (None, UNKNOWN_YEAR)


def test_february_29th_lands_on_a_leap_year():
    found, _, _ = _norm_date("2월 29일 밀롱가", published=date(2024, 2, 20))
    assert found == "2024-02-29"


# --- the extractor as a whole -----------------------------------------------

def test_the_posts_date_reaches_the_rule_through_extract_single():
    """A patch once changed a helper the pipeline did not call. Assert the path."""
    stale = extract_single(
        "2024 서울 살사 위크", "살사 소셜 9/25 저녁 8시 홍대",
        event_type="SOCIAL", published="2024-09-26T00:00:00+00:00")
    assert stale.date != "2026-09-25"
    assert stale.date == "2024-09-25"

    fresh = extract_single(
        "토요밀롱가", "9/5 저녁 8시 홍대", event_type="MILONGA",
        published=date(2026, 9, 1))
    assert fresh.date == "2026-09-05"


def test_a_date_we_refused_to_place_is_still_recorded_as_evidence():
    """So the console shows a refusal, not a post nobody read."""
    candidate = extract_single(
        "밀롱가 안내", "9월 25일 저녁 8시", event_type="MILONGA", published=None)
    assert candidate.date is None
    dates = [e for e in candidate.evidences if e.field == "date"]
    assert dates and dates[0].value is None
    assert dates[0].inference == UNKNOWN_YEAR
    assert dates[0].raw_text


def test_the_year_provenance_reaches_the_evidence_row():
    candidate = extract_single(
        "토요밀롱가", "9/5 저녁 8시", event_type="MILONGA", published=date(2026, 9, 1))
    dates = [e for e in candidate.evidences if e.field == "date"]
    assert dates and dates[0].inference == SOURCE_YEAR

    explicit = extract_single(
        "토요밀롱가", "2026년 9월 5일 저녁 8시", event_type="MILONGA",
        published=date(2026, 9, 1))
    dates = [e for e in explicit.evidences if e.field == "date"]
    assert dates and dates[0].inference == EXPLICIT_YEAR
