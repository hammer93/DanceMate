-- DanceMate v0.86.9 - Event Terminology: the words a scene uses for its
-- events, mapped to the Event Formats DanceMate already classifies by.
--
-- A tango post calls the same kind of night by several names - 밀롱가 /
-- Milonga, 쁘락띠까 / Practica - and some names mean more than one kind at
-- once: a 쁘롱가 / Pronga is a practica and a milonga in one evening. Those
-- words used to live in one hardcoded list in engine/src/classifier.py;
-- from here on an operator manages them in Settings.
--
-- What already exists is reused, not duplicated:
--   * the canonical vocabulary is the existing Event Format set in
--     runtime/events_api.py (MILONGA / PRACTICA / GENERAL / SOCIAL) - no new
--     enum, no CHECK list restating it here; runtime/event_terms.py is where
--     a term's formats are validated against that one definition;
--   * the genre scope is a real foreign key to the existing genres master,
--     not a genre name copied into this table.
--
-- One term can mean several formats, so the mapping is its own table
-- (event_term_formats) - a proper many-to-many, never a comma-joined string.
--
-- events.event_formats records which formats an event's own title resolved
-- to when it was last normalized - the one place a two-format night like a
-- Pronga can be stored as two formats, since events.event_type is the
-- engine's single classification and stays exactly as it is. It is added
-- NULL for every existing row: this migration rewrites no event. The
-- existing event-normalization job fills it in as it next rebuilds each
-- event, from whatever the Settings say at that time.
--
-- Seeds: only the six spellings whose meaning is settled. Anything else
-- (쁘렉틸롱가, organizer-specific names, regional aliases) is added by an
-- operator in Settings rather than guessed at here.

CREATE TABLE IF NOT EXISTS event_terms (
    event_term_id   BIGSERIAL PRIMARY KEY,
    genre_id        BIGINT NOT NULL REFERENCES genres (genre_id),
    -- As the operator wrote it: shown back exactly, Korean included.
    term            TEXT NOT NULL CHECK (btrim(term) <> ''),
    -- What lookups compare: NFKC, whitespace collapsed, lower-cased - see
    -- runtime.event_terms.normalize_term(), which computes it.
    normalized_term TEXT NOT NULL CHECK (normalized_term <> ''),
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One spelling per genre. The same word may still mean different things in
-- two different genres, which is exactly what the genre scope is for.
CREATE UNIQUE INDEX IF NOT EXISTS event_terms_genre_normalized_key
    ON event_terms (genre_id, normalized_term);

CREATE TABLE IF NOT EXISTS event_term_formats (
    event_term_id BIGINT NOT NULL REFERENCES event_terms (event_term_id) ON DELETE CASCADE,
    event_format  TEXT NOT NULL,
    PRIMARY KEY (event_term_id, event_format)
);

ALTER TABLE events ADD COLUMN IF NOT EXISTS event_formats TEXT[];

INSERT INTO event_terms (genre_id, term, normalized_term)
SELECT g.genre_id, seed.term, seed.normalized_term
FROM genres g
CROSS JOIN (VALUES
    ('Milonga',  'milonga'),
    ('밀롱가',   '밀롱가'),
    ('Practica', 'practica'),
    ('쁘락띠까', '쁘락띠까'),
    ('Pronga',   'pronga'),
    ('쁘롱가',   '쁘롱가')
) AS seed (term, normalized_term)
WHERE g.code = 'TANGO'
ON CONFLICT (genre_id, normalized_term) DO NOTHING;

INSERT INTO event_term_formats (event_term_id, event_format)
SELECT t.event_term_id, mapping.event_format
FROM event_terms t
JOIN genres g ON g.genre_id = t.genre_id AND g.code = 'TANGO'
JOIN (VALUES
    ('milonga',  'MILONGA'),
    ('밀롱가',   'MILONGA'),
    ('practica', 'PRACTICA'),
    ('쁘락띠까', 'PRACTICA'),
    ('pronga',   'MILONGA'),
    ('pronga',   'PRACTICA'),
    ('쁘롱가',   'MILONGA'),
    ('쁘롱가',   'PRACTICA')
) AS mapping (normalized_term, event_format)
  ON mapping.normalized_term = t.normalized_term
ON CONFLICT (event_term_id, event_format) DO NOTHING;
