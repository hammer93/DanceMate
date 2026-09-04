"""What the pipeline observes about a source, and what a person decided about it.

Those are two different facts and the console kept conflating them. "This cafe
serves articles only to a logged-in reader" is an observation the fetcher makes
every hour. "Replace it — the new salsa cafes cover the same ground" is a
judgement somebody made once and should not have to remember or re-derive.

So the observation stays where it is, in the fetch outcomes, and the decision
gets a column. A recommendation is offered beside it, with the numbers behind
it, and nothing is applied automatically: a community that fixes its settings
next week should not have been dropped this week.
"""

from __future__ import annotations

from typing import Any

from . import sources

ACTIVE = "ACTIVE"
KEEP = "KEEP"
REPLACE = "REPLACE"
DISABLE = "DISABLE"
MONITOR = "MONITOR"

DECISIONS = (ACTIVE, KEEP, REPLACE, DISABLE, MONITOR)

LABELS = {
    ACTIVE: "정상 — 계속 수집",
    KEEP: "유지 — 대체가 없다",
    REPLACE: "교체 — 같은 영역을 더 잘 덮는 소스가 있다",
    DISABLE: "중단 — 수집을 멈춘다",
    MONITOR: "관찰 — 판단 보류, 나중에 다시 본다",
}

TONES = {
    ACTIVE: "ok", KEEP: "warn", REPLACE: "warn", DISABLE: "bad", MONITOR: "muted",
}


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def event_breakdown(con, source_id: int) -> dict[str, int]:
    """Upcoming / past / no-event / blocked-body counts for one source
    (v0.82 Source Transparency) - a source's detail page, not its list row,
    since this is a per-source query.

    Two queries rather than one multi-join: events and source_item_content
    are both joined off source_items, and a source_item can carry more than
    one event (a multi-program post), so one query joining both would fan
    out and double-count the content-side (blocked) figure.

    "no_event" is an approximation, not the engine's own classification: an
    ingested item with no events row could be a real non-event post (a
    class advert, a season-ticket notice) or one with no extractable date -
    the engine does not report that distinction back to Postgres. Read as
    "produced nothing", not as a precise rejection reason.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT "
            "  count(*) FILTER (WHERE e.provenance='LIVE' AND e.listing_state='LISTED' "
            "    AND e.canonical_event_id IS NULL AND e.event_date >= current_date) AS upcoming, "
            "  count(*) FILTER (WHERE e.provenance='LIVE' AND e.listing_state='LISTED' "
            "    AND e.canonical_event_id IS NULL AND e.event_date < current_date) AS past, "
            "  count(*) FILTER (WHERE e.event_id IS NULL) AS no_event "
            "FROM source_items i LEFT JOIN events e ON e.source_item_id = i.source_item_id "
            "WHERE i.source_id = %s AND i.ingest_state = 'INGESTED'",
            (source_id,),
        )
        cols = [c.name for c in cur.description]
        first = dict(zip(cols, cur.fetchone()))
        cur.execute(
            "SELECT count(*) FILTER (WHERE c.acquisition_status IN ('FETCH_BLOCKED', 'LOGIN_REQUIRED')) "
            "FROM source_items i LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
            "WHERE i.source_id = %s",
            (source_id,),
        )
        blocked = cur.fetchone()[0] or 0
    first["blocked"] = blocked
    return first


def upcoming_yield(con) -> dict[int, int]:
    """Upcoming listed events per source.

    The number that matters. A hundred past events and one upcoming is a source
    worth keeping; a hundred past events and none upcoming is a source that has
    stopped being useful, and no total tells them apart.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT i.source_id, count(*) AS upcoming "
            "FROM events e JOIN source_items i ON i.source_item_id = e.source_item_id "
            "WHERE e.provenance = 'LIVE' AND e.listing_state = 'LISTED' "
            "  AND e.canonical_event_id IS NULL AND e.event_date >= current_date "
            "GROUP BY i.source_id"
        )
        return {row["source_id"]: row["upcoming"] for row in _rows(cur)}


def recommend(source: dict[str, Any], outcome: dict[str, Any],
              alternatives: int = 0) -> tuple[str, str]:
    """A suggested decision and the reason for it, from the numbers alone.

    Offered, never applied. The operator sees the counts that produced it, so
    they can disagree with the suggestion rather than with a black box.
    """
    items = outcome.get("items", 0) or 0
    fetched = outcome.get("fetched", 0) or 0
    blocked = (outcome.get("blocked", 0) or 0) + (outcome.get("login", 0) or 0)
    events = outcome.get("events", 0) or 0

    if not source.get("enabled"):
        return MONITOR, "사용 중지 상태입니다."
    if (source.get("last_status") or "").upper() == "AUTH_FAILED":
        return MONITOR, "자격증명 문제로 수집되지 않습니다. 외부 조건이라 이번 판단에서 제외합니다."
    if not items:
        return MONITOR, "아직 수집된 항목이 없습니다."
    if fetched == 0 and blocked:
        if alternatives:
            return REPLACE, (
                f"{items}건을 수집했지만 본문을 하나도 읽지 못했고(차단 {blocked}), "
                f"같은 장르를 읽어오는 소스가 {alternatives}개 있습니다."
            )
        return KEEP, (
            f"{items}건을 수집했지만 본문을 하나도 읽지 못했습니다(차단 {blocked}). "
            "다만 이 영역을 덮는 다른 소스가 없습니다."
        )
    if events == 0:
        return MONITOR, f"본문 {fetched}건을 읽었지만 아직 행사가 나오지 않았습니다."
    return ACTIVE, f"본문 {fetched}건, 행사 {events}건."


def overview(con) -> list[dict[str, Any]]:
    """Every source with what it yields and what to do about it."""
    rows = sources.list_sources(con)
    outcomes = sources.acquisition_outcomes(con)
    upcoming = upcoming_yield(con)

    # How many other enabled sources of the same genre are actually readable.
    readable_by_genre: dict[Any, int] = {}
    for source in rows:
        found = outcomes.get(source["source_id"], {})
        if source["enabled"] and (found.get("fetched", 0) or 0) > 0:
            readable_by_genre[source.get("genre_id")] = (
                readable_by_genre.get(source.get("genre_id"), 0) + 1
            )

    out = []
    for source in rows:
        found = outcomes.get(source["source_id"], {})
        alternatives = readable_by_genre.get(source.get("genre_id"), 0)
        if (found.get("fetched", 0) or 0) > 0:
            alternatives = max(0, alternatives - 1)  # do not count itself
        decision, reason = recommend(source, found, alternatives)
        entry = dict(source)
        entry.update({
            "items": found.get("items", 0) or 0,
            "fetched": found.get("fetched", 0) or 0,
            "blocked": (found.get("blocked", 0) or 0) + (found.get("login", 0) or 0),
            "events": found.get("events", 0) or 0,
            "upcoming_events": upcoming.get(source["source_id"], 0),
            "recommended": decision,
            "recommendation_reason": reason,
            "alternatives": alternatives,
        })
        out.append(entry)
    return out


def set_decision(con, source_id: int, decision: str, *, reviewer: str = "admin",
                 reason: str | None = None) -> dict[str, Any] | None:
    """Record what a person decided. Does not enable or disable anything.

    Deliberately separate from the enabled flag: writing down "replace this"
    and actually stopping collection are two steps, and an operator may well
    want the note before the action.
    """
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision {decision!r}; expected one of {', '.join(DECISIONS)}")
    with con.cursor() as cur:
        cur.execute(
            "UPDATE sources SET operational_decision = %s, decision_reason = %s, "
            "  decided_at = now(), decided_by = %s, updated_at = now() "
            "WHERE source_id = %s RETURNING *",
            (decision, (reason or "").strip() or None, reviewer, source_id),
        )
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    return None if row is None else dict(zip(names, row))
