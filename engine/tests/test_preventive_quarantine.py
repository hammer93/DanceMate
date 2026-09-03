from datetime import datetime, timezone, timedelta
import pytest

from src.database import init_db,persist_source_reliability_observation
from src.source_reliability import (
    recompute_profile,evaluate_verification_policy,start_canary
)
from src.preventive_policy_outcome import record_outcome,final_review
from src.preventive_recovery import (
    recovery_cases,record_root_cause,record_remediation,
    evaluate_recovery,requalify
)
from src.preventive_recurrence import approve_exception
from src.preventive_quarantine import (
    quarantines,evaluate_reintegration,release_review,
    quarantine_events,release_reviews
)

S="SRC-Q"; R="VERIFIED_EVENT_EXISTENCE"

def _seed(con):
    persist_source_reliability_observation(
        con,observation_key="critical-q",source_id=S,rule_key=R,
        outcome="CRITICAL_FAILURE",severity="CRITICAL",weight=1,rationale=["test"])
    recompute_profile(con,S,R)
    for i in range(3):
        evaluate_verification_policy(
            con,decision_key=f"seed-q-{i}",event_instance_id=10+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False)

def _fail_cycle(con,prefix):
    c=start_canary(con,source_id=S,rule_key=R,max_decisions=3,approved_by="김프로")
    ds=[]
    for i in range(3):
        ds.append(evaluate_verification_policy(
            con,decision_key=f"{prefix}-canary-{i}",
            event_instance_id=1000+len(recovery_cases(con))*100+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False))
    for d in ds:
        record_outcome(con,decision_id=d["decision_id"],
                       event_truth="CANCELLED",confirmed_by="김프로")
    final_review(con,canary_id=c["canary_id"],decision="PROMOTE",
                 reviewer="김프로",reason="safe canary")
    full=evaluate_verification_policy(
        con,decision_key=f"{prefix}-full-miss",
        event_instance_id=8000+len(recovery_cases(con)),
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=2,human_confirmed=False)
    o=record_outcome(con,decision_id=full["decision_id"],
                     event_truth="EVENT_DID_NOT_OCCUR",confirmed_by="김프로")
    assert o["runtime_guard"]["guard"]["rolled_back"] is True
    return recovery_cases(con)[-1]["recovery_case_id"]

def _recovery_safe(con,rid,count,prefix,quarantine=False):
    for i in range(count):
        independent=2 if quarantine and i<3 else 1
        truth="EVENT_OCCURRED" if independent>=2 else "CANCELLED"
        d=evaluate_verification_policy(
            con,decision_key=f"{prefix}-recovery-{i}",
            event_instance_id=5000+rid*100+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=independent,human_confirmed=False)
        if quarantine:
            assert d["production_mode"]=="QUARANTINE_SHADOW"
            assert d["production_action"]=="QUARANTINE_HOLD"
        record_outcome(con,decision_id=d["decision_id"],
                       event_truth=truth,confirmed_by="김프로")

def _complete_baseline(con):
    r1=_fail_cycle(con,"q-cycle1")
    record_root_cause(con,recovery_case_id=r1,root_cause="repeat root",actor="김프로")
    record_remediation(con,recovery_case_id=r1,remediation_ref="CHANGE-Q1",actor="김프로")
    _recovery_safe(con,r1,3,"q-r1")
    assert evaluate_recovery(con,r1)["status"]=="READY_FOR_REQUALIFICATION"
    requalify(con,recovery_case_id=r1,actor="김프로")
    return r1

def _complete_restricted_second(con):
    _complete_baseline(con)
    r2=_fail_cycle(con,"q-cycle2")
    record_root_cause(con,recovery_case_id=r2,root_cause=" REPEAT   root ",actor="김프로")
    record_remediation(con,recovery_case_id=r2,remediation_ref="CHANGE-Q2",actor="김프로")
    _recovery_safe(con,r2,7,"q-r2")
    approve_exception(con,recovery_case_id=r2,decision="APPROVE",
                      approved_by="김프로",reason="validated restricted recovery")
    assert evaluate_recovery(con,r2)["status"]=="READY_FOR_REQUALIFICATION"
    requalify(con,recovery_case_id=r2,actor="김프로")
    return r2

def _open_quarantine(con):
    _complete_restricted_second(con)
    r3=_fail_cycle(con,"q-cycle3")
    q=quarantines(con)[0]
    assert q["trigger_recovery_case_id"]==r3
    return r3,q["quarantine_id"]

def _prepare_release_ready(con):
    r3,qid=_open_quarantine(con)
    record_root_cause(con,recovery_case_id=r3,root_cause="third recurrence root",actor="김프로")
    record_remediation(con,recovery_case_id=r3,remediation_ref="CHANGE-Q3",actor="김프로")
    approve_exception(con,recovery_case_id=r3,decision="APPROVE",
                      approved_by="김프로",reason="third recurrence remediation validated")
    _recovery_safe(con,r3,7,"q-r3",quarantine=True)
    assert evaluate_recovery(con,r3)["status"]=="READY_FOR_REQUALIFICATION"
    requalify(con,recovery_case_id=r3,actor="김프로")
    old=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
    con.execute("UPDATE preventive_quarantines SET started_at=? WHERE quarantine_id=?",(old,qid))
    con.commit()
    return r3,qid

def test_failure_after_requalified_restricted_recovery_opens_quarantine(tmp_path):
    con=init_db(tmp_path/"q-open.sqlite3")
    _seed(con)
    r3,qid=_open_quarantine(con)
    q=quarantines(con)[0]
    assert q["status"]=="ACTIVE"
    assert q["trigger_recovery_case_id"]==r3
    assert any(e["event_type"]=="QUARANTINE_STARTED" for e in quarantine_events(con,qid))
    con.close()

def test_quarantine_forces_new_decisions_to_shadow_hold(tmp_path):
    con=init_db(tmp_path/"q-shadow.sqlite3")
    _seed(con)
    _,qid=_open_quarantine(con)
    d=evaluate_verification_policy(
        con,decision_key="quarantine-new",event_instance_id=9901,
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=2,human_confirmed=False)
    assert d["production_mode"]=="QUARANTINE_SHADOW"
    assert d["production_action"]=="QUARANTINE_HOLD"
    assert d["shadow_action"]=="ALLOW_VERIFIED"
    con.close()

def test_existing_verified_is_never_changed_by_quarantine(tmp_path):
    con=init_db(tmp_path/"q-existing.sqlite3")
    _seed(con)
    _open_quarantine(con)
    d=evaluate_verification_policy(
        con,decision_key="existing-q",event_instance_id=9992,
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=1,human_confirmed=False,existing_verified=True)
    assert d["production_mode"]=="NO_RETROACTIVE_CHANGE"
    assert d["production_action"]=="KEEP_EXISTING_VERIFIED"
    con.close()

def test_release_gate_needs_duration_recovery_and_alternative_coverage(tmp_path):
    con=init_db(tmp_path/"q-gate.sqlite3")
    _seed(con)
    r3,qid=_open_quarantine(con)
    g=evaluate_reintegration(con,qid)
    assert g["status"]=="OBSERVING"
    assert g["elapsed_hours"]<24
    assert g["recovery_requalified"] is False
    assert g["independent_alternative_count"]==0
    con.close()

def test_ready_reintegration_requires_safe_7_and_three_alternatives(tmp_path):
    con=init_db(tmp_path/"q-ready.sqlite3")
    _seed(con)
    _,qid=_prepare_release_ready(con)
    g=evaluate_reintegration(con,qid)
    assert g["status"]=="READY_FOR_RELEASE_REVIEW"
    assert g["shadow_decision_count"]>=7
    assert g["confirmed_outcome_count"]>=7
    assert g["safe_outcome_count"]==g["confirmed_outcome_count"]
    assert g["missed_critical_count"]==0
    assert g["independent_alternative_count"]>=3
    assert g["elapsed_hours"]>=24
    assert g["recovery_requalified"] is True
    con.close()

def test_release_is_human_review_only(tmp_path):
    con=init_db(tmp_path/"q-release.sqlite3")
    _seed(con)
    _,qid=_prepare_release_ready(con)
    r=release_review(con,quarantine_id=qid,decision="APPROVE",
                     reviewer="김프로",reason="controlled reintegration evidence validated")
    assert r["quarantine_status"]=="RELEASED"
    assert quarantines(con)[0]["status"]=="RELEASED"
    assert release_reviews(con,qid)[0]["decision"]=="APPROVE"
    assert any(e["event_type"]=="QUARANTINE_RELEASED" for e in quarantine_events(con,qid))
    con.close()

def test_release_before_gate_ready_is_rejected(tmp_path):
    con=init_db(tmp_path/"q-early-release.sqlite3")
    _seed(con)
    _,qid=_open_quarantine(con)
    with pytest.raises(ValueError,match="not READY"):
        release_review(con,quarantine_id=qid,decision="APPROVE",
                       reviewer="김프로",reason="too early")
    con.close()

def test_active_quarantine_blocks_canary_even_after_recovery_requalified(tmp_path):
    con=init_db(tmp_path/"q-canary-block.sqlite3")
    _seed(con)
    _,qid=_prepare_release_ready(con)
    with pytest.raises(ValueError,match="Quarantine"):
        start_canary(con,source_id=S,rule_key=R,max_decisions=3,approved_by="김프로")
    con.close()

def test_first_canary_after_release_is_limited_to_three_decisions(tmp_path):
    con=init_db(tmp_path/"q-limited-canary.sqlite3")
    _seed(con)
    _,qid=_prepare_release_ready(con)
    release_review(con,quarantine_id=qid,decision="APPROVE",
                   reviewer="김프로",reason="release approved")
    with pytest.raises(ValueError,match="limited to 3"):
        start_canary(con,source_id=S,rule_key=R,max_decisions=4,approved_by="김프로")
    c=start_canary(con,source_id=S,rule_key=R,max_decisions=3,approved_by="김프로")
    assert c["created"] is True
    assert c["reintegration"] is True
    assert c["quarantine_id"]==qid
    con.close()
