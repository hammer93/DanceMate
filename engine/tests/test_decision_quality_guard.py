from src.database import (
 init_db,create_or_get_promotion_candidate,create_promotion_lease,
 update_promotion_candidate_status,create_full_promotion,
 persist_canary_outcome_evaluation,persist_post_promotion_observation,
 full_promotion_rows
)
from src.goal_weighting import BASE_PROFILES
from src.decision_quality import record_decision_quality,evaluate_goal_relevance
from src.post_promotion_guard import evaluate_post_promotion_guard

GOAL="FIELD_QUALITY"; BASE=BASE_PROFILES[GOAL]

def test_five_successful_core_decisions_are_healthy(tmp_path):
    con=init_db(tmp_path/"healthy.sqlite3")
    for i in range(5):
        record_decision_quality(
            con,goal_profile=GOAL,decision_outcome="SUCCESS",
            event_truth="EVENT_OCCURRED",core_relevance=.9,user_impact=.8)
    r=evaluate_goal_relevance(con,GOAL)
    assert r["status"]=="HEALTHY"
    assert r["successful_decision_rate"]==1.0
    assert r["core_relevance_rate"]==.9
    con.close()

def test_false_verified_is_immediate_block(tmp_path):
    con=init_db(tmp_path/"fv.sqlite3")
    record_decision_quality(
        con,goal_profile=GOAL,decision_outcome="FAILURE",
        event_truth="EVENT_DID_NOT_OCCUR",source_confidence="VERIFIED",
        critical_error_type="FALSE_VERIFIED",core_relevance=1,user_impact=1)
    r=evaluate_goal_relevance(con,GOAL)
    assert r["status"]=="BLOCKED"
    assert r["false_verified_count"]==1
    con.close()

def test_cancellation_miss_is_immediate_block(tmp_path):
    con=init_db(tmp_path/"cancel.sqlite3")
    record_decision_quality(
        con,goal_profile=GOAL,decision_outcome="FAILURE",
        event_truth="CANCELLED",critical_error_type="CANCELLATION_MISS",
        core_relevance=1,user_impact=1)
    r=evaluate_goal_relevance(con,GOAL)
    assert r["status"]=="BLOCKED"
    assert r["cancellation_miss_count"]==1
    con.close()

def test_support_only_movements_are_goal_mismatch(tmp_path):
    con=init_db(tmp_path/"support.sqlite3")
    for i in range(5):
        record_decision_quality(
            con,goal_profile=GOAL,decision_outcome="SUCCESS",
            event_truth="EVENT_OCCURRED",core_relevance=.2,user_impact=.2)
    r=evaluate_goal_relevance(con,GOAL)
    assert r["status"]=="GOAL_MISMATCH"
    assert r["support_only_count"]==5
    con.close()

def _full(con):
    cid,_=create_or_get_promotion_candidate(
        con,goal_profile=GOAL,policy_version="v0.32",rolling_id=1,total_samples=20,
        agreement_rate=1.0,unsafe_improved=0,criteria={},reasons=["test"])
    update_promotion_candidate_status(con,cid,"APPROVED_CANARY","test")
    lid=create_promotion_lease(
        con,candidate_id=cid,goal_profile=GOAL,policy_version="v0.33",
        max_canary_changes=3,adaptive_weights=BASE,base_weights=BASE,
        approved_by="tester",metadata={})
    persist_canary_outcome_evaluation(
        con,lease_id=lid,policy_version="v0.34",status="READY_FOR_FINAL_REVIEW",
        completed_changes=3,safe_changes=3,divergent_changes=0,divergence_rate=0.0,
        false_optimism_count=0,base_improved_count=1,canary_improved_count=1,
        criteria={},reasons=[])
    return create_full_promotion(
        con,lease_id=lid,candidate_id=cid,goal_profile=GOAL,policy_version="v0.34",
        adaptive_weights=BASE,base_weights=BASE,promoted_by="tester",metadata={})

def test_decision_quality_block_forces_post_promotion_rollback(tmp_path):
    con=init_db(tmp_path/"integrated.sqlite3"); pid=_full(con)
    # Runtime technical verdicts look perfectly safe.
    for i in range(1,6):
        persist_post_promotion_observation(
            con,promotion_id=pid,change_id=i,goal_profile=GOAL,
            base_verdict="IMPROVED",full_verdict="IMPROVED",
            base_weighted_score=1,full_weighted_score=1)
    # But one real-world false VERIFIED makes user decision quality unsafe.
    record_decision_quality(
        con,goal_profile=GOAL,decision_outcome="FAILURE",
        event_truth="EVENT_DID_NOT_OCCUR",source_confidence="VERIFIED",
        critical_error_type="FALSE_VERIFIED",core_relevance=1,user_impact=1)
    r=evaluate_post_promotion_guard(con,pid,persist=True,enforce=True)
    assert r["decision_quality"]["status"]=="BLOCKED"
    assert r["status"]=="BLOCKED"
    assert r["action"]=="FAIL_CLOSED_ROLLBACK"
    assert full_promotion_rows(con,GOAL)[-1]["status"]=="ROLLED_BACK"
    con.close()
