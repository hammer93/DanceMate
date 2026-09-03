import pytest

from src.database import init_db
from src.origin_threshold_recommendation_versioning import register_version,versions
from src.origin_threshold_recommendation_challenge import create_challenge
from src.origin_threshold_recommendation_policy import _ensure_state,observe_runtime_verdict
from src.origin_threshold_recommendation_supersede_guard import execute_fallback,evaluate_fallback
from src.origin_threshold_recommendation_fallback_verification import observe as verify_observe
from src.origin_threshold_recommendation_fallback_family import (
    family_root_id,family_signature,profiles,automatic_fallback_allowed,
    review,status
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
    con.execute("""INSERT OR REPLACE INTO origin_threshold_recommendation_algorithm_version_profiles(
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

def _base_family(con):
    v1=register_version(con,ROOT,"alg-v1","eng",code_ref="v1",config_ref="v1",status="SUPERSEDED")
    v2=register_version(con,ROOT,"alg-v2","eng",parent_algorithm_version_id=v1["algorithm_version_id"],
                        code_ref="v2",config_ref="v2",status="SUPERSEDED")
    _profile(con,v2["algorithm_version_id"])
    _ensure_state(con,ROOT)
    return v1,v2

def _candidate(con,label,parent_id,status="PROMOTED"):
    return register_version(con,ROOT,label,"eng",parent_algorithm_version_id=parent_id,
                            code_ref=label,config_ref=label,status=status)

def _challenge(con,scope):
    return create_challenge(con,scope,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])

def _promote_only(con,vid):
    con.execute("""UPDATE origin_threshold_recommendation_algorithm_versions
                   SET status='PROMOTED' WHERE algorithm_version_id=?""",(vid,))
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
                   SET mode='PROMOTED' WHERE root_cause_type=?""",(ROOT,))
    con.commit()

def _supersede_only(con,vid):
    con.execute("""UPDATE origin_threshold_recommendation_algorithm_versions
                   SET status='SUPERSEDED' WHERE algorithm_version_id=?""",(vid,))
    con.commit()

def test_family_root_walks_ancestor_chain(tmp_path):
    con=init_db(tmp_path/"root.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    assert family_root_id(con,v3["algorithm_version_id"])==v1["algorithm_version_id"]
    con.close()

def test_family_signature_uses_root_and_fallback_target(tmp_path):
    con=init_db(tmp_path/"sig.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    assert family_signature(con,v3["algorithm_version_id"],v2["algorithm_version_id"])==f"{v1['algorithm_version_id']}=>{v2['algorithm_version_id']}"
    con.close()

def test_first_distinct_candidate_fallback_keeps_family_closed(tmp_path):
    con=init_db(tmp_path/"first.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    _promote_only(con,v3["algorithm_version_id"])
    r=execute_fallback(con,ROOT,_challenge(con,1)["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert r["executed"] is True
    p=profiles(con)[0]
    assert p["executed_fallback_count"]==1
    assert p["distinct_failing_version_count"]==1
    assert p["circuit_state"]=="CLOSED"
    con.close()

def test_second_distinct_candidate_fallback_opens_family_circuit(tmp_path):
    con=init_db(tmp_path/"second.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    _promote_only(con,v3["algorithm_version_id"])
    execute_fallback(con,ROOT,_challenge(con,1)["challenge_id"],"RECOMMENDATION_HARMFUL")
    _supersede_only(con,v2["algorithm_version_id"])
    v4=_candidate(con,"alg-v4",v2["algorithm_version_id"])
    _promote_only(con,v4["algorithm_version_id"])
    r=execute_fallback(con,ROOT,_challenge(con,2)["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert r["executed"] is True
    p=profiles(con)[0]
    assert p["executed_fallback_count"]==2
    assert p["distinct_failing_version_count"]==2
    assert p["circuit_state"]=="OPEN"
    assert p["architecture_review_required"]==1
    con.close()

def test_third_distinct_candidate_to_same_target_is_blocked(tmp_path):
    con=init_db(tmp_path/"third.sqlite3")
    v1,v2=_base_family(con)
    for idx,label in enumerate(("alg-v3","alg-v4"),1):
        cand=_candidate(con,label,v2["algorithm_version_id"])
        _promote_only(con,cand["algorithm_version_id"])
        execute_fallback(con,ROOT,_challenge(con,idx)["challenge_id"],"RECOMMENDATION_HARMFUL")
        _supersede_only(con,v2["algorithm_version_id"])
    v5=_candidate(con,"alg-v5",v2["algorithm_version_id"])
    _promote_only(con,v5["algorithm_version_id"])
    ev=evaluate_fallback(con,ROOT,_challenge(con,9)["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert ev["architecture_review_required"] is True
    assert any("family circuit breaker" in r for r in ev["reasons"])
    con.close()

def test_family_circuit_forces_long_term_shadow_only(tmp_path):
    con=init_db(tmp_path/"force.sqlite3")
    v1,v2=_base_family(con)
    for idx,label in enumerate(("alg-v3","alg-v4"),1):
        cand=_candidate(con,label,v2["algorithm_version_id"])
        _promote_only(con,cand["algorithm_version_id"])
        execute_fallback(con,ROOT,_challenge(con,idx)["challenge_id"],"RECOMMENDATION_HARMFUL")
        _supersede_only(con,v2["algorithm_version_id"])
    v5=_candidate(con,"alg-v5",v2["algorithm_version_id"])
    _promote_only(con,v5["algorithm_version_id"])
    st=observe_runtime_verdict(con,_challenge(con,10)["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert st["mode"]=="LONG_TERM_SHADOW_ONLY"
    assert st["architecture_review_required"] is True
    con.close()

def test_failed_fallback_verification_opens_family_circuit_immediately(tmp_path):
    con=init_db(tmp_path/"failed.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    _promote_only(con,v3["algorithm_version_id"])
    execute_fallback(con,ROOT,_challenge(con,1)["challenge_id"],"RECOMMENDATION_HARMFUL")
    c=_challenge(con,2)
    r=verify_observe(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert r["status"]=="FAILED"
    p=profiles(con)[0]
    assert p["failed_verification_count"]==1
    assert p["circuit_state"]=="OPEN"
    con.close()

def test_stable_fallback_verification_is_remembered(tmp_path):
    con=init_db(tmp_path/"stable.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    _promote_only(con,v3["algorithm_version_id"])
    execute_fallback(con,ROOT,_challenge(con,1)["challenge_id"],"RECOMMENDATION_HARMFUL")
    for i in range(5):
        c=_challenge(con,20+i)
        verify_observe(con,ROOT,c["challenge_id"],
                       "RECOMMENDATION_HELPFUL" if i<4 else "RUNTIME_SUCCESS_SHADOW_MIXED")
    p=profiles(con)[0]
    assert p["stable_verification_count"]==1
    assert p["failed_verification_count"]==0
    con.close()

def test_watch_fallback_verification_is_remembered(tmp_path):
    con=init_db(tmp_path/"watch.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    _promote_only(con,v3["algorithm_version_id"])
    execute_fallback(con,ROOT,_challenge(con,1)["challenge_id"],"RECOMMENDATION_HARMFUL")
    for i in range(5):
        c=_challenge(con,30+i)
        verify_observe(con,ROOT,c["challenge_id"],
                       "RECOMMENDATION_HELPFUL" if i<3 else "RUNTIME_SUCCESS_SHADOW_MIXED")
    p=profiles(con)[0]
    assert p["watch_verification_count"]==1
    con.close()

def test_different_fallback_target_has_separate_family_circuit(tmp_path):
    con=init_db(tmp_path/"target.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    assert automatic_fallback_allowed(con,ROOT,v3["algorithm_version_id"],v2["algorithm_version_id"])["allowed"] is True
    # A different target is a different family signature.
    assert automatic_fallback_allowed(con,ROOT,v3["algorithm_version_id"],v1["algorithm_version_id"])["allowed"] is True
    assert len(profiles(con))==2
    con.close()

def test_family_circuit_is_root_cause_isolated(tmp_path):
    con=init_db(tmp_path/"rootcause.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    p=automatic_fallback_allowed(con,ROOT,v3["algorithm_version_id"],v2["algorithm_version_id"])["profile"]
    assert p["root_cause_type"]==ROOT
    con.close()

def test_family_human_architecture_review_is_audited(tmp_path):
    con=init_db(tmp_path/"review.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    p=automatic_fallback_allowed(con,ROOT,v3["algorithm_version_id"],v2["algorithm_version_id"])["profile"]
    r=review(con,p["fallback_family_profile_id"],"ACKNOWLEDGE_ARCHITECTURE_REVIEW",
             "chief","family circuit investigation opened")
    assert r["decision"]=="ACKNOWLEDGE_ARCHITECTURE_REVIEW"
    assert r["reviewer"]=="chief"
    con.close()

def test_family_review_does_not_close_circuit(tmp_path):
    con=init_db(tmp_path/"noclose.sqlite3")
    v1,v2=_base_family(con)
    # Manually create two family fallback rows to open the circuit.
    for idx in (3,4):
        c=_candidate(con,f"alg-v{idx}",v2["algorithm_version_id"])
        con.execute("""INSERT INTO origin_threshold_recommendation_version_fallbacks(
          root_cause_type,failing_algorithm_version_id,fallback_algorithm_version_id,
          trigger_challenge_id,guard_evaluation_id,action,status,reason,executed_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (ROOT,c["algorithm_version_id"],v2["algorithm_version_id"],idx,idx,
           "FALLBACK_TO_SUPERSEDED_VERSION","EXECUTED","test",
           "2026-09-02T00:00:00+00:00"))
    con.commit()
    p=automatic_fallback_allowed(con,ROOT,c["algorithm_version_id"],v2["algorithm_version_id"])["profile"]
    assert p["circuit_state"]=="OPEN"
    review(con,p["fallback_family_profile_id"],"ACKNOWLEDGE_ARCHITECTURE_REVIEW",
           "chief","ack only")
    p2=profiles(con)[0]
    assert p2["circuit_state"]=="OPEN"
    con.close()

def test_family_circuit_profile_persists_reason(tmp_path):
    con=init_db(tmp_path/"reason.sqlite3")
    v1,v2=_base_family(con)
    for idx in (3,4):
        c=_candidate(con,f"alg-v{idx}",v2["algorithm_version_id"])
        con.execute("""INSERT INTO origin_threshold_recommendation_version_fallbacks(
          root_cause_type,failing_algorithm_version_id,fallback_algorithm_version_id,
          trigger_challenge_id,guard_evaluation_id,action,status,reason,executed_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (ROOT,c["algorithm_version_id"],v2["algorithm_version_id"],idx,idx,
           "FALLBACK_TO_SUPERSEDED_VERSION","EXECUTED","test",
           "2026-09-02T00:00:00+00:00"))
    con.commit()
    chk=automatic_fallback_allowed(con,ROOT,c["algorithm_version_id"],v2["algorithm_version_id"])
    assert chk["allowed"] is False
    assert any("family automatic fallback count" in r for r in chk["profile"]["reasons"])
    con.close()

def test_status_exposes_family_profiles_reviews_and_events(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    v1,v2=_base_family(con)
    v3=_candidate(con,"alg-v3",v2["algorithm_version_id"])
    p=automatic_fallback_allowed(con,ROOT,v3["algorithm_version_id"],v2["algorithm_version_id"])["profile"]
    review(con,p["fallback_family_profile_id"],"HOLD","chief","collect more evidence")
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["profiles"])==1
    assert len(s["reviews"])==1
    assert len(s["events"])==1
    con.close()
