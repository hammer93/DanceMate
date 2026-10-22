"""v0.96.50 - a date is not an event date, and a DJ's set is not the night.

DATA-01. 네오스윙's notices for one 10/25 graduation party were stored as
events on 10/20 and 10/22 - the performance sign-up and ticket pre-sale
deadlines. Not because of the title (the "10/22" in "...공연 신청 안내 10/22"
is the suffix `extract_schedule()` itself appends to each program it makes)
but because a 안내 title sends a post down the schedule route, and every dated
paragraph that so much as mentions 파티 became a program. `date_roles()`
recognises a deadline by its own grammar - closed by 까지/마감, introduced by
마감/기한, or the open end of "~10/22" - and no route takes one as the day
something happens on.

DATA-02. 스윙타임빠's weekly notice states "저녁 7시30분부터 소셜" and then the
DJ's "PM 8:15~10:15"; the DJ's range was the social's hours.

DATA-04. danceinfo's "일정정보 PM 9" - a bare hour with its half of the day
written in front - was never read as a clock.

Simulated over every stored Production item (4,858, pg_dump of 2026-10-23
05:38 KST, the runtime's own re-extract route on the 1.16 tree with and
without this change, cached poster OCR, no network): the date rule changes
exactly four posts - 네오스윙's 140기 and 141기 sign-up and ticket notices -
and the time rules eighteen: seventeen 스윙타임빠 notices that all state
"7시30분부터 소셜" before their DJ's range, and item 6644's "PM 9". Nothing else
reads differently.
"""

import pytest

from src.extraction_rules import parse_start_time, parse_time_range
from src.extractor import (
    DEADLINE,
    _all_date_matches,
    date_roles,
    extract_schedule,
    extract_single,
    extract_with_image_fallback,
)
from src.live_pipeline import process_discovered_post

from tests.fixture_v09650_date_time_roles import (
    NEOSWING_PUBLISHED,
    REAL_IMSALSA,
    REAL_LUXURY_PARTY,
    REAL_NEOSWING_HELPERS,
    REAL_NEOSWING_PERFORMANCE,
    REAL_NEOSWING_TICKETS,
    REAL_TIMEBAR,
    TIMEBAR_PUBLISHED,
)


class _Post:
    def __init__(self, title, body, published_at=None, **extra):
        self.title, self.body, self.published_at = title, body, published_at
        self.acquisition_quality = extra.pop("acquisition_quality", "FULL")
        for key, value in extra.items():
            setattr(self, key, value)


def _run(title, body, published=None, **extra):
    return process_discovered_post(None, _Post(title, body, published, **extra))


def _dates(result):
    return sorted(e.date for e in result["events"])


def _roles(text):
    matches = _all_date_matches(text)
    roles = date_roles(text, matches)
    return {m.group(0): roles.get(m.start()) for m in matches}


# --- DATA-01: the real notices -------------------------------------------------

@pytest.mark.parametrize("post", [REAL_NEOSWING_PERFORMANCE, REAL_NEOSWING_TICKETS,
                                  REAL_NEOSWING_HELPERS],
                         ids=["performance-6155", "tickets-6153", "helpers-6154"])
def test_a_notice_for_the_party_is_dated_on_the_party_never_a_deadline(post):
    result = _run(*post, NEOSWING_PUBLISHED)
    assert _dates(result) == ["2026-10-25"]


def test_the_sign_up_notice_no_longer_becomes_three_events():
    """Production stored 1629134 (10/25), 1629133 (10/20) and 1629132 (10/22)
    from this one post. Only the party is an event."""
    assert extract_schedule(*REAL_NEOSWING_PERFORMANCE, event_type="SOCIAL_WITH_CLASS",
                            published=NEOSWING_PUBLISHED) is None
    events = _run(*REAL_NEOSWING_PERFORMANCE, NEOSWING_PUBLISHED)["events"]
    assert len(events) == 1
    assert "10/22" not in events[0].name and "10/20" not in events[0].name


def test_every_deadline_in_the_real_notices_is_recognised_as_one():
    performance = " ".join(REAL_NEOSWING_PERFORMANCE)
    tickets = " ".join(REAL_NEOSWING_TICKETS)
    helpers = " ".join(REAL_NEOSWING_HELPERS)
    assert _roles(performance)["10/25"] is None
    assert _roles(performance)["10/20"] == DEADLINE            # "~ 10/20(화)"
    assert _roles(performance)["2026년 10월 20일"] == DEADLINE  # "신청 기한 : ..."
    assert _roles(performance)["10/22"] == DEADLINE            # "전송 : ~10/22(목)"
    assert _roles(tickets)["10월 25일"] is None
    assert _roles(helpers)["2026년 10월 23일"] == DEADLINE      # "모집기간 ...(금)까지"


def test_the_volunteers_call_time_is_not_the_partys_start():
    """Item 6154's deadline paragraph still ends the party's own: its
    "활동시간 : 당일 오후 3시" stays out of the party's scope, as before."""
    (event,) = _run(*REAL_NEOSWING_HELPERS, NEOSWING_PUBLISHED)["events"]
    assert event.date == "2026-10-25"
    assert event.start_time is None


def test_the_ticket_notices_estimated_timetable_invents_no_start():
    (event,) = _run(*REAL_NEOSWING_TICKETS, NEOSWING_PUBLISHED)["events"]
    assert event.start_time is None


# --- DATA-01: the cases around it ----------------------------------------------

PUB = "2026-10-12T00:00:00+09:00"


@pytest.mark.parametrize("ref, title, body, expected", [
    ("deadline and event date both in the title",
     "10/22 마감 · 10/25 스윙 소셜 파티", "많은 신청 바랍니다", "2026-10-25"),
    ("event date only", "스윙 소셜 파티", "10/25(일) 오후 7시 소셜 파티", "2026-10-25"),
    ("early bird deadline", "할로윈 파티 안내",
     "얼리버드 ~10/10까지 할인! 파티는 10월 31일 토요일 밤 9시 소셜", "2026-10-31"),
    ("payment deadline", "파티 입금 안내",
     "입금 마감 10월 20일 23시까지 / 10월 24일 토요일 파티 오후 8시", "2026-10-24"),
    ("registration period before the event", "워크샵 & 파티 신청 안내",
     "신청기간: 10/1 ~ 10/20 / 본 행사 10/25 소셜 파티 PM 8:00", "2026-10-25"),
    ("revised article moves the party", "[141기] 졸업파티 입장티켓 사전 구매 안내 (일정 변경)",
     "졸업파티가 11월 1일(일)로 변경되었습니다. 사전 신청 마감은 10월 29일 목요일 23시까지입니다.",
     "2026-11-01"),
])
def test_a_deadline_is_never_the_event_date(ref, title, body, expected):
    assert _dates(_run(title, body, PUB)) == [expected]


def test_a_deadline_title_over_an_event_body_reads_the_body():
    """Title "10월 22일 신청 마감", body "10월 25일 오후 7시 소셜". (The classifier
    files that exact post as OTHER - a registration notice - and makes no
    event of it at all; asked as a social, the date and time are the body's.)"""
    event = extract_single("10월 22일 신청 마감", "10월 25일 오후 7시 소셜", event_type="SOCIAL",
                           published=PUB)
    assert (event.date, event.start_time) == ("2026-10-25", "19:00")


def test_a_post_with_only_a_deadline_has_no_event_date():
    """"10월 22일 신청 마감! 자세한 행사 일정은 추후 공지" names one day, and it is
    not the event's. Nothing is filled in."""
    result = _run("스윙 파티 신청 안내", "10월 22일 신청 마감! 자세한 행사 일정은 추후 공지 소셜 파티", PUB)
    assert [e.date for e in result["events"]] in ([], [None])


def test_a_deadline_alone_does_not_date_a_single_event_either():
    event = extract_single("파티 안내", "예매는 10/21까지! 소셜 파티", event_type="SOCIAL",
                           published=PUB)
    assert event.date is None


def test_a_festival_period_is_never_read_as_a_registration_window():
    """Its last day is closed by 까지 like a deadline, but it ends a range that
    opened on a day nobody called a deadline. (Which day a prose festival is
    filed on is `extract_festival()`'s question and is unchanged here.)"""
    text = "BUSAN 탱고 페스티벌 11월 11일부터 11월 16일까지 진행됩니다 밀롱가"
    assert set(_roles(text).values()) == {None}


def test_a_registration_window_is_read_as_one_whole_window():
    text = "신청기간: 10/1 ~ 10/20 페스티벌 11/11~11/16"
    roles = _roles(text)
    assert roles["10/1"] == roles["10/20"] == DEADLINE
    assert roles["11/11"] is None and roles["11/16"] is None


def test_the_end_of_a_night_is_not_a_deadline():
    """Same shape as "10월 22일 23시까지" - the sentence is about no deadline."""
    assert _roles("10월 25일 밤 12시까지 신나게 소셜!")["10월 25일"] is None


def test_a_sentence_ending_tilde_is_not_an_open_range():
    """"해주세요~ 2026년 10월 8일" (item 2911): the tilde closes a sentence."""
    text = "생일 파티를 함께 해주세요~ 2026년 10월 8일... 부산의 목요일"
    assert _roles(text)["2026년 10월 8일"] is None


SCHEDULE_PUB = "2026-09-30T00:00:00+09:00"  # inside every program's announcement window


def test_a_recurring_schedule_keeps_every_night():
    result = extract_schedule("10월 소셜 일정 안내", "10/3 토 소셜 20:00 / 10/10 토 소셜 20:00 / "
                              "10/17 토 소셜 20:00", event_type="SOCIAL", published=SCHEDULE_PUB)
    assert sorted(e.date for e in result) == ["2026-10-03", "2026-10-10", "2026-10-17"]


def test_a_schedule_keeps_its_programs_and_drops_only_its_deadline():
    result = extract_schedule("10월 소셜 파티 일정 안내",
                              "10/3 토 소셜 파티 20:00 / 10/10 토 소셜 파티 20:00 / "
                              "파티 신청 마감 10/8까지", event_type="SOCIAL",
                              published=SCHEDULE_PUB)
    assert sorted(e.date for e in result) == ["2026-10-03", "2026-10-10"]


def test_a_poster_date_table_is_read_with_its_deadline_role():
    """A post whose body names no day falls back to its poster; the poster's
    deadline line is a deadline there too."""
    event = extract_with_image_fallback(
        "졸업파티 안내", "포스터를 확인해주세요", event_type="SOCIAL", published=PUB,
        image_texts=[("poster.jpg", "신청 마감 10/22(목)까지\n10/25(일) 졸업파티 소셜 PM 7:00")])
    assert event.date == "2026-10-25"


def test_an_ambiguous_announcement_never_falls_back_to_its_deadline():
    result = _run("파티 신청 안내",
                  "신청은 10월 22일까지 받습니다. 파티는 10월 25일 또는 11월 1일 중 확정 예정", PUB)
    assert "2026-10-22" not in _dates(result)


def test_historical_re_extraction_is_stable():
    """A stored post read again reads the same: what the engine produces for
    a post depends on the post, not on how often it is read."""
    first = _dates(_run(*REAL_NEOSWING_TICKETS, NEOSWING_PUBLISHED))
    again = _dates(_run(*REAL_NEOSWING_TICKETS, NEOSWING_PUBLISHED))
    assert first == again == ["2026-10-25"]


def test_the_same_party_from_three_notices_reads_one_date():
    """Same Event Across Sources: the three notices now agree on the one day;
    folding them is the runtime's duplicate work, not the engine's."""
    dates = {d for post in (REAL_NEOSWING_PERFORMANCE, REAL_NEOSWING_TICKETS,
                            REAL_NEOSWING_HELPERS)
             for d in _dates(_run(*post, NEOSWING_PUBLISHED))}
    assert dates == {"2026-10-25"}


# --- DATA-02: a DJ's set is not the night ------------------------------------------

def test_the_socials_own_opening_outranks_its_djs_set():
    result = _run(*REAL_TIMEBAR, TIMEBAR_PUBLISHED)
    (event,) = result["events"]
    assert event.date == "2026-10-24"
    assert (event.start_time, event.end_time) == ("19:30", None)


def test_a_djs_set_with_no_opening_sentence_is_still_the_nights_hours():
    """A one-DJ milonga very often states its hours as the DJ's set."""
    reading = parse_time_range("밀롱가 DJ 홍길동 PM 8:00~11:00", "MILONGA")
    assert (reading.start, reading.end) == ("20:00", "23:00")


def test_a_later_opening_does_not_replace_the_djs_set():
    """An opening after the DJ's start is a different thing (a second room, a
    later programme), not when this night opens."""
    reading = parse_time_range("DJ 가츠 PM 8:00~10:00 소셜 / 2부 소셜은 밤 10시부터", "SOCIAL")
    assert reading.start == "20:00"


def test_two_different_openings_decide_nothing():
    reading = parse_time_range("수요일 저녁 7시부터 소셜 / 토요일 저녁 8시부터 소셜 "
                               "DJ '가츠' PM 8:15~10:15", "SOCIAL")
    assert (reading.start, reading.end) == ("20:15", "22:15")


def test_a_class_before_the_social_is_not_its_start():
    assert parse_start_time("오후 8시 살사 레슨 / 오후 9시부터 소셜", "SOCIAL").start == "21:00"


def test_a_class_and_social_post_with_two_unowned_clocks_stays_unknown():
    """Item 6646: the field's 오후 8시 is the class, 오후 9시 the social, and a
    정모 that is both does not say which is "the" start."""
    (event,) = _run(*REAL_IMSALSA, source_category="EVENT")["events"]
    assert event.start_time is None


# --- DATA-04: clocks written the way posts write them --------------------------------

def test_a_bare_hour_with_its_half_of_day_in_front_is_read():
    (event,) = _run(*REAL_LUXURY_PARTY, source_category="EVENT")["events"]
    assert (event.date, event.start_time) == ("2026-10-23", "21:00")


@pytest.mark.parametrize("text, start", [
    ("PM 9 소셜", "21:00"),
    ("9 PM 소셜", "21:00"),
    ("오후 9시 소셜", "21:00"),
    ("밤 9시부터 소셜", "21:00"),
    ("21:00 소셜", "21:00"),
    ("21시 소셜", "21:00"),
    ("PM 9시 소셜", "21:00"),
    ("소셜 오픈 오후 9 입장", "21:00"),
])
def test_a_stated_start_is_read_in_every_common_spelling(text, start):
    assert parse_start_time(text, "SOCIAL").start == start


@pytest.mark.parametrize("text", [
    "2PM 9명 모집 소셜",        # a headcount
    "오후 9 / 10 소셜",          # a date-like pair
    "오후 9월 소셜",             # a month
    "PM 9,000원 소셜",           # a price
    "9시 소셜",                  # no half of day, no 부터: as likely a deadline
    "탱3-발3-밀3-AM3 소셜",      # 마제밀's music ratio (item 942), never a clock
])
def test_a_number_that_is_not_a_clock_stays_unread(text):
    assert parse_start_time(text, "SOCIAL") is None


# --- overnight contracts are untouched -----------------------------------------------

@pytest.mark.parametrize("text, start, end, offset", [
    ("소셜 21:00–00:00", "21:00", "00:00", 1),
    ("소셜 21:00–01:00", "21:00", "01:00", 1),
    ("소셜 21:00–03:00", "21:00", "03:00", 1),
    ("소셜 22:00–02:00", "22:00", "02:00", 1),
    ("소셜 PM 9:00 ~ 24:00", "21:00", "00:00", 1),
])
def test_overnight_ranges_keep_their_next_day_end(text, start, end, offset):
    reading = parse_time_range(text, "SOCIAL")
    assert (reading.start, reading.end, reading.end_day_offset) == (start, end, offset)


def test_a_lone_midnight_never_opens_a_night():
    assert parse_start_time("밀롱가 PM 24:00", "MILONGA") is None
