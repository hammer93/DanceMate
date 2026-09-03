import pytest
from src.database import init_db,persist_source_reliability_observation
from src.source_reliability import (
    recompute_profile,evaluate_verification_policy,start_canary,canaries
)
from src.preventive_policy_outcome import (
    record_outcome,outcomes,evaluate_canary_safety,final_review,
    full_promotions,rollback_full
)

S="SRC-X"; R="VERIFIED_EVENT_EXISTENCE"

def _watch(con):
    persist_source_reliability_observation(
        con,observation_key="critical-1",source_id=S,rule_key=R,
        outcome="CRITICAL_FAILURE",severity="CRITICAL",weight=1,
        rationale=["test"])
    recompute_profile(con,S,R)

def _shadow3(con):
    for i in range(3):
        evaluate_verification_policy(
            con,decision_key=f"shadow-{i}",event_instance_id=10+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False)

def _canary(con,n=3):
    _watch(con); _shadow3(con)
    c=start_canary(con,source_id=S,rule_key=R,max_decisions=n,approved_by="김프로")
    ds=[]
    for i in range(n):
        ds.append(evaluate_verification_policy(
            con,decision_key=f"canary-{i}",event_instance_id=100+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False))
    return c,ds

def test_cancelled_event_held_by_policy_is_prevented_critical_failure(tmp_path):
    con=init_db(tmp_path/"prevent.sqlite3")
    c,ds=_canary(con)
    o=record_outcome(con,decision_id=ds[0]["decision_id"],
                     event_truth="CANCELLED",confirmed_by="김프로")
    assert o["outcome_class"]=="PREVENTED_CRITICAL_FAILURE"
    assert o["critical_prevented"] is True
    con.close()

def test_held_event_blocked_by_policy_is_false_conservative_hold(tmp_path):
    con=init_db(tmp_path/"falsehold.sqlite3")
    c,ds=_canary(con)
    o=record_outcome(con,decision_id=ds[0]["decision_id"],
                     event_truth="EVENT_OCCURRED",confirmed_by="김프로")
    assert o["outcome_class"]=="FALSE_CONSERVATIVE_HOLD"
    assert o["false_conservative_hold"] is True
    con.close()

def test_outcome_is_idempotent(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3")
    c,ds=_canary(con)
    a=record_outcome(con,decision_id=ds[0]["decision_id"],
                     event_truth="CANCELLED",confirmed_by="김프로")
    b=record_outcome(con,decision_id=ds[0]["decision_id"],
                     event_truth="CANCELLED",confirmed_by="김프로")
    assert a["outcome_id"]==b["outcome_id"]
    assert b["created"] is False
    assert len(outcomes(con,c["canary_id"]))==1
    con.close()

def test_gate_ready_with_one_prevented_and_no_false_holds_after_exhaustion(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    c,ds=_canary(con,3)
    truths=["CANCELLED","CANCELLED","EVENT_DID_NOT_OCCUR"]
    for d,truth in zip(ds,truths):
        record_outcome(con,decision_id=d["decision_id"],event_truth=truth,confirmed_by="김프로")
    assert canaries(con)[0]["status"]=="EXHAUSTED"
    g=evaluate_canary_safety(con,c["canary_id"])
    assert g["status"]=="READY_FOR_FINAL_REVIEW"
    assert g["prevented_critical_count"]==3
    con.close()

def test_gate_blocks_excessive_false_conservative_hold(tmp_path):
    con=init_db(tmp_path/"blocked.sqlite3")
    c,ds=_canary(con,4)
    truths=["EVENT_OCCURRED","EVENT_OCCURRED","CANCELLED","CANCELLED"]
    for d,truth in zip(ds,truths):
        record_outcome(con,decision_id=d["decision_id"],event_truth=truth,confirmed_by="김프로")
    g=evaluate_canary_safety(con,c["canary_id"])
    assert g["status"]=="BLOCKED"
    assert g["false_conservative_hold_rate"]==pytest.approx(.5)
    con.close()

def test_final_promote_requires_ready_gate_and_human(tmp_path):
    con=init_db(tmp_path/"promote.sqlite3")
    c,ds=_canary(con,3)
    with pytest.raises(ValueError):
        final_review(con,canary_id=c["canary_id"],decision="PROMOTE",
                     reviewer="김프로")
    for d in ds:
        record_outcome(con,decision_id=d["decision_id"],event_truth="CANCELLED",confirmed_by="김프로")
    r=final_review(con,canary_id=c["canary_id"],decision="PROMOTE",
                   reviewer="김프로",reason="outcome gate passed")
    assert r["promotion_id"] is not None
    assert full_promotions(con)[0]["status"]=="ACTIVE"
    con.close()

def test_full_preventive_applies_shadow_action_to_new_events(tmp_path):
    con=init_db(tmp_path/"full.sqlite3")
    c,ds=_canary(con,3)
    for d in ds:
        record_outcome(con,decision_id=d["decision_id"],event_truth="CANCELLED",confirmed_by="김프로")
    final_review(con,canary_id=c["canary_id"],decision="PROMOTE",
                 reviewer="김프로")
    d=evaluate_verification_policy(
        con,decision_key="full-new",event_instance_id=999,
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=1,human_confirmed=False)
    assert d["production_mode"]=="FULL_PREVENTIVE"
    assert d["production_action"]=="REQUIRE_CORROBORATION"
    con.close()

def test_existing_verified_stays_unchanged_even_under_full_preventive(tmp_path):
    con=init_db(tmp_path/"existing.sqlite3")
    c,ds=_canary(con,3)
    for d in ds:
        record_outcome(con,decision_id=d["decision_id"],event_truth="CANCELLED",confirmed_by="김프로")
    final_review(con,canary_id=c["canary_id"],decision="PROMOTE",
                 reviewer="김프로")
    d=evaluate_verification_policy(
        con,decision_key="existing",event_instance_id=777,
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=1,human_confirmed=False,existing_verified=True)
    assert d["production_mode"]=="NO_RETROACTIVE_CHANGE"
    assert d["production_action"]=="KEEP_EXISTING_VERIFIED"
    con.close()
