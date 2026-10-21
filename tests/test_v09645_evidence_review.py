"""v0.96.45 - evidence review cases: what is known, and what it supports.

v0.96.44 listed the two kinds of question a person must settle - a festival
two sources date differently, and a protected source item the running engine
never re-read - without saying how far the stored evidence goes. An evidence
review case keeps two things apart: the *evidence* (each field confirmed,
conflicting, missing or unavailable, never filled in) and the *decision
readiness* of each existing action (Review EDIT/CONFIRM, the Duplicates
MERGE, a venue link).

The posters are Production's own OCR (``fixture_v09645_ktango_posters``):

* 643 stores 00:00 for 2025-05-08; the poster prints 24:00 only as the end of
  a night, and 20:00 is the first clock after 05.08 - a potential conflict
  whose ownership a person must confirm (the poster is a DAY-numbered
  schedule with five clocks).
* 646 stores 14:00~18:00 for 2024-09-27; 14:00~18:00 is on the poster, but
  the poster is a two-day list (9/27 and 9/28) and nothing shows which day's
  programme it is - insufficient, not wrong.
* 647 stores 16:00 for 2024-09-29; the poster states that one date and 16:00
  is its earliest clock - no correction recommended.

Every page is GET-only and is checked to write nothing. Two existing write
paths gain a guard: a Review form posted after its candidate changed is
refused (``review_basis``), and a duplicate pair is answered only once.
"""

from __future__ import annotations

import re
from datetime import date, time
from urllib.parse import parse_qs, urlparse

import pytest

from runtime import content_store, duplicates, evidence_review, review
from tests.fixture_v09645_ktango_posters import POSTER_OCR
from tests.test_v09642_source_revision import client, pipe  # noqa: F401 - fixtures
from tests.test_v09643_article_refresh import ktango  # noqa: F401 - fixture
from tests.test_v09644_event_conflicts import _state, corpus  # noqa: F401 - fixture

ER = evidence_review
POST_FORM = re.compile(r"<form[^>]*method=[\"']?post", re.IGNORECASE)

K643 = {"event_date": date(2025, 5, 8), "start_time": time(0, 0), "time_evidence": "EXPLICIT"}
K646 = {"event_date": date(2024, 9, 27), "start_time": time(14, 0), "end_time": time(18, 0)}
K647 = {"event_date": date(2024, 9, 29), "start_time": time(16, 0)}


# --- reading a poster -------------------------------------------------------------

def test_643_is_a_potential_conflict_whose_ownership_is_not_verified():
    found = ER.time_evidence(K643, [POSTER_OCR[643]])
    assert found["verdict"] == ER.TIME_POTENTIAL_CONFLICT
    assert found["state"] == ER.EVIDENCE_CONFLICTING
    assert found["stored_start"] == "00:00"
    assert found["potential"] == "20:00"
    assert found["ownership"] == ER.OWNERSHIP_NOT_VERIFIED
    assert found["multi_day_schedule_marker"] and found["event_date_on_poster"]
    assert "only as 24:00" in found["explanation"]
    readiness = ER._event_readiness(found["verdict"], found["ownership"])
    assert readiness["EDIT_TIME"]["readiness"] == ER.NOT_READY
    assert readiness["CONFIRM"]["readiness"] == ER.NOT_RECOMMENDED


def test_646_has_the_clock_on_a_two_day_poster_so_it_is_insufficient_not_wrong():
    found = ER.time_evidence(K646, [POSTER_OCR[646]])
    assert found["verdict"] == ER.TIME_EVIDENCE_INSUFFICIENT
    assert found["state"] == ER.EVIDENCE_MISSING
    assert found["poster_dates"] == ["09-27", "09-28"]
    assert found["potential"] is None, "no other value is proposed"
    assert "14:00 appears on the poster" in found["explanation"]
    readiness = ER._event_readiness(found["verdict"], found["ownership"])
    assert readiness["EDIT_TIME"]["readiness"] == ER.NOT_READY
    assert "do not clear" in readiness["EDIT_TIME"]["why"]
    assert readiness["CONFIRM"]["readiness"] == ER.NOT_RECOMMENDED


def test_647_matches_its_one_date_poster_and_needs_no_correction():
    found = ER.time_evidence(K647, [POSTER_OCR[647]])
    assert found["verdict"] == ER.TIME_MATCHES_EVIDENCE
    assert found["state"] == ER.EXISTING_VALUE_SUPPORTED
    assert found["poster_dates"] == ["09-29"] and found["poster_clocks"][0] == "16:00"
    readiness = ER._event_readiness(found["verdict"], found["ownership"])
    assert readiness["EDIT_TIME"]["readiness"] == ER.NOT_RECOMMENDED
    assert readiness["CONFIRM"]["readiness"] == ER.AVAILABLE
    assert "needs no action" in readiness["CONFIRM"]["why"]


def test_a_one_programme_poster_makes_a_correction_reviewable_not_applied():
    poster = "2026.11.20 (금) 밀롱가 PM 8:00 장소 엘땅고"
    found = ER.time_evidence({"event_date": date(2026, 11, 20), "start_time": time(0, 0)},
                             [poster])
    assert found["verdict"] == ER.TIME_POTENTIAL_CONFLICT
    assert (found["potential"], found["ownership"]) == ("20:00", ER.OWNERSHIP_SINGLE_PROGRAMME)
    assert ER._event_readiness(found["verdict"], found["ownership"])["EDIT_TIME"][
        "readiness"] == ER.AVAILABLE


@pytest.mark.parametrize("texts, verdict, state", [
    ([], ER.TIME_EVIDENCE_NOT_READ, ER.SOURCE_UNAVAILABLE),
    (["   "], ER.TIME_EVIDENCE_NOT_READ, ER.SOURCE_UNAVAILABLE),
    (["2024.09.29 한강탱고축제 장소: 반포"], ER.TIME_EVIDENCE_INSUFFICIENT, ER.EVIDENCE_MISSING),
])
def test_a_poster_that_says_nothing_never_decides(texts, verdict, state):
    found = ER.time_evidence(K647, texts)
    assert (found["verdict"], found["state"]) == (verdict, state)
    assert found["potential"] is None


def test_no_stored_time_is_not_a_question():
    found = ER.time_evidence({"event_date": date(2024, 9, 29), "start_time": None},
                             [POSTER_OCR[647]])
    assert found["verdict"] == ER.TIME_NOT_STORED and found["state"] == ER.NOT_APPLICABLE


def test_a_misread_date_only_weakens_a_match():
    """`1.5만원` reads as a date (memory: Jan 5); it may never create a match."""
    poster = POSTER_OCR[647] + "\n회비 1.5만원"
    found = ER.time_evidence(K647, [poster])
    assert found["verdict"] == ER.TIME_EVIDENCE_INSUFFICIENT
    assert found["state"] != ER.EXISTING_VALUE_SUPPORTED


def test_a_garbled_date_heading_is_not_read_as_another_date():
    """646's OCR prints "9월 28일" as "9월 282"; it is not read as Sept 2 or 28."""
    assert {(d["month"], d["day"]) for d in ER.poster_dates("9월 282 토요일")} == set()


def test_clock_reading():
    clocks = ER.poster_clocks("PM 20:00 - PM 24:00 | AM 03:00 오후 7:30 12:00 오전 12:00")
    assert [c["clock"] for c in clocks] == ["20:00", "24:00", "03:00", "19:30", "12:00",
                                            "00:00"]
    assert [c["end_of_night"] for c in clocks] == [False, True, False, False, False, False]
    assert ER.poster_clocks("24:30 99:00") == []


# --- identity ---------------------------------------------------------------------

@pytest.mark.parametrize("case_id, parsed", [
    ("conflict-1629292-1628795", ("conflict", (1628795, 1629292))),
    ("conflict-1628795-1629292", ("conflict", (1628795, 1629292))),
    ("source-643", ("source", (643,))),
    ("source-", None), ("conflict-1-", None), ("643", None), ("source-1;drop", None),
    ("", None), ("conflict-1-2-3", None),
])
def test_a_case_id_names_what_it_is_about(case_id, parsed):
    assert ER.parse_case_id(case_id) == parsed


def test_a_venue_resemblance_is_shown_never_linked():
    parts = ER.venue_parts("ELTANGO · Seoul Tango Academy", ["El Tango", "El Tango (엘땅고)"])
    assert [p["text"] for p in parts] == ["ELTANGO", "Seoul Tango Academy"]
    assert parts[0]["resembles"] == "El Tango" and parts[1]["resembles"] is None
    assert all(p["role"] == ER.UNKNOWN for p in parts)


# --- the cases, against the real tables --------------------------------------------

def _posters(pipe, ktango):
    """Attach Production's poster OCR to the protected items (image 3, as stored)."""
    with pipe.pg.cursor() as cur:
        for number, item_id in ktango.items():
            cur.execute(
                "INSERT INTO source_item_image (source_item_id, image_url, image_index, "
                "  fetch_status, ocr_status, ocr_text) "
                "VALUES (%s, %s, 3, 'FETCHED', 'OCR_SUCCESS', %s)",
                (item_id, f"http://www.k-tango.test/upload/editor/{number}.png",
                 POSTER_OCR[number]))


@pytest.fixture
def cases(pipe, ktango, corpus):
    _posters(pipe, ktango)
    return {"pipe": pipe, "ktango": ktango, "corpus": corpus}


def _stw(corpus) -> tuple[int, int]:
    return tuple(sorted((corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"])))


def test_every_case_is_found_once_with_its_own_status(cases):
    pipe, ktango, corpus = cases["pipe"], cases["ktango"], cases["corpus"]
    found = {c["case_id"]: c for c in ER.cases(pipe.pg, pipe.settings)}
    low, high = _stw(corpus)
    stw = found[f"conflict-{low}-{high}"]
    assert stw["status"] == ER.CONFLICT_UNRESOLVED and stw["priority"] == ER.PRIORITY_HIGH
    assert stw["types"] == [ER.CROSS_SOURCE_CONFLICT, ER.DATE_EVIDENCE_CONFLICT,
                            ER.VENUE_EVIDENCE_CONFLICT]
    expected = {643: ER.REVIEW_REQUIRED, 646: ER.NEEDS_MORE_EVIDENCE,
                647: ER.NO_CORRECTION_RECOMMENDED}
    for number, item_id in ktango.items():
        case = found[f"source-{item_id}"]
        assert case["status"] == expected[number], number
        assert ER.EXTRACTION_NOT_APPLIED in case["types"]
        event = pipe.event(item_id)
        assert case["event_ids"] == [event["event_id"]]
        assert case["candidate_ids"] == [event["candidate_id"]], "the item's own candidate"
    assert ER.TIME_EVIDENCE_CONFLICT in found[f"source-{ktango[643]}"]["types"]
    assert ER.SOURCE_EVIDENCE_INSUFFICIENT in found[f"source-{ktango[646]}"]["types"]
    assert ER.TIME_EVIDENCE_CONFLICT not in found[f"source-{ktango[647]}"]["types"]
    order = list(found)
    assert order.index(f"conflict-{low}-{high}") < order.index(f"source-{ktango[643]}"), \
        "an upcoming public conflict comes before past protected items"


def test_the_festival_programmes_are_never_cases(cases):
    corpus = cases["corpus"]
    protected = {corpus.ids[k] for k in ("kstw", "kstw_pohang", "kstw_hongdae", "grand")}
    for case in ER.cases(cases["pipe"].pg, cases["pipe"].settings):
        assert not protected & set(case["event_ids"]), case["case_id"]


def test_the_stw_case_keeps_the_merge_unready_and_the_dates_unchosen(cases):
    pipe, corpus = cases["pipe"], cases["corpus"]
    low, high = _stw(corpus)
    case = ER.case(pipe.pg, pipe.settings, f"conflict-{high}-{low}")
    assert case["case_id"] == f"conflict-{low}-{high}", "either order, one case"
    assert case["readiness"]["MERGE"]["merge_ready"] is False
    assert case["readiness"]["MERGE"]["readiness"] == ER.NOT_READY
    assert "DATE_CONFLICT" in case["readiness"]["MERGE"]["why"]
    assert case["readiness"]["DATE_CORRECTION"]["readiness"] == ER.NOT_READY
    assert case["readiness"]["VENUE_LINK"]["readiness"] == ER.NOT_READY
    assert case["evidence_confidence"] == [ER.event_conflicts.POSSIBLE_SAME_EVENT,
                                           ER.NEEDS_MORE_EVIDENCE]
    answers = {q["question"]: q["answer"] for q in case["questions"]}
    assert answers["Is there independent evidence that both are one event?"] == "NONE_STORED"
    assert all(a in (ER.UNKNOWN, "NONE_STORED") for a in answers.values()), \
        "nothing stored answers a date question"
    tangonow = case["venues"][corpus.ids["stw_tangonow"]]
    assert tangonow["resolved_venue"] == "UNRESOLVED"
    assert tangonow["raw_venue_text"] == "ELTANGO · Seoul Tango Academy"
    assert [p["text"] for p in tangonow["other_mentioned"]] == ["ELTANGO",
                                                                "Seoul Tango Academy"]
    miltang = case["venues"][corpus.ids["stw_miltang"]]
    assert "(venue " in miltang["resolved_venue"] and miltang["other_mentioned"] == []
    hrefs = {a["href"] for a in case["available_actions"]}
    assert f"/admin/conflicts/{low}/{high}" in hrefs and "/admin/venues/unresolved" in hrefs
    assert not any("/admin/duplicates/" in h for h in hrefs), "no merge route is linked"


def _item_of(pg, event_id: int) -> int:
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id FROM events WHERE event_id = %s", (event_id,))
        return cur.fetchone()[0]


def test_unrelated_or_unknown_case_ids_are_not_cases(cases):
    """An ordinary item is not presented as a question just because its id is typed."""
    pipe, corpus = cases["pipe"], cases["corpus"]
    ids = corpus.ids
    for case_id in (f'conflict-{ids["kstw_pohang"]}-{ids["kstw_hongdae"]}',
                    f'conflict-{ids["stw_miltang"]}-{ids["grand"]}',
                    f'conflict-{ids["stw_miltang"]}-{ids["stw_miltang"]}',
                    "conflict-0-1", "source-0", "nonsense",
                    f'source-{_item_of(pipe.pg, ids["stw_miltang"])}'):
        assert ER.case(pipe.pg, pipe.settings, case_id) is None, case_id


def test_a_persons_review_closes_a_protected_case(cases):
    pipe, ktango = cases["pipe"], cases["ktango"]
    item_id = ktango[647]
    event = pipe.event(item_id)
    review.record(pipe.pg, candidate_id=event["candidate_id"], action=review.CONFIRM,
                  reviewer="operator", reason="matches the poster")
    case = ER.case(pipe.pg, pipe.settings, f"source-{item_id}")
    assert case["status"] == ER.HUMAN_DECISION_RECORDED
    assert [h["action"] for h in case["human_history"]] == [review.CONFIRM]
    assert ER.metrics([case])["open"] == 0


def test_a_persons_merge_closes_a_conflict_case(cases):
    pipe, corpus = cases["pipe"], cases["corpus"]
    low, high = _stw(corpus)
    duplicates.record_decision(pipe.pg, event_id=high, canonical_event_id=low,
                               decision=duplicates.DUPLICATE, decided_by=duplicates.HUMAN,
                               rule=duplicates.RULE_HUMAN_REVIEW, reviewer="operator")
    case = ER.case(pipe.pg, pipe.settings, f"conflict-{low}-{high}")
    assert case["status"] == ER.HUMAN_DECISION_RECORDED
    assert case["readiness"]["MERGE"]["readiness"] == ER.NOT_OFFERED
    assert [d["event_id"] for d in case["human_decisions"]] == [high]


def test_the_protected_cases_say_what_is_blocked(cases):
    pipe, ktango = cases["pipe"], cases["ktango"]
    case = ER.case(pipe.pg, pipe.settings, f"source-{ktango[643]}")
    blocked = {b["action"]: b["readiness"] for b in case["blocked_actions"]}
    assert blocked == {"Re-fetch the source": ER.BLOCKED,
                       "Re-extract with the running engine": ER.BLOCKED}
    event = case["events"][0]
    assert event["time"]["potential"] == "20:00"
    assert event["time"]["ownership"] == ER.OWNERSHIP_NOT_VERIFIED
    assert event["start_time"] == "00:00", "the stored value is shown, not replaced"
    assert pipe.event(ktango[643])["start_time"] == time(0, 0)


def test_working_out_every_case_writes_nothing(cases):
    pipe, corpus = cases["pipe"], cases["corpus"]
    before = _state(pipe.pg)
    found = ER.all_cases(pipe.pg, pipe.settings)
    for case in found:
        ER.case(pipe.pg, pipe.settings, case["case_id"])
    ER.metrics(found)
    assert _state(pipe.pg) == before


# --- the pages -----------------------------------------------------------------------

def test_the_queue_and_every_case_page_read_only(cases, client):
    pipe, ktango, corpus = cases["pipe"], cases["ktango"], cases["corpus"]
    before = _state(pipe.pg)
    page = client.get("/admin/evidence-review")
    assert page.status_code == 200
    low, high = _stw(corpus)
    assert f'href="/admin/evidence-review/conflict-{low}-{high}"' in page.text
    assert 'href="/admin/evidence-review"' in page.text, "reachable from the nav"
    assert not POST_FORM.search(page.text)
    for case_id in [f"conflict-{low}-{high}"] + [f"source-{i}" for i in ktango.values()]:
        detail = client.get(f"/admin/evidence-review/{case_id}")
        assert detail.status_code == 200, case_id
        assert not POST_FORM.search(detail.text), case_id
        assert "records nothing" in detail.text
        api = client.get(f"/api/admin/evidence-review/{case_id}")
        assert api.status_code == 200 and api.json()["case_id"] == case_id
    stw = client.get(f"/admin/evidence-review/conflict-{high}-{low}").text
    assert ER.CONFLICT_UNRESOLVED in stw and ER.NOT_READY in stw
    assert "ELTANGO · Seoul Tango Academy" in stw and "not a link" in stw
    k643 = client.get(f"/admin/evidence-review/source-{ktango[643]}").text
    assert ER.OWNERSHIP_NOT_VERIFIED in k643 and "20:00" in k643
    assert f'href="/admin/review/{pipe.event(ktango[643])["candidate_id"]}"' in k643
    k647 = client.get(f"/admin/evidence-review/source-{ktango[647]}").text
    assert ER.NO_CORRECTION_RECOMMENDED in k647 and ER.EXISTING_VALUE_SUPPORTED in k647
    body = client.get("/api/admin/evidence-review").json()
    assert body["metrics"]["protected_source"] >= 3
    assert _state(pipe.pg) == before


def test_the_conflicts_page_links_its_cases(cases, client):
    low, high = _stw(cases["corpus"])
    page = client.get("/admin/conflicts").text
    assert f'/admin/evidence-review/conflict-{low}-{high}"' in page
    for item_id in cases["ktango"].values():
        assert f'/admin/evidence-review/source-{item_id}"' in page


def test_the_pages_need_an_admin_accept_no_write_and_404_unknown_cases(cases, client):
    pipe = cases["pipe"]
    low, high = _stw(cases["corpus"])
    paths = ("/admin/evidence-review", f"/admin/evidence-review/conflict-{low}-{high}",
             "/api/admin/evidence-review", f"/api/admin/evidence-review/conflict-{low}-{high}")
    for path in paths:
        assert client.get(path, auth=("dancemate", "wrong")).status_code == 401
    before = _state(pipe.pg)
    for path in paths:
        assert client.post(path).status_code in (403, 405)
    client.console_tokens = False
    for path in paths:
        assert client.post(path).status_code in (403, 405)
    for bad in ("conflict-1-2", "source-0", "x", "conflict-1-1"):
        assert client.get(f"/admin/evidence-review/{bad}").status_code == 404
        assert client.get(f"/api/admin/evidence-review/{bad}").status_code == 404
    assert _state(pipe.pg) == before


# --- a Review form opened before its candidate changed ------------------------------

def _basis(text: str) -> str:
    values = set(re.findall(r'name="basis" value="([0-9a-f]{32})"', text))
    assert len(values) == 1, "every form on the page carries the same basis"
    return values.pop()


def _actions(pg, candidate_id) -> int:
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM human_review_actions WHERE candidate_id = %s",
                    (candidate_id,))
        return cur.fetchone()[0]


def test_a_stale_review_form_is_refused_and_a_fresh_one_recorded(pipe, ktango, client):
    item_id = ktango[646]
    event = pipe.event(item_id)
    cid = event["candidate_id"]
    stale = _basis(client.get(f"/admin/review/{cid}").text)
    # A source revision re-reads the item after the page was opened.
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE events SET start_time = '19:00' WHERE event_id = %s",
                    (event["event_id"],))
    refused = client.post(f"/admin/review/{cid}/confirm", data={"basis": stale},
                          follow_redirects=False)
    assert refused.status_code == 303
    query = parse_qs(urlparse(refused.headers["location"]).query)
    assert query["tone"] == ["bad"] and "nothing was recorded" in query["msg"][0]
    assert _actions(pipe.pg, cid) == 0
    fresh = _basis(client.get(f"/admin/review/{cid}").text)
    assert fresh != stale
    done = client.post(f"/admin/review/{cid}/confirm", data={"basis": fresh},
                       follow_redirects=False)
    assert parse_qs(urlparse(done.headers["location"]).query)["tone"] == ["ok"]
    assert _actions(pipe.pg, cid) == 1
    again = client.post(f"/admin/review/{cid}/confirm", data={"basis": fresh},
                        follow_redirects=False)
    assert parse_qs(urlparse(again.headers["location"]).query)["tone"] == ["bad"], \
        "the same form cannot be submitted twice"
    assert _actions(pipe.pg, cid) == 1


def test_an_edit_from_a_stale_form_changes_nothing(pipe, ktango, client):
    event = pipe.event(ktango[643])
    cid = event["candidate_id"]
    stale = _basis(client.get(f"/admin/review/{cid}").text)
    review.record(pipe.pg, candidate_id=cid, action=review.CONFIRM, reviewer="other")
    client.post(f"/admin/review/{cid}/edit",
                data={"basis": stale, "start_time": "20:00", "reason": "poster"},
                follow_redirects=False)
    assert _actions(pipe.pg, cid) == 1, "only the other reviewer's action"
    assert review.state(pipe.pg, cid)["corrected_json"] in ({}, None)
    assert pipe.event(ktango[643])["start_time"] == time(0, 0)


def test_a_review_post_without_the_request_token_is_still_refused(pipe, ktango, client):
    cid = pipe.event(ktango[647])["candidate_id"]
    basis = _basis(client.get(f"/admin/review/{cid}").text)
    client.console_tokens = False
    assert client.post(f"/admin/review/{cid}/confirm", data={"basis": basis},
                       follow_redirects=False).status_code == 403
    assert _actions(pipe.pg, cid) == 0


def test_the_protected_review_still_lists_the_same_items(cases):
    pipe, ktango = cases["pipe"], cases["ktango"]
    listed = {r["source_item_id"] for r in content_store.listing(
        pipe.pg, extraction="REVIEW", source_id=pipe.source_id,
        engine_version=pipe.settings.engine_version)}
    assert listed == set(ktango.values()), "attaching the posters changes no freshness"


# --- a duplicate pair is answered once ------------------------------------------------

from tests.test_v09639_evidence_and_listing import (  # noqa: E402,F401 - fixtures
    run_normalization, settings, store, venue)
from tests.test_v09640_duplicate_revert import _verdict_id, two_clocks  # noqa: E402,F401


def test_a_decided_pair_cannot_be_decided_again_until_reverted(pg, two_clocks):
    case = two_clocks
    duplicates.resolve_pair(pg, case["pair"]["pair_id"], decision=duplicates.DISTINCT,
                            reviewer="operator", reason="two nights")
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_duplicate_decisions")
        before = cur.fetchone()[0]
    with pytest.raises(ValueError, match="already DISTINCT"):
        duplicates.resolve_pair(pg, case["pair"]["pair_id"], decision=duplicates.DUPLICATE,
                                canonical_event_id=case["a"]["event_id"], reviewer="stale tab")
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_duplicate_decisions")
        assert cur.fetchone()[0] == before
        cur.execute("SELECT canonical_event_id FROM events WHERE event_id = %s",
                    (case["b"]["event_id"],))
        assert cur.fetchone()[0] is None, "nothing was folded"
    verdict = _verdict_id(pg, case["a"]["event_id"])
    preview = duplicates.preview_revert(pg, decision_id=verdict, reviewer="operator")
    duplicates.revert_decision(pg, decision_id=verdict, token=preview["token"],
                               reviewer="operator", reason="reopen")
    duplicates.resolve_pair(pg, case["pair"]["pair_id"], decision=duplicates.DUPLICATE,
                            canonical_event_id=case["a"]["event_id"], reviewer="operator")
