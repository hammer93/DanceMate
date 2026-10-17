"""v0.96.39 - what `time_evidence` says, and what `listing_state` says.

Part A. Measured on Production 0.96.38: 33 events carried an image URL in
`events.time_evidence`, a column whose values say how certain a time is
(EXPLICIT / UNAMBIGUOUS / PROPAGATED / ABSENT / HUMAN / NULL, migration 046).
The engine records a poster-read time with the image it came from in the
evidence row's `inference` - the pointer the Review page's Image Evidence
section reads - and the reading's own verdict in `value`
(`meridiem_evidence`, `ambiguous`). `candidates.time_evidence()` took
`inference` as the verdict. All 33 were `ambiguous: false` (the engine only
takes a poster time it can place), so `time_confirmed` was true and right;
the column was not.

Part B. Measured on Production 0.96.38: every folded event (142 of 142,
`canonical_event_id` set) read `listing_state = LISTED`. Every writer but one
keeps HIDDEN for a fold; the normalization upsert recomputed the column from
the review state alone, and the duplicate scan never revisits a row that is
already folded. Readers were not misled - each also requires
`canonical_event_id IS NULL` - but the column contradicted the fold.

Invariant: listing_state = HIDDEN  <=>  review state REJECTED/DUPLICATE, or
canonical_event_id IS NOT NULL.

Everything runs the real route: a throwaway engine SQLite store, the
runtime's SELECTs, `normalize_all()` and `duplicates.scan()` into the real
`events` table inside the `pg` fixture's rolled-back transaction.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import timedelta

import pytest

from runtime import candidates as candidate_store
from runtime import db, duplicates, events_api, master_data, normalization, review
from runtime import venue_resolution
from runtime.engine_adapter import ENGINE_DB_FILENAME

POSTER = "https://t1.daumcdn.net/cafeattach/1SvB/0123456789abcdef0123456789abcdef01234567"

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


def _reading(start, end, meridiem, ambiguous, offset=0):
    """`extraction_rules.TimeReading.as_dict()`'s shape."""
    return {"start": start, "end": end, "end_day_offset": offset,
            "meridiem_evidence": meridiem, "ambiguous": ambiguous}


# --- Part A: the verdict, read from the row ---------------------------------

def _verdict(inference, value):
    return candidate_store._time_evidence_value(
        {"inference": inference,
         "value": json.dumps(value) if isinstance(value, dict) else value})


@pytest.mark.parametrize("inference, value, expected", [
    # a post's own text: the verdict is `inference`, as before
    ("EXPLICIT", _reading("21:00", "00:00", "EXPLICIT", False, 1), "EXPLICIT"),
    ("ABSENT", _reading("14:00", "18:00", "ABSENT", False), "UNAMBIGUOUS"),
    ("ABSENT", _reading("08:00", "11:00", "ABSENT", True), "ABSENT"),
    ("PROPAGATED", _reading("09:00", "11:00", "PROPAGATED", False), "PROPAGATED"),
    # a poster's: `inference` is the image, the verdict is the reading's
    (POSTER, _reading("21:10", "00:00", "EXPLICIT", False, 1), "EXPLICIT"),
    (POSTER, _reading("20:00", "01:00", "ABSENT", False, 1), "UNAMBIGUOUS"),
    (POSTER, _reading("09:10", "12:00", "ABSENT", True), "ABSENT"),
    # nothing that says how certain the time is: not passed on as a verdict
    (POSTER, {"start": "21:00", "end": None}, None),
    (POSTER, "not json", None),
    ("SOMETHING_ELSE", _reading("21:00", None, "BOGUS", False), None),
    (None, {"start": "19:00", "end": "23:00"}, None),          # pre-v0.74 legacy row
    ("", None, None),
])
def test_the_verdict_is_read_from_the_reading_never_from_the_pointer(inference, value,
                                                                     expected):
    assert _verdict(inference, value) == expected


def test_no_verdict_is_ever_a_url():
    for meridiem in ("EXPLICIT", "ABSENT", "PROPAGATED"):
        for ambiguous in (True, False):
            got = _verdict(POSTER, _reading("21:00", None, meridiem, ambiguous))
            assert got in candidate_store.ENGINE_MERIDIEM_VERDICTS | {"UNAMBIGUOUS"}


# --- the real route -----------------------------------------------------------

class Store:
    """A throwaway engine store; each post also stored as a live-collected
    source item, so what a reader is served can be asked."""

    def __init__(self, path, register):
        self.path = path
        self.register = register
        path.parent.mkdir(parents=True, exist_ok=True)
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

    def add(self, candidate_id: int, *, name: str, day: str, start: str | None,
            end: str | None = None, offset: int = 0, venue: str = "PISTA",
            status: str = "POSSIBLE", times: tuple | list = ()) -> int:
        """``times``: (evidence_type, inference, reading) rows, in order."""
        url = f"https://example.test/v09639/{candidate_id}"
        with self._open() as con:
            con.execute("INSERT INTO raw_posts VALUES (?,?,?,?,?,?,?)",
                        (candidate_id, "SRC", url, name, "body", "2026-10-18T00:00:00",
                         "cafe"))
            con.execute(
                "INSERT INTO event_candidates(candidate_id, post_id, name, event_type, "
                "  event_date, start_time, end_time, end_day_offset, venue, status, "
                "  core_complete) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (candidate_id, candidate_id, name, "MILONGA", day, start, end, offset,
                 venue, status, 1))
            for evidence_type, inference, reading in times:
                con.execute(
                    "INSERT INTO evidences(candidate_id, field, value, raw_text, "
                    "  evidence_type, inference) VALUES (?, 'time', ?, ?, ?, ?)",
                    (candidate_id, json.dumps(reading), "raw", evidence_type, inference))
                if evidence_type == "IMAGE_OCR":
                    con.execute(
                        "INSERT INTO evidences(candidate_id, field, value, raw_text, "
                        "  evidence_type, inference) VALUES (?, 'date', ?, ?, ?, ?)",
                        (candidate_id, day, day, evidence_type, inference))
        self.register(url, name)
        return candidate_id


@pytest.fixture
def store(env, monkeypatch, pg, unique) -> Store:
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-V09639-{unique}", name=f"v0.96.39 test {unique}",
        platform="WEB", source_role="COMMUNITY", url="https://example.test/v09639",
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
                (source["source_id"], run_id, url, url, title, url))

    monkeypatch.setenv("ENGINE_DATA_DIR", str(env / "engine-data"))
    return Store(env / "engine-data" / ENGINE_DB_FILENAME, register)


@pytest.fixture
def settings(store):
    from runtime.config import load_settings

    return load_settings()


@pytest.fixture
def run_normalization(pg, settings, monkeypatch):
    """`normalize_all()` into the `pg` transaction, prune disabled. ``again()``
    re-flows every candidate, as a NORMALIZATION_VERSION bump does."""

    @contextmanager
    def _connect(_settings, **_kwargs):
        yield pg

    monkeypatch.setattr(db, "connect", _connect)
    monkeypatch.setattr(candidate_store, "all_candidate_ids", lambda *a, **kw: None)
    passes = {"n": 0}

    def run():
        return normalization.normalize_all(settings, limit=None)

    def again():
        passes["n"] += 1
        monkeypatch.setattr(normalization, "NORMALIZATION_VERSION", f"test-{passes['n']}")
        return run()

    run.again = again
    return run


def _id(unique: str, n: int) -> int:
    return int(f"7{unique[-5:]}{n:02d}")


def _event(pg, candidate_id: int) -> dict:
    with pg.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE candidate_id = %s", (candidate_id,))
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    assert row is not None, f"candidate {candidate_id} produced no events row"
    return dict(zip(names, row))


def _day(n: int = 10) -> str:
    return (events_api.today() + timedelta(days=n)).isoformat()


def _api(pg, event_id: int, day: str) -> dict | None:
    found = [e for e in events_api.search(pg, on=day, limit=100)["events"]
             if e["id"] == event_id]
    return found[0] if found else None


def _clock(value) -> str | None:
    return str(value)[:5] if value is not None else None


TIME_CASES = [
    # name, start, end, offset, evidence rows, expected time_evidence, time_confirmed
    ("explicit 24-hour", "14:00", "18:00", 0,
     [("TEXT", "ABSENT", _reading("14:00", "18:00", "ABSENT", False))], "UNAMBIGUOUS", True),
    ("explicit pm", "21:00", "00:00", 1,
     [("TEXT", "EXPLICIT", _reading("21:00", "00:00", "EXPLICIT", False, 1))],
     "EXPLICIT", True),
    # item 2282's poster: "저녁 9:10 ~ 12:00"
    ("poster pm", "21:10", "00:00", 1,
     [("IMAGE_OCR", POSTER, _reading("21:10", "00:00", "EXPLICIT", False, 1))],
     "EXPLICIT", True),
    # item 1329's poster: "20:00 - 01:00"
    ("poster 24-hour", "20:00", "01:00", 1,
     [("IMAGE_OCR", POSTER, _reading("20:00", "01:00", "ABSENT", False, 1))],
     "UNAMBIGUOUS", True),
    # a bare poster clock the engine did not place (it does not take one; if it
    # ever did, this is what the column must say)
    ("poster ambiguous", "09:10", "12:00", 0,
     [("IMAGE_OCR", POSTER, _reading("09:10", "12:00", "ABSENT", True))], "ABSENT", False),
    ("bare clock", "08:00", "11:00", 0,
     [("TEXT", "ABSENT", _reading("08:00", "11:00", "ABSENT", True))], "ABSENT", False),
    # pre-v0.74 rows: a time, no verdict (Production: 10, provenance UNKNOWN)
    ("legacy", "19:00", "23:00", 0,
     [("TEXT", None, {"start": "19:00", "end": "23:00"})], None, True),
    ("no evidence row", "20:00", None, 0, [], None, True),
    ("no time", None, None, 0, [], None, None),
    # the post's own text first, then a later reading: the last row wins, as
    # before, and it is a verdict either way
    ("two readings", "21:00", "00:00", 1,
     [("TEXT", "ABSENT", _reading("21:00", "00:00", "ABSENT", False, 1)),
      ("IMAGE_OCR", POSTER, _reading("21:00", "00:00", "EXPLICIT", False, 1))],
     "EXPLICIT", True),
]


def test_time_evidence_semantics_through_normalization(pg, store, run_normalization, unique):
    day = _day()
    ids = {}
    for n, (name, start, end, offset, times, _, _) in enumerate(TIME_CASES):
        ids[name] = store.add(_id(unique, n), name=f"{name} {unique}", day=day, start=start,
                              end=end, offset=offset, venue=f"홀 {name} {unique}",
                              times=times)
    run_normalization()
    for name, start, end, offset, _, expected, confirmed in TIME_CASES:
        event = _event(pg, ids[name])
        assert event["time_evidence"] == expected, name
        assert _clock(event["start_time"]) == start, name
        assert _clock(event["end_time"]) == end, name
        assert event["end_day_offset"] == offset, name
        served = _api(pg, event["event_id"], day)
        assert served is not None, name
        assert served["time_confirmed"] is confirmed, name


def test_a_poster_time_keeps_its_image_and_its_values(pg, store, run_normalization, unique,
                                                      settings, monkeypatch):
    """The fixture reproduces 0.96.38's row, then the fix changes the verdict
    column and nothing else; the image stays the evidence the Review page
    shows."""
    day = _day()
    cid = store.add(_id(unique, 40), name=f"Poster Social {unique}", day=day,
                    start="21:10", end="00:00", offset=1, venue=f"홀 포스터 {unique}",
                    times=[("IMAGE_OCR", POSTER,
                            _reading("21:10", "00:00", "EXPLICIT", False, 1))])
    with monkeypatch.context() as old:
        old.setattr(candidate_store, "_time_evidence_value", lambda row: row["inference"])
        run_normalization()
    before = _event(pg, cid)
    assert before["time_evidence"] == POSTER, "the fixture must reproduce 0.96.38's row"
    before_api = _api(pg, before["event_id"], day)
    assert before_api["time_confirmed"] is True

    run_normalization.again()
    after = _event(pg, cid)
    assert after["time_evidence"] == "EXPLICIT"
    unchanged = ("event_id", "identity_key", "series_key", "event_date", "start_time",
                 "end_time", "end_day_offset", "venue_id", "venue_text", "region_id",
                 "canonical_event_id", "listing_state", "event_type", "genre_id")
    assert {k: after[k] for k in unchanged} == {k: before[k] for k in unchanged}
    assert _api(pg, after["event_id"], day) == before_api   # the reader is served the same

    image = candidate_store.image_ocr_fields(settings, cid)
    assert {(r["field"], r["inference"]) for r in image} == {("time", POSTER),
                                                             ("date", POSTER)}


def test_a_cancelled_night_keeps_its_poster_verdict(pg, store, run_normalization, unique):
    cid = store.add(_id(unique, 41), name=f"휴강 Social {unique}", day=_day(), start="21:00",
                    end="00:00", offset=1, venue=f"홀 휴강 {unique}", status="CANCELLED",
                    times=[("IMAGE_OCR", POSTER,
                            _reading("21:00", "00:00", "EXPLICIT", False, 1))])
    run_normalization()
    event = _event(pg, cid)
    assert event["engine_status"] == "CANCELLED"
    assert event["time_evidence"] == "EXPLICIT"


def test_a_corrected_time_is_still_the_persons(pg, store, run_normalization, unique):
    cid = store.add(_id(unique, 42), name=f"Edited {unique}", day=_day(), start="21:00",
                    venue=f"홀 수정 {unique}",
                    times=[("IMAGE_OCR", POSTER, _reading("21:00", None, "EXPLICIT", False))])
    run_normalization()
    review.record(pg, candidate_id=cid, action=review.EDIT,
                  before={"start_time": "21:00"}, after={"start_time": "20:30"})
    run_normalization()
    event = _event(pg, cid)
    assert _clock(event["start_time"]) == "20:30" and event["time_evidence"] == "HUMAN"


# --- Part B: a fold stays HIDDEN ---------------------------------------------

def _consistent(pg, candidate_ids) -> None:
    """The invariant, row by row."""
    with pg.cursor() as cur:
        cur.execute("SELECT event_id, listing_state, review_state, canonical_event_id "
                    "FROM events WHERE candidate_id = ANY(%s)", (list(candidate_ids),))
        rows = cur.fetchall()
    assert len(rows) == len(candidate_ids)
    for event_id, listing, state, canonical in rows:
        hidden = state in normalization.UNLISTABLE_REVIEW_STATES or canonical is not None
        assert listing == ("HIDDEN" if hidden else "LISTED"), (event_id, listing, state,
                                                                 canonical)


def _snapshot(pg, candidate_ids) -> dict:
    """candidate -> (event_id, identity_key, series_key, canonical_event_id,
    listing_state, duplicate_decided_by, venue_id)"""
    with pg.cursor() as cur:
        cur.execute("SELECT candidate_id, event_id, identity_key, series_key, "
                    "  canonical_event_id, listing_state, duplicate_decided_by, venue_id "
                    "FROM events WHERE candidate_id = ANY(%s)", (list(candidate_ids),))
        return {r[0]: r[1:] for r in cur.fetchall()}


def _decisions(pg) -> int:
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_duplicate_decisions")
        return cur.fetchone()[0]


@pytest.fixture
def venue(pg, unique, seoul_id):
    return master_data.create_venue(pg, name=f"Pasion Hall {unique}", region_id=seoul_id)


@pytest.fixture
def twins(pg, store, run_normalization, unique, venue):
    """Two posts of one afternoon practica at a resolved venue: the scan's
    SAME_DATE_VENUE_TIME fold, the shape of 1614475/1617066 on the Production
    clone (one weekday 15:00 practica, posted twice)."""
    day = _day(4)
    first = store.add(_id(unique, 50), name=f"평일 낮쁘락 {unique}", day=day, start="15:00",
                      end="18:00", venue=venue["name"])
    second = store.add(_id(unique, 51), name=f"낮쁘락 Pasion {unique}", day=day,
                       start="15:00", end="18:00", venue=venue["name"])
    run_normalization()
    duplicates.scan(pg, on=day)
    a, b = _event(pg, first), _event(pg, second)
    folded = a if a["canonical_event_id"] else b
    canonical = b if folded is a else a
    assert folded["canonical_event_id"] == canonical["event_id"]
    assert folded["duplicate_decided_by"] == duplicates.AUTO
    assert folded["listing_state"] == "HIDDEN"
    return {"ids": [first, second], "day": day, "folded": folded["candidate_id"],
            "canonical": canonical["candidate_id"]}


class _Undo(Exception):
    pass


def test_reproduced_a_re_normalized_fold_read_listed(pg, twins, run_normalization,
                                                     monkeypatch):
    """0.96.38's upsert, inside a savepoint: the fold is kept, its listing is
    rewritten from the review state alone - and the scan does not put it back."""
    with pytest.raises(_Undo):
        with pg.transaction():
            with monkeypatch.context() as old:
                old.setattr(normalization, "_FOLDED_STAYS_HIDDEN", "EXCLUDED.listing_state")
                run_normalization.again()
            folded = _event(pg, twins["folded"])
            assert folded["canonical_event_id"] is not None
            assert folded["listing_state"] == "LISTED"
            duplicates.scan(pg, on=twins["day"])
            assert _event(pg, twins["folded"])["listing_state"] == "LISTED"
            raise _Undo
    _consistent(pg, twins["ids"])


def test_a_fold_stays_hidden_through_normalization_and_scan(pg, twins, run_normalization):
    settled = _snapshot(pg, twins["ids"])
    for _ in range(2):
        run_normalization.again()
        _consistent(pg, twins["ids"])
        duplicates.scan(pg, on=twins["day"])
        _consistent(pg, twins["ids"])
        assert _snapshot(pg, twins["ids"]) == settled
    served = [e["id"] for e in events_api.search(pg, on=twins["day"], limit=100)["events"]]
    assert _event(pg, twins["canonical"])["event_id"] in served
    assert _event(pg, twins["folded"])["event_id"] not in served


def test_normalize_scan_normalize_scan_is_idempotent(pg, store, run_normalization, unique,
                                                     twins):
    alone = store.add(_id(unique, 52), name=f"Standalone {unique}", day=twins["day"],
                      start="21:00", venue=f"홀 단독 {unique}")
    ids = twins["ids"] + [alone]
    run_normalization()
    duplicates.scan(pg, on=twins["day"])
    settled, decided = _snapshot(pg, ids), _decisions(pg)
    for _ in range(2):
        run_normalization.again()
        found = duplicates.scan(pg, on=twins["day"])
        assert found["auto_merged"] == 0 and found["released"] == 0
        assert _snapshot(pg, ids) == settled
        _consistent(pg, ids)
    assert _decisions(pg) == decided
    assert _event(pg, alone)["listing_state"] == "LISTED"


def test_a_new_event_is_listed_and_a_rejected_one_hidden(pg, store, run_normalization,
                                                          unique):
    day = _day()
    new = store.add(_id(unique, 60), name=f"New {unique}", day=day, start="21:00",
                    venue=f"홀 신규 {unique}")
    rejected = store.add(_id(unique, 61), name=f"Rejected {unique}", day=day,
                         start="20:00", venue=f"홀 반려 {unique}")
    run_normalization()
    assert _event(pg, new)["listing_state"] == "LISTED"
    review.record(pg, candidate_id=rejected, action=review.REJECT, reason="test")
    run_normalization()
    assert _event(pg, rejected)["listing_state"] == "HIDDEN"
    run_normalization.again()
    assert _event(pg, rejected)["listing_state"] == "HIDDEN"
    _consistent(pg, [new, rejected])


def _human_pair(pg, store, run_normalization, unique, venue):
    """Same night, same venue, two clocks: a pair only a person settles."""
    day = _day(5)
    left = store.add(_id(unique, 70), name=f"Human A {unique}", day=day, start="20:00",
                     venue=venue["name"])
    right = store.add(_id(unique, 71), name=f"Human B {unique}", day=day, start="21:00",
                      venue=venue["name"])
    run_normalization()
    duplicates.scan(pg, on=day)
    a, b = _event(pg, left), _event(pg, right)
    with pg.cursor() as cur:
        cur.execute("SELECT pair_id FROM event_duplicate_pairs WHERE event_id = %s "
                    "AND other_event_id = %s",
                    tuple(sorted((a["event_id"], b["event_id"]))))
        pair_id = cur.fetchone()[0]
    return day, [left, right], pair_id, a


def test_a_persons_merge_stays_hidden_and_stays_a_merge(pg, store, run_normalization,
                                                        unique, venue):
    day, ids, pair_id, a = _human_pair(pg, store, run_normalization, unique, venue)
    duplicates.resolve_pair(pg, pair_id, decision=duplicates.DUPLICATE, reviewer="operator",
                            canonical_event_id=a["event_id"], reason="one night")
    settled = _snapshot(pg, ids)
    for _ in range(2):
        run_normalization.again()
        duplicates.scan(pg, on=day)
        assert _snapshot(pg, ids) == settled
        _consistent(pg, ids)
    folded = [v for v in settled.values() if v[3] is not None]
    assert len(folded) == 1
    assert folded[0][4] == "HIDDEN" and folded[0][5] == duplicates.HUMAN


def test_a_persons_keep_separate_stays_listed(pg, store, run_normalization, unique, venue):
    day, ids, pair_id, _ = _human_pair(pg, store, run_normalization, unique, venue)
    duplicates.resolve_pair(pg, pair_id, decision=duplicates.DISTINCT, reviewer="operator",
                            reason="two parties")
    for _ in range(2):
        run_normalization.again()
        duplicates.scan(pg, on=day)
        snap = _snapshot(pg, ids)
        assert all(v[3] is None and v[4] == "LISTED" and v[5] == duplicates.HUMAN
                   for v in snap.values())


def test_venue_approval_fold_and_its_revert_keep_the_invariant(pg, store, run_normalization,
                                                                unique, settings, seoul_id):
    """The clone's Tango Pasion case end to end: two posts of one 15:00
    practica at a string nobody has resolved are only a question; New Venue
    resolves them, the scan folds them, the next normalization (the alias
    moved the master revision) keeps the fold HIDDEN; the Revert releases it,
    and normalization and the scan afterwards leave both listed."""
    text = f"탱고 파시온 {unique} (서울 마포구 월드컵북로6길 69)"
    day = _day(3)
    ids = [store.add(_id(unique, 80), name=f"평일 낮쁘락 {unique}", day=day, start="15:00",
                     venue=text),
           store.add(_id(unique, 81), name=f"Pasion 낮쁘락 {unique}", day=day,
                     start="15:00", venue=text)]
    run_normalization()
    duplicates.scan(pg, on=day)
    assert all(v[3] is None and v[4] == "LISTED" for v in _snapshot(pg, ids).values())
    with pg.cursor() as cur:
        cur.execute("SELECT unresolved_venue_id FROM unresolved_venues "
                    "WHERE normalized_text = %s", (master_data.normalize_alias(text),))
        uid = cur.fetchone()[0]
    name = f"Tango Pasion {unique}"
    preview = venue_resolution.preview_create(pg, unresolved_venue_id=uid, name=name,
                                              region_id=seoul_id, settings=settings)
    assert preview["blockers"] == []
    venue_resolution.confirm_create(pg, unresolved_venue_id=uid, name=name,
                                    region_id=seoul_id, token=preview["token"],
                                    settings=settings)
    run_normalization()
    duplicates.scan(pg, on=day)
    approved = _snapshot(pg, ids)
    assert sum(v[3] is not None for v in approved.values()) == 1
    _consistent(pg, ids)
    run_normalization.again()
    duplicates.scan(pg, on=day)
    assert _snapshot(pg, ids) == approved
    _consistent(pg, ids)

    back = venue_resolution.preview_revert(pg, unresolved_venue_id=uid, settings=settings)
    assert back["blockers"] == [] and back["summary"]["released_folds"] == 1
    venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"],
                                     settings=settings, reason="test")
    _consistent(pg, ids)
    for _ in range(2):
        run_normalization.again()
        duplicates.scan(pg, on=day)
        assert all(v[3] is None and v[4] == "LISTED" for v in _snapshot(pg, ids).values())
        _consistent(pg, ids)


def test_rows_built_by_the_previous_version_are_rebuilt_once(pg, store, run_normalization,
                                                             unique):
    """The convergence path: the candidates' inputs did not move, so only the
    NORMALIZATION_VERSION bump reaches rows 0.96.38 built - and once rebuilt
    they leave the queue."""
    cid = store.add(_id(unique, 90), name=f"Queue {unique}", day=_day(), start="21:00",
                    venue=f"홀 큐 {unique}",
                    times=[("IMAGE_OCR", POSTER, _reading("21:00", None, "EXPLICIT", False))])
    run_normalization()
    assert normalization.NORMALIZATION_VERSION == "2"
    with pg.cursor() as cur:
        cur.execute("UPDATE candidate_normalization SET normalization_version = '1' "
                    "WHERE candidate_id = %s", (cid,))
    first = run_normalization()
    assert first["selected"] >= 1 and first["updated"] >= 1
    assert run_normalization()["selected"] == 0
