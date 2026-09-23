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

    v0.96.1 - three kinds of row, decided *before* the LIMIT (see
    acquisition.queue_state()):

    * PENDING - never asked (attempt_count = 0, no next_attempt_at): due now.
    * RETRYABLE - asked, and the policy named a time: due once that time
      has passed; a future time is left alone.
    * TERMINAL - asked, and the policy named no time (a PERMANENT_ERRORS
      refusal such as ROBOTS_DISALLOWED, or an exhausted retry class): never
      selected again, and its attempt_count never moves again.

    `next_attempt_at IS NULL` alone used to count as "due now, first in
    line", which made every terminal row the head of the queue on every
    tick and starved the rows behind it (Production, 2026-09-16 onward:
    five ROBOTS_DISALLOWED rows, 541 attempts each, 936 FETCH_PENDING rows
    never reached). Rows already in that state on a deployed database fall
    out of the queue by this rule alone - no cleanup, no migration.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT c.*, i.url, i.title AS item_title, i.source_id, s.source_key, s.platform "
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "JOIN sources s ON s.source_id = i.source_id "
            "WHERE c.acquisition_status = ANY(%s) "
            "  AND i.url IS NOT NULL "
            "  AND NOT (COALESCE(c.error_code, '') = ANY(%s)) "
            "  AND ((c.next_attempt_at IS NULL AND COALESCE(c.attempt_count, 0) = 0) "
            "       OR c.next_attempt_at <= now()) "
            "  AND NOT (COALESCE(s.config->>'parser', '') = ANY(%s)) "
            "ORDER BY c.next_attempt_at NULLS FIRST, c.source_item_id "
            "LIMIT %s",
            (list(acquisition.RETRYABLE), list(acquisition.PERMANENT_ERRORS),
             list(acquisition.NON_HTML_API_PARSERS), limit),
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


# v0.96.3: how many times one item may fail re-extraction before the
# incremental pass steps over it. Without a cap the first broken row would be
# selected first on every tick forever and nothing behind it would ever be
# reached; with one, the row leaves the queue and stays visible through
# `reprocess_error` / `reprocess_backlog()["stalled"]` instead of vanishing.
MAX_REPROCESS_ATTEMPTS = 3

# "We hold something the engine can read for this item": a fetched body, a
# blocked fetch that produced a poster for the image fallback, or - v0.96.9 -
# a blocked fetch whose *discovery* payload still carries readable text.
#
# The third arm asks about `source_items`, not about the content row, because
# that is where `engine_ingest._to_raw_post()` reads a blocked item from: a
# FETCH_BLOCKED row is handed the collector's own title and snippet and never
# its `extracted_text`, which `record_outcome()` overwrites with NULL on every
# refusal. Gating re-extraction on the content row's own body therefore asked
# a question about a column the blocked path does not use, and answered "no"
# for 1,081 of Production's 1,105 blocked items - including 641 carrying a
# candidate and 271 carrying an Event that no engine bump could ever reach.
#
# Readable is not the same question as trustworthy. Whether the *existing*
# candidates may be replaced by what the current engine makes of this text is
# decided separately, per item, by `engine_ingest._blocked_input_lost()`.
_HAS_READABLE_CONTENT = (
    "((c.acquisition_status = ANY(%(full)s) AND c.extracted_text IS NOT NULL) "
    " OR (c.acquisition_status = %(blocked)s AND ("
    "        (c.poster_candidates IS NOT NULL "
    "         AND jsonb_array_length(c.poster_candidates) > 0) "
    "     OR length(btrim(coalesce(i.raw->>%(body_key)s, ''))) >= %(min_text)s "
    "     OR length(btrim(coalesce(i.title, ''))) > 0)))"
)

# The parameters `_HAS_READABLE_CONTENT` needs beyond `full`/`blocked`, which
# both of its call sites already bind for their own reasons.
_READABLE_PARAMS = {
    "body_key": "body",
    "min_text": acquisition.MINIMUM_USEFUL_TEXT,
}


def needing_reprocess(con, *, limit: int = 50, force: bool = False,
                      engine_version: str | None = None,
                      after_item_id: int | None = None,
                      max_attempts: int = MAX_REPROCESS_ATTEMPTS,
                      ) -> list[dict[str, Any]]:
    """Items the engine should read again, newest reason first.

    Three reasons, OR'd:

    1. the body arrived after the last re-extract (the v0.76 case),
    2. a blocked fetch gained a poster since the last one (v0.84.3),
    3. ``engine_version`` is given and the row's stored
       ``extracted_engine_version`` is not it (v0.96.3).

    (3) is what makes an engine bump finishable. Re-extraction after a bump
    is not a content event - the bodies did not change, so (1) and (2) are
    false for every one of them - and the only previous answer was ``force``,
    which selects *everything* in `fetched_at` order. Because
    `mark_reprocessed()` does not change that order, repeating a forced batch
    re-read the same first rows forever and the only terminating call was a
    single synchronous pass over the whole table. With (3) the DB row is the
    cursor: a successful re-extract stamps the running version, the row
    leaves the queue for good, and the next tick necessarily gets new rows.
    Nothing here knows *which* version 0.91 is, so the next bump needs no
    code change.

    v0.96.9: (3)'s readable-content gate now also admits a blocked item
    whose discovery title or snippet the engine can still read, not only
    one carrying a poster - see `_HAS_READABLE_CONTENT`. Selecting a row
    is not the same as trusting the result over what is already stored;
    that stays `engine_ingest.reprocess_acquired()`'s own decision, made
    per item from the fetch log.

    Note this deliberately includes `settle_full_body()` rows (a discovery
    module's own synthesized body, stamped `reprocessed_at = fetched_at` so
    branch (1) never fires for it). v0.82.2's rule is that a *lesser* body
    must never overwrite a good one; re-reading the same stored body with a
    newer extractor is the opposite of that, and is the whole point here.

    ``force`` returns every item, reprocessed or not, in `source_item_id`
    order so `after_item_id` can page through it deterministically - the
    admin diagnostic path, not the operational one.
    """
    # Normally only items whose article body we actually fetched are worth
    # re-reading: nothing else has changed. A forced pass is the other case --
    # the extractor changed, so every post we hold reads differently now,
    # including the ones we only ever had a search snippet for. Those are
    # exactly where a wrong date hides, because a snippet is mostly title.
    #
    # v0.84.3: a FETCH_BLOCKED item carrying a poster candidate (an
    # image-only post - no body text was ever served, but a real attached
    # image was) is worth the same re-read once it has one, purely for the
    # image-OCR fallback `engine_ingest._gather_image_texts()` already
    # gates on field-missing + poster-present. A blocked item with no
    # poster stays excluded - there is nothing new to give the engine.
    #
    # A FETCH_BLOCKED outcome never sets `fetched_at` (it means "we got a
    # body", which a blocked fetch by definition did not) - gating this
    # branch on `fetched_at` the same way as FETCHED_FULL/PARTIAL would
    # make it permanently ineligible the moment `reprocessed_at` is ever
    # set at all (every item that has been through ordinary ingest once).
    # `record_outcome()` bumps `updated_at` on every fetch regardless of
    # outcome, so that is this branch's own freshness signal instead.
    params: dict[str, Any] = {}
    if force:
        where = "true"
    else:
        params = {
            "full": [acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL],
            "blocked": acquisition.FETCH_BLOCKED,
            **_READABLE_PARAMS,
        }
        reasons = [
            "(c.acquisition_status = ANY(%(full)s) AND c.extracted_text IS NOT NULL "
            "  AND (c.reprocessed_at IS NULL OR c.reprocessed_at < c.fetched_at))",
            "(c.acquisition_status = %(blocked)s "
            "    AND c.poster_candidates IS NOT NULL "
            "    AND jsonb_array_length(c.poster_candidates) > 0 "
            "    AND (c.reprocessed_at IS NULL OR c.reprocessed_at < c.updated_at))",
        ]
        if engine_version:
            params["engine"] = engine_version
            reasons.append(
                "(" + _HAS_READABLE_CONTENT + " AND (c.extracted_engine_version IS NULL "
                " OR c.extracted_engine_version <> %(engine)s))"
            )
        where = "(" + " OR ".join(reasons) + ")"
        # The failure cap applies to every operational reason, not only the
        # engine-version one: an item that raises on re-extract wedges the
        # queue in exactly the same way whichever branch selected it.
        params["max_attempts"] = max_attempts
        where += " AND COALESCE(c.reprocess_attempts, 0) < %(max_attempts)s"
    # The cursor is the caller's, for the forced pass; the incremental pass
    # needs none, because a stamped row stops matching `where` at all.
    if after_item_id is not None:
        params["after"] = after_item_id
        where += " AND c.source_item_id > %(after)s"
    order = "c.source_item_id" if (force or after_item_id is not None) \
        else "c.fetched_at NULLS LAST, c.source_item_id"
    with con.cursor() as cur:
        cur.execute(
            # i.title as its own alias: c.* already carries a `title` column
            # (source_item_content's own, parsed from the fetched page body
            # - NULL for anything that was never fetched, most obviously a
            # FETCH_BLOCKED row) which would otherwise shadow the source
            # item's real, discovery-time title from Python's column-name
            # dict-building with no error or warning. v0.84.4: found because
            # classify_with_image_evidence() needs a real title to work
            # with, not a silently-empty one.
            "SELECT c.*, i.url, i.source_id, i.published_at, i.title AS source_item_title, "
            "       s.source_key, s.source_role, i.raw "
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "JOIN sources s ON s.source_id = i.source_id "
            "WHERE " + where +
            " ORDER BY " + order + " LIMIT %(limit)s",
            {**params, "limit": limit},
        )
        return _rows(cur)


def mark_reprocessed(con, source_item_id: int, *,
                     engine_version: str | None = None) -> None:
    """Record that the engine has now read this content.

    ``engine_version`` is what takes the row out of the incremental queue
    (see `needing_reprocess()`), so every path that finishes with an item -
    re-extracted, skipped because a person reviewed it, or preserved because
    a blocked fetch had nothing better to offer - passes it. A skip that did
    not stamp would be re-selected on every tick forever and the rows behind
    it would never be reached, which is the very failure this release exists
    to remove.

    A successful pass also clears any previous failure: the item is healthy
    again, and a stale count would otherwise retire it early next time.
    """
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET reprocessed_at = now(), updated_at = now(), "
            "  extracted_engine_version = COALESCE(%s, extracted_engine_version), "
            "  reprocess_attempts = 0, reprocess_error = NULL "
            "WHERE source_item_id = %s",
            (engine_version, source_item_id),
        )


def mark_extracted_engine_version(con, source_item_id: int, engine_version: str) -> None:
    """Stamp the engine version without claiming a re-extract happened.

    First ingest already runs the *current* engine over the body it has, so
    the row does not belong in the incremental re-extract queue; but it has
    not been "reprocessed" either, and moving `reprocessed_at` would suppress
    the genuine body-arrived-later pass that `needing_reprocess()` branch (1)
    exists for.
    """
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET extracted_engine_version = %s, "
            "  updated_at = now() WHERE source_item_id = %s",
            (engine_version, source_item_id),
        )


def best_fetched_text_length(con, source_item_ids: list[int]) -> dict[int, int]:
    """The longest body we have ever actually been served for each item.

    `content_fetch_log` is append-only, which is the only reason this can be
    asked at all. `record_outcome()` writes every fetch over the same content
    row: a refusal sets `extracted_text` to NULL, `content_length` to 0 and
    `fetched_at` back to NULL, so an item that *was* fetched once and blocked
    afterwards is, in `source_item_content` alone, indistinguishable from one
    that was never served a body in its life. The log keeps both, and telling
    those two apart is the whole question v0.96.9's preserve rule turns on -
    see `engine_ingest._blocked_input_lost()`.

    Only a fetch that actually produced text counts: `FETCH_BLOCKED` rows are
    logged too, with `text_length` 0. Items with no successful fetch are
    absent from the result rather than present as 0, so a caller's own
    ``.get(id, 0)`` says "nothing was ever lost here".

    One query per batch, never per item.
    """
    if not source_item_ids:
        return {}
    with con.cursor() as cur:
        cur.execute(
            "SELECT source_item_id, max(text_length) FROM content_fetch_log "
            "WHERE source_item_id = ANY(%s) AND outcome = ANY(%s) "
            "  AND text_length > 0 GROUP BY source_item_id",
            (list(source_item_ids),
             [acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL]),
        )
        return {int(row[0]): int(row[1]) for row in cur.fetchall()}


def record_reprocess_failure(con, source_item_id: int, error: str) -> int:
    """Count a failed re-extraction and keep its reason on the row.

    Returns the new attempt count. Past `MAX_REPROCESS_ATTEMPTS` the item
    stops being selected - the queue keeps moving - but `reprocess_error`
    and `reprocess_failed_at` stay, and `reprocess_backlog()` reports it as
    stalled, so nothing is lost quietly.
    """
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET "
            "  reprocess_attempts = COALESCE(reprocess_attempts, 0) + 1, "
            "  reprocess_error = %s, reprocess_failed_at = now(), updated_at = now() "
            "WHERE source_item_id = %s RETURNING reprocess_attempts",
            ((error or "")[:500] or None, source_item_id),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def reprocess_backlog(con, engine_version: str, *,
                      max_attempts: int = MAX_REPROCESS_ATTEMPTS) -> dict[str, int]:
    """How much of the stored content the running engine has not read yet.

    `outdated` is what the incremental pass still has to work through,
    `stalled` what it gave up on, `current` what this engine version has
    already produced. The three sum to every item holding readable content,
    which is the denominator a re-extract rollout is measured against.
    """
    params = {
        "full": [acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL],
        "blocked": acquisition.FETCH_BLOCKED,
        "engine": engine_version,
        "max_attempts": max_attempts,
        **_READABLE_PARAMS,
    }
    with con.cursor() as cur:
        cur.execute(
            "SELECT "
            "  count(*) FILTER (WHERE c.extracted_engine_version IS NOT DISTINCT FROM "
            "                         %(engine)s), "
            "  count(*) FILTER (WHERE c.extracted_engine_version IS DISTINCT FROM "
            "                         %(engine)s "
            "                     AND COALESCE(c.reprocess_attempts, 0) < %(max_attempts)s), "
            "  count(*) FILTER (WHERE c.extracted_engine_version IS DISTINCT FROM "
            "                         %(engine)s "
            "                     AND COALESCE(c.reprocess_attempts, 0) >= %(max_attempts)s), "
            "  count(*) "
            # The same join `needing_reprocess()` makes, for the same reason:
            # v0.96.9's readable-content rule asks about the discovery payload
            # a blocked item is actually re-read from.
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "WHERE " + _HAS_READABLE_CONTENT,
            params,
        )
        current, outdated, stalled, total = cur.fetchone()
    return {
        "engine_version": engine_version,
        "current": int(current),
        "outdated": int(outdated),
        "stalled": int(stalled),
        "with_content": int(total),
    }


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


def bulk_extracted_text(con, source_item_ids: list[int]) -> dict[int, str | None]:
    """Batch form of reading `source_item_content.extracted_text` - one
    query for many items (v0.86.4 Source Audit Workbench, Section 107-112:
    no N+1 when a source's item list computes review hints for up to 50
    rows at once)."""
    ids = [i for i in source_item_ids if i is not None]
    if not ids:
        return {}
    with con.cursor() as cur:
        cur.execute(
            "SELECT source_item_id, extracted_text FROM source_item_content "
            "WHERE source_item_id = ANY(%s)",
            (ids,),
        )
        return dict(cur.fetchall())


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
