import json
from datetime import datetime, timezone, timedelta

from .database import (
    decision_outcome_evidence_rows, update_decision_outcome_evidence_status,
    upsert_decision_evidence_priority_state, decision_evidence_priority_rows,
    persist_decision_evidence_queue_event, decision_evidence_queue_event_rows
)

POLICY_VERSION="v0.38"
ACTIVE_STATUSES={"PENDING","HOLD"}
CRITICAL_ERRORS={"FALSE_VERIFIED","CANCELLATION_MISS"}
AUTO_EXPIRE_HOURS=72

def _dt(value):
    if not value:
        return None
    d=datetime.fromisoformat(value.replace("Z","+00:00"))
    if d.tzinfo is None:
        d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)

def _event_once(con,evidence_id,event_type,actor,detail):
    exists=con.execute("""SELECT 1 FROM decision_evidence_queue_events
                          WHERE evidence_id=? AND event_type=? LIMIT 1""",
                       (evidence_id,event_type)).fetchone()
    if exists:
        return None
    return persist_decision_evidence_queue_event(
        con,evidence_id=evidence_id,event_type=event_type,actor=actor,detail=detail)

def _cluster_key(row):
    critical=row["proposed_critical_error_type"] or "-"
    return f"{row['event_instance_id'] or 0}|{row['proposed_event_truth']}|{critical}"

def _event_start(con,row):
    event_id=row["event_instance_id"]
    if not event_id:
        return None
    e=con.execute("""SELECT event_date FROM event_instances
                     WHERE event_instance_id=?""",(event_id,)).fetchone()
    if not e or not e["event_date"]:
        return None
    f=con.execute("""SELECT value FROM event_field_states
                     WHERE event_instance_id=? AND field_name='start_time'""",
                  (event_id,)).fetchone()
    time_value=(f["value"] if f and f["value"] else "00:00").strip()
    try:
        hh,mm=[int(x) for x in time_value[:5].split(":")]
        d=datetime.fromisoformat(e["event_date"]).date()
        kst=timezone(timedelta(hours=9))
        return datetime(d.year,d.month,d.day,hh,mm,tzinfo=kst).astimezone(timezone.utc)
    except Exception:
        return None

def _priority(row, independent_sources, now, event_start=None):
    critical=row["proposed_critical_error_type"] in CRITICAL_ERRORS
    created=_dt(row["created_at"])
    age_hours=max(0.0,(now-created).total_seconds()/3600) if created else 0.0
    reasons=[]

    if critical:
        priority="P0"; score=100; sla_hours=.5
        reasons.append(f"Critical error candidate: {row['proposed_critical_error_type']}")
    elif row["evidence_type"] in ("CANCELLATION_DISCOVERED","ARRIVED_NO_EVENT"):
        priority="P1"; score=80; sla_hours=2
        reasons.append("High-impact event availability evidence")
    elif row["source_kind"] in ("USER_FEEDBACK","HUMAN_REVIEW"):
        priority="P1"; score=70; sla_hours=4
        reasons.append("Direct human/visit evidence")
    else:
        priority="P2"; score=50; sla_hours=24
        reasons.append("Normal confirmation queue")

    if row["confidence"]=="HIGH":
        score+=5
    if float(row["user_impact"])>=.9:
        score+=5
    if independent_sources>=2:
        score+=10
        reasons.append(f"{independent_sources} independent source kinds corroborate")
    if independent_sources>=3:
        score+=5

    if event_start is not None:
        hours_to_event=(event_start-now).total_seconds()/3600
        if 0 <= hours_to_event <= 6:
            score+=15
            reasons.append(f"Event starts within {round(hours_to_event,2)}h")
        elif 6 < hours_to_event <= 24:
            score+=8
            reasons.append(f"Event starts within {round(hours_to_event,2)}h")
        elif -6 <= hours_to_event < 0:
            score+=10
            reasons.append(f"Event started {round(abs(hours_to_event),2)}h ago; confirmation urgent")

    # Age escalation: don't let old high-impact evidence disappear below newer items.
    if age_hours>=24:
        score+=5
        reasons.append("Aged >=24h")
    if age_hours>=48:
        score+=5
        reasons.append("Aged >=48h")

    score=min(score,120)
    return priority,score,sla_hours,reasons

def _resolution_confidence(row, independent_sources):
    if independent_sources>=3:
        return "VERY_HIGH"
    if independent_sources>=2:
        return "HIGH_CORROBORATED"
    return row["confidence"]

def evaluate_evidence_priority_queue(con, *, now=None, apply_auto_resolution=True):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now=now.replace(tzinfo=timezone.utc)
    now=now.astimezone(timezone.utc)

    active=[r for r in decision_outcome_evidence_rows(con)
            if r["status"] in ACTIVE_STATUSES]

    clusters={}
    for r in active:
        key=_cluster_key(r)
        clusters.setdefault(key,[]).append(r)

    expired=[]
    overdue_ids=[]
    corroborated=[]
    evaluated=[]

    for row in active:
        key=_cluster_key(row)
        members=clusters[key]
        independent_sources=len({m["source_kind"] for m in members})
        corroboration=max(0,len(members)-1)
        event_start=_event_start(con,row)
        priority,score,sla_hours,reasons=_priority(
            row,independent_sources,now,event_start)

        created=_dt(row["created_at"]) or now
        sla_due=created+timedelta(hours=sla_hours)
        if event_start is not None:
            # Confirmation should complete before users need to depart.
            event_due=event_start-timedelta(hours=2)
            if event_due < sla_due:
                sla_due=event_due
                reasons.append("SLA tightened to event start minus 2h")
        overdue=now>sla_due

        critical=row["proposed_critical_error_type"] in CRITICAL_ERRORS
        auto_eligible=(not critical and row["confidence"] in ("LOW","MEDIUM"))
        expires_at=(created+timedelta(hours=AUTO_EXPIRE_HOURS)
                    if auto_eligible else None)

        if overdue:
            overdue_ids.append(row["evidence_id"])
            reasons.append("Confirmation SLA overdue")
            _event_once(
                con,row["evidence_id"],"SLA_BREACH","evidence-priority-queue",
                {"sla_due_at":sla_due.isoformat(),"priority":priority})

        if independent_sources>=2:
            corroborated.append(row["evidence_id"])
            _event_once(
                con,row["evidence_id"],"MULTI_SOURCE_CORROBORATION",
                "evidence-priority-queue",
                {"cluster_key":key,
                 "independent_source_count":independent_sources,
                 "corroboration_count":corroboration})

        resolution_confidence=_resolution_confidence(row,independent_sources)

        will_expire=(auto_eligible and expires_at and now>expires_at)
        if will_expire and apply_auto_resolution:
            update_decision_outcome_evidence_status(
                con,row["evidence_id"],"EXPIRED")
            expired.append(row["evidence_id"])
            reasons.append("Low-risk stale evidence auto-expired; never auto-confirmed")
            _event_once(
                con,row["evidence_id"],"AUTO_EXPIRED",
                "evidence-priority-queue",
                {"expires_at":expires_at.isoformat(),
                 "safety_policy":"NONCRITICAL_LOW_OR_MEDIUM_ONLY"})

        upsert_decision_evidence_priority_state(
            con,evidence_id=row["evidence_id"],priority=priority,
            priority_score=score,sla_due_at=sla_due.isoformat(),
            overdue=overdue,independent_source_count=independent_sources,
            corroboration_count=corroboration,
            resolution_confidence=resolution_confidence,
            expires_at=expires_at.isoformat() if expires_at else None,
            auto_resolution_eligible=auto_eligible,
            cluster_key=key,reasons=reasons,
            last_evaluated_at=now.isoformat())

        evaluated.append(row["evidence_id"])

    queue=[dict(r) for r in decision_evidence_priority_rows(con)
           if r["status"] in ACTIVE_STATUSES]
    for q in queue:
        q["reasons_json"]=json.loads(q["reasons_json"] or "[]")

    return {
        "policy_version":POLICY_VERSION,
        "evaluated_count":len(evaluated),
        "active_queue_count":len(queue),
        "p0_count":sum(q["priority"]=="P0" for q in queue),
        "p1_count":sum(q["priority"]=="P1" for q in queue),
        "overdue_count":sum(bool(q["overdue"]) for q in queue),
        "corroborated_count":sum(q["independent_source_count"]>=2 for q in queue),
        "auto_expired_count":len(expired),
        "auto_expired_evidence_ids":expired,
        "queue":queue,
        "safety":{
            "automatic_confirm":False,
            "automatic_reject":False,
            "automatic_expire_noncritical_low_medium_only":True,
            "critical_evidence_never_auto_expires":True,
            "multi_source_corroboration_never_auto_confirms":True
        }
    }

def priority_queue(con, *, status=None):
    rows=decision_evidence_priority_rows(con,status)
    out=[]
    for r in rows:
        x=dict(r)
        x["reasons_json"]=json.loads(x["reasons_json"] or "[]")
        out.append(x)
    return out

def queue_event_history(con,evidence_id=None):
    out=[]
    for r in decision_evidence_queue_event_rows(con,evidence_id):
        x=dict(r)
        x["detail_json"]=json.loads(x["detail_json"] or "{}")
        out.append(x)
    return out
