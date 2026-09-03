import json
from datetime import datetime, timezone

from .database import (
    decision_outcome_evidence_rows, upsert_decision_evidence_cluster,
    link_evidence_cluster, decision_evidence_cluster_rows,
    decision_evidence_cluster_row, cluster_evidence_rows,
    persist_root_cause_attribution, root_cause_attribution_rows,
    link_root_cause_backlog, create_backlog_item, backlog_row,
    persist_cluster_closure_check, cluster_closure_check_rows
)

POLICY_VERSION="v0.39"
ACTIVE={"PENDING","HOLD"}
FINAL={"CONFIRMED","REJECTED","EXPIRED"}
CRITICAL={"FALSE_VERIFIED","CANCELLATION_MISS"}

def _cluster_key(row):
    return f"{row['event_instance_id'] or 0}|{row['proposed_event_truth']}|{row['proposed_critical_error_type'] or '-'}"

def _severity(rows):
    if any(r["proposed_critical_error_type"] in CRITICAL for r in rows):
        return "CRITICAL"
    truths={r["proposed_event_truth"] for r in rows}
    if truths & {"CANCELLED","EVENT_DID_NOT_OCCUR"}:
        return "HIGH"
    return "MEDIUM"

def _resolution_confidence(rows):
    sources=len({r["source_kind"] for r in rows})
    confirmed=sum(r["status"]=="CONFIRMED" for r in rows)
    if confirmed>=1 and sources>=3:
        return "VERY_HIGH"
    if confirmed>=1 and sources>=2:
        return "HIGH_CONFIRMED_CORROBORATED"
    if confirmed>=1:
        return "HUMAN_CONFIRMED"
    if sources>=3:
        return "VERY_HIGH_PENDING"
    if sources>=2:
        return "HIGH_CORROBORATED_PENDING"
    return rows[0]["confidence"] if rows else "UNKNOWN"

def resolve_clusters(con):
    rows=list(decision_outcome_evidence_rows(con))
    groups={}
    for r in rows:
        groups.setdefault(_cluster_key(r),[]).append(r)

    created=0
    updated=0
    resolved=0
    clusters=[]
    for key,members in groups.items():
        confirmed=[r for r in members if r["status"]=="CONFIRMED"]
        rejected=[r for r in members if r["status"]=="REJECTED"]
        expired=[r for r in members if r["status"]=="EXPIRED"]
        active=[r for r in members if r["status"] in ACTIVE]
        source_count=len({r["source_kind"] for r in members})
        outcomes={r["proposed_outcome"] for r in confirmed}

        if confirmed and len(outcomes)==1:
            status="CONFIRMED_CASE"
            resolved_outcome=next(iter(outcomes))
            resolved_by="HUMAN_CONFIRMATION"
            resolved_at=max(r["updated_at"] for r in confirmed)
            resolved+=1
        elif confirmed and len(outcomes)>1:
            status="CONFLICT"
            resolved_outcome=None
            resolved_by=None
            resolved_at=None
        elif active:
            status="OPEN"
            resolved_outcome=None
            resolved_by=None
            resolved_at=None
        elif rejected and len(rejected)+len(expired)==len(members):
            status="DISMISSED"
            resolved_outcome=None
            resolved_by="HUMAN_REJECTION"
            resolved_at=max(r["updated_at"] for r in members)
            resolved+=1
        elif expired and len(expired)==len(members):
            status="EXPIRED"
            resolved_outcome=None
            resolved_by="SAFETY_EXPIRY"
            resolved_at=max(r["updated_at"] for r in members)
            resolved+=1
        else:
            status="OPEN"
            resolved_outcome=None
            resolved_by=None
            resolved_at=None

        first=members[0]
        cid,is_new=upsert_decision_evidence_cluster(
            con,cluster_key=key,event_instance_id=first["event_instance_id"],
            goal_profile=first["goal_profile"],
            proposed_event_truth=first["proposed_event_truth"],
            critical_error_type=first["proposed_critical_error_type"],
            status=status,severity=_severity(members),
            evidence_count=len(members),independent_source_count=source_count,
            confirmed_count=len(confirmed),rejected_count=len(rejected),
            resolution_confidence=_resolution_confidence(members),
            resolved_outcome=resolved_outcome,resolved_by=resolved_by,
            resolved_at=resolved_at)
        created+=int(is_new); updated+=int(not is_new)
        for r in members:
            link_evidence_cluster(con,cid,r["evidence_id"])
        clusters.append(cid)

    return {
        "policy_version":POLICY_VERSION,
        "cluster_count":len(clusters),
        "created_count":created,
        "updated_count":updated,
        "resolved_count":resolved,
        "cluster_ids":clusters
    }

def _source_id(con,row):
    ref=row["source_ref"]
    if not ref:
        return None
    if row["source_kind"]=="EVENT_REFRESH_CHECK":
        r=con.execute("""SELECT source_id FROM event_refresh_checks
                         WHERE check_id=?""",(ref,)).fetchone()
        return r["source_id"] if r else None
    if row["source_kind"]=="EVENT_REVISION":
        r=con.execute("""SELECT source_id FROM event_revisions
                         WHERE revision_id=?""",(ref,)).fetchone()
        return r["source_id"] if r else None
    return None

def _attribution_for(con,row):
    critical=row["proposed_critical_error_type"]
    source=row["source_kind"]
    sid=_source_id(con,row)

    if critical=="CANCELLATION_MISS":
        return {
            "category":"FRESHNESS_DETECTION_MISS",
            "component":"EVENT_LIFECYCLE",
            "source_id":sid,
            "rule_key":"CANCELLATION_REFRESH_WINDOW",
            "confidence":"HIGH" if source=="EVENT_REFRESH_CHECK" else "MEDIUM",
            "rationale":["Cancellation was not surfaced before the decision window",
                         f"Evidence source={source}"]
        }
    if critical=="FALSE_VERIFIED":
        return {
            "category":"VERIFICATION_FALSE_POSITIVE",
            "component":"VERIFICATION_GATE",
            "source_id":sid,
            "rule_key":"VERIFIED_EVENT_EXISTENCE",
            "confidence":"MEDIUM",
            "rationale":["Human-confirmed outcome contradicts VERIFIED/existence expectation",
                         f"Evidence source={source}"]
        }
    if source=="HUMAN_REVIEW":
        return {
            "category":"EXTRACTION_OR_RULE_CORRECTION",
            "component":"PARSER_RULE",
            "source_id":sid,
            "rule_key":"HUMAN_REVIEW_CORRECTION",
            "confidence":"MEDIUM",
            "rationale":["Human review corrected/rejected machine-derived event information"]
        }
    if source=="EVENT_REVISION":
        return {
            "category":"LIFECYCLE_CHANGE_DETECTION",
            "component":"EVENT_LIFECYCLE",
            "source_id":sid,
            "rule_key":"REVISION_PROPAGATION",
            "confidence":"MEDIUM",
            "rationale":["Later event revision changed the previously observed event truth"]
        }
    return {
        "category":"UNRESOLVED_EXTERNAL_SIGNAL",
        "component":"EVIDENCE_CONFIRMATION",
        "source_id":sid,
        "rule_key":"MANUAL_INVESTIGATION",
        "confidence":"LOW",
        "rationale":[f"No deterministic technical root cause from source={source}"]
    }

def attribute_root_causes(con, *, actor="root-cause-engine"):
    resolve_clusters(con)
    created=[]
    for cluster in decision_evidence_cluster_rows(con):
        if cluster["status"]!="CONFIRMED_CASE":
            continue
        members=list(cluster_evidence_rows(con,cluster["cluster_id"]))
        confirmed=[r for r in members if r["status"]=="CONFIRMED"]
        if not confirmed:
            continue

        # Prefer critical evidence, then strongest source types.
        confirmed.sort(key=lambda r:(
            0 if r["proposed_critical_error_type"] in CRITICAL else 1,
            0 if r["source_kind"]=="EVENT_REFRESH_CHECK" else
            1 if r["source_kind"]=="HUMAN_REVIEW" else
            2 if r["source_kind"]=="EVENT_REVISION" else 3,
            r["evidence_id"]))
        row=confirmed[0]
        a=_attribution_for(con,row)
        aid=persist_root_cause_attribution(
            con,cluster_id=cluster["cluster_id"],category=a["category"],
            component=a["component"],source_kind=row["source_kind"],
            source_id=a["source_id"],rule_key=a["rule_key"],
            confidence=a["confidence"],status="CONFIRMED_ATTRIBUTION",
            rationale=a["rationale"],attributed_by=actor)
        created.append(aid)
    return {
        "policy_version":POLICY_VERSION,
        "attributed_count":len(created),
        "attribution_ids":created
    }

def _repeat_count(con,a):
    q="""SELECT COUNT(DISTINCT r.cluster_id) n
         FROM root_cause_attributions r
         JOIN decision_evidence_clusters c ON c.cluster_id=r.cluster_id
         WHERE r.category=? AND COALESCE(r.component,'')=COALESCE(?,'')
           AND COALESCE(r.source_id,'')=COALESCE(?,'')
           AND r.status='CONFIRMED_ATTRIBUTION'
           AND c.severity='CRITICAL'"""
    return con.execute(q,(a["category"],a["component"],a["source_id"])).fetchone()["n"]

def sync_root_cause_backlog(con, *, actor="root-cause-engine"):
    attribute_root_causes(con,actor=actor)
    linked=[]
    skipped=[]
    for a in root_cause_attribution_rows(con):
        cluster=decision_evidence_cluster_row(con,a["cluster_id"])
        if cluster["severity"]!="CRITICAL" or a["status"]!="CONFIRMED_ATTRIBUTION":
            continue
        if a["backlog_id"]:
            skipped.append({"attribution_id":a["attribution_id"],"reason":"already_linked"})
            continue

        repeat=_repeat_count(con,a)
        if repeat<2:
            skipped.append({"attribution_id":a["attribution_id"],
                            "reason":"repeat_threshold_not_met","repeat_count":repeat})
            continue

        title=f"[Critical Evidence] {a['category']} 재발 방지"
        existing=con.execute("""SELECT backlog_id FROM improvement_backlog_items
          WHERE title=? AND COALESCE(source_id,'')=COALESCE(?,'')
            AND status IN ('OPEN','IN_PROGRESS','VERIFIED')
          ORDER BY backlog_id DESC LIMIT 1""",(title,a["source_id"])).fetchone()

        if existing:
            bid=existing["backlog_id"]
            created=False
        else:
            bid,_=create_backlog_item(
                con,source_id=a["source_id"],field_name="event_status",
                title=title,priority="P1",
                sample_confidence="MEDIUM" if repeat<5 else "HIGH",
                hotspot_score=repeat,opened_by=actor,
                goal_profile="FIELD_QUALITY",goal_weights={},
                metadata={
                    "origin":"v0.39_root_cause_attribution",
                    "root_cause_category":a["category"],
                    "component":a["component"],
                    "rule_key":a["rule_key"],
                    "repeat_confirmed_critical_clusters":repeat,
                    "acceptance_criteria":[
                        "reproduce root cause with regression fixture",
                        "prevent same critical error in fixture",
                        "full pytest passes",
                        "closure gate re-check passes"
                    ]
                })
            created=True

        # Link every matching attribution to the same backlog.
        matches=con.execute("""SELECT attribution_id FROM root_cause_attributions
          WHERE category=? AND COALESCE(component,'')=COALESCE(?,'')
            AND COALESCE(source_id,'')=COALESCE(?,'')
            AND status='CONFIRMED_ATTRIBUTION'""",
          (a["category"],a["component"],a["source_id"])).fetchall()
        for m in matches:
            link_root_cause_backlog(con,m["attribution_id"],bid)
        linked.append({"attribution_id":a["attribution_id"],"backlog_id":bid,
                       "created":created,"repeat_count":repeat})
    return {"policy_version":POLICY_VERSION,"linked":linked,"skipped":skipped}

def closure_check(con, cluster_id, *, actor="closure-gate"):
    cluster=decision_evidence_cluster_row(con,cluster_id)
    if not cluster:
        raise KeyError("cluster not found")
    members=list(cluster_evidence_rows(con,cluster_id))
    attrs=list(root_cause_attribution_rows(con,cluster_id))
    unresolved=sum(
        r["status"] in ACTIVE and r["proposed_critical_error_type"] in CRITICAL
        for r in members)

    backlog_ids=sorted({a["backlog_id"] for a in attrs if a["backlog_id"]})
    open_count=0
    verified_count=0
    for bid in backlog_ids:
        b=backlog_row(con,bid)
        if not b:
            continue
        if b["status"]=="VERIFIED":
            verified_count+=1
        elif b["status"] in ("OPEN","IN_PROGRESS"):
            open_count+=1

    reasons=[]
    ready=True
    if cluster["status"] not in ("CONFIRMED_CASE","DISMISSED"):
        ready=False; reasons.append(f"Cluster status {cluster['status']} is not resolvable")
    if unresolved:
        ready=False; reasons.append(f"{unresolved} unresolved critical evidence item(s)")
    if cluster["status"]=="CONFIRMED_CASE" and not attrs:
        ready=False; reasons.append("Root cause attribution missing")
    if cluster["severity"]=="CRITICAL":
        if not backlog_ids:
            ready=False; reasons.append("Critical cluster has no linked remediation backlog")
        elif open_count:
            ready=False; reasons.append(f"{open_count} remediation backlog item(s) still open")
        elif verified_count<len(backlog_ids):
            ready=False; reasons.append("Not all remediation backlog items are VERIFIED")

    status="READY_FOR_CLOSURE" if ready else "BLOCKED"
    if ready:
        reasons.append("All v0.39 closure prerequisites satisfied")

    cid=persist_cluster_closure_check(
        con,cluster_id=cluster_id,status=status,
        unresolved_critical_evidence=unresolved,open_backlog_count=open_count,
        verified_backlog_count=verified_count,reasons=reasons,checked_by=actor)
    return {
        "closure_check_id":cid,"cluster_id":cluster_id,"status":status,
        "unresolved_critical_evidence":unresolved,
        "open_backlog_count":open_count,"verified_backlog_count":verified_count,
        "reasons":reasons
    }

def close_cluster(con, cluster_id, *, actor, reason=None):
    if not actor:
        raise ValueError("actor required")
    check=closure_check(con,cluster_id,actor=actor)
    if check["status"]!="READY_FOR_CLOSURE":
        raise ValueError("cluster is not READY_FOR_CLOSURE")
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE decision_evidence_clusters
                   SET closure_status='CLOSED',updated_at=?
                   WHERE cluster_id=?""",(now,cluster_id))
    con.commit()
    return {"cluster_id":cluster_id,"closure_status":"CLOSED",
            "closed_by":actor,"reason":reason}

def cluster_list(con,status=None):
    return [dict(r) for r in decision_evidence_cluster_rows(con,status)]

def root_cause_list(con,cluster_id=None):
    out=[]
    for r in root_cause_attribution_rows(con,cluster_id):
        x=dict(r); x["rationale_json"]=json.loads(x["rationale_json"] or "[]"); out.append(x)
    return out

def closure_history(con,cluster_id=None):
    out=[]
    for r in cluster_closure_check_rows(con,cluster_id):
        x=dict(r); x["reasons_json"]=json.loads(x["reasons_json"] or "[]"); out.append(x)
    return out
