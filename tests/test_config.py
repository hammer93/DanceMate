"""Environment validation and version reporting (spec items 3, 11, 13)."""

from __future__ import annotations

import pytest

from runtime import config


def test_defaults_load_without_any_environment(monkeypatch):
    for key in ("DANCEMATE_VERSION", "POSTGRES_HOST", "SCHEDULER_HEARTBEAT_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    loaded = config.load_settings()
    assert loaded.version == config.PRODUCT_VERSION == "0.76"
    assert loaded.postgres_host == "postgres"
    assert loaded.scheduler_heartbeat_seconds == 60


def test_product_and_engine_versions_are_distinct(settings):
    assert settings.version == "0.76"
    assert settings.engine_version == "0.73"


def test_valid_environment_reports_no_problems(settings):
    assert config.validate(settings) == []


def test_placeholder_password_is_rejected(env, monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "CHANGE_ME")
    problems = config.validate(config.load_settings())
    assert any("placeholder" in p for p in problems)


def test_empty_password_is_rejected(env, monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "")
    problems = config.validate(config.load_settings())
    assert any("empty" in p for p in problems)


@pytest.mark.parametrize("beat", ["1", "5", "29"])
def test_sub_30s_heartbeat_is_rejected_to_protect_the_microsd(env, monkeypatch, beat):
    monkeypatch.setenv("SCHEDULER_HEARTBEAT_SECONDS", beat)
    problems = config.validate(config.load_settings())
    assert any("SD card write pressure" in p for p in problems)


def test_inconsistent_storage_thresholds_are_rejected(env, monkeypatch):
    monkeypatch.setenv("STORAGE_WARN_PERCENT", "96")
    monkeypatch.setenv("STORAGE_CRITICAL_PERCENT", "95")
    assert any("STORAGE_WARN_PERCENT" in p for p in config.validate(config.load_settings()))


def test_zero_retention_is_rejected(env, monkeypatch):
    monkeypatch.setenv("BACKUP_RETENTION", "0")
    assert any("BACKUP_RETENTION" in p for p in config.validate(config.load_settings()))


def test_safe_dsn_never_carries_the_password(settings):
    assert settings.postgres_password in settings.dsn
    assert settings.postgres_password not in settings.safe_dsn
    assert "password" not in settings.safe_dsn


def test_non_numeric_port_falls_back_instead_of_crashing(env, monkeypatch):
    monkeypatch.setenv("DANCEMATE_PORT", "not-a-number")
    assert config.load_settings().port == 8080
