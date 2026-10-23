"""v0.96.52: a merge is offered only on positive same-event evidence.

v0.96.51 refused a merge only on evidence against it (EXPLICIT_DISTINCT_
PROGRAMMES), so a pair with nothing against it stayed mergeable: 62 of
Production's 69 pairs offering "Same event" had no positive reason - two
directories' different milongas in one room, a weekly schedule beside one of
its parties, two names sharing only 추석. Now `duplicates.merge_evidence`
says what positively makes two events one, `resolve_blockers` refuses the
merge without it (INSUFFICIENT_SAME_EVENT_EVIDENCE), and the queue, the
preview and the confirm agree because they all ask `resolve_blockers`.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from runtime import decision_contract as DC
from runtime import duplicates
from tests.test_v09639_evidence_and_listing import (  # noqa: F401 - fixtures
    _event, _id, run_normalization, settings, store, venue)
from tests.test_v09640_duplicate_revert import (  # noqa: F401 - fixtures
    _day, _pair_of, _verdict_id, console, two_clocks)
from tests.test_v09646_decision_contract import _race, committed  # noqa: F401 - fixtures

TODAY = date(2026, 10, 23)


def _ev(event_id, **kw):
    row = {"event_id": event_id, "event_date": TODAY, "end_date": None, "period_end": None,
           "event_name": f"Night {event_id}", "start_time": "20:00", "venue_id": 186,
           "venue_text": "Ocho", "region_id": 1, "identity_key": f"k{event_id}",
           "series_key": None, "event_type": "MILONGA", "canonical_event_id": None,
           "duplicate_decided_by": None, "listing_state": "LISTED", "review_state": "PENDING",
           "provenance": "LIVE", "source_item_id": event_id * 10,
           "primary_source_item_id": None, "primary_source_decided_by": None,
           "folded_count": 0, "source_id": 5, "source_platform": "WEB",
           "source_role": "DIRECTORY", "item_event_count": 1}
    row.update(kw)
    return row


def _pair(low=10, high=20, state="OPEN", rule=duplicates.RULE_VENUE_TIME_DIFFERS):
    return {"pair_id": 1, "event_id": low, "other_event_id": high, "rule": rule,
            "state": state, "matched": ["event_date", "venue"],
            "resolved_by": None if state == "OPEN" else "operator", "resolved_at": None,
            "created_at": None}


def _assess(left, right, pair=None):
    pair = pair or _pair(left["event_id"], right["event_id"])
    rows = {left["event_id"]: left, right["event_id"]: right}
    return duplicates.assess_pair(pair, rows, {(pair["event_id"], pair["other_event_id"]): pair},
                                  TODAY)


def _merge_reasons(item):
    return {r for a in item["answers"] if a["decision"] == duplicates.DUPLICATE
            for r in a["reasons"]}


# --- names that name one night ------------------------------------------------------

@pytest.mark.parametrize("left,right", [
    ("Milonga Julie", "Andante | Milonga Julie"),                 # TangoNOW prefix
    ("KOREA SPECIAL TANGO WEEK 2026", "KOREA SPECIAL TANGO WEEK 2026 (포항)"),  # #715215
    ("오초 밀롱가", "오초밀롱가"),                                   # spacing
    ("HOLA TANGO | Hola milonga", "HOLA TANGO | Hola milonga"),   # #805256
    ("평일 낮쁘락", "평일 낮쁘락"),                                   # #557905
])
def test_names_naming_one_night_match(left, right):
    assert duplicates.names_match(left, right)


@pytest.mark.parametrize("left,right", [
    ("추석 피날레 소셜파티!", "추석 연휴 워크샵 - LATIN EVERLATN"),    # #320260: one shared word
    ("K-SENSUAL Bonita 추석연휴 파티!", "보니따에서 보내는 추석연휴 09/25"),  # #710713
    ("토이프밀롱가", "고고밀롱가"),                                    # two milongas of one room
    ("SEOUL SALSA WEEK 2026", "강턴 주간일정 10/01"),
    ("밀롱가", "Milonga"),                                          # only the kind of night
    ("Salsa Party", "Salsa Night"),
    ("", "Milonga Luz"),                                             # no name is no evidence
    (None, None),
])
def test_names_sharing_a_word_or_only_the_kind_of_night_do_not_match(left, right):
    assert not duplicates.names_match(left, right)


# --- merge_evidence -----------------------------------------------------------------

def test_same_date_same_venue_without_independent_evidence_needs_evidence():
    """The DUP-03 shape: one room, one date, unrelated names, two sources."""
    left = _ev(10, event_name="Milonga Hiro", start_time="19:00", source_id=3)
    right = _ev(20, event_name="Alonga", start_time="14:00", source_id=5)
    found = duplicates.merge_evidence(left, right)
    assert found["ready"] is False and found["strength"] == duplicates.STRENGTH_WEAK
    item = _assess(left, right)
    assert item["readiness"] == duplicates.READINESS_NEEDS_EVIDENCE
    assert item["available"] == ["KEEP_SEPARATE"]
    assert _merge_reasons(item) == {duplicates.REASON_INSUFFICIENT_SAME_EVENT_EVIDENCE}
    assert item["next_action"] == duplicates.NEXT_REVIEW_SOURCE_EVIDENCE


def test_a_generic_similar_title_alone_is_never_ready():
    left = _ev(10, event_name="Salsa Party", start_time="21:00", venue_id=None,
               venue_text="Club", source_id=3)
    right = _ev(20, event_name="Salsa Night", start_time="21:00", venue_id=None,
                venue_text="Club", source_id=5)
    found = duplicates.merge_evidence(left, right)
    assert found["ready"] is False
    assert "no name that names one night" in found["missing"]


def test_one_event_across_independent_sources_with_strong_evidence_is_ready():
    left = _ev(10, event_name="Milonga ON", start_time="19:00", source_id=2,
               source_role="AGGREGATOR")
    right = _ev(20, event_name="Milonga ON", start_time=None, source_id=5)
    found = duplicates.merge_evidence(left, right)
    assert found["ready"] and found["strength"] == duplicates.STRENGTH_STRONG
    item = _assess(left, right)
    assert item["readiness"] == duplicates.READINESS_MERGE_READY
    assert item["available"] == ["MERGE:10", "MERGE:20", "KEEP_SEPARATE"]
    assert item["merge_readiness"] == duplicates.EVIDENCE_SUPPORTS


def test_cross_source_starts_an_hour_apart_are_one_start_five_hours_are_not():
    def pair(second):
        return (_ev(10, event_name="cabeceo", start_time="17:00", source_id=2),
                _ev(20, event_name="cabeceo", start_time=second, source_id=5))
    assert duplicates.merge_evidence(*pair("18:00"))["ready"]
    far = duplicates.merge_evidence(*pair("22:00"))           # Production #1730
    assert not far["ready"] and "stated starts differ (17:00 / 22:00)" in far["missing"]


def test_one_source_one_name_two_starts_is_not_ready():
    left = _ev(10, event_name="Fall In Together", start_time="19:00", venue_id=None,
               venue_text="리베로", source_id=12)
    right = _ev(20, event_name="Salsa Bachata FALL IN TOGETHER", start_time="20:00",
                venue_id=None, venue_text="리베로", source_id=12)
    assert not duplicates.merge_evidence(left, right)["ready"]       # Production #639521


def test_unknown_fields_are_never_evidence():
    """No start, no resolved venue: one name on one date is a question."""
    left = _ev(10, event_name="춤추는 J 토끼파티", start_time=None, venue_id=None,
               venue_text="천안 턴", source_id=12)
    right = _ev(20, event_name="춤추는 토끼파티", start_time=None, venue_id=None,
                venue_text="천안 턴", source_id=12)
    found = duplicates.merge_evidence(left, right)
    assert duplicates.names_match(left["event_name"], right["event_name"])
    assert not found["ready"] and "a start time is not stated" in found["missing"]


def test_twelve_hours_apart_is_neither_one_start_nor_two():
    left = _ev(10, event_name="Milonga Luz", start_time="09:00", source_id=2)
    right = _ev(20, event_name="Milonga Luz", start_time="21:00", source_id=5)
    found = duplicates.merge_evidence(left, right)
    assert not found["ready"]
    assert not any("differ" in m for m in found["missing"])


def test_two_different_resolved_venues_are_never_ready():
    left = _ev(10, event_name="Milonga Luz", series_key="s1")
    right = _ev(20, event_name="Milonga Luz", series_key="s1", venue_id=8)
    found = duplicates.merge_evidence(left, right)
    assert not found["ready"] and "two different resolved venues" in found["missing"]


def test_one_festival_from_two_sources_is_ready_and_a_last_day_conflict_is_not():
    """Production #715215: KSTW 2026 from TangoNOW and Miltang, same first day."""
    left = _ev(10, event_name="KOREA SPECIAL TANGO WEEK 2026", event_type="FESTIVAL",
               start_time=None, venue_id=None, venue_text="포항 posTango", region_id=None,
               source_id=2)
    right = _ev(20, event_name="KOREA SPECIAL TANGO WEEK 2026 (포항)", event_type="FESTIVAL",
                start_time=None, venue_id=4218, venue_text="PosTango", region_id=444,
                end_date=date(2026, 11, 21), source_id=5)
    found = duplicates.merge_evidence(left, right)
    assert found["ready"] and found["strength"] == duplicates.STRENGTH_STRONG
    clash = duplicates.merge_evidence(dict(left, end_date=date(2026, 11, 20)), right)
    assert not clash["ready"] and "stated last days differ" in clash["missing"]


def test_what_the_rules_merge_on_their_own_is_ready():
    left, right = _ev(10, event_name="Night A"), _ev(20, event_name="Night B")
    assert duplicates.classify(left, right)["auto"]
    assert duplicates.merge_evidence(left, right)["ready"]


# --- contradictions stay blocked; resolved pairs offer nothing -------------------------

def test_an_explicit_distinct_programme_is_blocked_not_merely_unready():
    left = _ev(10, event_name="로까밀롱가", start_time="20:00")
    right = _ev(20, event_name="토이프밀롱가", start_time="14:00")
    item = _assess(left, right)
    assert item["readiness"] == duplicates.READINESS_BLOCKED
    assert _merge_reasons(item) == {duplicates.REASON_EXPLICIT_DISTINCT_PROGRAMMES}
    assert item["available"] == ["KEEP_SEPARATE"]


def test_a_festival_parent_and_its_programme_are_blocked():
    left = _ev(10, event_name="Tango Week", event_type="FESTIVAL", start_time=None)
    right = _ev(20, event_name="Tango Week", source_id=6)
    item = _assess(left, right)
    assert item["readiness"] == duplicates.READINESS_BLOCKED
    assert duplicates.REASON_FESTIVAL_PROGRAMME in _merge_reasons(item)


def test_a_region_conflict_is_blocked():
    left = _ev(10, event_name="Milonga Luz", start_time="20:00", source_id=2)
    right = _ev(20, event_name="Milonga Luz", start_time=None, source_id=5, region_id=2)
    item = _assess(left, right)
    assert item["readiness"] == duplicates.READINESS_BLOCKED
    assert duplicates.REASON_REGION_CONFLICT in _merge_reasons(item)


@pytest.mark.parametrize("state", [duplicates.MERGED, duplicates.DISTINCT])
def test_a_pair_a_person_answered_offers_no_decision(state):
    left = _ev(10, event_name="Milonga ON", source_id=2, start_time=None)
    right = _ev(20, event_name="Milonga ON", source_id=5)
    item = _assess(left, right, _pair(state=state))
    assert item["readiness"] == duplicates.READINESS_RESOLVED and item["available"] == []


def test_every_readiness_is_one_of_the_five_states():
    cases = [
        _assess(_ev(10, event_name="Milonga Hiro", start_time="19:00"),
                _ev(20, event_name="Alonga", start_time="14:00", source_id=7)),
        _assess(_ev(10, event_name="Milonga ON", source_id=2, start_time=None),
                _ev(20, event_name="Milonga ON", source_id=5)),
        _assess(_ev(10), _ev(20, start_time="21:00", event_date=date(2026, 10, 24))),
    ]
    for item in cases:
        assert item["readiness"] in duplicates.READINESS_STATES


# --- the gate counts what it must never see -----------------------------------------

def test_the_gate_counts_a_merge_offered_without_evidence(pg, two_clocks):
    assessed = duplicates.queue(pg)
    gates = duplicates.queue_integrity(pg, assessed)
    for gate in ("INSUFFICIENT_EVIDENCE_MARKED_MERGE_READY", "EXPLICIT_DISTINCT_PROGRAMME_MERGE",
                 "FALSE_FESTIVAL_PROGRAMME_MERGE", "FALSE_CROSS_REGION_MERGE"):
        assert gates[gate] == 0, gate
    item = next(a for a in assessed if a["pair_id"] == two_clocks["pair"]["pair_id"])
    forged = dict(item, evidence_ready=False)        # what a regression would produce
    assert duplicates.queue_integrity(pg, [forged])[
        "INSUFFICIENT_EVIDENCE_MARKED_MERGE_READY"] == 1


# --- queue, preview and confirm agree (real route) --------------------------------------

@pytest.fixture
def unevidenced(pg, store, run_normalization, unique, venue):
    """One room, one date, two unrelated names at two clocks from two sources."""
    from runtime import sources

    day = _day(7)
    ids = [store.add(_id(unique, 80), name=f"Milonga Hiro {unique[:4]}", day=day,
                     start="19:00", venue=venue["name"]),
           store.add(_id(unique, 81), name="Alonga", day=day, start="14:00",
                     venue=venue["name"])]
    run_normalization()
    duplicates.scan(pg, on=day)
    a, b = _event(pg, ids[0]), _event(pg, ids[1])
    other = sources.create_source(pg, source_key=f"SRC-V09652U-{unique}",
                                  name=f"v0.96.52 unevidenced {unique}", platform="WEB",
                                  source_role="DIRECTORY", url="https://example.test/u",
                                  enabled=False)
    with pg.cursor() as cur:
        cur.execute("UPDATE source_items SET source_id = %s WHERE source_item_id = %s",
                    (other["source_id"], b["source_item_id"]))
    pair = _pair_of(pg, a["event_id"], b["event_id"])
    assert pair["rule"] == duplicates.RULE_VENUE_TIME_DIFFERS
    return {"a": a, "b": b, "pair": pair}


def _item(pg, pair_id):
    return next(a for a in duplicates.queue(pg) if a["pair_id"] == pair_id)


def test_queue_preview_and_confirm_refuse_an_unevidenced_merge_alike(pg, unevidenced):
    case = unevidenced
    pair_id, keep = case["pair"]["pair_id"], case["a"]["event_id"]
    item = _item(pg, pair_id)
    assert item["status"] == duplicates.QUEUE_ACTIONABLE
    assert item["readiness"] == duplicates.READINESS_NEEDS_EVIDENCE
    assert item["available"] == ["KEEP_SEPARATE"]
    preview = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                         canonical_event_id=keep, reviewer="tester")
    assert preview["token"] is None
    assert preview["reasons"] == [duplicates.REASON_INSUFFICIENT_SAME_EVENT_EVIDENCE]
    keep_token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                            reviewer="tester")["token"]
    for token in (None, "1." + "0" * 64, keep_token):
        with pytest.raises(DC.DecisionRefused):
            duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=keep, token=token, reviewer="tester")
    assert _verdict_id(pg, case["b"]["event_id"]) is None
    assert _pair_of(pg, case["a"]["event_id"], case["b"]["event_id"])["state"] == "OPEN"
    # Different events stays a person's answer, through its signed preview.
    done = duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                      token=keep_token, reviewer="tester")
    assert done["state"] == duplicates.DISTINCT


def test_the_console_shows_not_ready_and_no_same_event_button(console, pg, unevidenced):
    pair_id = unevidenced["pair"]["pair_id"]
    page = console.get(f"/admin/duplicates/{pair_id}").text
    assert "MERGE_NEEDS_EVIDENCE" in page and "REVIEW_SOURCE_EVIDENCE" in page
    assert "INSUFFICIENT_SAME_EVENT_EVIDENCE" in page
    assert not re.search(r'value="keep_\d+"', page), "no Same event button"
    assert 'value="distinct"' in page
    queue_json = console.get("/api/admin/duplicates/queue").json()
    entry = next(p for p in queue_json["pairs"] if p["pair_id"] == pair_id)
    assert entry["readiness"] == duplicates.READINESS_NEEDS_EVIDENCE
    assert entry["next_action"] == duplicates.NEXT_REVIEW_SOURCE_EVIDENCE
    assert queue_json["integrity"]["INSUFFICIENT_EVIDENCE_MARKED_MERGE_READY"] == 0


def test_an_evidenced_pair_still_merges_reverts_and_needs_a_fresh_preview(pg, two_clocks):
    """The valid path: positive evidence (one name, one venue, two sources)."""
    case = two_clocks
    pair_id, keep = case["pair"]["pair_id"], case["a"]["event_id"]
    item = _item(pg, pair_id)
    assert item["readiness"] == duplicates.READINESS_MERGE_READY
    assert item["evidence_strength"] == duplicates.STRENGTH_STRONG
    preview = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                         canonical_event_id=keep, reviewer="tester")
    assert preview["reasons"] == [] and preview["token"]
    with pytest.raises(DC.DecisionRefused):                  # bound to its reviewer
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=preview["token"],
                                   reviewer="someone else")
    done = duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                      canonical_event_id=keep, token=preview["token"],
                                      reviewer="tester")
    assert done["state"] == duplicates.MERGED
    with pytest.raises(DC.DecisionRefused):                  # replay
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=preview["token"],
                                   reviewer="tester")
    assert _item(pg, pair_id)["readiness"] == duplicates.READINESS_RESOLVED
    verdict = _verdict_id(pg, case["b"]["event_id"])
    revert = duplicates.preview_revert(pg, decision_id=verdict, reviewer="tester")
    duplicates.revert_decision(pg, decision_id=verdict, token=revert["token"],
                               reviewer="tester", reason="test")
    with pytest.raises(DC.DecisionRefused) as stale:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=preview["token"],
                                   reviewer="tester")
    assert stale.value.code == DC.STALE_PREVIEW
    assert _item(pg, pair_id)["readiness"] == duplicates.READINESS_MERGE_READY


def test_a_basis_that_moved_is_refused(pg, two_clocks):
    case = two_clocks
    pair_id, keep = case["pair"]["pair_id"], case["a"]["event_id"]
    token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=keep, reviewer="tester")["token"]
    with pg.cursor() as cur:
        cur.execute("UPDATE source_items SET content_hash = 'revised' WHERE source_item_id = %s",
                    (case["a"]["source_item_id"],))
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=token, reviewer="tester")
    assert refused.value.code == DC.STALE_PREVIEW


@pytest.mark.parametrize("first,second", [(duplicates.DUPLICATE, duplicates.DISTINCT),
                                          (duplicates.DISTINCT, duplicates.DUPLICATE)])
def test_concurrent_merge_and_keep_separate_leave_at_most_one_decision(committed, first,
                                                                        second):
    from runtime import db

    pair_id = committed["pairs"][0]
    keep = min(committed["events"])
    tokens = {}
    with db.connect(committed["settings"], autocommit=True) as con:
        for decision in (first, second):
            preview = duplicates.preview_resolve(
                con, pair_id, decision=decision,
                canonical_event_id=keep if decision == duplicates.DUPLICATE else None,
                reviewer="tester")
            assert preview["token"], preview["reasons"]
            tokens[decision] = preview["token"]

    def answer(decision):
        def job(con):
            return duplicates.confirm_resolve(
                con, pair_id, decision=decision, token=tokens[decision],
                canonical_event_id=keep if decision == duplicates.DUPLICATE else None,
                reviewer="tester")
        return job

    results = _race(committed["settings"], [answer(first), answer(second)])
    assert sorted(r[0] for r in results) == ["ok", "refused"], results
    with db.connect(committed["settings"], autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute("SELECT count(DISTINCT decision) FROM event_duplicate_decisions "
                        "WHERE pair_id = %s AND reverts_decision_id IS NULL", (pair_id,))
            assert cur.fetchone()[0] == 1
