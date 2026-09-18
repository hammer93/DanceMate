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

import re
from collections import defaultdict
from typing import Any

from . import source_priority, sources

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


def audit_summary(con, source_id: int) -> dict[str, int]:
    """Items/Events/Date-Missing/Time-Missing/Venue-Missing/Fee-Missing/
    DJ-Missing counts for one source (v0.86.4 Source Audit Workbench,
    Section 51-53).

    Counted against the events this source's own items actually produced,
    not the whole catalogue - "missing" here means the field is absent from
    the extracted/canonical event row. It is deliberately not the same
    thing as `review_hints.hints()`'s "potential miss" (the original text
    *had* something a reviewer should check, extraction did not catch it) -
    that distinction (Section 53) needs the raw body per item and stays a
    per-item, on-demand computation (Item Audit Detail), never this
    source-wide aggregate.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM source_items WHERE source_id = %s",
            (source_id,),
        )
        items = cur.fetchone()[0]
        cur.execute(
            "SELECT "
            "  count(*) AS events, "
            "  count(*) FILTER (WHERE e.event_date IS NULL) AS date_missing, "
            "  count(*) FILTER (WHERE e.start_time IS NULL) AS time_missing, "
            "  count(*) FILTER (WHERE e.venue_id IS NULL) AS venue_missing, "
            "  count(*) FILTER (WHERE e.fee IS NULL) AS fee_missing, "
            "  count(*) FILTER (WHERE e.dj IS NULL) AS dj_missing "
            "FROM events e JOIN source_items i ON i.source_item_id = e.source_item_id "
            "WHERE i.source_id = %s",
            (source_id,),
        )
        cols = [c.name for c in cur.description]
        summary = dict(zip(cols, cur.fetchone()))
    summary["items"] = items
    return summary


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


def evidence_tiers(con) -> dict[str, int]:
    """v0.85.2 KPI (Section 22/23): for every visible upcoming event, which
    source-priority tier(s) exist across it AND its folded-away duplicates -
    not just the representative row's own tier. A folded DIRECTORY post is
    retained evidence (Section 17), and an event carrying both PRIMARY and
    DIRECTORY evidence is the concrete signal that "directory discovery"
    has actually converged into "official confirmation" - the thing this
    whole Direct Source effort is working toward, not just a raw coverage
    percentage.

    Returns counts, NOT mutually exclusive: `primary`/`promotion_board`
    count every event carrying that tier anywhere in its evidence;
    `directory_only` counts events whose evidence is DIRECTORY and nothing
    else; `multi_tier` counts events whose evidence spans more than one
    tier (Section 23's own highlighted case, PRIMARY+DIRECTORY, is a
    subset of this).
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(e.canonical_event_id, e.event_id) AS canonical_id, "
            "       src.source_role "
            "FROM events e "
            "LEFT JOIN source_items si ON si.source_item_id = e.source_item_id "
            "LEFT JOIN sources src ON src.source_id = si.source_id "
            "JOIN events canon ON canon.event_id = COALESCE(e.canonical_event_id, e.event_id) "
            "WHERE canon.provenance = 'LIVE' AND canon.listing_state = 'LISTED' "
            "  AND canon.canonical_event_id IS NULL AND canon.event_date >= current_date "
            "  AND canon.engine_status <> 'CANCELLED'"
        )
        rows = _rows(cur)

    tiers_by_event: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        tiers_by_event[row["canonical_id"]].add(source_priority.tier_of(row["source_role"]))

    result = {"primary": 0, "promotion_board": 0, "directory_only": 0, "multi_tier": 0}
    for tiers in tiers_by_event.values():
        if source_priority.PRIMARY in tiers:
            result["primary"] += 1
        if source_priority.PROMOTION_BOARD in tiers:
            result["promotion_board"] += 1
        if tiers == {source_priority.DIRECTORY}:
            result["directory_only"] += 1
        if len(tiers) > 1:
            result["multi_tier"] += 1
    return result


# --- v0.95.0: yield diagnosis, representative wins, coverage gaps ------------

DIRECT_ROLES = ("COMMUNITY", "ORGANIZER", "VENUE", "PROMOTION_BOARD")

DIAG_DISABLED = "DISABLED"
DIAG_NEVER_RUN = "NEVER_RUN"
DIAG_COLLECTOR_FAILURE = "COLLECTOR_FAILURE"
DIAG_QUERY_TOO_NARROW = "QUERY_TOO_NARROW"
DIAG_BOUNDARY_TOO_STRICT = "BOUNDARY_TOO_STRICT"
DIAG_METADATA_ONLY_NO_EVENT = "METADATA_ONLY_NO_EVENT"
DIAG_NON_EVENT_CONTENT = "NON_EVENT_CONTENT"
DIAG_PAST_ONLY = "PAST_ONLY"
DIAG_HEALTHY = "HEALTHY"

DIAG_LABELS = {
    DIAG_DISABLED: "비활성",
    DIAG_NEVER_RUN: "미실행",
    DIAG_COLLECTOR_FAILURE: "수집 실패",
    DIAG_QUERY_TOO_NARROW: "검색어 부족/활동 없음",
    DIAG_BOUNDARY_TOO_STRICT: "경계 필터로 전부 제외",
    DIAG_METADATA_ONLY_NO_EVENT: "본문 차단·행사 미추출",
    DIAG_NON_EVENT_CONTENT: "글은 있으나 행사 아님",
    DIAG_PAST_ONLY: "지난 행사만",
    DIAG_HEALTHY: "정상",
}

_SEARCH_HITS = re.compile(r"(\d+) search hits")
_OK_RUN = frozenset({"PASS", "SNAPSHOT"})


def yield_diagnosis(source: dict[str, Any], outcome: dict[str, Any],
                    last_run: dict[str, Any] | None) -> tuple[str, str]:
    """Why a source yields what it yields - one code and one sentence.

    "0 events" is five different situations, and each has a different fix:
    a switched-off source, a collector that fails, a query that finds
    nothing (or a community that has gone quiet), a boundary that rejects
    everything the search did find, posts that exist but announce no event
    (or whose bodies this deployment may not fetch), and a source whose
    events are all in the past. Deterministic, from numbers already stored.
    """
    if not source.get("enabled"):
        return DIAG_DISABLED, "enable and Test before expecting anything"
    if last_run is None:
        return DIAG_NEVER_RUN, "the scheduler has not collected from it yet"
    if (last_run.get("status") or "").upper() not in _OK_RUN:
        return DIAG_COLLECTOR_FAILURE, f"last run {last_run.get('status')}: {last_run.get('error') or '-'}"
    items = int(outcome.get("items", 0) or 0)
    if int(last_run.get("discovered_count") or 0) == 0 and items == 0:
        hits = _SEARCH_HITS.search(source.get("last_detail") or "")
        if hits and int(hits.group(1)) > 0:
            return DIAG_BOUNDARY_TOO_STRICT, (
                f"{hits.group(1)} search hits, none inside cafe_name_hint/url_contains")
        return DIAG_QUERY_TOO_NARROW, "the search returned nothing - widen the query profile or the community is quiet"
    events = int(outcome.get("events", 0) or 0)
    if events == 0:
        blocked = int(outcome.get("blocked", 0) or 0) + int(outcome.get("login", 0) or 0)
        fetched = int(outcome.get("fetched", 0) or 0)
        if fetched == 0 and blocked >= max(items, 1):
            return DIAG_METADATA_ONLY_NO_EVENT, (
                f"{items} posts, bodies not fetchable here; titles/snippets carried no dated event")
        return DIAG_NON_EVENT_CONTENT, f"{items} posts collected, none normalised into an event"
    if int(outcome.get("upcoming_events", 0) or 0) == 0:
        return DIAG_PAST_ONLY, f"{events} events, none upcoming"
    return DIAG_HEALTHY, f"{outcome.get('upcoming_events')} upcoming events"


def last_run_per_source(con) -> dict[int, dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (source_id) source_id, status, discovered_count, new_count, "
            "       started_at, error FROM source_collection_runs "
            "ORDER BY source_id, started_at DESC"
        )
        return {row["source_id"]: row for row in _rows(cur)}


def representative_yield(con) -> dict[int, dict[str, int]]:
    """Per source: how many visible upcoming events it *represents*
    (v0.94.0's elected primary post, else the row's own), and how many of
    those it won over another post - a direct source's "primary wins"."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT i.source_id, count(*) AS represented, "
            "       count(*) FILTER (WHERE e.primary_source_item_id IS NOT NULL) AS wins "
            "FROM events e "
            "JOIN source_items i ON i.source_item_id = "
            "     COALESCE(e.primary_source_item_id, e.source_item_id) "
            "WHERE e.provenance = 'LIVE' AND e.listing_state = 'LISTED' "
            "  AND e.canonical_event_id IS NULL AND e.event_date >= current_date "
            "GROUP BY i.source_id"
        )
        return {row["source_id"]: {"represented": row["represented"], "wins": row["wins"]}
                for row in _rows(cur)}


def coverage_gaps(con) -> list[dict[str, Any]]:
    """Region x genre: communities we know, how many of them have a direct
    source, how many direct sources are enabled there, and the upcoming
    events those sources represent. Sorted so the biggest gap (communities
    with no source at all) comes first - the next Source to propose."""
    with con.cursor() as cur:
        cur.execute(
            "WITH linked AS ("
            "  SELECT DISTINCT (config->>'community_id')::bigint AS community_id "
            "  FROM sources WHERE config ? 'community_id' AND config->>'community_id' ~ '^\\d+$'"
            "), comm AS ("
            "  SELECT c.community_id, c.region_id, cg.genre_id, "
            "         (l.community_id IS NOT NULL) AS has_source "
            "  FROM communities c JOIN community_genres cg USING (community_id) "
            "  LEFT JOIN linked l ON l.community_id = c.community_id "
            "  WHERE c.enabled"
            "), direct AS ("
            "  SELECT s.source_id, s.region_id, s.genre_id, s.enabled FROM sources s "
            "  WHERE s.source_role = ANY(%s)"
            "), upcoming AS ("
            "  SELECT src.region_id, src.genre_id, count(*) AS events FROM events e "
            "  JOIN source_items i ON i.source_item_id = "
            "       COALESCE(e.primary_source_item_id, e.source_item_id) "
            "  JOIN sources src ON src.source_id = i.source_id "
            "  WHERE e.provenance = 'LIVE' AND e.listing_state = 'LISTED' "
            "    AND e.canonical_event_id IS NULL AND e.event_date >= current_date "
            "    AND src.source_role = ANY(%s) GROUP BY 1, 2"
            ") "
            "SELECT r.code AS region_code, r.name AS region_name, g.code AS genre_code, "
            "       (SELECT count(*) FROM comm WHERE comm.region_id = r.region_id "
            "          AND comm.genre_id = g.genre_id) AS communities, "
            "       (SELECT count(*) FROM comm WHERE comm.region_id = r.region_id "
            "          AND comm.genre_id = g.genre_id AND comm.has_source) AS communities_with_source, "
            "       (SELECT count(*) FROM direct WHERE direct.region_id = r.region_id "
            "          AND direct.genre_id = g.genre_id AND direct.enabled) AS enabled_direct_sources, "
            "       COALESCE((SELECT events FROM upcoming WHERE upcoming.region_id = r.region_id "
            "          AND upcoming.genre_id = g.genre_id), 0) AS upcoming_direct_events "
            "FROM regions r CROSS JOIN genres g "
            "WHERE r.code <> 'KR' AND g.enabled "
            "ORDER BY r.name, g.code",
            (list(DIRECT_ROLES), list(DIRECT_ROLES)),
        )
        rows = [row for row in _rows(cur)
                if row["communities"] or row["enabled_direct_sources"] or row["upcoming_direct_events"]]
    for row in rows:
        row["communities_without_source"] = row["communities"] - row["communities_with_source"]
    rows.sort(key=lambda r: (-r["communities_without_source"], -r["communities"],
                             r["region_name"], r["genre_code"]))
    return rows


def communities_without_source(con) -> list[dict[str, Any]]:
    """Enabled communities no Source Master row is linked to, with what a
    proposal would need - the operator's work list, approved discovery
    candidates and recently-seen communities first."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT c.community_id, c.name, c.homepage_url, c.region_id, r.name AS region_name, "
            "       ARRAY(SELECT g.code FROM community_genres cg JOIN genres g USING (genre_id) "
            "             WHERE cg.community_id = c.community_id ORDER BY g.code) AS genre_codes, "
            "       (SELECT max(i.item_id) FROM community_discovery_items i "
            "        WHERE i.registered_community_id = c.community_id "
            "          AND i.review_state IN ('APPROVED', 'LINKED')) AS discovery_item_id, "
            "       (SELECT max(i.last_seen) FROM community_discovery_items i "
            "        WHERE i.registered_community_id = c.community_id) AS last_seen "
            "FROM communities c LEFT JOIN regions r ON r.region_id = c.region_id "
            "WHERE c.enabled AND NOT EXISTS ("
            "  SELECT 1 FROM sources s WHERE s.config->>'community_id' = c.community_id::text) "
            "ORDER BY (SELECT max(i.item_id) FROM community_discovery_items i "
            "          WHERE i.registered_community_id = c.community_id "
            "            AND i.review_state IN ('APPROVED', 'LINKED')) IS NULL, "
            "         (SELECT max(i.last_seen) FROM community_discovery_items i "
            "          WHERE i.registered_community_id = c.community_id) DESC NULLS LAST, "
            "         c.community_id"
        )
        rows = _rows(cur)
    from . import community_discovery as cd  # noqa: PLC0415

    for row in rows:
        ident = cd.identify(row.get("homepage_url"))
        row["platform"] = ident.platform if ident else None
        row["proposable"] = bool(ident and ident.platform in cd.SOURCE_PLATFORMS)
    return rows


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
    last_runs = last_run_per_source(con)
    represented = representative_yield(con)

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
        # v0.95.0: yield diagnosis and representative wins, from the same
        # stored numbers - no new tracking column.
        run = last_runs.get(source["source_id"])
        code, why = yield_diagnosis(source, entry, run)
        rep = represented.get(source["source_id"], {})
        entry.update({
            "diagnosis": code, "diagnosis_label": DIAG_LABELS[code], "diagnosis_detail": why,
            "last_run_status": run.get("status") if run else None,
            "last_run_at": run.get("started_at") if run else None,
            "last_run_discovered": run.get("discovered_count") if run else None,
            "last_run_new": run.get("new_count") if run else None,
            "represented_events": rep.get("represented", 0),
            "primary_wins": rep.get("wins", 0),
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
