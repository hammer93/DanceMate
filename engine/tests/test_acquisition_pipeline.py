from pathlib import Path
import json
from src.database import init_db, seed_sources, persist_raw_post
from src.collectors.base import RawPostRecord
from src.acquirers.snapshot import SnapshotDaumPostAcquirer
from src.acquisition_pipeline import acquire_pending_daum

ROOT=Path(__file__).resolve().parents[1]

def test_acquisition_upgrade_and_recovery(tmp_path):
    con=init_db(tmp_path/"t.sqlite3")
    sources=json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8"))
    seed_sources(con,sources)
    # published_at is what places a bare "8/22" in a year. Every collector
    # supplies it, so a post without one is not a shape production produces.
    p1=RawPostRecord("SRC-D-001","DAUM_CAFE","https://snapshot.local/daum/pista",
        "8/22 더 피스타 밀롱가","snippet",published_at="2026-08-18",
        acquisition_quality="METADATA_ONLY")
    p2=RawPostRecord("SRC-D-001","DAUM_CAFE","https://snapshot.local/daum/login",
        "8/29 테스트 밀롱가","snippet",published_at="2026-08-25",
        acquisition_quality="METADATA_ONLY")
    persist_raw_post(con,p1); persist_raw_post(con,p2)
    acq=SnapshotDaumPostAcquirer(ROOT/"data"/"acquisition_snapshots",{
        p1.source_url:"daum-full-pista.html",p2.source_url:"daum-partial-login-shell.html"})
    rows=acquire_pending_daum(con,mode="snapshot",acquirer=acq)
    by={r["url"]:r for r in rows}
    assert by[p1.source_url]["status"]=="FULL" and by[p1.source_url]["upgraded"] is True
    ev=con.execute("SELECT status,core_complete,start_time,end_time,fee FROM event_candidates WHERE post_id=(SELECT post_id FROM raw_posts WHERE source_url=?)",(p1.source_url,)).fetchone()
    assert ev["status"]=="VERIFIED" and ev["core_complete"]==1
    assert (ev["start_time"],ev["end_time"],ev["fee"])==("19:00","23:00",13000)
    assert by[p2.source_url]["status"]=="PARTIAL"
    q=con.execute("SELECT reason,state FROM recovery_queue WHERE post_id=(SELECT post_id FROM raw_posts WHERE source_url=?)",(p2.source_url,)).fetchone()
    assert q["state"]=="PENDING" and q["reason"]=="BODY_UNAVAILABLE"
    con.close()
