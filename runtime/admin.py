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
from typing import Any, Callable

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import (
    acquisition, candidates, collectors, content_store, db, health, intake,
    master_data, quota, review, sources, usage,
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
        "<h2>Runtime</h2>"
        + cards
        + "<h2>Components</h2>"
        + _table(["Component", "Status", "Detail"], status_rows, empty="no status")
        + "<h2>Today</h2>"
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

@router.get("/admin/sources", response_class=HTMLResponse)
def admin_sources(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    settings = _settings()
    with _connection() as con:
        rows = sources.list_sources(con)
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)

    table_rows = []
    for source in rows:
        capability = collectors.describe_capability(source["platform"])
        enabled = source["enabled"]
        toggle = "disable" if enabled else "enable"
        actions = (
            f'<form class="inline" method="post" '
            f'action="/admin/sources/{source["source_id"]}/{toggle}">'
            f"<button>{toggle.title()}</button></form> "
            f'<form class="inline" method="post" '
            f'action="/admin/sources/{source["source_id"]}/test">'
            "<button>Test</button></form>"
        )
        table_rows.append([
            f'<code>{E(source["source_key"])}</code><br>{E(source["name"])}',
            E(source["platform"]) + "<br>" + f'<span class="badge muted">{E(source["source_role"])}</span>',
            _badge("ENABLED" if enabled else "DISABLED", "ok" if enabled else "muted"),
            f'<span class="num">{source["collection_interval_minutes"]}m</span>',
            _badge(source["last_status"], "ok" if source["last_status"] == "PASS" else "muted")
            + "<br>" + E(str(source["last_collected_at"] or "never")[:19]),
            f'<span class="num">{source["item_count"]}</span>',
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

    body = (
        "<h2>Sources</h2>" + add_form
        + _table(
            ["Source", "Platform", "State", "Interval", "Last collection", "Items",
             "Collector", "Actions"],
            table_rows,
            empty="no source registered yet",
        )
        + f'<p class="note">Engine root: <code>{E(str(settings.engine_root))}</code>. '
          "Live collection needs the platform's API credentials in <code>.env</code>; "
          "without them a source can still be tested against a recorded snapshot.</p>"
    )
    return HTMLResponse(_page("Sources", "/admin/sources", body, flash=_flash(request)))


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


@router.post("/admin/sources/{source_id}/{action}")
def admin_source_action(
    source_id: int, action: str, _: str = Depends(require_admin)
) -> RedirectResponse:
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

    status = report.get("status")
    tone = {"PASS": "ok", "PASS_SNAPSHOT": "bad"}.get(status, "bad")
    note = ""
    if status == "PASS_SNAPSHOT":
        missing = ", ".join(report.get("missing_credentials") or []) or "credentials"
        note = f" [SNAPSHOT, NOT LIVE - {missing} missing; the scheduler will skip this source]"
    summary = f"{source['source_key']} test: {status} - {report.get('detail', '')}{note}"
    return _back("/admin/sources", summary[:300], tone)


# --- venues -----------------------------------------------------------------

@router.get("/admin/venues", response_class=HTMLResponse)
def admin_venues(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    with _connection() as con:
        venues = master_data.list_venues(con)
        regions = master_data.list_regions(con)

    rows = [
        [E(v["name"]), E(str(v.get("region_name") or "-")), E(str(v.get("address") or "-")),
         ", ".join(E(a) for a in (v.get("aliases") or [])) or "-",
         _badge("ENABLED" if v["enabled"] else "DISABLED", "ok" if v["enabled"] else "muted")]
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

    body = ('<h2>Venues</h2>'
            '<p class="note">Venue strings read from posts that this list does '
            'not recognise are queued at '
            '<a href="/admin/venues/unresolved">Unresolved Venues</a>.</p>'
            ) + add_form + _table(
        ["Name", "Region", "Address", "Aliases", "State"], rows,
        empty="no venue registered yet",
    )
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


# --- organizers -------------------------------------------------------------

@router.get("/admin/organizers", response_class=HTMLResponse)
def admin_organizers(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    with _connection() as con:
        organizers = master_data.list_organizers(con)
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)

    rows = [
        [E(o["name"]), E(str(o.get("genre_code") or "-")), E(str(o.get("region_name") or "-")),
         E(str(o.get("contact_url") or "-")),
         _badge("ENABLED" if o["enabled"] else "DISABLED", "ok" if o["enabled"] else "muted")]
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

    body = "<h2>Organizers</h2>" + add_form + _table(
        ["Name", "Genre", "Region", "Contact", "State"], rows,
        empty="no organizer registered yet",
    )
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
    with _connection() as con:
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)

    genre_rows = [
        [f'<code>{E(g["code"])}</code>', E(g["name"]),
         _badge("ENABLED" if g["enabled"] else "DISABLED", "ok" if g["enabled"] else "muted"),
         f'<form class="inline" method="post" '
         f'action="/admin/genres/{g["genre_id"]}/{"disable" if g["enabled"] else "enable"}">'
         f'<button>{"Disable" if g["enabled"] else "Enable"}</button></form>']
        for g in genres
    ]
    region_rows = [
        [f'<code>{E(r["code"])}</code>', E(r["name"]), E(r["country"]),
         E(str(r.get("city") or "-")),
         _badge("ENABLED" if r["enabled"] else "DISABLED", "ok" if r["enabled"] else "muted")]
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
        + _table(["Code", "Name", "State", ""], genre_rows, empty="no genre")
        + "<h2>Regions</h2>"
        + _table(["Code", "Name", "Country", "City", "State"], region_rows, empty="no region")
    )
    return HTMLResponse(_page("Genres & Regions", "/admin/master", body, flash=_flash(request)))


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
