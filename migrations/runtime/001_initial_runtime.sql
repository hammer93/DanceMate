-- DanceMate Runtime v0.74 - initial PostgreSQL schema.
--
-- Scope: runtime/scheduler bookkeeping only.
-- The Information Engine keeps its own SQLite persistence (hybrid persistence);
-- no engine table is mirrored here.

CREATE TABLE IF NOT EXISTS runtime_state (
    state_key   TEXT PRIMARY KEY,
    state_value TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
    worker       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    detail       TEXT,
    last_beat_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_runs (
    job_run_id  BIGSERIAL PRIMARY KEY,
    job_name    TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

-- Only the recent tail is ever queried; keeps the index small on microSD.
CREATE INDEX IF NOT EXISTS job_runs_started_at_idx
    ON job_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS job_runs_job_name_started_at_idx
    ON job_runs (job_name, started_at DESC);
