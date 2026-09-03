import json
from pathlib import Path
from src.database import init_db,seed_sources,upsert_event_instance
from src.evidence_service import apply_evidence_model
from src.daily_operations_summary import build_daily_operations_summary
from src.human_review_service import review_event
ROOT=Path(__file__).resolve().parents[1]

def test_approved_event_removed_from_review_queue(tmp_path):
    con=init_db(tmp_path/"q.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    eid=upsert_event_instance(con,"x","X","2026-08-27","OCHO","DISCOVERED")
    apply_evidence_model(con,event_instance_id=eid,date_value="2026-08-27",venue_value="OCHO",
                         time_value="20:00",fee_expected="13000",
                         occurrence_confirmed=True,primary_or_equivalent=False)
    s1=build_daily_operations_summary(con)
    assert any(x["type"]=="EVENT_REVIEW" for x in s1["human_review_queue"])
    review_event(con,event_instance_id=eid,action="APPROVE",reason="checked manually")
    s2=build_daily_operations_summary(con)
    assert not any(x["type"]=="EVENT_REVIEW" and x["event_instance_id"]==eid
                   for x in s2["human_review_queue"])
    con.close()
