from datetime import datetime, timezone, timedelta
import pytest

from src.database import init_db
from src.origin_threshold_scope_reintegration import (
    add_evidence,evaluate_gate,evaluations,review_for_canary,start_canary,
    canaries,record_canary_outcome,final_release,status
)
from src.origin_threshold_scope_isolation import (
    derive_scope_for_restriction,source_production_allowed
)
from src.source_reliability import evaluate_verification_policy

RULE="VERIFIED_EVENT_EXISTENCE"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _setup(con,risk="BASELINE",source="SRC-BAD"):
    now=_now()
    con.execute("""INSERT OR REPLACE INTO sources(
      source_id,platform,source_role,name,status,authority_level,access_state)
      VALUES(?,?,?,?,?,?,?)""",
      (source,"FACEBOOK","SECONDARY",source,"ACTIVE","SECONDARY","OPEN"))
    con.execute("""INSERT INTO origin_threshold_recurrence_profiles(
      recurrence_profile_id,signature,root_cause_type,dominant_source_id,
      dominant_platform,recurrence_count,post_requalification_recurrence_count,
      failed_effective_remediation_count,risk_band,long_term_restricted,
      reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,f"SOURCE_CONCENTRATION|{source}|*","SOURCE_CONCENTRATION",source,
       "FACEBOOK",3,2,1,risk,1,'[]',now))
    con.execute("""INSERT INTO origin_threshold_long_term_restrictions(
      restriction_id,recurrence_profile_id,signature,status,trigger_recovery_case_id,
      trigger_reason,recurrence_count,failed_effective_remediation_count,
      requires_human_exception,started_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (1,1,f"SOURCE_CONCENTRATION|{source}|*","ACTIVE",10,
       "repeat",3,1,1,now))
    con.execute("""INSERT INTO origin_threshold_recovery_cases(
      recovery_case_id,promotion_id,candidate_id,failed_threshold,fallback_threshold,
      status,rollback_reason,required_shadow_outcomes,safe_shadow_outcome_count,opened_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (10,10,10,.89,.86,"REQUALIFIED","test",5,5,now))
    con.execute("""INSERT INTO origin_threshold_root_causes(
      root_cause_id,recovery_case_id,promotion_id,failure_class,root_cause_type,
      risk_band,dominant_source_id,dominant_platform,source_concentration,
      boundary_distance,repeated_root_cause_count,evidence_json,reasons_json,attributed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (10,10,10,"FALSE_POSITIVE","SOURCE_CONCENTRATION",risk,source,"FACEBOOK",
       1.0,.2,3,'{}','[]',now))
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      remediation_ref,notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (10,10,10,"SOURCE_RULE_CHANGE","R-10","fix","human",now,"EFFECTIVE"))
    con.commit()
    return derive_scope_for_restriction(con,1)

def _evidence_set(con,scope_id,n=7,human_n=5,delta=0.0,start_hours=30):
    start=datetime.now(timezone.utc)-timedelta(hours=start_hours)
    for i in range(n):
        add_evidence(
            con,scope_id,100+i,"SAFE",
            human_confirmed=(i<human_n),
            alternative_quality_delta=delta if i<human_n else None,
            observed_at=(start+timedelta(minutes=i)).isoformat())

def _ready(con,scope_id):
    _evidence_set(con,scope_id)
    ev=evaluate_gate(con,scope_id,persist=True)
    assert ev["status"]=="READY_FOR_HUMAN_CANARY_REVIEW"
    review_for_canary(con,scope_id,ev["reintegration_evaluation_id"],
                      "APPROVE_CANARY","human","safe gate")
    return ev

def test_gate_requires_minimum_shadow_and_human_outcomes(tmp_path):
    con=init_db(tmp_path/"warm.sqlite3")
    s=_setup(con)
    _evidence_set(con,s["scope_id"],n=4,human_n=3)
    ev=evaluate_gate(con,s["scope_id"])
    assert ev["status"]=="WARMING"
    assert ev["shadow_count"]==4
    assert ev["decisive_human_count"]==3
    con.close()

def test_gate_requires_distinct_event_coverage(tmp_path):
    con=init_db(tmp_path/"events.sqlite3")
    s=_setup(con)
    start=datetime.now(timezone.utc)-timedelta(hours=30)
    for i in range(7):
        add_evidence(con,s["scope_id"],1,"SAFE",human_confirmed=(i<5),
                     alternative_quality_delta=0,
                     observed_at=(start+timedelta(minutes=i)).isoformat())
    ev=evaluate_gate(con,s["scope_id"])
    assert ev["status"]=="WARMING"
    assert ev["distinct_event_count"]==1
    con.close()

def test_false_corroboration_blocks_reintegration(tmp_path):
    con=init_db(tmp_path/"false.sqlite3")
    s=_setup(con)
    _evidence_set(con,s["scope_id"])
    add_evidence(con,s["scope_id"],999,"UNSAFE",human_confirmed=True,
                 false_corroboration=True,alternative_quality_delta=-.05,
                 observed_at=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat())
    ev=evaluate_gate(con,s["scope_id"])
    assert ev["status"]=="BLOCKED"
    assert ev["false_corroboration_count"]==1
    con.close()

def test_missed_syndication_blocks_reintegration(tmp_path):
    con=init_db(tmp_path/"miss.sqlite3")
    s=_setup(con)
    _evidence_set(con,s["scope_id"])
    add_evidence(con,s["scope_id"],998,"UNSAFE",human_confirmed=True,
                 missed_syndication=True,alternative_quality_delta=-.05,
                 observed_at=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat())
    ev=evaluate_gate(con,s["scope_id"])
    assert ev["status"]=="BLOCKED"
    assert ev["missed_syndication_count"]==1
    con.close()

def test_alternative_quality_regression_blocks_gate(tmp_path):
    con=init_db(tmp_path/"quality.sqlite3")
    s=_setup(con)
    _evidence_set(con,s["scope_id"],delta=-.20)
    ev=evaluate_gate(con,s["scope_id"])
    assert ev["status"]=="BLOCKED"
    assert ev["avg_alternative_quality_delta"]==pytest.approx(-.20)
    con.close()

def test_effective_remediation_is_required(tmp_path):
    con=init_db(tmp_path/"remediation.sqlite3")
    s=_setup(con)
    con.execute("DELETE FROM origin_threshold_remediations")
    con.commit()
    _evidence_set(con,s["scope_id"])
    ev=evaluate_gate(con,s["scope_id"])
    assert ev["status"]=="WARMING"
    assert ev["remediation_effective"] is False
    con.close()

def test_restricted_profile_uses_stricter_requirements(tmp_path):
    con=init_db(tmp_path/"restricted.sqlite3")
    s=_setup(con,risk="RESTRICTED")
    start=datetime.now(timezone.utc)-timedelta(hours=30)
    for i in range(8):
        add_evidence(con,s["scope_id"],200+i,"SAFE",human_confirmed=(i<6),
                     alternative_quality_delta=0,
                     observed_at=(start+timedelta(minutes=i)).isoformat())
    ev=evaluate_gate(con,s["scope_id"])
    assert ev["required_shadow_count"]==8
    assert ev["required_human_count"]==6
    assert ev["required_distinct_events"]==6
    assert ev["status"]=="READY_FOR_HUMAN_CANARY_REVIEW"
    con.close()

def test_canary_requires_human_approval(tmp_path):
    con=init_db(tmp_path/"approval.sqlite3")
    s=_setup(con)
    _evidence_set(con,s["scope_id"])
    ev=evaluate_gate(con,s["scope_id"],persist=True)
    with pytest.raises(ValueError,match="APPROVE_CANARY"):
        start_canary(con,s["scope_id"],ev["reintegration_evaluation_id"],"human")
    con.close()

def test_canary_assigns_only_bounded_events(tmp_path):
    con=init_db(tmp_path/"bounded.sqlite3")
    s=_setup(con)
    ev=_ready(con,s["scope_id"])
    c=start_canary(con,s["scope_id"],ev["reintegration_evaluation_id"],"human",3)
    for eid in (301,302,303):
        p=source_production_allowed(con,"SRC-BAD",RULE,eid)
        assert p["allowed"] is True
        assert p["production_action"]=="REINTEGRATION_CANARY"
        assert p["reintegration_canary_id"]==c["canary_id"]
    p=source_production_allowed(con,"SRC-BAD",RULE,304)
    assert p["allowed"] is False
    assert p["production_action"]=="BASE_ONLY_SHADOW_RESTRICTED"
    assert canaries(con,s["scope_id"])[0]["assigned_count"]==3
    con.close()

def test_unsafe_canary_outcome_fail_closed_rolls_back(tmp_path):
    con=init_db(tmp_path/"unsafe-canary.sqlite3")
    s=_setup(con)
    ev=_ready(con,s["scope_id"])
    c=start_canary(con,s["scope_id"],ev["reintegration_evaluation_id"],"human",3)
    source_production_allowed(con,"SRC-BAD",RULE,401)
    r=record_canary_outcome(con,c["canary_id"],401,"UNSAFE",
                            human_confirmed=True,false_corroboration=True)
    assert r["status"]=="ROLLED_BACK"
    # Scope remains ACTIVE, so subsequent event is blocked again.
    p=source_production_allowed(con,"SRC-BAD",RULE,402)
    assert p["allowed"] is False
    con.close()

def test_hold_canary_outcome_cannot_complete_release(tmp_path):
    con=init_db(tmp_path/"hold-canary.sqlite3")
    s=_setup(con)
    ev=_ready(con,s["scope_id"])
    c=start_canary(con,s["scope_id"],ev["reintegration_evaluation_id"],"human",1)
    source_production_allowed(con,"SRC-BAD",RULE,501)
    r=record_canary_outcome(con,c["canary_id"],501,"HOLD",human_confirmed=True)
    assert r["status"]=="ACTIVE"
    assert r["hold_count"]==1
    with pytest.raises(ValueError):
        final_release(con,c["canary_id"],"human","not safe")
    con.close()

def test_all_safe_canary_assignments_require_final_human_release(tmp_path):
    con=init_db(tmp_path/"safe-canary.sqlite3")
    s=_setup(con)
    ev=_ready(con,s["scope_id"])
    c=start_canary(con,s["scope_id"],ev["reintegration_evaluation_id"],"human",3)
    for eid in (601,602,603):
        source_production_allowed(con,"SRC-BAD",RULE,eid)
        r=record_canary_outcome(con,c["canary_id"],eid,"SAFE",human_confirmed=True)
    assert r["status"]=="READY_FOR_FINAL_RELEASE_REVIEW"
    # Scope still active until Human final release.
    assert source_production_allowed(con,"SRC-BAD",RULE)["allowed"] is False
    released=final_release(con,c["canary_id"],"human","3/3 safe")
    assert released["canary"]["status"]=="FULL_REINTEGRATED"
    assert released["scope"]["status"]=="RELEASED"
    assert source_production_allowed(con,"SRC-BAD",RULE)["allowed"] is True
    con.close()

def test_direct_verification_uses_reintegration_canary_mode(tmp_path):
    con=init_db(tmp_path/"direct.sqlite3")
    s=_setup(con)
    ev=_ready(con,s["scope_id"])
    c=start_canary(con,s["scope_id"],ev["reintegration_evaluation_id"],"human",1)
    q=evaluate_verification_policy(
        con,decision_key="direct",event_instance_id=701,source_id="SRC-BAD",
        rule_key=RULE,base_eligible=True,independent_source_count=1,
        human_confirmed=False,existing_verified=False)
    assert q["production_mode"]=="REINTEGRATION_CANARY"
    assert q["production_action"]=="ALLOW_VERIFIED"
    assert q["canary_id"]==c["canary_id"]
    con.close()

def test_existing_verified_invariant_still_wins_during_canary(tmp_path):
    con=init_db(tmp_path/"existing.sqlite3")
    s=_setup(con)
    ev=_ready(con,s["scope_id"])
    start_canary(con,s["scope_id"],ev["reintegration_evaluation_id"],"human",1)
    q=evaluate_verification_policy(
        con,decision_key="existing",event_instance_id=801,source_id="SRC-BAD",
        rule_key=RULE,base_eligible=True,independent_source_count=1,
        human_confirmed=False,existing_verified=True)
    assert q["production_mode"]=="NO_RETROACTIVE_CHANGE"
    assert q["production_action"]=="KEEP_EXISTING_VERIFIED"
    con.close()

def test_status_and_evaluation_history_are_persisted(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    s=_setup(con)
    _evidence_set(con,s["scope_id"])
    ev=evaluate_gate(con,s["scope_id"],persist=True)
    hist=evaluations(con,s["scope_id"])
    st=status(con)
    assert hist[-1]["reintegration_evaluation_id"]==ev["reintegration_evaluation_id"]
    assert st["policy_version"]=="v0.73"
    assert len(st["evidence"])==7
    assert len(st["evaluations"])==1
    con.close()
