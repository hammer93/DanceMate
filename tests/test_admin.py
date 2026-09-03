"""Admin console: authentication, pages and the JSON API.

The pages are rendered against whatever the database holds, so the page tests
skip without PostgreSQL. The authentication tests do not - a lock that only
works when a database is up would be no lock at all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from runtime import admin_auth

ADMIN_PAGES = (
    "/admin",
    "/admin/sources",
    "/admin/venues",
    "/admin/organizers",
    "/admin/candidates",
    "/admin/master",
)

ADMIN_APIS = (
    "/api/admin/genres",
    "/api/admin/regions",
    "/api/admin/venues",
    "/api/admin/organizers",
    "/api/admin/sources",
    "/api/admin/candidates",
    "/api/admin/intake",
)

CREDENTIALS = ("dancemate", "test-admin-password")


@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", CREDENTIALS[0])
    monkeypatch.setenv("ADMIN_PASSWORD", CREDENTIALS[1])
    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


@pytest.fixture
def locked_client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


# --- authentication ---------------------------------------------------------

def test_credential_check_is_false_when_unconfigured(monkeypatch):
    """A missing password must lock the console, not open it."""
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    assert admin_auth.configured() is False
    assert admin_auth.check("dancemate", "") is False
    assert admin_auth.check("dancemate", "anything") is False


def test_credential_check_matches_only_the_configured_pair(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "dancemate")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    assert admin_auth.check("dancemate", "s3cret") is True
    assert admin_auth.check("dancemate", "wrong") is False
    assert admin_auth.check("someone", "s3cret") is False
    assert admin_auth.check(None, None) is False


@pytest.mark.parametrize("path", ADMIN_PAGES + ADMIN_APIS)
def test_every_admin_route_refuses_anonymous_access(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_wrong_credentials_are_refused(client, path):
    assert client.get(path, auth=("dancemate", "nope")).status_code == 401


def test_a_locked_console_refuses_even_correct_looking_credentials(locked_client):
    response = locked_client.get("/admin", auth=CREDENTIALS)
    assert response.status_code == 503
    assert "ADMIN_PASSWORD" in response.json()["detail"]


def test_the_health_endpoint_stays_open(client):
    """Container healthchecks must not need admin credentials."""
    assert client.get("/health").status_code == 200


def test_the_challenge_names_the_realm(client):
    response = client.get("/admin")
    assert "Basic" in response.headers.get("www-authenticate", "")


# --- pages ------------------------------------------------------------------

pytestmark_db = pytest.mark.postgres


def _page(client, path: str) -> str:
    response = client.get(path, auth=CREDENTIALS)
    assert response.status_code == 200, f"{path} -> {response.status_code}"
    return response.text


def test_dashboard_renders(client, pg):
    body = _page(client, "/admin")
    assert "DanceMate Admin" in body
    for label in ("Runtime", "Database", "Scheduler", "Information Engine",
                  "Storage", "Backup"):
        assert label in body
    assert "Sources" in body and "Event candidates" in body


def test_sources_page_lists_and_offers_the_actions(client, pg):
    body = _page(client, "/admin/sources")
    assert "Add Source" in body
    for platform in ("DAUM_CAFE", "NAVER_CAFE", "NAVER_BLOG"):
        assert platform in body
    assert "Test" in body
    assert "New sources start disabled" in body


def test_venues_page_explains_aliases(client, pg):
    body = _page(client, "/admin/venues")
    assert "Add Venue" in body
    assert "Aliases" in body


def test_organizers_page_renders(client, pg):
    assert "Add Organizer" in _page(client, "/admin/organizers")


def test_master_page_shows_the_seeded_reference_data(client, pg):
    body = _page(client, "/admin/master")
    for code in ("TANGO", "SALSA", "SWING"):
        assert code in body
    assert "Seoul" in body


def test_candidates_page_is_read_only_in_v075(client, pg):
    body = _page(client, "/admin/candidates")
    assert "Event Candidates" in body
    assert "cannot grant VERIFIED" in body
    assert "v0.76" in body


def test_every_page_is_reachable(client, pg):
    for path in ADMIN_PAGES:
        _page(client, path)


# --- JSON API ---------------------------------------------------------------

def test_genres_api_returns_the_seeded_genres(client, pg):
    response = client.get("/api/admin/genres", auth=CREDENTIALS)
    assert response.status_code == 200
    codes = {g["code"] for g in response.json()}
    assert {"TANGO", "SALSA", "SWING"} <= codes


def test_sources_api_reports_collector_capability(client, pg):
    response = client.get("/api/admin/sources", auth=CREDENTIALS)
    assert response.status_code == 200
    for source in response.json():
        assert "collector" in source
        assert set(source["collector"]) >= {"live", "snapshot", "detail"}


def test_creating_an_invalid_source_answers_422_not_500(client, pg):
    response = client.post(
        "/api/admin/sources",
        auth=CREDENTIALS,
        json={"source_key": "SRC-X", "name": "Bad", "platform": "INSTAGRAM",
              "source_role": "COMMUNITY"},
    )
    assert response.status_code == 422
    assert "platform" in response.json()["detail"]


def test_candidates_api_returns_counts_and_rows(client, pg):
    response = client.get("/api/admin/candidates", auth=CREDENTIALS)
    assert response.status_code == 200
    body = response.json()
    assert "counts" in body and "candidates" in body


def test_intake_api_returns_summary_runs_and_items(client, pg):
    response = client.get("/api/admin/intake", auth=CREDENTIALS)
    assert response.status_code == 200
    assert set(response.json()) == {"summary", "runs", "items"}
