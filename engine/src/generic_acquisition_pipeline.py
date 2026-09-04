from datetime import datetime, timezone
from .database import (
    persist_acquisition_result, update_raw_post_acquisition, enqueue_recovery, persist_events,
    update_source_access, media_rows_for_post, classify_media_record,
    start_observation, finish_observation, latest_lineage_for_post
)
from .collectors.base import RawPostRecord
from .live_pipeline import process_discovered_post
from .source_state import derive_source_state
from .media_classifier import classify_media

def acquire_posts(con, rows, *, mode, acquirer, lineage_map=None):
    summary=[]
    for row in rows:
        lineage_id=None; parent_observation_id=None
        link=None
        if lineage_map and row["post_id"] in lineage_map:
            link=lineage_map[row["post_id"]]
        else:
            link=latest_lineage_for_post(con,row["post_id"])
        if link:
            lineage_id=link.get("lineage_id")
            parent_observation_id=link.get("observation_id")
        obs_id=start_observation(con,run_type="ACQUISITION",source_id=row["source_id"],
                                 target_url=row["source_url"],metadata={"mode":mode,"post_id":row["post_id"]},
                                 lineage_id=lineage_id,parent_observation_id=parent_observation_id,stage="ACQUISITION")
        started=datetime.now(timezone.utc).isoformat()
        result=acquirer.acquire(post_id=row["post_id"],source_id=row["source_id"],url=row["source_url"])
        persist_acquisition_result(con,result,mode=mode,started_at=started)

        srcrow=con.execute("SELECT source_role FROM sources WHERE source_id=?",(row["source_id"],)).fetchone()
        source_role=srcrow["source_role"] if srcrow else "UNKNOWN"
        authority,access=derive_source_state(
            source_role=source_role,
            acquisition_status=result.status,
            http_status=result.http_status,
            body_available=bool(result.body_text)
        )
        update_source_access(con,row["source_id"],authority_level=authority,access_state=access)

        # Classify all captured images; poster_candidate alone is not enough.
        for mr in media_rows_for_post(con,row["post_id"]):
            dec=classify_media(url=mr["media_url"],surrounding_text=result.body_text or "")
            classify_media_record(con,mr["media_id"],dec.media_class,dec.reason)

        upgraded=False
        if result.status in {"FULL","BODY_ONLY"} and result.body_text:
            update_raw_post_acquisition(con,row["post_id"],body=result.body_text,acquisition_quality=result.status)
            # Carry the post's own date. Re-extraction reads the dates out of
            # the body again, and a bare "8/22" cannot be placed in a year
            # without it -- dropping it here silently un-dated every post whose
            # body we successfully fetched.
            post=RawPostRecord(row["source_id"],row["platform"],row["source_url"],row["title"],result.body_text,
                published_at=row["published_at"],acquisition_quality=result.status)
            sr=con.execute("SELECT source_role FROM sources WHERE source_id=?",(row["source_id"],)).fetchone()
            role=sr["source_role"] if sr else "SECONDARY"
            processed=process_discovered_post(con,post,role)
            con.execute("DELETE FROM evidences WHERE candidate_id IN (SELECT candidate_id FROM event_candidates WHERE post_id=?)",(row["post_id"],))
            con.execute("DELETE FROM event_candidates WHERE post_id=?",(row["post_id"],))
            if processed["events"]:
                persist_events(con,row["post_id"],processed["events"])
            con.commit()
            upgraded=True
            if result.status=="BODY_ONLY":
                enqueue_recovery(con,row["post_id"],row["source_id"],row["title"],"POSTER_UNAVAILABLE")
        else:
            enqueue_recovery(con,row["post_id"],row["source_id"],row["title"],result.error_code or "FULL_BODY_UNAVAILABLE")
        finish_observation(con,obs_id,
            result_status="PASS" if result.status in {"FULL","BODY_ONLY"} else ("PARTIAL" if result.status=="PARTIAL" else "FAILED"),
            acquisition_attempt_count=1,
            acquisition_success_count=1 if result.status in {"FULL","BODY_ONLY"} else 0,
            acquisition_failure_count=1 if result.status in {"PARTIAL","FAILED"} else 0,
            error_code=result.error_code,error_message=result.error)
        lr=con.execute("SELECT lineage_id FROM observation_runs WHERE observation_id=?",(obs_id,)).fetchone()
        summary.append({
          "post_id":row["post_id"],"source_id":row["source_id"],"platform":row["platform"],"url":row["source_url"],
          "status":result.status,"body_chars":result.body_chars,"images":len(result.images),
          "poster_candidates":len(result.poster_candidates),"error_code":result.error_code,"upgraded":upgraded,
          "lineage_id":lr["lineage_id"],"observation_id":obs_id
        })
    return summary

def metadata_rows(con, platforms=None):
    sql="""SELECT rp.post_id,rp.source_id,rp.source_url,rp.title,rp.body,rp.published_at,rp.acquisition_quality,s.platform
           FROM raw_posts rp JOIN sources s ON s.source_id=rp.source_id
           WHERE rp.source_url IS NOT NULL AND rp.source_url<>'' AND rp.acquisition_quality='METADATA_ONLY'"""
    args=[]
    if platforms:
        ph=",".join("?" for _ in platforms)
        sql+=f" AND s.platform IN ({ph})"
        args=list(platforms)
    sql+=" ORDER BY rp.post_id"
    return con.execute(sql,args).fetchall()
