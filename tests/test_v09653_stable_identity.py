"""v0.96.53 - an Event keeps its id across re-extraction.

Events are upserted on the engine's candidate_id, so an Event lives exactly as
long as its candidate. v0.96.0 re-read a post into its own candidate only when
it had one candidate before and one after; every multi-programme post had its
candidates deleted and inserted afresh. The v0.96.52 ENGINE 1.17 probe moved
99 Event ids that way, and 95 of them were the same date under the same title
(a festival's five days, a club's Chuseok nights), the other four the real
party left behind when a deadline row went. `candidate_identity.match()` pairs
a post's stored candidates with the new ones by what each programme is, and
`reprocess_acquired()` re-reads every paired programme into its own candidate.

On the 2026-10-24 04:35 KST Production backup, re-run end to end at ENGINE
1.17: 99 exact, 9 revised, 9 genuinely new (the Sundays of DATA-06), 6
removed (the DATA-01 deadline rows), 0 ambiguous, 0 conflicting, 0 Event
ids moved and 0 canonical folds changed; a second pass changed nothing.

The first half is the pure decision; the second drives the engine through
`reprocess_acquired()`, which opens its own autocommit connection, so it
commits its own rows and cleans them up (tests/test_v0963_incremental_reextract.py's
discipline, whose helpers it reuses).
"""

from __future__ import annotations

import itertools
import sqlite3

import pytest

from runtime import candidate_identity as ci
from runtime import engine_adapter, engine_ingest
from tests.test_v0963_incremental_reextract import (
    _candidates,
    _cleanup,
    _event_row,
    _fetched,
    _item,
    _make_outdated,
    _normalize,
    _source,
)


def F(date="2026-10-24", name="클럽 소셜", event_type="SOCIAL", start="20:00",
      end="23:00", venue="스윙홀"):
    return ci._fields(date, name, event_type, start, end, venue)


def _match(stored, extracted):
    return ci.match(list(stored.items()), extracted)


# --- the decision ------------------------------------------------------------------

def test_the_same_source_re_read_pairs_every_programme_exactly():
    stored = {11: F(), 12: F(date="2026-10-25")}
    out = _match(stored, [F(), F(date="2026-10-25")])
    assert out["pairs"] == {0: 11, 1: 12}
    assert set(out["kinds"].values()) == {ci.MATCH_EXACT}
    assert out["new"] == [] and out["removed"] == []


def test_a_revised_title_keeps_the_programme():
    out = _match({11: F(), 12: F(date="2026-10-25")},
                 [F(name="클럽 할로윈 소셜"), F(date="2026-10-25")])
    assert out["pairs"] == {0: 11, 1: 12}
    assert out["kinds"][0] == ci.MATCH_REVISED


def test_a_corrected_start_keeps_the_programme():
    out = _match({11: F(start="20:15", end="22:15"), 12: F(date="2026-10-25")},
                 [F(start="19:30", end=None), F(date="2026-10-25")])
    assert out["pairs"] == {0: 11, 1: 12}
    assert out["kinds"][0] == ci.MATCH_REVISED


def test_a_refined_venue_keeps_the_programme():
    out = _match({11: F(venue="스윙홀"), 12: F(date="2026-10-25")},
                 [F(venue="스윙홀 (마포구 서교동 1-2)"), F(date="2026-10-25")])
    assert out["pairs"] == {0: 11, 1: 12}
    assert out["kinds"][0] == ci.MATCH_REVISED


def test_the_per_day_suffix_is_not_part_of_the_title():
    """The engine names each programme of a multi-day post "<title> MM/DD", and
    drops the suffix when one programme is left - the four party rows."""
    out = _match({11: F(name="졸업파티 안내 10/25", date="2026-10-25"),
                  12: F(name="졸업파티 안내 10/22", date="2026-10-22")},
                 [F(name="졸업파티 안내", date="2026-10-25")])
    assert out["pairs"] == {0: 11}
    assert out["removed"] == [12]
    assert out["counts"][ci.REMOVED] == 1


def test_a_programme_added_to_a_source_keeps_the_others_and_is_the_only_new_one():
    stored = {11: F(start="14:00", end="17:00", name="쁘락띠까", event_type="MILONGA"),
              12: F(start="20:00", end="23:00", name="밀롱가", event_type="MILONGA"),
              13: F(date="2026-10-25", start="19:30", end=None)}
    extracted = [stored[11], stored[12],
                 F(date="2026-10-25", start="16:00", end="18:00", name="워크샵",
                   event_type="CLASS"),
                 stored[13]]
    out = _match(stored, extracted)
    assert out["pairs"] == {0: 11, 1: 12, 3: 13}
    assert out["new"] == [2]
    assert out["counts"][ci.NEW_EVENT] == 1


def test_position_is_never_identity():
    stored = {11: F(), 12: F(date="2026-10-25"), 13: F(date="2026-10-26")}
    extracted = [F(date="2026-10-26"), F(), F(date="2026-10-25")]
    out = _match(stored, extracted)
    assert out["pairs"] == {0: 13, 1: 11, 2: 12}


@pytest.mark.parametrize("perm", list(itertools.permutations(range(3))))
def test_any_enumeration_order_gives_the_same_identities(perm):
    stored = {11: F(), 12: F(date="2026-10-25", start="19:30"),
              13: F(date="2026-10-26", name="밀롱가", event_type="MILONGA")}
    base = [F(start="19:30", end=None), F(date="2026-10-25", start="19:30"),
            F(date="2026-10-26", name="밀롱가 리뉴얼", event_type="MILONGA")]
    reference = {base_i: cid for base_i, cid in _match(stored, base)["pairs"].items()}
    shuffled = [base[i] for i in perm]
    out = ci.match([(c, stored[c]) for c in sorted(stored, key=lambda c: perm.index(c - 11))],
                   shuffled)
    assert {perm[new_i]: cid for new_i, cid in out["pairs"].items()} == reference


def test_one_stored_programme_two_new_readings_is_ambiguous_and_never_guessed():
    out = _match({11: F(start=None, end=None)},
                 [F(start="14:00", end="17:00"), F(start="20:00", end="23:00")])
    assert out["pairs"] == {}
    assert out["counts"][ci.AMBIGUOUS] == 2
    assert out["held"]["old"] == {11: ci.AMBIGUOUS}
    # Not counted as a removal: it is undecided, and says so.
    assert out["counts"][ci.REMOVED] == 0


def test_two_stored_programmes_one_new_reading_is_conflicting_and_never_merged():
    out = _match({11: F(start="14:00", end="17:00"), 12: F(start="20:00", end="23:00")},
                 [F(start=None, end=None)])
    assert out["pairs"] == {}
    assert out["counts"][ci.CONFLICTING] == 1
    assert out["held"]["old"] == {11: ci.CONFLICTING, 12: ci.CONFLICTING}


def test_a_programme_that_moved_day_is_a_different_programme():
    out = _match({11: F(), 12: F(date="2026-10-25")}, [F(), F(date="2026-10-31")])
    assert out["pairs"] == {0: 11}
    assert out["new"] == [1] and out["removed"] == [12]


def test_a_title_made_only_of_dates_is_never_matched_on_the_title():
    out = _match({11: F(name="10/24", start="14:00"), 12: F(name="10/24", start="20:00",
                                                            event_type="MILONGA")},
                 [F(name="10/24", start="15:00"), F(name="10/24", start="21:00",
                                                    event_type="MILONGA")])
    # The empty title stem may not pair them; type alone with a changed clock
    # is not evidence either.
    assert out["pairs"] == {}


def test_matching_its_own_output_again_changes_nothing():
    extracted = [F(), F(date="2026-10-25", start="19:30", end=None)]
    first = _match({11: F(start="20:15"), 12: F(date="2026-10-25")}, extracted)
    again = _match({cid: extracted[i] for i, cid in first["pairs"].items()}, extracted)
    assert again["pairs"] == first["pairs"]
    assert set(again["kinds"].values()) == {ci.MATCH_EXACT}


def test_every_result_key_is_reported_by_the_reprocess_pass():
    assert set(engine_ingest._IDENTITY_KEYS.values()) == {
        ci.MATCH_EXACT, ci.MATCH_REVISED, ci.NEW_EVENT, ci.REMOVED, ci.AMBIGUOUS,
        ci.CONFLICTING}


# --- through the engine ------------------------------------------------------------

SCHEDULE = ("10/3 토 소셜 20:00 @ 스윙홀 / 10/10 토 소셜 20:00 @ 스윙홀 "
            "/ 10/17 토 파티 20:00 @ 스윙홀")
SCHEDULE_REVISED = ("10/3 토 소셜 19:30 @ 스윙홀 / 10/10 토 소셜 20:00 @ 스윙홀 "
                    "/ 10/14 수 소셜 20:00 @ 스윙홀 / 10/17 토 파티 20:00 @ 스윙홀")


@pytest.fixture
def settings(env):
    from runtime.config import load_settings

    return load_settings()


def _schedule_post(pg, unique, key, body=SCHEDULE):
    source_id = _source(pg, unique, key=key)
    url = f"https://identity.test/{unique}/{key}"
    item_id = _item(pg, source_id, url=url, title="10월 소셜 일정")
    pg.commit()
    _fetched(pg, item_id, body)
    pg.commit()
    return source_id, url, item_id


def _by_date(candidates):
    return {c["event_date"]: c for c in candidates}


def test_a_revised_multi_programme_post_keeps_every_event_id(pg, unique, settings):
    source_id, url, item_id = _schedule_post(pg, unique, "KEEP")
    try:
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _by_date(_candidates(settings, url))
        assert sorted(before) == ["2026-10-03", "2026-10-10", "2026-10-17"]
        events = {d: _normalize(pg, c) for d, c in before.items()}

        # The publisher moves the first night's start and adds a Wednesday.
        _fetched(pg, item_id, SCHEDULE_REVISED)
        pg.commit()
        _make_outdated(pg, item_id)
        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["failed"] == 0
        after = _by_date(_candidates(settings, url))
        assert sorted(after) == ["2026-10-03", "2026-10-10", "2026-10-14", "2026-10-17"]
        for day in ("2026-10-03", "2026-10-10", "2026-10-17"):
            assert after[day]["candidate_id"] == before[day]["candidate_id"]
            assert _event_row(pg, events[day]["event_id"])["candidate_id"] == \
                before[day]["candidate_id"]
        assert after["2026-10-03"]["start_time"] == "19:30"
        assert after["2026-10-14"]["candidate_id"] not in {
            c["candidate_id"] for c in before.values()}
        assert result["events_dropped"] == 0
        assert result["identity_exact"] == 2 and result["identity_revised"] == 1
        assert result["identity_new"] == 1 and result["identity_removed"] == 0

        # And again: nothing moves.
        _make_outdated(pg, item_id)
        again = engine_ingest.reprocess_acquired(settings, limit=50)
        assert again["failed"] == 0 and again["identity_exact"] == 4
        assert {d: c["candidate_id"] for d, c in _by_date(_candidates(settings, url)).items()} \
            == {d: c["candidate_id"] for d, c in after.items()}
    finally:
        _cleanup(pg, [source_id])


def test_a_programme_the_engine_no_longer_reads_is_the_only_one_retired(pg, unique, settings):
    source_id, url, item_id = _schedule_post(pg, unique, "DROP")
    try:
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _by_date(_candidates(settings, url))
        events = {d: _normalize(pg, c) for d, c in before.items()}

        _fetched(pg, item_id, "10/3 토 소셜 20:00 @ 스윙홀 / 10/10 토 소셜 20:00 @ 스윙홀")
        pg.commit()
        _make_outdated(pg, item_id)
        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["failed"] == 0
        after = _by_date(_candidates(settings, url))
        assert sorted(after) == ["2026-10-03", "2026-10-10"]
        assert {d: c["candidate_id"] for d, c in after.items()} == {
            d: before[d]["candidate_id"] for d in after}
        assert result["identity_removed"] == 1 and result["events_dropped"] == 1
        assert result["events_preserved"] == 2
        assert all(_event_row(pg, events[d]["event_id"]) for d in after)
    finally:
        _cleanup(pg, [source_id])


def test_a_folded_programme_stays_folded_through_re_extraction(pg, unique, settings):
    source_id, url, item_id = _schedule_post(pg, unique, "FOLD")
    other_source, other_url, other_item = _schedule_post(pg, unique, "FOLDCANON",
                                                         body="10/10 토 소셜 20:00 @ 스윙홀")
    try:
        assert engine_ingest.ingest_pending(settings)["ingested"] == 2
        events = {d: _normalize(pg, c) for d, c in _by_date(_candidates(settings, url)).items()}
        canonical = _normalize(pg, _candidates(settings, other_url)[0])
        folded = events["2026-10-10"]["event_id"]
        with pg.cursor() as cur:
            cur.execute("UPDATE events SET canonical_event_id = %s, listing_state = 'HIDDEN', "
                        "duplicate_decided_by = 'AUTO' WHERE event_id = %s",
                        (canonical["event_id"], folded))
        pg.commit()

        _fetched(pg, item_id, SCHEDULE_REVISED)
        pg.commit()
        _make_outdated(pg, item_id)
        assert engine_ingest.reprocess_acquired(settings, limit=50)["failed"] == 0

        row = _event_row(pg, folded)
        assert row is not None and row["canonical_event_id"] == canonical["event_id"]
    finally:
        _cleanup(pg, [source_id, other_source])


def test_a_pass_that_fails_half_way_leaves_every_identity_where_it_was(pg, unique, settings,
                                                                       monkeypatch):
    """A retry after a crash: the engine store is rolled back with the item, so
    the next pass pairs the same stored candidates and creates nothing twice."""
    source_id, url, item_id = _schedule_post(pg, unique, "RETRY")
    try:
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _by_date(_candidates(settings, url))
        _fetched(pg, item_id, SCHEDULE_REVISED)
        pg.commit()
        _make_outdated(pg, item_id)

        engine_db = engine_ingest._engine(settings)[0]
        real = engine_db.persist_events
        calls = {"n": 0}

        def boom(con, post_id, events):
            calls["n"] += 1
            raise RuntimeError("simulated crash after the pairs were re-read")

        monkeypatch.setattr(engine_db, "persist_events", boom)
        failed = engine_ingest.reprocess_acquired(settings, limit=50)
        assert failed["failed"] >= 1 and calls["n"] == 1
        assert {d: c["candidate_id"] for d, c in _by_date(_candidates(settings, url)).items()} \
            == {d: c["candidate_id"] for d, c in before.items()}

        monkeypatch.setattr(engine_db, "persist_events", real)
        _make_outdated(pg, item_id)
        retried = engine_ingest.reprocess_acquired(settings, limit=50)
        assert retried["failed"] == 0
        after = _candidates(settings, url)
        assert len(after) == 4 and len({c["candidate_id"] for c in after}) == 4
        assert {d: c["candidate_id"] for d, c in _by_date(after).items()
                if d in before} == {d: c["candidate_id"] for d, c in before.items()}
    finally:
        _cleanup(pg, [source_id])


def test_a_reviewed_post_is_still_never_re_read(pg, unique, settings):
    source_id, url, item_id = _schedule_post(pg, unique, "REVIEWED")
    try:
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _candidates(settings, url)
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO human_review_actions (candidate_id, source_item_id, action) "
                "VALUES (%s, %s, 'APPROVE')", (before[0]["candidate_id"], item_id))
        pg.commit()
        _fetched(pg, item_id, SCHEDULE_REVISED)
        pg.commit()
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["skipped_reviewed"] >= 1
        assert [c["candidate_id"] for c in _candidates(settings, url)] == \
            [c["candidate_id"] for c in before]
    finally:
        _cleanup(pg, [source_id])


def test_the_pairing_reads_the_stored_programme_fields(settings):
    """stored_fields() reads an event_candidates row exactly as the reprocess
    query selects it."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE event_candidates (candidate_id, event_date, name, event_type, "
                "start_time, end_time, venue)")
    con.execute("INSERT INTO event_candidates VALUES (7, '2026-10-24', '소셜 10/24', "
                "'SOCIAL', '19:30', NULL, NULL)")
    row = con.execute("SELECT candidate_id, event_date, name, event_type, start_time, "
                      "end_time, venue FROM event_candidates").fetchone()
    assert ci.stored_fields(row) == {"date": "2026-10-24", "stem": "소셜", "type": "SOCIAL",
                                     "start": "19:30", "end": None, "venue": None}
    assert engine_adapter.engine_db_path(settings).name.endswith(".sqlite3")
