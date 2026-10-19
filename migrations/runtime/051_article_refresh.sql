-- DanceMate v0.96.43 - re-checking an article DanceMate already fetched.
--
-- A fetched article body was settled for good: acquisition.SETTLED holds
-- FETCHED_FULL/FETCHED_PARTIAL, next_attempt_at() returns NULL for them, and
-- due_for_acquisition() never selects them again. A publisher who edits the
-- date or time in the post body after the first fetch was never seen - the
-- discovery record (search title/snippet) can stay the same, and the
-- extraction input signature (migration 050) only moves when a new input is
-- stored. runtime.article_refresh re-checks a bounded set of these articles
-- and records what each check found here, beside the body it checks.
--
--   refresh_attempted_at   when a re-check last asked the server.
--   refresh_checked_at     when a re-check last *succeeded* (the body was
--                          read and compared, or a 304 confirmed it). A
--                          failed attempt never moves this.
--   refresh_outcome        what the last attempt found (UNCHANGED,
--                          NOT_MODIFIED, REVISED, or why it failed).
--   refresh_failures       consecutive failed attempts; 0 after a success.
--   refresh_next_at        an explicit backoff after a failure; NULL means
--                          "due by the policy interval".
--   refresh_error          the last failure, for the operator.
--   refresh_revised_at     the last time a re-check stored a revised body.
--   refresh_etag /
--   refresh_last_modified  validators for a conditional GET, when a server
--                          sends them.
--
-- content_fetch_log gains `purpose` (ACQUIRE for every existing row and every
-- first acquisition, REFRESH for a re-check) and `refresh_result`, so the
-- per-host request budget and the operator's counts come from the same
-- append-only log v0.96.9 already trusts.
--
-- Nothing is backfilled, every column is nullable or defaulted, and the
-- checks accept every existing row, so re-running is a no-op and v0.96.42
-- code reading these tables is unaffected.

ALTER TABLE source_item_content
    ADD COLUMN IF NOT EXISTS refresh_attempted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS refresh_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS refresh_outcome TEXT,
    ADD COLUMN IF NOT EXISTS refresh_failures INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS refresh_next_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS refresh_error TEXT,
    ADD COLUMN IF NOT EXISTS refresh_revised_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS refresh_etag TEXT,
    ADD COLUMN IF NOT EXISTS refresh_last_modified TEXT;

ALTER TABLE source_item_content
    DROP CONSTRAINT IF EXISTS source_item_content_refresh_outcome_known;
ALTER TABLE source_item_content
    ADD CONSTRAINT source_item_content_refresh_outcome_known
    CHECK (refresh_outcome IS NULL
           OR refresh_outcome IN ('UNCHANGED', 'NOT_MODIFIED', 'REVISED', 'SUPERSEDED',
                                  'FAILED', 'RATE_LIMITED', 'NOT_FOUND', 'FORBIDDEN',
                                  'ROBOTS_DISALLOWED', 'REFUSED', 'ADAPTER_MISMATCH',
                                  'BODY_UNAVAILABLE'));

ALTER TABLE content_fetch_log
    ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'ACQUIRE',
    ADD COLUMN IF NOT EXISTS refresh_result TEXT;

ALTER TABLE content_fetch_log
    DROP CONSTRAINT IF EXISTS content_fetch_log_purpose_known;
ALTER TABLE content_fetch_log
    ADD CONSTRAINT content_fetch_log_purpose_known
    CHECK (purpose IN ('ACQUIRE', 'REFRESH'));

CREATE INDEX IF NOT EXISTS content_fetch_log_refresh_idx
    ON content_fetch_log (host, fetched_at DESC) WHERE purpose = 'REFRESH';
