-- DanceMate v0.91.0 PHASE 6 - Source and Event Multi-Genre Relations.
--
-- Real production evidence proves a single genre_id loses discoverability:
-- SRC-D-020 item 2100's own title names both Salsa and Bachata
-- ("인천 살사&바차타 엘마르"); SRC-D-011 item 2225's body does the same
-- ("살사 바차타 강남 라틴 댄스 동호회"); the community layer already models
-- this reality (community_genres, 035_public_directory.sql: 10 of 37
-- communities carry 2+ genres today, e.g. Elmar's own community row carries
-- Bachata+Kizomba+Salsa+Tango). `sources.genre_id` and `events.genre_id`
-- have no equivalent - this migration adds one, following the two existing
-- many-to-many genre-link shapes in this schema rather than inventing a
-- third: 028_venue_genres.sql's audit-integrated, human-confirmed shape for
-- `source_genres` (a source's registered genre scope is an admin decision,
-- the same kind of fact "this venue hosts Tango" is), and
-- 035_public_directory.sql's plain composite-key shape for the join itself.
--
-- `event_genres` is the one genuinely new shape here: unlike a venue or a
-- source, an event is normalised fresh from its engine candidate on every
-- ingest cycle, and a genre hint read off a reprocessed post's text can
-- legitimately change or disappear between runs (a post gets its wording
-- corrected, or the hint was a coincidental phrase that a later, fuller
-- fetch's text no longer contains). `origin` distinguishes what the
-- runtime's own normalize_candidate() wrote from what a person confirmed
-- through review, so a later ingest cycle can safely delete-and-reinsert its
-- own AUTO rows without ever touching a HUMAN one - the same "never let
-- automation revisit what a person already decided" discipline
-- duplicates.py's own module docstring already states for duplicate pairs.
--
-- Both tables are backfilled from the existing primary genre_id columns
-- (never touching sources.genre_id/events.genre_id themselves, and never
-- changing any row's id) so every existing Source and Event is immediately
-- queryable through the new relation exactly as it already was through the
-- old column - old clients reading genre_id keep working unchanged.
--
-- No admin action-vocabulary change needed for source_genres: 014/028 already
-- put 'SOURCE' in master_data_actions_entity_check and 'GENRE_ADD'/
-- 'GENRE_REMOVE' in master_data_actions_action_check for venue_genres - the
-- same two actions describe "a source's registered genre scope changed" with
-- no schema change.

CREATE TABLE IF NOT EXISTS source_genres (
    source_id  BIGINT NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    genre_id   BIGINT NOT NULL REFERENCES genres (genre_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, genre_id)
);

CREATE INDEX IF NOT EXISTS source_genres_genre_idx ON source_genres (genre_id);

CREATE TABLE IF NOT EXISTS event_genres (
    event_id   BIGINT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    genre_id   BIGINT NOT NULL REFERENCES genres (genre_id),
    -- AUTO: written by normalize_candidate() from the primary genre_id or
    -- from the engine's own "genre_hint" evidence. HUMAN: confirmed through
    -- review. A reprocess only ever deletes-and-reinserts its own AUTO rows.
    origin     TEXT NOT NULL DEFAULT 'AUTO'
        CONSTRAINT event_genres_origin_check CHECK (origin IN ('AUTO', 'HUMAN')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, genre_id)
);

CREATE INDEX IF NOT EXISTS event_genres_genre_idx ON event_genres (genre_id);

-- Backfill: one AUTO row per existing Source/Event that already has a
-- primary genre_id. ON CONFLICT DO NOTHING makes this safe to run on both a
-- fresh 001->040 chain (nothing to backfill yet, or seed-only rows) and the
-- existing 039 baseline (real accumulated Sources/Events).
INSERT INTO source_genres (source_id, genre_id)
SELECT source_id, genre_id FROM sources WHERE genre_id IS NOT NULL
ON CONFLICT (source_id, genre_id) DO NOTHING;

INSERT INTO event_genres (event_id, genre_id, origin)
SELECT event_id, genre_id, 'AUTO' FROM events WHERE genre_id IS NOT NULL
ON CONFLICT (event_id, genre_id) DO NOTHING;
