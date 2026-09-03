"""Seed the Source Master from the Information Engine's own source list.

`engine/config/sources.json` is the real, evidence-backed set of sources the
v0.73 PoC was built against. Rather than invent sources, v0.75 imports those
rows into the Source Master so an operator starts with the actual candidates
and decides which to enable.

Every imported source arrives **disabled**. Registering a source is not the
same as pointing a collector at it: an operator tests it, then enables it.

Idempotent — re-running updates nothing that an operator has since changed
except the collector hints, and never re-enables a source.
"""

from __future__ import annotations

import json
from typing import Any

from . import sources as source_master
from .config import Settings

# The engine's authority vocabulary maps onto the Source Master's roles.
ROLE_BY_ENGINE_ROLE = {
    "PRIMARY": "ORGANIZER",
    "PRIMARY_VENUE": "VENUE",
    "PRIMARY_ORGANIZER": "ORGANIZER",
    "SECONDARY": "PROMOTION_BOARD",
    "AGGREGATOR": "AGGREGATOR",
    "COMMUNITY": "COMMUNITY",
    "DIRECTORY": "DIRECTORY",
}

AUTHORITY_BY_ENGINE = {
    "PRIMARY_VENUE": "PRIMARY_VENUE",
    "PRIMARY_ORGANIZER": "PRIMARY_ORGANIZER",
    "SECONDARY": "SECONDARY",
    "AGGREGATOR": "AGGREGATOR",
}

# Genre inference is only done where the engine's own entry states it.
GENRE_BY_KEYWORD = {"TANGO": "TANGO", "SALSA": "SALSA", "SWING": "SWING"}


def _genre_id(genres: list[dict[str, Any]], entry: dict[str, Any]) -> int | None:
    declared = (entry.get("genre") or "").upper()
    code = GENRE_BY_KEYWORD.get(declared)
    if not code:
        return None
    for genre in genres:
        if genre["code"] == code:
            return genre["genre_id"]
    return None


def _region_id(regions: list[dict[str, Any]], entry: dict[str, Any]) -> int | None:
    declared = entry.get("region") or ""
    if declared in ("서울", "Seoul", "SEOUL"):
        for region in regions:
            if region["code"] == "KR-SEOUL":
                return region["region_id"]
    return None


def load_engine_sources(settings: Settings) -> list[dict[str, Any]]:
    path = settings.engine_root / "config" / "sources.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def seed(con, settings: Settings) -> dict[str, Any]:
    """Import the engine's sources as disabled Source Master rows."""
    from . import master_data  # noqa: PLC0415 - avoids an import cycle at module load

    entries = load_engine_sources(settings)
    genres = master_data.list_genres(con)
    regions = master_data.list_regions(con)

    created: list[str] = []
    skipped: list[str] = []
    unsupported: list[str] = []
    rejected: list[str] = []

    for entry in entries:
        key = entry.get("source_id")
        if not key:
            continue
        if source_master.get_source_by_key(con, key) is not None:
            skipped.append(key)
            continue

        platform = entry.get("platform", "WEB")
        if platform not in source_master.PLATFORMS:
            unsupported.append(f"{key}:{platform}")
            continue

        engine_role = entry.get("source_role") or entry.get("authority_level") or "SECONDARY"
        config = {
            k: entry[k]
            for k in ("cafe_name_hint", "url_contains", "access_state")
            if k in entry
        }
        try:
            source_master.create_source(
                con,
                source_key=key,
                name=entry.get("name") or key,
                platform=platform,
                source_role=ROLE_BY_ENGINE_ROLE.get(engine_role, "COMMUNITY"),
                url=entry.get("url"),
                genre_id=_genre_id(genres, entry),
                region_id=_region_id(regions, entry),
                authority_level=AUTHORITY_BY_ENGINE.get(
                    entry.get("authority_level", ""), "UNKNOWN"
                ),
                queries=entry.get("queries") or [],
                config=config,
                # Always disabled: an operator decides what gets collected.
                enabled=False,
                collection_interval_minutes=60,
                notes="imported from engine/config/sources.json",
            )
        except source_master.SourceValidationError as exc:
            # One unusable entry must not stop the rest of the import.
            rejected.append(f"{key}: {exc}")
            continue
        created.append(key)

    return {
        "created": created,
        "already_present": skipped,
        "unsupported_platform": unsupported,
        "rejected": rejected,
        "total_in_engine_config": len(entries),
    }
