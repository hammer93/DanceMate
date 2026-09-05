-- DanceMate v0.82 Tango Source Expansion - venue alias seed for cross-source
-- duplicate resolution (docs/TANGO_SOURCE_DISCOVERY.md Section 10, this
-- release's task Section 5).
--
-- This deliberately does NOT add a new duplicate-detection system.
-- runtime/duplicates.py already auto-merges two events sharing the same
-- date, start time and *venue_id* (classify()'s RULE_SAME_DATE_VENUE_TIME),
-- and runtime/normalization.py's resolve_venue() already resolves every new
-- candidate's raw venue text against venue_aliases automatically, for every
-- source. The only thing actually missing for these eight well-known studios
-- is the alias rows themselves - once "PISTA" and "피스타" both resolve to
-- the same venue_id, TangoNOW writing "PISTA" and DanceInfo writing "피스타"
-- for the same Saturday milonga already merge through the existing pipeline
-- with no code change. This is that seed, in the existing venues/venue_aliases
-- tables, following 002_master_data.sql's own idempotent seed style.
--
-- region_id is left NULL for every venue here on purpose: the discovery
-- report's own city attributions for these names were not all consistent
-- across sources (docs/TANGO_SOURCE_DISCOVERY.md Section 14), and a wrong
-- region asserted here would be worse than an unset one - dedup itself does
-- not depend on region_id, only on venue_id + date + start_time, so nothing
-- about the merge behaviour needs it. A human can assign a region later
-- through the existing Venue Master edit screen.

-- `venues_region_name_key` (002_master_data.sql) is `UNIQUE (region_id, lower(name))`
-- - standard SQL unique-constraint semantics treat every NULL as distinct
-- from every other NULL, so that index (and an `ON CONFLICT` naming it)
-- can NEVER actually detect a duplicate among region_id-less rows; verified
-- directly (two inserts of the same NULL-region name both succeeded, giving
-- two venue_ids). A partial unique index scoped to `region_id IS NULL` gives
-- these rows a real conflict target without touching the existing schema.
CREATE UNIQUE INDEX IF NOT EXISTS venues_null_region_name_key
    ON venues (lower(name)) WHERE region_id IS NULL;

INSERT INTO venues (name, region_id, notes) VALUES
    ('PISTA', NULL, 'v0.82 seed: known cross-source venue alias group'),
    ('EN PAZ Tango Studio', NULL, 'v0.82 seed: known cross-source venue alias group'),
    ('Tango Andante', NULL, 'v0.82 seed: known cross-source venue alias group'),
    ('Tango O Nada', NULL, 'v0.82 seed: known cross-source venue alias group'),
    ('OCHO', NULL, 'v0.82 seed: known cross-source venue alias group'),
    ('La Ventana', NULL, 'v0.82 seed: known cross-source venue alias group'),
    ('Amigo Studio', NULL, 'v0.82 seed: known cross-source venue alias group'),
    ('Cafe de Tango', NULL, 'v0.82 seed: known cross-source venue alias group')
ON CONFLICT (lower(name)) WHERE region_id IS NULL DO NOTHING;

-- Aliases: each venue's own canonical name is included as an alias too
-- (matching master_data.create_venue()'s own convention - "the venue's own
-- name is an alias too, so lookup has one code path"), plus every variant
-- named in this release's task. `normalized_alias` mirrors
-- `master_data.normalize_alias()` (NFKC, lowercase, punctuation/space
-- stripped) so lookup at candidate-normalisation time is a plain equality
-- match, exactly like every other venue already in this table.

INSERT INTO venue_aliases (venue_id, alias, normalized_alias)
SELECT v.venue_id, a.alias, a.normalized_alias
FROM venues v
JOIN (VALUES
    ('PISTA', 'PISTA', 'pista'),
    ('PISTA', '피스타', '피스타'),

    ('EN PAZ Tango Studio', 'EN PAZ Tango Studio', 'enpaztangostudio'),
    ('EN PAZ Tango Studio', 'EN PAZ', 'enpaz'),
    ('EN PAZ Tango Studio', 'EnPaz', 'enpaz'),
    ('EN PAZ Tango Studio', '엔빠스', '엔빠스'),
    ('EN PAZ Tango Studio', '탱고 엔빠스 스튜디오', '탱고엔빠스스튜디오'),

    ('Tango Andante', 'Tango Andante', 'tangoandante'),
    ('Tango Andante', 'Andante', 'andante'),
    ('Tango Andante', '탱고 안단테', '탱고안단테'),

    ('Tango O Nada', 'Tango O Nada', 'tangoonada'),
    ('Tango O Nada', 'O Nada', 'onada'),
    ('Tango O Nada', '오나다', '오나다'),
    ('Tango O Nada', '탱고 오나다', '탱고오나다'),

    ('OCHO', 'OCHO', 'ocho'),
    ('OCHO', 'Ocho', 'ocho'),
    ('OCHO', '오초', '오초'),
    ('OCHO', '탱고 클럽 오초', '탱고클럽오초'),

    ('La Ventana', 'La Ventana', 'laventana'),
    ('La Ventana', '라 벤따나', '라벤따나'),

    ('Amigo Studio', 'Amigo Studio', 'amigostudio'),
    ('Amigo Studio', 'Amigo', 'amigo'),
    ('Amigo Studio', '아미고', '아미고'),
    ('Amigo Studio', '아미고스튜디오', '아미고스튜디오'),

    ('Cafe de Tango', 'Cafe de Tango', 'cafedetango'),
    ('Cafe de Tango', 'De Tango', 'detango'),
    ('Cafe de Tango', '데땅고', '데땅고')
) AS a(venue_name, alias, normalized_alias) ON a.venue_name = v.name
WHERE v.notes = 'v0.82 seed: known cross-source venue alias group'
ON CONFLICT (normalized_alias) DO NOTHING;
