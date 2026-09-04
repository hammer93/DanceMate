-- v0.81.1: Venue Master CSV import gets its own audit action.
--
-- master_data_actions.action's CHECK enumerated exactly ('EDIT','ENABLE',
-- 'DISABLE','ALIAS_ADD','ALIAS_REMOVE') -- none of which is a bulk create or
-- update from a spreadsheet. A CSV import that recorded 'EDIT' for every row
-- it created would misreport an import as a series of edits to rows that
-- never existed a moment before; a new value here is the honest label.
--
-- Same drop/re-add shape as 013's extension of venue_resolution_actions'
-- own action check.

ALTER TABLE master_data_actions
    DROP CONSTRAINT IF EXISTS master_data_actions_action_check;
ALTER TABLE master_data_actions
    ADD CONSTRAINT master_data_actions_action_check
    CHECK (action IN (
        'EDIT', 'ENABLE', 'DISABLE', 'ALIAS_ADD', 'ALIAS_REMOVE',
        -- One row of a Venue Master CSV import, created or updated.
        'VENUE_CSV_IMPORT'
    ));
