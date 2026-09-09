"""Operator-managed master data: genres, regions, venues, organizers.

Every function takes an open psycopg connection so the caller controls the
transaction. Rows are disabled rather than deleted - an event already
attributed to a venue still has to resolve after the venue stops hosting.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Any

# Venue aliases are matched after normalisation, so "La Ventana", "la  ventana"
# and "라벤타나" each reduce to one comparable key.
_PUNCTUATION = re.compile(r"[^0-9a-z가-힣]+")


def normalize_alias(value: str) -> str:
    """Fold case, width and spacing so an alias compares as one token.

    NFKC first, because Korean text arrives with both composed and half-width
    forms depending on the source.
    """
    folded = unicodedata.normalize("NFKC", value or "").strip().lower()
    return _PUNCTUATION.sub("", folded)


def _rows(cur) -> list[dict[str, Any]]:
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _row(cur) -> dict[str, Any] | None:
    columns = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(columns, row))


# --- genres -----------------------------------------------------------------

def list_genres(
    con, *, enabled_only: bool = False, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM genres"
    if enabled_only:
        sql += " WHERE enabled"
    sql += " ORDER BY code, genre_id"
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params = (limit, offset)
    with con.cursor() as cur:
        cur.execute(sql, params)
        return _rows(cur)


def count_genres(con, *, enabled_only: bool = False) -> int:
    sql = "SELECT count(*) FROM genres"
    if enabled_only:
        sql += " WHERE enabled"
    with con.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def create_genre(con, *, code: str, name: str) -> dict[str, Any]:
    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not code or not name:
        raise ValueError("genre code and name are required")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO genres (code, name) VALUES (%s, %s) RETURNING *",
            (code, name),
        )
        return _row(cur)


def set_genre_enabled(con, genre_id: int, enabled: bool) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute(
            "UPDATE genres SET enabled = %s, updated_at = now() "
            "WHERE genre_id = %s RETURNING *",
            (enabled, genre_id),
        )
        return _row(cur)


def genre_usage(con, genre_id: int) -> dict[str, int]:
    """How many rows in every table with a real FK to `genres` still point
    at this one (v0.86.7 Section 14, 16) - `organizers`, `sources`,
    `events`, `venue_genres`, the full set confirmed by reading every
    migration's own FK clause. None of these FKs carry `ON DELETE CASCADE`
    (Postgres default NO ACTION), so a plain `DELETE FROM genres` is
    already blocked by the database itself when any count here is nonzero -
    this exists to show the operator why, with real numbers, before they
    ever hit that error."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT "
            "  (SELECT count(*) FROM venue_genres WHERE genre_id = %s) AS venues, "
            "  (SELECT count(*) FROM organizers WHERE genre_id = %s) AS organizers, "
            "  (SELECT count(*) FROM sources WHERE genre_id = %s) AS sources, "
            "  (SELECT count(*) FROM events WHERE genre_id = %s) AS events",
            (genre_id, genre_id, genre_id, genre_id),
        )
        cols = [c.name for c in cur.description]
        return dict(zip(cols, cur.fetchone()))


def delete_genre(con, genre_id: int) -> None:
    """The raw delete. Never call directly from a route - `master_edit.
    delete_genre()` is where the reference-count check and the core-genre
    guard live; this is just the SQL, kept here so every other master-data
    write goes through this module the same way."""
    with con.cursor() as cur:
        cur.execute("DELETE FROM genres WHERE genre_id = %s", (genre_id,))


# --- regions ----------------------------------------------------------------

def list_regions(
    con, *, enabled_only: bool = False, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM regions"
    if enabled_only:
        sql += " WHERE enabled"
    sql += " ORDER BY code, region_id"
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params = (limit, offset)
    with con.cursor() as cur:
        cur.execute(sql, params)
        return _rows(cur)


def count_regions(con, *, enabled_only: bool = False) -> int:
    sql = "SELECT count(*) FROM regions"
    if enabled_only:
        sql += " WHERE enabled"
    with con.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def region_usage(con, region_id: int) -> dict[str, int]:
    """The region twin of `genre_usage()` - every real FK to `regions`
    (`venues`, `organizers`, `sources`, `events`; none `ON DELETE CASCADE`)."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT "
            "  (SELECT count(*) FROM venues WHERE region_id = %s) AS venues, "
            "  (SELECT count(*) FROM organizers WHERE region_id = %s) AS organizers, "
            "  (SELECT count(*) FROM sources WHERE region_id = %s) AS sources, "
            "  (SELECT count(*) FROM events WHERE region_id = %s) AS events",
            (region_id, region_id, region_id, region_id),
        )
        cols = [c.name for c in cur.description]
        return dict(zip(cols, cur.fetchone()))


def delete_region(con, region_id: int) -> None:
    """The raw delete - see `delete_genre()`'s own docstring for why the
    check lives in `master_edit`, not here."""
    with con.cursor() as cur:
        cur.execute("DELETE FROM regions WHERE region_id = %s", (region_id,))


def create_region(
    con, *, code: str, country: str, name: str, city: str | None = None,
    district: str | None = None,
) -> dict[str, Any]:
    code = (code or "").strip().upper()
    if not code or not country or not name:
        raise ValueError("region code, country and name are required")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO regions (code, country, city, district, name) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (code, country.strip(), city, district, name.strip()),
        )
        return _row(cur)


# --- venues -----------------------------------------------------------------

def _venue_filter_clause(
    *, region_id: int | None, genre_ids: "Sequence[int] | None"
) -> tuple[str, list[Any]]:
    """v0.86.7 Section 2, 4, 7: region is an exact `v.region_id` match (never
    fuzzy region-name comparison); a genre filter is OR across the given ids
    ("venue supports at least one of these genres") via `EXISTS` against
    `venue_genres`; the two conditions are ANDed together when both are set."""
    conditions: list[str] = []
    params: list[Any] = []
    if region_id is not None:
        conditions.append("v.region_id = %s")
        params.append(region_id)
    if genre_ids:
        conditions.append(
            "EXISTS (SELECT 1 FROM venue_genres vg2 "
            "WHERE vg2.venue_id = v.venue_id AND vg2.genre_id = ANY(%s))"
        )
        params.append(list(genre_ids))
    return " AND ".join(conditions), params


def list_venues(
    con, *, enabled_only: bool = False, region_id: int | None = None,
    genre_ids: "Sequence[int] | None" = None,
    limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    sql = (
        "SELECT v.*, r.name AS region_name, r.code AS region_code, "
        "  COALESCE(a.aliases, ARRAY[]::text[]) AS aliases, "
        "  COALESCE(dg.genre_codes, ARRAY[]::text[]) AS genre_codes "
        "FROM venues v "
        "LEFT JOIN regions r ON r.region_id = v.region_id "
        "LEFT JOIN LATERAL ("
        "  SELECT array_agg(alias ORDER BY alias) AS aliases "
        "  FROM venue_aliases WHERE venue_id = v.venue_id"
        ") a ON TRUE "
        "LEFT JOIN LATERAL ("
        "  SELECT array_agg(g.code ORDER BY g.code) AS genre_codes "
        "  FROM venue_genres vg JOIN genres g ON g.genre_id = vg.genre_id "
        "  WHERE vg.venue_id = v.venue_id"
        ") dg ON TRUE"
    )
    conditions = ["v.enabled"] if enabled_only else []
    params: list[Any] = []
    filter_clause, filter_params = _venue_filter_clause(
        region_id=region_id, genre_ids=genre_ids)
    if filter_clause:
        conditions.append(filter_clause)
        params.extend(filter_params)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY lower(v.name), v.venue_id"
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params += [limit, offset]
    with con.cursor() as cur:
        cur.execute(sql, tuple(params))
        return _rows(cur)


def count_venues(
    con, *, enabled_only: bool = False, region_id: int | None = None,
    genre_ids: "Sequence[int] | None" = None,
) -> int:
    sql = "SELECT count(*) FROM venues v"
    conditions = ["v.enabled"] if enabled_only else []
    params: list[Any] = []
    filter_clause, filter_params = _venue_filter_clause(
        region_id=region_id, genre_ids=genre_ids)
    if filter_clause:
        conditions.append(filter_clause)
        params.extend(filter_params)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    with con.cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchone()[0]


def get_venue(con, venue_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM venues WHERE venue_id = %s", (venue_id,))
        return _row(cur)


def create_venue(
    con, *, name: str, region_id: int | None = None, address: str | None = None,
    notes: str | None = None, aliases: list[str] | None = None,
    latitude: float | None = None, longitude: float | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("venue name is required")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO venues (name, region_id, address, notes, latitude, longitude) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (name, region_id, address, notes, latitude, longitude),
        )
        venue = _row(cur)
    for alias in aliases or []:
        add_venue_alias(con, venue["venue_id"], alias)
    # The venue's own name is an alias too, so lookup has one code path.
    add_venue_alias(con, venue["venue_id"], name, ignore_conflict=True)
    return venue


def update_venue(con, venue_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = ("name", "region_id", "address", "notes", "latitude", "longitude", "enabled")
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "name" in updates:
        # create_venue refuses a blank name; so must an edit, or a venue can be
        # renamed into something no list can show.
        updates["name"] = (updates["name"] or "").strip()
        if not updates["name"]:
            raise ValueError("venue name is required")
    for key in ("address", "notes"):
        if key in updates and isinstance(updates[key], str):
            updates[key] = updates[key].strip() or None
    if not updates:
        return get_venue(con, venue_id)
    assignments = ", ".join(f"{key} = %s" for key in updates)
    with con.cursor() as cur:
        cur.execute(
            f"UPDATE venues SET {assignments}, updated_at = now() "
            "WHERE venue_id = %s RETURNING *",
            (*updates.values(), venue_id),
        )
        return _row(cur)


def backfill_venue_region(con, venue_id: int, region_id: int) -> dict[str, Any]:
    """Give a venue a region it did not have when it was created or linked,
    and carry that region onto the events already resolved to it.

    `update_venue()` alone only touches the `venues` row - `link_unresolved_
    venue()` copies a venue's `region_id` onto its events once, at link time,
    and nothing re-reads the venue afterward. A venue created before its real
    region existed in the master (v0.83.2: Mi Vida tango studio, created
    during v0.83.1's Human Venue Review with `region_id=NULL` because Gwangju
    had no region row yet) would otherwise stay region-less forever even
    after the region is added.

    Scoped deliberately narrow: only events currently at `region_id IS NULL`
    are touched, so a venue already resolved to some other region is never
    silently overwritten by this call.
    """
    with con.transaction():
        venue = update_venue(con, venue_id, region_id=region_id)
        with con.cursor() as cur:
            cur.execute(
                "UPDATE events SET region_id = %s, updated_at = now() "
                "WHERE venue_id = %s AND region_id IS NULL "
                "RETURNING event_id",
                (region_id, venue_id),
            )
            updated_events = [r[0] for r in cur.fetchall()]
    return {"venue": venue, "events_updated": updated_events}


def add_venue_alias(
    con, venue_id: int, alias: str, *, ignore_conflict: bool = False
) -> dict[str, Any] | None:
    alias = (alias or "").strip()
    normalized = normalize_alias(alias)
    if not normalized:
        raise ValueError("alias normalises to nothing")
    conflict = " ON CONFLICT (normalized_alias) DO NOTHING" if ignore_conflict else ""
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO venue_aliases (venue_id, alias, normalized_alias) "
            f"VALUES (%s, %s, %s){conflict} RETURNING *",
            (venue_id, alias, normalized),
        )
        return _row(cur) if cur.description and cur.rowcount else None


def venue_aliases(con, venue_id: int) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM venue_aliases WHERE venue_id = %s ORDER BY alias",
            (venue_id,),
        )
        return _rows(cur)


# --- venue dance genres (v0.85.7) --------------------------------------------
#
# "This venue is known to host Tango" - a fact about the place, confirmed by
# a person (or a future release's own sufficiently-repeated-evidence policy),
# never written just because one event happened to carry that genre. Mirrors
# venue_aliases' own shape exactly: a plain join table, add/remove by pair,
# no soft-disable (a wrong genre is removed, not deactivated).

def venue_genres(con, venue_id: int) -> list[dict[str, Any]]:
    """This venue's confirmed genres, each row carrying the genre's own code
    and name so a caller never has to join genres separately."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT vg.*, g.code AS genre_code, g.name AS genre_name "
            "FROM venue_genres vg JOIN genres g ON g.genre_id = vg.genre_id "
            "WHERE vg.venue_id = %s ORDER BY g.code",
            (venue_id,),
        )
        return _rows(cur)


def add_venue_genre(con, venue_id: int, genre_id: int, *,
                    ignore_conflict: bool = True) -> dict[str, Any] | None:
    """Confirm one genre for a venue. Idempotent by default - re-confirming
    a genre that is already there is a no-op, not an error."""
    conflict = (" ON CONFLICT (venue_id, genre_id) DO NOTHING" if ignore_conflict
               else "")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO venue_genres (venue_id, genre_id) "
            f"VALUES (%s, %s){conflict} RETURNING *",
            (venue_id, genre_id),
        )
        return _row(cur) if cur.description and cur.rowcount else None


def remove_venue_genre(con, venue_id: int, genre_id: int) -> dict[str, Any] | None:
    """Un-confirm one genre for a venue. The venue and its events are
    untouched - this only removes a fact about the place."""
    with con.cursor() as cur:
        cur.execute(
            "DELETE FROM venue_genres WHERE venue_id = %s AND genre_id = %s "
            "RETURNING *",
            (venue_id, genre_id),
        )
        return _row(cur)


def observed_venue_genres(con, venue_id: int) -> list[dict[str, Any]]:
    """Genres actually seen in this venue's own event history - a read-only
    suggestion for a human reviewing the venue, never written on its own
    (Section 17-19 of the v0.85.7 task: observed is not confirmed).
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT g.genre_id, g.code AS genre_code, g.name AS genre_name, "
            "  count(*) AS event_count "
            "FROM events e JOIN genres g ON g.genre_id = e.genre_id "
            "WHERE e.venue_id = %s GROUP BY g.genre_id, g.code, g.name "
            "ORDER BY event_count DESC, g.code",
            (venue_id,),
        )
        return _rows(cur)


def resolve_venue(con, text: str) -> dict[str, Any] | None:
    """Find a venue by any of its aliases. Returns None rather than guessing."""
    normalized = normalize_alias(text)
    if not normalized:
        return None
    with con.cursor() as cur:
        cur.execute(
            "SELECT v.* FROM venue_aliases a "
            "JOIN venues v ON v.venue_id = a.venue_id "
            "WHERE a.normalized_alias = %s",
            (normalized,),
        )
        return _row(cur)


# --- organizers -------------------------------------------------------------

def list_organizers(
    con, *, enabled_only: bool = False, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    sql = (
        "SELECT o.*, g.code AS genre_code, r.name AS region_name "
        "FROM organizers o "
        "LEFT JOIN genres g ON g.genre_id = o.genre_id "
        "LEFT JOIN regions r ON r.region_id = o.region_id"
    )
    if enabled_only:
        sql += " WHERE o.enabled"
    sql += " ORDER BY lower(o.name), o.organizer_id"
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params = (limit, offset)
    with con.cursor() as cur:
        cur.execute(sql, params)
        return _rows(cur)


def count_organizers(con, *, enabled_only: bool = False) -> int:
    sql = "SELECT count(*) FROM organizers"
    if enabled_only:
        sql += " WHERE enabled"
    with con.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def create_organizer(
    con, *, name: str, genre_id: int | None = None, region_id: int | None = None,
    contact_url: str | None = None, notes: str | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("organizer name is required")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO organizers (name, genre_id, region_id, contact_url, notes) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (name, genre_id, region_id, contact_url, notes),
        )
        return _row(cur)


def update_organizer(con, organizer_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = ("name", "genre_id", "region_id", "contact_url", "notes", "enabled")
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "name" in updates:
        updates["name"] = (updates["name"] or "").strip()
        if not updates["name"]:
            raise ValueError("organizer name is required")
    for key in ("contact_url", "notes"):
        if key in updates and isinstance(updates[key], str):
            updates[key] = updates[key].strip() or None
    if not updates:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM organizers WHERE organizer_id = %s", (organizer_id,))
            return _row(cur)
    assignments = ", ".join(f"{key} = %s" for key in updates)
    with con.cursor() as cur:
        cur.execute(
            f"UPDATE organizers SET {assignments}, updated_at = now() "
            "WHERE organizer_id = %s RETURNING *",
            (*updates.values(), organizer_id),
        )
        return _row(cur)


# --- editing what is already registered -------------------------------------
#
# A code is how everything else refers to a row. TANGO is written into sources,
# KR-SEOUL into region filters, and both travel in URLs an operator has
# bookmarked. Renaming one silently breaks every reference, so codes are not
# editable here and the console renders them read-only. Display names are.

def update_genre(con, genre_id: int, **fields: Any) -> dict[str, Any] | None:
    """Change a genre's display name or whether it is offered. Never its code."""
    allowed = ("name", "enabled")
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "name" in updates:
        updates["name"] = (updates["name"] or "").strip()
        if not updates["name"]:
            raise ValueError("genre name is required")
    if not updates:
        return get_genre(con, genre_id)
    assignments = ", ".join(f"{key} = %s" for key in updates)
    with con.cursor() as cur:
        cur.execute(
            f"UPDATE genres SET {assignments}, updated_at = now() "
            "WHERE genre_id = %s RETURNING *",
            (*updates.values(), genre_id),
        )
        return _row(cur)


def get_genre(con, genre_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM genres WHERE genre_id = %s", (genre_id,))
        return _row(cur)


def get_region(con, region_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM regions WHERE region_id = %s", (region_id,))
        return _row(cur)


def update_region(con, region_id: int, **fields: Any) -> dict[str, Any] | None:
    """Change a region's names or whether it is offered. Never its code."""
    allowed = ("name", "country", "city", "district", "enabled")
    updates = {k: v for k, v in fields.items() if k in allowed}
    for key in ("name", "country"):
        if key in updates:
            updates[key] = (updates[key] or "").strip()
            if not updates[key]:
                raise ValueError(f"region {key} is required")
    for key in ("city", "district"):
        if key in updates:
            updates[key] = (updates[key] or "").strip() or None
    if not updates:
        return get_region(con, region_id)
    assignments = ", ".join(f"{key} = %s" for key in updates)
    with con.cursor() as cur:
        cur.execute(
            f"UPDATE regions SET {assignments}, updated_at = now() "
            "WHERE region_id = %s RETURNING *",
            (*updates.values(), region_id),
        )
        return _row(cur)


def get_organizer(con, organizer_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM organizers WHERE organizer_id = %s", (organizer_id,))
        return _row(cur)


def venue_alias_usage(con, venue_id: int) -> dict[int, int]:
    """How many events currently reach this venue through each of its aliases.

    An alias created from a raw post string is doing work: remove it and the
    next collection stops recognising that spelling. The console shows the
    count so a busy alias is not deleted by accident.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT a.venue_alias_id, count(e.event_id) "
            "FROM venue_aliases a "
            "LEFT JOIN events e ON e.venue_id = a.venue_id "
            "  AND lower(e.venue_text) = lower(a.alias) "
            "WHERE a.venue_id = %s GROUP BY a.venue_alias_id",
            (venue_id,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def get_venue_alias(con, venue_alias_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM venue_aliases WHERE venue_alias_id = %s", (venue_alias_id,)
        )
        return _row(cur)


def remove_venue_alias(con, venue_alias_id: int) -> dict[str, Any] | None:
    """Drop one alias. The venue and its events are untouched."""
    with con.cursor() as cur:
        cur.execute(
            "DELETE FROM venue_aliases WHERE venue_alias_id = %s RETURNING *",
            (venue_alias_id,),
        )
        return _row(cur)
