from pathlib import Path
import json
from src.database import init_db,seed_sources,persist_raw_post,persist_events,enqueue_recovery,event_instance_summary
from src.collectors.base import RawPostRecord
from src.live_pipeline import process_discovered_post
from src.providers.naver_snapshot import NaverApiSnapshotProvider
from src.recovery_engine import run_recovery

ROOT=Path(__file__).resolve().parents[1]

def test_naver_api_snapshot_recovery_resolves_pista(tmp_path):
    con=init_db(tmp_path/"n.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    p=RawPostRecord("SRC-D-001","DAUM_CAFE","https://x/pista-origin","8/22 더 피스타 밀롱가",
        "8/22 더 피스타 밀롱가 홍대 PISTA 입장료 13,000원 DJ Hernan",
        published_at="2026-08-18",acquisition_quality="BODY_ONLY")
    pid,_=persist_raw_post(con,p)
    r=process_discovered_post(con,p,"SECONDARY")
    persist_events(con,pid,r["events"]); con.commit()
    enqueue_recovery(con,pid,"SRC-D-001","8/22 더 피스타 밀롱가","FULL_BODY_UNAVAILABLE")
    out=run_recovery(con,NaverApiSnapshotProvider(ROOT/"data"/"collector_snapshots"))
    assert out[0]["status"]=="RESOLVED"
    assert out[0]["event_status"]=="VERIFIED"
    inst=[dict(x) for x in event_instance_summary(con)]
    assert len(inst)==1 and inst[0]["distinct_sources"]>=2
    con.close()
