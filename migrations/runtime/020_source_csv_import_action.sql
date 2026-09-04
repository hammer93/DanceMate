-- Source Master CSV import gets its own audit action.
--
-- Same reasoning as 018's VENUE_CSV_IMPORT: master_data_actions.action's
-- CHECK enumerated 'EDIT'/'ENABLE'/'DISABLE'/'ALIAS_ADD'/'ALIAS_REMOVE'/
-- 'VENUE_CSV_IMPORT' -- none of which is a bulk create or update of a
-- Source from a spreadsheet. Recording 'EDIT' for a row the import just
-- created would misreport it as an edit to something that did not exist a
-- moment before.

ALTER TABLE master_data_actions
    DROP CONSTRAINT IF EXISTS master_data_actions_action_check;
ALTER TABLE master_data_actions
    ADD CONSTRAINT master_data_actions_action_check
    CHECK (action IN (
        'EDIT', 'ENABLE', 'DISABLE', 'ALIAS_ADD', 'ALIAS_REMOVE',
        'VENUE_CSV_IMPORT',
        -- One row of a Source Master CSV import, created or updated.
        'SOURCE_CSV_IMPORT'
    ));
