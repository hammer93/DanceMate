from datetime import datetime, timezone, timedelta
import pytest

from src.database import init_db
from src.origin_threshold_post_reintegration_guard import (
    record_observation,evaluate_guard,observations,evaluations,re_isolations,
    requirement_penalty,clear_reisolation,status
)
from src.origin_threshold_scope_isolation import source_production_allowed
from src.origin_threshold_scope_reintegration import add_evidence,evaluate_gate

RULE="VERIFIED_EVENT_EXISTENCE"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _setup_released(con,risk="BASELINE"):
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
      (1,"SOURCE_CONCENTRATION|SRC-BAD|*","SOURCE_CONCENTRATION","SRC-BAD",
       "FACEBOOK",3,2,1,risk,1,'[]',now))
    con.execute("""INSERT INTO origin_threshold_long_term_restrictions(
      restriction_id,recurrence_profile_id,signature,status,trigger_recovery_case_id,
      trigger_reason,recurrence_count,failed_effective_remediation_count,
      requires_human_exception,started_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (1,1,"SOURCE_CONCENTRATION|SRC-BAD|*","ACTIVE",10,
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
      (10,10,10,"FALSE_POSITIVE","SOURCE_CONCENTRATION",risk,"SRC-BAD","FACEBOOK",
       1.0,.2,3,'{}','[]',now))
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      remediation_ref,notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (10,10,10,"SOURCE_RULE_CHANGE","R-10","fix","human",now,"EFFECTIVE"))
    con.execute("""INSERT INTO origin_threshold_restriction_scopes(
      scope_id,restriction_id,scope_type,source_id,platform,rule_key,status,
      production_action,shadow_learning_enabled,reason,created_at,released_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,1,"SOURCE","SRC-BAD",None,None,"RELEASED",
       "BASE_ONLY_SHADOW_RESTRICTED",1,"reintegration complete",now,now))
    con.execute("""INSERT INTO origin_threshold_scope_reintegration_evaluations(
      reintegration_evaluation_id,scope_id,shadow_count,decisive_human_count,
      safe_human_count,distinct_event_count,false_corroboration_count,
      missed_syndication_count,avg_alternative_quality_delta,elapsed_hours,
      remediation_effective,recurrence_risk_band,required_shadow_count,
      required_human_count,required_distinct_events,status,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,1,7,5,5,5,0,0,0.0,30,1,risk,7,5,5,
       "READY_FOR_HUMAN_CANARY_REVIEW",'[]',now))
    con.execute("""INSERT INTO origin_threshold_scope_reintegration_canaries(
      canary_id,scope_id,reintegration_evaluation_id,status,max_assignments,
      assigned_count,safe_count,unsafe_count,hold_count,approved_by,
      started_at,completed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,1,1,"FULL_REINTEGRATED",3,3,3,0,0,"human",now,now))
    con.commit()
    return 1

def _safe(con,eid,**kwargs):
    return record_observation(
        con,1,eid,"SAFE",reintegrated_correct=True,
        base_correct=True,alternative_correct=True,**kwargs)

def test_safe_observation_is_stored_with_three_way_counterfactual(tmp_path):
    con=init_db(tmp_path/"obs.sqlite3")
    _setup_released(con)
    r=record_observation(
        con,1,101,"SAFE",reintegrated_correct=True,
        base_correct=False,alternative_correct=False)
    assert r["observation"]["counterfactual_class"]=="REINTEGRATION_IMPROVEMENT"
    assert len(observations(con,1))==1
    con.close()

def test_reintegrated_wrong_alternative_right_is_regression(tmp_path):
    con=init_db(tmp_path/"cf.sqlite3")
    _setup_released(con)
    r=record_observation(
        con,1,101,"UNSAFE",reintegrated_correct=False,
        base_correct=False,alternative_correct=True)
    assert r["observation"]["counterfactual_class"]=="REINTEGRATION_REGRESSION"
    con.close()

def test_critical_regression_immediately_reisolates_scope(tmp_path):
    con=init_db(tmp_path/"critical.sqlite3")
    _setup_released(con)
    r=record_observation(
        con,1,101,"UNSAFE",critical=True,reintegrated_correct=False,
        base_correct=True,alternative_correct=True)
    assert r["guard"]["overall_status"]=="REISOLATE"
    assert r["guard"]["reisolation"]["status"]=="ACTIVE"
    assert source_production_allowed(con,"SRC-BAD",RULE)["allowed"] is False
    con.close()

def test_false_corroboration_immediately_reisolates(tmp_path):
    con=init_db(tmp_path/"false.sqlite3")
    _setup_released(con)
    r=record_observation(
        con,1,102,"UNSAFE",false_corroboration=True,
        reintegrated_correct=False,base_correct=True,alternative_correct=True)
    assert r["guard"]["overall_status"]=="REISOLATE"
    assert re_isolations(con,1)[0]["status"]=="ACTIVE"
    con.close()

def test_missed_syndication_immediately_reisolates(tmp_path):
    con=init_db(tmp_path/"miss.sqlite3")
    _setup_released(con)
    r=record_observation(
        con,1,103,"UNSAFE",missed_syndication=True,
        reintegrated_correct=False,base_correct=True,alternative_correct=True)
    assert r["guard"]["overall_status"]=="REISOLATE"
    con.close()

def test_single_noncritical_regression_is_watch_at_rolling5(tmp_path):
    con=init_db(tmp_path/"watch.sqlite3")
    _setup_released(con)
    for eid in range(201,205):
        _safe(con,eid)
    r=record_observation(
        con,1,205,"UNSAFE",reintegrated_correct=False,
        base_correct=True,alternative_correct=True)
    assert r["guard"]["overall_status"]=="WATCH"
    assert r["guard"]["windows"][0]["status"]=="WATCH"
    assert source_production_allowed(con,"SRC-BAD",RULE)["allowed"] is True
    con.close()

def test_two_noncritical_regressions_in_rolling5_reisolate(tmp_path):
    con=init_db(tmp_path/"rolling5.sqlite3")
    _setup_released(con)
    _safe(con,301)
    record_observation(con,1,302,"UNSAFE",reintegrated_correct=False,
                       base_correct=True,alternative_correct=True)
    _safe(con,303); _safe(con,304)
    r=record_observation(con,1,305,"UNSAFE",reintegrated_correct=False,
                         base_correct=True,alternative_correct=True)
    assert r["guard"]["overall_status"]=="REISOLATE"
    assert r["guard"]["windows"][0]["regression_count"]==2
    con.close()

def test_two_coverage_regressions_in_rolling5_reisolate(tmp_path):
    con=init_db(tmp_path/"coverage.sqlite3")
    _setup_released(con)
    _safe(con,401,coverage_quality_delta=-.20)
    _safe(con,402); _safe(con,403); _safe(con,404)
    r=_safe(con,405,coverage_quality_delta=-.15)
    assert r["guard"]["overall_status"]=="REISOLATE"
    assert r["guard"]["windows"][0]["coverage_regression_count"]==2
    con.close()

def test_all_safe_first_five_is_still_warming_for_long_windows(tmp_path):
    con=init_db(tmp_path/"warming.sqlite3")
    _setup_released(con)
    r=None
    for eid in range(501,506):
        r=_safe(con,eid)
    assert r["guard"]["windows"][0]["status"]=="HEALTHY"
    assert r["guard"]["overall_status"]=="WARMING"
    con.close()

def test_twenty_safe_observations_are_fully_healthy(tmp_path):
    con=init_db(tmp_path/"healthy.sqlite3")
    _setup_released(con)
    r=None
    for eid in range(601,621):
        r=_safe(con,eid)
    assert r["guard"]["overall_status"]=="HEALTHY"
    assert all(w["status"]=="HEALTHY" for w in r["guard"]["windows"])
    con.close()

def test_reisolation_feeds_recurrence_profile_and_penalty(tmp_path):
    con=init_db(tmp_path/"feedback.sqlite3")
    _setup_released(con)
    before=con.execute("""SELECT recurrence_count,post_requalification_recurrence_count
                          FROM origin_threshold_recurrence_profiles WHERE recurrence_profile_id=1""").fetchone()
    record_observation(
        con,1,701,"UNSAFE",critical=True,reintegrated_correct=False,
        base_correct=True,alternative_correct=True)
    after=con.execute("""SELECT recurrence_count,post_requalification_recurrence_count,risk_band
                         FROM origin_threshold_recurrence_profiles WHERE recurrence_profile_id=1""").fetchone()
    assert after["recurrence_count"]==before["recurrence_count"]+1
    assert after["post_requalification_recurrence_count"]==before["post_requalification_recurrence_count"]+1
    assert after["risk_band"]=="RESTRICTED"
    p=requirement_penalty(con,1)
    assert p=={"level":1,"shadow_bonus":2,"human_bonus":1,"event_bonus":1}
    con.close()

def test_old_reintegration_evidence_is_not_reused_after_reisolation(tmp_path):
    con=init_db(tmp_path/"fresh-evidence.sqlite3")
    _setup_released(con)
    old=datetime.now(timezone.utc)-timedelta(days=2)
    for i in range(8):
        add_evidence(con,1,800+i,"SAFE",human_confirmed=(i<6),
                     alternative_quality_delta=0,observed_at=(old+timedelta(minutes=i)).isoformat())
    record_observation(
        con,1,8010,"UNSAFE",critical=True,reintegrated_correct=False,
        base_correct=True,alternative_correct=True)
    ev=evaluate_gate(con,1,persist=False)
    assert ev["shadow_count"]==0
    assert ev["requirement_penalty_level"]==1
    assert ev["required_shadow_count"]>=10  # RESTRICTED 8 + penalty 2
    con.close()

def test_fresh_effective_remediation_required_after_reisolation(tmp_path):
    con=init_db(tmp_path/"fresh-remediation.sqlite3")
    _setup_released(con)
    record_observation(
        con,1,901,"UNSAFE",critical=True,reintegrated_correct=False,
        base_correct=True,alternative_correct=True)
    start=datetime.now(timezone.utc)+timedelta(seconds=.01)
    # Enough new evidence, but old remediation predates re-isolation.
    for i in range(10):
        add_evidence(con,1,910+i,"SAFE",human_confirmed=(i<7),
                     alternative_quality_delta=0,
                     observed_at=(start+timedelta(hours=30,minutes=i)).isoformat())
    ev=evaluate_gate(con,1,persist=False,now=start+timedelta(hours=31))
    assert ev["remediation_effective"] is False
    assert ev["status"]=="WARMING"
    con.close()

def test_repeated_reisolation_strengthens_next_requirement_again(tmp_path):
    con=init_db(tmp_path/"repeat.sqlite3")
    _setup_released(con)
    r=record_observation(
        con,1,1001,"UNSAFE",critical=True,reintegrated_correct=False,
        base_correct=True,alternative_correct=True)
    rid=r["guard"]["reisolation"]["reisolation_id"]
    clear_reisolation(con,rid,"human","prepare synthetic second release")
    con.execute("""UPDATE origin_threshold_restriction_scopes
                   SET status='RELEASED',released_at=? WHERE scope_id=1""",(_now(),))
    con.commit()
    r2=record_observation(
        con,1,1002,"UNSAFE",critical=True,reintegrated_correct=False,
        base_correct=True,alternative_correct=True)
    assert r2["guard"]["reisolation"]["requirement_penalty_level"]==2
    assert requirement_penalty(con,1)=={
        "level":2,"shadow_bonus":4,"human_bonus":2,"event_bonus":2}
    con.close()

def test_guard_history_and_status_are_persisted(tmp_path):
    con=init_db(tmp_path/"history.sqlite3")
    _setup_released(con)
    for eid in range(1101,1106):
        _safe(con,eid)
    hist=evaluations(con,1)
    assert len(hist)==15  # 5 observations x rolling 5/10/20
    st=status(con)
    assert st["policy_version"]=="v0.73"
    assert len(st["scopes"])==1
    assert st["re_isolations"]==[]
    con.close()
