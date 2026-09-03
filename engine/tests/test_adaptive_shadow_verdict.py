import json
from src.database import (
    init_db,create_daily_run,finish_daily_run,persist_daily_metric_snapshot,
    create_backlog_item,upsert_adaptive_weight_profile,
    adaptive_shadow_rows,adaptive_weight_observations
)
from src.daily_metric_snapshot import canonical_payload_hash
from src.change_traceability import (
    register_change,link_and_measure_change,evaluate_change_effect,change_detail
)
from src.goal_weighting import BASE_PROFILES

def _payload(correction,access,coverage=1.0,known=1.0,yield_rate=1.0,recovery=1.0):
    verified=int(round(coverage*100))
    expected=max(0,int(round((known-coverage)*100)))
    unknown=max(0,100-verified-expected)
    return {
      "event_confidence_distribution":{},
      "field_confidence_distribution":{
        "VERIFIED":verified,"EXPECTED":expected,"UNKNOWN":unknown},
      "source_operations":[{
        "source_id":"SRC-X",
        "access_failure_rate":access,
        "source_yield_rate":yield_rate,
        "recovery_success_rate":recovery}],
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

def _field_backlog(con):
    weights=BASE_PROFILES["FIELD_QUALITY"]
    bid,_=create_backlog_item(
        con,source_id="SRC-X",field_name="fee",title="fee quality",
        priority="P1",sample_confidence="HIGH",hotspot_score=9,
        goal_profile="FIELD_QUALITY",goal_weights=weights,opened_by="test")
    return bid

def test_base_verdict_remains_production_while_shadow_diverges(tmp_path):
    con=init_db(tmp_path/"shadow.sqlite3")
    bid=_field_backlog(con)

    base=_daily(con,"2026-08-27",_payload(.5,.2))
    c=register_change(
        con,backlog_id=bid,title="fee fix",component="EVIDENCE/FEE",actor="dev")
    assert c["auto_baseline"]["daily_run_id"]==base

    # Pre-existing adaptive suggestion from PRIOR observations only.
    adaptive=dict(BASE_PROFILES["FIELD_QUALITY"])
    adaptive["correction_rate"]=3.75
    adaptive["access_failure_rate"]=0.375
    upsert_adaptive_weight_profile(
        con,goal_profile="FIELD_QUALITY",
        base_weights=BASE_PROFILES["FIELD_QUALITY"],
        adaptive_weights=adaptive,sample_count=12)

    # correction improves 0.1, access worsens 0.5:
    # Base score ~ +0.09 => INCONCLUSIVE
    # Adaptive shadow score ~ +0.33 => IMPROVED
    post=_daily(con,"2026-08-28",_payload(.4,.7))
    link_and_measure_change(
        con,change_id=c["change_id"],daily_run_id=post,
        relation="POST_CHANGE",baseline_daily_run_id=base)

    r=evaluate_change_effect(con,c["change_id"])
    assert r["verdict"]=="INCONCLUSIVE"
    assert r["shadow"]["verdict"]=="IMPROVED"
    assert r["shadow"]["agrees_with_base"] is False
    assert r["shadow"]["adaptive_sample_count"]==12
    assert r["metric_weights"]["correction_rate"]==3.0
    assert r["shadow"]["metric_weights"]["correction_rate"]==3.75

    detail=change_detail(con,c["change_id"])
    assert detail["latest_shadow"]["base_verdict"]=="INCONCLUSIVE"
    assert detail["latest_shadow"]["shadow_verdict"]=="IMPROVED"
    assert detail["shadow_agreement"]["agreement_rate"]==0.0
    con.close()

def test_shadow_is_idempotent_for_same_change_pair(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3")
    bid=_field_backlog(con)
    base=_daily(con,"2026-08-27",_payload(.5,.2))
    c=register_change(con,backlog_id=bid,title="fee fix",component="EVIDENCE/FEE")
    post=_daily(con,"2026-08-28",_payload(.3,.2))
    link_and_measure_change(
        con,change_id=c["change_id"],daily_run_id=post,
        relation="POST_CHANGE",baseline_daily_run_id=base)

    evaluate_change_effect(con,c["change_id"])
    shadow_count_1=len(adaptive_shadow_rows(con,c["change_id"]))
    obs_count_1=len(adaptive_weight_observations(con,"FIELD_QUALITY"))

    evaluate_change_effect(con,c["change_id"])
    shadow_count_2=len(adaptive_shadow_rows(con,c["change_id"]))
    obs_count_2=len(adaptive_weight_observations(con,"FIELD_QUALITY"))

    assert shadow_count_1==1
    assert shadow_count_2==1
    assert obs_count_2==obs_count_1
    con.close()

def test_shadow_agrees_when_weights_do_not_change_outcome(tmp_path):
    con=init_db(tmp_path/"agree.sqlite3")
    bid=_field_backlog(con)
    base=_daily(con,"2026-08-27",_payload(.8,.5))
    c=register_change(con,backlog_id=bid,title="fee fix",component="EVIDENCE/FEE")

    adaptive=dict(BASE_PROFILES["FIELD_QUALITY"])
    adaptive["correction_rate"]=3.5
    upsert_adaptive_weight_profile(
        con,goal_profile="FIELD_QUALITY",
        base_weights=BASE_PROFILES["FIELD_QUALITY"],
        adaptive_weights=adaptive,sample_count=11)

    post=_daily(con,"2026-08-28",_payload(.2,.3))
    link_and_measure_change(
        con,change_id=c["change_id"],daily_run_id=post,
        relation="POST_CHANGE",baseline_daily_run_id=base)

    r=evaluate_change_effect(con,c["change_id"])
    assert r["verdict"]=="IMPROVED"
    assert r["shadow"]["verdict"]=="IMPROVED"
    assert r["shadow"]["agrees_with_base"] is True
    con.close()
