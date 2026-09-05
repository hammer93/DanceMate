"""v0.82.4 Regional Coverage: a region must be visible and filterable even
before an operator has resolved a venue into the master.

Root cause this guards against: `events.region_id` comes ONLY from a
resolved venue's own region_id (`normalization._region_id()`) - there is no
other path. Real Miltang milongas in Cheongju/Jinju/Changwon/Pohang/Ulsan/
Daegu/Jeju/Seongnam-Bundang sat with `region_id IS NULL` (venue_status
UNRESOLVED) and were shown no region at all, even once the region master
itself carried the right province - because their raw address never
carries the enclosing province name in the first place ("청주시 서원구...",
not "충청북도 청주시..."). `venue_resolution.guess_region_label()` is the
read-only, non-authoritative display/filter fallback for exactly that gap;
this file is its test coverage, alongside the region master itself
(migration 024) and `runtime.collectors.content_mode()` (the v0.82.3 Next
Recommendation).
"""

from __future__ import annotations

from datetime import date, time

import pytest

from runtime import collectors, events_api, normalization, venue_resolution


# --- venue_resolution.guess_region_label() / terms_for_label() (pure) -------

@pytest.mark.parametrize("raw_text,expected", [
    ("Milonga La Plata (StudioAura (청주시 서원구 사창동 474-3, 3F))", "청주"),
    ("JINJU MILONGA (진주 탱고피플 (진주시 평거로7 3층))", "진주"),
    ("ESPERAR MILONGA (Tango club Mi Noche (경남 창원시 마산합포구 가포로25))", "창원"),
    ("바모스 (PosTango (포항시 남구 중앙로 83))", "포항"),
    ("Milonga La Boca (Ulsan Tango Sociedad (울산탱고))", "울산"),
    ("디디디 (Tango Cafe Dia (대구 북구 침산로 168))", "대구"),
    ("JEJU Summ Milonga (씨오르리조트 (제주특별자치도 서귀포시 이어도로 989))", "제주"),
    ("러블리밀롱가 (실루엣 분당정자동 23-1 지파크프라자 5층)", "경기"),
    ("Amigo Studio (부산진구 서면로68번길 41)", "부산"),
])
def test_guess_region_label_matches_real_miltang_addresses(raw_text, expected):
    assert venue_resolution.guess_region_label(raw_text) == expected


def test_guess_region_label_is_none_without_a_recognisable_place():
    assert venue_resolution.guess_region_label("스튜디오 어딘가") is None
    assert venue_resolution.guess_region_label(None) is None
    assert venue_resolution.guess_region_label("") is None


def test_curated_city_beats_its_own_enclosing_province():
    """진주 reads as more useful to a dancer than 경남 (Section 19 of the
    v0.82.4 task) - a string carrying both must prefer the city."""
    assert venue_resolution.guess_region_label("경남 진주시 평거로 7") == "진주"


def test_terms_for_label_is_the_exact_reverse_of_the_guess():
    for term in ("청주", "진주", "창원", "포항", "울산", "대구", "제주"):
        label = venue_resolution.guess_region_label(term)
        assert term in venue_resolution.terms_for_label(label)
    # 분당/성남 (the curated cities) plus the bare province name itself, since
    # a raw address that spells out "경기도 성남시..." in full deserves to
    # match the same filter as one that only ever says "분당".
    assert set(venue_resolution.terms_for_label("경기")) == {"분당", "성남", "경기"}
    assert venue_resolution.terms_for_label("남극") == []


# --- events_api.present() (pure) --------------------------------------------

def _row(**overrides):
    row = {
        "event_id": 1, "event_name": "밀롱가", "event_date": date(2026, 9, 5),
        "start_time": time(19, 30), "end_time": time(23, 30), "end_day_offset": 0,
        "venue_status": "UNRESOLVED", "venue_id": None, "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
    }
    row.update(overrides)
    return row


def test_an_unresolved_venue_still_shows_a_region_guess():
    presented = events_api.present(_row(
        venue_text="JINJU MILONGA (진주시 평거로7 3층)", region_name=None,
    ))
    assert presented["region"] == "진주"
    assert presented["region_confirmed"] is False


def test_a_resolved_region_always_wins_over_the_guess():
    """Even if the raw text also happens to contain a curated city name, a
    real resolved region_id's own name is authoritative."""
    presented = events_api.present(_row(
        venue_text="어떤 청주 관련 이름의 서울 스튜디오",
        region_name="서울", region_code="KR-SEOUL", venue_status="RESOLVED",
    ))
    assert presented["region"] == "서울"
    assert presented["region_confirmed"] is True


def test_no_region_at_all_is_none_not_a_blank_string():
    presented = events_api.present(_row(venue_text="이름 없는 곳", region_name=None))
    assert presented["region"] is None
    assert presented["region_confirmed"] is False


# --- events_api.search(region=...) (DB-backed) ------------------------------

def test_an_unresolved_cheongju_event_is_findable_by_region_filter(pg, unique):
    stored = normalization.normalize_candidate(pg, {
        "candidate_id": int(f"{unique[-6:]}1"), "post_id": 1,
        "source_url": f"https://miltang.com/milongas/{unique}-1",
        "event_name": f"청주 테스트 밀롱가 {unique}",
        "event_type": "MILONGA", "event_date": "2026-09-05",
        "start_time": "19:30", "end_time": "23:30", "end_day_offset": 0,
        "venue": f"StudioAura {unique} (청주시 서원구 사창동 474-3, 3F)",
        "candidate_status": "POSSIBLE", "provenance": normalization.PROVENANCE_LIVE,
    })
    assert stored["venue_status"] == "UNRESOLVED"
    assert stored["region_id"] is None

    result = events_api.search(pg, on="2026-09-05", region="청주", limit=100)
    names = {e["name"] for e in result["events"]}
    assert f"청주 테스트 밀롱가 {unique}" in names

    matched = [e for e in result["events"] if e["name"] == f"청주 테스트 밀롱가 {unique}"][0]
    assert matched["region"] == "청주"
    assert matched["region_confirmed"] is False


def test_a_region_filter_that_matches_nothing_excludes_the_event(pg, unique):
    normalization.normalize_candidate(pg, {
        "candidate_id": int(f"{unique[-6:]}2"), "post_id": 1,
        "source_url": f"https://miltang.com/milongas/{unique}-2",
        "event_name": f"청주 배제 테스트 {unique}",
        "event_type": "MILONGA", "event_date": "2026-09-05",
        "start_time": "19:30", "end_time": "23:30", "end_day_offset": 0,
        "venue": f"StudioAura {unique} (청주시 서원구 사창동 474-3, 3F)",
        "candidate_status": "POSSIBLE", "provenance": normalization.PROVENANCE_LIVE,
    })
    result = events_api.search(pg, on="2026-09-05", region="진주", limit=100)
    names = {e["name"] for e in result["events"]}
    assert f"청주 배제 테스트 {unique}" not in names


# --- source region never overwrites an event's own (pure, code inspection) -

def test_event_region_comes_only_from_the_resolved_venue_not_the_source():
    """Section 27 of the v0.82.4 task: a multi-region source (Miltang, Tango
    Calendar Korea) must never have its own sources.region_id force an
    event's region. _region_id() reads only from venues; nothing in
    normalize_candidate ever reads source.region_id."""
    import inspect

    source = inspect.getsource(normalization._region_id)
    assert "FROM venues" in source
    assert "source" not in source.lower()


# --- runtime.collectors.content_mode() (pure) -------------------------------

@pytest.mark.parametrize("parser,expected", [
    (collectors.WEB_PARSER_TANGONOW, collectors.CONTENT_MODE_NON_HTML_API),
    (collectors.WEB_PARSER_TANGOCALENDAR, collectors.CONTENT_MODE_NON_HTML_API),
    (collectors.WEB_PARSER_MILTANG, collectors.CONTENT_MODE_DISCOVERY_FULL),
    (collectors.WEB_PARSER_DANCEINFO, collectors.CONTENT_MODE_DETAIL_FETCH),
    (collectors.WEB_PARSER_BOARD, collectors.CONTENT_MODE_GENERIC_FETCH),
])
def test_content_mode_matches_each_real_parsers_actual_behaviour(parser, expected):
    source = {"platform": "WEB", "config": {"parser": parser}}
    assert collectors.content_mode(source) == expected


def test_content_mode_for_a_credential_backed_platform():
    assert collectors.content_mode({"platform": "DAUM_CAFE", "config": {}}) \
        == collectors.CONTENT_MODE_SEARCH_API


def test_content_mode_defaults_to_generic_fetch_with_no_parser_set():
    assert collectors.content_mode({"platform": "WEB", "config": {}}) \
        == collectors.CONTENT_MODE_GENERIC_FETCH
