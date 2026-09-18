"""v0.95.0 Direct Community/Organizer source coverage expansion.

v0.94.0 settled how the most direct post represents an Event; this release
is about having more direct posts to choose from: genre-aware query
profiles for proposed sources, proposals for Communities that never went
through discovery, yield diagnosis and Region x Genre coverage gaps - all
on the existing Source Registry / Test / Enable / Reconciliation path,
which is re-asserted here unchanged. Fixtures only; no network.
"""

from __future__ import annotations

import contextlib
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from runtime import (
    collectors,
    communities,
    duplicates,
    events_api,
    master_data,
    normalization,
    source_ops,
    source_queries,
    sources,
)
from runtime import community_discovery as cd

EVENT_DATE = date(2026, 11, 10)


# === 1. query profiles =======================================================

@pytest.mark.parametrize("genre, must_have", [
    ("TANGO", {"밀롱가", "프락티카"}),
    ("SALSA", {"살사", "바차타", "소셜"}),
    ("SWING", {"스윙", "린디합", "발보아"}),
    ("BALBOA", {"발보아", "스윙"}),
    ("BACHATA", {"바차타", "살사"}),
    ("KIZOMBA", {"키좀바", "소셜"}),
])
def test_each_genre_profile_speaks_its_own_scenes_words(genre, must_have):
    assert must_have <= set(source_queries.profile_for(genre))
    assert genre in source_queries.QUERY_PROFILES


def test_the_six_target_genres_all_have_a_profile():
    assert set(cd.TARGET_GENRES) <= set(source_queries.QUERY_PROFILES)


def test_an_unknown_genre_falls_back_to_the_generic_community_vocabulary():
    assert source_queries.profile_for("POLKA") == source_queries.DEFAULT_PROFILE
    assert source_queries.profile_for(None) == source_queries.DEFAULT_PROFILE
    assert "정모" in source_queries.DEFAULT_PROFILE


@pytest.mark.parametrize("name, core", [
    ("홍대 탱고 동호회 OSIK", "OSIK"),
    ("진주 라틴 피루나 댄스", "라틴 피루나"),
    ("전주살사 바차타 라틴크루즈", "라틴크루즈"),
    ("부산 스윙 동호회", None),
    ("살사베이시스(Salsa Basis)", "베이시스"),
])
def test_core_name_strips_region_genre_and_club_words(name, core):
    assert source_queries.core_name(name) == core


def test_queries_are_anchored_on_the_community_name_and_wider_than_before():
    old = ["홍대 탱고 동호회 OSIK 정모", "홍대 탱고 동호회 OSIK 파티", "홍대 탱고 동호회 OSIK 공지"]
    new = source_queries.queries_for("TANGO", name="홍대 탱고 동호회 OSIK")
    assert new[0] == "OSIK"
    assert "OSIK 밀롱가" in new and "OSIK 프락티카" in new
    assert len(new) > len(old)
    assert len(new) <= source_queries.MAX_QUERIES
    assert all(q.startswith("OSIK") for q in new)


def test_region_and_genre_combine_when_no_community_name_anchors_the_search():
    queries = source_queries.queries_for("SALSA", region_name="부산")
    assert queries[0] == "부산 살사" and all(q.startswith("부산 ") for q in queries)
    plain = source_queries.queries_for("SALSA")
    assert plain[0] == "살사" and "부산" not in " ".join(plain)


def test_operator_extra_queries_come_first_and_duplicates_collapse():
    queries = source_queries.queries_for(
        "TANGO", name="홍대 탱고 동호회 OSIK",
        extra=["오식이 밀롱가", "  OSIK   밀롱가 ", "osik 밀롱가", ""])
    assert queries[:2] == ["오식이 밀롱가", "OSIK 밀롱가"]
    assert queries.count("OSIK 밀롱가") == 1
    assert len(queries) == len({source_queries.normalize(q) for q in queries})


def test_merge_keeps_every_operator_query_and_adds_the_profile_behind_it():
    merged = source_queries.merge_queries(["OSIK 프락티카", "osik 밀롱가"],
                                          source_queries.queries_for("TANGO", name="OSIK 탱고"))
    assert merged[:2] == ["OSIK 프락티카", "osik 밀롱가"]
    assert "OSIK" in merged and merged.count("OSIK 밀롱가") == 0  # already there, case-insensitively


def test_a_name_made_only_of_generic_words_still_gets_genre_queries():
    queries = source_queries.queries_for("SWING", name="부산 스윙 동호회", region_name="부산")
    assert queries[0] == "부산 스윙"


# === 2. Community -> Source proposals ========================================

def _six(pg):
    existing = {g["code"] for g in master_data.list_genres(pg)}
    for code in cd.TARGET_GENRES:
        if code not in existing:
            master_data.create_genre(pg, code=code, name=code.title())
    return {g["code"]: g["genre_id"] for g in master_data.list_genres(pg)}


def _community(pg, unique, seoul_id, *, name, genre="TANGO", homepage=None):
    genres = _six(pg)
    return communities.create_community(pg, {
        "name": name, "region_id": seoul_id, "description": "", "homepage_url": homepage or "",
        "notes": "", "enabled": "1", "genre_ids": [genres[genre]], "venue_ids": [],
    }, reviewer="tester")


def _discovered(pg, unique, *, platform, url, community_id, name, review_state="APPROVED"):
    ident = cd.identify(url)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO community_discovery_items (identity_key, platform, community_url, "
            "  title, candidate_name, review_state, registered_community_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING item_id",
            (ident.key, platform, ident.url, "t", name, review_state, community_id))
        return cur.fetchone()[0]


def test_a_tango_cafe_proposal_carries_the_tango_profile(pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id, name=f"홍대 탱고 동호회 OSIK{unique}")
    item = _discovered(pg, unique, platform="NAVER_CAFE", url=f"https://cafe.naver.com/osik{unique}",
                       community_id=community["community_id"], name=community["name"])
    source = cd.propose_source(pg, item)["source"]
    assert source["enabled"] is False and source["authority_level"] == "SECONDARY"
    assert source["config"]["community_id"] == community["community_id"]
    assert any("밀롱가" in q for q in source["queries"])
    assert any("프락티카" in q for q in source["queries"])
    assert not any("파티" in q for q in source["queries"]), "not the old fixed suffixes"
    assert len(source["queries"]) > 3
    assert "TANGO query profile" in source["notes"]


def test_a_salsa_and_a_swing_cafe_get_their_own_profiles(pg, unique, seoul_id):
    salsa = _community(pg, unique, seoul_id, name=f"인천살사 엘마르{unique}", genre="SALSA")
    swing = _community(pg, unique, seoul_id, name=f"비바스윙{unique}", genre="SWING")
    salsa_item = _discovered(pg, unique, platform="DAUM_CAFE", url=f"https://cafe.daum.net/elmar{unique}",
                             community_id=salsa["community_id"], name=salsa["name"])
    swing_item = _discovered(pg, unique, platform="NAVER_CAFE", url=f"https://cafe.naver.com/viva{unique}",
                             community_id=swing["community_id"], name=swing["name"])
    salsa_source = cd.propose_source(pg, salsa_item)["source"]
    swing_source = cd.propose_source(pg, swing_item)["source"]
    assert any("바차타" in q for q in salsa_source["queries"])
    assert any("린디합" in q for q in swing_source["queries"])
    assert not any("밀롱가" in q for q in salsa_source["queries"] + swing_source["queries"])


def test_a_registered_community_without_a_candidate_can_be_proposed_directly(pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id, name=f"라틴 피루나 {unique}", genre="SALSA",
                           homepage=f"https://cafe.naver.com/piruna{unique}")
    before = {c["community_id"] for c in source_ops.communities_without_source(pg)}
    assert community["community_id"] in before
    found = cd.propose_source_for_community(pg, community["community_id"], reviewer="tester")
    source = found["source"]
    assert found["created"] is True
    assert source["platform"] == "NAVER_CAFE" and source["enabled"] is False
    assert source["config"]["community_id"] == community["community_id"]
    assert "discovery_item_id" not in source["config"]
    assert source["config"]["url_contains"] == [f"piruna{unique}"]
    assert any("살사" in q for q in source["queries"])
    after = {c["community_id"] for c in source_ops.communities_without_source(pg)}
    assert community["community_id"] not in after
    # Idempotent, and a later discovery candidate for the same Community is
    # linked to the same source.
    again = cd.propose_source_for_community(pg, community["community_id"])
    assert again["created"] is False and again["source"]["source_id"] == source["source_id"]


def test_a_community_whose_page_is_already_a_source_reuses_it(pg, unique, seoul_id):
    url = f"https://cafe.daum.net/reuse{unique}"
    community = _community(pg, unique, seoul_id, name=f"재사용 {unique}", homepage=url)
    existing = sources.create_source(
        pg, source_key=f"SRC-D-7{unique[-3:]}", name="hand registered", platform="DAUM_CAFE",
        source_role="COMMUNITY", url=url.upper(), config={"community_id": community["community_id"]})
    found = cd.propose_source_for_community(pg, community["community_id"])
    assert found["created"] is False and found["source"]["source_id"] == existing["source_id"]
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM sources WHERE lower(url) = lower(%s)", (url,))
        assert cur.fetchone()[0] == 1


def test_another_communitys_board_is_refused_for_a_direct_proposal_too(pg, unique, seoul_id):
    url = f"https://cafe.naver.com/owned{unique}"
    owner = _community(pg, unique, seoul_id, name=f"주인 {unique}")
    other = _community(pg, unique, seoul_id, name=f"다른 {unique}", homepage=url)
    sources.create_source(pg, source_key=f"SRC-N-7{unique[-3:]}", name="owner's", platform="NAVER_CAFE",
                          source_role="COMMUNITY", url=url, config={"community_id": owner["community_id"]})
    with pytest.raises(cd.DiscoveryError, match="다른"):
        cd.propose_source_for_community(pg, other["community_id"])


def test_a_community_with_no_usable_public_page_is_listed_but_not_proposable(pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id, name=f"밴드만 {unique}",
                           homepage=f"https://band.us/band/{unique}")
    row = next(c for c in source_ops.communities_without_source(pg)
               if c["community_id"] == community["community_id"])
    assert row["proposable"] is False and row["platform"] == "BAND"
    with pytest.raises(cd.DiscoveryError):
        cd.propose_source_for_community(pg, community["community_id"])


def test_a_human_primary_organizer_promotion_survives_a_requery(pg, unique, seoul_id):
    community = _community(pg, unique, seoul_id, name=f"공식 {unique}",
                           homepage=f"https://cafe.naver.com/official{unique}")
    source = cd.propose_source_for_community(pg, community["community_id"])["source"]
    promoted = sources.update_source(pg, source["source_id"], authority_level="PRIMARY_ORGANIZER",
                                     queries=["공식 밀롱가 특별"])
    merged = cd.suggested_queries(pg, promoted)
    assert merged[0] == "공식 밀롱가 특별" and len(merged) > 1
    updated = sources.update_source(pg, source["source_id"], queries=merged)
    assert updated["authority_level"] == "PRIMARY_ORGANIZER"
    assert updated["queries"][0] == "공식 밀롱가 특별"
    assert updated["enabled"] is False


def test_proposals_from_the_approved_backlog_increase_with_direct_proposals(pg, unique, seoul_id):
    """Section 34 (2): the same approved backlog yields more proposals once
    Communities registered without a candidate can be proposed too."""
    with_item = _community(pg, unique, seoul_id, name=f"후보있음 {unique}")
    _discovered(pg, unique, platform="NAVER_CAFE", url=f"https://cafe.naver.com/withitem{unique}",
                community_id=with_item["community_id"], name=with_item["name"])
    without_item = _community(pg, unique, seoul_id, name=f"후보없음 {unique}",
                              homepage=f"https://cafe.daum.net/noitem{unique}")
    mine = {with_item["community_id"], without_item["community_id"]}
    backlog = [c for c in source_ops.communities_without_source(pg) if c["community_id"] in mine]
    assert len(backlog) == 2
    # v0.94.0 could only propose from a candidate: one of the two.
    from_candidates = [c for c in backlog if c["discovery_item_id"]]
    assert len(from_candidates) == 1
    # v0.95.0 proposes both.
    proposed = [cd.propose_source_for_community(pg, c["community_id"])["source"] for c in backlog]
    assert len(proposed) == 2 and all(s["enabled"] is False for s in proposed)
    assert not [c for c in source_ops.communities_without_source(pg) if c["community_id"] in mine]


# === 3. acquisition through the widened profile ==============================

def _source_row(pg, unique, *, platform="NAVER_CAFE", queries, hint, token):
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'TANGO'")
        tango = cur.fetchone()[0]
    return sources.create_source(
        pg, source_key=f"SRC-N-6{unique[-3:]}", name=f"test cafe {unique}", platform=platform,
        source_role="COMMUNITY", url=f"https://cafe.naver.com/{token}", genre_id=tango,
        authority_level="SECONDARY", queries=queries,
        config={"cafe_name_hint": hint, "url_contains": [token], "board_type": "EVENT_PRIMARY"},
        enabled=True)


def _record(url, title, cafe="오식이 탱고 카페", body="", published="2026-11-01T10:00:00+09:00"):
    from src.collectors.base import RawPostRecord  # engine package, on sys.path via _fake_naver

    return RawPostRecord(source_id="X", platform="NAVER_CAFE", source_url=url, title=title,
                         body=body, published_at=published, cafe_name=cafe, raw_json="{}")


def _fake_naver(monkeypatch, settings, responses):
    """collector.search(query, ...) answers from `responses[query]`."""
    calls = []
    collectors._engine_on_path(settings)
    from src.collectors.naver import NaverSearchCollector

    def search(self, query, **kw):
        calls.append(query)
        result = responses.get(query, [])
        if isinstance(result, Exception):
            raise result
        return list(result)
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")
    monkeypatch.setattr(NaverSearchCollector, "search", search)
    return calls


def test_the_wider_profile_finds_posts_the_three_suffixes_missed(settings, monkeypatch):
    token = "osiktango"
    collectors._engine_on_path(settings)
    milonga = _record(f"https://cafe.naver.com/{token}/501", "11월 정기 밀롱가 안내 (11/14 금)")
    practica = _record(f"https://cafe.naver.com/{token}/502", "프락티카 11/12 저녁 8시")
    other_cafe = _record("https://cafe.naver.com/othercafe/9", "OSIK 밀롱가 후기", cafe="다른 카페")
    responses = {"OSIK 정모": [], "OSIK 파티": [], "OSIK 공지": [],
                 "OSIK 밀롱가": [milonga, other_cafe], "OSIK 프락티카": [practica, milonga]}
    calls = _fake_naver(monkeypatch, settings, responses)
    source = {"source_id": 1, "source_key": "SRC-N-TEST", "platform": "NAVER_CAFE",
              "source_role": "COMMUNITY", "authority_level": "SECONDARY", "enabled": True,
              "url": f"https://cafe.naver.com/{token}", "genre_id": None, "region_id": None,
              "collection_interval_minutes": 60, "notes": None,
              "config": {"cafe_name_hint": "오식이", "url_contains": [token], "board_type": "EVENT_PRIMARY"},
              "queries": ["OSIK 정모", "OSIK 파티", "OSIK 공지"]}
    narrow = collectors.collect(settings, source, mode=collectors.MODE_LIVE)
    assert narrow.items == [] and narrow.search_hits == 0
    wide = dict(source, queries=source_queries.queries_for("TANGO", name="홍대 탱고 동호회 OSIK"))
    result = collectors.collect(settings, wide, mode=collectors.MODE_LIVE)
    urls = [item.url for item in result.items]
    # Two real posts, once each (the milonga matched two queries), the other
    # cafe's post excluded by the boundary; hits counted before the boundary.
    assert sorted(urls) == sorted([milonga.source_url, practica.source_url])
    assert result.search_hits == 4
    assert len(calls) == 3 + len(wide["queries"])


def test_zero_results_malformed_and_network_failures_stay_distinguishable(settings, monkeypatch):
    import urllib.error

    from runtime import collector_errors

    token = "quietcafe"
    base = {"source_id": 1, "source_key": "SRC-N-Q", "platform": "NAVER_CAFE", "source_role": "COMMUNITY",
            "authority_level": "SECONDARY", "enabled": True, "url": f"https://cafe.naver.com/{token}",
            "genre_id": None, "region_id": None, "collection_interval_minutes": 60, "notes": None,
            "config": {"cafe_name_hint": "quiet", "url_contains": [token]}, "queries": ["quiet 정모"]}
    _fake_naver(monkeypatch, settings, {"quiet 정모": []})
    empty = collectors.collect(settings, base, mode=collectors.MODE_LIVE)
    assert empty.items == [] and empty.search_hits == 0
    _fake_naver(monkeypatch, settings, {"quiet 정모": [_record("", "", cafe="")]})
    malformed = collectors.collect(settings, base, mode=collectors.MODE_LIVE)
    assert malformed.items == [] and malformed.search_hits == 1
    _fake_naver(monkeypatch, settings, {"quiet 정모": urllib.error.URLError("refused")})
    with pytest.raises(Exception) as raised:
        collectors.collect(settings, base, mode=collectors.MODE_LIVE)
    classified = collector_errors.classify(raised.value)
    assert "secret" not in classified.summary().lower()


# === 4. yield diagnosis and coverage gaps =====================================

def _diag(source, outcome, run):
    return source_ops.yield_diagnosis(source, outcome, run)[0]


def test_zero_events_are_five_different_situations():
    on = {"enabled": True, "last_detail": None}
    ok_run = {"status": "PASS", "discovered_count": 3, "new_count": 3, "error": None}
    assert _diag({"enabled": False}, {}, None) == source_ops.DIAG_DISABLED
    assert _diag(on, {}, None) == source_ops.DIAG_NEVER_RUN
    assert _diag(on, {}, {"status": "AUTH_FAILED", "error": "401"}) == source_ops.DIAG_COLLECTOR_FAILURE
    assert _diag(dict(on, last_detail="live: 0 found, 0 search hits"), {"items": 0},
                 dict(ok_run, discovered_count=0)) == source_ops.DIAG_QUERY_TOO_NARROW
    assert _diag(dict(on, last_detail="live: 0 found, 80 search hits"), {"items": 0},
                 dict(ok_run, discovered_count=0)) == source_ops.DIAG_BOUNDARY_TOO_STRICT
    assert _diag(on, {"items": 3, "fetched": 0, "blocked": 3, "events": 0},
                 ok_run) == source_ops.DIAG_METADATA_ONLY_NO_EVENT
    assert _diag(on, {"items": 3, "fetched": 3, "blocked": 0, "events": 0},
                 ok_run) == source_ops.DIAG_NON_EVENT_CONTENT
    assert _diag(on, {"items": 3, "fetched": 3, "events": 2, "upcoming_events": 0},
                 ok_run) == source_ops.DIAG_PAST_ONLY
    assert _diag(on, {"items": 3, "fetched": 3, "events": 2, "upcoming_events": 1},
                 ok_run) == source_ops.DIAG_HEALTHY
    assert set(source_ops.DIAG_LABELS) >= {source_ops.DIAG_QUERY_TOO_NARROW,
                                           source_ops.DIAG_BOUNDARY_TOO_STRICT}


def test_the_intake_detail_records_search_hits_for_the_diagnosis(pg, unique, settings, monkeypatch):
    from scheduler import intake_job

    token = f"hits{unique}"
    source = _source_row(pg, unique, queries=["hits 정모"], hint="hits", token=token)
    stranger = _record("https://cafe.naver.com/other/1", "정모", cafe="other")
    _fake_naver(monkeypatch, settings, {"hits 정모": [stranger, stranger]})
    monkeypatch.setattr(intake_job.quota, "check", lambda *a, **k: None)
    intake_job.collect_source(settings, pg, source)
    refreshed = sources.get_source(pg, source["source_id"])
    assert "2 search hits" in (refreshed["last_detail"] or "")
    outcome = sources.acquisition_outcomes(pg).get(source["source_id"], {})
    run = source_ops.last_run_per_source(pg)[source["source_id"]]
    assert _diag(refreshed, outcome, run) == source_ops.DIAG_BOUNDARY_TOO_STRICT
    op = next(o for o in source_ops.overview(pg) if o["source_id"] == source["source_id"])
    assert op["diagnosis"] == source_ops.DIAG_BOUNDARY_TOO_STRICT and op["last_run_status"] == "PASS"


def test_coverage_gaps_count_communities_without_a_source_per_region_and_genre(pg, unique, seoul_id):
    genres = _six(pg)
    _community(pg, unique, seoul_id, name=f"gap A {unique}", genre="KIZOMBA")
    linked = _community(pg, unique, seoul_id, name=f"gap B {unique}", genre="KIZOMBA",
                        homepage=f"https://cafe.naver.com/gapb{unique}")
    cd.propose_source_for_community(pg, linked["community_id"])
    row = next(g for g in source_ops.coverage_gaps(pg)
               if g["genre_code"] == "KIZOMBA" and g["region_code"] == "KR-SEOUL")
    assert row["communities"] >= 2
    assert row["communities_with_source"] >= 1
    assert row["communities_without_source"] >= 1
    assert row["enabled_direct_sources"] >= 0 and row["upcoming_direct_events"] >= 0
    assert genres["KIZOMBA"]


# === 5. v0.94.0 contracts, re-asserted under the new coverage ==============

def _src(pg, unique, key, role, authority):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO sources (source_key, name, platform, source_role, url, authority_level, "
                    "enabled) VALUES (%s, %s, 'WEB', %s, %s, %s, TRUE) RETURNING source_id",
                    (f"{key}-{unique}", key, role, f"https://{key.lower()}.test/{unique}", authority))
        return cur.fetchone()[0]


def _item(pg, source_id, url, external=False):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO source_items (source_id, external_id, url, content_hash, raw) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING source_item_id",
                    (source_id, url, url, url, json.dumps({"external_promotion": external})))
        return cur.fetchone()[0]


def _event(pg, unique, suffix, item, **over):
    payload = {"candidate_id": int(f"{unique[-6:]}{suffix}"), "post_id": 1,
               "source_url": f"https://post.test/{unique}-{suffix}", "event_name": f"밀롱가 {unique}",
               "event_type": "MILONGA", "event_date": EVENT_DATE.isoformat(), "start_time": "20:00",
               "end_time": "23:00", "end_day_offset": 0, "venue": f"venue-{unique}", "fee": 10000,
               "candidate_status": "POSSIBLE", "provenance": normalization.PROVENANCE_LIVE,
               "time_evidence": "EXPLICIT"}
    payload.update(over)
    stored = normalization.normalize_candidate(pg, payload)
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET source_item_id = %s WHERE event_id = %s", (item, stored["event_id"]))
    return stored["event_id"]


def _row(pg, event_id):
    with pg.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE event_id = %s", (event_id,))
        return dict(zip([c.name for c in cur.description], cur.fetchone()))


def test_aggregator_first_direct_later_still_keeps_the_id_and_elects_the_direct_post(pg, unique):
    agg_item = _item(pg, _src(pg, unique, "TANGONOW", "DIRECTORY", "AGGREGATOR"),
                     f"https://tangonow.test/{unique}")
    org_item = _item(pg, _src(pg, unique, "ORG", "COMMUNITY", "PRIMARY_ORGANIZER"),
                     f"https://org.test/{unique}")
    agg_event = _event(pg, unique, "1", agg_item, fee=None, end_time=None,
                       source_url=f"https://tangonow.test/{unique}")
    org_event = _event(pg, unique, "2", org_item, dj="DJ", fee=8000,
                       source_url=f"https://org.test/{unique}")
    duplicates.scan(pg, on=EVENT_DATE)
    agg = _row(pg, agg_event)
    assert agg["canonical_event_id"] is None
    assert _row(pg, org_event)["canonical_event_id"] == agg_event
    assert agg["primary_source_item_id"] == org_item
    posts = duplicates.sources_of(pg, agg_event)
    assert {p["source_url"] for p in posts} == {f"https://tangonow.test/{unique}", f"https://org.test/{unique}"}
    shown = events_api.get_event(pg, agg_event)
    assert shown["id"] == agg_event and shown["source_link"]["url"] == f"https://org.test/{unique}"
    wins = source_ops.representative_yield(pg)
    with pg.cursor() as cur:
        cur.execute("SELECT source_id FROM source_items WHERE source_item_id = %s", (org_item,))
        org_source = cur.fetchone()[0]
    if EVENT_DATE >= date.today():
        assert wins[org_source]["wins"] >= 1


def test_an_external_promotion_post_never_reaches_primary_organizer_or_moves_region(pg, unique):
    agg_item = _item(pg, _src(pg, unique, "MILTANG", "DIRECTORY", "AGGREGATOR"),
                     f"https://miltang.test/{unique}")
    promo_item = _item(pg, _src(pg, unique, "CAFE", "COMMUNITY", "PRIMARY_ORGANIZER"),
                       f"https://cafe.test/{unique}", external=True)
    agg_event = _event(pg, unique, "1", agg_item)
    _event(pg, unique, "2", promo_item)
    region_before = _row(pg, agg_event)["region_id"]
    duplicates.scan(pg, on=EVENT_DATE)
    agg = _row(pg, agg_event)
    assert agg["canonical_event_id"] is None and agg["region_id"] == region_before
    assert events_api.get_event(pg, agg_event)["source_evidence"]["class"] == "COMMUNITY_PROMOTION"


# === 6. Admin ================================================================

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


def test_the_discovery_screen_lists_unlinked_communities_and_proposes_in_place(pg, unique, seoul_id, web):
    community = _community(pg, unique, seoul_id, name=f"화면 {unique}",
                           homepage=f"https://cafe.naver.com/screen{unique}")
    page = web.get("/admin/community-discovery")
    assert page.status_code == 200
    assert "수집 Source가 없는 동호회" in page.text and f"화면 {unique}" in page.text
    assert "coverage gap" in page.text
    response = web.post(f"/admin/community-discovery/communities/{community['community_id']}/propose-source",
                        data={"return_to": "/admin/community-discovery"}, follow_redirects=False)
    assert response.status_code == 303 and "SRC-N-" in response.headers["location"]
    assert not [c for c in source_ops.communities_without_source(pg)
                if c["community_id"] == community["community_id"]]


def test_the_sources_screen_offers_query_profile_and_shows_the_diagnosis(pg, unique, web):
    source = _source_row(pg, unique, queries=["mine 정모"], hint="mine", token=f"mine{unique}")
    text = ""
    for number in range(1, 8):  # the shared table may run to several pages
        page = web.get(f"/admin/sources?page={number}")
        assert page.status_code == 200
        text = page.text
        if source["source_key"] in text:
            break
    assert source["source_key"] in text
    row = text[text.index(source["source_key"]):][:6000]
    assert "Query profile" in row and "미실행" in row
    response = web.post(f"/admin/sources/{source['source_id']}/requery", follow_redirects=False)
    assert response.status_code == 303
    refreshed = sources.get_source(pg, source["source_id"])
    assert refreshed["queries"][0] == "mine 정모" and len(refreshed["queries"]) > 1
    assert any("밀롱가" in q for q in refreshed["queries"])
