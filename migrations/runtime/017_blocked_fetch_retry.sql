-- 017 blocked_fetch_retry
--
-- FETCH_BLOCKED was in neither the settled set nor the retryable one, so a
-- page that refused its body once was never asked again. On the board that was
-- 47 items frozen for good, and a community that fixes its settings next week
-- would never have been noticed.
--
-- Two things follow. First, an operator looking at a source that yields
-- nothing needs to know when we last asked, which is not the same as when we
-- last got something: fetched_at stays null on a refusal, so there was no
-- column that answered "did we even try?".
--
-- Second, the items already blocked all carry a next_attempt_at from the old
-- fifteen-minute network default, long since past. The moment blocked items
-- become retryable, every one of them is due at once. So they are spread
-- across the next 24 hours instead, deterministically from the row id -- no
-- thundering herd, and a re-run of this migration lands them in the same
-- places.

ALTER TABLE source_item_content
    ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ;

-- What we know retrospectively: if a row has been attempted, the best record
-- of when is its last successful fetch, else when the row was last written.
UPDATE source_item_content
   SET last_attempt_at = COALESCE(fetched_at, updated_at)
 WHERE last_attempt_at IS NULL
   AND attempt_count > 0;

COMMENT ON COLUMN source_item_content.last_attempt_at IS
    'When the fetcher last asked, whether or not it got anything. '
    'fetched_at records only success.';

-- Spread the existing backlog over the coming day.
UPDATE source_item_content
   SET next_attempt_at = now() + make_interval(
           secs => (source_item_id * 1013 % 86400)::int)
 WHERE acquisition_status = 'FETCH_BLOCKED'
   AND (next_attempt_at IS NULL OR next_attempt_at <= now() + interval '1 hour');
