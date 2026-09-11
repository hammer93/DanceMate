"""Admin screen for Community Discovery (v0.89.0): /admin/community-discovery.

Queue a search, see what each run found and how each provider answered, and
review candidates - register one as a Community (through the Communities
screen's own form and communities.create_community()), link it to an existing
Community, hold it or reject it. Nothing here is public, and nothing becomes a
Community without an operator's click.

Follows directory_admin's rules: every page is admin._page() (the console's
one submit guard), every value is escaped, a return address is only ever this
screen, a failed save shows the form again with the reason.
"""

from __future__ import annotations

import html
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import admin, communities, master_data, pagination
from . import community_discovery as cd
from .admin_auth import require_admin
from .directory import DirectoryError, public_link
from .directory_admin import (
    _community_fields, _community_masters, _community_values, _go, _list, _page, _path_id,
    _return_to, _select, _text,
)

router = APIRouter()

E = html.escape
BASE = "/admin/community-discovery"
PAGE_SIZE = 50
FILTER_KEYS = ("provider", "genre", "region", "classification", "state")
ACTIONS = {"link", "hold", "reject", "reopen"}
_TONE = {cd.VERIFIED_NEW: "ok", cd.VERIFIED_EXISTING: "ok", cd.POSSIBLE_DUPLICATE: "warn",
         cd.UNVERIFIED: "muted", cd.STALE: "muted", cd.INACTIVE: "bad", cd.NOT_A_COMMUNITY: "muted",
         cd.HIGH: "ok", cd.MEDIUM: "warn", cd.LOW: "muted", cd.SUCCESS: "ok",
         cd.PARTIAL_SUCCESS: "warn", cd.FAILED: "bad", cd.QUEUED: "muted", cd.RUNNING: "warn",
         cd.CALL_SUCCESS: "ok", cd.CALL_NO_RESULTS: "muted", cd.ACCESS_LIMITED: "warn",
         cd.RATE_LIMITED: "warn", cd.CALL_ERROR: "bad"}


def _connection():
    return admin._connection()


def _badge(value: str | None, label: str | None = None) -> str:
    return f'<span class="badge {_TONE.get(value or "", "muted")}">{E(label or value or "-")}</span>'


def _filters(request: Request, genres, regions) -> dict[str, str]:
    allowed = {
        "provider": set(cd.PROVIDERS), "genre": {g["code"] for g in genres},
        "region": {r["code"] for r in regions}, "classification": set(cd.CLASSIFICATIONS),
        "state": set(cd.REVIEW_STATES),
    }
    out = {}
    for key in FILTER_KEYS:
        value = (request.query_params.get(key) or "").strip().upper()
        out[key] = value if value in allowed[key] else ""
    return out


def _when(value) -> str:
    if not value:
        return "-"
    from . import events_api  # noqa: PLC0415

    return value.astimezone(events_api.SEOUL).strftime("%Y-%m-%d %H:%M")


# --- sections -------------------------------------------------------------------------------

def _providers_card(available: list[dict[str, Any]]) -> str:
    cells = "".join(
        f'<div class="card"><div class="k">{E(p["label"])}</div>'
        f'<div class="v">{"configured" if p["configured"] else "not configured"}</div>'
        f'<div class="s">{E("credentials present" if p["configured"] else "missing: " + ", ".join(p["missing"]))}'
        "</div></div>" for p in available)
    return f'<div class="cards">{cells}</div>'


def _run_form(view: str, genres, regions) -> str:
    targets = [g for g in genres if g["code"] in cd.TARGET_GENRES]
    order = {c: n for n, c in enumerate(cd.TARGET_GENRES)}
    targets.sort(key=lambda g: order[g["code"]])
    genre_chips = "".join(
        f'<label class="chip"><input type="checkbox" name="genres" value="{E(g["code"])}" checked> '
        f'{E(g["name"])}{"" if g["enabled"] else " <span class=off>(비활성)</span>"}</label>'
        for g in targets)
    region_rows = [r for r in regions if r["code"] in cd.REGION_QUERY_CODES]
    region_chips = "".join(
        f'<label class="chip"><input type="checkbox" name="regions" value="{E(r["code"])}"> '
        f'{E(r["name"])}</label>' for r in region_rows)
    return f"""
<form method="post" action="{BASE}/runs">{_hidden(view)}
<div class="formgrid">
  <div><label>검색 서비스</label>{_select("provider", [("ALL", "전체 (Naver + Kakao/Daum)"), ("NAVER", "Naver"), ("KAKAO", "Kakao/Daum")], "ALL")}</div>
  <div><label>추가 검색어 (선택, 쉼표로 3개까지)</label><input name="keywords" maxlength="130" placeholder="예: 직장인 살사"></div>
</div>
<div class="field"><label>장르 (복수 선택)</label><div class="chipset">{genre_chips}</div></div>
<div class="field"><label>지역 (선택하지 않으면 전체)</label><div class="chipset">{region_chips}</div></div>
<div class="actions"><button class="primary" data-busy="등록 중...">동호회 검색</button>
<span class="note">검색은 스케줄러가 다음 주기(최대 {E(str(5))}분)에 실행합니다. 결과는 아래 후보 목록에만 들어가며, 동호회로 자동 등록되지 않습니다.</span></div>
</form>"""


def _hidden(view: str) -> str:
    return f'<input type="hidden" name="return_to" value="{E(view)}">'


def _runs_table(runs: list[dict[str, Any]]) -> str:
    rows = []
    for run in runs:
        providers = " ".join(
            _badge(v.get("status"), f'{cd.PROVIDER_LABELS.get(p, p)} {v.get("status")} '
                                    f'({v.get("results", 0)})')
            for p, v in (run["provider_status"] or {}).items()) or "-"
        rows.append([
            f"#{run['run_id']}", E(_when(run["requested_at"])), _badge(run["status"]),
            E(", ".join(run["genre_codes"])) + (f'<div class="note">{E(", ".join(run["region_codes"]))}</div>'
                                                 if run["region_codes"] else ""),
            providers, f"{run['query_count']} / {run['result_count']}",
            f"+{run['new_items']} / ~{run['updated_items']}",
            f'<div class="clip note">{E(run["error_summary"] or "")}</div>',
        ])
    return admin._table(["Run", "요청", "상태", "장르 / 지역", "Provider", "검색어 / 결과",
                         "신규 / 갱신", "오류"], rows, empty="아직 실행한 검색이 없습니다")


def _queries_section(view: str, queries: list[dict[str, Any]], genres) -> str:
    rows = []
    for q in queries:
        toggle = (f'<form class="inline" method="post" action="{BASE}/queries/{q["query_id"]}/enabled">'
                  f'{_hidden(view)}<input type="hidden" name="enabled" value="{"0" if q["enabled"] else "1"}">'
                  f'<button data-busy="...">{"끄기" if q["enabled"] else "켜기"}</button></form>')
        rows.append([E(q["genre_name"]), E(q["keyword"]), E(q["provider_scope"]),
                     admin._badge("ON" if q["enabled"] else "OFF", "ok" if q["enabled"] else "muted")
                     + (" <span class=note>기본</span>" if q["is_default"] else ""), toggle])
    targets = [g for g in genres if g["code"] in cd.TARGET_GENRES]
    genre_options = [("", "장르 선택")] + [(str(g["genre_id"]), g["name"]) for g in targets]
    add = f"""
<form method="post" action="{BASE}/queries">{_hidden(view)}
<div class="formgrid">
  <div><label>장르</label>{_select("genre_id", genre_options, "")}</div>
  <div><label>검색어</label><input name="keyword" maxlength="{cd.KEYWORD_MAX}" required></div>
  <div><label>검색 서비스</label>{_select("provider_scope", [(s, s) for s in cd.SCOPES], "ALL")}</div>
</div><div class="actions"><button class="primary" data-busy="저장 중...">검색어 추가</button></div></form>"""
    return (f'<details><summary>검색어 설정 ({len(queries)})</summary>{add}'
            + admin._table(["장르", "검색어", "서비스", "상태", ""], rows, empty="검색어가 없습니다")
            + "</details>")


def _filter_form(filters: dict[str, str], genres, regions) -> str:
    def options(values, labels=None):
        return [("", "전체")] + [(v, (labels or {}).get(v, v)) for v in values]

    return f"""
<form method="get" action="{BASE}" class="formgrid" style="margin:12px 0">
  <div><label>Provider</label>{_select("provider", options(cd.PROVIDERS, cd.PROVIDER_LABELS), filters["provider"])}</div>
  <div><label>장르</label>{_select("genre", options([g["code"] for g in genres if g["code"] in cd.TARGET_GENRES]), filters["genre"])}</div>
  <div><label>지역</label>{_select("region", options([r["code"] for r in regions if r["code"] != "KR"], {r["code"]: r["name"] for r in regions}), filters["region"])}</div>
  <div><label>분류</label>{_select("classification", options(cd.CLASSIFICATIONS, cd.CLASSIFICATION_LABELS), filters["classification"])}</div>
  <div><label>검토 상태</label>{_select("state", options(cd.REVIEW_STATES, cd.REVIEW_LABELS), filters["state"])}</div>
  <div style="align-self:end"><button>필터 적용</button></div>
</form>"""


def _candidate_rows(view: str, items: list[dict[str, Any]], comms, genre_names) -> tuple[list, list]:
    rows, attrs = [], []
    community_options = [("", "동호회 선택")] + [(str(c["community_id"]), c["name"]) for c in comms]
    for item in items:
        iid = item["item_id"]
        attrs.append(f' id="candidate-{iid}"')
        name = (f'<strong>{E(item["candidate_name"])}</strong>' if item["candidate_name"]
                else '<span class="badge muted">이름 미확정</span>')
        evidence = (f'<div class="note clip">{E(item["title"])}</div>'
                    f'<div class="note clip">{E(item["snippet"][:140])}</div>')
        link = public_link(item["community_url"])
        url = (f'<a href="{E(link)}" target="_blank" rel="noopener noreferrer">{E(item["community_url"])}</a>'
               if link else E(item["community_url"]))
        venues = ", ".join(
            f'{E(n)}{"" if k == cd.VENUE_MATCH else "?"}'
            for n, k in zip(item["venue_names"] or [], item["venue_kinds"] or [])) or "-"
        existing = ""
        if item["registered_community_name"]:
            existing = (f'<a href="/admin/communities#community-{item["registered_community_id"]}">'
                        f'{E(item["registered_community_name"])}</a>')
        elif item["existing_community_name"]:
            existing = f'{E(item["existing_community_name"])} (의심)'
        elif item["duplicate_of_item_id"]:
            existing = f'<a href="#candidate-{item["duplicate_of_item_id"]}">후보 #{item["duplicate_of_item_id"]}</a>'
        actions = []
        if item["review_state"] not in cd.DONE_STATES:
            actions.append(f'<a class="rowbtn" href="{BASE}/items/{iid}/register?'
                           f'{E(urlencode({"return_to": view}))}">등록</a>')
            if comms:
                actions.append(
                    f'<form class="inline" method="post" action="{BASE}/items/{iid}/link">{_hidden(view)}'
                    f'{_select("community_id", community_options, "")}'
                    f'<button data-busy="...">연결</button></form>')
            if item["review_state"] in (cd.HELD, cd.REJECTED):
                actions.append(_action_form(view, iid, "reopen", "되돌리기"))
            else:
                actions.append(_action_form(view, iid, "hold", "보류"))
                actions.append(_action_form(view, iid, "reject", "제외"))
        rows.append([
            f'<div class="clip">{name}{evidence}</div>',
            E(", ".join(genre_names.get(c, c) for c in item["genre_codes"]) or "-"),
            E(item["region_name"] or item["region_candidate"] or "-"),
            E(", ".join(cd.PROVIDER_LABELS.get(p, p) for p in item["providers"])),
            f'<div class="clip">{url}</div><div class="note">{E(item["platform"])}</div>',
            E(item["recent_activity_date"].isoformat() if item["recent_activity_date"] else "-")
            + f'<div class="note">{E(item["activity"])}</div>',
            _badge(item["confidence"]),
            _badge(item["classification"], cd.CLASSIFICATION_LABELS[item["classification"]])
            + f'<div class="note">{E(item["kind"])}</div>',
            existing or "-", f'<div class="clip">{venues}</div>',
            E(cd.REVIEW_LABELS[item["review_state"]]),
            '<div class="actionbar">' + "".join(actions) + "</div>",
        ])
    return rows, attrs


def _action_form(view: str, item_id: int, action: str, label: str) -> str:
    return (f'<form class="inline" method="post" action="{BASE}/items/{item_id}/{action}">'
            f'{_hidden(view)}<button data-busy="...">{E(label)}</button></form>')


def _pager(filters: dict[str, str], page: int, total: int) -> str:
    pages = pagination.total_pages(total, page_size=PAGE_SIZE)
    if pages <= 1:
        return ""
    base = {k: v for k, v in filters.items() if v}

    def href(p):
        return f"{BASE}?{urlencode({**base, 'page': p})}"

    prev = f'<a href="{E(href(page - 1))}">← 이전</a>' if page > 1 else ""
    nxt = f'<a href="{E(href(page + 1))}">다음 →</a>' if page < pages else ""
    return f'<p class="note">{prev} {page} / {pages} {nxt}</p>'


# --- routes ---------------------------------------------------------------------------------

@router.get(BASE, response_class=HTMLResponse)
def admin_discovery(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    from . import master_admin  # noqa: PLC0415

    view = master_admin.current_view(request)
    with _connection() as con:
        cd.ensure_default_queries(con)
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)
        filters = _filters(request, genres, regions)
        total = cd.list_items(con, provider=filters["provider"] or None, genre=filters["genre"] or None,
                              region=filters["region"] or None,
                              classification=filters["classification"] or None,
                              review_state=filters["state"] or None, limit=1)[1]
        page = pagination.resolve_page(request.query_params.get("page"), total, page_size=PAGE_SIZE)
        items, total = cd.list_items(
            con, provider=filters["provider"] or None, genre=filters["genre"] or None,
            region=filters["region"] or None, classification=filters["classification"] or None,
            review_state=filters["state"] or None, limit=PAGE_SIZE,
            offset=pagination.sql_offset(page, page_size=PAGE_SIZE))
        runs = cd.list_runs(con)
        queries = cd.list_queries(con)
        comms = communities.list_communities(con)
        current = cd.open_run(con)
    genre_names = {g["code"]: g["name"] for g in genres}
    rows, attrs = _candidate_rows(view, items, comms, genre_names)
    body = (
        "<h2>Community Discovery (동호회 발굴)</h2>"
        '<p class="note">Naver·Kakao/Daum 공개 검색으로 동호회 후보를 찾습니다. 후보는 관리자 전용이며 '
        "공개 동호회 탭에 나오지 않습니다. 등록은 이 화면에서 운영자가 검토한 뒤 동호회 등록 양식으로만 "
        "이루어집니다. 신뢰도와 분류는 판단을 돕는 참고 정보입니다.</p>"
        + _providers_card(cd.provider_availability())
        + (f'<p class="flash ok">검색 #{current["run_id"]} {E(current["status"])} - '
           "스케줄러가 처리 중입니다.</p>" if current else "")
        + _run_form(view, genres, regions)
        + "<h3>최근 검색</h3>" + _runs_table(runs)
        + _queries_section(view, queries, genres)
        + f"<h3>후보 ({total})</h3>" + _filter_form(filters, genres, regions)
        + admin._table(["이름 / 근거", "장르 후보", "지역", "Provider", "URL", "최근 활동", "신뢰도",
                        "분류", "기존 동호회", "장소 후보", "검토", "처리"], rows,
                       empty="후보가 없습니다", row_attrs=attrs)
        + _pager(filters, page, total)
    )
    return _page("Community Discovery", BASE, body, admin._flash(request))


@router.post(BASE + "/runs")
async def admin_queue_run(request: Request, reviewer: str = Depends(require_admin)):
    form = await request.form()
    return_to = _text(form, "return_to")
    provider = _text(form, "provider").upper() or "ALL"
    providers = list(cd.PROVIDERS) if provider == "ALL" else [provider]
    keywords = [k for k in _text(form, "keywords").split(",") if k.strip()]
    try:
        with _connection() as con:
            run = cd.queue_run(con, providers=providers, genre_codes=_list(form, "genres"),
                               region_codes=_list(form, "regions"), extra_keywords=keywords,
                               requested_by=reviewer)
    except DirectoryError as exc:
        return _go(return_to, BASE, f"검색을 등록하지 못했습니다: {exc}", "bad")
    return _go(return_to, BASE, f"검색 #{run['run_id']}을(를) 대기열에 등록했습니다. 스케줄러가 곧 실행합니다.")


@router.post(BASE + "/queries")
async def admin_add_query(request: Request, _: str = Depends(require_admin)):
    form = await request.form()
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            added = cd.add_query(con, genre_id=_text(form, "genre_id"), keyword=_text(form, "keyword"),
                                 provider_scope=_text(form, "provider_scope") or cd.SCOPE_ALL)
    except DirectoryError as exc:
        return _go(return_to, BASE, f"검색어를 추가하지 못했습니다: {exc}", "bad")
    return _go(return_to, BASE, f"검색어 '{added['keyword']}' 추가됨")


@router.post(BASE + "/queries/{query_id}/enabled")
async def admin_toggle_query(query_id: str, request: Request, _: str = Depends(require_admin)):
    qid = _path_id(query_id)
    form = await request.form()
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            result = cd.set_query_enabled(con, qid, _text(form, "enabled") == "1")
    except DirectoryError as exc:
        return _go(return_to, BASE, str(exc), "bad")
    return _go(return_to, BASE, f"검색어 '{result['keyword']}' {'켜짐' if result['enabled'] else '꺼짐'}")


def _register_page(item: dict[str, Any], values: dict[str, Any], return_to: str,
                   flash: tuple[str, str] | None, *, status_code: int = 200) -> HTMLResponse:
    with _connection() as con:
        masters = _community_masters(con)
    back = _return_to(return_to, BASE)
    candidates = [n for n, k in zip(item["venue_names"] or [], item["venue_kinds"] or [])
                  if k == cd.VENUE_CANDIDATE]
    link = public_link(item["community_url"])
    evidence = admin._table(["항목", "값"], [
        ["URL", (f'<a href="{E(link)}" target="_blank" rel="noopener noreferrer">{E(item["community_url"])}</a>'
                 if link else E(item["community_url"]))],
        ["플랫폼 / Provider", E(f'{item["platform"]} / {", ".join(item["providers"])}')],
        ["최근 제목", E(item["title"])], ["요약", E(item["snippet"])],
        ["분류 / 신뢰도", E(f'{item["classification"]} / {item["confidence"]} / {item["activity"]}')],
        ["최근 활동일", E(item["recent_activity_date"].isoformat() if item["recent_activity_date"] else "-")],
        ["처음 / 마지막 발견", E(f'{_when(item["first_seen"])} / {_when(item["last_seen"])} ({item["seen_count"]}회)')],
        ["근거", "<br>".join(E(r) for r in item["reasons"] or [])],
        ["장소 후보 (이름만 일치, 자동 선택 안 함)", E(", ".join(candidates) or "-")],
    ], empty="-")
    body = (
        f'<h2>동호회로 등록 <span class="note">후보 #{item["item_id"]}</span></h2>'
        '<p class="note">검색 결과를 그대로 옮기지 않습니다. 이름·소개·장르·장소·URL·상태를 확인하고 '
        "고친 뒤 등록하세요. 등록은 동호회 관리와 같은 규칙(이름 중복·URL·ID 검증, 감사 기록)을 거칩니다.</p>"
        + evidence
        + f'<form method="post" action="{BASE}/items/{item["item_id"]}/register">{_hidden(back)}'
        + _community_fields(values, masters)
        + '<div class="actions"><button class="primary" data-busy="등록 중...">동호회로 등록</button> '
        f'<a class="rowbtn" href="{E(back)}">취소</a></div></form>'
    )
    return _page("Community Discovery", BASE, body, flash, status_code=status_code)


@router.get(BASE + "/items/{item_id}/register", response_class=HTMLResponse)
def admin_register_form(item_id: str, request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    iid = _path_id(item_id)
    with _connection() as con:
        item = cd.get_item(con, iid)
        genre_ids = {g["code"]: g["genre_id"] for g in master_data.list_genres(con)}
    if item is None:
        raise HTTPException(status_code=404, detail="no such candidate")
    if item["review_state"] in cd.DONE_STATES:
        return _go(request.query_params.get("return_to"), BASE,
                   "이미 등록되었거나 연결된 후보입니다", "bad")
    return _register_page(item, cd.registration_defaults(item, genre_ids),
                          request.query_params.get("return_to") or "", admin._flash(request))


@router.post(BASE + "/items/{item_id}/register")
async def admin_register(item_id: str, request: Request, reviewer: str = Depends(require_admin)):
    iid = _path_id(item_id)
    form = await request.form()
    values = _community_values(form)
    return_to = _text(form, "return_to")
    with _connection() as con:
        item = cd.get_item(con, iid)
    if item is None:
        raise HTTPException(status_code=404, detail="no such candidate")
    try:
        with _connection() as con:
            community = cd.register_item(con, iid, values, reviewer=reviewer)
    except DirectoryError as exc:
        return _register_page(item, values, return_to, ("bad", f"등록하지 못했습니다: {exc}"),
                              status_code=400)
    return _go(return_to, BASE,
               f"동호회 '{community['name']}' 등록됨 (Community #{community['community_id']})",
               anchor=f"candidate-{iid}")


@router.post(BASE + "/items/{item_id}/{action}")
async def admin_review_action(item_id: str, action: str, request: Request,
                              reviewer: str = Depends(require_admin)):
    iid = _path_id(item_id)
    if action not in ACTIONS:
        raise HTTPException(status_code=400, detail="unknown action")
    form = await request.form()
    return_to = _text(form, "return_to")
    try:
        with _connection() as con:
            if action == "link":
                community = cd.link_item(con, iid, _text(form, "community_id"), reviewer=reviewer)
                message = f"후보 #{iid}을(를) 동호회 '{community['name']}'에 연결했습니다"
            else:
                state = {"hold": cd.HELD, "reject": cd.REJECTED, "reopen": cd.PENDING}[action]
                cd.set_review_state(con, iid, state, reviewer=reviewer)
                message = f"후보 #{iid}: {cd.REVIEW_LABELS[state]}"
    except DirectoryError as exc:
        return _go(return_to, BASE, str(exc), "bad", anchor=f"candidate-{iid}")
    return _go(return_to, BASE, message, anchor=f"candidate-{iid}")
