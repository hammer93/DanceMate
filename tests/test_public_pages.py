"""The alpha user surface: what a dancer sees, and what it refuses to claim."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from runtime import duplicates, normalization, public


@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


# --- rendering --------------------------------------------------------------

def test_a_missing_time_says_so_rather_than_guessing():
    """'시간 미확인' is information. An invented time is not."""
    rendered = public._when_line({"date": "2026-09-05", "start_time": None,
                                  "end_time": None, "ends_next_day": False})
    assert "미확인" in rendered
    assert "9/5(토)" in rendered


def test_a_time_that_crosses_midnight_is_marked():
    rendered = public._when_line({"date": "2026-09-05", "start_time": "20:00",
                                  "end_time": "00:30", "ends_next_day": True})
    assert "20:00" in rendered and "00:30" in rendered
    assert "+1" in rendered


def test_a_missing_fee_is_never_rendered_as_zero():
    """0원 would read as free admission, which nobody told us."""
    rendered = public._fee_line({"fee": None})
    assert "미확인" in rendered
    assert "0" not in rendered


def test_a_fee_is_rendered_with_a_thousands_separator():
    assert public._fee_line({"fee": 13000}) == "13,000원"


def test_an_unresolved_venue_is_shown_but_flagged():
    """We read this string off a post and have not confirmed the place. Hiding
    it would lose information; asserting it would overstate what we know."""
    rendered = public._venue_line(
        {"venue": {"name": "미등록 스튜디오", "status": "UNRESOLVED"}}
    )
    assert "미등록 스튜디오" in rendered
    assert "미확인" in rendered


def test_a_resolved_venue_carries_no_caveat():
    rendered = public._venue_line({"venue": {"name": "아미고스튜디오", "status": "RESOLVED"}})
    assert rendered == "아미고스튜디오"


def test_a_missing_venue_says_so():
    assert "미확인" in public._venue_line({"venue": {"name": None, "status": "ABSENT"}})


def test_event_names_are_escaped():
    """Event names come from posts written by other people."""
    rendered = public._event_item({
        "id": 1, "name": '<script>alert("x")</script>', "date": "2026-09-05",
        "start_time": "19:30", "end_time": "23:30", "ends_next_day": False,
        "venue": {"name": None, "status": "ABSENT"}, "fee": None,
    })
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_the_page_admits_it_is_an_alpha():
    footer = public._footer()
    assert "alpha" in footer.lower()
    assert "확인되지 않은" in footer


# --- routes -----------------------------------------------------------------

def test_the_user_surface_is_mounted_where_a_person_would_look():
    from runtime.app import app

    paths = {route.path for route in app.routes}
    assert {"/", "/events", "/events/{event_id}",
            "/api/events", "/api/events/{event_id}"} <= paths


def test_the_alpha_surface_never_shadows_the_operator_console():
    from runtime.app import app

    paths = [route.path for route in app.routes]
    assert paths.index("/api/events") < paths.index("/")


def test_an_unknown_when_is_a_bad_request_not_an_empty_page(client):
    response = client.get("/events?when=next_century")
    assert response.status_code == 400


def test_a_missing_event_is_a_404(client):
    response = client.get("/events/999999999")
    assert response.status_code in (404, 503)


# --- SQL --------------------------------------------------------------------

def _live(pg, unique, suffix, **overrides):
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/page/{unique}-{suffix}",
        "event_name": f"페이지 테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": date.today().isoformat(),
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"스튜디오 {unique}",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    candidate.update(overrides)
    return normalization.normalize_candidate(pg, candidate)


def test_the_json_api_answers_the_same_question_as_the_page(pg, unique):
    """Both read one search function, so they cannot drift apart."""
    from runtime import events_api

    _live(pg, unique, "1")
    result = events_api.search(pg, when="today", limit=100)
    assert any(unique in (e["name"] or "") for e in result["events"])


def test_a_snapshot_event_reaches_neither_surface(pg, unique):
    from runtime import events_api

    _live(pg, unique, "1", provenance=normalization.PROVENANCE_SNAPSHOT)
    result = events_api.search(pg, when="today", limit=100)
    assert not any(unique in (e["name"] or "") for e in result["events"])


def test_the_detail_page_links_back_to_the_original_posts(pg, unique):
    from runtime import events_api

    _live(pg, unique, "1")
    _live(pg, unique, "2")
    duplicates.scan(pg, on=date.today())
    found = [e for e in events_api.search(pg, when="today", limit=100)["events"]
             if unique in (e["name"] or "")]
    assert len(found) == 1
    event = events_api.get_event(pg, found[0]["id"])
    assert all(source["url"].startswith("https://") for source in event["sources"])
