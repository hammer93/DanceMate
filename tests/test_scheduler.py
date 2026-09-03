"""Scheduler heartbeat, job registry and graceful shutdown (spec item 5)."""

from __future__ import annotations

import pytest

from runtime import db
from scheduler import jobs, worker


def test_heartbeat_is_floored_regardless_of_the_environment(env, monkeypatch):
    from runtime.config import load_settings

    monkeypatch.setenv("SCHEDULER_HEARTBEAT_SECONDS", "1")
    assert worker.effective_heartbeat(load_settings()) == worker.MIN_HEARTBEAT_SECONDS


def test_configured_heartbeat_is_used_when_above_the_floor(settings):
    assert worker.effective_heartbeat(settings) == 60


def test_floor_protects_the_microsd_from_per_second_writes():
    assert worker.MIN_HEARTBEAT_SECONDS >= 30


def test_shutdown_flag_starts_clear_and_latches():
    shutdown = worker.Shutdown()
    assert not shutdown.requested
    shutdown.request()
    assert shutdown.requested
    # already set -> wait returns immediately rather than sleeping
    assert shutdown.wait(30) is True


def test_run_forever_exits_cleanly_when_shutdown_is_already_requested(settings, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(db, "set_runtime_state", lambda *a, **k: calls.append("state"))
    monkeypatch.setattr(worker.db, "set_runtime_state", lambda *a, **k: calls.append("state"))
    monkeypatch.setattr(worker, "write_heartbeat", lambda *a, **k: calls.append("beat"))

    shutdown = worker.Shutdown()
    shutdown.request()
    assert worker.run_forever(settings, shutdown) == 0
    # loop body skipped; only the final STOPPED heartbeat is written
    assert calls == ["state", "beat"]


def test_registered_jobs_are_self_checks_only_in_v074():
    assert sorted(jobs.REGISTRY) == ["engine-availability", "storage-probe"]


def test_unknown_job_names_the_known_jobs():
    with pytest.raises(KeyError, match="engine-availability"):
        jobs.get("collect-daum")


def test_storage_probe_runs_without_a_database(settings):
    detail = jobs.storage_probe(settings)
    assert detail.startswith("storage=")


def test_engine_availability_job_reports_the_real_engine(settings):
    detail = jobs.engine_availability(settings)
    assert "importable=True" in detail


def test_scheduler_component_fails_when_no_heartbeat_exists(settings, monkeypatch):
    from runtime import health

    monkeypatch.setattr(
        health.db,
        "latest_heartbeat",
        lambda *a, **k: {"available": True, "worker_status": None, "detail": "none"},
    )
    assert health.scheduler_component(settings)["status"] == "FAIL"


def test_scheduler_component_fails_when_the_database_probe_fails(settings, monkeypatch):
    from runtime import health

    monkeypatch.setattr(
        health.db, "latest_heartbeat", lambda *a, **k: {"available": False, "detail": "down"}
    )
    assert health.scheduler_component(settings)["status"] == "FAIL"


def test_scheduler_component_fails_when_the_worker_reported_a_failure(settings, monkeypatch):
    from runtime import health

    monkeypatch.setattr(
        health.db,
        "latest_heartbeat",
        lambda *a, **k: {"available": True, "worker_status": "FAIL", "age_seconds": 5},
    )
    assert health.scheduler_component(settings)["status"] == "FAIL"


def test_scheduler_component_fails_after_a_graceful_stop(settings, monkeypatch):
    from runtime import health

    monkeypatch.setattr(
        health.db,
        "latest_heartbeat",
        lambda *a, **k: {"available": True, "worker_status": "STOPPED", "age_seconds": 5},
    )
    assert health.scheduler_component(settings)["status"] == "FAIL"


@pytest.mark.parametrize(
    "age,expected",
    [(0, "PASS"), (60, "PASS"), (119, "PASS"), (121, "WARN"), (181, "FAIL")],
)
def test_scheduler_component_grades_heartbeat_age(settings, monkeypatch, age, expected):
    from runtime import health

    monkeypatch.setattr(
        health.db,
        "latest_heartbeat",
        lambda *a, **k: {"available": True, "worker_status": "PASS", "age_seconds": age},
    )
    assert health.scheduler_component(settings)["status"] == expected
