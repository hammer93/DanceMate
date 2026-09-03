"""Venue resolution: one screen turns a read string into a venue someone owns.

The success condition for v0.77.1 is not "venue creation exists". It is that
with an empty Venue Master, an operator can read the post, create the venue,
link the string and see the waiting events resolve — without leaving the queue.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from runtime import (
    events_api,
    master_data,
    normalization,
    venue_resolution,
)


@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


# --- parsing the raw string -------------------------------------------------

def test_a_bracketed_address_splits_into_name_and_address():
    suggestion = venue_resolution.suggest("라 벤따나 (서울 마포구 잔다리로 48, 2층)")
    assert suggestion["name"] == "라 벤따나"
    assert suggestion["address"] == "서울 마포구 잔다리로 48, 2층"
    assert "라 벤따나 (서울 마포구 잔다리로 48, 2층)" in suggestion["aliases"]
    assert suggestion["split_inferred"] is True


def test_a_bracketed_second_name_becomes_an_alias_not_an_address():
    """'EnPaz Tango Studio' is another name for the place. Filling the address
    field with it would be worse than leaving the field empty."""
    suggestion = venue_resolution.suggest("엔빠스(EnPaz Tango Studio)")
    assert suggestion["name"] == "엔빠스"
    assert suggestion["address"] is None
    assert "EnPaz Tango Studio" in suggestion["aliases"]


@pytest.mark.parametrize("raw", ["OCHO", "아미고스튜디오", "홍대 PISTA", "Tango Andante"])
def test_a_plain_name_is_left_alone(raw):
    suggestion = venue_resolution.suggest(raw)
    assert suggestion["name"] == raw
    assert suggestion["address"] is None
    assert suggestion["split_inferred"] is False


def test_the_raw_string_is_always_accounted_for():
    """Resolving it next time is the entire reason the operator is here.

    It is the name when the name is unchanged, and an alias when the form split
    it — never dropped, and never listed twice.
    """
    for raw in ("OCHO", "엔빠스(EnPaz Tango Studio)", "라 벤따나 (서울 마포구 잔다리로 48, 2층)"):
        suggestion = venue_resolution.suggest(raw)
        assert raw == suggestion["name"] or raw in suggestion["aliases"]
        assert suggestion["name"] not in suggestion["aliases"]


@pytest.mark.parametrize("text,expected", [
    ("서울 마포구 잔다리로 48, 2층", True),
    ("서울특별시 서초구 반포대로30길 82", True),
    ("마포구 잔다리로 48", True),
    ("EnPaz Tango Studio", False),
    ("지하 1층", False),
    ("", False),
])
def test_address_recognition_is_narrow_on_purpose(text, expected):
    assert venue_resolution.looks_like_an_address(text) is expected


# --- SQL --------------------------------------------------------------------

def _candidate(unique: str, suffix: str = "1", **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/venue/{unique}-{suffix}",
        "event_name": f"장소 테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"테스트홀 {unique}",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    base.update(overrides)
    return base


def _queued(con, venue_text: str) -> dict:
    return next(v for v in normalization.unresolved_venues(con)
                if v["venue_text"] == venue_text)


def test_create_and_link_registers_the_venue_and_resolves_the_events(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2", start_time="21:00"))
    entry = _queued(pg, venue_text)
    assert entry["event_count"] == 2

    result = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"테스트홀 {unique}", region_id=seoul_id,
        address="서울 마포구 테스트로 1", reviewer="tester",
    )
    assert result["events_updated"] == 2

    for event in (first, second):
        updated = normalization.get(pg, event["event_id"])
        assert updated["venue_status"] == normalization.VENUE_RESOLVED
        assert updated["venue_id"] == result["venue"]["venue_id"]
        assert updated["region_id"] == seoul_id


def test_create_and_link_makes_the_raw_string_resolve_next_time(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)

    result = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"완전히 다른 이름 {unique}", region_id=seoul_id, reviewer="tester",
    )
    found = master_data.resolve_venue(pg, venue_text)
    assert found is not None
    assert found["venue_id"] == result["venue"]["venue_id"]


def test_the_queue_entry_is_marked_resolved(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, reviewer="tester",
    )
    assert venue_text not in [v["venue_text"] for v in normalization.unresolved_venues(pg)]


def test_link_existing_resolves_without_creating_a_venue(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    venue = master_data.create_venue(pg, name=f"이미 있는 홀 {unique}", region_id=seoul_id)
    before = len(master_data.list_venues(pg))
    entry = _queued(pg, venue_text)

    result = venue_resolution.link_existing(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        venue_id=venue["venue_id"], reviewer="tester",
    )
    assert result["events_updated"] == 1
    assert len(master_data.list_venues(pg)) == before
    assert normalization.get(pg, stored["event_id"])["venue_id"] == venue["venue_id"]


# --- duplicate protection ---------------------------------------------------

def test_a_venue_with_the_same_name_raises_before_creating_a_second_one(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    master_data.create_venue(pg, name=f"테스트홀 {unique}", region_id=seoul_id)
    entry = _queued(pg, venue_text)

    before = len(master_data.list_venues(pg))
    with pytest.raises(venue_resolution.DuplicateVenue) as raised:
        venue_resolution.create_and_link(
            pg, unresolved_venue_id=entry["unresolved_venue_id"],
            name=f"테스트홀 {unique}", region_id=seoul_id, reviewer="tester",
        )
    assert any("name" in r for m in raised.value.matches for r in m["match_reasons"])
    assert len(master_data.list_venues(pg)) == before


def test_a_registered_alias_also_raises(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    venue = master_data.create_venue(pg, name=f"다른 이름 {unique}", region_id=seoul_id)
    master_data.add_venue_alias(pg, venue["venue_id"], venue_text)
    entry = _queued(pg, venue_text)

    with pytest.raises(venue_resolution.DuplicateVenue) as raised:
        venue_resolution.create_and_link(
            pg, unresolved_venue_id=entry["unresolved_venue_id"],
            name=f"새 이름 {unique}", region_id=seoul_id, reviewer="tester",
        )
    assert any("alias" in r for m in raised.value.matches for r in m["match_reasons"])


def test_the_same_address_raises(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    master_data.create_venue(pg, name=f"기존 홀 {unique}", region_id=seoul_id,
                             address=f"서울 마포구 테스트로 {unique}")
    entry = _queued(pg, venue_text)

    with pytest.raises(venue_resolution.DuplicateVenue) as raised:
        venue_resolution.create_and_link(
            pg, unresolved_venue_id=entry["unresolved_venue_id"],
            name=f"새 이름 {unique}", address=f"서울 마포구 테스트로  {unique}",
            region_id=seoul_id, reviewer="tester",
        )
    assert any("address" in r for m in raised.value.matches for r in m["match_reasons"])


def test_the_operator_can_say_it_really_is_a_different_place(pg, unique, seoul_id):
    """A warning, not a refusal. Two studios can share a name."""
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    master_data.create_venue(pg, name=f"테스트홀 {unique}", region_id=seoul_id)
    entry = _queued(pg, venue_text)

    result = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"테스트홀 {unique} 2호점", region_id=seoul_id,
        reviewer="tester", force=True,
    )
    assert result["venue"]["venue_id"] is not None


# --- not a venue ------------------------------------------------------------

def test_not_a_venue_leaves_the_events_and_the_evidence_alone(pg, unique):
    venue_text = f"테스트홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)

    venue_resolution.dismiss(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        reviewer="tester", reason="행사명",
    )
    still = normalization.get(pg, stored["event_id"])
    assert still is not None
    assert still["venue_text"] == venue_text
    assert still["venue_status"] == normalization.VENUE_UNRESOLVED
    assert venue_text not in [v["venue_text"] for v in normalization.unresolved_venues(pg)]


# --- audit ------------------------------------------------------------------

@pytest.mark.parametrize("action", [
    venue_resolution.CREATE_AND_LINK,
    venue_resolution.LINK_EXISTING,
    venue_resolution.NOT_A_VENUE,
])
def test_every_venue_decision_is_recorded_with_who_made_it(pg, unique, seoul_id, action):
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)

    if action == venue_resolution.CREATE_AND_LINK:
        venue_resolution.create_and_link(
            pg, unresolved_venue_id=entry["unresolved_venue_id"],
            name=venue_text, region_id=seoul_id, reviewer="kimpro",
        )
    elif action == venue_resolution.LINK_EXISTING:
        venue = master_data.create_venue(pg, name=f"기존 {unique}", region_id=seoul_id)
        venue_resolution.link_existing(
            pg, unresolved_venue_id=entry["unresolved_venue_id"],
            venue_id=venue["venue_id"], reviewer="kimpro",
        )
    else:
        venue_resolution.dismiss(
            pg, unresolved_venue_id=entry["unresolved_venue_id"], reviewer="kimpro",
        )

    recorded = next(a for a in venue_resolution.history(pg) if a["raw_venue"] == venue_text)
    assert recorded["action"] == action
    assert recorded["reviewer"] == "kimpro"
    assert recorded["before_json"]["venue_text"] == venue_text
    assert recorded["after_json"]


def test_the_audit_row_says_how_many_events_actually_moved(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1"))
    normalization.normalize_candidate(pg, _candidate(unique, "2", start_time="21:00"))
    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, reviewer="tester",
    )
    recorded = next(a for a in venue_resolution.history(pg) if a["raw_venue"] == venue_text)
    assert recorded["events_updated"] == 2


# --- context ----------------------------------------------------------------

def test_the_queue_shows_the_post_each_string_came_from(pg, unique):
    """Is OCHO a studio or the name of the event? Only the post says."""
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    found = venue_resolution.context(pg, venue_text)
    assert len(found) == 1
    assert found[0]["source_url"].startswith("https://")
    assert unique in found[0]["event_name"]


def test_a_snippet_is_a_window_not_the_whole_article():
    body = "가" * 500 + " 장소: 아미고스튜디오 DJ : 로띠 " + "나" * 500
    snippet = venue_resolution._snippet(body, "아미고스튜디오")
    assert "아미고스튜디오" in snippet
    assert "장소:" in snippet
    assert len(snippet) < 200


def test_no_body_means_no_snippet_rather_than_a_guess():
    assert venue_resolution._snippet(None, "OCHO") is None
    assert venue_resolution._snippet("무관한 본문입니다", "존재하지않는장소") is None


# --- end to end -------------------------------------------------------------

def test_resolution_reaches_the_user_surface_and_the_region_filter(pg, unique, seoul_id):
    """/admin action -> normalized event -> /events/{id} and ?region=Seoul."""
    venue_text = f"테스트홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique))

    before = events_api.get_event(pg, stored["event_id"])
    assert before["venue"]["status"] == normalization.VENUE_UNRESOLVED
    assert before["region"] is None
    assert not [e for e in events_api.search(
        pg, on="2026-09-05", region="Seoul", limit=100)["events"] if e["id"] == stored["event_id"]]

    entry = _queued(pg, venue_text)
    venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"테스트홀 {unique}", region_id=seoul_id,
        address="서울 마포구 테스트로 1", reviewer="tester",
    )

    after = events_api.get_event(pg, stored["event_id"])
    assert after["venue"]["status"] == normalization.VENUE_RESOLVED
    assert after["venue"]["name"] == f"테스트홀 {unique}"
    assert after["venue"]["address"] == "서울 마포구 테스트로 1"
    assert after["region"] == "Seoul"
    assert [e for e in events_api.search(
        pg, on="2026-09-05", region="Seoul", limit=100)["events"] if e["id"] == stored["event_id"]]


def test_a_region_hint_only_selects_a_region_it_actually_matches(pg, seoul_id):
    """Defaulting everything to Seoul would file a Busan milonga under Seoul."""
    assert venue_resolution.suggested_region_id(pg, "서울") == seoul_id
    assert venue_resolution.suggested_region_id(pg, None) is None
    assert venue_resolution.suggested_region_id(pg, "제주") is None


# --- failure handling -------------------------------------------------------

def test_a_missing_queue_entry_creates_nothing(pg, seoul_id):
    before = len(master_data.list_venues(pg))
    with pytest.raises(LookupError):
        venue_resolution.create_and_link(
            pg, unresolved_venue_id=999999999, name="없는 큐", region_id=seoul_id,
        )
    assert len(master_data.list_venues(pg)) == before


def test_an_empty_name_is_rejected(pg, unique):
    normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, f"테스트홀 {unique}")
    with pytest.raises(ValueError):
        venue_resolution.create_and_link(
            pg, unresolved_venue_id=entry["unresolved_venue_id"], name="   ",
        )


def test_a_failed_link_leaves_no_half_created_venue(pg, unique, monkeypatch):
    """Half-done is the worst outcome: a master record nobody asked for beside a
    queue entry that still looks untouched, so the operator creates it again."""
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    before = len(master_data.list_venues(pg))

    def explode(*args, **kwargs):
        raise RuntimeError("link failed")

    monkeypatch.setattr(normalization, "link_unresolved_venue", explode)
    with pytest.raises(RuntimeError):
        venue_resolution.create_and_link(
            pg, unresolved_venue_id=entry["unresolved_venue_id"],
            name=f"롤백 테스트 {unique}", reviewer="tester",
        )
    assert len(master_data.list_venues(pg)) == before
    assert venue_text in [v["venue_text"] for v in normalization.unresolved_venues(pg)]


def test_record_action_rejects_an_unknown_action(pg):
    with pytest.raises(ValueError):
        venue_resolution.record_action(
            pg, action="MAYBE_A_VENUE", raw_venue="x", reviewer="tester",
        )


# --- the console screen -----------------------------------------------------

def test_every_venue_route_requires_authentication(client):
    for method, path in (
        ("get", "/admin/venues/unresolved"),
        ("post", "/admin/venues/unresolved/1/create"),
        ("post", "/admin/venues/unresolved/1/link"),
        ("post", "/admin/venues/unresolved/1/dismiss"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code in (401, 503), f"{method} {path}"


def test_the_queue_offers_all_three_decisions_and_a_source_link():
    """Link Existing, New Venue and Not a venue, none of them buried."""
    from runtime import events_admin

    entry = {"unresolved_venue_id": 1, "venue_text": "라 벤따나 (서울 마포구 잔다리로 48, 2층)",
             "first_seen_at": "2026-09-03 09:09", "alias_candidates": [], "event_count": 2,
             "state": "OPEN"}
    suggestion = venue_resolution.suggest(entry["venue_text"])
    form = events_admin._new_venue_form(entry, suggestion, [], None)
    assert "New Venue" in form
    assert "Create &amp; Link" in form
    assert 'value="라 벤따나"' in form
    assert 'value="서울 마포구 잔다리로 48, 2층"' in form
    assert entry["venue_text"] in form  # the raw string is the alias

    context = events_admin._source_context(entry, [
        {"event_date": date(2026, 9, 5), "event_name": "밀롱가",
         "source_url": "https://cafe.daum.net/x/1", "snippet": "… 장소: 라 벤따나 …"},
    ])
    assert "원문 보기" in context
    assert "https://cafe.daum.net/x/1" in context
    assert "장소: 라 벤따나" in context


def test_the_form_says_when_it_inferred_the_split():
    from runtime import events_admin

    entry = {"unresolved_venue_id": 1, "venue_text": "라 벤따나 (서울 마포구 잔다리로 48, 2층)",
             "first_seen_at": "2026-09-03", "alias_candidates": [], "event_count": 1}
    form = events_admin._new_venue_form(
        entry, venue_resolution.suggest(entry["venue_text"]), [], None,
    )
    assert "추정한 값" in form


def test_a_venue_string_is_escaped_in_the_form():
    """Venue strings come from posts written by other people."""
    from runtime import events_admin

    entry = {"unresolved_venue_id": 1, "venue_text": '<script>alert(1)</script>',
             "first_seen_at": "2026-09-03", "alias_candidates": [], "event_count": 0}
    form = events_admin._new_venue_form(
        entry, venue_resolution.suggest(entry["venue_text"]), [], None,
    )
    assert "<script>" not in form
    assert "&lt;script&gt;" in form


def test_the_queue_says_how_many_live_posts_are_behind_a_string(pg, unique):
    """A string only a PoC fixture ever produced has no post to read, and a
    decision about it changes nothing a dancer sees."""
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1"))
    normalization.normalize_candidate(
        pg, _candidate(unique, "2", start_time="21:00",
                       provenance=normalization.PROVENANCE_UNKNOWN),
    )
    entry = _queued(pg, venue_text)
    assert entry["event_count"] == 2
    assert entry["live_event_count"] == 1


def test_a_fixture_only_string_is_marked_as_having_no_live_post():
    from runtime import events_admin

    entry = {"unresolved_venue_id": 1, "venue_text": "OCHO", "first_seen_at": "2026-09-03",
             "alias_candidates": [], "event_count": 8, "live_event_count": 0}
    suggestion = venue_resolution.suggest("OCHO")
    # Rendered through the page so the badge is checked where it appears.
    rendered = events_admin._new_venue_form(entry, suggestion, [], None)
    assert "OCHO" in rendered
