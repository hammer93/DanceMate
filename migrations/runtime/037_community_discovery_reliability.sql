-- DanceMate v0.89.1 - Community Discovery Reliability Patch.
--
-- Two Production reviews of Community Discovery (v0.89.0) found that its
-- notion of "recent activity" sometimes came from a provider's own search
-- result metadata (a date that can reflect when a search engine last
-- indexed or re-surfaced a page, not when the page's own content was
-- actually posted) rather than from a real date written in the post's own
-- text. This adds the columns needed to keep those two apart and to say,
-- for every candidate, how sure the stored activity date really is -
-- schema only, no behaviour lives in SQL.
--
-- activity_date / activity_date_confidence / activity_evidence_* sit
-- alongside the existing recent_activity_date/activity columns rather than
-- replacing them, so nothing that already reads those two names breaks.
-- Going forward the engine keeps them in sync (recent_activity_date mirrors
-- activity_date, activity mirrors the verdict); activity_date is the new,
-- provenance-aware value.
--
-- duplicate_cleared lets an operator say "these are not the same
-- organisation" for a POSSIBLE_DUPLICATE pair without deleting either
-- candidate - reclassify() skips the duplicate-matching branch for a
-- cleared item from then on, letting it be judged on its own evidence.

ALTER TABLE community_discovery_items
    ADD COLUMN IF NOT EXISTS activity_date              DATE,
    ADD COLUMN IF NOT EXISTS activity_date_confidence    TEXT NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS activity_evidence_url       TEXT,
    ADD COLUMN IF NOT EXISTS activity_evidence_title     TEXT,
    ADD COLUMN IF NOT EXISTS activity_evidence_source    TEXT,
    ADD COLUMN IF NOT EXISTS duplicate_cleared           BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE community_discovery_items
    DROP CONSTRAINT IF EXISTS community_discovery_items_activity_date_confidence_check;
ALTER TABLE community_discovery_items
    ADD CONSTRAINT community_discovery_items_activity_date_confidence_check
    CHECK (activity_date_confidence IN ('CONFIRMED', 'INFERRED', 'UNKNOWN'));

-- A safe, conservative backfill only: every existing candidate's best-known
-- date is carried over so the new column is never empty where the old one
-- had a value, but confidence stays at its default UNKNOWN for all of
-- them - none of the 425 rows already in Production is upgraded to a false
-- certainty by this migration. A reviewer confirming real evidence (through
-- the new Admin action) is the only way a row ever becomes CONFIRMED.
UPDATE community_discovery_items
SET activity_date = recent_activity_date
WHERE activity_date IS NULL AND recent_activity_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS community_discovery_items_duplicate_of_idx
    ON community_discovery_items (duplicate_of_item_id) WHERE duplicate_of_item_id IS NOT NULL;
