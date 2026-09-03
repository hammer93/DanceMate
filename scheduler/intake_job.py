"""Scheduler job: collect from the enabled sources whose interval has elapsed.

The rule that matters: this job touches a source only when an operator has
enabled it in the admin console **and** its `collection_interval_minutes` has
passed. Registering a source is not the same as pointing a collector at it, and
nothing polls faster than the Source Master says.

Flow per source:

    Source Master row
      -> runtime.collectors (the Information Engine's own collector)
      -> source_items (raw, deduplicated by content hash)
      -> handed to the engine by the ingest step

Failures are recorded against the source and the run, then the job moves to the
next source. One unreachable upstream must not stop the others.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from runtime import collectors, db, intake, sources
from runtime.config import Settings

log = logging.getLogger("dancemate.scheduler.intake")

# How many sources one tick will collect from. Keeps a single pass bounded on a
# 4GB board even if an operator enables many sources at once.
MAX_SOURCES_PER_TICK = 5


def collect_source(settings: Settings, con, source: dict[str, Any]) -> dict[str, Any]:
    """Collect one source and persist the result. Never raises."""
    platform = source["platform"]
    capability = collectors.describe_capability(platform)
    mode = collectors.MODE_LIVE if capability["live"] else collectors.MODE_SNAPSHOT

    run_id = intake.start_run(con, source["source_id"], mode=mode)
    try:
        result = collectors.collect(settings, source, mode=mode)
    except collectors.CollectorUnavailable as exc:
        intake.finish_run(con, run_id, status="SKIPPED", error=str(exc))
        intake.record_error(
            con, source_id=source["source_id"], collection_run_id=run_id,
            kind="COLLECTOR_UNAVAILABLE", detail=str(exc),
        )
        sources.record_collection_result(
            con, source["source_id"], status="SKIPPED", detail=str(exc)
        )
        return {"source_key": source["source_key"], "status": "SKIPPED", "detail": str(exc)}
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        intake.finish_run(con, run_id, status="FAIL", error=detail)
        intake.record_error(
            con, source_id=source["source_id"], collection_run_id=run_id,
            kind="COLLECTION_FAILED", detail=detail,
        )
        sources.record_collection_result(
            con, source["source_id"], status="FAIL", detail=detail
        )
        log.exception("collection failed for %s", source["source_key"])
        return {"source_key": source["source_key"], "status": "FAIL", "detail": detail}

    counts = intake.store_items(
        con, source["source_id"], result.items, collection_run_id=run_id
    )
    intake.finish_run(
        con, run_id, status="PASS",
        discovered=len(result.items),
        new=counts["NEW"] + counts["REVISED"],
        duplicates=counts["DUPLICATE"],
    )
    detail = (
        f"{result.mode}: {len(result.items)} found, {counts['NEW']} new, "
        f"{counts['REVISED']} revised, {counts['DUPLICATE']} duplicate"
    )
    sources.record_collection_result(
        con, source["source_id"], status="PASS", detail=detail,
        collected_at=datetime.now(timezone.utc),
    )
    return {
        "source_key": source["source_key"], "status": "PASS", "mode": result.mode,
        "discovered": len(result.items), **counts,
    }


def run(settings: Settings) -> str:
    """Scheduler entry point. Returns a one-line summary for job_runs.detail."""
    with db.connect(settings, autocommit=True) as con:
        due = sources.due_sources(con)
        if not due:
            with con.cursor() as cur:
                cur.execute("SELECT count(*) FROM sources WHERE enabled")
                enabled = cur.fetchone()[0]
            return f"no source due (enabled={enabled})"

        results = [
            collect_source(settings, con, source)
            for source in due[:MAX_SOURCES_PER_TICK]
        ]

    passed = sum(1 for r in results if r["status"] == "PASS")
    new_items = sum(r.get("NEW", 0) for r in results)
    revised = sum(r.get("REVISED", 0) for r in results)
    failed = [r["source_key"] for r in results if r["status"] == "FAIL"]
    skipped = [r["source_key"] for r in results if r["status"] == "SKIPPED"]

    summary = (
        f"collected {passed}/{len(results)} due sources, "
        f"{new_items} new, {revised} revised"
    )
    if skipped:
        summary += f", skipped {skipped}"
    if failed:
        summary += f", FAILED {failed}"
    return summary
