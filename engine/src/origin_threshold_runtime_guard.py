import json
from datetime import datetime, timezone

POLICY_VERSION="v0.62"
BASE_THRESHOLD=0.86
WINDOWS=(5,10,20)
REQUIRED_RECOVERY_SHADOW_OUTCOMES=5

def _now():
    return datetime.now(timezone.utc).isoformat()

def _active_promotion(con):
    r=con.execute("""SELECT * FROM origin_threshold_promotions
                     WHERE status='ACTIVE' ORDER BY promotion_id DESC LIMIT 1""").fetchone()
    return dict(r) if r else None

def _prediction(sim,threshold):
    return float(sim)>=float(threshold)

def _correct(predicted_syndication,human_outcome):
    actual=human_outcome=="CONFIRM_SYNDICATION"
    if human_outcome not in ("CONFIRM_SYNDICATION","CONFIRM_INDEPENDENT"):
        return None
    return bool(predicted_syndication)==actual

def _counterfactual_class(base_correct,promoted_correct):
    if base_correct is None or promoted_correct is None:
        return "UNRESOLVED"
    if promoted_correct and not base_correct:
        return "PROMOTION_IMPROVEMENT"
    if not promoted_correct and base_correct:
        return "PROMOTION_REGRESSION"
    if promoted_correct and base_correct:
        return "SAME_CORRECT"
    return "SHARED_ERROR"

def _runtime_rows(con,promotion_id,limit=None):
    sql="""SELECT * FROM origin_threshold_runtime_observations
           WHERE promotion_id=? ORDER BY runtime_observation_id DESC"""
    if limit is not None:
        sql+=" LIMIT ?"
        rows=con.execute(sql,(promotion_id,int(limit))).fetchall()
    else:
        rows=con.execute(sql,(promotion_id,)).fetchall()
    return [dict(r) for r in reversed(rows)]

def _rates(rows):
    tp=fp=fn=tn=base_fp=base_fn=reg=imp=crit_reg=0
    for r in rows:
        actual=r["human_outcome"]=="CONFIRM_SYNDICATION"
        pp=bool(r["promoted_predicted_syndication"])
        bp=bool(r["base_predicted_syndication"])
        if pp and actual: tp+=1
        elif pp and not actual: fp+=1
        elif not pp and actual: fn+=1
        else: tn+=1
        if bp and not actual: base_fp+=1
        if (not bp) and actual: base_fn+=1
        if r["counterfactual_class"]=="PROMOTION_REGRESSION":
            reg+=1
            if r["critical"]: crit_reg+=1
        elif r["counterfactual_class"]=="PROMOTION_IMPROVEMENT":
            imp+=1
    precision=tp/(tp+fp) if tp+fp else None
    fpr=fp/(fp+tn) if fp+tn else 0.0
    miss_rate=fn/(tp+fn) if tp+fn else 0.0
    return {
        "tp":tp,"fp":fp,"fn":fn,"tn":tn,
        "precision":precision,"false_positive_rate":fpr,"miss_rate":miss_rate,
        "base_false_positive_count":base_fp,
        "base_missed_syndication_count":base_fn,
        "promotion_regression_count":reg,
        "promotion_improvement_count":imp,
        "critical_regression_count":crit_reg
    }

def _window_status(window_size,observed,m):
    reasons=[]
    if observed==0:
        return "NO_DATA",["no post-promotion Human outcomes yet"]

    # Fail-closed immediate critical regression.
    if m["critical_regression_count"]>0:
        reasons.append("critical Event has promotion-specific regression")
        return "ROLLBACK",reasons

    # Small-window guard catches acute drift quickly.
    if window_size==5 and observed>=5:
        if m["promotion_regression_count"]>=2:
            reasons.append(">=2 promotion regressions in rolling 5 Human outcomes")
            return "ROLLBACK",reasons
        if m["miss_rate"]>=0.20:
            reasons.append(f"rolling-5 missed-syndication rate {m['miss_rate']:.3f} >= 0.20")
            return "ROLLBACK",reasons
        if m["false_positive_rate"]>=0.40:
            reasons.append(f"rolling-5 false-positive rate {m['false_positive_rate']:.3f} >= 0.40")
            return "ROLLBACK",reasons
        if m["promotion_regression_count"]==1 or m["false_positive_rate"]>=0.20:
            reasons.append("rolling-5 warning signal requires closer Human Review")
            return "WATCH",reasons

    if window_size==10 and observed>=10:
        if m["miss_rate"]>=0.10:
            reasons.append(f"rolling-10 missed-syndication rate {m['miss_rate']:.3f} >= 0.10")
            return "ROLLBACK",reasons
        if m["false_positive_rate"]>=0.25:
            reasons.append(f"rolling-10 false-positive rate {m['false_positive_rate']:.3f} >= 0.25")
            return "ROLLBACK",reasons
        if m["promotion_regression_count"]>=2:
            reasons.append(">=2 promotion regressions in rolling 10 Human outcomes")
            return "ROLLBACK",reasons

    if window_size==20 and observed>=20:
        if m["miss_rate"]>=0.10:
            reasons.append(f"rolling-20 missed-syndication rate {m['miss_rate']:.3f} >= 0.10")
            return "ROLLBACK",reasons
        if m["false_positive_rate"]>=0.20:
            reasons.append(f"rolling-20 false-positive rate {m['false_positive_rate']:.3f} >= 0.20")
            return "ROLLBACK",reasons
        if m["promotion_regression_count"]>=3:
            reasons.append(">=3 promotion regressions in rolling 20 Human outcomes")
            return "ROLLBACK",reasons

    if observed<window_size:
        reasons.append(f"collecting rolling-{window_size} Human outcomes ({observed}/{window_size})")
        return "WARMING",reasons

    reasons.append("post-promotion outcome window remains within safety limits")
    return "HEALTHY",reasons

def evaluate_runtime_guard(con,promotion_id,persist=True):
    evaluations=[]
    for w in WINDOWS:
        rows=_runtime_rows(con,promotion_id,w)
        m=_rates(rows)
        status,reasons=_window_status(w,len(rows),m)
        x={
            "policy_version":POLICY_VERSION,
            "promotion_id":promotion_id,"window_size":w,
            "observed_count":len(rows),
            "promoted_true_positive":m["tp"],
            "promoted_false_positive":m["fp"],
            "promoted_missed_syndication":m["fn"],
            "promoted_true_negative":m["tn"],
            "promoted_precision":m["precision"],
            "promoted_false_positive_rate":m["false_positive_rate"],
            "promoted_miss_rate":m["miss_rate"],
            "base_false_positive_count":m["base_false_positive_count"],
            "base_missed_syndication_count":m["base_missed_syndication_count"],
            "promotion_regression_count":m["promotion_regression_count"],
            "promotion_improvement_count":m["promotion_improvement_count"],
            "critical_regression_count":m["critical_regression_count"],
            "status":status,"reasons":reasons
        }
        if persist:
            con.execute("""INSERT INTO origin_threshold_runtime_evaluations(
              promotion_id,window_size,observed_count,promoted_true_positive,
              promoted_false_positive,promoted_missed_syndication,promoted_true_negative,
              promoted_precision,promoted_false_positive_rate,promoted_miss_rate,
              base_false_positive_count,base_missed_syndication_count,
              promotion_regression_count,promotion_improvement_count,
              critical_regression_count,status,reasons_json,evaluated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (promotion_id,w,len(rows),m["tp"],m["fp"],m["fn"],m["tn"],
               m["precision"],m["false_positive_rate"],m["miss_rate"],
               m["base_false_positive_count"],m["base_missed_syndication_count"],
               m["promotion_regression_count"],m["promotion_improvement_count"],
               m["critical_regression_count"],status,
               json.dumps(reasons,ensure_ascii=False),_now()))
        evaluations.append(x)
    if persist: con.commit()
    overall="ROLLBACK" if any(x["status"]=="ROLLBACK" for x in evaluations) else (
        "WATCH" if any(x["status"]=="WATCH" for x in evaluations) else (
        "HEALTHY" if all(x["status"] in ("HEALTHY","NO_DATA") for x in evaluations) else "WARMING"))
    return {"policy_version":POLICY_VERSION,"promotion_id":promotion_id,
            "overall_status":overall,"windows":evaluations}

def _open_recovery(con,promotion,reason):
    existing=con.execute("""SELECT * FROM origin_threshold_recovery_cases
                            WHERE promotion_id=?""",(promotion["promotion_id"],)).fetchone()
    if existing: return dict(existing)
    fallback=BASE_THRESHOLD
    cur=con.execute("""INSERT INTO origin_threshold_recovery_cases(
      promotion_id,candidate_id,failed_threshold,fallback_threshold,status,
      rollback_reason,required_shadow_outcomes,safe_shadow_outcome_count,opened_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (promotion["promotion_id"],promotion["candidate_id"],
       float(promotion["production_threshold"]),fallback,"OPEN",reason,
       REQUIRED_RECOVERY_SHADOW_OUTCOMES,0,_now()))
    rid=cur.lastrowid
    con.execute("""INSERT INTO origin_threshold_runtime_events(
      promotion_id,recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (promotion["promotion_id"],rid,"RECOVERY_OPENED","runtime-guard",
       json.dumps({"reason":reason,"fallback_threshold":fallback},ensure_ascii=False),_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_recovery_cases
                              WHERE recovery_case_id=?""",(rid,)).fetchone())

def auto_rollback(con,promotion_id,reason):
    p=con.execute("""SELECT * FROM origin_threshold_promotions
                     WHERE promotion_id=?""",(promotion_id,)).fetchone()
    if not p: raise ValueError("promotion not found")
    p=dict(p)
    if p["status"]!="ACTIVE":
        return {"rolled_back":False,"promotion":p,"recovery":None}
    con.execute("""UPDATE origin_threshold_promotions
                   SET status='ROLLED_BACK',rolled_back_at=?,rollback_reason=?
                   WHERE promotion_id=?""",(_now(),reason,promotion_id))
    con.execute("""UPDATE origin_threshold_candidates
                   SET status='RUNTIME_ROLLED_BACK',updated_at=?
                   WHERE candidate_id=?""",(_now(),p["candidate_id"]))
    con.execute("""INSERT INTO origin_threshold_runtime_events(
      promotion_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (promotion_id,"AUTO_FAIL_CLOSED_ROLLBACK","runtime-guard",
       json.dumps({"reason":reason},ensure_ascii=False),_now()))
    con.commit()
    recovery=_open_recovery(con,p,reason)
    # v0.52 immediately attributes an auditable root cause and upgrades the
    # fixed recovery gate to a risk-adaptive requirement.
    from .origin_threshold_recovery_root_cause import (
        attribute_root_cause,build_adaptive_requirement
    )
    attribute_root_cause(con,recovery["recovery_case_id"],persist=True)
    build_adaptive_requirement(con,recovery["recovery_case_id"],persist=True)
    recovery=dict(con.execute(
        "SELECT * FROM origin_threshold_recovery_cases WHERE recovery_case_id=?",
        (recovery["recovery_case_id"],)).fetchone())
    return {"rolled_back":True,
            "promotion":dict(con.execute("""SELECT * FROM origin_threshold_promotions
                                           WHERE promotion_id=?""",(promotion_id,)).fetchone()),
            "recovery":recovery}

def observe_runtime_outcome(con,*,event_instance_id,human_outcome,
                            max_text_similarity,cluster_id=None,
                            critical=False,event_status=None):
    if human_outcome not in ("CONFIRM_SYNDICATION","CONFIRM_INDEPENDENT"):
        raise ValueError("runtime guard requires decisive Human outcome")
    p=_active_promotion(con)
    if not p:
        return {"recorded":False,"reason":"no active Full threshold promotion"}
    promoted=float(p["production_threshold"])
    base=BASE_THRESHOLD
    bp=_prediction(max_text_similarity,base)
    pp=_prediction(max_text_similarity,promoted)
    bc=_correct(bp,human_outcome)
    pc=_correct(pp,human_outcome)
    cf=_counterfactual_class(bc,pc)
    cur=con.execute("""INSERT INTO origin_threshold_runtime_observations(
      promotion_id,event_instance_id,cluster_id,human_outcome,max_text_similarity,
      event_status,critical,base_threshold,promoted_threshold,
      base_predicted_syndication,promoted_predicted_syndication,
      base_correct,promoted_correct,counterfactual_class,observed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (p["promotion_id"],event_instance_id,cluster_id,human_outcome,
       float(max_text_similarity),event_status,int(bool(critical)),base,promoted,
       int(bp),int(pp),int(bool(bc)),int(bool(pc)),cf,_now()))
    oid=cur.lastrowid
    con.commit()

    guard=evaluate_runtime_guard(con,p["promotion_id"],persist=True)
    rollback=None
    if guard["overall_status"]=="ROLLBACK":
        reasons=[]
        for w in guard["windows"]:
            if w["status"]=="ROLLBACK": reasons+=w["reasons"]
        rollback=auto_rollback(con,p["promotion_id"],"; ".join(dict.fromkeys(reasons)))
    return {
        "recorded":True,"runtime_observation_id":oid,
        "promotion_id":p["promotion_id"],
        "counterfactual_class":cf,
        "base_correct":bool(bc),"promoted_correct":bool(pc),
        "guard":guard,"rollback":rollback
    }

def runtime_history(con,promotion_id=None):
    if promotion_id is None:
        rows=con.execute("""SELECT * FROM origin_threshold_runtime_observations
                            ORDER BY runtime_observation_id""").fetchall()
    else:
        rows=con.execute("""SELECT * FROM origin_threshold_runtime_observations
                            WHERE promotion_id=? ORDER BY runtime_observation_id""",
                         (promotion_id,)).fetchall()
    return [dict(r) for r in rows]

def evaluation_history(con,promotion_id=None):
    if promotion_id is None:
        rows=con.execute("""SELECT * FROM origin_threshold_runtime_evaluations
                            ORDER BY runtime_evaluation_id""").fetchall()
    else:
        rows=con.execute("""SELECT * FROM origin_threshold_runtime_evaluations
                            WHERE promotion_id=? ORDER BY runtime_evaluation_id""",
                         (promotion_id,)).fetchall()
    out=[]
    for r in rows:
        x=dict(r)
        x["reasons"]=json.loads(x.pop("reasons_json"))
        out.append(x)
    return out

def recovery_cases(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recovery_cases ORDER BY recovery_case_id""").fetchall()]

def add_recovery_shadow_outcome(con,recovery_case_id,event_instance_id,outcome,notes=None):
    if outcome not in ("SAFE","UNSAFE","HOLD"):
        raise ValueError("recovery outcome must be SAFE, UNSAFE, or HOLD")
    r=con.execute("""SELECT * FROM origin_threshold_recovery_cases
                     WHERE recovery_case_id=?""",(recovery_case_id,)).fetchone()
    if not r: raise ValueError("recovery case not found")
    if r["status"]=="REQUALIFIED":
        raise ValueError("recovery case already requalified")
    safe=int(outcome=="SAFE")
    con.execute("""INSERT INTO origin_threshold_recovery_outcomes(
      recovery_case_id,event_instance_id,outcome,safe,notes,observed_at)
      VALUES(?,?,?,?,?,?)""",
      (recovery_case_id,event_instance_id,outcome,safe,notes,_now()))
    if safe:
        con.execute("""UPDATE origin_threshold_recovery_cases
                       SET safe_shadow_outcome_count=safe_shadow_outcome_count+1
                       WHERE recovery_case_id=?""",(recovery_case_id,))
    # Any UNSAFE resets readiness and requires another full safe sequence.
    if outcome=="UNSAFE":
        con.execute("""UPDATE origin_threshold_recovery_cases
                       SET safe_shadow_outcome_count=0,status='OPEN',ready_at=NULL
                       WHERE recovery_case_id=?""",(recovery_case_id,))
    row=con.execute("""SELECT * FROM origin_threshold_recovery_cases
                       WHERE recovery_case_id=?""",(recovery_case_id,)).fetchone()
    if (row["safe_shadow_outcome_count"]>=row["required_shadow_outcomes"]
        and row["status"]!="READY_FOR_REQUALIFICATION"):
        con.execute("""UPDATE origin_threshold_recovery_cases
                       SET status='READY_FOR_REQUALIFICATION',ready_at=?
                       WHERE recovery_case_id=?""",(_now(),recovery_case_id))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_recovery_cases
                              WHERE recovery_case_id=?""",(recovery_case_id,)).fetchone())

def requalify_recovery(con,recovery_case_id,reviewer,reason):
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    # v0.52 adaptive gate supersedes the legacy count-only READY state.
    req=con.execute("""SELECT requirement_id FROM origin_threshold_adaptive_requirements
                       WHERE recovery_case_id=? ORDER BY requirement_id DESC LIMIT 1""",
                    (recovery_case_id,)).fetchone()
    if req:
        from .origin_threshold_recovery_root_cause import adaptive_requalification_status
        adaptive=adaptive_requalification_status(con,recovery_case_id)
        if adaptive["status"]!="READY_FOR_ADAPTIVE_REQUALIFICATION":
            raise ValueError("adaptive root-cause/recovery requirements are not satisfied")
    r=con.execute("""SELECT * FROM origin_threshold_recovery_cases
                     WHERE recovery_case_id=?""",(recovery_case_id,)).fetchone()
    if not r: raise ValueError("recovery case not found")
    if r["status"]!="READY_FOR_REQUALIFICATION":
        raise ValueError("recovery case is not ready for Human requalification")
    con.execute("""UPDATE origin_threshold_recovery_cases
                   SET status='REQUALIFIED',requalified_by=?,requalified_at=?,
                       requalification_reason=?
                   WHERE recovery_case_id=?""",
                (reviewer,_now(),reason,recovery_case_id))
    con.execute("""INSERT INTO origin_threshold_runtime_events(
      promotion_id,recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (r["promotion_id"],recovery_case_id,"HUMAN_REQUALIFIED",reviewer,
       json.dumps({"reason":reason},ensure_ascii=False),_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_recovery_cases
                              WHERE recovery_case_id=?""",(recovery_case_id,)).fetchone())

def runtime_guard_status(con):
    p=_active_promotion(con)
    recovery=recovery_cases(con)
    return {
        "policy_version":POLICY_VERSION,
        "active_promotion":p,
        "active_guard":evaluate_runtime_guard(con,p["promotion_id"],persist=False) if p else None,
        "recovery_cases":recovery
    }
