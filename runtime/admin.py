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

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import (
    acquisition, candidates, collectors, content_store, db, events_api, feedback,
    health, intake, master_data, public, quota, review, review_hints, source_ops,
    source_priority, sources, timeline_settings, usage,
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
/* v0.86.8 Section 4: inline row editing. The row being edited keeps its
   place in the table - same columns, same order - and only swaps its cells
   for inputs, so nothing moves under the operator's cursor. The <form>
   itself lives outside the table (a form cannot span <td>s) and the inputs
   join it with the HTML5 form="..." attribute; .rowform is that element,
   which has nothing to show. */
form.rowform{display:none}
tr.editing{background:var(--bg)}
tr.editing td{vertical-align:middle}
.cellinput{width:100%;min-width:110px;font-size:13px;padding:4px 6px}
/* v0.86.8: Notes is free text in a narrow column - a one-line input clipped
   it. Same cell, same width, two visible lines instead of one, so nothing
   about the table's own width changes. */
textarea.cellinput{min-height:3.4em;resize:vertical;line-height:1.35}
.celllabel{display:block;font-size:11px;color:var(--muted);margin:6px 0 2px}
.rowactions{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
a.rowbtn{display:inline-block;padding:4px 10px;border:1px solid var(--line);
border-radius:6px;text-decoration:none;color:var(--fg);background:var(--card);
font-size:13px;line-height:1.4}
a.rowbtn:hover{border-color:var(--accent);color:var(--accent)}
button[disabled]{opacity:.6;cursor:progress}
/* v0.86.8: the v0.86.7 venue filter bar was written with the PUBLIC
   stylesheet's class names (.filters/.key/label.chip/.apply) - none of which
   exist here, so admin's own `label{display:block}` put every genre on its
   own line and `select{width:100%}` gave the region picker the full page
   width. These are those rules, in this console's tokens: one flex line on a
   desktop, wrapping rather than overflowing when the window (or the genre
   list) grows. Nothing about the markup, the query parameters or the table
   changes - the genres are still whatever the master returns. */
.filters{display:flex;align-items:center;flex-wrap:wrap;gap:8px 16px;
margin:0 0 12px}
.filters .row{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:0}
.filters .key{color:var(--muted);font-size:12px;white-space:nowrap}
.filters select{width:auto;min-width:140px;max-width:100%}
.filters label.chip{display:inline-flex;align-items:center;gap:6px;margin:0;
padding:3px 11px;border:1px solid var(--line);border-radius:999px;
background:var(--card);color:var(--fg);font-size:12px;cursor:pointer;
white-space:nowrap}
.filters label.chip:has(input:checked){border-color:var(--accent);
color:var(--accent);font-weight:600}
.filters label.chip:focus-within{outline:2px solid var(--accent);
outline-offset:1px}
.filters label.chip input{width:auto;margin:0;accent-color:var(--accent)}
.filters a{text-decoration:none}
/* v0.86.9: a venue's linked events open as one full-width row right under
   it - the same "one row opened in place" shape as the inline editor. */
tr.rowdetail>td{background:var(--bg);padding:10px 14px}
.eventpanel h3{font-size:13px;margin:0 0 8px;display:flex;gap:10px;
align-items:baseline;flex-wrap:wrap}
.eventpanel .tablewrap{background:var(--card)}
tr.pastevent td{color:var(--muted)}
a.rowbtn.on{border-color:var(--accent);color:var(--accent);font-weight:600}
/* v0.86.9: an event term's canonical-format checkboxes. Rules of their own,
   not a second selector on .filters label.chip, so the venue filter bar
   keeps exactly the rules v0.86.8 shipped. */
.chipset{display:flex;flex-wrap:wrap;gap:6px}
.chipset label.chip{display:inline-flex;align-items:center;gap:6px;margin:0;
padding:3px 11px;border:1px solid var(--line);border-radius:999px;
background:var(--card);color:var(--fg);font-size:12px;cursor:pointer;
white-space:nowrap}
.chipset label.chip:has(input:checked){border-color:var(--accent);
color:var(--accent);font-weight:600}
.chipset label.chip input{width:auto;margin:0;accent-color:var(--accent)}
/* v0.87.0: the "?" beside an event's kind (shared markup from public.py's
   _kind_why) - a real button opening a native popover with the reasons. */
.kind-why{font:inherit;font-size:11px;font-weight:700;line-height:1;color:var(--bad);
background:none;border:1px solid currentColor;border-radius:999px;width:18px;height:18px;
padding:0;margin-left:4px;cursor:pointer;vertical-align:1px}
.kind-why:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.why-pop{max-width:min(360px,90vw);border:1px solid var(--line);border-radius:8px;
padding:12px 14px;background:var(--card);color:var(--fg);box-shadow:0 8px 24px rgba(0,0,0,.18);
font-size:12px;font-weight:400}
.why-pop p{margin:0 0 4px}
.why-pop ul{margin:4px 0 10px;padding-left:18px}
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
/* v0.86.4 Source Audit Workbench: the audit table is wider than a normal
   admin page and genuinely needs horizontal scroll rather than hiding
   columns - .tablewrap already scrolls (line 93), this just gives the page
   itself more room on a desktop viewport. Only pages that opt in with
   wide=True get it; every other admin page keeps its 1200px column. */
body.wide header .bar,body.wide nav,body.wide main{max-width:1600px}
.tierbadge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;
font-weight:600;border:1px solid var(--line);color:var(--muted)}
.tierbadge.primary{color:var(--ok);border-color:var(--ok)}
.tierbadge.promotion_board{color:var(--warn);border-color:var(--warn)}
.urlcell{font-size:12px;word-break:break-all}
.urlcell .lbl{color:var(--muted);font-size:10px;text-transform:uppercase;
letter-spacing:.04em;display:block}
.compare{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.compare .col{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:12px 14px}
.compare .col h3{margin:0 0 8px;font-size:13px}
.compare .col dl{display:grid;grid-template-columns:auto 1fr;gap:.3rem .7rem;margin:0}
.compare .col dt{color:var(--muted);font-size:11px}
.compare .col dd{margin:0;word-break:break-word}
.rawtext{white-space:pre-wrap;word-break:break-word;font-size:12px;max-height:320px;
overflow-y:auto;background:var(--bg);border:1px solid var(--line);border-radius:6px;
padding:8px 10px;margin:8px 0 0}
.hint{display:block;font-size:12px;padding:4px 0}
.hint.WARN{color:var(--bad)}
.hint.INFO{color:var(--warn)}
.previewbox{border:1px dashed var(--line);border-radius:8px;padding:10px 12px;margin-top:8px}
/* v0.86.5 Admin Source Dense Layout: seven columns instead of thirteen,
   most of the width handed to Source/Target - the two columns whose
   content can actually be long - and short admin metadata (Content Mode,
   collector capability, Health, Interval, Decision) folded into compact,
   at-most-three-line cells (.metacell) instead of one column each. */
table.sources-dense{table-layout:fixed}
table.sources-dense th:nth-child(1),table.sources-dense td:nth-child(1){width:15%}
table.sources-dense th:nth-child(2),table.sources-dense td:nth-child(2){width:9%}
table.sources-dense th:nth-child(3),table.sources-dense td:nth-child(3){width:30%}
table.sources-dense th:nth-child(4),table.sources-dense td:nth-child(4){width:14%}
table.sources-dense th:nth-child(5),table.sources-dense td:nth-child(5){width:12%}
table.sources-dense th:nth-child(6),table.sources-dense td:nth-child(6){width:12%}
table.sources-dense th:nth-child(7),table.sources-dense td:nth-child(7){width:8%}
table.sources-dense td{padding:6px 8px;font-size:12px;line-height:1.35}
.metacell{display:flex;flex-direction:column;gap:2px}
.targetcell{word-break:break-all}
.target-pub-row{color:var(--muted);font-size:11px;margin-top:2px}
.target-pub-row a{word-break:break-all}
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
    ("/admin/communities", "Communities"),
    ("/admin/notices", "Notices"),
    ("/admin/community-discovery", "Discovery"),
    ("/admin/master", "Genres & Regions"),
    ("/admin/usage", "Usage"),
    ("/admin/system", "System"),
    ("/admin/settings", "Settings"),
)

# /admin/candidates predates the Review console. It still works, and the nav
# points at its replacement; the old URL is not broken for anyone who bookmarked it.


# v0.86.8 Section 4: a save is sent once. A second click on a button whose
# form is already on its way is dropped, and the button says so instead of
# looking untouched. Progressive enhancement only - with no JavaScript the
# forms still submit exactly as they always did, and the edit routes stay
# safe to repeat (an unchanged edit writes nothing and records nothing).
SUBMIT_ONCE = """<script>(function(){
document.addEventListener('submit',function(e){
var f=e.target;if(!f||f.tagName!=='FORM')return;
if(f.dataset.sent){e.preventDefault();return;}
f.dataset.sent='1';
var id=f.getAttribute('id');
var buttons=[].slice.call(f.querySelectorAll('button'));
if(id){buttons=buttons.concat([].slice.call(
document.querySelectorAll('button[form="'+id+'"]')));}
buttons.forEach(function(b){var busy=b.getAttribute('data-busy');
if(busy){b.textContent=busy;}b.disabled=true;});
},true);})();</script>"""


def _page(title: str, current: str, body: str, *, flash: tuple[str, str] | None = None,
          wide: bool = False) -> str:
    settings = _settings()
    nav = "".join(
        f'<a href="{href}" class="{"on" if href == current else ""}">{E(label)}</a>'
        for href, label in NAV
    )
    banner = ""
    if flash:
        tone, message = flash
        banner = f'<p class="flash {tone}">{E(message)}</p>'
    body_class = ' class="wide"' if wide else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)} - DanceMate Admin</title><style>{STYLE}</style></head>
<body{body_class}>
<header><div class="bar">
  <h1>DanceMate Admin</h1>
  <span class="env">runtime v{E(settings.version)} &middot; engine v{E(settings.engine_version)}
  &middot; {E(settings.env)} &middot; LAN only</span>
</div><nav>{nav}</nav></header>
<main>{banner}{body}</main>
{SUBMIT_ONCE}
</body></html>"""


def _cards(items: list[tuple[str, Any, str]]) -> str:
    cells = "".join(
        f'<div class="card"><div class="k">{E(k)}</div>'
        f'<div class="v">{E(str(v))}</div>'
        f'<div class="s">{E(sub)}</div></div>'
        for k, v, sub in items
    )
    return f'<div class="cards">{cells}</div>'


def _table(headers: list[str], rows: list[list[str]], *, empty: str,
          table_class: str = "", row_attrs: list[str] | None = None,
          row_details: "list[str | None] | None" = None) -> str:
    """`row_attrs` (v0.86.8) is raw attribute text for the matching <tr> - the
    row's own anchor id, and the class that marks the one being edited.
    `row_details` (v0.86.9) is optional HTML for a full-width row directly
    under the matching row - a venue's linked events, opened in place."""
    cls = f' class="{E(table_class)}"' if table_class else ""
    if not rows:
        return f'<div class="tablewrap"><table{cls}><tbody><tr><td>{E(empty)}</td>' \
               "</tr></tbody></table></div>"
    head = "".join(f"<th>{E(h)}</th>" for h in headers)
    attrs = list(row_attrs or [])
    attrs += [""] * (len(rows) - len(attrs))
    details = list(row_details or [])
    details += [None] * (len(rows) - len(details))
    body = "".join(
        f"<tr{attr}>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
        + (f'<tr class="rowdetail"><td colspan="{len(headers)}">{detail}</td></tr>'
           if detail else "")
        for row, attr, detail in zip(rows, attrs, details)
    )
    return f'<div class="tablewrap"><table{cls}><thead><tr>{head}</tr></thead>' \
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


def _source_priority_panel(settings: Settings) -> str:
    """v0.85.0 Section 48-50/78: how much of upcoming coverage stands on its
    own feet (PRIMARY/PROMOTION_BOARD) versus only exists because an
    aggregator recompiled it (DIRECTORY) - the KPI Section 50 asks for by
    name, plus the honest follow-up Section 52-53 wants: which of those
    aggregator-only events has no direct source at all, so a human can
    decide whether it is worth going and finding one. No new crawler here -
    just what is already in the database, read differently.
    """
    try:
        with _connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT src.source_role, count(*) FROM events e "
                    "LEFT JOIN source_items si ON si.source_item_id = e.source_item_id "
                    "LEFT JOIN sources src ON src.source_id = si.source_id "
                    "WHERE " + events_api._VISIBLE + " AND e.event_date >= %s "
                    "AND e.engine_status <> 'CANCELLED' "
                    "GROUP BY 1", (events_api.today(),),
                )
                by_role = dict(cur.fetchall())
            open_feedback = feedback.count_open(con)
            gap_rows = _aggregator_only_gap(con, limit=10)
            evidence = source_ops.evidence_tiers(con)
    except db.DatabaseUnavailable:
        return ""

    tier_totals = {tier: 0 for tier in source_priority.TIERS}
    for role, n in by_role.items():
        tier_totals[source_priority.tier_of(role)] += n
    total = sum(tier_totals.values())
    direct_and_promotion = tier_totals[source_priority.PRIMARY] + tier_totals[source_priority.PROMOTION_BOARD]
    coverage_pct = round(100 * direct_and_promotion / total) if total else None

    cards = _cards([
        ("PRIMARY/DIRECT", tier_totals[source_priority.PRIMARY], "upcoming, direct/official"),
        ("PROMOTION BOARD", tier_totals[source_priority.PROMOTION_BOARD], "upcoming, promotion boards"),
        ("DIRECTORY", tier_totals[source_priority.DIRECTORY], "upcoming, aggregator-sourced"),
        ("Direct+Promotion 비율", f"{coverage_pct}%" if coverage_pct is not None else "-",
         f"of {total} upcoming"),
        ("열린 피드백", open_feedback, "정보가 달라요/부족해요 등"),
    ])

    # v0.85.2 Section 22/23: not the representative row's own tier, but
    # every tier of evidence retained behind it (folded duplicates
    # included) - PRIMARY+DIRECTORY together is the concrete "directory
    # discovery -> official confirmation" convergence signal.
    evidence_cards = _cards([
        ("PRIMARY evidence", evidence["primary"], "unique events, anywhere in their evidence"),
        ("PROMOTION_BOARD evidence", evidence["promotion_board"], "unique events, anywhere in their evidence"),
        ("DIRECTORY만", evidence["directory_only"], "다른 tier 증거 없음"),
        ("MULTI-TIER", evidence["multi_tier"], "2개 이상 tier 증거 (예: PRIMARY+DIRECTORY)"),
    ])

    gap_html = ""
    if gap_rows:
        rows = [
            [E(g["event_name"] or "")[:56], E(g["event_date"].isoformat()),
             E(g["region_name"] or "지역 미확인"), E(g["source_name"] or "-"),
             E(g["venue_text"] or g["venue_name"] or "-")]
            for g in gap_rows
        ]
        gap_html = (
            "<h3>Aggregator-only (direct/promotion source 없음)</h3>"
            + _table(["행사", "날짜", "지역", "현재 Source", "추정 주최/스튜디오"],
                    rows, empty="-")
        )

    return (
        "<h2>Source Priority</h2>" + cards
        + "<h3>Multi-tier Evidence</h3>" + evidence_cards
        + gap_html
        + '<p class="note">Section 51: direct/promotion 비율이 낮으면 다음 Source '
          "확장은 동호회 공식·주최자 공식·스튜디오 공식·홍보 게시판만 우선하고, "
          "aggregator 신규 확장은 후순위로 둡니다.</p>"
    )


def _aggregator_only_gap(con, *, limit: int = 10) -> list[dict[str, Any]]:
    """Upcoming events whose only known source is DIRECTORY-tier - Section
    52-53's gap list, exactly the columns it asks for (event/region/current
    source/possible organizer), soonest first."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT e.event_name, e.event_date, e.venue_text, "
            "       v.name AS venue_name, r.name AS region_name, "
            "       src.name AS source_name, src.source_role AS source_role "
            "FROM events e "
            "LEFT JOIN venues v ON v.venue_id = e.venue_id "
            "LEFT JOIN regions r ON r.region_id = e.region_id "
            "LEFT JOIN source_items si ON si.source_item_id = e.source_item_id "
            "LEFT JOIN sources src ON src.source_id = si.source_id "
            "WHERE " + events_api._VISIBLE + " AND e.event_date >= %s "
            "AND e.engine_status <> 'CANCELLED' "
            "ORDER BY e.event_date, e.event_id",
            (events_api.today(),),
        )
        names = [c.name for c in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
    gap = [r for r in rows if source_priority.tier_of(r["source_role"]) == source_priority.DIRECTORY]
    return gap[:limit]


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
    source_priority_panel = _source_priority_panel(settings)
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
        + source_priority_panel
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

def _source_decision_badge(op: dict[str, Any]) -> str:
    """What a person decided, or what the numbers suggest if nobody has -
    the small, always-visible half of `_source_decision_form()` (v0.86.5
    Section 3/62: the Decision column is gone, folded into Status/Last Run
    as a compact badge, with the recording form itself moved into Actions
    behind its own `<details>` - Section 13/43: a bulky select+input+button
    form was never "short metadata" and does not belong in a dense cell,
    but the CURRENT decision is exactly the kind of short status a reader
    wants at a glance without expanding anything)."""
    if not op:
        return "-"
    decided = op.get("operational_decision")
    recommended = op.get("recommended")
    if decided:
        return _badge(decided, source_ops.TONES.get(decided, "muted"))
    return _badge(f"권고: {recommended}", "muted")


def _source_decision_form(op: dict[str, Any]) -> str:
    """The Record-a-decision form - unchanged behaviour, just no longer
    rendered inline in a dedicated column (v0.86.5). Collapsed behind its
    own `<details>` in Actions so a row stays compact until an operator
    actually wants to change something."""
    if not op:
        return ""
    decided = op.get("operational_decision")
    recommended = op.get("recommended")
    options = "".join(
        f'<option value="{d}"{" selected" if d == (decided or recommended) else ""}>'
        f"{E(source_ops.LABELS[d])}</option>"
        for d in source_ops.DECISIONS
    )
    reason_note = (
        f'<div class="note">{E(str(op.get("decision_reason") or ""))[:70]}</div>' if decided
        else f'<div class="note">{E(op.get("recommendation_reason") or "")}</div>'
    )
    form = (
        f'<form class="inline" method="post" '
        f'action="/admin/sources/{op["source_id"]}/decision">'
        f'<select name="decision">{options}</select>'
        '<input name="reason" placeholder="이유 (선택)" style="width:150px">'
        "<button>Record</button></form>"
    )
    return (
        '<details><summary>Decision</summary>'
        f"{reason_note}{form}</details>"
    )


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


def _public_link_html(collector_url: str | None) -> str:
    """The "원문보기 ↗" link for a source's own resolved Public URL, or an
    honest "no public URL" badge - the shared half of `_source_url_cell()`
    (detail/item-audit pages, unchanged) and the dense list view's merged
    Target cell (v0.86.5 Section 6-9), so both ever call the one resolver
    (`events_api.resolve_public_source_url()`/`valid_public_url()`) rather
    than each keeping their own copy of this logic."""
    public_url = (
        events_api.valid_public_url(events_api.resolve_public_source_url(collector_url))
        if collector_url else None
    )
    if public_url:
        return (f'<a class="target-public" href="{E(public_url)}" target="_blank" '
                f'rel="noopener noreferrer" title="{E(public_url)}">원문보기 &#8599;</a>')
    return '<span class="badge warn">no public URL</span>'


def _source_url_cell(source: dict[str, Any]) -> str:
    """Collector URL vs Public URL, shown distinctly (v0.86.4 Section 82-92).
    Used by the source/item detail pages (their own vertical facts tables,
    untouched by v0.86.5's list-view density work - Section 47).

    A source's own configured `url` is what the collector fetches - for
    Tango Calendar Korea (an API detail endpoint) and TangoNOW (a raw
    Firestore document URL) that is never a page a human should be sent to.
    The "원문보기 ↗" link only ever points at the resolved result, never at
    the raw collector URL, and never opens in an iframe (Section 92).
    """
    collector_url = source.get("url")
    collector_html = (
        f'<span title="{E(collector_url)}">{E(_truncate(collector_url, 40))}</span>'
        if collector_url else '<span class="badge muted">-</span>'
    )
    return (
        f'<div class="urlcell"><span class="lbl">Collector</span>{collector_html}'
        f'<span class="lbl">Public</span>{_public_link_html(collector_url)}</div>'
    )


def _source_target_and_public(source: dict[str, Any]) -> str:
    """Target + Public URL merged into one cell (v0.86.5 Section 6-9, 40):
    the dense list view's replacement for the separate "Target" and "URL"
    columns v0.86.4 had. `_source_target()` still shows the collector's own
    target (a URL, or the search queries a query-driven source uses) with
    its own "Open Source" button pointed at the raw collector value - kept
    as-is, since for TangoNOW/Tango Calendar Korea that is a genuinely
    different, separately useful link than the resolved Public URL added
    below it (Section 2: no information removed). Nothing is shown twice:
    a WEB/DIRECTORY source's collector URL is not repeated under a second
    "Collector" label the way the old URL column did (Section 43).
    """
    target_html = _source_target(source)
    public_html = _public_link_html(source.get("url"))
    return (
        f'<div class="targetcell">{target_html}'
        f'<div class="target-pub-row">↳ {public_html}</div></div>'
    )


def _source_meta_cell(source: dict[str, Any], health: str,
                      capability: dict[str, Any]) -> str:
    """Content Mode + collector capability + Health + Interval, one cell,
    at most 3 logical lines (v0.86.5 Section 13-18): four short admin-
    operational facts that each used to cost their own column width for a
    value rarely more than a couple of words long."""
    mode = collectors.content_mode(source)
    cap_tone = "ok" if capability["live"] else "warn"
    cap_label = "LIVE" if capability["live"] else "SNAPSHOT"
    line1 = (f'<span class="badge muted" title="{E(mode)}">{E(mode)}</span> '
             f'<span class="badge {cap_tone}" title="{E(capability["detail"])}">{cap_label}</span>')
    line2 = _badge(health, _HEALTH_TONE.get(health, "muted"))
    line3 = f'<span class="num">{source["collection_interval_minutes"]}m</span>'
    return f'<div class="metacell"><div>{line1}</div><div>{line2}</div><div>{line3}</div></div>'


def _source_genre_tier_cell(genre_region_html: str, tier: str, tier_label: str) -> str:
    """Genre/Region + Tier, one cell (v0.86.5 Section 5): a source's genre
    and region badges stay - Section 2 forbids dropping information - the
    only change is the tier badge now shares this cell instead of its own
    column."""
    return (
        f'<div class="metacell"><div>{genre_region_html}</div>'
        f'<div><span class="tierbadge {E(tier.lower())}">{E(tier_label)}</span></div></div>'
    )


def _source_status_cell(source_id: int, last_success: dict[int, Any],
                        last_error: dict[int, dict[str, Any]],
                        op: dict[str, Any]) -> str:
    """Last Success/Error + the current Decision badge, one cell (v0.86.5
    Section 3/62): the bulky Decision *form* moves to Actions behind its
    own `<details>` (Section 13/43 - a select+input+button was never
    "short metadata"), but the decision itself is exactly the kind of
    glanceable status this cell already exists for."""
    return (
        '<div class="metacell">'
        f'<div>{_last_success_text(last_success.get(source_id))}</div>'
        f'<div>{_last_error_text(last_error.get(source_id))}</div>'
        f'<div>{_source_decision_badge(op)}</div></div>'
    )


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
def admin_sources(request: Request, genre: str = "ALL",
                  _: str = Depends(require_admin)) -> HTMLResponse:
    """The Source Audit Workbench (v0.86.4 Section 2, 24-36, 54-66, 82-92):
    a wide table an operator can actually audit - Genre/Tier/Health/Public-
    vs-Collector-URL all visible at once, never a "simple CRUD list" that
    hides the source's own authority behind a click.

    v0.86.5 (Section 1-43): the same information, seven columns instead of
    thirteen - short, single-fact columns (URL, Content Mode, Health,
    Interval, Decision) consolidated into a handful of compact, at-most-
    three-line cells, so one source reads as close to one complete row as
    its content allows, and the columns that genuinely need width (Source,
    Target) get more of it. No information removed (Section 2) - the
    Decision *form* moved into Actions behind its own `<details>`, but the
    decision itself stayed, as a small badge, right where a reader would
    look for it.
    """
    from . import master_admin, master_edit, pagination

    view = master_admin.current_view(request)
    genre = (genre or "ALL").upper()
    settings = _settings()
    with _connection() as con:
        total = sources.count_sources(con, genre_code=genre)
        page = pagination.resolve_page(request.query_params.get("page"), total)
        rows = sources.list_sources(
            con, genre_code=genre,
            limit=pagination.PAGE_SIZE, offset=pagination.sql_offset(page)
        )
        genres = master_data.list_genres(con)
        regions = master_data.list_regions(con)
        outcomes = sources.acquisition_outcomes(con)
        operations = {o["source_id"]: o for o in source_ops.overview(con)}
        last_success = intake.last_success_per_source(con)
        last_error = intake.last_error_per_source(con)

    genre_by_id = {g["genre_id"]: g["code"] for g in genres}
    region_by_id = {r["region_id"]: r["name"] for r in regions}

    genre_filter_bar = (
        '<div class="filterbar">'
        + "".join(
            f'<a class="{"on" if genre == code else ""}" '
            f'href="/admin/sources?genre={E(code)}">{E(label)}</a>'
            for code, label in (
                [("ALL", "ALL")]
                + [(g["code"], g["code"]) for g in genres]
                + [("UNKNOWN", "장르 미확인")]
            )
        )
        + "</div>"
    )

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
                return_to=view,
            )
            + f'<form class="inline" method="post" '
            f'action="/admin/sources/{source["source_id"]}/{toggle}">'
            f"<button>{toggle.title()}</button></form>"
            + f'<form class="inline" method="post" '
            f'action="/admin/sources/{source["source_id"]}/test">'
            "<button>Test</button></form>"
            + _source_decision_form(operations.get(source["source_id"], {}))
            + "</div>"
        )
        health = _source_health(source, outcomes.get(source["source_id"], {}))
        # A source with no region_id is not "unknown location" the way a
        # venue is - an AGGREGATOR/DIRECTORY (TangoNOW, Tango Calendar
        # Korea, Miltang) genuinely covers many regions at once, and its own
        # region_id is deliberately left unset rather than pinned to one
        # (Section 27 of the v0.82.4 task: a source's region must never be
        # used to overwrite an event's own). "전국" says that plainly
        # instead of a blank badge that reads as a gap.
        region_label = region_by_id.get(source.get("region_id"))
        if not region_label and source.get("source_role") in ("AGGREGATOR", "DIRECTORY"):
            region_label = "전국"
        genre_region = " ".join(
            f'<span class="badge muted">{E(v)}</span>' for v in (
                genre_by_id.get(source.get("genre_id")),
                region_label,
            ) if v
        ) or '<span class="badge muted">-</span>'
        tier = source_priority.tier_of(source["source_role"])
        tier_label = source_priority.label_of(source["source_role"])
        source_id = source["source_id"]
        table_rows.append([
            f'<a href="/admin/sources/{source_id}">{E(source["name"])}</a>'
            f'<div class="note"><code>{E(source["source_key"])}</code> · '
            f'{E(source["platform"])}</div>',
            _source_genre_tier_cell(genre_region, tier, tier_label),
            _source_target_and_public(source),
            _source_meta_cell(source, health, capability),
            _source_yield(outcomes.get(source_id, {}), operations.get(source_id, {})),
            _source_status_cell(source_id, last_success, last_error,
                                operations.get(source_id, {})),
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
        "<h2>Sources</h2>" + genre_filter_bar + add_form + csv_bar
        + _table(
            ["Source", "Genre / Tier", "Target", "Meta", "Activity",
             "Status / Last Run", "Actions"],
            table_rows,
            empty="no source registered yet",
            table_class="sources-dense",
        )
        + f'<p class="note">Engine root: <code>{E(str(settings.engine_root))}</code>. '
          "Live collection needs the platform's API credentials in <code>.env</code>; "
          "without them a source can still be tested against a recorded snapshot.</p>"
        + pagination.nav("/admin/sources", {"genre": genre} if genre != "ALL" else {},
                         page, total)
    )
    return HTMLResponse(
        _page("Sources", "/admin/sources", body, flash=_flash(request), wide=True)
    )


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
        audit = source_ops.audit_summary(con, source_id)
        # v0.86.4 Section 40-53: up to 50 recent items, never full-body
        # bulk loading here - the two lookups below are each one batched
        # query for the whole page (Section 107-112: no N+1), and only the
        # Item Audit Detail page (a single row, on click) reads a full body.
        recent = intake.recent_items(con, source_id=source_id, limit=50)
        item_ids = [item["source_item_id"] for item in recent]
        events_by_item = events_api.get_events_by_source_items(con, item_ids)
        bodies_by_item = content_store.bulk_extracted_text(con, item_ids)
        last_success = intake.last_success_per_source(con)
        last_error = intake.last_error_per_source(con)

    genre_by_id = {g["genre_id"]: g["code"] for g in genres}
    region_by_id = {r["region_id"]: r["name"] for r in regions}
    capability = collectors.describe_capability(source["platform"])
    outcome = outcomes.get(source_id, {})
    health = _source_health(source, outcome)
    tier = source_priority.tier_of(source["source_role"])
    tier_label = source_priority.label_of(source["source_role"])

    audit_cards = _cards([
        ("Items", audit.get("items", 0) or 0, "collected from this source"),
        ("Events", audit.get("events", 0) or 0, "produced by those items"),
        ("Date Missing", audit.get("date_missing", 0) or 0, "of this source's own events"),
        ("Time Missing", audit.get("time_missing", 0) or 0, "of this source's own events"),
        ("Venue Missing", audit.get("venue_missing", 0) or 0, "of this source's own events"),
        ("Fee Missing", audit.get("fee_missing", 0) or 0, "of this source's own events"),
        ("DJ Missing", audit.get("dj_missing", 0) or 0, "of this source's own events"),
    ])

    facts = _table(
        ["Field", "Value"],
        [
            ["Name", E(source["name"])],
            ["Source key", f'<code>{E(source["source_key"])}</code>'],
            ["Platform", E(source["platform"])],
            ["Role", E(source["source_role"])],
            ["Tier", f'<span class="tierbadge {E(tier.lower())}">{E(tier_label)}</span> '
                     f'<span class="note">({E(tier)}) - PRIMARY 여부만으로 확인 표시가 지워지지 않습니다</span>'],
            ["Authority", E(source["authority_level"])],
            ["Genre", E(genre_by_id.get(source.get("genre_id")) or "-")],
            ["Region", E(
                region_by_id.get(source.get("region_id"))
                or ("전국" if source.get("source_role") in ("AGGREGATOR", "DIRECTORY") else "-")
            )],
            ["Target", _source_target(source)],
            ["Collector / Public URL", _source_url_cell(source)],
            ["Parser", f'<code>{E(collectors._config(source).get("parser") or "board")}</code>'
             if source["platform"] == "WEB" else '<span class="badge muted">-</span>'],
            ["Content Mode",
             f'<span class="badge muted">{E(collectors.content_mode(source))}</span>'],
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
        event = events_by_item.get(item["source_item_id"])
        body = bodies_by_item.get(item["source_item_id"])
        candidate = {
            "start_time": event.get("start_time") if event else None,
            "end_time": event.get("end_time") if event else None,
            "fee": event.get("fee") if event else None,
            "venue": (event.get("venue") or {}).get("name") if event else None,
        }
        hint_count = len(review_hints.hints(candidate, body)) if body else 0
        # A relative link to the runtime's own public Timeline detail page -
        # not run through valid_public_url() (that guard is for a source's
        # own external URL, not an internal route this admin console always
        # serves alongside itself).
        public_url = f"/events/{event['id']}" if event else None
        event_cell = (
            f'event #{event["id"]} '
            f'<span class="badge muted">{E(event.get("status") or "-")}</span>'
            if event else '<span class="badge warn">no event</span>'
        )
        public_cell = (
            f'<a href="{E(public_url)}" target="_blank" rel="noopener noreferrer">'
            f'Timeline &#8599;</a>' if public_url
            else '<span class="badge muted">-</span>'
        )
        hint_cell = (
            f'<span class="badge warn">{hint_count} hint(s)</span>' if hint_count
            else '<span class="badge muted">0</span>'
        )
        recent_rows.append([
            E(str(item.get("collected_at") or "-")[:19]),
            f'<a href="/admin/sources/{source_id}/items/{item["source_item_id"]}">'
            f'{E(str(item.get("title") or "-")[:70])}</a>',
            E(str(item.get("published_at") or "-")[:19]),
            _badge(item.get("ingest_state") or "-",
                   "ok" if item.get("ingest_state") == "INGESTED" else "muted"),
            event_cell,
            public_cell,
            hint_cell,
        ])
    recent_table = _table(
        ["Collected", "Title (audit detail)", "Published", "Fetch/Ingest State",
         "Canonical Event", "Public URL", "Review Hints"],
        recent_rows,
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
        + "<h2>Source Audit Summary</h2>" + audit_cards
        + '<p class="note">"Missing" is the extracted/canonical event field being empty - '
          'not the same as a "review hint" (the original text had something extraction did '
          'not catch; see each item\'s own audit detail).</p>'
        + "<h2>Recent Items</h2>" + recent_table
        + raw_config
        + '<p class="note"><a href="/admin/sources">back to Sources</a></p>'
    )
    return HTMLResponse(
        _page(f"Source: {source['name']}", "/admin/sources", body, flash=_flash(request),
              wide=True)
    )


def _format_chips(event_type: str | None) -> str:
    """The read-only Event Format chip row (v0.86.7 Section 30, 38, 45-47):
    [밀롱가] [프락티카] [제너럴] [소셜] [미분류], the current one highlighted -
    never a new write action this release (Section 47: "김프로가 바로 볼 수
    있어야 함" is about visibility, not an edit workflow; a genuinely
    repeated hybrid-format case would justify one, and none was found).
    Plain, muted admin badges - Section 39 explicitly asks for no new
    strong colour scheme."""
    current = events_api.format_of(event_type)
    chips = "".join(
        f'<span class="badge {"ok" if code == current else "muted"}">{E(label)}</span>'
        for code, label in events_api.EVENT_FORMAT_LABELS.items()
    )
    return f'<span class="note">{chips}</span>'


def _extracted_fields_table(event: dict[str, Any] | None) -> str:
    """(C) Extracted - Section 40-53. `event` is already `events_api.present()`'s
    own dict, the same one every other consumer of an event reads - never a
    second, parallel reading of the row.

    No numeric confidence field exists anywhere in this codebase to show
    here (investigated first, per Section 18-21: the engine's own Evidence
    dataclass has no such field, only the enum `status` already shown) -
    "Confidence"/"Evidence" rows say so plainly rather than a placeholder
    that implies something is being hidden.
    """
    if event is None:
        return '<p class="note">아직 이 게시물로부터 생성된 canonical event가 없습니다.</p>'
    venue = event.get("venue") or {}
    rows = [
        ["Date", E(event.get("date") or "-")],
        ["Start", E(event.get("start_time") or "-")],
        # v0.86.6 Section 12: NULL is the real stored value and "미정" is
        # what a reader sees - shown together so an operator can tell a
        # genuinely open-ended event (start known, end never guessed) apart
        # from an End row that just says "-" for no particular reason.
        ["End", E(event.get("end_time")) if event.get("end_time")
                else '<span class="badge muted">NULL</span> (미정)'],
        ["Type", E(event.get("event_type_label") or "-")],
        ["Format", _format_chips(event.get("event_type"))],
        ["Genre", E(event.get("genre_label") or "-")],
        ["Resolved Venue", E(venue.get("name") or "-")
         + (f' <span class="badge muted">{E(venue.get("status") or "-")}</span>'
            if venue.get("status") else "")],
        ["DJ", E(event.get("dj") or "-")],
        ["Fee", E(event.get("fee_display_text")
                  or (f'{event["fee"]:,}원' if event.get("fee") is not None else "-"))],
        ["Region", E(event.get("region") or "-")],
        ["Status", E(event.get("status") or "-") + " - "
         + E(event.get("status_label") or "-")],
        ["Human Reviewed", "예" if event.get("human_reviewed") else "아니오"],
        ["Confidence (numeric)", '<span class="note">해당 필드 없음 - 엔진은 숫자 confidence를 '
         "기록하지 않고 위 Status(엔진 상태)만 있습니다</span>"],
    ]
    return _table(["Field", "Value"], rows, empty="-")


@router.get("/admin/sources/{source_id}/items/{source_item_id}", response_class=HTMLResponse)
def admin_source_item_detail(
    source_id: int, source_item_id: int, request: Request,
    _: str = Depends(require_admin),
) -> HTMLResponse:
    """The Item Audit Detail (v0.86.4 Section 40-53, 93-95): Original ->
    Acquired -> Extracted -> Public, side by side, so an operator can spot
    "in the original but missing from Extracted" or "shown in Public but
    different from the original" without cross-referencing four screens by
    hand. Read-only (Section 107-112): nothing here saves anything."""
    with _connection() as con:
        source = sources.get_source(con, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="source not found")
        item = content_store.detail(con, source_item_id)
        if item is None or item.get("source_id") != source_id:
            raise HTTPException(status_code=404, detail="item not found on this source")
        event = events_api.get_event_by_source_item(con, source_item_id)
        terms = public._enabled_terms(con)

    content = item.get("content") or {}
    body_text = content.get("extracted_text")
    collector_url = item.get("url")
    public_source_url = (
        events_api.valid_public_url(events_api.resolve_public_source_url(collector_url))
        if collector_url else None
    )

    original = _table(["Field", "Value"], [
        ["Source", E(item.get("source_name") or "-")
         + f' <span class="tierbadge {E(source_priority.tier_of(item.get("source_role")).lower())}">'
         f'{E(source_priority.label_of(item.get("source_role")))}</span>'],
        ["Platform", E(item.get("platform") or "-")],
        ["Published At", E(str(item.get("published_at") or "-")[:19])],
        ["Collected At", E(str(item.get("collected_at") or "-")[:19])],
        ["Collector URL", f'<span title="{E(collector_url)}">{E(_truncate(collector_url, 60))}</span>'
         if collector_url else "-"],
        ["Public URL", (
            f'<a href="{E(public_source_url)}" target="_blank" rel="noopener noreferrer">'
            f'원문보기 &#8599;</a>'
        ) if public_source_url else '<span class="badge warn">no public URL</span>'],
    ], empty="-")

    # (B) Acquired - Section 109: raw stored text is rendered escaped, never
    # as trusted HTML. This is DanceMate's own stored copy, explicitly
    # labelled as such - never presented as "the real site's screen"
    # (Section 88-91): the Public URL above, opened in a new tab, is the
    # only authoritative view of the original.
    shown_text = (body_text or "")[:4000]
    truncated_note = (
        '<p class="note">(4000자로 잘림 - 전체 원문은 위 Public URL에서 확인)</p>'
        if body_text and len(body_text) > 4000 else ""
    )
    acquired = _table(["Field", "Value"], [
        ["Fetch/Acquisition Status", E(content.get("acquisition_status") or "-")],
        ["Acquisition Method", E(content.get("acquisition_method") or "-")],
        ["HTTP Status", E(str(content.get("http_status") or "-"))],
        ["Content Length", E(str(content.get("content_length") or "-"))],
        ["Image Count", E(str(content.get("image_count") or "-"))],
        ["Title (stored)", E(item.get("title") or "-")],
    ], empty="-") + (
        f'<div class="rawtext">{E(shown_text) or "(본문 없음 - 수집된 텍스트가 없습니다)"}</div>'
        + truncated_note
    )

    extracted = _extracted_fields_table(event)

    if event is not None:
        preview = (
            f'<div class="previewbox"><ul class="events" style="list-style:none;padding:0;margin:0">'
            f'<li class="event">'
            f'{public._timeline_line1(event, terms=terms)}'
            f'{public._timeline_line2(event)}'
            f'</li>'
            f'{public._timeline_line3(event)}'
            "</ul></div>"
            '<p class="note">실제 Public Timeline과 동일한 렌더러(runtime/public.py)를 '
            "그대로 호출한 결과입니다 - 별도로 유지되는 admin 전용 포맷터가 아닙니다.</p>"
        )
    else:
        preview = '<p class="note">canonical event가 없어 Public 화면에 표시되지 않습니다.</p>'

    candidate = {
        "start_time": event.get("start_time") if event else None,
        "end_time": event.get("end_time") if event else None,
        "fee": event.get("fee") if event else None,
        "venue": (event.get("venue") or {}).get("name") if event else None,
    }
    hints = review_hints.hints(candidate, body_text) if body_text else []
    hints_html = (
        "".join(
            f'<span class="hint {E(h["severity"])}">[{E(h["severity"])}] '
            f'{E(h["field"])}: {E(h["message"])}</span>'
            for h in hints
        ) or '<p class="note">아무 힌트도 없습니다 (본문과 추출 결과가 겉보기에 일치합니다).</p>'
    )

    body = (
        f'<p class="sub"><a href="/admin/sources/{source_id}">&larr; {E(source["name"])}</a></p>'
        f'<h2>{E(item.get("title") or f"Item #{source_item_id}")}</h2>'
        f'<style>{public.STYLE}</style>'
        '<div class="compare">'
        f'<div class="col"><h3>(A) Original</h3>{original}</div>'
        f'<div class="col"><h3>(B) Acquired</h3>{acquired}</div>'
        f'<div class="col"><h3>(C) Extracted</h3>{extracted}</div>'
        f'<div class="col"><h3>(D) Public Display</h3>{preview}</div>'
        "</div>"
        "<h2>Review Hints</h2>"
        '<p class="note">추출 결과를 바로잡지 않습니다 - 원문과 다를 수 있는 지점만 알려줍니다 '
        "(runtime/review_hints.py, 기존 로직 재사용).</p>"
        f"{hints_html}"
    )
    return HTMLResponse(
        _page(f"Item #{source_item_id}", "/admin/sources", body, flash=_flash(request),
              wide=True)
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

def _venue_extras(venue: dict[str, Any], aliases: list[dict[str, Any]],
                  usage: dict[int, int], all_genres: list[dict[str, Any]],
                  observed_genres: list[dict[str, Any]] | None = None) -> str:
    """Aliases and confirmed genres: their own records, their own forms.

    Neither is a single value with a cell to sit in - an alias is added and
    removed one at a time, and the genre set is a checkbox group - so both
    stay the sub-editors they always were, beside the row rather than in it.
    """
    from . import master_admin

    return ('<details><summary>Aliases &amp; Dance Genres</summary>'
            + master_admin.alias_editor(venue, aliases, usage)
            + master_admin.genre_editor(venue, all_genres, observed_genres)
            + "</details>")


# --- venue linked events (v0.86.9) -------------------------------------------

VENUE_EVENTS_PARAM = "venue_events"
VENUE_EVENTS_PAGE_PARAM = "venue_events_page"


def _positive_int(raw: Any) -> int | None:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _venue_events_link(view: str, venue: dict[str, Any], is_open: bool) -> str:
    """[연결 행사 N] beside [편집]: opens this venue's events under its row,
    on the same list view - page, filters and any open editor kept."""
    from . import master_admin

    vid = venue["venue_id"]
    count = venue.get("events") or 0
    if is_open:
        href = master_admin._rebuilt(
            view, drop=(VENUE_EVENTS_PARAM, VENUE_EVENTS_PAGE_PARAM),
            anchor=master_admin.row_id("VENUE", vid))
        return (f'<a class="rowbtn on" href="{E(href)}" aria-expanded="true">'
                f'연결 행사 {count}</a>')
    href = master_admin._rebuilt(
        view, drop=(VENUE_EVENTS_PARAM, VENUE_EVENTS_PAGE_PARAM),
        add=[(VENUE_EVENTS_PARAM, str(vid))], anchor=f"events-VENUE-{vid}")
    return f'<a class="rowbtn" href="{E(href)}" aria-expanded="false">연결 행사 {count}</a>'


def _event_clock(row: dict[str, Any]) -> str:
    start, end = row.get("start_time"), row.get("end_time")
    if not start:
        return '<span class="muted">-</span>'
    text = start.strftime("%H:%M")
    if end:
        text += "–" + end.strftime("%H:%M") + ("+1" if row.get("end_day_offset") else "")
    return E(text)


def _venue_events_panel(view: str, venue: dict[str, Any], linked: dict[str, Any]) -> str:
    """One venue's events, in the row directly under it."""
    from . import master_admin, pagination, venue_resolution

    vid = venue["venue_id"]
    close = master_admin._rebuilt(view, drop=(VENUE_EVENTS_PARAM, VENUE_EVENTS_PAGE_PARAM),
                                  anchor=master_admin.row_id("VENUE", vid))
    groups = linked.get("groups", len(linked["rows"]))
    title = (f'<h3>{E(venue["name"])} · 연결 행사 {linked["total"]}건'
             + (f" · 반복 행사 {groups}개" if linked["total"] else "")
             + f' <a class="rowbtn" href="{E(close)}">닫기</a></h3>')
    if not linked["rows"]:
        return (f'<div class="eventpanel" id="events-VENUE-{vid}">{title}'
                '<p class="note">연결된 행사가 없습니다.</p></div>')
    note = ('<p class="note">같은 이름·같은 요일의 행사는 한 줄로 묶고 가장 최근 회차를 '
            f'보여줍니다 - 연결 행사 {linked["total"]}건이 {groups}줄로 정리되었습니다.</p>')
    today = events_api.today()
    rows, attrs = [], []
    for row in linked["rows"]:
        day = row["event_date"]
        state = [_badge(row.get("engine_status")), _badge(row.get("review_state"))]
        if row.get("canonical_event_id"):
            state.append(_badge(f"MERGED #{row['canonical_event_id']}", "warn"))
        elif row.get("listing_state") != "LISTED":
            state.append(_badge(row.get("listing_state"), "warn"))
        links = [f'<a href="/admin/review/{row["candidate_id"]}">검토</a>']
        if row.get("publicly_visible"):
            links.append(f'<a href="/events/{row["event_id"]}">공개</a>')
        shown = {"id": row["event_id"], "name": row.get("event_name"),
                 "genre": row.get("genre_code"), "event_type": row.get("event_type"),
                 "event_formats": row.get("event_formats"),
                 "event_type_label": events_api.event_kind_label(
                     row.get("event_type"), row.get("event_formats"))}
        kind = public._event_kind(shown, linked.get("terms"))
        rows.append([
            f"{E(day.isoformat())} ({public.WEEKDAYS[day.weekday()]})",
            _event_clock(row),
            E(row.get("event_name") or "-"),
            E(row.get("genre_name") or "-"),
            public._kind_html(shown, kind, f"kind-why-v{row['event_id']}"),
            f'{row.get("occurrences", 1)}회',
            " ".join(state),
            " · ".join(links),
        ])
        attrs.append(' class="pastevent"' if day < today else "")
    table = _table(["날짜", "시작", "행사", "장르", "분류", "회차", "상태", "링크"], rows,
                   empty="연결된 행사가 없습니다.", row_attrs=attrs)
    size = venue_resolution.VENUE_EVENTS_PAGE_SIZE
    last = pagination.total_pages(groups, page_size=size)
    pager = ""
    if last > 1:
        page = linked["page"]

        def step(target: int, label: str, disabled: bool) -> str:
            if disabled:
                return f'<span class="pager-link off">{E(label)}</span>'
            href = master_admin._rebuilt(view, drop=(VENUE_EVENTS_PAGE_PARAM,),
                                         add=[(VENUE_EVENTS_PAGE_PARAM, str(target))],
                                         anchor=f"events-VENUE-{vid}")
            return f'<a class="pager-link" href="{E(href)}">{E(label)}</a>'

        pager = ('<div class="pager"><span class="pager-count">'
                 f'반복 행사 {groups}개</span><span class="pager-nav">'
                 + step(page - 1, "Previous", page <= 1)
                 + f'<span class="pager-status">Page {page} / {last}</span>'
                 + step(page + 1, "Next", page >= last) + "</span></div>")
    return f'<div class="eventpanel" id="events-VENUE-{vid}">{title}{note}{table}{pager}</div>'


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
def admin_venues(request: Request, region: str = "",
                 genres: list[str] = Query(default=[]),
                 _: str = Depends(require_admin)) -> HTMLResponse:
    """v0.86.7 Section 1-11: a region selector (exact `venues.region_id`
    match, never fuzzy region-name comparison) and a multi-select genre
    filter (OR across the chosen genres, AND with region) - both kept in
    the query string (`?region=<code>&genres=<code>,<code>`) so a reload
    or a shared link keeps the same view. AND/OR toggle UI is deliberately
    out of scope this release (Section 5) - OR is the only behaviour.
    """
    from . import pagination, venue_resolution  # local: keeps the v0.75 console import list stable

    with _connection() as con:
        regions = master_data.list_regions(con)
        all_genres = master_data.list_genres(con, enabled_only=True)

        region_by_code = {r["code"]: r for r in regions}
        genre_by_code = {g["code"]: g for g in all_genres}
        selected_region = region_by_code.get(region.strip().upper()) if region.strip() else None
        # Accepts either repeated ?genres=TANGO&genres=SALSA (what the
        # checkbox form below submits) or a single comma-joined
        # ?genres=TANGO,SALSA (Section 8's own example URL shape) - both
        # land in the same place.
        selected_genre_codes = [
            c.strip().upper() for raw in genres for c in raw.split(",") if c.strip()
        ]
        selected_genre_ids = [
            genre_by_code[c]["genre_id"] for c in selected_genre_codes if c in genre_by_code
        ]
        region_id = selected_region["region_id"] if selected_region else None

        total = master_data.count_venues(
            con, region_id=region_id, genre_ids=selected_genre_ids or None)
        page = pagination.resolve_page(request.query_params.get("page"), total)
        venues = venue_resolution.venues_with_usage(
            con, region_id=region_id, genre_ids=selected_genre_ids or None,
            limit=pagination.PAGE_SIZE, offset=pagination.sql_offset(page),
        )
        alias_rows = {v["venue_id"]: master_data.venue_aliases(con, v["venue_id"])
                      for v in venues}
        alias_usage = {v["venue_id"]: master_data.venue_alias_usage(con, v["venue_id"])
                       for v in venues}
        observed_genres = {v["venue_id"]: master_data.observed_venue_genres(con, v["venue_id"])
                           for v in venues}
        # v0.86.9: at most one venue's events, and only when asked for - a
        # list page never renders every venue's events at once.
        linked = None
        open_events = _positive_int(request.query_params.get(VENUE_EVENTS_PARAM))
        if open_events is not None and any(v["venue_id"] == open_events for v in venues):
            # v0.87.0: every linked event is grouped first (same title, same
            # weekday), then the groups are paged - never page first and
            # group after, which would let one repeating event push another
            # off the page.
            linked_total = venue_resolution.count_venue_events(con, open_events)
            groups = venue_resolution.venue_event_groups(con, open_events)
            linked_size = venue_resolution.VENUE_EVENTS_PAGE_SIZE
            linked_page = pagination.resolve_page(
                request.query_params.get(VENUE_EVENTS_PAGE_PARAM), len(groups),
                page_size=linked_size)
            first = pagination.sql_offset(linked_page, page_size=linked_size)
            linked = {
                "venue_id": open_events, "total": linked_total, "groups": len(groups),
                "page": linked_page, "rows": groups[first:first + linked_size],
                "terms": public._enabled_terms(con),
            }

    from . import master_admin, master_edit

    view = master_admin.current_view(request)
    editing_venue = master_admin.editing_id(request, master_edit.VENUE)

    genre_names = {g["code"]: g["name"] for g in all_genres}

    def _alias_cell(v: dict[str, Any]) -> str:
        return ", ".join(E(a) for a in (v.get("aliases") or [])) or "-"

    def _genre_cell(v: dict[str, Any]) -> str:
        # v0.85.7 (Section 21): "Tango" / "Tango · Salsa" - a real name per
        # genre, not the raw code, same convention as everywhere else this
        # console shows a genre to an operator.
        return " · ".join(
            E(genre_names.get(code, code)) for code in (v.get("genre_codes") or [])) or "-"

    def _events_cell(v: dict[str, Any]) -> str:
        if not v["events"]:
            return '<span class="muted">0</span>'
        return (f'<strong>{v["events"]}</strong>'
                + (f' <span class="muted">({v["listed_events"]} listed)</span>'
                   if v["listed_events"] else ""))

    venue_forms, rows, row_attrs, row_details = [], [], [], []
    for v in venues:
        vid = v["venue_id"]
        editing = vid == editing_venue
        row_attrs.append(_row_attrs(master_edit.VENUE, vid, editing))
        extras = _venue_extras(v, alias_rows.get(vid, []), alias_usage.get(vid, {}),
                               all_genres, observed_genres.get(vid, []))
        events_open = linked is not None and linked["venue_id"] == vid
        events_link = _venue_events_link(view, v, events_open)
        row_details.append(_venue_events_panel(view, v, linked) if events_open else None)
        if editing:
            venue_forms.append(master_admin.row_form(master_edit.VENUE, vid, view))
            rows.append([
                master_admin.row_input(master_edit.VENUE, vid, "name", v["name"]),
                master_admin.row_input(
                    master_edit.VENUE, vid, "region_id", kind="select",
                    options=master_admin._options(
                        regions, id_key="region_id", label_key="name",
                        selected=v.get("region_id"))),
                # Notes is editable and has no column of its own; it rides
                # beside the address rather than being left out of the row.
                master_admin.row_input(master_edit.VENUE, vid, "address",
                                       v.get("address"))
                + master_admin.row_input(master_edit.VENUE, vid, "notes",
                                         v.get("notes"), label="Notes",
                                         kind="textarea"),
                _alias_cell(v), _genre_cell(v), _events_cell(v),
                master_admin.enabled_input(master_edit.VENUE, vid, v["enabled"]),
                master_admin.row_actions(view, master_edit.VENUE, vid) + events_link
                + extras
                + '<p class="note">이름을 바꿔도 같은 장소로 남습니다 — '
                  "연결된 Event는 그대로입니다.</p>",
            ])
            continue
        rows.append([
            E(v["name"]), E(str(v.get("region_name") or "-")),
            E(str(v.get("address") or "-")),
            _alias_cell(v), _genre_cell(v), _events_cell(v),
            _badge("ENABLED" if v["enabled"] else "DISABLED",
                   "ok" if v["enabled"] else "muted"),
            '<div class="actionbar">'
            + master_admin.edit_link(view, master_edit.VENUE, vid) + events_link
            + extras + _venue_actions(v) + "</div>"])
    region_options = "".join(
        f'<option value="{r["region_id"]}">{E(r["name"])}</option>' for r in regions
    )
    genre_boxes = "".join(
        f'<label class="chip"><input type="checkbox" name="genre_ids" '
        f'value="{g["genre_id"]}"> {E(g["name"])}</label>' for g in all_genres
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
    <div><label>Dance Genres</label><div class="grid">{genre_boxes}</div></div>
  </div>
  <div class="actions"><button class="primary">Add Venue</button></div>
  <p class="note">Aliases are how "La Ventana", "라벤타나" and "벤타나" resolve to
  one venue. The venue name is registered as an alias automatically. Dance
  Genres는 확실히 아는 경우에만 체크하세요 - 비워두면 나중에 편집에서 추가할 수
  있습니다.</p>
</form></details>"""

    csv_bar = (
        '<p class="actions">'
        '<a href="/admin/venues/export.csv"><button>Export CSV</button></a> '
        '<a href="/admin/venues/import"><button>Import CSV</button></a>'
        "</p>"
    )

    # v0.86.7 Section 1-11: region select + genre multi-select checkboxes,
    # a plain GET form so the result lands on a shareable, reload-safe
    # ?region=<code>&genres=<code>,<code> URL (Section 8) - no JS required.
    filter_region_options = "".join(
        f'<option value="{E(r["code"])}"'
        f'{" selected" if selected_region and selected_region["code"] == r["code"] else ""}>'
        f'{E(r["name"])}</option>'
        for r in regions
    )
    filter_genre_chips = "".join(
        f'<label class="chip"><input type="checkbox" name="genres" value="{E(g["code"])}"'
        f'{" checked" if g["code"] in selected_genre_codes else ""}> {E(g["name"])}</label>'
        for g in all_genres
    )
    filter_bar = f"""
<form method="get" action="/admin/venues" class="filters">
  <div class="row">
    <span class="key">지역</span>
    <select name="region"><option value="">전체</option>{filter_region_options}</select>
  </div>
  <div class="row">
    <span class="key">춤 종류</span>
    {filter_genre_chips}
  </div>
  <div class="row">
    <button class="apply" type="submit">적용</button>
    <a href="/admin/venues"><button type="button">초기화</button></a>
  </div>
</form>
<p class="note">Venues: <strong>{total}</strong></p>"""

    filter_query = {}
    if selected_region:
        filter_query["region"] = selected_region["code"]
    if selected_genre_codes:
        filter_query["genres"] = ",".join(selected_genre_codes)

    body = ('<h2>Venues</h2>'
            '<p class="note">Venue strings read from posts that this list does '
            'not recognise are queued at '
            '<a href="/admin/venues/unresolved">Unresolved Venues</a>. '
            'Deleting a venue removes the link and nothing else — the posts, '
            'the evidence and the events stay, and the strings they were read '
            'from go back in that queue.</p>'
            ) + csv_bar + add_form + filter_bar + "".join(venue_forms) + _table(
        ["Name", "Region", "Address", "Aliases", "Dance Genres", "Events using",
         "State", "Actions"],
        rows, empty="no venue registered yet", row_attrs=row_attrs,
        row_details=row_details,
    ) + pagination.nav("/admin/venues", filter_query, page, total)
    return HTMLResponse(_page("Venues", "/admin/venues", body, flash=_flash(request)))


@router.post("/admin/venues")
def admin_create_venue(
    name: str = Form(...),
    region_id: str = Form(""),
    address: str = Form(""),
    aliases: str = Form(""),
    notes: str = Form(""),
    genre_ids: list[int] = Form(default=[]),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
    try:
        with _connection() as con:
            venue = master_data.create_venue(
                con, name=name, region_id=int(region_id) if region_id else None,
                address=address.strip() or None, notes=notes.strip() or None,
                aliases=alias_list,
            )
            if genre_ids:
                from . import master_edit
                master_edit.set_venue_genres(
                    con, venue["venue_id"], genre_ids, reviewer=reviewer,
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

    view = master_admin.current_view(request)
    editing_organizer = master_admin.editing_id(request, master_edit.ORGANIZER)

    forms, rows, row_attrs = [], [], []
    for o in organizers:
        oid = o["organizer_id"]
        editing = oid == editing_organizer
        row_attrs.append(_row_attrs(master_edit.ORGANIZER, oid, editing))
        if editing:
            forms.append(master_admin.row_form(master_edit.ORGANIZER, oid, view))
            rows.append([
                master_admin.row_input(master_edit.ORGANIZER, oid, "name", o["name"]),
                master_admin.row_input(
                    master_edit.ORGANIZER, oid, "genre_id", kind="select",
                    options=master_admin._options(
                        genres, id_key="genre_id", label_key="code",
                        selected=o.get("genre_id"))),
                master_admin.row_input(
                    master_edit.ORGANIZER, oid, "region_id", kind="select",
                    options=master_admin._options(
                        regions, id_key="region_id", label_key="name",
                        selected=o.get("region_id"))),
                # Notes has no column; it is editable, so it rides here rather
                # than being the one field left behind by the row editor.
                master_admin.row_input(master_edit.ORGANIZER, oid, "contact_url",
                                       o.get("contact_url"))
                + master_admin.row_input(master_edit.ORGANIZER, oid, "notes",
                                         o.get("notes"), label="Notes"),
                master_admin.enabled_input(master_edit.ORGANIZER, oid, o["enabled"]),
                master_admin.row_actions(view, master_edit.ORGANIZER, oid)
                + '<p class="note">이름을 바꿔도 같은 주최자로 남습니다 — '
                  "연결된 Event는 그대로입니다.</p>",
            ])
            continue
        rows.append([
            E(o["name"]), E(str(o.get("genre_code") or "-")),
            E(str(o.get("region_name") or "-")),
            E(str(o.get("contact_url") or "-")),
            _badge("ENABLED" if o["enabled"] else "DISABLED",
                   "ok" if o["enabled"] else "muted"),
            '<div class="actionbar">'
            + master_admin.edit_link(view, master_edit.ORGANIZER, oid)
            + master_admin.toggle_form(master_edit.ORGANIZER, oid, o["enabled"], view)
            + "</div>"])
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
            "Event가 계속 해석되어야 합니다.</p>" + add_form) + "".join(forms) + _table(
        ["Name", "Genre", "Region", "Contact", "State", "Actions"], rows,
        empty="no organizer registered yet", row_attrs=row_attrs,
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

def _row_attrs(entity_type: str, entity_id: int, editing: bool) -> str:
    """A list row's anchor, and whether it is the one being edited (v0.86.8).

    The anchor is what a save redirects to, so a browser lands back on the
    same row of a long table rather than at the top of it.
    """
    from . import master_admin

    cls = ' class="editing"' if editing else ""
    return f' id="{master_admin.row_id(entity_type, entity_id)}"{cls}'


def _delete_form(kind: str, entity_id: int, name: str, *, core: bool,
                 usage: dict[str, int]) -> str:
    """v0.86.7 Section 15-16, 21: a collapsed confirmation showing exactly
    what a plain "Delete" button never would - the reference counts an
    operator needs to see BEFORE the database refuses (or, when nothing
    references the row, before it actually deletes). No cascade option is
    offered anywhere in this form (Section 17-18) - a referenced row is
    blocked, full stop, never unlinked or reassigned this release."""
    total = sum(usage.values())
    if core:
        body = (f'<p class="note">{E(name)}은 핵심 장르라 삭제할 수 없습니다 '
                "(TANGO/SALSA/SWING는 항상 보호됩니다).</p>")
    elif total:
        body = (
            f'<p class="flash bad">삭제할 수 없습니다 — '
            f'Venue {usage.get("venues", 0)}건, Organizer {usage.get("organizers", 0)}건, '
            f'Source {usage.get("sources", 0)}건, Event {usage.get("events", 0)}건'
            + "".join(f", {label} {usage[key]}건" for key, label in
                      (("communities", "Community"), ("notices", "Notice"))
                      if key in usage)
            + "</p>"
        )
    else:
        # No client-side confirm() - this console has never used inline JS
        # for a consequential action anywhere else; the collapsed <details>
        # a reader has to open first, plus this explicit question, is the
        # same "you have to mean it" gate every other destructive form here
        # already uses (venue delete, alias remove).
        body = (
            f'<p class="note">참조가 없습니다 - 삭제할 수 있습니다.</p>'
            f'<p class="note">{E(name)}을(를) 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.</p>'
            f'<form method="post" action="/admin/{kind}/{entity_id}/delete">'
            '<button class="primary">Delete</button></form>'
        )
    return f'<details><summary>Delete</summary>{body}</details>'


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
        # v0.86.7 Section 14-16: reference counts for the Delete confirmation,
        # computed while still inside the connection - genres/regions are a
        # handful of rows per page, never worth a batched query here.
        genre_usage_by_id = {g["genre_id"]: master_data.genre_usage(con, g["genre_id"])
                             for g in genres}
        region_usage_by_id = {r["region_id"]: master_data.region_usage(con, r["region_id"])
                              for r in regions}

    from . import master_admin, master_edit

    # v0.86.8 Section 4: the list URL as it stands right now - both page
    # numbers, and anything else in the query string - so an edit comes back
    # to this exact view instead of a bare /admin/master.
    view = master_admin.current_view(request)
    editing_genre = master_admin.editing_id(request, master_edit.GENRE)
    editing_region = master_admin.editing_id(request, master_edit.REGION)

    code_note = "code는 다른 레코드가 이 행을 가리키는 이름이라 수정할 수 없습니다"
    genre_forms, genre_rows, genre_attrs = [], [], []
    for g in genres:
        gid = g["genre_id"]
        editing = gid == editing_genre
        genre_attrs.append(_row_attrs(master_edit.GENRE, gid, editing))
        if editing:
            genre_forms.append(master_admin.row_form(master_edit.GENRE, gid, view))
            genre_rows.append([
                f'<code>{E(g["code"])}</code>',
                master_admin.row_input(master_edit.GENRE, gid, "name", g["name"]),
                master_admin.enabled_input(master_edit.GENRE, gid, g["enabled"]),
                master_admin.row_actions(view, master_edit.GENRE, gid)
                + f'<p class="note">{E(code_note)}</p>',
            ])
            continue
        genre_rows.append([
            f'<code>{E(g["code"])}</code>', E(g["name"]),
            _badge("ENABLED" if g["enabled"] else "DISABLED",
                   "ok" if g["enabled"] else "muted"),
            '<div class="actionbar">'
            + master_admin.edit_link(view, master_edit.GENRE, gid)
            + master_admin.toggle_form(master_edit.GENRE, gid, g["enabled"], view)
            + _delete_form(
                "genres", gid, g["name"],
                core=g["code"] in master_edit.CORE_GENRE_CODES,
                usage=genre_usage_by_id[gid])
            + "</div>"])

    region_forms, region_rows, region_attrs = [], [], []
    for r in regions:
        rid = r["region_id"]
        editing = rid == editing_region
        region_attrs.append(_row_attrs(master_edit.REGION, rid, editing))
        if editing:
            region_forms.append(master_admin.row_form(master_edit.REGION, rid, view))
            region_rows.append([
                f'<code>{E(r["code"])}</code>',
                master_admin.row_input(master_edit.REGION, rid, "name", r["name"]),
                master_admin.row_input(master_edit.REGION, rid, "country", r["country"]),
                # District has no column of its own; it is still editable, so
                # it rides in the cell next to the city it belongs to rather
                # than being the one field an operator has to go elsewhere for.
                master_admin.row_input(master_edit.REGION, rid, "city", r.get("city"))
                + master_admin.row_input(master_edit.REGION, rid, "district",
                                         r.get("district"), label="District"),
                master_admin.enabled_input(master_edit.REGION, rid, r["enabled"]),
                master_admin.row_actions(view, master_edit.REGION, rid)
                + f'<p class="note">{E(code_note)}</p>',
            ])
            continue
        region_rows.append([
            f'<code>{E(r["code"])}</code>', E(r["name"]), E(r["country"]),
            E(str(r.get("city") or "-")),
            _badge("ENABLED" if r["enabled"] else "DISABLED",
                   "ok" if r["enabled"] else "muted"),
            '<div class="actionbar">'
            + master_admin.edit_link(view, master_edit.REGION, rid)
            + master_admin.toggle_form(master_edit.REGION, rid, r["enabled"], view)
            + _delete_form(
                "regions", rid, r["name"], core=False,
                usage=region_usage_by_id[rid])
            + "</div>"])

    body = (
        "<h2>Genres</h2>"
        + """<details><summary>Add Genre</summary>
<form method="post" action="/admin/genres"><div class="grid">
<div><label>Code</label><input name="code" required placeholder="BACHATA"></div>
<div><label>Name</label><input name="name" required placeholder="Bachata"></div>
</div><div class="actions"><button class="primary">Add Genre</button></div>
<p class="note">Genres are disabled, never deleted - events already tagged with
one still have to resolve.</p></form></details>"""
        + "".join(genre_forms)
        + _table(["Code", "Name", "State", "Actions"], genre_rows, empty="no genre",
                 row_attrs=genre_attrs)
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
        + "".join(region_forms)
        + _table(["Code", "Name", "Country", "City", "State", "Actions"], region_rows,
                 empty="no region", row_attrs=region_attrs)
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


@router.post("/admin/genres/{genre_id}/delete")
def admin_delete_genre(
    genre_id: int, reviewer: str = Depends(require_admin)
) -> RedirectResponse:
    """v0.86.7 Section 13-19: blocked outright (no cascade, no unlink) when
    anything still references the genre, or when it's one of the three
    core genres - `master_edit.delete_genre()` does the actual check."""
    from . import master_edit

    with _connection() as con:
        try:
            deleted = master_edit.delete_genre(con, genre_id, reviewer=reviewer)
        except master_edit.EditError as exc:
            return _back("/admin/master", str(exc), "bad")
    return _back("/admin/master", f"{deleted['genre']['name']} 장르를 삭제했습니다")


@router.post("/admin/regions/{region_id}/delete")
def admin_delete_region(
    region_id: int, reviewer: str = Depends(require_admin)
) -> RedirectResponse:
    """The region twin of `admin_delete_genre()`."""
    from . import master_edit

    with _connection() as con:
        try:
            deleted = master_edit.delete_region(con, region_id, reviewer=reviewer)
        except master_edit.EditError as exc:
            return _back("/admin/master", str(exc), "bad")
    return _back("/admin/master", f"{deleted['region']['name']} 지역을 삭제했습니다")


@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    """Admin settings.

    v0.87.0: the v0.86.4 "사용자 Timeline 확인 표시" checklist is retired. Its
    "?" meant an unverified post but sat after the event's kind and read as
    doubt about the kind; the "?" now means the kind itself could not be
    settled, and what settles it is the terminology below. The old table and
    its row are left in the database untouched - nothing reads them now.
    """
    from . import event_terms  # local: keeps the v0.75 console import list stable

    with _connection() as con:
        terms = event_terms.list_terms(con)
        genres = master_data.list_genres(con)

    body = ('<p class="note">행사 종류 옆의 "?"는 이제 행사 유형을 제목만으로 확정하지 못했을 '
            "때만 표시됩니다 - 이전의 \"원문 확인 필요\"(검증 전 상태) 표시는 v0.87.0에서 "
            "제거되었습니다. 유형은 아래 행사 용어로 판정합니다.</p>"
            + _event_terms_section(request, terms, genres))
    return HTMLResponse(_page("Settings", "/admin/settings", body, flash=_flash(request)))


# --- Event terminology (v0.86.9) ---------------------------------------------

TERM_ENTITY = "TERM"


def _term_format_chips(selected: "tuple[str, ...] | set[str]", *, form_id: str | None = None) -> str:
    """One checkbox per canonical Event Format - pick one or several."""
    from . import event_terms

    bound = f' form="{E(form_id)}"' if form_id else ""
    return '<div class="chipset">' + "".join(
        f'<label class="chip"><input type="checkbox" name="formats" value="{code}"{bound}'
        f'{" checked" if code in selected else ""}> '
        f'{E(events_api.EVENT_FORMAT_LABELS.get(code, code))} <code>{code}</code></label>'
        for code in event_terms.FORMAT_CHOICES) + "</div>"


def _formats_text(formats: "tuple[str, ...]") -> str:
    return " + ".join(
        f'{E(events_api.EVENT_FORMAT_LABELS.get(f, f))} <code>{E(f)}</code>' for f in formats
    ) or '<span class="muted">-</span>'


def _event_terms_section(request: Request, terms: list[dict[str, Any]],
                         genres: list[dict[str, Any]]) -> str:
    from . import master_admin

    view = master_admin.current_view(request)
    editing = master_admin.editing_id(request, TERM_ENTITY)
    genre_choices = [g for g in genres]
    forms, rows, attrs = [], [], []
    for t in terms:
        tid = t["event_term_id"]
        is_editing = tid == editing
        attrs.append(_row_attrs(TERM_ENTITY, tid, is_editing))
        if is_editing:
            fid = master_admin.form_id(TERM_ENTITY, tid)
            forms.append(master_admin.row_form(
                TERM_ENTITY, tid, view, action=f"/admin/settings/event-terms/{tid}/edit"))
            rows.append([
                master_admin.row_input(
                    TERM_ENTITY, tid, "genre_id", kind="select",
                    options=master_admin._options(genre_choices, id_key="genre_id",
                                                  label_key="name", selected=t["genre_id"],
                                                  blank=None)),
                master_admin.row_input(TERM_ENTITY, tid, "term", t["term"]),
                _term_format_chips(t["formats"], form_id=fid),
                master_admin.enabled_input(TERM_ENTITY, tid, t["enabled"]),
                master_admin.row_actions(view, TERM_ENTITY, tid),
            ])
            continue
        delete = (
            f'<details><summary>Delete</summary><p class="note">'
            f'&#39;{E(t["term"])}&#39; 용어를 삭제합니다. 이미 저장된 행사의 분류는 '
            "그대로이며, 다음 정규화부터 이 용어가 쓰이지 않습니다.</p>"
            f'<form method="post" action="/admin/settings/event-terms/{tid}/delete">'
            f'{master_admin.return_field(view)}'
            '<button class="primary">Delete</button></form></details>'
        )
        rows.append([
            E(t["genre_name"]), E(t["term"]), _formats_text(t["formats"]),
            _badge("ENABLED" if t["enabled"] else "DISABLED",
                   "ok" if t["enabled"] else "muted"),
            '<div class="actionbar">' + master_admin.edit_link(view, TERM_ENTITY, tid)
            + delete + "</div>",
        ])
    genre_options = "".join(
        f'<option value="{g["genre_id"]}">{E(g["name"])}</option>' for g in genres)
    add_form = f"""
<details><summary>용어 추가</summary>
<form method="post" action="/admin/settings/event-terms">
  {master_admin.return_field(view)}
  <div class="grid">
    <div><label>장르</label><select name="genre_id" required>
      <option value="">장르 선택</option>{genre_options}</select></div>
    <div><label>용어</label><input name="term" required placeholder="게시글에 쓰이는 표현"></div>
    <div><label>상태</label><select name="enabled">
      <option value="1" selected>ENABLED</option><option value="0">DISABLED</option></select></div>
  </div>
  <label style="margin-top:10px">표준 분류 (하나 이상)</label>{_term_format_chips(())}
  <div class="actions"><button class="primary">용어 추가</button></div>
</form></details>"""
    return (
        '<h2 id="event-terms">행사 용어 (Event Terminology)</h2>'
        '<p class="note">게시글에 쓰이는 행사 이름을 DanceMate의 표준 분류로 연결합니다. '
        "한 용어가 여러 분류를 가질 수 있습니다 - 쁘롱가는 밀롱가이자 프락티카입니다. "
        "여기 있는 용어는 다음 수집부터 행사 인식과 분류에 쓰이고, 이미 저장된 행사는 "
        "정기 정규화가 다시 만들 때 반영됩니다. 목록에 없는 표현은 억지로 분류하지 않습니다. "
        "대소문자와 공백 차이는 같은 용어로 봅니다.</p>"
        + add_form + "".join(forms)
        + _table(["장르", "용어", "표준 분류", "상태", "Actions"], rows,
                 empty="등록된 용어가 없습니다", row_attrs=attrs)
    )


@router.post("/admin/settings/event-terms")
def admin_create_event_term(
    genre_id: str = Form(""),
    term: str = Form(""),
    formats: list[str] = Form(default=[]),
    enabled: str = Form("1"),
    return_to: str = Form(""),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    from . import event_terms, master_admin

    try:
        with _connection() as con:
            created = event_terms.create_term(con, genre_id=genre_id, term=term,
                                              formats=formats, enabled=enabled == "1")
    except event_terms.TermError as exc:
        return master_admin._back_to_view(TERM_ENTITY, 0, return_to,
                                          f"용어를 추가하지 못했습니다: {exc}", "bad")
    except Exception as exc:  # a race on the unique index, say
        return master_admin._back_to_view(TERM_ENTITY, 0, return_to,
                                          f"용어를 추가하지 못했습니다: {exc}", "bad")
    return master_admin._back_to_view(
        TERM_ENTITY, created["event_term_id"], return_to,
        f"용어 '{created['term']}' 추가됨 ({' + '.join(created['formats'])})")


@router.post("/admin/settings/event-terms/{event_term_id}/edit")
def admin_update_event_term(
    event_term_id: int,
    genre_id: str = Form(""),
    term: str = Form(""),
    formats: list[str] = Form(default=[]),
    enabled: str = Form("1"),
    return_to: str = Form(""),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    from . import event_terms, master_admin

    try:
        with _connection() as con:
            updated = event_terms.update_term(con, event_term_id, genre_id=genre_id,
                                              term=term, formats=formats,
                                              enabled=enabled == "1")
    except event_terms.TermError as exc:
        return master_admin._back_to_view(TERM_ENTITY, event_term_id, return_to,
                                          f"저장하지 못했습니다: {exc}", "bad",
                                          keep_editing=True)
    except Exception as exc:
        return master_admin._back_to_view(TERM_ENTITY, event_term_id, return_to,
                                          f"저장하지 못했습니다: {exc}", "bad",
                                          keep_editing=True)
    return master_admin._back_to_view(
        TERM_ENTITY, event_term_id, return_to,
        f"용어 '{updated['term']}' 저장됨 ({' + '.join(updated['formats'])})")


@router.post("/admin/settings/event-terms/{event_term_id}/delete")
def admin_delete_event_term(
    event_term_id: int,
    return_to: str = Form(""),
    _: str = Depends(require_admin),
) -> RedirectResponse:
    from . import event_terms, master_admin

    try:
        with _connection() as con:
            removed = event_terms.delete_term(con, event_term_id)
    except event_terms.TermError as exc:
        return master_admin._back_to_view(TERM_ENTITY, event_term_id, return_to,
                                          str(exc), "bad")
    return master_admin._back_to_view(TERM_ENTITY, event_term_id, return_to,
                                      f"용어 '{removed['term']}' 삭제됨")


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
