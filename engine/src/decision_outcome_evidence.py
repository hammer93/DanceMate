import json
from .database import (
    upsert_decision_outcome_evidence,decision_outcome_evidence_row,
    decision_outcome_evidence_rows,update_decision_outcome_evidence_status,
    persist_decision_outcome_confirmation,decision_outcome_confirmation_rows
)
from .decision_quality import record_decision_quality

POLICY_VERSION="v0.39"
CONFIRM_DECISIONS={"CONFIRM","REJECT","HOLD"}

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        if x.get("evidence_json"):
            x["evidence_json"]=json.loads(x["evidence_json"])
        if x.get("metadata_json"):
            x["metadata_json"]=json.loads(x["metadata_json"])
        out.append(x)
    return out

def scan_automatic_evidence(con, goal_profile="FIELD_QUALITY"):
    created=[]
    existing=[]

    # 1) Critical cancellation miss from lifecycle freshness checks.
    rows=con.execute("""SELECT c.*,e.status event_status,e.normalized_name,e.event_date
                        FROM event_refresh_checks c
                        JOIN event_instances e
                          ON e.event_instance_id=c.event_instance_id
                        WHERE c.critical_miss=1
                        ORDER BY c.check_id""").fetchall()
    for r in rows:
        key=f"REFRESH_CRITICAL_MISS:{r['check_id']}"
        eid,is_new=upsert_decision_outcome_evidence(
            con,evidence_key=key,event_instance_id=r["event_instance_id"],
            change_id=None,goal_profile=goal_profile,
            evidence_type="CANCELLATION_MISS_CANDIDATE",
            proposed_outcome="FAILURE",proposed_event_truth="CANCELLED",
            proposed_critical_error_type="CANCELLATION_MISS",
            source_kind="EVENT_REFRESH_CHECK",source_ref=str(r["check_id"]),
            confidence="HIGH",user_impact=1.0,core_relevance=1.0,
            evidence={
                "check_id":r["check_id"],
                "status_before":r["status_before"],
                "status_after":r["status_after"],
                "cancellation_detected":r["cancellation_detected"],
                "critical_miss":r["critical_miss"],
                "event_status":r["event_status"],
                "event_name":r["normalized_name"],
                "event_date":r["event_date"]
            })
        (created if is_new else existing).append(eid)

    # 2) Cancellation discovered after an event had already reached VERIFIED-like state.
    rows=con.execute("""SELECT r.revision_id,r.event_instance_id,r.revision_role,
                               r.observed_at,r.raw_summary,e.status,e.normalized_name
                        FROM event_revisions r
                        JOIN event_instances e
                          ON e.event_instance_id=r.event_instance_id
                        WHERE UPPER(r.revision_role)='CANCELLATION'
                        ORDER BY r.revision_id""").fetchall()
    for r in rows:
        key=f"REVISION_CANCELLATION:{r['revision_id']}"
        eid,is_new=upsert_decision_outcome_evidence(
            con,evidence_key=key,event_instance_id=r["event_instance_id"],
            change_id=None,goal_profile=goal_profile,
            evidence_type="CANCELLATION_DISCOVERED",
            proposed_outcome="UNKNOWN",proposed_event_truth="CANCELLED",
            proposed_critical_error_type=None,
            source_kind="EVENT_REVISION",source_ref=str(r["revision_id"]),
            confidence="MEDIUM",user_impact=.7,core_relevance=1.0,
            evidence={
                "revision_id":r["revision_id"],
                "revision_role":r["revision_role"],
                "observed_at":r["observed_at"],
                "event_status":r["status"],
                "event_name":r["normalized_name"],
                "raw_summary":r["raw_summary"]
            })
        (created if is_new else existing).append(eid)

    # 3) Human review that explicitly rejected/modified event information.
    rows=con.execute("""SELECT action_id,event_instance_id,action,reason,
                               old_value_json,new_value_json,evidence_json
                        FROM human_review_actions
                        WHERE event_instance_id IS NOT NULL
                          AND action IN ('REJECT','MODIFY','MODIFIED','REJECTED')
                        ORDER BY action_id""").fetchall()
    for r in rows:
        key=f"HUMAN_REVIEW:{r['action_id']}"
        proposed=("FAILURE" if str(r["action"]).startswith("REJECT") else "UNKNOWN")
        eid,is_new=upsert_decision_outcome_evidence(
            con,evidence_key=key,event_instance_id=r["event_instance_id"],
            change_id=None,goal_profile=goal_profile,
            evidence_type="HUMAN_REVIEW_CORRECTION",
            proposed_outcome=proposed,proposed_event_truth="CORRECTED",
            proposed_critical_error_type=None,
            source_kind="HUMAN_REVIEW",source_ref=str(r["action_id"]),
            confidence="HIGH",user_impact=.7,core_relevance=.9,
            evidence={
                "action_id":r["action_id"],"action":r["action"],
                "reason":r["reason"],"old_value_json":r["old_value_json"],
                "new_value_json":r["new_value_json"],
                "review_evidence_json":r["evidence_json"]
            })
        (created if is_new else existing).append(eid)

    return {
        "policy_version":POLICY_VERSION,
        "goal_profile":goal_profile,
        "created_count":len(created),
        "existing_count":len(existing),
        "created_evidence_ids":created,
        "existing_evidence_ids":existing
    }

def record_visit_feedback_evidence(con, *, event_instance_id, feedback,
                                   reviewer_source="USER_FEEDBACK",
                                   goal_profile="FIELD_QUALITY",
                                   note=None):
    feedback=feedback.upper()
    mapping={
        "VISITED_HELD":{
            "type":"VISIT_CONFIRMED_HELD","outcome":"SUCCESS",
            "truth":"EVENT_OCCURRED","critical":None,"confidence":"HIGH",
            "impact":1.0,"core":1.0
        },
        "ARRIVED_NO_EVENT":{
            "type":"ARRIVED_NO_EVENT","outcome":"FAILURE",
            "truth":"EVENT_DID_NOT_OCCUR","critical":"FALSE_VERIFIED",
            "confidence":"HIGH","impact":1.0,"core":1.0
        },
        "CANCELLED_BEFORE_VISIT":{
            "type":"CANCELLED_BEFORE_VISIT","outcome":"UNKNOWN",
            "truth":"CANCELLED","critical":None,"confidence":"HIGH",
            "impact":.8,"core":1.0
        }
    }
    if feedback not in mapping:
        raise ValueError(
            "feedback must be VISITED_HELD, ARRIVED_NO_EVENT, or CANCELLED_BEFORE_VISIT")
    m=mapping[feedback]
    # A feedback entry is intentionally unique per event/type/note combination.
    suffix=(note or "").strip()
    key=f"VISIT_FEEDBACK:{event_instance_id}:{feedback}:{suffix}"
    eid,is_new=upsert_decision_outcome_evidence(
        con,evidence_key=key,event_instance_id=event_instance_id,
        change_id=None,goal_profile=goal_profile,evidence_type=m["type"],
        proposed_outcome=m["outcome"],proposed_event_truth=m["truth"],
        proposed_critical_error_type=m["critical"],
        source_kind=reviewer_source,source_ref=None,confidence=m["confidence"],
        user_impact=m["impact"],core_relevance=m["core"],
        evidence={"feedback":feedback,"note":note})
    return {"evidence_id":eid,"created":is_new,"status":"PENDING",
            "proposed_outcome":m["outcome"],
            "critical_error_type":m["critical"]}

def confirm_evidence(con, *, evidence_id, decision, reviewer, reason=None):
    decision=decision.upper()
    if decision not in CONFIRM_DECISIONS:
        raise ValueError("decision must be CONFIRM, REJECT, or HOLD")
    if not reviewer:
        raise ValueError("reviewer is required")
    row=decision_outcome_evidence_row(con,evidence_id)
    if not row:
        raise KeyError("decision outcome evidence not found")
    if row["status"] in ("CONFIRMED","REJECTED","EXPIRED"):
        raise ValueError(f"evidence already finalized as {row['status']}")

    if decision=="HOLD":
        update_decision_outcome_evidence_status(con,evidence_id,"HOLD")
        cid=persist_decision_outcome_confirmation(
            con,evidence_id=evidence_id,decision=decision,reviewer=reviewer,
            reason=reason,metadata={"policy_version":POLICY_VERSION})
        return {"confirmation_id":cid,"evidence_id":evidence_id,
                "decision":"HOLD","status":"HOLD",
                "decision_quality_observation_id":None}

    if decision=="REJECT":
        update_decision_outcome_evidence_status(con,evidence_id,"REJECTED")
        cid=persist_decision_outcome_confirmation(
            con,evidence_id=evidence_id,decision=decision,reviewer=reviewer,
            reason=reason,metadata={"policy_version":POLICY_VERSION})
        return {"confirmation_id":cid,"evidence_id":evidence_id,
                "decision":"REJECT","status":"REJECTED",
                "decision_quality_observation_id":None}

    dq=record_decision_quality(
        con,goal_profile=row["goal_profile"],
        decision_outcome=row["proposed_outcome"],
        event_truth=row["proposed_event_truth"],
        decision_action="EVIDENCE_CONFIRMED",
        source_confidence=row["confidence"],
        critical_error_type=row["proposed_critical_error_type"],
        core_relevance=row["core_relevance"],user_impact=row["user_impact"],
        change_id=row["change_id"],event_id=row["event_instance_id"],
        metadata={
            "decision_outcome_evidence_id":evidence_id,
            "source_kind":row["source_kind"],
            "source_ref":row["source_ref"],
            "confirmed_by":reviewer
        })
    dqid=dq["decision_observation_id"]
    update_decision_outcome_evidence_status(con,evidence_id,"CONFIRMED")
    cid=persist_decision_outcome_confirmation(
        con,evidence_id=evidence_id,decision=decision,reviewer=reviewer,
        reason=reason,decision_quality_observation_id=dqid,
        metadata={"policy_version":POLICY_VERSION})
    # v0.39: confirmation immediately refreshes Cluster + Root-Cause traceability.
    from .evidence_cluster_resolution import resolve_clusters,attribute_root_causes
    cluster_result=resolve_clusters(con)
    attribution_result=attribute_root_causes(con,actor=reviewer)
    return {"confirmation_id":cid,"evidence_id":evidence_id,
            "decision":"CONFIRM","status":"CONFIRMED",
            "decision_quality_observation_id":dqid,
            "cluster_resolution":cluster_result,
            "root_cause_attribution":attribution_result}

def evidence_list(con,status=None,goal_profile=None):
    return _decode(decision_outcome_evidence_rows(con,status,goal_profile))

def confirmation_history(con,evidence_id=None):
    return _decode(decision_outcome_confirmation_rows(con,evidence_id))
