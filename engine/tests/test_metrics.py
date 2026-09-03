from pathlib import Path
import json
from src.database import init_db,seed_sources,persist_raw_post,persist_acquisition_result,enqueue_recovery
from src.collectors.base import RawPostRecord
from src.models import AcquisitionResult
from src.metrics import calculate_source_metrics

ROOT=Path(__file__).resolve().parents[1]

def test_metrics_rates(tmp_path):
    con=init_db(tmp_path/"m.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    p1=RawPostRecord("SRC-N-001","NAVER_BLOG","https://x/1","A","B",acquisition_quality="METADATA_ONLY")
    p2=RawPostRecord("SRC-N-001","NAVER_BLOG","https://x/2","C","D",acquisition_quality="METADATA_ONLY")
    id1,_=persist_raw_post(con,p1); id2,_=persist_raw_post(con,p2)
    persist_acquisition_result(con,AcquisitionResult("SRC-N-001",id1,p1.source_url,"FULL",200,p1.source_url,body_text="x"*50,body_chars=50,images=["a.jpg"],poster_candidates=["a.jpg"]))
    persist_acquisition_result(con,AcquisitionResult("SRC-N-001",id2,p2.source_url,"PARTIAL",200,p2.source_url,body_text="x",body_chars=1,error_code="BODY_UNAVAILABLE"))
    enqueue_recovery(con,id2,"SRC-N-001","C","BODY_UNAVAILABLE")
    rows=calculate_source_metrics(con)
    r=[x for x in rows if x["source_id"]=="SRC-N-001"][0]
    assert r["acquisition_attempts"]==2
    assert r["full_body_rate"]==0.5
    assert r["poster_rate"]==0.5
    assert r["human_review_count"]>=1
    con.close()
