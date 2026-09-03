import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
SUSTAINED_OBSERVATION_MIN=20
SUSTAINED_DAYS_MIN=30.0
ESTABLISHED_ATTEMPTS=3

def _now():
    return datetime.now(timezone.utc).isoformat()

def _parse(v):
    return datetime.fromisoformat(v) if v else None

def _plan(con,plan_id):
    r=con.execute("""SELECT * FROM origin_threshold_architecture_remediation_plans
                     WHERE architecture_plan_id=?""",(plan_id,)).fetchone()
    if not r: raise ValueError("architecture plan not found")
    return dict(r)

def _root_type_for_plan(con,plan_id):
    r=con.execute("""SELECT rc.root_cause_type
      FROM origin_threshold_architecture_remediation_plans p
      JOIN origin_threshold_post_reintegration_remediation_routes rr
        ON rr.remediation_route_id=p.remediation_route_id
      JOIN origin_threshold_post_reintegration_root_causes rc
        ON rc.post_root_cause_id=rr.post_root_cause_id
      WHERE p.architecture_plan_id=?""",(plan_id,)).fetchone()
    return r["root_cause_type"] if r else "UNRESOLVED"

def plan_signature(con,plan_id):
    rows=con.execute("""SELECT remediation_type
      FROM origin_threshold_architecture_remediation_steps
      WHERE architecture_plan_id=? AND required=1
      ORDER BY remediation_type""",(plan_id,)).fetchall()
    vals=sorted({r["remediation_type"] for r in rows})
    return "+".join(vals)

def _latest_approved_plan_for_scope(con,scope_id):
    r=con.execute("""SELECT architecture_plan_id
      FROM origin_threshold_architecture_remediation_plans
      WHERE scope_id=? AND status='APPROVED_FOR_REINTEGRATION'
      ORDER BY architecture_plan_id DESC LIMIT 1""",(scope_id,)).fetchone()
    return _plan(con,r["architecture_plan_id"]) if r else None

def runtime_outcomes(con,scope_id=None):
    sql="""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes"""
    params=()
    if scope_id is not None:
        sql+=" WHERE scope_id=?"; params=(scope_id,)
    sql+=" ORDER BY architecture_runtime_outcome_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def effectiveness_profiles(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_architecture_plan_effectiveness_profiles"""
    params=()
    if root_cause_type is not None:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY effectiveness_score DESC,attempt_count DESC,architecture_effectiveness_profile_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def recommendations(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_architecture_plan_recommendations"""
    params=()
    if root_cause_type is not None:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY architecture_recommendation_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r)
        x["blocked_types"]=json.loads(x.pop("blocked_types_json"))
        x["recommended_steps"]=json.loads(x.pop("recommended_steps_json"))
        x["reasons"]=json.loads(x.pop("reasons_json"))
        out.append(x)
    return out

def _refresh_profile(con,root_type,signature):
    rows=con.execute("""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes
      WHERE root_cause_type=? AND plan_signature=?""",(root_type,signature)).fetchall()
    attempts=len(rows)
    success=sum(r["status"]=="SUSTAINED_SUCCESS" for r in rows)
    failed=sum(r["status"]=="RECURRENCE_FAILED" for r in rows)
    active=sum(r["status"]=="ACTIVE" for r in rows)
    decisive=success+failed
    rate=(success/decisive) if decisive else None
    failure_days=[float(r["days_to_reisolation"]) for r in rows
                  if r["status"]=="RECURRENCE_FAILED" and r["days_to_reisolation"] is not None]
    avg_fail=(sum(failure_days)/len(failure_days)) if failure_days else None
    if attempts<ESTABLISHED_ATTEMPTS or decisive<2:
        confidence="LOW_DATA"
    elif attempts<5:
        confidence="EMERGING"
    else:
        confidence="ESTABLISHED"
    # conservative score: active runs do not count as successes.
    score=None
    if decisive:
        score=rate
        if avg_fail is not None:
            score=max(0.0,min(1.0,score*0.8 + min(avg_fail/90.0,1.0)*0.2))
    reasons=[
        f"attempts={attempts}",f"sustained_success={success}",
        f"recurrence_failure={failed}",f"active_runs={active}",
        f"confidence={confidence}"
    ]
    existing=con.execute("""SELECT architecture_effectiveness_profile_id
      FROM origin_threshold_architecture_plan_effectiveness_profiles
      WHERE root_cause_type=? AND plan_signature=?""",(root_type,signature)).fetchone()
    vals=(attempts,success,failed,active,rate,avg_fail,confidence,score,
          json.dumps(reasons,ensure_ascii=False),_now())
    if existing:
        con.execute("""UPDATE origin_threshold_architecture_plan_effectiveness_profiles
          SET attempt_count=?,sustained_success_count=?,recurrence_failure_count=?,
              active_run_count=?,success_rate=?,avg_days_to_reisolation=?,
              confidence_band=?,effectiveness_score=?,reasons_json=?,updated_at=?
          WHERE architecture_effectiveness_profile_id=?""",vals+(existing["architecture_effectiveness_profile_id"],))
    else:
        con.execute("""INSERT INTO origin_threshold_architecture_plan_effectiveness_profiles(
          root_cause_type,plan_signature,attempt_count,sustained_success_count,
          recurrence_failure_count,active_run_count,success_rate,avg_days_to_reisolation,
          confidence_band,effectiveness_score,reasons_json,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (root_type,signature)+vals)
    con.commit()
    return effectiveness_profiles(con,root_type)

def register_release(con,scope_id,canary_id,released_at=None):
    p=_latest_approved_plan_for_scope(con,scope_id)
    if not p:
        return None
    sig=plan_signature(con,p["architecture_plan_id"])
    root=_root_type_for_plan(con,p["architecture_plan_id"])
    existing=con.execute("""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes
      WHERE architecture_plan_id=? AND canary_id=?""",(p["architecture_plan_id"],canary_id)).fetchone()
    if existing: return dict(existing)
    cur=con.execute("""INSERT INTO origin_threshold_architecture_plan_runtime_outcomes(
      architecture_plan_id,scope_id,canary_id,root_cause_type,plan_signature,status,released_at)
      VALUES(?,?,?,?,?,?,?)""",
      (p["architecture_plan_id"],scope_id,canary_id,root,sig,"ACTIVE",released_at or _now()))
    con.commit()
    runtime=dict(con.execute("""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes
                              WHERE architecture_runtime_outcome_id=?""",(cur.lastrowid,)).fetchone())
    from .origin_threshold_architecture_ranking import capture_runtime_context
    step_count=con.execute("""SELECT COUNT(*) n FROM origin_threshold_architecture_remediation_steps
      WHERE architecture_plan_id=? AND required=1""",(p["architecture_plan_id"],)).fetchone()["n"]
    capture_runtime_context(con,runtime["architecture_runtime_outcome_id"],scope_id,step_count)
    from .origin_threshold_recommendation_challenge import link_runtime
    link_runtime(con,scope_id,p["architecture_plan_id"],runtime["architecture_runtime_outcome_id"])
    _refresh_profile(con,root,sig)
    return runtime

def observe_runtime(con,scope_id,canary_id,*,is_regression=False,observed_at=None):
    r=con.execute("""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes
      WHERE scope_id=? AND canary_id=? ORDER BY architecture_runtime_outcome_id DESC LIMIT 1""",
      (scope_id,canary_id)).fetchone()
    if not r: return None
    if r["status"]!="ACTIVE": return dict(r)
    ts=observed_at or _now()
    first=r["first_observed_at"] or ts
    con.execute("""UPDATE origin_threshold_architecture_plan_runtime_outcomes
      SET first_observed_at=?,last_observed_at=?,observation_count=observation_count+1,
          healthy_observation_count=healthy_observation_count+?,
          regression_observation_count=regression_observation_count+?
      WHERE architecture_runtime_outcome_id=?""",
      (first,ts,0 if is_regression else 1,1 if is_regression else 0,
       r["architecture_runtime_outcome_id"]))
    con.commit()
    return maybe_mark_sustained(con,r["architecture_runtime_outcome_id"],now=ts)

def maybe_mark_sustained(con,runtime_outcome_id,now=None):
    r=con.execute("""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes
      WHERE architecture_runtime_outcome_id=?""",(runtime_outcome_id,)).fetchone()
    if not r: raise ValueError("runtime outcome not found")
    if r["status"]!="ACTIVE": return dict(r)
    current=_parse(now) if isinstance(now,str) else (now or datetime.now(timezone.utc))
    release=_parse(r["released_at"])
    days=(current-release).total_seconds()/86400.0 if release else 0.0
    if (r["observation_count"]>=SUSTAINED_OBSERVATION_MIN and
        r["regression_observation_count"]==0 and
        days>=SUSTAINED_DAYS_MIN):
        con.execute("""UPDATE origin_threshold_architecture_plan_runtime_outcomes
          SET status='SUSTAINED_SUCCESS',finalized_at=? WHERE architecture_runtime_outcome_id=?""",
          (_now(),runtime_outcome_id))
        con.commit()
        from .origin_threshold_recommendation_challenge import finalize_runtime
        finalize_runtime(con,runtime_outcome_id,"SUSTAINED_SUCCESS",None)
        _refresh_profile(con,r["root_cause_type"],r["plan_signature"])
    return dict(con.execute("""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes
                              WHERE architecture_runtime_outcome_id=?""",(runtime_outcome_id,)).fetchone())

def mark_reisolation_failure(con,scope_id,canary_id,reisolation_id,reisolated_at=None):
    r=con.execute("""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes
      WHERE scope_id=? AND canary_id=? AND status='ACTIVE'
      ORDER BY architecture_runtime_outcome_id DESC LIMIT 1""",(scope_id,canary_id)).fetchone()
    if not r: return None
    ts=reisolated_at or _now()
    release=_parse(r["released_at"]); rt=_parse(ts)
    days=(rt-release).total_seconds()/86400.0 if release and rt else None
    con.execute("""UPDATE origin_threshold_architecture_plan_runtime_outcomes
      SET status='RECURRENCE_FAILED',reisolation_id=?,reisolated_at=?,
          days_to_reisolation=?,finalized_at=?
      WHERE architecture_runtime_outcome_id=?""",
      (reisolation_id,ts,days,_now(),r["architecture_runtime_outcome_id"]))
    con.commit()
    from .origin_threshold_recommendation_challenge import finalize_runtime
    finalize_runtime(con,r["architecture_runtime_outcome_id"],"RECURRENCE_FAILED",days)
    _refresh_profile(con,r["root_cause_type"],r["plan_signature"])
    return dict(con.execute("""SELECT * FROM origin_threshold_architecture_plan_runtime_outcomes
                              WHERE architecture_runtime_outcome_id=?""",(r["architecture_runtime_outcome_id"],)).fetchone())

def recommend_plan(con,root_cause_type,default_steps,blocked_types=None,persist=True):
    blocked=set(blocked_types or [])
    profiles=effectiveness_profiles(con,root_cause_type)
    eligible=[
        p for p in profiles
        if p["confidence_band"] in ("EMERGING","ESTABLISHED")
        and p["effectiveness_score"] is not None
        and p["attempt_count"]>=ESTABLISHED_ATTEMPTS
        and p["recurrence_failure_count"]==0
    ]
    if eligible:
        best=eligible[0]
        steps=[x for x in best["plan_signature"].split("+") if x and x not in blocked]
        if len(steps)>=2:
            source="EFFECTIVENESS_MEMORY"
            confidence=best["confidence_band"]
            attempts=best["attempt_count"]
            score=best["effectiveness_score"]
            reasons=[f"historical plan signature {best['plan_signature']} has no recurrence failures",
                     f"attempts={attempts}",f"effectiveness_score={score:.3f}"]
        else:
            eligible=[]
    if not eligible:
        steps=[x for x in default_steps if x not in blocked]
        source="DETERMINISTIC_FALLBACK"
        confidence="LOW_DATA"
        attempts=0
        score=None
        reasons=["insufficient longitudinal architecture-plan evidence; deterministic fallback retained"]
    # ensure at least two layers.
    for x in ["COLLECTOR_FIX","INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX",
              "THRESHOLD_CHANGE","SOURCE_RULE_CHANGE"]:
        if len(steps)>=2: break
        if x not in blocked and x not in steps: steps.append(x)
    result={
        "policy_version":POLICY_VERSION,"root_cause_type":root_cause_type,
        "recommended_steps":steps[:3],"source":source,
        "confidence_band":confidence,"evidence_attempt_count":attempts,
        "effectiveness_score":score,"reasons":reasons
    }
    if persist:
        sig="+".join(sorted(set(result["recommended_steps"])))
        con.execute("""INSERT INTO origin_threshold_architecture_plan_recommendations(
          root_cause_type,blocked_types_json,recommended_signature,recommended_steps_json,
          source,confidence_band,evidence_attempt_count,effectiveness_score,reasons_json,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (root_cause_type,json.dumps(sorted(blocked),ensure_ascii=False),sig,
           json.dumps(result["recommended_steps"],ensure_ascii=False),source,confidence,
           attempts,score,json.dumps(reasons,ensure_ascii=False),_now()))
        con.commit()
    return result

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "runtime_outcomes":runtime_outcomes(con),
        "effectiveness_profiles":effectiveness_profiles(con),
        "recommendations":recommendations(con)
    }
