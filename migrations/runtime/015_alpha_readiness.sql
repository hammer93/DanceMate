-- v0.80: two things a private alpha needs and the schema did not have.
--
-- 1. An operator's decision about a source, kept apart from what the source is
--    doing. "This cafe blocks us" is an observation the pipeline makes every
--    hour; "replace it, the new salsa cafes cover the same ground" is a
--    judgement a person made once and should not have to remember.
--
-- 2. What people actually opened. Not analytics in the growth sense: no
--    identifier, no IP, no session, no cookie. Three counters and a day, so
--    "did anyone look at tonight's list, and did they open anything" has an
--    answer. A private alpha with five people does not need more, and storing
--    more would mean storing people.

ALTER TABLE sources ADD COLUMN IF NOT EXISTS operational_decision TEXT;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS decision_reason TEXT;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS decided_by TEXT;

ALTER TABLE sources
    DROP CONSTRAINT IF EXISTS sources_operational_decision_check;
ALTER TABLE sources
    ADD CONSTRAINT sources_operational_decision_check
    CHECK (operational_decision IS NULL OR operational_decision IN (
        -- Working, keep collecting.
        'ACTIVE',
        -- Not working, but worth keeping: nothing else covers this ground.
        'KEEP',
        -- Something else covers this ground and does it better.
        'REPLACE',
        -- Stop collecting.
        'DISABLE',
        -- Undecided on purpose; look again later.
        'MONITOR'
    ));

-- One row per view, aggregated by the day it happened. Deliberately not per
-- person: there is no column here that could identify one.
CREATE TABLE IF NOT EXISTS alpha_view_log (
    view_id      BIGSERIAL PRIMARY KEY,
    kind         TEXT NOT NULL,
    -- Which event was opened, where that is the question being asked. Null for
    -- a list view, which is about the list rather than any one event.
    event_id     BIGINT,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_view_log_kind_check
        CHECK (kind IN ('EVENT_LIST_VIEW', 'EVENT_DETAIL_VIEW', 'SOURCE_LINK_CLICK'))
);

CREATE INDEX IF NOT EXISTS alpha_view_log_day_idx
    ON alpha_view_log (occurred_at DESC, kind);
CREATE INDEX IF NOT EXISTS alpha_view_log_event_idx
    ON alpha_view_log (event_id) WHERE event_id IS NOT NULL;
