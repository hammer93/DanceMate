"""v0.89.3 Community Discovery Evidence Attribution Patch: publisher/news
page classification (Section 13-18, 20-22).

A real Production candidate (#442, news.kbs.co.kr) surfaced during the
v0.89.2 Precision Run: a news article reporting a court case that described
a Salsa club's bylaws, picked up as a COMMUNITY candidate purely because its
text contains the word "동호회". This file locks in a generalized publisher/
news-page signal - never a single hardcoded outlet (KBS included) - and
checks the two false-negative risks explicitly: a real Community's own post
must never flip to NEWS_OR_MEDIA just because it mentions being covered by
the news, or links to a news article. Always synthetic fixtures, never a
write to the real #442 row.
"""

from __future__ import annotations

from datetime import date

import pytest

from runtime import master_data
from runtime import community_discovery as cd

TODAY = date(2026, 9, 14)


def hit(url, *, title="", snippet="", published=None, source_name=None, source_url=None,
        provider=cd.NAVER, kind="web", query="살사 동호회", genre_hint="SALSA"):
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


# === 9-10. News article mentioning a community ==================================================

def test_a_news_subdomain_mentioning_a_community_is_not_a_community():
    """Case B (Section 20): a generic 'news.' publisher subdomain, not a
    hardcoded outlet."""
    assert cd._looks_like_news("news.testbroadcast.example", [],
                               "한 살사 동호회의 규정이 논란이 되고 있다") is not None


def test_the_real_kbs_shaped_domain_is_caught_by_the_general_rule_not_a_special_case():
    """Production candidate #442 (news.kbs.co.kr) - "news." matches the
    same general rule as any other outlet, never a KBS-specific check."""
    assert cd._looks_like_news("news.kbs.co.kr", [], "동호회 규정") is not None


@pytest.mark.postgres
def test_news_article_full_pipeline_is_not_a_community(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(
        f"https://news.testoutlet{unique}.example/", title="살사 동호회 관련 기사",
        snippet="법원은 해당 카페는 살사댄스 동호회의 회원들로 구성돼 고유의 목적을 "
        "가지고 조직을 갖추고 있다고 판단했다")], ctx, None)
    [item] = _items(pg, unique)
    assert item["kind"] == cd.KIND_NEWS
    assert item["classification"] == cd.NOT_A_COMMUNITY
    assert "publisher/news page" in " / ".join(item["reasons"])


# === 11. Generic (non-"news.") known outlet domain needs a co-signal ===========================

def test_a_bare_known_outlet_domain_needs_a_path_or_word_co_signal():
    assert cd._looks_like_news("chosun.com", ["https://chosun.com/"], "아무 내용") is None


def test_a_known_outlet_domain_with_an_article_path_is_news():
    assert cd._looks_like_news("chosun.com", ["https://chosun.com/national/article/12345"],
                               "아무 내용") is not None


def test_a_known_outlet_domain_with_journalism_language_is_news():
    assert cd._looks_like_news("chosun.com", ["https://chosun.com/"],
                               "OOO 기자가 보도했다") is not None


# === 12-13. False-negative protection: a real Community stays a Community =====================

def test_community_domain_is_never_flagged_news_regardless_of_text():
    """Section 12: a Community cafe linking to (or quoting) a news article
    about itself must not become NEWS_OR_MEDIA - the host's own domain is
    what matters, not domains or words mentioned inside its post."""
    assert cd._looks_like_news("cafe.daum.net", ["https://cafe.daum.net/x/1"],
                               "저희 기사가 news.kbs.co.kr 에 보도되었습니다 기자") is None


@pytest.mark.postgres
def test_a_community_saying_it_was_featured_in_the_news_stays_a_community(pg, unique, six):
    """Section 21: "우리 동호회가 KBS 뉴스에 소개됐습니다" must never flip the
    Community's own cafe to NEWS_OR_MEDIA."""
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(
        f"https://cafe.daum.net/newsflex{unique}/1", title="우리 동호회가 KBS 뉴스에 소개됐습니다",
        snippet="이번 주 정모 때 함께 시청해요! 회원 여러분 축하합니다", published=TODAY,
        source_name=f"뉴스탄탱고{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert item["kind"] == cd.KIND_COMMUNITY


# === 18-20. Real per-genre positives still classify correctly =================================

@pytest.mark.postgres
def test_real_salsa_community_positive(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/rsalsa{unique}/1", title="살사 정모 안내",
                           snippet="이번 주 토요일 정모입니다", published=TODAY, genre_hint="SALSA",
                           source_name=f"real살사{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert item["genre_codes"] == ["SALSA"]
    assert item["kind"] == cd.KIND_COMMUNITY


@pytest.mark.postgres
def test_real_swing_community_positive(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/rswing{unique}/1", title="스윙댄스 정모 공지",
                           snippet="발보아 워크샵도 진행합니다", published=TODAY, genre_hint="SWING",
                           source_name=f"real스윙{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert set(item["genre_codes"]) == {"SWING", "BALBOA"}


@pytest.mark.postgres
def test_real_tango_community_positive(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/rtango{unique}/1", title="탱고 밀롱가 안내",
                           snippet="이번 주 정모 겸 밀롱가입니다", published=TODAY, genre_hint="TANGO",
                           source_name=f"real탱고{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert item["genre_codes"] == ["TANGO"]


# === 21-24. v0.89.1/v0.89.2 guarantees still hold ===============================================

@pytest.mark.postgres
def test_multi_genre_community_positive_unaffected(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/multi893{unique}/1",
                           title="살사 바차타 동호회 정모", snippet="이번 정모 때 바차타 강습도 있어요",
                           published=TODAY, genre_hint="SALSA",
                           source_name=f"멀티893{unique}")], ctx, None)
    [item] = _items(pg, unique)
    assert set(item["genre_codes"]) == {"SALSA", "BACHATA"}


@pytest.mark.postgres
def test_manual_review_state_preserved_through_the_new_pipeline(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/manual893{unique}/1", title="살사 동호회",
                           source_name=f"보류893{unique}")], ctx, None)
    [seeded] = _items(pg, unique)
    cd.set_review_state(pg, seeded["item_id"], cd.HELD, reviewer="tester")
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/manual893{unique}/1", title="10월 정모 공지",
                           published=date(2026, 10, 1), source_name=f"보류893{unique}")], ctx, None)
    assert cd.get_item(pg, seeded["item_id"])["review_state"] == cd.HELD


@pytest.mark.postgres
def test_confirmed_provenance_still_requires_an_explicit_admin_action(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/conf893{unique}/1", title="9월 정모 공지",
                           published=date(2026, 9, 10), source_name=f"확인893{unique}")], ctx, None)
    [seeded] = _items(pg, unique)
    assert seeded["activity_date_confidence"] == cd.INFERRED


@pytest.mark.postgres
def test_duplicate_grouping_still_works(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    name = f"중복893{unique}"
    weak = hit(f"https://cafe.daum.net/dup893w{unique}/1", title="살사", source_name=name)
    strong = hit(f"https://cafe.daum.net/dup893s{unique}/1", title="9월 정모 안내",
                published=date(2026, 9, 1), source_name=name)
    cd.store_hits(pg, [weak], ctx, None)
    cd.store_hits(pg, [strong], ctx, None)
    items = {("weak" if "dup893w" in i["identity_key"] else "strong"): i for i in _items(pg, unique)}
    assert items["strong"]["classification"] == cd.POSSIBLE_DUPLICATE
    assert items["strong"]["duplicate_of_item_id"] == items["weak"]["item_id"]
