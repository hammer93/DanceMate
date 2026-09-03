from datetime import datetime, timezone
from .revision import classify_revision,extract_change_hints
from .database import persist_event_revision,persist_refresh_check

def apply_revision(con, *, event_instance_id, candidate_row, source_id, raw_text, effective_at=None):
    before=con.execute("SELECT * FROM event_instances WHERE event_instance_id=?",(event_instance_id,)).fetchone()
    if not before:
        raise ValueError("event instance not found")
    dec=classify_revision(raw_text)
    hints=extract_change_hints(raw_text)
    changes={}
    after=before["status"]
    if dec.role=="CANCELLATION":
        after="CANCELLED"
        changes["status"]={"from":before["status"],"to":"CANCELLED"}
        con.execute("UPDATE event_instances SET status=?,updated_at=? WHERE event_instance_id=?",
                    (after,datetime.now(timezone.utc).isoformat(),event_instance_id))
    elif dec.role=="UPDATE":
        after="UPDATED"
        changes["status"]={"from":before["status"],"to":"UPDATED"}
        if "start_time" in hints: changes["start_time"]={"to":hints["start_time"]}
        if "venue" in hints: changes["venue"]={"to":hints["venue"]}
        con.execute("UPDATE event_instances SET status=?,updated_at=? WHERE event_instance_id=?",
                    (after,datetime.now(timezone.utc).isoformat(),event_instance_id))
    else:
        changes["status"]={"from":before["status"],"to":before["status"]}
    con.commit()
    rid=persist_event_revision(con,event_instance_id=event_instance_id,
        candidate_id=(candidate_row["candidate_id"] if candidate_row else None),
        source_id=source_id,revision_role=dec.role,effective_at=effective_at,
        field_changes=changes,raw_summary=raw_text,is_current=True)
    return {"revision_id":rid,"role":dec.role,"field_changes":changes,"status_after":after}

def record_refresh(con, *, event_instance_id, scheduled_event_date, hours_before_start,
                   status_before,status_after,source_id=None,notes=None,expected_cancellation=False):
    cancellation=(status_after=="CANCELLED")
    change=(status_before!=status_after)
    miss=bool(expected_cancellation and not cancellation)
    checked=datetime.now(timezone.utc).isoformat()
    persist_refresh_check(con,event_instance_id=event_instance_id,checked_at=checked,
        scheduled_event_date=scheduled_event_date,hours_before_start=hours_before_start,
        status_before=status_before,status_after=status_after,change_detected=change,
        cancellation_detected=cancellation,critical_miss=miss,source_id=source_id,notes=notes)
    return {"event_instance_id":event_instance_id,"status_before":status_before,"status_after":status_after,
            "change_detected":change,"cancellation_detected":cancellation,"critical_miss":miss}

def freshness_band(hours_before_start):
    if hours_before_start is None:return "UNKNOWN"
    if hours_before_start<=3:return "CRITICAL"
    if hours_before_start<=12:return "HIGH"
    if hours_before_start<=24:return "MEDIUM"
    return "NORMAL"
