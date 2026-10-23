"""Composite health/status assembly for the runtime API and check-server.sh.

Six components, each reported as PASS / WARN / FAIL, matching the operator
output contract:

    DanceMate Server
    Runtime ........ PASS
    Database ....... PASS
    Scheduler ...... PASS
    Information .... PASS
    Storage ........ PASS
    Backup ......... PASS
"""

from __future__ import annotations

import time
from typing import Any, Callable

from . import backup_state, db, engine_adapter, resources
from .config import Settings

COMPONENTS = ("runtime", "database", "scheduler", "information", "storage", "backup")
_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}

_STARTED_AT = time.time()


def uptime_seconds() -> int:
    return int(time.time() - _STARTED_AT)


def runtime_component(settings: Settings) -> dict[str, Any]:
    from .config import validate

    problems = validate(settings)
    return {
        "status": "PASS" if not problems else "FAIL",
        "env": settings.env,
        "version": settings.version,
        "uptime_seconds": uptime_seconds(),
        "config_problems": problems,
    }


def scheduler_component(settings: Settings) -> dict[str, Any]:
    """Grade the scheduler on both probe success and heartbeat freshness."""
    beat = db.latest_heartbeat(settings)
    # Allow two missed beats before WARN and three before FAIL.
    tolerance = settings.scheduler_heartbeat_seconds * 3
    result: dict[str, Any] = {**beat, "tolerance_seconds": tolerance}

    if not beat.get("available"):
        result["status"] = "FAIL"
        return result

    worker_status = beat.get("worker_status")
    age = beat.get("age_seconds")
    if worker_status is None or age is None:
        result["status"] = "FAIL"
    elif age > tolerance:
        result["status"] = "FAIL"
    elif worker_status in {"FAIL", "STOPPED"}:
        result["status"] = "FAIL"
    elif age > settings.scheduler_heartbeat_seconds * 2:
        result["status"] = "WARN"
    else:
        result["status"] = "PASS"
    return result


def information_component(settings: Settings) -> dict[str, Any]:
    return engine_adapter.inspect(settings)


def _probe(name: str, measure: Callable[[Settings], dict[str, Any]],
           settings: Settings) -> dict[str, Any]:
    """One component's measurement; a probe that raises is that component's
    FAIL, never the whole report's. v0.96.51 recovery: the backup probe's
    PermissionError escaped this call and /status answered HTTP 500, so the
    database, scheduler and information state could not be read either."""
    try:
        return measure(settings)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return {
            "status": "FAIL",
            "reason": "PROBE_ERROR",
            "detail": f"the {name} probe raised {type(exc).__name__}",
        }


def collect(settings: Settings) -> dict[str, Any]:
    """Full status payload. Individual probes never raise out of this call."""
    return {
        "runtime": _probe("runtime", runtime_component, settings),
        "database": _probe("database", db.ping, settings),
        "scheduler": _probe("scheduler", scheduler_component, settings),
        "information": _probe("information", information_component, settings),
        "storage": _probe("storage", resources.storage_status, settings),
        "backup": _probe("backup", backup_state.status, settings),
    }


def overall(payload: dict[str, Any]) -> str:
    """Worst component status wins."""
    worst = "PASS"
    for name in COMPONENTS:
        status = str(payload.get(name, {}).get("status", "FAIL"))
        if _RANK.get(status, 2) > _RANK[worst]:
            worst = status if status in _RANK else "FAIL"
    return worst


def summary_lines(payload: dict[str, Any]) -> list[str]:
    """The operator-facing dotted report used by scripts/check-server.sh."""
    labels = {
        "runtime": "Runtime",
        "database": "Database",
        "scheduler": "Scheduler",
        "information": "Information",
        "storage": "Storage",
        "backup": "Backup",
    }
    lines = ["DanceMate Server"]
    for name in COMPONENTS:
        status = str(payload.get(name, {}).get("status", "FAIL"))
        label = labels[name]
        lines.append(f"{label} {'.' * (15 - len(label))} {status}")
    return lines
