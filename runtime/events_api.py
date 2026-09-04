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
from collections.abc import Sequence
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
        # False when the post wrote a bare clock and nothing said which half of
        # the day it meant. The value is what the post says; this says how much
        # that is worth.
        "time_confirmed": (None if row.get("start_time") is None
                           else row.get("time_evidence") != "ABSENT"),
        "venue": {
            "name": row.get("venue_name") or row.get("venue_text"),
            "status": row.get("venue_status"),
            "address": row.get("venue_address"),
            "id": row.get("venue_id"),
        },
        "fee": row.get("fee"),
        "currency": "KRW" if row.get("fee") is not None else None,
        "event_type": row.get("event_type"),
        "event_type_label": EVENT_TYPE_LABELS.get(
            (row.get("event_type") or "").upper()),
        "genre": row.get("genre_code"),
        "region": row.get("region_name"),
        "region_code": row.get("region_code"),
        "status": row.get("engine_status"),
        "status_label": STATUS_LABELS.get(
            (row.get("engine_status") or "").upper(), "확인 필요"),
        "cancelled": (row.get("engine_status") or "").upper() == CANCELLED,
        "reviewed": row.get("review_state"),
        "human_reviewed": (row.get("review_state") or "").upper() in REVIEWED_STATES,
        "last_checked": (row["collected_at"].isoformat()
                         if row.get("collected_at") else None),
        "source_url": row.get("source_url"),
    }


_SELECT = (
    "SELECT e.*, v.name AS venue_name, v.address AS venue_address, "
    "       g.code AS genre_code, r.name AS region_name, r.code AS region_code, "
    # When the post behind this event was last collected. A dancer deciding
    # tonight is relying on something we read at some point, and when that was
    # is part of the answer.
    "       i.collected_at AS collected_at "
    "FROM events e "
    "LEFT JOIN venues v ON v.venue_id = e.venue_id "
    "LEFT JOIN genres g ON g.genre_id = e.genre_id "
    "LEFT JOIN regions r ON r.region_id = e.region_id "
    "LEFT JOIN source_items i ON i.source_item_id = e.source_item_id "
)

# Every alpha query starts here. Live, not a duplicate, not hidden.
_VISIBLE = (
    "e.provenance = 'LIVE' "
    "AND e.listing_state = 'LISTED' "
    "AND e.canonical_event_id IS NULL"
)

# What a cancelled event is called in the engine's vocabulary. It stays
# reachable by id -- someone who has the link deserves to learn it is off --
# but it does not belong in a list of places to go.
CANCELLED = "CANCELLED"

# The engine's lifecycle vocabulary is not a reader's. VERIFIED does not mean
# "true", it means "the evidence gate passed", and neither phrase belongs on a
# page someone reads on the way out the door.
STATUS_LABELS = {
    "VERIFIED": "확인됨",
    "POSSIBLE": "확인 필요",
    "EXPECTED": "예정",
    "CONFLICT": "정보 충돌",
    "CANCELLED": "취소",
    "UPDATED": "확인됨",
    "UNKNOWN": "확인 필요",
}

# What kind of night this is, in words a reader uses. The engine's taxonomy
# distinguishes MILONGA from SOCIAL because tango names its social event and
# the other scenes do not; a reader does not need that distinction spelled out,
# only what they are turning up to.
EVENT_TYPE_LABELS = {
    "MILONGA": "밀롱가",
    "MILONGA_WITH_CLASS": "밀롱가 (강습 포함)",
    "PRACTICA": "쁘락띠까",
    "SOCIAL": "소셜",
    "SOCIAL_WITH_CLASS": "소셜 (강습 포함)",
    "PARTY": "파티",
}


# A person looked at this and stood by it. Deliberately worded apart from
# 확인됨: a human review is not the engine's evidence gate, and conflating the
# two would let an approval look like proof.
REVIEWED_LABEL = "관리자 확인"
REVIEWED_STATES = ("APPROVED", "CONFIRMED", "EDITED")


def search(con, *, when: str | None = None, on: Any = None, date_from: Any = None,
           date_to: Any = None, genre: str | None = None,
           genres: "Sequence[str] | None" = None, region: str | None = None,
           status: str | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0,
           include_past: bool = False, include_cancelled: bool = False,
           now: datetime | None = None) -> dict[str, Any]:
    """Events a dancer could go to, soonest first.

    Past and cancelled events are excluded unless asked for. Both still exist,
    both are still reachable by id, and the console can see all of them -- but
    a list of where to dance is about tonight, and last Tuesday is not an
    answer to it.
    """
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

    if not include_past and start is None:
        where.append("e.event_date >= current_date")
    if not include_cancelled:
        where.append("e.engine_status <> %s")
        params.append(CANCELLED)
    if start is not None:
        where.append("e.event_date >= %s")
        params.append(start)
    if end is not None:
        where.append("e.event_date <= %s")
        params.append(end)
    if genre:
        where.append("g.code = %s")
        params.append(genre.strip().upper())
    if genres is not None:
        # An explicit set of genres. An empty set means the reader unchecked
        # everything, which is a real answer -- nothing matches -- and not a
        # reason to quietly show them everything instead.
        codes = [g.strip().upper() for g in genres if g and g.strip()]
        if codes:
            where.append("g.code = ANY(%s)")
            params.append(codes)
        else:
            where.append("false")
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
            "include_past": include_past,
            "include_cancelled": include_cancelled,
            "timezone": "Asia/Seoul",
        },
    }


def get_event(con, event_id: int) -> dict[str, Any] | None:
    """One event, with every post that mentioned it.

    The sources list is the point of keeping duplicates rather than deleting
    them: a reader who wants to check the fee can go and read the post.
    """
    # No date or cancellation filter here on purpose: someone holding the link
    # to a cancelled event should be told it is off, not shown a 404.
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
