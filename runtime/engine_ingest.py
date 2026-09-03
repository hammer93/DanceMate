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

from . import db, intake
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


def _to_raw_post(RawPostRecord, item: dict[str, Any]):
    """Rebuild the engine's RawPostRecord from a stored source item."""
    raw = item.get("raw") or {}
    if isinstance(raw, str):
        import json  # noqa: PLC0415

        raw = json.loads(raw)
    return RawPostRecord(
        source_id=raw.get("source_id") or item.get("source_key"),
        platform=raw.get("platform") or item.get("platform"),
        source_url=raw.get("source_url") or item.get("url") or "",
        title=raw.get("title") or item.get("title") or "",
        body=raw.get("body") or item.get("body") or "",
        published_at=raw.get("published_at"),
        cafe_name=raw.get("cafe_name"),
        thumbnail_url=raw.get("thumbnail_url"),
        discovery_query=raw.get("discovery_query"),
        acquisition_quality=raw.get("acquisition_quality") or "METADATA_ONLY",
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
                    post = _to_raw_post(RawPostRecord, item)
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
