-- v0.77.3: what an operator changed about a master record.
--
-- Separate from venue_resolution_actions, which answers a different question.
-- That table records decisions about *strings we read from posts*: this string
-- is that venue, this string is not a venue at all, deleting this venue sends
-- its strings back to the queue. This one records edits to the master rows
-- themselves -- a name corrected, an address filled in, a region moved, a
-- source's interval changed -- across every entity the console manages.
--
-- One table rather than five, because the question an operator asks is "what
-- changed in the master data, and who changed it", not "what changed in
-- organizers specifically".
--
-- entity_id is a plain id, not a foreign key: an edit record has to survive
-- the row it describes, and a per-entity foreign key would need five columns
-- and five ON DELETE rules to say the same thing.

CREATE TABLE IF NOT EXISTS master_data_actions (
    master_action_id BIGSERIAL PRIMARY KEY,

    entity_type     TEXT NOT NULL,
    entity_id       BIGINT NOT NULL,
    -- Kept verbatim so the record still reads after a rename or a deletion.
    entity_name     TEXT,

    action          TEXT NOT NULL,
    reviewer        TEXT NOT NULL,

    -- Only the fields that actually changed, old and new. An edit that changed
    -- nothing is not recorded at all.
    before_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    detail          TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT master_data_actions_entity_check
        CHECK (entity_type IN ('GENRE', 'REGION', 'VENUE', 'ORGANIZER', 'SOURCE')),
    CONSTRAINT master_data_actions_action_check
        CHECK (action IN ('EDIT', 'ENABLE', 'DISABLE', 'ALIAS_ADD', 'ALIAS_REMOVE'))
);

CREATE INDEX IF NOT EXISTS master_data_actions_created_idx
    ON master_data_actions (created_at DESC);
CREATE INDEX IF NOT EXISTS master_data_actions_entity_idx
    ON master_data_actions (entity_type, entity_id, master_action_id DESC);
