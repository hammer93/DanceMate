-- DanceMate v0.86.8 - clear the v0.82 alias-seed's own bookkeeping note off
-- the venues it created.
--
-- 022_tango_venue_aliases.sql writes a fixed string into `venues.notes` for
-- every venue it has to create:
--
--     'v0.82 seed: known cross-source venue alias group'
--
-- That is a note about the migration, not about the venue. It is the first
-- thing an operator sees in the Venue editor's Notes field for eight real
-- studios (PISTA, EN PAZ, Tango Andante, Tango O Nada, OCHO, La Ventana,
-- Amigo Studio, Cafe de Tango), and it reads as if someone had written it
-- about the place.
--
-- Why a new migration rather than editing 022: `runtime/migrate.py` records
-- a sha256 of every applied migration and reports `checksum_drift` (exit 1
-- from `python -m runtime.migrate`) when a file that has already run
-- changes. Migrations here are forward-only - 031 extended 014's CHECK
-- constraint rather than editing it, for the same reason. Running after 022
-- also means a *fresh* database ends up with the same result as an existing
-- one: the note is gone by the time the chain finishes.
--
-- Scope: an exact, whole-value equality match on the one string this
-- repository generates. No LIKE, no pattern, no "clear the notes column" -
-- an operator's own note on one of these venues says something else and is
-- left exactly as it is. Idempotent: a second run matches nothing.

UPDATE venues
   SET notes = NULL,
       updated_at = now()
 WHERE notes = 'v0.82 seed: known cross-source venue alias group';
