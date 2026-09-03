import json
import pytest

from src.database import (
    init_db,persist_adaptive_shadow_verdict,upsert_adaptive_weight_profile,
    promotion_candidate_row,active_promotion_lease,promotion_lease_row,
    create_daily_run,finish_daily_run,persist_daily_metric_snapshot,
    create_backlog_item
)
from src.goal_weighting import BASE_PROFILES
from src.rolling_shadow_stability import evaluate_rolling_shadow_stability,promotion_candidates
from src.adaptive_promotion import (
    review_promotion_candidate,promotion_review_history,promotion_leases,
    promotion_lease_events,rollback_active_goal_lease
)
from src.daily_metric_snapshot import canonical_payload_hash
from src.change_traceability import (
    register_change,link_and_measure_change,evaluate_change_effect
)

GOAL="FIELD_QUALITY"
BASE=BASE_PROFILES[GOAL]

def _shadow(con,idx,base="REGRESSED",shadow="REGRESSED"):
    persist_adaptive_shadow_verdict(
        con,change_id=idx,
        baseline_daily_run_id=f"sb-{idx}",
        post_daily_run_id=f"sp-{idx}",
        goal_profile=GOAL,
        base_verdict=base,shadow_verdict=shadow,
        base_weighted_score=-1.0 if base=="REGRESSED" else 1.0,
        shadow_weighted_score=-1.0 if shadow=="REGRESSED" else 1.0,
        agrees=(base==shadow),adaptive_sample_count=max(0,idx-1),
        base_weights=BASE,shadow_weights=BASE,reasons=[])

def _eligible_candidate(con,adaptive=None):
    for i in range(1,21):
        _shadow(con,i)
    rolling=evaluate_rolling_shadow_stability(con,GOAL)
    assert rolling["status"]=="ELIGIBLE"
    cid=rolling["promotion_candidate"]["candidate_id"]
    aw=dict(BASE)
    if adaptive:
        aw.update(adaptive)
    upsert_adaptive_weight_profile(
        con,goal_profile=GOAL,base_weights=BASE,
        adaptive_weights=aw,sample_count=20)
    return cid,aw

def test_human_approve_creates_goal_scoped_canary_lease(tmp_path):
    con=init_db(tmp_path/"approve.sqlite3")
    cid,aw=_eligible_candidate(con,{"correction_rate":3.5})
    result=review_promotion_candidate(
        con,candidate_id=cid,decision="APPROVE",reviewer="김프로",
        reason="Canary 승인",max_canary_changes=5)

    assert result["candidate_status"]=="APPROVED_CANARY"
    assert result["lease"]["status"]=="ACTIVE"
    assert result["lease"]["max_canary_changes"]==5
    assert promotion_candidate_row(con,cid)["status"]=="APPROVED_CANARY"

    lease=active_promotion_lease(con,GOAL)
    assert lease is not None
    assert json.loads(lease["adaptive_weights_json"])["correction_rate"]==3.5
    assert lease["approved_by"]=="김프로"

    reviews=promotion_review_history(con,cid)
    assert reviews[-1]["decision"]=="APPROVE"
    events=promotion_lease_events(con,lease["lease_id"])
    assert events[0]["event_type"]=="LEASE_STARTED"
    con.close()

def test_hold_and_reject_are_audited_without_lease(tmp_path):
    con=init_db(tmp_path/"review.sqlite3")
    cid,_=_eligible_candidate(con)

    hold=review_promotion_candidate(
        con,candidate_id=cid,decision="HOLD",reviewer="reviewer",
        reason="추가 표본 필요")
    assert hold["candidate_status"]=="HOLD"
    assert active_promotion_lease(con,GOAL) is None

    reject=review_promotion_candidate(
        con,candidate_id=cid,decision="REJECT",reviewer="reviewer",
        reason="가중치 근거 부족")
    assert reject["candidate_status"]=="REJECTED"
    reviews=promotion_review_history(con,cid)
    assert [r["decision"] for r in reviews]==["HOLD","REJECT"]
    assert active_promotion_lease(con,GOAL) is None
    con.close()

def test_approval_is_blocked_when_rolling_gate_is_not_eligible(tmp_path):
    con=init_db(tmp_path/"blocked.sqlite3")
    # Candidate row is created directly to test decision-time safety re-check.
    from src.database import create_or_get_promotion_candidate
    cid,_=create_or_get_promotion_candidate(
        con,goal_profile=GOAL,policy_version="v0.32",rolling_id=None,
        total_samples=1,agreement_rate=1.0,unsafe_improved=0,
        criteria={},reasons=["synthetic"])
    upsert_adaptive_weight_profile(
        con,goal_profile=GOAL,base_weights=BASE,
        adaptive_weights=BASE,sample_count=20)

    with pytest.raises(ValueError,match="rolling stability is OBSERVING"):
        review_promotion_candidate(
            con,candidate_id=cid,decision="APPROVE",reviewer="reviewer")
    assert active_promotion_lease(con,GOAL) is None
    con.close()

def _payload(correction,access,coverage=1.0,known=1.0,yield_rate=1.0,recovery=1.0):
    verified=int(round(coverage*100))
    expected=max(0,int(round((known-coverage)*100)))
    unknown=max(0,100-verified-expected)
    return {
      "event_confidence_distribution":{},
      "field_confidence_distribution":{
        "VERIFIED":verified,"EXPECTED":expected,"UNKNOWN":unknown},
      "source_operations":[{
        "source_id":"SRC-X","access_failure_rate":access,
        "source_yield_rate":yield_rate,"recovery_success_rate":recovery}],
      "human_in_loop_metrics":{"manual_correction_rate":correction},
      "correction_hotspots":{"source_field_hotspots":[{
        "source_id":"SRC-X","field":"fee","correction_rate":correction}]},
      "improvement_backlog":{},"p0_count":0,"health":"GREEN"
    }

def _daily(con,date,payload):
    rid=create_daily_run(con,run_date=date,mode="snapshot")
    finish_daily_run(con,rid,status="PASS",metric_status="PASS",report_status="PASS")
    persist_daily_metric_snapshot(
        con,daily_run_id=rid,run_date=date,payload=payload,
        immutable_hash=canonical_payload_hash(payload))
    return rid

def test_canary_production_uses_frozen_adaptive_weights_and_rolls_back_on_false_optimism(tmp_path):
    con=init_db(tmp_path/"canary.sqlite3")
    cid,aw=_eligible_candidate(
        con,{"correction_rate":3.75,"access_failure_rate":0.375})
    approved=review_promotion_candidate(
        con,candidate_id=cid,decision="APPROVE",reviewer="김프로",
        max_canary_changes=5)
    lease_id=approved["lease"]["lease_id"]

    bid,_=create_backlog_item(
        con,source_id="SRC-X",field_name="fee",title="fee quality",
        priority="P1",sample_confidence="HIGH",hotspot_score=9,
        goal_profile=GOAL,goal_weights=BASE,opened_by="test")

    baseline=_daily(con,"2026-08-27",_payload(.5,.2))
    change=register_change(
        con,backlog_id=bid,title="fee canary",component="EVIDENCE/FEE",
        actor="dev")
    assert change["auto_baseline"]["daily_run_id"]==baseline

    # Base: +0.3 gain vs -0.25 loss => INCONCLUSIVE.
    # Frozen canary: +0.375 gain vs -0.1875 loss => IMPROVED.
    post=_daily(con,"2026-08-28",_payload(.4,.7))
    link_and_measure_change(
        con,change_id=change["change_id"],daily_run_id=post,
        relation="POST_CHANGE",baseline_daily_run_id=baseline)

    result=evaluate_change_effect(con,change["change_id"])
    assert result["production_mode"]=="CANARY_ADAPTIVE"
    assert result["base_reference"]["verdict"]=="INCONCLUSIVE"
    assert result["verdict"]=="IMPROVED"
    assert result["canary"]["safety_guard_triggered"] is True

    lease=promotion_lease_row(con,lease_id)
    assert lease["status"]=="ROLLED_BACK"
    assert "Unsafe canary optimism" in lease["rollback_reason"]

    events=promotion_lease_events(con,lease_id)
    types=[e["event_type"] for e in events]
    assert "CANARY_CHANGE_USED" in types
    assert "CANARY_SAFETY_BLOCK" in types
    assert "ROLLBACK" in types
    con.close()

def test_manual_rollback_is_audited(tmp_path):
    con=init_db(tmp_path/"manual.sqlite3")
    cid,_=_eligible_candidate(con,{"correction_rate":3.5})
    approved=review_promotion_candidate(
        con,candidate_id=cid,decision="APPROVE",reviewer="김프로")
    lease_id=approved["lease"]["lease_id"]

    result=rollback_active_goal_lease(
        con,goal_profile=GOAL,actor="김프로",reason="운영 검토 중지")
    assert result["rolled_back"] is True
    lease=promotion_lease_row(con,lease_id)
    assert lease["status"]=="ROLLED_BACK"
    assert lease["rollback_reason"]=="운영 검토 중지"
    events=promotion_lease_events(con,lease_id)
    assert events[-1]["event_type"]=="ROLLBACK"
    assert events[-1]["actor"]=="김프로"
    con.close()
