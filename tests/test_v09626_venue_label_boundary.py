"""v0.96.26: where a labelled venue name ends.

Four Production Events showed a location that was not one:

    "안산 단원구 민속공원로 85, B1 🎂파티음식 맛집! 🍾외부 술·반입 환영! ⏰ 타임테이블 20"
    "압구정 TOP Bar 정택일 25주년 × 라틴시그니엘 3주년 협찬 & 경품 UP"
    "장소 카디즈 스튜디오"
    "장소 R스튜디오"

**The brief asked for a length problem and the corpus says it is not one.**
Over all 472 Production Events carrying a venue (114 distinct strings): 0 longer
than 60 characters, 110 longer than 40 - and **107 of those 110 already
resolved** to the Venue Master. They are Miltang's own
``Name (한글 이름) (주소)`` renderings, which v0.82.5 deliberately keeps whole
because the second bracket is the only text naming the venue's region. Trimming
by length would destroy every one of them to fix four. Length was never the
defect; the semantic boundary was.

Two defects, then. A labelled value ran past the end of the venue because the
section that followed had no marker - and the "<name>스튜디오" shortcut, which
allows up to three words before the suffix so it can find a venue in
"with DJ 롭 이데알 탱고 까페", swallowed the *label word* on a body that wrote
`장소` with no colon at all.

Every marker added here was measured against the venue strings that are correct
today, over 1,462 stored bodies and 1,675 stored OCR texts. A marker is usable
only if it never appears inside one. `주차` failed that test outright - it sits
inside four *resolved* venues (`…황제주차빌딩 2층`) - and `파티`, `소셜`, `무료`,
`특강`, `이벤트`, `안내`, `공지`, `신청`, `할인`, `모집` were left out for the
opposite reason: common after a label, but with no remaining case to fix.
"""

from __future__ import annotations

import sys

import pytest

from runtime.config import REPO_ROOT

# The engine package is reached the way `runtime.engine_ingest._engine()` reaches
# it - by path insertion, because the two suites are separate packages and the
# runtime suite's `pythonpath` is the repository root alone.
if str(REPO_ROOT / "engine") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "engine"))


def _venue(text: str):
    from src import extraction_rules

    reading = extraction_rules.extract_venue(text)
    return None if reading is None else reading.name


# --- the four Production cases ----------------------------------------------

def test_f1_ad_copy_after_the_address_is_not_part_of_the_venue():
    """F1, `/lessons/5000`. A pictograph once the name has started is the next
    section: the address stays, the party copy goes."""
    assert _venue(
        "장소: 안산 단원구 민속공원로 85, B1 🎂파티음식 맛집! 🍾외부 술·반입 환영! "
        "⏰ 타임테이블 20~21시: 로건&BK 바차타 파트너십 오픈강습"
    ) == "안산 단원구 민속공원로 85, B1"


def test_f2_a_sponsorship_section_ends_the_name():
    """F2, `/lessons/4350`. `협찬` cuts the sponsor paragraph. The event title
    between the venue and that heading has no marker of any kind, so this is an
    improvement rather than a fix, and it is recorded as one."""
    got = _venue(
        "장소 : 압구정 TOP Bar 정택일 25주년 × 라틴시그니엘 3주년 협찬 & 경품 UPDATE "
        "특별한 자리를 위해 보내주시는 따뜻한 협찬과 후원에 진심으로 감사드립니다"
    )
    assert got == "압구정 TOP Bar 정택일 25주년 × 라틴시그니엘 3주년"
    assert "협찬" not in got and "경품" not in got


@pytest.mark.parametrize("text, expected", [
    ("00:00 장소 카디즈 스튜디오", "카디즈 스튜디오"),
    ("19:00 장소 R스튜디오", "R스튜디오"),
    ("10:50 장소 양재동 스튜디오", "양재동 스튜디오"),
    ("5시 장소 EDM 댄스스튜디오", "EDM 댄스스튜디오"),
    ("9시20분 장소 한라댄스스튜디오", "한라댄스스튜디오"),
    ("장소 경성홀 8:00", "경성홀"),
])
def test_f3_the_suffix_shortcut_no_longer_swallows_the_label_word(text, expected):
    """F3/F4 and the nine other Production posts the same shape reached. No
    Korean venue is called "장소 X"."""
    assert _venue(text) == expected


def test_a_place_named_with_only_the_label_word_is_still_refused():
    """The guard drops a leading label, never a whole name: "장소 스튜디오" has
    nothing left that is a place, so no venue is read from it."""
    assert _venue("21:00 장소 스튜디오") is None


# --- the markers, and why these ones -----------------------------------------

@pytest.mark.parametrize("tail, expected", [
    ("협찬 품목: 주류, 음료", "일영 마당뜰 펜션"),
    ("경품 추첨 안내", "일영 마당뜰 펜션"),
    ("후원 계좌 안내", "일영 마당뜰 펜션"),
    ("타임테이블 20~21시", "일영 마당뜰 펜션"),
    ("타임 테이블 20~21시", "일영 마당뜰 펜션"),
    ("드레스코드 정장", "일영 마당뜰 펜션"),
    ("드레스 코드 정장", "일영 마당뜰 펜션"),
    ("Time Table 20:00", "일영 마당뜰 펜션"),
    ("수강료 25만원", "일영 마당뜰 펜션"),
    ("강습료 8만원", "일영 마당뜰 펜션"),
])
def test_each_added_section_heading_ends_the_name(tail, expected):
    assert _venue(f"장소: 일영 마당뜰 펜션 {tail}") == expected


def test_a_car_park_in_the_address_is_not_a_boundary():
    """`주차` was the one rejected candidate: 23 occurrences after a venue label,
    but inside four *resolved* venues. A venue whose address names a car park
    keeps it."""
    for venue in ("Amigo (아미고) (부산시 부산진구 부전로 34 황제주차빌딩 2층)",
                  "아미고 스튜디오 (부산진구 서면 황제주차장, 부산진구 부전로 34)",
                  "아미고 (서면 황제주차장 건물 2층, 부산 부산진구 부전로 34)"):
        assert _venue(f"장소: {venue} 주최: GatotangO 반복: 매주 수요일") == venue, venue


@pytest.mark.parametrize("word", ["파티", "소셜", "무료", "특강", "이벤트",
                                  "안내", "공지", "신청", "할인", "모집"])
def test_a_word_with_no_case_to_fix_was_not_made_a_boundary(word):
    """Each is common after a venue label, and none of them cut anything this
    release needed cut. A rule nobody can point at a defect for is a rule whose
    cost nobody measured."""
    assert word in (_venue(f"장소: 루에다 파티 {word} 자세한 내용") or "")


# --- the pictograph boundary --------------------------------------------------

def test_a_pictograph_only_ends_a_name_that_has_already_started():
    """A label's value routinely opens with one, and `_strip_decoration()` is
    what removes those - so the boundary waits until a real character has been
    passed. Exactly two emoji appear inside any Production venue today, both in
    F1's string; 200+ appear within 140 characters after a label."""
    assert _venue("장소: 홍턴 지하 2층 💰 수강료 및 할인 혜택") == "홍턴 지하 2층"
    assert _venue("장소: 📍 아미고 스튜디오 DJ 롭") == "📍 아미고 스튜디오"
    assert _venue("@ 신천 비바스윙 with 앙마의유혹쌤 ▣▣.... ▣▣▣ 스윙댄스 린디합 초급") \
        == "신천 비바스윙 with 앙마의유혹쌤"


# --- what must not change ---------------------------------------------------

LEGIT = [
    "MARINE TANGO (마린땅고) (경남 창원시 마산합포구 동서서4길 10, 2층 (태진전자음향 2층))",
    "Andante (안단테) (서울시 마포구 양화로 12길 24 선진빌딩 B1(합정역 3번 출구))",
    "La Ventana (라 벤따나) (서울시 마포구 잔다리로 48, 정원빌딩 2층)",
    "Tango club Mi Noche (경남 창원시 마산합포구 가포로25 지하1층)",
    "까미니또 (대전 유성 계룡로66번길 5 / 3중)",
    "Tango Magenta, B1, 709 Seolleung-ro, Gangnam-gu, Seoul",
    "PosTango (포스탱고) (포항시 남구 중앙로 83, 3층)",
]


@pytest.mark.parametrize("venue", LEGIT)
def test_a_long_venue_with_its_own_address_is_kept_whole(venue):
    """The 107 already-resolved long strings. Nothing here trims by length."""
    assert _venue(f"장소: {venue} 주최: Alex 반복: 매주 일요일") == venue


def test_a_venue_followed_by_its_own_bare_address_still_yields_the_name():
    """`이데알` is what resolves to venue 4222; the address after the comma is the
    address. Unchanged."""
    assert _venue("장소 : 이데알, 부산 서면 700비어 3층") == "이데알"


@pytest.mark.parametrize("tail", [
    "DJ 홍길동", "DJ: 홍길동", "시간: 20:00~23:00", "입장료: 10,000원",
    "문의: 010", "주최: 누군가", "저녁 7시", "[ 테이블 ]",
])
def test_the_boundaries_that_were_already_there_still_end_the_name(tail):
    assert _venue(f"장소: Studio X {tail}") == "Studio X"


def test_the_v0962_at_venue_readings_are_unchanged():
    assert _venue("9월 24일 저녁 8시 @오초") == "오초"
    assert _venue("9월 16일 9:15-11:15pm @ 아미고 스튜디오") == "아미고 스튜디오"
    assert _venue("@Studio Ocho 7:30pm") == "Studio Ocho"
    assert _venue("@ 올어바웃스윙 홀") == "올어바웃스윙 홀"
    assert _venue("@allaboutswing 팔로우 부탁드립니다") is None
    assert _venue("인스타그램 DM: @intothelatinittl") is None


def test_the_suffix_reading_that_needs_its_leading_words_still_works():
    """`_SUFFIX_VENUE_RE`'s three-word window exists for this; the label guard
    must not narrow it."""
    assert _venue("with DJ 롭 이데알 탱고 까페 19:30") == "이데알 탱고 까페"
    assert _venue("아미고 스튜디오 9:15pm") == "아미고 스튜디오"


def test_the_v09624_unlabelled_image_contract_is_untouched():
    from src.extractor import extract_with_image_fallback

    ev = extract_with_image_fallback(
        "무차살사소셜", "9/20(토) 21:00~01:00", event_type="SOCIAL", published="2026-09-01",
        image_texts=[("img1", "무차살사소셜 @ 스스 me1 입장료 10,000원")])
    assert ev.venue is None
    kept = extract_with_image_fallback(
        "탱고 이벤트", "9/5(토) 19:30-23:30 입장료 13,000원",
        event_type="MILONGA", published="2026-09-01",
        image_texts=[("img1", "탱고 이벤트 장소: 라밀롱가 스튜디오")])
    assert kept.venue == "라밀롱가 스튜디오"
