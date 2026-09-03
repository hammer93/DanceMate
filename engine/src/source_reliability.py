import json
from .database import (
    root_cause_attribution_rows, decision_evidence_cluster_row,
    persist_source_reliability_observation, source_reliability_observation_rows,
    upsert_source_reliability_profile, source_reliability_profile_row,
    source_reliability_profile_rows, persist_preventive_verification_decision,
    preventive_verification_decision_rows, create_preventive_policy_canary,
    active_preventive_policy_canary, consume_preventive_policy_canary,
    rollback_preventive_policy_canary, preventive_policy_canary_rows,
    preventive_policy_canary_event_rows, active_preventive_full_promotion
)

POLICY_VERSION="v0.41"
CRITICAL_PENALTY=0.20
SUCCESS_RECOVERY=0.025
TRUSTED_THRESHOLD=0.90
WATCH_THRESHOLD=0.70
MIN_SHADOW_DECISIONS_FOR_CANARY=3

def _decode(rows, json_fields=("reasons_json","rationale_json","metadata_json","detail_json")):
    out=[]
    for r in rows:
        x=dict(r)
        for f in json_fields:
            if f in x and x.get(f):
                try: x[f]=json.loads(x[f])
                except Exception: pass
        out.append(x)
    return out

def _band(score):
    if score>=TRUSTED_THRESHOLD:
        return "TRUSTED"
    if score>=WATCH_THRESHOLD:
        return "WATCH"
    return "DEGRADED"

def derive_critical_reliability_observations(con):
    created=[]
    skipped=[]
    for a in root_cause_attribution_rows(con):
        if a["status"]!="CONFIRMED_ATTRIBUTION":
            continue
        cluster=decision_evidence_cluster_row(con,a["cluster_id"])
        if not cluster or cluster["severity"]!="CRITICAL" or cluster["status"]!="CONFIRMED_CASE":
            continue
        if not a["source_id"] or not a["rule_key"]:
            skipped.append({
                "attribution_id":a["attribution_id"],
                "reason":"source_or_rule_not_attributable"})
            continue
        oid,is_new=persist_source_reliability_observation(
            con,observation_key=f"ROOT_CAUSE:{a['attribution_id']}",
            source_id=a["source_id"],rule_key=a["rule_key"],
            outcome="CRITICAL_FAILURE",severity="CRITICAL",weight=1.0,
            cluster_id=a["cluster_id"],attribution_id=a["attribution_id"],
            rationale=[
                f"Confirmed critical cluster #{a['cluster_id']}",
                f"Root cause {a['category']} / {a['component']}",
                "Reliability feedback is internal and affects only future verification policy"
            ])
        if is_new:
            created.append(oid)
    return {"created_count":len(created),"created_observation_ids":created,
            "skipped":skipped}

def record_success(con, *, source_id,rule_key,observation_key,
                   weight=1.0,rationale=None,evidence_id=None):
    if not source_id or not rule_key or not observation_key:
        raise ValueError("source_id, rule_key, observation_key are required")
    oid,is_new=persist_source_reliability_observation(
        con,observation_key=f"SUCCESS:{observation_key}",
        source_id=source_id,rule_key=rule_key,outcome="SUCCESS",
        severity="NORMAL",weight=float(weight),evidence_id=evidence_id,
        rationale=rationale or ["Confirmed successful verification outcome"])
    recompute_profile(con,source_id,rule_key)
    return {"reliability_observation_id":oid,"created":is_new,
            "source_id":source_id,"rule_key":rule_key}

def recompute_profile(con,source_id,rule_key):
    rows=list(source_reliability_observation_rows(con,source_id,rule_key))
    failures=[r for r in rows if r["outcome"]=="CRITICAL_FAILURE"]
    successes=[r for r in rows if r["outcome"]=="SUCCESS"]

    penalty=sum(float(r["weight"])*CRITICAL_PENALTY for r in failures)
    recovery=sum(float(r["weight"])*SUCCESS_RECOVERY for r in successes)
    score=max(0.20,min(1.0,1.0-penalty+recovery))

    consecutive=0
    for r in reversed(rows):
        if r["outcome"]=="SUCCESS":
            consecutive+=1
        else:
            break

    last_critical=max((r["observed_at"] for r in failures),default=None)
    last_success=max((r["observed_at"] for r in successes),default=None)
    reasons=[
        f"Base score 1.00 - critical penalty {penalty:.3f} + success recovery {recovery:.3f}",
        f"Critical failures={len(failures)}, successes={len(successes)}",
        "Existing VERIFIED events are never retroactively downgraded by this profile"
    ]
    return upsert_source_reliability_profile(
        con,source_id=source_id,rule_key=rule_key,score=score,band=_band(score),
        critical_failure_count=len(failures),success_count=len(successes),
        observation_count=len(rows),consecutive_success_count=consecutive,
        last_critical_at=last_critical,last_success_at=last_success,
        reasons=reasons)

def recompute_all_profiles(con):
    derive=derive_critical_reliability_observations(con)
    keys={(r["source_id"],r["rule_key"]) for r in source_reliability_observation_rows(con)}
    profiles=[]
    for source_id,rule_key in sorted(keys):
        profiles.append(dict(recompute_profile(con,source_id,rule_key)))
    return {"policy_version":POLICY_VERSION,"derived":derive,
            "profile_count":len(profiles),"profiles":profiles}

def reliability_profiles(con,source_id=None):
    return _decode(source_reliability_profile_rows(con,source_id))

def reliability_observations(con,source_id=None,rule_key=None):
    return _decode(source_reliability_observation_rows(con,source_id,rule_key))

def _profile_or_default(con,source_id,rule_key):
    row=source_reliability_profile_row(con,source_id,rule_key)
    if row:
        return row
    return {
        "source_id":source_id,"rule_key":rule_key,"score":1.0,"band":"TRUSTED",
        "critical_failure_count":0,"success_count":0,"observation_count":0,
        "consecutive_success_count":0
    }

def _shadow_action(profile,base_eligible,independent_source_count,human_confirmed,
                   existing_verified):
    if existing_verified:
        return "KEEP_EXISTING_VERIFIED",[
            "Preventive reliability policy never retroactively downgrades an existing VERIFIED event"]
    if not base_eligible:
        return "BASE_NOT_ELIGIBLE",["Base verification gate is not eligible"]
    band=profile["band"]
    if band=="TRUSTED":
        return "ALLOW_VERIFIED",["Reliability is TRUSTED; no extra preventive requirement"]
    if band=="WATCH":
        if human_confirmed or independent_source_count>=2:
            return "ALLOW_VERIFIED",[
                "WATCH source/rule satisfied corroboration or human confirmation"]
        return "REQUIRE_CORROBORATION",[
            "WATCH source/rule requires >=2 independent sources or human confirmation"]
    # DEGRADED
    if human_confirmed and independent_source_count>=2:
        return "ALLOW_VERIFIED",[
            "DEGRADED source/rule satisfied human confirmation + >=2 independent sources"]
    return "REQUIRE_HUMAN_AND_CORROBORATION",[
        "DEGRADED source/rule requires human confirmation and >=2 independent sources"]

def evaluate_verification_policy(
    con, *, decision_key,event_instance_id,source_id,rule_key,base_eligible,
    independent_source_count=1,human_confirmed=False,existing_verified=False):
    if not source_id or not rule_key:
        raise ValueError("source_id and rule_key are required")
    recompute_profile(con,source_id,rule_key)
    profile=_profile_or_default(con,source_id,rule_key)
    shadow_action,reasons=_shadow_action(
        profile,bool(base_eligible),int(independent_source_count),
        bool(human_confirmed),bool(existing_verified))

    full=active_preventive_full_promotion(con,source_id,rule_key)
    canary=active_preventive_policy_canary(con,source_id,rule_key)
    from .preventive_quarantine import production_override
    quarantine=production_override(
        con,source_id,rule_key,existing_verified=bool(existing_verified))
    from .origin_threshold_scope_isolation import source_production_allowed
    scope_policy=source_production_allowed(con,source_id,rule_key,event_instance_id)
    scope_isolated=not scope_policy["allowed"]
    route_plan=None
    if existing_verified:
        production_action="KEEP_EXISTING_VERIFIED"
        production_mode="NO_RETROACTIVE_CHANGE"
        canary_id=None
    elif scope_policy.get("production_action")=="REINTEGRATION_CANARY":
        production_action="ALLOW_VERIFIED" if base_eligible else "BASE_NOT_ELIGIBLE"
        production_mode="REINTEGRATION_CANARY"
        canary_id=scope_policy.get("reintegration_canary_id")
        reasons.append(
            f"scoped reintegration canary #{canary_id} assigned this Event")
    elif scope_isolated:
        from .alternative_source_routing import plan_alternative_route
        route_plan=plan_alternative_route(
            con,event_instance_id=event_instance_id,
            quarantined_source_id=source_id,rule_key=rule_key) if event_instance_id is not None else None
        if route_plan and route_plan["route_status"] in ("ROUTED_VERIFIED","ROUTED_POSSIBLE"):
            production_action=route_plan["production_recommendation"]
            production_mode="SCOPE_ISOLATED_ALTERNATIVE_ROUTE"
            reasons.extend(route_plan["reasons"])
        else:
            production_action="BASE_ONLY_SHADOW_RESTRICTED"
            production_mode="SCOPE_ISOLATED_SHADOW"
            if route_plan:
                reasons.extend(route_plan["reasons"])
        canary_id=None
        reasons.append(
            f"long-term restriction scope isolates source from Production; matched scopes={scope_policy['matched_scope_ids']}")
    elif quarantine:
        from .alternative_source_routing import plan_alternative_route
        route_plan=plan_alternative_route(
            con,event_instance_id=event_instance_id,
            quarantined_source_id=source_id,rule_key=rule_key) if event_instance_id is not None else None
        if route_plan and route_plan["route_status"]=="ROUTED_VERIFIED":
            production_action=route_plan["production_recommendation"]
            production_mode="ALTERNATIVE_ROUTE"
            reasons.extend(route_plan["reasons"])
        elif route_plan and route_plan["route_status"]=="ROUTED_POSSIBLE":
            production_action=route_plan["production_recommendation"]
            production_mode="ALTERNATIVE_ROUTE"
            reasons.extend(route_plan["reasons"])
        else:
            production_action=quarantine["production_action"]
            production_mode=quarantine["production_mode"]
            if route_plan:
                reasons.extend(route_plan["reasons"])
        canary_id=None
        reasons.append(quarantine["reason"])
    elif full:
        production_action=shadow_action
        production_mode="FULL_PREVENTIVE"
        canary_id=full["canary_id"]
        reasons.append(f"Human-approved Full Preventive promotion #{full['promotion_id']} is active")
    elif canary:
        production_action=shadow_action
        production_mode="CANARY"
        canary_id=canary["canary_id"]
        reasons.append(f"Human-approved preventive canary #{canary_id} is active")
    else:
        production_action="ALLOW_VERIFIED" if base_eligible else "BASE_NOT_ELIGIBLE"
        production_mode="BASE_WITH_SHADOW"
        canary_id=None
        reasons.append("Preventive policy is shadow-only; production follows Base")

    did,is_new=persist_preventive_verification_decision(
        con,decision_key=decision_key,event_instance_id=event_instance_id,
        source_id=source_id,rule_key=rule_key,base_eligible=base_eligible,
        independent_source_count=independent_source_count,
        human_confirmed=human_confirmed,existing_verified=existing_verified,
        reliability_score=profile["score"],reliability_band=profile["band"],
        shadow_action=shadow_action,production_action=production_action,
        production_mode=production_mode,canary_id=canary_id,reasons=reasons)

    if is_new and canary and production_mode=="CANARY" and not existing_verified:
        consume_preventive_policy_canary(con,canary["canary_id"],did)

    route=None
    if is_new and (quarantine or scope_isolated) and event_instance_id is not None and not existing_verified:
        from .alternative_source_routing import persist_route_plan
        route=persist_route_plan(con,trigger_decision_id=did,plan=route_plan)

    return {
        "decision_id":did,"created":is_new,
        "source_id":source_id,"rule_key":rule_key,
        "reliability_score":profile["score"],"reliability_band":profile["band"],
        "shadow_action":shadow_action,"production_action":production_action,
        "production_mode":production_mode,"canary_id":canary_id,
        "existing_verified":bool(existing_verified),"reasons":reasons,
        "scope_policy":scope_policy,
        "alternative_route":route
    }

def verification_decisions(con,source_id=None):
    return _decode(preventive_verification_decision_rows(con,source_id))

def start_canary(con, *, source_id,rule_key,max_decisions,approved_by):
    from .preventive_recovery import assert_canary_requalification_ready
    assert_canary_requalification_ready(con,source_id,rule_key)
    from .preventive_quarantine import canary_constraint
    reintegration=canary_constraint(con,source_id,rule_key,max_decisions)
    if not approved_by:
        raise ValueError("approved_by is required")
    if int(max_decisions)<1 or int(max_decisions)>20:
        raise ValueError("max_decisions must be 1..20")
    profile=_profile_or_default(con,source_id,rule_key)
    if profile["band"]=="TRUSTED":
        raise ValueError("TRUSTED profile does not need preventive canary")
    shadow_count=con.execute("""SELECT COUNT(*) n
      FROM preventive_verification_decisions
      WHERE source_id=? AND rule_key=?
        AND production_mode IN ('BASE_WITH_SHADOW','QUARANTINE_SHADOW')""",
      (source_id,rule_key)).fetchone()["n"]
    if shadow_count<MIN_SHADOW_DECISIONS_FOR_CANARY:
        raise ValueError(
            f"at least {MIN_SHADOW_DECISIONS_FOR_CANARY} shadow decisions are required before canary")
    cid,created=create_preventive_policy_canary(
        con,source_id=source_id,rule_key=rule_key,
        max_decisions=max_decisions,approved_by=approved_by,
        metadata={"policy_version":POLICY_VERSION,"shadow_decision_count":shadow_count,
                  "profile_band":profile["band"],"profile_score":profile["score"],
                  "reintegration":reintegration["reintegration"],
                  "quarantine_id":reintegration["quarantine_id"]})
    return {"canary_id":cid,"created":created,"source_id":source_id,
            "rule_key":rule_key,"max_decisions":int(max_decisions),
            "approved_by":approved_by,
            "reintegration":reintegration["reintegration"],
            "quarantine_id":reintegration["quarantine_id"]}

def rollback_canary(con, *, canary_id,actor,reason):
    if not actor or not reason:
        raise ValueError("actor and reason are required")
    rollback_preventive_policy_canary(con,canary_id,actor,reason)
    return {"canary_id":canary_id,"status":"ROLLED_BACK","actor":actor,"reason":reason}

def canaries(con):
    return _decode(preventive_policy_canary_rows(con))

def canary_events(con,canary_id=None):
    return _decode(preventive_policy_canary_event_rows(con,canary_id))
