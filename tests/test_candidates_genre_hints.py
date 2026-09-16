"""candidates.genre_hints() (v0.91.0 PHASE 6): reading the engine's own
"genre_hint" evidence back out of its SQLite store.

Builds a throwaway engine database at the exact filename/shape
runtime.candidates._connect() expects (engine_adapter.ENGINE_DB_FILENAME),
rather than depending on the shared, committed engine/data fixtures - this
needs specific, deterministic evidence rows, not whatever the fixture store
happens to hold today.
"""

from __future__ import annotations

import sqlite3

import pytest

from runtime import candidates
from runtime.engine_adapter import ENGINE_DB_FILENAME


@pytest.fixture
def engine_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINE_DATA_DIR", str(tmp_path))
    db_path = tmp_path / ENGINE_DB_FILENAME
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE raw_posts(post_id INTEGER PRIMARY KEY, title TEXT, body TEXT);
        CREATE TABLE event_candidates(
            candidate_id INTEGER PRIMARY KEY, post_id INTEGER, name TEXT,
            event_type TEXT, event_date TEXT
        );
        CREATE TABLE evidences(
            evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER,
            field TEXT, value TEXT, raw_text TEXT, evidence_type TEXT,
            source_role TEXT, inference TEXT, context_id TEXT
        );
        """
    )
    con.execute("INSERT INTO raw_posts VALUES (1, 't', 'b')")
    con.execute("INSERT INTO raw_posts VALUES (2, 't2', 'b2')")
    con.execute(
        "INSERT INTO event_candidates VALUES (101, 1, 'Salsa&Bachata Night', 'SOCIAL', '2026-09-20')"
    )
    con.execute(
        "INSERT INTO event_candidates VALUES (102, 2, 'Pure Swing Social', 'SOCIAL', '2026-09-16')"
    )
    con.execute(
        "INSERT INTO evidences(candidate_id, field, value, raw_text) "
        "VALUES (101, 'genre_hint', 'BACHATA', 'Salsa&Bachata Night')"
    )
    con.execute(
        "INSERT INTO evidences(candidate_id, field, value, raw_text) "
        "VALUES (101, 'date', '2026-09-20', '9/20')"
    )
    con.commit()
    con.close()
    from runtime.config import load_settings

    return load_settings()


def test_a_candidate_with_a_genre_hint_returns_its_code(engine_db):
    hints = candidates.genre_hints(engine_db, [101, 102])
    assert hints == {101: ["BACHATA"]}


def test_a_candidate_with_no_genre_hint_is_absent_from_the_result(engine_db):
    hints = candidates.genre_hints(engine_db, [102])
    assert hints == {}


def test_an_empty_id_list_returns_empty_without_touching_the_store():
    assert candidates.genre_hints(object(), []) == {}


def test_multiple_hints_on_one_candidate_all_come_back(engine_db):
    import sqlite3 as _sqlite3

    from runtime.engine_adapter import engine_db_path

    con = _sqlite3.connect(engine_db_path(engine_db))
    con.execute(
        "INSERT INTO evidences(candidate_id, field, value, raw_text) "
        "VALUES (101, 'genre_hint', 'KIZOMBA', 'Salsa&Bachata Night')"
    )
    con.commit()
    con.close()
    hints = candidates.genre_hints(engine_db, [101])
    assert set(hints[101]) == {"BACHATA", "KIZOMBA"}


def test_only_explicitly_ambiguous_engine_clock_is_flagged(engine_db):
    from runtime.engine_adapter import engine_db_path

    con = sqlite3.connect(engine_db_path(engine_db))
    for candidate_id, value in (
        (101, '{"start":"07:20","ambiguous":true}'),
        (102, '{"start":"21:10","ambiguous":false}'),
        (102, 'not-json'),
    ):
        con.execute(
            "INSERT INTO evidences(candidate_id, field, value, raw_text) "
            "VALUES (?, 'time', ?, 'raw clock')", (candidate_id, value),
        )
    con.commit()
    con.close()
    assert candidates.ambiguous_time_ids(engine_db, [101, 102]) == {101}
    assert candidates.ambiguous_time_ids(engine_db, []) == set()
