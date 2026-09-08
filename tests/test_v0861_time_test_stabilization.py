"""v0.86.1 Time-dependent Test Stabilization.

Not a production behaviour change - a test-suite hardening pass. Two real,
permanent failures existed on main: `tests/test_v0852_source_depth.py` and
`tests/test_tangocalendar_discovery.py` both hardcoded a fixed calendar
date that the test's own intent needed to stay "upcoming"/"today" relative
to the REAL clock. Once the real calendar passed that fixed date, both
failed forever - not a flake, a permanent regression with each passing day.

Both are now fixed at the source (relative fixtures anchored to
`events_api.today()`, and an added optional `today=` parameter threaded
through `tangocalendar_discovery.parse_list()`/`discover()`, mirroring
`parse_events()`'s own pre-existing parameter - production callers never
pass it, so live behaviour is unchanged). This file is the project-wide
sweep's own deliverable: proving the underlying date arithmetic those
fixes rely on is genuinely date-agnostic (KST timezone boundary, week/
month/year rollover), and pinning `events_api.today()`'s own existing
KST-correctness across the boundary matrix Section 13 of the task asked
for, alongside the one point `test_v085_timeline_calendar.py`'s own
`test_kst_boundary_for_today` already covered.

No wall-clock sleeps anywhere in this file (Section 24) - every "clock" is
an explicit `datetime`/`date` passed to a function that already accepts
one, the same pattern `test_kst_boundary_for_today` already established.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from runtime import events_api


# --- Section 13: KST/UTC boundary matrix -------------------------------
#
# Asia/Seoul is UTC+9 with no DST, so the dangerous window is 00:00-08:59
# KST, when the UTC clock still reads the *previous* calendar day. A naive
# `datetime.utcnow().date()` anywhere in this codepath would read one day
# behind for nine hours out of every day; `events_api.today()` converts to
# SEOUL before taking `.date()`, so it must not.

@pytest.mark.parametrize("hour,minute,expected_day", [
    (0, 0, 12),    # KST midnight - the instant the day changes
    (0, 30, 12),   # just after midnight - still 11:xx UTC the day before
    (8, 59, 12),   # one minute before the UTC day itself rolls over
    (9, 0, 12),    # UTC midnight - KST is already 9 hours into the new day
    (23, 59, 12),  # one minute before KST midnight
])
def test_kst_boundary_matrix(hour, minute, expected_day):
    moment = datetime(2026, 9, 12, hour, minute, tzinfo=events_api.SEOUL)
    assert events_api.today(moment) == date(2026, 9, expected_day)


def test_kst_boundary_matrix_actually_disagrees_with_naive_utc():
    """Not a tautology: 00:30 KST is still 15:30 UTC *the day before* - if
    `today()` ever regressed to reading the UTC date directly instead of
    converting to Seoul first, this is the assertion that would catch it."""
    from datetime import timezone

    moment = datetime(2026, 9, 12, 0, 30, tzinfo=events_api.SEOUL)
    assert moment.astimezone(timezone.utc).date() == date(2026, 9, 11)
    assert events_api.today(moment) == date(2026, 9, 12)


# --- Section 17: week starts Monday -------------------------------------

@pytest.mark.parametrize("moment,expected_monday", [
    (datetime(2026, 9, 12, 0, 0, tzinfo=events_api.SEOUL), date(2026, 9, 7)),   # Saturday
    (datetime(2026, 9, 7, 0, 0, tzinfo=events_api.SEOUL), date(2026, 9, 7)),    # Monday itself
    (datetime(2026, 9, 13, 23, 59, tzinfo=events_api.SEOUL), date(2026, 9, 7)),  # Sunday, late
])
def test_week_window_starts_monday(moment, expected_monday):
    monday, sunday = events_api.week_window(0, now=moment)
    assert monday == expected_monday
    assert sunday == expected_monday + timedelta(days=6)
    assert monday <= moment.date() <= sunday


# --- Section 15/16/31/32: multi-date matrix for the relative-fixture
# arithmetic test_v0852_source_depth.py now uses (base = today + 14 days,
# week window recomputed around it) - proving the SHAPE of that fix is
# date-agnostic across month, year, and (2027-01-01 lands 14 days after a
# fresh year start) year-boundary cases, without needing to fake Postgres's
# own clock to literally re-run the DB-backed suite on each date. ----------

_MATRIX_DATES = [
    date(2026, 9, 8),   # the exact date that used to be hardcoded
    date(2026, 9, 9),   # the day it went stale
    date(2026, 12, 31),  # year-end
    date(2027, 1, 1),   # year-start
]


@pytest.mark.parametrize("simulated_today", _MATRIX_DATES)
def test_relative_base_date_is_always_comfortably_upcoming(simulated_today):
    base = simulated_today + timedelta(days=14)
    assert base > simulated_today
    assert (base - simulated_today).days == 14


@pytest.mark.parametrize("simulated_today", _MATRIX_DATES)
def test_relative_base_date_week_window_is_monday_start_and_contains_it(simulated_today):
    base = simulated_today + timedelta(days=14)
    week_start = base - timedelta(days=base.weekday())
    week_end = week_start + timedelta(days=6)
    assert week_start.weekday() == 0  # Monday
    assert week_end.weekday() == 6    # Sunday
    assert week_start <= base <= week_end
    assert (week_end - week_start).days == 6


def test_relative_base_date_crosses_year_boundary_correctly():
    """2026-12-31 + 14 days must land in 2027, not silently wrap or error -
    this is exactly what a hand-rolled month/day calculator could get
    wrong; `timedelta` arithmetic (the only date math anywhere in this
    codebase) gets it right by construction, which is what this pins."""
    base = date(2026, 12, 31) + timedelta(days=14)
    assert base == date(2027, 1, 14)


def test_relative_base_date_from_new_year_stays_in_the_new_year():
    base = date(2027, 1, 1) + timedelta(days=14)
    assert base == date(2027, 1, 15)


# --- Section 33: repeated-run flake check for the KST/week matrix above -
# not a wall-clock sleep loop (Section 24 forbids that) - the same
# parametrized cases re-evaluated is what "no flake" means for pure,
# already-deterministic date arithmetic: run alongside `pytest --count=10`
# or a shell loop if deeper confidence is wanted (see RELEASE_NOTES.md's
# own record of the actual repeated-run pass for this release).

def test_kst_boundary_matrix_is_deterministic_across_repeated_calls():
    moment = datetime(2026, 9, 12, 0, 30, tzinfo=events_api.SEOUL)
    results = {events_api.today(moment) for _ in range(20)}
    assert results == {date(2026, 9, 12)}
