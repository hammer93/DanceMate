import pytest

from src.database import init_db,persist_source_reliability_observation
from src.source_reliability import (
    recompute_profile,evaluate_verification_policy,start_canary
)
from src.preventive_policy_outcome import record_outcome,final_review,full_promotions
from src.preventive_recovery import (
    recovery_cases,record_root_cause,record_remediation,
    evaluate_recovery,requalify,recovery_events
)

S="SRC-REC"; R="VERIFIED_EVENT_EXISTENCE"

def _promote_and_rollback(con):
    persist_source_reliability_observation(
        con,observation_key="critical-rec",source_id=S,rule_key=R,
        outcome="CRITICAL_FAILURE",severity="CRITICAL",weight=1,rationale=["test"])
    recompute_profile(con,S,R)

    for i in range(3):
        evaluate_verification_policy(
            con,decision_key=f"shadow-pre-{i}",event_instance_id=10+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False)

    c=start_canary(con,source_id=S,rule_key=R,max_decisions=3,approved_by="김프로")
    ds=[]
    for i in range(3):
        ds.append(evaluate_verification_policy(
            con,decision_key=f"canary-pre-{i}",event_instance_id=100+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False))
    for d in ds:
        record_outcome(con,decision_id=d["decision_id"],
                       event_truth="CANCELLED",confirmed_by="김프로")
    fr=final_review(con,canary_id=c["canary_id"],decision="PROMOTE",
                    reviewer="김프로")

    full=evaluate_verification_policy(
        con,decision_key="full-missed-recovery",event_instance_id=500,
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=2,human_confirmed=False)
    o=record_outcome(con,decision_id=full["decision_id"],
                     event_truth="EVENT_DID_NOT_OCCUR",confirmed_by="김프로")
    assert o["runtime_guard"]["guard"]["rolled_back"] is True
    return fr["promotion_id"],recovery_cases(con)[0]["recovery_case_id"]

def _safe_recovery_window(con):
    rows=[]
    for i in range(3):
        d=evaluate_verification_policy(
            con,decision_key=f"recovery-shadow-{i}",event_instance_id=600+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False)
        assert d["production_mode"]=="BASE_WITH_SHADOW"
        rows.append(d)
        o=record_outcome(con,decision_id=d["decision_id"],
                         event_truth="CANCELLED",confirmed_by="김프로")
        assert o["outcome_class"]=="PREVENTED_CRITICAL_FAILURE"
    return rows

def test_fail_closed_rollback_opens_recovery_case(tmp_path):
    con=init_db(tmp_path/"open.sqlite3")
    pid,rid=_promote_and_rollback(con)
    case=recovery_cases(con)[0]
    assert case["failed_promotion_id"]==pid
    assert case["status"]=="OPEN"
    assert case["source_id"]==S
    assert any(e["event_type"]=="RECOVERY_OPENED" for e in recovery_events(con,rid))
    con.close()

def test_new_canary_is_blocked_until_requalified(tmp_path):
    con=init_db(tmp_path/"blocked.sqlite3")
    _,rid=_promote_and_rollback(con)
    with pytest.raises(ValueError,match="must be REQUALIFIED"):
        start_canary(con,source_id=S,rule_key=R,max_decisions=2,approved_by="김프로")
    con.close()

def test_root_cause_and_remediation_alone_are_not_enough(tmp_path):
    con=init_db(tmp_path/"notenough.sqlite3")
    _,rid=_promote_and_rollback(con)
    record_root_cause(con,recovery_case_id=rid,
                      root_cause="independent corroboration accepted stale cancellation state",
                      actor="김프로")
    record_remediation(con,recovery_case_id=rid,
                       remediation_ref="CHANGE-REC-001",actor="김프로",
                       notes="tighten refresh freshness check")
    g=evaluate_recovery(con,rid)
    assert g["status"]=="OBSERVING"
    assert g["shadow_decision_count"]==0
    assert g["confirmed_outcome_count"]==0
    con.close()

def test_safe_post_rollback_window_becomes_ready(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    _,rid=_promote_and_rollback(con)
    record_root_cause(con,recovery_case_id=rid,
                      root_cause="stale refresh state",actor="김프로")
    record_remediation(con,recovery_case_id=rid,
                       remediation_ref="CHANGE-REC-002",actor="김프로")
    _safe_recovery_window(con)
    g=evaluate_recovery(con,rid)
    assert g["status"]=="READY_FOR_REQUALIFICATION"
    assert g["shadow_decision_count"]==3
    assert g["confirmed_outcome_count"]==3
    assert g["safe_outcome_count"]==3
    assert g["missed_critical_count"]==0
    con.close()

def test_false_conservative_hold_blocks_requalification(tmp_path):
    con=init_db(tmp_path/"falsehold.sqlite3")
    _,rid=_promote_and_rollback(con)
    record_root_cause(con,recovery_case_id=rid,root_cause="stale rule",actor="김프로")
    record_remediation(con,recovery_case_id=rid,remediation_ref="CHANGE-REC-003",actor="김프로")
    for i,truth in enumerate(["EVENT_OCCURRED","CANCELLED","CANCELLED"]):
        d=evaluate_verification_policy(
            con,decision_key=f"recovery-mixed-{i}",event_instance_id=700+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False)
        record_outcome(con,decision_id=d["decision_id"],event_truth=truth,confirmed_by="김프로")
    g=evaluate_recovery(con,rid)
    assert g["status"]=="OBSERVING"
    assert g["false_conservative_hold_rate"]==pytest.approx(1/3)
    con.close()

def test_human_requalification_required_before_new_canary(tmp_path):
    con=init_db(tmp_path/"requal.sqlite3")
    _,rid=_promote_and_rollback(con)
    record_root_cause(con,recovery_case_id=rid,root_cause="root cause fixed",actor="김프로")
    record_remediation(con,recovery_case_id=rid,remediation_ref="CHANGE-REC-004",actor="김프로")
    _safe_recovery_window(con)
    assert evaluate_recovery(con,rid)["status"]=="READY_FOR_REQUALIFICATION"

    with pytest.raises(ValueError):
        start_canary(con,source_id=S,rule_key=R,max_decisions=2,approved_by="김프로")

    r=requalify(con,recovery_case_id=rid,actor="김프로")
    assert r["status"]=="REQUALIFIED"

    c=start_canary(con,source_id=S,rule_key=R,max_decisions=2,approved_by="김프로")
    assert c["created"] is True
    assert recovery_cases(con)[0]["status"]=="REQUALIFIED"
    assert any(e["event_type"]=="HUMAN_REQUALIFIED" for e in recovery_events(con,rid))
    con.close()

def test_requalification_cannot_be_automatic_or_early(tmp_path):
    con=init_db(tmp_path/"early.sqlite3")
    _,rid=_promote_and_rollback(con)
    record_root_cause(con,recovery_case_id=rid,root_cause="known",actor="김프로")
    record_remediation(con,recovery_case_id=rid,remediation_ref="CHANGE-REC-005",actor="김프로")
    with pytest.raises(ValueError,match="not READY"):
        requalify(con,recovery_case_id=rid,actor="김프로")
    con.close()
