"""v0.88.0 Communities and the Notice board: data rules and the Admin screens.

Communities are canonical master data (region, genres and venues many-to-many)
created only by an operator. Every change is audited in master_data_actions;
a community is disabled before it can be deleted, and a delete takes only its
own links with it. Notices live on the NOTICE board (migration 035), are
scoped to genres (none = a global notice) and are plain text.

The Admin tests drive the real routes over the rolled-back PostgreSQL fixture
connection, so nothing they write outlives the test.
"""

from __future__ import annotations

import contextlib
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from runtime import (
    admin, boards, communities, directory, master_data, master_edit, public, venue_resolution,
)
from runtime.directory import DirectoryError


def _actions(pg, entity_type, entity_id):
    with pg.cursor() as cur:
        cur.execute("SELECT action FROM master_data_actions WHERE entity_type = %s "
                    "AND entity_id = %s ORDER BY master_action_id", (entity_type, entity_id))
        return [r[0] for r in cur.fetchall()]


@pytest.fixture
def genre(pg, unique):
    return master_data.create_genre(pg, code=f"G88{unique}"[:16].upper(), name=f"G88 {unique}")


# === 1. Schema ===================================================================

@pytest.mark.postgres
def test_the_notice_board_is_seeded_and_ready_for_more(pg):
    board = boards.get_board(pg, boards.NOTICE)
    assert (board["name"], board["board_type"], board["write_access"], board["enabled"]) == \
        ("공지사항", "NOTICE", "ADMIN", True)
    with pg.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'board_posts'")
        columns = {r[0] for r in cur.fetchall()}
    assert {"board_id", "author_kind", "author_user_id", "status", "pinned",
            "published_at"} <= columns


# === 2. Communities ================================================================

@pytest.mark.postgres
def test_a_community_links_genres_and_venues_and_is_audited(pg, unique, genre, seoul_id):
    venue = master_data.create_venue(pg, name=f"C88 venue {unique}")
    created = communities.create_community(pg, {
        "name": f"  C88  Club {unique} ", "region_id": str(seoul_id),
        "genre_ids": [str(genre["genre_id"])], "venue_ids": [str(venue["venue_id"])] * 2,
        "description": "금요일\r\n초보 환영", "homepage_url": "https://club.example/"})
    assert created["name"] == f"C88 Club {unique}"           # whitespace collapsed
    assert created["genre_ids"] == [genre["genre_id"]]
    assert created["venue_ids"] == [venue["venue_id"]]       # a duplicate id is one link
    assert created["description"] == "금요일\n초보 환영"
    cid = created["community_id"]
    result = communities.update_community(pg, cid, {**communities.snapshot(created),
                                                     "genre_ids": [], "notes": "메모"})
    assert result["changed"] == ["notes", "genre_ids"]
    assert communities.update_community(pg, cid, communities.snapshot(result["community"]))[
        "changed"] == []
    assert _actions(pg, "COMMUNITY", cid) == ["CREATE", "EDIT"]


@pytest.mark.postgres
@pytest.mark.parametrize("fields, message", [
    ({"name": "   "}, "이름: 필수 항목입니다"),
    ({"name": "x" * 121}, "이름: 120자 이하"),
    ({"name": "ok", "homepage_url": "javascript:alert(1)"}, "http:// 또는 https://"),
    ({"name": "ok", "homepage_url": "https://a.example/?token=SECRET"}, "계정 정보나 키"),
    ({"name": "ok", "homepage_url": "https://a.example/ x"}, "공백"),
    ({"name": "ok", "genre_ids": ["abc"]}, "장르: 올바른 ID가 아닙니다"),
    ({"name": "ok", "genre_ids": ["-1"]}, "장르: 올바른 ID가 아닙니다"),
    ({"name": "ok", "venue_ids": ["999999999999"]}, "장소: 존재하지 않는 항목"),
    ({"name": "ok", "region_id": "1 OR 1=1"}, "지역: 올바른 ID가 아닙니다"),
    ({"name": "ok", "region_id": "999999999999"}, "지역: 존재하지 않는 항목"),
])
def test_bad_community_input_is_refused_with_a_sentence(pg, fields, message):
    with pytest.raises(DirectoryError, match=message):
        communities.create_community(pg, fields)


@pytest.mark.postgres
def test_community_names_are_unique_whatever_the_case(pg, unique):
    communities.create_community(pg, {"name": f"Tango Club {unique}"})
    with pytest.raises(DirectoryError, match="같은 이름의 동호회"):
        communities.create_community(pg, {"name": f"  TANGO club {unique} "})


@pytest.mark.postgres
def test_delete_is_two_steps_and_takes_only_the_links(pg, unique, genre):
    venue = master_data.create_venue(pg, name=f"C88 keep {unique}")
    cid = communities.create_community(pg, {
        "name": f"C88 Gone {unique}", "genre_ids": [genre["genre_id"]],
        "venue_ids": [venue["venue_id"]]})["community_id"]
    with pytest.raises(DirectoryError, match="먼저 비활성화"):
        communities.delete_community(pg, cid)
    assert communities.set_community_enabled(pg, cid, False)["changed"] is True
    assert communities.set_community_enabled(pg, cid, False)["changed"] is False
    communities.delete_community(pg, cid)
    assert communities.get_community(pg, cid) is None
    assert master_data.get_venue(pg, venue["venue_id"]) is not None
    assert master_data.get_genre(pg, genre["genre_id"]) is not None
    assert _actions(pg, "COMMUNITY", cid) == ["CREATE", "DISABLE", "DELETE"]


@pytest.mark.postgres
def test_a_genre_used_by_a_community_or_notice_cannot_be_deleted(pg, unique, genre):
    communities.create_community(pg, {"name": f"C88 uses {unique}",
                                      "genre_ids": [genre["genre_id"]]})
    boards.create_post(pg, {"title": f"N88 uses {unique}", "genre_ids": [genre["genre_id"]]})
    usage = master_data.genre_usage(pg, genre["genre_id"])
    assert (usage["communities"], usage["notices"]) == (1, 1)
    with pytest.raises(master_edit.EditError, match="Community 1건, Notice 1건"):
        master_edit.delete_genre(pg, genre["genre_id"])


@pytest.mark.postgres
def test_a_region_used_by_a_community_cannot_be_deleted(pg, unique):
    region = master_data.create_region(pg, code=f"R88-{unique}"[:20].upper(),
                                       country="South Korea", name=f"R88 {unique}")
    communities.create_community(pg, {"name": f"C88 region {unique}",
                                      "region_id": region["region_id"]})
    assert master_data.region_usage(pg, region["region_id"])["communities"] == 1
    with pytest.raises(master_edit.EditError, match="Community 1건"):
        master_edit.delete_region(pg, region["region_id"])


@pytest.mark.postgres
def test_renaming_a_venue_keeps_every_community_link(pg, unique):
    """The link is the venue's id, never its name."""
    a = master_data.create_venue(pg, name=f"C88 old name {unique}")
    b = master_data.create_venue(pg, name=f"C88 second {unique}")
    cid = communities.create_community(pg, {
        "name": f"C88 renamed {unique}", "venue_ids": [a["venue_id"], b["venue_id"]]})["community_id"]
    master_data.update_venue(pg, a["venue_id"], name=f"C88 new name {unique}")
    assert communities.get_community(pg, cid)["venue_ids"] == sorted([a["venue_id"], b["venue_id"]])
    row = next(r for r in directory.public_communities(pg, None) if r["community_id"] == cid)
    assert row["venue_names"] == [f"C88 new name {unique}", f"C88 second {unique}"]


@pytest.mark.postgres
def test_a_community_with_no_venue_or_genre_is_still_listed(pg, unique):
    cid = communities.create_community(pg, {"name": f"C88 alone {unique}"})["community_id"]
    row = next(r for r in directory.public_communities(pg, None) if r["community_id"] == cid)
    assert (row["venue_names"], row["genre_codes"]) == ([], [])


@pytest.mark.postgres
def test_deleting_a_venue_only_unlinks_it_from_its_communities(pg, unique):
    venue = master_data.create_venue(pg, name=f"C88 doomed {unique}")
    cid = communities.create_community(pg, {"name": f"C88 stays {unique}",
                                            "venue_ids": [venue["venue_id"]]})["community_id"]
    venue_resolution.delete_venue(pg, venue["venue_id"])
    assert communities.get_community(pg, cid)["venue_ids"] == []


# === 3. Notices ======================================================================

@pytest.mark.postgres
def test_a_notice_gets_its_date_when_first_published_and_keeps_it(pg, unique, genre):
    draft = boards.create_post(pg, {"title": f"N88 d {unique}", "status": "DRAFT",
                                    "genre_ids": [genre["genre_id"]]})
    assert draft["published_at"] is None and draft["genre_ids"] == [genre["genre_id"]]
    fields = boards.snapshot(draft)
    first = boards.update_post(pg, draft["post_id"], {**fields, "status": "PUBLISHED"})["post"]
    assert first["published_at"] is not None
    again = boards.update_post(pg, draft["post_id"],
                               {**boards.snapshot(first), "status": "HIDDEN"})["post"]
    again = boards.update_post(pg, draft["post_id"],
                               {**boards.snapshot(again), "status": "PUBLISHED"})["post"]
    assert again["published_at"] == first["published_at"]
    assert _actions(pg, "BOARD_POST", draft["post_id"]) == ["CREATE", "EDIT", "EDIT", "EDIT"]


@pytest.mark.postgres
def test_the_same_notice_sent_twice_is_saved_once(pg, unique):
    fields = {"title": f"N88 twice {unique}", "body": "같은 본문"}
    first = boards.create_post(pg, fields)
    with pytest.raises(boards.DuplicatePost) as caught:
        boards.create_post(pg, fields)
    assert caught.value.post_id == first["post_id"]
    boards.create_post(pg, {**fields, "body": "다른 본문"})       # a different notice is fine


@pytest.mark.postgres
@pytest.mark.parametrize("fields, message", [
    ({"title": ""}, "제목: 필수 항목입니다"),
    ({"title": "t", "status": "LIVE"}, "상태:"),
    ({"title": "t", "body": "x" * (boards.BODY_MAX + 1)}, "본문:"),
    ({"title": "t", "genre_ids": ["1;DROP TABLE"]}, "장르: 올바른 ID가 아닙니다"),
    ({"title": "t", "genre_ids": ["999999999999"]}, "장르: 존재하지 않는 항목"),
])
def test_bad_notice_input_is_refused(pg, fields, message):
    with pytest.raises(DirectoryError, match=message):
        boards.create_post(pg, fields)


@pytest.mark.postgres
def test_control_characters_are_dropped_and_the_body_is_audited_by_length(pg, unique):
    post = boards.create_post(pg, {"title": f"N88\x00 ctl {unique}", "body": "a\x00b\x07c"})
    assert post["title"] == f"N88 ctl {unique}" and post["body"] == "abc"
    with pg.cursor() as cur:
        cur.execute("SELECT after_json FROM master_data_actions WHERE entity_type = "
                    "'BOARD_POST' AND entity_id = %s", (post["post_id"],))
        after = cur.fetchone()[0]
    assert after["body_chars"] == 3 and "body" not in after
    boards.delete_post(pg, post["post_id"])
    assert boards.get_post(pg, post["post_id"]) is None


# === 4. Admin screens =================================================================

@pytest.fixture
def admin_auth(monkeypatch) -> tuple[str, str]:
    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")
    return ("tester", "test-only")


@pytest.fixture
def web(pg, env, monkeypatch, admin_auth):
    """The real app, every page reading and writing through the test's own
    rolled-back connection."""
    from runtime import app as app_module, directory_admin

    @contextlib.contextmanager
    def shared():
        yield pg

    monkeypatch.setattr(directory_admin, "_connection", shared)
    monkeypatch.setattr(public, "_connection", shared)
    monkeypatch.setattr(app_module, "_settings", None)
    client = TestClient(app_module.app, raise_server_exceptions=False)
    client.auth = admin_auth
    return client


def _post(web, path, data):
    return web.post(path, data=data, follow_redirects=False)


def _location(response):
    parts = urlsplit(response.headers["location"])
    return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}, parts.fragment


def _community_id(pg, name):
    return next(c["community_id"] for c in communities.list_communities(pg) if c["name"] == name)


@pytest.mark.postgres
def test_the_console_lists_both_new_screens(web):
    page = web.get("/admin/communities").text
    assert '<a href="/admin/communities" class="on">Communities</a>' in page
    assert '<a href="/admin/notices" class="">Notices</a>' in page
    assert "f.dataset.sent" in page                          # the console's one submit guard
    assert web.get("/admin/notices").status_code == 200


@pytest.mark.postgres
@pytest.mark.parametrize("path", ["/admin/communities", "/admin/notices"])
def test_both_screens_need_the_admin_login(web, path):
    web.auth = None
    assert web.get(path).status_code == 401
    assert _post(web, path, {"name": "x", "title": "x"}).status_code == 401


@pytest.mark.postgres
def test_add_edit_disable_delete_a_community(web, pg, unique, genre):
    name = f"C88 web {unique}"
    response = _post(web, "/admin/communities", {
        "name": name, "genre_ids": [str(genre["genre_id"])], "enabled": "1",
        "return_to": "/admin/communities?page=1"})
    assert response.status_code == 303
    path, query, fragment = _location(response)
    cid = _community_id(pg, name)
    assert (path, query["page"], fragment) == ("/admin/communities", "1", f"community-{cid}")
    assert query["msg"] == f"동호회 '{name}' 추가됨"

    edit = web.get(f"/admin/communities/{cid}/edit?return_to=/admin/communities?page=1")
    assert edit.status_code == 200 and f'value="{name}"' in edit.text
    response = _post(web, f"/admin/communities/{cid}/edit", {
        "name": name, "description": "새 소개", "genre_ids": [str(genre["genre_id"])],
        "enabled": "1", "return_to": "/admin/communities?page=1"})
    assert "저장됨 (description)" in _location(response)[1]["msg"]
    assert "새 소개" in web.get(f"/?tab=communities").text

    response = _post(web, f"/admin/communities/{cid}/delete", {})
    assert "먼저 비활성화" in _location(response)[1]["msg"]
    _post(web, f"/admin/communities/{cid}/enabled", {"enabled": "0"})
    assert name not in web.get("/?tab=communities").text      # off the public page at once
    response = _post(web, f"/admin/communities/{cid}/delete", {})
    assert _location(response)[1]["msg"] == f"동호회 '{name}' 삭제됨"
    assert communities.get_community(pg, cid) is None


@pytest.mark.postgres
@pytest.mark.parametrize("return_to", [
    "https://evil.example/x", "//evil.example/x", "/\\evil.example", "javascript:alert(1)",
    "/admin/notices", "/admin/communitiesX", "/events",
])
def test_a_save_never_redirects_anywhere_but_its_own_list(web, unique, return_to):
    response = _post(web, "/admin/communities", {"name": f"C88 r {unique}",
                                                 "return_to": return_to})
    assert response.status_code == 303
    assert _location(response)[0] == "/admin/communities"
    assert response.headers["location"].startswith("/admin/communities?")


@pytest.mark.postgres
def test_a_failed_save_shows_the_form_again_with_what_was_typed(web):
    response = _post(web, "/admin/communities", {
        "name": "", "description": "keep me <b>", "genre_ids": ["abc"]})
    assert response.status_code == 400
    assert "이름: 필수 항목입니다" in response.text
    assert "keep me &lt;b&gt;" in response.text and "keep me <b>" not in response.text
    assert "<details open><summary>동호회 추가</summary>" in response.text


@pytest.mark.postgres
def test_malformed_or_missing_ids_are_404_or_a_message_never_a_500(web):
    assert web.get("/admin/communities/abc/edit").status_code == 404
    assert web.get("/admin/communities/0/edit").status_code == 404
    assert web.get("/admin/communities/999999999999/edit").status_code == 404
    assert _post(web, "/admin/communities/abc/delete", {}).status_code == 404
    assert _post(web, "/admin/notices/1e3/edit", {"title": "x"}).status_code == 404
    response = _post(web, "/admin/communities/999999999999/edit", {"name": "x"})
    assert "찾을 수 없습니다" in _location(response)[1]["msg"]
    response = _post(web, "/admin/notices/999999999999/delete", {})
    assert _location(response)[1]["tone"] == "bad"


@pytest.mark.postgres
def test_names_are_escaped_on_the_admin_list(web, unique):
    _post(web, "/admin/communities", {"name": f"<img src=x onerror=alert(1)> {unique}"})
    page = web.get("/admin/communities").text
    assert "<img src=x onerror" not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


@pytest.mark.postgres
def test_notices_from_the_console_to_the_public_page(web, pg, unique, genre):
    _post(web, "/admin/notices", {"title": f"N88 all {unique}", "body": "모두에게 <b>"})
    _post(web, "/admin/notices", {"title": f"N88 scoped {unique}", "body": "b",
                                  "genre_ids": [str(genre["genre_id"])]})
    _post(web, "/admin/notices", {"title": f"N88 draft {unique}", "status": "DRAFT"})
    posts = {p["title"]: p for p in boards.list_posts(pg) if unique in p["title"]}
    assert set(posts) == {f"N88 all {unique}", f"N88 scoped {unique}", f"N88 draft {unique}"}

    board = web.get("/?tab=notices").text
    assert f"N88 all {unique}" in board and f"N88 scoped {unique}" in board
    assert f"N88 draft {unique}" not in board

    detail = web.get(f"/notices/{posts[f'N88 all {unique}']['post_id']}")
    assert detail.status_code == 200 and "모두에게 &lt;b&gt;" in detail.text
    assert web.get(f"/notices/{posts[f'N88 draft {unique}']['post_id']}").status_code == 404
    admin_page = web.get("/admin/notices").text

    def row(title):
        return admin_page.split(f'id="notice-{posts[title]["post_id"]}"', 1)[1].split("</tr>", 1)[0]

    assert "공개 보기" in row(f"N88 all {unique}")           # published: a link to its page
    assert "공개 보기" not in row(f"N88 draft {unique}")      # a draft has no public page
    assert genre["name"] in row(f"N88 scoped {unique}")
    assert "전체 공지" in row(f"N88 all {unique}")


@pytest.mark.postgres
def test_a_double_submitted_notice_is_saved_once(web, pg, unique):
    data = {"title": f"N88 dbl {unique}", "body": "한 번만"}
    assert _post(web, "/admin/notices", data).status_code == 303
    second = _post(web, "/admin/notices", data)
    assert "방금 등록" in _location(second)[1]["msg"]
    assert [p["title"] for p in boards.list_posts(pg)].count(f"N88 dbl {unique}") == 1


@pytest.mark.postgres
def test_notice_edit_and_delete(web, pg, unique):
    _post(web, "/admin/notices", {"title": f"N88 e {unique}", "body": "처음"})
    pid = next(p["post_id"] for p in boards.list_posts(pg) if p["title"] == f"N88 e {unique}")
    page = web.get(f"/admin/notices/{pid}/edit")
    assert page.status_code == 200 and ">처음</textarea>" in page.text
    response = _post(web, f"/admin/notices/{pid}/edit", {
        "title": f"N88 e {unique}", "body": "고침", "status": "PUBLISHED", "pinned": "1"})
    assert "저장됨 (body, pinned)" in _location(response)[1]["msg"]
    bad = _post(web, f"/admin/notices/{pid}/edit", {"title": "", "body": "지워지면 안 됨"})
    assert bad.status_code == 400 and "지워지면 안 됨" in bad.text
    response = _post(web, f"/admin/notices/{pid}/delete", {"return_to": "/admin/notices"})
    assert _location(response)[1]["msg"] == f"공지 'N88 e {unique}' 삭제됨"
    assert boards.get_post(pg, pid) is None


def test_the_admin_nav_carries_the_new_screens():
    hrefs = [href for href, _ in admin.NAV]
    assert hrefs.index("/admin/communities") == hrefs.index("/admin/organizers") + 1
    assert hrefs.index("/admin/notices") == hrefs.index("/admin/communities") + 1


def test_directory_module_never_imports_the_board_module_at_import_time():
    """boards imports directory's input rules; directory reads boards' status
    lazily, so neither import can ever be circular."""
    import inspect

    top = inspect.getsource(directory).split("def ", 1)[0]
    assert "boards" not in top
