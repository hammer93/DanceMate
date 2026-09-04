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
              note: str | None = None) -> str:
    """An inline edit form, opened where the row is listed.

    ``Cancel`` is the browser's own close on a <details> block: nothing has been
    sent, so nothing has to be undone.
    """
    hint = f'<p class="note">{note}</p>' if note else ""
    return f"""
<details class="editrow">
  <summary>{E(summary)}</summary>
  <form method="post" action="/admin/master-data/{E(entity_type)}/{entity_id}/edit">
    <div class="grid">{''.join(fields)}</div>
    {hint}
    <div class="actions">
      <button class="primary">Save Changes</button>
      <span class="note">Cancel: 닫으면 아무것도 저장되지 않습니다</span>
    </div>
  </form>
  {extra}
</details>"""


def toggle_form(entity_type: str, entity_id: int, enabled: bool) -> str:
    """Enable or disable, which is not the same button as delete."""
    return (
        f'<form class="inline" method="post" '
        f'action="/admin/master-data/{E(entity_type)}/{entity_id}/enabled">'
        f'<input type="hidden" name="enabled" value="{"0" if enabled else "1"}">'
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


# --- routes -----------------------------------------------------------------

def _back(entity_type: str, message: str, tone: str = "ok") -> RedirectResponse:
    return admin._back(PAGE.get(entity_type, "/admin"), message, tone)


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
    with db.connect(admin._settings()) as con:
        try:
            wanted = _form_values(entity_type, raw)
            result = master_edit.apply_edit(
                con, entity_type, entity_id, wanted, reviewer=reviewer,
            )
            con.commit()
        except master_edit.EditError as exc:
            return _back(entity_type, f"저장하지 못했습니다: {exc}", "bad")
        except Exception as exc:  # pragma: no cover - defensive
            return _back(entity_type, f"저장하지 못했습니다: {exc}", "bad")

    if not result["changed"]:
        return _back(entity_type, "변경된 내용이 없습니다")
    fields = ", ".join(result["changed"])
    return _back(entity_type,
                 f"{result['entity'].get('name') or entity_id} 수정됨 ({fields})")


@router.post("/admin/master-data/{entity_type}/{entity_id}/enabled")
def admin_toggle_master_row(
    entity_type: str,
    entity_id: int,
    enabled: str = Form("1"),
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
            return _back(entity_type, f"변경하지 못했습니다: {exc}", "bad")
    name = result["entity"].get("name") or entity_id
    return _back(entity_type, f"{name} {'enabled' if wanted else 'disabled'}")


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


@api.get("/master-data/history")
def api_master_history(entity_type: str | None = None, entity_id: int | None = None,
                       limit: int = 50, _: str = Depends(require_admin)) -> JSONResponse:
    with db.connect(admin._settings(), autocommit=True) as con:
        return admin._dump({
            "actions": master_edit.history(
                con, entity_type=entity_type, entity_id=entity_id, limit=limit,
            )
        })
