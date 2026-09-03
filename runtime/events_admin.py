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

from . import admin, duplicates, events_api, master_data, normalization
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

@router.get("/admin/venues/unresolved", response_class=HTMLResponse)
def admin_unresolved_venues(request: Request,
                            _: str = Depends(require_admin)) -> HTMLResponse:
    with _connection() as con:
        pending = normalization.unresolved_venues(con)
        venues = master_data.list_venues(con, enabled_only=True)

    options = "".join(
        f'<option value="{v["venue_id"]}">{E(v["name"])}'
        + (f' ({E(v["region_name"])})' if v.get("region_name") else "")
        + "</option>"
        for v in venues
    )

    rows = []
    for entry in pending:
        aliases = ", ".join(E(str(a)) for a in (entry.get("alias_candidates") or []))
        form = (
            f'<form method="post" action="/admin/venues/unresolved/{entry["unresolved_venue_id"]}" '
            'class="inline">'
            f'<select name="venue_id"><option value="">choose a venue</option>{options}</select> '
            '<button class="primary" name="action" value="link">Link</button> '
            '<button name="action" value="dismiss">Not a venue</button>'
            "</form>"
        )
        rows.append([
            E(entry["venue_text"]),
            aliases or "-",
            str(entry.get("event_count") or 0),
            E(str(entry["first_seen_at"])[:16]),
            form,
        ])

    note = (
        '<p class="note">These are strings the extractor read from a post that '
        "the Venue Master does not recognise. Linking one records it as an "
        "alias and re-resolves every event waiting on it. Nothing here is "
        "registered automatically: a misread line must not become a venue.</p>"
    )
    body = ("<h2>Unresolved Venues</h2>" + note + admin._table(
        ["Read from the post", "Also tried", "Events waiting", "First seen", "Decide"], rows,
        empty="every venue we have read is recognised",
    ))
    return HTMLResponse(admin._page("Unresolved Venues", "/admin/venues", body,
                                    flash=admin._flash(request)))


@router.post("/admin/venues/unresolved/{unresolved_venue_id}")
def admin_resolve_venue(
    unresolved_venue_id: int,
    action: str = Form(...),
    venue_id: str = Form(""),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    target = "/admin/venues/unresolved"
    try:
        with _connection() as con:
            if action == "dismiss":
                normalization.dismiss_unresolved_venue(con, unresolved_venue_id)
                return admin._back(target, "recorded as not a venue")
            if not venue_id:
                return admin._back(target, "choose a venue to link to", "bad")
            result = normalization.link_unresolved_venue(
                con, unresolved_venue_id, int(venue_id),
            )
    except Exception as exc:
        return admin._back(target, f"could not resolve: {exc}", "bad")
    return admin._back(target, f"linked; {result['events_updated']} event(s) updated")


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
