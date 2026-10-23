"""Operations alerts: what is wrong, said once, and said again when it is fixed.

v0.96.51. ``scripts/ops-monitor.sh`` (a systemd timer on the board, apart
from the collection scheduler) gathers the facts every few minutes - the
runtime's own `/status` and `/health/sources`, the scheduler container count,
the disk, and ``runtime.ops_facts`` from inside the runtime - and this module
decides what to say about them. Standard library only: it runs with the
host's ``python3`` precisely when the runtime container may be the thing that
is down.

A condition becomes an alert only after it has held for its threshold of
consecutive checks (one failed collection of a third-party site is not an
outage; TangoNOW answered HTTP 500 for one run on 2026-10-23 and was fine on
the next). An open alert is repeated at most once per cooldown, and its
recovery is said once. ``/health`` is never read: it is liveness and stays
200 with the database down; readiness is ``/status``.

Delivery is the alert log (JSON lines) and the journal. No external channel
is configured, and none is assumed: ``delivery`` reports
``PENDING_CONFIGURATION`` until one is.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

KST = timezone(timedelta(hours=9))

CRITICAL = "CRITICAL"
WARNING = "WARNING"

ALERT = "ALERT"
REMINDER = "REMINDER"
RECOVERED = "RECOVERED"

#: How long an open alert stays quiet before it is said again.
COOLDOWN = timedelta(hours=6)
#: Below this much free space on the data disk, it is critical.
DISK_CRITICAL_FREE_PCT = 10.0
#: Consecutive failed runs of one job before it is an alert.
JOB_FAILURE_STREAK = 3
#: Consecutive failed collections of one source before DEGRADED is an alert.
SOURCE_FAILURE_STREAK = 2

DELIVERY_PENDING = "PENDING_CONFIGURATION"


def _component(status: dict[str, Any] | None, name: str) -> str | None:
    if not status:
        return None
    value = (status.get(name) or {}).get("status")
    return str(value).upper() if value else None


def conditions(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every condition that holds in ``facts`` now: {key: {severity,
    threshold, message}}. Pure. A fact that is missing raises nothing and
    proves nothing - except the runtime's own answer, whose absence *is* the
    finding."""
    found: dict[str, dict[str, Any]] = {}

    def add(key: str, severity: str, threshold: int, message: str) -> None:
        found[key] = {"severity": severity, "threshold": threshold, "message": message}

    status = facts.get("status")
    reachable = facts.get("runtime_running") and status is not None
    if not reachable:
        add("RUNTIME_UNAVAILABLE", CRITICAL, 2,
            "the runtime did not answer /status" + (
                "" if facts.get("runtime_running") else " (container not running)"))
    if _component(status, "database") == "FAIL":
        add("DATABASE_FAILED", CRITICAL, 2, "readiness reports the database FAIL")
    count = facts.get("scheduler_count")
    if count is not None and count > 1:
        add("SCHEDULER_DUPLICATE", CRITICAL, 1, f"{count} scheduler containers are running")
    elif count == 0 or _component(status, "scheduler") == "FAIL":
        add("SCHEDULER_MISSING", CRITICAL, 2,
            "no scheduler container is running" if count == 0
            else "the scheduler heartbeat is stale or failing")
    backup = _component(status, "backup")
    if backup == "FAIL":
        add("BACKUP_FAILED", CRITICAL, 1,
            (status.get("backup") or {}).get("detail") or "backup FAIL")
    elif backup == "WARN":
        add("BACKUP_STALE", WARNING, 1,
            (status.get("backup") or {}).get("detail") or "backup is old")
    free = facts.get("disk_free_pct")
    if (free is not None and free < DISK_CRITICAL_FREE_PCT) or \
            _component(status, "storage") == "FAIL":
        add("DISK_CRITICAL", CRITICAL, 1,
            f"data disk {free:.1f}% free" if free is not None else "storage FAIL")

    db = facts.get("db") or {}
    for job, streak in sorted((db.get("job_failure_streaks") or {}).items()):
        if streak >= JOB_FAILURE_STREAK:
            add(f"JOB_FAILED:{job}", WARNING, 1,
                f"job {job} failed its last {streak} runs")
    stalled = (db.get("reextract") or {}).get("stalled") or 0
    failed = (db.get("normalization") or {}).get("failed") or 0
    if stalled or failed:
        add("EXTRACTION_FAILING", WARNING, 3,
            f"re-extraction stalled {stalled}, normalization failed {failed}")

    for source in ((facts.get("sources") or {}).get("sources") or {}).get(
            "not_collecting") or []:
        key, state = source.get("source_key"), str(source.get("state") or "").upper()
        streak = int(source.get("consecutive_failures") or 0)
        label = f"{source.get('name') or key} ({key})"
        if state in ("FAILED", "ACCESS_DENIED"):
            add(f"SOURCE_FAILED:{key}", WARNING, 1,
                f"source {label} is {state} after {streak} failed collection(s)")
        elif state == "DEGRADED" and streak >= SOURCE_FAILURE_STREAK:
            add(f"SOURCE_DEGRADED:{key}", WARNING, 1,
                f"source {label} failed {streak} collections in a row")
    return found


def evaluate(facts: dict[str, Any], state: dict[str, Any], now: datetime
             ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(notices to emit, the next state). Pure.

    ``state["alerts"][key]`` = {consecutive, open, first_seen, last_notified}.
    A key whose condition no longer holds is dropped from the state - with a
    RECOVERED notice if it had been said.
    """
    previous = dict((state or {}).get("alerts") or {})
    current = conditions(facts)
    notices: list[dict[str, Any]] = []
    nxt: dict[str, Any] = {}
    stamp = now.astimezone(KST).isoformat(timespec="seconds")
    for key, cond in sorted(current.items()):
        entry = dict(previous.get(key) or {"consecutive": 0, "open": False,
                                           "first_seen": stamp})
        entry["consecutive"] = int(entry.get("consecutive") or 0) + 1
        kind = None
        if not entry.get("open") and entry["consecutive"] >= cond["threshold"]:
            entry["open"] = True
            kind = ALERT
        elif entry.get("open"):
            last = entry.get("last_notified")
            if last is None or now - datetime.fromisoformat(last) >= COOLDOWN:
                kind = REMINDER
        if kind:
            entry["last_notified"] = stamp
            notices.append({"at_kst": stamp, "kind": kind, "key": key,
                            "severity": cond["severity"], "message": cond["message"],
                            "since_kst": entry["first_seen"]})
        nxt[key] = entry
    for key, entry in sorted(previous.items()):
        if key not in current and entry.get("open"):
            notices.append({"at_kst": stamp, "kind": RECOVERED, "key": key,
                            "severity": "INFO", "message": f"{key} cleared",
                            "since_kst": entry.get("first_seen")})
    return notices, {"alerts": nxt, "checked_at_kst": stamp}


def delivery_status(environ: dict[str, str] | None = None) -> str:
    """No external channel exists yet; the log and the journal are delivery."""
    return DELIVERY_PENDING


# --- the host command ---------------------------------------------------------------

def _load(path: str | None) -> Any:
    if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_atomic(path: str, data: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--status-file")
    parser.add_argument("--sources-file")
    parser.add_argument("--db-file")
    parser.add_argument("--runtime-running", type=int, default=0)
    parser.add_argument("--scheduler-count", type=int)
    parser.add_argument("--disk-free-pct", type=float)
    args = parser.parse_args(argv)

    db_facts = _load(args.db_file)
    facts = {
        "runtime_running": bool(args.runtime_running),
        "status": _load(args.status_file),
        "sources": _load(args.sources_file),
        "db": db_facts if isinstance(db_facts, dict) and "error" not in db_facts else None,
        "scheduler_count": args.scheduler_count,
        "disk_free_pct": args.disk_free_pct,
    }
    notices, state = evaluate(facts, _load(args.state) or {}, datetime.now(timezone.utc))
    with open(args.log, "a", encoding="utf-8") as handle:
        for notice in notices:
            handle.write(json.dumps(notice, ensure_ascii=False) + "\n")
    _write_atomic(args.state, state)
    for notice in notices:
        print(f"{notice['kind']} {notice['severity']} {notice['key']}: {notice['message']}")
    open_alerts = sorted(k for k, v in state["alerts"].items() if v.get("open"))
    print(f"ops-monitor: {len(open_alerts)} open alert(s)"
          + (f" ({', '.join(open_alerts)})" if open_alerts else "")
          + f"; external delivery {delivery_status()}")
    current = conditions(facts)
    return 1 if any(current[k]["severity"] == CRITICAL for k in open_alerts) else 0


if __name__ == "__main__":
    sys.exit(main())
