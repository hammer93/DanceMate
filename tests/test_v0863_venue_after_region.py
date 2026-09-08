"""v0.86.3 Venue After Region.

Moves the resolved venue name from line 2 (v0.86.2's own brief home for
it, "Venue · 행사명 (DJ) · 입장료 · 주소") to line 1, right after the region:
"[서울] Tango O Nada · 오늘 20:00~23:30 밀롱가". Line 2 goes back to what
v0.86.1 had - event title first, no venue prefix.

v0.86.2's title-duplicate-suppression helpers (`_venue_prefix_html()`,
`_title_already_announces_venue()`) are gone: investigated first (Section
8) and confirmed unused anywhere except line 2's own now-removed venue
prefix and its own now-deleted test file - nothing else in the codebase
referenced them. Line 1 has no competing "title" to duplicate against, so
no replacement duplicate-check is needed; a raw event title that happens
to already contain the venue's name (Section 9, "Tango O Nada 월나다") is
the original post's own text and is left exactly as it is - only line 1's
own venue span is new here, and it never touches or hides that title.
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
        "venue": {"name": "Tango O Nada", "status": "RESOLVED",
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


# 1. resolved venue after region
def test_resolved_venue_shown_after_region_on_line1():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert "[서울]" in line1
    assert '<span class="tl-1-venue" title="Tango O Nada" aria-label="Tango O Nada">' \
           'Tango O Nada</span>' in line1
    assert "오늘 20:00~23:30 밀롱가" in line1


def test_venue_appears_immediately_after_region_and_before_date():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert line1.index("[서울]") < line1.index("Tango O Nada") < line1.index("오늘")


# 2. venue removed from line2
def test_venue_removed_from_line2():
    line2 = public._timeline_line2(_event())
    assert "tl-2-venue" not in line2
    assert "Tango O Nada" not in line2
    assert line2.startswith('<div class="tl-2"><span class="ev-name"')


# 3. unresolved venue preserves old line1
def test_unresolved_venue_preserves_pre_v0863_line1():
    event = _event(venue={"name": "탱고오나다", "status": "UNRESOLVED",
                          "address": None, "map_url": None, "aliases": []})
    line1 = public._timeline_line1(event, now=_NOW)
    assert "tl-1-venue" not in line1
    assert "탱고오나다" not in line1
    assert "[서울] 오늘 20:00~23:30 밀롱가" in line1


def test_no_venue_at_all_preserves_pre_v0863_line1():
    event = _event(venue={"name": None, "status": "ABSENT", "address": None,
                          "map_url": None, "aliases": []})
    line1 = public._timeline_line1(event, now=_NOW)
    assert "tl-1-venue" not in line1
    assert "[서울] 오늘 20:00~23:30 밀롱가" in line1


# 4. no empty separator
def test_no_venue_leaves_no_floating_separator():
    event = _event(venue={"name": None, "status": "ABSENT", "address": None,
                          "map_url": None, "aliases": []})
    line1 = public._timeline_line1(event, now=_NOW)
    assert "[서울] ·" not in line1
    assert "[서울]  " not in line1


# 5. canonical venue name used
def test_canonical_master_name_used_verbatim():
    event = _event(venue={"name": "Tango O nada", "status": "RESOLVED",
                          "address": None, "map_url": None, "aliases": ["오나다"]})
    line1 = public._timeline_line1(event, now=_NOW)
    assert "Tango O nada" in line1


# 6. venue alias not shown as canonical
def test_alias_is_never_substituted_for_the_canonical_name():
    event = _event(venue={"name": "Tango O Nada", "status": "RESOLVED",
                          "address": None, "map_url": None, "aliases": ["오나다"]})
    line1 = public._timeline_line1(event, now=_NOW)
    assert "Tango O Nada" in line1
    assert "오나다" not in line1


# 7. long venue ellipsis (CSS-driven; structural check that the span carries
#    the ellipsis class and the full name in title/aria-label regardless of
#    length - Section 20-21)
def test_long_venue_name_carries_full_text_in_title_and_aria_label():
    long_name = "Solo Tango Studio Yeonnamdong Second Floor Practice Room"
    event = _event(venue={"name": long_name, "status": "RESOLVED",
                          "address": None, "map_url": None, "aliases": []})
    line1 = public._timeline_line1(event, now=_NOW)
    assert f'class="tl-1-venue" title="{long_name}" aria-label="{long_name}"' in line1
    assert long_name in line1  # full text present in the DOM; CSS ellipsizes visually


def test_venue_span_has_the_ellipsis_css_rule():
    assert '.tl-1 .tl-1-venue { display:inline-block; max-width:12em;' in public.STYLE
    assert 'text-overflow:ellipsis; white-space:nowrap; }' in public.STYLE


def test_line1_is_not_a_single_line_flex_row():
    """Regression pin for the exact defect the production audit caught:
    an earlier version made .tl-1 `display:flex; white-space:nowrap;
    overflow:hidden`, which silently clips the date/time/type/status tail
    on any real event where that content alone (no venue at all) is
    already wider than a narrow phone viewport - measured ~430px of
    never-shrinking content against a ~310-380px budget on real
    production venues (Mi Vida tango studio, Ulsan Tango Sociedad). Line 1
    must stay plain inline flow, exactly like line 2, so it wraps instead
    of clipping."""
    tl1_rule = public.STYLE.split(".tl-1 {", 1)[1].split("}", 1)[0]
    assert "display:flex" not in tl1_rule
    assert "overflow:hidden" not in tl1_rule
    assert "white-space:nowrap" not in tl1_rule


# 8. date/time preserved
def test_date_and_time_preserved_alongside_venue():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert "오늘" in line1
    assert "20:00~23:30" in line1
    assert "밀롱가" in line1


# 9. end time regression
def test_end_time_regression():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert "20:00~23:30" in line1


def test_midnight_crossing_end_time_regression():
    event = _event(start_time="20:30", end_time="00:00", ends_next_day=True)
    line1 = public._timeline_line1(event, now=_NOW)
    assert "20:30~00:00" in line1


# 10. conditional fee regression
def test_conditional_fee_regression():
    line2 = public._timeline_line2(_event())
    assert "입장료: 8,000원 (22시 이후 5,000원)" in line2


# 11. DJ duplicate regression
def test_dj_duplicate_regression():
    event = _event(name="Solo Tango 화요정모 (DJ 유진)", dj="유진")
    line2 = public._timeline_line2(event)
    assert line2.count("유진") == 1


def test_dj_emoji_decorated_title_regression():
    event = _event(name="\U0001f389이벤트\U0001f389DJ네로\U0001f389", dj="네로")
    line2 = public._timeline_line2(event)
    assert line2.count("네로") == 1


# 12. address still after fee
def test_address_still_follows_fee_on_line2():
    line2 = public._timeline_line2(_event())
    assert line2.index("입장료") < line2.index("tl-2-addr")
    assert "마포구 동교로 193" in line2


# 13. source row one-line
def test_source_row_still_one_line():
    line3 = public._timeline_line3(_event(), now=_NOW)
    assert line3.count('<div class="tl-3">') == 1


# 14. map regression
def test_naver_map_regression():
    line3 = public._timeline_line3(_event(), now=_NOW)
    assert 'href="https://map.naver.com/p/search/' in line3
    assert "?c=15.00,0,0,0,dh" in line3
    assert 'target="_blank" rel="noopener noreferrer"' in line3


# 15. source human link regression
def test_human_readable_source_link_regression():
    assert events_api.resolve_public_source_url(
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events/abc123"
    ) == "https://ktnow.kr/"


# 16. region filter regression
def test_positive_region_filter_regression():
    html = public._region_chips(
        "/events", None, [{"value": "서울", "label": "서울", "events": 3}],
        None, {})
    assert "서울 3" in html
    assert "부산" not in html


# 17. calendar regression (venue display has no effect on week_window/
#     week_counts, both untouched this release)
def test_week_window_unaffected():
    monday, sunday = events_api.week_window(0, now=_NOW)
    assert monday.weekday() == 0
    assert (sunday - monday).days == 6


# 18. no DB mutation - the new line1 venue logic is a pure function over
#     an already-presented dict, never a connection/cursor.
def test_line1_venue_rendering_takes_no_database_connection():
    import inspect

    for fn in (public._timeline_line1_venue_name, public._timeline_line1):
        params = inspect.signature(fn).parameters
        assert not any(name in ("con", "cursor", "pg") for name in params), (
            f"{fn.__name__} must stay a pure display function, never touch the DB"
        )
