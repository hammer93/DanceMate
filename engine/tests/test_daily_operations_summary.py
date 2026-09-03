import json
from pathlib import Path
from src.database import init_db,seed_sources,upsert_event_instance
from src.evidence_service import apply_evidence_model
from src.daily_operations_summary import build_daily_operations_summary
ROOT=Path(__file__).resolve().parents[1]

def test_yellow_for_review(tmp_path):
    con=init_db(tmp_path/"ops.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    eid=upsert_event_instance(con,"x","Sueño Dulce","2026-08-27","La Ventana","DISCOVERED")
    apply_evidence_model(con,event_instance_id=eid,date_value="2026-08-27",
      venue_value="La Ventana",time_value="20:00",fee_expected="11000",
      occurrence_confirmed=True,primary_or_equivalent=False)
    s=build_daily_operations_summary(con)
    assert s["event_confidence_distribution"]["HIGH_CONFIDENCE"]==1
    assert s["field_confidence_distribution"]["EXPECTED"]==1
    assert s["p0_count"]==0 and s["health"]=="YELLOW"
    con.close()

def test_red_on_false_verified(tmp_path):
    con=init_db(tmp_path/"ops2.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    upsert_event_instance(con,"bad","Bad","2026-08-27","PISTA","VERIFIED")
    s=build_daily_operations_summary(con)
    assert s["p0_count"]>=1 and s["health"]=="RED"
    con.close()
