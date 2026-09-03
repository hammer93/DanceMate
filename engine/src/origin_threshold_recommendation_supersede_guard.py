import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"

MIN_FALLBACK_DECISIVE=3
MIN_FALLBACK_PRODUCTION=3
MIN_FALLBACK_HELPFUL=2
MIN_FALLBACK_SURVIVAL_DAYS=30.0

def _now():
    return datetime.now(timezone.utc).isoformat()

def _version(con,version_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
                     WHERE algorithm_version_id=?""",(version_id,)).fetchone()
    return dict(r) if r else None

def _challenge_context(con,challenge_id):
    if challenge_id is None:
        return None
    r=con.execute("""SELECT context_signature FROM origin_threshold_architecture_recommendation_challenges
                     WHERE challenge_id=?""",(challenge_id,)).fetchone()
    return r["context_signature"] if r else None

def _failed_version_for_challenge(con,challenge_id,root_cause_type):
    if challenge_id is not None:
        r=con.execute("""SELECT v.* FROM origin_threshold_recommendation_algorithm_lineage l
          JOIN origin_threshold_recommendation_algorithm_versions v
            ON v.algorithm_version_id=l.algorithm_version_id
          WHERE l.entity_type='CHALLENGE' AND l.entity_id=? AND l.relation_type='EVALUATED_BY'
          ORDER BY l.algorithm_lineage_id DESC LIMIT 1""",(challenge_id,)).fetchone()
        if r:
            return dict(r)
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
      WHERE root_cause_type=? AND status='PROMOTED'
      ORDER BY algorithm_version_id DESC LIMIT 1""",(root_cause_type,)).fetchone()
    return dict(r) if r else None

def _fallback_candidate(con,root_cause_type,failing_version_id):
    # Prefer the most recently superseded predecessor of the failing version.
    failed=_version(con,failing_version_id)
    if failed and failed.get("parent_algorithm_version_id"):
        r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
          WHERE algorithm_version_id=? AND status='SUPERSEDED'""",
          (failed["parent_algorithm_version_id"],)).fetchone()
        if r:
            return dict(r)
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
      WHERE root_cause_type=? AND status='SUPERSEDED' AND algorithm_version_id<>?
      ORDER BY algorithm_version_id DESC LIMIT 1""",
      (root_cause_type,failing_version_id)).fetchone()
    return dict(r) if r else None

def _profile(con,version_id,context_signature):
    if not context_signature:
        return None
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_version_profiles
      WHERE algorithm_version_id=? AND context_signature=?""",
      (version_id,context_signature)).fetchone()
    return dict(r) if r else None

def evaluations(con,failing_algorithm_version_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_supersede_runtime_guard_evaluations"""
    params=()
    if failing_algorithm_version_id is not None:
        sql+=" WHERE failing_algorithm_version_id=?"; params=(failing_algorithm_version_id,)
    sql+=" ORDER BY supersede_runtime_guard_evaluation_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def fallbacks(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_recommendation_version_fallbacks"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY version_fallback_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def events(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_recommendation_supersede_runtime_guard_events"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY supersede_runtime_guard_event_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def _event(con,root,failing,fallback,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_supersede_runtime_guard_events(
      root_cause_type,failing_algorithm_version_id,fallback_algorithm_version_id,
      event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?,?)""",
      (root,failing,fallback,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def evaluate_fallback(con,root_cause_type,trigger_challenge_id,verdict,persist=True):
    failing=_failed_version_for_challenge(con,trigger_challenge_id,root_cause_type)
    context=_challenge_context(con,trigger_challenge_id)
    reasons=[]
    fallback=None
    p=None
    prior_recovery_count=con.execute(
        """SELECT COUNT(*) n FROM origin_threshold_recommendation_policy_recovery_cases
           WHERE root_cause_type=?""",(root_cause_type,)).fetchone()["n"]
    if int(prior_recovery_count)>=2:
        reasons.append("third-or-later rollback cannot use automatic version fallback")
    if verdict!="RECOMMENDATION_HARMFUL":
        reasons.append("fallback guard only activates on RECOMMENDATION_HARMFUL")
    if not failing:
        reasons.append("failing algorithm version could not be resolved")
    elif failing["status"]!="PROMOTED":
        reasons.append(f"failing version must be PROMOTED; have {failing['status']}")
    if failing:
        fallback=_fallback_candidate(con,root_cause_type,failing["algorithm_version_id"])
    if not fallback:
        reasons.append("no SUPERSEDED fallback version is available")
    elif fallback["status"]!="SUPERSEDED":
        reasons.append(f"fallback candidate status must be SUPERSEDED; have {fallback['status']}")
    if fallback:
        from .origin_threshold_recommendation_fallback_verification import automatic_fallback_allowed
        pair_check=automatic_fallback_allowed(
            con,failing["algorithm_version_id"],fallback["algorithm_version_id"])
        if not pair_check["allowed"]:
            reasons.append("anti-ping-pong guard: "+pair_check["reason"])
        from .origin_threshold_recommendation_fallback_family import automatic_fallback_allowed as family_fallback_allowed
        family_check=family_fallback_allowed(
            con,root_cause_type,failing["algorithm_version_id"],fallback["algorithm_version_id"])
        if not family_check["allowed"]:
            reasons.append("family circuit breaker: "+family_check["reason"])
        p=_profile(con,fallback["algorithm_version_id"],context)
        if not p:
            reasons.append("fallback version lacks comparable profile in failing context")
        else:
            if int(p["harmful_count"] or 0)>0 or p["safety_band"]!="SAFE":
                reasons.append("fallback version has unsafe/harmful evidence")
            if int(p["decisive_runtime_count"] or 0)<MIN_FALLBACK_DECISIVE:
                reasons.append(f"fallback decisive {p['decisive_runtime_count']}/{MIN_FALLBACK_DECISIVE}")
            if int(p["production_runtime_count"] or 0)<MIN_FALLBACK_PRODUCTION:
                reasons.append(f"fallback production {p['production_runtime_count']}/{MIN_FALLBACK_PRODUCTION}")
            if int(p["helpful_count"] or 0)<MIN_FALLBACK_HELPFUL:
                reasons.append(f"fallback helpful {p['helpful_count']}/{MIN_FALLBACK_HELPFUL}")
            if float(p["median_survival_days"] or 0.0)<MIN_FALLBACK_SURVIVAL_DAYS:
                reasons.append(
                    f"fallback median survival {float(p['median_survival_days'] or 0.0):.1f} < {MIN_FALLBACK_SURVIVAL_DAYS:.1f}")
            if p["promotion_memory_status"] not in ("VERSION_PRODUCTION_PROVEN","VERSION_CANARY_PROVEN"):
                reasons.append(
                    f"fallback promotion memory is not proven; have {p['promotion_memory_status']}")
    safe=not reasons
    status="READY_FOR_AUTOMATIC_VERSION_FALLBACK" if safe else "FALLBACK_BLOCKED"
    action="FALLBACK_TO_SUPERSEDED_VERSION" if safe else "DETERMINISTIC_BASELINE_ROLLBACK"
    result={
        "policy_version":POLICY_VERSION,
        "root_cause_type":root_cause_type,
        "failing_algorithm_version_id":failing["algorithm_version_id"] if failing else None,
        "failing_algorithm_version_label":failing["version_label"] if failing else None,
        "fallback_algorithm_version_id":fallback["algorithm_version_id"] if fallback else None,
        "fallback_algorithm_version_label":fallback["version_label"] if fallback else None,
        "context_signature":context,
        "failing_verdict":verdict,
        "fallback_decisive_count":int(p["decisive_runtime_count"] or 0) if p else 0,
        "fallback_production_count":int(p["production_runtime_count"] or 0) if p else 0,
        "fallback_helpful_count":int(p["helpful_count"] or 0) if p else 0,
        "fallback_harmful_count":int(p["harmful_count"] or 0) if p else 0,
        "fallback_median_survival_days":p["median_survival_days"] if p else None,
        "fallback_safety_band":p["safety_band"] if p else None,
        "fallback_memory_status":p["promotion_memory_status"] if p else None,
        "status":status,"action":action,"reasons":reasons,
        "architecture_review_required":bool(
            fallback and 'family_check' in locals()
            and family_check.get("profile",{}).get("architecture_review_required"))
    }
    if persist and failing:
        cur=con.execute("""INSERT INTO origin_threshold_recommendation_supersede_runtime_guard_evaluations(
          failing_algorithm_version_id,root_cause_type,context_signature,
          fallback_algorithm_version_id,failing_verdict,fallback_decisive_count,
          fallback_production_count,fallback_helpful_count,fallback_harmful_count,
          fallback_median_survival_days,fallback_safety_band,fallback_memory_status,
          status,action,reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (failing["algorithm_version_id"],root_cause_type,context,
           fallback["algorithm_version_id"] if fallback else None,verdict,
           result["fallback_decisive_count"],result["fallback_production_count"],
           result["fallback_helpful_count"],result["fallback_harmful_count"],
           result["fallback_median_survival_days"],result["fallback_safety_band"],
           result["fallback_memory_status"],status,action,
           json.dumps(reasons,ensure_ascii=False),_now()))
        result["supersede_runtime_guard_evaluation_id"]=cur.lastrowid
        con.commit()
    return result

def execute_fallback(con,root_cause_type,trigger_challenge_id,verdict,
                     actor="supersede-runtime-guard"):
    ev=evaluate_fallback(con,root_cause_type,trigger_challenge_id,verdict,persist=True)
    if ev["status"]!="READY_FOR_AUTOMATIC_VERSION_FALLBACK":
        if ev.get("failing_algorithm_version_id"):
            _event(con,root_cause_type,ev["failing_algorithm_version_id"],
                   ev.get("fallback_algorithm_version_id"),
                   "VERSION_FALLBACK_BLOCKED",actor,
                   {"reasons":ev["reasons"],"action":ev["action"]})
        return {"executed":False,"evaluation":ev}

    failing_id=ev["failing_algorithm_version_id"]
    fallback_id=ev["fallback_algorithm_version_id"]

    from .origin_threshold_recommendation_versioning import (
        mark_status,create_recovery_link,link_entity
    )
    from .origin_threshold_recommendation_recovery import open_recovery_case

    mark_status(con,failing_id,"FAILED",actor,
                f"post-supersede runtime regression: {verdict}")
    mark_status(con,fallback_id,"PROMOTED",actor,
                "automatic fallback to last proven safe superseded version")
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
      SET mode='PROMOTED',rolled_back_at=NULL,rollback_reason=NULL,updated_at=?
      WHERE root_cause_type=?""",(_now(),root_cause_type))
    con.commit()

    recovery=open_recovery_case(
        con,root_cause_type,
        f"superseded version regression; automatic fallback from {failing_id} to {fallback_id}",
        trigger_challenge_id=trigger_challenge_id,verdict=verdict)
    create_recovery_link(con,recovery["policy_recovery_case_id"],failing_id)
    link_entity(con,failing_id,root_cause_type,
                "RECOVERY_CASE",recovery["policy_recovery_case_id"],"FAILED_IN")

    cur=con.execute("""INSERT INTO origin_threshold_recommendation_version_fallbacks(
      root_cause_type,failing_algorithm_version_id,fallback_algorithm_version_id,
      trigger_challenge_id,guard_evaluation_id,action,status,recovery_case_id,
      reason,executed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (root_cause_type,failing_id,fallback_id,trigger_challenge_id,
       ev["supersede_runtime_guard_evaluation_id"],ev["action"],"EXECUTED",
       recovery["policy_recovery_case_id"],
       "fallback version satisfied stable production evidence gate",_now()))
    con.commit()
    version_fallback_id=cur.lastrowid
    from .origin_threshold_recommendation_fallback_family import record_fallback
    family_profile=record_fallback(con,root_cause_type,failing_id,fallback_id)
    from .origin_threshold_recommendation_fallback_verification import open_generation
    verification=open_generation(
        con,version_fallback_id,root_cause_type,failing_id,fallback_id)
    _event(con,root_cause_type,failing_id,fallback_id,
           "AUTOMATIC_VERSION_FALLBACK",actor,
           {"version_fallback_id":version_fallback_id,
            "recovery_case_id":recovery["policy_recovery_case_id"],
            "context_signature":ev["context_signature"],
            "fallback_verification_generation_id":
                verification["fallback_verification_generation_id"]})
    return {
        "executed":True,
        "evaluation":ev,
        "version_fallback_id":version_fallback_id,
        "fallback_verification_generation_id":
            verification["fallback_verification_generation_id"],
        "recovery_case_id":recovery["policy_recovery_case_id"],
        "policy_mode":"PROMOTED",
        "fallback_family_profile":family_profile,
    }

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "evaluations":evaluations(con),
        "fallbacks":fallbacks(con),
        "events":events(con),
    }
