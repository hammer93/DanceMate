"""Tango Coverage Metrics (v0.82, spec Section 27-30).

A single-genre expansion release is judged on whether ITS coverage grew -
the pre-existing dashboard panels (_today_panel/_coverage_panel) blend every
genre together and cannot show that. quality.upcoming_buckets(genre_code=)
and quality.genre_region_windows() are the SQL side; admin._genre_coverage_panel
is the rendering, reused generically (genre_code + label) rather than a
Tango-only special case, so a future genre expansion is the same code path.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime import admin, events_api, normalization, quality


def _live(pg, unique, suffix="1", **overrides):
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/cov78/{unique}-{suffix}",
        "event_name": f"커버리지 테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": (events_api.today() + timedelta(days=3)).isoformat(),
        "start_time": "20:00", "end_time": "23:30", "end_day_offset": 0,
        "venue": f"커버리지홀 {unique}", "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
        "time_evidence": "EXPLICIT",
    }
    candidate.update(overrides)
    return normalization.normalize_candidate(pg, candidate)


CREDENTIALS = ("dancemate", "test-admin-password")


# --- quality.upcoming_buckets(genre_code=) -----------------------------------

def test_genre_code_none_keeps_the_original_all_genre_count(pg, unique):
    """Backward compatibility: every existing caller passes no genre_code."""
    _live(pg, unique, "1")
    all_genres = quality.upcoming_buckets(pg)
    assert all_genres["upcoming"] >= 1


def test_genre_code_narrows_to_one_genre(pg, unique):
    tango = _live(pg, unique, "1")
    swing = _live(pg, unique, "2", event_type="SWING_SOCIAL")
    only_tango = quality.upcoming_buckets(pg, genre_code="TANGO")
    ids_via_search = {
        e["id"] for e in events_api.search(pg, genre="TANGO", limit=events_api.MAX_LIMIT)["events"]
    }
    assert tango["event_id"] in ids_via_search
    assert only_tango["upcoming"] >= 1
    # A genre with no events at all narrows to zero, never falls back to "all".
    empty = quality.upcoming_buckets(pg, genre_code="NOT-A-REAL-GENRE")
    assert empty == {"today": 0, "tomorrow": 0, "this_week": 0, "upcoming": 0, "past": 0}


# --- quality.genre_region_windows --------------------------------------------

def test_genre_region_windows_places_todays_event_in_the_today_column(pg, unique):
    """KR-SEOUL's `name` is asserted by lookup, not hardcoded as "Seoul" - an
    operator can rename a region's display name from the console (Master
    Data), and this real staging DB has one renamed to "서울"; the code under
    test is genuinely region-name-agnostic, so the test should be too."""
    from runtime import master_data

    seoul = next(r for r in master_data.list_regions(pg) if r["code"] == "KR-SEOUL")
    today_event = _live(pg, unique, "1", event_date=events_api.today().isoformat())
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET region_id = %s WHERE event_id = %s",
                    (seoul["region_id"], today_event["event_id"]))

    matrix = quality.genre_region_windows(pg, "TANGO")
    assert matrix["genre"] == "TANGO"
    assert matrix["grid"][seoul["name"]]["today"] >= 1


def test_genre_region_windows_never_leaks_another_genre_in(pg, unique):
    _live(pg, unique, "1", event_type="SWING_SOCIAL",
          event_date=events_api.today().isoformat())
    matrix = quality.genre_region_windows(pg, "TANGO")
    total = sum(cell["today"] for cell in matrix["grid"].values())
    # The swing row must not have inflated TANGO's today count via a bad join.
    assert total == quality.upcoming_buckets(pg, genre_code="TANGO")["today"]


# --- dashboard panel: real Postgres, through the app -------------------------

@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", CREDENTIALS[0])
    monkeypatch.setenv("ADMIN_PASSWORD", CREDENTIALS[1])
    monkeypatch.setattr(app_module, "_settings", None)
    from fastapi.testclient import TestClient

    return TestClient(app_module.app, raise_server_exceptions=False)


def test_dashboard_shows_tango_coverage_when_tango_sources_exist(client, pg, unique):
    """Created through the app's own admin API, not the `pg` fixture: `pg`'s
    writes live in a connection that is rolled back at teardown and never
    committed, so `client`'s requests (each a fresh, real connection) would
    never see a row inserted only via `pg` - proven directly during v0.82's
    board test run (a diagnostic insert-then-cross-connection-read came back
    VISIBLE_COUNT=0)."""
    from runtime import master_data

    tango = next(g for g in master_data.list_genres(pg) if g["code"] == "TANGO")
    response = client.post(
        "/api/admin/sources", auth=CREDENTIALS,
        json={
            "source_key": f"SRC-COV-{unique}", "name": f"coverage test {unique}",
            "platform": "WEB", "source_role": "COMMUNITY",
            "url": f"https://example.test/coverage-board-{unique}",
            "genre_id": tango["genre_id"], "enabled": True,
        },
    )
    assert response.status_code == 200, response.text

    response = client.get("/admin", auth=CREDENTIALS)
    assert response.status_code == 200
    assert "Tango Coverage" in response.text
    assert "Tango Sources" in response.text


def test_genre_coverage_panel_is_empty_with_no_sources_for_that_genre(client, pg, unique):
    """A genre nothing is registered under must render nothing, not an
    empty-but-present panel shell. `client` only exists here to trigger
    runtime.app's import-time admin.bind(), so admin._settings() resolves;
    the assertion itself calls the panel function directly against a genre
    code that cannot exist, independent of whatever else is in the shared,
    non-transactional DB."""
    html = admin._genre_coverage_panel(admin._settings(), f"NOT-A-REAL-GENRE-{unique}", "Nope")
    assert html == ""
