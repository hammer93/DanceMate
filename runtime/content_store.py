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
    if outcome.status == acquisition.NOT_MODIFIED:
        # A 304 carries no body; written here it would erase the one it
        # confirms. Only `runtime.article_refresh` asks conditionally.
        raise ValueError("a 304 is article_refresh's to record, not record_outcome()'s")
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

# v0.96.42: what an item's engine input *is*, as one value the database can
# compare - so "this page was revised after the engine read it" is a fact in
# the row rather than something a call site has to remember to say.
#
# Exactly the inputs `engine_ingest._to_raw_post()` builds a post from:
#
#   * `source_items.content_hash` - `intake.RawItem.content_hash()`, over
#     external_id, url, title, body and published_at, the collector's record
#     of the page (a title-only edit moves it);
#   * the content row's acquisition status, its own content_hash (the fetched
#     or settled article text) and the page title acquisition parsed - the
#     body a re-extraction reads, and its title fallback;
#   * the collector's judgement keys (`intake.JUDGEMENT_KEYS`, v0.96.35),
#     present-and-null distinct from absent, as `intake._judgement()` reads
#     them.
#
# And nothing else: not collected_at, attempt counts, run ids, fetch
# timestamps or poster URLs (signed, so volatile). Collecting an unchanged
# page again moves none of these, so it never moves the signature. A
# blocked refusal repeated stores the same status, a NULL hash and the same
# title, so neither does that.
INPUT_SIGNATURE = (
    "md5(concat_ws(chr(31), coalesce(i.content_hash, ''), "
    "  coalesce(c.acquisition_status, ''), coalesce(c.content_hash, ''), "
    "  coalesce(c.title, ''), "
    "  coalesce((SELECT jsonb_object_agg(k, i.raw -> k) "
    "              FROM unnest(%(judgement_keys)s::text[]) AS k "
    "             WHERE jsonb_typeof(i.raw) = 'object' AND i.raw ? k)::text, '')))"
)

#: How the pass that finished an item finished it (migration 050).
OUTCOME_EXTRACTED = "EXTRACTED"
OUTCOME_PRESERVED_BODY_LOST = "PRESERVED_BODY_LOST"
OUTCOME_PRESERVED_IMAGE_EVIDENCE_LOST = "PRESERVED_IMAGE_EVIDENCE_LOST"
OUTCOME_KEPT_HUMAN_REVIEWED = "KEPT_HUMAN_REVIEWED"
OUTCOMES = (OUTCOME_EXTRACTED, OUTCOME_PRESERVED_BODY_LOST,
            OUTCOME_PRESERVED_IMAGE_EVIDENCE_LOST, OUTCOME_KEPT_HUMAN_REVIEWED)
PRESERVED_OUTCOMES = (OUTCOME_PRESERVED_BODY_LOST, OUTCOME_PRESERVED_IMAGE_EVIDENCE_LOST)


def _signature_params() -> dict[str, Any]:
    from . import intake  # local: intake imports this module lazily too

    return {"judgement_keys": list(intake.JUDGEMENT_KEYS)}


# A recorded signature that no longer matches the input: revised since the
# engine read it. NULL ("recorded before v0.96.42") is not a revision - those
# rows are signed by `engine_ingest.reconcile_unsigned()`, never assumed stale.
_REVISED_SINCE_READ = (
    "(c.extracted_input_signature IS NOT NULL "
    " AND c.extracted_input_signature <> " + INPUT_SIGNATURE + ")"
)


def input_signature(con, source_item_id: int) -> str | None:
    """The item's current input signature; None when it has no content row."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT " + INPUT_SIGNATURE + " FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "WHERE c.source_item_id = %(id)s",
            {**_signature_params(), "id": source_item_id},
        )
        row = cur.fetchone()
    return row[0] if row else None


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
        # v0.96.42: (4) the input was revised after the pass that finished
        # this item read it. Not tied to an engine version: a revised page is
        # re-read by the engine that is running, and only that page is.
        reasons.append("(" + _HAS_READABLE_CONTENT + " AND " + _REVISED_SINCE_READ + ")")
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
            #
            # v0.96.42: input_signature is the signature of exactly what this
            # selection hands the engine. The pass stamps *this* value, not a
            # fresh one, so a revision stored while the pass runs leaves the
            # row reading "revised since read" and it is selected again.
            "SELECT c.*, i.url, i.source_id, i.published_at, i.title AS source_item_title, "
            "       i.collected_at AS source_collected_at, "
            "       s.source_key, s.source_role, i.raw, "
            "       " + INPUT_SIGNATURE + " AS input_signature "
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "JOIN sources s ON s.source_id = i.source_id "
            "WHERE " + where +
            " ORDER BY " + order + " LIMIT %(limit)s",
            {**params, **_signature_params(), "limit": limit},
        )
        return _rows(cur)


def mark_reprocessed(con, source_item_id: int, *,
                     engine_version: str | None = None,
                     input_signature: str | None = None,
                     outcome: str | None = None) -> None:
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

    v0.96.42: finished is not the same as applied, so the pass now says
    which it was. ``outcome`` is recorded (`OUTCOMES`), and
    `applied_engine_version` moves only for `OUTCOME_EXTRACTED` - a
    preserved or human-kept item keeps whatever reading was in force, known or
    not. ``input_signature`` is the signature the pass *selected* the row
    with (`needing_reprocess()`'s ``input_signature``), so a revision stored
    while the pass ran still reads as revised afterwards.
    """
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError(f"unknown extraction outcome {outcome!r}")
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET reprocessed_at = now(), updated_at = now(), "
            "  extracted_engine_version = COALESCE(%(engine)s, extracted_engine_version), "
            "  reprocess_attempts = 0, reprocess_error = NULL, "
            "  extracted_input_signature = COALESCE(%(signature)s, extracted_input_signature), "
            "  extraction_outcome = COALESCE(%(outcome)s, extraction_outcome), "
            "  extraction_outcome_at = CASE WHEN %(outcome)s::text IS NULL "
            "    THEN extraction_outcome_at ELSE now() END, "
            "  applied_engine_version = CASE WHEN %(outcome)s = %(extracted)s "
            "    THEN COALESCE(%(engine)s, applied_engine_version) "
            "    ELSE applied_engine_version END "
            "WHERE source_item_id = %(id)s",
            {"engine": engine_version, "signature": input_signature, "outcome": outcome,
             "extracted": OUTCOME_EXTRACTED, "id": source_item_id},
        )


def mark_extracted_engine_version(con, source_item_id: int, engine_version: str, *,
                                  input_signature: str | None = None) -> None:
    """Stamp the engine version without claiming a re-extract happened.

    First ingest already runs the *current* engine over the body it has, so
    the row does not belong in the incremental re-extract queue; but it has
    not been "reprocessed" either, and moving `reprocessed_at` would suppress
    the genuine body-arrived-later pass that `needing_reprocess()` branch (1)
    exists for.

    v0.96.42: first ingest did apply that engine's reading, so it is recorded
    as `OUTCOME_EXTRACTED`, with the ``input_signature`` read before the
    ingest built its post (`engine_ingest.ingest_pending()`).
    """
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET extracted_engine_version = %(engine)s, "
            "  applied_engine_version = %(engine)s, extraction_outcome = %(extracted)s, "
            "  extraction_outcome_at = now(), "
            "  extracted_input_signature = COALESCE(%(signature)s, extracted_input_signature), "
            "  updated_at = now() WHERE source_item_id = %(id)s",
            {"engine": engine_version, "extracted": OUTCOME_EXTRACTED,
             "signature": input_signature, "id": source_item_id},
        )


def mark_needs_reextract(con, source_item_id: int) -> None:
    """Put one item back in the incremental re-extract queue (v0.96.35).

    The mirror image of `mark_extracted_engine_version()` above: that one
    stamps a row as already read by the running engine, this one withdraws
    the claim. `needing_reprocess()` branch (3) selects on
    `extracted_engine_version` not matching the running version, so clearing
    it is exactly "this item has not been read by the current engine", which
    is true again the moment the input the engine reads has changed.

    The caller is `intake.store_item()`, for an item whose *text* is
    unchanged - so none of the content-event branches (1) and (2) would ever
    fire for it - but whose collector record now carries a different
    judgement than the one the engine last read. Re-ingesting cannot help
    there: `database.persist_raw_post()` keys on the post's own URL and
    returns `is_new = False`, and `ingest_pending()` only extracts a new
    post, so without this the better record would sit in `source_items.raw`
    and never be read. Does not touch `reprocessed_at`: no content arrived,
    so branch (1)'s body-arrived-later pass must stay available.

    v0.96.42: also called for a page whose *text* was revised (the other
    `store_item()` branch), which needed it just as much - item 6234's
    re-collected title sat behind `is_new = False` until the next engine
    bump. It is the explicit request; the input signature it leaves behind
    is what makes the row read "revised since read" even if a request were
    ever lost, and does not touch `extracted_input_signature`.
    """
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET extracted_engine_version = NULL, "
            "  updated_at = now() WHERE source_item_id = %s",
            (source_item_id,),
        )


def unsigned_rows(con, engine_version: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """Readable rows the running engine finished before v0.96.42 recorded
    what it read - `engine_ingest.reconcile_unsigned()`'s batch, in the same
    shape `needing_reprocess()` returns. Rows still outdated are left to the
    queue, which signs them when it re-reads them."""
    params = {
        "full": [acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL],
        "blocked": acquisition.FETCH_BLOCKED,
        **_READABLE_PARAMS,
        **_signature_params(),
        "engine": engine_version,
        "limit": limit,
    }
    with con.cursor() as cur:
        cur.execute(
            "SELECT c.*, i.url, i.source_id, i.published_at, i.title AS source_item_title, "
            "       i.collected_at AS source_collected_at, "
            "       s.source_key, s.source_role, i.raw, "
            "       " + INPUT_SIGNATURE + " AS input_signature "
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "JOIN sources s ON s.source_id = i.source_id "
            "WHERE " + _HAS_READABLE_CONTENT +
            "  AND c.extracted_input_signature IS NULL "
            "  AND c.extracted_engine_version = %(engine)s "
            "ORDER BY c.source_item_id LIMIT %(limit)s",
            params,
        )
        return _rows(cur)


def sign_input(con, source_item_id: int, input_signature: str) -> None:
    """Record the signature of an input the engine is shown to have read,
    without claiming a pass happened now (`reconcile_unsigned()`).

    Leaves `updated_at` alone on purpose: `needing_reprocess()` branch (2)
    re-reads a blocked item with a poster whenever `updated_at` passes
    `reprocessed_at`, and signing is not news about its content."""
    with con.cursor() as cur:
        cur.execute(
            "UPDATE source_item_content SET extracted_input_signature = %s "
            "WHERE source_item_id = %s AND extracted_input_signature IS NULL",
            (input_signature, source_item_id),
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
        **_signature_params(),
    }
    # v0.96.42: an item revised since it was read is not current either -
    # it is work the queue still has to do, whichever version stamped it.
    stale = ("(c.extracted_engine_version IS DISTINCT FROM %(engine)s OR "
             + _REVISED_SINCE_READ + ")")
    with con.cursor() as cur:
        cur.execute(
            "SELECT "
            "  count(*) FILTER (WHERE NOT " + stale + "), "
            "  count(*) FILTER (WHERE " + stale +
            "                     AND COALESCE(c.reprocess_attempts, 0) < %(max_attempts)s), "
            "  count(*) FILTER (WHERE " + stale +
            "                     AND COALESCE(c.reprocess_attempts, 0) >= %(max_attempts)s), "
            "  count(*), "
            "  count(*) FILTER (WHERE c.extracted_engine_version IS NOT DISTINCT FROM "
            "                         %(engine)s AND " + _REVISED_SINCE_READ + "), "
            "  count(*) FILTER (WHERE c.extracted_input_signature IS NULL) "
            # The same join `needing_reprocess()` makes, for the same reason:
            # v0.96.9's readable-content rule asks about the discovery payload
            # a blocked item is actually re-read from.
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "WHERE " + _HAS_READABLE_CONTENT,
            params,
        )
        current, outdated, stalled, total, revised, unsigned = cur.fetchone()
    return {
        "engine_version": engine_version,
        "current": int(current),
        "outdated": int(outdated),
        "stalled": int(stalled),
        "with_content": int(total),
        # Of outdated + stalled: revised since read under the running engine.
        "revised_since_read": int(revised),
        # Recorded before v0.96.42 and not yet signed by reconcile_unsigned().
        "unsigned": int(unsigned),
    }


# --- extraction freshness (v0.96.42) ------------------------------------------
#
# "The running engine's version is stamped on this row" and "the running
# engine's reading of this item is the one in force" used to be one value.
# They are not: a FETCH_BLOCKED item whose input is gone, and an item whose
# candidate a person reviewed, are both stamped by a pass that applied
# nothing - item 643 reads 1.16 while its event is still what an older
# engine read off a poster. These are the states an operator is shown
# instead, from what the database records, and from what the reprocess
# policy itself derives where nothing was recorded (rows finished before
# v0.96.42).

NOT_EXTRACTED = "NOT_EXTRACTED"
REEXTRACTION_PENDING = "REEXTRACTION_PENDING"
REEXTRACTION_FAILED = "REEXTRACTION_FAILED"
EXTRACTION_CURRENT = "EXTRACTION_CURRENT"
ENGINE_UPDATE_NOT_APPLIED = "ENGINE_UPDATE_NOT_APPLIED"
HUMAN_DECISION_KEPT = "HUMAN_DECISION_KEPT"
REEXTRACTION_NOT_VERIFIED = "REEXTRACTION_NOT_VERIFIED"
FRESHNESS_STATES = (NOT_EXTRACTED, REEXTRACTION_PENDING, REEXTRACTION_FAILED,
                    EXTRACTION_CURRENT, ENGINE_UPDATE_NOT_APPLIED, HUMAN_DECISION_KEPT,
                    REEXTRACTION_NOT_VERIFIED)
FLAG_SOURCE_FETCH_BLOCKED = "SOURCE_FETCH_BLOCKED"
FLAG_REVIEW_RECOMMENDED = "REVIEW_RECOMMENDED"
#: Where a state came from: written by the pass, or worked out from the policy.
BASIS_RECORDED = "RECORDED"
BASIS_DERIVED = "DERIVED"
UNKNOWN = "UNKNOWN"


def extraction_freshness(content: dict[str, Any] | None, engine_version: str, *,
                         readable: bool, revised_since_read: bool,
                         reviewed: bool = False, body_lost: bool | None = None,
                         used_image_ocr: bool | None = None, has_events: bool = False,
                         max_attempts: int = MAX_REPROCESS_ATTEMPTS) -> dict[str, Any]:
    """One item's extraction freshness, for the intake page and its JSON.

    A pure function of the content row and four facts the caller looks up:
    whether a person reviewed one of its candidates, whether a blocked item's
    fetched body is gone (`engine_ingest._blocked_body_lost()`, the policy's
    own test), whether its candidates were read off a poster, and whether it
    has events. ``body_lost``/``used_image_ocr`` are only consulted for a row
    whose outcome was never recorded; None means "not known", and an unknown
    never becomes a warning.
    """
    content = content or {}
    blocked = content.get("acquisition_status") == acquisition.FETCH_BLOCKED
    stamped = content.get("extracted_engine_version")
    outcome = content.get("extraction_outcome")
    applied = content.get("applied_engine_version")
    attempts = int(content.get("reprocess_attempts") or 0)
    flags = [FLAG_SOURCE_FETCH_BLOCKED] if blocked else []
    basis = BASIS_RECORDED
    if not readable:
        state, reason = NOT_EXTRACTED, "no content the engine can read is stored"
    elif stamped != engine_version or revised_since_read:
        why = ("revised since it was read" if stamped == engine_version
               else f"read by {stamped or 'no engine version'}, running {engine_version}")
        if attempts >= max_attempts:
            state, reason = REEXTRACTION_FAILED, (
                f"{why}; re-extraction failed {attempts} times: "
                f"{content.get('reprocess_error') or 'no error recorded'}")
        else:
            state, reason = REEXTRACTION_PENDING, why
    elif outcome == OUTCOME_EXTRACTED:
        state, reason = EXTRACTION_CURRENT, f"engine {applied} reading applied"
    elif outcome in PRESERVED_OUTCOMES:
        state = ENGINE_UPDATE_NOT_APPLIED
        reason = ("fetch blocked and the body it was read from is gone; the stored "
                  "candidates were kept" if outcome == OUTCOME_PRESERVED_BODY_LOST else
                  "its candidates were read off a poster this pass could not read; "
                  "they were kept")
    elif outcome == OUTCOME_KEPT_HUMAN_REVIEWED:
        state, reason = HUMAN_DECISION_KEPT, "a person reviewed its candidate; not re-read"
    else:
        # Finished before v0.96.42: nothing recorded how. What the policy
        # itself says about such a row, and no more.
        basis = BASIS_DERIVED
        if reviewed:
            state, reason = HUMAN_DECISION_KEPT, "a person reviewed its candidate; not re-read"
        elif not blocked:
            # An unblocked, unreviewed item is only ever stamped by a pass
            # that applied its reading (reprocess_acquired / ingest_pending).
            state, reason = EXTRACTION_CURRENT, f"stamped {stamped}; applied by every path that stamps it"
        elif body_lost:
            state, reason = ENGINE_UPDATE_NOT_APPLIED, (
                "fetch blocked and the body it was read from is gone; every pass "
                "keeps the stored candidates without asking the engine")
        elif used_image_ocr:
            state, reason = REEXTRACTION_NOT_VERIFIED, (
                "fetch blocked and its candidates came off a poster; whether the "
                "last pass could read the poster was not recorded")
        elif body_lost is None or used_image_ocr is None:
            state, reason = REEXTRACTION_NOT_VERIFIED, "fetch blocked; not enough recorded to say"
        else:
            state, reason = EXTRACTION_CURRENT, (
                f"stamped {stamped}; a blocked item with its input intact is re-read")
    if state in (ENGINE_UPDATE_NOT_APPLIED, REEXTRACTION_NOT_VERIFIED) and has_events:
        flags.append(FLAG_REVIEW_RECOMMENDED)
    return {
        "state": state,
        "basis": basis,
        "reason": reason,
        "flags": flags,
        "current_engine_version": engine_version,
        "stamped_engine_version": stamped,
        "last_applied_engine_version": applied or UNKNOWN,
        "extraction_outcome": outcome or UNKNOWN,
        "extraction_outcome_at": content.get("extraction_outcome_at"),
        "last_reprocessed_at": content.get("reprocessed_at"),
        "input_signature_recorded": content.get("extracted_input_signature"),
        "revised_since_read": revised_since_read,
        "reprocess_attempts": attempts,
        "reprocess_error": content.get("reprocess_error"),
    }


def freshness_inputs(con, source_item_id: int) -> dict[str, Any]:
    """The database facts `extraction_freshness()` needs about one item."""
    params = {
        "full": [acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL],
        "blocked": acquisition.FETCH_BLOCKED,
        **_READABLE_PARAMS,
        **_signature_params(),
        "id": source_item_id,
    }
    with con.cursor() as cur:
        cur.execute(
            "SELECT " + _HAS_READABLE_CONTENT + ", " + _REVISED_SINCE_READ + ", "
            "  EXISTS (SELECT 1 FROM events e WHERE e.source_item_id = i.source_item_id) "
            "FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "WHERE c.source_item_id = %(id)s",
            params,
        )
        row = cur.fetchone()
    if row is None:
        return {"readable": False, "revised_since_read": False, "has_events": False}
    return {"readable": bool(row[0]), "revised_since_read": bool(row[1]),
            "has_events": bool(row[2])}


# The intake list's extraction filter: recorded facts only, in SQL, so a
# page of 50 never asks the engine store anything. The detail page refines
# an UNRECORDED_BLOCKED row with the policy's derivation.
EXTRACTION_FILTERS = {
    "PENDING": "(c.extracted_engine_version IS DISTINCT FROM %(engine)s OR "
               + _REVISED_SINCE_READ + ") AND COALESCE(c.reprocess_attempts, 0) < %(max_attempts)s",
    "FAILED": "(c.extracted_engine_version IS DISTINCT FROM %(engine)s OR "
              + _REVISED_SINCE_READ + ") AND COALESCE(c.reprocess_attempts, 0) >= %(max_attempts)s",
    "NOT_APPLIED": "c.extraction_outcome = ANY(%(preserved)s)",
    "HUMAN_KEPT": "c.extraction_outcome = %(kept)s",
    "UNRECORDED_BLOCKED": "c.acquisition_status = %(blocked)s AND c.extraction_outcome IS NULL",
    # v0.96.43: the protected items an operator should look at - blocked,
    # served a body once that the fetch log remembers and the row no longer
    # holds (`engine_ingest._blocked_body_lost()`'s own test, asked of the
    # log in SQL), not re-read since, feeding an Event, and not yet looked
    # at by a person (a Review action on one of its Events' candidates).
    # Production, 2026-10-20: exactly 643, 646 and 647, the three the
    # per-item derivation flags REVIEW_RECOMMENDED.
    "REVIEW": "c.acquisition_status = %(blocked)s "
              "AND COALESCE(c.extraction_outcome, '') <> %(extracted)s "
              "AND EXISTS (SELECT 1 FROM events e WHERE e.source_item_id = c.source_item_id) "
              "AND NOT EXISTS (SELECT 1 FROM human_review_actions h "
              "  WHERE h.source_item_id = c.source_item_id OR h.candidate_id IN "
              "    (SELECT e.candidate_id FROM events e WHERE e.source_item_id = c.source_item_id)) "
              "AND EXISTS (SELECT 1 FROM content_fetch_log l "
              "  WHERE l.source_item_id = c.source_item_id AND l.outcome = ANY(%(full)s) "
              "    AND l.text_length >= %(min_text)s "
              "    AND l.text_length > length(COALESCE(NULLIF(i.raw->>'body', ''), i.body, '')))",
}


def review_filter_params() -> dict[str, Any]:
    """The parameters `EXTRACTION_FILTERS["REVIEW"]` binds."""
    return {"blocked": acquisition.FETCH_BLOCKED, "extracted": OUTCOME_EXTRACTED,
            "full": [acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL],
            "min_text": acquisition.MINIMUM_USEFUL_TEXT}


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


def listing_extraction_label(row: dict[str, Any], engine_version: str) -> tuple[str, str]:
    """The intake list's one-word extraction state and its tone, from what the
    row records (the detail page adds the policy's derivation)."""
    outcome = row.get("extraction_outcome")
    stamped = row.get("extracted_engine_version")
    if row.get("acquisition_status") in (None, acquisition.METADATA_ONLY) and not stamped:
        return "NOT READ", "muted"
    if stamped != engine_version or row.get("revised_since_read"):
        return "PENDING", "warn"
    if outcome in PRESERVED_OUTCOMES:
        return "NOT APPLIED", "warn"
    if outcome == OUTCOME_KEPT_HUMAN_REVIEWED:
        return "HUMAN KEPT", "muted"
    if outcome == OUTCOME_EXTRACTED:
        return "CURRENT", "ok"
    if row.get("acquisition_status") == acquisition.FETCH_BLOCKED:
        return "UNRECORDED", "muted"
    return "CURRENT", "ok"


def _listing_where(
    *, status: str | None, source_id: int | None, today_only: bool,
    extraction: str | None = None, engine_version: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    where = ["TRUE"]
    params: dict[str, Any] = {}
    if status:
        where.append("c.acquisition_status = %(status)s")
        params["status"] = status
    if source_id is not None:
        where.append("i.source_id = %(source_id)s")
        params["source_id"] = source_id
    if today_only:
        where.append("i.collected_at::date = current_date")
    if extraction:
        # v0.96.42: an unknown filter is refused rather than silently ignored.
        where.append("(" + EXTRACTION_FILTERS[extraction] + ")")
        params.update({
            "engine": engine_version, "max_attempts": MAX_REPROCESS_ATTEMPTS,
            "preserved": list(PRESERVED_OUTCOMES), "kept": OUTCOME_KEPT_HUMAN_REVIEWED,
            "blocked": acquisition.FETCH_BLOCKED, **_signature_params(),
            **review_filter_params(),
        })
    return where, params


def listing(
    con, *, limit: int = 200, offset: int = 0, status: str | None = None,
    source_id: int | None = None, today_only: bool = False,
    extraction: str | None = None, engine_version: str | None = None,
) -> list[dict[str, Any]]:
    """The /admin/intake table: what was collected, and what came of it."""
    where, params = _listing_where(
        status=status, source_id=source_id, today_only=today_only,
        extraction=extraction, engine_version=engine_version)

    with con.cursor() as cur:
        cur.execute(
            "SELECT i.source_item_id, i.collected_at, i.title, i.url, i.ingest_state, "
            "       i.external_id, s.source_key, s.name AS source_name, s.platform, "
            "       r.mode AS discovery_mode, "
            "       coalesce(c.acquisition_status, %(metadata_only)s) AS acquisition_status, "
            "       c.content_length, c.acquisition_method, c.fetched_at, c.http_status, "
            "       c.extracted_engine_version, c.extraction_outcome, "
            "       COALESCE(" + _REVISED_SINCE_READ + ", false) AS revised_since_read "
            "FROM source_items i "
            "JOIN sources s ON s.source_id = i.source_id "
            "LEFT JOIN source_collection_runs r ON r.collection_run_id = i.collection_run_id "
            "LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY i.collected_at DESC, i.source_item_id DESC "
            "LIMIT %(limit)s OFFSET %(offset)s",
            {**params, **_signature_params(), "metadata_only": acquisition.METADATA_ONLY,
             "limit": limit, "offset": offset},
        )
        return _rows(cur)


def count_listing(
    con, *, status: str | None = None, source_id: int | None = None,
    today_only: bool = False, extraction: str | None = None,
    engine_version: str | None = None,
) -> int:
    where, params = _listing_where(
        status=status, source_id=source_id, today_only=today_only,
        extraction=extraction, engine_version=engine_version)
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM source_items i "
            "JOIN sources s ON s.source_id = i.source_id "
            "LEFT JOIN source_collection_runs r ON r.collection_run_id = i.collection_run_id "
            "LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
            f"WHERE {' AND '.join(where)}",
            params,
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


# --- protected source review (v0.96.43) ----------------------------------------
#
# v0.96.42 could say *that* an item's stored Event was not re-read by the
# running engine (ENGINE_UPDATE_NOT_APPLIED, REVIEW_RECOMMENDED). This puts
# what an operator needs to act on it beside that verdict: the candidates and
# Events it concerns, what original evidence is still held, and which of the
# existing Review actions applies. Read-only, like the page it feeds; every
# correction goes through `/admin/review/{candidate_id}`, which already has
# authentication, the request token and the audit trail.

ACTION_REVIEW = "REVIEW_AGAINST_EVIDENCE"
ACTION_REQUEST_EVIDENCE = "REQUEST_ADDITIONAL_EVIDENCE"
ACTION_NONE = "NONE"

#: The event fields an operator compares against the evidence.
REVIEW_EVENT_FIELDS = (
    "event_id", "candidate_id", "event_name", "event_type", "event_date", "end_date",
    "start_time", "end_time", "end_day_offset", "venue_text", "venue_id", "fee", "dj",
    "listing_state", "canonical_event_id", "review_state", "time_evidence",
)


def protected_review(con, source_item_id: int, freshness: dict[str, Any] | None
                     ) -> dict[str, Any]:
    """What a protected (or otherwise not-re-read) item needs reviewed."""
    freshness = freshness or {}
    candidate_ids = list(freshness.get("candidate_ids") or [])
    with con.cursor() as cur:
        cur.execute(
            "SELECT " + ", ".join(REVIEW_EVENT_FIELDS) + ", "
            "  (COALESCE(end_date, event_date) >= (now() AT TIME ZONE 'Asia/Seoul')::date) "
            "    AS not_ended "
            "FROM events WHERE source_item_id = %s OR primary_source_item_id = %s "
            "  OR candidate_id = ANY(%s) ORDER BY event_date, event_id",
            (source_item_id, source_item_id, candidate_ids),
        )
        events = _rows(cur)
        cur.execute(
            "SELECT text_length, fetched_at, http_status FROM content_fetch_log "
            "WHERE source_item_id = %s AND outcome = ANY(%s) AND text_length > 0 "
            "ORDER BY text_length DESC, fetched_at DESC LIMIT 1",
            (source_item_id, [acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL]),
        )
        best = cur.fetchone()
        cur.execute(
            "SELECT c.poster_candidates, length(COALESCE(i.raw->>'body', i.body, '')), "
            "  c.extracted_text IS NOT NULL "
            "FROM source_items i LEFT JOIN source_item_content c USING (source_item_id) "
            "WHERE i.source_item_id = %s", (source_item_id,))
        posters, snippet_chars, holds_text = cur.fetchone() or (None, 0, False)
        cur.execute(
            "SELECT count(*), count(*) FILTER (WHERE ocr_text IS NOT NULL AND ocr_text <> '') "
            "FROM source_item_image WHERE source_item_id = %s", (source_item_id,))
        images_fetched, images_read = cur.fetchone()
        cur.execute(
            "SELECT count(*), max(created_at) FROM human_review_actions "
            "WHERE candidate_id = ANY(%s) OR source_item_id = %s",
            (candidate_ids + [e["candidate_id"] for e in events if e.get("candidate_id")],
             source_item_id))
        human_actions, last_human_action = cur.fetchone()

    evidence = {
        "article_text_held": bool(holds_text),
        "best_fetched_chars": int(best[0]) if best else 0,
        "best_fetched_at": best[1] if best else None,
        "discovery_snippet_chars": int(snippet_chars or 0),
        "poster_urls": list(posters or []),
        "images_fetched": int(images_fetched),
        "images_with_ocr_text": int(images_read),
        "human_review_actions": int(human_actions),
        "last_human_action_at": last_human_action,
    }
    flagged = FLAG_REVIEW_RECOMMENDED in (freshness.get("flags") or [])
    # A person has looked already: their decision stands, nothing is asked twice.
    recommended = flagged and not evidence["human_review_actions"]
    original = evidence["poster_urls"] or evidence["images_with_ocr_text"] \
        or evidence["article_text_held"] or evidence["discovery_snippet_chars"]
    reviewed = evidence["human_review_actions"] and (
        flagged or freshness.get("state") == HUMAN_DECISION_KEPT)
    if reviewed:
        action, what = ACTION_NONE, (
            f"reviewed by a person ({evidence['human_review_actions']} action(s), last "
            f"{str(evidence['last_human_action_at'])[:19]}); their decision stands and the "
            "FETCH_BLOCKED protection stays")
    elif not recommended:
        action, what = ACTION_NONE, "no review recommended for this item"
    elif original:
        action, what = ACTION_REVIEW, (
            "Open each candidate in Review and compare its Event fields with the original "
            "evidence below. EDIT corrects a field the evidence settles, CONFIRM records "
            "that the stored values stand, REJECT removes a non-event. If the evidence does "
            "not settle a field, keep the existing data. Nothing changes until you act: "
            "the FETCH_BLOCKED protection stays and this page fetches nothing.")
    else:
        action, what = ACTION_REQUEST_EVIDENCE, (
            "No original evidence is held here: check the Original URL by hand before "
            "changing anything, and keep the existing data until something settles it.")
    return {
        "source_item_id": source_item_id,
        "review_recommended": recommended,
        "candidate_ids": candidate_ids,
        "events": events,
        "events_not_ended": sum(1 for e in events if e.get("not_ended")),
        "evidence": evidence,
        "required_action": action,
        "required_action_text": what,
    }
