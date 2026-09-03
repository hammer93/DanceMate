"""Runtime PostgreSQL migrations (spec item 4)."""

from __future__ import annotations

import pytest

from runtime import migrate


def test_migrations_are_discovered_in_order():
    found = migrate.discover()
    assert [m.name for m in found] == [
        "001_initial_runtime",
        "002_master_data",
        "003_source_intake",
    ]
    assert [m.version for m in found] == ["001", "002", "003"]


def test_initial_migration_creates_the_v074_runtime_tables():
    sql = migrate.discover()[0].sql.lower()
    for table in ("runtime_state", "scheduler_heartbeat", "job_runs"):
        assert f"create table if not exists {table}" in sql


def test_migrations_are_idempotent_by_construction():
    """A container restart must not fail on an existing schema."""
    for migration in migrate.discover():
        sql = migration.sql.lower()
        assert sql.count("create table") == sql.count("create table if not exists"), migration.name
        assert sql.count("create index") == sql.count("create index if not exists"), migration.name


def test_master_data_migration_creates_the_v075_tables():
    sql = migrate.discover()[1].sql.lower()
    for table in ("genres", "regions", "venues", "venue_aliases", "organizers"):
        assert f"create table if not exists {table}" in sql


def test_master_data_migration_seeds_only_decided_reference_data():
    sql = migrate.discover()[1].sql
    for code in ("TANGO", "SALSA", "SWING"):
        assert f"'{code}'" in sql
    assert "KR-SEOUL" in sql
    # No invented venues or organizers.
    assert "INSERT INTO venues" not in sql
    assert "INSERT INTO organizers" not in sql


def test_source_intake_migration_creates_the_v075_tables():
    sql = migrate.discover()[2].sql.lower()
    for table in ("sources", "source_collection_runs", "source_items", "source_errors"):
        assert f"create table if not exists {table}" in sql


def test_source_intake_migration_constrains_polling_and_duplicates():
    sql = migrate.discover()[2].sql.lower()
    # A source must not be pollable faster than every 10 minutes.
    assert "collection_interval_minutes >= 10" in sql
    # The same upstream item from the same source is stored once.
    assert "source_items_source_external_key" in sql
    assert "sources_url_unique" in sql


def test_no_engine_table_is_mirrored_into_postgres():
    """Hybrid persistence: the Information Engine keeps its own SQLite store."""
    for migration in migrate.discover():
        sql = migration.sql.lower()
        for engine_table in ("raw_posts", "event_candidates", "evidences", "event_instances"):
            assert f"table if not exists {engine_table}" not in sql, migration.name


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
