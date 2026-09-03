import json
from pathlib import Path
from src.database import init_db,seed_sources,upsert_event_instance
from src.evidence_service import apply_evidence_model
from src.human_review_service import review_event
from src.daily_operations_summary import build_daily_operations_summary

ROOT=Path(__file__).resolve().parents[1]

def test_ops_includes_human_metrics(tmp_path):
    con=init_db(tmp_path/"ops.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    eid=upsert_event_instance(con,"x","X","2026-08-27","OCHO","POSSIBLE")
    apply_evidence_model(con,event_instance_id=eid,date_value="2026-08-27",
                         venue_value="OCHO",time_value="20:00",
                         fee_expected="13000",occurrence_confirmed=True,
                         primary_or_equivalent=False)
    review_event(con,event_instance_id=eid,action="APPROVE",
                 reason="checked",evidence={"source":"manual check"})
    s=build_daily_operations_summary(con)
    assert "human_in_loop_metrics" in s
    assert s["human_in_loop_metrics"]["review_count"]==1
    assert s["human_in_loop_metrics"]["approval_rate"]==1.0
    con.close()
