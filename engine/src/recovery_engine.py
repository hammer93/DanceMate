from datetime import datetime, timezone
from .database import (
    list_pending_recovery, persist_raw_post, persist_events, event_candidates_for_post,
    persist_cross_source_run, update_recovery_state, upsert_event_instance, link_candidate_to_instance
)
from .live_pipeline import process_discovered_post
from .event_identity import same_event_instance, build_identity_key, normalize_event_name, normalize_venue

def _candidate_dict(row):
    return {
        "candidate_id":row["candidate_id"],"name":row["name"],"event_date":row["event_date"],
        "start_time":row["start_time"],"end_time":row["end_time"],"fee":row["fee"],"venue":row["venue"],
        "status":row["status"]
    }

def _build_query(recovery_row, origin_candidate=None):
    parts=[]
    if origin_candidate:
        for v in [origin_candidate.get("name"), origin_candidate.get("event_date"), origin_candidate.get("venue")]:
            if v: parts.append(str(v))
    if not parts:
        parts.append(recovery_row["event_hint"] or recovery_row["post_title"] or "")
    return " ".join(parts).strip()

def _merged_status(candidates):
    # Cross-source VERIFIED only if one or combined candidates provide date/time/fee and no explicit conflict.
    date=next((c["event_date"] for c in candidates if c.get("event_date")),None)
    start=next((c["start_time"] for c in candidates if c.get("start_time")),None)
    fee=next((c["fee"] for c in candidates if c.get("fee") is not None),None)
    return "VERIFIED" if date and start and fee is not None else "POSSIBLE"

def run_recovery(con, provider):
    output=[]
    for rq in list_pending_recovery(con):
        origin_rows=event_candidates_for_post(con,rq["post_id"])
        origin=_candidate_dict(origin_rows[0]) if origin_rows else None
        query=_build_query(rq,origin)
        started=datetime.now(timezone.utc).isoformat()
        try:
            posts=provider.search(query)
            matched=[]
            origin_candidates=[origin] if origin else []
            for post in posts:
                post_id,is_new=persist_raw_post(con,post)
                srcrow=con.execute("SELECT source_role FROM sources WHERE source_id=?",(post.source_id,)).fetchone()
                role=srcrow["source_role"] if srcrow else "SECONDARY"
                processed=process_discovered_post(con,post,role)
                if is_new and processed["events"]:
                    persist_events(con,post_id,processed["events"]); con.commit()
                candidate_rows=event_candidates_for_post(con,post_id)
                for row in candidate_rows:
                    cand=_candidate_dict(row)
                    if origin:
                        decision=same_event_instance(origin,cand)
                    else:
                        # Without origin candidate we cannot safely auto-merge.
                        decision=None
                    if decision and decision.match:
                        matched.append((row,cand,decision))
            if matched:
                allc=[origin] if origin else []
                allc += [m[1] for m in matched]
                ref=origin or matched[0][1]
                key=build_identity_key(ref.get("name"),ref.get("event_date"),ref.get("venue"))
                status=_merged_status(allc)
                eid=upsert_event_instance(con,key,normalize_event_name(ref.get("name")),ref.get("event_date"),normalize_venue(ref.get("venue")),status)
                if origin_rows:
                    link_candidate_to_instance(con,eid,origin_rows[0]["candidate_id"],rq["source_id"])
                for row,cand,decision in matched:
                    src=con.execute("SELECT source_id FROM raw_posts WHERE post_id=(SELECT post_id FROM event_candidates WHERE candidate_id=?)",(row["candidate_id"],)).fetchone()["source_id"]
                    link_candidate_to_instance(con,eid,row["candidate_id"],src)
                update_recovery_state(con,rq["recovery_id"],"RESOLVED")
                persist_cross_source_run(con,rq["recovery_id"],provider.name,query,len(posts),len(matched),started,"PASS")
                output.append({"recovery_id":rq["recovery_id"],"query":query,"status":"RESOLVED","matches":len(matched),"event_instance_id":eid,"event_status":status})
            else:
                persist_cross_source_run(con,rq["recovery_id"],provider.name,query,len(posts),0,started,"NO_MATCH")
                output.append({"recovery_id":rq["recovery_id"],"query":query,"status":"PENDING","matches":0})
        except Exception as e:
            persist_cross_source_run(con,rq["recovery_id"],provider.name,query,0,0,started,"FAILED",str(e))
            output.append({"recovery_id":rq["recovery_id"],"query":query,"status":"FAILED","error":str(e)})
    return output

def run_recovery_with_lineage(con, provider, lineage_map=None):
    from .database import start_observation,finish_observation,link_observation_event,recovery_parent_for_post
    pending=con.execute("SELECT * FROM recovery_queue WHERE state='PENDING' ORDER BY recovery_id").fetchall()
    results=[]
    for item in pending:
        lineage_id=None; parent=None
        link=None
        if lineage_map and item["post_id"] in lineage_map:
            link=lineage_map[item["post_id"]]
        else:
            link=recovery_parent_for_post(con,item["post_id"])
        if link:
            lineage_id=link.get("lineage_id")
            parent=link.get("observation_id")
        obs_id=start_observation(con,run_type="RECOVERY",source_id=item["source_id"],
            query_text=item["event_hint"],lineage_id=lineage_id,parent_observation_id=parent,
            stage="RECOVERY",metadata={"recovery_id":item["recovery_id"]})
        others=con.execute("SELECT recovery_id FROM recovery_queue WHERE state='PENDING' AND recovery_id<>?",
                           (item["recovery_id"],)).fetchall()
        for o in others: con.execute("UPDATE recovery_queue SET state='DEFERRED' WHERE recovery_id=?",(o["recovery_id"],))
        con.commit()
        try:
            one=run_recovery(con,provider)
        finally:
            for o in others: con.execute("UPDATE recovery_queue SET state='PENDING' WHERE recovery_id=?",(o["recovery_id"],))
            con.commit()
        result=next((x for x in one if x.get("recovery_id")==item["recovery_id"]),{})
        state=result.get("status","PENDING")
        success=1 if state=="RESOLVED" else 0
        finish_observation(con,obs_id,result_status="PASS" if success else "PARTIAL",
                           recovery_attempt_count=1,recovery_success_count=success,
                           metadata={"recovery_id":item["recovery_id"],"state_after":state})
        if result.get("event_instance_id"):
            lid=con.execute("SELECT lineage_id FROM observation_runs WHERE observation_id=?",(obs_id,)).fetchone()["lineage_id"]
            link_observation_event(con,lineage_id=lid,observation_id=obs_id,
                                   event_instance_id=result["event_instance_id"],role="RECOVERY_RESULT")
        results.append({"recovery_id":item["recovery_id"],"state":state,"observation_id":obs_id,
                        "event_instance_id":result.get("event_instance_id")})
    return results
