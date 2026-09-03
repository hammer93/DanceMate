import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

from .evaluator import run_gate1_replay, process_fixture, SOURCE_IDS
from .fixtures import FIXTURES
from .database import init_db, reset_runtime_tables, persist_fixture, seed_sources, persist_raw_post, persist_events
from .collectors.daum import DaumCafeSearchCollector, MissingApiKey, DaumCollectorError, load_snapshot
from .live_pipeline import process_discovered_post
from .acquisition_pipeline import acquire_pending_daum
from .acquirers.daum_post import DaumPostAcquirer
from .acquirers.snapshot import SnapshotDaumPostAcquirer
from .providers.snapshot import SnapshotCrossSourceProvider
from .providers.naver import NaverCrossSourceProvider
from .providers.naver_snapshot import NaverApiSnapshotProvider
from .collectors.naver import NaverSearchCollector, MissingNaverCredentials, NaverCollectorError, load_naver_snapshot
from .acquirers.generic import GenericPostAcquirer
from .acquirers.snapshot_generic import SnapshotGenericPostAcquirer
from .generic_acquisition_pipeline import acquire_posts, metadata_rows
from .metrics import calculate_source_metrics, aggregate_metrics
from .lifecycle import apply_revision,record_refresh,freshness_band
from .database import persist_event_revision,revision_history,upsert_event_instance,link_candidate_to_instance
from .gate1_validation import run_validation
from .validation_admin import add_ground_truth,update_ground_truth_status,export_dancemate_results,reconcile,generate_daily_report,generate_rolling_report
from .evidence_service import apply_evidence_model
from .media_classifier import classify_media
from .source_state import derive_source_state,source_can_verify_event,source_requires_recovery
from .evidence_metrics_v2 import calculate_metrics_v2
from .day1_real_metrics import calculate as calculate_day1_real
from .observation_metrics import calculate_observation_metrics
from .database import start_observation,finish_observation,lineage_trace
from .lineage_snapshot import run_snapshot as run_lineage_snapshot
from .live_lineage_harness import run_live_lineage_snapshot
from .daily_orchestrator import run_daily
from .daily_operations_summary import build_daily_operations_summary
from .daily_report_renderer import render_markdown
from .human_review_service import (
    review_event,review_field,review_recovery,validate_event_after_review
)
from .human_review_metrics import calculate_human_review_metrics
from .correction_hotspot import analyze_correction_hotspots
from .improvement_backlog import recommend_improvement_backlog
from .improvement_lifecycle import (
    sync_recommended_backlog,change_backlog_status,backlog_detail,backlog_list,capture_backlog_effect
)
from .change_traceability import (
    register_change,link_and_measure_change,change_detail,list_changes,evaluate_change_effect,metric_weights_for_change
)
from .daily_metric_snapshot import load_snapshot_payload,verify_snapshot_integrity
from .database import list_daily_metric_snapshots,backlog_row
from .goal_weighting import profile_status,recompute_adaptive_profile
from .database import adaptive_shadow_agreement_stats
from .shadow_safety_gate import evaluate_shadow_safety,shadow_safety_history
from .rolling_shadow_stability import evaluate_rolling_shadow_stability,rolling_shadow_history,promotion_candidates
from .adaptive_promotion import (
    review_promotion_candidate,promotion_review_history,promotion_leases,
    promotion_lease_events,rollback_active_goal_lease
)
from .canary_outcome import (
    evaluate_canary_outcome,canary_outcome_history,final_promotion_decision,
    final_promotion_reviews,full_promotions,rollback_active_full_promotion
)
from .post_promotion_guard import (
    evaluate_post_promotion_guard,post_promotion_guard_history,post_promotion_health
)
from .decision_quality import (
    record_decision_quality,evaluate_goal_relevance,
    decision_quality_history,goal_relevance_history
)
from .decision_outcome_evidence import (
    scan_automatic_evidence,record_visit_feedback_evidence,
    confirm_evidence,evidence_list,confirmation_history
)
from .evidence_priority_queue import (
    evaluate_evidence_priority_queue,priority_queue,queue_event_history
)
from .evidence_cluster_resolution import (
    resolve_clusters,cluster_list,attribute_root_causes,root_cause_list,
    sync_root_cause_backlog,closure_check,close_cluster,closure_history
)
from .source_reliability import (
    recompute_all_profiles,reliability_profiles,reliability_observations,
    record_success,evaluate_verification_policy,verification_decisions,
    start_canary,rollback_canary,canaries,canary_events
)
from .preventive_policy_outcome import (
    record_outcome,outcomes,evaluate_canary_safety,safety_history,
    final_review,full_promotions,final_reviews,rollback_full
)
from .preventive_full_runtime_guard import (
    evaluate_runtime_guard,guard_history,runtime_observations,guard_events
)
from .preventive_recovery import (
    record_root_cause,record_remediation,evaluate_recovery,requalify,
    recovery_cases,recovery_evaluations,recovery_events
)
from .preventive_recurrence import (
    recurrence_policy,recurrence_profiles,recurrence_evaluations,
    approve_exception,recurrence_exceptions
)
from .preventive_quarantine import (
    quarantines,quarantine_events,evaluate_reintegration,
    reintegration_evaluations,release_review,release_reviews
)
from .alternative_source_routing import (
    plan_alternative_route,route_evaluations,route_events,
    continuity_metrics,continuity_snapshots
)
from .source_independence_graph import (
    register_relationship,register_fingerprint,evaluate_pair,
    relationships,fingerprints,independence_history
)
from .automated_origin_inference import (
    infer_cross_post_cluster,clusters,review_cluster
)
from .origin_confidence_calibration import (
    evaluate_calibration,calibration_history,build_review_queue,priority_history
)
from .origin_threshold_promotion import (
    create_candidate_from_latest_calibration,candidates,review_candidate,
    start_canary,canary,canaries,record_canary_outcome,
    promote_candidate,promotions,rollback_promotion,runtime_status
)
from .origin_threshold_runtime_guard import (
    observe_runtime_outcome,runtime_history,evaluation_history,
    recovery_cases,add_recovery_shadow_outcome,requalify_recovery,
    runtime_guard_status
)
from .origin_threshold_recovery_root_cause import (
    attribute_root_cause,root_causes,build_adaptive_requirement,requirements,
    submit_remediation,review_remediation,review_root_cause,
    adaptive_requalification_status
)
from .origin_threshold_recurrence_guard import (
    profiles as threshold_recurrence_profiles,
    recurrence_events as threshold_recurrence_events,
    remediation_effectiveness_history,remediation_type_stats,
    evaluate_remediation_effectiveness,restrictions as threshold_restrictions,
    restriction_exceptions,grant_restriction_exception,release_restriction,
    recurrence_status
)
from .origin_threshold_scope_isolation import (
    scopes as threshold_restriction_scopes,scope_routes as threshold_scope_routes,
    derive_scope_for_restriction,derive_all_active_scopes,override_scope,
    release_scope,scope_status,evaluate_safe_alternative_path
)
from .origin_threshold_scope_reintegration import (
    add_evidence as add_scope_reintegration_evidence,
    evidence as scope_reintegration_evidence,
    evaluate_gate as evaluate_scope_reintegration_gate,
    evaluations as scope_reintegration_evaluations,
    review_for_canary as review_scope_reintegration,
    start_canary as start_scope_reintegration_canary,
    canaries as scope_reintegration_canaries,
    record_canary_outcome as record_scope_reintegration_canary_outcome,
    final_release as final_scope_reintegration_release,
    status as scope_reintegration_status
)
from .origin_threshold_post_reintegration_guard import (
    record_observation as record_post_reintegration_observation,
    observations as post_reintegration_observations,
    evaluations as post_reintegration_evaluations,
    re_isolations as post_reintegration_reisolations,
    evaluate_guard as evaluate_post_reintegration_guard,
    clear_reisolation as clear_post_reintegration_reisolation,
    requirement_penalty as post_reintegration_requirement_penalty,
    status as post_reintegration_status
)
from .origin_threshold_post_reintegration_root_cause import (
    attribute_root_cause as attribute_post_reintegration_root_cause,
    root_causes as post_reintegration_root_causes,
    remediation_routes as post_reintegration_remediation_routes,
    review_root_cause as review_post_reintegration_root_cause,
    latest_route_for_scope as latest_post_reintegration_route_for_scope,
    status as post_reintegration_root_cause_status
)
from .origin_threshold_architecture_escalation import (
    create_plan as create_architecture_plan,
    plans as architecture_plans,
    approve_plan as approve_architecture_plan,
    complete_step as complete_architecture_step,
    add_validation_evidence as add_architecture_validation_evidence,
    evaluate_plan as evaluate_architecture_plan,
    architecture_review as review_architecture_plan,
    architecture_gate_for_scope,
    status as architecture_escalation_status
)
from .origin_threshold_architecture_memory import (
    runtime_outcomes as architecture_runtime_outcomes,
    effectiveness_profiles as architecture_effectiveness_profiles,
    recommendations as architecture_recommendations,
    maybe_mark_sustained as maybe_mark_architecture_sustained,
    recommend_plan as recommend_architecture_plan,
    status as architecture_memory_status
)
from .origin_threshold_architecture_ranking import (
    context_for_scope as architecture_context_for_scope,
    comparative_scores as architecture_comparative_scores,
    score_history as architecture_comparative_score_history,
    recommendation_history as architecture_context_recommendation_history,
    recommend_contextual_plan as recommend_contextual_architecture_plan,
    status as architecture_ranking_status
)
from .origin_threshold_recommendation_challenge import (
    challenges as architecture_recommendation_challenges,
    add_shadow_outcome as add_architecture_challenge_shadow_outcome,
    evaluate_challenge as evaluate_architecture_challenge,
    human_decision as architecture_challenge_human_decision,
    runtime_results as architecture_challenge_runtime_results,
    quality_profiles as architecture_recommendation_quality_profiles,
    status as architecture_challenge_status
)
from .origin_threshold_recommendation_policy import (
    evaluate_candidate as evaluate_recommendation_policy_candidate,
    candidates as recommendation_policy_candidates,
    states as recommendation_policy_states,
    review_candidate as review_recommendation_policy_candidate,
    final_policy_review as final_recommendation_policy_review,
    manual_rollback as rollback_recommendation_policy,
    assignments as recommendation_policy_assignments,
    events as recommendation_policy_events,
    status as recommendation_policy_status
)
from .origin_threshold_recommendation_recovery import (
    cases as recommendation_recovery_cases,
    add_remediation as add_recommendation_recovery_remediation,
    review_remediation as review_recommendation_recovery_remediation,
    add_evidence as add_recommendation_recovery_evidence,
    evaluate as evaluate_recommendation_recovery,
    review_recanary as review_recommendation_recanary,
    status as recommendation_recovery_status
)
from .origin_threshold_recommendation_versioning import (
    register_version as register_recommendation_algorithm_version,
    versions as recommendation_algorithm_versions,
    current_version as current_recommendation_algorithm_version,
    lineage as recommendation_algorithm_lineage,
    events as recommendation_algorithm_version_events,
    propose_successor as propose_recovery_successor_algorithm_version,
    approve_successor as approve_recovery_successor_algorithm_version,
    recovery_links as recommendation_recovery_version_links,
    recovery_successor_ready as recommendation_recovery_successor_ready,
    status as recommendation_algorithm_versioning_status
)
from .origin_threshold_recommendation_version_cohort import (
    cohorts as recommendation_algorithm_version_cohorts,
    profiles as recommendation_algorithm_version_profiles,
    evaluate_version as evaluate_recommendation_algorithm_version,
    evaluations as recommendation_algorithm_version_evaluations,
    status as recommendation_algorithm_version_cohort_status
)
from .origin_threshold_recommendation_version_promotion import (
    evaluate_gate as evaluate_recommendation_version_promotion_gate,
    human_review as review_recommendation_version_promotion,
    promotion_ready as recommendation_version_promotion_ready,
    gates as recommendation_version_promotion_gates,
    comparisons as recommendation_version_supersede_comparisons,
    reviews as recommendation_version_promotion_reviews,
    events as recommendation_version_promotion_events,
    status as recommendation_version_promotion_status
)
from .origin_threshold_recommendation_supersede_guard import (
    evaluate_fallback as evaluate_recommendation_version_fallback,
    evaluations as recommendation_supersede_guard_evaluations,
    fallbacks as recommendation_version_fallbacks,
    events as recommendation_supersede_guard_events,
    status as recommendation_supersede_guard_status
)
from .origin_threshold_recommendation_fallback_verification import (
    generations as recommendation_fallback_verification_generations,
    observations as recommendation_fallback_verification_observations,
    pair_profiles as recommendation_fallback_pair_profiles,
    events as recommendation_fallback_verification_events,
    status as recommendation_fallback_verification_status
)
from .origin_threshold_recommendation_fallback_family import (
    profiles as recommendation_fallback_family_profiles,
    reviews as recommendation_fallback_family_reviews,
    review as review_recommendation_fallback_family,
    events as recommendation_fallback_family_events,
    status as recommendation_fallback_family_status
)
from .origin_threshold_recommendation_fallback_family_recovery import (
    cases as recommendation_fallback_family_recovery_cases,
    remediations as recommendation_fallback_family_recovery_remediations,
    add_remediation as add_recommendation_fallback_family_remediation,
    review_remediation as review_recommendation_fallback_family_remediation,
    set_candidate_version as set_recommendation_fallback_family_candidate,
    evidence as recommendation_fallback_family_recovery_evidence,
    add_evidence as add_recommendation_fallback_family_evidence,
    evaluate as evaluate_recommendation_fallback_family_recovery,
    human_rearm_review as review_recommendation_fallback_family_rearm,
    evaluations as recommendation_fallback_family_recovery_evaluations,
    reviews as recommendation_fallback_family_recovery_reviews,
    events as recommendation_fallback_family_recovery_events,
    status as recommendation_fallback_family_recovery_status
)
from .origin_threshold_recommendation_fallback_family_memory import (
    outcomes as recommendation_fallback_family_generation_outcomes,
    effectiveness_profiles as recommendation_fallback_family_effectiveness_profiles,
    evaluate_sustained as evaluate_recommendation_fallback_family_generation_sustained,
    remediation_allowed as recommendation_fallback_family_remediation_allowed,
    events as recommendation_fallback_family_generation_events,
    status as recommendation_fallback_family_memory_status
)
from .origin_threshold_recommendation_fallback_family_ranking import (
    rank_case as rank_recommendation_fallback_family_remediations,
    recommend_case as recommend_recommendation_fallback_family_remediation,
    rankings as recommendation_fallback_family_remediation_rankings,
    recommendations as recommendation_fallback_family_remediation_recommendations,
    review_selection as review_recommendation_fallback_family_remediation_selection,
    selection_reviews as recommendation_fallback_family_remediation_selection_reviews,
    events as recommendation_fallback_family_remediation_ranking_events,
    status as recommendation_fallback_family_ranking_status
)
from .origin_threshold_recommendation_fallback_family_recommendation_outcome import (
    outcomes as recommendation_fallback_family_recommendation_outcomes,
    effectiveness_profiles as recommendation_fallback_family_recommendation_effectiveness_profiles,
    events as recommendation_fallback_family_recommendation_outcome_events,
    status as recommendation_fallback_family_recommendation_outcome_status
)
from .database import list_human_review_actions
from .discovery_observer import run_discovery_with_lineage,record_discovery_persist_result
from .recovery_engine import run_recovery_with_lineage
from .recovery_engine import run_recovery
from .database import enqueue_recovery, event_instance_summary

ROOT = Path(__file__).resolve().parents[1]

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def db_path():
    return ROOT/"data"/"dancemate_ie_poc_v0.73.sqlite3"

def cmd_fixture():
    con=init_db(db_path())
    reset_runtime_tables(con)
    sources=load_json(ROOT/"config"/"sources.json")
    seed_sources(con,sources)
    for key, fx in FIXTURES.items():
        c, events=process_fixture(key,fx)
        persist_fixture(con,key,SOURCE_IDS[key],fx['title'],fx['body'],events)
    con.close()
    results = run_gate1_replay()
    ok = all(r['pass'] for r in results)
    report = {"version":"0.3","mode":"fixture_replay","fixtures":results,
              "summary":{"total":len(results),"passed":sum(r['pass'] for r in results),"failed":sum(not r['pass'] for r in results),"gate":"PASS" if ok else "FAIL"}}
    out=ROOT/"data"/"reports"/"gate1-fixture-report-v0.3.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Fixture Gate: {report['summary']['gate']} ({report['summary']['passed']}/{report['summary']['total']})")
    return 0 if ok else 1

def _daum_sources():
    return [s for s in load_json(ROOT/"config"/"sources.json") if s.get("platform")=="DAUM_CAFE" and s.get("status")=="ACTIVE"]

def _collect_records(mode: str, source: dict, settings: dict):
    if mode == "snapshot":
        return load_snapshot(ROOT/"data"/"collector_snapshots"/"daum-cafe-sample.json", source, query="snapshot")
    d=settings["daum"]
    collector=DaumCafeSearchCollector(d["endpoint"], timeout_seconds=d.get("timeout_seconds",15))
    return collector.collect_source(source, sort=d.get("sort","recency"), page=d.get("page",1), size=d.get("size",50))

def cmd_daum(mode: str):
    settings=load_json(ROOT/"config"/"settings.json")
    con=init_db(db_path())
    sources=load_json(ROOT/"config"/"sources.json")
    seed_sources(con,sources)
    summary=[]
    try:
        for source in _daum_sources():
            started=datetime.now(timezone.utc).isoformat()
            try:
                observed=run_discovery_with_lineage(
                    con,source_id=source["source_id"],
                    query=" | ".join(source.get("queries") or ["밀롱가"]),
                    collector_callable=lambda source=source: _collect_records(mode,source,settings)
                )
                records=observed["rows"]
                new=dup=0
                processed=[]
                for post in records:
                    post_id,is_new=persist_raw_post(con,post)
                    record_discovery_persist_result(
                        con,lineage_id=observed["lineage_id"],observation_id=observed["observation_id"],
                        post_id=post_id,source_id=post.source_id,source_url=post.source_url,is_new=is_new
                    )
                    new += int(is_new); dup += int(not is_new)
                    if is_new:
                        result=process_discovered_post(con,post,source.get("source_role","SECONDARY"))
                        if result["events"]:
                            persist_events(con,post_id,result["events"]); con.commit()
                        processed.append({"url":post.source_url,"title":post.title,"classification":result["classification"],"events":[e.to_dict() for e in result["events"]]})
                finished=datetime.now(timezone.utc).isoformat()
                con.execute("INSERT INTO collector_runs(collector,source_id,mode,query_count,discovered_count,new_count,duplicate_count,started_at,finished_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            ("DAUM_CAFE_SEARCH",source["source_id"],mode,len(source.get("queries") or ["밀롱가"]),len(records),new,dup,started,finished,"PASS"))
                con.commit()
                summary.append({"source_id":source["source_id"],"source":source["name"],"mode":mode,"discovered":len(records),"new":new,"duplicates":dup,"processed":processed,"status":"PASS"})
            except (MissingApiKey,DaumCollectorError) as e:
                finished=datetime.now(timezone.utc).isoformat()
                con.execute("INSERT INTO collector_runs(collector,source_id,mode,query_count,started_at,finished_at,status,error) VALUES(?,?,?,?,?,?,?,?)",
                            ("DAUM_CAFE_SEARCH",source["source_id"],mode,len(source.get("queries") or ["밀롱가"]),started,finished,"BLOCKED",str(e)))
                con.commit()
                summary.append({"source_id":source["source_id"],"source":source["name"],"mode":mode,"status":"BLOCKED","error":str(e)})
                if mode == "live":
                    break
    finally:
        con.close()
    report={"version":"0.3","collector":"DAUM_CAFE_SEARCH","mode":mode,"generated_at":datetime.now(timezone.utc).isoformat(),"sources":summary}
    out=ROOT/"data"/"reports"/f"daum-collector-{mode}-report-v0.3.json"
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"mode":mode,"report":str(out),"sources":[{k:v for k,v in s.items() if k!='processed'} for s in summary]},ensure_ascii=False,indent=2))
    return 2 if any(s["status"]=="BLOCKED" for s in summary) else 0

def _seed_acquisition_snapshot_posts(con):
    # Deterministic local snapshots for FULL and PARTIAL acquisition paths.
    from .collectors.base import RawPostRecord
    rows = [
        RawPostRecord("SRC-D-001","DAUM_CAFE","https://snapshot.local/daum/pista",
                      "8/22 더 피스타 밀롱가","검색 snippet",acquisition_quality="METADATA_ONLY"),
        RawPostRecord("SRC-D-001","DAUM_CAFE","https://snapshot.local/daum/login",
                      "8/29 테스트 밀롱가","검색 snippet",acquisition_quality="METADATA_ONLY"),
    ]
    ids=[]
    for p in rows:
        obs=run_discovery_with_lineage(
            con,source_id=p.source_id,query=p.title,collector_callable=lambda p=p:[p]
        )
        pid,is_new=persist_raw_post(con,p)
        record_discovery_persist_result(
            con,lineage_id=obs["lineage_id"],observation_id=obs["observation_id"],
            post_id=pid,source_id=p.source_id,source_url=p.source_url,is_new=is_new
        )
        ids.append((p.source_url,pid))
    return ids

def cmd_acquire(mode: str):
    con=init_db(db_path())
    sources=load_json(ROOT/"config"/"sources.json")
    seed_sources(con,sources)
    try:
        if mode=="snapshot":
            # only add snapshot inputs if they do not yet exist
            _seed_acquisition_snapshot_posts(con)
            mapping={
                "https://snapshot.local/daum/pista":"daum-full-pista.html",
                "https://snapshot.local/daum/login":"daum-partial-login-shell.html",
            }
            acq=SnapshotDaumPostAcquirer(ROOT/"data"/"acquisition_snapshots",mapping)
        else:
            acq=DaumPostAcquirer(timeout_seconds=load_json(ROOT/"config"/"settings.json")["daum"].get("timeout_seconds",15))
        rows=acquire_pending_daum(con,mode=mode,acquirer=acq)
        pending=con.execute("SELECT COUNT(*) AS n FROM recovery_queue WHERE state='PENDING'").fetchone()["n"]
        report={"version":"0.3","mode":mode,"generated_at":datetime.now(timezone.utc).isoformat(),
                "acquisitions":rows,"recovery_queue_pending":pending}
        out=ROOT/"data"/"reports"/f"daum-acquisition-{mode}-report-v0.3.json"
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"mode":mode,"acquisitions":[{k:v for k,v in r.items() if k!='events'} for r in rows],
                          "recovery_queue_pending":pending,"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()


def _seed_cross_source_recovery(con):
    from .collectors.base import RawPostRecord
    # Origin Daum record intentionally lacks time; recovery should find a Naver source
    # for the same 2026-08-22 PISTA event and link both candidates to one EventInstance.
    p=RawPostRecord(
        "SRC-D-001","DAUM_CAFE","https://snapshot.local/daum/pista-incomplete",
        "8/22 더 피스타 밀롱가",
        "8/22 더 피스타 밀롱가 홍대 PISTA 입장료 13,000원 DJ Hernan",
        acquisition_quality="BODY_ONLY"
    )
    observed=run_discovery_with_lineage(
        con,source_id=p.source_id,query=p.title,collector_callable=lambda:[p]
    )
    post_id,is_new=persist_raw_post(con,p)
    record_discovery_persist_result(
        con,lineage_id=observed["lineage_id"],observation_id=observed["observation_id"],
        post_id=post_id,source_id=p.source_id,source_url=p.source_url,is_new=is_new
    )
    if is_new:
        result=process_discovered_post(con,p,"SECONDARY")
        if result["events"]:
            persist_events(con,post_id,result["events"]); con.commit()
    enqueue_recovery(con,post_id,"SRC-D-001","8/22 더 피스타 밀롱가","FULL_BODY_UNAVAILABLE")
    return post_id

def cmd_recover_snapshot():
    con=init_db(db_path())
    sources=load_json(ROOT/"config"/"sources.json")
    seed_sources(con,sources)
    try:
        _seed_cross_source_recovery(con)
        provider=SnapshotCrossSourceProvider(ROOT/"data"/"cross_source_snapshots"/"naver-recovery-sample.json")
        rows=run_recovery_with_lineage(con,provider)
        inst=[dict(r) for r in event_instance_summary(con)]
        pending=con.execute("SELECT COUNT(*) AS n FROM recovery_queue WHERE state='PENDING'").fetchone()["n"]
        report={"version":"0.4","mode":"snapshot","generated_at":datetime.now(timezone.utc).isoformat(),
                "recoveries":rows,"event_instances":inst,"pending_recovery":pending}
        out=ROOT/"data"/"reports"/"cross-source-recovery-snapshot-report-v0.4.json"
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"recoveries":rows,"event_instances":inst,"pending_recovery":pending,"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()


def cmd_naver_snapshot():
    con=init_db(db_path())
    sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        result=[]
        for kind, sid, fn in [
            ("blog","SRC-N-001","naver-blog-sample.json"),
            ("cafe","SRC-N-002","naver-cafe-sample.json"),
        ]:
            observed=run_discovery_with_lineage(
                con,source_id=sid,query="밀롱가",
                collector_callable=lambda kind=kind,sid=sid,fn=fn:
                    load_naver_snapshot(ROOT/"data"/"collector_snapshots"/fn,kind=kind,source_id=sid,query="밀롱가")
            )
            rows=observed["rows"]
            new=dup=0
            processed=[]
            for post in rows:
                pid,is_new=persist_raw_post(con,post)
                record_discovery_persist_result(
                    con,lineage_id=observed["lineage_id"],observation_id=observed["observation_id"],
                    post_id=pid,source_id=post.source_id,source_url=post.source_url,is_new=is_new
                )
                new+=int(is_new); dup+=int(not is_new)
                if is_new:
                    src=next((s for s in sources if s["source_id"]==sid),{})
                    r=process_discovered_post(con,post,src.get("source_role","SECONDARY"))
                    if r["events"]:
                        persist_events(con,pid,r["events"]); con.commit()
                    processed.append({"title":post.title,"classification":r["classification"],"events":[e.to_dict() for e in r["events"]]})
            result.append({"kind":kind,"source_id":sid,"discovered":len(rows),"new":new,"duplicates":dup,"processed":processed})
        out=ROOT/"data"/"reports"/"naver-collector-snapshot-report-v0.6.json"
        out.write_text(json.dumps({"version":"0.6","mode":"snapshot","results":result},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"results":[{k:v for k,v in x.items() if k!="processed"} for x in result],"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()

def cmd_naver_live():
    con=init_db(db_path())
    sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    collector=NaverSearchCollector(timeout_seconds=load_json(ROOT/"config"/"settings.json").get("naver",{}).get("timeout_seconds",15))
    summary=[]
    try:
        try:
            for kind,sid in [("blog","SRC-N-001"),("cafe","SRC-N-002")]:
                observed=run_discovery_with_lineage(
                    con,source_id=sid,query="서울 탱고 밀롱가",
                    collector_callable=lambda kind=kind,sid=sid:
                        collector.search("서울 탱고 밀롱가",kind=kind,display=100,start=1,sort="date",source_id=sid)
                )
                rows=observed["rows"]
                new=dup=0
                for post in rows:
                    pid,is_new=persist_raw_post(con,post)
                    record_discovery_persist_result(
                        con,lineage_id=observed["lineage_id"],observation_id=observed["observation_id"],
                        post_id=pid,source_id=post.source_id,source_url=post.source_url,is_new=is_new
                    )
                    new+=int(is_new); dup+=int(not is_new)
                    if is_new:
                        src=next((s for s in sources if s["source_id"]==sid),{})
                        r=process_discovered_post(con,post,src.get("source_role","SECONDARY"))
                        if r["events"]:
                            persist_events(con,pid,r["events"]); con.commit()
                summary.append({"kind":kind,"source_id":sid,"discovered":len(rows),"new":new,"duplicates":dup,"status":"PASS"})
        except (MissingNaverCredentials,NaverCollectorError) as e:
            summary.append({"status":"BLOCKED","error":str(e)})
        out=ROOT/"data"/"reports"/"naver-collector-live-report-v0.6.json"
        out.write_text(json.dumps({"version":"0.6","mode":"live","results":summary},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"results":summary,"report":str(out)},ensure_ascii=False,indent=2))
        return 2 if any(x.get("status")=="BLOCKED" for x in summary) else 0
    finally:
        con.close()

def cmd_recover_naver(mode):
    con=init_db(db_path())
    sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        _seed_cross_source_recovery(con)
        if mode=="snapshot":
            provider=NaverApiSnapshotProvider(ROOT/"data"/"collector_snapshots")
        else:
            provider=NaverCrossSourceProvider()
        try:
            rows=run_recovery_with_lineage(con,provider)
            status="PASS"
        except (MissingNaverCredentials,NaverCollectorError) as e:
            rows=[]; status="BLOCKED"; error=str(e)
        inst=[dict(r) for r in event_instance_summary(con)]
        pending=con.execute("SELECT COUNT(*) AS n FROM recovery_queue WHERE state='PENDING'").fetchone()["n"]
        report={"version":"0.6","mode":mode,"status":status,"recoveries":rows,"event_instances":inst,"pending_recovery":pending}
        if status=="BLOCKED": report["error"]=error
        out=ROOT/"data"/"reports"/f"naver-cross-source-recovery-{mode}-report-v0.6.json"
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"status":status,"recoveries":rows,"event_instances":inst,"pending_recovery":pending,"report":str(out),**({"error":error} if status=="BLOCKED" else {})},ensure_ascii=False,indent=2))
        return 2 if status=="BLOCKED" else 0
    finally:
        con.close()


def cmd_acquire_naver_snapshot():
    con=init_db(db_path()); sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        # Seed Naver API-shaped discovery first so acquisition has METADATA_ONLY rows.
        for kind,sid,fn in [("blog","SRC-N-001","naver-blog-sample.json"),("cafe","SRC-N-002","naver-cafe-sample.json")]:
            observed=run_discovery_with_lineage(
                con,source_id=sid,query="밀롱가",
                collector_callable=lambda kind=kind,sid=sid,fn=fn:
                    load_naver_snapshot(ROOT/"data"/"collector_snapshots"/fn,kind=kind,source_id=sid,query="밀롱가")
            )
            for post in observed["rows"]:
                pid,is_new=persist_raw_post(con,post)
                record_discovery_persist_result(
                    con,lineage_id=observed["lineage_id"],observation_id=observed["observation_id"],
                    post_id=pid,source_id=post.source_id,source_url=post.source_url,is_new=is_new
                )
                if is_new:
                    src=next((s for s in sources if s["source_id"]==sid),{})
                    r=process_discovered_post(con,post,src.get("source_role","SECONDARY"))
                    if r["events"]: persist_events(con,pid,r["events"]); con.commit()
        mapping={
          "https://snapshot.local/naver/blog/pista":"naver-blog-full.html",
          "https://snapshot.local/naver/cafe/pista":"naver-cafe-body-only.html",
          "https://snapshot.local/naver/blog/class":"naver-blocked.html",
        }
        acq=SnapshotGenericPostAcquirer(ROOT/"data"/"acquisition_snapshots",mapping)
        rows=metadata_rows(con,platforms=["NAVER_BLOG","NAVER_CAFE"])
        result=acquire_posts(con,rows,mode="snapshot",acquirer=acq)
        out=ROOT/"data"/"reports"/"naver-acquisition-snapshot-report-v0.6.json"
        out.write_text(json.dumps({"version":"0.6","mode":"snapshot","acquisitions":result},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"acquisitions":result,"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()

def cmd_acquire_naver_live():
    con=init_db(db_path()); sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        rows=metadata_rows(con,platforms=["NAVER_BLOG","NAVER_CAFE"])
        result=acquire_posts(con,rows,mode="live",acquirer=GenericPostAcquirer(timeout_seconds=load_json(ROOT/"config"/"settings.json")["naver"].get("timeout_seconds",15)))
        out=ROOT/"data"/"reports"/"naver-acquisition-live-report-v0.6.json"
        out.write_text(json.dumps({"version":"0.6","mode":"live","acquisitions":result},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"acquisitions":result,"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()

def cmd_metrics():
    con=init_db(db_path()); sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        rows=calculate_source_metrics(con,window_label="runtime")
        agg=aggregate_metrics(rows)
        report={"version":"0.6","generated_at":datetime.now(timezone.utc).isoformat(),"sources":rows,"aggregate":agg}
        out=ROOT/"data"/"reports"/"acquisition-metrics-report-v0.7.json"
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        # Markdown companion
        md=["# DanceMate Information Engine v0.6 Metrics","",
            f"- Total discovered: {agg['discovered_count']}",
            f"- Full body rate: {agg['full_body_rate']}",
            f"- Poster rate: {agg['poster_rate']}",
            f"- Recovery success rate: {agg['recovery_success_rate']}",
            f"- Human review rate: {agg['human_review_rate']}","",
            "| Source | Platform | Discovered | Acquisition | Full Body Rate | Poster Rate | Recovery Rate | Human Review Rate |",
            "|---|---|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            md.append(f"| {r['source_id']} | {r['platform']} | {r['discovered_count']} | {r['acquisition_attempts']} | {r['full_body_rate']} | {r['poster_rate']} | {r['recovery_success_rate']} | {r['human_review_rate']} |")
        mdout=ROOT/"data"/"reports"/"acquisition-metrics-report-v0.7.md"
        mdout.write_text("\n".join(md),encoding="utf-8")
        print(json.dumps({"aggregate":agg,"sources":rows,"report":str(out),"markdown":str(mdout)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()


def cmd_revision_snapshot():
    con=init_db(db_path()); sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        from .collectors.base import RawPostRecord
        data=load_json(ROOT/"data"/"revision_snapshots"/"pista-revisions.json")
        p=RawPostRecord("SRC-D-001","DAUM_CAFE","https://snapshot.local/revision/pista-original",
            data["original"]["title"],data["original"]["body"],acquisition_quality="BODY_ONLY")
        pid,_=persist_raw_post(con,p)
        r=process_discovered_post(con,p,"SECONDARY")
        persist_events(con,pid,r["events"]);con.commit()
        cand=con.execute("SELECT * FROM event_candidates WHERE post_id=? LIMIT 1",(pid,)).fetchone()
        eid=upsert_event_instance(con,"2026-08-29|pista|pista","pista","2026-08-29","pista","VERIFIED")
        link_candidate_to_instance(con,eid,cand["candidate_id"],"SRC-D-001")
        persist_event_revision(con,event_instance_id=eid,candidate_id=cand["candidate_id"],source_id="SRC-D-001",
            revision_role="ORIGINAL",field_changes={"status":{"to":"VERIFIED"}},raw_summary=data["original"]["body"])
        before="VERIFIED"
        upd=apply_revision(con,event_instance_id=eid,candidate_row=cand,source_id="SRC-D-001",raw_text=data["update"]["body"])
        r1=record_refresh(con,event_instance_id=eid,scheduled_event_date="2026-08-29",hours_before_start=6,
            status_before=before,status_after=upd["status_after"],source_id="SRC-D-001",notes=f"band={freshness_band(6)}")
        before2=upd["status_after"]
        can=apply_revision(con,event_instance_id=eid,candidate_row=cand,source_id="SRC-D-001",raw_text=data["cancel"]["body"])
        r2=record_refresh(con,event_instance_id=eid,scheduled_event_date="2026-08-29",hours_before_start=2,
            status_before=before2,status_after=can["status_after"],source_id="SRC-D-001",notes=f"band={freshness_band(2)}")
        event=dict(con.execute("SELECT * FROM event_instances WHERE event_instance_id=?",(eid,)).fetchone())
        hist=[dict(x) for x in revision_history(con,eid)]
        out=ROOT/"data"/"reports"/"event-revision-snapshot-report-v0.7.json"
        out.write_text(json.dumps({"version":"0.7","event":event,"update":upd,"cancellation":can,
            "refresh_checks":[r1,r2],"revisions":hist},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"event":event,"update":upd,"cancellation":can,"refresh_checks":[r1,r2],
            "revision_count":len(hist),"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_freshness_miss_snapshot():
    con=init_db(db_path()); sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        row=con.execute("SELECT event_instance_id,event_date FROM event_instances ORDER BY event_instance_id LIMIT 1").fetchone()
        if not row:
            print(json.dumps({"status":"SKIPPED","reason":"no event instance"}));return 0
        res=record_refresh(con,event_instance_id=row["event_instance_id"],scheduled_event_date=row["event_date"],
            hours_before_start=1,status_before="VERIFIED",status_after="VERIFIED",source_id="SRC-D-001",
            notes="synthetic critical cancellation miss",expected_cancellation=True)
        print(json.dumps(res,ensure_ascii=False,indent=2));return 0
    finally: con.close()


def cmd_gate1_14d(fail_case=False):
    gt=ROOT/"data"/"ground_truth"/"gate1-ground-truth-14d-v0.8.csv"
    dm=ROOT/"data"/"validation"/("gate1-dancemate-results-fail-v0.8.csv" if fail_case else "gate1-dancemate-results-14d-v0.8.csv")
    result=run_validation(gt,dm)
    suffix="fail" if fail_case else "pass"
    out=ROOT/"data"/"reports"/f"gate1-14d-{suffix}-report-v0.8.json"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    md=[
      "# DanceMate Gate 1 — 14 Day Validation v0.8","",
      f"- Gate: **{result['gate']}**",
      f"- Days: {result['aggregate']['days']}",
      f"- Ground Truth Events: {result['aggregate']['ground_truth_events']}",
      f"- Detected Events: {result['aggregate']['detected_events']}",
      f"- Event Recall: {result['aggregate']['event_recall']}",
      f"- VERIFIED Precision: {result['aggregate']['verified_precision']}",
      f"- Date Accuracy: {result['aggregate']['date_accuracy']}",
      f"- Time Accuracy: {result['aggregate']['time_accuracy']}",
      f"- Fee Accuracy: {result['aggregate']['fee_accuracy']}",
      f"- Venue Accuracy: {result['aggregate']['venue_accuracy']}",
      f"- Human Touch Rate: {result['aggregate']['human_touch_rate']}",
      f"- False VERIFIED: {result['aggregate']['false_verified']}",
      f"- Hallucinated Core Fields: {result['aggregate']['hallucinated_core_fields']}",
      f"- Critical Cancellation Miss: {result['aggregate']['critical_cancellation_miss']}",
      "",
      "## Daily",
      "",
      "| Date | GT | Detected | Recall | VERIFIED | Precision | Human Touch | Cancel Miss |",
      "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for d in result["daily"]:
        md.append(f"| {d['date']} | {d['ground_truth_events']} | {d['detected_events']} | {d['event_recall']} | {d['verified_events']} | {d['verified_precision']} | {d['human_touch_rate']} | {d['critical_cancellation_miss']} |")
    mdout=ROOT/"data"/"reports"/f"gate1-14d-{suffix}-report-v0.8.md"
    mdout.write_text("\n".join(md),encoding="utf-8")
    print(json.dumps({"gate":result["gate"],"aggregate":result["aggregate"],"report":str(out),"markdown":str(mdout)},ensure_ascii=False,indent=2))
    return 0 if result["gate"] in ("PASS","CONDITIONAL_PASS") else 1


def _live_gt_path():
    return ROOT/"data"/"validation_runtime"/"ground_truth_live.csv"

def _live_dm_path():
    return ROOT/"data"/"validation_runtime"/"dancemate_results_live.csv"

def cmd_gt_add(args):
    row=add_ground_truth(_live_gt_path(),event_date=args.date,event_name=args.name,venue=args.venue,
        start_time=args.start,end_time=args.end,fee=args.fee,actual_status=args.status,
        evidence_url=args.evidence_url or "",notes=args.notes or "")
    print(json.dumps(row,ensure_ascii=False,indent=2))
    return 0

def cmd_gt_status(args):
    row=update_ground_truth_status(_live_gt_path(),args.gt_id,args.status,args.notes or "")
    print(json.dumps(row,ensure_ascii=False,indent=2))
    return 0

def cmd_export_dm(args):
    con=init_db(db_path())
    try:
        result=export_dancemate_results(con,_live_dm_path(),event_date=args.date)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()

def cmd_reconcile(args):
    result=reconcile(_live_gt_path(),_live_dm_path(),date_filter=args.date)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

def cmd_daily_report(args):
    result=generate_daily_report(_live_gt_path(),_live_dm_path(),ROOT/"data"/"reports",args.date)
    print(json.dumps({"json":result["json"],"markdown":result["markdown"],"metrics":result["payload"]["metrics"]},ensure_ascii=False,indent=2))
    return 0

def cmd_rolling_report():
    result=generate_rolling_report(_live_gt_path(),_live_dm_path(),ROOT/"data"/"reports","rolling")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


def cmd_evidence_model_snapshot():
    con=init_db(db_path()); sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        data=load_json(ROOT/"data"/"evidence_model_snapshots"/"day1-reclassification.json")
        results=[]
        for item in data["events"]:
            eid=upsert_event_instance(con,item["identity_key"],item["name"],item["date"],item["venue"],"DISCOVERED")
            r=apply_evidence_model(con,event_instance_id=eid,date_value=item["date"],venue_value=item["venue"],
                time_value=item["time"],fee_verified=item.get("fee_verified"),fee_expected=item.get("fee_expected"),
                occurrence_confirmed=item.get("occurrence_confirmed",False),
                primary_or_equivalent=item.get("primary_or_equivalent",False))
            results.append({"name":item["name"],"expected":item["expected_event_confidence"],"result":r})
        out=ROOT/"data"/"reports"/"evidence-model-day1-report-v0.10.json"
        out.write_text(json.dumps({"version":"0.10","events":results},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"events":results,"report":str(out)},ensure_ascii=False,indent=2))
        return 0 if all(x["expected"]==x["result"]["event_confidence"] and not x["result"]["p0_errors"] for x in results) else 1
    finally:
        con.close()

def cmd_evidence_p0_snapshot():
    from .evidence_model import build_field_state,p0_validate
    d=build_field_state("date",current_value="2026-08-27",same_occurrence_verified=True)
    v=build_field_state("venue",current_value="PISTA",same_occurrence_verified=True)
    f=build_field_state("fee",recurring_value="13000")
    f.confidence="VERIFIED"
    errors=p0_validate("VERIFIED",[d,v,f])
    print(json.dumps({"errors":errors},ensure_ascii=False,indent=2))
    return 1 if errors else 0


def cmd_poster_source_snapshot():
    data=load_json(ROOT/"data"/"poster_source_snapshots"/"day1-media-source.json")
    media=[]
    ok=True
    for item in data["media_cases"]:
        r=classify_media(url=item["url"],surrounding_text=item.get("text",""))
        media.append({"url":item["url"],"expected":item["expected"],"actual":r.media_class,"reason":r.reason})
        ok = ok and (r.media_class==item["expected"])
    src=[]
    for item in data["source_cases"]:
        a,x=derive_source_state(source_role=item["source_role"],acquisition_status=item["status"],
                                http_status=item.get("http_status"),body_available=item.get("body_available",True))
        src.append({"input":item,"actual_authority":a,"actual_access":x,
                    "can_verify_event":source_can_verify_event(a,x),
                    "requires_recovery":source_requires_recovery(a,x)})
        ok = ok and (a==item["expected_authority"] and x==item["expected_access"])
    out=ROOT/"data"/"reports"/"poster-source-model-report-v0.11.json"
    out.write_text(json.dumps({"version":"0.11","media":media,"sources":src},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"media":media,"sources":src,"report":str(out)},ensure_ascii=False,indent=2))
    return 0 if ok else 1


def cmd_evidence_metrics_v2_snapshot():
    from .collectors.base import RawPostRecord
    con=init_db(db_path()); sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
    try:
        data=load_json(ROOT/"data"/"evidence_metrics_snapshots"/"metrics-v2-sample.json")
        now=datetime.now(timezone.utc).isoformat()
        for i,item in enumerate(data["events"],1):
            eid=upsert_event_instance(con,item["identity_key"],item["name"],item["date"],item["venue"],"DISCOVERED")
            apply_evidence_model(con,event_instance_id=eid,date_value=item["date"],venue_value=item["venue"],time_value=item["time"],
                fee_verified=item.get("fee_verified"),fee_expected=item.get("fee_expected"),
                occurrence_confirmed=item["occurrence_confirmed"],primary_or_equivalent=item["primary_or_equivalent"])
            sid="SRC-F-001" if i==1 else "SRC-D-001"
            post=RawPostRecord(sid,"FACEBOOK" if i==1 else "DAUM_CAFE",f"https://snapshot.local/metrics/{i}",
                item["name"],item["name"],acquisition_quality="BODY_ONLY")
            pid,_=persist_raw_post(con,post)
            cur=con.execute("""INSERT INTO event_candidates(post_id,name,event_type,event_date,start_time,end_time,end_day_offset,fee,venue,dj,status,core_complete)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid,item["name"],"MILONGA",item["date"],item["time"],None,0,
                 int(item["fee_verified"]) if item.get("fee_verified") else None,item["venue"],None,
                 "VERIFIED" if i==1 else "POSSIBLE",1))
            link_candidate_to_instance(con,eid,cur.lastrowid,sid)
        con.execute("""INSERT INTO acquisition_runs(post_id,source_id,source_url,mode,status,http_status,final_url,content_type,body_chars,image_count,poster_candidate_count,started_at,finished_at,error_code,error)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (1,"SRC-F-001","https://snapshot.local/metrics/1","snapshot","FAILED",403,"https://snapshot.local/metrics/1","text/html",0,0,0,now,now,"ACCESS_DENIED","403"))
        con.execute("""INSERT INTO acquisition_runs(post_id,source_id,source_url,mode,status,http_status,final_url,content_type,body_chars,image_count,poster_candidate_count,started_at,finished_at,error_code,error)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (2,"SRC-D-001","https://snapshot.local/metrics/2","snapshot","FULL",200,"https://snapshot.local/metrics/2","text/html",100,1,1,now,now,None,None))
        con.execute("""INSERT INTO recovery_queue(post_id,source_id,event_hint,reason,state,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?)""",(1,"SRC-F-001","PISTA","ACCESS_DENIED","RESOLVED",now,now))
        con.commit()
        rows=calculate_metrics_v2(con,"snapshot")
        out=ROOT/"data"/"reports"/"evidence-metrics-v2-report-v0.12.json"
        out.write_text(json.dumps({"version":"0.12","rows":rows},ensure_ascii=False,indent=2),encoding="utf-8")
        o=rows[0]
        print(json.dumps({"overall":o,"report":str(out)},ensure_ascii=False,indent=2))
        ok=(o["event_count"]==2 and o["field_total"]==8 and o["field_verified"]==7 and o["field_expected"]==1
            and o["field_coverage_rate"]==0.875 and o["known_field_rate"]==1.0
            and o["expected_to_verified_promotion_rate"]==0.5 and o["source_yield_rate"]==1.0
            and o["access_failure_rate"]==0.5 and o["primary_recovery_success_rate"]==1.0)
        return 0 if ok else 1
    finally: con.close()

def cmd_evidence_metrics_v2():
    con=init_db(db_path())
    try:
        rows=calculate_metrics_v2(con,"runtime")
        out=ROOT/"data"/"reports"/"evidence-metrics-v2-runtime-v0.12.json"
        out.write_text(json.dumps({"version":"0.12","rows":rows},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"overall":rows[0],"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_day1_real_metrics():
    data=load_json(ROOT/"data"/"day1_real"/"2026-08-27.json")
    metrics=calculate_day1_real(data)
    out=ROOT/"data"/"reports"/"day1-real-metrics-v0.13.json"
    out.write_text(json.dumps({"version":"0.13","metrics":metrics},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"metrics":metrics,"report":str(out)},ensure_ascii=False,indent=2))
    return 0 if metrics["field_coverage_rate"]==0.75 and metrics["known_field_rate"]==0.9375 else 1


def cmd_observation_snapshot():
    con=init_db(db_path())
    try:
        data=load_json(ROOT/"data"/"observation_snapshots"/"observation-sample.json")
        for item in data["runs"]:
            oid=start_observation(con,run_type=item["run_type"],source_id=item["source_id"])
            finish_observation(con,oid,result_status="PASS",
                discovered_count=item.get("discovered",0),
                rawpost_new_count=item.get("raw_new",0),
                rawpost_duplicate_count=item.get("raw_dup",0),
                acquisition_attempt_count=item.get("acq_attempts",0),
                acquisition_success_count=item.get("acq_success",0),
                acquisition_failure_count=item.get("acq_fail",0),
                recovery_attempt_count=item.get("rec_attempts",0),
                recovery_success_count=item.get("rec_success",0))
        metrics=calculate_observation_metrics(con)
        out=ROOT/"data"/"reports"/"observation-metrics-v0.14.json"
        out.write_text(json.dumps({"version":"0.14","metrics":metrics},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"metrics":metrics,"report":str(out)},ensure_ascii=False,indent=2))
        o=metrics["overall"]
        ok=(o["discovered_count"]==6 and o["rawpost_new_count"]==4 and
            o["source_yield_rate"]==0.6667 and o["access_failure_rate"]==0.6 and
            o["recovery_success_rate"]==0.5)
        return 0 if ok else 1
    finally:
        con.close()

def cmd_observation_metrics():
    con=init_db(db_path())
    try:
        metrics=calculate_observation_metrics(con)
        out=ROOT/"data"/"reports"/"observation-runtime-v0.14.json"
        out.write_text(json.dumps({"version":"0.14","metrics":metrics},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"metrics":metrics,"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()


def cmd_lineage_snapshot():
    con=init_db(db_path())
    try:
        trace=run_lineage_snapshot(con)
        out=ROOT/"data"/"reports"/"lineage-snapshot-v0.15.json"
        out.write_text(json.dumps({"version":"0.15","trace":trace},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"trace":trace,"report":str(out)},ensure_ascii=False,indent=2))
        ok=(trace["lineage"]["status"]=="COMPLETE" and
            len(trace["runs"])==3 and
            [x["stage"] for x in trace["runs"]]==["DISCOVERY","ACQUISITION","RECOVERY"] and
            len(trace["posts"])==1 and len(trace["events"])==1 and
            trace["events"][0]["status"]=="VERIFIED")
        return 0 if ok else 1
    finally:
        con.close()

def cmd_lineage_trace(args):
    con=init_db(db_path())
    try:
        trace=lineage_trace(con,args.lineage_id)
        print(json.dumps(trace,ensure_ascii=False,indent=2))
        return 0 if trace["lineage"] else 1
    finally:
        con.close()

def cmd_live_lineage_snapshot():
    con=init_db(db_path())
    try:
        sources=load_json(ROOT/"config"/"sources.json"); seed_sources(con,sources)
        trace=run_live_lineage_snapshot(con,ROOT)
        out=ROOT/"data"/"reports"/"live-lineage-snapshot-v0.16.json"
        out.write_text(json.dumps({"version":"0.16","trace":trace},ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"trace":trace,"report":str(out)},ensure_ascii=False,indent=2))
        return 0 if (trace["lineage"]["status"]=="COMPLETE"
            and [x["stage"] for x in trace["runs"]]==["DISCOVERY","ACQUISITION","RECOVERY"]
            and len(trace["posts"])>=1 and len(trace["events"])>=1) else 1
    finally: con.close()


def cmd_lineage_status():
    con=init_db(db_path())
    try:
        rows=[dict(x) for x in con.execute("""SELECT l.lineage_id,l.root_run_type,l.root_source_id,l.status,
            l.final_event_instance_id,COUNT(DISTINCT rl.observation_id) run_count,
            COUNT(DISTINCT pl.post_id) post_count
            FROM observation_lineages l
            LEFT JOIN observation_run_links rl ON rl.lineage_id=l.lineage_id
            LEFT JOIN observation_post_links pl ON pl.lineage_id=l.lineage_id
            GROUP BY l.lineage_id ORDER BY l.created_at DESC""").fetchall()]
        print(json.dumps({"lineages":rows},ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_run_daily(args):
    con=init_db(db_path())
    try:
        t=run_daily(con,ROOT,run_date=args.date,mode=args.mode)
        print(json.dumps(t,ensure_ascii=False,indent=2))
        return 0 if t["daily_run"]["status"]=="PASS" else 1
    finally: con.close()

def cmd_daily_status():
    con=init_db(db_path())
    try:
        rows=[dict(r) for r in con.execute("""SELECT daily_run_id,run_date,mode,status,
          discovery_lineage_count,acquisition_run_count,recovery_run_count,
          metric_status,report_status,started_at,finished_at FROM daily_runs
          ORDER BY started_at DESC""").fetchall()]
        print(json.dumps({"daily_runs":rows},ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_operations_summary(args):
    con=init_db(db_path())
    try:
        ops=build_daily_operations_summary(con)
        run_date=args.date or datetime.now(timezone.utc).date().isoformat()
        out=ROOT/"data"/"reports"/f"operations-summary-{run_date}-v0.19.json"
        md=ROOT/"data"/"reports"/f"operations-summary-{run_date}-v0.19.md"
        out.write_text(json.dumps({"version":"0.19","date":run_date,"summary":ops},
                                  ensure_ascii=False,indent=2),encoding="utf-8")
        md.write_text(render_markdown(run_date=run_date,daily_run_id="AD-HOC",summary=ops),encoding="utf-8")
        print(json.dumps({"summary":ops,"json":str(out),"markdown":str(md)},ensure_ascii=False,indent=2))
        return 1 if ops["p0_count"] else 0
    finally: con.close()


def cmd_review_event(args):
    con=init_db(db_path())
    try:
        r=review_event(con,event_instance_id=args.event_id,action=args.action,
                       actor=args.actor,reason=args.reason,new_status=args.new_status,
                       evidence={"note":args.evidence} if args.evidence else None)
        r["p0_errors"]=validate_event_after_review(con,args.event_id)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 1 if r["p0_errors"] else 0
    finally: con.close()

def cmd_review_field(args):
    con=init_db(db_path())
    try:
        r=review_field(con,event_instance_id=args.event_id,field_name=args.field,
                       action=args.action,actor=args.actor,reason=args.reason,
                       new_value=args.value,new_confidence=args.confidence,
                       evidence={"note":args.evidence} if args.evidence else None)
        r["p0_errors"]=validate_event_after_review(con,args.event_id)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 1 if r["p0_errors"] else 0
    finally: con.close()

def cmd_review_recovery(args):
    con=init_db(db_path())
    try:
        r=review_recovery(con,recovery_id=args.recovery_id,action=args.action,
                          actor=args.actor,reason=args.reason,
                          evidence={"note":args.evidence} if args.evidence else None)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_review_audit(args):
    con=init_db(db_path())
    try:
        rows=[dict(r) for r in list_human_review_actions(con,args.limit)]
        print(json.dumps({"actions":rows},ensure_ascii=False,indent=2))
        return 0
    finally: con.close()


def cmd_review_metrics():
    con=init_db(db_path())
    try:
        metrics=calculate_human_review_metrics(con)
        out=ROOT/"data"/"reports"/"human-review-metrics-v0.21.json"
        out.write_text(json.dumps({"version":"0.21","metrics":metrics},
                                  ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"metrics":metrics,"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()

def cmd_correction_hotspots():
    con=init_db(db_path())
    try:
        result=analyze_correction_hotspots(con)
        out=ROOT/"data"/"reports"/"correction-hotspots-v0.22.json"
        out.write_text(json.dumps({"version":"0.22","analysis":result},
                                  ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"analysis":result,"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()

def cmd_improvement_backlog():
    con=init_db(db_path())
    try:
        result=recommend_improvement_backlog(con)
        out=ROOT/"data"/"reports"/"improvement-backlog-v0.23.json"
        out.write_text(json.dumps({"version":"0.23","result":result},
                                  ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"result":result,"report":str(out)},ensure_ascii=False,indent=2))
        return 0
    finally:
        con.close()


def cmd_backlog_sync(args):
    con=init_db(db_path())
    try:
        result=sync_recommended_backlog(con,opened_by=args.actor)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_backlog_list():
    con=init_db(db_path())
    try:
        print(json.dumps({"items":backlog_list(con)},ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_backlog_status(args):
    con=init_db(db_path())
    try:
        result=change_backlog_status(
            con,args.backlog_id,status=args.status,actor=args.actor,note=args.note,
            owner=args.owner,rejection_reason=args.rejection_reason
        )
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_backlog_effect(args):
    con=init_db(db_path())
    try:
        result=capture_backlog_effect(con,args.backlog_id,phase=args.phase)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_backlog_detail(args):
    con=init_db(db_path())
    try:
        result=backlog_detail(con,args.backlog_id)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result else 1
    finally: con.close()


def cmd_change_add(args):
    con=init_db(db_path())
    try:
        result=register_change(
            con,backlog_id=args.backlog_id,title=args.title,description=args.description,
            component=args.component,version_label=args.version,actor=args.actor
        )
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_change_list():
    con=init_db(db_path())
    try:
        print(json.dumps({"changes":list_changes(con)},ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_change_link(args):
    con=init_db(db_path())
    try:
        result=link_and_measure_change(
            con,change_id=args.change_id,daily_run_id=args.daily_run_id,
            relation=args.relation,baseline_daily_run_id=args.baseline_daily_run_id
        )
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    finally: con.close()

def cmd_change_detail(args):
    con=init_db(db_path())
    try:
        result=change_detail(con,args.change_id)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result else 1
    finally: con.close()

def cmd_snapshot_list():
    con=init_db(db_path())
    try:
        print(json.dumps({"snapshots":[dict(r) for r in list_daily_metric_snapshots(con)]},
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_snapshot_show(args):
    con=init_db(db_path())
    try:
        r=load_snapshot_payload(con,args.daily_run_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r else 1
    finally: con.close()

def cmd_snapshot_verify(args):
    con=init_db(db_path())
    try:
        r=verify_snapshot_integrity(con,args.daily_run_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r.get("valid") else 1
    finally: con.close()

def cmd_change_verdict(args):
    con=init_db(db_path())
    try:
        r=evaluate_change_effect(con,args.change_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_change_goal(args):
    con=init_db(db_path())
    try:
        profile,weights=metric_weights_for_change(con,args.change_id)
        print(json.dumps({"change_id":args.change_id,"goal_profile":profile,"metric_weights":weights},ensure_ascii=False,indent=2)); return 0
    finally: con.close()


def cmd_backlog_goal(args):
    con=init_db(db_path())
    try:
        row=backlog_row(con,args.backlog_id)
        if not row:
            print(json.dumps({"error":"backlog not found"},ensure_ascii=False)); return 1
        print(json.dumps({
            "backlog_id":args.backlog_id,
            "goal_profile":row["goal_profile"],
            "goal_weights":json.loads(row["goal_weights_json"] or "{}")
        },ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_adaptive_weight_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(profile_status(con,args.goal_profile),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_adaptive_weight_recompute(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recompute_adaptive_profile(con,args.goal_profile),ensure_ascii=False,indent=2)); return 0
    finally: con.close()


def cmd_shadow_agreement(args):
    con=init_db(db_path())
    try:
        result=adaptive_shadow_agreement_stats(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_shadow_safety(args):
    con=init_db(db_path())
    try:
        result=evaluate_shadow_safety(con,args.goal_profile,persist=True)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_shadow_safety_history(args):
    con=init_db(db_path())
    try:
        result=shadow_safety_history(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_rolling_shadow(args):
    con=init_db(db_path())
    try:
        result=evaluate_rolling_shadow_stability(
            con,args.goal_profile,persist=True,manage_candidate=True)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_rolling_shadow_history(args):
    con=init_db(db_path())
    try:
        result=rolling_shadow_history(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_candidates(args):
    con=init_db(db_path())
    try:
        result=promotion_candidates(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_review(args):
    con=init_db(db_path())
    try:
        result=review_promotion_candidate(
            con,candidate_id=args.candidate_id,decision=args.decision,
            reviewer=args.reviewer,reason=args.reason,
            max_canary_changes=args.max_canary_changes)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_reviews(args):
    con=init_db(db_path())
    try:
        result=promotion_review_history(con,args.candidate_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_leases(args):
    con=init_db(db_path())
    try:
        result=promotion_leases(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_lease_events(args):
    con=init_db(db_path())
    try:
        result=promotion_lease_events(con,args.lease_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_rollback(args):
    con=init_db(db_path())
    try:
        result=rollback_active_goal_lease(
            con,goal_profile=args.goal_profile,actor=args.actor,reason=args.reason)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_canary_outcome(args):
    con=init_db(db_path())
    try:
        result=evaluate_canary_outcome(con,args.lease_id,persist=True)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_canary_outcomes(args):
    con=init_db(db_path())
    try:
        result=canary_outcome_history(con,args.lease_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_final(args):
    con=init_db(db_path())
    try:
        result=final_promotion_decision(
            con,lease_id=args.lease_id,decision=args.decision,
            reviewer=args.reviewer,reason=args.reason,
            additional_changes=args.additional_changes)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_final_reviews(args):
    con=init_db(db_path())
    try:
        result=final_promotion_reviews(con,args.lease_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_full_promotions(args):
    con=init_db(db_path())
    try:
        result=full_promotions(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_full_promotion_rollback(args):
    con=init_db(db_path())
    try:
        result=rollback_active_full_promotion(
            con,goal_profile=args.goal_profile,actor=args.actor,reason=args.reason)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_promotion_guard(args):
    con=init_db(db_path())
    try:
        result=evaluate_post_promotion_guard(
            con,args.promotion_id,persist=True,enforce=not args.no_enforce)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_promotion_guards(args):
    con=init_db(db_path())
    try:
        result=post_promotion_guard_history(con,args.promotion_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_promotion_health(args):
    con=init_db(db_path())
    try:
        result=post_promotion_health(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_decision_quality_record(args):
    con=init_db(db_path())
    try:
        result=record_decision_quality(
            con,goal_profile=args.goal_profile,decision_outcome=args.outcome,
            event_truth=args.event_truth,decision_action=args.action,
            source_confidence=args.source_confidence,
            critical_error_type=args.critical_error,
            core_relevance=args.core_relevance,user_impact=args.user_impact,
            change_id=args.change_id,event_id=args.event_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_decision_quality(args):
    con=init_db(db_path())
    try:
        result=decision_quality_history(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_goal_relevance(args):
    con=init_db(db_path())
    try:
        result=evaluate_goal_relevance(con,args.goal_profile,persist=True)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_goal_relevance_history(args):
    con=init_db(db_path())
    try:
        result=goal_relevance_history(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_decision_evidence_scan(args):
    con=init_db(db_path())
    try:
        result=scan_automatic_evidence(con,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_decision_evidence_feedback(args):
    con=init_db(db_path())
    try:
        result=record_visit_feedback_evidence(
            con,event_instance_id=args.event_id,feedback=args.feedback,
            reviewer_source=args.source,goal_profile=args.goal_profile,note=args.note)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_decision_evidence_confirm(args):
    con=init_db(db_path())
    try:
        result=confirm_evidence(
            con,evidence_id=args.evidence_id,decision=args.decision,
            reviewer=args.reviewer,reason=args.reason)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_decision_evidence_list(args):
    con=init_db(db_path())
    try:
        result=evidence_list(con,args.status,args.goal_profile)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_decision_evidence_confirmations(args):
    con=init_db(db_path())
    try:
        result=confirmation_history(con,args.evidence_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_evidence_queue_evaluate(args):
    con=init_db(db_path())
    try:
        result=evaluate_evidence_priority_queue(
            con,apply_auto_resolution=not args.no_auto_expire)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_evidence_queue(args):
    con=init_db(db_path())
    try:
        result=priority_queue(con,args.status)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_evidence_queue_events(args):
    con=init_db(db_path())
    try:
        result=queue_event_history(con,args.evidence_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_evidence_clusters_resolve(args):
    con=init_db(db_path())
    try:
        result=resolve_clusters(con)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_evidence_clusters(args):
    con=init_db(db_path())
    try:
        result=cluster_list(con,args.status)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_root_cause_attribute(args):
    con=init_db(db_path())
    try:
        result=attribute_root_causes(con,actor=args.actor)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_root_causes(args):
    con=init_db(db_path())
    try:
        result=root_cause_list(con,args.cluster_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_root_cause_backlog_sync(args):
    con=init_db(db_path())
    try:
        result=sync_root_cause_backlog(con,actor=args.actor)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_cluster_closure_check(args):
    con=init_db(db_path())
    try:
        result=closure_check(con,args.cluster_id,actor=args.actor)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result["status"]=="READY_FOR_CLOSURE" else 1
    finally: con.close()

def cmd_cluster_close(args):
    con=init_db(db_path())
    try:
        result=close_cluster(
            con,args.cluster_id,actor=args.actor,reason=args.reason)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_cluster_closure_history(args):
    con=init_db(db_path())
    try:
        result=closure_history(con,args.cluster_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_reliability_refresh(args):
    con=init_db(db_path())
    try:
        result=recompute_all_profiles(con)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_reliability_profiles(args):
    con=init_db(db_path())
    try:
        result=reliability_profiles(con,args.source_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_reliability_observations(args):
    con=init_db(db_path())
    try:
        result=reliability_observations(con,args.source_id,args.rule_key)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_reliability_success(args):
    con=init_db(db_path())
    try:
        result=record_success(
            con,source_id=args.source_id,rule_key=args.rule_key,
            observation_key=args.observation_key,weight=args.weight,
            rationale=[args.reason] if args.reason else None)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_policy_evaluate(args):
    con=init_db(db_path())
    try:
        result=evaluate_verification_policy(
            con,decision_key=args.decision_key,event_instance_id=args.event_id,
            source_id=args.source_id,rule_key=args.rule_key,
            base_eligible=args.base_eligible,
            independent_source_count=args.independent_sources,
            human_confirmed=args.human_confirmed,
            existing_verified=args.existing_verified)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_policy_decisions(args):
    con=init_db(db_path())
    try:
        result=verification_decisions(con,args.source_id)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_canary_start(args):
    con=init_db(db_path())
    try:
        result=start_canary(
            con,source_id=args.source_id,rule_key=args.rule_key,
            max_decisions=args.max_decisions,approved_by=args.approved_by)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_canaries(args):
    con=init_db(db_path())
    try:
        print(json.dumps(canaries(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_canary_rollback(args):
    con=init_db(db_path())
    try:
        result=rollback_canary(
            con,canary_id=args.canary_id,actor=args.actor,reason=args.reason)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_canary_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(canary_events(con,args.canary_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_outcome_record(args):
    con=init_db(db_path())
    try:
        r=record_outcome(con,decision_id=args.decision_id,event_truth=args.event_truth,
                         confirmed_by=args.confirmed_by,outcome_key=args.outcome_key)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_outcomes(args):
    con=init_db(db_path())
    try:
        print(json.dumps(outcomes(con,args.canary_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_canary_safety(args):
    con=init_db(db_path())
    try:
        r=evaluate_canary_safety(con,args.canary_id)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0 if r["status"]=="READY_FOR_FINAL_REVIEW" else 1
    finally: con.close()

def cmd_preventive_canary_safety_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(safety_history(con,args.canary_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_final_review(args):
    con=init_db(db_path())
    try:
        r=final_review(con,canary_id=args.canary_id,decision=args.decision,
                       reviewer=args.reviewer,reason=args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_full_promotions(args):
    con=init_db(db_path())
    try:
        print(json.dumps(full_promotions(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_final_reviews(args):
    con=init_db(db_path())
    try:
        print(json.dumps(final_reviews(con,args.canary_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_full_rollback(args):
    con=init_db(db_path())
    try:
        r=rollback_full(con,promotion_id=args.promotion_id,actor=args.actor,reason=args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_full_runtime_guard(args):
    con=init_db(db_path())
    try:
        r=evaluate_runtime_guard(con,args.promotion_id)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0 if r["status"]!="BLOCKED" else 1
    finally: con.close()

def cmd_preventive_full_runtime_guards(args):
    con=init_db(db_path())
    try:
        print(json.dumps(guard_history(con,args.promotion_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_full_runtime_observations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(runtime_observations(con,args.promotion_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_full_runtime_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(guard_events(con,args.promotion_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recovery_cases(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recovery_cases(con,args.status),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recovery_root_cause(args):
    con=init_db(db_path())
    try:
        r=record_root_cause(con,recovery_case_id=args.recovery_case_id,
                            root_cause=args.root_cause,actor=args.actor)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recovery_remediation(args):
    con=init_db(db_path())
    try:
        r=record_remediation(con,recovery_case_id=args.recovery_case_id,
                             remediation_ref=args.remediation_ref,
                             actor=args.actor,notes=args.notes)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recovery_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_recovery(con,args.recovery_case_id)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0 if r["status"]=="READY_FOR_REQUALIFICATION" else 1
    finally: con.close()

def cmd_preventive_recovery_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recovery_evaluations(con,args.recovery_case_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recovery_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recovery_events(con,args.recovery_case_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_requalify(args):
    con=init_db(db_path())
    try:
        r=requalify(con,recovery_case_id=args.recovery_case_id,actor=args.actor)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recurrence_profiles(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recurrence_profiles(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recurrence_evaluate(args):
    con=init_db(db_path())
    try:
        r=recurrence_policy(con,args.recovery_case_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recurrence_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recurrence_evaluations(con,args.recovery_case_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recurrence_exception(args):
    con=init_db(db_path())
    try:
        r=approve_exception(con,recovery_case_id=args.recovery_case_id,
                            decision=args.decision,approved_by=args.approved_by,
                            reason=args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_recurrence_exceptions(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recurrence_exceptions(con,args.recovery_case_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_quarantines(args):
    con=init_db(db_path())
    try:
        print(json.dumps(quarantines(con,args.status),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_quarantine_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(quarantine_events(con,args.quarantine_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_reintegration_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_reintegration(con,args.quarantine_id)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0 if r["status"]=="READY_FOR_RELEASE_REVIEW" else 1
    finally: con.close()

def cmd_preventive_reintegration_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(reintegration_evaluations(con,args.quarantine_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_quarantine_release_review(args):
    con=init_db(db_path())
    try:
        r=release_review(con,quarantine_id=args.quarantine_id,
                         decision=args.decision,reviewer=args.reviewer,
                         reason=args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_preventive_quarantine_release_reviews(args):
    con=init_db(db_path())
    try:
        print(json.dumps(release_reviews(con,args.quarantine_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_alternative_route_plan(args):
    con=init_db(db_path())
    try:
        r=plan_alternative_route(
            con,event_instance_id=args.event_instance_id,
            quarantined_source_id=args.quarantined_source_id,
            rule_key=args.rule_key)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0 if r["route_status"]=="ROUTED_VERIFIED" else 1
    finally: con.close()

def cmd_alternative_route_evaluations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(route_evaluations(con,args.event_instance_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_alternative_route_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(route_events(con,args.route_evaluation_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_verification_continuity(args):
    con=init_db(db_path())
    try:
        r=continuity_metrics(
            con,source_id=args.source_id,rule_key=args.rule_key,
            persist=bool(args.source_id and args.rule_key))
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_verification_continuity_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(continuity_snapshots(con,args.source_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_source_relationship_add(args):
    con=init_db(db_path())
    try:
        r=register_relationship(
            con,source_id_a=args.source_id_a,source_id_b=args.source_id_b,
            relationship_type=args.relationship_type,confidence=args.confidence,
            provenance=args.provenance,reviewed_by=args.reviewed_by,
            reason=args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_source_relationships(args):
    con=init_db(db_path())
    try:
        print(json.dumps(relationships(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_evidence_fingerprint_add(args):
    con=init_db(db_path())
    try:
        r=register_fingerprint(
            con,event_instance_id=args.event_instance_id,source_id=args.source_id,
            content=args.content,content_hash=args.content_hash,
            poster_hash=args.poster_hash,canonical_url=args.canonical_url,
            origin_source_id=args.origin_source_id,
            fingerprint_method=args.fingerprint_method)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_evidence_fingerprints(args):
    con=init_db(db_path())
    try:
        print(json.dumps(fingerprints(con,args.event_instance_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_source_independence_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_pair(
            con,event_instance_id=args.event_instance_id,
            source_id_a=args.source_id_a,source_id_b=args.source_id_b,
            persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0 if r["independence_status"]=="INDEPENDENT" else 1
    finally: con.close()

def cmd_source_independence_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(independence_history(con,args.event_instance_id),
                         ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_cross_post_infer(args):
    con=init_db(db_path())
    try:
        r=infer_cross_post_cluster(con,args.event_instance_id,args.text_threshold)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_cross_post_clusters(args):
    con=init_db(db_path())
    try:
        print(json.dumps(clusters(con,args.event_instance_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_cross_post_review(args):
    con=init_db(db_path())
    try:
        r=review_cluster(con,args.cluster_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_origin_calibration(args):
    con=init_db(db_path())
    try:
        r=evaluate_calibration(
            con,baseline=args.baseline_text_threshold,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_origin_calibration_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(calibration_history(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_origin_review_queue(args):
    con=init_db(db_path())
    try:
        r=build_review_queue(con,persist=True)
        if args.band:
            r["items"]=[x for x in r["items"] if x["priority_band"]==args.band]
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_origin_review_priority_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(priority_history(con,args.cluster_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_candidate_create(args):
    con=init_db(db_path())
    try:
        r=create_candidate_from_latest_calibration(con)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_candidates(args):
    con=init_db(db_path())
    try:
        print(json.dumps(candidates(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_review(args):
    con=init_db(db_path())
    try:
        r=review_candidate(
            con,args.candidate_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_canary_start(args):
    con=init_db(db_path())
    try:
        r=start_canary(
            con,args.candidate_id,args.approved_by,args.max_assignments)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_canary_list(args):
    con=init_db(db_path())
    try:
        print(json.dumps(canaries(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_canary_outcome(args):
    con=init_db(db_path())
    try:
        r=record_canary_outcome(
            con,args.event_instance_id,args.cluster_id,args.outcome,
            critical=args.critical)
        print(json.dumps(r,ensure_ascii=False,indent=2) if r else "null")
        return 0
    finally: con.close()

def cmd_threshold_promote(args):
    con=init_db(db_path())
    try:
        r=promote_candidate(
            con,args.candidate_id,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_promotions(args):
    con=init_db(db_path())
    try:
        print(json.dumps(promotions(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_rollback(args):
    con=init_db(db_path())
    try:
        r=rollback_promotion(
            con,args.promotion_id,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_runtime_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(runtime_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_runtime_observe(args):
    con=init_db(db_path())
    try:
        r=observe_runtime_outcome(
            con,event_instance_id=args.event_instance_id,
            cluster_id=args.cluster_id,human_outcome=args.outcome,
            max_text_similarity=args.max_text_similarity,
            critical=args.critical,event_status=args.event_status)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_runtime_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(runtime_history(con,args.promotion_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_guard_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(evaluation_history(con,args.promotion_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_guard_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(runtime_guard_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_recovery_list(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recovery_cases(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_recovery_outcome(args):
    con=init_db(db_path())
    try:
        r=add_recovery_shadow_outcome(
            con,args.recovery_case_id,args.event_instance_id,args.outcome,args.notes)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_requalify(args):
    con=init_db(db_path())
    try:
        r=requalify_recovery(
            con,args.recovery_case_id,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_root_cause(args):
    con=init_db(db_path())
    try:
        r=attribute_root_cause(con,args.recovery_case_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_root_causes(args):
    con=init_db(db_path())
    try:
        print(json.dumps(root_causes(con,args.recovery_case_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_adaptive_requirement(args):
    con=init_db(db_path())
    try:
        r=build_adaptive_requirement(con,args.recovery_case_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_adaptive_requirements(args):
    con=init_db(db_path())
    try:
        print(json.dumps(requirements(con,args.recovery_case_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_remediation(args):
    con=init_db(db_path())
    try:
        r=submit_remediation(
            con,args.recovery_case_id,args.type,args.submitted_by,args.notes,args.ref)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_remediation_review(args):
    con=init_db(db_path())
    try:
        r=review_remediation(
            con,args.remediation_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_root_cause_review(args):
    con=init_db(db_path())
    try:
        r=review_root_cause(
            con,args.root_cause_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_adaptive_status(args):
    con=init_db(db_path())
    try:
        r=adaptive_requalification_status(con,args.recovery_case_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_recurrence_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recurrence_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_recurrence_profiles(args):
    con=init_db(db_path())
    try:
        print(json.dumps(threshold_recurrence_profiles(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_recurrence_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(threshold_recurrence_events(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_remediation_effectiveness_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_remediation_effectiveness(con,args.min_sustained_days)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_remediation_effectiveness_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(remediation_effectiveness_history(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_remediation_type_stats(args):
    con=init_db(db_path())
    try:
        print(json.dumps(remediation_type_stats(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_restrictions(args):
    con=init_db(db_path())
    try:
        print(json.dumps(threshold_restrictions(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_restriction_exceptions(args):
    con=init_db(db_path())
    try:
        print(json.dumps(restriction_exceptions(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_restriction_exception(args):
    con=init_db(db_path())
    try:
        r=grant_restriction_exception(
            con,args.restriction_id,args.decision,args.approved_by,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_restriction_release(args):
    con=init_db(db_path())
    try:
        r=release_restriction(
            con,args.restriction_id,args.released_by,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_scope_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(scope_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_scopes(args):
    con=init_db(db_path())
    try:
        if args.derive:
            derive_all_active_scopes(con)
        print(json.dumps(threshold_restriction_scopes(con,args.active_only),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_scope_derive(args):
    con=init_db(db_path())
    try:
        r=derive_scope_for_restriction(con,args.restriction_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_scope_override(args):
    con=init_db(db_path())
    try:
        r=override_scope(
            con,args.restriction_id,args.scope_type,args.reviewer,args.reason,
            source_id=args.source_id,platform=args.platform,rule_key=args.rule_key)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_scope_release(args):
    con=init_db(db_path())
    try:
        r=release_scope(con,args.scope_id,args.released_by,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_scope_routes(args):
    con=init_db(db_path())
    try:
        print(json.dumps(threshold_scope_routes(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_threshold_safe_alternative(args):
    con=init_db(db_path())
    try:
        candidates=[x for x in (args.candidates or "").split(",") if x]
        selected=[x for x in (args.selected or "").split(",") if x]
        r=evaluate_safe_alternative_path(
            con,event_instance_id=args.event_instance_id,rule_key=args.rule_key,
            trigger_source_id=args.trigger_source_id,
            candidate_source_ids=candidates,selected_source_ids=selected)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_evidence_add(args):
    con=init_db(db_path())
    try:
        r=add_scope_reintegration_evidence(
            con,args.scope_id,args.event_instance_id,args.outcome,
            human_confirmed=args.human_confirmed,
            alternative_quality_delta=args.alternative_quality_delta,
            false_corroboration=args.false_corroboration,
            missed_syndication=args.missed_syndication,
            notes=args.notes)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_evidence(args):
    con=init_db(db_path())
    try:
        print(json.dumps(scope_reintegration_evidence(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_scope_reintegration_gate(con,args.scope_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_evaluations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(scope_reintegration_evaluations(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_review(args):
    con=init_db(db_path())
    try:
        r=review_scope_reintegration(
            con,args.scope_id,args.evaluation_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_canary_start(args):
    con=init_db(db_path())
    try:
        r=start_scope_reintegration_canary(
            con,args.scope_id,args.evaluation_id,args.approved_by,args.max_assignments)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_canaries(args):
    con=init_db(db_path())
    try:
        print(json.dumps(scope_reintegration_canaries(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_canary_outcome(args):
    con=init_db(db_path())
    try:
        r=record_scope_reintegration_canary_outcome(
            con,args.canary_id,args.event_instance_id,args.outcome,
            human_confirmed=args.human_confirmed,
            false_corroboration=args.false_corroboration,
            missed_syndication=args.missed_syndication,
            reviewer=args.reviewer)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_release(args):
    con=init_db(db_path())
    try:
        r=final_scope_reintegration_release(
            con,args.canary_id,args.released_by,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_scope_reintegration_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(scope_reintegration_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_observe(args):
    con=init_db(db_path())
    try:
        base=None if args.base_correct=="unknown" else args.base_correct=="true"
        alt=None if args.alternative_correct=="unknown" else args.alternative_correct=="true"
        r=record_post_reintegration_observation(
            con,args.scope_id,args.event_instance_id,args.human_outcome,
            critical=args.critical,
            false_corroboration=args.false_corroboration,
            missed_syndication=args.missed_syndication,
            coverage_quality_delta=args.coverage_quality_delta,
            reintegrated_correct=args.reintegrated_correct,
            base_correct=base,alternative_correct=alt)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_observations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(post_reintegration_observations(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_guard(args):
    con=init_db(db_path())
    try:
        r=evaluate_post_reintegration_guard(con,args.scope_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_evaluations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(post_reintegration_evaluations(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_reisolations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(post_reintegration_reisolations(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_penalty(args):
    con=init_db(db_path())
    try:
        print(json.dumps(post_reintegration_requirement_penalty(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_reisolation_clear(args):
    con=init_db(db_path())
    try:
        r=clear_post_reintegration_reisolation(
            con,args.reisolation_id,args.cleared_by,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(post_reintegration_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_root_cause(args):
    con=init_db(db_path())
    try:
        r=attribute_post_reintegration_root_cause(con,args.reisolation_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_root_causes(args):
    con=init_db(db_path())
    try:
        print(json.dumps(post_reintegration_root_causes(con,args.reisolation_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_remediation_routes(args):
    con=init_db(db_path())
    try:
        print(json.dumps(post_reintegration_remediation_routes(con,args.reisolation_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_root_review(args):
    con=init_db(db_path())
    try:
        r=review_post_reintegration_root_cause(
            con,args.post_root_cause_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_remediation_route(args):
    con=init_db(db_path())
    try:
        r=latest_post_reintegration_route_for_scope(con,args.scope_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_post_reintegration_root_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(post_reintegration_root_cause_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_plan_create(args):
    con=init_db(db_path())
    try:
        r=create_architecture_plan(con,args.scope_id,args.created_by,args.rationale)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_plans(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_plans(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_plan_review(args):
    con=init_db(db_path())
    try:
        r=approve_architecture_plan(
            con,args.plan_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_step_complete(args):
    con=init_db(db_path())
    try:
        r=complete_architecture_step(
            con,args.plan_id,args.step_order,args.remediation_id,
            args.completed_by,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_evidence_add(args):
    con=init_db(db_path())
    try:
        r=add_architecture_validation_evidence(
            con,args.plan_id,args.event_instance_id,args.outcome,
            human_confirmed=args.human_confirmed,
            false_corroboration=args.false_corroboration,
            missed_syndication=args.missed_syndication,
            quality_delta=args.quality_delta)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_plan_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_architecture_plan(con,args.plan_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_final_review(args):
    con=init_db(db_path())
    try:
        r=review_architecture_plan(
            con,args.plan_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_gate(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_gate_for_scope(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_escalation_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_runtime_outcomes(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_runtime_outcomes(con,args.scope_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_effectiveness(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_effectiveness_profiles(con,args.root_cause_type),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_recommendations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_recommendations(con,args.root_cause_type),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_memory_recommend(args):
    con=init_db(db_path())
    try:
        defaults=[x for x in args.default_steps.split(",") if x]
        blocked=[x for x in (args.blocked_types or "").split(",") if x]
        r=recommend_architecture_plan(
            con,args.root_cause_type,defaults,blocked,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_runtime_sustain(args):
    con=init_db(db_path())
    try:
        r=maybe_mark_architecture_sustained(con,args.runtime_outcome_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_memory_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_memory_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_comparative_scores(args):
    con=init_db(db_path())
    try:
        ctx=architecture_context_for_scope(con,args.scope_id)
        r=architecture_comparative_scores(
            con,args.root_cause_type,ctx,persist=True)
        print(json.dumps({"context":ctx,"scores":r},ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_context_recommend(args):
    con=init_db(db_path())
    try:
        ctx=architecture_context_for_scope(con,args.scope_id)
        defaults=[x for x in args.default_steps.split(",") if x]
        blocked=[x for x in (args.blocked_types or "").split(",") if x]
        r=recommend_contextual_architecture_plan(
            con,args.root_cause_type,ctx,defaults,blocked,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_comparative_history(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            architecture_comparative_score_history(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_context_recommendations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            architecture_context_recommendation_history(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_ranking_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_ranking_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_challenges(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            architecture_recommendation_challenges(con,args.scope_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_challenge_shadow(args):
    con=init_db(db_path())
    try:
        r=add_architecture_challenge_shadow_outcome(
            con,args.challenge_id,args.event_instance_id,
            args.recommended_outcome,args.deterministic_outcome,
            human_confirmed=args.human_confirmed,
            recommended_quality_delta=args.recommended_quality_delta,
            deterministic_quality_delta=args.deterministic_quality_delta)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_challenge_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_architecture_challenge(con,args.challenge_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_challenge_decide(args):
    con=init_db(db_path())
    try:
        r=architecture_challenge_human_decision(
            con,args.challenge_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_challenge_runtime(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            architecture_challenge_runtime_results(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_recommendation_quality(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            architecture_recommendation_quality_profiles(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_architecture_challenge_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(architecture_challenge_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_recommendation_policy_candidate(
            con,args.root_cause_type,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_candidates(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_policy_candidates(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_states(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_policy_states(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_review(args):
    con=init_db(db_path())
    try:
        r=review_recommendation_policy_candidate(
            con,args.candidate_id,args.decision,args.reviewer,args.reason,args.canary_max)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_final_review(args):
    con=init_db(db_path())
    try:
        r=final_recommendation_policy_review(
            con,args.root_cause_type,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_rollback(args):
    con=init_db(db_path())
    try:
        r=rollback_recommendation_policy(
            con,args.root_cause_type,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_assignments(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_policy_assignments(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_policy_events(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_policy_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_policy_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_cases(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_recovery_cases(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_remediation_add(args):
    con=init_db(db_path())
    try:
        r=add_recommendation_recovery_remediation(
            con,args.case_id,args.remediation_type,args.remediation_ref,
            args.submitted_by,args.notes)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_remediation_review(args):
    con=init_db(db_path())
    try:
        r=review_recommendation_recovery_remediation(
            con,args.remediation_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_evidence_add(args):
    con=init_db(db_path())
    try:
        r=add_recommendation_recovery_evidence(
            con,args.case_id,args.challenge_id,args.verdict,
            args.human_confirmed,args.notes)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_recommendation_recovery(con,args.case_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_review(args):
    con=init_db(db_path())
    try:
        r=review_recommendation_recanary(
            con,args.case_id,args.decision,args.reviewer,args.reason,
            args.canary_max,args.architecture_exception)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_recovery_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_version_register(args):
    con=init_db(db_path())
    try:
        r=register_recommendation_algorithm_version(
            con,args.root_cause_type,args.version_label,args.created_by,args.notes,
            parent_algorithm_version_id=args.parent_version_id,
            code_ref=args.code_ref,config_ref=args.config_ref,
            fingerprint=args.fingerprint,status=args.status)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_versions(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_algorithm_versions(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_current(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            current_recommendation_algorithm_version(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_lineage(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_algorithm_lineage(
                con,args.algorithm_version_id,args.entity_type,args.entity_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_algorithm_version_events(con,args.algorithm_version_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_version_propose(args):
    con=init_db(db_path())
    try:
        r=propose_recovery_successor_algorithm_version(
            con,args.case_id,args.version_label,args.created_by,
            args.remediation_id,args.notes,args.code_ref,args.config_ref)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_version_approve(args):
    con=init_db(db_path())
    try:
        r=approve_recovery_successor_algorithm_version(
            con,args.case_id,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_recovery_version_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps({
            "links":recommendation_recovery_version_links(con,args.case_id),
            "successor_check":
                recommendation_recovery_successor_ready(con,args.case_id)
                if args.case_id is not None else None
        },ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_versioning_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_algorithm_versioning_status(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_version_cohorts(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_algorithm_version_cohorts(
                con,args.algorithm_version_id,args.context_signature),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_version_profiles(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_algorithm_version_profiles(con,args.algorithm_version_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_version_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_recommendation_algorithm_version(
            con,args.algorithm_version_id,args.context_signature,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_version_evaluations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_algorithm_version_evaluations(con,args.algorithm_version_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_algorithm_version_cohort_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_algorithm_version_cohort_status(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_promotion_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_recommendation_version_promotion_gate(
            con,args.algorithm_version_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_promotion_review(args):
    con=init_db(db_path())
    try:
        r=review_recommendation_version_promotion(
            con,args.algorithm_version_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_promotion_ready(args):
    con=init_db(db_path())
    try:
        r=recommendation_version_promotion_ready(con,args.algorithm_version_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_promotion_gates(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_version_promotion_gates(con,args.algorithm_version_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_supersede_comparisons(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_version_supersede_comparisons(con,args.algorithm_version_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_promotion_reviews(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_version_promotion_reviews(con,args.algorithm_version_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_promotion_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_version_promotion_events(con,args.algorithm_version_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_promotion_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_version_promotion_status(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_supersede_guard_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_recommendation_version_fallback(
            con,args.root_cause_type,args.challenge_id,args.verdict,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_supersede_guard_evaluations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_supersede_guard_evaluations(con,args.algorithm_version_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_version_fallbacks(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_version_fallbacks(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_supersede_guard_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_supersede_guard_events(con,args.root_cause_type),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_supersede_guard_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_supersede_guard_status(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_verification_generations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_verification_generations(con,args.root_cause_type),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_verification_observations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_verification_observations(con,args.generation_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_pair_profiles(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_pair_profiles(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_verification_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_verification_events(con,args.generation_id),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_verification_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_verification_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_profiles(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_family_profiles(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_reviews(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_family_reviews(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_review(args):
    con=init_db(db_path())
    try:
        r=review_recommendation_fallback_family(
            con,args.family_profile_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_family_events(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(recommendation_fallback_family_status(con),ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_recovery_cases(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_recovery_cases(con,args.family_profile_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_add(args):
    con=init_db(db_path())
    try:
        r=add_recommendation_fallback_family_remediation(
            con,args.case_id,args.remediation_type,args.remediation_ref,
            args.submitted_by,args.notes)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_review(args):
    con=init_db(db_path())
    try:
        r=review_recommendation_fallback_family_remediation(
            con,args.remediation_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_candidate_set(args):
    con=init_db(db_path())
    try:
        r=set_recommendation_fallback_family_candidate(
            con,args.case_id,args.algorithm_version_id,args.actor,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_evidence_add(args):
    con=init_db(db_path())
    try:
        r=add_recommendation_fallback_family_evidence(
            con,args.case_id,args.challenge_id,args.verdict,
            args.human_confirmed,args.notes)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_recovery_evaluate(args):
    con=init_db(db_path())
    try:
        r=evaluate_recommendation_fallback_family_recovery(
            con,args.case_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_rearm_review(args):
    con=init_db(db_path())
    try:
        r=review_recommendation_fallback_family_rearm(
            con,args.case_id,args.decision,args.reviewer,args.reason)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_recovery_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_recovery_status(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_generation_outcomes(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_generation_outcomes(con,args.family_signature),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_effectiveness_profiles(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_effectiveness_profiles(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_generation_sustain(args):
    con=init_db(db_path())
    try:
        r=evaluate_recommendation_fallback_family_generation_sustained(
            con,args.outcome_id,args.now)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_memory(args):
    con=init_db(db_path())
    try:
        r=recommendation_fallback_family_remediation_allowed(
            con,args.family_signature,args.remediation_type,args.remediation_ref)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_generation_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_generation_events(con,args.outcome_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_memory_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_memory_status(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_rank(args):
    con=init_db(db_path())
    try:
        r=rank_recommendation_fallback_family_remediations(
            con,args.case_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_recommend(args):
    con=init_db(db_path())
    try:
        r=recommend_recommendation_fallback_family_remediation(
            con,args.case_id,persist=True)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_rankings(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_remediation_rankings(con,args.case_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_recommendations(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_remediation_recommendations(con,args.case_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_select(args):
    con=init_db(db_path())
    try:
        r=review_recommendation_fallback_family_remediation_selection(
            con,args.case_id,args.decision,args.reviewer,args.reason,args.ranking_id)
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_selection_reviews(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_remediation_selection_reviews(con,args.case_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_remediation_ranking_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_remediation_ranking_events(con,args.case_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_ranking_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_ranking_status(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_recommendation_outcomes(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_recommendation_outcomes(con,args.family_signature),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_recommendation_effectiveness(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_recommendation_effectiveness_profiles(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_recommendation_outcome_events(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_recommendation_outcome_events(con,args.outcome_id),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def cmd_recommendation_fallback_family_recommendation_outcome_status(args):
    con=init_db(db_path())
    try:
        print(json.dumps(
            recommendation_fallback_family_recommendation_outcome_status(con),
            ensure_ascii=False,indent=2)); return 0
    finally: con.close()

def main():
    p=argparse.ArgumentParser(description="DanceMate Information Engine PoC v0.73")
    sub=p.add_subparsers(dest="command")
    sub.add_parser("fixture", help="run fixture regression")
    sub.add_parser("collect-daum-snapshot", help="replay Kakao API-shaped discovery snapshot")
    sub.add_parser("collect-daum", help="run live Kakao Daum Cafe Search API collector; requires KAKAO_REST_API_KEY")
    sub.add_parser("acquire-daum-snapshot", help="test FULL/PARTIAL post acquisition and recovery queue without network")
    sub.add_parser("acquire-daum", help="attempt full body/poster acquisition for METADATA_ONLY Daum posts")
    sub.add_parser("recover-cross-source-snapshot", help="resolve recovery queue against legacy Naver-shaped snapshots")
    sub.add_parser("collect-naver-snapshot", help="replay official Naver API-shaped Blog/Cafe search snapshots")
    sub.add_parser("collect-naver", help="run live Naver Blog/Cafe Search APIs; requires NAVER_CLIENT_ID/SECRET")
    sub.add_parser("recover-naver-snapshot", help="resolve recovery queue through Naver API-shaped snapshots")
    sub.add_parser("recover-naver", help="resolve recovery queue through live Naver Blog/Cafe Search APIs")
    sub.add_parser("acquire-naver-snapshot", help="test Naver Blog/Cafe full-body and poster acquisition with snapshots")
    sub.add_parser("acquire-naver", help="attempt full acquisition for Naver METADATA_ONLY posts")
    sub.add_parser("metrics", help="calculate Daum/Naver acquisition/recovery/human-review metrics")
    sub.add_parser("revision-snapshot", help="apply ORIGINAL -> UPDATE -> CANCELLATION lifecycle snapshot")
    sub.add_parser("freshness-miss-snapshot", help="record synthetic critical cancellation miss")
    sub.add_parser("gate1-14d", help="run 14-day Gate 1 validation against sample Ground Truth")
    sub.add_parser("gate1-14d-fail", help="run intentional P0 failure fixture")

    gtadd=sub.add_parser("gt-add", help="append one live Ground Truth event")
    gtadd.add_argument("--date",required=True)
    gtadd.add_argument("--name",required=True)
    gtadd.add_argument("--venue",required=True)
    gtadd.add_argument("--start",required=True)
    gtadd.add_argument("--end",default="")
    gtadd.add_argument("--fee",default="")
    gtadd.add_argument("--status",choices=["HELD","CANCELLED"],default="HELD")
    gtadd.add_argument("--evidence-url",default="")
    gtadd.add_argument("--notes",default="")

    gtstat=sub.add_parser("gt-status", help="update live Ground Truth status")
    gtstat.add_argument("--gt-id",required=True)
    gtstat.add_argument("--status",choices=["HELD","CANCELLED"],required=True)
    gtstat.add_argument("--notes",default="")

    ex=sub.add_parser("export-dm", help="export runtime EventInstances into live validation CSV")
    ex.add_argument("--date",default=None)

    rc=sub.add_parser("reconcile", help="show unmatched Ground Truth / DanceMate rows")
    rc.add_argument("--date",default=None)

    dr=sub.add_parser("daily-report", help="generate one-day validation report")
    dr.add_argument("--date",required=True)

    sub.add_parser("rolling-report", help="generate cumulative live validation report")
    sub.add_parser("evidence-model-snapshot", help="apply Evidence Model v0.2 to Day 1 candidates")
    sub.add_parser("evidence-p0-snapshot", help="verify EXPECTED_AS_VERIFIED P0 protection")
    sub.add_parser("poster-source-snapshot", help="verify media class and source authority/access models")
    sub.add_parser("evidence-metrics-v2-snapshot", help="verify Evidence Metrics v2")
    sub.add_parser("evidence-metrics-v2", help="calculate Evidence Metrics v2 from runtime DB")
    sub.add_parser("day1-real-metrics", help="calculate retained Day 1 real metrics")
    sub.add_parser("observation-snapshot", help="verify complete observation denominators")
    sub.add_parser("observation-metrics", help="calculate runtime observation metrics")
    sub.add_parser("lineage-snapshot", help="verify Discovery→Acquisition→Recovery→Event lineage")
    sub.add_parser("live-lineage-snapshot", help="verify lineage propagation through production paths")
    rd=sub.add_parser("run-daily", help="run Collect→Acquire→Recover→Metrics→Report")
    rd.add_argument("--date",default=None)
    rd.add_argument("--mode",choices=["snapshot","live"],default="snapshot")
    sub.add_parser("daily-status", help="list daily orchestrator runs")
    osum=sub.add_parser("operations-summary", help="generate operator-facing daily operations summary")
    osum.add_argument("--date",default=None)

    rev=sub.add_parser("review-event", help="review one event")
    rev.add_argument("--event-id",type=int,required=True)
    rev.add_argument("--action",choices=["APPROVE","MODIFY","REJECT","HOLD"],required=True)
    rev.add_argument("--new-status",default=None)
    rev.add_argument("--actor",default="operator")
    rev.add_argument("--reason",default=None)
    rev.add_argument("--evidence",default=None)

    rf=sub.add_parser("review-field", help="review one event field")
    rf.add_argument("--event-id",type=int,required=True)
    rf.add_argument("--field",required=True)
    rf.add_argument("--action",choices=["APPROVE","MODIFY","REJECT","HOLD"],required=True)
    rf.add_argument("--value",default=None)
    rf.add_argument("--confidence",choices=["VERIFIED","EXPECTED","INFERRED","CONFLICT","UNKNOWN"],default=None)
    rf.add_argument("--actor",default="operator")
    rf.add_argument("--reason",default=None)
    rf.add_argument("--evidence",default=None)

    rr=sub.add_parser("review-recovery", help="review one recovery item")
    rr.add_argument("--recovery-id",type=int,required=True)
    rr.add_argument("--action",choices=["APPROVE","MODIFY","REJECT","HOLD"],required=True)
    rr.add_argument("--actor",default="operator")
    rr.add_argument("--reason",default=None)
    rr.add_argument("--evidence",default=None)

    ra=sub.add_parser("review-audit", help="list human review audit trail")
    ra.add_argument("--limit",type=int,default=100)
    sub.add_parser("review-metrics", help="calculate human-in-the-loop quality metrics")
    sub.add_parser("correction-hotspots", help="analyze source/field correction hotspots")
    sub.add_parser("improvement-backlog", help="recommend development backlog from correction hotspots")

    bs=sub.add_parser("backlog-sync", help="persist recommended backlog items")
    bs.add_argument("--actor",default="system")
    sub.add_parser("backlog-list", help="list persisted improvement backlog items")

    bst=sub.add_parser("backlog-status", help="change backlog lifecycle status")
    bst.add_argument("--backlog-id",type=int,required=True)
    bst.add_argument("--status",choices=["OPEN","IN_PROGRESS","VERIFIED","REJECTED"],required=True)
    bst.add_argument("--actor",default="operator")
    bst.add_argument("--owner",default=None)
    bst.add_argument("--note",default=None)
    bst.add_argument("--rejection-reason",default=None)

    be=sub.add_parser("backlog-effect", help="capture BEFORE/AFTER effect metrics")
    be.add_argument("--backlog-id",type=int,required=True)
    be.add_argument("--phase",choices=["BEFORE","AFTER"],required=True)

    bd=sub.add_parser("backlog-detail", help="show backlog history and before/after effects")
    bd.add_argument("--backlog-id",type=int,required=True)

    ca=sub.add_parser("change-add", help="register an implementation/rule change")
    ca.add_argument("--backlog-id",type=int,default=None)
    ca.add_argument("--title",required=True)
    ca.add_argument("--description",default=None)
    ca.add_argument("--component",default=None)
    ca.add_argument("--version",default=None)
    ca.add_argument("--actor",default="operator")

    sub.add_parser("change-list", help="list registered changes")

    cl=sub.add_parser("change-link", help="link a change to a Daily Run and measure effect")
    cl.add_argument("--change-id",type=int,required=True)
    cl.add_argument("--daily-run-id",required=True)
    cl.add_argument("--relation",choices=["BASELINE","POST_CHANGE","VALIDATION"],default="POST_CHANGE")
    cl.add_argument("--baseline-daily-run-id",default=None)

    cd=sub.add_parser("change-detail", help="show Change→Daily Run→Metric trace")
    cd.add_argument("--change-id",type=int,required=True)
    cv=sub.add_parser("change-verdict", help="evaluate immutable BASELINE vs POST_CHANGE effect")
    cv.add_argument("--change-id",type=int,required=True)
    cg=sub.add_parser("change-goal", help="show inferred/explicit goal profile and metric weights")
    cg.add_argument("--change-id",type=int,required=True)
    bg=sub.add_parser("backlog-goal", help="show explicit goal profile stored on backlog")
    bg.add_argument("--backlog-id",type=int,required=True)
    aws=sub.add_parser("adaptive-weight-status", help="show adaptive weight foundation status")
    aws.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],required=True)
    awr=sub.add_parser("adaptive-weight-recompute", help="recompute conservative adaptive weight suggestion")
    awr.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],required=True)
    sa=sub.add_parser("shadow-agreement", help="show Base vs Adaptive Shadow verdict agreement")
    sa.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    ssafe=sub.add_parser("shadow-safety", help="evaluate Shadow Safety Gate and confusion matrix")
    ssafe.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    ssh=sub.add_parser("shadow-safety-history", help="show persisted Shadow Safety Gate evaluations")
    ssh.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    rs=sub.add_parser("rolling-shadow", help="evaluate rolling 7/14/30 Shadow Stability Gate")
    rs.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    rsh=sub.add_parser("rolling-shadow-history", help="show persisted rolling Shadow stability evaluations")
    rsh.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    pc=sub.add_parser("promotion-candidates", help="show Adaptive promotion candidates/revocations")
    pc.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    prv=sub.add_parser("promotion-review", help="human review of Adaptive promotion candidate")
    prv.add_argument("--candidate-id",type=int,required=True)
    prv.add_argument("--decision",choices=["APPROVE","REJECT","HOLD"],required=True)
    prv.add_argument("--reviewer",required=True)
    prv.add_argument("--reason",default=None)
    prv.add_argument("--max-canary-changes",type=int,default=5)
    prh=sub.add_parser("promotion-reviews", help="show promotion human review audit history")
    prh.add_argument("--candidate-id",type=int,default=None)
    pls=sub.add_parser("promotion-leases", help="show Adaptive canary promotion leases")
    pls.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    ple=sub.add_parser("promotion-lease-events", help="show promotion lease audit events")
    ple.add_argument("--lease-id",type=int,default=None)
    prb=sub.add_parser("promotion-rollback", help="manually rollback an active Adaptive canary lease")
    prb.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],required=True)
    prb.add_argument("--actor",required=True)
    prb.add_argument("--reason",required=True)
    co=sub.add_parser("canary-outcome", help="evaluate Canary Outcome Gate for one lease")
    co.add_argument("--lease-id",type=int,required=True)
    coh=sub.add_parser("canary-outcomes", help="show persisted Canary Outcome Gate history")
    coh.add_argument("--lease-id",type=int,default=None)
    pf=sub.add_parser("promotion-final", help="human final decision: PROMOTE, EXTEND, or ROLLBACK")
    pf.add_argument("--lease-id",type=int,required=True)
    pf.add_argument("--decision",choices=["PROMOTE","EXTEND","ROLLBACK"],required=True)
    pf.add_argument("--reviewer",required=True)
    pf.add_argument("--reason",default=None)
    pf.add_argument("--additional-changes",type=int,default=3)
    pfr=sub.add_parser("promotion-final-reviews", help="show final promotion decision audit history")
    pfr.add_argument("--lease-id",type=int,default=None)
    fp=sub.add_parser("full-promotions", help="show full Adaptive promotions")
    fp.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    fpr=sub.add_parser("full-promotion-rollback", help="rollback active full Adaptive promotion")
    fpr.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],required=True)
    fpr.add_argument("--actor",required=True)
    fpr.add_argument("--reason",required=True)
    ppg=sub.add_parser("post-promotion-guard", help="evaluate/enforce Full Promotion runtime drift guard")
    ppg.add_argument("--promotion-id",type=int,required=True)
    ppg.add_argument("--no-enforce",action="store_true")
    ppgh=sub.add_parser("post-promotion-guards", help="show Post-Promotion Guard history")
    ppgh.add_argument("--promotion-id",type=int,default=None)
    ph=sub.add_parser("promotion-health", help="show Goal Profile Full Promotion runtime health")
    ph.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    dqr=sub.add_parser("decision-quality-record", help="record Successful/Failed Dance Decision observation")
    dqr.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],required=True)
    dqr.add_argument("--outcome",choices=["SUCCESS","FAILURE","UNKNOWN"],required=True)
    dqr.add_argument("--event-truth",required=True)
    dqr.add_argument("--action",default=None)
    dqr.add_argument("--source-confidence",default=None)
    dqr.add_argument("--critical-error",choices=["FALSE_VERIFIED","CANCELLATION_MISS"],default=None)
    dqr.add_argument("--core-relevance",type=float,default=1.0)
    dqr.add_argument("--user-impact",type=float,default=1.0)
    dqr.add_argument("--change-id",type=int,default=None)
    dqr.add_argument("--event-id",type=int,default=None)
    dq=sub.add_parser("decision-quality", help="show Decision Quality observations")
    dq.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    gr=sub.add_parser("goal-relevance", help="evaluate Goal-Relevance / Decision Quality diagnostic")
    gr.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],required=True)
    grh=sub.add_parser("goal-relevance-history", help="show Goal-Relevance diagnostic history")
    grh.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    des=sub.add_parser("decision-evidence-scan", help="scan lifecycle/review data for Decision Outcome Evidence candidates")
    des.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default="FIELD_QUALITY")
    defb=sub.add_parser("decision-evidence-feedback", help="record visit feedback as pending Decision Outcome Evidence")
    defb.add_argument("--event-id",type=int,required=True)
    defb.add_argument("--feedback",choices=["VISITED_HELD","ARRIVED_NO_EVENT","CANCELLED_BEFORE_VISIT"],required=True)
    defb.add_argument("--source",default="USER_FEEDBACK")
    defb.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default="FIELD_QUALITY")
    defb.add_argument("--note",default=None)
    dec=sub.add_parser("decision-evidence-confirm", help="CONFIRM/REJECT/HOLD pending Decision Outcome Evidence")
    dec.add_argument("--evidence-id",type=int,required=True)
    dec.add_argument("--decision",choices=["CONFIRM","REJECT","HOLD"],required=True)
    dec.add_argument("--reviewer",required=True)
    dec.add_argument("--reason",default=None)
    deli=sub.add_parser("decision-evidence-list", help="list Decision Outcome Evidence")
    deli.add_argument("--status",choices=["PENDING","HOLD","CONFIRMED","REJECTED","EXPIRED"],default=None)
    deli.add_argument("--goal-profile",choices=["FIELD_QUALITY","SOURCE_ACCESS","RECOVERY","BALANCED"],default=None)
    dech=sub.add_parser("decision-evidence-confirmations", help="show Decision Outcome confirmation audit")
    dech.add_argument("--evidence-id",type=int,default=None)
    eqe=sub.add_parser("evidence-queue-evaluate", help="evaluate priority/SLA/corroboration/expiry for pending evidence")
    eqe.add_argument("--no-auto-expire",action="store_true")
    eql=sub.add_parser("evidence-queue", help="show prioritized Decision Outcome Evidence queue")
    eql.add_argument("--status",choices=["PENDING","HOLD","CONFIRMED","REJECTED","EXPIRED"],default=None)
    eqev=sub.add_parser("evidence-queue-events", help="show priority/SLA/auto-resolution audit events")
    eqev.add_argument("--evidence-id",type=int,default=None)
    ecr=sub.add_parser("evidence-clusters-resolve", help="group Decision Outcome Evidence into resolvable cases")
    ecl=sub.add_parser("evidence-clusters", help="list Evidence Cluster cases")
    ecl.add_argument("--status",choices=["OPEN","CONFIRMED_CASE","CONFLICT","DISMISSED","EXPIRED"],default=None)
    rca=sub.add_parser("root-cause-attribute", help="derive conservative Root-Cause attribution for confirmed clusters")
    rca.add_argument("--actor",default="root-cause-engine")
    rcl=sub.add_parser("root-causes", help="list Root-Cause attributions")
    rcl.add_argument("--cluster-id",type=int,default=None)
    rcbs=sub.add_parser("root-cause-backlog-sync", help="create/link remediation backlog for repeated confirmed critical Root Causes")
    rcbs.add_argument("--actor",default="root-cause-engine")
    ccc=sub.add_parser("cluster-closure-check", help="run critical Case closure gate")
    ccc.add_argument("--cluster-id",type=int,required=True)
    ccc.add_argument("--actor",default="closure-gate")
    cclose=sub.add_parser("cluster-close", help="human-close a case after READY_FOR_CLOSURE")
    cclose.add_argument("--cluster-id",type=int,required=True)
    cclose.add_argument("--actor",required=True)
    cclose.add_argument("--reason",default=None)
    cch=sub.add_parser("cluster-closure-history", help="show Case closure-gate audit history")
    cch.add_argument("--cluster-id",type=int,default=None)
    rfr=sub.add_parser("reliability-refresh", help="derive confirmed critical failures and recompute internal Source/Rule Reliability")
    rfp=sub.add_parser("reliability-profiles", help="show internal Source/Rule Reliability profiles")
    rfp.add_argument("--source-id",default=None)
    rfo=sub.add_parser("reliability-observations", help="show Reliability observations")
    rfo.add_argument("--source-id",default=None)
    rfo.add_argument("--rule-key",default=None)
    rfs=sub.add_parser("reliability-success", help="record one confirmed successful Source/Rule verification")
    rfs.add_argument("--source-id",required=True)
    rfs.add_argument("--rule-key",required=True)
    rfs.add_argument("--observation-key",required=True)
    rfs.add_argument("--weight",type=float,default=1.0)
    rfs.add_argument("--reason",default=None)
    pve=sub.add_parser("preventive-policy-evaluate", help="evaluate Base vs preventive Shadow/Canary verification action for a new event")
    pve.add_argument("--decision-key",required=True)
    pve.add_argument("--event-id",type=int,default=None)
    pve.add_argument("--source-id",required=True)
    pve.add_argument("--rule-key",required=True)
    pve.add_argument("--base-eligible",action="store_true")
    pve.add_argument("--independent-sources",type=int,default=1)
    pve.add_argument("--human-confirmed",action="store_true")
    pve.add_argument("--existing-verified",action="store_true")
    pvd=sub.add_parser("preventive-policy-decisions", help="show preventive verification Shadow/Canary decisions")
    pvd.add_argument("--source-id",default=None)
    pcs=sub.add_parser("preventive-canary-start", help="human-approve a preventive verification Canary after Shadow evidence")
    pcs.add_argument("--source-id",required=True)
    pcs.add_argument("--rule-key",required=True)
    pcs.add_argument("--max-decisions",type=int,default=5)
    pcs.add_argument("--approved-by",required=True)
    sub.add_parser("preventive-canaries", help="show preventive policy Canary leases")
    pcr=sub.add_parser("preventive-canary-rollback", help="rollback a preventive policy Canary")
    pcr.add_argument("--canary-id",type=int,required=True)
    pcr.add_argument("--actor",required=True)
    pcr.add_argument("--reason",required=True)
    pce=sub.add_parser("preventive-canary-events", help="show preventive Canary audit events")
    pce.add_argument("--canary-id",type=int,default=None)
    por=sub.add_parser("preventive-outcome-record", help="record human-confirmed Ground Truth for a preventive decision")
    por.add_argument("--decision-id",type=int,required=True)
    por.add_argument("--event-truth",choices=["EVENT_OCCURRED","HELD","CANCELLED","EVENT_DID_NOT_OCCUR"],required=True)
    por.add_argument("--confirmed-by",required=True)
    por.add_argument("--outcome-key",default=None)
    pol=sub.add_parser("preventive-outcomes", help="show preventive policy outcome evidence")
    pol.add_argument("--canary-id",type=int,default=None)
    pcsf=sub.add_parser("preventive-canary-safety", help="evaluate Canary Outcome Safety Gate")
    pcsf.add_argument("--canary-id",type=int,required=True)
    pcsh=sub.add_parser("preventive-canary-safety-history", help="show Canary Safety Gate history")
    pcsh.add_argument("--canary-id",type=int,default=None)
    pfr=sub.add_parser("preventive-final-review", help="human final PROMOTE/ROLLBACK/HOLD decision")
    pfr.add_argument("--canary-id",type=int,required=True)
    pfr.add_argument("--decision",choices=["PROMOTE","ROLLBACK","HOLD"],required=True)
    pfr.add_argument("--reviewer",required=True)
    pfr.add_argument("--reason",default=None)
    sub.add_parser("preventive-full-promotions", help="show Full Preventive promotions")
    pfrs=sub.add_parser("preventive-final-reviews", help="show final review audit")
    pfrs.add_argument("--canary-id",type=int,default=None)
    pfrr=sub.add_parser("preventive-full-rollback", help="rollback active Full Preventive promotion")
    pfrr.add_argument("--promotion-id",type=int,required=True)
    pfrr.add_argument("--actor",required=True)
    pfrr.add_argument("--reason",required=True)
    pfg=sub.add_parser("preventive-full-runtime-guard", help="evaluate Full Preventive runtime guard and fail-closed rollback if unsafe")
    pfg.add_argument("--promotion-id",type=int,required=True)
    pfgh=sub.add_parser("preventive-full-runtime-guards", help="show Full Preventive runtime guard history")
    pfgh.add_argument("--promotion-id",type=int,default=None)
    pfgo=sub.add_parser("preventive-full-runtime-observations", help="show Full Preventive runtime outcome observations")
    pfgo.add_argument("--promotion-id",type=int,default=None)
    pfge=sub.add_parser("preventive-full-runtime-events", help="show Full Preventive runtime guard audit events")
    pfge.add_argument("--promotion-id",type=int,default=None)
    prc=sub.add_parser("preventive-recovery-cases", help="show Runtime Rollback recovery/re-qualification cases")
    prc.add_argument("--status",default=None)
    prr=sub.add_parser("preventive-recovery-root-cause", help="record human-reviewed Root Cause for a recovery case")
    prr.add_argument("--recovery-case-id",type=int,required=True)
    prr.add_argument("--root-cause",required=True)
    prr.add_argument("--actor",required=True)
    prm=sub.add_parser("preventive-recovery-remediation", help="record remediation reference for a recovery case")
    prm.add_argument("--recovery-case-id",type=int,required=True)
    prm.add_argument("--remediation-ref",required=True)
    prm.add_argument("--actor",required=True)
    prm.add_argument("--notes",default=None)
    pre=sub.add_parser("preventive-recovery-evaluate", help="evaluate Recovery Evidence Window")
    pre.add_argument("--recovery-case-id",type=int,required=True)
    prh=sub.add_parser("preventive-recovery-history", help="show Recovery Gate evaluation history")
    prh.add_argument("--recovery-case-id",type=int,default=None)
    prev=sub.add_parser("preventive-recovery-events", help="show Recovery audit events")
    prev.add_argument("--recovery-case-id",type=int,default=None)
    prq=sub.add_parser("preventive-requalify", help="human re-qualify a recovered Source/Rule before a new Canary")
    prq.add_argument("--recovery-case-id",type=int,required=True)
    prq.add_argument("--actor",required=True)
    prp=sub.add_parser("preventive-recurrence-profiles", help="show Source/Rule recurrence risk profiles")
    pree=sub.add_parser("preventive-recurrence-evaluate", help="evaluate recurrence risk and escalated recovery thresholds")
    pree.add_argument("--recovery-case-id",type=int,required=True)
    prhi=sub.add_parser("preventive-recurrence-history", help="show recurrence evaluation history")
    prhi.add_argument("--recovery-case-id",type=int,default=None)
    prex=sub.add_parser("preventive-recurrence-exception", help="human APPROVE/DENY exception for restricted recurrence")
    prex.add_argument("--recovery-case-id",type=int,required=True)
    prex.add_argument("--decision",choices=["APPROVE","DENY"],required=True)
    prex.add_argument("--approved-by",required=True)
    prex.add_argument("--reason",required=True)
    prexs=sub.add_parser("preventive-recurrence-exceptions", help="show recurrence exception audit")
    prexs.add_argument("--recovery-case-id",type=int,default=None)
    pqs=sub.add_parser("preventive-quarantines", help="show Source/Rule quarantine states")
    pqs.add_argument("--status",default=None)
    pqe=sub.add_parser("preventive-quarantine-events", help="show quarantine audit events")
    pqe.add_argument("--quarantine-id",type=int,default=None)
    prie=sub.add_parser("preventive-reintegration-evaluate", help="evaluate controlled reintegration gate")
    prie.add_argument("--quarantine-id",type=int,required=True)
    prih=sub.add_parser("preventive-reintegration-history", help="show reintegration gate history")
    prih.add_argument("--quarantine-id",type=int,default=None)
    pqrr=sub.add_parser("preventive-quarantine-release-review", help="human APPROVE/DENY/HOLD quarantine release")
    pqrr.add_argument("--quarantine-id",type=int,required=True)
    pqrr.add_argument("--decision",choices=["APPROVE","DENY","HOLD"],required=True)
    pqrr.add_argument("--reviewer",required=True)
    pqrr.add_argument("--reason",required=True)
    pqrrs=sub.add_parser("preventive-quarantine-release-reviews", help="show quarantine release review audit")
    pqrrs.add_argument("--quarantine-id",type=int,default=None)
    arp=sub.add_parser("alternative-route-plan", help="plan a safe alternative source route for a quarantined Source/Rule")
    arp.add_argument("--event-instance-id",type=int,required=True)
    arp.add_argument("--quarantined-source-id",required=True)
    arp.add_argument("--rule-key",required=True)
    are=sub.add_parser("alternative-route-evaluations", help="show persisted alternative route evaluations")
    are.add_argument("--event-instance-id",type=int,default=None)
    arv=sub.add_parser("alternative-route-events", help="show alternative route audit events")
    arv.add_argument("--route-evaluation-id",type=int,default=None)
    vcm=sub.add_parser("verification-continuity", help="measure VERIFIED continuity while Source/Rule is quarantined")
    vcm.add_argument("--source-id",default=None)
    vcm.add_argument("--rule-key",default=None)
    vch=sub.add_parser("verification-continuity-history", help="show continuity metric snapshots")
    vch.add_argument("--source-id",default=None)
    sra=sub.add_parser("source-relationship-add", help="register explicit Source independence/relationship evidence")
    sra.add_argument("--source-id-a",required=True)
    sra.add_argument("--source-id-b",required=True)
    sra.add_argument("--relationship-type",choices=["INDEPENDENT","RELATED","SYNDICATED","UNKNOWN"],required=True)
    sra.add_argument("--confidence",choices=["LOW","MEDIUM","HIGH"],default="HIGH")
    sra.add_argument("--provenance",default="HUMAN_REVIEW")
    sra.add_argument("--reviewed-by",default=None)
    sra.add_argument("--reason",default=None)
    sub.add_parser("source-relationships", help="show Source Independence Graph edges")

    efa=sub.add_parser("evidence-fingerprint-add", help="register Event/Source origin fingerprint")
    efa.add_argument("--event-instance-id",type=int,required=True)
    efa.add_argument("--source-id",required=True)
    efa.add_argument("--content",default=None)
    efa.add_argument("--content-hash",default=None)
    efa.add_argument("--poster-hash",default=None)
    efa.add_argument("--canonical-url",default=None)
    efa.add_argument("--origin-source-id",default=None)
    efa.add_argument("--fingerprint-method",default="MANUAL_OR_DERIVED")
    efs=sub.add_parser("evidence-fingerprints", help="show Event/Source origin fingerprints")
    efs.add_argument("--event-instance-id",type=int,default=None)

    sie=sub.add_parser("source-independence-evaluate", help="evaluate a Source pair for independent corroboration")
    sie.add_argument("--event-instance-id",type=int,required=True)
    sie.add_argument("--source-id-a",required=True)
    sie.add_argument("--source-id-b",required=True)
    sih=sub.add_parser("source-independence-history", help="show pairwise independence evaluation audit")
    sih.add_argument("--event-instance-id",type=int,default=None)
    cpi=sub.add_parser("cross-post-infer", help="infer near-duplicate cross-post clusters in Shadow mode")
    cpi.add_argument("--event-instance-id",type=int,required=True)
    cpi.add_argument("--text-threshold",type=float,default=None)
    cps=sub.add_parser("cross-post-clusters", help="show inferred cross-post clusters")
    cps.add_argument("--event-instance-id",type=int,default=None)
    cpr=sub.add_parser("cross-post-review", help="human confirm/clear an inferred cross-post cluster")
    cpr.add_argument("--cluster-id",type=int,required=True)
    cpr.add_argument("--decision",choices=["CONFIRM_SYNDICATION","CONFIRM_INDEPENDENT","HOLD"],required=True)
    cpr.add_argument("--reviewer",required=True)
    cpr.add_argument("--reason",required=True)
    ocal=sub.add_parser("origin-calibration", help="evaluate Human-reviewed Cross-Post precision and Shadow threshold recommendation")
    ocal.add_argument("--baseline-text-threshold",type=float,default=.86)
    sub.add_parser("origin-calibration-history", help="show immutable Origin calibration snapshots")
    orq=sub.add_parser("origin-review-queue", help="rank AUTO_SUSPECTED_SYNDICATION clusters for Human Review")
    orq.add_argument("--band",choices=["P1","P2","P3"],default=None)
    orh=sub.add_parser("origin-review-priority-history", help="show persisted Human Review priority snapshots")
    orh.add_argument("--cluster-id",type=int,default=None)
    sub.add_parser("threshold-candidate-create", help="create a promotion candidate from latest Shadow calibration")
    sub.add_parser("threshold-candidates", help="show Origin threshold promotion candidates")
    thr=sub.add_parser("threshold-review", help="Human review a threshold candidate before Canary")
    thr.add_argument("--candidate-id",type=int,required=True)
    thr.add_argument("--decision",choices=["APPROVE_CANARY","REJECT","HOLD"],required=True)
    thr.add_argument("--reviewer",required=True)
    thr.add_argument("--reason",required=True)
    tcs=sub.add_parser("threshold-canary-start", help="start a bounded Human-approved threshold Canary")
    tcs.add_argument("--candidate-id",type=int,required=True)
    tcs.add_argument("--approved-by",required=True)
    tcs.add_argument("--max-assignments",type=int,default=3)
    sub.add_parser("threshold-canary-list", help="show threshold Canary state and assignments")
    tco=sub.add_parser("threshold-canary-outcome", help="record explicit Canary outcome including missed syndication")
    tco.add_argument("--event-instance-id",type=int,required=True)
    tco.add_argument("--cluster-id",type=int,default=None)
    tco.add_argument("--outcome",choices=["CONFIRM_SYNDICATION","CONFIRM_INDEPENDENT","HOLD","MISSED_SYNDICATION"],required=True)
    tco.add_argument("--critical",action="store_true")
    tp=sub.add_parser("threshold-promote", help="Human promote a successfully completed threshold Canary")
    tp.add_argument("--candidate-id",type=int,required=True)
    tp.add_argument("--reviewer",required=True)
    tp.add_argument("--reason",required=True)
    sub.add_parser("threshold-promotions", help="show threshold Full promotion history")
    tr=sub.add_parser("threshold-rollback", help="Human rollback an active Full threshold promotion")
    tr.add_argument("--promotion-id",type=int,required=True)
    tr.add_argument("--reviewer",required=True)
    tr.add_argument("--reason",required=True)
    sub.add_parser("threshold-runtime-status", help="show Base/Canary/Full Origin threshold runtime state")
    tro=sub.add_parser("threshold-runtime-observe", help="record post-Full-promotion Human outcome and evaluate rolling drift guard")
    tro.add_argument("--event-instance-id",type=int,required=True)
    tro.add_argument("--cluster-id",type=int,default=None)
    tro.add_argument("--outcome",choices=["CONFIRM_SYNDICATION","CONFIRM_INDEPENDENT"],required=True)
    tro.add_argument("--max-text-similarity",type=float,required=True)
    tro.add_argument("--event-status",default=None)
    tro.add_argument("--critical",action="store_true")
    trh=sub.add_parser("threshold-runtime-history", help="show post-promotion Human outcome observations")
    trh.add_argument("--promotion-id",type=int,default=None)
    tgh=sub.add_parser("threshold-guard-history", help="show rolling 5/10/20 threshold guard evaluations")
    tgh.add_argument("--promotion-id",type=int,default=None)
    sub.add_parser("threshold-guard-status", help="show active Full-promotion drift guard and recovery state")
    sub.add_parser("threshold-recovery-list", help="show threshold runtime recovery cases")
    trco=sub.add_parser("threshold-recovery-outcome", help="record one Shadow recovery outcome after fail-closed rollback")
    trco.add_argument("--recovery-case-id",type=int,required=True)
    trco.add_argument("--event-instance-id",type=int,required=True)
    trco.add_argument("--outcome",choices=["SAFE","UNSAFE","HOLD"],required=True)
    trco.add_argument("--notes",default=None)
    trq=sub.add_parser("threshold-requalify", help="Human requalify a runtime-rolled-back threshold after safe Shadow recovery")
    trq.add_argument("--recovery-case-id",type=int,required=True)
    trq.add_argument("--reviewer",required=True)
    trq.add_argument("--reason",required=True)
    trc=sub.add_parser("threshold-root-cause", help="attribute deterministic root cause for threshold runtime recovery")
    trc.add_argument("--recovery-case-id",type=int,required=True)
    trcs=sub.add_parser("threshold-root-causes", help="show threshold recovery root-cause history")
    trcs.add_argument("--recovery-case-id",type=int,default=None)
    tar=sub.add_parser("threshold-adaptive-requirement", help="build risk-adaptive requalification requirement")
    tar.add_argument("--recovery-case-id",type=int,required=True)
    tars=sub.add_parser("threshold-adaptive-requirements", help="show adaptive threshold recovery requirements")
    tars.add_argument("--recovery-case-id",type=int,default=None)
    trem=sub.add_parser("threshold-remediation", help="submit documented remediation for threshold recovery")
    trem.add_argument("--recovery-case-id",type=int,required=True)
    trem.add_argument("--type",choices=["THRESHOLD_CHANGE","SOURCE_RULE_CHANGE","INDEPENDENCE_GRAPH_FIX","COLLECTOR_FIX","DATA_QUALITY_FIX","OTHER"],required=True)
    trem.add_argument("--submitted-by",required=True)
    trem.add_argument("--notes",required=True)
    trem.add_argument("--ref",default=None)
    trmr=sub.add_parser("threshold-remediation-review", help="Human evaluate whether submitted remediation was effective")
    trmr.add_argument("--remediation-id",type=int,required=True)
    trmr.add_argument("--decision",choices=["EFFECTIVE","INEFFECTIVE","HOLD"],required=True)
    trmr.add_argument("--reviewer",required=True)
    trmr.add_argument("--reason",required=True)
    trcr=sub.add_parser("threshold-root-cause-review", help="Human confirm/reject/hold attributed threshold root cause")
    trcr.add_argument("--root-cause-id",type=int,required=True)
    trcr.add_argument("--decision",choices=["CONFIRM","REJECT","HOLD"],required=True)
    trcr.add_argument("--reviewer",required=True)
    trcr.add_argument("--reason",required=True)
    tas=sub.add_parser("threshold-adaptive-status", help="evaluate adaptive recovery/requalification readiness")
    tas.add_argument("--recovery-case-id",type=int,required=True)
    sub.add_parser("threshold-recurrence-status", help="show long-term threshold root-cause recurrence and remediation effectiveness status")
    sub.add_parser("threshold-recurrence-profiles", help="show root-cause recurrence profiles")
    sub.add_parser("threshold-recurrence-events", help="show recurrence event history")
    ree=sub.add_parser("remediation-effectiveness-evaluate", help="mark EFFECTIVE_PENDING remediation as sustained after a no-recurrence window")
    ree.add_argument("--min-sustained-days",type=float,default=30)
    sub.add_parser("remediation-effectiveness-history", help="show remediation effectiveness longitudinal history")
    sub.add_parser("remediation-type-stats", help="show remediation type sustained/recurrence-failure statistics")
    sub.add_parser("threshold-restrictions", help="show long-term threshold restrictions")
    sub.add_parser("threshold-restriction-exceptions", help="show Human restriction exception history")
    tre=sub.add_parser("threshold-restriction-exception", help="Human approve/deny/hold one promotion attempt under active long-term restriction")
    tre.add_argument("--restriction-id",type=int,required=True)
    tre.add_argument("--decision",choices=["APPROVE","DENY","HOLD"],required=True)
    tre.add_argument("--approved-by",required=True)
    tre.add_argument("--reason",required=True)
    trrel=sub.add_parser("threshold-restriction-release", help="Human release a long-term threshold restriction")
    trrel.add_argument("--restriction-id",type=int,required=True)
    trrel.add_argument("--released-by",required=True)
    trrel.add_argument("--reason",required=True)
    sub.add_parser("threshold-scope-status", help="show active scoped/global restriction isolation and safe-route audit")
    ts=sub.add_parser("threshold-scopes", help="show restriction scopes")
    ts.add_argument("--active-only",action="store_true")
    ts.add_argument("--derive",action="store_true")
    tsd=sub.add_parser("threshold-scope-derive", help="derive isolation scope for one active long-term restriction")
    tsd.add_argument("--restriction-id",type=int,required=True)
    tso=sub.add_parser("threshold-scope-override", help="Human override restriction isolation scope")
    tso.add_argument("--restriction-id",type=int,required=True)
    tso.add_argument("--scope-type",choices=["GLOBAL_THRESHOLD","SOURCE","PLATFORM","RULE","SOURCE_RULE"],required=True)
    tso.add_argument("--source-id",default=None)
    tso.add_argument("--platform",default=None)
    tso.add_argument("--rule-key",default=None)
    tso.add_argument("--reviewer",required=True)
    tso.add_argument("--reason",required=True)
    tsr=sub.add_parser("threshold-scope-release", help="Human release one isolation scope")
    tsr.add_argument("--scope-id",type=int,required=True)
    tsr.add_argument("--released-by",required=True)
    tsr.add_argument("--reason",required=True)
    sub.add_parser("threshold-scope-routes", help="show scoped safe-alternative route evaluations")
    tsa=sub.add_parser("threshold-safe-alternative", help="diagnose safe alternative evidence after scope isolation")
    tsa.add_argument("--event-instance-id",type=int,required=True)
    tsa.add_argument("--rule-key",required=True)
    tsa.add_argument("--trigger-source-id",default=None)
    tsa.add_argument("--candidates",required=True,help="comma-separated source IDs")
    tsa.add_argument("--selected",default="",help="comma-separated selected source IDs")
    sre=sub.add_parser("scope-reintegration-evidence-add", help="record scoped Shadow/Human evidence for reintegration gate")
    sre.add_argument("--scope-id",type=int,required=True)
    sre.add_argument("--event-instance-id",type=int,required=True)
    sre.add_argument("--outcome",choices=["SAFE","UNSAFE","HOLD"],required=True)
    sre.add_argument("--human-confirmed",action="store_true")
    sre.add_argument("--alternative-quality-delta",type=float,default=None)
    sre.add_argument("--false-corroboration",action="store_true")
    sre.add_argument("--missed-syndication",action="store_true")
    sre.add_argument("--notes",default=None)
    srel=sub.add_parser("scope-reintegration-evidence", help="show scoped reintegration evidence")
    srel.add_argument("--scope-id",type=int,default=None)
    sreg=sub.add_parser("scope-reintegration-evaluate", help="evaluate scoped reintegration safety/coverage gate")
    sreg.add_argument("--scope-id",type=int,required=True)
    sregs=sub.add_parser("scope-reintegration-evaluations", help="show scoped reintegration gate history")
    sregs.add_argument("--scope-id",type=int,default=None)
    srr=sub.add_parser("scope-reintegration-review", help="Human approve/reject/hold scoped reintegration canary")
    srr.add_argument("--scope-id",type=int,required=True)
    srr.add_argument("--evaluation-id",type=int,required=True)
    srr.add_argument("--decision",choices=["APPROVE_CANARY","REJECT","HOLD"],required=True)
    srr.add_argument("--reviewer",required=True)
    srr.add_argument("--reason",required=True)
    srcs=sub.add_parser("scope-reintegration-canary-start", help="start bounded scoped reintegration canary")
    srcs.add_argument("--scope-id",type=int,required=True)
    srcs.add_argument("--evaluation-id",type=int,required=True)
    srcs.add_argument("--approved-by",required=True)
    srcs.add_argument("--max-assignments",type=int,default=3)
    srcl=sub.add_parser("scope-reintegration-canaries", help="show scoped reintegration canaries")
    srcl.add_argument("--scope-id",type=int,default=None)
    srco=sub.add_parser("scope-reintegration-canary-outcome", help="record Human outcome for one scoped reintegration canary Event")
    srco.add_argument("--canary-id",type=int,required=True)
    srco.add_argument("--event-instance-id",type=int,required=True)
    srco.add_argument("--outcome",choices=["SAFE","UNSAFE","HOLD"],required=True)
    srco.add_argument("--human-confirmed",action="store_true")
    srco.add_argument("--false-corroboration",action="store_true")
    srco.add_argument("--missed-syndication",action="store_true")
    srco.add_argument("--reviewer",default="operator")
    srf=sub.add_parser("scope-reintegration-release", help="Human final release after fully safe scoped reintegration canary")
    srf.add_argument("--canary-id",type=int,required=True)
    srf.add_argument("--released-by",required=True)
    srf.add_argument("--reason",required=True)
    sub.add_parser("scope-reintegration-status", help="show scoped reintegration gate/canary status")
    pro=sub.add_parser("post-reintegration-observe", help="record Human outcome after scoped full reintegration release")
    pro.add_argument("--scope-id",type=int,required=True)
    pro.add_argument("--event-instance-id",type=int,required=True)
    pro.add_argument("--human-outcome",choices=["SAFE","UNSAFE","HOLD"],required=True)
    pro.add_argument("--critical",action="store_true")
    pro.add_argument("--false-corroboration",action="store_true")
    pro.add_argument("--missed-syndication",action="store_true")
    pro.add_argument("--coverage-quality-delta",type=float,default=None)
    pro.add_argument("--reintegrated-correct",action=argparse.BooleanOptionalAction,default=True)
    pro.add_argument("--base-correct",choices=["true","false","unknown"],default="unknown")
    pro.add_argument("--alternative-correct",choices=["true","false","unknown"],default="unknown")
    proh=sub.add_parser("post-reintegration-observations", help="show post-reintegration runtime observations")
    proh.add_argument("--scope-id",type=int,default=None)
    prg=sub.add_parser("post-reintegration-guard", help="evaluate rolling 5/10/20 post-reintegration runtime guard")
    prg.add_argument("--scope-id",type=int,required=True)
    preg=sub.add_parser("post-reintegration-evaluations", help="show post-reintegration rolling guard history")
    preg.add_argument("--scope-id",type=int,default=None)
    pris=sub.add_parser("post-reintegration-reisolations", help="show automatic scope re-isolation history")
    pris.add_argument("--scope-id",type=int,default=None)
    prp=sub.add_parser("post-reintegration-penalty", help="show strengthened next reintegration requirements after re-isolation")
    prp.add_argument("--scope-id",type=int,required=True)
    prc=sub.add_parser("post-reintegration-reisolation-clear", help="Human clear re-isolation marker; scope still follows normal reintegration policy")
    prc.add_argument("--reisolation-id",type=int,required=True)
    prc.add_argument("--cleared-by",required=True)
    prc.add_argument("--reason",required=True)
    sub.add_parser("post-reintegration-status", help="show post-reintegration runtime guard and re-isolation status")
    prc=sub.add_parser("post-reintegration-root-cause", help="attribute root cause for one automatic scope re-isolation")
    prc.add_argument("--reisolation-id",type=int,required=True)
    prcs=sub.add_parser("post-reintegration-root-causes", help="show post-reintegration root-cause history")
    prcs.add_argument("--reisolation-id",type=int,default=None)
    prr=sub.add_parser("post-reintegration-remediation-routes", help="show root-cause-specific remediation routing history")
    prr.add_argument("--reisolation-id",type=int,default=None)
    prrv=sub.add_parser("post-reintegration-root-review", help="Human confirm/reject/hold post-reintegration root cause")
    prrv.add_argument("--post-root-cause-id",type=int,required=True)
    prrv.add_argument("--decision",choices=["CONFIRM","REJECT","HOLD"],required=True)
    prrv.add_argument("--reviewer",required=True)
    prrv.add_argument("--reason",required=True)
    prroute=sub.add_parser("post-reintegration-remediation-route", help="show required remediation route for active re-isolated scope")
    prroute.add_argument("--scope-id",type=int,required=True)
    sub.add_parser("post-reintegration-root-status", help="show post-reintegration root-cause/remediation-routing status")
    apc=sub.add_parser("architecture-plan-create", help="create cross-layer remediation plan for architecture-escalated scope")
    apc.add_argument("--scope-id",type=int,required=True)
    apc.add_argument("--created-by",required=True)
    apc.add_argument("--rationale",required=True)
    apl=sub.add_parser("architecture-plans", help="show cross-layer architecture remediation plans")
    apl.add_argument("--scope-id",type=int,default=None)
    apr=sub.add_parser("architecture-plan-review", help="Human approve/reject/hold architecture remediation plan")
    apr.add_argument("--plan-id",type=int,required=True)
    apr.add_argument("--decision",choices=["APPROVE","REJECT","HOLD"],required=True)
    apr.add_argument("--reviewer",required=True)
    apr.add_argument("--reason",required=True)
    asc=sub.add_parser("architecture-step-complete", help="complete one architecture plan step with an EFFECTIVE remediation")
    asc.add_argument("--plan-id",type=int,required=True)
    asc.add_argument("--step-order",type=int,required=True)
    asc.add_argument("--remediation-id",type=int,required=True)
    asc.add_argument("--completed-by",required=True)
    asc.add_argument("--reason",required=True)
    aea=sub.add_parser("architecture-evidence-add", help="add cross-layer Shadow/Human validation evidence")
    aea.add_argument("--plan-id",type=int,required=True)
    aea.add_argument("--event-instance-id",type=int,required=True)
    aea.add_argument("--outcome",choices=["SAFE","UNSAFE","HOLD"],required=True)
    aea.add_argument("--human-confirmed",action="store_true")
    aea.add_argument("--false-corroboration",action="store_true")
    aea.add_argument("--missed-syndication",action="store_true")
    aea.add_argument("--quality-delta",type=float,default=None)
    ape=sub.add_parser("architecture-plan-evaluate", help="evaluate cross-layer remediation plan validation gate")
    ape.add_argument("--plan-id",type=int,required=True)
    afr=sub.add_parser("architecture-final-review", help="Human architecture review after cross-layer validation")
    afr.add_argument("--plan-id",type=int,required=True)
    afr.add_argument("--decision",choices=["APPROVE_REINTEGRATION","REJECT","HOLD"],required=True)
    afr.add_argument("--reviewer",required=True)
    afr.add_argument("--reason",required=True)
    ag=sub.add_parser("architecture-gate", help="show architecture escalation gate for active scope")
    ag.add_argument("--scope-id",type=int,required=True)
    sub.add_parser("architecture-status", help="show architecture escalation plans/status")
    aro=sub.add_parser("architecture-runtime-outcomes", help="show long-term runtime outcomes of released architecture plans")
    aro.add_argument("--scope-id",type=int,default=None)
    aep=sub.add_parser("architecture-effectiveness", help="show root-cause/plan-signature effectiveness memory")
    aep.add_argument("--root-cause-type",default=None)
    arl=sub.add_parser("architecture-recommendations", help="show architecture plan recommendation history")
    arl.add_argument("--root-cause-type",default=None)
    arm=sub.add_parser("architecture-memory-recommend", help="recommend cross-layer plan from longitudinal evidence with low-data fallback")
    arm.add_argument("--root-cause-type",required=True)
    arm.add_argument("--default-steps",required=True,help="comma-separated deterministic fallback steps")
    arm.add_argument("--blocked-types",default="")
    ars=sub.add_parser("architecture-runtime-sustain", help="evaluate one active architecture runtime outcome for sustained success")
    ars.add_argument("--runtime-outcome-id",type=int,required=True)
    sub.add_parser("architecture-memory-status", help="show architecture plan runtime/effectiveness memory status")
    acs=sub.add_parser("architecture-comparative-scores", help="compare historical architecture plans for one current scope context")
    acs.add_argument("--root-cause-type",required=True)
    acs.add_argument("--scope-id",type=int,required=True)
    acr=sub.add_parser("architecture-context-recommend", help="recommend architecture plan using context-aware conservative comparative ranking")
    acr.add_argument("--root-cause-type",required=True)
    acr.add_argument("--scope-id",type=int,required=True)
    acr.add_argument("--default-steps",required=True,help="comma-separated deterministic fallback steps")
    acr.add_argument("--blocked-types",default="")
    ach=sub.add_parser("architecture-comparative-history", help="show comparative score audit history")
    ach.add_argument("--root-cause-type",default=None)
    arx=sub.add_parser("architecture-context-recommendations", help="show context-aware recommendation history")
    arx.add_argument("--root-cause-type",default=None)
    sub.add_parser("architecture-ranking-status", help="show comparative ranking and context recommendation status")
    achl=sub.add_parser("architecture-challenges", help="show recommendation-vs-deterministic Shadow challenges")
    achl.add_argument("--scope-id",type=int,default=None)
    achs=sub.add_parser("architecture-challenge-shadow", help="record one Human-confirmed Shadow comparison outcome")
    achs.add_argument("--challenge-id",type=int,required=True)
    achs.add_argument("--event-instance-id",type=int,required=True)
    achs.add_argument("--recommended-outcome",choices=["SAFE","UNSAFE","HOLD"],required=True)
    achs.add_argument("--deterministic-outcome",choices=["SAFE","UNSAFE","HOLD"],required=True)
    achs.add_argument("--human-confirmed",action="store_true")
    achs.add_argument("--recommended-quality-delta",type=float,default=None)
    achs.add_argument("--deterministic-quality-delta",type=float,default=None)
    ache=sub.add_parser("architecture-challenge-evaluate", help="evaluate recommendation Shadow challenge")
    ache.add_argument("--challenge-id",type=int,required=True)
    achd=sub.add_parser("architecture-challenge-decide", help="Human accept recommendation, choose baseline, hold, or reject")
    achd.add_argument("--challenge-id",type=int,required=True)
    achd.add_argument("--decision",choices=["ACCEPT_RECOMMENDATION","CHOOSE_BASELINE","HOLD","REJECT"],required=True)
    achd.add_argument("--reviewer",required=True)
    achd.add_argument("--reason",required=True)
    sub.add_parser("architecture-challenge-runtime", help="show runtime outcomes linked to Human challenge choices")
    sub.add_parser("architecture-recommendation-quality", help="show recommendation algorithm acceptance/helpfulness profiles")
    sub.add_parser("architecture-challenge-status", help="show recommendation challenge status and quality")
    rpe=sub.add_parser("recommendation-policy-evaluate", help="evaluate Root-Cause recommendation algorithm for policy promotion")
    rpe.add_argument("--root-cause-type",required=True)
    rpc=sub.add_parser("recommendation-policy-candidates", help="show recommendation policy promotion candidates")
    rpc.add_argument("--root-cause-type",default=None)
    sub.add_parser("recommendation-policy-states", help="show Root-Cause recommendation policy modes")
    rpr=sub.add_parser("recommendation-policy-review", help="Human review promotion candidate and optionally start limited policy canary")
    rpr.add_argument("--candidate-id",type=int,required=True)
    rpr.add_argument("--decision",choices=["APPROVE_CANARY","REJECT","HOLD"],required=True)
    rpr.add_argument("--reviewer",required=True)
    rpr.add_argument("--reason",required=True)
    rpr.add_argument("--canary-max",type=int,default=3)
    rpf=sub.add_parser("recommendation-policy-final-review", help="Human final promote/reject/hold after policy canary")
    rpf.add_argument("--root-cause-type",required=True)
    rpf.add_argument("--decision",choices=["PROMOTE","REJECT","HOLD"],required=True)
    rpf.add_argument("--reviewer",required=True)
    rpf.add_argument("--reason",required=True)
    rpb=sub.add_parser("recommendation-policy-rollback", help="Human force recommendation algorithm rollback to deterministic baseline")
    rpb.add_argument("--root-cause-type",required=True)
    rpb.add_argument("--reviewer",required=True)
    rpb.add_argument("--reason",required=True)
    rpa=sub.add_parser("recommendation-policy-assignments", help="show limited recommendation policy canary assignments")
    rpa.add_argument("--root-cause-type",default=None)
    rpev=sub.add_parser("recommendation-policy-events", help="show recommendation policy promotion/rollback audit events")
    rpev.add_argument("--root-cause-type",default=None)
    sub.add_parser("recommendation-policy-status", help="show recommendation policy promotion gate/canary/rollback status")
    rrc=sub.add_parser("recommendation-recovery-cases", help="show recommendation policy rollback recovery cases")
    rrc.add_argument("--root-cause-type",default=None)
    rra=sub.add_parser("recommendation-recovery-remediation-add", help="submit fresh recommendation algorithm remediation")
    rra.add_argument("--case-id",type=int,required=True)
    rra.add_argument("--remediation-type",required=True)
    rra.add_argument("--remediation-ref",required=True)
    rra.add_argument("--submitted-by",required=True)
    rra.add_argument("--notes",default="")
    rrr=sub.add_parser("recommendation-recovery-remediation-review", help="Human review rollback remediation effectiveness")
    rrr.add_argument("--remediation-id",type=int,required=True)
    rrr.add_argument("--decision",choices=["EFFECTIVE","INEFFECTIVE","HOLD"],required=True)
    rrr.add_argument("--reviewer",required=True)
    rrr.add_argument("--reason",required=True)
    rre=sub.add_parser("recommendation-recovery-evidence-add", help="add fresh post-rollback Shadow challenge evidence")
    rre.add_argument("--case-id",type=int,required=True)
    rre.add_argument("--challenge-id",type=int,required=True)
    rre.add_argument("--verdict",choices=["RECOMMENDATION_HELPFUL","RECOMMENDATION_HARMFUL","NEUTRAL"],required=True)
    rre.add_argument("--human-confirmed",action="store_true")
    rre.add_argument("--notes",default="")
    rrev=sub.add_parser("recommendation-recovery-evaluate", help="evaluate strengthened rollback requalification gate")
    rrev.add_argument("--case-id",type=int,required=True)
    rrw=sub.add_parser("recommendation-recovery-review", help="Human approve/reject/hold re-canary after rollback recovery")
    rrw.add_argument("--case-id",type=int,required=True)
    rrw.add_argument("--decision",choices=["APPROVE_RECANARY","REJECT","HOLD"],required=True)
    rrw.add_argument("--reviewer",required=True)
    rrw.add_argument("--reason",required=True)
    rrw.add_argument("--canary-max",type=int,default=3)
    rrw.add_argument("--architecture-exception",action="store_true")
    sub.add_parser("recommendation-recovery-status", help="show rollback recovery/requalification status")
    rav=sub.add_parser("recommendation-algorithm-version-register", help="register immutable recommendation algorithm version")
    rav.add_argument("--root-cause-type",required=True)
    rav.add_argument("--version-label",required=True)
    rav.add_argument("--created-by",required=True)
    rav.add_argument("--notes",default="")
    rav.add_argument("--parent-version-id",type=int,default=None)
    rav.add_argument("--code-ref",default=None)
    rav.add_argument("--config-ref",default=None)
    rav.add_argument("--fingerprint",default=None)
    rav.add_argument("--status",choices=["DRAFT","SHADOW","CANARY","PROMOTED","FAILED","SUPERSEDED"],default="SHADOW")
    rvl=sub.add_parser("recommendation-algorithm-versions", help="list recommendation algorithm versions")
    rvl.add_argument("--root-cause-type",default=None)
    rvc=sub.add_parser("recommendation-algorithm-current", help="show current recommendation algorithm version for Root Cause")
    rvc.add_argument("--root-cause-type",required=True)
    rlin=sub.add_parser("recommendation-algorithm-lineage", help="show algorithm version lineage edges")
    rlin.add_argument("--algorithm-version-id",type=int,default=None)
    rlin.add_argument("--entity-type",default=None)
    rlin.add_argument("--entity-id",type=int,default=None)
    revt=sub.add_parser("recommendation-algorithm-events", help="show algorithm version lifecycle events")
    revt.add_argument("--algorithm-version-id",type=int,default=None)
    rvp=sub.add_parser("recommendation-recovery-version-propose", help="propose a distinct successor algorithm version after rollback")
    rvp.add_argument("--case-id",type=int,required=True)
    rvp.add_argument("--version-label",required=True)
    rvp.add_argument("--created-by",required=True)
    rvp.add_argument("--remediation-id",type=int,required=True)
    rvp.add_argument("--notes",default="")
    rvp.add_argument("--code-ref",default=None)
    rvp.add_argument("--config-ref",default=None)
    rva=sub.add_parser("recommendation-recovery-version-approve", help="Human approve successor algorithm version for re-canary")
    rva.add_argument("--case-id",type=int,required=True)
    rva.add_argument("--reviewer",required=True)
    rva.add_argument("--reason",required=True)
    rvst=sub.add_parser("recommendation-recovery-version-status", help="show failed/successor version lineage for recovery case")
    rvst.add_argument("--case-id",type=int,default=None)
    sub.add_parser("recommendation-algorithm-versioning-status", help="show algorithm versioning and recovery lineage status")
    rac=sub.add_parser("recommendation-algorithm-version-cohorts", help="show runtime cohorts for one recommendation algorithm version")
    rac.add_argument("--algorithm-version-id",type=int,default=None)
    rac.add_argument("--context-signature",default=None)
    rap=sub.add_parser("recommendation-algorithm-version-profiles", help="show version/context runtime performance profiles")
    rap.add_argument("--algorithm-version-id",type=int,default=None)
    rae=sub.add_parser("recommendation-algorithm-version-evaluate", help="evaluate version-level promotion/runtime memory")
    rae.add_argument("--algorithm-version-id",type=int,required=True)
    rae.add_argument("--context-signature",required=True)
    raeh=sub.add_parser("recommendation-algorithm-version-evaluations", help="show version-level evaluation history")
    raeh.add_argument("--algorithm-version-id",type=int,default=None)
    sub.add_parser("recommendation-algorithm-version-cohort-status", help="show algorithm version runtime cohort/promotion memory status")
    rvpe=sub.add_parser("recommendation-version-promotion-evaluate", help="evaluate one algorithm version for promotion or supersede")
    rvpe.add_argument("--algorithm-version-id",type=int,required=True)
    rvpr=sub.add_parser("recommendation-version-promotion-review", help="Human review version-level promotion/supersede gate")
    rvpr.add_argument("--algorithm-version-id",type=int,required=True)
    rvpr.add_argument("--decision",choices=["PROMOTE","KEEP_CURRENT","HOLD","REJECT"],required=True)
    rvpr.add_argument("--reviewer",required=True)
    rvpr.add_argument("--reason",required=True)
    rvprd=sub.add_parser("recommendation-version-promotion-ready", help="show whether version gate plus Human review allow final policy promotion")
    rvprd.add_argument("--algorithm-version-id",type=int,required=True)
    rvpg=sub.add_parser("recommendation-version-promotion-gates", help="show version-level promotion gate history")
    rvpg.add_argument("--algorithm-version-id",type=int,default=None)
    rvsc=sub.add_parser("recommendation-version-supersede-comparisons", help="show candidate-vs-incumbent conservative supersede comparisons")
    rvsc.add_argument("--algorithm-version-id",type=int,default=None)
    rvprh=sub.add_parser("recommendation-version-promotion-reviews", help="show Human version promotion reviews")
    rvprh.add_argument("--algorithm-version-id",type=int,default=None)
    rvpev=sub.add_parser("recommendation-version-promotion-events", help="show version promotion/supersede events")
    rvpev.add_argument("--algorithm-version-id",type=int,default=None)
    sub.add_parser("recommendation-version-promotion-status", help="show version-aware promotion and supersede status")
    rsge=sub.add_parser("recommendation-supersede-guard-evaluate", help="evaluate whether harmful promoted version can fall back to last safe superseded version")
    rsge.add_argument("--root-cause-type",required=True)
    rsge.add_argument("--challenge-id",type=int,required=True)
    rsge.add_argument("--verdict",choices=["RECOMMENDATION_HELPFUL","RECOMMENDATION_HARMFUL","NEUTRAL"],required=True)
    rsgh=sub.add_parser("recommendation-supersede-guard-evaluations", help="show supersede runtime guard evaluation history")
    rsgh.add_argument("--algorithm-version-id",type=int,default=None)
    rvfb=sub.add_parser("recommendation-version-fallbacks", help="show executed safe version fallbacks")
    rvfb.add_argument("--root-cause-type",default=None)
    rsgev=sub.add_parser("recommendation-supersede-guard-events", help="show version fallback runtime guard events")
    rsgev.add_argument("--root-cause-type",default=None)
    sub.add_parser("recommendation-supersede-guard-status", help="show supersede runtime guard and version fallback status")
    rfvg=sub.add_parser("recommendation-fallback-verification-generations", help="show bounded fallback verification generations")
    rfvg.add_argument("--root-cause-type",default=None)
    rfvo=sub.add_parser("recommendation-fallback-verification-observations", help="show fallback verification runtime observations")
    rfvo.add_argument("--generation-id",type=int,default=None)
    sub.add_parser("recommendation-fallback-pair-profiles", help="show anti-ping-pong version-pair profiles")
    rfve=sub.add_parser("recommendation-fallback-verification-events", help="show fallback verification events")
    rfve.add_argument("--generation-id",type=int,default=None)
    sub.add_parser("recommendation-fallback-verification-status", help="show fallback verification and anti-ping-pong status")
    sub.add_parser("recommendation-fallback-family-profiles", help="show Version Family fallback stability/circuit-breaker profiles")
    sub.add_parser("recommendation-fallback-family-reviews", help="show Human architecture review audit for fallback families")
    rffr=sub.add_parser("recommendation-fallback-family-review", help="record Human architecture review acknowledgement/hold/reject")
    rffr.add_argument("--family-profile-id",type=int,required=True)
    rffr.add_argument("--decision",choices=["ACKNOWLEDGE_ARCHITECTURE_REVIEW","HOLD","REJECT"],required=True)
    rffr.add_argument("--reviewer",required=True)
    rffr.add_argument("--reason",required=True)
    sub.add_parser("recommendation-fallback-family-events", help="show Version Family fallback circuit-breaker events")
    sub.add_parser("recommendation-fallback-family-status", help="show fallback stability memory and Version Family circuit-breaker status")
    rfrc=sub.add_parser("recommendation-fallback-family-recovery-cases", help="show Family Circuit recovery/re-arm cases")
    rfrc.add_argument("--family-profile-id",type=int,default=None)
    rfra=sub.add_parser("recommendation-fallback-family-remediation-add", help="submit fresh family-level Architecture remediation")
    rfra.add_argument("--case-id",type=int,required=True)
    rfra.add_argument("--remediation-type",required=True)
    rfra.add_argument("--remediation-ref",required=True)
    rfra.add_argument("--submitted-by",required=True)
    rfra.add_argument("--notes",default="")
    rfrr=sub.add_parser("recommendation-fallback-family-remediation-review", help="Human review family-level remediation effectiveness")
    rfrr.add_argument("--remediation-id",type=int,required=True)
    rfrr.add_argument("--decision",choices=["EFFECTIVE","INEFFECTIVE","HOLD"],required=True)
    rfrr.add_argument("--reviewer",required=True)
    rfrr.add_argument("--reason",required=True)
    rfcv=sub.add_parser("recommendation-fallback-family-candidate-set", help="bind a fresh Algorithm Version to a Family recovery case")
    rfcv.add_argument("--case-id",type=int,required=True)
    rfcv.add_argument("--algorithm-version-id",type=int,required=True)
    rfcv.add_argument("--actor",required=True)
    rfcv.add_argument("--reason",required=True)
    rfea=sub.add_parser("recommendation-fallback-family-evidence-add", help="add fresh Human-confirmed Shadow evidence for Family recovery")
    rfea.add_argument("--case-id",type=int,required=True)
    rfea.add_argument("--challenge-id",type=int,required=True)
    rfea.add_argument("--verdict",choices=["RECOMMENDATION_HELPFUL","RECOMMENDATION_HARMFUL","NEUTRAL"],required=True)
    rfea.add_argument("--human-confirmed",action="store_true")
    rfea.add_argument("--notes",default="")
    rfev=sub.add_parser("recommendation-fallback-family-recovery-evaluate", help="evaluate Family Circuit re-arm qualification gate")
    rfev.add_argument("--case-id",type=int,required=True)
    rfar=sub.add_parser("recommendation-fallback-family-rearm-review", help="Human approve/hold/reject limited Family Circuit re-arm")
    rfar.add_argument("--case-id",type=int,required=True)
    rfar.add_argument("--decision",choices=["APPROVE_REARM","HOLD","REJECT"],required=True)
    rfar.add_argument("--reviewer",required=True)
    rfar.add_argument("--reason",required=True)
    sub.add_parser("recommendation-fallback-family-recovery-status", help="show Family recovery qualification and re-arm audit status")
    rgo=sub.add_parser("recommendation-fallback-family-generation-outcomes", help="show stabilized Family recovery generation runtime outcomes")
    rgo.add_argument("--family-signature",default=None)
    rgep=sub.add_parser("recommendation-fallback-family-effectiveness-profiles", help="show Family remediation long-term effectiveness memory")
    rgs=sub.add_parser("recommendation-fallback-family-generation-sustain", help="evaluate sustained success for one Family recovery generation")
    rgs.add_argument("--outcome-id",type=int,required=True)
    rgs.add_argument("--now",default=None)
    rgr=sub.add_parser("recommendation-fallback-family-remediation-memory", help="check whether a Family remediation is allowed by recurrence memory")
    rgr.add_argument("--family-signature",required=True)
    rgr.add_argument("--remediation-type",required=True)
    rgr.add_argument("--remediation-ref",required=True)
    rgev=sub.add_parser("recommendation-fallback-family-generation-events", help="show Family generation runtime memory events")
    rgev.add_argument("--outcome-id",type=int,default=None)
    sub.add_parser("recommendation-fallback-family-memory-status", help="show Family generation runtime and remediation effectiveness memory")
    rfrk=sub.add_parser("recommendation-fallback-family-remediation-rank", help="rank historical Family remediations with conservative effectiveness scoring")
    rfrk.add_argument("--case-id",type=int,required=True)
    rfrc=sub.add_parser("recommendation-fallback-family-remediation-recommend", help="create shadow Family remediation recommendation for one recovery case")
    rfrc.add_argument("--case-id",type=int,required=True)
    rfrl=sub.add_parser("recommendation-fallback-family-remediation-rankings", help="show Family remediation ranking history")
    rfrl.add_argument("--case-id",type=int,default=None)
    rfrs=sub.add_parser("recommendation-fallback-family-remediation-recommendations", help="show shadow Family remediation recommendations")
    rfrs.add_argument("--case-id",type=int,default=None)
    rfsel=sub.add_parser("recommendation-fallback-family-remediation-select", help="Human Architecture Selection for ranked Family remediation")
    rfsel.add_argument("--case-id",type=int,required=True)
    rfsel.add_argument("--decision",choices=["SELECT","USE_DETERMINISTIC","HOLD","REJECT"],required=True)
    rfsel.add_argument("--ranking-id",type=int,default=None)
    rfsel.add_argument("--reviewer",required=True)
    rfsel.add_argument("--reason",required=True)
    rfsrh=sub.add_parser("recommendation-fallback-family-remediation-selection-reviews", help="show Human Family remediation selection review history")
    rfsrh.add_argument("--case-id",type=int,default=None)
    rfrev=sub.add_parser("recommendation-fallback-family-remediation-ranking-events", help="show Family remediation ranking/recommendation events")
    rfrev.add_argument("--case-id",type=int,default=None)
    sub.add_parser("recommendation-fallback-family-ranking-status", help="show conservative Family remediation ranking and Human selection status")
    rfo=sub.add_parser("recommendation-fallback-family-recommendation-outcomes", help="show runtime outcomes for Family remediation recommendations/selections")
    rfo.add_argument("--family-signature",default=None)
    sub.add_parser("recommendation-fallback-family-recommendation-effectiveness", help="show recommendation acceptance/override/helpfulness effectiveness profiles")
    rfev=sub.add_parser("recommendation-fallback-family-recommendation-outcome-events", help="show recommendation runtime outcome events")
    rfev.add_argument("--outcome-id",type=int,default=None)
    sub.add_parser("recommendation-fallback-family-recommendation-outcome-status", help="show Family recommendation runtime outcome and calibration status")
    sub.add_parser("snapshot-list", help="list immutable Daily Run metric snapshots")
    ss=sub.add_parser("snapshot-show", help="show immutable Daily Run metric snapshot")
    ss.add_argument("--daily-run-id",required=True)
    sv=sub.add_parser("snapshot-verify", help="verify immutable snapshot hash integrity")
    sv.add_argument("--daily-run-id",required=True)
    sub.add_parser("lineage-status", help="list lineage summaries created by normal CLI commands")
    lt=sub.add_parser("lineage-trace", help="print one observation lineage trace")
    lt.add_argument("--lineage-id",required=True)
    args=p.parse_args()
    if args.command in (None,"fixture"):
        raise SystemExit(cmd_fixture())
    if args.command=="collect-daum-snapshot":
        raise SystemExit(cmd_daum("snapshot"))
    if args.command=="collect-daum":
        raise SystemExit(cmd_daum("live"))
    if args.command=="acquire-daum-snapshot":
        raise SystemExit(cmd_acquire("snapshot"))
    if args.command=="acquire-daum":
        raise SystemExit(cmd_acquire("live"))
    if args.command=="recover-cross-source-snapshot":
        raise SystemExit(cmd_recover_snapshot())
    if args.command=="collect-naver-snapshot":
        raise SystemExit(cmd_naver_snapshot())
    if args.command=="collect-naver":
        raise SystemExit(cmd_naver_live())
    if args.command=="recover-naver-snapshot":
        raise SystemExit(cmd_recover_naver("snapshot"))
    if args.command=="recover-naver":
        raise SystemExit(cmd_recover_naver("live"))
    if args.command=="acquire-naver-snapshot":
        raise SystemExit(cmd_acquire_naver_snapshot())
    if args.command=="acquire-naver":
        raise SystemExit(cmd_acquire_naver_live())
    if args.command=="metrics":
        raise SystemExit(cmd_metrics())
    if args.command=="revision-snapshot":
        raise SystemExit(cmd_revision_snapshot())
    if args.command=="freshness-miss-snapshot":
        raise SystemExit(cmd_freshness_miss_snapshot())
    if args.command=="gate1-14d":
        raise SystemExit(cmd_gate1_14d(False))
    if args.command=="gate1-14d-fail":
        raise SystemExit(cmd_gate1_14d(True))
    if args.command=="gt-add":
        raise SystemExit(cmd_gt_add(args))
    if args.command=="gt-status":
        raise SystemExit(cmd_gt_status(args))
    if args.command=="export-dm":
        raise SystemExit(cmd_export_dm(args))
    if args.command=="reconcile":
        raise SystemExit(cmd_reconcile(args))
    if args.command=="daily-report":
        raise SystemExit(cmd_daily_report(args))
    if args.command=="rolling-report":
        raise SystemExit(cmd_rolling_report())
    if args.command=="evidence-model-snapshot":
        raise SystemExit(cmd_evidence_model_snapshot())
    if args.command=="evidence-p0-snapshot":
        raise SystemExit(cmd_evidence_p0_snapshot())
    if args.command=="poster-source-snapshot":
        raise SystemExit(cmd_poster_source_snapshot())
    if args.command=="evidence-metrics-v2-snapshot":
        raise SystemExit(cmd_evidence_metrics_v2_snapshot())
    if args.command=="evidence-metrics-v2":
        raise SystemExit(cmd_evidence_metrics_v2())
    if args.command=="day1-real-metrics":
        raise SystemExit(cmd_day1_real_metrics())
    if args.command=="observation-snapshot":
        raise SystemExit(cmd_observation_snapshot())
    if args.command=="observation-metrics":
        raise SystemExit(cmd_observation_metrics())
    if args.command=="lineage-snapshot":
        raise SystemExit(cmd_lineage_snapshot())
    if args.command=="live-lineage-snapshot":
        raise SystemExit(cmd_live_lineage_snapshot())
    if args.command=="run-daily":
        raise SystemExit(cmd_run_daily(args))
    if args.command=="daily-status":
        raise SystemExit(cmd_daily_status())
    if args.command=="operations-summary":
        raise SystemExit(cmd_operations_summary(args))
    if args.command=="review-event":
        raise SystemExit(cmd_review_event(args))
    if args.command=="review-field":
        raise SystemExit(cmd_review_field(args))
    if args.command=="review-recovery":
        raise SystemExit(cmd_review_recovery(args))
    if args.command=="review-audit":
        raise SystemExit(cmd_review_audit(args))
    if args.command=="review-metrics":
        raise SystemExit(cmd_review_metrics())
    if args.command=="correction-hotspots":
        raise SystemExit(cmd_correction_hotspots())
    if args.command=="improvement-backlog":
        raise SystemExit(cmd_improvement_backlog())
    if args.command=="backlog-sync":
        raise SystemExit(cmd_backlog_sync(args))
    if args.command=="backlog-list":
        raise SystemExit(cmd_backlog_list())
    if args.command=="backlog-status":
        raise SystemExit(cmd_backlog_status(args))
    if args.command=="backlog-effect":
        raise SystemExit(cmd_backlog_effect(args))
    if args.command=="backlog-detail":
        raise SystemExit(cmd_backlog_detail(args))
    if args.command=="change-add":
        raise SystemExit(cmd_change_add(args))
    if args.command=="change-list":
        raise SystemExit(cmd_change_list())
    if args.command=="change-link":
        raise SystemExit(cmd_change_link(args))
    if args.command=="change-detail":
        raise SystemExit(cmd_change_detail(args))
    if args.command=="change-verdict":
        raise SystemExit(cmd_change_verdict(args))
    if args.command=="change-goal":
        raise SystemExit(cmd_change_goal(args))
    if args.command=="backlog-goal":
        raise SystemExit(cmd_backlog_goal(args))
    if args.command=="adaptive-weight-status":
        raise SystemExit(cmd_adaptive_weight_status(args))
    if args.command=="adaptive-weight-recompute":
        raise SystemExit(cmd_adaptive_weight_recompute(args))
    if args.command=="shadow-agreement":
        raise SystemExit(cmd_shadow_agreement(args))
    if args.command=="shadow-safety":
        raise SystemExit(cmd_shadow_safety(args))
    if args.command=="shadow-safety-history":
        raise SystemExit(cmd_shadow_safety_history(args))
    if args.command=="rolling-shadow":
        raise SystemExit(cmd_rolling_shadow(args))
    if args.command=="rolling-shadow-history":
        raise SystemExit(cmd_rolling_shadow_history(args))
    if args.command=="promotion-candidates":
        raise SystemExit(cmd_promotion_candidates(args))
    if args.command=="promotion-review":
        raise SystemExit(cmd_promotion_review(args))
    if args.command=="promotion-reviews":
        raise SystemExit(cmd_promotion_reviews(args))
    if args.command=="promotion-leases":
        raise SystemExit(cmd_promotion_leases(args))
    if args.command=="promotion-lease-events":
        raise SystemExit(cmd_promotion_lease_events(args))
    if args.command=="promotion-rollback":
        raise SystemExit(cmd_promotion_rollback(args))
    if args.command=="canary-outcome":
        raise SystemExit(cmd_canary_outcome(args))
    if args.command=="canary-outcomes":
        raise SystemExit(cmd_canary_outcomes(args))
    if args.command=="promotion-final":
        raise SystemExit(cmd_promotion_final(args))
    if args.command=="promotion-final-reviews":
        raise SystemExit(cmd_promotion_final_reviews(args))
    if args.command=="full-promotions":
        raise SystemExit(cmd_full_promotions(args))
    if args.command=="full-promotion-rollback":
        raise SystemExit(cmd_full_promotion_rollback(args))
    if args.command=="post-promotion-guard":
        raise SystemExit(cmd_post_promotion_guard(args))
    if args.command=="post-promotion-guards":
        raise SystemExit(cmd_post_promotion_guards(args))
    if args.command=="promotion-health":
        raise SystemExit(cmd_promotion_health(args))
    if args.command=="decision-quality-record":
        raise SystemExit(cmd_decision_quality_record(args))
    if args.command=="decision-quality":
        raise SystemExit(cmd_decision_quality(args))
    if args.command=="goal-relevance":
        raise SystemExit(cmd_goal_relevance(args))
    if args.command=="goal-relevance-history":
        raise SystemExit(cmd_goal_relevance_history(args))
    if args.command=="decision-evidence-scan":
        raise SystemExit(cmd_decision_evidence_scan(args))
    if args.command=="decision-evidence-feedback":
        raise SystemExit(cmd_decision_evidence_feedback(args))
    if args.command=="decision-evidence-confirm":
        raise SystemExit(cmd_decision_evidence_confirm(args))
    if args.command=="decision-evidence-list":
        raise SystemExit(cmd_decision_evidence_list(args))
    if args.command=="decision-evidence-confirmations":
        raise SystemExit(cmd_decision_evidence_confirmations(args))
    if args.command=="evidence-queue-evaluate":
        raise SystemExit(cmd_evidence_queue_evaluate(args))
    if args.command=="evidence-queue":
        raise SystemExit(cmd_evidence_queue(args))
    if args.command=="evidence-queue-events":
        raise SystemExit(cmd_evidence_queue_events(args))
    if args.command=="evidence-clusters-resolve":
        raise SystemExit(cmd_evidence_clusters_resolve(args))
    if args.command=="evidence-clusters":
        raise SystemExit(cmd_evidence_clusters(args))
    if args.command=="root-cause-attribute":
        raise SystemExit(cmd_root_cause_attribute(args))
    if args.command=="root-causes":
        raise SystemExit(cmd_root_causes(args))
    if args.command=="root-cause-backlog-sync":
        raise SystemExit(cmd_root_cause_backlog_sync(args))
    if args.command=="cluster-closure-check":
        raise SystemExit(cmd_cluster_closure_check(args))
    if args.command=="cluster-close":
        raise SystemExit(cmd_cluster_close(args))
    if args.command=="cluster-closure-history":
        raise SystemExit(cmd_cluster_closure_history(args))
    if args.command=="reliability-refresh":
        raise SystemExit(cmd_reliability_refresh(args))
    if args.command=="reliability-profiles":
        raise SystemExit(cmd_reliability_profiles(args))
    if args.command=="reliability-observations":
        raise SystemExit(cmd_reliability_observations(args))
    if args.command=="reliability-success":
        raise SystemExit(cmd_reliability_success(args))
    if args.command=="preventive-policy-evaluate":
        raise SystemExit(cmd_preventive_policy_evaluate(args))
    if args.command=="preventive-policy-decisions":
        raise SystemExit(cmd_preventive_policy_decisions(args))
    if args.command=="preventive-canary-start":
        raise SystemExit(cmd_preventive_canary_start(args))
    if args.command=="preventive-canaries":
        raise SystemExit(cmd_preventive_canaries(args))
    if args.command=="preventive-canary-rollback":
        raise SystemExit(cmd_preventive_canary_rollback(args))
    if args.command=="preventive-canary-events":
        raise SystemExit(cmd_preventive_canary_events(args))
    if args.command=="preventive-outcome-record":
        raise SystemExit(cmd_preventive_outcome_record(args))
    if args.command=="preventive-outcomes":
        raise SystemExit(cmd_preventive_outcomes(args))
    if args.command=="preventive-canary-safety":
        raise SystemExit(cmd_preventive_canary_safety(args))
    if args.command=="preventive-canary-safety-history":
        raise SystemExit(cmd_preventive_canary_safety_history(args))
    if args.command=="preventive-final-review":
        raise SystemExit(cmd_preventive_final_review(args))
    if args.command=="preventive-full-promotions":
        raise SystemExit(cmd_preventive_full_promotions(args))
    if args.command=="preventive-final-reviews":
        raise SystemExit(cmd_preventive_final_reviews(args))
    if args.command=="preventive-full-rollback":
        raise SystemExit(cmd_preventive_full_rollback(args))
    if args.command=="preventive-full-runtime-guard":
        raise SystemExit(cmd_preventive_full_runtime_guard(args))
    if args.command=="preventive-full-runtime-guards":
        raise SystemExit(cmd_preventive_full_runtime_guards(args))
    if args.command=="preventive-full-runtime-observations":
        raise SystemExit(cmd_preventive_full_runtime_observations(args))
    if args.command=="preventive-full-runtime-events":
        raise SystemExit(cmd_preventive_full_runtime_events(args))
    if args.command=="preventive-recovery-cases":
        raise SystemExit(cmd_preventive_recovery_cases(args))
    if args.command=="preventive-recovery-root-cause":
        raise SystemExit(cmd_preventive_recovery_root_cause(args))
    if args.command=="preventive-recovery-remediation":
        raise SystemExit(cmd_preventive_recovery_remediation(args))
    if args.command=="preventive-recovery-evaluate":
        raise SystemExit(cmd_preventive_recovery_evaluate(args))
    if args.command=="preventive-recovery-history":
        raise SystemExit(cmd_preventive_recovery_history(args))
    if args.command=="preventive-recovery-events":
        raise SystemExit(cmd_preventive_recovery_events(args))
    if args.command=="preventive-requalify":
        raise SystemExit(cmd_preventive_requalify(args))
    if args.command=="preventive-recurrence-profiles":
        raise SystemExit(cmd_preventive_recurrence_profiles(args))
    if args.command=="preventive-recurrence-evaluate":
        raise SystemExit(cmd_preventive_recurrence_evaluate(args))
    if args.command=="preventive-recurrence-history":
        raise SystemExit(cmd_preventive_recurrence_history(args))
    if args.command=="preventive-recurrence-exception":
        raise SystemExit(cmd_preventive_recurrence_exception(args))
    if args.command=="preventive-recurrence-exceptions":
        raise SystemExit(cmd_preventive_recurrence_exceptions(args))
    if args.command=="preventive-quarantines":
        raise SystemExit(cmd_preventive_quarantines(args))
    if args.command=="preventive-quarantine-events":
        raise SystemExit(cmd_preventive_quarantine_events(args))
    if args.command=="preventive-reintegration-evaluate":
        raise SystemExit(cmd_preventive_reintegration_evaluate(args))
    if args.command=="preventive-reintegration-history":
        raise SystemExit(cmd_preventive_reintegration_history(args))
    if args.command=="preventive-quarantine-release-review":
        raise SystemExit(cmd_preventive_quarantine_release_review(args))
    if args.command=="preventive-quarantine-release-reviews":
        raise SystemExit(cmd_preventive_quarantine_release_reviews(args))
    if args.command=="alternative-route-plan":
        raise SystemExit(cmd_alternative_route_plan(args))
    if args.command=="alternative-route-evaluations":
        raise SystemExit(cmd_alternative_route_evaluations(args))
    if args.command=="alternative-route-events":
        raise SystemExit(cmd_alternative_route_events(args))
    if args.command=="verification-continuity":
        raise SystemExit(cmd_verification_continuity(args))
    if args.command=="verification-continuity-history":
        raise SystemExit(cmd_verification_continuity_history(args))
    if args.command=="source-relationship-add":
        raise SystemExit(cmd_source_relationship_add(args))
    if args.command=="source-relationships":
        raise SystemExit(cmd_source_relationships(args))
    if args.command=="evidence-fingerprint-add":
        raise SystemExit(cmd_evidence_fingerprint_add(args))
    if args.command=="evidence-fingerprints":
        raise SystemExit(cmd_evidence_fingerprints(args))
    if args.command=="source-independence-evaluate":
        raise SystemExit(cmd_source_independence_evaluate(args))
    if args.command=="source-independence-history":
        raise SystemExit(cmd_source_independence_history(args))
    if args.command=="cross-post-infer":
        raise SystemExit(cmd_cross_post_infer(args))
    if args.command=="cross-post-clusters":
        raise SystemExit(cmd_cross_post_clusters(args))
    if args.command=="cross-post-review":
        raise SystemExit(cmd_cross_post_review(args))
    if args.command=="origin-calibration":
        raise SystemExit(cmd_origin_calibration(args))
    if args.command=="origin-calibration-history":
        raise SystemExit(cmd_origin_calibration_history(args))
    if args.command=="origin-review-queue":
        raise SystemExit(cmd_origin_review_queue(args))
    if args.command=="origin-review-priority-history":
        raise SystemExit(cmd_origin_review_priority_history(args))
    if args.command=="threshold-candidate-create":
        raise SystemExit(cmd_threshold_candidate_create(args))
    if args.command=="threshold-candidates":
        raise SystemExit(cmd_threshold_candidates(args))
    if args.command=="threshold-review":
        raise SystemExit(cmd_threshold_review(args))
    if args.command=="threshold-canary-start":
        raise SystemExit(cmd_threshold_canary_start(args))
    if args.command=="threshold-canary-list":
        raise SystemExit(cmd_threshold_canary_list(args))
    if args.command=="threshold-canary-outcome":
        raise SystemExit(cmd_threshold_canary_outcome(args))
    if args.command=="threshold-promote":
        raise SystemExit(cmd_threshold_promote(args))
    if args.command=="threshold-promotions":
        raise SystemExit(cmd_threshold_promotions(args))
    if args.command=="threshold-rollback":
        raise SystemExit(cmd_threshold_rollback(args))
    if args.command=="threshold-runtime-status":
        raise SystemExit(cmd_threshold_runtime_status(args))
    if args.command=="threshold-runtime-observe":
        raise SystemExit(cmd_threshold_runtime_observe(args))
    if args.command=="threshold-runtime-history":
        raise SystemExit(cmd_threshold_runtime_history(args))
    if args.command=="threshold-guard-history":
        raise SystemExit(cmd_threshold_guard_history(args))
    if args.command=="threshold-guard-status":
        raise SystemExit(cmd_threshold_guard_status(args))
    if args.command=="threshold-recovery-list":
        raise SystemExit(cmd_threshold_recovery_list(args))
    if args.command=="threshold-recovery-outcome":
        raise SystemExit(cmd_threshold_recovery_outcome(args))
    if args.command=="threshold-requalify":
        raise SystemExit(cmd_threshold_requalify(args))
    if args.command=="threshold-root-cause":
        raise SystemExit(cmd_threshold_root_cause(args))
    if args.command=="threshold-root-causes":
        raise SystemExit(cmd_threshold_root_causes(args))
    if args.command=="threshold-adaptive-requirement":
        raise SystemExit(cmd_threshold_adaptive_requirement(args))
    if args.command=="threshold-adaptive-requirements":
        raise SystemExit(cmd_threshold_adaptive_requirements(args))
    if args.command=="threshold-remediation":
        raise SystemExit(cmd_threshold_remediation(args))
    if args.command=="threshold-remediation-review":
        raise SystemExit(cmd_threshold_remediation_review(args))
    if args.command=="threshold-root-cause-review":
        raise SystemExit(cmd_threshold_root_cause_review(args))
    if args.command=="threshold-adaptive-status":
        raise SystemExit(cmd_threshold_adaptive_status(args))
    if args.command=="threshold-recurrence-status":
        raise SystemExit(cmd_threshold_recurrence_status(args))
    if args.command=="threshold-recurrence-profiles":
        raise SystemExit(cmd_threshold_recurrence_profiles(args))
    if args.command=="threshold-recurrence-events":
        raise SystemExit(cmd_threshold_recurrence_events(args))
    if args.command=="remediation-effectiveness-evaluate":
        raise SystemExit(cmd_remediation_effectiveness_evaluate(args))
    if args.command=="remediation-effectiveness-history":
        raise SystemExit(cmd_remediation_effectiveness_history(args))
    if args.command=="remediation-type-stats":
        raise SystemExit(cmd_remediation_type_stats(args))
    if args.command=="threshold-restrictions":
        raise SystemExit(cmd_threshold_restrictions(args))
    if args.command=="threshold-restriction-exceptions":
        raise SystemExit(cmd_threshold_restriction_exceptions(args))
    if args.command=="threshold-restriction-exception":
        raise SystemExit(cmd_threshold_restriction_exception(args))
    if args.command=="threshold-restriction-release":
        raise SystemExit(cmd_threshold_restriction_release(args))
    if args.command=="threshold-scope-status":
        raise SystemExit(cmd_threshold_scope_status(args))
    if args.command=="threshold-scopes":
        raise SystemExit(cmd_threshold_scopes(args))
    if args.command=="threshold-scope-derive":
        raise SystemExit(cmd_threshold_scope_derive(args))
    if args.command=="threshold-scope-override":
        raise SystemExit(cmd_threshold_scope_override(args))
    if args.command=="threshold-scope-release":
        raise SystemExit(cmd_threshold_scope_release(args))
    if args.command=="threshold-scope-routes":
        raise SystemExit(cmd_threshold_scope_routes(args))
    if args.command=="threshold-safe-alternative":
        raise SystemExit(cmd_threshold_safe_alternative(args))
    if args.command=="scope-reintegration-evidence-add":
        raise SystemExit(cmd_scope_reintegration_evidence_add(args))
    if args.command=="scope-reintegration-evidence":
        raise SystemExit(cmd_scope_reintegration_evidence(args))
    if args.command=="scope-reintegration-evaluate":
        raise SystemExit(cmd_scope_reintegration_evaluate(args))
    if args.command=="scope-reintegration-evaluations":
        raise SystemExit(cmd_scope_reintegration_evaluations(args))
    if args.command=="scope-reintegration-review":
        raise SystemExit(cmd_scope_reintegration_review(args))
    if args.command=="scope-reintegration-canary-start":
        raise SystemExit(cmd_scope_reintegration_canary_start(args))
    if args.command=="scope-reintegration-canaries":
        raise SystemExit(cmd_scope_reintegration_canaries(args))
    if args.command=="scope-reintegration-canary-outcome":
        raise SystemExit(cmd_scope_reintegration_canary_outcome(args))
    if args.command=="scope-reintegration-release":
        raise SystemExit(cmd_scope_reintegration_release(args))
    if args.command=="scope-reintegration-status":
        raise SystemExit(cmd_scope_reintegration_status(args))
    if args.command=="post-reintegration-observe":
        raise SystemExit(cmd_post_reintegration_observe(args))
    if args.command=="post-reintegration-observations":
        raise SystemExit(cmd_post_reintegration_observations(args))
    if args.command=="post-reintegration-guard":
        raise SystemExit(cmd_post_reintegration_guard(args))
    if args.command=="post-reintegration-evaluations":
        raise SystemExit(cmd_post_reintegration_evaluations(args))
    if args.command=="post-reintegration-reisolations":
        raise SystemExit(cmd_post_reintegration_reisolations(args))
    if args.command=="post-reintegration-penalty":
        raise SystemExit(cmd_post_reintegration_penalty(args))
    if args.command=="post-reintegration-reisolation-clear":
        raise SystemExit(cmd_post_reintegration_reisolation_clear(args))
    if args.command=="post-reintegration-status":
        raise SystemExit(cmd_post_reintegration_status(args))
    if args.command=="post-reintegration-root-cause":
        raise SystemExit(cmd_post_reintegration_root_cause(args))
    if args.command=="post-reintegration-root-causes":
        raise SystemExit(cmd_post_reintegration_root_causes(args))
    if args.command=="post-reintegration-remediation-routes":
        raise SystemExit(cmd_post_reintegration_remediation_routes(args))
    if args.command=="post-reintegration-root-review":
        raise SystemExit(cmd_post_reintegration_root_review(args))
    if args.command=="post-reintegration-remediation-route":
        raise SystemExit(cmd_post_reintegration_remediation_route(args))
    if args.command=="post-reintegration-root-status":
        raise SystemExit(cmd_post_reintegration_root_status(args))
    if args.command=="architecture-plan-create":
        raise SystemExit(cmd_architecture_plan_create(args))
    if args.command=="architecture-plans":
        raise SystemExit(cmd_architecture_plans(args))
    if args.command=="architecture-plan-review":
        raise SystemExit(cmd_architecture_plan_review(args))
    if args.command=="architecture-step-complete":
        raise SystemExit(cmd_architecture_step_complete(args))
    if args.command=="architecture-evidence-add":
        raise SystemExit(cmd_architecture_evidence_add(args))
    if args.command=="architecture-plan-evaluate":
        raise SystemExit(cmd_architecture_plan_evaluate(args))
    if args.command=="architecture-final-review":
        raise SystemExit(cmd_architecture_final_review(args))
    if args.command=="architecture-gate":
        raise SystemExit(cmd_architecture_gate(args))
    if args.command=="architecture-status":
        raise SystemExit(cmd_architecture_status(args))
    if args.command=="architecture-runtime-outcomes":
        raise SystemExit(cmd_architecture_runtime_outcomes(args))
    if args.command=="architecture-effectiveness":
        raise SystemExit(cmd_architecture_effectiveness(args))
    if args.command=="architecture-recommendations":
        raise SystemExit(cmd_architecture_recommendations(args))
    if args.command=="architecture-memory-recommend":
        raise SystemExit(cmd_architecture_memory_recommend(args))
    if args.command=="architecture-runtime-sustain":
        raise SystemExit(cmd_architecture_runtime_sustain(args))
    if args.command=="architecture-memory-status":
        raise SystemExit(cmd_architecture_memory_status(args))
    if args.command=="architecture-comparative-scores":
        raise SystemExit(cmd_architecture_comparative_scores(args))
    if args.command=="architecture-context-recommend":
        raise SystemExit(cmd_architecture_context_recommend(args))
    if args.command=="architecture-comparative-history":
        raise SystemExit(cmd_architecture_comparative_history(args))
    if args.command=="architecture-context-recommendations":
        raise SystemExit(cmd_architecture_context_recommendations(args))
    if args.command=="architecture-ranking-status":
        raise SystemExit(cmd_architecture_ranking_status(args))
    if args.command=="architecture-challenges":
        raise SystemExit(cmd_architecture_challenges(args))
    if args.command=="architecture-challenge-shadow":
        raise SystemExit(cmd_architecture_challenge_shadow(args))
    if args.command=="architecture-challenge-evaluate":
        raise SystemExit(cmd_architecture_challenge_evaluate(args))
    if args.command=="architecture-challenge-decide":
        raise SystemExit(cmd_architecture_challenge_decide(args))
    if args.command=="architecture-challenge-runtime":
        raise SystemExit(cmd_architecture_challenge_runtime(args))
    if args.command=="architecture-recommendation-quality":
        raise SystemExit(cmd_architecture_recommendation_quality(args))
    if args.command=="architecture-challenge-status":
        raise SystemExit(cmd_architecture_challenge_status(args))
    if args.command=="recommendation-policy-evaluate":
        raise SystemExit(cmd_recommendation_policy_evaluate(args))
    if args.command=="recommendation-policy-candidates":
        raise SystemExit(cmd_recommendation_policy_candidates(args))
    if args.command=="recommendation-policy-states":
        raise SystemExit(cmd_recommendation_policy_states(args))
    if args.command=="recommendation-policy-review":
        raise SystemExit(cmd_recommendation_policy_review(args))
    if args.command=="recommendation-policy-final-review":
        raise SystemExit(cmd_recommendation_policy_final_review(args))
    if args.command=="recommendation-policy-rollback":
        raise SystemExit(cmd_recommendation_policy_rollback(args))
    if args.command=="recommendation-policy-assignments":
        raise SystemExit(cmd_recommendation_policy_assignments(args))
    if args.command=="recommendation-policy-events":
        raise SystemExit(cmd_recommendation_policy_events(args))
    if args.command=="recommendation-policy-status":
        raise SystemExit(cmd_recommendation_policy_status(args))
    if args.command=="recommendation-recovery-cases":
        raise SystemExit(cmd_recommendation_recovery_cases(args))
    if args.command=="recommendation-recovery-remediation-add":
        raise SystemExit(cmd_recommendation_recovery_remediation_add(args))
    if args.command=="recommendation-recovery-remediation-review":
        raise SystemExit(cmd_recommendation_recovery_remediation_review(args))
    if args.command=="recommendation-recovery-evidence-add":
        raise SystemExit(cmd_recommendation_recovery_evidence_add(args))
    if args.command=="recommendation-recovery-evaluate":
        raise SystemExit(cmd_recommendation_recovery_evaluate(args))
    if args.command=="recommendation-recovery-review":
        raise SystemExit(cmd_recommendation_recovery_review(args))
    if args.command=="recommendation-recovery-status":
        raise SystemExit(cmd_recommendation_recovery_status(args))
    if args.command=="recommendation-algorithm-version-register":
        raise SystemExit(cmd_recommendation_algorithm_version_register(args))
    if args.command=="recommendation-algorithm-versions":
        raise SystemExit(cmd_recommendation_algorithm_versions(args))
    if args.command=="recommendation-algorithm-current":
        raise SystemExit(cmd_recommendation_algorithm_current(args))
    if args.command=="recommendation-algorithm-lineage":
        raise SystemExit(cmd_recommendation_algorithm_lineage(args))
    if args.command=="recommendation-algorithm-events":
        raise SystemExit(cmd_recommendation_algorithm_events(args))
    if args.command=="recommendation-recovery-version-propose":
        raise SystemExit(cmd_recommendation_recovery_version_propose(args))
    if args.command=="recommendation-recovery-version-approve":
        raise SystemExit(cmd_recommendation_recovery_version_approve(args))
    if args.command=="recommendation-recovery-version-status":
        raise SystemExit(cmd_recommendation_recovery_version_status(args))
    if args.command=="recommendation-algorithm-versioning-status":
        raise SystemExit(cmd_recommendation_algorithm_versioning_status(args))
    if args.command=="recommendation-algorithm-version-cohorts":
        raise SystemExit(cmd_recommendation_algorithm_version_cohorts(args))
    if args.command=="recommendation-algorithm-version-profiles":
        raise SystemExit(cmd_recommendation_algorithm_version_profiles(args))
    if args.command=="recommendation-algorithm-version-evaluate":
        raise SystemExit(cmd_recommendation_algorithm_version_evaluate(args))
    if args.command=="recommendation-algorithm-version-evaluations":
        raise SystemExit(cmd_recommendation_algorithm_version_evaluations(args))
    if args.command=="recommendation-algorithm-version-cohort-status":
        raise SystemExit(cmd_recommendation_algorithm_version_cohort_status(args))
    if args.command=="recommendation-version-promotion-evaluate":
        raise SystemExit(cmd_recommendation_version_promotion_evaluate(args))
    if args.command=="recommendation-version-promotion-review":
        raise SystemExit(cmd_recommendation_version_promotion_review(args))
    if args.command=="recommendation-version-promotion-ready":
        raise SystemExit(cmd_recommendation_version_promotion_ready(args))
    if args.command=="recommendation-version-promotion-gates":
        raise SystemExit(cmd_recommendation_version_promotion_gates(args))
    if args.command=="recommendation-version-supersede-comparisons":
        raise SystemExit(cmd_recommendation_version_supersede_comparisons(args))
    if args.command=="recommendation-version-promotion-reviews":
        raise SystemExit(cmd_recommendation_version_promotion_reviews(args))
    if args.command=="recommendation-version-promotion-events":
        raise SystemExit(cmd_recommendation_version_promotion_events(args))
    if args.command=="recommendation-version-promotion-status":
        raise SystemExit(cmd_recommendation_version_promotion_status(args))
    if args.command=="recommendation-supersede-guard-evaluate":
        raise SystemExit(cmd_recommendation_supersede_guard_evaluate(args))
    if args.command=="recommendation-supersede-guard-evaluations":
        raise SystemExit(cmd_recommendation_supersede_guard_evaluations(args))
    if args.command=="recommendation-version-fallbacks":
        raise SystemExit(cmd_recommendation_version_fallbacks(args))
    if args.command=="recommendation-supersede-guard-events":
        raise SystemExit(cmd_recommendation_supersede_guard_events(args))
    if args.command=="recommendation-supersede-guard-status":
        raise SystemExit(cmd_recommendation_supersede_guard_status(args))
    if args.command=="recommendation-fallback-verification-generations":
        raise SystemExit(cmd_recommendation_fallback_verification_generations(args))
    if args.command=="recommendation-fallback-verification-observations":
        raise SystemExit(cmd_recommendation_fallback_verification_observations(args))
    if args.command=="recommendation-fallback-pair-profiles":
        raise SystemExit(cmd_recommendation_fallback_pair_profiles(args))
    if args.command=="recommendation-fallback-verification-events":
        raise SystemExit(cmd_recommendation_fallback_verification_events(args))
    if args.command=="recommendation-fallback-verification-status":
        raise SystemExit(cmd_recommendation_fallback_verification_status(args))
    if args.command=="recommendation-fallback-family-profiles":
        raise SystemExit(cmd_recommendation_fallback_family_profiles(args))
    if args.command=="recommendation-fallback-family-reviews":
        raise SystemExit(cmd_recommendation_fallback_family_reviews(args))
    if args.command=="recommendation-fallback-family-review":
        raise SystemExit(cmd_recommendation_fallback_family_review(args))
    if args.command=="recommendation-fallback-family-events":
        raise SystemExit(cmd_recommendation_fallback_family_events(args))
    if args.command=="recommendation-fallback-family-status":
        raise SystemExit(cmd_recommendation_fallback_family_status(args))
    if args.command=="recommendation-fallback-family-recovery-cases":
        raise SystemExit(cmd_recommendation_fallback_family_recovery_cases(args))
    if args.command=="recommendation-fallback-family-remediation-add":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_add(args))
    if args.command=="recommendation-fallback-family-remediation-review":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_review(args))
    if args.command=="recommendation-fallback-family-candidate-set":
        raise SystemExit(cmd_recommendation_fallback_family_candidate_set(args))
    if args.command=="recommendation-fallback-family-evidence-add":
        raise SystemExit(cmd_recommendation_fallback_family_evidence_add(args))
    if args.command=="recommendation-fallback-family-recovery-evaluate":
        raise SystemExit(cmd_recommendation_fallback_family_recovery_evaluate(args))
    if args.command=="recommendation-fallback-family-rearm-review":
        raise SystemExit(cmd_recommendation_fallback_family_rearm_review(args))
    if args.command=="recommendation-fallback-family-recovery-status":
        raise SystemExit(cmd_recommendation_fallback_family_recovery_status(args))
    if args.command=="recommendation-fallback-family-generation-outcomes":
        raise SystemExit(cmd_recommendation_fallback_family_generation_outcomes(args))
    if args.command=="recommendation-fallback-family-effectiveness-profiles":
        raise SystemExit(cmd_recommendation_fallback_family_effectiveness_profiles(args))
    if args.command=="recommendation-fallback-family-generation-sustain":
        raise SystemExit(cmd_recommendation_fallback_family_generation_sustain(args))
    if args.command=="recommendation-fallback-family-remediation-memory":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_memory(args))
    if args.command=="recommendation-fallback-family-generation-events":
        raise SystemExit(cmd_recommendation_fallback_family_generation_events(args))
    if args.command=="recommendation-fallback-family-memory-status":
        raise SystemExit(cmd_recommendation_fallback_family_memory_status(args))
    if args.command=="recommendation-fallback-family-remediation-rank":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_rank(args))
    if args.command=="recommendation-fallback-family-remediation-recommend":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_recommend(args))
    if args.command=="recommendation-fallback-family-remediation-rankings":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_rankings(args))
    if args.command=="recommendation-fallback-family-remediation-recommendations":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_recommendations(args))
    if args.command=="recommendation-fallback-family-remediation-select":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_select(args))
    if args.command=="recommendation-fallback-family-remediation-selection-reviews":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_selection_reviews(args))
    if args.command=="recommendation-fallback-family-remediation-ranking-events":
        raise SystemExit(cmd_recommendation_fallback_family_remediation_ranking_events(args))
    if args.command=="recommendation-fallback-family-ranking-status":
        raise SystemExit(cmd_recommendation_fallback_family_ranking_status(args))
    if args.command=="recommendation-fallback-family-recommendation-outcomes":
        raise SystemExit(cmd_recommendation_fallback_family_recommendation_outcomes(args))
    if args.command=="recommendation-fallback-family-recommendation-effectiveness":
        raise SystemExit(cmd_recommendation_fallback_family_recommendation_effectiveness(args))
    if args.command=="recommendation-fallback-family-recommendation-outcome-events":
        raise SystemExit(cmd_recommendation_fallback_family_recommendation_outcome_events(args))
    if args.command=="recommendation-fallback-family-recommendation-outcome-status":
        raise SystemExit(cmd_recommendation_fallback_family_recommendation_outcome_status(args))
    if args.command=="snapshot-list":
        raise SystemExit(cmd_snapshot_list())
    if args.command=="snapshot-show":
        raise SystemExit(cmd_snapshot_show(args))
    if args.command=="snapshot-verify":
        raise SystemExit(cmd_snapshot_verify(args))
    if args.command=="lineage-status":
        raise SystemExit(cmd_lineage_status())
    if args.command=="lineage-trace":
        raise SystemExit(cmd_lineage_trace(args))

if __name__ == '__main__':
    main()
