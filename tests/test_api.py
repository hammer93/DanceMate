"""Runtime HTTP API: /health, /status, /version (spec items 1, 2, 13)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    # Force the module-level settings cache to pick up the test environment.
    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


def test_health_is_cheap_and_reports_the_runtime_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.77"}


def test_version_separates_product_runtime_from_information_engine(client):
    body = client.get("/version").json()
    assert body["product_runtime"] == "0.77"
    assert body["information_engine"] == "0.74"
    assert body["environment"] == "test"


def test_status_reports_all_six_components(client):
    from runtime.health import COMPONENTS

    body = client.get("/status").json()
    for component in COMPONENTS:
        assert component in body, f"/status is missing {component}"
        assert body[component]["status"] in {"PASS", "WARN", "FAIL"}


def test_status_returns_503_when_a_component_fails(client):
    # No PostgreSQL is reachable from the test process, so database FAILs and
    # the endpoint must refuse to answer 200.
    response = client.get("/status")
    assert response.json()["database"]["status"] == "FAIL"
    assert response.status_code == 503
    assert response.json()["status"] == "FAIL"


def test_status_never_leaks_the_database_password(client):
    body = client.get("/status").text
    assert "test-password" not in body


def test_status_summary_matches_the_operator_report_format(client):
    text = client.get("/status/summary").text
    lines = text.strip().splitlines()
    assert lines[0] == "DanceMate Server"
    labels = ["Runtime", "Database", "Scheduler", "Information", "Storage", "Backup"]
    assert len(lines) == len(labels) + 1
    for label, line in zip(labels, lines[1:]):
        assert line.startswith(f"{label} ")
        assert "." in line
        assert line.split()[-1] in {"PASS", "WARN", "FAIL"}
        # every report line is padded to the same status column
        assert line.index(line.split()[-1]) == 17


def test_resources_endpoint_exposes_cpu_memory_disk(client):
    body = client.get("/resources").json()
    assert set(body) == {"cpu", "memory", "disk"}
    assert set(body["disk"]) == {"data", "engine", "backup"}
