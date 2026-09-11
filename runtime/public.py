"""The alpha user surface: the JSON search API and the three pages on top of it.

This is the first part of DanceMate a dancer sees, so it answers one question
and stops: *what can I go to?* A list of tonight's events, and one page per
event with enough to decide and a link to the post it came from.

Deliberately thin. No account, no map, no recommendations, no design system --
those are decisions that need evidence we do not have yet, and shipping them
now would only make it harder to find out what people actually use. What it
does have to be is honest: a missing fee reads as unknown, a venue we have not
recognised says so, and nothing that is not a live collected post appears here
at all.
"""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import (
    alpha_metrics, db, events_api, feedback, master_data, timeline_settings,
    venue_resolution,
)
from .config import Settings

router = APIRouter(tags=["events"])
api = APIRouter(prefix="/api", tags=["events"])

E = html.escape

_settings_provider: Callable[[], Settings] | None = None


def bind(settings_provider: Callable[[], Settings]) -> None:
    global _settings_provider
    _settings_provider = settings_provider


def _settings() -> Settings:
    if _settings_provider is None:  # pragma: no cover - wiring error
        raise RuntimeError("public router was not bound to a settings provider")
    return _settings_provider()


def _connection():
    return db.connect(_settings(), autocommit=True)


def _json(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code)


# What a reader sees when the database is not reachable. Not an empty list: an
# empty list reads as "nothing is on tonight", which would be a lie.
UNAVAILABLE = "행사 정보를 불러올 수 없습니다. 잠시 후 다시 시도해 주세요."


# --- JSON API ---------------------------------------------------------------

@api.get("/events")
def list_events(
    when: str | None = Query(None, description="today, tomorrow, this_week, weekend, upcoming"),
    date: str | None = Query(None, description="a single day, YYYY-MM-DD (Asia/Seoul)"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    genre: str | None = None,
    genres: list[str] | None = Query(None, description="repeat, or comma-separate"),
    region: str | None = None,
    status: str | None = None,
    limit: int = events_api.DEFAULT_LIMIT,
    offset: int = 0,
    include_past: bool = False,
    include_cancelled: bool = False,
    include_completed: bool = False,
) -> JSONResponse:
    try:
        # Validated before a connection is opened, so a bad query is a 400 even
        # when the database is down.
        events_api.window(when)
        with _connection() as con:
            return _json(events_api.search(
                con, when=when, on=date, date_from=date_from, date_to=date_to,
                genre=genre, genres=_split_genres(genres), region=region,
                status=status, limit=limit, offset=offset,
                include_past=include_past, include_cancelled=include_cancelled,
                include_completed=include_completed,
            ))
    except events_api.SearchError as exc:
        return _json({"detail": str(exc)}, status_code=400)
    except db.DatabaseUnavailable as exc:
        return _json({"detail": UNAVAILABLE, "reason": str(exc)}, status_code=503)


@api.get("/events/{event_id}")
def get_event(event_id: int) -> JSONResponse:
    try:
        with _connection() as con:
            event = events_api.get_event(con, event_id)
    except db.DatabaseUnavailable as exc:
        return _json({"detail": UNAVAILABLE, "reason": str(exc)}, status_code=503)
    if event is None:
        raise HTTPException(status_code=404, detail="no such event")
    return _json(event)


# --- pages ------------------------------------------------------------------

STYLE = """
:root { color-scheme: light dark; --fg:#1b1b1f; --muted:#6b6b76; --line:#e2e2e8;
        --bg:#fbfbfd; --card:#fff; --accent:#8a3ffc; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#ececf1; --muted:#9b9ba6; --line:#33333c; --bg:#161619; --card:#1e1e23; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font-size:16px; line-height:1.55;
       font-family: system-ui, -apple-system, "Segoe UI", "Noto Sans KR", sans-serif; }
main { max-width: 44rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1 { font-size: 1.35rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .75rem; }
a { color: inherit; }
.sub { color: var(--muted); font-size: .875rem; margin: 0 0 1.25rem; }
nav { display:flex; gap:.5rem; flex-wrap:wrap; margin: 0 0 1.5rem; }
nav a { border:1px solid var(--line); border-radius:999px; padding:.3rem .85rem;
        text-decoration:none; font-size:.875rem; background:var(--card); }
nav a[aria-current="page"] { border-color:var(--accent); color:var(--accent); font-weight:600; }
/* v0.88.0: the first screen's directory tabs - one row that scrolls sideways
   on a narrow screen rather than wrapping into a second row of pills. */
nav.dirtabs { flex-wrap:nowrap; overflow-x:auto; gap:.15rem; margin:0 0 1rem;
              border-bottom:1px solid var(--line); -webkit-overflow-scrolling:touch; }
nav.dirtabs a { border:none; border-radius:0; background:none; white-space:nowrap;
                padding:.5rem .8rem; font-size:.95rem; border-bottom:2px solid transparent; }
nav.dirtabs a[aria-current="page"] { border-bottom-color:var(--accent); }
ul.dir { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:.6rem; }
li.dir-item { background:var(--card); border:1px solid var(--line); border-radius:12px;
              padding:.85rem 1rem; overflow-wrap:anywhere; }
li.dir-item > a.dir-link { display:block; text-decoration:none; margin:-.85rem -1rem;
                           padding:.85rem 1rem; }
.dir-name { font-weight:600; }
.dir-meta { color:var(--muted); font-size:.875rem; margin:.1rem 0 0; }
.dir-desc { margin:.35rem 0 0; font-size:.925rem; white-space:pre-line; }
.tags { display:flex; flex-wrap:wrap; gap:.3rem; margin:.45rem 0 0; padding:0; list-style:none; }
.tag { font-size:.75rem; border:1px solid var(--line); border-radius:999px;
       padding:.05rem .55rem; color:var(--muted); }
.tag.pin { border-color:var(--accent); color:var(--accent); }
.dir-links { margin:.45rem 0 0; font-size:.875rem; display:flex; gap:.9rem; flex-wrap:wrap; }
.dir-note { color:var(--muted); font-size:.8rem; margin:0 0 .75rem; }
/* 장소 and 정보원 read as a list: one entry, one line, never wider than the
   page. Short of room, the facts give way first (they only get what is left),
   then the genre list; the name keeps at least a few characters and the link
   is never cut. Anything cut ends in an ellipsis and stays whole in the DOM
   (screen readers read all of it) and in the element's title tooltip. */
ul.dir.rows { gap:0; background:var(--card); border:1px solid var(--line);
              border-radius:12px; overflow:hidden; }
li.dir-row { display:flex; align-items:center; gap:.6rem; min-width:0;
             padding:.55rem .9rem; border-top:1px solid var(--line); white-space:nowrap; }
li.dir-row:first-child { border-top:none; }
li.dir-row .dir-name { flex:0 1 auto; min-width:4.5em; max-width:60%; overflow:hidden;
                       text-overflow:ellipsis; }
li.dir-row .dir-meta { flex:1 1 0%; min-width:0; margin:0; overflow:hidden;
                       text-overflow:ellipsis; font-size:.85rem; }
li.dir-row .tags { display:block; flex:0 3 auto; min-width:0; max-width:35%; margin:0;
                   overflow:hidden; text-overflow:ellipsis; }
li.dir-row .tags .tag { display:inline; }
li.dir-row .tags .tag + .tag { margin-left:.3rem; }
li.dir-row .dir-go { flex:0 0 auto; font-size:.85rem; }
.notice-body { margin:1rem 0; overflow-wrap:anywhere; }
.notice-body p { margin:0 0 .9rem; }
.back { font-size:.875rem; margin:0 0 .75rem; }
ul.events { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:.6rem; }
li.event { background:var(--card); border:1px solid var(--line); border-radius:12px; }
li.event a { display:block; padding:.9rem 1rem; text-decoration:none; }
.when { font-variant-numeric: tabular-nums; font-weight:600; }
.name { margin:.15rem 0; }
/* A source falls back to its raw URL when the post has no title, and a URL
   has nowhere to wrap. Everything else here is Korean, which breaks per
   character; this is for the one string that does not. */
li.event a, .name { overflow-wrap: anywhere; }
.meta { color:var(--muted); font-size:.875rem; display:flex; gap:.6rem; flex-wrap:wrap; }
.unknown { color:var(--muted); font-style:italic; }
.tag { font-size:.7rem; letter-spacing:.04em; text-transform:uppercase;
       border:1px solid var(--line); border-radius:4px; padding:.05rem .35rem; }
.empty { background:var(--card); border:1px dashed var(--line); border-radius:12px;
         padding:1.5rem 1rem; color:var(--muted); }
dl { display:grid; grid-template-columns:auto 1fr; gap:.4rem 1rem; margin:0; }
dt { color:var(--muted); font-size:.875rem; }
dd { margin:0; }
footer { margin-top:3rem; color:var(--muted); font-size:.8rem; border-top:1px solid var(--line);
         padding-top:1rem; }
.filters { margin: 0 0 1.25rem; }
.filters .row { display:flex; gap:.4rem; flex-wrap:wrap; align-items:center; margin-top:.5rem; }
.filters .key { color:var(--muted); font-size:.8rem; width:2.6rem; flex:none; }
.filters a { border:1px solid var(--line); border-radius:999px; padding:.2rem .7rem;
             text-decoration:none; font-size:.8rem; background:var(--card); color:var(--muted); }
.filters a[aria-current="true"] { border-color:var(--accent); color:var(--accent); font-weight:600; }
/* v0.86.8 (Section 1): the style picker is a short row of chips, not a
   page-wide band. `inline-flex` + `width:fit-content` makes it exactly as
   wide as the chips it holds; `min-width` keeps a single short chip from
   collapsing into a sliver, and `max-width:100%` means a long genre name
   (or a lot of them) wraps inside the same box instead of pushing the
   page sideways on a phone. Spacing, border radius and type are the ones
   the chips already had - nothing about the design system moves here. */
.filters form.genres { display:inline-flex; gap:.4rem; flex-wrap:wrap; align-items:center;
                       margin:0 0 .5rem; width:fit-content;
                       min-width:min(100%, 12rem); max-width:100%; }
.filters label.chip { display:inline-flex; align-items:center; gap:.35rem;
                      border:1px solid var(--line); border-radius:999px;
                      padding:.25rem .7rem; font-size:.8rem; background:var(--card);
                      color:var(--muted); cursor:pointer;
                      max-width:100%; overflow-wrap:anywhere; }
.filters label.chip:has(input:checked) { border-color:var(--accent); color:var(--accent);
                                         font-weight:600; }
.filters label.chip:focus-within { outline:2px solid var(--accent); outline-offset:2px; }
.filters label.chip input { accent-color:var(--accent); margin:0; }
.filters .apply { border:1px solid var(--line); border-radius:999px; padding:.25rem .7rem;
                  font-size:.8rem; background:var(--card); color:var(--fg); cursor:pointer; }
.filters form.auto .apply { display:none; }
.status { font-size:.7rem; border:1px solid var(--line); border-radius:4px;
          padding:.05rem .35rem; color:var(--muted); }
.status.ok { border-color:var(--accent); color:var(--accent); }
.status.warn { border-color:#c0392b; color:#c0392b; font-weight:600; }
@media (prefers-color-scheme: dark) { .status.warn { border-color:#ff6b5e; color:#ff6b5e; } }
.status + .status { margin-left:.3rem; }
/* v0.87.0: the "?" beside an event's kind means one thing only - the kind
   itself could not be settled from the title (v0.86.4's "unverified post"
   meaning is retired). A real button, opening a native popover with the
   reasons the decision actually used - no script, keyboard and Esc work. */
.kind-why { font:inherit; font-size:.78em; font-weight:700; line-height:1;
            color:#c0392b; background:none; border:1px solid currentColor;
            border-radius:999px; width:1.4em; height:1.4em; padding:0;
            margin-left:.2em; cursor:pointer; vertical-align:.08em; }
.kind-why:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
@media (prefers-color-scheme: dark) { .kind-why { color:#ff6b5e; } }
.why-pop { max-width:min(22rem, 90vw); border:1px solid var(--line); border-radius:12px;
           padding:.9rem 1rem; background:var(--card); color:var(--fg);
           box-shadow:0 8px 24px rgba(0,0,0,.18); font-size:.88rem; font-weight:400;
           font-variant-numeric:normal; text-align:left; }
.why-pop p { margin:0 0 .3rem; }
.why-pop ul { margin:.3rem 0 .8rem; padding-left:1.1rem; }
.why-pop button { font:inherit; font-size:.8rem; border:1px solid var(--line);
                  border-radius:999px; padding:.2rem .8rem; background:var(--card);
                  color:var(--fg); cursor:pointer; }
/* A card whose kind carries a "?" cannot keep its body inside one <a> - a
   button inside a link is invalid and would navigate. That card's link
   becomes an overlay (a stretched link) with the button above it. */
li.event.has-why { position:relative; }
li.event.has-why .card-body { padding:.55rem .8rem; }
li.event a.card-link { position:absolute; inset:0; padding:0; z-index:0; border-radius:12px; }
li.event.has-why .kind-why, li.event.has-why .tl-3 a { position:relative; z-index:1; }
.checked { color:var(--muted); font-size:.75rem; }
.cancelled { text-decoration: line-through; }
/* A card's <a> is the whole event; the source link sits outside it as a
   sibling, never nested inside another link. */
.source { padding: 0 1rem .8rem; font-size:.8rem; color:var(--muted); }
.source a { color:var(--accent); text-decoration:none; margin-left:.3rem; }
.source a:hover { text-decoration:underline; }
/* Compact timeline row (v0.85.0): up to three stacked lines, never a card
   (Section 12). li.event's own border/padding/gap already fit this; only
   the line-specific typography is new. */
li.event a { padding: .55rem .8rem; }
/* v0.86.3 (Section 3, 13-16): the resolved venue name sits right after
   the region, on line 1 - "[서울] Tango O Nada · 오늘 20:00~23:30 밀롱가".
   Plain inline flow, same as line 1 always was - not flex, no
   `overflow:hidden`/`nowrap` on the line itself, since the date/time/
   type/status tail alone can already be too wide for a narrow phone
   viewport on real production data (confirmed: ~430px of that content
   against a ~310-380px budget) and forcing it onto one non-wrapping row
   would silently clip it. Only the venue name gets a bounded width - the
   exact same `.tl-2-addr` shape line 2's own address already uses
   (v0.85.8) - so an unusually long venue is the one thing that can
   ellipsize (Section 14-15, 20); everything else wraps onto another
   visual line exactly as it always safely could. Weight matches the
   line's own existing bold, no badge/box, no added color - Section
   13/36's own "compact text, existing hierarchy" ask. */
.tl-1 { font-variant-numeric: tabular-nums; font-weight:600; font-size:.92rem; }
.tl-1 .tl-1-venue { display:inline-block; max-width:12em; vertical-align:bottom;
                    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tl-2 { margin:.2rem 0 0; overflow-wrap: anywhere; }
.tl-2 .ev-name { font-weight:600; }
.tl-2 .dj { color:var(--muted); font-weight:400; }
/* v0.85.8 (Section 4-11): the address moved here from line 3, as its own
   trailing segment - existing small/meta styling (same font-size/color
   line 3 has always used), never the event name's own bold/size. Bounded
   and ellipsized rather than flex-shrunk: line 2's title is already
   allowed to wrap onto more than one visual line for a long event name
   (unchanged, pre-existing, deliberately out of this release's scope -
   Section 11), so the address cannot assume it is sharing a single flex
   line with the name/fee before it the way line 3's own items do. */
.tl-2 .tl-2-addr { font-size:.78rem; color:var(--muted); font-weight:400;
                   display:inline-block; max-width:16em; vertical-align:bottom;
                   overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
/* v0.85.8 (Section 12-20): line 3 is 출처/확인시간/지도보기 only now (no
   address) and it is a single row that can never wrap or scroll -
   `overflow:hidden` here is the hard backstop, not a fallback path the
   way v0.85.7's `overflow-x:auto` was. The one part allowed to give way
   is the source's own name (`.src-name`): flex `min-width:0` lets it
   shrink below its own content width so `text-overflow:ellipsis` can
   activate, while 확인시간/지도보기 (`.tl-fixed`) stay flex-shrink:0 and
   are never touched, whatever the source name's real length turns out
   to be. */
.tl-3 { display:flex; align-items:baseline; white-space:nowrap; overflow:hidden;
        padding: .15rem .8rem .6rem; font-size:.78rem; color:var(--muted); }
.tl-3 .src-link { display:inline-flex; align-items:baseline; min-width:0;
                  overflow:hidden; flex-shrink:1; }
.tl-3 .src-name { min-width:0; overflow:hidden; text-overflow:ellipsis;
                  white-space:nowrap; }
.tl-3 .tl-fixed { flex-shrink:0; white-space:nowrap; }
.tl-3 a { color:var(--accent); text-decoration:none; }
.tl-3 a:hover { text-decoration:underline; }
.ext { font-size:.75em; flex-shrink:0; }
/* Weekly calendar (v0.85.0). */
.calendar { margin: 0 0 1.25rem; border:1px solid var(--line); border-radius:12px;
            background:var(--card); overflow:hidden; }
.cal-nav-row { display:flex; align-items:center; justify-content:space-between;
               padding:.6rem .8rem; border-bottom:1px solid var(--line);
               font-size:.8rem; }
.cal-nav-row .cal-nav { color:var(--accent); text-decoration:none; }
.cal-range { color:var(--muted); }
.cal-grid { display:grid; grid-template-columns:repeat(7, 1fr); }
.cal-day { display:flex; flex-direction:column; align-items:center; gap:.15rem;
           padding:.6rem .1rem; text-decoration:none; color:var(--fg);
           border-right:1px solid var(--line); }
.cal-day:last-child { border-right:none; }
.cal-day .cal-wd { font-size:.7rem; color:var(--muted); }
.cal-day .cal-d { font-size:.95rem; font-weight:600; }
.cal-day .cal-n { font-size:.7rem; color:var(--muted); }
.cal-day.today .cal-d { color:var(--accent); }
.cal-day.selected { background:var(--bg); box-shadow:inset 0 -3px 0 var(--accent); }
.cal-day.past { opacity:.55; }
@media (max-width: 30rem) {
  .cal-day { padding:.45rem .05rem; }
  .cal-day .cal-d { font-size:.85rem; }
}
/* Feedback (v0.85.0): three small buttons, event-detail only (Section 55). */
.feedback { margin-top:2rem; display:flex; gap:.5rem; flex-wrap:wrap; align-items:center; }
.feedback .fb-form { margin:0; }
.feedback .fb-btn { border:1px solid var(--line); border-radius:999px; padding:.3rem .85rem;
                    font-size:.8rem; background:var(--card); color:var(--fg); cursor:pointer; }
.feedback .fb-btn:hover { border-color:var(--accent); color:var(--accent); }
.banner { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
          border-radius:8px; padding:.8rem 1rem; margin-bottom:1rem; font-size:.875rem; }
.empty-actions { margin:.75rem 0 0; display:flex; gap:.5rem; flex-wrap:wrap; padding:0; list-style:none; }
.empty-actions a { border:1px solid var(--line); border-radius:999px; padding:.3rem .85rem;
                   text-decoration:none; font-size:.85rem; background:var(--card); color:var(--accent); }
@media (max-width: 30rem) {
  main { padding: 1rem .75rem 3rem; }
  h1 { font-size: 1.2rem; }
  li.event a { padding: .8rem .85rem; }
  .filters .key { width: 100%; }
  dl { grid-template-columns: 1fr; gap:.15rem .5rem; }
  dl dt { margin-top:.5rem; }
}
""".strip()

WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")

TABS = (
    ("today", "오늘"),
    ("tomorrow", "내일"),
    ("weekend", "주말"),
    ("this_week", "이번 주"),
    ("upcoming", "다가오는"),
)


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{E(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


# The three DanceMate promises to show a filter for, whatever the data says
# today. Read from the genre master in practice; this is the floor, so an empty
# or unreachable master never leaves the first screen without its filter.
BASELINE_GENRES = (("TANGO", "Tango"), ("SALSA", "Salsa"), ("SWING", "Swing"))

# Said when a filter is the reason the list is empty. Never followed by
# quietly re-ticking something to make the page look fuller.
EMPTY_FILTERED = "선택한 조건에 해당하는 행사가 없습니다."
EMPTY_TODAY = "오늘 확인된 행사가 없습니다. 수집된 글에서 확인된 것만 보여드립니다."

# v0.88.0: the first screen's tabs. "행사" is the page exactly as it was and
# stays the default (no ?tab= at all); the other four are the directory.
EVENTS_TAB = "events"
DIRECTORY_TABS = (
    (EVENTS_TAB, "행사"),
    ("venues", "장소"),
    ("communities", "동호회"),
    ("sources", "정보원"),
    ("notices", "게시판"),
)
DIRECTORY_TAB_KEYS = frozenset(key for key, _ in DIRECTORY_TABS)
EMPTY_NOTHING_TICKED = "선택한 춤 종류가 없습니다. 춤 종류를 하나 이상 골라 주세요."


def _next_actions(*, when: str | None, region: str | None,
                  genre_query: dict[str, str]) -> str:
    """What to try next when a list comes back empty (Section 27).

    "행사가 없습니다" alone leaves a reader to guess what else to try; this
    is always at least one real place to look next, built from the same
    filters already carrying through the rest of the page - widening the
    dates or the region, never silently dropping what the reader picked.
    """
    from urllib.parse import urlencode

    links = []
    for candidate, label in (("tomorrow", "내일 보기"), ("this_week", "이번 주 보기")):
        if candidate == when:
            continue
        params = {"when": candidate, **genre_query}
        if region:
            params["region"] = region
        links.append(f'<a href="/events?{urlencode(params)}">{label}</a>')
    if region:
        params = {"when": when or events_api.WHEN_TODAY, **genre_query}
        links.append(f'<a href="/events?{urlencode(params)}">지역 전체 보기</a>')
    if not links:
        return ""
    return '<ul class="empty-actions">' + "".join(f"<li>{link}</li>" for link in links) + "</ul>"


def _is_narrowed(options: list[dict[str, str]], selected: list[str]) -> bool:
    """Has the reader actually restricted anything?"""
    return set(selected) < {o["code"] for o in options}


def _split_genres(values: list[str] | None) -> list[str] | None:
    """Accept ?genres=TANGO&genres=SALSA and ?genres=TANGO,SALSA alike.

    None means the reader said nothing about genre. An empty list means they
    said "none of them", which is different and must survive as such.
    """
    if values is None:
        return None
    codes: list[str] = []
    for value in values:
        for part in (value or "").split(","):
            code = part.strip().upper()
            if code and code not in codes:
                codes.append(code)
    return codes


def _is_enabled(row: dict[str, Any]) -> bool:
    """Is this master row live? Read from the row's own state, never its name.

    v0.86.8 (Section 2): a genre is hidden because the master says it is
    disabled, and for no other reason - nothing here, or anywhere else on
    the reader's side, may ask "is this the salsa one?". A row that does not
    carry the flag at all is treated as enabled: an unknown state is not a
    reason to take a working filter off the page.
    """
    return bool(row.get("enabled", True))


def _baseline_options() -> list[dict[str, str]]:
    """The floor, used only when the master cannot be read at all."""
    return [{"code": code, "label": label} for code, label in BASELINE_GENRES]


def _enabled_genre_options(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The chips, built from master rows: enabled ones only, in a fixed order.

    A genre with no events today still gets a chip - "is there any swing on?"
    is a question the page should answer with an empty list rather than by
    removing the question. A *disabled* genre is a different case entirely
    (v0.86.8, Section 2): it is not a question this product is answering at
    all right now, so it is left out of the list rather than shown greyed
    out, which would only invite a click that goes nowhere.
    """
    options: list[dict[str, str]] = []
    for row in rows or []:
        if not _is_enabled(row):
            continue
        code = (row.get("code") or "").strip().upper()
        if code and code not in {o["code"] for o in options}:
            options.append({"code": code, "label": row.get("name") or code.title()})
    order = {code: n for n, (code, _) in enumerate(BASELINE_GENRES)}
    options.sort(key=lambda o: (order.get(o["code"], len(order)), o["label"]))
    return options


def _genre_options(con) -> list[dict[str, str]]:
    """Every genre a reader may filter by: the enabled ones in the master.

    The master is the only authority. When it can be read, what it says goes -
    including "nothing is enabled", which is a real answer and leaves the page
    without a style filter rather than inventing one. The baseline is a floor
    for an *unreachable* master only, so a database hiccup never silently
    removes the filter from the first screen.
    """
    from . import master_data

    try:
        rows = master_data.list_genres(con)
    except Exception:  # noqa: BLE001 - the filter is not worth a 500
        return _baseline_options()
    return _enabled_genre_options(rows)


def _region_options(con, counted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every place with something to show, under the filters on screen right now.

    v0.85.7 (Section 24-30): built from the region master so a real region is
    never mis-spelled or mis-ordered, but a chip only survives into the
    returned list when its count under the *current* window/genre selection
    is at least 1 - "청주 0" is not a place to go, it is a dead end with a
    number attached, and Section 24 says to just not offer it. "전체" (All)
    is unaffected: it is injected separately by ``_region_chips()`` and never
    passes through this list at all, so it stays visible regardless of any
    region's individual count.
    """
    from . import master_data

    counts = {row["value"]: row.get("events") or 0 for row in counted}
    options: list[dict[str, Any]] = []
    try:
        rows = master_data.list_regions(con, enabled_only=True)
    except Exception:  # noqa: BLE001 - the filter is not worth a 500
        rows = []
    for row in rows:
        if not row.get("city"):
            continue
        name = row.get("name")
        if name and counts.get(name, 0) > 0:
            options.append({"value": name, "label": name, "events": counts[name]})
    if not options:
        # list_regions() itself failed - counted is already positive-count-only
        # (it comes straight from a GROUP BY over actual matching events, so a
        # region with zero matches was never a row in it to begin with).
        options = list(counted)
    options.sort(key=lambda o: (-(o["events"] or 0), o["label"]))
    return options


def _shows_selector(options: list[dict[str, str]]) -> bool:
    """Is there a choice to offer? (v0.86.8, Section 3)

    Two or more enabled genres is a question. One is not - a control whose
    only option is already the answer is furniture, and it is the whole width
    of the first screen's most valuable row. Zero is not a question either.
    """
    return len(options) > 1


def _selected_genres(options: list[dict[str, str]], asked: list[str] | None,
                     declared: bool) -> list[str]:
    """Which chips are ticked. Everything, until the reader says otherwise.

    v0.86.8 (Section 3): what a link asks for is checked against what the
    master currently enables, so a shared or bookmarked URL naming a genre
    that has since been disabled (or never existed) cannot leave a reader
    looking at a filtered-to-nothing page they have no control to undo:

    * with no selector on screen, the enabled genres are simply applied -
      there is nothing for the reader to change, so a stale parameter is
      corrected rather than obeyed;
    * with the selector on screen, unknown codes are dropped, and an ask
      that survives none of them falls back to everything;
    * ticking every box off by hand stays exactly what it was - an answer,
      not a mistake to be corrected.
    """
    codes = [o["code"] for o in options]
    if asked is None and not declared:
        return list(codes)
    picked = [code for code in (asked or []) if code in codes]
    if not _shows_selector(options):
        # One enabled genre (or none): that is the current genre, whatever
        # the query string still says.
        return list(codes)
    if asked and not picked:
        return list(codes)
    return picked


def _genre_constraint(options: list[dict[str, str]], selected: list[str]) -> list[str] | None:
    """What to pass to search: None when the selection covers everything.

    With every box ticked the reader has asked for all of it, and an event
    whose genre we could not read is still part of all of it. Constraining on
    the full list would drop exactly those, which is not what ticking every box
    means.
    """
    if set(selected) >= {o["code"] for o in options}:
        return None
    return selected


def _facets(con, when: str, genre_codes: "list[str] | None" = None
           ) -> dict[str, list[dict[str, Any]]]:
    """The genres and regions that have events *in the window being shown*.

    Counted over the same dates the page lists, because a chip is a promise. A
    "Swing 1" chip beside a page that returns nothing is the same small lie as
    offering an empty filter: it says events of that kind are in here when they
    are not. ``genre_codes`` (v0.85.7, Section 25) scopes the *region* counts
    to the currently-ticked genre chips - the genre chips themselves always
    count across every genre, so a reader can still see what else exists.
    """
    return _facets_window(con, events_api.window(when), genre_codes)


def _facets_for_date(con, day_iso: str, genre_codes: "list[str] | None" = None
                     ) -> dict[str, list[dict[str, Any]]]:
    """Same promise as ``_facets()``, for a single calendar-selected day
    (v0.85.0) rather than a ``when`` keyword - a past day included, since
    _facets_window's own "no window" branch (today onward) would otherwise
    wrongly hide every filter chip on a day already gone by."""
    from datetime import date as date_type

    day = date_type.fromisoformat(day_iso)
    return _facets_window(con, (day, day), genre_codes)


def _facets_window(con, window: tuple | None,
                   genre_codes: "list[str] | None" = None
                   ) -> dict[str, list[dict[str, Any]]]:
    where = [events_api._VISIBLE, "e.engine_status <> 'CANCELLED'"]
    params: list[Any] = []
    if window:
        where.append("e.event_date BETWEEN %s AND %s")
        params.extend(window)
    else:
        where.append("e.event_date >= %s")
        params.append(events_api.today())
    clause = " AND ".join(where)

    # Only the region query is scoped by the current genre selection - the
    # genre chips themselves must keep counting every genre regardless of
    # which ones are ticked, or a reader could never discover/re-select one
    # they just unchecked.
    region_join = "JOIN genres g ON g.genre_id = e.genre_id " if genre_codes else ""
    region_where = clause + (" AND g.code = ANY(%s)" if genre_codes else "")
    region_params = list(params) + ([genre_codes] if genre_codes else [])

    with con.cursor() as cur:
        cur.execute(
            "SELECT g.code AS value, g.name AS label, count(*) AS events "
            "FROM events e JOIN genres g ON g.genre_id = e.genre_id "
            f"WHERE {clause} GROUP BY 1, 2 ORDER BY events DESC",
            tuple(params),
        )
        genres = [dict(zip([c.name for c in cur.description], r)) for r in cur.fetchall()]
        cur.execute(
            "SELECT r.name AS value, r.name AS label, count(*) AS events "
            "FROM events e JOIN regions r ON r.region_id = e.region_id "
            f"{region_join}"
            # Only places, not the country-level row. "South Korea" as a filter
            # option next to Seoul and Busan tells a reader nothing about where
            # to go, and offering it makes the other two look like subsets.
            f"WHERE {region_where} AND r.city IS NOT NULL "
            "GROUP BY 1, 2 ORDER BY events DESC",
            tuple(region_params),
        )
        regions = [dict(zip([c.name for c in cur.description], r)) for r in cur.fetchall()]

    unresolved = _unresolved_region_counts(con, clause, params, genre_codes)
    by_label = {row["label"]: row for row in regions}
    for label, extra in unresolved.items():
        if label in by_label:
            by_label[label]["events"] += extra
        else:
            row = {"value": label, "label": label, "events": extra}
            regions.append(row)
            by_label[label] = row
    regions.sort(key=lambda r: -(r["events"] or 0))

    return {"genres": genres, "regions": regions,
            "region_options": _region_options(con, regions)}


def _unresolved_region_counts(con, clause: str, params: list,
                              genre_codes: "list[str] | None" = None) -> dict[str, int]:
    """Regions an unresolved venue's raw text would still earn, per
    venue_resolution.guess_region_label() - Section 22 of the v0.82.4 task:
    a filter chip's count is a promise, and "청주: 0" while real Cheongju
    milongas sit unresolved would be the same small lie the genre docstring
    above already refuses to tell. Genre-scoped the same way the resolved
    region count is (v0.85.7 Section 25), so the two halves of one chip's
    number never disagree about which genre they are counting.
    """
    counts: dict[str, int] = {}
    labels = sorted({label for label in venue_resolution.CURATED_CITY_HINTS.values()})
    genre_join = "JOIN genres g ON g.genre_id = e.genre_id " if genre_codes else ""
    genre_where = " AND g.code = ANY(%s)" if genre_codes else ""
    with con.cursor() as cur:
        for label in labels:
            terms = venue_resolution.terms_for_label(label)
            if not terms:
                continue
            ors = " OR ".join(["e.venue_text ILIKE %s"] * len(terms))
            query_params = (tuple(params) + tuple(f"%{t}%" for t in terms)
                            + ((genre_codes,) if genre_codes else ()))
            cur.execute(
                f"SELECT count(*) FROM events e {genre_join}WHERE {clause} "
                f"AND e.region_id IS NULL AND ({ors}){genre_where}",
                query_params,
            )
            n = cur.fetchone()[0]
            if n:
                counts[label] = counts.get(label, 0) + n
    return counts


def _genre_query(selected: list[str], options: list[dict[str, str]]) -> dict[str, str]:
    """The genre half of a link, canonical and comma-joined so it is shareable.

    Nothing at all when everything is selected: the default should not clutter
    every link on the page, and an absent parameter already means "all".
    """
    if set(selected) >= {o["code"] for o in options}:
        return {}
    return {"genres": ",".join(selected), "genres_set": "1"}


def _genre_filter(action: str, when: str | None, region: str | None,
                  options: list[dict[str, str]], selected: list[str], *,
                  tab: str | None = None) -> str:
    """Dance styles, every enabled one, always showing which are on.

    Real checkboxes rather than styled links: the checked state is carried by
    the control itself, so it survives a reader who cannot see the colour and
    it answers to the keyboard without anything being added. The submit button
    is what makes it work with no JavaScript at all; the script below hides it
    and submits on change, which is what "immediately" means for everyone else.
    """
    if not _shows_selector(options):
        # v0.86.8 (Section 3): one enabled genre is not a choice, and zero
        # is not one either. The genre still applies - _selected_genres()
        # has already made it the current one - it just is not asked about.
        return ""
    chosen = set(selected)
    boxes = []
    for option in options:
        mark = " checked" if option["code"] in chosen else ""
        boxes.append(
            f'<label class="chip"><input type="checkbox" name="genres" '
            f'value="{E(option["code"])}"{mark}> {E(option["label"])}</label>'
        )
    hidden = '<input type="hidden" name="genres_set" value="1">'
    if when:
        hidden += f'<input type="hidden" name="when" value="{E(when)}">'
    if region:
        hidden += f'<input type="hidden" name="region" value="{E(region)}">'
    if tab:
        # v0.88.0: a genre change on a directory tab stays on that tab.
        hidden += f'<input type="hidden" name="tab" value="{E(tab)}">'
    return (
        f'<form class="row genres" method="get" action="{E(action)}">'
        f'{hidden}<span class="key">춤 종류</span>'
        + "".join(boxes)
        + '<button class="apply">적용</button></form>'
    )


def _region_chips(action: str, when: str | None, rows: list[dict[str, Any]],
                  chosen: str | None, genre_query: dict[str, str]) -> str:
    """Where. Only places that have something, and never the country row."""
    from urllib.parse import urlencode

    if not rows:
        return ""
    links = []
    for row in [{"value": None, "label": "전체"}] + rows:
        params: dict[str, str] = {}
        if when:
            params["when"] = when
        params.update(genre_query)
        if row["value"]:
            params["region"] = row["value"]
        mark = ' aria-current="true"' if (row["value"] or None) == chosen else ""
        count = f' {row["events"]}' if row.get("events") else ""
        query = f"?{urlencode(params)}" if params else ""
        links.append(f'<a href="{E(action)}{query}"{mark}>{E(row["label"])}{count}</a>')
    return ('<div class="row"><span class="key">지역</span>' + "".join(links) + "</div>")


AUTO_SUBMIT = (
    "<script>(function(){var f=document.querySelector('form.genres');"
    "if(!f)return;f.classList.add('auto');"
    "f.addEventListener('change',function(){f.submit();});})();</script>"
)


def _filter_bar(action: str, when: str | None, facets: dict[str, list[dict[str, Any]]],
                options: list[dict[str, str]], selected: list[str],
                region: str | None) -> str:
    """Dance style first, then where. Both above the list, both without scrolling.

    The style row is only here when there is more than one enabled genre to
    choose between (v0.86.8, Section 3); the region row, the counts and every
    link on the page carry on unchanged either way.
    """
    genre_form = _genre_filter(action, when, region, options, selected)
    return (
        '<div class="filters">'
        + genre_form
        + _region_chips(action, when, facets["region_options"], region,
                        _genre_query(selected, options))
        + "</div>"
        + (AUTO_SUBMIT if genre_form else "")
    )


def _nav(current: str, genre: str | None = None, region: str | None = None,
         genre_query: dict[str, str] | None = None) -> str:
    from urllib.parse import urlencode

    links = []
    for key, label in TABS:
        params = {"when": key}
        if genre:
            params["genre"] = genre
        params.update(genre_query or {})
        if region:
            params["region"] = region
        mark = ' aria-current="page"' if key == current else ""
        links.append(f'<a href="/events?{urlencode(params)}"{mark}>{E(label)}</a>')
    return "<nav>" + "".join(links) + "</nav>"


def _when_line(event: dict[str, Any]) -> str:
    from datetime import date as date_type

    day = event.get("date")
    label = ""
    if day:
        parsed = date_type.fromisoformat(day)
        label = f"{parsed.month}/{parsed.day}({WEEKDAYS[parsed.weekday()]})"
    start, end = event.get("start_time"), event.get("end_time")
    if start and end:
        clock = f"{start}–{end}" + ("<sup>+1</sup>" if event.get("ends_next_day") else "")
    elif start:
        # v0.86.6 (Section 5-9, 21-24): a post that names a start but never
        # says when the night ends is not the same fact as one that names
        # neither - DanceMate does not guess an end time (no default
        # duration, never 21:00~00:00 or 21:00~23:00 invented), so the gap
        # itself is shown, plainly, rather than silently dropped (a bare
        # "21:00" reads as if that were the whole answer).
        clock = f'{start}–<span class="unknown">미정</span>'
    # v0.86.4 (Section 4-6): a bare, am/pm-ambiguous clock (5시30 is very
    # likely half past five in the evening, but the post does not say so)
    # used to append its own "시간 미확인" tag right next to the real value
    # it was flagging - self-contradictory the moment a reader is shown a
    # time and told in the same breath that it is unknown. The reading
    # stands, unflagged here; the original is a click away regardless.
    if not start:
        # Not "TBD": we simply do not know, and the post is linked so a reader
        # can check for themselves.
        clock = '<span class="unknown">시간 미확인</span>'
    return f'<span class="when">{E(label)} {clock}</span>'


def _region_line(event: dict[str, Any]) -> str:
    """지역 미확인 rather than a blank field - Section 18 of the v0.82.4
    task. A region read off the raw venue string rather than a resolved
    venue (region_confirmed is False) is tagged the same way an unresolved
    venue name already is, so a reader can tell the two apart."""
    region = event.get("region")
    if not region:
        return '<span class="unknown">지역 미확인</span>'
    if not event.get("region_confirmed"):
        return f'{E(region)} <span class="tag">미확인</span>'
    return E(region)


def _venue_line(event: dict[str, Any]) -> str:
    venue = event.get("venue") or {}
    name = venue.get("name")
    region = event.get("region")
    suffix = f" · {E(region)}" if region else " · 지역 미확인"
    if not name:
        return '<span class="unknown">장소 미확인</span>' + suffix
    if venue.get("status") == "UNRESOLVED":
        # We read this string off the post and have not confirmed the place.
        return f'{E(name)} <span class="tag">미확인</span>' + suffix
    return E(name) + suffix


def _fee_line(event: dict[str, Any]) -> str:
    # A conditional or multi-option fee (v0.85.9, Section 13) already spells
    # out everything a plain number could - "8,000원 (22시 이후 5,000원)",
    # "예매 15,000원 · 현매 20,000원" - so it wins over `fee` outright rather
    # than the two being merged into something neither source actually said.
    display = event.get("fee_display_text")
    if display:
        return E(display)
    fee = event.get("fee")
    if fee is None:
        return '<span class="unknown">요금 미확인</span>'
    if fee == 0:
        # A post that names a fee of 0 said so on purpose - rendering "0원"
        # would read as a typo rather than what a dancer actually wants to
        # know: this one costs nothing.
        return "무료"
    return f"{fee:,}원"


def _in_progress(event: dict[str, Any], *, now: "datetime | None" = None) -> bool:
    """True only when the post gave us a real start AND end time and the
    current moment (Asia/Seoul) genuinely falls between them.

    Section 23: shown only when we can say so from real evidence - a bare
    start time with no end is exactly the case events_api already refuses to
    qualify (``time_confirmed``), and guessing an end here would be the same
    mistake in a new place.
    """
    from datetime import date as date_type, datetime as datetime_type, time as time_type
    from datetime import timedelta

    day = event.get("date")
    start, end = event.get("start_time"), event.get("end_time")
    if not day or not start or not end:
        return False
    moment = now or datetime_type.now(events_api.SEOUL)
    event_date = date_type.fromisoformat(day)
    start_at = datetime_type.combine(event_date, time_type.fromisoformat(start),
                                     tzinfo=events_api.SEOUL)
    end_date = event_date + timedelta(days=1) if event.get("ends_next_day") else event_date
    end_at = datetime_type.combine(end_date, time_type.fromisoformat(end),
                                   tzinfo=events_api.SEOUL)
    return start_at <= moment <= end_at


def _status_line(event: dict[str, Any], *, with_type: bool = True,
                 now: "datetime | None" = None) -> str:
    """What we know about this event, in words a reader owes nobody to decode.

    The engine says VERIFIED, POSSIBLE, or (not yet seen live, but supported)
    CONFLICT/UPDATED/COMPLETED/EXPECTED/UNKNOWN. None of them belong on a page
    someone reads on the way out the door as-is, and VERIFIED does not mean
    "true" anyway -- it means the evidence gate passed (spelled out in its
    ``title`` attribute, Section 12, rather than a paragraph nobody asked for).

    CONFLICT gets its own tone rather than sharing POSSIBLE's plain badge --
    Section 14 asks that a reader recognise it at a glance, and a colour alone
    would fail anyone who cannot see it (Section 43), so the text itself
    ("정보 충돌") already carries the meaning and the colour is additional,
    not the only signal.

    ``with_type`` drops the kind-of-event badge for callers that already show
    it in a field of its own; repeating it reads as two different facts.
    """
    parts = []
    if with_type and event.get("event_type_label"):
        parts.append(f'<span class="status">{E(event["event_type_label"])}</span>')
    if not event.get("cancelled") and _in_progress(event, now=now):
        parts.append('<span class="status ok">진행 중</span>')
    if event.get("cancelled"):
        parts.append('<span class="status">취소</span>')
    elif event.get("status_label"):
        status = event.get("status")
        tone = " ok" if status == "VERIFIED" else " warn" if status == "CONFLICT" else ""
        title = (f' title="{E(events_api.VERIFIED_EXPLANATION)}"'
                  if status == "VERIFIED" else "")
        parts.append(f'<span class="status{tone}"{title}>{E(event["status_label"])}</span>')
    if event.get("human_reviewed"):
        parts.append('<span class="status">관리자 확인</span>')
    return "".join(parts)


def _checked_line(event: dict[str, Any], *, now: "datetime | None" = None) -> str:
    """When we last read the post behind this.

    Not a freshness score. The timestamp, and a nudge when an event is close
    and what we know about it is not.

    ``now`` lets a test fix "the current moment" - real wall-clock time in
    two independent places (here and in events_api.today()) can otherwise
    disagree right at the Seoul midnight boundary a "N시간 전" timestamp
    happens to straddle, for a reason that has nothing to do with what this
    function actually computes.
    """
    from datetime import datetime, timezone

    stamp = event.get("last_checked")
    if not stamp:
        return ""
    try:
        seen = datetime.fromisoformat(stamp)
    except ValueError:
        return ""
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    local = seen.astimezone(events_api.SEOUL)
    today = events_api.today(now)
    age = (now - seen).total_seconds()
    # "2시간 전" reads faster than a timestamp for anything recent; a date is
    # clearer once it is no longer today.
    if age < 3600:
        when = f"{max(1, int(age // 60))}분 전"
    elif local.date() == today:
        when = f"{int(age // 3600)}시간 전"
    else:
        when = f"{local.month}/{local.day} {local:%H:%M}"
    stale = age > 24 * 3600
    soon = event.get("date") and event["date"] <= today.isoformat()
    tail = " · 재확인 필요" if (stale and soon) else ""
    return f'<span class="checked">{E(when)} 확인{E(tail)}</span>'


def _is_unknown_heavy(event: dict[str, Any]) -> bool:
    """True when time, venue, and fee are all unknown at once.

    Section 28: a card that carries a real date but nothing else must not
    read with the same weight as one a poster actually filled in - three
    "미확인" tags already say that on their own, but a reader skimming past
    (rather than reading each field) deserves the same warning at a glance.
    """
    no_time = not event.get("start_time")
    no_venue = not (event.get("venue") or {}).get("name")
    no_fee = event.get("fee") is None
    return no_time and no_venue and no_fee


def _is_past(event: dict[str, Any], *, now: "datetime | None" = None) -> bool:
    """Strictly by date, never by the engine's own status.

    Section 28/36: production has only ever written POSSIBLE/VERIFIED - an
    engine_status of COMPLETED is a real, supported value that has simply
    never been set by anything upstream yet. Whether a night has already
    happened is knowable today regardless: it is whatever the calendar
    already says, compared against the same Asia/Seoul "today" every other
    date computation on this page already uses.
    """
    day = event.get("date")
    if not day:
        return False
    from datetime import date as date_type

    return date_type.fromisoformat(day) < events_api.today(now)


# --- compact timeline row (v0.85.0) -----------------------------------------
#
# Up to three stacked text lines, never a card (Section 12): region+date+
# time+type, then name+DJ+fee, then source+confirmation-time - the third
# line only when there is something real to put on it (a source link or a
# confirmation timestamp; Section 29's "thin event" still gets exactly two
# real lines, never a blank third one). The older, larger _event_item() this
# replaces is gone outright, not kept behind a flag - Section 12 is explicit
# that this never goes back to a big card.

def _human_date(day_iso: str, *, now: "datetime | None" = None) -> str:
    """오늘 / 내일 / 9/12(토) - Section 15, person-first over machine-first."""
    from datetime import date as date_type, timedelta as timedelta_type

    day = date_type.fromisoformat(day_iso)
    today = events_api.today(now)
    if day == today:
        return "오늘"
    if day == today + timedelta_type(days=1):
        return "내일"
    return f"{day.month}/{day.day}({WEEKDAYS[day.weekday()]})"


def _timeline_clock(event: dict[str, Any]) -> str:
    """20:00~23:30 when the post gave an end time, 20:00~미정 when it gave a
    start and nothing else - never a blank (Section 16), never a bare
    start that reads as if that were the whole answer. 시간 미확인 only
    when there is no reading at all.

    v0.85.9 (Section 8-10): the Timeline used to show only `start_time`,
    dropping an end time the extractor already had (the detail page's own
    `_when_line()` has shown it for longer, with an en dash - `~` here
    instead, matching this section's own exact target render).

    v0.86.4 (Section 4-6): a time the post left ambiguous (no am/pm marker)
    used to append its own "시간 미확인" tag right after a real clock value -
    "20:30~23:30 시간 미확인", self-contradictory the moment a reader has
    just been shown the time and is then told it is unknown. That ambiguity
    is real and still worth surfacing, but never as text that contradicts
    the value sitting right next to it - the clock is shown as read, and
    the original post is a click away (v0.87.0: the "?" beside the kind now
    speaks only to the kind, never to the clock).

    v0.86.6 (Section 5-9, 21-24): a start with no end is not the same fact
    as no time at all - DanceMate never guesses a duration (no default
    length, never 21:00~00:00 or 21:00~23:00 invented; a source that truly
    gives neither field stays end_time=NULL in the database, display-only
    here). Structured on `start`/`end` themselves, not a string patched
    after the fact, so the no-end case can never silently collide with a
    real end time the same way the old bare-`start` fallback could read as
    one.
    """
    start = event.get("start_time")
    if not start:
        return '<span class="unknown">시간 미확인</span>'
    end = event.get("end_time")
    if not end:
        clock = f'{start}~<span class="unknown">미정</span>'
    elif event.get("ends_next_day"):
        clock = f"{start}~{end}<sup>+1</sup>"
    else:
        clock = f"{start}~{end}"
    return clock


def _timeline_region(event: dict[str, Any]) -> str:
    """[서울] / [지역 미확인] - always the line's own first token (Section 14)."""
    region = event.get("region")
    if not region:
        return '<span class="unknown">[지역 미확인]</span>'
    tag = " <span class=\"tag\">미확인</span>" if not event.get("region_confirmed") else ""
    return f"[{E(region)}]{tag}"


def _timeline_badges(event: dict[str, Any], *, now: "datetime | None" = None) -> str:
    """Small, inline status signals appended to line 1 - never a line of
    their own (Section 28). CANCELLED never reaches here at all (excluded
    from the default upcoming list before the page ever sees it); a past
    date reads COMPLETED regardless of what the engine's own status says
    (_is_past's own docstring explains why); CONFLICT gets its warn tone
    unchanged from the previous card design.

    v0.86.4 (Section 7-11): the "확인 필요" text badge (POSSIBLE/UNKNOWN, and
    events_api.present()'s own blank-status fallback - all three share that
    exact label) is gone from here outright, replaced by the "?" indicator
    right after the event type (retired in v0.87.0: that "?" is now the
    kind's own - see `_event_kind()`).
    VERIFIED's "확인됨" and CONFLICT's "정보 충돌" are unrelated status
    badges, not the removed phrase, and are unchanged.
    """
    if _is_past(event, now=now):
        return f' <span class="status">{E(events_api.STATUS_LABELS[events_api.COMPLETED])}</span>'
    if not event.get("cancelled") and _in_progress(event, now=now):
        return ' <span class="status ok">진행 중</span>'
    status = event.get("status")
    label = event.get("status_label")
    if not label or label == events_api.STATUS_LABELS["POSSIBLE"]:
        return ""
    tone = " ok" if status == "VERIFIED" else " warn" if status == "CONFLICT" else ""
    title = (f' title="{E(events_api.VERIFIED_EXPLANATION)}"'
             if status == "VERIFIED" else "")
    return f'<span class="status{tone}"{title}>{E(label)}</span>'


# v0.87.0: the "?" beside an event's kind is about the kind alone. v0.86.4's
# "?" meant an unverified post (engine status POSSIBLE/EXPECTED/CONFLICT/
# UNKNOWN, switched in Settings); it read as doubt about the kind - "밀롱가?"
# on a plain milonga - and is retired. VERIFIED/CONFLICT keep their badges.


def _enabled_terms(con) -> "list[dict[str, Any]] | None":
    """The Settings terminology, once per request. None when it cannot be
    read: the kind then shows exactly as it did before v0.87.0, with no "?"."""
    from . import event_terms

    try:
        return event_terms.list_terms(con, enabled_only=True)
    except Exception:  # noqa: BLE001 - a page is worth more than a label
        return None


def _event_kind(event: dict[str, Any],
                terms: "list[dict[str, Any]] | None") -> "dict[str, Any] | None":
    """How this event's kind is shown, settled from its own title
    (runtime.event_terms.classify_kind). None when no terminology was given -
    the caller then shows the plain type label, as before."""
    if terms is None:
        return None
    from . import event_terms

    return event_terms.classify_kind(
        event.get("name"), event_terms.terms_for_genre_code(terms, event.get("genre")),
        event_type=event.get("event_type"), stored_formats=event.get("event_formats"))


def _kind_why(kind: dict[str, Any], element_id: str) -> str:
    """The "?" and what it opens: the reasons the kind decision actually used."""
    from . import event_terms

    items = "".join(f"<li>{E(line)}</li>" for line in event_terms.kind_reason_lines(kind))
    return (
        f'<button type="button" class="kind-why" popovertarget="{E(element_id)}" '
        'aria-label="행사 유형 판정 이유 보기" title="행사 유형 판정 이유 보기">?</button>'
        f'<div class="why-pop" id="{E(element_id)}" popover role="dialog" '
        'aria-label="행사 유형 판정 이유">'
        "<p><strong>행사 유형을 확정하지 못했습니다.</strong></p>"
        f"<p>이유:</p><ul>{items}</ul>"
        f'<button type="button" popovertarget="{E(element_id)}" '
        'popovertargetaction="hide">닫기</button></div>'
    )


def _kind_html(event: dict[str, Any], kind: "dict[str, Any] | None", element_id: str) -> str:
    """The kind segment: the word the title used, and a "?" only when unsettled."""
    if kind is None:
        label = event.get("event_type_label") or ""
        return E(label) if label else ""
    html = f'<span class="kind">{E(kind["display"])}</span>' if kind.get("display") else ""
    if kind.get("uncertain"):
        html += " " + _kind_why(kind, element_id)
    return html


def _timeline_line1_venue_name(event: dict[str, Any]) -> str | None:
    """The resolved Venue Master's own canonical name, or None - v0.86.3
    Section 3-6: only a RESOLVED venue shows at all, and only its Master
    name (never an alias, never raw unresolved source text, never
    guessed). Escaping/wrapping is the caller's job."""
    venue = event.get("venue") or {}
    if venue.get("status") != "RESOLVED":
        return None
    return (venue.get("name") or "").strip() or None


def _timeline_line1(event: dict[str, Any], *, now: "datetime | None" = None,
                    terms: "list[dict[str, Any]] | None" = None,
                    kind: "dict[str, Any] | None" = None) -> str:
    """[지역] Venue · 날짜 시간 종류 - v0.86.3 moved the resolved venue name
    here from line 2 (Section 1-7; was 행사명 앞, v0.86.2's own Section
    1-7). No venue at all keeps the exact pre-v0.86.3 form, "[지역] 날짜
    시간 종류", with no floating separator (Section 4).

    Plain inline flow, not flex: an early version of this made the whole
    line a single-line flex row with `overflow:hidden`, which broke on
    real production data the moment the *non-venue* tail alone (date +
    time + type + the status badge, all `flex-shrink:0`) was already too
    wide for a narrow phone viewport - Mi Vida tango studio and 여러 real
    events measured ~430px of never-shrinking content against a
    ~310-380px budget, which `overflow:hidden` would have silently
    clipped rather than wrapped. This instead mirrors line 2's own
    already-proven `.tl-2-addr` pattern (v0.85.8): only the venue name
    itself gets a bounded `max-width` + `text-overflow:ellipsis`
    (Section 14-15, 20); everything else stays normal inline text that
    wraps onto another visual line exactly as it always safely could,
    never overflowing the page horizontally.

    v0.87.0: the kind is the word the title itself uses when a Settings term
    matched ("쁘락", "Pronga"), else the stored formats, else the engine's
    type label (`_event_kind()`); a "?" follows it only when that could not
    be settled, as a button opening the actual reasons. Without terminology
    (`terms` and `kind` both None) the plain type label shows, as before.
    """
    if kind is None and terms is not None:
        kind = _event_kind(event, terms)
    day = event.get("date")
    date_label = _human_date(day, now=now) if day else ""
    venue_name = _timeline_line1_venue_name(event)
    venue_html = ""
    if venue_name:
        escaped = E(venue_name)
        venue_html = (f'<span class="tl-1-venue" title="{escaped}" '
                      f'aria-label="{escaped}">{escaped}</span> ·')
    type_html = _kind_html(event, kind, f"kind-why-{event.get('id')}")
    parts = [_timeline_region(event), venue_html, E(date_label), _timeline_clock(event),
             type_html]
    return (f'<div class="tl-1">' + " ".join(p for p in parts if p)
            + _timeline_badges(event, now=now) + "</div>")


def _fee_text(event: dict[str, Any]) -> str:
    """입장료: 무료 / 20,000원 / 미확인 - Section 21's exact wording.

    A conditional or multi-option fee (v0.85.9, Section 13) shows its own
    full text instead - "입장료: 8,000원 (22시 이후 5,000원)" - never reduced
    to just the base number, and never left "미확인" when a real price (with
    a real condition) is known.
    """
    display = event.get("fee_display_text")
    if display:
        return f"입장료: {E(display)}"
    fee = event.get("fee")
    if fee is None:
        return '입장료: <span class="unknown">미확인</span>'
    if fee == 0:
        return "입장료: 무료"
    return f"입장료: {fee:,}원"


# v0.85.3: a raw post title can already spell out "(DJ : 유진)" as free
# text, while the engine *also* extracts "유진" into the structured `dj`
# field it has always had - both true, both independently rendered, and
# the reader sees the same name twice. Found live in production
# (event_id 221245, SRC-D-003). Only the DISPLAY badge is skipped when it
# would repeat the title verbatim; the title text and the stored `dj`
# field are never touched (Section 31's own requirement). Normalization
# is limited to label spacing/case/colon/parens (Section 32) - no fuzzy
# name matching, so a genuinely different DJ named in the title is never
# mistaken for a match (Section 33) and stays visible as a real conflict
# signal rather than being silently hidden.
_DJ_LABEL_RE = re.compile(r"DJ\s*[:：]?\s*", re.IGNORECASE)
_DJ_NAME_STOP = re.compile(r"[)）,、·]")


def _strip_trailing_decoration(value: str) -> str:
    """Drop trailing emoji/ornaments a decorated title puts right up
    against a name, e.g. "...DJ네로\U0001f389\U0001f389" - the same
    unicodedata-category approach extraction_rules._strip_decoration()
    already uses on the engine side (Symbol/Punctuation/Separator/Mark/
    Other), so a name followed by decoration reads as that name, not as
    the name-plus-decoration string _DJ_NAME_STOP's plain stop-character
    list never anticipated every real emoji for."""
    value = value.strip()
    while value and unicodedata.category(value[-1])[0] in ("S", "P", "Z", "M", "C"):
        value = value[:-1]
    return value.strip()


def _title_already_announces_dj(title: str, dj: str) -> bool:
    dj = (dj or "").strip()
    if not title or not dj:
        return False
    for match in _DJ_LABEL_RE.finditer(title):
        rest = title[match.end():]
        name = _DJ_NAME_STOP.split(rest, maxsplit=1)[0].strip()
        name = _strip_trailing_decoration(name)
        if name == dj:
            return True
    return False


def _timeline_line2(event: dict[str, Any]) -> str:
    """행사명 (DJ) · 입장료 · 주소 - v0.86.3 Section 1-7 moved the resolved
    venue name to line 1 (after the region), so line 2 goes back to what
    v0.86.1 had: event title first, never a venue prefix here again
    (v0.86.2's own brief home for it). The DJ parenthetical is entirely
    absent, not "DJ 미확인", when there is none (Section 20 of v0.85.8,
    unchanged).

    The address (already display-compacted by _compact_address(), never
    the raw value) is its own trailing span in the existing small/meta
    styling (Section 6-7 of v0.85.8) - never the same size/weight as the
    event name. It is what ellipsizes first if the line runs long, and it
    is omitted entirely rather than shown as "주소 미확인" when there is
    none (Section 25-26 of v0.85.8): a name and a fee are always the point
    of this line, an unknown address is not information worth a whole
    segment for.

    v0.86.3 Section 9: the event's own raw title may still happen to
    contain the venue's name (e.g. "Tango O Nada 월나다") - that is the
    original post's own text and is never edited or filtered here. Only
    the line 1 venue span (Section 3) has anything to do with the venue at
    all now; this line never adds one.
    """
    thin = ' <span class="tag">정보 적음</span>' if _is_unknown_heavy(event) else ""
    cancelled = " cancelled" if event.get("cancelled") else ""
    name = f'<span class="ev-name{cancelled}">{E(event.get("name") or "")}</span>{thin}'
    dj = event.get("dj")
    dj_html = (
        f' <span class="dj">(DJ {E(dj)})</span>'
        if dj and not _title_already_announces_dj(event.get("name") or "", dj)
        else ""
    )
    address = _compact_address((event.get("venue") or {}).get("address"))
    address_html = f' · <span class="tl-2-addr">{E(address)}</span>' if address else ""
    return f'<div class="tl-2">{name}{dj_html} · {_fee_text(event)}{address_html}</div>'


def _confirmation_text(event: dict[str, Any], *, now: "datetime | None" = None) -> str:
    """2시간 전 확인 - real evidence timestamp only (Section 26-27, 48), the
    same age-bucketing the previous card design already used. v0.85.4: no
    more wrapping parens - this sits as its own " · "-joined segment on
    line 3. v0.85.7 (Section 11): "확인" now appended consistently across
    every bucket rather than only the oldest one, so the phrase reads the
    same regardless of how long ago the post was checked."""
    from datetime import datetime as datetime_type, timezone

    stamp = event.get("last_checked")
    if not stamp:
        return ""
    try:
        seen = datetime_type.fromisoformat(stamp)
    except ValueError:
        return ""
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    moment = now or datetime_type.now(timezone.utc)
    local = seen.astimezone(events_api.SEOUL)
    today = events_api.today(moment)
    age = (moment - seen).total_seconds()
    if age < 3600:
        when = f"{max(1, int(age // 60))}분 전 확인"
    elif local.date() == today:
        when = f"{int(age // 3600)}시간 전 확인"
    else:
        when = f"{local.month}/{local.day} {local:%H:%M} 확인"
    return when


# v0.85.4 (Section 7-14): a 시/도 prefix is already redundant once
# _timeline_line1's own "[지역]" token is on screen, so it is dropped here as
# a display-only simplification - the stored venues.address value itself is
# never touched (Section 25: "원본 DB 주소 값은 절대 변경하지 않는다").
_PROVINCE_PREFIX = re.compile(
    "^(?:서울특별시|서울시|서울|부산광역시|부산시|부산|대구광역시|대구시|대구|"
    "인천광역시|인천시|인천|광주광역시|광주시|광주|대전광역시|대전시|대전|"
    "울산광역시|울산시|울산|세종특별자치시|세종|"
    "경기도|경기|강원특별자치도|강원도|강원|충청북도|충북|충청남도|충남|"
    "전북특별자치도|전라북도|전북|전라남도|전남|"
    "경상북도|경북|경상남도|경남|제주특별자치도|제주도|제주)\\s+"
)
_PURE_STREET_NUMBER = re.compile(r"^\d+(-\d+)?$")
_ADDRESS_HARD_CAP = 18


def _compact_address(address: str | None) -> str | None:
    """서울 서초구 서초대로 123 4층 -> 서초구 서초대로 123... (Section 8-14).

    Display-only: keeps the district and road name plus the first street
    number, and drops whatever comes after it (floor, suite, building name,
    station exit) since that is what makes an address too long for one
    line, not what makes it identifiable. Never invents or reorders
    anything already there - it only decides where to stop reading."""
    if not address or not address.strip():
        return None
    text = _PROVINCE_PREFIX.sub("", address.strip(), count=1)
    tokens = [t for t in re.split(r"[\s,]+", text) if t]
    if not tokens:
        return None
    kept: list[str] = []
    for index, token in enumerate(tokens):
        kept.append(token)
        if _PURE_STREET_NUMBER.match(token):
            return " ".join(kept) + ("…" if index < len(tokens) - 1 else "")
    joined = " ".join(tokens)
    if len(joined) > _ADDRESS_HARD_CAP:
        return joined[:_ADDRESS_HARD_CAP].rstrip() + "…"
    return joined


def _timeline_line3(event: dict[str, Any], *, now: "datetime | None" = None) -> str:
    """출처: OOO ↗ · 확인시간 · 지도보기↗ - Section 1-22 of v0.85.8.

    The address moved to line 2 this release; line 3 is only 출처/
    확인시간/지도보기 now, and it is a single, structurally-unbreakable
    row - not "usually one line" like v0.85.7's own address+meta design,
    which still allowed a rare horizontal micro-scroll. This release
    forbids that too (Section 15): the row itself is `white-space:nowrap;
    overflow:hidden` with no scroll mechanism at all, and the ONE thing
    allowed to shrink is the source's own name (`.src-name`, CSS
    text-overflow: ellipsis via flex min-width:0) - 확인시간 and 지도보기
    are flex-shrink:0 and never touched (Section 20, 37). No source
    master field for a pre-shortened name exists (checked before writing
    this - Section 16's own instruction), so this is the sanctioned
    fallback (Section 19): a real ellipsis on the real name, never an
    invented abbreviation, with the full name still in the link's own
    `title` attribute for anyone who wants it (Section 38).

    Only rendered when there is a real source or confirmation timestamp
    to put on it; a candidate with neither (should not happen in practice
    - every live post has a source_url - but defensively) contributes no
    third line at all, keeping Section 12's "up to three lines" honest
    rather than padding to three."""
    link = event.get("source_link") or {}
    # Defense in depth: events_api.present() already runs this, but a
    # malformed URL must never become a clickable link here either
    # (Section 18), whatever handed the event dict to this function.
    url = events_api.valid_public_url(link.get("url"))
    label = link.get("label")
    confirmed = _confirmation_text(event, now=now)
    # Never a fabricated map link for an address we do not actually have
    # (Section 36) - map_url is already None whenever the venue's own
    # raw address is.
    map_url = (event.get("venue") or {}).get("map_url")
    if not url and not label and not confirmed:
        return ""
    if url:
        shown = E(label) if label else "원문"
        title_attr = f' title="{E(label)}"' if label else ""
        source_html = (
            f'출처: <a class="src-link" href="{E(url)}" target="_blank" '
            f'rel="noopener noreferrer"{title_attr}>'
            f'<span class="src-name">{shown}</span> '
            f'<span class="ext" aria-hidden="true">&#8599;</span></a>'
        )
    elif label:
        source_html = f'출처: <span class="src-name" title="{E(label)}">{E(label)}</span>'
    else:
        source_html = '<span class="unknown">출처 미확인</span>'
    tail = []
    if confirmed:
        tail.append(f'<span class="tl-fixed">{E(confirmed)}</span>')
    if map_url:
        tail.append(
            f'<a class="tl-fixed" href="{E(map_url)}" target="_blank" '
            f'rel="noopener noreferrer">지도보기 '
            f'<span class="ext" aria-hidden="true">&#8599;</span></a>'
        )
    body = source_html + "".join(f" · {t}" for t in tail)
    return f'<div class="tl-3">{body}</div>'


def _event_item(event: dict[str, Any], *, now: "datetime | None" = None,
                terms: "list[dict[str, Any]] | None" = None) -> str:
    kind = _event_kind(event, terms)
    line1 = _timeline_line1(event, now=now, kind=kind)
    if kind is not None and kind.get("uncertain"):
        # v0.87.0: the "?" is a button, which may not sit inside the card's
        # <a>; this card's link becomes an overlay instead (see .card-link).
        name = event.get("name") or ""
        return (
            f'<li class="event has-why"><div class="card-body">{line1}'
            f"{_timeline_line2(event)}</div>"
            f'<a class="card-link" href="/events/{event["id"]}" '
            f'aria-label="{E(name)} 상세 보기"></a>'
            f"{_timeline_line3(event, now=now)}"
            "</li>"
        )
    return (
        f'<li class="event"><a href="/events/{event["id"]}">'
        f"{line1}"
        f'{_timeline_line2(event)}'
        "</a>"
        f"{_timeline_line3(event, now=now)}"
        "</li>"
    )


def _count(kind: str, event_id: int | None = None) -> None:
    """Record one view. Never blocks the page; see runtime.alpha_metrics."""
    alpha_metrics.record(_settings(), kind, event_id=event_id)


@router.get("/", response_class=HTMLResponse)
def home(
    genres: list[str] | None = Query(None),
    genres_set: str | None = Query(None),
    region: str | None = None,
    tab: str | None = None,
) -> HTMLResponse:
    """Tonight, with the dance styles on screen before anything is scrolled.

    v0.88.0: the same page carries the directory tabs. No ``tab`` (or one
    this page does not know) is the events view, unchanged.
    """
    asked = _split_genres(genres)
    current_tab = _directory_tab(tab)
    if current_tab != EVENTS_TAB:
        return _directory_page(current_tab, asked, bool(genres_set))
    try:
        with _connection() as con:
            options = _genre_options(con)
            selected = _selected_genres(options, asked, bool(genres_set))
            constraint = _genre_constraint(options, selected)
            result = events_api.search(
                con, when=events_api.WHEN_TODAY, genres=constraint, region=region,
                limit=20)
            upcoming = events_api.search(
                con, when=events_api.WHEN_UPCOMING, genres=constraint, region=region,
                limit=5)
            facets = _facets(con, events_api.WHEN_TODAY, constraint)
            monday, sunday = events_api.week_window(0)
            week_counts = events_api.week_counts(
                con, start=monday, end=sunday, genres=constraint, region=region)
            terms = _enabled_terms(con)
    except db.DatabaseUnavailable:
        return _unavailable_page("DanceMate")

    genre_query = _genre_query(selected, options)
    # Home has no date-filtered view of its own - a day cell takes the
    # reader to the full /events page for that day, Section 33's own
    # "Weekly Calendar -> Timeline" order kept intact by handing off to the
    # page that actually renders both together for an arbitrary day.
    calendar = _week_calendar(
        monday=monday, sunday=sunday, counts=week_counts, selected_date=None,
        week_offset=0, base_action="/events",
        query={"when": events_api.WHEN_TODAY, **genre_query,
               **({"region": region} if region else {})},
    )

    narrowed = _is_narrowed(options, selected) or bool(region)
    if result["events"]:
        listing = "<ul class=\"events\">" + "".join(
            _event_item(e, terms=terms) for e in result["events"]
        ) + "</ul>"
    else:
        nearest = "".join(
            _event_item(e, terms=terms) for e in upcoming["events"])
        # The nearest events are still inside the reader's filter -- the search
        # above carries it -- so this widens the dates, never the conditions.
        if narrowed:
            message = "오늘은 " + EMPTY_FILTERED if nearest else EMPTY_FILTERED
        else:
            message = EMPTY_TODAY
        listing = (
            f'<p class="empty">{message}</p>'
            + _next_actions(when=events_api.WHEN_TODAY, region=region,
                            genre_query=_genre_query(selected, options))
            + (f'<h2>다가오는 행사</h2><ul class="events">{nearest}</ul>' if nearest else "")
        )

    _count(alpha_metrics.EVENT_LIST_VIEW)
    body = (
        "<h1>DanceMate</h1>"
        '<p class="sub">오늘 어디서 출까.</p>'
        + _directory_nav(EVENTS_TAB, genre_query)
        + _nav("today", genre_query=genre_query)
        + _filter_bar("/", None, facets, options, selected, region)
        + calendar
        + listing
        + _footer()
    )
    return HTMLResponse(_page("DanceMate", body))


# --- weekly calendar (v0.85.0) ----------------------------------------------
#
# One 7-day strip: Monday first (Section 41), today marked, past days dimmed
# but always a real link (Section 35-38), each cell's own number the count
# of distinct events that day (Section 32/42) - clicking a day filters the
# timeline below to it (Section 43), never a page reload's worth of new
# navigation, just a normal link with `date=` set. Counts come from
# events_api.week_counts() in one query per week (Section 63: no N+1 - the
# whole reason that function exists rather than seven separate search()
# calls here).

def _week_calendar(*, monday: "date", sunday: "date", counts: dict[str, int],
                   selected_date: str | None, week_offset: int,
                   base_action: str, query: dict[str, str]) -> str:
    from datetime import timedelta as timedelta_type
    from urllib.parse import urlencode

    today = events_api.today()
    cells = []
    for i in range(7):
        day = monday + timedelta_type(days=i)
        iso = day.isoformat()
        count = counts.get(iso, 0)
        classes = ["cal-day"]
        if day == today:
            classes.append("today")
        if iso == selected_date:
            classes.append("selected")
        if day < today:
            classes.append("past")
        params = {**query, "week": str(week_offset), "date": iso}
        cells.append(
            f'<a class="{" ".join(classes)}" href="{E(base_action)}?{urlencode(params)}">'
            f'<span class="cal-wd">{WEEKDAYS[i]}</span>'
            f'<span class="cal-d">{day.day}</span>'
            f'<span class="cal-n">{count}</span></a>'
        )

    def _nav_link(label: str, offset: int, *, clear_date: bool) -> str:
        params = dict(query)
        if clear_date:
            params.pop("date", None)
        params["week"] = str(offset)
        return f'<a class="cal-nav" href="{E(base_action)}?{urlencode(params)}">{E(label)}</a>'

    nav = (
        _nav_link("← 이전 주", week_offset - 1, clear_date=True)
        + f'<span class="cal-range">{monday.month}/{monday.day} - {sunday.month}/{sunday.day}</span>'
        + _nav_link("이번 주", 0, clear_date=True)
        + _nav_link("다음 주 →", week_offset + 1, clear_date=True)
    )
    return (
        '<div class="calendar">'
        f'<div class="cal-nav-row">{nav}</div>'
        f'<div class="cal-grid">{"".join(cells)}</div>'
        "</div>"
    )


@router.get("/events", response_class=HTMLResponse)
def events_page(
    when: str = Query(events_api.WHEN_TODAY),
    genre: str | None = None,
    genres: list[str] | None = Query(None),
    genres_set: str | None = Query(None),
    region: str | None = None,
    week: int = Query(0, description="week offset from this week, Section 34"),
    date: str | None = Query(None, description="a single day, YYYY-MM-DD - overrides `when`"),
) -> HTMLResponse:
    asked = _split_genres(genres)
    # ?genre=TANGO still works; it simply means that one is ticked.
    if asked is None and genre:
        asked = _split_genres([genre])
    try:
        if date is None:
            events_api.window(when)
        with _connection() as con:
            options = _genre_options(con)
            selected = _selected_genres(options, asked, bool(genres_set) or bool(genre))
            constraint = _genre_constraint(options, selected)
            if date is not None:
                result = events_api.search(
                    con, on=date, genres=constraint, region=region, limit=100)
            else:
                result = events_api.search(
                    con, when=when, genres=constraint, region=region, limit=100)
            facets = (_facets(con, when, constraint) if date is None
                     else _facets_for_date(con, date, constraint))
            monday, sunday = events_api.week_window(week)
            week_counts = events_api.week_counts(
                con, start=monday, end=sunday, genres=constraint, region=region)
            terms = _enabled_terms(con)
    except events_api.SearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except db.DatabaseUnavailable:
        return _unavailable_page(when)

    genre_query = _genre_query(selected, options)
    calendar = _week_calendar(
        monday=monday, sunday=sunday, counts=week_counts, selected_date=date,
        week_offset=week, base_action="/events",
        query={**({"when": when} if date is None else {}), **genre_query,
               **({"region": region} if region else {})},
    )

    actions = _next_actions(when=when, region=region, genre_query=genre_query)
    if result["events"]:
        listing = "<ul class=\"events\">" + "".join(
            _event_item(e, terms=terms) for e in result["events"]
        ) + "</ul>"
    elif _is_narrowed(options, selected) or region:
        listing = f'<p class="empty">{EMPTY_FILTERED}</p>' + (actions if date is None else "")
    else:
        listing = '<p class="empty">해당 기간에 확인된 행사가 없습니다.</p>' + (actions if date is None else "")

    _count(alpha_metrics.EVENT_LIST_VIEW)
    label = _human_date(date) if date is not None else dict(TABS).get(when, when)
    chosen_labels = [o["label"] for o in options if o["code"] in set(selected)]
    narrowed = " · ".join(
        x for x in (", ".join(chosen_labels) if _is_narrowed(options, selected) else "",
                    region or "") if x)
    body = (
        f"<h1>{E(label)}</h1>"
        f'<p class="sub">{result["total"]}건'
        + (f" · {E(narrowed)}" if narrowed else "")
        + " · Asia/Seoul 기준</p>"
        + (_nav(when, region=region, genre_query=genre_query) if date is None else
           f'<p class="sub"><a href="/events?when={E(when)}&week={week}'
           f'{"&region=" + quote(region) if region else ""}">&larr; 목록으로</a></p>')
        + calendar
        + _filter_bar("/events", when if date is None else None, facets, options, selected, region)
        + listing + _footer()
    )
    return HTMLResponse(_page(f"{label} - DanceMate", body))


def _feedback_block(event_id: int, *, sent: str | None = None) -> str:
    """정보가 정확해요 / 달라요 / 부족해요 - Section 54-56. Three plain GET-
    submittable forms (no JavaScript required, same reasoning as the genre
    filter's own auto-submit script: it is progressive enhancement, not a
    requirement), each posting straight to the one thing this ever does -
    record a row - and never touching the event itself (Section 56)."""
    if sent:
        label = feedback.LABELS.get(sent.upper())
        if label:
            return f'<p class="banner">의견을 남겨주셔서 감사합니다 - "{E(label)}"</p>'
    buttons = "".join(
        f'<form method="post" action="/events/{event_id}/feedback" class="fb-form">'
        f'<input type="hidden" name="kind" value="{E(kind)}">'
        f'<button class="fb-btn">{E(label)}</button></form>'
        for kind, label in feedback.LABELS.items()
    )
    return f'<div class="feedback"><span class="key">이 정보, 어떤가요?</span>{buttons}</div>'


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_page(event_id: int, feedback: str | None = Query(None)) -> HTMLResponse:
    try:
        with _connection() as con:
            event = events_api.get_event(con, event_id)
            terms = _enabled_terms(con)
    except db.DatabaseUnavailable:
        return _unavailable_page("DanceMate")
    if event is None:
        raise HTTPException(status_code=404, detail="no such event")
    _count(alpha_metrics.EVENT_DETAIL_VIEW, event_id)

    venue = event.get("venue") or {}
    rows = [
        ("일시", _when_line(event)),
        ("장소", _venue_line(event)),
        ("주소", E(venue.get("address")) if venue.get("address")
                 else '<span class="unknown">주소 미확인</span>'),
        ("요금", _fee_line(event)),
    ]
    if event.get("dj"):
        rows.append(("DJ", E(event["dj"])))
    rows += [
        ("종류", _kind_html(event, _event_kind(event, terms), "kind-why-detail")
                 or '<span class="unknown">-</span>'),
        ("장르", E(event.get("genre_label") or "")
                 or '<span class="unknown">-</span>'),
        ("지역", _region_line(event)),
        ("상태", _status_line(event, with_type=False)
                 or '<span class="unknown">-</span>'),
        ("최근 확인", _checked_line(event) or '<span class="unknown">-</span>'),
    ]
    details = "".join(f"<dt>{E(k)}</dt><dd>{v}</dd>" for k, v in rows)

    # Through a redirect rather than straight out, so "they went to read the
    # post" can be counted. That is the one signal worth having: a detail view
    # says the card was interesting, a source click says the card was not
    # enough. It is a measurement of DanceMate, not of a person.
    sources = "".join(
        f'<li class="event"><a href="/events/{event["id"]}/source?to={quote(source["url"], safe="")}" '
        f'rel="nofollow noopener" target="_blank">'
        f'{E(source["event_name"] or source["url"])}</a></li>'
        for source in event.get("sources") or []
    )
    origin = (
        f'<h2>출처 {len(event.get("sources") or [])}건</h2>'
        f'<ul class="events">{sources}</ul>' if sources else ""
    )

    cancelled = (
        '<div class="banner">이 행사는 <strong>취소</strong>로 표시되어 있습니다. '
        "원문을 확인해 주세요.</div>" if event.get("cancelled") else ""
    )
    body = (
        f'<p class="sub"><a href="/events?when=today">&larr; 목록</a></p>'
        + cancelled
        + f"<h1>{E(event.get('name') or '')}</h1>"
        f"<dl>{details}</dl>"
        + origin
        + _feedback_block(event_id, sent=feedback)
        + _footer()
    )
    return HTMLResponse(_page(f"{event.get('name')} - DanceMate", body))


@router.get("/events/{event_id}/source")
def event_source(event_id: int, to: str) -> RedirectResponse:
    """Send a reader to the original post, and count that they went.

    Only to a URL this event actually lists. An open redirect on a page anyone
    can reach is a way to lend DanceMate's address to somebody else's link.
    """
    try:
        with _connection() as con:
            event = events_api.get_event(con, event_id)
    except db.DatabaseUnavailable:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    if event is None:
        raise HTTPException(status_code=404, detail="no such event")
    allowed = {s["url"] for s in event.get("sources") or [] if s.get("url")}
    if to not in allowed:
        raise HTTPException(status_code=400, detail="not a source of this event")
    _count(alpha_metrics.SOURCE_LINK_CLICK, event_id)
    return RedirectResponse(to, status_code=303)


@router.post("/events/{event_id}/feedback")
def submit_feedback(event_id: int, kind: str = Form(...)) -> RedirectResponse:
    """Record one feedback row and bounce straight back to the event page
    (Section 56: never mutates the event - the redirect target is the same
    detail page, now carrying ?feedback= so it can thank the reader)."""
    try:
        with _connection() as con:
            if events_api.get_event(con, event_id) is None:
                raise HTTPException(status_code=404, detail="no such event")
            feedback.record(con, event_id=event_id, kind=kind)
    except db.DatabaseUnavailable:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    except feedback.UnknownKind:
        raise HTTPException(status_code=400, detail="unknown feedback kind") from None
    return RedirectResponse(
        f"/events/{event_id}?feedback={quote(kind)}", status_code=303)


# --- directory tabs (v0.88.0) -------------------------------------------------
#
# 장소 / 동호회 / 정보원 / 게시판 beside the events. Every tab reads the genre
# choice through the same functions the event list uses (_selected_genres,
# _genre_constraint, _genre_query), so a selection survives a tab change, a
# reload and a shared link. What a tab does with a row that has no genre is
# runtime/directory.py's documented policy, not decided here.

def _directory_tab(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    return key if key in DIRECTORY_TAB_KEYS else EVENTS_TAB


def _directory_nav(current: str, genre_query: dict[str, str]) -> str:
    """The five tabs. Each link keeps the genre choice and nothing else."""
    from urllib.parse import urlencode

    links = []
    for key, label in DIRECTORY_TABS:
        params = dict(genre_query) if key == EVENTS_TAB else {"tab": key, **genre_query}
        href = "/" + (f"?{urlencode(params)}" if params else "")
        mark = ' aria-current="page"' if key == current else ""
        links.append(f'<a href="{E(href)}"{mark}>{E(label)}</a>')
    return ('<nav class="dirtabs" aria-label="DanceMate 둘러보기">'
            + "".join(links) + "</nav>")


def _tags(codes: "list[str] | None", labels: dict[str, str], *, none_label: str,
          lead: str = "", title: bool = False) -> str:
    """Genre labels as small tags - enabled genres only (a disabled genre is not
    something this product shows), ``none_label`` for a row with no genre.
    ``title`` puts the whole list in a tooltip, for a one-line row that may
    cut it short."""
    names = ([labels[c] for c in codes if c in labels] if codes else [none_label])
    items = ([lead] if lead else []) + [f'<li class="tag">{E(n)}</li>' for n in names]
    tip = f' title="{E(", ".join(names))}"' if title and names else ""
    return f'<ul class="tags"{tip}>{"".join(items)}</ul>' if items else ""


def _external(url: str | None, label: str) -> str:
    return (f'<a href="{E(url)}" target="_blank" rel="noopener noreferrer">'
            f'{E(label)} &#8599;</a>') if url else ""


def _dir_row(name: str, facts: "tuple[str | None, ...]", tags: str, link: str) -> str:
    """One directory entry on one line: name, facts (region, address, platform
    ...), genre tags, link."""
    shown = " · ".join(x for x in facts if x)
    return (
        '<li class="dir-row">'
        f'<span class="dir-name" title="{E(name)}">{E(name)}</span>'
        + (f'<span class="dir-meta" title="{E(shown)}">{E(shown)}</span>' if shown else "")
        + tags
        + (f'<span class="dir-go">{link}</span>' if link else "")
        + "</li>"
    )


def _venue_card(venue: dict[str, Any], labels: dict[str, str]) -> str:
    return _dir_row(
        venue["name"], (venue.get("region_name"), venue.get("address")),
        _tags(venue.get("genre_codes"), labels, none_label="장르 미지정", title=True),
        _external(events_api.build_naver_map_search_url(venue.get("address")), "지도"),
    )


def _community_card(community: dict[str, Any], labels: dict[str, str]) -> str:
    places = community.get("venue_names") or []
    links = _external(community.get("homepage_url"), "홈페이지")
    return (
        '<li class="dir-item">'
        f'<div class="dir-name">{E(community["name"])}</div>'
        + (f'<p class="dir-meta">{E(community["region_name"])}</p>'
           if community.get("region_name") else "")
        + (f'<p class="dir-desc">{E(community["description"])}</p>'
           if community.get("description") else "")
        + (f'<p class="dir-meta">장소: {E(", ".join(places))}</p>' if places else "")
        + _tags(community.get("genre_codes"), labels, none_label="장르 미지정")
        + (f'<p class="dir-links">{links}</p>' if links else "")
        + "</li>"
    )


def _source_card(source: dict[str, Any], labels: dict[str, str]) -> str:
    code = source.get("genre_code")
    return _dir_row(
        source["name"],
        (source["platform_label"], source["tier_label"], source.get("region_name")),
        _tags([code] if code else [], labels, none_label="장르 미확인", title=True),
        _external(source.get("public_url"), "바로가기"),
    )


def _notice_date(value) -> str:
    if not value:
        return ""
    day = value.astimezone(events_api.SEOUL)
    return f"{day.year}.{day.month:02d}.{day.day:02d}"


NOTICE_EXCERPT_CHARS = 100


def _notice_excerpt(text: str | None) -> str:
    """One line of the body under a notice's title - whitespace collapsed,
    cut at NOTICE_EXCERPT_CHARS, escaped like everything else."""
    line = " ".join((text or "").split())
    if not line:
        return ""
    if len(line) > NOTICE_EXCERPT_CHARS:
        line = line[:NOTICE_EXCERPT_CHARS].rstrip() + "…"
    return f'<p class="dir-desc">{E(line)}</p>'


def _notice_card(notice: dict[str, Any], labels: dict[str, str]) -> str:
    pin = '<li class="tag pin">고정</li>' if notice.get("pinned") else ""
    return (
        f'<li class="dir-item"><a class="dir-link" href="/notices/{int(notice["post_id"])}">'
        f'<div class="dir-name">{E(notice["title"])}</div>'
        f'<p class="dir-meta">{E(_notice_date(notice.get("published_at")))}</p>'
        + _notice_excerpt(notice.get("excerpt"))
        + _tags(notice.get("genre_codes"), labels, none_label="전체 공지", lead=pin)
        + "</a></li>"
    )


_DIRECTORY_SPECS: dict[str, dict[str, Any]] = {
    "venues": {
        "title": "장소", "sub": "춤출 수 있는 곳.", "loader": "public_venues",
        "card": _venue_card, "list_class": "dir rows",
        "empty": "등록된 장소가 없습니다.",
        "empty_filtered": "선택한 춤 종류에 해당하는 장소가 없습니다.",
        "note": "장르가 지정되지 않은 장소는 춤 종류 전체를 볼 때만 표시됩니다.",
    },
    "communities": {
        "title": "동호회", "sub": "함께 추는 사람들.", "loader": "public_communities",
        "card": _community_card,
        "empty": "등록된 동호회가 없습니다.",
        "empty_filtered": "선택한 춤 종류에 해당하는 동호회가 없습니다.",
        "note": "장르가 지정되지 않은 동호회는 춤 종류 전체를 볼 때만 표시됩니다.",
    },
    "sources": {
        "title": "정보원", "sub": "DanceMate가 행사 소식을 모으는 곳.",
        "loader": "public_sources", "card": _source_card, "list_class": "dir rows",
        "empty": "등록된 정보원이 없습니다.",
        "empty_filtered": "선택한 춤 종류에 해당하는 정보원이 없습니다.",
        "note": "장르가 확인되지 않은 정보원은 춤 종류 전체를 볼 때만 표시됩니다.",
    },
    "notices": {
        "title": "게시판", "sub": "DanceMate 공지사항.", "loader": "public_notices",
        "card": _notice_card,
        "empty": "등록된 공지가 없습니다.",
        "empty_filtered": "선택한 춤 종류에 해당하는 공지사항이 없습니다.",
        "note": "장르를 정하지 않은 전체 공지는 어떤 춤 종류를 골라도 함께 보입니다.",
    },
}


def _directory_page(tab: str, asked: "list[str] | None", declared: bool) -> HTMLResponse:
    from . import directory

    spec = _DIRECTORY_SPECS[tab]
    try:
        with _connection() as con:
            options = _genre_options(con)
            selected = _selected_genres(options, asked, declared)
            constraint = _genre_constraint(options, selected)
            rows = getattr(directory, spec["loader"])(con, constraint)
    except db.DatabaseUnavailable:
        return _unavailable_page("DanceMate")

    genre_query = _genre_query(selected, options)
    labels = {o["code"]: o["label"] for o in options}
    form = _genre_filter("/", None, None, options, selected, tab=tab)
    narrowed = constraint is not None
    if rows:
        listing = (f'<ul class="{spec.get("list_class", "dir")}">'
                   + "".join(spec["card"](row, labels) for row in rows) + "</ul>")
    elif constraint == []:
        listing = f'<p class="empty">{E(EMPTY_NOTHING_TICKED)}</p>'
    else:
        listing = f'<p class="empty">{E(spec["empty_filtered"] if narrowed else spec["empty"])}</p>'
    body = (
        "<h1>DanceMate</h1>"
        f'<p class="sub">{E(spec["sub"])}</p>'
        + _directory_nav(tab, genre_query)
        + (f'<div class="filters">{form}</div>{AUTO_SUBMIT}' if form else "")
        + (f'<p class="dir-note">{E(spec["note"])}</p>' if narrowed else "")
        + listing
        + _footer()
    )
    return HTMLResponse(_page(f"{spec['title']} - DanceMate", body))


# A bare web address inside a notice's plain-text body.
_NOTICE_URL = re.compile(r"https?://[^\s<>\"']+")
_URL_TRAILING = ".,;:!?)]}'\"。、」』）"


def _linkify(line: str) -> str:
    """Escape a line of text, turning each bare http(s) address into a link.
    Nothing else in the text is ever markup."""
    out, last = [], 0
    for match in _NOTICE_URL.finditer(line):
        url = match.group(0).rstrip(_URL_TRAILING)
        start, end = match.start(), match.start() + len(url)
        out.append(E(line[last:start]))
        safe = events_api.valid_public_url(url)
        out.append(f'<a href="{E(safe)}" target="_blank" rel="nofollow noopener noreferrer">'
                   f'{E(url)}</a>' if safe else E(url))
        last = end
    out.append(E(line[last:]))
    return "".join(out)


def _notice_body_html(body: str | None) -> str:
    """Plain text to HTML: paragraphs at blank lines, <br> at single breaks."""
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return ""
    return ('<div class="notice-body">' + "".join(
        "<p>" + "<br>".join(_linkify(line) for line in p.split("\n")) + "</p>"
        for p in paragraphs) + "</div>")


def _notice_missing() -> HTMLResponse:
    body = ('<p class="back"><a href="/?tab=notices">← 게시판</a></p>'
            '<h1>공지를 찾을 수 없습니다</h1>'
            '<p class="empty">삭제되었거나 아직 게시되지 않은 공지입니다.</p>' + _footer())
    return HTMLResponse(_page("DanceMate", body), status_code=404)


@router.get("/notices/{post_id}", response_class=HTMLResponse)
def notice_page(post_id: str) -> HTMLResponse:
    """One published notice. A draft, a hidden post or a garbage id is a 404."""
    from . import directory

    text = (post_id or "").strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 18 or int(text) == 0:
        return _notice_missing()
    try:
        with _connection() as con:
            options = _genre_options(con)
            notice = directory.public_notice(con, int(text))
    except db.DatabaseUnavailable:
        return _unavailable_page("DanceMate")
    if notice is None:
        return _notice_missing()
    labels = {o["code"]: o["label"] for o in options}
    pin = '<li class="tag pin">고정</li>' if notice.get("pinned") else ""
    body = (
        '<p class="back"><a href="/?tab=notices">← 게시판</a></p>'
        f'<h1>{E(notice["title"])}</h1>'
        f'<p class="sub">{E(_notice_date(notice.get("published_at")))}</p>'
        + _tags(notice.get("genre_codes"), labels, none_label="전체 공지", lead=pin)
        + _notice_body_html(notice.get("body"))
        + _footer()
    )
    return HTMLResponse(_page(f"{notice['title']} - DanceMate", body))


def _footer() -> str:
    """Say where this came from and what it is.

    An alpha that does not admit it is an alpha invites people to trust a
    number nobody has checked.
    """
    return (
        "<footer><strong>DanceMate Alpha</strong> · 공개 게시글에서 추출한 "
        "정보이고 바뀔 수 있습니다. 확인되지 않은 항목은 비워 두니, 가시기 전에 "
        "원문을 함께 확인해 주세요.</footer>"
    )


def _unavailable_page(title: str) -> HTMLResponse:
    """503 with a sentence, not a stack trace.

    A reader who cannot be served needs to know that -- rendering an empty list
    would tell them there is nothing on tonight.
    """
    body = (
        "<h1>DanceMate</h1>"
        f'<p class="empty">{E(UNAVAILABLE)}</p>' + _footer()
    )
    return HTMLResponse(_page(str(title), body), status_code=503)
