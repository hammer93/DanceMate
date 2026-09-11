"""Admin screens for the v0.88.0 directory: Communities and Notices.

Both follow the console's existing rules rather than inventing new ones: every
page is ``admin._page()`` (so the one submit guard, ``SUBMIT_ONCE``, covers
every form here), every value is escaped, a return address is only ever this
screen's own list (``_return_to()``), and a save that fails shows the form
again with what the operator typed and the reason - it never loses their input
and never answers with a stack trace.

A community or notice has more fields than a table row can edit comfortably (a
many-venue multi-select, a long body), so each opens its own edit page rather
than the inline row editor, and returns to the exact list view it came from.
"""

from __future__ import annotations

import html
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import admin, boards, communities, events_api, master_admin, master_data
from .admin_auth import require_admin
from .directory import DirectoryError, public_link

router = APIRouter()

E = html.escape

COMMUNITIES_PAGE = "/admin/communities"
NOTICES_PAGE = "/admin/notices"

_CSS = (
    "<style>.chipset.scroll{max-height:15rem;overflow:auto;padding:6px;"
    "border:1px solid var(--line);border-radius:8px}"
    ".chipset .off{color:var(--muted)}.clip{max-width:24rem;overflow-wrap:anywhere}"
    ".formgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));"
    "gap:10px}.field{margin-top:10px}</style>"
)


def _connection():
    return admin._connection()


# --- small shared rules -------------------------------------------------------

def _path_id(raw: str) -> int:
    """A row id from the path. Anything but a positive whole number is a 404,
    not a validation error page and not a 500."""
    text = (raw or "").strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 18 or int(text) == 0:
        raise HTTPException(status_code=404, detail="not found")
    return int(text)


def _return_to(raw: str | None, base: str) -> str:
    """Only this screen's own list, with its query - nothing absolute, nothing
    protocol-relative, nothing elsewhere on the site or in the console."""
    view = master_admin.safe_view(raw, base)
    if urlsplit(view).path != base:
        return base
    return view


def _go(raw_return_to: str | None, base: str, message: str, tone: str = "ok", *,
        anchor: str = "") -> RedirectResponse:
    view = _return_to(raw_return_to, base)
    target = master_admin._rebuilt(view, drop=("msg", "tone"),
                                   add=[("msg", message), ("tone", tone)], anchor=anchor)
    return RedirectResponse(target, status_code=303)


def _page(title: str, current: str, body: str, flash: tuple[str, str] | None, *,
          status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(admin._page(title, current, _CSS + body, flash=flash),
                        status_code=status_code)


def _text(form, key: str) -> str:
    value = form.get(key)
    return value if isinstance(value, str) else ""


def _list(form, key: str) -> list[str]:
    return [v for v in form.getlist(key) if isinstance(v, str)]


def _lenient_ids(values: Any) -> set[int]:
    """The ids a re-shown form should keep ticked - garbage simply unticked."""
    if values is None:
        return set()
    if isinstance(values, (str, int)):
        values = [values]
    return {int(v) for v in (str(x).strip() for x in values)
            if v.isascii() and v.isdigit() and 0 < len(v) <= 18}


def _when(value) -> str:
    if not value:
        return "-"
    return value.astimezone(events_api.SEOUL).strftime("%Y-%m-%d %H:%M")


def _genre_chips(genres: list[dict[str, Any]], selected: set[int], *,
                 form_id: str | None = None) -> str:
    bound = f' form="{E(form_id)}"' if form_id else ""
    return '<div class="chipset">' + "".join(
        f'<label class="chip"><input type="checkbox" name="genre_ids" '
        f'value="{g["genre_id"]}"{bound}{" checked" if g["genre_id"] in selected else ""}> '
        f'{E(g["name"])}{"" if g["enabled"] else " <span class=off>(비활성)</span>"}</label>'
        for g in genres) + "</div>"


def _select(name: str, choices: list[tuple[str, str]], chosen: str) -> str:
    return (f'<select name="{E(name)}">' + "".join(
        f'<option value="{E(value)}"{" selected" if value == chosen else ""}>{E(label)}</option>'
        for value, label in choices) + "</select>")


# === Communities ================================================================

def _community_values(form) -> dict[str, Any]:
    return {
        "name": _text(form, "name"), "region_id": _text(form, "region_id"),
        "description": _text(form, "description"),
        "homepage_url": _text(form, "homepage_url"), "notes": _text(form, "notes"),
        "enabled": _text(form, "enabled") or "1",
        "genre_ids": _list(form, "genre_ids"), "venue_ids": _list(form, "venue_ids"),
    }


def _community_masters(con) -> dict[str, list[dict[str, Any]]]:
    venues = master_data.list_venues(con)
    venues.sort(key=lambda v: ((v.get("region_name") or "~"), (v["name"] or "").lower()))
    return {"genres": master_data.list_genres(con),
            "regions": master_data.list_regions(con), "venues": venues}


def _community_fields(values: dict[str, Any], masters: dict[str, list[dict[str, Any]]]) -> str:
    region_choices = [("", "지역 없음")] + [
        (str(r["region_id"]), r["name"] + ("" if r["enabled"] else " (비활성)"))
        for r in masters["regions"]]
    enabled = "1" if str(values.get("enabled", "1")) in ("1", "True", "true") else "0"
    chosen_venues = _lenient_ids(values.get("venue_ids"))
    venue_chips = '<div class="chipset scroll">' + "".join(
        f'<label class="chip"><input type="checkbox" name="venue_ids" value="{v["venue_id"]}"'
        f'{" checked" if v["venue_id"] in chosen_venues else ""}> {E(v["name"])}'
        f'{" · " + E(v["region_name"]) if v.get("region_name") else ""}'
        f'{"" if v["enabled"] else " <span class=off>(비활성)</span>"}</label>'
        for v in masters["venues"]) + "</div>" if masters["venues"] else \
        '<p class="note">등록된 장소가 없습니다</p>'
    return f"""
<div class="formgrid">
  <div><label>이름</label><input name="name" required maxlength="{communities.NAME_MAX}"
    value="{E(str(values.get('name') or ''))}"></div>
  <div><label>지역</label>{_select("region_id", region_choices, str(values.get("region_id") or ""))}</div>
  <div><label>홈페이지 URL</label><input name="homepage_url" placeholder="https://"
    value="{E(str(values.get('homepage_url') or ''))}"></div>
  <div><label>상태</label>{_select("enabled", [("1", "ENABLED"), ("0", "DISABLED")], enabled)}</div>
</div>
<div class="field"><label>소개 (공개)</label><textarea name="description" rows="3"
  maxlength="{communities.DESCRIPTION_MAX}">{E(str(values.get('description') or ''))}</textarea></div>
<div class="field"><label>운영 메모 (비공개)</label><textarea name="notes" rows="2"
  maxlength="{communities.NOTES_MAX}">{E(str(values.get('notes') or ''))}</textarea></div>
<div class="field"><label>장르 (여러 개 선택 가능)</label>
  {_genre_chips(masters["genres"], _lenient_ids(values.get("genre_ids")))}</div>
<div class="field"><label>장소 (여러 개 선택 가능)</label>{venue_chips}</div>"""


def _communities_page(view: str, flash: tuple[str, str] | None, *,
                      add_values: dict[str, Any] | None = None,
                      status_code: int = 200) -> HTMLResponse:
    with _connection() as con:
        rows = communities.list_communities(con)
        masters = _community_masters(con)
    genre_names = {g["genre_id"]: g["name"] for g in masters["genres"]}
    venue_names = {v["venue_id"]: v["name"] for v in masters["venues"]}
    table_rows, attrs = [], []
    for c in rows:
        cid = c["community_id"]
        attrs.append(f' id="community-{cid}"')
        link = public_link(c["homepage_url"])
        edit_href = f"{COMMUNITIES_PAGE}/{cid}/edit?" + urlencode({"return_to": view})
        toggle = (
            f'<form class="inline" method="post" action="{COMMUNITIES_PAGE}/{cid}/enabled">'
            f'<input type="hidden" name="enabled" value="{"0" if c["enabled"] else "1"}">'
            f'{master_admin.return_field(view)}'
            f'<button data-busy="처리 중...">{"Disable" if c["enabled"] else "Enable"}</button></form>'
        )
        if c["enabled"]:
            delete = '<span class="note">삭제하려면 먼저 비활성화하세요</span>'
        else:
            delete = (
                f'<details><summary>Delete</summary><p class="note">&#39;{E(c["name"])}&#39;'
                " 동호회와 그 장르·장소 연결만 삭제됩니다. 장소와 장르 자체는 그대로 남습니다.</p>"
                f'<form method="post" action="{COMMUNITIES_PAGE}/{cid}/delete">'
                f'{master_admin.return_field(view)}'
                '<button class="primary" data-busy="삭제 중...">Delete</button></form></details>'
            )
        table_rows.append([
            f'<div class="clip"><strong>{E(c["name"])}</strong>'
            + (f'<div class="note">{E(c["notes"])}</div>' if c["notes"] else "") + "</div>",
            E(c["region_name"] or "-"),
            E(", ".join(genre_names.get(g, str(g)) for g in c["genre_ids"]) or "-"),
            f'<div class="clip">{E(", ".join(venue_names.get(v, str(v)) for v in c["venue_ids"]) or "-")}</div>',
            (f'<a href="{E(link)}" target="_blank" rel="noopener noreferrer">열기 &#8599;</a>'
             if link else "-"),
            admin._badge("ENABLED" if c["enabled"] else "DISABLED",
                          "ok" if c["enabled"] else "muted"),
            '<div class="actionbar">'
            f'<a class="rowbtn" href="{E(edit_href)}">편집</a>{toggle}{delete}</div>',
        ])
    add_form = (
        f'<details{" open" if add_values is not None else ""}><summary>동호회 추가</summary>'
        f'<form method="post" action="{COMMUNITIES_PAGE}">{master_admin.return_field(view)}'
        + _community_fields(add_values or {"enabled": "1"}, masters)
        + '<div class="actions"><button class="primary" data-busy="저장 중...">'
        "동호회 추가</button></div></form></details>"
    )
    body = (
        "<h2>Communities (동호회)</h2>"
        '<p class="note">공개 첫 화면의 동호회 탭에 보이는 목록입니다. 활성(ENABLED) 동호회만 '
        "공개되며, 운영 메모는 공개되지 않습니다. 장르가 없는 동호회는 공개 화면에서 춤 종류 "
        "전체를 볼 때만 표시됩니다.</p>"
        + add_form
        + admin._table(["이름", "지역", "장르", "장소", "홈페이지", "상태", "Actions"],
                       table_rows, empty="등록된 동호회가 없습니다", row_attrs=attrs)
    )
    return _page("Communities", COMMUNITIES_PAGE, body, flash, status_code=status_code)


@router.get(COMMUNITIES_PAGE, response_class=HTMLResponse)
def admin_communities(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    return _communities_page(master_admin.current_view(request), admin._flash(request))


@router.post(COMMUNITIES_PAGE)
async def admin_create_community(request: Request, reviewer: str = Depends(require_admin)):
    form = await request.form()
    values = _community_values(form)
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            created = communities.create_community(con, values, reviewer=reviewer)
    except DirectoryError as exc:
        return _communities_page(_return_to(return_to, COMMUNITIES_PAGE),
                                 ("bad", f"동호회를 추가하지 못했습니다: {exc}"),
                                 add_values=values, status_code=400)
    return _go(return_to, COMMUNITIES_PAGE, f"동호회 '{created['name']}' 추가됨",
               anchor=f"community-{created['community_id']}")


def _community_edit_page(community_id: int, values: dict[str, Any], return_to: str,
                         flash: tuple[str, str] | None, *, status_code: int = 200) -> HTMLResponse:
    with _connection() as con:
        masters = _community_masters(con)
    back = _return_to(return_to, COMMUNITIES_PAGE)
    body = (
        f'<h2>동호회 편집 <span class="note">#{community_id}</span></h2>'
        f'<form method="post" action="{COMMUNITIES_PAGE}/{community_id}/edit">'
        f'{master_admin.return_field(back)}'
        + _community_fields(values, masters)
        + '<div class="actions"><button class="primary" data-busy="저장 중...">저장</button> '
        f'<a class="rowbtn" href="{E(back)}">취소</a></div></form>'
    )
    return _page("Communities", COMMUNITIES_PAGE, body, flash, status_code=status_code)


@router.get(COMMUNITIES_PAGE + "/{community_id}/edit", response_class=HTMLResponse)
def admin_edit_community_form(community_id: str, request: Request,
                              _: str = Depends(require_admin)) -> HTMLResponse:
    cid = _path_id(community_id)
    with _connection() as con:
        row = communities.get_community(con, cid)
    if row is None:
        raise HTTPException(status_code=404, detail="no such community")
    return _community_edit_page(cid, communities.snapshot(row),
                                request.query_params.get("return_to") or "",
                                admin._flash(request))


@router.post(COMMUNITIES_PAGE + "/{community_id}/edit")
async def admin_edit_community(community_id: str, request: Request,
                               reviewer: str = Depends(require_admin)):
    cid = _path_id(community_id)
    form = await request.form()
    values = _community_values(form)
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            if communities.get_community(con, cid) is None:
                return _go(return_to, COMMUNITIES_PAGE, f"동호회 {cid}을(를) 찾을 수 없습니다", "bad")
            result = communities.update_community(con, cid, values, reviewer=reviewer)
    except DirectoryError as exc:
        return _community_edit_page(cid, values, return_to,
                                    ("bad", f"저장하지 못했습니다: {exc}"), status_code=400)
    if not result["changed"]:
        return _go(return_to, COMMUNITIES_PAGE, "변경된 내용이 없습니다", anchor=f"community-{cid}")
    return _go(return_to, COMMUNITIES_PAGE,
               f"동호회 '{result['community']['name']}' 저장됨 ({', '.join(result['changed'])})",
               anchor=f"community-{cid}")


@router.post(COMMUNITIES_PAGE + "/{community_id}/enabled")
async def admin_toggle_community(community_id: str, request: Request,
                                 reviewer: str = Depends(require_admin)):
    cid = _path_id(community_id)
    form = await request.form()
    return_to = _text(form, "return_to")
    enabled = _text(form, "enabled") == "1"
    try:
        with _connection() as con:
            result = communities.set_community_enabled(con, cid, enabled, reviewer=reviewer)
    except DirectoryError as exc:
        return _go(return_to, COMMUNITIES_PAGE, str(exc), "bad")
    state = "활성화" if enabled else "비활성화"
    message = (f"동호회 '{result['community']['name']}' {state}됨" if result["changed"]
               else "변경된 내용이 없습니다")
    return _go(return_to, COMMUNITIES_PAGE, message, anchor=f"community-{cid}")


@router.post(COMMUNITIES_PAGE + "/{community_id}/delete")
async def admin_delete_community(community_id: str, request: Request,
                                 reviewer: str = Depends(require_admin)):
    cid = _path_id(community_id)
    form = await request.form()
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            removed = communities.delete_community(con, cid, reviewer=reviewer)
    except DirectoryError as exc:
        return _go(return_to, COMMUNITIES_PAGE, str(exc), "bad", anchor=f"community-{cid}")
    return _go(return_to, COMMUNITIES_PAGE, f"동호회 '{removed['community']['name']}' 삭제됨")


# === Notices ======================================================================

def _notice_values(form) -> dict[str, Any]:
    return {
        "title": _text(form, "title"), "body": _text(form, "body"),
        "status": _text(form, "status") or boards.PUBLISHED,
        "pinned": _text(form, "pinned") or "0", "genre_ids": _list(form, "genre_ids"),
    }


def _notice_fields(values: dict[str, Any], genres: list[dict[str, Any]]) -> str:
    status = str(values.get("status") or boards.PUBLISHED).upper()
    pinned = "1" if str(values.get("pinned")) in ("1", "True", "true") else "0"
    return f"""
<div class="formgrid">
  <div style="grid-column:1/-1"><label>제목</label><input name="title" required
    maxlength="{boards.TITLE_MAX}" value="{E(str(values.get('title') or ''))}"></div>
  <div><label>상태</label>{_select("status", [(s, f"{boards.STATUS_LABELS[s]} ({s})") for s in boards.STATUSES], status)}</div>
  <div><label>상단 고정</label>{_select("pinned", [("0", "고정 안 함"), ("1", "상단 고정")], pinned)}</div>
</div>
<div class="field"><label>장르 (선택하지 않으면 모든 장르에 보이는 전체 공지)</label>
  {_genre_chips(genres, _lenient_ids(values.get("genre_ids")))}</div>
<div class="field"><label>본문 (일반 텍스트 - HTML은 그대로 글자로 표시되고, http(s) 주소는 링크가 됩니다)</label>
  <textarea name="body" rows="10" maxlength="{boards.BODY_MAX}">{E(str(values.get('body') or ''))}</textarea></div>"""


def _notices_page(view: str, flash: tuple[str, str] | None, *,
                  add_values: dict[str, Any] | None = None,
                  status_code: int = 200) -> HTMLResponse:
    with _connection() as con:
        posts = boards.list_posts(con)
        genres = master_data.list_genres(con)
    genre_names = {g["genre_id"]: g["name"] for g in genres}
    table_rows, attrs = [], []
    for p in posts:
        pid = p["post_id"]
        attrs.append(f' id="notice-{pid}"')
        edit_href = f"{NOTICES_PAGE}/{pid}/edit?" + urlencode({"return_to": view})
        public = (f'<a class="rowbtn" href="/notices/{pid}" target="_blank" '
                  'rel="noopener noreferrer">공개 보기 &#8599;</a>'
                  if p["status"] == boards.PUBLISHED else "")
        delete = (
            f'<details><summary>Delete</summary><p class="note">&#39;{E(p["title"])}&#39;'
            " 공지를 삭제합니다. 되돌릴 수 없습니다 - 잠시 내리려면 상태를 숨김으로 바꾸세요.</p>"
            f'<form method="post" action="{NOTICES_PAGE}/{pid}/delete">'
            f'{master_admin.return_field(view)}'
            '<button class="primary" data-busy="삭제 중...">Delete</button></form></details>'
        )
        tone = {"PUBLISHED": "ok", "DRAFT": "muted", "HIDDEN": "warn"}.get(p["status"], "muted")
        table_rows.append([
            f'<div class="clip"><strong>{E(p["title"])}</strong></div>',
            E(", ".join(genre_names.get(g, str(g)) for g in p["genre_ids"]) or "전체 공지"),
            admin._badge(boards.STATUS_LABELS.get(p["status"], p["status"]), tone),
            "고정" if p["pinned"] else "-",
            _when(p["published_at"]),
            '<div class="actionbar">'
            f'<a class="rowbtn" href="{E(edit_href)}">편집</a>{public}{delete}</div>',
        ])
    add_form = (
        f'<details{" open" if add_values is not None else ""}><summary>공지 추가</summary>'
        f'<form method="post" action="{NOTICES_PAGE}">{master_admin.return_field(view)}'
        + _notice_fields(add_values or {}, genres)
        + '<div class="actions"><button class="primary" data-busy="저장 중...">'
        "공지 추가</button></div></form></details>"
    )
    body = (
        "<h2>Notices (공지사항)</h2>"
        '<p class="note">공개 첫 화면의 게시판 탭에 보이는 공지입니다. 게시 상태만 공개되며, '
        "장르를 고르면 그 장르를 보는 사람에게, 고르지 않으면 모두에게 보입니다.</p>"
        + add_form
        + admin._table(["제목", "장르", "상태", "고정", "게시일", "Actions"], table_rows,
                       empty="등록된 공지가 없습니다", row_attrs=attrs)
    )
    return _page("Notices", NOTICES_PAGE, body, flash, status_code=status_code)


@router.get(NOTICES_PAGE, response_class=HTMLResponse)
def admin_notices(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    return _notices_page(master_admin.current_view(request), admin._flash(request))


@router.post(NOTICES_PAGE)
async def admin_create_notice(request: Request, reviewer: str = Depends(require_admin)):
    form = await request.form()
    values = _notice_values(form)
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            created = boards.create_post(con, values, reviewer=reviewer)
    except boards.DuplicatePost as exc:
        return _go(return_to, NOTICES_PAGE, str(exc), anchor=f"notice-{exc.post_id}")
    except DirectoryError as exc:
        return _notices_page(_return_to(return_to, NOTICES_PAGE),
                             ("bad", f"공지를 추가하지 못했습니다: {exc}"),
                             add_values=values, status_code=400)
    return _go(return_to, NOTICES_PAGE, f"공지 '{created['title']}' 추가됨",
               anchor=f"notice-{created['post_id']}")


def _notice_edit_page(post_id: int, values: dict[str, Any], return_to: str,
                      flash: tuple[str, str] | None, *, status_code: int = 200) -> HTMLResponse:
    with _connection() as con:
        genres = master_data.list_genres(con)
    back = _return_to(return_to, NOTICES_PAGE)
    body = (
        f'<h2>공지 편집 <span class="note">#{post_id}</span></h2>'
        f'<form method="post" action="{NOTICES_PAGE}/{post_id}/edit">'
        f'{master_admin.return_field(back)}'
        + _notice_fields(values, genres)
        + '<div class="actions"><button class="primary" data-busy="저장 중...">저장</button> '
        f'<a class="rowbtn" href="{E(back)}">취소</a></div></form>'
    )
    return _page("Notices", NOTICES_PAGE, body, flash, status_code=status_code)


@router.get(NOTICES_PAGE + "/{post_id}/edit", response_class=HTMLResponse)
def admin_edit_notice_form(post_id: str, request: Request,
                           _: str = Depends(require_admin)) -> HTMLResponse:
    pid = _path_id(post_id)
    with _connection() as con:
        row = boards.get_post(con, pid)
    if row is None:
        raise HTTPException(status_code=404, detail="no such notice")
    return _notice_edit_page(pid, boards.snapshot(row),
                             request.query_params.get("return_to") or "",
                             admin._flash(request))


@router.post(NOTICES_PAGE + "/{post_id}/edit")
async def admin_edit_notice(post_id: str, request: Request,
                            reviewer: str = Depends(require_admin)):
    pid = _path_id(post_id)
    form = await request.form()
    values = _notice_values(form)
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            if boards.get_post(con, pid) is None:
                return _go(return_to, NOTICES_PAGE, f"게시글 {pid}을(를) 찾을 수 없습니다", "bad")
            result = boards.update_post(con, pid, values, reviewer=reviewer)
    except DirectoryError as exc:
        return _notice_edit_page(pid, values, return_to,
                                 ("bad", f"저장하지 못했습니다: {exc}"), status_code=400)
    if not result["changed"]:
        return _go(return_to, NOTICES_PAGE, "변경된 내용이 없습니다", anchor=f"notice-{pid}")
    return _go(return_to, NOTICES_PAGE,
               f"공지 '{result['post']['title']}' 저장됨 ({', '.join(result['changed'])})",
               anchor=f"notice-{pid}")


@router.post(NOTICES_PAGE + "/{post_id}/delete")
async def admin_delete_notice(post_id: str, request: Request,
                              reviewer: str = Depends(require_admin)):
    pid = _path_id(post_id)
    form = await request.form()
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            removed = boards.delete_post(con, pid, reviewer=reviewer)
    except DirectoryError as exc:
        return _go(return_to, NOTICES_PAGE, str(exc), "bad")
    return _go(return_to, NOTICES_PAGE, f"공지 '{removed['post']['title']}' 삭제됨")
