"""v0.89.0 Community Discovery: queries, providers, identity, analysis, runs.

Search results never become Communities by themselves: they are staged as one
candidate per public identity (a cafe, a Band, a homepage host ...), with
deterministic evidence, for an operator to review. The provider tests use
fakes - the suite never calls a real API.
"""

from __future__ import annotations

import urllib.error
from datetime import date
from types import SimpleNamespace

import pytest

from runtime import communities, directory, master_data
from runtime import community_discovery as cd
from runtime.directory import DirectoryError

TODAY = date(2026, 9, 12)
ALL_GENRES = {code: n for n, code in enumerate(cd.TARGET_GENRES, start=1)}


def rows_for(genres=cd.TARGET_GENRES):
    return [{"genre_code": g, "keyword": k, "provider_scope": "ALL", "enabled": True}
            for g in genres for k in cd.DEFAULT_QUERIES[g]]


def hit(url, *, title="", snippet="", published=None, source_name=None, source_url=None,
        provider=cd.KAKAO, kind="cafe", query="살사 동호회", genre_hint="SALSA"):
    return cd.Hit(provider=provider, kind=kind, query=query, genre_hint=genre_hint, url=url,
                  title=title, snippet=snippet, published=published, source_name=source_name,
                  source_url=source_url)


def ctx_for(**overrides):
    base = dict(today=TODAY, genre_ids=dict(ALL_GENRES),
                regions=[("KR-SEOUL", 2, "서울", ("서울",) + cd.REGION_HINTS["KR-SEOUL"]),
                         ("KR-BUSAN", 35, "부산", ("부산",) + cd.REGION_HINTS["KR-BUSAN"])],
                region_names={2: "서울", 35: "부산"}, venues=[], venue_names={}, communities=[])
    base.update(overrides)
    return cd.Context(**base)


# === 1. Queries ========================================================================

@pytest.mark.parametrize("genre", cd.TARGET_GENRES)
def test_each_genre_gets_its_default_queries(genre):
    plans = cd.plan_queries(rows_for(), genre_codes=[genre], providers=[cd.NAVER])
    assert [p.text for p in plans] == list(cd.DEFAULT_QUERIES[genre])
    assert all(p.genre_code == genre for p in plans)


def test_the_six_genres_are_exactly_the_requested_ones():
    assert cd.TARGET_GENRES == ("SALSA", "SWING", "TANGO", "BALBOA", "BACHATA", "KIZOMBA")
    assert cd.DEFAULT_QUERIES["SALSA"] == ("살사 동호회", "살사 모임", "살사 커뮤니티", "살사 카페",
                                           "살사 초보 모임")
    assert "Kizomba Korea" in cd.DEFAULT_QUERIES["KIZOMBA"]


def test_every_genre_gets_a_query_before_any_gets_a_second():
    plans = cd.plan_queries(rows_for(), genre_codes=list(cd.TARGET_GENRES), providers=[cd.KAKAO])
    assert [p.genre_code for p in plans[:6]] == list(cd.TARGET_GENRES)
    assert len(plans) == sum(len(v) for v in cd.DEFAULT_QUERIES.values())      # 27, under the cap


def test_regions_combine_with_only_the_first_keywords_of_each_genre():
    plans = cd.plan_queries(rows_for(), genre_codes=["SALSA", "TANGO"], region_names=["서울", "부산"],
                            providers=[cd.NAVER])
    assert [p.text for p in plans] == ["서울 살사 동호회", "서울 탱고 동호회", "서울 살사 모임",
                                       "서울 아르헨티나 탱고 동호회", "부산 살사 동호회",
                                       "부산 탱고 동호회", "부산 살사 모임",
                                       "부산 아르헨티나 탱고 동호회"]


def test_queries_are_deduplicated_capped_and_scoped():
    rows = rows_for(["SALSA"]) + [
        {"genre_code": "SALSA", "keyword": "  살사   동호회 ", "provider_scope": "ALL", "enabled": True},
        {"genre_code": "SALSA", "keyword": "살사 네이버전용", "provider_scope": "NAVER", "enabled": True},
        {"genre_code": "SALSA", "keyword": "꺼진 검색어", "provider_scope": "ALL", "enabled": False},
    ]
    plans = cd.plan_queries(rows, genre_codes=["SALSA"], extra_keywords=["직장인 살사"])
    naver = [p.text for p in plans if p.provider == cd.NAVER]
    kakao = [p.text for p in plans if p.provider == cd.KAKAO]
    assert naver.count("살사 동호회") == 1 and "꺼진 검색어" not in naver
    assert "살사 네이버전용" in naver and "살사 네이버전용" not in kakao
    assert naver.count("직장인 살사") == 1 and kakao.count("직장인 살사") == 1   # extras take a turn too
    assert len(cd.plan_queries(rows_for(), genre_codes=list(cd.TARGET_GENRES),
                               providers=[cd.NAVER], max_per_provider=5)) == 5


# === 2. Providers (fakes only) =========================================================

def test_naver_provider_reads_the_engine_client_records():
    record = SimpleNamespace(source_url="https://cafe.naver.com/salsa4u/77", title="9월 정모",
                             body="홍대 살사 정모", published_at=None, cafe_name="살사포유",
                             raw_json='{"cafeurl": "https://cafe.naver.com/salsa4u"}')
    calls = []

    class Client:
        def search(self, query, **kw):
            calls.append((query, kw))
            return [record]

    rows = cd.NaverProvider(Client()).search("cafe", "살사 동호회", 15)
    assert rows == [{"url": "https://cafe.naver.com/salsa4u/77", "title": "9월 정모",
                     "snippet": "홍대 살사 정모", "published": None, "source_name": "살사포유",
                     "source_url": "https://cafe.naver.com/salsa4u"}]
    assert calls[0][1]["kind"] == "cafe" and calls[0][1]["display"] == 15


def test_kakao_provider_cleans_documents_and_refuses_a_malformed_body():
    client = SimpleNamespace(search=lambda query, sort, page, size: {"documents": [
        {"url": "http://cafe.daum.net/tango/x/1", "title": "<b>탱고</b> 정모", "contents": "밀롱가&amp;",
         "datetime": "2026-09-01T20:00:00.000+09:00", "cafename": "<b>탱고사랑</b>"}]})
    rows = cd.KakaoProvider({"cafe": client, "web": client}).search("cafe", "탱고", 15)
    assert rows[0]["title"] == "탱고 정모" and rows[0]["snippet"] == "밀롱가&"
    assert rows[0]["source_name"] == "탱고사랑"
    broken = SimpleNamespace(search=lambda query, sort, page, size: {"unexpected": 1})
    with pytest.raises(ValueError, match="malformed"):
        cd.KakaoProvider({"cafe": broken}).search("cafe", "탱고", 15)


def _http_error(code):
    try:
        raise urllib.error.HTTPError("https://api.example/search", code, "denied", {}, None)
    except urllib.error.HTTPError as exc:
        try:
            raise RuntimeError(f"search failed: HTTP Error {code}: denied; KakaoAK sk-SECRET123") from exc
        except RuntimeError as wrapped:
            return wrapped


class FakeProvider:
    kinds = ("cafe", "web")

    def __init__(self, name, behaviour):
        self.name = name
        self.behaviour = behaviour
        self.calls = []

    def search(self, kind, query, size):
        self.calls.append((kind, query))
        outcome = self.behaviour(kind, query)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _plans(n=3):
    """n planned searches for each provider."""
    plans = cd.plan_queries(rows_for(["SALSA"]), genre_codes=["SALSA"])
    return ([p for p in plans if p.provider == cd.NAVER][:n]
            + [p for p in plans if p.provider == cd.KAKAO][:n])


def test_success_no_results_and_counts():
    ok = FakeProvider(cd.NAVER, lambda kind, q: [{"url": f"https://cafe.naver.com/c{kind}/1",
                                                  "title": "t", "snippet": "s"}])
    empty = FakeProvider(cd.KAKAO, lambda kind, q: [])
    sleeps = []
    hits, status = cd.collect_hits(_plans(), [cd.NAVER, cd.KAKAO],
                                   {cd.NAVER: ok, cd.KAKAO: empty}.__getitem__, sleep=sleeps.append)
    assert status[cd.NAVER]["status"] == cd.CALL_SUCCESS and status[cd.NAVER]["results"] == 6
    assert status[cd.KAKAO]["status"] == cd.CALL_NO_RESULTS
    assert cd.overall_status(status) == cd.SUCCESS
    assert len(sleeps) == 12                       # a pause after every call, both providers


@pytest.mark.parametrize("code, expected", [(401, cd.ACCESS_LIMITED), (403, cd.ACCESS_LIMITED),
                                            (429, cd.RATE_LIMITED)])
def test_a_refused_or_throttled_kind_stops_and_the_other_provider_carries_on(code, expected):
    refused = FakeProvider(cd.KAKAO, lambda kind, q: _http_error(code))
    ok = FakeProvider(cd.NAVER, lambda kind, q: [])
    hits, status = cd.collect_hits(_plans(), [cd.KAKAO, cd.NAVER],
                                   {cd.NAVER: ok, cd.KAKAO: refused}.__getitem__, sleep=lambda s: None)
    assert status[cd.KAKAO]["status"] == expected
    assert len(refused.calls) == 2                 # one call per kind, then that kind is skipped
    assert status[cd.NAVER]["status"] == cd.CALL_NO_RESULTS
    assert cd.overall_status(status) == cd.PARTIAL_SUCCESS
    assert "sk-SECRET123" not in repr(status)      # redacted before it is stored


def test_a_malformed_response_is_an_error_but_not_a_stop():
    bad = FakeProvider(cd.NAVER, lambda kind, q: ValueError("Expecting value: line 1 (json)"))
    hits, status = cd.collect_hits(_plans(), [cd.NAVER], {cd.NAVER: bad}.__getitem__,
                                   sleep=lambda s: None)
    assert status[cd.NAVER]["status"] == cd.CALL_ERROR
    assert len(bad.calls) == 6                     # tried every planned search
    assert cd.overall_status(status) == cd.FAILED


def test_missing_credentials_are_access_limited_without_a_call(monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    factory = cd.default_provider_factory(settings=None)
    hits, status = cd.collect_hits(_plans(), [cd.NAVER, cd.KAKAO], factory, sleep=lambda s: None)
    assert status[cd.NAVER]["status"] == status[cd.KAKAO]["status"] == cd.ACCESS_LIMITED
    assert "NAVER_CLIENT_ID" in status[cd.NAVER]["errors"][0]
    assert cd.overall_status(status) == cd.FAILED
    assert [p["configured"] for p in cd.provider_availability()] == [False, False]


def test_results_without_a_web_url_are_dropped_and_personal_data_redacted():
    provider = FakeProvider(cd.NAVER, lambda kind, q: [
        {"url": "javascript:alert(1)", "title": "x"},
        {"url": "https://cafe.naver.com/ok/1", "title": "문의 010-1234-5678",
         "snippet": "메일 a.b@example.com 오픈채팅 https://open.kakao.com/o/abcdef 정모"}])
    hits, _ = cd.collect_hits(_plans(1)[:1], [cd.NAVER], {cd.NAVER: provider}.__getitem__,
                              sleep=lambda s: None)
    assert [h.url for h in hits] == ["https://cafe.naver.com/ok/1"] * 2
    assert "010-1234-5678" not in hits[0].title and "example.com" not in hits[0].snippet
    assert "open.kakao.com" not in hits[0].snippet and "정모" in hits[0].snippet


# === 3. Identity =========================================================================

@pytest.mark.parametrize("url, source, key", [
    ("https://cafe.naver.com/salsa4u/12", None, "naver-cafe:salsa4u"),
    ("https://cafe.naver.com/ArticleRead.nhn?clubid=1&articleid=2", "https://cafe.naver.com/Salsa4U",
     "naver-cafe:salsa4u"),
    ("http://cafe.daum.net/TangoKorea/abc/1", None, "daum-cafe:tangokorea"),
    ("https://m.cafe.daum.net/TangoKorea/x", None, "daum-cafe:tangokorea"),
    ("https://band.us/band/123/post/9", None, "band:123"),
    ("https://www.swingclub.example/board/1?page=2", None, "web:swingclub.example"),
    ("https://blog.naver.com/someone/22", None, "naver-blog:someone"),
    ("https://www.youtube.com/watch?v=1", None, "web:youtube.com"),
])
def test_identity_is_the_group_not_the_post(url, source, key):
    assert cd.identify(url, source).key == key


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x", "", None, "https://cafe.naver.com/"])
def test_no_identity_for_unusable_urls(url):
    assert cd.identify(url) is None


# === 4. Analysis ========================================================================

@pytest.mark.parametrize("text, expected", [
    ("홍대 살사 동호회", {"SALSA"}),
    ("살사 & 바차타 소셜", {"SALSA", "BACHATA"}),
    ("스윙댄스 발보아 모임", {"SWING", "BALBOA"}),
    ("아르헨티나 탱고 밀롱가", {"TANGO"}),
    ("바차타 키좀바 파티", {"BACHATA", "KIZOMBA"}),
    ("댄스 동호회", set()),
])
def test_genres_come_from_the_text(text, expected):
    assert set(cd.detect_genres(text, ALL_GENRES)) == expected


def test_a_genre_the_master_lacks_is_not_detected():
    assert set(cd.detect_genres("살사 키좀바", {"SALSA": 2})) == {"SALSA"}


def test_region_resolves_only_when_unambiguous():
    ctx = ctx_for()
    assert cd.detect_region("홍대 살사 정모", ctx.regions) == (2, "서울")
    assert cd.detect_region("서울/부산 연합 모임", ctx.regions) == (None, "부산/서울")
    assert cd.detect_region("살사 모임", ctx.regions) == (None, None)


@pytest.mark.parametrize("hits, expected", [
    ([hit("https://x.example/1", title="9월 정모 안내", published=date(2026, 8, 30))], cd.ACTIVE),
    ([hit("https://x.example/1", title="2026년 7월 파티 후기")], cd.ACTIVE),
    ([hit("https://x.example/1", title="회원 사진", published=date(2026, 8, 30))], cd.UNVERIFIED),
    ([hit("https://x.example/1", title="정모 안내", published=date(2024, 3, 1))], cd.STALE),
    ([hit("https://x.example/1", title="동호회 활동 중단 공지", published=date(2026, 8, 1))], cd.INACTIVE),
    ([hit("https://x.example/1", title="9/13 정모")], cd.UNVERIFIED),          # no year, no date
])
def test_activity_needs_a_dated_post_that_shows_activity(hits, expected):
    assert cd.assess_activity(hits, TODAY)[0] == expected


def test_activity_keeps_the_previous_date():
    state, recent, _ = cd.assess_activity([hit("https://x/1", title="사진")], TODAY,
                                          previous=date(2026, 6, 1))
    assert (state, recent) == (cd.ACTIVE, date(2026, 6, 1))


@pytest.mark.parametrize("url, name, text, kind", [
    ("https://cafe.daum.net/salsa4u", "살사포유", "살사 정모", cd.KIND_COMMUNITY),
    ("https://cafe.daum.net/bar1", "홍대 살사바", "살사 소셜", cd.KIND_VENUE),
    ("https://cafe.daum.net/ac1", "라틴 댄스 아카데미", "살사 강습", cd.KIND_ACADEMY),
    ("https://cafe.daum.net/t1", "김살사 강사", "살사 레슨", cd.KIND_INSTRUCTOR),
    ("https://festival.example/2026", None, "2026 서울 살사 페스티벌 티켓", cd.KIND_EVENT),
    ("https://club.example/", None, "서울 살사 동호회 회원 모집", cd.KIND_COMMUNITY),
    ("https://blog.naver.com/me/1", None, "살사 동호회 후기", cd.KIND_BLOG),
    ("https://www.youtube.com/watch?v=1", None, "살사 동호회", cd.KIND_OTHER),
])
def test_what_a_result_is(url, name, text, kind):
    assert cd.detect_kind(cd.identify(url), name, text, ctx_for())[0] == kind


def test_a_name_that_is_a_registered_venue_is_a_venue():
    ctx = ctx_for(venue_names={"보니따": 4248})
    assert cd.detect_kind(cd.identify("https://cafe.daum.net/bonita1"), "보니따", "살사", ctx) == \
        (cd.KIND_VENUE, "same name as registered venue #4248")


def test_names_come_from_the_group_never_from_a_post_title():
    cafe = cd.identify("https://cafe.naver.com/salsa4u/1")
    assert cd.extract_name(cafe, [hit(cafe.url, title="9월 정모 안내 서울 살사 동호회 ABC",
                                      source_name="살사포유")])[0] == "살사포유"
    assert cd.extract_name(cafe, [hit(cafe.url, title="서울 살사 동호회 ABC 9월 정모 안내")])[0] is None
    assert cd.extract_name(cafe, [hit(cafe.url, title="살사포유 : 네이버 카페")])[0] == "살사포유"
    home = cd.identify("https://swingclub.example/")
    assert cd.extract_name(home, [hit("https://swingclub.example/", title="스윙클럽 동호회 | 홈")])[0] \
        == "스윙클럽 동호회"
    assert cd.extract_name(home, [hit("https://swingclub.example/board/9", title="스윙 동호회 | 공지")])[0] \
        is None


def test_venues_match_by_their_own_names_with_corroboration():
    venues = [{"venue_id": 1, "region_id": 2, "genre_codes": ["SALSA"], "keys": ["보니따"]},
              {"venue_id": 2, "region_id": 35, "genre_codes": ["TANGO"], "keys": ["데땅고"]},
              {"venue_id": 3, "region_id": 2, "genre_codes": ["SALSA"], "keys": ["동교로191"]}]
    found = cd.match_venues("수요일 보니따 정모, 뒤풀이는 데땅고", 2, ["SALSA"], venues)
    assert found == [(1, cd.VENUE_MATCH, "보니따"), (2, cd.VENUE_CANDIDATE, "데땅고")]
    # A venue sharing a building is not matched unless it is named.
    assert cd.match_venues("홍대 살사 정모", 2, ["SALSA"], venues) == []


def test_confidence_is_a_hint_with_fixed_rules():
    item = {"classification": cd.VERIFIED_NEW, "platform": "DAUM_CAFE", "candidate_name": "살사포유",
            "region_id": 2, "kind": cd.KIND_COMMUNITY, "activity": cd.ACTIVE, "seen_count": 1,
            "providers": ["KAKAO"]}
    assert cd.confidence_for(item, ["SALSA"]) == cd.HIGH
    assert cd.confidence_for({**item, "region_id": None}, ["SALSA"]) == cd.MEDIUM
    assert cd.confidence_for({**item, "classification": cd.UNVERIFIED, "activity": cd.UNVERIFIED,
                              "kind": cd.KIND_UNKNOWN}, []) == cd.LOW


# === 5. PostgreSQL: storing, dedupe, classification, runs =====================================

@pytest.fixture
def six(pg):
    """The six target genres exist (a fresh database seeds only three)."""
    existing = {g["code"] for g in master_data.list_genres(pg)}
    for code in cd.TARGET_GENRES:
        if code not in existing:
            master_data.create_genre(pg, code=code, name=code.title())
    return {g["code"]: g["genre_id"] for g in master_data.list_genres(pg)}


def _items(pg, unique):
    return [i for i in cd.list_items(pg, limit=500)[0] if unique in i["identity_key"]]


@pytest.mark.postgres
def test_the_schema_holds_one_open_run(pg):
    pg.execute("INSERT INTO community_discovery_runs (providers, genre_codes) "
               "VALUES ('{NAVER}', '{SALSA}')")
    with pytest.raises(Exception):
        with pg.transaction():
            pg.execute("INSERT INTO community_discovery_runs (providers, genre_codes) "
                       "VALUES ('{KAKAO}', '{TANGO}')")
    with pytest.raises(Exception):
        with pg.transaction():
            pg.execute("INSERT INTO community_discovery_runs (providers, genre_codes, status) "
                       "VALUES ('{GOOGLE}', '{SALSA}', 'SUCCESS')")


@pytest.mark.postgres
def test_default_queries_are_idempotent_and_a_switched_off_one_stays_off(pg, six):
    cd.ensure_default_queries(pg)
    queries = cd.list_queries(pg)
    assert {q["genre_code"] for q in queries} >= set(cd.TARGET_GENRES)
    first = queries[0]
    cd.set_query_enabled(pg, first["query_id"], False)
    assert cd.ensure_default_queries(pg) == 0
    assert next(q for q in cd.list_queries(pg) if q["query_id"] == first["query_id"])["enabled"] is False
    with pytest.raises(DirectoryError, match="이미 있는 검색어"):
        cd.add_query(pg, genre_id=first["genre_id"], keyword=f"  {first['keyword'].upper()} ")


@pytest.mark.postgres
def test_the_same_group_found_again_is_one_candidate(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    url = f"https://cafe.daum.net/t890{unique}"
    first = [hit(f"{url}/a/1", title="살사 정모", published=date(2026, 9, 1), source_name=f"살사{unique}",
                 query="살사 동호회"),
             hit(f"{url}/b/2", title="바차타 파티", published=date(2026, 9, 5), source_name=f"살사{unique}",
                 query="바차타 모임")]
    assert cd.store_hits(pg, first, ctx, None) == {"new": 1, "updated": 0, "skipped": 0}
    naver = hit(f"{url}/c/3", title="살사 모임", provider=cd.NAVER, kind="web", query="살사 모임")
    assert cd.store_hits(pg, [naver], ctx, None)["updated"] == 1
    [item] = _items(pg, unique)
    assert item["seen_count"] == 2 and item["providers"] == ["KAKAO", "NAVER"]
    assert set(item["queries"]) == {"살사 동호회", "바차타 모임", "살사 모임"}
    assert item["recent_activity_date"] == date(2026, 9, 5)
    assert item["candidate_name"] == f"살사{unique}" and item["community_url"] == url
    assert set(item["genre_codes"]) == {"SALSA", "BACHATA"}


@pytest.mark.postgres
def test_query_genre_is_never_the_candidates_genre(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/sw{unique}/1", title="스윙 린디합 정모",
                           source_name=f"린디{unique}", genre_hint="SALSA", query="살사 동호회")], ctx, None)
    [item] = _items(pg, unique)
    assert item["genre_codes"] == ["SWING"]


@pytest.mark.postgres
def test_same_name_is_a_possible_duplicate_only_when_regions_agree(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    name = f"라틴크루{unique}"
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/a{unique}/1", title="서울 살사 정모", source_name=name,
                           published=date(2026, 9, 1))], ctx, None)
    # 광주, not 부산: a freshly migrated database seeds KR-GWANGJU but not KR-BUSAN.
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/b{unique}/1", title="광주 살사 정모", source_name=name,
                           published=date(2026, 9, 1))], ctx, None)
    cd.store_hits(pg, [hit(f"https://cafe.naver.com/c{unique}/1", title="홍대 살사 정모",
                           source_name=name, provider=cd.NAVER)], ctx, None)
    by_key = {i["identity_key"]: i for i in _items(pg, unique)}
    seoul, busan = by_key[f"daum-cafe:a{unique}"], by_key[f"daum-cafe:b{unique}"]
    twin = by_key[f"naver-cafe:c{unique}"]
    assert seoul["classification"] == cd.VERIFIED_NEW
    assert busan["classification"] == cd.VERIFIED_NEW          # same name, other city: not merged
    # Same name, same city, another platform: flagged, never merged.
    assert (twin["classification"], twin["duplicate_of_item_id"]) == \
        (cd.POSSIBLE_DUPLICATE, seoul["item_id"])
    assert len(by_key) == 3


@pytest.mark.postgres
def test_existing_communities_are_matched_by_url_then_name(pg, unique, six, seoul_id):
    by_url = communities.create_community(pg, {"name": f"URL클럽{unique}",
                                               "homepage_url": f"https://cafe.daum.net/u{unique}",
                                               "region_id": seoul_id})
    by_name = communities.create_community(pg, {"name": f"이름클럽{unique}", "region_id": seoul_id})
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [
        hit(f"https://cafe.daum.net/u{unique}/1", title="살사 정모", source_name="다른 이름"),
        hit(f"https://cafe.daum.net/n{unique}/1", title="서울 살사 정모", source_name=f"이름클럽{unique}",
            published=date(2026, 9, 1)),
    ], ctx, None)
    by_key = {i["identity_key"]: i for i in _items(pg, unique)}
    url_item, name_item = by_key[f"daum-cafe:u{unique}"], by_key[f"daum-cafe:n{unique}"]
    assert (url_item["classification"], url_item["existing_community_id"]) == \
        (cd.VERIFIED_EXISTING, by_url["community_id"])
    assert (name_item["classification"], name_item["existing_community_id"]) == \
        (cd.POSSIBLE_DUPLICATE, by_name["community_id"])


@pytest.mark.postgres
def test_venue_candidates_use_the_venue_id_and_survive_a_rename(pg, unique, six, seoul_id):
    venue = master_data.create_venue(pg, name=f"V890홀{unique}", region_id=seoul_id)
    master_data.add_venue_genre(pg, venue["venue_id"], six["SALSA"])
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/v{unique}/1", source_name=f"크루{unique}",
                           title=f"홍대 V890홀{unique} 살사 정모", published=date(2026, 9, 1))], ctx, None)
    master_data.update_venue(pg, venue["venue_id"], name=f"V890새이름{unique}")
    [item] = _items(pg, unique)
    assert item["venue_ids"] == [venue["venue_id"]] and item["venue_kinds"] == [cd.VENUE_MATCH]
    assert item["venue_names"] == [f"V890새이름{unique}"]


@pytest.mark.postgres
def test_not_a_community_and_stale_and_personal_data(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [
        hit(f"https://cafe.daum.net/bar{unique}/1", source_name=f"홍대 살사바{unique}바", title="소셜"),
        hit(f"https://cafe.daum.net/old{unique}/1", source_name=f"옛모임{unique}", title="살사 정모",
            published=date(2023, 5, 1)),
        hit(f"https://cafe.daum.net/p{unique}/1", source_name=f"개인정보{unique}",
            title="정모 문의 010-9999-8888", snippet="이메일 x@y.example 로 연락", published=date(2026, 9, 1)),
    ], ctx, None)
    by_key = {i["identity_key"]: i for i in _items(pg, unique)}
    assert by_key[f"daum-cafe:bar{unique}"]["classification"] == cd.NOT_A_COMMUNITY
    assert by_key[f"daum-cafe:old{unique}"]["classification"] == cd.STALE
    private = by_key[f"daum-cafe:p{unique}"]
    assert "010-9999-8888" not in private["title"] and "x@y.example" not in private["snippet"]


def _factory(unique):
    def make(name):
        if name == cd.KAKAO:
            return FakeProvider(cd.KAKAO, lambda kind, q: _http_error(401))
        return FakeProvider(cd.NAVER, lambda kind, q: [
            {"url": f"https://cafe.naver.com/run{unique}/{kind}", "title": "살사 정모 2026.09.01",
             "snippet": "홍대 살사 동호회", "source_name": f"런크루{unique}"}] if kind == "cafe" else [])
    return make


@pytest.mark.postgres
def test_a_run_goes_queue_claim_execute_without_touching_communities(pg, unique, six):
    before = len(communities.list_communities(pg))
    run = cd.queue_run(pg, providers=["NAVER", "KAKAO"], genre_codes=["SALSA", "TANGO"],
                       requested_by="tester")
    with pytest.raises(DirectoryError, match="이미 대기 중"):
        cd.queue_run(pg, providers=["NAVER"], genre_codes=["SALSA"])
    assert cd.claim_next_run(pg) == run["run_id"]
    done = cd.execute_run(pg, run["run_id"], provider_factory=_factory(unique), sleep=lambda s: None,
                          today=TODAY)
    assert done["status"] == cd.PARTIAL_SUCCESS
    assert done["provider_status"]["KAKAO"]["status"] == cd.ACCESS_LIMITED
    assert done["provider_status"]["NAVER"]["status"] == cd.CALL_SUCCESS
    assert done["query_count"] == len(cd.DEFAULT_QUERIES["SALSA"]) + len(cd.DEFAULT_QUERIES["TANGO"]) * 1 \
        + len(cd.DEFAULT_QUERIES["SALSA"]) + len(cd.DEFAULT_QUERIES["TANGO"])
    assert done["new_items"] == 1
    assert "Kakao/Daum ACCESS_LIMITED" in (done["error_summary"] or "")
    assert "sk-SECRET123" not in (done["error_summary"] or "") + str(done["provider_status"])
    [item] = _items(pg, unique)
    assert item["classification"] == cd.VERIFIED_NEW and item["last_run_id"] == run["run_id"]
    assert len(communities.list_communities(pg)) == before
    again = cd.queue_run(pg, providers=["NAVER"], genre_codes=["SALSA"])
    cd.claim_next_run(pg)
    second = cd.execute_run(pg, again["run_id"], provider_factory=_factory(unique),
                            sleep=lambda s: None, today=TODAY)
    assert (second["status"], second["new_items"], second["updated_items"]) == (cd.SUCCESS, 0, 1)


@pytest.mark.postgres
@pytest.mark.parametrize("kwargs, message", [
    ({"providers": [], "genre_codes": ["SALSA"]}, "검색 서비스"),
    ({"providers": ["NAVER"], "genre_codes": []}, "장르를 하나 이상"),
    ({"providers": ["NAVER"], "genre_codes": ["WALTZ"]}, "지원하지 않는 장르"),
    ({"providers": ["NAVER"], "genre_codes": ["SALSA"], "region_codes": ["KR-NOWHERE"]}, "지역"),
    ({"providers": ["NAVER"], "genre_codes": ["SALSA"], "extra_keywords": ["a", "b", "c", "d"]},
     "3개까지"),
])
def test_a_bad_run_request_is_refused(pg, six, kwargs, message):
    with pytest.raises(DirectoryError, match=message):
        cd.queue_run(pg, **kwargs)


@pytest.mark.postgres
def test_register_goes_through_the_community_contract_and_marks_the_candidate(pg, unique, six, seoul_id):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/r{unique}/1", source_name=f"등록크루{unique}",
                           title="홍대 살사 정모", published=date(2026, 9, 1))], ctx, None)
    [item] = _items(pg, unique)
    assert f"등록크루{unique}" not in [c["name"] for c in directory.public_communities(pg, None)]
    defaults = cd.registration_defaults(item, six)
    assert defaults["name"] == f"등록크루{unique}" and defaults["genre_ids"] == [six["SALSA"]]
    community = cd.register_item(pg, item["item_id"], {**defaults, "description": "검토 후 등록"},
                                 reviewer="tester")
    after = cd.get_item(pg, item["item_id"])
    assert (after["review_state"], after["registered_community_id"]) == (cd.APPROVED,
                                                                         community["community_id"])
    assert f"등록크루{unique}" in [c["name"] for c in directory.public_communities(pg, None)]
    with pytest.raises(DirectoryError, match="이미"):
        cd.register_item(pg, item["item_id"], defaults, reviewer="tester")
    # Found again later: it is the existing community, not a new candidate.
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/r{unique}/9", source_name=f"등록크루{unique}",
                           title="살사 파티", published=date(2026, 9, 10))],
                  cd.load_context(pg, TODAY), None)
    again = cd.get_item(pg, item["item_id"])
    assert again["classification"] == cd.VERIFIED_EXISTING and again["review_state"] == cd.APPROVED


@pytest.mark.postgres
def test_a_failed_registration_leaves_the_candidate_pending(pg, unique, six):
    communities.create_community(pg, {"name": f"이미있음{unique}"})
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/f{unique}/1", source_name=f"후보{unique}",
                           title="살사 정모")], ctx, None)
    [item] = _items(pg, unique)
    with pytest.raises(DirectoryError, match="같은 이름의 동호회"):
        cd.register_item(pg, item["item_id"], {"name": f"이미있음{unique}"}, reviewer="tester")
    assert cd.get_item(pg, item["item_id"])["review_state"] == cd.PENDING


@pytest.mark.postgres
def test_link_hold_reject_reopen(pg, unique, six):
    target = communities.create_community(pg, {"name": f"연결대상{unique}"})
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/l{unique}/1", source_name=f"연결{unique}",
                           title="살사"),
                       hit(f"https://cafe.daum.net/h{unique}/1", source_name=f"보류{unique}",
                           title="살사")], ctx, None)
    by_key = {i["identity_key"]: i for i in _items(pg, unique)}
    linked, held = by_key[f"daum-cafe:l{unique}"], by_key[f"daum-cafe:h{unique}"]
    with pytest.raises(DirectoryError, match="올바른 ID"):
        cd.link_item(pg, linked["item_id"], "abc")
    with pytest.raises(DirectoryError, match="존재하지 않는"):
        cd.link_item(pg, linked["item_id"], "999999999999")
    cd.link_item(pg, linked["item_id"], str(target["community_id"]), reviewer="tester")
    assert cd.get_item(pg, linked["item_id"])["review_state"] == cd.LINKED
    with pytest.raises(DirectoryError):
        cd.set_review_state(pg, linked["item_id"], cd.REJECTED)
    for state in (cd.HELD, cd.REJECTED, cd.PENDING):
        cd.set_review_state(pg, held["item_id"], state, reviewer="tester")
        assert cd.get_item(pg, held["item_id"])["review_state"] == state


@pytest.mark.postgres
def test_filters(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/fs{unique}/1", source_name=f"필터{unique}",
                           title="홍대 스윙 정모", published=date(2026, 9, 1)),
                       hit(f"https://cafe.naver.com/ft{unique}/1", source_name=f"필터탱고{unique}",
                           title="탱고", provider=cd.NAVER)], ctx, None)

    def keys(**kw):
        return {i["identity_key"] for i in cd.list_items(pg, limit=500, **kw)[0] if unique in i["identity_key"]}

    assert keys(provider=cd.NAVER) == {f"naver-cafe:ft{unique}"}
    assert keys(genre="SWING") == {f"daum-cafe:fs{unique}"}
    assert keys(region="KR-SEOUL") == {f"daum-cafe:fs{unique}"}
    assert keys(classification=cd.VERIFIED_NEW) == {f"daum-cafe:fs{unique}"}
    assert keys(review_state=cd.PENDING) == {f"daum-cafe:fs{unique}", f"naver-cafe:ft{unique}"}
