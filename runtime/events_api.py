"""Alpha Event Search: the first thing in DanceMate a dancer uses.

One question, asked plainly: *what can I go to?* So the API is narrow on
purpose -- a date window, a genre, a region, a status, and one event by id.
No recommendations, no ranking, no scoring. Those need a reason to exist and
right now there is none.

What it will not serve:

    Anything that is not LIVE. A replayed snapshot and a PoC fixture are how we
    test a parser. Showing one as a real Saturday night would be a lie told to
    someone making plans.

    A duplicate, or an event a person rejected. Both stay in the database with
    their provenance; neither is an answer to "where can I dance tonight?".

Dates are Asia/Seoul. "Today" means today where the dancer is, not UTC: at
23:00 KST a UTC-based "today" would already be showing tomorrow's list.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")

WHEN_TODAY = "today"
WHEN_TOMORROW = "tomorrow"
WHEN_THIS_WEEK = "this_week"
WHEN_WEEKEND = "weekend"
WHEN_UPCOMING = "upcoming"

WHEN_VALUES = (WHEN_TODAY, WHEN_TOMORROW, WHEN_THIS_WEEK, WHEN_WEEKEND, WHEN_UPCOMING)

MAX_LIMIT = 100
DEFAULT_LIMIT = 50


class SearchError(ValueError):
    """The query cannot be answered as asked."""


def today(now: datetime | None = None) -> date:
    """Today in Seoul."""
    moment = now.astimezone(SEOUL) if now else datetime.now(SEOUL)
    return moment.date()


def window(when: str | None, *, now: datetime | None = None) -> tuple[date, date] | None:
    """The date range a ``when`` keyword means, inclusive at both ends."""
    if not when:
        return None
    key = when.strip().lower()
    start = today(now)
    if key == WHEN_TODAY:
        return start, start
    if key == WHEN_TOMORROW:
        return start + timedelta(days=1), start + timedelta(days=1)
    if key == WHEN_THIS_WEEK:
        # Today through Sunday: "this week" is what is still ahead of you, not
        # a calendar week half of which has already happened.
        days_to_sunday = 6 - start.weekday()
        return start, start + timedelta(days=days_to_sunday)
    if key == WHEN_WEEKEND:
        days_to_saturday = (5 - start.weekday()) % 7
        saturday = start + timedelta(days=days_to_saturday)
        return saturday, saturday + timedelta(days=1)
    if key == WHEN_UPCOMING:
        return start, start + timedelta(days=30)
    raise SearchError(
        f"unknown when={when!r}; expected one of {', '.join(WHEN_VALUES)}"
    )


def _as_date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise SearchError(f"{field} must be YYYY-MM-DD, got {value!r}") from None


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _clock(value: Any) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M") if isinstance(value, time) else str(value)[:5]


def present(row: dict[str, Any]) -> dict[str, Any]:
    """One event as the API returns it.

    Missing stays missing. A null fee is not 0 and a null venue is not "TBD":
    both would read as information we do not have. ``venue.status`` says
    whether the place is one we recognise or only a string we read.
    """
    return {
        "id": row["event_id"],
        "name": row["event_name"],
        "date": row["event_date"].isoformat() if row.get("event_date") else None,
        "start_time": _clock(row.get("start_time")),
        "end_time": _clock(row.get("end_time")),
        "ends_next_day": bool(row.get("end_day_offset")),
        "venue": {
            "name": row.get("venue_name") or row.get("venue_text"),
            "status": row.get("venue_status"),
            "address": row.get("venue_address"),
            "id": row.get("venue_id"),
        },
        "fee": row.get("fee"),
        "currency": "KRW" if row.get("fee") is not None else None,
        "genre": row.get("genre_code"),
        "region": row.get("region_name"),
        "status": row.get("engine_status"),
        "reviewed": row.get("review_state"),
        "source_url": row.get("source_url"),
    }


_SELECT = (
    "SELECT e.*, v.name AS venue_name, v.address AS venue_address, "
    "       g.code AS genre_code, r.name AS region_name "
    "FROM events e "
    "LEFT JOIN venues v ON v.venue_id = e.venue_id "
    "LEFT JOIN genres g ON g.genre_id = e.genre_id "
    "LEFT JOIN regions r ON r.region_id = e.region_id "
)

# Every alpha query starts here. Live, not a duplicate, not hidden.
_VISIBLE = (
    "e.provenance = 'LIVE' "
    "AND e.listing_state = 'LISTED' "
    "AND e.canonical_event_id IS NULL"
)


def search(con, *, when: str | None = None, on: Any = None, date_from: Any = None,
           date_to: Any = None, genre: str | None = None, region: str | None = None,
           status: str | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0,
           now: datetime | None = None) -> dict[str, Any]:
    """Events a dancer could go to, soonest first."""
    if limit < 1 or limit > MAX_LIMIT:
        raise SearchError(f"limit must be between 1 and {MAX_LIMIT}")
    if offset < 0:
        raise SearchError("offset cannot be negative")

    where = [_VISIBLE]
    params: list[Any] = []

    single = _as_date(on, "date")
    start = _as_date(date_from, "from")
    end = _as_date(date_to, "to")
    keyword = window(when, now=now)

    if single is not None:
        start = end = single
    elif keyword is not None and start is None and end is None:
        start, end = keyword

    if start is not None:
        where.append("e.event_date >= %s")
        params.append(start)
    if end is not None:
        where.append("e.event_date <= %s")
        params.append(end)
    if genre:
        where.append("g.code = %s")
        params.append(genre.strip().upper())
    if region:
        where.append("(r.code = %s OR r.name ILIKE %s)")
        params.extend([region.strip().upper(), region.strip()])
    if status:
        where.append("e.engine_status = %s")
        params.append(status.strip().upper())

    clause = " AND ".join(where)
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events e "
            "LEFT JOIN genres g ON g.genre_id = e.genre_id "
            "LEFT JOIN regions r ON r.region_id = e.region_id "
            "WHERE " + clause,
            tuple(params),
        )
        total = cur.fetchone()[0]
        cur.execute(
            _SELECT + "WHERE " + clause +
            # Soonest first; an event with no time last within its day, because
            # a time we do not have should not outrank one we do.
            " ORDER BY e.event_date, e.start_time NULLS LAST, e.event_id "
            "LIMIT %s OFFSET %s",
            tuple(params) + (limit, offset),
        )
        rows = _rows(cur)

    return {
        "events": [present(row) for row in rows],
        "count": len(rows),
        "total": total,
        "query": {
            "when": when,
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
            "genre": genre,
            "region": region,
            "status": status,
            "limit": limit,
            "offset": offset,
            "timezone": "Asia/Seoul",
        },
    }


def get_event(con, event_id: int) -> dict[str, Any] | None:
    """One event, with every post that mentioned it.

    The sources list is the point of keeping duplicates rather than deleting
    them: a reader who wants to check the fee can go and read the post.
    """
    with con.cursor() as cur:
        cur.execute(_SELECT + "WHERE e.event_id = %s AND " + _VISIBLE, (event_id,))
        rows = _rows(cur)
    if not rows:
        return None

    from . import duplicates  # local import: search does not need it

    event = present(rows[0])
    event["sources"] = [
        {
            "url": source["source_url"],
            "event_name": source["event_name"],
            "is_canonical": source["is_canonical"],
        }
        for source in duplicates.sources_of(con, event_id)
        if source["source_url"]
    ]
    return event
