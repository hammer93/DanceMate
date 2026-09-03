import pytest
from datetime import datetime, timezone

from src.database import init_db,create_preventive_quarantine
from src.origin_threshold_scope_isolation import (
    derive_scope_for_restriction,scopes,source_production_allowed,
    evaluate_safe_alternative_path,override_scope,release_scope,scope_status
)
from src.origin_threshold_recurrence_guard import grant_restriction_exception
from src.origin_threshold_promotion import create_candidate_from_latest_calibration
from src.source_reliability import evaluate_verification_policy
from src.source_independence_graph import register_relationship

RULE="VERIFIED_EVENT_EXISTENCE"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _source(con,sid,platform="FACEBOOK"):
    con.execute("""INSERT OR REPLACE INTO sources(
      source_id,platform,source_role,name,status,authority_level,access_state)
      VALUES(?,?,?,?,?,?,?)""",
      (sid,platform,"SECONDARY",sid,"ACTIVE","SECONDARY","OPEN"))
    con.commit()

def _restriction(con,*,rid=1,pid=1,signature="SOURCE_CONCENTRATION|SRC-BAD|*",
                 root_type="SOURCE_CONCENTRATION",source="SRC-BAD",
                 platform="FACEBOOK"):
    con.execute("""INSERT INTO origin_threshold_recurrence_profiles(
      recurrence_profile_id,signature,root_cause_type,dominant_source_id,
      dominant_platform,recurrence_count,post_requalification_recurrence_count,
      failed_effective_remediation_count,risk_band,long_term_restricted,
      reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (pid,signature,root_type,source,platform,3,2,2,"RESTRICTED",1,'[]',_now()))
    con.execute("""INSERT INTO origin_threshold_long_term_restrictions(
      restriction_id,recurrence_profile_id,signature,status,trigger_recovery_case_id,
      trigger_reason,recurrence_count,failed_effective_remediation_count,
      requires_human_exception,started_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (rid,pid,signature,"ACTIVE",99,"repeat",3,2,1,_now()))
    con.commit()
    return derive_scope_for_restriction(con,rid)

def _decision(con,key,event,sid,platform="FACEBOOK",human=False):
    _source(con,sid,platform)
    return evaluate_verification_policy(
        con,decision_key=key,event_instance_id=event,source_id=sid,rule_key=RULE,
        base_eligible=True,independent_source_count=1,human_confirmed=human,
        existing_verified=False)

def _calibration(con,cal_id=1):
    con.execute("""INSERT INTO origin_inference_calibrations(
      calibration_id,policy_version,reviewed_cluster_count,
      confirmed_syndication_count,confirmed_independent_count,hold_count,
      precision,false_positive_rate,baseline_text_threshold,
      shadow_recommended_text_threshold,threshold_delta,
      recommendation_status,reasons_json,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cal_id,"v0.73",0,0,0,0,None,None,.86,.89,.03,
       "SHADOW_TIGHTEN",'["scope test"]',_now()))
    con.commit()

def test_source_concentration_auto_derives_source_scope(tmp_path):
    con=init_db(tmp_path/"source.sqlite3")
    s=_restriction(con)
    assert s["scope_type"]=="SOURCE"
    assert s["source_id"]=="SRC-BAD"
    assert s["production_action"]=="BASE_ONLY_SHADOW_RESTRICTED"
    assert s["shadow_learning_enabled"]==1
    con.close()

def test_threshold_boundary_remains_global_scope(tmp_path):
    con=init_db(tmp_path/"global.sqlite3")
    s=_restriction(
        con,signature="THRESHOLD_BOUNDARY|*|*",root_type="THRESHOLD_BOUNDARY",
        source=None,platform=None)
    assert s["scope_type"]=="GLOBAL_THRESHOLD"
    assert s["production_action"]=="GLOBAL_PROMOTION_RESTRICTED"
    con.close()

def test_scoped_source_is_blocked_from_production_but_shadow_remains(tmp_path):
    con=init_db(tmp_path/"policy.sqlite3")
    _source(con,"SRC-BAD")
    _restriction(con)
    p=source_production_allowed(con,"SRC-BAD",RULE)
    assert p["allowed"] is False
    assert p["production_action"]=="BASE_ONLY_SHADOW_RESTRICTED"
    assert p["matched_scope_ids"]
    good=source_production_allowed(con,"SRC-GOOD",RULE)
    assert good["allowed"] is True
    con.close()

def test_safe_alternative_path_excludes_restricted_source(tmp_path):
    con=init_db(tmp_path/"safe-path.sqlite3")
    for sid,platform in [("SRC-BAD","FACEBOOK"),("SRC-A","NAVER_BLOG"),("SRC-B","DAUM_CAFE")]:
        _source(con,sid,platform)
    _restriction(con)
    r=evaluate_safe_alternative_path(
        con,event_instance_id=10,rule_key=RULE,trigger_source_id="SRC-Q",
        candidate_source_ids=["SRC-BAD","SRC-A","SRC-B"],
        selected_source_ids=["SRC-A","SRC-B"])
    assert r["blocked_source_ids"]==["SRC-BAD"]
    assert set(r["safe_source_ids"])=={"SRC-A","SRC-B"}
    assert r["route_status"]=="SAFE_ALTERNATIVE_SELECTED"
    assert r["coverage_preserved"] is True
    con.close()

def test_single_safe_source_degrades_to_possible(tmp_path):
    con=init_db(tmp_path/"degraded.sqlite3")
    _source(con,"SRC-BAD","FACEBOOK"); _source(con,"SRC-A","NAVER_BLOG")
    _restriction(con)
    r=evaluate_safe_alternative_path(
        con,event_instance_id=11,rule_key=RULE,trigger_source_id="SRC-Q",
        candidate_source_ids=["SRC-BAD","SRC-A"])
    assert r["route_status"]=="DEGRADED_POSSIBLE"
    assert r["coverage_preserved"] is False
    con.close()

def test_all_restricted_sources_fail_closed(tmp_path):
    con=init_db(tmp_path/"none.sqlite3")
    _source(con,"SRC-BAD","FACEBOOK")
    _restriction(con)
    override_scope(
        con,1,"PLATFORM","human","platform-wide recurrence",platform="FACEBOOK")
    _source(con,"SRC-BAD2","FACEBOOK")
    r=evaluate_safe_alternative_path(
        con,event_instance_id=12,rule_key=RULE,trigger_source_id="SRC-Q",
        candidate_source_ids=["SRC-BAD","SRC-BAD2"])
    assert set(r["blocked_source_ids"])=={"SRC-BAD","SRC-BAD2"}
    assert r["route_status"]=="NO_SAFE_ALTERNATIVE"
    assert r["production_recommendation"]=="UNKNOWN_OR_SHADOW_ONLY"
    con.close()

def test_human_scope_override_supports_rule_scope(tmp_path):
    con=init_db(tmp_path/"rule.sqlite3")
    _source(con,"SRC-X","FACEBOOK")
    _restriction(con)
    s=override_scope(con,1,"RULE","reviewer","failure isolated to one rule",
                     rule_key=RULE)
    assert s["scope_type"]=="RULE"
    assert source_production_allowed(con,"SRC-X",RULE)["allowed"] is False
    assert source_production_allowed(con,"SRC-X","OTHER_RULE")["allowed"] is True
    con.close()

def test_source_rule_scope_is_narrower_than_source_scope(tmp_path):
    con=init_db(tmp_path/"source-rule.sqlite3")
    _source(con,"SRC-BAD","FACEBOOK")
    _restriction(con)
    override_scope(con,1,"SOURCE_RULE","reviewer","only one source/rule pair",
                   source_id="SRC-BAD",rule_key=RULE)
    assert source_production_allowed(con,"SRC-BAD",RULE)["allowed"] is False
    assert source_production_allowed(con,"SRC-BAD","OTHER_RULE")["allowed"] is True
    assert source_production_allowed(con,"SRC-GOOD",RULE)["allowed"] is True
    con.close()

def test_source_scoped_restriction_does_not_globally_block_new_candidate(tmp_path):
    con=init_db(tmp_path/"candidate-scoped.sqlite3")
    _restriction(con)
    _calibration(con)
    c=create_candidate_from_latest_calibration(con)
    assert c["candidate_id"]>0
    assert c["consumed_restriction_exception_ids"]==[]
    # No Human outcomes means Shadow gate is blocked, but Candidate creation itself is allowed.
    assert c["shadow_gate_status"]=="BLOCKED"
    con.close()

def test_global_scope_still_requires_one_time_human_exception(tmp_path):
    con=init_db(tmp_path/"candidate-global.sqlite3")
    _restriction(
        con,signature="THRESHOLD_BOUNDARY|*|*",root_type="THRESHOLD_BOUNDARY",
        source=None,platform=None)
    _calibration(con)
    with pytest.raises(ValueError,match="require explicit Human exception"):
        create_candidate_from_latest_calibration(con)
    ex=grant_restriction_exception(con,1,"APPROVE","human","controlled global retry")
    c=create_candidate_from_latest_calibration(con)
    assert ex["exception_id"] in c["consumed_restriction_exception_ids"]
    con.close()

def test_direct_restricted_source_uses_safe_alternative_verified_route(tmp_path):
    con=init_db(tmp_path/"direct-route.sqlite3")
    _restriction(con)
    _decision(con,"a",101,"SRC-A","NAVER_BLOG")
    _decision(con,"b",101,"SRC-B","DAUM_CAFE")
    register_relationship(
        con,source_id_a="SRC-A",source_id_b="SRC-B",
        relationship_type="INDEPENDENT",reviewed_by="human",reason="independent origins")
    _source(con,"SRC-BAD","FACEBOOK")
    q=evaluate_verification_policy(
        con,decision_key="bad-direct",event_instance_id=101,source_id="SRC-BAD",
        rule_key=RULE,base_eligible=True,independent_source_count=1,
        human_confirmed=False,existing_verified=False)
    assert q["production_mode"]=="SCOPE_ISOLATED_ALTERNATIVE_ROUTE"
    assert q["production_action"]=="ALLOW_VERIFIED_VIA_ALTERNATIVE_ROUTE"
    assert q["alternative_route"]["route_status"]=="ROUTED_VERIFIED"
    assert set(q["alternative_route"]["selected_source_ids"])=={"SRC-A","SRC-B"}
    con.close()

def test_restricted_alternative_is_not_double_counted(tmp_path):
    con=init_db(tmp_path/"alt-filter.sqlite3")
    _restriction(con)
    _source(con,"SRC-Q","FACEBOOK")
    create_preventive_quarantine(
        con,source_id="SRC-Q",rule_key=RULE,trigger_recovery_case_id=1,
        trigger_reason="test",metadata={})
    _decision(con,"bad",102,"SRC-BAD","FACEBOOK")
    _decision(con,"a",102,"SRC-A","NAVER_BLOG")
    _decision(con,"b",102,"SRC-B","DAUM_CAFE")
    register_relationship(
        con,source_id_a="SRC-A",source_id_b="SRC-B",
        relationship_type="INDEPENDENT",reviewed_by="human",reason="independent")
    q=evaluate_verification_policy(
        con,decision_key="q",event_instance_id=102,source_id="SRC-Q",
        rule_key=RULE,base_eligible=True,independent_source_count=1,
        human_confirmed=False,existing_verified=False)
    route=q["alternative_route"]
    assert "SRC-BAD" not in route["candidate_source_ids"]
    assert "SRC-BAD" in route["scope_blocked_source_ids"]
    assert route["route_status"]=="ROUTED_VERIFIED"
    con.close()

def test_existing_verified_is_never_retroactively_removed_by_scope(tmp_path):
    con=init_db(tmp_path/"existing.sqlite3")
    _restriction(con)
    _source(con,"SRC-BAD")
    q=evaluate_verification_policy(
        con,decision_key="existing",event_instance_id=103,source_id="SRC-BAD",
        rule_key=RULE,base_eligible=True,independent_source_count=1,
        human_confirmed=False,existing_verified=True)
    assert q["production_mode"]=="NO_RETROACTIVE_CHANGE"
    assert q["production_action"]=="KEEP_EXISTING_VERIFIED"
    con.close()

def test_scope_release_restores_source_production_eligibility(tmp_path):
    con=init_db(tmp_path/"release.sqlite3")
    _source(con,"SRC-BAD")
    s=_restriction(con)
    assert source_production_allowed(con,"SRC-BAD",RULE)["allowed"] is False
    release_scope(con,s["scope_id"],"human","source-specific issue fixed")
    assert source_production_allowed(con,"SRC-BAD",RULE)["allowed"] is True
    con.close()

def test_scope_status_separates_global_and_scoped_restrictions(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    _restriction(con,rid=1,pid=1)
    _restriction(
        con,rid=2,pid=2,signature="THRESHOLD_BOUNDARY|*|*",
        root_type="THRESHOLD_BOUNDARY",source=None,platform=None)
    s=scope_status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["scoped_restrictions"])==1
    assert len(s["global_restrictions"])==1
    con.close()
