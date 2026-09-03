-- DanceMate v0.75 - Source Master and real source intake.
--
-- The Source Master is what an operator turns on and off in the admin console;
-- the scheduler only ever collects from sources marked enabled here.
--
-- Intake is stored raw. Interpretation is the Information Engine's job, and it
-- keeps its own SQLite store - nothing in this file mirrors an engine table.

CREATE TABLE IF NOT EXISTS sources (
    source_id                   BIGSERIAL PRIMARY KEY,
    -- Stable operator-facing key, e.g. SRC-D-001. Also how a row is matched to
    -- the Information Engine's own config/sources.json entries.
    source_key                  TEXT NOT NULL,
    name                        TEXT NOT NULL,
    platform                    TEXT NOT NULL,
    source_role                 TEXT NOT NULL,
    url                         TEXT,
    genre_id                    BIGINT REFERENCES genres (genre_id),
    region_id                   BIGINT REFERENCES regions (region_id),
    authority_level             TEXT NOT NULL DEFAULT 'UNKNOWN',
    access_state                TEXT NOT NULL DEFAULT 'UNKNOWN',
    -- Search terms for the API-backed collectors, one per element.
    queries                     JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Collector-specific settings (cafe hints, url filters, snapshot paths).
    config                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled                     BOOLEAN NOT NULL DEFAULT FALSE,
    collection_interval_minutes INTEGER NOT NULL DEFAULT 60,
    last_collected_at           TIMESTAMPTZ,
    last_status                 TEXT,
    last_detail                 TEXT,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT sources_platform_check CHECK (platform IN (
        'DAUM_CAFE', 'NAVER_CAFE', 'NAVER_BLOG', 'FACEBOOK', 'WEB', 'DIRECTORY'
    )),
    CONSTRAINT sources_role_check CHECK (source_role IN (
        'COMMUNITY', 'PROMOTION_BOARD', 'VENUE', 'ORGANIZER', 'DIRECTORY', 'AGGREGATOR'
    )),
    -- A source polled faster than every 10 minutes would hammer both the
    -- upstream service and a 32GB microSD.
    CONSTRAINT sources_interval_check CHECK (collection_interval_minutes >= 10)
);

CREATE UNIQUE INDEX IF NOT EXISTS sources_key_unique ON sources (source_key);
-- Two rows pointing at the same URL are a duplicate, not two sources. NULL urls
-- are allowed and unconstrained: API-backed sources are identified by queries.
CREATE UNIQUE INDEX IF NOT EXISTS sources_url_unique
    ON sources (lower(url)) WHERE url IS NOT NULL AND url <> '';
CREATE INDEX IF NOT EXISTS sources_enabled_idx
    ON sources (enabled, last_collected_at);

CREATE TABLE IF NOT EXISTS source_collection_runs (
    collection_run_id BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    mode              TEXT NOT NULL,
    status            TEXT NOT NULL,
    discovered_count  INTEGER NOT NULL DEFAULT 0,
    new_count         INTEGER NOT NULL DEFAULT 0,
    duplicate_count   INTEGER NOT NULL DEFAULT 0,
    error             TEXT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS source_collection_runs_source_idx
    ON source_collection_runs (source_id, started_at DESC);
CREATE INDEX IF NOT EXISTS source_collection_runs_started_idx
    ON source_collection_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS source_items (
    source_item_id    BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    collection_run_id BIGINT REFERENCES source_collection_runs (collection_run_id) ON DELETE SET NULL,
    -- The upstream's own identifier where it has one, else the URL.
    external_id       TEXT NOT NULL,
    url               TEXT,
    title             TEXT,
    body              TEXT,
    published_at      TIMESTAMPTZ,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- sha256 over the meaningful content: re-collecting an unchanged post is a
    -- duplicate, an edited one is a new revision.
    content_hash      TEXT NOT NULL,
    raw               JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Whether this item has been handed to the Information Engine yet.
    ingest_state      TEXT NOT NULL DEFAULT 'PENDING',
    ingested_at       TIMESTAMPTZ,

    CONSTRAINT source_items_ingest_state_check CHECK (ingest_state IN (
        'PENDING', 'INGESTED', 'SKIPPED', 'FAILED'
    ))
);

-- Dedup key: the same upstream item from the same source is stored once.
CREATE UNIQUE INDEX IF NOT EXISTS source_items_source_external_key
    ON source_items (source_id, external_id);
CREATE INDEX IF NOT EXISTS source_items_hash_idx ON source_items (content_hash);
CREATE INDEX IF NOT EXISTS source_items_pending_idx
    ON source_items (ingest_state, collected_at) WHERE ingest_state = 'PENDING';
CREATE INDEX IF NOT EXISTS source_items_collected_idx
    ON source_items (collected_at DESC);

CREATE TABLE IF NOT EXISTS source_errors (
    source_error_id   BIGSERIAL PRIMARY KEY,
    source_id         BIGINT REFERENCES sources (source_id) ON DELETE CASCADE,
    collection_run_id BIGINT REFERENCES source_collection_runs (collection_run_id) ON DELETE CASCADE,
    kind              TEXT NOT NULL,
    detail            TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS source_errors_source_idx
    ON source_errors (source_id, occurred_at DESC);
