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
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import alpha_metrics, db, events_api
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
    include_past: bool = False,
    include_cancelled: bool = False,
) -> JSONResponse:
    try:
        # Validated before a connection is opened, so a bad query is a 400 even
        # when the database is down.
        events_api.window(when)
        with _connection() as con:
            return _json(events_api.search(
                con, when=when, on=date, date_from=date_from, date_to=date_to,
                genre=genre, region=region, status=status, limit=limit, offset=offset,
                include_past=include_past, include_cancelled=include_cancelled,
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
.filters { margin: 0 0 1.25rem; }
.filters .row { display:flex; gap:.4rem; flex-wrap:wrap; align-items:center; margin-top:.5rem; }
.filters .key { color:var(--muted); font-size:.8rem; width:2.6rem; flex:none; }
.filters a { border:1px solid var(--line); border-radius:999px; padding:.2rem .7rem;
             text-decoration:none; font-size:.8rem; background:var(--card); color:var(--muted); }
.filters a[aria-current="true"] { border-color:var(--accent); color:var(--accent); font-weight:600; }
.status { font-size:.7rem; border:1px solid var(--line); border-radius:4px;
          padding:.05rem .35rem; color:var(--muted); }
.status.ok { border-color:var(--accent); color:var(--accent); }
.checked { color:var(--muted); font-size:.75rem; }
.cancelled { text-decoration: line-through; }
.banner { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
          border-radius:8px; padding:.8rem 1rem; margin-bottom:1rem; font-size:.875rem; }
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


def _facets(con, when: str) -> dict[str, list[dict[str, Any]]]:
    """The genres and regions that have events *in the window being shown*.

    Counted over the same dates the page lists, because a chip is a promise. A
    "Swing 1" chip beside a page that returns nothing is the same small lie as
    offering an empty filter: it says events of that kind are in here when they
    are not.
    """
    window = events_api.window(when)
    where = [events_api._VISIBLE, "e.engine_status <> 'CANCELLED'"]
    params: list[Any] = []
    if window:
        where.append("e.event_date BETWEEN %s AND %s")
        params.extend(window)
    else:
        where.append("e.event_date >= current_date")
    clause = " AND ".join(where)

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
            # Only places, not the country-level row. "South Korea" as a filter
            # option next to Seoul and Busan tells a reader nothing about where
            # to go, and offering it makes the other two look like subsets.
            f"WHERE {clause} AND r.city IS NOT NULL "
            "GROUP BY 1, 2 ORDER BY events DESC",
            tuple(params),
        )
        regions = [dict(zip([c.name for c in cur.description], r)) for r in cur.fetchall()]
    return {"genres": genres, "regions": regions}


def _filter_bar(when: str, facets: dict[str, list[dict[str, Any]]],
                genre: str | None, region: str | None) -> str:
    """Genre and region, shown only when there is more than one to choose."""
    from urllib.parse import urlencode

    def chips(key: str, rows: list[dict[str, Any]], chosen: str | None) -> str:
        if len(rows) < 2:
            return ""
        links = []
        for row in [{"value": None, "label": "전체"}] + rows:
            params = {"when": when}
            if genre and key != "genre":
                params["genre"] = genre
            if region and key != "region":
                params["region"] = region
            if row["value"]:
                params[key] = row["value"]
            mark = ' aria-current="true"' if (row["value"] or None) == chosen else ""
            count = f' {row["events"]}' if row.get("events") else ""
            links.append(
                f'<a href="/events?{urlencode(params)}"{mark}>{E(row["label"])}{count}</a>'
            )
        title = "장르" if key == "genre" else "지역"
        return (f'<div class="row"><span class="key">{title}</span>'
                + "".join(links) + "</div>")

    body = chips("genre", facets["genres"], genre) + chips("region", facets["regions"], region)
    return f'<div class="filters">{body}</div>' if body else ""


def _nav(current: str, genre: str | None = None, region: str | None = None) -> str:
    from urllib.parse import urlencode

    links = []
    for key, label in TABS:
        params = {"when": key}
        if genre:
            params["genre"] = genre
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


def _status_line(event: dict[str, Any]) -> str:
    """What we know about this event, in words a reader owes nobody to decode.

    The engine says VERIFIED or POSSIBLE. Neither belongs on a page someone
    reads on the way out the door, and VERIFIED does not mean "true" anyway --
    it means the evidence gate passed.
    """
    parts = []
    if event.get("event_type_label"):
        parts.append(f'<span class="status">{E(event["event_type_label"])}</span>')
    if event.get("cancelled"):
        parts.append('<span class="status">취소</span>')
    elif event.get("status_label"):
        tone = " ok" if event.get("status") == "VERIFIED" else ""
        parts.append(f'<span class="status{tone}">{E(event["status_label"])}</span>')
    if event.get("human_reviewed"):
        parts.append('<span class="status">관리자 확인</span>')
    return "".join(parts)


def _checked_line(event: dict[str, Any]) -> str:
    """When we last read the post behind this.

    Not a freshness score. The timestamp, and a nudge when an event is close
    and what we know about it is not.
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
    local = seen.astimezone(events_api.SEOUL)
    today = events_api.today()
    age = (datetime.now(timezone.utc) - seen).total_seconds()
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


def _event_item(event: dict[str, Any]) -> str:
    cancelled = " cancelled" if event.get("cancelled") else ""
    return (
        f'<li class="event"><a href="/events/{event["id"]}">'
        f'{_when_line(event)}'
        f'<div class="name{cancelled}">{E(event.get("name") or "")}</div>'
        f'<div class="meta"><span>{_venue_line(event)}</span>'
        f'<span>{_fee_line(event)}</span>{_status_line(event)}</div>'
        "</a></li>"
    )


def _count(kind: str, event_id: int | None = None) -> None:
    """Record one view. Never blocks the page; see runtime.alpha_metrics."""
    alpha_metrics.record(_settings(), kind, event_id=event_id)


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    """Tonight, without asking anyone to choose a filter first."""
    try:
        with _connection() as con:
            result = events_api.search(con, when=events_api.WHEN_TODAY, limit=20)
            upcoming = events_api.search(con, when=events_api.WHEN_UPCOMING, limit=5)
            facets = _facets(con, events_api.WHEN_TODAY)
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

    _count(alpha_metrics.EVENT_LIST_VIEW)
    body = (
        "<h1>DanceMate</h1>"
        '<p class="sub">오늘 어디서 출까.</p>'
        + _nav("today")
        + _filter_bar("today", facets, None, None)
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
            facets = _facets(con, when)
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

    _count(alpha_metrics.EVENT_LIST_VIEW)
    label = dict(TABS).get(when, when)
    narrowed = " · ".join(x for x in (genre, region) if x)
    body = (
        f"<h1>{E(label)}</h1>"
        f'<p class="sub">{result["total"]}건'
        + (f" · {E(narrowed)}" if narrowed else "")
        + " · Asia/Seoul 기준</p>"
        + _nav(when, genre, region)
        + _filter_bar(when, facets, genre, region)
        + listing + _footer()
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
    _count(alpha_metrics.EVENT_DETAIL_VIEW, event_id)

    venue = event.get("venue") or {}
    rows = [
        ("일시", _when_line(event)),
        ("장소", _venue_line(event)),
        ("주소", E(venue.get("address")) if venue.get("address")
                 else '<span class="unknown">주소 미확인</span>'),
        ("요금", _fee_line(event)),
        ("종류", E(event.get("event_type_label") or "")
                 or '<span class="unknown">-</span>'),
        ("장르", E(event.get("genre") or "") or '<span class="unknown">-</span>'),
        ("지역", E(event.get("region") or "") or '<span class="unknown">-</span>'),
        ("상태", _status_line(event) or '<span class="unknown">-</span>'),
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
