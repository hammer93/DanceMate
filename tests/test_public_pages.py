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


def test_the_representative_source_link_is_rendered():
    rendered = public._event_item({
        "id": 1, "name": "더 피스타 밀롱가", "date": "2026-09-05",
        "start_time": "19:30", "end_time": "23:30", "ends_next_day": False,
        "venue": {"name": None, "status": "ABSENT"}, "fee": None,
        "source_link": {"url": "https://cafe.daum.net/latindance/5HTC/22276",
                        "label": "Daum Cafe"},
    })
    assert "출처: Daum Cafe" in rendered
    assert 'href="https://cafe.daum.net/latindance/5HTC/22276"' in rendered
    assert 'target="_blank"' in rendered
    assert 'rel="noopener noreferrer"' in rendered
    assert "원문 보기" in rendered


def test_a_missing_source_url_shows_no_link_at_all():
    """No fake source link - the card's own /events/{id} link is expected,
    but nothing inside the .source block should be a link."""
    rendered = public._event_item({
        "id": 1, "name": "이름 없는 행사", "date": "2026-09-05",
        "start_time": None, "end_time": None, "ends_next_day": False,
        "venue": {"name": None, "status": "ABSENT"}, "fee": None,
        "source_link": {"url": None, "label": None},
    })
    assert "출처 미확인" in rendered
    source_block = rendered[rendered.index('<div class="source">'):]
    assert "<a href" not in source_block


def test_the_source_link_is_never_nested_inside_the_card_link():
    """Two <a> in one anchor is invalid HTML browsers resolve unpredictably."""
    rendered = public._event_item({
        "id": 1, "name": "이벤트", "date": "2026-09-05",
        "start_time": None, "end_time": None, "ends_next_day": False,
        "venue": {"name": None, "status": "ABSENT"}, "fee": None,
        "source_link": {"url": "https://example.com/post/1", "label": "Example"},
    })
    card_link_end = rendered.index("</a>")
    source_link_start = rendered.index('<a href="https://example.com')
    assert card_link_end < source_link_start


def test_internal_source_codes_never_reach_the_card():
    """SRC-W-001, NAVER_BLOG - a reader sees a brand, never the wiring."""
    rendered = public._event_item({
        "id": 1, "name": "이벤트", "date": "2026-09-05",
        "start_time": None, "end_time": None, "ends_next_day": False,
        "venue": {"name": None, "status": "ABSENT"}, "fee": None,
        "source_link": {"url": "https://cafe.daum.net/x/y/1", "label": "Daum Cafe"},
    })
    assert "SRC-" not in rendered
    assert "DAUM_CAFE" not in rendered
    assert "NAVER_BLOG" not in rendered


# --- events_api.source_label / valid_public_url ------------------------------

def test_a_search_api_platform_gets_its_brand_name():
    from runtime import events_api

    assert events_api.source_label("DAUM_CAFE", "외부홍보게시판(파티)") == "Daum Cafe"
    assert events_api.source_label("NAVER_BLOG", "소셜댄스 블로그 검색") == "Naver Blog"


def test_a_web_source_uses_its_own_registered_name():
    """WEB has no brand of its own here - K-TANGO is the source's own name."""
    from runtime import events_api

    assert events_api.source_label("WEB", "K-TANGO") == "K-TANGO"


def test_an_unregistered_source_yields_no_label_rather_than_a_guess():
    from runtime import events_api

    assert events_api.source_label(None, None) is None
    assert events_api.source_label("WEB", None) is None


@pytest.mark.parametrize("url", [
    "https://cafe.daum.net/x/y/1",
    "http://www.k-tango.net/cnf/festival02/read.jsp?no=10",
])
def test_valid_http_urls_pass_through(url):
    from runtime import events_api

    assert events_api.valid_public_url(url) == url


@pytest.mark.parametrize("url", [
    None, "", "javascript:alert(1)", "not a url", "ftp://example.com/file",
    "mailto:a@b.com", "//example.com/no-scheme",
])
def test_malformed_or_non_web_urls_are_blocked(url):
    from runtime import events_api

    assert events_api.valid_public_url(url) is None


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


def test_the_representative_source_is_the_events_own_registered_source(pg, unique):
    """A WEB source's own name (K-TANGO), not its platform code, and the same
    link on the list result as on the detail page for the same event."""
    from runtime import events_api, intake, sources

    source = sources.create_source(
        pg, source_key=f"SRC-W-{unique}", name=f"K-TANGO {unique}",
        platform="WEB", source_role="ORGANIZER",
        url=f"http://www.k-tango.net/test-{unique}/", queries=[],
        config={"board_urls": [f"http://www.k-tango.net/test-{unique}/index.jsp"]},
    )
    url = f"http://www.k-tango.net/cnf/festival02/read.jsp?no={unique}"
    intake.store_item(
        pg, source["source_id"],
        intake.RawItem(external_id=url, url=url, title="2026 K-TANGO SF"),
    )
    with pg.cursor() as cur:
        cur.execute(
            "SELECT source_item_id FROM source_items WHERE url = %s", (url,)
        )
        source_item_id = cur.fetchone()[0]

    _live(pg, unique, "1", source_url=url, source_item_id=source_item_id)

    found = [e for e in events_api.search(pg, when="today", limit=100)["events"]
             if unique in (e["name"] or "")]
    assert len(found) == 1
    listed = found[0]

    assert listed["source_link"]["url"] == url
    assert listed["source_link"]["label"] == f"K-TANGO {unique}"

    detail = events_api.get_event(pg, listed["id"])
    assert detail["source_link"] == listed["source_link"]
    # Same event context: the detail page's own canonical entry in `sources`
    # is this exact post, not some other event's.
    canonical = [s for s in detail["sources"] if s["is_canonical"]]
    assert len(canonical) == 1
    assert canonical[0]["url"] == url


def test_a_daum_source_shows_its_platform_brand_not_its_operational_name(pg, unique):
    from runtime import events_api, intake, sources

    source = sources.create_source(
        pg, source_key=f"SRC-D-{unique}", name=f"외부홍보게시판(파티) {unique}",
        platform="DAUM_CAFE", source_role="PROMOTION_BOARD",
        url=f"https://cafe.daum.net/{unique}", queries=["밀롱가"],
    )
    url = f"https://cafe.daum.net/latindance/x/{unique}"
    intake.store_item(
        pg, source["source_id"],
        intake.RawItem(external_id=url, url=url, title="밀롱가 공지"),
    )
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id FROM source_items WHERE url = %s", (url,))
        source_item_id = cur.fetchone()[0]

    _live(pg, unique, "1", source_url=url, source_item_id=source_item_id)

    found = [e for e in events_api.search(pg, when="today", limit=100)["events"]
             if unique in (e["name"] or "")]
    assert found[0]["source_link"]["label"] == "Daum Cafe"
    assert "외부홍보게시판" not in found[0]["source_link"]["label"]


def test_a_time_the_post_did_not_qualify_is_shown_but_flagged():
    """'5시30' is very likely half past five in the evening. The post does not
    say so, the engine refused to guess, and neither does the page."""
    rendered = public._when_line({"date": "2026-09-12", "start_time": "05:30",
                                  "end_time": "09:30", "ends_next_day": False,
                                  "time_confirmed": False})
    assert "05:30" in rendered
    assert "시간 미확인" in rendered


def test_a_time_the_post_marked_carries_no_caveat():
    rendered = public._when_line({"date": "2026-09-05", "start_time": "19:30",
                                  "end_time": "23:30", "ends_next_day": False,
                                  "time_confirmed": True})
    assert "미확인" not in rendered
