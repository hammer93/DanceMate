-- v0.77: let an event that no longer exists be removed.
--
-- Re-extraction issues new candidate ids, so normalisation prunes events whose
-- engine candidate is gone. Two self-references blocked that: a duplicate
-- pointing at its canonical, and the audit row recording that verdict. Both
-- named an event that was being deleted, and the delete was refused.
--
-- SET NULL rather than CASCADE, in both places, for the same reason: the
-- verdict is history and history is not deleted because its subject was. A
-- decision row with a null canonical still says who decided what, and when.

ALTER TABLE events
    DROP CONSTRAINT IF EXISTS events_canonical_event_id_fkey;
ALTER TABLE events
    ADD CONSTRAINT events_canonical_event_id_fkey
    FOREIGN KEY (canonical_event_id) REFERENCES events (event_id) ON DELETE SET NULL;

ALTER TABLE event_duplicate_decisions
    DROP CONSTRAINT IF EXISTS event_duplicate_decisions_canonical_event_id_fkey;
ALTER TABLE event_duplicate_decisions
    ADD CONSTRAINT event_duplicate_decisions_canonical_event_id_fkey
    FOREIGN KEY (canonical_event_id) REFERENCES events (event_id) ON DELETE SET NULL;
