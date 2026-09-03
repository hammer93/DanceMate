-- v0.77.1: what a person decided about a venue string, and when.
--
-- Deliberately not folded into human_review_actions. That table records a
-- verdict about one event candidate -- APPROVE, EDIT, REJECT and so on -- and
-- is keyed by candidate_id. This records a verdict about a *string* that many
-- candidates share: "아미고스튜디오 is that studio" is one decision that settles
-- three events at once, and squeezing it into a per-candidate table would
-- either duplicate it three times or lose which string was decided.
--
-- The shape mirrors human_review_actions on purpose -- reviewer, before, after,
-- created_at -- so both read the same way in a console.
--
-- Nothing here is deleted. A venue later disabled or a queue entry later
-- reopened still leaves the record of who decided what.

CREATE TABLE IF NOT EXISTS venue_resolution_actions (
    venue_action_id     BIGSERIAL PRIMARY KEY,

    -- The queue entry acted on. SET NULL rather than CASCADE: the decision
    -- outlives the queue row, which is the point of an audit trail.
    unresolved_venue_id BIGINT REFERENCES unresolved_venues (unresolved_venue_id)
                               ON DELETE SET NULL,
    -- Kept verbatim, so the record still says what was decided even if the
    -- queue entry is gone.
    raw_venue           TEXT NOT NULL,

    action              TEXT NOT NULL,
    venue_id            BIGINT REFERENCES venues (venue_id) ON DELETE SET NULL,
    reviewer            TEXT NOT NULL,

    -- How many events the decision moved. The operator asked "2 events are
    -- waiting on this"; this says whether 2 events actually changed.
    events_updated      INTEGER NOT NULL DEFAULT 0,

    before_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT venue_resolution_actions_action_check
        CHECK (action IN ('CREATE_AND_LINK', 'LINK_EXISTING', 'NOT_A_VENUE')),
    -- The two linking actions have to say what they linked to.
    CONSTRAINT venue_resolution_actions_link_needs_venue
        CHECK (action = 'NOT_A_VENUE' OR venue_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS venue_resolution_actions_created_idx
    ON venue_resolution_actions (created_at DESC);
CREATE INDEX IF NOT EXISTS venue_resolution_actions_venue_idx
    ON venue_resolution_actions (venue_id) WHERE venue_id IS NOT NULL;
