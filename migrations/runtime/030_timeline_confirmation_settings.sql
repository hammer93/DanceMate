-- DanceMate v0.86.4 - Admin Source Audit & Public Display Parity.
--
-- The Timeline's "?" confirmation indicator (Section 7-21, 72-75) replaces
-- the old "확인 필요" text badge and is admin-configurable per engine status,
-- reusing the engine's existing POSSIBLE/EXPECTED/CONFLICT/UNKNOWN
-- vocabulary rather than inventing a confidence score. No generic
-- admin-settings mechanism exists anywhere in this codebase to reuse
-- (investigated first, per Section 21) - this is the smallest table that
-- supports the required enum-based checklist. A single row (id=1, enforced
-- by the CHECK): one site-wide toggle, not per-source/per-genre
-- configuration.
--
-- VERIFIED has no column at all - Section 73 explicitly discourages ever
-- letting VERIFIED show "?", so there is no way to configure it back on.
-- CANCELLED/COMPLETED are excluded the same way: existing UI already owns
-- that signal (see runtime/timeline_settings.py's own docstring).

CREATE TABLE IF NOT EXISTS timeline_confirmation_settings (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    show_for_possible BOOLEAN NOT NULL DEFAULT TRUE,
    show_for_expected BOOLEAN NOT NULL DEFAULT TRUE,
    show_for_conflict BOOLEAN NOT NULL DEFAULT TRUE,
    show_for_unknown BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO timeline_confirmation_settings (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;
