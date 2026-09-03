from src.database import init_db,create_daily_run,finish_daily_run
from src.daily_metric_snapshot import capture_daily_metric_snapshot,load_snapshot_payload,verify_snapshot_integrity

def test_snapshot_immutable(tmp_path):
    con=init_db(tmp_path/"s.sqlite3")
    rid=create_daily_run(con,run_date="2026-08-27",mode="snapshot")
    finish_daily_run(con,rid,status="PASS",metric_status="PASS",report_status="PASS")
    s1=capture_daily_metric_snapshot(con,daily_run_id=rid,run_date="2026-08-27")
    assert s1["already_exists"] is False
    con.execute("""INSERT INTO human_review_actions(
      action_uuid,review_type,target_id,event_instance_id,field_name,recovery_id,
      action,actor,reason,old_value_json,new_value_json,evidence_json,created_at)
      VALUES('later','EVENT',1,1,NULL,NULL,'HOLD','tester','later',NULL,NULL,'{}',datetime('now'))""")
    con.commit()
    loaded=load_snapshot_payload(con,rid)
    assert loaded["payload"]["human_in_loop_metrics"]["review_count"]==0
    s2=capture_daily_metric_snapshot(con,daily_run_id=rid,run_date="2026-08-27")
    assert s2["already_exists"] is True
    assert s2["snapshot_id"]==s1["snapshot_id"]
    assert verify_snapshot_integrity(con,rid)["valid"] is True
    con.close()
