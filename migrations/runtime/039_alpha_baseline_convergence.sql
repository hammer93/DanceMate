-- DanceMate v0.90.0 - Alpha Readiness & Baseline Convergence.
--
-- A fresh 001-038 install and the real Production database have quietly
-- diverged since early in this project: three Regions, three Genres and one
-- Source that Production has carried since before migrations existed (or
-- that an operator added by hand through the Admin console later) were
-- never captured in a migration. None of this is new data - every row this
-- migration adds already exists, unchanged, in Production today - this only
-- makes a fresh install converge on the same baseline rather than starting
-- from a narrower one. Forward-only; no existing migration (001-038)
-- changed. Every statement below is idempotent (ON CONFLICT DO NOTHING /
-- conditional UPDATE), so re-applying this migration, or running it against
-- a database that already has some of these rows by hand, is a no-op for
-- whatever already exists - Production's own ids, enabled flags and
-- timestamps on any pre-existing row are left exactly as an operator left
-- them.
--
-- Regions: KR-BUSAN and KR-INCHEON were, per migration 038's own audit
-- (038:28-33) and this project's release notes, "only ever added by hand
-- through the Admin console, never migration-seeded" - migration 024's
-- comment claiming the master "always seeded KR/KR-SEOUL/KR-BUSAN" was
-- itself wrong (024_regional_coverage_expansion.sql seeds neither KR-BUSAN
-- nor anything before it does). KR-DAEJEON is the same story (024's own
-- comment: "added later, live, by an operator"). All three were left out of
-- 038 deliberately, as a documented follow-up, because adding KR-BUSAN
-- there surfaced two pre-existing stale assertions in tests/test_genre_
-- filter.py (fixed alongside this migration - see that file). All three are
-- also no longer optional: runtime/community_discovery.py's own
-- REGION_QUERY_CODES and REGION_HINTS (current, shipped code) already treat
-- KR-BUSAN/KR-DAEJEON/KR-INCHEON as first-class Discovery query regions: a
-- fresh install silently could never resolve a Busan/Daejeon/Incheon
-- community. KR-SEJONG, also named in runtime/venue_resolution.py's
-- _REGION_BY_ADMIN, stays deliberately unseeded - no Production row and no
-- Admin-confirmed event names it (same policy 038 already applied).
--
-- Genres: runtime/community_discovery.py's TARGET_GENRES/DEFAULT_QUERIES
-- (current, shipped code) already name six genres - TANGO/SALSA/SWING
-- (migration 002) plus BACHATA/BALBOA/KIZOMBA, which exist in Production
-- only because an operator added them by hand (their high, non-sequential
-- genre_id values there are exactly that fingerprint). A fresh install
-- without them means Community Discovery silently only ever queries half
-- its own target vocabulary.
--
-- SRC-W-001 "K-TANGO": migration 021's own comment already says this row
-- "was added through the admin console at runtime", not by any migration -
-- registered in Production since v0.81, before this project's source
-- migrations began. Two regression tests (test_k_tango_is_preserved_
-- untouched, test_existing_top3_sources_are_preserved) are named
-- specifically after preserving it, and both have failed on every fresh
-- install this project has ever produced for exactly that reason. Seeded
-- here with Production's own current field values (platform WEB, role
-- ORGANIZER, authority PRIMARY_ORGANIZER - a valid, unrelated value; enabled
-- true; the same interval/url/config Production carries today).
--
-- SRC-D-003 authority_level correction: migration 027 seeded SRC-D-003 with
-- authority_level = 'PRIMARY_COMMUNITY', a value runtime/sources.py's own
-- AUTHORITY_LEVELS domain has never included. This project's own v0.87.0
-- release notes call it explicitly "a value outside the system's real
-- enum" and, when the same bad value turned up in a later CSV import,
-- corrected those new rows to 'UNKNOWN' - "matching the convention every
-- other COMMUNITY-role source already uses" - while deliberately leaving
-- this one Production row untouched at the time to avoid an unrelated edit.
-- PRIMARY_COMMUNITY is not being added to AUTHORITY_LEVELS (it is not an
-- authoritative value - no code anywhere else in this project reads or
-- writes it); instead this migration finishes that same correction the
-- v0.87.0 CSV import already established as the right fix, conditionally,
-- only for this one row, only if it still carries the bad value, and
-- without touching any of its other fields. This is also what makes the
-- Admin enable/disable action's 500 (fixed alongside this migration in
-- runtime/admin.py) stop being reachable through this row in the first
-- place.

INSERT INTO regions (code, country, city, name) VALUES
    ('KR-BUSAN',   'South Korea', 'Busan',   '부산'),
    ('KR-DAEJEON', 'South Korea', 'Daejeon', '대전'),
    ('KR-INCHEON', 'South Korea', 'Incheon', '인천')
ON CONFLICT (code) DO NOTHING;

INSERT INTO genres (code, name) VALUES
    ('BACHATA', 'Bachata'),
    ('BALBOA',  'Balboa'),
    ('KIZOMBA', 'Kizomba')
ON CONFLICT (code) DO NOTHING;

INSERT INTO sources (
    source_key, name, platform, source_role, url, region_id, genre_id,
    authority_level, queries, config, enabled, collection_interval_minutes, notes
) VALUES (
    'SRC-W-001', 'K-TANGO', 'WEB', 'ORGANIZER', 'http://www.k-tango.net/',
    NULL, NULL, 'PRIMARY_ORGANIZER',
    '[]'::jsonb,
    jsonb_build_object(
        'board_urls', jsonb_build_array('http://www.k-tango.net/cnf/festival02/index.jsp')
    ),
    TRUE, 240,
    'Korea Tango Community and Festival organizing committee board. ' ||
    'Registered v0.81 as the first WEB-platform source.'
)
ON CONFLICT (source_key) DO NOTHING;

-- Only SRC-D-003, only if it still carries the bad legacy value; every
-- other field (name/url/queries/config/enabled/collection_interval_minutes)
-- and every other source's authority_level is untouched. When the row
-- already reads 'UNKNOWN' (or does not exist), this UPDATE matches zero
-- rows and updated_at does not move.
UPDATE sources SET authority_level = 'UNKNOWN', updated_at = now()
WHERE source_key = 'SRC-D-003' AND authority_level = 'PRIMARY_COMMUNITY';
