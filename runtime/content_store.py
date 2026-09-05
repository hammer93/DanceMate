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


def settle_full_body(con, source_item_id: int, *, body: str | None) -> dict[str, Any] | None:
    """Record a discovery-synthesized body as already-settled `FETCHED_FULL`
    content, so the generic acquisition queue never has a reason to touch it.

    v0.82.2 root cause: a source whose discovery module already produces the
    complete article body (TangoNOW, Tango Calendar Korea, Miltang - none of
    them do a separate HTML detail fetch the way DanceInfo's title-only list
    stage does) previously left `source_item_content` untouched at intake
    time. `mark_pending()`/`due_for_acquisition()` then read "no content row
    yet" as "needs fetching", queued it, and a later generic re-fetch through
    `acquisition.fetch()` (which has no Miltang/TangoNOW-specific extraction
    rule) could silently replace the correct body with the site's own
    generic `og:description` tagline - which `engine-reprocess` then read as
    a genuine revision and re-extracted, producing a date-less candidate
    that `normalization.normalize_all()`'s own cleanup correctly read as "no
    longer live" and deleted the previously-correct event for. Confirmed
    live: 85 of 108 real Miltang items were degraded this way within about
    90 minutes, and the derived event count fell from 50 to 8.

    Calling this immediately after `intake.store_item()` closes the gap at
    its source: `mark_pending()` only ever promotes a row already sitting at
    `METADATA_ONLY`, and `due_for_acquisition()` only selects `RETRYABLE`
    statuses (`FETCH_PENDING`/`FETCH_FAILED`/`FETCH_BLOCKED`) - a row
    inserted here as `FETCHED_FULL` structurally never matches either query,
    with no extra guard needed anywhere else in the acquisition/reprocess
    path. `reprocessed_at` is set alongside `fetched_at` for the same
    reason: `engine_ingest.ingest_pending()`'s own very next pass already
    reads this exact body through `source_item_content` (see its
    `_to_raw_post()`), so a later `engine-reprocess` pass has nothing left
    to usefully redo.

    A blank or too-short body is never settled (existing thin-body
    semantics, `MINIMUM_USEFUL_TEXT` - Section 8's own "빈 본문은 settled
    금지"): the row is left exactly as `ensure_row()`/`mark_pending()` would
    have left it, so the ordinary acquisition queue still tries for real
    content. Idempotent and revision-safe by construction: an unchanged body
    updates nothing (the `WHERE` guard on the upsert), and a genuinely
    changed one (a revised discovery, not a lesser-quality fallback) is
    written straight over the previous settled text - the same "new
    discovery body wins outright" rule this project already applies to a
    revised `source_items` row.
    """
    text = (body or "").strip()
    if len(text) < acquisition.MINIMUM_USEFUL_TEXT:
        return None
    now = datetime.now(timezone.utc)
    digest = acquisition.content_hash(text)
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO source_item_content ("
            "  source_item_id, acquisition_status, acquisition_method, "
            "  extracted_text, content_length, content_hash, "
            "  first_attempt_at, last_attempt_at, fetched_at, reprocessed_at, "
            "  attempt_count, updated_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, now()) "
            "ON CONFLICT (source_item_id) DO UPDATE SET "
            "  acquisition_status = EXCLUDED.acquisition_status, "
            "  acquisition_method = EXCLUDED.acquisition_method, "
            "  extracted_text = EXCLUDED.extracted_text, "
            "  content_length = EXCLUDED.content_length, "
            "  previous_content_hash = source_item_content.content_hash, "
            "  content_hash = EXCLUDED.content_hash, "
            "  last_attempt_at = EXCLUDED.last_attempt_at, "
            "  fetched_at = EXCLUDED.fetched_at, "
            "  reprocessed_at = EXCLUDED.reprocessed_at, "
            "  updated_at = now() "
            "WHERE source_item_content.content_hash IS DISTINCT FROM EXCLUDED.content_hash "
            "RETURNING *",
            (
                source_item_id, acquisition.FETCHED_FULL,
                acquisition.METHOD_DISCOVERY_SYNTHESIZED,
                text, len(text), digest, now, now, now, now,
            ),
        )
        return _row(cur)


def get(con, source_item_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM source_item_content WHERE source_item_id = %s", (source_item_id,)
        )
        return _row(cur)


def newly_collected(con) -> list[int]:
    """Items with a URL that have never been considered for acquisition at
    all, or that are still sitting at `METADATA_ONLY` - `acquisition_job.run()`'s
    own first step, "anything collected but never queued becomes queued".

    A `NON_HTML_API_PARSERS` source (TangoNOW, Tango Calendar Korea) is
    excluded here regardless of its content state: its `source_url` is a
    JSON API endpoint that will never serve HTML, so this is not "waiting to
    be queued" - it must never be queued at all. v0.82.2's
    `settle_full_body()` already keeps a normal item off this list by giving
    it a `FETCHED_FULL` content row at intake; this exclusion is the
    content-agnostic backstop for the rare case discovery's own body was too
    short to settle.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT i.source_item_id FROM source_items i "
            "JOIN sources s ON s.source_id = i.source_id "
            "LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
            "WHERE i.url IS NOT NULL "
            "  AND (c.source_item_id IS NULL OR c.acquisition_status = %s) "
            "  AND NOT (COALESCE(s.config->>'parser', '') = ANY(%s))",
            (acquisition.METADATA_ONLY, list(acquisition.NON_HTML_API_PARSERS)),
        )
        return [row[0] for row in cur.fetchall()]


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
    """Items whose fetch is due: queued or retryable, and past their backoff.

    A row belonging to a `NON_HTML_API_PARSERS` source is excluded here too,
    independent of the exclusion already applied where such a row would
    normally get queued (`scheduler.acquisition_job.run()`'s own selection).
    This is deliberate defense in depth: a historical row already sitting at
    `FETCH_PENDING`/`FETCH_FAILED`/`FETCH_BLOCKED` from before this release
    must not be fetched either, even though no new one can be created.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT c.*, i.url, i.title AS item_title, i.source_id, s.source_key, s.platform "
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "JOIN sources s ON s.source_id = i.source_id "
            "WHERE c.acquisition_status = ANY(%s) "
            "  AND i.url IS NOT NULL "
            "  AND (c.next_attempt_at IS NULL OR c.next_attempt_at <= now()) "
            "  AND NOT (COALESCE(s.config->>'parser', '') = ANY(%s)) "
            "ORDER BY c.next_attempt_at NULLS FIRST, c.source_item_id "
            "LIMIT %s",
            (list(acquisition.RETRYABLE), list(acquisition.NON_HTML_API_PARSERS), limit),
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
            "SELECT c.*, i.url, i.source_id, i.published_at, "
            "       s.source_key, s.source_role, i.raw "
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


def _listing_where(
    *, status: str | None, source_id: int | None, today_only: bool,
) -> tuple[list[str], list[Any]]:
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
    return where, params


def listing(
    con, *, limit: int = 200, offset: int = 0, status: str | None = None,
    source_id: int | None = None, today_only: bool = False,
) -> list[dict[str, Any]]:
    """The /admin/intake table: what was collected, and what came of it."""
    where, params = _listing_where(
        status=status, source_id=source_id, today_only=today_only)

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
            "ORDER BY i.collected_at DESC, i.source_item_id DESC LIMIT %s OFFSET %s",
            (acquisition.METADATA_ONLY, *params, limit, offset),
        )
        return _rows(cur)


def count_listing(
    con, *, status: str | None = None, source_id: int | None = None,
    today_only: bool = False,
) -> int:
    where, params = _listing_where(
        status=status, source_id=source_id, today_only=today_only)
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM source_items i "
            "JOIN sources s ON s.source_id = i.source_id "
            "LEFT JOIN source_collection_runs r ON r.collection_run_id = i.collection_run_id "
            "LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
            f"WHERE {' AND '.join(where)}",
            tuple(params),
        )
        return cur.fetchone()[0]


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
