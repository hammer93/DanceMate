import pytest

from src.database import init_db,persist_source_reliability_observation
from src.source_reliability import (
    recompute_profile,evaluate_verification_policy,start_canary
)
from src.preventive_policy_outcome import (
    record_outcome,final_review,full_promotions
)
from src.preventive_full_runtime_guard import (
    evaluate_runtime_guard,guard_history,runtime_observations,guard_events
)

S="SRC-RUNTIME"; R="VERIFIED_EVENT_EXISTENCE"

def _promote(con):
    persist_source_reliability_observation(
        con,observation_key="critical-runtime",source_id=S,rule_key=R,
        outcome="CRITICAL_FAILURE",severity="CRITICAL",weight=1,rationale=["test"])
    recompute_profile(con,S,R)
    for i in range(3):
        evaluate_verification_policy(
            con,decision_key=f"shadow-r-{i}",event_instance_id=10+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False)
    c=start_canary(con,source_id=S,rule_key=R,max_decisions=3,approved_by="김프로")
    canary=[]
    for i in range(3):
        canary.append(evaluate_verification_policy(
            con,decision_key=f"canary-r-{i}",event_instance_id=100+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False))
    for d in canary:
        record_outcome(con,decision_id=d["decision_id"],
                       event_truth="CANCELLED",confirmed_by="김프로")
    fr=final_review(con,canary_id=c["canary_id"],decision="PROMOTE",
                    reviewer="김프로",reason="safe canary")
    return fr["promotion_id"]

def _full_decision(con,key,idx,sources=1,human=False):
    return evaluate_verification_policy(
        con,decision_key=key,event_instance_id=1000+idx,
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=sources,human_confirmed=human)

def test_full_runtime_outcome_is_tracked_and_guard_observes(tmp_path):
    con=init_db(tmp_path/"observe.sqlite3")
    pid=_promote(con)
    d=_full_decision(con,"full-observe",1)
    o=record_outcome(con,decision_id=d["decision_id"],
                     event_truth="CANCELLED",confirmed_by="김프로")
    assert o["runtime_guard"]["tracked"] is True
    assert o["runtime_guard"]["guard"]["status"]=="OBSERVING"
    rows=runtime_observations(con,pid)
    assert len(rows)==1
    assert rows[0]["critical_prevented"]==1
    con.close()

def test_missed_critical_failure_immediately_rolls_back_full_promotion(tmp_path):
    con=init_db(tmp_path/"missed.sqlite3")
    pid=_promote(con)
    # WATCH + two independent sources allows VERIFIED. Ground truth says cancelled -> missed critical.
    d=_full_decision(con,"full-missed",2,sources=2)
    assert d["production_action"]=="ALLOW_VERIFIED"
    o=record_outcome(con,decision_id=d["decision_id"],
                     event_truth="CANCELLED",confirmed_by="김프로")
    g=o["runtime_guard"]["guard"]
    assert o["outcome_class"]=="MISSED_CRITICAL_FAILURE"
    assert g["status"]=="BLOCKED"
    assert g["action"]=="FAIL_CLOSED_ROLLBACK"
    assert g["rolled_back"] is True
    assert full_promotions(con)[0]["status"]=="ROLLED_BACK"
    assert any(e["event_type"]=="AUTO_FAIL_CLOSED_ROLLBACK" for e in guard_events(con,pid))
    con.close()

def test_after_auto_rollback_future_event_returns_to_base_with_shadow(tmp_path):
    con=init_db(tmp_path/"fallback.sqlite3")
    _promote(con)
    d=_full_decision(con,"full-trigger",1,sources=2)
    record_outcome(con,decision_id=d["decision_id"],
                   event_truth="EVENT_DID_NOT_OCCUR",confirmed_by="김프로")
    future=_full_decision(con,"future-after-rollback",2,sources=1)
    assert future["production_mode"]=="BASE_WITH_SHADOW"
    assert future["production_action"]=="ALLOW_VERIFIED"
    assert future["shadow_action"]=="REQUIRE_CORROBORATION"
    con.close()

def test_existing_verified_remains_unchanged_after_runtime_rollback(tmp_path):
    con=init_db(tmp_path/"existing.sqlite3")
    _promote(con)
    d=_full_decision(con,"trigger",1,sources=2)
    record_outcome(con,decision_id=d["decision_id"],
                   event_truth="CANCELLED",confirmed_by="김프로")
    existing=evaluate_verification_policy(
        con,decision_key="existing-runtime",event_instance_id=777,
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=1,human_confirmed=False,existing_verified=True)
    assert existing["production_mode"]=="NO_RETROACTIVE_CHANGE"
    assert existing["production_action"]=="KEEP_EXISTING_VERIFIED"
    con.close()

def test_recent5_excess_false_holds_roll_back(tmp_path):
    con=init_db(tmp_path/"falsehold5.sqlite3")
    pid=_promote(con)
    truths=["EVENT_OCCURRED","EVENT_OCCURRED","EVENT_OCCURRED","CANCELLED","CANCELLED"]
    last=None
    for i,truth in enumerate(truths):
        d=_full_decision(con,f"fh-{i}",i,sources=1)
        last=record_outcome(con,decision_id=d["decision_id"],
                            event_truth=truth,confirmed_by="김프로")
    g=last["runtime_guard"]["guard"]
    assert g["recent5_false_hold_rate"]==pytest.approx(.6)
    assert g["status"]=="BLOCKED"
    assert full_promotions(con)[0]["status"]=="ROLLED_BACK"
    con.close()

def test_ten_safe_runtime_outcomes_reach_stable_full(tmp_path):
    con=init_db(tmp_path/"stable.sqlite3")
    pid=_promote(con)
    last=None
    # 1 normal event falsely held + 9 cancelled events correctly held = 10% false-hold.
    truths=["EVENT_OCCURRED"]+["CANCELLED"]*9
    for i,truth in enumerate(truths):
        d=_full_decision(con,f"stable-{i}",i,sources=1)
        last=record_outcome(con,decision_id=d["decision_id"],
                            event_truth=truth,confirmed_by="김프로")
    g=last["runtime_guard"]["guard"]
    assert g["status"]=="STABLE_FULL"
    assert g["recent10_false_hold_rate"]==pytest.approx(.1)
    assert g["missed_critical_count"]==0
    assert full_promotions(con)[0]["status"]=="ACTIVE"
    con.close()

def test_runtime_guard_manual_evaluation_is_audited(tmp_path):
    con=init_db(tmp_path/"manual.sqlite3")
    pid=_promote(con)
    g=evaluate_runtime_guard(con,pid)
    assert g["status"]=="OBSERVING"
    assert len(guard_history(con,pid))==1
    con.close()
