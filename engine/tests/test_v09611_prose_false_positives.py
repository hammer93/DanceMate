"""v0.96.11 - a month in Buenos Aires read as eight Korean dance nights
(Information Engine 0.97).

``is_non_event_notice()`` has refused a heading that calls itself a recap
since v0.96.0, and one that calls itself an administrative notice since the
same release. Three shapes fall between them, and every one of them is
somebody writing about themselves rather than announcing anything: a trip
counting its own days, a note saying where its writer has been, and a club
asking for sponsorship.

Measured read-only on Production 0ee6a9d / 0.96.10 / engine 0.96, fully
converged, over all 2,351 collected items: 9 classifications move, 8 stop
being events, **1 of them was on public display as upcoming** - item 2034,
dated 2026-10-01 off a body that mentions a Saigon tango marathon its writer
attended. Nothing moves the other way.

**Why there is no prose detector here.** The obvious rule - a long first-
person post with no venue, no fee and no DJ - was simulated on this corpus
before any of this was written: it corrects 10 and destroys 6 genuine
nights, because a real announcement often names none of the three ("🥳
대전까미니또 9월 첫토밀롱가" carries a day and nothing else). So this release
adds title evidence only, in the place v0.96.0 and v0.96.8 already put it,
and it adds three arms rather than a family of words.

**Why two measured tokens were left out.** 풍경 and 어나운스 each catch
exactly one stored false positive and nothing legitimate *today*, which is
how the audit first scored them. They are still not admissible, and
``BARE_NAME_NIGHTS`` is the reason: 102 of Production's 143 public upcoming
events carry a heading that is a bare name with no digits in it, 81 of them
are events only because their collector's prior says so, and this guard is
asked *above* that prior since v0.96.8. A bare noun here does not risk a
false refusal - it overrules the one signal that knows better. 어나운스 is
worse than a coincidence: it is what this scene calls the announcement
segment *of* a milonga, and a real La Vida night announces its own
"매니저님 어나운스 타임" in its body.

``STILL_PROSE`` holds the four the audit counted and this release does not
reach. All four are past-dated; none is on public display as somewhere to go
tonight. Removing them would mean guessing, and zero genuine loss outranks
the count.
"""

import pytest

from src.classifier import classify, is_non_event_notice

from tests.fixture_v09611_prose_false_positives import (
    A_DAY_OF_SOMETHING_REAL,
    BARE_NAME_NIGHTS,
    CALLS_FOR_SPONSORSHIP,
    CAME_HOME,
    NOT_TAKEN_BY_THE_NEW_WORDS,
    STILL_PROSE,
    TRIP_DIARY,
)

TANGO_TERMS = ("milonga", "밀롱가", "practica", "쁘락띠까", "pronga", "쁘롱가",
               "프렉틸롱가", "쁘락밀", "쁘락", "쁘롱")

# What the Argentina diaries actually carried: a Korean date, a milonga name,
# a class, a time. Every ingredient of an announcement except the announcing.
_DIARY_BODY = (
    "📍 La Rosa Milonga (El Beso) 중급반 14:00~15:00 강사 ㅡ Marcela Guabara "
    "밀롱가 15:00~18:00 오늘 엘베소에서의 수업은 뮤지컬리티와 고급반"
)


# --- T1 a trip counting its own days --------------------------------------

@pytest.mark.parametrize("ref,title", TRIP_DIARY)
def test_a_trip_counting_its_own_days_is_not_a_night(ref, title):
    """The number is the trip's, not the night's. Six of these seven held a
    visible events row on Production, dated in Korea for days spent in
    Argentina."""
    assert is_non_event_notice(title, TANGO_TERMS), ref
    assert classify(title, _DIARY_BODY, event_terms=TANGO_TERMS) == "OTHER", ref


@pytest.mark.parametrize("title", A_DAY_OF_SOMETHING_REAL)
def test_a_day_of_a_real_event_keeps_its_night(title):
    """T8. The second question the arm asks, and the whole reason it asks
    one: a multi-day event counts its days too, and says so in the same
    heading."""
    assert not is_non_event_notice(title, TANGO_TERMS)
    assert classify(title, "9월 20일 20:00~23:00 입장료 15,000원",
                    event_terms=TANGO_TERMS) in {
        "MILONGA", "MILONGA_WITH_CLASS", "SOCIAL", "SOCIAL_WITH_CLASS"}


def test_the_number_alone_is_never_enough():
    """Asserted directly, so the guard cannot be simplified away into a bare
    word list later without this failing."""
    from src.classifier import _TRIP_DAY_TITLE_RE

    heading = "춘천탱고마라톤 2일차 밀롱가"
    assert _TRIP_DAY_TITLE_RE.search(heading)
    assert not is_non_event_notice(heading, TANGO_TERMS)


# --- T2 somebody saying where they have been ------------------------------

@pytest.mark.parametrize("ref,title", CAME_HOME)
def test_a_note_about_coming_home_is_not_a_night(ref, title):
    """T9. The hard gate. Public upcoming on Production, dated 2026-10-01."""
    assert is_non_event_notice(title, TANGO_TERMS), ref
    assert classify(
        title,
        "안녕하세요 베트남에서 142기 쏠땅 기수 하러 두달 탱고유학 왔었던 "
        "우노입니다. 142기 발표회 하기위해 어제 귀국했습니다. 10월1일부터 "
        "6일 싸이공탱고 마라톤",
        event_terms=TANGO_TERMS,
    ) == "OTHER", ref


# --- T4 a club asking for sponsorship -------------------------------------

@pytest.mark.parametrize("ref,title", CALLS_FOR_SPONSORSHIP)
def test_a_call_for_sponsorship_is_not_a_night(ref, title):
    assert is_non_event_notice(title, TANGO_TERMS), ref
    assert classify(title, "협찬 마감: 2026년 9월 12일(토) PM 18:00까지 "
                           "댓글로 속히 협찬 신청을 올려주시옵소서",
                    event_terms=TANGO_TERMS) == "OTHER", ref


@pytest.mark.parametrize("title", NOT_TAKEN_BY_THE_NEW_WORDS)
def test_the_new_words_do_not_take_the_nights_beside_them(title):
    """T7. 귀국 is conjugated and 협찬 is a phrase for exactly this reason: a
    night welcoming somebody home, and a night thanking its sponsors, are
    both nights."""
    assert not is_non_event_notice(title, TANGO_TERMS)


# --- T6 / the bare-noun tokens this release refuses to add ----------------

@pytest.mark.parametrize("ref,title", BARE_NAME_NIGHTS)
def test_a_night_whose_whole_title_is_its_name_survives(ref, title):
    """T6. These are real, currently-upcoming Production milongas whose
    headings are nothing but a brand name. They are what a bare-noun token
    would take, and they are events only because their collector's prior says
    so - a prior this guard is asked above."""
    assert not is_non_event_notice(title, TANGO_TERMS), ref
    assert classify(title, "", known_event_type="MILONGA",
                    event_terms=TANGO_TERMS) == "MILONGA", ref


def test_the_rejected_tokens_are_actually_absent():
    """T3/T5 read the other way. 풍경 and 어나운스 were measured safe on
    today's corpus and are still not in the guard; if a later release adds
    one, it must delete this test and say why rather than inherit it."""
    from src.classifier import _ADMIN_NOTICE_TITLE_RE, _RECAP_TITLE_RE

    for word in ("풍경", "어나운스", "포토"):
        assert not _RECAP_TITLE_RE.search(word), word
        assert not _ADMIN_NOTICE_TITLE_RE.search(word), word
    assert not is_non_event_notice("밀롱가 풍경", TANGO_TERMS)
    assert not is_non_event_notice("9월 정모 어나운스", TANGO_TERMS)
    assert not is_non_event_notice("포토파티 8월 22일(토)", TANGO_TERMS)


@pytest.mark.parametrize("ref,title", STILL_PROSE)
def test_the_prose_this_release_does_not_reach(ref, title):
    """Named rather than quietly left out. Each is a real false positive that
    no arm here explains; each is past-dated and invisible to "where can I
    dance tonight"."""
    assert not is_non_event_notice(title, TANGO_TERMS), ref


# --- T10 the earlier releases' own contracts ------------------------------

# Shapes, not ids: the reading each release is named for. None may move.
EARLIER_CONTRACTS = [
    # v0.96.0: the recap half that has been here all along
    ("축하소셜 스케치 영상", "", "OTHER"),
    # v0.96.8: the night is off, and the prior does not save it
    ("26년9월25일(금) 수라댄 금요정모 휴강", "", "OTHER"),
    # v0.96.8: the prior still answers everything the guard does not
    ("디디디", "", "MILONGA"),
    # v0.96.5: a night announced in the title of a post whose body teaches
    ("💢대전까미니또 초고급밀롱가",
     "●수업 7시~7시50 💢밀롱가 8시~10시30 ❤️입문ㆍ초중급반 수업하러 오세요",
     "MILONGA_WITH_CLASS"),
    # v0.96.7: a course written only in the education vocabulary
    ("Milonga Autumn Edition vol.1 - 3주 완성 밀롱가 리듬 클래스",
     "3주 완성 커리큘럼", "CLASS"),
    # v0.96.10: a course the post's own heading sells
    ("Lv3.린디베이직 강습 신청",
     "대상: Lv.2 린디입문 과정 이수자 ⏰매주 토요일: 16:00~18:00 "
     "(소셜타임 18:00~22:00) 📍장소: 강습 인원...", "CLASS"),
    # v0.96.10: and the night that teaches, which must not move with it
    ("금요소셜데이♡챔피온 칸쌤 특강♡인천살사엘마르 금요...",
     "금요일에는 엘마르 소셜데이! 특별히 이번주에는 챔피언 칸쌤의 특강이 "
     "있는 날입니다. 특강부터 소셜 + 뒤풀이까지", "SOCIAL_WITH_CLASS"),
]


@pytest.mark.parametrize("title,body,expected", EARLIER_CONTRACTS)
def test_earlier_releases_keep_their_readings(title, body, expected):
    known = "MILONGA" if title == "디디디" else None
    assert classify(title, body, known_event_type=known,
                    event_terms=TANGO_TERMS) == expected


def test_the_guard_still_takes_a_title_on_its_own():
    """The signature gained an optional argument; every existing caller
    passes one string and must keep working."""
    assert is_non_event_notice("축하소셜 스케치 영상") is True
    assert is_non_event_notice("디디디") is False
    assert is_non_event_notice("") is False
    assert is_non_event_notice(None) is False
    # and the trip arm works without Settings terms, on the built-in words
    assert is_non_event_notice("🇦🇷아르헨티나 29일차 (9월 2일ㆍ수)") is True
    assert is_non_event_notice("춘천탱고마라톤 2일차 밀롱가") is False
