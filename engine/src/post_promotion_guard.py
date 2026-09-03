import json
from .database import (
    active_full_promotion,full_promotion_rows,post_promotion_observation_rows,
    persist_post_promotion_guard,post_promotion_guard_rows,
    rollback_full_promotion,mark_full_promotion_stable,latest_canary_outcome,
    persist_promotion_lease_event
)
from .decision_quality import evaluate_goal_relevance

POLICY_VERSION="v0.35"
RECENT_SHORT=7
RECENT_LONG=14
MAX_RECENT7_DIVERGENCE=0.40
MAX_RECENT14_DIVERGENCE=0.30
MAX_DRIFT_FROM_CANARY=0.20
STABLE_MIN_SAMPLES=14

def _rate(rows):
    return round(sum(int(r["diverged"]) for r in rows)/len(rows),4) if rows else None

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        if x.get("reasons_json"):
            x["reasons_json"]=json.loads(x["reasons_json"])
        out.append(x)
    return out

def evaluate_post_promotion_guard(con, promotion_id, *, persist=True, enforce=True):
    promos=[r for r in full_promotion_rows(con) if r["promotion_id"]==promotion_id]
    if not promos:
        raise KeyError("full promotion not found")
    promo=promos[0]
    rows=post_promotion_observation_rows(con,promotion_id)
    recent7=rows[-RECENT_SHORT:]
    recent14=rows[-RECENT_LONG:]
    r7=_rate(recent7)
    r14=_rate(recent14)
    false_optimism=sum(int(r["false_optimism"]) for r in rows)

    canary=latest_canary_outcome(con,promo["lease_id"])
    canary_rate=canary["divergence_rate"] if canary else None
    drift=(round(r14-canary_rate,4)
           if r14 is not None and canary_rate is not None else None)

    decision_quality=evaluate_goal_relevance(con,promo["goal_profile"],persist=True)
    reasons=[]
    blocked=False
    if decision_quality["status"]=="BLOCKED":
        blocked=True
        reasons.append(
            "Decision Quality Guard BLOCKED: " + "; ".join(decision_quality["reasons"]))
    if false_optimism>0:
        blocked=True
        reasons.append(f"Post-promotion false optimism detected: {false_optimism}")
    if len(recent7)>=RECENT_SHORT and r7>MAX_RECENT7_DIVERGENCE:
        blocked=True
        reasons.append(
            f"Recent 7 divergence {r7} > {MAX_RECENT7_DIVERGENCE}")
    if len(recent14)>=RECENT_LONG and r14>MAX_RECENT14_DIVERGENCE:
        blocked=True
        reasons.append(
            f"Recent 14 divergence {r14} > {MAX_RECENT14_DIVERGENCE}")
    if len(recent14)>=RECENT_LONG and drift is not None and drift>MAX_DRIFT_FROM_CANARY:
        blocked=True
        reasons.append(
            f"Runtime drift from Canary {drift} > {MAX_DRIFT_FROM_CANARY}")

    stable=(not blocked and len(rows)>=STABLE_MIN_SAMPLES and
            (r14 is None or r14<=MAX_RECENT14_DIVERGENCE) and
            false_optimism==0)

    if blocked:
        status="BLOCKED"
    elif stable:
        status="STABLE_FULL"
        reasons.append("14+ safe runtime observations satisfy stable-full policy")
    else:
        status="OBSERVING"
        reasons.append(f"Runtime samples {len(rows)} < stable minimum {STABLE_MIN_SAMPLES}")

    result={
        "policy_version":POLICY_VERSION,
        "promotion_id":promotion_id,
        "goal_profile":promo["goal_profile"],
        "promotion_status_before":promo["status"],
        "status":status,
        "sample_count":len(rows),
        "recent7_count":len(recent7),
        "recent7_divergence_rate":r7,
        "recent14_count":len(recent14),
        "recent14_divergence_rate":r14,
        "false_optimism_count":false_optimism,
        "canary_divergence_rate":canary_rate,
        "drift_from_canary":drift,
        "stable_full":stable,
        "decision_quality":decision_quality,
        "reasons":reasons
    }

    if persist:
        gid=persist_post_promotion_guard(
            con,promotion_id=promotion_id,goal_profile=promo["goal_profile"],
            policy_version=POLICY_VERSION,status=status,sample_count=len(rows),
            recent7_count=len(recent7),recent7_divergence_rate=r7,
            recent14_count=len(recent14),recent14_divergence_rate=r14,
            false_optimism_count=false_optimism,
            canary_divergence_rate=canary_rate,drift_from_canary=drift,
            stable_full=stable,reasons=reasons)
        result["guard_id"]=gid

    if enforce and blocked and promo["status"] in ("ACTIVE","STABLE_FULL"):
        rollback_full_promotion(
            con,promo["goal_profile"],actor="post-promotion-runtime-guard",
            reason="; ".join(reasons))
        persist_promotion_lease_event(
            con,lease_id=promo["lease_id"],event_type="POST_PROMOTION_GUARD_BLOCK",
            actor="post-promotion-runtime-guard",
            detail={"promotion_id":promotion_id,"reasons":reasons})
        result["action"]="FAIL_CLOSED_ROLLBACK"
        result["promotion_status_after"]="ROLLED_BACK"
    elif enforce and stable and promo["status"]=="ACTIVE":
        mark_full_promotion_stable(con,promotion_id)
        persist_promotion_lease_event(
            con,lease_id=promo["lease_id"],event_type="FULL_PROMOTION_STABLE",
            actor="post-promotion-runtime-guard",
            detail={"promotion_id":promotion_id,"sample_count":len(rows)})
        result["action"]="MARK_STABLE_FULL"
        result["promotion_status_after"]="STABLE_FULL"
    else:
        result["action"]="NONE"
        result["promotion_status_after"]=promo["status"]
    return result

def post_promotion_guard_history(con, promotion_id=None):
    return _decode(post_promotion_guard_rows(con,promotion_id))

def post_promotion_health(con, goal_profile=None):
    promos=full_promotion_rows(con,goal_profile)
    out=[]
    for p in promos:
        rows=post_promotion_observation_rows(con,p["promotion_id"])
        guards=post_promotion_guard_rows(con,p["promotion_id"])
        latest=dict(guards[-1]) if guards else None
        if latest and latest.get("reasons_json"):
            latest["reasons_json"]=json.loads(latest["reasons_json"])
        out.append({
            "promotion_id":p["promotion_id"],
            "goal_profile":p["goal_profile"],
            "promotion_status":p["status"],
            "runtime_observations":len(rows),
            "latest_guard":latest
        })
    return out
