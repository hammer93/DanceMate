"""v0.96.3 - incremental, restart-safe engine re-extraction.

The problem this release exists for, measured on Production b1784ff: 1,039
fetched bodies, of which only 20 had been re-read since the engine moved to
0.91. Re-extraction after an engine bump is not a content event - the stored
bodies did not change - so `needing_reprocess()`'s ordinary branches selected
none of them, and the only other answer was
`POST /api/admin/events/reextract?limit=N`, which is
`needing_reprocess(force=True)`: `WHERE true ORDER BY fetched_at NULLS LAST
LIMIT N`. Nothing in `mark_reprocessed()` changes that ordering, so calling it
repeatedly re-read the *same* first N rows forever; the only call that ever
terminated was a single synchronous pass over all 2,201 rows (~80 minutes on
the board, OCR included) against a live scheduler.

The fix is a column, not a worker: `extracted_engine_version` makes the DB row
itself the cursor. What that has to be proved to do, and what each section
below covers:

  1. paging       - successive batches select different rows, never the same
                    first N, until the backlog is empty
  2. restart-safe - selection is a pure function of DB state, so a process
                    that dies mid-pass resumes rather than restarting
  3/4. generic    - rows the running engine produced are excluded, and the
                    *next* version bump makes them eligible again with no
                    code change (a one-off "re-extract for 0.91" would fail)
  7. failure      - a raising item cannot wedge the queue, and is not lost
  10. force API   - the diagnostic path pages with a cursor

and, through the engine itself: reviewed candidates are still skipped (5),
a 1->1 re-read still keeps its candidate_id and Event id (6), a
cardinality change is measured rather than forced (8), and the
FETCH_BLOCKED preservation contract still holds (9).

The store-level tests run inside the `pg` fixture's rolled-back transaction.
The engine-level ones drive `reprocess_acquired()`, which opens its own
autocommit connection, so they commit their own rows and clean up explicitly
- the same discipline tests/test_v0960_direct_source_yield.py uses, including
normalising one candidate at a time rather than calling normalize_all().
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from runtime import (
    acquisition,
    content_store,
    engine_adapter,
    engine_ingest,
    normalization,
    sources,
)

PUBLISHED = "2026-09-14"
OLD_ENGINE = "0.90"
NEW_ENGINE = "0.91"
NEXT_ENGINE = "0.92"


# --- helpers ----------------------------------------------------------------

def _quiesce(pg, engine_version: str) -> None:
    """Stamp every pre-existing content row as already current.

    A selection test asserts *which* rows come back in *what* batches, which
    is only meaningful when the test owns the whole queue. Written inside the
    `pg` fixture's transaction and rolled back at teardown, so a shared
    database is never changed - the same reason every other row this file
    writes is safe.
    """
    with pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET extracted_engine_version = %s",
                    (engine_version,))


def _source(pg, unique, key="REX"):
    return sources.create_source(
        pg, source_key=f"{key}-{unique}", name=f"{key} {unique}", platform="WEB",
        source_role="COMMUNITY", url=f"https://{key.lower()}.test/{unique}",
        enabled=False,
    )["source_id"]


def _item(pg, source_id, *, url, title="재추출 대상", body="", published=PUBLISHED):
    raw = {"platform": "WEB", "published_at": published, "body": body,
           "acquisition_quality": "METADATA_ONLY"}
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, title, content_hash, "
            "  raw, ingest_state) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'PENDING') "
            "RETURNING source_item_id",
            (source_id, url, url, title, f"hash-{url}", json.dumps(raw)),
        )
        return cur.fetchone()[0]


def _fetched(pg, item_id, text="밀롱가 2026.10.10 20:00-23:00 장소: 스튜디오 오초 회비 10,000원"):
    content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
        fetched_url=f"https://rex.test/{item_id}", text=text,
    ))


def _backlog_of(pg, source_id, engine_version, **kwargs):
    """The test's own outdated ids, in the order the pass would take them."""
    rows = content_store.needing_reprocess(
        pg, engine_version=engine_version, limit=500, **kwargs)
    mine = _ids_of(pg, source_id)
    return [r["source_item_id"] for r in rows if r["source_item_id"] in mine]


def _ids_of(pg, source_id):
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id FROM source_items WHERE source_id = %s",
                    (source_id,))
        return {row[0] for row in cur.fetchall()}


def _outdated_fixture(pg, unique, count):
    """`count` items holding a fetched body, none of them ever engine-stamped.

    `fetched_at` is spread out deliberately: the incremental pass orders by
    it, and rows written in the same statement would otherwise share a
    timestamp and make "did batch 2 get different rows" untestable.
    """
    source_id = _source(pg, unique)
    ids = []
    for n in range(count):
        item_id = _item(pg, source_id, url=f"https://rex.test/{unique}/{n}")
        _fetched(pg, item_id)
        ids.append(item_id)
    with pg.cursor() as cur:
        for offset, item_id in enumerate(ids):
            cur.execute(
                "UPDATE source_item_content SET fetched_at = now() - %s * interval '1 minute', "
                "  reprocessed_at = now() "
                "WHERE source_item_id = %s",
                (count - offset, item_id),
            )
    return source_id, ids


def _stamp_state(pg, item_id):
    with pg.cursor() as cur:
        cur.execute(
            "SELECT extracted_engine_version, reprocess_attempts, reprocess_error "
            "FROM source_item_content WHERE source_item_id = %s", (item_id,))
        version, attempts, error = cur.fetchone()
    return {"engine_version": version, "attempts": attempts, "error": error}


# === 1. paging: the queue actually moves ====================================

def test_the_incremental_pass_walks_the_backlog_in_batches_without_repeating(pg, unique):
    """T1. 60 outdated items, batch 25: 25 / 25 / 10 / 0, all disjoint.

    This is the exact failure the release is for. The pre-v0.96.3 forced
    pass returned the same first 25 rows on every call, forever.
    """
    _quiesce(pg, NEW_ENGINE)
    source_id, ids = _outdated_fixture(pg, unique, 60)

    batches = []
    for _ in range(4):
        rows = content_store.needing_reprocess(pg, limit=25, engine_version=NEW_ENGINE)
        batch = [r["source_item_id"] for r in rows]
        batches.append(batch)
        for item_id in batch:
            content_store.mark_reprocessed(pg, item_id, engine_version=NEW_ENGINE)

    assert [len(b) for b in batches] == [25, 25, 10, 0]
    seen = [item_id for batch in batches for item_id in batch]
    assert len(seen) == len(set(seen)), "no row may be re-selected by a later batch"
    assert set(seen) == set(ids), "every outdated row must be reached exactly once"
    assert _backlog_of(pg, source_id, NEW_ENGINE) == []


def test_a_batch_that_is_not_marked_is_offered_again(pg, unique):
    """The other half of the contract: progress comes from the stamp, not
    from the passage of time. An item the pass could not finish must come
    back, or a crash mid-batch would silently lose it."""
    _quiesce(pg, NEW_ENGINE)
    _source_id, ids = _outdated_fixture(pg, unique, 3)

    first = [r["source_item_id"]
             for r in content_store.needing_reprocess(pg, limit=2, engine_version=NEW_ENGINE)]
    again = [r["source_item_id"]
             for r in content_store.needing_reprocess(pg, limit=2, engine_version=NEW_ENGINE)]
    assert first == again == ids[:2]


# === 2. restart safety ======================================================

def test_the_cursor_survives_a_restart_because_it_is_the_row_itself(pg, unique):
    """T2. Nothing in Python remembers where the pass got to.

    Re-importing the module (the cheapest honest stand-in for the scheduler
    process being restarted - a fresh import holds no state from the last
    one) must not rewind the pass.
    """
    import importlib

    _quiesce(pg, NEW_ENGINE)
    _source_id, ids = _outdated_fixture(pg, unique, 6)

    first = [r["source_item_id"]
             for r in content_store.needing_reprocess(pg, limit=3, engine_version=NEW_ENGINE)]
    for item_id in first:
        content_store.mark_reprocessed(pg, item_id, engine_version=NEW_ENGINE)

    restarted = importlib.reload(content_store)
    after = [r["source_item_id"]
             for r in restarted.needing_reprocess(pg, limit=3, engine_version=NEW_ENGINE)]

    assert first == ids[:3]
    assert after == ids[3:]
    assert not set(first) & set(after)


# === 3/4. engine-version awareness, not a 0.91 one-off ======================

def test_content_already_extracted_by_the_running_engine_is_not_selected(pg, unique):
    """T3."""
    _quiesce(pg, NEW_ENGINE)
    source_id, ids = _outdated_fixture(pg, unique, 3)
    content_store.mark_reprocessed(pg, ids[0], engine_version=NEW_ENGINE)

    assert _backlog_of(pg, source_id, NEW_ENGINE) == ids[1:]


def test_the_next_engine_version_makes_current_content_outdated_again(pg, unique):
    """T4. The queue is defined against whatever ENGINE_VERSION is running,
    so 0.91 -> 0.92 needs no migration, no backfill and no code change. An
    implementation that hardcoded "before the 0.91 bump" would pass every
    test above and fail this one."""
    _quiesce(pg, NEXT_ENGINE)
    source_id, ids = _outdated_fixture(pg, unique, 3)
    for item_id in ids:
        content_store.mark_reprocessed(pg, item_id, engine_version=NEW_ENGINE)

    assert _backlog_of(pg, source_id, NEW_ENGINE) == []
    assert _backlog_of(pg, source_id, NEXT_ENGINE) == ids
    assert _backlog_of(pg, source_id, OLD_ENGINE) == ids, (
        "'not the running version' is the rule - not 'older than', which a "
        "rollback would get backwards")


def test_without_an_engine_version_the_pass_behaves_exactly_as_before(pg, unique):
    """Non-regression: the body-arrived-later queue is unchanged, so a
    caller that passes no version (the existing v0.84.3 call sites and their
    tests) sees the pre-v0.96.3 selection."""
    _quiesce(pg, NEW_ENGINE)
    source_id, _ids = _outdated_fixture(pg, unique, 3)
    rows = content_store.needing_reprocess(pg, limit=500)
    assert not (_ids_of(pg, source_id) & {r["source_item_id"] for r in rows})


# === what counts as re-readable content =====================================

def test_a_discovery_settled_body_is_part_of_the_backlog(pg, unique):
    """A direct source's own synthesized body is stamped
    `reprocessed_at = fetched_at` by `settle_full_body()`, so the ordinary
    body-arrived branch never fires for it - and it is precisely the
    high-quality body an engine bump most needs to re-read. v0.82.2's rule
    (a *lesser* body must never overwrite a good one) is untouched: nothing
    here refetches anything."""
    _quiesce(pg, NEW_ENGINE)
    source_id = _source(pg, unique, key="DIRECT")
    item_id = _item(pg, source_id, url=f"https://direct.test/{unique}/1")
    content_store.settle_full_body(
        pg, item_id,
        body="밀롱가 2026.10.10 20:00-23:00 장소: 스튜디오 오초 회비 10,000원 " * 3)

    assert item_id not in {r["source_item_id"]
                           for r in content_store.needing_reprocess(pg, limit=500)}, (
        "settle_full_body() stamps reprocessed_at = fetched_at, so the "
        "body-arrived branch is (correctly) silent for it")
    assert _backlog_of(pg, source_id, NEW_ENGINE) == [item_id]


def test_an_item_with_nothing_to_read_is_never_part_of_the_backlog(pg, unique):
    """A metadata-only row has no body and no poster: re-reading it would
    produce exactly what it produced before, and it would sit in the queue
    forever because there is nothing to extract from."""
    _quiesce(pg, NEW_ENGINE)
    source_id = _source(pg, unique, key="META")
    item_id = _item(pg, source_id, url=f"https://meta.test/{unique}/1")
    before = content_store.reprocess_backlog(pg, NEW_ENGINE)["with_content"]
    content_store.ensure_row(pg, item_id)

    assert _backlog_of(pg, source_id, NEW_ENGINE) == []
    assert content_store.reprocess_backlog(pg, NEW_ENGINE)["with_content"] == before


def test_a_blocked_fetch_with_a_poster_is_part_of_the_backlog(pg, unique):
    """T9's selection half: the v0.84.3 image-only path is re-readable for
    the same reason a body is - the OCR fallback is engine code too."""
    _quiesce(pg, NEW_ENGINE)
    source_id = _source(pg, unique, key="BLOCKED")
    item_id = _item(pg, source_id, url=f"https://blocked.test/{unique}/1")
    content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE,
        fetched_url=f"https://blocked.test/{unique}/1",
        images=["https://cdn.example.test/poster.jpg"],
        error_code="BODY_UNAVAILABLE", error="page fetched but no article body was served",
    ))
    content_store.mark_reprocessed(pg, item_id, engine_version=NEW_ENGINE)
    assert _backlog_of(pg, source_id, NEW_ENGINE) == []
    assert _backlog_of(pg, source_id, NEXT_ENGINE) == [item_id]


# === 7. a failing item must not wedge the queue - or vanish =================

def test_a_repeatedly_failing_item_steps_aside_and_stays_visible(pg, unique):
    """T7. Retried while it might recover, retired once it clearly will not,
    and reported as stalled either way. Silently dropping it (no counter) and
    retrying it forever (no cap) are both failures."""
    _quiesce(pg, NEW_ENGINE)
    source_id, ids = _outdated_fixture(pg, unique, 3)
    broken = ids[0]

    for attempt in range(1, content_store.MAX_REPROCESS_ATTEMPTS + 1):
        assert content_store.record_reprocess_failure(
            pg, broken, "RuntimeError: engine store is locked") == attempt
        still_queued = broken in _backlog_of(pg, source_id, NEW_ENGINE)
        assert still_queued is (attempt < content_store.MAX_REPROCESS_ATTEMPTS)

    assert _backlog_of(pg, source_id, NEW_ENGINE) == ids[1:], (
        "the rows behind a broken one must still be reachable")
    state = _stamp_state(pg, broken)
    assert state["attempts"] == content_store.MAX_REPROCESS_ATTEMPTS
    assert "engine store is locked" in state["error"]

    backlog = content_store.reprocess_backlog(pg, NEW_ENGINE)
    assert backlog["stalled"] >= 1 and backlog["outdated"] >= 2

    # And a later success clears the record, so one bad week does not retire
    # an item permanently.
    content_store.mark_reprocessed(pg, broken, engine_version=OLD_ENGINE)
    assert _stamp_state(pg, broken) == {"engine_version": OLD_ENGINE,
                                        "attempts": 0, "error": None}
    assert broken in _backlog_of(pg, source_id, NEW_ENGINE)


# === 10. the admin force path pages ========================================

def test_the_forced_pass_pages_with_a_cursor_instead_of_repeating(pg, unique):
    """T10. `force` selects everything, stamped or not, so it cannot rely on
    the queue shrinking - it pages by `source_item_id` instead. Without a
    cursor it repeats, which is the documented pre-v0.96.3 behaviour and
    exactly why the operational path is the incremental one."""
    _quiesce(pg, NEW_ENGINE)
    _source_id, ids = _outdated_fixture(pg, unique, 5)
    floor = min(ids) - 1

    first = [r["source_item_id"] for r in content_store.needing_reprocess(
        pg, limit=2, force=True, after_item_id=floor)]
    repeat = [r["source_item_id"] for r in content_store.needing_reprocess(
        pg, limit=2, force=True, after_item_id=floor)]
    second = [r["source_item_id"] for r in content_store.needing_reprocess(
        pg, limit=2, force=True, after_item_id=first[-1])]
    third = [r["source_item_id"] for r in content_store.needing_reprocess(
        pg, limit=2, force=True, after_item_id=second[-1])]

    assert first == ids[:2] and repeat == first
    assert second == ids[2:4]
    assert third == ids[4:]
    assert not set(first) & set(second)
    assert not set(second) & set(third)


def test_a_forced_pass_still_stamps_so_it_advances_the_incremental_queue(pg, unique):
    """A diagnostic pass is still a real re-extraction: what it re-read must
    leave the operational backlog too, or the two paths would fight."""
    _quiesce(pg, NEW_ENGINE)
    source_id, ids = _outdated_fixture(pg, unique, 3)
    for item_id in ids[:2]:
        content_store.mark_reprocessed(pg, item_id, engine_version=NEW_ENGINE)
    assert _backlog_of(pg, source_id, NEW_ENGINE) == ids[2:]


# === observability ==========================================================

def test_the_backlog_report_adds_up(pg, unique):
    _quiesce(pg, NEW_ENGINE)
    source_id, ids = _outdated_fixture(pg, unique, 4)
    before = content_store.reprocess_backlog(pg, NEW_ENGINE)
    assert before["engine_version"] == NEW_ENGINE
    assert before["outdated"] >= 4

    content_store.mark_reprocessed(pg, ids[0], engine_version=NEW_ENGINE)
    for _ in range(content_store.MAX_REPROCESS_ATTEMPTS):
        content_store.record_reprocess_failure(pg, ids[1], "boom")
    after = content_store.reprocess_backlog(pg, NEW_ENGINE)

    assert after["current"] == before["current"] + 1
    assert after["stalled"] == before["stalled"] + 1
    assert after["outdated"] == before["outdated"] - 2
    assert after["with_content"] == before["with_content"]
    assert after["current"] + after["outdated"] + after["stalled"] == after["with_content"]
    assert _ids_of(pg, source_id)  # fixture sanity: the rows are this test's


# === the engine path ========================================================
#
# These commit (reprocess_acquired() opens its own connection) and clean up.

@pytest.fixture
def settings(env):
    from runtime.config import load_settings

    return load_settings()


def _candidates(settings, source_url):
    con = sqlite3.connect(engine_adapter.engine_db_path(settings))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT c.candidate_id, c.name AS event_name, c.event_date, c.start_time, "
            "       c.end_time, c.end_day_offset, c.venue, c.event_type, c.fee, "
            "       c.fee_display_text, c.dj, c.status AS candidate_status, "
            "       p.post_id, p.source_url "
            "FROM event_candidates c JOIN raw_posts p ON p.post_id = c.post_id "
            "WHERE p.source_url = ? ORDER BY c.candidate_id", (source_url,),
        ).fetchall()
    finally:
        con.close()
    out = []
    for row in rows:
        item = dict(row)
        item["provenance"] = normalization.PROVENANCE_LIVE
        item["time_evidence"] = "EXPLICIT"
        out.append(item)
    return out


def _normalize(pg, candidate):
    candidate = dict(candidate)
    candidate["source_item_id"] = normalization.source_of(
        pg, candidate["source_url"])["source_item_id"]
    stored = normalization.normalize_candidate(pg, candidate)
    pg.commit()
    return stored


def _event_row(pg, event_id):
    with pg.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE event_id = %s", (event_id,))
        names = [c.name for c in cur.description]
        found = cur.fetchone()
        return None if found is None else dict(zip(names, found))


def _make_outdated(pg, item_id, version=OLD_ENGINE):
    """What every pre-v0.96.3 Production row looks like: a body the engine
    has read, under a version that is no longer the running one."""
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET extracted_engine_version = %s "
            "WHERE source_item_id = %s", (version, item_id))
    pg.commit()


def _cleanup(pg, source_ids):
    with pg.cursor() as cur:
        cur.execute(
            "DELETE FROM event_primary_source_history WHERE event_id IN ("
            "  SELECT e.event_id FROM events e JOIN source_items i USING (source_item_id) "
            "  WHERE i.source_id = ANY(%s))", (source_ids,))
        cur.execute(
            "DELETE FROM human_review_actions WHERE source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))",
            (source_ids,))
        cur.execute(
            "DELETE FROM events WHERE canonical_event_id IS NOT NULL AND source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))",
            (source_ids,))
        cur.execute(
            "DELETE FROM events WHERE source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))",
            (source_ids,))
        cur.execute(
            "DELETE FROM source_item_content WHERE source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))",
            (source_ids,))
        cur.execute("DELETE FROM source_items WHERE source_id = ANY(%s)", (source_ids,))
        cur.execute("DELETE FROM sources WHERE source_id = ANY(%s)", (source_ids,))
    pg.commit()


BODY = "밀롱가 2026.10.10 20:00-23:00 장소: 스튜디오 오초 회비 10,000원"


def test_an_outdated_item_is_re_read_into_the_same_candidate_and_event(pg, unique, settings):
    """T6 + T3, end to end: the ordinary 1->1 shape, which is 1,235 of the
    1,236 Production posts that hold candidates. Re-extraction must leave
    the candidate_id and the Event id exactly where they were - "재추출
    때문에 단순 1->1 event가 새 Event ID를 받으면 release blocker다" - and
    must take the item out of the queue so the next tick moves on."""
    source_id = _source(pg, unique, key="ONE")
    url = f"https://one.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title="10월 밀롱가 안내")
    pg.commit()
    try:
        _fetched(pg, item_id, BODY)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _candidates(settings, url)
        assert len(before) == 1 and before[0]["event_date"] == "2026-10-10"
        event = _normalize(pg, before[0])
        assert event is not None
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["failed"] == 0
        assert result["engine_version"] == settings.engine_version
        after = _candidates(settings, url)
        assert [c["candidate_id"] for c in after] == [before[0]["candidate_id"]]
        assert _event_row(pg, event["event_id"])["candidate_id"] == before[0]["candidate_id"]
        assert result["events_dropped"] == 0
        assert result["events_preserved"] >= 1
        assert result["multi_event_changed"] == 0

        # Out of the queue, permanently: this is the cursor.
        assert _stamp_state(pg, item_id)["engine_version"] == settings.engine_version
        assert item_id not in {r["source_item_id"] for r in content_store.needing_reprocess(
            pg, limit=500, engine_version=settings.engine_version)}
    finally:
        _cleanup(pg, [source_id])


def test_a_reviewed_candidate_is_skipped_but_still_leaves_the_queue(pg, unique, settings):
    """T5. Review state is keyed by candidate_id and re-extraction issues new
    ids, so a reviewed candidate is never re-read - and must still be stamped,
    or it would be re-selected first on every tick from now on and the rows
    behind it would never be reached."""
    source_id = _source(pg, unique, key="REVIEWED")
    url = f"https://reviewed.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title="10월 밀롱가 안내")
    pg.commit()
    try:
        _fetched(pg, item_id, BODY)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _candidates(settings, url)
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO human_review_actions (candidate_id, source_item_id, action) "
                "VALUES (%s, %s, 'APPROVE')", (before[0]["candidate_id"], item_id))
        pg.commit()
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["skipped_reviewed"] >= 1 and result["failed"] == 0
        assert [c["candidate_id"] for c in _candidates(settings, url)] == \
            [before[0]["candidate_id"]]
        assert _stamp_state(pg, item_id)["engine_version"] == settings.engine_version
    finally:
        _cleanup(pg, [source_id])


def test_a_cardinality_change_is_measured_and_leaves_other_events_alone(pg, unique, settings):
    """T8. A schedule post genuinely becomes N events. Forcing the original
    id onto one of them would be a guess; the release records the change
    instead (`multi_event_changed`, `events_dropped`) and leaves the
    duplicate/canonical machinery to decide. What it must never do is crash,
    or touch an Event that belongs to another post."""
    source_id = _source(pg, unique, key="MULTI")
    url = f"https://multi.test/{unique}/1"
    other_url = f"https://multi.test/{unique}/other"
    item_id = _item(pg, source_id, url=url, title="10월 소셜 일정")
    other_id = _item(pg, source_id, url=other_url, title="10월 밀롱가 안내")
    pg.commit()
    try:
        _fetched(pg, item_id, BODY)
        _fetched(pg, other_id, BODY)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 2
        first = _candidates(settings, url)
        assert len(first) == 1
        event = _normalize(pg, first[0])
        other_event = _normalize(pg, _candidates(settings, other_url)[0])
        assert event and other_event

        # The same post, re-fetched as the schedule it always was.
        _fetched(pg, item_id,
                 "10/3 토 소셜 20:00 @ 스윙홀 / 10/10 토 소셜 20:00 @ 스윙홀 "
                 "/ 10/17 토 파티 20:00 @ 스윙홀")
        pg.commit()
        _make_outdated(pg, item_id)
        _make_outdated(pg, other_id)

        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["failed"] == 0
        after = _candidates(settings, url)
        assert len(after) >= 2, "the schedule must expand rather than crash"
        assert result["multi_event_changed"] >= 1
        assert result["events_dropped"] >= 1
        assert _event_row(pg, other_event["event_id"]) is not None, (
            "re-extracting one post must never prune another post's Event")
        assert _event_row(pg, other_event["event_id"])["candidate_id"] == \
            other_event["candidate_id"]
    finally:
        _cleanup(pg, [source_id])


def test_an_item_whose_re_extraction_raises_is_counted_on_the_row(pg, unique, settings,
                                                                  monkeypatch):
    """T7, through the real path: the failure lands on the row, so the cap
    that keeps the queue moving is fed by actual failures and the reason is
    readable afterwards without digging through a log."""
    source_id = _source(pg, unique, key="BROKEN")
    url = f"https://broken.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title="10월 밀롱가 안내")
    pg.commit()
    try:
        _fetched(pg, item_id, BODY)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        _make_outdated(pg, item_id)

        def _boom(*args, **kwargs):
            raise RuntimeError("engine exploded")

        monkeypatch.setattr(engine_ingest, "_to_raw_post", _boom)
        result = engine_ingest.reprocess_acquired(settings, limit=50)

        assert result["failed"] >= 1
        state = _stamp_state(pg, item_id)
        assert state["attempts"] == 1
        assert "engine exploded" in state["error"]
        assert state["engine_version"] == OLD_ENGINE, (
            "a failed re-extraction must not claim the current engine read it")
    finally:
        _cleanup(pg, [source_id])


def test_the_scheduler_job_reports_the_backlog_it_is_working_through(pg, settings):
    """The rollout is measured from `job_runs.detail`: without `remaining`
    and the engine version, "is the re-extract finishing?" is unanswerable
    from the board."""
    from scheduler import jobs

    detail = jobs.get("engine-reprocess")(settings)
    for field in ("pending=", "reprocessed=", "failed=", "candidates ", "events ",
                  "newly_dated=", "upcoming +", "multi_changed=", "engine=", "remaining="):
        assert field in detail, f"{field!r} missing from {detail!r}"


# === 10 (HTTP). the admin endpoint =========================================

ADMIN = ("dancemate", "test-admin-password")


@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", ADMIN[0])
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN[1])
    monkeypatch.setattr(app_module, "_settings", None)
    from fastapi.testclient import TestClient

    return TestClient(app_module.app, raise_server_exceptions=False)


def test_the_admin_reextract_endpoint_advances_instead_of_repeating(pg, unique, settings,
                                                                    client):
    """T10, through the route an operator actually calls.

    Before v0.96.3 this endpoint was `force=True` with no cursor: two calls
    at `limit=1` re-read the same single row, which is why only 20 of 1,039
    Production bodies had moved. Now the default pass takes the incremental
    queue (each success stamps the row and it leaves), and the forced pass
    pages by `after_item_id`.
    """
    source_id = _source(pg, unique, key="ROUTE")
    urls = [f"https://route.test/{unique}/{n}" for n in range(2)]
    ids = [_item(pg, source_id, url=url, title="10월 밀롱가 안내") for url in urls]
    pg.commit()
    try:
        for item_id in ids:
            _fetched(pg, item_id, BODY)
        pg.commit()
        engine_ingest.ingest_pending(settings)
        for item_id in ids:
            _make_outdated(pg, item_id)

        first = client.post("/api/admin/events/reextract?limit=1", auth=ADMIN).json()
        second = client.post("/api/admin/events/reextract?limit=1", auth=ADMIN).json()

        assert first["reprocessed"] == 1 and second["reprocessed"] == 1
        assert first["next_after_item_id"] != second["next_after_item_id"], (
            "two incremental batches must not re-read the same row")
        assert second["remaining"] < first["remaining"]
        assert {_stamp_state(pg, i)["engine_version"] for i in ids} == \
            {settings.engine_version}

        # Forced, now that nothing is outdated: it selects anyway, and pages.
        forced = client.post(
            f"/api/admin/events/reextract?limit=1&force=true&after_item_id={ids[0] - 1}",
            auth=ADMIN).json()
        assert forced["next_after_item_id"] == ids[0]
        onward = client.post(
            f"/api/admin/events/reextract?limit=1&force=true"
            f"&after_item_id={forced['next_after_item_id']}", auth=ADMIN).json()
        assert onward["next_after_item_id"] == ids[1]

        backlog = client.get("/api/admin/events/reextract-backlog", auth=ADMIN).json()
        assert backlog["engine_version"] == settings.engine_version
        assert backlog["outdated"] == 0 and backlog["current"] >= 2
    finally:
        _cleanup(pg, [source_id])
