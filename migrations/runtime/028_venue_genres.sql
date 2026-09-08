-- DanceMate v0.85.7 - Venue Dance Genres.
--
-- Which dance genres are confirmed to happen at a venue - a separate
-- concept from an event's own genre (Section 16/23 of the v0.85.7 task):
-- "this venue is known to host Tango" is not the same claim as "this one
-- event is a Tango event", and neither implies the other automatically.
--
-- Reuses the existing genres master (TANGO/SALSA/SWING, 002_master_data.sql)
-- rather than a new enum, and mirrors venue_aliases' own join-table shape
-- exactly: a surrogate id, ON DELETE CASCADE from the venue, a plain FK to
-- genres (never cascaded - a genre is disabled, not deleted), a uniqueness
-- guard on the pair, and an index on the FK used for the reverse lookup.
--
-- No initial data: Section 61 of the v0.85.7 task is explicit that no venue
-- is bulk-assigned a genre here, Tango-heavy dataset or not. A row only
-- exists once a human confirms it (or a future release's own sufficiently-
-- repeated-evidence policy decides to write one) - see runtime/master_data.py
-- for the confirmed-write functions and runtime/venue_resolution.py for the
-- read-only "observed genre" suggestion this migration does not compute.

CREATE TABLE IF NOT EXISTS venue_genres (
    venue_genre_id BIGSERIAL PRIMARY KEY,
    venue_id       BIGINT NOT NULL REFERENCES venues (venue_id) ON DELETE CASCADE,
    genre_id       BIGINT NOT NULL REFERENCES genres (genre_id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS venue_genres_venue_genre_key
    ON venue_genres (venue_id, genre_id);
CREATE INDEX IF NOT EXISTS venue_genres_venue_idx
    ON venue_genres (venue_id);

-- Same reasoning as 018/020's own CSV-import actions: master_data_actions.
-- action's CHECK did not know about confirming or removing a venue's
-- dance genre, so runtime.master_edit.set_venue_genres() could not record
-- either one to the existing audit trail without this.
ALTER TABLE master_data_actions
    DROP CONSTRAINT IF EXISTS master_data_actions_action_check;
ALTER TABLE master_data_actions
    ADD CONSTRAINT master_data_actions_action_check
    CHECK (action IN (
        'EDIT', 'ENABLE', 'DISABLE', 'ALIAS_ADD', 'ALIAS_REMOVE',
        'VENUE_CSV_IMPORT', 'SOURCE_CSV_IMPORT',
        -- A venue's confirmed dance genre, added or removed by a human
        -- through the admin console (v0.85.7).
        'GENRE_ADD', 'GENRE_REMOVE'
    ));
