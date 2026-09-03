-- DanceMate v0.75 - operator-managed master data.
--
-- Scope: the reference data an operator maintains in the admin console.
-- Nothing here duplicates Information Engine tables; the engine keeps its own
-- SQLite store and is not touched.
--
-- Rows are disabled, not deleted. A venue that stops hosting events still has
-- to resolve for the events already attributed to it.

CREATE TABLE IF NOT EXISTS genres (
    genre_id   BIGSERIAL PRIMARY KEY,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS genres_code_key ON genres (code);

CREATE TABLE IF NOT EXISTS regions (
    region_id  BIGSERIAL PRIMARY KEY,
    code       TEXT NOT NULL,
    country    TEXT NOT NULL,
    city       TEXT,
    district   TEXT,
    name       TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS regions_code_key ON regions (code);

CREATE TABLE IF NOT EXISTS venues (
    venue_id   BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    region_id  BIGINT REFERENCES regions (region_id),
    address    TEXT,
    latitude   DOUBLE PRECISION,
    longitude  DOUBLE PRECISION,
    notes      TEXT,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A venue name is only unique within its region: "Studio A" in Seoul and
-- "Studio A" in Busan are different places.
CREATE UNIQUE INDEX IF NOT EXISTS venues_region_name_key
    ON venues (region_id, lower(name));

-- Aliases are what makes "La Ventana", "라벤타나" and "벤타나" resolve to one
-- venue. Normalised on write so lookup is a plain equality match.
CREATE TABLE IF NOT EXISTS venue_aliases (
    venue_alias_id  BIGSERIAL PRIMARY KEY,
    venue_id        BIGINT NOT NULL REFERENCES venues (venue_id) ON DELETE CASCADE,
    alias           TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS venue_aliases_normalized_key
    ON venue_aliases (normalized_alias);
CREATE INDEX IF NOT EXISTS venue_aliases_venue_idx
    ON venue_aliases (venue_id);

CREATE TABLE IF NOT EXISTS organizers (
    organizer_id BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    genre_id     BIGINT REFERENCES genres (genre_id),
    region_id    BIGINT REFERENCES regions (region_id),
    contact_url  TEXT,
    notes        TEXT,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS organizers_name_region_key
    ON organizers (lower(name), COALESCE(region_id, 0));

-- Seed: only what is actually decided. Three genres and Seoul, nothing invented.
INSERT INTO genres (code, name) VALUES
    ('TANGO', 'Tango'),
    ('SALSA', 'Salsa'),
    ('SWING', 'Swing')
ON CONFLICT (code) DO NOTHING;

INSERT INTO regions (code, country, city, name) VALUES
    ('KR', 'South Korea', NULL, 'South Korea'),
    ('KR-SEOUL', 'South Korea', 'Seoul', 'Seoul')
ON CONFLICT (code) DO NOTHING;
