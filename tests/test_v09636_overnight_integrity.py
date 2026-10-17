"""v0.96.36 Part B - an overnight event says it ends the next day.

Measured on Production (v0.96.35, 2026-10-17): the engine store holds
`end_day_offset = 1` on 321 candidates and the `events` table on none of its
1,411 rows. The 317 events whose end clock is at or before their start
(`20:00~02:00`, `20:00~00:00`) are exactly the 317 offset-1 candidates that
have a row; the other 4 have no date and never became an event. Every one was
served with `ends_next_day: false`, so a card read "20:00~02:00" as a night
that ends before it begins, and the "now on" check never fired for it.

Root cause: `normalize_candidate()` has written `end_day_offset` since
migration 007, but none of `runtime/candidates.py`'s SELECTs ever read the
column, so the key was always absent and `or 0` always won. The fix carries
the engine's own answer - it is never re-derived from `end < start` - and
adds the column to `NORMALIZATION_INPUT_COLUMNS`, which is the queue's own
contract for re-flowing rows already built without it.

Everything here runs the real route: a throwaway engine SQLite store, the
runtime's SELECTs, `normalize_all()` into the real `events` table (inside the
`pg` fixture's rolled-back transaction), `events_api.search()`, and the
public JSON route.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import time

import pytest
from fastapi.testclient import TestClient

from runtime import candidates as candidate_store
from runtime import db, events_api, normalization
from runtime.engine_adapter import ENGINE_DB_FILENAME

ENGINE_SCHEMA = """
CREATE TABLE raw_posts(
    post_id INTEGER PRIMARY KEY, source_id TEXT, source_url TEXT, title TEXT,
    body TEXT, collected_at TEXT, cafe_name TEXT
);
CREATE TABLE event_candidates(
    candidate_id INTEGER PRIMARY KEY, post_id INTEGER, name TEXT,
    event_type TEXT, event_date TEXT, start_time TEXT, end_time TEXT,
    end_day_offset INTEGER, fee INTEGER, fee_display_text TEXT, venue TEXT,
    dj TEXT, status TEXT, core_complete INTEGER
);
CREATE TABLE evidences(
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER,
    field TEXT, value TEXT, raw_text TEXT, evidence_type TEXT,
    source_role TEXT, inference TEXT, context_id TEXT
);
"""

# The columns v0.96.35 digested - what every Production candidate's stored
# digest was computed from when this release was deployed.
V09635_INPUT_COLUMNS = tuple(
    column for column in candidate_store.NORMALIZATION_INPUT_COLUMNS
    if column != "end_day_offset"
)

# Identity and every field the offset fix must leave exactly as it was.
PROTECTED_COLUMNS = (
    "event_id", "identity_key", "series_key", "event_date", "start_time",
    "end_time", "event_type", "genre_id", "venue_id", "venue_text", "region_id",
    "fee", "dj", "event_name", "canonical_event_id", "time_evidence",
)


class Store:
    """A throwaway engine SQLite store at the filename the runtime expects,
    each post also stored as a live-collected source item - an event nobody
    can trace to a live collection is never served (`normalization.source_of`),
    and the point here is what a reader is served."""

    def __init__(self, path, register=None):
        self.path = path
        self.register = register
        with self._open() as con:
            con.executescript(ENGINE_SCHEMA)

    @contextmanager
    def _open(self):
        con = sqlite3.connect(self.path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def add(self, candidate_id: int, *, name: str, event_date: str,
            start: str | None, end: str | None, offset: int | None,
            venue: str = "PISTA", event_type: str = "MILONGA") -> int:
        with self._open() as con:
            con.execute(
                "INSERT INTO raw_posts(post_id, source_id, source_url, title, body, "
                "  collected_at, cafe_name) VALUES (?,?,?,?,?,?,?)",
                (candidate_id, "SRC", f"https://example.test/v09636/{candidate_id}",
                 name, "body", "2026-10-17T00:00:00", "cafe"),
            )
            con.execute(
                "INSERT INTO event_candidates(candidate_id, post_id, name, event_type, "
                "  event_date, start_time, end_time, end_day_offset, venue, status, "
                "  core_complete) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (candidate_id, candidate_id, name, event_type, event_date, start, end,
                 offset, venue, "POSSIBLE", 1),
            )
        if self.register:
            self.register(f"https://example.test/v09636/{candidate_id}", name)
        return candidate_id

    def set_offset(self, candidate_id: int, offset: int) -> None:
        with self._open() as con:
            con.execute("UPDATE event_candidates SET end_day_offset = ? "
                        "WHERE candidate_id = ?", (offset, candidate_id))


@pytest.fixture
def store(env, monkeypatch, pg, unique) -> Store:
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-V09636-{unique}", name=f"v0.96.36 test {unique}",
        platform="WEB", source_role="COMMUNITY", url="https://example.test/v09636",
        enabled=False,
    )
    with pg.cursor() as cur:
        cur.execute("INSERT INTO source_collection_runs (source_id, mode, status) "
                    "VALUES (%s, 'live', 'PASS') RETURNING collection_run_id",
                    (source["source_id"],))
        run_id = cur.fetchone()[0]

    def register(url: str, title: str) -> None:
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO source_items (source_id, collection_run_id, external_id, "
                "  url, title, content_hash, ingest_state) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'INGESTED')",
                (source["source_id"], run_id, url, url, title, url),
            )

    monkeypatch.setenv("ENGINE_DATA_DIR", str(env / "engine-data"))
    return Store(env / "engine-data" / ENGINE_DB_FILENAME, register)


@pytest.fixture
def settings_for_store(store):
    from runtime.config import load_settings

    return load_settings()


@pytest.fixture
def run_normalization(pg, settings_for_store, monkeypatch):
    """`normalize_all()` into the `pg` fixture's transaction, prune disabled
    (a test must never be what decides a real event's candidate is gone)."""

    @contextmanager
    def _connect(_settings, **_kwargs):
        yield pg

    monkeypatch.setattr(db, "connect", _connect)
    monkeypatch.setattr(candidate_store, "all_candidate_ids", lambda *a, **kw: None)
    return lambda: normalization.normalize_all(settings_for_store, limit=None)


def _id(unique: str, n: int) -> int:
    return int(f"8{unique[-5:]}{n:02d}")


def _event(pg, candidate_id: int) -> dict:
    with pg.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE candidate_id = %s", (candidate_id,))
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    assert row is not None, f"candidate {candidate_id} produced no events row"
    return dict(zip(names, row))


def _served(pg, event_id: int, day: str) -> dict:
    found = [e for e in events_api.search(pg, on=day, limit=100)["events"]
             if e["id"] == event_id]
    assert len(found) == 1, f"event {event_id} is not served on {day}"
    return found[0]


def _stale(pg, settings, ids: set[int]) -> list[int]:
    inputs = [row for row in candidate_store.normalization_inputs(settings)
              if row["candidate_id"] in ids]
    stale, _ = normalization.select_stale(
        inputs, normalization.normalization_states(pg),
        normalization.review_markers(pg), ids, normalization.master_revision(pg))
    return stale


# The release's fixtures, each the shape of a real Production row.
CASES = [
    # name, date, start, end, engine offset, expected offset
    ("PISTA | 금요 밀롱가 (item 6239)", "2026-10-30", "20:00", "02:00", 1, 1),
    ("La Ventana | 소셜 (item 6388)", "2026-10-23", "20:00", "00:00", 1, 1),
    ("루미노소 선데이탱고", "2026-10-25", "14:00", "18:00", 0, 0),
    ("가또땅고 쁘롱가", "2026-10-22", "21:15", "23:15", 0, 0),
    ("저녁 밀롱가", "2026-10-24", "19:00", "23:00", 0, 0),
    ("자정 직전 종료", "2026-10-24", "20:00", "23:59", 0, 0),
    ("심야 밀롱가", "2026-10-24", "23:30", "04:30", 1, 1),
    ("자정 이후 시작", "2026-10-24", "00:30", "04:00", 0, 0),
    ("오전 강습", "2026-10-26", "10:00", "12:00", 0, 0),
]


@pytest.mark.parametrize("name,day,start,end,engine_offset,expected", CASES)
def test_the_engine_offset_reaches_the_event_and_the_api(
        run_normalization, pg, store, unique, name, day, start, end,
        engine_offset, expected):
    candidate_id = store.add(_id(unique, 1), name=f"{name} {unique}", event_date=day,
                             start=start, end=end, offset=engine_offset)
    run_normalization()

    event = _event(pg, candidate_id)
    assert event["end_day_offset"] == expected
    assert event["event_date"].isoformat() == day
    assert event["start_time"].strftime("%H:%M") == start
    assert event["end_time"].strftime("%H:%M") == end
    assert _served(pg, event["event_id"], day)["ends_next_day"] is bool(expected)


def test_the_offset_is_carried_never_derived_from_the_clocks(run_normalization, pg,
                                                             store, unique):
    """The engine had no offset to give (NULL) for a clock that reads as if it
    crosses midnight. normalization must not invent one: `end < start` is a
    guess about a clock the engine itself did not place."""
    candidate_id = store.add(_id(unique, 2), name=f"불완전 공지 {unique}",
                             event_date="2026-10-24", start="23:00", end="01:00",
                             offset=None)
    run_normalization()
    assert _event(pg, candidate_id)["end_day_offset"] == 0


def test_no_end_time_never_ends_the_next_day(run_normalization, pg, store, unique):
    candidate_id = store.add(_id(unique, 3), name=f"종료 미정 {unique}",
                             event_date="2026-10-24", start="20:00", end=None, offset=1)
    run_normalization()
    event = _event(pg, candidate_id)
    assert event["end_time"] is None
    assert event["end_day_offset"] == 0
    assert _served(pg, event["event_id"], "2026-10-24")["ends_next_day"] is False


def test_an_event_with_no_clock_at_all_is_untouched(run_normalization, pg, store, unique):
    candidate_id = store.add(_id(unique, 4), name=f"시각 없는 행사 {unique}",
                             event_date="2026-10-24", start=None, end=None, offset=None)
    run_normalization()
    event = _event(pg, candidate_id)
    assert (event["start_time"], event["end_time"], event["end_day_offset"]) == (None, None, 0)


def test_a_past_overnight_event_is_repaired_too(run_normalization, pg, store, unique):
    candidate_id = store.add(_id(unique, 5), name=f"지난 밤 {unique}",
                             event_date="2026-09-05", start="20:00", end="02:00", offset=1)
    run_normalization()
    assert _event(pg, candidate_id)["end_day_offset"] == 1


def test_the_signature_change_re_flows_a_row_built_without_the_column(
        run_normalization, pg, store, settings_for_store, unique, monkeypatch):
    """How the 317 Production rows are repaired: the official queue, not SQL.

    Build the row the way v0.96.35 did (the column absent from the SELECT and
    from the digest), then run the pass again with this release's columns.
    The candidate must be re-selected on its own - its digest moved - and the
    row updated in place: same event_id, same identity and series keys, same
    date and clocks, only the offset corrected. A further pass does nothing.
    """
    overnight = store.add(_id(unique, 6), name=f"Andante | cabeceo {unique}",
                          event_date="2026-10-24", start="17:00", end="00:00", offset=1)
    evening = store.add(_id(unique, 7), name=f"Andante | Alonga {unique}",
                        event_date="2026-10-25", start="14:00", end="18:00", offset=0)
    ours = {overnight, evening}

    with monkeypatch.context() as old:
        old.setattr(candidate_store, "NORMALIZATION_INPUT_COLUMNS", V09635_INPUT_COLUMNS)
        old.setattr(candidate_store, "_CANDIDATE_SELECT",
                    candidate_store._CANDIDATE_SELECT.replace("c.end_day_offset,", ""))
        run_normalization()
        before = {cid: _event(pg, cid) for cid in ours}
        assert before[overnight]["end_day_offset"] == 0, (
            "the fixture must reproduce v0.96.35's row, or this proves nothing")
        assert _stale(pg, settings_for_store, ours) == []

    assert set(_stale(pg, settings_for_store, ours)) == ours, (
        "the new column must move every digest, so the queue re-flows them")

    run_normalization()
    after = {cid: _event(pg, cid) for cid in ours}
    assert after[overnight]["end_day_offset"] == 1
    assert after[evening]["end_day_offset"] == 0
    for cid in ours:
        for column in PROTECTED_COLUMNS:
            assert after[cid][column] == before[cid][column], column
        assert after[cid]["listing_state"] == before[cid]["listing_state"]

    assert _stale(pg, settings_for_store, ours) == [], (
        "once repaired, the row is current and stays out of the queue")


def test_re_normalizing_keeps_a_fold_onto_its_canonical(
        run_normalization, pg, store, unique, monkeypatch, settings_for_store):
    """A folded overnight duplicate keeps its canonical when the offset is
    repaired - the upsert never writes canonical_event_id."""
    canonical = store.add(_id(unique, 10), name=f"Miltang 밀롱가 {unique}",
                          event_date="2026-10-24", start="20:00", end="02:00", offset=1)
    duplicate = store.add(_id(unique, 11), name=f"TangoNOW 밀롱가 {unique}",
                          event_date="2026-10-24", start="20:00", end="02:00", offset=1)
    with monkeypatch.context() as old:
        old.setattr(candidate_store, "NORMALIZATION_INPUT_COLUMNS", V09635_INPUT_COLUMNS)
        old.setattr(candidate_store, "_CANDIDATE_SELECT",
                    candidate_store._CANDIDATE_SELECT.replace("c.end_day_offset,", ""))
        run_normalization()
    canonical_id = _event(pg, canonical)["event_id"]
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET canonical_event_id = %s, listing_state = 'HIDDEN' "
                    "WHERE candidate_id = %s", (canonical_id, duplicate))

    run_normalization()
    assert _event(pg, canonical)["end_day_offset"] == 1
    folded = _event(pg, duplicate)
    assert folded["end_day_offset"] == 1
    assert folded["canonical_event_id"] == canonical_id
    served = [e["id"] for e in events_api.search(pg, on="2026-10-24", limit=100)["events"]]
    assert canonical_id in served and folded["event_id"] not in served


def test_an_engine_correction_of_the_offset_moves_the_digest(run_normalization, pg,
                                                             store, unique):
    """The offset is an input like any other: when a re-extract changes only
    it, the row follows on the next tick."""
    candidate_id = store.add(_id(unique, 8), name=f"재추출 {unique}",
                             event_date="2026-10-24", start="20:00", end="01:00", offset=0)
    run_normalization()
    assert _event(pg, candidate_id)["end_day_offset"] == 0
    store.set_offset(candidate_id, 1)
    built = run_normalization()
    assert built["updated"] >= 1
    assert _event(pg, candidate_id)["end_day_offset"] == 1


def test_the_public_json_says_the_night_ends_the_next_day(run_normalization, pg,
                                                          store, unique, monkeypatch):
    from runtime import app as app_module

    candidate_id = store.add(_id(unique, 9), name=f"OCHO | 그리셀밀롱가 {unique}",
                             event_date="2026-10-30", start="20:00", end="02:00", offset=1)
    run_normalization()
    event_id = _event(pg, candidate_id)["event_id"]

    monkeypatch.setattr(app_module, "_settings", None)
    client = TestClient(app_module.app, raise_server_exceptions=False)
    listed = client.get("/api/events", params={"date": "2026-10-30", "limit": 100})
    assert listed.status_code == 200
    mine = [e for e in listed.json()["events"] if e["id"] == event_id]
    assert len(mine) == 1
    assert (mine[0]["start_time"], mine[0]["end_time"], mine[0]["ends_next_day"]) == (
        "20:00", "02:00", True)
    detail = client.get(f"/api/events/{event_id}")
    assert detail.status_code == 200
    assert detail.json()["ends_next_day"] is True


# --- normalization's own rule, pure ----------------------------------------

def test_a_corrected_end_time_does_not_keep_the_engines_offset():
    """A person who rewrote the end clock wrote a clock the engine's offset
    does not describe; the row keeps the 0 it always had until they say."""
    candidate = {"end_day_offset": 1}
    assert normalization._end_day_offset(candidate, time(2, 0), set()) == 1
    assert normalization._end_day_offset(candidate, time(2, 0), {"end_time"}) == 0
    assert normalization._end_day_offset(candidate, time(2, 0), {"start_time"}) == 1
    assert normalization._end_day_offset(candidate, None, set()) == 0
    assert normalization._end_day_offset({}, time(2, 0), set()) == 0
    assert normalization._end_day_offset({"end_day_offset": None}, time(2, 0), set()) == 0


def test_both_projections_normalization_reads_carry_the_offset():
    """The two SELECTs a candidate reaches normalization through - the digest
    (`normalization_inputs()`) and the rows built (`candidates_by_id()`, via
    `_CANDIDATE_SELECT`). The review console's own `_SELECT_COLUMNS` reads no
    offset and builds no event, so it is deliberately left as it was."""
    import inspect

    assert "c.end_day_offset" in candidate_store._CANDIDATE_SELECT
    assert "c.end_day_offset" in inspect.getsource(candidate_store.normalization_inputs)
    assert "end_day_offset" in candidate_store.NORMALIZATION_INPUT_COLUMNS
