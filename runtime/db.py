"""PostgreSQL access for the DanceMate runtime.

psycopg is imported lazily so that unit tests, config validation and the
static ARM64 checks all work on a machine without the driver installed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from .config import Settings


class DatabaseUnavailable(RuntimeError):
    """Raised when PostgreSQL cannot be reached or the driver is missing."""


def _psycopg():
    try:
        import psycopg  # noqa: PLC0415 - deliberately lazy
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise DatabaseUnavailable(f"psycopg is not installed: {exc}") from exc
    return psycopg


@contextmanager
def connect(settings: Settings, *, autocommit: bool = False) -> Iterator[Any]:
    psycopg = _psycopg()
    try:
        con = psycopg.connect(settings.dsn, autocommit=autocommit, connect_timeout=5)
    except Exception as exc:  # pragma: no cover - needs a live server
        raise DatabaseUnavailable(str(exc)) from exc
    try:
        yield con
    finally:
        con.close()


def ping(settings: Settings) -> dict[str, Any]:
    """Cheap liveness probe. Never raises."""
    try:
        with connect(settings, autocommit=True) as con:
            with con.cursor() as cur:
                cur.execute("SELECT version()")
                server = cur.fetchone()[0]
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                tables = cur.fetchone()[0]
        return {
            "status": "PASS",
            "server": server.split(" on ")[0],
            "public_tables": tables,
            "dsn": settings.safe_dsn,
        }
    except DatabaseUnavailable as exc:
        return {"status": "FAIL", "detail": str(exc), "dsn": settings.safe_dsn}
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "FAIL", "detail": repr(exc), "dsn": settings.safe_dsn}


def set_runtime_state(settings: Settings, key: str, value: str) -> None:
    with connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO runtime_state(state_key, state_value, updated_at) "
                "VALUES (%s, %s, now()) "
                "ON CONFLICT (state_key) DO UPDATE "
                "SET state_value = EXCLUDED.state_value, updated_at = now()",
                (key, value),
            )


def get_runtime_state(settings: Settings, key: str) -> str | None:
    with connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT state_value FROM runtime_state WHERE state_key = %s", (key,)
            )
            row = cur.fetchone()
    return None if row is None else row[0]


def latest_heartbeat(settings: Settings, worker: str = "scheduler") -> dict[str, Any]:
    """Read the scheduler heartbeat row.

    ``available`` says whether the probe itself worked; ``worker_status`` is
    what the worker last wrote. Keeping them apart stops a healthy probe of an
    unhealthy worker from reading as PASS.
    """
    try:
        with connect(settings, autocommit=True) as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT status, detail, last_beat_at, "
                    "       EXTRACT(EPOCH FROM (now() - last_beat_at))::bigint "
                    "FROM scheduler_heartbeat WHERE worker = %s",
                    (worker,),
                )
                row = cur.fetchone()
    except DatabaseUnavailable as exc:
        return {"available": False, "detail": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "detail": repr(exc)}
    if row is None:
        return {
            "available": True,
            "worker_status": None,
            "detail": "no heartbeat recorded yet",
        }
    worker_status, detail, last_beat_at, age = row
    return {
        "available": True,
        "worker_status": worker_status,
        "detail": detail,
        "last_beat_at": last_beat_at.isoformat() if last_beat_at else None,
        "age_seconds": int(age),
    }
