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

import logging
import sys
from datetime import date
from typing import Any

from . import acquisition, content_store, db, image_fallback, intake
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
                            pg, item["source_item_id"], settings.engine_version)
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
        "engine_version": engine_version,
        "next_after_item_id": None,
        "remaining": backlog["outdated"],
        "stalled": backlog["stalled"],
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
        failures: list[str] = []
        try:
            for item in items:
                source_item_id = item["source_item_id"]
                blocked = item.get("acquisition_status") == acquisition.FETCH_BLOCKED
                try:
                    post = _to_raw_post(RawPostRecord, item, item,
                                        event_terms=detection(item.get("source_id")))
                    post_id, _ = engine_db.persist_raw_post(engine_con, post)

                    existing = engine_con.execute(
                        "SELECT candidate_id, event_date FROM event_candidates "
                        "WHERE post_id=?",
                        (post_id,),
                    ).fetchall()
                    existing_ids = [row[0] for row in existing]
                    if any(cid in reviewed for cid in existing_ids):
                        # Stamped, not just skipped: an unstamped skip would
                        # be re-selected first on every following tick and
                        # the rows behind it would never be reached.
                        content_store.mark_reprocessed(
                            pg, source_item_id, engine_version=engine_version)
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
                            pg, source_item_id, engine_version=engine_version)
                        events_preserved += len(_events_of(pg, existing_ids))
                        skipped_blocked += 1
                        preserved_body_lost += 1
                        continue

                    before_total += len(existing_ids)
                    before_dates = _iso_dates(row[1] for row in existing)
                    item_events = _events_of(pg, existing_ids)
                    events_before += len(item_events)

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
                            pg, source_item_id, engine_version=engine_version)
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
                    if len(existing_ids) == 1 and len(events) == 1 \
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
                            pg, source_item_id, engine_version=engine_version)
                        reprocessed += 1
                        if blocked:
                            blocked_reconciled += 1
                        continue

                    # Replace this post's candidates with whatever the current
                    # engine now makes of it -- including nothing.
                    #
                    # Guarding the delete on `events` meant a post that stopped
                    # being an event kept the candidate it used to have. A rule
                    # correction could then never take effect: the engine would
                    # say "this is a lesson" and the old event would sit there,
                    # normalised and listed, forever. That still holds for a
                    # real fetch (FULL/PARTIAL) - only a blocked one, handled
                    # above, is exempted.
                    #
                    # Candidates a person has reviewed are never reached here;
                    # that check runs above and skips the item entirely.
                    for candidate_id in existing_ids:
                        engine_con.execute(
                            "DELETE FROM evidences WHERE candidate_id=?", (candidate_id,)
                        )
                    engine_con.execute(
                        "DELETE FROM event_candidates WHERE post_id=?", (post_id,)
                    )
                    if events:
                        engine_db.persist_events(engine_con, post_id, events)
                        used = {
                            e.inference
                            for ev in events for e in ev.evidences
                            if e.evidence_type == "IMAGE_OCR" and e.inference
                        }
                        if used:
                            image_fallback.mark_used_as_fallback(pg, source_item_id, used)
                    after_total += len(events)
                    # The candidate ids these Events were built from are gone,
                    # so normalization's own orphan pass will retire the Event
                    # rows. Counted rather than prevented: forcing an id to
                    # survive a genuine 1->N cardinality change is what the
                    # duplicate/canonical machinery exists to decide, not this
                    # loop. The 1->1 shape above never reaches here.
                    events_dropped += len(item_events)
                    if not events:
                        # An Event the current engine no longer stands
                        # behind, retired from input it could read -
                        # v0.96.9's whole reason for existing, and the
                        # number a rollout of it is watched on.
                        stale_event_removed += len(item_events)
                    engine_con.commit()
                    content_store.mark_reprocessed(
                        pg, source_item_id, engine_version=engine_version)
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
        "engine_version": engine_version,
        # Where a forced pass got to, so the next call starts after it. The
        # incremental pass ignores this: its cursor is the stamped row.
        "next_after_item_id": max(int(i["source_item_id"]) for i in items),
        "remaining": backlog["outdated"],
        "stalled": backlog["stalled"],
        "failures": failures[:3],
    }
