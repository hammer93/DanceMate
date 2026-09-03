import json
from datetime import datetime, timezone

POLICY_VERSION="v0.62"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _recovery(con,recovery_case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recovery_cases
                     WHERE recovery_case_id=?""",(recovery_case_id,)).fetchone()
    if not r: raise ValueError("recovery case not found")
    return dict(r)

def _promotion_observations(con,promotion_id):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_runtime_observations
           WHERE promotion_id=? ORDER BY runtime_observation_id""",
        (promotion_id,)).fetchall()]

def _source_platform_context(con,cluster_id):
    if not cluster_id:
        return []
    rows=con.execute("""SELECT DISTINCT m.source_id,s.platform
      FROM cross_post_cluster_members m
      LEFT JOIN sources s ON s.source_id=m.source_id
      WHERE m.cluster_id=?""",(cluster_id,)).fetchall()
    return [{"source_id":r["source_id"],"platform":r["platform"] or "UNKNOWN"} for r in rows]

def _failure_class(rows):
    bad=[r for r in rows if r["counterfactual_class"]=="PROMOTION_REGRESSION"]
    if not bad: return "NO_PROMOTION_REGRESSION"
    misses=sum(r["human_outcome"]=="CONFIRM_SYNDICATION" for r in bad)
    fps=sum(r["human_outcome"]=="CONFIRM_INDEPENDENT" for r in bad)
    if misses and not fps: return "MISSED_SYNDICATION"
    if fps and not misses: return "FALSE_POSITIVE"
    return "MIXED"

def attribute_root_cause(con,recovery_case_id,persist=True):
    existing=con.execute("""SELECT * FROM origin_threshold_root_causes
      WHERE recovery_case_id=? ORDER BY root_cause_id DESC LIMIT 1""",
      (recovery_case_id,)).fetchone()
    if existing:
        x=dict(existing)
        x["evidence"]=json.loads(x.pop("evidence_json"))
        x["reasons"]=json.loads(x.pop("reasons_json"))
        x["policy_version"]=POLICY_VERSION
        return x
    rc=_recovery(con,recovery_case_id)
    rows=_promotion_observations(con,rc["promotion_id"])
    regressions=[r for r in rows if r["counterfactual_class"]=="PROMOTION_REGRESSION"]
    failure=_failure_class(rows)

    failed=float(rc["failed_threshold"])
    boundary_distances=[abs(float(r["max_text_similarity"])-failed) for r in regressions]
    boundary=min(boundary_distances) if boundary_distances else None

    source_counts={}
    platform_counts={}
    source_evidence=[]
    for r in regressions:
        ctx=_source_platform_context(con,r.get("cluster_id"))
        for x in ctx:
            source_counts[x["source_id"]]=source_counts.get(x["source_id"],0)+1
            platform_counts[x["platform"]]=platform_counts.get(x["platform"],0)+1
        source_evidence.append({"cluster_id":r.get("cluster_id"),"sources":ctx})

    total_source_hits=sum(source_counts.values())
    dominant_source=max(source_counts,key=source_counts.get) if source_counts else None
    dominant_platform=max(platform_counts,key=platform_counts.get) if platform_counts else None
    concentration=(source_counts.get(dominant_source,0)/total_source_hits) if total_source_hits and dominant_source else 0.0

    # Auditable deterministic attribution.
    reasons=[]
    if regressions and boundary is not None and boundary<=0.03:
        root="THRESHOLD_BOUNDARY"
        reasons.append(f"promotion regression lies within {boundary:.3f} of promoted threshold")
    elif concentration>=0.75 and len(regressions)>=2:
        root="SOURCE_CONCENTRATION"
        reasons.append(f"{concentration:.3f} of regression source evidence is concentrated on one source")
    elif any(len(x["sources"])>=2 for x in source_evidence) and failure=="FALSE_POSITIVE":
        root="SOURCE_INDEPENDENCE_OR_SYNDICATION_MODEL"
        reasons.append("false-positive regressions involve multi-source cross-post clusters")
    else:
        root="UNRESOLVED"
        reasons.append("available evidence does not isolate one deterministic root cause")

    previous=con.execute("""SELECT COUNT(*) n FROM origin_threshold_root_causes
      WHERE root_cause_type=? AND recovery_case_id<>?""",(root,recovery_case_id)).fetchone()["n"]
    repeated=int(previous)+1

    critical=sum(int(bool(r["critical"])) for r in regressions)
    if critical or repeated>=3:
        risk="RESTRICTED"
    elif repeated>=2 or len(regressions)>=2:
        risk="ELEVATED"
    else:
        risk="BASELINE"

    evidence={
        "promotion_regression_count":len(regressions),
        "critical_regression_count":critical,
        "failure_class":failure,
        "source_counts":source_counts,
        "platform_counts":platform_counts,
        "source_evidence":source_evidence,
        "failed_threshold":failed,
        "boundary_distance":boundary
    }

    result={
        "policy_version":POLICY_VERSION,
        "recovery_case_id":recovery_case_id,
        "promotion_id":rc["promotion_id"],
        "failure_class":failure,
        "root_cause_type":root,
        "risk_band":risk,
        "dominant_source_id":dominant_source,
        "dominant_platform":dominant_platform,
        "source_concentration":round(concentration,4),
        "boundary_distance":boundary,
        "repeated_root_cause_count":repeated,
        "evidence":evidence,
        "reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_root_causes(
          recovery_case_id,promotion_id,failure_class,root_cause_type,risk_band,
          dominant_source_id,dominant_platform,source_concentration,boundary_distance,
          repeated_root_cause_count,evidence_json,reasons_json,attributed_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (recovery_case_id,rc["promotion_id"],failure,root,risk,dominant_source,
           dominant_platform,concentration,boundary,repeated,
           json.dumps(evidence,ensure_ascii=False),
           json.dumps(reasons,ensure_ascii=False),_now()))
        result["root_cause_id"]=cur.lastrowid
        con.commit()
        from .origin_threshold_recurrence_guard import update_recurrence_profile
        recurrence=update_recurrence_profile(con,result["root_cause_id"])
        result["recurrence_profile"]=recurrence["profile"]
        result["long_term_restriction"]=recurrence["restriction"]
    return result

def root_causes(con,recovery_case_id=None):
    if recovery_case_id is None:
        rows=con.execute("""SELECT * FROM origin_threshold_root_causes
                            ORDER BY root_cause_id""").fetchall()
    else:
        rows=con.execute("""SELECT * FROM origin_threshold_root_causes
                            WHERE recovery_case_id=? ORDER BY root_cause_id""",
                         (recovery_case_id,)).fetchall()
    out=[]
    for r in rows:
        x=dict(r)
        x["evidence"]=json.loads(x.pop("evidence_json"))
        x["reasons"]=json.loads(x.pop("reasons_json"))
        out.append(x)
    return out

def build_adaptive_requirement(con,recovery_case_id,persist=True):
    rows=root_causes(con,recovery_case_id)
    if not rows:
        rc=attribute_root_cause(con,recovery_case_id,persist=True)
    else:
        rc=rows[-1]

    risk=rc["risk_band"]
    recurrence=int(rc["repeated_root_cause_count"])
    if risk=="BASELINE":
        safe=5; ds=2; dp=1; remed=1; review=1
    elif risk=="ELEVATED":
        safe=8; ds=3; dp=2; remed=1; review=1
    else:
        safe=12; ds=4; dp=2; remed=1; review=1

    penalty=max(0,recurrence-1)
    safe+=min(penalty*2,6)
    reasons=[
        f"risk band {risk} requires {safe} safe Shadow outcomes",
        f"recovery evidence must cover >= {ds} distinct sources and >= {dp} platforms",
        "documented remediation and Human root-cause confirmation are required"
    ]
    result={
        "policy_version":POLICY_VERSION,
        "recovery_case_id":recovery_case_id,
        "root_cause_id":rc["root_cause_id"],
        "risk_band":risk,
        "required_safe_shadow_outcomes":safe,
        "required_distinct_sources":ds,
        "required_distinct_platforms":dp,
        "require_remediation":True,
        "require_human_root_cause_review":True,
        "recurrence_penalty":penalty,
        "reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_adaptive_requirements(
          recovery_case_id,root_cause_id,risk_band,required_safe_shadow_outcomes,
          required_distinct_sources,required_distinct_platforms,require_remediation,
          require_human_root_cause_review,recurrence_penalty,reasons_json,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
          (recovery_case_id,rc["root_cause_id"],risk,safe,ds,dp,1,1,penalty,
           json.dumps(reasons,ensure_ascii=False),_now()))
        result["requirement_id"]=cur.lastrowid
        # Upgrade legacy fixed requirement so existing recovery state machine respects the adaptive minimum.
        con.execute("""UPDATE origin_threshold_recovery_cases
          SET required_shadow_outcomes=MAX(required_shadow_outcomes,?)
          WHERE recovery_case_id=?""",(safe,recovery_case_id))
        con.commit()
    return result

def requirements(con,recovery_case_id=None):
    sql="""SELECT * FROM origin_threshold_adaptive_requirements"""
    params=()
    if recovery_case_id is not None:
        sql+=" WHERE recovery_case_id=?"; params=(recovery_case_id,)
    sql+=" ORDER BY requirement_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def submit_remediation(con,recovery_case_id,remediation_type,submitted_by,notes,
                       remediation_ref=None):
    if remediation_type not in (
        "THRESHOLD_CHANGE","SOURCE_RULE_CHANGE","INDEPENDENCE_GRAPH_FIX",
        "COLLECTOR_FIX","DATA_QUALITY_FIX","OTHER"):
        raise ValueError("invalid remediation type")
    if not submitted_by or not notes:
        raise ValueError("submitted_by and notes required")
    rcs=root_causes(con,recovery_case_id)
    if not rcs: raise ValueError("root cause attribution required first")
    cur=con.execute("""INSERT INTO origin_threshold_remediations(
      recovery_case_id,root_cause_id,remediation_type,remediation_ref,notes,
      submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?)""",
      (recovery_case_id,rcs[-1]["root_cause_id"],remediation_type,remediation_ref,
       notes,submitted_by,_now(),"SUBMITTED"))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_remediations
                              WHERE remediation_id=?""",(cur.lastrowid,)).fetchone())


def review_remediation(con,remediation_id,decision,reviewer,reason):
    if decision not in ("EFFECTIVE","INEFFECTIVE","HOLD"):
        raise ValueError("invalid remediation review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    row=con.execute("""SELECT * FROM origin_threshold_remediations
                       WHERE remediation_id=?""",(remediation_id,)).fetchone()
    if not row: raise ValueError("remediation not found")
    con.execute("""UPDATE origin_threshold_remediations SET status=?
                   WHERE remediation_id=?""",(decision,remediation_id))
    con.execute("""INSERT INTO origin_threshold_runtime_events(
      recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (row["recovery_case_id"],"REMEDIATION_REVIEWED",reviewer,
       json.dumps({"remediation_id":remediation_id,"decision":decision,
                   "reason":reason},ensure_ascii=False),_now()))
    con.commit()
    result=dict(con.execute("""SELECT * FROM origin_threshold_remediations
                              WHERE remediation_id=?""",(remediation_id,)).fetchone())
    if decision=="EFFECTIVE":
        from .origin_threshold_recurrence_guard import record_effective_remediation
        record_effective_remediation(con,remediation_id)
    return result

def review_root_cause(con,root_cause_id,decision,reviewer,reason):
    if decision not in ("CONFIRM","REJECT","HOLD"):
        raise ValueError("invalid root-cause review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    con.execute("""INSERT INTO origin_threshold_root_cause_reviews(
      root_cause_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(root_cause_id,decision,reviewer,reason,_now()))
    con.commit()
    return {"root_cause_id":root_cause_id,"decision":decision,
            "reviewer":reviewer,"reason":reason}

def _latest_requirement(con,recovery_case_id):
    r=con.execute("""SELECT * FROM origin_threshold_adaptive_requirements
      WHERE recovery_case_id=? ORDER BY requirement_id DESC LIMIT 1""",
      (recovery_case_id,)).fetchone()
    return dict(r) if r else None

def adaptive_requalification_status(con,recovery_case_id):
    req=_latest_requirement(con,recovery_case_id)
    if not req:
        req=build_adaptive_requirement(con,recovery_case_id,persist=True)

    outcomes=[dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recovery_outcomes
           WHERE recovery_case_id=? ORDER BY recovery_outcome_id""",
        (recovery_case_id,)).fetchall()]
    safe=[r for r in outcomes if r["outcome"]=="SAFE"]

    # Distinct-source/platform coverage is reconstructed from event clusters where available.
    source_ids=set(); platforms=set()
    for o in safe:
        cids=con.execute("""SELECT cluster_id FROM cross_post_clusters
                            WHERE event_instance_id=?""",(o["event_instance_id"],)).fetchall()
        for c in cids:
            for sp in _source_platform_context(con,c["cluster_id"]):
                source_ids.add(sp["source_id"]); platforms.add(sp["platform"])

    remediation=con.execute("""SELECT * FROM origin_threshold_remediations
      WHERE recovery_case_id=? AND status='EFFECTIVE'
      ORDER BY remediation_id DESC LIMIT 1""",(recovery_case_id,)).fetchone()
    rcs=root_causes(con,recovery_case_id)
    root_id=rcs[-1]["root_cause_id"]
    review=con.execute("""SELECT * FROM origin_threshold_root_cause_reviews
      WHERE root_cause_id=? ORDER BY root_cause_review_id DESC LIMIT 1""",
      (root_id,)).fetchone()

    checks={
        "safe_outcomes":len(safe)>=int(req["required_safe_shadow_outcomes"]),
        "distinct_sources":len(source_ids)>=int(req["required_distinct_sources"]),
        "distinct_platforms":len(platforms)>=int(req["required_distinct_platforms"]),
        "remediation":bool(remediation),
        "human_root_cause_confirmed":bool(review and review["decision"]=="CONFIRM")
    }
    ready=all(checks.values())
    return {
        "policy_version":POLICY_VERSION,
        "recovery_case_id":recovery_case_id,
        "requirement":req,
        "observed_safe_outcomes":len(safe),
        "observed_distinct_sources":len(source_ids),
        "observed_distinct_platforms":len(platforms),
        "checks":checks,
        "status":"READY_FOR_ADAPTIVE_REQUALIFICATION" if ready else "NOT_READY"
    }
