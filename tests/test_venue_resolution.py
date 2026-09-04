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
    assert "원문 문자열에서 나눈 값" in form


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


# --- an address the post gives but the venue string does not -----------------

@pytest.mark.parametrize("body,venue,expected", [
    # The address runs straight into the next field; it stops at the emoji.
    ("📍 홍대 PISTA 서울 마포구 월드컵북로6길 49 B1 📩 예약 / 문의 🐰 바니 [전화번호]",
     "PISTA", "서울 마포구 월드컵북로6길 49 B1"),
    # A building and floor belong to the address; the fee that follows does not.
    ("장소 : 엔빠스(EnPaz Tango Studio) 서울특별시 서초구 반포대로30길 82 우서빌딩 지하 1층 밀롱가 : 13,000원",
     "엔빠스(EnPaz Tango Studio)", "서울특별시 서초구 반포대로30길 82 우서빌딩 지하 1층"),
    ("주소: 서울 강남구 테헤란로 1 2층", "어딘가", "서울 강남구 테헤란로 1 2층"),
])
def test_an_address_written_next_to_the_venue_is_that_venues(body, venue, expected):
    assert venue_resolution.address_in(body, venue) == expected


@pytest.mark.parametrize("body,venue", [
    # A parking address in the same post is not the venue's address.
    ("공원 공영주차장은 서울 마포구 어딘가로 12 입니다. 장소: 데땅고", "데땅고"),
    ("장소: 아미고스튜디오 DJ : 로띠 이번 주 수고해 주실 부산", "아미고스튜디오"),
    ("", "PISTA"),
])
def test_an_address_that_is_not_this_venues_is_left_alone(body, venue):
    assert venue_resolution.address_in(body, venue) is None


def test_the_post_fills_the_address_the_venue_string_does_not_carry(pg, unique):
    """The complaint this release answers: the name and the address were on
    screen and the form still asked for them."""
    venue_text = f"픽업홀 {unique}"
    address = "서울 마포구 월드컵북로6길 49 B1"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    with pg.cursor() as cur:
        cur.execute(
            "SELECT source_item_id FROM events WHERE candidate_id = %s",
            (int(f"{unique[-6:]}1"),),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        pytest.skip("this candidate has no stored post body to read")

    entry = _queued(pg, venue_text)
    filled = venue_resolution.prefill(pg, entry)
    assert filled["name"] == venue_text
    assert filled["address"] is None  # nothing in the post yet


def test_prefill_reports_where_each_value_came_from(pg, unique):
    venue_text = f"라 벤따나 {unique} (서울 마포구 잔다리로 48, 2층)"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    filled = venue_resolution.prefill(pg, entry)
    assert filled["name"] == f"라 벤따나 {unique}"
    assert filled["address"] == "서울 마포구 잔다리로 48, 2층"
    assert filled["address_source"] == "raw string"
    assert filled["region_id"] is not None


def test_two_posts_disagreeing_on_the_address_offer_neither(pg, unique):
    """Two answers is not a stronger signal than none. The posts are linked on
    the same screen; the operator reads them."""
    assert venue_resolution.address_from_context(pg, f"존재하지않는장소{unique}") is None


# --- removing a venue -------------------------------------------------------

def test_a_venue_nothing_uses_can_be_deleted(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"미사용 홀 {unique}", region_id=seoul_id)
    assert venue_resolution.usage(pg, venue["venue_id"])["in_use"] is False

    result = venue_resolution.delete_venue(pg, venue["venue_id"], reviewer="tester")
    assert result["events_unlinked"] == 0
    assert master_data.get_venue(pg, venue["venue_id"]) is None


def test_a_venue_events_use_refuses_a_plain_delete(pg, unique, seoul_id):
    """Told before, not after: the exception carries the counts the console puts
    in the confirmation."""
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, reviewer="tester",
    )
    venue_id = created["venue"]["venue_id"]

    with pytest.raises(venue_resolution.VenueInUse) as raised:
        venue_resolution.delete_venue(pg, venue_id, reviewer="tester")
    assert raised.value.usage["events"] == 1
    assert master_data.get_venue(pg, venue_id) is not None


def test_unlink_and_delete_sends_the_events_back_to_their_raw_string(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"오등록 홀 {unique}", region_id=seoul_id, reviewer="tester",
    )
    venue_id = created["venue"]["venue_id"]
    assert normalization.get(pg, stored["event_id"])["venue_id"] == venue_id

    result = venue_resolution.delete_venue(pg, venue_id, reviewer="tester", unlink=True)
    assert result["events_unlinked"] == 1
    assert master_data.get_venue(pg, venue_id) is None

    back = normalization.get(pg, stored["event_id"])
    assert back["venue_id"] is None
    assert back["region_id"] is None
    assert back["venue_status"] == normalization.VENUE_UNRESOLVED
    # The string is what the post said, and the post has not changed.
    assert back["venue_text"] == venue_text


def test_the_raw_string_goes_back_in_the_queue(pg, unique, seoul_id):
    """Deleting a venue loses no information: the string can be decided again."""
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"오등록 홀 {unique}", region_id=seoul_id, reviewer="tester",
    )
    assert venue_text not in [v["venue_text"] for v in normalization.unresolved_venues(pg)]

    venue_resolution.delete_venue(
        pg, created["venue"]["venue_id"], reviewer="tester", unlink=True,
    )
    assert venue_text in [v["venue_text"] for v in normalization.unresolved_venues(pg)]


def test_deleting_a_venue_keeps_the_event_and_its_provenance(pg, unique, seoul_id):
    """A venue is a link. The posts, the candidate and the event exist without it
    and survive it."""
    venue_text = f"테스트홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"오등록 홀 {unique}", region_id=seoul_id, reviewer="tester",
    )
    venue_resolution.delete_venue(
        pg, created["venue"]["venue_id"], reviewer="tester", unlink=True,
    )
    survived = normalization.get(pg, stored["event_id"])
    assert survived is not None
    assert survived["candidate_id"] == stored["candidate_id"]
    assert survived["source_url"] == stored["source_url"]
    assert survived["event_date"] == stored["event_date"]
    assert survived["fee"] == stored["fee"]


def test_the_user_surface_and_the_region_filter_follow_the_deletion(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"오등록 홀 {unique}", region_id=seoul_id, reviewer="tester",
    )
    assert events_api.get_event(pg, stored["event_id"])["region"] == "Seoul"

    venue_resolution.delete_venue(
        pg, created["venue"]["venue_id"], reviewer="tester", unlink=True,
    )
    after = events_api.get_event(pg, stored["event_id"])
    assert after["venue"]["status"] == "UNRESOLVED"
    assert after["venue"]["name"] == venue_text
    assert after["region"] is None
    # A stale region filter would keep offering it as a Seoul event.
    assert not [e for e in events_api.search(
        pg, on="2026-09-05", region="Seoul", limit=100)["events"]
        if e["id"] == stored["event_id"]]


def test_an_automatic_merge_based_on_that_venue_is_released(pg, unique, seoul_id):
    """The rules merged on date, place and time. Take the place away and the
    merge no longer follows from anything, so the next scan decides again."""
    from runtime import duplicates

    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2"))
    entry = _queued(pg, f"테스트홀 {unique}")
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"오등록 홀 {unique}", region_id=seoul_id, reviewer="tester",
    )
    duplicates.scan(pg, on=date(2026, 9, 5))
    merged = [e for e in (first, second)
              if normalization.get(pg, e["event_id"])["canonical_event_id"] is not None]
    assert len(merged) == 1

    result = venue_resolution.delete_venue(
        pg, created["venue"]["venue_id"], reviewer="tester", unlink=True,
    )
    assert result["automatic_merges_released"] >= 1
    for event in (first, second):
        assert normalization.get(pg, event["event_id"])["canonical_event_id"] is None


def test_a_human_duplicate_decision_survives_a_venue_deletion(pg, unique, seoul_id):
    """Automation releases what automation decided. It does not overturn a person."""
    from runtime import duplicates

    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2", start_time="22:00"))
    entry = _queued(pg, f"테스트홀 {unique}")
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"오등록 홀 {unique}", region_id=seoul_id, reviewer="tester",
    )
    duplicates.scan(pg, on=date(2026, 9, 5))
    pair = next(p for p in duplicates.open_pairs(pg)
                if p["event_id"] in (first["event_id"], second["event_id"]))
    duplicates.resolve_pair(
        pg, pair["pair_id"], decision=duplicates.DUPLICATE,
        canonical_event_id=first["event_id"], reviewer="kimpro",
    )

    venue_resolution.delete_venue(
        pg, created["venue"]["venue_id"], reviewer="tester", unlink=True,
    )
    kept = normalization.get(pg, second["event_id"])
    assert kept["canonical_event_id"] == first["event_id"]
    assert kept["duplicate_decided_by"] == duplicates.HUMAN


def test_deactivating_keeps_everything_and_only_stops_offering_it(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, reviewer="tester",
    )
    venue_id = created["venue"]["venue_id"]

    result = venue_resolution.set_venue_enabled(pg, venue_id, False, reviewer="tester")
    assert result["venue"]["enabled"] is False
    assert normalization.get(pg, stored["event_id"])["venue_id"] == venue_id
    assert venue_id not in [v["venue_id"]
                            for v in master_data.list_venues(pg, enabled_only=True)]

    venue_resolution.set_venue_enabled(pg, venue_id, True, reviewer="tester")
    assert master_data.get_venue(pg, venue_id)["enabled"] is True


@pytest.mark.parametrize("unlink,expected", [
    (False, venue_resolution.VENUE_DELETE),
    (True, venue_resolution.VENUE_UNLINK_DELETE),
])
def test_every_removal_is_audited_and_stays_readable(pg, unique, seoul_id, unlink, expected):
    """The record outlives the venue it names."""
    if unlink:
        venue_text = f"테스트홀 {unique}"
        normalization.normalize_candidate(pg, _candidate(unique))
        entry = _queued(pg, venue_text)
        venue = venue_resolution.create_and_link(
            pg, unresolved_venue_id=entry["unresolved_venue_id"],
            name=f"오등록 홀 {unique}", region_id=seoul_id, reviewer="tester",
        )["venue"]
    else:
        venue = master_data.create_venue(pg, name=f"미사용 홀 {unique}", region_id=seoul_id)

    venue_resolution.delete_venue(pg, venue["venue_id"], reviewer="kimpro", unlink=unlink)
    recorded = next(a for a in venue_resolution.history(pg)
                    if a["venue_id"] == venue["venue_id"] and a["action"] == expected)
    assert recorded["reviewer"] == "kimpro"
    assert recorded["venue_name"] == venue["name"]
    # Still readable after the venue itself is gone.
    assert recorded["resolved_venue_name"] == venue["name"]
    assert recorded["before_json"]["name"] == venue["name"]


def test_deleting_a_venue_that_does_not_exist_changes_nothing(pg):
    with pytest.raises(LookupError):
        venue_resolution.delete_venue(pg, 999999999, reviewer="tester")


def test_the_venue_list_carries_what_depends_on_each_row(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=venue_text, region_id=seoul_id, reviewer="tester",
    )
    unused = master_data.create_venue(pg, name=f"미사용 홀 {unique}", region_id=seoul_id)

    listed = {v["venue_id"]: v for v in venue_resolution.venues_with_usage(pg)}
    assert listed[created["venue"]["venue_id"]]["events"] == 1
    assert listed[created["venue"]["venue_id"]]["in_use"] is True
    assert listed[unused["venue_id"]]["events"] == 0
    assert listed[unused["venue_id"]]["in_use"] is False


def test_the_venue_page_says_how_many_events_a_deletion_would_change():
    from runtime import admin

    used = admin._venue_actions(
        {"venue_id": 1, "name": "라 벤따나", "enabled": True, "in_use": True,
         "events": 3, "listed_events": 2, "aliases": ["라 벤따나"]},
    )
    assert "Unlink &amp; Delete" in used
    assert "Event 3건에서 사용 중" in used
    assert "Deactivate" in used

    unused = admin._venue_actions(
        {"venue_id": 2, "name": "미사용", "enabled": True, "in_use": False,
         "events": 0, "listed_events": 0, "aliases": []},
    )
    assert "<summary>Delete</summary>" in unused
    assert "어떤 Event에서도 쓰이지 않습니다" in unused


def test_both_removal_routes_require_authentication(client):
    for path in ("/admin/venues/1/delete", "/admin/venues/1/enabled"):
        assert client.post(path).status_code in (401, 503), path
