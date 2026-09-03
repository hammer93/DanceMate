import pytest

from src.database import init_db
from src.origin_threshold_recommendation_versioning import (
    register_version,versions,current_version,lineage,version_for_entity,
    mark_status,mark_failed,recovery_links,propose_successor,approve_successor,
    recovery_successor_ready,status
)
from src.origin_threshold_recommendation_challenge import create_challenge
from src.origin_threshold_recommendation_policy import (
    _ensure_state,manual_rollback,evaluate_candidate,review_candidate,
    final_policy_review
)
from src.origin_threshold_recommendation_recovery import (
    cases,add_remediation,review_remediation,add_evidence,evaluate,review_recanary
)
from src.origin_threshold_recommendation_version_promotion import human_review as version_human_review

ROOT="SOURCE_LOCAL_RECURRENCE"

def _rec():
    return {
        "selected_steps":["DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"],
        "source":"CONTEXT_COMPARATIVE_RANKING",
        "comparative_score":.8,
        "context_signature":"CTX"
    }

def _quality(con):
    con.execute("""INSERT INTO origin_threshold_architecture_recommendation_quality_profiles(
      root_cause_type,challenge_count,accepted_count,baseline_selected_count,hold_count,
      runtime_decisive_count,recommendation_helpful_count,recommendation_harmful_count,
      recommendation_neutral_count,acceptance_rate,helpful_rate,harmful_rate,
      confidence_band,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ROOT,5,4,1,0,5,4,0,1,.8,.8,0.0,"ESTABLISHED","2026-09-02T00:00:00+00:00"))
    con.commit()

def _rollback_case(con):
    register_version(con,ROOT,"alg-v1","engineer",code_ref="code-v1",config_ref="cfg-v1",status="PROMOTED")
    _ensure_state(con,ROOT)
    con.execute("UPDATE origin_threshold_recommendation_policy_states SET mode='PROMOTED' WHERE root_cause_type=?",(ROOT,))
    con.commit()
    st=manual_rollback(con,ROOT,"owner","harmful recommendation runtime verdict")
    return st,cases(con,ROOT)[0]

def _successor(con,case_id,label="alg-v2"):
    r=add_remediation(con,case_id,"RANKING_LOGIC_FIX","REM-2","engineer","fix")
    review_remediation(con,r["policy_recovery_remediation_id"],"EFFECTIVE","reviewer","verified")
    p=propose_successor(con,case_id,label,"engineer",r["policy_recovery_remediation_id"],
                        "new algorithm",code_ref=label+"-code",config_ref=label+"-cfg")
    a=approve_successor(con,case_id,"reviewer","approved version")
    return r,p,a

def _fresh_evidence(con,case_id,n=5,helpful=5):
    for i in range(n):
        add_evidence(con,case_id,100+i,
                     "RECOMMENDATION_HELPFUL" if i<helpful else "NEUTRAL",
                     True,"fresh")

def test_register_version_is_immutable_by_label(tmp_path):
    con=init_db(tmp_path/"label.sqlite3")
    register_version(con,ROOT,"alg-v1","eng",code_ref="a",config_ref="b")
    with pytest.raises(Exception):
        register_version(con,ROOT,"alg-v1","eng",code_ref="c",config_ref="d")
    con.close()

def test_register_version_is_immutable_by_fingerprint(tmp_path):
    con=init_db(tmp_path/"fp.sqlite3")
    a=register_version(con,ROOT,"alg-v1","eng",fingerprint="same")
    assert a["fingerprint"]=="same"
    with pytest.raises(Exception):
        register_version(con,ROOT,"alg-v2","eng",fingerprint="same")
    con.close()

def test_challenge_is_linked_to_current_algorithm_version(tmp_path):
    con=init_db(tmp_path/"challenge.sqlite3")
    v=register_version(con,ROOT,"alg-v1","eng",code_ref="c1",config_ref="f1",status="SHADOW")
    c=create_challenge(con,1,ROOT,"CTX",_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    linked=version_for_entity(con,"CHALLENGE",c["challenge_id"],"EVALUATED_BY")
    assert linked["algorithm_version_id"]==v["algorithm_version_id"]
    con.close()

def test_policy_candidate_is_linked_to_algorithm_version(tmp_path):
    con=init_db(tmp_path/"candidate.sqlite3")
    v=register_version(con,ROOT,"alg-v1","eng",code_ref="c1",config_ref="f1",status="SHADOW")
    _quality(con)
    c=evaluate_candidate(con,ROOT,persist=True)
    linked=version_for_entity(con,"POLICY_CANDIDATE",c["policy_candidate_id"],"CANDIDATE_FOR")
    assert linked["algorithm_version_id"]==v["algorithm_version_id"]
    con.close()

def test_canary_review_marks_candidate_version_canary(tmp_path):
    con=init_db(tmp_path/"canary.sqlite3")
    v=register_version(con,ROOT,"alg-v1","eng",code_ref="c1",config_ref="f1",status="SHADOW")
    _quality(con)
    c=evaluate_candidate(con,ROOT,persist=True)
    review_candidate(con,c["policy_candidate_id"],"APPROVE_CANARY","owner","ready",1)
    assert versions(con,ROOT)[0]["status"]=="CANARY"
    con.close()

def test_rollback_marks_exact_algorithm_failed_and_locks_recovery_link(tmp_path):
    con=init_db(tmp_path/"rollback.sqlite3")
    st,case=_rollback_case(con)
    v=versions(con,ROOT)[0]
    assert v["status"]=="FAILED"
    link=recovery_links(con,case["policy_recovery_case_id"])[0]
    assert link["failed_algorithm_version_id"]==v["algorithm_version_id"]
    assert link["status"]=="FAILED_VERSION_LOCKED"
    con.close()

def test_failed_version_label_cannot_be_reused_as_successor(tmp_path):
    con=init_db(tmp_path/"same.sqlite3")
    st,case=_rollback_case(con)
    r=add_remediation(con,case["policy_recovery_case_id"],"RANKING_LOGIC_FIX","R","eng","fix")
    review_remediation(con,r["policy_recovery_remediation_id"],"EFFECTIVE","reviewer","ok")
    with pytest.raises(ValueError,match="cannot be reused"):
        propose_successor(con,case["policy_recovery_case_id"],"alg-v1","eng",
                          r["policy_recovery_remediation_id"],code_ref="new",config_ref="new")
    con.close()

def test_successor_requires_effective_recovery_remediation(tmp_path):
    con=init_db(tmp_path/"effective.sqlite3")
    st,case=_rollback_case(con)
    r=add_remediation(con,case["policy_recovery_case_id"],"RANKING_LOGIC_FIX","R","eng","fix")
    propose_successor(con,case["policy_recovery_case_id"],"alg-v2","eng",
                      r["policy_recovery_remediation_id"],code_ref="new",config_ref="new")
    with pytest.raises(ValueError,match="EFFECTIVE"):
        approve_successor(con,case["policy_recovery_case_id"],"reviewer","not effective")
    con.close()

def test_approved_successor_is_distinct_child_of_failed_version(tmp_path):
    con=init_db(tmp_path/"child.sqlite3")
    st,case=_rollback_case(con)
    r,p,a=_successor(con,case["policy_recovery_case_id"])
    failed=versions(con,ROOT)[0]
    successor=p["successor"]
    assert successor["algorithm_version_id"]!=failed["algorithm_version_id"]
    assert successor["parent_algorithm_version_id"]==failed["algorithm_version_id"]
    assert recovery_successor_ready(con,case["policy_recovery_case_id"])["ready"] is True
    con.close()

def test_recovery_gate_blocks_without_successor_version(tmp_path):
    con=init_db(tmp_path/"gate.sqlite3")
    st,case=_rollback_case(con)
    r=add_remediation(con,case["policy_recovery_case_id"],"RANKING_LOGIC_FIX","R","eng","fix")
    review_remediation(con,r["policy_recovery_remediation_id"],"EFFECTIVE","reviewer","ok")
    _fresh_evidence(con,case["policy_recovery_case_id"],5,5)
    ev=evaluate(con,case["policy_recovery_case_id"],persist=False)
    assert ev["successor_version_ready"] is False
    assert ev["status"]=="WARMING"
    con.close()

def test_recovery_gate_ready_with_new_approved_version(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    st,case=_rollback_case(con)
    _successor(con,case["policy_recovery_case_id"])
    _fresh_evidence(con,case["policy_recovery_case_id"],5,5)
    ev=evaluate(con,case["policy_recovery_case_id"],persist=False)
    assert ev["successor_version_ready"] is True
    assert ev["status"]=="READY_FOR_RECANARY"
    con.close()

def test_recanary_marks_successor_version_canary(tmp_path):
    con=init_db(tmp_path/"recanary.sqlite3")
    st,case=_rollback_case(con)
    r,p,a=_successor(con,case["policy_recovery_case_id"])
    _fresh_evidence(con,case["policy_recovery_case_id"],5,5)
    review_recanary(con,case["policy_recovery_case_id"],"APPROVE_RECANARY","owner","ready",1)
    successor=versions(con,ROOT)[-1]
    assert successor["version_label"]=="alg-v2"
    assert successor["status"]=="CANARY"
    con.close()

def test_repromotion_promotes_successor_not_failed_version(tmp_path):
    con=init_db(tmp_path/"promote.sqlite3")
    st,case=_rollback_case(con)
    _successor(con,case["policy_recovery_case_id"])
    _fresh_evidence(con,case["policy_recovery_case_id"],5,5)
    review_recanary(con,case["policy_recovery_case_id"],"APPROVE_RECANARY","owner","ready",1)
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
                   SET mode='READY_FOR_PROMOTION' WHERE root_cause_type=?""",(ROOT,))
    successor=versions(con,ROOT)[-1]
    con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_version_profiles(
      algorithm_version_id,root_cause_type,context_signature,total_runtime_count,
      decisive_runtime_count,canary_runtime_count,production_runtime_count,
      helpful_count,harmful_count,neutral_count,rollback_count,helpful_rate,
      harmful_rate,median_survival_days,confidence_band,safety_band,
      promotion_memory_status,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (successor["algorithm_version_id"],ROOT,"CTX",3,3,3,0,3,0,0,0,1.0,0.0,90.0,
       "EMERGING","SAFE","VERSION_CANARY_PROVEN",'[]',"2026-09-02T00:00:00+00:00"))
    con.commit()
    version_human_review(
        con,successor["algorithm_version_id"],"PROMOTE","version-owner",
        "successor version canary evidence passed")
    final_policy_review(con,ROOT,"PROMOTE","owner","recanary passed")
    vs=versions(con,ROOT)
    assert vs[0]["status"]=="FAILED"
    assert vs[-1]["status"]=="PROMOTED"
    con.close()

def test_lineage_contains_failed_and_successor_recovery_edges(tmp_path):
    con=init_db(tmp_path/"lineage.sqlite3")
    st,case=_rollback_case(con)
    r,p,a=_successor(con,case["policy_recovery_case_id"])
    rows=lineage(con)
    relations={x["relation_type"] for x in rows}
    assert "FAILED_IN" in relations
    assert "SUCCESSOR_FOR" in relations
    assert "CREATED_BY" in relations
    con.close()

def test_version_status_exposes_full_audit(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    st,case=_rollback_case(con)
    _successor(con,case["policy_recovery_case_id"])
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["versions"])==2
    assert len(s["recovery_version_links"])==1
    assert len(s["events"])>=4
    con.close()
