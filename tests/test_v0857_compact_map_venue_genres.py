"""v0.85.7 Compact Timeline + Venue Dance Genres + Active Region Filter +
Naver Map Link. 41 required tests (Section 55-58): Venue Dance Genres (12),
Region Filter (9), Naver Map (11), Timeline (9).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from runtime import events_api, master_data, master_edit, normalization, public


# =============================================================================
# Venue Dance Genres (12)
# =============================================================================

def _genre_id(pg, code: str) -> int:
    for g in master_data.list_genres(pg):
        if g["code"] == code:
            return g["genre_id"]
    pytest.skip(f"{code} genre is not seeded; run the migrations first")


def _region_name(pg, code: str) -> str:
    """Daegu (KR-DAEGU), unlike Busan, is seeded by the migrations
    themselves rather than added later by hand on production - safe to
    rely on in any freshly-migrated environment, staging included."""
    for r in master_data.list_regions(pg):
        if r["code"] == code:
            return r["name"]
    pytest.skip(f"{code} region is not seeded; run the migrations first")


def _candidate(unique: str, suffix: str = "1", **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/venue/{unique}-{suffix}",
        "event_name": f"장르 테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"장르테스트홀 {unique}",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    base.update(overrides)
    return base


# 1. Tango only
def test_venue_genre_tango_only(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"탱고홀 {unique}", region_id=seoul_id)
    master_edit.set_venue_genres(pg, venue["venue_id"], [_genre_id(pg, "TANGO")])
    codes = {g["genre_code"] for g in master_data.venue_genres(pg, venue["venue_id"])}
    assert codes == {"TANGO"}


# 2. Salsa only
def test_venue_genre_salsa_only(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"살사홀 {unique}", region_id=seoul_id)
    master_edit.set_venue_genres(pg, venue["venue_id"], [_genre_id(pg, "SALSA")])
    codes = {g["genre_code"] for g in master_data.venue_genres(pg, venue["venue_id"])}
    assert codes == {"SALSA"}


# 3. Swing only
def test_venue_genre_swing_only(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"스윙홀 {unique}", region_id=seoul_id)
    master_edit.set_venue_genres(pg, venue["venue_id"], [_genre_id(pg, "SWING")])
    codes = {g["genre_code"] for g in master_data.venue_genres(pg, venue["venue_id"])}
    assert codes == {"SWING"}


# 4. Tango+Salsa (multi-select)
def test_venue_genre_multi_select(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"복합홀 {unique}", region_id=seoul_id)
    master_edit.set_venue_genres(
        pg, venue["venue_id"], [_genre_id(pg, "TANGO"), _genre_id(pg, "SALSA")])
    codes = {g["genre_code"] for g in master_data.venue_genres(pg, venue["venue_id"])}
    assert codes == {"TANGO", "SALSA"}


# 5. no genres - a venue may have none at all, and that is a valid state.
def test_venue_genre_none(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"미확인홀 {unique}", region_id=seoul_id)
    assert master_data.venue_genres(pg, venue["venue_id"]) == []


# 6. duplicate genre prevented - re-confirming the same genre is a no-op.
def test_venue_genre_duplicate_prevented(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"중복홀 {unique}", region_id=seoul_id)
    tango_id = _genre_id(pg, "TANGO")
    master_data.add_venue_genre(pg, venue["venue_id"], tango_id)
    master_data.add_venue_genre(pg, venue["venue_id"], tango_id)
    rows = master_data.venue_genres(pg, venue["venue_id"])
    assert len(rows) == 1


# 7. invalid genre rejected - an unknown genre_id is refused, not silently
#    written as a dangling reference.
def test_venue_genre_invalid_rejected(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"잘못된장르홀 {unique}", region_id=seoul_id)
    with pytest.raises(master_edit.EditError):
        master_edit.set_venue_genres(pg, venue["venue_id"], [999999999])
    assert master_data.venue_genres(pg, venue["venue_id"]) == []


# 8. admin create - genres chosen at venue-creation time are saved.
def test_venue_genre_admin_create(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"생성시홀 {unique}", region_id=seoul_id)
    result = master_edit.set_venue_genres(
        pg, venue["venue_id"], [_genre_id(pg, "TANGO")], reviewer="tester")
    assert result["added"] == ["TANGO"]


# 9. admin edit - a later edit correctly diffs against what is already there.
def test_venue_genre_admin_edit_diffs(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"수정홀 {unique}", region_id=seoul_id)
    master_edit.set_venue_genres(pg, venue["venue_id"], [_genre_id(pg, "TANGO")])
    result = master_edit.set_venue_genres(
        pg, venue["venue_id"], [_genre_id(pg, "SALSA")], reviewer="tester")
    assert result["added"] == ["SALSA"]
    assert result["removed"] == ["TANGO"]
    codes = {g["genre_code"] for g in master_data.venue_genres(pg, venue["venue_id"])}
    assert codes == {"SALSA"}


# 10. venue list display - list_venues() carries genre_codes for the console.
def test_venue_genre_list_display(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"목록표시홀 {unique}", region_id=seoul_id)
    master_edit.set_venue_genres(
        pg, venue["venue_id"], [_genre_id(pg, "TANGO"), _genre_id(pg, "SALSA")])
    rows = master_data.list_venues(pg)
    row = next(r for r in rows if r["venue_id"] == venue["venue_id"])
    assert set(row["genre_codes"]) == {"TANGO", "SALSA"}


# 11. event genre does not mutate venue genre automatically - creating a
#     TANGO event at a venue never writes a venue_genres row on its own.
def test_event_genre_does_not_auto_mutate_venue_genre(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"자동방지홀 {unique}", region_id=seoul_id)
    normalization.normalize_candidate(
        pg, _candidate(unique, venue=f"자동방지홀 {unique}"))
    # No explicit set_venue_genres call at all.
    assert master_data.venue_genres(pg, venue["venue_id"]) == []


# 12. observed genre suggestion - read-only, computed from real event
#     history, never itself written to venue_genres.
def test_observed_genre_suggestion_is_read_only(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"관찰홀 {unique}", region_id=seoul_id)
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'TANGO'")
        tango_genre_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO events (candidate_id, event_name, event_date, venue_id, "
            "  venue_status, genre_id, identity_key, provenance, listing_state, "
            "  engine_status) "
            "VALUES (1, %s, current_date + 1, %s, 'RESOLVED', %s, %s, 'LIVE', "
            "  'LISTED', 'POSSIBLE')",
            (f"관찰 이벤트 {unique}", venue["venue_id"], tango_genre_id, f"key-{unique}"),
        )
    observed = master_data.observed_venue_genres(pg, venue["venue_id"])
    assert any(row["genre_code"] == "TANGO" and row["event_count"] == 1
              for row in observed)
    # Purely observed - nothing was written to venue_genres by computing it.
    assert master_data.venue_genres(pg, venue["venue_id"]) == []


# =============================================================================
# Region Filter (9)
# =============================================================================

def _live_event(pg, unique, suffix, *, region_id, genre_code="TANGO", event_date=None):
    genre_id = _genre_id(pg, genre_code)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO events (candidate_id, event_name, event_date, region_id, "
            "  genre_id, identity_key, provenance, listing_state, engine_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'LIVE', 'LISTED', 'POSSIBLE')",
            (int(f"{unique[-6:]}{suffix}"), f"지역테스트 {unique}-{suffix}",
             event_date or (events_api.today() + timedelta(days=1)).isoformat(),
             region_id, genre_id, f"regionkey-{unique}-{suffix}"),
        )


# 13. count=0 hidden - a region with no matching events under the current
#     window never appears in region_options.
def test_region_zero_count_hidden(pg, unique, seoul_id):
    daegu_name = _region_name(pg, "KR-DAEGU")
    _live_event(pg, unique, "1", region_id=seoul_id)
    facets = public._facets_window(pg, (events_api.today(), events_api.today() + timedelta(days=30)))
    labels = {r["label"] for r in facets["region_options"]}
    assert daegu_name not in labels


# 14. count=1 visible
def test_region_count_one_visible(pg, unique, seoul_id, seoul_name):
    _live_event(pg, unique, "1", region_id=seoul_id)
    facets = public._facets_window(pg, (events_api.today(), events_api.today() + timedelta(days=30)))
    row = next((r for r in facets["region_options"] if r["label"] == seoul_name), None)
    assert row is not None and row["events"] >= 1


# 15. count>1 visible
def test_region_count_multiple_visible(pg, unique, seoul_id, seoul_name):
    _live_event(pg, unique, "1", region_id=seoul_id)
    _live_event(pg, unique, "2", region_id=seoul_id)
    facets = public._facets_window(pg, (events_api.today(), events_api.today() + timedelta(days=30)))
    row = next(r for r in facets["region_options"] if r["label"] == seoul_name)
    assert row["events"] >= 2


# 16. All always visible - "전체" is injected by _region_chips() itself,
#     never filtered by any region's individual count.
def test_all_region_always_visible():
    html = public._region_chips(
        "/events", None, [{"value": "서울", "label": "서울", "events": 3}],
        None, {})
    assert "전체" in html


# 17. genre filter changes region counts
def test_region_counts_scoped_by_genre(pg, unique, seoul_id, seoul_name):
    _live_event(pg, unique, "1", region_id=seoul_id, genre_code="TANGO")
    window = (events_api.today(), events_api.today() + timedelta(days=30))
    all_genres_facets = public._facets_window(pg, window)
    salsa_only_facets = public._facets_window(pg, window, ["SALSA"])
    all_labels = {r["label"] for r in all_genres_facets["region_options"]}
    salsa_labels = {r["label"] for r in salsa_only_facets["region_options"]}
    assert seoul_name in all_labels
    assert seoul_name not in salsa_labels


# 18. date filter changes region counts
def test_region_counts_scoped_by_date(pg, unique, seoul_id, seoul_name):
    far_future = (events_api.today() + timedelta(days=200)).isoformat()
    _live_event(pg, unique, "1", region_id=seoul_id, event_date=far_future)
    near_window = (events_api.today(), events_api.today() + timedelta(days=7))
    far_window = (events_api.today() + timedelta(days=195), events_api.today() + timedelta(days=205))
    near_facets = public._facets_window(pg, near_window)
    far_facets = public._facets_window(pg, far_window)
    near_labels = {r["label"] for r in near_facets["region_options"]}
    far_labels = {r["label"] for r in far_facets["region_options"]}
    assert seoul_name not in near_labels
    assert seoul_name in far_labels


# 19. week navigation changes counts - _facets_for_date uses a single-day
#     window, so a day with nothing shows nothing for that region.
def test_region_counts_change_with_selected_date(pg, unique, seoul_id, seoul_name):
    only_day = (events_api.today() + timedelta(days=3)).isoformat()
    other_day = (events_api.today() + timedelta(days=4)).isoformat()
    _live_event(pg, unique, "1", region_id=seoul_id, event_date=only_day)
    on_day_facets = public._facets_for_date(pg, only_day)
    off_day_facets = public._facets_for_date(pg, other_day)
    assert seoul_name in {r["label"] for r in on_day_facets["region_options"]}
    assert seoul_name not in {r["label"] for r in off_day_facets["region_options"]}


# 20. selected zero-count region resets safely - no ghost chip is rendered
#     for a region whose count has dropped to zero under the current filter.
def test_selected_zero_count_region_no_ghost_chip(pg, unique, seoul_id):
    daegu_name = _region_name(pg, "KR-DAEGU")
    _live_event(pg, unique, "1", region_id=seoul_id)
    facets = public._facets_window(pg, (events_api.today(), events_api.today() + timedelta(days=30)))
    html = public._region_chips("/events", None, facets["region_options"], daegu_name, {})
    assert daegu_name not in html


# 21. ordering retained - highest count still sorts first among the
#     surviving (positive-count) regions.
def test_region_ordering_retained(pg, unique, seoul_id, seoul_name):
    for suffix in ("1", "2", "3"):
        _live_event(pg, unique, suffix, region_id=seoul_id)
    facets = public._facets_window(pg, (events_api.today(), events_api.today() + timedelta(days=30)))
    options = facets["region_options"]
    assert options[0]["label"] == seoul_name


# =============================================================================
# Naver Map (11)
# =============================================================================

# 22. Korean address encoded (exact spec example)
def test_naver_map_korean_address_encoded():
    url = events_api.build_naver_map_search_url("청주시 상당구 상당로 120")
    assert url == (
        "https://map.naver.com/p/search/%EC%B2%AD%EC%A3%BC%EC%8B%9C%20"
        "%EC%83%81%EB%8B%B9%EA%B5%AC%20%EC%83%81%EB%8B%B9%EB%A1%9C%20120"
        "?c=15.00,0,0,0,dh"
    )


# 23. spaces encoded as %20, not literal spaces or '+'
def test_naver_map_spaces_encoded():
    url = events_api.build_naver_map_search_url("서울 마포구 동교로 193")
    assert " " not in url.split("/search/", 1)[1].split("?")[0]
    assert "%20" in url


# 24. floor information preserved in the map query (full raw address, not
#     the display-compacted one)
def test_naver_map_floor_preserved():
    url = events_api.build_naver_map_search_url("서울 마포구 동교로 193 지하1층")
    import urllib.parse
    query = urllib.parse.unquote(url.split("/search/", 1)[1].split("?")[0])
    assert "지하1층" in query


# 25. None -> no link
def test_naver_map_none_address():
    assert events_api.build_naver_map_search_url(None) is None


# 26. empty/whitespace -> no link
def test_naver_map_empty_address():
    assert events_api.build_naver_map_search_url("") is None
    assert events_api.build_naver_map_search_url("   ") is None


# 27. target="_blank" on the rendered link
def test_naver_map_target_blank():
    event = _event_with_map()
    line3 = public._timeline_line3(event, now=_NOW)
    assert 'target="_blank"' in line3


# 28. rel="noopener noreferrer"
def test_naver_map_noopener_noreferrer():
    event = _event_with_map()
    line3 = public._timeline_line3(event, now=_NOW)
    assert 'rel="noopener noreferrer"' in line3


# 29. correct map.naver.com host
def test_naver_map_correct_host():
    url = events_api.build_naver_map_search_url("서울 마포구 동교로 193")
    assert url.startswith("https://map.naver.com/p/search/")


# 30. exact ?c=15.00,0,0,0,dh suffix
def test_naver_map_exact_suffix():
    url = events_api.build_naver_map_search_url("서울 마포구 동교로 193")
    assert url.endswith("?c=15.00,0,0,0,dh")


# 31. full raw address used in the map query, not the display-compacted one
def test_naver_map_uses_full_address_not_compact():
    raw = "서울 마포구 동교로 193 지하1층"
    event = {
        "venue": {"address": raw, "map_url": events_api.build_naver_map_search_url(raw)},
        "source_link": {"url": "https://cafe.daum.net/x/1", "label": "테스트"},
        "last_checked": _NOW.isoformat(),
    }
    line3 = public._timeline_line3(event, now=_NOW)
    # The compact display address never includes 지하1층 (Section 6), but the
    # map query URL must still carry it (Section 34-35).
    assert "마포구 동교로 193…" in line3
    import urllib.parse
    assert "지하1층" in urllib.parse.unquote(line3)


# 32. no API request - purely deterministic string construction, verified
#     by the fact this module makes no network-capable call at all.
def test_naver_map_helper_makes_no_network_call():
    import inspect
    source = inspect.getsource(events_api.build_naver_map_search_url)
    for forbidden in ("requests.", "urlopen", "httpx.", "fetch("):
        assert forbidden not in source


_NOW = datetime.fromisoformat("2026-09-12T10:00:00+09:00")


def _event_with_map(**overrides):
    base = {
        "venue": {"address": "서울 마포구 동교로 193 지하1층",
                  "map_url": events_api.build_naver_map_search_url(
                      "서울 마포구 동교로 193 지하1층")},
        "source_link": {"url": "https://cafe.daum.net/latindance/73b/68727",
                        "label": "Solo Tango 화요정모 공지"},
        "last_checked": (_NOW - timedelta(hours=7)).isoformat(),
    }
    base.update(overrides)
    return base


# =============================================================================
# Timeline (9)
# =============================================================================

# 33. source-confirm-map is one semantic (nowrap) group in the markup
def test_timeline_source_confirm_map_one_group():
    line3 = public._timeline_line3(_event_with_map(), now=_NOW)
    assert '<span class="tl-meta">' in line3
    # everything after the address lives inside that single span
    meta = line3.split('<span class="tl-meta">', 1)[1]
    assert "출처:" in meta and "확인" in meta and "지도보기" in meta


# 34. source clickable
def test_timeline_source_clickable():
    line3 = public._timeline_line3(_event_with_map(), now=_NOW)
    assert '<a href="https://cafe.daum.net/latindance/73b/68727"' in line3


# 35. confirmation visible
def test_timeline_confirmation_visible():
    line3 = public._timeline_line3(_event_with_map(), now=_NOW)
    assert "7시간 전 확인" in line3


# 36. map link visible with an address
def test_timeline_map_link_visible_with_address():
    line3 = public._timeline_line3(_event_with_map(), now=_NOW)
    assert "지도보기" in line3
    assert "map.naver.com" in line3


# 37. map omitted without an address
def test_timeline_map_omitted_without_address():
    event = _event_with_map(venue={"address": None, "map_url": None})
    line3 = public._timeline_line3(event, now=_NOW)
    assert "지도보기" not in line3
    assert "주소 미확인" in line3


# 38. address ellipsis still applied (v0.85.4 regression)
def test_timeline_address_ellipsis_regression():
    line3 = public._timeline_line3(_event_with_map(), now=_NOW)
    assert "마포구 동교로 193…" in line3


# 39. DJ duplicate regression (v0.85.3)
def test_timeline_dj_duplicate_regression():
    event = {"id": 1, "name": "Solo Tango 화요정모 (DJ 유진)", "dj": "유진",
            "fee": None, "cancelled": False}
    line2 = public._timeline_line2(event)
    assert line2.count("유진") == 1


# 40. JSON/API source-link regression (v0.85.4)
def test_timeline_json_link_regression():
    assert events_api.resolve_public_source_url(
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events/abc123"
    ) == "https://ktnow.kr/"


# 41. max 3 structural rows even with address + source + confirm + map all present
def test_timeline_max_three_structural_rows():
    event = _event_with_map(id=1, name="테스트 밀롱가", date="2026-09-12",
                            start_time="19:00", end_time="23:00",
                            ends_next_day=False, time_confirmed=True,
                            event_type_label="밀롱가", region="서울",
                            region_confirmed=True, fee=20000, dj="유진",
                            status="POSSIBLE", status_label="확인 필요",
                            cancelled=False)
    rendered = public._event_item(event, now=_NOW)
    assert rendered.count('<div class="tl-') == 3
