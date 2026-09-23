"""v0.96.10 - a course read as the night it teaches you to dance at
(Information Engine 0.96).

The social family's missing half of v0.96.5. ``announced_night_evidence()``
has refused a post whose own heading sells a lesson since v0.96.5, and
v0.96.7 gave ``classify()`` an education branch on the same test - but only
for the milonga family. ``social_evidence()`` still returns True the moment a
소셜 or a 파티 appears in a heading, or beside a clock anywhere in the body,
and the CLASS branch defers to it without ever asking whether the post is
selling the course itself.

Measured read-only on Production fe212b2 / 0.96.9 / engine 0.95, fully
converged, over all 2,345 collected items: ten reach a reader through that
gap, and two of them are upcoming - item 186 ("Lv3.린디베이직💚 강습 신청",
2026-09-26) and item 3746 ("대회실전 트레이닝", 2026-10-11, "3회 12만원 /
1회 4만원").

**The rule has three readings and one escape, and the escape is the point.**
``sold_as_a_course()`` never promotes anything; it only declines to let a
mentioned social carry a lesson advert, and a night the post announces in its
own right still wins by the two bundles the other scenes are already read
with plus a night named in the title beside its own clock. Every member of
``NIGHTS_THAT_TEACH`` is asserted unchanged, because a test that only proved
the false positives gone would be satisfied by refusing everything that
teaches.

**Three of the ten cannot be separated by text and are not.** "살사 소셜
트레이닝", "진짜소셜 시즌8", "살사 소셜패턴" name a social in their own
titles and are lessons about dancing at one; nothing in their words tells
them from "서울살사위크 소셜이벤트" or "[월간 슬로우 소셜파티_SlowJam
12월12일]". danceinfo.net had already sorted them and the collector was
throwing the answer away - that is what ``source_category`` carries, and it
is the only reading admitted to outrank a social named in a heading.

**Simulated before it was written.** On the stored corpus the change moves
eight classifications with the stored rows as they are and twelve once the
source's own category is flowing, every one of them an event losing its
event-ness or an OTHER becoming a CLASS: zero classifications move the other
way, zero genuine events are lost and zero genuine upcoming events are lost.
"""

import pytest

from src.classifier import (
    SOURCE_CATEGORY_CLASS,
    SOURCE_CATEGORY_EVENT,
    classify,
    sold_as_a_course,
)
from src.live_pipeline import EVENT_CLASSIFICATIONS

from tests.fixture_v09610_course_false_positives import (
    LEFT_ON_THE_LINE,
    NIGHTS_THAT_TEACH,
    NOT_FIXED_HERE,
    OPEN_CLASS_BOUNDARY,
    SOURCE_FILED_AS_A_COURSE,
    SOURCE_FILED_AS_A_NIGHT,
    TITLE_SELLS_THE_COURSE,
    TRAINS_BUT_IS_A_NIGHT,
    TRAINS_OVER_A_PRICED_BLOCK,
)

TANGO_TERMS = ("milonga", "밀롱가", "practica", "쁘락띠까", "pronga", "쁘롱가",
               "프렉틸롱가", "쁘락밀", "쁘락", "쁘롱")


# --- T1 the source's own category, and what it may and may not do ---------

@pytest.mark.parametrize("ref,title,body", SOURCE_FILED_AS_A_COURSE)
def test_a_listing_the_source_files_as_a_course_is_not_a_night(ref, title, body):
    """T1/T2/T3. A social named in the heading of a 강습 listing is the
    subject being taught, not an announcement - the source already said so."""
    assert classify(title, body) in EVENT_CLASSIFICATIONS, (
        f"item {ref} is expected to be the false positive this release fixes; "
        "if it no longer classifies as an event without the category, the "
        "fixture has drifted from Production"
    )
    assert classify(title, body, source_category=SOURCE_CATEGORY_CLASS) == "CLASS"


@pytest.mark.parametrize("ref,title,body,expected", SOURCE_FILED_AS_A_NIGHT)
def test_a_listing_the_source_files_as_a_night_stays_a_night(ref, title, body, expected):
    """T7/T8. "출빠정보/강습" is a night that also teaches. Both danceinfo
    events that were public upcoming when this was measured are in it."""
    assert classify(title, body, event_terms=TANGO_TERMS,
                    source_category=SOURCE_CATEGORY_EVENT) == expected
    # and the reading is the same one it had with no category at all
    assert classify(title, body, event_terms=TANGO_TERMS) == expected


def test_the_source_category_never_promotes_anything():
    """EVENT is protective only. A post the text reads as a recap does not
    become a night because a listing page filed it under 출빠정보 - that is
    the Naver known_event_type defect, and this signal must not repeat it."""
    title, body = "지난 정모 사진", "지난주 정모 사진 올립니다"
    assert classify(title, body) == "OTHER"
    assert classify(title, body, source_category=SOURCE_CATEGORY_EVENT) == "OTHER"


def test_an_unmapped_category_classifies_exactly_as_no_category_does():
    """T9. 오픈강습 is mapped to nothing on purpose, so the post is read by
    its own text - and its own text names a 파티 in the heading."""
    for ref, title, body, expected in OPEN_CLASS_BOUNDARY:
        assert classify(title, body) == expected, ref
        assert classify(title, body, source_category=None) == expected, ref


# --- T4 the post's own title -----------------------------------------------

@pytest.mark.parametrize("ref,title,body", TITLE_SELLS_THE_COURSE)
def test_a_title_that_sells_the_course_is_not_carried_by_a_mentioned_social(
        ref, title, body):
    """The hall's standing Saturday slot written into a course timetable -
    "⏰매주 토요일: 16:00~18:00 (소셜타임 18:00~22:00)" - is a fact about the
    hall. Item 186 is public upcoming on Production."""
    assert classify(title, body, event_terms=TANGO_TERMS) == "CLASS"


@pytest.mark.parametrize("ref,title,body", TRAINS_OVER_A_PRICED_BLOCK)
def test_a_title_that_trains_over_a_priced_block_of_sessions_is_a_course(
        ref, title, body):
    """T4. Item 3746 is public upcoming on Production, sold as "3회 12만원 /
    1회 4만원", and reads as a MILONGA today because its body names one."""
    assert classify(title, body, event_terms=TANGO_TERMS) == "CLASS"


@pytest.mark.parametrize("ref,title,body,expected", TRAINS_BUT_IS_A_NIGHT)
def test_training_alone_never_makes_a_course(ref, title, body, expected):
    """Item 2367 is a real Friday practica written in the same word as item
    3746. It prices nothing and sells no block, so nothing here touches it -
    this is why 트레이닝 is not in _TITLE_SELLS_A_CLASS_RE."""
    assert classify(title, body, event_terms=TANGO_TERMS) == expected
    assert not sold_as_a_course(title, body, event_terms=TANGO_TERMS)


# --- T5/T6 nights that teach, and must stay nights -------------------------

@pytest.mark.parametrize("ref,title,body,expected", NIGHTS_THAT_TEACH)
def test_a_night_that_teaches_stays_a_night(ref, title, body, expected):
    """T5/T6. The casualty set of every cruder rule considered. 221 and 136
    are the real boundary: both sell a lesson in their own heading and both
    are nights."""
    assert classify(title, body, event_terms=TANGO_TERMS) == expected


@pytest.mark.parametrize("ref,title,body,expected", LEFT_ON_THE_LINE)
def test_the_post_v0965_left_on_the_line_does_not_move(ref, title, body, expected):
    """Item 256 is a real night whose own title offers a free lesson an hour
    before it. v0.96.5 refused to rescue it because the one widening that
    would is the one that could also rescue an advert; this release does not
    move it either - in either direction."""
    assert classify(title, body, event_terms=TANGO_TERMS) == expected


def test_the_symmetric_port_of_the_milonga_rule_would_have_cost_item_136():
    """Why the obvious fix was not the fix. "title sells a lesson AND course
    evidence anywhere" catches one of the ten and destroys item 136, whose
    own body carries 커리큘럼 and whose two dated socials are the reason it
    is an event at all. Held as an assertion so the reasoning cannot quietly
    be undone by widening _COURSE_EVIDENCE_RE later."""
    from src.classifier import _COURSE_EVIDENCE_RE, _TITLE_SELLS_A_CLASS_RE

    ref, title, body, expected = next(
        entry for entry in NIGHTS_THAT_TEACH if entry[0] == 136
    )
    assert _TITLE_SELLS_A_CLASS_RE.search(title)
    assert _COURSE_EVIDENCE_RE.search(f"{title} {body}")
    assert classify(title, body) == expected


def test_a_night_announced_with_a_non_scene_word_outranks_every_reading():
    """The escape that separates item 136 from item 186, and the only thing
    that does: notice_evidence_bundle() - a night named with a non-scene word,
    backed by a day and a clock or a place. Both posts sell a course in their
    heading and both carry a social beside a clock in their body."""
    for entry in NIGHTS_THAT_TEACH:
        if entry[0] == 136:
            assert not sold_as_a_course(entry[1], entry[2])
    for ref, title, body in TITLE_SELLS_THE_COURSE:
        if ref == 186:
            assert sold_as_a_course(title, body)


# --- T11 the earlier releases' own contracts -------------------------------

# v0.96.5 rescued twelve nights whose bodies mention a lesson; v0.96.7 kept
# six genuine nights a word list would have destroyed; v0.96.8 corrected 126
# recaps without touching the prior. None of them may move here. Shapes, not
# ids: these are the readings each release is named for.
EARLIER_CONTRACTS = [
    # v0.96.5: a night announced in the title of a post whose body teaches.
    # The 초중급반 line is what puts it in the CLASS branch at all - without
    # a word from class_words this shape never reaches the rule it is here
    # to protect.
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
    # v0.96.8: a club's own archive of a night already danced
    ("정기모임 영상 #01", "#대전살사 #대전바차타", "OTHER"),
    # v0.96.8: the night is off
    ("26년9월25일(금) 수라댄 금요정모 휴강", "", "OTHER"),
]


@pytest.mark.parametrize("title,body,expected", EARLIER_CONTRACTS)
def test_earlier_releases_keep_their_readings(title, body, expected):
    assert classify(title, body, event_terms=TANGO_TERMS) == expected


def test_the_collector_prior_still_outranks_everything_below_the_guard():
    """v0.96.8's contract: known_event_type is returned before any rule here
    is reached, and 119 of Production's 162 public upcoming events depend on
    it. sold_as_a_course() is not placed above it and must not be."""
    title, body = "살사 소셜패턴", "· 살사 · 강습 · 5주간 수업비는 9만원"
    assert classify(title, body, source_category=SOURCE_CATEGORY_CLASS) == "CLASS"
    assert classify(title, body, known_event_type="SOCIAL",
                    source_category=SOURCE_CATEGORY_CLASS) == "SOCIAL"


@pytest.mark.parametrize("ref,title,body,with_prior,without_prior", NOT_FIXED_HERE)
def test_an_item_this_release_deliberately_does_not_reach(
        ref, title, body, with_prior, without_prior):
    """Item 2909 is a course, and this release does not correct it: its Naver
    source hands every item a source-level known_event_type and classify()
    returns that first. Named rather than quietly left out - the day that
    prior is narrowed, this assertion is already here."""
    assert classify(title, body) == without_prior
    assert classify(title, body, known_event_type="SOCIAL") == with_prior
