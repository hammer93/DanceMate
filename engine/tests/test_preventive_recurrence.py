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
from src.preventive_recurrence import (
    recurrence_policy,recurrence_profiles,approve_exception,
    recurrence_exceptions
)

S="SRC-RECUR"; R="VERIFIED_EVENT_EXISTENCE"

def _seed(con):
    persist_source_reliability_observation(
        con,observation_key="critical-recur",source_id=S,rule_key=R,
        outcome="CRITICAL_FAILURE",severity="CRITICAL",weight=1,rationale=["test"])
    recompute_profile(con,S,R)
    for i in range(3):
        evaluate_verification_policy(
            con,decision_key=f"initial-shadow-{i}",event_instance_id=10+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False)

def _canary_promote_and_fail(con,prefix):
    c=start_canary(con,source_id=S,rule_key=R,max_decisions=3,approved_by="김프로")
    ds=[]
    for i in range(3):
        ds.append(evaluate_verification_policy(
            con,decision_key=f"{prefix}-canary-{i}",event_instance_id=1000+i+len(recovery_cases(con))*100,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False))
    for d in ds:
        record_outcome(con,decision_id=d["decision_id"],
                       event_truth="CANCELLED",confirmed_by="김프로")
    fr=final_review(con,canary_id=c["canary_id"],decision="PROMOTE",
                    reviewer="김프로",reason="safe canary")
    full=evaluate_verification_policy(
        con,decision_key=f"{prefix}-full-miss",event_instance_id=9000+len(recovery_cases(con)),
        source_id=S,rule_key=R,base_eligible=True,
        independent_source_count=2,human_confirmed=False)
    miss=record_outcome(con,decision_id=full["decision_id"],
                        event_truth="EVENT_DID_NOT_OCCUR",confirmed_by="김프로")
    assert miss["runtime_guard"]["guard"]["rolled_back"] is True
    return recovery_cases(con)[-1]["recovery_case_id"]

def _recovery_evidence(con,rid,count,prefix):
    for i in range(count):
        d=evaluate_verification_policy(
            con,decision_key=f"{prefix}-recovery-{i}",event_instance_id=5000+rid*100+i,
            source_id=S,rule_key=R,base_eligible=True,
            independent_source_count=1,human_confirmed=False)
        assert d["production_mode"]=="BASE_WITH_SHADOW"
        record_outcome(con,decision_id=d["decision_id"],
                       event_truth="CANCELLED",confirmed_by="김프로")

def _complete_first_recovery(con,root="freshness miss",rem="CHANGE-R1"):
    rid=_canary_promote_and_fail(con,"cycle1")
    record_root_cause(con,recovery_case_id=rid,root_cause=root,actor="김프로")
    record_remediation(con,recovery_case_id=rid,remediation_ref=rem,actor="김프로")
    _recovery_evidence(con,rid,3,"cycle1")
    g=evaluate_recovery(con,rid)
    assert g["status"]=="READY_FOR_REQUALIFICATION"
    requalify(con,recovery_case_id=rid,actor="김프로")
    return rid

def test_first_recurrence_profile_is_baseline(tmp_path):
    con=init_db(tmp_path/"baseline.sqlite3")
    _seed(con)
    rid=_canary_promote_and_fail(con,"first")
    p=recurrence_policy(con,rid)
    assert p["recurrence_count"]==1
    assert p["risk_band"]=="BASELINE"
    assert p["required_shadow_decisions"]==3
    assert p["required_confirmed_outcomes"]==3
    assert p["max_false_hold_rate"]==pytest.approx(.25)
    assert p["human_exception_required"] is False
    con.close()

def test_second_rollback_escalates_to_elevated_and_marks_prior_remediation_ineffective(tmp_path):
    con=init_db(tmp_path/"elevated.sqlite3")
    _seed(con)
    _complete_first_recovery(con,root="freshness miss",rem="CHANGE-R1")
    rid2=_canary_promote_and_fail(con,"cycle2")
    p=recurrence_policy(con,rid2)
    assert p["recurrence_count"]==2
    assert p["risk_band"]=="ELEVATED"
    assert p["required_shadow_decisions"]==5
    assert p["required_confirmed_outcomes"]==5
    assert p["max_false_hold_rate"]==pytest.approx(.20)
    assert p["remediation_effective"]=="INEFFECTIVE"
    assert p["previous_remediation_ref"]=="CHANGE-R1"
    prof=recurrence_profiles(con)[0]
    assert prof["ineffective_remediation_count"]==1
    con.close()

def test_elevated_recovery_needs_five_new_shadow_outcomes(tmp_path):
    con=init_db(tmp_path/"need5.sqlite3")
    _seed(con)
    _complete_first_recovery(con)
    rid2=_canary_promote_and_fail(con,"cycle2")
    record_root_cause(con,recovery_case_id=rid2,root_cause="different parser miss",actor="김프로")
    record_remediation(con,recovery_case_id=rid2,remediation_ref="CHANGE-R2",actor="김프로")
    _recovery_evidence(con,rid2,3,"cycle2a")
    g=evaluate_recovery(con,rid2)
    assert g["status"]=="OBSERVING"
    assert g["required_shadow_decisions"]==5
    _recovery_evidence(con,rid2,2,"cycle2b")
    g=evaluate_recovery(con,rid2)
    assert g["status"]=="READY_FOR_REQUALIFICATION"
    con.close()

def test_same_root_cause_repeat_immediately_restricts_second_recovery(tmp_path):
    con=init_db(tmp_path/"same-root.sqlite3")
    _seed(con)
    _complete_first_recovery(con,root="same stale cancellation root")
    rid2=_canary_promote_and_fail(con,"cycle2")
    record_root_cause(con,recovery_case_id=rid2,
                      root_cause=" SAME   stale cancellation root ",actor="김프로")
    p=recurrence_policy(con,rid2)
    assert p["recurrence_count"]==2
    assert p["repeated_root_cause"] is True
    assert p["risk_band"]=="RESTRICTED"
    assert p["long_term_restricted"] is True
    assert p["required_shadow_decisions"]==7
    assert p["human_exception_required"] is True
    con.close()

def test_restricted_case_cannot_requalify_without_human_exception(tmp_path):
    con=init_db(tmp_path/"exception-required.sqlite3")
    _seed(con)
    _complete_first_recovery(con,root="repeat root")
    rid2=_canary_promote_and_fail(con,"cycle2")
    record_root_cause(con,recovery_case_id=rid2,root_cause="repeat root",actor="김프로")
    record_remediation(con,recovery_case_id=rid2,remediation_ref="CHANGE-R2",actor="김프로")
    _recovery_evidence(con,rid2,7,"restricted")
    g=evaluate_recovery(con,rid2)
    assert g["status"]=="OBSERVING"
    assert g["human_exception_required"] is True
    assert g["human_exception_approved"] is False
    with pytest.raises(ValueError,match="not READY"):
        requalify(con,recovery_case_id=rid2,actor="김프로")
    con.close()

def test_human_exception_approval_unlocks_restricted_requalification(tmp_path):
    con=init_db(tmp_path/"exception-approve.sqlite3")
    _seed(con)
    _complete_first_recovery(con,root="repeat root")
    rid2=_canary_promote_and_fail(con,"cycle2")
    record_root_cause(con,recovery_case_id=rid2,root_cause="repeat root",actor="김프로")
    record_remediation(con,recovery_case_id=rid2,remediation_ref="CHANGE-R2",actor="김프로")
    _recovery_evidence(con,rid2,7,"restricted")
    x=approve_exception(con,recovery_case_id=rid2,decision="APPROVE",
                        approved_by="김프로",
                        reason="root cause independently verified and remediation validated")
    assert x["decision"]=="APPROVE"
    g=evaluate_recovery(con,rid2)
    assert g["status"]=="READY_FOR_REQUALIFICATION"
    assert g["human_exception_approved"] is True
    r=requalify(con,recovery_case_id=rid2,actor="김프로")
    assert r["status"]=="REQUALIFIED"
    assert recurrence_exceptions(con,rid2)[0]["decision"]=="APPROVE"
    con.close()

def test_exception_deny_does_not_unlock_requalification(tmp_path):
    con=init_db(tmp_path/"exception-deny.sqlite3")
    _seed(con)
    _complete_first_recovery(con,root="repeat root")
    rid2=_canary_promote_and_fail(con,"cycle2")
    record_root_cause(con,recovery_case_id=rid2,root_cause="repeat root",actor="김프로")
    record_remediation(con,recovery_case_id=rid2,remediation_ref="CHANGE-R2",actor="김프로")
    _recovery_evidence(con,rid2,7,"restricted")
    approve_exception(con,recovery_case_id=rid2,decision="DENY",
                      approved_by="김프로",reason="remediation evidence not convincing")
    g=evaluate_recovery(con,rid2)
    assert g["status"]=="OBSERVING"
    assert g["human_exception_approved"] is False
    con.close()

def test_recurrence_profiles_remain_internal_and_auditable(tmp_path):
    con=init_db(tmp_path/"audit.sqlite3")
    _seed(con)
    _complete_first_recovery(con)
    rid2=_canary_promote_and_fail(con,"cycle2")
    p=recurrence_policy(con,rid2)
    rows=recurrence_profiles(con)
    assert len(rows)==1
    assert rows[0]["source_id"]==S
    assert rows[0]["recurrence_count"]==2
    assert p["requalified_failure_count"]==1
    con.close()
