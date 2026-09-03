"""Job registry for the DanceMate scheduler.

A job is a callable taking Settings and returning a short detail string. It
must be safe to run repeatedly and must not write large amounts of data - the
deployment target boots from a 32GB microSD.

v0.74 registers self-check jobs only. Real Dance Event source collectors are
v0.75 work and will register here.
"""

from __future__ import annotations

from typing import Callable

from runtime import engine_adapter, resources
from runtime.config import Settings

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


REGISTRY: dict[str, Job] = {
    "engine-availability": engine_availability,
    "storage-probe": storage_probe,
}


def get(name: str) -> Job:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown job {name!r}; known jobs: {sorted(REGISTRY)}") from None
