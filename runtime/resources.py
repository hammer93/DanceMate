"""Host resource probes for the ROCKPro64 target (4GB RAM, 32GB microSD).

Standard library only - no psutil - to keep the ARM64 image small and to avoid
a compiled dependency on the deployment target.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .config import Settings

MEMINFO = Path("/proc/meminfo")


def load_average() -> dict[str, Any]:
    try:
        one, five, fifteen = os.getloadavg()
    except (OSError, AttributeError):  # not available on every platform
        return {"available": False}
    cpus = os.cpu_count() or 1
    return {
        "available": True,
        "load1": round(one, 2),
        "load5": round(five, 2),
        "load15": round(fifteen, 2),
        "cpu_count": cpus,
        "load1_per_cpu": round(one / cpus, 2),
    }


def memory() -> dict[str, Any]:
    """Read /proc/meminfo. Returns available=False off Linux."""
    if not MEMINFO.is_file():
        return {"available": False}
    values: dict[str, int] = {}
    for line in MEMINFO.read_text(encoding="utf-8").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0])  # kB
    total = values.get("MemTotal", 0)
    avail = values.get("MemAvailable", 0)
    if total <= 0:
        return {"available": False}
    used = total - avail
    return {
        "available": True,
        "total_mb": total // 1024,
        "available_mb": avail // 1024,
        "used_mb": used // 1024,
        "used_percent": round(used * 100 / total, 1),
    }


def classify_usage(used_percent: float, warn: int, critical: int) -> str:
    if used_percent >= critical:
        return "CRITICAL"
    if used_percent >= warn:
        return "WARN"
    return "OK"


def disk(path: Path, warn: int, critical: int) -> dict[str, Any]:
    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return {"available": False, "path": str(path), "detail": str(exc)}
    used_percent = round(usage.used * 100 / usage.total, 1) if usage.total else 0.0
    return {
        "available": True,
        "path": str(path),
        "measured_at": str(target),
        "total_gb": round(usage.total / 1024**3, 2),
        "free_gb": round(usage.free / 1024**3, 2),
        "used_percent": used_percent,
        "state": classify_usage(used_percent, warn, critical),
    }


def snapshot(settings: Settings) -> dict[str, Any]:
    warn = settings.storage_warn_percent
    critical = settings.storage_critical_percent
    return {
        "cpu": load_average(),
        "memory": memory(),
        "disk": {
            "data": disk(settings.data_dir, warn, critical),
            "engine": disk(settings.engine_data_dir, warn, critical),
            "backup": disk(settings.backup_dir, warn, critical),
        },
    }


def storage_status(settings: Settings) -> dict[str, Any]:
    """Aggregate the disk probes into one PASS / WARN / FAIL verdict."""
    disks = snapshot(settings)["disk"]
    states = [d.get("state") for d in disks.values() if d.get("available")]
    if not states:
        return {"status": "FAIL", "detail": "no filesystem could be measured", "disks": disks}
    if "CRITICAL" in states:
        status = "FAIL"
    elif "WARN" in states:
        status = "WARN"
    else:
        status = "PASS"
    return {
        "status": status,
        "warn_percent": settings.storage_warn_percent,
        "critical_percent": settings.storage_critical_percent,
        "disks": disks,
    }
