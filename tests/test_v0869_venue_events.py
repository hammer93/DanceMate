"""v0.86.9 Venue Linked Events.

A venue row on /admin/venues can open the events that point at it - in a
full-width row directly under that venue, on the same list view (page,
filters and any open inline editor kept), exactly like the v0.86.8 inline
editor opens a row in place.

The relation is `events.venue_id`, the real foreign key the "Events using"
count has always used - never a venue name, so a renamed venue keeps every
event it had, and two venues that happen to share a name never share events.

The page tests run everywhere against a stubbed data layer; the SQL tests use
the rolled-back PostgreSQL fixture.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import inspect
import re

import pytest

from runtime import admin, events_api, master_admin, master_data, master_edit, venue_resolution

TODAY = dt.date(2026, 9, 11)


def _request(url: str):
    from urllib.parse import urlsplit

    from starlette.requests import Request

    parts = urlsplit(url)
    return Request({"type": "http", "method": "GET", "path": parts.path,
                    "query_string": parts.query.encode(), "headers": []})


def _event(event_id, *, candidate_id=None, name="Friday Pronga", day=TODAY,
           start=dt.time(20, 0), end=dt.time(23, 30), formats=None, event_type="MILONGA",
           visible=True, listing="LISTED", merged_into=None):
    return {"event_id": event_id, "candidate_id": candidate_id or event_id + 9000,
            "event_name": name, "event_type": event_type, "event_formats": formats,
            "event_date": day, "start_time": start, "end_time": end, "end_day_offset": 0,
            "engine_status": "VERIFIED", "review_state": "PENDING", "listing_state": listing,
            "canonical_event_id": merged_into, "provenance": "LIVE", "genre_name": "Tango",
            "publicly_visible": visible}


@pytest.fixture
def stub_venues(monkeypatch):
    """Two venues on the page: 11 has events, 12 has none."""
    class _Settings:
        version = "0.86.9"
        engine_version = "0.85"
        env = "test"

    @contextlib.contextmanager
    def _connection():
        yield object()

    venues = [
        {"venue_id": 11, "name": "PISTA", "region_id": 1, "region_name": "서울",
         "address": "a", "notes": None, "aliases": [], "genre_codes": ["TANGO"],
         "events": 3, "listed_events": 2, "enabled": True, "in_use": True},
        {"venue_id": 12, "name": "Empty Hall", "region_id": 1, "region_name": "서울",
         "address": None, "notes": None, "aliases": [], "genre_codes": [],
         "events": 0, "listed_events": 0, "enabled": True, "in_use": False},
    ]
    events = {
        11: [_event(101, day=TODAY + dt.timedelta(days=2), formats=["MILONGA", "PRACTICA"]),
             _event(102, name="Saturday Milonga", day=TODAY + dt.timedelta(days=3)),
             _event(100, name="Old Milonga", day=TODAY - dt.timedelta(days=5), start=None,
                    end=None, visible=False, listing="HIDDEN")],
        12: [],
    }
    calls: list[tuple[int, int, int]] = []
    state = {"total": None}

    def _venue_events(con, venue_id, *, limit, offset, today=None):
        calls.append((venue_id, limit, offset))
        return events.get(venue_id, [])[offset:offset + limit]

    monkeypatch.setattr(admin, "_settings", lambda: _Settings())
    monkeypatch.setattr(admin, "_connection", _connection)
    monkeypatch.setattr(events_api, "today", lambda now=None: TODAY)
    monkeypatch.setattr(master_data, "list_regions", lambda con, **kw: [
        {"region_id": 1, "code": "KR-SEOUL", "name": "서울", "country": "South Korea",
         "city": "Seoul", "district": None, "enabled": True}])
    monkeypatch.setattr(master_data, "list_genres", lambda con, **kw: [
        {"genre_id": 1, "code": "TANGO", "name": "Tango", "enabled": True}])
    monkeypatch.setattr(master_data, "count_venues", lambda con, **kw: len(venues))
    monkeypatch.setattr(master_data, "venue_aliases", lambda con, vid: [])
    monkeypatch.setattr(master_data, "venue_alias_usage", lambda con, vid: {})
    monkeypatch.setattr(master_data, "observed_venue_genres", lambda con, vid: [])
    monkeypatch.setattr(venue_resolution, "venues_with_usage", lambda con, **kw: venues)
    monkeypatch.setattr(venue_resolution, "count_venue_events",
                        lambda con, vid: state["total"] if state["total"] is not None
                        else len(events.get(vid, [])))
    monkeypatch.setattr(venue_resolution, "venue_events", _venue_events)
    return {"venues": venues, "events": events, "calls": calls, "state": state}


def _page(url, **kw):
    return admin.admin_venues(_request(url), region=kw.get("region", ""),
                              genres=kw.get("genres", []), _="tester").body.decode()


def _row(html, venue_id):
    return html.split(f'id="row-VENUE-{venue_id}"', 1)[1].split("</tr>", 1)[0]


def _panel(html, venue_id):
    """The panel's own HTML. It ends where its detail row does: every event row
    inside it also ends in </td></tr>, but only the panel's end is </div></td></tr>."""
    return html.split(f'id="events-VENUE-{venue_id}"', 1)[1].split("</div></td></tr>", 1)[0]


# --- the action, and the panel being closed by default -------------------------

def test_every_venue_row_offers_its_linked_events_with_the_count(stub_venues):
    html = _page("/admin/venues")
    for venue in stub_venues["venues"]:
        row = _row(html, venue["venue_id"])
        assert f'aria-expanded="false">연결 행사 {venue["events"]}</a>' in row
    # Closed by default: no venue's events are fetched or rendered.
    assert 'class="rowdetail"' not in html
    assert stub_venues["calls"] == []


def test_the_action_sits_beside_edit_in_the_same_row(stub_venues):
    row = _row(_page("/admin/venues"), 11)
    assert row.index("편집") < row.index("연결 행사 3")


# --- 1/2/3/4: empty, one, many, and never another venue's events -------------

def test_a_venue_with_no_events_shows_an_empty_state(stub_venues):
    html = _page("/admin/venues?venue_events=12")
    panel = _panel(html, 12)
    assert "연결된 행사가 없습니다." in panel
    assert "<table" not in panel
    assert "Empty Hall · 연결 행사 0건" in panel


def test_opening_a_venue_fetches_and_shows_only_that_venue(stub_venues):
    html = _page("/admin/venues?venue_events=11")
    assert [c[0] for c in stub_venues["calls"]] == [11]
    assert html.count('class="rowdetail"') == 1
    assert 'id="events-VENUE-11"' in html and 'id="events-VENUE-12"' not in html
    panel = _panel(html, 11)
    for name in ("Friday Pronga", "Saturday Milonga", "Old Milonga"):
        assert name in panel
    # The detail row sits directly under venue 11's own row.
    assert html.index('id="row-VENUE-11"') < html.index('id="events-VENUE-11"') \
        < html.index('id="row-VENUE-12"')


def test_one_event_shows_every_field_the_schema_has(stub_venues):
    stub_venues["events"][11] = [_event(101, day=TODAY + dt.timedelta(days=2),
                                        formats=["MILONGA", "PRACTICA"])]
    panel = _panel(_page("/admin/venues?venue_events=11"), 11)
    assert "2026-09-13 (일)" in panel                       # date, with weekday
    assert "20:00–23:30" in panel                           # start (and end)
    assert "Friday Pronga" in panel                         # title
    assert "<td>Tango</td>" in panel                        # genre
    assert "밀롱가 + 쁘렉" in panel                          # canonical formats
    assert "VERIFIED" in panel and "PENDING" in panel       # status
    assert 'href="/admin/review/9101"' in panel             # admin detail


def test_the_public_link_appears_only_when_the_public_page_would_serve_it(stub_venues):
    panel = _panel(_page("/admin/venues?venue_events=11"), 11)
    assert 'href="/events/101"' in panel
    assert 'href="/events/100"' not in panel                # hidden: no public page
    assert "HIDDEN" in panel


def test_a_merged_event_says_where_it_went(stub_venues):
    stub_venues["events"][11] = [_event(105, merged_into=77, visible=False)]
    panel = _panel(_page("/admin/venues?venue_events=11"), 11)
    assert "MERGED #77" in panel


def test_an_event_without_formats_falls_back_to_its_own_type_label(stub_venues):
    stub_venues["events"][11] = [_event(106, formats=None, event_type="MILONGA")]
    panel = _panel(_page("/admin/venues?venue_events=11"), 11)
    assert "<td>밀롱가</td>" in panel
    stub_venues["events"][11] = [_event(107, formats=None, event_type=None)]
    panel = _panel(_page("/admin/venues?venue_events=11"), 11)
    assert "<td>미분류</td>" in panel


# --- 6: order, as rendered (the SQL order itself is tested below) -----------

def test_past_events_are_marked_as_past(stub_venues):
    panel = _panel(_page("/admin/venues?venue_events=11"), 11)
    past = panel.split('<tr class="pastevent">', 1)[1].split("</tr>", 1)[0]
    assert "Old Milonga" in past
    assert panel.index("Friday Pronga") < panel.index("Old Milonga")


# --- 7: pagination -------------------------------------------------------------

def test_a_long_list_is_paged_and_keeps_its_place(stub_venues):
    stub_venues["events"][11] = [
        _event(200 + n, name=f"Night {n}", day=TODAY + dt.timedelta(days=n)) for n in range(45)]
    html = _page("/admin/venues?page=1&venue_events=11&venue_events_page=2")
    panel = _panel(html, 11)
    assert stub_venues["calls"][-1] == (11, venue_resolution.VENUE_EVENTS_PAGE_SIZE, 20)
    assert "Page 2 / 3" in panel
    assert panel.count("<tr>") + panel.count('<tr class="pastevent">') == 20 + 1  # + header
    for link in re.findall(r'class="pager-link" href="([^"]+)"', panel):
        link = link.replace("&amp;", "&")
        assert "venue_events=11" in link and "page=1" in link
        assert link.endswith("#events-VENUE-11")


def test_an_out_of_range_panel_page_is_corrected_not_a_500(stub_venues):
    stub_venues["events"][11] = [_event(300 + n) for n in range(45)]
    html = _page("/admin/venues?venue_events=11&venue_events_page=99")
    assert "Page 3 / 3" in _panel(html, 11)


def test_a_stale_or_garbage_parameter_opens_nothing(stub_venues):
    for url in ("/admin/venues?venue_events=999", "/admin/venues?venue_events=abc",
                "/admin/venues?venue_events=-3"):
        html = _page(url)
        assert 'class="rowdetail"' not in html, url
    assert stub_venues["calls"] == []


# --- 8/9: coexists with the inline editor; the list context survives --------

def test_the_open_link_keeps_page_filters_and_lands_on_the_panel(stub_venues):
    html = _page("/admin/venues?region=KR-SEOUL&genres=TANGO&page=1",
                 region="KR-SEOUL", genres=["TANGO"])
    href = re.search(r'href="([^"]+)" aria-expanded="false">연결 행사 3', html).group(1)
    href = href.replace("&amp;", "&")
    for part in ("region=KR-SEOUL", "genres=TANGO", "page=1", "venue_events=11"):
        assert part in href, part
    assert href.startswith("/admin/venues?") and href.endswith("#events-VENUE-11")


def test_closing_keeps_everything_but_the_panel(stub_venues):
    html = _page("/admin/venues?region=KR-SEOUL&page=1&venue_events=11&venue_events_page=2",
                 region="KR-SEOUL")
    close = re.search(r'class="rowbtn" href="([^"]+)">닫기</a>', html).group(1).replace("&amp;", "&")
    assert "venue_events" not in close
    assert "region=KR-SEOUL" in close and "page=1" in close
    assert close.endswith("#row-VENUE-11")


def test_editing_and_linked_events_can_be_open_on_the_same_row(stub_venues):
    html = _page("/admin/venues?edit=VENUE:11&venue_events=11")
    assert 'id="row-VENUE-11" class="editing"' in html
    assert 'id="events-VENUE-11"' in html
    # The row editor's return_to carries the open panel, so saving keeps it open.
    form = html.split('id="edit-VENUE-11"', 1)[1].split("</form>", 1)[0]
    assert "venue_events=11" in form
    # And the editing row still offers the events action.
    assert "연결 행사 3" in _row(html, 11)


# --- 10: the links go to real routes ------------------------------------------

def test_the_detail_links_point_at_routes_that_exist():
    from runtime import app as app_module

    paths = {getattr(r, "path", "") for r in app_module.app.routes}
    assert "/admin/review/{candidate_id}" in paths
    assert "/events/{event_id}" in paths


# --- 5: identity, not names - read straight from the source --------------------

def test_the_query_joins_on_venue_id_and_never_on_a_name():
    source = inspect.getsource(venue_resolution.venue_events) \
        + inspect.getsource(venue_resolution.count_venue_events)
    assert "e.venue_id = %s" in source or "venue_id = %s" in source
    for forbidden in ("LIKE", "venue_text", "v.name", "lower("):
        assert forbidden not in source.split('"""')[-1], forbidden


def test_the_public_visibility_rule_is_reused_not_restated():
    source = inspect.getsource(venue_resolution.venue_events)
    assert "events_api._VISIBLE" in source


# --- against a real database -----------------------------------------------------

_N = {"n": 0}


def _insert_event(pg, unique, *, venue_id, name, day, start=None, genre_id=None):
    """A linked event, written the way normalization writes one: a venue_id
    comes with venue_status RESOLVED (events_venue_link_check insists)."""
    from runtime import normalization

    _N["n"] += 1
    candidate_id = int(f"86{unique}{_N['n']:03d}")
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO events (candidate_id, event_name, event_date, start_time, venue_id, "
            "                    venue_status, genre_id, identity_key, provenance) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'LIVE') RETURNING event_id",
            (candidate_id, name, day, start, venue_id, normalization.VENUE_RESOLVED,
             genre_id, f"v0869-{unique}-{_N['n']}"),
        )
        return cur.fetchone()[0]


@pytest.fixture
def two_venues_with_events(pg, unique, seoul_id):
    a = master_data.create_venue(pg, name=f"V0869 Hall {unique}", region_id=seoul_id)
    b = master_data.create_venue(pg, name=f"V0869 Other {unique}", region_id=seoul_id)
    today = events_api.today()
    ids = {
        "a_plus5": _insert_event(pg, unique, venue_id=a["venue_id"], name="A +5",
                                 day=today + dt.timedelta(days=5)),
        "a_plus1": _insert_event(pg, unique, venue_id=a["venue_id"], name="A +1",
                                 day=today + dt.timedelta(days=1), start=dt.time(21, 0)),
        "a_today": _insert_event(pg, unique, venue_id=a["venue_id"], name="A today",
                                 day=today, start=dt.time(19, 0)),
        "a_minus1": _insert_event(pg, unique, venue_id=a["venue_id"], name="A -1",
                                  day=today - dt.timedelta(days=1)),
        "a_minus10": _insert_event(pg, unique, venue_id=a["venue_id"], name="A -10",
                                   day=today - dt.timedelta(days=10)),
        "b_plus1": _insert_event(pg, unique, venue_id=b["venue_id"], name="B +1",
                                 day=today + dt.timedelta(days=1)),
    }
    return {"a": a["venue_id"], "b": b["venue_id"], "ids": ids, "today": today}


def test_only_the_venues_own_events_come_back(pg, two_venues_with_events):
    data = two_venues_with_events
    rows = venue_resolution.venue_events(pg, data["a"], limit=50)
    assert {r["event_name"] for r in rows} == {"A +5", "A +1", "A today", "A -1", "A -10"}
    assert venue_resolution.count_venue_events(pg, data["a"]) == 5
    b_rows = venue_resolution.venue_events(pg, data["b"], limit=50)
    assert [r["event_name"] for r in b_rows] == ["B +1"]


def test_upcoming_soonest_first_then_past_most_recent_first(pg, two_venues_with_events):
    rows = venue_resolution.venue_events(pg, two_venues_with_events["a"], limit=50,
                                         today=two_venues_with_events["today"])
    assert [r["event_name"] for r in rows] == ["A today", "A +1", "A +5", "A -1", "A -10"]


def test_limit_and_offset_page_through_the_same_order(pg, two_venues_with_events):
    vid = two_venues_with_events["a"]
    first = venue_resolution.venue_events(pg, vid, limit=2, offset=0)
    second = venue_resolution.venue_events(pg, vid, limit=2, offset=2)
    third = venue_resolution.venue_events(pg, vid, limit=2, offset=4)
    names = [r["event_name"] for r in first + second + third]
    assert names == [r["event_name"] for r in venue_resolution.venue_events(pg, vid, limit=50)]
    assert len(third) == 1


def test_renaming_the_venue_keeps_every_event(pg, two_venues_with_events, unique):
    vid = two_venues_with_events["a"]
    master_edit.apply_edit(pg, master_edit.VENUE, vid, {"name": f"Renamed {unique}"},
                           reviewer="tester")
    assert venue_resolution.count_venue_events(pg, vid) == 5


def test_two_venues_sharing_a_name_never_share_events(pg, unique, seoul_id, busan_name):
    busan = next(r for r in master_data.list_regions(pg) if r["name"] == busan_name)
    same = f"Same Name {unique}"
    a = master_data.create_venue(pg, name=same, region_id=seoul_id)
    b = master_data.create_venue(pg, name=same, region_id=busan["region_id"])
    _insert_event(pg, unique, venue_id=a["venue_id"], name="only A", day=events_api.today())
    assert [r["event_name"] for r in venue_resolution.venue_events(pg, a["venue_id"])] == ["only A"]
    assert venue_resolution.venue_events(pg, b["venue_id"]) == []


def test_the_link_count_and_the_panel_total_agree(pg, two_venues_with_events):
    vid = two_venues_with_events["a"]
    listed = {v["venue_id"]: v for v in venue_resolution.venues_with_usage(pg)}
    assert listed[vid]["events"] == venue_resolution.count_venue_events(pg, vid) == 5


def test_a_venue_with_no_events_returns_nothing_not_an_error(pg, unique, seoul_id):
    v = master_data.create_venue(pg, name=f"Quiet {unique}", region_id=seoul_id)
    assert venue_resolution.venue_events(pg, v["venue_id"]) == []
    assert venue_resolution.count_venue_events(pg, v["venue_id"]) == 0


def test_the_rows_carry_the_public_visibility_the_public_page_uses(pg, two_venues_with_events):
    rows = venue_resolution.venue_events(pg, two_venues_with_events["a"], limit=50)
    assert all(r["publicly_visible"] is True for r in rows)   # LIVE + LISTED + not merged
