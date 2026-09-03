from datetime import datetime, timezone, timedelta
import pytest

from src.database import init_db
from src.origin_threshold_architecture_memory import (
    plan_signature,register_release,runtime_outcomes,observe_runtime,
    maybe_mark_sustained,mark_reisolation_failure,effectiveness_profiles,
    recommend_plan,recommendations,status,_refresh_profile
)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _setup_plan(con,plan_id=1,scope_id=1,canary_id=1,
                root="SOURCE_LOCAL_RECURRENCE",
                steps=("INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX"),
                released_at=None,status="APPROVED_FOR_REINTEGRATION"):
    released_at=released_at or _now()
    con.execute("""INSERT INTO origin_threshold_restriction_scopes(
      scope_id,restriction_id,scope_type,source_id,status,production_action,
      shadow_learning_enabled,reason,created_at,released_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (scope_id,scope_id,"SOURCE",f"SRC-{scope_id}","RELEASED",
       "BASE_ONLY_SHADOW_RESTRICTED",1,"released",released_at,released_at))
    con.execute("""INSERT INTO origin_threshold_post_reintegration_root_causes(
      post_root_cause_id,reisolation_id,scope_id,canary_id,root_cause_type,
      severity,evidence_json,reasons_json,attributed_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (plan_id,plan_id,scope_id,canary_id,root,"HIGH",'{}','[]',released_at))
    con.execute("""INSERT INTO origin_threshold_post_reintegration_remediation_routes(
      remediation_route_id,post_root_cause_id,reisolation_id,required_remediation_type,
      blocked_remediation_types_json,escalation_level,architecture_review_required,reason,created_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (plan_id,plan_id,plan_id,"OTHER",'[]',2,1,"architecture",released_at))
    con.execute("""INSERT INTO origin_threshold_architecture_remediation_plans(
      architecture_plan_id,scope_id,reisolation_id,remediation_route_id,status,
      required_step_count,created_by,rationale,created_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (plan_id,scope_id,plan_id,plan_id,status,len(steps),"architect","memory test",released_at))
    for i,step in enumerate(steps,1):
        con.execute("""INSERT INTO origin_threshold_architecture_remediation_steps(
          architecture_plan_id,step_order,remediation_type,required,status)
          VALUES(?,?,?,?,?)""",(plan_id,i,step,1,"EFFECTIVE"))
    con.execute("""INSERT INTO origin_threshold_scope_reintegration_canaries(
      canary_id,scope_id,reintegration_evaluation_id,status,max_assignments,
      assigned_count,safe_count,unsafe_count,hold_count,approved_by,
      started_at,completed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (canary_id,scope_id,plan_id,"FULL_REINTEGRATED",3,3,3,0,0,
       "human",released_at,released_at))
    con.commit()
    return register_release(con,scope_id,canary_id,released_at)

def _insert_runtime(con,idx,root,signature,outcome,days=None):
    release=(datetime.now(timezone.utc)-timedelta(days=40+idx)).isoformat()
    con.execute("""INSERT INTO origin_threshold_architecture_plan_runtime_outcomes(
      architecture_plan_id,scope_id,canary_id,root_cause_type,plan_signature,status,
      released_at,observation_count,healthy_observation_count,regression_observation_count,
      days_to_reisolation,finalized_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (100+idx,100+idx,100+idx,root,signature,outcome,release,
       20,20 if outcome=="SUSTAINED_SUCCESS" else 18,
       0 if outcome=="SUSTAINED_SUCCESS" else 2,days,_now()))
    con.commit()

def test_plan_signature_is_order_independent_sorted_unique(tmp_path):
    con=init_db(tmp_path/"sig.sqlite3")
    _setup_plan(con,steps=("DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX"))
    assert plan_signature(con,1)=="DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX"
    con.close()

def test_release_registers_active_runtime_outcome(tmp_path):
    con=init_db(tmp_path/"release.sqlite3")
    r=_setup_plan(con)
    assert r["status"]=="ACTIVE"
    assert r["root_cause_type"]=="SOURCE_LOCAL_RECURRENCE"
    assert r["plan_signature"]=="DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX"
    con.close()

def test_release_registration_is_idempotent(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3")
    first=_setup_plan(con)
    second=register_release(con,1,1,first["released_at"])
    assert first["architecture_runtime_outcome_id"]==second["architecture_runtime_outcome_id"]
    assert len(runtime_outcomes(con,1))==1
    con.close()

def test_healthy_runtime_observation_accumulates_memory(tmp_path):
    con=init_db(tmp_path/"obs.sqlite3")
    _setup_plan(con)
    r=observe_runtime(con,1,1,is_regression=False)
    assert r["observation_count"]==1
    assert r["healthy_observation_count"]==1
    assert r["regression_observation_count"]==0
    con.close()

def test_regression_runtime_observation_is_counted(tmp_path):
    con=init_db(tmp_path/"reg.sqlite3")
    _setup_plan(con)
    r=observe_runtime(con,1,1,is_regression=True)
    assert r["observation_count"]==1
    assert r["regression_observation_count"]==1
    con.close()

def test_20_observations_before_30_days_do_not_mark_sustained(tmp_path):
    con=init_db(tmp_path/"early.sqlite3")
    release=(datetime.now(timezone.utc)-timedelta(days=10)).isoformat()
    r=_setup_plan(con,released_at=release)
    con.execute("""UPDATE origin_threshold_architecture_plan_runtime_outcomes
                   SET observation_count=20,healthy_observation_count=20
                   WHERE architecture_runtime_outcome_id=?""",(r["architecture_runtime_outcome_id"],))
    con.commit()
    x=maybe_mark_sustained(con,r["architecture_runtime_outcome_id"])
    assert x["status"]=="ACTIVE"
    con.close()

def test_20_healthy_observations_after_30_days_mark_sustained(tmp_path):
    con=init_db(tmp_path/"sustained.sqlite3")
    release=(datetime.now(timezone.utc)-timedelta(days=31)).isoformat()
    r=_setup_plan(con,released_at=release)
    con.execute("""UPDATE origin_threshold_architecture_plan_runtime_outcomes
                   SET observation_count=20,healthy_observation_count=20,regression_observation_count=0
                   WHERE architecture_runtime_outcome_id=?""",(r["architecture_runtime_outcome_id"],))
    con.commit()
    x=maybe_mark_sustained(con,r["architecture_runtime_outcome_id"])
    assert x["status"]=="SUSTAINED_SUCCESS"
    prof=effectiveness_profiles(con,"SOURCE_LOCAL_RECURRENCE")[0]
    assert prof["sustained_success_count"]==1
    con.close()

def test_any_regression_prevents_sustained_success(tmp_path):
    con=init_db(tmp_path/"no-sustain.sqlite3")
    release=(datetime.now(timezone.utc)-timedelta(days=31)).isoformat()
    r=_setup_plan(con,released_at=release)
    con.execute("""UPDATE origin_threshold_architecture_plan_runtime_outcomes
                   SET observation_count=20,healthy_observation_count=19,regression_observation_count=1
                   WHERE architecture_runtime_outcome_id=?""",(r["architecture_runtime_outcome_id"],))
    con.commit()
    assert maybe_mark_sustained(con,r["architecture_runtime_outcome_id"])["status"]=="ACTIVE"
    con.close()

def test_reisolation_marks_runtime_recurrence_failed_and_days(tmp_path):
    con=init_db(tmp_path/"fail.sqlite3")
    release=(datetime.now(timezone.utc)-timedelta(days=12)).isoformat()
    _setup_plan(con,released_at=release)
    fail=mark_reisolation_failure(con,1,1,77)
    assert fail["status"]=="RECURRENCE_FAILED"
    assert fail["reisolation_id"]==77
    assert fail["days_to_reisolation"]>=11.9
    prof=effectiveness_profiles(con,"SOURCE_LOCAL_RECURRENCE")[0]
    assert prof["recurrence_failure_count"]==1
    con.close()

def test_profile_is_low_data_with_fewer_than_three_attempts(tmp_path):
    con=init_db(tmp_path/"low.sqlite3")
    sig="DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX"
    _insert_runtime(con,1,"SOURCE_LOCAL_RECURRENCE",sig,"SUSTAINED_SUCCESS")
    _insert_runtime(con,2,"SOURCE_LOCAL_RECURRENCE",sig,"SUSTAINED_SUCCESS")
    _refresh_profile(con,"SOURCE_LOCAL_RECURRENCE",sig)
    p=effectiveness_profiles(con,"SOURCE_LOCAL_RECURRENCE")[0]
    assert p["confidence_band"]=="LOW_DATA"
    assert p["attempt_count"]==2
    con.close()

def test_low_data_recommendation_keeps_deterministic_fallback(tmp_path):
    con=init_db(tmp_path/"fallback.sqlite3")
    sig="DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX"
    _insert_runtime(con,1,"SOURCE_LOCAL_RECURRENCE",sig,"SUSTAINED_SUCCESS")
    _insert_runtime(con,2,"SOURCE_LOCAL_RECURRENCE",sig,"SUSTAINED_SUCCESS")
    _refresh_profile(con,"SOURCE_LOCAL_RECURRENCE",sig)
    r=recommend_plan(
        con,"SOURCE_LOCAL_RECURRENCE",
        ["COLLECTOR_FIX","DATA_QUALITY_FIX"],[],persist=True)
    assert r["source"]=="DETERMINISTIC_FALLBACK"
    assert r["confidence_band"]=="LOW_DATA"
    assert r["recommended_steps"][:2]==["COLLECTOR_FIX","DATA_QUALITY_FIX"]
    con.close()

def test_three_sustained_attempts_enable_evidence_memory_recommendation(tmp_path):
    con=init_db(tmp_path/"memory.sqlite3")
    sig="DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX"
    for i in range(1,4):
        _insert_runtime(con,i,"SOURCE_LOCAL_RECURRENCE",sig,"SUSTAINED_SUCCESS")
    _refresh_profile(con,"SOURCE_LOCAL_RECURRENCE",sig)
    r=recommend_plan(
        con,"SOURCE_LOCAL_RECURRENCE",
        ["COLLECTOR_FIX","THRESHOLD_CHANGE"],[],persist=True)
    assert r["source"]=="EFFECTIVENESS_MEMORY"
    assert set(r["recommended_steps"])=={"DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"}
    assert r["evidence_attempt_count"]==3
    con.close()

def test_any_recurrence_failure_disqualifies_memory_recommendation(tmp_path):
    con=init_db(tmp_path/"failed-memory.sqlite3")
    sig="DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX"
    _insert_runtime(con,1,"SOURCE_LOCAL_RECURRENCE",sig,"SUSTAINED_SUCCESS")
    _insert_runtime(con,2,"SOURCE_LOCAL_RECURRENCE",sig,"SUSTAINED_SUCCESS")
    _insert_runtime(con,3,"SOURCE_LOCAL_RECURRENCE",sig,"RECURRENCE_FAILED",days=12)
    _refresh_profile(con,"SOURCE_LOCAL_RECURRENCE",sig)
    r=recommend_plan(
        con,"SOURCE_LOCAL_RECURRENCE",
        ["COLLECTOR_FIX","THRESHOLD_CHANGE"],[],persist=True)
    assert r["source"]=="DETERMINISTIC_FALLBACK"
    con.close()

def test_blocked_type_is_removed_from_memory_recommendation(tmp_path):
    con=init_db(tmp_path/"blocked.sqlite3")
    sig="DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX"
    for i in range(1,4):
        _insert_runtime(con,i,"SOURCE_LOCAL_RECURRENCE",sig,"SUSTAINED_SUCCESS")
    _refresh_profile(con,"SOURCE_LOCAL_RECURRENCE",sig)
    r=recommend_plan(
        con,"SOURCE_LOCAL_RECURRENCE",
        ["COLLECTOR_FIX","THRESHOLD_CHANGE"],["DATA_QUALITY_FIX"],persist=True)
    # Memory signature becomes too narrow after block, so fail back to safe deterministic path.
    assert r["source"]=="DETERMINISTIC_FALLBACK"
    assert "DATA_QUALITY_FIX" not in r["recommended_steps"]
    assert len(r["recommended_steps"])>=2
    con.close()

def test_status_exposes_runtime_profiles_and_recommendations(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    _setup_plan(con)
    recommend_plan(
        con,"SOURCE_LOCAL_RECURRENCE",
        ["COLLECTOR_FIX","DATA_QUALITY_FIX"],[],persist=True)
    st=status(con)
    assert st["policy_version"]=="v0.73"
    assert len(st["runtime_outcomes"])==1
    assert len(st["effectiveness_profiles"])==1
    assert len(st["recommendations"])==1
    con.close()
