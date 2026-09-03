import json
from .database import (
    promotion_candidate_row,update_promotion_candidate_status,persist_promotion_review,
    promotion_review_rows,create_promotion_lease,active_promotion_lease,
    promotion_lease_rows,promotion_lease_event_rows,persist_promotion_lease_event,
    rollback_promotion_lease
)
from .goal_weighting import get_base_weights,profile_status
from .rolling_shadow_stability import rolling_shadow_status

POLICY_VERSION="v0.33"
DECISIONS={"APPROVE","REJECT","HOLD"}
DEFAULT_CANARY_CHANGES=5

def _decode(rows, json_fields):
    out=[]
    for row in rows:
        item=dict(row)
        for k in json_fields:
            if item.get(k):
                try:
                    item[k]=json.loads(item[k])
                except Exception:
                    pass
        out.append(item)
    return out

def review_promotion_candidate(con, *, candidate_id, decision, reviewer,
                               reason=None, max_canary_changes=DEFAULT_CANARY_CHANGES):
    decision=decision.upper()
    if decision not in DECISIONS:
        raise ValueError("decision must be APPROVE, REJECT, or HOLD")
    if not reviewer:
        raise ValueError("reviewer is required")

    candidate=promotion_candidate_row(con,candidate_id)
    if not candidate:
        raise KeyError("promotion candidate not found")
    if candidate["status"] not in ("CANDIDATE","HOLD"):
        raise ValueError(f"candidate status {candidate['status']} cannot be reviewed")

    goal=candidate["goal_profile"]
    rolling=rolling_shadow_status(con,goal)

    metadata={
        "policy_version":POLICY_VERSION,
        "goal_profile":goal,
        "candidate_status_before":candidate["status"],
        "rolling_status":rolling["status"],
        "rolling_total_samples":rolling["total_samples"]
    }

    if decision=="HOLD":
        rid=persist_promotion_review(
            con,candidate_id=candidate_id,decision=decision,reviewer=reviewer,
            reason=reason,metadata=metadata)
        update_promotion_candidate_status(
            con,candidate_id,"HOLD",
            reason=f"HOLD by {reviewer}: {reason or 'no reason'}")
        return {
            "review_id":rid,"candidate_id":candidate_id,"decision":"HOLD",
            "candidate_status":"HOLD","lease":None,
            "rolling_status":rolling["status"]
        }

    if decision=="REJECT":
        rid=persist_promotion_review(
            con,candidate_id=candidate_id,decision=decision,reviewer=reviewer,
            reason=reason,metadata=metadata)
        update_promotion_candidate_status(
            con,candidate_id,"REJECTED",
            reason=f"REJECTED by {reviewer}: {reason or 'no reason'}")
        return {
            "review_id":rid,"candidate_id":candidate_id,"decision":"REJECT",
            "candidate_status":"REJECTED","lease":None,
            "rolling_status":rolling["status"]
        }

    # APPROVE: re-check the safety gate at decision time.
    if rolling["status"]!="ELIGIBLE":
        raise ValueError(
            f"candidate cannot be approved: rolling stability is {rolling['status']}")
    if active_promotion_lease(con,goal):
        raise ValueError("an active promotion lease already exists for this goal profile")
    if max_canary_changes<1 or max_canary_changes>20:
        raise ValueError("max_canary_changes must be between 1 and 20")

    adaptive=profile_status(con,goal)
    if adaptive["sample_count"]<10:
        raise ValueError("candidate cannot be approved: adaptive observations fewer than 10")

    base_weights=get_base_weights(goal)
    adaptive_weights=dict(adaptive["adaptive_weights"])

    rid=persist_promotion_review(
        con,candidate_id=candidate_id,decision=decision,reviewer=reviewer,
        reason=reason,metadata={
            **metadata,
            "adaptive_sample_count":adaptive["sample_count"],
            "max_canary_changes":max_canary_changes,
            "base_weights":base_weights,
            "adaptive_weights":adaptive_weights
        })

    lease_id=create_promotion_lease(
        con,candidate_id=candidate_id,goal_profile=goal,
        policy_version=POLICY_VERSION,max_canary_changes=max_canary_changes,
        adaptive_weights=adaptive_weights,base_weights=base_weights,
        approved_by=reviewer,
        metadata={
            "review_id":rid,
            "human_approved":True,
            "canary_only":True,
            "automatic_full_promotion":False
        })
    persist_promotion_lease_event(
        con,lease_id=lease_id,event_type="LEASE_STARTED",actor=reviewer,
        detail={"candidate_id":candidate_id,"max_canary_changes":max_canary_changes})
    update_promotion_candidate_status(
        con,candidate_id,"APPROVED_CANARY",
        reason=f"APPROVED_CANARY by {reviewer}")

    return {
        "review_id":rid,"candidate_id":candidate_id,"decision":"APPROVE",
        "candidate_status":"APPROVED_CANARY",
        "rolling_status":rolling["status"],
        "lease":{
            "lease_id":lease_id,"status":"ACTIVE","mode":"CANARY",
            "goal_profile":goal,"max_canary_changes":max_canary_changes,
            "human_approved":True
        }
    }

def rollback_active_goal_lease(con, *, goal_profile, actor, reason):
    row=active_promotion_lease(con,goal_profile)
    if not row:
        return {"goal_profile":goal_profile,"rolled_back":False,"reason":"no active lease"}
    ok=rollback_promotion_lease(
        con,row["lease_id"],actor=actor,reason=reason)
    return {
        "goal_profile":goal_profile,
        "lease_id":row["lease_id"],
        "rolled_back":ok,
        "reason":reason
    }

def promotion_review_history(con, candidate_id=None):
    return _decode(promotion_review_rows(con,candidate_id),("metadata_json",))

def promotion_leases(con, goal_profile=None):
    return _decode(
        promotion_lease_rows(con,goal_profile),
        ("adaptive_weights_json","base_weights_json","metadata_json"))

def promotion_lease_events(con, lease_id=None):
    return _decode(promotion_lease_event_rows(con,lease_id),("detail_json",))
