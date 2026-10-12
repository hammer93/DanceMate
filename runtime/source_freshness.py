"""Is each source still working, and does each region still have a future?

v0.96.31. Two collectors failed every single run for three weeks - Miltang
from 2026-09-21 (82 runs), TangoNOW from 2026-09-25 (133 runs) - and nothing
said so. `job_runs` recorded 2,042 consecutive PASSes, `scheduler_heartbeat`
said "jobs ok", and the Sources page read ACTIVE, because:

  * a job's status answers "did the tick finish", not "did the sources work";
  * `sources.record_collection_result()` sets `last_collected_at` on a
    *failure* too, so a source that fails every tick never looks stale; and
  * `admin._source_health()` only special-cased AUTH_FAILED / BAD_RESPONSE,
    and both of these failures classified as UNKNOWN.

So the person who noticed was the user, looking at an empty Busan listing.

Everything here is read-only and computed from rows that already exist -
`source_collection_runs`, `source_errors`, `sources`, `source_items`,
`events`. No new column, no new table, no background writer: a monitoring
store that can itself go stale is one more thing to be wrong.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import quality

# Source states, most actionable first. Reuses the operator-facing error
# kinds `collector_errors` already produces rather than inventing a parallel
# vocabulary - the only new words are the ones that describe a *pattern of
# runs*, which no single error kind can say.
HEALTHY = "HEALTHY"
PARTIAL = "PARTIAL"
STALE = "STALE"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
ACCESS_DENIED = "ACCESS_DENIED"
NO_RECENT_CONTENT = "NO_RECENT_CONTENT"
DISABLED = "DISABLED"
UNKNOWN = "UNKNOWN"

#: Consecutive failures before a source is called FAILED rather than DEGRADED.
#: Two is not a blip and not a hair trigger: one tick can lose a connection.
FAILED_AFTER_CONSECUTIVE = 2
#: How many of a source's own intervals may pass with no success before it is
#: STALE. The same multiple `admin._source_health()` already uses, so the two
#: never disagree about the word.
STALE_INTERVAL_MULTIPLE = 6
#: A source that collects fine but has published nothing for this long is not
#: broken - it is quiet. Only said for sources that *do* normally post.
QUIET_DAYS = 30

_DEFAULT_INTERVAL = 180


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _days_since(when: Any, *, now: datetime) -> int | None:
    when = _aware(when)
    return None if when is None else max(0, (now - when).days)


def source_rows(con) -> list[dict[str, Any]]:
    """Per enabled-or-not source: attempt/success recency, the current run
    streak, its last classified error, and what it has produced.

    One query. `consecutive_failures` counts back from the newest run and
    stops at the first non-failure, which is the number an operator wants:
    "how long has this been broken", not "how many times ever".
    """
    with con.cursor() as cur:
        cur.execute(
            "WITH streak AS ("
            "  SELECT source_id, count(*) AS consecutive_failures FROM ("
            "    SELECT source_id, status,"
            "           row_number() OVER (PARTITION BY source_id"
            "                              ORDER BY collection_run_id DESC) AS rn,"
            "           sum(CASE WHEN status IN ('FAIL', 'PARTIAL') THEN 0 ELSE 1 END)"
            "             OVER (PARTITION BY source_id"
            "                   ORDER BY collection_run_id DESC) AS breaks"
            "    FROM source_collection_runs"
            "  ) ranked WHERE breaks = 0 GROUP BY source_id"
            "),"
            "runs AS ("
            "  SELECT source_id,"
            "         max(started_at) AS last_attempt_at,"
            "         max(started_at) FILTER (WHERE status = 'PASS') AS last_success_at,"
            "         max(started_at) FILTER (WHERE status = 'PARTIAL')"
            "           AS last_partial_at,"
            "         count(*) FILTER (WHERE status IN ('FAIL', 'PARTIAL')"
            "                            AND started_at >= now() - interval '7 days')"
            "           AS recent_failures"
            "  FROM source_collection_runs GROUP BY source_id"
            "),"
            "items AS ("
            "  SELECT source_id, max(collected_at) AS last_acquired_item_at,"
            "         count(*) FILTER (WHERE collected_at >= now() - interval '7 days')"
            "           AS items_7d"
            "  FROM source_items GROUP BY source_id"
            "),"
            "err AS ("
            "  SELECT DISTINCT ON (source_id) source_id, kind, detail, occurred_at"
            "  FROM source_errors ORDER BY source_id, source_error_id DESC"
            "),"
            "future AS ("
            "  SELECT si.source_id, max(e.event_date) AS latest_future_event_date,"
            "         count(*) AS future_events"
            "  FROM events e JOIN source_items si USING (source_item_id)"
            f"  WHERE {quality.LISTED_E} AND e.event_date >= %(today)s"
            "  GROUP BY si.source_id"
            ")"
            "SELECT s.source_id, s.source_key, s.name, s.platform, s.enabled,"
            "       s.source_role, s.last_status, s.last_detail,"
            "       s.collection_interval_minutes, g.name AS genre,"
            "       r.code AS region_code,"
            "       runs.last_attempt_at, runs.last_success_at, runs.last_partial_at,"
            "       coalesce(runs.recent_failures, 0) AS recent_failures,"
            "       coalesce(streak.consecutive_failures, 0) AS consecutive_failures,"
            "       items.last_acquired_item_at, coalesce(items.items_7d, 0) AS items_7d,"
            "       err.kind AS last_error_kind, err.detail AS last_error_message,"
            "       future.latest_future_event_date,"
            "       coalesce(future.future_events, 0) AS future_events "
            "FROM sources s "
            "LEFT JOIN genres g USING (genre_id) "
            "LEFT JOIN regions r USING (region_id) "
            "LEFT JOIN runs ON runs.source_id = s.source_id "
            "LEFT JOIN streak ON streak.source_id = s.source_id "
            "LEFT JOIN items ON items.source_id = s.source_id "
            "LEFT JOIN err ON err.source_id = s.source_id "
            "LEFT JOIN future ON future.source_id = s.source_id "
            "ORDER BY s.source_key",
            {"today": quality._seoul_today()},
        )
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def classify(row: dict[str, Any], *, now: datetime | None = None) -> str:
    """One source's state. Never from volume alone: a source with 681 stored
    items whose every recent run failed is FAILED, not HEALTHY."""
    now = now or datetime.now(timezone.utc)
    if not row.get("enabled"):
        return DISABLED

    last_status = (row.get("last_status") or "").upper()
    kind = (row.get("last_error_kind") or "").upper()
    failures = int(row.get("consecutive_failures") or 0)

    if failures and (last_status == "ACCESS_DENIED" or kind == "ACCESS_DENIED"):
        return ACCESS_DENIED
    if failures >= FAILED_AFTER_CONSECUTIVE:
        return FAILED
    if failures:
        return DEGRADED

    last_success = _aware(row.get("last_success_at"))
    if last_success is None:
        # Never a clean run. Attempted but never passed is a failure state
        # even before the streak counter has anything to say.
        return FAILED if row.get("last_attempt_at") else UNKNOWN

    interval = int(row.get("collection_interval_minutes") or _DEFAULT_INTERVAL)
    if (now - last_success) > timedelta(minutes=interval * STALE_INTERVAL_MULTIPLE):
        return STALE
    if row.get("last_partial_at") and _aware(row["last_partial_at"]) == last_success:
        return PARTIAL

    quiet = _days_since(row.get("last_acquired_item_at"), now=now)
    if quiet is not None and quiet >= QUIET_DAYS:
        # Collecting fine, publishing nothing. Not an error - a fact.
        return NO_RECENT_CONTENT
    return HEALTHY


def report(con, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """`source_rows()` with a state and the two ages an operator reads."""
    now = now or datetime.now(timezone.utc)
    out = []
    for row in source_rows(con):
        row = dict(row)
        row["state"] = classify(row, now=now)
        row["days_since_success"] = _days_since(row.get("last_success_at"), now=now)
        row["days_since_item"] = _days_since(row.get("last_acquired_item_at"), now=now)
        out.append(row)
    return out


def failing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sources an operator has to do something about, worst first.

    Takes `report()`'s rows. A row with no `state` simply does not match -
    a monitoring helper that raises is worse than one that says nothing.
    """
    order = {FAILED: 0, ACCESS_DENIED: 1, PARTIAL: 2, DEGRADED: 3, STALE: 4}
    return sorted((r for r in rows if r.get("state") in order),
                  key=lambda r: (order[r["state"]],
                                 -(r.get("consecutive_failures") or 0)))


# --- regional future supply -------------------------------------------------

#: The regions a reader actually picks from, and the one genre whose supply
#: collapsed. Seoul is included deliberately: a zero that is zero everywhere
#: is a pipeline problem, and a zero in three cities while Seoul is fine is a
#: supply problem, and the table has to be able to show the difference.
WATCHED_REGIONS = ("KR-SEOUL", "KR-BUSAN", "KR-DAEGU", "KR-DAEJEON",
                   "KR-GYEONGGI", "KR-INCHEON")


def regional_supply(con, *, genre: str = "Tango",
                    today: date | None = None) -> list[dict[str, Any]]:
    """Per region: how much future this genre has, and how old that news is.

    Counted over exactly what a reader can reach (`quality.LISTED_E`), so
    this cannot report a supply the public listing does not show.
    """
    today = today or quality._seoul_today()
    with con.cursor() as cur:
        cur.execute(
            "SELECT r.code AS region_code, r.name AS region_name,"
            "  count(*) FILTER (WHERE e.event_date = %(today)s) AS today,"
            "  count(*) FILTER (WHERE e.event_date BETWEEN %(today)s"
            "                     AND %(today)s + 7) AS d7,"
            "  count(*) FILTER (WHERE e.event_date BETWEEN %(today)s"
            "                     AND %(today)s + 14) AS d14,"
            "  count(*) FILTER (WHERE e.event_date BETWEEN %(today)s"
            "                     AND %(today)s + 30) AS d30,"
            "  count(*) FILTER (WHERE e.event_date >= %(today)s) AS future_events,"
            "  max(e.event_date) FILTER (WHERE e.event_date >= %(today)s)"
            "    AS latest_future_date,"
            "  max(si.collected_at) FILTER (WHERE e.event_date >= %(today)s)"
            "    AS future_acquired_at "
            "FROM regions r "
            "LEFT JOIN events e ON e.region_id = r.region_id "
            f" AND {quality.LISTED_E} "
            "LEFT JOIN genres g ON g.genre_id = e.genre_id AND g.name = %(genre)s "
            "LEFT JOIN source_items si ON si.source_item_id = e.source_item_id "
            "WHERE r.code = ANY(%(codes)s) AND (e.event_id IS NULL OR g.name IS NOT NULL) "
            "GROUP BY 1, 2 ORDER BY 7 DESC, 1",
            {"today": today, "genre": genre, "codes": list(WATCHED_REGIONS)},
        )
        names = [c.name for c in cur.description]
        rows = [dict(zip(names, row)) for row in cur.fetchall()]
    now = datetime.now(timezone.utc)
    for row in rows:
        row["days_since_future_acquired"] = _days_since(
            row.get("future_acquired_at"), now=now)
        row["days_of_runway"] = (
            None if row.get("latest_future_date") is None
            else (row["latest_future_date"] - today).days)
    return rows


# Why a region shows zero. Four different jobs for the operator, so four
# different words - never one ERROR for all of them (§19).
ZERO_NO_EVENTS = "SOURCES_WORKING_BUT_NO_FUTURE_EVENTS"
ZERO_COLLECTOR_FAILED = "COLLECTOR_FAILED"
ZERO_NO_SOURCE = "NO_SOURCE_FOR_REGION"
ZERO_UNATTRIBUTED = "EVENTS_EXIST_BUT_UNATTRIBUTED"


def zero_supply_reasons(con, *, genre: str = "Tango",
                        today: date | None = None) -> list[dict[str, Any]]:
    """For every watched region with no future event of this genre, why.

    Reads three facts and does not guess past them: whether any source is
    registered for that region, whether any source is currently failing, and
    whether there are visible future events of this genre that simply carry
    no region. The last one is the case a region filter hides rather than a
    supply that is missing.
    """
    today = today or quality._seoul_today()
    supply = {r["region_code"]: r for r in regional_supply(con, genre=genre,
                                                           today=today)}
    states = {r["source_id"]: r for r in report(con)}
    broken_states = (FAILED, ACCESS_DENIED, PARTIAL, DEGRADED)
    # Which broken source ever supplied which region. A collector is only
    # named as the reason a region is empty if that region's own history
    # says it used to come from there - Miltang produced 33 Busan, 10 Daegu
    # and 22 Daejeon events and is the answer for those three; naming it for
    # a region it never served would send an operator the wrong way.
    with con.cursor() as cur:
        cur.execute(
            "SELECT r.code, si.source_id, count(*) AS events "
            "FROM events e JOIN genres g USING (genre_id) "
            "JOIN regions r ON r.region_id = e.region_id "
            "JOIN source_items si ON si.source_item_id = e.source_item_id "
            "WHERE g.name = %s GROUP BY 1, 2",
            (genre,),
        )
        served: dict[str, list[tuple[int, int]]] = {}
        for code, source_id, events in cur.fetchall():
            served.setdefault(code, []).append((source_id, events))
    with con.cursor() as cur:
        cur.execute(
            "SELECT r.code, count(*) AS sources FROM sources s "
            "JOIN regions r USING (region_id) LEFT JOIN genres g USING (genre_id) "
            "WHERE s.enabled AND (g.name = %s OR g.name IS NULL) GROUP BY 1",
            (genre,),
        )
        regional_sources = dict(cur.fetchall())
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events e JOIN genres g USING (genre_id) "
            f"WHERE {quality.LISTED_E} AND g.name = %s AND e.event_date >= %s "
            "  AND e.region_id IS NULL",
            (genre, today),
        )
        unattributed = cur.fetchone()[0]

    out = []
    for code in WATCHED_REGIONS:
        row = supply.get(code) or {}
        if (row.get("future_events") or 0) > 0:
            continue
        culprits = sorted(
            ((states[sid], events) for sid, events in served.get(code, ())
             if sid in states and states[sid]["state"] in broken_states),
            key=lambda pair: -pair[1],
        )
        if culprits:
            reason = ZERO_COLLECTOR_FAILED
            evidence = ", ".join(
                f"{state['source_key']} {state['state']} since "
                f"{str(state['last_success_at'])[:10]} "
                f"({events} {genre} event(s) here historically)"
                for state, events in culprits[:3])
        elif not regional_sources.get(code):
            reason = ZERO_NO_SOURCE
            evidence = f"no enabled {genre} source is registered for {code}"
        elif unattributed:
            reason = ZERO_UNATTRIBUTED
            evidence = (f"{unattributed} visible future {genre} event(s) carry "
                        f"no region at all")
        else:
            reason = ZERO_NO_EVENTS
            evidence = "every source collected cleanly and none lists a future date"
        out.append({
            "region_code": code,
            "region_name": row.get("region_name"),
            "genre": genre,
            "reason": reason,
            "evidence": evidence,
            "days_since_future_acquired": row.get("days_since_future_acquired"),
        })
    return out
