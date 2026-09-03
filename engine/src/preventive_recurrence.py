import json
import re

from .database import (
    preventive_recovery_case_row,
    preventive_recovery_case_rows,
    upsert_preventive_recurrence_profile,
    preventive_recurrence_profile_row,
    preventive_recurrence_profile_rows,
    persist_preventive_recurrence_evaluation,
    preventive_recurrence_evaluation_rows,
    persist_preventive_recurrence_exception,
    latest_preventive_recurrence_exception,
    preventive_recurrence_exception_rows
)

POLICY_VERSION="v0.48"

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        for f in ("reasons_json",):
            if f in x and x.get(f):
                try: x[f]=json.loads(x[f])
                except Exception: pass
        out.append(x)
    return out

def _normalize_root_cause(value):
    if not value:
        return ""
    return re.sub(r"\s+"," ",value.strip().lower())

def recurrence_policy(con,recovery_case_id):
    case=preventive_recovery_case_row(con,recovery_case_id)
    if not case:
        raise KeyError("recovery case not found")

    cases=[
        r for r in preventive_recovery_case_rows(con)
        if r["source_id"]==case["source_id"] and r["rule_key"]==case["rule_key"]
        and r["recovery_case_id"]<=recovery_case_id
    ]
    recurrence_count=len(cases)
    prior=cases[:-1]

    current_rc=_normalize_root_cause(case["root_cause"])
    repeated=False
    if current_rc:
        repeated=any(
            _normalize_root_cause(r["root_cause"])==current_rc
            for r in prior if r["root_cause"]
        )

    prior_requalified=[
        r for r in prior
        if r["status"]=="REQUALIFIED" and r["remediation_ref"]
    ]
    requalified_failure_count=len(prior_requalified)
    ineffective_remediation_count=requalified_failure_count

    previous_remediation_ref=(
        prior_requalified[-1]["remediation_ref"] if prior_requalified else None
    )
    if recurrence_count==1:
        remediation_effective="NOT_APPLICABLE"
    elif prior_requalified:
        remediation_effective="INEFFECTIVE"
    else:
        remediation_effective="UNKNOWN"

    if recurrence_count>=3 or repeated:
        risk_band="RESTRICTED"
        req_shadow=7
        req_outcomes=7
        max_false_hold=.10
        exception_required=True
        long_term_restricted=True
    elif recurrence_count==2:
        risk_band="ELEVATED"
        req_shadow=5
        req_outcomes=5
        max_false_hold=.20
        exception_required=False
        long_term_restricted=False
    else:
        risk_band="BASELINE"
        req_shadow=3
        req_outcomes=3
        max_false_hold=.25
        exception_required=False
        long_term_restricted=False

    reasons=[
        f"recurrence_count={recurrence_count}",
        f"risk_band={risk_band}",
        f"required_shadow_decisions={req_shadow}",
        f"required_confirmed_outcomes={req_outcomes}",
        f"max_false_hold_rate={max_false_hold:.2f}",
    ]
    if repeated:
        reasons.append("same normalized Root Cause repeated")
    if prior_requalified:
        reasons.append(
            f"{len(prior_requalified)} prior requalified remediation(s) were followed by another rollback")
    if exception_required:
        reasons.append("Human recurrence exception approval is required before re-qualification")

    pid=upsert_preventive_recurrence_profile(
        con,source_id=case["source_id"],rule_key=case["rule_key"],
        recurrence_count=recurrence_count,
        requalified_failure_count=requalified_failure_count,
        repeated_root_cause_count=1 if repeated else 0,
        ineffective_remediation_count=ineffective_remediation_count,
        risk_band=risk_band,long_term_restricted=long_term_restricted,
        reasons=reasons)

    eid=persist_preventive_recurrence_evaluation(
        con,recovery_case_id=recovery_case_id,source_id=case["source_id"],
        rule_key=case["rule_key"],recurrence_count=recurrence_count,
        repeated_root_cause=repeated,
        previous_remediation_ref=previous_remediation_ref,
        remediation_effective=remediation_effective,
        required_shadow_decisions=req_shadow,
        required_confirmed_outcomes=req_outcomes,
        max_false_hold_rate=max_false_hold,
        human_exception_required=exception_required,
        risk_band=risk_band,reasons=reasons)

    return {
        "recurrence_profile_id":pid,
        "recurrence_evaluation_id":eid,
        "recovery_case_id":recovery_case_id,
        "source_id":case["source_id"],"rule_key":case["rule_key"],
        "recurrence_count":recurrence_count,
        "repeated_root_cause":repeated,
        "requalified_failure_count":requalified_failure_count,
        "ineffective_remediation_count":ineffective_remediation_count,
        "previous_remediation_ref":previous_remediation_ref,
        "remediation_effective":remediation_effective,
        "risk_band":risk_band,
        "long_term_restricted":long_term_restricted,
        "required_shadow_decisions":req_shadow,
        "required_confirmed_outcomes":req_outcomes,
        "max_false_hold_rate":max_false_hold,
        "human_exception_required":exception_required,
        "reasons":reasons
    }

def approve_exception(con, *, recovery_case_id,decision,approved_by,reason):
    decision=decision.upper()
    if decision not in {"APPROVE","DENY"}:
        raise ValueError("decision must be APPROVE or DENY")
    if not approved_by or not reason:
        raise ValueError("approved_by and reason are required")
    case=preventive_recovery_case_row(con,recovery_case_id)
    if not case:
        raise KeyError("recovery case not found")
    policy=recurrence_policy(con,recovery_case_id)
    if not policy["human_exception_required"]:
        raise ValueError("this Recovery Case does not require a recurrence exception")
    xid=persist_preventive_recurrence_exception(
        con,recovery_case_id=recovery_case_id,source_id=case["source_id"],
        rule_key=case["rule_key"],decision=decision,
        approved_by=approved_by,reason=reason)
    return {"exception_id":xid,"recovery_case_id":recovery_case_id,
            "decision":decision,"approved_by":approved_by,
            "risk_band":policy["risk_band"]}

def exception_is_approved(con,recovery_case_id):
    row=latest_preventive_recurrence_exception(con,recovery_case_id)
    return bool(row and row["decision"]=="APPROVE")

def recurrence_profiles(con):
    return _decode(preventive_recurrence_profile_rows(con))

def recurrence_evaluations(con,recovery_case_id=None):
    return _decode(preventive_recurrence_evaluation_rows(con,recovery_case_id))

def recurrence_exceptions(con,recovery_case_id=None):
    return [dict(r) for r in preventive_recurrence_exception_rows(con,recovery_case_id)]
