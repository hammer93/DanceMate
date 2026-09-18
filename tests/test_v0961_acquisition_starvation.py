"""v0.96.1: terminal acquisition rows must not starve the queue.

Production, 2026-09-16 onward: five ROBOTS_DISALLOWED rows with
next_attempt_at = NULL sat at the head of every content-acquisition tick
(budget 5), 541 attempts each, while 936 FETCH_PENDING rows never got a
turn. The queue read "no retry time" as "due now, first in line".

Everything here runs on the rolled-back ``pg`` fixture with synthetic
sources whose URLs end in ``.invalid``; the fetcher is a fake that counts
calls; no network, no Production row. The tick simulation runs the same
select -> fetch -> record_outcome loop scheduler.acquisition_job.run()
runs, on this connection, so the rows stay invisible to any other test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime import acquisition, content_store, source_ops, sources

TERMINAL_ATTEMPTS = 541


# --- fixtures -----------------------------------------------------------------

def _source(pg, unique, key="SRC-Q", platform="WEB", role="COMMUNITY"):
    return sources.create_source(
        pg, source_key=f"{key}-{unique}", name=f"{key} {unique}", platform=platform,
        source_role=role, url=f"https://{key.lower()}.invalid/{unique}", enabled=False,
    )["source_id"]


def _items(pg, source_id, unique, count, prefix="p"):
    ids = []
    with pg.cursor() as cur:
        for n in range(count):
            cur.execute(
                "INSERT INTO source_items (source_id, external_id, url, title, content_hash) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING source_item_id",
                (source_id, f"{prefix}-{unique}-{n}", f"https://{prefix}.invalid/{unique}/{n}",
                 f"{prefix} {n}", f"hash-{prefix}-{unique}-{n}"))
            ids.append(cur.fetchone()[0])
    return ids


def _pending(pg, ids):
    """The real lifecycle of a new item: a content row, then queued by intake."""
    for item in ids:
        content_store.ensure_row(pg, item)
    assert content_store.mark_pending(pg, ids) == len(ids)
    return ids


def _new_never_asked(pg, ids):
    """FETCH_PENDING with next_attempt_at NULL and no attempt - the plain
    'never asked' shape (older rows queued before mark_pending stamped now())."""
    _pending(pg, ids)
    with pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET next_attempt_at = NULL WHERE source_item_id = ANY(%s)", (ids,))
    return ids


def _terminal_robots(pg, ids, attempts=TERMINAL_ATTEMPTS):
    """Exactly the Production shape: FETCH_BLOCKED / ROBOTS_DISALLOWED, no
    retry time, hundreds of attempts - written through the real
    record_outcome() path and then aged to the observed attempt count."""
    for item in ids:
        content_store.ensure_row(pg, item)
        stored = content_store.record_outcome(pg, item, acquisition.AcquisitionOutcome(
            status=acquisition.FETCH_BLOCKED, error_code="ROBOTS_DISALLOWED",
            error="robots.txt disallows", fetched_url=f"https://x.invalid/{item}"))
        assert stored["next_attempt_at"] is None
    with pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET attempt_count = %s WHERE source_item_id = ANY(%s)",
                    (attempts, ids))
    return ids


def _retry(pg, ids, *, due):
    """A blocked page with a scheduled retry: due (in the past) or not yet."""
    for item in ids:
        content_store.ensure_row(pg, item)
        content_store.record_outcome(pg, item, acquisition.AcquisitionOutcome(
            status=acquisition.FETCH_BLOCKED, error_code="BODY_UNAVAILABLE",
            fetched_url=f"https://x.invalid/{item}"))
    when = "now() - interval '1 minute'" if due else "now() + interval '1 day'"
    with pg.cursor() as cur:
        cur.execute(f"UPDATE source_item_content SET next_attempt_at = {when} WHERE source_item_id = ANY(%s)", (ids,))
    return ids


def _attempts(pg, ids):
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id, attempt_count FROM source_item_content WHERE source_item_id = ANY(%s)", (ids,))
        return dict(cur.fetchall())


def _due(pg, mine, limit):
    """due_for_acquisition() restricted to this test's own rows: the shared
    dev database has its own queue, and only a fresh database is empty."""
    return [row["source_item_id"] for row in content_store.due_for_acquisition(pg, limit=limit + len(mine) * 0)
            if row["source_item_id"] in mine][:limit]


def _due_exact(pg, mine, limit):
    """The LIMIT applied by the SQL itself, on a queue that is exactly this
    test's rows. Other rows in a shared database would take slots first, so
    this variant asserts through the full-queue window only when it can."""
    rows = content_store.due_for_acquisition(pg, limit=limit)
    return [row["source_item_id"] for row in rows]


class FakeFetcher:
    """Counts fetches per url; answers a full body for every one."""

    def __init__(self):
        self.calls: dict[str, int] = {}

    def __call__(self, url):
        self.calls[url] = self.calls.get(url, 0) + 1
        return acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_VISIBLE_TEXT,
            fetched_url=url, text="본문 " * 50)


def _tick(pg, mine, limit, fetcher):
    """One scheduler tick over this test's rows: the loop acquisition_job.run()
    runs, on this connection."""
    taken = _due(pg, mine, limit)
    for item in taken:
        with pg.cursor() as cur:
            cur.execute("SELECT url FROM source_items WHERE source_item_id = %s", (item,))
            url = cur.fetchone()[0]
        content_store.record_outcome(pg, item, fetcher(url))
    return taken


# === A. starvation ============================================================

def test_five_terminal_rows_no_longer_take_the_whole_tick(pg, unique):
    source = _source(pg, unique)
    robots = _terminal_robots(pg, _items(pg, source, unique, 5, "robots"))
    pending = _pending(pg, _items(pg, source, unique, 100, "pend"))
    mine = set(robots) | set(pending)

    taken = _due(pg, mine, 5)
    assert len(taken) == 5
    assert not set(taken) & set(robots), "a terminal row must never be selected"
    assert set(taken) <= set(pending)


def test_terminal_rows_are_excluded_before_the_limit_not_after(pg, unique):
    """Ask for exactly as many rows as there are terminal ones: if the SQL
    only filtered after LIMIT, this would come back empty."""
    source = _source(pg, unique)
    robots = _terminal_robots(pg, _items(pg, source, unique, 5, "robots"))
    pending = _pending(pg, _items(pg, source, unique, 5, "pend"))
    rows = [r["source_item_id"] for r in content_store.due_for_acquisition(pg, limit=5000)]
    assert not set(rows) & set(robots)
    assert set(pending) <= set(rows)


# === B. terminal is never selected again =====================================

def test_a_robots_row_with_null_next_attempt_is_never_returned_again(pg, unique):
    source = _source(pg, unique)
    robots = _terminal_robots(pg, _items(pg, source, unique, 1, "robots"))
    for _ in range(5):
        assert not set(_due(pg, set(robots), 100)) & set(robots)


@pytest.mark.parametrize("status, error_code, attempts", [
    (acquisition.FETCH_BLOCKED, "ROBOTS_DISALLOWED", 1),
    (acquisition.FETCH_BLOCKED, "ROBOTS_DISALLOWED", TERMINAL_ATTEMPTS),
    (acquisition.FETCH_FAILED, "UNSUPPORTED_CONTENT_TYPE", 1),
    # An exhausted retry class: the policy stops scheduling, the queue stops asking.
    (acquisition.FETCH_FAILED, "NETWORK", acquisition.MAX_ATTEMPTS["NETWORK"]),
    (acquisition.FETCH_FAILED, "NOT_FOUND", acquisition.MAX_ATTEMPTS["NOT_FOUND"]),
])
def test_every_row_the_policy_declined_to_reschedule_is_terminal(pg, unique, status, error_code, attempts):
    source = _source(pg, unique)
    item = _items(pg, source, unique, 1, "term")[0]
    content_store.ensure_row(pg, item)
    with pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET attempt_count = %s WHERE source_item_id = %s",
                    (attempts - 1, item))
    stored = content_store.record_outcome(pg, item, acquisition.AcquisitionOutcome(
        status=status, error_code=error_code, fetched_url=f"https://x.invalid/{item}"))
    assert stored["attempt_count"] == attempts
    assert stored["next_attempt_at"] is None, "the policy names no retry time"
    assert acquisition.queue_state(status, error_code, attempts, None) == acquisition.QUEUE_TERMINAL
    assert item not in _due(pg, {item}, 100)


# === C. new pending ==========================================================

def test_a_never_asked_row_is_selected_whether_or_not_it_carries_a_time(pg, unique):
    source = _source(pg, unique)
    stamped = _pending(pg, _items(pg, source, unique, 3, "stamped"))     # mark_pending: now()
    bare = _new_never_asked(pg, _items(pg, source, unique, 3, "bare"))    # NULL, attempt 0
    mine = set(stamped) | set(bare)
    assert set(_due(pg, mine, 100)) == mine
    for item in bare:
        assert acquisition.queue_state(acquisition.FETCH_PENDING, None, 0, None) == acquisition.QUEUE_PENDING


# === D / E. retryable ========================================================

def test_a_future_retry_is_left_alone_and_a_due_retry_is_taken(pg, unique):
    source = _source(pg, unique)
    future = _retry(pg, _items(pg, source, unique, 3, "future"), due=False)
    due = _retry(pg, _items(pg, source, unique, 3, "due"), due=True)
    taken = set(_due(pg, set(future) | set(due), 100))
    assert taken == set(due)
    later = datetime.now(timezone.utc) + timedelta(days=1)
    assert acquisition.queue_state(acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE", 1, later) == acquisition.QUEUE_RETRYABLE


def test_the_retry_schedule_and_backoff_are_untouched():
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    first = acquisition.next_attempt_at(acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE", 1, now=now, jitter=False)
    assert first == now + timedelta(hours=24)
    assert acquisition.next_attempt_at(acquisition.FETCH_BLOCKED, "ROBOTS_DISALLOWED", 1, now=now) is None
    assert acquisition.next_attempt_at(acquisition.FETCH_FAILED, "NETWORK", 5, now=now) is None
    assert acquisition.next_attempt_at(acquisition.FETCH_FAILED, "NETWORK", 1, now=now, jitter=False) == now + timedelta(minutes=15)


# === F. mixed queue ==========================================================

def test_a_mixed_queue_yields_only_normal_rows(pg, unique):
    source = _source(pg, unique)
    terminal = _terminal_robots(pg, _items(pg, source, unique, 10, "term"))
    future = _retry(pg, _items(pg, source, unique, 10, "future"), due=False)
    due = _retry(pg, _items(pg, source, unique, 3, "due"), due=True)
    new = _new_never_asked(pg, _items(pg, source, unique, 20, "new"))
    mine = set(terminal) | set(future) | set(due) | set(new)

    taken = _due(pg, mine, 5)
    assert len(taken) == 5
    assert not set(taken) & set(terminal)
    assert not set(taken) & set(future)
    assert set(taken) <= set(due) | set(new)
    # The existing priority contract: NULLS FIRST, then the oldest row.
    assert taken == sorted(new)[:5]
    everything = _due(pg, mine, 1000)
    assert set(everything) == set(due) | set(new)


# === G. multi-tick progress ==================================================

def test_twenty_pending_rows_all_get_their_turn_in_four_ticks(pg, unique):
    source = _source(pg, unique)
    robots = _terminal_robots(pg, _items(pg, source, unique, 5, "robots"))
    pending = _pending(pg, _items(pg, source, unique, 20, "pend"))
    mine = set(robots) | set(pending)
    fetcher = FakeFetcher()
    served: list[int] = []
    for _ in range(4):
        served += _tick(pg, mine, 5, fetcher)
    assert sorted(served) == sorted(pending), "every pending row was fetched exactly once"
    assert len(fetcher.calls) == 20
    assert _due(pg, mine, 100) == [], "nothing left: the settled rows are out, the terminal rows never in"


# === H. attempt_count of a terminal row never moves ==========================

def test_a_terminal_rows_attempts_stay_at_541_and_the_fetcher_never_sees_it(pg, unique):
    source = _source(pg, unique)
    robots = _terminal_robots(pg, _items(pg, source, unique, 5, "robots"))
    pending = _pending(pg, _items(pg, source, unique, 7, "pend"))
    mine = set(robots) | set(pending)
    before = _attempts(pg, robots)
    assert set(before.values()) == {TERMINAL_ATTEMPTS}
    fetcher = FakeFetcher()
    for _ in range(3):
        _tick(pg, mine, 5, fetcher)
    assert _attempts(pg, robots) == before, "history kept, never incremented"
    with pg.cursor() as cur:
        cur.execute("SELECT url FROM source_items WHERE source_item_id = ANY(%s)", (robots,))
        robot_urls = {row[0] for row in cur.fetchall()}
    assert not robot_urls & set(fetcher.calls), "the fetcher was never called for a terminal row"
    assert set(_attempts(pg, pending).values()) == {1}


# === 가또땅고-shaped fixture =================================================

def test_robots_rows_are_skipped_and_the_daum_bodies_are_read(pg, unique):
    naver = _source(pg, unique, key="SRC-N", platform="NAVER_CAFE")
    daum = _source(pg, unique, key="SRC-D", platform="DAUM_CAFE")
    robots = _terminal_robots(pg, _items(pg, naver, unique, 5, "jinju"))
    daum_pending = _pending(pg, _items(pg, daum, unique, 12, "gato"))
    mine = set(robots) | set(daum_pending)

    fetcher = FakeFetcher()
    first = _tick(pg, mine, 5, fetcher)
    assert set(first) <= set(daum_pending) and len(first) == 5
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM source_item_content WHERE source_item_id = ANY(%s) "
                    "AND acquisition_status = %s", (daum_pending, acquisition.FETCHED_FULL))
        assert cur.fetchone()[0] == 5
    # The v0.96.0 diagnostics: the robots rows are blocked (metadata-limited),
    # never "body pending"; the Daum rows still waiting are exactly that.
    with pg.cursor() as cur:
        cur.execute("UPDATE source_items SET ingest_state = 'INGESTED' WHERE source_id IN (%s, %s)", (naver, daum))
    overview = {e["source_id"]: e for e in source_ops.overview(pg)}
    assert overview[naver]["body_pending"] == 0 and overview[naver]["blocked"] == 5
    assert overview[daum]["body_pending"] == 7 and overview[daum]["fetched"] == 5


# === the helper and the SQL agree; run() still asks the queue =================

def test_queue_state_mirrors_the_selection_rule():
    now = datetime.now(timezone.utc)
    S = acquisition
    assert S.queue_state(S.FETCH_PENDING, None, 0, None) == S.QUEUE_PENDING
    assert S.queue_state(S.FETCH_PENDING, None, 0, now) == S.QUEUE_RETRYABLE
    assert S.queue_state(S.FETCH_BLOCKED, "BODY_UNAVAILABLE", 3, now + timedelta(days=3)) == S.QUEUE_RETRYABLE
    assert S.queue_state(S.FETCH_BLOCKED, "ROBOTS_DISALLOWED", 0, None) == S.QUEUE_TERMINAL
    assert S.queue_state(S.FETCH_BLOCKED, "ROBOTS_DISALLOWED", 541, None) == S.QUEUE_TERMINAL
    assert S.queue_state(S.FETCH_FAILED, "NETWORK", 5, None) == S.QUEUE_TERMINAL
    assert S.queue_state(S.FETCHED_FULL, None, 1, None) == S.QUEUE_TERMINAL
    assert S.queue_state(S.LOGIN_REQUIRED, "BLOCKED", 1, None) == S.QUEUE_TERMINAL
    assert S.queue_state(S.METADATA_ONLY, None, 0, None) == S.QUEUE_TERMINAL


def test_the_scheduler_job_still_selects_through_due_for_acquisition_with_its_budget(monkeypatch):
    """The fix lives in the selection; the tick must still go through it with
    the unchanged budget of 5. The connection and the queue are both fakes
    answering nothing, so no row of any database is touched."""
    from contextlib import contextmanager

    from scheduler import acquisition_job

    seen = {}

    @contextmanager
    def fake_connect(settings, *, autocommit=False):
        yield object()

    monkeypatch.setattr(acquisition_job.db, "connect", fake_connect)
    monkeypatch.setattr(content_store, "newly_collected", lambda con: [])
    monkeypatch.setattr(content_store, "mark_pending", lambda con, ids: 0)

    def spy(con, *, limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(content_store, "due_for_acquisition", spy)
    assert acquisition_job.MAX_FETCHES_PER_TICK == 5
    assert acquisition_job.run(object(), sleep=lambda s: None).startswith("nothing due")
    assert seen["limit"] == 5
