"""v0.96.56 browser E2E: what a dancer sees once a clock's role is read.

As in test_v09650_corrected_data.py, the timed rows are what the engine itself
reads out of real stored posts (engine/tests/fixture_v09656_time_roles.py -
스위티스윙's DDP notice, PHU QUOC's listing, a Sunday practica), with the
post's date moved relative to the server's own "today". The one hand-set value
is a row's ``time_evidence``, written the way normalization writes it for a
bare clock (ABSENT), so the page's handling of an unplaced hour is seen in a
real browser. Rows live on the suite's disposable PostgreSQL and are removed
afterwards; viewports are browser emulation, not a physical phone.
"""

from __future__ import annotations

import importlib.util
import time
from datetime import timedelta
from pathlib import Path

import pytest

sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed - browser E2E NOT RUN (requirements-e2e.txt)")

from conftest import _REAL_POSTGRES  # noqa: E402
from test_public_journeys import (  # noqa: E402  (same suite, same helpers)
    Corpus, Session, _connect, _free_port, _serve)

REPO = Path(__file__).resolve().parents[2]


def _engine_fixture():
    spec = importlib.util.spec_from_file_location(
        "fixture_v09656_time_roles", REPO / "engine" / "tests" / "fixture_v09656_time_roles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FIXTURE = _engine_fixture()


def _engine_events(title, body, published=None):
    from runtime import config, engine_ingest

    _db, _record, process, _single, _needs = engine_ingest._engine(config.load_settings())

    class Post:
        acquisition_quality = "FULL"

        def __init__(self):
            self.title, self.body, self.published_at = title, body, published

    return process(None, Post())["events"]


def _evidence(corpus, key, value):
    with corpus.con.cursor() as cur:
        cur.execute("UPDATE events SET time_evidence=%s WHERE event_id=%s", (value, corpus.ids[key]))


@pytest.fixture(scope="module")
def corpus():
    if not _REAL_POSTGRES.get("POSTGRES_PASSWORD"):
        pytest.skip("no disposable PostgreSQL configured (TEST_POSTGRES_*) - browser E2E NOT RUN")
    con = _connect()
    c = Corpus(con, f"t{int(time.time()) % 1000000}")
    day = c.today + timedelta(days=2)

    title, body = _FIXTURE.REAL_DDP_SWING
    stamp = f"{day.year}.{day.month}.{day.day}"
    body = body.replace("2026.11.4", stamp)
    (ddp,) = _engine_events(title.replace("11/4", f"{day.month}/{day.day}"), body,
                            (c.today - timedelta(days=10)).isoformat())
    assert (ddp.date, ddp.start_time, ddp.end_time) == (day.isoformat(), "19:00", "22:00")
    c.add("ddp", days=2, genre="SWING", kind="SOCIAL", region="KR-SEOUL",
          name=f"스윙팍 동대문 DDP {c.tag}", start=ddp.start_time, end=ddp.end_time)
    _evidence(c, "ddp", "EXPLICIT")

    title, body = _FIXTURE.REAL_PHU_QUOC
    (phu, *_rest) = [e for e in _engine_events(title, body.replace("2026-10-29", day.isoformat()))
                     if e.date] or [None]
    assert phu is None or phu.start_time is None
    c.add("phu_quoc", days=2, genre="SALSA", kind="SOCIAL_WITH_CLASS",
          name=f"PHU QUOC SUMMER LATIN FESTIVAL {c.tag}", start=None, end=None)

    title, body = _FIXTURE.REAL_SUNDAY_PRACTICA
    (practica,) = _engine_events(title, body.replace(
        "2026년 11월 1일", f"{day.year}년 {day.month}월 {day.day}일"))
    assert (practica.start_time, practica.end_time) == ("11:00", "13:00")
    c.add("practica_am", days=2, genre="TANGO", kind="PRACTICA", region="KR-SEOUL",
          name=f"SUNDAY PRACTICA {c.tag}", start=practica.start_time, end=practica.end_time)
    _evidence(c, "practica_am", "UNAMBIGUOUS")

    # "소셜 9시 30분부터" (item 6853): the hour as written, its half of the day unstated.
    c.add("bare_clock", days=2, genre="SALSA", kind="SOCIAL", region="KR-SEOUL",
          name=f"라틴 할로윈 코스튬 페스티벌 {c.tag}", start="09:30", end=None)
    _evidence(c, "bare_clock", "ABSENT")
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


def _when(s, corpus, key):
    s.go(f"/events/{corpus.ids[key]}")
    return s.page.locator("dd").first.inner_text()


def _row(s, corpus, key):
    day = corpus.today + timedelta(days=2)
    s.go(f"/events?date={day.isoformat()}")
    row = s.page.locator(f'li.event:has(a[href="/events/{corpus.ids[key]}"])')
    assert row.count() == 1
    return row.inner_text()


# --- E2E-33 .. E2E-37 -----------------------------------------------------------------

def test_e2e_33_the_swing_social_is_shown_at_its_own_hours(s, corpus):
    when = _when(s, corpus, "ddp")
    assert "19:00" in when and "22:00" in when
    assert "08:00" not in when and "08:40" not in when and "미표기" not in when
    assert "19:00~22:00" in _row(s, corpus, "ddp")


def test_e2e_34_an_unplaced_clock_is_never_shown_as_a_morning(s, corpus):
    when = _when(s, corpus, "bare_clock")
    assert "9:30" in when and "09:30" not in when and "오전·오후 미표기" in when
    assert "시간 미확인" not in when
    row = _row(s, corpus, "bare_clock")
    assert "9:30" in row and "09:30" not in row and "오전·오후 미표기" in row


def test_e2e_35_an_end_alone_gives_no_start(s, corpus):
    when = _when(s, corpus, "phu_quoc")
    assert "시간 미확인" in when and "05:00" not in when


def test_e2e_36_a_real_morning_practica_is_shown_plainly(s, corpus):
    when = _when(s, corpus, "practica_am")
    assert "11:00" in when and "13:00" in when and "미표기" not in when


def test_e2e_37_the_flag_fits_a_360px_phone(browser, base, corpus):
    m = Session(browser, base, "m360")
    try:
        _row(m, corpus, "bare_clock")
        layout = m.layout()
        assert layout["sw"] <= layout["vw"], "horizontal scroll at 360px"
        assert not m.errors
    finally:
        m.close()
