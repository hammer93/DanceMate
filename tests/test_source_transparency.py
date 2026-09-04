"""Source Transparency (v0.82): what a source actually looks at, and whether
it is actually working - answerable from the Sources page without opening
the edit form, and without any new tracking column (target/health/last
success/last error are all derived from signals the pipeline already
records).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime import admin, intake, source_ops, sources


CREDENTIALS = ("dancemate", "test-admin-password")


# --- _source_target: pure, no DB ---------------------------------------------

def test_web_source_shows_its_board_url():
    source = {"platform": "WEB", "url": "https://www.k-tango.net/cnf/festival02/",
              "queries": []}
    html = admin._source_target(source)
    assert "www.k-tango.net/cnf/festival02/" in html
    assert "Open Source" in html
    assert 'href="https://www.k-tango.net/cnf/festival02/"' in html


def test_web_source_with_no_url_is_flagged():
    source = {"platform": "WEB", "url": None, "queries": []}
    html = admin._source_target(source)
    assert "no target URL" in html
    assert "Open Source" not in html


def test_naver_source_shows_its_query():
    source = {"platform": "NAVER_BLOG", "url": None, "queries": ["서울 탱고 밀롱가"]}
    html = admin._source_target(source)
    assert "서울 탱고 밀롱가" in html
    assert "Query:" in html


def test_naver_source_with_no_query_is_flagged():
    source = {"platform": "NAVER_CAFE", "url": None, "queries": []}
    html = admin._source_target(source)
    assert "no query configured" in html


def test_daum_source_shows_query_and_url_filter():
    source = {"platform": "DAUM_CAFE", "url": "https://cafe.daum.net/latindance",
              "queries": ["밀롱가"]}
    html = admin._source_target(source)
    assert "밀롱가" in html
    assert "filter:" in html
    assert "Open Source" in html


def test_a_long_url_is_truncated_but_the_full_url_is_still_present_as_title():
    long_url = "https://example.test/" + "a" * 200
    source = {"platform": "WEB", "url": long_url, "queries": []}
    html = admin._source_target(source)
    assert f'title="{long_url}"' in html
    assert "…" in html


def test_queries_field_as_a_json_string_is_parsed():
    """Postgres JSONB usually comes back as a Python list already, but the
    function must not assume that if a caller hands it a raw JSON string."""
    source = {"platform": "NAVER_BLOG", "url": None, "queries": '["서울 탱고"]'}
    html = admin._source_target(source)
    assert "서울 탱고" in html


# --- _source_health: pure, no DB ---------------------------------------------

def _source(**overrides):
    base = {
        "enabled": True, "last_status": "PASS",
        "last_collected_at": datetime.now(timezone.utc),
        "collection_interval_minutes": 60,
    }
    base.update(overrides)
    return base


def test_a_disabled_source_is_disabled_regardless_of_everything_else():
    assert admin._source_health(_source(enabled=False, last_status="AUTH_FAILED"), {}) \
        == admin.HEALTH_DISABLED


def test_auth_failed_status_is_reported_as_auth_failed():
    assert admin._source_health(_source(last_status="AUTH_FAILED"), {}) == admin.HEALTH_AUTH_FAILED


def test_credentials_missing_status_is_also_auth_failed():
    assert admin._source_health(_source(last_status="CREDENTIALS_MISSING"), {}) \
        == admin.HEALTH_AUTH_FAILED


def test_bad_response_status_is_parser_error():
    assert admin._source_health(_source(last_status="BAD_RESPONSE"), {}) == admin.HEALTH_PARSER_ERROR


def test_never_collected_is_stale():
    assert admin._source_health(_source(last_collected_at=None), {}) == admin.HEALTH_STALE


def test_far_past_its_own_interval_is_stale():
    old = datetime.now(timezone.utc) - timedelta(hours=10)
    assert admin._source_health(
        _source(last_collected_at=old, collection_interval_minutes=60), {}
    ) == admin.HEALTH_STALE


def test_just_past_its_interval_is_not_yet_stale():
    """One missed tick is not staleness - only sustained silence is."""
    recent = datetime.now(timezone.utc) - timedelta(minutes=90)
    health = admin._source_health(
        _source(last_collected_at=recent, collection_interval_minutes=60),
        {"items": 5, "fetched": 5, "events": 1},
    )
    assert health != admin.HEALTH_STALE


def test_items_with_zero_readable_and_some_blocked_is_fetch_blocked():
    assert admin._source_health(_source(), {"items": 10, "fetched": 0, "blocked": 10}) \
        == admin.HEALTH_FETCH_BLOCKED


def test_readable_but_no_events_is_no_new_items():
    assert admin._source_health(_source(), {"items": 10, "fetched": 10, "events": 0}) \
        == admin.HEALTH_NO_NEW_ITEMS


def test_readable_with_events_is_active():
    assert admin._source_health(_source(), {"items": 10, "fetched": 10, "events": 3}) \
        == admin.HEALTH_ACTIVE


# --- last success / last error: real Postgres -------------------------------

def _make_source(pg, unique, suffix="1"):
    return sources.create_source(
        pg, source_key=f"SRC-HEALTH-{unique}-{suffix}", name=f"health test {unique}",
        platform="WEB", source_role="COMMUNITY", url="https://example.test/board",
        enabled=True,
    )


def _run(pg, source_id, *, status, error=None):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_collection_runs (source_id, mode, status, error) "
            "VALUES (%s, 'live', %s, %s)",
            (source_id, status, error),
        )


def test_last_success_per_source_reads_the_newest_pass(pg, unique):
    source = _make_source(pg, unique)
    _run(pg, source["source_id"], status="FAIL", error="boom")
    _run(pg, source["source_id"], status="PASS")
    result = intake.last_success_per_source(pg)
    assert source["source_id"] in result


def test_last_error_per_source_reads_the_newest_failure(pg, unique):
    source = _make_source(pg, unique)
    _run(pg, source["source_id"], status="PASS")
    _run(pg, source["source_id"], status="FAIL", error="rate limited")
    result = intake.last_error_per_source(pg)
    assert result[source["source_id"]]["error"] == "rate limited"


def test_a_source_with_no_failed_run_has_no_last_error(pg, unique):
    source = _make_source(pg, unique)
    _run(pg, source["source_id"], status="PASS")
    result = intake.last_error_per_source(pg)
    assert source["source_id"] not in result


# --- source detail page: real Postgres, through the app ---------------------

@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", CREDENTIALS[0])
    monkeypatch.setenv("ADMIN_PASSWORD", CREDENTIALS[1])
    monkeypatch.setattr(app_module, "_settings", None)
    from fastapi.testclient import TestClient

    return TestClient(app_module.app, raise_server_exceptions=False)


def _make_source_via_client(client, committed_sources, unique, suffix="1"):
    """Create a source through the app's own admin API, not the `pg` fixture.

    `pg` opens its own, never-committed connection (rolled back at teardown
    so a shared staging DB is never polluted) - a row inserted there is
    invisible to `client`'s requests, which each open a fresh, real
    connection. Proven directly: a diagnostic insert-then-read-from-a-second-
    connection check during v0.82's board test run showed VISIBLE_COUNT=0.
    Anything a test needs `client` itself to see has to be written through
    `client`, whose admin API commits for real - which is why the created
    id is registered with `committed_sources` for a real, explicit cleanup
    (see conftest.py: this board's PostgreSQL accepts any password, so the
    write lands in the real shared database no matter what).
    """
    response = client.post(
        "/api/admin/sources", auth=CREDENTIALS,
        json={
            "source_key": f"SRC-HEALTH-{unique}-{suffix}", "name": f"health test {unique}",
            "platform": "WEB", "source_role": "COMMUNITY",
            "url": f"https://example.test/board-{unique}-{suffix}", "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    committed_sources.append(created["source_id"])
    return created


def test_source_detail_page_shows_target_and_recent_items(client, pg, unique, committed_sources):
    source = _make_source_via_client(client, committed_sources, unique)
    response = client.get(f"/admin/sources/{source['source_id']}", auth=CREDENTIALS)
    assert response.status_code == 200
    assert f"example.test/board-{unique}-1" in response.text
    assert "Recent Items" in response.text
    assert "Raw config" in response.text


def test_source_detail_page_404s_for_an_unknown_id(client, pg):
    response = client.get("/admin/sources/999999999", auth=CREDENTIALS)
    assert response.status_code == 404


def test_sources_list_page_shows_the_target_column(client, pg, unique, committed_sources):
    _make_source_via_client(client, committed_sources, unique)
    response = client.get("/admin/sources", auth=CREDENTIALS)
    assert response.status_code == 200
    assert "Target" in response.text
    assert f"example.test/board-{unique}-1" in response.text


def test_no_secret_appears_on_the_sources_list_or_detail_page(
    client, pg, unique, committed_sources, monkeypatch,
):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "super-secret-key-value")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "another-secret-value")
    source = _make_source_via_client(client, committed_sources, unique)
    list_body = client.get("/admin/sources", auth=CREDENTIALS).text
    detail_body = client.get(f"/admin/sources/{source['source_id']}", auth=CREDENTIALS).text
    # Prove these are the real, populated pages - not a false pass off a 404
    # or an empty list, which would also happen to contain no secret.
    assert f"example.test/board-{unique}-1" in list_body
    assert f"example.test/board-{unique}-1" in detail_body
    for secret in ("super-secret-key-value", "another-secret-value"):
        assert secret not in list_body
        assert secret not in detail_body
