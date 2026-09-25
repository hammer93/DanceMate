"""v0.96.15 - a run of nights stored as one day (Information Engine 1.00).

``extract_schedule()`` has produced one candidate per dated program since
v0.96.0, and two things kept a holiday run out of it.

*The days could not be read.* danceinfo.net publishes no ``published_at`` on
purpose, so every yearless day in a body - ``9/25``, ``9월 26일`` - resolved
to nothing, and the only dates left were the ISO ones in the site's own
``전체일정`` header, packed comma-to-comma with no program between them. The
last of those swallowed the whole body, which is why 보니따's four-day run
was stored as 9/27 alone.

*And the expansion was gated on the title.* Only a post whose own title said
일정 / 스케줄 / 안내 / 공지 was ever asked. "보니따에서 보내는 추석연휴" says
none of them.

Measured read-only on Production 25cd038 / 0.96.14 / engine 0.99, fully
converged, over all 2,472 collected items, and re-checked live on
2026-09-25. Of the nine listings missing from that day's Salsa/Bachata
results, eight already held a real event on the wrong day of a run.

**The release's own question is not "how many dates does this post name".**
It is which of those days has a program. A four-week course names four; a
community's weekly post names three nights at three venues; a raffle-results
post names the milongas whose draws it announces. Group B of the fixture is
each of those, and every one of them must go on producing exactly what it
produces today.

**Simulated before it was written.** Over the whole stored corpus the change
moves five posts, every one of them from one candidate to several, and **no
date is lost anywhere**: no event is removed, no event type changes, and no
post that is not one of those five reads differently.
"""

import pytest

from src.extractor import (
    extract_schedule,
    extract_with_image_fallback,
    own_explicit_dates,
)

from tests.fixture_v09615_multi_day_schedule import (
    MULTI_DAY_RUNS,
    NOT_A_RUN_OF_NIGHTS,
    PRICES_NOT_DATES,
)

SOCIAL = "SOCIAL_WITH_CLASS"


def _dates(rows):
    return {e.date for e in rows}


# --- T1/T2/T3/T4 the runs this release reads ------------------------------

@pytest.mark.parametrize("ref,title,body,published,expected", MULTI_DAY_RUNS)
def test_a_run_of_nights_becomes_one_candidate_per_night(
        ref, title, body, published, expected):
    rows = extract_schedule(title, body, event_type=SOCIAL, published=published)
    assert rows is not None, "the post's own day list was not read"
    assert _dates(rows) == expected


@pytest.mark.parametrize("ref,title,body,published,expected", MULTI_DAY_RUNS)
def test_each_night_of_a_run_is_stored_as_its_own_day(
        ref, title, body, published, expected):
    """Not one candidate carrying a span: `events.event_date` holds one day,
    so a run has to arrive as one candidate per day or not at all."""
    rows = extract_schedule(title, body, event_type=SOCIAL, published=published)
    assert len(rows) == len(expected)
    assert len({e.date for e in rows}) == len(rows)


@pytest.mark.parametrize("ref,title,body,published,expected", MULTI_DAY_RUNS)
def test_the_day_the_post_was_already_read_as_still_exists(
        ref, title, body, published, expected):
    """The expansion may only add. Whatever single day Production holds for
    this post today has to be among the days it holds afterwards."""
    single = extract_with_image_fallback(
        title, body, event_type=SOCIAL, published=published)
    rows = extract_schedule(title, body, event_type=SOCIAL, published=published)
    assert single.date in _dates(rows)


# --- T5 a day in the list with nothing on it ------------------------------

def test_a_closed_day_inside_the_run_produces_no_candidate():
    """T5. 클럽 하바나's own 전체일정 carries 9/24 and its own body says
    "9월 24일(목) 🌙 하루 쉬어갑니다". Nothing here reads 휴무 as a word - the
    day simply names no social and no party, which is the test
    extract_schedule() has applied since v0.96.0."""
    ref, title, body, published, expected = next(
        e for e in MULTI_DAY_RUNS if e[0] == 3772)
    rows = extract_schedule(title, body, event_type=SOCIAL, published=published)
    assert "2026-09-24" not in _dates(rows)


def test_a_closed_day_the_site_itself_leaves_out_stays_out():
    """강턴's 전체일정 omits 9/24 and its body says 강턴휴무. Both readings
    agree, and the day is not a candidate either way."""
    ref, title, body, published, expected = next(
        e for e in MULTI_DAY_RUNS if e[0] == 3792)
    assert "2026-09-24" not in own_explicit_dates(f"{title} {body}")
    rows = extract_schedule(title, body, event_type=SOCIAL, published=published)
    assert "2026-09-24" not in _dates(rows)


def test_a_listed_day_whose_only_program_is_a_workshop_is_not_a_night():
    """서울살사위크 lists four days; 9/30's own line names a workshop and
    nothing else. Being in the header is not being a night."""
    ref, title, body, published, expected = next(
        e for e in MULTI_DAY_RUNS if e[0] == 3734)
    assert "2026-09-30" in own_explicit_dates(f"{title} {body}")
    rows = extract_schedule(title, body, event_type=SOCIAL, published=published)
    assert "2026-09-30" not in _dates(rows)


# --- T6/T7 and the rest of what must not explode --------------------------

@pytest.mark.parametrize("ref,title,body,published,expected", NOT_A_RUN_OF_NIGHTS)
def test_a_post_that_is_not_a_run_of_nights_is_left_alone(
        ref, title, body, published, expected):
    """T6/T7. A course's session list, a community's weekly roundup, a
    raffle-results post, a forward reference, and the two posts whose own
    reading the expansion would have damaged. Each keeps exactly the single
    candidate it has today."""
    assert extract_schedule(
        title, body, event_type=SOCIAL, published=published) is None


def test_a_four_week_course_never_becomes_four_nights():
    """T6, named. Its 전체일정 is a session list and its body prices the
    course. Read with the classifier's own course words - the same ones
    sold_as_a_course() reads - so the two answers cannot drift apart."""
    ref, title, body, published, _ = next(
        e for e in NOT_A_RUN_OF_NIGHTS if e[0] == 2242)
    assert len(own_explicit_dates(f"{title} {body}")) == 4
    assert extract_schedule(title, body, event_type=SOCIAL,
                            published=published) is None


def test_a_day_the_post_never_listed_is_not_a_program_of_it():
    """A single-day post that mentions a party a month away. The day list is
    what admits a day, so a date outside it stays unread - which is also why
    this route needs the post to have written a list at all."""
    ref, title, body, published, _ = next(
        e for e in NOT_A_RUN_OF_NIGHTS if e[0] == 3822)
    assert own_explicit_dates(f"{title} {body}") == {"2026-09-27"}
    assert extract_schedule(title, body, event_type=SOCIAL,
                            published=published) is None


def test_a_post_with_its_own_publication_date_is_unchanged():
    """The day list is read only when there is no published_at to anchor
    against. A community's weekly roundup has one, resolves its days from it
    exactly as before, and is not reachable by this release at all."""
    ref, title, body, published, _ = next(
        e for e in NOT_A_RUN_OF_NIGHTS if e[0] == 2068)
    assert published is not None
    assert extract_schedule(title, body, event_type=SOCIAL,
                            published=published) is None


# --- the price guard ------------------------------------------------------

@pytest.mark.parametrize("text", PRICES_NOT_DATES)
def test_a_price_is_never_read_as_a_date(text):
    """"1.5만원" is the exact shape the bare m.d fallback was built for, and
    it is a price. Every occurrence in the stored corpus is one."""
    assert own_explicit_dates(text) == set()
    assert extract_with_image_fallback(
        "파티", text, event_type=SOCIAL, published=None).date is None


def test_the_price_guard_does_not_refuse_a_real_date_beside_a_price():
    """A date and a price next to each other is the ordinary shape of an
    announcement; only a price *being* the date is refused."""
    text = "2026-09-26 전체일정 2026-09-26 파티 9/26 소셜 21:00 현매 1.5만원"
    assert own_explicit_dates(text) == {"2026-09-26"}


# --- T8/T9 what must not move ---------------------------------------------

def test_a_single_date_post_is_untouched():
    """T8. The overwhelming majority of posts name one day, and the
    expansion cannot reach them: two dated programs are required before
    anything here runs at all."""
    title = "9월 26일 토요 소셜"
    body = "2026-09-26 일정정보 21:00 - 24:00 장소 루에다 소셜 파티"
    assert extract_schedule(title, body, event_type=SOCIAL, published=None) is None
    assert extract_with_image_fallback(
        title, body, event_type=SOCIAL, published=None).date == "2026-09-26"


def test_a_schedule_title_post_keeps_v0960s_own_contract():
    """T9. The title route is judged exactly as it was: none of the three
    extra tests the day-list route must pass is applied to it."""
    title = "10월 소셜 일정 안내"
    body = ("10/3 토 소셜 20:00 @ 스윙홀 10/10 토 소셜 20:00 @ 스윙홀 "
            "10/17 토 소셜 20:00 @ 스윙홀")
    rows = extract_schedule(title, body, event_type=SOCIAL,
                            published="2026-09-28")
    assert rows is not None and len(rows) == 3
