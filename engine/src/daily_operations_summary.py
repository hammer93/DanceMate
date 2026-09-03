def _ratio(n,d):
    return round(n/d,4) if d else None

def _distribution(rows,key):
    out={}
    for r in rows:
        v=r[key] if r[key] is not None else "UNKNOWN"
        out[v]=out.get(v,0)+1
    return dict(sorted(out.items()))

def _review_state(con,key):
    r=con.execute("SELECT state FROM human_review_state WHERE review_key=?",(key,)).fetchone()
    return r["state"] if r else None

def build_daily_operations_summary(con):
    from .human_review_metrics import calculate_human_review_metrics
    from .correction_hotspot import analyze_correction_hotspots
    from .improvement_backlog import recommend_improvement_backlog
    from .improvement_lifecycle import backlog_list
    from .change_traceability import list_changes
    from .shadow_safety_gate import shadow_safety_status
    from .rolling_shadow_stability import rolling_shadow_status,promotion_candidates
    from .adaptive_promotion import promotion_review_history,promotion_leases,promotion_lease_events
    from .canary_outcome import canary_outcome_history,final_promotion_reviews,full_promotions
    from .post_promotion_guard import post_promotion_guard_history,post_promotion_health
    from .decision_quality import decision_quality_history,goal_relevance_history
    from .decision_outcome_evidence import evidence_list,confirmation_history
    from .evidence_priority_queue import priority_queue,queue_event_history
    from .evidence_cluster_resolution import cluster_list,root_cause_list,closure_history
    from .source_reliability import reliability_profiles,verification_decisions,canaries,canary_events
    from .preventive_policy_outcome import outcomes,safety_history,full_promotions,final_reviews
    from .preventive_full_runtime_guard import guard_history,runtime_observations,guard_events
    from .preventive_recovery import recovery_cases,recovery_evaluations,recovery_events
    from .preventive_recurrence import recurrence_profiles,recurrence_evaluations,recurrence_exceptions
    from .preventive_quarantine import quarantines,quarantine_events,reintegration_evaluations,release_reviews
    from .alternative_source_routing import route_evaluations,continuity_snapshots
    from .source_independence_graph import relationships,fingerprints,independence_history
    from .automated_origin_inference import clusters
    from .origin_confidence_calibration import (
        calibration_history,priority_history
    )
    from .origin_threshold_promotion import (
        candidates as threshold_candidates,
        canaries as threshold_canaries,
        promotions as threshold_promotions,
        runtime_status as threshold_runtime_status
    )
    from .origin_threshold_runtime_guard import (
        runtime_history as threshold_runtime_history,
        evaluation_history as threshold_guard_history,
        recovery_cases as threshold_recovery_cases,
        runtime_guard_status as threshold_guard_status
    )
    from .origin_threshold_recovery_root_cause import (
        root_causes as threshold_root_causes,
        requirements as threshold_adaptive_requirements
    )
    from .origin_threshold_recurrence_guard import (
        profiles as threshold_recurrence_profiles,
        restrictions as threshold_long_term_restrictions,
        remediation_effectiveness_history,
        remediation_type_stats
    )
    from .origin_threshold_scope_isolation import (
        scopes as threshold_restriction_scopes,
        scope_routes as threshold_scope_routes,
        scope_status as threshold_scope_status
    )
    from .origin_threshold_scope_reintegration import (
        evidence as threshold_scope_reintegration_evidence,
        evaluations as threshold_scope_reintegration_evaluations,
        canaries as threshold_scope_reintegration_canaries,
        status as threshold_scope_reintegration_status
    )
    from .origin_threshold_post_reintegration_guard import (
        observations as threshold_post_reintegration_observations,
        evaluations as threshold_post_reintegration_evaluations,
        re_isolations as threshold_post_reintegration_reisolations,
        status as threshold_post_reintegration_status
    )
    from .origin_threshold_post_reintegration_root_cause import (
        root_causes as threshold_post_reintegration_root_causes,
        remediation_routes as threshold_post_reintegration_remediation_routes,
        status as threshold_post_reintegration_root_status
    )
    from .origin_threshold_architecture_escalation import (
        plans as threshold_architecture_plans,
        status as threshold_architecture_status
    )
    from .origin_threshold_architecture_memory import (
        runtime_outcomes as threshold_architecture_runtime_outcomes,
        effectiveness_profiles as threshold_architecture_effectiveness_profiles,
        recommendations as threshold_architecture_recommendations,
        status as threshold_architecture_memory_status
    )
    from .origin_threshold_architecture_ranking import (
        score_history as threshold_architecture_comparative_scores,
        recommendation_history as threshold_architecture_context_recommendations,
        status as threshold_architecture_ranking_status
    )
    from .origin_threshold_recommendation_challenge import (
        challenges as threshold_architecture_recommendation_challenges,
        runtime_results as threshold_architecture_challenge_runtime_results,
        quality_profiles as threshold_architecture_recommendation_quality_profiles,
        status as threshold_architecture_challenge_status
    )
    from .origin_threshold_recommendation_policy import (
        candidates as threshold_recommendation_policy_candidates,
        states as threshold_recommendation_policy_states,
        assignments as threshold_recommendation_policy_assignments,
        events as threshold_recommendation_policy_events,
        status as threshold_recommendation_policy_status
    )
    from .origin_threshold_recommendation_recovery import (
        cases as threshold_recommendation_recovery_cases,
        status as threshold_recommendation_recovery_status
    )
    from .origin_threshold_recommendation_versioning import (
        versions as threshold_recommendation_algorithm_versions,
        lineage as threshold_recommendation_algorithm_lineage,
        recovery_links as threshold_recommendation_recovery_version_links,
        status as threshold_recommendation_algorithm_versioning_status
    )
    from .origin_threshold_recommendation_version_cohort import (
        cohorts as threshold_recommendation_algorithm_version_cohorts,
        profiles as threshold_recommendation_algorithm_version_profiles,
        evaluations as threshold_recommendation_algorithm_version_evaluations,
        status as threshold_recommendation_algorithm_version_cohort_status
    )
    from .origin_threshold_recommendation_version_promotion import (
        gates as threshold_recommendation_version_promotion_gates,
        comparisons as threshold_recommendation_version_supersede_comparisons,
        reviews as threshold_recommendation_version_promotion_reviews,
        events as threshold_recommendation_version_promotion_events,
        status as threshold_recommendation_version_promotion_status
    )
    from .origin_threshold_recommendation_supersede_guard import (
        evaluations as threshold_recommendation_supersede_guard_evaluations,
        fallbacks as threshold_recommendation_version_fallbacks,
        events as threshold_recommendation_supersede_guard_events,
        status as threshold_recommendation_supersede_guard_status
    )
    from .origin_threshold_recommendation_fallback_verification import (
        generations as threshold_recommendation_fallback_verification_generations,
        observations as threshold_recommendation_fallback_verification_observations,
        pair_profiles as threshold_recommendation_fallback_pair_profiles,
        events as threshold_recommendation_fallback_verification_events,
        status as threshold_recommendation_fallback_verification_status
    )
    from .origin_threshold_recommendation_fallback_family import (
        profiles as threshold_recommendation_fallback_family_profiles,
        reviews as threshold_recommendation_fallback_family_reviews,
        events as threshold_recommendation_fallback_family_events,
        status as threshold_recommendation_fallback_family_status
    )
    from .origin_threshold_recommendation_fallback_family_recovery import (
        cases as threshold_recommendation_fallback_family_recovery_cases,
        remediations as threshold_recommendation_fallback_family_recovery_remediations,
        evidence as threshold_recommendation_fallback_family_recovery_evidence,
        evaluations as threshold_recommendation_fallback_family_recovery_evaluations,
        reviews as threshold_recommendation_fallback_family_recovery_reviews,
        events as threshold_recommendation_fallback_family_recovery_events,
        status as threshold_recommendation_fallback_family_recovery_status
    )
    from .origin_threshold_recommendation_fallback_family_memory import (
        outcomes as threshold_recommendation_fallback_family_generation_outcomes,
        effectiveness_profiles as threshold_recommendation_fallback_family_effectiveness_profiles,
        events as threshold_recommendation_fallback_family_generation_events,
        status as threshold_recommendation_fallback_family_memory_status
    )
    from .origin_threshold_recommendation_fallback_family_ranking import (
        rankings as threshold_recommendation_fallback_family_remediation_rankings,
        recommendations as threshold_recommendation_fallback_family_remediation_recommendations,
        selection_reviews as threshold_recommendation_fallback_family_remediation_selection_reviews,
        events as threshold_recommendation_fallback_family_remediation_ranking_events,
        status as threshold_recommendation_fallback_family_ranking_status
    )
    from .origin_threshold_recommendation_fallback_family_recommendation_outcome import (
        outcomes as threshold_recommendation_fallback_family_recommendation_outcomes,
        effectiveness_profiles as threshold_recommendation_fallback_family_recommendation_effectiveness_profiles,
        events as threshold_recommendation_fallback_family_recommendation_outcome_events,
        status as threshold_recommendation_fallback_family_recommendation_outcome_status
    )
    event_conf=_distribution(con.execute("SELECT status FROM event_instances").fetchall(),"status")
    field_conf=_distribution(con.execute("""SELECT confidence FROM event_field_states
                                           WHERE field_name IN ('date','start_time','venue','fee')""").fetchall(),
                             "confidence")

    source_rows=[]
    for s in con.execute("""SELECT source_id,name,platform,authority_level,access_state
                            FROM sources ORDER BY source_id""").fetchall():
        o=con.execute("""SELECT
          COALESCE(SUM(discovered_count),0) discovered,
          COALESCE(SUM(rawpost_new_count),0) raw_new,
          COALESCE(SUM(acquisition_attempt_count),0) aa,
          COALESCE(SUM(acquisition_failure_count),0) af,
          COALESCE(SUM(recovery_attempt_count),0) ra,
          COALESCE(SUM(recovery_success_count),0) rs
          FROM observation_runs WHERE source_id=? AND result_status<>'RUNNING'""",(s["source_id"],)).fetchone()
        source_rows.append({
          "source_id":s["source_id"],"name":s["name"],"platform":s["platform"],
          "authority_level":s["authority_level"],"access_state":s["access_state"],
          "discovered":o["discovered"],"rawpost_new":o["raw_new"],
          "source_yield_rate":_ratio(o["raw_new"],o["discovered"]),
          "acquisition_attempts":o["aa"],"acquisition_failures":o["af"],
          "access_failure_rate":_ratio(o["af"],o["aa"]),
          "recovery_attempts":o["ra"],"recovery_success":o["rs"],
          "recovery_success_rate":_ratio(o["rs"],o["ra"])
        })

    recovery_status={r["state"]:r["n"] for r in con.execute(
        "SELECT state,COUNT(*) n FROM recovery_queue GROUP BY state ORDER BY state").fetchall()}

    review=[]
    for e in con.execute("""SELECT event_instance_id,identity_key,normalized_name,event_date,
                            normalized_venue,status FROM event_instances
                            WHERE status IN ('DISCOVERED','POSSIBLE','HIGH_CONFIDENCE','CONFLICT')
                            ORDER BY event_instance_id""").fetchall():
        key=f"EVENT:{e['event_instance_id']}"
        rs=_review_state(con,key)
        if rs not in ("APPROVED","REJECTED","MODIFIED"):
            review.append({"type":"EVENT_REVIEW","review_key":key,
                           "event_instance_id":e["event_instance_id"],
                           "event_name":e["normalized_name"],"reason":f"EVENT_{e['status']}",
                           "review_state":rs,
                           "priority":"HIGH" if e["status"]=="CONFLICT" else "NORMAL"})
    for f in con.execute("""SELECT event_instance_id,field_name,confidence,value,
                            expected_value,verified_value FROM event_field_states
                            WHERE confidence IN ('EXPECTED','UNKNOWN','CONFLICT')
                            ORDER BY event_instance_id,field_name""").fetchall():
        key=f"FIELD:{f['event_instance_id']}:{f['field_name']}"
        rs=_review_state(con,key)
        if rs not in ("APPROVED","REJECTED","MODIFIED"):
            review.append({"type":"FIELD_REVIEW","review_key":key,
                           "event_instance_id":f["event_instance_id"],
                           "field":f["field_name"],"confidence":f["confidence"],
                           "reason":f"FIELD_{f['confidence']}",
                           "review_state":rs,
                           "priority":"HIGH" if f["confidence"]=="CONFLICT" else "NORMAL"})
    for r in con.execute("""SELECT recovery_id,post_id,source_id,event_hint,reason,state
                            FROM recovery_queue WHERE state<>'RESOLVED'
                            ORDER BY recovery_id""").fetchall():
        key=f"RECOVERY:{r['recovery_id']}"
        rs=_review_state(con,key)
        if rs not in ("APPROVED","REJECTED","MODIFIED"):
            review.append({"type":"RECOVERY_REVIEW","review_key":key,
                           "recovery_id":r["recovery_id"],
                           "source_id":r["source_id"],"event_hint":r["event_hint"],
                           "reason":r["reason"],"state":r["state"],
                           "review_state":rs,"priority":"HIGH"})

    p0=[]
    for r in con.execute("""SELECT event_instance_id,field_name FROM event_field_states
                            WHERE confidence='VERIFIED' AND verified_value IS NULL""").fetchall():
        p0.append({"code":"FALSE_FIELD_VERIFIED","event_instance_id":r["event_instance_id"],
                   "field":r["field_name"]})
    for r in con.execute("""SELECT ei.event_instance_id,ei.identity_key FROM event_instances ei
                            WHERE ei.status='VERIFIED' AND (
                              NOT EXISTS(SELECT 1 FROM event_field_states f
                                WHERE f.event_instance_id=ei.event_instance_id
                                  AND f.field_name='date' AND f.confidence='VERIFIED')
                              OR NOT EXISTS(SELECT 1 FROM event_field_states f
                                WHERE f.event_instance_id=ei.event_instance_id
                                  AND f.field_name='venue' AND f.confidence='VERIFIED')
                            )""").fetchall():
        p0.append({"code":"FALSE_EVENT_VERIFIED","event_instance_id":r["event_instance_id"],
                   "identity_key":r["identity_key"]})

    high=sum(1 for x in review if x["priority"]=="HIGH")
    health="RED" if p0 else ("YELLOW" if review else "GREEN")
    return {
      "health":health,
      "event_confidence_distribution":event_conf,
      "field_confidence_distribution":field_conf,
      "source_operations":source_rows,
      "recovery_status":recovery_status,
      "human_review_queue":review,
      "human_review_count":len(review),
      "human_review_high_priority_count":high,
      "p0_errors":p0,
      "p0_count":len(p0),
      "human_in_loop_metrics":calculate_human_review_metrics(con),
      "correction_hotspots":analyze_correction_hotspots(con),
      "improvement_backlog":recommend_improvement_backlog(con),
      "backlog_lifecycle":{"items":backlog_list(con)},
      "change_traceability":{
        "changes":list_changes(con),
        "verdicts":[dict(x) for x in con.execute("""SELECT v.change_id,v.verdict,v.score,
          v.comparable_metric_count,v.improved_metric_count,v.regressed_metric_count,
          v.unchanged_metric_count,v.weighted_score,v.goal_profile,v.baseline_daily_run_id,v.post_daily_run_id,v.created_at
          FROM change_effect_verdicts v
          JOIN (SELECT change_id,MAX(verdict_id) vid FROM change_effect_verdicts GROUP BY change_id) x
            ON x.vid=v.verdict_id
          ORDER BY v.change_id""").fetchall()],
        "shadow_verdicts":[dict(x) for x in con.execute("""SELECT s.change_id,s.goal_profile,
          s.base_verdict,s.shadow_verdict,s.base_weighted_score,s.shadow_weighted_score,
          s.agrees,s.adaptive_sample_count,s.baseline_daily_run_id,s.post_daily_run_id,s.created_at
          FROM adaptive_shadow_verdicts s
          JOIN (SELECT change_id,MAX(shadow_id) sid FROM adaptive_shadow_verdicts GROUP BY change_id) x
            ON x.sid=s.shadow_id
          ORDER BY s.change_id""").fetchall()],
        "shadow_safety":shadow_safety_status(con),
        "rolling_shadow_stability":rolling_shadow_status(con),
        "promotion_candidates":promotion_candidates(con),
        "promotion_reviews":promotion_review_history(con),
        "promotion_leases":promotion_leases(con),
        "promotion_lease_events":promotion_lease_events(con),
        "canary_outcomes":canary_outcome_history(con),
        "final_promotion_reviews":final_promotion_reviews(con),
        "full_promotions":full_promotions(con),
        "post_promotion_guards":post_promotion_guard_history(con),
        "promotion_health":post_promotion_health(con)
,
        "decision_quality":decision_quality_history(con),
        "goal_relevance_diagnostics":goal_relevance_history(con),
        "decision_outcome_evidence":evidence_list(con),
        "decision_outcome_confirmations":confirmation_history(con),
        "evidence_priority_queue":priority_queue(con),
        "evidence_queue_events":queue_event_history(con),
        "evidence_clusters":cluster_list(con),
        "root_cause_attributions":root_cause_list(con),
        "cluster_closure_checks":closure_history(con),
        "source_reliability_profiles":reliability_profiles(con),
        "preventive_verification_decisions":verification_decisions(con),
        "preventive_policy_canaries":canaries(con),
        "preventive_policy_canary_events":canary_events(con),
        "preventive_policy_outcomes":outcomes(con),
        "preventive_canary_safety":safety_history(con),
        "preventive_full_promotions":full_promotions(con),
        "preventive_final_reviews":final_reviews(con),
        "preventive_full_runtime_guard":guard_history(con),
        "preventive_full_runtime_observations":runtime_observations(con),
        "preventive_full_runtime_events":guard_events(con),
        "preventive_recovery_cases":recovery_cases(con),
        "preventive_recovery_evaluations":recovery_evaluations(con),
        "preventive_recovery_events":recovery_events(con),
        "preventive_recurrence_profiles":recurrence_profiles(con),
        "preventive_recurrence_evaluations":recurrence_evaluations(con),
        "preventive_recurrence_exceptions":recurrence_exceptions(con),
        "preventive_quarantines":quarantines(con),
        "preventive_quarantine_events":quarantine_events(con),
        "preventive_reintegration_evaluations":reintegration_evaluations(con),
        "preventive_quarantine_release_reviews":release_reviews(con),
        "alternative_route_evaluations":route_evaluations(con),
        "verification_continuity_snapshots":continuity_snapshots(con),
        "source_relationships":relationships(con),
        "evidence_origin_fingerprints":fingerprints(con),
        "source_independence_evaluations":independence_history(con),
        "cross_post_clusters":clusters(con),
        "origin_inference_calibrations":calibration_history(con),
        "origin_review_priorities":priority_history(con),
        "origin_threshold_candidates":threshold_candidates(con),
        "origin_threshold_canaries":threshold_canaries(con),
        "origin_threshold_promotions":threshold_promotions(con),
        "origin_threshold_runtime":threshold_runtime_status(con),
        "origin_threshold_runtime_observations":threshold_runtime_history(con),
        "origin_threshold_guard_evaluations":threshold_guard_history(con),
        "origin_threshold_recovery_cases":threshold_recovery_cases(con),
        "origin_threshold_guard_status":threshold_guard_status(con),
        "origin_threshold_root_causes":threshold_root_causes(con),
        "origin_threshold_adaptive_requirements":threshold_adaptive_requirements(con),
        "origin_threshold_recurrence_profiles":threshold_recurrence_profiles(con),
        "origin_threshold_long_term_restrictions":threshold_long_term_restrictions(con),
        "origin_threshold_remediation_effectiveness":remediation_effectiveness_history(con),
        "origin_threshold_remediation_type_stats":remediation_type_stats(con),
        "origin_threshold_restriction_scopes":threshold_restriction_scopes(con),
        "origin_threshold_scope_routes":threshold_scope_routes(con),
        "origin_threshold_scope_status":threshold_scope_status(con),
        "origin_threshold_scope_reintegration_evidence":threshold_scope_reintegration_evidence(con),
        "origin_threshold_scope_reintegration_evaluations":threshold_scope_reintegration_evaluations(con),
        "origin_threshold_scope_reintegration_canaries":threshold_scope_reintegration_canaries(con),
        "origin_threshold_scope_reintegration_status":threshold_scope_reintegration_status(con),
        "origin_threshold_post_reintegration_observations":threshold_post_reintegration_observations(con),
        "origin_threshold_post_reintegration_evaluations":threshold_post_reintegration_evaluations(con),
        "origin_threshold_post_reintegration_reisolations":threshold_post_reintegration_reisolations(con),
        "origin_threshold_post_reintegration_status":threshold_post_reintegration_status(con),
        "origin_threshold_post_reintegration_root_causes":threshold_post_reintegration_root_causes(con),
        "origin_threshold_post_reintegration_remediation_routes":threshold_post_reintegration_remediation_routes(con),
        "origin_threshold_post_reintegration_root_status":threshold_post_reintegration_root_status(con),
        "origin_threshold_architecture_plans":threshold_architecture_plans(con),
        "origin_threshold_architecture_status":threshold_architecture_status(con),
        "origin_threshold_architecture_runtime_outcomes":threshold_architecture_runtime_outcomes(con),
        "origin_threshold_architecture_effectiveness_profiles":threshold_architecture_effectiveness_profiles(con),
        "origin_threshold_architecture_recommendations":threshold_architecture_recommendations(con),
        "origin_threshold_architecture_memory_status":threshold_architecture_memory_status(con),
        "origin_threshold_architecture_comparative_scores":threshold_architecture_comparative_scores(con),
        "origin_threshold_architecture_context_recommendations":threshold_architecture_context_recommendations(con),
        "origin_threshold_architecture_ranking_status":threshold_architecture_ranking_status(con),
        "origin_threshold_architecture_recommendation_challenges":threshold_architecture_recommendation_challenges(con),
        "origin_threshold_architecture_challenge_runtime_results":threshold_architecture_challenge_runtime_results(con),
        "origin_threshold_architecture_recommendation_quality_profiles":threshold_architecture_recommendation_quality_profiles(con),
        "origin_threshold_architecture_challenge_status":threshold_architecture_challenge_status(con),
        "origin_threshold_recommendation_policy_candidates":threshold_recommendation_policy_candidates(con),
        "origin_threshold_recommendation_policy_states":threshold_recommendation_policy_states(con),
        "origin_threshold_recommendation_policy_assignments":threshold_recommendation_policy_assignments(con),
        "origin_threshold_recommendation_policy_events":threshold_recommendation_policy_events(con),
        "origin_threshold_recommendation_policy_status":threshold_recommendation_policy_status(con),
        "origin_threshold_recommendation_recovery_cases":threshold_recommendation_recovery_cases(con),
        "origin_threshold_recommendation_recovery_status":threshold_recommendation_recovery_status(con),
        "origin_threshold_recommendation_algorithm_versions":threshold_recommendation_algorithm_versions(con),
        "origin_threshold_recommendation_algorithm_lineage":threshold_recommendation_algorithm_lineage(con),
        "origin_threshold_recommendation_recovery_version_links":threshold_recommendation_recovery_version_links(con),
        "origin_threshold_recommendation_algorithm_versioning_status":threshold_recommendation_algorithm_versioning_status(con),
        "origin_threshold_recommendation_algorithm_version_cohorts":threshold_recommendation_algorithm_version_cohorts(con),
        "origin_threshold_recommendation_algorithm_version_profiles":threshold_recommendation_algorithm_version_profiles(con),
        "origin_threshold_recommendation_algorithm_version_evaluations":threshold_recommendation_algorithm_version_evaluations(con),
        "origin_threshold_recommendation_algorithm_version_cohort_status":threshold_recommendation_algorithm_version_cohort_status(con),
        "origin_threshold_recommendation_version_promotion_gates":threshold_recommendation_version_promotion_gates(con),
        "origin_threshold_recommendation_version_supersede_comparisons":threshold_recommendation_version_supersede_comparisons(con),
        "origin_threshold_recommendation_version_promotion_reviews":threshold_recommendation_version_promotion_reviews(con),
        "origin_threshold_recommendation_version_promotion_events":threshold_recommendation_version_promotion_events(con),
        "origin_threshold_recommendation_version_promotion_status":threshold_recommendation_version_promotion_status(con),
        "origin_threshold_recommendation_supersede_guard_evaluations":threshold_recommendation_supersede_guard_evaluations(con),
        "origin_threshold_recommendation_version_fallbacks":threshold_recommendation_version_fallbacks(con),
        "origin_threshold_recommendation_supersede_guard_events":threshold_recommendation_supersede_guard_events(con),
        "origin_threshold_recommendation_supersede_guard_status":threshold_recommendation_supersede_guard_status(con),
        "origin_threshold_recommendation_fallback_verification_generations":threshold_recommendation_fallback_verification_generations(con),
        "origin_threshold_recommendation_fallback_verification_observations":threshold_recommendation_fallback_verification_observations(con),
        "origin_threshold_recommendation_fallback_pair_profiles":threshold_recommendation_fallback_pair_profiles(con),
        "origin_threshold_recommendation_fallback_verification_events":threshold_recommendation_fallback_verification_events(con),
        "origin_threshold_recommendation_fallback_verification_status":threshold_recommendation_fallback_verification_status(con),
        "origin_threshold_recommendation_fallback_family_profiles":threshold_recommendation_fallback_family_profiles(con),
        "origin_threshold_recommendation_fallback_family_reviews":threshold_recommendation_fallback_family_reviews(con),
        "origin_threshold_recommendation_fallback_family_events":threshold_recommendation_fallback_family_events(con),
        "origin_threshold_recommendation_fallback_family_status":threshold_recommendation_fallback_family_status(con),
        "origin_threshold_recommendation_fallback_family_recovery_cases":threshold_recommendation_fallback_family_recovery_cases(con),
        "origin_threshold_recommendation_fallback_family_recovery_remediations":threshold_recommendation_fallback_family_recovery_remediations(con),
        "origin_threshold_recommendation_fallback_family_recovery_evidence":threshold_recommendation_fallback_family_recovery_evidence(con),
        "origin_threshold_recommendation_fallback_family_recovery_evaluations":threshold_recommendation_fallback_family_recovery_evaluations(con),
        "origin_threshold_recommendation_fallback_family_recovery_reviews":threshold_recommendation_fallback_family_recovery_reviews(con),
        "origin_threshold_recommendation_fallback_family_recovery_events":threshold_recommendation_fallback_family_recovery_events(con),
        "origin_threshold_recommendation_fallback_family_recovery_status":threshold_recommendation_fallback_family_recovery_status(con),
        "origin_threshold_recommendation_fallback_family_generation_outcomes":threshold_recommendation_fallback_family_generation_outcomes(con),
        "origin_threshold_recommendation_fallback_family_effectiveness_profiles":threshold_recommendation_fallback_family_effectiveness_profiles(con),
        "origin_threshold_recommendation_fallback_family_generation_events":threshold_recommendation_fallback_family_generation_events(con),
        "origin_threshold_recommendation_fallback_family_memory_status":threshold_recommendation_fallback_family_memory_status(con),
        "origin_threshold_recommendation_fallback_family_remediation_rankings":threshold_recommendation_fallback_family_remediation_rankings(con),
        "origin_threshold_recommendation_fallback_family_remediation_recommendations":threshold_recommendation_fallback_family_remediation_recommendations(con),
        "origin_threshold_recommendation_fallback_family_remediation_selection_reviews":threshold_recommendation_fallback_family_remediation_selection_reviews(con),
        "origin_threshold_recommendation_fallback_family_remediation_ranking_events":threshold_recommendation_fallback_family_remediation_ranking_events(con),
        "origin_threshold_recommendation_fallback_family_ranking_status":threshold_recommendation_fallback_family_ranking_status(con),
        "origin_threshold_recommendation_fallback_family_recommendation_outcomes":threshold_recommendation_fallback_family_recommendation_outcomes(con),
        "origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles":threshold_recommendation_fallback_family_recommendation_effectiveness_profiles(con),
        "origin_threshold_recommendation_fallback_family_recommendation_outcome_events":threshold_recommendation_fallback_family_recommendation_outcome_events(con),
        "origin_threshold_recommendation_fallback_family_recommendation_outcome_status":threshold_recommendation_fallback_family_recommendation_outcome_status(con)      }
    }
