"""v0.96.5 - a night announced in the title, lost to a lesson in the body
(Information Engine 0.93).

Measured on Production after v0.96.4's 0.92 re-extraction had fully
converged - 1,180 stored bodies, 0 remaining, 0 failed - so what follows is
the classifier's own reading, not a stale one.

``social_evidence()`` has let a *title* announce a night for the other
scenes since v0.79: a 소셜 or 파티 in the heading is the announcement, and
``classify()``'s CLASS branch defers to it. The milonga family never had
that rule. So a post whose title names a real night, dated, timed and
placed, was read as CLASS - and produced no candidate at all - as soon as
its body mentioned a lesson anywhere: the milonga's own half-hour warm-up,
a beginners' round starting the same week, a visiting couple's workshop,
even a studio's "20여년 강습경력" in the cafe boilerplate.

Twelve Production items, one still upcoming. Sweeping all 2,267 collected
items - each classified the way the runtime classifies it, with its own
known_event_type and the Settings event terms - changes exactly those
twelve, every one of them CLASS -> MILONGA_WITH_CLASS, and nothing else in
either direction. Six further posts of the same aggregator shape would be
rescued by the rule too and are deliberately not counted: their collector
already tags them known_event_type=MILONGA, which classify() answers on
before any of this is reached.

The rule cannot be social_evidence()'s, because a lesson advert names the
milonga it teaches you to dance at, in its own title, beside its own date
("[금요특강] 26년 9월 18일 시작!! 밀롱가/땅고 실전패턴!!"). It is three
tests, not one - see announced_night_evidence()'s own comment - and both
sides of the line are tested here from the real posts.
"""

import pytest

from src.classifier import announced_night_evidence, classify
from src.collectors.base import RawPostRecord
from src.live_pipeline import EVENT_CLASSIFICATIONS, process_discovered_post
from tests.fixture_v0965_night_false_negatives import (
    AMBIGUOUS, RESCUED, STAYS_A_CLASS,
)


class Dummy:
    """A connection the live pipeline never touches for these posts."""


def _post(title, body, published, **kw):
    return RawPostRecord(
        source_id="SRC-D-011", platform="DAUM_CAFE",
        source_url="https://example.invalid/post",
        title=title, body=body, published_at=published,
        acquisition_quality="FULL_TEXT", **kw)


def _processed(title, body, published, **kw):
    return process_discovered_post(Dummy(), _post(title, body, published, **kw),
                                   "SECONDARY")


# --- The Production regression set -----------------------------------------

@pytest.mark.parametrize("ref,title,body,published", RESCUED,
                         ids=[row[0] for row in RESCUED])
def test_a_night_named_in_the_title_survives_a_lesson_in_the_body(
        ref, title, body, published):
    """Every one of these produced events=[] at engine 0.92.

    Asserted as MILONGA_WITH_CLASS, not merely "some event type": a plain
    MILONGA would mean the body carries no class word at all and the fixture
    had stopped reproducing the defect.
    """
    assert classify(title, body) == "MILONGA_WITH_CLASS", ref
    result = _processed(title, body, published)
    assert len(result["events"]) == 1, ref


@pytest.mark.parametrize("ref,title,body,published", STAYS_A_CLASS,
                         ids=[row[0] for row in STAYS_A_CLASS])
def test_a_lesson_advert_naming_a_milonga_is_still_not_a_night(
        ref, title, body, published):
    """The other side of the same line: a course, a recap, a ticket bundle."""
    assert classify(title, body) not in EVENT_CLASSIFICATIONS, ref
    assert _processed(title, body, published)["events"] == [], ref


@pytest.mark.parametrize("ref,title,body,published", AMBIGUOUS,
                         ids=[row[0] for row in AMBIGUOUS])
def test_a_title_that_offers_a_free_lesson_is_left_exactly_as_it_was(
        ref, title, body, published):
    """A real night whose *title* carries a class word (item 256).

    Reading it would mean letting a title say 강습 and still announce, which
    is the one widening that could also rescue an advert. v0.96.5 does not
    take it: the post classifies as it did before, and this test is here so
    that stays a decision.
    """
    assert classify(title, body) == "CLASS", ref
    assert _processed(title, body, published)["events"] == [], ref


# --- T1..T3: the rule, stated on its own -----------------------------------

def test_t1_title_names_the_night_and_the_body_merely_teaches():
    title = "9월 19일 토요일 밀롱가 라비다"
    body = ("날짜: 2026년 9월 19일\n시간: 20:00~23:30\n장소: 아미고스튜디오\n"
            "이번주부터 밀롱가전에 왕초급 강습이 시작됩니다.")
    assert classify(title, body) == "MILONGA_WITH_CLASS"


def test_t2_a_title_naming_the_night_cannot_carry_a_course():
    """Same title shape, a body that is a term: tuition, weeks, curriculum."""
    title = "쁘롱가 적응 밀롱가 시퀀스"
    body = ("3/15, 3/22, 3/29, 4/5, 4/12, 4/19 4:20-5:30\n"
            "참가비용: 6주 10만원\n개강 후에는 환불이 어렵습니다\n"
            "☆ 커리큘럼 ☆ 1주차: 축과 커넥션")
    assert classify(title, body) == "CLASS"


def test_t3_a_title_that_sells_a_lesson_is_a_class_whatever_it_names():
    title = "[금요특강] 26년 9월 18일 시작!! 밀롱가/땅고 실전패턴!!"
    body = "📌금요일 8시: 실전 밀롱가 패턴\n장소: 아미고스튜디오\n워크샵기간 휴강"
    assert classify(title, body) == "CLASS"


@pytest.mark.parametrize("heading", [
    "밀롱가 실전 강습 9월 19일",
    "밀롱가 준비 수업 (9/19 20:00)",
    "9월 밀롱가 오픈클래스 모집",
    "Milonga Workshop 9/19 20:00 @아미고",
    "밀롱가 초중급반 9월 19일 20:00",
])
def test_a_heading_that_sells_a_lesson_never_announces(heading):
    body = "날짜: 2026년 9월 19일\n시간: 20:00~23:30\n장소: 아미고스튜디오"
    assert announced_night_evidence(heading, body) is False


def test_a_night_word_in_the_body_alone_never_announces():
    """The title is what has to name it - this is the whole discipline."""
    assert announced_night_evidence(
        "9월 정기 모임 안내",
        "밀롱가 20:00~23:30 장소: 아미고스튜디오 2026년 9월 19일") is False


def test_a_night_named_in_the_title_still_needs_logistics():
    """A mention carries no clock; an announcement does."""
    assert announced_night_evidence(
        "밀롱가 이야기", "지난 밀롱가는 정말 즐거웠습니다. 강습도 좋았어요.") is False


def test_a_night_beside_its_own_clock_needs_no_written_date():
    """Item 3643's shape: "내일" and two adjacent clocks, no date anywhere."""
    assert announced_night_evidence(
        "💢대전까미니또 초고급밀롱가",
        "내일은 행복한 월요일! ●수업 7시~7시50 💢밀롱가 8시~10시30") is True


def test_a_clock_alone_is_not_logistics():
    """Without a day, a place, a fee, a DJ or the night's own clock beside
    it, a lone time is not an announcement."""
    assert announced_night_evidence(
        "밀롱가 소식", "저녁 8시쯤 강습 이야기를 나눴습니다") is False


# --- T4: a night with an open/free lesson attached -------------------------

def test_t4_a_night_with_a_lesson_before_it_still_produces_a_candidate():
    """The real shape of five Production items: the warm-up is in the
    recurrence line, the night is the post."""
    result = _processed(
        "milonga_tu",
        "2026년 9월 3일 시간: 20:00~00:00 장소: O Nada 지역: 서울 "
        "DJ: 시스루 반복: 매주 목요일 7:30 오픈강습",
        "2026-08-27")
    assert result["classification"] == "MILONGA_WITH_CLASS"
    assert len(result["events"]) == 1
    assert str(result["events"][0].date) == "2026-09-03"
    assert str(result["events"][0].start_time) == "20:00"


# --- T5/T6/T7: what this does to the class_event_opt_in path ---------------

_OPT_IN_CLASS = (
    "[가또땅고] 9월 19일 쁘롱가 적응 강습",
    "수업 일정: 2026년 9월 19일 20:00 장소: 아미고스튜디오\n참가비용: 6주 10만원",
    "2026-09-16",
)


def test_t5_an_opt_in_class_instance_is_untouched_and_stays_one_candidate():
    """A CLASS_PRIMARY board's own dated lesson still reaches the opt-in
    path: the new rule refuses its title (강습) and its body (6주 10만원),
    so the classification it depends on is still CLASS."""
    title, body, published = _OPT_IN_CLASS
    assert classify(title, body) == "CLASS"
    result = _processed(title, body, published, class_event_opt_in=True)
    assert result["classification"] == "CLASS"
    assert len(result["events"]) == 1


def test_t6_a_rescued_night_produces_one_candidate_not_two():
    """The rescued post leaves the opt-in path entirely rather than adding
    to it - a post is read once, by one route, whichever way opt-in is set."""
    ref, title, body, published = RESCUED[4]
    assert ref == "2334"
    with_opt_in = _processed(title, body, published, class_event_opt_in=True)
    without = _processed(title, body, published)
    assert len(with_opt_in["events"]) == 1
    assert len(without["events"]) == 1
    assert with_opt_in["classification"] == without["classification"]
    assert (with_opt_in["events"][0].date, with_opt_in["events"][0].start_time) == \
           (without["events"][0].date, without["events"][0].start_time)


def test_t7_a_rescued_night_reads_the_same_way_twice():
    """1 -> 1: re-reading the same stored body yields the same single
    candidate with the same core fields, which is what the incremental
    re-extract relies on to keep an event's identity."""
    ref, title, body, published = RESCUED[4]
    first = _processed(title, body, published)["events"]
    second = _processed(title, body, published)["events"]
    assert len(first) == len(second) == 1
    assert (first[0].date, first[0].start_time, first[0].end_time, first[0].venue) == \
           (second[0].date, second[0].start_time, second[0].end_time, second[0].venue)


# A human-reviewed candidate is protected one level up, in the runtime's own
# re-extract pass, and has been since v0.96.3: `reprocess_acquired()` skips a
# row whose candidate carries a review verdict and still stamps it with the
# running engine version, so it leaves the queue without being re-read (see
# tests/test_v0963_incremental_reextract.py::
# test_a_reviewed_candidate_is_skipped_but_still_leaves_the_queue). Nothing
# in this release touches that path: the classifier is only ever reached for
# a row the pass has already decided to re-read.


# --- T9/T10: what must not move -------------------------------------------

def test_t9_a_multi_programme_schedule_post_is_unchanged():
    """Item 3132: a week's programme under a title that names no night.

    Measured on Production, the real post classifies MILONGA_WITH_CLASS both
    before and after this release - through the *open-class* rule, because
    its Thursday line says "초급 원데이클라스". What matters here is that the
    new rule is never the thing deciding it: the title names no night, so
    announced_night_evidence() refuses before any of its other tests run.
    Take that one phrase away and the same post is a CLASS, and stays one.
    """
    title = "[부산_탱고동호회]가또땅고 9월 둘째주 열탱즐탱 일정..."
    body = ("9/14(월) 8:00~11:00pm 군무 연습 (이데알)\n"
            "9/16(수)_8:00~9:10pm ① 무료 일일 특강 좁은공간 테크닉 (아미고 큰홀)\n"
            "② 초급입문 4주차 (미오)\n[가또땅고 쁘롱가] 9:15~11:15pm (DJ 알루, 아미고 큰홀)\n"
            "9/17(목) 자율연습 Practica (초급 원데이클라스)\n☆9/23(수) 8시 개강☆")
    assert announced_night_evidence(title, body) is False
    assert classify(title, body) == "MILONGA_WITH_CLASS"
    without_the_open_class = body.replace(" (초급 원데이클라스)", "")
    assert announced_night_evidence(title, without_the_open_class) is False
    assert classify(title, without_the_open_class) == "CLASS"


@pytest.mark.parametrize("title,body", [
    # A recap, a video, a photo set.
    ("9월 밀롱가 후기와 사진", "2026년 9월 19일 20:00 아미고스튜디오 강습도 좋았어요"),
    ("지난 밀롱가 스케치 영상", "9월 19일 20:00 장소: 아미고스튜디오 강습 안내"),
    # A ticket product.
    ("밀롱가 정기권 판매 안내", "2026년 9월 19일 20:00 정기권 6만원 강습 포함"),
])
def test_t10_a_recap_or_a_product_never_becomes_a_night(title, body):
    assert classify(title, body) not in EVENT_CLASSIFICATIONS


def test_an_event_classification_reached_before_this_rule_is_unchanged():
    """The rule is checked last on purpose: a post the CLASS branch already
    had an answer for never reaches it."""
    # social_evidence() via the title - SOCIAL_WITH_CLASS, not the new type.
    assert classify("9월 19일 소셜 공지", "20:00 소셜 강습 안내") == "SOCIAL_WITH_CLASS"
    # The open-class rule - MILONGA_WITH_CLASS, as it always was.
    assert classify("밀롱가 원데이 클래스", "9월 19일 20:00 밀롱가 강습") == "MILONGA_WITH_CLASS"
    # No class word at all - the branch is never entered.
    assert classify("9월 19일 밀롱가", "20:00 아미고스튜디오") == "MILONGA"


def test_a_known_event_type_still_wins_over_everything():
    assert classify("[금요특강] 밀롱가 실전패턴", "수강료 8만원",
                    known_event_type="CLASS") == "CLASS"


def test_an_operator_term_can_announce_a_night_in_a_title():
    """v0.86.9's Settings terms add to the built-in words here exactly as
    they add to has_milonga - they never remove one."""
    title = "9월 19일 프렉틸롱가 공지"
    body = "시간: 20:00~23:00 장소: 아미고스튜디오 강습 후 이어집니다"
    assert classify(title, body) == "CLASS"
    assert classify(title, body, event_terms=["프렉틸롱가"]) == "MILONGA_WITH_CLASS"
