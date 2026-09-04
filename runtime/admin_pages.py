"""v0.76 admin console pages: Intake, Review, Usage, System.

Split out of `admin.py` so the v0.75 master-data console stays where operators
already know to find it. Shares that module's rendering helpers, authentication
and settings binding — one console, two files.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import (
    acquisition,
    events_api,
    admin,
    candidates,
    content_store,
    health,
    image_fallback,
    review,
    review_hints,
    sources,
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
    from . import pagination
    from . import sources as source_master

    with _connection() as con:
        total = content_store.count_listing(
            con,
            status=status or None,
            source_id=int(source_id) if source_id else None,
            today_only=bool(today),
        )
        page = pagination.resolve_page(request.query_params.get("page"), total)
        rows = content_store.listing(
            con,
            status=status or None,
            source_id=int(source_id) if source_id else None,
            today_only=bool(today),
            limit=pagination.PAGE_SIZE,
            offset=pagination.sql_offset(page),
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
        + pagination.nav(
            "/admin/intake",
            {"status": status, "source_id": source_id, "today": today},
            page, total,
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
        # Two different facts: when we last asked, and when we last got
        # anything. A blocked item has one and not the other, and an operator
        # looking at a silent source needs to tell them apart.
        ("Last attempt", E(str(content.get("last_attempt_at") or "-"))[:19]),
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

def _default_review_state(candidate_id: int) -> dict[str, Any]:
    """review.state()'s fallback shape, without the per-row query.

    A page is at most 50 rows and `review.states()` returns one query for all
    of them, but only for the ones that actually have a row - a PENDING
    candidate has never had one written. Building the same fallback locally
    avoids up to 50 individual `review.state()` queries per page.
    """
    return {
        "candidate_id": candidate_id, "review_state": review.PENDING,
        "last_action": None, "last_reviewer": None, "last_review_at": None,
        "corrected_json": {}, "duplicate_of_candidate_id": None, "action_count": 0,
    }


def _with_review_state(rows: list[dict[str, Any]], states: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        row["review"] = states.get(row["candidate_id"]) or _default_review_state(row["candidate_id"])
    return rows


def _is_pending(row: dict[str, Any]) -> bool:
    return (row["review"]["review_state"] == review.PENDING
            and row["candidate_status"] in review.REVIEWABLE_ENGINE_STATUSES)


def _event_date(row: dict[str, Any]) -> date | None:
    value = row.get("event_date")
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _days_away(row: dict[str, Any]) -> int | None:
    """Days from today in Seoul. Negative for a date already past."""
    day = _event_date(row)
    return None if day is None else (day - events_api.today()).days


def _has_wrong_time(row: dict[str, Any]) -> bool:
    """A morning start on a candidate whose post marked the afternoon.

    The same thing the quality panel counts, asked of a review row so the one
    problem that is worse than a gap sorts above every gap.
    """
    start = str(row.get("start_time") or "")
    if not start or start >= "12:00":
        return False
    return any(h["severity"] == review_hints.SEVERITY_WARN
               for h in row.get("hints") or [])


def _when_badge(row: dict[str, Any]) -> str:
    """How close this event is, said once rather than worked out per row."""
    away = _days_away(row)
    if away is None:
        return ' <span class="badge muted">날짜 미확인</span>'
    if away < 0:
        return ' <span class="badge muted">지난 행사</span>'
    if away == 0:
        return ' <span class="badge bad">오늘</span>'
    if away == 1:
        return ' <span class="badge warn">내일</span>'
    if away <= 7:
        return f' <span class="badge warn">{away}일 뒤</span>'
    return f' <span class="badge muted">{away}일 뒤</span>'


def review_priority(row: dict[str, Any]) -> tuple:
    """What a reviewer should look at first.

    A sort key, not a model. In order: a value that contradicts its post, then
    tonight and tomorrow, then a missing time, then a missing venue, then a
    missing fee, then by date. DanceMate exists to answer "where can I dance
    tonight", so tonight outranks a more incomplete event three weeks out.
    """
    away = _days_away(row)
    imminent = away is not None and 0 <= away <= 1
    return (
        0 if row["candidate_status"] == "CONFLICT" else 1,
        0 if _has_wrong_time(row) else 1,
        0 if imminent else 1,
        0 if not row.get("start_time") else 1,
        0 if not row.get("venue") else 1,
        0 if row.get("fee") is None else 1,
        away if away is not None else 9999,
    )


def _is_upcoming(row: dict[str, Any]) -> bool:
    away = _days_away(row)
    return away is not None and away >= 0


def _within(row: dict[str, Any], days: int) -> bool:
    away = _days_away(row)
    return away is not None and 0 <= away <= days


# The questions an operator actually arrives with, each with the predicate
# behind it. Counts are rendered beside every one, so an empty filter is
# visible before it is clicked.
#
# Upcoming comes first and is the default. A private alpha is judged on where
# somebody can dance tonight; last month's missing fee is not worth an
# afternoon, and a queue that opens on all 33 rows buries the eight that are.
REVIEW_FILTERS: dict[str, tuple[str, Any]] = {
    "upcoming": ("앞으로", _is_upcoming),
    "today": ("오늘", lambda r: _within(r, 0)),
    "tomorrow": ("내일", lambda r: (_days_away(r) == 1)),
    "week": ("이번 주", lambda r: _within(r, 7)),
    "conflict": ("충돌", lambda r: r["candidate_status"] in ("CONFLICT", "UNKNOWN")),
    "unknown_time": ("시간 미확인",
                     lambda r: _is_upcoming(r) and not r.get("start_time")),
    "unknown_venue": ("장소 미확인",
                      lambda r: _is_upcoming(r) and not r.get("venue")),
    "unknown_fee": ("요금 미확인",
                    lambda r: _is_upcoming(r) and r.get("fee") is None),
    "pending": ("검토 대기", _is_pending),
    "reviewed": ("검토 완료", lambda r: r["review"]["review_state"] != review.PENDING),
    "all": ("전체", lambda r: True),
}

DEFAULT_REVIEW_FILTER = "upcoming"


def _raw_page(raw: Any) -> int:
    try:
        page = int(raw)
    except (TypeError, ValueError):
        page = 1
    return max(1, page)


@router.get("/admin/review", response_class=HTMLResponse)
def admin_review(
    request: Request, show: str = "pending", filter: str = "", genre: str = "",
    _: str = Depends(require_admin),
) -> HTMLResponse:
    from . import pagination

    settings = _settings()
    chosen = (filter or show or DEFAULT_REVIEW_FILTER).strip().lower()
    if chosen not in REVIEW_FILTERS:
        chosen = DEFAULT_REVIEW_FILTER
    genre = genre.strip().upper()

    with _connection() as con:
        # Fetched once regardless of `chosen`: filter_counts() below needs it
        # for the pending/reviewed tallies in the filter bar no matter which
        # tab is open.
        reviewed_ids = review.reviewed_candidate_ids(con)
        metrics = review.metrics(con)
        source_keys = sources.source_keys_for_genre(con, genre) if genre else None

    raw_page = _raw_page(request.query_params.get("page"))
    result = candidates.query(
        settings, filter_key=chosen, reviewed_ids=reviewed_ids,
        page=raw_page, page_size=pagination.PAGE_SIZE, source_keys=source_keys,
    )
    total = result["total"]
    page = pagination.resolve_page(request.query_params.get("page"), total)
    if page != raw_page:
        # Only reached for a param outside the real range (0, -1, "abc",
        # 999999) - the common case costs one query, not two.
        result = candidates.query(
            settings, filter_key=chosen, reviewed_ids=reviewed_ids,
            page=page, page_size=pagination.PAGE_SIZE, source_keys=source_keys,
        )
    visible_page = result["rows"]

    with _connection() as con:
        page_states = review.states(con, [r["candidate_id"] for r in visible_page])
    _with_review_state(visible_page, page_states)

    counts_by_filter = candidates.filter_counts(
        settings, reviewed_ids=reviewed_ids, source_keys=source_keys,
    )
    genre_suffix = f"&genre={genre}" if genre else ""
    filter_bar = '<div class="filterbar">' + "".join(
        f'<a href="/admin/review?filter={key}{genre_suffix}"'
        + (' class="on"' if key == chosen else "")
        + f'>{E(label)} {counts_by_filter.get(key, 0)}</a>'
        for key, (label, _match) in REVIEW_FILTERS.items()
    ) + "</div>"
    if genre:
        filter_bar += (
            f'<p class="note">장르: {E(genre)} '
            f'&middot; <a href="/admin/review?filter={chosen}">전체 장르로</a></p>'
        )

    cards = admin._cards([
        ("Review pending", counts_by_filter.get("pending", 0), "candidates awaiting a person"),
        ("Approved today", metrics["today"][review.APPROVE], "APPROVE"),
        ("Edited today", metrics["today"][review.EDIT], "EDIT"),
        ("Rejected today", metrics["today"][review.REJECT], "REJECT"),
        ("Duplicate today", metrics["today"][review.DUPLICATE], "DUPLICATE"),
        ("Confirmed today", metrics["today"][review.CONFIRM], "CONFIRM"),
    ])

    table_rows = []
    for row in visible_page:
        state_value = row["review"]["review_state"]
        detail_href = f'/admin/review/{row["candidate_id"]}?queue={chosen}&page={page}{genre_suffix}'
        table_rows.append([
            (f'<a href="{detail_href}">'
             f'{E(str(row.get("event_name") or "-")[:48])}</a>'
             + _when_badge(row)),
            E(str(row.get("event_date") or "-")),
            E(str(row.get("start_time") or "-")),
            E(str(row.get("venue") or "-")),
            admin._badge(row["candidate_status"], row["status_tone"]),
            admin._badge(state_value, REVIEW_TONE.get(state_value, "muted")),
            E(str(row.get("source_id") or "-")),
            f'<a href="{detail_href}"><button>Review</button></a>',
        ])

    body = (
        "<h2>Human Verification</h2>" + cards
        + filter_bar
        + '<p class="note">A human decision is recorded alongside the engine\'s status, '
          "never instead of it. APPROVE does not grant VERIFIED - only the engine's "
          "evidence gate does that.</p>"
        + '<p class="note">정렬: 게시글과 어긋나는 값 → 오늘·내일 행사 → 시간 미확인 '
          "→ 장소 미확인 → 요금 미확인 → 날짜순.</p>"
        + admin._table(
            ["Event", "Date", "Start", "Venue", "Engine", "Review", "Source", ""],
            table_rows,
            empty="nothing to review in this view",
        )
        + pagination.nav("/admin/review", {"filter": chosen, "genre": genre}, page, total)
    )
    return HTMLResponse(admin._page("Review", "/admin/review", body, flash=admin._flash(request)))


def _event_summary(merged: dict[str, Any], found: dict[str, Any]) -> str:
    """The event in one block, in the order a reviewer needs it.

    Date, time, venue, fee first, because those are what someone deciding
    whether to go actually reads. Everything below is how we came to believe
    them.
    """
    def cell(value: Any, missing: str) -> str:
        return (E(str(value)) if value not in (None, "")
                else f'<span class="badge warn">{E(missing)}</span>')

    away = _days_away(merged)
    when = ("오늘" if away == 0 else "내일" if away == 1
            else f"{away}일 뒤" if away is not None and away > 0
            else "지난 행사" if away is not None else "날짜 미확인")
    rows = [
        ("날짜", cell(merged.get("event_date"), "날짜 미확인") + f' <span class="badge muted">{E(when)}</span>'),
        ("시간", cell(merged.get("start_time"), "시간 미확인")
                 + (f' ~ {E(str(merged.get("end_time")))}' if merged.get("end_time") else "")),
        ("장소", cell(merged.get("venue"), "장소 미확인")),
        ("요금", cell(merged.get("fee"), "요금 미확인")),
        ("종류", cell(found.get("event_type"), "-")),
        ("상태", admin._badge(found.get("candidate_status"), found.get("status_tone", "muted"))),
    ]
    cells = "".join(f"<dt>{E(k)}</dt><dd>{v}</dd>" for k, v in rows)
    return (f'<div class="tablewrap" style="padding:12px 16px">'
            f'<dl style="display:grid;grid-template-columns:auto 1fr;gap:.4rem 1rem;margin:0">'
            f"{cells}</dl></div>")


def _queue_position(
    settings, queue_key: str, reviewed_ids: set[int], page: int,
    source_keys: list[str] | None = None,
) -> str:
    """How far into the queue this page is, so a reviewer knows how far to go.

    An exact row ordinal ("47/842") would need the candidate's own rank in the
    filtered order, which costs a full scan to compute - the one thing this
    release removes. A page-level position costs one indexed COUNT instead,
    and answers the same practical question ("how much is left").
    """
    from . import pagination

    try:
        result = candidates.query(
            settings, filter_key=queue_key, reviewed_ids=reviewed_ids,
            page=page, page_size=1, source_keys=source_keys,
        )
    except candidates.EngineStoreUnavailable:
        return ""
    total = result["total"]
    return f"Page {page} / {pagination.total_pages(total)} · Total {total}"


@router.get("/admin/review/{candidate_id}", response_class=HTMLResponse)
def admin_review_detail(
    candidate_id: int, request: Request, queue: str = "", page: str = "1", genre: str = "",
    _: str = Depends(require_admin),
) -> HTMLResponse:
    settings = _settings()
    genre = genre.strip().upper()
    found = candidates.get(settings, candidate_id)
    if found is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    with _connection() as con:
        current = review.state(con, candidate_id)
        actions = review.history(con, candidate_id)
        item = None
        image_rows: list[dict[str, Any]] = []
        if found.get("source_url"):
            with con.cursor() as cur:
                cur.execute(
                    "SELECT source_item_id FROM source_items WHERE url = %s LIMIT 1",
                    (found["source_url"],),
                )
                row = cur.fetchone()
            if row:
                item = content_store.detail(con, row[0])
                image_rows = image_fallback.images_for_review(con, row[0])
        ocr_fields = candidates.image_ocr_fields(settings, candidate_id)

    queue_key = queue if queue in REVIEW_FILTERS else DEFAULT_REVIEW_FILTER
    queue_label = REVIEW_FILTERS[queue_key][0]
    page_num = _raw_page(page)
    with _connection() as con:
        reviewed_ids = review.reviewed_candidate_ids(con)
        source_keys = sources.source_keys_for_genre(con, genre) if genre else None
    position = _queue_position(settings, queue_key, reviewed_ids, page_num, source_keys)

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

    def image_evidence_block() -> str:
        """What extract_with_image_fallback() saw and used, per image
        (v0.81.3, Section 30) - every image this item's ingest ever fetched
        or OCR'd, whether or not it ended up filling anything.
        """
        if not image_rows:
            return ""
        field_labels = {"date": "Date", "time": "Time", "fee": "Fee"}
        detected_by_url: dict[str, list[str]] = {}
        for f in ocr_fields:
            url = f.get("inference")
            if not url:
                continue
            detected_by_url.setdefault(url, []).append(
                f"{field_labels.get(f['field'], f['field'])}: {f['value']}")

        blocks = []
        for row in image_rows:
            url = row["image_url"]
            used = bool(row.get("used_as_fallback"))
            status = row.get("ocr_status") or row.get("fetch_status") or "-"
            tone = "ok" if used else ("warn" if row.get("ocr_status") == "OCR_SUCCESS" else "muted")
            detected = detected_by_url.get(url)
            confidence = row.get("ocr_confidence")
            blocks.append(
                f'<details{" open" if used else ""}>'
                f'<summary>Image {row["image_index"] + 1}'
                + (' <span class="badge ok">IMAGE_OCR_USED</span>' if used else "")
                + "</summary>"
                f'<p class="note"><a href="{E(url)}" target="_blank" '
                f'rel="noreferrer noopener">{E(url)}</a></p>'
                f'<p class="note">{admin._badge(status, tone)}'
                + (f" &middot; confidence {confidence:.0f}" if confidence is not None else "")
                + "</p>"
                + (f'<p class="note">Detected: {E(", ".join(detected))}</p>' if detected else "")
                + (f'<pre style="white-space:pre-wrap;word-break:break-word;margin:0;'
                   f'font:13px/1.6 ui-monospace,monospace">{E(row.get("ocr_text") or "")}</pre>'
                   if row.get("ocr_text") else '<p class="note">no text recognised</p>')
                + "</details>"
            )
        return "<h2>Image Evidence</h2>" + "".join(blocks)

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
<input type="hidden" name="queue" value="{E(queue_key)}">
<input type="hidden" name="page" value="{page_num}">
<input type="hidden" name="queue_genre" value="{E(genre)}">
<div class="actions">
  <button class="primary" name="next_after" value="0">Save correction</button>
  <button class="primary" name="next_after" value="1">Save &amp; Next</button>
</div>
<p class="note">The engine's own values are kept; your correction is stored alongside them.
Save &amp; Next moves to the next event in the {E(queue_label)} queue.</p>
</form></details>"""

    def simple_form(action: str, label: str, note: str) -> str:
        primary = " class=\"primary\"" if action.lower() in ("approve", "confirm") else ""
        return f"""
<form method="post" action="/admin/review/{candidate_id}/{action.lower()}" class="inline">
  <input type="hidden" name="reason" value="">
  <input type="hidden" name="queue" value="{E(queue_key)}">
  <input type="hidden" name="page" value="{page_num}">
  <input type="hidden" name="queue_genre" value="{E(genre)}">
  <button name="next_after" value="0" title="{E(note)}"{primary}>{E(label)}</button>
  <button name="next_after" value="1" title="{E(note)} — 그리고 다음 항목으로">
    {E(label)} &amp; Next</button></form>"""

    duplicate_form = f"""
<form method="post" action="/admin/review/{candidate_id}/duplicate" class="inline">
  <input name="duplicate_of_candidate_id" placeholder="duplicate of candidate id" style="width:190px">
  <input type="hidden" name="queue" value="{E(queue_key)}">
  <input type="hidden" name="page" value="{page_num}">
  <input type="hidden" name="queue_genre" value="{E(genre)}">
  <button name="next_after" value="0">DUPLICATE</button></form>"""

    history_rows = [
        [E(str(a["created_at"])[:19]), admin._badge(a["action"]), E(a["reviewer"]),
         E(str(a.get("reason") or "-")),
         f'<code>{E(str(a.get("after_json") or {}))[:70]}</code>']
        for a in actions
    ]

    genre_suffix = f"&genre={E(genre)}" if genre else ""
    body = (
        f'<p class="sub"><a href="/admin/review?filter={E(queue_key)}&page={page_num}{genre_suffix}">&larr; '
        f'{E(queue_label)} 큐</a> &middot; {E(position)}</p>'
        f"<h2>Review candidate {candidate_id}</h2>"
        + _event_summary(merged, found)
        + "<h2>Evidence</h2>" + evidence
        + text_block("Search snippet (discovery)", snippet,
                     "What the provider's search API returned.")
        + text_block("Acquired article text", content.get("extracted_text"),
                     "Fetched from the original post, personal data removed.")
        + image_evidence_block()
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
    row = candidates.get(settings, candidate_id)
    if row is None:
        return {}
    return {
        "event_name": row.get("event_name"),
        "event_date": row.get("event_date"),
        "start_time": row.get("start_time"),
        "end_time": row.get("end_time"),
        "venue": row.get("venue"),
        "fee": row.get("fee"),
    }


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
    queue: str = Form(""),
    page: str = Form("1"),
    queue_genre: str = Form(""),
    next_after: str = Form(""),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    action_name = action.upper()
    if action_name not in review.ACTIONS:
        raise HTTPException(status_code=404, detail="unknown review action")

    settings = _settings()
    page_num = _raw_page(page)
    queue_genre = queue_genre.strip().upper()
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
        return admin._back(_detail_url(candidate_id, queue, page_num, queue_genre), str(exc), "bad")
    except Exception as exc:
        return admin._back(
            _detail_url(candidate_id, queue, page_num, queue_genre), f"could not record: {exc}", "bad",
        )

    if next_after == "1":
        # Straight on to the next one in the same queue. Reviewing eight events
        # should not mean eight trips back to a list. The set fetched here is
        # deliberately fresh (after review.record's commit above), since this
        # very action may have just moved the candidate out of a
        # pending/reviewed filter.
        with _connection() as con:
            reviewed_ids = review.reviewed_candidate_ids(con)
            source_keys = (
                sources.source_keys_for_genre(con, queue_genre) if queue_genre else None
            )
        following, next_page = _next_in_queue(
            settings, candidate_id, queue, page_num, reviewed_ids, source_keys,
        )
        if following is not None:
            return admin._back(
                _detail_url(following, queue, next_page, queue_genre),
                f"{action_name} recorded — next one",
            )
        return admin._back(
            f"/admin/review?filter={queue or DEFAULT_REVIEW_FILTER}"
            + (f"&genre={queue_genre}" if queue_genre else ""),
            f"{action_name} recorded — that was the last one in this queue",
        )
    return admin._back(
        _detail_url(candidate_id, queue, page_num, queue_genre), f"{action_name} recorded",
    )


def _detail_url(candidate_id: int, queue: str, page: int = 1, genre: str = "") -> str:
    params = []
    if queue:
        params.append(f"queue={queue}")
    if page and page != 1:
        params.append(f"page={page}")
    if genre:
        params.append(f"genre={genre}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return f"/admin/review/{candidate_id}{suffix}"


def _next_in_queue(
    settings, candidate_id: int, queue: str, page: int, reviewed_ids: set[int],
    source_keys: list[str] | None = None,
) -> tuple[int | None, int]:
    """The candidate after this one, and the page it is on.

    Reads only the one page the reviewer was already looking at (and, at
    most, the page after or before it) rather than the whole queue. If the
    action just recorded moved this candidate out of the filter (approving it
    off a "pending" queue, say), it is gone from a freshly-queried page and
    whatever now leads that same page is the next thing needing attention.
    """
    from . import pagination

    key = queue if queue in REVIEW_FILTERS else DEFAULT_REVIEW_FILTER
    try:
        result = candidates.query(
            settings, filter_key=key, reviewed_ids=reviewed_ids,
            page=page, page_size=pagination.PAGE_SIZE, source_keys=source_keys,
        )
    except candidates.EngineStoreUnavailable:
        return None, page
    ids = [r["candidate_id"] for r in result["rows"]]

    if candidate_id in ids:
        idx = ids.index(candidate_id)
        if idx + 1 < len(ids):
            return ids[idx + 1], page
        try:
            nxt = candidates.query(
                settings, filter_key=key, reviewed_ids=reviewed_ids,
                page=page + 1, page_size=pagination.PAGE_SIZE, source_keys=source_keys,
            )
        except candidates.EngineStoreUnavailable:
            return None, page
        if nxt["rows"]:
            return nxt["rows"][0]["candidate_id"], page + 1
        return None, page

    # It left the queue -- reviewing it is often what removed it. The
    # (refreshed) same page has shifted up to fill the gap.
    if ids:
        return ids[0], page
    if page > 1:
        try:
            prev = candidates.query(
                settings, filter_key=key, reviewed_ids=reviewed_ids,
                page=page - 1, page_size=pagination.PAGE_SIZE, source_keys=source_keys,
            )
        except candidates.EngineStoreUnavailable:
            return None, page
        if prev["rows"]:
            return prev["rows"][0]["candidate_id"], page - 1
    return None, page


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
def api_review(
    filter: str = DEFAULT_REVIEW_FILTER, page: int = 1, genre: str = "",
    _: str = Depends(require_admin),
) -> JSONResponse:
    from . import pagination

    settings = _settings()
    chosen = filter if filter in REVIEW_FILTERS else DEFAULT_REVIEW_FILTER
    genre = genre.strip().upper()
    with _connection() as con:
        reviewed_ids = review.reviewed_candidate_ids(con)
        metrics = review.metrics(con)
        source_keys = sources.source_keys_for_genre(con, genre) if genre else None
    result = candidates.query(
        settings, filter_key=chosen, reviewed_ids=reviewed_ids,
        page=_raw_page(page), page_size=pagination.PAGE_SIZE, source_keys=source_keys,
    )
    return admin._dump({
        "metrics": metrics,
        "filter": chosen,
        "page": _raw_page(page),
        "total": result["total"],
        "candidates": result["rows"],
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
