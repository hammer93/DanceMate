from pathlib import Path
from datetime import date
import json
from .database import create_lineage,create_daily_run,finish_daily_run,link_daily_lineage,daily_run_trace
from .main_helpers import collect_naver_snapshot_step,acquire_naver_snapshot_step,recover_naver_snapshot_step
from .evidence_metrics_v2 import calculate_metrics_v2
from .observation_metrics import calculate_observation_metrics
from .daily_operations_summary import build_daily_operations_summary
from .daily_report_renderer import render_markdown
from .change_traceability import link_and_measure_change,auto_post_change_and_verdict
from .daily_metric_snapshot import capture_daily_metric_snapshot
from .decision_outcome_evidence import scan_automatic_evidence
from .evidence_priority_queue import evaluate_evidence_priority_queue
from .evidence_cluster_resolution import resolve_clusters,attribute_root_causes,sync_root_cause_backlog
from .source_reliability import recompute_all_profiles
from .preventive_full_runtime_guard import evaluate_active_runtime_guards
from .preventive_recovery import evaluate_active_recoveries
from .preventive_quarantine import evaluate_active_quarantines
from .alternative_source_routing import evaluate_active_route_continuity
from .origin_confidence_calibration import daily_origin_quality
from .origin_threshold_promotion import runtime_status as origin_threshold_runtime_status
from .origin_threshold_runtime_guard import runtime_guard_status as origin_threshold_guard_status


def run_daily(con,root,*,run_date=None,mode="snapshot",report_dir=None):
    """One day's run.

    ``report_dir`` overrides where the two report files land. It defaults to
    the repository's own data/reports, which is what the CLI wants and what
    production does; a test can point it somewhere writable instead of
    assuming the checkout is.
    """
    run_date=run_date or date.today().isoformat()
    root_lineage=create_lineage(con,root_run_type="DAILY_RUN",root_source_id="SYSTEM",
      root_query=f"daily:{run_date}",metadata={"mode":mode})
    daily_id=create_daily_run(con,run_date=run_date,mode=mode,root_lineage_id=root_lineage)
    link_daily_lineage(con,daily_run_id=daily_id,lineage_id=root_lineage,role="ROOT")
    started=con.execute("SELECT started_at FROM daily_runs WHERE daily_run_id=?",(daily_id,)).fetchone()["started_at"]
    summary={"steps":[]}
    try:
        if mode!="snapshot": raise NotImplementedError("v0.18 live mode intentionally disabled")
        c=collect_naver_snapshot_step(con,root); summary["steps"].append({"collect":c})
        for lid in c["lineages"]: link_daily_lineage(con,daily_run_id=daily_id,lineage_id=lid,role="DISCOVERY")
        a=acquire_naver_snapshot_step(con,root); summary["steps"].append({"acquire":a})
        r=recover_naver_snapshot_step(con,root); summary["steps"].append({"recover":r})
        ev=calculate_metrics_v2(con,"daily"); ob=calculate_observation_metrics(con)
        summary["evidence_metrics"]=ev[0] if ev else {}
        summary["observation_metrics"]=ob["overall"]
        decision_evidence_scan=scan_automatic_evidence(con,"FIELD_QUALITY")
        summary["decision_outcome_evidence_scan"]=decision_evidence_scan
        summary["steps"].append({"decision_evidence_scan":decision_evidence_scan})
        evidence_queue=evaluate_evidence_priority_queue(
            con,apply_auto_resolution=True)
        summary["evidence_priority_queue"]=evidence_queue
        summary["steps"].append({"evidence_priority_queue":{
            k:v for k,v in evidence_queue.items() if k!="queue"}})

        cluster_resolution=resolve_clusters(con)
        root_cause_attribution=attribute_root_causes(
            con,actor="daily-root-cause-engine")
        root_cause_backlog=sync_root_cause_backlog(
            con,actor="daily-root-cause-engine")
        reliability_refresh=recompute_all_profiles(con)
        full_runtime_guard=evaluate_active_runtime_guards(con)
        recovery_gate=evaluate_active_recoveries(con)
        quarantine_gate=evaluate_active_quarantines(con)
        continuity=evaluate_active_route_continuity(con)
        origin_quality=daily_origin_quality(con)
        origin_threshold_runtime=origin_threshold_runtime_status(con)
        origin_threshold_guard=origin_threshold_guard_status(con)
        summary["evidence_cluster_resolution"]=cluster_resolution
        summary["root_cause_attribution"]=root_cause_attribution
        summary["root_cause_backlog_sync"]=root_cause_backlog
        summary["source_reliability_refresh"]=reliability_refresh
        summary["preventive_full_runtime_guard"]=full_runtime_guard
        summary["preventive_runtime_recovery"]=recovery_gate
        summary["preventive_quarantine"]=quarantine_gate
        summary["verification_continuity"]=continuity
        summary["origin_confidence_calibration"]=origin_quality
        summary["origin_threshold_runtime"]=origin_threshold_runtime
        summary["origin_threshold_runtime_guard"]=origin_threshold_guard
        summary["steps"].append({"evidence_cluster_resolution":cluster_resolution})
        summary["steps"].append({"root_cause_attribution":root_cause_attribution})
        summary["steps"].append({"root_cause_backlog_sync":{
            "linked_count":len(root_cause_backlog.get("linked",[])),
            "skipped_count":len(root_cause_backlog.get("skipped",[]))}})
        summary["steps"].append({"source_reliability_refresh":{
            "profile_count":reliability_refresh.get("profile_count",0),
            "derived_critical_observations":reliability_refresh.get("derived",{}).get("created_count",0)}})
        summary["steps"].append({"preventive_full_runtime_guard":{
            "active_promotion_count":full_runtime_guard.get("active_promotion_count",0),
            "blocked_count":sum(1 for x in full_runtime_guard.get("evaluations",[])
                                if x.get("status")=="BLOCKED")}})
        summary["steps"].append({"preventive_runtime_recovery":{
            "active_recovery_count":recovery_gate.get("active_recovery_count",0),
            "ready_count":sum(1 for x in recovery_gate.get("evaluations",[])
                              if x.get("status")=="READY_FOR_REQUALIFICATION")}})
        summary["steps"].append({"preventive_quarantine":{
            "active_quarantine_count":quarantine_gate.get("active_quarantine_count",0),
            "ready_release_count":sum(1 for x in quarantine_gate.get("evaluations",[])
                                      if x.get("status")=="READY_FOR_RELEASE_REVIEW")}})
        summary["steps"].append({"verification_continuity":{
            "active_quarantined_source_rule_count":
                continuity.get("active_quarantined_source_rule_count",0),
            "routed_verified_count":sum(
                x.get("routed_verified_count",0) for x in continuity.get("continuity",[])),
            "no_safe_route_count":sum(
                x.get("no_safe_route_count",0) for x in continuity.get("continuity",[]))}})
        summary["steps"].append({"origin_confidence_calibration":{
            "recommendation_status":
                origin_quality.get("calibration",{}).get("recommendation_status"),
            "precision":origin_quality.get("calibration",{}).get("precision"),
            "false_positive_rate":
                origin_quality.get("calibration",{}).get("false_positive_rate"),
            "pending_review_count":
                origin_quality.get("review_queue",{}).get("pending_cluster_count",0),
            "p1_review_count":
                origin_quality.get("review_queue",{}).get("p1_count",0)}})
        summary["steps"].append({"origin_threshold_runtime":{
            "effective_full_threshold":
                origin_threshold_runtime.get("effective_full_threshold"),
            "active_canary_id":
                (origin_threshold_runtime.get("active_canary") or {}).get("canary_id"),
            "active_full_promotion_id":
                (origin_threshold_runtime.get("active_full_promotion") or {}).get("promotion_id")}})
        summary["steps"].append({"origin_threshold_runtime_guard":{
            "active_promotion_id":
                (origin_threshold_guard.get("active_promotion") or {}).get("promotion_id"),
            "guard_status":
                (origin_threshold_guard.get("active_guard") or {}).get("overall_status"),
            "recovery_case_count":
                len(origin_threshold_guard.get("recovery_cases") or [])}})
        ops=build_daily_operations_summary(con)
        summary["operations_summary"]=ops
        report_dir=Path(report_dir) if report_dir else root/"data"/"reports"
        report_dir.mkdir(parents=True,exist_ok=True)
        report=report_dir/f"daily-run-{run_date}-v0.19.json"
        md=report_dir/f"daily-operations-{run_date}-v0.19.md"
        report.write_text(json.dumps({"version":"0.19","daily_run_id":daily_id,
          "run_date":run_date,"summary":summary},ensure_ascii=False,indent=2),encoding="utf-8")
        md.write_text(render_markdown(run_date=run_date,daily_run_id=daily_id,summary=ops),encoding="utf-8")
        summary["report"]=str(report); summary["operations_report"]=str(md)
        dc=con.execute("SELECT COUNT(*) n FROM daily_run_lineages WHERE daily_run_id=? AND role='DISCOVERY'",(daily_id,)).fetchone()["n"]
        ac=con.execute("SELECT COUNT(*) n FROM observation_runs WHERE run_type='ACQUISITION' AND started_at>=?",(started,)).fetchone()["n"]
        rc=con.execute("SELECT COUNT(*) n FROM observation_runs WHERE run_type='RECOVERY' AND started_at>=?",(started,)).fetchone()["n"]
        finish_daily_run(con,daily_id,status="PASS",discovery_lineage_count=dc,
          acquisition_run_count=ac,recovery_run_count=rc,metric_status="PASS",report_status="PASS",summary=summary)

        snap=capture_daily_metric_snapshot(con,daily_run_id=daily_id,run_date=run_date)
        summary["immutable_metric_snapshot"]={k:v for k,v in snap.items() if k!="payload"}

        # Any registered change not yet linked to a Daily Run is automatically
        # associated with this completed run as POST_CHANGE.
        pending=con.execute("""SELECT ic.change_id
                               FROM improvement_changes ic
                               WHERE NOT EXISTS(
                                 SELECT 1 FROM change_daily_run_links l
                                 WHERE l.change_id=ic.change_id AND l.relation='POST_CHANGE'
                               )
                               ORDER BY ic.change_id""").fetchall()
        change_effects=[]
        for row in pending:
            change_effects.append({
                "change_id":row["change_id"],
                **auto_post_change_and_verdict(con,change_id=row["change_id"],daily_run_id=daily_id)
            })
        summary["change_effects"]=change_effects

        t=daily_run_trace(con,daily_id); t["summary"]=summary; return t
    except Exception as e:
        finish_daily_run(con,daily_id,status="FAILED",metric_status="FAILED",report_status="FAILED",
          summary={"error":str(e),"steps":summary["steps"]}); raise
