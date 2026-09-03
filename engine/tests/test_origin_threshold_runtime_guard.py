import pytest
from datetime import datetime, timezone

from src.database import init_db
from src.origin_threshold_runtime_guard import (
    observe_runtime_outcome,evaluate_runtime_guard,runtime_history,
    evaluation_history,recovery_cases,add_recovery_shadow_outcome,
    requalify_recovery,runtime_guard_status
)
from src.origin_threshold_promotion import (
    create_candidate_from_latest_calibration,runtime_status
)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _candidate(con,cid=1,base=.86,cand=.89,status="FULL_PROMOTED"):
    con.execute("""INSERT INTO origin_threshold_candidates(
      candidate_id,calibration_id,baseline_threshold,candidate_threshold,direction,
      status,shadow_gate_status,decisive_review_count,base_precision,
      candidate_precision,base_false_positive_rate,candidate_false_positive_rate,
      base_missed_syndication_count,candidate_missed_syndication_count,
      critical_missed_syndication_count,reasons_json,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cid,cid,base,cand,"TIGHTEN",status,"READY_FOR_HUMAN_REVIEW",7,
       .7,.9,.3,.1,0,0,0,'[]',_now(),_now()))
    con.commit()

def _promotion(con,pid=1,cid=1,threshold=.89):
    _candidate(con,cid,base=.86,cand=threshold)
    con.execute("""INSERT INTO origin_threshold_promotions(
      promotion_id,candidate_id,canary_id,status,production_threshold,
      approved_by,reason,promoted_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (pid,cid,None,"ACTIVE",threshold,"human","safe canary",_now()))
    con.commit()

def _observe(con,eid,outcome,sim,critical=False,status="POSSIBLE"):
    return observe_runtime_outcome(
        con,event_instance_id=eid,human_outcome=outcome,
        max_text_similarity=sim,critical=critical,event_status=status)

def test_no_active_promotion_does_not_record(tmp_path):
    con=init_db(tmp_path/"none.sqlite3")
    r=_observe(con,1,"CONFIRM_SYNDICATION",.95)
    assert r["recorded"] is False
    assert runtime_history(con)==[]
    con.close()

def test_counterfactual_promotion_improvement_for_tighten(tmp_path):
    con=init_db(tmp_path/"improve.sqlite3")
    _promotion(con)
    # Independent post at .87: Base .86 says syndication (wrong), promoted .89 says no (correct).
    r=_observe(con,1,"CONFIRM_INDEPENDENT",.87)
    assert r["counterfactual_class"]=="PROMOTION_IMPROVEMENT"
    assert r["base_correct"] is False
    assert r["promoted_correct"] is True
    assert r["rollback"] is None
    con.close()

def test_counterfactual_promotion_regression_detected(tmp_path):
    con=init_db(tmp_path/"regression.sqlite3")
    _promotion(con)
    # True syndication at .87: Base catches it, promoted .89 misses it.
    r=_observe(con,1,"CONFIRM_SYNDICATION",.87)
    assert r["counterfactual_class"]=="PROMOTION_REGRESSION"
    assert r["base_correct"] is True
    assert r["promoted_correct"] is False
    assert r["guard"]["overall_status"]=="WARMING"
    con.close()

def test_critical_promotion_regression_rolls_back_immediately(tmp_path):
    con=init_db(tmp_path/"critical.sqlite3")
    _promotion(con)
    r=_observe(con,1,"CONFIRM_SYNDICATION",.87,critical=True,status="VERIFIED")
    assert r["guard"]["overall_status"]=="ROLLBACK"
    assert r["rollback"]["rolled_back"] is True
    assert r["rollback"]["promotion"]["status"]=="ROLLED_BACK"
    assert runtime_status(con)["effective_full_threshold"]==pytest.approx(.86)
    rc=recovery_cases(con)
    assert len(rc)==1 and rc[0]["status"]=="OPEN"
    con.close()

def test_two_promotion_regressions_in_rolling_five_auto_rollback(tmp_path):
    con=init_db(tmp_path/"five-reg.sqlite3")
    _promotion(con)
    # 3 safe/improved/correct + 2 promotion-specific misses.
    rows=[
        ("CONFIRM_SYNDICATION",.95),
        ("CONFIRM_INDEPENDENT",.87),
        ("CONFIRM_SYNDICATION",.95),
        ("CONFIRM_SYNDICATION",.87),
        ("CONFIRM_SYNDICATION",.87),
    ]
    last=None
    for i,(outcome,sim) in enumerate(rows,1):
        last=_observe(con,i,outcome,sim)
    assert last["guard"]["windows"][0]["observed_count"]==5
    assert last["guard"]["windows"][0]["promotion_regression_count"]==2
    assert last["guard"]["overall_status"]=="ROLLBACK"
    assert last["rollback"]["rolled_back"] is True
    con.close()

def test_rolling_five_healthy_with_safe_outcomes(tmp_path):
    con=init_db(tmp_path/"healthy.sqlite3")
    _promotion(con)
    # Tighten fixes Base FPs, plus obvious true syndications.
    rows=[
        ("CONFIRM_INDEPENDENT",.87),
        ("CONFIRM_SYNDICATION",.95),
        ("CONFIRM_INDEPENDENT",.87),
        ("CONFIRM_SYNDICATION",.96),
        ("CONFIRM_INDEPENDENT",.20),
    ]
    last=None
    for i,(outcome,sim) in enumerate(rows,1):
        last=_observe(con,i,outcome,sim)
    w5=last["guard"]["windows"][0]
    assert w5["status"]=="HEALTHY"
    assert w5["promotion_regression_count"]==0
    assert w5["promotion_improvement_count"]==2
    assert last["rollback"] is None
    con.close()

def test_rolling_five_false_positive_watch_not_rollback(tmp_path):
    con=init_db(tmp_path/"watch.sqlite3")
    # Relaxed promotion used to demonstrate one promotion regression false positive.
    _promotion(con,threshold=.85)
    rows=[
        ("CONFIRM_INDEPENDENT",.855), # promoted FP, Base correct
        ("CONFIRM_SYNDICATION",.95),
        ("CONFIRM_INDEPENDENT",.20),
        ("CONFIRM_SYNDICATION",.96),
        ("CONFIRM_INDEPENDENT",.10),
    ]
    last=None
    for i,(outcome,sim) in enumerate(rows,1):
        last=_observe(con,i,outcome,sim)
    w5=last["guard"]["windows"][0]
    assert w5["promotion_regression_count"]==1
    assert w5["status"]=="WATCH"
    assert last["rollback"] is None
    con.close()

def test_runtime_evaluations_are_persisted_for_5_10_20(tmp_path):
    con=init_db(tmp_path/"persist.sqlite3")
    _promotion(con)
    _observe(con,1,"CONFIRM_SYNDICATION",.95)
    hist=evaluation_history(con,1)
    assert len(hist)==3
    assert {x["window_size"] for x in hist}=={5,10,20}
    con.close()

def test_runtime_status_exposes_active_guard(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    _promotion(con)
    _observe(con,1,"CONFIRM_SYNDICATION",.95)
    s=runtime_guard_status(con)
    assert s["active_promotion"]["promotion_id"]==1
    assert s["active_guard"]["promotion_id"]==1
    assert s["active_guard"]["overall_status"]=="WARMING"
    con.close()

def test_v052_restricted_recovery_is_not_ready_after_only_five_safe_outcomes(tmp_path):
    con=init_db(tmp_path/"recovery.sqlite3")
    _promotion(con)
    _observe(con,1,"CONFIRM_SYNDICATION",.87,critical=True,status="VERIFIED")
    rc=recovery_cases(con)[0]
    for eid in range(10,14):
        r=add_recovery_shadow_outcome(
            con,rc["recovery_case_id"],eid,"SAFE")
        assert r["status"]=="OPEN"
    r=add_recovery_shadow_outcome(
        con,rc["recovery_case_id"],14,"SAFE")
    assert r["safe_shadow_outcome_count"]==5
    assert r["status"]=="OPEN"
    assert r["required_shadow_outcomes"]>=12
    con.close()

def test_recovery_unsafe_resets_safe_sequence(tmp_path):
    con=init_db(tmp_path/"reset.sqlite3")
    _promotion(con)
    _observe(con,1,"CONFIRM_SYNDICATION",.87,critical=True,status="VERIFIED")
    rid=recovery_cases(con)[0]["recovery_case_id"]
    for eid in (10,11,12):
        add_recovery_shadow_outcome(con,rid,eid,"SAFE")
    r=add_recovery_shadow_outcome(con,rid,13,"UNSAFE")
    assert r["safe_shadow_outcome_count"]==0
    assert r["status"]=="OPEN"
    con.close()

def test_v052_requalification_requires_adaptive_root_cause_gate(tmp_path):
    con=init_db(tmp_path/"requal.sqlite3")
    _promotion(con)
    _observe(con,1,"CONFIRM_SYNDICATION",.87,critical=True,status="VERIFIED")
    rid=recovery_cases(con)[0]["recovery_case_id"]
    with pytest.raises(ValueError):
        requalify_recovery(con,rid,"human","too early")
    for eid in range(20,25):
        add_recovery_shadow_outcome(con,rid,eid,"SAFE")
    with pytest.raises(ValueError,match="adaptive root-cause/recovery requirements"):
        requalify_recovery(con,rid,"human","five safe outcomes are not enough in v0.52")
    con.close()

def test_new_candidate_blocked_until_runtime_recovery_requalified(tmp_path):
    con=init_db(tmp_path/"block.sqlite3")
    _promotion(con)
    _observe(con,1,"CONFIRM_SYNDICATION",.87,critical=True,status="VERIFIED")
    # Runtime recovery gate is checked before calibration availability.
    with pytest.raises(ValueError,match="requires Human requalification"):
        create_candidate_from_latest_calibration(con)
    con.close()

def test_recovery_hold_does_not_advance_safe_count(tmp_path):
    con=init_db(tmp_path/"hold.sqlite3")
    _promotion(con)
    _observe(con,1,"CONFIRM_SYNDICATION",.87,critical=True,status="VERIFIED")
    rid=recovery_cases(con)[0]["recovery_case_id"]
    r=add_recovery_shadow_outcome(con,rid,2,"HOLD")
    assert r["safe_shadow_outcome_count"]==0
    assert r["status"]=="OPEN"
    con.close()

def test_rollback_is_idempotent_after_guard_trigger(tmp_path):
    con=init_db(tmp_path/"idempotent.sqlite3")
    _promotion(con)
    first=_observe(con,1,"CONFIRM_SYNDICATION",.87,critical=True,status="VERIFIED")
    assert first["rollback"]["rolled_back"] is True
    # With no active promotion, later observation is not attached to old promotion.
    second=_observe(con,2,"CONFIRM_SYNDICATION",.87,critical=True,status="VERIFIED")
    assert second["recorded"] is False
    assert len(recovery_cases(con))==1
    con.close()
