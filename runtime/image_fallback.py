"""Fetch, OCR and cache a post's attached images for field fallback (v0.81.3).

`runtime.image_fetch` discovers and safely fetches image bytes; `runtime.ocr`
reads text out of them; this module is the Postgres-backed orchestration
between them and `engine.extract_with_image_fallback()`, which is the only
thing that decides whether any of it actually gets *used*. Every image this
module ever fetches or OCRs is recorded in `source_item_image`, whether or
not it ends up contributing a field - that table is the audit trail Section
30's Review UI reads from.

Nothing here is skipped because it might be slow: the per-item image cap
(`image_fetch.MAX_IMAGES_PER_ITEM`) and the fact that a caller only invokes
this when the body left a field missing (`runtime.engine_ingest`) are what
keep the cost bounded.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from . import image_fetch, ocr
from .acquisition import redact_personal_data
from .config import Settings

log = logging.getLogger("dancemate.image_fallback")


def _rows(cur) -> list[dict[str, Any]]:
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _row(cur) -> dict[str, Any] | None:
    columns = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(columns, row))


def _classify_media(settings: Settings, *, url: str, surrounding_text: str,
                     width: int | None, height: int | None):
    """engine.media_classifier.classify_media(), imported the same way
    engine_ingest._engine() reaches the engine package - a lazy sys.path
    insert, so this module carries no import-time dependency on it."""
    root = str(settings.engine_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    from src.media_classifier import classify_media  # noqa: PLC0415

    return classify_media(url=url, surrounding_text=surrounding_text,
                          image_width=width, image_height=height)


def _get_by_url(pg, source_item_id: int, url: str) -> dict[str, Any] | None:
    with pg.cursor() as cur:
        cur.execute(
            "SELECT * FROM source_item_image WHERE source_item_id = %s AND image_url = %s",
            (source_item_id, url),
        )
        return _row(cur)


def _get_by_hash(pg, content_hash: str) -> dict[str, Any] | None:
    """Another source_item's already-successful OCR of the same bytes - the
    same poster reposted across several cafes, most often."""
    with pg.cursor() as cur:
        cur.execute(
            "SELECT * FROM source_item_image WHERE content_hash = %s "
            "AND ocr_status = %s ORDER BY processed_at DESC LIMIT 1",
            (content_hash, ocr.STATUS_SUCCESS),
        )
        return _row(cur)


def _upsert(pg, source_item_id: int, url: str, index: int, fields: dict[str, Any]) -> None:
    columns = ["source_item_id", "image_url", "image_index", *fields.keys()]
    values = [source_item_id, url, index, *fields.values()]
    placeholders = ", ".join(["%s"] * len(values))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in fields)
    with pg.cursor() as cur:
        cur.execute(
            f"INSERT INTO source_item_image ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            "ON CONFLICT (source_item_id, image_url) DO UPDATE SET "
            f"{updates}",
            values,
        )


def _process_one(pg, settings: Settings, source_item_id: int, url: str,
                 index: int, surrounding_text: str) -> str | None:
    """One image, fetched/OCR'd/cached/redacted/recorded. Returns usable OCR
    text, or None. Exceptions from image_fetch/ocr are never raised past
    fetch_image/run_ocr themselves (both return a status instead) - anything
    that does escape here is a real bug, not an expected failure mode, and is
    left to the caller's own broad guard."""
    existing = _get_by_url(pg, source_item_id, url)
    if existing is not None and existing.get("ocr_status") is not None:
        return existing["ocr_text"] if existing["ocr_status"] == ocr.STATUS_SUCCESS else None

    fetched = image_fetch.fetch_image(url)
    now = datetime.now(timezone.utc)
    if not fetched.ok:
        _upsert(pg, source_item_id, url, index, {
            "fetch_status": fetched.status, "processed_at": now,
        })
        return None

    content_hash = hashlib.sha256(fetched.data).hexdigest()
    cached = _get_by_hash(pg, content_hash)
    if cached is not None:
        text, redacted = redact_personal_data(cached["ocr_text"] or "")
        _upsert(pg, source_item_id, url, index, {
            "fetch_status": "FETCHED", "content_hash": content_hash,
            "ocr_status": ocr.STATUS_SUCCESS, "ocr_engine": cached.get("ocr_engine"),
            "ocr_language": cached.get("ocr_language"),
            "ocr_confidence": cached.get("ocr_confidence"),
            "ocr_text": text, "redacted_spans": redacted, "processed_at": now,
        })
        return text or None

    decision = _classify_media(settings, url=url, surrounding_text=surrounding_text,
                               width=None, height=None)
    result = ocr.run_ocr(fetched.data)
    text, redacted = redact_personal_data(result.text or "")
    _upsert(pg, source_item_id, url, index, {
        "fetch_status": "FETCHED", "content_hash": content_hash,
        "media_class": decision.media_class, "media_class_reason": decision.reason,
        "width": result.width, "height": result.height,
        "ocr_status": result.status, "ocr_engine": "tesseract",
        "ocr_language": ocr.LANGUAGES, "ocr_confidence": result.confidence,
        "ocr_text": text, "redacted_spans": redacted, "processed_at": now,
    })
    return text if result.ok and text else None


def gather_image_texts(
    pg, settings: Settings, *, source_item_id: int, candidate_urls: list[str],
    surrounding_text: str = "",
) -> list[tuple[str, str]]:
    """Already-OCR'd, PII-redacted ``(image_url, text)`` pairs for this item,
    in priority order - ready to hand straight to
    ``engine.extract_with_image_fallback()``'s ``image_texts``.

    Never raises: one image's fetch/OCR failure is recorded and skipped, not
    bubbled up - a poster that fails to OCR must never fail the item's own
    ingestion (Section 39).
    """
    selected = image_fetch.select_candidate_urls(candidate_urls)
    results: list[tuple[str, str]] = []
    for index, url in enumerate(selected):
        try:
            text = _process_one(pg, settings, source_item_id, url, index, surrounding_text)
        except Exception as exc:
            log.warning("image OCR failed for item %s (%s): %s", source_item_id, url, exc)
            continue
        if text:
            results.append((url, text))
    return results


def mark_used_as_fallback(pg, source_item_id: int, used_urls: set[str]) -> None:
    """Record which images `extract_with_image_fallback()` actually drew a
    field from - the engine decides this, only after extraction runs, so it
    is always a separate call from `gather_image_texts()`."""
    if not used_urls:
        return
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE source_item_image SET used_as_fallback = TRUE "
            "WHERE source_item_id = %s AND image_url = ANY(%s)",
            (source_item_id, list(used_urls)),
        )


def images_for_review(pg, source_item_id: int) -> list[dict[str, Any]]:
    """Every image considered for this item, for the Review detail page."""
    with pg.cursor() as cur:
        cur.execute(
            "SELECT * FROM source_item_image WHERE source_item_id = %s "
            "ORDER BY image_index", (source_item_id,),
        )
        return _rows(cur)
