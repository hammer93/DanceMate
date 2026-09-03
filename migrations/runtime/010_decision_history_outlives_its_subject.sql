-- v0.77: a duplicate verdict records the id it named, forever.
--
-- 009 made event_duplicate_decisions.canonical_event_id ON DELETE SET NULL so
-- a pruned event could be removed. That collides with the table's own rule
-- that a DUPLICATE verdict must say what it duplicates -- and the rule is
-- right. Nulling the id would turn "merged into #223" into "merged into
-- nothing", which is not what happened.
--
-- So the column stops being a foreign key. It is a historical record of an id,
-- not a live link, and history does not need its subject to still exist.

ALTER TABLE event_duplicate_decisions
    DROP CONSTRAINT IF EXISTS event_duplicate_decisions_canonical_event_id_fkey;
