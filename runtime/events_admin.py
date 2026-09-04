"""v0.77 console pages: Events, Unresolved Venues, Duplicates.

Two of these exist because automation deliberately stopped short.

    Unresolved Venues -- the extractor read a place name off a post and the
    Venue Master does not know it. Registering it automatically would turn a
    typo, a landmark or a misread line into a permanent master record, so it
    waits here for someone to say "yes, that is that studio" or "no, that is
    not a venue at all".

    Duplicates -- the rules merged what they could settle and stopped at the
    pairs they could not. Same venue, three hours apart: that is either one
    event posted twice with a corrected time, or two events in one studio on a
    Saturday night. Only a person can tell, and their answer is final.

Shares admin.py's rendering, authentication and settings binding.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import (
    admin,
    db,
    duplicates,
    events_api,
    master_data,
    normalization,
    venue_resolution,
)
from .admin_auth import require_admin

router = APIRouter()
api = APIRouter(prefix="/api/admin", tags=["admin"])

E = html.escape

VENUE_TONE = {
    normalization.VENUE_RESOLVED: "ok",
    normalization.VENUE_UNRESOLVED: "warn",
    normalization.VENUE_ABSENT: "muted",
}


def _connection():
    return admin._connection()


def _clock(value: Any) -> str:
    if value is None:
        return "-"
    return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)[:5]


# --- events -----------------------------------------------------------------

@router.get("/admin/events", response_class=HTMLResponse)
def admin_events(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    with _connection() as con:
        summary = normalization.metrics(con)
        duplicate_summary = duplicates.metrics(con)
        with con.cursor() as cur:
            cur.execute(
                "SELECT e.*, v.name AS venue_name FROM events e "
                "LEFT JOIN venues v ON v.venue_id = e.venue_id "
                "ORDER BY e.event_date DESC, e.start_time NULLS LAST, e.event_id "
                "LIMIT 200"
            )
            names = [c.name for c in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]

    table = admin._table(
        ["Date", "Time", "Event", "Venue", "Fee", "Engine", "Review", "Source", "Listing"],
        [
            [
                E(str(row["event_date"])),
                E(_clock(row["start_time"]) + " - " + _clock(row["end_time"])
                  + ("+1" if row["end_day_offset"] else "")),
                E(row["event_name"] or "-"),
                (E(row["venue_name"] or row["venue_text"] or "-") + " "
                 + admin._badge(row["venue_status"],
                                VENUE_TONE.get(row["venue_status"], "muted"))),
                f'{row["fee"]:,}' if row["fee"] is not None else "-",
                admin._badge(row["engine_status"],
                             "ok" if row["engine_status"] == "VERIFIED" else "warn"),
                E(row["review_state"]),
                admin._badge(row["provenance"],
                             "ok" if row["provenance"] == "LIVE" else "muted"),
                (admin._badge("DUPLICATE", "muted")
                 if row["canonical_event_id"] else admin._badge(row["listing_state"],
                     "ok" if row["listing_state"] == "LISTED" else "muted")),
            ]
            for row in rows
        ],
        empty="no event normalised yet - run the event-normalization job",
    )

    cards = admin._cards([
        ("Events normalised", summary["total"], "one row per engine candidate"),
        ("Live", summary["live"], "traced to a live collection"),
        ("Listed to users", summary["listed"], "live, canonical, not rejected"),
        ("Venue resolved", summary["venue_resolved"], "matched to the Venue Master"),
        ("Venue unresolved", summary["venue_unresolved"],
         "read from a post, not recognised"),
        ("With a time", summary["with_time"], "start time extracted"),
        ("With a fee", summary["with_fee"], "fee extracted"),
        ("Auto-merged", duplicate_summary["auto_merged"],
         "same date, venue and start time"),
        ("Pairs for review", duplicate_summary["open_pairs"], "waiting on a person"),
    ])

    note = (
        '<p class="note">Only LIVE events appear on the user surface. A '
        "snapshot replay and a PoC fixture stay here and nowhere else.</p>"
    )
    body = "<h2>Events</h2>" + cards + note + table
    return HTMLResponse(admin._page("Events", "/admin/events", body,
                                    flash=admin._flash(request)))


# --- unresolved venues ------------------------------------------------------
#
# The one screen where a venue string becomes a venue. Everything needed to
# decide is here -- what the post said, whether we already know the place, and
# a form prefilled from the string itself -- because the alternative was a trip
# to /admin/venues and back, and an operator who has left the queue to create a
# venue has lost the context they were about to use it for.
#
# No JavaScript framework. The New Venue form and the Not-a-venue confirmation
# are <details> blocks, which work with scripting off and need nothing loaded.

def _source_context(entry: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    """The posts this string came from, with a line of surrounding text.

    "OCHO" could be a studio or the name of the event. Only the post says
    which, so the post is one click away and a snippet is already on screen.
    """
    if not sources:
        return ('<p class="note">No post is currently waiting on this string — '
                "it may already have been resolved or re-extracted.</p>")
    items = []
    for source in sources:
        link = (f'<a href="{E(source["source_url"])}" target="_blank" '
                f'rel="nofollow noopener">원문 보기</a>'
                if source.get("source_url") else '<span class="muted">no link</span>')
        snippet = (f'<div class="snippet">{E(source["snippet"])}</div>'
                   if source.get("snippet") else
                   '<div class="snippet">(본문에서 해당 문자열 주변을 찾지 못했습니다)</div>')
        items.append(
            f'<li><strong>{E(str(source["event_date"]))}</strong> '
            f'{E((source["event_name"] or "")[:60])} &middot; {link}{snippet}</li>'
        )
    return f'<ul class="sources">{"".join(items)}</ul>'


def _new_venue_form(entry: dict[str, Any], suggestion: dict[str, Any],
                    regions: list[dict[str, Any]], region_id: int | None,
                    *, open_form: bool = False, force: bool = False) -> str:
    """The New Venue form, prefilled from the raw string. Nothing is saved yet."""
    options = "".join(
        f'<option value="{r["region_id"]}"'
        + (" selected" if region_id == r["region_id"] else "")
        + f">{E(r['name'])}</option>"
        for r in regions
    )
    aliases = ", ".join(suggestion["aliases"])
    source = suggestion.get("address_source")
    told = []
    if suggestion["split_inferred"]:
        told.append("이름과 주소는 원문 문자열에서 나눈 값입니다")
    if source == "the post":
        told.append("주소는 게시글 본문에서 가져왔습니다")
    if suggestion.get("region_id"):
        told.append("지역은 주소를 보고 선택했습니다")
    inferred = (
        f'<p class="note">{E(", ".join(told))}. 저장 전에 확인하고, 틀렸으면 '
        "고치거나 지우세요.</p>" if told else ""
    )
    return f"""
<details class="newvenue"{' open' if open_form else ''}>
  <summary>New Venue</summary>
  <form method="post" action="/admin/venues/unresolved/{entry['unresolved_venue_id']}/create">
    <div class="grid">
      <div><label>Name</label>
        <input name="name" value="{E(suggestion['name'])}" required></div>
      <div><label>Region</label>
        <select name="region_id"><option value="">-</option>{options}</select></div>
      <div><label>Address</label>
        <input name="address" value="{E(suggestion['address'] or '')}"></div>
      <div><label>Aliases (comma separated)</label>
        <input name="aliases" value="{E(aliases)}"></div>
      <div><label>Notes</label><input name="notes"></div>
    </div>
    {inferred}
    <p class="note">원문 문자열 <code>{E(entry['venue_text'])}</code> 은 자동으로
    alias에 포함됩니다 — 다음 수집부터 이 표현이 바로 인식됩니다.</p>
    <div class="actions">
      <input type="hidden" name="force" value="{'1' if force else '0'}">
      <button class="primary">Create &amp; Link</button>
    </div>
  </form>
</details>"""


@router.get("/admin/venues/unresolved", response_class=HTMLResponse)
def admin_unresolved_venues(request: Request,
                            _: str = Depends(require_admin)) -> HTMLResponse:
    with _connection() as con:
        pending = normalization.unresolved_venues(con)
        venues = master_data.list_venues(con, enabled_only=True)
        regions = master_data.list_regions(con, enabled_only=True)
        contexts = {
            entry["unresolved_venue_id"]: venue_resolution.context(con, entry["venue_text"])
            for entry in pending
        }
        suggestions = {
            entry["unresolved_venue_id"]: venue_resolution.prefill(con, entry)
            for entry in pending
        }
        region_ids = {key: s["region_id"] for key, s in suggestions.items()}

    options = "".join(
        f'<option value="{v["venue_id"]}">{E(v["name"])}'
        + (f' ({E(v["region_name"])})' if v.get("region_name") else "")
        + "</option>"
        for v in venues
    )

    banner = "" if venues else (
        '<div class="callout"><h3>등록된 장소가 아직 없습니다</h3>'
        "<p>여기서 바로 만들 수 있습니다. 아래 항목의 <strong>New Venue</strong>를 "
        "누르면 원문 문자열로 채워진 양식이 열리고, 저장과 동시에 대기 중인 "
        "Event가 정리됩니다. Venues 화면으로 옮겨갈 필요가 없습니다.</p></div>"
    )

    items = []
    for entry in pending:
        key = entry["unresolved_venue_id"]
        also = ", ".join(E(str(a)) for a in (entry.get("alias_candidates") or [])
                         if str(a) != entry["venue_text"])
        if venues:
            link_form = (
                f'<form class="inline" method="post" '
                f'action="/admin/venues/unresolved/{key}/link">'
                f'<select name="venue_id" required>'
                f'<option value="">기존 장소 선택…</option>{options}</select>'
                '<button class="primary">Link Existing</button></form>'
            )
        else:
            link_form = ('<span class="badge muted">No venues registered yet</span>')

        live = entry.get("live_event_count") or 0
        # A string only a fixture ever produced has no post to read, and a
        # decision about it changes nothing a dancer sees. Say so rather than
        # letting it sit in the queue looking like the others.
        live_note = (f" (live {live}건)" if live and live != (entry.get("event_count") or 0)
                     else "" if live else
                     ' <span class="badge muted">live 게시글 없음</span>')

        dismiss_form = f"""
<details>
  <summary>Not a venue</summary>
  <form method="post" action="/admin/venues/unresolved/{key}/dismiss">
    <p class="note">이 문자열을 장소가 아닌 것으로 처리합니다. 원문과 근거는
    삭제되지 않고, 이 문자열만 대기열에서 내려갑니다.</p>
    <div><label>사유 (선택)</label>
      <input name="reason" placeholder="행사명 / 건물 층수 / 오추출 등"></div>
    <div class="actions"><button>확인, 장소가 아닙니다</button></div>
  </form>
</details>"""

        items.append(f"""
<section class="item">
  <div class="raw">{E(entry['venue_text'])}</div>
  <div class="facts">
    <span>대기 중 Event {entry.get('event_count') or 0}건{live_note}</span>
    <span>처음 발견 {E(str(entry['first_seen_at'])[:16])}</span>
    {f'<span>Also tried: {also}</span>' if also else ''}
  </div>
  {_source_context(entry, contexts[key])}
  <div class="actionbar">
    {link_form}
    {_new_venue_form(entry, suggestions[key], regions, region_ids[key])}
    {dismiss_form}
  </div>
</section>""")

    note = (
        '<p class="note">이 문자열들은 추출기가 게시글에서 읽었지만 Venue Master가 '
        "알지 못하는 것입니다. 연결하면 alias로 기록되어 대기 중 Event가 즉시 "
        "정리되고, 다음 수집부터 자동으로 인식됩니다. 자동 등록은 하지 않습니다 — "
        "잘못 읽은 한 줄이 영구 마스터 레코드가 되면 안 됩니다.</p>"
    )
    body = ("<h2>Unresolved Venues</h2>" + banner + note
            + (f'<div class="queue">{"".join(items)}</div>' if items
               else '<div class="tablewrap"><table><tbody><tr><td>'
                    "every venue we have read is recognised</td></tr></tbody></table></div>"))
    return HTMLResponse(admin._page("Unresolved Venues", "/admin/venues", body,
                                    flash=admin._flash(request)))


def _duplicate_warning_page(entry: dict[str, Any], matches: list[dict[str, Any]],
                            form: dict[str, Any], regions: list[dict[str, Any]],
                            region_id: int | None) -> HTMLResponse:
    """Ask before creating a second row for a place we may already have.

    Not a refusal: the operator may well know these are different places. It
    stops here so that is a decision rather than an accident.
    """
    key = entry["unresolved_venue_id"]
    rows = "".join(
        f'<li><strong>{E(m["name"])}</strong>'
        + (f' &middot; {E(m["region_name"])}' if m.get("region_name") else "")
        + (f' &middot; {E(m["address"])}' if m.get("address") else "")
        + f' &middot; <span class="muted">{E(", ".join(m["match_reasons"]))}</span> '
        + f'<form class="inline" method="post" '
        f'action="/admin/venues/unresolved/{key}/link">'
        f'<input type="hidden" name="venue_id" value="{m["venue_id"]}">'
        f'<button class="primary">Link Existing</button></form></li>'
        for m in matches
    )
    suggestion = {
        "name": form["name"], "address": form["address"] or None,
        "aliases": form["aliases"], "split_inferred": False,
    }
    body = (
        "<h2>Unresolved Venues</h2>"
        '<div class="callout"><h3>비슷한 장소가 이미 등록되어 있습니다</h3>'
        f'<p>원문 문자열: <code>{E(entry["venue_text"])}</code></p>'
        f'<ul class="sources">{rows}</ul>'
        "<p class=\"note\">같은 장소라면 위에서 연결하세요. 정말 다른 장소라면 "
        "아래 양식에서 그대로 저장하면 됩니다.</p></div>"
        + _new_venue_form(entry, suggestion, regions, region_id,
                          open_form=True, force=True)
        + '<p class="note"><a href="/admin/venues/unresolved">← 대기열로 돌아가기</a></p>'
    )
    return HTMLResponse(admin._page("Unresolved Venues", "/admin/venues", body),
                        status_code=409)


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/create")
def admin_create_and_link_venue(
    unresolved_venue_id: int,
    name: str = Form(...),
    region_id: str = Form(""),
    address: str = Form(""),
    aliases: str = Form(""),
    notes: str = Form(""),
    force: str = Form("0"),
    reviewer: str = Depends(require_admin),
) -> Any:
    target = "/admin/venues/unresolved"
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
    # Not autocommit: create-venue, alias and link commit together or not at all.
    with db.connect(admin._settings()) as con:
        try:
            result = venue_resolution.create_and_link(
                con, unresolved_venue_id=unresolved_venue_id, name=name,
                region_id=int(region_id) if region_id else None,
                address=address, notes=notes, aliases=alias_list,
                reviewer=reviewer, force=(force == "1"),
            )
            con.commit()
        except venue_resolution.DuplicateVenue as duplicate:
            entry = normalization.unresolved_venue(con, unresolved_venue_id)
            regions = master_data.list_regions(con, enabled_only=True)
            return _duplicate_warning_page(
                entry, duplicate.matches,
                {"name": name, "address": address, "aliases": alias_list},
                regions, int(region_id) if region_id else None,
            )
        except Exception as exc:
            return admin._back(target, f"could not create venue: {exc}", "bad")
    return admin._back(
        target,
        f"created {result['venue']['name']} and resolved "
        f"{result['events_updated']} event(s)",
    )


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/link")
def admin_link_existing_venue(
    unresolved_venue_id: int,
    venue_id: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    target = "/admin/venues/unresolved"
    if not venue_id:
        return admin._back(target, "연결할 장소를 선택하세요", "bad")
    with db.connect(admin._settings()) as con:
        try:
            result = venue_resolution.link_existing(
                con, unresolved_venue_id=unresolved_venue_id,
                venue_id=int(venue_id), reviewer=reviewer,
            )
            con.commit()
        except Exception as exc:
            return admin._back(target, f"could not link: {exc}", "bad")
    return admin._back(
        target,
        f"linked to {result['venue']['name']}; "
        f"{result['events_updated']} event(s) resolved",
    )


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/dismiss")
def admin_dismiss_venue(
    unresolved_venue_id: int,
    reason: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    target = "/admin/venues/unresolved"
    with db.connect(admin._settings()) as con:
        try:
            venue_resolution.dismiss(
                con, unresolved_venue_id=unresolved_venue_id, reviewer=reviewer,
                reason=reason.strip() or None,
            )
            con.commit()
        except Exception as exc:
            return admin._back(target, f"could not dismiss: {exc}", "bad")
    return admin._back(target, "장소가 아닌 것으로 기록했습니다")


# --- duplicates -------------------------------------------------------------

@router.get("/admin/duplicates", response_class=HTMLResponse)
def admin_duplicates(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    with _connection() as con:
        pairs = duplicates.open_pairs(con)
        summary = duplicates.metrics(con)

    rows = []
    for pair in pairs:
        left = (f'<strong>#{pair["event_id"]}</strong> {E(pair["event_name"] or "")}<br>'
                f'{E(_clock(pair["start_time"]))} · {E(pair["venue_text"] or "-")}')
        right = (f'<strong>#{pair["other_event_id"]}</strong> {E(pair["other_event_name"] or "")}<br>'
                 f'{E(_clock(pair["other_start_time"]))} · {E(pair["other_venue_text"] or "-")}')
        form = (
            f'<form method="post" action="/admin/duplicates/{pair["pair_id"]}" class="inline">'
            f'<button class="primary" name="action" value="keep_{pair["event_id"]}">'
            f'Same event, keep #{pair["event_id"]}</button> '
            f'<button class="primary" name="action" value="keep_{pair["other_event_id"]}">'
            f'Same event, keep #{pair["other_event_id"]}</button> '
            '<button name="action" value="distinct">Different events</button>'
            "</form>"
        )
        rows.append([
            E(str(pair["event_date"])),
            left, right,
            E(", ".join(pair["matched"])),
            E(", ".join(pair["differs"])),
            form,
        ])

    cards = admin._cards([
        ("Auto-merged", summary["auto_merged"], "by rule, no judgement call"),
        ("Decided by a person", summary["human_decided"], "final; never revisited"),
        ("Waiting on you", summary["open_pairs"], "the rules could not settle these"),
        ("Listed", summary["listed"], "shown on the user surface"),
    ])

    note = (
        '<p class="note">The rules merge only what they can settle outright: '
        "same date, same venue, same start time. These pairs matched on some of "
        "that and not the rest. Your answer is final - the scan will not "
        "revisit a pair you have decided.</p>"
    )
    body = ("<h2>Duplicates</h2>" + cards + note + admin._table(
        ["Date", "Event", "Other", "Matched", "Differs", "Decide"], rows,
        empty="nothing ambiguous - the rules settled everything they found",
    ))
    return HTMLResponse(admin._page("Duplicates", "/admin/duplicates", body,
                                    flash=admin._flash(request)))


@router.post("/admin/duplicates/{pair_id}")
def admin_resolve_duplicate(
    pair_id: int,
    action: str = Form(...),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    target = "/admin/duplicates"
    try:
        with _connection() as con:
            if action == "distinct":
                duplicates.resolve_pair(con, pair_id, decision=duplicates.DISTINCT)
                return admin._back(target, "recorded as different events")
            if not action.startswith("keep_"):
                return admin._back(target, f"unknown action {action}", "bad")
            canonical = int(action.removeprefix("keep_"))
            result = duplicates.resolve_pair(
                con, pair_id, decision=duplicates.DUPLICATE,
                canonical_event_id=canonical,
            )
    except Exception as exc:
        return admin._back(target, f"could not resolve: {exc}", "bad")
    return admin._back(target, f"merged into #{result['canonical_event_id']}")


# --- JSON -------------------------------------------------------------------

@api.get("/events/metrics")
def api_event_metrics(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return admin._dump({
            "events": normalization.metrics(con),
            "duplicates": duplicates.metrics(con),
        })


@api.get("/venues/unresolved")
def api_unresolved_venues(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return admin._dump({"unresolved": normalization.unresolved_venues(con)})


@api.post("/events/reextract")
def api_reextract(limit: int = 50, _: str = Depends(require_admin)) -> JSONResponse:
    """Re-run the current engine over every post whose body we already hold.

    For an engine version bump: the stored candidates were extracted by the
    previous version and nothing about the article says so. Candidates a person
    has acted on are skipped, so this cannot overwrite a review.
    """
    from . import engine_ingest

    return admin._dump(
        engine_ingest.reprocess_acquired(admin._settings(), limit=limit, force=True)
    )


@api.post("/events/normalize")
def api_normalize(_: str = Depends(require_admin)) -> JSONResponse:
    """Rebuild the event rows now, rather than waiting for the next tick."""
    built = normalization.normalize_all(admin._settings())
    with _connection() as con:
        found = duplicates.scan(con)
    return admin._dump({"normalized": built, "duplicates": found})


@api.get("/events/search-preview")
def api_search_preview(when: str = "today", _: str = Depends(require_admin)) -> JSONResponse:
    """What the user surface would return right now, for an operator check."""
    try:
        with _connection() as con:
            return admin._dump(events_api.search(con, when=when.strip()))
    except events_api.SearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# --- removing a venue -------------------------------------------------------
#
# The listing lives on the v0.75 master-data page; the removal machinery is
# venue resolution, so the routes live here beside the rest of it.

@router.post("/admin/venues/{venue_id}/delete")
def admin_delete_venue(
    venue_id: int,
    unlink: str = Form("0"),
    reviewer: str = Depends(require_admin),
) -> Any:
    target = "/admin/venues"
    with db.connect(admin._settings()) as con:
        try:
            result = venue_resolution.delete_venue(
                con, venue_id, reviewer=reviewer, unlink=(unlink == "1"),
            )
            con.commit()
        except venue_resolution.VenueInUse as in_use:
            # Reached only if the page was stale: the button that offers a plain
            # delete is not rendered for a venue in use.
            return admin._back(
                target,
                f"이 장소는 Event {in_use.usage['events']}건에서 사용 중입니다 — "
                "Unlink & Delete 를 사용하세요",
                "bad",
            )
        except Exception as exc:
            return admin._back(target, f"could not delete venue: {exc}", "bad")

    detail = f"deleted {result['venue']['name']}"
    if result["events_unlinked"]:
        detail += (f"; {result['events_unlinked']} event(s) back to their raw string, "
                   f"{result['strings_requeued']} queued for review")
    if result["automatic_merges_released"]:
        detail += f"; {result['automatic_merges_released']} automatic merge(s) released"
    return admin._back(target, detail)


@router.post("/admin/venues/{venue_id}/enabled")
def admin_set_venue_enabled(
    venue_id: int,
    enabled: str = Form("1"),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    target = "/admin/venues"
    wanted = enabled == "1"
    with db.connect(admin._settings()) as con:
        try:
            result = venue_resolution.set_venue_enabled(
                con, venue_id, wanted, reviewer=reviewer,
            )
            con.commit()
        except Exception as exc:
            return admin._back(target, f"could not update venue: {exc}", "bad")
    return admin._back(
        target,
        f"{result['venue']['name']} {'reactivated' if wanted else 'deactivated'}",
    )


@api.get("/venues/{venue_id}/usage")
def api_venue_usage(venue_id: int, _: str = Depends(require_admin)) -> JSONResponse:
    """What would change if this venue were deleted."""
    with _connection() as con:
        return admin._dump({"venue_id": venue_id, "usage": venue_resolution.usage(con, venue_id)})


@api.get("/venues/history")
def api_venue_history(limit: int = 50, _: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return admin._dump({"actions": venue_resolution.history(con, limit=limit)})
