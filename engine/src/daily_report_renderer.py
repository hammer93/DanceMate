def _pct(v):
    return "N/A" if v is None else f"{v*100:.1f}%"

def render_markdown(*,run_date,daily_run_id,summary):
    lines=[f"# DanceMate Daily Operations Summary — {run_date}","",
           f"- Daily Run ID: `{daily_run_id}`",
           f"- Health: **{summary['health']}**",
           f"- P0: **{summary['p0_count']}**",
           f"- Human Review: **{summary['human_review_count']}** "
           f"(High {summary['human_review_high_priority_count']})","",
           "## Event Confidence"]
    for k,v in summary["event_confidence_distribution"].items(): lines.append(f"- {k}: {v}")
    lines+=["","## Field Confidence"]
    for k,v in summary["field_confidence_distribution"].items(): lines.append(f"- {k}: {v}")
    lines+=["","## Source Operations",
            "| Source | Authority | Access | Yield | Access Failure | Recovery |",
            "|---|---|---|---:|---:|---:|"]
    for s in summary["source_operations"]:
        lines.append(f"| {s['source_id']} | {s['authority_level']} | {s['access_state']} | "
                     f"{_pct(s['source_yield_rate'])} | {_pct(s['access_failure_rate'])} | "
                     f"{_pct(s['recovery_success_rate'])} |")
    lines+=["","## Recovery Status"]
    for k,v in summary["recovery_status"].items(): lines.append(f"- {k}: {v}")
    if not summary["recovery_status"]: lines.append("- 없음")
    lines+=["","## Human Review Queue"]
    if summary["human_review_queue"]:
        for i,r in enumerate(summary["human_review_queue"],1):
            lines.append(f"{i}. [{r['priority']}] {r['type']} — {r['reason']}")
    else: lines.append("- 없음")
    lines+=["","## P0"]
    if summary["p0_errors"]:
        for e in summary["p0_errors"]: lines.append(f"- `{e['code']}` — {e}")
    else: lines.append("- P0 없음")
    hm=summary.get("human_in_loop_metrics") or {}
    lines+=["","## Human-in-the-loop Metrics",
            f"- Review Count: {hm.get('review_count',0)}",
            f"- Manual Correction Rate: {_pct(hm.get('manual_correction_rate'))}",
            f"- Machine↔Human Disagreement: {_pct(hm.get('machine_human_disagreement_rate'))}",
            f"- Approval Rate: {_pct(hm.get('approval_rate'))}",
            f"- Rejection Rate: {_pct(hm.get('rejection_rate'))}",
            f"- Hold Rate: {_pct(hm.get('hold_rate'))}",
            f"- Evidence-backed Resolution: {_pct(hm.get('evidence_backed_resolution_rate'))}",
            f"- Avg Review Turnaround: {hm.get('average_review_turnaround_seconds') if hm.get('average_review_turnaround_seconds') is not None else 'N/A'} sec",
            f"- Reviewer Reliability: {hm.get('reviewer_reliability_status','N/A')}"]

    hs=summary.get("correction_hotspots") or {}
    lines+=["","## Correction Hotspots"]
    tops=hs.get("top_hotspots") or []
    if tops:
        lines+=["| Priority | Source | Field | Reviews | Corrections | Holds | Score |",
                "|---|---|---|---:|---:|---:|---:|"]
        for x in tops:
            lines.append(f"| {x['priority']} | {x['source_id']} | {x['field']} | "
                         f"{x['reviews']} | {x['modifications']+x['rejections']} | "
                         f"{x['holds']} | {x['hotspot_score']} |")
    else:
        lines.append("- 아직 Review 데이터 부족")

    backlog=(summary.get("improvement_backlog") or {}).get("backlog") or []
    lines+=["","## Improvement Backlog"]
    if backlog:
        for item in backlog[:5]:
            lines.append(
                f"{item['rank']}. [{item['priority']}/{item['confidence']}] "
                f"{item.get('source_id') or '-'} × {item.get('field') or '-'} — {item['problem_statement']}"
            )
            for epic in item["recommended_epics"]:
                lines.append(f"   - {epic['component']}: {epic['title']}")
    else:
        lines.append("- 없음")

    ct=summary.get("change_traceability") or {}
    verdicts=ct.get("verdicts") or []
    lines+=["","## Change Effect Verdicts"]
    if verdicts:
        lines+=["| Change | Goal | Verdict | Weighted Score | Improved | Regressed |",
                "|---:|---|---|---:|---:|---:|"]
        for v in verdicts:
            lines.append(f"| {v['change_id']} | {v.get('goal_profile') or '-'} | {v['verdict']} | "
                         f"{v.get('weighted_score') if v.get('weighted_score') is not None else 'N/A'} | "
                         f"{v['improved_metric_count']} | {v['regressed_metric_count']} |")
    else:
        lines.append("- 아직 Change verdict 없음")

    shadows=ct.get("shadow_verdicts") or []
    lines+=["","## Adaptive Shadow Verdicts"]
    if shadows:
        lines+=["| Change | Goal | Base | Shadow | Agree | Base Score | Shadow Score | Samples |",
                "|---:|---|---|---|---|---:|---:|---:|"]
        for s in shadows:
            lines.append(
                f"| {s['change_id']} | {s.get('goal_profile') or '-'} | {s['base_verdict']} | "
                f"{s['shadow_verdict']} | {'YES' if s.get('agrees') else 'NO'} | "
                f"{s.get('base_weighted_score')} | {s.get('shadow_weighted_score')} | "
                f"{s.get('adaptive_sample_count',0)} |")
    else:
        lines.append("- 아직 Adaptive Shadow verdict 없음")

    safety=ct.get("shadow_safety") or {}
    lines+=["","## Shadow Safety Gate"]
    if safety:
        lines.append(f"- Status: **{safety.get('status','N/A')}**")
        lines.append(f"- Samples: {safety.get('total',0)} / {safety.get('minimum_samples',20)}")
        lines.append(f"- Agreement: {_pct(safety.get('agreement_rate'))}")
        lines.append(f"- Critical False IMPROVED: {safety.get('critical_false_improved',0)}")
        lines.append(f"- Unsafe IMPROVED: {safety.get('unsafe_improved',0)}")
        for reason in safety.get("reasons") or []:
            lines.append(f"- Reason: {reason}")
    else:
        lines.append("- 아직 Safety Gate 데이터 없음")

    rolling=ct.get("rolling_shadow_stability") or {}
    lines+=["","## Rolling Shadow Stability"]
    if rolling:
        lines.append(f"- Status: **{rolling.get('status','N/A')}**")
        lines.append(f"- Total Samples: {rolling.get('total_samples',0)}")
        lines.append(f"- Downgrade Detected: {'YES' if rolling.get('downgrade_detected') else 'NO'}")
        for w in ("7","14","30"):
            ws=(rolling.get("windows") or {}).get(w) or {}
            lines.append(
                f"- Window {w}: {ws.get('status','N/A')} "
                f"(samples={ws.get('sample_count',0)}, agreement={_pct(ws.get('agreement_rate'))}, "
                f"unsafe={ws.get('unsafe_improved',0)})")
        for reason in rolling.get("reasons") or []:
            lines.append(f"- Reason: {reason}")
    else:
        lines.append("- 아직 Rolling Stability 데이터 없음")

    pcs=ct.get("promotion_candidates") or []
    lines+=["","## Adaptive Promotion Candidates"]
    if pcs:
        for c in pcs[-5:]:
            lines.append(
                f"- Candidate #{c.get('candidate_id')} [{c.get('status')}] "
                f"Goal={c.get('goal_profile') or 'ALL'}, Samples={c.get('total_samples')}, "
                f"Agreement={_pct(c.get('agreement_rate'))}")
    else:
        lines.append("- 없음")

    leases=ct.get("promotion_leases") or []
    lines+=["","## Adaptive Promotion Leases"]
    if leases:
        for l in leases[-5:]:
            lines.append(
                f"- Lease #{l.get('lease_id')} [{l.get('status')}] "
                f"Goal={l.get('goal_profile')}, Mode={l.get('mode')}, "
                f"Canary={l.get('used_canary_changes',0)}/{l.get('max_canary_changes',0)}, "
                f"ApprovedBy={l.get('approved_by')}")
            if l.get("rollback_reason"):
                lines.append(f"  - Rollback: {l.get('rollback_reason')}")
    else:
        lines.append("- 없음")

    reviews=ct.get("promotion_reviews") or []
    lines+=["","## Promotion Human Reviews"]
    if reviews:
        for r in reviews[-5:]:
            lines.append(
                f"- Review #{r.get('review_id')} Candidate #{r.get('candidate_id')} "
                f"{r.get('decision')} by {r.get('reviewer')}"
                + (f" — {r.get('reason')}" if r.get('reason') else ""))
    else:
        lines.append("- 없음")

    outcomes=ct.get("canary_outcomes") or []
    lines+=["","## Canary Outcome Gate"]
    if outcomes:
        for o in outcomes[-5:]:
            lines.append(
                f"- Outcome #{o.get('outcome_id')} Lease #{o.get('lease_id')} "
                f"[{o.get('status')}] Completed={o.get('completed_changes')}, "
                f"Safe={o.get('safe_changes')}, Divergence={_pct(o.get('divergence_rate'))}, "
                f"FalseOptimism={o.get('false_optimism_count')}")
    else:
        lines.append("- 없음")

    finals=ct.get("final_promotion_reviews") or []
    lines+=["","## Final Promotion Decisions"]
    if finals:
        for r in finals[-5:]:
            lines.append(
                f"- FinalReview #{r.get('final_review_id')} Lease #{r.get('lease_id')} "
                f"{r.get('decision')} by {r.get('reviewer')}"
                + (f" — {r.get('reason')}" if r.get('reason') else ""))
    else:
        lines.append("- 없음")

    fulls=ct.get("full_promotions") or []
    lines+=["","## Full Adaptive Promotions"]
    if fulls:
        for f in fulls[-5:]:
            lines.append(
                f"- Promotion #{f.get('promotion_id')} [{f.get('status')}] "
                f"Goal={f.get('goal_profile')}, By={f.get('promoted_by')}")
            if f.get("rollback_reason"):
                lines.append(f"  - Rollback: {f.get('rollback_reason')}")
    else:
        lines.append("- 없음")

    guards=ct.get("post_promotion_guards") or []
    lines+=["","## Post-Promotion Runtime Guard"]
    if guards:
        for g in guards[-5:]:
            lines.append(
                f"- Guard #{g.get('guard_id')} Promotion #{g.get('promotion_id')} "
                f"[{g.get('status')}] Samples={g.get('sample_count')}, "
                f"Recent7={_pct(g.get('recent7_divergence_rate'))}, "
                f"Recent14={_pct(g.get('recent14_divergence_rate'))}, "
                f"FalseOptimism={g.get('false_optimism_count')}, "
                f"Drift={_pct(g.get('drift_from_canary'))}")
    else:
        lines.append("- 없음")

    health=ct.get("promotion_health") or []
    lines+=["","## Promotion Runtime Health"]
    if health:
        for h in health:
            lines.append(
                f"- Promotion #{h.get('promotion_id')} Goal={h.get('goal_profile')} "
                f"Status={h.get('promotion_status')}, RuntimeSamples={h.get('runtime_observations')}")
    else:
        lines.append("- 없음")

    dq=ct.get("decision_quality") or []
    lines+=["","## Decision Quality"]
    if dq:
        success=sum(1 for x in dq if x.get("decision_outcome")=="SUCCESS")
        failure=sum(1 for x in dq if x.get("decision_outcome")=="FAILURE")
        critical=sum(1 for x in dq if x.get("critical_error_type"))
        lines.append(f"- Samples={len(dq)}, Success={success}, Failure={failure}, CriticalErrors={critical}")
    else:
        lines.append("- 없음")

    gd=ct.get("goal_relevance_diagnostics") or []
    lines+=["","## Goal-Relevance Diagnostics"]
    if gd:
        for g in gd[-5:]:
            lines.append(
                f"- Diagnostic #{g.get('diagnostic_id')} Goal={g.get('goal_profile')} "
                f"[{g.get('status')}] Samples={g.get('sample_count')}, "
                f"Core={_pct(g.get('core_relevance_rate'))}, "
                f"Success={_pct(g.get('successful_decision_rate'))}, "
                f"Failure={_pct(g.get('failed_decision_rate'))}, "
                f"Critical={g.get('critical_error_count')}")
    else:
        lines.append("- 없음")

    doe=ct.get("decision_outcome_evidence") or []
    lines+=["","## Decision Outcome Evidence"]
    if doe:
        counts={}
        for e in doe:
            counts[e.get("status")]=counts.get(e.get("status"),0)+1
        lines.append("- " + ", ".join(f"{k}={v}" for k,v in sorted(counts.items())))
        for e in doe[-5:]:
            lines.append(
                f"- Evidence #{e.get('evidence_id')} [{e.get('status')}] "
                f"Type={e.get('evidence_type')}, Outcome={e.get('proposed_outcome')}, "
                f"Critical={e.get('proposed_critical_error_type') or '-'}")
    else:
        lines.append("- 없음")

    conf=ct.get("decision_outcome_confirmations") or []
    lines+=["","## Decision Outcome Confirmations"]
    if conf:
        for c in conf[-5:]:
            lines.append(
                f"- Confirmation #{c.get('confirmation_id')} Evidence #{c.get('evidence_id')} "
                f"{c.get('decision')} by {c.get('reviewer')}")
    else:
        lines.append("- 없음")

    eq=ct.get("evidence_priority_queue") or []
    lines+=["","## Evidence Priority Queue"]
    if eq:
        p0=sum(1 for x in eq if x.get("priority")=="P0" and x.get("status") in ("PENDING","HOLD"))
        p1=sum(1 for x in eq if x.get("priority")=="P1" and x.get("status") in ("PENDING","HOLD"))
        overdue=sum(1 for x in eq if x.get("overdue") and x.get("status") in ("PENDING","HOLD"))
        corr=sum(1 for x in eq if (x.get("independent_source_count") or 0)>=2 and x.get("status") in ("PENDING","HOLD"))
        lines.append(f"- Active P0={p0}, P1={p1}, Overdue={overdue}, Corroborated={corr}")
        for e in [x for x in eq if x.get("status") in ("PENDING","HOLD")][:5]:
            lines.append(
                f"- Evidence #{e.get('evidence_id')} {e.get('priority')} "
                f"Score={e.get('priority_score')} SLA={e.get('sla_due_at')} "
                f"Sources={e.get('independent_source_count')} "
                f"Confidence={e.get('resolution_confidence')}")
    else:
        lines.append("- 없음")

    qev=ct.get("evidence_queue_events") or []
    lines+=["","## Evidence Queue Audit"]
    if qev:
        for e in qev[-5:]:
            lines.append(
                f"- QueueEvent #{e.get('queue_event_id')} Evidence #{e.get('evidence_id')} "
                f"{e.get('event_type')} by {e.get('actor')}")
    else:
        lines.append("- 없음")

    clusters=ct.get("evidence_clusters") or []
    lines+=["","## Evidence Cluster Cases"]
    if clusters:
        critical=sum(1 for x in clusters if x.get("severity")=="CRITICAL")
        confirmed=sum(1 for x in clusters if x.get("status")=="CONFIRMED_CASE")
        open_cases=sum(1 for x in clusters if x.get("status")=="OPEN")
        lines.append(f"- Cases={len(clusters)}, Critical={critical}, Confirmed={confirmed}, Open={open_cases}")
        for c in clusters[-5:]:
            lines.append(
                f"- Cluster #{c.get('cluster_id')} [{c.get('status')}] "
                f"Severity={c.get('severity')} Evidence={c.get('evidence_count')} "
                f"Sources={c.get('independent_source_count')} "
                f"RootCause={c.get('root_cause_status')} Closure={c.get('closure_status')}")
    else:
        lines.append("- 없음")

    roots=ct.get("root_cause_attributions") or []
    lines+=["","## Root-Cause Attribution"]
    if roots:
        for r in roots[-5:]:
            lines.append(
                f"- Attribution #{r.get('attribution_id')} Cluster #{r.get('cluster_id')} "
                f"{r.get('category')} / {r.get('component')} "
                f"Confidence={r.get('confidence')} Backlog={r.get('backlog_id') or '-'}")
    else:
        lines.append("- 없음")

    closure=ct.get("cluster_closure_checks") or []
    lines+=["","## Cluster Closure Gate"]
    if closure:
        for c in closure[-5:]:
            lines.append(
                f"- Check #{c.get('closure_check_id')} Cluster #{c.get('cluster_id')} "
                f"[{c.get('status')}] UnresolvedCritical={c.get('unresolved_critical_evidence')} "
                f"OpenBacklog={c.get('open_backlog_count')} VerifiedBacklog={c.get('verified_backlog_count')}")
    else:
        lines.append("- 없음")

    rel=ct.get("source_reliability_profiles") or []
    lines+=["","## Source/Rule Reliability"]
    if rel:
        trusted=sum(1 for x in rel if x.get("band")=="TRUSTED")
        watch=sum(1 for x in rel if x.get("band")=="WATCH")
        degraded=sum(1 for x in rel if x.get("band")=="DEGRADED")
        lines.append(f"- Profiles={len(rel)}, TRUSTED={trusted}, WATCH={watch}, DEGRADED={degraded}")
        for r in rel[:5]:
            lines.append(
                f"- {r.get('source_id')} / {r.get('rule_key')} "
                f"Score={r.get('score'):.3f} [{r.get('band')}] "
                f"Critical={r.get('critical_failure_count')} Success={r.get('success_count')}")
    else:
        lines.append("- 없음")

    pvd=ct.get("preventive_verification_decisions") or []
    lines+=["","## Preventive Verification Shadow/Canary"]
    if pvd:
        shadow=sum(1 for x in pvd if x.get("production_mode")=="BASE_WITH_SHADOW")
        canary_n=sum(1 for x in pvd if x.get("production_mode")=="CANARY")
        lines.append(f"- Decisions={len(pvd)}, Shadow={shadow}, Canary={canary_n}")
        for d in pvd[-5:]:
            lines.append(
                f"- Decision #{d.get('decision_id')} {d.get('source_id')} / {d.get('rule_key')} "
                f"Band={d.get('reliability_band')} Shadow={d.get('shadow_action')} "
                f"Production={d.get('production_action')} Mode={d.get('production_mode')}")
    else:
        lines.append("- 없음")

    cans=ct.get("preventive_policy_canaries") or []
    lines+=["","## Preventive Policy Canaries"]
    if cans:
        for c in cans[-5:]:
            lines.append(
                f"- Canary #{c.get('canary_id')} {c.get('source_id')} / {c.get('rule_key')} "
                f"[{c.get('status')}] Used={c.get('used_decisions')}/{c.get('max_decisions')} "
                f"ApprovedBy={c.get('approved_by')}")
    else:
        lines.append("- 없음")

    pout=ct.get("preventive_policy_outcomes") or []
    lines+=["","## Preventive Policy Outcomes"]
    if pout:
        prevented=sum(1 for x in pout if x.get("critical_prevented"))
        false_hold=sum(1 for x in pout if x.get("false_conservative_hold"))
        lines.append(f"- Outcomes={len(pout)}, PreventedCritical={prevented}, FalseConservativeHold={false_hold}")
        for o in pout[-5:]:
            lines.append(
                f"- Outcome #{o.get('outcome_id')} Decision #{o.get('decision_id')} "
                f"{o.get('outcome_class')} Truth={o.get('event_truth')}")
    else:
        lines.append("- 없음")

    psg=ct.get("preventive_canary_safety") or []
    lines+=["","## Preventive Canary Safety Gate"]
    if psg:
        for g in psg[-5:]:
            rate=g.get("false_conservative_hold_rate")
            rate_text="-" if rate is None else f"{rate:.3f}"
            lines.append(
                f"- Canary #{g.get('canary_id')} [{g.get('status')}] "
                f"Samples={g.get('sample_count')} Prevented={g.get('prevented_critical_count')} "
                f"FalseHoldRate={rate_text}")
    else:
        lines.append("- 없음")

    pfull=ct.get("preventive_full_promotions") or []
    lines+=["","## Full Preventive Promotions"]
    if pfull:
        for f in pfull[-5:]:
            lines.append(
                f"- Promotion #{f.get('promotion_id')} {f.get('source_id')} / {f.get('rule_key')} "
                f"[{f.get('status')}] PromotedBy={f.get('promoted_by')}")
    else:
        lines.append("- 없음")

    frg=ct.get("preventive_full_runtime_guard") or []
    lines+=["","## Full Preventive Runtime Guard"]
    if frg:
        for g in frg[-5:]:
            r5=g.get("recent5_false_hold_rate")
            r10=g.get("recent10_false_hold_rate")
            r5t="-" if r5 is None else f"{r5:.3f}"
            r10t="-" if r10 is None else f"{r10:.3f}"
            lines.append(
                f"- Promotion #{g.get('promotion_id')} [{g.get('status')}] "
                f"Samples={g.get('sample_count')} MissedCritical={g.get('missed_critical_count')} "
                f"Recent5FalseHold={r5t} Recent10FalseHold={r10t} "
                f"Action={g.get('action')}")
    else:
        lines.append("- 없음")

    fro=ct.get("preventive_full_runtime_observations") or []
    lines+=["","## Full Preventive Runtime Outcomes"]
    if fro:
        missed=sum(1 for x in fro if x.get("missed_critical_failure"))
        false_hold=sum(1 for x in fro if x.get("false_conservative_hold"))
        prevented=sum(1 for x in fro if x.get("critical_prevented"))
        lines.append(
            f"- Outcomes={len(fro)}, Prevented={prevented}, "
            f"FalseConservativeHold={false_hold}, MissedCritical={missed}")
    else:
        lines.append("- 없음")

    prc=ct.get("preventive_recovery_cases") or []
    lines+=["","## Preventive Runtime Recovery"]
    if prc:
        for c in prc[-5:]:
            lines.append(
                f"- Recovery #{c.get('recovery_case_id')} {c.get('source_id')} / {c.get('rule_key')} "
                f"[{c.get('status')}] FailedPromotion=#{c.get('failed_promotion_id')} "
                f"RootCause={'Y' if c.get('root_cause') else 'N'} "
                f"Remediation={'Y' if c.get('remediation_ref') else 'N'}")
    else:
        lines.append("- 없음")

    pre=ct.get("preventive_recovery_evaluations") or []
    lines+=["","## Recovery Re-Qualification Gate"]
    if pre:
        for e in pre[-5:]:
            rate=e.get("false_conservative_hold_rate")
            rt="-" if rate is None else f"{rate:.3f}"
            lines.append(
                f"- Recovery #{e.get('recovery_case_id')} [{e.get('status')}] "
                f"Shadow={e.get('shadow_decision_count')} Confirmed={e.get('confirmed_outcome_count')} "
                f"Safe={e.get('safe_outcome_count')} MissedCritical={e.get('missed_critical_count')} "
                f"FalseHoldRate={rt}")
    else:
        lines.append("- 없음")

    rprof=ct.get("preventive_recurrence_profiles") or []
    lines+=["","## Recovery Effectiveness / Recurrence Guard"]
    if rprof:
        for r in rprof[-5:]:
            lines.append(
                f"- {r.get('source_id')} / {r.get('rule_key')} "
                f"[{r.get('risk_band')}] Recurrence={r.get('recurrence_count')} "
                f"RequalifiedFailures={r.get('requalified_failure_count')} "
                f"IneffectiveRemediation={r.get('ineffective_remediation_count')} "
                f"Restricted={'Y' if r.get('long_term_restricted') else 'N'}")
    else:
        lines.append("- 없음")

    reval=ct.get("preventive_recurrence_evaluations") or []
    lines+=["","## Escalated Re-Qualification Policy"]
    if reval:
        for e in reval[-5:]:
            lines.append(
                f"- Recovery #{e.get('recovery_case_id')} [{e.get('risk_band')}] "
                f"NeedShadow={e.get('required_shadow_decisions')} "
                f"NeedConfirmed={e.get('required_confirmed_outcomes')} "
                f"MaxFalseHold={e.get('max_false_hold_rate'):.2f} "
                f"Exception={'Y' if e.get('human_exception_required') else 'N'} "
                f"Remediation={e.get('remediation_effective')}")
    else:
        lines.append("- 없음")

    qrows=ct.get("preventive_quarantines") or []
    lines+=["","## Source/Rule Quarantine"]
    if qrows:
        for q in qrows[-5:]:
            lines.append(
                f"- Quarantine #{q.get('quarantine_id')} {q.get('source_id')} / {q.get('rule_key')} "
                f"[{q.get('status')}] TriggerRecovery=#{q.get('trigger_recovery_case_id')}")
    else:
        lines.append("- 없음")

    qeval=ct.get("preventive_reintegration_evaluations") or []
    lines+=["","## Controlled Reintegration Gate"]
    if qeval:
        for e in qeval[-5:]:
            rate=e.get("false_hold_rate")
            rt="-" if rate is None else f"{rate:.3f}"
            lines.append(
                f"- Quarantine #{e.get('quarantine_id')} [{e.get('status')}] "
                f"Shadow={e.get('shadow_decision_count')} Confirmed={e.get('confirmed_outcome_count')} "
                f"Safe={e.get('safe_outcome_count')} AltCoverage={e.get('independent_alternative_count')} "
                f"FalseHoldRate={rt} ElapsedHours={e.get('elapsed_hours'):.1f}")
    else:
        lines.append("- 없음")

    routes=ct.get("alternative_route_evaluations") or []
    lines+=["","## Alternative Source Routing"]
    if routes:
        for r in routes[-8:]:
            lines.append(
                f"- Event #{r.get('event_instance_id')} {r.get('quarantined_source_id')} "
                f"[{r.get('route_status')}] SafeCandidates={r.get('safe_candidate_count')} "
                f"IndependentGroups={r.get('independent_group_count')} "
                f"Coverage={'PRESERVED' if r.get('coverage_preserved') else 'DEGRADED'}")
    else:
        lines.append("- 없음")

    continuity=ct.get("verification_continuity_snapshots") or []
    lines+=["","## Verification Continuity"]
    if continuity:
        for c in continuity[-5:]:
            rate=c.get("coverage_preservation_rate")
            rt="-" if rate is None else f"{rate:.3f}"
            lines.append(
                f"- {c.get('source_id')} / {c.get('rule_key')} "
                f"Quarantined={c.get('quarantined_decision_count')} "
                f"RoutedVerified={c.get('routed_verified_count')} "
                f"Possible={c.get('degraded_possible_count')} "
                f"NoSafeRoute={c.get('no_safe_route_count')} "
                f"PreservationRate={rt}")
    else:
        lines.append("- 없음")

    rels=ct.get("source_relationships") or []
    lines+=["","## Source Independence Graph"]
    if rels:
        for r in rels[-8:]:
            lines.append(
                f"- {r.get('source_id_a')} ↔ {r.get('source_id_b')} "
                f"[{r.get('relationship_type')}/{r.get('confidence')}] "
                f"via {r.get('provenance')}")
    else:
        lines.append("- 없음")

    indep=ct.get("source_independence_evaluations") or []
    lines+=["","## Syndication / Independence Diagnostics"]
    if indep:
        for e in indep[-8:]:
            sig=e.get("syndication_signals_json")
            lines.append(
                f"- Event #{e.get('event_instance_id')} "
                f"{e.get('source_id_a')} ↔ {e.get('source_id_b')} "
                f"[{e.get('independence_status')}] Relation={e.get('relationship_type')} "
                f"Signals={sig}")
    else:
        lines.append("- 없음")

    cps=ct.get("cross_post_clusters") or []
    lines+=["","## Automated Origin Inference / Cross-Post Clusters"]
    if cps:
        for c in cps[-8:]:
            lines.append(
                f"- Event #{c.get('event_instance_id')} Cluster #{c.get('cluster_id')} "
                f"[{c.get('status')}] Members={c.get('member_count')} "
                f"LikelyOrigin={c.get('likely_origin_source_id')} Confidence={c.get('confidence')}")
    else:
        lines.append("- 없음")

    cals=ct.get("origin_inference_calibrations") or []
    lines+=["","## Origin Confidence Calibration"]
    if cals:
        c=cals[-1]
        precision=c.get("precision")
        fp=c.get("false_positive_rate")
        lines.append(
            f"- [{c.get('recommendation_status')}] Reviews={c.get('reviewed_cluster_count')} "
            f"ConfirmedSyndication={c.get('confirmed_syndication_count')} "
            f"ConfirmedIndependent={c.get('confirmed_independent_count')} "
            f"Precision={'-' if precision is None else f'{precision:.3f}'} "
            f"FalsePositive={'-' if fp is None else f'{fp:.3f}'} "
            f"Threshold={c.get('baseline_text_threshold')}→"
            f"{c.get('shadow_recommended_text_threshold')} (SHADOW ONLY)")
    else:
        lines.append("- 없음")

    prios=ct.get("origin_review_priorities") or []
    lines+=["","## Origin Human Review Priority"]
    if prios:
        latest={}
        for r in prios:
            latest[r.get("cluster_id")]=r
        for r in sorted(
            latest.values(),
            key=lambda x:(-float(x.get("priority_score") or 0),x.get("cluster_id") or 0)
        )[:8]:
            lines.append(
                f"- Cluster #{r.get('cluster_id')} [{r.get('priority_band')}] "
                f"Score={r.get('priority_score')} Members={r.get('member_count')} "
                f"MaxSimilarity={r.get('max_text_similarity')} "
                f"RouteImpact={r.get('route_impact_count')}")
    else:
        lines.append("- 없음")

    tc=ct.get("origin_threshold_candidates") or []
    tcan=ct.get("origin_threshold_canaries") or []
    tprom=ct.get("origin_threshold_promotions") or []
    trun=ct.get("origin_threshold_runtime") or {}
    lines+=["","## Threshold Promotion Gate / Canary"]
    lines.append(
        f"- Runtime Full Threshold={trun.get('effective_full_threshold',0.86)} "
        f"ActiveCanary={((trun.get('active_canary') or {}).get('canary_id')) or '-'} "
        f"ActivePromotion={((trun.get('active_full_promotion') or {}).get('promotion_id')) or '-'}")
    if tc:
        c=tc[-1]
        lines.append(
            f"- Candidate #{c.get('candidate_id')} [{c.get('status')}] "
            f"Gate={c.get('shadow_gate_status')} "
            f"{c.get('baseline_threshold')}→{c.get('candidate_threshold')} "
            f"Reviews={c.get('decisive_review_count')} "
            f"CriticalMiss={c.get('critical_missed_syndication_count')}")
    if tcan:
        c=tcan[-1]
        lines.append(
            f"- Canary #{c.get('canary_id')} [{c.get('status')}] "
            f"Assignments={c.get('assigned_count')}/{c.get('max_assignments')} "
            f"Safe={c.get('confirmed_syndication_count')} "
            f"FalsePositive={c.get('confirmed_independent_count')} "
            f"Missed={c.get('missed_syndication_count')}")
    if tprom:
        p=tprom[-1]
        lines.append(
            f"- Promotion #{p.get('promotion_id')} [{p.get('status')}] "
            f"ProductionThreshold={p.get('production_threshold')}")

    guard=ct.get("origin_threshold_guard_status") or {}
    lines+=["","## Post-Promotion Threshold Runtime Guard"]
    ap=guard.get("active_promotion")
    ag=guard.get("active_guard")
    if ap:
        lines.append(
            f"- Active Promotion #{ap.get('promotion_id')} "
            f"Threshold={ap.get('production_threshold')} "
            f"Guard={((ag or {}).get('overall_status')) or '-'}")
        for w in (ag or {}).get("windows",[]):
            lines.append(
                f"- Rolling-{w.get('window_size')} [{w.get('status')}] "
                f"N={w.get('observed_count')} "
                f"FP={w.get('promoted_false_positive')} "
                f"Miss={w.get('promoted_missed_syndication')} "
                f"Regression={w.get('promotion_regression_count')} "
                f"CriticalRegression={w.get('critical_regression_count')}")
    else:
        lines.append("- Active Full threshold promotion 없음")

    recoveries=ct.get("origin_threshold_recovery_cases") or []
    lines+=["","## Threshold Recovery / Re-Qualification"]
    if recoveries:
        for r in recoveries[-5:]:
            lines.append(
                f"- Recovery #{r.get('recovery_case_id')} [{r.get('status')}] "
                f"Promotion=#{r.get('promotion_id')} "
                f"Failed={r.get('failed_threshold')}→Fallback={r.get('fallback_threshold')} "
                f"SafeShadow={r.get('safe_shadow_outcome_count')}/"
                f"{r.get('required_shadow_outcomes')}")
    else:
        lines.append("- 없음")

    rcs=ct.get("origin_threshold_root_causes") or []
    reqs=ct.get("origin_threshold_adaptive_requirements") or []
    lines+=["","## Threshold Recovery Root-Cause / Adaptive Gate"]
    if rcs:
        r=rcs[-1]
        lines.append(
            f"- RootCause #{r.get('root_cause_id')} [{r.get('risk_band')}] "
            f"Failure={r.get('failure_class')} Cause={r.get('root_cause_type')} "
            f"Source={r.get('dominant_source_id') or '-'} "
            f"Platform={r.get('dominant_platform') or '-'} "
            f"Repeat={r.get('repeated_root_cause_count')}")
    else:
        lines.append("- Root cause 없음")
    if reqs:
        q=reqs[-1]
        lines.append(
            f"- Adaptive Requirement [{q.get('risk_band')}] "
            f"Safe={q.get('required_safe_shadow_outcomes')} "
            f"Sources={q.get('required_distinct_sources')} "
            f"Platforms={q.get('required_distinct_platforms')} "
            f"RemediationRequired={bool(q.get('require_remediation'))}")

    recs=ct.get("origin_threshold_recurrence_profiles") or []
    restrictions=ct.get("origin_threshold_long_term_restrictions") or []
    remstats=ct.get("origin_threshold_remediation_type_stats") or []
    lines+=["","## Root-Cause Recurrence Guard / Long-Term Restriction"]
    if recs:
        for r in recs[-5:]:
            lines.append(
                f"- [{r.get('risk_band')}] {r.get('signature')} "
                f"Recurrence={r.get('recurrence_count')} "
                f"PostRequal={r.get('post_requalification_recurrence_count')} "
                f"FailedEffectiveRemediation={r.get('failed_effective_remediation_count')} "
                f"Restricted={bool(r.get('long_term_restricted'))}")
    else:
        lines.append("- Recurrence profile 없음")
    active=[r for r in restrictions if r.get("status")=="ACTIVE"]
    if active:
        for r in active[-5:]:
            lines.append(
                f"- Restriction #{r.get('restriction_id')} ACTIVE "
                f"Signature={r.get('signature')} "
                f"Recurrence={r.get('recurrence_count')} "
                f"FailedEffective={r.get('failed_effective_remediation_count')}")
    else:
        lines.append("- Active long-term restriction 없음")

    lines+=["","## Remediation Effectiveness History"]
    if remstats:
        for r in remstats:
            rate=r.get("sustained_success_rate")
            lines.append(
                f"- {r.get('remediation_type')} Total={r.get('total')} "
                f"Sustained={r.get('sustained_effective')} "
                f"RecurrenceFailed={r.get('recurrence_failed')} "
                f"Pending={r.get('pending')} "
                f"SuccessRate={'-' if rate is None else f'{rate:.3f}'}")
    else:
        lines.append("- 없음")

    scopes=ct.get("origin_threshold_restriction_scopes") or []
    scope_routes=ct.get("origin_threshold_scope_routes") or []
    lines+=["","## Restriction Scope Isolation / Safe Alternative Path"]
    active_scopes=[s for s in scopes if s.get("status")=="ACTIVE"]
    if active_scopes:
        for s in active_scopes[-8:]:
            lines.append(
                f"- Scope #{s.get('scope_id')} [{s.get('scope_type')}] "
                f"Source={s.get('source_id') or '-'} "
                f"Platform={s.get('platform') or '-'} "
                f"Rule={s.get('rule_key') or '-'} "
                f"Action={s.get('production_action')} "
                f"Shadow={bool(s.get('shadow_learning_enabled'))}")
    else:
        lines.append("- Active scope 없음")
    if scope_routes:
        for r in scope_routes[-5:]:
            lines.append(
                f"- Route #{r.get('scope_route_id')} [{r.get('route_status')}] "
                f"Blocked={len(r.get('blocked_source_ids') or [])} "
                f"Safe={len(r.get('safe_source_ids') or [])} "
                f"CoveragePreserved={bool(r.get('coverage_preserved'))}")
    else:
        lines.append("- Scoped route evaluation 없음")

    reintegration_evals=ct.get("origin_threshold_scope_reintegration_evaluations") or []
    reintegration_canaries=ct.get("origin_threshold_scope_reintegration_canaries") or []
    lines+=["","## Scoped Reintegration Gate / Coverage Preservation Guard"]
    if reintegration_evals:
        e=reintegration_evals[-1]
        lines.append(
            f"- Scope #{e.get('scope_id')} [{e.get('status')}] "
            f"Shadow={e.get('shadow_count')}/{e.get('required_shadow_count')} "
            f"HumanSafe={e.get('safe_human_count')}/{e.get('required_human_count')} "
            f"Events={e.get('distinct_event_count')}/{e.get('required_distinct_events')} "
            f"FalseCorroboration={e.get('false_corroboration_count')} "
            f"MissedSyndication={e.get('missed_syndication_count')} "
            f"AltQualityDelta={e.get('avg_alternative_quality_delta')}")
    else:
        lines.append("- Reintegration evaluation 없음")
    if reintegration_canaries:
        for c in reintegration_canaries[-5:]:
            lines.append(
                f"- Canary #{c.get('canary_id')} [{c.get('status')}] "
                f"Assigned={c.get('assigned_count')}/{c.get('max_assignments')} "
                f"Safe={c.get('safe_count')} Unsafe={c.get('unsafe_count')} Hold={c.get('hold_count')}")
    else:
        lines.append("- Reintegration canary 없음")

    post_obs=ct.get("origin_threshold_post_reintegration_observations") or []
    post_evals=ct.get("origin_threshold_post_reintegration_evaluations") or []
    post_reiso=ct.get("origin_threshold_post_reintegration_reisolations") or []
    lines+=["","## Post-Reintegration Runtime Guard / Automatic Scope Re-Isolation"]
    if post_obs:
        last=post_obs[-1]
        lines.append(
            f"- Last Observation Scope={last.get('scope_id')} Event={last.get('event_instance_id')} "
            f"Outcome={last.get('human_outcome')} Critical={bool(last.get('critical'))} "
            f"FalseCorroboration={bool(last.get('false_corroboration'))} "
            f"MissedSyndication={bool(last.get('missed_syndication'))} "
            f"Counterfactual={last.get('counterfactual_class')}")
    else:
        lines.append("- Post-release observation 없음")
    latest_by_window={}
    for e in post_evals:
        latest_by_window[(e.get('scope_id'),e.get('window_size'))]=e
    for (_,w),e in list(latest_by_window.items())[-6:]:
        lines.append(
            f"- Rolling {w} [{e.get('status')}] N={e.get('sample_count')} "
            f"Regression={e.get('regression_count')} "
            f"FalseCorr={e.get('false_corroboration_count')} "
            f"Miss={e.get('missed_syndication_count')} "
            f"Critical={e.get('critical_regression_count')} "
            f"CoverageReg={e.get('coverage_regression_count')}")
    active=[r for r in post_reiso if r.get("status")=="ACTIVE"]
    if active:
        for r in active[-5:]:
            lines.append(
                f"- Re-Isolation #{r.get('reisolation_id')} ACTIVE "
                f"Scope={r.get('scope_id')} PenaltyLevel={r.get('requirement_penalty_level')} "
                f"Reason={r.get('reason')}")
    else:
        lines.append("- Active automatic re-isolation 없음")

    post_roots=ct.get("origin_threshold_post_reintegration_root_causes") or []
    post_routes=ct.get("origin_threshold_post_reintegration_remediation_routes") or []
    lines+=["","## Post-Reintegration Root Cause / Remediation Routing"]
    if post_roots:
        r=post_roots[-1]
        lines.append(
            f"- RootCause #{r.get('post_root_cause_id')} "
            f"[{r.get('root_cause_type')}] Secondary={r.get('secondary_root_cause_type') or '-'} "
            f"Severity={r.get('severity')} ReIsolation={r.get('reisolation_id')}")
    else:
        lines.append("- Post-reintegration root cause 없음")
    if post_routes:
        rr=post_routes[-1]
        lines.append(
            f"- Route #{rr.get('remediation_route_id')} "
            f"Required={rr.get('required_remediation_type')} "
            f"Escalation={rr.get('escalation_level')} "
            f"ArchitectureReview={bool(rr.get('architecture_review_required'))} "
            f"Blocked={rr.get('blocked_remediation_types')}")
    else:
        lines.append("- Remediation route 없음")

    arch_plans=ct.get("origin_threshold_architecture_plans") or []
    lines+=["","## Architecture Escalation / Cross-Layer Remediation Plan"]
    if arch_plans:
        p=arch_plans[-1]
        effective=sum(1 for s in (p.get("steps") or []) if s.get("status")=="EFFECTIVE")
        lines.append(
            f"- Plan #{p.get('architecture_plan_id')} [{p.get('status')}] "
            f"Scope={p.get('scope_id')} Steps={effective}/{p.get('required_step_count')} "
            f"Route={p.get('remediation_route_id')}")
        for s in (p.get("steps") or []):
            lines.append(
                f"- Step {s.get('step_order')} {s.get('remediation_type')} "
                f"[{s.get('status')}] Remediation={s.get('remediation_id') or '-'}")
    else:
        lines.append("- Architecture escalation plan 없음")

    arch_runtime=ct.get("origin_threshold_architecture_runtime_outcomes") or []
    arch_profiles=ct.get("origin_threshold_architecture_effectiveness_profiles") or []
    arch_recs=ct.get("origin_threshold_architecture_recommendations") or []
    lines+=["","## Architecture Plan Runtime Outcome / Effectiveness Memory"]
    if arch_runtime:
        r=arch_runtime[-1]
        lines.append(
            f"- Runtime #{r.get('architecture_runtime_outcome_id')} "
            f"Plan={r.get('architecture_plan_id')} [{r.get('status')}] "
            f"RootCause={r.get('root_cause_type')} Signature={r.get('plan_signature')} "
            f"Obs={r.get('observation_count')} Healthy={r.get('healthy_observation_count')} "
            f"Regression={r.get('regression_observation_count')} "
            f"DaysToReIsolation={r.get('days_to_reisolation')}")
    else:
        lines.append("- Architecture runtime outcome 없음")
    if arch_profiles:
        p=arch_profiles[0]
        lines.append(
            f"- Best Memory RootCause={p.get('root_cause_type')} "
            f"Signature={p.get('plan_signature')} Attempts={p.get('attempt_count')} "
            f"Success={p.get('sustained_success_count')} Failure={p.get('recurrence_failure_count')} "
            f"Confidence={p.get('confidence_band')} Score={p.get('effectiveness_score')}")
    else:
        lines.append("- Architecture effectiveness profile 없음")
    if arch_recs:
        r=arch_recs[-1]
        lines.append(
            f"- Recommendation [{r.get('source')}] {r.get('recommended_signature')} "
            f"Confidence={r.get('confidence_band')} Attempts={r.get('evidence_attempt_count')}")
    else:
        lines.append("- Architecture recommendation history 없음")

    cmp_scores=ct.get("origin_threshold_architecture_comparative_scores") or []
    ctx_recs=ct.get("origin_threshold_architecture_context_recommendations") or []
    lines+=["","## Architecture Plan Comparative Ranking / Context-Aware Recommendation"]
    if cmp_scores:
        latest_context=cmp_scores[-1].get("context_signature")
        ranked=[x for x in cmp_scores if x.get("context_signature")==latest_context]
        ranked=sorted(ranked,key=lambda x:x.get("comparative_score") or 0,reverse=True)[:3]
        for i,r in enumerate(ranked,1):
            lines.append(
                f"- Rank {i} {r.get('plan_signature')} "
                f"Score={r.get('comparative_score'):.3f} "
                f"Wilson={r.get('wilson_lower_bound'):.3f} "
                f"Context={r.get('context_similarity'):.3f} "
                f"N={r.get('decisive_count')} "
                f"Confidence={r.get('confidence_band')}")
    else:
        lines.append("- Comparative ranking 없음")
    if ctx_recs:
        r=ctx_recs[-1]
        lines.append(
            f"- Recommendation [{r.get('source')}] {r.get('selected_plan_signature')} "
            f"Score={r.get('comparative_score')} Margin={r.get('score_margin')} "
            f"Confidence={r.get('confidence_band')} Evidence={r.get('evidence_attempt_count')}")
    else:
        lines.append("- Context-aware recommendation 없음")

    challenges=ct.get("origin_threshold_architecture_recommendation_challenges") or []
    challenge_runtime=ct.get("origin_threshold_architecture_challenge_runtime_results") or []
    quality_profiles=ct.get("origin_threshold_architecture_recommendation_quality_profiles") or []
    lines+=["","## Recommendation Shadow Challenge / Human Acceptance Outcome"]
    if challenges:
        c=challenges[-1]
        lines.append(
            f"- Challenge #{c.get('challenge_id')} [{c.get('status')}] "
            f"Recommended={c.get('recommended_signature')} "
            f"Baseline={c.get('deterministic_signature')} "
            f"Source={c.get('recommendation_source')}")
    else:
        lines.append("- Recommendation challenge 없음")
    if challenge_runtime:
        r=challenge_runtime[-1]
        lines.append(
            f"- Runtime Choice={r.get('selected_side')} "
            f"Status={r.get('runtime_status')} Verdict={r.get('counterfactual_verdict')} "
            f"DaysToReIsolation={r.get('days_to_reisolation')}")
    else:
        lines.append("- Challenge runtime outcome 없음")
    if quality_profiles:
        q=quality_profiles[-1]
        lines.append(
            f"- Recommendation Quality RootCause={q.get('root_cause_type')} "
            f"Challenges={q.get('challenge_count')} Accepted={q.get('accepted_count')} "
            f"Baseline={q.get('baseline_selected_count')} "
            f"Helpful={q.get('recommendation_helpful_count')} "
            f"Harmful={q.get('recommendation_harmful_count')} "
            f"Confidence={q.get('confidence_band')}")
    else:
        lines.append("- Recommendation quality profile 없음")

    policy_states=ct.get("origin_threshold_recommendation_policy_states") or []
    policy_candidates=ct.get("origin_threshold_recommendation_policy_candidates") or []
    policy_assignments=ct.get("origin_threshold_recommendation_policy_assignments") or []
    policy_events=ct.get("origin_threshold_recommendation_policy_events") or []
    lines+=["","## Recommendation Policy Promotion Gate / Algorithm Rollback"]
    if policy_states:
        for s in policy_states[-5:]:
            lines.append(
                f"- RootCause={s.get('root_cause_type')} Mode={s.get('mode')} "
                f"Canary={s.get('canary_assigned_count')}/{s.get('canary_max_assignments')} "
                f"Helpful={s.get('canary_helpful_count')} Harmful={s.get('canary_harmful_count')} "
                f"Neutral={s.get('canary_neutral_count')} "
                f"Rollback={s.get('rollback_reason') or '-'}")
    else:
        lines.append("- Recommendation policy state 없음")
    if policy_candidates:
        c=policy_candidates[-1]
        lines.append(
            f"- Candidate #{c.get('policy_candidate_id')} [{c.get('status')}] "
            f"RootCause={c.get('root_cause_type')} N={c.get('runtime_decisive_count')} "
            f"Helpful={c.get('helpful_rate'):.3f} Harmful={c.get('harmful_rate'):.3f} "
            f"Acceptance={c.get('acceptance_rate')}")
    if policy_assignments:
        a=policy_assignments[-1]
        lines.append(
            f"- Canary Assignment #{a.get('policy_canary_assignment_id')} "
            f"Challenge={a.get('challenge_id')} [{a.get('status')}] "
            f"Verdict={a.get('verdict') or '-'}")
    if policy_events:
        e=policy_events[-1]
        lines.append(
            f"- Last Policy Event={e.get('event_type')} RootCause={e.get('root_cause_type')}")

    recovery_cases=ct.get("origin_threshold_recommendation_recovery_cases") or []
    lines+=["","## Policy Rollback Recovery / Re-Promotion Qualification"]
    if recovery_cases:
        c=recovery_cases[-1]
        lines.append(
            f"- Recovery #{c.get('policy_recovery_case_id')} "
            f"RootCause={c.get('root_cause_type')} RollbackNo={c.get('rollback_number')} "
            f"Failure={c.get('failure_type')} Status={c.get('status')}")
    else:
        lines.append("- Recommendation rollback recovery case 없음")

    alg_versions=ct.get("origin_threshold_recommendation_algorithm_versions") or []
    alg_lineage=ct.get("origin_threshold_recommendation_algorithm_lineage") or []
    recovery_vlinks=ct.get("origin_threshold_recommendation_recovery_version_links") or []
    lines+=["","## Recommendation Algorithm Versioning / Recovery Lineage"]
    if alg_versions:
        for v in alg_versions[-5:]:
            lines.append(
                f"- Version #{v.get('algorithm_version_id')} "
                f"{v.get('version_label')} RootCause={v.get('root_cause_type')} "
                f"Status={v.get('status')} Parent={v.get('parent_algorithm_version_id') or '-'}")
    else:
        lines.append("- Recommendation algorithm version 없음")
    if recovery_vlinks:
        l=recovery_vlinks[-1]
        lines.append(
            f"- Recovery Version Link Case={l.get('policy_recovery_case_id')} "
            f"Failed={l.get('failed_algorithm_version_id')} "
            f"Successor={l.get('successor_algorithm_version_id') or '-'} "
            f"Status={l.get('status')}")
    if alg_lineage:
        lines.append(f"- Algorithm lineage edges={len(alg_lineage)}")

    version_cohorts=ct.get("origin_threshold_recommendation_algorithm_version_cohorts") or []
    version_profiles=ct.get("origin_threshold_recommendation_algorithm_version_profiles") or []
    lines+=["","## Algorithm Version Runtime Cohort / Version-Level Promotion Memory"]
    if version_profiles:
        for p in version_profiles[-5:]:
            lines.append(
                f"- Version={p.get('algorithm_version_id')} Context={p.get('context_signature')} "
                f"N={p.get('decisive_runtime_count')} Canary={p.get('canary_runtime_count')} "
                f"Prod={p.get('production_runtime_count')} Helpful={p.get('helpful_count')} "
                f"Harmful={p.get('harmful_count')} Rollback={p.get('rollback_count')} "
                f"Safety={p.get('safety_band')} Memory={p.get('promotion_memory_status')} "
                f"MedianSurvival={p.get('median_survival_days')}")
    else:
        lines.append("- Algorithm version runtime profile 없음")
    if version_cohorts:
        c=version_cohorts[-1]
        lines.append(
            f"- Latest Cohort Version={c.get('algorithm_version_id')} "
            f"Phase={c.get('runtime_phase')} Runtime={c.get('runtime_status')} "
            f"Verdict={c.get('counterfactual_verdict') or '-'} "
            f"Context={c.get('context_signature')}")

    version_gates=ct.get("origin_threshold_recommendation_version_promotion_gates") or []
    supersede_cmp=ct.get("origin_threshold_recommendation_version_supersede_comparisons") or []
    version_reviews=ct.get("origin_threshold_recommendation_version_promotion_reviews") or []
    lines+=["","## Version-Aware Promotion Gate / Supersede Decision"]
    if version_gates:
        g=version_gates[-1]
        lines.append(
            f"- Version={g.get('algorithm_version_id')} Status={g.get('status')} "
            f"Context={g.get('selected_context_signature') or '-'} "
            f"CandidateScore={g.get('candidate_score')} "
            f"Incumbent={g.get('incumbent_algorithm_version_id') or '-'} "
            f"IncumbentScore={g.get('incumbent_score')} Margin={g.get('score_margin')} "
            f"SupersedeAllowed={bool(g.get('supersede_allowed'))}")
    else:
        lines.append("- Version promotion gate 없음")
    if supersede_cmp:
        c=supersede_cmp[-1]
        lines.append(
            f"- Supersede Compare Candidate={c.get('candidate_algorithm_version_id')} "
            f"Incumbent={c.get('incumbent_algorithm_version_id')} "
            f"CandidateWilson={c.get('candidate_wilson_lower'):.3f} "
            f"IncumbentWilson={c.get('incumbent_wilson_lower'):.3f} "
            f"Margin={c.get('score_margin'):.3f} Status={c.get('status')}")
    if version_reviews:
        r=version_reviews[-1]
        lines.append(
            f"- Human Version Review Version={r.get('algorithm_version_id')} "
            f"Decision={r.get('decision')} Reviewer={r.get('reviewer')}")

    fallback_evals=ct.get("origin_threshold_recommendation_supersede_guard_evaluations") or []
    version_fallbacks=ct.get("origin_threshold_recommendation_version_fallbacks") or []
    lines+=["","## Supersede Runtime Guard / Automatic Version Fallback"]
    if fallback_evals:
        e=fallback_evals[-1]
        lines.append(
            f"- FailingVersion={e.get('failing_algorithm_version_id')} "
            f"Fallback={e.get('fallback_algorithm_version_id') or '-'} "
            f"Status={e.get('status')} Action={e.get('action')} "
            f"Context={e.get('context_signature') or '-'} "
            f"FallbackN={e.get('fallback_decisive_count')} "
            f"FallbackProd={e.get('fallback_production_count')} "
            f"FallbackHelpful={e.get('fallback_helpful_count')} "
            f"FallbackHarmful={e.get('fallback_harmful_count')} "
            f"MedianSurvival={e.get('fallback_median_survival_days')}")
    else:
        lines.append("- Supersede runtime guard evaluation 없음")
    if version_fallbacks:
        f=version_fallbacks[-1]
        lines.append(
            f"- Fallback #{f.get('version_fallback_id')} "
            f"{f.get('failing_algorithm_version_id')}→{f.get('fallback_algorithm_version_id')} "
            f"Status={f.get('status')} Recovery={f.get('recovery_case_id') or '-'}")

    fv_gens=ct.get("origin_threshold_recommendation_fallback_verification_generations") or []
    fv_pairs=ct.get("origin_threshold_recommendation_fallback_pair_profiles") or []
    lines+=["","## Fallback Runtime Verification / Anti-Ping-Pong Guard"]
    if fv_gens:
        g=fv_gens[-1]
        lines.append(
            f"- Generation={g.get('fallback_verification_generation_id')} "
            f"Pair={g.get('pair_signature')} Status={g.get('status')} "
            f"Observed={g.get('observation_count')}/{g.get('max_observations')} "
            f"Helpful={g.get('helpful_count')} Harmful={g.get('harmful_count')} "
            f"Neutral={g.get('neutral_count')}")
    else:
        lines.append("- Fallback verification generation 없음")
    if fv_pairs:
        p=fv_pairs[-1]
        lines.append(
            f"- PairProfile={p.get('pair_signature')} "
            f"Fallbacks={p.get('executed_fallback_count')} "
            f"Stable={p.get('stable_verification_count')} "
            f"Failed={p.get('failed_verification_count')} "
            f"PingPongBlocked={bool(p.get('anti_ping_pong_blocked'))}")

    family_profiles=ct.get("origin_threshold_recommendation_fallback_family_profiles") or []
    family_reviews=ct.get("origin_threshold_recommendation_fallback_family_reviews") or []
    lines+=["","## Fallback Stability Memory / Version Family Circuit Breaker"]
    if family_profiles:
        p=family_profiles[-1]
        lines.append(
            f"- Family={p.get('family_signature')} Root={p.get('family_root_algorithm_version_id')} "
            f"FallbackTarget={p.get('fallback_target_algorithm_version_id')} "
            f"Fallbacks={p.get('executed_fallback_count')} "
            f"DistinctFailing={p.get('distinct_failing_version_count')} "
            f"Stable={p.get('stable_verification_count')} Watch={p.get('watch_verification_count')} "
            f"Failed={p.get('failed_verification_count')} "
            f"Circuit={p.get('circuit_state')} "
            f"ArchitectureReview={bool(p.get('architecture_review_required'))}")
    else:
        lines.append("- Version Family fallback profile 없음")
    if family_reviews:
        r=family_reviews[-1]
        lines.append(
            f"- Family Review Profile={r.get('fallback_family_profile_id')} "
            f"Decision={r.get('decision')} Reviewer={r.get('reviewer')}")

    family_recovery=ct.get("origin_threshold_recommendation_fallback_family_recovery_cases") or []
    family_recovery_evals=ct.get("origin_threshold_recommendation_fallback_family_recovery_evaluations") or []
    lines+=["","## Family Recovery Qualification / Circuit Re-Arm Gate"]
    if family_recovery:
        c=family_recovery[-1]
        lines.append(
            f"- RecoveryCase={c.get('family_recovery_case_id')} "
            f"Family={c.get('family_signature')} Status={c.get('status')} "
            f"Candidate={c.get('candidate_algorithm_version_id') or '-'} "
            f"CanaryFallback={c.get('canary_used_fallbacks')}/{c.get('canary_max_fallbacks')} "
            f"ReadyAt={c.get('ready_at') or '-'} RearmedAt={c.get('rearmed_at') or '-'} "
            f"StabilizedAt={c.get('stabilized_at') or '-'}")
    else:
        lines.append("- Family recovery case 없음")
    if family_recovery_evals:
        e=family_recovery_evals[-1]
        lines.append(
            f"- Qualification={e.get('status')} "
            f"ArchitectureReview={bool(e.get('architecture_review_confirmed'))} "
            f"RemediationEffective={bool(e.get('remediation_effective'))} "
            f"CandidateReady={bool(e.get('candidate_version_ready'))} "
            f"Decisive={e.get('decisive_count')}/8 Helpful={e.get('helpful_count')}/7 "
            f"Harmful={e.get('harmful_count')}")

    family_generations=ct.get("origin_threshold_recommendation_fallback_family_generation_outcomes") or []
    family_effectiveness=ct.get("origin_threshold_recommendation_fallback_family_effectiveness_profiles") or []
    lines+=["","## Family Generation Runtime Memory / Re-Arm Effectiveness"]
    if family_generations:
        g=family_generations[-1]
        lines.append(
            f"- Generation={g.get('family_generation_outcome_id')} "
            f"Family={g.get('family_signature')} Status={g.get('status')} "
            f"Candidate={g.get('candidate_algorithm_version_id')} "
            f"Remediation={g.get('remediation_type')}:{g.get('remediation_ref')} "
            f"Observed={g.get('observation_count')} Healthy={g.get('healthy_observation_count')} "
            f"Harmful={g.get('harmful_observation_count')} "
            f"DaysToRecurrence={g.get('days_to_family_recurrence')}")
    else:
        lines.append("- Family generation runtime outcome 없음")
    if family_effectiveness:
        p=family_effectiveness[-1]
        lines.append(
            f"- Effectiveness Family={p.get('family_signature')} "
            f"Remediation={p.get('remediation_type')}:{p.get('remediation_ref')} "
            f"Attempts={p.get('attempt_count')} Sustained={p.get('sustained_success_count')} "
            f"Recurrence={p.get('recurrence_failure_count')} "
            f"Confidence={p.get('confidence_band')} Band={p.get('effectiveness_band')} "
            f"AvgDaysToRecurrence={p.get('avg_days_to_family_recurrence')}")

    remediation_rankings=ct.get("origin_threshold_recommendation_fallback_family_remediation_rankings") or []
    remediation_recommendations=ct.get("origin_threshold_recommendation_fallback_family_remediation_recommendations") or []
    remediation_selections=ct.get("origin_threshold_recommendation_fallback_family_remediation_selection_reviews") or []
    lines+=["","## Family Remediation Recommendation / Conservative Effectiveness Ranking"]
    if remediation_rankings:
        latest_case=max(r.get("family_recovery_case_id",0) for r in remediation_rankings)
        case_rankings=[r for r in remediation_rankings if r.get("family_recovery_case_id")==latest_case]
        r=min(case_rankings,key=lambda x:x.get("rank_position",999))
        lines.append(
            f"- TopRank Case={r.get('family_recovery_case_id')} Rank={r.get('rank_position')} "
            f"Remediation={r.get('remediation_type')}:{r.get('remediation_ref')} "
            f"State={r.get('rank_state')} Score={r.get('conservative_score'):.3f} "
            f"ContextSimilarity={r.get('context_similarity'):.2f} "
            f"Attempts={r.get('attempt_count')} Sustained={r.get('sustained_success_count')} "
            f"Recurrence={r.get('recurrence_failure_count')} "
            f"Wilson={r.get('wilson_lower_bound'):.3f}")
    else:
        lines.append("- Family remediation ranking 없음")
    if remediation_recommendations:
        r=remediation_recommendations[-1]
        lines.append(
            f"- Recommendation Case={r.get('family_recovery_case_id')} "
            f"Source={r.get('source')} Status={r.get('status')} "
            f"Remediation={r.get('recommended_remediation_type') or '-'}:"
            f"{r.get('recommended_remediation_ref') or '-'} "
            f"Score={r.get('recommended_score')} Margin={r.get('score_margin')} "
            f"HumanSelectionRequired={bool(r.get('human_selection_required'))}")
    if remediation_selections:
        s=remediation_selections[-1]
        lines.append(
            f"- Human Architecture Selection Case={s.get('family_recovery_case_id')} "
            f"Decision={s.get('decision')} "
            f"Selected={s.get('selected_remediation_type') or '-'}:"
            f"{s.get('selected_remediation_ref') or '-'} "
            f"Reviewer={s.get('reviewer')}")

    reco_outcomes=ct.get("origin_threshold_recommendation_fallback_family_recommendation_outcomes") or []
    reco_profiles=ct.get("origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles") or []
    lines+=["","## Recommendation Runtime Outcome / Selection Effectiveness"]
    if reco_outcomes:
        o=reco_outcomes[-1]
        lines.append(
            f"- Case={o.get('family_recovery_case_id')} "
            f"Recommended={o.get('recommended_remediation_ref') or '-'} "
            f"Selected={o.get('selected_remediation_ref') or '-'} "
            f"Accepted={bool(o.get('recommendation_accepted'))} "
            f"Override={bool(o.get('human_override'))} "
            f"Generation={o.get('generation_status')} "
            f"Outcome={o.get('outcome_class')} "
            f"Regret={o.get('selection_regret_score')}")
    else:
        lines.append("- Recommendation runtime outcome 없음")
    if reco_profiles:
        p=reco_profiles[-1]
        lines.append(
            f"- Effectiveness Family={p.get('family_signature')} "
            f"AcceptanceRate={p.get('acceptance_rate')} "
            f"HelpfulRate={p.get('recommendation_helpful_rate')} "
            f"OverrideSuccessRate={p.get('override_success_rate')} "
            f"AvgRegret={p.get('avg_selection_regret')} "
            f"Calibration={p.get('calibration_band')}")

    lines+=["","## Operator Decision",
            "- GREEN: 자동 운영 지속",
            "- YELLOW: Human Review Queue 우선 확인",
            "- RED: P0 해결 전 VERIFIED 결과 외부 노출 금지"]
    return "\n".join(lines)
