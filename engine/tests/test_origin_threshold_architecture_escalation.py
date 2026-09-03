from datetime import datetime, timezone, timedelta
import pytest

from src.database import init_db
from src.origin_threshold_architecture_escalation import (
    create_plan,plans,approve_plan,complete_step,add_validation_evidence,
    evaluate_plan,architecture_review,architecture_gate_for_scope,status
)
from src.origin_threshold_scope_reintegration import (
    add_evidence as add_scope_evidence,evaluate_gate as evaluate_scope_gate,
    review_for_canary,start_canary
)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _setup(con,architecture=True,blocked=None):
    old=(datetime.now(timezone.utc)-timedelta(hours=31)).isoformat()
    now=_now()
    con.execute("""INSERT INTO sources(
      source_id,platform,source_role,name,status,authority_level,access_state)
      VALUES(?,?,?,?,?,?,?)""",
      ("SRC-BAD","FACEBOOK","SECONDARY","SRC-BAD","ACTIVE","SECONDARY","OPEN"))
    con.execute("""INSERT INTO origin_threshold_recurrence_profiles(
      recurrence_profile_id,signature,root_cause_type,dominant_source_id,
      dominant_platform,recurrence_count,post_requalification_recurrence_count,
      failed_effective_remediation_count,risk_band,long_term_restricted,
      reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,"SIG","SOURCE_CONCENTRATION","SRC-BAD","FACEBOOK",4,3,2,
       "RESTRICTED",1,'[]',now))
    con.execute("""INSERT INTO origin_threshold_long_term_restrictions(
      restriction_id,recurrence_profile_id,signature,status,trigger_recovery_case_id,
      trigger_reason,recurrence_count,failed_effective_remediation_count,
      requires_human_exception,started_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (1,1,"SIG","ACTIVE",10,"repeat",4,2,1,old))
    con.execute("""INSERT INTO origin_threshold_recovery_cases(
      recovery_case_id,promotion_id,candidate_id,failed_threshold,fallback_threshold,
      status,rollback_reason,required_shadow_outcomes,safe_shadow_outcome_count,opened_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (10,10,10,.89,.86,"REQUALIFIED","test",5,5,old))
    con.execute("""INSERT INTO origin_threshold_root_causes(
      root_cause_id,recovery_case_id,promotion_id,failure_class,root_cause_type,
      risk_band,dominant_source_id,dominant_platform,source_concentration,
      boundary_distance,repeated_root_cause_count,evidence_json,reasons_json,attributed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (10,10,10,"FALSE_POSITIVE","SOURCE_CONCENTRATION","RESTRICTED",
       "SRC-BAD","FACEBOOK",1.0,.2,4,'{}','[]',old))
    con.execute("""INSERT INTO origin_threshold_restriction_scopes(
      scope_id,restriction_id,scope_type,source_id,status,production_action,
      shadow_learning_enabled,reason,created_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (1,1,"SOURCE","SRC-BAD","ACTIVE","BASE_ONLY_SHADOW_RESTRICTED",
       1,"re-isolated",old))
    con.execute("""INSERT INTO origin_threshold_scope_reisolations(
      reisolation_id,scope_id,canary_id,trigger_post_observation_id,
      trigger_post_evaluation_id,status,reason,failure_count,
      requirement_penalty_level,reactivated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (1,1,1,None,None,"ACTIVE","repeat architecture failure",1,1,old))
    con.execute("""INSERT INTO origin_threshold_post_reintegration_root_causes(
      post_root_cause_id,reisolation_id,scope_id,canary_id,
      trigger_post_observation_id,root_cause_type,secondary_root_cause_type,
      severity,evidence_json,reasons_json,attributed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
      (1,1,1,1,None,"SOURCE_LOCAL_RECURRENCE",
       "REMEDIATION_INEFFECTIVE_RECURRENCE","CRITICAL",'{}','[]',old))
    import json
    con.execute("""INSERT INTO origin_threshold_post_reintegration_remediation_routes(
      remediation_route_id,post_root_cause_id,reisolation_id,
      required_remediation_type,blocked_remediation_types_json,
      escalation_level,architecture_review_required,reason,created_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (1,1,1,"OTHER",json.dumps(blocked or ["SOURCE_RULE_CHANGE"]),
       2,int(bool(architecture)),"architecture escalation",old))
    con.commit()
    return datetime.fromisoformat(old)

def _approve_and_complete(con):
    p=create_plan(con,1,"architect","systemic repeat")
    p=approve_plan(con,p["architecture_plan_id"],"APPROVE","architect","plan approved")
    for step in p["steps"]:
        rid=100+step["step_order"]
        con.execute("""INSERT INTO origin_threshold_remediations(
          remediation_id,recovery_case_id,root_cause_id,remediation_type,
          remediation_ref,notes,submitted_by,submitted_at,status)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (rid,10,10,step["remediation_type"],f"ARCH-{rid}",
           "cross layer fix","engineer",_now(),"EFFECTIVE"))
        con.commit()
        p=complete_step(con,p["architecture_plan_id"],step["step_order"],
                        rid,"architect","step verified")
    return p

def _validation(con,plan_id,n=12,human=8,delta=0.0,unsafe=None):
    for i in range(n):
        add_validation_evidence(
            con,plan_id,200+i,
            "UNSAFE" if unsafe==i else "SAFE",
            human_confirmed=(i<human),
            false_corroboration=(unsafe==i),
            quality_delta=delta if i<human else None)

def test_plan_only_allowed_for_architecture_escalated_route(tmp_path):
    con=init_db(tmp_path/"not-arch.sqlite3")
    _setup(con,architecture=False)
    with pytest.raises(ValueError,match="only required"):
        create_plan(con,1,"architect","not needed")
    con.close()

def test_create_plan_has_multiple_cross_layer_steps_and_excludes_blocked(tmp_path):
    con=init_db(tmp_path/"create.sqlite3")
    _setup(con,blocked=["SOURCE_RULE_CHANGE"])
    p=create_plan(con,1,"architect","systemic repeat")
    assert p["required_step_count"]>=2
    assert len({s["remediation_type"] for s in p["steps"]})>=2
    assert "SOURCE_RULE_CHANGE" not in [s["remediation_type"] for s in p["steps"]]
    con.close()

def test_plan_requires_human_approval_before_step_completion(tmp_path):
    con=init_db(tmp_path/"approval.sqlite3")
    _setup(con)
    p=create_plan(con,1,"architect","repeat")
    step=p["steps"][0]
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?)""",
      (101,10,10,step["remediation_type"],"fix","eng",_now(),"EFFECTIVE"))
    con.commit()
    with pytest.raises(ValueError,match="approved"):
        complete_step(con,p["architecture_plan_id"],1,101,"architect","done")
    con.close()

def test_step_requires_human_effective_remediation(tmp_path):
    con=init_db(tmp_path/"effective.sqlite3")
    _setup(con)
    p=create_plan(con,1,"architect","repeat")
    p=approve_plan(con,p["architecture_plan_id"],"APPROVE","architect","go")
    step=p["steps"][0]
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?)""",
      (101,10,10,step["remediation_type"],"fix","eng",_now(),"SUBMITTED"))
    con.commit()
    with pytest.raises(ValueError,match="EFFECTIVE"):
        complete_step(con,p["architecture_plan_id"],1,101,"architect","done")
    con.close()

def test_step_rejects_wrong_remediation_type(tmp_path):
    con=init_db(tmp_path/"wrong-step.sqlite3")
    _setup(con)
    p=create_plan(con,1,"architect","repeat")
    p=approve_plan(con,p["architecture_plan_id"],"APPROVE","architect","go")
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?)""",
      (101,10,10,"THRESHOLD_CHANGE","wrong","eng",_now(),"EFFECTIVE"))
    con.commit()
    if p["steps"][0]["remediation_type"]!="THRESHOLD_CHANGE":
        with pytest.raises(ValueError,match="step requires"):
            complete_step(con,p["architecture_plan_id"],1,101,"architect","wrong")
    con.close()

def test_all_required_steps_must_be_effective(tmp_path):
    con=init_db(tmp_path/"steps.sqlite3")
    _setup(con)
    p=create_plan(con,1,"architect","repeat")
    approve_plan(con,p["architecture_plan_id"],"APPROVE","architect","go")
    _validation(con,p["architecture_plan_id"])
    ev=evaluate_plan(con,p["architecture_plan_id"])
    assert ev["status"]=="WARMING"
    assert ev["completed_required_steps"]==0
    con.close()

def test_cross_layer_validation_requires_12_shadow_8_human_8_events(tmp_path):
    con=init_db(tmp_path/"counts.sqlite3")
    _setup(con)
    p=_approve_and_complete(con)
    _validation(con,p["architecture_plan_id"],n=10,human=7)
    ev=evaluate_plan(con,p["architecture_plan_id"])
    assert ev["status"]=="WARMING"
    assert ev["shadow_count"]==10
    assert ev["human_safe_count"]==7
    assert ev["distinct_event_count"]==7
    con.close()

def test_false_corroboration_blocks_architecture_validation(tmp_path):
    con=init_db(tmp_path/"false.sqlite3")
    _setup(con)
    p=_approve_and_complete(con)
    _validation(con,p["architecture_plan_id"],unsafe=0)
    ev=evaluate_plan(con,p["architecture_plan_id"])
    assert ev["status"]=="BLOCKED"
    assert ev["false_corroboration_count"]==1
    con.close()

def test_quality_regression_below_minus_005_blocks_plan(tmp_path):
    con=init_db(tmp_path/"quality.sqlite3")
    _setup(con)
    p=_approve_and_complete(con)
    _validation(con,p["architecture_plan_id"],delta=-.10)
    ev=evaluate_plan(con,p["architecture_plan_id"])
    assert ev["status"]=="BLOCKED"
    con.close()

def test_complete_plan_and_validation_reaches_arch_review(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    _setup(con)
    p=_approve_and_complete(con)
    _validation(con,p["architecture_plan_id"])
    ev=evaluate_plan(con,p["architecture_plan_id"])
    assert ev["status"]=="READY_FOR_ARCH_REVIEW"
    assert plans(con,1)[-1]["status"]=="READY_FOR_ARCH_REVIEW"
    con.close()

def test_final_architecture_approval_is_required_for_gate(tmp_path):
    con=init_db(tmp_path/"final.sqlite3")
    _setup(con)
    p=_approve_and_complete(con)
    _validation(con,p["architecture_plan_id"])
    evaluate_plan(con,p["architecture_plan_id"])
    g=architecture_gate_for_scope(con,1)
    assert g["required"] is True and g["accepted"] is False
    architecture_review(con,p["architecture_plan_id"],"APPROVE_REINTEGRATION",
                        "chief-architect","all cross-layer checks passed")
    assert architecture_gate_for_scope(con,1)["accepted"] is True
    con.close()

def test_architecture_review_cannot_approve_before_validation_ready(tmp_path):
    con=init_db(tmp_path/"too-early.sqlite3")
    _setup(con)
    p=_approve_and_complete(con)
    with pytest.raises(ValueError,match="not ready"):
        architecture_review(con,p["architecture_plan_id"],"APPROVE_REINTEGRATION",
                            "chief","too early")
    con.close()

def test_single_effective_other_remediation_cannot_bypass_architecture_gate(tmp_path):
    con=init_db(tmp_path/"single.sqlite3")
    old=_setup(con)
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?)""",
      (199,10,10,"OTHER","single fix","eng",_now(),"EFFECTIVE"))
    con.commit()
    # Add enough normal scoped evidence. Without architecture plan it still must not pass.
    for i in range(12):
        add_scope_evidence(con,1,500+i,"SAFE",human_confirmed=(i<8),
                           alternative_quality_delta=0,
                           observed_at=(old+timedelta(minutes=1+i)).isoformat())
    ev=evaluate_scope_gate(con,1,persist=False,
                           now=old+timedelta(hours=31))
    assert ev["remediation_effective"] is False
    assert ev["architecture_gate"]["required"] is True
    assert ev["status"]=="WARMING"
    con.close()

def test_approved_architecture_plan_allows_normal_scoped_gate_and_canary_path(tmp_path):
    con=init_db(tmp_path/"canary.sqlite3")
    old=_setup(con)
    p=_approve_and_complete(con)
    _validation(con,p["architecture_plan_id"])
    evaluate_plan(con,p["architecture_plan_id"])
    architecture_review(con,p["architecture_plan_id"],"APPROVE_REINTEGRATION",
                        "chief","approved")
    # RESTRICTED + penalty1 => normal scoped gate requires 10/7/7.
    for i in range(12):
        add_scope_evidence(con,1,600+i,"SAFE",human_confirmed=(i<8),
                           alternative_quality_delta=0,
                           observed_at=(old+timedelta(minutes=1+i)).isoformat())
    ev=evaluate_scope_gate(con,1,persist=True,now=old+timedelta(hours=31))
    assert ev["status"]=="READY_FOR_HUMAN_CANARY_REVIEW"
    assert ev["architecture_gate"]["accepted"] is True
    review_for_canary(con,1,ev["reintegration_evaluation_id"],
                      "APPROVE_CANARY","human","architecture gate passed")
    c=start_canary(con,1,ev["reintegration_evaluation_id"],"human",3)
    assert c["status"]=="ACTIVE"
    con.close()

def test_architecture_status_persists_plan_and_steps(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    _setup(con)
    p=create_plan(con,1,"architect","repeat")
    st=status(con)
    assert st["policy_version"]=="v0.73"
    assert st["plans"][0]["architecture_plan_id"]==p["architecture_plan_id"]
    assert len(st["plans"][0]["steps"])>=2
    con.close()
