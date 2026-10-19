-- DanceMate v0.96.42 - what the engine's last applied reading of an item read.
--
-- extracted_engine_version (v0.96.3) answers one question: has the running
-- engine *finished with* this item? Every path that finishes one stamps it -
-- a re-extraction, a skip because a person reviewed the candidate, and a
-- FETCH_BLOCKED item preserved because its input is gone - so "stamped" and
-- "the running engine's reading was applied" have been the same value for
-- three different things. And it says nothing about the input: a source page
-- revised after it was read still reads current, which is how item 6234's
-- re-collected title waited for the next engine bump.
--
--   extracted_input_signature  the input signature (content_store.
--                              INPUT_SIGNATURE) of the item as the pass that
--                              finished it selected it. A row whose current
--                              signature differs has had its input revised
--                              since, and is re-read.
--   extraction_outcome         how that pass finished: EXTRACTED,
--                              PRESERVED_BODY_LOST,
--                              PRESERVED_IMAGE_EVIDENCE_LOST or
--                              KEPT_HUMAN_REVIEWED.
--   applied_engine_version     the engine version whose reading is the one
--                              in force - moved only by EXTRACTED.
--   extraction_outcome_at      when that outcome was recorded.
--
-- Nothing is backfilled: NULL on every existing row means "recorded before
-- v0.96.42", which the freshness diagnostic reports as unknown rather than
-- guessing. The runtime signs existing rows itself, a batch per scheduler
-- tick (engine_ingest.reconcile_unsigned()), against the engine's own stored
-- copy of what it read. Nullable columns and a check every NULL satisfies,
-- so re-running is a no-op and v0.96.41 code reading this table is unaffected.

ALTER TABLE source_item_content
    ADD COLUMN IF NOT EXISTS extracted_input_signature TEXT,
    ADD COLUMN IF NOT EXISTS extraction_outcome TEXT,
    ADD COLUMN IF NOT EXISTS applied_engine_version TEXT,
    ADD COLUMN IF NOT EXISTS extraction_outcome_at TIMESTAMPTZ;

ALTER TABLE source_item_content
    DROP CONSTRAINT IF EXISTS source_item_content_extraction_outcome_known;
ALTER TABLE source_item_content
    ADD CONSTRAINT source_item_content_extraction_outcome_known
    CHECK (extraction_outcome IS NULL
           OR extraction_outcome IN ('EXTRACTED', 'PRESERVED_BODY_LOST',
                                     'PRESERVED_IMAGE_EVIDENCE_LOST',
                                     'KEPT_HUMAN_REVIEWED'));
