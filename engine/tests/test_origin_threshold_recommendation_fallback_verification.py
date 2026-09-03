import pytest

from src.database import init_db
from src.origin_threshold_recommendation_versioning import register_version,versions
from src.origin_threshold_recommendation_challenge import create_challenge
from src.origin_threshold_recommendation_policy import _ensure_state,observe_runtime_verdict
from src.origin_threshold_recommendation_supersede_guard import execute_fallback,evaluate_fallback
from src.origin_threshold_recommendation_fallback_verification import (
    pair_signature,automatic_fallback_allowed,generations,observations,
    pair_profiles,observe,status
)

ROOT="SOURCE_LOCAL_RECURRENCE"
CTX="SOURCE|SRC-A|FACEBOOK|RULE|*|ALT0"

def _rec():
    return {
        "selected_steps":["DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"],
        "source":"CONTEXT_COMPARATIVE_RANKING","comparative_score":.8,
        "context_signature":CTX
    }

def _profile(con,vid):
    con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_version_profiles(
      algorithm_version_id,root_cause_type,context_signature,total_runtime_count,
      decisive_runtime_count,canary_runtime_count,production_runtime_count,
      helpful_count,harmful_count,neutral_count,rollback_count,helpful_rate,
      harmful_rate,median_survival_days,confidence_band,safety_band,
      promotion_memory_status,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (vid,ROOT,CTX,5,5,0,5,4,0,1,0,.8,0.0,60.0,
       "ESTABLISHED","SAFE","VERSION_PRODUCTION_PROVEN",'[]',
       "2026-09-02T00:00:00+00:00"))
    con.commit()

def _setup_and_fallback(con):
    old=register_version(con,ROOT,"alg-v1","eng",code_ref="v1",config_ref="v1",status="SUPERSEDED")
    new=register_version(con,ROOT,"alg-v2","eng",parent_algorithm_version_id=old["algorithm_version_id"],
                         code_ref="v2",config_ref="v2",status="PROMOTED")
    _profile(con,old["algorithm_version_id"])
    _ensure_state(con,ROOT)
    con.execute("UPDATE origin_threshold_recommendation_policy_states SET mode='PROMOTED' WHERE root_cause_type=?",(ROOT,))
    con.commit()
    c=create_challenge(con,1,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    r=execute_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    return old,new,c,r

def _fallback_challenge(con,scope):
    return create_challenge(con,scope,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])

def test_pair_signature_is_directional():
    assert pair_signature(2,1)=="2->1"
    assert pair_signature(1,2)=="1->2"

def test_fallback_opens_bounded_verification_generation(tmp_path):
    con=init_db(tmp_path/"open.sqlite3")
    old,new,c,r=_setup_and_fallback(con)
    gs=generations(con,ROOT)
    assert len(gs)==1
    assert gs[0]["status"]=="ACTIVE"
    assert gs[0]["max_observations"]==5
    assert r["fallback_verification_generation_id"]==gs[0]["fallback_verification_generation_id"]
    con.close()

def test_first_pair_execution_blocks_same_pair_auto_fallback_reuse(tmp_path):
    con=init_db(tmp_path/"pair.sqlite3")
    old,new,c,r=_setup_and_fallback(con)
    chk=automatic_fallback_allowed(con,new["algorithm_version_id"],old["algorithm_version_id"])
    assert chk["allowed"] is False
    assert pair_profiles(con)[0]["anti_ping_pong_blocked"]==1
    con.close()

def test_helpful_fallback_runtime_is_counted(tmp_path):
    con=init_db(tmp_path/"help.sqlite3")
    _setup_and_fallback(con)
    c=_fallback_challenge(con,2)
    r=observe(con,ROOT,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    assert r["handled"] is True
    assert r["status"]=="ACTIVE"
    assert r["generation"]["helpful_count"]==1
    con.close()

def test_neutral_fallback_runtime_is_counted(tmp_path):
    con=init_db(tmp_path/"neutral.sqlite3")
    _setup_and_fallback(con)
    c=_fallback_challenge(con,2)
    r=observe(con,ROOT,c["challenge_id"],"RUNTIME_SUCCESS_SHADOW_MIXED")
    assert r["generation"]["neutral_count"]==1
    con.close()

def test_five_observations_four_helpful_marks_stable(tmp_path):
    con=init_db(tmp_path/"stable.sqlite3")
    _setup_and_fallback(con)
    last=None
    for i in range(5):
        c=_fallback_challenge(con,10+i)
        verdict="RECOMMENDATION_HELPFUL" if i<4 else "RUNTIME_SUCCESS_SHADOW_MIXED"
        last=observe(con,ROOT,c["challenge_id"],verdict)
    assert last["status"]=="STABLE"
    assert last["generation"]["status"]=="STABLE"
    assert pair_profiles(con)[0]["stable_verification_count"]==1
    con.close()

def test_five_observations_below_four_helpful_marks_watch(tmp_path):
    con=init_db(tmp_path/"watch.sqlite3")
    _setup_and_fallback(con)
    last=None
    for i in range(5):
        c=_fallback_challenge(con,20+i)
        verdict="RECOMMENDATION_HELPFUL" if i<3 else "RUNTIME_SUCCESS_SHADOW_MIXED"
        last=observe(con,ROOT,c["challenge_id"],verdict)
    assert last["status"]=="WATCH"
    assert last["force_baseline"] is False
    con.close()

def test_any_harmful_fallback_runtime_fails_generation(tmp_path):
    con=init_db(tmp_path/"fail.sqlite3")
    _setup_and_fallback(con)
    c=_fallback_challenge(con,2)
    r=observe(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert r["status"]=="FAILED"
    assert r["force_baseline"] is True
    assert pair_profiles(con)[0]["failed_verification_count"]==1
    con.close()

def test_observe_runtime_verdict_harmful_fallback_forces_baseline_rollback(tmp_path):
    con=init_db(tmp_path/"policy-fail.sqlite3")
    _setup_and_fallback(con)
    c=_fallback_challenge(con,2)
    st=observe_runtime_verdict(con,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert st["mode"] in ("ROLLED_BACK","LONG_TERM_SHADOW_ONLY")
    assert st["fallback_verification"]["status"]=="FAILED"
    vs={v["version_label"]:v for v in versions(con,ROOT)}
    assert vs["alg-v1"]["status"]=="FAILED"
    con.close()

def test_observe_runtime_verdict_helpful_keeps_promoted_fallback(tmp_path):
    con=init_db(tmp_path/"policy-help.sqlite3")
    _setup_and_fallback(con)
    c=_fallback_challenge(con,2)
    st=observe_runtime_verdict(con,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    assert st["mode"]=="PROMOTED"
    assert st["fallback_verification"]["status"]=="ACTIVE"
    con.close()

def test_duplicate_challenge_observation_is_idempotent(tmp_path):
    con=init_db(tmp_path/"dup.sqlite3")
    _setup_and_fallback(con)
    c=_fallback_challenge(con,2)
    a=observe(con,ROOT,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    b=observe(con,ROOT,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    assert b["duplicate"] is True
    assert len(observations(con,a["generation"]["fallback_verification_generation_id"]))==1
    con.close()

def test_challenge_from_other_algorithm_is_not_used_for_fallback_verification(tmp_path):
    con=init_db(tmp_path/"other.sqlite3")
    old,new,c,r=_setup_and_fallback(con)
    # Temporarily create a distinct promoted version so the challenge lineage differs.
    register_version(con,ROOT,"alg-v3","eng",code_ref="v3",config_ref="v3",status="PROMOTED")
    c3=_fallback_challenge(con,3)
    x=observe(con,ROOT,c3["challenge_id"],"RECOMMENDATION_HELPFUL")
    assert x["handled"] is False
    con.close()

def test_same_pair_second_fallback_is_blocked_before_execution(tmp_path):
    con=init_db(tmp_path/"pingpong.sqlite3")
    old,new,c,r=_setup_and_fallback(con)
    # Restore statuses to simulate attempted recurrence of the exact same pair.
    con.execute("UPDATE origin_threshold_recommendation_algorithm_versions SET status='SUPERSEDED' WHERE algorithm_version_id=?",(old["algorithm_version_id"],))
    con.execute("UPDATE origin_threshold_recommendation_algorithm_versions SET status='PROMOTED' WHERE algorithm_version_id=?",(new["algorithm_version_id"],))
    con.commit()
    c2=create_challenge(con,3,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    ev=evaluate_fallback(con,ROOT,c2["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert any("anti-ping-pong" in r for r in ev["reasons"])
    con.close()

def test_pair_direction_change_is_separate_but_not_blindly_reused(tmp_path):
    con=init_db(tmp_path/"direction.sqlite3")
    old,new,c,r=_setup_and_fallback(con)
    assert automatic_fallback_allowed(con,old["algorithm_version_id"],new["algorithm_version_id"])["allowed"] is True
    assert automatic_fallback_allowed(con,new["algorithm_version_id"],old["algorithm_version_id"])["allowed"] is False
    con.close()

def test_status_exposes_generation_observation_pair_profile_and_events(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    _setup_and_fallback(con)
    c=_fallback_challenge(con,2)
    observe(con,ROOT,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["generations"])==1
    assert len(s["observations"])==1
    assert len(s["pair_profiles"])==1
    assert len(s["events"])>=1
    con.close()
