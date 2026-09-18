"""v0.94.0 Event Source Evidence: direct sources over aggregators, same Event.

The product rule under test: TangoNOW/Miltang are the safety net that keeps
a night from being missed; when the organizer's, community's or venue's own
public post exists, *that* post represents the Event - without the Event's
id changing, without the aggregator's post being deleted, and without a
shared/promotion post ever being mistaken for the organizer speaking.

Everything runs on the rolled-back ``pg`` fixture with synthetic sources
whose URLs end in ``.test``; no network, no credential, no production row.
"""

from __future__ import annotations

import contextlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from runtime import (
    collectors,
    communities,
    duplicates,
    events_api,
    master_data,
    normalization,
    source_evidence,
    sources,
    web_discovery,
)
from runtime import community_discovery as cd

EVENT_DATE = date(2026, 11, 3)


# --- helpers -----------------------------------------------------------------

def _candidate(unique, suffix="1", **overrides):
    payload = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://post.test/{unique}-{suffix}",
        "event_name": f"밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": EVENT_DATE.isoformat(),
        "start_time": "20:00", "end_time": "23:00", "end_day_offset": 0,
        "venue": f"venue-{unique}", "fee": 10000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
        "time_evidence": "EXPLICIT",
    }
    payload.update(overrides)
    return payload


def _source(pg, unique, *, key, role, authority="UNKNOWN", platform="WEB", url=None,
            config=None):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (source_key, name, platform, source_role, url, "
            "  authority_level, enabled, config) "
            "VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s::jsonb) RETURNING source_id",
            (f"{key}-{unique}", f"{key} {unique}", platform, role,
             url or f"https://{key.lower()}.test/{unique}", authority,
             json.dumps(config or {})),
        )
        return cur.fetchone()[0]


def _item(pg, source_id, url, *, external=False, collected_at=None):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, content_hash, raw, "
            "  collected_at) VALUES (%s, %s, %s, %s, %s::jsonb, COALESCE(%s, now())) "
            "RETURNING source_item_id",
            (source_id, url, url, url, json.dumps({"external_promotion": external}),
             collected_at),
        )
        return cur.fetchone()[0]


def _event(pg, unique, suffix, source_item_id, **overrides):
    """An event normalised through the real path, then pointed at its post."""
    stored = normalization.normalize_candidate(pg, _candidate(unique, suffix, **overrides))
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET source_item_id = %s WHERE event_id = %s",
                    (source_item_id, stored["event_id"]))
    return stored["event_id"]


def _row(pg, event_id):
    with pg.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE event_id = %s", (event_id,))
        names = [c.name for c in cur.description]
        return dict(zip(names, cur.fetchone()))


def _aggregator_then_organizer(pg, unique, *, authority="PRIMARY_ORGANIZER", external=False,
                               organizer_overrides=None):
    """TangoNOW-like DIRECTORY post first (older id), organizer's own post
    later - the exact sequence the release exists for."""
    aggregator = _source(pg, unique, key="TANGONOW", role="DIRECTORY", authority="AGGREGATOR")
    organizer = _source(pg, unique, key="ORG", role="COMMUNITY", authority=authority)
    agg_url = f"https://tangonow.test/{unique}/event"
    org_url = f"https://org.test/{unique}/post"
    agg_item = _item(pg, aggregator, agg_url)
    org_item = _item(pg, organizer, org_url, external=external,
                     collected_at=datetime.now(timezone.utc) - timedelta(minutes=3))
    agg_event = _event(pg, unique, "1", agg_item, source_url=agg_url)
    org_event = _event(pg, unique, "2", org_item, source_url=org_url,
                       **(organizer_overrides or {}))
    return {"agg_event": agg_event, "org_event": org_event, "agg_item": agg_item,
            "org_item": org_item, "agg_url": agg_url, "org_url": org_url}


# === 1. evidence classes ======================================================

@pytest.mark.parametrize("role, authority, platform, external, expected", [
    ("ORGANIZER", "PRIMARY_ORGANIZER", "WEB", False, source_evidence.PRIMARY_ORGANIZER),
    ("COMMUNITY", "PRIMARY_ORGANIZER", "NAVER_CAFE", False, source_evidence.PRIMARY_ORGANIZER),
    ("COMMUNITY", "SECONDARY", "DAUM_CAFE", False, source_evidence.OFFICIAL_ORGANIZER),
    ("ORGANIZER", "UNKNOWN", "WEB", False, source_evidence.OFFICIAL_ORGANIZER),
    ("VENUE", "PRIMARY_VENUE", "WEB", False, source_evidence.OFFICIAL_VENUE),
    ("PROMOTION_BOARD", "SECONDARY", "DAUM_CAFE", False, source_evidence.COMMUNITY_PROMOTION),
    ("COMMUNITY", "PRIMARY_ORGANIZER", "DAUM_CAFE", True, source_evidence.COMMUNITY_PROMOTION),
    ("DIRECTORY", "SECONDARY", "WEB", False, source_evidence.AGGREGATOR),
    ("AGGREGATOR", "AGGREGATOR", "WEB", False, source_evidence.AGGREGATOR),
    ("AGGREGATOR", "AGGREGATOR", "NAVER_BLOG", False, source_evidence.SEARCH_DISCOVERY),
    (None, None, None, False, source_evidence.SEARCH_DISCOVERY),
    ("SOMETHING_NEW", "PRIMARY_ORGANIZER", "WEB", False, source_evidence.SEARCH_DISCOVERY),
])
def test_evidence_class_is_derived_from_role_authority_platform_and_promotion(
        role, authority, platform, external, expected):
    assert source_evidence.classify(role, authority, platform, external) == expected


def test_evidence_order_is_organizer_venue_promotion_aggregator_search():
    ranks = [source_evidence.rank(c) for c in source_evidence.CLASSES]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert source_evidence.rank(source_evidence.PRIMARY_ORGANIZER) < source_evidence.rank(
        source_evidence.COMMUNITY_PROMOTION) < source_evidence.rank(source_evidence.AGGREGATOR)
    assert source_evidence.is_direct(source_evidence.OFFICIAL_VENUE)
    assert not source_evidence.is_direct(source_evidence.COMMUNITY_PROMOTION)


def test_external_promotion_is_a_ceiling_not_a_tiebreak():
    """A Busan cafe sharing a Seoul organizer's night: however the cafe's own
    source is configured, the shared post is promotion, never the organizer."""
    for authority in ("PRIMARY_ORGANIZER", "SECONDARY", "UNKNOWN"):
        assert (source_evidence.classify("COMMUNITY", authority, "DAUM_CAFE", True)
                == source_evidence.COMMUNITY_PROMOTION)


# === 2. the release's own scenario: aggregator first, organizer later ========

def test_organizer_post_found_later_becomes_the_representative_and_the_event_id_stays(pg, unique):
    pair = _aggregator_then_organizer(pg, unique)
    before = _row(pg, pair["agg_event"])
    assert before["canonical_event_id"] is None

    found = duplicates.scan(pg, on=EVENT_DATE)
    assert found["auto_merged"] >= 1

    # 4. The incumbent (aggregator-first) row is still the canonical one.
    agg = _row(pg, pair["agg_event"])
    org = _row(pg, pair["org_event"])
    assert agg["canonical_event_id"] is None, "the existing Event must keep its id"
    assert org["canonical_event_id"] == pair["agg_event"]
    # 5. The organizer's post is the representative of that same Event.
    assert agg["primary_source_item_id"] == pair["org_item"]
    assert agg["primary_source_decided_by"] == duplicates.AUTO
    assert "PRIMARY_ORGANIZER" in (agg["primary_source_reason"] or "")
    # 6. The aggregator's post is retained as supporting evidence.
    posts = duplicates.sources_of(pg, pair["agg_event"])
    assert {p["source_url"] for p in posts} == {pair["agg_url"], pair["org_url"]}
    primary = [p for p in posts if p["is_primary"]]
    assert [p["source_url"] for p in primary] == [pair["org_url"]]
    assert primary[0]["evidence_class"] == source_evidence.PRIMARY_ORGANIZER
    supporting = next(p for p in posts if p["source_url"] == pair["agg_url"])
    assert supporting["is_canonical"] and not supporting["is_primary"]
    assert supporting["evidence_class"] == source_evidence.AGGREGATOR
    # 7. Public/API: the reader is sent to the organizer's post, under the
    #    existing id, and freshness follows the representative post.
    event = events_api.get_event(pg, pair["agg_event"])
    assert event["id"] == pair["agg_event"]
    assert event["source_link"]["url"] == pair["org_url"]
    assert event["source_evidence"]["class"] == source_evidence.PRIMARY_ORGANIZER
    assert event["source_evidence"]["elected"] is True
    assert event["source_tier"] == "PRIMARY"
    assert [s["url"] for s in event["sources"] if s["is_primary"]] == [pair["org_url"]]
    # 14. The change of representative is recorded, not lost.
    history = duplicates.primary_source_history(pg, pair["agg_event"])
    assert len(history) == 1
    assert history[0]["source_item_id"] == pair["org_item"]
    assert history[0]["previous_source_item_id"] == pair["agg_item"]
    assert history[0]["decided_by"] == duplicates.AUTO


def test_the_representative_post_fills_what_the_listing_lacked_and_never_overrides(pg, unique):
    """The DJ and a fee the aggregator never carried come from the organizer's
    post the reader is sent to; a value the listing already had stays."""
    # Both posts declined to reduce the two-tier fee to one number (equally
    # complete, so the listing's row stays canonical); only the organizer's
    # post names the DJ and carries the fee's display text.
    pair = _aggregator_then_organizer(
        pg, unique, organizer_overrides={"dj": "DJ 유진", "fee": None,
                                         "fee_display_text": "8,000원 (22시 이후 5,000원)"})
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET dj = NULL, fee = NULL WHERE event_id = %s",
                    (pair["agg_event"],))
    duplicates.scan(pg, on=EVENT_DATE)
    shown = events_api.get_event(pg, pair["agg_event"])
    assert shown["id"] == pair["agg_event"]
    assert shown["dj"] == "DJ 유진"
    assert shown["fee"] is None and shown["fee_display_text"] == "8,000원 (22시 이후 5,000원)"

    kept = _aggregator_then_organizer(pg, f"{unique}7", organizer_overrides={"dj": "DJ B", "fee": 8000})
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET dj = 'DJ A' WHERE event_id = %s", (kept["agg_event"],))
    duplicates.scan(pg, on=EVENT_DATE)
    shown = events_api.get_event(pg, kept["agg_event"])
    assert shown["dj"] == "DJ A" and shown["fee"] == 10000


def test_a_link_to_the_folded_organizer_row_still_answers_with_the_event(pg, unique):
    pair = _aggregator_then_organizer(pg, unique)
    duplicates.scan(pg, on=EVENT_DATE)
    event = events_api.get_event(pg, pair["org_event"])
    assert event is not None and event["id"] == pair["agg_event"]


def test_organizer_first_then_aggregator_keeps_the_organizer_as_representative(pg, unique):
    organizer = _source(pg, unique, key="ORG", role="ORGANIZER", authority="PRIMARY_ORGANIZER")
    aggregator = _source(pg, unique, key="MILTANG", role="DIRECTORY", authority="AGGREGATOR")
    org_url, agg_url = f"https://org.test/{unique}", f"https://miltang.test/{unique}"
    org_item = _item(pg, organizer, org_url)
    agg_item = _item(pg, aggregator, agg_url)
    org_event = _event(pg, unique, "1", org_item, source_url=org_url)
    agg_event = _event(pg, unique, "2", agg_item, source_url=agg_url)

    duplicates.scan(pg, on=EVENT_DATE)

    org = _row(pg, org_event)
    assert org["canonical_event_id"] is None
    assert _row(pg, agg_event)["canonical_event_id"] == org_event
    # Its own post is already the best evidence: nothing is stored, nothing
    # is recorded, and the reader still lands on the organizer's page.
    assert org["primary_source_item_id"] is None
    assert duplicates.primary_source_history(pg, org_event) == []
    assert events_api.get_event(pg, org_event)["source_link"]["url"] == org_url


def test_a_more_complete_organizer_post_found_later_never_changes_the_event_id(pg, unique):
    """Case A - the contract this release exists for. A TangoNOW-like Event
    with gaps exists first; the organizer's own, clearly fuller post (DJ,
    fee, end time) is found later. Better information makes the Event more
    accurate; it never becomes a different Event."""
    pair = _aggregator_then_organizer(
        pg, unique, organizer_overrides={"dj": "DJ 유진", "fee": 8000, "end_time": "23:30"})
    old_event_id_before = pair["agg_event"]
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET fee = NULL, end_time = NULL, dj = NULL WHERE event_id = %s",
                    (old_event_id_before,))
    before = _row(pg, old_event_id_before)
    assert duplicates.completeness(_row(pg, pair["org_event"])) > duplicates.completeness(before)

    found = duplicates.scan(pg, on=EVENT_DATE)
    assert found["auto_merged"] >= 1

    canonical_event_id_after = duplicates.canonical_id_of(pg, pair["org_event"])
    assert old_event_id_before == canonical_event_id_after
    agg, org = _row(pg, old_event_id_before), _row(pg, pair["org_event"])
    assert agg["canonical_event_id"] is None
    assert org["canonical_event_id"] == old_event_id_before
    # Primary source = the organizer's post; the aggregator's stays as
    # supporting evidence.
    assert agg["primary_source_item_id"] == pair["org_item"]
    posts = duplicates.sources_of(pg, old_event_id_before)
    assert {p["source_url"] for p in posts} == {pair["agg_url"], pair["org_url"]}
    assert [p["source_url"] for p in posts if p["is_primary"]] == [pair["org_url"]]
    assert next(p for p in posts if p["source_url"] == pair["agg_url"])["is_canonical"]
    # Both ids answer, with the same Event.
    shown = events_api.get_event(pg, old_event_id_before)
    assert shown["id"] == old_event_id_before
    assert events_api.get_event(pg, pair["org_event"])["id"] == old_event_id_before
    assert shown["source_link"]["url"] == pair["org_url"]
    assert shown["source_evidence"]["class"] == source_evidence.PRIMARY_ORGANIZER
    # The allowed fields (v0.94.0's NULL-only fill: DJ, fee pair) are
    # absorbed; the row itself is not rewritten, and its Region attribution
    # (read from its own source) did not move.
    assert shown["dj"] == "DJ 유진" and shown["fee"] == 8000
    assert _row(pg, old_event_id_before)["dj"] is None
    assert _row(pg, old_event_id_before)["region_id"] == before["region_id"]
    assert agg["source_item_id"] == before["source_item_id"]


def test_an_aggregator_that_is_fuller_than_the_direct_event_it_joins_never_takes_the_id(pg, unique):
    """Case C: Direct Event first, a richer aggregator listing later."""
    organizer = _source(pg, unique, key="ORG", role="ORGANIZER", authority="PRIMARY_ORGANIZER")
    aggregator = _source(pg, unique, key="MILTANG", role="DIRECTORY", authority="AGGREGATOR")
    org_url, agg_url = f"https://org.test/{unique}", f"https://miltang.test/{unique}"
    org_item, agg_item = _item(pg, organizer, org_url), _item(pg, aggregator, agg_url)
    org_event = _event(pg, unique, "1", org_item, source_url=org_url, fee=None, end_time=None)
    agg_event = _event(pg, unique, "2", agg_item, source_url=agg_url, dj="DJ X", fee=15000)
    duplicates.scan(pg, on=EVENT_DATE)
    assert _row(pg, org_event)["canonical_event_id"] is None
    assert _row(pg, agg_event)["canonical_event_id"] == org_event
    assert _row(pg, org_event)["primary_source_item_id"] is None
    assert events_api.get_event(pg, agg_event)["id"] == org_event
    assert events_api.get_event(pg, org_event)["source_link"]["url"] == org_url


def test_a_fuller_post_of_the_same_evidence_class_never_takes_the_id(pg, unique):
    """Case D: same authority, only completeness differs - identity stays,
    and the representative does not churn within one class either."""
    pair = _aggregator_then_organizer(pg, unique)
    duplicates.scan(pg, on=EVENT_DATE)
    second = _source(pg, unique, key="ORG2", role="COMMUNITY", authority="PRIMARY_ORGANIZER")
    second_url = f"https://org2.test/{unique}"
    second_item = _item(pg, second, second_url)
    second_event = _event(pg, unique, "3", second_item, source_url=second_url,
                          dj="DJ 둘", fee=12000, end_time="23:59")
    duplicates.scan(pg, on=EVENT_DATE)
    assert _row(pg, pair["agg_event"])["canonical_event_id"] is None
    assert _row(pg, second_event)["canonical_event_id"] == pair["agg_event"]
    assert _row(pg, pair["agg_event"])["primary_source_item_id"] == pair["org_item"]


# === 3. promotion, conflicts, humans =========================================

def test_an_external_promotion_beats_the_aggregator_but_is_never_the_organizer(pg, unique):
    pair = _aggregator_then_organizer(pg, unique, authority="PRIMARY_ORGANIZER", external=True)
    region_before = _row(pg, pair["agg_event"])["region_id"]
    duplicates.scan(pg, on=EVENT_DATE)
    agg = _row(pg, pair["agg_event"])
    assert agg["canonical_event_id"] is None
    assert agg["primary_source_item_id"] == pair["org_item"]
    # Stored as promotion evidence; the PRIMARY_ORGANIZER class is never
    # reached through a shared post, and the Event's own Region attribution
    # (which reads the row's own source) did not move.
    assert "COMMUNITY_PROMOTION" in agg["primary_source_reason"]
    assert "PRIMARY_ORGANIZER" not in agg["primary_source_reason"].split(" over ")[0]
    assert agg["region_id"] == region_before
    event = events_api.get_event(pg, pair["agg_event"])
    assert event["source_evidence"]["class"] == source_evidence.COMMUNITY_PROMOTION
    assert event["source_evidence"]["direct"] is False


def test_a_genuine_organizer_post_then_replaces_the_promotion(pg, unique):
    pair = _aggregator_then_organizer(pg, unique, external=True)
    duplicates.scan(pg, on=EVENT_DATE)
    organizer = _source(pg, unique, key="REALORG", role="ORGANIZER", authority="PRIMARY_ORGANIZER")
    real_url = f"https://realorg.test/{unique}"
    real_item = _item(pg, organizer, real_url)
    _event(pg, unique, "3", real_item, source_url=real_url)
    duplicates.scan(pg, on=EVENT_DATE)
    agg = _row(pg, pair["agg_event"])
    assert agg["canonical_event_id"] is None
    assert agg["primary_source_item_id"] == real_item
    assert len(duplicates.primary_source_history(pg, pair["agg_event"])) == 2


def test_same_class_never_reshuffles_the_representative(pg, unique):
    pair = _aggregator_then_organizer(pg, unique)
    duplicates.scan(pg, on=EVENT_DATE)
    second = _source(pg, unique, key="ORG2", role="COMMUNITY", authority="PRIMARY_ORGANIZER")
    second_url = f"https://org2.test/{unique}"
    second_item = _item(pg, second, second_url)
    _event(pg, unique, "3", second_item, source_url=second_url, fee=12000, dj="DJ")
    duplicates.scan(pg, on=EVENT_DATE)
    assert _row(pg, pair["agg_event"])["primary_source_item_id"] == pair["org_item"]


def test_an_official_post_that_disagrees_on_time_does_not_become_the_representative(pg, unique):
    """A person merged them despite the differing time; the badge stays
    conservative and the reason says why."""
    pair = _aggregator_then_organizer(pg, unique, organizer_overrides={"start_time": "21:30"})
    found = duplicates.scan(pg, on=EVENT_DATE)
    assert found["auto_merged"] == 0 and found["flagged_for_review"] >= 1
    pair_id = next(p["pair_id"] for p in duplicates.open_pairs(pg, limit=500)
                   if {p["event_id"], p["other_event_id"]} == {pair["agg_event"], pair["org_event"]})
    duplicates.resolve_pair(pg, pair_id, decision=duplicates.DUPLICATE,
                            canonical_event_id=pair["agg_event"])
    agg = _row(pg, pair["agg_event"])
    assert agg["canonical_event_id"] is None
    assert agg["primary_source_item_id"] is None, "a conflicting post must not be promoted"
    assert events_api.get_event(pg, pair["agg_event"])["source_link"]["url"] == pair["agg_url"]
    members = duplicates.evidence_of(pg, pair["agg_event"])
    assert {m["source_url"] for m in members} == {pair["agg_url"], pair["org_url"]}


def test_a_human_choice_outlasts_the_scan_until_reset(pg, unique):
    pair = _aggregator_then_organizer(pg, unique)
    duplicates.scan(pg, on=EVENT_DATE)
    assert _row(pg, pair["agg_event"])["primary_source_item_id"] == pair["org_item"]

    duplicates.set_primary_source(pg, pair["agg_event"], pair["agg_item"], reviewer="tester")
    row = _row(pg, pair["agg_event"])
    assert row["primary_source_item_id"] == pair["agg_item"]
    assert row["primary_source_decided_by"] == duplicates.HUMAN
    assert duplicates.reconcile_primary_source(pg, pair["agg_event"])["changed"] is False
    duplicates.scan(pg, on=EVENT_DATE)
    assert _row(pg, pair["agg_event"])["primary_source_item_id"] == pair["agg_item"]
    assert events_api.get_event(pg, pair["agg_event"])["source_link"]["url"] == pair["agg_url"]

    result = duplicates.reset_primary_source(pg, pair["agg_event"], reviewer="tester")
    assert result["changed"] is True
    row = _row(pg, pair["agg_event"])
    assert row["primary_source_item_id"] == pair["org_item"]
    assert row["primary_source_decided_by"] == duplicates.AUTO
    assert [h["decided_by"] for h in duplicates.primary_source_history(pg, pair["agg_event"])] \
        == ["AUTO", "AUTO", "HUMAN", "AUTO"]


def test_a_human_may_only_choose_one_of_the_events_own_posts(pg, unique):
    pair = _aggregator_then_organizer(pg, unique)
    duplicates.scan(pg, on=EVENT_DATE)
    stranger = _item(pg, _source(pg, unique, key="OTHER", role="ORGANIZER"),
                     f"https://other.test/{unique}")
    with pytest.raises(ValueError):
        duplicates.set_primary_source(pg, pair["agg_event"], stranger)
    with pytest.raises(LookupError):
        duplicates.set_primary_source(pg, 0, stranger)


def test_ruling_a_pair_distinct_gives_each_row_its_own_post_back(pg, unique):
    pair = _aggregator_then_organizer(pg, unique)
    duplicates.scan(pg, on=EVENT_DATE)
    duplicates.record_decision(pg, event_id=pair["org_event"], canonical_event_id=None,
                               decision=duplicates.DISTINCT, decided_by=duplicates.HUMAN,
                               rule="HUMAN_REVIEW")
    duplicates.reconcile_primary_source(pg, pair["agg_event"])
    agg = _row(pg, pair["agg_event"])
    assert agg["primary_source_item_id"] is None
    assert events_api.get_event(pg, pair["agg_event"])["source_link"]["url"] == pair["agg_url"]
    assert events_api.get_event(pg, pair["org_event"])["source_link"]["url"] == pair["org_url"]


# === 4. identity matching stays narrow =======================================

def test_same_title_on_another_date_is_never_the_same_event(pg, unique):
    pair = _aggregator_then_organizer(
        pg, unique, organizer_overrides={"event_date": (EVENT_DATE + timedelta(days=7)).isoformat()})
    duplicates.scan(pg, on=EVENT_DATE)
    duplicates.scan(pg, on=EVENT_DATE + timedelta(days=7))
    assert _row(pg, pair["agg_event"])["canonical_event_id"] is None
    assert _row(pg, pair["org_event"])["canonical_event_id"] is None
    assert _row(pg, pair["agg_event"])["primary_source_item_id"] is None


def test_same_date_different_venue_is_left_for_a_person_not_merged(pg, unique):
    pair = _aggregator_then_organizer(pg, unique, organizer_overrides={"venue": "다른 스튜디오"})
    found = duplicates.scan(pg, on=EVENT_DATE)
    assert found["auto_merged"] == 0
    assert _row(pg, pair["agg_event"])["primary_source_item_id"] is None


def test_same_organizer_venue_date_and_time_merge_and_the_organizer_represents(pg, unique):
    pair = _aggregator_then_organizer(pg, unique, organizer_overrides={"event_name": "완전히 다른 제목"})
    duplicates.scan(pg, on=EVENT_DATE)
    assert _row(pg, pair["org_event"])["canonical_event_id"] == pair["agg_event"]
    assert _row(pg, pair["agg_event"])["primary_source_item_id"] == pair["org_item"]


# === 5. Community -> Source Registry ==========================================

def _six(pg):
    existing = {g["code"] for g in master_data.list_genres(pg)}
    for code in cd.TARGET_GENRES:
        if code not in existing:
            master_data.create_genre(pg, code=code, name=code.title())
    return {g["code"]: g["genre_id"] for g in master_data.list_genres(pg)}


def _community(pg, unique, seoul_id, name=None):
    genres = _six(pg)
    return communities.create_community(pg, {
        "name": name or f"살사포유 {unique}", "region_id": seoul_id, "description": "",
        "homepage_url": "", "notes": "", "enabled": "1", "genre_ids": [genres["SALSA"]],
        "venue_ids": [],
    }, reviewer="tester")


def _discovered(pg, unique, *, platform="NAVER_CAFE", url=None, review_state="APPROVED",
                community_id=None, name=None):
    url = url or f"https://cafe.naver.com/salsa{unique}"
    ident = cd.identify(url)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO community_discovery_items (identity_key, platform, community_url, "
            "  title, candidate_name, review_state, registered_community_id, region_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, NULL) RETURNING item_id",
            (ident.key if ident else f"{platform.lower()}:{unique}", platform,
             ident.url if ident else url, "t", name or f"살사포유 {unique}", review_state,
             community_id),
        )
        return cur.fetchone()[0]


def test_an_approved_community_becomes_a_disabled_source_the_operator_still_has_to_enable(
        pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id)
    item_id = _discovered(pg, unique, community_id=community["community_id"])
    found = cd.propose_source(pg, item_id, reviewer="tester")
    source = found["source"]
    assert found["created"] is True
    assert source["enabled"] is False
    assert source["platform"] == "NAVER_CAFE" and source["source_role"] == "COMMUNITY"
    assert source["authority_level"] == "SECONDARY", "never PRIMARY_ORGANIZER by proposal alone"
    assert source["url"] == f"https://cafe.naver.com/salsa{unique}"
    assert source["source_key"].startswith("SRC-N-")
    config = source["config"]
    assert config["community_id"] == community["community_id"]
    assert config["discovery_item_id"] == item_id
    assert config["cafe_name_hint"] == community["name"]
    assert config["url_contains"] == [f"salsa{unique}"]
    assert config["board_type"] == "EVENT_PRIMARY"
    # v0.95.0: queries come from the genre's profile, anchored on the
    # community's distinctive name (genre/region/club words stripped), not
    # three fixed suffixes.
    from runtime import source_queries

    anchor = source_queries.core_name(community["name"])
    assert anchor and len(source["queries"]) >= 3
    assert all(q.startswith(anchor) for q in source["queries"])
    assert any(q.endswith(" 살사") for q in source["queries"])
    assert source["region_id"] == seoul_id and source["genre_id"] is not None
    assert cd.get_item(pg, item_id)["source_id"] == source["source_id"]
    assert cd.get_item(pg, item_id)["source_key"] == source["source_key"]
    # Disabled means the scheduler never picks it up (existing rule).
    assert source["source_id"] not in {s["source_id"] for s in sources.due_sources(pg)}


def test_proposing_twice_returns_the_same_source(pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id)
    item_id = _discovered(pg, unique, community_id=community["community_id"])
    first = cd.propose_source(pg, item_id)
    second = cd.propose_source(pg, item_id)
    assert second["created"] is False
    assert second["source"]["source_id"] == first["source"]["source_id"]


def test_a_source_already_registered_at_that_url_is_linked_not_duplicated(pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id)
    url = f"https://cafe.naver.com/salsa{unique}"
    existing = sources.create_source(
        pg, source_key=f"SRC-N-9{unique[-3:]}", name="hand registered", platform="NAVER_CAFE",
        source_role="COMMUNITY", url=url.upper(),
        config={"community_id": community["community_id"]},
    )
    item_id = _discovered(pg, unique, url=url, community_id=community["community_id"])
    found = cd.propose_source(pg, item_id)
    assert found["created"] is False
    assert found["source"]["source_id"] == existing["source_id"]
    assert cd.get_item(pg, item_id)["source_id"] == existing["source_id"]


def test_the_same_board_is_refused_for_a_different_community(pg, unique, seoul_id):
    owner = _community(pg, unique, seoul_id, name=f"주인 {unique}")
    other = _community(pg, unique, seoul_id, name=f"다른 {unique}")
    url = f"https://cafe.naver.com/salsa{unique}"
    sources.create_source(
        pg, source_key=f"SRC-N-8{unique[-3:]}", name="owner's board", platform="NAVER_CAFE",
        source_role="COMMUNITY", url=url, config={"community_id": owner["community_id"]},
    )
    item_id = _discovered(pg, unique, url=url, community_id=other["community_id"])
    with pytest.raises(cd.DiscoveryError, match="다른"):
        cd.propose_source(pg, item_id)


def test_only_a_registered_or_linked_candidate_on_a_collectable_platform_can_be_proposed(
        pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id)
    pending = _discovered(pg, unique, review_state="PENDING")
    with pytest.raises(cd.DiscoveryError):
        cd.propose_source(pg, pending)
    band = _discovered(pg, f"{unique}b", platform="BAND", url=f"https://band.us/band/{unique}",
                       community_id=community["community_id"])
    with pytest.raises(cd.DiscoveryError, match="플랫폼"):
        cd.propose_source(pg, band)


def test_a_daum_cafe_and_a_web_homepage_proposal_carry_their_own_collector_config(
        pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id)
    daum = _discovered(pg, unique, platform="DAUM_CAFE", url=f"https://cafe.daum.net/salsa{unique}",
                       community_id=community["community_id"])
    daum_source = cd.propose_source(pg, daum)["source"]
    assert daum_source["source_key"].startswith("SRC-D-")
    assert daum_source["config"]["url_contains"] == [f"salsa{unique}"]
    web = _discovered(pg, f"{unique}w", platform="WEB", url=f"https://salsa{unique}.example/",
                      community_id=community["community_id"])
    web_source = cd.propose_source(pg, web)["source"]
    assert web_source["source_key"].startswith("SRC-W-")
    assert web_source["config"]["parser"] == "board"
    assert web_source["config"]["board_urls"] == [f"https://salsa{unique}.example/"]
    assert web_source["queries"] == []
    # Registered disabled, so nothing collects from an unverified homepage.
    assert web_source["enabled"] is False


def test_next_source_key_continues_the_platforms_own_sequence(pg, unique):
    sources.create_source(pg, source_key="SRC-W-7777", name=f"x {unique}", platform="WEB",
                          source_role="DIRECTORY", url=f"https://seq{unique}.test/")
    assert sources.next_source_key(pg, "WEB") == "SRC-W-7778"
    assert sources.next_source_key(pg, "FACEBOOK").startswith("SRC-F-")


# === 6. the Direct/Public Web provider path itself ===========================

class _Response:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = type("H", (), {"get_content_charset": staticmethod(lambda: "utf-8")})()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_a_malformed_public_page_yields_no_posts_rather_than_an_error(monkeypatch):
    monkeypatch.setattr(web_discovery.acquisition, "robots_allows", lambda *a, **k: True)
    opener = lambda request, timeout: _Response(b"<html><body><p>not a board")  # noqa: E731
    assert web_discovery.discover("https://board.test/list", source_id="SRC-W-999",
                                  opener=opener) == []


def test_a_row_missing_its_date_or_title_is_skipped_not_guessed(monkeypatch):
    monkeypatch.setattr(web_discovery.acquisition, "robots_allows", lambda *a, **k: True)
    page = ("<td class=\"tit\" onclick=\"location.href='read.jsp?no=1'\">"
            "<p class=\"mw100\"></p></td><td>2026-01-01</td>"
            "<td class=\"tit\" onclick=\"location.href='read.jsp?no=2'\">"
            "<p class=\"mw100\">실제 공지</p></td><td>no-date-here</td>")
    assert web_discovery.parse_list(page, "https://board.test/list") == []


def test_a_network_error_surfaces_and_never_fabricates_posts(monkeypatch):
    import urllib.error

    monkeypatch.setattr(web_discovery.acquisition, "robots_allows", lambda *a, **k: True)

    def opener(request, timeout):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(urllib.error.URLError):
        web_discovery.discover("https://board.test/list", source_id="SRC-W-999", opener=opener)


def test_a_disallowed_page_is_never_fetched(monkeypatch):
    monkeypatch.setattr(web_discovery.acquisition, "robots_allows", lambda *a, **k: False)
    called = []

    def opener(request, timeout):
        called.append(request)
        return _Response(b"")

    with pytest.raises(web_discovery.DiscoveryError):
        web_discovery.discover("https://board.test/list", source_id="SRC-W-999", opener=opener)
    assert called == []


def test_an_unknown_parser_code_falls_back_to_the_plain_board_parser():
    assert collectors._web_discovery_module("no-such-parser") is web_discovery
    assert collectors._web_discovery_module(collectors.WEB_PARSER_BOARD) is web_discovery


def test_a_direct_web_source_needs_no_credential_and_leaks_none():
    assert collectors.missing_credentials("WEB") == []
    from runtime import collector_errors

    leaked = "X-NCP-APIGW-API-KEY: abc123 KakaoAK sk-SECRET"
    assert "abc123" not in collector_errors.redact(leaked)
    assert "sk-SECRET" not in collector_errors.redact(leaked)


# === 7. Admin ================================================================

_AUTH = ("tester", "test-only")


@pytest.fixture
def web(pg, env, monkeypatch):
    from runtime import admin, app as app_module, discovery_admin, public
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ADMIN_USERNAME", _AUTH[0])
    monkeypatch.setenv("ADMIN_PASSWORD", _AUTH[1])

    @contextlib.contextmanager
    def shared():
        yield pg

    for module in (admin, discovery_admin, public):
        monkeypatch.setattr(module, "_connection", shared)
    monkeypatch.setattr(app_module, "_settings", None)
    client = TestClient(app_module.app, raise_server_exceptions=False)
    client.auth = _AUTH
    return client


def test_the_admin_shows_primary_and_supporting_sources_and_lets_a_person_choose(pg, unique, web):
    pair = _aggregator_then_organizer(pg, unique)
    duplicates.scan(pg, on=EVENT_DATE)
    page = web.get(f"/admin/events/{pair['agg_event']}/sources")
    assert page.status_code == 200
    assert "대표 출처" in page.text and "PRIMARY_ORGANIZER" in page.text
    assert f"folded #{pair['org_event']}" in page.text
    assert pair["org_url"] in page.text and pair["agg_url"] in page.text

    response = web.post(f"/admin/events/{pair['agg_event']}/primary-source",
                        data={"source_item_id": str(pair["agg_item"])}, follow_redirects=False)
    assert response.status_code == 303
    assert _row(pg, pair["agg_event"])["primary_source_decided_by"] == duplicates.HUMAN
    reset = web.post(f"/admin/events/{pair['agg_event']}/primary-source",
                     data={"action": "reset"}, follow_redirects=False)
    assert reset.status_code == 303
    assert _row(pg, pair["agg_event"])["primary_source_item_id"] == pair["org_item"]

    listing = web.get("/admin/events")
    assert listing.status_code == 200 and "대표 출처" in listing.text


def test_the_public_detail_marks_the_representative_post(pg, unique, web):
    pair = _aggregator_then_organizer(pg, unique)
    duplicates.scan(pg, on=EVENT_DATE)
    page = web.get(f"/events/{pair['agg_event']}")
    assert page.status_code == 200
    assert "대표 출처" in page.text and "출처 2건" in page.text


def test_the_discovery_screen_offers_and_records_a_source_proposal(pg, unique, seoul_id, web):
    community = _community(pg, unique, seoul_id)
    item_id = _discovered(pg, unique, community_id=community["community_id"])
    listing = web.get(f"/admin/community-discovery?state=APPROVED")
    assert listing.status_code == 200
    response = web.post(f"/admin/community-discovery/items/{item_id}/propose-source",
                        data={"return_to": "/admin/community-discovery"}, follow_redirects=False)
    assert response.status_code == 303
    assert "SRC-N-" in response.headers["location"]
    assert cd.get_item(pg, item_id)["source_id"] is not None
