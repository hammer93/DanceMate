-- v0.77 PHASE E: Duplicate Resolution.
--
-- The same milonga gets posted by the venue, the organiser and two dancers.
-- Showing it four times is a worse answer than showing it once, and merging
-- two different events is worse than either.
--
-- Rules only: same date, same resolved venue, overlapping start time. No
-- embeddings, no clustering, no similarity score anybody has to trust. A pair
-- the rules cannot settle is an open question for a person, not a merge.
--
-- Nothing is deleted. A duplicate keeps its own row, its own candidate_id and
-- its own source URL, and points at the canonical one -- so "which posts said
-- this?" stays answerable after a merge.

-- Every duplicate verdict ever recorded, automatic or human. The event row
-- carries the current answer; this carries how it got there.
CREATE TABLE IF NOT EXISTS event_duplicate_decisions (
    decision_id      BIGSERIAL PRIMARY KEY,
    event_id         BIGINT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    canonical_event_id BIGINT REFERENCES events (event_id),
    decision         TEXT NOT NULL,
    decided_by       TEXT NOT NULL,
    rule             TEXT NOT NULL,
    reason           TEXT,
    reviewer         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT event_duplicate_decisions_decision_check
        CHECK (decision IN ('DUPLICATE', 'DISTINCT')),
    CONSTRAINT event_duplicate_decisions_by_check
        CHECK (decided_by IN ('AUTO', 'HUMAN')),
    -- A DUPLICATE verdict has to say what it duplicates.
    CONSTRAINT event_duplicate_decisions_needs_canonical
        CHECK (decision <> 'DUPLICATE' OR canonical_event_id IS NOT NULL),
    CONSTRAINT event_duplicate_decisions_not_self
        CHECK (canonical_event_id IS NULL OR canonical_event_id <> event_id)
);

CREATE INDEX IF NOT EXISTS event_duplicate_decisions_event_idx
    ON event_duplicate_decisions (event_id, decision_id DESC);

-- Pairs the rules matched on some fields and not others: same date and venue
-- but three hours apart, or same date and time with one venue unresolved.
-- Auto-merging these is how two different milongas become one.
CREATE TABLE IF NOT EXISTS event_duplicate_pairs (
    pair_id         BIGSERIAL PRIMARY KEY,
    -- Stored lowest id first so a pair is recorded once, not twice.
    event_id        BIGINT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    other_event_id  BIGINT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    rule            TEXT NOT NULL,
    matched         JSONB NOT NULL DEFAULT '[]'::jsonb,
    differs         JSONB NOT NULL DEFAULT '[]'::jsonb,
    state           TEXT NOT NULL DEFAULT 'OPEN',
    resolved_by     TEXT,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT event_duplicate_pairs_state_check
        CHECK (state IN ('OPEN', 'MERGED', 'DISTINCT')),
    CONSTRAINT event_duplicate_pairs_ordered
        CHECK (event_id < other_event_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS event_duplicate_pairs_key
    ON event_duplicate_pairs (event_id, other_event_id);
CREATE INDEX IF NOT EXISTS event_duplicate_pairs_state_idx
    ON event_duplicate_pairs (state);
