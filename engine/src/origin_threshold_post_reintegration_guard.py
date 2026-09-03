import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
WINDOWS=(5,10,20)
COVERAGE_REGRESSION_THRESHOLD=-0.10

def _now():
    return datetime.now(timezone.utc).isoformat()

def _scope(con,scope_id):
    r=con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                     WHERE scope_id=?""",(scope_id,)).fetchone()
    if not r: raise ValueError("scope not found")
    return dict(r)

def _released_canary(con,scope_id):
    r=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_canaries
      WHERE scope_id=? AND status='FULL_REINTEGRATED'
      ORDER BY canary_id DESC LIMIT 1""",(scope_id,)).fetchone()
    return dict(r) if r else None

def observations(con,scope_id=None):
    if scope_id is None:
        rows=con.execute("""SELECT * FROM origin_threshold_post_reintegration_observations
                            ORDER BY post_observation_id""").fetchall()
    else:
        rows=con.execute("""SELECT * FROM origin_threshold_post_reintegration_observations
                            WHERE scope_id=? ORDER BY post_observation_id""",
                         (scope_id,)).fetchall()
    return [dict(r) for r in rows]

def evaluations(con,scope_id=None):
    sql="""SELECT * FROM origin_threshold_post_reintegration_evaluations"""
    params=()
    if scope_id is not None:
        sql+=" WHERE scope_id=?"; params=(scope_id,)
    sql+=" ORDER BY post_evaluation_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def re_isolations(con,scope_id=None):
    sql="""SELECT * FROM origin_threshold_scope_reisolations"""
    params=()
    if scope_id is not None:
        sql+=" WHERE scope_id=?"; params=(scope_id,)
    sql+=" ORDER BY reisolation_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def _counterfactual(human_outcome,reintegrated_correct,base_correct,alternative_correct):
    comparisons=[x for x in (base_correct,alternative_correct) if x is not None]
    if not comparisons:
        return "NO_COUNTERFACTUAL"
    if reintegrated_correct and any(not x for x in comparisons):
        return "REINTEGRATION_IMPROVEMENT"
    if not reintegrated_correct and any(x for x in comparisons):
        return "REINTEGRATION_REGRESSION"
    if reintegrated_correct and all(comparisons):
        return "SAME_CORRECT"
    return "SHARED_ERROR"

def record_observation(con,scope_id,event_instance_id,human_outcome,*,critical=False,
                       false_corroboration=False,missed_syndication=False,
                       coverage_quality_delta=None,reintegrated_correct=True,
                       base_correct=None,alternative_correct=None,observed_at=None):
    scope=_scope(con,scope_id)
    canary=_released_canary(con,scope_id)
    if not canary:
        raise ValueError("scope has no FULL_REINTEGRATED canary")
    if scope["status"]!="RELEASED":
        raise ValueError("scope is not in released post-reintegration runtime")
    if human_outcome not in ("SAFE","UNSAFE","HOLD"):
        raise ValueError("human_outcome must be SAFE, UNSAFE, or HOLD")
    cf=_counterfactual(
        human_outcome,bool(reintegrated_correct),
        None if base_correct is None else bool(base_correct),
        None if alternative_correct is None else bool(alternative_correct))
    cur=con.execute("""INSERT INTO origin_threshold_post_reintegration_observations(
      scope_id,canary_id,event_instance_id,human_outcome,critical,false_corroboration,
      missed_syndication,coverage_quality_delta,reintegrated_correct,
      base_correct,alternative_correct,counterfactual_class,observed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (scope_id,canary["canary_id"],event_instance_id,human_outcome,
       int(bool(critical)),int(bool(false_corroboration)),int(bool(missed_syndication)),
       coverage_quality_delta,int(bool(reintegrated_correct)),
       None if base_correct is None else int(bool(base_correct)),
       None if alternative_correct is None else int(bool(alternative_correct)),
       cf,observed_at or _now()))
    oid=cur.lastrowid
    con.commit()
    from .origin_threshold_architecture_memory import observe_runtime
    is_regression=(
        cf=="REINTEGRATION_REGRESSION"
        or not bool(reintegrated_correct)
        or bool(false_corroboration)
        or bool(missed_syndication)
        or (coverage_quality_delta is not None
            and float(coverage_quality_delta)<COVERAGE_REGRESSION_THRESHOLD))
    architecture_runtime=observe_runtime(
        con,scope_id,canary["canary_id"],is_regression=is_regression,
        observed_at=observed_at or _now())
    guard=evaluate_guard(con,scope_id,persist=True,trigger_observation_id=oid)
    return {
        "observation":dict(con.execute(
            """SELECT * FROM origin_threshold_post_reintegration_observations
               WHERE post_observation_id=?""",(oid,)).fetchone()),
        "architecture_runtime_outcome":architecture_runtime,
        "guard":guard
    }

def _window_metrics(rows,n):
    vals=rows[-n:]
    regressions=sum(
        r["counterfactual_class"]=="REINTEGRATION_REGRESSION"
        or not bool(r["reintegrated_correct"]) for r in vals)
    fc=sum(bool(r["false_corroboration"]) for r in vals)
    miss=sum(bool(r["missed_syndication"]) for r in vals)
    critical=sum(
        bool(r["critical"]) and (
            r["counterfactual_class"]=="REINTEGRATION_REGRESSION"
            or not bool(r["reintegrated_correct"])
            or bool(r["false_corroboration"])
            or bool(r["missed_syndication"])
        ) for r in vals)
    cov=sum(
        r["coverage_quality_delta"] is not None
        and float(r["coverage_quality_delta"]) < COVERAGE_REGRESSION_THRESHOLD
        for r in vals)
    return {
        "sample_count":len(vals),"regression_count":regressions,
        "false_corroboration_count":fc,"missed_syndication_count":miss,
        "critical_regression_count":critical,"coverage_regression_count":cov
    }

def _status_for_window(m,n):
    reasons=[]
    status="WARMING" if m["sample_count"]<n else "HEALTHY"
    if m["critical_regression_count"]>0:
        return "REISOLATE",[f"critical reintegration regression in rolling {n}"]
    # Any false corroboration or missed syndication is too dangerous post release.
    if m["false_corroboration_count"]>0:
        return "REISOLATE",[f"false corroboration in rolling {n}"]
    if m["missed_syndication_count"]>0:
        return "REISOLATE",[f"missed syndication in rolling {n}"]
    if n==5:
        if m["regression_count"]>=2 or m["coverage_regression_count"]>=2:
            return "REISOLATE",[f"rolling 5 regression threshold exceeded"]
        if m["sample_count"]>=5 and (m["regression_count"]==1 or m["coverage_regression_count"]==1):
            status="WATCH"; reasons.append("single rolling-5 post-release regression")
    elif n==10:
        if m["regression_count"]>=2 or m["coverage_regression_count"]>=2:
            return "REISOLATE",[f"rolling 10 regression threshold exceeded"]
        if m["sample_count"]>=10 and (m["regression_count"]==1 or m["coverage_regression_count"]==1):
            status="WATCH"; reasons.append("rolling-10 post-release regression watch")
    else:
        if m["regression_count"]>=3 or m["coverage_regression_count"]>=3:
            return "REISOLATE",[f"rolling 20 regression threshold exceeded"]
        if m["sample_count"]>=20 and (m["regression_count"]>=1 or m["coverage_regression_count"]>=1):
            status="WATCH"; reasons.append("rolling-20 post-release regression watch")
    if status=="HEALTHY":
        reasons.append(f"rolling {n} post-release runtime is healthy")
    elif status=="WARMING":
        reasons.append(f"rolling {n} warming: {m['sample_count']}/{n}")
    return status,reasons

def _penalty_level(con,scope_id):
    n=con.execute("""SELECT COUNT(*) n FROM origin_threshold_scope_reisolations
                     WHERE scope_id=?""",(scope_id,)).fetchone()["n"]
    return int(n)+1

def _re_isolate(con,scope_id,canary_id,reason,trigger_observation_id=None,
                trigger_evaluation_id=None):
    existing=con.execute("""SELECT * FROM origin_threshold_scope_reisolations
      WHERE scope_id=? AND status='ACTIVE' ORDER BY reisolation_id DESC LIMIT 1""",
      (scope_id,)).fetchone()
    if existing:
        return dict(existing)
    penalty=_penalty_level(con,scope_id)
    con.execute("""UPDATE origin_threshold_restriction_scopes
                   SET status='ACTIVE',released_at=NULL WHERE scope_id=?""",(scope_id,))
    scope=con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                         WHERE scope_id=?""",(scope_id,)).fetchone()
    restriction=con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                               WHERE restriction_id=?""",(scope["restriction_id"],)).fetchone()
    if restriction:
        profile=con.execute("""SELECT * FROM origin_threshold_recurrence_profiles
                               WHERE recurrence_profile_id=?""",
                            (restriction["recurrence_profile_id"],)).fetchone()
        if profile:
            try:
                reasons=json.loads(profile["reasons_json"] or "[]")
            except Exception:
                reasons=[]
            reasons.append("post-reintegration runtime regression triggered automatic scope re-isolation")
            con.execute("""UPDATE origin_threshold_recurrence_profiles
              SET recurrence_count=recurrence_count+1,
                  post_requalification_recurrence_count=post_requalification_recurrence_count+1,
                  risk_band='RESTRICTED',long_term_restricted=1,
                  reasons_json=?,updated_at=?
              WHERE recurrence_profile_id=?""",
              (json.dumps(reasons,ensure_ascii=False),_now(),
               profile["recurrence_profile_id"]))
    cur=con.execute("""INSERT INTO origin_threshold_scope_reisolations(
      scope_id,canary_id,trigger_post_observation_id,trigger_post_evaluation_id,
      status,reason,failure_count,requirement_penalty_level,reactivated_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (scope_id,canary_id,trigger_observation_id,trigger_evaluation_id,
       "ACTIVE",reason,1,penalty,_now()))
    rid=cur.lastrowid
    con.execute("""INSERT INTO origin_threshold_post_reintegration_events(
      scope_id,canary_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (scope_id,canary_id,"AUTO_SCOPE_REISOLATED","post-reintegration-runtime-guard",
       json.dumps({"reason":reason,"requirement_penalty_level":penalty},
                  ensure_ascii=False),_now()))
    con.commit()
    from .origin_threshold_post_reintegration_root_cause import attribute_root_cause
    attribution=attribute_root_cause(con,rid,persist=True)
    from .origin_threshold_architecture_memory import mark_reisolation_failure
    architecture_failure=mark_reisolation_failure(
        con,scope_id,canary_id,rid,reisolated_at=_now())
    result=dict(con.execute("""SELECT * FROM origin_threshold_scope_reisolations
                              WHERE reisolation_id=?""",(rid,)).fetchone())
    result["post_reintegration_root_cause"]=attribution
    result["architecture_plan_runtime_failure"]=architecture_failure
    return result

def evaluate_guard(con,scope_id,persist=True,trigger_observation_id=None):
    scope=_scope(con,scope_id)
    canary=_released_canary(con,scope_id)
    if not canary:
        return {"policy_version":POLICY_VERSION,"scope_id":scope_id,
                "overall_status":"NO_RELEASED_RUNTIME","windows":[]}
    rows=observations(con,scope_id)
    windows=[]
    overall="NO_DATA" if not rows else "WARMING"
    reiso_reason=None
    trigger_eval_id=None
    for n in WINDOWS:
        m=_window_metrics(rows,n)
        status,reasons=_status_for_window(m,n)
        item={"window_size":n,**m,"status":status,"reasons":reasons}
        if persist:
            cur=con.execute("""INSERT INTO origin_threshold_post_reintegration_evaluations(
              scope_id,canary_id,window_size,sample_count,regression_count,
              false_corroboration_count,missed_syndication_count,
              critical_regression_count,coverage_regression_count,status,
              reasons_json,evaluated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (scope_id,canary["canary_id"],n,m["sample_count"],m["regression_count"],
               m["false_corroboration_count"],m["missed_syndication_count"],
               m["critical_regression_count"],m["coverage_regression_count"],
               status,json.dumps(reasons,ensure_ascii=False),_now()))
            item["post_evaluation_id"]=cur.lastrowid
            if status=="REISOLATE" and trigger_eval_id is None:
                trigger_eval_id=cur.lastrowid
        windows.append(item)
        if status=="REISOLATE":
            overall="REISOLATE"
            if reiso_reason is None:
                reiso_reason="; ".join(reasons)
        elif overall!="REISOLATE":
            if status=="WATCH":
                overall="WATCH"
            elif status=="HEALTHY" and overall not in ("WATCH",):
                overall="HEALTHY"
            elif status=="WARMING" and overall not in ("WATCH","HEALTHY"):
                overall="WARMING"
    if overall not in ("REISOLATE","WATCH"):
        if any(w["status"]=="WARMING" for w in windows):
            overall="WARMING"
        elif windows and all(w["status"]=="HEALTHY" for w in windows):
            overall="HEALTHY"
    if persist:
        con.commit()
    reisolation=None
    if overall=="REISOLATE":
        reisolation=_re_isolate(
            con,scope_id,canary["canary_id"],reiso_reason or "post-release regression",
            trigger_observation_id=trigger_observation_id,
            trigger_evaluation_id=trigger_eval_id)
    return {
        "policy_version":POLICY_VERSION,"scope_id":scope_id,
        "canary_id":canary["canary_id"],"overall_status":overall,
        "windows":windows,"reisolation":reisolation
    }

def clear_reisolation(con,reisolation_id,cleared_by,reason):
    if not cleared_by or not reason:
        raise ValueError("cleared_by and reason required")
    r=con.execute("""SELECT * FROM origin_threshold_scope_reisolations
                     WHERE reisolation_id=?""",(reisolation_id,)).fetchone()
    if not r: raise ValueError("re-isolation not found")
    if r["status"]!="ACTIVE":
        raise ValueError("re-isolation is not active")
    con.execute("""UPDATE origin_threshold_scope_reisolations
      SET status='CLEARED',cleared_at=?,cleared_by=?,clear_reason=?
      WHERE reisolation_id=?""",(_now(),cleared_by,reason,reisolation_id))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_scope_reisolations
                              WHERE reisolation_id=?""",(reisolation_id,)).fetchone())

def requirement_penalty(con,scope_id):
    row=con.execute("""SELECT MAX(requirement_penalty_level) level
      FROM origin_threshold_scope_reisolations WHERE scope_id=?""",
      (scope_id,)).fetchone()
    level=int(row["level"] or 0)
    return {
        "level":level,
        "shadow_bonus":min(level*2,6),
        "human_bonus":min(level,3),
        "event_bonus":min(level,3)
    }

def status(con):
    scope_ids=[r["scope_id"] for r in con.execute(
        """SELECT DISTINCT scope_id FROM origin_threshold_scope_reintegration_canaries
           WHERE status='FULL_REINTEGRATED' ORDER BY scope_id""").fetchall()]
    return {
        "policy_version":POLICY_VERSION,
        "scopes":[evaluate_guard(con,sid,persist=False) for sid in scope_ids],
        "re_isolations":re_isolations(con)
    }
