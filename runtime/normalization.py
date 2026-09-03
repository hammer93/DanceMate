"""Turn engine candidates into event instances a person can search.

The Information Engine produces candidates in its own store. This builds the
runtime's normalised view of them: one row per event on one date, with the
venue resolved against the Venue Master where we recognise it, the human's
corrections overlaid, and a deterministic key that PHASE E's duplicate rules
can compare.

Three things it deliberately does not do:

    It does not write to the engine. The engine store stays the source of
    truth, and ``events`` can be rebuilt from it at any time.

    It does not create venues. A venue string we have read but not recognised
    is UNRESOLVED and goes in a queue for a person. Auto-registering venue
    names is how a typo becomes a permanent master record.

    It does not grant status. The engine's verdict and the human's review sit
    side by side; neither is derived from the other.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, time
from typing import Any

from . import master_data, review

VENUE_RESOLVED = "RESOLVED"
VENUE_UNRESOLVED = "UNRESOLVED"
VENUE_ABSENT = "ABSENT"

LISTED = "LISTED"
HIDDEN = "HIDDEN"

# Event types that are tango events. Anything else gets no genre rather than a
# guessed one -- an empty filter is honest, a wrong one is not.
GENRE_BY_EVENT_TYPE = {
    "MILONGA": "TANGO",
    "PRACTICA": "TANGO",
    "TANGO": "TANGO",
}

# Review outcomes that must never reach the alpha search.
UNLISTABLE_REVIEW_STATES = {"REJECTED", "DUPLICATE"}

_DECORATION = re.compile(r"[^0-9A-Za-z가-힣]+")
# Dates, weekdays and ordinals inside a title: "9/5(토) 더 피스타 밀롱가" and
# "9월 12일 더 피스타 밀롱가" are the same series on different days.
_DATE_IN_NAME = re.compile(
    r"\d{1,4}\s*[./-]\s*\d{1,2}(\s*[./-]\s*\d{1,2})?"
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일?"
    r"|\d{1,4}\s*년"
    r"|[월화수목금토일]요일"
    r"|\(\s*[월화수목금토일]\s*\)"
    r"|\d+\s*(?:번째|째)\s*주"
)


def name_key(name: str | None) -> str:
    """A title reduced to what identifies the event across posts."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name)
    text = _DATE_IN_NAME.sub(" ", text)
    return _DECORATION.sub("", text).lower()


def venue_key(venue_id: int | None, venue_text: str | None) -> str | None:
    """What counts as 'the same place' for comparison.

    A resolved venue compares by id, so two spellings of one studio match. An
    unresolved one compares by its normalised text and only ever matches an
    identical reading -- we have no grounds to call two unknown strings equal.
    """
    if venue_id is not None:
        return f"venue:{venue_id}"
    normalized = master_data.normalize_alias(venue_text or "")
    return f"text:{normalized}" if normalized else None


def identity_key(event_date: Any, venue: str | None, start: Any) -> str:
    """Date, place and start time -- the three things that make an event *this* one."""
    day = event_date.isoformat() if isinstance(event_date, date) else str(event_date or "")
    clock = start.strftime("%H:%M") if isinstance(start, time) else (str(start or "")[:5])
    return f"{day}|{venue or '-'}|{clock or '-'}"


def series_key(venue: str | None, event_date: Any, name: str | None) -> str | None:
    """What groups a weekly milonga's instances without merging them.

    Present only when we know both the place and the name; a series we cannot
    identify is simply not grouped, which costs nothing.
    """
    key = name_key(name)
    if not venue or not key:
        return None
    if not isinstance(event_date, date):
        return None
    return f"{venue}|{event_date.weekday()}|{key}"


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _as_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:5], "%H:%M").time()
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_venue(con, venue_text: str | None,
                  alias_candidates: list[str] | None = None) -> dict[str, Any]:
    """Match an extracted venue string against the Venue Master.

    Tries the whole string first, then the parts the extractor offered -- the
    name without its bracketed address, and the name inside the brackets. All
    of them are exact alias matches; none of them invents a venue.
    """
    if not venue_text:
        return {"venue_id": None, "venue_status": VENUE_ABSENT, "matched_on": None}
    for attempt in [venue_text] + [a for a in (alias_candidates or []) if a != venue_text]:
        found = master_data.resolve_venue(con, attempt)
        if found:
            return {
                "venue_id": found["venue_id"],
                "venue_status": VENUE_RESOLVED,
                "matched_on": attempt,
                "region_id": found.get("region_id"),
            }
    return {"venue_id": None, "venue_status": VENUE_UNRESOLVED, "matched_on": None}


def record_unresolved_venue(con, venue_text: str,
                            alias_candidates: list[str] | None = None) -> dict[str, Any] | None:
    """Queue a venue string nobody has recognised yet. Creates no venue."""
    normalized = master_data.normalize_alias(venue_text)
    if not normalized:
        return None
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO unresolved_venues (venue_text, normalized_text, alias_candidates) "
            "VALUES (%s, %s, %s::jsonb) "
            "ON CONFLICT (normalized_text) DO UPDATE SET "
            "  occurrence_count = unresolved_venues.occurrence_count + 1, "
            "  last_seen_at = now(), "
            "  alias_candidates = EXCLUDED.alias_candidates "
            "RETURNING *",
            (venue_text, normalized,
             json.dumps(alias_candidates or [venue_text], ensure_ascii=False)),
        )
        columns = [c.name for c in cur.description]
        row = cur.fetchone()
    return None if row is None else dict(zip(columns, row))


def _genre_id(con, event_type: str | None) -> int | None:
    code = GENRE_BY_EVENT_TYPE.get((event_type or "").upper())
    if not code:
        return None
    with con.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = %s", (code,))
        row = cur.fetchone()
    return row[0] if row else None


def _region_id(con, venue_id: int | None) -> int | None:
    if venue_id is None:
        return None
    with con.cursor() as cur:
        cur.execute("SELECT region_id FROM venues WHERE venue_id = %s", (venue_id,))
        row = cur.fetchone()
    return row[0] if row else None


def normalize_candidate(con, candidate: dict[str, Any], *,
                        review_state: dict[str, Any] | None = None,
                        alias_candidates: list[str] | None = None) -> dict[str, Any] | None:
    """Write one candidate into ``events``. Returns the stored row.

    A candidate without a date is not an event instance yet -- it is a post we
    could not place on a calendar, and it stays in the review queue rather than
    becoming a row with a made-up day.
    """
    review_state = review_state or {}
    merged = review.apply_corrections(candidate, review_state)

    event_date = _as_date(merged.get("event_date"))
    if event_date is None:
        return None

    start = _as_time(merged.get("start_time"))
    end = _as_time(merged.get("end_time"))
    venue_text = (merged.get("venue") or "").strip() or None

    resolution = resolve_venue(con, venue_text, alias_candidates)
    if resolution["venue_status"] == VENUE_UNRESOLVED:
        record_unresolved_venue(con, venue_text, alias_candidates)

    venue_id = resolution["venue_id"]
    state = (review_state.get("review_state") or review.PENDING).upper()
    listing = HIDDEN if state in UNLISTABLE_REVIEW_STATES else LISTED

    # Which fields a person changed, so the console and the API can say so.
    origin = {field: "HUMAN" for field in (merged.get("corrected_fields") or [])}

    key = venue_key(venue_id, venue_text)
    values = {
        "candidate_id": _as_int(candidate.get("candidate_id")),
        "post_id": _as_int(candidate.get("post_id")),
        "source_item_id": _as_int(candidate.get("source_item_id")),
        "source_url": candidate.get("source_url"),
        "event_name": (merged.get("event_name") or "").strip() or "(untitled)",
        "event_type": candidate.get("event_type"),
        "event_date": event_date,
        "start_time": start,
        "end_time": end,
        "end_day_offset": _as_int(candidate.get("end_day_offset")) or 0,
        "venue_text": venue_text,
        "venue_id": venue_id,
        "venue_status": resolution["venue_status"],
        "fee": _as_int(merged.get("fee")),
        "genre_id": _genre_id(con, candidate.get("event_type")),
        "region_id": _region_id(con, venue_id),
        "engine_status": (candidate.get("candidate_status") or "POSSIBLE").upper(),
        "review_state": state,
        "field_origin": json.dumps(origin, ensure_ascii=False),
        "identity_key": identity_key(event_date, key, start),
        "series_key": series_key(key, event_date, merged.get("event_name")),
        "listing_state": listing,
        "provenance": candidate.get("provenance") or PROVENANCE_UNKNOWN,
    }

    columns = list(values)
    placeholders = ", ".join(
        "%s::jsonb" if c == "field_origin" else "%s" for c in columns
    )
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "candidate_id")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO events (" + ", ".join(columns) + ") "
            "VALUES (" + placeholders + ") "
            "ON CONFLICT (candidate_id) DO UPDATE SET " + updates + ", updated_at = now() "
            "RETURNING *",
            tuple(values[c] for c in columns),
        )
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    return None if row is None else dict(zip(names, row))


def get(con, event_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE event_id = %s", (event_id,))
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    return None if row is None else dict(zip(names, row))


def by_candidate(con, candidate_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE candidate_id = %s", (candidate_id,))
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    return None if row is None else dict(zip(names, row))


def unresolved_venues(con, *, state: str = "OPEN", limit: int = 100) -> list[dict[str, Any]]:
    """The queue of venue strings waiting on a person."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT u.*, "
            "  (SELECT count(*) FROM events e "
            "    WHERE e.venue_status = 'UNRESOLVED' "
            "      AND lower(e.venue_text) = lower(u.venue_text)) AS event_count "
            "FROM unresolved_venues u WHERE u.state = %s "
            "ORDER BY u.occurrence_count DESC, u.last_seen_at DESC LIMIT %s",
            (state, limit),
        )
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def link_unresolved_venue(con, unresolved_venue_id: int, venue_id: int, *,
                          reviewer: str = "admin", add_alias: bool = True) -> dict[str, Any]:
    """A person says this string is that venue.

    Records the string as an alias so the same reading resolves next time, then
    re-resolves the events that were waiting on it. This is the only path from
    an unrecognised string to the Venue Master, and a person is on it.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM unresolved_venues WHERE unresolved_venue_id = %s",
            (unresolved_venue_id,),
        )
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    if row is None:
        raise LookupError("no unresolved venue " + str(unresolved_venue_id))
    entry = dict(zip(names, row))

    if master_data.get_venue(con, venue_id) is None:
        raise LookupError("no venue " + str(venue_id))

    if add_alias:
        try:
            master_data.add_venue_alias(con, venue_id=venue_id, alias=entry["venue_text"])
        except Exception:
            # Already an alias of this venue, or of another one. Either way the
            # link below is what the operator asked for.
            pass

    with con.cursor() as cur:
        cur.execute(
            "UPDATE unresolved_venues SET state = 'LINKED', resolved_venue_id = %s, "
            "  resolved_by = %s, resolved_at = now() WHERE unresolved_venue_id = %s",
            (venue_id, reviewer, unresolved_venue_id),
        )
        cur.execute(
            "UPDATE events SET venue_id = %s, venue_status = 'RESOLVED', "
            "  region_id = (SELECT region_id FROM venues WHERE venue_id = %s), "
            "  updated_at = now() "
            "WHERE venue_status = 'UNRESOLVED' AND lower(venue_text) = lower(%s) "
            "RETURNING event_id",
            (venue_id, venue_id, entry["venue_text"]),
        )
        updated = [r[0] for r in cur.fetchall()]
    # The identity key contains the venue, so it has to be recomputed.
    for event_id in updated:
        _refresh_keys(con, event_id)
    return {"unresolved_venue_id": unresolved_venue_id, "venue_id": venue_id,
            "events_updated": len(updated)}


def dismiss_unresolved_venue(con, unresolved_venue_id: int, *,
                             reviewer: str = "admin") -> None:
    """Not a venue: a room number, a landmark, a mis-read. Left recorded."""
    with con.cursor() as cur:
        cur.execute(
            "UPDATE unresolved_venues SET state = 'DISMISSED', resolved_by = %s, "
            "  resolved_at = now() WHERE unresolved_venue_id = %s",
            (reviewer, unresolved_venue_id),
        )


def _refresh_keys(con, event_id: int) -> None:
    event = get(con, event_id)
    if event is None:
        return
    key = venue_key(event["venue_id"], event["venue_text"])
    with con.cursor() as cur:
        cur.execute(
            "UPDATE events SET identity_key = %s, series_key = %s, updated_at = now() "
            "WHERE event_id = %s",
            (identity_key(event["event_date"], key, event["start_time"]),
             series_key(key, event["event_date"], event["event_name"]), event_id),
        )


# --- provenance -------------------------------------------------------------

PROVENANCE_LIVE = "LIVE"
PROVENANCE_SNAPSHOT = "SNAPSHOT"
PROVENANCE_UNKNOWN = "UNKNOWN"

_PROVENANCE_BY_MODE = {"live": PROVENANCE_LIVE, "snapshot": PROVENANCE_SNAPSHOT}


def source_of(con, source_url: str | None) -> dict[str, Any]:
    """Which collected item a candidate came from, and how it was collected.

    The engine's store keeps the post; the runtime's keeps how we got it. They
    join on the URL. An event we cannot trace back to a live collection is not
    shown to a dancer -- a replayed snapshot is a fine way to test a parser and
    a terrible way to tell someone where to go tonight.
    """
    if not source_url:
        return {"source_item_id": None, "provenance": PROVENANCE_UNKNOWN}
    with con.cursor() as cur:
        cur.execute(
            "SELECT i.source_item_id, r.mode FROM source_items i "
            "LEFT JOIN source_collection_runs r ON r.collection_run_id = i.collection_run_id "
            "WHERE i.url = %s ORDER BY i.source_item_id DESC LIMIT 1",
            (source_url,),
        )
        row = cur.fetchone()
    if row is None:
        return {"source_item_id": None, "provenance": PROVENANCE_UNKNOWN}
    source_item_id, mode = row
    return {
        "source_item_id": source_item_id,
        "provenance": _PROVENANCE_BY_MODE.get((mode or "").lower(), PROVENANCE_UNKNOWN),
    }


def normalize_all(settings, *, limit: int = 500) -> dict[str, Any]:
    """Normalise every engine candidate the runtime can see.

    Idempotent: a candidate already normalised is updated in place, so this can
    run on a schedule, after an ingest, or after a person edits a candidate.
    """
    from . import candidates as candidate_store  # local: engine store is optional
    from . import db

    rows = candidate_store.list_candidates(settings, limit=limit)
    if not rows:
        return {"candidates": 0, "normalized": 0, "skipped_no_date": 0}

    ids = [int(r["candidate_id"]) for r in rows if r.get("candidate_id") is not None]
    aliases = candidate_store.venue_alias_candidates(settings, ids)

    normalized = skipped = 0
    unresolved = 0
    with db.connect(settings, autocommit=True) as con:
        states = review.states(con, ids)
        for row in rows:
            candidate_id = row.get("candidate_id")
            origin = source_of(con, row.get("source_url"))
            enriched = dict(row)
            enriched["source_item_id"] = origin["source_item_id"]
            enriched["provenance"] = origin["provenance"]
            stored = normalize_candidate(
                con, enriched,
                review_state=states.get(candidate_id),
                alias_candidates=aliases.get(candidate_id),
            )
            if stored is None:
                skipped += 1
                continue
            if stored["venue_status"] == VENUE_UNRESOLVED:
                unresolved += 1
            normalized += 1

    return {
        "candidates": len(rows),
        "normalized": normalized,
        "skipped_no_date": skipped,
        "unresolved_venues": unresolved,
    }


def metrics(con) -> dict[str, Any]:
    """Counts for the dashboard and the acceptance report."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS total, "
            "  count(*) FILTER (WHERE provenance = 'LIVE') AS live, "
            "  count(*) FILTER (WHERE listing_state = 'LISTED' "
            "                     AND canonical_event_id IS NULL "
            "                     AND provenance = 'LIVE') AS listed, "
            "  count(*) FILTER (WHERE venue_status = 'RESOLVED') AS venue_resolved, "
            "  count(*) FILTER (WHERE venue_status = 'UNRESOLVED') AS venue_unresolved, "
            "  count(*) FILTER (WHERE start_time IS NOT NULL) AS with_time, "
            "  count(*) FILTER (WHERE fee IS NOT NULL) AS with_fee "
            "FROM events"
        )
        names = [c.name for c in cur.description]
        summary = dict(zip(names, cur.fetchone()))
        cur.execute("SELECT count(*) FROM unresolved_venues WHERE state = 'OPEN'")
        summary["unresolved_venue_queue"] = cur.fetchone()[0]
    return summary
