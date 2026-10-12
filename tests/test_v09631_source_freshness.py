"""v0.96.31: a healthy scheduler is not an answer about the sources.

For three weeks `job_runs` recorded 2,042 consecutive PASSes, the heartbeat
said "jobs ok", and the Sources page showed every source ACTIVE - while two
collectors failed every single run. Three separate reasons, and the state
model here exists because of all three:

  1. a job's status answers "did the tick finish", not "did the sources work";
  2. `sources.record_collection_result()` writes `last_collected_at` on a
     failure too, so a source failing every tick can never look stale; and
  3. `admin._source_health()` named only AUTH_FAILED and BAD_RESPONSE, and
     both of these failures classified as UNKNOWN.

So the state has to be read from the *run history*, which is the only place
that knows a streak. Nothing here writes, and nothing here is derived from
volume: a source with 681 stored items whose last 133 runs all failed is
FAILED.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime import source_freshness as sf

NOW = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)


def _row(**over):
    row = {
        "source_id": 1,
        "source_key": "SRC-X-001",
        "name": "a source",
        "enabled": True,
        "collection_interval_minutes": 60,
        "last_status": "PASS",
        "last_attempt_at": NOW - timedelta(minutes=10),
        "last_success_at": NOW - timedelta(minutes=10),
        "last_partial_at": None,
        "recent_failures": 0,
        "consecutive_failures": 0,
        "last_acquired_item_at": NOW - timedelta(hours=2),
        "items_7d": 12,
        "last_error_kind": None,
        "last_error_message": None,
        "latest_future_event_date": None,
        "future_events": 3,
    }
    row.update(over)
    return row


def test_a_working_source_is_healthy():
    assert sf.classify(_row(), now=NOW) == sf.HEALTHY


def test_a_disabled_source_is_disabled_whatever_else_is_true():
    assert sf.classify(_row(enabled=False, consecutive_failures=90),
                       now=NOW) == sf.DISABLED


def test_two_failures_in_a_row_is_failed():
    assert sf.classify(_row(consecutive_failures=2), now=NOW) == sf.FAILED


def test_one_failure_is_degraded_not_yet_failed():
    """One tick can lose a connection. Two is not a blip."""
    assert sf.classify(_row(consecutive_failures=1), now=NOW) == sf.DEGRADED


def test_miltang_as_it_actually_was():
    """82 consecutive failures, last success 2026-09-21, 315 stored items,
    and `last_collected_at` refreshed by the failures themselves."""
    row = _row(
        source_key="SRC-W-005", name="Miltang",
        consecutive_failures=82, recent_failures=28,
        last_status="UNKNOWN", last_error_kind="UNKNOWN",
        last_error_message="has no readable day header - list page shape changed",
        last_success_at=datetime(2026, 9, 21, 11, 12, tzinfo=timezone.utc),
        last_attempt_at=NOW - timedelta(minutes=5),
        last_acquired_item_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        items_7d=0, future_events=0,
    )
    assert sf.classify(row, now=NOW) == sf.FAILED, \
        "this is the state that read as ACTIVE for three weeks"


def test_tangonow_as_it_actually_was():
    row = _row(
        source_key="SRC-W-002", name="TangoNOW",
        consecutive_failures=133, last_status="ACCESS_DENIED",
        last_error_kind="ACCESS_DENIED",
        last_error_message="TangoNOW Firestore returned 403 for ... - public "
                           "read rules may have changed",
        last_success_at=datetime(2026, 9, 25, 6, 35, tzinfo=timezone.utc),
        items_7d=0,
    )
    assert sf.classify(row, now=NOW) == sf.ACCESS_DENIED, \
        "a refusal is its own state - it needs an operator, not a retry"


def test_volume_never_makes_a_failing_source_healthy():
    row = _row(items_7d=527, future_events=55, consecutive_failures=5)
    assert sf.classify(row, now=NOW) == sf.FAILED


def test_a_source_that_has_never_passed_is_failed_not_unknown():
    row = _row(last_success_at=None, last_attempt_at=NOW - timedelta(minutes=5),
               consecutive_failures=0)
    assert sf.classify(row, now=NOW) == sf.FAILED


def test_a_source_never_attempted_is_unknown():
    row = _row(last_success_at=None, last_attempt_at=None)
    assert sf.classify(row, now=NOW) == sf.UNKNOWN


def test_a_source_whose_successes_have_stopped_is_stale():
    """Six of its own intervals with no clean run."""
    row = _row(last_success_at=NOW - timedelta(hours=10),
               collection_interval_minutes=60)
    assert sf.classify(row, now=NOW) == sf.STALE


def test_a_partial_window_is_its_own_state():
    when = NOW - timedelta(minutes=10)
    row = _row(last_success_at=when, last_partial_at=when)
    assert sf.classify(row, now=NOW) == sf.PARTIAL


def test_a_quiet_source_is_not_a_broken_one():
    """Collecting fine, publishing nothing. A community that posts monthly
    must not be reported as an outage."""
    row = _row(last_acquired_item_at=NOW - timedelta(days=45), items_7d=0)
    assert sf.classify(row, now=NOW) == sf.NO_RECENT_CONTENT


def test_failing_puts_the_worst_first():
    rows = [
        _row(source_id=1, source_key="stale", last_success_at=NOW - timedelta(days=5)),
        _row(source_id=2, source_key="denied", consecutive_failures=3,
             last_status="ACCESS_DENIED"),
        _row(source_id=3, source_key="failed", consecutive_failures=82),
        _row(source_id=4, source_key="fine"),
        _row(source_id=5, source_key="degraded", consecutive_failures=1),
    ]
    for row in rows:                       # what report() does before failing()
        row["state"] = sf.classify(row, now=NOW)
    order = [r["source_key"] for r in sf.failing(rows)]
    assert order == ["failed", "denied", "degraded", "stale"]
    assert "fine" not in order


def test_failing_ignores_a_row_that_was_never_classified():
    assert sf.failing([{"source_key": "x"}]) == []


def test_a_healthy_scheduler_does_not_hide_a_failed_source():
    """The whole point. Nothing in this state model reads the job table."""
    row = _row(consecutive_failures=82, last_status="UNKNOWN")
    assert sf.classify(row, now=NOW) == sf.FAILED


# --- the admin badge the operator actually sees ----------------------------

def test_admin_health_reports_a_failing_collector():
    from runtime import admin

    source = {"enabled": True, "last_status": "UNKNOWN",
              "last_collected_at": NOW - timedelta(minutes=5),
              "collection_interval_minutes": 60}
    outcome = {"items": 315, "fetched": 315, "blocked": 0, "events": 261}
    assert admin._source_health(source, outcome) == admin.HEALTH_ACTIVE, \
        "without the freshness row this is exactly the old, wrong answer"
    state = {"state": sf.FAILED}
    assert admin._source_health(source, outcome, state) == \
        admin.HEALTH_COLLECTION_FAILING


def test_admin_health_reports_a_refusal_distinctly():
    from runtime import admin

    source = {"enabled": True, "last_status": "ACCESS_DENIED",
              "last_collected_at": NOW, "collection_interval_minutes": 60}
    assert admin._source_health(source, {}, {"state": sf.ACCESS_DENIED}) == \
        admin.HEALTH_ACCESS_DENIED


def test_admin_health_still_reports_the_states_it_always_did():
    from runtime import admin

    assert admin._source_health({"enabled": False}, {}) == admin.HEALTH_DISABLED
    blocked = {"enabled": True, "last_status": "PASS",
               "last_collected_at": NOW, "collection_interval_minutes": 60}
    assert admin._source_health(
        blocked, {"items": 10, "fetched": 0, "blocked": 10, "events": 0},
        {"state": sf.HEALTHY}) == admin.HEALTH_FETCH_BLOCKED


# --- the zero-supply vocabulary -------------------------------------------

def test_the_four_reasons_a_region_shows_zero_are_distinct():
    """One ERROR for all four would tell an operator nothing about what to
    do: fix a collector, register a source, resolve a venue, or wait."""
    assert len({sf.ZERO_NO_EVENTS, sf.ZERO_COLLECTOR_FAILED,
                sf.ZERO_NO_SOURCE, sf.ZERO_UNATTRIBUTED}) == 4


def test_the_watched_regions_include_the_three_that_went_empty():
    for code in ("KR-BUSAN", "KR-DAEGU", "KR-DAEJEON"):
        assert code in sf.WATCHED_REGIONS
    assert "KR-SEOUL" in sf.WATCHED_REGIONS, \
        "the control: a zero everywhere and a zero in three cities are " \
        "different problems, and the table has to show the difference"
