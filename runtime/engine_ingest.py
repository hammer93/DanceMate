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
from typing import Any

from . import acquisition, content_store, db, intake
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
    except ImportError as exc:  # pragma: no cover - depends on deployment
        raise EngineIngestUnavailable(f"engine package not importable: {exc}") from exc
    return engine_db, RawPostRecord, process_discovered_post


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


def _to_raw_post(RawPostRecord, item: dict[str, Any], content: dict[str, Any] | None = None):
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
        title=raw.get("title") or item.get("title") or "",
        body=body,
        published_at=raw.get("published_at"),
        cafe_name=raw.get("cafe_name"),
        thumbnail_url=raw.get("thumbnail_url"),
        discovery_query=raw.get("discovery_query"),
        acquisition_quality=quality,
        raw_json=raw.get("raw_json"),
    )


def ingest_pending(settings: Settings, *, limit: int = 50) -> dict[str, Any]:
    """Feed pending source items into the Information Engine.

    Returns counts rather than raising: the scheduler records the summary and
    carries on. Individual item failures are marked FAILED and reported.
    """
    engine_db, RawPostRecord, process_discovered_post = _engine(settings)

    with db.connect(settings, autocommit=True) as pg:
        items = intake.pending_items(pg, limit=limit)
        if not items:
            return {"pending": 0, "ingested": 0, "skipped": 0, "failed": 0, "candidates": 0}

        engine_con = _open_engine_store(settings, engine_db)
        ingested = skipped = failed = candidates = 0
        failures: list[str] = []
        try:
            for item in items:
                try:
                    content = content_store.get(pg, item["source_item_id"])
                    post = _to_raw_post(RawPostRecord, item, content)
                    if not post.source_url or not post.title:
                        intake.mark_ingested(pg, item["source_item_id"], intake.INGEST_SKIPPED)
                        skipped += 1
                        continue

                    post_id, is_new = engine_db.persist_raw_post(engine_con, post)
                    if is_new:
                        result = process_discovered_post(
                            engine_con, post,
                            item.get("source_role") or DEFAULT_SOURCE_ROLE,
                        )
                        events = result.get("events") or []
                        if events:
                            engine_db.persist_events(engine_con, post_id, events)
                            candidates += len(events)
                    engine_con.commit()
                    intake.mark_ingested(pg, item["source_item_id"], intake.INGEST_DONE)
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


def reprocess_acquired(settings: Settings, *, limit: int = 25,
                       force: bool = False) -> dict[str, Any]:
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

    ``force`` re-extracts items already reprocessed. Needed when the extractor
    itself changes -- an engine version bump leaves every stored candidate
    holding values the current engine would no longer produce. Both safeguards
    above still apply, so a forced pass cannot overwrite anyone's review.
    """
    engine_db, RawPostRecord, process_discovered_post = _engine(settings)

    with db.connect(settings, autocommit=True) as pg:
        items = content_store.needing_reprocess(pg, limit=limit, force=force)
        if not items:
            return {"pending": 0, "reprocessed": 0, "skipped_reviewed": 0,
                    "candidates_before": 0, "candidates_after": 0, "failed": 0}

        with pg.cursor() as cur:
            cur.execute("SELECT DISTINCT candidate_id FROM human_review_actions")
            reviewed = {row[0] for row in cur.fetchall()}

        engine_con = _open_engine_store(settings, engine_db)
        reprocessed = skipped = failed = 0
        before_total = after_total = 0
        failures: list[str] = []
        try:
            for item in items:
                source_item_id = item["source_item_id"]
                try:
                    post = _to_raw_post(RawPostRecord, item, item)
                    post_id, _ = engine_db.persist_raw_post(engine_con, post)

                    existing = engine_con.execute(
                        "SELECT candidate_id FROM event_candidates WHERE post_id=?",
                        (post_id,),
                    ).fetchall()
                    existing_ids = [row[0] for row in existing]
                    if any(cid in reviewed for cid in existing_ids):
                        content_store.mark_reprocessed(pg, source_item_id)
                        skipped += 1
                        continue

                    before_total += len(existing_ids)

                    # Give the engine the article text in place of the snippet.
                    engine_db.update_raw_post_acquisition(
                        engine_con, post_id,
                        body=post.body, acquisition_quality=post.acquisition_quality,
                    )

                    result = process_discovered_post(
                        engine_con, post, item.get("source_role") or DEFAULT_SOURCE_ROLE
                    )
                    events = result.get("events") or []
                    # Replace this post's candidates with whatever the current
                    # engine now makes of it -- including nothing.
                    #
                    # Guarding the delete on `events` meant a post that stopped
                    # being an event kept the candidate it used to have. A rule
                    # correction could then never take effect: the engine would
                    # say "this is a lesson" and the old event would sit there,
                    # normalised and listed, forever.
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
                    after_total += len(events)
                    engine_con.commit()
                    content_store.mark_reprocessed(pg, source_item_id)
                    reprocessed += 1
                except Exception as exc:
                    engine_con.rollback()
                    failed += 1
                    failures.append(f"{source_item_id}: {type(exc).__name__}: {exc}")
                    log.exception("reprocess failed for source item %s", source_item_id)
        finally:
            engine_con.close()

    return {
        "pending": len(items),
        "reprocessed": reprocessed,
        "skipped_reviewed": skipped,
        "candidates_before": before_total,
        "candidates_after": after_total,
        "failed": failed,
        "failures": failures[:3],
    }
