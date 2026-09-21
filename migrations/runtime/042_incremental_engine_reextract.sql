-- DanceMate v0.96.3 - incremental engine re-extraction.
--
-- Root cause this migration exists for: an engine version bump changes what
-- `extract_*()` reads out of a stored body, but nothing about the stored row
-- said which engine version had last read it. `needing_reprocess()` could
-- therefore only offer two answers - "the body is newer than the last
-- re-extract" (true for nothing after an engine bump, because the bodies did
-- not change) or `force=true`, "every row with text, ordered by fetched_at,
-- LIMIT n" - and `mark_reprocessed()` does not change that ordering, so
-- calling the forced pass repeatedly re-read the same first n rows forever.
-- The only way to actually finish a pass was one synchronous call over all
-- 2,201 rows (~80 minutes on the board, OCR included), which is not a thing
-- an operator can run against a live scheduler.
--
-- `extracted_engine_version` makes the DB row itself the cursor: the
-- incremental pass selects bodies whose stored extraction came from some
-- other engine version, and every successful re-extract stamps the current
-- one, so the row leaves the queue permanently and the next scheduler tick
-- necessarily picks up different rows. A future ENGINE_VERSION bump makes
-- every row stale again with no code change and no further migration - this
-- is deliberately not a one-off "re-extract everything older than <date>".
--
-- NULL means "extracted by an engine version that predates this column",
-- which is exactly the 1,039 fetched Production bodies still holding
-- pre-0.91 candidates. They become the first incremental backlog.
ALTER TABLE source_item_content
    ADD COLUMN IF NOT EXISTS extracted_engine_version TEXT;

-- A re-extract that raises must not wedge the cursor: without a failure
-- count the same broken row would be selected first on every tick forever
-- and nothing behind it would ever be reached. Counting attempts lets the
-- incremental pass step over a row after a few tries while leaving the
-- reason visible - dropped from the queue, never silently forgotten.
ALTER TABLE source_item_content
    ADD COLUMN IF NOT EXISTS reprocess_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_item_content
    ADD COLUMN IF NOT EXISTS reprocess_error TEXT;
ALTER TABLE source_item_content
    ADD COLUMN IF NOT EXISTS reprocess_failed_at TIMESTAMPTZ;

COMMENT ON COLUMN source_item_content.extracted_engine_version IS
    'ENGINE_VERSION that produced the candidates currently stored for this '
    'content. NULL = pre-v0.96.3, treated as stale. The incremental '
    'engine-reprocess queue is exactly the rows where this differs from the '
    'running ENGINE_VERSION.';
COMMENT ON COLUMN source_item_content.reprocess_attempts IS
    'Consecutive failed re-extractions; reset to 0 on success. Past the '
    'runtime cap the incremental pass skips the row so the queue keeps moving.';

-- The incremental queue's own index: "rows with a body whose stored
-- extraction is not the running engine version", in the pass's own order.
CREATE INDEX IF NOT EXISTS source_item_content_engine_version_idx
    ON source_item_content (extracted_engine_version, fetched_at, source_item_id)
    WHERE acquisition_status IN ('FETCHED_FULL', 'FETCHED_PARTIAL', 'FETCH_BLOCKED');
