"""v0.96.7 - a lesson advert read as the night it teaches you to dance at
(Information Engine 0.94).

The mirror image of v0.96.5. ``classify()``'s ``class_words`` decides whether
a post is judged as a class at all, and it has known 강습, 개강, 모집 and
워크샵 since the first version - but never 수업, 특강, 클래스, 클라스, 강좌 or
레슨. A course written only in those words therefore never reached the CLASS
branch at all: it fell straight through to the milonga/social keyword test
below it and became a plain MILONGA or SOCIAL, because a lesson advert names
the night it teaches you to dance at. "10월 31일 - 밀롱가 & 발스" is the last
line of a six-week syllabus and became a Saturday night in October; "Milonga
Autumn Edition vol.1 - 3주 완성 밀롱가 리듬 클래스" became a milonga.

Measured read-only on Production f147af7 / engine 0.93, 0.93 re-extraction
fully converged, over all 2,298 collected items: 121 carry one of those words
and classify as an event, 82 of them with a real ``events`` row.

**Why this is not six more words in ``class_words``.** That was simulated
first. It corrects 19 of the misreadings and changes 131 classifications in
all, destroying six genuine nights - one of them still upcoming - because the
CLASS branch then judges them with rules built for a different question. The
open-class rule promotes item 977's "원데이 클래스" course to
MILONGA_WITH_CLASS on the word 원데이 alone, and item 3127's real night
(가또땅고's 한가위밀롱가, 20:00-24:00, DJ 스톤, 참가비 12,000원) fails
``announced_night_evidence()`` because it is announced as a "Special Event"
rather than in a scene word. ``LOST_TO_A_WORD_LIST`` is that casualty set and
every one of its members is asserted untouched here.

**What the rule actually is.** Both 977 and 3127 carry a day, a place and
``notice_evidence_bundle()``; on Production a title education word appears on
62% of the false positives and 8% of the genuine nights, while a night
announced without a lesson sold in its own heading appears on 45% of the
genuine nights and none of the false positives. So the test is the one
v0.96.5 already trusts to keep a lesson advert out of the milonga family -
``_TITLE_SELLS_A_CLASS_RE`` on the post's own title - checked in its own
branch *after* every existing judgment has been reached exactly as before,
and still losing to a social or a party announced in that same title.

It also loses to a night that has hours of its own, which is the whole
difference between a night named *inside* a course ("3주 완성! 밀롱가 리듬
클래스" - 밀롱가 is what the six weeks are about, and the post carries no
clock at all) and a night the same heading announces alongside the class
("원데이 오픈클래스 & 밀롱가 9/25(금)", body "오픈클래스 19:00 / 밀롱가
20:00-23:00"). Both halves are required - the title must name the night and
the night must be written beside its own clock - so the 자율쁘락 slot inside
a class timetable rescues nothing.

Sweeping all 2,298 items changes 61: 18 stop being events, 6 become
SOCIAL_WITH_CLASS instead of SOCIAL (still events, now naming the lesson they
carry) and 37 become CLASS instead of OTHER. **0 genuine nights lost, 0
upcoming events lost, 0 posts promoted into being an event.**
"""

import pytest

from src.classifier import (
    MILONGA_WORDS, classify, notice_evidence_bundle, social_evidence,
)
from src.collectors.base import RawPostRecord
from src.live_pipeline import EVENT_CLASSIFICATIONS, process_discovered_post
from tests.fixture_v0967_class_false_positives import (
    A_NIGHT_THAT_PRICES_ITSELF, A_NIGHT_THAT_TEACHES, CORRECTED,
    LOST_TO_A_WORD_LIST, UNCHANGED,
)

# ``class_words`` as it stood at engine 0.93, restated so the fixtures can be
# held to the *precondition* of the defect and not merely to its symptom: a
# post that matched one of these never had the problem in the first place.
PRE_V0967_CLASS_WORDS = [
    "lesson", "강습", "개강", "모집", "안무반", "공연반", "초중급",
    "전문가반", "워크샵", "워크숍", "workshop",
]


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


def _fell_through_the_class_branch(title, body):
    """The pre-v0.96.7 reading of this post, restated.

    No 0.93 class word anywhere, so ``classify()`` never entered the CLASS
    branch; a night word, a social or a notice bundle then decided it. Both
    halves must hold or the fixture has stopped reproducing the defect.
    """
    text = f"{title} {body}".lower()
    if any(word in text for word in PRE_V0967_CLASS_WORDS):
        return False
    return bool(
        any(word in text for word in MILONGA_WORDS)
        or social_evidence(title, body)
        or notice_evidence_bundle(title, body)
    )


# --- T10: the Production false positives -----------------------------------

@pytest.mark.parametrize("ref,title,body,published", CORRECTED,
                         ids=[row[0] for row in CORRECTED])
def test_a_lesson_sold_in_its_own_title_is_not_the_night_it_teaches(
        ref, title, body, published):
    """Every one of these is an event on Production at engine 0.93."""
    assert _fell_through_the_class_branch(title, body), (
        f"{ref}: fixture no longer reproduces the 0.93 reading")
    assert classify(title, body) == "CLASS", ref
    assert _processed(title, body, published)["events"] == [], ref


# --- T11: what a word list would have cost ---------------------------------

@pytest.mark.parametrize("ref,title,body,published", LOST_TO_A_WORD_LIST,
                         ids=[row[0] for row in LOST_TO_A_WORD_LIST])
def test_a_night_a_word_list_would_have_destroyed_is_untouched(
        ref, title, body, published):
    """Adding 수업/특강/클래스/강좌/레슨/수강료 to ``class_words`` turns each
    of these into CLASS. Item 3127 was still upcoming when it was measured."""
    assert classify(title, body) in EVENT_CLASSIFICATIONS, ref
    assert len(_processed(title, body, published)["events"]) >= 1, ref


def test_the_release_regression_keeps_its_day_its_door_and_its_fee():
    """Item 3127 in full: the one night the word-list simulation destroyed
    while it was still upcoming."""
    ref, title, body, published = LOST_TO_A_WORD_LIST[0]
    assert ref == "3127"
    # Everything the naive reading would have keyed on is here: a title
    # education word is absent, a *body* one ("오픈특강") is present, and the
    # post is a night by every other measure.
    assert "오픈특강" in body
    assert notice_evidence_bundle(title, body) is True
    assert classify(title, body) == "MILONGA"
    event = _processed(title, body, published)["events"][0]
    assert event.date is not None
    assert event.start_time is not None


# --- T3/T4/T5: a night that teaches keeps its heading ----------------------

@pytest.mark.parametrize("ref,title,body,published,expected", A_NIGHT_THAT_TEACHES,
                         ids=[row[0] for row in A_NIGHT_THAT_TEACHES])
def test_a_night_that_sells_a_class_in_its_title_is_still_a_night(
        ref, title, body, published, expected):
    """The social/party rules the CLASS branch already applies are what beats
    the new rule - a party announced in the same title wins, exactly as it
    does for a post that carries 강습."""
    assert classify(title, body) == expected, ref
    assert expected in EVENT_CLASSIFICATIONS


@pytest.mark.parametrize("ref,title,body,published", A_NIGHT_THAT_PRICES_ITSELF,
                         ids=[row[0] for row in A_NIGHT_THAT_PRICES_ITSELF])
def test_a_night_whose_body_is_full_of_course_words_is_untouched(
        ref, title, body, published):
    """No education word in the *title*, so the rule is never reached - even
    for item 882, whose aggregator files the door price under 수강료."""
    assert classify(title, body) in EVENT_CLASSIFICATIONS, ref
    assert len(_processed(title, body, published)["events"]) >= 1, ref


# --- T12: the posts on the line do not move --------------------------------

@pytest.mark.parametrize("ref,title,body,published,expected", UNCHANGED,
                         ids=[row[0] for row in UNCHANGED])
def test_a_post_on_the_line_classifies_exactly_as_it_did(
        ref, title, body, published, expected):
    """Weekly timetables, a paid guided practica and a festival form are
    genuinely both things at once. This release moves none of them."""
    assert classify(title, body) == expected, ref


# --- T1 / T2 / T3: the three shapes the release names ----------------------

def test_t1_a_course_named_after_the_night_it_teaches_is_a_class():
    assert classify(
        "3주 완성! 밀롱가 리듬 클래스",
        "2026년 9월 14일 시간: 20:00~22:00 장소: Bailamos Tango "
        "3주 완성 밀롱가 리듬 클래스 (9/14·21·28, 월 3회)",
    ) == "CLASS"


def test_t2_a_syllabus_of_dates_never_becomes_an_event():
    result = _processed(
        "토욜 스페셜 원데이 클래스",
        "2026년 9월 5일 장소: 서울시 마포구 동교동 152-14 지하 1층 "
        "9월 5일 – 다양한 바시코 10월 31일 – 밀롱가 & 발스",
        "2026-09-01",
    )
    assert result["classification"] == "CLASS"
    assert result["events"] == []


def test_t3_a_monthly_special_lesson_notice_is_a_class():
    assert classify(
        "9월의 토요특강",
        "매주 토요일 4주수업. 커리큘럼 1주차 8/29, 2주차 9/5. 수강신청서 필수 제출",
    ) == "CLASS"


def test_t4_a_night_announced_as_a_special_event_stays_an_event():
    assert classify(
        "가또땅고 Special Event 9월24일 한가위밀롱가",
        "* 일정 : 9월 24일 목요일 8시pm - 12시am * 장소 : 이데알 스튜디오 "
        "* D J : 스톤 * 밀롱가 참가비 : 12,000원",
    ) in EVENT_CLASSIFICATIONS


def test_t5_a_free_warm_up_in_front_of_a_night_stays_an_event():
    assert classify(
        "9월 24일 한가위밀롱가",
        "19:30 무료강습 20:00~24:00 밀롱가 DJ 스톤 입장료 12,000원",
    ) in EVENT_CLASSIFICATIONS


def test_t6_a_night_word_used_only_inside_a_lesson_name_is_a_class():
    """Section 9A: 밀롱가 is what the course is *about*."""
    for title in ("밀롱가 리듬 클래스", "밀롱가 실전 패턴 수업", "쁘롱가 적응 시퀀스 레슨"):
        assert classify(title, "6주 과정, 수강료 10만원, 커리큘럼 1주차") == "CLASS", title


def test_t7_a_night_with_its_own_schedule_is_protected():
    """Section 9B: the class is an item on the night's timetable, and the
    night has its own hours, its own DJ and its own door price."""
    assert classify(
        "수요 쁘롱가 with DJ ALU",
        "일시: 9월 16일 9:15-11:15pm DJ: ALU 입장료: 오천원 "
        "장소: 아미고 스튜디오 8:00~9:10pm 초급입문 수업",
    ) in EVENT_CLASSIFICATIONS


def test_t7_a_heading_that_announces_both_keeps_the_night():
    """The same heading sells the class *and* announces the night, and the
    night has hours of its own - v0.96.0's own fixture shape."""
    title = "원데이 오픈클래스 & 밀롱가 9/25(금)"
    body = "오픈클래스 19:00 밀롱가 20:00-23:00"
    assert classify(title, body) == "MILONGA"


def test_t6_the_same_words_without_the_night_s_own_hours_are_a_class():
    """The contrast that makes the test above a structure and not a word
    list: take the night's own clock away and only the course is left."""
    assert classify("원데이 오픈클래스 & 밀롱가 9/25(금)",
                    "오픈클래스 수강료 3만원 6회 과정") == "CLASS"
    # And the night's clock alone is not enough when the title never names
    # the night: item 3271's 자율쁘락 slot sits inside a class timetable.
    assert classify("Lady Leaders Class_리딩을 배우고픈 땅게라들을 위한 수업",
                    "8:10-8:40 자율쁘락 8:40-9:50 수업 수강료: 8주 8만원") == "CLASS"


# --- T8: class_event_opt_in --------------------------------------------

def test_t8_an_opt_in_class_still_produces_exactly_one_event():
    """``class_event_opt_in`` reads a dated CLASS as one class instance. A
    post that reaches CLASS through the new rule takes the same single path -
    there is no second candidate and no second classification."""
    title = "[10월_강습 공지] 살사 기초완성반 (토요반)"
    body = "10월 4일 개강. 수업일 : 10월 4일 토요일 오후 2시. 수강료 9만원"
    result = _processed(title, body, "2026-09-20", class_event_opt_in=True)
    assert result["classification"] == "CLASS"
    assert len(result["events"]) == 1


def test_t8_an_opt_in_post_the_new_rule_reaches_is_not_also_a_night():
    """The new branch returns one classification like every other branch;
    a post cannot come out of it as both a class and a milonga."""
    title = "토욜 스페셜 원데이 클래스"
    body = ("수업일 : 10월 31일 토요일 오후 5시. 10월 31일 – 밀롱가 & 발스. "
            "수강료 30,000원")
    result = _processed(title, body, "2026-09-20", class_event_opt_in=True)
    assert result["classification"] == "CLASS"
    assert len(result["events"]) <= 1


def test_an_opt_out_post_of_the_same_shape_produces_nothing():
    title = "토욜 스페셜 원데이 클래스"
    body = "수업일 : 10월 31일 토요일 오후 5시. 10월 31일 – 밀롱가 & 발스"
    assert _processed(title, body, "2026-09-20")["events"] == []


# --- The rule's own boundaries ---------------------------------------------

def test_a_known_event_type_still_wins_over_everything():
    assert classify("토욜 스페셜 원데이 클래스", "10월 31일 – 밀롱가 & 발스",
                    known_event_type="MILONGA") == "MILONGA"


def test_every_judgment_above_the_new_branch_is_reached_first():
    """The branch is checked after the whole CLASS branch on purpose: a post
    that already carries a 0.93 class word never reaches it and is read
    exactly as it was."""
    # The open-class rule, on a post with a 0.93 class word - unchanged.
    assert classify("밀롱가 원데이 클래스",
                    "9월 19일 20:00 밀롱가 강습") == "MILONGA_WITH_CLASS"
    # announced_night_evidence(), v0.96.5 - unchanged.
    assert classify("2026년 9월 19일 토요일 밀롱가 La Vida No.802 DJ 조앤",
                    "20:00 시작 강습 경력 20년") == "MILONGA_WITH_CLASS"
    # social_evidence() via the title - unchanged.
    assert classify("9월 19일 소셜 공지", "20:00 소셜 강습 안내") == "SOCIAL_WITH_CLASS"


def test_a_title_with_no_education_word_is_never_touched():
    assert classify("9월 19일 밀롱가", "20:00 아미고스튜디오 수업 후 이어집니다") == "MILONGA"


def test_the_branch_never_promotes_a_post_into_being_an_event():
    """It can only ever answer CLASS, SOCIAL_WITH_CLASS or the answer the
    social rules would already have given - never OTHER -> an event."""
    assert classify("탱고 수업 안내", "매주 화요일 수강료 8만원") == "CLASS"


def test_an_operator_term_in_a_lesson_title_does_not_rescue_the_lesson():
    """v0.86.9's Settings terms add to has_milonga, and a course named after
    one is still a course."""
    title = "프렉틸롱가 적응 시퀀스 클래스"
    body = "6주 과정, 수강료 10만원, 커리큘럼 1주차"
    assert classify(title, body, event_terms=["프렉틸롱가"]) == "CLASS"
