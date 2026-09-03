import json
from pathlib import Path
from src.database import init_db,seed_sources,persist_raw_post,latest_lineage_for_post,recovery_parent_for_post
from src.collectors.base import RawPostRecord
from src.discovery_observer import run_discovery_with_lineage,record_discovery_persist_result
from src.generic_acquisition_pipeline import acquire_posts
from src.acquirers.snapshot_generic import SnapshotGenericPostAcquirer

ROOT=Path(__file__).resolve().parents[1]

def test_lineage_inferred_across_separate_steps(tmp_path):
    con=init_db(tmp_path/"cli.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    p=RawPostRecord("SRC-N-001","NAVER_BLOG","https://snapshot.local/naver/blog/pista",
                    "8/22 PISTA","snippet",acquisition_quality="METADATA_ONLY")
    d=run_discovery_with_lineage(con,source_id=p.source_id,query="밀롱가",collector_callable=lambda:[p])
    pid,is_new=persist_raw_post(con,p)
    record_discovery_persist_result(con,lineage_id=d["lineage_id"],observation_id=d["observation_id"],
        post_id=pid,source_id=p.source_id,source_url=p.source_url,is_new=is_new)

    # Separate acquisition call: no lineage_map supplied.
    row=con.execute("""SELECT rp.post_id,rp.source_id,rp.source_url,rp.title,rp.body,rp.acquisition_quality,s.platform
                       FROM raw_posts rp JOIN sources s ON s.source_id=rp.source_id WHERE rp.post_id=?""",(pid,)).fetchone()
    acq=SnapshotGenericPostAcquirer(ROOT/"data"/"acquisition_snapshots",
                                    {p.source_url:"naver-blog-full.html"})
    res=acquire_posts(con,[row],mode="snapshot",acquirer=acq)
    assert res[0]["lineage_id"]==d["lineage_id"]
    assert res[0]["observation_id"]!=d["observation_id"]
    parent=recovery_parent_for_post(con,pid)
    assert parent["lineage_id"]==d["lineage_id"]
    assert parent["observation_id"]==res[0]["observation_id"]
    con.close()
