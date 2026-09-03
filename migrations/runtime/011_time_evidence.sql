-- v0.77: carry the engine's meridiem evidence through to the reader.
--
-- Engine v0.74 refuses to turn "5시30분" into 17:30, because the post gives no
-- PM/오후 marker and a dance event is not evidence of one. It records the
-- reading as written, marked ABSENT.
--
-- That was the right call inside the engine and the wrong thing to then show a
-- dancer as "05:30", flat, next to times we do know. So the evidence travels
-- with the value and the alpha surface marks the difference: EXPLICIT the post
-- said which half of the day, ABSENT it did not.

ALTER TABLE events ADD COLUMN IF NOT EXISTS time_evidence TEXT;

COMMENT ON COLUMN events.time_evidence IS
    'EXPLICIT when the post carried a PM/오후 marker for this time, ABSENT when '
    'the clock was written with no half-of-day evidence, NULL when no time was '
    'extracted at all.';
