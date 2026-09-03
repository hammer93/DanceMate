-- DanceMate v0.76 - provider usage, quota and cost monitoring.
--
-- The question this answers: "how many times did we call an external API
-- today, and what did those calls actually get us?"
--
-- Two things are counted separately and must never be added together:
--   API requests   - calls to a provider's search API (Kakao, Naver)
--   content fetches - HTTP GETs of an original post, which cost no API quota
--
-- Daily aggregate rather than a row per call: a row per request would be a
-- write amplifier on a 32GB microSD for information nobody reads at that
-- resolution. The per-run detail already lives in source_collection_runs.

CREATE TABLE IF NOT EXISTS provider_usage_daily (
    usage_date        DATE NOT NULL,
    provider          TEXT NOT NULL,
    api_name          TEXT NOT NULL,

    request_count     INTEGER NOT NULL DEFAULT 0,
    success_count     INTEGER NOT NULL DEFAULT 0,
    error_count       INTEGER NOT NULL DEFAULT 0,
    rate_limit_count  INTEGER NOT NULL DEFAULT 0,
    auth_error_count  INTEGER NOT NULL DEFAULT 0,

    item_count        INTEGER NOT NULL DEFAULT 0,
    new_item_count    INTEGER NOT NULL DEFAULT 0,
    duplicate_item_count INTEGER NOT NULL DEFAULT 0,

    last_status       TEXT,
    last_request_at   TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (usage_date, provider, api_name)
);

CREATE INDEX IF NOT EXISTS provider_usage_daily_date_idx
    ON provider_usage_daily (usage_date DESC);

-- What we believe about a provider's limits and price, and how strongly.
--
-- The status column exists because "it looks free right now" is not the same
-- as "it is free". Nothing here may be rendered as a cost figure unless
-- pricing_status says the figures were actually verified.
CREATE TABLE IF NOT EXISTS provider_pricing_config (
    provider         TEXT NOT NULL,
    api_name         TEXT NOT NULL,

    -- CONFIGURED  a value we chose ourselves, e.g. a self-imposed budget
    -- DOCUMENTED  taken from the provider's published documentation
    -- OBSERVED    inferred from responses we actually received
    -- UNKNOWN     we do not know
    quota_limit      INTEGER,
    quota_status     TEXT NOT NULL DEFAULT 'UNKNOWN',
    quota_source_url TEXT,

    -- FREE / PAID / UNKNOWN / NOT_CONFIGURED. Never defaulted to FREE.
    pricing_status   TEXT NOT NULL DEFAULT 'UNKNOWN',
    free_quota       INTEGER,
    unit_size        INTEGER,
    unit_price       NUMERIC(12, 4),
    currency         TEXT,
    price_source_url TEXT,
    effective_from   DATE,
    verified_at      TIMESTAMPTZ,
    notes            TEXT,

    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (provider, api_name),
    CONSTRAINT provider_quota_status_check CHECK (quota_status IN (
        'CONFIGURED', 'DOCUMENTED', 'OBSERVED', 'UNKNOWN'
    )),
    CONSTRAINT provider_pricing_status_check CHECK (pricing_status IN (
        'FREE', 'PAID', 'UNKNOWN', 'NOT_CONFIGURED'
    ))
);

-- Seed what is actually known today, and nothing more.
--
-- Kakao: the 5000/day figure is our own self-imposed budget, not a published
-- provider limit, so it is CONFIGURED rather than DOCUMENTED. Price is UNKNOWN
-- because we have not verified Kakao's current terms - it is not recorded as
-- FREE just because no invoice has arrived.
--
-- Naver: the engine's settings.json cites 25,000 calls/day from Naver's Search
-- API documentation, so the quota is DOCUMENTED. Price likewise UNKNOWN.
INSERT INTO provider_pricing_config
    (provider, api_name, quota_limit, quota_status, pricing_status, notes)
VALUES
    ('KAKAO', 'daum_cafe_search', 5000, 'CONFIGURED', 'UNKNOWN',
     'Self-imposed daily budget. Kakao''s published quota and pricing have not been verified.'),
    ('NAVER', 'search_blog', 25000, 'DOCUMENTED', 'UNKNOWN',
     '25,000 calls/day per the Naver Search API documentation cited in engine/config/settings.json.'),
    ('NAVER', 'search_cafearticle', 25000, 'DOCUMENTED', 'UNKNOWN',
     'Shares the same daily allowance and the same credential as search_blog.')
ON CONFLICT (provider, api_name) DO NOTHING;
