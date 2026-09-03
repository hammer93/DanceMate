import pytest

from src.database import init_db
from src.origin_threshold_recommendation_versioning import register_version
from src.origin_threshold_recommendation_challenge import create_challenge
from src.origin_threshold_recommendation_policy import _ensure_state
from src.origin_threshold_recommendation_fallback_family import (
    automatic_fallback_allowed,profiles,review as family_review
)
from src.origin_threshold_recommendation_fallback_family_recovery import (
    cases,add_remediation,review_remediation,set_candidate_version,
    add_evidence,evaluate,human_rearm_review,rearm_permission,status as recovery_status
)
from src.origin_threshold_recommendation_supersede_guard import execute_fallback
from src.origin_threshold_recommendation_fallback_verification import observe as verify_observe

ROOT="SOURCE_LOCAL_RECURRENCE"
CTX="SOURCE|SRC-A|FACEBOOK|RULE|*|ALT0"

def _rec():
    return {
        "selected_steps":["DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"],
        "source":"CONTEXT_COMPARATIVE_RANKING","comparative_score":.8,
        "context_signature":CTX
    }

def _safe_profile(con,vid):
    con.execute("""INSERT OR REPLACE INTO origin_threshold_recommendation_algorithm_version_profiles(
      algorithm_version_id,root_cause_type,context_signature,total_runtime_count,
      decisive_runtime_count,canary_runtime_count,production_runtime_count,
      helpful_count,harmful_count,neutral_count,rollback_count,helpful_rate,
      harmful_rate,median_survival_days,confidence_band,safety_band,
      promotion_memory_status,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (vid,ROOT,CTX,5,5,0,5,4,0,1,0,.8,0.0,60.0,
       "ESTABLISHED","SAFE","VERSION_PRODUCTION_PROVEN",'[]',
       "2026-09-03T00:00:00+00:00"))
    con.commit()

def _family_base(con):
    v1=register_version(con,ROOT,"alg-v1","eng",code_ref="v1",config_ref="v1",status="SUPERSEDED")
    v2=register_version(con,ROOT,"alg-v2","eng",parent_algorithm_version_id=v1["algorithm_version_id"],
                        code_ref="v2",config_ref="v2",status="SUPERSEDED")
    _safe_profile(con,v2["algorithm_version_id"])
    _ensure_state(con,ROOT)
    return v1,v2

def _open_family(con,v2):
    # Two distinct historical descendants fell back to v2.
    for idx in (3,4):
        v=register_version(con,ROOT,f"alg-v{idx}","eng",
                           parent_algorithm_version_id=v2["algorithm_version_id"],
                           code_ref=f"v{idx}",config_ref=f"v{idx}",status="FAILED")
        con.execute("""INSERT INTO origin_threshold_recommendation_version_fallbacks(
          root_cause_type,failing_algorithm_version_id,fallback_algorithm_version_id,
          trigger_challenge_id,guard_evaluation_id,action,status,reason,executed_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (ROOT,v["algorithm_version_id"],v2["algorithm_version_id"],idx,idx,
           "FALLBACK_TO_SUPERSEDED_VERSION","EXECUTED","historical",
           f"2026-09-02T0{idx}:00:00+00:00"))
    con.commit()
    chk=automatic_fallback_allowed(con,ROOT,v["algorithm_version_id"],v2["algorithm_version_id"])
    assert chk["allowed"] is False
    p=profiles(con)[0]
    assert p["circuit_state"]=="OPEN"
    return p,cases(con,p["fallback_family_profile_id"])[-1]

def _prepare_recovery(con,v2,case,p):
    family_review(con,p["fallback_family_profile_id"],
                  "ACKNOWLEDGE_ARCHITECTURE_REVIEW","chief","architecture review opened")
    rem=add_remediation(con,case["family_recovery_case_id"],
                        "FAMILY_ARCHITECTURE_FIX","FAM-70-1","engineer","cross-layer family fix")
    review_remediation(con,rem["family_recovery_remediation_id"],
                       "EFFECTIVE","chief","remediation validated")
    cand=register_version(con,ROOT,"alg-v5","eng",
                          parent_algorithm_version_id=v2["algorithm_version_id"],
                          code_ref="v5-new",config_ref="v5-new",status="SHADOW")
    set_candidate_version(con,case["family_recovery_case_id"],
                          cand["algorithm_version_id"],"chief","fresh family candidate")
    return cand

def _add_fresh_evidence(con,case,cand,n=8,helpful=7,harmful=0):
    for i in range(n):
        c=create_challenge(con,100+i,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
        if i<helpful:
            verdict="RECOMMENDATION_HELPFUL"
        elif i<helpful+harmful:
            verdict="RECOMMENDATION_HARMFUL"
        else:
            verdict="NEUTRAL"
        add_evidence(con,case["family_recovery_case_id"],c["challenge_id"],verdict,True,"fresh")
    return evaluate(con,case["family_recovery_case_id"],persist=False)

def test_open_family_circuit_auto_creates_recovery_case(tmp_path):
    con=init_db(tmp_path/"open.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    assert c["status"]=="OPEN"
    assert c["family_signature"]==p["family_signature"]
    con.close()

def test_recovery_requires_fresh_architecture_review(tmp_path):
    con=init_db(tmp_path/"arch.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    # Remove review to prove hard gate.
    con.execute("DELETE FROM origin_threshold_recommendation_fallback_family_reviews")
    con.commit()
    ev=_add_fresh_evidence(con,c,cand,8,8)
    assert ev["architecture_review_confirmed"] is False
    assert ev["status"]=="WARMING"
    con.close()

def test_recovery_requires_effective_family_remediation(tmp_path):
    con=init_db(tmp_path/"rem.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    family_review(con,p["fallback_family_profile_id"],
                  "ACKNOWLEDGE_ARCHITECTURE_REVIEW","chief","review")
    cand=register_version(con,ROOT,"alg-v5","eng",parent_algorithm_version_id=v2["algorithm_version_id"],
                          code_ref="v5",config_ref="v5",status="SHADOW")
    set_candidate_version(con,c["family_recovery_case_id"],cand["algorithm_version_id"],"chief","fresh")
    ev=_add_fresh_evidence(con,c,cand,8,8)
    assert ev["remediation_effective"] is False
    assert ev["status"]=="WARMING"
    con.close()

def test_candidate_must_be_created_after_recovery_open(tmp_path):
    con=init_db(tmp_path/"fresh.sqlite3")
    v1,v2=_family_base(con)
    old=register_version(con,ROOT,"alg-old","eng",parent_algorithm_version_id=v2["algorithm_version_id"],
                         code_ref="old",config_ref="old",status="SHADOW")
    p,c=_open_family(con,v2)
    with pytest.raises(ValueError,match="created after"):
        set_candidate_version(con,c["family_recovery_case_id"],old["algorithm_version_id"],"chief","reuse")
    con.close()

def test_candidate_must_belong_to_affected_family(tmp_path):
    con=init_db(tmp_path/"family.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    other=register_version(con,"THRESHOLD_RECURRENCE","other-v1","eng",
                           code_ref="o",config_ref="o",status="SHADOW")
    with pytest.raises(ValueError,match="root cause mismatch"):
        set_candidate_version(con,c["family_recovery_case_id"],other["algorithm_version_id"],"chief","wrong")
    con.close()

def test_recovery_requires_8_decisive_7_helpful(tmp_path):
    con=init_db(tmp_path/"87.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    ev=_add_fresh_evidence(con,c,cand,7,7)
    assert ev["required_decisive_count"]==8
    assert ev["required_helpful_count"]==7
    assert ev["status"]=="WARMING"
    con.close()

def test_harmful_fresh_family_evidence_blocks_rearm(tmp_path):
    con=init_db(tmp_path/"harm.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    ev=_add_fresh_evidence(con,c,cand,8,7,1)
    assert ev["status"]=="BLOCKED"
    assert ev["harmful_count"]==1
    con.close()

def test_complete_recovery_becomes_ready_for_human_rearm(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    ev=_add_fresh_evidence(con,c,cand,8,7,0)
    assert ev["status"]=="READY_FOR_HUMAN_REARM"
    assert ev["architecture_review_confirmed"] is True
    assert ev["remediation_effective"] is True
    con.close()

def test_human_rearm_sets_circuit_armed_and_policy_shadow_only(tmp_path):
    con=init_db(tmp_path/"rearm.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    _add_fresh_evidence(con,c,cand,8,8)
    r=human_rearm_review(con,c["family_recovery_case_id"],
                         "APPROVE_REARM","chief","fresh family evidence passed")
    assert r["family_profile"]["circuit_state"]=="ARMED"
    st=con.execute("""SELECT mode FROM origin_threshold_recommendation_policy_states
                      WHERE root_cause_type=?""",(ROOT,)).fetchone()
    assert st["mode"]=="SHADOW_ONLY"
    con.close()

def test_rearm_allows_only_approved_candidate_version(tmp_path):
    con=init_db(tmp_path/"candidate.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    _add_fresh_evidence(con,c,cand,8,8)
    human_rearm_review(con,c["family_recovery_case_id"],"APPROVE_REARM","chief","approved")
    other=register_version(con,ROOT,"alg-v6","eng",parent_algorithm_version_id=v2["algorithm_version_id"],
                           code_ref="v6",config_ref="v6",status="PROMOTED")
    perm=rearm_permission(con,p["fallback_family_profile_id"],other["algorithm_version_id"])
    assert perm["allowed"] is False
    con.close()

def test_approved_candidate_gets_one_limited_family_fallback(tmp_path):
    con=init_db(tmp_path/"limited.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    _add_fresh_evidence(con,c,cand,8,8)
    human_rearm_review(con,c["family_recovery_case_id"],"APPROVE_REARM","chief","approved")
    con.execute("UPDATE origin_threshold_recommendation_algorithm_versions SET status='PROMOTED' WHERE algorithm_version_id=?",
                (cand["algorithm_version_id"],))
    con.execute("UPDATE origin_threshold_recommendation_policy_states SET mode='PROMOTED' WHERE root_cause_type=?",(ROOT,))
    con.commit()
    ch=create_challenge(con,500,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    r=execute_fallback(con,ROOT,ch["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert r["executed"] is True
    rc=cases(con,p["fallback_family_profile_id"])[-1]
    assert rc["status"]=="CANARY_ACTIVE"
    assert rc["canary_used_fallbacks"]==1
    con.close()

def test_stable_limited_family_canary_closes_circuit(tmp_path):
    con=init_db(tmp_path/"stable.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    _add_fresh_evidence(con,c,cand,8,8)
    human_rearm_review(con,c["family_recovery_case_id"],"APPROVE_REARM","chief","approved")
    con.execute("UPDATE origin_threshold_recommendation_algorithm_versions SET status='PROMOTED' WHERE algorithm_version_id=?",
                (cand["algorithm_version_id"],))
    con.execute("UPDATE origin_threshold_recommendation_policy_states SET mode='PROMOTED' WHERE root_cause_type=?",(ROOT,))
    con.commit()
    ch=create_challenge(con,500,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    execute_fallback(con,ROOT,ch["challenge_id"],"RECOMMENDATION_HARMFUL")
    for i in range(5):
        fc=create_challenge(con,600+i,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
        verify_observe(con,ROOT,fc["challenge_id"],
                       "RECOMMENDATION_HELPFUL" if i<4 else "RUNTIME_SUCCESS_SHADOW_MIXED")
    fp=profiles(con)[0]
    rc=cases(con,fp["fallback_family_profile_id"])[-1]
    assert fp["circuit_state"]=="CLOSED"
    assert rc["status"]=="STABLE"
    assert rc["stabilized_at"]
    con.close()

def test_watch_family_canary_reopens_circuit(tmp_path):
    con=init_db(tmp_path/"watch.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    _add_fresh_evidence(con,c,cand,8,8)
    human_rearm_review(con,c["family_recovery_case_id"],"APPROVE_REARM","chief","approved")
    con.execute("UPDATE origin_threshold_recommendation_algorithm_versions SET status='PROMOTED' WHERE algorithm_version_id=?",
                (cand["algorithm_version_id"],))
    con.execute("UPDATE origin_threshold_recommendation_policy_states SET mode='PROMOTED' WHERE root_cause_type=?",(ROOT,))
    con.commit()
    execute_fallback(con,ROOT,create_challenge(con,500,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])["challenge_id"],
                     "RECOMMENDATION_HARMFUL")
    for i in range(5):
        fc=create_challenge(con,700+i,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
        verify_observe(con,ROOT,fc["challenge_id"],
                       "RECOMMENDATION_HELPFUL" if i<3 else "RUNTIME_SUCCESS_SHADOW_MIXED")
    assert profiles(con)[0]["circuit_state"]=="OPEN"
    con.close()

def test_failed_family_canary_reopens_circuit(tmp_path):
    con=init_db(tmp_path/"failed.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    _add_fresh_evidence(con,c,cand,8,8)
    human_rearm_review(con,c["family_recovery_case_id"],"APPROVE_REARM","chief","approved")
    con.execute("UPDATE origin_threshold_recommendation_algorithm_versions SET status='PROMOTED' WHERE algorithm_version_id=?",
                (cand["algorithm_version_id"],))
    con.execute("UPDATE origin_threshold_recommendation_policy_states SET mode='PROMOTED' WHERE root_cause_type=?",(ROOT,))
    con.commit()
    execute_fallback(con,ROOT,create_challenge(con,500,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])["challenge_id"],
                     "RECOMMENDATION_HARMFUL")
    fc=create_challenge(con,800,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    verify_observe(con,ROOT,fc["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert profiles(con)[0]["circuit_state"]=="OPEN"
    assert cases(con,p["fallback_family_profile_id"])[-1]["status"]=="FAILED"
    con.close()

def test_recovery_status_exposes_full_audit(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    v1,v2=_family_base(con)
    p,c=_open_family(con,v2)
    cand=_prepare_recovery(con,v2,c,p)
    _add_fresh_evidence(con,c,cand,8,8)
    human_rearm_review(con,c["family_recovery_case_id"],"HOLD","chief","hold")
    s=recovery_status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["cases"])==1
    assert len(s["remediations"])==1
    assert len(s["evidence"])==8
    assert len(s["evaluations"])>=1
    assert len(s["reviews"])==1
    assert len(s["events"])>=3
    con.close()
