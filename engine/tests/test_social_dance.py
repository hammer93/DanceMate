"""Social dance classification (Information Engine v0.75).

Tango names its social event and the engine knew that word. Salsa and swing
call theirs a 소셜 or a 파티, and the engine called them OTHER — so a swing
community contributed twenty-three readable posts and zero events.

Every string here reproduces a *form* found in the twenty-three swing posts
collected on 2026-09-04. None is a stored copy of a post: no phone numbers, no
account numbers, no full bodies. What matters is the shape.

The hard half is not finding socials. It is not finding them where they are not:
six of those twenty-three say 소셜 or 파티 without announcing one, and a
keyword match would turn every lesson advert into a night out.
"""

import pytest

from src.classifier import classify, social_evidence
from src.extraction_rules import parse_time_range
from src.extractor import extract_single
from src.live_pipeline import EVENT_CLASSIFICATIONS


# --- what counts as announcing a social -------------------------------------

@pytest.mark.parametrize("title,body", [
    # Announced in the title, which is how the recurring ones are written.
    ("■ 스윙타임빠 (9월 2일) 수 소셜 공지",
     "수요일 저녁 7시30분부터 소셜이 진행 됩니다. DJ 데미안 PM 8:15~10:15"),
    ("[월간 슬로우 소셜파티_SlowJam 12월12일]",
     "분위기는 파티처럼, 입장료는 그대로!"),
    # Announced beside its own clock, which is how a mixed programme lists it.
    ("BAL&SHAG 스페셜 워크샵",
     "일정 8/8 (토) - 15:00-16:30 발스윙 중고급 - 20:00-22:30 소셜"),
])
def test_a_social_that_is_being_announced_is_evidence(title, body):
    assert social_evidence(title, body) is True


@pytest.mark.parametrize("title,body", [
    # A lesson blurb explaining where you will use what you learn.
    ("문이화 베이직원정대 Swing Out Variation",
     "린디합의 기초를 함께 연습하고, 소셜에서 조금 더 편안하게 활용하기 위한 스타일을"),
    ("ShineSteps 9월 멤버모집",
     "소셜부터 공연 및 대회까지 실력을 향상 시키고 개성있는 댄서가 되어 봅시다"),
    ("들라&칼요의 Jazz UP 시즌2",
     "스윙아웃, 슈가푸시, 서클 - 매번 소셜에서 쓰는 동작들이죠"),
    # A season ticket for socials is not a social.
    ("■ 스윙타임빠 수요일 정기권을 판매합니다",
     "기간내에 타임빠 수 소셜의 입장을 할 수 있는 정기권입니다. 3개월 단위 6만원"),
    # A ticket bundle is not a party.
    ("부산린디합위캔 BLW파티팩 오픈했어요",
     "올 해 BLW 파티팩이(89,000원) 오픈 되었습니다! 신청링크"),
    # A performance date is not a social's clock.
    ("At the Savoy Season 17 모집합니다",
     "공연날짜 : 10월 31일(토) 스윙스캔들 졸업파티 강습 일정: 매주 오후 4시~7시"),
])
def test_a_social_merely_mentioned_is_not_evidence(title, body):
    """Six of twenty-three real posts do this. A keyword match would turn every
    one of them into an event."""
    assert social_evidence(title, body) is False


def test_a_duration_is_not_a_clock():
    """'10시간 이상 소셜' is a festival boasting about its length, not a social
    written next to the time it starts."""
    assert social_evidence("가성비 행사 2025", "<10시간 이상 소셜>과 <대회>를 함께") is False


# --- classification ---------------------------------------------------------

def test_tango_is_unchanged():
    """The whole tango path has to behave exactly as it did in v0.74."""
    assert classify("9/5(토) 더 피스타 밀롱가", "장소: PISTA 입장료 13,000원") == "MILONGA"
    assert classify("밀롱가 안내", "강습 후 밀롱가가 이어집니다") == "MILONGA_WITH_CLASS"


def test_a_swing_social_is_an_event():
    assert classify(
        "■ 스윙타임빠 (9월 2일) 수 소셜 공지",
        "수요일 저녁 7시30분부터 소셜이 진행 됩니다. DJ 데미안 PM 8:15~10:15",
    ) == "SOCIAL"


def test_a_salsa_party_is_an_event():
    assert classify("금요 살사 소셜 파티", "9월 5일 금요일 PM 9:00~2:00 DJ 안내") == "SOCIAL"


def test_a_lesson_advert_is_a_class():
    for title, body in (
        ("스윙입문 138기 모집안내", "기간 : 8월 22일(토) 시간 : 토요일 오후 6시20분~7시55분"),
        ("발보아 초중급 클래스 모집", "강습 일시 날짜 : 7월 6, 13, 20, 27 시간 : 오후 8:15~9:45"),
    ):
        assert classify(title, body) == "CLASS"


def test_a_workshop_with_a_social_keeps_the_social():
    """Reading this as a class only is what lost every swing event."""
    assert classify(
        "BAL&SHAG 스페셜 워크샵 in 대전",
        "강사: 랭보&홍지 일정 8/8 (토) - 15:00-16:30 발스윙 중고급 "
        "- 16:45-18:15 쉐그 초급 - 20:00-22:30 소셜",
    ) == "SOCIAL_WITH_CLASS"


def test_a_post_that_is_no_kind_of_event_stays_out():
    assert classify("공지사항", "회원 게시판 이용 규칙을 안내드립니다") == "OTHER"


@pytest.mark.parametrize("classification,is_event", [
    ("MILONGA", True),
    ("MILONGA_WITH_CLASS", True),
    ("SOCIAL", True),
    ("SOCIAL_WITH_CLASS", True),
    ("CLASS", False),
    ("OTHER", False),
])
def test_only_the_types_a_dancer_can_attend_become_candidates(classification, is_event):
    assert (classification in EVENT_CLASSIFICATIONS) is is_event


# --- the social's own hours -------------------------------------------------

def test_the_social_runs_at_its_own_time_not_the_workshops():
    """Three ranges in one post; the social is the third. Taking the first
    would send someone to a class they did not sign up for."""
    text = ("일정 8/8 (토) - 15:00-16:30 발스윙 중고급 - 16:45-18:15 쉐그 초급 "
            "- 20:00-22:30 소셜")
    social = parse_time_range(text, "SOCIAL_WITH_CLASS")
    assert (social.start, social.end) == ("20:00", "22:30")


def test_without_an_event_type_the_first_range_still_wins():
    """v0.74 behaviour, unchanged for every caller that does not pass a type."""
    text = "일정 - 15:00-16:30 발스윙 - 20:00-22:30 소셜"
    assert parse_time_range(text).start == "15:00"


def test_a_milongas_hours_are_still_the_milongas():
    text = ('8월 22일 토요일 7:30-8:45pm 지노&유니 특강 "밀롱게로스의 비밀"(올레벨) '
            "9pm-1am 밀롱가 헨떼 아미가")
    reading = parse_time_range(text, "MILONGA")
    assert (reading.start, reading.end, reading.end_day_offset) == ("21:00", "01:00", 1)


def test_a_marked_evening_social_is_read_as_evening():
    """Wrong Time = 0 is not negotiable for a new event type either."""
    reading = parse_time_range(
        "수요일 저녁 소셜 DJ 데미안 PM 8:15~10:15", "SOCIAL",
    )
    assert (reading.start, reading.end) == ("20:15", "22:15")
    assert reading.meridiem_evidence == "EXPLICIT"


# --- the whole post ---------------------------------------------------------

def test_a_swing_social_extracts_into_a_candidate():
    candidate = extract_single(
        "■ 스윙타임빠 (9월 2일) 수 소셜 공지",
        "수요일 저녁 7시30분부터 소셜이 진행 됩니다. DJ 데미안 PM 8:15~10:15",
        event_type="SOCIAL",
    )
    assert candidate.event_type == "SOCIAL"
    assert (candidate.start_time, candidate.end_time) == ("20:15", "22:15")


def test_a_social_is_never_verified_on_discovery_alone():
    """A community post is not a venue confirming its own night. The evidence
    gate is untouched by this release."""
    candidate = extract_single(
        "금요 살사 소셜", "9월 5일 금요일 PM 9:00~11:00 입장료 15,000원",
        event_type="SOCIAL", source_role="COMMUNITY",
    )
    assert candidate.status != "VERIFIED"


def test_the_default_event_type_is_unchanged_for_existing_callers():
    candidate = extract_single("밀롱가 안내", "9월 5일 시간: PM 07:30~11:30")
    assert candidate.event_type == "MILONGA"
    assert (candidate.start_time, candidate.end_time) == ("19:30", "23:30")


def test_the_event_type_reaches_the_time_rule_through_extract_single():
    """A patch once changed the compatibility shim instead of the real call
    site, so the workshop's 15:00 was stored as the social's start time while
    the rule itself was picking 20:00 correctly."""
    candidate = extract_single(
        "🌊BAL&SHAG 스페셜 워크샵 in 대전",
        "소셜에서 바로 써먹을 수 있는 무브를 다룹니다. 강사: 랭보&홍지 "
        "일정 8/8 (토) - 15:00-16:30 발스윙 중고급 - 16:45-18:15 쉐그 초급 "
        "- 20:00-22:30 소셜 8/9 (일) - 13:00-14:30 슬로우발",
        event_type="SOCIAL_WITH_CLASS",
    )
    assert (candidate.start_time, candidate.end_time) == ("20:00", "22:30")


def test_the_compatibility_shim_still_works_without_a_type():
    from src.extractor import _norm_time

    assert _norm_time("시간: PM 07:30~11:30")[:2] == ("19:30", "23:30")
