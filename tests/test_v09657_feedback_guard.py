"""v0.96.57 - the one public write is rate- and size-limited.

POST /events/{id}/feedback used to write a row for every request anyone sent.
These tests drive the real app (runtime.app) through its real middleware with
the database replaced by a recorder, so they run anywhere and can never write
a feedback row to any database: what is asserted is what the route *would*
have written. ``_Peer`` stands in for the TCP connection - the one thing a
client cannot forge - by setting the ASGI peer address the way uvicorn does.
"""

from __future__ import annotations

import ast
import asyncio
import threading
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from runtime import feedback_guard, public
from runtime.feedback_guard import Limiter, client_address, parse_trusted

REPO = Path(__file__).resolve().parents[1]
KNOWN = {101, 102, 103}


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _Peer:
    """Outermost ASGI shim: the test says which address the connection came
    from (x-test-peer), and the header is removed before the app sees it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = [(k, v) for k, v in scope["headers"] if k != b"x-test-peer"]
            peer = dict(scope["headers"]).get(b"x-test-peer")
            scope = dict(scope, headers=headers,
                         client=(peer.decode(), 40000) if peer else scope.get("client"))
        await self.app(scope, receive, send)


@pytest.fixture
def written(env, monkeypatch):
    """The rows the route would have written; no database is opened."""
    from runtime import app as app_module, events_api, feedback

    rows: list[tuple[int, str]] = []

    @contextmanager
    def connection():
        yield object()

    def record(_con, *, event_id, kind):
        rows.append((event_id, kind))
        return {}

    monkeypatch.setattr(public, "_connection", connection)
    monkeypatch.setattr(events_api, "get_event",
                        lambda _con, event_id: {"id": event_id} if event_id in KNOWN else None)
    monkeypatch.setattr(feedback, "record", record)
    monkeypatch.setattr(app_module, "_trusted_proxies", ())
    return rows


@pytest.fixture
def clock():
    clock = _Clock()
    feedback_guard.reset(Limiter(clock=clock))
    yield clock
    feedback_guard.reset()


@pytest.fixture
def client(written, clock):
    from runtime.app import app

    with TestClient(_Peer(app), follow_redirects=False) as c:
        yield c


def _post(client, event_id=101, kind="INCORRECT", peer="198.51.100.7", headers=None, **kw):
    h = {"x-test-peer": peer, **(headers or {})}
    return client.post(f"/events/{event_id}/feedback", data={"kind": kind}, headers=h, **kw)


def _trust(monkeypatch, value):
    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_trusted_proxies", parse_trusted(value))


# --- normal use ---------------------------------------------------------------

def test_a_reader_leaves_feedback_and_is_thanked(client, written):
    r = _post(client, kind="incorrect")
    assert r.status_code == 303
    assert r.headers["location"] == "/events/101?feedback=INCORRECT"
    assert written == [(101, "INCORRECT")]


def test_one_reader_can_rate_several_events(client, written):
    for event_id in (101, 102, 103):
        assert _post(client, event_id=event_id).status_code == 303
    assert written == [(101, "INCORRECT"), (102, "INCORRECT"), (103, "INCORRECT")]


def test_an_unknown_kind_is_still_400_and_writes_nothing(client, written):
    assert _post(client, kind="SPAM").status_code == 400
    assert written == []


def test_the_page_still_offers_the_three_buttons():
    html = public._feedback_block(101)
    assert html.count('action="/events/101/feedback"') == 3


# --- identical repetition -------------------------------------------------------

def test_the_same_note_twice_is_thanked_twice_and_written_once(client, written):
    assert _post(client).status_code == 303
    second = _post(client)
    assert second.status_code == 303
    assert second.headers["location"] == "/events/101?feedback=INCORRECT"
    assert written == [(101, "INCORRECT")]


def test_a_different_kind_or_event_is_a_new_note(client, written):
    _post(client)
    _post(client, kind="INCOMPLETE")
    _post(client, event_id=102)
    assert written == [(101, "INCORRECT"), (101, "INCOMPLETE"), (102, "INCORRECT")]


def test_the_same_note_after_ten_minutes_is_written_again(client, written, clock):
    _post(client)
    clock.now += feedback_guard.DUPLICATE_SECONDS + 1
    _post(client)
    assert written == [(101, "INCORRECT"), (101, "INCORRECT")]


def test_a_note_that_was_not_written_can_be_sent_again(client, written, monkeypatch):
    from runtime import db, feedback

    def down(_con, **_kw):
        raise db.DatabaseUnavailable("down")

    monkeypatch.setattr(feedback, "record", down)
    assert _post(client).status_code == 503
    monkeypatch.setattr(feedback, "record",
                        lambda _con, *, event_id, kind: written.append((event_id, kind)))
    assert _post(client).status_code == 303
    assert written == [(101, "INCORRECT")]


# --- rate limits ------------------------------------------------------------------

def test_the_eleventh_note_in_a_minute_is_429_with_retry_after(client, written):
    for n in range(feedback_guard.SHORT_WINDOW[0]):
        assert _post(client, event_id=101 + n % 3, kind=("INCORRECT", "INCOMPLETE",
                     "ACCURATE")[n // 3 % 3]).status_code == 303
    r = _post(client, event_id=102, kind="ACCURATE")
    assert r.status_code == 429
    retry = int(r.headers["retry-after"])
    assert 1 <= retry <= feedback_guard.SHORT_WINDOW[1]
    assert r.headers["content-type"].startswith("text/html")
    assert "잠시 후 다시 시도해 주세요" in r.text
    assert "198.51.100.7" not in r.text and "198.51.100.7" not in str(r.headers)
    assert len(written) <= feedback_guard.SHORT_WINDOW[0]


def test_waiting_out_the_retry_after_is_enough(client, clock):
    for _ in range(feedback_guard.SHORT_WINDOW[0]):
        _post(client, kind="ACCURATE")
    r = _post(client)
    assert r.status_code == 429
    clock.now += int(r.headers["retry-after"])
    assert _post(client, event_id=103).status_code == 303


def test_the_long_window_holds_past_the_short_one(client, clock):
    short_n, short_s = feedback_guard.SHORT_WINDOW
    long_n, _long_s = feedback_guard.LONG_WINDOW
    sent = 0
    while sent < long_n:
        for _ in range(short_n):
            assert _post(client, kind="ACCURATE").status_code == 303
            sent += 1
        clock.now += short_s
    r = _post(client)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > short_s


def test_the_global_window_caps_rotating_clients(client, clock):
    limit, _window = feedback_guard.GLOBAL_WINDOW
    for n in range(limit):
        assert _post(client, peer=f"203.0.113.{n % 250}",
                     kind=("ACCURATE", "INCORRECT")[n // 250]).status_code == 303
        if n % 100 == 99:
            clock.now += 61
    r = _post(client, peer="192.0.2.99")
    assert r.status_code == 429


def test_unknown_event_ids_count_toward_the_limit(client, written):
    for n in range(feedback_guard.SHORT_WINDOW[0]):
        assert _post(client, event_id=900000 + n).status_code == 404
    assert _post(client, event_id=101).status_code == 429
    assert written == []


def test_a_non_numeric_id_counts_toward_the_limit(client):
    for _ in range(feedback_guard.SHORT_WINDOW[0]):
        assert _post(client, event_id="abc").status_code == 422
    assert _post(client).status_code == 429


def test_other_routes_are_not_counted(client):
    for _ in range(feedback_guard.SHORT_WINDOW[0] * 2):
        client.get("/events/101/feedback", headers={"x-test-peer": "198.51.100.7"})
        client.post("/events/101", headers={"x-test-peer": "198.51.100.7"})
    assert _post(client).status_code == 303


# --- who the client is ------------------------------------------------------------------

@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP", "Forwarded"])
def test_a_forged_address_header_does_not_make_a_new_client(client, header):
    for n in range(feedback_guard.SHORT_WINDOW[0]):
        value = f"for=10.9.{n}.1" if header == "Forwarded" else f"10.9.{n}.1"
        assert _post(client, kind="ACCURATE", headers={header: value}).status_code == 303
    assert _post(client, headers={header: "10.9.99.1"}).status_code == 429


def test_different_connections_are_different_clients(client):
    for _ in range(feedback_guard.SHORT_WINDOW[0]):
        _post(client, kind="ACCURATE", peer="198.51.100.7")
    assert _post(client, peer="198.51.100.7").status_code == 429
    assert _post(client, peer="198.51.100.8").status_code == 303


def test_readers_sharing_one_nat_address_can_each_leave_notes(client, written):
    # Two readers at one studio, one address: different events or kinds are
    # all written; the same kind on the same event is written once.
    _post(client, event_id=101, kind="INCORRECT")
    _post(client, event_id=102, kind="ACCURATE")
    _post(client, event_id=101, kind="INCOMPLETE")
    _post(client, event_id=101, kind="INCORRECT")
    assert written == [(101, "INCORRECT"), (102, "ACCURATE"), (101, "INCOMPLETE")]


def test_a_trusted_proxy_names_the_reader_by_its_own_entry(client, monkeypatch):
    _trust(monkeypatch, "172.18.0.0/16")
    proxy = "172.18.0.2"
    for n in range(feedback_guard.SHORT_WINDOW[0]):
        # The reader rotates the part it wrote; the proxy's own entry is last.
        xff = f"10.0.{n}.1, 198.51.100.7"
        assert _post(client, peer=proxy, kind="ACCURATE",
                     headers={"X-Forwarded-For": xff}).status_code == 303
    assert _post(client, peer=proxy, headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.7"}
                 ).status_code == 429
    # Another reader through the same proxy is a different client.
    assert _post(client, peer=proxy, headers={"X-Forwarded-For": "198.51.100.8"}
                 ).status_code == 303


def test_an_untrusted_peer_cannot_borrow_the_proxy_rule(client, monkeypatch):
    _trust(monkeypatch, "172.18.0.0/16")
    for n in range(feedback_guard.SHORT_WINDOW[0]):
        assert _post(client, peer="192.168.1.50", kind="ACCURATE",
                     headers={"X-Forwarded-For": f"10.0.{n}.1"}).status_code == 303
    assert _post(client, peer="192.168.1.50",
                 headers={"X-Forwarded-For": "10.0.99.1"}).status_code == 429


def test_client_address_rules():
    trusted = parse_trusted("172.18.0.0/16")

    def scope(peer, *xff):
        return {"client": (peer, 1), "headers": [(b"x-forwarded-for", v.encode()) for v in xff]}

    assert client_address(scope("192.168.1.9", "6.6.6.6"), trusted) == "192.168.1.9"
    assert client_address(scope("172.18.0.2", "6.6.6.6, 5.5.5.5"), trusted) == "5.5.5.5"
    assert client_address(scope("172.18.0.2", "6.6.6.6", "5.5.5.5"), trusted) == "5.5.5.5"
    assert client_address(scope("172.18.0.2", "not-an-ip"), trusted) == "172.18.0.2"
    assert client_address(scope("172.18.0.2"), trusted) == "172.18.0.2"
    assert client_address(scope("172.18.0.2", "6.6.6.6"), ()) == "172.18.0.2"
    assert client_address({"headers": []}, trusted) == "unknown"


def test_trusted_proxies_must_be_addresses(monkeypatch, env):
    from runtime.config import load_settings, validate

    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    monkeypatch.setenv("DANCEMATE_TRUSTED_PROXIES", "172.18.0.0/16, 10.0.0.5")
    assert not any("TRUSTED" in p for p in validate(load_settings()))
    monkeypatch.setenv("DANCEMATE_TRUSTED_PROXIES", "caddy")
    assert any("DANCEMATE_TRUSTED_PROXIES" in p for p in validate(load_settings()))
    monkeypatch.delenv("DANCEMATE_TRUSTED_PROXIES")
    assert load_settings().trusted_proxies == ""


def test_uvicorn_does_not_rewrite_the_peer_from_headers():
    tree = ast.parse((REPO / "runtime" / "__main__.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "run"]
    assert calls, "uvicorn.run call not found"
    kwargs = {k.arg: k.value for k in calls[0].keywords}
    assert isinstance(kwargs.get("proxy_headers"), ast.Constant)
    assert kwargs["proxy_headers"].value is False


# --- body size --------------------------------------------------------------------------

def test_an_oversized_body_is_413_and_never_reaches_the_route(client, written):
    big = "kind=INCORRECT&pad=" + "x" * 4096
    r = client.post("/events/101/feedback", content=big,
                    headers={"x-test-peer": "198.51.100.7",
                             "content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413
    assert written == []


def test_an_oversized_chunked_body_is_413(client, written):
    def chunks():
        yield b"kind=INCORRECT&pad="
        for _ in range(8):
            yield b"x" * 512

    r = client.post("/events/101/feedback", content=chunks(),
                    headers={"x-test-peer": "198.51.100.7",
                             "content-type": "application/x-www-form-urlencoded"})
    assert "content-length" not in {k.lower() for k in r.request.headers}
    assert r.status_code == 413
    assert written == []


def test_a_lying_content_length_is_not_trusted(written, clock):
    from runtime.app import app

    sent = []

    async def run():
        body = [b"kind=INCORRECT&pad=" + b"x" * 600, b"y" * 600]
        messages = [{"type": "http.request", "body": c, "more_body": i < len(body) - 1}
                    for i, c in enumerate(body)]

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": "POST", "path": "/events/101/feedback",
                 "raw_path": b"/events/101/feedback", "query_string": b"",
                 "headers": [(b"content-length", b"20"),
                             (b"content-type", b"application/x-www-form-urlencoded")],
                 "client": ("198.51.100.7", 1), "server": ("t", 80), "scheme": "http",
                 "root_path": "", "http_version": "1.1", "asgi": {"version": "3.0"}}
        await app(scope, receive, send)

    asyncio.run(run())
    assert sent[0]["status"] == 413
    assert written == []


def test_a_small_body_is_handed_to_the_route_intact(client, written):
    r = client.post("/events/101/feedback", content=b"kind=ACCURATE",
                    headers={"x-test-peer": "198.51.100.7",
                             "content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 303
    assert written == [(101, "ACCURATE")]


# --- concurrency, bounded state, restart -------------------------------------------------

def test_a_parallel_burst_admits_exactly_the_limit():
    limiter = Limiter(clock=lambda: 5000.0)
    results = []
    start = threading.Barrier(50)

    def hit():
        start.wait()
        results.append(limiter.hit("one-client"))

    threads = [threading.Thread(target=hit) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(0) == feedback_guard.SHORT_WINDOW[0]


def test_a_parallel_http_burst_writes_no_more_than_the_limit(written, clock):
    from runtime.app import app

    async def burst():
        transport = httpx.ASGITransport(app=_Peer(app))
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await asyncio.gather(*[
                c.post(f"/events/{101 + n % 3}/feedback",
                       data={"kind": ("ACCURATE", "INCORRECT", "INCOMPLETE")[n % 3]},
                       headers={"x-test-peer": "198.51.100.7"})
                for n in range(40)])

    responses = asyncio.run(burst())
    codes = [r.status_code for r in responses]
    assert codes.count(429) == 40 - feedback_guard.SHORT_WINDOW[0]
    assert len(written) <= feedback_guard.SHORT_WINDOW[0]


def test_state_stays_bounded_under_many_clients():
    clock = _Clock()
    limiter = Limiter(clock=clock, max_clients=64)
    for n in range(1000):
        limiter.hit(limiter.key(f"10.{n // 250}.{n % 250}.1"))
        limiter.seen_recently(limiter.key(f"10.{n // 250}.{n % 250}.1"), n, "ACCURATE")
    size = limiter.size()
    assert size["clients"] <= 64 and size["recent"] <= 64
    assert size["global"] <= feedback_guard.GLOBAL_WINDOW[0]
    clock.now += feedback_guard.LONG_WINDOW[1] + 1
    limiter.hit("late")
    assert limiter.size()["clients"] == 1


def test_a_restart_starts_empty_and_keeps_nothing(client, written, tmp_path):
    for _ in range(feedback_guard.SHORT_WINDOW[0]):
        _post(client, kind="ACCURATE")
    assert _post(client).status_code == 429
    before = feedback_guard.LIMITER
    after = feedback_guard.reset()
    assert after is not before and after.size() == {"clients": 0, "global": 0, "recent": 0}
    assert after.key("198.51.100.7") != before.key("198.51.100.7")
    assert _post(client).status_code == 303


def test_the_client_key_is_not_the_address():
    limiter = Limiter()
    key = limiter.key("198.51.100.7")
    assert "198" not in key and len(key) == 24
    assert key == limiter.key("198.51.100.7") != limiter.key("198.51.100.8")


def test_the_guard_writes_nothing_to_disk_or_log():
    source = (REPO / "runtime" / "feedback_guard.py").read_text(encoding="utf-8")
    for word in ("open(", "logging", "getLogger", "print(", "INSERT", "connect("):
        assert word not in source
