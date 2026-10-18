-- DanceMate v0.96.41 - a festival's last day, when its own record states one.
--
-- An event has always been one day: event_date, and a start and end clock on
-- it (end_day_offset for a night that ends after midnight). A multi-day post
-- kept that shape by storing its first day and recording the span as
-- MULTI_DAY_EVENT evidence (v0.91.0), because there was nowhere else to put it.
--
-- v0.96.41 reads festivals, marathons and tango weeks from the structured
-- calendars that publish them, and Miltang's notices state each one's period
-- outright (JSON-LD startDate and endDate). end_date is that last day, and only
-- that: NULL for every one-day event, and NULL for a festival whose record
-- states when it starts and not when it ends - nothing here infers a span.
--
-- The checks keep it a period: strictly after event_date, and no longer than a
-- month (festival_evidence.MAX_PERIOD_DAYS).
--
-- Nothing existing is rewritten: one nullable column, NULL on every row, and a
-- check every row therefore satisfies. Re-running is a no-op.

ALTER TABLE events
    ADD COLUMN IF NOT EXISTS end_date DATE;

ALTER TABLE events
    DROP CONSTRAINT IF EXISTS events_end_date_is_a_period;
ALTER TABLE events
    ADD CONSTRAINT events_end_date_is_a_period
    CHECK (end_date IS NULL
           OR (end_date > event_date AND end_date <= event_date + 31));
