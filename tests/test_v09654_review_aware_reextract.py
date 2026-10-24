"""v0.96.54 - re-reading a post a person has worked on, without touching their work.

Review state lives on the candidate (`candidate_review_state`, laid over the
engine reading at normalization), but `reprocess_acquired()` protects the
whole *post*: one reviewed candidate and the post is never read again. That
kept every decision safe, and it also froze whatever else the post announced.
On Production that is 스윙타임빠's 10/24-25 notice: candidate 5228 was EDITED
(19:30, no end) on 2026-10-24, and its Sunday 10/25 social can now never be
read.

`_review_aware_apply()` - behind REVIEW_AWARE_REEXTRACT, off by default - reads
such a post and:
  * never re-reads, retires or renumbers a reviewed candidate (any Review
    action);
  * re-reads an unreviewed paired candidate in place, keeps an unpaired one;
  * creates a new programme only when every stored candidate paired with a
    reading and the new one falls on no day a person rejected or marked
    duplicate - otherwise PENDING_EVIDENCE;
  * writes nothing when an identity is undecided.

On the 2026-10-24 09:57 KST snapshot at ENGINE 1.17 with the gate on: 8
reviewed posts read, 8 reviewed candidates kept, 1 new programme (6826's Sunday
10/25), 2 held as PENDING_EVIDENCE (items 2295/2297, where a CONFIRMED class
date and the engine's reading differ), Human records byte-identical.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from types import SimpleNamespace

import pytest

from runtime import candidate_identity as ci
from runtime import config, engine_ingest, normalization, review
from tests.test_v09653_stable_identity import SCHEDULE, SCHEDULE_REVISED, _by_date, _schedule_post
from tests.test_v0963_incremental_reextract import (
    _candidates,
    _cleanup,
    _event_row,
    _fetched,
    _make_outdated,
    _normalize,
)


# --- the decision, with a recording engine ------------------------------------------

class _Engine:
    def __init__(self):
        self.replaced, self.persisted = [], []

    def replace_candidate(self, con, candidate_id, ev):
        self.replaced.append(candidate_id)

    def persist_events(self, con, post_id, events):
        self.persisted.extend(events)


def _rows(*cands):
    """event_candidates rows as sqlite3.Row, the shape the reprocess query returns."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE c (candidate_id, event_date, name, event_type, start_time, "
                "end_time, venue)")
    con.executemany("INSERT INTO c VALUES (?,?,?,?,?,?,?)", cands)
    return con.execute("SELECT * FROM c ORDER BY candidate_id").fetchall()


def _ev(date, name="스윙 소셜", event_type="SOCIAL", start="19:30", end=None, venue=None):
    return SimpleNamespace(date=date, name=name, event_type=event_type, start_time=start,
                           end_time=end, venue=venue, evidences=[])


def _apply(existing, events, reviewed, states=None):
    identity = ci.match(((r[0], ci.stored_fields(r)) for r in existing),
                        [ci.extracted_fields(e) for e in events])
    engine = _Engine()
    out = engine_ingest._review_aware_apply(engine, None, 1, existing, events, identity,
                                            set(reviewed), states or {})
    return out, engine


SAT = (5228, "2026-10-24", "스윙 소셜", "SOCIAL", "20:15", "22:15", None)


def test_an_edited_saturday_is_untouched_and_the_sunday_is_created():
    out, engine = _apply(_rows(SAT), [_ev("2026-10-24"), _ev("2026-10-25")], {5228},
                         {5228: "EDITED"})
    assert engine.replaced == []                       # the edited candidate is never re-read
    assert [e.date for e in engine.persisted] == ["2026-10-25"]
    assert out["counts"]["review_locked_kept"] == 1
    assert out["counts"]["review_new_created"] == 1 and not out["held"]


def test_a_rejected_deadline_never_comes_back_under_a_new_title():
    deadline = (5028, "2026-10-22", "졸업파티 공연 신청 안내 10/22", "SOCIAL", None, None, None)
    party = (5026, "2026-10-25", "졸업파티 공연 신청 안내 10/25", "SOCIAL", None, None, None)
    out, engine = _apply(_rows(deadline, party),
                         [_ev("2026-10-25", "졸업파티 공연 신청 안내", start=None),
                          _ev("2026-10-22", "음악 전송 마감", start=None)],
                         {5028}, {5028: "REJECTED"})
    assert engine.persisted == []
    assert out["counts"]["review_rejected_kept"] == 1
    assert out["counts"]["review_new_pending"] == 1


def test_a_duplicate_marked_candidate_stays_as_it_is():
    out, engine = _apply(_rows(SAT), [_ev("2026-10-24", start="19:30")], {5228},
                         {5228: "DUPLICATE"})
    assert engine.replaced == [] and engine.persisted == []
    assert out["counts"]["review_rejected_kept"] == 1


def test_every_reviewed_candidate_of_a_post_is_kept():
    sun = (5229, "2026-10-25", "스윙 소셜", "SOCIAL", "19:30", None, None)
    out, engine = _apply(_rows(SAT, sun), [_ev("2026-10-24"), _ev("2026-10-25")],
                         {5228, 5229}, {5228: "EDITED", 5229: "CONFIRMED"})
    assert engine.replaced == [] and engine.persisted == []
    assert out["counts"]["review_locked_kept"] == 2


def test_an_unreviewed_sibling_is_re_read_in_place():
    sun = (5229, "2026-10-25", "스윙 소셜", "SOCIAL", "20:00", None, None)
    out, engine = _apply(_rows(SAT, sun), [_ev("2026-10-24"), _ev("2026-10-25")],
                         {5228}, {5228: "EDITED"})
    assert engine.replaced == [5229]
    assert out["counts"]["review_unreviewed_reread"] == 1


def test_a_stored_programme_left_unpaired_holds_every_new_reading():
    """Items 2295/2297: a person CONFIRMED a class on 10/03; the engine now
    reads it as 09/20. The 09/20 reading may be that very class."""
    confirmed = (2071, "2026-10-03", "살사 기초완성반", "CLASS", None, None, None)
    out, engine = _apply(_rows(confirmed), [_ev("2026-09-20", "살사 기초완성반", "CLASS", None)],
                         {2071}, {2071: "CONFIRMED"})
    assert engine.persisted == []
    assert out["counts"]["review_new_pending"] == 1


def test_an_undecided_identity_writes_nothing():
    out, engine = _apply(_rows((7, "2026-10-24", "스윙 소셜", "SOCIAL", None, None, None)),
                         [_ev("2026-10-24", start="14:00"), _ev("2026-10-24", start="20:00")],
                         {7}, {7: "EDITED"})
    assert out["held"] and out["counts"]["review_held"] == 1
    assert engine.replaced == [] and engine.persisted == []


def test_a_new_reading_with_no_day_is_never_created():
    out, engine = _apply(_rows(SAT), [_ev("2026-10-24"), _ev(None, "스윙 공지")], {5228},
                         {5228: "EDITED"})
    assert engine.persisted == []
    assert out["counts"]["review_new_pending"] == 1


def test_an_unpaired_unreviewed_programme_is_kept_not_retired():
    gone = (5230, "2026-10-31", "스윙 소셜", "SOCIAL", "19:30", None, None)
    out, engine = _apply(_rows(SAT, gone), [_ev("2026-10-24")], {5228}, {5228: "EDITED"})
    assert out["counts"]["review_unpaired_kept"] == 1
    assert engine.replaced == [] and engine.persisted == []


def test_the_gate_is_off_unless_the_operator_turns_it_on(monkeypatch):
    monkeypatch.delenv("REVIEW_AWARE_REEXTRACT", raising=False)
    assert config.load_settings().review_aware_reextract is False
    for value, expected in (("1", True), ("true", True), ("on", True), ("0", False), ("", False)):
        monkeypatch.setenv("REVIEW_AWARE_REEXTRACT", value)
        assert config.load_settings().review_aware_reextract is expected


def test_every_counter_is_in_both_result_shapes():
    empty = engine_ingest._empty_reprocess_result("1.16", {"outdated": 0, "stalled": 0})
    assert set(engine_ingest.REVIEW_AWARE_KEYS) <= set(empty)


# --- through the engine ------------------------------------------------------------

@pytest.fixture
def settings(env):
    return config.load_settings()


def _edit(pg, candidate, item_id, after):
    review.record(pg, candidate_id=candidate["candidate_id"], action=review.EDIT,
                  reviewer="test", source_item_id=item_id,
                  before={"start_time": candidate["start_time"]}, after=after)
    pg.commit()


def _drop_review_state(pg, candidate_ids):
    with pg.cursor() as cur:
        cur.execute("DELETE FROM candidate_review_state WHERE candidate_id = ANY(%s)",
                    (list(candidate_ids),))
    pg.commit()


def test_with_the_gate_off_a_reviewed_post_is_still_skipped_whole(pg, unique, settings):
    source_id, url, item_id = _schedule_post(pg, unique, "OFF")
    ids = []
    try:
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _by_date(_candidates(settings, url))
        ids = [c["candidate_id"] for c in before.values()]
        _edit(pg, before["2026-10-03"], item_id, {"start_time": "19:00"})
        _fetched(pg, item_id, SCHEDULE_REVISED)
        pg.commit()
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["skipped_reviewed"] >= 1 and result["review_new_created"] == 0
        assert sorted(c["candidate_id"] for c in _candidates(settings, url)) == sorted(ids)
    finally:
        _drop_review_state(pg, ids)
        _cleanup(pg, [source_id])


def test_with_the_gate_on_the_edit_survives_and_the_new_programme_is_added(pg, unique, settings):
    on = dataclasses.replace(settings, review_aware_reextract=True)
    source_id, url, item_id = _schedule_post(pg, unique, "ON")
    ids = []
    try:
        assert engine_ingest.ingest_pending(on)["ingested"] == 1
        before = _by_date(_candidates(on, url))
        ids = [c["candidate_id"] for c in before.values()]
        events = {d: _normalize(pg, c) for d, c in before.items()}
        edited = before["2026-10-03"]
        _edit(pg, edited, item_id, {"start_time": "19:00", "end_time": None})
        actions_before = len(review.history(pg, edited["candidate_id"]))

        _fetched(pg, item_id, SCHEDULE_REVISED)
        pg.commit()
        _make_outdated(pg, item_id)
        result = engine_ingest.reprocess_acquired(on, limit=50)

        assert result["failed"] == 0
        after = _by_date(_candidates(on, url))
        ids = [c["candidate_id"] for c in after.values()]
        # The edited candidate: same id, engine reading untouched.
        assert after["2026-10-03"]["candidate_id"] == edited["candidate_id"]
        assert after["2026-10-03"]["start_time"] == edited["start_time"]
        # The person's correction is what normalizes, and their record is intact.
        stored = review.state(pg, edited["candidate_id"])
        assert stored["review_state"] == "EDITED"
        assert len(review.history(pg, edited["candidate_id"])) == actions_before
        candidate = dict(after["2026-10-03"])
        candidate["source_item_id"] = item_id
        row = normalization.normalize_candidate(pg, candidate, review_state=stored)
        pg.commit()
        assert row["event_id"] == events["2026-10-03"]["event_id"]
        assert str(row["start_time"])[:5] == "19:00" and row["end_time"] is None
        assert row["review_state"] == "EDITED"
        # Unreviewed programmes keep their ids; the 10/14 Wednesday is new.
        for day in ("2026-10-10", "2026-10-17"):
            assert after[day]["candidate_id"] == before[day]["candidate_id"]
        assert "2026-10-14" in after and after["2026-10-14"]["candidate_id"] not in \
            {c["candidate_id"] for c in before.values()}
        assert result["review_locked_kept"] == 1 and result["review_new_created"] == 1

        _make_outdated(pg, item_id)
        again = engine_ingest.reprocess_acquired(on, limit=50)
        assert again["review_new_created"] == 0 and again["failed"] == 0
        assert {d: c["candidate_id"] for d, c in _by_date(_candidates(on, url)).items()} == \
            {d: c["candidate_id"] for d, c in after.items()}
        assert _event_row(pg, events["2026-10-10"]["event_id"]) is not None
    finally:
        _drop_review_state(pg, ids)
        _cleanup(pg, [source_id])


def test_a_human_duplicate_decision_is_never_retired_by_a_revision(pg, unique, settings):
    """A MERGE / KEEP_SEPARATE is recorded on Events. A revision still re-reads
    the post (v0.96.42: the verdict and the id survive, the new values are
    read), but an Event a person answered about is never retired - here its
    programme vanishes from the post and it is kept."""
    source_id, url, item_id = _schedule_post(pg, unique, "DUPL")
    try:
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _by_date(_candidates(settings, url))
        events = {d: _normalize(pg, c) for d, c in before.items()}
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO event_duplicate_decisions (event_id, canonical_event_id, decision, "
                "decided_by, rule, reviewer) VALUES (%s, NULL, 'DISTINCT', 'HUMAN', 'TEST', 'test')",
                (events["2026-10-17"]["event_id"],))
        pg.commit()
        _fetched(pg, item_id, "10/3 토 소셜 19:30 @ 스윙홀 / 10/10 토 소셜 20:00 @ 스윙홀")
        pg.commit()
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["failed"] == 0 and result["skipped_reviewed"] == 0
        after = _by_date(_candidates(settings, url))
        assert after["2026-10-17"]["candidate_id"] == before["2026-10-17"]["candidate_id"]
        assert after["2026-10-03"]["start_time"] == "19:30"     # the revision was read
        assert result["duplicate_decision_kept"] == 1 and result["events_dropped"] == 0
    finally:
        with pg.cursor() as cur:
            cur.execute("DELETE FROM event_duplicate_decisions WHERE reviewer = 'test' AND "
                        "rule = 'TEST'")
        pg.commit()
        _cleanup(pg, [source_id])


def test_a_blocked_item_is_never_read_review_aware(monkeypatch):
    """The gate opens reviewed posts, never FETCH_BLOCKED ones (K-TANGO 643/646/647)."""
    source = open(engine_ingest.__file__, encoding="utf-8").read()
    assert "settings.review_aware_reextract and not blocked" in source
    assert SCHEDULE != SCHEDULE_REVISED
