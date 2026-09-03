"""Runtime PostgreSQL migrations (spec item 4)."""

from __future__ import annotations

import pytest

from runtime import migrate


def test_initial_migration_is_discovered():
    found = migrate.discover()
    assert [m.name for m in found] == ["001_initial_runtime"]
    assert found[0].version == "001"


def test_initial_migration_creates_the_v074_runtime_tables():
    sql = migrate.discover()[0].sql.lower()
    for table in ("runtime_state", "scheduler_heartbeat", "job_runs"):
        assert f"create table if not exists {table}" in sql


def test_migrations_are_idempotent_by_construction():
    sql = migrate.discover()[0].sql.lower()
    # A container restart must not fail on an existing schema.
    assert sql.count("create table") == sql.count("create table if not exists")
    assert sql.count("create index") == sql.count("create index if not exists")


def test_no_engine_table_is_mirrored_into_postgres():
    """Hybrid persistence: the Information Engine keeps its own SQLite store."""
    sql = migrate.discover()[0].sql.lower()
    for engine_table in ("raw_posts", "event_candidates", "evidences", "event_instances"):
        assert engine_table not in sql


def test_checksum_changes_when_a_migration_changes(tmp_path):
    path = tmp_path / "001_x.sql"
    path.write_text("SELECT 1;", encoding="utf-8")
    first = migrate.discover(tmp_path)[0].checksum
    path.write_text("SELECT 2;", encoding="utf-8")
    assert migrate.discover(tmp_path)[0].checksum != first


def test_badly_named_migration_is_rejected(tmp_path):
    (tmp_path / "initial.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="NNN_name.sql"):
        migrate.discover(tmp_path)


def test_duplicate_versions_are_rejected(tmp_path):
    (tmp_path / "001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "001_b.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate migration versions"):
        migrate.discover(tmp_path)


def test_migrations_apply_in_version_order(tmp_path):
    for name in ("003_c.sql", "001_a.sql", "002_b.sql"):
        (tmp_path / name).write_text("SELECT 1;", encoding="utf-8")
    assert [m.version for m in migrate.discover(tmp_path)] == ["001", "002", "003"]
