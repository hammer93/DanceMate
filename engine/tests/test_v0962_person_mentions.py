"""v0.96.2 release-blocker fix (Information Engine 0.91): a person mentioned
after "@" is not a venue, however the Korean is glued together.

Production item 2020 (SRC-D-003) addresses a senior twice. The first
mention, "루 @ 선배님 은 밀롱가에 …", has a detached particle and engine 0.90
refused it. The second, "루 @ 선배님은 지금까지 묵묵부답이다… 기다림에 지친
142기", has the particle attached to the honorific ("선배님은") and its
predicate in the middle of the value - and engine 0.90 stored it as the
venue of candidate 1860. The rules are grammar, not sentences: PERSON +
optional plural + optional attached particle is a person mention; a
multi-word value with a finite predicate on any word is prose. A longer
proper noun that merely starts with an honorific ("선배님카페") survives,
and every real "@" venue form of v0.96.2 still reads as before.
"""

import pytest

from fixture_v0962_precision import AT_VENUE, GATO_WEEKLY_BODY, GATO_WEEKLY_PUBLISHED, GATO_WEEKLY_TITLE
from src import extraction_rules as rules
from src.extractor import extract_single

# Production item 2020, both mentions, in the body's own shape.
ITEM_2020_SECOND_MENTION = "루 @ 선배님은 지금까지 묵묵부답이다… 기다림에 지친 142기, 목청껏 외쳐본다!"
ITEM_2020_FIRST_MENTION = "루 @ 선배님 은 밀롱가에 살다시피 하신다 했다. · 나도 데려가 달라고 바짓가랑이를 붙잡아 보았다."

PERSON_MENTIONS = [
    ITEM_2020_SECOND_MENTION,
    ITEM_2020_FIRST_MENTION,
    "루 @ 선배님은 지금까지 묵묵부답이다. 기다림에 지친 142기",
    "@ 선배님은 이번에 오세요",
    "@ 선배님이 이번에 오신다",
    "@ 선배님가 이번에",            # ungrammatical, still a person
    "@ 선배님께서 이번에 오십니다",
    "@ 선배님도 오세요",
    "@ 선배님을 모십니다",
    "@ 선배님를 모십니다",
    "@ 선배님과 함께",
    "@ 선배님와 함께",
    "@ 선배님에게 전달",
    "@ 선배님한테 전달",
    "@ 형님은 오늘 오십니다",
    "@ 강사님이 말씀하셨다",
    "@ 대표님께서 안내했다",
    "@ 회원님은 기다리고 있다",
    "@ 회원님들을 모십니다",
    "@ 누나가 온다",
    "@ 언니는 오늘",
    "@ 오빠도 온다",
    "@ 쌤께서 오셨습니다",
    "@ 선생님이 오셨습니다",
    "@ 여러분은 준비되셨나요",
    # Prose with a predicate in the middle, no honorific at all.
    "@ 우리는 이미 도착했다 홍대",
    "@ 오늘은 쉽니다 다음주에",
]

# Proper nouns that merely start with an honorific are not person mentions.
NOT_A_PERSON_MENTION = [
    ("@선배님카페", "선배님카페"),
    ("@대표님스튜디오", "대표님스튜디오"),
    ("@ 형제 스튜디오", "형제 스튜디오"),
]


def test_item_2020_second_mention_is_not_a_venue():
    assert rules.extract_venue(ITEM_2020_SECOND_MENTION) is None
    assert rules.extract_venue(ITEM_2020_FIRST_MENTION) is None
    # Both mentions in one body, as Production has them: nothing is read.
    assert rules.extract_venue(ITEM_2020_FIRST_MENTION + " · 그러나 " + ITEM_2020_SECOND_MENTION) is None


@pytest.mark.parametrize("text", PERSON_MENTIONS)
def test_a_person_mention_with_an_attached_particle_is_not_a_venue(text):
    assert rules.extract_venue(text) is None


@pytest.mark.parametrize("text, expected", NOT_A_PERSON_MENTION)
def test_a_proper_noun_that_starts_with_an_honorific_survives(text, expected):
    reading = rules.extract_venue(text)
    assert reading is not None
    assert reading.name == expected


@pytest.mark.parametrize("text, expected", [
    ("@오초", "오초"),
    ("@ 오초", "오초"),
    ("@ 아미고 스튜디오", "아미고 스튜디오"),
    ("@스튜디오242", "스튜디오242"),
    ("@ 신천 비바스윙", "신천 비바스윙"),
    ("@ 이데알 탱고 까페", "이데알 탱고 까페"),
    ("at Studio Ocho", "Studio Ocho"),
    ("@ 올어바웃스윙 홀", "올어바웃스윙 홀"),
] + AT_VENUE)
def test_every_real_at_venue_still_reads(text, expected):
    reading = rules.extract_venue(text)
    assert reading is not None, text
    assert reading.name == expected


def test_the_handle_and_account_rejections_are_unchanged():
    assert rules.extract_venue("문의 @intothelatinittl º 카카오톡") is None
    assert rules.extract_venue("📞 문의 º 인스타그램 DM: @intothelatinittl º 카카오톡 ID: latin_manager") is None
    assert rules.extract_venue("카카오톡 ID: @홍길동") is None


def test_item_3132_schedule_result_is_unchanged():
    ev = extract_single(GATO_WEEKLY_TITLE, GATO_WEEKLY_BODY, event_type="MILONGA_WITH_CLASS",
                        published=GATO_WEEKLY_PUBLISHED)
    assert (ev.date, ev.start_time, ev.end_time) == ("2026-09-16", "21:15", "23:15")
    assert next(e for e in ev.evidences if e.field == "time").raw_text == "9:15~11:15pm"
    assert any(e.field == "context" and e.value == "MULTI_EVENT_CONTEXT" for e in ev.evidences)


# --- before / after ---------------------------------------------------------

# Engine 0.90 (commit 0f15fcb) on PERSON_MENTIONS, captured with engine/src
# stashed: how many of them it still read as a venue. Hard-coded on purpose.
BEFORE_PERSON_FALSE_POSITIVES = 16


def test_after_reads_no_person_mention_as_a_venue_and_keeps_every_place():
    false_positives = sum(rules.extract_venue(text) is not None for text in PERSON_MENTIONS)
    assert false_positives == 0 < BEFORE_PERSON_FALSE_POSITIVES
    kept = sum((r := rules.extract_venue(text)) is not None and r.name == expected for text, expected in AT_VENUE)
    assert kept == len(AT_VENUE)
