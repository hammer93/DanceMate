from pathlib import Path
import json
from src.database import init_db,seed_sources,upsert_event_instance,get_event_field_states
from src.evidence_service import apply_evidence_model
ROOT=Path(__file__).resolve().parents[1]

def test_day1_high_confidence_expected_fee(tmp_path):
    con=init_db(tmp_path/"e.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    eid=upsert_event_instance(con,"x","Sueño Dulce","2026-08-27","La Ventana","DISCOVERED")
    r=apply_evidence_model(con,event_instance_id=eid,date_value="2026-08-27",venue_value="La Ventana",time_value="20:00",
        fee_expected="11000",occurrence_confirmed=True,primary_or_equivalent=False)
    assert r["event_confidence"]=="HIGH_CONFIDENCE"
    assert r["fields"]["fee"]["confidence"]=="EXPECTED"
    fields={x["field_name"]:x for x in get_event_field_states(con,eid)}
    assert fields["fee"]["verified_value"] is None
    con.close()
