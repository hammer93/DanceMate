-- DanceMate v0.94.0 - Event Source Evidence and Primary Source selection.
--
-- Until now an Event had exactly one source: the `source_item_id` of its own
-- row. When the same night was found by an aggregator (Miltang/TangoNOW) and
-- by the organizer's own board, duplicate resolution folded one row under
-- the other and the *row* that survived decided which source a reader saw -
-- so making the direct post the representative meant flipping which row was
-- canonical, and with it the Event's public id.
--
-- This migration separates the two questions. Which row is canonical stays a
-- question of completeness and age (the incumbent keeps its id); which
-- source represents the Event is `primary_source_item_id`, elected across
-- the whole duplicate group by evidence priority (runtime/source_evidence.py:
-- PRIMARY_ORGANIZER > OFFICIAL_ORGANIZER > OFFICIAL_VENUE >
-- COMMUNITY_PROMOTION > AGGREGATOR > SEARCH_DISCOVERY). NULL means "the
-- row's own source_item" - exactly today's behaviour, so nothing existing
-- needs a backfill and nothing reads differently until a better source is
-- actually found. `primary_source_decided_by` is AUTO or HUMAN; a HUMAN
-- choice is never overturned by a later scan, the same rule
-- event_duplicate_decisions already enforces for merges.
--
-- event_primary_source_history keeps every change of representative, so
-- "discovered on TangoNOW, later confirmed by the community's own post" is
-- a recorded sequence rather than a lost one.
--
-- community_discovery_items.source_id records that a reviewed Community
-- candidate has been proposed as a Source Master row (registered DISABLED,
-- like migrations 021/023/027 - an operator tests, then enables). A
-- Community is not a Source: one Community may end up with several.

ALTER TABLE events
    ADD COLUMN IF NOT EXISTS primary_source_item_id BIGINT
        REFERENCES source_items (source_item_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS primary_source_decided_by TEXT,
    ADD COLUMN IF NOT EXISTS primary_source_reason TEXT,
    ADD COLUMN IF NOT EXISTS primary_source_updated_at TIMESTAMPTZ;

ALTER TABLE events DROP CONSTRAINT IF EXISTS events_primary_source_decided_by_check;
ALTER TABLE events ADD CONSTRAINT events_primary_source_decided_by_check
    CHECK (primary_source_decided_by IS NULL OR primary_source_decided_by IN ('AUTO', 'HUMAN'));

CREATE INDEX IF NOT EXISTS events_primary_source_item_idx
    ON events (primary_source_item_id) WHERE primary_source_item_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS event_primary_source_history (
    history_id              BIGSERIAL PRIMARY KEY,
    event_id                BIGINT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    source_item_id          BIGINT REFERENCES source_items (source_item_id) ON DELETE SET NULL,
    previous_source_item_id BIGINT REFERENCES source_items (source_item_id) ON DELETE SET NULL,
    evidence_class          TEXT,
    decided_by              TEXT NOT NULL,
    reason                  TEXT,
    reviewer                TEXT,
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT event_primary_source_history_decided_by_check
        CHECK (decided_by IN ('AUTO', 'HUMAN'))
);

CREATE INDEX IF NOT EXISTS event_primary_source_history_event_idx
    ON event_primary_source_history (event_id, history_id);

ALTER TABLE community_discovery_items
    ADD COLUMN IF NOT EXISTS source_id BIGINT REFERENCES sources (source_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS community_discovery_items_source_idx
    ON community_discovery_items (source_id) WHERE source_id IS NOT NULL;
