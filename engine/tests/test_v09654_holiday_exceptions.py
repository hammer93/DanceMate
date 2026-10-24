"""v0.96.54 - EXT-01: a day a post says is off is not an event, and a night
the post still holds is not taken away with it.

Measured on the 2026-10-24 09:57 KST Production snapshot (4,910 items, the
runtime's own re-extract route, no network): of 60 stored posts that mention
both a weekday and a closure, exactly two read differently.

* Item 3713, 스윙타임빠 "(9월 23,26,27일) 수,토,일 소셜 공지 ... 토요일 추석연휴
  휴무": one candidate with no date became the Wednesday and Sunday socials,
  with the Saturday recorded as closed.
* Item 5767, "26년10월9일(금) 수라댄 금요정모 휴무": a closure notice that was
  stored and listed as a 10/9 event (1613277) now reads as no event.

Nothing is inferred from a holiday's name: 추석, 연휴 or 공휴일 decide nothing
on their own, and no date is created or removed without the post writing it.
"""

import pytest

from src.extractor import CLOSED_DAY, closes_its_day, closure_notice_for
from src.live_pipeline import process_discovered_post

PUBLISHED = "2026-10-20T10:00:00+09:00"

REAL_TIMEBAR_CHUSEOK = (
    "■ 스윙타임빠 (9월 23,26,27일) 수,토,일 소셜 공지",
    "■ 스윙타임빠 (9월 23,26,27일) 수,토,일 소셜 공지 - 수요일 저녁 7시30분부터 소셜이 "
    "진행 됩니다. DJ '훔머' PM 8:15~10:15 - 토요일 추석연휴 휴무 - 일요일 저녁 7시30분부터 "
    "소셜이 진행 됩니다. 1부 DJ '캐롤' PM 7:30~9:00 2부 DJ '캐롤' 9:00~10:30 ■ 타임빠소셜 "
    "실시간 스트리밍 서비스 안내 수, 일요일 소셜은 스윙프렌즈 유튜브채널에서 실시간으로 현장을 "
    "보실수 있습니다.",
)
# Item 5767 (title and the body's own lines; the rest is the cafe's page chrome).
REAL_SURADAN_CLOSED = (
    "26년10월9일(금) 수라댄 금요정모 휴무",
    "26년10월9일(금) 수라댄 금요정모 휴무 - ▒ 공지합니다 - [수라댄] 수원살사 바차타 동호회 "
    "수원라틴댄스사랑방 CAFE ▒ 공지합니다 앱으로보기 26년10월9일(금) 수라댄 금요정모 휴무 "
    "작성자 카이(Kai) | 작성시간 26.10.06 | 조회수 31 목록 댓글 0",
)


class _Post:
    def __init__(self, title, body, published_at=PUBLISHED):
        self.title, self.body, self.published_at = title, body, published_at
        self.acquisition_quality = "FULL"


def _nights(title, body, published=PUBLISHED):
    result = process_discovered_post(None, _Post(title, body, published))
    return [(e.date, e.start_time, e.end_time) for e in result["events"]]


# --- the two real posts ------------------------------------------------------------

def test_the_chuseok_weekend_keeps_wednesday_and_sunday_and_closes_saturday():
    result = process_discovered_post(None, _Post(*REAL_TIMEBAR_CHUSEOK,
                                                 published_at="2026-09-22T10:00:00+09:00"))
    assert [(e.date, e.start_time, e.end_time) for e in result["events"]] == [
        ("2026-09-23", "19:30", None), ("2026-09-27", "19:30", None)]
    for ev in result["events"]:
        closed = [e for e in ev.evidences if e.field == "context" and e.value == CLOSED_DAY]
        assert [(e.inference, e.raw_text) for e in closed] == [("2026-09-26", "토요일 추석연휴 휴무")]


def test_a_stored_closure_notice_is_not_an_event():
    assert _nights(*REAL_SURADAN_CLOSED, published="2026-10-06T10:00:00+09:00") == []


# --- explicit closures -------------------------------------------------------------

TITLE = "클럽 스윙 (10월 24,25일) 주말 소셜 공지"


@pytest.mark.parametrize("saturday", ["토요일 휴무합니다", "토요일은 쉽니다",
                                      "토요일 운영하지 않습니다", "토요일 소셜 저녁 8시 취소"])
def test_a_closed_saturday_leaves_only_the_sunday(saturday):
    body = f"{TITLE} - {saturday} - 일요일 오후 6시부터 소셜"
    assert _nights(TITLE, body) == [("2026-10-25", "18:00", None)]


def test_saturday_open_sunday_closed():
    body = f"{TITLE} - 토요일 저녁 8시부터 소셜 정상 운영 - 일요일 휴무"
    assert _nights(TITLE, body) == [("2026-10-24", "20:00", None)]


def test_a_cancelled_lesson_does_not_take_the_social_with_it():
    body = f"{TITLE} - 토요일 강습 휴강, 소셜은 저녁 8시부터 정상 진행 - 일요일 오후 6시부터 소셜"
    assert _nights(TITLE, body) == [("2026-10-24", "20:00", None), ("2026-10-25", "18:00", None)]


def test_a_refund_policy_closes_nothing():
    body = f"{TITLE} - 토요일 저녁 8시부터 소셜, 취소하시면 환불 - 일요일 오후 6시부터 소셜"
    assert _nights(TITLE, body) == [("2026-10-24", "20:00", None), ("2026-10-25", "18:00", None)]


def test_a_post_that_closes_every_day_it_names_has_no_event():
    assert _nights(TITLE, f"{TITLE} - 토요일 휴무 - 일요일 휴무") == []


def test_a_recurring_schedule_skips_only_its_closed_week():
    nights = _nights("탱고클럽 10월 토요 밀롱가 일정 안내",
                     "10/24(토) 밀롱가 저녁 8시~12시 / 10/31(토) 밀롱가 휴무합니다 / "
                     "11/7(토) 밀롱가 저녁 8시~12시")
    assert nights == [("2026-10-24", "20:00", "00:00"), ("2026-11-07", "20:00", "00:00")]


@pytest.mark.parametrize("title, body", [
    ("공지: 10월 31일 휴무", "10월 31일 토요일 밀롱가는 휴무입니다. 다음 주 정상 운영합니다."),
    ("이번 주 토요일 쉽니다", "이번 주 토요일 밀롱가 쉽니다. 다음 주에 만나요"),
    ("일요일 밀롱가 취소 안내", "10월 25일 일요일 밀롱가 취소되었습니다."),
])
def test_a_holiday_notice_is_not_an_event(title, body):
    assert _nights(title, body) == []


def test_two_closed_days_beside_an_open_one():
    nights = _nights("10/26, 10/27 운영 안내",
                     "10/26, 10/27 운영하지 않습니다. 10/28(수) 저녁 8시 소셜은 정상 진행")
    assert nights == [("2026-10-28", "20:00", None)]


# --- what a closure must never touch -----------------------------------------------

def test_a_closure_about_another_day_keeps_the_event():
    nights = _nights("10월 24일 토요 소셜", "10월 24일 토요 소셜 진행합니다 (일요일은 쉽니다)")
    assert [n[0] for n in nights] == ["2026-10-24"]


def test_a_holidays_name_alone_decides_nothing():
    nights = _nights("10월 24일 토요 소셜",
                     "추석 연휴 잘 보내셨나요? 10월 24일 토요일 저녁 8시부터 소셜 진행합니다.")
    assert nights == [("2026-10-24", "20:00", None)]


def test_an_incidental_closure_in_a_clocked_post_keeps_the_party():
    """Item 5553's shape: '월요일 휴무니까 이번 일요일은 미니파티처럼'."""
    assert not closes_its_day("월요일 휴무니까 이번 일요일은 미니파티처럼 신나게! 저녁 8시 30분")
    nights = _nights("일요일 소셜 파티", "10월 25일 일요일 저녁 8시 소셜 파티. 월요일 휴무니까 "
                                          "이번 일요일은 미니파티처럼 신나게!")
    assert nights == [("2026-10-25", "20:00", None)]


def test_a_date_range_festival_is_unchanged():
    """A written range is a period: one event on its first day, never split."""
    nights = _nights("탱고 마라톤 10월 24일~25일",
                     "탱고 마라톤 10월 24일~25일 토요일 저녁 8시 밀롱가, 일요일 오후 3시 밀롱가")
    assert [n[0] for n in nights] == ["2026-10-24"]


def test_a_multi_date_social_is_unchanged():
    body = f"{TITLE} - 토요일 저녁 8시부터 소셜 - 일요일 오후 6시부터 소셜"
    assert _nights(TITLE, body) == [("2026-10-24", "20:00", None), ("2026-10-25", "18:00", None)]


def test_a_registration_deadline_is_neither_an_event_nor_a_closure():
    body = f"{TITLE} - 신청 마감 10월 22일까지 - 토요일 저녁 8시부터 소셜 - 일요일 오후 6시부터 소셜"
    assert [n[0] for n in _nights(TITLE, body)] == ["2026-10-24", "2026-10-25"]


def test_an_ambiguous_mention_is_not_read_as_a_closure():
    """No day is named before the closure word: nothing is closed."""
    assert not closure_notice_for("휴무 안내", "연휴 동안 휴무가 있을 수 있습니다", "2026-10-24")


def test_a_closure_notice_needs_the_day_it_would_be_read_as():
    assert not closure_notice_for("휴무", "10월 31일 토요일 휴무", None)
    assert closure_notice_for("휴무", "10월 31일 토요일 휴무", "2026-10-31")
    assert not closure_notice_for("휴무", "10월 31일 토요일 휴무", "2026-10-24")
