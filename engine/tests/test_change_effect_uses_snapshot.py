from src.database import init_db,create_daily_run,finish_daily_run
from src.daily_metric_snapshot import capture_daily_metric_snapshot
from src.change_traceability import register_change,link_and_measure_change

def test_change_effect_reads_snapshot(tmp_path):
    con=init_db(tmp_path/"c2.sqlite3")
    c=register_change(con,title="x",actor="dev")
    rid=create_daily_run(con,run_date="2026-08-27",mode="snapshot")
    finish_daily_run(con,rid,status="PASS",metric_status="PASS",report_status="PASS")
    capture_daily_metric_snapshot(con,daily_run_id=rid,run_date="2026-08-27")
    r=link_and_measure_change(con,change_id=c["change_id"],daily_run_id=rid)
    assert r["metrics"]["snapshot_id"] is not None
    assert r["metrics"]["immutable_hash"]
    con.close()
