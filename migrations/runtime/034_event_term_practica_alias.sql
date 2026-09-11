-- DanceMate v0.87.0 - 쁘락: the scene's own short word for a practica.
--
-- v0.87.0 shows an event's kind as the word its title actually uses - "목요
-- 쁘락" reads 쁘락, not a generic label - and settles that kind only when the
-- title's words agree. "쁘락" is the everyday short form of 쁘락띠까 in
-- Korean tango posts (the engine's own built-in detection has always read
-- "쁘락" as a tango social), and it is the one new term this release's
-- requirements define: 쁘락 -> PRACTICA. Nothing else is seeded.
--
-- A term is matched literally (runtime.event_terms): as a Korean term it may
-- sit inside a longer run, and where it overlaps a longer registered term -
-- 쁘락띠까 - the longer one wins, so existing 쁘락띠까 titles resolve exactly
-- as before.
--
-- Idempotent and non-destructive: an operator who already added 쁘락 for
-- TANGO in Settings keeps their own row and its formats untouched.

INSERT INTO event_terms (genre_id, term, normalized_term)
SELECT g.genre_id, '쁘락', '쁘락'
FROM genres g
WHERE g.code = 'TANGO'
ON CONFLICT (genre_id, normalized_term) DO NOTHING;

INSERT INTO event_term_formats (event_term_id, event_format)
SELECT t.event_term_id, 'PRACTICA'
FROM event_terms t
JOIN genres g ON g.genre_id = t.genre_id AND g.code = 'TANGO'
WHERE t.normalized_term = '쁘락'
  AND NOT EXISTS (SELECT 1 FROM event_term_formats f WHERE f.event_term_id = t.event_term_id)
ON CONFLICT (event_term_id, event_format) DO NOTHING;
