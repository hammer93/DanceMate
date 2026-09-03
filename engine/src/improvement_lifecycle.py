import json
from .database import (
    create_backlog_item,update_backlog_status,persist_effect_snapshot,
    backlog_row,backlog_history,effect_snapshots
)
from .improvement_backlog import recommend_improvement_backlog
from .correction_hotspot import analyze_correction_hotspots
from .evidence_metrics_v2 import calculate_metrics_v2
from .observation_metrics import calculate_observation_metrics
from .goal_weighting import backlog_goal_defaults

VALID_STATUS={"OPEN","IN_PROGRESS","VERIFIED","REJECTED"}

def _ratio(n,d):
    return round(n/d,4) if d else None

def sync_recommended_backlog(con, *, opened_by="system"):
    rec=recommend_improvement_backlog(con)
    created=[]
    existing={(r["source_id"],r["field_name"],r["status"]) for r in
              con.execute("""SELECT source_id,field_name,status FROM improvement_backlog_items
                             WHERE status IN ('OPEN','IN_PROGRESS')""").fetchall()}

    for item in rec["backlog"]:
        key=(item.get("source_id"),item.get("field"))
        if key+( "OPEN",) in existing or key+( "IN_PROGRESS",) in existing:
            continue
        title=item["recommended_epics"][0]["title"] if item["recommended_epics"] else item["problem_statement"]
        component=(item["recommended_epics"][0]["component"]
                   if item.get("recommended_epics") else None)
        goal_profile,goal_weights=backlog_goal_defaults(
            component=component,field_name=item.get("field"))
        bid,buuid=create_backlog_item(
            con,source_id=item.get("source_id"),field_name=item.get("field"),
            title=title,priority=item["priority"],sample_confidence=item["confidence"],
            hotspot_score=item.get("hotspot_score",0),opened_by=opened_by,
            metadata={"recommendation":item},
            goal_profile=goal_profile,goal_weights=goal_weights
        )
        created.append({"backlog_id":bid,"backlog_uuid":buuid,"source_id":item.get("source_id"),
                        "field":item.get("field"),"title":title})
    return {"created":created,"recommendation":rec}

def _source_metrics(con, source_id):
    if not source_id:
        return {}
    row=con.execute("""SELECT
        COALESCE(SUM(discovered_count),0) discovered,
        COALESCE(SUM(rawpost_new_count),0) raw_new,
        COALESCE(SUM(acquisition_attempt_count),0) aa,
        COALESCE(SUM(acquisition_failure_count),0) af,
        COALESCE(SUM(recovery_attempt_count),0) ra,
        COALESCE(SUM(recovery_success_count),0) rs
        FROM observation_runs
        WHERE source_id=? AND result_status<>'RUNNING'""",(source_id,)).fetchone()
    return {
        "access_failure_rate":_ratio(row["af"],row["aa"]),
        "source_yield_rate":_ratio(row["raw_new"],row["discovered"]),
        "recovery_success_rate":_ratio(row["rs"],row["ra"]),
    }

def capture_backlog_effect(con, backlog_id, *, phase):
    b=backlog_row(con,backlog_id)
    if not b:
        raise KeyError("backlog not found")
    hotspots=analyze_correction_hotspots(con)
    target=None
    for h in hotspots["source_field_hotspots"]:
        if h["source_id"]==b["source_id"] and h["field"]==b["field_name"]:
            target=h
            break

    ev=calculate_metrics_v2(con,f"backlog-{phase.lower()}")
    overall=ev[0] if ev else {}
    sm=_source_metrics(con,b["source_id"])

    metrics={
        "review_count":target["reviews"] if target else 0,
        "correction_rate":target["correction_rate"] if target else None,
        "access_failure_rate":sm.get("access_failure_rate"),
        "field_coverage_rate":overall.get("field_coverage_rate"),
        "known_field_rate":overall.get("known_field_rate"),
        "source_yield_rate":sm.get("source_yield_rate"),
        "recovery_success_rate":sm.get("recovery_success_rate"),
    }
    sid=persist_effect_snapshot(con,backlog_id=backlog_id,phase=phase,metrics=metrics,
                                metadata={"source_id":b["source_id"],"field":b["field_name"]})
    return {"snapshot_id":sid,"phase":phase,"metrics":metrics}

def change_backlog_status(con, backlog_id, *, status, actor="operator",
                          note=None, owner=None, rejection_reason=None):
    if status not in VALID_STATUS:
        raise ValueError("invalid status")
    row=backlog_row(con,backlog_id)
    if not row:
        raise KeyError("backlog not found")

    # BEFORE is captured automatically when work starts.
    if row["status"]=="OPEN" and status=="IN_PROGRESS":
        capture_backlog_effect(con,backlog_id,phase="BEFORE")

    # AFTER is captured before final verification/rejection so effect can be compared.
    if status in ("VERIFIED","REJECTED") and row["status"]=="IN_PROGRESS":
        capture_backlog_effect(con,backlog_id,phase="AFTER")

    update_backlog_status(con,backlog_id,to_status=status,actor=actor,note=note,
                          owner=owner,rejection_reason=rejection_reason)
    return backlog_detail(con,backlog_id)

def backlog_detail(con, backlog_id):
    b=backlog_row(con,backlog_id)
    if not b:
        return None
    snaps=[dict(x) for x in effect_snapshots(con,backlog_id)]
    hist=[dict(x) for x in backlog_history(con,backlog_id)]

    before=next((x for x in snaps if x["phase"]=="BEFORE"),None)
    after=next((x for x in reversed(snaps) if x["phase"]=="AFTER"),None)

    effect=None
    if before and after:
        def delta(key):
            a=after[key]; bval=before[key]
            return round(a-bval,4) if a is not None and bval is not None else None
        effect={
            "correction_rate_delta":delta("correction_rate"),
            "access_failure_rate_delta":delta("access_failure_rate"),
            "field_coverage_rate_delta":delta("field_coverage_rate"),
            "known_field_rate_delta":delta("known_field_rate"),
            "source_yield_rate_delta":delta("source_yield_rate"),
            "recovery_success_rate_delta":delta("recovery_success_rate"),
            "improved":{
                "correction_rate":(
                    after["correction_rate"] < before["correction_rate"]
                    if after["correction_rate"] is not None and before["correction_rate"] is not None else None
                ),
                "access_failure_rate":(
                    after["access_failure_rate"] < before["access_failure_rate"]
                    if after["access_failure_rate"] is not None and before["access_failure_rate"] is not None else None
                ),
                "field_coverage_rate":(
                    after["field_coverage_rate"] > before["field_coverage_rate"]
                    if after["field_coverage_rate"] is not None and before["field_coverage_rate"] is not None else None
                )
            }
        }

    return {
        "backlog":dict(b),
        "history":hist,
        "snapshots":snaps,
        "effect":effect
    }

def backlog_list(con):
    return [dict(x) for x in con.execute("""SELECT * FROM improvement_backlog_items
                                           ORDER BY CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                                           backlog_id""").fetchall()]
