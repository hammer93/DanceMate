-- DanceMate v0.96.6 - incremental, restart-safe event normalization.
--
-- Root cause this migration exists for: `normalize_all()` asked the engine
-- store for `list_candidates(limit=500)`, which is "the newest 500 posts by
-- `raw_posts.collected_at`". Every scheduler tick therefore re-normalised the
-- same recent window and nothing else. On Production that window held 500 of
-- 1,264 candidates, so 764 candidates could never become an Event again no
-- matter what changed about them - and "what changed" is not hypothetical:
-- v0.96.4/v0.96.5 taught the classifier and the date parser to read nights
-- they had been dropping, v0.96.3 re-extracted every stored body into the
-- candidate it already had, and eight of the twelve candidates those releases
-- rescued were collected before the window and so never reached `events`.
-- Nine dated candidates in that backlog were real upcoming nights when they
-- were collected.
--
-- Raising the limit only moves the cliff; removing it re-normalises every
-- candidate on every tick forever. This table is the third answer: the DB row
-- is the cursor, exactly as `source_item_content.extracted_engine_version` is
-- for re-extraction (migration 042). One row per candidate records the digest
-- of the inputs normalization actually read and the normalization version
-- that read them, so the queue is "candidates whose inputs are not the ones
-- behind their current row" - which a stamped candidate leaves permanently,
-- which a changed candidate re-enters on its own, and which a restart cannot
-- lose because nothing about it lives in memory.
CREATE TABLE IF NOT EXISTS candidate_normalization (
    candidate_id BIGINT PRIMARY KEY,

    -- sha256 over exactly the engine-side inputs `normalize_candidate()`
    -- reads for this candidate - its own fields, the evidence rows behind
    -- them, and the human review state overlaid on top. A re-extract that
    -- rewrites a candidate in place (v0.96.0 `replace_candidate()`, which
    -- keeps the candidate_id) changes this; so does a review action. Either
    -- puts the candidate back in the queue with no code involved.
    input_digest TEXT NOT NULL,

    -- Bumped in runtime/normalization.py when normalization itself starts
    -- reading the same inputs differently. Like the engine version in 042,
    -- this makes a logic change finishable in small batches instead of
    -- needing a one-off "re-normalise everything" pass.
    normalization_version TEXT NOT NULL,

    -- NORMALIZED  an events row exists for this candidate
    -- NO_DATE     no event date could be read, so there is deliberately no
    --             events row - a durable answer, not a silent skip, or the
    --             candidate would be re-selected on every tick forever
    -- FAILED      normalization raised; see attempts/last_error below
    outcome TEXT NOT NULL,
    event_id BIGINT,

    normalized_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A candidate that raises must not wedge the queue ahead of the ones
    -- behind it, and must not vanish either. Past the runtime's cap the row
    -- steps aside with its reason still readable, and any change to its
    -- inputs (a new digest) starts the count again.
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    failed_at TIMESTAMPTZ,

    CONSTRAINT candidate_normalization_outcome_check
        CHECK (outcome IN ('NORMALIZED', 'NO_DATE', 'FAILED'))
);

COMMENT ON TABLE candidate_normalization IS
    'One row per engine candidate the runtime has normalised, recording which '
    'inputs produced its current events row. The normalization queue is '
    'exactly the candidates with no row here, a stale digest, or a stale '
    'normalization version - never "the newest N candidates".';
COMMENT ON COLUMN candidate_normalization.input_digest IS
    'sha256 of the engine-side normalization inputs (candidate fields, '
    'evidence marker, human review marker). Differs => re-normalise.';
COMMENT ON COLUMN candidate_normalization.attempts IS
    'Consecutive failed normalizations for this digest; reset to 0 on success '
    'and to 1 when the inputs change. Past the runtime cap the candidate is '
    'skipped so the queue keeps moving.';
