import json
from datetime import datetime, timezone

from .database import (
    create_preventive_quarantine,active_preventive_quarantine,
    latest_preventive_quarantine,preventive_quarantine_rows,
    persist_preventive_quarantine_event,preventive_quarantine_event_rows,
    persist_preventive_reintegration_evaluation,
    preventive_reintegration_evaluation_rows,
    release_preventive_quarantine,
    persist_preventive_quarantine_release_review,
    preventive_quarantine_release_review_rows,
    preventive_recovery_case_row
)

POLICY_VERSION="v0.48"
MIN_QUARANTINE_HOURS=24.0
MIN_SHADOW_DECISIONS=7
MIN_CONFIRMED_OUTCOMES=7
MAX_FALSE_HOLD_RATE=0.10
MIN_INDEPENDENT_ALTERNATIVE_DECISIONS=3
MAX_REINTEGRATION_CANARY_DECISIONS=3
SAFE_OUTCOMES={"PREVENTED_CRITICAL_FAILURE","CORRECT_ALLOW"}

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        for f in ("metadata_json","detail_json","reasons_json"):
            if f in x and x.get(f):
                try: x[f]=json.loads(x[f])
                except Exception: pass
        out.append(x)
    return out

def should_quarantine(con,recovery_case_id):
    case=preventive_recovery_case_row(con,recovery_case_id)
    if not case:
        raise KeyError("recovery case not found")

    # A new rollback after a previously REQUALIFIED RESTRICTED recovery is the
    # primary v0.45 quarantine trigger. Four or more recurrence cycles are
    # quarantined regardless, so repeated failures cannot escape by changing labels.
    prior=con.execute("""SELECT rc.recovery_case_id,rc.status,
                               MAX(re.risk_band) risk_band
      FROM preventive_recovery_cases rc
      LEFT JOIN preventive_recurrence_evaluations re
        ON re.recovery_case_id=rc.recovery_case_id
      WHERE rc.source_id=? AND rc.rule_key=? AND rc.recovery_case_id<?
      GROUP BY rc.recovery_case_id,rc.status
      ORDER BY rc.recovery_case_id""",
      (case["source_id"],case["rule_key"],recovery_case_id)).fetchall()

    prior_restricted_requalified=any(
        r["status"]=="REQUALIFIED" and r["risk_band"]=="RESTRICTED"
        for r in prior
    )
    count=con.execute("""SELECT COUNT(*) n FROM preventive_recovery_cases
      WHERE source_id=? AND rule_key=? AND recovery_case_id<=?""",
      (case["source_id"],case["rule_key"],recovery_case_id)).fetchone()["n"]

    trigger=prior_restricted_requalified or count>=4
    reasons=[]
    if prior_restricted_requalified:
        reasons.append("critical failure recurred after RESTRICTED recovery was human-requalified")
    if count>=4:
        reasons.append(f"recurrence_count={count} reached mandatory quarantine threshold")
    return {"trigger":trigger,"recurrence_count":count,
            "prior_restricted_requalified":prior_restricted_requalified,
            "reasons":reasons}

def maybe_open_quarantine(con,recovery_case_id):
    case=preventive_recovery_case_row(con,recovery_case_id)
    if not case:
        raise KeyError("recovery case not found")
    trigger=should_quarantine(con,recovery_case_id)
    if not trigger["trigger"]:
        return {"quarantined":False,"trigger":trigger}

    qid,created=create_preventive_quarantine(
        con,source_id=case["source_id"],rule_key=case["rule_key"],
        trigger_recovery_case_id=recovery_case_id,
        trigger_reason="; ".join(trigger["reasons"]),
        metadata={"policy_version":POLICY_VERSION,"trigger":trigger})
    return {"quarantined":True,"created":created,"quarantine_id":qid,
            "source_id":case["source_id"],"rule_key":case["rule_key"],
            "trigger":trigger}

def evaluate_reintegration(con,quarantine_id):
    q=con.execute("SELECT * FROM preventive_quarantines WHERE quarantine_id=?",
                  (quarantine_id,)).fetchone()
    if not q:
        raise KeyError("quarantine not found")

    started=datetime.fromisoformat(q["started_at"])
    now=datetime.now(timezone.utc)
    elapsed=max(0.0,(now-started).total_seconds()/3600.0)

    decisions=con.execute("""SELECT * FROM preventive_verification_decisions
      WHERE source_id=? AND rule_key=? AND evaluated_at>=?
        AND production_mode='QUARANTINE_SHADOW'
      ORDER BY decision_id""",
      (q["source_id"],q["rule_key"],q["started_at"])).fetchall()
    ids=[d["decision_id"] for d in decisions]
    outcomes=[]
    if ids:
        marks=",".join("?" for _ in ids)
        outcomes=con.execute(
            f"""SELECT * FROM preventive_policy_outcomes
                WHERE decision_id IN ({marks}) ORDER BY outcome_id""",ids).fetchall()

    n_dec=len(decisions)
    n_out=len(outcomes)
    safe=sum(r["outcome_class"] in SAFE_OUTCOMES for r in outcomes)
    missed=sum(r["outcome_class"]=="MISSED_CRITICAL_FAILURE" for r in outcomes)
    false_hold=sum(r["outcome_class"]=="FALSE_CONSERVATIVE_HOLD" for r in outcomes)
    false_rate=(false_hold/n_out) if n_out else None
    independent=sum(int(d["independent_source_count"])>=2 for d in decisions)

    recovery=preventive_recovery_case_row(con,q["trigger_recovery_case_id"])
    recovery_requalified=bool(recovery and recovery["status"]=="REQUALIFIED")

    reasons=[]
    if elapsed<MIN_QUARANTINE_HOURS:
        reasons.append(f"quarantine elapsed {elapsed:.1f}h < {MIN_QUARANTINE_HOURS:.0f}h")
    if n_dec<MIN_SHADOW_DECISIONS:
        reasons.append(f"need >= {MIN_SHADOW_DECISIONS} quarantine shadow decisions")
    if n_out<MIN_CONFIRMED_OUTCOMES:
        reasons.append(f"need >= {MIN_CONFIRMED_OUTCOMES} human-confirmed outcomes")
    if independent<MIN_INDEPENDENT_ALTERNATIVE_DECISIONS:
        reasons.append(
            f"need >= {MIN_INDEPENDENT_ALTERNATIVE_DECISIONS} decisions with independent-source alternative coverage")
    if missed:
        reasons.append("MISSED_CRITICAL_FAILURE exists in quarantine window")
    if false_rate is not None and false_rate>MAX_FALSE_HOLD_RATE:
        reasons.append(
            f"false conservative hold rate {false_rate:.3f} > {MAX_FALSE_HOLD_RATE:.2f}")
    if safe<n_out:
        reasons.append(f"safe outcomes {safe}/{n_out}; all confirmed outcomes must be safe")
    if not recovery_requalified:
        reasons.append("trigger Recovery Case must be human REQUALIFIED")

    ready=(
        elapsed>=MIN_QUARANTINE_HOURS
        and n_dec>=MIN_SHADOW_DECISIONS
        and n_out>=MIN_CONFIRMED_OUTCOMES
        and independent>=MIN_INDEPENDENT_ALTERNATIVE_DECISIONS
        and missed==0
        and (false_rate is None or false_rate<=MAX_FALSE_HOLD_RATE)
        and safe==n_out
        and recovery_requalified
    )
    status="READY_FOR_RELEASE_REVIEW" if ready else "OBSERVING"
    if ready:
        reasons=["quarantine duration, recovery, shadow evidence, and independent alternative coverage satisfy release gate"]

    eid=persist_preventive_reintegration_evaluation(
        con,quarantine_id=quarantine_id,shadow_decision_count=n_dec,
        confirmed_outcome_count=n_out,safe_outcome_count=safe,
        missed_critical_count=missed,false_hold_count=false_hold,
        false_hold_rate=false_rate,independent_alternative_count=independent,
        elapsed_hours=elapsed,recovery_requalified=recovery_requalified,
        status=status,reasons=reasons)
    return {
        "reintegration_evaluation_id":eid,"quarantine_id":quarantine_id,
        "shadow_decision_count":n_dec,"confirmed_outcome_count":n_out,
        "safe_outcome_count":safe,"missed_critical_count":missed,
        "false_hold_count":false_hold,"false_hold_rate":false_rate,
        "independent_alternative_count":independent,
        "elapsed_hours":elapsed,"recovery_requalified":recovery_requalified,
        "status":status,"reasons":reasons
    }

def release_review(con, *, quarantine_id,decision,reviewer,reason):
    decision=decision.upper()
    if decision not in {"APPROVE","DENY","HOLD"}:
        raise ValueError("decision must be APPROVE, DENY, or HOLD")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason are required")
    q=con.execute("SELECT * FROM preventive_quarantines WHERE quarantine_id=?",
                  (quarantine_id,)).fetchone()
    if not q:
        raise KeyError("quarantine not found")
    gate=evaluate_reintegration(con,quarantine_id)
    if decision=="APPROVE":
        if q["status"]!="ACTIVE":
            raise ValueError("quarantine is not ACTIVE")
        if gate["status"]!="READY_FOR_RELEASE_REVIEW":
            raise ValueError("Reintegration Gate is not READY_FOR_RELEASE_REVIEW")
        release_preventive_quarantine(con,quarantine_id,reviewer,reason)
    rid=persist_preventive_quarantine_release_review(
        con,quarantine_id=quarantine_id,decision=decision,reviewer=reviewer,
        reason=reason,reintegration_evaluation_id=gate["reintegration_evaluation_id"])
    return {"release_review_id":rid,"quarantine_id":quarantine_id,
            "decision":decision,"gate":gate,
            "quarantine_status":"RELEASED" if decision=="APPROVE" else q["status"]}

def production_override(con,source_id,rule_key,existing_verified=False):
    if existing_verified:
        return None
    q=active_preventive_quarantine(con,source_id,rule_key)
    if not q:
        return None
    return {"quarantine_id":q["quarantine_id"],
            "production_mode":"QUARANTINE_SHADOW",
            "production_action":"QUARANTINE_HOLD",
            "reason":f"Source/Rule is quarantined by Quarantine #{q['quarantine_id']}"}

def canary_constraint(con,source_id,rule_key,max_decisions):
    active=active_preventive_quarantine(con,source_id,rule_key)
    if active:
        raise ValueError(
            f"Quarantine #{active['quarantine_id']} is ACTIVE; Production Canary is blocked")
    latest=latest_preventive_quarantine(con,source_id,rule_key)
    if latest and latest["status"]=="RELEASED":
        if int(max_decisions)>MAX_REINTEGRATION_CANARY_DECISIONS:
            raise ValueError(
                f"first Canary after Quarantine release is limited to "
                f"{MAX_REINTEGRATION_CANARY_DECISIONS} decisions")
        return {"reintegration":True,"quarantine_id":latest["quarantine_id"],
                "max_decisions":int(max_decisions)}
    return {"reintegration":False,"quarantine_id":None,
            "max_decisions":int(max_decisions)}

def quarantines(con,status=None):
    return _decode(preventive_quarantine_rows(con,status))

def quarantine_events(con,quarantine_id=None):
    return _decode(preventive_quarantine_event_rows(con,quarantine_id))

def reintegration_evaluations(con,quarantine_id=None):
    return _decode(preventive_reintegration_evaluation_rows(con,quarantine_id))

def release_reviews(con,quarantine_id=None):
    return [dict(r) for r in preventive_quarantine_release_review_rows(con,quarantine_id)]

def evaluate_active_quarantines(con):
    rows=con.execute("""SELECT quarantine_id FROM preventive_quarantines
                       WHERE status='ACTIVE' ORDER BY quarantine_id""").fetchall()
    results=[evaluate_reintegration(con,r["quarantine_id"]) for r in rows]
    return {"policy_version":POLICY_VERSION,"active_quarantine_count":len(rows),
            "evaluations":results}
