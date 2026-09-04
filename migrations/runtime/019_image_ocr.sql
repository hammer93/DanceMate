-- DanceMate v0.81.3 - image text fallback extraction.
--
-- source_item_content.poster_candidates already holds up to 10 bare image
-- URLs per item, but nothing about any of them: no OCR text, no confidence,
-- no way to tell "already tried, nothing legible" from "never looked at".
-- This table is one row per image actually considered for OCR, keyed so the
-- same poster image reused across several source items (a festival's flyer
-- reposted by five different cafes) is OCR'd once, not five times.

CREATE TABLE IF NOT EXISTS source_item_image (
    source_item_image_id BIGSERIAL PRIMARY KEY,
    source_item_id  BIGINT NOT NULL REFERENCES source_items (source_item_id) ON DELETE CASCADE,

    image_url       TEXT NOT NULL,
    image_index     INTEGER NOT NULL DEFAULT 0,
    -- sha256 of the fetched bytes. Null until a fetch actually succeeded;
    -- the cache lookup keys on this, not the URL, so a re-hosted copy of the
    -- same poster is still recognised.
    content_hash    TEXT,

    media_class     TEXT,
    media_class_reason TEXT,
    width           INTEGER,
    height          INTEGER,

    fetch_status    TEXT NOT NULL DEFAULT 'NOT_NEEDED',
    ocr_status      TEXT,
    ocr_engine      TEXT,
    ocr_language    TEXT,
    ocr_confidence  REAL,
    ocr_text        TEXT,
    redacted_spans  INTEGER NOT NULL DEFAULT 0,

    -- Did extract_with_image_fallback() actually use this image's text for
    -- any field. False for every image whose OCR ran but contributed
    -- nothing (the body was already complete, or a later-priority image
    -- won instead) - kept for the audit trail, not treated as a failure.
    used_as_fallback BOOLEAN NOT NULL DEFAULT FALSE,

    processed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT source_item_image_fetch_status_check CHECK (fetch_status IN (
        'NOT_NEEDED',
        'NO_IMAGE',
        'FETCHED',
        'UNSAFE_URL',
        'FETCH_FAILED',
        'UNSUPPORTED_TYPE',
        'TOO_LARGE'
    )),
    CONSTRAINT source_item_image_ocr_status_check CHECK (ocr_status IS NULL OR ocr_status IN (
        'OCR_SUCCESS',
        'OCR_LOW_CONFIDENCE',
        'OCR_FAILED',
        'TOO_SMALL'
    )),
    CONSTRAINT source_item_image_url_key UNIQUE (source_item_id, image_url)
);

-- The cache lookup: "have we already OCR'd bytes with this hash". Partial,
-- since most rows never reach a successful fetch.
CREATE INDEX IF NOT EXISTS source_item_image_hash_idx
    ON source_item_image (content_hash)
    WHERE content_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS source_item_image_item_idx
    ON source_item_image (source_item_id);
