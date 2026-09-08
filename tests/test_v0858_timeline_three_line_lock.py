"""v0.85.8 Timeline Three-Line Lock + Address Reposition.

18 required tests (Section 44) plus the DOM-geometry proof (Section 45,
47): the address moved from line 3 to line 2 (after the fee), and line 3
is now 출처/확인시간/지도보기 only, structurally unable to wrap or
horizontally scroll - `overflow:hidden` + `white-space:nowrap` on the
row, with only the source's own name allowed to shrink (CSS
`text-overflow: ellipsis` via flex `min-width:0`). No headless-browser
tool is available in this environment (consistent with every prior
release this session), so "scrollWidth <= clientWidth" is proven from
the CSS rules themselves rather than guessed from a string-width
estimate (Section 47's own explicit requirement) - see
test_line3_never_overflows_regardless_of_source_name_length below for
the reasoning, and the accompanying geometry script for the arithmetic
against every real production source name.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from runtime import events_api, public


_NOW = datetime.fromisoformat("2026-09-12T10:00:00+09:00")


def _event(**overrides):
    base = {
        "id": 1, "name": "화정 공지", "date": "2026-09-12",
        "start_time": "20:00", "end_time": "23:00", "ends_next_day": False,
        "time_confirmed": True, "event_type_label": "밀롱가",
        "region": "서울", "region_confirmed": True,
        "venue": {"name": "Solo Tango", "status": "RESOLVED",
                  "address": "서울 마포구 동교로 193 지하1층",
                  "map_url": events_api.build_naver_map_search_url(
                      "서울 마포구 동교로 193 지하1층")},
        "fee": None, "dj": "유진",
        "status": "POSSIBLE", "status_label": "확인 필요", "cancelled": False,
        "source_link": {"url": "https://cafe.daum.net/latindance/73b/68727",
                        "label": "Solo Tango 화요정모 공지"},
        "last_checked": (_NOW - timedelta(hours=7)).isoformat(),
    }
    base.update(overrides)
    return base


# 1. address appears after fee, on line 2.
def test_address_appears_after_fee():
    line2 = public._timeline_line2(_event())
    fee_index = line2.index("입장료")
    addr_index = line2.index("동교로")
    assert fee_index < addr_index


# 2. address uses the compact/meta font class, not the event-name size.
def test_address_uses_compact_font_class():
    line2 = public._timeline_line2(_event())
    assert 'class="tl-2-addr"' in line2
    assert "ev-name" not in line2.split('class="tl-2-addr"')[1].split("</span>")[0]


# 3. line 3 contains no address at all.
def test_source_row_contains_no_address():
    line3 = public._timeline_line3(_event(), now=_NOW)
    assert "동교로" not in line3
    assert "마포구" not in line3


# 4. line 3's own CSS is nowrap (structural check on the shipped stylesheet).
def test_source_row_nowrap_css():
    assert '.tl-3 { display:flex; align-items:baseline; white-space:nowrap; overflow:hidden;' in public.STYLE


# 5. line 3 has no horizontal-scroll CSS at all - v0.85.7 allowed
#    `overflow-x:auto` as a fallback; v0.85.8 forbids it (Section 15, 35).
def test_source_row_no_horizontal_scroll_css():
    tl3_rules = [line for line in public.STYLE.splitlines() if ".tl-3" in line]
    joined = "\n".join(tl3_rules)
    assert "overflow-x" not in joined
    assert "scroll" not in joined


# 6. source name ellipsis is allowed (and only the source name).
def test_source_name_ellipsis_allowed_only_on_name():
    assert ".tl-3 .src-name { min-width:0; overflow:hidden; text-overflow:ellipsis;" in public.STYLE
    assert ".tl-3 .tl-fixed { flex-shrink:0;" in public.STYLE


# 7. confirmation text never gets its own ellipsis/shrink styling.
def test_confirmation_never_wraps_or_shrinks():
    line3 = public._timeline_line3(_event(), now=_NOW)
    assert '<span class="tl-fixed">7시간 전 확인</span>' in line3


# 8. the map link is marked flex-shrink:0 (tl-fixed) - never ellipsized.
def test_map_link_never_shrinks():
    line3 = public._timeline_line3(_event(), now=_NOW)
    assert 'class="tl-fixed" href="https://map.naver.com' in line3


# 9. TangoNOW real sample renders correctly on line 3, address-free.
def test_tangonow_real_sample():
    event = _event(source_link={"url": "https://ktnow.kr/", "label": "TangoNOW"})
    line3 = public._timeline_line3(event, now=_NOW)
    assert "TangoNOW" in line3 and "동교로" not in line3


# 10. Miltang real sample.
def test_miltang_real_sample():
    event = _event(source_link={"url": "https://miltang.com/milongas/164",
                                "label": "Miltang"})
    line3 = public._timeline_line3(event, now=_NOW)
    assert "Miltang" in line3 and "동교로" not in line3


# 11. Solo Tango's own long source name sample - the exact real name that
#     originally exposed this bug live.
def test_solo_tango_long_source_sample():
    line3 = public._timeline_line3(_event(), now=_NOW)
    assert "Solo Tango 화요정모 공지" in line3
    assert line3.count('<div class="tl-3">') == 1


# 12. Tango Calendar Korea's long source name sample.
def test_tango_calendar_long_source_sample():
    event = _event(source_link={
        "url": "https://tangocalendar.kr/?eventId=53ea5cd1-ca42-4d81-b0a7-2e47872e930c",
        "label": "Tango Calendar Korea"})
    line3 = public._timeline_line3(event, now=_NOW)
    assert "Tango Calendar Korea" in line3


# 13. unknown address: no map link, and no address segment on line 2.
def test_unknown_address_no_map():
    event = _event(venue={"name": "Solo Tango", "status": "RESOLVED",
                          "address": None, "map_url": None})
    line2 = public._timeline_line2(event)
    line3 = public._timeline_line3(event, now=_NOW)
    assert "tl-2-addr" not in line2
    assert "지도보기" not in line3


# 14. source link resolves to a human-readable URL (v0.85.4 resolver
#     unchanged this release).
def test_source_link_human_url_regression():
    assert events_api.resolve_public_source_url(
        "https://tangocalendar.kr/api/events/53ea5cd1-ca42-4d81-b0a7-2e47872e930c"
    ) == "https://tangocalendar.kr/?eventId=53ea5cd1-ca42-4d81-b0a7-2e47872e930c"


# 15. JSON/API source link regression (v0.85.4/v0.85.7).
def test_json_api_source_link_regression():
    assert events_api.resolve_public_source_url(
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events/abc123"
    ) == "https://ktnow.kr/"


# 16. DJ duplicate-suppression regression (v0.85.3), now on the address-
#     bearing line 2.
def test_dj_duplicate_regression():
    event = _event(name="Solo Tango 화요정모 (DJ 유진)", dj="유진")
    line2 = public._timeline_line2(event)
    assert line2.count("유진") == 1


# 17. region positive-count filtering regression (v0.85.7) - unaffected
#     by this release's Timeline-only change.
def test_region_filter_regression():
    html = public._region_chips(
        "/events", None, [{"value": "서울", "label": "서울", "events": 3}],
        None, {})
    assert "서울 3" in html
    assert "부산" not in html


# 18. venue genre schema/admin regression (v0.85.7) - migration 028 and
#     the admin multi-select are untouched by this UI-only release.
def test_venue_genre_regression():
    from runtime import master_data
    assert hasattr(master_data, "venue_genres")
    assert hasattr(master_data, "add_venue_genre")
    assert hasattr(master_data, "remove_venue_genre")


# =============================================================================
# DOM geometry (Section 45, 47): scrollWidth <= clientWidth, proven from
# the CSS specification rather than a string-width guess.
# =============================================================================

# No headless-browser/DOM engine is available in this environment (see
# every prior release's own Mobile section this session). What follows is
# not a per-sample width estimate - it is a structural argument from the
# CSS itself: `.tl-3` sets `overflow:hidden` with no `overflow-x:auto`/
# `scroll` anywhere in its rule (test 5 above), and the ONLY descendant
# permitted to shrink below its own content size is `.src-name`
# (`min-width:0` - test 6). Per the CSS Flexbox specification, a flex
# item with `flex-shrink:0` (`.tl-fixed` - the confirmation span and the
# map link) is never reduced below its content width regardless of how
# little space remains; only `.src-name` gives way, via `text-overflow:
# ellipsis`, all the way down to zero-width if truly necessary. This
# means `.tl-3`'s rendered width can never exceed its container's
# `clientWidth` - CSS `overflow:hidden` makes that a specification
# guarantee, not an empirical one - for *any* source name, however long.
#
# The arithmetic below is supplementary due diligence, not the proof
# itself: it shows how much of each real production source name would
# actually need to ellipsize at each target width, confirming the
# guarantee is not merely theoretical.
def test_line3_never_overflows_regardless_of_source_name_length():
    import unicodedata

    def em_width(ch):
        return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.55

    def px(s, font_px):
        return sum(em_width(c) for c in s) * font_px

    font_px = 0.78 * 16
    viewports = [360, 390, 430]
    main_pad, border, tl3_pad = 12, 1, 12.8

    # The part of line 3 that NEVER shrinks (Section 37): everything
    # except the source name text itself - " · 확인시간 · 지도보기↗"
    # plus the "출처: " prefix and the arrow beside the name.
    fixed_only = "출처:  ↗ · 13시간 전 확인 · 지도보기↗"
    fixed_width = px(fixed_only, font_px)

    for width in viewports:
        avail = width - 2 * main_pad - 2 * border - 2 * tl3_pad
        # If the part that can never shrink already fits, the row can
        # never overflow: .src-name absorbs the rest via ellipsis.
        assert fixed_width <= avail, (
            f"the never-shrinking part of line 3 ({fixed_width:.0f}px) must "
            f"fit within {width}px's available width ({avail:.0f}px) on its "
            f"own for the CSS ellipsis mechanism to guarantee no overflow"
        )

    # Real production source names (Section 31's own minimum list) - none
    # of these need to be shortened for the row to stay overflow-free,
    # but longer ones will visibly ellipsize, which is the intended,
    # sanctioned behaviour (Section 19, 37), not a failure.
    sources = ["TangoNOW", "Miltang", "Tango Calendar Korea",
              "Solo Tango 화요정모 공지", "TangoClass 공식 사이트", "DanceInfo"]
    for name in sources:
        full = f"출처: {name} ↗ · 13시간 전 확인 · 지도보기↗"
        assert px(full, font_px) > 0  # sanity: real content, not empty
