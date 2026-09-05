"""Raw source intake: collection runs, deduplication and the ingest queue."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime import content_store, intake, sources


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
    # A generous limit on purpose. pending_items batches at 50 by default and
    # orders oldest first, so a staging queue with a real backlog would push
    # this test's own row off the end -- which says nothing about the state
    # transition being tested.
    deep = 100000

    intake.store_item(pg, source["source_id"], _item())
    pending = [p for p in intake.pending_items(pg, limit=deep)
               if p["source_id"] == source["source_id"]]
    assert len(pending) == 1
    assert pending[0]["source_key"] == source["source_key"]

    intake.mark_ingested(pg, pending[0]["source_item_id"])
    still_pending = [p for p in intake.pending_items(pg, limit=deep)
                     if p["source_id"] == source["source_id"]]
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


# --- v0.82.2: FETCHED_FULL settlement ----------------------------------------
#
# Root cause this section guards against: a source whose discovery module
# already synthesizes the complete article body (TangoNOW, Tango Calendar
# Korea, Miltang - none of them do a separate HTML detail fetch) left
# `source_item_content` untouched at intake time. The generic acquisition
# queue (`content_store.mark_pending()`/`due_for_acquisition()`) then read
# "no content row yet" as "needs fetching", re-fetched through the generic
# extractor, and could silently replace the correct body with the site's own
# boilerplate (e.g. Miltang's `og:description` tagline) - which
# `engine-reprocess` then read as a genuine revision and re-extracted from,
# producing a date-less candidate that `normalization.normalize_all()`'s own
# cleanup correctly read as "no longer live" and deleted the previously-
# correct event for. Confirmed live: 85 of 108 real Miltang items degraded
# this way within about 90 minutes; the derived event count fell 50 -> 8.

def _full_item(**overrides) -> intake.RawItem:
    body = overrides.pop("body", "2026년 9월 12일 시간: 19:00~23:00 장소: PISTA (피스타)")
    raw = {"platform": "WEB", "acquisition_quality": "FETCHED_FULL", **overrides.pop("raw", {})}
    payload = {
        "external_id": "https://example.test/full/1",
        "url": "https://example.test/full/1",
        "title": "The PISTA Milonga",
        "body": body,
        "published_at": None,
        "raw": raw,
    }
    payload.update(overrides)
    return intake.RawItem(**payload)


def test_fetched_full_intake_settles_content_immediately(pg, source):
    assert intake.store_item(pg, source["source_id"], _full_item()) == "NEW"
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    settled = content_store.get(pg, item_id)
    assert settled is not None
    assert settled["acquisition_status"] == "FETCHED_FULL"
    assert settled["extracted_text"] == "2026년 9월 12일 시간: 19:00~23:00 장소: PISTA (피스타)"
    assert settled["acquisition_method"] == "discovery_synthesized"
    # engine-reprocess must have nothing left to usefully redo on this item.
    assert settled["reprocessed_at"] is not None
    assert settled["reprocessed_at"] >= settled["fetched_at"]


def test_a_settled_full_item_is_excluded_from_the_generic_acquisition_queue(pg, source):
    """The structural proof that a settled item can never be downgraded:
    it must never even be selected by either stage of the generic queue."""
    intake.store_item(pg, source["source_id"], _full_item())
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]

    # "Anything collected but never queued becomes queued" (acquisition_job's
    # own first step) must not touch an already-settled row.
    content_store.ensure_row(pg, item_id)
    queued = content_store.mark_pending(pg, [item_id])
    assert queued == 0
    assert content_store.get(pg, item_id)["acquisition_status"] == "FETCHED_FULL"

    due = [d["source_item_id"] for d in content_store.due_for_acquisition(pg, limit=1000)]
    assert item_id not in due


def test_empty_full_body_is_not_settled(pg, source):
    intake.store_item(pg, source["source_id"], _full_item(body=""))
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    assert content_store.get(pg, item_id) is None


def test_whitespace_only_full_body_is_not_settled(pg, source):
    intake.store_item(pg, source["source_id"], _full_item(body="   \n\t  "))
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    assert content_store.get(pg, item_id) is None


def test_a_too_short_full_body_is_not_settled(pg, source):
    """Below MINIMUM_USEFUL_TEXT - a placeholder, not real content."""
    intake.store_item(pg, source["source_id"], _full_item(body="짧음"))
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    assert content_store.get(pg, item_id) is None


def test_fetched_partial_quality_is_left_to_the_existing_acquisition_flow(pg, source):
    """Only FETCHED_FULL settles at intake - PARTIAL keeps its existing
    fallback-eligible behaviour, unchanged by this patch."""
    item = _full_item(raw={"acquisition_quality": "FETCHED_PARTIAL"})
    intake.store_item(pg, source["source_id"], item)
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    assert content_store.get(pg, item_id) is None


def test_metadata_only_quality_is_untouched(pg, source):
    """DanceInfo's own title-only list stage - must keep queuing normally."""
    item = _full_item(raw={"acquisition_quality": "METADATA_ONLY"}, body="")
    intake.store_item(pg, source["source_id"], item)
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    assert content_store.get(pg, item_id) is None


def test_storing_the_same_full_item_twice_is_idempotent(pg, source):
    intake.store_item(pg, source["source_id"], _full_item())
    intake.store_item(pg, source["source_id"], _full_item())
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    with pg.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM source_item_content WHERE source_item_id = %s", (item_id,)
        )
        assert cur.fetchone()[0] == 1


def test_a_revised_full_item_updates_the_settled_content(pg, source):
    intake.store_item(pg, source["source_id"], _full_item())
    intake.mark_ingested(
        pg, intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    )
    new_body = "2026년 9월 19일 시간: 19:00~23:00 장소: PISTA (피스타)"
    assert intake.store_item(pg, source["source_id"], _full_item(body=new_body)) == "REVISED"
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    settled = content_store.get(pg, item_id)
    assert settled["extracted_text"] == new_body


def test_tangonow_output_settles_at_intake(pg, source):
    """The exact discovery -> collector -> intake path a real cycle uses."""
    from runtime import collectors, tangonow_discovery as tn

    doc = {
        "name": "projects/ktangoguide/databases/(default)/documents/events/x1",
        "fields": {
            "title": {"stringValue": "The PISTA Milonga"},
            "date": {"stringValue": "2026-09-12"},
            "time": {"stringValue": "19:00-23:00"},
            "place": {"stringValue": "PISTA"},
        },
    }
    record = tn.parse_documents([doc], "https://firestore.googleapis.com/v1/x")[0]
    record["source_id"] = source["source_key"]
    record["platform"] = "WEB"
    item = collectors._to_raw_item(record)
    assert intake.store_item(pg, source["source_id"], item) == "NEW"
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    settled = content_store.get(pg, item_id)
    assert settled is not None and settled["acquisition_status"] == "FETCHED_FULL"


def test_tangocalendar_output_settles_at_intake(pg, source):
    from datetime import date

    from runtime import collectors, tangocalendar_discovery as tc

    event = {
        "id": "3aa58986-65da-41c4-8693-895b005d1f1c",
        "title": "Alonga", "description": None,
        "startDate": "2026-09-12T05:00:00Z", "endDate": "2026-09-12T09:00:00Z",
        "entranceFee": 13000, "venue": "PISTA", "djName": None,
        "organizerOther": None, "createdAt": "2026-09-02T06:06:40Z",
        "updatedAt": "2026-09-02T06:06:40Z", "rrule": None,
        "occurrenceOverrides": None, "isCancelled": False,
    }
    record = tc.parse_events([event], "https://tangocalendar.kr/api/events",
                              today=date(2026, 9, 5))[0]
    record["source_id"] = source["source_key"]
    record["platform"] = "WEB"
    item = collectors._to_raw_item(record)
    assert intake.store_item(pg, source["source_id"], item) == "NEW"
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    settled = content_store.get(pg, item_id)
    assert settled is not None and settled["acquisition_status"] == "FETCHED_FULL"


def test_danceinfo_title_only_discovery_still_queues_for_a_real_detail_fetch(pg, source):
    """Section 17's own explicit guard: DanceInfo's list stage never carries
    a full body - it must keep going through the ordinary acquisition path,
    not be mistaken for already-settled content."""
    from runtime import collectors, danceinfo_discovery as di

    raw_html = (
        '<script id="__NEXT_DATA__">{"props":{"pageProps":{"initialDays":['
        '{"lessons":[{"genreName":"탱고","contentIdx":501,"title":"러블리밀롱가"}]}'
        ']}}}</script>'
    )
    record = di.parse_list(raw_html, "https://danceinfo.net/lessons")[0]
    record["source_id"] = source["source_key"]
    record["platform"] = "WEB"
    item = collectors._to_raw_item(record)
    assert item.raw["acquisition_quality"] == "METADATA_ONLY"
    intake.store_item(pg, source["source_id"], item)
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    assert content_store.get(pg, item_id) is None


def test_miltang_output_settles_at_intake(pg, source):
    from runtime import collectors, miltang_discovery as md

    page = (
        '<html><body>'
        '<script type="application/ld+json">'
        '{"@type":"Event","name":"The PISTA Milonga","startDate":"2026-09-12",'
        '"location":{"@type":"Place","name":"PISTA 피스타",'
        '"address":{"@type":"PostalAddress","streetAddress":"서울 월드컵북로6길 49"}}}'
        '</script>'
        '<h2 class="text-2xl font-bold text-fg1">The PISTA Milonga</h2>'
        '<dl><div><dt>TIME</dt><dd>19:00~23:00</dd></div></dl>'
        '</body></html>'
    )
    record = md.parse_detail(page, "https://miltang.com/milongas/731")
    record["source_id"] = source["source_key"]
    record["platform"] = "WEB"
    item = collectors._to_raw_item(record)
    assert intake.store_item(pg, source["source_id"], item) == "NEW"
    item_id = intake.recent_items(pg, source_id=source["source_id"])[0]["source_item_id"]
    settled = content_store.get(pg, item_id)
    assert settled is not None and settled["acquisition_status"] == "FETCHED_FULL"
    assert "PISTA" in settled["extracted_text"]
