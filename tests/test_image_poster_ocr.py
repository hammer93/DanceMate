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

v0.84.4 adds a third gap this file also covers: even with both gaps above
fixed, process_discovered_post() classified from title+body alone, before
image_texts was ever consulted - a genuinely image-only post (empty body)
always classified OTHER and never reached extraction. See
engine.classifier.classify_with_image_evidence() and
runtime.image_fallback.gather_trusted_classification_texts() for the fix;
the tests near the end of this file cover the DB-integration and runtime-
wiring side of it.
"""

from __future__ import annotations

from runtime import acquisition, content_store, engine_ingest, image_fallback, image_fetch, ocr


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
#
# Wiring image_texts into reprocess_acquired() (below) is not, by itself,
# enough to stop that: process_discovered_post() classifies from title+body
# alone before it ever looks at image_texts, and a FETCH_BLOCKED item's body
# is empty - so a genuinely image-only post still classifies as OTHER and
# still produces zero events, wiring or no wiring. That gap is real and is
# documented, deliberately unfixed, scope for this release (it would mean
# changing what classify() itself is allowed to see). What *is* in scope,
# and what the guard in reprocess_acquired() below provides, is refusing to
# let "we couldn't classify this blocked fetch" be read as "the engine says
# this is no longer an event" - the two are not the same claim, and only the
# second one should ever delete a real candidate.

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


def _events_for(settings, source_url):
    from runtime import engine_adapter
    import sqlite3

    con = sqlite3.connect(engine_adapter.engine_db_path(settings))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT ec.* FROM event_candidates ec "
        "JOIN raw_posts rp ON rp.post_id = ec.post_id "
        "WHERE rp.source_url = ?", (source_url,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def test_reprocessing_a_blocked_item_preserves_its_existing_event_instead_of_deleting_it(
    pg, unique, env, monkeypatch
):
    """ingest_pending() and reprocess_acquired() each open their own
    autocommit connection (they are written to run standalone, as scheduler
    jobs) - invisible to the `pg` fixture's own uncommitted transaction, so
    this test commits its own writes and cleans them up explicitly instead
    of relying on the fixture's usual rollback.

    This is the shape of the K-TANGO 647 incident with a poster that OCR'd
    fine but reads as nothing recognizable (v0.84.4's own K-TANGO detect-
    only found real posters exactly this unreadable, e.g. source_items 643/
    648/649) - image-aware classification (v0.84.4) still correctly leaves
    this as OTHER (no social/milonga signal at all), so the v0.84.3 guard
    below it is still what protects the real prior event. See
    test_reprocessing_a_blocked_item_with_a_readable_poster_now_recovers_
    via_image_aware_classification for the case a readable poster *does*
    now recover, which this same guard used to (wrongly) suppress."""
    from runtime.config import load_settings

    title = "탱고 이벤트"
    url = "https://example.invalid/reprocess/post"
    item_id = _pending_item(pg, unique, title, url)
    pg.commit()
    settings = load_settings()

    try:
        # The body the site originally served: a real, complete announcement.
        # An explicit year avoids needing a `published_at` on the fixture
        # row - the same v0.80.2 rule that would otherwise leave the date
        # unresolved. "밀롱가" makes this classify as an event from the body
        # alone, same as any real announcement naming its own kind of night.
        content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
            fetched_url=url,
            text="밀롱가 2026.09.05 19:30-23:30 장소: PISTA 입장료 13,000원",
        ))
        pg.commit()
        result = engine_ingest.ingest_pending(settings)
        assert result["ingested"] == 1

        before = _events_for(settings, url)
        assert len(before) == 1
        assert before[0]["event_date"] == "2026-09-05"

        # The site now serves an image-only version of the same post: no
        # body text at all, and a poster whose OCR text carries no social/
        # milonga signal - a real, unreadable-for-classification result,
        # not a fetch failure.
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
            text="안내 포스터 이미지를 확인해 주세요 자세한 사항은 문의 바랍니다"))

        selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
        assert item_id in selected

        outcome = engine_ingest.reprocess_acquired(settings)
        assert outcome["failed"] == 0
        assert outcome["skipped_blocked"] == 1, (
            "a blocked fetch with a poster that carries no recognizable "
            "event signal must be recorded as preserved-not-reprocessed, "
            "not silently treated as a normal reprocess"
        )
        assert outcome["reprocessed"] == 0

        after = _events_for(settings, url)
        assert len(after) == 1, (
            "the real event must survive being reprocessed from an "
            "image-only fetch, not be silently deleted because classify() "
            "cannot see a poster's OCR text"
        )
        assert after[0]["event_date"] == "2026-09-05"
        assert after[0]["venue"] == "PISTA"
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


def test_reprocessing_a_blocked_item_with_a_readable_poster_now_recovers_via_image_aware_classification(
    pg, unique, env, monkeypatch
):
    """v0.84.4: the case the v0.84.3 guard above could only ever preserve,
    never actually recover - a genuinely image-only post whose poster does
    carry real, multi-signal event evidence (a date, a time, a labelled
    venue, and social/milonga context) now classifies and creates a real
    candidate through reprocess_acquired(), not just through
    ingest_pending(). Every field here is IMAGE_OCR evidence, so this must
    still never reach VERIFIED (Section 19-20)."""
    from runtime.config import load_settings

    title = "K-TANGO 행사"
    url = "https://example.invalid/reprocess/post-image-aware"
    item_id = _pending_item(pg, unique, title, url)
    pg.commit()
    settings = load_settings()

    try:
        # First fetch: blocked, and genuinely no poster at all - ingest_
        # pending() correctly finds nothing to recover, exactly as it
        # always has.
        content_store.record_outcome(pg, item_id, _blocked_outcome([]))
        pg.commit()
        result = engine_ingest.ingest_pending(settings)
        assert result["ingested"] == 1
        assert _events_for(settings, url) == []

        # A later fetch: still blocked, but the site now serves a poster -
        # the real K-TANGO shape (643/648/649's own live-audited state).
        content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
            status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE,
            fetched_url=url, images=["https://cdn.example.test/poster.jpg"],
            error_code="BODY_UNAVAILABLE", error="page fetched but no article body was served",
        ))
        pg.commit()
        monkeypatch.setattr(image_fetch, "fetch_image", lambda u, **kw: image_fetch.ImageFetchResult(
            url=u, status="FETCHED", content_type="image/jpeg", data=b"\xff\xd8\xff fake"))
        # An explicit year - a yearless "8/1" would need `published_at` set
        # on the fixture row for the v0.80.2 inference rule to resolve it,
        # and a genuinely blocked item never gets one; this poster, like a
        # real one, states its own year outright.
        monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: ocr.OcrResult(
            status=ocr.STATUS_SUCCESS, confidence=88.0, width=800, height=600,
            text="밀롱가 2026.08.01 19:00-23:00 장소: 연세대학교 대강당 입장료 13,000원"))

        selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
        assert item_id in selected

        outcome = engine_ingest.reprocess_acquired(settings)
        assert outcome["failed"] == 0
        assert outcome["skipped_blocked"] == 0, (
            "a readable poster must not fall into the preserve-guard - it "
            "should classify and reprocess normally"
        )
        assert outcome["reprocessed"] == 1
        assert outcome["candidates_after"] == 1

        after = _events_for(settings, url)
        assert len(after) == 1
        assert after[0]["event_date"] == "2026-08-01"
        assert after[0]["venue"] == "연세대학교 대강당"
        assert after[0]["fee"] == 13000
        assert after[0]["status"] == "POSSIBLE", (
            "an event whose classification and every field came from "
            "image OCR alone must never reach VERIFIED"
        )
        assert after[0]["name"] == title, (
            "reprocess_acquired()'s own item shape has no title of its own "
            "(source_item_content.title is only ever set by a page-title "
            "parse, never by a blocked fetch) - needing_reprocess() must "
            "still hand back the item's real, discovery-time title rather "
            "than silently classifying and naming the event from an empty "
            "string"
        )
    finally:
        with pg.cursor() as cur:
            cur.execute("DELETE FROM events WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM source_item_content WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM source_items WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM sources WHERE source_key = %s", (f"SRC-REP-{unique}",))
        pg.commit()


def test_reprocessing_a_fetched_item_missing_a_field_recovers_it_from_the_poster(
    pg, unique, env, monkeypatch
):
    """The genuine, reachable win of wiring image_texts into
    reprocess_acquired(): a post whose body classify() *can* read (it names
    a milonga, so classification never depends on the poster) but which is
    missing its fee, gets that fee filled from the poster once one is found
    on a later fetch - exactly the pre-existing v0.81.3 image-fallback path,
    now also reachable from reprocess_acquired() and not just
    ingest_pending()."""
    from runtime.config import load_settings

    title = "밀롱가 안내"
    url = "https://example.invalid/reprocess/post-full"
    item_id = _pending_item(pg, unique, title, url)
    pg.commit()
    settings = load_settings()

    try:
        # First fetch: a real, classifiable body, but no fee anywhere in it
        # and no poster yet.
        content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
            fetched_url=url,
            text="밀롱가 2026.09.05 19:30-23:30 장소: 라밀롱가 스튜디오",
        ))
        pg.commit()
        result = engine_ingest.ingest_pending(settings)
        assert result["ingested"] == 1

        before = _events_for(settings, url)
        assert len(before) == 1
        assert before[0]["fee"] is None

        # A second fetch of the same body, this time with the post's own
        # poster attached - the fee was on the poster all along.
        content_store.record_outcome(pg, item_id, acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
            fetched_url=url,
            text="밀롱가 2026.09.05 19:30-23:30 장소: 라밀롱가 스튜디오",
            images=["https://cdn.example.test/poster.jpg"],
        ))
        pg.commit()
        monkeypatch.setattr(image_fetch, "fetch_image", lambda u, **kw: image_fetch.ImageFetchResult(
            url=u, status="FETCHED", content_type="image/jpeg", data=b"\xff\xd8\xff fake"))
        monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: ocr.OcrResult(
            status=ocr.STATUS_SUCCESS, confidence=88.0, width=800, height=600,
            text="밀롱가 2026.09.05 19:30-23:30 장소: 라밀롱가 스튜디오 입장료 13,000원"))

        selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
        assert item_id in selected

        outcome = engine_ingest.reprocess_acquired(settings)
        assert outcome["failed"] == 0
        assert outcome["reprocessed"] == 1
        assert outcome["skipped_blocked"] == 0

        after = _events_for(settings, url)
        assert len(after) == 1
        assert after[0]["fee"] == 13000, (
            "a missing fee found only on the post's own poster must be "
            "recovered when reprocess_acquired() re-extracts, the same way "
            "ingest_pending() already recovers it on first ingest"
        )
    finally:
        with pg.cursor() as cur:
            cur.execute("DELETE FROM events WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM source_item_content WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM source_items WHERE source_item_id = %s", (item_id,))
            cur.execute("DELETE FROM sources WHERE source_key = %s", (f"SRC-REP-{unique}",))
        pg.commit()


# --- v0.84.4: image_fallback.gather_trusted_classification_texts() ---------
#
# A stricter, DB-read-only subset of whatever gather_image_texts() already
# fetched/OCR'd/cached in source_item_image for classification's own use -
# see the function's own docstring in runtime/image_fallback.py. These
# tests exercise gather_image_texts() first (the real way these rows get
# populated) and then check what gather_trusted_classification_texts()
# does and does not hand back.

def test_gather_trusted_classification_texts_excludes_a_logo_classified_image(
    pg, unique, monkeypatch,
):
    item_id = _source_item(pg, unique, suffix="logo")
    monkeypatch.setattr(image_fetch, "fetch_image", lambda u, **kw: image_fetch.ImageFetchResult(
        url=u, status="FETCHED", content_type="image/png", data=b"\x89PNG fake"))
    monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: ocr.OcrResult(
        status=ocr.STATUS_SUCCESS, confidence=90.0, width=200, height=200,
        text="밀롱가 9/5(토) 19:30-23:30 장소: PISTA 입장료 13,000원"))

    from runtime.config import load_settings
    settings = load_settings()
    texts = image_fallback.gather_image_texts(
        pg, settings, source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/site-logo.png"],
    )
    assert len(texts) == 1, "gather_image_texts() itself stays permissive - unchanged"

    trusted = image_fallback.gather_trusted_classification_texts(pg, item_id)
    assert trusted == [], (
        "a URL classified LOGO by media_classifier.classify_media() must "
        "never be trusted to help decide an image-only post's "
        "classification, even though it is still trusted for field-fill"
    )


def test_gather_trusted_classification_texts_excludes_text_under_the_minimum_length(
    pg, unique, monkeypatch,
):
    item_id = _source_item(pg, unique, suffix="short")
    monkeypatch.setattr(image_fetch, "fetch_image", lambda u, **kw: image_fetch.ImageFetchResult(
        url=u, status="FETCHED", content_type="image/jpeg", data=b"\xff\xd8\xff fake"))
    monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: ocr.OcrResult(
        status=ocr.STATUS_SUCCESS, confidence=40.0, width=400, height=400,
        text="밀롱가"))  # a real poster candidate, but a near-empty OCR read

    from runtime.config import load_settings
    settings = load_settings()
    image_fallback.gather_image_texts(
        pg, settings, source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/poster.jpg"],
    )

    trusted = image_fallback.gather_trusted_classification_texts(pg, item_id)
    assert trusted == [], "a single word is not 'the poster said this is a milonga'"


def test_gather_trusted_classification_texts_includes_a_real_poster_reading(
    pg, unique, monkeypatch,
):
    item_id = _source_item(pg, unique, suffix="real")
    poster_text = "밀롱가 9/5(토) 19:30-23:30 장소: PISTA 입장료 13,000원"
    monkeypatch.setattr(image_fetch, "fetch_image", lambda u, **kw: image_fetch.ImageFetchResult(
        url=u, status="FETCHED", content_type="image/jpeg", data=b"\xff\xd8\xff fake"))
    monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: ocr.OcrResult(
        status=ocr.STATUS_SUCCESS, confidence=90.0, width=800, height=600,
        text=poster_text))

    from runtime.config import load_settings
    settings = load_settings()
    image_fallback.gather_image_texts(
        pg, settings, source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/real-poster.jpg"],
    )

    trusted = image_fallback.gather_trusted_classification_texts(pg, item_id)
    assert trusted == [("https://cdn.example.test/real-poster.jpg", poster_text)]
