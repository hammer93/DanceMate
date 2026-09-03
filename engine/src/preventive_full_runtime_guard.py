import json

from .database import (
    persist_preventive_full_runtime_observation,
    preventive_full_runtime_observation_rows,
    persist_preventive_full_runtime_guard_evaluation,
    preventive_full_runtime_guard_evaluation_rows,
    persist_preventive_full_runtime_guard_event,
    preventive_full_runtime_guard_event_rows,
    rollback_preventive_full_promotion
)

POLICY_VERSION="v0.48"
RECENT5_FALSE_HOLD_BLOCK=0.40
RECENT10_FALSE_HOLD_BLOCK=0.30
STABLE_SAMPLE_COUNT=10
STABLE_FALSE_HOLD_RATE=0.20

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        for f in ("reasons_json","detail_json"):
            if f in x and x.get(f):
                try: x[f]=json.loads(x[f])
                except Exception: pass
        out.append(x)
    return out

def _rate(rows,field):
    if not rows: return None
    return sum(int(r[field]) for r in rows)/len(rows)

def promotion_for_full_decision(con,decision_row):
    if decision_row["production_mode"]!="FULL_PREVENTIVE":
        return None
    return con.execute("""SELECT * FROM preventive_full_promotions
      WHERE source_id=? AND rule_key=? AND canary_id=?
      ORDER BY promotion_id DESC LIMIT 1""",
      (decision_row["source_id"],decision_row["rule_key"],decision_row["canary_id"])).fetchone()

def persist_runtime_outcome(con, *, outcome_id,decision_id,outcome_class,
                            false_conservative_hold,critical_prevented):
    d=con.execute("SELECT * FROM preventive_verification_decisions WHERE decision_id=?",
                  (decision_id,)).fetchone()
    if not d or d["production_mode"]!="FULL_PREVENTIVE":
        return {"tracked":False,"reason":"decision is not FULL_PREVENTIVE"}
    promotion=promotion_for_full_decision(con,d)
    if not promotion:
        return {"tracked":False,"reason":"matching Full Preventive promotion not found"}

    missed=outcome_class=="MISSED_CRITICAL_FAILURE"
    oid,created=persist_preventive_full_runtime_observation(
        con,promotion_id=promotion["promotion_id"],outcome_id=outcome_id,
        decision_id=decision_id,outcome_class=outcome_class,
        missed_critical_failure=missed,
        false_conservative_hold=false_conservative_hold,
        critical_prevented=critical_prevented)
    if created:
        persist_preventive_full_runtime_guard_event(
            con,promotion_id=promotion["promotion_id"],event_type="RUNTIME_OUTCOME",
            actor="runtime-guard",outcome_id=outcome_id,
            detail={"runtime_observation_id":oid,"outcome_class":outcome_class})
    guard=evaluate_runtime_guard(con,promotion["promotion_id"],trigger_outcome_id=outcome_id)
    return {"tracked":True,"created":created,
            "runtime_observation_id":oid,"promotion_id":promotion["promotion_id"],
            "guard":guard}

def evaluate_runtime_guard(con,promotion_id, *, trigger_outcome_id=None):
    promotion=con.execute("""SELECT * FROM preventive_full_promotions
                             WHERE promotion_id=?""",(promotion_id,)).fetchone()
    if not promotion:
        raise KeyError("Full Preventive promotion not found")
    rows=list(preventive_full_runtime_observation_rows(con,promotion_id))
    n=len(rows)
    recent5=rows[-5:]
    recent10=rows[-10:]
    r5=_rate(recent5,"false_conservative_hold")
    r10=_rate(recent10,"false_conservative_hold")
    missed=sum(int(r["missed_critical_failure"]) for r in rows)
    prevented=sum(int(r["critical_prevented"]) for r in rows)
    reasons=[]

    if missed>0:
        status="BLOCKED"
        action="FAIL_CLOSED_ROLLBACK"
        reasons.append(f"{missed} MISSED_CRITICAL_FAILURE observed after Full Preventive promotion")
    elif len(recent5)>=5 and r5>RECENT5_FALSE_HOLD_BLOCK:
        status="BLOCKED"
        action="FAIL_CLOSED_ROLLBACK"
        reasons.append(
            f"recent5 false conservative hold rate {r5:.3f} > {RECENT5_FALSE_HOLD_BLOCK:.2f}")
    elif len(recent10)>=10 and r10>RECENT10_FALSE_HOLD_BLOCK:
        status="BLOCKED"
        action="FAIL_CLOSED_ROLLBACK"
        reasons.append(
            f"recent10 false conservative hold rate {r10:.3f} > {RECENT10_FALSE_HOLD_BLOCK:.2f}")
    elif n>=STABLE_SAMPLE_COUNT and r10 is not None and r10<=STABLE_FALSE_HOLD_RATE:
        status="STABLE_FULL"
        action="CONTINUE_MONITORING"
        reasons.append(
            f"{n} runtime outcomes, recent10 false hold rate {r10:.3f} <= {STABLE_FALSE_HOLD_RATE:.2f}")
    else:
        status="OBSERVING"
        action="CONTINUE_MONITORING"
        reasons.append(f"runtime samples={n}; continue monitoring")

    eid=persist_preventive_full_runtime_guard_evaluation(
        con,promotion_id=promotion_id,sample_count=n,
        recent5_sample_count=len(recent5),recent5_false_hold_rate=r5,
        recent10_sample_count=len(recent10),recent10_false_hold_rate=r10,
        missed_critical_count=missed,prevented_critical_count=prevented,
        status=status,action=action,reasons=reasons)

    rolled_back=False
    if status=="BLOCKED" and promotion["status"]=="ACTIVE":
        reason="; ".join(reasons)
        rollback_preventive_full_promotion(
            con,promotion_id,"preventive-full-runtime-guard",reason)
        persist_preventive_full_runtime_guard_event(
            con,promotion_id=promotion_id,event_type="AUTO_FAIL_CLOSED_ROLLBACK",
            actor="preventive-full-runtime-guard",outcome_id=trigger_outcome_id,
            detail={"guard_evaluation_id":eid,"reason":reason})
        from .preventive_recovery import open_recovery_case
        recovery=open_recovery_case(
            con,promotion_id=promotion_id,rollback_reason=reason)
        persist_preventive_full_runtime_guard_event(
            con,promotion_id=promotion_id,event_type="RECOVERY_CASE_OPENED",
            actor="preventive-full-runtime-guard",outcome_id=trigger_outcome_id,
            detail=recovery)
        rolled_back=True

    return {
        "guard_evaluation_id":eid,"promotion_id":promotion_id,
        "sample_count":n,"recent5_sample_count":len(recent5),
        "recent5_false_hold_rate":r5,"recent10_sample_count":len(recent10),
        "recent10_false_hold_rate":r10,"missed_critical_count":missed,
        "prevented_critical_count":prevented,"status":status,"action":action,
        "rolled_back":rolled_back,"reasons":reasons
    }

def guard_history(con,promotion_id=None):
    return _decode(preventive_full_runtime_guard_evaluation_rows(con,promotion_id))

def runtime_observations(con,promotion_id=None):
    return _decode(preventive_full_runtime_observation_rows(con,promotion_id))

def guard_events(con,promotion_id=None):
    return _decode(preventive_full_runtime_guard_event_rows(con,promotion_id))


def evaluate_active_runtime_guards(con):
    rows=con.execute("""SELECT promotion_id FROM preventive_full_promotions
                        WHERE status='ACTIVE' ORDER BY promotion_id""").fetchall()
    results=[]
    for r in rows:
        results.append(evaluate_runtime_guard(con,r["promotion_id"]))
    return {"policy_version":POLICY_VERSION,"active_promotion_count":len(rows),
            "evaluations":results}
