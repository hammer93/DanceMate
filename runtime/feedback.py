"""Event Feedback (v0.85.0): a dancer's own signal on one listing.

Three kinds, nothing else: does the listing look right (ACCURATE), wrong
(INCORRECT), or thin (INCOMPLETE). Anonymous, per-event, and read-only from
this module's own point of view - Section 56 is explicit that feedback must
never mutate an event by itself. What an operator does with an open feedback
row (correct the listing through the existing, audited
runtime.review/runtime.normalization path, or leave it) is a human decision
made in the console, same as any other human review action; this module only
records that someone raised a hand and lets the console see the queue.
"""

from __future__ import annotations

from typing import Any

ACCURATE = "ACCURATE"
INCORRECT = "INCORRECT"
INCOMPLETE = "INCOMPLETE"

KINDS = (ACCURATE, INCORRECT, INCOMPLETE)

LABELS = {
    ACCURATE: "정보가 정확해요",
    INCORRECT: "정보가 달라요",
    INCOMPLETE: "정보가 부족해요",
}


class UnknownKind(ValueError):
    """Not one of ``KINDS``."""


def record(con, *, event_id: int, kind: str) -> dict[str, Any]:
    kind = (kind or "").strip().upper()
    if kind not in KINDS:
        raise UnknownKind(f"unknown feedback kind: {kind!r}")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO event_feedback (event_id, kind) VALUES (%s, %s) "
            "RETURNING feedback_id, event_id, kind, created_at",
            (event_id, kind),
        )
        row = cur.fetchone()
    return {
        "feedback_id": row[0], "event_id": row[1],
        "kind": row[2], "created_at": row[3].isoformat(),
    }


def count_open(con) -> int:
    with con.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_feedback WHERE resolved_at IS NULL")
        return cur.fetchone()[0]


def counts_by_kind(con, *, open_only: bool = True) -> dict[str, int]:
    where = "WHERE resolved_at IS NULL" if open_only else ""
    with con.cursor() as cur:
        cur.execute(f"SELECT kind, count(*) FROM event_feedback {where} GROUP BY kind")
        found = dict(cur.fetchall())
    return {kind: found.get(kind, 0) for kind in KINDS}


def recent(con, *, limit: int = 50, open_only: bool = True) -> list[dict[str, Any]]:
    """Open feedback with the event it is about, newest first - the queue an
    admin dashboard reads (Section 78)."""
    where = "WHERE f.resolved_at IS NULL" if open_only else ""
    with con.cursor() as cur:
        cur.execute(
            "SELECT f.feedback_id, f.event_id, f.kind, f.created_at, f.resolved_at, "
            "       e.event_name, e.event_date "
            "FROM event_feedback f JOIN events e ON e.event_id = f.event_id "
            f"{where} ORDER BY f.created_at DESC LIMIT %s",
            (limit,),
        )
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def resolve(con, feedback_id: int) -> bool:
    """Mark one row read/acted-on. Never touches the event itself."""
    with con.cursor() as cur:
        cur.execute(
            "UPDATE event_feedback SET resolved_at = now() "
            "WHERE feedback_id = %s AND resolved_at IS NULL",
            (feedback_id,),
        )
        return cur.rowcount > 0
