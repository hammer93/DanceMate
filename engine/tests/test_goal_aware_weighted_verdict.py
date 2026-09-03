from src.database import init_db,create_daily_run,finish_daily_run,persist_daily_metric_snapshot,create_backlog_item
from src.daily_metric_snapshot import canonical_payload_hash
from src.change_traceability import register_change,link_and_measure_change,evaluate_change_effect,metric_weights_for_change

def _payload(correction,access,coverage,known,yield_rate,recovery):
    verified=int(round(coverage*100)); expected=max(0,int(round((known-coverage)*100))); unknown=max(0,100-verified-expected)
    return {"event_confidence_distribution":{},"field_confidence_distribution":{"VERIFIED":verified,"EXPECTED":expected,"UNKNOWN":unknown},
      "source_operations":[{"source_id":"SRC-X","access_failure_rate":access,"source_yield_rate":yield_rate,"recovery_success_rate":recovery}],
      "human_in_loop_metrics":{"manual_correction_rate":correction},
      "correction_hotspots":{"source_field_hotspots":[{"source_id":"SRC-X","field":"fee","correction_rate":correction}]},
      "improvement_backlog":{},"p0_count":0,"health":"GREEN"}

def _daily(con,date,payload):
    rid=create_daily_run(con,run_date=date,mode="snapshot"); finish_daily_run(con,rid,status="PASS",metric_status="PASS",report_status="PASS")
    persist_daily_metric_snapshot(con,daily_run_id=rid,run_date=date,payload=payload,immutable_hash=canonical_payload_hash(payload)); return rid

def test_field_quality_profile(tmp_path):
    con=init_db(tmp_path/"f.sqlite3")
    bid,_=create_backlog_item(con,source_id="SRC-X",field_name="fee",title="fee",priority="P1",sample_confidence="HIGH",hotspot_score=9,opened_by="t")
    base=_daily(con,"2026-08-27",_payload(.8,.2,.4,.5,.8,.8))
    c=register_change(con,backlog_id=bid,title="fee fix",component="EVIDENCE/FEE",actor="dev")
    post=_daily(con,"2026-08-28",_payload(.3,.3,.8,.9,.7,.7))
    link_and_measure_change(con,change_id=c["change_id"],daily_run_id=post,relation="POST_CHANGE",baseline_daily_run_id=base)
    profile,weights=metric_weights_for_change(con,c["change_id"]); assert profile=="FIELD_QUALITY" and weights["correction_rate"]==3.0
    v=evaluate_change_effect(con,c["change_id"]); assert v["weighted_score"]>0 and v["verdict"]=="IMPROVED"; con.close()

def test_source_access_profile(tmp_path):
    con=init_db(tmp_path/"s.sqlite3")
    bid,_=create_backlog_item(con,source_id="SRC-X",field_name=None,title="source",priority="P1",sample_confidence="HIGH",hotspot_score=9,opened_by="t")
    base=_daily(con,"2026-08-27",_payload(.5,.2,.5,.6,.8,.8))
    c=register_change(con,backlog_id=bid,title="collector fix",component="COLLECTOR/NAVER_BLOG",actor="dev")
    post=_daily(con,"2026-08-28",_payload(.3,.7,.8,.9,.4,.3))
    link_and_measure_change(con,change_id=c["change_id"],daily_run_id=post,relation="POST_CHANGE",baseline_daily_run_id=base)
    profile,_=metric_weights_for_change(con,c["change_id"]); assert profile=="SOURCE_ACCESS"
    v=evaluate_change_effect(con,c["change_id"]); assert v["weighted_score"]<0 and v["verdict"]=="REGRESSED"; con.close()
