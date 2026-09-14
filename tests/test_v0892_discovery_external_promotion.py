"""v0.89.2 Community Discovery Classification Precision Patch: cross-post /
external-promotion attribution (Section 6-8, 14-15).

The real Production failure this file locks in: CASINO RUEDA, a Daum cafe,
had a single collected hit - a third-party tango academy's class-enrollment
ad posted to the cafe's own advertisement board. The v0.89.1 classifier read
that ad's "탱고" genre word and its date as CASINO RUEDA's own activity,
because being a Daum cafe (a GROUP_PLATFORMS identity) was, by itself,
enough to call it KIND_COMMUNITY. This file reproduces that shape with a
synthetic fixture - never against the real row - and checks the fix: an
external-promotion hit never feeds the host's own genre or activity, a
mixed host+external candidate still won't take the ad's date as its own,
and every v0.89.1 guarantee (manual review preservation, duplicate
grouping, activity-date provenance) still holds with the new filtering in
place.
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


# === Section 6-8, Case 1: the CASINO RUEDA pattern ==============================================

@pytest.mark.postgres
def test_an_ad_board_post_never_gives_the_host_cafe_a_genre_it_never_earned(pg, unique, six):
    """Case 1 (Section 17): Community cafe, board = 광고방, post = a third-
    party tango academy's enrollment ad. Expected: the host gains no TANGO
    genre, and kind is UNKNOWN with an explanatory reason - never the
    confident COMMUNITY a bare Daum-cafe identity used to produce."""
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(
        f"https://cafe.daum.net/rueda{unique}/JGiq/364",
        title="10월(대구탱고카니발)낭만의 3040탱고초급&스트레칭반 모집해요",
        snippet="광고방. 20여년 강습경력의 대구탱고카니발 학원 수강생을 모집합니다 #대구탱고학원",
        published=TODAY, source_name=f"CASINO RUEDA{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert item["genre_codes"] == []
    assert item["kind"] == cd.KIND_UNKNOWN
    assert "external promotion evidence only" in " / ".join(item["reasons"])
    assert item["classification"] != cd.VERIFIED_NEW
    assert item["classification"] != cd.NOT_A_COMMUNITY   # not enough evidence either way - Section 7 UNKNOWN


@pytest.mark.postgres
def test_a_board_name_alone_is_a_hint_not_a_verdict(pg, unique, six):
    """Section 18: a generic board name ("정보공유") a real community could
    just as easily use for its own posts must not, by itself, wipe out that
    community's own genuine SALSA genre."""
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(
        f"https://cafe.daum.net/genuine{unique}/1",
        title="정보공유 게시판: 이번 주 살사 정모 공지",
        snippet="우리 살사 동호회 정모 안내입니다. 참석 부탁드려요",
        published=TODAY, source_name=f"진짜살사동호회{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert "SALSA" in item["genre_codes"]
    assert item["kind"] == cd.KIND_COMMUNITY


# === Section 14: a cross-posted ad's date never becomes host activity =========================

@pytest.mark.postgres
def test_an_external_ads_date_never_becomes_the_hosts_own_activity_date(pg, unique, six):
    """Section 14: even mixed in with the host's own (dateless) content, an
    external-promotion hit's date must never freshen the host's own
    activity_date - the exact provenance failure that let the old
    classifier show CASINO RUEDA as ACTIVE today."""
    ctx = cd.load_context(pg, TODAY)
    own = hit(f"https://cafe.daum.net/mixed{unique}/1", title="카페 소개",
             snippet="우리는 대구의 작은 모임입니다", source_name=f"믹스드카페{unique}")
    ad = hit(f"https://cafe.daum.net/mixed{unique}/2", title="광고방: 외부 탱고 학원 강습 모집",
            snippet="타 학원 수강생을 모집합니다", published=TODAY,
            source_name=f"믹스드카페{unique}")
    cd.store_hits(pg, [own, ad], ctx, None)
    [item] = _items(pg, unique)
    assert item["activity_date"] is None
    assert item["activity"] == cd.UNVERIFIED
    assert "TANGO" not in item["genre_codes"]


# === Section 15, 25: v0.89.1 guarantees still hold with the new filtering ======================

@pytest.mark.postgres
def test_manual_review_state_is_still_never_touched_by_a_later_run(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/hold892{unique}/1", title="탱고 동호회",
                           source_name=f"보류892{unique}")], ctx, None)
    [seeded] = _items(pg, unique)
    cd.set_review_state(pg, seeded["item_id"], cd.HELD, reviewer="tester")
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/hold892{unique}/1", title="광고방: 외부 학원 광고",
                           snippet="타 학원 수강생 모집", published=TODAY,
                           source_name=f"보류892{unique}")], ctx, None)
    after = cd.get_item(pg, seeded["item_id"])
    assert after["review_state"] == cd.HELD


@pytest.mark.postgres
def test_activity_date_confidence_is_still_never_confirmed_by_an_automated_run(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/conf892{unique}/1", title="9월 정모 공지",
                           published=date(2026, 9, 10), source_name=f"확인892{unique}")], ctx, None)
    [seeded] = _items(pg, unique)
    assert seeded["activity_date_confidence"] == cd.INFERRED


@pytest.mark.postgres
def test_duplicate_grouping_still_works_alongside_external_hit_filtering(pg, unique, six):
    """Regression: v0.89.1's duplicate detection (same normalized name, no
    duplicate_cleared) must still work once genre/activity is computed off
    filtered host_hits instead of every hit."""
    ctx = cd.load_context(pg, TODAY)
    name = f"필터중복{unique}"
    weak = hit(f"https://cafe.daum.net/dupw892{unique}/1", title="탱고", source_name=name)
    strong = hit(f"https://cafe.daum.net/dups892{unique}/1", title="9월 정모 안내",
                published=date(2026, 9, 1), source_name=name)
    cd.store_hits(pg, [weak], ctx, None)
    cd.store_hits(pg, [strong], ctx, None)
    items = {("weak" if "dupw892" in i["identity_key"] else "strong"): i for i in _items(pg, unique)}
    assert items["strong"]["classification"] == cd.POSSIBLE_DUPLICATE
    assert items["strong"]["duplicate_of_item_id"] == items["weak"]["item_id"]


@pytest.mark.postgres
def test_genre_multi_relation_is_unaffected_by_the_negative_context_change(pg, unique, six):
    """Regression: a multi-genre community (v0.89.0's own coverage) must
    still get every one of its real genres, none suppressed by an unrelated
    negative-context word appearing elsewhere in the same snippet."""
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(
        f"https://cafe.daum.net/multi892{unique}/1", title="살사 바차타 동호회 정모",
        snippet="이번 뒤풀이에 살사소스도 준비했어요. 다음 정모 때 바차타 강습도 있습니다.",
        published=TODAY, source_name=f"멀티장르{unique}", genre_hint="SALSA")], ctx, None)
    [item] = _items(pg, unique)
    assert set(item["genre_codes"]) == {"SALSA", "BACHATA"}
