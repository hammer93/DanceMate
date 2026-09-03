"""Shared fixtures for the v0.74 runtime test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

BASE_ENV = {
    "DANCEMATE_ENV": "test",
    "DANCEMATE_VERSION": "0.74",
    "ENGINE_VERSION": "0.73",
    "DANCEMATE_BIND_ADDRESS": "127.0.0.1",
    "DANCEMATE_PORT": "8080",
    "POSTGRES_HOST": "postgres",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "dancemate",
    "POSTGRES_USER": "dancemate",
    "POSTGRES_PASSWORD": "test-password",
    "SCHEDULER_HEARTBEAT_SECONDS": "60",
    "SCHEDULER_JOB_INTERVAL_SECONDS": "300",
    "STORAGE_WARN_PERCENT": "75",
    "STORAGE_CRITICAL_PERCENT": "95",
    "BACKUP_RETENTION": "7",
    "BACKUP_MAX_AGE_HOURS": "48",
}

# Every DANCEMATE_*/POSTGRES_*/ENGINE_* variable the runtime reads, so a value
# leaking in from the developer's shell cannot change a test outcome.
MANAGED_KEYS = tuple(BASE_ENV) + (
    "ENGINE_ROOT",
    "ENGINE_DATA_DIR",
    "DANCEMATE_DATA_DIR",
    "DANCEMATE_LOG_DIR",
    "DANCEMATE_BACKUP_DIR",
)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Deterministic environment with all runtime directories under tmp_path."""
    for key in MANAGED_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)

    for name in ("engine-data", "data", "logs", "backup"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ENGINE_ROOT", str(REPO_ROOT / "engine"))
    monkeypatch.setenv("ENGINE_DATA_DIR", str(tmp_path / "engine-data"))
    monkeypatch.setenv("DANCEMATE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DANCEMATE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DANCEMATE_BACKUP_DIR", str(tmp_path / "backup"))
    return tmp_path


@pytest.fixture
def settings(env):
    from runtime.config import load_settings

    return load_settings()


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


def read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")
