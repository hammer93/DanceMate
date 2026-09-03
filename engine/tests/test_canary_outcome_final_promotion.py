import json
import pytest

from src.database import (
    init_db,create_or_get_promotion_candidate,create_promotion_lease,
    update_promotion_candidate_status,consume_promotion_lease_change,
    persist_promotion_lease_event,promotion_lease_row,active_full_promotion,
    full_promotion_rows
)
from src.goal_weighting import BASE_PROFILES
from src.canary_outcome import (
    evaluate_canary_outcome,final_promotion_decision,final_promotion_reviews,
    full_promotions,rollback_active_full_promotion
)

GOAL="FIELD_QUALITY"
BASE=BASE_PROFILES[GOAL]

def _lease(con,max_changes=3,adaptive=None):
    cid,_=create_or_get_promotion_candidate(
        con,goal_profile=GOAL,policy_version="v0.32",rolling_id=1,
        total_samples=20,agreement_rate=1.0,unsafe_improved=0,
        criteria={},reasons=["test"])
    update_promotion_candidate_status(con,cid,"APPROVED_CANARY","test approval")
    aw=dict(BASE)
    if adaptive:
        aw.update(adaptive)
    lid=create_promotion_lease(
        con,candidate_id=cid,goal_profile=GOAL,policy_version="v0.33",
        max_canary_changes=max_changes,adaptive_weights=aw,base_weights=BASE,
        approved_by="tester",metadata={"test":True})
    return cid,lid,aw

def _outcome(con,lid,change_id,base,canary):
    consume_promotion_lease_change(
        con,lid,change_id=change_id,actor="test")
    persist_promotion_lease_event(
        con,lease_id=lid,event_type="CANARY_OUTCOME",actor="test",
        change_id=change_id,
        detail={
            "base_verdict":base,
            "canary_verdict":canary,
            "diverged":base!=canary,
            "false_optimism":base!="IMPROVED" and canary=="IMPROVED"
        })

def test_exhausted_safe_canary_is_ready_for_final_review(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    _,lid,_=_lease(con,3)
    _outcome(con,lid,1,"REGRESSED","REGRESSED")
    _outcome(con,lid,2,"IMPROVED","IMPROVED")
    _outcome(con,lid,3,"INCONCLUSIVE","INCONCLUSIVE")

    r=evaluate_canary_outcome(con,lid)
    assert promotion_lease_row(con,lid)["status"]=="EXHAUSTED"
    assert r["status"]=="READY_FOR_FINAL_REVIEW"
    assert r["completed_changes"]==3
    assert r["safe_changes"]==3
    assert r["false_optimism_count"]==0
    assert r["divergence_rate"]==0.0
    con.close()

def test_false_optimism_blocks_outcome_gate(tmp_path):
    con=init_db(tmp_path/"blocked.sqlite3")
    _,lid,_=_lease(con,3)
    _outcome(con,lid,1,"REGRESSED","REGRESSED")
    _outcome(con,lid,2,"INCONCLUSIVE","IMPROVED")
    _outcome(con,lid,3,"IMPROVED","IMPROVED")

    r=evaluate_canary_outcome(con,lid)
    assert r["status"]=="BLOCKED"
    assert r["false_optimism_count"]==1
    con.close()

def test_final_promote_requires_ready_gate_and_human_decision(tmp_path):
    con=init_db(tmp_path/"promote.sqlite3")
    cid,lid,aw=_lease(con,3,{"correction_rate":3.5})
    for i in range(1,4):
        _outcome(con,lid,i,"IMPROVED","IMPROVED")

    result=final_promotion_decision(
        con,lease_id=lid,decision="PROMOTE",reviewer="김프로",
        reason="Canary 안전 완료")
    assert result["status"]=="FULL_PROMOTION_ACTIVE"
    assert result["human_final_approval"] is True

    full=active_full_promotion(con,GOAL)
    assert full is not None
    assert full["promoted_by"]=="김프로"
    assert json.loads(full["adaptive_weights_json"])["correction_rate"]==3.5
    assert promotion_lease_row(con,lid)["status"]=="PROMOTED"

    reviews=final_promotion_reviews(con,lid)
    assert reviews[-1]["decision"]=="PROMOTE"
    assert reviews[-1]["reviewer"]=="김프로"
    con.close()

def test_final_promote_blocked_before_lease_exhaustion(tmp_path):
    con=init_db(tmp_path/"early.sqlite3")
    _,lid,_=_lease(con,5)
    for i in range(1,4):
        _outcome(con,lid,i,"IMPROVED","IMPROVED")
    gate=evaluate_canary_outcome(con,lid)
    assert gate["status"]=="OBSERVING"
    assert promotion_lease_row(con,lid)["status"]=="ACTIVE"

    with pytest.raises(ValueError,match="cannot PROMOTE"):
        final_promotion_decision(
            con,lease_id=lid,decision="PROMOTE",reviewer="tester")
    assert active_full_promotion(con,GOAL) is None
    con.close()

def test_extend_reactivates_exhausted_lease(tmp_path):
    con=init_db(tmp_path/"extend.sqlite3")
    _,lid,_=_lease(con,3)
    for i in range(1,4):
        _outcome(con,lid,i,"REGRESSED","REGRESSED")
    assert promotion_lease_row(con,lid)["status"]=="EXHAUSTED"

    result=final_promotion_decision(
        con,lease_id=lid,decision="EXTEND",reviewer="tester",
        reason="추가 표본",additional_changes=2)
    assert result["status"]=="ACTIVE"
    assert result["new_max_canary_changes"]==5
    lease=promotion_lease_row(con,lid)
    assert lease["status"]=="ACTIVE"
    assert lease["max_canary_changes"]==5
    con.close()

def test_full_promotion_has_explicit_rollback(tmp_path):
    con=init_db(tmp_path/"rollback.sqlite3")
    _,lid,_=_lease(con,3)
    for i in range(1,4):
        _outcome(con,lid,i,"IMPROVED","IMPROVED")
    final_promotion_decision(
        con,lease_id=lid,decision="PROMOTE",reviewer="김프로")

    result=rollback_active_full_promotion(
        con,goal_profile=GOAL,actor="김프로",reason="운영 중지")
    assert result["rolled_back"] is True
    rows=full_promotions(con,GOAL)
    assert rows[-1]["status"]=="ROLLED_BACK"
    assert rows[-1]["rollback_reason"]=="운영 중지"
    con.close()
