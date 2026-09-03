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
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from . import db, events_api
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
    region: str | None = None,
    status: str | None = None,
    limit: int = events_api.DEFAULT_LIMIT,
    offset: int = 0,
) -> JSONResponse:
    try:
        # Validated before a connection is opened, so a bad query is a 400 even
        # when the database is down.
        events_api.window(when)
        with _connection() as con:
            return _json(events_api.search(
                con, when=when, on=date, date_from=date_from, date_to=date_to,
                genre=genre, region=region, status=status, limit=limit, offset=offset,
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
ul.events { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:.6rem; }
li.event { background:var(--card); border:1px solid var(--line); border-radius:12px; }
li.event a { display:block; padding:.9rem 1rem; text-decoration:none; }
.when { font-variant-numeric: tabular-nums; font-weight:600; }
.name { margin:.15rem 0; }
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


def _nav(current: str) -> str:
    links = []
    for key, label in TABS:
        mark = ' aria-current="page"' if key == current else ""
        links.append(f'<a href="/events?when={key}"{mark}>{E(label)}</a>')
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
        clock = start
    if start and event.get("time_confirmed") is False:
        # The post wrote a bare clock. 5시30 is very likely half past five in
        # the evening, but the post does not say so and neither will we -- the
        # reading stands, flagged, with the original a click away.
        clock += ' <span class="tag">시간 미확인</span>'
    if not start:
        # Not "TBD": we simply do not know, and the post is linked so a reader
        # can check for themselves.
        clock = '<span class="unknown">시간 미확인</span>'
    return f'<span class="when">{E(label)} {clock}</span>'


def _venue_line(event: dict[str, Any]) -> str:
    venue = event.get("venue") or {}
    name = venue.get("name")
    if not name:
        return '<span class="unknown">장소 미확인</span>'
    if venue.get("status") == "UNRESOLVED":
        # We read this string off the post and have not confirmed the place.
        return f'{E(name)} <span class="tag">미확인</span>'
    return E(name)


def _fee_line(event: dict[str, Any]) -> str:
    fee = event.get("fee")
    if fee is None:
        return '<span class="unknown">요금 미확인</span>'
    return f"{fee:,}원"


def _event_item(event: dict[str, Any]) -> str:
    return (
        f'<li class="event"><a href="/events/{event["id"]}">'
        f'{_when_line(event)}'
        f'<div class="name">{E(event.get("name") or "")}</div>'
        f'<div class="meta"><span>{_venue_line(event)}</span>'
        f'<span>{_fee_line(event)}</span></div>'
        "</a></li>"
    )


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    """Tonight, without asking anyone to choose a filter first."""
    try:
        with _connection() as con:
            result = events_api.search(con, when=events_api.WHEN_TODAY, limit=20)
            upcoming = events_api.search(con, when=events_api.WHEN_UPCOMING, limit=5)
    except db.DatabaseUnavailable:
        return _unavailable_page("DanceMate")

    if result["events"]:
        listing = "<ul class=\"events\">" + "".join(
            _event_item(e) for e in result["events"]
        ) + "</ul>"
    else:
        nearest = "".join(_event_item(e) for e in upcoming["events"])
        listing = (
            '<p class="empty">오늘 확인된 행사가 없습니다. '
            "수집된 글에서 확인된 것만 보여드립니다.</p>"
            + (f'<h2>다가오는 행사</h2><ul class="events">{nearest}</ul>' if nearest else "")
        )

    body = (
        "<h1>DanceMate</h1>"
        '<p class="sub">오늘 어디서 출까.</p>'
        + _nav("today")
        + listing
        + _footer()
    )
    return HTMLResponse(_page("DanceMate", body))


@router.get("/events", response_class=HTMLResponse)
def events_page(
    when: str = Query(events_api.WHEN_TODAY),
    genre: str | None = None,
    region: str | None = None,
) -> HTMLResponse:
    try:
        events_api.window(when)
        with _connection() as con:
            result = events_api.search(con, when=when, genre=genre, region=region, limit=100)
    except events_api.SearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except db.DatabaseUnavailable:
        return _unavailable_page(when)

    if result["events"]:
        listing = "<ul class=\"events\">" + "".join(
            _event_item(e) for e in result["events"]
        ) + "</ul>"
    else:
        listing = '<p class="empty">해당 기간에 확인된 행사가 없습니다.</p>'

    label = dict(TABS).get(when, when)
    body = (
        f"<h1>{E(label)}</h1>"
        f'<p class="sub">{result["total"]}건 · Asia/Seoul 기준</p>'
        + _nav(when) + listing + _footer()
    )
    return HTMLResponse(_page(f"{label} - DanceMate", body))


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_page(event_id: int) -> HTMLResponse:
    try:
        with _connection() as con:
            event = events_api.get_event(con, event_id)
    except db.DatabaseUnavailable:
        return _unavailable_page("DanceMate")
    if event is None:
        raise HTTPException(status_code=404, detail="no such event")

    venue = event.get("venue") or {}
    rows = [
        ("일시", _when_line(event)),
        ("장소", _venue_line(event)),
        ("주소", E(venue.get("address")) if venue.get("address")
                 else '<span class="unknown">-</span>'),
        ("요금", _fee_line(event)),
    ]
    details = "".join(f"<dt>{E(k)}</dt><dd>{v}</dd>" for k, v in rows)

    sources = "".join(
        f'<li class="event"><a href="{E(source["url"])}" rel="nofollow noopener" '
        f'target="_blank">{E(source["event_name"] or source["url"])}</a></li>'
        for source in event.get("sources") or []
    )
    origin = (
        f'<h2>출처 {len(event.get("sources") or [])}건</h2>'
        f'<ul class="events">{sources}</ul>' if sources else ""
    )

    body = (
        f'<p class="sub"><a href="/events?when=today">&larr; 목록</a></p>'
        f"<h1>{E(event.get('name') or '')}</h1>"
        f"<dl>{details}</dl>"
        + origin
        + _footer()
    )
    return HTMLResponse(_page(f"{event.get('name')} - DanceMate", body))


def _footer() -> str:
    """Say where this came from and what it is.

    An alpha that does not admit it is an alpha invites people to trust a
    number nobody has checked.
    """
    return (
        "<footer>수집된 공개 게시글에서 추출한 정보입니다. "
        "확인되지 않은 항목은 비워 둡니다 — 원문을 함께 확인해 주세요. "
        "DanceMate alpha.</footer>"
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
