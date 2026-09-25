"""v0.96.14 - a night read as the workshop inside it (Information Engine 0.99).

The mirror image of v0.96.10. ``sold_as_a_course()`` has read
danceinfo.net's own per-item category since that release, but only in one
direction: when the site says 강습, the filing outranks a social named in
the heading. When the site says 출빠정보 / 파티 / 정모 - a night to turn up
to - nothing read it at all, and a post that also ran a workshop was judged
by the workshop alone.

Measured read-only on Production e131945 / 0.96.13 / engine 0.98, fully
converged, over all 2,468 collected items, and re-checked against the live
danceinfo.net pages on 2026-09-25. Eleven of the 52 listings the site files
under a night category classify CLASS and produce no candidate; seven of the
eleven are real nights that also teach, five of them still upcoming.

**The question this release answers is not "does this post teach".** It is
whether the thing being sold is the course itself or a night that has a
workshop in it. Group A teaches and is seven nights; group B teaches and is
four courses; the classifier must keep both answers.

**Three conditions, and the category is only the first.** The site's own
filing is a reason to look; the other two are the test
``notice_evidence_bundle()`` already applies to a night named with a
non-scene word - an announcement carries logistics, a mention does not - a
specific day, and a clock. Group C is the measured proof the category cannot
stand alone: two listings filed 출빠정보 are a roundup of other clubs'
schedules and a bar's opening hours, and both are correctly OTHER.

**Simulated before it was written.** On the whole stored corpus the change
moves exactly seven classifications, every one of them CLASS ->
SOCIAL_WITH_CLASS: no event of any kind is lost, no post filed as a course
moves, no OTHER becomes an event, and the 680 items carrying a collector's
``known_event_type`` are untouched.
"""

import pytest

from src.classifier import (
    SOURCE_CATEGORY_CLASS,
    SOURCE_CATEGORY_EVENT,
    classify,
    night_event_bundle,
    notice_evidence_bundle,
    sold_as_a_course,
)
from src.live_pipeline import EVENT_CLASSIFICATIONS

from tests.fixture_v09614_night_with_workshop import (
    FILED_AS_A_NIGHT_AND_STILL_NOT_AN_EVENT,
    FILED_AS_A_NIGHT_BUT_A_COURSE,
    NIGHTS_THE_SOURCE_FILED_AS_NIGHTS,
    SOURCE_FILED_AS_A_COURSE,
    WEEKLY_ROUNDUPS,
)

TANGO_TERMS = ("milonga", "밀롱가", "practica", "쁘락띠까", "pronga", "쁘롱가",
               "프렉틸롱가", "쁘락밀", "쁘락", "쁘롱")


# --- T1/T2/T11/T12/T13 the nights this release restores --------------------

@pytest.mark.parametrize("ref,title,body", NIGHTS_THE_SOURCE_FILED_AS_NIGHTS)
def test_a_night_the_source_filed_as_a_night_is_a_night(ref, title, body):
    """T1/T2: a real night whose body also teaches - a workshop, a free open
    class, a 무료특강 - is an event, not the class inside it."""
    assert classify(title, body, source_category=SOURCE_CATEGORY_EVENT) \
        in EVENT_CLASSIFICATIONS


@pytest.mark.parametrize("ref,title,body", NIGHTS_THE_SOURCE_FILED_AS_NIGHTS)
def test_each_restored_night_was_a_class_before_the_category_was_read(
        ref, title, body):
    """Every one of the seven is CLASS on its own text. This is what the
    release is for, and it is also the proof that none of them was already
    being read by some other rule: take the source's filing away and the
    classifier gives the answer Production gives today."""
    assert classify(title, body) == "CLASS"


@pytest.mark.parametrize("ref,title,body", NIGHTS_THE_SOURCE_FILED_AS_NIGHTS)
def test_the_bundle_itself_reads_each_restored_night(ref, title, body):
    assert night_event_bundle(title, body,
                              source_category=SOURCE_CATEGORY_EVENT)


# --- T3/T4/T5 filed as a night, and still a course -------------------------

@pytest.mark.parametrize("ref,title,body", FILED_AS_A_NIGHT_BUT_A_COURSE)
def test_a_course_filed_as_a_night_is_not_promoted(ref, title, body):
    """T3: the site's own category is not a licence. Three of these four
    name no social, no party and no 정모 anywhere; the fourth names a party
    and gives it neither a day nor a clock of its own."""
    assert classify(title, body, source_category=SOURCE_CATEGORY_EVENT) \
        == "CLASS"
    assert not night_event_bundle(title, body,
                                  source_category=SOURCE_CATEGORY_EVENT)


def test_the_notice_bundle_is_not_what_reads_a_night_here():
    """Why the new reading is not simply ``notice_evidence_bundle()`` handed
    to the CLASS branch. That bundle fires on item 3778 - "MAX NIGHT Free
    Salsa On1 Class" carries the word NIGHT in its heading, a day and a
    clock - and 3778 is a free beginners' class in a practice studio."""
    ref, title, body = next(
        e for e in FILED_AS_A_NIGHT_BUT_A_COURSE if e[0] == 3778)
    assert notice_evidence_bundle(title, body)
    assert classify(title, body, source_category=SOURCE_CATEGORY_EVENT) \
        == "CLASS"


@pytest.mark.parametrize("ref,title,body", SOURCE_FILED_AS_A_COURSE)
def test_a_course_the_source_filed_as_a_course_stays_a_course(
        ref, title, body):
    """T4/T5: v0.96.10's and v0.96.13's contract, unchanged. Includes item
    3840, v0.96.13's own hard gate, and the four listings whose bodies name
    the venue's DJ beside a social - the set a "names a social and a DJ"
    rule would have taken."""
    assert classify(title, body, source_category=SOURCE_CATEGORY_CLASS) \
        == "CLASS"
    assert sold_as_a_course(title, body,
                            source_category=SOURCE_CATEGORY_CLASS)
    assert not night_event_bundle(title, body,
                                  source_category=SOURCE_CATEGORY_CLASS)


def test_item_3840_holds_the_line_it_was_given_in_v09613():
    ref, title, body = next(
        e for e in SOURCE_FILED_AS_A_COURSE if e[0] == 3840)
    assert classify(title, body, source_category=SOURCE_CATEGORY_CLASS) \
        == "CLASS"
    assert classify(title, body, source_category=SOURCE_CATEGORY_CLASS) \
        not in EVENT_CLASSIFICATIONS


# --- T7/T8 filed as a night, and not an event at all ----------------------

@pytest.mark.parametrize("ref,title,body",
                         FILED_AS_A_NIGHT_AND_STILL_NOT_AN_EVENT)
def test_a_roundup_or_a_business_notice_filed_as_a_night_stays_other(
        ref, title, body):
    """T7/T8: the measured reason the source's own filing is one condition
    of three and never the answer. Both are filed 출빠정보 and neither is an
    event - a roundup of other clubs' schedules, and a bar's opening hours."""
    assert classify(title, body, source_category=SOURCE_CATEGORY_EVENT) \
        == "OTHER"


def test_what_actually_protects_the_business_hours_notice():
    """The limit, pinned rather than left to be discovered. The roundup fails
    the bundle on its own - it carries no clock - but the opening-hours
    notice passes it: "아침 6시까지" is a clock, the holiday dates are days,
    and "연휴 크레이지 파티" names a party. What keeps it OTHER is that a bar
    announcing its hours uses no word from ``class_words``, so it never
    enters the branch the bundle is asked in.

    Asserted both ways so the day someone widens ``class_words`` or loosens
    the bundle, this test says which of the two moved."""
    ref, title, body = next(
        e for e in FILED_AS_A_NIGHT_AND_STILL_NOT_AN_EVENT if e[0] == 3771)
    assert not night_event_bundle(title, body,
                                  source_category=SOURCE_CATEGORY_EVENT)

    ref, title, body = next(
        e for e in FILED_AS_A_NIGHT_AND_STILL_NOT_AN_EVENT if e[0] == 3777)
    assert night_event_bundle(title, body,
                              source_category=SOURCE_CATEGORY_EVENT)
    assert classify(title, body, source_category=SOURCE_CATEGORY_EVENT) \
        == "OTHER"
    class_words = ("lesson", "강습", "개강", "모집", "안무반", "공연반",
                   "초중급", "전문가반", "워크샵", "워크숍", "workshop")
    assert not any(w in f"{title} {body}".lower() for w in class_words)


# --- the rule that was rejected, and what it cost -------------------------

@pytest.mark.parametrize("ref,title,body", WEEKLY_ROUNDUPS)
def test_a_weekly_schedule_roundup_is_never_promoted(ref, title, body):
    """A community's week, listing three or four nights at different venues
    on different days beside that week's courses. Each names a social, a DJ
    and a clock, so "social + DJ + clock" - the first rule tried - takes all
    of them, and none has one date it could be given. No collector but
    danceinfo.net carries a category, so requiring the source's own filing
    keeps every one of them out."""
    assert classify(title, body, event_terms=TANGO_TERMS) == "CLASS"
    assert not night_event_bundle(title, body, source_category=None)


def test_a_post_with_no_source_category_is_classified_exactly_as_before():
    """The reading is reachable only from a collector that carries the
    source's own per-item category. Every other source - every Naver cafe,
    every Daum board, every web discovery module - hands None, and None is
    not EVENT."""
    ref, title, body = NIGHTS_THE_SOURCE_FILED_AS_NIGHTS[0]
    assert classify(title, body, source_category=None) == "CLASS"
    assert not night_event_bundle(title, body, source_category=None)


# --- T6/T9/T10 the earlier releases' own contracts ------------------------

# The new reading is placed last in the CLASS branch, after every judgment
# above it has been made exactly as it was. These are the readings each
# earlier release is named for; none of them may move.
EARLIER_CONTRACTS = [
    # T6 v0.96.8: the night is off. Asked above the collector's own prior.
    ("26년9월25일(금) 수라댄 금요정모 휴강", "", "OTHER"),
    # T6 v0.96.0: a recap of a night already danced
    ("정기모임 영상 #01", "#대전살사 #대전바차타", "OTHER"),
    # T9 v0.96.5: a night announced in the title of a post whose body teaches
    ("💢대전까미니또 초고급밀롱가",
     "●수업 7시~7시50 💢밀롱가 8시~10시30 멋진음악ㅡ월광님 "
     "❤️입문ㆍ초중급반 ㅡ편한마음으로 수업하러 오세요",
     "MILONGA_WITH_CLASS"),
    # v0.96.5's own refusal: a lesson advert naming the night it teaches at
    ("[금요특강] 26년 9월 18일 시작!! 밀롱가/땅고 실전패턴!!",
     "수강료 커리큐럼 6회 수업(2달 과정)", "CLASS"),
    # v0.96.7: a course written only in the education vocabulary
    ("Milonga Autumn Edition vol.1 - 3주 완성 밀롱가 리듬 클래스",
     "3주 완성 커리큘럼", "CLASS"),
    # v0.96.7's own protection: a real night announced as a "Special Event"
    ("[부산_탱고동호회]가또땅고 Special Event 9월24일(목...",
     "9월 24일 목요일, 가또땅고 한가위밀롱가가 열립니다. 20:00-24:00 "
     "디제이는 스톤님 참가비 12,000원 장소: 아미고", "MILONGA"),
    # v0.96.11: a trip counting its own days
    ("🇦🇷아르헨티나 29일차 (9월 2일ㆍ수)", "부에노스아이레스", "OTHER"),
]


@pytest.mark.parametrize("title,body,expected", EARLIER_CONTRACTS)
def test_earlier_releases_keep_their_readings(title, body, expected):
    assert classify(title, body, event_terms=TANGO_TERMS) == expected


@pytest.mark.parametrize("title,body,expected", EARLIER_CONTRACTS)
def test_earlier_readings_are_unchanged_under_a_night_filing_too(
        title, body, expected):
    """The same seven, asked again with the source calling them nights. The
    new reading is last in the branch, so nothing that already had an answer
    can reach it - including the 휴강 guard, which is asked above the
    collector's prior and stays there."""
    assert classify(title, body, event_terms=TANGO_TERMS,
                    source_category=SOURCE_CATEGORY_EVENT) == expected


def test_the_collector_prior_still_outranks_the_new_reading():
    """T10: v0.96.8's contract. ``known_event_type`` is returned before any
    rule here is reached, and 324 of Production's events exist only because
    of it. Nothing in this release is placed above it."""
    ref, title, body = NIGHTS_THE_SOURCE_FILED_AS_NIGHTS[0]
    assert classify(title, body, known_event_type="MILONGA",
                    source_category=SOURCE_CATEGORY_EVENT) == "MILONGA"
    ref, title, body = next(
        e for e in FILED_AS_A_NIGHT_BUT_A_COURSE if e[0] == 3803)
    assert classify(title, body, known_event_type="SOCIAL",
                    source_category=SOURCE_CATEGORY_EVENT) == "SOCIAL"


def test_the_new_reading_never_takes_an_event_away():
    """It is reached only where the branch was about to return CLASS, so it
    can add a night and can never remove one. Asserted on the shape rather
    than left to the placement: a night already read by the social branch
    keeps the type that branch gives it."""
    title = "금요소셜데이 9월 26일 with 챔피온 칸쌤 특강"
    body = "소셜 오픈 9시 강습 8시~9시"
    assert classify(title, body) == "SOCIAL_WITH_CLASS"
    assert classify(title, body, source_category=SOURCE_CATEGORY_EVENT) \
        == "SOCIAL_WITH_CLASS"
