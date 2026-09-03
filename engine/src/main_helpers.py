import json
from .database import seed_sources,persist_raw_post,persist_events
from .discovery_observer import run_discovery_with_lineage,record_discovery_persist_result
from .collectors.naver import load_naver_snapshot
from .generic_acquisition_pipeline import acquire_posts,metadata_rows
from .acquirers.snapshot_generic import SnapshotGenericPostAcquirer
from .recovery_engine import run_recovery_with_lineage
from .providers.naver_snapshot import NaverApiSnapshotProvider
from .live_pipeline import process_discovered_post
from .evidence_service import apply_evidence_model

def collect_naver_snapshot_step(con,root):
    seed_sources(con,json.loads((root/"config"/"sources.json").read_text(encoding="utf-8")))
    cfg=[("blog","SRC-N-001","naver-blog-sample.json"),("cafe","SRC-N-002","naver-cafe-sample.json")]
    results=[]; lineages=[]
    for kind,sid,fn in cfg:
        obs=run_discovery_with_lineage(con,source_id=sid,query="밀롱가",
          collector_callable=lambda kind=kind,sid=sid,fn=fn:
            load_naver_snapshot(root/"data"/"collector_snapshots"/fn,kind=kind,source_id=sid,query="밀롱가"))
        lineages.append(obs["lineage_id"]); new=dup=0
        for post in obs["rows"]:
            pid,is_new=persist_raw_post(con,post)
            record_discovery_persist_result(con,lineage_id=obs["lineage_id"],
              observation_id=obs["observation_id"],post_id=pid,source_id=post.source_id,
              source_url=post.source_url,is_new=is_new)
            new+=int(is_new); dup+=int(not is_new)
            if is_new:
                d=process_discovered_post(con,post,"SECONDARY"); persist_events(con,pid,d["events"])
        con.commit()
        results.append({"kind":kind,"source_id":sid,"discovered":len(obs["rows"]),"new":new,"duplicates":dup})
    return {"results":results,"lineages":lineages}

def acquire_naver_snapshot_step(con,root):
    mapping={
      "https://snapshot.local/naver/blog/pista":"naver-blog-full.html",
      "https://snapshot.local/naver/blog/class":"naver-blocked.html",
      "https://snapshot.local/naver/cafe/pista":"naver-cafe-body-only.html"}
    acq=SnapshotGenericPostAcquirer(root/"data"/"acquisition_snapshots",mapping)
    rows=metadata_rows(con,platforms=("NAVER_BLOG","NAVER_CAFE"))
    return {"acquisitions":acquire_posts(con,rows,mode="snapshot",acquirer=acq)}

def recover_naver_snapshot_step(con,root):
    rows=run_recovery_with_lineage(con,NaverApiSnapshotProvider(root/"data"/"collector_snapshots"))
    normalized=[]
    for r in rows:
        eid=r.get("event_instance_id")
        if eid:
            # Recovery engine may create a legacy VERIFIED EventInstance before v0.10 field-state enforcement.
            # Rebuild its confidence from the actual recovered candidate so no VERIFIED event exists without field evidence.
            c=con.execute("""SELECT ec.event_date,ec.start_time,ec.fee,ec.venue,eic.source_id,
                            s.authority_level,s.access_state
                            FROM event_instance_candidates eic
                            JOIN event_candidates ec ON ec.candidate_id=eic.candidate_id
                            LEFT JOIN sources s ON s.source_id=eic.source_id
                            WHERE eic.event_instance_id=?
                            ORDER BY ec.candidate_id DESC LIMIT 1""",(eid,)).fetchone()
            if c:
                primary=(c["authority_level"] in ("PRIMARY_ORGANIZER","PRIMARY_VENUE")
                         and c["access_state"]=="OPEN")
                apply_evidence_model(
                    con,event_instance_id=eid,
                    date_value=c["event_date"],venue_value=c["venue"],time_value=c["start_time"],
                    fee_verified=(str(c["fee"]) if c["fee"] is not None else None),
                    fee_expected=None,occurrence_confirmed=True,
                    primary_or_equivalent=primary,freshness_ok=True,
                    source_scope="RECOVERY"
                )
        normalized.append(r)
    return {"recoveries":normalized}
