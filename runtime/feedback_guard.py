"""Abuse protection for the one public write (v0.96.57).

``POST /events/{id}/feedback`` is the only thing an anonymous reader can make
the runtime write, and until now it would write as fast as anyone could send:
no rate limit, no body limit, every request a row. This module sits in front
of it, as plain ASGI middleware, and does three things before the route sees
a byte of the body:

* counts the attempt against a per-client short and long window and a
  global window, and answers 429 with ``Retry-After`` when any is full;
* refuses a body over ``MAX_BODY_BYTES`` with 413, by its declared length or
  - for a chunked body - by reading no further than one byte past it;
* hands the route a client key so it can drop the same reader's identical
  feedback on the same event within ``DUPLICATE_SECONDS`` (``seen_recently``).

Why in memory. The runtime is one uvicorn process with no workers (see
``__main__``), so one process-wide limiter is the whole picture; a database
table would add a write per request to protect against too many writes, and
the reverse proxy's stock build has no rate limiter at all. A restart empties
the windows - a restart is an operator's act, not something a client can
cause, and the global window bounds the worst case either way.

Who is the client. The TCP peer, and nothing a client wrote. uvicorn's own
proxy-header rewriting is turned off (``__main__``) so that the peer stays the
peer; only when the peer is a reverse proxy the operator named in
DANCEMATE_TRUSTED_PROXIES is the right-most X-Forwarded-For entry used - the
one that proxy itself appended. X-Real-IP and Forwarded are never read.

What is kept. Not the address: an HMAC of it under a key drawn at process
start and never stored, so the windows cannot be read back into addresses
and are gone at the next restart. Nothing here is logged or written to disk.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from typing import Any, Callable, Iterable

# The policy. One reader leaves one note on a page; ten in a minute or a
# hundred and twenty in an hour is a script, or a whole studio on one Wi-Fi
# having a very thorough evening - generous on purpose, since readers behind
# one NAT share a key. The global window is the backstop for a client that
# rotates addresses: it caps what the table can grow by in an hour.
SHORT_WINDOW = (10, 60)          # requests, seconds - per client
LONG_WINDOW = (120, 3600)        # per client
GLOBAL_WINDOW = (300, 3600)      # every client together
DUPLICATE_SECONDS = 600          # same client, event and kind: not a new row
MAX_BODY_BYTES = 1024            # the form is "kind=INCOMPLETE": 15 bytes
MAX_CLIENTS = 4096               # bounded state: least-recently-seen goes first

# Any POST shaped like the route, including a non-numeric id - the route
# answers those itself (422), but each one still counts as an attempt.
PATH = re.compile(r"^/events/[^/]+/feedback/?$")

TOO_MANY = "의견 전송이 잠시 너무 많습니다. 잠시 후 다시 시도해 주세요."
TOO_LARGE = "요청이 너무 큽니다."


def parse_trusted(raw: str | Iterable[str] | None) -> tuple:
    """DANCEMATE_TRUSTED_PROXIES ("172.18.0.0/16, 10.0.0.5") as networks.
    Raises ValueError on an entry that is not an address or network."""
    if raw is None:
        return ()
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    return tuple(ipaddress.ip_network(item.strip(), strict=False)
                 for item in items if item and item.strip())


def _ip(text: str | None):
    try:
        return ipaddress.ip_address((text or "").strip())
    except ValueError:
        return None


def client_address(scope: dict[str, Any], trusted: tuple) -> str:
    """The address a limit is charged to (see the module docstring)."""
    client = scope.get("client")
    peer = str(client[0]) if client else ""
    peer_ip = _ip(peer)
    if peer_ip is None or not any(peer_ip in net for net in trusted):
        return peer or "unknown"
    values = [value.decode("latin-1") for name, value in scope.get("headers") or ()
              if name.lower() == b"x-forwarded-for"]
    hops = [hop.strip() for hop in ",".join(values).split(",") if hop.strip()]
    nearest = _ip(hops[-1]) if hops else None
    # A trusted proxy that sent no usable address leaves the proxy itself as
    # the client: every reader behind it shares one key. Safe, if strict.
    return str(nearest) if nearest is not None else peer


class Limiter:
    """Sliding-window counts behind one lock. Check-and-record is a single
    step, so a burst of parallel requests cannot all read "not full yet"."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 short: tuple[int, int] = SHORT_WINDOW,
                 long: tuple[int, int] = LONG_WINDOW,
                 global_: tuple[int, int] = GLOBAL_WINDOW,
                 duplicate_seconds: int = DUPLICATE_SECONDS,
                 max_clients: int = MAX_CLIENTS) -> None:
        self._clock = clock
        self._short, self._long, self._global = short, long, global_
        self._duplicate_seconds = duplicate_seconds
        self._max_clients = max_clients
        self._lock = threading.Lock()
        self._key = secrets.token_bytes(32)        # never stored, never logged
        self._clients: OrderedDict[str, deque[float]] = OrderedDict()
        self._all: deque[float] = deque()
        self._recent: OrderedDict[tuple[str, int, str], float] = OrderedDict()

    def key(self, address: str) -> str:
        return hmac.new(self._key, address.encode(), hashlib.sha256).hexdigest()[:24]

    @staticmethod
    def _wait(stamps: deque[float], limit: int, window: int, now: float) -> float:
        """Seconds until ``stamps`` has room, 0 when it has room now. Reads
        only: the short and long windows look at one shared list, so neither
        may drop what the other still counts."""
        if len(stamps) < limit:
            return 0.0
        edge = stamps[-limit]          # the limit-th most recent attempt
        return max(0.0, edge + window - now)

    def hit(self, client_key: str) -> int:
        """Record one attempt. 0 when admitted, else whole seconds to wait
        (a refused attempt is not recorded - waiting it out works)."""
        with self._lock:
            now = self._clock()
            stamps = self._clients.get(client_key)
            if stamps is None:
                stamps = deque()
            wait = max(
                self._wait(stamps, *self._short, now),
                self._wait(stamps, *self._long, now),
                self._wait(self._all, *self._global, now),
            )
            if wait > 0:
                return max(1, math.ceil(wait))
            stamps.append(now)
            # The long window is the deepest any count looks back.
            while len(stamps) > self._long[0]:
                stamps.popleft()
            self._clients[client_key] = stamps
            self._clients.move_to_end(client_key)
            self._all.append(now)
            while len(self._all) > self._global[0]:
                self._all.popleft()
            self._evict(now)
            return 0

    def seen_recently(self, client_key: str, event_id: int, kind: str) -> bool:
        """True when this client sent this kind for this event within
        DUPLICATE_SECONDS; otherwise remembers it and returns False."""
        marker = (client_key, event_id, kind)
        with self._lock:
            now = self._clock()
            until = self._recent.get(marker)
            if until is not None and until > now:
                return True
            self._recent[marker] = now + self._duplicate_seconds
            self._recent.move_to_end(marker)
            self._evict(now)
            return False

    def forget(self, client_key: str, event_id: int, kind: str) -> None:
        """Undo ``seen_recently`` for a row that was never written."""
        with self._lock:
            self._recent.pop((client_key, event_id, kind), None)

    def _evict(self, now: float) -> None:
        horizon = now - self._long[1]
        while self._clients:
            _, stamps = next(iter(self._clients.items()))
            if len(self._clients) > self._max_clients or not stamps or stamps[-1] <= horizon:
                self._clients.popitem(last=False)
            else:
                break
        while self._recent:
            marker, until = next(iter(self._recent.items()))
            if len(self._recent) > self._max_clients or until <= now:
                self._recent.popitem(last=False)
            else:
                break

    def size(self) -> dict[str, int]:
        with self._lock:
            return {"clients": len(self._clients), "global": len(self._all),
                    "recent": len(self._recent)}


LIMITER = Limiter()


def reset(limiter: Limiter | None = None) -> Limiter:
    """A fresh process-wide limiter - what a restart does (and what tests use)."""
    global LIMITER
    LIMITER = limiter or Limiter()
    return LIMITER


def _page(status: int, message: str, headers: list[tuple[bytes, bytes]]) -> dict:
    body = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>DanceMate</title></head><body><p>{message}</p>"
        '<p><a href="/events">행사 목록으로</a></p></body></html>'
    ).encode()
    return {
        "body": body,
        "status": status,
        "headers": [
            (b"content-type", b"text/html; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
            *headers,
        ],
    }


async def _send_page(send, page: dict) -> None:
    await send({"type": "http.response.start", "status": page["status"],
                "headers": page["headers"]})
    await send({"type": "http.response.body", "body": page["body"]})


class FeedbackGuard:
    """ASGI middleware; every other request passes straight through."""

    def __init__(self, app, trusted: Callable[[], tuple] = lambda: ()) -> None:
        self.app = app
        self.trusted = trusted

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or not PATH.match(scope.get("path") or "")):
            await self.app(scope, receive, send)
            return

        limiter = LIMITER
        client_key = limiter.key(client_address(scope, self.trusted()))
        wait = limiter.hit(client_key)
        if wait:
            await _send_page(send, _page(429, TOO_MANY,
                                         [(b"retry-after", str(wait).encode())]))
            return

        declared = None
        for name, value in scope.get("headers") or ():
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = MAX_BODY_BYTES + 1
        if declared is not None and declared > MAX_BODY_BYTES:
            await _send_page(send, _page(413, TOO_LARGE, []))
            return

        # Read the body here, never past the limit, and hand the route a
        # replay of it - so the route's own form parser can't be made to.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                await _send_page(send, _page(413, TOO_LARGE, []))
                return
            chunks.append(chunk)
            if not message.get("more_body"):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        scope.setdefault("state", {})["feedback_client"] = client_key
        await self.app(scope, replay, send)
