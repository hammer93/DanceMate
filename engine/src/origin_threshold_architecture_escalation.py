import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MIN_SHADOW=12
MIN_HUMAN_SAFE=8
MIN_DISTINCT_EVENTS=8
MIN_AVG_QUALITY_DELTA=-0.05

def _now():
    return datetime.now(timezone.utc).isoformat()

def _route(con,route_id):
    r=con.execute("""SELECT * FROM origin_threshold_post_reintegration_remediation_routes
                     WHERE remediation_route_id=?""",(route_id,)).fetchone()
    if not r: raise ValueError("remediation route not found")
    x=dict(r); x["blocked_remediation_types"]=json.loads(x["blocked_remediation_types_json"])
    return x

def _active_route_for_scope(con,scope_id):
    from .origin_threshold_post_reintegration_root_cause import latest_route_for_scope
    return latest_route_for_scope(con,scope_id)

def _root_for_route(con,route_id):
    r=con.execute("""SELECT rc.* FROM origin_threshold_post_reintegration_root_causes rc
      JOIN origin_threshold_post_reintegration_remediation_routes rr
        ON rr.post_root_cause_id=rc.post_root_cause_id
      WHERE rr.remediation_route_id=?""",(route_id,)).fetchone()
    return dict(r) if r else None

def _recommended_steps(root_type,blocked):
    mapping={
        "THRESHOLD_RECURRENCE":["THRESHOLD_CHANGE","DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"],
        "SOURCE_LOCAL_RECURRENCE":["SOURCE_RULE_CHANGE","INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX"],
        "PLATFORM_PATTERN_SHIFT":["SOURCE_RULE_CHANGE","COLLECTOR_FIX","DATA_QUALITY_FIX"],
        "INDEPENDENCE_GRAPH_ERROR":["INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX","COLLECTOR_FIX"],
        "ALTERNATIVE_ROUTE_DEGRADATION":["DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX","SOURCE_RULE_CHANGE"],
        "COLLECTOR_EVIDENCE_QUALITY_DRIFT":["COLLECTOR_FIX","DATA_QUALITY_FIX","SOURCE_RULE_CHANGE"],
        "REMEDIATION_INEFFECTIVE_RECURRENCE":["COLLECTOR_FIX","INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX"],
        "UNRESOLVED":["COLLECTOR_FIX","INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX"],
    }
    steps=[x for x in mapping.get(root_type,mapping["UNRESOLVED"]) if x not in set(blocked or [])]
    # Cross-layer means at least two independent remediation layers.
    if len(steps)<2:
        for x in ["COLLECTOR_FIX","INDEPENDENCE_GRAPH_FIX","DATA_QUALITY_FIX","THRESHOLD_CHANGE","SOURCE_RULE_CHANGE"]:
            if x not in steps and x not in set(blocked or []):
                steps.append(x)
            if len(steps)>=2: break
    return steps[:3]

def create_plan(con,scope_id,created_by,rationale):
    if not created_by or not rationale:
        raise ValueError("created_by and rationale required")
    route=_active_route_for_scope(con,scope_id)
    if not route:
        raise ValueError("active remediation route not found")
    if not route["architecture_review_required"]:
        raise ValueError("architecture escalation plan is only required for architecture-review routes")
    existing=con.execute("""SELECT * FROM origin_threshold_architecture_remediation_plans
      WHERE scope_id=? AND status NOT IN ('REJECTED','COMPLETED')
      ORDER BY architecture_plan_id DESC LIMIT 1""",(scope_id,)).fetchone()
    if existing: return plan(con,existing["architecture_plan_id"])
    root=_root_for_route(con,route["remediation_route_id"])
    defaults=_recommended_steps(root["root_cause_type"],route["blocked_remediation_types"])
    from .origin_threshold_architecture_ranking import (
        context_for_scope,recommend_contextual_plan
    )
    target_context=context_for_scope(con,scope_id)
    recommendation=recommend_contextual_plan(
        con,root["root_cause_type"],target_context,defaults,
        route["blocked_remediation_types"],persist=True)
    from .origin_threshold_recommendation_challenge import (
        create_challenge,selected_steps_for_scope
    )
    challenge=create_challenge(
        con,scope_id,root["root_cause_type"],recommendation["context_signature"],
        recommendation,defaults)
    human_selected=selected_steps_for_scope(con,scope_id)
    from .origin_threshold_recommendation_policy import resolve_selection
    selection=resolve_selection(
        con,root["root_cause_type"],challenge["challenge_id"],
        recommendation["selected_steps"],defaults,human_selected)
    steps=selection["steps"]
    plan_rationale=(
        rationale + " | recommendation_source=" + recommendation["source"]
        + " | recommendation_confidence=" + recommendation["confidence_band"]
        + " | context_signature=" + recommendation["context_signature"]
        + " | shadow_challenge_id=" + str(challenge["challenge_id"])
        + " | policy_mode=" + selection["policy_mode"]
        + " | plan_selection_source=" + selection["selection_source"]
        + " | selected_side=" + selection["selected_side"])
    cur=con.execute("""INSERT INTO origin_threshold_architecture_remediation_plans(
      scope_id,reisolation_id,remediation_route_id,status,required_step_count,
      created_by,rationale,created_at) VALUES(?,?,?,?,?,?,?,?)""",
      (scope_id,route["reisolation_id"],route["remediation_route_id"],"DRAFT",
       len(steps),created_by,plan_rationale,_now()))
    pid=cur.lastrowid
    for idx,rtype in enumerate(steps,1):
        con.execute("""INSERT INTO origin_threshold_architecture_remediation_steps(
          architecture_plan_id,step_order,remediation_type,required,status)
          VALUES(?,?,?,?,?)""",(pid,idx,rtype,1,"PENDING"))
    con.commit()
    return plan(con,pid)

def plan(con,plan_id):
    r=con.execute("""SELECT * FROM origin_threshold_architecture_remediation_plans
                     WHERE architecture_plan_id=?""",(plan_id,)).fetchone()
    if not r: raise ValueError("architecture plan not found")
    x=dict(r)
    x["steps"]=[dict(s) for s in con.execute(
        """SELECT * FROM origin_threshold_architecture_remediation_steps
           WHERE architecture_plan_id=? ORDER BY step_order""",(plan_id,)).fetchall()]
    return x

def plans(con,scope_id=None):
    if scope_id is None:
        rows=con.execute("""SELECT architecture_plan_id FROM origin_threshold_architecture_remediation_plans
                            ORDER BY architecture_plan_id""").fetchall()
    else:
        rows=con.execute("""SELECT architecture_plan_id FROM origin_threshold_architecture_remediation_plans
                            WHERE scope_id=? ORDER BY architecture_plan_id""",(scope_id,)).fetchall()
    return [plan(con,r["architecture_plan_id"]) for r in rows]

def approve_plan(con,plan_id,decision,reviewer,reason):
    if decision not in ("APPROVE","REJECT","HOLD"):
        raise ValueError("invalid plan review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    p=plan(con,plan_id)
    if p["status"] not in ("DRAFT","HOLD"):
        raise ValueError("plan is not reviewable")
    new_status={"APPROVE":"APPROVED","REJECT":"REJECTED","HOLD":"HOLD"}[decision]
    con.execute("""UPDATE origin_threshold_architecture_remediation_plans
      SET status=?,approved_by=?,approved_at=?,approval_reason=? WHERE architecture_plan_id=?""",
      (new_status,reviewer,_now(),reason,plan_id))
    con.execute("""INSERT INTO origin_threshold_architecture_plan_reviews(
      architecture_plan_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(plan_id,decision,reviewer,reason,_now()))
    con.commit()
    return plan(con,plan_id)

def complete_step(con,plan_id,step_order,remediation_id,completed_by,reason):
    if not completed_by or not reason:
        raise ValueError("completed_by and reason required")
    p=plan(con,plan_id)
    if p["status"] not in ("APPROVED","IN_PROGRESS"):
        raise ValueError("plan must be approved before completing steps")
    step=con.execute("""SELECT * FROM origin_threshold_architecture_remediation_steps
      WHERE architecture_plan_id=? AND step_order=?""",(plan_id,step_order)).fetchone()
    if not step: raise ValueError("architecture step not found")
    rem=con.execute("""SELECT * FROM origin_threshold_remediations WHERE remediation_id=?""",
                    (remediation_id,)).fetchone()
    if not rem: raise ValueError("remediation not found")
    if rem["status"]!="EFFECTIVE":
        raise ValueError("step remediation must be Human-reviewed EFFECTIVE")
    if rem["remediation_type"]!=step["remediation_type"]:
        raise ValueError(f"step requires {step['remediation_type']}")
    route=_route(con,p["remediation_route_id"])
    if rem["remediation_type"] in route["blocked_remediation_types"]:
        raise ValueError("blocked remediation type cannot satisfy architecture plan")
    con.execute("""UPDATE origin_threshold_architecture_remediation_steps
      SET status='EFFECTIVE',remediation_id=?,completed_by=?,completed_at=?,completion_reason=?
      WHERE architecture_step_id=?""",
      (remediation_id,completed_by,_now(),reason,step["architecture_step_id"]))
    con.execute("""UPDATE origin_threshold_architecture_remediation_plans
                   SET status='IN_PROGRESS' WHERE architecture_plan_id=?""",(plan_id,))
    con.commit()
    return plan(con,plan_id)

def add_validation_evidence(con,plan_id,event_instance_id,outcome,*,human_confirmed=False,
                            false_corroboration=False,missed_syndication=False,
                            quality_delta=None,observed_at=None):
    if outcome not in ("SAFE","UNSAFE","HOLD"):
        raise ValueError("invalid outcome")
    plan(con,plan_id)
    cur=con.execute("""INSERT INTO origin_threshold_architecture_validation_evidence(
      architecture_plan_id,event_instance_id,outcome,human_confirmed,false_corroboration,
      missed_syndication,quality_delta,observed_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (plan_id,event_instance_id,outcome,int(bool(human_confirmed)),
       int(bool(false_corroboration)),int(bool(missed_syndication)),
       quality_delta,observed_at or _now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_architecture_validation_evidence
                              WHERE architecture_evidence_id=?""",(cur.lastrowid,)).fetchone())

def evaluate_plan(con,plan_id,persist=True):
    p=plan(con,plan_id)
    steps=p["steps"]
    completed=sum(s["required"] and s["status"]=="EFFECTIVE" for s in steps)
    req=sum(bool(s["required"]) for s in steps)
    rows=[dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_architecture_validation_evidence
           WHERE architecture_plan_id=? ORDER BY architecture_evidence_id""",(plan_id,)).fetchall()]
    human_safe=[r for r in rows if r["human_confirmed"] and r["outcome"]=="SAFE"]
    distinct=len({r["event_instance_id"] for r in human_safe})
    fc=sum(bool(r["false_corroboration"]) for r in rows if r["human_confirmed"])
    miss=sum(bool(r["missed_syndication"]) for r in rows if r["human_confirmed"])
    deltas=[float(r["quality_delta"]) for r in human_safe if r["quality_delta"] is not None]
    avg=(sum(deltas)/len(deltas)) if deltas else None
    reasons=[]
    if p["status"] not in ("APPROVED","IN_PROGRESS","READY_FOR_ARCH_REVIEW","APPROVED_FOR_REINTEGRATION"):
        reasons.append("architecture plan must be Human APPROVED")
    if completed<req: reasons.append(f"required effective steps {completed}/{req}")
    if len(rows)<MIN_SHADOW: reasons.append(f"cross-layer Shadow evidence {len(rows)}/{MIN_SHADOW}")
    if len(human_safe)<MIN_HUMAN_SAFE: reasons.append(f"Human SAFE {len(human_safe)}/{MIN_HUMAN_SAFE}")
    if distinct<MIN_DISTINCT_EVENTS: reasons.append(f"distinct Events {distinct}/{MIN_DISTINCT_EVENTS}")
    if fc: reasons.append(f"false corroboration must be 0; have {fc}")
    if miss: reasons.append(f"missed syndication must be 0; have {miss}")
    if avg is not None and avg<MIN_AVG_QUALITY_DELTA:
        reasons.append(f"avg quality delta {avg:.3f} < {MIN_AVG_QUALITY_DELTA:.3f}")
    critical=bool(fc or miss or (avg is not None and avg<MIN_AVG_QUALITY_DELTA))
    if critical:
        status="BLOCKED"
    elif reasons:
        status="WARMING"
    else:
        status="READY_FOR_ARCH_REVIEW"
        if p["status"]!="APPROVED_FOR_REINTEGRATION":
            con.execute("""UPDATE origin_threshold_architecture_remediation_plans
                           SET status='READY_FOR_ARCH_REVIEW' WHERE architecture_plan_id=?""",(plan_id,))
            con.commit()
    result={
        "policy_version":POLICY_VERSION,"architecture_plan_id":plan_id,
        "completed_required_steps":completed,"required_step_count":req,
        "shadow_count":len(rows),"human_safe_count":len(human_safe),
        "distinct_event_count":distinct,"false_corroboration_count":fc,
        "missed_syndication_count":miss,"avg_quality_delta":avg,
        "status":status,"reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_architecture_plan_evaluations(
          architecture_plan_id,completed_required_steps,required_step_count,
          shadow_count,human_safe_count,distinct_event_count,false_corroboration_count,
          missed_syndication_count,avg_quality_delta,status,reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (plan_id,completed,req,len(rows),len(human_safe),distinct,fc,miss,avg,
           status,json.dumps(reasons,ensure_ascii=False),_now()))
        result["architecture_evaluation_id"]=cur.lastrowid
        con.commit()
    return result

def architecture_review(con,plan_id,decision,reviewer,reason):
    if decision not in ("APPROVE_REINTEGRATION","REJECT","HOLD"):
        raise ValueError("invalid architecture review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    ev=evaluate_plan(con,plan_id,persist=True)
    if decision=="APPROVE_REINTEGRATION" and ev["status"]!="READY_FOR_ARCH_REVIEW":
        raise ValueError("architecture validation is not ready")
    new_status={
        "APPROVE_REINTEGRATION":"APPROVED_FOR_REINTEGRATION",
        "REJECT":"REJECTED",
        "HOLD":"HOLD"
    }[decision]
    con.execute("""UPDATE origin_threshold_architecture_remediation_plans
                   SET status=? WHERE architecture_plan_id=?""",(new_status,plan_id))
    con.execute("""INSERT INTO origin_threshold_architecture_plan_reviews(
      architecture_plan_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(plan_id,decision,reviewer,reason,_now()))
    con.commit()
    return plan(con,plan_id)

def active_plan_for_scope(con,scope_id):
    r=con.execute("""SELECT architecture_plan_id FROM origin_threshold_architecture_remediation_plans
      WHERE scope_id=? AND status IN ('DRAFT','HOLD','APPROVED','IN_PROGRESS',
                                      'READY_FOR_ARCH_REVIEW','APPROVED_FOR_REINTEGRATION')
      ORDER BY architecture_plan_id DESC LIMIT 1""",(scope_id,)).fetchone()
    return plan(con,r["architecture_plan_id"]) if r else None

def architecture_gate_for_scope(con,scope_id):
    route=_active_route_for_scope(con,scope_id)
    if not route or not route["architecture_review_required"]:
        return {"required":False,"accepted":True,"plan":None,
                "reason":"architecture plan not required"}
    p=active_plan_for_scope(con,scope_id)
    if not p:
        return {"required":True,"accepted":False,"plan":None,
                "reason":"architecture remediation plan required"}
    accepted=p["status"]=="APPROVED_FOR_REINTEGRATION"
    return {"required":True,"accepted":accepted,"plan":p,
            "reason":"architecture plan approved for reintegration" if accepted
                     else f"architecture plan status={p['status']}"}

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "plans":plans(con)
    }
