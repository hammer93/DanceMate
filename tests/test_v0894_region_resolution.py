"""v0.89.4 Region Master Coverage & Resolution.

Four real Production Communities had no Region to resolve to at all:
전주살사 바차타 라틴크루즈 (Jeonju), 여수 엘카리베라틴클럽 (Yeosu), 천안세븐
(Cheonan), and 서당탱고 (Seosan/Dangjin) - all in provinces (전북/전남/충남)
that had no Region row at all. This file locks in the fix: four new
province-level Regions (migrations/runtime/038_region_master_coverage.sql)
and REGION_HINTS coverage wide enough for their real cities, while keeping
the existing "ambiguous stays unresolved, never guess the nearest Region"
rule exactly as it was (Section 10-11: 천안 was deliberately left blank
rather than filed under the wrong province in an earlier review - this file
proves that same discipline, never a name-only auto-fill).
"""

from __future__ import annotations

from datetime import date

import pytest

from runtime import master_data
from runtime import community_discovery as cd

TODAY = date(2026, 9, 14)

# Every Region code this project's REGION_HINTS covers, mirroring exactly
# what load_context() would build from a real DB with all of them present -
# a pure-function fixture, no DB needed for the pure detect_region tests.
_REGION_NAMES = {
    "KR-SEOUL": "서울", "KR-GYEONGGI": "경기", "KR-INCHEON": "인천", "KR-BUSAN": "부산",
    "KR-DAEJEON": "대전", "KR-DAEGU": "대구", "KR-GWANGJU": "광주", "KR-ULSAN": "울산",
    "KR-JEJU": "제주", "KR-CHUNGBUK": "충북", "KR-GYEONGBUK": "경북", "KR-GYEONGNAM": "경남",
    "KR-CHEONGJU": "청주", "KR-JINJU": "진주", "KR-CHANGWON": "창원", "KR-POHANG": "포항",
    "KR-JEONBUK": "전북", "KR-JEONNAM": "전남", "KR-CHUNGNAM": "충남", "KR-GANGWON": "강원",
}


def all_regions():
    out = []
    for i, (code, name) in enumerate(_REGION_NAMES.items(), start=1):
        hints = tuple(dict.fromkeys((name,) + cd.REGION_HINTS.get(code, ())))
        out.append((code, i, name, hints))
    return out


def resolve(text):
    return cd.detect_region(text, all_regions())


# === Section 36: resolver positive cases ========================================================

@pytest.mark.parametrize("text, expected_name", [
    ("전주", "전북"), ("전주시", "전북"), ("전라북도 전주시", "전북"),
    ("여수", "전남"), ("여수시", "전남"),
    ("천안", "충남"), ("천안시", "충남"), ("충남 천안", "충남"), ("충청남도 천안시", "충남"),
    ("서산", "충남"), ("당진", "충남"),
    ("청주", "청주"),   # existing dedicated Region - never pulled up into 충북
    ("포항", "포항"),   # existing dedicated Region
    ("진주", "진주"),   # existing dedicated Region
    ("제주", "제주"), ("서귀포", "제주"),
    ("서울 강남", "서울"), ("서울 마포", "서울"),
])
def test_resolver_positive_cases(text, expected_name):
    region_id, name = resolve(text)
    assert region_id is not None, f"{text!r} should resolve, got unresolved"
    assert name == expected_name


# === Section 18: 서산+당진 both under 충남 resolve to ONE region, never picked between ===========

def test_seosan_and_dangjin_together_resolve_to_the_single_shared_province():
    region_id, name = resolve("서산 / 당진 지역 탱고 동아리")
    assert (region_id, name) == resolve("서산")
    assert name == "충남"


# === Section 15: other existing province gaps (충북/경북/경남 without their own city) ===========

@pytest.mark.parametrize("text, expected_name", [
    ("충주", "충북"), ("제천", "충북"),
    ("경주", "경북"), ("구미", "경북"),
    ("김해", "경남"), ("거제", "경남"),
])
def test_other_province_cities_without_their_own_region_resolve_to_the_province(text, expected_name):
    region_id, name = resolve(text)
    assert region_id is not None
    assert name == expected_name


# === Section 37: negative cases - never auto-confirm an ambiguous or unrelated region ===========

@pytest.mark.parametrize("text", [
    "Boston", "전국", "서울/부산", "수도권 전체", "전국모임", "온라인", "지역 없음",
    "전국 각지에서 활동", "우리는 전국구 동호회입니다",
])
def test_negative_cases_never_auto_resolve(text):
    region_id, _name = resolve(text)
    assert region_id is None


def test_multi_region_text_stays_unresolved_with_both_named():
    region_id, name = resolve("서울과 부산에서 함께 활동합니다")
    assert region_id is None
    assert name == "부산/서울"


# === Section 39: Discovery integration - region_candidate resolves through the real pipeline ====

@pytest.fixture
def six(pg):
    existing = {g["code"] for g in master_data.list_genres(pg)}
    for code in cd.TARGET_GENRES:
        if code not in existing:
            master_data.create_genre(pg, code=code, name=code.title())
    return {g["code"]: g["genre_id"] for g in master_data.list_genres(pg)}


@pytest.fixture
def jeonbuk_chungnam(pg):
    """The two new Regions this release adds, created through the same
    master_data.create_region() contract the Admin route itself uses -
    ON CONFLICT-safe against a DB that already has them (Production)."""
    existing = {r["code"] for r in master_data.list_regions(pg)}
    ids = {}
    for code, country, city, name in (
        ("KR-JEONBUK", "South Korea", "Jeonbuk", "전북"),
        ("KR-CHUNGNAM", "South Korea", "Chungnam", "충남"),
    ):
        if code not in existing:
            master_data.create_region(pg, code=code, country=country, city=city, name=name)
    for r in master_data.list_regions(pg):
        if r["code"] in ("KR-JEONBUK", "KR-CHUNGNAM"):
            ids[r["code"]] = r["region_id"]
    return ids


def hit(url, *, title="", snippet="", published=None, source_name=None, source_url=None,
        provider=cd.KAKAO, kind="cafe", query="", genre_hint=None):
    return cd.Hit(provider=provider, kind=kind, query=query, genre_hint=genre_hint, url=url,
                  title=title, snippet=snippet, published=published, source_name=source_name,
                  source_url=source_url)


def _items(pg, unique):
    return [i for i in cd.list_items(pg, limit=500)[0] if unique in i["identity_key"]]


@pytest.mark.postgres
def test_discovery_candidate_resolves_a_previously_unresolvable_province(pg, unique, six,
                                                                          jeonbuk_chungnam):
    """Case (Section 39): "천안 바차타 동호회" - Production candidate #23's
    own shape - now resolves to 충남 end to end through store_hits(), not
    just the pure detect_region() call."""
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/cheonan894{unique}/1",
                           title="천안 바차타 동호회 정모 공지", snippet="이번 주 정모입니다",
                           published=TODAY, source_name=f"천안바차타{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert item["region_id"] == jeonbuk_chungnam["KR-CHUNGNAM"]


@pytest.mark.postgres
def test_discovery_never_guesses_a_single_region_for_multi_city_text(pg, unique, six,
                                                                      jeonbuk_chungnam):
    """"서울과 전북에서 활동" (Section 12) must never resolve to either one.

    KR-SEOUL and KR-JEONBUK specifically (not KR-BUSAN): KR-BUSAN was only
    ever added ad hoc through the Admin console in Production, never
    migration-seeded (see migrations/runtime/024_regional_coverage_
    expansion.sql's own comment) - a fresh DB genuinely has no Busan Region
    at all, which would make "서울과 부산" resolve to Seoul alone here for a
    reason that has nothing to do with this release's own ambiguity rule.
    """
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/multicity894{unique}/1",
                           title="전국모임", snippet="서울과 전북에서 활동하는 동호회입니다",
                           published=TODAY, source_name=f"전국동호회{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert item["region_id"] is None


# === Regression: existing behaviour outside this release's scope is untouched ===================

def test_existing_seoul_gyeonggi_resolution_is_unaffected():
    assert resolve("홍대 살사 정모")[1] == "서울"
    assert resolve("수원 스윙댄스 동호회")[1] == "경기"


def test_a_genre_master_lacking_a_region_still_resolves_on_pure_text():
    # detect_region never depends on genre_ids at all - a quick sanity check
    # that this release did not accidentally couple the two.
    assert resolve("대구 탱고 동호회")[1] == "대구"
