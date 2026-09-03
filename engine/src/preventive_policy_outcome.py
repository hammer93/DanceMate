import json
from .database import (
    persist_preventive_policy_outcome,preventive_policy_outcome_rows,
    persist_preventive_canary_safety_evaluation,preventive_canary_safety_rows,
    preventive_policy_canary_rows,create_preventive_full_promotion,
    preventive_full_promotion_rows,rollback_preventive_full_promotion,
    persist_preventive_final_review,preventive_final_review_rows,
    rollback_preventive_policy_canary
)

POLICY_VERSION="v0.48"
MIN_CANARY_OUTCOMES=3
MAX_FALSE_CONSERVATIVE_HOLD_RATE=0.25

HELD_ACTIONS={"REQUIRE_CORROBORATION","REQUIRE_HUMAN_AND_CORROBORATION"}
BAD_TRUTHS={"CANCELLED","EVENT_DID_NOT_OCCUR"}
GOOD_TRUTHS={"EVENT_OCCURRED","HELD"}

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        for f in ("rationale_json","reasons_json","metadata_json"):
            if f in x and x.get(f):
                try: x[f]=json.loads(x[f])
                except Exception: pass
        out.append(x)
    return out

def record_outcome(con, *, decision_id,event_truth,confirmed_by,outcome_key=None):
    if not confirmed_by:
        raise ValueError("confirmed_by is required")
    d=con.execute("SELECT * FROM preventive_verification_decisions WHERE decision_id=?",
                  (decision_id,)).fetchone()
    if not d: raise KeyError("preventive decision not found")
    truth=event_truth.upper()
    if truth not in GOOD_TRUTHS|BAD_TRUTHS:
        raise ValueError("event_truth must be EVENT_OCCURRED, HELD, CANCELLED, or EVENT_DID_NOT_OCCUR")

    base_action="ALLOW_VERIFIED" if d["base_eligible"] else "BASE_NOT_ELIGIBLE"
    preventive=d["shadow_action"]
    held=preventive in HELD_ACTIONS
    critical_prevented=bool(d["base_eligible"] and held and truth in BAD_TRUTHS)
    false_hold=bool(d["base_eligible"] and held and truth in GOOD_TRUTHS)

    if critical_prevented:
        cls="PREVENTED_CRITICAL_FAILURE"
    elif false_hold:
        cls="FALSE_CONSERVATIVE_HOLD"
    elif d["base_eligible"] and not held and truth in BAD_TRUTHS:
        cls="MISSED_CRITICAL_FAILURE"
    elif truth in GOOD_TRUTHS:
        cls="CORRECT_ALLOW"
    else:
        cls="NEUTRAL"

    key=outcome_key or f"DECISION_OUTCOME:{decision_id}"
    rationale=[
        f"Base={base_action}, Preventive={preventive}, Truth={truth}",
        "Ground Truth is human-confirmed before affecting Canary Safety Gate"
    ]
    oid,created=persist_preventive_policy_outcome(
        con,outcome_key=key,decision_id=decision_id,
        event_instance_id=d["event_instance_id"],source_id=d["source_id"],
        rule_key=d["rule_key"],policy_mode=d["production_mode"],
        base_action=base_action,preventive_action=preventive,event_truth=truth,
        outcome_class=cls,critical_prevented=critical_prevented,
        false_conservative_hold=false_hold,confirmed_by=confirmed_by,
        rationale=rationale)

    runtime_guard=None
    if d["production_mode"]=="FULL_PREVENTIVE":
        from .preventive_full_runtime_guard import persist_runtime_outcome
        runtime_guard=persist_runtime_outcome(
            con,outcome_id=oid,decision_id=decision_id,outcome_class=cls,
            false_conservative_hold=false_hold,
            critical_prevented=critical_prevented)

    return {"outcome_id":oid,"created":created,"decision_id":decision_id,
            "outcome_class":cls,"critical_prevented":critical_prevented,
            "false_conservative_hold":false_hold,"event_truth":truth,
            "runtime_guard":runtime_guard}

def outcomes(con,canary_id=None):
    return _decode(preventive_policy_outcome_rows(con,canary_id))

def evaluate_canary_safety(con,canary_id):
    c=con.execute("SELECT * FROM preventive_policy_canaries WHERE canary_id=?",
                  (canary_id,)).fetchone()
    if not c: raise KeyError("preventive canary not found")
    rows=list(preventive_policy_outcome_rows(con,canary_id))
    n=len(rows)
    prevented=sum(r["critical_prevented"] for r in rows)
    false_holds=sum(r["false_conservative_hold"] for r in rows)
    rate=(false_holds/n) if n else None
    reasons=[]
    if n<MIN_CANARY_OUTCOMES:
        status="OBSERVING"; reasons.append(f"need >= {MIN_CANARY_OUTCOMES} confirmed outcomes")
    elif rate>MAX_FALSE_CONSERVATIVE_HOLD_RATE:
        status="BLOCKED"; reasons.append(
            f"false conservative hold rate {rate:.3f} > {MAX_FALSE_CONSERVATIVE_HOLD_RATE:.2f}")
    elif prevented<1:
        status="OBSERVING"; reasons.append("no prevented critical failure observed yet")
    elif c["status"]!="EXHAUSTED":
        status="OBSERVING"; reasons.append("canary must be EXHAUSTED before final review")
    else:
        status="READY_FOR_FINAL_REVIEW"
        reasons.append("confirmed outcomes show critical prevention within conservative-hold limit")
    eid=persist_preventive_canary_safety_evaluation(
        con,canary_id=canary_id,sample_count=n,prevented_critical_count=prevented,
        false_conservative_hold_count=false_holds,false_conservative_hold_rate=rate,
        status=status,reasons=reasons)
    return {"evaluation_id":eid,"canary_id":canary_id,"sample_count":n,
            "prevented_critical_count":prevented,
            "false_conservative_hold_count":false_holds,
            "false_conservative_hold_rate":rate,"status":status,"reasons":reasons}

def safety_history(con,canary_id=None):
    return _decode(preventive_canary_safety_rows(con,canary_id))

def final_review(con, *, canary_id,decision,reviewer,reason=None):
    decision=decision.upper()
    if decision not in {"PROMOTE","ROLLBACK","HOLD"}:
        raise ValueError("decision must be PROMOTE, ROLLBACK, or HOLD")
    if not reviewer: raise ValueError("reviewer is required")
    c=con.execute("SELECT * FROM preventive_policy_canaries WHERE canary_id=?",
                  (canary_id,)).fetchone()
    if not c: raise KeyError("preventive canary not found")
    gate=evaluate_canary_safety(con,canary_id)
    promotion_id=None
    if decision=="PROMOTE":
        if gate["status"]!="READY_FOR_FINAL_REVIEW":
            raise ValueError("Canary Safety Gate is not READY_FOR_FINAL_REVIEW")
        promotion_id,_=create_preventive_full_promotion(
            con,source_id=c["source_id"],rule_key=c["rule_key"],canary_id=canary_id,
            promoted_by=reviewer,metadata={"policy_version":POLICY_VERSION,
                "safety_evaluation_id":gate["evaluation_id"]})
        con.execute("UPDATE preventive_policy_canaries SET status='PROMOTED' WHERE canary_id=?",
                    (canary_id,)); con.commit()
    elif decision=="ROLLBACK":
        rollback_preventive_policy_canary(con,canary_id,reviewer,reason or "final review rollback")
        active=con.execute("""SELECT promotion_id FROM preventive_full_promotions
          WHERE canary_id=? AND status='ACTIVE'""",(canary_id,)).fetchone()
        if active:
            rollback_preventive_full_promotion(
                con,active["promotion_id"],reviewer,reason or "final review rollback")
    rid=persist_preventive_final_review(
        con,canary_id=canary_id,decision=decision,reviewer=reviewer,
        reason=reason,promotion_id=promotion_id)
    return {"final_review_id":rid,"canary_id":canary_id,"decision":decision,
            "promotion_id":promotion_id,"safety_gate":gate}

def full_promotions(con):
    return _decode(preventive_full_promotion_rows(con))

def final_reviews(con,canary_id=None):
    return _decode(preventive_final_review_rows(con,canary_id))

def rollback_full(con, *, promotion_id,actor,reason):
    if not actor or not reason: raise ValueError("actor and reason required")
    rollback_preventive_full_promotion(con,promotion_id,actor,reason)
    return {"promotion_id":promotion_id,"status":"ROLLED_BACK",
            "actor":actor,"reason":reason}
