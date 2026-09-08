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

import re
import urllib.parse
from datetime import date, datetime, time, timedelta
from collections.abc import Sequence
from typing import Any
from zoneinfo import ZoneInfo

from . import source_priority, venue_resolution

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


def week_window(offset: int = 0, *, now: datetime | None = None) -> tuple[date, date]:
    """Monday through Sunday for the week ``offset`` weeks from this one.

    ``offset=0`` is this week (today's own Monday-Sunday, even when today is
    itself a Sunday - a week already three-quarters gone is still this week,
    not last week, the same "still ahead of you" reasoning ``window()``
    already applies to ``this_week``). Monday-start per Section 41: this
    product's own dates are Asia/Seoul and its own readers are; ISO's own
    Monday-start week is the one that matches how a Korean calendar app
    already lays a week out, and there is no existing Sunday-start
    convention anywhere else in this codebase to stay consistent with.
    """
    start = today(now)
    monday = start - timedelta(days=start.weekday()) + timedelta(weeks=offset)
    return monday, monday + timedelta(days=6)


def week_counts(con, *, start: date, end: date, genre: str | None = None,
                genres: "Sequence[str] | None" = None,
                region: str | None = None) -> dict[str, int]:
    """One distinct-event count per day in ``[start, end]``, zero-filled.

    Never floors at today (Section 35-37): a week's Monday may already be
    behind us, and a past day's count is exactly as real as tomorrow's -
    the whole reason the weekly calendar keeps history instead of only
    showing what is upcoming. "Distinct" costs nothing extra here: every row
    ``_VISIBLE`` returns is already the one canonical, listed row for its
    event (Section 47) - a duplicate merged into it was hidden, not counted,
    by ``duplicates.record_decision()`` long before this query runs.
    """
    where = [_VISIBLE, "e.engine_status <> %s", "e.event_date BETWEEN %s AND %s"]
    params: list[Any] = [CANCELLED, start, end]
    if genre:
        where.append("g.code = %s")
        params.append(genre.strip().upper())
    if genres is not None:
        codes = [g.strip().upper() for g in genres if g and g.strip()]
        if codes:
            where.append("g.code = ANY(%s)")
            params.append(codes)
        else:
            where.append("false")
    if region:
        region_value = region.strip()
        guess_terms = venue_resolution.terms_for_label(region_value)
        if guess_terms:
            placeholders = " OR ".join(["e.venue_text ILIKE %s"] * len(guess_terms))
            where.append(
                f"(r.code = %s OR r.name ILIKE %s "
                f"OR (e.region_id IS NULL AND ({placeholders})))"
            )
            params.extend([region_value.upper(), region_value])
            params.extend(f"%{term}%" for term in guess_terms)
        else:
            where.append("(r.code = %s OR r.name ILIKE %s)")
            params.extend([region_value.upper(), region_value])
    clause = " AND ".join(where)

    with con.cursor() as cur:
        cur.execute(
            "SELECT e.event_date, count(*) FROM events e "
            "LEFT JOIN genres g ON g.genre_id = e.genre_id "
            "LEFT JOIN regions r ON r.region_id = e.region_id "
            f"WHERE {clause} GROUP BY 1",
            tuple(params),
        )
        found = {row[0].isoformat(): row[1] for row in cur.fetchall()}

    counts: dict[str, int] = {}
    day = start
    while day <= end:
        key = day.isoformat()
        counts[key] = found.get(key, 0)
        day += timedelta(days=1)
    return counts


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


# A reader never sees the internal platform code or a source's operational
# registration name (e.g. "외부홍보게시판(파티)") - this is the brand a person
# would recognise instead. A WEB source has no such brand of its own here, so
# it falls through to the source's own registered name (e.g. "K-TANGO").
PLATFORM_LABELS = {
    "DAUM_CAFE": "Daum Cafe",
    "NAVER_CAFE": "Naver Cafe",
    "NAVER_BLOG": "Naver Blog",
    "NAVER_WEB": "Naver",
    "FACEBOOK": "Facebook",
}


def source_label(platform: str | None, name: str | None) -> str | None:
    """The friendly label a reader sees for where an event's post came from.

    v0.85.4: a source's own real name (e.g. "Solo Tango 화요정모 공지") is
    what identifies it to a reader - PLATFORM_LABELS is a last-resort filler
    for the rare row with no name at all, not a default that overrides one.
    Before this, every DAUM_CAFE source read as the generic "출처: Daum
    Cafe" regardless of which cafe post it actually was (Section 26-28).
    """
    return name or PLATFORM_LABELS.get(platform or "") or None


def valid_public_url(url: str | None) -> str | None:
    """http(s) only. A malformed or non-web URL is never rendered as a link."""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return url


# v0.85.4 (Section 18-30, 41-43, 56-57): a source's own *collection* target
# (what the collector fetches - a JSON API in these two cases) is not what a
# reader should be sent to when they tap "출처" (Section 23). Both patterns
# below are pure string rewrites of the already-stored source_url - no
# network call, so this costs nothing at render time (Section 43-44).
#
# Tango Calendar Korea (SRC-W-003) stores its own API detail endpoint
# (".../api/events/{uuid}") as source_url. The site's own sitemap.xml
# declares "{origin}/?eventId={uuid}" as the canonical, crawlable page for
# that same event (confirmed live: sitemap.xml lists exactly this shape with
# lastmod/changefreq/priority for dozens of real events) - so the rewrite
# below is not a guess, it is the operator's own declared URL for the page.
_TANGOCALENDAR_API_DETAIL = re.compile(
    r"^(https?://[^/]+)/api/events/([0-9a-fA-F-]{36})/?(?:\?.*)?$"
)

# TangoNOW (SRC-W-002) stores a raw Firestore REST document URL as
# source_url. tangonow_discovery.py's own eventsBundle investigation (kept
# in that module's docstring) already found that ~80% of that source's own
# records carry no link/sourceLink field at all and that ktnow.kr's
# frontend is JS-only with no per-event route to recover one - there is no
# real per-event human page to rewrite to, so the only honest fallback is
# the source's own home page (Section 25's own prescribed fallback order).
_FIRESTORE_DOCUMENT = re.compile(r"^https?://firestore\.googleapis\.com/")
_HOME_PAGE_FALLBACK = {
    "firestore": "https://ktnow.kr/",
}


def resolve_public_source_url(url: str | None) -> str | None:
    """The human page a reader should be sent to, never the collector's own
    API endpoint (Section 18-30). Pattern-matches the stored source_url only
    - never fetches anything - so an already-human URL (Daum Cafe, Miltang,
    DanceInfo, TangoClass's own WordPress `link`) passes through unchanged.
    """
    if not url:
        return None
    match = _TANGOCALENDAR_API_DETAIL.match(url)
    if match:
        return f"{match.group(1)}/?eventId={match.group(2)}"
    if _FIRESTORE_DOCUMENT.match(url):
        return _HOME_PAGE_FALLBACK["firestore"]
    return url


# v0.85.7 (Section 31-42): a Naver Maps *search* URL, never a geocoding
# API call - the address is only ever handed to the same search box a
# person would type into themselves. Deterministic and stateless: the
# same address always produces the same URL, so nothing is stored.
_NAVER_MAP_SEARCH = "https://map.naver.com/p/search/{query}?c=15.00,0,0,0,dh"


def build_naver_map_search_url(address: str | None) -> str | None:
    """A Naver Map search link for a real venue address, or None.

    None/empty/whitespace-only in, None out - never a link with nowhere
    real to go. The full raw address is expected (never the display-
    compacted one): whatever venues.address actually says, URL-encoded
    with the standard library, nothing hand-rolled.
    """
    if not address or not address.strip():
        return None
    return _NAVER_MAP_SEARCH.format(query=urllib.parse.quote(address.strip()))


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
            "map_url": build_naver_map_search_url(row.get("venue_address")),
        },
        "fee": row.get("fee"),
        "currency": "KRW" if row.get("fee") is not None else None,
        # Full text for a fee that means more than one plain number - a
        # conditional discount or a set of named options (v0.85.9,
        # Section 18). None for an ordinary single price.
        "fee_display_text": row.get("fee_display_text"),
        "dj": row.get("dj"),
        "event_type": row.get("event_type"),
        "event_type_label": EVENT_TYPE_LABELS.get(
            (row.get("event_type") or "").upper()),
        # The code is the API's contract and what ?genre= filters on; the
        # label is what a page shows a reader. Both, rather than a choice.
        "genre": row.get("genre_code"),
        "genre_label": row.get("genre_name") or row.get("genre_code"),
        # A resolved venue's own region always wins. Otherwise a best-effort,
        # non-authoritative label read straight off the raw venue string
        # (venue_resolution.guess_region_label()'s own docstring has the
        # full v0.82.4 reasoning) - never None just because nobody has
        # resolved the venue yet, so a reader is not shown a blank region.
        "region": row.get("region_name") or venue_resolution.guess_region_label(
            row.get("venue_text")),
        "region_code": row.get("region_code"),
        "region_confirmed": row.get("region_name") is not None,
        "status": row.get("engine_status"),
        "status_label": STATUS_LABELS.get(
            (row.get("engine_status") or "").upper(), "확인 필요"),
        "cancelled": (row.get("engine_status") or "").upper() == CANCELLED,
        "reviewed": row.get("review_state"),
        "human_reviewed": (row.get("review_state") or "").upper() in REVIEWED_STATES,
        "last_checked": (row["collected_at"].isoformat()
                         if row.get("collected_at") else None),
        "source_url": row.get("source_url"),
        # The representative source for THIS event row specifically - never a
        # different event's post. Rule: the event's own directly-linked
        # source_item (normalization.source_of's URL match), which is what
        # source_item_id / source_url already denormalize onto every event
        # row. No fallback: a missing URL means no link, not a guessed one.
        "source_link": {
            "url": valid_public_url(resolve_public_source_url(row.get("source_url"))),
            "label": source_label(row.get("source_platform"), row.get("source_name")),
        },
        # v0.85.0: which tier this event's own source falls into (Section 5/8)
        # - a display/ranking signal derived from sources.source_role, never
        # a claim about verification. See runtime.source_priority's own
        # docstring for the exact role->tier mapping.
        "source_tier": source_priority.tier_of(row.get("source_source_role")),
        "source_tier_label": source_priority.label_of(row.get("source_source_role")),
    }


_SELECT = (
    "SELECT e.*, v.name AS venue_name, v.address AS venue_address, "
    "       g.code AS genre_code, g.name AS genre_name, "
    "       r.name AS region_name, r.code AS region_code, "
    # When the post behind this event was last collected. A dancer deciding
    # tonight is relying on something we read at some point, and when that was
    # is part of the answer.
    "       i.collected_at AS collected_at, "
    # The event's own source, for a reader who wants to check the original
    # post — not "every post that ever mentioned this event" (get_event's
    # duplicates.sources_of does that on the detail page), just this row's.
    "       src.name AS source_name, src.platform AS source_platform, "
    "       src.source_role AS source_source_role "
    "FROM events e "
    "LEFT JOIN venues v ON v.venue_id = e.venue_id "
    "LEFT JOIN genres g ON g.genre_id = e.genre_id "
    "LEFT JOIN regions r ON r.region_id = e.region_id "
    "LEFT JOIN source_items i ON i.source_item_id = e.source_item_id "
    "LEFT JOIN sources src ON src.source_id = i.source_id "
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
#
# v0.84.0: UPDATED used to share VERIFIED's label ("확인됨"), which told a
# reader an event whose details just changed was the same kind of settled as
# one the evidence gate actually passed - a real Section 11 defect once
# UPDATED starts firing (it does not yet - production has only ever written
# POSSIBLE and VERIFIED - but the label has to be right before it does, not
# after someone reads a changed fee as confirmed). COMPLETED was missing
# outright and fell back to "확인 필요", which is backwards for an event
# that has already happened.
STATUS_LABELS = {
    "VERIFIED": "확인됨",
    "POSSIBLE": "확인 필요",
    "EXPECTED": "예정",
    "CONFLICT": "정보 충돌",
    "CANCELLED": "취소",
    "UPDATED": "변경됨",
    "COMPLETED": "종료",
    "UNKNOWN": "확인 필요",
}

# The one-line explanation behind the VERIFIED badge (Section 12): what the
# evidence gate means, not how it works. Surfaced as a `title` attribute
# rather than a paragraph - a reader who wants more can hover or long-press,
# nobody else has to read past the badge itself.
VERIFIED_EXPLANATION = "공식/신뢰 가능한 근거에서 날짜·시간·가격이 같은 행사 문맥으로 확인됨"

# An event the engine has marked as already having happened. Section 22:
# excluded from the default upcoming list for the same reason CANCELLED is -
# it stays reachable by id, but it is not an answer to "where can I dance".
COMPLETED = "COMPLETED"

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
           include_completed: bool = False,
           now: datetime | None = None) -> dict[str, Any]:
    """Events a dancer could go to, soonest first.

    Past, cancelled, and completed events are excluded unless asked for. All
    three still exist, all three are still reachable by id, and the console
    can see all of them -- but a list of where to dance is about tonight, and
    last Tuesday (or a milonga that already ended) is not an answer to it.
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
        where.append("e.event_date >= %s")
        params.append(today(now))
    if not include_cancelled:
        where.append("e.engine_status <> %s")
        params.append(CANCELLED)
    if not include_completed:
        where.append("e.engine_status <> %s")
        params.append(COMPLETED)
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
        region_value = region.strip()
        # An unresolved event (region_id NULL) matches too, by the same raw
        # substring guess_region_label() itself uses for display - so
        # selecting "청주" actually returns the real Cheongju milongas, not
        # just the (currently zero) ones with a resolved venue.
        guess_terms = venue_resolution.terms_for_label(region_value)
        if guess_terms:
            placeholders = " OR ".join(["e.venue_text ILIKE %s"] * len(guess_terms))
            where.append(
                f"(r.code = %s OR r.name ILIKE %s "
                f"OR (e.region_id IS NULL AND ({placeholders})))"
            )
            params.extend([region_value.upper(), region_value])
            params.extend(f"%{term}%" for term in guess_terms)
        else:
            where.append("(r.code = %s OR r.name ILIKE %s)")
            params.extend([region_value.upper(), region_value])
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
            # a time we do not have should not outrank one we do. Source
            # directness (Section 9: "보조 ranking", a tiebreak, never a
            # reason to reorder across dates or times) settles same-date-
            # same-time ties only - this CASE mirrors source_priority.rank()
            # exactly (see that module's own role sets); a test asserts the
            # two never drift apart.
            " ORDER BY e.event_date, e.start_time NULLS LAST, "
            "CASE src.source_role "
            "  WHEN 'ORGANIZER' THEN 0 WHEN 'VENUE' THEN 0 WHEN 'COMMUNITY' THEN 0 "
            "  WHEN 'PROMOTION_BOARD' THEN 1 "
            "  ELSE 2 END, "
            "e.event_id "
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
            "include_completed": include_completed,
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
            "url": valid_public_url(resolve_public_source_url(source["source_url"])),
            "event_name": source["event_name"],
            "is_canonical": source["is_canonical"],
        }
        for source in duplicates.sources_of(con, event_id)
        if source["source_url"]
    ]
    return event
