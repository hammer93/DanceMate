"""v0.96.53 - one post, a section per weekday (DATA-06).

스윙타임빠's weekend notice "(10월 24,25일) 토,일 소셜 공지" announces a Saturday
and a Sunday social, each in its own sentence with its own clock. Every route
read one night: the title's day list was flagged MULTI_DAY_EVENT on its first
day, and the Sunday social of 10/25 (and of eight earlier weekends) was never a
candidate. `extract_weekday_sections()` reads that shape and nothing wider.

Replayed over every stored Production item (4,908, the 2026-10-24 04:35 KST
scheduled backup, the runtime's own re-extract route, cached poster OCR, no
network): exactly nine items change, all of them 스윙타임빠 weekend notices,
each gaining its Sunday.
"""

import pytest

from src.extractor import WEEKDAY_SECTION, extract_weekday_sections, extract_with_image_fallback
from src.live_pipeline import process_discovered_post
from tests.fixture_v09650_date_time_roles import REAL_TIMEBAR, TIMEBAR_PUBLISHED

PUBLISHED = "2026-10-22T13:13:16.000+09:00"

# Item 3713, the Chuseok weekend: the Saturday line is a closure.
REAL_TIMEBAR_CHUSEOK = (
    "■ 스윙타임빠 (9월 23,26,27일) 수,토,일 소셜 공지",
    "■ 스윙타임빠 (9월 23,26,27일) 수,토,일 소셜 공지 - 수요일 저녁 7시30분부터 소셜이 "
    "진행 됩니다. DJ '훔머' PM 8:15~10:15 - 토요일 추석연휴 휴무 - 일요일 저녁 7시30분부터 "
    "소셜이 진행 됩니다. 1부 DJ '캐롤' PM 7:30~9:00 2부 DJ '캐롤' 9:00~10:30 ■ 타임빠소셜 "
    "실시간 스트리밍 서비스 안내 수, 일요일 소셜은 스윙프렌즈 유튜브채널에서 실시간으로 현장을 "
    "보실수 있습니다.",
)
CHUSEOK_PUBLISHED = "2026-09-21T10:00:00.000+09:00"

# Item 130, an ordinary Wednesday: one night, untouched.
REAL_TIMEBAR_WEDNESDAY = (
    "■ 스윙타임빠 (9월 2일) 수 소셜 공지",
    "■ 스윙타임빠 (9월 2일) 수 소셜 공지 - 수요일 저녁 7시30분부터 소셜이 진행 됩니다. "
    "DJ \"데미안\" PM 8:15~10:15 ■ 타임빠소셜 실시간 스트리밍 서비스 안내 수, 일요일 소셜은 "
    "스윙프렌즈 유튜브채널에서 실시간으로 현장을 보실수 있습니다.",
)


class _Post:
    def __init__(self, title, body, published_at=None, **extra):
        self.title, self.body, self.published_at = title, body, published_at
        self.acquisition_quality = extra.pop("acquisition_quality", "FULL")
        for key, value in extra.items():
            setattr(self, key, value)


def _run(title, body, published=PUBLISHED, **extra):
    return process_discovered_post(None, _Post(title, body, published, **extra))


def _nights(result):
    return [(e.date, e.start_time, e.end_time) for e in result["events"]]


def _sections(title, body, event_type="SOCIAL", published=PUBLISHED):
    current = extract_with_image_fallback(title, body, event_type=event_type,
                                          published=published)
    return extract_weekday_sections(title, body, event_type=event_type,
                                    published=published, current=current)


# --- DATA-06, the real post -------------------------------------------------------

def test_the_real_notice_is_two_socials_each_from_its_own_sentence():
    result = _run(*REAL_TIMEBAR, TIMEBAR_PUBLISHED)
    assert _nights(result) == [("2026-10-24", "19:30", None), ("2026-10-25", "19:30", None)]


def test_the_sunday_never_borrows_the_saturday_djs_set():
    events = _run(*REAL_TIMEBAR, TIMEBAR_PUBLISHED)["events"]
    sunday = next(e for e in events if e.date == "2026-10-25")
    assert sunday.start_time == "19:30"
    assert "8:15" not in str([e.raw_text for e in sunday.evidences if e.field == "time"])


def test_each_night_records_the_section_it_was_read_from():
    for index, ev in enumerate(_run(*REAL_TIMEBAR, TIMEBAR_PUBLISHED)["events"], start=1):
        sections = [e for e in ev.evidences if e.field == "context" and e.value == WEEKDAY_SECTION]
        assert len(sections) == 1
        assert sections[0].raw_text.startswith(("토요일", "일요일")[index - 1])
        assert {e.context_id for e in ev.evidences} == {f"weekday{index}"}
        assert not any(e.value == "MULTI_DAY_EVENT" for e in ev.evidences)


def test_each_night_is_named_as_the_schedule_route_names_its_programmes():
    names = [e.name for e in _run(*REAL_TIMEBAR, TIMEBAR_PUBLISHED)["events"]]
    assert names == ["■ 스윙타임빠 (10월 24,25일) 토,일 소셜 공지 10/24",
                     "■ 스윙타임빠 (10월 24,25일) 토,일 소셜 공지 10/25"]


def test_a_weekend_whose_saturday_is_closed_keeps_its_other_nights():
    """v0.96.54 (EXT-01, condition 3b): the closed Saturday is excluded by its
    own words, and the Wednesday and Sunday are read - before, the whole post
    was refused and its single reading had no date at all
    (tests/test_v09654_holiday_exceptions.py)."""
    title, body = REAL_TIMEBAR_CHUSEOK
    events = _sections(title, body, published=CHUSEOK_PUBLISHED)
    assert [(e.date, e.start_time) for e in events] == [("2026-09-23", "19:30"),
                                                        ("2026-09-27", "19:30")]
    assert [e.date for e in _run(title, body, CHUSEOK_PUBLISHED)["events"]] == [
        "2026-09-23", "2026-09-27"]


def test_a_single_day_notice_is_untouched():
    title, body = REAL_TIMEBAR_WEDNESDAY
    assert _sections(title, body, published="2026-08-31T10:00:00+09:00") is None
    assert _nights(_run(title, body, "2026-08-31T10:00:00+09:00")) == [
        ("2026-09-02", "19:30", None)]


# --- the ways a post writes its days down -----------------------------------------

@pytest.mark.parametrize("days", [
    "10월 24,25일",
    "10월 24일, 25일",
    "10월 24일과 25일",
    "10월 24일(토) 및 25일(일)",
    "10/24(토), 10/25(일)",
    "10월 24일·25일",
])
def test_every_explicit_way_of_writing_the_two_days(days):
    title = f"클럽 스윙 ({days}) 주말 소셜 공지"
    body = (f"{title} - 토요일 저녁 8시부터 소셜이 진행됩니다. "
            "- 일요일 오후 6시부터 소셜이 진행됩니다.")
    assert _nights(_run(title, body)) == [("2026-10-24", "20:00", None),
                                          ("2026-10-25", "18:00", None)]


def test_a_saturday_milonga_and_a_sunday_practica_are_never_one_event():
    """The post is a milonga notice and its Sunday line names a practica, not
    this night's word: refused whole (condition 3). The single reading that
    stays is the Saturday's own hours - the Sunday's are not merged into it
    and the Saturday's are not given to a Sunday event."""
    title = "탱고 클럽 (10월 24,25일) 주말 안내"
    body = (f"{title} - 토요일 밀롱가 저녁 8시~12시 DJ 홍길동 "
            "- 일요일 쁘락띠까 오후 6시~9시")
    assert _sections(title, body, event_type="MILONGA") is None
    assert _nights(_run(title, body)) == [("2026-10-24", "20:00", "00:00")]


def test_two_milongas_keep_their_own_hours():
    title = "탱고 클럽 (10월 24,25일) 주말 안내"
    body = (f"{title} - 토요일 밀롱가 저녁 8시~12시 DJ 홍길동 "
            "- 일요일 오후 밀롱가 오후 3시~7시")
    events = _sections(title, body, event_type="MILONGA")
    assert [(e.date, e.start_time, e.end_time) for e in events] == [
        ("2026-10-24", "20:00", "00:00"), ("2026-10-25", "15:00", "19:00")]


def test_a_deadline_beside_the_two_days_is_never_a_third_night():
    title = "클럽 스윙 (10월 24,25일) 주말 소셜 공지"
    body = (f"{title} - 신청 마감 10월 22일까지 - 토요일 저녁 8시부터 소셜 "
            "- 일요일 오후 6시부터 소셜")
    assert [n[0] for n in _nights(_run(title, body))] == ["2026-10-24", "2026-10-25"]


def test_a_written_range_is_a_period_and_stays_one_event():
    """"10월 24일~25일" may be a two-day festival; nothing here splits it."""
    title = "탱고 페스티벌 10월 24일~25일"
    body = (f"{title} - 토요일 저녁 8시부터 밀롱가 - 일요일 오후 6시부터 밀롱가")
    assert _sections(title, body, event_type="MILONGA") is None


def test_weekdays_without_dates_name_no_day():
    for title in ("이번 주 토, 일 소셜 공지", "매주 토요일과 일요일 소셜"):
        body = f"{title} - 토요일 저녁 8시부터 소셜 - 일요일 오후 6시부터 소셜"
        assert _sections(title, body) is None


def test_no_year_means_no_expansion():
    title = "클럽 스윙 (10월 24,25일) 주말 소셜 공지"
    body = f"{title} - 토요일 저녁 8시부터 소셜 - 일요일 오후 6시부터 소셜"
    assert _sections(title, body, published=None) is None


def test_a_day_whose_section_has_no_clock_refuses_the_post():
    title = "클럽 스윙 (10월 24,25일) 주말 소셜 공지"
    body = f"{title} - 토요일 저녁 8시부터 소셜 - 일요일 소셜은 추후 공지"
    assert _sections(title, body) is None


def test_a_weekday_that_is_not_its_dates_calendar_day_is_no_section_of_it():
    # 10/24/2026 is a Saturday; a "금요일" section does not describe it.
    title = "클럽 스윙 (10월 24,25일) 주말 소셜 공지"
    body = f"{title} - 금요일 저녁 8시부터 소셜 - 토요일 오후 6시부터 소셜"
    assert _sections(title, body) is None


def test_sections_out_of_date_order_are_refused():
    title = "클럽 스윙 (10월 24,25일) 주말 소셜 공지"
    body = f"{title} - 일요일 오후 6시부터 소셜 - 토요일 저녁 8시부터 소셜"
    assert _sections(title, body) is None


def test_a_section_that_dates_another_day_is_refused():
    title = "클럽 스윙 (10월 24,25일) 주말 소셜 공지"
    body = (f"{title} - 토요일 저녁 8시부터 소셜 "
            "- 일요일 오후 6시부터 소셜, 11월 1일 할로윈 파티 안내")
    assert _sections(title, body) is None


def test_course_evidence_refuses_the_post():
    title = "클럽 스윙 (10월 24,25일) 주말 4주과정 안내"
    body = f"{title} - 토요일 저녁 8시부터 소셜 - 일요일 오후 6시부터 소셜"
    assert _sections(title, body) is None


def test_the_reading_is_the_same_on_every_run():
    first = _nights(_run(*REAL_TIMEBAR, TIMEBAR_PUBLISHED))
    assert all(_nights(_run(*REAL_TIMEBAR, TIMEBAR_PUBLISHED)) == first for _ in range(3))
