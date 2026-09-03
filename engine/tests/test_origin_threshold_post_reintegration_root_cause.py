from datetime import datetime, timezone, timedelta

from src.database import init_db
from src.origin_threshold_post_reintegration_guard import (
    record_observation,clear_reisolation
)
from src.origin_threshold_post_reintegration_root_cause import (
    root_causes,remediation_routes,review_root_cause,
    latest_route_for_scope,validate_remediation_for_scope,status
)
from src.origin_threshold_scope_reintegration import add_evidence,evaluate_gate

def _now():
    return datetime.now(timezone.utc).isoformat()

def _setup(con,scope_type="SOURCE",source="SRC-BAD",platform=None,rule=None):
    now=_now()
    if source:
        con.execute("""INSERT OR REPLACE INTO sources(
          source_id,platform,source_role,name,status,authority_level,access_state)
          VALUES(?,?,?,?,?,?,?)""",
          (source,platform or "FACEBOOK","SECONDARY",source,"ACTIVE","SECONDARY","OPEN"))
    con.execute("""INSERT INTO origin_threshold_recurrence_profiles(
      recurrence_profile_id,signature,root_cause_type,dominant_source_id,
      dominant_platform,recurrence_count,post_requalification_recurrence_count,
      failed_effective_remediation_count,risk_band,long_term_restricted,
      reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,"TEST-SIG","SOURCE_CONCENTRATION",source,platform,3,2,1,
       "BASELINE",1,'[]',now))
    con.execute("""INSERT INTO origin_threshold_long_term_restrictions(
      restriction_id,recurrence_profile_id,signature,status,trigger_recovery_case_id,
      trigger_reason,recurrence_count,failed_effective_remediation_count,
      requires_human_exception,started_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (1,1,"TEST-SIG","ACTIVE",10,"repeat",3,1,1,now))
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
      (10,10,10,"FALSE_POSITIVE","SOURCE_CONCENTRATION","BASELINE",source,platform,
       1.0,.2,3,'{}','[]',now))
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      remediation_ref,notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (10,10,10,"SOURCE_RULE_CHANGE","R-10","initial fix","human",now,"EFFECTIVE"))
    con.execute("""INSERT INTO origin_threshold_restriction_scopes(
      scope_id,restriction_id,scope_type,source_id,platform,rule_key,status,
      production_action,shadow_learning_enabled,reason,created_at,released_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,1,scope_type,source,platform,rule,"RELEASED",
       "BASE_ONLY_SHADOW_RESTRICTED",1,"released",now,now))
    con.execute("""INSERT INTO origin_threshold_scope_reintegration_evaluations(
      reintegration_evaluation_id,scope_id,shadow_count,decisive_human_count,
      safe_human_count,distinct_event_count,false_corroboration_count,
      missed_syndication_count,avg_alternative_quality_delta,elapsed_hours,
      remediation_effective,recurrence_risk_band,required_shadow_count,
      required_human_count,required_distinct_events,status,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,1,7,5,5,5,0,0,0,30,1,"BASELINE",7,5,5,
       "READY_FOR_HUMAN_CANARY_REVIEW",'[]',now))
    con.execute("""INSERT INTO origin_threshold_scope_reintegration_canaries(
      canary_id,scope_id,reintegration_evaluation_id,status,max_assignments,
      assigned_count,safe_count,unsafe_count,hold_count,approved_by,started_at,completed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,1,1,"FULL_REINTEGRATED",3,3,3,0,0,"human",now,now))
    con.commit()

def _trigger(con,**kw):
    defaults=dict(
        scope_id=1,event_instance_id=101,human_outcome="UNSAFE",
        critical=True,reintegrated_correct=False,base_correct=True,
        alternative_correct=True)
    defaults.update(kw)
    return record_observation(con,**defaults)

def test_false_corroboration_attributes_independence_graph_error(tmp_path):
    con=init_db(tmp_path/"ind.sqlite3"); _setup(con)
    _trigger(con,false_corroboration=True)
    rc=root_causes(con)[-1]
    assert rc["root_cause_type"]=="INDEPENDENCE_GRAPH_ERROR"
    assert remediation_routes(con)[-1]["required_remediation_type"]=="INDEPENDENCE_GRAPH_FIX"
    con.close()

def test_missed_syndication_on_source_attributes_source_local_recurrence(tmp_path):
    con=init_db(tmp_path/"src.sqlite3"); _setup(con)
    _trigger(con,missed_syndication=True)
    assert root_causes(con)[-1]["root_cause_type"]=="SOURCE_LOCAL_RECURRENCE"
    assert remediation_routes(con)[-1]["required_remediation_type"]=="SOURCE_RULE_CHANGE"
    con.close()

def test_global_scope_attributes_threshold_recurrence(tmp_path):
    con=init_db(tmp_path/"global.sqlite3"); _setup(con,"GLOBAL_THRESHOLD",None,None,None)
    _trigger(con)
    assert root_causes(con)[-1]["root_cause_type"]=="THRESHOLD_RECURRENCE"
    assert remediation_routes(con)[-1]["required_remediation_type"]=="THRESHOLD_CHANGE"
    con.close()

def test_platform_scope_attributes_platform_pattern_shift(tmp_path):
    con=init_db(tmp_path/"platform.sqlite3"); _setup(con,"PLATFORM",None,"FACEBOOK",None)
    _trigger(con)
    assert root_causes(con)[-1]["root_cause_type"]=="PLATFORM_PATTERN_SHIFT"
    assert remediation_routes(con)[-1]["required_remediation_type"]=="SOURCE_RULE_CHANGE"
    con.close()

def test_alternative_route_degradation_has_data_quality_route(tmp_path):
    con=init_db(tmp_path/"alt.sqlite3"); _setup(con)
    _trigger(con,critical=True,coverage_quality_delta=-.25,
             alternative_correct=True,base_correct=False)
    assert root_causes(con)[-1]["root_cause_type"]=="ALTERNATIVE_ROUTE_DEGRADATION"
    assert remediation_routes(con)[-1]["required_remediation_type"]=="DATA_QUALITY_FIX"
    con.close()

def test_all_paths_wrong_attributes_collector_evidence_drift(tmp_path):
    con=init_db(tmp_path/"collector.sqlite3"); _setup(con,"RULE",None,None,"R")
    _trigger(con,reintegrated_correct=False,base_correct=False,alternative_correct=False)
    assert root_causes(con)[-1]["root_cause_type"]=="COLLECTOR_EVIDENCE_QUALITY_DRIFT"
    assert remediation_routes(con)[-1]["required_remediation_type"]=="COLLECTOR_FIX"
    con.close()

def test_root_cause_attribution_is_idempotent(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3"); _setup(con)
    r=_trigger(con)
    rid=r["guard"]["reisolation"]["reisolation_id"]
    from src.origin_threshold_post_reintegration_root_cause import attribute_root_cause
    a=attribute_root_cause(con,rid); b=attribute_root_cause(con,rid)
    assert a["post_root_cause_id"]==b["post_root_cause_id"]
    assert len(root_causes(con,rid))==1
    con.close()

def test_human_root_review_is_auditable(tmp_path):
    con=init_db(tmp_path/"review.sqlite3"); _setup(con)
    _trigger(con)
    rc=root_causes(con)[-1]
    r=review_root_cause(con,rc["post_root_cause_id"],"CONFIRM","김프로","evidence matches")
    assert r["decision"]=="CONFIRM"
    row=con.execute("SELECT * FROM origin_threshold_post_reintegration_root_reviews").fetchone()
    assert row["reviewer"]=="김프로"
    con.close()

def test_matching_fresh_remediation_is_accepted_for_gate(tmp_path):
    con=init_db(tmp_path/"match.sqlite3"); _setup(con)
    r=_trigger(con,missed_syndication=True)
    reactivated=r["guard"]["reisolation"]["reactivated_at"]
    submitted=(datetime.fromisoformat(reactivated)+timedelta(seconds=1)).isoformat()
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      remediation_ref,notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (11,10,10,"SOURCE_RULE_CHANGE","R-11","fresh route fix","human",submitted,"EFFECTIVE"))
    con.commit()
    ev=evaluate_gate(con,1,persist=False,now=datetime.fromisoformat(submitted)+timedelta(hours=30))
    assert ev["remediation_effective"] is True
    assert ev["remediation_route_check"]["accepted"] is True
    con.close()

def test_wrong_fresh_remediation_type_is_rejected_for_gate(tmp_path):
    con=init_db(tmp_path/"wrong.sqlite3"); _setup(con)
    r=_trigger(con,false_corroboration=True)
    reactivated=r["guard"]["reisolation"]["reactivated_at"]
    submitted=(datetime.fromisoformat(reactivated)+timedelta(seconds=1)).isoformat()
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      remediation_ref,notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (11,10,10,"SOURCE_RULE_CHANGE","R-11","wrong fix","human",submitted,"EFFECTIVE"))
    con.commit()
    ev=evaluate_gate(con,1,persist=False,now=datetime.fromisoformat(submitted)+timedelta(hours=30))
    assert ev["remediation_effective"] is False
    assert ev["remediation_route_check"]["accepted"] is False
    assert "INDEPENDENCE_GRAPH_FIX" in ev["remediation_route_check"]["reason"]
    con.close()

def test_validation_persists_remediation_attempt_audit(tmp_path):
    con=init_db(tmp_path/"attempt.sqlite3"); _setup(con)
    _trigger(con,false_corroboration=True)
    route=latest_route_for_scope(con,1)
    row={"remediation_id":99,"remediation_type":"INDEPENDENCE_GRAPH_FIX"}
    result=validate_remediation_for_scope(con,1,row)
    assert result["accepted"] is True
    a=con.execute("SELECT * FROM origin_threshold_post_reintegration_remediation_attempts").fetchone()
    assert a["remediation_route_id"]==route["remediation_route_id"]
    assert a["accepted_for_gate"]==1
    con.close()

def test_repeat_same_root_cause_after_effective_remediation_escalates(tmp_path):
    con=init_db(tmp_path/"escalate.sqlite3"); _setup(con)
    first=_trigger(con,missed_syndication=True)
    rid=first["guard"]["reisolation"]["reisolation_id"]
    clear_reisolation(con,rid,"human","synthetic next release")
    con.execute("UPDATE origin_threshold_restriction_scopes SET status='RELEASED',released_at=? WHERE scope_id=1",(_now(),))
    con.commit()
    second=_trigger(con,event_instance_id=102,missed_syndication=True)
    rc=root_causes(con)[-1]
    route=remediation_routes(con)[-1]
    assert rc["secondary_root_cause_type"]=="REMEDIATION_INEFFECTIVE_RECURRENCE"
    assert route["architecture_review_required"]==1
    assert route["required_remediation_type"]=="OTHER"
    assert "SOURCE_RULE_CHANGE" in route["blocked_remediation_types"]
    con.close()

def test_escalated_route_rejects_repeating_same_remediation_type(tmp_path):
    con=init_db(tmp_path/"block-repeat.sqlite3"); _setup(con)
    first=_trigger(con,missed_syndication=True)
    clear_reisolation(con,first["guard"]["reisolation"]["reisolation_id"],"human","again")
    con.execute("UPDATE origin_threshold_restriction_scopes SET status='RELEASED',released_at=? WHERE scope_id=1",(_now(),)); con.commit()
    _trigger(con,event_instance_id=103,missed_syndication=True)
    result=validate_remediation_for_scope(con,1,{"remediation_id":100,"remediation_type":"SOURCE_RULE_CHANGE"})
    assert result["accepted"] is False
    assert "SOURCE_RULE_CHANGE" in result["route"]["blocked_remediation_types"]
    con.close()

def test_status_exposes_root_causes_and_routes(tmp_path):
    con=init_db(tmp_path/"status.sqlite3"); _setup(con)
    _trigger(con,false_corroboration=True)
    st=status(con)
    assert st["policy_version"]=="v0.73"
    assert len(st["root_causes"])==1
    assert len(st["routes"])==1
    con.close()

def test_reisolation_result_contains_attribution_and_route(tmp_path):
    con=init_db(tmp_path/"embedded.sqlite3"); _setup(con)
    r=_trigger(con,false_corroboration=True)
    ri=r["guard"]["reisolation"]
    assert ri["post_reintegration_root_cause"]["root_cause_type"]=="INDEPENDENCE_GRAPH_ERROR"
    assert ri["post_reintegration_root_cause"]["remediation_route"]["required_remediation_type"]=="INDEPENDENCE_GRAPH_FIX"
    con.close()
