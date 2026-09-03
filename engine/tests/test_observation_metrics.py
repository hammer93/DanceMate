from pathlib import Path
import json
from src.database import init_db,start_observation,finish_observation
from src.observation_metrics import calculate_observation_metrics

def test_observation_metrics(tmp_path):
    con=init_db(tmp_path/"o.sqlite3")
    oid=start_observation(con,run_type="DISCOVERY",source_id="S1")
    finish_observation(con,oid,result_status="PASS",discovered_count=4,rawpost_new_count=3,rawpost_duplicate_count=1)
    oid=start_observation(con,run_type="ACQUISITION",source_id="S1")
    finish_observation(con,oid,result_status="PASS",acquisition_attempt_count=2,acquisition_success_count=1,acquisition_failure_count=1)
    oid=start_observation(con,run_type="RECOVERY",source_id="S1")
    finish_observation(con,oid,result_status="PASS",recovery_attempt_count=2,recovery_success_count=1)
    m=calculate_observation_metrics(con)["overall"]
    assert m["source_yield_rate"]==0.75
    assert m["access_failure_rate"]==0.5
    assert m["recovery_success_rate"]==0.5
    con.close()
