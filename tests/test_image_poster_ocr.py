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

from runtime import acquisition, content_store


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


def test_a_repeated_blocked_fetch_does_not_re_enter_the_queue(pg, unique):
    """A FETCH_BLOCKED outcome never sets `fetched_at` (it means "we got a
    body", which a blocked fetch by definition did not) - so a second,
    still-blocked fetch of an already-reprocessed item carries no new
    information and correctly does not re-enter the queue. This differs
    from FETCHED_FULL/PARTIAL, where `fetched_at` advances on every
    successful fetch and a changed body is exactly what re-triggers reprocess;
    a page that never gained a body has nothing new to reprocess."""
    item_id = _source_item(pg, unique)
    content_store.record_outcome(pg, item_id, _blocked_outcome(
        ["https://cdn.example.test/poster.jpg"]
    ))
    content_store.mark_reprocessed(pg, item_id)
    content_store.record_outcome(pg, item_id, _blocked_outcome(
        ["https://cdn.example.test/poster.jpg"]
    ))
    selected = {row["source_item_id"] for row in content_store.needing_reprocess(pg, limit=50)}
    assert item_id not in selected


def test_poster_candidates_are_stored_as_the_images_list(pg, unique):
    item_id = _source_item(pg, unique)
    content_store.record_outcome(pg, item_id, _blocked_outcome(
        ["https://cdn.example.test/poster.jpg"]
    ))
    row = content_store.get(pg, item_id)
    assert row["poster_candidates"] == ["https://cdn.example.test/poster.jpg"]
    assert row["image_count"] == 1
