# -*- coding: utf-8 -*-
"""v0.96.32: a venue named after its city, and a step that is not a venue.

Two readings in `engine/src` put a Daejeon milonga in Seoul:

    `장소: 대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)` was cut to the
    empty string, because the rule that drops an address *after* a venue name
    also fired at the head of the value, where there is no name yet.

    `extract_single()` then fell through to its hardcoded known-name list,
    where `"OCHO" in scope.upper()` and `"오나다" in scope` matched a substring
    with no regard for what the post had actually said about where it is.

Every body quoted here is a real stored body (miltang.com, cafe.daum.net,
k-tango.net), kept verbatim so a later change cannot pass these by reading
something the corpus does not contain.
"""

import pytest

from src import extraction_rules
from src.extractor import extract_single

DAEJEON_BOBBY = (
    "2026년 10월 16일 시간: 21:00~02:00 장소: 대전 땅고 오나다 "
    "(대전시 유성구 대학로76번안길 23 지하) 주최: 바비 "
    "원문 링크: https://www.facebook.com/daejeon.tango.o.nada"
)
SEOUL_BULGEUM = (
    "2026년 10월 16일 시간: 21:00~02:00 장소: O Nada (오나다) "
    "(서울 마포구 동교동 200-29 B1) 주최: Sophia 반복: 매주 금요일"
)
# The Latin gloss of a tango step, in a Busan club's class write-up that names
# no place at all (cafe.daum.net/GatotangO/Qbxu/886, 2,928 characters).
BUSAN_CLASS_DIARY = (
    "오늘은 쁠라네오를 배운다. 🔄 쁠라네오는 언제 쓰일까? 오초(Ocho) 이후 "
    "히로(Giro) 중 사카다(Sacada) 후 음악이 늘어질 때 ... 지난 수업 때 배웠던 "
    "상구치또와 마찬가지로 백오초로 시작을 하고, 좌측으로 1회의 백오초를 하고"
)


# --- T1: the venue a post states in its own field, city word and all --------

def test_labelled_venue_named_after_its_city_is_read():
    reading = extraction_rules.extract_venue(DAEJEON_BOBBY)
    assert reading is not None
    assert reading.name == "대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)"
    assert reading.label == "장소"


def test_the_daejeon_address_survives_as_an_alias_candidate():
    reading = extraction_rules.extract_venue(DAEJEON_BOBBY)
    assert "대전 땅고 오나다" in reading.alias_candidates
    assert "대전시 유성구 대학로76번안길 23 지하" in reading.alias_candidates


def test_the_seoul_reading_is_unchanged():
    reading = extraction_rules.extract_venue(SEOUL_BULGEUM)
    assert reading.name == "O Nada (오나다) (서울 마포구 동교동 200-29 B1)"
    assert reading.alias_candidates == [
        "O Nada (오나다) (서울 마포구 동교동 200-29 B1)",
        "O Nada", "오나다", "서울 마포구 동교동 200-29 B1",
    ]


@pytest.mark.parametrize("value,expected", [
    # Real stored values whose head is a city and whose name is the venue.
    ("대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)",
     "대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)"),
    ("대전 스윙잇 댄스홀", "대전 스윙잇 댄스홀"),
    ("부산 일빠(부산 부산진구 신천대로62번길 38 4층)",
     "부산 일빠(부산 부산진구 신천대로62번길 38 4층)"),
    ("서울 반포 한강공원 수변무대", "서울 반포 한강공원 수변무대"),
])
def test_city_named_venues_are_read_whole(value, expected):
    reading = extraction_rules.extract_venue(f"장소: {value}")
    assert reading is not None and reading.name == expected


@pytest.mark.parametrize("value", [
    # Real stored values whose head is a city and whose rest is an address.
    "서울 마포구 동교로 162 르네상스빌딩 3층 린댄스연습실",
    "서울시 마포구 동교동 152-14 지하 1층",
    "서울특별시 강남구 삼성로 634 (지하철 7호선 청담역 인근)",
    "대전광역시 유성구 문화원로6번길 1 지하1층 리트모",
    "경기 수원시 팔달구 효원로307번길 61 지하 1층 (린디성 빠)",
    "경기도 수원, 인계동",
    "대전 서구 갈마동 395-13 동원빌딩 3층",
    "인천 검단구 완정로7번길 1 단춤스튜디오 B1",
    # A snippet cut mid-address still reads as the address it is.
    "서울 광진구...",
])
def test_an_address_in_the_field_still_names_nothing(value):
    assert extraction_rules.extract_venue(f"장소: {value}") is None


def test_a_stop_word_at_the_head_still_names_nothing():
    # The address rule relaxed; the stop-word rule did not.
    assert extraction_rules.extract_venue("장소: DJ : 로띠") is None


def test_an_address_after_a_name_is_still_dropped_from_the_name():
    reading = extraction_rules.extract_venue(
        "장소: 엔빠스(EnPaz Tango Studio) 서울특별시 마포구 잔다리로 48")
    assert reading.name == "엔빠스(EnPaz Tango Studio)"


# --- T2: the known-name fallback is for posts that label nothing ------------

def test_a_post_that_labels_its_place_is_never_given_a_known_name():
    assert extraction_rules.known_venue_fallback(DAEJEON_BOBBY) is None
    assert extraction_rules.known_venue_fallback(SEOUL_BULGEUM) is None


def test_an_unreadable_label_is_not_rescued_by_a_known_name():
    # The post labelled its place and the value is another field's label. We
    # do not know where this is; "오초" in the prose does not tell us.
    assert extraction_rules.known_venue_fallback(
        "밀롱가 안내 장소: DJ : 로띠 오초에서 만나요") is None


def test_a_tango_step_glossed_in_latin_is_not_a_venue():
    assert extraction_rules.known_venue_fallback(BUSAN_CLASS_DIARY) is None


def test_the_korean_compound_back_ocho_is_not_a_venue():
    assert extraction_rules.known_venue_fallback(
        "백오초로 시작을 하고, 좌측으로 1회의 백오초를 하고") is None


@pytest.mark.parametrize("body,expected", [
    # Real posts that name their place in prose and label nothing.
    ("💜9/5(토) THE PISTA MILONGA | 더 피스타 밀롱가 매주 토요일 밤, 홍대 "
     "PISTA에서 열리는 밀롱가 ✨ 🎧 DJ Epitone 📍 홍대 PISTA 서울 마포구 "
     "월드컵북로6길 49 B1", "PISTA"),
    ("🎉 솔로땅고 빠시온 138기 1주년 파티 🎉 📅 10월 13일(화) 오후 8시 "
     "📍 화정 오나다 ❤️ 드레스코드 : 레드", "Tango O Nada"),
    ("OCHO weekly Schedule 8.24~8.30 8/24 무초밀롱가 20:00-24:00", "OCHO"),
    ("Tango O Nada (땅고 오나다) 2026.08.07 Friday 09:00 pm to 02:00 am DJ 태양",
     "Tango O Nada"),
])
def test_a_prose_mention_of_a_known_venue_still_reads(body, expected):
    found = extraction_rules.known_venue_fallback(body)
    assert found is not None and found[0] == expected


def test_the_fallback_keeps_its_historical_raw_text():
    assert extraction_rules.known_venue_fallback(
        "📍 화정 오나다 오후 8시") == ("Tango O Nada", "O Nada/오나다")


# --- T3: through extract_single, the way the pipeline reads a post ----------

def _venue_of(title, body):
    candidate = extract_single(title, body, event_type="MILONGA")
    return None if candidate is None else candidate.venue


def test_extract_single_reads_the_daejeon_venue_from_the_field():
    assert _venue_of("Bobby Millonga", DAEJEON_BOBBY) == (
        "대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)")


def test_extract_single_reads_the_seoul_venue_unchanged():
    assert _venue_of("Milonga Bulgeum", SEOUL_BULGEUM) == (
        "O Nada (오나다) (서울 마포구 동교동 200-29 B1)")


def test_extract_single_gives_the_busan_class_diary_no_venue():
    assert _venue_of("이토록 아름다울 수가 (가또땅고 쿠모y페퍼's 초급심화...",
                     BUSAN_CLASS_DIARY) is None


def test_the_two_october_milongas_no_longer_share_a_venue_string():
    daejeon = _venue_of("Bobby Millonga", DAEJEON_BOBBY)
    seoul = _venue_of("Milonga Bulgeum", SEOUL_BULGEUM)
    assert daejeon != seoul
