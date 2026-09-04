"""Environment-driven configuration for the DanceMate runtime and scheduler.

Every value has a safe default so the module imports (and the unit tests run)
without any environment set up. Nothing here reads a secret from disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Product runtime version. Deliberately distinct from the Information Engine
# version: the Information Engine is versioned by its own extraction
# behaviour. v0.74 is the first version DanceMate modified (time, venue and
# fee reading); the untouched import is tagged engine-v0.73-baseline.
PRODUCT_VERSION = "0.77.3"
DEFAULT_ENGINE_VERSION = "0.74"

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# DANCEMATE_HOST and DANCEMATE_BIND_ADDRESS are NOT the same thing:
#
#   DANCEMATE_HOST          the address the server listens on INSIDE the
#                           container. Almost always 0.0.0.0 - a container has
#                           no LAN address of its own, so binding the host's
#                           LAN IP here fails with "could not bind on any
#                           address".
#   DANCEMATE_BIND_ADDRESS  the HOST interface Docker publishes the port on.
#                           Compose and the health scripts read it; the
#                           application never does.


@dataclass(frozen=True)
class Settings:
    env: str
    version: str
    engine_version: str

    listen_address: str
    port: int

    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str

    engine_root: Path
    engine_data_dir: Path
    data_dir: Path
    log_dir: Path
    backup_dir: Path

    scheduler_heartbeat_seconds: int
    scheduler_job_interval_seconds: int

    storage_warn_percent: int
    storage_critical_percent: int
    backup_retention: int
    backup_max_age_hours: int

    @property
    def dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} "
            f"password={self.postgres_password}"
        )

    @property
    def safe_dsn(self) -> str:
        """DSN with the password removed - safe to log or return over HTTP."""
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user}"
        )


def load_settings() -> Settings:
    engine_root = Path(_env("ENGINE_ROOT", str(REPO_ROOT / "engine")))
    return Settings(
        env=_env("DANCEMATE_ENV", "staging"),
        version=_env("DANCEMATE_VERSION", PRODUCT_VERSION),
        engine_version=_env("ENGINE_VERSION", DEFAULT_ENGINE_VERSION),
        listen_address=_env("DANCEMATE_HOST", "0.0.0.0"),
        port=_env_int("DANCEMATE_PORT", 8080),
        postgres_host=_env("POSTGRES_HOST", "postgres"),
        postgres_port=_env_int("POSTGRES_PORT", 5432),
        postgres_db=_env("POSTGRES_DB", "dancemate"),
        postgres_user=_env("POSTGRES_USER", "dancemate"),
        postgres_password=_env("POSTGRES_PASSWORD", ""),
        engine_root=engine_root,
        engine_data_dir=Path(_env("ENGINE_DATA_DIR", str(engine_root / "data"))),
        data_dir=Path(_env("DANCEMATE_DATA_DIR", str(REPO_ROOT / "data"))),
        log_dir=Path(_env("DANCEMATE_LOG_DIR", str(REPO_ROOT / "logs"))),
        backup_dir=Path(_env("DANCEMATE_BACKUP_DIR", str(REPO_ROOT / "backup"))),
        scheduler_heartbeat_seconds=_env_int("SCHEDULER_HEARTBEAT_SECONDS", 60),
        scheduler_job_interval_seconds=_env_int("SCHEDULER_JOB_INTERVAL_SECONDS", 300),
        storage_warn_percent=_env_int("STORAGE_WARN_PERCENT", 75),
        storage_critical_percent=_env_int("STORAGE_CRITICAL_PERCENT", 95),
        backup_retention=_env_int("BACKUP_RETENTION", 7),
        backup_max_age_hours=_env_int("BACKUP_MAX_AGE_HOURS", 48),
    )


def validate(settings: Settings) -> list[str]:
    """Return a list of configuration problems. Empty list means valid."""
    problems: list[str] = []
    if not settings.postgres_password:
        problems.append("POSTGRES_PASSWORD is empty")
    if settings.postgres_password == "CHANGE_ME":
        problems.append("POSTGRES_PASSWORD is still the .env.example placeholder")
    if not 1 <= settings.port <= 65535:
        problems.append(f"DANCEMATE_PORT out of range: {settings.port}")
    if settings.scheduler_heartbeat_seconds < 30:
        problems.append(
            "SCHEDULER_HEARTBEAT_SECONDS below 30 - too much SD card write pressure"
        )
    if not 1 <= settings.storage_warn_percent < settings.storage_critical_percent <= 100:
        problems.append("STORAGE_WARN_PERCENT/STORAGE_CRITICAL_PERCENT are inconsistent")
    if settings.backup_retention < 1:
        problems.append("BACKUP_RETENTION must be at least 1")
    return problems
