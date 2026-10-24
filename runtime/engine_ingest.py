"""Hand collected raw items to the Information Engine.

    source_items (PostgreSQL)  ->  adapter  ->  Information Engine (SQLite)

The engine is not modified. This adapter rebuilds the engine's own
`RawPostRecord` from the payload the collector produced — which is exactly what
`source_items.raw` stores — and then calls the engine's own pipeline functions,
the same ones `src/main.py` calls for a live collection:

    persist_raw_post()        store the post, tell us if it is new
    process_discovered_post() classify and extract event candidates
    persist_events()          store the candidates

Items are marked INGESTED, SKIPPED or FAILED in PostgreSQL so the same post is
never processed twice and a failure is visible instead of silent.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from datetime import date
from typing import Any

from . import acquisition, candidate_identity, content_store, db, image_fallback, intake
from .config import Settings
from .engine_adapter import engine_db_path

log = logging.getLogger("dancemate.ingest")

# The engine's own default when a source does not declare a role.
DEFAULT_SOURCE_ROLE = "SECONDARY"


class EngineIngestUnavailable(RuntimeError):
    """The engine package or its store cannot be reached."""


def _engine(settings: Settings):
    root = str(settings.engine_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from src import database as engine_db  # noqa: PLC0415
        from src.collectors.base import RawPostRecord  # noqa: PLC0415
        from src.live_pipeline import process_discovered_post  # noqa: PLC0415
        from src.extractor import extract_single, needs_image_fallback  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on deployment
        raise EngineIngestUnavailable(f"engine package not importable: {exc}") from exc
    return engine_db, RawPostRecord, process_discovered_post, extract_single, needs_image_fallback


def _gather_image_texts(pg, settings: Settings, extract_single, needs_image_fallback,
                        item: dict, content: dict | None, post) -> list[tuple[str, str]]:
    """Image fallback's own cost gate (v0.81.3): only worth fetching and
    OCR-ing images at all when the body itself left date/start_time/fee
    missing. `extract_single()` is cheap (no I/O) and safe to call here as a
    plain precheck - `process_discovered_post()` runs it again for the real
    result, with the correct classification this precheck does not bother
    computing (event_type=None here only changes which EVENT_WORDS the
    precheck's own context-safety windowing uses, not the final answer).

    Never raises: a fetch/OCR failure here must not fail the item's own
    ingestion (Section 39) - only a missing image list is treated as "no
    fallback available", everything else about *why* is already recorded by
    image_fallback.gather_image_texts() itself.
    """
    urls = (content or {}).get("poster_candidates") or []
    if not urls:
        return []
    try:
        precheck = extract_single(post.title, post.body, published=post.published_at)
        if not needs_image_fallback(precheck):
            return []
        return image_fallback.gather_image_texts(
            pg, settings, source_item_id=item["source_item_id"],
            candidate_urls=urls, surrounding_text=post.title,
        )
    except Exception as exc:
        log.warning("image fallback skipped for source item %s: %s",
                   item.get("source_item_id"), exc)
        return []


def _open_engine_store(settings: Settings, engine_db):
    con = engine_db.init_db(engine_db_path(settings))
    # The engine's raw_posts.source_id references its own sources table, so the
    # engine's source registry has to exist before a post can be stored.
    try:
        import json  # noqa: PLC0415

        sources_path = settings.engine_root / "config" / "sources.json"
        if sources_path.is_file():
            engine_db.seed_sources(
                con, json.loads(sources_path.read_text(encoding="utf-8"))
            )
            con.commit()
    except Exception as exc:  # seeding is best effort; ingest can still proceed
        log.warning("could not seed engine sources: %s", exc)
    return con


def _to_raw_post(RawPostRecord, item: dict[str, Any], content: dict[str, Any] | None = None,
                 event_terms: tuple[str, ...] | None = None):
    """Rebuild the engine's RawPostRecord from a stored source item.

    When deep acquisition has fetched the original post, its text becomes the
    body and the engine sees the whole article instead of a search snippet.
    That is the entire point of v0.76: the times, venues and fees the extractor
    was missing are in the body, not the snippet.

    ``acquisition_quality`` is set to the engine's own vocabulary so its
    downstream logic keeps working: FULL when the article was fetched and has
    images, BODY_ONLY when it was fetched without, METADATA_ONLY otherwise.
    """
    raw = item.get("raw") or {}
    if isinstance(raw, str):
        import json  # noqa: PLC0415

        raw = json.loads(raw)

    snippet = raw.get("body") or item.get("body") or ""
    body = snippet
    quality = raw.get("acquisition_quality") or "METADATA_ONLY"

    if content and content.get("extracted_text"):
        status = content.get("acquisition_status")
        if status in (acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL):
            body = content["extracted_text"]
            if status == acquisition.FETCHED_FULL:
                quality = "FULL" if (content.get("image_count") or 0) else "BODY_ONLY"
            else:
                quality = "PARTIAL"

    return RawPostRecord(
        source_id=raw.get("source_id") or item.get("source_key"),
        platform=raw.get("platform") or item.get("platform"),
        source_url=raw.get("source_url") or item.get("url") or "",
        # item.get("title"): ingest_pending()'s `item` (intake.pending_items())
        # carries the discovery-time title directly under this key.
        # reprocess_acquired()'s `item` (content_store.needing_reprocess())
        # is a source_item_content row first - its own "title" column is the
        # page's own parsed title when acquisition found one, NULL for
        # anything never fetched (a FETCH_BLOCKED row, most obviously) -
        # source_item_title is that same call's explicit alias for the
        # discovery-time title, so a blocked or title-less fetch still gets
        # a real title instead of silently classifying an empty string.
        title=raw.get("title") or item.get("title") or item.get("source_item_title") or "",
        body=body,
        # The stored raw JSON is the collector's own record; the column is the
        # runtime's. Either will do, and one of them is always there.
        published_at=raw.get("published_at") or item.get("published_at"),
        cafe_name=raw.get("cafe_name"),
        thumbnail_url=raw.get("thumbnail_url"),
        discovery_query=raw.get("discovery_query"),
        acquisition_quality=quality,
        raw_json=raw.get("raw_json"),
        # v0.82.5: a discovery module sets this only when its own page/
        # section structure already guarantees the event type (see
        # miltang_discovery.discover()'s own comment) - process_discovered_
        # post() reads it straight off the RawPostRecord it is handed.
        known_event_type=raw.get("known_event_type"),
        class_event_opt_in=bool(raw.get("class_event_opt_in")),
        # v0.96.10: a collector that reads the source's own per-item
        # category carries it here (danceinfo_discovery.source_category()).
        # Read straight off the stored raw JSON, so a re-extraction of an
        # item collected after v0.96.10 sees it exactly as the first pass
        # did; an item collected before it has no such key and classifies
        # by text alone, which is what every other source does anyway.
        source_category=raw.get("source_category"),
        # v0.96.35: the collector's structural answer to "is there a night
        # here at all", for a source whose pages carry no event type to read.
        # Read off the stored raw the same way known_event_type above is, so
        # a re-extraction sees exactly what the ingest pass saw; an item
        # collected before v0.96.35 has no such key and classifies by text
        # alone, which is what every other source does anyway.
        source_night_fallback=raw.get("source_night_fallback"),
        # v0.96.41: a structured calendar's own "this record is a festival",
        # and the period the record states (festival_evidence.judgement()).
        # Read off the stored raw like the two above, so an item stored before
        # its collector learned to say so classifies by its text, as before.
        source_event_format=raw.get("source_event_format"),
        event_period=raw.get("event_period"),
        # v0.86.9: the Settings terminology for this source's genre -
        # see _detection_terms_by_source().
        event_terms=event_terms,
    )


def _detection_terms_by_source(pg):
    """The Settings words each source's posts should be recognised by (v0.86.9).

    One query for the terms and one for the sources, per batch - never per
    item. A source's genre scopes its words; a source with no genre gets
    every genre's. Never raises: if the terminology cannot be read, every
    post is classified exactly as it was before Settings existed.
    """
    from . import event_terms  # noqa: PLC0415 - keeps the import list stable

    import json as _json  # noqa: PLC0415

    try:
        grouped = event_terms.terms_by_genre(pg)
        with pg.cursor() as cur:
            # v0.96.0: a source's own config.event_terms - words this one
            # board uses for its night ("쁘락타임", "열탱즐탱") that no
            # genre-wide Settings term should carry. Same plumbing as the
            # Settings terms; never a source id in code.
            cur.execute("SELECT source_id, genre_id, config->'event_terms' FROM sources")
            rows = cur.fetchall()
        genre_of = {row[0]: row[1] for row in rows}
        own_terms = {}
        for row in rows:
            extra = row[2] if len(row) > 2 else None
            if isinstance(extra, str):
                try:
                    extra = _json.loads(extra)
                except ValueError:
                    extra = None
            if isinstance(extra, list):
                own_terms[row[0]] = tuple(
                    event_terms.normalize_term(str(t)) for t in extra if str(t).strip())
    except Exception as exc:  # noqa: BLE001 - classification must not stop here
        log.warning("event terminology unavailable, using built-in words only: %s", exc)
        return lambda source_id: None

    def lookup(source_id):
        words = tuple(event_terms.detection_terms(
            event_terms.terms_for(grouped, genre_of.get(source_id))) or ())
        words = tuple(dict.fromkeys(words + own_terms.get(source_id, ())))
        return words or None

    return lookup


def ingest_pending(settings: Settings, *, limit: int = 50) -> dict[str, Any]:
    """Feed pending source items into the Information Engine.

    Returns counts rather than raising: the scheduler records the summary and
    carries on. Individual item failures are marked FAILED and reported.
    """
    engine_db, RawPostRecord, process_discovered_post, extract_single, needs_image_fallback = \
        _engine(settings)

    with db.connect(settings, autocommit=True) as pg:
        items = intake.pending_items(pg, limit=limit)
        detection = _detection_terms_by_source(pg)
        if not items:
            return {"pending": 0, "ingested": 0, "skipped": 0, "failed": 0, "candidates": 0}

        engine_con = _open_engine_store(settings, engine_db)
        ingested = skipped = failed = candidates = 0
        failures: list[str] = []
        try:
            for item in items:
                try:
                    # v0.96.42: the signature first, then the input - a
                    # revision stored between the two leaves the stamp below
                    # older than the input, so the row reads "revised since
                    # read" and is re-read. The other order could stamp a
                    # revision this pass never saw.
                    signature = content_store.input_signature(pg, item["source_item_id"])
                    content = content_store.get(pg, item["source_item_id"])
                    post = _to_raw_post(RawPostRecord, item, content,
                                        event_terms=detection(item.get("source_id")))
                    if not post.source_url or not post.title:
                        intake.mark_ingested(pg, item["source_item_id"], intake.INGEST_SKIPPED)
                        skipped += 1
                        continue

                    image_texts = _gather_image_texts(
                        pg, settings, extract_single, needs_image_fallback,
                        item, content, post,
                    )
                    trusted_classification_texts = \
                        image_fallback.gather_trusted_classification_texts(
                            pg, item["source_item_id"],
                        )

                    post_id, is_new = engine_db.persist_raw_post(engine_con, post)
                    if is_new:
                        result = process_discovered_post(
                            engine_con, post,
                            item.get("source_role") or DEFAULT_SOURCE_ROLE,
                            image_texts=image_texts,
                            trusted_classification_texts=trusted_classification_texts,
                        )
                        events = result.get("events") or []
                        if events:
                            engine_db.persist_events(engine_con, post_id, events)
                            candidates += len(events)
                        used = {
                            e.inference
                            for ev in events for e in ev.evidences
                            if e.evidence_type == "IMAGE_OCR" and e.inference
                        }
                        if used:
                            image_fallback.mark_used_as_fallback(pg, item["source_item_id"], used)
                    engine_con.commit()
                    intake.mark_ingested(pg, item["source_item_id"], intake.INGEST_DONE)
                    if is_new and content is not None:
                        # v0.96.3: first ingest already ran the *current*
                        # engine over whatever body it had, so the row does
                        # not belong in the re-extract queue. Not
                        # `mark_reprocessed()`: a body that arrives later
                        # must still trigger the ordinary body-arrived pass.
                        content_store.mark_extracted_engine_version(
                            pg, item["source_item_id"], settings.engine_version,
                            input_signature=signature)
                    ingested += 1
                except Exception as exc:
                    engine_con.rollback()
                    detail = f"{type(exc).__name__}: {exc}"
                    failures.append(f"{item['source_item_id']}: {detail}")
                    intake.mark_ingested(pg, item["source_item_id"], intake.INGEST_FAILED)
                    intake.record_error(
                        pg, source_id=item["source_id"], collection_run_id=None,
                        kind="INGEST_FAILED", detail=detail,
                    )
                    failed += 1
                    log.exception("ingest failed for source item %s", item["source_item_id"])
        finally:
            engine_con.close()

    return {
        "pending": len(items),
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
        "candidates": candidates,
        "failures": failures[:3],
    }


def _iso_dates(values) -> list[str]:
    """The non-empty dates in a candidate set, as comparable ISO strings."""
    return [str(v) for v in values if v]


# The engine's own evidence_type for a field it read off a poster
# (engine.extractor.IMAGE_OCR). Restated rather than imported, the way
# image_fallback.MIN_TEXT_FOR_CLASSIFICATION_TRUST already restates the
# engine's own constant: this module reaches the engine store through plain
# SQL and does not need the engine importable to answer the question.
IMAGE_OCR_EVIDENCE = "IMAGE_OCR"


def _blocked_body_lost(item: dict[str, Any], post, best_fetched: int) -> bool:
    """Was this blocked item once served a body it no longer holds?

    FETCH_BLOCKED is a fetch outcome, not a statement about what we know.
    Two completely different items wear it:

    * one we were **refused from the start** - no body was ever served, and
      its candidates were built from the very discovery title and snippet
      `_to_raw_post()` still hands the engine today. Re-reading that text
      with a newer classifier is not a downgrade; it is the entire point of
      an engine bump, and refusing it is what left 126 of v0.96.8's own
      corrections stranded in the database.
    * one we **did** fetch once and were refused afterwards. A refusal wipes
      `extracted_text`, so this item's candidates were built from text that
      is simply gone. Whatever the engine now makes of the remaining title is
      a verdict on less evidence, and must never retire the older, better-
      informed one.

    `best_fetched` is `content_store.best_fetched_text_length()`'s answer for
    this item - the append-only fetch log, the only place the difference
    survives. Production, 2026-09-23: exactly six blocked items (the K-TANGO
    643/644/646/647/648/649 group) were ever served a real body, and
    re-extracting three of them without this guard replaced a correct
    `event_date` with NULL - the v0.84.3 regression, reproduced.
    """
    if item.get("acquisition_status") != acquisition.FETCH_BLOCKED:
        return False
    if best_fetched < acquisition.MINIMUM_USEFUL_TEXT:
        return False
    return len(post.body or "") < best_fetched


def _raw_post_key(post) -> str:
    """The engine raw store's key for a post - `database.persist_raw_post()`'s
    own formula, which is the one that decides is_new."""
    ext = post.source_url or hashlib.sha256(
        f"{post.source_id}|{post.title}|{post.published_at}".encode()).hexdigest()
    return f"{post.source_id}|{ext}"


def _refresh_raw_post(engine_con, post_id: int, post) -> None:
    """Make the engine's stored post the one it is about to read (v0.96.42).

    `persist_raw_post()` returns early for a key it holds, so title,
    published_at, raw_json and raw_hash have stayed at their first-ingest
    values through every revision since. Written in the engine's own shape -
    raw_hash is `persist_raw_post()`'s formula - and not committed here: the
    caller's next commit carries it with the body.
    """
    raw_hash = hashlib.sha256(
        f"{post.title}\n{post.body}\n{post.raw_json or ''}".encode("utf-8")).hexdigest()
    engine_con.execute(
        "UPDATE raw_posts SET title=?, published_at=?, raw_json=?, raw_hash=? "
        "WHERE post_id=?",
        (post.title, post.published_at, post.raw_json, raw_hash, post_id),
    )


def reconcile_unsigned(settings: Settings, *, limit: int = 500) -> dict[str, Any]:
    """Sign rows the engine finished before v0.96.42, or send them back.

    Migration 050 records no signature for an existing row - the pass that
    read it never said what it read - and `needing_reprocess()` never treats
    "unknown" as "revised". This decides each one from the only record of
    what the engine actually read, its own raw store, against the input the
    reprocess path builds now (the same `_to_raw_post()`):

    * the same title and body -> signed with today's signature, current;
    * the same body, a different title, and the last pass ran after the
      revision -> that pass read the new title from PostgreSQL (the raw store
      simply never stored it), so the raw store is corrected and the row
      signed. 44 Production rows on 2026-10-19;
    * anything else - the body differs, or the title differs and nothing read
      the item after its revision - went unread: back in the queue
      (`mark_needs_reextract()`), where the ordinary pass re-reads it under
      every protection it has and signs it when it finishes.

    Rows with no raw store entry are left alone: never ingested, nothing to
    compare, and ingest signs them itself. Restart-safe and finite: a signed
    or re-queued row stops matching, so each tick takes new rows, and once
    every row is signed this is one empty query.
    """
    engine_db, RawPostRecord, *_ = _engine(settings)
    counts = {"selected": 0, "signed": 0, "raw_title_refreshed": 0,
              "requeued": 0, "not_ingested": 0, "requeued_ids": []}
    with db.connect(settings, autocommit=True) as pg:
        rows = content_store.unsigned_rows(pg, settings.engine_version, limit=limit)
        counts["selected"] = len(rows)
        if not rows:
            return counts
        detection = _detection_terms_by_source(pg)
        engine_con = _open_engine_store(settings, engine_db)
        try:
            for item in rows:
                source_item_id = item["source_item_id"]
                post = _to_raw_post(RawPostRecord, item, item,
                                    event_terms=detection(item.get("source_id")))
                stored = engine_con.execute(
                    "SELECT post_id, title, body FROM raw_posts WHERE external_key=?",
                    (_raw_post_key(post),),
                ).fetchone()
                if stored is None:
                    counts["not_ingested"] += 1
                    continue
                raw = item.get("raw") or {}
                # ingest_pending() and reprocess_acquired() resolve a missing
                # raw title differently (the item's own title, or the fetched
                # page's), so either is a title the engine was given.
                ingest_title = (raw.get("title") if isinstance(raw, dict) else None) \
                    or item.get("source_item_title") or ""
                same_title = stored["title"] in (post.title, ingest_title)
                same_body = (stored["body"] or "") == (post.body or "")
                read_after = (item.get("reprocessed_at") is not None
                              and item.get("source_collected_at") is not None
                              and item["reprocessed_at"] > item["source_collected_at"])
                if same_body and (same_title or read_after):
                    if not same_title:
                        engine_con.execute("UPDATE raw_posts SET title=? WHERE post_id=?",
                                           (post.title, stored["post_id"]))
                        counts["raw_title_refreshed"] += 1
                    content_store.sign_input(pg, source_item_id, item["input_signature"])
                    counts["signed"] += 1
                else:
                    content_store.mark_needs_reextract(pg, source_item_id)
                    counts["requeued"] += 1
                    counts["requeued_ids"].append(source_item_id)
            engine_con.commit()
        finally:
            engine_con.close()
    counts["requeued_ids"] = counts["requeued_ids"][:20]
    return counts


def freshness(settings: Settings, pg, source_item_id: int) -> dict[str, Any] | None:
    """`content_store.extraction_freshness()` for one item, with the facts the
    reprocess policy itself would consult (v0.96.42).

    Read-only on both stores: `_blocked_body_lost()` and
    `_candidates_used_image_ocr()` are the policy's own tests, asked of the
    same inputs a pass would build, and nothing is written. The engine store
    being unreadable leaves those two facts unknown, never guessed.
    """
    content = content_store.get(pg, source_item_id)
    if content is None:
        return None
    facts = content_store.freshness_inputs(pg, source_item_id)
    body_lost = used_ocr = None
    candidate_ids: list[int] = []
    try:
        _engine_db, RawPostRecord, *_ = _engine(settings)
        with pg.cursor() as cur:
            cur.execute(
                "SELECT i.url, i.source_id, i.published_at, i.title AS source_item_title, "
                "       s.source_key, i.raw FROM source_items i "
                "JOIN sources s ON s.source_id = i.source_id WHERE i.source_item_id = %s",
                (source_item_id,))
            names = [c.name for c in cur.description]
            found = cur.fetchone()
        item = {**content, **dict(zip(names, found))} if found else dict(content)
        post = _to_raw_post(RawPostRecord, item, item)
        body_lost = _blocked_body_lost(
            item, post,
            content_store.best_fetched_text_length(pg, [source_item_id]).get(source_item_id, 0))
        from . import candidates  # local: the console's read-only engine reader

        engine_con = candidates._connect(settings)
        try:
            stored = engine_con.execute(
                "SELECT post_id FROM raw_posts WHERE external_key=?",
                (_raw_post_key(post),)).fetchone()
            if stored is not None:
                candidate_ids = [r[0] for r in engine_con.execute(
                    "SELECT candidate_id FROM event_candidates WHERE post_id=?",
                    (stored["post_id"],)).fetchall()]
            used_ocr = _candidates_used_image_ocr(engine_con, candidate_ids)
        finally:
            engine_con.close()
    except Exception:  # noqa: BLE001 - a diagnostic never fails the page
        log.exception("freshness facts unavailable for source item %s", source_item_id)
    reviewed = False
    if candidate_ids:
        with pg.cursor() as cur:
            cur.execute("SELECT 1 FROM human_review_actions WHERE candidate_id = ANY(%s) "
                        "LIMIT 1", (candidate_ids,))
            reviewed = cur.fetchone() is not None
    result = content_store.extraction_freshness(
        content, settings.engine_version, readable=facts["readable"],
        revised_since_read=facts["revised_since_read"], reviewed=reviewed,
        body_lost=body_lost, used_image_ocr=used_ocr, has_events=facts["has_events"])
    result["source_item_id"] = source_item_id
    result["candidates"] = len(candidate_ids)
    # v0.96.43: which ones, so the intake page can link each to Review.
    result["candidate_ids"] = list(candidate_ids)
    return result


def _candidates_used_image_ocr(engine_con, candidate_ids: list[int]) -> bool:
    """Did a poster, rather than the post's own text, give these candidates a
    field? Then the post's text alone never explained them."""
    if not candidate_ids:
        return False
    marks = ",".join("?" * len(candidate_ids))
    row = engine_con.execute(
        "SELECT 1 FROM evidences WHERE evidence_type = ? "
        f"AND candidate_id IN ({marks}) LIMIT 1",
        (IMAGE_OCR_EVIDENCE, *candidate_ids),
    ).fetchone()
    return row is not None


def _events_of(pg, candidate_ids: list[int]) -> list[tuple[int, int]]:
    """(event_id, candidate_id) for the runtime Events built from these
    candidates - what a re-extraction either keeps or orphans."""
    if not candidate_ids:
        return []
    with pg.cursor() as cur:
        cur.execute(
            "SELECT event_id, candidate_id FROM events WHERE candidate_id = ANY(%s)",
            (list(candidate_ids),),
        )
        return [(int(r[0]), int(r[1])) for r in cur.fetchall()]


# v0.96.53: how each multi-programme re-read paired its candidates, by result key.
_IDENTITY_KEYS = {
    "identity_exact": candidate_identity.MATCH_EXACT,
    "identity_revised": candidate_identity.MATCH_REVISED,
    "identity_new": candidate_identity.NEW_EVENT,
    "identity_removed": candidate_identity.REMOVED,
    "identity_ambiguous": candidate_identity.AMBIGUOUS,
    "identity_conflicting": candidate_identity.CONFLICTING,
}


# v0.96.54: what a review-aware re-read did with a reviewed post's programmes.
REVIEW_AWARE_KEYS = (
    "review_locked_kept",        # EXISTING_HUMAN_LOCKED: untouched
    "review_rejected_kept",      # ...of which REJECTED / DUPLICATE
    "review_unreviewed_reread",  # EXISTING_UNREVIEWED: re-read in place
    "review_unpaired_kept",      # stored, no new reading: kept, never retired here
    "review_new_created",        # GENUINE_NEW_PROGRAMME created
    "review_new_pending",        # new reading refused: PENDING_EVIDENCE
    "review_held",               # AMBIGUOUS / CONFLICTING: nothing written
)
_REFUSED_STATES = ("REJECTED", "DUPLICATE")


def _review_aware_apply(engine_db, engine_con, post_id, existing, events, identity,
                        reviewed, review_states) -> dict[str, Any]:
    """Re-read a post that holds a reviewed candidate without touching a
    person's decision (v0.96.54, behind REVIEW_AWARE_REEXTRACT).

    * A reviewed candidate (any Review action) is never re-read, retired or
      renumbered, paired or not. Its corrections live on `candidate_review_state` and are
      laid over it at normalization, so it publishes what the person decided.
    * An unreviewed candidate the new reading pairs with is re-read in place,
      as on any other post. One it does not pair with is kept: retiring a
      programme from a post a person has worked on is not this pass's call.
    * A new reading is a new programme only when it paired with nothing and
      every stored candidate of the post paired with a reading. It is refused
      (PENDING_EVIDENCE) otherwise, and when it falls on a day a person
      rejected or marked duplicate in this post, or names no day - a rejected
      deadline must not come back under a new title.
    * Any undecided identity (AMBIGUOUS / CONFLICTING) holds the whole post:
      nothing is written.
    """
    counts = dict.fromkeys(REVIEW_AWARE_KEYS, 0)
    if identity["held"]["old"] or identity["held"]["new"]:
        counts["review_held"] = 1
        return {"counts": counts, "created": [], "held": True}
    locked = {row[0] for row in existing if row[0] in reviewed}
    refused_days = {str(row[1])[:10] for row in existing
                    if row[0] in locked and review_states.get(row[0]) in _REFUSED_STATES}
    paired = set(identity["pairs"].values())
    for cid in locked:
        counts["review_locked_kept"] += 1
        if review_states.get(cid) in _REFUSED_STATES:
            counts["review_rejected_kept"] += 1
    for index, cid in sorted(identity["pairs"].items()):
        if cid not in locked:
            engine_db.replace_candidate(engine_con, cid, events[index])
            counts["review_unreviewed_reread"] += 1
    counts["review_unpaired_kept"] = sum(1 for row in existing
                                         if row[0] not in locked and row[0] not in paired)
    # A new reading is only *additional* when every stored programme is
    # accounted for. If one is left over - a person CONFIRMED a class on 10/01
    # and this engine reads it as 09/20 - the new reading may be that very
    # programme on another day, and creating it would publish a second copy
    # beside the decision (items 2295 and 2297 on the 2026-10-24 snapshot).
    accounted = all(row[0] in paired for row in existing)
    created = []
    for index in identity["new"]:
        day = candidate_identity.extracted_fields(events[index])["date"]
        if not accounted or day is None or day in refused_days:
            counts["review_new_pending"] += 1
        else:
            created.append(index)
    if created:
        engine_db.persist_events(engine_con, post_id, [events[i] for i in created])
    counts["review_new_created"] = len(created)
    return {"counts": counts, "created": created, "held": False}


def _empty_reprocess_result(engine_version: str, backlog: dict[str, int]) -> dict[str, Any]:
    return {
        "pending": 0, "selected": 0, "reprocessed": 0, "succeeded": 0,
        "skipped_reviewed": 0, "skipped_blocked": 0, "failed": 0,
        "blocked_selected": 0, "blocked_reconciled": 0,
        "blocked_preserved_input_loss": 0,
        "blocked_preserved_body_lost": 0,
        "blocked_preserved_image_evidence_lost": 0,
        "blocked_preserved_reviewed": 0, "blocked_failed": 0,
        "stale_event_removed": 0,
        "candidates_before": 0, "candidates_after": 0,
        "events_before": 0, "events_after": 0,
        "events_preserved": 0, "events_dropped": 0,
        "newly_dated": 0, "newly_upcoming": 0, "lost_upcoming": 0,
        "multi_event_changed": 0,
        **dict.fromkeys(_IDENTITY_KEYS, 0),
        **dict.fromkeys(REVIEW_AWARE_KEYS, 0),
        "duplicate_decision_kept": 0,
        "engine_version": engine_version,
        "next_after_item_id": None,
        "remaining": backlog["outdated"],
        "stalled": backlog["stalled"],
        "revised_since_read": backlog.get("revised_since_read", 0),
        "failures": [],
    }


def reprocess_acquired(settings: Settings, *, limit: int = 25,
                       force: bool = False,
                       after_item_id: int | None = None) -> dict[str, Any]:
    """Re-extract candidates for items whose original post has now been fetched.

    The v0.75 items were already ingested from a search snippet, so the normal
    PENDING queue will never revisit them. This walks the items whose acquired
    text is newer than their last reprocess, replaces the engine's stored body
    with the article text, and re-runs the engine's own extraction.

    Two safeguards:

    * A candidate a human has already acted on is **not** reprocessed. Review
      state is keyed by candidate_id, and re-extraction issues new ids, so
      reprocessing would silently orphan somebody's decision.
    * The engine's evidence gate is untouched. Supplying a full body lets
      `verify()` see complete core fields; whether that reaches VERIFIED is the
      engine's decision, exactly as it is for any other acquisition path.

    v0.96.3: the ordinary scheduler pass now also selects items whose stored
    extraction came from a *different engine version* than the running one
    (`content_store.needing_reprocess()`, branch 3). That is what makes an
    engine bump finishable in small batches: each success stamps
    `extracted_engine_version`, so the row leaves the queue permanently and
    the next tick necessarily gets different rows. Restarting the process
    changes nothing - the cursor is the DB row, never anything in memory.

    ``force`` re-extracts items already reprocessed, including ones with no
    fetched body at all. It is the admin diagnostic path; page it with
    ``after_item_id``, since a forced selection is ordered by
    `source_item_id` and does not shrink as rows are stamped.

    v0.96.9: a `FETCH_BLOCKED` item is no longer preserved for being
    blocked. The first safeguard above is unchanged; the second now asks
    the question the status was standing in for - is the classification
    input these candidates were built from still here? An item refused
    from the start still holds exactly the discovery text that made them,
    and reconciles normally; one whose fetched body a later refusal wiped
    (`_blocked_body_lost()`), or whose candidates were read off a poster
    this pass cannot see (`_candidates_used_image_ocr()`), keeps them.
    Both protected shapes are stamped, so "deliberately preserved" is a
    finished state and never an unshrinking backlog.
    """
    engine_db, RawPostRecord, process_discovered_post, extract_single, needs_image_fallback = \
        _engine(settings)
    engine_version = settings.engine_version
    today = date.today().isoformat()

    with db.connect(settings, autocommit=True) as pg:
        items = content_store.needing_reprocess(
            pg, limit=limit, force=force,
            engine_version=engine_version, after_item_id=after_item_id,
        )
        detection = _detection_terms_by_source(pg)
        if not items:
            return _empty_reprocess_result(
                engine_version, content_store.reprocess_backlog(pg, engine_version))

        with pg.cursor() as cur:
            cur.execute("SELECT DISTINCT candidate_id FROM human_review_actions")
            reviewed = {row[0] for row in cur.fetchall()}
            # v0.96.54: a person's duplicate answer (MERGE, KEEP_SEPARATE,
            # REVERT) is recorded on the Events, not the candidates. It is a
            # decision about which Event is which, not about the Event's
            # values, so a revision still re-reads such a candidate in place
            # (v0.96.42's contract: the verdict and the id survive, the new
            # title is read). What it must never do is retire one: an Event a
            # person answered about is kept even when the reading no longer
            # pairs with it.
            cur.execute(
                "SELECT DISTINCT e.candidate_id FROM event_duplicate_decisions d "
                "JOIN events e ON e.event_id IN (d.event_id, d.canonical_event_id) "
                "WHERE d.decided_by = 'HUMAN' AND e.candidate_id IS NOT NULL")
            decided = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT candidate_id, review_state FROM candidate_review_state")
            review_states = {row[0]: row[1] for row in cur.fetchall()}

        # v0.96.9: one query for the whole batch, never one per item.
        best_fetched = content_store.best_fetched_text_length(
            pg, [int(i["source_item_id"]) for i in items])

        engine_con = _open_engine_store(settings, engine_db)
        reprocessed = skipped = skipped_blocked = failed = 0
        blocked_selected = sum(
            1 for i in items
            if i.get("acquisition_status") == acquisition.FETCH_BLOCKED)
        blocked_reconciled = blocked_reviewed = blocked_failed = 0
        preserved_body_lost = preserved_image_lost = 0
        stale_event_removed = 0
        before_total = after_total = 0
        events_before = events_preserved = events_dropped = 0
        newly_dated = newly_upcoming = lost_upcoming = multi_event_changed = 0
        identity_counts = dict.fromkeys(_IDENTITY_KEYS.values(), 0)
        review_counts = dict.fromkeys(REVIEW_AWARE_KEYS, 0)
        decision_kept = 0
        failures: list[str] = []
        try:
            for item in items:
                source_item_id = item["source_item_id"]
                blocked = item.get("acquisition_status") == acquisition.FETCH_BLOCKED
                # v0.96.42: the signature of what this selection read, stamped
                # by whichever way the item finishes (see needing_reprocess()).
                signature = item.get("input_signature")
                try:
                    post = _to_raw_post(RawPostRecord, item, item,
                                        event_terms=detection(item.get("source_id")))
                    post_id, _ = engine_db.persist_raw_post(engine_con, post)

                    # v0.96.53: and what each candidate is, so a multi-programme
                    # re-read can keep its ids (candidate_identity.match()).
                    existing = engine_con.execute(
                        "SELECT candidate_id, event_date, name, event_type, "
                        "start_time, end_time, venue FROM event_candidates "
                        "WHERE post_id=?",
                        (post_id,),
                    ).fetchall()
                    existing_ids = [row[0] for row in existing]
                    # v0.96.54: with REVIEW_AWARE_REEXTRACT on, a reviewed post
                    # is read rather than skipped - every reviewed candidate
                    # stays exactly as it is, and only programmes the post newly
                    # states are added (_review_aware_apply). Never for a
                    # blocked item: its input is not this pass's to trust.
                    review_aware = bool(
                        settings.review_aware_reextract and not blocked
                        and any(cid in reviewed for cid in existing_ids))
                    if any(cid in reviewed for cid in existing_ids) and not review_aware:
                        # Stamped, not just skipped: an unstamped skip would
                        # be re-selected first on every following tick and
                        # the rows behind it would never be reached.
                        content_store.mark_reprocessed(
                            pg, source_item_id, engine_version=engine_version,
                            input_signature=signature,
                            outcome=content_store.OUTCOME_KEPT_HUMAN_REVIEWED)
                        skipped += 1
                        if blocked:
                            blocked_reviewed += 1
                        continue

                    # v0.96.9: a blocked item whose stored classification
                    # input is gone is decided here, before the engine is
                    # asked anything - there is no question to put to it. It
                    # is stamped, not merely skipped, for the same reason the
                    # review skip above is: an unstamped row is re-selected
                    # first on every following tick forever, and "protected"
                    # would become indistinguishable from "backlog".
                    if blocked and _blocked_body_lost(
                            item, post, best_fetched.get(source_item_id, 0)):
                        content_store.mark_reprocessed(
                            pg, source_item_id, engine_version=engine_version,
                            input_signature=signature,
                            outcome=content_store.OUTCOME_PRESERVED_BODY_LOST)
                        events_preserved += len(_events_of(pg, existing_ids))
                        skipped_blocked += 1
                        preserved_body_lost += 1
                        continue

                    before_total += len(existing_ids)
                    before_dates = _iso_dates(row[1] for row in existing)
                    item_events = _events_of(pg, existing_ids)
                    events_before += len(item_events)

                    # v0.96.42: and the title, date and collector record it is
                    # re-read with. persist_raw_post() returns early for a URL
                    # it already holds and update_raw_post_acquisition() moves
                    # only the body, so the raw store kept its first-ingest
                    # title through every revision. Before the body update,
                    # whose commit then carries both.
                    _refresh_raw_post(engine_con, post_id, post)
                    # Give the engine the article text in place of the snippet.
                    engine_db.update_raw_post_acquisition(
                        engine_con, post_id,
                        body=post.body, acquisition_quality=post.acquisition_quality,
                    )

                    # v0.84.3: this call site never gathered image_texts at
                    # all - an image-only post (no body, a poster
                    # needing_reprocess() now selects it for) would always
                    # re-extract to nothing and then hit the unconditional
                    # delete below, losing whatever the *original* ingest's
                    # own image fallback had found. Found by that exact
                    # regression on a real K-TANGO event: 647's real,
                    # correctly-OCR'd date was thrown away because this
                    # path never even tried the fallback ingest_pending()
                    # already wires up.
                    image_texts = _gather_image_texts(
                        pg, settings, extract_single, needs_image_fallback,
                        item, item, post,
                    )
                    # v0.84.4: classify() ran on title+body alone, before
                    # image_texts was ever consulted - a genuinely image-only
                    # post (empty body) always classified OTHER and never
                    # reached extraction at all, wiring or no wiring. See
                    # engine.classifier.classify_with_image_evidence().
                    trusted_classification_texts = \
                        image_fallback.gather_trusted_classification_texts(
                            pg, source_item_id,
                        )
                    result = process_discovered_post(
                        engine_con, post, item.get("source_role") or DEFAULT_SOURCE_ROLE,
                        image_texts=image_texts,
                        trusted_classification_texts=trusted_classification_texts,
                    )
                    events = result.get("events") or []

                    # v0.84.3, narrowed by v0.96.9: the second way a blocked
                    # item's classification input can be gone.
                    #
                    # The original guard read FETCH_BLOCKED itself as "we
                    # have less text than whatever made these candidates",
                    # because the only blocked items it could ever be handed
                    # were poster-carrying ones. That is no longer true, and
                    # as a rule about the status it was always too wide: an
                    # item refused from the start has *exactly* the text its
                    # candidates were built from, so zero events really does
                    # mean "the engine has decided this is no longer an
                    # event". `_blocked_body_lost()` above answers that half,
                    # from the fetch log, before the engine is even asked.
                    #
                    # This is the half that can only be answered here: a
                    # candidate whose fields came off a poster was never
                    # explained by the post's own text, so a pass that could
                    # not read the poster this time - the image fetch failed,
                    # the host was down, OCR returned nothing - is reading
                    # less than the candidate was built from even though the
                    # stored text never changed. That is the shape of the
                    # K-TANGO 647 regression this guard was written for, and
                    # the shape it still covers.
                    if not events and existing_ids and blocked \
                            and not image_texts \
                            and not trusted_classification_texts \
                            and _candidates_used_image_ocr(engine_con, existing_ids):
                        content_store.mark_reprocessed(
                            pg, source_item_id, engine_version=engine_version,
                            input_signature=signature,
                            outcome=content_store.OUTCOME_PRESERVED_IMAGE_EVIDENCE_LOST)
                        events_preserved += len(item_events)
                        skipped_blocked += 1
                        preserved_image_lost += 1
                        continue

                    after_dates = _iso_dates(ev.date for ev in events)
                    if after_dates and not before_dates:
                        newly_dated += 1
                    before_upcoming = any(d >= today for d in before_dates)
                    after_upcoming = any(d >= today for d in after_dates)
                    if after_upcoming and not before_upcoming:
                        newly_upcoming += 1
                    if before_upcoming and not after_upcoming:
                        lost_upcoming += 1
                    if len(events) != len(existing_ids):
                        multi_event_changed += 1

                    # v0.96.0: the common shape - one candidate before, one
                    # after - is re-read *into the same candidate_id*, so the
                    # Event the runtime already built from it keeps its id
                    # when the Daum body arrives with the venue and time the
                    # snippet lacked (Section 16: better information makes
                    # the Event more accurate, never a different Event).
                    if len(existing_ids) == 1 and len(events) == 1 and not review_aware \
                            and hasattr(engine_db, "replace_candidate"):
                        engine_db.replace_candidate(engine_con, existing_ids[0], events[0])
                        used = {
                            e.inference for e in events[0].evidences
                            if e.evidence_type == "IMAGE_OCR" and e.inference
                        }
                        if used:
                            image_fallback.mark_used_as_fallback(pg, source_item_id, used)
                        after_total += 1
                        events_preserved += len(item_events)
                        engine_con.commit()
                        content_store.mark_reprocessed(
                            pg, source_item_id, engine_version=engine_version,
                            input_signature=signature,
                            outcome=content_store.OUTCOME_EXTRACTED)
                        reprocessed += 1
                        if blocked:
                            blocked_reconciled += 1
                        continue

                    # Re-read this post into whatever the current engine now
                    # makes of it -- including nothing.
                    #
                    # Guarding the delete on `events` meant a post that stopped
                    # being an event kept the candidate it used to have. A rule
                    # correction could then never take effect: the engine would
                    # say "this is a lesson" and the old event would sit there,
                    # normalised and listed, forever. That still holds for a
                    # real fetch (FULL/PARTIAL) - only a blocked one, handled
                    # above, is exempted.
                    #
                    # v0.96.53: a programme the engine still reads is re-read
                    # *into its own candidate*, as the 1->1 shape above always
                    # was, so its Event keeps its id. Before, every candidate
                    # of a multi-programme post was deleted and inserted afresh
                    # - 95 of the 99 ids the v0.96.52 ENGINE 1.17 probe moved
                    # were the same date under the same title. Pairing is by
                    # what each programme is, never its position, and a key
                    # two candidates share is never guessed at
                    # (candidate_identity.match()).
                    #
                    # Candidates a person has reviewed are never reached here;
                    # that check runs above and skips the item entirely.
                    identity = candidate_identity.match(
                        ((row[0], candidate_identity.stored_fields(row)) for row in existing),
                        [candidate_identity.extracted_fields(ev) for ev in events],
                    )
                    for kind, n in identity["counts"].items():
                        identity_counts[kind] += n
                    if review_aware:
                        outcome = _review_aware_apply(
                            engine_db, engine_con, post_id, existing, events, identity,
                            reviewed, review_states)
                        for key, n in outcome["counts"].items():
                            review_counts[key] += n
                        if outcome["created"]:
                            used = {
                                e.inference
                                for i in outcome["created"] for e in events[i].evidences
                                if e.evidence_type == "IMAGE_OCR" and e.inference
                            }
                            if used:
                                image_fallback.mark_used_as_fallback(pg, source_item_id, used)
                        kept = set(existing_ids)
                        events_preserved += sum(1 for _, cid in item_events if cid in kept)
                        after_total += len(existing_ids) + len(outcome["created"])
                        engine_con.commit()
                        content_store.mark_reprocessed(
                            pg, source_item_id, engine_version=engine_version,
                            input_signature=signature,
                            outcome=(content_store.OUTCOME_KEPT_HUMAN_REVIEWED
                                     if outcome["held"] else content_store.OUTCOME_EXTRACTED))
                        reprocessed += 1
                        continue
                    if identity["held"]["old"] or identity["held"]["new"]:
                        log.warning("re-extract of source item %s: identity not decided "
                                    "for candidates %s (%s new)", source_item_id,
                                    sorted(identity["held"]["old"]),
                                    len(identity["held"]["new"]))
                    for index, candidate_id in sorted(identity["pairs"].items()):
                        engine_db.replace_candidate(engine_con, candidate_id, events[index])
                    retired = [cid for cid in identity["removed"] if cid not in decided]
                    decision_kept += len(identity["removed"]) - len(retired)
                    for candidate_id in retired:
                        engine_con.execute(
                            "DELETE FROM evidences WHERE candidate_id=?", (candidate_id,)
                        )
                        engine_con.execute(
                            "DELETE FROM event_candidates WHERE candidate_id=?",
                            (candidate_id,),
                        )
                    if identity["new"]:
                        engine_db.persist_events(
                            engine_con, post_id, [events[i] for i in identity["new"]])
                    if events:
                        used = {
                            e.inference
                            for ev in events for e in ev.evidences
                            if e.evidence_type == "IMAGE_OCR" and e.inference
                        }
                        if used:
                            image_fallback.mark_used_as_fallback(pg, source_item_id, used)
                    after_total += len(events)
                    # The candidates no new programme claimed are gone, so
                    # normalization's own orphan pass will retire their Event
                    # rows. Counted rather than prevented: forcing an id to
                    # survive a genuine change of programme is what the
                    # duplicate/canonical machinery exists to decide, not this
                    # loop.
                    kept = set(identity["pairs"].values()) | (set(existing_ids) - set(retired))
                    item_kept = sum(1 for _, cid in item_events if cid in kept)
                    events_preserved += item_kept
                    events_dropped += len(item_events) - item_kept
                    if not events:
                        # An Event the current engine no longer stands
                        # behind, retired from input it could read -
                        # v0.96.9's whole reason for existing, and the
                        # number a rollout of it is watched on.
                        stale_event_removed += len(item_events) - item_kept
                    engine_con.commit()
                    content_store.mark_reprocessed(
                        pg, source_item_id, engine_version=engine_version,
                        input_signature=signature,
                        outcome=content_store.OUTCOME_EXTRACTED)
                    reprocessed += 1
                    if blocked:
                        blocked_reconciled += 1
                except Exception as exc:
                    engine_con.rollback()
                    failed += 1
                    if blocked:
                        blocked_failed += 1
                    detail = f"{type(exc).__name__}: {exc}"
                    failures.append(f"{source_item_id}: {detail}")
                    # Count the failure on the row itself so the queue can
                    # step over it after a few tries instead of re-selecting
                    # the same broken item forever - and so the reason stays
                    # readable afterwards rather than only in a log line.
                    try:
                        content_store.record_reprocess_failure(pg, source_item_id, detail)
                    except Exception:  # noqa: BLE001 - never mask the real failure
                        log.exception("could not record reprocess failure for %s",
                                      source_item_id)
                    log.exception("reprocess failed for source item %s", source_item_id)
        finally:
            engine_con.close()

        backlog = content_store.reprocess_backlog(pg, engine_version)

    return {
        # `pending` is what the scheduler has always reported; `selected` is
        # the same number under the name the v0.96.3 rollout measures with.
        "pending": len(items),
        "selected": len(items),
        "reprocessed": reprocessed,
        "succeeded": reprocessed,
        "skipped_reviewed": skipped,
        "skipped_blocked": skipped_blocked,
        # v0.96.9: the blocked population on its own terms. `selected`
        # minus the four outcomes below is always zero, so a tick that
        # neither reconciled nor protected a blocked row is visible as
        # such instead of hiding inside the totals.
        "blocked_selected": blocked_selected,
        "blocked_reconciled": blocked_reconciled,
        "blocked_preserved_input_loss": preserved_body_lost + preserved_image_lost,
        "blocked_preserved_body_lost": preserved_body_lost,
        "blocked_preserved_image_evidence_lost": preserved_image_lost,
        "blocked_preserved_reviewed": blocked_reviewed,
        "blocked_failed": blocked_failed,
        "stale_event_removed": stale_event_removed,
        "failed": failed,
        "candidates_before": before_total,
        "candidates_after": after_total,
        "events_before": events_before,
        "events_after": events_preserved,
        "events_preserved": events_preserved,
        "events_dropped": events_dropped,
        "newly_dated": newly_dated,
        "newly_upcoming": newly_upcoming,
        "lost_upcoming": lost_upcoming,
        "multi_event_changed": multi_event_changed,
        **{name: identity_counts[kind] for name, kind in _IDENTITY_KEYS.items()},
        **review_counts,
        "duplicate_decision_kept": decision_kept,
        "engine_version": engine_version,
        # Where a forced pass got to, so the next call starts after it. The
        # incremental pass ignores this: its cursor is the stamped row.
        "next_after_item_id": max(int(i["source_item_id"]) for i in items),
        "remaining": backlog["outdated"],
        "stalled": backlog["stalled"],
        "revised_since_read": backlog.get("revised_since_read", 0),
        "failures": failures[:3],
    }
