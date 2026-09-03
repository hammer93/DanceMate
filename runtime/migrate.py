"""Minimal forward-only SQL migration runner for the runtime PostgreSQL schema.

Migrations are numbered files in ``migrations/runtime`` (``001_*.sql``).
Applied versions are recorded in ``schema_migrations`` with a checksum, so a
container restart re-runs nothing and an edited migration is reported instead
of being silently reapplied.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .config import REPO_ROOT, Settings
from .db import connect

MIGRATION_NAME = re.compile(r"^(\d{3,})_[A-Za-z0-9_\-]+\.sql$")

BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def migrations_dir() -> Path:
    return REPO_ROOT / "migrations" / "runtime"


def discover(directory: Path | None = None) -> list[Migration]:
    """Load migrations in version order. Rejects unparseable filenames loudly."""
    directory = directory or migrations_dir()
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_NAME.match(path.name)
        if not match:
            raise ValueError(f"migration filename not in NNN_name.sql form: {path.name}")
        found.append(
            Migration(
                version=match.group(1),
                name=path.stem,
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise ValueError(f"duplicate migration versions: {versions}")
    return found


def applied_versions(con) -> dict[str, str]:
    with con.cursor() as cur:
        cur.execute("SELECT version, checksum FROM schema_migrations")
        return dict(cur.fetchall())


def run(settings: Settings, directory: Path | None = None) -> dict[str, object]:
    """Apply pending migrations. Each migration commits in its own transaction."""
    pending_applied: list[str] = []
    drifted: list[str] = []
    found = discover(directory)

    with connect(settings) as con:
        with con.cursor() as cur:
            cur.execute(BOOTSTRAP)
        con.commit()

        already = applied_versions(con)
        for migration in found:
            recorded = already.get(migration.version)
            if recorded is not None:
                if recorded != migration.checksum:
                    drifted.append(migration.name)
                continue
            with con.cursor() as cur:
                cur.execute(migration.sql)
                cur.execute(
                    "INSERT INTO schema_migrations(version, name, checksum) "
                    "VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
            con.commit()
            pending_applied.append(migration.name)

    return {
        "discovered": [m.name for m in found],
        "applied": pending_applied,
        "already_applied": sorted(already),
        "checksum_drift": drifted,
    }


def main() -> int:  # pragma: no cover - container entrypoint
    from .config import load_settings

    result = run(load_settings())
    print(f"migrations discovered: {result['discovered']}")
    print(f"migrations applied:    {result['applied']}")
    if result["checksum_drift"]:
        print(f"WARNING checksum drift: {result['checksum_drift']}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
