import json
from .database import (
    backlog_row,adaptive_weight_profile,upsert_adaptive_weight_profile,
    insert_adaptive_weight_observation,adaptive_weight_observations
)

BASE_PROFILES={
    "FIELD_QUALITY":{
        "correction_rate":3.0,"field_coverage_rate":2.0,"known_field_rate":1.5,
        "access_failure_rate":0.5,"source_yield_rate":0.5,"recovery_success_rate":0.5},
    "SOURCE_ACCESS":{
        "access_failure_rate":3.0,"source_yield_rate":2.0,"recovery_success_rate":2.0,
        "correction_rate":0.5,"field_coverage_rate":0.5,"known_field_rate":0.5},
    "RECOVERY":{
        "recovery_success_rate":3.0,"access_failure_rate":2.0,"source_yield_rate":1.5,
        "correction_rate":0.5,"field_coverage_rate":0.5,"known_field_rate":0.5},
    "BALANCED":{
        "correction_rate":1.0,"access_failure_rate":1.0,"field_coverage_rate":1.0,
        "known_field_rate":1.0,"source_yield_rate":1.0,"recovery_success_rate":1.0}
}
VALID_PROFILES=set(BASE_PROFILES)

def infer_goal_profile_from_component(component=None,field_name=None):
    c=(component or "").upper()
    if c.startswith("SOURCE/") or c.startswith("COLLECTOR/"): return "SOURCE_ACCESS"
    if c.startswith("RECOVERY/"): return "RECOVERY"
    if c.startswith("EVIDENCE/") or c.startswith("PARSER/") or field_name: return "FIELD_QUALITY"
    return "BALANCED"

def explicit_or_inferred_profile(con,change_row,backlog=None):
    if backlog and backlog["goal_profile"]:
        return backlog["goal_profile"]
    return infer_goal_profile_from_component(
        change_row["component"], backlog["field_name"] if backlog else None)

def backlog_goal_defaults(*,component=None,field_name=None):
    p=infer_goal_profile_from_component(component,field_name)
    return p,dict(BASE_PROFILES[p])

def record_verdict_observations(con,*,change_id,goal_profile,verdict_result):
    comparable=verdict_result.get("comparable_metric_count",0) or 0
    strength=0.5 if comparable<3 else (1.0 if comparable>=5 else 0.75)
    for group,sign in (("improved_metrics",1.0),("regressed_metrics",-1.0)):
        for row in verdict_result.get(group) or []:
            insert_adaptive_weight_observation(
                con,goal_profile=goal_profile,metric_name=row["metric"],change_id=change_id,
                verdict=verdict_result.get("verdict"),delta=row.get("delta"),
                direction_score=sign,evidence_strength=strength)

def recompute_adaptive_profile(con,goal_profile):
    if goal_profile not in VALID_PROFILES:
        raise ValueError("invalid goal profile")
    base=dict(BASE_PROFILES[goal_profile])
    obs=adaptive_weight_observations(con,goal_profile)
    by_metric={k:[] for k in base}
    for r in obs:
        if r["metric_name"] in by_metric and r["direction_score"] is not None:
            by_metric[r["metric_name"]].append(
                float(r["direction_score"])*float(r["evidence_strength"] or 1.0))
    adaptive={}
    for metric,bw in base.items():
        vals=by_metric[metric]
        if not vals:
            adaptive[metric]=bw
            continue
        avg=sum(vals)/len(vals)
        factor=1.0+max(-0.25,min(0.25,0.05*avg*min(len(vals),5)))
        adaptive[metric]=round(bw*factor,4)
    upsert_adaptive_weight_profile(
        con,goal_profile=goal_profile,base_weights=base,
        adaptive_weights=adaptive,sample_count=len(obs))
    return {"goal_profile":goal_profile,"base_weights":base,
            "adaptive_weights":adaptive,"sample_count":len(obs),
            "mode":"FOUNDATION_CONSERVATIVE","max_adjustment_pct":25}

def get_effective_weights(con,goal_profile):
    row=adaptive_weight_profile(con,goal_profile)
    if not row:
        return dict(BASE_PROFILES[goal_profile]),"BASE"
    if row["sample_count"]<10:
        return dict(BASE_PROFILES[goal_profile]),"BASE_UNTIL_10_SAMPLES"
    return json.loads(row["adaptive_weights_json"]),"ADAPTIVE"

def profile_status(con,goal_profile):
    row=adaptive_weight_profile(con,goal_profile)
    if not row:
        return {"goal_profile":goal_profile,"base_weights":BASE_PROFILES[goal_profile],
                "adaptive_weights":BASE_PROFILES[goal_profile],"sample_count":0,
                "effective_mode":"BASE"}
    return {"goal_profile":goal_profile,
            "base_weights":json.loads(row["base_weights_json"]),
            "adaptive_weights":json.loads(row["adaptive_weights_json"]),
            "sample_count":row["sample_count"],
            "effective_mode":"ADAPTIVE" if row["sample_count"]>=10 else "BASE_UNTIL_10_SAMPLES",
            "last_recomputed_at":row["last_recomputed_at"]}


def get_base_weights(goal_profile):
    if goal_profile not in VALID_PROFILES:
        raise ValueError("invalid goal profile")
    return dict(BASE_PROFILES[goal_profile])

def get_shadow_weights(con, goal_profile):
    """Return latest adaptive suggestion for shadow evaluation only.
    Never changes the production/base verdict."""
    row=adaptive_weight_profile(con,goal_profile)
    if not row:
        return dict(BASE_PROFILES[goal_profile]),0,"BASE_NO_ADAPTIVE_DATA"
    return json.loads(row["adaptive_weights_json"]),int(row["sample_count"] or 0),"ADAPTIVE_SHADOW"
