"""Venue Master CSV import/export.

Export gives every venue, one row per venue, so an operator can edit it in a
spreadsheet and bring it back. Import never writes on upload — a CSV is
parsed and classified into New / Update / Duplicate-warning / Invalid rows
first (`preview`), and only a `confirm` on that exact preview writes
anything, in one transaction, all-or-nothing if any row is still invalid.

Match policy, in priority order — the same discipline
`venue_resolution.similar_venues()` already keeps, no fuzzy scoring:

    1. an explicit `id` column naming a venue that exists      -> UPDATE
    2. exact normalised name + exact normalised address         -> UPDATE
    3. exact registered alias                                   -> UPDATE
    4. same name, a *different* address                         -> DUPLICATE
       (PISTA/Seoul and PISTA/Busan are not the same venue —
       never auto-merged, always held for a person)
    5. otherwise                                                 -> NEW

`apply_import` is itself idempotent on top of that: a row that matches an
existing venue but changes nothing (the export -> import roundtrip with no
edits) writes nothing and is counted separately from a row that actually
changed a field or added an alias. Existing aliases are never removed by an
import — new ones are added, nothing is replaced.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from . import master_data, master_edit, venue_resolution

ALIAS_SEPARATOR = "|"

EXPORT_COLUMNS = (
    "id", "name", "region_code", "address", "aliases", "notes",
    "active", "created_at", "updated_at",
)
TEMPLATE_COLUMNS = ("name", "region", "address", "aliases", "notes", "active")

# A 4GB board, not a data lake: an unbounded upload could exhaust it before
# a single row is even parsed.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

STATUS_NEW = "NEW"
STATUS_UPDATE = "UPDATE"
STATUS_DUPLICATE = "DUPLICATE"
STATUS_INVALID = "INVALID"

_FALSY = {"false", "0", "no", "n", "off"}


class ImportTooLarge(ValueError):
    """The uploaded file is over MAX_UPLOAD_BYTES."""


class ImportRejected(ValueError):
    """The batch was not written: at least one row is still invalid."""


# --- formula-injection safety ------------------------------------------------

_FORMULA_LEAD = ("=", "+", "-", "@")


def _safe_cell(value: str) -> str:
    """Excel/Sheets reads a leading =/+/-/@ as a formula, not text. A leading
    tab defeats that without changing what the cell displays as."""
    return ("\t" + value) if value and value[0] in _FORMULA_LEAD else value


# --- export -------------------------------------------------------------------

def export_rows(con) -> list[dict[str, Any]]:
    return master_data.list_venues(con)


def to_csv(rows: list[dict[str, Any]]) -> bytes:
    """RFC4180-ish CSV, UTF-8 with a BOM so Excel opens Korean text correctly."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        aliases = ALIAS_SEPARATOR.join(row.get("aliases") or [])
        writer.writerow([
            str(row["venue_id"]),
            _safe_cell(row["name"] or ""),
            _safe_cell(row.get("region_code") or ""),
            _safe_cell(row.get("address") or ""),
            _safe_cell(aliases),
            _safe_cell(row.get("notes") or ""),
            "true" if row["enabled"] else "false",
            row["created_at"].isoformat() if row.get("created_at") else "",
            row["updated_at"].isoformat() if row.get("updated_at") else "",
        ])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def export_filename(*, now: datetime | None = None) -> str:
    when = now or datetime.now(timezone.utc)
    return f"dancemate_venues_{when.strftime('%Y%m%d')}.csv"


def template_csv() -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(TEMPLATE_COLUMNS)
    writer.writerow([
        "La Ventana", "Seoul", "서울 마포구 잔다리로 48",
        "라벤타나|벤타나", "2층", "true",
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


def _resolve_region(
    value: str | None, regions: list[dict[str, Any]]
) -> tuple[int | None, bool]:
    """(region_id, invalid). invalid=True: the CSV named a region that is not
    registered — never auto-created, so the row surfaces it instead."""
    text = (value or "").strip()
    if not text:
        return None, False
    for region in regions:
        if region["code"].lower() == text.lower() or region["name"].lower() == text.lower():
            return region["region_id"], False
    return None, True


def _active(value: str | None) -> bool:
    return (value or "true").strip().lower() not in _FALSY


# --- preview --------------------------------------------------------------------

def preview(con, raw_rows: list[dict[str, str]]) -> dict[str, Any]:
    """Classify every row before anything is written. Never writes."""
    regions = master_data.list_regions(con)
    results: list[dict[str, Any]] = []
    counts = {STATUS_NEW: 0, STATUS_UPDATE: 0, STATUS_DUPLICATE: 0, STATUS_INVALID: 0}

    for index, raw in enumerate(raw_rows, start=1):
        name = (raw.get("name") or "").strip()
        region_text = (raw.get("region") or raw.get("region_code") or "").strip()
        address = (raw.get("address") or "").strip() or None
        aliases = [a.strip() for a in (raw.get("aliases") or "").split(ALIAS_SEPARATOR)
                   if a.strip()]
        notes = (raw.get("notes") or "").strip() or None
        active = _active(raw.get("active") or raw.get("enabled"))
        explicit_id = (raw.get("id") or "").strip()

        entry: dict[str, Any] = {
            "row": index, "name": name, "region": region_text, "address": address,
            "aliases": aliases, "notes": notes, "active": active,
            "region_id": None, "matched_venue_id": None, "reasons": [], "errors": [],
        }

        if not name:
            entry["errors"].append("name is required")

        region_id, invalid_region = _resolve_region(region_text, regions)
        entry["region_id"] = region_id
        if invalid_region:
            entry["errors"].append(f"INVALID_REGION: {region_text!r} is not registered")

        if entry["errors"]:
            entry["status"] = STATUS_INVALID
            counts[STATUS_INVALID] += 1
            results.append(entry)
            continue

        if explicit_id:
            try:
                venue_id = int(explicit_id)
            except ValueError:
                entry["errors"].append(f"id {explicit_id!r} is not a number")
                entry["status"] = STATUS_INVALID
                counts[STATUS_INVALID] += 1
                results.append(entry)
                continue
            existing = master_data.get_venue(con, venue_id)
            if existing is None:
                entry["errors"].append(f"id {venue_id} does not exist")
                entry["status"] = STATUS_INVALID
                counts[STATUS_INVALID] += 1
                results.append(entry)
                continue
            entry["matched_venue_id"] = venue_id
            entry["reasons"] = ["explicit id"]
            entry["status"] = STATUS_UPDATE
            counts[STATUS_UPDATE] += 1
            results.append(entry)
            continue

        candidates = venue_resolution.similar_venues(con, name=name, address=address)
        exact = [c for c in candidates if "same name" in c["match_reasons"]
                 and "same address" in c["match_reasons"]]
        alias_hit = [c for c in candidates
                     if any(r.startswith("registered alias") for r in c["match_reasons"])]
        name_only = [c for c in candidates if "same name" in c["match_reasons"]
                     and "same address" not in c["match_reasons"]]

        if exact:
            entry["matched_venue_id"] = exact[0]["venue_id"]
            entry["reasons"] = exact[0]["match_reasons"]
            entry["status"] = STATUS_UPDATE
        elif alias_hit:
            entry["matched_venue_id"] = alias_hit[0]["venue_id"]
            entry["reasons"] = alias_hit[0]["match_reasons"]
            entry["status"] = STATUS_UPDATE
        elif name_only:
            entry["matched_venue_id"] = name_only[0]["venue_id"]
            entry["reasons"] = name_only[0]["match_reasons"] + ["address differs"]
            entry["status"] = STATUS_DUPLICATE
        else:
            entry["status"] = STATUS_NEW

        counts[entry["status"]] += 1
        results.append(entry)

    return {"rows": results, "counts": counts, "total": len(results)}


# --- apply ----------------------------------------------------------------------

def apply_import(
    con, preview_rows: list[dict[str, Any]], *, reviewer: str, filename: str
) -> dict[str, Any]:
    """Write a previously-previewed batch.

    All-or-nothing: any row still INVALID means nothing is written at all.
    A DUPLICATE row is never auto-applied — it is counted and skipped, the
    same as an operator declining to click it. An UPDATE row that changes
    nothing (the roundtrip case) writes nothing and is counted separately
    from one that did.
    """
    if any(r["status"] == STATUS_INVALID for r in preview_rows):
        raise ImportRejected(
            "at least one row is still INVALID; nothing was imported"
        )

    created = updated = noop = duplicate_skipped = 0
    applied_rows: list[dict[str, Any]] = []

    for entry in preview_rows:
        if entry["status"] == STATUS_DUPLICATE:
            duplicate_skipped += 1
            applied_rows.append({**entry, "applied": "SKIPPED_DUPLICATE"})
            continue

        if entry["status"] == STATUS_NEW:
            venue = master_data.create_venue(
                con, name=entry["name"], region_id=entry["region_id"],
                address=entry["address"], notes=entry["notes"],
                aliases=entry["aliases"],
            )
            if not entry["active"]:
                master_data.update_venue(con, venue["venue_id"], enabled=False)
            master_edit.record(
                con, entity_type=master_edit.VENUE, entity_id=venue["venue_id"],
                action="VENUE_CSV_IMPORT", reviewer=reviewer, entity_name=entry["name"],
                before={},
                after={"name": entry["name"], "region_id": entry["region_id"],
                       "address": entry["address"], "notes": entry["notes"],
                       "enabled": entry["active"]},
                detail=f"created from {filename}, row {entry['row']}",
            )
            created += 1
            applied_rows.append(
                {**entry, "applied": "CREATED", "venue_id": venue["venue_id"]}
            )
            continue

        # STATUS_UPDATE
        venue_id = entry["matched_venue_id"]
        current = master_data.get_venue(con, venue_id)
        changes: dict[str, Any] = {}
        if entry["name"] and entry["name"] != current["name"]:
            changes["name"] = entry["name"]
        if entry["region_id"] is not None and entry["region_id"] != current["region_id"]:
            changes["region_id"] = entry["region_id"]
        if entry["address"] and entry["address"] != current["address"]:
            changes["address"] = entry["address"]
        if entry["notes"] and entry["notes"] != current["notes"]:
            changes["notes"] = entry["notes"]
        if entry["active"] != current["enabled"]:
            changes["enabled"] = entry["active"]

        existing_normalized = {
            master_data.normalize_alias(a["alias"])
            for a in master_data.venue_aliases(con, venue_id)
        }
        new_aliases = [
            a for a in entry["aliases"]
            if master_data.normalize_alias(a) not in existing_normalized
        ]

        if not changes and not new_aliases:
            noop += 1
            applied_rows.append({**entry, "applied": "NOOP", "venue_id": venue_id})
            continue

        before = {k: current.get(k) for k in changes}
        if changes:
            master_data.update_venue(con, venue_id, **changes)
        for alias in new_aliases:
            master_data.add_venue_alias(con, venue_id, alias, ignore_conflict=True)

        detail = f"updated from {filename}, row {entry['row']}"
        if new_aliases:
            detail += f"; aliases added: {', '.join(new_aliases)}"
        master_edit.record(
            con, entity_type=master_edit.VENUE, entity_id=venue_id,
            action="VENUE_CSV_IMPORT", reviewer=reviewer,
            entity_name=entry["name"] or current["name"],
            before=before, after=changes, detail=detail,
        )
        updated += 1
        applied_rows.append({**entry, "applied": "UPDATED", "venue_id": venue_id})

    return {
        "created": created, "updated": updated, "noop": noop,
        "duplicate_skipped": duplicate_skipped, "rows": applied_rows,
    }
