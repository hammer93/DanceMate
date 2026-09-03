import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MIN_DECISIVE=8
MIN_DISTINCT_EVENTS=8

def _now():
    return datetime.now(timezone.utc).isoformat()

def _steps_sig(steps):
    return "+".join(sorted(set(steps)))

def create_challenge(con,scope_id,root_cause_type,context_signature,
                     recommendation,deterministic_steps):
    existing=con.execute("""SELECT * FROM origin_threshold_architecture_recommendation_challenges
      WHERE scope_id=? AND status IN ('SHADOW_ACTIVE','READY_FOR_HUMAN_DECISION','HOLD')
      ORDER BY challenge_id DESC LIMIT 1""",(scope_id,)).fetchone()
    if existing:
        return challenge(con,existing["challenge_id"])
    rec_steps=recommendation["selected_steps"]
    det_steps=list(deterministic_steps)
    cur=con.execute("""INSERT INTO origin_threshold_architecture_recommendation_challenges(
      scope_id,root_cause_type,context_signature,recommendation_source,
      recommended_signature,recommended_steps_json,deterministic_signature,
      deterministic_steps_json,recommended_score,deterministic_score,status,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (scope_id,root_cause_type,context_signature,recommendation["source"],
       _steps_sig(rec_steps),json.dumps(rec_steps,ensure_ascii=False),
       _steps_sig(det_steps),json.dumps(det_steps,ensure_ascii=False),
       recommendation.get("comparative_score"),None,"SHADOW_ACTIVE",_now()))
    con.commit()
    from .origin_threshold_recommendation_versioning import current_version,link_entity
    alg=current_version(con,root_cause_type)
    link_entity(con,alg["algorithm_version_id"],root_cause_type,
                "CHALLENGE",cur.lastrowid,"EVALUATED_BY")
    result=challenge(con,cur.lastrowid)
    result["algorithm_version_id"]=alg["algorithm_version_id"]
    result["algorithm_version_label"]=alg["version_label"]
    return result

def challenge(con,challenge_id):
    r=con.execute("""SELECT * FROM origin_threshold_architecture_recommendation_challenges
                     WHERE challenge_id=?""",(challenge_id,)).fetchone()
    if not r: raise ValueError("challenge not found")
    x=dict(r)
    x["recommended_steps"]=json.loads(x.pop("recommended_steps_json"))
    x["deterministic_steps"]=json.loads(x.pop("deterministic_steps_json"))
    return x

def challenges(con,scope_id=None):
    if scope_id is None:
        rows=con.execute("""SELECT challenge_id FROM origin_threshold_architecture_recommendation_challenges
                            ORDER BY challenge_id""").fetchall()
    else:
        rows=con.execute("""SELECT challenge_id FROM origin_threshold_architecture_recommendation_challenges
                            WHERE scope_id=? ORDER BY challenge_id""",(scope_id,)).fetchall()
    return [challenge(con,r["challenge_id"]) for r in rows]

def add_shadow_outcome(con,challenge_id,event_instance_id,recommended_outcome,
                       deterministic_outcome,*,human_confirmed=False,
                       recommended_quality_delta=None,deterministic_quality_delta=None):
    if recommended_outcome not in ("SAFE","UNSAFE","HOLD"):
        raise ValueError("invalid recommended_outcome")
    if deterministic_outcome not in ("SAFE","UNSAFE","HOLD"):
        raise ValueError("invalid deterministic_outcome")
    ch=challenge(con,challenge_id)
    if ch["status"] not in ("SHADOW_ACTIVE","READY_FOR_HUMAN_DECISION","HOLD"):
        raise ValueError("challenge is not accepting Shadow outcomes")
    con.execute("""INSERT INTO origin_threshold_architecture_challenge_shadow_outcomes(
      challenge_id,event_instance_id,recommended_outcome,deterministic_outcome,
      human_confirmed,recommended_quality_delta,deterministic_quality_delta,observed_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (challenge_id,event_instance_id,recommended_outcome,deterministic_outcome,
       int(bool(human_confirmed)),recommended_quality_delta,
       deterministic_quality_delta,_now()))
    con.commit()
    return evaluate_challenge(con,challenge_id,persist=True)

def _classify(r):
    if not r["human_confirmed"]: return None
    rec=r["recommended_outcome"]; det=r["deterministic_outcome"]
    if rec=="SAFE" and det!="SAFE": return "RECOMMENDED_WIN"
    if det=="SAFE" and rec!="SAFE": return "DETERMINISTIC_WIN"
    if rec=="SAFE" and det=="SAFE":
        rq=r["recommended_quality_delta"]; dq=r["deterministic_quality_delta"]
        if rq is not None and dq is not None:
            if float(rq)>float(dq)+0.02: return "RECOMMENDED_WIN"
            if float(dq)>float(rq)+0.02: return "DETERMINISTIC_WIN"
        return "TIE"
    if rec=="UNSAFE" and det=="UNSAFE": return "TIE"
    return "TIE"

def evaluate_challenge(con,challenge_id,persist=True):
    ch=challenge(con,challenge_id)
    rows=[dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_architecture_challenge_shadow_outcomes
           WHERE challenge_id=? ORDER BY challenge_shadow_id""",(challenge_id,)).fetchall()]
    classes=[_classify(r) for r in rows]
    classes=[x for x in classes if x]
    decisive=len(classes)
    distinct=len({r["event_instance_id"] for r in rows if r["human_confirmed"]})
    rw=classes.count("RECOMMENDED_WIN")
    dw=classes.count("DETERMINISTIC_WIN")
    tie=classes.count("TIE")
    rec_loss=dw
    rate=(rw/(rw+dw)) if (rw+dw)>0 else None
    reasons=[]
    if decisive<MIN_DECISIVE:
        reasons.append(f"need >= {MIN_DECISIVE} Human-confirmed Shadow outcomes; have {decisive}")
    if distinct<MIN_DISTINCT_EVENTS:
        reasons.append(f"need >= {MIN_DISTINCT_EVENTS} distinct Events; have {distinct}")
    status="READY_FOR_HUMAN_DECISION" if not reasons else "SHADOW_ACTIVE"
    if ch["status"]!="HOLD":
        con.execute("""UPDATE origin_threshold_architecture_recommendation_challenges
                       SET status=? WHERE challenge_id=?""",(status,challenge_id))
    result={
        "policy_version":POLICY_VERSION,"challenge_id":challenge_id,
        "decisive_count":decisive,"distinct_event_count":distinct,
        "recommended_win_count":rw,"deterministic_win_count":dw,
        "tie_count":tie,"recommended_loss_count":rec_loss,
        "recommended_win_rate":rate,"status":status,"reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_architecture_challenge_evaluations(
          challenge_id,decisive_count,distinct_event_count,recommended_win_count,
          deterministic_win_count,tie_count,recommended_loss_count,
          recommended_win_rate,status,reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
          (challenge_id,decisive,distinct,rw,dw,tie,rec_loss,rate,status,
           json.dumps(reasons,ensure_ascii=False),_now()))
        result["challenge_evaluation_id"]=cur.lastrowid
        con.commit()
    return result

def human_decision(con,challenge_id,decision,reviewer,reason):
    if decision not in ("ACCEPT_RECOMMENDATION","CHOOSE_BASELINE","HOLD","REJECT"):
        raise ValueError("invalid challenge decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    ev=evaluate_challenge(con,challenge_id,persist=True)
    if decision in ("ACCEPT_RECOMMENDATION","CHOOSE_BASELINE") and ev["status"]!="READY_FOR_HUMAN_DECISION":
        raise ValueError("challenge is not ready for Human decision")
    status={
        "ACCEPT_RECOMMENDATION":"HUMAN_ACCEPTED_RECOMMENDATION",
        "CHOOSE_BASELINE":"HUMAN_SELECTED_BASELINE",
        "HOLD":"HOLD","REJECT":"REJECTED"
    }[decision]
    con.execute("""UPDATE origin_threshold_architecture_recommendation_challenges
                   SET status=? WHERE challenge_id=?""",(status,challenge_id))
    con.execute("""INSERT INTO origin_threshold_architecture_challenge_human_decisions(
      challenge_id,decision,reviewer,reason,challenge_evaluation_id,decided_at)
      VALUES(?,?,?,?,?,?)""",
      (challenge_id,decision,reviewer,reason,ev.get("challenge_evaluation_id"),_now()))
    con.commit()
    _refresh_quality_profile(con,challenge(con,challenge_id)["root_cause_type"])
    return {"challenge":challenge(con,challenge_id),"decision":decision,
            "evaluation":ev}

def selected_steps_for_scope(con,scope_id):
    r=con.execute("""SELECT c.*,d.decision
      FROM origin_threshold_architecture_recommendation_challenges c
      JOIN origin_threshold_architecture_challenge_human_decisions d
        ON d.challenge_id=c.challenge_id
      WHERE c.scope_id=? AND d.decision IN ('ACCEPT_RECOMMENDATION','CHOOSE_BASELINE')
      ORDER BY d.challenge_decision_id DESC LIMIT 1""",(scope_id,)).fetchone()
    if not r: return None
    if r["decision"]=="ACCEPT_RECOMMENDATION":
        steps=json.loads(r["recommended_steps_json"]); side="RECOMMENDATION"
    else:
        steps=json.loads(r["deterministic_steps_json"]); side="BASELINE"
    return {"challenge_id":r["challenge_id"],"decision":r["decision"],
            "selected_side":side,"steps":steps}

def link_runtime(con,scope_id,architecture_plan_id,runtime_outcome_id):
    sel=selected_steps_for_scope(con,scope_id)
    if sel:
        ch=challenge(con,sel["challenge_id"])
    else:
        row=con.execute("""SELECT challenge_id FROM origin_threshold_architecture_recommendation_challenges
          WHERE scope_id=? ORDER BY challenge_id DESC LIMIT 1""",(scope_id,)).fetchone()
        if not row:
            return None
        ch=challenge(con,row["challenge_id"])
        step_rows=con.execute("""SELECT remediation_type
          FROM origin_threshold_architecture_remediation_steps
          WHERE architecture_plan_id=? AND required=1 ORDER BY remediation_type""",
          (architecture_plan_id,)).fetchall()
        plan_sig=_steps_sig([r["remediation_type"] for r in step_rows])
        if plan_sig==ch["recommended_signature"]:
            side="RECOMMENDATION"
        elif plan_sig==ch["deterministic_signature"]:
            side="BASELINE"
        else:
            side="UNKNOWN"
        sel={
            "challenge_id":ch["challenge_id"],
            "decision":"POLICY_SELECTION",
            "selected_side":side,
            "steps":[r["remediation_type"] for r in step_rows]
        }
    existing=con.execute("""SELECT * FROM origin_threshold_architecture_challenge_runtime_results
      WHERE challenge_id=?""",(ch["challenge_id"],)).fetchone()
    if existing: return dict(existing)
    sig=_steps_sig(sel["steps"])
    cur=con.execute("""INSERT INTO origin_threshold_architecture_challenge_runtime_results(
      challenge_id,architecture_plan_id,architecture_runtime_outcome_id,human_decision,
      selected_signature,selected_side,runtime_status)
      VALUES(?,?,?,?,?,?,?)""",
      (ch["challenge_id"],architecture_plan_id,runtime_outcome_id,
       sel["decision"],sig,sel["selected_side"],"ACTIVE"))
    con.commit()
    from .origin_threshold_recommendation_versioning import (
        version_for_entity,link_entity
    )
    alg=version_for_entity(con,"CHALLENGE",ch["challenge_id"],"EVALUATED_BY")
    if alg:
        link_entity(con,alg["algorithm_version_id"],ch["root_cause_type"],
                    "CHALLENGE_RUNTIME",cur.lastrowid,"RUNTIME_OF")
    from .origin_threshold_recommendation_version_cohort import register_runtime as register_version_runtime
    register_version_runtime(con,cur.lastrowid)
    return dict(con.execute("""SELECT * FROM origin_threshold_architecture_challenge_runtime_results
                              WHERE challenge_runtime_result_id=?""",(cur.lastrowid,)).fetchone())

def finalize_runtime(con,runtime_outcome_id,status,days_to_reisolation=None):
    rr=con.execute("""SELECT * FROM origin_threshold_architecture_challenge_runtime_results
      WHERE architecture_runtime_outcome_id=?""",(runtime_outcome_id,)).fetchone()
    if not rr: return None
    ch=challenge(con,rr["challenge_id"])
    # Counterfactual verdict uses pre-release Shadow challenge + real selected runtime.
    ev=con.execute("""SELECT * FROM origin_threshold_architecture_challenge_evaluations
      WHERE challenge_id=? ORDER BY challenge_evaluation_id DESC LIMIT 1""",
      (ch["challenge_id"],)).fetchone()
    if status=="SUSTAINED_SUCCESS":
        if rr["selected_side"]=="RECOMMENDATION":
            verdict="RECOMMENDATION_HELPFUL" if (ev and ev["recommended_win_count"]>=ev["deterministic_win_count"]) else "RUNTIME_SUCCESS_SHADOW_MIXED"
        else:
            verdict="BASELINE_HELPFUL" if (ev and ev["deterministic_win_count"]>=ev["recommended_win_count"]) else "RUNTIME_SUCCESS_SHADOW_MIXED"
    elif status=="RECURRENCE_FAILED":
        if rr["selected_side"]=="RECOMMENDATION" and ev and ev["deterministic_win_count"]>ev["recommended_win_count"]:
            verdict="RECOMMENDATION_HARMFUL"
        elif rr["selected_side"]=="BASELINE" and ev and ev["recommended_win_count"]>ev["deterministic_win_count"]:
            verdict="MISSED_RECOMMENDATION_OPPORTUNITY"
        else:
            verdict="RUNTIME_FAILURE_INCONCLUSIVE"
    else:
        verdict=None
    con.execute("""UPDATE origin_threshold_architecture_challenge_runtime_results
      SET runtime_status=?,counterfactual_verdict=?,days_to_reisolation=?,finalized_at=?
      WHERE challenge_runtime_result_id=?""",
      (status,verdict,days_to_reisolation,_now(),rr["challenge_runtime_result_id"]))
    con.commit()
    _refresh_quality_profile(con,ch["root_cause_type"])
    from .origin_threshold_recommendation_policy import observe_runtime_verdict
    policy_state=observe_runtime_verdict(con,ch["challenge_id"],verdict)
    from .origin_threshold_recommendation_version_cohort import finalize_runtime as finalize_version_runtime
    version_cohort=finalize_version_runtime(con,rr["challenge_runtime_result_id"])
    result=dict(con.execute("""SELECT * FROM origin_threshold_architecture_challenge_runtime_results
                              WHERE challenge_runtime_result_id=?""",(rr["challenge_runtime_result_id"],)).fetchone())
    result["recommendation_policy_state"]=policy_state
    result["algorithm_version_runtime_cohort"]=version_cohort
    return result

def runtime_results(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_architecture_challenge_runtime_results
           ORDER BY challenge_runtime_result_id""").fetchall()]

def _refresh_quality_profile(con,root_cause_type):
    ch=con.execute("""SELECT COUNT(*) n FROM origin_threshold_architecture_recommendation_challenges
                      WHERE root_cause_type=?""",(root_cause_type,)).fetchone()["n"]
    decisions=con.execute("""SELECT d.decision FROM origin_threshold_architecture_challenge_human_decisions d
      JOIN origin_threshold_architecture_recommendation_challenges c ON c.challenge_id=d.challenge_id
      WHERE c.root_cause_type=?""",(root_cause_type,)).fetchall()
    accepted=sum(r["decision"]=="ACCEPT_RECOMMENDATION" for r in decisions)
    base=sum(r["decision"]=="CHOOSE_BASELINE" for r in decisions)
    hold=sum(r["decision"]=="HOLD" for r in decisions)
    runs=con.execute("""SELECT rr.* FROM origin_threshold_architecture_challenge_runtime_results rr
      JOIN origin_threshold_architecture_recommendation_challenges c ON c.challenge_id=rr.challenge_id
      WHERE c.root_cause_type=? AND rr.runtime_status IN ('SUSTAINED_SUCCESS','RECURRENCE_FAILED')""",
      (root_cause_type,)).fetchall()
    helpful=sum(r["counterfactual_verdict"]=="RECOMMENDATION_HELPFUL" for r in runs)
    harmful=sum(r["counterfactual_verdict"]=="RECOMMENDATION_HARMFUL" for r in runs)
    neutral=len(runs)-helpful-harmful
    acceptance=(accepted/(accepted+base)) if (accepted+base)>0 else None
    helpful_rate=(helpful/len(runs)) if runs else None
    harmful_rate=(harmful/len(runs)) if runs else None
    if len(runs)<3: conf="LOW_DATA"
    elif len(runs)<5: conf="EMERGING"
    else: conf="ESTABLISHED"
    vals=(ch,accepted,base,hold,len(runs),helpful,harmful,neutral,
          acceptance,helpful_rate,harmful_rate,conf,_now())
    ex=con.execute("""SELECT recommendation_quality_profile_id
      FROM origin_threshold_architecture_recommendation_quality_profiles
      WHERE root_cause_type=?""",(root_cause_type,)).fetchone()
    if ex:
        con.execute("""UPDATE origin_threshold_architecture_recommendation_quality_profiles
          SET challenge_count=?,accepted_count=?,baseline_selected_count=?,hold_count=?,
              runtime_decisive_count=?,recommendation_helpful_count=?,
              recommendation_harmful_count=?,recommendation_neutral_count=?,
              acceptance_rate=?,helpful_rate=?,harmful_rate=?,confidence_band=?,updated_at=?
          WHERE recommendation_quality_profile_id=?""",
          vals+(ex["recommendation_quality_profile_id"],))
    else:
        con.execute("""INSERT INTO origin_threshold_architecture_recommendation_quality_profiles(
          root_cause_type,challenge_count,accepted_count,baseline_selected_count,hold_count,
          runtime_decisive_count,recommendation_helpful_count,recommendation_harmful_count,
          recommendation_neutral_count,acceptance_rate,helpful_rate,harmful_rate,
          confidence_band,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(root_cause_type,)+vals)
    con.commit()

def quality_profiles(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_architecture_recommendation_quality_profiles
           ORDER BY recommendation_quality_profile_id""").fetchall()]

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "challenges":challenges(con),
        "runtime_results":runtime_results(con),
        "quality_profiles":quality_profiles(con)
    }
