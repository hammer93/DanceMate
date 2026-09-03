"""Job registry for the DanceMate scheduler.

A job is a callable taking Settings and returning a short detail string. It
must be safe to run repeatedly and must not write large amounts of data - the
deployment target boots from a 32GB microSD.

The pipeline runs as four jobs in order:

    source-intake        discover posts through a provider's search API
    content-acquisition  fetch the original post behind each result
    engine-ingest        hand new items to the Information Engine
    engine-reprocess     re-extract items whose body arrived after ingest
    event-normalization  build the searchable events and resolve duplicates

plus the v0.74 self-checks.
"""

from __future__ import annotations

from typing import Callable

from runtime import (
    db,
    duplicates,
    engine_adapter,
    engine_ingest,
    normalization,
    resources,
)
from runtime.config import Settings

from . import acquisition_job, intake_job

Job = Callable[[Settings], str]


def engine_availability(settings: Settings) -> str:
    report = engine_adapter.inspect(settings)
    checks = report["checks"]
    return (
        f"engine={report['status']} importable={checks['importable']} "
        f"sqlite_present={checks['sqlite_present']} bytes={checks['sqlite_bytes']}"
    )


def storage_probe(settings: Settings) -> str:
    report = resources.storage_status(settings)
    parts = [
        f"{name}={disk.get('used_percent')}%({disk.get('state')})"
        for name, disk in report["disks"].items()
        if disk.get("available")
    ]
    return f"storage={report['status']} " + " ".join(parts)


def source_intake(settings: Settings) -> str:
    """Collect from enabled sources whose interval has elapsed."""
    return intake_job.run(settings)


def engine_ingest_job(settings: Settings) -> str:
    """Hand collected raw items to the Information Engine."""
    result = engine_ingest.ingest_pending(settings)
    detail = (
        f"pending={result['pending']} ingested={result['ingested']} "
        f"skipped={result['skipped']} failed={result['failed']} "
        f"candidates={result['candidates']}"
    )
    if result.get("failures"):
        detail += f" first_failures={result['failures']}"
    return detail


def content_acquisition(settings: Settings) -> str:
    """Fetch the original posts behind collected search results."""
    return acquisition_job.run(settings)


def engine_reprocess(settings: Settings) -> str:
    """Re-extract candidates for items whose body arrived after first ingest."""
    result = engine_ingest.reprocess_acquired(settings)
    detail = (
        f"pending={result['pending']} reprocessed={result['reprocessed']} "
        f"skipped_reviewed={result['skipped_reviewed']} failed={result['failed']} "
        f"candidates {result['candidates_before']}->{result['candidates_after']}"
    )
    if result.get("failures"):
        detail += f" first_failures={result['failures']}"
    return detail


def event_normalization(settings: Settings) -> str:
    """Build the searchable event rows, then let the duplicate rules run.

    One job rather than two so the order is guaranteed: duplicates are found by
    comparing normalised rows, and comparing a half-built table would flag
    pairs that stop existing on the next tick.
    """
    built = normalization.normalize_all(settings)
    detail = (
        f"candidates={built['candidates']} normalized={built['normalized']} "
        f"no_date={built['skipped_no_date']} unresolved_venues={built['unresolved_venues']}"
    )
    with db.connect(settings, autocommit=True) as con:
        found = duplicates.scan(con)
    detail += (
        f" | compared={found['compared']} auto_merged={found['auto_merged']} "
        f"for_review={found['flagged_for_review']}"
    )
    return detail


REGISTRY: dict[str, Job] = {
    "engine-availability": engine_availability,
    "storage-probe": storage_probe,
    "source-intake": source_intake,
    "content-acquisition": content_acquisition,
    "engine-ingest": engine_ingest_job,
    "engine-reprocess": engine_reprocess,
    "event-normalization": event_normalization,
}


def get(name: str) -> Job:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown job {name!r}; known jobs: {sorted(REGISTRY)}") from None
