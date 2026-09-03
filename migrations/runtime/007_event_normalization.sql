-- v0.77 PHASE D: Event Normalization.
--
-- One row per event instance: a thing happening on one date, which is what a
-- dancer looks for. The Information Engine keeps producing candidates in its
-- own store; this is the runtime's normalised view of them, and it is the only
-- thing the alpha search API reads.
--
-- Two distinctions the schema refuses to collapse:
--
--   Series vs instance. "매주 토요일 밀롱가" recurring at one venue is a series;
--   this Saturday's is an instance. series_key groups instances so a duplicate
--   check can tell "the same event posted twice" from "the same event, next
--   week". It never merges them.
--
--   Extracted vs resolved venue. venue_text is the string the post carried.
--   venue_id is a Venue Master row a person stands behind. A venue we have
--   read but not recognised is UNRESOLVED and stays that way until someone
--   decides; nothing here creates a venue.

CREATE TABLE IF NOT EXISTS events (
    event_id        BIGSERIAL PRIMARY KEY,

    -- Provenance. candidate_id is the engine's, kept so the engine store stays
    -- the source of truth and this table can always be rebuilt from it.
    candidate_id    BIGINT NOT NULL,
    post_id         BIGINT,
    source_item_id  BIGINT REFERENCES source_items (source_item_id),
    source_url      TEXT,

    event_name      TEXT NOT NULL,
    event_type      TEXT,
    event_date      DATE NOT NULL,
    start_time      TIME,
    end_time        TIME,
    end_day_offset  SMALLINT NOT NULL DEFAULT 0,

    venue_text      TEXT,
    venue_id        BIGINT REFERENCES venues (venue_id),
    venue_status    TEXT NOT NULL DEFAULT 'ABSENT',

    fee             INTEGER,
    genre_id        BIGINT REFERENCES genres (genre_id),
    region_id       BIGINT REFERENCES regions (region_id),

    -- The engine's lifecycle verdict and the human's, side by side. Neither
    -- overwrites the other: APPROVE has never granted VERIFIED and does not
    -- start here.
    engine_status   TEXT NOT NULL DEFAULT 'POSSIBLE',
    review_state    TEXT NOT NULL DEFAULT 'PENDING',

    -- Which fields a person corrected, so the console can show both readings.
    field_origin    JSONB NOT NULL DEFAULT '{}'::jsonb,

    identity_key    TEXT NOT NULL,
    series_key      TEXT,

    -- Set by PHASE E. Declared here so a search query needs one table.
    canonical_event_id  BIGINT REFERENCES events (event_id),
    duplicate_decided_by TEXT,

    -- Whether the alpha search may show it. Never granted automatically to a
    -- candidate a person has rejected.
    listing_state   TEXT NOT NULL DEFAULT 'LISTED',

    -- Where the post came from. The alpha user surface serves LIVE only: a
    -- recorded snapshot replayed for testing, or a PoC fixture, must never
    -- appear to a dancer as something happening this Saturday.
    provenance      TEXT NOT NULL DEFAULT 'UNKNOWN',

    normalized_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT events_venue_status_check
        CHECK (venue_status IN ('RESOLVED', 'UNRESOLVED', 'ABSENT')),
    CONSTRAINT events_listing_state_check
        CHECK (listing_state IN ('LISTED', 'HIDDEN')),
    CONSTRAINT events_provenance_check
        CHECK (provenance IN ('LIVE', 'SNAPSHOT', 'FIXTURE', 'UNKNOWN')),
    CONSTRAINT events_duplicate_decided_by_check
        CHECK (duplicate_decided_by IS NULL OR duplicate_decided_by IN ('AUTO', 'HUMAN')),
    -- A resolved venue needs a venue; an unresolved one needs the text we read.
    CONSTRAINT events_venue_link_check
        CHECK ((venue_status = 'RESOLVED' AND venue_id IS NOT NULL)
            OR (venue_status = 'UNRESOLVED' AND venue_text IS NOT NULL)
            OR (venue_status = 'ABSENT' AND venue_id IS NULL)),
    -- An event cannot be its own duplicate.
    CONSTRAINT events_not_self_duplicate
        CHECK (canonical_event_id IS NULL OR canonical_event_id <> event_id)
);

-- One normalised row per engine candidate. Re-normalising updates in place
-- rather than accumulating copies.
CREATE UNIQUE INDEX IF NOT EXISTS events_candidate_key
    ON events (candidate_id);

-- The alpha search's own query: listed, live, canonical, by date.
CREATE INDEX IF NOT EXISTS events_listing_idx
    ON events (event_date, provenance, listing_state)
    WHERE canonical_event_id IS NULL;
CREATE INDEX IF NOT EXISTS events_date_idx
    ON events (event_date);
CREATE INDEX IF NOT EXISTS events_identity_idx
    ON events (identity_key);
CREATE INDEX IF NOT EXISTS events_series_idx
    ON events (series_key) WHERE series_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS events_venue_idx
    ON events (venue_id) WHERE venue_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS events_canonical_idx
    ON events (canonical_event_id) WHERE canonical_event_id IS NOT NULL;

-- Venue strings we have read and not recognised. A queue for a person, not a
-- staging area that becomes a Venue Master row on its own: registering a venue
-- stays a decision someone makes in the console.
CREATE TABLE IF NOT EXISTS unresolved_venues (
    unresolved_venue_id BIGSERIAL PRIMARY KEY,
    venue_text      TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    alias_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- OPEN until someone links it to a venue or dismisses it.
    state           TEXT NOT NULL DEFAULT 'OPEN',
    resolved_venue_id BIGINT REFERENCES venues (venue_id),
    resolved_by     TEXT,
    resolved_at     TIMESTAMPTZ,
    CONSTRAINT unresolved_venues_state_check
        CHECK (state IN ('OPEN', 'LINKED', 'DISMISSED')),
    CONSTRAINT unresolved_venues_linked_needs_venue
        CHECK (state <> 'LINKED' OR resolved_venue_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS unresolved_venues_normalized_key
    ON unresolved_venues (normalized_text);
CREATE INDEX IF NOT EXISTS unresolved_venues_state_idx
    ON unresolved_venues (state);
