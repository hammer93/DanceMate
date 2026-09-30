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
# test asserts it stays that way), so these tests run inside a container:
#
#     scripts/run-container-tests.sh
#
# which creates a disposable database, declares it so, migrates it, runs the
# suite against it and drops it again.
#
# v0.96.28: what used to stand here was
#
#     docker compose exec -T runtime python -m pytest -q tests/
#
# with the reassurance that "every test runs in a transaction that is rolled
# back, so a shared staging database is never polluted". That was false, and it
# cost two releases (v0.96.14: 1,852 Production rows stamped; v0.96.27: 50). The
# `pg` fixture below owns one connection and rolls it back; nine other test call
# sites and most of the runtime open their own `db.connect(settings,
# autocommit=True)` and commit through it. `engine_ingest.reprocess_acquired()`
# is the one that bit: it stamps the re-extract cursor on real rows.
#
# So the suite no longer trusts a rollback to make a database safe. It asks the
# database, once, before any test runs - see `pytest_sessionstart` below and
# `runtime/scratch_db_guard.py` for why the answer is a database comment.

_UNIQUE_COUNTER = {"n": 0}

# Captured at import, before any fixture rewrites the environment. The `env`
# fixture deliberately installs a fake POSTGRES_PASSWORD so config tests are
# deterministic; the SQL tests need the real one back.
_REAL_POSTGRES = {
    key: os.environ.get(f"TEST_{key}") or os.environ.get(key)
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
                "POSTGRES_USER", "POSTGRES_PASSWORD")
}


def pytest_sessionstart(session):
    """Refuse the whole session unless the target database is expendable.

    Before any test runs, and about the database rather than about a connection
    to it - because the connections that did the damage in v0.96.14 and v0.96.27
    were not the fixture's. Two ways this exits quietly instead of failing:
    there are no credentials (a developer checkout with no PostgreSQL: the
    DB-backed tests already skip, and there is nothing to protect), or the
    database cannot be reached (same). A database that *is* reachable and does
    not declare itself disposable stops the run.
    """
    from runtime import scratch_db_guard

    target = _REAL_POSTGRES.get("POSTGRES_DB")
    if not (target and _REAL_POSTGRES.get("POSTGRES_PASSWORD")):
        return

    deployment = None
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("POSTGRES_DB="):
                deployment = line.split("=", 1)[1].strip()

    collision = scratch_db_guard.deployment_collision_report(target, deployment)
    if collision["status"] != "PASS":
        pytest.exit(f"TEST DB TARGET: {target}\n{collision['detail']}", returncode=3)

    from runtime import db
    from runtime.config import load_settings

    saved = {k: os.environ.get(k) for k in _REAL_POSTGRES}
    try:
        for key, value in _REAL_POSTGRES.items():
            if value:
                os.environ[key] = value
        try:
            with db.connect(load_settings()) as con, con.cursor() as cur:
                cur.execute(scratch_db_guard.MARKER_READ_SQL)
                row = cur.fetchone()
                marker = row[0] if row else None
        except Exception as exc:  # noqa: BLE001
            # A connection that cannot be made cannot commit either, so an
            # unreachable or unauthenticated database is left to the existing
            # skip: refusing here would only stop a developer whose PostgreSQL
            # is down from running the 2,000 tests that need none of it. Said
            # out loud, though - a silent pass is how this whole class of
            # problem stayed invisible for two releases.
            print(f"TEST DB TARGET: {target} [UNREACHABLE: "
                  f"{type(exc).__name__}] - DB-backed tests will skip")
            return
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    verdict = scratch_db_guard.disposable_report(marker, target)
    print(f"TEST DB TARGET: {target} [{verdict['status']}]")
    if verdict["status"] != "PASS":
        pytest.exit(f"TEST DB TARGET: {target}\n{verdict['detail']}", returncode=3)


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
            # Never commit: one test's rows must not be another's fixture. That
            # is all this buys - it does not make the *database* safe, which is
            # what `pytest_sessionstart` above is for.
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
def seoul_name(pg) -> str:
    """The region master's current display name for KR-SEOUL.

    v0.82.1: an admin renamed regions.name from "Seoul" to "서울" on the live
    staging database. A test that hardcodes "Seoul" is asserting a global
    value it does not own; this fixture reads whatever name is live right now,
    so the assertion tracks the master instead of freezing a snapshot of it.
    """
    from runtime import master_data

    for region in master_data.list_regions(pg):
        if region["code"] == "KR-SEOUL":
            return region["name"]
    pytest.skip("KR-SEOUL region is not seeded; run the migrations first")


@pytest.fixture
def busan_name(pg) -> str:
    """The region master's current display name for KR-BUSAN (see seoul_name)."""
    from runtime import master_data

    for region in master_data.list_regions(pg):
        if region["code"] == "KR-BUSAN":
            return region["name"]
    pytest.skip("KR-BUSAN region is not seeded; run the migrations first")


@pytest.fixture
def gwangju_id(pg) -> int:
    """v0.83.2: migration 025 (see seoul_id)."""
    from runtime import master_data

    for region in master_data.list_regions(pg):
        if region["code"] == "KR-GWANGJU":
            return region["region_id"]
    pytest.skip("KR-GWANGJU region is not seeded; run the migrations first")


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


def register_venue(con, name: str | None, *, region_code: str = "KR-SEOUL"):
    """Put a venue string in the Venue Master, the way the Admin would.

    v0.96.23: an automatic duplicate merge needs a *resolved* place. Identical
    words for a venue nothing has resolved are a question for a person now, not
    a merge - two posts can write the same words for two different places, and
    a string nobody has matched to anywhere may not be a place at all (found
    live: one poster's Instagram handle, OCR'd, attached to eighteen DanceInfo
    listings in eight cities).

    So a test that invents a studio and then expects two posts about one night
    to fold has to register that studio first. Resolves before creating, so
    calling it twice for one name is safe and a shared database is never given
    a second row for the same place.
    """
    from runtime import master_data

    if not (name or "").strip():
        return None
    existing = master_data.resolve_venue(con, name)
    if existing:
        return existing
    region_id = next((r["region_id"] for r in master_data.list_regions(con)
                      if r["code"] == region_code), None)
    return master_data.create_venue(con, name=name, region_id=region_id)
