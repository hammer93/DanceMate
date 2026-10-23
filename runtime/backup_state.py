"""Backup inventory shared by the runtime /status endpoint and backup.sh.

The naming contract is a single source of truth so that the shell tooling and
the Python health check can never disagree about what a backup looks like.
"""

from __future__ import annotations

import json
import re
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


def incomplete_reason(path: Path) -> str | None:
    """Why this backup is not one, or None when both parts are present and
    non-empty and - when the backup wrote a manifest - both recorded ok there
    (v0.96.51).

    A file merely existing was the old test: a failed pg_dump still leaves a
    `postgres.dump` behind, empty or cut short, and the manifest beside it
    said `"status": "failed"` while /status said PASS. A manifest that cannot
    be read is not evidence of success.
    """
    for name in (POSTGRES_DUMP, ENGINE_SQLITE):
        part = path / name
        if not part.is_file():
            return f"is missing {name}"
        if part.stat().st_size == 0:
            return f"has an empty {name}"
    manifest = path / MANIFEST
    if not manifest.exists():
        return None                      # older backups wrote none
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"has an unreadable {MANIFEST}"
    for part, name in (("postgres", POSTGRES_DUMP), ("engine_sqlite", ENGINE_SQLITE)):
        if str((data.get(part) or {}).get("status", "")).lower() != "ok":
            return f"records {name} as failed in its {MANIFEST}"
    if data.get("complete") is False:
        return f"is recorded incomplete in its {MANIFEST}"
    return None


def is_complete(path: Path) -> bool:
    return incomplete_reason(path) is None


def status(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    entries = list_backups(settings.backup_dir)
    if not entries:
        return {
            "status": "FAIL",
            "detail": f"no backup found under {settings.backup_dir}",
            "count": 0,
            "retention": settings.backup_retention,
        }
    latest = entries[0]
    age = now - latest.created_at
    problem = incomplete_reason(latest.path)
    stale = age > timedelta(hours=settings.backup_max_age_hours)
    if problem:
        state = "FAIL"
        detail = f"{latest.name} {problem}"
    elif stale:
        state = "WARN"
        detail = f"latest backup is {int(age.total_seconds() // 3600)}h old"
    else:
        state = "PASS"
        detail = "latest backup complete and current"
    return {
        "status": state,
        "detail": detail,
        "latest": latest.name,
        "latest_age_hours": round(age.total_seconds() / 3600, 1),
        "count": len(entries),
        "retention": settings.backup_retention,
        "max_age_hours": settings.backup_max_age_hours,
    }
