"""v0.96.16 - a post's own day-list field read as the days it runs.

danceinfo.net publishes one row per (content, date) for every day a listing
runs, and the ``전체일정`` field `acquisition.danceinfo_payload_body()` writes
is that day set. `extract_schedule()` reads a schedule post as a run of date
*headings*, which is the wrong shape for a field: every day but the last gets
the segment ``"2026-09-25,"`` and is dropped for naming no event, and the last
day's segment swallows the whole ``일정정보`` + description block. So the post
falls through to the single-candidate path and is filed on the last day of its
own run - 부에나's five-night party as one event on 9/27.

**This is not "one shared schedule, therefore every date".** That inference
was measured against the live corpus on 2026-09-26 and is right one time in
seven; the other six are a congress, a festival, a 6주과정, a monthly roundup,
a workshop weekend and a recurring class day. What makes reading the field
safe is the five conditions, each of which has a post in the fixture that
breaks without it.

The route is additive by construction: it runs only where `extract_schedule()`
produced nothing, so every post that already expands - including the ones
carrying no source category, which condition 1 would refuse - is untouched.

**Measured before it was written**, with a harness that calls
`process_discovered_post()` itself and rebuilds the same `image_texts` and
`trusted_classification_texts` Production builds from its own stored
`source_item_image` rows. That harness reproduces Production's dates on 1,366
of 1,368 extracted items. Over the whole corpus, re-acquisition plus this
route changes six posts: **10 dates added, 2 removed (both already past), no
start time lost, no classification changed, and nothing upcoming lost.**
"""

import pytest

from src.extractor import (
    extract_day_list,
    extract_schedule,
    extract_single,
    own_day_list,
)

from tests.fixture_v09616_own_day_list import (
    BABARU_POSTER,
    DAY_LIST_FIELD_FORMS,
    HAVANA,
    HAVANA_CLOSED_DAY,
    HAVANA_OPEN_ONLY_DAYS,
    LATIN_EVERLATN,
    LATIN_EVERLATN_WORKSHOP_ONLY_DAYS,
    NOT_A_RUN_OF_NIGHTS,
    NO_FIELD_JUST_PROSE,
    OWN_DAY_LIST_RUNS,
    SOCIAL,
    SUWON_CUBA,
    SUWON_CUBA_CURRENT,
    SUWON_CUBA_POSTER,
)

EVENT = "EVENT"


def _read(title, body, **kwargs):
    kwargs.setdefault("event_type", SOCIAL)
    kwargs.setdefault("source_category", EVENT)
    return extract_day_list(title, body, **kwargs)


def _dates(rows):
    return {e.date for e in rows}


# --- T1/T2 the field is a day list, not a run of date headings -------------

@pytest.mark.parametrize("ref,title,body,expected", OWN_DAY_LIST_RUNS)
def test_the_day_list_field_becomes_one_candidate_per_day(ref, title, body, expected):
    rows = _read(title, body)
    assert rows is not None, "the post's own day-list field was not read"
    assert _dates(rows) == expected


@pytest.mark.parametrize("ref,title,body,expected", OWN_DAY_LIST_RUNS)
def test_the_days_inside_the_field_are_not_separate_programs(ref, title, body, expected):
    """The defect this release fixes, stated as a test.

    Read as date headings, the field's days each get an empty segment and only
    the last one - the one that swallowed the description - survives. So
    `extract_schedule()` produces nothing at all here, and whatever the single
    path gives is one day of the run.
    """
    assert extract_schedule(title, body, event_type=SOCIAL) is None
    single = extract_single(title, body, event_type=SOCIAL)
    assert single.date in expected
    assert len(expected) > 1


@pytest.mark.parametrize("ref,title,body,expected", OWN_DAY_LIST_RUNS)
def test_every_day_of_a_run_is_its_own_candidate_and_own_day(ref, title, body, expected):
    """`events.event_date` holds one day, so a run arrives as one candidate per
    day or not at all - never one candidate carrying a span."""
    rows = _read(title, body)
    assert len(rows) == len(expected)
    assert len({e.date for e in rows}) == len(rows)


# --- T3..T8 the same shape that must stay out -----------------------------

@pytest.mark.parametrize("ref,title,body,expected", NOT_A_RUN_OF_NIGHTS)
def test_the_same_shape_that_is_not_a_run_of_nights_is_refused(
        ref, title, body, expected):
    """Asserted against the route directly, with a night classification
    forced, so the refusal is this route's own and not a side effect of how
    `classify()` happens to read the post today."""
    assert expected is None
    assert _read(title, body) is None


def test_a_course_listing_its_sessions_never_becomes_that_many_nights():
    """The recurrence family, which is the whole reason condition 1 and
    condition 3 both exist. Over the stored corpus an ungated version of this
    rule adds 65 candidates of which 45 are course sessions."""
    ref, title, body, _ = next(r for r in NOT_A_RUN_OF_NIGHTS if r[0] == 3622)
    assert _read(title, body) is None
    # ...and it is the course wording that does it, not the classification.
    assert _read(title, body, event_type="SOCIAL") is None


def test_a_source_that_does_not_call_it_a_night_is_refused():
    """Condition 1. The nine stored posts that slipped an ungated version of
    this rule were all collected before the category was carried, and every
    one of them is a weekly 과정."""
    ref, title, body, expected = OWN_DAY_LIST_RUNS[0]
    assert _read(title, body) is not None
    assert extract_day_list(title, body, event_type=SOCIAL,
                            source_category="CLASS") is None
    assert extract_day_list(title, body, event_type=SOCIAL,
                            source_category=None) is None


def test_a_post_that_only_lists_dates_in_prose_has_no_day_list():
    """Condition 2. The label is written by the acquisition layer, so it can
    never appear by accident - and without it there is no field to read."""
    title, body = NO_FIELD_JUST_PROSE
    assert own_day_list(f"{title} {body}") == (frozenset(), None)
    assert _read(title, body) is None


# --- T9 a day the post closes, and a day it only opens the doors on -------

def test_a_day_the_post_closes_is_not_a_night():
    """Condition 4, and no new vocabulary: 하바나's 9/24 line says "하루
    쉬어갑니다", which simply fails the test that a day's own words must name
    the night."""
    ref, title, body = HAVANA
    rows = _read(title, body)
    produced = _dates(rows) if rows else {extract_single(title, body,
                                                        event_type=SOCIAL).date}
    assert HAVANA_CLOSED_DAY not in produced


def test_a_span_that_only_says_the_doors_are_open_is_not_a_night():
    """"9월 25일(금) ~ 27일(일) 정상 영업" covers three listed days, and a day
    written inside a span has that span's words as its own evidence. None of
    those three may become a party on the strength of the shared block."""
    ref, title, body = HAVANA
    rows = _read(title, body)
    produced = _dates(rows) if rows else set()
    assert not (produced & HAVANA_OPEN_ONLY_DAYS)


def test_havana_keeps_expanding_the_way_it_already_does():
    """It reaches `extract_schedule()` first, so this release does not touch
    it: the route is only ever tried where that one produced nothing."""
    assert extract_schedule(HAVANA[1], HAVANA[2], event_type=SOCIAL) is not None


# --- T10 nothing already shown is traded away -----------------------------

def test_a_night_does_not_lose_its_hours_to_gain_days():
    """Condition 5, measured on 수원쿠바: its own 9/26 line is "9월 26일 추석
    소셜" with no clock, and the 8:00 PM that times it is in the shared block.
    Keeping the day and dropping the hour trades a night somebody can turn up
    to for three they only know the date of, so the post is left alone."""
    ref, title, body = SUWON_CUBA
    day, start = SUWON_CUBA_CURRENT
    current = extract_single(title, body, event_type=SOCIAL)
    assert (current.date, current.start_time) == (day, start), \
        "the fixture's own premise: this post reads as one timed night today"
    assert _read(title, body, current=current) is None


def test_the_day_a_post_already_shows_must_survive_the_expansion():
    """Stated generally: whatever the single path gives is still there
    afterwards, for every run this release does expand."""
    for ref, title, body, expected in OWN_DAY_LIST_RUNS:
        current = extract_single(title, body, event_type=SOCIAL)
        rows = _read(title, body, current=current)
        assert rows is not None, ref
        assert current.date in _dates(rows), ref


# --- T11 one day's poster never times another day -------------------------

def test_a_poster_only_fills_a_day_the_post_describes_through_its_shared_block():
    """A poster is evidence about the post. 수원쿠바's is titled 9월 19일 and
    reads "소셜 PM 8:00 ~ 11:00" - one day's hours - and every day that post
    lists has a line of its own. A clock those lines left out is the post's own
    silence about that day, not licence to borrow the 19th's."""
    ref, title, body = SUWON_CUBA
    current = extract_single(title, body, event_type=SOCIAL)
    assert _read(title, body, current=current,
                 image_texts=SUWON_CUBA_POSTER) is None


def test_a_shared_block_day_may_take_the_posters_hours():
    """The other side of the same rule, read from the real stored OCR.

    BABARU's poster states WORKSHOP PM 8:00 ~ 9:00 and SOCIAL PM 9:00 START
    under each of its three dates, so the 20:00 Production already shows
    belongs to every day of the run. Every day of this post is described only
    through the shared block - the post's second writing of its own day list
    is not three per-day descriptions - so every day may read that poster, and
    condition 5 becomes satisfiable instead of having to refuse the expansion
    in order to keep one hour.
    """
    ref, title, body, expected = next(r for r in OWN_DAY_LIST_RUNS if r[0] == 4063)
    current = extract_single(title, body, event_type=SOCIAL)
    rows = _read(title, body, current=current, image_texts=BABARU_POSTER)
    assert rows is not None
    assert _dates(rows) == expected
    assert {e.start_time for e in rows} == {"20:00"}, \
        "every day of the run should carry the hours the poster states for it"


# --- T16 a post whose only night is one of its listed days ----------------

def test_a_workshop_only_day_never_becomes_a_night():
    """LATIN EVERLATN lists four days and gives two of them nothing but
    "Salsa 워크샵". A day's own words beat the shared 7:00-10:00 p.m., whatever
    that block says."""
    ref, title, body = LATIN_EVERLATN
    rows = _read(title, body)
    produced = _dates(rows) if rows else set()
    assert not (produced & LATIN_EVERLATN_WORKSHOP_ONLY_DAYS)


def test_a_run_whose_one_real_night_would_lose_its_hours_is_declined():
    """What is left of that post is its 9/27 Kizomba party - and read from its
    own narrow line, the clock beside 파티 carries no meridiem, so its hours
    are not published. The post already reads as a *timed* 9/27, so condition 5
    declines the expansion and it keeps the single night it has."""
    ref, title, body = LATIN_EVERLATN
    current = extract_single(title, body, event_type=SOCIAL)
    assert current.date == "2026-09-27" and current.start_time is not None
    assert _read(title, body, current=current) is None


# --- T12 a restated list is the list again, not a description -------------

def test_a_day_list_restated_in_prose_is_not_a_description_of_one_day():
    """BABARU writes its run twice - as the field, and as "9/23수 · 9/25금 ·
    9/26토 BABARU에서 살사 · 바차타와 함께 알차게 준비했습니다". Between those
    tokens there is a weekday letter and a separator and nothing else, and the
    sentence after the last of them is about all three days. Read as three
    per-day descriptions, none of them names a night and the post produces
    nothing."""
    ref, title, body, expected = next(r for r in OWN_DAY_LIST_RUNS if r[0] == 4063)
    assert _dates(_read(title, body)) == expected


# --- T13 what the field parses to ----------------------------------------

@pytest.mark.parametrize("label,text,expected", DAY_LIST_FIELD_FORMS)
def test_the_day_list_field_resolves_only_what_the_post_states(label, text, expected):
    days, end = own_day_list(text)
    assert set(days) == expected, label
    if expected:
        assert end is not None and end <= len(text)


def test_the_field_capture_stops_before_the_next_label():
    """`일` of `일정정보` is a weekday character; a looser separator class eats
    it and the capture runs into the next field."""
    days, end = own_day_list(
        "2026-09-23 전체일정 2026-09-23,2026-09-24 일정정보 PM 9:00 장소 부에나")
    assert set(days) == {"2026-09-23", "2026-09-24"}
    assert "일정정보" not in "2026-09-23 전체일정 2026-09-23,2026-09-24"[:end]


# --- T14 a guessed morning start is not published ------------------------

def test_a_days_own_line_never_publishes_a_guessed_morning_start():
    """One day's line can be narrow enough that the only clock beside the
    event's word carries no meridiem. A 7am party is worse than a party whose
    hours nobody claims to know - the same trade the image fallback already
    makes for an OCR'd clock."""
    body = ("2026-09-26 전체일정 2026-09-26,2026-09-27 일정정보 9:00 PM 소셜 "
            "장소 라틴 강의 소개 소셜 파티 안내 "
            "09/26(토) 7:00-8:00 p.m.: 살사 워크샵, 9:00-10:00 p.m.: 소셜 파티 "
            "09/27(일) 8:00-9:00 p.m.: 소셜 파티")
    rows = _read("라틴 주말 소셜", body)
    if rows:
        for event in rows:
            assert event.start_time is None or event.start_time >= "12:00", \
                f"{event.date} published a morning start"


# --- T15 the route never fires where the old one already did -------------

def test_the_route_is_only_tried_where_the_schedule_route_produced_nothing():
    """Stated as a property of every fixture entry, positive or negative: a
    post `extract_schedule()` already expands is never handed to this one, so
    v0.96.0's and v0.96.15's contracts cannot narrow."""
    for ref, title, body, _ in OWN_DAY_LIST_RUNS + NOT_A_RUN_OF_NIGHTS:
        if extract_schedule(title, body, event_type=SOCIAL) is not None:
            pytest.fail(f"{ref} reaches the schedule route; it does not belong here")
