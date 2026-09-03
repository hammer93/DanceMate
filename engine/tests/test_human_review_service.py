import json
from pathlib import Path
import pytest
from src.database import init_db,seed_sources,upsert_event_instance,get_human_review_state
from src.evidence_service import apply_evidence_model
from src.human_review_service import (
    review_event,review_field,review_recovery,field_review_key,event_review_key
)
ROOT=Path(__file__).resolve().parents[1]

def _con(tmp_path):
    con=init_db(tmp_path/"r.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    return con

def test_modify_field_verified_requires_evidence(tmp_path):
    con=_con(tmp_path)
    eid=upsert_event_instance(con,"x","A","2026-08-27","PISTA","DISCOVERED")
    apply_evidence_model(con,event_instance_id=eid,date_value="2026-08-27",venue_value="PISTA",
                         time_value="20:00",fee_expected="13000",
                         occurrence_confirmed=True,primary_or_equivalent=False)
    with pytest.raises(ValueError):
        review_field(con,event_instance_id=eid,field_name="fee",action="MODIFY",
                     new_value="15000",new_confidence="VERIFIED")
    r=review_field(con,event_instance_id=eid,field_name="fee",action="MODIFY",
                   new_value="15000",new_confidence="VERIFIED",
                   evidence={"source":"manual poster"})
    assert r["new"]["confidence"]=="VERIFIED"
    assert r["new"]["verified_value"]=="15000"
    st=get_human_review_state(con,field_review_key(eid,"fee"))
    assert st["state"]=="MODIFIED"
    con.close()

def test_event_hold_audited(tmp_path):
    con=_con(tmp_path)
    eid=upsert_event_instance(con,"e","E","2026-08-27","OCHO","POSSIBLE")
    r=review_event(con,event_instance_id=eid,action="HOLD",reason="need organizer post")
    assert r["state"]=="HELD"
    st=get_human_review_state(con,event_review_key(eid))
    assert st["state"]=="HELD"
    con.close()
