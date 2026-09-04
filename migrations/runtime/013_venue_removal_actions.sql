-- v0.77.2: a venue can be removed, and the record of removing it survives.
--
-- Same lesson as 010. venue_resolution_actions.venue_id was a foreign key with
-- ON DELETE SET NULL, so deleting a venue would blank the id out of the very
-- record that says it was deleted -- and then fail the table's own rule that a
-- linking action must name a venue.
--
-- The column becomes a plain id and the name is stored beside it. "Deleted
-- 라 벤따나, 2 events unlinked" has to stay readable after 라 벤따나 is gone;
-- that is the entire purpose of writing it down.

ALTER TABLE venue_resolution_actions
    DROP CONSTRAINT IF EXISTS venue_resolution_actions_venue_id_fkey;

ALTER TABLE venue_resolution_actions
    ADD COLUMN IF NOT EXISTS venue_name TEXT;

-- Existing rows still have their venue, so the name can be filled in.
UPDATE venue_resolution_actions a
   SET venue_name = v.name
  FROM venues v
 WHERE a.venue_id = v.venue_id AND a.venue_name IS NULL;

ALTER TABLE venue_resolution_actions
    DROP CONSTRAINT IF EXISTS venue_resolution_actions_action_check;
ALTER TABLE venue_resolution_actions
    ADD CONSTRAINT venue_resolution_actions_action_check
    CHECK (action IN (
        'CREATE_AND_LINK',
        'LINK_EXISTING',
        'NOT_A_VENUE',
        -- Removing a venue nothing referenced.
        'VENUE_DELETE',
        -- Removing one that events referenced: they go back to the raw string
        -- they were read from, and the string goes back in the queue.
        'VENUE_UNLINK_DELETE',
        -- Keeping the row and its history, but taking it out of circulation.
        'VENUE_DEACTIVATE',
        'VENUE_REACTIVATE'
    ));

ALTER TABLE venue_resolution_actions
    DROP CONSTRAINT IF EXISTS venue_resolution_actions_link_needs_venue;
ALTER TABLE venue_resolution_actions
    ADD CONSTRAINT venue_resolution_actions_link_needs_venue
    CHECK (action = 'NOT_A_VENUE' OR venue_id IS NOT NULL);
