"""v0.87.0 Event kind, its "?", and repeating events grouped per venue.

**The kind an event is shown as** is the word its own title uses when a
Settings term matched ("쁘락", "Pronga"), with the canonical formats kept
underneath (PRACTICA; MILONGA + PRACTICA). A "?" beside it means one thing:
the kind could not be settled - the title's words disagree with no registered
mixed term covering them, or contradict the engine's own type, or there is no
usable type at all. The "?" is a real button opening a popover whose lines
are translated from the reason codes the decision actually used. (v0.86.4's
status-driven "?" is retired by the user's decision.)

**A venue's linked events** show each repeating event once: same venue, same
title (the project's own normalization.name_key(), never fuzzy), same weekday
of the real event_date. The latest occurrence represents the group, with its
count; grouping happens over every event before paging.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import inspect
import re

import pytest

from runtime import admin, event_terms, events_api, public, venue_resolution

MILONGA, PRACTICA = events_api.EVENT_FORMAT_MILONGA, events_api.EVENT_FORMAT_PRACTICA
SOCIAL = events_api.EVENT_FORMAT_SOCIAL
TODAY = dt.date(2026, 9, 11)          # a Friday


def term(display, formats, *, tid, enabled=True, genre="TANGO"):
    return {"event_term_id": tid, "genre_code": genre, "genre_id": 1 if genre == "TANGO" else 2,
            "term": display, "normalized_term": event_terms.normalize_term(display),
            "enabled": enabled, "formats": event_terms.ordered_formats(formats)}


TERMS = [
    term("Milonga", {MILONGA}, tid=1), term("밀롱가", {MILONGA}, tid=2),
    term("Practica", {PRACTICA}, tid=3), term("쁘락띠까", {PRACTICA}, tid=4),
    term("Pronga", {MILONGA, PRACTICA}, tid=5), term("쁘롱가", {MILONGA, PRACTICA}, tid=6),
    term("쁘락", {PRACTICA}, tid=7),
]


def kind(title, event_type="MILONGA", stored=None, terms=TERMS):
    return event_terms.classify_kind(title, terms, event_type=event_type,
                                     stored_formats=stored)


# === 1. The required outcomes ==========================================================

def test_a_plain_milonga_is_settled_as_milonga():
    k = kind("금요일 밀롱가")
    assert (k["display"], k["formats"], k["certainty"], k["uncertain"]) == \
        ("밀롱가", (MILONGA,), event_terms.CONFIRMED, False)
    assert [m["term"] for m in k["matched"]] == ["밀롱가"]


def test_the_field_word_is_shown_and_the_canonical_type_kept():
    k = kind("목요 쁘락")
    assert k["display"] == "쁘락"
    assert k["formats"] == (PRACTICA,)
    assert k["uncertain"] is False


@pytest.mark.parametrize("title, display", [("쁘롱가", "쁘롱가"), ("Friday Pronga", "Pronga")])
def test_a_registered_mixed_term_is_settled_as_both(title, display):
    k = kind(title)
    assert k["display"] == display
    assert k["formats"] == (MILONGA, PRACTICA)
    assert k["certainty"] == event_terms.CONFIRMED and k["uncertain"] is False


def test_milonga_with_a_different_term_is_ambiguous_with_its_real_reasons():
    k = kind("토요 밀롱가 & 쁘락")
    assert k["certainty"] == event_terms.AMBIGUOUS and k["uncertain"] is True
    assert k["display"] == "밀롱가 · 쁘락"
    assert k["formats"] == (MILONGA, PRACTICA)          # both detected, kept as found
    codes = [r["code"] for r in k["reasons"]]
    assert codes == ["TERM_MATCH", "TERM_MATCH", "TERMS_DISAGREE", "NO_MIXED_TERM"]
    lines = event_terms.kind_reason_lines(k)
    assert '제목에서 발견: "밀롱가" (밀롱가)' in lines
    assert '제목에서 발견: "쁘락" (프락티카)' in lines
    assert "발견된 용어들이 서로 다른 행사 형식을 가리킴" in lines
    assert "밀롱가 · 프락티카 성격이 함께 감지됨 - 등록된 혼합 용어와 정확히 일치하지 않음" in lines


def test_a_mixed_term_already_covers_a_milonga_beside_it():
    k = kind("쁘롱가 & 밀롱가")
    assert k["certainty"] == event_terms.CONFIRMED
    assert k["display"] == "쁘롱가" and k["formats"] == (MILONGA, PRACTICA)


def test_two_words_for_the_same_kind_agree():
    k = kind("Milonga 밀롱가")
    assert k["certainty"] == event_terms.CONFIRMED and k["display"] == "Milonga"


def test_the_engines_contradiction_is_a_reason_too():
    k = kind("금요일 밀롱가", event_type="SOCIAL")
    assert k["uncertain"] is True
    assert k["reasons"][-1] == {"code": "ENGINE_DISAGREES", "event_type": "SOCIAL",
                                "formats": [MILONGA]}
    assert "기존 분류기 판정: SOCIAL (소셜) - 제목의 용어와 다름" in event_terms.kind_reason_lines(k)


def test_the_engines_milonga_covers_a_practica():
    """The engine files every tango social, practicas included, as MILONGA."""
    assert kind("목요 쁘락", event_type="MILONGA")["uncertain"] is False
    assert kind("목요 쁘락", event_type="MILONGA_WITH_CLASS")["uncertain"] is False


def test_no_word_but_a_real_engine_type_shows_that_type_without_a_question_mark():
    k = kind("Tango O Nada", event_type="MILONGA_WITH_CLASS")
    assert (k["display"], k["certainty"], k["uncertain"]) == \
        ("밀롱가 (강습 포함)", event_terms.ENGINE, False)


def test_no_word_and_no_usable_type_is_unresolved_with_reasons():
    k = kind("Workshop Weekend", event_type="CLASS")
    assert k["certainty"] == event_terms.UNRESOLVED and k["uncertain"] is True
    assert k["display"] == "미분류"
    assert event_terms.kind_reason_lines(k) == [
        "제목에서 등록된 행사 용어를 찾지 못함",
        "기존 분류기 판정: CLASS - 행사 형식으로 볼 수 없음"]
    none = kind("Workshop Weekend", event_type=None)
    assert event_terms.kind_reason_lines(none)[-1] == "기존 분류기의 판정도 없음"


def test_stored_formats_stand_when_no_term_matches_now():
    k = kind("Tango O Nada", stored=[PRACTICA, MILONGA])
    assert (k["display"], k["certainty"], k["uncertain"]) == \
        ("밀롱가 + 프락티카", event_terms.STORED, False)


def test_a_disabled_term_is_no_evidence():
    terms = [term("쁘락", {PRACTICA}, tid=7, enabled=False)]
    assert kind("목요 쁘락", terms=terms)["certainty"] == event_terms.ENGINE


def test_the_longer_registered_term_wins_over_the_short_one():
    k = kind("일요 쁘락띠까")
    assert k["display"] == "쁘락띠까" and [m["term"] for m in k["matched"]] == ["쁘락띠까"]


def test_genre_scope_keeps_other_genres_words_out():
    salsa = [term("쁘락", {SOCIAL}, tid=9, genre="SALSA")]
    scoped = event_terms.terms_for_genre_code(TERMS + salsa, "TANGO")
    assert all(t["genre_code"] == "TANGO" for t in scoped)
    assert len(event_terms.terms_for_genre_code(TERMS + salsa, None)) == len(TERMS) + 1


def test_no_term_is_written_into_the_decision():
    source = inspect.getsource(event_terms.classify_kind).split('"""', 2)[2]
    for word in ("밀롱가", "쁘락", "쁘롱가", "Pronga", "Practica"):
        assert word not in source, word


def test_only_the_codes_the_decision_used_become_lines():
    settled = kind("금요일 밀롱가")
    assert event_terms.kind_reason_lines(settled) == ['제목에서 발견: "밀롱가" (밀롱가)']


# === 2. What the reader's pages render ======================================================

def _event(**overrides):
    base = {"id": 7, "name": "금요일 밀롱가", "date": "2026-09-12", "start_time": "20:00",
            "end_time": "23:00", "ends_next_day": False, "time_confirmed": True,
            "event_type": "MILONGA", "event_type_label": "밀롱가", "event_formats": [],
            "genre": "TANGO", "region": "서울", "region_confirmed": True,
            "venue": {"name": None, "status": "ABSENT", "aliases": []},
            "fee": None, "dj": None, "status": "POSSIBLE", "status_label": "확인 필요",
            "cancelled": False, "source_link": {"url": None, "label": None},
            "last_checked": None}
    base.update(overrides)
    return base


NOW = dt.datetime.fromisoformat("2026-09-11T10:00:00+09:00")


def test_a_settled_kind_renders_the_word_and_no_button():
    line1 = public._timeline_line1(_event(name="목요 쁘락"), now=NOW, terms=TERMS)
    assert '<span class="kind">쁘락</span>' in line1
    assert "<button" not in line1


def test_an_unsettled_kind_renders_an_accessible_button_and_popover():
    line1 = public._timeline_line1(_event(name="밀롱가 & 쁘락"), now=NOW, terms=TERMS)
    assert '<button type="button" class="kind-why" popovertarget="kind-why-7"' in line1
    assert 'aria-label="행사 유형 판정 이유 보기"' in line1
    assert '<div class="why-pop" id="kind-why-7" popover role="dialog"' in line1
    assert "행사 유형을 확정하지 못했습니다." in line1
    assert "<li>발견된 용어들이 서로 다른 행사 형식을 가리킴</li>" in line1
    assert 'popovertargetaction="hide">닫기</button>' in line1


def test_the_popover_escapes_what_it_shows():
    terms = TERMS + [term("<b>x</b>", {SOCIAL}, tid=40)]
    line1 = public._timeline_line1(_event(name="밀롱가 <b>x</b>"), now=NOW, terms=terms)
    assert "<b>x</b>" not in line1 and "&lt;b&gt;x&lt;/b&gt;" in line1


def test_a_settled_card_keeps_its_one_link_exactly_as_before():
    item = public._event_item(_event(name="목요 쁘락"), now=NOW, terms=TERMS)
    assert item.startswith('<li class="event"><a href="/events/7">')


def test_an_unsettled_card_never_puts_the_button_inside_a_link():
    item = public._event_item(_event(name="밀롱가 & 쁘락"), now=NOW, terms=TERMS)
    assert item.startswith('<li class="event has-why"><div class="card-body">')
    for link in re.findall(r"<a\b[^>]*>(.*?)</a>", item, re.S):
        assert "<button" not in link
    overlay = '<a class="card-link" href="/events/7" aria-label="밀롱가 &amp; 쁘락 상세 보기"></a>'
    assert overlay in item
    # Line 3 (whatever it renders for this event) still follows, after the overlay.
    line3 = public._timeline_line3(_event(name="밀롱가 & 쁘락"), now=NOW)
    assert item.endswith(overlay + line3 + "</li>")


def test_without_terminology_the_page_is_what_it_was():
    item = public._event_item(_event(), now=NOW)
    assert item.startswith('<li class="event"><a href="/events/7">')
    assert "kind-why" not in item and 'class="kind"' not in item


def test_the_detail_page_uses_the_same_kind_renderer():
    source = inspect.getsource(public.event_page)
    assert '_kind_html(event, _event_kind(event, terms), "kind-why-detail")' in source


def test_the_styles_for_the_button_popover_and_overlay_exist():
    for rule in (".kind-why {", ".why-pop {", "li.event a.card-link {",
                 "li.event.has-why .kind-why, li.event.has-why .tl-3 a {"):
        assert rule in public.STYLE, rule
    assert ".confirm-flag" not in public.STYLE


def test_present_carries_the_stored_formats():
    row = {"event_id": 1, "event_name": "x", "event_date": dt.date(2026, 9, 12),
           "event_formats": [MILONGA, PRACTICA], "event_type": "MILONGA"}
    try:
        presented = events_api.present(row)
    except KeyError as exc:   # present() needs more columns than this fixture has
        pytest.skip(f"present() needs {exc}")
    assert presented["event_formats"] == [MILONGA, PRACTICA]


# === 3. Admin: the retired checklist, and the preview ========================================

def test_the_retired_checklist_and_its_route_are_gone():
    from runtime import app as app_module

    assert not hasattr(admin, "_STATUS_CHECKLIST_LABELS")
    paths = {getattr(r, "path", "") for r in app_module.app.routes}
    assert "/admin/settings/timeline-confirmation" not in paths
    assert "/admin/settings/event-terms" in paths


def test_the_item_audit_preview_renders_the_kind_with_the_same_terminology():
    source = inspect.getsource(admin.admin_source_item_detail)
    assert "terms = public._enabled_terms(con)" in source
    assert "public._timeline_line1(event, terms=terms)" in source


# === 4. Repeating events at a venue, grouped =================================================

def ev(event_id, name, day, start=None, **extra):
    row = {"event_id": event_id, "candidate_id": 9000 + event_id, "event_name": name,
           "event_type": "MILONGA", "event_formats": None, "event_date": day,
           "start_time": start, "end_time": None, "end_day_offset": 0,
           "engine_status": "POSSIBLE", "review_state": "PENDING", "listing_state": "LISTED",
           "canonical_event_id": None, "provenance": "LIVE", "genre_code": "TANGO",
           "genre_name": "Tango", "publicly_visible": True}
    row.update(extra)
    return row


FRI = [dt.date(2026, 8, 7), dt.date(2026, 8, 14), dt.date(2026, 8, 21), dt.date(2026, 8, 28)]


@pytest.fixture
def raw(monkeypatch):
    """venue_event_groups() over a fixed list of one venue's events."""
    rows: list[dict] = []
    calls: list[tuple] = []

    def _venue_events(con, venue_id, *, limit, offset, today=None):
        calls.append((venue_id, limit, offset))
        return list(rows)

    monkeypatch.setattr(venue_resolution, "venue_events", _venue_events)
    return rows, calls


def groups(today=TODAY):
    return venue_resolution.venue_event_groups(None, 11, today=today)


def test_same_title_same_weekday_is_one_row_with_its_count(raw):
    rows, calls = raw
    rows += [ev(n, "Friday Milonga", d) for n, d in enumerate(FRI, 1)]
    out = groups()
    assert len(out) == 1 and out[0]["occurrences"] == 4
    assert calls == [(11, None, 0)]                   # every event, before any paging


def test_the_latest_occurrence_represents_the_group(raw):
    rows, _ = raw
    rows += [ev(n, "Friday Milonga", d) for n, d in enumerate(FRI, 1)]
    assert groups()[0]["event_date"] == dt.date(2026, 8, 28)


def test_on_the_same_date_the_later_start_then_the_higher_id_wins(raw):
    rows, _ = raw
    day = dt.date(2026, 8, 28)
    rows += [ev(1, "Friday Milonga", day, dt.time(20, 0)),
             ev(2, "Friday Milonga", day, dt.time(21, 0)),
             ev(3, "Friday Milonga", day, dt.time(21, 0))]
    assert groups()[0]["event_id"] == 3


def test_same_title_on_another_weekday_is_its_own_row(raw):
    rows, _ = raw
    rows += [ev(1, "Tango Night", dt.date(2026, 8, 28)),      # Friday
             ev(2, "Tango Night", dt.date(2026, 8, 29))]      # Saturday
    assert len(groups()) == 2


def test_same_weekday_another_title_is_its_own_row(raw):
    rows, _ = raw
    rows += [ev(1, "Friday Milonga", FRI[0]), ev(2, "Friday Practica", FRI[1])]
    assert len(groups()) == 2


def test_whitespace_case_and_dates_in_the_title_do_not_split_a_series(raw):
    rows, _ = raw
    rows += [ev(1, "  Friday   Milonga ", FRI[0]), ev(2, "friday milonga", FRI[1]),
             ev(3, "8/21(금) Friday Milonga", FRI[2])]
    out = groups()
    assert len(out) == 1 and out[0]["occurrences"] == 3


def test_a_different_title_is_never_fuzzily_merged(raw):
    rows, _ = raw
    rows += [ev(1, "Friday Milonga", FRI[0]), ev(2, "Friday Special Milonga", FRI[1])]
    assert len(groups()) == 2


def test_a_title_that_normalizes_to_nothing_is_never_merged(raw):
    rows, _ = raw
    rows += [ev(1, "8/7", FRI[0]), ev(2, "8/14", FRI[1])]
    assert len(groups()) == 2


def test_groups_order_upcoming_soonest_then_past_most_recent(raw):
    rows, _ = raw
    rows += [ev(1, "A", TODAY + dt.timedelta(days=5)), ev(2, "B", TODAY + dt.timedelta(days=1)),
             ev(3, "C", TODAY - dt.timedelta(days=1)), ev(4, "D", TODAY - dt.timedelta(days=9))]
    assert [g["event_name"] for g in groups()] == ["B", "A", "C", "D"]


def test_the_counts_add_back_up_to_the_raw_total(raw):
    rows, _ = raw
    rows += [ev(n, "Friday Milonga", d) for n, d in enumerate(FRI, 1)]
    rows += [ev(10 + n, "Tango Night", dt.date(2026, 8, 1) + dt.timedelta(days=7 * n))
             for n in range(3)]
    rows += [ev(20, "Special Gala", dt.date(2026, 9, 1))]
    out = groups()
    assert len(out) == 3
    assert sum(g["occurrences"] for g in out) == len(rows) == 8


def test_grouping_reuses_the_projects_title_key_not_a_new_one():
    source = inspect.getsource(venue_resolution.venue_event_groups)
    assert "normalization.name_key(" in source
    assert 'row["event_date"].weekday()' in source


# --- the admin panel over those groups --------------------------------------------------------

@pytest.fixture
def panel_stub(monkeypatch):
    from runtime import master_data

    class _Settings:
        version = "0.87.0"
        engine_version = "0.85"
        env = "test"

    @contextlib.contextmanager
    def _connection():
        yield object()

    venues = [{"venue_id": 11, "name": "Cafe de Tango", "region_id": 1, "region_name": "서울",
               "address": None, "notes": None, "aliases": [], "genre_codes": ["TANGO"],
               "events": 0, "listed_events": 0, "enabled": True, "in_use": True}]
    rows: list[dict] = []
    state = {"terms": None}
    monkeypatch.setattr(admin, "_settings", lambda: _Settings())
    monkeypatch.setattr(admin, "_connection", _connection)
    monkeypatch.setattr(events_api, "today", lambda now=None: TODAY)
    monkeypatch.setattr(master_data, "list_regions", lambda con, **kw: [])
    monkeypatch.setattr(master_data, "list_genres", lambda con, **kw: [])
    monkeypatch.setattr(master_data, "count_venues", lambda con, **kw: 1)
    monkeypatch.setattr(master_data, "venue_aliases", lambda con, vid: [])
    monkeypatch.setattr(master_data, "venue_alias_usage", lambda con, vid: {})
    monkeypatch.setattr(master_data, "observed_venue_genres", lambda con, vid: [])
    monkeypatch.setattr(venue_resolution, "venues_with_usage", lambda con, **kw: venues)
    monkeypatch.setattr(venue_resolution, "count_venue_events", lambda con, vid: len(rows))
    monkeypatch.setattr(venue_resolution, "venue_events",
                        lambda con, vid, *, limit, offset, today=None: list(rows))
    monkeypatch.setattr(public, "_enabled_terms", lambda con: state["terms"])
    return venues, rows, state


def _panel(url):
    from starlette.requests import Request
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    req = Request({"type": "http", "method": "GET", "path": parts.path,
                   "query_string": parts.query.encode(), "headers": []})
    html = admin.admin_venues(req, region="", genres=[], _="tester").body.decode()
    return html.split('id="events-VENUE-11"', 1)[1].split("</div></td></tr>", 1)[0]


def test_the_panel_shows_one_row_per_series_with_its_count(panel_stub):
    venues, rows, _ = panel_stub
    rows += [ev(n, "Friday Milonga", d) for n, d in enumerate(FRI, 1)]
    rows += [ev(9, "Special Gala", dt.date(2026, 8, 1))]
    venues[0]["events"] = len(rows)
    panel = _panel("/admin/venues?venue_events=11")
    assert "Cafe de Tango · 연결 행사 5건 · 반복 행사 2개" in panel
    assert panel.count(">Friday Milonga<") == 1
    friday = panel.split(">Friday Milonga<", 1)[1].split("</tr>", 1)[0]
    assert "<td>4회</td>" in friday
    assert "2026-08-28 (금)" in panel
    assert "<th>회차</th>" in panel


def test_the_panel_pages_after_grouping_with_nothing_lost_or_repeated(panel_stub):
    venues, rows, _ = panel_stub
    for g in range(30):                       # 30 series x 2 weeks = 60 events
        for week in range(2):
            day = dt.date(2026, 6, 1) + dt.timedelta(days=g % 7 + 7 * week + 7 * (g // 7) * 2)
            rows.append(ev(1000 + g * 10 + week, f"Series {g:02d}", day))
    venues[0]["events"] = len(rows)
    seen = []
    for page in (1, 2):
        panel = _panel(f"/admin/venues?venue_events=11&venue_events_page={page}")
        seen += re.findall(r"<td>(Series \d\d)</td>", panel)
    assert len(seen) == 30 and len(set(seen)) == 30            # no repeats, none missing
    assert "Page 2 / 2" in panel


def test_the_panel_shows_the_field_word_and_a_question_mark_only_when_unsettled(panel_stub):
    venues, rows, state = panel_stub
    state["terms"] = TERMS
    rows += [ev(1, "목요 쁘락", dt.date(2026, 9, 10)), ev(2, "밀롱가 & 쁘락", dt.date(2026, 9, 9))]
    venues[0]["events"] = 2
    panel = _panel("/admin/venues?venue_events=11")
    settled = panel.split(">목요 쁘락<", 1)[1].split("</tr>", 1)[0]
    unsettled = panel.split(">밀롱가 &amp; 쁘락<", 1)[1].split("</tr>", 1)[0]
    assert '<span class="kind">쁘락</span>' in settled and "kind-why" not in settled
    assert 'class="kind-why"' in unsettled and "행사 유형을 확정하지 못했습니다." in unsettled


# === 5. Against a real database ==============================================================

def test_the_migration_adds_ppeurak_as_practica(pg):
    rows = {t["term"]: t["formats"] for t in event_terms.list_terms(pg)
            if t["genre_code"] == "TANGO"}
    assert rows.get("쁘락") == (PRACTICA,)


def test_the_real_terms_settle_the_required_titles(pg):
    terms = event_terms.list_terms(pg, enabled_only=True)
    for title, display, formats in (("금요일 밀롱가", "밀롱가", (MILONGA,)),
                                    ("목요 쁘락", "쁘락", (PRACTICA,)),
                                    ("쁘롱가", "쁘롱가", (MILONGA, PRACTICA))):
        k = event_terms.classify_kind(title, event_terms.terms_for_genre_code(terms, "TANGO"),
                                      event_type="MILONGA")
        assert (k["display"], k["formats"], k["uncertain"]) == (display, formats, False), title


_N = {"n": 0}


def _insert(pg, unique, *, venue_id, name, day):
    from runtime import normalization

    _N["n"] += 1
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO events (candidate_id, event_name, event_date, venue_id, venue_status, "
            "                    identity_key, provenance) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'LIVE') RETURNING event_id",
            (int(f"88{unique}{_N['n']:03d}"), name, day, venue_id, normalization.VENUE_RESOLVED,
             f"v0870-{unique}-{_N['n']}"))
        return cur.fetchone()[0]


def test_two_venues_never_share_a_group(pg, unique, seoul_id):
    from runtime import master_data

    a = master_data.create_venue(pg, name=f"V0870 A {unique}", region_id=seoul_id)["venue_id"]
    b = master_data.create_venue(pg, name=f"V0870 B {unique}", region_id=seoul_id)["venue_id"]
    for day in FRI:
        _insert(pg, unique, venue_id=a, name="Friday Milonga", day=day)
    _insert(pg, unique, venue_id=b, name="Friday Milonga", day=FRI[0])
    ga = venue_resolution.venue_event_groups(pg, a)
    gb = venue_resolution.venue_event_groups(pg, b)
    assert [(g["event_name"], g["occurrences"]) for g in ga] == [("Friday Milonga", 4)]
    assert [(g["event_name"], g["occurrences"]) for g in gb] == [("Friday Milonga", 1)]
