import json
from pathlib import Path
from src.database import init_db,seed_sources,upsert_event_instance
from src.evidence_service import apply_evidence_model
from src.human_review_service import review_event,review_field
from src.human_review_metrics import calculate_human_review_metrics

ROOT=Path(__file__).resolve().parents[1]

def test_human_review_metrics(tmp_path):
    con=init_db(tmp_path/"hm.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    eid=upsert_event_instance(con,"x","X","2026-08-27","OCHO","DISCOVERED")
    apply_evidence_model(con,event_instance_id=eid,date_value="2026-08-27",venue_value="OCHO",
                         time_value="20:00",fee_expected="13000",
                         occurrence_confirmed=True,primary_or_equivalent=False)
    review_event(con,event_instance_id=eid,action="HOLD",reason="need source")
    review_field(con,event_instance_id=eid,field_name="fee",action="MODIFY",
                 new_value="15000",new_confidence="VERIFIED",
                 evidence={"source":"official poster"})
    m=calculate_human_review_metrics(con)
    assert m["review_count"]==2
    assert m["action_distribution"]["HOLD"]==1
    assert m["action_distribution"]["MODIFY"]==1
    assert m["manual_correction_rate"]==0.5
    assert m["machine_human_disagreement_rate"]==0.5
    assert m["manual_verified_override_rate"]==0.5
    assert m["hold_rate"]==0.5
    assert m["reviewer_reliability_status"]=="PROXY_ONLY"
    assert len(m["reviewers"])==1
    con.close()
