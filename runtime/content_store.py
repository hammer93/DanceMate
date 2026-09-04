"""Persistence for acquired content, and the acquisition work queue.

Sits between `runtime.acquisition` (which knows how to fetch) and PostgreSQL
(which remembers what was fetched). Keeps the storage policy in one place:
extracted text only, personal data already redacted, one row per source item.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from . import acquisition


def _rows(cur) -> list[dict[str, Any]]:
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _row(cur) -> dict[str, Any] | None:
    columns = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(columns, row))


def ensure_row(con, source_item_id: int) -> dict[str, Any]:
    """Every source item has a content row, even before anything is fetched."""
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO source_item_content (source_item_id, acquisition_status) "
            "VALUES (%s, %s) ON CONFLICT (source_item_id) DO NOTHING",
            (source_item_id, acquisition.METADATA_ONLY),
        )
        cur.execute(
            "SELECT * FROM source_item_content WHERE source_item_id = %s", (source_item_id,)
        )
        return _row(cur)


def get(con, source_item_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM source_item_content WHERE source_item_id = %s", (source_item_id,)
        )
        return _row(cur)


def mark_pending(con, source_item_ids: list[int]) -> int:
    """Queue items for acquisition. Never re-queues a settled item."""
    if not source_item_ids:
        return 0
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET acquisition_status = %s, "
            "  next_attempt_at = now(), updated_at = now() "
            "WHERE source_item_id = ANY(%s) AND acquisition_status = %s",
            (acquisition.FETCH_PENDING, source_item_ids, acquisition.METADATA_ONLY),
        )
        return cur.rowcount


def due_for_acquisition(con, *, limit: int = 10) -> list[dict[str, Any]]:
    """Items whose fetch is due: queued or retryable, and past their backoff."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT c.*, i.url, i.title AS item_title, i.source_id, s.source_key, s.platform "
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "JOIN sources s ON s.source_id = i.source_id "
            "WHERE c.acquisition_status = ANY(%s) "
            "  AND i.url IS NOT NULL "
            "  AND (c.next_attempt_at IS NULL OR c.next_attempt_at <= now()) "
            "ORDER BY c.next_attempt_at NULLS FIRST, c.source_item_id "
            "LIMIT %s",
            (list(acquisition.RETRYABLE), limit),
        )
        return _rows(cur)


def record_outcome(
    con, source_item_id: int, outcome: acquisition.AcquisitionOutcome,
    *, now: datetime | None = None,
) -> dict[str, Any]:
    """Store what a fetch produced and schedule any retry."""
    now = now or datetime.now(timezone.utc)
    existing = ensure_row(con, source_item_id)
    attempt_count = int(existing.get("attempt_count") or 0) + 1
    previous_hash = existing.get("content_hash")
    retry_at = acquisition.next_attempt_at(
        outcome.status, outcome.error_code, attempt_count, now=now
    )

    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET "
            "  acquisition_status = %s, acquisition_method = %s, fetched_url = %s, "
            "  canonical_url = %s, http_status = %s, content_type = %s, title = %s, "
            "  extracted_text = %s, content_length = %s, content_hash = %s, "
            "  previous_content_hash = %s, image_count = %s, poster_candidates = %s::jsonb, "
            "  redacted_spans = %s, fetch_error = %s, error_code = %s, "
            "  attempt_count = %s, "
            "  first_attempt_at = COALESCE(first_attempt_at, %s), "
            "  last_attempt_at = %s, "
            # fetched_at means "we got the body", and stays null on a refusal.
            # last_attempt_at means "we asked", which is the one an operator
            # needs when nothing is coming back.
            "  fetched_at = %s, next_attempt_at = %s, updated_at = now() "
            "WHERE source_item_id = %s RETURNING *",
            (
                outcome.status, outcome.method, outcome.fetched_url,
                outcome.canonical_url, outcome.http_status, outcome.content_type,
                outcome.title, outcome.text or None, outcome.content_length,
                outcome.content_hash, previous_hash, len(outcome.images),
                json.dumps(outcome.images[:10]), outcome.redacted_spans,
                (outcome.error or None), outcome.error_code, attempt_count,
                now, now, (now if outcome.text else None), retry_at, source_item_id,
            ),
        )
        stored = _row(cur)

    host = ""
    if outcome.fetched_url:
        host = urllib.parse.urlparse(outcome.fetched_url).netloc
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO content_fetch_log (source_item_id, host, http_status, outcome, "
            "  text_length, duration_ms) VALUES (%s, %s, %s, %s, %s, %s)",
            (source_item_id, host or "unknown", outcome.http_status, outcome.status,
             outcome.content_length, outcome.duration_ms),
        )
    return stored


def content_changed(existing: dict[str, Any] | None, outcome) -> bool:
    """Did this fetch produce different text from last time?

    An unchanged page does not need re-extraction, which is the whole point of
    storing the hash.
    """
    if existing is None:
        return True
    return (existing.get("content_hash") or "") != (outcome.content_hash or "")


def needing_reprocess(con, *, limit: int = 50, force: bool = False) -> list[dict[str, Any]]:
    """Items with fetched text the engine has not seen since it was fetched.

    ``force`` returns every item with text, whether or not it has already been
    reprocessed. That is the case when the *extractor* changed rather than the
    content: engine v0.74 reads a time out of ``PM 07:30~11:30`` that v0.73
    got wrong, and nothing about the stored article says so. Re-extraction is
    then an explicit operator decision, not something a scheduler infers.
    """
    freshness = "" if force else (
        " AND (c.reprocessed_at IS NULL OR c.reprocessed_at < c.fetched_at)"
    )
    # Normally only items whose article body we actually fetched are worth
    # re-reading: nothing else has changed. A forced pass is the other case --
    # the extractor changed, so every post we hold reads differently now,
    # including the ones we only ever had a search snippet for. Those are
    # exactly where a wrong date hides, because a snippet is mostly title.
    statuses = ([acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL]
                if not force else None)
    with con.cursor() as cur:
        cur.execute(
            "SELECT c.*, i.url, i.source_id, s.source_key, s.source_role, i.raw "
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "JOIN sources s ON s.source_id = i.source_id "
            "WHERE " + ("c.acquisition_status = ANY(%s) AND c.extracted_text IS NOT NULL"
                        if statuses else "true")
            + freshness +
            " ORDER BY c.fetched_at NULLS LAST, c.source_item_id LIMIT %s",
            ((statuses, limit) if statuses else (limit,)),
        )
        return _rows(cur)


def mark_reprocessed(con, source_item_id: int) -> None:
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET reprocessed_at = now(), updated_at = now() "
            "WHERE source_item_id = %s",
            (source_item_id,),
        )


def summary(con) -> dict[str, Any]:
    """Acquisition state for the dashboard and the intake viewer."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT acquisition_status, count(*) FROM source_item_content "
            "GROUP BY acquisition_status"
        )
        by_status = dict(cur.fetchall())
        cur.execute(
            "SELECT coalesce(avg(content_length), 0)::int, coalesce(max(content_length), 0) "
            "FROM source_item_content WHERE content_length > 0"
        )
        average_length, max_length = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM content_fetch_log WHERE fetched_at::date = current_date"
        )
        fetches_today = cur.fetchone()[0]
        cur.execute("SELECT coalesce(sum(redacted_spans), 0) FROM source_item_content")
        redacted = cur.fetchone()[0]
    return {
        "by_status": by_status,
        "fetched": by_status.get(acquisition.FETCHED_FULL, 0)
        + by_status.get(acquisition.FETCHED_PARTIAL, 0),
        "average_text_length": average_length,
        "max_text_length": max_length,
        "content_fetches_today": fetches_today,
        "redacted_spans": redacted,
    }


def listing(
    con, *, limit: int = 200, status: str | None = None,
    source_id: int | None = None, today_only: bool = False,
) -> list[dict[str, Any]]:
    """The /admin/intake table: what was collected, and what came of it."""
    where = ["TRUE"]
    params: list[Any] = []
    if status:
        where.append("c.acquisition_status = %s")
        params.append(status)
    if source_id is not None:
        where.append("i.source_id = %s")
        params.append(source_id)
    if today_only:
        where.append("i.collected_at::date = current_date")

    with con.cursor() as cur:
        cur.execute(
            "SELECT i.source_item_id, i.collected_at, i.title, i.url, i.ingest_state, "
            "       i.external_id, s.source_key, s.name AS source_name, s.platform, "
            "       r.mode AS discovery_mode, "
            "       coalesce(c.acquisition_status, %s) AS acquisition_status, "
            "       c.content_length, c.acquisition_method, c.fetched_at, c.http_status "
            "FROM source_items i "
            "JOIN sources s ON s.source_id = i.source_id "
            "LEFT JOIN source_collection_runs r ON r.collection_run_id = i.collection_run_id "
            "LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY i.collected_at DESC, i.source_item_id DESC LIMIT %s",
            (acquisition.METADATA_ONLY, *params, limit),
        )
        return _rows(cur)


def detail(con, source_item_id: int) -> dict[str, Any] | None:
    """Everything known about one intake item, for /admin/intake/{id}."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT i.*, s.source_key, s.name AS source_name, s.platform, s.source_role, "
            "       r.mode AS discovery_mode, r.started_at AS run_started_at "
            "FROM source_items i "
            "JOIN sources s ON s.source_id = i.source_id "
            "LEFT JOIN source_collection_runs r ON r.collection_run_id = i.collection_run_id "
            "WHERE i.source_item_id = %s",
            (source_item_id,),
        )
        item = _row(cur)
    if item is None:
        return None
    item["content"] = get(con, source_item_id)
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM content_fetch_log WHERE source_item_id = %s "
            "ORDER BY fetched_at DESC LIMIT 10",
            (source_item_id,),
        )
        item["fetch_log"] = _rows(cur)
    return item
