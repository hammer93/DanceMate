-- DanceMate v0.89.0 - Community Discovery.
--
-- Staging for community candidates found through public search (NAVER API
-- HUB and Kakao Daum search, through the Information Engine's own clients).
-- Nothing here is shown to the public and nothing here is a community: a
-- candidate becomes a row of `communities` only when an operator registers it
-- in the Admin review screen, through communities.create_community().
--
-- * community_discovery_queries - the search keywords per genre (defaults are
--   inserted by the application for the genres that exist; an operator can
--   add more and switch any off).
-- * community_discovery_runs   - one search run: scope, per-provider outcome,
--   counts. At most one run is open (QUEUED or RUNNING) at a time.
-- * community_discovery_items  - one candidate per public identity (a Naver
--   or Daum cafe, a Band, a homepage host ...), so the same cafe found by ten
--   queries is one row whose first_seen/last_seen/seen_count move. Only short,
--   redacted evidence is kept - never a page's HTML.
-- * ..._item_genres / ..._item_venues - genre evidence (by genre FK) and venue
--   candidates (by venue FK) for review; neither creates a real relation.

CREATE TABLE IF NOT EXISTS community_discovery_queries (
    query_id        BIGSERIAL PRIMARY KEY,
    genre_id        BIGINT NOT NULL REFERENCES genres (genre_id) ON DELETE CASCADE,
    keyword         TEXT NOT NULL,
    provider_scope  TEXT NOT NULL DEFAULT 'ALL',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT community_discovery_queries_keyword_check CHECK (btrim(keyword) <> ''),
    CONSTRAINT community_discovery_queries_scope_check
        CHECK (provider_scope IN ('ALL', 'NAVER', 'KAKAO'))
);

CREATE UNIQUE INDEX IF NOT EXISTS community_discovery_queries_key
    ON community_discovery_queries (genre_id, lower(btrim(keyword)));

CREATE TABLE IF NOT EXISTS community_discovery_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'QUEUED',
    providers       TEXT[] NOT NULL,
    genre_codes     TEXT[] NOT NULL,
    region_codes    TEXT[] NOT NULL DEFAULT '{}',
    extra_keywords  TEXT[] NOT NULL DEFAULT '{}',
    requested_by    TEXT,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    query_count     INTEGER NOT NULL DEFAULT 0,
    result_count    INTEGER NOT NULL DEFAULT 0,
    new_items       INTEGER NOT NULL DEFAULT 0,
    updated_items   INTEGER NOT NULL DEFAULT 0,
    -- Per provider: outcome (SUCCESS / NO_RESULTS / PARTIAL_SUCCESS /
    -- ACCESS_LIMITED / RATE_LIMITED / ERROR), call and result counts, and
    -- redacted error lines. Never a credential.
    provider_status JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_summary   TEXT,

    CONSTRAINT community_discovery_runs_status_check
        CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCESS', 'PARTIAL_SUCCESS', 'FAILED')),
    CONSTRAINT community_discovery_runs_providers_check
        CHECK (cardinality(providers) > 0 AND providers <@ ARRAY['NAVER', 'KAKAO']::TEXT[])
);

-- One open run at a time, enforced by the database: a second click, a second
-- tab or a second operator cannot queue a parallel search.
CREATE UNIQUE INDEX IF NOT EXISTS community_discovery_runs_one_open
    ON community_discovery_runs ((true)) WHERE status IN ('QUEUED', 'RUNNING');

CREATE TABLE IF NOT EXISTS community_discovery_items (
    item_id                  BIGSERIAL PRIMARY KEY,
    -- The public identity this candidate is: 'naver-cafe:<club>',
    -- 'daum-cafe:<cafe>', 'band:<id>', 'web:<host>' ...
    identity_key             TEXT NOT NULL,
    platform                 TEXT NOT NULL,
    community_url            TEXT NOT NULL,
    title                    TEXT NOT NULL DEFAULT '',
    -- NULL when no name could be read with confidence - an unresolved name
    -- is better than a wrong one taken from a post title.
    candidate_name           TEXT,
    normalized_name          TEXT,
    observed_names           TEXT[] NOT NULL DEFAULT '{}',
    snippet                  TEXT NOT NULL DEFAULT '',
    region_id                BIGINT REFERENCES regions (region_id) ON DELETE SET NULL,
    region_candidate         TEXT,
    providers                TEXT[] NOT NULL DEFAULT '{}',
    queries                  TEXT[] NOT NULL DEFAULT '{}',
    first_seen               TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen                TIMESTAMPTZ NOT NULL DEFAULT now(),
    seen_count               INTEGER NOT NULL DEFAULT 1,
    recent_activity_date     DATE,
    activity                 TEXT NOT NULL DEFAULT 'UNVERIFIED',
    kind                     TEXT NOT NULL DEFAULT 'UNKNOWN',
    classification           TEXT NOT NULL DEFAULT 'UNVERIFIED',
    confidence               TEXT NOT NULL DEFAULT 'LOW',
    reasons                  TEXT[] NOT NULL DEFAULT '{}',
    existing_community_id    BIGINT REFERENCES communities (community_id) ON DELETE SET NULL,
    duplicate_of_item_id     BIGINT REFERENCES community_discovery_items (item_id) ON DELETE SET NULL,
    review_state             TEXT NOT NULL DEFAULT 'PENDING',
    registered_community_id  BIGINT REFERENCES communities (community_id) ON DELETE SET NULL,
    reviewed_by              TEXT,
    reviewed_at              TIMESTAMPTZ,
    last_run_id              BIGINT REFERENCES community_discovery_runs (run_id) ON DELETE SET NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT community_discovery_items_activity_check
        CHECK (activity IN ('ACTIVE', 'STALE', 'INACTIVE', 'UNVERIFIED')),
    CONSTRAINT community_discovery_items_classification_check
        CHECK (classification IN ('VERIFIED_NEW', 'VERIFIED_EXISTING', 'POSSIBLE_DUPLICATE',
                                  'UNVERIFIED', 'STALE', 'INACTIVE', 'NOT_A_COMMUNITY')),
    CONSTRAINT community_discovery_items_confidence_check
        CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
    CONSTRAINT community_discovery_items_review_check
        CHECK (review_state IN ('PENDING', 'APPROVED', 'LINKED', 'HELD', 'REJECTED'))
);

CREATE UNIQUE INDEX IF NOT EXISTS community_discovery_items_identity
    ON community_discovery_items (identity_key);
CREATE INDEX IF NOT EXISTS community_discovery_items_review_idx
    ON community_discovery_items (review_state, classification, confidence);
CREATE INDEX IF NOT EXISTS community_discovery_items_name_idx
    ON community_discovery_items (normalized_name);

CREATE TABLE IF NOT EXISTS community_discovery_item_genres (
    item_id   BIGINT NOT NULL REFERENCES community_discovery_items (item_id) ON DELETE CASCADE,
    genre_id  BIGINT NOT NULL REFERENCES genres (genre_id) ON DELETE CASCADE,
    evidence  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (item_id, genre_id)
);

CREATE TABLE IF NOT EXISTS community_discovery_item_venues (
    item_id     BIGINT NOT NULL REFERENCES community_discovery_items (item_id) ON DELETE CASCADE,
    venue_id    BIGINT NOT NULL REFERENCES venues (venue_id) ON DELETE CASCADE,
    match_kind  TEXT NOT NULL,
    evidence    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (item_id, venue_id),
    CONSTRAINT community_discovery_item_venues_kind_check
        CHECK (match_kind IN ('VENUE_MATCH', 'VENUE_CANDIDATE'))
);
