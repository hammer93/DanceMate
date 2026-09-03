-- DanceMate v0.76 - deep content acquisition.
--
-- A search API is a discovery layer. What it returns is a snippet, not the
-- post: the v0.75 live intake averaged 97 characters, which is why Time, Venue
-- and Fee were missing from almost every candidate. This table holds what was
-- actually fetched from the original URL, kept separate from the discovery
-- record in source_items so the two can never be confused.
--
-- Storage policy: extracted article text only, not raw HTML. Raw pages are
-- large, mostly chrome, and carry copyright and microSD-wear concerns for no
-- extraction benefit. The content hash lets an unchanged page skip reprocessing.

CREATE TABLE IF NOT EXISTS source_item_content (
    source_item_content_id BIGSERIAL PRIMARY KEY,
    source_item_id  BIGINT NOT NULL REFERENCES source_items (source_item_id) ON DELETE CASCADE,

    acquisition_status TEXT NOT NULL,
    -- How the text was obtained, so a thin result can be told from a good one:
    -- article_region / og_description / visible_text / none
    acquisition_method TEXT,
    -- The representation actually fetched. Daum serves the desktop URL as an
    -- iframe shell; the article lives on the mobile host.
    fetched_url     TEXT,
    canonical_url   TEXT,
    http_status     INTEGER,
    content_type    TEXT,

    title           TEXT,
    extracted_text  TEXT,
    content_length  INTEGER NOT NULL DEFAULT 0,
    content_hash    TEXT,
    previous_content_hash TEXT,
    image_count     INTEGER NOT NULL DEFAULT 0,
    poster_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Personal data found and removed before storage, counted so the redaction
    -- can be audited without keeping what it removed.
    redacted_spans  INTEGER NOT NULL DEFAULT 0,

    fetch_error     TEXT,
    error_code      TEXT,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    first_attempt_at TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    reprocessed_at  TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT source_item_content_status_check CHECK (acquisition_status IN (
        'METADATA_ONLY',
        'FETCH_PENDING',
        'FETCHED_FULL',
        'FETCHED_PARTIAL',
        'FETCH_BLOCKED',
        'FETCH_FAILED',
        'LOGIN_REQUIRED',
        'UNSUPPORTED'
    ))
);

-- One content record per source item.
CREATE UNIQUE INDEX IF NOT EXISTS source_item_content_item_key
    ON source_item_content (source_item_id);
CREATE INDEX IF NOT EXISTS source_item_content_status_idx
    ON source_item_content (acquisition_status);
-- The acquisition worker's queue: due, and not already settled.
CREATE INDEX IF NOT EXISTS source_item_content_due_idx
    ON source_item_content (next_attempt_at)
    WHERE acquisition_status IN ('FETCH_PENDING', 'FETCH_FAILED');

-- Content fetches are not provider API calls. Counting them together would
-- make the Kakao quota look spent when nothing was asked of Kakao at all.
CREATE TABLE IF NOT EXISTS content_fetch_log (
    content_fetch_id BIGSERIAL PRIMARY KEY,
    source_item_id   BIGINT REFERENCES source_items (source_item_id) ON DELETE CASCADE,
    host             TEXT NOT NULL,
    http_status      INTEGER,
    outcome          TEXT NOT NULL,
    text_length      INTEGER NOT NULL DEFAULT 0,
    duration_ms      INTEGER,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS content_fetch_log_fetched_idx
    ON content_fetch_log (fetched_at DESC);
CREATE INDEX IF NOT EXISTS content_fetch_log_host_idx
    ON content_fetch_log (host, fetched_at DESC);

-- Existing live items start as what they honestly are: discovery only.
INSERT INTO source_item_content (source_item_id, acquisition_status, content_length)
SELECT source_item_id, 'METADATA_ONLY', 0
FROM source_items
ON CONFLICT (source_item_id) DO NOTHING;
