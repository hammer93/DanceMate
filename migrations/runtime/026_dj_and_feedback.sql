-- v0.85.0 Private Alpha: DJ field + minimal user feedback.
--
-- DJ. The Information Engine already extracts a DJ name (extractor.py's
-- DJ_RE, EventCandidate.dj, event_candidates.dj in the engine's own SQLite)
-- and always has, but nothing downstream ever read it: runtime.candidates.
-- list_candidates()'s own SELECT never named the column, so it was dropped
-- before normalize_candidate() ever saw it. Not a new extraction feature -
-- closing a gap in a pipe that was already there.
ALTER TABLE events ADD COLUMN IF NOT EXISTS dj TEXT;

-- A dancer's own signal on one event: does the listing look right. Kept
-- separate from human_review_actions on purpose - that table is an
-- operator's own audit log (reviewer defaults to 'admin', gated behind
-- admin auth everywhere it is written); this is public, anonymous, and
-- per-event rather than per-candidate, which the admin table is not shaped
-- for. Read-only signal: nothing here ever mutates an event by itself
-- (Section 56) - an operator reads this queue and, if anything, acts
-- through the existing, audited human_review_actions path instead.
CREATE TABLE IF NOT EXISTS event_feedback (
    feedback_id     BIGSERIAL PRIMARY KEY,
    event_id        BIGINT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- An operator marks a feedback row read/acted-on without deleting it -
    -- the queue count on the admin dashboard is "open", not "ever received".
    resolved_at     TIMESTAMPTZ,
    CONSTRAINT event_feedback_kind_check
        CHECK (kind IN ('ACCURATE', 'INCORRECT', 'INCOMPLETE'))
);

CREATE INDEX IF NOT EXISTS event_feedback_event_idx ON event_feedback (event_id);
CREATE INDEX IF NOT EXISTS event_feedback_open_idx
    ON event_feedback (created_at) WHERE resolved_at IS NULL;
