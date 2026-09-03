import json
from .database import (
    adaptive_shadow_rows_by_goal,persist_shadow_safety_evaluation,
    latest_shadow_safety_evaluation,shadow_safety_evaluation_rows
)

LABELS=("IMPROVED","REGRESSED","INCONCLUSIVE")
POLICY_VERSION="v0.31"
MIN_SAMPLES=20
MIN_AGREEMENT_RATE=0.90

def _empty_matrix():
    return {b:{s:0 for s in LABELS} for b in LABELS}

def _classify_rows(rows):
    matrix=_empty_matrix()
    total=0
    agreements=0
    critical_false_improved=0
    unsafe_improved=0
    conservative_false_regressed=0

    for r in rows:
        base=r["base_verdict"]
        shadow=r["shadow_verdict"]
        if base not in matrix or shadow not in matrix[base]:
            continue
        matrix[base][shadow]+=1
        total+=1
        if base==shadow:
            agreements+=1

        # Highest-risk failure: trusted Base says REGRESSED but adaptive Shadow says IMPROVED.
        if base=="REGRESSED" and shadow=="IMPROVED":
            critical_false_improved+=1

        # Any Shadow IMPROVED when Base is not IMPROVED is unsafe for trust-sensitive promotion.
        if shadow=="IMPROVED" and base!="IMPROVED":
            unsafe_improved+=1

        # Conservative miss: Base says IMPROVED but Shadow says REGRESSED.
        # This may reduce recall but does not create false optimism.
        if base=="IMPROVED" and shadow=="REGRESSED":
            conservative_false_regressed+=1

    disagreements=total-agreements
    agreement_rate=round(agreements/total,4) if total else None
    return {
        "confusion_matrix":matrix,
        "total":total,
        "agreements":agreements,
        "disagreements":disagreements,
        "agreement_rate":agreement_rate,
        "critical_false_improved":critical_false_improved,
        "unsafe_improved":unsafe_improved,
        "conservative_false_regressed":conservative_false_regressed
    }

def evaluate_shadow_safety(con, goal_profile=None, persist=True):
    rows=adaptive_shadow_rows_by_goal(con,goal_profile)
    stats=_classify_rows(rows)
    reasons=[]

    if stats["critical_false_improved"]>0:
        status="BLOCKED"
        reasons.append(
            f"Critical false IMPROVED detected: {stats['critical_false_improved']} "
            "(Base REGRESSED → Shadow IMPROVED)"
        )
    elif stats["unsafe_improved"]>0:
        status="BLOCKED"
        reasons.append(
            f"Unsafe Shadow IMPROVED detected: {stats['unsafe_improved']} "
            "(Base not IMPROVED → Shadow IMPROVED)"
        )
    elif stats["total"]<MIN_SAMPLES:
        status="OBSERVING"
        reasons.append(f"Shadow samples {stats['total']} < minimum {MIN_SAMPLES}")
    elif stats["agreement_rate"] is None or stats["agreement_rate"]<MIN_AGREEMENT_RATE:
        status="OBSERVING"
        reasons.append(
            f"Agreement rate {stats['agreement_rate']} < minimum {MIN_AGREEMENT_RATE}"
        )
    else:
        status="ELIGIBLE"
        reasons.append(
            "Minimum sample count, agreement rate, and zero unsafe IMPROVED requirements met"
        )

    # Eligibility is only a safety signal. Never auto-promote adaptive weights.
    result={
        "policy_version":POLICY_VERSION,
        "goal_profile":goal_profile,
        "status":status,
        **stats,
        "minimum_samples":MIN_SAMPLES,
        "minimum_agreement_rate":MIN_AGREEMENT_RATE,
        "automatic_promotion":False,
        "reasons":reasons
    }

    if persist:
        result["safety_id"]=persist_shadow_safety_evaluation(
            con,goal_profile=goal_profile,policy_version=POLICY_VERSION,status=status,
            total=stats["total"],agreements=stats["agreements"],
            disagreements=stats["disagreements"],agreement_rate=stats["agreement_rate"],
            critical_false_improved=stats["critical_false_improved"],
            unsafe_improved=stats["unsafe_improved"],
            conservative_false_regressed=stats["conservative_false_regressed"],
            confusion_matrix=stats["confusion_matrix"],reasons=reasons
        )
    return result

def shadow_safety_status(con, goal_profile=None):
    """Non-persisting current status for reports/daily summary."""
    return evaluate_shadow_safety(con,goal_profile=goal_profile,persist=False)

def shadow_safety_history(con, goal_profile=None):
    rows=shadow_safety_evaluation_rows(con,goal_profile)
    out=[]
    for r in rows:
        item=dict(r)
        item["confusion_matrix_json"]=json.loads(item["confusion_matrix_json"])
        item["reasons_json"]=json.loads(item["reasons_json"])
        out.append(item)
    return out

def latest_shadow_safety(con, goal_profile=None):
    row=latest_shadow_safety_evaluation(con,goal_profile)
    if not row:
        return None
    item=dict(row)
    item["confusion_matrix_json"]=json.loads(item["confusion_matrix_json"])
    item["reasons_json"]=json.loads(item["reasons_json"])
    return item
