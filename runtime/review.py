"""Human Verification: what a person decided about a candidate.

Kept deliberately separate from the Information Engine's own lifecycle status.
The engine decides EXPECTED / POSSIBLE / VERIFIED / CONFLICT from evidence; a
person decides whether the extracted event is usable. Those are different
judgements and this module never conflates them:

    APPROVE   the extracted content is usable as it stands
    EDIT      a person corrected fields, and both versions are kept
    REJECT    not an event, or the wrong candidate
    DUPLICATE this candidate describes the same event as another
    CONFIRM   a person has explicitly checked the evidence and stands by it

**APPROVE does not grant VERIFIED.** Nothing here writes to the engine's store.
The engine's evidence gate is the only thing that sets VERIFIED, and a human
approval is recorded alongside it, not instead of it.

Nothing is ever deleted. A rejected candidate is the raw material for finding
out why the collector or the extractor got it wrong.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

APPROVE = "APPROVE"
EDIT = "EDIT"
REJECT = "REJECT"
DUPLICATE = "DUPLICATE"
CONFIRM = "CONFIRM"

ACTIONS = (APPROVE, EDIT, REJECT, DUPLICATE, CONFIRM)

# Review state after each action.
STATE_BY_ACTION = {
    APPROVE: "APPROVED",
    EDIT: "EDITED",
    REJECT: "REJECTED",
    DUPLICATE: "DUPLICATE",
    CONFIRM: "CONFIRMED",
}

PENDING = "PENDING"

# Fields a person may correct. Deliberately the decision fields an event needs
# to be usable, not everything the engine stores.
EDITABLE_FIELDS = (
    "event_name",
    "event_date",
    "start_time",
    "end_time",
    "venue",
    "fee",
    "genre",
    "organizer",
    "notes",
)

# Engine statuses that still want a human to look at them. CANCELLED is
# excluded: the engine has already settled it and re-queueing it would bury the
# candidates that actually need attention.
REVIEWABLE_ENGINE_STATUSES = ("POSSIBLE", "EXPECTED", "CONFLICT", "UNKNOWN")


class ReviewError(ValueError):
    """The action cannot be recorded as asked."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _clean(fields: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only editable fields, with blanks normalised to None."""
    if not fields:
        return {}
    cleaned: dict[str, Any] = {}
    for key in EDITABLE_FIELDS:
        if key not in fields:
            continue
        value = fields[key]
        if isinstance(value, str):
            value = value.strip() or None
        cleaned[key] = _json_safe(value)
    return cleaned


def _row(cur) -> dict[str, Any] | None:
    columns = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(columns, row))


def _rows(cur) -> list[dict[str, Any]]:
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def state(con, candidate_id: int) -> dict[str, Any]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM candidate_review_state WHERE candidate_id = %s", (candidate_id,)
        )
        found = _row(cur)
    return found or {
        "candidate_id": candidate_id,
        "review_state": PENDING,
        "last_action": None,
        "last_reviewer": None,
        "last_review_at": None,
        "corrected_json": {},
        "duplicate_of_candidate_id": None,
        "action_count": 0,
    }


def states(con, candidate_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not candidate_ids:
        return {}
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM candidate_review_state WHERE candidate_id = ANY(%s)",
            (candidate_ids,),
        )
        return {row["candidate_id"]: row for row in _rows(cur)}


def record(
    con, *, candidate_id: int, action: str, reviewer: str = "admin",
    before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
    reason: str | None = None, source_item_id: int | None = None,
    duplicate_of_candidate_id: int | None = None,
) -> dict[str, Any]:
    """Record one human action and update the candidate's review state."""
    if action not in ACTIONS:
        raise ReviewError(f"unknown action {action!r}; expected one of {', '.join(ACTIONS)}")
    if action == DUPLICATE:
        if duplicate_of_candidate_id is None:
            raise ReviewError("DUPLICATE needs the candidate this one duplicates")
        if duplicate_of_candidate_id == candidate_id:
            raise ReviewError("a candidate cannot be a duplicate of itself")

    before_fields = _clean(before)
    after_fields = _clean(after) if action == EDIT else {}
    if action == EDIT and not after_fields:
        raise ReviewError("EDIT needs at least one corrected field")
    if action == EDIT and after_fields == {k: before_fields.get(k) for k in after_fields}:
        raise ReviewError("EDIT changed nothing")

    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO human_review_actions (candidate_id, source_item_id, action, "
            "  reviewer, reason, before_json, after_json, duplicate_of_candidate_id) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) RETURNING *",
            (candidate_id, source_item_id, action, reviewer, reason,
             json.dumps(before_fields, ensure_ascii=False, default=str),
             json.dumps(after_fields, ensure_ascii=False, default=str),
             duplicate_of_candidate_id),
        )
        recorded = _row(cur)

    current = state(con, candidate_id)
    corrected = dict(current.get("corrected_json") or {})
    if action == EDIT:
        corrected.update(after_fields)

    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO candidate_review_state (candidate_id, review_state, last_action, "
            "  last_reviewer, last_review_at, corrected_json, duplicate_of_candidate_id, "
            "  action_count, updated_at) "
            "VALUES (%s, %s, %s, %s, now(), %s::jsonb, %s, 1, now()) "
            "ON CONFLICT (candidate_id) DO UPDATE SET "
            "  review_state = EXCLUDED.review_state, last_action = EXCLUDED.last_action, "
            "  last_reviewer = EXCLUDED.last_reviewer, last_review_at = now(), "
            "  corrected_json = EXCLUDED.corrected_json, "
            "  duplicate_of_candidate_id = COALESCE(EXCLUDED.duplicate_of_candidate_id, "
            "                                       candidate_review_state.duplicate_of_candidate_id), "
            "  action_count = candidate_review_state.action_count + 1, updated_at = now()",
            (candidate_id, STATE_BY_ACTION[action], action, reviewer,
             json.dumps(corrected, ensure_ascii=False, default=str),
             duplicate_of_candidate_id),
        )
    return recorded


def history(con, candidate_id: int) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM human_review_actions WHERE candidate_id = %s "
            "ORDER BY created_at DESC, review_action_id DESC",
            (candidate_id,),
        )
        return _rows(cur)


def recent(con, *, limit: int = 50) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM human_review_actions ORDER BY review_action_id DESC LIMIT %s",
            (limit,),
        )
        return _rows(cur)


def metrics(con) -> dict[str, Any]:
    """Counts for the dashboard: what has a person done today?"""
    with con.cursor() as cur:
        cur.execute(
            "SELECT action, count(*) FROM human_review_actions "
            "WHERE created_at::date = current_date GROUP BY action"
        )
        today = dict(cur.fetchall())
        cur.execute("SELECT review_state, count(*) FROM candidate_review_state GROUP BY review_state")
        by_state = dict(cur.fetchall())
        cur.execute("SELECT count(*) FROM human_review_actions")
        total_actions = cur.fetchone()[0]
    return {
        "today": {action: today.get(action, 0) for action in ACTIONS},
        "by_state": by_state,
        "reviewed_candidates": sum(by_state.values()),
        "total_actions": total_actions,
    }


def apply_corrections(candidate: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Overlay a person's corrections onto an engine candidate for display.

    The engine's own values are kept under ``engine_*`` so the console can show
    both, which is the whole point of recording an EDIT rather than overwriting.
    """
    corrected = dict(review.get("corrected_json") or {})
    merged = dict(candidate)
    field_map = {
        "event_name": "event_name",
        "event_date": "event_date",
        "start_time": "start_time",
        "end_time": "end_time",
        "venue": "venue",
        "fee": "fee",
    }
    for review_field, candidate_field in field_map.items():
        if review_field in corrected and corrected[review_field] is not None:
            merged[f"engine_{candidate_field}"] = candidate.get(candidate_field)
            merged[candidate_field] = corrected[review_field]
            merged.setdefault("corrected_fields", []).append(candidate_field)
    for extra in ("genre", "organizer", "notes"):
        if corrected.get(extra) is not None:
            merged[extra] = corrected[extra]
            merged.setdefault("corrected_fields", []).append(extra)
    return merged
