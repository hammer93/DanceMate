"""Scheduler job: collect from the enabled sources whose interval has elapsed.

Two rules this job exists to enforce.

**A source is collected from only when an operator enabled it and its
`collection_interval_minutes` has passed.** Registering a source is not the same
as pointing a collector at it, and nothing polls faster than the Source Master
says.

**The scheduler never substitutes recorded snapshot data for a live
collection.** An earlier version fell back to the engine's snapshot fixtures
whenever credentials were absent, which quietly filled `source_items` with
offline sample data that looked exactly like real intake. A source with no
usable credential is now SKIPPED and says so. Snapshot remains available for
the admin [Test] button, and for a source whose operator has deliberately set
`config.snapshot_intake_allowed` - those runs are recorded with
`mode = 'snapshot'` and a `SNAPSHOT` status, so no count can be mistaken for
live data.

Flow per source:

    Source Master row
      -> quota check (per provider, per day)
      -> runtime.collectors (the Information Engine's own live collector)
      -> source_items (raw, deduplicated by content hash)
      -> handed to the engine by the ingest step

Failures are classified, recorded against the source and the run, and the job
moves on. One unreachable upstream must not stop the others.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from runtime import collector_errors, collectors, db, intake, quota, sources, usage
from runtime.config import Settings

log = logging.getLogger("dancemate.scheduler.intake")

# How many sources one tick will collect from. Keeps a single pass bounded on a
# 4GB board even if an operator enables many sources at once.
MAX_SOURCES_PER_TICK = 5

STATUS_PASS = "PASS"
STATUS_SNAPSHOT = "SNAPSHOT"
STATUS_SKIPPED = "SKIPPED"
STATUS_FAIL = "FAIL"


def snapshot_intake_allowed(source: dict[str, Any]) -> bool:
    """Has an operator deliberately opted this source into snapshot intake?

    Off unless explicitly set. This is a development affordance, never a
    fallback: it exists so the pipeline can be demonstrated without a
    credential, and every run it produces is labelled snapshot.
    """
    config = source.get("config") or {}
    if isinstance(config, str):
        config = json.loads(config)
    return bool(config.get("snapshot_intake_allowed"))


def choose_mode(source: dict[str, Any]) -> tuple[str | None, str]:
    """Decide how - or whether - to collect. Returns (mode, reason).

    A mode of None means: do not collect, and report the reason.
    """
    platform = source["platform"]
    capability = collectors.describe_capability(platform)

    if not capability["live"] and not capability["snapshot"]:
        return None, f"{platform} has no collector in this version"
    if capability["live"]:
        return collectors.MODE_LIVE, "live collection"
    if snapshot_intake_allowed(source):
        return (
            collectors.MODE_SNAPSHOT,
            "snapshot intake explicitly enabled for this source - NOT live data",
        )
    missing = ", ".join(capability.get("missing_credentials") or []) or "credentials"
    return None, (
        f"no live collection: {missing} not configured. "
        "Refusing to store snapshot data as if it were collected"
    )


def collect_source(settings: Settings, con, source: dict[str, Any]) -> dict[str, Any]:
    """Collect one source and persist the result. Never raises."""
    source_id = source["source_id"]
    source_key = source["source_key"]
    platform = source["platform"]

    mode, reason = choose_mode(source)
    if mode is None:
        sources.record_collection_result(
            con, source_id, status=STATUS_SKIPPED, detail=reason
        )
        intake.record_error(
            con, source_id=source_id, collection_run_id=None,
            kind=collector_errors.CREDENTIALS_MISSING, detail=reason,
        )
        log.info("skipping %s: %s", source_key, reason)
        return {"source_key": source_key, "status": STATUS_SKIPPED, "detail": reason}

    # Budget check before any request: a source with six queries costs six calls.
    expected = quota.expected_request_count(source)
    if mode == collectors.MODE_LIVE:
        try:
            quota.check(con, platform, cost=expected)
        except quota.QuotaExceeded as exc:
            detail = str(exc)
            sources.record_collection_result(
                con, source_id, status=collector_errors.QUOTA_EXCEEDED, detail=detail
            )
            intake.record_error(
                con, source_id=source_id, collection_run_id=None,
                kind=collector_errors.QUOTA_EXCEEDED, detail=detail,
            )
            log.warning("quota exhausted for %s: %s", source_key, detail)
            return {
                "source_key": source_key,
                "status": collector_errors.QUOTA_EXCEEDED,
                "detail": detail,
            }

    run_id = intake.start_run(con, source_id, mode=mode)
    started = datetime.now(timezone.utc)
    try:
        result = collectors.collect(settings, source, mode=mode)
    except collectors.CollectorUnavailable as exc:
        detail = collector_errors.redact(str(exc))
        intake.finish_run(con, run_id, status=STATUS_SKIPPED, error=detail)
        intake.record_error(
            con, source_id=source_id, collection_run_id=run_id,
            kind="COLLECTOR_UNAVAILABLE", detail=detail,
        )
        sources.record_collection_result(
            con, source_id, status=STATUS_SKIPPED, detail=detail
        )
        return {"source_key": source_key, "status": STATUS_SKIPPED, "detail": detail}
    except Exception as exc:
        classified = collector_errors.classify(exc)
        if mode == collectors.MODE_LIVE:
            # The requests were spent even though they failed.
            quota.record(con, platform, requests=expected, error=classified.kind)
        usage.record_api_requests(
            con, platform, requests=expected, errors=expected,
            rate_limited=expected if classified.kind == collector_errors.RATE_LIMITED else 0,
            auth_errors=expected if classified.kind == collector_errors.AUTH_FAILED else 0,
            status=classified.kind,
        )
        intake.finish_run(con, run_id, status=STATUS_FAIL, error=classified.summary())
        intake.record_error(
            con, source_id=source_id, collection_run_id=run_id,
            kind=classified.kind, detail=classified.detail,
        )
        sources.record_collection_result(
            con, source_id, status=classified.kind, detail=classified.summary()
        )
        log.warning(
            "collection failed for %s: %s (retryable=%s)",
            source_key, classified.summary(), classified.retryable,
        )
        return {
            "source_key": source_key, "status": STATUS_FAIL,
            "kind": classified.kind, "retryable": classified.retryable,
            "detail": classified.summary(),
        }

    if mode == collectors.MODE_LIVE:
        quota.record(con, platform, requests=expected)

    counts = intake.store_items(con, source_id, result.items, collection_run_id=run_id)
    if mode == collectors.MODE_LIVE:
        usage.record_api_requests(
            con, platform, requests=expected, success=expected,
            items=len(result.items), new_items=counts["NEW"] + counts["REVISED"],
            duplicate_items=counts["DUPLICATE"], status=STATUS_PASS,
        )
    duration = (datetime.now(timezone.utc) - started).total_seconds()
    intake.finish_run(
        con, run_id, status=STATUS_PASS,
        discovered=len(result.items),
        new=counts["NEW"] + counts["REVISED"],
        duplicates=counts["DUPLICATE"],
    )

    status = STATUS_PASS if mode == collectors.MODE_LIVE else STATUS_SNAPSHOT
    detail = (
        f"{result.mode}: {len(result.items)} found, {counts['NEW']} new, "
        f"{counts['REVISED']} revised, {counts['DUPLICATE']} duplicate, "
        f"{duration:.1f}s"
    )
    sources.record_collection_result(
        con, source_id, status=status, detail=detail,
        collected_at=datetime.now(timezone.utc),
    )
    log.info("source=%s run=%s %s", source_key, run_id, detail)
    return {
        "source_key": source_key, "status": status, "mode": result.mode,
        "discovered": len(result.items), "duration_seconds": round(duration, 1),
        **counts,
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

    live = [r for r in results if r["status"] == STATUS_PASS]
    snapshot_runs = [r for r in results if r["status"] == STATUS_SNAPSHOT]
    skipped = [r["source_key"] for r in results if r["status"] == STATUS_SKIPPED]
    failed = [f"{r['source_key']}({r.get('kind', 'FAIL')})"
              for r in results if r["status"] == STATUS_FAIL]
    quota_blocked = [r["source_key"] for r in results
                     if r["status"] == collector_errors.QUOTA_EXCEEDED]

    new_items = sum(r.get("NEW", 0) for r in results)
    revised = sum(r.get("REVISED", 0) for r in results)

    summary = (
        f"live {len(live)}/{len(results)} due sources, {new_items} new, {revised} revised"
    )
    if snapshot_runs:
        summary += f", SNAPSHOT (not live) {[r['source_key'] for r in snapshot_runs]}"
    if quota_blocked:
        summary += f", quota-blocked {quota_blocked}"
    if skipped:
        summary += f", skipped {skipped}"
    if failed:
        summary += f", FAILED {failed}"
    return summary
