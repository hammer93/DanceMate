"""v0.96.6 - incremental, restart-safe event normalization.

The problem this release exists for, measured on Production c34ee25: the
engine store held 1,264 candidates and `normalize_all()` read
`list_candidates(limit=500)`, which is "the newest 500 posts by
`raw_posts.collected_at`". 764 candidates were therefore outside every
scheduler tick's reach, permanently - not because anything about them was
wrong, but because of when they had been collected. Eighteen dated candidates
had no `events` row at all, and nine of those were real upcoming nights on the
day they were collected:

    2800  2026-09-19 20:15  스윙타임빠 소셜        2113  2026-09-12 20:15  스윙타임빠 소셜
    2334  2026-09-19 19:30  부산탱고 La Vida       1264  2026-09-10 20:00  milonga_tu
    1311  2026-09-17 20:00  milonga_tu            1334  2026-09-09       Korea Special Tango Week
    1976  2026-09-08 15:00  Milonga Dorada         623  2026-09-05 20:15  스윙타임빠 소셜
       2  2026-09-05 19:00  대구 낭만밀롱가

Eight of the twelve candidates v0.96.5 rescued are in that list. The
classifier fix worked; the window ate the result.

Raising the limit moves the cliff, and removing it re-normalises every
candidate on every tick forever. The fix is the same shape as v0.96.3's:
the DB row is the cursor. `candidate_normalization` records the digest of the
inputs behind each candidate's current events row, so the queue is "the
candidates whose inputs are not those" - which a stamped candidate leaves for
good, which a changed candidate re-enters on its own, and which a restart
re-derives exactly rather than losing.

What each section below proves, against the release brief's T1-T12:

  T1/T2/T7  a candidate outside the old window is selected, and the old
            selection is reproduced here to show it was not
  T3/T12    successive batches take different candidates until none are left
  T4        the queue survives a restart, because it is a pure function of
            DB state
  T5/T6     a current candidate is not re-selected; a changed one is
  T8        one candidate that raises does not wedge the queue
  T9/T10/T11 re-normalising keeps the event id, the canonical folding and
            the review state, because it is still the same upsert

The selection tests are pure: `select_stale()` takes DB state as arguments
and returns ids, so they need no database at all. The stamping tests use the
`pg` fixture's rolled-back transaction. The end-to-end tests drive
`normalize_all()` itself with `db.connect` redirected into that same
transaction - and with `all_candidate_ids()` made unreadable, so
`_prune_orphans()` prunes nothing: a test must never be the thing that
decides a real event no longer exists (the v0.82.2 safety rule that keeps
every other test file from calling `normalize_all()` at all).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from runtime import candidates as candidate_store
from runtime import db, normalization
from runtime.engine_adapter import ENGINE_DB_FILENAME

VERSION = normalization.NORMALIZATION_VERSION
OLD_VERSION = "0"


# --- the engine store a normalization pass reads ----------------------------

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


class Store:
    """A throwaway engine SQLite store at the filename the runtime expects."""

    def __init__(self, path):
        self.path = path
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

    def add(self, candidate_id: int, *, collected_at: str,
            event_date: str | None = "2026-09-19", name: str | None = None,
            venue: str = "PISTA", url: str | None = None) -> int:
        """One candidate and the post behind it. `collected_at` is the whole
        point: it is what the pre-v0.96.6 window ordered and cut on."""
        with self._open() as con:
            con.execute(
                "INSERT INTO raw_posts(post_id, source_id, source_url, title, "
                "  body, collected_at, cafe_name) VALUES (?,?,?,?,?,?,?)",
                (candidate_id, "SRC", url or f"https://example.test/{candidate_id}",
                 f"post {candidate_id}", "body", collected_at, "cafe"),
            )
            con.execute(
                "INSERT INTO event_candidates(candidate_id, post_id, name, "
                "  event_type, event_date, start_time, venue, status, core_complete) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (candidate_id, candidate_id, name or f"Milonga {candidate_id}",
                 "MILONGA", event_date, "20:00", venue, "POSSIBLE", 1),
            )
        return candidate_id

    def re_extract(self, candidate_id: int, *, event_date: str) -> None:
        """What v0.96.0 `replace_candidate()` does: the same candidate_id, new
        values, new evidence rows. The id being stable is exactly why the
        queue cannot be keyed on "candidate ids we have not seen"."""
        with self._open() as con:
            con.execute("UPDATE event_candidates SET event_date = ? "
                        "WHERE candidate_id = ?", (event_date, candidate_id))
            con.execute("DELETE FROM evidences WHERE candidate_id = ?", (candidate_id,))
            con.execute(
                "INSERT INTO evidences(candidate_id, field, value, raw_text) "
                "VALUES (?, 'date', ?, ?)", (candidate_id, event_date, event_date),
            )


@pytest.fixture
def store(env, monkeypatch) -> Store:
    monkeypatch.setenv("ENGINE_DATA_DIR", str(env / "engine-data"))
    return Store(env / "engine-data" / ENGINE_DB_FILENAME)


@pytest.fixture
def engine_settings_for_store(store):
    from runtime.config import load_settings

    return load_settings()


def _day(offset: int) -> str:
    return (date(2026, 9, 20) - timedelta(days=offset)).isoformat() + "T00:00:00"


def _inputs(settings) -> list[dict]:
    rows = candidate_store.normalization_inputs(settings)
    assert rows is not None, "the throwaway engine store should be readable"
    return rows


def _state(digest: str, *, outcome: str = normalization.NORMALIZED,
           version: str = VERSION, attempts: int = 0) -> dict:
    return {"input_digest": digest, "normalization_version": version,
            "outcome": outcome, "attempts": attempts}


# --- T1/T2/T7: the window starved candidates the new selection reaches ------

def test_the_old_window_cannot_see_an_older_candidate_at_all(engine_settings_for_store,
                                                             store):
    """T1. The starvation, reproduced against the code that caused it.

    700 candidates, the oldest collected first. `list_candidates(limit=500)`
    is what `normalize_all()` used to read, and candidate 1 is not in it - not
    ranked low, not deferred to a later tick, simply absent from every tick
    forever.
    """
    for candidate_id in range(1, 701):
        store.add(candidate_id, collected_at=_day(701 - candidate_id))

    window = candidate_store.list_candidates(engine_settings_for_store, limit=500)
    assert len(window) == 500
    assert 1 not in {row["candidate_id"] for row in window}, (
        "the fixture must put candidate 1 outside the old 500-row window, "
        "or this file is not testing the bug"
    )

    stale, _ = normalization.select_stale(
        _inputs(engine_settings_for_store), {}, {}, set())
    assert len(stale) == 700
    assert 1 in stale, (
        "v0.96.6: normalization selects the candidates that need building, "
        "not the ones that happen to have been collected recently"
    )


def test_an_old_dated_candidate_with_no_event_is_selected(engine_settings_for_store,
                                                          store):
    """T2/T7. The nine Production samples, in the shape they had on the board:
    a dated candidate, collected weeks ago, with no events row."""
    for candidate_id in range(1, 601):
        store.add(candidate_id, collected_at=_day(1))
    starved = store.add(2800, collected_at=_day(400), event_date="2026-09-19")

    inputs = _inputs(engine_settings_for_store)
    # Everything else is already current, so the only thing queued is the one
    # candidate the window used to hide.
    states = {row["candidate_id"]: _state(
        normalization.input_digest(row, "")) for row in inputs
        if row["candidate_id"] != starved}
    with_event = set(states)

    stale, _ = normalization.select_stale(inputs, states, {}, with_event)
    assert stale == [starved]


# --- T3/T12: batches advance instead of repeating ---------------------------

def test_successive_batches_take_different_candidates_until_none_are_left(
        engine_settings_for_store, store):
    """T3/T12. 260 candidates, batch 100: 100, 100, 60, 0 - each batch new.

    The stamping is simulated in-memory here (the DB round trip has its own
    test below); what this proves is that the *selection* advances, which the
    forced re-extract pass of v0.96.3 famously did not.
    """
    for candidate_id in range(1, 261):
        store.add(candidate_id, collected_at=_day(candidate_id))

    inputs = _inputs(engine_settings_for_store)
    states: dict[int, dict] = {}
    seen: list[int] = []
    sizes = []
    for _ in range(4):
        stale, digests = normalization.select_stale(inputs, states, {}, set(states))
        batch = stale[:100]
        sizes.append(len(batch))
        seen += batch
        for candidate_id in batch:
            states[candidate_id] = _state(digests[candidate_id])

    assert sizes == [100, 100, 60, 0]
    assert len(set(seen)) == len(seen) == 260, (
        "a candidate selected once and stamped must never be selected again"
    )


def test_a_batch_that_is_not_stamped_is_offered_again(engine_settings_for_store, store):
    """The other half of T12: the batch limit bounds the work, and nothing
    else. Work that was not recorded is still owed."""
    for candidate_id in range(1, 11):
        store.add(candidate_id, collected_at=_day(candidate_id))

    inputs = _inputs(engine_settings_for_store)
    first, _ = normalization.select_stale(inputs, {}, {}, set())
    again, _ = normalization.select_stale(inputs, {}, {}, set())
    assert first[:5] == again[:5]


# --- T4: restart-safe -------------------------------------------------------

def test_the_queue_survives_a_restart_because_it_is_derived_not_remembered(
        pg, engine_settings_for_store, store, unique):
    """T4. Stamp one batch, throw away everything in memory, and ask again.

    "Throw away everything in memory" is literal: the second selection is
    computed from a fresh read of `candidate_normalization`, which is all a
    restarted process would have. It resumes at candidate 4, not candidate 1.
    """
    for candidate_id in range(1, 7):
        store.add(_id(unique, candidate_id), collected_at=_day(candidate_id))

    inputs = _inputs(engine_settings_for_store)
    ours = [row["candidate_id"] for row in inputs]

    stale, digests = normalization.select_stale(inputs, {}, {}, set())
    for candidate_id in stale[:3]:
        normalization._stamp(pg, candidate_id, digests[candidate_id],
                             outcome=normalization.NORMALIZED)

    # A restarted scheduler knows nothing but the database.
    resumed, _ = normalization.select_stale(
        inputs, _ours(normalization.normalization_states(pg), ours), {}, set(ours[:3]))
    assert resumed == stale[3:]
    assert not set(resumed) & set(stale[:3])


# --- T5/T6: current candidates rest, changed ones come back -----------------

def test_a_current_candidate_is_not_selected_again(pg, engine_settings_for_store,
                                                   store, unique):
    """T5. The whole reason this can run every five minutes over a store that
    only ever grows."""
    candidate_id = store.add(_id(unique, 1), collected_at=_day(90))
    inputs = _inputs(engine_settings_for_store)
    digest = normalization.input_digest(inputs[0], "")
    normalization._stamp(pg, candidate_id, digest, outcome=normalization.NORMALIZED,
                         event_id=1)

    stale, _ = normalization.select_stale(
        inputs, _ours(normalization.normalization_states(pg), [candidate_id]),
        {}, {candidate_id})
    assert stale == []


def test_a_re_extracted_candidate_comes_back_even_though_its_id_did_not_change(
        pg, engine_settings_for_store, store, unique):
    """T6. v0.96.0 re-extraction rewrites a candidate *in place* to keep its
    event id, so "ids we have not seen" would miss every one of them. The
    digest is over the values, so it does not."""
    candidate_id = store.add(_id(unique, 1), collected_at=_day(90),
                             event_date="2026-09-19")
    before = _inputs(engine_settings_for_store)
    normalization._stamp(pg, candidate_id, normalization.input_digest(before[0], ""),
                         outcome=normalization.NORMALIZED, event_id=1)

    store.re_extract(candidate_id, event_date="2026-09-26")
    after = _inputs(engine_settings_for_store)
    assert after[0]["candidate_id"] == candidate_id

    stale, _ = normalization.select_stale(
        after, _ours(normalization.normalization_states(pg), [candidate_id]),
        {}, {candidate_id})
    assert stale == [candidate_id]


def test_a_reviewed_candidate_comes_back_although_the_engine_store_is_unchanged():
    """T6, the runtime half. An EDIT changes the event without touching the
    engine store at all, so the review marker is part of the digest."""
    row = {"candidate_id": 7, "event_name": "Milonga", "event_date": "2026-09-19"}
    before = normalization.input_digest(row, "")
    after = normalization.input_digest(row, "1@2026-09-20T10:00:00+00:00")
    assert before != after

    state = _state(before)
    assert not normalization.needs_normalization(state, before, has_event=True)
    assert normalization.needs_normalization(state, after, has_event=True)


def test_a_dateless_candidate_is_answered_once_not_every_tick():
    """NO_DATE is a durable answer. Without it the several hundred candidates
    that carry no readable date would fill the head of the queue forever and
    nothing behind them would ever be built."""
    state = _state("d", outcome=normalization.NO_DATE)
    assert not normalization.needs_normalization(state, "d", has_event=False)
    assert normalization.needs_normalization(state, "changed", has_event=False)


def test_a_normalization_version_bump_re_flows_the_whole_store():
    """The escape hatch for a change in normalization itself, drained by the
    ordinary batches rather than a one-off pass over everything."""
    state = _state("d", version=OLD_VERSION)
    assert normalization.needs_normalization(state, "d", has_event=True)


def test_an_event_that_has_gone_missing_is_rebuilt():
    """We recorded an events row and there is not one. Whatever removed it,
    the candidate is owed its event back."""
    state = _state("d")
    assert normalization.needs_normalization(state, "d", has_event=False)
    assert not normalization.needs_normalization(state, "d", has_event=True)


# --- T8: a failure cannot wedge the queue -----------------------------------

def test_a_failing_candidate_steps_aside_and_stays_visible(pg, engine_settings_for_store,
                                                           store, unique):
    """T8. Retried, then set down with its reason still readable - never
    retried forever at the head of the queue, and never silently dropped."""
    candidate_id = store.add(_id(unique, 1), collected_at=_day(90))
    inputs = _inputs(engine_settings_for_store)
    digest = normalization.input_digest(inputs[0], "")

    for attempt in range(1, normalization.MAX_NORMALIZATION_ATTEMPTS + 1):
        normalization._stamp(pg, candidate_id, digest, outcome=normalization.FAILED,
                             error="ValueError: boom")
        state = _ours(normalization.normalization_states(pg), [candidate_id])
        assert state[candidate_id]["attempts"] == attempt
        still_queued = normalization.needs_normalization(
            state[candidate_id], digest, has_event=False)
        assert still_queued is (attempt < normalization.MAX_NORMALIZATION_ATTEMPTS)

    with pg.cursor() as cur:
        cur.execute("SELECT outcome, last_error, failed_at IS NOT NULL "
                    "FROM candidate_normalization WHERE candidate_id = %s",
                    (candidate_id,))
        outcome, error, failed_at = cur.fetchone()
    assert (outcome, error, failed_at) == (normalization.FAILED, "ValueError: boom", True)


def test_a_failing_candidate_is_given_its_tries_back_when_its_inputs_change(
        pg, engine_settings_for_store, store, unique):
    """A candidate fixed upstream must not stay excluded by the attempts a
    different reading of it used up."""
    candidate_id = store.add(_id(unique, 1), collected_at=_day(90))
    for _ in range(normalization.MAX_NORMALIZATION_ATTEMPTS):
        normalization._stamp(pg, candidate_id, "old", outcome=normalization.FAILED,
                             error="ValueError: boom")

    normalization._stamp(pg, candidate_id, "new", outcome=normalization.FAILED,
                         error="ValueError: boom")
    state = _ours(normalization.normalization_states(pg), [candidate_id])
    assert state[candidate_id]["attempts"] == 1
    assert normalization.needs_normalization(state[candidate_id], "new", has_event=False)


def test_a_success_clears_the_failure_count(pg, engine_settings_for_store,
                                            store, unique):
    candidate_id = store.add(_id(unique, 1), collected_at=_day(90))
    normalization._stamp(pg, candidate_id, "d", outcome=normalization.FAILED,
                         error="ValueError: boom")
    normalization._stamp(pg, candidate_id, "d", outcome=normalization.NORMALIZED,
                         event_id=99)
    state = _ours(normalization.normalization_states(pg), [candidate_id])
    assert state[candidate_id]["attempts"] == 0
    assert state[candidate_id]["outcome"] == normalization.NORMALIZED


# --- helpers for the tests that write ---------------------------------------
#
# The `pg` fixture is a shared staging database inside a rolled-back
# transaction. Ids are made unique per run so a test never reads a row another
# run of itself left behind, and every state read is narrowed to the ids the
# test created - `normalization_states()` returns the whole table, which on a
# real database is everything the scheduler has ever normalised.

def _id(unique: str, n: int) -> int:
    return int(f"9{unique[-5:]}{n:02d}")


def _ours(states: dict, ids: list[int]) -> dict:
    return {cid: state for cid, state in states.items() if cid in set(ids)}


# --- end to end: the pass itself, against the real schema -------------------
#
# `normalize_all()` opens its own connection because it is a scheduler job.
# Redirecting that into the `pg` fixture's transaction is what lets these
# assert against the real `events` table and still leave a shared database
# exactly as they found it. `all_candidate_ids()` is made unreadable on
# purpose: prune then does nothing, and a test can never be the thing that
# decides a production event's candidate has gone away.

@pytest.fixture
def run_normalization(pg, engine_settings_for_store, monkeypatch):
    @contextmanager
    def _connect(_settings, **_kwargs):
        yield pg

    monkeypatch.setattr(db, "connect", _connect)
    monkeypatch.setattr(candidate_store, "all_candidate_ids", lambda *a, **kw: None)

    def run(**kwargs):
        return normalization.normalize_all(engine_settings_for_store, **kwargs)

    return run


def _event(pg, candidate_id: int) -> dict | None:
    with pg.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE candidate_id = %s", (candidate_id,))
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    return None if row is None else dict(zip(names, row))


def test_a_starved_old_candidate_finally_becomes_an_event(run_normalization, pg,
                                                          store, unique):
    """The release's own success criterion, in miniature: candidate 2800's
    shape - dated, collected long ago, no events row - reaching `events`."""
    for n in range(1, 30):
        store.add(_id(unique, n), collected_at=_day(1))
    starved = _id(unique, 90)
    store.add(starved, collected_at=_day(400), event_date="2026-09-19",
              name="스윙타임빠 소셜")

    assert _event(pg, starved) is None
    built = run_normalization()

    assert built["created"] >= 1
    assert built["remaining"] == 0
    event = _event(pg, starved)
    assert event is not None, "a dated candidate must not be excluded by its age"
    assert event["event_date"] == date(2026, 9, 19)
    assert event["listing_state"] == "LISTED"


def test_the_second_pass_does_no_work_at_all(run_normalization, pg, store, unique):
    """T5 end to end, and the answer to "will this rewrite the whole store
    every five minutes"."""
    for n in range(1, 6):
        store.add(_id(unique, n), collected_at=_day(n))

    first = run_normalization()
    assert first["selected"] == 5 and first["created"] == 5

    second = run_normalization()
    assert second["selected"] == 0
    assert second["skipped_current"] == 5
    assert (second["normalized"], second["created"], second["updated"]) == (0, 0, 0)


def test_a_batch_limits_the_work_and_the_rest_is_reported_as_remaining(
        run_normalization, store, unique):
    """T3/T12 end to end: three ticks of two, then nothing, no repeats."""
    for n in range(1, 6):
        store.add(_id(unique, n), collected_at=_day(n))

    ticks = [run_normalization(limit=2) for _ in range(4)]
    assert [built["selected"] for built in ticks] == [2, 2, 1, 0]
    assert [built["remaining"] for built in ticks] == [3, 1, 0, 0]
    assert sum(built["created"] for built in ticks) == 5


def test_re_normalizing_keeps_the_event_id_and_the_review_state(
        run_normalization, pg, store, unique):
    """T9/T11. The upsert is keyed on candidate_id and always was; what is new
    is that a candidate this old can be re-normalised at all. A re-read that
    produces one event for one candidate must not issue a new event id, and
    must not disturb what a person decided about it."""
    candidate_id = store.add(_id(unique, 1), collected_at=_day(365),
                             event_date="2026-09-19")
    run_normalization()
    before = _event(pg, candidate_id)
    assert before is not None

    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO candidate_review_state (candidate_id, review_state, "
            "  last_action, last_reviewer, last_review_at, corrected_json, "
            "  action_count, updated_at) "
            "VALUES (%s, 'APPROVED', 'APPROVE', 'tester', now(), '{}'::jsonb, 1, now())",
            (candidate_id,),
        )

    after_review = run_normalization()
    assert after_review["selected"] == 1, (
        "a review action changes the event without changing the engine store, "
        "so it has to put the candidate back in the queue"
    )
    reviewed = _event(pg, candidate_id)
    assert reviewed["event_id"] == before["event_id"]
    assert reviewed["review_state"] == "APPROVED"

    store.re_extract(candidate_id, event_date="2026-09-26")
    reextracted = run_normalization()
    assert reextracted["selected"] == 1 and reextracted["updated"] == 1
    assert reextracted["created"] == 0
    final = _event(pg, candidate_id)
    assert final["event_id"] == before["event_id"], (
        "1 -> 1 re-normalization must keep the established event id"
    )
    assert final["event_date"] == date(2026, 9, 26)
    assert final["review_state"] == "APPROVED"


def test_a_late_promoted_event_goes_through_the_ordinary_duplicate_rules(
        run_normalization, pg, store, unique):
    """T10. A candidate promoted long after its twin is a new duplicate, and
    it is settled by the same `duplicates.scan()` the job has always run -
    normalization creates rows and decides nothing about canonicality."""
    from runtime import duplicates

    when = "2027-12-31"
    first = store.add(_id(unique, 1), collected_at=_day(1), event_date=when,
                      name="La Vida Milonga", venue="LA VIDA",
                      url="https://example.test/first")
    late = store.add(_id(unique, 2), collected_at=_day(400), event_date=when,
                     name="La Vida Milonga", venue="LA VIDA",
                     url="https://example.test/late")

    run_normalization()
    rows = {cid: _event(pg, cid) for cid in (first, late)}
    assert all(row is not None for row in rows.values())
    assert rows[first]["identity_key"] == rows[late]["identity_key"]
    assert all(row["canonical_event_id"] is None for row in rows.values()), (
        "normalization must not fold anything itself"
    )

    found = duplicates.scan(pg, on=date(2027, 12, 31))
    assert found["auto_merged"] + found["flagged_for_review"] >= 1
    after = {cid: _event(pg, cid) for cid in (first, late)}
    canonical = [cid for cid, row in after.items() if row["canonical_event_id"] is None]
    folded = [cid for cid, row in after.items() if row["canonical_event_id"] is not None]
    assert len(canonical) == 1 and len(folded) == 1, (
        "the pair must be settled by the duplicate rules, not left as two "
        "independent listings"
    )
    assert after[folded[0]]["canonical_event_id"] == after[canonical[0]]["event_id"]


def test_one_candidate_that_raises_does_not_stop_the_others(
        run_normalization, pg, store, unique, monkeypatch):
    """T8 end to end. The queue keeps moving, the failure is recorded on its
    own row, and it does not come back first on the next tick forever."""
    good = store.add(_id(unique, 1), collected_at=_day(2))
    bad = store.add(_id(unique, 2), collected_at=_day(1))

    real = normalization.normalize_candidate

    def _explode(con, candidate, **kwargs):
        if candidate.get("candidate_id") == bad:
            raise ValueError("boom")
        return real(con, candidate, **kwargs)

    monkeypatch.setattr(normalization, "normalize_candidate", _explode)
    built = run_normalization()

    assert built["failed"] == 1
    assert built["created"] == 1
    assert _event(pg, good) is not None
    assert _event(pg, bad) is None

    states = _ours(normalization.normalization_states(pg), [bad])
    assert states[bad]["outcome"] == normalization.FAILED
    assert states[bad]["attempts"] == 1

    monkeypatch.setattr(normalization, "normalize_candidate", real)
    retried = run_normalization()
    assert retried["selected"] == 1 and retried["created"] == 1
    assert _event(pg, bad) is not None


def test_a_dateless_candidate_is_recorded_rather_than_left_in_the_queue(
        run_normalization, pg, store, unique):
    """Several hundred Production candidates carry no readable date. Without a
    durable NO_DATE they would be the whole of every batch, forever."""
    dateless = store.add(_id(unique, 1), collected_at=_day(30), event_date=None)
    built = run_normalization()
    assert built["skipped_no_date"] == 1 and built["created"] == 0

    states = _ours(normalization.normalization_states(pg), [dateless])
    assert states[dateless]["outcome"] == normalization.NO_DATE
    assert run_normalization()["selected"] == 0


def test_the_backlog_report_agrees_with_the_pass_it_describes(
        run_normalization, engine_settings_for_store, pg, store, unique):
    """What a rollout is watched on. `pending` is the number of candidates the
    scheduler still owes work, and it has to fall to 0 and stay there."""
    for n in range(1, 5):
        store.add(_id(unique, n), collected_at=_day(n))

    before = normalization.backlog(engine_settings_for_store, con=pg)
    assert before["readable"] is True
    assert before["candidates"] == 4
    assert before["pending"] == 4 and before["never_normalized"] == 4

    run_normalization()
    after = normalization.backlog(engine_settings_for_store, con=pg)
    assert after["pending"] == 0 and after["current"] == 4


def test_an_unreadable_engine_store_reports_no_backlog(settings, monkeypatch):
    """An unreadable store: "I cannot see the candidates" must never act as
    "there is nothing to do" - the rule `all_candidate_ids()` has always
    held to, applied to the backlog report as well."""
    monkeypatch.setattr(candidate_store, "normalization_inputs", lambda *a, **kw: None)
    report = normalization.backlog(settings)
    assert report == {"readable": False, "candidates": 0, "pending": 0, "current": 0,
                      "never_normalized": 0, "stale_inputs": 0, "stale_version": 0,
                      "missing_event": 0, "failed": 0, "exhausted": 0}


# --- master data is a global input, so it is part of every digest ----------
#
# The old window re-normalised its newest 500 rows on every tick, which is
# how a venue registered today reached the events built yesterday. Dropping
# the window without replacing that would have been a quiet regression: the
# venue would resolve for new candidates and never for the ones already
# built. The master revision is the replacement, and it reaches all of them,
# not the newest 500.

def test_registering_a_venue_puts_the_whole_store_back_in_the_queue(
        pg, engine_settings_for_store, store, unique, seoul_id):
    from runtime import master_data

    candidate_id = store.add(_id(unique, 1), collected_at=_day(200),
                             venue=f"미등록홀{unique}")
    inputs = _inputs(engine_settings_for_store)
    before = normalization.master_revision(pg)
    normalization._stamp(pg, candidate_id,
                         normalization.input_digest(inputs[0], "", before),
                         outcome=normalization.NORMALIZED, event_id=1)

    states = _ours(normalization.normalization_states(pg), [candidate_id])
    resting, _ = normalization.select_stale(inputs, states, {}, {candidate_id}, before)
    assert resting == []

    master_data.create_venue(pg, name=f"미등록홀{unique}", region_id=seoul_id,
                             aliases=[f"미등록홀{unique}"])
    after = normalization.master_revision(pg)
    assert after != before, (
        "a new venue has to move the revision, or the candidates that could "
        "now resolve against it would never be looked at again"
    )

    queued, _ = normalization.select_stale(inputs, states, {}, {candidate_id}, after)
    assert queued == [candidate_id]


def test_the_master_revision_moves_when_a_row_is_removed_as_well(pg, unique, seoul_id):
    """A delete moves no `updated_at`, which is why the revision counts rows
    as well as dating them."""
    from runtime import master_data

    before = normalization.master_revision(pg)
    venue = master_data.create_venue(pg, name=f"임시홀{unique}", region_id=seoul_id)
    added = normalization.master_revision(pg)
    assert added != before

    with pg.cursor() as cur:
        cur.execute("DELETE FROM venues WHERE venue_id = %s", (venue["venue_id"],))
    assert normalization.master_revision(pg) != added


# --- and the master revision has to be quiet ------------------------------
#
# Found on Production, twenty minutes after the v0.96.6 rollout. The revision
# originally took `max(sources.updated_at)`, which the intake job touches
# every time it collects from a source - several times an hour. Every
# candidate's digest therefore changed on every tick, the queue reset to its
# first 500 rows by collected_at each time, and the 764 behind them were
# never reached: the starvation this release removes, reintroduced through
# the door meant to keep master edits reaching old events.
#
#   candidates=500 normalized=229 no_date=271 created=0 current=0 remaining=764
#   candidates=500 normalized=383 no_date=117 created=6 current=500 remaining=264
#   candidates=500 normalized=229 no_date=271 created=0 current=0 remaining=764
#
# The third line is the bug: a tick that had advanced, undone. So the
# revision now digests `sources` over the columns normalization actually
# joins it for, and this test holds it there - a new operational column on
# any of these tables must not reach the queue.

def test_collecting_from_a_source_does_not_disturb_the_queue(pg, unique):
    from runtime import sources as source_store

    source = source_store.create_source(
        pg, source_key=f"QUIET-{unique}", name=f"quiet {unique}",
        platform="WEB", source_role="DIRECTORY", authority_level="SECONDARY",
    )
    before = normalization.master_revision(pg)

    # Exactly what an intake tick leaves behind: bookkeeping, no change to
    # anything normalization reads. `clock_timestamp()`, not `now()`: inside
    # one transaction `now()` is the transaction's own start time and would
    # write the value that is already there, which is a test that passes
    # while proving nothing. A real intake tick is a later transaction.
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE sources SET updated_at = clock_timestamp() + interval '1 hour', "
            "  last_collected_at = clock_timestamp() + interval '1 hour' "
            "WHERE source_id = %s", (source["source_id"],),
        )
        cur.execute("SELECT max(updated_at) > now() FROM sources")
        assert cur.fetchone()[0], "the fixture has to actually move the column"
    assert normalization.master_revision(pg) == before, (
        "an intake collection must not restage every candidate - that is the "
        "window bug with a different cause"
    )


def test_changing_what_normalization_reads_off_a_source_does_move_it(pg, unique):
    from runtime import sources as source_store

    source = source_store.create_source(
        pg, source_key=f"LOUD-{unique}", name=f"loud {unique}",
        platform="WEB", source_role="DIRECTORY", authority_level="SECONDARY",
    )
    before = normalization.master_revision(pg)
    with pg.cursor() as cur:
        cur.execute("UPDATE sources SET authority_level = 'PRIMARY_ORGANIZER' "
                    "WHERE source_id = %s", (source["source_id"],))
    assert normalization.master_revision(pg) != before, (
        "the region rule reads authority_level, so events built against the "
        "old value are owed a re-read"
    )


def test_the_revision_holds_still_when_nothing_changes(pg):
    """The property the whole queue rests on: two reads in a row agree, so a
    tick that changed nothing leaves every candidate current."""
    assert normalization.master_revision(pg) == normalization.master_revision(pg)
