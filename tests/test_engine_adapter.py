"""Information Engine adapter and persistence paths (spec items 6, 7)."""

from __future__ import annotations

from runtime import engine_adapter


def test_engine_is_importable_from_the_repository(settings):
    report = engine_adapter.inspect(settings)
    assert report["checks"]["importable"] is True, report["checks"]["import_detail"]
    assert report["checks"]["package_present"] is True
    assert report["version"] == "0.75"


def test_adapter_targets_the_filename_the_engine_actually_uses():
    """engine/src/main.py db_path() hardcodes this name; keep them in sync."""
    from pathlib import Path

    main_py = Path(__file__).resolve().parents[1] / "engine" / "src" / "main.py"
    assert engine_adapter.ENGINE_DB_FILENAME in main_py.read_text(encoding="utf-8")


def test_persistence_path_follows_engine_data_dir(settings, env):
    expected = env / "engine-data" / engine_adapter.ENGINE_DB_FILENAME
    assert engine_adapter.engine_db_path(settings) == expected


def test_fresh_deployment_without_a_database_warns_rather_than_fails(settings):
    report = engine_adapter.inspect(settings)
    assert report["checks"]["sqlite_present"] is False
    assert report["status"] == "WARN"


def test_present_database_makes_the_component_pass(settings):
    engine_adapter.engine_db_path(settings).write_bytes(b"SQLite format 3\x00")
    report = engine_adapter.inspect(settings)
    assert report["checks"]["sqlite_present"] is True
    assert report["checks"]["sqlite_bytes"] > 0
    assert report["status"] == "PASS"


def test_missing_engine_tree_fails_and_never_raises(env, monkeypatch):
    from runtime.config import load_settings

    monkeypatch.setenv("ENGINE_ROOT", str(env / "no-such-engine"))
    report = engine_adapter.inspect(load_settings())
    assert report["status"] == "FAIL"
    assert report["checks"]["importable"] is False


def test_smoke_reports_failure_instead_of_raising_when_engine_is_absent(env, monkeypatch):
    from runtime.config import load_settings

    monkeypatch.setenv("ENGINE_ROOT", str(env / "no-such-engine"))
    result = engine_adapter.smoke(load_settings())
    assert result["status"] == "FAIL"
    assert "missing" in result["detail"]


def test_smoke_uses_a_read_only_engine_command():
    assert engine_adapter.SMOKE_COMMAND[-1] == "snapshot-list"
