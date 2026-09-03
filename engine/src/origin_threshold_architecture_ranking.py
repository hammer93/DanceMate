import json, math, statistics
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MIN_DECISIVE_FOR_RANKING=3
MIN_SCORE_MARGIN=0.08
MIN_COMPARATIVE_SCORE=0.45

def _now():
    return datetime.now(timezone.utc).isoformat()

def _scope(con,scope_id):
    r=con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                     WHERE scope_id=?""",(scope_id,)).fetchone()
    return dict(r) if r else {}

def _latest_root_for_scope(con,scope_id):
    r=con.execute("""SELECT rc.* FROM origin_threshold_post_reintegration_root_causes rc
      JOIN origin_threshold_scope_reisolations ri ON ri.reisolation_id=rc.reisolation_id
      WHERE rc.scope_id=? ORDER BY rc.post_root_cause_id DESC LIMIT 1""",
      (scope_id,)).fetchone()
    return dict(r) if r else {}

def _alternative_available(con,scope_id):
    scope=_scope(con,scope_id)
    source=scope.get("source_id")
    rule=scope.get("rule_key")
    if not source:
        return False
    row=con.execute("""SELECT 1 FROM origin_threshold_scope_route_evaluations
      WHERE trigger_source_id=? AND (? IS NULL OR rule_key=?)
        AND route_status IN ('SAFE_ALTERNATIVE_SELECTED','SAFE_ALTERNATIVE_AVAILABLE')
      ORDER BY scope_route_id DESC LIMIT 1""",(source,rule,rule)).fetchone()
    return bool(row)

def context_for_scope(con,scope_id):
    scope=_scope(con,scope_id)
    root=_latest_root_for_scope(con,scope_id)
    return {
        "scope_type":scope.get("scope_type") or "UNKNOWN",
        "source_id":scope.get("source_id"),
        "platform":scope.get("platform"),
        "rule_key":scope.get("rule_key"),
        "secondary_root_cause_type":root.get("secondary_root_cause_type"),
        "alternative_route_available":_alternative_available(con,scope_id),
    }

def context_signature(ctx):
    vals=[
        ctx.get("scope_type") or "*",
        ctx.get("source_id") or "*",
        ctx.get("platform") or "*",
        ctx.get("rule_key") or "*",
        ctx.get("secondary_root_cause_type") or "*",
        "ALT1" if ctx.get("alternative_route_available") else "ALT0",
    ]
    return "|".join(vals)

def capture_runtime_context(con,runtime_outcome_id,scope_id,plan_step_count):
    existing=con.execute("""SELECT * FROM origin_threshold_architecture_runtime_contexts
      WHERE architecture_runtime_outcome_id=?""",(runtime_outcome_id,)).fetchone()
    if existing:
        return dict(existing)
    ctx=context_for_scope(con,scope_id)
    cur=con.execute("""INSERT INTO origin_threshold_architecture_runtime_contexts(
      architecture_runtime_outcome_id,scope_type,source_id,platform,rule_key,
      secondary_root_cause_type,alternative_route_available,plan_step_count,
      context_json,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (runtime_outcome_id,ctx["scope_type"],ctx["source_id"],ctx["platform"],
       ctx["rule_key"],ctx["secondary_root_cause_type"],
       int(bool(ctx["alternative_route_available"])),int(plan_step_count),
       json.dumps(ctx,ensure_ascii=False),_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_architecture_runtime_contexts
                              WHERE architecture_runtime_context_id=?""",(cur.lastrowid,)).fetchone())

def _wilson_lower(successes,n,z=1.96):
    if n<=0: return 0.0
    phat=successes/n
    denom=1+z*z/n
    center=phat+z*z/(2*n)
    adj=z*math.sqrt((phat*(1-phat)+z*z/(4*n))/n)
    return max(0.0,(center-adj)/denom)

def _context_similarity(candidate,target):
    weights={
        "scope_type":0.20,
        "source_id":0.20,
        "platform":0.15,
        "rule_key":0.10,
        "secondary_root_cause_type":0.10,
        "alternative_route_available":0.10,
    }
    score=0.15  # root cause exact match is handled by query; reserve baseline.
    for key,w in weights.items():
        tv=target.get(key)
        cv=candidate.get(key)
        if tv is None:
            score+=w*0.5
        elif cv==tv:
            score+=w
    return min(1.0,score)

def _severity_penalty(rows):
    failures=[r for r in rows if r["status"]=="RECURRENCE_FAILED"]
    if not failures: return 0.0
    vals=[]
    for r in failures:
        d=r["days_to_reisolation"]
        if d is None: vals.append(0.75)
        elif d<=7: vals.append(1.0)
        elif d<=30: vals.append(0.65)
        elif d<=90: vals.append(0.35)
        else: vals.append(0.15)
    return sum(vals)/len(vals)

def _median_survival(rows):
    vals=[]
    for r in rows:
        if r["status"]=="SUSTAINED_SUCCESS":
            vals.append(90.0)
        elif r["status"]=="RECURRENCE_FAILED" and r["days_to_reisolation"] is not None:
            vals.append(float(r["days_to_reisolation"]))
    return statistics.median(vals) if vals else None

def _candidate_contexts(con,root_cause_type,signature):
    rows=con.execute("""SELECT o.*,c.scope_type,c.source_id,c.platform,c.rule_key,
      c.secondary_root_cause_type,c.alternative_route_available,c.plan_step_count
      FROM origin_threshold_architecture_plan_runtime_outcomes o
      LEFT JOIN origin_threshold_architecture_runtime_contexts c
        ON c.architecture_runtime_outcome_id=o.architecture_runtime_outcome_id
      WHERE o.root_cause_type=? AND o.plan_signature=?""",
      (root_cause_type,signature)).fetchall()
    return [dict(r) for r in rows]

def comparative_scores(con,root_cause_type,target_context,persist=True):
    signatures=[r["plan_signature"] for r in con.execute(
        """SELECT DISTINCT plan_signature FROM origin_threshold_architecture_plan_runtime_outcomes
           WHERE root_cause_type=?""",(root_cause_type,)).fetchall()]
    results=[]
    target_sig=context_signature(target_context)
    for sig in signatures:
        rows=_candidate_contexts(con,root_cause_type,sig)
        decisive=[r for r in rows if r["status"] in ("SUSTAINED_SUCCESS","RECURRENCE_FAILED")]
        successes=sum(r["status"]=="SUSTAINED_SUCCESS" for r in decisive)
        failures=sum(r["status"]=="RECURRENCE_FAILED" for r in decisive)
        n=len(decisive)
        if not rows: continue
        bayes=(successes+1)/(n+2)
        wilson=_wilson_lower(successes,n)
        survival=_median_survival(rows)
        survival_score=min((survival or 0.0)/90.0,1.0)
        severity=_severity_penalty(rows)
        context_vals=[]
        for r in rows:
            ctx={
                "scope_type":r.get("scope_type") or "UNKNOWN",
                "source_id":r.get("source_id"),
                "platform":r.get("platform"),
                "rule_key":r.get("rule_key"),
                "secondary_root_cause_type":r.get("secondary_root_cause_type"),
                "alternative_route_available":bool(r.get("alternative_route_available")),
            }
            context_vals.append(_context_similarity(ctx,target_context))
        context_sim=max(context_vals) if context_vals else 0.15
        evidence=min(n/5.0,1.0)
        step_counts=[int(r["plan_step_count"]) for r in rows if r.get("plan_step_count")]
        step_count=round(sum(step_counts)/len(step_counts)) if step_counts else max(2,len(sig.split("+")))
        complexity=max(0.0,(step_count-2)*0.05)
        # Conservative weighted score. Wilson lower bound dominates raw success rate.
        score=(
            wilson*0.35
            + bayes*0.15
            + survival_score*0.15
            + context_sim*0.20
            + evidence*0.15
            - severity*0.15
            - complexity
        )
        score=max(0.0,min(1.0,score))
        if n<3:
            conf="LOW_DATA"
        elif n<5:
            conf="EMERGING"
        else:
            conf="ESTABLISHED"
        reasons=[
            f"decisive={n}, success={successes}, failure={failures}",
            f"wilson_lower={wilson:.3f}, bayesian_success={bayes:.3f}",
            f"median_survival_days={survival}",
            f"context_similarity={context_sim:.3f}",
            f"evidence_factor={evidence:.3f}",
            f"recurrence_severity_penalty={severity:.3f}",
            f"complexity_penalty={complexity:.3f}",
        ]
        item={
            "policy_version":POLICY_VERSION,
            "root_cause_type":root_cause_type,"plan_signature":sig,
            "context_signature":target_sig,"attempt_count":len(rows),"decisive_count":n,
            "sustained_success_count":successes,"recurrence_failure_count":failures,
            "bayesian_success_rate":bayes,"wilson_lower_bound":wilson,
            "median_survival_days":survival,"context_similarity":context_sim,
            "evidence_factor":evidence,"complexity_penalty":complexity,
            "recurrence_severity_penalty":severity,"comparative_score":score,
            "confidence_band":conf,"reasons":reasons
        }
        if persist:
            con.execute("""INSERT INTO origin_threshold_architecture_comparative_scores(
              root_cause_type,plan_signature,context_signature,attempt_count,decisive_count,
              sustained_success_count,recurrence_failure_count,bayesian_success_rate,
              wilson_lower_bound,median_survival_days,context_similarity,evidence_factor,
              complexity_penalty,recurrence_severity_penalty,comparative_score,
              confidence_band,reasons_json,scored_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (root_cause_type,sig,target_sig,len(rows),n,successes,failures,bayes,wilson,
               survival,context_sim,evidence,complexity,severity,score,conf,
               json.dumps(reasons,ensure_ascii=False),_now()))
        results.append(item)
    if persist: con.commit()
    return sorted(results,key=lambda x:(x["comparative_score"],x["decisive_count"]),reverse=True)

def score_history(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_architecture_comparative_scores"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY architecture_comparative_score_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def recommendation_history(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_architecture_context_recommendations"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY context_recommendation_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r)
        x["blocked_types"]=json.loads(x.pop("blocked_types_json"))
        x["selected_steps"]=json.loads(x.pop("selected_steps_json"))
        x["reasons"]=json.loads(x.pop("reasons_json"))
        out.append(x)
    return out

def recommend_contextual_plan(con,root_cause_type,target_context,default_steps,
                              blocked_types=None,persist=True):
    blocked=set(blocked_types or [])
    scores=comparative_scores(con,root_cause_type,target_context,persist=persist)
    eligible=[]
    for s in scores:
        steps=[x for x in s["plan_signature"].split("+") if x]
        safe_steps=[x for x in steps if x not in blocked]
        if (s["decisive_count"]>=MIN_DECISIVE_FOR_RANKING
            and s["confidence_band"] in ("EMERGING","ESTABLISHED")
            and len(safe_steps)>=2
            and s["comparative_score"]>=MIN_COMPARATIVE_SCORE):
            eligible.append((s,safe_steps))
    reasons=[]
    if eligible:
        best,best_steps=eligible[0]
        runner=eligible[1][0]["comparative_score"] if len(eligible)>1 else None
        margin=(best["comparative_score"]-runner) if runner is not None else best["comparative_score"]
        if runner is not None and margin<MIN_SCORE_MARGIN:
            source="CONSERVATIVE_TIE_FALLBACK"
            steps=[x for x in default_steps if x not in blocked]
            confidence="LOW_DATA"
            score=None
            reasons.append(
                f"top comparative plans are too close (margin={margin:.3f} < {MIN_SCORE_MARGIN:.3f})")
            evidence=0
        else:
            source="CONTEXT_COMPARATIVE_RANKING"
            steps=best_steps
            confidence=best["confidence_band"]
            score=best["comparative_score"]
            evidence=best["decisive_count"]
            reasons.extend(best["reasons"])
            reasons.append(f"selected by context-aware comparative ranking, margin={margin:.3f}")
    else:
        source="DETERMINISTIC_FALLBACK"
        steps=[x for x in default_steps if x not in blocked]
        confidence="LOW_DATA"
        score=None
        runner=None
        margin=None
        evidence=0
        reasons.append("no context-comparable plan has sufficient conservative evidence")
    for x in ["COLLECTOR_FIX","INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX",
              "THRESHOLD_CHANGE","SOURCE_RULE_CHANGE"]:
        if len(steps)>=2: break
        if x not in blocked and x not in steps: steps.append(x)
    steps=steps[:3]
    result={
        "policy_version":POLICY_VERSION,"root_cause_type":root_cause_type,
        "target_context":target_context,"context_signature":context_signature(target_context),
        "selected_steps":steps,"source":source,"confidence_band":confidence,
        "comparative_score":score,"runner_up_score":runner,
        "score_margin":margin,"evidence_attempt_count":evidence,"reasons":reasons
    }
    if persist:
        con.execute("""INSERT INTO origin_threshold_architecture_context_recommendations(
          root_cause_type,context_signature,blocked_types_json,selected_plan_signature,
          selected_steps_json,source,confidence_band,comparative_score,runner_up_score,
          score_margin,evidence_attempt_count,reasons_json,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (root_cause_type,result["context_signature"],json.dumps(sorted(blocked),ensure_ascii=False),
           "+".join(sorted(set(steps))),json.dumps(steps,ensure_ascii=False),source,confidence,
           score,runner,margin,evidence,json.dumps(reasons,ensure_ascii=False),_now()))
        con.commit()
    return result

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "scores":score_history(con),
        "recommendations":recommendation_history(con)
    }
