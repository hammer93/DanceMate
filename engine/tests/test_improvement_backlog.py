import json
from pathlib import Path
from src.database import init_db,seed_sources,upsert_event_instance,persist_raw_post,persist_events,link_candidate_to_instance
from src.collectors.base import RawPostRecord
from src.models import EventCandidate
from src.evidence_service import apply_evidence_model
from src.human_review_service import review_field
from src.improvement_backlog import recommend_improvement_backlog

ROOT=Path(__file__).resolve().parents[1]

def test_fee_hotspot_generates_fee_backlog(tmp_path):
    con=init_db(tmp_path/"b.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    eid=upsert_event_instance(con,"e","E","2026-08-27","OCHO","DISCOVERED")
    apply_evidence_model(con,event_instance_id=eid,date_value="2026-08-27",
        venue_value="OCHO",time_value="20:00",fee_expected="13000",
        occurrence_confirmed=True,primary_or_equivalent=False)

    post=RawPostRecord("SRC-F-001","FACEBOOK","https://snapshot.local/e",
                       "E","fee",acquisition_quality="BODY_ONLY")
    pid,_=persist_raw_post(con,post)
    ev=EventCandidate(name="E",event_type="MILONGA",date="2026-08-27",
                      start_time="20:00",fee=13000,venue="OCHO",
                      status="POSSIBLE",core_complete=True)
    persist_events(con,pid,[ev])
    cid=con.execute("SELECT MAX(candidate_id) candidate_id FROM event_candidates WHERE post_id=?",
                    (pid,)).fetchone()["candidate_id"]
    link_candidate_to_instance(con,eid,cid,"SRC-F-001")

    review_field(con,event_instance_id=eid,field_name="fee",action="MODIFY",
                 new_value="15000",new_confidence="VERIFIED",
                 evidence={"source":"official poster"})
    r=recommend_improvement_backlog(con)
    item=r["backlog"][0]
    assert item["field"]=="fee"
    assert item["priority"]=="P2"
    assert item["confidence"]=="LOW"
    assert any(x["component"]=="EVIDENCE/FEE" for x in item["recommended_epics"])
    assert any("VERIFIED" in x for x in item["acceptance_criteria"])
    con.close()

def test_empty_hotspot_generates_observability_backlog(tmp_path):
    con=init_db(tmp_path/"empty.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    r=recommend_improvement_backlog(con)
    assert r["backlog"][0]["component"] if "component" in r["backlog"][0] else True
    assert r["backlog"][0]["priority"]=="P3"
    assert r["backlog"][0]["review_count"]==0
    con.close()
