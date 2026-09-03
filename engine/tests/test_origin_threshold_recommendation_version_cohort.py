import pytest

from src.database import init_db
from src.origin_threshold_recommendation_versioning import register_version,mark_status
from src.origin_threshold_recommendation_challenge import create_challenge
from src.origin_threshold_recommendation_version_cohort import (
    register_runtime,finalize_runtime,cohorts,refresh_profile,profile,profiles,
    evaluate_version,evaluations,status
)

ROOT="SOURCE_LOCAL_RECURRENCE"
CTX="SOURCE|SRC-A|FACEBOOK|RULE|*|ALT0"

def _rec():
    return {
        "selected_steps":["DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"],
        "source":"CONTEXT_COMPARATIVE_RANKING",
        "comparative_score":.82,
        "context_signature":CTX
    }

def _runtime(con,idx,version_status="CANARY",runtime_status="ACTIVE",
             verdict=None,days=None,context=CTX,selected_side="RECOMMENDATION"):
    if not con.execute("SELECT 1 FROM origin_threshold_recommendation_algorithm_versions").fetchone():
        register_version(con,ROOT,"alg-v1","eng",code_ref="code1",config_ref="cfg1",
                         status=version_status)
    else:
        v=con.execute("SELECT algorithm_version_id FROM origin_threshold_recommendation_algorithm_versions ORDER BY algorithm_version_id DESC LIMIT 1").fetchone()
        mark_status(con,v["algorithm_version_id"],version_status,"test","phase")
    c=create_challenge(con,100+idx,ROOT,context,_rec(),
                       ["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    cur=con.execute("""INSERT INTO origin_threshold_architecture_challenge_runtime_results(
      challenge_id,architecture_plan_id,architecture_runtime_outcome_id,human_decision,
      selected_signature,selected_side,runtime_status,counterfactual_verdict,
      days_to_reisolation,finalized_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (c["challenge_id"],1000+idx,2000+idx,"POLICY_SELECTION",
       c["recommended_signature"],selected_side,runtime_status,verdict,days,
       "2026-09-02T00:00:00+00:00" if runtime_status!="ACTIVE" else None))
    con.commit()
    register_runtime(con,cur.lastrowid)
    if runtime_status!="ACTIVE":
        finalize_runtime(con,cur.lastrowid)
    return cur.lastrowid

def test_canary_runtime_is_recorded_in_version_cohort(tmp_path):
    con=init_db(tmp_path/"canary.sqlite3")
    _runtime(con,1,"CANARY")
    r=cohorts(con)[0]
    assert r["runtime_phase"]=="CANARY"
    assert r["runtime_status"]=="ACTIVE"
    con.close()

def test_promoted_runtime_is_recorded_as_production(tmp_path):
    con=init_db(tmp_path/"prod.sqlite3")
    _runtime(con,1,"PROMOTED")
    assert cohorts(con)[0]["runtime_phase"]=="PRODUCTION"
    con.close()

def test_runtime_registration_is_idempotent(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3")
    rr=_runtime(con,1,"CANARY")
    a=register_runtime(con,rr)
    b=register_runtime(con,rr)
    assert a["algorithm_runtime_cohort_id"]==b["algorithm_runtime_cohort_id"]
    assert len(cohorts(con))==1
    con.close()

def test_finalize_helpful_runtime_updates_profile(tmp_path):
    con=init_db(tmp_path/"help.sqlite3")
    _runtime(con,1,"CANARY","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    p=profiles(con)[0]
    assert p["decisive_runtime_count"]==1
    assert p["helpful_count"]==1
    assert p["harmful_count"]==0
    con.close()

def test_finalize_harmful_runtime_marks_unsafe(tmp_path):
    con=init_db(tmp_path/"harm.sqlite3")
    _runtime(con,1,"CANARY","RECURRENCE_FAILED","RECOMMENDATION_HARMFUL",3.0)
    p=profiles(con)[0]
    assert p["harmful_count"]==1
    assert p["safety_band"]=="UNSAFE"
    assert p["promotion_memory_status"]=="VERSION_ROLLBACK_EVIDENCE"
    con.close()

def test_three_canary_two_helpful_are_version_canary_proven(tmp_path):
    con=init_db(tmp_path/"proven.sqlite3")
    _runtime(con,1,"CANARY","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    _runtime(con,2,"CANARY","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    _runtime(con,3,"CANARY","SUSTAINED_SUCCESS","RUNTIME_SUCCESS_SHADOW_MIXED")
    p=profiles(con)[0]
    assert p["canary_runtime_count"]==3
    assert p["helpful_count"]==2
    assert p["promotion_memory_status"]=="VERSION_CANARY_PROVEN"
    assert p["safety_band"]=="SAFE"
    con.close()

def test_two_canary_results_remain_low_data(tmp_path):
    con=init_db(tmp_path/"low.sqlite3")
    _runtime(con,1,"CANARY","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    _runtime(con,2,"CANARY","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    p=profiles(con)[0]
    assert p["confidence_band"]=="LOW_DATA"
    assert p["promotion_memory_status"]=="VERSION_WARMING"
    con.close()

def test_five_production_runs_create_production_proven_memory(tmp_path):
    con=init_db(tmp_path/"prod-proven.sqlite3")
    for i in range(5):
        _runtime(con,i,"PROMOTED","SUSTAINED_SUCCESS",
                 "RECOMMENDATION_HELPFUL" if i<4 else "RUNTIME_SUCCESS_SHADOW_MIXED")
    p=profiles(con)[0]
    assert p["production_runtime_count"]==5
    assert p["helpful_count"]==4
    assert p["promotion_memory_status"]=="VERSION_PRODUCTION_PROVEN"
    assert p["confidence_band"]=="ESTABLISHED"
    con.close()

def test_median_survival_uses_90_day_success_cap_and_failure_days(tmp_path):
    con=init_db(tmp_path/"survival.sqlite3")
    _runtime(con,1,"PROMOTED","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    _runtime(con,2,"PROMOTED","RECURRENCE_FAILED","RUNTIME_FAILURE_INCONCLUSIVE",10.0)
    p=profiles(con)[0]
    assert p["median_survival_days"]==50.0
    assert p["rollback_count"]==1
    con.close()

def test_contexts_are_profiled_separately(tmp_path):
    con=init_db(tmp_path/"ctx.sqlite3")
    _runtime(con,1,"PROMOTED","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL",context=CTX)
    _runtime(con,2,"PROMOTED","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL",
             context="PLATFORM|*|NAVER|RULE|*|ALT1")
    ps=profiles(con)
    assert len(ps)==2
    assert {p["context_signature"] for p in ps}=={CTX,"PLATFORM|*|NAVER|RULE|*|ALT1"}
    con.close()

def test_evaluate_version_ready_after_three_canary_two_helpful(tmp_path):
    con=init_db(tmp_path/"eval-ready.sqlite3")
    for i,v in enumerate(("RECOMMENDATION_HELPFUL","RECOMMENDATION_HELPFUL","RUNTIME_SUCCESS_SHADOW_MIXED")):
        _runtime(con,i,"CANARY","SUSTAINED_SUCCESS",v)
    vid=con.execute("SELECT algorithm_version_id FROM origin_threshold_recommendation_algorithm_versions LIMIT 1").fetchone()["algorithm_version_id"]
    e=evaluate_version(con,vid,CTX,persist=True)
    assert e["status"]=="READY_FOR_VERSION_PROMOTION"
    assert len(evaluations(con,vid))==1
    con.close()

def test_evaluate_version_blocks_on_any_harmful(tmp_path):
    con=init_db(tmp_path/"eval-block.sqlite3")
    _runtime(con,1,"CANARY","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    _runtime(con,2,"CANARY","RECURRENCE_FAILED","RECOMMENDATION_HARMFUL",4.0)
    _runtime(con,3,"CANARY","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    vid=con.execute("SELECT algorithm_version_id FROM origin_threshold_recommendation_algorithm_versions LIMIT 1").fetchone()["algorithm_version_id"]
    e=evaluate_version(con,vid,CTX,persist=False)
    assert e["status"]=="BLOCKED"
    assert e["harmful_count"]==1
    con.close()

def test_version_profiles_are_separate_between_versions(tmp_path):
    con=init_db(tmp_path/"versions.sqlite3")
    _runtime(con,1,"CANARY","SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL")
    v1=con.execute("SELECT algorithm_version_id FROM origin_threshold_recommendation_algorithm_versions LIMIT 1").fetchone()["algorithm_version_id"]
    mark_status(con,v1,"SUPERSEDED","test","next")
    register_version(con,ROOT,"alg-v2","eng",code_ref="code2",config_ref="cfg2",status="CANARY")
    _runtime(con,2,"CANARY","RECURRENCE_FAILED","RECOMMENDATION_HARMFUL",2.0)
    ps=profiles(con)
    assert len(ps)==2
    by={p["algorithm_version_id"]:p for p in ps}
    assert by[v1]["helpful_count"]==1
    assert by[max(by)]["harmful_count"]==1
    con.close()

def test_active_runtime_is_not_decisive(tmp_path):
    con=init_db(tmp_path/"active.sqlite3")
    _runtime(con,1,"CANARY","ACTIVE",None)
    p=profiles(con)[0]
    assert p["total_runtime_count"]==1
    assert p["decisive_runtime_count"]==0
    assert p["confidence_band"]=="LOW_DATA"
    con.close()

def test_status_exposes_cohorts_profiles_and_evaluations(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    for i in range(3):
        _runtime(con,i,"CANARY","SUSTAINED_SUCCESS",
                 "RECOMMENDATION_HELPFUL" if i<2 else "RUNTIME_SUCCESS_SHADOW_MIXED")
    vid=con.execute("SELECT algorithm_version_id FROM origin_threshold_recommendation_algorithm_versions LIMIT 1").fetchone()["algorithm_version_id"]
    evaluate_version(con,vid,CTX,persist=True)
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["cohorts"])==3
    assert len(s["profiles"])==1
    assert len(s["evaluations"])==1
    con.close()
