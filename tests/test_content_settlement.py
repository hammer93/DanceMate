"""v0.82.2: FETCHED_FULL content settlement, end to end.

`tests/test_intake.py`'s own settlement section already proves the
structural exclusion (a settled item is never selected by
`content_store.mark_pending()`/`due_for_acquisition()`) at the intake layer
directly. This file proves the same guarantee holds across the *whole*
pipeline a real collection cycle actually runs: discover -> intake ->
engine-ingest -> (a generic acquisition/reprocess cycle that, before this
fix, silently degraded the item) -> normalize. The invariant under test:

    a source item stored with acquisition_quality=FETCHED_FULL keeps its
    event alive across that whole cycle - candidate/event count does not
    erode.

Needs a real, isolated Information Engine SQLite (never the repository's
own committed one) alongside the `pg` fixture, so both skip together
whenever either is unavailable.
"""

from __future__ import annotations

import pytest

from runtime import content_store, intake, sources


@pytest.fixture
def isolated_engine_settings(env, tmp_path, monkeypatch):
    """A fresh, disposable engine SQLite - never the repo's own committed
    one, and never the live board's."""
    from runtime.config import load_settings

    monkeypatch.setenv("ENGINE_DATA_DIR", str(tmp_path / "engine-data"))
    settings = load_settings()
    try:
        from runtime.engine_ingest import _engine
        _engine(settings)
    except Exception as exc:  # pragma: no cover - depends on deployment
        pytest.skip(f"Information Engine not importable: {exc}")
    return settings


@pytest.fixture
def source(pg, unique):
    return sources.create_source(
        pg, source_key=f"SRC-SETTLE-{unique}", name="Settlement test",
        platform="WEB", source_role="AGGREGATOR", queries=[],
    )


def _full_item(unique, **overrides) -> intake.RawItem:
    payload = {
        "external_id": f"https://example.test/settle/{unique}",
        "url": f"https://example.test/settle/{unique}",
        "title": f"밀롱가 {unique}",
        "body": f"2026년 9월 12일 시간: 19:00~23:00 장소: PISTA 지역: 서울",
        "published_at": None,
        "raw": {"platform": "WEB", "acquisition_quality": "FETCHED_FULL"},
    }
    payload.update(overrides)
    return intake.RawItem(**payload)


def _event_count_for(pg, source_id) -> int:
    with pg.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM events e "
            "JOIN source_items si ON si.source_item_id = e.source_item_id "
            "WHERE si.source_id = %s",
            (source_id,),
        )
        return cur.fetchone()[0]


def test_a_settled_item_survives_ingest_reprocess_and_normalize(
    pg, source, unique, isolated_engine_settings,
):
    from runtime import engine_ingest, normalization

    settings = isolated_engine_settings

    assert intake.store_item(pg, source["source_id"], _full_item(unique)) == "NEW"
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    assert content_store.get(pg, item_id)["acquisition_status"] == "FETCHED_FULL"

    # First engine-ingest pass: exactly what a real collection cycle does next.
    result = engine_ingest.ingest_pending(settings, limit=10)
    assert result["failed"] == 0
    normalization.normalize_all(settings)
    before = _event_count_for(pg, source["source_id"])
    assert before == 1, "the settled item must produce exactly one live event"

    # Simulate one full generic acquisition/reprocess cycle - the exact
    # sequence that used to degrade an already-complete body.
    with pg.cursor() as cur:
        cur.execute(
            "SELECT i.source_item_id FROM source_items i "
            "LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
            "WHERE i.url IS NOT NULL "
            "  AND (c.source_item_id IS NULL OR c.acquisition_status = %s)",
            (content_store.acquisition.METADATA_ONLY,),
        )
        newly = [row[0] for row in cur.fetchall()]
    for sid in newly:
        content_store.ensure_row(pg, sid)
    queued = content_store.mark_pending(pg, newly)
    assert item_id not in newly or queued == 0, (
        "a settled item must never be queued by the generic acquisition sweep"
    )
    due = [d["source_item_id"] for d in content_store.due_for_acquisition(pg, limit=1000)]
    assert item_id not in due

    reprocessed = engine_ingest.reprocess_acquired(settings)
    assert reprocessed["reprocessed"] == 0, (
        "nothing should be eligible for reprocess: engine-ingest's own first "
        "pass already read the correct, settled body"
    )
    normalization.normalize_all(settings)

    after = _event_count_for(pg, source["source_id"])
    assert after == before == 1, "the event must not be eroded by a routine cycle"

    settled = content_store.get(pg, item_id)
    assert settled["acquisition_status"] == "FETCHED_FULL"
    assert "PISTA" in settled["extracted_text"]


def test_two_settled_items_across_two_simulated_cycles_stay_stable(
    pg, source, unique, isolated_engine_settings,
):
    """Section 45/46's own stability requirement: no large, unexplained
    event-count drop across repeated cycles."""
    from runtime import engine_ingest, normalization

    settings = isolated_engine_settings

    for suffix in ("a", "b"):
        intake.store_item(
            pg, source["source_id"], _full_item(f"{unique}{suffix}",
                external_id=f"https://example.test/settle/{unique}{suffix}",
                url=f"https://example.test/settle/{unique}{suffix}"),
        )
    engine_ingest.ingest_pending(settings, limit=10)
    normalization.normalize_all(settings)
    counts = [_event_count_for(pg, source["source_id"])]

    for _ in range(2):
        with pg.cursor() as cur:
            cur.execute(
                "SELECT i.source_item_id FROM source_items i "
                "LEFT JOIN source_item_content c ON c.source_item_id = i.source_item_id "
                "WHERE i.url IS NOT NULL "
                "  AND (c.source_item_id IS NULL OR c.acquisition_status = %s)",
                (content_store.acquisition.METADATA_ONLY,),
            )
            newly = [row[0] for row in cur.fetchall()]
        for sid in newly:
            content_store.ensure_row(pg, sid)
        content_store.mark_pending(pg, newly)
        engine_ingest.reprocess_acquired(settings)
        normalization.normalize_all(settings)
        counts.append(_event_count_for(pg, source["source_id"]))

    assert counts == [2, 2, 2], f"event count eroded across cycles: {counts}"
