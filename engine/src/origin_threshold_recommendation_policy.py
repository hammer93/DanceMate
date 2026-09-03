import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"

MIN_RUNTIME_DECISIVE=5
MIN_HELPFUL_RATE=0.60
MAX_HARMFUL_RATE=0.10
MIN_ACCEPTANCE_RATE=0.60
DEFAULT_CANARY_MAX=3
MIN_CANARY_HELPFUL=2

MODES=("SHADOW_ONLY","CANARY","READY_FOR_PROMOTION","PROMOTED","ROLLED_BACK")

def _now():
    return datetime.now(timezone.utc).isoformat()

def _profile(con,root_cause_type):
    r=con.execute("""SELECT * FROM origin_threshold_architecture_recommendation_quality_profiles
                     WHERE root_cause_type=?""",(root_cause_type,)).fetchone()
    return dict(r) if r else None

def _ensure_state(con,root_cause_type):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_states
                     WHERE root_cause_type=?""",(root_cause_type,)).fetchone()
    if not r:
        con.execute("""INSERT INTO origin_threshold_recommendation_policy_states(
          root_cause_type,mode,canary_max_assignments,updated_at)
          VALUES(?,?,?,?)""",
          (root_cause_type,"SHADOW_ONLY",DEFAULT_CANARY_MAX,_now()))
        con.commit()
        r=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_states
                         WHERE root_cause_type=?""",(root_cause_type,)).fetchone()
    return dict(r)

def states(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recommendation_policy_states
           ORDER BY policy_state_id""").fetchall()]

def candidates(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_recommendation_policy_candidates"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY policy_candidate_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def events(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_recommendation_policy_events"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY policy_event_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def _event(con,root,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_policy_events(
      root_cause_type,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (root,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def evaluate_candidate(con,root_cause_type,persist=True):
    p=_profile(con,root_cause_type)
    reasons=[]
    if not p:
        return {
            "policy_version":POLICY_VERSION,"root_cause_type":root_cause_type,
            "status":"NO_PROFILE","eligible":False,
            "reasons":["recommendation quality profile does not exist"]
        }
    decisive=int(p["runtime_decisive_count"] or 0)
    helpful=float(p["helpful_rate"] or 0.0)
    harmful=float(p["harmful_rate"] or 0.0)
    acceptance=p["acceptance_rate"]
    acceptance=float(acceptance) if acceptance is not None else 0.0

    if decisive<MIN_RUNTIME_DECISIVE:
        reasons.append(f"runtime decisive {decisive}/{MIN_RUNTIME_DECISIVE}")
    if p["confidence_band"]!="ESTABLISHED":
        reasons.append(f"quality confidence must be ESTABLISHED; have {p['confidence_band']}")
    if helpful<MIN_HELPFUL_RATE:
        reasons.append(f"helpful rate {helpful:.3f} < {MIN_HELPFUL_RATE:.3f}")
    if harmful>MAX_HARMFUL_RATE:
        reasons.append(f"harmful rate {harmful:.3f} > {MAX_HARMFUL_RATE:.3f}")
    if acceptance<MIN_ACCEPTANCE_RATE:
        reasons.append(f"acceptance rate {acceptance:.3f} < {MIN_ACCEPTANCE_RATE:.3f}")

    eligible=not reasons
    status="READY_FOR_POLICY_REVIEW" if eligible else "WARMING"
    result={
        "policy_version":POLICY_VERSION,"root_cause_type":root_cause_type,
        "quality_profile_id":p["recommendation_quality_profile_id"],
        "runtime_decisive_count":decisive,"helpful_rate":helpful,
        "harmful_rate":harmful,"acceptance_rate":acceptance,
        "baseline_selected_count":int(p["baseline_selected_count"] or 0),
        "eligible":eligible,"status":status,"reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_recommendation_policy_candidates(
          root_cause_type,quality_profile_id,runtime_decisive_count,helpful_rate,
          harmful_rate,acceptance_rate,baseline_selected_count,status,reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (root_cause_type,p["recommendation_quality_profile_id"],decisive,helpful,
           harmful,acceptance,int(p["baseline_selected_count"] or 0),status,
           json.dumps(reasons,ensure_ascii=False),_now()))
        result["policy_candidate_id"]=cur.lastrowid
        con.commit()
        from .origin_threshold_recommendation_versioning import current_version,link_entity
        alg=current_version(con,root_cause_type)
        link_entity(con,alg["algorithm_version_id"],root_cause_type,
                    "POLICY_CANDIDATE",cur.lastrowid,"CANDIDATE_FOR")
        result["algorithm_version_id"]=alg["algorithm_version_id"]
        result["algorithm_version_label"]=alg["version_label"]
    return result

def review_candidate(con,candidate_id,decision,reviewer,reason,canary_max=DEFAULT_CANARY_MAX):
    if decision not in ("APPROVE_CANARY","REJECT","HOLD"):
        raise ValueError("invalid policy review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    c=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_candidates
                     WHERE policy_candidate_id=?""",(candidate_id,)).fetchone()
    if not c: raise ValueError("policy candidate not found")
    root=c["root_cause_type"]
    if decision=="APPROVE_CANARY" and c["status"]!="READY_FOR_POLICY_REVIEW":
        raise ValueError("policy candidate is not ready for canary")
    if canary_max<1 or canary_max>10:
        raise ValueError("canary_max must be 1..10")
    st=_ensure_state(con,root)
    if decision=="APPROVE_CANARY" and st["mode"] in ("ROLLED_BACK","LONG_TERM_SHADOW_ONLY"):
        raise ValueError("rollback recovery qualification is required before re-canary")
    if decision=="APPROVE_CANARY":
        mode="CANARY"
        from .origin_threshold_recommendation_versioning import version_for_entity,mark_status
        alg=version_for_entity(con,"POLICY_CANDIDATE",candidate_id,"CANDIDATE_FOR")
        if alg:
            mark_status(con,alg["algorithm_version_id"],"CANARY",reviewer,
                        "Human approved recommendation policy canary")
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
          SET mode='CANARY',candidate_id=?,canary_max_assignments=?,
              canary_assigned_count=0,canary_helpful_count=0,
              canary_harmful_count=0,canary_neutral_count=0,
              rolled_back_at=NULL,rollback_reason=NULL,updated_at=?
          WHERE root_cause_type=?""",
          (candidate_id,canary_max,_now(),root))
    elif decision=="HOLD":
        mode=st["mode"]
    else:
        mode="SHADOW_ONLY"
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
          SET mode='SHADOW_ONLY',candidate_id=?,updated_at=?
          WHERE root_cause_type=?""",(candidate_id,_now(),root))
    con.execute("""INSERT INTO origin_threshold_recommendation_policy_reviews(
      root_cause_type,candidate_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?,?)""",(root,candidate_id,decision,reviewer,reason,_now()))
    con.commit()
    _event(con,root,"POLICY_REVIEW",reviewer,
           {"candidate_id":candidate_id,"decision":decision,"mode":mode,"reason":reason})
    return _ensure_state(con,root)

def _assignment(con,challenge_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_canary_assignments
                     WHERE challenge_id=?""",(challenge_id,)).fetchone()
    return dict(r) if r else None

def maybe_assign_canary(con,root_cause_type,challenge_id):
    st=_ensure_state(con,root_cause_type)
    existing=_assignment(con,challenge_id)
    if existing: return existing
    if st["mode"]!="CANARY":
        return None
    if st["canary_assigned_count"]>=st["canary_max_assignments"]:
        return None
    number=st["canary_assigned_count"]+1
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_policy_canary_assignments(
      root_cause_type,challenge_id,assignment_number,status,assigned_at)
      VALUES(?,?,?,?,?)""",
      (root_cause_type,challenge_id,number,"ACTIVE",_now()))
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
      SET canary_assigned_count=canary_assigned_count+1,updated_at=?
      WHERE root_cause_type=?""",(_now(),root_cause_type))
    con.commit()
    _event(con,root_cause_type,"CANARY_ASSIGNED","policy-engine",
           {"challenge_id":challenge_id,"assignment_number":number})
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_policy_canary_assignments
                              WHERE policy_canary_assignment_id=?""",(cur.lastrowid,)).fetchone())

def resolve_selection(con,root_cause_type,challenge_id,recommended_steps,
                      deterministic_steps,human_selection=None):
    st=_ensure_state(con,root_cause_type)
    if human_selection:
        return {
            "selected_side":human_selection["selected_side"],
            "steps":human_selection["steps"],
            "policy_mode":st["mode"],"selection_source":"HUMAN_CHALLENGE_DECISION"
        }
    if st["mode"]=="PROMOTED":
        return {
            "selected_side":"RECOMMENDATION","steps":list(recommended_steps),
            "policy_mode":"PROMOTED","selection_source":"PROMOTED_DEFAULT"
        }
    if st["mode"]=="CANARY":
        assignment=maybe_assign_canary(con,root_cause_type,challenge_id)
        if assignment:
            return {
                "selected_side":"RECOMMENDATION","steps":list(recommended_steps),
                "policy_mode":"CANARY","selection_source":"POLICY_CANARY",
                "policy_canary_assignment_id":assignment["policy_canary_assignment_id"]
            }
    # SHADOW_ONLY, ROLLED_BACK, LONG_TERM_SHADOW_ONLY, READY_FOR_PROMOTION,
    # or canary cap reached.
    return {
        "selected_side":"BASELINE","steps":list(deterministic_steps),
        "policy_mode":st["mode"],"selection_source":"DETERMINISTIC_BASELINE"
    }

def _rollback(con,root_cause_type,reason,actor="policy-runtime-guard",trigger_challenge_id=None,verdict=None):
    st=_ensure_state(con,root_cause_type)
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
      SET mode='ROLLED_BACK',rolled_back_at=?,rollback_reason=?,updated_at=?
      WHERE root_cause_type=?""",(_now(),reason,_now(),root_cause_type))
    # Any still active canary assignments are fail-closed.
    con.execute("""UPDATE origin_threshold_recommendation_policy_canary_assignments
      SET status='ROLLED_BACK',completed_at=?,verdict=COALESCE(verdict,'POLICY_ROLLBACK')
      WHERE root_cause_type=? AND status='ACTIVE'""",(_now(),root_cause_type))
    con.commit()
    _event(con,root_cause_type,"ALGORITHM_ROLLBACK",actor,{"reason":reason})
    event_row=con.execute("""SELECT policy_event_id FROM origin_threshold_recommendation_policy_events
      WHERE root_cause_type=? AND event_type='ALGORITHM_ROLLBACK'
      ORDER BY policy_event_id DESC LIMIT 1""",(root_cause_type,)).fetchone()
    from .origin_threshold_recommendation_recovery import open_recovery_case
    from .origin_threshold_recommendation_versioning import (
        version_for_entity,current_version,mark_failed,create_recovery_link,link_entity
    )
    failed_alg=(version_for_entity(con,"CHALLENGE",trigger_challenge_id,"EVALUATED_BY")
                if trigger_challenge_id is not None else None)
    if not failed_alg:
        failed_alg=current_version(con,root_cause_type)
    failed_alg=mark_failed(con,failed_alg["algorithm_version_id"],actor,reason)
    recovery=open_recovery_case(
        con,root_cause_type,reason,trigger_challenge_id=trigger_challenge_id,
        trigger_policy_event_id=event_row["policy_event_id"] if event_row else None,
        verdict=verdict)
    create_recovery_link(con,recovery["policy_recovery_case_id"],
                         failed_alg["algorithm_version_id"])
    link_entity(con,failed_alg["algorithm_version_id"],root_cause_type,
                "RECOVERY_CASE",recovery["policy_recovery_case_id"],"FAILED_IN")
    recovery["failed_algorithm_version_id"]=failed_alg["algorithm_version_id"]
    recovery["failed_algorithm_version_label"]=failed_alg["version_label"]
    state=_ensure_state(con,root_cause_type)
    state["recovery_case"]=recovery
    return state

def observe_runtime_verdict(con,challenge_id,verdict):
    ch=con.execute("""SELECT * FROM origin_threshold_architecture_recommendation_challenges
                      WHERE challenge_id=?""",(challenge_id,)).fetchone()
    if not ch: return None
    root=ch["root_cause_type"]
    st=_ensure_state(con,root)
    assignment=_assignment(con,challenge_id)

    if st["mode"]=="PROMOTED":
        from .origin_threshold_recommendation_fallback_family_memory import (
            observe_runtime as observe_family_generation_runtime,
            evaluate_sustained as evaluate_family_generation_sustained
        )
        family_memory=observe_family_generation_runtime(con,root,challenge_id,verdict)
        if family_memory.get("handled"):
            out=family_memory["outcome"]
            sustained=evaluate_family_generation_sustained(
                con,out["family_generation_outcome_id"])
            family_memory["outcome"]=sustained

    # A restored fallback version gets a bounded verification generation.
    if st["mode"]=="PROMOTED":
        from .origin_threshold_recommendation_fallback_verification import observe as observe_fallback_verification
        fv=observe_fallback_verification(con,root,challenge_id,verdict)
        if fv.get("handled"):
            if fv.get("force_baseline"):
                rolled=_rollback(
                    con,root,
                    f"fallback verification failed on challenge {challenge_id}: {verdict}",
                    trigger_challenge_id=challenge_id,verdict=verdict)
                rolled["fallback_verification"]=fv
                return rolled
            state=_ensure_state(con,root)
            state["fallback_verification"]=fv
            return state

    # Harmful recommendation is a critical algorithm regression for CANARY/PROMOTED.
    if verdict=="RECOMMENDATION_HARMFUL" and st["mode"] in ("CANARY","PROMOTED","READY_FOR_PROMOTION"):
        if assignment and assignment["status"]=="ACTIVE":
            con.execute("""UPDATE origin_threshold_recommendation_policy_canary_assignments
              SET status='HARMFUL',completed_at=?,verdict=?
              WHERE policy_canary_assignment_id=?""",
              (_now(),verdict,assignment["policy_canary_assignment_id"]))
            con.execute("""UPDATE origin_threshold_recommendation_policy_states
              SET canary_harmful_count=canary_harmful_count+1,updated_at=?
              WHERE root_cause_type=?""",(_now(),root))
            con.commit()
        if st["mode"]=="PROMOTED":
            from .origin_threshold_recommendation_supersede_guard import execute_fallback
            fallback=execute_fallback(con,root,challenge_id,verdict)
            if fallback["executed"]:
                state=_ensure_state(con,root)
                state["version_fallback"]=fallback
                return state
            if fallback.get("evaluation",{}).get("architecture_review_required"):
                rolled=_rollback(con,root,
                    f"family circuit breaker forced baseline on challenge {challenge_id}: {verdict}",
                    trigger_challenge_id=challenge_id,verdict=verdict)
                con.execute("""UPDATE origin_threshold_recommendation_policy_states
                  SET mode='LONG_TERM_SHADOW_ONLY',updated_at=? WHERE root_cause_type=?""",
                  (_now(),root))
                con.commit()
                rolled=_ensure_state(con,root)
                rolled["version_fallback"]=fallback
                rolled["architecture_review_required"]=True
                return rolled
        return _rollback(con,root,
                         f"harmful recommendation runtime verdict on challenge {challenge_id}: {verdict}",
                         trigger_challenge_id=challenge_id,verdict=verdict)

    if st["mode"]=="CANARY" and assignment and assignment["status"]=="ACTIVE":
        if verdict=="RECOMMENDATION_HELPFUL":
            status="HELPFUL"; col="canary_helpful_count"
        else:
            status="NEUTRAL"; col="canary_neutral_count"
        con.execute(f"""UPDATE origin_threshold_recommendation_policy_states
          SET {col}={col}+1,updated_at=? WHERE root_cause_type=?""",(_now(),root))
        con.execute("""UPDATE origin_threshold_recommendation_policy_canary_assignments
          SET status=?,completed_at=?,verdict=?
          WHERE policy_canary_assignment_id=?""",
          (status,_now(),verdict,assignment["policy_canary_assignment_id"]))
        con.commit()
        st=_ensure_state(con,root)
        completed=st["canary_helpful_count"]+st["canary_harmful_count"]+st["canary_neutral_count"]
        if (completed>=st["canary_max_assignments"]
            and st["canary_harmful_count"]==0
            and st["canary_helpful_count"]>=min(MIN_CANARY_HELPFUL,st["canary_max_assignments"])):
            con.execute("""UPDATE origin_threshold_recommendation_policy_states
              SET mode='READY_FOR_PROMOTION',updated_at=? WHERE root_cause_type=?""",
              (_now(),root))
            con.commit()
            _event(con,root,"CANARY_READY_FOR_PROMOTION","policy-engine",
                   {"completed":completed,"helpful":st["canary_helpful_count"],
                    "harmful":st["canary_harmful_count"],"neutral":st["canary_neutral_count"]})
    return _ensure_state(con,root)

def final_policy_review(con,root_cause_type,decision,reviewer,reason):
    if decision not in ("PROMOTE","REJECT","HOLD"):
        raise ValueError("invalid final policy decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    st=_ensure_state(con,root_cause_type)
    if decision=="PROMOTE" and st["mode"]!="READY_FOR_PROMOTION":
        raise ValueError("policy canary is not ready for promotion")
    if decision=="PROMOTE":
        from .origin_threshold_recommendation_versioning import (
            version_for_entity,mark_status,current_version
        )
        alg=version_for_entity(con,"POLICY_CANDIDATE",st.get("candidate_id"),"CANDIDATE_FOR") if st.get("candidate_id") else None
        if not alg or alg["status"]=="FAILED":
            alg=current_version(con,root_cause_type)
        from .origin_threshold_recommendation_version_promotion import promotion_ready
        version_gate=promotion_ready(con,alg["algorithm_version_id"])
        if not version_gate["ready"]:
            raise ValueError("version-aware promotion gate and Human version promotion review are required")
        if alg:
            previous=con.execute("""SELECT algorithm_version_id FROM origin_threshold_recommendation_algorithm_versions
              WHERE root_cause_type=? AND status='PROMOTED' AND algorithm_version_id<>?""",
              (root_cause_type,alg["algorithm_version_id"])).fetchall()
            for row in previous:
                mark_status(con,row["algorithm_version_id"],"SUPERSEDED",reviewer,
                            "superseded after version-aware comparative promotion gate")
            mark_status(con,alg["algorithm_version_id"],"PROMOTED",reviewer,
                        "Human final recommendation policy promotion after version gate")
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
          SET mode='PROMOTED',promoted_at=?,rolled_back_at=NULL,rollback_reason=NULL,updated_at=?
          WHERE root_cause_type=?""",(_now(),_now(),root_cause_type))
    elif decision=="REJECT":
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
          SET mode='SHADOW_ONLY',updated_at=? WHERE root_cause_type=?""",(_now(),root_cause_type))
    con.execute("""INSERT INTO origin_threshold_recommendation_policy_reviews(
      root_cause_type,candidate_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?,?)""",
      (root_cause_type,st.get("candidate_id"),decision,reviewer,reason,_now()))
    con.commit()
    _event(con,root_cause_type,"FINAL_POLICY_REVIEW",reviewer,
           {"decision":decision,"reason":reason})
    return _ensure_state(con,root_cause_type)

def manual_rollback(con,root_cause_type,reviewer,reason):
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    return _rollback(con,root_cause_type,reason,reviewer)

def assignments(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_recommendation_policy_canary_assignments"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY policy_canary_assignment_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "states":states(con),
        "candidates":candidates(con),
        "assignments":assignments(con),
        "events":events(con)
    }
