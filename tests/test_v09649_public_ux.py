"""v0.96.49 Public UX, Mobile E2E & Release Readiness Audit.

What the audit of the reader's pages found, and what keeps it from coming back:

* a long list stopped at 100 under a heading that counted all of it ("253건"),
  and the first screen showed 20 of tonight with no way to the rest;
* "← 목록" on an event always went to today's unfiltered list;
* a festival whose record gave no last day read as a one-day event;
* ``?region=KR-SEOUL`` filtered the list but marked no chip as selected;
* a source whose address cannot be served as a link made the detail page 500;
* the unavailable page said "try again" with nothing to try again with.

Plus the fixed-clock contracts the release protects (v0.96.41/48 festivals,
the overnight ``end_day_offset`` display), pinned with a fixed KST moment.
"""

from __future__ import annotations

import contextlib
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from runtime import events_api, public, sources

KST = events_api.SEOUL
#: v0.96.48's BUSAN TANGO FESTIVAL case, as a fixture: 10/21-10/29, read on 10/22.
FESTIVAL_NOW = datetime(2026, 10, 22, 12, 0, tzinfo=KST)


# --- rendering: no invented period, overnight shown as the next day ----------

def test_a_festival_without_a_stated_last_day_says_so():
    event = {"date": "2026-11-12", "end_date": None, "event_type": "FESTIVAL",
             "start_time": None, "end_time": None}
    detail = public._when_line(event)
    card = public._timeline_line1(event, now=FESTIVAL_NOW)
    for rendered in (detail, card):
        assert "종료일 미확인" in rendered
        assert "부터" in rendered
    assert "11/12(목)" in detail
    # nothing is filled in: no second date appears
    assert not re.search(r"–\d+/\d+", detail)


def test_a_festival_with_its_period_shows_it_and_no_caveat():
    event = {"date": "2026-10-21", "end_date": "2026-10-29", "event_type": "FESTIVAL",
             "start_time": None, "end_time": None}
    detail = public._when_line(event)
    assert "10/21(수)–10/29(목)" in detail
    assert "종료일 미확인" not in detail
    assert "종료일 미확인" not in public._timeline_line1(event, now=FESTIVAL_NOW)


@pytest.mark.parametrize("event_type", ["MILONGA", "PRACTICA", "SOCIAL", None])
def test_a_one_night_event_is_not_given_a_period_caveat(event_type):
    event = {"date": "2026-10-22", "end_date": None, "event_type": event_type,
             "start_time": "20:00", "end_time": "23:00"}
    assert "종료일 미확인" not in public._when_line(event)
    assert "종료일 미확인" not in public._timeline_line1(event, now=FESTIVAL_NOW)


@pytest.mark.parametrize("source_item, start, end", [
    (5601, "21:00", "00:00"),   # danceinfo 오아시스 월요소셜, poster 21:00~24:00
    (3809, "21:00", "01:00"),   # danceinfo 오아시스 한가위 소셜
    (5859, "21:00", "03:00"),   # danceinfo 진주 라틴피루나 17주년파티
    (None, "22:00", "02:00"),
])
def test_an_overnight_end_is_marked_as_the_next_day(source_item, start, end):
    event = {"date": "2026-10-05", "start_time": start, "end_time": end,
             "ends_next_day": True, "event_type": "SOCIAL"}
    for rendered in (public._when_line(event), public._timeline_clock(event)):
        assert start in rendered and end in rendered
        assert "<sup>+1</sup>" in rendered
    # the date shown is the night it starts, never the morning it ends
    assert "10/5(월)" in public._when_line(event)


def test_a_start_without_an_end_is_never_given_one():
    event = {"date": "2026-10-05", "start_time": "21:00", "end_time": None,
             "ends_next_day": False}
    assert "미정" in public._timeline_clock(event)
    assert "미정" in public._when_line(event)
    assert "+1" not in public._timeline_clock(event)


def test_no_time_at_all_reads_unknown_not_midnight():
    event = {"date": "2026-10-05", "start_time": None, "end_time": None}
    assert "시간 미확인" in public._timeline_clock(event)
    assert "00:00" not in public._when_line(event)


# --- the pager ----------------------------------------------------------------

def test_a_list_that_fits_one_page_has_no_pager():
    assert public._pager({"when": "today"}, page=1, shown=28, total=28) == ""
    assert public._pager({"when": "today"}, page=1, shown=100, total=100) == ""


def test_the_pager_keeps_every_filter_and_counts_the_whole_list():
    query = {"when": "upcoming", "genres": "SALSA", "genres_set": "1", "region": "부산",
             "week": "0"}
    first = public._pager(query, page=1, shown=100, total=253)
    assert "1–100 / 253건" in first
    assert 'rel="prev"' not in first
    href = re.search(r'href="([^"]+)" rel="next"', first).group(1).replace("&amp;", "&")
    params = {k: v[0] for k, v in parse_qs(urlsplit(href).query).items()}
    assert params == dict(query, page="2")

    last = public._pager(query, page=3, shown=53, total=253)
    assert "201–253 / 253건" in last
    assert 'rel="next"' not in last
    prev = re.search(r'href="([^"]+)" rel="prev"', last).group(1).replace("&amp;", "&")
    assert parse_qs(urlsplit(prev).query)["page"] == ["2"]


def test_page_one_is_the_plain_address():
    second = public._pager({"when": "today"}, page=2, shown=5, total=105)
    prev = re.search(r'href="([^"]+)" rel="prev"', second).group(1)
    assert "page=" not in prev


# --- "← 목록" goes back to the list the reader came from ------------------------

@pytest.mark.parametrize("referer, expected", [
    ("http://dm.test/events?when=upcoming&genres=SALSA&genres_set=1&region=%EB%B6%80%EC%82%B0",
     "/events?when=upcoming&genres=SALSA&genres_set=1&region=%EB%B6%80%EC%82%B0"),
    ("http://dm.test/?region=%EC%84%9C%EC%9A%B8", "/?region=%EC%84%9C%EC%9A%B8"),
    ("http://dm.test/events", "/events"),
    ("http://dm.test/events?date=2026-10-24&week=0", "/events?date=2026-10-24&week=0"),
])
def test_back_returns_to_this_sites_own_list(referer, expected):
    assert public._back_to_list(referer, "dm.test") == expected


@pytest.mark.parametrize("referer", [
    None, "", "https://evil.example/events?when=today", "http://dm.test/admin/duplicates",
    "http://dm.test/events/123", "javascript:alert(1)", "http://dm.test.evil.example/events",
    "//evil.example/events", "http://[::1/events",
])
def test_back_never_follows_anything_else(referer):
    assert public._back_to_list(referer, "dm.test") == "/events?when=today"


# --- pages over a database ------------------------------------------------------

@pytest.fixture
def web(pg, env, monkeypatch):
    """The real app, every public page reading through the test's own
    rolled-back connection."""
    from runtime import app as app_module

    @contextlib.contextmanager
    def shared():
        yield pg

    monkeypatch.setattr(public, "_connection", shared)
    monkeypatch.setattr(app_module, "_settings", None)
    monkeypatch.setattr(public.alpha_metrics, "record", lambda *a, **k: False)
    return TestClient(app_module.app, raise_server_exceptions=False)


class Night:
    """Live, listed rows inserted the way normalization leaves them."""

    def __init__(self, pg, unique):
        self.pg, self.unique, self.n = pg, unique, 0
        self.source = sources.create_source(
            pg, source_key=f"SRC-V49-{unique}", name=f"v0.96.49 {unique}", platform="WEB",
            source_role="DIRECTORY", queries=[], config={}, enabled=False)["source_id"]

    def add(self, day, *, name=None, kind="MILONGA", last=None, start="20:00",
            region_code=None, venue_text=None, genre_code=None):
        self.n += 1
        url = f"https://example.test/v09649/{self.unique}/{self.n}"
        title = name or f"v49 밀롱가 {self.unique} #{self.n:03d}"
        with self.pg.cursor() as cur:
            cur.execute(
                "INSERT INTO source_items (source_id, external_id, url, title, content_hash, raw) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING source_item_id",
                (self.source, url, url, title, f"h{self.n}", json.dumps({"title": title})))
            item = cur.fetchone()[0]
            region = genre = None
            if genre_code:
                cur.execute("SELECT genre_id FROM genres WHERE code = %s", (genre_code,))
                genre = cur.fetchone()[0]
            if region_code:
                cur.execute("SELECT region_id FROM regions WHERE code = %s", (region_code,))
                row = cur.fetchone()
                region = row[0] if row else None
            cur.execute(
                "INSERT INTO events (candidate_id, source_item_id, source_url, event_name, "
                "  event_type, event_date, end_date, start_time, venue_text, venue_status, "
                "  region_id, genre_id, identity_key, listing_state, provenance) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'LISTED', 'LIVE') "
                "RETURNING event_id",
                (950000000 + self.n, item, url, title, kind, day, last, start, venue_text,
                 "UNRESOLVED" if venue_text else "ABSENT", region, genre,
                 f"v09649|{self.unique}|{self.n}"))
            return cur.fetchone()[0]


def _ids(html):
    return [int(x) for x in re.findall(r'href="/events/(\d+)"', html)]


#: A day no other row in a scratch database is on, so a count is this test's own.
QUIET_DAY = date(2031, 2, 4)


def test_a_long_day_is_paged_and_every_event_is_reachable(pg, unique, web):
    corpus = Night(pg, unique)
    made = {corpus.add(QUIET_DAY) for _ in range(105)}
    first = web.get(f"/events?date={QUIET_DAY.isoformat()}")
    assert first.status_code == 200
    assert "105건" in first.text
    assert "1–100 / 105건" in first.text
    page_one = set(_ids(first.text))
    assert len(page_one) == 100
    nxt = re.search(r'href="([^"]+)" rel="next"', first.text).group(1).replace("&amp;", "&")
    second = web.get(nxt)
    assert second.status_code == 200
    assert "101–105 / 105건" in second.text
    page_two = set(_ids(second.text))
    assert page_one | page_two == made
    assert not page_one & page_two


def test_a_page_past_the_end_says_so_and_offers_the_way_back(pg, unique, web):
    corpus = Night(pg, unique)
    for _ in range(3):
        corpus.add(QUIET_DAY)
    response = web.get(f"/events?date={QUIET_DAY.isoformat()}&page=5")
    assert response.status_code == 200
    assert "이 페이지에는 행사가 없습니다" in response.text
    assert 'rel="prev"' in response.text


def test_page_zero_is_refused(web):
    assert web.get("/events?when=today&page=0").status_code == 422


def test_the_first_screen_links_to_the_rest_of_tonight(pg, unique, web):
    corpus = Night(pg, unique)
    today = events_api.today()
    for _ in range(21):
        corpus.add(today, region_code="KR-SEOUL", genre_code="SALSA")
    response = web.get("/?region=KR-SEOUL&genres=TANGO,SALSA&genres_set=1")
    assert response.status_code == 200
    match = re.search(r'<p class="more"><a href="([^"]+)">오늘 행사 (\d+)건 모두 보기', response.text)
    assert match, "the first screen hid part of tonight with no way to it"
    href = match.group(1).replace("&amp;", "&")
    params = {k: v[0] for k, v in parse_qs(urlsplit(href).query).items()}
    assert params["when"] == "today"
    assert params["genres"] == "TANGO,SALSA" and params["genres_set"] == "1"
    assert params["region"]
    assert int(match.group(2)) >= 21


def test_a_region_named_by_its_code_marks_its_chip(pg, unique, web):
    from runtime import master_data

    seoul = next(r["name"] for r in master_data.list_regions(pg) if r["code"] == "KR-SEOUL")
    corpus = Night(pg, unique)
    corpus.add(events_api.today(), region_code="KR-SEOUL")
    for path in ("/events?when=today&region=KR-SEOUL", f"/events?when=today&region={seoul}"):
        html = web.get(path).text
        chip = re.search(r'<a href="[^"]*"( aria-current="true")?>' + re.escape(seoul) + r" \d+</a>",
                         html)
        assert chip and chip.group(1), f"{path}: the 서울 chip is not marked selected"


def test_an_unknown_region_is_not_mapped_to_a_real_one(pg, web):
    assert public._region_shown(pg, "아틀란티스") == "아틀란티스"
    response = web.get("/events?when=upcoming&region=아틀란티스")
    assert response.status_code == 200
    assert "0건" in response.text
    body = response.text.split("</style>", 1)[1]
    assert not re.search(r'<a [^>]*aria-current="true"', body)


def test_back_from_a_day_keeps_the_genres(pg, unique, web):
    corpus = Night(pg, unique)
    corpus.add(QUIET_DAY)
    html = web.get(f"/events?date={QUIET_DAY.isoformat()}&genres=SALSA&genres_set=1"
                   "&region=KR-BUSAN&week=3").text
    href = re.search(r'class="back-link" href="([^"]+)">&larr; 목록으로', html).group(1)
    params = {k: v[0] for k, v in parse_qs(urlsplit(href.replace("&amp;", "&")).query).items()}
    assert params == {"when": "today", "week": "3", "genres": "SALSA", "genres_set": "1",
                      "region": "KR-BUSAN"}


def test_the_detail_page_returns_to_the_filtered_list(pg, unique, web):
    corpus = Night(pg, unique)
    event_id = corpus.add(QUIET_DAY)
    came_from = "http://testserver/events?when=upcoming&genres=SALSA&genres_set=1"
    html = web.get(f"/events/{event_id}", headers={"Referer": came_from}).text
    assert 'class="back-link" href="/events?when=upcoming&amp;genres=SALSA&amp;genres_set=1"' in html
    plain = web.get(f"/events/{event_id}").text
    assert 'class="back-link" href="/events?when=today"' in plain
    foreign = web.get(f"/events/{event_id}", headers={"Referer": "https://evil.example/events"}).text
    assert 'class="back-link" href="/events?when=today"' in foreign


def test_an_ongoing_festival_is_listed_on_each_of_its_days(pg, unique, web):
    """The v0.96.48 contract, on the pages: started yesterday, ends next week."""
    corpus = Night(pg, unique)
    today = events_api.today()
    festival = corpus.add(today - timedelta(days=1), kind="FESTIVAL",
                          last=today + timedelta(days=7), start=None,
                          name=f"BUSAN TANGO FESTIVAL v49 {unique}")
    assert festival in _ids(web.get("/events?when=today").text)
    assert festival in _ids(web.get("/events?when=tomorrow").text)
    html = web.get(f"/events/{festival}").text
    assert "종료일 미확인" not in html
    ended = corpus.add(today - timedelta(days=9), kind="FESTIVAL",
                       last=today - timedelta(days=1), start=None)
    assert ended not in _ids(web.get("/events?when=upcoming").text)
    open_ended = corpus.add(today + timedelta(days=3), kind="FESTIVAL", start=None,
                            name=f"v49 open-ended festival {unique}")
    response = web.get(f"/events/{open_ended}").text
    assert "부터" in response and "종료일 미확인" in response


def test_a_source_without_a_public_address_is_named_not_linked(monkeypatch, web):
    event = {"id": 7, "name": "링크 없는 행사", "date": "2026-10-22", "start_time": None,
             "end_time": None, "ends_next_day": False, "venue": {}, "fee": None,
             "event_type": "MILONGA", "sources": [
                 {"url": None, "event_name": "API 원문", "is_primary": True,
                  "evidence_label": "일정모음"},
                 {"url": "https://example.test/post/1", "event_name": "원문 글",
                  "is_primary": False, "evidence_label": None}]}
    monkeypatch.setattr(events_api, "get_event", lambda con, event_id: event)
    response = web.get("/events/7")
    assert response.status_code == 200
    assert "API 원문 (원문 링크 없음)" in response.text
    assert response.text.count("/events/7/source?to=") == 1


def test_the_unavailable_page_offers_a_retry(monkeypatch, web):
    from runtime import db

    @contextlib.contextmanager
    def down():
        raise db.DatabaseUnavailable("connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(public, "_connection", down)
    for path in ("/", "/events?when=today&region=KR-BUSAN", "/events/1"):
        response = web.get(path)
        assert response.status_code == 503
        assert public.UNAVAILABLE in response.text
        assert '<a href="">다시 시도</a>' in response.text
        assert 'role="alert"' in response.text
        assert "Traceback" not in response.text


# --- fixed-clock search contract (no wall clock) --------------------------------

@pytest.mark.parametrize("first, last, today_listed", [
    ("2026-10-21", "2026-10-29", True),    # ongoing: started yesterday
    ("2026-10-22", "2026-10-22", True),    # one day, today
    ("2026-10-15", "2026-10-22", True),    # ends today - the last day counts
    ("2026-10-14", "2026-10-21", False),   # ended yesterday
    ("2026-10-23", "2026-10-25", False),   # starts tomorrow
])
def test_the_today_window_on_a_fixed_kst_moment(pg, unique, first, last, today_listed):
    corpus = Night(pg, unique)
    event_id = corpus.add(date.fromisoformat(first), kind="FESTIVAL", start=None,
                          last=date.fromisoformat(last) if last != first else None)
    found = events_api.search(pg, when="today", now=FESTIVAL_NOW, limit=100,
                              region=None)["total"]
    ids = set()
    offset = 0
    while offset < found:
        page = events_api.search(pg, when="today", now=FESTIVAL_NOW, limit=100, offset=offset)
        ids |= {e["id"] for e in page["events"]}
        offset += 100
    assert (event_id in ids) is today_listed


def test_an_open_ended_festival_is_not_kept_past_its_first_day(pg, unique):
    """No last day was stated, so none is assumed: it is on its stated day only."""
    corpus = Night(pg, unique)
    event_id = corpus.add(date(2026, 10, 21), kind="FESTIVAL", start=None)
    on_start = events_api.search(pg, on="2026-10-21", now=FESTIVAL_NOW, limit=100)
    next_day = events_api.search(pg, on="2026-10-22", now=FESTIVAL_NOW, limit=100)
    assert event_id in {e["id"] for e in on_start["events"]}
    assert event_id not in {e["id"] for e in next_day["events"]}
