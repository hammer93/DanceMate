"""v0.96.57 browser E2E: a reader's feedback still works, a flood does not.

One event on the suite's disposable PostgreSQL (removed afterwards, its
feedback rows with it - event_feedback cascades). A real browser taps a
feedback button, is thanked, and one row is written; tapping the same button
again thanks again and writes nothing more. Then the same browser context
sends a burst straight at the route and is told to wait (429, Retry-After),
and an oversized body is refused (413). Browser emulation, not a phone.
"""

from __future__ import annotations

import time

import pytest

sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed - browser E2E NOT RUN (requirements-e2e.txt)")

from conftest import _REAL_POSTGRES  # noqa: E402
from test_public_journeys import Corpus, Session, _connect, _free_port, _serve  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    if not _REAL_POSTGRES.get("POSTGRES_PASSWORD"):
        pytest.skip("no disposable PostgreSQL configured (TEST_POSTGRES_*) - browser E2E NOT RUN")
    con = _connect()
    c = Corpus(con, f"f{int(time.time()) % 1000000}")
    c.add("rated", days=2, genre="TANGO", region="KR-SEOUL", name=f"E2E Feedback {c.tag}")
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


def _rows(corpus):
    with corpus.con.cursor() as cur:
        cur.execute("SELECT kind FROM event_feedback WHERE event_id = %s ORDER BY feedback_id",
                    (corpus.ids["rated"],))
        return [r[0] for r in cur.fetchall()]


def test_e2e_38_feedback_is_thanked_and_written_once(browser, base, corpus):
    s = Session(browser, base)
    try:
        event = corpus.ids["rated"]
        for _ in range(2):
            s.go(f"/events/{event}")
            s.navigate_by(s.page.locator("button.fb-btn", has_text="정보가 달라요"))
            assert f"/events/{event}?feedback=INCORRECT" in s.page.url
            assert "의견을 남겨주셔서 감사합니다" in s.page.locator(".banner").inner_text()
        assert _rows(corpus) == ["INCORRECT"]
        assert not s.errors
    finally:
        s.close()


def test_e2e_39_a_burst_is_told_to_wait_and_a_large_body_is_refused(browser, base, corpus):
    s = Session(browser, base)
    try:
        url = f"{base}/events/{corpus.ids['rated']}/feedback"
        statuses = [s.page.request.post(url, form={"kind": "ACCURATE"}, max_redirects=0).status
                    for _ in range(12)]
        assert 429 in statuses
        refused = s.page.request.post(url, form={"kind": "ACCURATE"}, max_redirects=0)
        assert refused.status == 429
        assert int(refused.headers["retry-after"]) >= 1
        assert "잠시 후 다시 시도해 주세요" in refused.text()
        assert _rows(corpus).count("ACCURATE") == 1
    finally:
        s.close()


def test_e2e_40_an_oversized_body_is_refused(browser, base, corpus):
    # A fresh server: the previous test used up this client's window.
    port = _free_port()
    proc = _serve(port)
    try:
        s = Session(browser, f"http://127.0.0.1:{port}")
        try:
            r = s.page.request.post(
                f"http://127.0.0.1:{port}/events/{corpus.ids['rated']}/feedback",
                form={"kind": "INCOMPLETE", "pad": "x" * 4096}, max_redirects=0)
            assert r.status == 413
            assert "INCOMPLETE" not in _rows(corpus)
        finally:
            s.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
