from .database import persist_raw_post,persist_events,lineage_trace,close_lineage
from .collectors.base import RawPostRecord
from .discovery_observer import run_discovery_with_lineage,record_discovery_persist_result
from .live_pipeline import process_discovered_post
from .generic_acquisition_pipeline import acquire_posts
from .acquirers.snapshot_generic import SnapshotGenericPostAcquirer
from .recovery_engine import run_recovery_with_lineage
from .providers.naver_snapshot import NaverApiSnapshotProvider

def run_live_lineage_snapshot(con, root):
    d=run_discovery_with_lineage(con,source_id="SRC-D-001",query="8/22 더 피스타 밀롱가",
        collector_callable=lambda:[RawPostRecord("SRC-D-001","DAUM_CAFE",
            "https://snapshot.local/live-lineage/pista","8/22 더 피스타 밀롱가",
            "8/22 더 피스타 밀롱가 홍대 PISTA 입장료 13,000원",
            published_at="2026-08-18",
            acquisition_quality="METADATA_ONLY")])
    post=d["rows"][0]
    post_id,is_new=persist_raw_post(con,post)
    record_discovery_persist_result(con,lineage_id=d["lineage_id"],observation_id=d["observation_id"],
        post_id=post_id,source_id=post.source_id,source_url=post.source_url,is_new=is_new)

    # Create the origin candidate now, so cross-source recovery can safely match the same EventInstance.
    processed=process_discovered_post(con,post,"SECONDARY")
    if processed["events"]:
        persist_events(con,post_id,processed["events"]); con.commit()

    row=con.execute("""SELECT rp.post_id,rp.source_id,rp.source_url,rp.title,rp.body,rp.published_at,rp.acquisition_quality,s.platform
                       FROM raw_posts rp JOIN sources s ON s.source_id=rp.source_id WHERE rp.post_id=?""",(post_id,)).fetchone()
    acq=SnapshotGenericPostAcquirer(root/"data"/"acquisition_snapshots",{post.source_url:"naver-blocked.html"})
    aq=acquire_posts(con,[row],mode="snapshot",acquirer=acq,
        lineage_map={post_id:{"lineage_id":d["lineage_id"],"observation_id":d["observation_id"]}})
    acq_obs=aq[0]["observation_id"]

    provider=NaverApiSnapshotProvider(root/"data"/"collector_snapshots")
    run_recovery_with_lineage(con,provider,
        lineage_map={post_id:{"lineage_id":d["lineage_id"],"observation_id":acq_obs}})
    close_lineage(con,d["lineage_id"],"COMPLETE")
    return lineage_trace(con,d["lineage_id"])
