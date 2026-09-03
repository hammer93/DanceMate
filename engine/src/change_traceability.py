import json
from .database import (
    create_improvement_change,link_change_daily_run,persist_change_metric_effect,
    change_row,change_links,change_effect_rows,backlog_row,daily_metric_snapshot,
    persist_change_effect_verdict,latest_change_effect_verdict,change_effect_verdict_rows,
    persist_adaptive_shadow_verdict,adaptive_shadow_rows,latest_adaptive_shadow,
    adaptive_shadow_agreement_stats,adaptive_shadow_for_pair,
    active_promotion_lease,promotion_lease_for_change,consume_promotion_lease_change,
    rollback_promotion_lease,persist_promotion_lease_event,active_full_promotion,
    rollback_full_promotion
)

def _ratio(n,d):
    return round(n/d,4) if d else None

def _latest_baseline_daily_run(con):
    row=con.execute("""SELECT dms.daily_run_id,dms.run_date,dms.snapshot_id
                       FROM daily_metric_snapshots dms
                       JOIN daily_runs dr ON dr.daily_run_id=dms.daily_run_id
                       WHERE dr.status='PASS'
                       ORDER BY dms.snapshot_id DESC LIMIT 1""").fetchone()
    return dict(row) if row else None

def register_change(con, *, backlog_id=None, title, description=None, component=None,
                    version_label=None, actor="operator", metadata=None, auto_baseline=True):
    if backlog_id is not None and not backlog_row(con,backlog_id):
        raise KeyError("backlog not found")
    cid,cuuid=create_improvement_change(
        con,backlog_id=backlog_id,title=title,description=description,
        component=component,version_label=version_label,actor=actor,metadata=metadata
    )
    baseline=None
    if auto_baseline:
        baseline=_latest_baseline_daily_run(con)
        if baseline:
            link_and_measure_change(con,change_id=cid,daily_run_id=baseline["daily_run_id"],
                                    relation="BASELINE")
    return {"change_id":cid,"change_uuid":cuuid,"auto_baseline":baseline}

def _daily_metrics(con,daily_run_id,source_id=None,field_name=None):
    snap=daily_metric_snapshot(con,daily_run_id)
    if not snap:
        raise KeyError("daily metric snapshot not found")
    payload=json.loads(snap["payload_json"])
    source_ops=payload.get("source_operations",[])
    source_row=next((x for x in source_ops if x.get("source_id")==source_id),None) if source_id else None
    fc=payload.get("field_confidence_distribution",{})
    total=sum(fc.values()); verified=fc.get("VERIFIED",0)
    known=verified+fc.get("EXPECTED",0)+fc.get("INFERRED",0)
    human=payload.get("human_in_loop_metrics",{})
    hotspots=(payload.get("correction_hotspots") or {}).get("source_field_hotspots",[])
    hotspot=next((x for x in hotspots if x.get("source_id")==source_id and x.get("field")==field_name),None)
    return {
      "correction_rate":hotspot.get("correction_rate") if hotspot else human.get("manual_correction_rate"),
      "access_failure_rate":source_row.get("access_failure_rate") if source_row else None,
      "field_coverage_rate":_ratio(verified,total),
      "known_field_rate":_ratio(known,total),
      "source_yield_rate":source_row.get("source_yield_rate") if source_row else None,
      "recovery_success_rate":source_row.get("recovery_success_rate") if source_row else None,
      "snapshot_id":snap["snapshot_id"],"immutable_hash":snap["immutable_hash"]
    }

def link_and_measure_change(con, *, change_id, daily_run_id, relation="POST_CHANGE",
                            baseline_daily_run_id=None):
    ch=change_row(con,change_id)
    if not ch:
        raise KeyError("change not found")

    source_id=None
    field_name=None
    if ch["backlog_id"]:
        b=backlog_row(con,ch["backlog_id"])
        if b:
            source_id=b["source_id"]
            field_name=b["field_name"]

    link_change_daily_run(con,change_id=change_id,daily_run_id=daily_run_id,relation=relation)
    metrics=_daily_metrics(con,daily_run_id,source_id=source_id,field_name=field_name)
    eid=persist_change_metric_effect(
        con,change_id=change_id,daily_run_id=daily_run_id,metrics=metrics,
        baseline_daily_run_id=baseline_daily_run_id,
        metadata={"source_id":source_id,"field_name":field_name,"relation":relation}
    )
    return {"effect_id":eid,"metrics":metrics}

from .goal_weighting import (
    BASE_PROFILES,explicit_or_inferred_profile,get_base_weights,get_shadow_weights,
    record_verdict_observations,recompute_adaptive_profile
)
from .shadow_safety_gate import evaluate_shadow_safety,shadow_safety_status
from .rolling_shadow_stability import evaluate_rolling_shadow_stability,rolling_shadow_status
from .post_promotion_guard import evaluate_post_promotion_guard

GOAL_PROFILES=BASE_PROFILES

def infer_goal_profile(con,change_id):
    ch=change_row(con,change_id)
    if not ch: raise KeyError("change not found")
    b=backlog_row(con,ch["backlog_id"]) if ch["backlog_id"] else None
    return explicit_or_inferred_profile(con,ch,b)

def metric_weights_for_change(con,change_id):
    """Production verdict always uses explicit/base goal weights in v0.30."""
    profile=infer_goal_profile(con,change_id)
    return profile,get_base_weights(profile)

LOWER_IS_BETTER={"correction_rate","access_failure_rate"}
HIGHER_IS_BETTER={"field_coverage_rate","known_field_rate","source_yield_rate","recovery_success_rate"}
MATERIAL_EPSILON=0.01

def _effect_by_relation(con,change_id,relation):
    return con.execute("""SELECT e.*,l.relation
                          FROM improvement_changes_metric_effects e
                          JOIN change_daily_run_links l
                            ON l.change_id=e.change_id AND l.daily_run_id=e.daily_run_id
                          WHERE e.change_id=? AND l.relation=?
                          ORDER BY e.effect_id DESC LIMIT 1""",(change_id,relation)).fetchone()

def _compute_weighted_verdict(baseline,post,weights):
    improved=[]; regressed=[]; unchanged=[]
    metrics=["correction_rate","access_failure_rate","field_coverage_rate",
             "known_field_rate","source_yield_rate","recovery_success_rate"]
    weighted_gain=0.0; weighted_loss=0.0

    for name in metrics:
        b=baseline[name]; a=post[name]
        if b is None or a is None:
            continue
        delta=round(a-b,4)
        row={"metric":name,"before":b,"after":a,"delta":delta,
             "weight":weights.get(name,1.0)}
        if abs(delta)<MATERIAL_EPSILON:
            unchanged.append(row)
            continue
        better=(delta<0) if name in LOWER_IS_BETTER else (delta>0)
        impact=round(abs(delta)*weights.get(name,1.0),4)
        row["weighted_impact"]=impact
        if better:
            improved.append(row); weighted_gain+=impact
        else:
            regressed.append(row); weighted_loss+=impact

    comparable=len(improved)+len(regressed)+len(unchanged)
    directional=len(improved)+len(regressed)
    raw_score=round((len(improved)-len(regressed))/directional,4) if directional else 0.0
    denom=weighted_gain+weighted_loss
    weighted_score=round((weighted_gain-weighted_loss)/denom,4) if denom else 0.0
    reasons=[]

    if comparable<2:
        verdict="INCONCLUSIVE"; reasons.append("Comparable metrics fewer than 2")
    elif directional==0:
        verdict="INCONCLUSIVE"; reasons.append("No material metric movement")
    elif weighted_score>=0.25:
        verdict="IMPROVED"; reasons.append(f"Goal-aware weighted score {weighted_score} favors improvement")
    elif weighted_score<=-0.25:
        verdict="REGRESSED"; reasons.append(f"Goal-aware weighted score {weighted_score} favors regression")
    else:
        verdict="INCONCLUSIVE"; reasons.append(f"Goal-aware weighted score {weighted_score} is mixed")

    primary=max(weights,key=weights.get)
    if verdict=="IMPROVED" and any(x["metric"]==primary for x in regressed):
        verdict="INCONCLUSIVE"
        reasons.append(f"Primary goal metric {primary} regressed; improvement claim blocked")

    return {
        "verdict":verdict,"score":raw_score,"weighted_score":weighted_score,
        "comparable_metric_count":comparable,
        "improved_metrics":improved,"regressed_metrics":regressed,
        "unchanged_metrics":unchanged,"reasons":reasons
    }

def evaluate_change_effect(con,change_id):
    baseline=_effect_by_relation(con,change_id,"BASELINE")
    post=_effect_by_relation(con,change_id,"POST_CHANGE")
    goal_profile,base_weights=metric_weights_for_change(con,change_id)

    if not baseline or not post:
        reasons=[]
        if not baseline: reasons.append("BASELINE immutable snapshot/effect missing")
        if not post: reasons.append("POST_CHANGE immutable snapshot/effect missing")
        vid=persist_change_effect_verdict(
            con,change_id=change_id,
            baseline_daily_run_id=baseline["daily_run_id"] if baseline else None,
            post_daily_run_id=post["daily_run_id"] if post else None,
            verdict="INCONCLUSIVE",comparable_metric_count=0,improved_metric_count=0,
            regressed_metric_count=0,unchanged_metric_count=0,score=0.0,weighted_score=0.0,
            goal_profile=goal_profile,metric_weights=base_weights,improved_metrics=[],
            regressed_metrics=[],unchanged_metrics=[],reasons=reasons)
        return {"verdict_id":vid,"verdict":"INCONCLUSIVE","reasons":reasons,
                "goal_profile":goal_profile,"metric_weights":base_weights,
                "weighted_score":0.0,"shadow":None,"production_mode":"BASE",
                "baseline_daily_run_id":baseline["daily_run_id"] if baseline else None,
                "post_daily_run_id":post["daily_run_id"] if post else None}

    # Base is the safety/reference verdict. Shadow is the latest adaptive suggestion.
    shadow_weights,shadow_samples,shadow_mode=get_shadow_weights(con,goal_profile)
    base_result=_compute_weighted_verdict(baseline,post,base_weights)
    shadow_result=_compute_weighted_verdict(baseline,post,shadow_weights)

    # A previously consumed canary lease wins for idempotent re-evaluation of this Change,
    # even if that lease has since EXHAUSTED/ROLLED_BACK.
    historical_lease=promotion_lease_for_change(con,change_id)
    lease=historical_lease or active_promotion_lease(con,goal_profile)
    full_promotion=active_full_promotion(con,goal_profile)
    production_result=base_result
    production_weights=base_weights
    production_mode="BASE"
    canary=None
    full=None

    if full_promotion and not historical_lease:
        full_weights=json.loads(full_promotion["adaptive_weights_json"])
        full_result=_compute_weighted_verdict(baseline,post,full_weights)
        production_result=full_result
        production_weights=full_weights
        production_mode="FULL_ADAPTIVE"
        full={
            "promotion_id":full_promotion["promotion_id"],
            "lease_id":full_promotion["lease_id"],
            "verdict":full_result["verdict"],
            "weighted_score":full_result["weighted_score"],
            "metric_weights":full_weights,
            "safety_guard_triggered":False
        }
    elif lease and lease["goal_profile"]==goal_profile:
        lease_weights=json.loads(lease["adaptive_weights_json"])
        canary_result=_compute_weighted_verdict(baseline,post,lease_weights)
        production_result=canary_result
        production_weights=lease_weights
        production_mode="CANARY_REPLAY" if historical_lease else "CANARY_ADAPTIVE"
        canary={
            "lease_id":lease["lease_id"],
            "candidate_id":lease["candidate_id"],
            "verdict":canary_result["verdict"],
            "weighted_score":canary_result["weighted_score"],
            "metric_weights":lease_weights,
            "status_before":lease["status"],
            "safety_guard_triggered":False
        }

    vid=persist_change_effect_verdict(
        con,change_id=change_id,baseline_daily_run_id=baseline["daily_run_id"],
        post_daily_run_id=post["daily_run_id"],verdict=production_result["verdict"],
        comparable_metric_count=production_result["comparable_metric_count"],
        improved_metric_count=len(production_result["improved_metrics"]),
        regressed_metric_count=len(production_result["regressed_metrics"]),
        unchanged_metric_count=len(production_result["unchanged_metrics"]),
        score=production_result["score"],weighted_score=production_result["weighted_score"],
        goal_profile=goal_profile,metric_weights=production_weights,
        improved_metrics=production_result["improved_metrics"],
        regressed_metrics=production_result["regressed_metrics"],
        unchanged_metrics=production_result["unchanged_metrics"],
        reasons=production_result["reasons"]+[f"Production mode: {production_mode}"])

    agrees=(base_result["verdict"]==shadow_result["verdict"])
    shadow_reasons=list(shadow_result["reasons"])
    shadow_reasons.append(f"Shadow mode: {shadow_mode}")
    existing_shadow=adaptive_shadow_for_pair(
        con,change_id,baseline["daily_run_id"],post["daily_run_id"])
    sid=(existing_shadow["shadow_id"] if existing_shadow else persist_adaptive_shadow_verdict(
        con,change_id=change_id,
        baseline_daily_run_id=baseline["daily_run_id"],
        post_daily_run_id=post["daily_run_id"],
        goal_profile=goal_profile,
        base_verdict=base_result["verdict"],
        shadow_verdict=shadow_result["verdict"],
        base_weighted_score=base_result["weighted_score"],
        shadow_weighted_score=shadow_result["weighted_score"],
        agrees=agrees,adaptive_sample_count=shadow_samples,
        base_weights=base_weights,shadow_weights=shadow_weights,
        reasons=shadow_reasons))

    # First execution under an ACTIVE lease consumes one canary slot.
    if canary and not historical_lease:
        lease_status,used=consume_promotion_lease_change(
            con,lease["lease_id"],change_id=change_id,actor="change-effect")
        canary["status_after_use"]=lease_status
        canary["used_canary_changes"]=used
        persist_promotion_lease_event(
            con,lease_id=lease["lease_id"],event_type="CANARY_OUTCOME",
            actor="change-effect",change_id=change_id,
            detail={
                "base_verdict":base_result["verdict"],
                "canary_verdict":production_result["verdict"],
                "base_weighted_score":base_result["weighted_score"],
                "canary_weighted_score":production_result["weighted_score"],
                "diverged":base_result["verdict"]!=production_result["verdict"],
                "false_optimism":(
                    base_result["verdict"]!="IMPROVED" and
                    production_result["verdict"]=="IMPROVED")
            })

        # Hard safety guard: Adaptive canary must never turn a non-improvement reference
        # into an optimistic production IMPROVED.
        if base_result["verdict"]!="IMPROVED" and production_result["verdict"]=="IMPROVED":
            rollback_promotion_lease(
                con,lease["lease_id"],actor="canary-safety-guard",
                reason=f"Unsafe canary optimism: Base={base_result['verdict']} → Canary=IMPROVED")
            persist_promotion_lease_event(
                con,lease_id=lease["lease_id"],event_type="CANARY_SAFETY_BLOCK",
                actor="canary-safety-guard",change_id=change_id,
                detail={
                    "base_verdict":base_result["verdict"],
                    "canary_verdict":production_result["verdict"],
                    "action":"ROLLBACK"
                })
            canary["safety_guard_triggered"]=True
            canary["status_after_guard"]="ROLLED_BACK"

    runtime_guard=None
    if full:
        persist_post_promotion_observation(
            con,promotion_id=full["promotion_id"],change_id=change_id,
            goal_profile=goal_profile,
            base_verdict=base_result["verdict"],
            full_verdict=production_result["verdict"],
            base_weighted_score=base_result["weighted_score"],
            full_weighted_score=production_result["weighted_score"])

    if full and base_result["verdict"]!="IMPROVED" and production_result["verdict"]=="IMPROVED":
        rollback_full_promotion(
            con,goal_profile,actor="full-promotion-safety-guard",
            reason=f"Unsafe full-promotion optimism: Base={base_result['verdict']} → Full=IMPROVED")
        persist_promotion_lease_event(
            con,lease_id=full["lease_id"],event_type="FULL_PROMOTION_SAFETY_BLOCK",
            actor="full-promotion-safety-guard",change_id=change_id,
            detail={
                "base_verdict":base_result["verdict"],
                "full_verdict":production_result["verdict"],
                "action":"ROLLBACK"
            })
        full["safety_guard_triggered"]=True
        full["status_after_guard"]="ROLLED_BACK"

    if full:
        runtime_guard=evaluate_post_promotion_guard(
            con,full["promotion_id"],persist=True,enforce=True)

    # Only after Base + Shadow are frozen do we feed the current outcome into the
    # adaptive foundation for the NEXT Change. Use Base reference to prevent the
    # canary from training itself.
    if not existing_shadow:
        record_verdict_observations(
            con,change_id=change_id,goal_profile=goal_profile,
            verdict_result={
                "verdict":base_result["verdict"],
                "comparable_metric_count":base_result["comparable_metric_count"],
                "improved_metrics":base_result["improved_metrics"],
                "regressed_metrics":base_result["regressed_metrics"]
            })
        adaptive_status=recompute_adaptive_profile(con,goal_profile)
    else:
        adaptive_status={"goal_profile":goal_profile,"mode":"UNCHANGED_EXISTING_SHADOW",
                         "sample_count":shadow_samples}

    agreement=adaptive_shadow_agreement_stats(con,goal_profile)
    safety=(evaluate_shadow_safety(con,goal_profile,persist=True)
            if not existing_shadow else shadow_safety_status(con,goal_profile))
    rolling=(evaluate_rolling_shadow_stability(
                con,goal_profile,persist=True,manage_candidate=True)
             if not existing_shadow else rolling_shadow_status(con,goal_profile))

    return {
        "verdict_id":vid,
        "verdict":production_result["verdict"],
        "score":production_result["score"],
        "weighted_score":production_result["weighted_score"],
        "goal_profile":goal_profile,
        "metric_weights":production_weights,
        "production_mode":production_mode,
        "base_reference":{
            "verdict":base_result["verdict"],
            "weighted_score":base_result["weighted_score"],
            "metric_weights":base_weights,
            "reasons":base_result["reasons"]
        },
        "canary":canary,
        "full_promotion":full,
        "post_promotion_runtime_guard":runtime_guard,
        "comparable_metric_count":production_result["comparable_metric_count"],
        "improved_metrics":production_result["improved_metrics"],
        "regressed_metrics":production_result["regressed_metrics"],
        "unchanged_metrics":production_result["unchanged_metrics"],
        "reasons":production_result["reasons"],
        "baseline_daily_run_id":baseline["daily_run_id"],
        "post_daily_run_id":post["daily_run_id"],
        "shadow":{
            "shadow_id":sid,
            "verdict":shadow_result["verdict"],
            "weighted_score":shadow_result["weighted_score"],
            "metric_weights":shadow_weights,
            "adaptive_sample_count":shadow_samples,
            "mode":shadow_mode,
            "agrees_with_base":agrees,
            "reasons":shadow_reasons
        },
        "shadow_agreement":agreement,
        "shadow_safety":safety,
        "rolling_shadow_stability":rolling,
        "adaptive_weight_status":adaptive_status
    }

def auto_post_change_and_verdict(con,*,change_id,daily_run_id):
    baseline=_effect_by_relation(con,change_id,"BASELINE")
    measurement=link_and_measure_change(
        con,change_id=change_id,daily_run_id=daily_run_id,relation="POST_CHANGE",
        baseline_daily_run_id=baseline["daily_run_id"] if baseline else None)
    return {"measurement":measurement,"verdict":evaluate_change_effect(con,change_id)}

def change_detail(con,change_id):
    ch=change_row(con,change_id)
    if not ch:
        return None
    links=[dict(x) for x in change_links(con,change_id)]
    effects=[dict(x) for x in change_effect_rows(con,change_id)]

    baseline=None
    post=None
    for e in effects:
        if e["baseline_daily_run_id"] is None and baseline is None:
            baseline=e
        post=e

    comparison=None
    if len(effects)>=2:
        before=effects[0]
        after=effects[-1]
        def delta(k):
            a=after[k]; b=before[k]
            return round(a-b,4) if a is not None and b is not None else None
        comparison={
            "before_daily_run_id":before["daily_run_id"],
            "after_daily_run_id":after["daily_run_id"],
            "correction_rate_delta":delta("correction_rate"),
            "access_failure_rate_delta":delta("access_failure_rate"),
            "field_coverage_rate_delta":delta("field_coverage_rate"),
            "known_field_rate_delta":delta("known_field_rate"),
            "source_yield_rate_delta":delta("source_yield_rate"),
            "recovery_success_rate_delta":delta("recovery_success_rate"),
        }

    verdicts=[dict(x) for x in change_effect_verdict_rows(con,change_id)]
    for v in verdicts:
        for k in ("metric_weights_json","improved_metrics_json","regressed_metrics_json","unchanged_metrics_json","reasons_json"):
            if v.get(k):
                try: v[k]=json.loads(v[k])
                except Exception: pass
    lr=latest_change_effect_verdict(con,change_id)
    latest=dict(lr) if lr else None
    if latest:
        for k in ("metric_weights_json","improved_metrics_json","regressed_metrics_json","unchanged_metrics_json","reasons_json"):
            if latest.get(k):
                try: latest[k]=json.loads(latest[k])
                except Exception: pass
    shadows=[dict(x) for x in adaptive_shadow_rows(con,change_id)]
    for s in shadows:
        for k in ("base_weights_json","shadow_weights_json","reasons_json"):
            if s.get(k):
                try: s[k]=json.loads(s[k])
                except Exception: pass
    lsr=latest_adaptive_shadow(con,change_id)
    latest_shadow=dict(lsr) if lsr else None
    if latest_shadow:
        for k in ("base_weights_json","shadow_weights_json","reasons_json"):
            if latest_shadow.get(k):
                try: latest_shadow[k]=json.loads(latest_shadow[k])
                except Exception: pass
    return {"change":dict(ch),"daily_run_links":links,"metric_effects":effects,
            "comparison":comparison,"verdict_history":verdicts,"latest_verdict":latest,
            "shadow_history":shadows,"latest_shadow":latest_shadow,
            "shadow_agreement":adaptive_shadow_agreement_stats(con,infer_goal_profile(con,change_id)),
            "shadow_safety":shadow_safety_status(con,infer_goal_profile(con,change_id)),
            "rolling_shadow_stability":rolling_shadow_status(con,infer_goal_profile(con,change_id))}

def list_changes(con):
    return [dict(x) for x in con.execute("""SELECT ic.*,ibi.source_id,ibi.field_name,
        ibi.priority,ibi.status backlog_status
        FROM improvement_changes ic
        LEFT JOIN improvement_backlog_items ibi ON ibi.backlog_id=ic.backlog_id
        ORDER BY ic.change_id""").fetchall()]
