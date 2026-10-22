"""v0.96.50 browser E2E: what a dancer sees once a deadline is not an event date.

The rows here are not hand-written values: each is what the engine itself reads
out of a real stored post (tests/../engine/tests/fixture_v09650_date_time_roles.py
- 네오스윙's ticket notice, 스윙타임빠's weekly notice, 아임살사's 정모), with
the post's dates moved to days relative to the server's own "today" so the
journeys never age. The engine is called through the runtime's own loader
(`engine_ingest._engine`), the rows are committed to the suite's disposable
PostgreSQL for the server to read, and removed afterwards.

An operator's correction of an already-stored wrong row (Review EDIT /
REJECT) is a person's decision and is not taken here on Production. Its
outcome is reproduced on the disposable DB the way normalization writes it -
a REJECTED candidate's Event leaves the listing, an EDITED one carries the
corrected date - and the pages are checked against that.
"""

from __future__ import annotations

import importlib.util
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote

import pytest

sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed - browser E2E NOT RUN (requirements-e2e.txt)")

from conftest import _REAL_POSTGRES  # noqa: E402
from test_public_journeys import (  # noqa: E402  (same suite, same helpers)
    Corpus, Session, _connect, _free_port, _only_genre, _serve)

REPO = Path(__file__).resolve().parents[2]


def _engine_fixture():
    # By path: the engine's tests/ and this suite's tests/ share a name.
    spec = importlib.util.spec_from_file_location(
        "fixture_v09650_date_time_roles",
        REPO / "engine" / "tests" / "fixture_v09650_date_time_roles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FIXTURE = _engine_fixture()
REAL_IMSALSA = _FIXTURE.REAL_IMSALSA
REAL_NEOSWING_TICKETS = _FIXTURE.REAL_NEOSWING_TICKETS
REAL_TIMEBAR = _FIXTURE.REAL_TIMEBAR


def _md(day, korean=False):
    return f"{day.month}월 {day.day}일" if korean else f"{day.month}/{day.day}"


def _engine_events(title, body, published=None, **extra):
    from runtime import config, engine_ingest

    _db, _record, process, _single, _needs = engine_ingest._engine(config.load_settings())

    class Post:
        acquisition_quality = "FULL"

        def __init__(self):
            self.title, self.body, self.published_at = title, body, published
            for key, value in extra.items():
                setattr(self, key, value)

    return process(None, Post())["events"]


@pytest.fixture(scope="module")
def corpus():
    if not _REAL_POSTGRES.get("POSTGRES_PASSWORD"):
        pytest.skip("no disposable PostgreSQL configured (TEST_POSTGRES_*) - browser E2E NOT RUN")
    con = _connect()
    c = Corpus(con, f"c{int(time.time()) % 1000000}")
    c.deadline = c.today            # the pre-sale closes today ...
    c.party = c.today + timedelta(days=2)   # ... for a party the day after tomorrow
    published = (c.today - timedelta(days=10)).isoformat()
    title, body = REAL_NEOSWING_TICKETS
    body = (body.replace("10월 25일", _md(c.party, True)).replace("10/25", _md(c.party))
                .replace("10월 22일", _md(c.deadline, True)).replace("10/19", _md(c.today)))
    (party,) = _engine_events(title, body, published)
    assert party.date == c.party.isoformat(), "the engine dated the notice on its deadline"
    c.add("party", days=2, genre="SWING", kind="SOCIAL", region="KR-SEOUL",
          name=f"{party.name} {c.tag}", start=party.start_time, end=party.end_time)
    # What Production stores today for the same notice: a second row on the
    # deadline (1629136), waiting on a person's decision.
    c.add("stored_wrong_reject", days=0, genre="SWING", kind="SOCIAL", region="KR-SEOUL",
          name=f"{title} {_md(c.deadline)} REJECT {c.tag}", start=None, end=None)
    c.add("stored_wrong_edit", days=0, genre="SWING", kind="SOCIAL", region="KR-SEOUL",
          name=f"{title} EDIT {c.tag}", start=None, end=None)

    night = c.today + timedelta(days=1)
    title, body = REAL_TIMEBAR
    body = body.replace("10월 24,25일", f"{night.month}월 {night.day},{night.day}일")
    (social,) = _engine_events(title.replace("10월 24,25일", f"{night.month}월 {night.day}일"),
                               body, (c.today - timedelta(days=1)).isoformat())
    assert (social.start_time, social.end_time) == ("19:30", None)
    c.add("timebar", days=1, genre="SWING", kind="SOCIAL", region="KR-SEOUL",
          name=f"스윙타임빠 소셜 {c.tag}", start=social.start_time, end=social.end_time)

    title, body = REAL_IMSALSA
    body = body.replace("2026-10-23", (c.today + timedelta(days=3)).isoformat())
    (jeongmo,) = _engine_events(title, body, None, source_category="EVENT")
    assert jeongmo.start_time is None
    c.add("imsalsa", days=3, genre="SALSA", kind="SOCIAL_WITH_CLASS", region="KR-SEOUL",
          name=f"아임살사 정모 {c.tag}", start=None, end=None)
    yield c
    c.remove()
    con.close()


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


@pytest.fixture
def s(browser, base):
    session = Session(browser, base)
    yield session
    errors = list(session.errors)
    session.close()
    assert not errors, f"public JS errors: {errors}"


def _decide(corpus, key, *, reject=False, date=None):
    """A person's Review outcome as normalization writes it (disposable DB only)."""
    with corpus.con.cursor() as cur:
        if reject:
            cur.execute("UPDATE events SET review_state='REJECTED', listing_state='HIDDEN' "
                        "WHERE event_id=%s", (corpus.ids[key],))
        else:
            cur.execute("UPDATE events SET review_state='EDITED', event_date=%s, "
                        "field_origin='{\"event_date\": \"HUMAN\"}'::jsonb WHERE event_id=%s",
                        (date, corpus.ids[key]))


# --- E2E-26 .. E2E-32 -----------------------------------------------------------------

def test_e2e_26_the_party_is_on_its_own_date_not_the_deadline(s, corpus):
    s.go(f"/events?date={corpus.party.isoformat()}")
    assert corpus.ids["party"] in s.ids()
    s.go(f"/events?date={corpus.deadline.isoformat()}")
    assert corpus.ids["party"] not in s.ids()


def test_e2e_27_detail_after_a_persons_correction(s, corpus):
    """REJECT takes the deadline row out of every list and its link stops
    answering; EDIT moves a row to the corrected day and its page says so."""
    _decide(corpus, "stored_wrong_reject", reject=True)
    _decide(corpus, "stored_wrong_edit", date=corpus.party)
    s.go(f"/events?date={corpus.deadline.isoformat()}")
    assert corpus.ids["stored_wrong_reject"] not in s.ids()
    assert corpus.ids["stored_wrong_edit"] not in s.ids()
    # A request, not a navigation: the browser logs every 404 page it opens.
    gone = s.page.request.get(f"{s.base}/events/{corpus.ids['stored_wrong_reject']}")
    assert gone.status == 404
    s.go(f"/events/{corpus.ids['stored_wrong_edit']}")
    assert _md(corpus.party) in s.page.locator("dd").first.inner_text()
    s.go(f"/events?date={corpus.party.isoformat()}")
    assert corpus.ids["stored_wrong_edit"] in s.ids()


def test_e2e_28_no_deadline_date_in_upcoming_results(s, corpus):
    s.go("/events?when=upcoming")
    _only_genre(s, "SWING")
    row = s.page.locator(f'li.event:has(a[href="/events/{corpus.ids["party"]}"])')
    assert row.count() == 1
    ids = s.api_ids(when="upcoming", genre="SWING")
    assert corpus.ids["stored_wrong_reject"] not in ids


def test_e2e_29_a_djs_set_is_not_shown_as_the_start(s, corpus):
    s.go(f"/events/{corpus.ids['timebar']}")
    when = s.page.locator("dd").first.inner_text()
    assert "19:30" in when
    assert "20:15" not in when and "22:15" not in when


def test_e2e_30_unknown_time_says_so(s, corpus):
    s.go(f"/events/{corpus.ids['imsalsa']}")
    when = s.page.locator("dd").first.inner_text()
    assert "시간 미확인" in when and "20:00" not in when and "21:00" not in when


def test_e2e_31_mobile_search_after_the_fix(browser, base, corpus):
    m = Session(browser, base, "m360")
    try:
        m.go(f"/events?date={corpus.party.isoformat()}")
        _only_genre(m, "SWING")
        assert corpus.ids["party"] in m.ids()
        layout = m.layout()
        assert layout["sw"] <= layout["vw"], "horizontal scroll at 360px"
        assert not m.errors
    finally:
        m.close()


def test_e2e_32_source_link_of_the_corrected_event(s, corpus):
    s.go(f"/events/{corpus.ids['party']}")
    href = s.page.locator('a[href*="/source?to="]').first.get_attribute("href")
    assert unquote(href.split("to=", 1)[1]) == corpus.urls["party"]
    r = s.page.request.get(s.base + href, max_redirects=0)
    assert r.status == 303 and r.headers["location"] == corpus.urls["party"]
