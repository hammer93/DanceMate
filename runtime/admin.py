"""DanceMate admin console — LAN staging operations UI and JSON API.

Server-rendered HTML built with the standard library. No template engine, no
SPA framework, no build step: the runtime's dependency list stays at three
packages and the whole console costs the 4GB board nothing beyond the process
already running.

What an operator can do here in v0.75:
  * see runtime, scheduler, engine and intake state on one page
  * maintain genres, regions, venues (with aliases) and organizers
  * register sources, enable/disable them, set collection interval, test them
  * read the Event Candidates the Information Engine has produced

What they deliberately cannot do: grant VERIFIED. The APPROVE / EDIT / REJECT /
DUPLICATE / CONFIRM workflow is v0.76.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import (
    acquisition, candidates, collectors, content_store, db, health, intake,
    master_data, quota, review, source_ops, sources, usage,
)
from .admin_auth import require_admin
from .config import Settings

router = APIRouter()
api = APIRouter(prefix="/api/admin", tags=["admin"])

# Injected by app.py so the console and the API share one Settings instance.
_settings_provider: Callable[[], Settings] | None = None


def bind(settings_provider: Callable[[], Settings]) -> None:
    global _settings_provider
    _settings_provider = settings_provider


def _settings() -> Settings:
    if _settings_provider is None:  # pragma: no cover - wiring error
        raise RuntimeError("admin router was not bound to a settings provider")
    return _settings_provider()


def _connection():
    return db.connect(_settings(), autocommit=True)


def _json_default(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _dump(payload: Any) -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(payload, default=_json_default)))


# --- rendering --------------------------------------------------------------

E = html.escape

STYLE = """
:root{--bg:#faf9f7;--fg:#1c1a17;--muted:#6b665e;--line:#e2ded7;--card:#fff;
--ok:#1f7a4d;--warn:#8a6100;--bad:#a32b1f;--accent:#3f4a7e}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;
background:var(--bg);color:var(--fg)}
header{background:var(--card);border-bottom:1px solid var(--line);padding:0 20px}
header .bar{display:flex;align-items:baseline;gap:16px;max-width:1200px;margin:0 auto;
padding:14px 0;flex-wrap:wrap}
header h1{font-size:16px;margin:0;letter-spacing:.02em}
header .env{color:var(--muted);font-size:12px}
nav{max-width:1200px;margin:0 auto;display:flex;gap:2px;flex-wrap:wrap}
nav a{padding:8px 12px;color:var(--muted);text-decoration:none;border-bottom:2px solid transparent}
nav a:hover{color:var(--fg)}
nav a.on{color:var(--fg);border-bottom-color:var(--accent);font-weight:600}
main{max-width:1200px;margin:0 auto;padding:20px}
h2{font-size:15px;margin:24px 0 10px}
h2:first-child{margin-top:0}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.card .v{font-size:22px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}
.card .s{color:var(--muted);font-size:12px;margin-top:2px;word-break:break-all}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
background:var(--bg);position:sticky;top:0}
tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600;
border:1px solid}
.ok{color:var(--ok);border-color:var(--ok);background:#eef7f2}
.warn{color:var(--warn);border-color:var(--warn);background:#fdf5e6}
.bad{color:var(--bad);border-color:var(--bad);background:#fbeeec}
.muted{color:var(--muted);border-color:var(--line);background:var(--bg)}
form.inline{display:inline}
button{font:inherit;padding:4px 10px;border:1px solid var(--line);background:var(--card);
border-radius:6px;cursor:pointer;color:var(--fg)}
button:hover{border-color:var(--accent);color:var(--accent)}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
button.primary:hover{opacity:.9;color:#fff}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;
margin-bottom:14px}
summary{cursor:pointer;font-weight:600;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;
margin-top:12px}
label{display:block;font-size:12px;color:var(--muted);margin-bottom:3px}
input,select,textarea{width:100%;font:inherit;padding:6px 8px;border:1px solid var(--line);
border-radius:6px;background:var(--card);color:var(--fg)}
.actions{margin-top:12px}
.note{color:var(--muted);font-size:12px;margin:6px 0 0}
.flash{padding:9px 12px;border-radius:8px;margin-bottom:14px;border:1px solid}
.flash.ok{border-color:var(--ok)}
.flash.bad{border-color:var(--bad)}
a{color:var(--accent)}
code{background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:0 4px;
font-size:12px}
.queue{display:flex;flex-direction:column;gap:12px}
.queue .item{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.queue .raw{font-size:16px;font-weight:600;word-break:break-all}
.queue .facts{color:var(--muted);font-size:12px;margin-top:3px;display:flex;gap:14px;flex-wrap:wrap}
.queue .sources{margin:10px 0 0;padding:0;list-style:none;font-size:12px}
.queue .sources li{margin-top:6px}
.snippet{color:var(--muted);border-left:3px solid var(--line);padding:2px 0 2px 10px;
margin-top:2px;word-break:break-word}
.actionbar{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap;margin-top:12px;
padding-top:12px;border-top:1px solid var(--line)}
.actionbar form.inline{display:flex;gap:6px;align-items:center}
.actionbar select{width:auto;min-width:200px}
.actionbar details{margin:0;padding:0;border:none;background:none}
.actionbar details summary{display:inline-block;padding:4px 10px;border:1px solid var(--line);
background:var(--card);border-radius:6px;font-weight:400}
.actionbar details summary:hover{border-color:var(--accent);color:var(--accent)}
.actionbar details[open]{display:block;width:100%;border:1px solid var(--line);
border-radius:8px;padding:10px 14px;background:var(--bg)}
.callout{background:var(--card);border:1px solid var(--warn);border-left-width:4px;
border-radius:8px;padding:12px 16px;margin-bottom:14px}
.callout h3{margin:0 0 6px;font-size:14px}
details.editrow{margin:0;padding:0;border:none;background:none}
details.editrow>summary{display:inline-block;padding:4px 10px;border:1px solid var(--accent);
color:var(--accent);background:var(--card);border-radius:6px;font-weight:600}
details.editrow>summary:hover{background:var(--accent);color:#fff}
details.editrow[open]{display:block;width:100%;border:1px solid var(--line);
border-radius:8px;padding:12px 14px;background:var(--bg);margin-top:6px}
details.editrow input[disabled]{background:var(--bg);color:var(--muted)}
.qrow{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--line)}
.qrow:last-child{border-bottom:none}
.qlabel{width:170px;color:var(--muted);font-size:12px}
.qval{font-variant-numeric:tabular-nums;font-weight:600;min-width:92px}
.filterbar{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px}
.filterbar a{border:1px solid var(--line);border-radius:999px;padding:3px 11px;
text-decoration:none;font-size:12px;background:var(--card);color:var(--muted)}
.filterbar a.on{border-color:var(--accent);color:var(--accent);font-weight:600}
.pager{display:flex;align-items:center;justify-content:space-between;gap:12px;
flex-wrap:wrap;margin-top:10px;padding:8px 2px;font-size:12px;color:var(--muted)}
.pager-nav{display:flex;align-items:center;gap:10px}
.pager-link{border:1px solid var(--line);border-radius:6px;padding:4px 10px;
text-decoration:none;color:var(--fg);background:var(--card)}
.pager-link:hover{border-color:var(--accent);color:var(--accent)}
.pager-link.off{color:var(--muted);border-color:var(--line);opacity:.5}
.pager-status{font-variant-numeric:tabular-nums}
"""

NAV = (
    ("/admin", "Dashboard"),
    ("/admin/intake", "Intake"),
    ("/admin/review", "Review"),
    ("/admin/events", "Events"),
    ("/admin/duplicates", "Duplicates"),
    ("/admin/sources", "Sources"),
    ("/admin/venues", "Venues"),
    ("/admin/organizers", "Organizers"),
    ("/admin/master", "Genres & Regions"),
    ("/admin/usage", "Usage"),
    ("/admin/system", "System"),
)

# /admin/candidates predates the Review console. It still works, and the nav
# points at its replacement; the old URL is not broken for anyone who bookmarked it.


def _page(title: str, current: str, body: str, *, flash: tuple[str, str] | None = None) -> str:
    settings = _settings()
    nav = "".join(
        f'<a href="{href}" class="{"on" if href == current else ""}">{E(label)}</a>'
        for href, label in NAV
    )
    banner = ""
    if flash:
        tone, message = flash
        banner = f'<p class="flash {tone}">{E(message)}</p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)} - DanceMate Admin</title><style>{STYLE}</style></head>
<body>
<header><div class="bar">
  <h1>DanceMate Admin</h1>
  <span class="env">runtime v{E(settings.version)} &middot; engine v{E(settings.engine_version)}
  &middot; {E(settings.env)} &middot; LAN only</span>
</div><nav>{nav}</nav></header>
<main>{banner}{body}</main>
</body></html>"""


def _cards(items: list[tuple[str, Any, str]]) -> str:
    cells = "".join(
        f'<div class="card"><div class="k">{E(k)}</div>'
        f'<div class="v">{E(str(v))}</div>'
        f'<div class="s">{E(sub)}</div></div>'
        for k, v, sub in items
    )
    return f'<div class="cards">{cells}</div>'


def _table(headers: list[str], rows: list[list[str]], *, empty: str) -> str:
    if not rows:
        return f'<div class="tablewrap"><table><tbody><tr><td>{E(empty)}</td>' \
               "</tr></tbody></table></div>"
    head = "".join(f"<th>{E(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead>' \
           f"<tbody>{body}</tbody></table></div>"


def _badge(value: str | None, tone: str = "muted") -> str:
    return f'<span class="badge {tone}">{E(str(value or "-"))}</span>'


def _flash(request: Request) -> tuple[str, str] | None:
    message = request.query_params.get("msg")
    if not message:
        return None
    tone = "bad" if request.query_params.get("tone") == "bad" else "ok"
    return tone, message


def _back(path: str, message: str, tone: str = "ok") -> RedirectResponse:
    from urllib.parse import urlencode

    query = urlencode({"msg": message, "tone": tone})
    return RedirectResponse(f"{path}?{query}", status_code=303)


# --- dashboard --------------------------------------------------------------

def _quality_bar(label: str, part: int, whole: int, *, link: str | None = None,
                 missing_label: str = "미확인") -> str:
    """One field's completeness, with the gap named rather than implied.

    "Time 31/42" leaves the reader to subtract. Saying "11 미확인" and linking to
    those eleven is the difference between a number and something to act on.
    """
    from . import quality

    percent = quality.percentage(part, whole)
    gap = max(0, whole - part)
    shown = f"{part}/{whole}" + (f" · {percent}%" if percent is not None else "")
    if gap and link:
        tail = (f' <a href="{link}" class="badge warn">{gap} {E(missing_label)}</a>')
    elif gap:
        tail = f' <span class="badge warn">{gap} {E(missing_label)}</span>'
    else:
        tail = ' <span class="badge ok">전부 확인됨</span>' if whole else ""
    return (f'<div class="qrow"><span class="qlabel">{E(label)}</span>'
            f'<span class="qval">{E(shown)}</span>{tail}</div>')


def _today_panel(settings: Settings) -> str:
    """What an operator has to deal with today, before anything else.

    The dashboard used to open on totals -- sources registered, items ever
    collected. Those are true and they are not the morning's question, which is
    what is on tonight and what still needs looking at.
    """
    from . import quality, review

    try:
        with _connection() as con:
            buckets = quality.upcoming_buckets(con)
            upcoming = quality.completeness(con, upcoming_only=True)
            metrics = review.metrics(con)
    except db.DatabaseUnavailable:
        return ""

    pending = max(0, upcoming["events"] - upcoming["human_reviewed"])
    cards = _cards([
        ("오늘", buckets["today"], "listed for today"),
        ("내일", buckets["tomorrow"], "listed for tomorrow"),
        ("이번 주", buckets["this_week"], "today through +7 days"),
        ("검토 대기", pending, f'of {upcoming["events"]} upcoming'),
        ("검토 완료", upcoming["human_reviewed"], "a person has ruled on these"),
        ("지난 행사", buckets["past"], "kept, not shown to readers"),
    ])
    actions = (
        '<div class="filterbar">'
        '<a href="/admin/review?filter=today">오늘 검토</a>'
        '<a href="/admin/review?filter=tomorrow">내일 검토</a>'
        '<a href="/admin/review?filter=unknown_time">시간 미확인</a>'
        '<a href="/admin/review?filter=unknown_venue">장소 미확인</a>'
        '<a href="/admin/review?filter=upcoming&genre=TANGO">탱고 검토</a>'
        '<a href="/admin/venues/unresolved">장소 연결</a>'
        "</div>"
    )
    return "<h2>오늘 할 일</h2>" + cards + actions


def _alpha_panel(settings: Settings) -> str:
    """What people actually opened. No identifiers behind any of these numbers."""
    from . import alpha_metrics

    found = alpha_metrics.snapshot(settings)
    if not found.get("available"):
        return ""
    counts = found["counts"]
    cards = _cards([
        (alpha_metrics.LABELS[kind], counts[kind]["today"],
         f'{counts[kind]["recent"]} in {found["days"]} days')
        for kind in alpha_metrics.KINDS
    ])
    opened = found["most_opened"]
    listing = ""
    if opened:
        rows = "".join(
            f'<li>{E(str(o["event_name"] or o["event_id"])[:56])} '
            f'<span class="badge muted">{o["views"]}회</span></li>'
            for o in opened if o.get("event_id")
        )
        listing = f'<ul class="sources">{rows}</ul>' if rows else ""
    return (
        '<h2>Alpha usage</h2>' + cards + listing
        + '<p class="note">식별자·IP·세션을 저장하지 않습니다. 세 가지 횟수와 '
          "날짜뿐입니다. 원문 이동이 많다면 추출이 부족하다는 뜻입니다.</p>"
    )


def _coverage_panel(settings: Settings) -> str:
    """Genre against region. The zeroes are the interesting cells."""
    from . import quality

    try:
        with _connection() as con:
            matrix = quality.coverage_matrix(con)
    except db.DatabaseUnavailable:
        return ""
    if not matrix["genres"]:
        return ""
    header = "".join(f"<th>{E(r)}</th>" for r in matrix["regions"])
    rows = []
    for genre in matrix["genres"]:
        cells = "".join(
            (f'<td class="num">{matrix["grid"][genre].get(region, 0)}</td>'
             if matrix["grid"][genre].get(region, 0)
             else '<td class="num"><span class="badge muted">0</span></td>')
            for region in matrix["regions"]
        )
        rows.append(f"<tr><td>{E(genre)}</td>{cells}</tr>")
    return (
        '<h2>Coverage <span class="note">— 앞으로의 행사 기준</span></h2>'
        '<div class="tablewrap"><table><thead><tr><th>Genre</th>'
        f"{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        '<p class="note">0인 칸이 다음에 채울 곳입니다. 실제 공개 소스가 없으면 '
        "억지로 채우지 않습니다.</p>"
    )


def _genre_coverage_panel(settings: Settings, genre_code: str, label: str) -> str:
    """Sources / Upcoming / Today / Tomorrow / This Week for one genre, plus
    a region x window matrix (v0.82 Coverage Metrics, Section 27-30) - a
    single-genre expansion release is judged on whether ITS coverage grew,
    which the all-genre _today_panel/_coverage_panel above cannot show.
    """
    from . import quality

    try:
        with _connection() as con:
            source_keys = sources.source_keys_for_genre(con, genre_code)
            buckets = quality.upcoming_buckets(con, genre_code=genre_code)
            matrix = quality.genre_region_windows(con, genre_code)
    except db.DatabaseUnavailable:
        return ""
    if not source_keys:
        return ""

    cards = _cards([
        (f"{label} Sources", len(source_keys), "registered"),
        (f"{label} Upcoming", buckets["upcoming"], "listed, not cancelled"),
        (f"{label} Today", buckets["today"], "listed for today"),
        (f"{label} Tomorrow", buckets["tomorrow"], "listed for tomorrow"),
        (f"{label} This Week", buckets["this_week"], "today through +7 days"),
    ])

    rows = "".join(
        f"<tr><td>{E(region)}</td>"
        f'<td class="num">{matrix["grid"][region]["today"]}</td>'
        f'<td class="num">{matrix["grid"][region]["tomorrow"]}</td>'
        f'<td class="num">{matrix["grid"][region]["this_week"]}</td></tr>'
        for region in matrix["regions"]
    )
    table = (
        '<div class="tablewrap"><table><thead><tr><th>Region</th>'
        "<th>Today</th><th>Tomorrow</th><th>This Week</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        if rows else '<p class="note">no region data yet</p>'
    )
    return f"<h2>{E(label)} Coverage</h2>" + cards + table


def _quality_panel(settings: Settings) -> str:
    """What the data would look like to a dancer, and what is wrong with it."""
    from . import quality

    try:
        with _connection() as con:
            found = quality.snapshot(con)
    except db.DatabaseUnavailable:
        return ""

    upcoming = found["upcoming"]
    total = upcoming["events"]
    bars = "".join([
        _quality_bar("Date", upcoming["date_known"], total),
        _quality_bar("Time", upcoming["time_known"], total,
                     link="/admin/review?filter=unknown_time"),
        _quality_bar("Venue extracted", upcoming["venue_extracted"], total,
                     link="/admin/review?filter=unknown_venue"),
        _quality_bar("Venue resolved", upcoming["venue_resolved"], total,
                     link="/admin/venues/unresolved", missing_label="미해결"),
        _quality_bar("Fee", upcoming["fee_known"], total,
                     link="/admin/review?filter=unknown_fee"),
        _quality_bar("Region", upcoming["region_known"], total,
                     link="/admin/venues", missing_label="지역 미확인"),
        _quality_bar("Human reviewed", upcoming["human_reviewed"], total,
                     link="/admin/review?filter=upcoming", missing_label="미검토"),
    ])

    wrong = found["wrong"]
    if wrong:
        rows = "".join(
            f'<li><strong>{E(str(w["event_date"]))}</strong> {E(w["event_name"] or "")[:50]} '
            f'— {E(str(w["start_time"]))} ({E(w["rule"])})</li>'
            for w in wrong
        )
        alert = (
            '<div class="callout" style="border-color:var(--bad)">'
            f"<h3>Wrong critical field: {len(wrong)}</h3>"
            "<p>게시글이 오후라고 적었는데 오전으로 읽힌 시각입니다. "
            "값이 없는 것보다 나쁩니다 — 추출기 회귀입니다.</p>"
            f'<ul class="sources">{rows}</ul></div>'
        )
    else:
        alert = ('<p class="note"><span class="badge ok">Wrong critical field 0</span> '
                 "게시글과 어긋나는 값은 없습니다. 위 숫자는 전부 '아직 모른다'입니다.</p>")

    fresh = found["freshness"]
    checked = fresh["checked_24h"] or 0
    stale = (fresh["upcoming"] or 0) - checked
    freshness = (
        f'<div class="qrow"><span class="qlabel">최근 24시간 내 확인</span>'
        f'<span class="qval">{checked}/{fresh["upcoming"] or 0}</span>'
        + (f' <span class="badge warn">{stale}건 재확인 필요</span>' if stale else
           ' <span class="badge ok">최신</span>' if fresh["upcoming"] else "")
        + "</div>"
    )

    spread = " · ".join(
        f'{E(r["region"])} {r["upcoming"]}' for r in found["by_region"]
    ) or "-"
    genres = " · ".join(
        f'{E(g["genre"])} {g["upcoming"]}' for g in found["by_genre"]
    ) or "-"

    return (
        '<h2>Data Quality <span class="note">— 사용자에게 보이는 앞으로의 행사 '
        f'{total}건 기준</span></h2>'
        + alert
        + f'<div class="tablewrap" style="padding:12px 16px">{bars}{freshness}</div>'
        + f'<p class="note">지역: {spread} &nbsp;|&nbsp; 장르: {genres}</p>'
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    settings = _settings()
    component_status = health.collect(settings)
    candidate_counts = candidates.counts(settings)

    try:
        with _connection() as con:
            intake_summary = intake.summary(con)
            runs = intake.recent_runs(con, limit=8)
            quota_state = {
                provider: quota.usage(con, provider) for provider in sorted(quota.DAILY_BUDGET)
            }
            acquisition_summary = content_store.summary(con)
            review_metrics = review.metrics(con)
            usage_today = usage.daily(con)
            fetches_today = usage.content_fetches(con)
            efficiency_today = usage.efficiency(con)
    except db.DatabaseUnavailable as exc:
        intake_summary = {"error": str(exc)}
        runs = []
        quota_state = {}
        acquisition_summary = {"by_status": {}, "fetched": 0, "average_text_length": 0,
                               "content_fetches_today": 0, "redacted_spans": 0}
        review_metrics = {"today": dict.fromkeys(review.ACTIONS, 0), "by_state": {}}
        usage_today = []
        fetches_today = {"total": 0, "succeeded": 0}
        efficiency_today = {"new_items_per_request": None, "api_requests": 0, "new_items": 0}

    def tone_of(name: str) -> str:
        status = component_status.get(name, {}).get("status", "FAIL")
        return {"PASS": "ok", "WARN": "warn"}.get(status, "bad")

    status_rows = [
        [E(label), _badge(component_status.get(key, {}).get("status", "FAIL"), tone_of(key)),
         E(str(component_status.get(key, {}).get("detail", ""))[:110])]
        for key, label in (
            ("runtime", "Runtime"), ("database", "Database"), ("scheduler", "Scheduler"),
            ("information", "Information Engine"), ("storage", "Storage"), ("backup", "Backup"),
        )
    ]

    today_panel = _today_panel(settings)
    quality_panel = _quality_panel(settings)
    coverage_panel = _coverage_panel(settings)
    tango_coverage_panel = _genre_coverage_panel(settings, "TANGO", "Tango")
    alpha_panel = _alpha_panel(settings)

    cards = _cards([
        ("Sources", intake_summary.get("sources", "-"),
         f"{intake_summary.get('enabled_sources', 0)} enabled"),
        ("Live items", intake_summary.get("live_items", "-"),
         f"{intake_summary.get('live_runs', 0)} live collection runs"),
        ("Snapshot items", intake_summary.get("snapshot_items", "-"),
         "recorded fixtures, NOT live data"),
        ("Pending ingest", intake_summary.get("pending_ingest", "-"),
         f"{intake_summary.get('source_items', 0)} items stored in total"),
        ("Body fetched", acquisition_summary.get("fetched", 0),
         f"avg {acquisition_summary.get('average_text_length', 0)} chars"),
        ("Event candidates", candidate_counts.get("total", 0),
         f"{candidate_counts.get('review_pending', 0)} not settled"),
        ("Review pending", max(0, candidate_counts.get("total", 0)
                               - review_metrics.get("reviewed_candidates", 0)),
         "candidates awaiting a person"),
        ("Last collection", (intake_summary.get("last_collection_at") or "never")[:19],
         f"{intake_summary.get('errors_24h', 0)} errors in 24h"),
    ])

    run_rows = [
        [E(r["source_key"]), _badge(r["status"], "ok" if r["status"] == "PASS" else "bad"),
         _badge(r["mode"].upper(), "ok" if r["mode"] == "live" else "warn"), f'<span class="num">{r["discovered_count"]}</span>',
         f'<span class="num">{r["new_count"]}</span>',
         f'<span class="num">{r["duplicate_count"]}</span>',
         E(str(r["started_at"])[:19])]
        for r in runs
    ]

    body = (
        today_panel
        + quality_panel
        + coverage_panel
        + tango_coverage_panel
        + alpha_panel
        + "<h2>Collection</h2>"
        + cards
        + "<h2>Components</h2>"
        + _table(["Component", "Status", "Detail"], status_rows, empty="no status")
        + "<h2>Providers today</h2>"
        + _table(
            ["Provider", "API requests", "Success", "Errors", "Items", "New", "Duplicate"],
            [
                [E(r["provider"]), f'<span class="num">{r["request_count"]}</span>',
                 f'<span class="num">{r["success_count"]}</span>',
                 f'<span class="num">{r["error_count"]}</span>',
                 f'<span class="num">{r["item_count"]}</span>',
                 f'<span class="num">{r["new_item_count"]}</span>',
                 f'<span class="num">{r["duplicate_item_count"]}</span>']
                for r in usage_today
            ],
            empty="no provider usage recorded today",
        )
        + _cards([
            ("Content fetches", fetches_today.get("total", 0),
             "original posts, no provider quota"),
            ("New items / request", efficiency_today.get("new_items_per_request")
             if efficiency_today.get("new_items_per_request") is not None else "-",
             "today"),
            ("Human actions today", sum(review_metrics["today"].values()),
             " ".join(f"{a}:{n}" for a, n in review_metrics["today"].items() if n)
             or "none yet"),
            ("Acquisition", acquisition_summary.get("fetched", 0),
             ", ".join(f"{k}:{v}" for k, v in
                       sorted(acquisition_summary.get("by_status", {}).items())) or "-"),
        ])
        + '<p class="note">Full detail on <a href="/admin/usage">Usage</a>, '
          '<a href="/admin/intake">Intake</a> and <a href="/admin/review">Review</a>.</p>'
        + "<h2>Provider quota (today, UTC)</h2>"
        + _table(
            ["Provider", "Requests", "Budget", "Remaining", "Last request"],
            [
                [E(name), f'<span class="num">{state.get("requests", 0)}</span>',
                 f'<span class="num">{state.get("budget", 0)}</span>',
                 _badge(state.get("remaining", 0),
                        "ok" if state.get("remaining", 0) > 0 else "bad"),
                 E(str(state.get("last_request_at") or "never")[:19])]
                for name, state in sorted(quota_state.items())
                if isinstance(state, dict)
            ],
            empty="no provider quota recorded yet",
        )
        + "<h2>Recent collection runs</h2>"
        + _table(
            ["Source", "Status", "Mode", "Found", "New", "Dup", "Started"],
            run_rows,
            empty="no collection has run yet - enable a source on the Sources page",
        )
    )
    return HTMLResponse(_page("Dashboard", "/admin", body, flash=_flash(request)))


# --- sources ----------------------------------------------------------------

def _source_decision(op: dict[str, Any]) -> str:
    """What a person decided, and what the numbers suggest if nobody has.

    The recommendation is offered with its reason attached, so an operator can
    disagree with the reasoning rather than with a verdict.
    """
    if not op:
        return "-"
    decided = op.get("operational_decision")
    recommended = op.get("recommended")
    options = "".join(
        f'<option value="{d}"{" selected" if d == (decided or recommended) else ""}>'
        f"{E(source_ops.LABELS[d])}</option>"
        for d in source_ops.DECISIONS
    )
    current = (
        _badge(decided, source_ops.TONES.get(decided, "muted"))
        + f'<div class="note">{E(str(op.get("decision_reason") or ""))[:70]}</div>'
        if decided else
        _badge(f"권고: {recommended}", "muted")
        + f'<div class="note">{E(op.get("recommendation_reason") or "")}</div>'
    )
    form = (
        f'<form class="inline" method="post" '
        f'action="/admin/sources/{op["source_id"]}/decision">'
        f'<select name="decision">{options}</select>'
        '<input name="reason" placeholder="이유 (선택)" style="width:150px">'
        "<button>Record</button></form>"
    )
    return current + form


def _source_yield(found: dict[str, Any], op: dict[str, Any] | None = None) -> str:
    """Items collected, and how many of them we could actually read.

    "21 items" reads like a working source. "21 items, 0 readable" is the same
    source and a different decision.
    """
    items = found.get("items", 0)
    if not items:
        return '<span class="num">0</span>'
    fetched = found.get("fetched", 0)
    blocked = (found.get("blocked", 0) or 0) + (found.get("login", 0) or 0)
    events = found.get("events", 0)
    tone = "ok" if fetched else "bad"
    parts = [f'<span class="num">{items}</span>']
    parts.append(f'<div class="note"><span class="badge {tone}">본문 {fetched}</span>')
    if blocked:
        parts.append(f' <span class="badge warn">차단 {blocked}</span>')
    parts.append(f' · 이벤트 {events}')
    upcoming = (op or {}).get("upcoming_events", 0)
    # The number that decides whether a source still earns its requests: a
    # hundred past events and none upcoming is a source that has stopped being
    # useful, and no total tells them apart.
    parts.append(
        f' <span class="badge ok">앞으로 {upcoming}</span>' if upcoming
        else ' <span class="badge muted">앞으로 0</span>'
    )
    parts.append("</div>")
    return "".join(parts)


# --- v0.82 Source Transparency ------------------------------------------------
#
# "K-TANGO Festival Board" told an operator nothing about which site, board
# or search query actually stands behind that name. Everything below answers
# "where is this source actually looking" and "is it actually working" from
# signals the pipeline already records - no new tracking column, no guess.

def _truncate(text: str, length: int = 70) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def _source_queries(source: dict[str, Any]) -> list[str]:
    queries = source.get("queries") or []
    if isinstance(queries, str):
        queries = json.loads(queries)
    return [str(q) for q in queries]


def _source_target(source: dict[str, Any]) -> str:
    """Where this source actually looks, in one line."""
    platform = source["platform"]
    url = source.get("url")
    queries = _source_queries(source)
    open_link = (
        f' <a href="{E(url)}" target="_blank" rel="noreferrer noopener">'
        "<button type=\"button\">Open Source</button></a>"
    ) if url else ""

    if platform in ("WEB", "DIRECTORY"):
        if not url:
            return '<span class="badge bad">no target URL</span>'
        display = url.split("://", 1)[-1]
        return f'<span title="{E(url)}">{E(_truncate(display))}</span>{open_link}'

    # NAVER_BLOG / NAVER_CAFE / DAUM_CAFE / FACEBOOK: query-driven discovery.
    # A url here (if set) is an extra filter - a cafe/domain restriction -
    # never the target itself.
    if queries:
        shown = ", ".join(f'"{E(q)}"' for q in queries[:2])
        if len(queries) > 2:
            shown += f" +{len(queries) - 2}"
        parts = [f"Query: {shown}"]
    else:
        parts = ['<span class="badge warn">no query configured</span>']
    if url:
        parts.append(
            f'<div class="note">filter: <span title="{E(url)}">{E(_truncate(url, 50))}</span></div>'
        )
    return "".join(parts) + open_link


HEALTH_ACTIVE = "ACTIVE"
HEALTH_NO_NEW_ITEMS = "NO_NEW_ITEMS"
HEALTH_FETCH_BLOCKED = "FETCH_BLOCKED"
HEALTH_AUTH_FAILED = "AUTH_FAILED"
HEALTH_PARSER_ERROR = "PARSER_ERROR"
HEALTH_STALE = "STALE"
HEALTH_DISABLED = "DISABLED"

_HEALTH_TONE = {
    HEALTH_ACTIVE: "ok", HEALTH_NO_NEW_ITEMS: "warn", HEALTH_FETCH_BLOCKED: "bad",
    HEALTH_AUTH_FAILED: "bad", HEALTH_PARSER_ERROR: "bad", HEALTH_STALE: "warn",
    HEALTH_DISABLED: "muted",
}

# How many missed collection intervals with nothing fresh before a source
# counts as STALE rather than merely between ticks. Six intervals is not a
# blip - it is the scheduler not reaching this source, or one that keeps
# failing before ever reaching record_collection_result with a real outcome.
_STALE_INTERVAL_MULTIPLE = 6


def _source_health(source: dict[str, Any], outcome: dict[str, Any]) -> str:
    """A status richer than Enabled/Disabled, derived from last_status
    (already the collector's own operator-facing classification -
    collector_errors.py), collection recency, and read yield - never a new
    tracking column, never a guess about why."""
    if not source.get("enabled"):
        return HEALTH_DISABLED
    last_status = (source.get("last_status") or "").upper()
    if last_status in ("AUTH_FAILED", "CREDENTIALS_MISSING"):
        return HEALTH_AUTH_FAILED
    if last_status == "BAD_RESPONSE":
        return HEALTH_PARSER_ERROR

    last_collected = source.get("last_collected_at")
    interval = source.get("collection_interval_minutes") or sources.DEFAULT_INTERVAL_MINUTES
    if last_collected is None:
        return HEALTH_STALE
    now = datetime.now(timezone.utc)
    last_collected = (
        last_collected if last_collected.tzinfo else last_collected.replace(tzinfo=timezone.utc)
    )
    if (now - last_collected).total_seconds() > interval * 60 * _STALE_INTERVAL_MULTIPLE:
        return HEALTH_STALE

    items = outcome.get("items", 0) or 0
    fetched = outcome.get("fetched", 0) or 0
    blocked = (outcome.get("blocked", 0) or 0) + (outcome.get("login", 0) or 0)
    events = outcome.get("events", 0) or 0
    if items and fetched == 0 and blocked:
        return HEALTH_FETCH_BLOCKED
    if fetched and not events:
        return HEALTH_NO_NEW_ITEMS
    return HEALTH_ACTIVE


def _last_success_text(when: Any) -> str:
    if when is None:
        return '<span class="badge muted">never</span>'
    return E(str(when)[:19])


def _last_error_text(entry: dict[str, Any] | None) -> str:
    if not entry:
        return '<span class="badge ok">none</span>'
    detail = E(str(entry.get("error") or "")[:80])
    return f'<span class="badge bad">{E(str(entry["at"])[:19])}</span><div class="note">{detail}</div>'


@router.get("/admin/sources", response_class=HTMLResponse)
def admin_sources(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    from . import master_admin, master_edit, pagination

    settings = _settings()
    with _connection() as con:
        total = sources.count_sources(con)
        page = pagination.resolve_page(request.query_params.get("page"), total)
        rows = sources.list_sources(
            con, limit=pagination.PAGE_SIZE, offset=pagination.sql_offset(page)
        )
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)
        outcomes = sources.acquisition_outcomes(con)
        operations = {o["source_id"]: o for o in source_ops.overview(con)}
        last_success = intake.last_success_per_source(con)
        last_error = intake.last_error_per_source(con)

    genre_by_id = {g["genre_id"]: g["code"] for g in genres}
    region_by_id = {r["region_id"]: r["name"] for r in regions}

    table_rows = []
    for source in rows:
        capability = collectors.describe_capability(source["platform"])
        enabled = source["enabled"]
        toggle = "disable" if enabled else "enable"
        actions = (
            '<div class="actionbar">'
            + master_admin.edit_form(
                master_edit.SOURCE, source["source_id"],
                [
                    master_admin.field("source_key", "Source key", source["source_key"],
                                       kind="readonly",
                                       note="엔진 config와 맞추는 키라 수정할 수 없습니다"),
                    master_admin.field("name", "Name", source["name"]),
                    master_admin.field("platform", "Platform", kind="select",
                                       options=master_admin._choices(
                                           sources.PLATFORMS, source["platform"])),
                    master_admin.field("source_role", "Role", kind="select",
                                       options=master_admin._choices(
                                           sources.SOURCE_ROLES, source["source_role"])),
                    master_admin.field("authority_level", "Authority", kind="select",
                                       options=master_admin._choices(
                                           sources.AUTHORITY_LEVELS,
                                           source["authority_level"])),
                    master_admin.field("url", "URL", source.get("url")),
                    master_admin.field("genre_id", "Genre", kind="select",
                                       options=master_admin._options(
                                           genres, id_key="genre_id", label_key="code",
                                           selected=source.get("genre_id"))),
                    master_admin.field("region_id", "Region", kind="select",
                                       options=master_admin._options(
                                           regions, id_key="region_id", label_key="name",
                                           selected=source.get("region_id"))),
                    master_admin.field(
                        "collection_interval_minutes", "Interval (minutes)",
                        source["collection_interval_minutes"], kind="number",
                        note=f"최소 {sources.MIN_INTERVAL_MINUTES}분; 저장 즉시 "
                             "다음 수집 시점 계산에 반영됩니다"),
                    master_admin.field("notes", "Notes", source.get("notes")),
                ],
                note="API Key와 Secret은 .env에만 있고 이 화면에 표시되지 않습니다. "
                     "검색어와 수집기 설정은 Test/Enable 흐름에서 관리합니다.",
            )
            + f'<form class="inline" method="post" '
            f'action="/admin/sources/{source["source_id"]}/{toggle}">'
            f"<button>{toggle.title()}</button></form>"
            + f'<form class="inline" method="post" '
            f'action="/admin/sources/{source["source_id"]}/test">'
            "<button>Test</button></form></div>"
        )
        health = _source_health(source, outcomes.get(source["source_id"], {}))
        genre_region = " ".join(
            f'<span class="badge muted">{E(v)}</span>' for v in (
                genre_by_id.get(source.get("genre_id")),
                region_by_id.get(source.get("region_id")),
            ) if v
        ) or '<span class="badge muted">-</span>'
        table_rows.append([
            f'<a href="/admin/sources/{source["source_id"]}">'
            f'<code>{E(source["source_key"])}</code><br>{E(source["name"])}</a>',
            E(source["platform"]) + "<br>" + f'<span class="badge muted">{E(source["source_role"])}</span>'
            + "<br>" + genre_region,
            _source_target(source),
            _badge(health, _HEALTH_TONE.get(health, "muted")),
            f'<span class="num">{source["collection_interval_minutes"]}m</span>',
            "Success: " + _last_success_text(last_success.get(source["source_id"]))
            + "<br>Error: " + _last_error_text(last_error.get(source["source_id"])),
            _source_yield(outcomes.get(source["source_id"], {}),
                          operations.get(source["source_id"], {})),
            _source_decision(operations.get(source["source_id"], {})),
            _badge("LIVE" if capability["live"] else "SNAPSHOT",
                   "ok" if capability["live"] else "warn")
            + f'<div class="note">{E(capability["detail"])}</div>',
            actions,
        ])

    genre_options = "".join(
        f'<option value="{g["genre_id"]}">{E(g["code"])}</option>' for g in genres
    )
    region_options = "".join(
        f'<option value="{r["region_id"]}">{E(r["name"])}</option>' for r in regions
    )
    platform_options = "".join(f"<option>{p}</option>" for p in sources.PLATFORMS)
    role_options = "".join(f"<option>{r}</option>" for r in sources.SOURCE_ROLES)
    authority_options = "".join(f"<option>{a}</option>" for a in sources.AUTHORITY_LEVELS)

    add_form = f"""
<details><summary>Add Source</summary>
<form method="post" action="/admin/sources">
  <div class="grid">
    <div><label>Source key</label><input name="source_key" required placeholder="SRC-D-003"></div>
    <div><label>Name</label><input name="name" required></div>
    <div><label>Platform</label><select name="platform">{platform_options}</select></div>
    <div><label>Role</label><select name="source_role">{role_options}</select></div>
    <div><label>Authority</label><select name="authority_level">{authority_options}</select></div>
    <div><label>Genre</label><select name="genre_id"><option value="">-</option>{genre_options}</select></div>
    <div><label>Region</label><select name="region_id"><option value="">-</option>{region_options}</select></div>
    <div><label>URL (optional)</label><input name="url" placeholder="https://..."></div>
    <div><label>Search queries (comma separated)</label><input name="queries" placeholder="밀롱가, 서울 밀롱가"></div>
    <div><label>Interval (minutes, min {sources.MIN_INTERVAL_MINUTES})</label>
      <input name="collection_interval_minutes" type="number" value="60"
             min="{sources.MIN_INTERVAL_MINUTES}"></div>
    <div><label>Notes</label><input name="notes"></div>
  </div>
  <div class="actions"><button class="primary">Add Source</button></div>
  <p class="note">New sources start disabled. Test one before enabling it -
  the scheduler collects only from enabled sources whose interval has elapsed.</p>
</form></details>"""

    csv_bar = (
        '<p class="actions">'
        '<a href="/admin/sources/export.csv"><button>Export CSV</button></a> '
        '<a href="/admin/sources/import"><button>Import CSV</button></a>'
        "</p>"
    )
    body = (
        "<h2>Sources</h2>" + add_form + csv_bar
        + _table(
            ["Source", "Platform / Genre / Region", "Target", "Health", "Interval",
             "Last Success / Error", "Items / readable", "Decision", "Collector", "Actions"],
            table_rows,
            empty="no source registered yet",
        )
        + f'<p class="note">Engine root: <code>{E(str(settings.engine_root))}</code>. '
          "Live collection needs the platform's API credentials in <code>.env</code>; "
          "without them a source can still be tested against a recorded snapshot.</p>"
        + pagination.nav("/admin/sources", {}, page, total)
    )
    return HTMLResponse(_page("Sources", "/admin/sources", body, flash=_flash(request)))


# --- source CSV import/export -------------------------------------------------

@router.get("/admin/sources/export.csv")
def admin_sources_export_csv(_: str = Depends(require_admin)) -> Response:
    from . import source_csv

    with _connection() as con:
        rows = source_csv.export_rows(con)
    body = source_csv.to_csv(rows)
    filename = source_csv.export_filename()
    return Response(
        content=body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/sources/import/template.csv")
def admin_sources_import_template(_: str = Depends(require_admin)) -> Response:
    from . import source_csv

    return Response(
        content=source_csv.template_csv(), media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="dancemate_sources_template.csv"'
        },
    )


def _source_preview_rows_table(preview_result: dict[str, Any]) -> str:
    tone = {"NEW": "ok", "UPDATE": "warn", "INVALID": "bad"}
    rows = []
    for entry in preview_result["rows"]:
        detail = (
            E("; ".join(entry["errors"])) if entry["errors"]
            else E("; ".join(entry["reasons"])) if entry["reasons"]
            else "-"
        )
        rows.append([
            str(entry["row"]),
            _badge(entry["status"], tone.get(entry["status"], "muted")),
            E(entry["source_key"] or "-"),
            E(entry["name"] or "-"),
            E(entry["platform"] or "-"),
            E(entry["genre"] or "-"),
            E(entry["region"] or "-"),
            "true" if entry["enabled"] else "false",
            detail,
        ])
    return _table(
        ["Row", "Status", "Source key", "Name", "Platform", "Genre", "Region", "Enabled", "Detail"],
        rows, empty="the file has no data rows",
    )


@router.get("/admin/sources/import", response_class=HTMLResponse)
def admin_sources_import_form(
    request: Request, _: str = Depends(require_admin)
) -> HTMLResponse:
    from . import source_csv

    body = f"""<h2>Import Sources (CSV)</h2>
<p class="note">Nothing is written until you review a preview and press Confirm.
<a href="/admin/sources/import/template.csv">Download the template</a> for the
expected columns — {E(", ".join(source_csv.TEMPLATE_COLUMNS))},
queries separated by <code>|</code>. Rows are matched by <code>id</code> or
<code>source_key</code>; anything unmatched is created new. Enabling a source
through import still has to pass the same checks Enable does on the Sources
page — a row missing what its platform needs to collect is rejected, not
written broken.</p>
<form method="post" action="/admin/sources/import" enctype="multipart/form-data">
  <div class="grid">
    <div><label>CSV file (max 5MB)</label><input type="file" name="csvfile" accept=".csv" required></div>
  </div>
  <div class="actions"><button class="primary">Preview</button></div>
</form>"""
    return HTMLResponse(
        _page("Import Sources", "/admin/sources", body, flash=_flash(request))
    )


@router.post("/admin/sources/import", response_class=HTMLResponse)
async def admin_sources_import_preview(
    csvfile: UploadFile, _: str = Depends(require_admin)
) -> HTMLResponse:
    import base64

    from . import source_csv

    raw = await csvfile.read()
    if len(raw) > source_csv.MAX_UPLOAD_BYTES:
        return _back(
            "/admin/sources/import",
            f"file is over the {source_csv.MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
            "bad",
        )
    try:
        rows = source_csv.parse_csv(raw)
    except (source_csv.ImportTooLarge, UnicodeDecodeError) as exc:
        return _back("/admin/sources/import", f"could not read the file: {exc}", "bad")

    with _connection() as con:
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)
        result = source_csv.preview(con, rows, genres=genres, regions=regions)

    counts = result["counts"]
    cards = _cards([
        ("Rows", result["total"], "parsed from the file"),
        ("New", counts["NEW"], "will be created"),
        ("Update", counts["UPDATE"], "matched by id or source_key"),
        ("Invalid", counts["INVALID"], "must be fixed before Confirm"),
    ])
    can_confirm = counts["INVALID"] == 0 and result["total"] > 0
    confirm_form = ""
    if can_confirm:
        encoded = base64.b64encode(raw).decode("ascii")
        confirm_form = f"""
<form method="post" action="/admin/sources/import/confirm">
  <input type="hidden" name="csv_b64" value="{E(encoded)}">
  <input type="hidden" name="filename" value="{E(csvfile.filename or 'import.csv')}">
  <div class="actions"><button class="primary">Confirm Import</button>
  <a href="/admin/sources/import"><button type="button">Cancel</button></a></div>
</form>"""
    else:
        confirm_form = (
            '<p class="note">Fix the INVALID rows and upload again — '
            "Confirm is disabled while any row is invalid.</p>"
            if counts["INVALID"] else
            '<p class="note">Nothing to import — the file has no data rows.</p>'
        )

    body = (
        "<h2>Import Preview</h2>" + cards + confirm_form
        + _source_preview_rows_table(result)
    )
    return HTMLResponse(_page("Import Preview", "/admin/sources", body))


@router.post("/admin/sources/import/confirm")
def admin_sources_import_confirm(
    csv_b64: str = Form(...), filename: str = Form("import.csv"),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    import base64

    from . import source_csv

    try:
        raw = base64.b64decode(csv_b64)
        rows = source_csv.parse_csv(raw)
    except Exception as exc:
        return _back("/admin/sources", f"could not re-read the upload: {exc}", "bad")

    try:
        with _connection() as con:
            genres = master_data.list_genres(con)
            regions = master_data.list_regions(con)
            # Re-derived from the same rows Preview showed - a stale or
            # tampered confirm can never apply something Preview never saw.
            result = source_csv.preview(con, rows, genres=genres, regions=regions)
            # One savepoint-backed transaction for the whole batch: a failure
            # partway through must not leave earlier rows committed under an
            # autocommit connection that would otherwise commit each
            # statement as it runs.
            with con.transaction():
                applied = source_csv.apply_import(
                    con, result["rows"], reviewer=reviewer, filename=filename
                )
    except source_csv.ImportRejected as exc:
        return _back("/admin/sources", str(exc), "bad")
    except Exception as exc:
        return _back("/admin/sources", f"import failed: {exc}", "bad")

    return _back(
        "/admin/sources",
        f"imported {filename}: {applied['created']} created, "
        f"{applied['updated']} updated, {applied['noop']} unchanged",
    )


# --- source detail ------------------------------------------------------------

@router.get("/admin/sources/{source_id}", response_class=HTMLResponse)
def admin_source_detail(
    source_id: int, request: Request, _: str = Depends(require_admin)
) -> HTMLResponse:
    """Everything an operator needs to answer "where is this actually
    looking, and is it working" about one source, in one screen
    (v0.82 Source Transparency)."""
    with _connection() as con:
        source = sources.get_source(con, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="source not found")
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)
        outcomes = sources.acquisition_outcomes(con)
        upcoming = source_ops.upcoming_yield(con)
        breakdown = source_ops.event_breakdown(con, source_id)
        recent = intake.recent_items(con, source_id=source_id, limit=10)
        last_success = intake.last_success_per_source(con)
        last_error = intake.last_error_per_source(con)

    genre_by_id = {g["genre_id"]: g["code"] for g in genres}
    region_by_id = {r["region_id"]: r["name"] for r in regions}
    capability = collectors.describe_capability(source["platform"])
    outcome = outcomes.get(source_id, {})
    health = _source_health(source, outcome)

    facts = _table(
        ["Field", "Value"],
        [
            ["Name", E(source["name"])],
            ["Source key", f'<code>{E(source["source_key"])}</code>'],
            ["Platform", E(source["platform"])],
            ["Role", E(source["source_role"])],
            ["Authority", E(source["authority_level"])],
            ["Genre", E(genre_by_id.get(source.get("genre_id")) or "-")],
            ["Region", E(region_by_id.get(source.get("region_id")) or "-")],
            ["Target", _source_target(source)],
            ["Collection interval", f'{source["collection_interval_minutes"]} minutes'],
            ["Enabled", _badge("ENABLED" if source["enabled"] else "DISABLED",
                               "ok" if source["enabled"] else "muted")],
            ["Collector", _badge("LIVE" if capability["live"] else "SNAPSHOT",
                                 "ok" if capability["live"] else "warn")
             + f'<div class="note">{E(capability["detail"])}</div>'],
            ["Notes", E(source.get("notes") or "-")],
            ["Created", E(str(source.get("created_at") or "-")[:19])],
            ["Updated", E(str(source.get("updated_at") or "-")[:19])],
        ],
        empty="-",
    )

    health_panel = (
        '<div class="tablewrap" style="padding:12px 16px">'
        '<dl style="display:grid;grid-template-columns:auto 1fr;gap:.4rem 1rem;margin:0">'
        f'<dt>Health</dt><dd>{_badge(health, _HEALTH_TONE.get(health, "muted"))}</dd>'
        f'<dt>Last Success</dt><dd>{_last_success_text(last_success.get(source_id))}</dd>'
        f'<dt>Last Error</dt><dd>{_last_error_text(last_error.get(source_id))}</dd>'
        "</dl></div>"
    )

    coverage = _cards([
        ("Items collected", outcome.get("items", 0) or 0, "all time"),
        ("Body readable", outcome.get("fetched", 0) or 0,
         f"blocked {outcome.get('blocked', 0) or 0}, login {outcome.get('login', 0) or 0}"),
        ("Upcoming events", upcoming.get(source_id, 0), "listed, today or later"),
        ("Past events", breakdown.get("past", 0), "listed, before today"),
        ("No event produced", breakdown.get("no_event", 0),
         "ingested, no event came of it - non-event post or unparseable date"),
        ("Acquisition blocked", breakdown.get("blocked", 0), "body could not be read"),
    ])

    recent_rows = []
    for item in recent:
        recent_rows.append([
            E(str(item.get("collected_at") or "-")[:19]),
            f'<a href="{E(item["url"])}" target="_blank" rel="noreferrer noopener">'
            f'{E(str(item.get("title") or "-")[:70])}</a>' if item.get("url")
            else E(str(item.get("title") or "-")[:70]),
            E(str(item.get("published_at") or "-")[:19]),
            _badge(item.get("ingest_state") or "-",
                   "ok" if item.get("ingest_state") == "INGESTED" else "muted"),
        ])
    recent_table = _table(
        ["Collected", "Title", "Published", "Ingest state"], recent_rows,
        empty="nothing collected from this source yet",
    )

    queries = _source_queries(source)
    raw_config = f"""
<details><summary>Raw config</summary>
<div class="tablewrap" style="padding:12px 16px">
<pre style="white-space:pre-wrap;word-break:break-word;margin:0;font:13px/1.6 ui-monospace,monospace">{E(json.dumps({
    "url": source.get("url"),
    "queries": queries,
    "config": source.get("config") or {},
}, ensure_ascii=False, indent=2))}</pre>
</div>
<p class="note">API keys and secrets are never stored here - they live only in <code>.env</code>.</p>
</details>"""

    body = (
        f'<p class="sub"><a href="/admin/sources">&larr; Sources</a></p>'
        f"<h2>{E(source['name'])}</h2>"
        + facts + health_panel + coverage
        + "<h2>Recent Items</h2>" + recent_table
        + raw_config
        + '<p class="note"><a href="/admin/sources">back to Sources</a></p>'
    )
    return HTMLResponse(
        _page(f"Source: {source['name']}", "/admin/sources", body, flash=_flash(request))
    )


@router.post("/admin/sources")
def admin_create_source(
    source_key: str = Form(...),
    name: str = Form(...),
    platform: str = Form(...),
    source_role: str = Form(...),
    authority_level: str = Form("UNKNOWN"),
    genre_id: str = Form(""),
    region_id: str = Form(""),
    url: str = Form(""),
    queries: str = Form(""),
    collection_interval_minutes: int = Form(60),
    notes: str = Form(""),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    query_list = [q.strip() for q in queries.split(",") if q.strip()]
    try:
        with _connection() as con:
            created = sources.create_source(
                con,
                source_key=source_key, name=name, platform=platform,
                source_role=source_role, authority_level=authority_level,
                genre_id=int(genre_id) if genre_id else None,
                region_id=int(region_id) if region_id else None,
                url=url.strip() or None, queries=query_list,
                collection_interval_minutes=int(collection_interval_minutes),
                notes=notes.strip() or None,
            )
    except sources.SourceValidationError as exc:
        return _back("/admin/sources", str(exc), "bad")
    except Exception as exc:
        return _back("/admin/sources", f"could not add source: {exc}", "bad")
    return _back("/admin/sources", f"added {created['source_key']} (disabled)")


@router.post("/admin/sources/{source_id}/decision")
def admin_source_decision(
    source_id: int,
    decision: str = Form(...),
    reason: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    """Record an operator's decision about a source. Collection is unchanged.

    Writing down "replace this" and actually stopping collection are two steps
    on purpose: an operator often wants the note before the action, and a
    blocked community that fixes its settings next week should not have been
    dropped this week.
    """
    try:
        with _connection() as con:
            updated = source_ops.set_decision(
                con, source_id, decision.strip().upper(), reviewer=reviewer,
                reason=reason,
            )
    except Exception as exc:
        return _back("/admin/sources", f"could not record decision: {exc}", "bad")
    if updated is None:
        return _back("/admin/sources", f"no source {source_id}", "bad")
    return _back("/admin/sources",
                 f"{updated['source_key']}: {decision.strip().upper()} 기록됨")


@router.post("/admin/sources/{source_id}/{action}", response_model=None)
def admin_source_action(
    source_id: int, action: str, request: Request, _: str = Depends(require_admin)
) -> HTMLResponse | RedirectResponse:
    if action not in ("enable", "disable", "test"):
        raise HTTPException(status_code=404, detail="unknown action")
    settings = _settings()
    with _connection() as con:
        source = sources.get_source(con, source_id)
        if source is None:
            return _back("/admin/sources", f"source {source_id} not found", "bad")
        if action in ("enable", "disable"):
            sources.set_enabled(con, source_id, action == "enable")
            return _back("/admin/sources", f"{source['source_key']} {action}d")
        report = collectors.test_source(settings, source)

    return HTMLResponse(_page(
        f"Test: {source['name']}", "/admin/sources",
        _source_test_report(source, report), flash=_flash(request),
    ))


def _source_test_report(source: dict[str, Any], report: dict[str, Any]) -> str:
    """The [Test] button's result (v0.82 Section 12): a dry run, nothing
    written - discovery only, the same collect() the scheduler would call,
    reported in full instead of squeezed into a one-line flash message."""
    status = report.get("status")
    tone = {"PASS": "ok", "PASS_SNAPSHOT": "warn", "PASS_NO_MATCH": "warn"}.get(status, "bad")
    rows = [
        ["Source", E(source["name"]) + f' (<code>{E(source["source_key"])}</code>)'],
        ["Target", _source_target(source)],
        ["Result", _badge(status or "-", tone)],
        ["Mode", E(report.get("mode") or ("SNAPSHOT" if status == "PASS_SNAPSHOT" else "-"))],
        ["Discovered", f'<span class="num">{report.get("items", 0)}</span>'],
    ]
    if status == "PASS_SNAPSHOT":
        missing = ", ".join(report.get("missing_credentials") or []) or "credentials"
        rows.append(["Warning", E(
            f"SNAPSHOT, NOT LIVE - {missing} missing; the scheduler will skip this source"
        )])
    if report.get("missing_credentials"):
        rows.append(["Missing credentials", E(", ".join(report["missing_credentials"]))])
    if report.get("provider_results") is not None:
        rows.append(["Provider returned", f'<span class="num">{report["provider_results"]}</span>'])
        rows.append(["Matched this source's filter", f'<span class="num">{report.get("items", 0)}</span>'])
    if report.get("detail"):
        rows.append(["Detail", E(str(report["detail"])[:400])])
    sample = report.get("sample_titles") or []
    if sample:
        rows.append(["Sample titles", "<br>".join(E(t) for t in sample)])

    body = (
        f'<p class="sub"><a href="/admin/sources">&larr; Sources</a></p>'
        f"<h2>Source Test</h2>"
        + _table(["Field", "Value"], rows, empty="-")
        + '<p class="note">Nothing was written to the database - this is discovery only, '
          "the same call the scheduler would make on its next tick. Body fetch and event "
          "extraction happen later, in the normal collection pipeline.</p>"
    )
    return body


# --- venues -----------------------------------------------------------------

def _venue_edit(venue: dict[str, Any], regions: list[dict[str, Any]],
                aliases: list[dict[str, Any]], usage: dict[int, int]) -> str:
    """The venue's own record, opened where it is listed and already filled in."""
    from . import master_admin, master_edit

    return master_admin.edit_form(
        master_edit.VENUE, venue["venue_id"],
        [
            master_admin.field("name", "Name", venue["name"]),
            master_admin.field(
                "region_id", "Region", kind="select",
                options=master_admin._options(
                    regions, id_key="region_id", label_key="name",
                    selected=venue.get("region_id"),
                ),
            ),
            master_admin.field("address", "Address", venue.get("address")),
            master_admin.field("notes", "Notes", venue.get("notes")),
        ],
        extra=master_admin.alias_editor(venue, aliases, usage),
        note="이름을 바꿔도 같은 장소로 남습니다 — 연결된 Event는 그대로입니다.",
    )


def _venue_actions(venue: dict[str, Any]) -> str:
    """Delete, unlink-and-delete or deactivate, whichever this venue allows.

    A venue nothing references can simply go. One that events point at cannot
    be deleted by the same button and the same click: the confirmation names
    how many events would change, because finding that out afterwards is not a
    confirmation.
    """
    venue_id = venue["venue_id"]
    toggle = (
        f'<form class="inline" method="post" action="/admin/venues/{venue_id}/enabled">'
        f'<input type="hidden" name="enabled" value="{"0" if venue["enabled"] else "1"}">'
        f'<button>{"Deactivate" if venue["enabled"] else "Reactivate"}</button></form>'
    )
    if not venue["in_use"]:
        confirm = (
            f'<details><summary>Delete</summary>'
            f'<p class="note">이 장소는 어떤 Event에서도 쓰이지 않습니다. '
            f'삭제하면 alias {len(venue.get("aliases") or [])}건도 함께 사라집니다.</p>'
            f'<form method="post" action="/admin/venues/{venue_id}/delete">'
            '<div class="actions"><button>확인, 삭제합니다</button></div></form></details>'
        )
    else:
        confirm = (
            f'<details><summary>Unlink &amp; Delete</summary>'
            f'<p class="note"><strong>이 장소는 Event {venue["events"]}건에서 사용 중입니다.</strong> '
            "삭제하면 해당 Event는 게시글에서 읽은 원래 문자열로 되돌아가고 "
            "(사용자 화면에서 다시 &quot;미확인&quot;), 그 문자열은 Unresolved 대기열로 "
            "돌아갑니다. 게시글·근거·Event·리뷰는 그대로 남습니다.</p>"
            f'<form method="post" action="/admin/venues/{venue_id}/delete">'
            '<input type="hidden" name="unlink" value="1">'
            '<div class="actions"><button>확인, 해제하고 삭제합니다</button></div>'
            "</form></details>"
        )
    return toggle + confirm


@router.get("/admin/venues", response_class=HTMLResponse)
def admin_venues(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    from . import pagination, venue_resolution  # local: keeps the v0.75 console import list stable

    with _connection() as con:
        total = master_data.count_venues(con)
        page = pagination.resolve_page(request.query_params.get("page"), total)
        venues = venue_resolution.venues_with_usage(
            con, limit=pagination.PAGE_SIZE,
            offset=pagination.sql_offset(page),
        )
        regions = master_data.list_regions(con)
        alias_rows = {v["venue_id"]: master_data.venue_aliases(con, v["venue_id"])
                      for v in venues}
        alias_usage = {v["venue_id"]: master_data.venue_alias_usage(con, v["venue_id"])
                       for v in venues}

    rows = [
        [E(v["name"]), E(str(v.get("region_name") or "-")), E(str(v.get("address") or "-")),
         ", ".join(E(a) for a in (v.get("aliases") or [])) or "-",
         (f'<strong>{v["events"]}</strong>'
          + (f' <span class="muted">({v["listed_events"]} listed)</span>'
             if v["listed_events"] else "")
          if v["events"] else '<span class="muted">0</span>'),
         _badge("ENABLED" if v["enabled"] else "DISABLED", "ok" if v["enabled"] else "muted"),
         '<div class="actionbar">'
         + _venue_edit(v, regions, alias_rows.get(v["venue_id"], []),
                       alias_usage.get(v["venue_id"], {}))
         + _venue_actions(v) + "</div>"]
        for v in venues
    ]
    region_options = "".join(
        f'<option value="{r["region_id"]}">{E(r["name"])}</option>' for r in regions
    )
    add_form = f"""
<details><summary>Add Venue</summary>
<form method="post" action="/admin/venues">
  <div class="grid">
    <div><label>Name</label><input name="name" required></div>
    <div><label>Region</label><select name="region_id"><option value="">-</option>{region_options}</select></div>
    <div><label>Address</label><input name="address"></div>
    <div><label>Aliases (comma separated)</label>
      <input name="aliases" placeholder="La Ventana, 라벤타나, 벤타나"></div>
    <div><label>Notes</label><input name="notes"></div>
  </div>
  <div class="actions"><button class="primary">Add Venue</button></div>
  <p class="note">Aliases are how "La Ventana", "라벤타나" and "벤타나" resolve to
  one venue. The venue name is registered as an alias automatically.</p>
</form></details>"""

    csv_bar = (
        '<p class="actions">'
        '<a href="/admin/venues/export.csv"><button>Export CSV</button></a> '
        '<a href="/admin/venues/import"><button>Import CSV</button></a>'
        "</p>"
    )
    body = ('<h2>Venues</h2>'
            '<p class="note">Venue strings read from posts that this list does '
            'not recognise are queued at '
            '<a href="/admin/venues/unresolved">Unresolved Venues</a>. '
            'Deleting a venue removes the link and nothing else — the posts, '
            'the evidence and the events stay, and the strings they were read '
            'from go back in that queue.</p>'
            ) + csv_bar + add_form + _table(
        ["Name", "Region", "Address", "Aliases", "Events using", "State", "Actions"], rows,
        empty="no venue registered yet",
    ) + pagination.nav("/admin/venues", {}, page, total)
    return HTMLResponse(_page("Venues", "/admin/venues", body, flash=_flash(request)))


@router.post("/admin/venues")
def admin_create_venue(
    name: str = Form(...),
    region_id: str = Form(""),
    address: str = Form(""),
    aliases: str = Form(""),
    notes: str = Form(""),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
    try:
        with _connection() as con:
            master_data.create_venue(
                con, name=name, region_id=int(region_id) if region_id else None,
                address=address.strip() or None, notes=notes.strip() or None,
                aliases=alias_list,
            )
    except Exception as exc:
        return _back("/admin/venues", f"could not add venue: {exc}", "bad")
    return _back("/admin/venues", f"added venue {name}")


# --- venue CSV import/export -------------------------------------------------

@router.get("/admin/venues/export.csv")
def admin_venues_export_csv(_: str = Depends(require_admin)) -> Response:
    from . import venue_csv

    with _connection() as con:
        rows = venue_csv.export_rows(con)
    body = venue_csv.to_csv(rows)
    filename = venue_csv.export_filename()
    return Response(
        content=body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/venues/import/template.csv")
def admin_venues_import_template(_: str = Depends(require_admin)) -> Response:
    from . import venue_csv

    return Response(
        content=venue_csv.template_csv(), media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="dancemate_venues_template.csv"'
        },
    )


def _preview_rows_table(preview_result: dict[str, Any]) -> str:
    tone = {
        "NEW": "ok", "UPDATE": "warn", "DUPLICATE": "bad", "INVALID": "bad",
    }
    rows = []
    for entry in preview_result["rows"]:
        detail = (
            E("; ".join(entry["errors"])) if entry["errors"]
            else E("; ".join(entry["reasons"])) if entry["reasons"]
            else "-"
        )
        rows.append([
            str(entry["row"]),
            _badge(entry["status"], tone.get(entry["status"], "muted")),
            E(entry["name"] or "-"),
            E(entry["region"] or "-"),
            E(entry["address"] or "-"),
            E(", ".join(entry["aliases"]) or "-"),
            detail,
        ])
    return _table(
        ["Row", "Status", "Name", "Region", "Address", "Aliases", "Detail"],
        rows, empty="the file has no data rows",
    )


@router.get("/admin/venues/import", response_class=HTMLResponse)
def admin_venues_import_form(
    request: Request, _: str = Depends(require_admin)
) -> HTMLResponse:
    body = f"""<h2>Import Venues (CSV)</h2>
<p class="note">Nothing is written until you review a preview and press Confirm.
<a href="/admin/venues/import/template.csv">Download the template</a> for the
expected columns — {E(", ".join(("name", "region", "address", "aliases", "notes", "active")))},
aliases separated by <code>|</code>.</p>
<form method="post" action="/admin/venues/import" enctype="multipart/form-data">
  <div class="grid">
    <div><label>CSV file (max 5MB)</label><input type="file" name="csvfile" accept=".csv" required></div>
  </div>
  <div class="actions"><button class="primary">Preview</button></div>
</form>"""
    return HTMLResponse(
        _page("Import Venues", "/admin/venues", body, flash=_flash(request))
    )


@router.post("/admin/venues/import", response_class=HTMLResponse)
async def admin_venues_import_preview(
    csvfile: UploadFile, _: str = Depends(require_admin)
) -> HTMLResponse:
    import base64

    from . import venue_csv

    raw = await csvfile.read()
    if len(raw) > venue_csv.MAX_UPLOAD_BYTES:
        return _back(
            "/admin/venues/import",
            f"file is over the {venue_csv.MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
            "bad",
        )
    try:
        rows = venue_csv.parse_csv(raw)
    except (venue_csv.ImportTooLarge, UnicodeDecodeError) as exc:
        return _back("/admin/venues/import", f"could not read the file: {exc}", "bad")

    with _connection() as con:
        result = venue_csv.preview(con, rows)

    counts = result["counts"]
    cards = _cards([
        ("Rows", result["total"], "parsed from the file"),
        ("New", counts["NEW"], "will be created"),
        ("Update", counts["UPDATE"], "matched to an existing venue"),
        ("Duplicate", counts["DUPLICATE"],
         "same name, different address — never auto-merged"),
        ("Invalid", counts["INVALID"], "must be fixed before Confirm"),
    ])
    can_confirm = counts["INVALID"] == 0 and result["total"] > 0
    confirm_form = ""
    if can_confirm:
        encoded = base64.b64encode(raw).decode("ascii")
        confirm_form = f"""
<form method="post" action="/admin/venues/import/confirm">
  <input type="hidden" name="csv_b64" value="{E(encoded)}">
  <input type="hidden" name="filename" value="{E(csvfile.filename or 'import.csv')}">
  <div class="actions"><button class="primary">Confirm Import</button>
  <a href="/admin/venues/import"><button type="button">Cancel</button></a></div>
</form>"""
    else:
        confirm_form = (
            '<p class="note">Fix the INVALID rows and upload again — '
            "Confirm is disabled while any row is invalid.</p>"
            if counts["INVALID"] else
            '<p class="note">Nothing to import — the file has no data rows.</p>'
        )

    body = (
        "<h2>Import Preview</h2>" + cards + confirm_form
        + _preview_rows_table(result)
    )
    return HTMLResponse(_page("Import Preview", "/admin/venues", body))


@router.post("/admin/venues/import/confirm")
def admin_venues_import_confirm(
    csv_b64: str = Form(...), filename: str = Form("import.csv"),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    import base64

    from . import venue_csv

    try:
        raw = base64.b64decode(csv_b64)
        rows = venue_csv.parse_csv(raw)
    except Exception as exc:
        return _back("/admin/venues", f"could not re-read the upload: {exc}", "bad")

    try:
        with _connection() as con:
            # Re-derived from the same rows Preview showed - a stale or
            # tampered confirm can never apply something Preview never saw.
            result = venue_csv.preview(con, rows)
            # One savepoint-backed transaction for the whole batch: a failure
            # on row 8 of 10 must not leave rows 1-7 committed under an
            # autocommit connection that would otherwise commit each
            # statement as it runs.
            with con.transaction():
                applied = venue_csv.apply_import(
                    con, result["rows"], reviewer=reviewer, filename=filename
                )
    except venue_csv.ImportRejected as exc:
        return _back("/admin/venues", str(exc), "bad")
    except Exception as exc:
        return _back("/admin/venues", f"import failed: {exc}", "bad")

    return _back(
        "/admin/venues",
        f"imported {filename}: {applied['created']} created, "
        f"{applied['updated']} updated, {applied['noop']} unchanged, "
        f"{applied['duplicate_skipped']} duplicate(s) skipped",
    )


# --- organizers -------------------------------------------------------------

@router.get("/admin/organizers", response_class=HTMLResponse)
def admin_organizers(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    from . import pagination

    with _connection() as con:
        total = master_data.count_organizers(con)
        page = pagination.resolve_page(request.query_params.get("page"), total)
        organizers = master_data.list_organizers(
            con, limit=pagination.PAGE_SIZE, offset=pagination.sql_offset(page)
        )
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)

    from . import master_admin, master_edit

    rows = [
        [E(o["name"]), E(str(o.get("genre_code") or "-")), E(str(o.get("region_name") or "-")),
         E(str(o.get("contact_url") or "-")),
         _badge("ENABLED" if o["enabled"] else "DISABLED", "ok" if o["enabled"] else "muted"),
         '<div class="actionbar">'
         + master_admin.edit_form(
             master_edit.ORGANIZER, o["organizer_id"],
             [
                 master_admin.field("name", "Name", o["name"]),
                 master_admin.field(
                     "genre_id", "Genre", kind="select",
                     options=master_admin._options(
                         genres, id_key="genre_id", label_key="code",
                         selected=o.get("genre_id")),
                 ),
                 master_admin.field(
                     "region_id", "Region", kind="select",
                     options=master_admin._options(
                         regions, id_key="region_id", label_key="name",
                         selected=o.get("region_id")),
                 ),
                 master_admin.field("contact_url", "Contact URL", o.get("contact_url")),
                 master_admin.field("notes", "Notes", o.get("notes")),
             ],
             note="이름을 바꿔도 같은 주최자로 남습니다 — 연결된 Event는 그대로입니다.",
         )
         + master_admin.toggle_form(master_edit.ORGANIZER, o["organizer_id"], o["enabled"])
         + "</div>"]
        for o in organizers
    ]
    genre_options = "".join(
        f'<option value="{g["genre_id"]}">{E(g["code"])}</option>' for g in genres
    )
    region_options = "".join(
        f'<option value="{r["region_id"]}">{E(r["name"])}</option>' for r in regions
    )
    add_form = f"""
<details><summary>Add Organizer</summary>
<form method="post" action="/admin/organizers">
  <div class="grid">
    <div><label>Name</label><input name="name" required></div>
    <div><label>Genre</label><select name="genre_id"><option value="">-</option>{genre_options}</select></div>
    <div><label>Region</label><select name="region_id"><option value="">-</option>{region_options}</select></div>
    <div><label>Contact URL</label><input name="contact_url" placeholder="https://..."></div>
    <div><label>Notes</label><input name="notes"></div>
  </div>
  <div class="actions"><button class="primary">Add Organizer</button></div>
  <p class="note">Store only what operations needs. No personal contact details.</p>
</form></details>"""

    body = ("<h2>Organizers</h2>"
            '<p class="note">주최자는 삭제하지 않고 Disable 합니다 — 이미 연결된 '
            "Event가 계속 해석되어야 합니다.</p>" + add_form) + _table(
        ["Name", "Genre", "Region", "Contact", "State", "Actions"], rows,
        empty="no organizer registered yet",
    ) + pagination.nav("/admin/organizers", {}, page, total)
    return HTMLResponse(_page("Organizers", "/admin/organizers", body, flash=_flash(request)))


@router.post("/admin/organizers")
def admin_create_organizer(
    name: str = Form(...),
    genre_id: str = Form(""),
    region_id: str = Form(""),
    contact_url: str = Form(""),
    notes: str = Form(""),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    try:
        with _connection() as con:
            master_data.create_organizer(
                con, name=name, genre_id=int(genre_id) if genre_id else None,
                region_id=int(region_id) if region_id else None,
                contact_url=contact_url.strip() or None, notes=notes.strip() or None,
            )
    except Exception as exc:
        return _back("/admin/organizers", f"could not add organizer: {exc}", "bad")
    return _back("/admin/organizers", f"added organizer {name}")


# --- candidates -------------------------------------------------------------

@router.get("/admin/candidates", response_class=HTMLResponse)
def admin_candidates(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    settings = _settings()
    rows_data = candidates.list_candidates(settings, limit=200)
    counts = candidates.counts(settings)

    rows = []
    for c in rows_data:
        source_link = (
            f'<a href="{E(c["source_url"])}" rel="noreferrer noopener" target="_blank">View Source</a>'
            if c.get("source_url") else "-"
        )
        rows.append([
            E(str(c.get("event_name") or c.get("post_title") or "-")),
            E(str(c.get("event_date") or "-")),
            E(str(c.get("start_time") or "-")),
            E(str(c.get("end_time") or "-")),
            E(str(c.get("venue") or "-")),
            E(str(c.get("event_type") or "-")),
            E(str(c.get("source_id") or "-")),
            _badge(c["candidate_status"], c["status_tone"]),
            E(str(c.get("collected_at") or "-")[:19]),
            source_link,
        ])

    if counts.get("available"):
        summary_cards = _cards([
            ("Candidates", counts["total"], f"{counts['review_pending']} not settled"),
            ("Raw posts", counts["raw_posts"], "collected by the engine"),
            ("Event instances", counts["event_instances"], "identity-resolved"),
            ("Statuses", len(counts["by_status"]),
             ", ".join(f"{k}:{v}" for k, v in sorted(counts["by_status"].items())) or "-"),
        ])
    else:
        summary_cards = (
            f'<p class="flash bad">Information Engine store not readable: '
            f'{E(str(counts.get("detail", "")))}</p>'
        )

    body = (
        "<h2>Event Candidates</h2>" + summary_cards
        + '<p class="note">Read-only in v0.75. APPROVE / EDIT / REJECT / DUPLICATE / '
          "CONFIRM arrive with the v0.76 Human Verification Console; the console cannot "
          "grant VERIFIED.</p>"
        + _table(
            ["Event", "Date", "Start", "End", "Venue", "Type", "Source", "Status",
             "Collected", ""],
            rows,
            empty="the Information Engine has produced no candidate yet",
        )
    )
    return HTMLResponse(_page("Candidates", "/admin/candidates", body, flash=_flash(request)))


# --- genres and regions -----------------------------------------------------

@router.get("/admin/master", response_class=HTMLResponse)
def admin_master(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    from . import pagination

    with _connection() as con:
        genre_total = master_data.count_genres(con)
        genre_page = pagination.resolve_page(
            request.query_params.get("genre_page"), genre_total)
        genres = master_data.list_genres(
            con, limit=pagination.PAGE_SIZE, offset=pagination.sql_offset(genre_page))
        region_total = master_data.count_regions(con)
        region_page = pagination.resolve_page(
            request.query_params.get("region_page"), region_total)
        regions = master_data.list_regions(
            con, limit=pagination.PAGE_SIZE, offset=pagination.sql_offset(region_page))

    from . import master_admin, master_edit

    code_note = "code는 다른 레코드가 이 행을 가리키는 이름이라 수정할 수 없습니다"
    genre_rows = [
        [f'<code>{E(g["code"])}</code>', E(g["name"]),
         _badge("ENABLED" if g["enabled"] else "DISABLED", "ok" if g["enabled"] else "muted"),
         '<div class="actionbar">'
         + master_admin.edit_form(
             master_edit.GENRE, g["genre_id"],
             [master_admin.field("code", "Code", g["code"], kind="readonly",
                                 note=code_note),
              master_admin.field("name", "Display name", g["name"])],
         )
         + master_admin.toggle_form(master_edit.GENRE, g["genre_id"], g["enabled"])
         + "</div>"]
        for g in genres
    ]
    region_rows = [
        [f'<code>{E(r["code"])}</code>', E(r["name"]), E(r["country"]),
         E(str(r.get("city") or "-")),
         _badge("ENABLED" if r["enabled"] else "DISABLED", "ok" if r["enabled"] else "muted"),
         '<div class="actionbar">'
         + master_admin.edit_form(
             master_edit.REGION, r["region_id"],
             [master_admin.field("code", "Code", r["code"], kind="readonly",
                                 note=code_note),
              master_admin.field("name", "Display name", r["name"]),
              master_admin.field("country", "Country", r["country"]),
              master_admin.field("city", "City", r.get("city")),
              master_admin.field("district", "District", r.get("district"))],
         )
         + master_admin.toggle_form(master_edit.REGION, r["region_id"], r["enabled"])
         + "</div>"]
        for r in regions
    ]

    body = (
        "<h2>Genres</h2>"
        + """<details><summary>Add Genre</summary>
<form method="post" action="/admin/genres"><div class="grid">
<div><label>Code</label><input name="code" required placeholder="BACHATA"></div>
<div><label>Name</label><input name="name" required placeholder="Bachata"></div>
</div><div class="actions"><button class="primary">Add Genre</button></div>
<p class="note">Genres are disabled, never deleted - events already tagged with
one still have to resolve.</p></form></details>"""
        + _table(["Code", "Name", "State", "Actions"], genre_rows, empty="no genre")
        + pagination.nav("/admin/master", {"region_page": region_page}, genre_page,
                         genre_total, page_param="genre_page")
        + "<h2>Regions</h2>"
        + """<details><summary>Add Region</summary>
<form method="post" action="/admin/regions"><div class="grid">
<div><label>Code</label><input name="code" required placeholder="KR-BUSAN">
<div class="note">한 번 정하면 바꿀 수 없습니다 — Source와 filter가 이 값을 씁니다</div></div>
<div><label>Country</label><input name="country" required value="South Korea"></div>
<div><label>City</label><input name="city" placeholder="Busan"></div>
<div><label>District</label><input name="district" placeholder=""></div>
<div><label>Display name</label><input name="name" required placeholder="Busan"></div>
</div><div class="actions"><button class="primary">Add Region</button></div>
<p class="note">실제로 행사가 확인된 지역만 추가하세요. 비어 있는 지역은 사용자에게
필터로 보이면서 아무것도 돌려주지 않습니다.</p></form></details>"""
        + '<p class="note">지역도 삭제하지 않고 Disable 합니다. code는 Source와 '
          "Region filter가 사용하므로 수정할 수 없습니다.</p>"
        + _table(["Code", "Name", "Country", "City", "State", "Actions"], region_rows,
                 empty="no region")
        + pagination.nav("/admin/master", {"genre_page": genre_page}, region_page,
                         region_total, page_param="region_page")
    )
    return HTMLResponse(_page("Genres & Regions", "/admin/master", body, flash=_flash(request)))


@router.post("/admin/regions")
def admin_create_region(
    code: str = Form(...),
    country: str = Form(...),
    name: str = Form(...),
    city: str = Form(""),
    district: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    """Register a region. There was no way to do this from the console at all.

    Seoul was seeded by a migration and nothing else could be added, so a venue
    in Busan had to be filed under the country-level row and the region filter
    could not tell the two cities apart.
    """
    from . import master_edit

    try:
        with _connection() as con:
            created = master_data.create_region(
                con, code=code.strip().upper(), country=country.strip(),
                name=name.strip(), city=city.strip() or None,
                district=district.strip() or None,
            )
            master_edit.record(
                con, entity_type=master_edit.REGION, entity_id=created["region_id"],
                action=master_edit.EDIT, reviewer=reviewer, entity_name=created["name"],
                after={"code": created["code"], "name": created["name"],
                       "city": created.get("city")},
                detail="region created",
            )
    except Exception as exc:
        return _back("/admin/master", f"could not add region: {exc}", "bad")
    return _back("/admin/master", f"added region {created['code']}")


@router.post("/admin/genres")
def admin_create_genre(
    code: str = Form(...), name: str = Form(...), _: str = Depends(require_admin)
) -> RedirectResponse:
    try:
        with _connection() as con:
            master_data.create_genre(con, code=code, name=name)
    except Exception as exc:
        return _back("/admin/master", f"could not add genre: {exc}", "bad")
    return _back("/admin/master", f"added genre {code.upper()}")


@router.post("/admin/genres/{genre_id}/{action}")
def admin_genre_action(
    genre_id: int, action: str, _: str = Depends(require_admin)
) -> RedirectResponse:
    if action not in ("enable", "disable"):
        raise HTTPException(status_code=404, detail="unknown action")
    with _connection() as con:
        master_data.set_genre_enabled(con, genre_id, action == "enable")
    return _back("/admin/master", f"genre {action}d")


# --- JSON API ---------------------------------------------------------------

@api.get("/genres")
def api_genres(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return _dump(master_data.list_genres(con))


@api.post("/genres")
def api_create_genre(payload: dict[str, Any], _: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return _dump(master_data.create_genre(
            con, code=payload.get("code", ""), name=payload.get("name", "")
        ))


@api.get("/regions")
def api_regions(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return _dump(master_data.list_regions(con))


@api.get("/venues")
def api_venues(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return _dump(master_data.list_venues(con))


@api.post("/venues")
def api_create_venue(payload: dict[str, Any], _: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return _dump(master_data.create_venue(
            con,
            name=payload.get("name", ""),
            region_id=payload.get("region_id"),
            address=payload.get("address"),
            notes=payload.get("notes"),
            aliases=payload.get("aliases") or [],
        ))


@api.get("/organizers")
def api_organizers(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return _dump(master_data.list_organizers(con))


@api.post("/organizers")
def api_create_organizer(payload: dict[str, Any], _: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return _dump(master_data.create_organizer(
            con,
            name=payload.get("name", ""),
            genre_id=payload.get("genre_id"),
            region_id=payload.get("region_id"),
            contact_url=payload.get("contact_url"),
            notes=payload.get("notes"),
        ))


@api.get("/sources")
def api_sources(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        rows = sources.list_sources(con)
    for row in rows:
        row["collector"] = collectors.describe_capability(row["platform"])
    return _dump(rows)


@api.post("/sources")
def api_create_source(payload: dict[str, Any], _: str = Depends(require_admin)) -> JSONResponse:
    try:
        with _connection() as con:
            return _dump(sources.create_source(
                con,
                source_key=payload.get("source_key", ""),
                name=payload.get("name", ""),
                platform=payload.get("platform", ""),
                source_role=payload.get("source_role", ""),
                url=payload.get("url"),
                genre_id=payload.get("genre_id"),
                region_id=payload.get("region_id"),
                authority_level=payload.get("authority_level", "UNKNOWN"),
                queries=payload.get("queries") or [],
                config=payload.get("config") or {},
                enabled=bool(payload.get("enabled", False)),
                collection_interval_minutes=int(
                    payload.get("collection_interval_minutes",
                                sources.DEFAULT_INTERVAL_MINUTES)
                ),
                notes=payload.get("notes"),
            ))
    except sources.SourceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@api.patch("/sources/{source_id}")
def api_update_source(
    source_id: int, payload: dict[str, Any], _: str = Depends(require_admin)
) -> JSONResponse:
    try:
        with _connection() as con:
            updated = sources.update_source(con, source_id, **payload)
    except sources.SourceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="source not found")
    return _dump(updated)


@api.post("/sources/{source_id}/test")
def api_test_source(source_id: int, _: str = Depends(require_admin)) -> JSONResponse:
    settings = _settings()
    with _connection() as con:
        source = sources.get_source(con, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return _dump(collectors.test_source(settings, source))


@api.get("/candidates")
def api_candidates(limit: int = 200, _: str = Depends(require_admin)) -> JSONResponse:
    settings = _settings()
    return _dump({
        "counts": candidates.counts(settings),
        "candidates": candidates.list_candidates(settings, limit=limit),
    })


@api.get("/intake")
def api_intake(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return _dump({
            "summary": intake.summary(con),
            "runs": intake.recent_runs(con, limit=20),
            "items": intake.recent_items(con, limit=50),
        })
