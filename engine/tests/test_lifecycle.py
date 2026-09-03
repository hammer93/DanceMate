from pathlib import Path
import json
from src.database import init_db,seed_sources,upsert_event_instance,persist_event_revision,revision_history
from src.lifecycle import apply_revision,record_refresh,freshness_band
ROOT=Path(__file__).resolve().parents[1]
def test_update_cancel_history(tmp_path):
    con=init_db(tmp_path/"x.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    eid=upsert_event_instance(con,"x","x","2026-08-29","x","VERIFIED")
    persist_event_revision(con,event_instance_id=eid,candidate_id=None,source_id="SRC-D-001",
        revision_role="ORIGINAL",field_changes={},raw_summary="original")
    u=apply_revision(con,event_instance_id=eid,candidate_row=None,source_id="SRC-D-001",
        raw_text="오늘만 시작 시간 변경합니다. 21시 시작")
    c=apply_revision(con,event_instance_id=eid,candidate_row=None,source_id="SRC-D-001",
        raw_text="금일 밀롱가 취소합니다")
    assert u["status_after"]=="UPDATED"
    assert c["status_after"]=="CANCELLED"
    assert [x["revision_role"] for x in revision_history(con,eid)]==["ORIGINAL","UPDATE","CANCELLATION"]
    assert sum(x["is_current"] for x in revision_history(con,eid))==1
    con.close()
def test_critical_miss(tmp_path):
    con=init_db(tmp_path/"y.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    eid=upsert_event_instance(con,"y","y","2026-08-29","y","VERIFIED")
    r=record_refresh(con,event_instance_id=eid,scheduled_event_date="2026-08-29",hours_before_start=1,
        status_before="VERIFIED",status_after="VERIFIED",source_id="SRC-D-001",expected_cancellation=True)
    assert r["critical_miss"] is True and freshness_band(1)=="CRITICAL"
    con.close()
