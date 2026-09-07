"""v0.84.3: image-only posters become eligible for OCR fallback.

Two structural gaps, both real production bugs found on K-TANGO, made the
existing v0.81.3 OCR fallback pipeline unreachable for an image-only post:

  1. `acquisition.fetch()`'s FETCH_BLOCKED branch never populated `images`,
     so a real poster's URL was discarded the moment the body came up empty.
  2. `content_store.needing_reprocess()` only ever selected FETCHED_FULL/
     PARTIAL rows, so even a FETCH_BLOCKED row that *did* carry a poster
     candidate was never handed back to the engine for image-only recovery.

`runtime.acquisition`'s own test file covers gap 1 (`extract_content_images`,
FETCH_BLOCKED now carrying `images`). This file covers gap 2 against the real
staging PostgreSQL (the `pg` fixture rolls back) - nothing here calls
normalize_all()/ingest_pending()/reprocess_acquired() in bulk, per the
v0.82.2 safety rule.
"""

from __future__ import annotations

from runtime import acquisition, content_store, engine_ingest, image_fetch, ocr


def _source_item(pg, unique, suffix="1"):
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-OCR-{unique}-{suffix}", name=f"ocr probe {unique}",
        platform="WEB", source_role="COMMUNITY",
        url=f"https://example.invalid/{unique}/{suffix}", enabled=False)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, title, content_hash) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING source_item_id",
            (source["source_id"], f"ext-{unique}-{suffix}",
             f"https://example.invalid/{unique}/{suffix}/post", "ocr probe",
             f"hash-{unique}-{suffix}"))
        return cur.fetchone()[0]


def _blocked_outcome(images):
    return acquisition.AcquisitionOutcome(
        status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE,
        fetched_url="https://example.invalid/post", images=images,
        error_code="BODY_UNAVAILABLE", error="page fetched but no article body was served",
    )


def _full_outcome(text="a real fetched article body, well past the threshold" * 3):
    return acquisition.AcquisitionOutcome(
        status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
        fetched_url="https://example.invalid/post", text=text,
    )


# --- the core v0.84.3 gap: FETCH_BLOCKED-with-poster becomes reprocessable --

def test_a_blocked_item_with_a_poster_is_selected_for_reprocessing(pg, unique):
    item_id = _source_item(pg, unique)
    content_store.record_outcome(pg, item_id, _blocked_outcome(
        ["https://cdn.example.test/poster.jpg"]
    ))
    selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
    assert item_id in selected


def test_a_blocked_item_with_no_poster_is_not_selected_for_reprocessing(pg, unique):
    item_id = _source_item(pg, unique)
    content_store.record_outcome(pg, item_id, _blocked_outcome([]))
    selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
    assert item_id not in selected


def test_a_settled_full_item_is_still_selected_unchanged(pg, unique):
    """Non-regression: the existing FETCHED_FULL/PARTIAL reprocess path (the
    whole reason this function exists before v0.84.3) must be untouched."""
    item_id = _source_item(pg, unique)
    content_store.record_outcome(pg, item_id, _full_outcome())
    selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
    assert item_id in selected


def test_a_reprocessed_blocked_item_is_not_selected_again(pg, unique):
    item_id = _source_item(pg, unique)
    content_store.record_outcome(pg, item_id, _blocked_outcome(
        ["https://cdn.example.test/poster.jpg"]
    ))
    content_store.mark_reprocessed(pg, item_id)
    selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
    assert item_id not in selected


def test_a_re_fetched_blocked_item_is_eligible_again_after_reprocessing(pg, unique):
    """A FETCH_BLOCKED outcome never sets `fetched_at` (it means "we got a
    body", which a blocked fetch by definition did not), so gating this
    branch on `fetched_at` the way FETCHED_FULL/PARTIAL is gated would make
    it permanently ineligible the moment `reprocessed_at` is set at all -
    found running this exact scenario against real K-TANGO production rows,
    every one of which already had a `reprocessed_at` from its original
    ingest. `record_outcome()` bumps `updated_at` on every fetch regardless
    of outcome, so a genuine re-fetch (the scheduler's own backoff-scheduled
    retry, not a spurious call) re-enters the queue exactly like
    FETCHED_FULL/PARTIAL already does on every successful fetch - even one
    that finds no new content. Re-running OCR on an unchanged poster is
    idempotent and cheap (the existing content-hash cache in
    runtime.image_fallback skips the actual Tesseract call), so this
    symmetry costs nothing but a little redundant engine-side reading."""
    item_id = _source_item(pg, unique)
    content_store.record_outcome(pg, item_id, _blocked_outcome(
        ["https://cdn.example.test/poster.jpg"]
    ))
    content_store.mark_reprocessed(pg, item_id)
    # `mark_reprocessed()` and `record_outcome()` both stamp their column
    # with SQL now(), which Postgres freezes for the whole transaction - the
    # `pg` fixture's own single, rolled-back transaction, so a second
    # `now()` call here would read back identical to the first regardless of
    # real elapsed time. Backdating `reprocessed_at` explicitly is the
    # test's own concern, not a change to how production actually orders
    # these two real, separately-committed calls a scheduler tick apart.
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET reprocessed_at = reprocessed_at - interval '1 hour' "
            "WHERE source_item_id = %s", (item_id,),
        )
    content_store.record_outcome(pg, item_id, _blocked_outcome(
        ["https://cdn.example.test/poster.jpg"]
    ))
    selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
    assert item_id in selected


def test_poster_candidates_are_stored_as_the_images_list(pg, unique):
    item_id = _source_item(pg, unique)
    content_store.record_outcome(pg, item_id, _blocked_outcome(
        ["https://cdn.example.test/poster.jpg"]
    ))
    row = content_store.get(pg, item_id)
    assert row["poster_candidates"] == ["https://cdn.example.test/poster.jpg"]
    assert row["image_count"] == 1


# --- the real production regression: reprocess_acquired() never wired up ---
# image fallback at all, so an image-only item now-selected by
# needing_reprocess() would re-extract to nothing and hit the unconditional
# "replace this post's candidates with whatever the engine now makes of it"
# delete below it - losing a real, previously-correct event. Found live: a
# K-TANGO event (date correctly OCR'd from its own poster, back when the
# post was still FETCHED_FULL pre-v0.84.2) was deleted the moment this
# release's fix made the item eligible for reprocessing again.

def _pending_item(pg, unique, title, url):
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-REP-{unique}", name=f"reprocess probe {unique}",
        platform="WEB", source_role="ORGANIZER",
        url=f"https://example.invalid/reprocess/{unique}",
        enabled=False)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items "
            "(source_id, external_id, url, title, content_hash, ingest_state) "
            "VALUES (%s, %s, %s, %s, %s, 'PENDING') RETURNING source_item_id",
            (source["source_id"], f"ext-rep-{unique}", url, title, f"hash-rep-{unique}"))
        return cur.fetchone()[0]


def test_reprocessing_an_image_only_item_recovers_from_its_poster_not_nothing(
    pg, unique, env, monkeypatch
):
    """ingest_pending() and reprocess_acquired() each open their own
    autocommit connection (they are written to run standalone, as scheduler
    jobs) - invisible to the `pg` fixture's own uncommitted transaction, so
    this test commits its own writes and cleans them up explicitly instead
    of relying on the fixture's usual rollback."""
    from runtime import engine_adapter
    from runtime.config import load_settings
    import sqlite3

    title = "탱고 이벤트"
    url = "https://example.invalid/reprocess/post"
    item_id = _pending_item(pg, unique, title, url)
    pg.commit()
    settings = load_settings()

    try:
        # The body the site originally served: a real, complete announcement.
        # An explicit year avoids needing a `published_at` on the fixture
        # row - the same v0.80.2 rule that would otherwise leave the date
        # unresolved.
        content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
            fetched_url=url,
            text="2026.09.05 19:30-23:30 장소: 라밀롱가 스튜디오 입장료 13,000원",
        ))
        pg.commit()
        result = engine_ingest.ingest_pending(settings)
        assert result["ingested"] == 1

        def _events_for(source_url):
            con = sqlite3.connect(engine_adapter.engine_db_path(settings))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT ec.* FROM event_candidates ec "
                "JOIN raw_posts rp ON rp.post_id = ec.post_id "
                "WHERE rp.source_url = ?", (source_url,),
            ).fetchall()
            con.close()
            return [dict(r) for r in rows]

        before = _events_for(url)
        assert len(before) == 1
        assert before[0]["event_date"] == "2026-09-05"

        # The site now serves an image-only version of the same post: no
        # body text at all, just a poster naming the same event.
        content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
            status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE,
            fetched_url=url, images=["https://cdn.example.test/poster.jpg"],
            error_code="BODY_UNAVAILABLE", error="page fetched but no article body was served",
        ))
        pg.commit()
        monkeypatch.setattr(image_fetch, "fetch_image", lambda u, **kw: image_fetch.ImageFetchResult(
            url=u, status="FETCHED", content_type="image/jpeg", data=b"\xff\xd8\xff fake"))
        monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: ocr.OcrResult(
            status=ocr.STATUS_SUCCESS, confidence=88.0, width=800, height=600,
            text="탱고 이벤트 2026.09.05 19:30~23:30 장소: 라밀롱가 스튜디오 입장료 13,000원"))

        selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
        assert item_id in selected

        outcome = engine_ingest.reprocess_acquired(settings)
        assert outcome["reprocessed"] == 1
        assert outcome["failed"] == 0

        after = _events_for(url)
        assert len(after) == 1, (
            "the real event must survive being reprocessed from an "
            "image-only fetch, not be silently deleted for lack of "
            "image-fallback wiring"
        )
        assert after[0]["event_date"] == "2026-09-05"
        assert after[0]["venue"] == "라밀롱가 스튜디오"
    finally:
        # This test committed its own writes (see docstring) - the `pg`
        # fixture's rollback at teardown cannot undo them, so clean up
        # explicitly rather than leaving rows in the shared staging database.
        with pg.cursor() as cur:
            cur.execute("DELETE FROM events WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM source_item_content WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM source_items WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM sources WHERE source_key = %s", (f"SRC-REP-{unique}",))
        pg.commit()
