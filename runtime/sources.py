"""Source Master: what the operator turns on, and what the scheduler collects.

The scheduler only ever touches sources marked `enabled` here, and only when
their interval has elapsed. That is the whole point of this table: adding a
source to the database is not the same as pointing a collector at it.

Platform and role vocabularies deliberately mirror the Information Engine's
own `config/sources.json`, so a Source Master row and an engine source describe
the same thing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

PLATFORMS = (
    "DAUM_CAFE",
    "NAVER_CAFE",
    "NAVER_BLOG",
    "FACEBOOK",
    "WEB",
    "DIRECTORY",
)

SOURCE_ROLES = (
    "COMMUNITY",
    "PROMOTION_BOARD",
    "VENUE",
    "ORGANIZER",
    "DIRECTORY",
    "AGGREGATOR",
)

AUTHORITY_LEVELS = (
    "PRIMARY_VENUE",
    "PRIMARY_ORGANIZER",
    "SECONDARY",
    "AGGREGATOR",
    "UNKNOWN",
)

MIN_INTERVAL_MINUTES = 10
DEFAULT_INTERVAL_MINUTES = 60


class SourceValidationError(ValueError):
    """Raised for a source definition the operator has to fix."""


def _rows(cur) -> list[dict[str, Any]]:
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _row(cur) -> dict[str, Any] | None:
    columns = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(columns, row))


def validate(
    *, source_key: str, name: str, platform: str, source_role: str,
    url: str | None, authority_level: str, collection_interval_minutes: int,
    queries: list[str], for_collection: bool = False,
) -> None:
    """Reject a source definition before it reaches the database.

    ``for_collection`` adds the rules that only matter once something will
    actually fetch from this source. A disabled source is a draft: it may be
    registered before its search queries are decided, and the engine's own
    config/sources.json contains exactly such entries. Enabling one is what
    requires it to be collectable.
    """
    problems: list[str] = []
    if not (source_key or "").strip():
        problems.append("source_key is required")
    if not (name or "").strip():
        problems.append("name is required")
    if platform not in PLATFORMS:
        problems.append(f"platform must be one of {', '.join(PLATFORMS)}")
    if source_role not in SOURCE_ROLES:
        problems.append(f"source_role must be one of {', '.join(SOURCE_ROLES)}")
    if authority_level not in AUTHORITY_LEVELS:
        problems.append(f"authority_level must be one of {', '.join(AUTHORITY_LEVELS)}")
    if collection_interval_minutes < MIN_INTERVAL_MINUTES:
        problems.append(
            f"collection_interval_minutes must be at least {MIN_INTERVAL_MINUTES} "
            "- faster polling wears the microSD and hammers the upstream"
        )
    if url and not str(url).lower().startswith(("http://", "https://")):
        problems.append("url must start with http:// or https://")
    # An API-backed source with neither a url nor a query has nothing to fetch.
    # Only blocking once it is going to be collected from.
    if (
        for_collection
        and platform in ("DAUM_CAFE", "NAVER_CAFE", "NAVER_BLOG")
        and not queries
        and not url
    ):
        problems.append(
            f"{platform} needs at least one search query or a url before it can be enabled"
        )
    if problems:
        raise SourceValidationError("; ".join(problems))


def list_sources(
    con, *, enabled_only: bool = False, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    sql = (
        "SELECT s.*, g.code AS genre_code, r.name AS region_name, "
        "  (SELECT count(*) FROM source_items i WHERE i.source_id = s.source_id) AS item_count "
        "FROM sources s "
        "LEFT JOIN genres g ON g.genre_id = s.genre_id "
        "LEFT JOIN regions r ON r.region_id = s.region_id"
    )
    if enabled_only:
        sql += " WHERE s.enabled"
    sql += " ORDER BY s.source_key"
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params = (limit, offset)
    with con.cursor() as cur:
        cur.execute(sql, params)
        return _rows(cur)


def count_sources(con, *, enabled_only: bool = False) -> int:
    sql = "SELECT count(*) FROM sources"
    if enabled_only:
        sql += " WHERE enabled"
    with con.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def get_source(con, source_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM sources WHERE source_id = %s", (source_id,))
        return _row(cur)


def get_source_by_key(con, source_key: str) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM sources WHERE source_key = %s", (source_key,))
        return _row(cur)


def create_source(
    con, *, source_key: str, name: str, platform: str, source_role: str,
    url: str | None = None, genre_id: int | None = None, region_id: int | None = None,
    authority_level: str = "UNKNOWN", queries: list[str] | None = None,
    config: dict[str, Any] | None = None, enabled: bool = False,
    collection_interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    notes: str | None = None,
) -> dict[str, Any]:
    queries = [q.strip() for q in (queries or []) if q and q.strip()]
    validate(
        source_key=source_key, name=name, platform=platform, source_role=source_role,
        url=url, authority_level=authority_level, queries=queries,
        collection_interval_minutes=collection_interval_minutes,
        for_collection=enabled,
    )
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (source_key, name, platform, source_role, url, "
            "  genre_id, region_id, authority_level, queries, config, enabled, "
            "  collection_interval_minutes, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s) "
            "RETURNING *",
            (
                source_key.strip(), name.strip(), platform, source_role,
                (url or None), genre_id, region_id, authority_level,
                json.dumps(queries), json.dumps(config or {}), enabled,
                collection_interval_minutes, notes,
            ),
        )
        return _row(cur)


def update_source(con, source_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = (
        "name", "platform", "source_role", "url", "genre_id", "region_id",
        "authority_level", "enabled", "collection_interval_minutes", "notes",
    )
    updates = {k: v for k, v in fields.items() if k in allowed}
    json_updates = {k: fields[k] for k in ("queries", "config") if k in fields}

    if "collection_interval_minutes" in updates:
        interval = int(updates["collection_interval_minutes"])
        if interval < MIN_INTERVAL_MINUTES:
            raise SourceValidationError(
                f"collection_interval_minutes must be at least {MIN_INTERVAL_MINUTES}"
            )
        updates["collection_interval_minutes"] = interval
    if "platform" in updates and updates["platform"] not in PLATFORMS:
        raise SourceValidationError(f"unknown platform: {updates['platform']}")
    if "source_role" in updates and updates["source_role"] not in SOURCE_ROLES:
        raise SourceValidationError(f"unknown source_role: {updates['source_role']}")

    if not updates and not json_updates:
        return get_source(con, source_id)

    # Turning a source on through update_source() has to clear the same bar as
    # set_enabled(): from that moment the scheduler fetches from it.
    if updates.get("enabled") is True:
        current = get_source(con, source_id)
        if current is None:
            return None
        merged = {**current, **updates}
        queries = json_updates.get("queries", merged.get("queries") or [])
        if isinstance(queries, str):
            queries = json.loads(queries)
        validate(
            source_key=merged["source_key"], name=merged["name"],
            platform=merged["platform"], source_role=merged["source_role"],
            url=merged.get("url"), authority_level=merged["authority_level"],
            collection_interval_minutes=int(merged["collection_interval_minutes"]),
            queries=queries, for_collection=True,
        )

    assignments = [f"{key} = %s" for key in updates]
    values: list[Any] = list(updates.values())
    for key, value in json_updates.items():
        assignments.append(f"{key} = %s::jsonb")
        values.append(json.dumps(value))

    with con.cursor() as cur:
        cur.execute(
            f"UPDATE sources SET {', '.join(assignments)}, updated_at = now() "
            "WHERE source_id = %s RETURNING *",
            (*values, source_id),
        )
        return _row(cur)


def set_enabled(con, source_id: int, enabled: bool) -> dict[str, Any] | None:
    """Enable or disable a source.

    Enabling re-validates with the collection rules: from this moment the
    scheduler will fetch from it, so an incomplete definition has to be
    rejected here rather than failing on every tick afterwards.
    """
    if enabled:
        source = get_source(con, source_id)
        if source is None:
            return None
        queries = source.get("queries") or []
        if isinstance(queries, str):
            queries = json.loads(queries)
        validate(
            source_key=source["source_key"], name=source["name"],
            platform=source["platform"], source_role=source["source_role"],
            url=source.get("url"), authority_level=source["authority_level"],
            collection_interval_minutes=source["collection_interval_minutes"],
            queries=queries, for_collection=True,
        )
    with con.cursor() as cur:
        cur.execute(
            "UPDATE sources SET enabled = %s, updated_at = now() "
            "WHERE source_id = %s RETURNING *",
            (enabled, source_id),
        )
        return _row(cur)


def record_collection_result(
    con, source_id: int, *, status: str, detail: str | None = None,
    collected_at: datetime | None = None,
) -> None:
    with con.cursor() as cur:
        cur.execute(
            "UPDATE sources SET last_status = %s, last_detail = %s, "
            "  last_collected_at = COALESCE(%s, now()), updated_at = now() "
            "WHERE source_id = %s",
            (status, (detail or "")[:500] or None, collected_at, source_id),
        )


def is_due(source: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Has this source's collection interval elapsed?

    A source that has never been collected is always due; a disabled one never
    is, whatever its interval says.
    """
    if not source.get("enabled"):
        return False
    last = source.get("last_collected_at")
    if last is None:
        return True
    now = now or datetime.now(timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    interval = int(source.get("collection_interval_minutes") or DEFAULT_INTERVAL_MINUTES)
    return now - last >= timedelta(minutes=interval)


def due_sources(con, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Enabled sources whose interval has elapsed, oldest collection first."""
    return [s for s in list_sources(con, enabled_only=True) if is_due(s, now=now)]


def acquisition_outcomes(con) -> dict[int, dict[str, int]]:
    """Per source: how many of its posts we could actually read.

    A source can pass its Test, return results and still be useless, because
    the cafe serves its articles only to a logged-in reader. That shows up here
    as items with no body, and it is the operator's call whether to keep the
    source -- an automatic rule would quietly drop a community that fixes its
    settings next week.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT i.source_id, "
            "  count(*) AS items, "
            "  count(*) FILTER (WHERE c.acquisition_status LIKE 'FETCHED%%') AS fetched, "
            "  count(*) FILTER (WHERE c.acquisition_status = 'FETCH_BLOCKED') AS blocked, "
            "  count(*) FILTER (WHERE c.acquisition_status = 'LOGIN_REQUIRED') AS login, "
            "  count(e.event_id) AS events "
            "FROM source_items i "
            "LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
            "LEFT JOIN events e ON e.source_item_id = i.source_item_id "
            "GROUP BY i.source_id"
        )
        names = [c.name for c in cur.description]
        return {row[0]: dict(zip(names, row)) for row in cur.fetchall()}
