"""v0.89.3 Community Discovery Evidence Attribution Patch: snippet-only
third-party promotion detection (Section 4-12, 19, 23).

A real Production validation run (v0.89.2 Precision Run #3) found the
CASINO RUEDA row's collected snippet never contains any board-name word
("광고방" etc.) at all - the Naver/Kakao search API simply does not return
the board name a human sees by opening the real page. v0.89.2's external-
promotion detection, built entirely around board-name/explicit-phrase
words, never fires for this real row. This file locks in the fix: an
instructor-bio-plus-enrollment combination, naming a differently-named
academy/course, is now enough on its own - but only when the host's own
community-activity language is absent, so a real Community that also
teaches classes is never mistaken for someone else's ad. Always a
synthetic fixture (see module docstrings on hit_is_external/_looks_like_news
in runtime/community_discovery.py), never a write to the real #437 row.
"""

from __future__ import annotations

from datetime import date

import pytest

from runtime import master_data
from runtime import community_discovery as cd

TODAY = date(2026, 9, 14)


def hit(url, *, title="", snippet="", published=None, source_name=None, source_url=None,
        provider=cd.KAKAO, kind="cafe", query="탱고 동호회", genre_hint="TANGO"):
    return cd.Hit(provider=provider, kind=kind, query=query, genre_hint=genre_hint, url=url,
                  title=title, snippet=snippet, published=published, source_name=source_name,
                  source_url=source_url)


@pytest.fixture
def six(pg):
    existing = {g["code"] for g in master_data.list_genres(pg)}
    for code in cd.TARGET_GENRES:
        if code not in existing:
            master_data.create_genre(pg, code=code, name=code.title())
    return {g["code"]: g["genre_id"] for g in master_data.list_genres(pg)}


def _items(pg, unique):
    return [i for i in cd.list_items(pg, limit=500)[0] if unique in i["identity_key"]]


# === 1. External ad WITHOUT a board name - the real CASINO RUEDA shape =========================

def test_instructor_bio_plus_enrollment_is_external_without_any_board_name():
    """Case 1 (Section 19): no '광고방'/'외부홍보' anywhere in the text, just
    the instructor-bio + enrollment + differently-named-academy pattern the
    real row actually contains."""
    h = hit("https://cafe.daum.net/ruedasalsa/1",
            title="대구탱고카니발 탱고 초급반 모집",
            snippet="20여년 강습경력의 원장이 진행하는 #대구탱고학원 수강생을 모집합니다",
            source_name="CASINO RUEDA")
    assert cd.hit_is_external(h, host_name="CASINO RUEDA")


# === 2. External ad WITH a board name still works (v0.89.2 regression) =========================

def test_board_name_alone_is_still_sufficient():
    h = hit("https://cafe.daum.net/x/1", title="광고방: 외부 학원 강습 모집",
            snippet="타 학원 수강생을 모집합니다")
    assert cd.hit_is_external(h)


# === 3. Host name != promoted entity name ======================================================

def test_mentions_other_entity_ignores_the_hosts_own_name():
    text = "#우리동호회 정기 소셜 안내입니다. #우리동호회 화이팅"
    assert cd._mentions_other_entity(text, "우리동호회") is None


def test_mentions_other_entity_finds_a_differently_named_academy():
    text = "이번 학기 강습 안내 #대구탱고학원 수강생 모집"
    found = cd._mentions_other_entity(text, "CASINO RUEDA")
    assert found and "학원" in found


# === 4. A real Community's own class post is never mistaken for an ad =========================

def test_host_community_signal_protects_a_real_academy_plus_community():
    """Section 6/22: an academy-branded Community's own post about its own
    instructor still counts as HOST evidence once it also carries the
    host's own community-activity language."""
    h = hit("https://cafe.daum.net/y/1", title="정모 겸 강습 안내",
            snippet="20년 강습경력의 원장님이 진행하는 정모입니다. 수강생 모집합니다",
            source_name="우리동네탱고아카데미")
    assert cd.hit_is_external(h, host_name="우리동네탱고아카데미") is None


# === 5. An academy word alone never forces external (Section 12) ==============================

def test_a_bare_academy_word_alone_is_not_external():
    h = hit("https://cafe.daum.net/z/1", title="우리 동호회는 지역 학원과 제휴합니다",
            snippet="자세한 내용은 공지를 참고하세요")
    assert cd.hit_is_external(h, host_name="지역동호회") is None


# === 6-8. Full pipeline: multi-hit evidence, external-only, activity date protection ===========

@pytest.mark.postgres
def test_a_single_foreign_genre_ad_never_outweighs_repeated_host_genre_evidence(pg, unique, six):
    """Case 6 (Section 23): 여러 SALSA host posts + 1 TANGO academy ad -
    host genre stays SALSA-only, the ad's TANGO never gets added."""
    ctx = cd.load_context(pg, TODAY)
    name = f"멀티에비던스살사{unique}"
    host_hits = [
        hit(f"https://cafe.daum.net/multiev{unique}/{i}", title=f"살사 정모 안내 {i}",
           snippet="이번 주 회원 정모입니다", published=date(2026, 9, i), source_name=name,
           genre_hint="SALSA")
        for i in range(1, 4)
    ]
    ad_hit = hit(f"https://cafe.daum.net/multiev{unique}/99",
                title="탱고 초급반 모집", snippet="20여년 강습경력의 원장이 진행하는 "
                "#부산탱고학원 수강생을 모집합니다", published=date(2026, 9, 10), source_name=name)
    cd.store_hits(pg, host_hits + [ad_hit], ctx, None)
    [item] = _items(pg, unique)
    assert item["genre_codes"] == ["SALSA"]
    assert item["kind"] == cd.KIND_COMMUNITY


@pytest.mark.postgres
def test_only_external_ads_and_no_host_evidence_stays_unknown(pg, unique, six):
    """Case 7 (Section 19/23): the CASINO RUEDA shape end to end - a single
    collected hit, entirely someone else's ad, no board-name word at all."""
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(
        f"https://cafe.daum.net/onlyext{unique}/1",
        title="10월(대구탱고카니발)낭만의 3040탱고초급&스트레칭반 모집해요",
        snippet="20여년 강습경력 #대구탱고학원 수강생을 모집합니다", published=TODAY,
        source_name=f"CASINO RUEDA{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert item["genre_codes"] == []
    assert item["kind"] == cd.KIND_UNKNOWN
    assert "instructor/academy self-promotion" in " / ".join(item["reasons"])
    assert item["classification"] != cd.VERIFIED_NEW


@pytest.mark.postgres
def test_an_external_ads_date_never_becomes_host_activity_even_without_board_name(pg, unique, six):
    """Case 8 (Section 9, 19): the ad has a real, recent date; the host's
    own (dateless) content must not inherit it."""
    ctx = cd.load_context(pg, TODAY)
    name = f"믹스드8{unique}"
    own = hit(f"https://cafe.daum.net/mix8{unique}/1", title="카페 소개",
             snippet="우리는 대구의 작은 모임입니다", source_name=name)
    ad = hit(f"https://cafe.daum.net/mix8{unique}/2", title="탱고 초급반 모집",
            snippet="20여년 강습경력 #대구탱고학원 수강생을 모집합니다", published=TODAY,
            source_name=name)
    cd.store_hits(pg, [own, ad], ctx, None)
    [item] = _items(pg, unique)
    assert item["activity_date"] is None
    assert item["activity"] == cd.UNVERIFIED


# === Regression: v0.89.2 context precision still holds =========================================

def test_swing_financial_regression():
    text = "스윙매매 판단, 진입 전 체크리스트. #스윙매매 #주식공부"
    assert "SWING" not in cd.detect_genres(text, {"SWING": 3})


def test_salsa_food_regression():
    text = "살사소스 만드는 법: 토마토와 칠리로 만드는 홈메이드 레시피"
    assert "SALSA" not in cd.detect_genres(text, {"SALSA": 2})


def test_tango_cultural_regression():
    text = "시인이 남긴 시집 속 한 구절, 가사와 앨범 이야기, 정통 라플라타 탱고 리듬"
    assert "TANGO" not in cd.detect_genres(text, {"TANGO": 1})
