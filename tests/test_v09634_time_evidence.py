# -*- coding: utf-8 -*-
"""v0.96.34: an hour written 14:00 was being reported as one nobody confirmed.

`events.time_evidence` carried the engine's *marker* verdict only - EXPLICIT
when the post wrote PM/오후, ABSENT when it wrote none - and the reader turned
ABSENT into `time_confirmed: false`. But a post that writes `시간: 14:00~18:00`
writes no marker either, and needs none: 14 o'clock has one reading. The
engine has recorded exactly that all along, as `ambiguous: False` in the same
evidence row, and nobody read it. Measured on Production before the change:
of 711 ABSENT Events, 659 were of this kind and none of them started before
noon; the remaining 52 wrote a bare 1..12 clock and stay unconfirmed.

Builds a throwaway engine database at the shape `candidates._connect()`
expects, the way test_candidates_genre_hints.py does, because this needs
specific evidence rows rather than whatever the committed fixture holds.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
from datetime import date, time

import pytest

from runtime import candidates, events_api, quality
from runtime.engine_adapter import ENGINE_DB_FILENAME

# (candidate_id, inference, reading) exactly as the engine writes them.
READINGS = [
    (201, "ABSENT", {"start": "14:00", "end": "18:00", "end_day_offset": 0,
                     "meridiem_evidence": "ABSENT", "ambiguous": False}),
    (202, "ABSENT", {"start": "09:15", "end": "11:15", "end_day_offset": 0,
                     "meridiem_evidence": "ABSENT", "ambiguous": True}),
    (203, "EXPLICIT", {"start": "21:15", "end": "23:15", "end_day_offset": 0,
                       "meridiem_evidence": "EXPLICIT", "ambiguous": False}),
    (204, "PROPAGATED", {"start": "19:30", "end": "23:30", "end_day_offset": 0,
                         "meridiem_evidence": "PROPAGATED", "ambiguous": False}),
    (205, "ABSENT", {"start": "20:00", "end": "02:00", "end_day_offset": 1,
                     "meridiem_evidence": "ABSENT", "ambiguous": False}),
]


@pytest.fixture
def engine_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINE_DATA_DIR", str(tmp_path))
    con = sqlite3.connect(tmp_path / ENGINE_DB_FILENAME)
    con.executescript(
        """
        CREATE TABLE evidences(
            evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER,
            field TEXT, value TEXT, raw_text TEXT, evidence_type TEXT,
            source_role TEXT, inference TEXT, context_id TEXT
        );
        """
    )
    for candidate_id, inference, reading in READINGS:
        con.execute(
            "INSERT INTO evidences(candidate_id, field, value, raw_text, "
            "  inference) VALUES (?, 'time', ?, ?, ?)",
            (candidate_id, json.dumps(reading), reading["start"], inference),
        )
    con.commit()
    con.close()
    from runtime.config import load_settings

    return load_settings()


def test_an_hour_that_needs_no_marker_is_not_reported_as_unconfirmed(engine_db):
    read = candidates.time_evidence(engine_db, [c for c, _i, _r in READINGS])
    assert read[201] == candidates.EVIDENCE_UNAMBIGUOUS
    assert read[205] == candidates.EVIDENCE_UNAMBIGUOUS


def test_a_bare_clock_that_could_be_either_half_stays_absent(engine_db):
    read = candidates.time_evidence(engine_db, [202])
    assert read[202] == "ABSENT"


def test_a_marker_the_post_wrote_is_still_reported_as_the_post_wrote_it(engine_db):
    read = candidates.time_evidence(engine_db, [203, 204])
    assert read[203] == "EXPLICIT"
    assert read[204] == "PROPAGATED"


def test_an_unreadable_evidence_row_is_left_as_the_engine_marked_it(tmp_path,
                                                                    monkeypatch):
    monkeypatch.setenv("ENGINE_DATA_DIR", str(tmp_path))
    con = sqlite3.connect(tmp_path / ENGINE_DB_FILENAME)
    con.executescript(
        """
        CREATE TABLE evidences(
            evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER,
            field TEXT, value TEXT, raw_text TEXT, evidence_type TEXT,
            source_role TEXT, inference TEXT, context_id TEXT
        );
        """
    )
    for candidate_id, value in ((301, None), (302, "not json"), (303, "[]"),
                                (304, '{"start": "14:00"}')):
        con.execute(
            "INSERT INTO evidences(candidate_id, field, value, inference) "
            "VALUES (?, 'time', ?, 'ABSENT')", (candidate_id, value))
    con.commit()
    con.close()
    from runtime.config import load_settings

    read = candidates.time_evidence(load_settings(), [301, 302, 303, 304])
    assert set(read.values()) == {"ABSENT"}


def test_the_reader_confirms_an_unambiguous_hour():
    presented = events_api.present({
        "event_id": 1, "event_name": "밀롱가 루미노소 선데이탱고",
        "event_date": date(2026, 10, 18), "start_time": time(14, 0),
        "end_time": time(18, 0), "end_day_offset": 0,
        "time_evidence": candidates.EVIDENCE_UNAMBIGUOUS,
        "venue_status": "ABSENT", "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
    })
    assert presented["start_time"] == "14:00"
    assert presented["time_confirmed"] is True


def test_the_reader_still_refuses_to_confirm_a_bare_clock():
    presented = events_api.present({
        "event_id": 2, "event_name": "수요 쁘락띠까",
        "event_date": date(2026, 10, 14), "start_time": time(9, 15),
        "end_time": time(11, 15), "end_day_offset": 0,
        "time_evidence": "ABSENT", "venue_status": "ABSENT", "fee": None,
        "engine_status": "POSSIBLE", "review_state": "PENDING",
    })
    assert presented["time_confirmed"] is False


def test_the_quality_metric_counts_only_the_hours_that_need_confirming():
    # time_unconfirmed is still keyed on ABSENT, which now means only the
    # genuinely ambiguous rows - that is the whole point of splitting them.
    source = inspect.getsource(quality.completeness)
    assert "time_evidence = 'ABSENT'" in source
    assert f"time_evidence = '{candidates.EVIDENCE_UNAMBIGUOUS}'" not in source


def test_a_morning_claimed_against_an_explicit_marker_is_still_a_defect():
    assert "time_evidence = 'EXPLICIT'" in quality.WRONG_TIME_SQL
    assert candidates.EVIDENCE_UNAMBIGUOUS not in quality.WRONG_TIME_SQL
