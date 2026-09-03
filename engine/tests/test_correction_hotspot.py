import json
from pathlib import Path
from src.database import (
    init_db,seed_sources,upsert_event_instance,persist_raw_post,persist_events,
    link_candidate_to_instance
)
from src.collectors.base import RawPostRecord
from src.models import EventCandidate
from src.evidence_service import apply_evidence_model
from src.human_review_service import review_field
from src.correction_hotspot import analyze_correction_hotspots

ROOT=Path(__file__).resolve().parents[1]

def test_hotspot_by_source_field(tmp_path):
    con=init_db(tmp_path/"h.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))

    eid=upsert_event_instance(con,"e1","E1","2026-08-27","OCHO","DISCOVERED")
    apply_evidence_model(con,event_instance_id=eid,date_value="2026-08-27",
        venue_value="OCHO",time_value="20:00",fee_expected="13000",
        occurrence_confirmed=True,primary_or_equivalent=False)

    post=RawPostRecord("SRC-F-001","FACEBOOK","https://snapshot.local/ocho",
                       "OCHO fee","2026-08-27 fee 13000",acquisition_quality="BODY_ONLY")
    pid,_=persist_raw_post(con,post)
    ev=EventCandidate(name="E1",event_type="MILONGA",date="2026-08-27",
                      start_time="20:00",fee=13000,venue="OCHO",
                      status="POSSIBLE",core_complete=True)
    persist_events(con,pid,[ev])
    cid=con.execute("SELECT MAX(candidate_id) candidate_id FROM event_candidates WHERE post_id=?",
                    (pid,)).fetchone()["candidate_id"]
    link_candidate_to_instance(con,eid,cid,"SRC-F-001")

    review_field(con,event_instance_id=eid,field_name="fee",action="MODIFY",
        new_value="15000",new_confidence="VERIFIED",
        evidence={"source":"official poster"})

    a=analyze_correction_hotspots(con)
    assert a["field_hotspots"][0]["field"]=="fee"
    assert a["field_hotspots"][0]["correction_rate"]==1.0
    top=a["top_hotspots"][0]
    assert top["source_id"]=="SRC-F-001"
    assert top["field"]=="fee"
    assert top["modifications"]==1
    assert top["priority"]=="P2"
    con.close()
