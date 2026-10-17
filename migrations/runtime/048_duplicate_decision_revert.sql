-- DanceMate v0.96.40 - a person's duplicate verdict can be taken back, on the record.
--
-- A Same event / Different events answer on the Duplicates page was final:
-- nothing could undo it, and the scan never re-asks a pair a person settled.
-- v0.96.40 adds a revert of one such verdict (duplicates.revert_decision).
--
-- event_duplicate_decisions is the trail of every duplicate verdict, so the
-- revert is recorded there too - as its own kind of decision, REVERT, which
-- names the verdict it takes back. It is not venue_resolution_actions'
-- DECISION_REVERT: that undoes a venue queue decision, a different subject
-- with a different table. The original verdict's row is kept; a verdict can
-- be reverted once (the unique index below), and only by a person.
--
-- pair_id records which Duplicates-page question a person's verdict answered,
-- so a revert can put that question back. Rows written before this release
-- carry NULL and are found by their pair's two event ids instead.
--
-- before_json / after_json hold what the revert changed: each event's
-- canonical, listing state and identity before and after, and what the
-- duplicate scan did on that date in the same transaction.
--
-- Nothing existing is rewritten: four nullable columns, one check replaced by
-- a strictly wider one, two new checks every existing row already satisfies
-- (none is a REVERT and none names a reverted verdict), and an index.
-- Re-running is a no-op.

ALTER TABLE event_duplicate_decisions
    ADD COLUMN IF NOT EXISTS pair_id BIGINT,
    ADD COLUMN IF NOT EXISTS reverts_decision_id BIGINT,
    ADD COLUMN IF NOT EXISTS before_json JSONB,
    ADD COLUMN IF NOT EXISTS after_json JSONB;

ALTER TABLE event_duplicate_decisions
    DROP CONSTRAINT IF EXISTS event_duplicate_decisions_decision_check;
ALTER TABLE event_duplicate_decisions
    ADD CONSTRAINT event_duplicate_decisions_decision_check
    CHECK (decision IN ('DUPLICATE', 'DISTINCT', 'REVERT'));

-- A revert says which verdict it takes back, and nothing else does.
ALTER TABLE event_duplicate_decisions
    DROP CONSTRAINT IF EXISTS event_duplicate_decisions_revert_names_verdict;
ALTER TABLE event_duplicate_decisions
    ADD CONSTRAINT event_duplicate_decisions_revert_names_verdict
    CHECK ((decision = 'REVERT') = (reverts_decision_id IS NOT NULL));

-- Automation releases what automation decided (STALE_AUTO_MERGE); taking back
-- a verdict is a person's act.
ALTER TABLE event_duplicate_decisions
    DROP CONSTRAINT IF EXISTS event_duplicate_decisions_revert_by_human;
ALTER TABLE event_duplicate_decisions
    ADD CONSTRAINT event_duplicate_decisions_revert_by_human
    CHECK (decision <> 'REVERT' OR decided_by = 'HUMAN');

-- One revert per verdict, even under two confirms at once.
CREATE UNIQUE INDEX IF NOT EXISTS event_duplicate_decisions_reverted_once
    ON event_duplicate_decisions (reverts_decision_id)
    WHERE reverts_decision_id IS NOT NULL;
