"""Discovery for Tango Calendar Korea (v0.82): a public unpaged JSON array
API. Fixtures are hand-built, shaped like the fields this module reads, not
a captured copy of the real (746-record) response.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone

import pytest

from runtime import tangocalendar_discovery as tc

LIST_URL = "https://tangocalendar.kr/api/events"
TODAY = date(2026, 9, 5)


def _event(**overrides) -> dict:
    base = {
        "id": "3aa58986-65da-41c4-8693-895b005d1f1c",
        "title": "Alonga",
        "description": None,
        "startDate": "2026-09-06T05:00:00Z",  # 14:00 KST
        "endDate": "2026-09-06T09:00:00Z",    # 18:00 KST
        "entranceFee": 13000,
        "venue": "탱고 안단테",
        "djName": None,
        "organizerOther": None,
        "createdAt": "2026-09-02T06:06:40Z",
        "updatedAt": "2026-09-02T06:06:40Z",
        "rrule": None,
        "occurrenceOverrides": None,
        "isCancelled": False,
    }
    base.update(overrides)
    return base


# --- base event parsing --------------------------------------------------

def test_base_event_parses_title_venue_fee():
    posts = tc.parse_events([_event()], LIST_URL, today=TODAY)
    assert len(posts) == 1
    assert posts[0]["title"] == "Alonga"
    assert "장소: 탱고 안단테" in posts[0]["body"]
    assert "입장료 13000원" in posts[0]["body"]


def test_utc_start_time_is_rendered_in_seoul_local_time():
    """05:00Z is 14:00 KST - the body must read the Korean local hour, not
    the API's own UTC value."""
    posts = tc.parse_events([_event()], LIST_URL, today=TODAY)
    assert "14:00~18:00" in posts[0]["body"]


def test_entrance_fee_is_preserved_losslessly_even_as_text():
    posts = tc.parse_events([_event(entranceFee="문의")], LIST_URL, today=TODAY)
    assert "입장료: 문의" in posts[0]["body"]


# --- occurrence overrides --------------------------------------------------

def test_an_occurrence_override_wins_over_the_base_event():
    posts = tc.parse_events(
        [_event(occurrenceOverrides={"venue": "새 장소", "entranceFee": 15000})],
        LIST_URL, today=TODAY,
    )
    assert "장소: 새 장소" in posts[0]["body"]
    assert "입장료 15000원" in posts[0]["body"]


def test_an_override_with_no_value_for_a_field_leaves_the_base_value():
    posts = tc.parse_events(
        [_event(occurrenceOverrides={"entranceFee": 15000})], LIST_URL, today=TODAY,
    )
    # venue was not part of the override, so the base's own venue survives.
    assert "장소: 탱고 안단테" in posts[0]["body"]


def test_a_cancelled_occurrence_override_is_excluded():
    posts = tc.parse_events(
        [_event(occurrenceOverrides={"isCancelled": True})], LIST_URL, today=TODAY,
    )
    assert posts == []


def test_a_cancelled_base_event_with_no_override_is_excluded():
    posts = tc.parse_events([_event(isCancelled=True)], LIST_URL, today=TODAY)
    assert posts == []


def test_a_list_of_overrides_is_handled_not_only_a_single_dict():
    posts = tc.parse_events(
        [_event(occurrenceOverrides=[{"venue": "다른 장소"}])], LIST_URL, today=TODAY,
    )
    assert "장소: 다른 장소" in posts[0]["body"]


def test_organizer_reads_organizerOther_not_a_nonexistent_name_field():
    """v0.82.1, confirmed against a live response: there is no single
    "organizer name" field, only organizerFacebook/organizerKakaoId/
    organizerOther/organizerPhone contact channels - organizerOther is the
    one free-text field among them."""
    posts = tc.parse_events(
        [_event(organizerOther="탱고 안단테 운영팀")], LIST_URL, today=TODAY,
    )
    assert "주최: 탱고 안단테 운영팀" in posts[0]["body"]


def test_an_override_naming_only_occurrence_date_gets_the_bases_time_of_day():
    """v0.82.1, confirmed against a live response: 75 of 151 sampled override
    entries carry only `occurrenceDate`, with their own `startDate`/`endDate`
    left null - the real hour/minute for that occurrence is the base
    event's own, applied to the override's date. Before this was fixed,
    every such override silently collapsed onto the BASE event's own date
    instead of its own - found live in a real weekly series whose seven
    earlier occurrences all resolved to the series' most recent date."""
    posts = tc.parse_events(
        [_event(occurrenceOverrides={
            "occurrenceDate": "2026-09-13T05:00:00.000Z", "startDate": None, "endDate": None,
        })],
        LIST_URL, today=TODAY,
    )
    assert len(posts) == 1
    # The date must be the OVERRIDE's own (Sep 13), not the base's (Sep 6).
    assert "2026년 9월 13일" in posts[0]["body"]
    # But the time-of-day must still be the base's own (14:00-18:00 KST).
    assert "14:00~18:00" in posts[0]["body"]


def test_an_override_with_its_own_start_date_is_not_recombined_with_the_base():
    """When the override DOES supply its own startDate/endDate (76 of 151
    sampled entries), that value must win outright - _combine_date_and_time
    must never override an override that already knows its own time."""
    posts = tc.parse_events(
        [_event(occurrenceOverrides={
            "occurrenceDate": "2026-09-13T09:00:00.000Z",
            "startDate": "2026-09-13T09:00:00.000Z",  # 18:00 KST - a real time change
            "endDate": "2026-09-13T13:00:00.000Z",     # 22:00 KST
        })],
        LIST_URL, today=TODAY,
    )
    assert "2026년 9월 13일" in posts[0]["body"]
    assert "18:00~22:00" in posts[0]["body"]


# --- cutoff -----------------------------------------------------------------

def test_a_past_event_is_dropped_by_the_cutoff():
    past = _event(startDate="2026-08-01T05:00:00Z", endDate="2026-08-01T09:00:00Z")
    assert tc.parse_events([past], LIST_URL, today=TODAY) == []


def test_todays_event_survives_the_cutoff():
    today_event = _event(
        startDate="2026-09-05T05:00:00Z", endDate="2026-09-05T09:00:00Z",
    )
    posts = tc.parse_events([today_event], LIST_URL, today=TODAY)
    assert len(posts) == 1


def test_an_event_with_no_start_date_is_dropped():
    assert tc.parse_events([_event(startDate=None)], LIST_URL, today=TODAY) == []


# --- malformed schema ---------------------------------------------------------

def test_a_non_array_response_raises_a_schema_error():
    """Guards the "unpaged array" assumption itself: if the API ever adds a
    pagination wrapper, this must fail loudly rather than silently parse
    zero events out of a dict."""
    with pytest.raises(tc.DiscoveryError):
        tc.parse_events({"items": [], "cursor": "abc"}, LIST_URL, today=TODAY)


def test_a_blank_title_is_skipped():
    posts = tc.parse_events([_event(title="")], LIST_URL, today=TODAY)
    assert posts == []


def test_a_non_dict_array_entry_is_skipped_not_fatal():
    posts = tc.parse_events([_event(), "not an event"], LIST_URL, today=TODAY)
    assert len(posts) == 1


# --- source_url / published_at ------------------------------------------------

def test_source_url_points_at_the_event_detail_endpoint():
    posts = tc.parse_events([_event()], LIST_URL, today=TODAY)
    assert posts[0]["source_url"] == (
        "https://tangocalendar.kr/api/events/3aa58986-65da-41c4-8693-895b005d1f1c"
    )


def test_published_at_comes_from_updated_or_created_at():
    posts = tc.parse_events([_event()], LIST_URL, today=TODAY)
    assert posts[0]["published_at"] is not None


# --- body synthesis feeds the engine's own extraction rules ------------------

def test_an_unambiguous_24_hour_time_is_read_cleanly_by_the_engine():
    from engine.src import extraction_rules

    posts = tc.parse_events([_event()], LIST_URL, today=TODAY)
    reading = extraction_rules.parse_time_range(posts[0]["body"])
    assert (reading.start, reading.end) == ("14:00", "18:00")
    assert reading.ambiguous is False


def test_a_genuinely_ambiguous_start_hour_is_left_for_a_person_not_guessed():
    """v0.82.1, found live: an earlier version rendered every time as an
    explicit am/pm marker, which invents certainty the API never actually
    gave - a real TangoNOW record's own "09:00~26:00" got flagged as
    WRONG_TIME_SQL (start before noon, evidence EXPLICIT) precisely because
    of that. The fix applies here too (same format_time_range() design):
    a start hour in 1-12 with no other evidence must stay ambiguous."""
    from engine.src import extraction_rules

    posts = tc.parse_events(
        [_event(startDate="2026-09-06T00:00:00Z",   # 09:00 KST
                endDate="2026-09-06T17:00:00Z")],    # 02:00 KST next day
        LIST_URL, today=TODAY,
    )
    reading = extraction_rules.parse_time_range(posts[0]["body"])
    assert reading.ambiguous is True
    assert reading.meridiem_evidence == extraction_rules.EVIDENCE_ABSENT


def test_synthesized_venue_is_read_by_the_engine():
    from engine.src import extraction_rules

    posts = tc.parse_events([_event()], LIST_URL, today=TODAY)
    reading = extraction_rules.extract_venue(posts[0]["body"])
    assert reading.name == "탱고 안단테"


# --- fetching / discover() ----------------------------------------------------

class _Resp(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Headers:
    def get_content_charset(self):
        return "utf-8"


def test_discover_tags_every_post_with_source_and_platform(monkeypatch):
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    opener = lambda request, timeout=None: _Resp([_event()])
    posts = tc.discover(LIST_URL, source_id="SRC-W-003", opener=opener)
    assert posts[0]["source_id"] == "SRC-W-003"
    assert posts[0]["platform"] == "WEB"


def test_discover_honours_robots_disallow(monkeypatch):
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: False)
    with pytest.raises(tc.DiscoveryError):
        tc.discover(LIST_URL, source_id="SRC-W-003", opener=lambda *a, **kw: _Resp([]))


def test_malformed_json_raises_discovery_error():
    class _BadResp(io.BytesIO):
        def __init__(self):
            super().__init__(b"{not json}")
            self.headers = _Headers()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with pytest.raises(tc.DiscoveryError):
        tc._fetch_json(LIST_URL, timeout=5, opener=lambda *a, **kw: _BadResp())


def test_fetch_event_detail_uses_the_documented_endpoint(monkeypatch):
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        return _Resp(_event())

    tc.fetch_event_detail(
        "https://tangocalendar.kr", "3aa58986-65da-41c4-8693-895b005d1f1c", opener=opener,
    )
    assert seen["url"] == (
        "https://tangocalendar.kr/api/events/3aa58986-65da-41c4-8693-895b005d1f1c"
    )


# --- parse_list(): the fixture/snapshot dry-run entry point ------------------

def test_parse_list_reads_a_recorded_api_response_text():
    """The same entry point collectors._collect_snapshot() calls for every
    WEB source - a fixture dry-run must go through this, not a bespoke path."""
    raw_text = json.dumps([_event()])
    posts = tc.parse_list(raw_text, LIST_URL)
    assert posts[0]["title"] == "Alonga"


def test_parse_list_raises_on_invalid_json():
    with pytest.raises(tc.DiscoveryError):
        tc.parse_list("{not json}", LIST_URL)
