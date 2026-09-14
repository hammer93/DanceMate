"""v0.89.1 Community Discovery Reliability Patch: Admin screen.

Covers the four Admin-facing fixes from the two Production reviews: activity
provenance made visible, a duplicate candidate never hidden behind a weaker
one, classification reasons shown instead of guessed at, and a review queue
that filters/sorts by evidence quality rather than item_id. Driven through
the real routes over the rolled-back PostgreSQL fixture connection, exactly
like tests/test_v0890_community_discovery_admin.py.
"""

from __future__ import annotations

import contextlib
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from runtime import master_data, public
from runtime import community_discovery as cd

BASE = "/admin/community-discovery"
TODAY = date(2026, 9, 14)


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
def test_a_stronger_duplicate_is_shown_next_to_the_weaker_anchor_not_hidden(web, pg, unique):
    name = f"보이는스윙{unique}"
    items = _seed(pg, unique,
                  (cd.KAKAO, f"https://cafe.daum.net/dw{unique}/1", name, "스윙", None),
                  (cd.KAKAO, f"https://cafe.daum.net/ds{unique}/1", name, "9월 정모", date(2026, 9, 1)))
    weak, strong = items[f"daum-cafe:dw{unique}"], items[f"daum-cafe:ds{unique}"]
    assert strong["classification"] == cd.POSSIBLE_DUPLICATE
    html = web.get(BASE).text
    # Both candidates are on the page, and the weaker anchor's row links
    # forward to the stronger one instead of the stronger one being invisible.
    assert f'id="candidate-{weak["item_id"]}"' in html
    assert f'id="candidate-{strong["item_id"]}"' in html
    weak_row = html.split(f'id="candidate-{weak["item_id"]}"', 1)[1].split("</tr>", 1)[0]
    assert f"#{strong['item_id']}" in weak_row and "중복 그룹" in weak_row
    assert "(추천)" in weak_row                                    # the stronger one is the hint


@pytest.mark.postgres
def test_activity_provenance_and_classification_reasons_are_visible(web, pg, unique):
    items = _seed(pg, unique, (cd.KAKAO, f"https://cafe.daum.net/pr{unique}/1", f"근거표시{unique}",
                               "2024년 8월 정모 후기", TODAY))
    [item] = items.values()
    assert item["activity_date"] == date(2024, 8, 1)
    html = web.get(BASE).text
    row = html.split(f'id="candidate-{item["item_id"]}"', 1)[1].split("</tr>", 1)[0]
    assert "2024-08-01" in row
    assert "추정" in row and "확인됨" not in row                     # INFERRED, never silently "확인됨"
    assert "activity:" in row or "latest" in row                    # the reason itself, not just a verdict


@pytest.mark.postgres
def test_confirming_evidence_through_the_form(web, pg, unique):
    items = _seed(pg, unique, (cd.KAKAO, f"https://cafe.daum.net/ce{unique}/1", f"확인폼{unique}",
                               "9월 정모 사진", TODAY))
    [item] = items.values()
    assert item["activity_date_confidence"] == cd.INFERRED
    response = _post(web, f"{BASE}/items/{item['item_id']}/confirm-evidence", {
        "activity_date": "2024-08-26", "evidence_url": "https://cafe.daum.net/ce/notice/1",
        "evidence_title": "2024년 8월 정모 공지", "return_to": BASE})
    assert response.status_code == 303 and "확인했습니다" in _msg(response)
    after = cd.get_item(pg, item["item_id"])
    assert after["activity_date"] == date(2024, 8, 26)
    assert after["activity_date_confidence"] == cd.CONFIRMED
    assert after["classification"] == cd.STALE
    html = web.get(BASE).text
    row = html.split(f'id="candidate-{item["item_id"]}"', 1)[1].split("</tr>", 1)[0]
    assert "확인됨" in row

    bad = _post(web, f"{BASE}/items/{item['item_id']}/confirm-evidence", {"activity_date": "not-a-date"})
    assert "올바른 날짜가 아닙니다" in _msg(bad)


@pytest.mark.postgres
def test_marking_two_candidates_as_separate_communities(web, pg, unique):
    name = f"별개{unique}"
    items = _seed(pg, unique,
                  (cd.KAKAO, f"https://cafe.daum.net/sa{unique}/1", name, "살사", None),
                  (cd.KAKAO, f"https://cafe.daum.net/sb{unique}/1", name, "9월 정모", date(2026, 9, 1)))
    weak, strong = items[f"daum-cafe:sa{unique}"], items[f"daum-cafe:sb{unique}"]
    assert strong["classification"] == cd.POSSIBLE_DUPLICATE
    row = web.get(BASE).text.split(f'id="candidate-{strong["item_id"]}"', 1)[1].split("</tr>", 1)[0]
    assert "서로 다른 Community" in row

    response = _post(web, f"{BASE}/items/{strong['item_id']}/separate", {"return_to": BASE})
    assert response.status_code == 303 and "서로 다른 Community" in _msg(response)
    after = cd.get_item(pg, strong["item_id"])
    assert after["duplicate_cleared"] is True
    assert after["classification"] != cd.POSSIBLE_DUPLICATE
    assert cd.duplicate_group(pg, weak["item_id"]) == []


@pytest.mark.postgres
def test_review_queue_and_region_unresolved_filters(web, pg, unique):
    items = _seed(pg, unique,
                  (cd.KAKAO, f"https://cafe.daum.net/rq{unique}/1", f"큐지역없음{unique}", "살사", None),
                  (cd.KAKAO, f"https://cafe.daum.net/rs{unique}/1", f"큐스테일{unique}",
                   "서울 정모 안내", date(2024, 1, 1)))
    no_region = items[f"daum-cafe:rq{unique}"]
    stale = items[f"daum-cafe:rs{unique}"]
    assert no_region["region_id"] is None
    assert stale["region_id"] is not None
    assert stale["classification"] == cd.STALE

    unresolved_html = web.get(f"{BASE}?region=UNRESOLVED").text
    assert f"큐지역없음{unique}" in unresolved_html
    assert f"큐스테일{unique}" not in unresolved_html

    stale_html = web.get(f"{BASE}?queue=stale").text
    assert f"큐스테일{unique}" in stale_html
    assert f"큐지역없음{unique}" not in stale_html

    # needs_review sorts a large shared candidate table by evidence quality,
    # so a freshly seeded PENDING row is not guaranteed to land on page one -
    # the filter's own correctness (not pagination) is already covered
    # directly against cd.list_items() in test_v0891_discovery_reliability.py.
    assert web.get(f"{BASE}?queue=needs_review").status_code == 200
    assert web.get(f"{BASE}?queue=bogus").status_code == 200      # ignored, not a 500


@pytest.mark.postgres
def test_registering_a_representative_links_the_rest_of_the_group(web, pg, unique, seoul_id, six):
    name = f"그룹등록{unique}"
    items = _seed(pg, unique,
                  (cd.KAKAO, f"https://cafe.daum.net/gw{unique}/1", name, "스윙", None),
                  (cd.KAKAO, f"https://cafe.daum.net/gs{unique}/1", name, "9월 정모", date(2026, 9, 1)))
    weak, strong = items[f"daum-cafe:gw{unique}"], items[f"daum-cafe:gs{unique}"]
    form = web.get(f"{BASE}/items/{strong['item_id']}/register")
    assert form.status_code == 200
    assert f'name="sibling_ids" value="{weak["item_id"]}"' in form.text
    assert "같은 Community로 함께 연결" in form.text

    response = _post(web, f"{BASE}/items/{strong['item_id']}/register", {
        "name": name, "region_id": str(seoul_id), "genre_ids": [str(six["SWING"])],
        "enabled": "1", "sibling_ids": [str(weak["item_id"])], "return_to": BASE})
    assert response.status_code == 303 and "등록됨" in _msg(response)
    strong_after = cd.get_item(pg, strong["item_id"])
    weak_after = cd.get_item(pg, weak["item_id"])
    assert strong_after["review_state"] == cd.APPROVED
    assert weak_after["review_state"] == cd.LINKED
    assert weak_after["registered_community_id"] == strong_after["registered_community_id"]


@pytest.mark.postgres
def test_new_evidence_is_flagged_without_changing_the_held_state(web, pg, unique):
    items = _seed(pg, unique, (cd.KAKAO, f"https://cafe.daum.net/ne{unique}/1", f"새근거{unique}",
                               "살사", None))
    [item] = items.values()
    _post(web, f"{BASE}/items/{item['item_id']}/hold", {"return_to": BASE})
    pg.execute("UPDATE community_discovery_items SET reviewed_at = now() - interval '1 day' "
              "WHERE item_id = %s", (item["item_id"],))
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [cd.Hit(provider=cd.KAKAO, kind="cafe", query="살사 동호회", genre_hint="SALSA",
                              url=f"https://cafe.daum.net/ne{unique}/1", title="10월 정모 공지",
                              snippet="", published=date(2026, 10, 1), source_name=f"새근거{unique}",
                              source_url=None)], ctx, None)
    assert cd.get_item(pg, item["item_id"])["review_state"] == cd.HELD
    html = web.get(f"{BASE}?queue=new_evidence").text
    assert f"새근거{unique}" in html and "새 근거 발견" in html
