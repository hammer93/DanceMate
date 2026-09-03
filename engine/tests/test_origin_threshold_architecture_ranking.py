from datetime import datetime, timezone, timedelta
import json

from src.database import init_db
from src.origin_threshold_architecture_ranking import (
    context_signature,capture_runtime_context,comparative_scores,
    recommend_contextual_plan,score_history,recommendation_history,status
)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _scope(con,scope_id=1,scope_type="SOURCE",source="SRC-A",platform="FACEBOOK",
           rule="VERIFIED_EVENT_EXISTENCE",secondary=None,alt=False):
    con.execute("""INSERT INTO origin_threshold_restriction_scopes(
      scope_id,restriction_id,scope_type,source_id,platform,rule_key,status,
      production_action,shadow_learning_enabled,reason,created_at,released_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (scope_id,scope_id,scope_type,source,platform,rule,"RELEASED",
       "BASE_ONLY_SHADOW_RESTRICTED",1,"test",_now(),_now()))
    con.execute("""INSERT INTO origin_threshold_scope_reisolations(
      reisolation_id,scope_id,canary_id,status,reason,failure_count,
      requirement_penalty_level,reactivated_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (scope_id,scope_id,scope_id,"CLEARED","test",1,1,_now()))
    con.execute("""INSERT INTO origin_threshold_post_reintegration_root_causes(
      post_root_cause_id,reisolation_id,scope_id,canary_id,root_cause_type,
      secondary_root_cause_type,severity,evidence_json,reasons_json,attributed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (scope_id,scope_id,scope_id,scope_id,"SOURCE_LOCAL_RECURRENCE",
       secondary,"HIGH",'{}','[]',_now()))
    if alt:
        con.execute("""INSERT INTO origin_threshold_scope_route_evaluations(
          event_instance_id,rule_key,trigger_source_id,candidate_source_ids_json,
          blocked_source_ids_json,safe_source_ids_json,selected_source_ids_json,
          route_status,production_recommendation,coverage_preserved,reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (900+scope_id,rule,source,'[]','[]','["X","Y"]','["X","Y"]',
           "SAFE_ALTERNATIVE_AVAILABLE","RECOMPUTE_ROUTE_WITH_SAFE_SOURCES",1,'[]',_now()))
    con.commit()

def _runtime(con,idx,signature,status,root="SOURCE_LOCAL_RECURRENCE",
             days=None,scope_id=None,scope_type="SOURCE",source="SRC-A",
             platform="FACEBOOK",rule="VERIFIED_EVENT_EXISTENCE",
             secondary=None,alt=False,steps=2):
    scope_id=scope_id or (100+idx)
    release=(datetime.now(timezone.utc)-timedelta(days=90+idx)).isoformat()
    con.execute("""INSERT INTO origin_threshold_architecture_plan_runtime_outcomes(
      architecture_plan_id,scope_id,canary_id,root_cause_type,plan_signature,status,
      released_at,observation_count,healthy_observation_count,regression_observation_count,
      days_to_reisolation,finalized_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1000+idx,scope_id,2000+idx,root,signature,status,release,20,
       20 if status=="SUSTAINED_SUCCESS" else 15,
       0 if status=="SUSTAINED_SUCCESS" else 2,days,_now()))
    rid=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.execute("""INSERT INTO origin_threshold_architecture_runtime_contexts(
      architecture_runtime_outcome_id,scope_type,source_id,platform,rule_key,
      secondary_root_cause_type,alternative_route_available,plan_step_count,
      context_json,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (rid,scope_type,source,platform,rule,secondary,int(bool(alt)),steps,
       json.dumps({"scope_type":scope_type},ensure_ascii=False),_now()))
    con.commit()
    return rid

def _target(**kw):
    d=dict(scope_type="SOURCE",source_id="SRC-A",platform="FACEBOOK",
           rule_key="VERIFIED_EVENT_EXISTENCE",
           secondary_root_cause_type=None,alternative_route_available=False)
    d.update(kw); return d

def test_context_signature_is_stable_and_explicit():
    assert context_signature(_target())=="SOURCE|SRC-A|FACEBOOK|VERIFIED_EVENT_EXISTENCE|*|ALT0"
    assert context_signature(_target(alternative_route_available=True)).endswith("ALT1")

def test_capture_runtime_context_uses_scope_and_alternative_state(tmp_path):
    con=init_db(tmp_path/"capture.sqlite3")
    _scope(con,1,alt=True)
    con.execute("""INSERT INTO origin_threshold_architecture_plan_runtime_outcomes(
      architecture_plan_id,scope_id,canary_id,root_cause_type,plan_signature,status,released_at)
      VALUES(?,?,?,?,?,?,?)""",(1,1,1,"SOURCE_LOCAL_RECURRENCE","A+B","ACTIVE",_now()))
    con.commit()
    rid=con.execute("SELECT architecture_runtime_outcome_id FROM origin_threshold_architecture_plan_runtime_outcomes").fetchone()["architecture_runtime_outcome_id"]
    c=capture_runtime_context(con,rid,1,3)
    assert c["scope_type"]=="SOURCE"
    assert c["source_id"]=="SRC-A"
    assert c["alternative_route_available"]==1
    assert c["plan_step_count"]==3
    con.close()

def test_small_perfect_sample_has_low_confidence(tmp_path):
    con=init_db(tmp_path/"small.sqlite3")
    for i in range(2):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS")
    s=comparative_scores(con,"SOURCE_LOCAL_RECURRENCE",_target(),persist=False)[0]
    assert s["decisive_count"]==2
    assert s["confidence_band"]=="LOW_DATA"
    assert s["wilson_lower_bound"]<0.5
    con.close()

def test_five_perfect_samples_have_stronger_wilson_evidence(tmp_path):
    con=init_db(tmp_path/"wilson.sqlite3")
    for i in range(5):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS")
    s=comparative_scores(con,"SOURCE_LOCAL_RECURRENCE",_target(),persist=False)[0]
    assert s["wilson_lower_bound"]>0.5
    assert s["confidence_band"]=="ESTABLISHED"
    con.close()

def test_exact_context_scores_higher_than_source_mismatch(tmp_path):
    con=init_db(tmp_path/"context.sqlite3")
    for i in range(3):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS",source="SRC-A")
    for i in range(3,6):
        _runtime(con,i,"C+D","SUSTAINED_SUCCESS",source="SRC-Z")
    scores={s["plan_signature"]:s for s in comparative_scores(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),persist=False)}
    assert scores["A+B"]["context_similarity"]>scores["C+D"]["context_similarity"]
    assert scores["A+B"]["comparative_score"]>scores["C+D"]["comparative_score"]
    con.close()

def test_platform_context_mismatch_is_penalized(tmp_path):
    con=init_db(tmp_path/"platform.sqlite3")
    for i in range(3):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS",platform="FACEBOOK")
    for i in range(3,6):
        _runtime(con,i,"C+D","SUSTAINED_SUCCESS",platform="NAVER_BLOG")
    scores={s["plan_signature"]:s for s in comparative_scores(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),persist=False)}
    assert scores["A+B"]["context_similarity"]>scores["C+D"]["context_similarity"]
    con.close()

def test_quick_recurrence_failure_has_severity_penalty(tmp_path):
    con=init_db(tmp_path/"severity.sqlite3")
    _runtime(con,1,"A+B","SUSTAINED_SUCCESS")
    _runtime(con,2,"A+B","SUSTAINED_SUCCESS")
    _runtime(con,3,"A+B","RECURRENCE_FAILED",days=3)
    s=comparative_scores(con,"SOURCE_LOCAL_RECURRENCE",_target(),persist=False)[0]
    assert s["recurrence_severity_penalty"]==1.0
    assert s["recurrence_failure_count"]==1
    con.close()

def test_longer_survival_improves_comparative_score(tmp_path):
    con=init_db(tmp_path/"survival.sqlite3")
    for i,d in enumerate((5,7,9),1):
        _runtime(con,i,"SHORT+A","RECURRENCE_FAILED",days=d)
    for i,d in enumerate((60,70,80),10):
        _runtime(con,i,"LONG+B","RECURRENCE_FAILED",days=d)
    scores={s["plan_signature"]:s for s in comparative_scores(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),persist=False)}
    assert scores["LONG+B"]["median_survival_days"]>scores["SHORT+A"]["median_survival_days"]
    assert scores["LONG+B"]["comparative_score"]>scores["SHORT+A"]["comparative_score"]
    con.close()

def test_extra_plan_complexity_is_penalized(tmp_path):
    con=init_db(tmp_path/"complexity.sqlite3")
    for i in range(3):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS",steps=2)
    for i in range(3,6):
        _runtime(con,i,"A+B+C","SUSTAINED_SUCCESS",steps=3)
    scores={s["plan_signature"]:s for s in comparative_scores(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),persist=False)}
    assert scores["A+B+C"]["complexity_penalty"]>scores["A+B"]["complexity_penalty"]
    assert scores["A+B"]["comparative_score"]>scores["A+B+C"]["comparative_score"]
    con.close()

def test_tiny_100_percent_plan_does_not_beat_robust_plan(tmp_path):
    con=init_db(tmp_path/"tiny.sqlite3")
    for i in range(2):
        _runtime(con,i,"TINY+A","SUSTAINED_SUCCESS")
    for i in range(2,7):
        _runtime(con,i,"ROBUST+B","SUSTAINED_SUCCESS")
    r=recommend_contextual_plan(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),
        ["COLLECTOR_FIX","DATA_QUALITY_FIX"],[],persist=False)
    assert r["source"]=="CONTEXT_COMPARATIVE_RANKING"
    assert set(r["selected_steps"])=={"ROBUST","B"}
    con.close()

def test_close_top_scores_use_conservative_tie_fallback(tmp_path):
    con=init_db(tmp_path/"tie.sqlite3")
    for i in range(5):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS")
    for i in range(5,10):
        _runtime(con,i,"C+D","SUSTAINED_SUCCESS")
    r=recommend_contextual_plan(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),
        ["COLLECTOR_FIX","DATA_QUALITY_FIX"],[],persist=False)
    assert r["source"]=="CONSERVATIVE_TIE_FALLBACK"
    assert r["selected_steps"][:2]==["COLLECTOR_FIX","DATA_QUALITY_FIX"]
    con.close()

def test_blocked_type_disqualifies_historical_plan(tmp_path):
    con=init_db(tmp_path/"blocked.sqlite3")
    for i in range(5):
        _runtime(con,i,"DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX","SUSTAINED_SUCCESS")
    r=recommend_contextual_plan(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),
        ["COLLECTOR_FIX","THRESHOLD_CHANGE"],["DATA_QUALITY_FIX"],persist=False)
    assert r["source"]=="DETERMINISTIC_FALLBACK"
    assert "DATA_QUALITY_FIX" not in r["selected_steps"]
    con.close()

def test_root_cause_memories_are_not_cross_ranked(tmp_path):
    con=init_db(tmp_path/"root.sqlite3")
    for i in range(5):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS",root="THRESHOLD_RECURRENCE")
    for i in range(5,10):
        _runtime(con,i,"C+D","SUSTAINED_SUCCESS",root="SOURCE_LOCAL_RECURRENCE")
    scores=comparative_scores(con,"SOURCE_LOCAL_RECURRENCE",_target(),persist=False)
    assert {s["plan_signature"] for s in scores}=={"C+D"}
    con.close()

def test_score_and_recommendation_history_persist(tmp_path):
    con=init_db(tmp_path/"history.sqlite3")
    for i in range(5):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS")
    recommend_contextual_plan(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),
        ["COLLECTOR_FIX","DATA_QUALITY_FIX"],[],persist=True)
    assert len(score_history(con,"SOURCE_LOCAL_RECURRENCE"))==1
    assert len(recommendation_history(con,"SOURCE_LOCAL_RECURRENCE"))==1
    con.close()

def test_status_exposes_scores_and_context_recommendations(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    for i in range(5):
        _runtime(con,i,"A+B","SUSTAINED_SUCCESS")
    recommend_contextual_plan(
        con,"SOURCE_LOCAL_RECURRENCE",_target(),
        ["COLLECTOR_FIX","DATA_QUALITY_FIX"],[],persist=True)
    st=status(con)
    assert st["policy_version"]=="v0.73"
    assert len(st["scores"])==1
    assert len(st["recommendations"])==1
    con.close()
