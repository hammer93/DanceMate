"""v0.96.19 - a clock range belongs to the programme nearest it, not to any
class word within sixteen characters of it.

v0.96.18 made that judgement comparative for a lone clock and pinned 가또땅고
3199 as the range side of the same defect. This closes it, with two rules the
lone-clock side did not need, because a naive comparison over the stored range
corpus admits two ranges it should not: a workshop's range whose nearest event
word is labelling the *next* clock (4449), and a late-night package's hours
whose class word sits *after* the range (the PISTA poster).
"""

import pytest

from src import extraction_rules
from src.extractor import extract_single

from tests.fixture_v09619_range_attribution import (
    ATTRIBUTED,
    EITHER_SIDE,
    EVENT_WORD_BODY,
    EVENT_WORDS_TRIED,
    LONE_CLOCK_UNMOVED,
    MILONGA,
    RANGE_TAIL_STILL_REFUSED,
    SOCIAL,
    STILL_A_CLASS_TIMETABLE,
    STILL_ANOTHER_PROGRAMMES,
    UNCHANGED_RANGES,
    UNMARKED_MORNING_REFUSED,
    UNVETOED_MORNING_KEPT,
    MERIDIEM_SWALLOWED,
    EVERLATN_PROGRAMME_LINE,
)


def _range(body, event_type):
    reading = extraction_rules.parse_time_range(body, event_type=event_type)
    return (reading.start, reading.end) if reading else (None, None)


# --- the ranges this release attributes to the event ---------------------

@pytest.mark.parametrize("label,body,event_type,start,end", ATTRIBUTED)
def test_a_range_beside_a_class_word_can_still_be_the_events(
        label, body, event_type, start, end):
    assert _range(body, event_type) == (start, end), label


def test_3199_reads_the_hour_its_milonga_states():
    """The release's own target, end to end.

    v0.96.18 read 22:30 - the performance's hour - because the milonga's own
    `9:00pm-12:30am` was thrown away by the 오픈특강 ten minutes before it.
    """
    label, body, event_type, start, end = ATTRIBUTED[0]
    event = extract_single(
        "[부산_탱고동호회]가또땅고 3월 첫째주 열탱즐탱 일정 안내", body,
        event_type=MILONGA)
    assert (event.start_time, event.end_time) == ("21:00", "00:30")
    time_evidence = next(e for e in event.evidences if e.field == "time")
    assert time_evidence.evidence_type == "TEXT"
    assert "9:00pm" in time_evidence.raw_text


@pytest.mark.parametrize("label,body,expected", EITHER_SIDE)
def test_the_event_may_name_its_range_from_either_side(label, body, expected):
    assert _range(body, SOCIAL)[0] == expected, label


@pytest.mark.parametrize("word,event_type", EVENT_WORDS_TRIED)
def test_the_rule_is_not_specific_to_one_scenes_word(word, event_type):
    body = EVENT_WORD_BODY.format(word=word)
    assert _range(body, event_type) == ("21:00", "23:00")


def test_the_nearest_named_range_wins_not_the_first_one():
    """Among the ranges the event's word names, the one it names most closely.

    `공연 오후 8시~8시30분 LATIN PARTY 오후 9시~12시` puts the PARTY inside the
    공연 range's window too, and taking the first named range by position gave
    the party the performance's half hour.
    """
    body = "바차타 클래스 오후 6시~7시 공연 오후 8시~8시30분 LATIN PARTY 오후 9시~12시"
    assert _range(body, SOCIAL) == ("21:00", "00:00")


# --- what must stay another programme's ----------------------------------

@pytest.mark.parametrize("label,body,event_type", STILL_ANOTHER_PROGRAMMES)
def test_a_class_range_is_still_refused(label, body, event_type):
    assert _range(body, event_type) == (None, None), label


def test_a_class_word_after_the_range_owns_it_however_near_the_event_word_is():
    """The false positive that distance alone introduced, stated on its own.

    The PISTA poster writes `심야밀롱가(11:30 p.m-4:30 a.m) 패키지`. 밀롱가 is
    one character before the range and 패키지 two after it, so the milonga would
    take the late-night package's hours - and unlike the 9am cases it carries
    p.m/a.m markers, so nothing further down would refuse it.
    """
    poster = ("*10시 이후 입장시, 무료 입장권 1장제공 *심야밀롱가(11:30 p.m-4:30 a.m) "
              "패키지 사전결제 ) 20,0008!")
    assert _range(poster, MILONGA) == (None, None)
    assert extract_single("더 피스타 밀롱가", poster,
                          event_type=MILONGA).start_time is None
    # ...and the same statement in the body's own wording, where 패키지 is
    # nearer than 밀롱가 and distance alone already refuses it.
    body = ("🎟 10시 이후 입장 시 무료 입장권 1장 제공 🌙 심야 밀롱가 패키지 "
            "23:30 – 04:30 사전결제 20,000원")
    assert _range(body, MILONGA) == (None, None)


def test_an_event_word_that_labels_another_clock_does_not_claim_this_range():
    """4449: `워크샵 : ... PM 7:00~8:00 소셜 시작 : PM 8:00`.

    The 소셜 is nearest the workshop's range, and it is naming the 8 PM that
    follows it. The post's stored 20:00 is correct and must not become 19:00.
    """
    body = "워크샵 : 양 & 베키 · PM 7:00~8:00 소셜 시작 : PM 8:00 DJ 린넨"
    assert _range(body, SOCIAL) == (None, None)
    assert extraction_rules.parse_start_time(
        body, event_type=SOCIAL).start == "20:00"


def test_an_event_word_followed_by_its_own_range_does_not_claim_this_one():
    """`특강 7시~8시 소셜 9시~11시`: the 소셜 names the range after it."""
    body = "살사 초급 특강 오후 7시~8시 소셜 오후 9시~11시"
    first = next(extraction_rules._RANGE_RE.finditer(body))
    words = extraction_rules._EVENT_WORDS[SOCIAL]
    assert extraction_rules._range_belongs_to_other_programme(
        body, first, words), "the class's own range stays the class's"


# --- admitted, then refused for a different reason ----------------------

@pytest.mark.parametrize("label,body,event_type", UNMARKED_MORNING_REFUSED)
def test_a_range_admitted_by_context_must_not_be_an_unmarked_morning(
        label, body, event_type):
    """These carry no meridiem anywhere, so they resolve literally to 9am.

    Telling somebody to turn up at 9am for a night is worse than telling them
    nothing, which is what these posts store today.
    """
    assert _range(body, event_type) == (None, None), label


def test_a_range_no_class_word_objected_to_keeps_its_literal_morning():
    """The refusal above is scoped to ranges admitted by weighing context. A
    plain morning range is read as a morning, exactly as before."""
    body, event_type, start, end = UNVETOED_MORNING_KEPT
    assert _range(body, event_type) == (start, end)


# --- v0.96.18 and v0.96.17, unmoved -------------------------------------

@pytest.mark.parametrize("label,body,event_type,expected", LONE_CLOCK_UNMOVED)
def test_v09618_lone_clock_recovery_is_unchanged(
        label, body, event_type, expected):
    reading = extraction_rules.parse_start_time(body, event_type=event_type)
    assert reading is not None and reading.start == expected, label


@pytest.mark.parametrize("body", RANGE_TAIL_STILL_REFUSED)
def test_v09618_range_tail_refusals_are_unchanged(body):
    assert extraction_rules.parse_start_time(body, event_type=SOCIAL) is None


def test_the_range_guard_still_means_what_it_meant():
    """`parse_start_time()` calls `_readings()` with no vocabulary, so every
    range is judged there exactly as it always was - a post that states a range
    of its own is `parse_time_range()`'s to read."""
    body = "소셜 20:00-22:30"
    assert list(extraction_rules._readings(body)), "the body states a range"
    assert extraction_rules.parse_start_time(body, event_type=SOCIAL) is None
    # and a class range is still invisible to it, vocabulary or not
    class_only = "초급 살사 워크샵 오후 7시~9시"
    assert not list(extraction_rules._readings(class_only))


def test_v09617_night_named_programme_still_expands():
    from src.extractor import extract_schedule
    from tests.fixture_v09617_night_named_program import HONGTURN, HONGTURN_DATES

    ref, title, body = HONGTURN
    rows = extract_schedule(title, body, event_type=SOCIAL)
    assert rows is not None
    assert {e.date for e in rows} == HONGTURN_DATES
    by_date = {e.date: e for e in rows}
    assert by_date["2026-09-23"].start_time == "21:00"
    assert by_date["2026-09-26"].start_time == "21:00"


# --- ranges that were already read, and must not move -------------------

@pytest.mark.parametrize("label,body,event_type,start,end", UNCHANGED_RANGES)
def test_a_range_that_was_already_read_is_read_the_same_way(
        label, body, event_type, start, end):
    assert _range(body, event_type) == (start, end), label


# --- the case this release does not fix ---------------------------------

def test_a_class_timetable_classified_as_a_milonga_is_still_a_class_timetable():
    """가또땅고 3201, pinned honestly.

    2/22 is four classes and no milonga, and the post is classified
    MILONGA_WITH_CLASS, so a range is read off a class timetable either way. It
    read 3:05-4:15pm (탱고 집중 준중급) and now reads 4:20-5:20pm - the line that
    actually says 밀롱가, which is why it moves. Still a class. This asserts the
    state of the world, not an approval of it; the fix belongs on the
    classification side.
    """
    ref, body, event_type, start, end = STILL_A_CLASS_TIMETABLE
    assert _range(body, event_type) == (start, end)


# --- pre-existing limitations, pinned so they are not mistaken for this ---

def test_a_swallowed_meridiem_is_not_an_attribution_problem():
    """`_RANGE_RE` takes a following range's 오후 into its own match.

    So the second range of `특강 오후 7시~8시 오후 9시~11시 소셜` reaches the
    reading rules as a bare `9시~11시` and is refused as an unmarked morning,
    even though the 소셜 names it and this release attributes it correctly. The
    same sentence written with its own marker reads 21:00. Unchanged by this
    release - None before and None after - and pinned so the boundary is clear.
    """
    body, event_type = MERIDIEM_SWALLOWED
    assert _range(body, event_type) == (None, None)
    assert _range("특강 오후 7시~8시, 9:00pm~11:00pm 소셜", event_type) == ("21:00", "23:00")


def test_everlatns_programme_line_alone_still_gives_nothing():
    """3769's stored 19:00-22:00 comes from its 일정정보 field. Its programme
    line read on its own has the class word nearer every range, and gives
    nothing - before this release and after it."""
    body, event_type = EVERLATN_PROGRAMME_LINE
    assert _range(body, event_type) == (None, None)
