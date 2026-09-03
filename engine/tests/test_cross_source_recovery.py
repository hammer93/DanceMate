from pathlib import Path
import json
from src.database import init_db, seed_sources, persist_raw_post, persist_events, enqueue_recovery, event_instance_summary
from src.collectors.base import RawPostRecord
from src.live_pipeline import process_discovered_post
from src.providers.snapshot import SnapshotCrossSourceProvider
from src.recovery_engine import run_recovery

ROOT=Path(__file__).resolve().parents[1]

def test_cross_source_recovery_merges_same_event(tmp_path):
    con=init_db(tmp_path/"r.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    p=RawPostRecord("SRC-D-001","DAUM_CAFE","https://x/origin","8/22 더 피스타 밀롱가",
        "8/22 더 피스타 밀롱가 홍대 PISTA 입장료 13,000원 DJ Hernan",acquisition_quality="BODY_ONLY")
    pid,_=persist_raw_post(con,p)
    res=process_discovered_post(con,p,"SECONDARY")
    persist_events(con,pid,res["events"]); con.commit()
    enqueue_recovery(con,pid,"SRC-D-001","8/22 더 피스타 밀롱가","FULL_BODY_UNAVAILABLE")
    provider=SnapshotCrossSourceProvider(ROOT/"data"/"cross_source_snapshots"/"naver-recovery-sample.json")
    out=run_recovery(con,provider)
    assert out[0]["status"]=="RESOLVED"
    assert out[0]["event_status"]=="VERIFIED"
    rows=[dict(r) for r in event_instance_summary(con)]
    assert len(rows)==1
    assert rows[0]["distinct_sources"]==2
    q=con.execute("SELECT state FROM recovery_queue").fetchone()
    assert q["state"]=="RESOLVED"
    con.close()
