-- DanceMate v0.76 - Human Verification Console.
--
-- The Information Engine decides an event's lifecycle status from evidence.
-- This table records what a *person* decided, separately, so the two are never
-- confused: an operator APPROVEing a candidate is not the engine granting
-- VERIFIED, and nothing here promotes a candidate on its own.
--
-- Nothing is ever deleted. A REJECTed candidate stays, because the reason it
-- was wrong is the raw material for improving the collector and the extractor.

CREATE TABLE IF NOT EXISTS human_review_actions (
    review_action_id BIGSERIAL PRIMARY KEY,

    -- The engine's candidate_id, in its SQLite store. Deliberately not a
    -- foreign key: the engine owns that database and this one must not
    -- constrain it.
    candidate_id     BIGINT NOT NULL,
    source_item_id   BIGINT REFERENCES source_items (source_item_id) ON DELETE SET NULL,

    action           TEXT NOT NULL,
    reviewer         TEXT NOT NULL DEFAULT 'admin',
    reason           TEXT,

    -- Full field snapshot either side of the action, so any edit can be
    -- audited and undone by a human reading it.
    before_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_json       JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- DUPLICATE only: the candidate this one duplicates.
    duplicate_of_candidate_id BIGINT,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT human_review_action_check CHECK (action IN (
        'APPROVE', 'EDIT', 'REJECT', 'DUPLICATE', 'CONFIRM'
    )),
    CONSTRAINT human_review_duplicate_target_check CHECK (
        action <> 'DUPLICATE' OR duplicate_of_candidate_id IS NOT NULL
    ),
    CONSTRAINT human_review_not_self_duplicate CHECK (
        duplicate_of_candidate_id IS NULL OR duplicate_of_candidate_id <> candidate_id
    )
);

CREATE INDEX IF NOT EXISTS human_review_actions_candidate_idx
    ON human_review_actions (candidate_id, created_at DESC);
CREATE INDEX IF NOT EXISTS human_review_actions_created_idx
    ON human_review_actions (created_at DESC);
CREATE INDEX IF NOT EXISTS human_review_actions_action_idx
    ON human_review_actions (action, created_at DESC);

-- Current human state per candidate, so the review queue does not have to
-- replay the whole action log on every page load.
CREATE TABLE IF NOT EXISTS candidate_review_state (
    candidate_id     BIGINT PRIMARY KEY,
    review_state     TEXT NOT NULL,
    last_action      TEXT,
    last_reviewer    TEXT,
    last_review_at   TIMESTAMPTZ,
    -- Human-corrected field values. The engine's own extraction is never
    -- overwritten; this is the operator's version alongside it.
    corrected_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    duplicate_of_candidate_id BIGINT,
    action_count     INTEGER NOT NULL DEFAULT 0,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT candidate_review_state_check CHECK (review_state IN (
        'PENDING', 'APPROVED', 'EDITED', 'REJECTED', 'DUPLICATE', 'CONFIRMED'
    ))
);

CREATE INDEX IF NOT EXISTS candidate_review_state_state_idx
    ON candidate_review_state (review_state, updated_at DESC);
