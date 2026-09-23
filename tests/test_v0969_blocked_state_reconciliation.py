"""v0.96.9 - FETCH_BLOCKED is a fetch outcome, not a reason to freeze a state.

Measured on Production f9a719e (2026-09-23), 1,105 blocked items:

  641 carry an engine candidate, 271 carry an Event, and 1,081 of the 1,105
  had never been read by *any* engine version, because
  `needing_reprocess()`'s readable-content gate asked about
  `source_item_content.extracted_text` - a column `_to_raw_post()` does not
  read for a blocked item and `record_outcome()` overwrites with NULL on
  every refusal. Re-running engine 0.95 over the text those items actually
  do hold retires 129 Events: 126 of them the club's-own-video / photo /
  후기 / 경품 recaps v0.96.8 corrected and could not reach, and 3 lessons
  v0.96.7 reclassified. None is upcoming, none is reviewed, all 129 were
  read by hand.

  Of the same 1,105, exactly **six** were ever served a body they no longer
  hold: the K-TANGO 643/644/646/647/648/649 group, fetched once at ~720
  characters and refused four times since. Re-extracting three of those
  without a guard replaces a correct `event_date` with NULL - the v0.84.3
  regression that 647 is named for, reproduced in simulation before this
  release was written.

So the two populations are real, and they are told apart by evidence rather
than by status: `content_fetch_log` is append-only and still remembers the
722-character body 647 was served, long after the content row stopped being
able to. The rules under test:

  T1/T8  blocked + a body the fetch log says is gone  -> Event preserved
  T2/T9  blocked + the input that made the candidate  -> stale Event retired
  T3/T11 blocked + preserved input + still an event   -> candidate/Event ids kept
  T4     a re-readable blocked row joins the incremental queue
  T5/T12 a protected row is stamped, so it leaves the queue for good
  T6     a reconciled row is not selected again on the next tick
  T7     a reviewed candidate is never touched by any of it
  T10    a known_event_type does not exempt a row from any of the above

Store-level tests run inside the `pg` fixture's rolled-back transaction.
Engine-level ones drive `reprocess_acquired()`, which opens its own
autocommit connection, so they commit and clean up after themselves - the
discipline tests/test_v0963_incremental_reextract.py established.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from runtime import (
    acquisition,
    candidates as candidate_store,
    content_store,
    db,
    engine_adapter,
    engine_ingest,
    normalization,
    sources,
)

PUBLISHED = "2026-09-14"
OLD_ENGINE = "0.94"

# A post the running engine reads as a real milonga, used wherever a test
# needs a blocked item that genuinely still is an event.
EVENT_TEXT = "밀롱가 2026.10.10 20:00-23:00 장소: 스튜디오 오초 회비 10,000원"

# Production's own shape for the 126 stranded recaps: the night happened, the
# post is the club's video of it. `is_non_event_notice()` reads the title.
RECAP_TITLE = "전주라틴크루즈 생일자정모 (24/04/01) 영상 #14 라이더&너랑나랑 살사소셜"


# --- helpers ----------------------------------------------------------------

def _quiesce(pg, engine_version: str) -> None:
    """Stamp every pre-existing content row as current, so a selection test
    owns the whole queue. Rolled back with the `pg` fixture's transaction."""
    with pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET extracted_engine_version = %s",
                    (engine_version,))


def _source(pg, unique, key="BLK"):
    return sources.create_source(
        pg, source_key=f"{key}-{unique}", name=f"{key} {unique}", platform="WEB",
        source_role="COMMUNITY", url=f"https://{key.lower()}.test/{unique}",
        enabled=False,
    )["source_id"]


def _item(pg, source_id, *, url, title, body="", known_event_type=None):
    """A collected item, with the discovery payload a blocked fetch leaves as
    the only thing `_to_raw_post()` has to work with."""
    raw = {"platform": "WEB", "published_at": PUBLISHED, "body": body,
           "acquisition_quality": "METADATA_ONLY", "title": title}
    if known_event_type:
        raw["known_event_type"] = known_event_type
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, title, content_hash, "
            "  raw, ingest_state) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'PENDING') "
            "RETURNING source_item_id",
            (source_id, url, url, title, f"hash-{url}", json.dumps(raw)),
        )
        return cur.fetchone()[0]


def _blocked(pg, item_id, url, *, images=()):
    """A refusal: no body served. Note what this does to the content row -
    `extracted_text` NULL, `content_length` 0, `fetched_at` back to NULL -
    which is exactly why the fetch log, not this row, has to answer "was
    there ever more?"."""
    content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE,
        fetched_url=url, images=list(images),
        error_code="BODY_UNAVAILABLE",
        error="page fetched but no article body was served",
    ))


def _fetched(pg, item_id, url, text):
    content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
        fetched_url=url, text=text,
    ))


def _stamp_state(pg, item_id):
    with pg.cursor() as cur:
        cur.execute("SELECT extracted_engine_version FROM source_item_content "
                    "WHERE source_item_id = %s", (item_id,))
        return cur.fetchone()[0]


def _make_outdated(pg, item_id, version=OLD_ENGINE):
    with pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET extracted_engine_version = %s "
                    "WHERE source_item_id = %s", (version, item_id))
    pg.commit()


def _queued(pg, source_id, engine_version):
    rows = content_store.needing_reprocess(
        pg, engine_version=engine_version, limit=1000)
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id FROM source_items WHERE source_id = %s",
                    (source_id,))
        mine = {r[0] for r in cur.fetchall()}
    return [r["source_item_id"] for r in rows if r["source_item_id"] in mine]


# === the engine store =======================================================

def _engine_con(settings):
    con = sqlite3.connect(engine_adapter.engine_db_path(settings))
    con.row_factory = sqlite3.Row
    return con


def _candidates(settings, url):
    con = _engine_con(settings)
    try:
        rows = con.execute(
            "SELECT c.candidate_id, c.name AS event_name, c.event_date, c.start_time, "
            "       c.end_time, c.end_day_offset, c.venue, c.event_type, c.fee, "
            "       c.fee_display_text, c.dj, c.status AS candidate_status, "
            "       p.post_id, p.source_url "
            "FROM event_candidates c JOIN raw_posts p ON p.post_id = c.post_id "
            "WHERE p.source_url = ? ORDER BY c.candidate_id", (url,),
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


def _legacy_candidate(settings, url, *, name, event_date, event_type="SOCIAL",
                      image_ocr=False):
    """The candidate an engine older than the running one left behind.

    This is what Production actually holds for the 129 stale rows: a row the
    current classifier would never produce from the same text, because the
    text is not what changed. Writing it by hand is the only honest way to
    stage that - the old engine is not importable, and rewriting the item's
    stored input would stage the opposite situation, the one this release
    still refuses to reconcile.
    """
    con = _engine_con(settings)
    try:
        post_id = con.execute(
            "SELECT post_id FROM raw_posts WHERE source_url = ?", (url,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO event_candidates (post_id, name, event_type, event_date, "
            "  start_time, venue, status, core_complete) "
            "VALUES (?,?,?,?,?,?,'POSSIBLE',0)",
            (post_id, name, event_type, event_date, "20:00", "스튜디오 오초"),
        )
        candidate_id = cur.lastrowid
        if image_ocr:
            con.execute(
                "INSERT INTO evidences (candidate_id, field, value, raw_text, "
                "  evidence_type, source_role, inference) "
                "VALUES (?, 'event_date', ?, ?, ?, 'COMMUNITY', ?)",
                (candidate_id, event_date, event_date,
                 engine_ingest.IMAGE_OCR_EVIDENCE, "https://cdn.example.test/poster.jpg"),
            )
        con.commit()
        return candidate_id
    finally:
        con.close()


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


def _cleanup(pg, source_ids):
    with pg.cursor() as cur:
        cur.execute(
            "DELETE FROM candidate_normalization WHERE candidate_id IN ("
            "  SELECT candidate_id FROM events WHERE source_item_id IN ("
            "    SELECT source_item_id FROM source_items WHERE source_id = ANY(%s)))",
            (source_ids,))
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
            "DELETE FROM content_fetch_log WHERE source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))",
            (source_ids,))
        cur.execute(
            "DELETE FROM source_item_content WHERE source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))",
            (source_ids,))
        cur.execute("DELETE FROM source_items WHERE source_id = ANY(%s)", (source_ids,))
        cur.execute("DELETE FROM sources WHERE source_id = ANY(%s)", (source_ids,))
    pg.commit()


@pytest.fixture
def settings(env):
    from runtime.config import load_settings

    return load_settings()


# === what the fetch log remembers that the content row cannot ===============

def test_a_refusal_erases_the_body_from_the_content_row_but_not_from_the_log(pg, unique):
    """The measurement this whole release rests on. After a fetch and then a
    refusal, `source_item_content` looks identical to a row that was refused
    from the start - same NULL text, same 0 length, same NULL `fetched_at`.
    Production's 647 is this row, four refusals later."""
    source_id = _source(pg, unique, key="LOG")
    url = f"https://log.test/{unique}/1"
    once_fetched = _item(pg, source_id, url=url, title="한강탱고축제")
    never_fetched = _item(pg, source_id, url=f"{url}/b", title="한강탱고축제 후기")

    _fetched(pg, once_fetched, url, EVENT_TEXT)
    _blocked(pg, once_fetched, url)
    _blocked(pg, never_fetched, f"{url}/b")

    rows = {i: content_store.get(pg, i) for i in (once_fetched, never_fetched)}
    for row in rows.values():
        assert row["acquisition_status"] == acquisition.FETCH_BLOCKED
        assert row["extracted_text"] is None
        assert row["fetched_at"] is None

    best = content_store.best_fetched_text_length(pg, [once_fetched, never_fetched])
    assert best[once_fetched] == len(EVENT_TEXT)
    assert never_fetched not in best, (
        "an item that was never served a body has lost nothing, and must not "
        "be reported as though it had")


def test_a_refused_fetch_is_not_counted_as_a_body_we_once_held(pg, unique):
    """`content_fetch_log` records refusals too, at text_length 0. Counting
    those would make every blocked item look like a loss and restore exactly
    the blanket preservation this release exists to remove."""
    source_id = _source(pg, unique, key="LOGZERO")
    url = f"https://logzero.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title="공지")
    for _ in range(4):
        _blocked(pg, item_id, url)

    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM content_fetch_log WHERE source_item_id = %s",
                    (item_id,))
        assert cur.fetchone()[0] == 4
    assert content_store.best_fetched_text_length(pg, [item_id]) == {}


# === T4. queue eligibility ==================================================

def test_a_blocked_item_the_engine_can_read_joins_the_incremental_queue(pg, unique):
    """T4. The 1,081 Production rows no engine version could reach. A blocked
    item is re-read from its discovery title and snippet, so that - not the
    content row's wiped `extracted_text` - is what decides whether there is
    anything to re-read."""
    _quiesce(pg, OLD_ENGINE)
    source_id = _source(pg, unique, key="QUEUE")
    url = f"https://queue.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title=RECAP_TITLE)
    _blocked(pg, item_id, url)

    assert content_store.get(pg, item_id)["extracted_text"] is None
    assert _queued(pg, source_id, "0.95") == [item_id]

    content_store.mark_reprocessed(pg, item_id, engine_version="0.95")
    assert _queued(pg, source_id, "0.95") == [], "T6: a stamped row leaves for good"
    assert _queued(pg, source_id, "0.96") == [item_id], "the next bump reaches it again"


def test_a_blocked_item_with_nothing_readable_at_all_stays_out(pg, unique):
    """No title, no snippet, no poster: re-reading it would hand the engine an
    empty string. The widened gate must not become "every blocked row"."""
    _quiesce(pg, OLD_ENGINE)
    source_id = _source(pg, unique, key="EMPTY")
    url = f"https://empty.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title="")
    with pg.cursor() as cur:
        cur.execute("UPDATE source_items SET title = NULL WHERE source_item_id = %s",
                    (item_id,))
    _blocked(pg, item_id, url)

    assert _queued(pg, source_id, "0.95") == []


def test_the_backlog_report_counts_the_blocked_rows_it_now_selects(pg, unique):
    """`reprocess_backlog()` is what a rollout is watched on, so it has to
    apply the same readable-content rule the queue does or convergence would
    be reported against a denominator that excludes the work."""
    _quiesce(pg, OLD_ENGINE)
    before = content_store.reprocess_backlog(pg, "0.95")
    source_id = _source(pg, unique, key="BACKLOG")
    url = f"https://backlog.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title=RECAP_TITLE)
    _blocked(pg, item_id, url)

    after = content_store.reprocess_backlog(pg, "0.95")
    assert after["with_content"] == before["with_content"] + 1
    assert after["outdated"] == before["outdated"] + 1

    content_store.mark_reprocessed(pg, item_id, engine_version="0.95")
    done = content_store.reprocess_backlog(pg, "0.95")
    assert done["current"] == before["current"] + 1
    assert done["outdated"] == before["outdated"]
    assert done["current"] + done["outdated"] + done["stalled"] == done["with_content"]


# === T1/T8. the body the fetch log says is gone =============================

def test_a_blocked_item_whose_fetched_body_is_gone_keeps_its_event(pg, unique, settings):
    """T1 + T8, the 647 contract. This item was served a real body once and
    refused since; its candidate was built from text the content row no
    longer holds. Whatever the engine now makes of the title alone is a
    verdict on less evidence and must not retire the better-informed one -
    and the row must still leave the queue, or "protected" would be
    indistinguishable from "backlog" forever."""
    source_id = _source(pg, unique, key="LOST")
    url = f"https://lost.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title="한강탱고축제")
    pg.commit()
    try:
        _fetched(pg, item_id, url, EVENT_TEXT)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _candidates(settings, url)
        assert len(before) == 1
        event = _normalize(pg, before[0])
        assert event is not None

        # The later refusal that wipes the body the candidate was built from.
        _blocked(pg, item_id, url)
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=200)

        assert result["failed"] == 0
        assert result["blocked_preserved_body_lost"] >= 1
        assert result["blocked_preserved_input_loss"] >= 1
        after = _candidates(settings, url)
        assert [c["candidate_id"] for c in after] == [before[0]["candidate_id"]], (
            "the candidate must be untouched, not re-extracted from less text")
        assert after[0]["event_date"] == before[0]["event_date"]
        assert _event_row(pg, event["event_id"]) is not None

        # T5/T12: protected is a finished state, not a permanent backlog.
        assert _stamp_state(pg, item_id) == settings.engine_version
        assert _queued(pg, source_id, settings.engine_version) == []
    finally:
        _cleanup(pg, [source_id])


def test_a_blocked_item_read_off_a_poster_keeps_its_event_when_the_poster_is_unreadable(
        pg, unique, settings):
    """The other half of the 647 shape. Nothing about the stored text
    changed, so the fetch log reports no loss - but the candidate's date came
    off a poster, and this pass could not read one. Re-extracting from the
    text alone would delete a real event for a reason that is about the image
    fetch, not about the post."""
    source_id = _source(pg, unique, key="POSTER")
    url = f"https://poster.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title="공지 2025 K-TANGO CF 일정표 NEW")
    pg.commit()
    try:
        _blocked(pg, item_id, url, images=["https://cdn.example.test/poster.jpg"])
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        assert _candidates(settings, url) == [], (
            "fixture sanity: the title alone is not an event to this engine")
        candidate_id = _legacy_candidate(
            settings, url, name="2025 K-TANGO CF", event_date="2025-05-08",
            event_type="MILONGA", image_ocr=True)
        event = _normalize(pg, _candidates(settings, url)[0])
        assert event is not None
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=200)

        assert result["failed"] == 0
        assert result["blocked_preserved_image_evidence_lost"] >= 1
        assert [c["candidate_id"] for c in _candidates(settings, url)] == [candidate_id]
        assert _event_row(pg, event["event_id"]) is not None
        assert _stamp_state(pg, item_id) == settings.engine_version
    finally:
        _cleanup(pg, [source_id])


# === T2/T9/T10. the input that made the candidate is still here =============

def test_a_blocked_item_that_never_lost_anything_reconciles_to_the_current_engine(
        pg, unique, settings):
    """T2 + T9 + T10, and the 126 Production rows v0.96.8 corrected and could
    not reach. This item was refused from the start: the recap title its
    candidate was built from is the very text the engine reads now. A
    `known_event_type` does not exempt it - v0.96.8 put the non-event notice
    check above KET precisely so a club's own video of a past night stops
    being an event - and neither does the blocked status."""
    source_id = _source(pg, unique, key="STALE")
    url = f"https://stale.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title=RECAP_TITLE,
                    known_event_type="SOCIAL")
    # A second, genuine event on the same source. `_prune_orphans()` refuses
    # to act on an empty candidate set - "I cannot see the candidates" must
    # never be read as "there are none" - so a store holding nothing else
    # would prove the prune ran when it had simply declined to.
    keeper_url = f"https://stale.test/{unique}/2"
    keeper_id = _item(pg, source_id, url=keeper_url, title="10월 밀롱가 안내",
                      body=EVENT_TEXT)
    pg.commit()
    try:
        _blocked(pg, item_id, url)
        _blocked(pg, keeper_id, keeper_url)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 2
        assert _candidates(settings, url) == []
        keeper = _candidates(settings, keeper_url)
        assert len(keeper) == 1
        keeper_event = _normalize(pg, keeper[0])
        candidate_id = _legacy_candidate(
            settings, url, name="전주라틴크루즈 생일자정모", event_date="2024-04-01")
        event = _normalize(pg, _candidates(settings, url)[0])
        assert event is not None and event["candidate_id"] == candidate_id
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=200)

        assert result["failed"] == 0
        assert result["blocked_preserved_input_loss"] == 0
        assert result["blocked_reconciled"] >= 1
        assert result["stale_event_removed"] >= 1
        assert _candidates(settings, url) == [], (
            "the engine no longer stands behind this candidate, and the input "
            "it decided that on is the input that made it")

        # The Event goes the ordinary way - orphaned by the candidate's
        # removal, retired by normalization's own prune. No SQL DELETE here.
        assert _event_row(pg, event["event_id"])["candidate_id"] == candidate_id
        with db.connect(settings) as con:
            pruned = normalization._prune_orphans(
                con, candidate_store.all_candidate_ids(settings))
            con.commit()
        assert pruned >= 1
        pg.commit()  # read the prune's own commit, not this session's snapshot
        assert _event_row(pg, event["event_id"]) is None
        assert _event_row(pg, keeper_event["event_id"]) is not None, (
            "reconciliation retires the candidate that lost its engine, "
            "never the ones that still have one")

        assert _stamp_state(pg, item_id) == settings.engine_version
        assert _queued(pg, source_id, settings.engine_version) == []
    finally:
        _cleanup(pg, [source_id])


# === T3/T11. still an event: identity is kept ===============================

def test_a_blocked_item_that_is_still_an_event_keeps_its_candidate_and_event_id(
        pg, unique, settings):
    """T3 + T11. Reconciliation is not deletion: the 139 Production rows the
    current engine still reads as events must come through with the same
    candidate_id and the same event_id. A 1->1 re-read that issued a new
    Event id would be a release blocker."""
    source_id = _source(pg, unique, key="KEEP")
    url = f"https://keep.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title="10월 밀롱가 안내", body=EVENT_TEXT)
    pg.commit()
    try:
        _blocked(pg, item_id, url)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _candidates(settings, url)
        assert len(before) == 1 and before[0]["event_date"] == "2026-10-10"
        event = _normalize(pg, before[0])
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=200)

        assert result["failed"] == 0
        assert result["stale_event_removed"] == 0
        after = _candidates(settings, url)
        assert [c["candidate_id"] for c in after] == [before[0]["candidate_id"]]
        assert after[0]["event_date"] == before[0]["event_date"]
        row = _event_row(pg, event["event_id"])
        assert row is not None and row["candidate_id"] == before[0]["candidate_id"]
    finally:
        _cleanup(pg, [source_id])


# === T7. a person's decision outranks all of it =============================

def test_a_reviewed_candidate_on_a_blocked_item_is_never_reconciled(
        pg, unique, settings):
    """T7. Review state is keyed by candidate_id, so reconciling a reviewed
    candidate would silently orphan somebody's decision - and this release
    widens exactly the queue that reaches them. The skip runs before any
    input question is asked, and still stamps."""
    source_id = _source(pg, unique, key="REV")
    url = f"https://rev.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title=RECAP_TITLE,
                    known_event_type="SOCIAL")
    pg.commit()
    try:
        _blocked(pg, item_id, url)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        candidate_id = _legacy_candidate(
            settings, url, name="전주라틴크루즈 생일자정모", event_date="2024-04-01")
        event = _normalize(pg, _candidates(settings, url)[0])
        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO human_review_actions (candidate_id, source_item_id, action) "
                "VALUES (%s, %s, 'APPROVE')", (candidate_id, item_id))
        pg.commit()
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=200)

        assert result["failed"] == 0
        assert result["blocked_preserved_reviewed"] >= 1
        assert result["blocked_reconciled"] == 0
        assert [c["candidate_id"] for c in _candidates(settings, url)] == [candidate_id]
        assert _event_row(pg, event["event_id"]) is not None
        assert _stamp_state(pg, item_id) == settings.engine_version
    finally:
        _cleanup(pg, [source_id])


# === T6/T12. one pass each, restart or no restart ===========================

def test_a_second_tick_selects_neither_the_reconciled_nor_the_protected_row(
        pg, unique, settings):
    """T6 + T12. Both outcomes stamp, so the queue shrinks whichever way an
    item goes and a process that dies mid-pass resumes instead of starting
    over. A protected row that never stamped would sit at the head of every
    future tick and starve everything behind it - v0.96.1's own lesson."""
    source_id = _source(pg, unique, key="TICK")
    stale_url = f"https://tick.test/{unique}/stale"
    lost_url = f"https://tick.test/{unique}/lost"
    stale_id = _item(pg, source_id, url=stale_url, title=RECAP_TITLE,
                     known_event_type="SOCIAL")
    lost_id = _item(pg, source_id, url=lost_url, title="한강탱고축제")
    pg.commit()
    try:
        _blocked(pg, stale_id, stale_url)
        _fetched(pg, lost_id, lost_url, EVENT_TEXT)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 2
        _legacy_candidate(settings, stale_url, name="정모", event_date="2024-04-01")
        _blocked(pg, lost_id, lost_url)
        pg.commit()
        _make_outdated(pg, stale_id)
        _make_outdated(pg, lost_id)

        first = engine_ingest.reprocess_acquired(settings, limit=200)
        assert first["failed"] == 0
        assert first["blocked_selected"] >= 2
        assert first["blocked_reconciled"] >= 1
        assert first["blocked_preserved_input_loss"] >= 1

        assert _queued(pg, source_id, settings.engine_version) == []
        second = engine_ingest.reprocess_acquired(settings, limit=200)
        assert second["blocked_selected"] == 0 or (
            stale_id, lost_id) not in second.get("failures", [])
        assert _stamp_state(pg, stale_id) == settings.engine_version
        assert _stamp_state(pg, lost_id) == settings.engine_version
    finally:
        _cleanup(pg, [source_id])


# === observability ==========================================================

def test_the_blocked_counters_account_for_every_blocked_row_selected(
        pg, unique, settings):
    """Section 16: an operator watching this rollout needs to see which of
    the four things happened to each blocked row, not a single total that
    cannot distinguish "protected" from "did nothing"."""
    source_id = _source(pg, unique, key="COUNT")
    url = f"https://count.test/{unique}/1"
    item_id = _item(pg, source_id, url=url, title=RECAP_TITLE,
                    known_event_type="SOCIAL")
    pg.commit()
    try:
        _blocked(pg, item_id, url)
        pg.commit()
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        _legacy_candidate(settings, url, name="정모", event_date="2024-04-01")
        _make_outdated(pg, item_id)

        result = engine_ingest.reprocess_acquired(settings, limit=200)

        accounted = (result["blocked_reconciled"]
                     + result["blocked_preserved_input_loss"]
                     + result["blocked_preserved_reviewed"]
                     + result["blocked_failed"])
        assert accounted == result["blocked_selected"]
        assert (result["blocked_preserved_body_lost"]
                + result["blocked_preserved_image_evidence_lost"]
                == result["blocked_preserved_input_loss"])
    finally:
        _cleanup(pg, [source_id])
