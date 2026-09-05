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
-- with no code change.
--
-- Each group is handled as "does ANY spelling in this group already resolve
-- to a real venue? If so, add only the missing spellings to THAT venue - do
-- not create a second, competing venue for a place already registered."
-- This matters concretely on this project's own board: real usage had
-- already registered "아미고스튜디오"/"아미고"/"엔빠스"/"데땅고" as their own
-- venues (venue_id 180/184/185) before this migration was written. A naive
-- "always insert my own canonical English name" seed would have created a
-- second, orphaned venue for the same real place under a name nobody's
-- actual post ever wrote - defeating the whole point of the seed. Found by
-- running the dedup integration tests directly against the real board data
-- (rolled back, never committed) before writing this version.
--
-- region_id is left NULL for every *newly created* venue here on purpose:
-- the discovery report's own city attributions for these names were not all
-- consistent across sources (docs/TANGO_SOURCE_DISCOVERY.md Section 14), and
-- a wrong region asserted here would be worse than an unset one - dedup
-- itself does not depend on region_id, only on venue_id + date + start_time.
-- A human can assign a region later through the existing Venue Master edit
-- screen. An already-existing venue this migration attaches aliases to
-- keeps whatever region_id it already had.
--
-- `venues_region_name_key` (002_master_data.sql) is `UNIQUE (region_id, lower(name))`
-- - standard SQL unique-constraint semantics treat every NULL as distinct
-- from every other NULL, so that index can never actually detect a
-- duplicate among region_id-less rows (verified directly: two inserts of the
-- same NULL-region name both succeeded). This partial index gives those rows
-- a real conflict target without touching the existing schema.
CREATE UNIQUE INDEX IF NOT EXISTS venues_null_region_name_key
    ON venues (lower(name)) WHERE region_id IS NULL;

DO $$
DECLARE
    -- One row per known cross-source venue group: the name to register if
    -- no existing venue is found under any of these spellings, and every
    -- (alias, normalized_alias) pair to ensure once a target venue_id is
    -- known (matching `master_data.normalize_alias()`'s own NFKC/lower/
    -- punctuation-strip rule, so runtime lookup is a plain equality match).
    groups CONSTANT jsonb := '[
        {"canonical": "PISTA", "aliases": [
            ["PISTA", "pista"], ["피스타", "피스타"]
        ]},
        {"canonical": "EN PAZ Tango Studio", "aliases": [
            ["EN PAZ Tango Studio", "enpaztangostudio"], ["EN PAZ", "enpaz"],
            ["EnPaz", "enpaz"], ["엔빠스", "엔빠스"],
            ["탱고 엔빠스 스튜디오", "탱고엔빠스스튜디오"]
        ]},
        {"canonical": "Tango Andante", "aliases": [
            ["Tango Andante", "tangoandante"], ["Andante", "andante"],
            ["탱고 안단테", "탱고안단테"]
        ]},
        {"canonical": "Tango O Nada", "aliases": [
            ["Tango O Nada", "tangoonada"], ["O Nada", "onada"],
            ["오나다", "오나다"], ["탱고 오나다", "탱고오나다"]
        ]},
        {"canonical": "OCHO", "aliases": [
            ["OCHO", "ocho"], ["Ocho", "ocho"], ["오초", "오초"],
            ["탱고 클럽 오초", "탱고클럽오초"]
        ]},
        {"canonical": "La Ventana", "aliases": [
            ["La Ventana", "laventana"], ["라 벤따나", "라벤따나"]
        ]},
        {"canonical": "Amigo Studio", "aliases": [
            ["Amigo Studio", "amigostudio"], ["Amigo", "amigo"],
            ["아미고", "아미고"], ["아미고스튜디오", "아미고스튜디오"]
        ]},
        {"canonical": "Cafe de Tango", "aliases": [
            ["Cafe de Tango", "cafedetango"], ["De Tango", "detango"],
            ["데땅고", "데땅고"]
        ]}
    ]'::jsonb;
    grp jsonb;
    alias_pair jsonb;
    target_venue_id BIGINT;
BEGIN
    FOR grp IN SELECT * FROM jsonb_array_elements(groups)
    LOOP
        -- Does any spelling in this group already resolve to a real venue?
        SELECT v.venue_id INTO target_venue_id
        FROM venue_aliases va
        JOIN venues v ON v.venue_id = va.venue_id
        WHERE va.normalized_alias IN (
            SELECT (a->>1) FROM jsonb_array_elements(grp->'aliases') AS a
        )
        LIMIT 1;

        IF target_venue_id IS NULL THEN
            INSERT INTO venues (name, region_id, notes)
            VALUES (
                grp->>'canonical', NULL,
                'v0.82 seed: known cross-source venue alias group'
            )
            ON CONFLICT (lower(name)) WHERE region_id IS NULL DO NOTHING
            RETURNING venue_id INTO target_venue_id;

            IF target_venue_id IS NULL THEN
                -- A concurrent/earlier run of this same migration already
                -- created it (ON CONFLICT above hit) - look it up rather
                -- than proceed with a NULL venue_id.
                SELECT venue_id INTO target_venue_id
                FROM venues WHERE region_id IS NULL AND lower(name) = lower(grp->>'canonical');
            END IF;
        END IF;

        FOR alias_pair IN SELECT * FROM jsonb_array_elements(grp->'aliases')
        LOOP
            INSERT INTO venue_aliases (venue_id, alias, normalized_alias)
            VALUES (target_venue_id, alias_pair->>0, alias_pair->>1)
            ON CONFLICT (normalized_alias) DO NOTHING;
        END LOOP;
    END LOOP;
END $$;
