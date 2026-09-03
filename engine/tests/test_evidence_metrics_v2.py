from pathlib import Path
import json
from src.database import init_db,seed_sources,upsert_event_instance
from src.evidence_service import apply_evidence_model
from src.evidence_metrics_v2 import calculate_metrics_v2
ROOT=Path(__file__).resolve().parents[1]
def test_metrics_v2_field_coverage(tmp_path):
    con=init_db(tmp_path/"m.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    a=upsert_event_instance(con,"a","A","2026-08-27","PISTA","DISCOVERED")
    apply_evidence_model(con,event_instance_id=a,date_value="2026-08-27",venue_value="PISTA",time_value="20:00",
        fee_verified="13000",fee_expected="13000",occurrence_confirmed=True,primary_or_equivalent=True)
    b=upsert_event_instance(con,"b","B","2026-08-27","OCHO","DISCOVERED")
    apply_evidence_model(con,event_instance_id=b,date_value="2026-08-27",venue_value="OCHO",time_value="20:30",
        fee_expected="15000",occurrence_confirmed=True,primary_or_equivalent=False)
    o=calculate_metrics_v2(con,"test")[0]
    assert o["field_total"]==8
    assert o["field_verified"]==7
    assert o["field_expected"]==1
    assert o["field_coverage_rate"]==0.875
    assert o["known_field_rate"]==1.0
    assert o["expected_to_verified_promotion_rate"]==0.5
    con.close()
