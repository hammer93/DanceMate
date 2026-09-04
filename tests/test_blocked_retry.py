"""Coming back to a page that refused us.

FETCH_BLOCKED was in neither the settled set nor the retryable one. It read as
caution and behaved as amnesia: the item was asked once, refused once, and
never queued again. On the board that was 47 items frozen for good, and two
cafes whose settings might change next week would never have been noticed.

The other half of the problem is the opposite one. A blocked page that comes
back round every tick is a page being hammered, and a batch that failed
together must not return together.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime import acquisition

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _next(status, error_code, attempt, *, now=NOW, jitter=False):
    return acquisition.next_attempt_at(
        status, error_code, attempt, now=now, jitter=jitter)


# --- 32.1, 32.9: blocked comes back at all ----------------------------------

def test_a_blocked_page_is_asked_again():
    """The whole bug, in one assertion."""
    assert acquisition.FETCH_BLOCKED in acquisition.RETRYABLE
    assert acquisition.FETCH_BLOCKED not in acquisition.SETTLED
    assert _next(acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE", 1) is not None


def test_the_fetcher_selects_on_the_same_set_it_retries_on():
    """due_for_acquisition filters by RETRYABLE; if the two ever drift, blocked
    items get a next_attempt_at that nothing acts on -- which is what the old
    code did."""
    import inspect

    from runtime import content_store

    source = inspect.getsource(content_store.due_for_acquisition)
    assert "acquisition.RETRYABLE" in source
    assert "next_attempt_at" in source


# --- 32.2, 32.3: not immediately, and not for a day --------------------------

def test_a_blocked_page_is_not_retried_on_the_next_tick():
    due = _next(acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE", 1)
    assert due - NOW >= timedelta(hours=24)


def test_the_first_retry_waits_a_day():
    assert _next(acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE", 1) == NOW + timedelta(hours=24)


# --- 32.4, 32.5: it backs off, and stops backing off ------------------------

def test_repeated_failures_wait_longer_each_time():
    waits = [_next(acquisition.FETCH_BLOCKED, "BLOCKED", n) - NOW for n in (1, 2, 3)]
    assert waits == [timedelta(hours=24), timedelta(hours=72), timedelta(days=7)]
    assert waits == sorted(waits)


def test_the_backoff_stops_at_a_week():
    for attempt in (3, 4, 10, 100):
        assert _next(acquisition.FETCH_BLOCKED, "BLOCKED", attempt) - NOW == timedelta(days=7)


def test_a_blocked_page_is_never_given_up_on_entirely():
    """A week apart forever is about fifty requests a year. Cheap enough to
    keep the door open, and the only way recovery is ever noticed."""
    assert acquisition.MAX_ATTEMPTS["BLOCKED"] is None
    assert _next(acquisition.FETCH_BLOCKED, "BLOCKED", 500) is not None


# --- 32.6: success ends it ---------------------------------------------------

@pytest.mark.parametrize("status", [acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL])
def test_a_successful_fetch_settles_the_item(status):
    assert status in acquisition.SETTLED
    assert _next(status, None, 5) is None


def test_recovery_is_just_the_next_outcome_winning():
    """Nothing special-cases recovery: the row stores whatever the last attempt
    produced, so a body arriving replaces the blocked status by itself."""
    import inspect

    from runtime import content_store

    source = inspect.getsource(content_store.record_outcome)
    assert "acquisition_status = %s" in source
    assert "outcome.status" in source


# --- 32.7, 32.8: the ones that must not be retried --------------------------

def test_a_login_wall_is_not_retried_until_the_credentials_change():
    """Asking again changes nothing and looks like an attack."""
    assert acquisition.LOGIN_REQUIRED in acquisition.SETTLED
    assert _next(acquisition.LOGIN_REQUIRED, "BLOCKED", 1) is None


def test_a_missing_page_is_not_retried_noisily():
    assert _next(acquisition.FETCH_BLOCKED, "NOT_FOUND", 1) == NOW + timedelta(hours=12)
    assert _next(acquisition.FETCH_BLOCKED, "NOT_FOUND", 2) is None


def test_a_page_we_were_told_not_to_fetch_is_never_fetched_again():
    """robots.txt is not a transient condition, and re-asking is rude."""
    assert "ROBOTS_DISALLOWED" in acquisition.PERMANENT_ERRORS
    for attempt in (1, 2, 5):
        assert _next(acquisition.FETCH_BLOCKED, "ROBOTS_DISALLOWED", attempt) is None
    assert _next(acquisition.FETCH_BLOCKED, "UNSUPPORTED_CONTENT_TYPE", 1) is None


# --- 32.11: they do not all come back together ------------------------------

def test_retries_are_spread_rather_than_synchronised():
    due = [acquisition.next_attempt_at(
        acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE", 1, now=NOW) for _ in range(40)]
    assert len(set(due)) > 30, "a batch that failed together would return together"


def test_the_spread_only_ever_delays_a_retry():
    base = NOW + timedelta(hours=24)
    for _ in range(40):
        due = acquisition.next_attempt_at(
            acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE", 1, now=NOW)
        assert base <= due <= base + timedelta(hours=24) * acquisition.RETRY_JITTER


# --- 32.12: nothing else moved ----------------------------------------------

def test_the_other_retry_classes_are_unchanged():
    assert _next(acquisition.FETCH_FAILED, "NETWORK", 1) == NOW + timedelta(minutes=15)
    assert _next(acquisition.FETCH_FAILED, "SERVER_ERROR", 1) == NOW + timedelta(minutes=30)
    assert _next(acquisition.FETCH_FAILED, "NETWORK", 5) is None
    assert _next(acquisition.FETCH_FAILED, "SERVER_ERROR", 5) is None


def test_an_unknown_error_code_still_behaves_like_a_network_blip():
    assert _next(acquisition.FETCH_FAILED, "SOMETHING_NEW", 1) == NOW + timedelta(minutes=15)


# --- the schedule is readable as a policy -----------------------------------

def test_the_schedule_says_what_the_release_notes_say():
    schedule = acquisition.RETRY_SCHEDULE["BLOCKED"]
    assert schedule == (timedelta(hours=24), timedelta(hours=72), timedelta(days=7))
    # And the first delay is still reachable where callers expect it.
    assert acquisition.RETRY_BACKOFF["BLOCKED"] == timedelta(hours=24)


# --- 32.9, 32.10, 45: through the real queue --------------------------------

def _synthetic_item(pg, unique):
    """A source item nobody collected, so no live source is touched."""
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-RETRY-{unique}", name=f"retry probe {unique}",
        platform="WEB", source_role="COMMUNITY",
        url=f"https://example.invalid/{unique}", enabled=False)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, title, content_hash) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING source_item_id",
            (source["source_id"], f"ext-{unique}",
             f"https://example.invalid/{unique}/1", "retry probe", f"hash-{unique}"))
        return cur.fetchone()[0]


def _outcome(status, error_code=None, text=""):
    # text defaults to "" on the dataclass and no fetch path leaves it None;
    # passing None here would be testing a shape production cannot produce.
    return acquisition.AcquisitionOutcome(
        status=status, error_code=error_code, text=text,
        fetched_url="https://example.invalid/x")


def test_a_blocked_item_leaves_the_queue_then_comes_back_to_it(pg, unique):
    """blocked -> not due -> due -> success -> settled, on the real tables."""
    from runtime import content_store

    item_id = _synthetic_item(pg, unique)
    content_store.ensure_row(pg, item_id)

    def queued(now=None):
        due = content_store.due_for_acquisition(pg, limit=1000)
        return any(row["source_item_id"] == item_id for row in due)

    assert queued(), "a fresh item should be waiting to be fetched"

    # It refuses its body.
    stored = content_store.record_outcome(
        pg, item_id, _outcome(acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE"),
        now=NOW)
    assert stored["acquisition_status"] == acquisition.FETCH_BLOCKED
    assert stored["next_attempt_at"] is not None, "blocked must be scheduled, not dropped"
    assert stored["next_attempt_at"] >= NOW + timedelta(hours=24)
    assert stored["last_attempt_at"] is not None
    assert stored["fetched_at"] is None, "we asked, we did not receive"
    assert not queued(), "and it must not come round again on the next tick"

    # A day later it is due again.
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET next_attempt_at = now() - interval '1 minute' "
            "WHERE source_item_id = %s", (item_id,))
    assert queued(), "after its wait, a blocked item is asked again"

    # This time the page answers.
    recovered = content_store.record_outcome(
        pg, item_id,
        _outcome(acquisition.FETCHED_FULL, None, text="본문" * 100), now=NOW)
    assert recovered["acquisition_status"] == acquisition.FETCHED_FULL
    assert recovered["next_attempt_at"] is None, "a settled item needs no retry"
    assert recovered["fetched_at"] is not None
    assert not queued()


def test_an_item_not_yet_due_is_left_alone(pg, unique):
    from runtime import content_store

    item_id = _synthetic_item(pg, unique)
    content_store.ensure_row(pg, item_id)
    content_store.record_outcome(
        pg, item_id, _outcome(acquisition.FETCH_BLOCKED, "BODY_UNAVAILABLE"))

    due = content_store.due_for_acquisition(pg, limit=1000)
    assert item_id not in {row["source_item_id"] for row in due}


def test_a_login_wall_never_returns_to_the_queue(pg, unique):
    from runtime import content_store

    item_id = _synthetic_item(pg, unique)
    content_store.ensure_row(pg, item_id)
    stored = content_store.record_outcome(
        pg, item_id, _outcome(acquisition.LOGIN_REQUIRED, "BLOCKED"))
    assert stored["next_attempt_at"] is None
    due = content_store.due_for_acquisition(pg, limit=1000)
    assert item_id not in {row["source_item_id"] for row in due}
