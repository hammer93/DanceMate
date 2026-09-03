"""Raw source intake: collection runs, deduplication and the ingest queue."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime import intake, sources


def _item(**overrides) -> intake.RawItem:
    payload = {
        "external_id": "https://cafe.daum.net/6uP/5HTC/1",
        "url": "https://cafe.daum.net/6uP/5HTC/1",
        "title": "8/22 밀롱가",
        "body": "PISTA 20:00",
        "published_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "raw": {"platform": "DAUM_CAFE"},
    }
    payload.update(overrides)
    return intake.RawItem(**payload)


# --- content hashing (pure, always runs) ------------------------------------

def test_the_same_content_hashes_the_same():
    assert _item().content_hash() == _item().content_hash()


def test_an_edited_title_changes_the_hash():
    assert _item().content_hash() != _item(title="8/22 밀롱가 (취소)").content_hash()


def test_an_edited_body_changes_the_hash():
    assert _item().content_hash() != _item(body="PISTA 21:00").content_hash()


def test_the_hash_ignores_metadata_we_add_ourselves():
    """Otherwise re-collecting an unchanged post would never be a duplicate."""
    assert _item(raw={"anything": "else"}).content_hash() == _item().content_hash()


# --- database-backed behaviour ----------------------------------------------

@pytest.fixture
def source(pg, unique):
    return sources.create_source(
        pg, source_key=f"SRC-I-{unique}", name="Intake test", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )


def test_a_new_item_is_stored(pg, source):
    assert intake.store_item(pg, source["source_id"], _item()) == "NEW"
    stored = intake.recent_items(pg, source_id=source["source_id"])
    assert len(stored) == 1
    assert stored[0]["ingest_state"] == intake.INGEST_PENDING


def test_recollecting_an_unchanged_item_is_a_duplicate(pg, source):
    intake.store_item(pg, source["source_id"], _item())
    assert intake.store_item(pg, source["source_id"], _item()) == "DUPLICATE"
    assert len(intake.recent_items(pg, source_id=source["source_id"])) == 1


def test_an_edited_item_is_a_revision_and_is_requeued(pg, source):
    intake.store_item(pg, source["source_id"], _item())
    intake.mark_ingested(pg, intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"])

    assert intake.store_item(pg, source["source_id"], _item(title="취소되었습니다")) == "REVISED"
    stored = intake.recent_items(pg, source_id=source["source_id"])
    assert len(stored) == 1, "a revision updates the row rather than adding one"
    assert stored[0]["title"] == "취소되었습니다"
    assert stored[0]["ingest_state"] == intake.INGEST_PENDING, "the engine must see the edit"


def test_the_same_url_from_two_sources_is_two_items(pg, unique):
    """Dedup is per source: two boards can carry the same post."""
    first = sources.create_source(
        pg, source_key=f"SRC-A-{unique}", name="A", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    second = sources.create_source(
        pg, source_key=f"SRC-B-{unique}", name="B", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    assert intake.store_item(pg, first["source_id"], _item()) == "NEW"
    assert intake.store_item(pg, second["source_id"], _item()) == "NEW"


def test_store_items_counts_each_outcome(pg, source):
    items = [_item(), _item(external_id="x2", url="https://example.invalid/2")]
    first = intake.store_items(pg, source["source_id"], items)
    assert first == {"NEW": 2, "REVISED": 0, "DUPLICATE": 0}

    second = intake.store_items(pg, source["source_id"], items)
    assert second == {"NEW": 0, "REVISED": 0, "DUPLICATE": 2}


def test_a_collection_run_is_persisted(pg, source):
    run_id = intake.start_run(pg, source["source_id"], mode="snapshot")
    intake.finish_run(pg, run_id, status="PASS", discovered=3, new=2, duplicates=1)

    runs = [r for r in intake.recent_runs(pg) if r["collection_run_id"] == run_id]
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "PASS"
    assert (run["discovered_count"], run["new_count"], run["duplicate_count"]) == (3, 2, 1)
    assert run["finished_at"] is not None


def test_a_failed_run_records_its_error(pg, source):
    run_id = intake.start_run(pg, source["source_id"], mode="live")
    intake.finish_run(pg, run_id, status="FAIL", error="HTTP 401")
    intake.record_error(
        pg, source_id=source["source_id"], collection_run_id=run_id,
        kind="COLLECTION_FAILED", detail="HTTP 401",
    )
    run = [r for r in intake.recent_runs(pg) if r["collection_run_id"] == run_id][0]
    assert run["status"] == "FAIL"
    assert "401" in run["error"]


def test_pending_items_feed_the_ingest_queue(pg, source):
    intake.store_item(pg, source["source_id"], _item())
    pending = [p for p in intake.pending_items(pg) if p["source_id"] == source["source_id"]]
    assert len(pending) == 1
    assert pending[0]["source_key"] == source["source_key"]

    intake.mark_ingested(pg, pending[0]["source_item_id"])
    still_pending = [p for p in intake.pending_items(pg) if p["source_id"] == source["source_id"]]
    assert still_pending == []


def test_only_terminal_ingest_states_are_accepted(pg, source):
    intake.store_item(pg, source["source_id"], _item())
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    with pytest.raises(ValueError):
        intake.mark_ingested(pg, item_id, "PENDING")


def test_summary_reports_what_the_dashboard_shows(pg, source):
    intake.store_item(pg, source["source_id"], _item())
    sources.set_enabled(pg, source["source_id"], True)

    summary = intake.summary(pg)
    assert summary["sources"] >= 1
    assert summary["enabled_sources"] >= 1
    assert summary["source_items"] >= 1
    assert summary["pending_ingest"] >= 1
    assert "errors_24h" in summary
