"""v0.76 admin console pages: Intake, Review, Usage, System.

Split out of `admin.py` so the v0.75 master-data console stays where operators
already know to find it. Shares that module's rendering helpers, authentication
and settings binding — one console, two files.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import (
    acquisition,
    admin,
    candidates,
    content_store,
    health,
    review,
    review_hints,
    usage,
)
from .admin_auth import require_admin

router = APIRouter()
api = APIRouter(prefix="/api/admin", tags=["admin"])

E = html.escape

# Acquisition status -> badge tone. FETCHED_FULL is the only green: a page we
# could not read must never look like one we could.
STATUS_TONE = {
    acquisition.FETCHED_FULL: "ok",
    acquisition.FETCHED_PARTIAL: "warn",
    acquisition.FETCH_PENDING: "muted",
    acquisition.METADATA_ONLY: "muted",
    acquisition.FETCH_BLOCKED: "bad",
    acquisition.FETCH_FAILED: "bad",
    acquisition.LOGIN_REQUIRED: "bad",
    acquisition.UNSUPPORTED: "bad",
}

REVIEW_TONE = {
    "PENDING": "warn",
    "APPROVED": "ok",
    "CONFIRMED": "ok",
    "EDITED": "ok",
    "REJECTED": "bad",
    "DUPLICATE": "muted",
}


def _settings():
    return admin._settings()


def _connection():
    return admin._connection()


# --- intake -----------------------------------------------------------------

@router.get("/admin/intake", response_class=HTMLResponse)
def admin_intake(
    request: Request,
    status: str = "",
    source_id: str = "",
    today: str = "",
    _: str = Depends(require_admin),
) -> HTMLResponse:
    from . import sources as source_master

    with _connection() as con:
        rows = content_store.listing(
            con,
            status=status or None,
            source_id=int(source_id) if source_id else None,
            today_only=bool(today),
            limit=300,
        )
        summary = content_store.summary(con)
        all_sources = source_master.list_sources(con)

    cards = admin._cards([
        ("Items collected", sum(summary["by_status"].values()), "all time"),
        ("Body fetched", summary["fetched"],
         f"avg {summary['average_text_length']} chars, max {summary['max_text_length']}"),
        ("Content fetches today", summary["content_fetches_today"],
         "original-post GETs, not provider API calls"),
        ("Personal data removed", summary["redacted_spans"],
         "phone/account/email spans redacted before storage"),
    ])

    table_rows = []
    for row in rows:
        status_value = row["acquisition_status"]
        link = (
            f'<a href="{E(row["url"])}" target="_blank" rel="noreferrer noopener">source</a>'
            if row.get("url") else "-"
        )
        table_rows.append([
            E(str(row["collected_at"])[:19]),
            E(str(row["platform"])),
            f'<code>{E(row["source_key"])}</code>',
            E(str(row.get("title") or "")[:64]),
            link,
            admin._badge(str(row.get("discovery_mode") or "-").upper(),
                         "ok" if row.get("discovery_mode") == "live" else "warn"),
            admin._badge(status_value, STATUS_TONE.get(status_value, "muted"))
            + (f'<div class="note">{E(str(row.get("acquisition_method") or ""))}</div>'
               if row.get("acquisition_method") else ""),
            f'<span class="num">{row.get("content_length") or 0}</span>',
            admin._badge(row["ingest_state"], "ok" if row["ingest_state"] == "INGESTED" else "muted"),
            f'<a href="/admin/intake/{row["source_item_id"]}">detail</a>',
        ])

    status_options = "".join(
        f'<option value="{s}"{" selected" if status == s else ""}>{s}</option>'
        for s in ("", acquisition.METADATA_ONLY, acquisition.FETCH_PENDING,
                  acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL,
                  acquisition.FETCH_BLOCKED, acquisition.FETCH_FAILED,
                  acquisition.LOGIN_REQUIRED, acquisition.UNSUPPORTED)
    )
    source_options = "".join(
        f'<option value="{s["source_id"]}"{" selected" if source_id == str(s["source_id"]) else ""}>'
        f'{E(s["source_key"])}</option>'
        for s in all_sources
    )
    filters = f"""
<form method="get" action="/admin/intake"><div class="grid">
  <div><label>Acquisition status</label><select name="status">{status_options}</select></div>
  <div><label>Source</label><select name="source_id"><option value="">all</option>{source_options}</select></div>
  <div><label>When</label><select name="today">
      <option value=""{"" if today else " selected"}>all</option>
      <option value="1"{" selected" if today else ""}>today</option></select></div>
</div><div class="actions"><button class="primary">Filter</button>
  <a href="/admin/intake"><button type="button">Reset</button></a></div></form>"""

    body = (
        "<h2>Intake</h2>" + cards
        + '<p class="note">What was actually collected, and how much of each original '
          "post could be read. A search API returns a snippet; the body is fetched "
          "separately and only <code>FETCHED_FULL</code> means the article was obtained.</p>"
        + filters
        + admin._table(
            ["Collected", "Provider", "Source", "Title", "Original", "Discovery",
             "Acquisition", "Chars", "Engine", ""],
            table_rows,
            empty="nothing collected yet",
        )
    )
    return HTMLResponse(admin._page("Intake", "/admin/intake", body, flash=admin._flash(request)))


@router.get("/admin/intake/{source_item_id}", response_class=HTMLResponse)
def admin_intake_detail(
    source_item_id: int, request: Request, _: str = Depends(require_admin)
) -> HTMLResponse:
    with _connection() as con:
        item = content_store.detail(con, source_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="source item not found")

    content = item.get("content") or {}
    raw = item.get("raw") or {}
    snippet = raw.get("body") if isinstance(raw, dict) else None
    status_value = content.get("acquisition_status") or acquisition.METADATA_ONLY

    def field_rows(pairs):
        return admin._table(["Field", "Value"],
                            [[E(k), v] for k, v in pairs], empty="-")

    discovery = field_rows([
        ("Source", f'<code>{E(item["source_key"])}</code> {E(item["source_name"])}'),
        ("Platform", E(item["platform"])),
        ("Discovery mode", admin._badge(str(item.get("discovery_mode") or "-").upper(),
                                        "ok" if item.get("discovery_mode") == "live" else "warn")),
        ("Collected at", E(str(item["collected_at"])[:19])),
        ("Published at", E(str(item.get("published_at") or "-"))),
        ("External id", f'<code>{E(str(item["external_id"])[:80])}</code>'),
        ("Original URL", f'<a href="{E(item["url"])}" target="_blank" rel="noreferrer noopener">'
                         f'{E(item["url"])}</a>' if item.get("url") else "-"),
        ("Engine state", admin._badge(item["ingest_state"],
                                      "ok" if item["ingest_state"] == "INGESTED" else "muted")),
    ])

    acquired = field_rows([
        ("Status", admin._badge(status_value, STATUS_TONE.get(status_value, "muted"))),
        ("Method", E(str(content.get("acquisition_method") or "-"))),
        ("Fetched URL", E(str(content.get("fetched_url") or "-"))),
        ("HTTP status", E(str(content.get("http_status") or "-"))),
        ("Fetched at", E(str(content.get("fetched_at") or "-"))[:19]),
        ("Text length", f'<span class="num">{content.get("content_length") or 0}</span>'),
        ("Content hash", f'<code>{E(str(content.get("content_hash") or "-")[:24])}</code>'),
        ("Attempts", E(str(content.get("attempt_count") or 0))),
        ("Next attempt", E(str(content.get("next_attempt_at") or "no automatic retry"))[:19]),
        ("Redacted spans", E(str(content.get("redacted_spans") or 0))),
        ("Error", E(str(content.get("fetch_error") or "-"))),
    ])

    def block(title: str, text: str | None, note: str) -> str:
        content_html = (
            f'<pre style="white-space:pre-wrap;word-break:break-word;margin:0;'
            f'font:13px/1.6 ui-monospace,monospace">{E(text)}</pre>'
            if text else '<p class="note">not available</p>'
        )
        return (f'<details open><summary>{E(title)}</summary>'
                f'<p class="note">{E(note)}</p>{content_html}</details>')

    body = (
        f"<h2>Intake item {source_item_id}</h2>"
        f"<h2>Discovery</h2>{discovery}"
        f"<h2>Acquisition</h2>{acquired}"
        + block("Search snippet (discovery)", snippet,
                "What the provider's search API returned. Incomplete by definition.")
        + block("Acquired article text", content.get("extracted_text"),
                "Fetched from the original post. Phone numbers, bank accounts and "
                "email addresses are removed before storage.")
        + '<p class="note"><a href="/admin/intake">back to intake</a></p>'
    )
    return HTMLResponse(admin._page(f"Intake {source_item_id}", "/admin/intake", body,
                                    flash=admin._flash(request)))


@router.post("/admin/intake/{source_item_id}/reacquire")
def admin_reacquire(source_item_id: int, _: str = Depends(require_admin)) -> RedirectResponse:
    from scheduler import acquisition_job

    result = acquisition_job.reacquire(_settings(), [source_item_id])
    first = (result.get("results") or [{}])[0]
    tone = "ok" if first.get("status") == acquisition.FETCHED_FULL else "bad"
    return admin._back(
        f"/admin/intake/{source_item_id}",
        f"re-acquired: {first.get('status')} ({first.get('chars', 0)} chars)"[:200],
        tone,
    )


# --- review -----------------------------------------------------------------

def _review_rows(settings, con) -> list[dict[str, Any]]:
    rows = candidates.list_candidates(settings, limit=300)
    states = review.states(con, [r["candidate_id"] for r in rows])
    for row in rows:
        row["review"] = states.get(row["candidate_id"]) or review.state(con, row["candidate_id"])
    return rows


@router.get("/admin/review", response_class=HTMLResponse)
def admin_review(
    request: Request, show: str = "pending", _: str = Depends(require_admin)
) -> HTMLResponse:
    settings = _settings()
    with _connection() as con:
        rows = _review_rows(settings, con)
        metrics = review.metrics(con)

    if show == "pending":
        visible = [
            r for r in rows
            if r["review"]["review_state"] == review.PENDING
            and r["candidate_status"] in review.REVIEWABLE_ENGINE_STATUSES
        ]
    elif show == "reviewed":
        visible = [r for r in rows if r["review"]["review_state"] != review.PENDING]
    else:
        visible = rows

    cards = admin._cards([
        ("Review pending", sum(1 for r in rows if r["review"]["review_state"] == review.PENDING),
         "candidates awaiting a person"),
        ("Approved today", metrics["today"][review.APPROVE], "APPROVE"),
        ("Edited today", metrics["today"][review.EDIT], "EDIT"),
        ("Rejected today", metrics["today"][review.REJECT], "REJECT"),
        ("Duplicate today", metrics["today"][review.DUPLICATE], "DUPLICATE"),
        ("Confirmed today", metrics["today"][review.CONFIRM], "CONFIRM"),
    ])

    table_rows = []
    for row in visible:
        state_value = row["review"]["review_state"]
        table_rows.append([
            f'<a href="/admin/review/{row["candidate_id"]}">{E(str(row.get("event_name") or "-")[:48])}</a>',
            E(str(row.get("event_date") or "-")),
            E(str(row.get("start_time") or "-")),
            E(str(row.get("venue") or "-")),
            admin._badge(row["candidate_status"], row["status_tone"]),
            admin._badge(state_value, REVIEW_TONE.get(state_value, "muted")),
            E(str(row.get("source_id") or "-")),
            f'<a href="/admin/review/{row["candidate_id"]}"><button>Review</button></a>',
        ])

    tabs = " ".join(
        f'<a href="/admin/review?show={key}"><button{" class=primary" if show == key else ""}>'
        f"{label}</button></a>"
        for key, label in (("pending", "Pending"), ("reviewed", "Reviewed"), ("all", "All"))
    )

    body = (
        "<h2>Human Verification</h2>" + cards
        + f'<div class="actions">{tabs}</div>'
        + '<p class="note">A human decision is recorded alongside the engine\'s status, '
          "never instead of it. APPROVE does not grant VERIFIED - only the engine's "
          "evidence gate does that.</p>"
        + admin._table(
            ["Event", "Date", "Start", "Venue", "Engine", "Review", "Source", ""],
            table_rows,
            empty="nothing to review in this view",
        )
    )
    return HTMLResponse(admin._page("Review", "/admin/review", body, flash=admin._flash(request)))


@router.get("/admin/review/{candidate_id}", response_class=HTMLResponse)
def admin_review_detail(
    candidate_id: int, request: Request, _: str = Depends(require_admin)
) -> HTMLResponse:
    settings = _settings()
    with _connection() as con:
        rows = candidates.list_candidates(settings, limit=1000)
        found = next((r for r in rows if r["candidate_id"] == candidate_id), None)
        if found is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        current = review.state(con, candidate_id)
        actions = review.history(con, candidate_id)
        item = None
        if found.get("source_url"):
            with con.cursor() as cur:
                cur.execute(
                    "SELECT source_item_id FROM source_items WHERE url = %s LIMIT 1",
                    (found["source_url"],),
                )
                row = cur.fetchone()
            if row:
                item = content_store.detail(con, row[0])

    merged = review.apply_corrections(found, current)
    content = (item or {}).get("content") or {}
    warnings = review_hints.hints(merged, content.get("extracted_text"))
    raw = (item or {}).get("raw") or {}
    snippet = raw.get("body") if isinstance(raw, dict) else None

    evidence = admin._table(
        ["Field", "Value"],
        [
            ["Source", E(str(found.get("source_id") or "-"))],
            ["Original URL",
             f'<a href="{E(found["source_url"])}" target="_blank" rel="noreferrer noopener">'
             f'Open Source</a>' if found.get("source_url") else "-"],
            ["Collected at", E(str(found.get("collected_at") or "-"))[:19]],
            ["Acquisition", admin._badge(
                content.get("acquisition_status") or acquisition.METADATA_ONLY,
                STATUS_TONE.get(content.get("acquisition_status"), "muted"))],
            ["Fetched at", E(str(content.get("fetched_at") or "-"))[:19]],
            ["Body chars", f'<span class="num">{content.get("content_length") or 0}</span>'],
        ],
        empty="-",
    )

    def text_block(title: str, text: str | None, note: str) -> str:
        inner = (f'<pre style="white-space:pre-wrap;word-break:break-word;margin:0;'
                 f'font:13px/1.6 ui-monospace,monospace">{E(text)}</pre>'
                 if text else '<p class="note">not available</p>')
        return f'<details open><summary>{E(title)}</summary><p class="note">{E(note)}</p>{inner}</details>'

    def value_row(label: str, field: str) -> list[str]:
        engine_value = merged.get(f"engine_{field}")
        shown = E(str(merged.get(field) if merged.get(field) is not None else "-"))
        if engine_value is not None:
            shown += f'<div class="note">engine said: {E(str(engine_value))}</div>'
        return [E(label), shown]

    extracted = admin._table(
        ["Field", "Value"],
        [
            value_row("Event name", "event_name"),
            value_row("Date", "event_date"),
            value_row("Start", "start_time"),
            value_row("End", "end_time"),
            value_row("Venue", "venue"),
            value_row("Fee", "fee"),
            ["Event type", E(str(found.get("event_type") or "-"))],
            ["Engine status", admin._badge(found["candidate_status"], found["status_tone"])],
            ["Review state", admin._badge(current["review_state"],
                                          REVIEW_TONE.get(current["review_state"], "muted"))],
        ],
        empty="-",
    )

    def field_input(name: str, label: str, value: Any) -> str:
        return (f'<div><label>{E(label)}</label>'
                f'<input name="{name}" value="{E(str(value)) if value is not None else ""}"></div>')

    edit_form = f"""
<details><summary>EDIT — correct fields</summary>
<form method="post" action="/admin/review/{candidate_id}/edit"><div class="grid">
  {field_input("event_name", "Event name", merged.get("event_name"))}
  {field_input("event_date", "Date (YYYY-MM-DD)", merged.get("event_date"))}
  {field_input("start_time", "Start (HH:MM)", merged.get("start_time"))}
  {field_input("end_time", "End (HH:MM)", merged.get("end_time"))}
  {field_input("venue", "Venue", merged.get("venue"))}
  {field_input("fee", "Fee", merged.get("fee"))}
  {field_input("genre", "Genre", (current.get("corrected_json") or {}).get("genre"))}
  {field_input("organizer", "Organizer", (current.get("corrected_json") or {}).get("organizer"))}
  {field_input("notes", "Notes", (current.get("corrected_json") or {}).get("notes"))}
</div>
<div><label>Reason</label><input name="reason" placeholder="what you corrected and why"></div>
<div class="actions"><button class="primary">Save correction</button></div>
<p class="note">The engine's own values are kept; your correction is stored alongside them.</p>
</form></details>"""

    def simple_form(action: str, label: str, note: str) -> str:
        return f"""
<form method="post" action="/admin/review/{candidate_id}/{action.lower()}" class="inline">
  <input type="hidden" name="reason" value="">
  <button title="{E(note)}">{E(label)}</button></form>"""

    duplicate_form = f"""
<form method="post" action="/admin/review/{candidate_id}/duplicate" class="inline">
  <input name="duplicate_of_candidate_id" placeholder="duplicate of candidate id" style="width:190px">
  <button>DUPLICATE</button></form>"""

    history_rows = [
        [E(str(a["created_at"])[:19]), admin._badge(a["action"]), E(a["reviewer"]),
         E(str(a.get("reason") or "-")),
         f'<code>{E(str(a.get("after_json") or {}))[:70]}</code>']
        for a in actions
    ]

    body = (
        f"<h2>Review candidate {candidate_id}</h2>"
        "<h2>Evidence</h2>" + evidence
        + text_block("Search snippet (discovery)", snippet,
                     "What the provider's search API returned.")
        + text_block("Acquired article text", content.get("extracted_text"),
                     "Fetched from the original post, personal data removed.")
        + "<h2>Extracted</h2>"
        + (
            "".join(
                f'<p class="flash {"bad" if w["severity"] == review_hints.SEVERITY_WARN else "ok"}">'
                f'{E(w["severity"])} — {E(w["message"])}</p>'
                for w in warnings
            )
            if warnings else ""
        )
        + extracted
        + "<h2>Human action</h2>"
        + '<div class="actions">'
        + simple_form("approve", "APPROVE", "the extracted content is usable as it stands")
        + " " + simple_form("confirm", "CONFIRM", "you have checked the evidence and stand by it")
        + " " + simple_form("reject", "REJECT", "not an event, or the wrong candidate")
        + " " + duplicate_form
        + "</div>"
        + edit_form
        + "<h2>Audit trail</h2>"
        + admin._table(["When", "Action", "Reviewer", "Reason", "Changed"], history_rows,
                       empty="no human action recorded yet")
        + '<p class="note"><a href="/admin/review">back to the queue</a></p>'
    )
    return HTMLResponse(admin._page(f"Review {candidate_id}", "/admin/review", body,
                                    flash=admin._flash(request)))


def _candidate_snapshot(settings, candidate_id: int) -> dict[str, Any]:
    for row in candidates.list_candidates(settings, limit=1000):
        if row["candidate_id"] == candidate_id:
            return {
                "event_name": row.get("event_name"),
                "event_date": row.get("event_date"),
                "start_time": row.get("start_time"),
                "end_time": row.get("end_time"),
                "venue": row.get("venue"),
                "fee": row.get("fee"),
            }
    return {}


@router.post("/admin/review/{candidate_id}/{action}")
def admin_review_action(
    candidate_id: int,
    action: str,
    reason: str = Form(""),
    duplicate_of_candidate_id: str = Form(""),
    event_name: str = Form(None),
    event_date: str = Form(None),
    start_time: str = Form(None),
    end_time: str = Form(None),
    venue: str = Form(None),
    fee: str = Form(None),
    genre: str = Form(None),
    organizer: str = Form(None),
    notes: str = Form(None),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    action_name = action.upper()
    if action_name not in review.ACTIONS:
        raise HTTPException(status_code=404, detail="unknown review action")

    settings = _settings()
    before = _candidate_snapshot(settings, candidate_id)
    after = None
    if action_name == review.EDIT:
        after = {
            "event_name": event_name, "event_date": event_date,
            "start_time": start_time, "end_time": end_time,
            "venue": venue, "fee": fee, "genre": genre,
            "organizer": organizer, "notes": notes,
        }

    try:
        with _connection() as con:
            review.record(
                con, candidate_id=candidate_id, action=action_name,
                before=before, after=after, reason=reason.strip() or None,
                duplicate_of_candidate_id=(
                    int(duplicate_of_candidate_id) if duplicate_of_candidate_id.strip() else None
                ),
            )
    except review.ReviewError as exc:
        return admin._back(f"/admin/review/{candidate_id}", str(exc), "bad")
    except Exception as exc:
        return admin._back(f"/admin/review/{candidate_id}", f"could not record: {exc}", "bad")
    return admin._back(f"/admin/review/{candidate_id}", f"{action_name} recorded")


# --- usage ------------------------------------------------------------------

@router.get("/admin/usage", response_class=HTMLResponse)
def admin_usage(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    snapshot = usage.snapshot(_settings())
    if not snapshot.get("available"):
        body = f'<p class="flash bad">usage unavailable: {E(str(snapshot.get("detail")))}</p>'
        return HTMLResponse(admin._page("Usage", "/admin/usage", body))

    today_rows = []
    for row in snapshot["today"]:
        quota = row["quota"]
        cost = row["cost"]
        quota_cell = (
            f'{quota["used"]} / {quota["limit"]}'
            if quota["limit"] is not None else f'{quota["used"]} / unknown'
        )
        today_rows.append([
            E(row["provider"]), f'<code>{E(row["api_name"])}</code>',
            f'<span class="num">{row["request_count"]}</span>',
            f'<span class="num">{row["success_count"]}</span>',
            f'<span class="num">{row["error_count"]}</span>',
            f'<span class="num">{row["item_count"]}</span>',
            f'<span class="num">{row["new_item_count"]}</span>',
            f'<span class="num">{row["duplicate_item_count"]}</span>',
            quota_cell + f'<div class="note">{E(quota["status"])}</div>',
            admin._badge(cost["status"], "muted" if cost["status"] != "PAID" else "warn")
            + (f'<div class="note">{cost["amount"]} {E(str(cost["currency"] or ""))}</div>'
               if cost["amount"] is not None else
               '<div class="note">no verified pricing</div>'),
            admin._badge(row.get("last_status") or "-",
                         "ok" if row.get("last_status") == "PASS" else "muted"),
        ])

    mtd = snapshot["month_to_date"]
    mtd_rows = [
        [E(r["provider"]), f'<span class="num">{r["requests"] or 0}</span>',
         f'<span class="num">{r["success"] or 0}</span>',
         f'<span class="num">{r["errors"] or 0}</span>',
         f'<span class="num">{r["items"] or 0}</span>',
         f'<span class="num">{r["new_items"] or 0}</span>']
        for r in mtd["by_provider"]
    ]

    fetches = snapshot["content_fetches"]
    eff = snapshot["efficiency"]
    cards = admin._cards([
        ("API requests today", sum(r["request_count"] for r in snapshot["today"]),
         "provider search API calls"),
        ("Content fetches today", fetches["total"],
         f'{fetches["succeeded"]} produced text - no provider quota'),
        ("New items / request", eff["new_items_per_request"] if eff["new_items_per_request"] is not None else "-",
         f'{eff["new_items"]} new from {eff["api_requests"]} requests'),
        ("Month to date", mtd["totals"]["requests"],
         f'{mtd["totals"]["new_items"]} new items'),
    ])

    body = (
        "<h2>Provider usage — today (UTC)</h2>" + cards
        + admin._table(
            ["Provider", "API", "Requests", "Success", "Errors", "Items", "New",
             "Duplicate", "Quota", "Cost", "Last"],
            today_rows, empty="no provider configured",
        )
        + '<p class="note">Quota shows where the figure came from: CONFIGURED is a budget '
          "we set ourselves, DOCUMENTED comes from the provider's published limits. "
          "Cost is UNKNOWN unless the pricing was actually verified — an absent invoice "
          "is not evidence of FREE.</p>"
        + "<h2>Content fetches — today</h2>"
        + admin._table(
            ["Host", "Fetches"],
            [[E(h["host"]), f'<span class="num">{h["fetches"]}</span>'] for h in fetches["by_host"]],
            empty="no original post fetched today",
        )
        + '<p class="note">Fetching an original post costs no provider API quota. '
          "These are counted separately so the two can never be confused.</p>"
        + f"<h2>Month to date ({mtd['from']} — {mtd['to']})</h2>"
        + admin._table(["Provider", "Requests", "Success", "Errors", "Items", "New"],
                       mtd_rows, empty="no usage this month")
    )
    return HTMLResponse(admin._page("Usage", "/admin/usage", body, flash=admin._flash(request)))


# --- system -----------------------------------------------------------------

@router.get("/admin/system", response_class=HTMLResponse)
def admin_system(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    settings = _settings()
    payload = health.collect(settings)
    verdict = health.overall(payload)

    rows = []
    for key, label in (("runtime", "Runtime"), ("database", "Database"),
                       ("scheduler", "Scheduler"), ("information", "Information Engine"),
                       ("storage", "Storage"), ("backup", "Backup")):
        component = payload.get(key, {})
        status_value = component.get("status", "FAIL")
        tone = {"PASS": "ok", "WARN": "warn"}.get(status_value, "bad")
        rows.append([E(label), admin._badge(status_value, tone),
                     E(str(component.get("detail", ""))[:140])])

    body = (
        "<h2>System</h2>"
        + admin._cards([
            ("Overall", verdict, "worst component wins"),
            ("Runtime version", settings.version, f"engine v{settings.engine_version}"),
            ("Environment", settings.env, "LAN only"),
        ])
        + admin._table(["Component", "Status", "Detail"], rows, empty="no status")
        + '<p class="note">The same six components <code>scripts/check-server.sh</code> '
          "reports. Machine-readable at <code>/status</code>, "
          "<code>/status/summary</code> and <code>/health</code>.</p>"
    )
    return HTMLResponse(admin._page("System", "/admin/system", body, flash=admin._flash(request)))


# --- JSON API ---------------------------------------------------------------

@api.get("/intake")
def api_intake_v2(limit: int = 200, _: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return admin._dump({
            "summary": content_store.summary(con),
            "items": content_store.listing(con, limit=limit),
        })


@api.get("/intake/{source_item_id}")
def api_intake_detail(source_item_id: int, _: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        found = content_store.detail(con, source_item_id)
    if found is None:
        raise HTTPException(status_code=404, detail="source item not found")
    return admin._dump(found)


@api.get("/review")
def api_review(_: str = Depends(require_admin)) -> JSONResponse:
    settings = _settings()
    with _connection() as con:
        return admin._dump({
            "metrics": review.metrics(con),
            "candidates": _review_rows(settings, con),
        })


@api.post("/review/{candidate_id}")
def api_review_action(
    candidate_id: int, payload: dict[str, Any], _: str = Depends(require_admin)
) -> JSONResponse:
    settings = _settings()
    action = str(payload.get("action", "")).upper()
    try:
        with _connection() as con:
            recorded = review.record(
                con, candidate_id=candidate_id, action=action,
                reviewer=str(payload.get("reviewer") or "admin"),
                before=_candidate_snapshot(settings, candidate_id),
                after=payload.get("fields"),
                reason=payload.get("reason"),
                duplicate_of_candidate_id=payload.get("duplicate_of_candidate_id"),
            )
    except review.ReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return admin._dump(recorded)


@api.get("/usage")
def api_usage(_: str = Depends(require_admin)) -> JSONResponse:
    return admin._dump(usage.snapshot(_settings()))
