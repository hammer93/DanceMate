import json
from .database import (
    promotion_lease_row,promotion_lease_event_rows,persist_canary_outcome_evaluation,
    latest_canary_outcome,canary_outcome_rows,persist_final_promotion_review,
    final_promotion_review_rows,extend_promotion_lease,create_full_promotion,
    full_promotion_rows,active_full_promotion,rollback_promotion_lease,
    rollback_full_promotion,update_promotion_candidate_status,
    persist_promotion_lease_event
)

POLICY_VERSION="v0.34"
MIN_SAFE_COMPLETIONS=3
MAX_DIVERGENCE_RATE=0.40
FINAL_DECISIONS={"PROMOTE","EXTEND","ROLLBACK"}

def _decode(rows, fields):
    out=[]
    for row in rows:
        item=dict(row)
        for f in fields:
            if item.get(f):
                try:
                    item[f]=json.loads(item[f])
                except Exception:
                    pass
        out.append(item)
    return out

def _outcome_events(con, lease_id):
    rows=promotion_lease_event_rows(con,lease_id)
    out=[]
    seen=set()
    for r in rows:
        if r["event_type"]!="CANARY_OUTCOME":
            continue
        if r["change_id"] in seen:
            continue
        seen.add(r["change_id"])
        detail=json.loads(r["detail_json"] or "{}")
        out.append((r,detail))
    return out

def evaluate_canary_outcome(con, lease_id, persist=True):
    lease=promotion_lease_row(con,lease_id)
    if not lease:
        raise KeyError("promotion lease not found")

    events=_outcome_events(con,lease_id)
    completed=len(events)
    safe=0
    divergent=0
    false_optimism=0
    base_improved=0
    canary_improved=0

    for _,d in events:
        b=d.get("base_verdict")
        c=d.get("canary_verdict")
        if b=="IMPROVED":
            base_improved+=1
        if c=="IMPROVED":
            canary_improved+=1
        if b!=c:
            divergent+=1
        if b!="IMPROVED" and c=="IMPROVED":
            false_optimism+=1
        else:
            safe+=1

    divergence_rate=round(divergent/completed,4) if completed else None
    criteria={
        "minimum_safe_completions":MIN_SAFE_COMPLETIONS,
        "maximum_divergence_rate":MAX_DIVERGENCE_RATE,
        "false_optimism_allowed":0,
        "lease_must_be_exhausted_for_final_promotion":True,
        "automatic_final_promotion":False
    }
    reasons=[]

    if false_optimism>0:
        status="BLOCKED"
        reasons.append(f"False optimism detected: {false_optimism}")
    elif lease["status"]=="ROLLED_BACK":
        status="BLOCKED"
        reasons.append("Canary lease is ROLLED_BACK")
    elif completed<MIN_SAFE_COMPLETIONS:
        status="OBSERVING"
        reasons.append(f"Safe Canary outcomes {completed} < minimum {MIN_SAFE_COMPLETIONS}")
    elif divergence_rate is not None and divergence_rate>MAX_DIVERGENCE_RATE:
        status="OBSERVING"
        reasons.append(
            f"Canary divergence rate {divergence_rate} > maximum {MAX_DIVERGENCE_RATE}")
    elif lease["status"]!="EXHAUSTED":
        status="OBSERVING"
        reasons.append(
            f"Canary outcome is safe so far, but lease status is {lease['status']}; "
            "EXHAUSTED required before final promotion")
    else:
        status="READY_FOR_FINAL_REVIEW"
        reasons.append(
            "Canary lease exhausted with sufficient safe outcomes and no false optimism")

    result={
        "policy_version":POLICY_VERSION,
        "lease_id":lease_id,
        "candidate_id":lease["candidate_id"],
        "goal_profile":lease["goal_profile"],
        "lease_status":lease["status"],
        "status":status,
        "completed_changes":completed,
        "safe_changes":safe,
        "divergent_changes":divergent,
        "divergence_rate":divergence_rate,
        "false_optimism_count":false_optimism,
        "base_improved_count":base_improved,
        "canary_improved_count":canary_improved,
        "criteria":criteria,
        "automatic_final_promotion":False,
        "reasons":reasons
    }
    if persist:
        oid=persist_canary_outcome_evaluation(
            con,lease_id=lease_id,policy_version=POLICY_VERSION,status=status,
            completed_changes=completed,safe_changes=safe,
            divergent_changes=divergent,divergence_rate=divergence_rate,
            false_optimism_count=false_optimism,
            base_improved_count=base_improved,canary_improved_count=canary_improved,
            criteria=criteria,reasons=reasons)
        result["outcome_id"]=oid
    return result

def canary_outcome_history(con, lease_id=None):
    return _decode(canary_outcome_rows(con,lease_id),("criteria_json","reasons_json"))

def final_promotion_decision(con, *, lease_id, decision, reviewer,
                             reason=None, additional_changes=3):
    decision=decision.upper()
    if decision not in FINAL_DECISIONS:
        raise ValueError("decision must be PROMOTE, EXTEND, or ROLLBACK")
    if not reviewer:
        raise ValueError("reviewer is required")
    lease=promotion_lease_row(con,lease_id)
    if not lease:
        raise KeyError("promotion lease not found")

    outcome=evaluate_canary_outcome(con,lease_id,persist=True)
    metadata={
        "policy_version":POLICY_VERSION,
        "outcome_status":outcome["status"],
        "completed_changes":outcome["completed_changes"],
        "divergence_rate":outcome["divergence_rate"],
        "false_optimism_count":outcome["false_optimism_count"]
    }

    if decision=="PROMOTE":
        if outcome["status"]!="READY_FOR_FINAL_REVIEW":
            raise ValueError(
                f"cannot PROMOTE: Canary Outcome Gate is {outcome['status']}")
        adaptive=json.loads(lease["adaptive_weights_json"])
        base=json.loads(lease["base_weights_json"])
        pid=create_full_promotion(
            con,lease_id=lease_id,candidate_id=lease["candidate_id"],
            goal_profile=lease["goal_profile"],policy_version=POLICY_VERSION,
            adaptive_weights=adaptive,base_weights=base,promoted_by=reviewer,
            metadata={
                **metadata,
                "human_final_approval":True,
                "rollback_available":True
            })
        con.execute("""UPDATE adaptive_promotion_leases
                       SET status='PROMOTED',ended_at=COALESCE(ended_at,datetime('now'))
                       WHERE lease_id=?""",(lease_id,))
        con.commit()
        update_promotion_candidate_status(
            con,lease["candidate_id"],"PROMOTED",
            reason=f"Final PROMOTE by {reviewer}")
        persist_promotion_lease_event(
            con,lease_id=lease_id,event_type="FULL_PROMOTION_STARTED",
            actor=reviewer,detail={"promotion_id":pid,"reason":reason})
        fid=persist_final_promotion_review(
            con,lease_id=lease_id,candidate_id=lease["candidate_id"],
            goal_profile=lease["goal_profile"],decision=decision,reviewer=reviewer,
            reason=reason,outcome_id=outcome["outcome_id"],metadata=metadata)
        return {
            "final_review_id":fid,"decision":"PROMOTE",
            "promotion_id":pid,"status":"FULL_PROMOTION_ACTIVE",
            "goal_profile":lease["goal_profile"],
            "human_final_approval":True
        }

    if decision=="EXTEND":
        if outcome["status"]=="BLOCKED":
            raise ValueError("cannot EXTEND a BLOCKED Canary outcome")
        if lease["status"] not in ("ACTIVE","EXHAUSTED"):
            raise ValueError(f"cannot EXTEND lease in status {lease['status']}")
        new_max=extend_promotion_lease(
            con,lease_id,additional_changes=additional_changes,
            actor=reviewer,reason=reason)
        fid=persist_final_promotion_review(
            con,lease_id=lease_id,candidate_id=lease["candidate_id"],
            goal_profile=lease["goal_profile"],decision=decision,reviewer=reviewer,
            reason=reason,outcome_id=outcome["outcome_id"],
            metadata={**metadata,"additional_changes":additional_changes})
        return {
            "final_review_id":fid,"decision":"EXTEND",
            "lease_id":lease_id,"status":"ACTIVE",
            "new_max_canary_changes":new_max
        }

    # ROLLBACK is always allowed for safety.
    rolled=rollback_promotion_lease(
        con,lease_id,actor=reviewer,
        reason=reason or "Final review rollback")
    full=rollback_full_promotion(
        con,lease["goal_profile"],actor=reviewer,
        reason=reason or "Final review rollback")
    update_promotion_candidate_status(
        con,lease["candidate_id"],"ROLLED_BACK",
        reason=f"Final ROLLBACK by {reviewer}: {reason or 'no reason'}")
    fid=persist_final_promotion_review(
        con,lease_id=lease_id,candidate_id=lease["candidate_id"],
        goal_profile=lease["goal_profile"],decision=decision,reviewer=reviewer,
        reason=reason,outcome_id=outcome.get("outcome_id"),metadata=metadata)
    return {
        "final_review_id":fid,"decision":"ROLLBACK",
        "lease_rolled_back":bool(rolled),
        "full_promotion_rolled_back":full is not None,
        "status":"ROLLED_BACK"
    }

def final_promotion_reviews(con, lease_id=None):
    return _decode(final_promotion_review_rows(con,lease_id),("metadata_json",))

def full_promotions(con, goal_profile=None):
    return _decode(
        full_promotion_rows(con,goal_profile),
        ("adaptive_weights_json","base_weights_json","metadata_json"))

def rollback_active_full_promotion(con, *, goal_profile, actor, reason):
    pid=rollback_full_promotion(con,goal_profile,actor=actor,reason=reason)
    return {
        "goal_profile":goal_profile,
        "promotion_id":pid,
        "rolled_back":pid is not None,
        "reason":reason
    }
