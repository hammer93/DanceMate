-- DanceMate v0.96.34 - what `events.time_evidence` can say, in full.
--
-- 011_time_evidence.sql described two values and a NULL, because the engine
-- recorded one thing: whether the post carried a PM/오후 marker. It recorded a
-- second thing in the same evidence row all along - `ambiguous`, true only
-- when the written hour could equally be twelve hours later - and nothing read
-- it. So `시간: 14:00~18:00` and a bare `2:00` were stored identically, and
-- the reader showed both as a time nobody had confirmed. Measured before the
-- change: of 711 ABSENT Events, 659 wrote their hour in a notation with one
-- reading, and not one of them started before noon.
--
-- No data is rewritten here and no column changes. The value is produced by
-- `candidates.time_evidence()` for rows the engine re-reads, so the column
-- carries UNAMBIGUOUS as those rows re-normalize; this migration only makes
-- the schema say so.
COMMENT ON COLUMN events.time_evidence IS
    'EXPLICIT when the post carried a PM/오후 marker for this time, '
    'UNAMBIGUOUS when it wrote an hour that has only one reading (14:00), '
    'PROPAGATED when one half of a range was read from the marked other half, '
    'ABSENT when the clock was written with no half-of-day evidence and could '
    'be either, HUMAN when a person corrected it, NULL when no time was '
    'extracted at all.';
