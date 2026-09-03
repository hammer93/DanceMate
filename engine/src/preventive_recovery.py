import json

from .database import (
    create_preventive_recovery_case,preventive_recovery_case_row,
    preventive_recovery_case_rows,latest_preventive_recovery_case,
    update_preventive_recovery_root_cause,update_preventive_recovery_remediation,
    persist_preventive_recovery_evaluation,preventive_recovery_evaluation_rows,
    mark_preventive_recovery_requalified,preventive_recovery_event_rows
)

POLICY_VERSION="v0.48"
MIN_RECOVERY_SHADOW_DECISIONS=3
MIN_CONFIRMED_RECOVERY_OUTCOMES=3
MAX_FALSE_CONSERVATIVE_HOLD_RATE=0.25
SAFE_OUTCOMES={"PREVENTED_CRITICAL_FAILURE","CORRECT_ALLOW"}

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        for f in ("metadata_json","reasons_json","detail_json"):
            if f in x and x.get(f):
                try: x[f]=json.loads(x[f])
                except Exception: pass
        out.append(x)
    return out

def open_recovery_case(con, *, promotion_id,rollback_reason):
    p=con.execute("""SELECT * FROM preventive_full_promotions
                     WHERE promotion_id=?""",(promotion_id,)).fetchone()
    if not p:
        raise KeyError("Full Preventive promotion not found")
    rid,created=create_preventive_recovery_case(
        con,source_id=p["source_id"],rule_key=p["rule_key"],
        failed_promotion_id=promotion_id,rollback_reason=rollback_reason,
        metadata={"policy_version":POLICY_VERSION,
                  "canary_id":p["canary_id"],
                  "opened_by":"automatic_runtime_rollback"})
    from .preventive_recurrence import recurrence_policy
    recurrence=recurrence_policy(con,rid)
    from .preventive_quarantine import maybe_open_quarantine
    quarantine=maybe_open_quarantine(con,rid)
    return {"recovery_case_id":rid,"created":created,
            "source_id":p["source_id"],"rule_key":p["rule_key"],
            "failed_promotion_id":promotion_id,"status":"OPEN",
            "recurrence":recurrence,"quarantine":quarantine}

def record_root_cause(con, *, recovery_case_id,root_cause,actor):
    if not root_cause or not actor:
        raise ValueError("root_cause and actor are required")
    if not preventive_recovery_case_row(con,recovery_case_id):
        raise KeyError("recovery case not found")
    update_preventive_recovery_root_cause(con,recovery_case_id,root_cause,actor)
    from .preventive_recurrence import recurrence_policy
    recurrence_policy(con,recovery_case_id)
    return dict(preventive_recovery_case_row(con,recovery_case_id))

def record_remediation(con, *, recovery_case_id,remediation_ref,actor,notes=None):
    if not remediation_ref or not actor:
        raise ValueError("remediation_ref and actor are required")
    if not preventive_recovery_case_row(con,recovery_case_id):
        raise KeyError("recovery case not found")
    update_preventive_recovery_remediation(
        con,recovery_case_id,remediation_ref,notes,actor)
    from .preventive_recurrence import recurrence_policy
    recurrence_policy(con,recovery_case_id)
    return dict(preventive_recovery_case_row(con,recovery_case_id))

def evaluate_recovery(con,recovery_case_id):
    case=preventive_recovery_case_row(con,recovery_case_id)
    if not case:
        raise KeyError("recovery case not found")

    from .preventive_recurrence import recurrence_policy,exception_is_approved
    recurrence=recurrence_policy(con,recovery_case_id)
    required_shadow=recurrence["required_shadow_decisions"]
    required_outcomes=recurrence["required_confirmed_outcomes"]
    max_false_hold=recurrence["max_false_hold_rate"]
    exception_required=recurrence["human_exception_required"]
    exception_approved=exception_is_approved(con,recovery_case_id)

    decisions=con.execute("""SELECT * FROM preventive_verification_decisions
      WHERE source_id=? AND rule_key=? AND evaluated_at>?
        AND production_mode IN ('BASE_WITH_SHADOW','QUARANTINE_SHADOW')
      ORDER BY decision_id""",
      (case["source_id"],case["rule_key"],case["opened_at"])).fetchall()
    decision_ids=[r["decision_id"] for r in decisions]

    outcomes=[]
    if decision_ids:
        marks=",".join("?" for _ in decision_ids)
        outcomes=con.execute(
            f"""SELECT * FROM preventive_policy_outcomes
                WHERE decision_id IN ({marks}) ORDER BY outcome_id""",
            decision_ids).fetchall()

    n_dec=len(decisions)
    n_out=len(outcomes)
    safe=sum(r["outcome_class"] in SAFE_OUTCOMES for r in outcomes)
    missed=sum(r["outcome_class"]=="MISSED_CRITICAL_FAILURE" for r in outcomes)
    false_hold=sum(r["outcome_class"]=="FALSE_CONSERVATIVE_HOLD" for r in outcomes)
    false_rate=(false_hold/n_out) if n_out else None

    reasons=[]
    if not case["root_cause"]:
        reasons.append("Root Cause has not been recorded")
    if not case["remediation_ref"]:
        reasons.append("Remediation reference has not been recorded")
    if n_dec<required_shadow:
        reasons.append(
            f"need >= {required_shadow} post-rollback Shadow decisions for {recurrence['risk_band']}")
    if n_out<required_outcomes:
        reasons.append(
            f"need >= {required_outcomes} human-confirmed recovery outcomes for {recurrence['risk_band']}")
    if missed>0:
        reasons.append("MISSED_CRITICAL_FAILURE exists in recovery window")
    if false_rate is not None and false_rate>max_false_hold:
        reasons.append(
            f"false conservative hold rate {false_rate:.3f} > "
            f"{max_false_hold:.2f} for {recurrence['risk_band']}")
    if exception_required and not exception_approved:
        reasons.append("Human recurrence exception approval is required")
    if safe<n_out:
        reasons.append(f"safe outcomes {safe}/{n_out}; all recovery outcomes must be safe")

    ready=(
        bool(case["root_cause"]) and bool(case["remediation_ref"])
        and n_dec>=required_shadow
        and n_out>=required_outcomes
        and missed==0
        and (false_rate is None or false_rate<=max_false_hold)
        and safe==n_out
        and (not exception_required or exception_approved)
    )
    status="READY_FOR_REQUALIFICATION" if ready else "OBSERVING"
    if ready:
        reasons=["Root Cause + Remediation + post-rollback Shadow evidence satisfy re-qualification gate"]

    eid=persist_preventive_recovery_evaluation(
        con,recovery_case_id=recovery_case_id,shadow_decision_count=n_dec,
        confirmed_outcome_count=n_out,safe_outcome_count=safe,
        missed_critical_count=missed,false_conservative_hold_count=false_hold,
        false_conservative_hold_rate=false_rate,status=status,reasons=reasons)

    return {
        "recovery_evaluation_id":eid,"recovery_case_id":recovery_case_id,
        "source_id":case["source_id"],"rule_key":case["rule_key"],
        "shadow_decision_count":n_dec,"confirmed_outcome_count":n_out,
        "safe_outcome_count":safe,"missed_critical_count":missed,
        "false_conservative_hold_count":false_hold,
        "false_conservative_hold_rate":false_rate,
        "risk_band":recurrence["risk_band"],
        "recurrence_count":recurrence["recurrence_count"],
        "required_shadow_decisions":required_shadow,
        "required_confirmed_outcomes":required_outcomes,
        "max_false_hold_rate":max_false_hold,
        "human_exception_required":exception_required,
        "human_exception_approved":exception_approved,
        "remediation_effective":recurrence["remediation_effective"],
        "status":status,"reasons":reasons
    }

def requalify(con, *, recovery_case_id,actor):
    if not actor:
        raise ValueError("actor is required")
    case=preventive_recovery_case_row(con,recovery_case_id)
    if not case:
        raise KeyError("recovery case not found")
    result=evaluate_recovery(con,recovery_case_id)
    if result["status"]!="READY_FOR_REQUALIFICATION":
        raise ValueError("Recovery Gate is not READY_FOR_REQUALIFICATION")
    mark_preventive_recovery_requalified(con,recovery_case_id,actor)
    return {"recovery_case_id":recovery_case_id,"status":"REQUALIFIED",
            "requalified_by":actor,"gate":result}

def assert_canary_requalification_ready(con,source_id,rule_key):
    case=latest_preventive_recovery_case(con,source_id,rule_key)
    if not case:
        return {"required":False}
    if case["status"]!="REQUALIFIED":
        raise ValueError(
            f"Recovery Case #{case['recovery_case_id']} must be REQUALIFIED before a new Canary")
    return {"required":True,"recovery_case_id":case["recovery_case_id"],
            "status":case["status"]}

def recovery_cases(con,status=None):
    return _decode(preventive_recovery_case_rows(con,status))

def recovery_evaluations(con,recovery_case_id=None):
    return _decode(preventive_recovery_evaluation_rows(con,recovery_case_id))

def recovery_events(con,recovery_case_id=None):
    return _decode(preventive_recovery_event_rows(con,recovery_case_id))


def evaluate_active_recoveries(con):
    rows=con.execute("""SELECT recovery_case_id FROM preventive_recovery_cases
      WHERE status NOT IN ('REQUALIFIED','CLOSED')
      ORDER BY recovery_case_id""").fetchall()
    results=[]
    for r in rows:
        results.append(evaluate_recovery(con,r["recovery_case_id"]))
    return {"policy_version":POLICY_VERSION,"active_recovery_count":len(rows),
            "evaluations":results}
