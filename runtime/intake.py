"""Raw source intake persistence.

What a collector returns is stored verbatim here before anything interprets it.
Interpretation belongs to the Information Engine, which keeps its own SQLite
store; this module never writes there.

Deduplication is on `(source_id, external_id)`. Re-collecting an unchanged post
is a duplicate; an edited one keeps the same row but gets a new content hash and
goes back to PENDING so the engine sees the revision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

INGEST_PENDING = "PENDING"
INGEST_DONE = "INGESTED"
INGEST_SKIPPED = "SKIPPED"
INGEST_FAILED = "FAILED"


@dataclass(frozen=True)
class RawItem:
    """One item as a collector saw it, before any interpretation."""

    external_id: str
    url: str | None = None
    title: str | None = None
    body: str | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        """Hash the meaningful content, not the metadata we add ourselves.

        collected_at is deliberately excluded: collecting the same post twice
        must produce the same hash, or nothing would ever be a duplicate.
        """
        payload = json.dumps(
            {
                "external_id": self.external_id,
                "url": self.url,
                "title": self.title,
                "body": self.body,
                "published_at": self.published_at.isoformat() if self.published_at else None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(cur) -> dict[str, Any] | None:
    columns = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(columns, row))


def _rows(cur) -> list[dict[str, Any]]:
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def start_run(con, source_id: int, *, mode: str) -> int:
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO source_collection_runs (source_id, mode, status) "
            "VALUES (%s, %s, 'RUNNING') RETURNING collection_run_id",
            (source_id, mode),
        )
        return cur.fetchone()[0]


def finish_run(
    con, collection_run_id: int, *, status: str, discovered: int = 0,
    new: int = 0, duplicates: int = 0, error: str | None = None,
) -> None:
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_collection_runs SET status = %s, discovered_count = %s, "
            "  new_count = %s, duplicate_count = %s, error = %s, finished_at = now() "
            "WHERE collection_run_id = %s",
            (status, discovered, new, duplicates, (error or "")[:1000] or None,
             collection_run_id),
        )


def record_error(
    con, *, source_id: int | None, collection_run_id: int | None,
    kind: str, detail: str | None,
) -> None:
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO source_errors (source_id, collection_run_id, kind, detail) "
            "VALUES (%s, %s, %s, %s)",
            (source_id, collection_run_id, kind, (detail or "")[:2000] or None),
        )


def store_item(
    con, source_id: int, item: RawItem, *, collection_run_id: int | None = None
) -> str:
    """Persist one raw item. Returns NEW, REVISED or DUPLICATE."""
    digest = item.content_hash()
    with con.cursor() as cur:
        cur.execute(
            "SELECT source_item_id, content_hash FROM source_items "
            "WHERE source_id = %s AND external_id = %s",
            (source_id, item.external_id),
        )
        existing = cur.fetchone()

        if existing is None:
            cur.execute(
                "INSERT INTO source_items (source_id, collection_run_id, external_id, "
                "  url, title, body, published_at, content_hash, raw) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                (source_id, collection_run_id, item.external_id, item.url, item.title,
                 item.body, item.published_at, digest,
                 json.dumps(item.raw, ensure_ascii=False, default=str)),
            )
            return "NEW"

        source_item_id, previous_hash = existing
        if previous_hash == digest:
            return "DUPLICATE"

        # Upstream edited the post: keep the row, refresh it, re-queue for the engine.
        cur.execute(
            "UPDATE source_items SET collection_run_id = %s, url = %s, title = %s, "
            "  body = %s, published_at = %s, content_hash = %s, raw = %s::jsonb, "
            "  collected_at = now(), ingest_state = %s, ingested_at = NULL "
            "WHERE source_item_id = %s",
            (collection_run_id, item.url, item.title, item.body, item.published_at,
             digest, json.dumps(item.raw, ensure_ascii=False, default=str),
             INGEST_PENDING, source_item_id),
        )
        return "REVISED"


def store_items(
    con, source_id: int, items: list[RawItem], *, collection_run_id: int | None = None
) -> dict[str, int]:
    counts = {"NEW": 0, "REVISED": 0, "DUPLICATE": 0}
    for item in items:
        counts[store_item(con, source_id, item, collection_run_id=collection_run_id)] += 1
    return counts


def pending_items(con, *, limit: int = 50) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT i.*, s.source_key, s.platform, s.source_role "
            "FROM source_items i JOIN sources s ON s.source_id = i.source_id "
            "WHERE i.ingest_state = %s ORDER BY i.collected_at LIMIT %s",
            (INGEST_PENDING, limit),
        )
        return _rows(cur)


def mark_ingested(con, source_item_id: int, state: str = INGEST_DONE) -> None:
    if state not in (INGEST_DONE, INGEST_SKIPPED, INGEST_FAILED):
        raise ValueError(f"not an ingest terminal state: {state}")
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_items SET ingest_state = %s, ingested_at = now() "
            "WHERE source_item_id = %s",
            (state, source_item_id),
        )


def recent_items(con, *, limit: int = 100, source_id: int | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT i.*, s.source_key, s.name AS source_name, s.platform "
        "FROM source_items i JOIN sources s ON s.source_id = i.source_id"
    )
    params: tuple[Any, ...] = ()
    if source_id is not None:
        sql += " WHERE i.source_id = %s"
        params = (source_id,)
    sql += " ORDER BY i.collected_at DESC LIMIT %s"
    with con.cursor() as cur:
        cur.execute(sql, (*params, limit))
        return _rows(cur)


def recent_runs(con, *, limit: int = 20) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT r.*, s.source_key, s.name AS source_name "
            "FROM source_collection_runs r JOIN sources s ON s.source_id = r.source_id "
            "ORDER BY r.started_at DESC LIMIT %s",
            (limit,),
        )
        return _rows(cur)


def summary(con) -> dict[str, Any]:
    """Counts for the admin dashboard. One query per figure, all cheap."""
    with con.cursor() as cur:
        cur.execute("SELECT count(*) FROM sources")
        total_sources = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sources WHERE enabled")
        enabled_sources = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM source_items")
        total_items = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM source_items WHERE ingest_state = %s", (INGEST_PENDING,)
        )
        pending = cur.fetchone()[0]
        cur.execute("SELECT max(last_collected_at) FROM sources")
        last_collection = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM source_errors WHERE occurred_at > now() - interval '24 hours'"
        )
        recent_errors = cur.fetchone()[0]
    return {
        "sources": total_sources,
        "enabled_sources": enabled_sources,
        "source_items": total_items,
        "pending_ingest": pending,
        "last_collection_at": last_collection.isoformat() if last_collection else None,
        "errors_24h": recent_errors,
    }
