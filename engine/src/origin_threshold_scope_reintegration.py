import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
BASE_REQ={"shadow":7,"human":5,"events":5}
RESTRICTED_REQ={"shadow":8,"human":6,"events":6}
MIN_ELAPSED_HOURS=24.0
MAX_ALLOWED_ALT_QUALITY_REGRESSION=0.10
DEFAULT_CANARY_MAX=3

def _now():
    return datetime.now(timezone.utc).isoformat()

def _scope(con,scope_id):
    r=con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                     WHERE scope_id=?""",(scope_id,)).fetchone()
    if not r: raise ValueError("scope not found")
    return dict(r)

def _restriction(con,restriction_id):
    r=con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                     WHERE restriction_id=?""",(restriction_id,)).fetchone()
    if not r: raise ValueError("restriction not found")
    return dict(r)

def _profile(con,scope):
    restriction=_restriction(con,scope["restriction_id"])
    r=con.execute("""SELECT * FROM origin_threshold_recurrence_profiles
                     WHERE recurrence_profile_id=?""",
                  (restriction["recurrence_profile_id"],)).fetchone()
    return dict(r) if r else {"risk_band":"BASELINE"}

def _effective_remediation(con,scope):
    restriction=_restriction(con,scope["restriction_id"])
    recovery_id=restriction["trigger_recovery_case_id"]
    r=con.execute("""SELECT * FROM origin_threshold_remediations
      WHERE recovery_case_id=? AND status='EFFECTIVE'
      ORDER BY remediation_id DESC LIMIT 1""",(recovery_id,)).fetchone()
    return dict(r) if r else None

def add_evidence(con,scope_id,event_instance_id,outcome,*,human_confirmed=False,
                 alternative_quality_delta=None,false_corroboration=False,
                 missed_syndication=False,notes=None,observed_at=None):
    if outcome not in ("SAFE","UNSAFE","HOLD"):
        raise ValueError("outcome must be SAFE, UNSAFE, or HOLD")
    _scope(con,scope_id)
    cur=con.execute("""INSERT INTO origin_threshold_scope_reintegration_evidence(
      scope_id,event_instance_id,outcome,human_confirmed,alternative_quality_delta,
      false_corroboration,missed_syndication,notes,observed_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (scope_id,event_instance_id,outcome,int(bool(human_confirmed)),
       alternative_quality_delta,int(bool(false_corroboration)),
       int(bool(missed_syndication)),notes,observed_at or _now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_scope_reintegration_evidence
                              WHERE evidence_id=?""",(cur.lastrowid,)).fetchone())

def evidence(con,scope_id=None):
    if scope_id is None:
        rows=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_evidence
                            ORDER BY evidence_id""").fetchall()
    else:
        rows=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_evidence
                            WHERE scope_id=? ORDER BY evidence_id""",
                         (scope_id,)).fetchall()
    return [dict(r) for r in rows]

def evaluate_gate(con,scope_id,persist=True,now=None):
    scope=_scope(con,scope_id)
    if scope["status"]!="ACTIVE":
        return {"policy_version":POLICY_VERSION,"scope_id":scope_id,
                "status":"NOT_APPLICABLE","reasons":["scope is not ACTIVE"]}
    rows=evidence(con,scope_id)
    from .origin_threshold_post_reintegration_guard import requirement_penalty
    penalty=requirement_penalty(con,scope_id)
    latest_reiso=con.execute("""SELECT reactivated_at FROM origin_threshold_scope_reisolations
      WHERE scope_id=? AND status='ACTIVE' ORDER BY reisolation_id DESC LIMIT 1""",
      (scope_id,)).fetchone()
    if latest_reiso:
        rows=[r for r in rows if r["observed_at"]>=latest_reiso["reactivated_at"]]
    profile=_profile(con,scope)
    base=RESTRICTED_REQ if profile.get("risk_band")=="RESTRICTED" else BASE_REQ
    req={
        "shadow":base["shadow"]+penalty["shadow_bonus"],
        "human":base["human"]+penalty["human_bonus"],
        "events":base["events"]+penalty["event_bonus"]
    }
    shadow_count=len(rows)
    decisive=[r for r in rows if r["human_confirmed"] and r["outcome"] in ("SAFE","UNSAFE")]
    safe=[r for r in decisive if r["outcome"]=="SAFE"]
    distinct=len({r["event_instance_id"] for r in decisive})
    fc=sum(bool(r["false_corroboration"]) for r in decisive)
    miss=sum(bool(r["missed_syndication"]) for r in decisive)
    deltas=[float(r["alternative_quality_delta"]) for r in decisive
            if r["alternative_quality_delta"] is not None]
    avg_delta=(sum(deltas)/len(deltas)) if deltas else None

    if rows:
        first=datetime.fromisoformat(rows[0]["observed_at"])
        current=now or datetime.now(timezone.utc)
        elapsed=max(0.0,(current-first).total_seconds()/3600.0)
    else:
        elapsed=0.0

    remediation_row=_effective_remediation(con,scope)
    remediation=bool(remediation_row)
    remediation_route_check=None
    architecture_gate=None
    if latest_reiso:
        from .origin_threshold_architecture_escalation import architecture_gate_for_scope
        architecture_gate=architecture_gate_for_scope(con,scope_id)
        if architecture_gate["required"]:
            remediation=bool(architecture_gate["accepted"])
            remediation_route_check={
                "accepted":remediation,
                "architecture_plan_required":True,
                "reason":architecture_gate["reason"],
                "architecture_plan_id":
                    architecture_gate["plan"]["architecture_plan_id"]
                    if architecture_gate["plan"] else None
            }
        elif remediation_row:
            remediation=remediation_row["submitted_at"]>=latest_reiso["reactivated_at"]
            if remediation:
                from .origin_threshold_post_reintegration_root_cause import validate_remediation_for_scope
                remediation_route_check=validate_remediation_for_scope(con,scope_id,remediation_row)
                remediation=bool(remediation_route_check["accepted"])
    reasons=[]
    if shadow_count<req["shadow"]:
        reasons.append(f"need >= {req['shadow']} scoped Shadow outcomes; have {shadow_count}")
    if len(decisive)<req["human"]:
        reasons.append(f"need >= {req['human']} decisive Human outcomes; have {len(decisive)}")
    if len(safe)<req["human"]:
        reasons.append(f"need >= {req['human']} Human-confirmed SAFE outcomes; have {len(safe)}")
    if distinct<req["events"]:
        reasons.append(f"need >= {req['events']} distinct Event outcomes; have {distinct}")
    if fc:
        reasons.append(f"false corroboration count must be 0; have {fc}")
    if miss:
        reasons.append(f"missed syndication count must be 0; have {miss}")
    if avg_delta is not None and avg_delta < -MAX_ALLOWED_ALT_QUALITY_REGRESSION:
        reasons.append(
            f"reintegration quality delta {avg_delta:.3f} is worse than allowed {-MAX_ALLOWED_ALT_QUALITY_REGRESSION:.3f}")
    if elapsed<MIN_ELAPSED_HOURS:
        reasons.append(f"isolation evidence window must be >= {MIN_ELAPSED_HOURS:g}h; have {elapsed:.1f}h")
    if not remediation:
        if architecture_gate and architecture_gate["required"]:
            reasons.append("Architecture escalation gate is not satisfied: "
                           + architecture_gate["reason"])
        elif remediation_route_check and not remediation_route_check["accepted"]:
            reasons.append("EFFECTIVE remediation does not match post-reintegration root-cause remediation route: "
                           + remediation_route_check["reason"])
        else:
            reasons.append("EFFECTIVE remediation is required before scoped reintegration")

    quality_regression=bool(
        avg_delta is not None and avg_delta < -MAX_ALLOWED_ALT_QUALITY_REGRESSION)
    critical=bool(fc or miss or quality_regression)
    if critical:
        status="BLOCKED"
    elif reasons:
        status="WARMING"
    else:
        status="READY_FOR_HUMAN_CANARY_REVIEW"

    result={
        "policy_version":POLICY_VERSION,"scope_id":scope_id,
        "shadow_count":shadow_count,
        "decisive_human_count":len(decisive),
        "safe_human_count":len(safe),
        "distinct_event_count":distinct,
        "false_corroboration_count":fc,
        "missed_syndication_count":miss,
        "avg_alternative_quality_delta":avg_delta,
        "elapsed_hours":elapsed,
        "remediation_effective":remediation,
        "remediation_route_check":remediation_route_check,
        "architecture_gate":architecture_gate,
        "recurrence_risk_band":profile.get("risk_band","BASELINE"),
        "required_shadow_count":req["shadow"],
        "required_human_count":req["human"],
        "required_distinct_events":req["events"],
        "requirement_penalty_level":penalty["level"],
        "status":status,"reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_scope_reintegration_evaluations(
          scope_id,shadow_count,decisive_human_count,safe_human_count,
          distinct_event_count,false_corroboration_count,missed_syndication_count,
          avg_alternative_quality_delta,elapsed_hours,remediation_effective,
          recurrence_risk_band,required_shadow_count,required_human_count,
          required_distinct_events,status,reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (scope_id,shadow_count,len(decisive),len(safe),distinct,fc,miss,avg_delta,
           elapsed,int(remediation),profile.get("risk_band","BASELINE"),
           req["shadow"],req["human"],req["events"],status,
           json.dumps(reasons,ensure_ascii=False),_now()))
        result["reintegration_evaluation_id"]=cur.lastrowid
        con.commit()
    return result

def evaluations(con,scope_id=None):
    sql="""SELECT * FROM origin_threshold_scope_reintegration_evaluations"""
    params=()
    if scope_id is not None:
        sql+=" WHERE scope_id=?"; params=(scope_id,)
    sql+=" ORDER BY reintegration_evaluation_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def review_for_canary(con,scope_id,evaluation_id,decision,reviewer,reason):
    if decision not in ("APPROVE_CANARY","REJECT","HOLD"):
        raise ValueError("invalid reintegration review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    ev=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_evaluations
                      WHERE reintegration_evaluation_id=? AND scope_id=?""",
                   (evaluation_id,scope_id)).fetchone()
    if not ev: raise ValueError("reintegration evaluation not found")
    if decision=="APPROVE_CANARY" and ev["status"]!="READY_FOR_HUMAN_CANARY_REVIEW":
        raise ValueError("reintegration gate is not ready for canary approval")
    con.execute("""INSERT INTO origin_threshold_scope_reintegration_reviews(
      scope_id,reintegration_evaluation_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?,?)""",(scope_id,evaluation_id,decision,reviewer,reason,_now()))
    con.commit()
    return {"scope_id":scope_id,"reintegration_evaluation_id":evaluation_id,
            "decision":decision,"reviewer":reviewer,"reason":reason}

def start_canary(con,scope_id,evaluation_id,approved_by,max_assignments=DEFAULT_CANARY_MAX):
    if not approved_by:
        raise ValueError("approved_by required")
    if int(max_assignments)<1 or int(max_assignments)>10:
        raise ValueError("max_assignments must be 1..10")
    scope=_scope(con,scope_id)
    if scope["status"]!="ACTIVE":
        raise ValueError("scope must remain ACTIVE during reintegration canary")
    review=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_reviews
      WHERE scope_id=? AND reintegration_evaluation_id=? AND decision='APPROVE_CANARY'
      ORDER BY review_id DESC LIMIT 1""",(scope_id,evaluation_id)).fetchone()
    if not review:
        raise ValueError("Human APPROVE_CANARY review required")
    active=con.execute("""SELECT canary_id FROM origin_threshold_scope_reintegration_canaries
                          WHERE scope_id=? AND status='ACTIVE'""",(scope_id,)).fetchone()
    if active:
        raise ValueError("active reintegration canary already exists for scope")
    cur=con.execute("""INSERT INTO origin_threshold_scope_reintegration_canaries(
      scope_id,reintegration_evaluation_id,status,max_assignments,approved_by,started_at)
      VALUES(?,?,?,?,?,?)""",
      (scope_id,evaluation_id,"ACTIVE",int(max_assignments),approved_by,_now()))
    cid=cur.lastrowid
    con.execute("""INSERT INTO origin_threshold_scope_reintegration_events(
      scope_id,canary_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (scope_id,cid,"CANARY_STARTED",approved_by,
       json.dumps({"max_assignments":int(max_assignments)},ensure_ascii=False),_now()))
    con.commit()
    return canary(con,cid)

def canary(con,canary_id):
    r=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_canaries
                     WHERE canary_id=?""",(canary_id,)).fetchone()
    return dict(r) if r else None

def canaries(con,scope_id=None):
    if scope_id is None:
        rows=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_canaries
                            ORDER BY canary_id""").fetchall()
    else:
        rows=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_canaries
                            WHERE scope_id=? ORDER BY canary_id""",(scope_id,)).fetchall()
    return [dict(r) for r in rows]

def _active_canary(con,scope_id):
    r=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_canaries
                     WHERE scope_id=? AND status='ACTIVE'
                     ORDER BY canary_id DESC LIMIT 1""",(scope_id,)).fetchone()
    return dict(r) if r else None

def assignment_policy(con,scope_id,event_instance_id):
    c=_active_canary(con,scope_id)
    if not c:
        return {"allowed":False,"mode":"SCOPE_RESTRICTED","canary_id":None}
    existing=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_assignments
                            WHERE canary_id=? AND event_instance_id=?""",
                         (c["canary_id"],event_instance_id)).fetchone()
    if existing:
        return {"allowed":True,"mode":"REINTEGRATION_CANARY",
                "canary_id":c["canary_id"],"assignment_id":existing["assignment_id"]}
    if c["assigned_count"]>=c["max_assignments"]:
        return {"allowed":False,"mode":"CANARY_CAP_REACHED","canary_id":c["canary_id"]}
    cur=con.execute("""INSERT INTO origin_threshold_scope_reintegration_assignments(
      canary_id,event_instance_id,assigned_at) VALUES(?,?,?)""",
      (c["canary_id"],event_instance_id,_now()))
    con.execute("""UPDATE origin_threshold_scope_reintegration_canaries
                   SET assigned_count=assigned_count+1 WHERE canary_id=?""",
                (c["canary_id"],))
    con.commit()
    return {"allowed":True,"mode":"REINTEGRATION_CANARY",
            "canary_id":c["canary_id"],"assignment_id":cur.lastrowid}

def record_canary_outcome(con,canary_id,event_instance_id,outcome,*,human_confirmed,
                          false_corroboration=False,missed_syndication=False,reviewer="human"):
    if outcome not in ("SAFE","UNSAFE","HOLD"):
        raise ValueError("outcome must be SAFE, UNSAFE, or HOLD")
    a=con.execute("""SELECT * FROM origin_threshold_scope_reintegration_assignments
                     WHERE canary_id=? AND event_instance_id=?""",
                  (canary_id,event_instance_id)).fetchone()
    if not a: raise ValueError("canary assignment not found")
    if a["outcome"] is not None:
        return canary(con,canary_id)
    c=canary(con,canary_id)
    if not c or c["status"]!="ACTIVE":
        raise ValueError("canary is not active")

    unsafe=outcome=="UNSAFE" or bool(false_corroboration) or bool(missed_syndication)
    con.execute("""UPDATE origin_threshold_scope_reintegration_assignments
      SET outcome=?,human_confirmed=?,false_corroboration=?,missed_syndication=?,outcome_at=?
      WHERE assignment_id=?""",
      (outcome,int(bool(human_confirmed)),int(bool(false_corroboration)),
       int(bool(missed_syndication)),_now(),a["assignment_id"]))

    if unsafe:
        con.execute("""UPDATE origin_threshold_scope_reintegration_canaries
          SET unsafe_count=unsafe_count+1,status='ROLLED_BACK',completed_at=?,
              rollback_reason=? WHERE canary_id=?""",
          (_now(),"unsafe reintegration canary outcome / corroboration regression",canary_id))
        con.execute("""INSERT INTO origin_threshold_scope_reintegration_events(
          scope_id,canary_id,event_type,actor,detail_json,created_at)
          VALUES(?,?,?,?,?,?)""",
          (c["scope_id"],canary_id,"CANARY_FAIL_CLOSED_ROLLBACK",reviewer,
           json.dumps({"event_instance_id":event_instance_id,"outcome":outcome,
                       "false_corroboration":bool(false_corroboration),
                       "missed_syndication":bool(missed_syndication)},ensure_ascii=False),_now()))
    elif outcome=="HOLD" or not human_confirmed:
        con.execute("""UPDATE origin_threshold_scope_reintegration_canaries
                       SET hold_count=hold_count+1 WHERE canary_id=?""",(canary_id,))
    else:
        con.execute("""UPDATE origin_threshold_scope_reintegration_canaries
                       SET safe_count=safe_count+1 WHERE canary_id=?""",(canary_id,))
        fresh=canary(con,canary_id)
        if fresh["assigned_count"]>=fresh["max_assignments"] and \
           fresh["safe_count"]>=fresh["max_assignments"] and \
           fresh["unsafe_count"]==0 and fresh["hold_count"]==0:
            con.execute("""UPDATE origin_threshold_scope_reintegration_canaries
              SET status='READY_FOR_FINAL_RELEASE_REVIEW',completed_at=?
              WHERE canary_id=?""",(_now(),canary_id))
            con.execute("""INSERT INTO origin_threshold_scope_reintegration_events(
              scope_id,canary_id,event_type,actor,detail_json,created_at)
              VALUES(?,?,?,?,?,?)""",
              (c["scope_id"],canary_id,"CANARY_COMPLETED_SAFE",reviewer,
               json.dumps({"safe_count":fresh["safe_count"]},ensure_ascii=False),_now()))
    con.commit()
    return canary(con,canary_id)

def final_release(con,canary_id,released_by,reason):
    if not released_by or not reason:
        raise ValueError("released_by and reason required")
    c=canary(con,canary_id)
    if not c or c["status"]!="READY_FOR_FINAL_RELEASE_REVIEW":
        raise ValueError("canary is not ready for final Human release")
    scope=_scope(con,c["scope_id"])
    con.execute("""UPDATE origin_threshold_scope_reintegration_canaries
                   SET status='FULL_REINTEGRATED',completed_at=? WHERE canary_id=?""",
                (_now(),canary_id))
    con.execute("""UPDATE origin_threshold_restriction_scopes
                   SET status='RELEASED',released_at=? WHERE scope_id=?""",
                (_now(),scope["scope_id"]))
    con.execute("""UPDATE origin_threshold_scope_reisolations
      SET status='CLEARED',cleared_at=?,cleared_by=?,clear_reason=?
      WHERE scope_id=? AND status='ACTIVE'""",
      (_now(),released_by,"successful scoped reintegration after re-isolation",
       scope["scope_id"]))
    con.execute("""INSERT INTO origin_threshold_scope_reintegration_events(
      scope_id,canary_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (scope["scope_id"],canary_id,"HUMAN_FULL_REINTEGRATION_RELEASE",released_by,
       json.dumps({"reason":reason},ensure_ascii=False),_now()))
    con.commit()
    released_canary=canary(con,canary_id)
    released_scope=dict(con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                                      WHERE scope_id=?""",(scope["scope_id"],)).fetchone())
    from .origin_threshold_architecture_memory import register_release
    architecture_runtime=register_release(
        con,scope["scope_id"],canary_id,released_at=released_scope["released_at"])
    return {"canary":released_canary,"scope":released_scope,
            "architecture_runtime_outcome":architecture_runtime}

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "evidence":evidence(con),
        "evaluations":evaluations(con),
        "canaries":canaries(con)
    }
