"""v0.96.47: the Duplicates queue says what every pair is now.

A pair's stored state only changes by a person's answer or its revert. What
it *is* moves on without it: the scan folds one member into another group
(the question has moved to that group's pair), or both into one (the rules
settled it), or a re-extraction leaves two events no rule pairs any more.
v0.96.46 refused every answer on 37 such Production pairs and still offered
their buttons. `duplicates.queue()` assesses each pair from the rows as they
are, and its per-answer eligibility comes from the same `resolve_blockers()`
the preview and the confirm use - so the page offers exactly what the confirm
accepts, and the confirm's own checks are unchanged.

The pure tests build pairs in memory; the rest run the real route inside the
`pg` fixture's rolled-back transaction, and the parallel one on committed rows
of the disposable database, cleaned up afterwards.
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
    _fingerprint, _verdict_id, console, two_clocks)
from tests.test_v09646_decision_contract import (  # noqa: F401 - fixtures
    _confirm, _fold, _preview, _race, _signed, _state_of, _tokens, committed)

DAY = date(2026, 11, 7)


# --- assess_pair, in memory ---------------------------------------------------------

def _ev(event_id, **kw):
    # v0.96.52: one night's name from two independent sources (source_id per
    # event) - the positive evidence a merge now needs (`merge_evidence`).
    row = {"event_id": event_id, "event_date": DAY, "event_name": "Milonga Luz",
           "source_id": event_id,
           "start_time": "20:00", "venue_id": 7, "venue_text": "Hall", "region_id": 1,
           "identity_key": f"k{event_id}", "series_key": None, "event_type": "MILONGA",
           "canonical_event_id": None, "duplicate_decided_by": None, "listing_state": "LISTED",
           "review_state": "PENDING", "provenance": "LIVE", "source_item_id": event_id * 10,
           "primary_source_item_id": None, "primary_source_decided_by": None,
           "folded_count": 0}
    row.update(kw)
    return row


def _pair(pair_id=1, low=10, high=20, state="OPEN"):
    return {"pair_id": pair_id, "event_id": low, "other_event_id": high,
            "rule": duplicates.RULE_VENUE_TIME_DIFFERS, "state": state,
            "resolved_by": None if state == "OPEN" else "tester", "resolved_at": None,
            "created_at": None}


def _assess(rows, pair=None, pairs=()):
    pair = pair or _pair()
    index = {tuple(sorted((p["event_id"], p["other_event_id"]))): p for p in (pair, *pairs)}
    return duplicates.assess_pair(pair, {r["event_id"]: r for r in rows}, index)


def _two(**right):
    return [_ev(10), _ev(20, start_time="21:00", **right)]


def test_an_open_pair_of_two_standalone_events_is_actionable():
    found = _assess(_two())
    assert found["status"] == duplicates.QUEUE_ACTIONABLE
    assert found["available"] == ["MERGE:10", "MERGE:20", "KEEP_SEPARATE"]
    assert found["primary_reason"] is None and found["reasons"] == []


@pytest.mark.parametrize("state", [duplicates.MERGED, duplicates.DISTINCT])
def test_a_pair_a_person_answered_is_not_actionable(state):
    found = _assess(_two(), pair=_pair(state=state))
    assert found["status"] == duplicates.QUEUE_PERSON
    assert found["primary_reason"] == duplicates.REASON_ALREADY_RESOLVED
    assert found["available"] == []
    assert all(duplicates.REASON_ALREADY_RESOLVED in a["reasons"] for a in found["answers"])


def test_a_missing_event_is_an_invalid_target():
    found = _assess([_ev(10)])
    assert found["status"] == duplicates.QUEUE_INVALID
    assert found["primary_reason"] == duplicates.REASON_TARGET_NOT_FOUND
    assert found["available"] == []


def test_a_fold_into_a_third_event_supersedes_the_pair_and_names_its_successor():
    rows = [_ev(10), _ev(20, start_time="21:00", canonical_event_id=30,
                         duplicate_decided_by="AUTO", listing_state="HIDDEN"),
            _ev(30, start_time="21:00", folded_count=1)]
    successor = _pair(pair_id=2, low=10, high=30)
    found = _assess(rows, pairs=[successor])
    assert found["status"] == duplicates.QUEUE_SUPERSEDED
    assert found["primary_reason"] == duplicates.REASON_CANONICAL_CHANGED
    assert found["roots"] == [10, 30]
    assert (found["successor_pair_id"], found["successor_state"]) == (2, "OPEN")
    assert found["available"] == [], "no answer would leave the third event's fold alone"


def test_a_rule_fold_into_the_other_member_is_settled_but_can_still_be_split():
    rows = [_ev(10, folded_count=1),
            _ev(20, canonical_event_id=10, duplicate_decided_by="AUTO", listing_state="HIDDEN")]
    found = _assess(rows)
    assert found["status"] == duplicates.QUEUE_RULES
    assert found["primary_reason"] == duplicates.REASON_SAME_GROUP
    assert found["available"] == ["KEEP_SEPARATE"]


def test_two_members_folded_into_one_root_are_settled_with_nothing_to_answer():
    rows = [_ev(10, canonical_event_id=30, duplicate_decided_by="AUTO"),
            _ev(20, canonical_event_id=30, duplicate_decided_by="AUTO"),
            _ev(30, folded_count=2)]
    found = _assess(rows)
    assert found["status"] == duplicates.QUEUE_RULES and found["available"] == []


def test_a_human_fold_is_never_reported_as_settled_by_the_rules():
    rows = [_ev(10, folded_count=1),
            _ev(20, canonical_event_id=10, duplicate_decided_by="HUMAN", listing_state="HIDDEN")]
    found = _assess(rows)
    assert found["status"] == duplicates.QUEUE_SUPERSEDED
    assert found["available"] == []


def test_two_dates_are_stale_and_nothing_is_offered():
    found = _assess([_ev(10), _ev(20, event_date=date(2026, 11, 8))])
    assert found["status"] == duplicates.QUEUE_STALE
    assert duplicates.REASON_DATE_CONFLICT in found["reasons"]
    assert found["available"] == []


def test_two_regions_refuse_a_merge_but_not_keep_separate():
    found = _assess(_two(region_id=2))
    assert found["status"] == duplicates.QUEUE_ACTIONABLE
    assert found["available"] == ["KEEP_SEPARATE"]
    merges = [a for a in found["answers"] if a["action"] == "MERGE"]
    assert all(a["reasons"] == [duplicates.REASON_REGION_CONFLICT] for a in merges)


def test_two_posts_naming_exclusive_cities_refuse_a_merge():
    """The O Nada shape: Daejeon's room under no venue, Seoul's under 187."""
    rows = [_ev(10, venue_id=None, region_id=None,
                venue_text="대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)"),
            _ev(20, start_time="21:00", venue_id=187, region_id=2,
                venue_text="O Nada (오나다) (서울 마포구 동교동 200-29 B1)")]
    found = _assess(rows)
    assert found["status"] == duplicates.QUEUE_STALE
    assert found["available"] == ["KEEP_SEPARATE"]
    assert duplicates.REASON_REGION_CONFLICT in found["reasons"]


def test_a_festival_and_a_night_refuse_a_merge():
    found = _assess(_two(event_type=duplicates.FESTIVAL))
    assert found["status"] == duplicates.QUEUE_STALE, "no rule pairs a festival with a night"
    assert found["available"] == ["KEEP_SEPARATE"]
    assert duplicates.REASON_FESTIVAL_PROGRAMME in found["reasons"]


def test_a_member_heading_a_group_can_only_be_kept():
    found = _assess([_ev(10), _ev(20, start_time="21:00", folded_count=2)])
    assert found["status"] == duplicates.QUEUE_ACTIONABLE
    assert found["available"] == ["MERGE:20", "KEEP_SEPARATE"]
    keep_low = found["answers"][0]
    assert keep_low["reasons"] == [duplicates.REASON_GROUP_CHAIN]


def test_a_pair_is_the_same_whichever_way_round_it_is_named():
    rows = _two()
    forward = _assess(rows, pair=_pair(low=10, high=20))
    backward = _assess(rows, pair=_pair(low=20, high=10))
    for key in ("event_id", "other_event_id", "status", "available", "reasons"):
        assert forward[key] == backward[key], key


def test_every_status_has_guidance_and_every_refusal_a_reason():
    for status in duplicates.QUEUE_STATUSES:
        assert duplicates.QUEUE_GUIDANCE[status]
    cases = [_two(), _two(region_id=2), [_ev(10)], _two(event_date=date(2026, 11, 8))]
    for rows in cases:
        found = _assess(rows)
        assert found["status"] in duplicates.QUEUE_STATUSES
        if found["status"] != duplicates.QUEUE_ACTIONABLE:
            assert found["primary_reason"], rows
        for answer in found["answers"]:
            assert answer["available"] == (not answer["reasons"]), answer
            assert len(answer["reasons"]) == len(answer["messages"])


# --- the real route ----------------------------------------------------------------

def _item(pg, pair_id):
    return next(a for a in duplicates.queue(pg) if a["pair_id"] == pair_id)


def _gates(pg):
    return duplicates.queue_integrity(pg, duplicates.queue(pg))


def test_the_queue_matches_what_the_preview_and_confirm_accept(pg, two_clocks):
    pair_id = two_clocks["pair"]["pair_id"]
    item = _item(pg, pair_id)
    assert item["status"] == duplicates.QUEUE_ACTIONABLE
    for answer in item["answers"]:
        preview = duplicates.preview_resolve(pg, pair_id, decision=answer["decision"],
                                             canonical_event_id=answer["keep"],
                                             reviewer="tester")
        assert (preview["token"] is not None) == answer["available"]
        assert preview["reasons"] == answer["reasons"]
    assert set(_gates(pg).values()) == {0}


def test_reading_the_queue_writes_nothing(console, pg, two_clocks):
    before = _fingerprint(pg, two_clocks["day"])
    assert console.get("/admin/duplicates").status_code == 200
    for view in ("actionable", "stale", "superseded", "rules", "resolved", "invalid",
                 "blocked", "all", "nonsense"):
        assert console.get(f"/admin/duplicates?view={view}").status_code == 200
    assert console.get(f"/admin/duplicates/{two_clocks['pair']['pair_id']}").status_code == 200
    assert console.get("/api/admin/duplicates/queue").status_code == 200
    assert _fingerprint(pg, two_clocks["day"]) == before


@pytest.mark.parametrize("answer", ["merge", "keep_separate"])
def test_a_resolved_pair_leaves_the_default_queue_and_keeps_its_history(console, pg,
                                                                        two_clocks, answer):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    action = f"keep_{case['a']['event_id']}" if answer == "merge" else "distinct"
    preview_form = f'action="/admin/duplicates/{pair_id}/preview"'
    assert preview_form in console.get("/admin/duplicates").text
    token = _signed(_preview(console, pair_id, action))
    done = console.post(f"/admin/duplicates/{pair_id}",
                        data={"action": action, "token": token, "reason": "checked"},
                        follow_redirects=False)
    assert done.status_code == 303
    item = _item(pg, pair_id)
    assert item["status"] == duplicates.QUEUE_PERSON and item["available"] == []
    assert preview_form not in console.get("/admin/duplicates").text
    resolved = console.get("/admin/duplicates?view=resolved").text
    assert f'href="/admin/duplicates/{pair_id}"' in resolved and preview_form not in resolved
    # An old bookmark or tab: told the state, never handed an answer.
    detail = console.get(f"/admin/duplicates/{pair_id}")
    assert detail.status_code == 200
    assert duplicates.QUEUE_PERSON in detail.text and duplicates.REASON_ALREADY_RESOLVED in \
        detail.text
    assert preview_form not in detail.text and 'name="token"' not in detail.text
    assert "HUMAN_REVIEW" in detail.text, "the decision history is shown"
    replay = console.post(f"/admin/duplicates/{pair_id}", data={"action": action,
                                                                "token": token},
                          follow_redirects=False)
    assert replay.status_code == 409 and DC.ALREADY_RESOLVED in replay.text
    assert set(_gates(pg).values()) == {0}


def test_a_revert_reopens_the_pair_and_a_new_preview_is_required(pg, two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    keep = case["a"]["event_id"]
    token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=keep, reviewer="tester")["token"]
    duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                               canonical_event_id=keep, token=token, reviewer="tester")
    assert _item(pg, pair_id)["status"] == duplicates.QUEUE_PERSON
    verdict = _verdict_id(pg, case["b"]["event_id"])
    revert = duplicates.preview_revert(pg, decision_id=verdict, reviewer="tester")
    duplicates.revert_decision(pg, decision_id=verdict, token=revert["token"],
                               reviewer="tester", reason="reopen")
    item = _item(pg, pair_id)
    assert item["state"] == duplicates.OPEN and item["status"] == duplicates.QUEUE_ACTIONABLE
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=token, reviewer="tester")
    assert refused.value.code == DC.STALE_PREVIEW
    assert set(_gates(pg).values()) == {0}


def test_a_revert_cannot_be_replayed(pg, two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                       reviewer="tester")["token"]
    duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DISTINCT, token=token,
                               reviewer="tester")
    verdict = _verdict_id(pg, case["a"]["event_id"])
    revert = duplicates.preview_revert(pg, decision_id=verdict, reviewer="tester")
    duplicates.revert_decision(pg, decision_id=verdict, token=revert["token"],
                               reviewer="tester")
    with pytest.raises(duplicates.RevertRefused) as refused:
        duplicates.revert_decision(pg, decision_id=verdict, token=revert["token"],
                                   reviewer="tester")
    assert refused.value.code == "REVERT_ALREADY_APPLIED"


def test_a_fold_into_a_third_event_is_shown_as_superseded(console, pg, two_clocks, store,
                                                          run_normalization, unique):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    other = store.add(_id(unique, 17), name=f"Elsewhere {unique}", day=case["day"],
                      start="18:00", venue=f"Other hall {unique}")
    run_normalization()
    third = _event(pg, other)["event_id"]
    _fold(pg, case["b"]["event_id"], third)
    item = _item(pg, pair_id)
    assert item["status"] == duplicates.QUEUE_SUPERSEDED and item["available"] == []
    assert set(item["roots"]) == {case["a"]["event_id"], third}
    page = console.get("/admin/duplicates?view=superseded").text
    assert f'href="/admin/duplicates/{pair_id}"' in page
    assert f'action="/admin/duplicates/{pair_id}/preview"' not in page
    assert f'action="/admin/duplicates/{pair_id}/preview"' not in \
        console.get("/admin/duplicates").text
    preview = _preview(console, pair_id, "distinct")
    assert preview.status_code == 409
    assert duplicates.REASON_CANONICAL_CHANGED in preview.text
    assert f'href="/admin/duplicates/{pair_id}"' in preview.text


def test_a_changed_source_makes_the_pair_stale_and_the_old_preview_dead(pg, two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    keep = case["a"]["event_id"]
    token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=keep, reviewer="tester")["token"]
    with pg.cursor() as cur:      # re-extracted: the other post now names another place
        cur.execute("UPDATE events SET venue_id = NULL, venue_text = 'Somewhere else', "
                    "  venue_status = 'UNRESOLVED' "
                    "WHERE event_id = %s", (case["b"]["event_id"],))
    item = _item(pg, pair_id)
    assert item["status"] == duplicates.QUEUE_STALE
    assert item["primary_reason"] == duplicates.REASON_NO_CURRENT_MATCH
    # v0.96.48: two posts naming two places that no rule pairs any more is not a
    # merge anybody may make, so the confirm refuses it on the evidence before
    # it reaches the token (the stale-token refusal itself: test_v09648).
    preview = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                         canonical_event_id=keep, reviewer="tester")
    assert preview["reasons"] == [duplicates.REASON_PLACE_CONFLICT]
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=token, reviewer="tester")
    assert refused.value.code == DC.DECISION_REFUSED
    assert _verdict_id(pg, case["b"]["event_id"]) is None


def test_a_region_conflict_refuses_the_merge_at_preview_and_confirm(pg, two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    keep = case["a"]["event_id"]
    token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=keep, reviewer="tester")["token"]
    with pg.cursor() as cur:
        cur.execute("SELECT region_id FROM regions WHERE region_id <> %s ORDER BY region_id "
                    "LIMIT 1", (case["b"]["region_id"],))
        other_region = cur.fetchone()[0]
        cur.execute("UPDATE events SET region_id = %s WHERE event_id = %s",
                    (other_region, case["b"]["event_id"]))
    preview = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                         canonical_event_id=keep, reviewer="tester")
    assert preview["token"] is None
    assert preview["reasons"] == [duplicates.REASON_REGION_CONFLICT]
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=token, reviewer="tester")
    assert refused.value.code == DC.DECISION_REFUSED
    separate = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                          reviewer="tester")
    assert separate["token"] is not None
    assert _verdict_id(pg, case["b"]["event_id"]) is None


def test_a_festival_never_merges_with_a_night(pg, two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET event_type = 'FESTIVAL' WHERE event_id = %s",
                    (case["a"]["event_id"],))
    for keep in (case["a"]["event_id"], case["b"]["event_id"]):
        preview = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                             canonical_event_id=keep, reviewer="tester")
        assert preview["token"] is None
        assert duplicates.REASON_FESTIVAL_PROGRAMME in preview["reasons"]


def test_the_queue_api_reports_counts_and_gates_and_no_token(console, pg, two_clocks):
    response = console.get("/api/admin/duplicates/queue")
    assert response.status_code == 200
    body = response.json()
    assert set(body["integrity"].values()) == {0}
    assert body["counts"]["TOTAL"] == len(body["pairs"])
    assert body["counts"][duplicates.QUEUE_ACTIONABLE] >= 1
    assert "token" not in response.text
    mine = [p for p in body["pairs"] if p["pair_id"] == two_clocks["pair"]["pair_id"]]
    assert mine and mine[0]["status"] == duplicates.QUEUE_ACTIONABLE
    only = console.get(f"/api/admin/duplicates/queue?status={duplicates.QUEUE_PERSON}").json()
    assert all(p["status"] == duplicates.QUEUE_PERSON for p in only["pairs"])
    assert console.get("/api/admin/duplicates/queue", auth=None).status_code == 401


def test_the_integrity_gate_catches_a_pair_reopened_under_a_standing_verdict(pg, two_clocks):
    """A pair put back to OPEN by hand while its verdict stands is exactly what
    the gate exists to name - the queue would otherwise offer a second answer."""
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                       reviewer="tester")["token"]
    duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DISTINCT, token=token,
                               reviewer="tester")
    assert _gates(pg)["INCORRECT_HUMAN_DECISION_STATE"] == 0
    with pg.cursor() as cur:
        cur.execute("UPDATE event_duplicate_pairs SET state = 'OPEN' WHERE pair_id = %s",
                    (pair_id,))
    assert _gates(pg)["INCORRECT_HUMAN_DECISION_STATE"] == 1


def test_a_pair_cannot_be_stored_twice_or_reversed(pg, two_clocks):
    import psycopg

    low, high = two_clocks["a"]["event_id"], two_clocks["b"]["event_id"]
    low, high = sorted((low, high))
    for args in ((low, high), (high, low)):
        with pg.transaction():
            with pytest.raises(psycopg.errors.IntegrityError):
                with pg.transaction():
                    with pg.cursor() as cur:
                        cur.execute("INSERT INTO event_duplicate_pairs (event_id, "
                                    "other_event_id, rule) VALUES (%s, %s, 'TEST')", args)
    assert _gates(pg)["DUPLICATE_QUEUE_ENTRY"] == 0


# --- truly parallel: a confirm and a queue refresh ------------------------------------

def test_a_queue_refresh_during_a_confirm_sees_one_state_or_the_other(committed):
    made = committed
    settings, pair_id = made["settings"], made["pairs"][0]
    tokens = _tokens(settings, made)
    low = sorted(made["events"])[0]

    def refresh(con):
        return next(a for a in duplicates.queue(con) if a["pair_id"] == pair_id)

    results = _race(settings, [
        _confirm(made, duplicates.DUPLICATE, tokens["merge_low"], "admin-a", keep=low),
        refresh, refresh,
    ])
    assert results[0][0] == "ok", results[0]
    for outcome, seen in results[1:]:
        assert outcome == "ok", seen
        assert seen["state"] in (duplicates.OPEN, duplicates.MERGED)
        if seen["state"] == duplicates.MERGED:
            assert seen["status"] == duplicates.QUEUE_PERSON and seen["available"] == []
        else:
            assert seen["available"], "an open pair seen before the commit is still answerable"
    events, pair, decisions = _state_of(settings, made)
    assert pair == duplicates.MERGED and decisions == {duplicates.DUPLICATE: 1}
    from runtime import db

    with db.connect(settings, autocommit=True) as con:
        after = refresh(con)
    assert after["status"] == duplicates.QUEUE_PERSON
