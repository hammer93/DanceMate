"""Review queue DB-level pagination at synthetic scale (v0.81.2).

Before this release, `/admin/review` fetched the newest 300 candidates
(`candidates.list_candidates(limit=300)`) and did every filter, sort and page
cut in Python. The 301st row - and everything past it, however urgent -
simply could not be reached. `candidates.query()` replaced that with a real
SQL WHERE/ORDER BY/LIMIT/OFFSET; this file proves it at a scale the old code
could never have served: 737 synthetic candidates, spanning well past the old
300-row ceiling and past 700, is not something a real board queue is likely
to reach yet, but the query must already be correct there, since it is a
`LIMIT/OFFSET` and not a cap.

No PostgreSQL needed: the "reviewed" side of the queue (candidate_review_state)
is irrelevant to the "upcoming" filter these tests use, so `reviewed_ids` is
passed as an empty set throughout, and only the engine's own SQLite file
(built here by hand, matching engine/src/database.py's schema) is involved.
"""

from __future__ import annotations

import sqlite3

import pytest

from runtime import admin_pages, candidates, pagination

TOTAL_ROWS = 737
BASE_DATE = "2026-01-01"  # arbitrary, fixed so the test is not clock-dependent


def _seed(settings, n: int = TOTAL_ROWS) -> None:
    """`n` complete, non-conflicting candidates, one calendar day apart.

    Starting two days out (never "today"/"tomorrow") and giving every row a
    time, venue and fee keeps every CASE tier in candidates._ORDER_BY equal
    except the days-away term - so the resulting order is exactly creation
    order, and a synthetic test can assert on it without re-implementing the
    sort.
    """
    path = candidates.engine_db_path(settings)
    con = sqlite3.connect(str(path))
    try:
        con.executescript("""
            CREATE TABLE raw_posts(
                post_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT, source_url TEXT, title TEXT NOT NULL,
                cafe_name TEXT, collected_at TEXT NOT NULL
            );
            CREATE TABLE event_candidates(
                candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL,
                name TEXT, event_type TEXT, event_date TEXT, start_time TEXT, end_time TEXT,
                fee INTEGER, venue TEXT, status TEXT
            );
        """)
        for i in range(1, n + 1):
            con.execute(
                "INSERT INTO raw_posts(post_id, source_id, source_url, title, "
                "cafe_name, collected_at) VALUES (?, 'WEB', ?, ?, 'synthetic', ?)",
                (i, f"https://example.test/{i}", f"post {i}", f"2026-01-01T00:00:{i % 60:02d}"),
            )
            con.execute(
                "INSERT INTO event_candidates(candidate_id, post_id, name, event_type, "
                "event_date, start_time, end_time, fee, venue, status) "
                "VALUES (?, ?, ?, 'MILONGA', date(?, ?), '20:00', '23:00', 13000, "
                "'Synthetic Studio', 'POSSIBLE')",
                (i, i, f"Synthetic Event {i}", BASE_DATE, f"+{i + 1} day"),
            )
        con.commit()
    finally:
        con.close()


@pytest.fixture
def seeded(settings):
    _seed(settings)
    return settings


def _names(rows) -> list[str]:
    return [r["event_name"] for r in rows]


def test_total_reflects_every_synthetic_row_not_a_300_cap(seeded):
    result = candidates.query(seeded, filter_key="upcoming", reviewed_ids=set(),
                               page=1, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert result["total"] == TOTAL_ROWS


def test_page_1_is_the_first_50_in_date_order(seeded):
    result = candidates.query(seeded, filter_key="upcoming", reviewed_ids=set(),
                               page=1, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert len(result["rows"]) == 50
    assert _names(result["rows"])[0] == "Synthetic Event 1"
    assert _names(result["rows"])[-1] == "Synthetic Event 50"


def test_page_6_is_reachable_past_the_old_300_row_window(seeded):
    result = candidates.query(seeded, filter_key="upcoming", reviewed_ids=set(),
                               page=6, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert _names(result["rows"])[0] == "Synthetic Event 251"
    assert _names(result["rows"])[-1] == "Synthetic Event 300"


def test_pending_with_nothing_reviewed_yet_shows_every_reviewable_row(seeded):
    """SQL's `x NOT IN (NULL)` is NULL - never true - for any x. A board with
    zero human review actions ever recorded (reviewed_ids empty) hit this
    directly: "pending" silently matched nothing instead of every POSSIBLE
    candidate, found live on the board before this was caught."""
    result = candidates.query(seeded, filter_key="pending", reviewed_ids=set(),
                               page=1, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert result["total"] == TOTAL_ROWS


def test_reviewed_with_nothing_reviewed_yet_shows_no_rows(seeded):
    result = candidates.query(seeded, filter_key="reviewed", reviewed_ids=set(),
                               page=1, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert result["total"] == 0


def test_pending_excludes_exactly_the_reviewed_ids(seeded):
    reviewed = {1, 2, 3}
    result = candidates.query(seeded, filter_key="pending", reviewed_ids=reviewed,
                               page=1, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert result["total"] == TOTAL_ROWS - len(reviewed)
    seen_ids = {r["candidate_id"] for r in result["rows"]}
    assert seen_ids.isdisjoint(reviewed)


def test_page_7_starts_on_the_301st_row(seeded):
    """The exact row the old `limit=300` fetch could never have returned."""
    result = candidates.query(seeded, filter_key="upcoming", reviewed_ids=set(),
                               page=7, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert len(result["rows"]) == 50
    assert _names(result["rows"])[0] == "Synthetic Event 301"


def test_page_13_is_reachable_well_past_the_old_cap(seeded):
    result = candidates.query(seeded, filter_key="upcoming", reviewed_ids=set(),
                               page=13, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert _names(result["rows"])[0] == "Synthetic Event 601"
    assert _names(result["rows"])[-1] == "Synthetic Event 650"


def test_last_page_shows_the_true_remainder_not_a_full_50(seeded):
    last = pagination.total_pages(TOTAL_ROWS)
    assert last == 15  # ceil(737 / 50)
    result = candidates.query(seeded, filter_key="upcoming", reviewed_ids=set(),
                               page=last, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert len(result["rows"]) == 37  # 737 - 14*50
    assert _names(result["rows"])[0] == "Synthetic Event 701"
    assert _names(result["rows"])[-1] == "Synthetic Event 737"


def test_a_page_past_the_last_one_is_empty_not_an_error(seeded):
    result = candidates.query(seeded, filter_key="upcoming", reviewed_ids=set(),
                               page=999, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
    assert result["rows"] == []
    assert result["total"] == TOTAL_ROWS  # the count is unaffected by an out-of-range page


def test_pages_partition_the_queue_with_no_gaps_and_no_duplicates(seeded):
    """Walking every page start-to-finish reconstructs all 737 rows exactly once."""
    seen: list[str] = []
    for page in range(1, pagination.total_pages(TOTAL_ROWS) + 1):
        result = candidates.query(seeded, filter_key="upcoming", reviewed_ids=set(),
                                   page=page, page_size=pagination.PAGE_SIZE, today=BASE_DATE)
        seen.extend(_names(result["rows"]))
    assert len(seen) == TOTAL_ROWS
    assert len(set(seen)) == TOTAL_ROWS  # no row repeated across a page boundary
    assert seen[0] == "Synthetic Event 1"
    assert seen[-1] == "Synthetic Event 737"


# --- invalid page params must never 500 -------------------------------------
#
# The actual guard lives in admin_pages._raw_page() (first pass, before the
# true total is known) and pagination.resolve_page() (final clamp, once it
# is) - proven here directly, without needing a live request, since these are
# the two pure functions the route relies on to never hand SQLite a page
# number that produces a 500.

@pytest.mark.parametrize("raw", [0, -1, "abc", None, "", "3.5", "999999"])
def test_raw_page_always_returns_a_positive_int(raw):
    page = admin_pages._raw_page(raw)
    assert isinstance(page, int)
    assert page >= 1


@pytest.mark.parametrize("raw,expected", [
    (0, 1), (-1, 1), ("abc", 1), (None, 1), ("", 1),
    ("7", 7), (999999, 15),  # clamped to the last real page of 737 rows
])
def test_resolve_page_clamps_into_the_real_range(raw, expected):
    assert pagination.resolve_page(raw, TOTAL_ROWS) == expected
