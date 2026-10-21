"""v0.96.44 - one festival, two sources, two dates: laid out for a person.

The duplicate rules compare only events that share a date (`duplicates.scan`
buckets by `event_date`; `duplicates.classify` returns None for two dates), so
on Production at v0.96.43 Miltang's `2026 Seoul Tango Week` (2026-11-11 ~
2026-11-16, El Tango, venue 4223) and TangoNOW's `SEOUL TANGO WEEK 2026`
(from 2026-11-12, `ELTANGO · Seoul Tango Academy`, unresolved) were both
listed and never compared. `event_conflicts` finds such a pair and the
Conflicts pages compare it - reading only: no table, no verdict, no merge.

The KOREA SPECIAL TANGO WEEK family is the false positive to avoid: the
series row, its (포항) and (홍대) programmes, and the nights inside them
(POHANG WELCOME MILONGA, SEOUL GRAND MILONGA) share words and dates and are
not one festival.

The pure rules are tested on plain dicts; the rest runs against the real
tables inside the `pg` fixture's rolled-back transaction, with the v0.96.42
pipeline fixture standing in for the database the Admin reads.
"""

from __future__ import annotations

import json
import re
from datetime import date, time, timedelta

import pytest

from runtime import content_store, duplicates, event_conflicts, events_api, sources
from tests.conftest import register_venue
from tests.test_v09642_source_revision import client, pipe  # noqa: F401 - fixtures
from tests.test_v09643_article_refresh import ktango  # noqa: F401 - fixture

EC = event_conflicts
POST_FORM = re.compile(r"<form[^>]*method=[\"']?post", re.IGNORECASE)


def _festival(event_id, **overrides):
    base = {
        "event_id": event_id,
        "event_name": "2026 Seoul Tango Week",
        "event_type": "FESTIVAL",
        "event_date": date(2026, 11, 11),
        "end_date": date(2026, 11, 16),
        "venue_id": 4223,
        "venue_text": "El Tango (엘땅고) (서울 서초구 주흥길 12)",
        "region_id": 2,
        "genre_id": 1,
        "review_state": "PENDING",
        "source_id": 5,
    }
    base.update(overrides)
    return base


STW_MILTANG = _festival(1628795)
STW_TANGONOW = _festival(1629292, event_name="SEOUL TANGO WEEK 2026",
                         event_date=date(2026, 11, 12), end_date=None, venue_id=None,
                         venue_text="ELTANGO · Seoul Tango Academy", region_id=None,
                         source_id=2)


# --- the name -------------------------------------------------------------------

def test_word_order_case_and_year_do_not_change_the_name():
    assert EC.name_key("2026 Seoul Tango Week") == EC.name_key("SEOUL TANGO WEEK 2026")
    assert EC.name_key("2026년 Seoul-Tango Week!") == EC.name_key("seoul tango week 2026")
    assert EC.name_key("SEOUL TANGO WEEK 2026")[1] == frozenset({"2026"})


def test_a_programme_qualifier_is_part_of_the_name():
    series = EC.name_key("KOREA SPECIAL TANGO WEEK 2026")[0]
    pohang = EC.name_key("KOREA SPECIAL TANGO WEEK 2026 (포항)")[0]
    hongdae = EC.name_key("KOREA SPECIAL TANGO WEEK 2026 (홍대)")[0]
    assert len({series, pohang, hongdae}) == 3


# --- positive cases ---------------------------------------------------------------

def test_seoul_tango_week_is_a_review_candidate_and_nothing_more():
    found = EC.classify(STW_MILTANG, STW_TANGONOW)
    assert found["conflicts"] == [EC.DATE_CONFLICT, EC.VENUE_UNRESOLVED]
    assert found["assessment"] == EC.POSSIBLE_SAME_EVENT
    assert found["review"] == EC.HUMAN_REVIEW_REQUIRED
    assert found["gap_days"] == 0
    assert EC.classify(STW_TANGONOW, STW_MILTANG)["conflicts"] == found["conflicts"]


def test_the_duplicate_rules_never_see_it():
    """The blind spot itself: two dates are not compared by the scanner."""
    assert duplicates.classify(STW_MILTANG, STW_TANGONOW) is None


def test_when_both_sources_state_periods_that_disagree_it_says_so():
    left = dict(STW_MILTANG, source_period={"start": "2026-11-11", "end": "2026-11-16"})
    right = dict(STW_TANGONOW, source_period={"start": "2026-11-12"})
    assert EC.SOURCE_EVIDENCE_CONFLICT in EC.classify(left, right)["conflicts"]


def test_same_first_day_different_stated_last_days_is_a_range_conflict():
    other = _festival(2, end_date=date(2026, 11, 15), source_id=2)
    found = EC.classify(STW_MILTANG, other)
    assert found["conflicts"] == [EC.DATE_RANGE_CONFLICT]
    assert found["venue"] == "SAME_RESOLVED_VENUE"


def test_same_first_day_and_compatible_periods_are_left_to_the_duplicate_rules():
    """Busan Tango Festival: TangoNOW states the start, Miltang the period, one
    resolved venue - the scanner folds that (SAME_DATE_VENUE_FESTIVAL)."""
    start_only = _festival(2, end_date=None, source_id=2)
    assert EC.classify(STW_MILTANG, start_only) is None
    finding = duplicates.classify(STW_MILTANG, start_only)
    assert finding["rule"] == duplicates.RULE_SAME_DATE_VENUE_FESTIVAL and finding["auto"]


def test_same_day_different_places_stays_the_duplicate_rules_question():
    elsewhere = _festival(2, end_date=None, venue_id=99, venue_text="다른 곳", source_id=2)
    assert EC.classify(STW_MILTANG, elsewhere) is None
    assert duplicates.classify(STW_MILTANG, elsewhere)["rule"] == \
        duplicates.RULE_SAME_DATE_FESTIVAL_PLACE_DIFFERS


def test_two_resolved_venues_that_differ_are_a_venue_conflict_not_a_possible_match():
    moved = _festival(2, event_date=date(2026, 11, 12), venue_id=99, venue_text="다른 곳",
                      source_id=2)
    found = EC.classify(STW_MILTANG, moved)
    assert EC.VENUE_CONFLICT in found["conflicts"]
    assert found["assessment"] == EC.INSUFFICIENT_EVIDENCE


def test_periods_a_little_apart_are_a_question_with_insufficient_evidence():
    later = dict(STW_TANGONOW, event_date=date(2026, 11, 18))
    found = EC.classify(STW_MILTANG, later)
    assert found["gap_days"] == 2 and found["assessment"] == EC.INSUFFICIENT_EVIDENCE


# --- negative cases ---------------------------------------------------------------

@pytest.mark.parametrize("other", [
    pytest.param(dict(STW_TANGONOW, event_name="SEOUL TANGO WEEK 2027",
                      event_date=date(2027, 11, 12)), id="another edition"),
    pytest.param(dict(STW_TANGONOW, event_name="SEOUL TANGO WEEK 2025"), id="year disagrees"),
    pytest.param(dict(STW_TANGONOW, event_date=date(2025, 11, 12),
                      event_name="SEOUL TANGO WEEK"), id="different years"),
    pytest.param(dict(STW_TANGONOW, region_id=35), id="different cities"),
    pytest.param(dict(STW_TANGONOW, venue_text="부산 데땅고"), id="place names another city"),
    pytest.param(dict(STW_TANGONOW, event_type="MILONGA"), id="festival vs milonga"),
    pytest.param(dict(STW_TANGONOW, event_type="PRACTICA"), id="festival vs practica"),
    pytest.param(dict(STW_TANGONOW, event_name="SEOUL TANGO FESTIVAL 2026"),
                 id="weak title similarity"),
    pytest.param(dict(STW_TANGONOW, event_name="SEOUL TANGO WEEK 2026 (부산)"),
                 id="a programme of the series"),
    pytest.param(dict(STW_TANGONOW, source_id=5), id="same source"),
    pytest.param(dict(STW_TANGONOW, event_date=date(2026, 11, 21)), id="too far apart"),
    pytest.param(dict(STW_TANGONOW, review_state="REJECTED"), id="rejected"),
    pytest.param(dict(STW_TANGONOW, genre_id=3), id="another genre"),
    pytest.param(dict(STW_TANGONOW, source_id=None), id="no source"),
])
def test_not_a_pair(other):
    assert EC.classify(STW_MILTANG, other) is None


def test_the_korea_special_tango_week_family_is_never_a_pair():
    """Production 1615842 / 1629120 / 1629117 and the nights inside them."""
    series = _festival(1615842, event_name="KOREA SPECIAL TANGO WEEK 2026",
                       event_date=date(2026, 11, 18), end_date=None, venue_id=None,
                       venue_text="포항 posTango", region_id=None, source_id=2)
    pohang = _festival(1629120, event_name="KOREA SPECIAL TANGO WEEK 2026 (포항)",
                       event_date=date(2026, 11, 18), end_date=date(2026, 11, 21),
                       venue_id=4218, venue_text="PosTango (포스탱고)", region_id=444)
    hongdae = _festival(1629117, event_name="KOREA SPECIAL TANGO WEEK 2026 (홍대)",
                        event_date=date(2026, 11, 21), end_date=date(2026, 11, 24),
                        venue_id=186, venue_text="Ocho (오초)", region_id=2)
    welcome = dict(pohang, event_id=1629119, event_type="MILONGA",
                   event_name="KOREA SPECIAL TANGO WEEK 2026 (포항) POHANG WELCOME MILONGA",
                   event_date=date(2026, 11, 20), end_date=None)
    grand = dict(hongdae, event_id=1629116, event_type="MILONGA",
                 event_name="KOREA SPECIAL TANGO WEEK 2026 (홍대) SEOUL GRAND MILONGA",
                 end_date=None)
    rows = [series, pohang, hongdae, welcome, grand]
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            assert EC.classify(left, right) is None, (left["event_id"], right["event_id"])


# --- against the real tables ---------------------------------------------------------

def _source(pg, unique, key):
    return sources.create_source(pg, source_key=f"SRC-V44-{key}-{unique}",
                                 name=f"v0.96.44 {key} {unique}", platform="WEB",
                                 source_role="DIRECTORY", queries=[], config={},
                                 enabled=False)["source_id"]


class Corpus:
    """Festival and night rows inserted the way normalization leaves them."""

    def __init__(self, pg, unique):
        self.pg, self.unique = pg, unique
        self.sources = {k: _source(pg, unique, k) for k in ("MILTANG", "TANGONOW")}
        self.n = 0

    def add(self, source, name, first, *, last=None, kind="FESTIVAL", start=None,
            venue=None, venue_text=None, region=None, period=None, canonical=None,
            listing="LISTED"):
        self.n += 1
        url = f"https://example.test/v09644/{self.unique}/{self.n}"
        raw = {"title": name, "body": f"{first} 장소: {venue_text or '-'}"}
        if period:
            raw["event_period"] = period
            raw["festival_evidence"] = f"test record ({period})"
        with self.pg.cursor() as cur:
            cur.execute(
                "INSERT INTO source_items (source_id, external_id, url, title, content_hash, "
                "  raw) VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING source_item_id",
                (self.sources[source], url, url, name, f"h{self.n}", json.dumps(raw)))
            item_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO events (candidate_id, source_item_id, source_url, event_name, "
                "  event_type, event_date, end_date, start_time, venue_id, venue_text, "
                "  venue_status, region_id, identity_key, canonical_event_id, "
                "  listing_state, provenance, duplicate_decided_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "  'LIVE', %s) RETURNING event_id",
                (900000000 + self.n, item_id, url, name, kind, first, last, start,
                 venue["venue_id"] if venue else None, venue_text,
                 "RESOLVED" if venue else ("UNRESOLVED" if venue_text else "ABSENT"),
                 region, f"v09644|{self.unique}|{self.n}", canonical, listing,
                 "AUTO" if canonical else None))
            return cur.fetchone()[0]


def _region(pg, code):
    with pg.cursor() as cur:
        cur.execute("SELECT region_id FROM regions WHERE code = %s", (code,))
        row = cur.fetchone()
    return row[0] if row else None


@pytest.fixture
def corpus(pipe):
    """Inserted after any pipeline fixture has run its ticks (list it last)."""
    pg, unique = pipe.pg, pipe.unique
    today = events_api.today()
    c = Corpus(pg, unique)
    seoul, busan = _region(pg, "KR-SEOUL"), _region(pg, "KR-BUSAN")
    el_tango = register_venue(pg, f"El Tango {unique}")
    ocho = register_venue(pg, f"Ocho {unique}")
    first = today + timedelta(days=22)
    c.ids = {}
    c.ids["stw_miltang"] = c.add(
        "MILTANG", f"2026 Seoul Tango Week {unique}", first, last=first + timedelta(days=5),
        venue=el_tango, venue_text=el_tango["name"], region=seoul,
        period={"start": str(first), "end": str(first + timedelta(days=5))})
    c.ids["stw_tangonow"] = c.add(
        "TANGONOW", f"SEOUL TANGO WEEK 2026 {unique}", first + timedelta(days=1),
        venue_text="ELTANGO · Seoul Tango Academy",
        period={"start": str(first + timedelta(days=1))})
    kstw = first + timedelta(days=7)
    c.ids["kstw"] = c.add("TANGONOW", f"KOREA SPECIAL TANGO WEEK 2026 {unique}", kstw,
                          venue_text="포항 posTango")
    c.ids["kstw_pohang"] = c.add(
        "MILTANG", f"KOREA SPECIAL TANGO WEEK 2026 (포항) {unique}", kstw,
        last=kstw + timedelta(days=3), venue_text="PosTango (포스탱고)")
    c.ids["kstw_hongdae"] = c.add(
        "MILTANG", f"KOREA SPECIAL TANGO WEEK 2026 (홍대) {unique}", kstw + timedelta(days=3),
        last=kstw + timedelta(days=6), venue=ocho, venue_text=ocho["name"], region=seoul)
    c.ids["grand"] = c.add(
        "MILTANG", f"KOREA SPECIAL TANGO WEEK 2026 (홍대) SEOUL GRAND MILONGA {unique}",
        kstw + timedelta(days=3), kind="MILONGA", start=time(21), venue=ocho,
        venue_text=ocho["name"], region=seoul)
    busan_first = first + timedelta(days=30)
    c.ids["busan_miltang"] = c.add(
        "MILTANG", f"BUSAN TANGO FESTIVAL {unique}", busan_first,
        last=busan_first + timedelta(days=8), region=busan, venue_text="데땅고")
    c.ids["busan_tangonow"] = c.add(
        "TANGONOW", f"BUSAN TANGO FESTIVAL {unique}", busan_first,
        last=busan_first + timedelta(days=6), region=busan, venue_text="데땅고",
        canonical=c.ids["busan_miltang"], listing="HIDDEN")
    return c


def _ours(pairs, corpus):
    mine = set(corpus.ids.values())
    return [p for p in pairs if {p["left"]["event_id"], p["right"]["event_id"]} <= mine]


def _state(pg) -> tuple:
    """Everything a review page could conceivably change."""
    with pg.cursor() as cur:
        out = []
        for sql in (
            "SELECT event_id, event_date, end_date, start_time, venue_id, region_id, "
            "  canonical_event_id, listing_state, duplicate_decided_by, review_state "
            "FROM events ORDER BY event_id",
            "SELECT * FROM event_duplicate_decisions ORDER BY decision_id",
            "SELECT * FROM event_duplicate_pairs ORDER BY pair_id",
            "SELECT * FROM human_review_actions ORDER BY 1",
            "SELECT * FROM venues ORDER BY venue_id",
            "SELECT count(*), max(content_fetch_id) FROM content_fetch_log",
            "SELECT * FROM source_item_content ORDER BY source_item_id",
        ):
            cur.execute(sql)
            out.append(cur.fetchall())
    return tuple(out)


def test_find_reports_exactly_the_seoul_tango_week_pair_and_the_folded_range(pg, corpus):
    pairs = _ours(EC.find(pg), corpus)
    keys = {(p["left"]["event_id"], p["right"]["event_id"]): p for p in pairs}
    stw = keys[tuple(sorted((corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"])))]
    assert stw["conflicts"] == [EC.DATE_CONFLICT, EC.SOURCE_EVIDENCE_CONFLICT,
                                EC.VENUE_UNRESOLVED]
    assert stw["priority"] == EC.PRIORITY_HIGH and not stw["already_folded"]
    busan = keys[tuple(sorted((corpus.ids["busan_miltang"], corpus.ids["busan_tangonow"])))]
    assert busan["conflicts"] == [EC.DATE_RANGE_CONFLICT, EC.VENUE_UNRESOLVED]
    assert busan["already_folded"] and busan["priority"] == EC.PRIORITY_MEDIUM
    assert len(pairs) == 2, "the KOREA SPECIAL TANGO WEEK family is not a pair"


def test_compare_lays_out_both_sources_without_inventing_anything(pg, corpus):
    a, b = corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"]
    found = EC.compare(pg, b, a)
    fields = {f["label"]: f for f in found["fields"]}
    assert fields["First day"]["differs"]
    assert fields["Last day (stated)"]["right"] == EC.UNKNOWN
    assert fields["Start time"]["left"] == fields["Start time"]["right"] == EC.UNKNOWN
    assert "(unresolved)" in fields["Venue"]["right"]
    assert fields["Type"]["differs"] is False
    tangonow = found["evidence"][b]
    assert tangonow["date_evidence"]["stated_end"] == EC.UNKNOWN
    assert tangonow["venue_evidence"] == "ELTANGO · Seoul Tango Academy"
    assert found["public_now"] == {a: True, b: True}
    assert found["merge_offered"] is False and found["merge_note"] == EC.MERGE_NOT_OFFERED
    assert f"#{b} would be hidden" in found["if_merged"]
    assert "two entries" in found["if_separate"]


def test_compare_refuses_anything_that_is_not_a_conflict_pair(pg, corpus):
    ids = corpus.ids
    assert EC.compare(pg, ids["kstw"], ids["kstw_hongdae"]) is None
    assert EC.compare(pg, ids["kstw_pohang"], ids["kstw_hongdae"]) is None
    assert EC.compare(pg, ids["stw_miltang"], ids["grand"]) is None
    assert EC.compare(pg, ids["stw_miltang"], ids["stw_miltang"]) is None
    assert EC.compare(pg, ids["stw_miltang"], 0) is None


def test_finding_and_comparing_write_nothing(pg, corpus):
    before = _state(pg)
    EC.find(pg)
    EC.summary(pg)
    EC.compare(pg, corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"])
    duplicates.scan(pg, dry_run=True)
    assert _state(pg) == before


def test_the_scan_still_never_merges_the_pair_or_a_festival_into_a_night(pg, corpus):
    duplicates.scan(pg)
    with pg.cursor() as cur:
        cur.execute("SELECT event_id, canonical_event_id, listing_state FROM events "
                    "WHERE event_id = ANY(%s) ORDER BY event_id",
                    ([corpus.ids[k] for k in ("stw_miltang", "stw_tangonow", "kstw",
                                              "kstw_pohang", "kstw_hongdae", "grand")],))
        rows = cur.fetchall()
    assert all(canonical is None and listing == "LISTED" for _, canonical, listing in rows)


# --- the Admin ---------------------------------------------------------------------

def test_the_conflicts_page_lists_the_pair_and_the_protected_items(pipe, ktango, corpus,
                                                                   client):
    before = _state(pipe.pg)
    page = client.get("/admin/conflicts")
    assert page.status_code == 200
    a, b = corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"]
    assert f'/admin/conflicts/{a}/{b}"' in page.text
    assert EC.DATE_CONFLICT in page.text and EC.PRIORITY_HIGH in page.text
    assert f'/admin/conflicts/{corpus.ids["kstw"]}/' not in page.text
    for item_id in ktango.values():
        assert f'href="/admin/intake/{item_id}"' in page.text
        event = pipe.event(item_id)
        assert f'href="/admin/review/{event["candidate_id"]}"' in page.text
    assert not POST_FORM.search(page.text), "the page offers no action"
    assert 'href="/admin/conflicts"' in page.text, "reachable from the nav"
    assert _state(pipe.pg) == before


def test_the_comparison_page_shows_differences_and_offers_no_merge(pipe, corpus, client):
    before = _state(pipe.pg)
    a, b = corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"]
    page = client.get(f"/admin/conflicts/{b}/{a}")
    assert page.status_code == 200
    text = page.text
    assert "differs" in text and EC.HUMAN_REVIEW_REQUIRED in text
    assert "ELTANGO · Seoul Tango Academy" in text and EC.UNKNOWN in text
    assert "It is not offered for this pair" in text
    assert "If they were merged" in text and "nothing is applied" in text
    assert not POST_FORM.search(text)
    assert _state(pipe.pg) == before


def test_a_pair_that_is_not_a_conflict_is_not_found(pipe, corpus, client):
    ids = corpus.ids
    assert client.get(f'/admin/conflicts/{ids["kstw_pohang"]}/{ids["kstw_hongdae"]}'
                      ).status_code == 404
    assert client.get(f'/api/admin/conflicts/{ids["kstw"]}/{ids["kstw_hongdae"]}'
                      ).status_code == 404


def test_the_api_matches_the_page(pipe, ktango, corpus, client):
    body = client.get("/api/admin/conflicts").json()
    mine = {(p["left_event_id"], p["right_event_id"]) for p in body["pairs"]}
    assert tuple(sorted((corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"]))) in mine
    protected = {p["source_item_id"]: p for p in body["protected_review_items"]}
    for item_id in ktango.values():
        assert protected[item_id]["state"] == content_store.ENGINE_UPDATE_NOT_APPLIED
        assert protected[item_id]["required_action"] == content_store.ACTION_REVIEW
    detail = client.get(f'/api/admin/conflicts/{corpus.ids["stw_miltang"]}/'
                        f'{corpus.ids["stw_tangonow"]}').json()
    assert detail["merge_offered"] is False and detail["review"] == EC.HUMAN_REVIEW_REQUIRED


def test_the_pages_need_an_admin_and_accept_no_write(pipe, corpus, client):
    a, b = corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"]
    for path in ("/admin/conflicts", f"/admin/conflicts/{a}/{b}", "/api/admin/conflicts",
                 f"/api/admin/conflicts/{a}/{b}"):
        assert client.get(path, auth=("dancemate", "wrong")).status_code == 401
    before = _state(pipe.pg)
    assert client.post(f"/admin/conflicts/{a}/{b}").status_code in (403, 405)
    client.console_tokens = False
    assert client.post(f"/admin/conflicts/{a}/{b}").status_code in (403, 405)
    assert _state(pipe.pg) == before


def test_the_duplicates_page_points_at_the_conflicts(pipe, corpus, client):
    page = client.get("/admin/duplicates")
    assert page.status_code == 200
    assert "Cross-source conflicts" in page.text and 'href="/admin/conflicts"' in page.text


# --- the protected items ------------------------------------------------------------

def test_a_protected_review_says_what_a_person_needs_and_changes_nothing(pipe, ktango,
                                                                         client):
    from runtime import engine_ingest

    before = _state(pipe.pg)
    for number, item_id in ktango.items():
        fresh = engine_ingest.freshness(pipe.settings, pipe.pg, item_id)
        review = content_store.protected_review(pipe.pg, item_id, fresh)
        event = pipe.event(item_id)
        assert [e["event_id"] for e in review["events"]] == [event["event_id"]], number
        assert review["events_public_now"] == 0, "past events are not shown to readers"
        assert any("article body" in u for u in review["unverifiable"])
        assert str(event["candidate_id"]) in review["correction_supported"]
        assert "not re-fetched" in review["correction_supported"]
        assert review["evidence_needed"] != "-"
        page = client.get(f"/admin/intake/{item_id}")
        assert "Cannot be verified" in page.text and "Correction supported" in page.text
        assert "not shown" in page.text
    assert pipe.event(ktango[643])["start_time"] == time(0, 0), "00:00 is not corrected"
    assert _state(pipe.pg) == before
