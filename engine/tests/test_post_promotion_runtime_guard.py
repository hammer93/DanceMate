import json
from src.database import (
    init_db,create_or_get_promotion_candidate,create_promotion_lease,
    update_promotion_candidate_status,create_full_promotion,
    persist_post_promotion_observation,active_full_promotion,
    full_promotion_rows,persist_canary_outcome_evaluation
)
from src.goal_weighting import BASE_PROFILES
from src.post_promotion_guard import evaluate_post_promotion_guard,post_promotion_health

GOAL="FIELD_QUALITY"; BASE=BASE_PROFILES[GOAL]

def _full(con,canary_rate=0.0):
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
        completed_changes=3,safe_changes=3,divergent_changes=int(canary_rate*3),
        divergence_rate=canary_rate,false_optimism_count=0,
        base_improved_count=1,canary_improved_count=1,criteria={},reasons=[])
    pid=create_full_promotion(
        con,lease_id=lid,candidate_id=cid,goal_profile=GOAL,policy_version="v0.34",
        adaptive_weights=BASE,base_weights=BASE,promoted_by="tester",metadata={})
    return pid

def _obs(con,pid,n,diverged=False,false=False):
    for i in range(1,n+1):
        if false and i==n:
            b,c="INCONCLUSIVE","IMPROVED"
        elif diverged:
            b,c="IMPROVED","REGRESSED"
        else:
            b,c="IMPROVED","IMPROVED"
        persist_post_promotion_observation(
            con,promotion_id=pid,change_id=i,goal_profile=GOAL,
            base_verdict=b,full_verdict=c,base_weighted_score=1.0,
            full_weighted_score=1.0 if c=="IMPROVED" else -1.0)

def test_under_14_samples_remains_observing(tmp_path):
    con=init_db(tmp_path/"observe.sqlite3"); pid=_full(con); _obs(con,pid,7)
    r=evaluate_post_promotion_guard(con,pid)
    assert r["status"]=="OBSERVING"
    assert r["action"]=="NONE"
    assert active_full_promotion(con,GOAL)["status"]=="ACTIVE"
    con.close()

def test_14_safe_samples_mark_stable_full(tmp_path):
    con=init_db(tmp_path/"stable.sqlite3"); pid=_full(con); _obs(con,pid,14)
    r=evaluate_post_promotion_guard(con,pid)
    assert r["status"]=="STABLE_FULL"
    assert r["action"]=="MARK_STABLE_FULL"
    assert active_full_promotion(con,GOAL)["status"]=="STABLE_FULL"
    con.close()

def test_false_optimism_fails_closed(tmp_path):
    con=init_db(tmp_path/"false.sqlite3"); pid=_full(con); _obs(con,pid,3,false=True)
    r=evaluate_post_promotion_guard(con,pid)
    assert r["status"]=="BLOCKED"
    assert r["false_optimism_count"]==1
    assert r["action"]=="FAIL_CLOSED_ROLLBACK"
    assert active_full_promotion(con,GOAL) is None
    assert full_promotion_rows(con,GOAL)[-1]["status"]=="ROLLED_BACK"
    con.close()

def test_recent7_divergence_drift_rolls_back(tmp_path):
    con=init_db(tmp_path/"drift.sqlite3"); pid=_full(con,canary_rate=0.0)
    _obs(con,pid,7,diverged=True)
    r=evaluate_post_promotion_guard(con,pid)
    assert r["recent7_divergence_rate"]==1.0
    assert r["status"]=="BLOCKED"
    assert r["action"]=="FAIL_CLOSED_ROLLBACK"
    con.close()

def test_runtime_observation_is_idempotent_per_promotion_change(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3"); pid=_full(con)
    _obs(con,pid,1); _obs(con,pid,1)
    h=post_promotion_health(con,GOAL)
    assert h[0]["runtime_observations"]==1
    con.close()
