import json
from pathlib import Path
from src.database import (
    init_db,seed_sources,upsert_event_instance,persist_raw_post,persist_events,link_candidate_to_instance
)
from src.collectors.base import RawPostRecord
from src.models import EventCandidate
from src.evidence_service import apply_evidence_model
from src.human_review_service import review_field
from src.improvement_lifecycle import (
    sync_recommended_backlog,change_backlog_status,backlog_detail
)

ROOT=Path(__file__).resolve().parents[1]

def _seed_hotspot(con):
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

def test_lifecycle_captures_before_after(tmp_path):
    con=init_db(tmp_path/"life.sqlite3")
    _seed_hotspot(con)
    sync=sync_recommended_backlog(con)
    bid=sync["created"][0]["backlog_id"]

    d1=change_backlog_status(con,bid,status="IN_PROGRESS",actor="dev")
    assert d1["backlog"]["status"]=="IN_PROGRESS"
    assert any(x["phase"]=="BEFORE" for x in d1["snapshots"])

    d2=change_backlog_status(con,bid,status="VERIFIED",actor="dev",note="done")
    assert d2["backlog"]["status"]=="VERIFIED"
    assert any(x["phase"]=="AFTER" for x in d2["snapshots"])
    assert len(d2["history"])==3
    assert d2["effect"] is not None
    con.close()
