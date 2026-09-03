"""check-server report assembly and overall verdict (spec item 10)."""

from __future__ import annotations

import pytest

from runtime import health


def payload(**overrides):
    base = {name: {"status": "PASS"} for name in health.COMPONENTS}
    base.update({name: {"status": value} for name, value in overrides.items()})
    return base


def test_all_pass_is_pass():
    assert health.overall(payload()) == "PASS"


def test_worst_component_wins():
    assert health.overall(payload(backup="WARN")) == "WARN"
    assert health.overall(payload(backup="WARN", database="FAIL")) == "FAIL"


def test_a_missing_component_counts_as_fail():
    incomplete = payload()
    del incomplete["scheduler"]
    assert health.overall(incomplete) == "FAIL"


def test_an_unknown_status_is_never_reported_as_pass():
    assert health.overall(payload(storage="UNKNOWN")) == "FAIL"


def test_summary_matches_the_operator_output_contract():
    lines = health.summary_lines(payload())
    assert lines == [
        "DanceMate Server",
        "Runtime ........ PASS",
        "Database ....... PASS",
        "Scheduler ...... PASS",
        "Information .... PASS",
        "Storage ........ PASS",
        "Backup ......... PASS",
    ]


def test_summary_shows_the_real_component_state():
    lines = health.summary_lines(payload(database="FAIL", backup="WARN"))
    assert "Database ....... FAIL" in lines
    assert "Backup ......... WARN" in lines
    assert "Runtime ........ PASS" in lines


def test_runtime_component_fails_on_a_misconfigured_environment(env, monkeypatch):
    from runtime.config import load_settings

    monkeypatch.setenv("POSTGRES_PASSWORD", "CHANGE_ME")
    component = health.runtime_component(load_settings())
    assert component["status"] == "FAIL"
    assert component["config_problems"]


def test_runtime_component_passes_on_a_valid_environment(settings):
    component = health.runtime_component(settings)
    assert component["status"] == "PASS"
    assert component["uptime_seconds"] >= 0


def test_collect_never_raises_without_a_database(settings):
    result = health.collect(settings)
    assert set(result) == set(health.COMPONENTS)
    assert result["database"]["status"] == "FAIL"


@pytest.mark.parametrize(
    "used,expected", [(10.0, "OK"), (74.9, "OK"), (75.0, "WARN"), (94.9, "WARN"), (95.0, "CRITICAL")]
)
def test_storage_bands(used, expected):
    from runtime.resources import classify_usage

    assert classify_usage(used, 75, 95) == expected
