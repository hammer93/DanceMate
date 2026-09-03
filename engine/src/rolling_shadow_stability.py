import json
from .database import (
    adaptive_shadow_rows_by_goal,
    persist_rolling_shadow_stability,
    latest_rolling_shadow_stability,
    rolling_shadow_stability_rows,
    create_or_get_promotion_candidate,
    revoke_active_promotion_candidate,
    promotion_candidate_rows,active_promotion_lease,rollback_promotion_lease
)
from .shadow_safety_gate import _classify_rows, shadow_safety_status

POLICY_VERSION="v0.32"
WINDOWS=(7,14,30)
MIN_AGREEMENT_RATE=0.90
MIN_PROMOTION_SAMPLES=20

def _window_status(stats, window_size, available_total):
    if stats["critical_false_improved"]>0 or stats["unsafe_improved"]>0:
        return "BLOCKED"
    if available_total < window_size:
        return "OBSERVING"
    if stats["agreement_rate"] is None or stats["agreement_rate"] < MIN_AGREEMENT_RATE:
        return "OBSERVING"
    return "STABLE"

def _window_summary(rows, window_size):
    recent=rows[-window_size:]
    stats=_classify_rows(recent)
    return {
        "window_size":window_size,
        "sample_count":len(recent),
        "status":_window_status(stats,window_size,len(rows)),
        **stats
    }

def _decode_row(row):
    if not row:
        return None
    item=dict(row)
    for k in ("windows_json","reasons_json","criteria_json"):
        if k in item and item.get(k):
            try:
                item[k]=json.loads(item[k])
            except Exception:
                pass
    return item

def evaluate_rolling_shadow_stability(con, goal_profile=None, persist=True,
                                      manage_candidate=True):
    rows=adaptive_shadow_rows_by_goal(con,goal_profile)
    cumulative=shadow_safety_status(con,goal_profile)
    windows={str(w):_window_summary(rows,w) for w in WINDOWS}

    previous=latest_rolling_shadow_stability(con,goal_profile)
    previous_status=previous["status"] if previous else None
    reasons=[]

    recent7=windows["7"]
    recent14=windows["14"]
    recent30=windows["30"]

    if cumulative["status"]=="BLOCKED":
        status="BLOCKED"
        reasons.append("Cumulative Shadow Safety Gate is BLOCKED")
    elif recent7["status"]=="BLOCKED" or recent14["status"]=="BLOCKED":
        status="BLOCKED"
        reasons.append("Recent 7/14 window contains unsafe Shadow optimism")
    elif cumulative["status"]!="ELIGIBLE":
        status="OBSERVING"
        reasons.append(f"Cumulative Safety status is {cumulative['status']}")
    elif recent7["status"]!="STABLE" or recent14["status"]!="STABLE":
        status="OBSERVING"
        reasons.append("Recent 7/14 windows are not both STABLE")
    elif len(rows)>=30 and recent30["status"]!="STABLE":
        status="OBSERVING"
        reasons.append("Recent 30 window is not STABLE")
    else:
        status="ELIGIBLE"
        reasons.append("Cumulative and recent rolling windows satisfy stability policy")

    downgrade_detected=(previous_status=="ELIGIBLE" and status=="BLOCKED")
    if downgrade_detected:
        reasons.append("ELIGIBLE → BLOCKED downgrade detected")

    result={
        "policy_version":POLICY_VERSION,
        "goal_profile":goal_profile,
        "status":status,
        "cumulative_status":cumulative["status"],
        "total_samples":len(rows),
        "previous_status":previous_status,
        "downgrade_detected":downgrade_detected,
        "windows":windows,
        "cumulative":cumulative,
        "promotion_candidate":None,
        "automatic_promotion":False,
        "reasons":reasons
    }

    rolling_id=None
    if persist:
        rolling_id=persist_rolling_shadow_stability(
            con,goal_profile=goal_profile,policy_version=POLICY_VERSION,
            status=status,cumulative_status=cumulative["status"],
            total_samples=len(rows),downgrade_detected=downgrade_detected,
            previous_status=previous_status,windows=windows,reasons=reasons)
        result["rolling_id"]=rolling_id

    if manage_candidate:
        candidate_criteria={
            "minimum_total_samples":MIN_PROMOTION_SAMPLES,
            "minimum_agreement_rate":MIN_AGREEMENT_RATE,
            "cumulative_status_required":"ELIGIBLE",
            "window_7_required":"STABLE",
            "window_14_required":"STABLE",
            "window_30_required":"STABLE when >=30 samples",
            "unsafe_improved_allowed":0,
            "automatic_promotion":False
        }

        if status=="ELIGIBLE" and len(rows)>=MIN_PROMOTION_SAMPLES:
            lease=active_promotion_lease(con,goal_profile) if goal_profile else None
            if lease:
                result["promotion_candidate"]={
                    "candidate_id":lease["candidate_id"],
                    "status":"ACTIVE_CANARY_LEASE",
                    "lease_id":lease["lease_id"],
                    "created":False,
                    "human_approval_required":False
                }
            else:
                cid,created=create_or_get_promotion_candidate(
                    con,goal_profile=goal_profile,policy_version=POLICY_VERSION,
                    rolling_id=rolling_id,total_samples=len(rows),
                    agreement_rate=cumulative["agreement_rate"],
                    unsafe_improved=cumulative["unsafe_improved"],
                    criteria=candidate_criteria,
                    reasons=["Rolling Shadow Stability Gate is ELIGIBLE; human approval still required"])
                result["promotion_candidate"]={
                    "candidate_id":cid,
                    "status":"CANDIDATE",
                    "created":created,
                    "human_approval_required":True
                }
        elif status=="BLOCKED":
            revoked=revoke_active_promotion_candidate(
                con,goal_profile,
                reason="Revoked because Rolling Shadow Stability Gate became BLOCKED")
            if revoked:
                result["promotion_candidate"]={
                    "candidate_id":revoked,
                    "status":"REVOKED",
                    "created":False,
                    "human_approval_required":True
                }
            lease=active_promotion_lease(con,goal_profile) if goal_profile else None
            if lease:
                rolled=rollback_promotion_lease(
                    con,lease["lease_id"],actor="rolling-safety-gate",
                    reason="Automatic rollback: Rolling Shadow Stability Gate BLOCKED")
                result["lease_rollback"]={
                    "lease_id":lease["lease_id"],
                    "rolled_back":rolled,
                    "reason":"Rolling Shadow Stability Gate BLOCKED"
                }

    return result

def rolling_shadow_status(con, goal_profile=None):
    return evaluate_rolling_shadow_stability(
        con,goal_profile=goal_profile,persist=False,manage_candidate=False)

def rolling_shadow_history(con, goal_profile=None):
    return [_decode_row(r) for r in rolling_shadow_stability_rows(con,goal_profile)]

def promotion_candidates(con, goal_profile=None):
    return [_decode_row(r) for r in promotion_candidate_rows(con,goal_profile)]
