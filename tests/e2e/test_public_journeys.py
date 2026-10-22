"""v0.96.49 browser E2E: a dancer's journeys through the public pages.

A real Chromium (Playwright) drives a real DanceMate process over a disposable
PostgreSQL - the same one the rest of the suite runs against, which
tests/conftest.py has already refused unless it declares itself disposable.
Ten fixture rows are committed for the server to read and deleted afterwards;
nothing here can reach Production.

Run it where Playwright is installed (it is not part of the runtime image):

    pip install -r requirements-e2e.txt && python -m playwright install chromium
    python -m pytest -q tests/e2e

Without Playwright the module is skipped and says so - it is never counted as
a pass. Viewports are browser emulation, not a physical phone.

Dates are relative to the server's own Seoul "today" (events_api.today()), so
nothing depends on the wall clock this was written on; the fixed-moment date
contracts are in tests/test_v09649_public_ux.py.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import pytest

sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed - browser E2E NOT RUN (requirements-e2e.txt)")

from conftest import _REAL_POSTGRES  # noqa: E402  (the suite's own disposable DB)

REPO = Path(__file__).resolve().parents[2]
VIEWPORTS = {"m360": (360, 800), "m390": (390, 844), "m430": (430, 932),
             "t768": (768, 1024), "d1280": (1280, 800), "d1440": (1440, 900)}
MOBILE = {"m360", "m390", "m430", "t768"}
SHOT_DIR = os.environ.get("DANCEMATE_E2E_SCREENSHOTS")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _connect():
    import psycopg

    env = _REAL_POSTGRES
    return psycopg.connect(host=env["POSTGRES_HOST"], port=env["POSTGRES_PORT"],
                           dbname=env["POSTGRES_DB"], user=env["POSTGRES_USER"],
                           password=env["POSTGRES_PASSWORD"], autocommit=True)


# --- fixture rows ------------------------------------------------------------

class Corpus:
    """What a dancer could find: each row a case the release has to get right."""

    def __init__(self, con, tag):
        from runtime import events_api

        self.con, self.tag, self.n = con, tag, 0
        self.today = events_api.today()
        self.ids: dict[str, int] = {}
        self.urls: dict[str, str] = {}
        with con.cursor() as cur:
            cur.execute("INSERT INTO sources (source_key, name, platform, source_role, enabled) "
                        "VALUES (%s, %s, 'WEB', 'DIRECTORY', false) RETURNING source_id",
                        (f"SRC-E2E-{tag}", f"E2E {tag}"))
            self.source = cur.fetchone()[0]
            cur.execute("SELECT code, region_id FROM regions")
            self.region = dict(cur.fetchall())
            cur.execute("SELECT code, genre_id FROM genres")
            self.genre = dict(cur.fetchall())
            cur.execute("INSERT INTO venues (name, region_id, address) VALUES (%s, %s, %s) "
                        "RETURNING venue_id",
                        (f"E2E 탱고홀 {tag}", self.region["KR-SEOUL"], "서울 마포구 E2E로 1"))
            self.venue = cur.fetchone()[0]

    def add(self, key, *, days, genre, kind="MILONGA", name=None, start="20:00", end="23:00",
            overnight=False, last_days=None, region=None, venue=False, venue_text=None,
            canonical=None):
        self.n += 1
        url = f"https://example.test/e2e/{self.tag}/{key}"
        title = name or f"E2E {key} {self.tag}"
        with self.con.cursor() as cur:
            cur.execute("INSERT INTO source_items (source_id, external_id, url, title, "
                        "content_hash, raw) VALUES (%s, %s, %s, %s, %s, '{}'::jsonb) "
                        "RETURNING source_item_id", (self.source, url, url, title, f"e2e{self.n}"))
            item = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO events (candidate_id, source_item_id, source_url, event_name, "
                " event_type, event_date, end_date, start_time, end_time, end_day_offset, "
                " venue_id, venue_text, venue_status, genre_id, region_id, identity_key, "
                " canonical_event_id, duplicate_decided_by, listing_state, provenance) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'LIVE') "
                "RETURNING event_id",
                (970000000 + self.n, item, url, title, kind, self.today + timedelta(days=days),
                 self.today + timedelta(days=last_days) if last_days is not None else None,
                 start, end, 1 if overnight else 0, self.venue if venue else None,
                 venue_text or (f"E2E 탱고홀 {self.tag}" if venue else None),
                 "RESOLVED" if venue else ("UNRESOLVED" if venue_text else "ABSENT"),
                 self.genre[genre], self.region.get(region) if region else None,
                 f"e2e|{self.tag}|{key}", canonical, "AUTO" if canonical else None,
                 "HIDDEN" if canonical else "LISTED"))
            self.ids[key] = cur.fetchone()[0]
            self.urls[key] = url
        return self.ids[key]

    def remove(self):
        with self.con.cursor() as cur:
            cur.execute("DELETE FROM alpha_view_log WHERE event_id = ANY(%s)",
                        (list(self.ids.values()),))
            cur.execute("UPDATE events SET canonical_event_id = NULL WHERE source_item_id IN "
                        "(SELECT source_item_id FROM source_items WHERE source_id = %s)",
                        (self.source,))
            cur.execute("DELETE FROM events WHERE source_item_id IN (SELECT source_item_id "
                        "FROM source_items WHERE source_id = %s)", (self.source,))
            cur.execute("DELETE FROM source_items WHERE source_id = %s", (self.source,))
            cur.execute("DELETE FROM sources WHERE source_id = %s", (self.source,))
            cur.execute("DELETE FROM venues WHERE venue_id = %s", (self.venue,))


@pytest.fixture(scope="module")
def corpus():
    if not _REAL_POSTGRES.get("POSTGRES_PASSWORD"):
        pytest.skip("no disposable PostgreSQL configured (TEST_POSTGRES_*) - browser E2E NOT RUN")
    con = _connect()
    c = Corpus(con, f"{int(time.time()) % 1000000}")
    c.add("tango_today", days=0, genre="TANGO", region="KR-SEOUL", venue=True,
          name=f"E2E Tango Tonight {c.tag}")
    c.add("folded_child", days=0, genre="TANGO", region="KR-SEOUL", venue=True,
          name=f"E2E Folded Duplicate {c.tag}", canonical=c.ids["tango_today"])
    c.add("salsa_overnight", days=0, genre="SALSA", kind="SOCIAL", region="KR-BUSAN",
          start="21:00", end="01:00", overnight=True, name=f"E2E Salsa Overnight {c.tag}")
    c.add("swing_tomorrow", days=1, genre="SWING", kind="SOCIAL", region="KR-DAEJEON",
          start="19:00", end="22:00", name=f"E2E Swing Tomorrow {c.tag}")
    c.add("festival_ongoing", days=-1, last_days=7, genre="TANGO", kind="FESTIVAL",
          region="KR-BUSAN", start=None, end=None, name=f"BUSAN TANGO FESTIVAL E2E {c.tag}")
    c.add("practica", days=3, genre="TANGO", kind="PRACTICA", region="KR-SEOUL",
          start="15:00", end="18:00", name=f"PRACTICA / 프락티카 {c.tag}")
    c.add("unknown_time", days=5, genre="TANGO", region="KR-SEOUL", start=None, end=None,
          name=f"E2E Time Unknown {c.tag}")
    c.add("unresolved_venue", days=2, genre="TANGO", venue_text="대전 땅고 오나다 (E2E 미등록)",
          name=f"E2E Unresolved Venue {c.tag}")
    c.add("long_title", days=4, genre="TANGO", region="KR-SEOUL",
          venue_text="Social Tango Academy (소셜탱고아카데미) (서울 마포구 동교로 201 4층) E2E",
          name=f"SEOUL TANGO WEEK · Social Tango Academy 초청 특별 밀롱가 & 프락티카 "
               f"마라톤 Extended Edition 2026 {c.tag}")
    c.add("salsa_d12", days=12, genre="SALSA", kind="SOCIAL", region="KR-SEOUL",
          name=f"E2E Salsa D12 {c.tag}")
    c.add("tango_d25", days=25, genre="TANGO", region="KR-SEOUL", name=f"E2E Tango D25 {c.tag}")
    yield c
    c.remove()
    con.close()


def _serve(port, db_port=None):
    env = dict(os.environ)
    env.update({k: v for k, v in _REAL_POSTGRES.items() if v})
    if db_port:
        env["POSTGRES_PORT"] = str(db_port)
    env.update({"DANCEMATE_ENV": "test", "PYTHONIOENCODING": "utf-8",
                "ADMIN_USERNAME": "e2e", "ADMIN_PASSWORD": "e2e-local-only"})
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "runtime.app:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return proc
        except Exception:  # noqa: BLE001 - not up yet
            if proc.poll() is not None:
                break
            time.sleep(0.2)
    proc.terminate()
    pytest.fail("the DanceMate server did not start")


@pytest.fixture(scope="module")
def base(corpus):
    port = _free_port()
    proc = _serve(port)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Session:
    """One viewport's page, with every JS error and failed request it saw."""

    def __init__(self, browser, base, viewport="m390"):
        w, h = VIEWPORTS[viewport]
        mobile = viewport in MOBILE
        self.viewport = viewport
        self.ctx = browser.new_context(viewport={"width": w, "height": h}, is_mobile=mobile,
                                       has_touch=mobile, locale="ko-KR",
                                       timezone_id="Asia/Seoul")
        self.page = self.ctx.new_page()
        self.base = base
        self.errors: list[str] = []
        self.documents: list[str] = []
        self.page.on("pageerror", lambda exc: self.errors.append(f"pageerror: {exc}"))
        self.page.on("console", lambda m: self.errors.append(f"console: {m.text}")
                     if m.type == "error" else None)
        self.page.on("request", lambda r: self.documents.append(r.url)
                     if r.resource_type == "document" else None)

    def go(self, path):
        response = self.page.goto(self.base + path, wait_until="load")
        return response

    def tap(self, locator):
        if self.viewport in MOBILE:
            locator.tap()
        else:
            locator.click()

    def navigate_by(self, locator):
        with self.page.expect_navigation(wait_until="load"):
            self.tap(locator)

    def ids(self):
        return [int(x) for x in re.findall(r'href="/events/(\d+)"', self.page.content())]

    def query(self):
        return {k: v[0] for k, v in parse_qs(urlsplit(self.page.url).query).items()}

    def api_ids(self, **params):
        ids, offset = [], 0
        while True:
            q = dict(params, limit=100, offset=offset)
            r = self.page.request.get(f"{self.base}/api/events?{urlencode(q)}")
            assert r.status == 200
            data = r.json()
            ids += [e["id"] for e in data["events"]]
            offset += 100
            if offset >= data["total"]:
                return ids

    def layout(self):
        return self.page.evaluate(
            "() => ({vw: innerWidth, sw: document.documentElement.scrollWidth,"
            " controls: [...document.querySelectorAll('nav a, .filters a, label.chip,"
            " .cal-day, .cal-nav')].filter(e => e.getBoundingClientRect().width > 0)"
            ".map(e => { const r = e.getBoundingClientRect(); const s = e.closest('nav.dirtabs');"
            " return {t: e.textContent.trim().slice(0, 20), l: r.left, r: r.right,"
            " scroller: !!s}; })})")

    def shot(self, name):
        if SHOT_DIR:
            os.makedirs(SHOT_DIR, exist_ok=True)
            self.page.screenshot(path=os.path.join(SHOT_DIR, f"{name}.png"), full_page=True)

    def close(self):
        self.ctx.close()


@pytest.fixture
def s(browser, base):
    session = Session(browser, base)
    yield session
    errors = list(session.errors)
    session.close()
    assert not errors, f"public JS errors: {errors}"


def _only_genre(s, code):
    """Untick every style chip but one, the way a reader does: one tap each."""
    while True:
        boxes = s.page.locator("form.genres input[type=checkbox]")
        target = None
        for i in range(boxes.count()):
            box = boxes.nth(i)
            value = box.get_attribute("value")
            if box.is_checked() != (value == code):
                target = s.page.locator(f"form.genres label.chip:has(input[value='{value}'])")
                break
        if target is None:
            return
        s.navigate_by(target)


def _listed_matches_api(s, **params):
    shown = s.ids()
    expected = s.api_ids(**params)
    assert sorted(set(shown)) == sorted(expected[:100]) or set(shown) == set(expected)
    return shown


# --- E2E-01 .. E2E-25 ------------------------------------------------------------

def test_e2e_01_open_main_page(s, corpus):
    response = s.go("/")
    assert response.status == 200
    assert s.page.locator("h1").inner_text() == "DanceMate"
    assert s.page.locator("form.genres label.chip").count() >= 3
    assert corpus.ids["tango_today"] in s.ids()
    s.shot("mobile-main")


@pytest.mark.parametrize("number, code, mine, others", [
    ("02", "TANGO", "tango_d25", ("salsa_d12", "swing_tomorrow")),
    ("03", "SALSA", "salsa_d12", ("tango_d25", "swing_tomorrow")),
    ("04", "SWING", "swing_tomorrow", ("tango_d25", "salsa_d12")),
])
def test_e2e_02_04_select_a_genre(s, corpus, number, code, mine, others):
    s.go("/events?when=upcoming")
    _only_genre(s, code)
    assert s.query().get("genres") == code
    shown = _listed_matches_api(s, when="upcoming", genres=code)
    assert corpus.ids[mine] in shown
    for other in others:
        assert corpus.ids[other] not in shown
    assert s.query()["when"] == "upcoming", "changing the style reset the dates"


def test_e2e_05_change_region_keeps_genre_and_dates(s, corpus):
    s.go("/events?when=upcoming")
    _only_genre(s, "TANGO")
    s.navigate_by(s.page.locator(".filters a", has_text=re.compile(r"^부산")))
    q = s.query()
    assert q["region"] == "부산" and q["genres"] == "TANGO" and q["when"] == "upcoming"
    shown = _listed_matches_api(s, when="upcoming", genres="TANGO", region="부산")
    assert corpus.ids["festival_ongoing"] in shown
    assert corpus.ids["tango_d25"] not in shown
    assert s.page.locator('.filters a[aria-current="true"]').inner_text().startswith("부산")


@pytest.mark.parametrize("number, tab, when, present, absent", [
    ("06", "오늘", "today", ("tango_today", "salsa_overnight", "festival_ongoing"),
     ("swing_tomorrow",)),
    ("07", "내일", "tomorrow", ("swing_tomorrow", "festival_ongoing"),
     ("tango_today", "salsa_overnight")),
    ("10", "다가오는", "upcoming", ("tango_d25", "salsa_d12", "practica"), ()),
])
def test_e2e_06_07_10_date_tabs(s, corpus, number, tab, when, present, absent):
    s.go("/events?when=today")
    s.navigate_by(s.page.locator("main > nav a", has_text=tab))
    assert s.query()["when"] == when
    shown = _listed_matches_api(s, when=when)
    for key in present:
        assert corpus.ids[key] in shown, key
    for key in absent:
        assert corpus.ids[key] not in shown, key
    total = int(re.search(r"(\d+)건", s.page.locator("p.sub").first.inner_text()).group(1))
    assert total == len(s.api_ids(when=when))


@pytest.mark.parametrize("number, days, inside, outside", [
    ("08", 7, ("practica", "unknown_time"), ("salsa_d12", "tango_d25")),
    ("09", 14, ("salsa_d12",), ("tango_d25",)),
])
def test_e2e_08_09_d7_d14_ranges(s, corpus, number, days, inside, outside):
    """No D7/D14 control exists on the pages (오늘/내일/주말/이번 주/다가오는);
    the API's from/to is the supported way to ask, inclusive at both ends."""
    s.go("/")
    start, end = corpus.today, corpus.today + timedelta(days=days - 1)
    ids = s.api_ids(**{"from": start.isoformat(), "to": end.isoformat()})
    for key in inside:
        assert corpus.ids[key] in ids
    for key in outside:
        assert corpus.ids[key] not in ids
    assert corpus.ids["festival_ongoing"] in ids


def test_e2e_11_genre_region_date_combined(s, corpus):
    s.go("/events?when=today")
    _only_genre(s, "SALSA")
    s.navigate_by(s.page.locator(".filters a", has_text=re.compile(r"^부산")))
    s.navigate_by(s.page.locator("main > nav a", has_text="다가오는"))
    q = s.query()
    assert (q["when"], q["genres"], q["region"]) == ("upcoming", "SALSA", "부산")
    shown = _listed_matches_api(s, when="upcoming", genres="SALSA", region="부산")
    assert corpus.ids["salsa_overnight"] in shown
    assert corpus.ids["salsa_d12"] not in shown        # Seoul
    assert corpus.ids["festival_ongoing"] not in shown  # Tango
    assert "Salsa" in s.page.locator("p.sub").first.inner_text()


def test_e2e_12_13_open_detail_and_return(s, corpus):
    s.go("/events?when=upcoming")
    _only_genre(s, "TANGO")
    listing = s.page.url
    s.navigate_by(s.page.locator(f'a[href="/events/{corpus.ids["practica"]}"]').first)
    assert s.page.url.endswith(f"/events/{corpus.ids['practica']}")
    assert "PRACTICA / 프락티카" in s.page.locator("h1").inner_text()
    s.navigate_by(s.page.locator("a.back-link"))
    assert s.page.url == listing, "← 목록 dropped the reader's filters"
    s.go(f"/events/{corpus.ids['practica']}")
    s.page.go_back(wait_until="load")
    assert s.page.url == listing
    assert s.page.locator("form.genres input[value=TANGO]").is_checked()
    assert not s.page.locator("form.genres input[value=SALSA]").is_checked()


def test_e2e_14_source_link(s, corpus):
    s.go(f"/events/{corpus.ids['tango_today']}")
    link = s.page.locator('a[href*="/source?to="]').first
    href = link.get_attribute("href")
    assert unquote(href.split("to=", 1)[1]) == corpus.urls["tango_today"]
    assert link.get_attribute("target") == "_blank"
    assert "noopener" in link.get_attribute("rel")
    r = s.page.request.get(s.base + href, max_redirects=0)
    assert r.status == 303 and r.headers["location"] == corpus.urls["tango_today"]
    bad = s.page.request.get(f"{s.base}/events/{corpus.ids['tango_today']}/source?"
                             f"to=https%3A%2F%2Fevil.example%2F", max_redirects=0)
    assert bad.status == 400, "an open redirect"
    s.go("/events?when=today")
    card_source = s.page.locator(".tl-3 a.src-link").first
    assert card_source.get_attribute("rel") == "noopener noreferrer"


def test_e2e_15_ongoing_festival(s, corpus):
    s.go("/events?when=today")
    fid = corpus.ids["festival_ongoing"]
    assert fid in s.ids()
    row = s.page.locator(f'li.event:has(a[href="/events/{fid}"])')
    first, last = corpus.today - timedelta(days=1), corpus.today + timedelta(days=7)
    assert f"{last.month}/{last.day}" in row.inner_text()
    s.go(f"/events/{fid}")
    when = s.page.locator("dd").first.inner_text()
    assert f"{first.month}/{first.day}" in when and f"{last.month}/{last.day}" in when
    assert "시간 미확인" in when
    s.shot("mobile-event-detail")


def test_e2e_16_overnight_event(s, corpus):
    s.go(f"/events/{corpus.ids['salsa_overnight']}")
    when = s.page.locator("dd").first.inner_html()
    assert "21:00–01:00<sup>+1</sup>" in when
    day = corpus.today
    assert f"{day.month}/{day.day}" in s.page.locator("dd").first.inner_text()


def test_e2e_17_unknown_time(s, corpus):
    s.go(f"/events/{corpus.ids['unknown_time']}")
    when = s.page.locator("dd").first.inner_text()
    assert "시간 미확인" in when and "00:00" not in when


def test_e2e_18_unresolved_venue(s, corpus):
    s.go(f"/events/{corpus.ids['unresolved_venue']}")
    venue = s.page.locator("dt:has-text('장소') + dd").inner_text()
    assert "대전 땅고 오나다 (E2E 미등록)" in venue and "미확인" in venue
    assert "주소 미확인" in s.page.locator("dt:has-text('주소') + dd").inner_text()
    s.go(f"/events?when=upcoming&region=대전")
    row = s.page.locator(f'li.event:has(a[href="/events/{corpus.ids["unresolved_venue"]}"])')
    assert "[대전] 미확인" in row.locator(".tl-1").inner_text()
    assert "Tango O Nada" not in row.inner_text()


def test_e2e_19_empty_result(s, corpus):
    s.go("/events?" + urlencode({"when": "today", "genres": "SWING", "genres_set": "1",
                                 "region": "부산"}))
    assert s.page.locator("p.empty").inner_text() == "선택한 조건에 해당하는 행사가 없습니다."
    actions = s.page.locator("ul.empty-actions a")
    assert actions.count() >= 2
    s.navigate_by(actions.filter(has_text="지역 전체 보기"))
    q = s.query()
    assert "region" not in q and q["genres"] == "SWING"
    s.shot("mobile-empty-result")


def test_e2e_20_failure_and_retry(browser, corpus):
    """The database is unreachable: a sentence and a retry, never a blank page,
    an endless spinner, or a JS error. Then the network drops and comes back."""
    port, dead = _free_port(), _free_port()
    proc = _serve(port, db_port=dead)
    try:
        s = Session(browser, f"http://127.0.0.1:{port}")
        response = s.go("/events?when=today&region=부산")
        assert response.status == 503
        assert "행사 정보를 불러올 수 없습니다" in s.page.locator("p.empty").inner_text()
        retry = s.page.locator("ul.empty-actions a", has_text="다시 시도")
        s.navigate_by(retry)
        assert s.query() == {"when": "today", "region": "부산"}
        api = s.page.request.get(f"{s.base}/api/events?when=today")
        assert api.status == 503 and "detail" in api.json()
        # The browser logs the 503 it was sent; that is the case under test,
        # not a page fault. Any script error still fails.
        assert not [e for e in s.errors if "status of 503" not in e], s.errors
        s.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_e2e_20b_network_loss_then_recovery(s, corpus):
    s.go("/events?when=today")
    s.ctx.set_offline(True)
    with pytest.raises(sync_api.Error):
        s.page.goto(s.base + "/events?when=tomorrow", timeout=5000)
    s.ctx.set_offline(False)
    assert s.go("/events?when=tomorrow").status == 200
    assert corpus.ids["swing_tomorrow"] in s.ids()
    s.errors[:] = [e for e in s.errors if "ERR_INTERNET_DISCONNECTED" not in e]


def test_e2e_21_rapid_filter_changes_last_one_wins(s, corpus):
    """Seoul Tango asked first and answered last must not paint over Busan Salsa."""
    slow = {"n": 0}

    def delay_seoul(route):
        if "region=%EC%84%9C%EC%9A%B8" in route.request.url:
            slow["n"] += 1
            time.sleep(1.5)
        route.continue_()

    s.page.route("**/events?*", delay_seoul)
    s.go("/events?when=upcoming")
    seoul = "/events?" + urlencode({"when": "upcoming", "genres": "TANGO", "genres_set": "1",
                                    "region": "서울"})
    busan = "/events?" + urlencode({"when": "upcoming", "genres": "SALSA", "genres_set": "1",
                                    "region": "부산"})
    s.page.evaluate(f"location.href = {seoul!r}")
    s.page.wait_for_timeout(100)
    s.go(busan)
    s.page.wait_for_timeout(2000)
    q = s.query()
    assert (q["region"], q["genres"]) == ("부산", "SALSA")
    shown = s.ids()
    assert corpus.ids["salsa_overnight"] in shown
    assert corpus.ids["practica"] not in shown
    assert slow["n"] >= 1
    s.page.unroute("**/events?*")


def test_e2e_21b_a_double_tap_lands_once(s, corpus):
    s.go("/events?when=today")
    s.documents.clear()
    chip = s.page.locator(".filters a", has_text=re.compile(r"^부산"))
    with s.page.expect_navigation(wait_until="load"):
        chip.dblclick()
    assert s.query().get("region") == "부산"
    assert len(s.documents) <= 2


@pytest.mark.parametrize("number, viewport", [("22", "m360"), ("22", "m390"), ("22", "m430"),
                                              ("23", "t768"), ("24", "d1280"),
                                              ("24", "d1440")])
def test_e2e_22_24_viewports(browser, base, corpus, number, viewport):
    s = Session(browser, base, viewport)
    try:
        for path in ("/", "/events?when=upcoming", f"/events/{corpus.ids['long_title']}",
                     "/events?when=today&genres=SWING&genres_set=1&region=부산"):
            assert s.go(path).status == 200
            layout = s.layout()
            assert layout["sw"] <= layout["vw"], f"{viewport} {path}: horizontal scroll"
            for control in layout["controls"]:
                if control["scroller"]:
                    continue  # the directory tabs scroll inside their own row
                assert control["l"] >= -1 and control["r"] <= layout["vw"] + 1, \
                    f"{viewport} {path}: {control['t']} is off screen"
        s.go("/events?when=upcoming")
        _only_genre(s, "TANGO")
        assert s.query()["genres"] == "TANGO"
        if viewport in ("m390", "t768", "d1280"):
            s.shot({"m390": "mobile-search", "t768": "tablet-search",
                    "d1280": "desktop-search"}[viewport])
        assert not s.errors, s.errors
    finally:
        s.close()


def test_e2e_25_folded_duplicate_is_hidden(s, corpus):
    child, root = corpus.ids["folded_child"], corpus.ids["tango_today"]
    for path in ("/", "/events?when=today", "/events?when=upcoming"):
        s.go(path)
        assert child not in s.ids(), path
    assert child not in s.api_ids(when="upcoming")
    s.go(f"/events/{child}")
    assert s.page.locator("h1").inner_text() == f"E2E Tango Tonight {corpus.tag}"
    assert root in s.api_ids(when="today")


def test_e2e_keyboard_reaches_the_filters(s, corpus):
    s.go("/events?when=today")
    seen = []
    for _ in range(40):
        s.page.keyboard.press("Tab")
        seen.append(s.page.evaluate(
            "() => { const e = document.activeElement; return e.tagName + ':' +"
            " (e.value || e.textContent || '').trim().slice(0, 12); }"))
    assert any(x.startswith("INPUT:TANGO") for x in seen)
    assert any(x.startswith("A:부산") for x in seen)
    outline = s.page.evaluate("() => getComputedStyle(document.activeElement).outlineStyle")
    assert outline != "none" or s.page.evaluate(
        "() => getComputedStyle(document.activeElement).boxShadow") != "none"
