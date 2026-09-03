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
