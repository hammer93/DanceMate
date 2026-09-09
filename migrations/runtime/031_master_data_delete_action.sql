-- DanceMate v0.86.7 - Admin Venue Filters + Genre/Region Management.
--
-- runtime.master_edit.delete_genre()/delete_region() record their own
-- audit-trail entry through the same master_data_actions table every other
-- master-data edit already uses (Section 22) - but action's CHECK
-- constraint (014_master_data_actions.sql, last extended by
-- 028_venue_genres.sql) never knew about a genre/region actually being
-- deleted, only edited/enabled/disabled/aliased/imported/genre-tagged.
-- Caught by this release's own staging test run before merge: every call
-- to delete_genre()/delete_region() raised a CheckViolation, not the
-- intended EditError.
--
-- Same drop-and-recreate shape 018/020/028 already used for this exact
-- constraint - Postgres has no ALTER CONSTRAINT ... ADD VALUE for a plain
-- CHECK the way it does for a native enum type.

ALTER TABLE master_data_actions
    DROP CONSTRAINT IF EXISTS master_data_actions_action_check;
ALTER TABLE master_data_actions
    ADD CONSTRAINT master_data_actions_action_check
    CHECK (action IN (
        'EDIT', 'ENABLE', 'DISABLE', 'ALIAS_ADD', 'ALIAS_REMOVE',
        'VENUE_CSV_IMPORT', 'SOURCE_CSV_IMPORT',
        'GENRE_ADD', 'GENRE_REMOVE',
        -- A genre or region actually removed, not merely disabled -
        -- only ever recorded when master_edit.delete_genre()/delete_region()
        -- found zero references and the row was really deleted (v0.86.7).
        'DELETE'
    ));
