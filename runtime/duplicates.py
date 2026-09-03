"""Duplicate Resolution: the same milonga posted four times, shown once.

A venue posts it, the organiser posts it, two dancers post it. Four rows for
one Saturday night is a worse answer than one row -- and one row for two
different milongas is worse than four.

So the rules are deterministic and narrow. Auto-merge needs all three of:

    the same date, the same place, and the same start time

with the place being a resolved Venue Master row or an identical venue string,
and the time actually present on both sides. Anything less specific -- same
venue but two hours apart, same time but one venue unknown -- is an open
question recorded for a person. There is no similarity score and no clustering:
a number nobody can check is not a reason to merge two events.

Nothing is deleted. A duplicate keeps its row, its candidate, its source URL,
and points at the canonical event, so "which posts said this?" still has an
answer afterwards.

A person's decision is final. Automation skips any event a human has ruled on,
in either direction, and re-running the scan never revisits it.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

AUTO = "AUTO"
HUMAN = "HUMAN"

DUPLICATE = "DUPLICATE"
DISTINCT = "DISTINCT"

# Auto-merge: every identifying field agrees and none of them is missing.
RULE_SAME_DATE_VENUE_TIME = "SAME_DATE_VENUE_TIME"
# For a person: enough agrees to be suspicious, not enough to act.
RULE_VENUE_TIME_DIFFERS = "SAME_DATE_VENUE_TIME_DIFFERS"
RULE_TIME_NAME_VENUE_DIFFERS = "SAME_DATE_TIME_NAME_VENUE_DIFFERS"

OPEN = "OPEN"
MERGED = "MERGED"


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _row(cur) -> dict[str, Any] | None:
    names = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(names, row))


def completeness(event: dict[str, Any]) -> int:
    """How much of an event this row actually carries.

    Used only to pick which of two identical events is the canonical one, so
    the surviving row is the one a reader learns the most from. It is a tie
    break, never a reason to merge.
    """
    score = 0
    if event.get("venue_status") == "RESOLVED":
        score += 3
    elif event.get("venue_text"):
        score += 1
    if event.get("start_time"):
        score += 1
    if event.get("end_time"):
        score += 1
    if event.get("fee") is not None:
        score += 1
    if (event.get("engine_status") or "").upper() == "VERIFIED":
        score += 1
    if (event.get("review_state") or "").upper() in ("APPROVED", "CONFIRMED", "EDITED"):
        score += 2
    return score


def _canonical_of(left: dict[str, Any], right: dict[str, Any]) -> tuple[dict, dict]:
    """(canonical, duplicate). Deterministic: completeness, then oldest id."""
    ranked = sorted(
        (left, right),
        key=lambda e: (-completeness(e), e["event_id"]),
    )
    return ranked[0], ranked[1]


def _place(event: dict[str, Any]) -> str | None:
    if event.get("venue_id") is not None:
        return f"venue:{event['venue_id']}"
    text = (event.get("venue_text") or "").strip().lower()
    return f"text:{text}" if text else None


def _clock(event: dict[str, Any]) -> str | None:
    value = event.get("start_time")
    return value.strftime("%H:%M") if hasattr(value, "strftime") else (str(value)[:5] or None)


def classify(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """What, if anything, these two events have in common.

    Returns None when they are simply different events -- including the case
    that matters most for a weekly milonga: two instances of one series on two
    dates are not duplicates, however identical everything else looks.
    """
    if left["event_date"] != right["event_date"]:
        return None

    left_place, right_place = _place(left), _place(right)
    left_clock, right_clock = _clock(left), _clock(right)
    same_place = bool(left_place) and left_place == right_place
    same_clock = bool(left_clock) and left_clock == right_clock

    if same_place and same_clock:
        return {
            "rule": RULE_SAME_DATE_VENUE_TIME,
            "auto": True,
            "matched": ["event_date", "venue", "start_time"],
            "differs": [],
        }
    if same_place:
        return {
            "rule": RULE_VENUE_TIME_DIFFERS,
            "auto": False,
            "matched": ["event_date", "venue"],
            "differs": ["start_time"],
        }
    if same_clock and left.get("series_key") and left["series_key"] == right.get("series_key"):
        return {
            "rule": RULE_TIME_NAME_VENUE_DIFFERS,
            "auto": False,
            "matched": ["event_date", "start_time", "series_key"],
            "differs": ["venue"],
        }
    return None


def _decided_by_human(event: dict[str, Any]) -> bool:
    return (event.get("duplicate_decided_by") or "").upper() == HUMAN


def record_decision(con, *, event_id: int, canonical_event_id: int | None,
                    decision: str, decided_by: str, rule: str,
                    reason: str | None = None, reviewer: str | None = None) -> dict[str, Any]:
    """Write one duplicate verdict and update the event to match it."""
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO event_duplicate_decisions (event_id, canonical_event_id, "
            "  decision, decided_by, rule, reason, reviewer) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (event_id, canonical_event_id, decision, decided_by, rule, reason, reviewer),
        )
        recorded = _row(cur)
        if decision == DUPLICATE:
            cur.execute(
                "UPDATE events SET canonical_event_id = %s, duplicate_decided_by = %s, "
                "  listing_state = 'HIDDEN', updated_at = now() WHERE event_id = %s",
                (canonical_event_id, decided_by, event_id),
            )
        else:
            cur.execute(
                "UPDATE events SET canonical_event_id = NULL, duplicate_decided_by = %s, "
                "  listing_state = CASE WHEN review_state IN ('REJECTED', 'DUPLICATE') "
                "                       THEN 'HIDDEN' ELSE 'LISTED' END, "
                "  updated_at = now() WHERE event_id = %s",
                (decided_by, event_id),
            )
    return recorded


def _record_pair(con, left_id: int, right_id: int, finding: dict[str, Any]) -> bool:
    """Park an ambiguous pair for a person. Returns True if it is new."""
    low, high = sorted((left_id, right_id))
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO event_duplicate_pairs (event_id, other_event_id, rule, "
            "  matched, differs) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb) "
            "ON CONFLICT (event_id, other_event_id) DO NOTHING RETURNING pair_id",
            (low, high, finding["rule"],
             json.dumps(finding["matched"]), json.dumps(finding["differs"])),
        )
        return cur.fetchone() is not None


def scan(con, *, on: date | None = None, limit_days: int | None = None) -> dict[str, Any]:
    """Compare events sharing a date and act on what the rules can settle.

    Only events on the same day are ever compared, so the scan stays cheap and
    a weekly series can never collapse into one row.
    """
    where = ["e.review_state <> 'REJECTED'"]
    params: list[Any] = []
    if on is not None:
        where.append("e.event_date = %s")
        params.append(on)
    elif limit_days is not None:
        where.append("e.event_date >= current_date - %s")
        params.append(limit_days)

    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM events e WHERE " + " AND ".join(where) +
            " ORDER BY e.event_date, e.event_id",
            tuple(params),
        )
        events = _rows(cur)

    by_date: dict[Any, list[dict[str, Any]]] = {}
    for event in events:
        by_date.setdefault(event["event_date"], []).append(event)

    merged = 0
    flagged = 0
    compared = 0
    # An event already merged away is not compared again: three posts of one
    # milonga produce one canonical row, not a chain.
    resolved: set[int] = {
        e["event_id"] for e in events if e.get("canonical_event_id") is not None
    }

    for day_events in by_date.values():
        for index, left in enumerate(day_events):
            if left["event_id"] in resolved:
                continue
            for right in day_events[index + 1:]:
                if right["event_id"] in resolved:
                    continue
                compared += 1
                finding = classify(left, right)
                if finding is None:
                    continue
                if _decided_by_human(left) or _decided_by_human(right):
                    # A person has already ruled on one of these. Automation
                    # does not get a second opinion.
                    continue
                if finding["auto"]:
                    canonical, duplicate = _canonical_of(left, right)
                    record_decision(
                        con,
                        event_id=duplicate["event_id"],
                        canonical_event_id=canonical["event_id"],
                        decision=DUPLICATE,
                        decided_by=AUTO,
                        rule=finding["rule"],
                        reason="same date, same venue and same start time",
                    )
                    resolved.add(duplicate["event_id"])
                    merged += 1
                    if duplicate["event_id"] == left["event_id"]:
                        break
                elif _record_pair(con, left["event_id"], right["event_id"], finding):
                    flagged += 1

    return {"events": len(events), "compared": compared,
            "auto_merged": merged, "flagged_for_review": flagged}


def open_pairs(con, *, limit: int = 100) -> list[dict[str, Any]]:
    """Pairs waiting on a person, with both events attached."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT p.*, "
            "  a.event_name AS event_name, a.event_date AS event_date, "
            "  a.start_time AS start_time, a.venue_text AS venue_text, "
            "  a.venue_status AS venue_status, a.source_url AS source_url, "
            "  b.event_name AS other_event_name, b.start_time AS other_start_time, "
            "  b.venue_text AS other_venue_text, b.venue_status AS other_venue_status, "
            "  b.source_url AS other_source_url "
            "FROM event_duplicate_pairs p "
            "JOIN events a ON a.event_id = p.event_id "
            "JOIN events b ON b.event_id = p.other_event_id "
            "WHERE p.state = 'OPEN' ORDER BY a.event_date, p.pair_id LIMIT %s",
            (limit,),
        )
        return _rows(cur)


def resolve_pair(con, pair_id: int, *, decision: str, reviewer: str = "admin",
                 canonical_event_id: int | None = None,
                 reason: str | None = None) -> dict[str, Any]:
    """A person settles an open pair. This overrides and outlasts automation."""
    if decision not in (DUPLICATE, DISTINCT):
        raise ValueError(f"decision must be {DUPLICATE} or {DISTINCT}, got {decision!r}")
    with con.cursor() as cur:
        cur.execute("SELECT * FROM event_duplicate_pairs WHERE pair_id = %s", (pair_id,))
        pair = _row(cur)
    if pair is None:
        raise LookupError(f"no duplicate pair {pair_id}")

    members = (pair["event_id"], pair["other_event_id"])
    if decision == DUPLICATE:
        if canonical_event_id is None:
            with con.cursor() as cur:
                cur.execute("SELECT * FROM events WHERE event_id = ANY(%s)", (list(members),))
                left, right = _rows(cur)
            canonical_event_id = _canonical_of(left, right)[0]["event_id"]
        if canonical_event_id not in members:
            raise ValueError("the canonical event has to be one of the pair")
        duplicate_id = members[0] if members[1] == canonical_event_id else members[1]
        record_decision(
            con, event_id=duplicate_id, canonical_event_id=canonical_event_id,
            decision=DUPLICATE, decided_by=HUMAN, rule="HUMAN_REVIEW",
            reason=reason, reviewer=reviewer,
        )
        new_state = MERGED
    else:
        for event_id in members:
            record_decision(
                con, event_id=event_id, canonical_event_id=None, decision=DISTINCT,
                decided_by=HUMAN, rule="HUMAN_REVIEW", reason=reason, reviewer=reviewer,
            )
        new_state = DISTINCT

    with con.cursor() as cur:
        cur.execute(
            "UPDATE event_duplicate_pairs SET state = %s, resolved_by = %s, "
            "  resolved_at = now() WHERE pair_id = %s",
            (new_state, reviewer, pair_id),
        )
    return {"pair_id": pair_id, "state": new_state,
            "canonical_event_id": canonical_event_id}


def sources_of(con, event_id: int) -> list[dict[str, Any]]:
    """Every post behind an event, its own and its duplicates'.

    This is what merging costs nothing: the canonical row is what a reader
    sees, and all of the provenance is still here.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT event_id, candidate_id, source_item_id, source_url, event_name, "
            "       venue_text, start_time, fee, engine_status, review_state, "
            "       (event_id = %s) AS is_canonical "
            "FROM events WHERE event_id = %s OR canonical_event_id = %s "
            "ORDER BY (event_id = %s) DESC, event_id",
            (event_id, event_id, event_id, event_id),
        )
        return _rows(cur)


def metrics(con) -> dict[str, Any]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE canonical_event_id IS NOT NULL) AS duplicates, "
            "       count(*) FILTER (WHERE canonical_event_id IS NOT NULL "
            "                          AND duplicate_decided_by = 'AUTO') AS auto_merged, "
            "       count(*) FILTER (WHERE duplicate_decided_by = 'HUMAN') AS human_decided, "
            # What a user would actually be shown: live, canonical and listed.
            # Counting every LISTED row here would have claimed 26 on a board
            # showing 15.
            "       count(*) FILTER (WHERE listing_state = 'LISTED' "
            "                          AND canonical_event_id IS NULL "
            "                          AND provenance = 'LIVE') AS listed "
            "FROM events"
        )
        summary = _row(cur)
        cur.execute("SELECT count(*) FROM event_duplicate_pairs WHERE state = 'OPEN'")
        summary["open_pairs"] = cur.fetchone()[0]
    return summary
