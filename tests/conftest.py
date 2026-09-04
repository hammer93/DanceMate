"""Shared fixtures for the v0.74 runtime test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

BASE_ENV = {
    "DANCEMATE_ENV": "test",
    "DANCEMATE_VERSION": "0.80",
    "ENGINE_VERSION": "0.75",
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


# --- PostgreSQL-backed fixtures ---------------------------------------------
#
# The master-data, source and intake modules are SQL. Testing them against a
# mock would only prove the mock works, so these fixtures use a real database
# and skip when none is reachable.
#
# On a developer host PostgreSQL is not published (compose uses `expose`, and a
# test asserts it stays that way), so these tests skip there and run inside the
# runtime container:
#
#     docker compose exec -T runtime python -m pytest -q tests/
#
# Every test runs in a transaction that is rolled back, so a shared staging
# database is never polluted.

_UNIQUE_COUNTER = {"n": 0}

# Captured at import, before any fixture rewrites the environment. The `env`
# fixture deliberately installs a fake POSTGRES_PASSWORD so config tests are
# deterministic; the SQL tests need the real one back.
_REAL_POSTGRES = {
    key: os.environ.get(f"TEST_{key}") or os.environ.get(key)
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
                "POSTGRES_USER", "POSTGRES_PASSWORD")
}


@pytest.fixture
def pg(env, monkeypatch):
    """An open, rolled-back PostgreSQL connection, or a skip."""
    from runtime import db
    from runtime.config import load_settings

    if not _REAL_POSTGRES.get("POSTGRES_PASSWORD"):
        pytest.skip(
            "no PostgreSQL credentials in the environment; "
            "run these from inside the runtime container"
        )
    for key, value in _REAL_POSTGRES.items():
        if value:
            monkeypatch.setenv(key, value)

    settings = load_settings()
    try:
        with db.connect(settings) as con:
            yield con
            # Never commit: a shared staging database must survive the suite.
            con.rollback()
    except db.DatabaseUnavailable as exc:
        pytest.skip(f"no PostgreSQL reachable for the SQL tests: {exc}")


@pytest.fixture
def unique() -> str:
    """A short suffix so repeated runs do not collide on unique indexes."""
    import time

    _UNIQUE_COUNTER["n"] += 1
    return f"{int(time.time()) % 100000}{_UNIQUE_COUNTER['n']}"


@pytest.fixture
def seoul_id(pg) -> int:
    from runtime import master_data

    for region in master_data.list_regions(pg):
        if region["code"] == "KR-SEOUL":
            return region["region_id"]
    pytest.skip("KR-SEOUL region is not seeded; run the migrations first")


@pytest.fixture
def committed_sources():
    """source_ids created through a real, committing connection (e.g. a
    TestClient POST to the admin API), deleted for real at teardown.

    `pg` is safe to leave uncommitted - rolled back at teardown, so a shared
    staging database is never polluted. But a route test that needs the
    running app itself to see created data has to write through a real,
    committing path (a TestClient request, whose admin API opens its own
    autocommit connection) - and on a board where PostgreSQL accepts any
    password (trust auth, confirmed directly against this project's board),
    that path reaches the actual shared database regardless of which fake
    credentials a test's `env` fixture set. Without an explicit, immediately-
    committed cleanup here, every such test permanently leaks a row into
    production - which is exactly what happened before this fixture existed:
    six rows from early v0.82 test runs had to be hand-deleted from the real
    board database once discovered.
    """
    ids: list[int] = []
    yield ids
    if not ids:
        return
    from runtime import db
    from runtime.config import load_settings

    settings = load_settings()
    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute(
                "DELETE FROM source_collection_runs WHERE source_id = ANY(%s)", (ids,)
            )
            cur.execute("DELETE FROM sources WHERE source_id = ANY(%s)", (ids,))


@pytest.fixture
def engine_settings(env, monkeypatch):
    """Settings pointing ENGINE_DATA_DIR at the repository's engine fixtures.

    The snapshot collectors read recorded API responses from there, so the
    variable has to be set before Settings is built - hence one fixture rather
    than a settings/fixtures pair whose resolution order would matter.
    Read-only: only the snapshot JSON files are opened.
    """
    from runtime.config import load_settings

    data_dir = REPO_ROOT / "engine" / "data"
    if not (data_dir / "collector_snapshots").is_dir():
        pytest.skip("engine collector fixtures are not present")
    monkeypatch.setenv("ENGINE_DATA_DIR", str(data_dir))
    return load_settings()
