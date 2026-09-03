from src.database import init_db,create_daily_run,finish_daily_run,persist_daily_metric_snapshot,create_backlog_item
from src.daily_metric_snapshot import canonical_payload_hash
from src.change_traceability import register_change,link_and_measure_change,evaluate_change_effect,change_detail

def _payload(correction,access,coverage,known,yield_rate,recovery):
    verified=int(round(coverage*100))
    expected=max(0,int(round((known-coverage)*100)))
    unknown=max(0,100-verified-expected)
    return {
      "event_confidence_distribution":{},
      "field_confidence_distribution":{"VERIFIED":verified,"EXPECTED":expected,"UNKNOWN":unknown},
      "source_operations":[{"source_id":"SRC-X","access_failure_rate":access,
                            "source_yield_rate":yield_rate,"recovery_success_rate":recovery}],
      "human_in_loop_metrics":{"manual_correction_rate":correction},
      "correction_hotspots":{"source_field_hotspots":[
        {"source_id":"SRC-X","field":"fee","correction_rate":correction}]},
      "improvement_backlog":{},"p0_count":0,"health":"GREEN"
    }

def _daily(con,date,payload):
    rid=create_daily_run(con,run_date=date,mode="snapshot")
    finish_daily_run(con,rid,status="PASS",metric_status="PASS",report_status="PASS")
    persist_daily_metric_snapshot(con,daily_run_id=rid,run_date=date,payload=payload,
                                  immutable_hash=canonical_payload_hash(payload))
    return rid

def _backlog(con):
    bid,_=create_backlog_item(con,source_id="SRC-X",field_name="fee",title="fee",
                              priority="P1",sample_confidence="HIGH",
                              hotspot_score=9,opened_by="test")
    return bid

def test_auto_baseline_and_improved_verdict(tmp_path):
    con=init_db(tmp_path/"v.sqlite3"); bid=_backlog(con)
    base=_daily(con,"2026-08-27",_payload(.6,.5,.5,.6,.4,.4))
    c=register_change(con,backlog_id=bid,title="fee fix",actor="dev")
    assert c["auto_baseline"]["daily_run_id"]==base
    post=_daily(con,"2026-08-28",_payload(.2,.3,.8,.9,.7,.8))
    link_and_measure_change(con,change_id=c["change_id"],daily_run_id=post,
                            relation="POST_CHANGE",baseline_daily_run_id=base)
    v=evaluate_change_effect(con,c["change_id"])
    assert v["verdict"]=="IMPROVED"
    assert not v["regressed_metrics"]
    assert len(v["improved_metrics"])>=2
    assert change_detail(con,c["change_id"])["latest_verdict"]["verdict"]=="IMPROVED"
    con.close()

def test_regressed_verdict(tmp_path):
    con=init_db(tmp_path/"r.sqlite3"); bid=_backlog(con)
    base=_daily(con,"2026-08-27",_payload(.2,.2,.8,.9,.8,.8))
    c=register_change(con,backlog_id=bid,title="bad fix",actor="dev")
    post=_daily(con,"2026-08-28",_payload(.7,.7,.5,.6,.4,.3))
    link_and_measure_change(con,change_id=c["change_id"],daily_run_id=post,
                            relation="POST_CHANGE",baseline_daily_run_id=base)
    assert evaluate_change_effect(con,c["change_id"])["verdict"]=="REGRESSED"
    con.close()

def test_inconclusive_no_material_change(tmp_path):
    con=init_db(tmp_path/"i.sqlite3"); bid=_backlog(con)
    base=_daily(con,"2026-08-27",_payload(.2,.2,.8,.9,.8,.8))
    c=register_change(con,backlog_id=bid,title="neutral",actor="dev")
    post=_daily(con,"2026-08-28",_payload(.2,.2,.8,.9,.8,.8))
    link_and_measure_change(con,change_id=c["change_id"],daily_run_id=post,
                            relation="POST_CHANGE",baseline_daily_run_id=base)
    assert evaluate_change_effect(con,c["change_id"])["verdict"]=="INCONCLUSIVE"
    con.close()
