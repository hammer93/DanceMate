"""Source Master CSV import/export.

Mirrors venue_csv.py's shape: export gives every source, one row per source,
so an operator can review/edit sources in a spreadsheet and bring them back.
Import never writes on upload -- a CSV is parsed and classified into
New / Update / Invalid rows first (`preview`), and only a `confirm` on that
exact preview writes anything, in one transaction, all-or-nothing if any row
is still invalid.

Match policy, in priority order:

    1. an explicit `id` column naming a source that exists   -> UPDATE
    2. exact `source_key`                                     -> UPDATE
       (source_key is this table's own stable business key --
       the engine's own config/sources.json keys off the same value)
    3. otherwise                                               -> NEW

No fuzzy/duplicate tier: unlike a venue, a source is never matched by name --
two sources can legitimately share a name (a "K-TANGO" board and a "K-TANGO"
Naver cafe are different sources), so only an explicit id or source_key ever
matches an existing row.

Enabling a source through import re-validates with the same collection
rules `sources.set_enabled()` already enforces -- a row that turns a source
on without the queries/url it needs is rejected as INVALID here, not
silently written broken and then failing on every scheduler tick.

Nothing in the `sources` table is a credential. API keys and secrets live
only in `.env` and are never read by this module, so export carries no
secret-leak risk by construction.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from . import master_edit, sources

QUERY_SEPARATOR = "|"

EXPORT_COLUMNS = (
    "id", "source_key", "name", "platform", "source_role", "authority_level",
    "genre_code", "region_name", "url", "queries", "collection_interval_minutes",
    "enabled", "notes", "last_status", "last_collected_at", "created_at", "updated_at",
)
TEMPLATE_COLUMNS = (
    "source_key", "name", "platform", "source_role", "authority_level",
    "genre", "region", "url", "queries", "collection_interval_minutes",
    "enabled", "notes",
)

# A 4GB board, not a data lake: an unbounded upload could exhaust it before a
# single row is even parsed.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

STATUS_NEW = "NEW"
STATUS_UPDATE = "UPDATE"
STATUS_INVALID = "INVALID"

_FALSY = {"false", "0", "no", "n", "off"}


class ImportTooLarge(ValueError):
    """The uploaded file is over MAX_UPLOAD_BYTES."""


class ImportRejected(ValueError):
    """The batch was not written: at least one row is still invalid."""


# --- formula-injection safety -------------------------------------------------

_FORMULA_LEAD = ("=", "+", "-", "@")


def _safe_cell(value: str) -> str:
    """Excel/Sheets reads a leading =/+/-/@ as a formula, not text. A leading
    tab defeats that without changing what the cell displays as."""
    return ("\t" + value) if value and value[0] in _FORMULA_LEAD else value


def _queries_of(row: dict[str, Any]) -> list[str]:
    queries = row.get("queries") or []
    if isinstance(queries, str):
        try:
            queries = json.loads(queries)
        except (TypeError, ValueError):
            queries = []
    return [str(q) for q in queries]


# --- export --------------------------------------------------------------------

def export_rows(con) -> list[dict[str, Any]]:
    return sources.list_sources(con)


def to_csv(rows: list[dict[str, Any]]) -> bytes:
    """RFC4180-ish CSV, UTF-8 with a BOM so Excel opens Korean text correctly."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow([
            str(row["source_id"]),
            _safe_cell(row["source_key"] or ""),
            _safe_cell(row["name"] or ""),
            row["platform"],
            row["source_role"],
            row["authority_level"],
            _safe_cell(row.get("genre_code") or ""),
            _safe_cell(row.get("region_name") or ""),
            _safe_cell(row.get("url") or ""),
            _safe_cell(QUERY_SEPARATOR.join(_queries_of(row))),
            str(row["collection_interval_minutes"]),
            "true" if row["enabled"] else "false",
            _safe_cell(row.get("notes") or ""),
            row.get("last_status") or "",
            row["last_collected_at"].isoformat() if row.get("last_collected_at") else "",
            row["created_at"].isoformat() if row.get("created_at") else "",
            row["updated_at"].isoformat() if row.get("updated_at") else "",
        ])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def export_filename(*, now: datetime | None = None) -> str:
    when = now or datetime.now(timezone.utc)
    return f"dancemate_sources_{when.strftime('%Y%m%d')}.csv"


def template_csv() -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(TEMPLATE_COLUMNS)
    writer.writerow([
        "SRC-W-010", "Seoul Tango Community", "WEB", "COMMUNITY", "SECONDARY",
        "TANGO", "Seoul", "https://example-tango-board.test/notice",
        "", "240", "false", "서울 밀롱가 공지용",
    ])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


# --- parsing --------------------------------------------------------------------

def parse_csv(raw: bytes) -> list[dict[str, str]]:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImportTooLarge(
            f"CSV is {len(raw)} bytes, over the {MAX_UPLOAD_BYTES}-byte limit"
        )
    text = raw.decode("utf-8-sig")  # tolerates a BOM, ours or Excel's
    return list(csv.DictReader(io.StringIO(text)))


def _resolve_lookup(
    value: str | None, options: list[dict[str, Any]], *, id_key: str, code_key: str = "code",
) -> tuple[int | None, bool]:
    """(row_id, invalid). invalid=True: the CSV named a genre/region that is
    not registered -- never auto-created, so the row surfaces it instead."""
    text = (value or "").strip()
    if not text:
        return None, False
    for option in options:
        if (option.get(code_key) or "").lower() == text.lower() \
                or (option.get("name") or "").lower() == text.lower():
            return option[id_key], False
    return None, True


def _bool_field(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in _FALSY


# --- preview ---------------------------------------------------------------------

def preview(con, raw_rows: list[dict[str, str]], *, genres: list[dict[str, Any]],
           regions: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify every row before anything is written. Never writes."""
    results: list[dict[str, Any]] = []
    counts = {STATUS_NEW: 0, STATUS_UPDATE: 0, STATUS_INVALID: 0}

    for index, raw in enumerate(raw_rows, start=1):
        source_key = (raw.get("source_key") or "").strip()
        name = (raw.get("name") or "").strip()
        platform = (raw.get("platform") or "").strip().upper()
        source_role = (raw.get("source_role") or "").strip().upper()
        authority_level = (raw.get("authority_level") or "UNKNOWN").strip().upper()
        genre_text = (raw.get("genre") or raw.get("genre_code") or "").strip()
        region_text = (raw.get("region") or raw.get("region_name") or "").strip()
        url = (raw.get("url") or "").strip() or None
        queries = [q.strip() for q in (raw.get("queries") or "").split(QUERY_SEPARATOR)
                   if q.strip()]
        notes = (raw.get("notes") or "").strip() or None
        explicit_id = (raw.get("id") or "").strip()

        interval_raw = (raw.get("collection_interval_minutes") or "").strip()
        try:
            interval = int(interval_raw) if interval_raw else sources.DEFAULT_INTERVAL_MINUTES
        except ValueError:
            interval = None

        entry: dict[str, Any] = {
            "row": index, "source_key": source_key, "name": name, "platform": platform,
            "source_role": source_role, "authority_level": authority_level,
            "genre": genre_text, "region": region_text, "url": url, "queries": queries,
            "collection_interval_minutes": interval, "notes": notes,
            "genre_id": None, "region_id": None,
            "matched_source_id": None, "reasons": [], "errors": [],
        }

        enabled_col = raw.get("enabled") if raw.get("enabled") is not None else raw.get("active")
        existing_for_default = None
        if explicit_id.isdigit():
            existing_for_default = sources.get_source(con, int(explicit_id))
        elif source_key:
            existing_for_default = sources.get_source_by_key(con, source_key)
        default_enabled = bool(existing_for_default["enabled"]) if existing_for_default else False
        entry["enabled"] = _bool_field(enabled_col, default=default_enabled)

        if interval is None:
            entry["errors"].append(
                f"collection_interval_minutes {interval_raw!r} is not a number"
            )

        genre_id, invalid_genre = _resolve_lookup(genre_text, genres, id_key="genre_id")
        entry["genre_id"] = genre_id
        if invalid_genre:
            entry["errors"].append(f"INVALID_GENRE: {genre_text!r} is not registered")

        region_id, invalid_region = _resolve_lookup(region_text, regions, id_key="region_id")
        entry["region_id"] = region_id
        if invalid_region:
            entry["errors"].append(f"INVALID_REGION: {region_text!r} is not registered")

        # Which existing row this CSV row refers to, before validation --
        # update_source()/create_source() need to know NEW vs UPDATE to pick
        # the right name/platform/role defaults for a row that leaves those
        # columns blank on an UPDATE.
        matched = None
        if explicit_id:
            if not explicit_id.isdigit():
                entry["errors"].append(f"id {explicit_id!r} is not a number")
            else:
                matched = sources.get_source(con, int(explicit_id))
                if matched is None:
                    entry["errors"].append(f"id {explicit_id} does not exist")
        elif source_key:
            matched = sources.get_source_by_key(con, source_key)

        if matched is not None:
            entry["matched_source_id"] = matched["source_id"]
            entry["reasons"] = ["explicit id"] if explicit_id else ["source_key"]

        effective_name = name or (matched["name"] if matched else "")
        effective_platform = platform or (matched["platform"] if matched else "")
        effective_role = source_role or (matched["source_role"] if matched else "")
        effective_authority = authority_level or (
            matched["authority_level"] if matched else "UNKNOWN")
        effective_url = url if url is not None else (matched.get("url") if matched else None)
        effective_queries = queries or (
            [str(q) for q in (matched.get("queries") or [])] if matched else [])

        if not source_key:
            entry["errors"].append("source_key is required")
        if not effective_name:
            entry["errors"].append("name is required")

        if not entry["errors"]:
            try:
                sources.validate(
                    source_key=source_key, name=effective_name, platform=effective_platform,
                    source_role=effective_role, url=effective_url,
                    authority_level=effective_authority,
                    collection_interval_minutes=interval, queries=effective_queries,
                    for_collection=entry["enabled"],
                )
            except sources.SourceValidationError as exc:
                entry["errors"].append(str(exc))

        if entry["errors"]:
            entry["status"] = STATUS_INVALID
            counts[STATUS_INVALID] += 1
            results.append(entry)
            continue

        if matched is not None:
            entry["status"] = STATUS_UPDATE
        else:
            entry["status"] = STATUS_NEW
        counts[entry["status"]] += 1
        results.append(entry)

    return {"rows": results, "counts": counts, "total": len(results)}


# --- apply -----------------------------------------------------------------------

def apply_import(
    con, preview_rows: list[dict[str, Any]], *, reviewer: str, filename: str
) -> dict[str, Any]:
    """Write a previously-previewed batch.

    All-or-nothing: any row still INVALID means nothing is written at all. A
    row that matches an existing source but changes nothing (the export ->
    import roundtrip with no edits) writes nothing and is counted separately
    from one that actually changed a field.
    """
    if any(r["status"] == STATUS_INVALID for r in preview_rows):
        raise ImportRejected(
            "at least one row is still INVALID; nothing was imported"
        )

    created = updated = noop = 0
    applied_rows: list[dict[str, Any]] = []

    for entry in preview_rows:
        if entry["status"] == STATUS_NEW:
            source = sources.create_source(
                con, source_key=entry["source_key"], name=entry["name"],
                platform=entry["platform"], source_role=entry["source_role"],
                url=entry["url"], genre_id=entry["genre_id"], region_id=entry["region_id"],
                authority_level=entry["authority_level"], queries=entry["queries"],
                enabled=entry["enabled"],
                collection_interval_minutes=entry["collection_interval_minutes"],
                notes=entry["notes"],
            )
            master_edit.record(
                con, entity_type=master_edit.SOURCE, entity_id=source["source_id"],
                action="SOURCE_CSV_IMPORT", reviewer=reviewer, entity_name=entry["name"],
                before={},
                after={"source_key": entry["source_key"], "platform": entry["platform"],
                       "source_role": entry["source_role"], "enabled": entry["enabled"]},
                detail=f"created from {filename}, row {entry['row']}",
            )
            created += 1
            applied_rows.append(
                {**entry, "applied": "CREATED", "source_id": source["source_id"]}
            )
            continue

        # STATUS_UPDATE
        source_id = entry["matched_source_id"]
        current = sources.get_source(con, source_id)
        changes: dict[str, Any] = {}
        if entry["name"] and entry["name"] != current["name"]:
            changes["name"] = entry["name"]
        if entry["platform"] and entry["platform"] != current["platform"]:
            changes["platform"] = entry["platform"]
        if entry["source_role"] and entry["source_role"] != current["source_role"]:
            changes["source_role"] = entry["source_role"]
        if entry["authority_level"] and entry["authority_level"] != current["authority_level"]:
            changes["authority_level"] = entry["authority_level"]
        if entry["url"] is not None and entry["url"] != current.get("url"):
            changes["url"] = entry["url"]
        if entry["genre_id"] is not None and entry["genre_id"] != current.get("genre_id"):
            changes["genre_id"] = entry["genre_id"]
        if entry["region_id"] is not None and entry["region_id"] != current.get("region_id"):
            changes["region_id"] = entry["region_id"]
        if (entry["collection_interval_minutes"] is not None
                and entry["collection_interval_minutes"] != current["collection_interval_minutes"]):
            changes["collection_interval_minutes"] = entry["collection_interval_minutes"]
        if entry["notes"] and entry["notes"] != current.get("notes"):
            changes["notes"] = entry["notes"]
        if entry["enabled"] != current["enabled"]:
            changes["enabled"] = entry["enabled"]
        if entry["queries"] and entry["queries"] != _queries_of(current):
            changes["queries"] = entry["queries"]

        if not changes:
            noop += 1
            applied_rows.append({**entry, "applied": "NOOP", "source_id": source_id})
            continue

        before = {k: current.get(k) for k in changes}
        sources.update_source(con, source_id, **changes)
        master_edit.record(
            con, entity_type=master_edit.SOURCE, entity_id=source_id,
            action="SOURCE_CSV_IMPORT", reviewer=reviewer,
            entity_name=entry["name"] or current["name"],
            before=before, after=changes,
            detail=f"updated from {filename}, row {entry['row']}",
        )
        updated += 1
        applied_rows.append({**entry, "applied": "UPDATED", "source_id": source_id})

    return {
        "created": created, "updated": updated, "noop": noop, "rows": applied_rows,
    }
