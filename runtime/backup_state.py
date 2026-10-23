"""Backup inventory shared by the runtime /status endpoint and backup.sh.

The naming contract is a single source of truth so that the shell tooling and
the Python health check can never disagree about what a backup looks like.
"""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Settings

# dancemate-backup-YYYYmmdd-HHMMSS
BACKUP_DIR_NAME = re.compile(r"^dancemate-backup-(\d{8})-(\d{6})$")
BACKUP_PREFIX = "dancemate-backup"
POSTGRES_DUMP = "postgres.dump"
ENGINE_SQLITE = "engine.sqlite3"
MANIFEST = "manifest.json"
# backup.sh writes into `.inprogress-<name>` and renames it into the naming
# contract only once it is complete, verified and readable by the runtime
# (v0.96.51 recovery), so a backup being written is never the latest one.
IN_PROGRESS_PREFIX = ".inprogress-"

# Why the Backup component is not PASS - stable codes for /status, the
# operations monitor and the audit (v0.96.51 recovery). The detail text
# beside them is for people and may change.
REASON_NONE = "BACKUP_NONE"
REASON_PERMISSION_DENIED = "BACKUP_PERMISSION_DENIED"
REASON_UNREADABLE = "BACKUP_UNREADABLE"
REASON_PART_MISSING = "BACKUP_PART_MISSING"
REASON_PART_EMPTY = "BACKUP_PART_EMPTY"
REASON_SIZE_MISMATCH = "BACKUP_SIZE_MISMATCH"
REASON_MANIFEST_UNREADABLE = "BACKUP_MANIFEST_UNREADABLE"
REASON_RECORDED_FAILED = "BACKUP_RECORDED_FAILED"
REASON_RECORDED_INCOMPLETE = "BACKUP_RECORDED_INCOMPLETE"
REASON_STALE = "BACKUP_STALE"


def backup_name(moment: datetime) -> str:
    return f"{BACKUP_PREFIX}-{moment.strftime('%Y%m%d-%H%M%S')}"


def parse_backup_name(name: str) -> datetime | None:
    match = BACKUP_DIR_NAME.match(name)
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass(frozen=True)
class BackupEntry:
    name: str
    created_at: datetime
    path: Path


def list_backups(backup_dir: Path) -> list[BackupEntry]:
    """Newest first. Ignores anything that does not match the naming contract."""
    if not backup_dir.is_dir():
        return []
    entries: list[BackupEntry] = []
    for child in backup_dir.iterdir():
        if not child.is_dir():
            continue
        created = parse_backup_name(child.name)
        if created is None:
            continue
        entries.append(BackupEntry(child.name, created, child))
    return sorted(entries, key=lambda e: e.created_at, reverse=True)


def prune(backup_dir: Path, retention: int) -> list[str]:
    """Return the names that exceed the retention window (oldest first).

    This only decides *what* to delete; deletion itself stays in backup.sh so
    that no import of this module can remove an operator's data.
    """
    if retention < 1:
        raise ValueError("retention must be at least 1")
    entries = list_backups(backup_dir)
    return [e.name for e in reversed(entries[retention:])]


def retention_split(names: "Iterable[str]", retention: int) -> tuple[list[str], list[str]]:
    """(kept, pruned) exactly as scripts/backup.sh's retention decides it:
    every `dancemate-backup-*` directory name, newest first by name (the
    names are timestamps), the first ``retention`` kept - regardless of who
    owns them. Ownership decides only whether the prune *succeeds*."""
    if retention < 1:
        raise ValueError("retention must be at least 1")
    ordered = sorted((n for n in names if n.startswith(BACKUP_PREFIX + "-")), reverse=True)
    return ordered[:retention], ordered[retention:]


def foreign_owned(owners: "dict[str, str]", owner: str) -> list[str]:
    """Backup directories not owned by the deployment user - what
    `scripts/fix-ownership.sh --backups` reclaims (and nothing else)."""
    return sorted(name for name, who in owners.items()
                  if name.startswith(BACKUP_PREFIX + "-") and who != owner)


def _os_failure(exc: OSError, what: str) -> tuple[str, str]:
    if isinstance(exc, PermissionError):
        return REASON_PERMISSION_DENIED, f"{what} cannot be read by the runtime (permission denied)"
    return REASON_UNREADABLE, f"{what} cannot be read by the runtime ({type(exc).__name__})"


def inspect(path: Path) -> tuple[str, str] | None:
    """(reason, detail) for why this backup is not one, or None when both
    parts are present and non-empty and - when the backup wrote a manifest -
    both recorded ok there, at the sizes it recorded (v0.96.51).

    A file merely existing was the old test: a failed pg_dump still leaves a
    `postgres.dump` behind, empty or cut short, and the manifest beside it
    said `"status": "failed"` while /status said PASS. A manifest that cannot
    be read is not evidence of success.

    Only metadata is needed: a part is stat()ed, never opened, so the dumps
    themselves may stay private to the backup owner (0600) - the runtime
    needs search permission on the directory and read permission on the
    manifest, nothing more. A path the runtime may not read is a FAIL with
    a reason, never an exception out of /status (v0.96.51 recovery: the
    deploy that hit a 0700 backup answered /status with HTTP 500).
    """
    sizes: dict[str, int] = {}
    for name in (POSTGRES_DUMP, ENGINE_SQLITE):
        part = path / name
        try:
            info = part.stat()
        except FileNotFoundError:
            return REASON_PART_MISSING, f"is missing {name}"
        except OSError as exc:
            return _os_failure(exc, name)
        if not stat.S_ISREG(info.st_mode):
            return REASON_PART_MISSING, f"is missing {name}"
        if info.st_size == 0:
            return REASON_PART_EMPTY, f"has an empty {name}"
        sizes[name] = info.st_size
    manifest = path / MANIFEST
    try:
        text = manifest.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None                      # older backups wrote none
    except OSError as exc:
        return _os_failure(exc, MANIFEST)
    try:
        data = json.loads(text)
    except ValueError:
        return REASON_MANIFEST_UNREADABLE, f"has an unreadable {MANIFEST}"
    if not isinstance(data, dict):
        return REASON_MANIFEST_UNREADABLE, f"has an unreadable {MANIFEST}"
    for part, name in (("postgres", POSTGRES_DUMP), ("engine_sqlite", ENGINE_SQLITE)):
        record = data.get(part) or {}
        if str(record.get("status", "")).lower() != "ok":
            return REASON_RECORDED_FAILED, f"records {name} as failed in its {MANIFEST}"
        recorded = record.get("bytes")
        if isinstance(recorded, int) and recorded != sizes[name]:
            return (REASON_SIZE_MISMATCH,
                    f"has a {name} of {sizes[name]} bytes where its {MANIFEST} recorded {recorded}")
    if data.get("complete") is False:
        return REASON_RECORDED_INCOMPLETE, f"is recorded incomplete in its {MANIFEST}"
    return None


def incomplete_reason(path: Path) -> str | None:
    """The detail text of inspect(), or None for a complete backup."""
    found = inspect(path)
    return found[1] if found else None


def in_progress(backup_dir: Path) -> list[str]:
    """Names of backups being written now (backup.sh holds its lock)."""
    try:
        return sorted(child.name[len(IN_PROGRESS_PREFIX):] for child in backup_dir.iterdir()
                      if child.name.startswith(IN_PROGRESS_PREFIX))
    except OSError:
        return []


def is_complete(path: Path) -> bool:
    return incomplete_reason(path) is None


def status(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    try:
        entries = list_backups(settings.backup_dir)
    except OSError as exc:
        reason, detail = _os_failure(exc, f"backup directory {settings.backup_dir}")
        return {
            "status": "FAIL",
            "reason": reason,
            "detail": detail,
            "count": 0,
            "retention": settings.backup_retention,
        }
    if not entries:
        return {
            "status": "FAIL",
            "reason": REASON_NONE,
            "detail": f"no backup found under {settings.backup_dir}",
            "count": 0,
            "retention": settings.backup_retention,
        }
    latest = entries[0]
    age = now - latest.created_at
    problem = inspect(latest.path)
    stale = age > timedelta(hours=settings.backup_max_age_hours)
    if problem:
        state = "FAIL"
        reason, why = problem
        detail = f"{latest.name} {why}"
    elif stale:
        state = "WARN"
        reason = REASON_STALE
        detail = f"latest backup is {int(age.total_seconds() // 3600)}h old"
    else:
        state = "PASS"
        reason = None
        detail = "latest backup complete and current"
    result: dict[str, Any] = {
        "status": state,
        "detail": detail,
        "latest": latest.name,
        "latest_age_hours": round(age.total_seconds() / 3600, 1),
        "count": len(entries),
        "retention": settings.backup_retention,
        "max_age_hours": settings.backup_max_age_hours,
    }
    if reason:
        result["reason"] = reason
    running = in_progress(settings.backup_dir)
    if running:
        result["in_progress"] = running
    return result
