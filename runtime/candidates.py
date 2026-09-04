"""Read Event Candidates out of the Information Engine's SQLite store.

Read-only on purpose. v0.75 shows an operator what the engine has produced; the
APPROVE / EDIT / REJECT / DUPLICATE / CONFIRM workflow is v0.76 Human
Verification, and nothing here writes a verdict.

The engine's own tables are the source of truth: `event_candidates` joined to
`raw_posts` for provenance, and `event_instances` for the lifecycle status the
engine has settled on.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .config import Settings
from .engine_adapter import engine_db_path

# The engine's lifecycle vocabulary, reused rather than reinvented.
STATUSES = (
    "EXPECTED",
    "POSSIBLE",
    "VERIFIED",
    "UPDATED",
    "CONFLICT",
    "CANCELLED",
    "UNKNOWN",
)

# Badge colour per status for the admin list. VERIFIED is not something the
# console can hand out - it is shown, never granted, until v0.76.
STATUS_TONE = {
    "VERIFIED": "ok",
    "UPDATED": "ok",
    "EXPECTED": "warn",
    "POSSIBLE": "warn",
    "CONFLICT": "bad",
    "CANCELLED": "bad",
    "UNKNOWN": "muted",
}


class EngineStoreUnavailable(RuntimeError):
    """The engine database is absent or unreadable."""


def _connect(settings: Settings) -> sqlite3.Connection:
    path = engine_db_path(settings)
    if not path.is_file():
        raise EngineStoreUnavailable(f"engine database not present yet: {path}")
    # Read-only URI: the admin console must never mutate engine state.
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def list_candidates(settings: Settings, *, limit: int = 200) -> list[dict[str, Any]]:
    """Recent Event Candidates with their source provenance."""
    try:
        con = _connect(settings)
    except EngineStoreUnavailable:
        return []
    try:
        rows = con.execute(
            """
            SELECT c.candidate_id,
                   c.name        AS event_name,
                   c.event_date,
                   c.start_time,
                   c.end_time,
                   c.venue,
                   c.event_type,
                   c.status      AS candidate_status,
                   c.fee,
                   p.post_id,
                   p.source_id,
                   p.source_url,
                   p.title       AS post_title,
                   p.collected_at,
                   p.cafe_name
            FROM event_candidates c
            LEFT JOIN raw_posts p ON p.post_id = c.post_id
            ORDER BY p.collected_at DESC, c.candidate_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.Error as exc:  # schema drift must not 500 the console
        raise EngineStoreUnavailable(str(exc)) from exc
    finally:
        con.close()

    candidates = []
    for row in rows:
        item = dict(row)
        status = (item.get("candidate_status") or "UNKNOWN").upper()
        item["candidate_status"] = status if status in STATUSES else "UNKNOWN"
        item["status_tone"] = STATUS_TONE.get(item["candidate_status"], "muted")
        candidates.append(item)
    return candidates


# --- DB-level review pagination (v0.81.2) ------------------------------------
#
# list_candidates(limit=300) fetched the newest N posts and left every filter,
# sort and page cut to Python over whatever fell inside that window - so an
# "upcoming" event whose post was collected before the newest 300 could never
# be seen, no matter how urgent review_priority() would have ranked it. query()
# below pushes the filter and the sort into the SQL itself and pages with a
# real LIMIT/OFFSET, so nothing above row 300 is invisible; the corresponding
# indexes are added in engine/src/database.py.
#
# Filters that need PENDING/reviewed status also need candidate_review_state,
# which lives in Postgres, not this SQLite file - see reviewed_candidate_ids().

# Mirrors runtime/admin_pages.py:REVIEW_FILTERS. Each entry is the extra SQL
# WHERE fragment for that filter; "pending"/"reviewed" are handled separately
# in query() because they need the Postgres-side id set.
_UPCOMING = "c.event_date IS NOT NULL AND date(c.event_date) >= date(?)"
_FILTER_WHERE: dict[str, str] = {
    "upcoming": _UPCOMING,
    "today": "c.event_date IS NOT NULL AND date(c.event_date) = date(?)",
    "tomorrow": "c.event_date IS NOT NULL AND date(c.event_date) = date(?, '+1 day')",
    "week": "c.event_date IS NOT NULL AND date(c.event_date) BETWEEN date(?) AND date(?, '+7 day')",
    "conflict": "c.status IN ('CONFLICT', 'UNKNOWN')",
    "unknown_time": f"({_UPCOMING}) AND (c.start_time IS NULL OR c.start_time = '')",
    "unknown_venue": f"({_UPCOMING}) AND (c.venue IS NULL OR c.venue = '')",
    "unknown_fee": f"({_UPCOMING}) AND c.fee IS NULL",
    "all": "1=1",
}

# One bound `?` per `?` placeholder in the fragment above, in order, all the
# same `today` value except "week"'s second bound.
_FILTER_PARAM_COUNT = {
    "upcoming": 1, "today": 1, "tomorrow": 1, "week": 2, "conflict": 0,
    "unknown_time": 1, "unknown_venue": 1, "unknown_fee": 1, "all": 0,
}

# review_priority()'s tuple, translated to ORDER BY. "Missing sorts first" is
# not a bug: a row missing a critical field needs a human sooner than a
# complete one, so CASE gives 0 (sorts first) exactly when the field is absent
# - matching admin_pages.review_priority()'s `0 if not row.get(...) else 1`.
#
# review_priority()'s wrong_time signal (a post's own PM/AM marker
# contradicting the extracted time) is intentionally not reproduced here: it
# depends on review_hints.hints(), computed per-row from acquired content that
# lives in Postgres, and was already never active on the *list* page before
# this change (admin_pages._review_rows never populated row["hints"], so
# _has_wrong_time was always False there) - carrying that same behaviour
# forward is not a regression, just not a new capability this query adds.
_ORDER_BY = """
    CASE WHEN c.status IN ('CONFLICT', 'UNKNOWN') THEN 0 ELSE 1 END,
    CASE WHEN c.event_date IS NOT NULL
              AND julianday(date(c.event_date)) - julianday(date(?)) BETWEEN 0 AND 1
         THEN 0 ELSE 1 END,
    CASE WHEN c.start_time IS NULL OR c.start_time = '' THEN 0 ELSE 1 END,
    CASE WHEN c.venue IS NULL OR c.venue = '' THEN 0 ELSE 1 END,
    CASE WHEN c.fee IS NULL THEN 0 ELSE 1 END,
    CASE WHEN c.event_date IS NOT NULL
         THEN julianday(date(c.event_date)) - julianday(date(?))
         ELSE 9999 END,
    p.collected_at DESC,
    c.candidate_id DESC
"""

_SELECT_COLUMNS = """
    c.candidate_id,
    c.name        AS event_name,
    c.event_date,
    c.start_time,
    c.end_time,
    c.venue,
    c.event_type,
    c.status      AS candidate_status,
    c.fee,
    p.post_id,
    p.source_id,
    p.source_url,
    p.title       AS post_title,
    p.collected_at,
    p.cafe_name
"""


class InvalidFilter(ValueError):
    """Not one of the recognised review filter keys."""


def query(
    settings: Settings, *, filter_key: str = "upcoming",
    reviewed_ids: set[int] | None = None, page: int = 1, page_size: int = 50,
    today: str | None = None,
) -> dict[str, Any]:
    """One page of the review queue, filtered and sorted entirely in SQL.

    ``reviewed_ids`` is the set of candidate_ids with a non-PENDING row in
    Postgres's `candidate_review_state` - the caller fetches it once (see
    `runtime/review.reviewed_candidate_ids`) since it does not live in this
    SQLite file. "pending"/"reviewed" filter on membership in that set; every
    other filter never touches it. Returns ``{"rows": [...], "total": N}``.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    if filter_key not in _FILTER_WHERE and filter_key not in ("pending", "reviewed"):
        raise InvalidFilter(f"unknown review filter {filter_key!r}")

    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    page = max(1, page)
    offset = (page - 1) * page_size

    where = "1=1"
    params: list[Any] = []
    if filter_key in _FILTER_WHERE:
        where = _FILTER_WHERE[filter_key]
        params = [today] * _FILTER_PARAM_COUNT[filter_key]
    elif filter_key in ("pending", "reviewed"):
        ids = sorted(reviewed_ids or set())
        placeholders = ",".join("?" for _ in ids) or "NULL"
        if filter_key == "reviewed":
            where = f"c.candidate_id IN ({placeholders})"
            params = list(ids)
        else:  # pending
            where = (
                f"c.candidate_id NOT IN ({placeholders}) "
                "AND c.status IN ('POSSIBLE', 'EXPECTED', 'CONFLICT', 'UNKNOWN')"
            )
            params = list(ids)

    try:
        con = _connect(settings)
    except EngineStoreUnavailable:
        return {"rows": [], "total": 0}
    try:
        total = con.execute(
            f"SELECT count(*) FROM event_candidates c "
            f"LEFT JOIN raw_posts p ON p.post_id = c.post_id WHERE {where}",
            tuple(params),
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {_SELECT_COLUMNS} FROM event_candidates c "
            f"LEFT JOIN raw_posts p ON p.post_id = c.post_id "
            f"WHERE {where} "
            f"ORDER BY {_ORDER_BY} "
            "LIMIT ? OFFSET ?",
            tuple(params) + (today, today, page_size, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        raise EngineStoreUnavailable(str(exc)) from exc
    finally:
        con.close()

    candidates = []
    for row in rows:
        item = dict(row)
        status = (item.get("candidate_status") or "UNKNOWN").upper()
        item["candidate_status"] = status if status in STATUSES else "UNKNOWN"
        item["status_tone"] = STATUS_TONE.get(item["candidate_status"], "muted")
        candidates.append(item)
    return {"rows": candidates, "total": total}


def get(settings: Settings, candidate_id: int) -> dict[str, Any] | None:
    """One candidate by id, however far back it was collected.

    The detail page and the "before" snapshot for an EDIT/APPROVE/etc. audit
    row used to find their candidate by scanning `list_candidates(limit=1000)`
    - a linear search with the same cap problem the list page had, just at
    1000 instead of 300. This is a primary-key lookup instead: no candidate
    is ever unreachable by its own detail URL, however old.
    """
    try:
        con = _connect(settings)
    except EngineStoreUnavailable:
        return None
    try:
        row = con.execute(
            f"SELECT {_SELECT_COLUMNS} FROM event_candidates c "
            "LEFT JOIN raw_posts p ON p.post_id = c.post_id "
            "WHERE c.candidate_id = ?",
            (candidate_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise EngineStoreUnavailable(str(exc)) from exc
    finally:
        con.close()
    if row is None:
        return None
    item = dict(row)
    status = (item.get("candidate_status") or "UNKNOWN").upper()
    item["candidate_status"] = status if status in STATUSES else "UNKNOWN"
    item["status_tone"] = STATUS_TONE.get(item["candidate_status"], "muted")
    return item


def filter_counts(
    settings: Settings, *, reviewed_ids: set[int] | None = None, today: str | None = None,
) -> dict[str, int]:
    """How many candidates match each REVIEW_FILTERS key, for the filter bar.

    One COUNT query per filter - eleven small, indexed queries against a
    local SQLite file, not a network round trip each - rather than fetching
    every candidate to filter in Python, which is the same "read everything
    first" cost `query()` itself was written to remove.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    keys = list(_FILTER_WHERE) + ["pending", "reviewed"]
    out: dict[str, int] = {}
    for key in keys:
        try:
            out[key] = query(
                settings, filter_key=key, reviewed_ids=reviewed_ids,
                page=1, page_size=1, today=today,
            )["total"]
        except EngineStoreUnavailable:
            out[key] = 0
    return out


def counts(settings: Settings) -> dict[str, Any]:
    """Candidate totals for the dashboard. Never raises."""
    try:
        con = _connect(settings)
    except EngineStoreUnavailable as exc:
        return {"available": False, "detail": str(exc), "total": 0, "by_status": {}}
    try:
        total = con.execute("SELECT count(*) FROM event_candidates").fetchone()[0]
        by_status = {
            (row[0] or "UNKNOWN").upper(): row[1]
            for row in con.execute(
                "SELECT status, count(*) FROM event_candidates GROUP BY status"
            ).fetchall()
        }
        posts = con.execute("SELECT count(*) FROM raw_posts").fetchone()[0]
        instances = con.execute("SELECT count(*) FROM event_instances").fetchone()[0]
    except sqlite3.Error as exc:
        return {"available": False, "detail": str(exc), "total": 0, "by_status": {}}
    finally:
        con.close()

    # "Review pending" is everything the engine has not settled as VERIFIED or
    # CANCELLED. v0.76 turns this into a real queue.
    pending = sum(
        count for status, count in by_status.items()
        if status not in ("VERIFIED", "CANCELLED")
    )
    return {
        "available": True,
        "total": total,
        "by_status": by_status,
        "review_pending": pending,
        "raw_posts": posts,
        "event_instances": instances,
    }


def venue_alias_candidates(settings: Settings,
                           candidate_ids: list[int]) -> dict[int, list[str]]:
    """The venue strings the extractor thought worth matching, per candidate.

    Engine v0.74 records these alongside the venue it read: the whole string,
    the name without its bracketed address, and the name inside the brackets.
    Reading them back beats re-deriving them here and drifting from the engine.
    """
    if not candidate_ids:
        return {}
    try:
        con = _connect(settings)
    except EngineStoreUnavailable:
        return {}
    try:
        placeholders = ",".join("?" for _ in candidate_ids)
        rows = con.execute(
            "SELECT candidate_id, value FROM evidences "
            f"WHERE field = 'venue' AND candidate_id IN ({placeholders})",
            tuple(candidate_ids),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()

    found: dict[int, list[str]] = {}
    for row in rows:
        try:
            value = json.loads(row["value"])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("alias_candidates"):
            found[row["candidate_id"]] = [str(a) for a in value["alias_candidates"]]
    return found


def all_candidate_ids(settings: Settings) -> set[int] | None:
    """Every candidate the engine store currently holds, or None if unreadable.

    None and empty mean different things here, and the caller acts on the
    difference: an unreadable store must never be read as "the engine has no
    candidates", which would prune every normalised event.
    """
    try:
        con = _connect(settings)
    except EngineStoreUnavailable:
        return None
    try:
        rows = con.execute("SELECT candidate_id FROM event_candidates").fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return {row["candidate_id"] for row in rows}


def time_evidence(settings: Settings, candidate_ids: list[int]) -> dict[int, str]:
    """How the engine knew which half of the day each time belongs to.

    EXPLICIT when the post carried a PM/오후/저녁 marker, ABSENT when it wrote a
    bare clock and the engine declined to guess. Read back rather than
    re-derived so the reader is told exactly what the extractor decided.
    """
    if not candidate_ids:
        return {}
    try:
        con = _connect(settings)
    except EngineStoreUnavailable:
        return {}
    try:
        placeholders = ",".join("?" for _ in candidate_ids)
        rows = con.execute(
            "SELECT candidate_id, inference FROM evidences "
            f"WHERE field = 'time' AND candidate_id IN ({placeholders})",
            tuple(candidate_ids),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {row["candidate_id"]: row["inference"] for row in rows if row["inference"]}
