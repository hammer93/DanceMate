import json
from .database import (
    persist_decision_quality_observation,decision_quality_rows,
    persist_goal_relevance_diagnostic,goal_relevance_diagnostic_rows
)

POLICY_VERSION="v0.36"
OUTCOMES={"SUCCESS","FAILURE","UNKNOWN"}
CRITICAL_ERRORS={"FALSE_VERIFIED","CANCELLATION_MISS"}
MIN_DIAGNOSTIC_SAMPLES=5
MAX_FAILED_DECISION_RATE=0.20
MIN_CORE_RELEVANCE_RATE=0.60

def record_decision_quality(con, *, goal_profile, decision_outcome, event_truth,
                            decision_action=None,source_confidence=None,
                            critical_error_type=None,core_relevance=1.0,
                            user_impact=1.0,change_id=None,event_id=None,
                            metadata=None):
    decision_outcome=decision_outcome.upper()
    if decision_outcome not in OUTCOMES:
        raise ValueError("decision_outcome must be SUCCESS, FAILURE, or UNKNOWN")
    if critical_error_type:
        critical_error_type=critical_error_type.upper()
    if not 0.0<=float(core_relevance)<=1.0:
        raise ValueError("core_relevance must be between 0 and 1")
    if not 0.0<=float(user_impact)<=1.0:
        raise ValueError("user_impact must be between 0 and 1")
    oid=persist_decision_quality_observation(
        con,goal_profile=goal_profile,decision_outcome=decision_outcome,
        event_truth=event_truth,decision_action=decision_action,
        source_confidence=source_confidence,critical_error_type=critical_error_type,
        core_relevance=core_relevance,user_impact=user_impact,
        change_id=change_id,event_id=event_id,metadata=metadata)
    return {"decision_observation_id":oid,"goal_profile":goal_profile,
            "decision_outcome":decision_outcome,
            "critical_error_type":critical_error_type}

def evaluate_goal_relevance(con, goal_profile, *, persist=True):
    rows=decision_quality_rows(con,goal_profile)
    n=len(rows)
    if not n:
        result={"goal_profile":goal_profile,"sample_count":0,
                "status":"NO_DATA","reasons":["No decision-quality observations"]}
        return result

    success=sum(int(r["successful_decision"]) for r in rows)
    failed=sum(int(r["failed_decision"]) for r in rows)
    known=success+failed
    core=sum(float(r["core_relevance"]) for r in rows)/n
    success_rate=round(success/known,4) if known else None
    failed_rate=round(failed/known,4) if known else None
    critical=[r for r in rows if r["critical_error_type"] in CRITICAL_ERRORS]
    fv=sum(r["critical_error_type"]=="FALSE_VERIFIED" for r in rows)
    cm=sum(r["critical_error_type"]=="CANCELLATION_MISS" for r in rows)
    support=sum(float(r["core_relevance"])<0.5 for r in rows)

    reasons=[]
    if critical:
        status="BLOCKED"
        reasons.append(f"Critical decision errors detected: {len(critical)}")
    elif n<MIN_DIAGNOSTIC_SAMPLES:
        status="OBSERVING"
        reasons.append(f"Decision samples {n} < minimum {MIN_DIAGNOSTIC_SAMPLES}")
    elif failed_rate is not None and failed_rate>MAX_FAILED_DECISION_RATE:
        status="BLOCKED"
        reasons.append(
            f"Failed Dance Decision rate {failed_rate} > {MAX_FAILED_DECISION_RATE}")
    elif core<MIN_CORE_RELEVANCE_RATE:
        status="GOAL_MISMATCH"
        reasons.append(
            f"Core relevance {round(core,4)} < {MIN_CORE_RELEVANCE_RATE}; "
            "support-only movement dominates")
    else:
        status="HEALTHY"
        reasons.append("Decision quality and goal relevance satisfy v0.36 policy")

    result={
        "policy_version":POLICY_VERSION,"goal_profile":goal_profile,
        "sample_count":n,"core_relevance_rate":round(core,4),
        "successful_decision_rate":success_rate,"failed_decision_rate":failed_rate,
        "critical_error_count":len(critical),"false_verified_count":fv,
        "cancellation_miss_count":cm,"support_only_count":support,
        "status":status,"reasons":reasons
    }
    if persist:
        did=persist_goal_relevance_diagnostic(
            con,goal_profile=goal_profile,scope_key=goal_profile,sample_count=n,
            core_relevance_rate=result["core_relevance_rate"],
            successful_decision_rate=success_rate,failed_decision_rate=failed_rate,
            critical_error_count=len(critical),false_verified_count=fv,
            cancellation_miss_count=cm,support_only_count=support,
            status=status,reasons=reasons)
        result["diagnostic_id"]=did
    return result

def decision_quality_history(con, goal_profile=None):
    out=[]
    for r in decision_quality_rows(con,goal_profile):
        x=dict(r); x["metadata_json"]=json.loads(x["metadata_json"] or "{}"); out.append(x)
    return out

def goal_relevance_history(con, goal_profile=None):
    out=[]
    for r in goal_relevance_diagnostic_rows(con,goal_profile):
        x=dict(r); x["reasons_json"]=json.loads(x["reasons_json"] or "[]"); out.append(x)
    return out
