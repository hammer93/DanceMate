"""v0.86.2 Timeline Venue Name Prefix.

Line 2 gains the resolved Venue Master name ahead of the event title -
"Tango O nada · [화정] 9월 8일 화정 공지 (DJ : 유진) · 입장료: ... · 주소...".
Display-only: no event/candidate/venue row is ever written by this
release, only how a resolved venue's own name is rendered on top of data
that already exists (events_api._SELECT already joined `venues`; the only
schema-adjacent change is one additive LATERAL join for the venue's own
alias table, so duplicate-prefix detection never needs a per-event query -
Section 31).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from runtime import events_api, public


_NOW = datetime.fromisoformat("2026-09-08T21:00:00+09:00")


def _event(**overrides):
    base = {
        "id": 1, "name": "[화정] 9월 8일 화정 공지 (DJ : 유진)",
        "date": "2026-09-08",
        "start_time": "20:00", "end_time": "23:30", "ends_next_day": False,
        "time_confirmed": True, "event_type_label": "밀롱가",
        "region": "서울", "region_confirmed": True,
        "venue": {"name": "Tango O nada", "status": "RESOLVED",
                  "address": "서울 마포구 동교로 193 지하1층",
                  "map_url": events_api.build_naver_map_search_url(
                      "서울 마포구 동교로 193 지하1층"),
                  "aliases": []},
        "fee": 8000, "fee_display_text": "8,000원 (22시 이후 5,000원)",
        "dj": "유진",
        "status": "POSSIBLE", "status_label": "확인 필요", "cancelled": False,
        "source_link": {"url": "https://cafe.daum.net/latindance/73b/68727",
                        "label": "Solo Tango 화요정모 공지"},
        "last_checked": (_NOW - timedelta(hours=7)).isoformat(),
    }
    base.update(overrides)
    return base


# 1. resolved venue prefix
def test_resolved_venue_shows_as_a_prefix():
    line2 = public._timeline_line2(_event())
    assert line2.index('<span class="tl-2-venue">Tango O nada</span>') < line2.index("화정")


# 2. no venue -> no prefix
def test_no_venue_shows_no_prefix():
    event = _event(venue={"name": None, "status": "ABSENT", "address": None,
                          "map_url": None, "aliases": []})
    line2 = public._timeline_line2(event)
    assert "tl-2-venue" not in line2


def test_unresolved_venue_shows_no_prefix():
    """Section 5's own safe policy: only RESOLVED venues prefix at all -
    an unresolved venue (raw text read, not yet matched to the Venue
    Master) keeps line 2 exactly as it was before this release."""
    event = _event(venue={"name": "탱고오나다", "status": "UNRESOLVED",
                          "address": None, "map_url": None, "aliases": []})
    line2 = public._timeline_line2(event)
    assert "tl-2-venue" not in line2


# 3. venue exact duplicate suppressed
def test_exact_duplicate_title_suppresses_the_prefix():
    event = _event(name="Tango O Nada 월나다",
                   venue={"name": "Tango O Nada", "status": "RESOLVED",
                          "address": None, "map_url": None, "aliases": []})
    line2 = public._timeline_line2(event)
    assert "tl-2-venue" not in line2
    assert line2.count("Tango O Nada") == 1


# 4. case-insensitive duplicate
def test_case_insensitive_duplicate_is_suppressed():
    event = _event(name="tango o nada 정기모임",
                   venue={"name": "Tango O Nada", "status": "RESOLVED",
                          "address": None, "map_url": None, "aliases": []})
    line2 = public._timeline_line2(event)
    assert "tl-2-venue" not in line2


# 5. whitespace-normalized duplicate
def test_whitespace_normalized_duplicate_is_suppressed():
    event = _event(name="TangoONada 정기모임",
                   venue={"name": "Tango O   Nada", "status": "RESOLVED",
                          "address": None, "map_url": None, "aliases": []})
    line2 = public._timeline_line2(event)
    assert "tl-2-venue" not in line2


# 6. official alias duplicate suppressed
def test_official_alias_in_title_suppresses_the_prefix():
    event = _event(name="오나다 월요밀롱가",
                   venue={"name": "Tango O Nada", "status": "RESOLVED",
                          "address": None, "map_url": None, "aliases": ["오나다"]})
    line2 = public._timeline_line2(event)
    assert "tl-2-venue" not in line2


# 7. unrelated similar name is not suppressed
def test_unrelated_similar_name_is_not_treated_as_a_duplicate():
    """Section 11: similarity alone is never enough - the title below does
    not actually contain "Tango Andante" or any of its aliases, so the
    prefix must still show."""
    event = _event(name="orange 정기 밀롱가",
                   venue={"name": "Tango Andante", "status": "RESOLVED",
                          "address": None, "map_url": None, "aliases": []})
    line2 = public._timeline_line2(event)
    assert '<span class="tl-2-venue">Tango Andante</span>' in line2


# 8. venue before title
def test_venue_appears_before_the_event_title():
    line2 = public._timeline_line2(_event())
    assert line2.index("tl-2-venue") < line2.index("ev-name")


# 9. fee follows title/DJ
def test_fee_follows_title_and_dj():
    line2 = public._timeline_line2(_event())
    assert line2.index("유진") < line2.index("입장료")


# 10. address after fee
def test_address_follows_fee():
    line2 = public._timeline_line2(_event())
    assert line2.index("입장료") < line2.index("tl-2-addr")


# 11. conditional fee regression (v0.85.9)
def test_conditional_fee_regression():
    line2 = public._timeline_line2(_event())
    assert "입장료: 8,000원 (22시 이후 5,000원)" in line2


# 12. end time regression (v0.85.9)
def test_end_time_regression():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert "20:00~23:30" in line1


# 13. DJ duplicate regression (v0.85.3/v0.86.0) - venue prefix must not
#     reintroduce a duplicate DJ badge, nor should it interfere with the
#     existing DJ-in-title suppression.
def test_dj_duplicate_regression_unaffected_by_venue_prefix():
    line2 = public._timeline_line2(_event())
    assert line2.count("유진") == 1


def test_dj_emoji_decorated_title_regression_unaffected_by_venue_prefix():
    event = _event(
        name="\U0001f389이벤트\U0001f389DJ네로\U0001f389",
        dj="네로",
        venue={"name": "OCHO", "status": "RESOLVED", "address": None,
              "map_url": None, "aliases": []},
    )
    line2 = public._timeline_line2(event)
    assert line2.count("네로") == 1
    assert '<span class="tl-2-venue">OCHO</span>' in line2


# 14. source line stays one-line (line 3 never touched by this release)
def test_source_line_still_one_line():
    line3 = public._timeline_line3(_event(), now=_NOW)
    assert line3.count('<div class="tl-3">') == 1


# 15. human-readable source URL regression
def test_human_readable_source_url_regression():
    assert events_api.resolve_public_source_url(
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events/abc123"
    ) == "https://ktnow.kr/"


# 16. Naver map regression
def test_naver_map_regression():
    line3 = public._timeline_line3(_event(), now=_NOW)
    assert 'href="https://map.naver.com/p/search/' in line3
    assert "?c=15.00,0,0,0,dh" in line3
    assert 'target="_blank" rel="noopener noreferrer"' in line3


# 17. positive-region-filter regression (v0.85.7, untouched)
def test_positive_region_filter_regression():
    html = public._region_chips(
        "/events", None, [{"value": "서울", "label": "서울", "events": 3}],
        None, {})
    assert "서울 3" in html
    assert "부산" not in html


# 18. historical event still shows the venue prefix (same renderer, no
#     special-casing for past dates - Section 44)
def test_historical_event_still_shows_venue_prefix():
    past_now = datetime.fromisoformat("2026-09-20T10:00:00+09:00")
    event = _event(date="2026-09-08")
    line1 = public._timeline_line1(event, now=past_now)
    line2 = public._timeline_line2(event)
    assert "tl-2-venue" not in line1  # line 1 is unaffected structurally
    assert '<span class="tl-2-venue">Tango O nada</span>' in line2


# 19. no DB mutation - the rendering path is pure functions over an
#     already-presented dict, never a connection/cursor.
def test_venue_prefix_rendering_takes_no_database_connection():
    import inspect

    for fn in (public._venue_prefix_html, public._timeline_line2,
              public._title_already_announces_venue):
        params = inspect.signature(fn).parameters
        assert not any(name in ("con", "cursor", "pg") for name in params), (
            f"{fn.__name__} must stay a pure display function, never touch the DB"
        )


# 20. API backward compatibility - present() still returns every
#     pre-v0.86.2 field, plus the new additive "aliases" key; a row that
#     predates the venue_aliases LATERAL join (no "venue_aliases" key at
#     all) degrades gracefully instead of raising.
def test_present_is_backward_compatible_without_venue_aliases_column():
    from datetime import date, time

    row = {
        "event_id": 1, "event_name": "화정", "event_date": date(2026, 9, 8),
        "start_time": time(20, 0), "end_time": time(23, 30), "end_day_offset": 0,
        "venue_status": "RESOLVED", "venue_name": "Tango O nada",
        "venue_address": "서울 마포구 동교로 193", "venue_id": 187,
        "fee": 8000, "dj": "유진", "event_type": "MILONGA",
        "engine_status": "POSSIBLE", "review_state": "PENDING",
        "listing_state": "LISTED",
        # deliberately no "venue_aliases" key, simulating a caller/row
        # shape that predates this release
    }
    presented = events_api.present(row)
    assert presented["venue"]["name"] == "Tango O nada"
    assert presented["venue"]["aliases"] == []
    assert presented["fee"] == 8000
    assert presented["dj"] == "유진"
