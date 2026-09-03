from src.database import init_db,create_daily_run,finish_daily_run
from src.change_traceability import register_change,link_and_measure_change,change_detail
from src.daily_metric_snapshot import capture_daily_metric_snapshot

def test_change_daily_run_trace(tmp_path):
    con=init_db(tmp_path/"c.sqlite3")
    c=register_change(con,title="rule change",component="EVIDENCE/FEE",
                      version_label="v0.25",actor="dev")
    d1=create_daily_run(con,run_date="2026-08-27",mode="snapshot")
    finish_daily_run(con,d1,status="PASS",metric_status="PASS",report_status="PASS")
    capture_daily_metric_snapshot(con,daily_run_id=d1,run_date="2026-08-27")
    link_and_measure_change(con,change_id=c["change_id"],daily_run_id=d1,relation="BASELINE")

    d2=create_daily_run(con,run_date="2026-08-28",mode="snapshot")
    finish_daily_run(con,d2,status="PASS",metric_status="PASS",report_status="PASS")
    capture_daily_metric_snapshot(con,daily_run_id=d2,run_date="2026-08-28")
    link_and_measure_change(con,change_id=c["change_id"],daily_run_id=d2,
                            relation="POST_CHANGE",baseline_daily_run_id=d1)

    detail=change_detail(con,c["change_id"])
    assert len(detail["daily_run_links"])==2
    assert len(detail["metric_effects"])==2
    assert detail["comparison"] is not None
    assert detail["comparison"]["before_daily_run_id"]==d1
    assert detail["comparison"]["after_daily_run_id"]==d2
    con.close()
