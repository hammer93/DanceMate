"""One editing pattern for every master-data screen.

Genres, regions, venues, organizers and sources are five different things, but
the operator's question is the same each time: *this row is slightly wrong, let
me fix it*. So they get one form, one route shape and one set of rules, rather
than five slightly different ones that each have to be learned.

The form opens where the row is, already filled in with what the row says --
an empty form would be asking the operator to retype the record they are
looking at. Codes and provider credentials are shown as read-only text or not
shown at all: a code is how everything else refers to the row, and a credential
belongs in .env and nowhere a browser can reach.

Rendering helpers live here and are called from the pages in admin.py, which
still own their own layouts. The routes live here too, beside the rules.
"""

from __future__ import annotations

import html
from typing import Any, Callable

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import admin, db, master_edit
from .admin_auth import require_admin

router = APIRouter()
api = APIRouter(prefix="/api/admin", tags=["admin"])

E = html.escape

# Where each entity's page lives, so an edit returns to where it started.
PAGE = {
    master_edit.GENRE: "/admin/master",
    master_edit.REGION: "/admin/master",
    master_edit.VENUE: "/admin/venues",
    master_edit.ORGANIZER: "/admin/organizers",
    master_edit.SOURCE: "/admin/sources",
    # v0.86.9: Settings' event terminology rows use the same inline row
    # helpers; this is where a save on one of them returns to.
    "TERM": "/admin/settings",
    # v0.88.0: rows with their own screens that share the audit trail.
    master_edit.COMMUNITY: "/admin/communities",
    master_edit.BOARD_POST: "/admin/notices",
}


def _options(rows: list[dict[str, Any]], *, id_key: str, label_key: str,
             selected: Any, blank: str | None = "-") -> str:
    out = [f'<option value="">{E(blank)}</option>'] if blank is not None else []
    for row in rows:
        mark = " selected" if row[id_key] == selected else ""
        out.append(f'<option value="{row[id_key]}"{mark}>{E(str(row[label_key]))}</option>')
    return "".join(out)


def _choices(values: tuple[str, ...] | list[str], selected: Any) -> str:
    return "".join(
        f'<option{" selected" if v == selected else ""}>{E(str(v))}</option>'
        for v in values
    )


def field(name: str, label: str, value: Any = "", *, kind: str = "text",
          options: str | None = None, note: str | None = None,
          placeholder: str = "") -> str:
    """One labelled input, filled in with what the row currently says."""
    shown = "" if value is None else str(value)
    hint = f'<div class="note">{E(note)}</div>' if note else ""
    if kind == "readonly":
        # Rendered, not editable: the operator can see the code without being
        # invited to change what every other record uses to find this one.
        return (f'<div><label>{E(label)}</label>'
                f'<input value="{E(shown)}" disabled>{hint}</div>')
    if kind == "select":
        return (f'<div><label>{E(label)}</label>'
                f'<select name="{E(name)}">{options or ""}</select>{hint}</div>')
    if kind == "checkbox":
        checked = " checked" if value else ""
        return (f'<div><label>{E(label)}</label>'
                f'<input type="checkbox" name="{E(name)}" value="1"{checked}>{hint}</div>')
    attrs = ' type="number" min="1"' if kind == "number" else ""
    return (f'<div><label>{E(label)}</label>'
            f'<input name="{E(name)}"{attrs} value="{E(shown)}" '
            f'placeholder="{E(placeholder)}">{hint}</div>')


def edit_form(entity_type: str, entity_id: int, fields: list[str], *,
              summary: str = "Edit", extra: str = "",
              note: str | None = None, return_to: str | None = None) -> str:
    """An inline edit form, opened where the row is listed.

    ``Cancel`` is the browser's own close on a <details> block: nothing has been
    sent, so nothing has to be undone.

    ``return_to`` (v0.86.8, Section 4) is the list URL the operator is looking
    at right now - page number, filters and search included - so saving lands
    back on it instead of on a bare first page.
    """
    hint = f'<p class="note">{note}</p>' if note else ""
    return f"""
<details class="editrow">
  <summary>{E(summary)}</summary>
  <form method="post" action="/admin/master-data/{E(entity_type)}/{entity_id}/edit">
    {return_field(return_to)}
    <div class="grid">{''.join(fields)}</div>
    {hint}
    <div class="actions">
      <button class="primary">Save Changes</button>
      <span class="note">Cancel: 닫으면 아무것도 저장되지 않습니다</span>
    </div>
  </form>
  {extra}
</details>"""


# --- inline row editing (v0.86.8, Section 4) --------------------------------
#
# Clicking Edit on a list row turns *that row* into inputs, in place: same
# page, same route, same page number, same filters, same scroll position.
# Which row is open is a query parameter (`?edit=GENRE:5`) rather than
# client-side state, so it survives the redirect a POST has to end with, and
# a save that fails comes back with the row still open, the error above it,
# and the row's stored values back in the inputs.
#
# The inputs live in the row's own cells while the <form> element itself sits
# outside the table (a form cannot legally span <td>s); they are tied together
# with the HTML5 `form="..."` attribute, which is also what lets the row's
# other forms - toggle, delete, the venue's alias editor - keep working beside
# it without ever being nested inside it.

EDIT_PARAM = "edit"


def form_id(entity_type: str, entity_id: int) -> str:
    return f"edit-{entity_type}-{entity_id}"


def row_id(entity_type: str, entity_id: int) -> str:
    return f"row-{entity_type}-{entity_id}"


def _split_url(url: str) -> tuple[str, list[tuple[str, str]]]:
    from urllib.parse import parse_qsl, urlsplit

    parts = urlsplit(url)
    return parts.path, list(parse_qsl(parts.query))


def _rebuilt(url: str, *, drop: tuple[str, ...] = (),
             add: list[tuple[str, str]] | None = None, anchor: str = "") -> str:
    from urllib.parse import urlencode

    path, params = _split_url(url)
    kept = [(k, v) for k, v in params if k not in drop]
    kept.extend(add or [])
    query = urlencode(kept)
    out = f"{path}?{query}" if query else path
    return f"{out}#{anchor}" if anchor else out


def current_view(request) -> str:
    """The list URL exactly as the operator is looking at it.

    Page number, filters, search and sort all ride along; the one-shot flash
    parameters do not, so a save after a save does not stack old messages.
    """
    url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return _rebuilt(url, drop=("msg", "tone"))


def safe_view(raw: str | None, fallback: str) -> str:
    """A return URL is only ever a path on this console.

    Anything absolute, protocol-relative or outside /admin is not somewhere a
    save is allowed to send a browser, so it falls back to the entity's own
    list page rather than being followed.
    """
    candidate = (raw or "").strip()
    if (not candidate or candidate.startswith("//") or "\\" in candidate
            or not candidate.startswith("/admin")):
        return fallback
    return candidate


def return_field(return_to: str | None) -> str:
    if not return_to:
        return ""
    return f'<input type="hidden" name="return_to" value="{E(return_to)}">'


def editing_id(request, entity_type: str) -> int | None:
    """Which row of this entity the list has been asked to open, if any."""
    raw = request.query_params.get(EDIT_PARAM) if request is not None else None
    if not raw or ":" not in raw:
        return None
    kind, _, ident = raw.partition(":")
    if kind.strip().upper() != entity_type:
        return None
    try:
        return int(ident)
    except ValueError:
        return None


def edit_link(view: str, entity_type: str, entity_id: int, *,
              label: str = "편집") -> str:
    """Open this row for editing: same page, same filters, one row different."""
    href = _rebuilt(view, drop=(EDIT_PARAM,),
                    add=[(EDIT_PARAM, f"{entity_type}:{entity_id}")],
                    anchor=row_id(entity_type, entity_id))
    return f'<a class="rowbtn" href="{E(href)}">{E(label)}</a>'


def cancel_url(view: str, entity_type: str, entity_id: int) -> str:
    """Back to the same list, same page, nothing sent and nothing changed."""
    return _rebuilt(view, drop=(EDIT_PARAM,), anchor=row_id(entity_type, entity_id))


def row_form(entity_type: str, entity_id: int, return_to: str, *,
             action: str | None = None) -> str:
    """The <form> element the row's inputs belong to. Rendered before the table.

    ``action`` (v0.86.9) lets a row that is not master data - a Settings
    term - post to its own route while reusing every other helper here.
    """
    target = action or f"/admin/master-data/{entity_type}/{entity_id}/edit"
    return (
        f'<form id="{E(form_id(entity_type, entity_id))}" class="rowform" method="post" '
        f'action="{E(target)}">'
        f'{return_field(return_to)}</form>'
    )


def row_input(entity_type: str, entity_id: int, name: str, value: Any = "", *,
              kind: str = "text", options: str | None = None,
              label: str | None = None, placeholder: str = "") -> str:
    """One editable cell of a row that is currently in edit mode."""
    fid = form_id(entity_type, entity_id)
    shown = "" if value is None else str(value)
    tag = f'<span class="celllabel">{E(label)}</span>' if label else ""
    if kind == "select":
        return (f'{tag}<select class="cellinput" name="{E(name)}" form="{E(fid)}">'
                f'{options or ""}</select>')
    if kind == "textarea":
        # Free text in a narrow column (v0.86.8): the same cell and the same
        # width, but two visible lines, so a note is readable where a
        # single-line input clipped it. An empty one still renders - a field
        # with no value is not a field that has gone away.
        return (f'{tag}<textarea class="cellinput" name="{E(name)}" '
                f'form="{E(fid)}" rows="2" '
                f'placeholder="{E(placeholder)}">{E(shown)}</textarea>')
    return (f'{tag}<input class="cellinput" name="{E(name)}" form="{E(fid)}" '
            f'value="{E(shown)}" placeholder="{E(placeholder)}">')


def enabled_input(entity_type: str, entity_id: int, enabled: bool) -> str:
    """State as a real field of the row, not a button beside it.

    A <select> rather than a checkbox on purpose: an unticked checkbox is not
    submitted at all, which would read as "unchanged" and silently ignore an
    operator who meant to disable the row.
    """
    return row_input(
        entity_type, entity_id, "enabled", kind="select",
        options=(f'<option value="1"{" selected" if enabled else ""}>ENABLED</option>'
                 f'<option value="0"{"" if enabled else " selected"}>DISABLED</option>'),
    )


def row_actions(view: str, entity_type: str, entity_id: int) -> str:
    """Save and Cancel, on the row being edited.

    Save submits the row's form; Cancel is a plain link back to the same list
    view with the row closed - nothing has been sent, so nothing has to be
    undone. `data-busy` is what the console's one submit guard reads to stop a
    second click sending the same edit twice.
    """
    fid = form_id(entity_type, entity_id)
    return (
        '<div class="rowactions">'
        f'<button class="primary" type="submit" form="{E(fid)}" '
        f'data-busy="저장 중...">완료</button>'
        f'<a class="rowbtn" href="{E(cancel_url(view, entity_type, entity_id))}">취소</a>'
        "</div>"
    )


def toggle_form(entity_type: str, entity_id: int, enabled: bool,
                return_to: str | None = None) -> str:
    """Enable or disable, which is not the same button as delete."""
    return (
        f'<form class="inline" method="post" '
        f'action="/admin/master-data/{E(entity_type)}/{entity_id}/enabled">'
        f'<input type="hidden" name="enabled" value="{"0" if enabled else "1"}">'
        f'{return_field(return_to)}'
        f'<button>{"Disable" if enabled else "Enable"}</button></form>'
    )


def alias_editor(venue: dict[str, Any], alias_rows: list[dict[str, Any]],
                 usage: dict[int, int]) -> str:
    """The venue's spellings, with how much work each one is doing.

    An alias created from a raw post string is what makes that spelling resolve
    next time. Removing one is allowed and sometimes right, but the count says
    what it would cost.
    """
    items = []
    for alias in alias_rows:
        used = usage.get(alias["venue_alias_id"], 0)
        badge = (f'<span class="badge warn">{used} event</span>' if used
                 else '<span class="badge muted">unused</span>')
        items.append(
            f'<li>{E(alias["alias"])} {badge} '
            f'<form class="inline" method="post" '
            f'action="/admin/master-data/VENUE/{venue["venue_id"]}/alias-remove">'
            f'<input type="hidden" name="venue_alias_id" value="{alias["venue_alias_id"]}">'
            + (f'<input type="hidden" name="force" value="1">' if not used else "")
            + "<button>Remove</button></form></li>"
        )
    listing = f'<ul class="sources">{"".join(items)}</ul>' if items else (
        '<p class="note">alias가 없습니다.</p>')
    return f"""
<h3 style="font-size:13px;margin:14px 0 6px">Aliases</h3>
{listing}
<form method="post" action="/admin/master-data/VENUE/{venue['venue_id']}/alias-add">
  <div class="grid"><div><label>Add alias</label>
    <input name="alias" placeholder="La Ventana" required></div></div>
  <div class="actions"><button>Add Alias</button></div>
  <p class="note">alias는 게시글에서 읽은 표현이 이 장소로 인식되게 합니다.
  사용 중인 alias를 지우면 그 표현은 다시 Unresolved 대기열로 갑니다.</p>
</form>"""


def genre_editor(venue: dict[str, Any], all_genres: list[dict[str, Any]],
                 observed: list[dict[str, Any]] | None = None) -> str:
    """Which dance genres are confirmed at this venue (v0.85.7).

    A multi-select checkbox group, not one-at-a-time like aliases - the
    genre set is small and fixed (TANGO/SALSA/SWING today), so ticking the
    boxes that apply and saving once is the whole interaction. Saving
    diffs the checked set against what is already confirmed rather than
    replacing rows wholesale, so nothing is touched that did not change.

    ``observed`` (Section 18/62), when given, is a read-only suggestion
    from the venue's own event history - shown beside the checkboxes,
    never pre-checking anything on its own. A human still ticks the box.
    """
    checked = set(venue.get("genre_codes") or [])
    boxes = []
    for g in all_genres:
        mark = " checked" if g["code"] in checked else ""
        boxes.append(
            f'<label class="chip"><input type="checkbox" name="genre_ids" '
            f'value="{g["genre_id"]}"{mark}> {E(g["name"])}</label>'
        )
    observed_note = ""
    if observed:
        parts = ", ".join(
            f'{E(row["genre_name"])} ({row["event_count"]})' for row in observed)
        observed_note = (
            f'<p class="note">Observed from event history: {parts} - '
            "a suggestion only, nothing here is saved until you check a box "
            "and press Save.</p>"
        )
    return f"""
<h3 style="font-size:13px;margin:14px 0 6px">Dance Genres</h3>
{observed_note}
<form method="post" action="/admin/master-data/VENUE/{venue['venue_id']}/genres">
  <div class="grid">{''.join(boxes)}</div>
  <div class="actions"><button>Save Genres</button></div>
  <p class="note">이 장소에서 실제로 열리는 것으로 확인된 춤 종류만 선택하세요.
  event 하나가 발견됐다고 자동으로 채워지지 않습니다 - 사람이 확인한 것만 저장됩니다.</p>
</form>"""


# --- routes -----------------------------------------------------------------

def _back(entity_type: str, message: str, tone: str = "ok") -> RedirectResponse:
    return admin._back(PAGE.get(entity_type, "/admin"), message, tone)


def _back_to_view(entity_type: str, entity_id: int, raw_return_to: str | None,
                  message: str, tone: str = "ok", *,
                  keep_editing: bool = False) -> RedirectResponse:
    """Back to the list the operator was actually looking at (Section 4).

    The page number, the filters, the search box and the sort all came along
    in ``return_to`` and go straight back out again, so finishing an edit
    never resets the list to its first page. The row that was edited is the
    fragment, so the browser restores the same place in a long table.

    ``keep_editing`` is what a *failed* save does: the row stays open with the
    error above it, so the operator can correct it where they were, rather
    than the row closing as if the edit had gone through.
    """
    view = safe_view(raw_return_to, PAGE.get(entity_type, "/admin"))
    drop = ("msg", "tone") if keep_editing else ("msg", "tone", EDIT_PARAM)
    add = [("msg", message), ("tone", tone)]
    target = _rebuilt(view, drop=drop, add=add,
                      anchor=row_id(entity_type, entity_id))
    return RedirectResponse(target, status_code=303)


def _form_values(entity_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Turn form strings into the types the update helpers expect."""
    wanted: dict[str, Any] = {}
    for key in master_edit.EDITABLE[entity_type]:
        if key not in raw:
            continue
        value = raw[key]
        if key.endswith("_id"):
            wanted[key] = int(value) if str(value).strip() else None
        elif key == "collection_interval_minutes":
            text = str(value).strip()
            if not text.isdigit():
                raise master_edit.EditError("collection interval must be a whole number")
            wanted[key] = int(text)
        elif key == "enabled":
            wanted[key] = str(value) == "1"
        else:
            wanted[key] = value
    return wanted


@router.post("/admin/master-data/{entity_type}/{entity_id}/edit")
async def admin_edit_master_row(
    entity_type: str,
    entity_id: int,
    request: Request,
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    entity_type = entity_type.upper()
    if entity_type not in master_edit.ENTITIES:
        raise HTTPException(status_code=404, detail="unknown entity")

    raw = dict(await request.form())
    return_to = raw.get("return_to")
    with db.connect(admin._settings()) as con:
        try:
            wanted = _form_values(entity_type, raw)
            result = master_edit.apply_edit(
                con, entity_type, entity_id, wanted, reviewer=reviewer,
            )
            con.commit()
        except master_edit.EditError as exc:
            return _back_to_view(entity_type, entity_id, return_to,
                                 f"저장하지 못했습니다: {exc}", "bad", keep_editing=True)
        except Exception as exc:  # pragma: no cover - defensive
            return _back_to_view(entity_type, entity_id, return_to,
                                 f"저장하지 못했습니다: {exc}", "bad", keep_editing=True)

    if not result["changed"]:
        return _back_to_view(entity_type, entity_id, return_to, "변경된 내용이 없습니다")
    fields = ", ".join(result["changed"])
    return _back_to_view(
        entity_type, entity_id, return_to,
        f"{result['entity'].get('name') or entity_id} 수정됨 ({fields})")


@router.post("/admin/master-data/{entity_type}/{entity_id}/enabled")
def admin_toggle_master_row(
    entity_type: str,
    entity_id: int,
    enabled: str = Form("1"),
    return_to: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    entity_type = entity_type.upper()
    if entity_type not in master_edit.ENTITIES:
        raise HTTPException(status_code=404, detail="unknown entity")
    wanted = enabled == "1"
    with db.connect(admin._settings()) as con:
        try:
            result = master_edit.set_enabled(
                con, entity_type, entity_id, wanted, reviewer=reviewer,
            )
            con.commit()
        except master_edit.EditError as exc:
            return _back_to_view(entity_type, entity_id, return_to,
                                 f"변경하지 못했습니다: {exc}", "bad")
    name = result["entity"].get("name") or entity_id
    return _back_to_view(entity_type, entity_id, return_to,
                         f"{name} {'enabled' if wanted else 'disabled'}")


@router.post("/admin/master-data/VENUE/{venue_id}/alias-add")
def admin_add_venue_alias(
    venue_id: int,
    alias: str = Form(...),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    with db.connect(admin._settings()) as con:
        try:
            master_edit.add_alias(con, venue_id, alias, reviewer=reviewer)
            con.commit()
        except master_edit.EditError as exc:
            return _back(master_edit.VENUE, f"alias를 추가하지 못했습니다: {exc}", "bad")
    return _back(master_edit.VENUE, f"alias '{alias.strip()}' 추가됨")


@router.post("/admin/master-data/VENUE/{venue_id}/alias-remove")
def admin_remove_venue_alias(
    venue_id: int,
    venue_alias_id: int = Form(...),
    force: str = Form("0"),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    with db.connect(admin._settings()) as con:
        try:
            removed = master_edit.remove_alias(
                con, venue_alias_id, reviewer=reviewer, force=(force == "1"),
            )
            con.commit()
        except master_edit.EditError as exc:
            return _back(master_edit.VENUE, str(exc), "bad")
    return _back(master_edit.VENUE, f"alias '{removed['alias']['alias']}' 삭제됨")


@router.post("/admin/master-data/VENUE/{venue_id}/genres")
def admin_set_venue_genres(
    venue_id: int,
    genre_ids: list[int] = Form(default=[]),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    with db.connect(admin._settings()) as con:
        try:
            result = master_edit.set_venue_genres(
                con, venue_id, genre_ids, reviewer=reviewer,
            )
            con.commit()
        except master_edit.EditError as exc:
            return _back(master_edit.VENUE, str(exc), "bad")
    parts = []
    if result["added"]:
        parts.append(f"추가: {', '.join(result['added'])}")
    if result["removed"]:
        parts.append(f"삭제: {', '.join(result['removed'])}")
    return _back(master_edit.VENUE, "; ".join(parts) if parts else "변경 없음")


@api.get("/master-data/history")
def api_master_history(entity_type: str | None = None, entity_id: int | None = None,
                       limit: int = 50, _: str = Depends(require_admin)) -> JSONResponse:
    with db.connect(admin._settings(), autocommit=True) as con:
        return admin._dump({
            "actions": master_edit.history(
                con, entity_type=entity_type, entity_id=entity_id, limit=limit,
            )
        })
