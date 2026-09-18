"""v0.96.0 direct-source extraction yield - the runtime side.

The engine side (`engine/tests/test_v0960_extraction_yield.py`) proves the
rules read more of what a community writes. This file proves the three
things that only exist once the runtime is involved:

1. When a Daum body arrives after the search-snippet ingest, the post is
   re-read *into the same candidate* and the Event keeps its id - and gains
   the time and venue the snippet lacked. "새 정보 때문에 기존 Event ID가
   바뀌면 실패다."
2. The 월간가또 shape: a direct post whose snippet names no night cannot
   match its Miltang listing; once the body carries the real date, time
   and venue it matches under the existing (unrelaxed) duplicate rules, the
   Miltang Event keeps its id, and the direct post becomes its
   representative.
3. Per-source yield diagnostics: past/today/upcoming/undated, body_pending,
   the two rates (0-division safe), and the BODY_PENDING diagnosis.

ingest_pending()/reprocess_acquired() open their own autocommit connections
(they are scheduler jobs), invisible to the `pg` fixture's transaction, so
the tests that drive them commit their own rows and clean up explicitly -
the same discipline tests/test_image_poster_ocr.py uses. Nothing here
calls normalize_all() (v0.82.2 safety rule): candidates are normalised one
at a time through normalization.normalize_candidate(), the exact call
normalize_all() makes per row.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from runtime import (
    acquisition,
    content_store,
    duplicates,
    engine_adapter,
    engine_ingest,
    events_api,
    normalization,
    source_evidence,
    source_ops,
    sources,
)

PUBLISHED = "2026-09-14"


# --- helpers -----------------------------------------------------------------

def _source(pg, unique, *, key, platform, role, authority, config=None):
    return sources.create_source(
        pg, source_key=f"{key}-{unique}", name=f"{key} {unique}", platform=platform,
        source_role=role, authority_level=authority,
        url=f"https://{key.lower()}.test/{unique}", config=config or {}, enabled=False,
    )["source_id"]


def _pending_item(pg, source_id, *, url, title, body="", platform="DAUM_CAFE",
                  published=PUBLISHED, external_id=None):
    raw = {"platform": platform, "published_at": published, "body": body,
           "acquisition_quality": "METADATA_ONLY"}
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, title, content_hash, "
            "  raw, ingest_state) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'PENDING') "
            "RETURNING source_item_id",
            (source_id, external_id or url, url, title, f"hash-{url}", json.dumps(raw)),
        )
        return cur.fetchone()[0]


def _engine_candidates(settings, source_url):
    con = sqlite3.connect(engine_adapter.engine_db_path(settings))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT c.candidate_id, c.name AS event_name, c.event_date, c.start_time, "
            "       c.end_time, c.end_day_offset, c.venue, c.event_type, c.fee, "
            "       c.fee_display_text, c.dj, c.status AS candidate_status, "
            "       p.post_id, p.source_url "
            "FROM event_candidates c JOIN raw_posts p ON p.post_id = c.post_id "
            "WHERE p.source_url = ? ORDER BY c.candidate_id", (source_url,),
        ).fetchall()
    finally:
        con.close()
    out = []
    for row in rows:
        item = dict(row)
        item["provenance"] = normalization.PROVENANCE_LIVE
        item["time_evidence"] = "EXPLICIT"
        out.append(item)
    return out


def _normalize(pg, candidate):
    # What normalize_all() adds per row before calling normalize_candidate():
    # the collected item the post came from (provenance is fixed to LIVE here
    # because these fixture items have no collection run behind them).
    candidate = dict(candidate)
    candidate["source_item_id"] = normalization.source_of(pg, candidate["source_url"])["source_item_id"]
    assert candidate["source_item_id"] is not None
    stored = normalization.normalize_candidate(pg, candidate)
    pg.commit()
    return stored


def _row(pg, event_id):
    with pg.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE event_id = %s", (event_id,))
        names = [c.name for c in cur.description]
        found = cur.fetchone()
        return None if found is None else dict(zip(names, found))


def _cleanup(pg, source_ids):
    """Undo committed rows: history, events (folded first), content, items, sources."""
    with pg.cursor() as cur:
        cur.execute(
            "DELETE FROM event_primary_source_history WHERE event_id IN ("
            "  SELECT e.event_id FROM events e JOIN source_items i USING (source_item_id) "
            "  WHERE i.source_id = ANY(%s))", (source_ids,))
        cur.execute(
            "DELETE FROM events WHERE canonical_event_id IS NOT NULL AND source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))", (source_ids,))
        cur.execute(
            "DELETE FROM events WHERE source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))", (source_ids,))
        cur.execute(
            "DELETE FROM source_item_content WHERE source_item_id IN ("
            "  SELECT source_item_id FROM source_items WHERE source_id = ANY(%s))", (source_ids,))
        cur.execute("DELETE FROM source_items WHERE source_id = ANY(%s)", (source_ids,))
        cur.execute("DELETE FROM sources WHERE source_id = ANY(%s)", (source_ids,))
    pg.commit()


@pytest.fixture
def settings():
    from runtime.config import load_settings

    return load_settings()


# === 1. body arrival keeps the candidate and the Event id ===================

def test_a_daum_body_arriving_later_fills_the_event_without_changing_its_id(pg, unique, settings):
    direct = _source(pg, unique, key="GATO", platform="DAUM_CAFE", role="COMMUNITY",
                     authority="PRIMARY_ORGANIZER")
    url = f"https://cafe.daum.test/gato/{unique}/152"
    item = _pending_item(pg, direct, url=url,
                         title="가또땅고 152번째 수요 밀롱가 09.16 with DJ 롭")
    pg.commit()
    try:
        # Snippet only: a dated milonga with no time and no venue.
        assert engine_ingest.ingest_pending(settings)["ingested"] == 1
        before = _engine_candidates(settings, url)
        assert len(before) == 1
        assert before[0]["event_date"] == "2026-09-16"
        assert before[0]["start_time"] is None and before[0]["venue"] is None
        stored = _normalize(pg, before[0])
        event_id = stored["event_id"]
        first = _row(pg, event_id)
        assert first["candidate_id"] == before[0]["candidate_id"]
        assert first["start_time"] is None and first["venue_text"] is None
        # The body is still queued - the Daum shape right after enabling.
        content_store.ensure_row(pg, item)
        assert content_store.mark_pending(pg, [item]) == 1
        pg.commit()
        assert next(e for e in source_ops.overview(pg) if e["source_id"] == direct)["body_pending"] == 1
        # The body arrives, with the night's time and place.
        content_store.record_outcome(pg, item, acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
            fetched_url=url, text="이데알 탱고 까페 저녁 8시부터 회비 10,000원 DJ 롭",
        ))
        pg.commit()
        assert item in {r["source_item_id"] for r in content_store.needing_reprocess(pg, limit=100)}
        outcome = engine_ingest.reprocess_acquired(settings)
        assert outcome["failed"] == 0 and outcome["reprocessed"] >= 1

        after = _engine_candidates(settings, url)
        assert [c["candidate_id"] for c in after] == [before[0]["candidate_id"]], (
            "re-extraction must re-read into the same candidate, not issue a new id")
        assert after[0]["event_date"] == "2026-09-16"
        assert after[0]["start_time"] == "20:00"
        assert after[0]["venue"] == "이데알 탱고 까페"
        assert after[0]["fee"] == 10000

        stored_again = _normalize(pg, after[0])
        assert stored_again["event_id"] == event_id, "new information must never change the Event id"
        second = _row(pg, event_id)
        assert str(second["start_time"])[:5] == "20:00"
        assert second["venue_text"] == "이데알 탱고 까페"
        assert second["fee"] == 10000
        assert second["event_date"] == date(2026, 9, 16)
        assert events_api.get_event(pg, event_id)["id"] == event_id
    finally:
        _cleanup(pg, [direct])


# === 2. 월간가또: matching only once the body names the night ==============

def test_wolgan_gato_matches_its_miltang_listing_only_once_the_body_names_the_night(
        pg, unique, settings):
    miltang = _source(pg, unique, key="MILTANG", platform="WEB", role="DIRECTORY",
                      authority="AGGREGATOR")
    direct = _source(pg, unique, key="GATO", platform="DAUM_CAFE", role="COMMUNITY",
                     authority="PRIMARY_ORGANIZER")
    miltang_url = f"https://miltang.test/milongas/{unique}"
    direct_url = f"https://cafe.daum.test/gato/{unique}/monthly"
    miltang_item = _pending_item(
        pg, miltang, url=miltang_url, platform="WEB", published=None,
        title="월간가또 Monthly Gato Milonga",
        body="2026년 10월 10일 시간: 19:00~23:00 장소: 이데알 탱고 까페 주최: 가또땅고")
    direct_item = _pending_item(
        pg, direct, url=direct_url, published="2026-09-15",
        title="[부산_가또땅고]월간가또 Monthly Gato Milonga 시즌2")
    pg.commit()
    try:
        assert engine_ingest.ingest_pending(settings)["ingested"] == 2
        listing = _engine_candidates(settings, miltang_url)
        assert len(listing) == 1 and listing[0]["event_date"] == "2026-10-10"
        miltang_event = _normalize(pg, listing[0])["event_id"]

        # The snippet names no night: no date, so nothing to match against.
        snippet = _engine_candidates(settings, direct_url)
        assert len(snippet) == 1
        assert snippet[0]["event_date"] is None
        assert _normalize(pg, snippet[0]) is None
        found = duplicates.scan(pg, on=date(2026, 10, 10))
        assert _row(pg, miltang_event)["canonical_event_id"] is None

        # The body arrives: the monthly night, its clock and its place.
        content_store.ensure_row(pg, direct_item)
        content_store.mark_pending(pg, [direct_item])
        content_store.record_outcome(pg, direct_item, acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
            fetched_url=direct_url,
            text="매월 둘째 토요일 19:00-23:00 장소: 이데알 탱고 까페 회비 10,000원",
        ))
        pg.commit()
        assert engine_ingest.reprocess_acquired(settings)["failed"] == 0
        body = _engine_candidates(settings, direct_url)
        assert [c["candidate_id"] for c in body] == [snippet[0]["candidate_id"]]
        assert (body[0]["event_date"], body[0]["start_time"], body[0]["venue"]) == (
            "2026-10-10", "19:00", "이데알 탱고 까페")
        direct_event = _normalize(pg, body[0])["event_id"]
        assert direct_event != miltang_event

        # Same date, same place, same start: the existing auto-merge rule,
        # unrelaxed. The older (Miltang) Event keeps its id; the direct post
        # represents it.
        found = duplicates.scan(pg, on=date(2026, 10, 10))
        assert found["auto_merged"] >= 1
        head, member = _row(pg, miltang_event), _row(pg, direct_event)
        assert head["canonical_event_id"] is None
        assert member["canonical_event_id"] == miltang_event
        assert head["primary_source_item_id"] == direct_item
        assert head["primary_source_decided_by"] == duplicates.AUTO
        shown = events_api.get_event(pg, miltang_event)
        assert shown["id"] == miltang_event
        assert shown["source_link"]["url"] == direct_url
        assert shown["source_evidence"]["class"] == source_evidence.PRIMARY_ORGANIZER
        assert events_api.get_event(pg, direct_event)["id"] == miltang_event
        posts = duplicates.sources_of(pg, miltang_event)
        assert {p["source_url"] for p in posts} == {miltang_url, direct_url}
    finally:
        _cleanup(pg, [miltang, direct])


# === 3. yield diagnostics ===================================================

def test_rates_are_zero_safe_and_per_post():
    assert source_ops.yield_rates(0, 0, 0) == {"event_candidate_rate": 0.0, "upcoming_event_rate": 0.0}
    assert source_ops.yield_rates(None, 3, 1) == {"event_candidate_rate": 0.0, "upcoming_event_rate": 0.0}
    assert source_ops.yield_rates(30, 3, 1) == {"event_candidate_rate": 0.1, "upcoming_event_rate": 0.033}


def _diag(**outcome):
    source = {"enabled": True, "last_detail": "PASS, 20 search hits"}
    run = {"status": "PASS", "discovered_count": outcome.get("items", 0)}
    base = {"items": 0, "fetched": 0, "blocked": 0, "login": 0, "events": 0,
            "upcoming_events": 0, "body_pending": 0}
    base.update(outcome)
    return source_ops.yield_diagnosis(source, base, run)[0]


def test_body_pending_is_told_apart_from_unreadable_and_from_non_event():
    assert _diag(items=149, body_pending=149) == source_ops.DIAG_BODY_PENDING
    assert _diag(items=30, blocked=30) == source_ops.DIAG_METADATA_ONLY_NO_EVENT
    assert _diag(items=100, fetched=100) == source_ops.DIAG_NON_EVENT_CONTENT
    assert _diag(items=100, fetched=100, events=7) == source_ops.DIAG_PAST_ONLY
    assert _diag(items=100, fetched=100, events=7, upcoming_events=2) == source_ops.DIAG_HEALTHY
    assert source_ops.DIAG_LABELS[source_ops.DIAG_BODY_PENDING]


def test_the_overview_carries_the_per_source_breakdown(pg, unique):
    direct = _source(pg, unique, key="YIELD", platform="DAUM_CAFE", role="COMMUNITY",
                     authority="PRIMARY_ORGANIZER")
    items = [_pending_item(pg, direct, url=f"https://yield.test/{unique}/{n}",
                           title=f"밀롱가 {n}") for n in range(4)]
    for item in items:
        content_store.ensure_row(pg, item)
    assert content_store.mark_pending(pg, items[:3]) == 3
    with pg.cursor() as cur:
        cur.execute("UPDATE source_items SET ingest_state = 'INGESTED' WHERE source_id = %s", (direct,))
    for n, (when, suffix) in enumerate([("2026-01-10", "1"), ("2099-12-31", "2")]):
        stored = normalization.normalize_candidate(pg, {
            "candidate_id": int(f"{unique[-6:]}{suffix}"), "post_id": 1,
            "source_url": f"https://yield.test/{unique}/{n}", "source_item_id": items[n],
            "event_name": f"밀롱가 {unique} {n}",
            "event_type": "MILONGA", "event_date": when, "start_time": "20:00",
            "end_time": "23:00", "end_day_offset": 0, "venue": f"v-{unique}", "fee": None,
            "candidate_status": "POSSIBLE", "provenance": normalization.PROVENANCE_LIVE,
            "time_evidence": "EXPLICIT",
        })
        assert stored is not None
    entry = next(e for e in source_ops.overview(pg) if e["source_id"] == direct)
    assert entry["items"] == 4
    assert entry["events"] == 2
    assert entry["events_past"] == 1 and entry["events_upcoming"] == 1
    assert entry["events_undated"] == 0
    assert entry["body_pending"] == 3
    assert entry["event_candidate_rate"] == 0.5
    assert entry["upcoming_event_rate"] == 0.25
    # Fixture sources are created disabled (never collected): the v0.95.0
    # diagnosis order still puts that first, breakdown or no breakdown.
    assert entry["diagnosis"] == source_ops.DIAG_DISABLED
    for key in ("events_today", "events_rejected", "diagnosis_label"):
        assert key in entry


# === 3b. per-source tuning through config.event_terms =======================

class _Cursor:
    def __init__(self, rows):
        self.rows, self.description = rows, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args):
        pass

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)


def test_a_sources_own_event_terms_join_the_genre_words_without_a_source_id_in_code(monkeypatch):
    from runtime import engine_ingest, event_terms

    monkeypatch.setattr(event_terms, "terms_by_genre", lambda con: {})
    lookup = engine_ingest._detection_terms_by_source(_Conn([
        (10, 1, ["열탱즐탱", " 쁘락 타임 "]), (20, 1, None), (30, 1, '["가또나이트"]'), (40, 1),
    ]))
    assert lookup(10) == ("열탱즐탱", "쁘락 타임")
    assert lookup(20) is None
    assert lookup(30) == ("가또나이트",)
    assert lookup(40) is None


# === 4. the contracts this release must not move ===========================

def test_a_direct_post_found_later_represents_the_event_but_never_takes_its_id(pg, unique):
    """v0.94.0 identity + reconciliation, re-asserted on the new engine store
    shape: the aggregator's older Event keeps its id, the organizer's post
    represents it, and the folded id still answers with the Event."""
    aggregator = _source(pg, unique, key="AGG", platform="WEB", role="DIRECTORY",
                         authority="AGGREGATOR")
    organizer = _source(pg, unique, key="ORG", platform="NAVER_CAFE", role="COMMUNITY",
                        authority="PRIMARY_ORGANIZER")
    agg_url, org_url = f"https://agg.test/{unique}", f"https://org.test/{unique}"
    agg_item = _pending_item(pg, aggregator, url=agg_url, platform="WEB", title="a")
    org_item = _pending_item(pg, organizer, url=org_url, platform="NAVER_CAFE", title="o")
    ids = []
    for n, (url, name, item) in enumerate([(agg_url, "밀롱가 A", agg_item),
                                           (org_url, "밀롱가 A (organizer)", org_item)]):
        stored = normalization.normalize_candidate(pg, {
            "candidate_id": int(f"{unique[-6:]}{n + 5}"), "post_id": 1, "source_url": url,
            "source_item_id": item,
            "event_name": f"{name} {unique}", "event_type": "MILONGA",
            "event_date": "2026-11-20", "start_time": "20:00", "end_time": "23:00",
            "end_day_offset": 0, "venue": f"venue-{unique}", "fee": 10000,
            "candidate_status": "POSSIBLE", "provenance": normalization.PROVENANCE_LIVE,
            "time_evidence": "EXPLICIT",
        })
        ids.append(stored["event_id"])
    agg_event, org_event = ids
    assert duplicates.scan(pg, on=date(2026, 11, 20))["auto_merged"] >= 1
    assert _row(pg, agg_event)["canonical_event_id"] is None
    assert _row(pg, org_event)["canonical_event_id"] == agg_event
    assert _row(pg, agg_event)["primary_source_item_id"] == org_item
    assert events_api.get_event(pg, org_event)["id"] == agg_event
    assert events_api.get_event(pg, agg_event)["source_link"]["url"] == org_url
    assert agg_item is not None
