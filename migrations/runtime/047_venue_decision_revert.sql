-- DanceMate v0.96.37 - a venue decision can be taken back, on the record.
--
-- Until now the only way to undo a wrong Link Existing was to delete the venue
-- it went to, which for a link onto the right studio's wrong neighbour deletes
-- a real place along with the mistake. v0.96.37 adds a revert of one queue
-- decision (venue_resolution.revert_decision): that string's own alias on that
-- venue, the events that decision moved back to the words their post used, the
-- automatic folds they were in, and the queue entry back to OPEN.
--
-- A correction has to be audited like the decision it corrects, and the audit
-- table only accepts the actions it names. So this adds one: DECISION_REVERT.
-- The original decision's row is kept - the trail says what was decided, and
-- then that it was undone.
--
-- Reverting a Not-a-venue verdict moves no event and names no venue, so a
-- revert is allowed a NULL venue_id the way NOT_A_VENUE already is.
--
-- No row is written or rewritten: two constraints are replaced, each by a
-- strictly wider one, so every existing row still satisfies them. Re-running
-- is a no-op (DROP IF EXISTS, then the same ADD).

ALTER TABLE venue_resolution_actions
    DROP CONSTRAINT IF EXISTS venue_resolution_actions_action_check;
ALTER TABLE venue_resolution_actions
    ADD CONSTRAINT venue_resolution_actions_action_check
    CHECK (action IN (
        'CREATE_AND_LINK',
        'LINK_EXISTING',
        'NOT_A_VENUE',
        'VENUE_DELETE',
        'VENUE_UNLINK_DELETE',
        'VENUE_DEACTIVATE',
        'VENUE_REACTIVATE',
        -- A person took one of the three queue decisions back.
        'DECISION_REVERT'
    ));

ALTER TABLE venue_resolution_actions
    DROP CONSTRAINT IF EXISTS venue_resolution_actions_link_needs_venue;
ALTER TABLE venue_resolution_actions
    ADD CONSTRAINT venue_resolution_actions_link_needs_venue
    CHECK (action IN ('NOT_A_VENUE', 'DECISION_REVERT') OR venue_id IS NOT NULL);
