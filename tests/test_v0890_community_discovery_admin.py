"""v0.89.0 Community Discovery Admin screen and review workflow.

Driven through the real routes over the rolled-back PostgreSQL fixture
connection, so nothing written outlives a test.
"""

from __future__ import annotations

import contextlib
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from runtime import admin, communities, master_data, public
from runtime import community_discovery as cd

BASE = "/admin/community-discovery"
TODAY = date(2026, 9, 12)


@pytest.fixture
def admin_auth(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")
    return ("tester", "test-only")


@pytest.fixture
def six(pg):
    existing = {g["code"] for g in master_data.list_genres(pg)}
    for code in cd.TARGET_GENRES:
        if code not in existing:
            master_data.create_genre(pg, code=code, name=code.title())
    return {g["code"]: g["genre_id"] for g in master_data.list_genres(pg)}


@pytest.fixture
def web(pg, env, monkeypatch, admin_auth, six):
    from runtime import app as app_module, directory_admin, discovery_admin

    @contextlib.contextmanager
    def shared():
        yield pg

    for module in (directory_admin, discovery_admin, public):
        monkeypatch.setattr(module, "_connection", shared)
    monkeypatch.setattr(app_module, "_settings", None)
    client = TestClient(app_module.app, raise_server_exceptions=False)
    client.auth = admin_auth
    return client


def _post(web, path, data):
    return web.post(path, data=data, follow_redirects=False)


def _msg(response):
    return parse_qs(urlsplit(response.headers["location"]).query).get("msg", [""])[0]


def _seed(pg, unique, *specs):
    ctx = cd.load_context(pg, TODAY)
    hits = [cd.Hit(provider=provider, kind="cafe", query="살사 동호회", genre_hint="SALSA",
                   url=url, title=title, snippet="", published=published, source_name=name,
                   source_url=None) for provider, url, name, title, published in specs]
    cd.store_hits(pg, hits, ctx, None)
    return {i["identity_key"]: i for i in cd.list_items(pg, limit=500)[0] if unique in i["identity_key"]}


@pytest.mark.postgres
def test_the_screen_shows_providers_run_form_queries_and_candidates(web, pg, unique, monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "SECRETVALUE-ID-123")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "SECRETVALUE-XYZ-456")
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    _seed(pg, unique, (cd.KAKAO, f"https://cafe.daum.net/s{unique}/1", f"화면크루{unique}",
                       "홍대 살사 바차타 정모", date(2026, 9, 1)))
    page = web.get(BASE)
    assert page.status_code == 200
    html = page.text
    assert '<a href="/admin/community-discovery" class="on">Discovery</a>' in html
    assert "SECRETVALUE" not in html and "missing: KAKAO_REST_API_KEY" in html
    assert 'name="provider"' in html and html.count('name="genres"') == 6
    assert 'name="regions" value="KR-SEOUL"' in html and "동호회 검색</button>" in html
    assert "검색어 설정" in html and "살사 초보 모임" in html
    row = html.split(f'id="candidate-', 1)[1]
    assert f"화면크루{unique}" in html and "등록</a>" in row and "보류" in row and "제외" in row
    assert "f.dataset.sent" in html                                   # the one submit guard


@pytest.mark.postgres
def test_queue_a_run_once(web, pg):
    response = _post(web, BASE + "/runs", {"provider": "ALL", "genres": ["SALSA", "SWING"],
                                           "regions": ["KR-SEOUL"], "keywords": "직장인 살사",
                                           "return_to": "https://evil.example/"})
    assert response.status_code == 303 and response.headers["location"].startswith(BASE + "?")
    assert "대기열에 등록" in _msg(response)
    run = cd.open_run(pg)
    assert (run["providers"], run["genre_codes"], run["region_codes"], run["extra_keywords"]) == \
        (["NAVER", "KAKAO"], ["SALSA", "SWING"], ["KR-SEOUL"], ["직장인 살사"])
    again = _post(web, BASE + "/runs", {"provider": "NAVER", "genres": ["TANGO"]})
    assert "이미 대기 중" in _msg(again)
    none = _post(web, BASE + "/runs", {"provider": "NAVER"})
    assert "장르를 하나 이상" in _msg(none) or "이미 대기 중" in _msg(none)


@pytest.mark.postgres
def test_filters_narrow_the_list(web, pg, unique):
    _seed(pg, unique, (cd.KAKAO, f"https://cafe.daum.net/fa{unique}/1", f"스윙필터{unique}",
                       "홍대 스윙 정모", date(2026, 9, 1)),
          (cd.NAVER, f"https://cafe.naver.com/fb{unique}/1", f"탱고필터{unique}", "탱고", None))
    swing = web.get(BASE + "?genre=SWING").text
    assert f"스윙필터{unique}" in swing and f"탱고필터{unique}" not in swing
    naver = web.get(BASE + "?provider=NAVER").text
    assert f"탱고필터{unique}" in naver and f"스윙필터{unique}" not in naver
    assert f"탱고필터{unique}" not in web.get(BASE + "?classification=VERIFIED_NEW").text
    assert web.get(BASE + "?genre=<script>&state=bogus").status_code == 200   # ignored, not a 500


@pytest.mark.postgres
def test_register_through_the_community_form(web, pg, unique, seoul_id, six):
    venue = master_data.create_venue(pg, name=f"등록홀{unique}", region_id=seoul_id)
    master_data.add_venue_genre(pg, venue["venue_id"], six["SALSA"])
    items = _seed(pg, unique, (cd.KAKAO, f"https://cafe.daum.net/rg{unique}/1", f"등록크루{unique}",
                               f"홍대 등록홀{unique} 살사 정모", date(2026, 9, 1)))
    item = items[f"daum-cafe:rg{unique}"]
    form = web.get(f"{BASE}/items/{item['item_id']}/register")
    assert form.status_code == 200
    assert f'value="등록크루{unique}"' in form.text
    assert f'name="genre_ids" value="{six["SALSA"]}" checked' in form.text
    assert f'name="venue_ids" value="{venue["venue_id"]}" checked' in form.text
    assert f"https://cafe.daum.net/rg{unique}" in form.text
    assert f"등록크루{unique}" not in web.get("/?tab=communities").text      # not public yet
    response = _post(web, f"{BASE}/items/{item['item_id']}/register", {
        "name": f"등록크루{unique}", "description": "검토 완료", "genre_ids": [str(six["SALSA"])],
        "venue_ids": [str(venue["venue_id"])], "homepage_url": f"https://cafe.daum.net/rg{unique}",
        "enabled": "1", "region_id": str(seoul_id), "return_to": BASE})
    assert response.status_code == 303 and "등록됨" in _msg(response)
    registered = cd.get_item(pg, item["item_id"])
    assert registered["review_state"] == cd.APPROVED
    community = communities.get_community(pg, registered["registered_community_id"])
    assert community["venue_ids"] == [venue["venue_id"]] and community["genre_ids"] == [six["SALSA"]]
    assert f"등록크루{unique}" in web.get("/?tab=communities").text           # now public
    assert "이미" in _msg(web.get(f"{BASE}/items/{item['item_id']}/register", follow_redirects=False))
    twice = _post(web, f"{BASE}/items/{item['item_id']}/register", {"name": f"다른{unique}"})
    assert twice.status_code == 400 and "이미" in twice.text


@pytest.mark.postgres
def test_a_failed_registration_shows_the_form_again(web, pg, unique):
    items = _seed(pg, unique, (cd.KAKAO, f"https://cafe.daum.net/bad{unique}/1", f"실패{unique}",
                               "살사", None))
    item = items[f"daum-cafe:bad{unique}"]
    response = _post(web, f"{BASE}/items/{item['item_id']}/register",
                     {"name": "", "description": "keep <b>me</b>"})
    assert response.status_code == 400
    assert "이름: 필수 항목입니다" in response.text and "keep &lt;b&gt;me&lt;/b&gt;" in response.text
    assert cd.get_item(pg, item["item_id"])["review_state"] == cd.PENDING


@pytest.mark.postgres
def test_link_hold_reject_and_bad_requests(web, pg, unique):
    target = communities.create_community(pg, {"name": f"대상{unique}"})
    items = _seed(pg, unique, (cd.KAKAO, f"https://cafe.daum.net/la{unique}/1", f"링크{unique}", "살사", None),
                  (cd.KAKAO, f"https://cafe.daum.net/lb{unique}/1", f"보류{unique}", "살사", None))
    linked, held = items[f"daum-cafe:la{unique}"], items[f"daum-cafe:lb{unique}"]
    bad = _post(web, f"{BASE}/items/{linked['item_id']}/link", {"community_id": "abc"})
    assert "올바른 ID" in _msg(bad)
    ok = _post(web, f"{BASE}/items/{linked['item_id']}/link", {"community_id": str(target["community_id"])})
    assert "연결했습니다" in _msg(ok) and cd.get_item(pg, linked["item_id"])["review_state"] == cd.LINKED
    for action, state in (("hold", cd.HELD), ("reject", cd.REJECTED), ("reopen", cd.PENDING)):
        _post(web, f"{BASE}/items/{held['item_id']}/{action}", {"return_to": "//evil.example"})
        assert cd.get_item(pg, held["item_id"])["review_state"] == state
    assert _post(web, f"{BASE}/items/{held['item_id']}/explode", {}).status_code == 400
    assert _post(web, f"{BASE}/items/abc/hold", {}).status_code == 404
    assert web.get(f"{BASE}/items/0/register").status_code == 404
    assert web.get(f"{BASE}/items/999999999999/register").status_code == 404
    response = _post(web, f"{BASE}/items/{held['item_id']}/hold", {"return_to": "https://evil.example"})
    assert response.headers["location"].startswith(BASE)


@pytest.mark.postgres
def test_query_settings(web, pg, six):
    response = _post(web, BASE + "/queries", {"genre_id": str(six["SALSA"]), "keyword": "홍대 살사 크루",
                                              "provider_scope": "KAKAO"})
    assert "추가됨" in _msg(response)
    added = next(q for q in cd.list_queries(pg) if q["keyword"] == "홍대 살사 크루")
    assert added["provider_scope"] == "KAKAO"
    _post(web, f"{BASE}/queries/{added['query_id']}/enabled", {"enabled": "0"})
    assert next(q for q in cd.list_queries(pg) if q["query_id"] == added["query_id"])["enabled"] is False
    assert "추가하지 못했습니다" in _msg(_post(web, BASE + "/queries", {"genre_id": "abc", "keyword": "x"}))


@pytest.mark.postgres
@pytest.mark.parametrize("method, path", [("get", BASE), ("post", BASE + "/runs")])
def test_the_screen_needs_the_admin_login(web, method, path):
    web.auth = None
    assert getattr(web, method)(path).status_code == 401


def test_the_admin_nav_lists_discovery_after_notices():
    hrefs = [href for href, _ in admin.NAV]
    assert hrefs.index("/admin/community-discovery") == hrefs.index("/admin/notices") + 1
