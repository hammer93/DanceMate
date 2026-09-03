"""The DanceMate scheduler worker loop.

Design constraints for the ROCKPro64 target:
  * one process, no broker, no Celery, no Redis
  * heartbeat interval is configurable and floored at 30s so the microSD is
    not hammered with writes
  * job history is written once per job run, not per tick
  * SIGTERM / SIGINT drain the current tick and exit 0 so ``docker compose
    stop`` is a clean shutdown rather than a kill
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Any

from runtime import db
from runtime.config import Settings

from . import jobs

log = logging.getLogger("dancemate.scheduler")

WORKER_NAME = "scheduler"
MIN_HEARTBEAT_SECONDS = 30


class Shutdown:
    """Cooperative stop flag driven by SIGTERM/SIGINT."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self, signum: int | None = None, frame: Any = None) -> None:
        if signum is not None:
            log.info("received signal %s, draining", signum)
        self._event.set()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> bool:
        """Sleep in one interruptible chunk. True if a stop was requested."""
        return self._event.wait(seconds)

    def install(self) -> None:  # pragma: no cover - signal wiring
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self.request)
            except (ValueError, OSError):
                pass


def effective_heartbeat(settings: Settings) -> int:
    """Never beat faster than MIN_HEARTBEAT_SECONDS, whatever the env says."""
    return max(MIN_HEARTBEAT_SECONDS, settings.scheduler_heartbeat_seconds)


def write_heartbeat(settings: Settings, status: str, detail: str) -> None:
    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO scheduler_heartbeat(worker, status, detail, last_beat_at) "
                "VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (worker) DO UPDATE "
                "SET status = EXCLUDED.status, detail = EXCLUDED.detail, "
                "    last_beat_at = now()",
                (WORKER_NAME, status, detail[:500]),
            )


def run_job(settings: Settings, name: str) -> dict[str, Any]:
    """Run one registered job and record exactly one job_runs row."""
    job = jobs.get(name)
    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO job_runs(job_name, status) VALUES (%s, 'RUNNING') "
                "RETURNING job_run_id",
                (name,),
            )
            job_run_id = cur.fetchone()[0]
    try:
        detail = job(settings)
        status = "PASS"
    except Exception as exc:  # a broken job must not kill the worker
        detail = f"{type(exc).__name__}: {exc}"
        status = "FAIL"
        log.exception("job %s failed", name)
    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute(
                "UPDATE job_runs SET status = %s, detail = %s, finished_at = now() "
                "WHERE job_run_id = %s",
                (status, detail[:500], job_run_id),
            )
    log.info("job %s -> %s (%s)", name, status, detail)
    return {"job_run_id": job_run_id, "job_name": name, "status": status, "detail": detail}


def run_forever(settings: Settings, shutdown: Shutdown | None = None) -> int:
    shutdown = shutdown or Shutdown()
    shutdown.install()

    beat_seconds = effective_heartbeat(settings)
    job_seconds = max(beat_seconds, settings.scheduler_job_interval_seconds)
    log.info(
        "scheduler starting: heartbeat=%ss jobs=%ss registry=%s",
        beat_seconds,
        job_seconds,
        sorted(jobs.REGISTRY),
    )

    db.set_runtime_state(settings, "scheduler.started_at", str(int(time.time())))
    next_job_at = 0.0

    while not shutdown.requested:
        now = time.monotonic()
        try:
            if now >= next_job_at:
                results = [run_job(settings, name) for name in sorted(jobs.REGISTRY)]
                failed = [r["job_name"] for r in results if r["status"] == "FAIL"]
                detail = "jobs ok" if not failed else f"failed jobs: {failed}"
                write_heartbeat(settings, "FAIL" if failed else "PASS", detail)
                next_job_at = now + job_seconds
            else:
                write_heartbeat(settings, "PASS", "idle")
        except db.DatabaseUnavailable as exc:
            log.error("database unavailable, retrying next tick: %s", exc)
        if shutdown.wait(beat_seconds):
            break

    log.info("scheduler stopped cleanly")
    try:
        write_heartbeat(settings, "STOPPED", "graceful shutdown")
    except db.DatabaseUnavailable:
        pass
    return 0
