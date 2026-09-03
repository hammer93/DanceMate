import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"

ROOT_TYPES={
    "THRESHOLD_RECURRENCE",
    "SOURCE_LOCAL_RECURRENCE",
    "PLATFORM_PATTERN_SHIFT",
    "INDEPENDENCE_GRAPH_ERROR",
    "ALTERNATIVE_ROUTE_DEGRADATION",
    "COLLECTOR_EVIDENCE_QUALITY_DRIFT",
    "REMEDIATION_INEFFECTIVE_RECURRENCE",
    "UNRESOLVED",
}

ROUTE_MAP={
    "THRESHOLD_RECURRENCE":"THRESHOLD_CHANGE",
    "SOURCE_LOCAL_RECURRENCE":"SOURCE_RULE_CHANGE",
    "PLATFORM_PATTERN_SHIFT":"SOURCE_RULE_CHANGE",
    "INDEPENDENCE_GRAPH_ERROR":"INDEPENDENCE_GRAPH_FIX",
    "ALTERNATIVE_ROUTE_DEGRADATION":"DATA_QUALITY_FIX",
    "COLLECTOR_EVIDENCE_QUALITY_DRIFT":"COLLECTOR_FIX",
    "REMEDIATION_INEFFECTIVE_RECURRENCE":"OTHER",
    "UNRESOLVED":"OTHER",
}

def _now():
    return datetime.now(timezone.utc).isoformat()

def _reisolation(con,reisolation_id):
    r=con.execute("""SELECT * FROM origin_threshold_scope_reisolations
                     WHERE reisolation_id=?""",(reisolation_id,)).fetchone()
    if not r: raise ValueError("re-isolation not found")
    return dict(r)

def _scope(con,scope_id):
    r=con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                     WHERE scope_id=?""",(scope_id,)).fetchone()
    if not r: raise ValueError("scope not found")
    return dict(r)

def _obs(con,obs_id):
    if obs_id is None: return None
    r=con.execute("""SELECT * FROM origin_threshold_post_reintegration_observations
                     WHERE post_observation_id=?""",(obs_id,)).fetchone()
    return dict(r) if r else None

def _previous_effective_remediation(con,scope):
    restriction=con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                               WHERE restriction_id=?""",(scope["restriction_id"],)).fetchone()
    if not restriction: return None
    return con.execute("""SELECT * FROM origin_threshold_remediations
      WHERE recovery_case_id=? AND status='EFFECTIVE'
      ORDER BY remediation_id DESC LIMIT 1""",
      (restriction["trigger_recovery_case_id"],)).fetchone()

def root_causes(con,reisolation_id=None):
    sql="""SELECT * FROM origin_threshold_post_reintegration_root_causes"""
    params=()
    if reisolation_id is not None:
        sql+=" WHERE reisolation_id=?"; params=(reisolation_id,)
    sql+=" ORDER BY post_root_cause_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["evidence"]=json.loads(x.pop("evidence_json"))
        x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def remediation_routes(con,reisolation_id=None):
    sql="""SELECT * FROM origin_threshold_post_reintegration_remediation_routes"""
    params=()
    if reisolation_id is not None:
        sql+=" WHERE reisolation_id=?"; params=(reisolation_id,)
    sql+=" ORDER BY remediation_route_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["blocked_remediation_types"]=json.loads(
            x.pop("blocked_remediation_types_json")); out.append(x)
    return out

def _same_type_failures(con,root_type):
    return con.execute("""SELECT COUNT(*) n
      FROM origin_threshold_post_reintegration_root_causes rc
      JOIN origin_threshold_scope_reisolations ri ON ri.reisolation_id=rc.reisolation_id
      WHERE rc.root_cause_type=?""",(root_type,)).fetchone()["n"]

def attribute_root_cause(con,reisolation_id,persist=True):
    existing=root_causes(con,reisolation_id)
    if existing: return existing[-1]
    ri=_reisolation(con,reisolation_id)
    scope=_scope(con,ri["scope_id"])
    obs=_obs(con,ri["trigger_post_observation_id"])
    previous_remediation=_previous_effective_remediation(con,scope)

    reasons=[]; secondary=None
    if obs and obs["false_corroboration"]:
        root="INDEPENDENCE_GRAPH_ERROR"
        reasons.append("post-release false corroboration indicates independence/cross-post model failure")
    elif obs and obs["missed_syndication"]:
        root="SOURCE_LOCAL_RECURRENCE" if scope["scope_type"] in ("SOURCE","SOURCE_RULE") else "THRESHOLD_RECURRENCE"
        reasons.append("missed syndication recurred after reintegration")
    elif obs and obs["coverage_quality_delta"] is not None and float(obs["coverage_quality_delta"]) < -0.10 and obs["alternative_correct"]:
        root="ALTERNATIVE_ROUTE_DEGRADATION"
        reasons.append("reintegrated path degraded coverage/quality versus correct alternative route")
    elif scope["scope_type"]=="GLOBAL_THRESHOLD":
        root="THRESHOLD_RECURRENCE"
        reasons.append("global threshold scope failed again after reintegration")
    elif scope["scope_type"]=="PLATFORM":
        root="PLATFORM_PATTERN_SHIFT"
        reasons.append("platform-scoped behavior regressed after reintegration")
    elif obs and not obs["reintegrated_correct"] and not bool(obs["base_correct"]) and not bool(obs["alternative_correct"]):
        root="COLLECTOR_EVIDENCE_QUALITY_DRIFT"
        reasons.append("reintegrated/base/alternative paths all fail, suggesting evidence/collector quality drift")
    elif scope["scope_type"] in ("SOURCE","SOURCE_RULE"):
        root="SOURCE_LOCAL_RECURRENCE"
        reasons.append("failure remains localized to the same source scope")
    else:
        root="UNRESOLVED"
        reasons.append("available runtime evidence does not isolate a deterministic root cause")

    prior_same=_same_type_failures(con,root)
    if previous_remediation is not None and prior_same>=1:
        secondary="REMEDIATION_INEFFECTIVE_RECURRENCE"
        reasons.append("same root-cause family recurred after an EFFECTIVE remediation")

    severity="CRITICAL" if obs and (obs["critical"] or obs["false_corroboration"] or obs["missed_syndication"]) else "HIGH"
    evidence={
        "scope_type":scope["scope_type"],"source_id":scope["source_id"],
        "platform":scope["platform"],"rule_key":scope["rule_key"],
        "trigger_observation":obs,"previous_effective_remediation":
            dict(previous_remediation) if previous_remediation else None,
        "prior_same_root_cause_count":prior_same
    }
    result={
        "reisolation_id":reisolation_id,"scope_id":ri["scope_id"],
        "canary_id":ri["canary_id"],"trigger_post_observation_id":ri["trigger_post_observation_id"],
        "root_cause_type":root,"secondary_root_cause_type":secondary,
        "severity":severity,"evidence":evidence,"reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_post_reintegration_root_causes(
          reisolation_id,scope_id,canary_id,trigger_post_observation_id,
          root_cause_type,secondary_root_cause_type,severity,evidence_json,
          reasons_json,attributed_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (reisolation_id,ri["scope_id"],ri["canary_id"],ri["trigger_post_observation_id"],
           root,secondary,severity,json.dumps(evidence,ensure_ascii=False),
           json.dumps(reasons,ensure_ascii=False),_now()))
        result["post_root_cause_id"]=cur.lastrowid
        con.commit()
        route=build_remediation_route(con,cur.lastrowid,persist=True)
        result["remediation_route"]=route
    return result

def build_remediation_route(con,post_root_cause_id,persist=True):
    rc=con.execute("""SELECT * FROM origin_threshold_post_reintegration_root_causes
                      WHERE post_root_cause_id=?""",(post_root_cause_id,)).fetchone()
    if not rc: raise ValueError("post-reintegration root cause not found")
    existing=con.execute("""SELECT * FROM origin_threshold_post_reintegration_remediation_routes
                            WHERE post_root_cause_id=? ORDER BY remediation_route_id DESC LIMIT 1""",
                         (post_root_cause_id,)).fetchone()
    if existing:
        x=dict(existing); x["blocked_remediation_types"]=json.loads(x.pop("blocked_remediation_types_json")); return x

    required=ROUTE_MAP[rc["root_cause_type"]]
    same_type_attempts=con.execute("""SELECT COUNT(*) n
      FROM origin_threshold_post_reintegration_remediation_attempts
      WHERE remediation_type=? AND accepted_for_gate=1""",(required,)).fetchone()["n"]
    escalation=1
    blocked=[]
    architecture=False
    reason=f"{rc['root_cause_type']} requires {required}"

    # Repeated failure after the same remediation family means do not repeat it blindly.
    if rc["secondary_root_cause_type"]=="REMEDIATION_INEFFECTIVE_RECURRENCE":
        escalation=2
        blocked=[required]
        architecture=True
        required="OTHER"
        reason+="; prior remediation family recurred, architecture-level alternative remediation required"
    elif same_type_attempts>=2:
        escalation=2
        blocked=[required]
        architecture=True
        required="OTHER"
        reason+="; remediation type has repeated accepted attempts, escalate to architecture review"

    result={
        "post_root_cause_id":post_root_cause_id,"reisolation_id":rc["reisolation_id"],
        "required_remediation_type":required,"blocked_remediation_types":blocked,
        "escalation_level":escalation,"architecture_review_required":architecture,
        "reason":reason
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_post_reintegration_remediation_routes(
          post_root_cause_id,reisolation_id,required_remediation_type,
          blocked_remediation_types_json,escalation_level,architecture_review_required,
          reason,created_at) VALUES(?,?,?,?,?,?,?,?)""",
          (post_root_cause_id,rc["reisolation_id"],required,
           json.dumps(blocked,ensure_ascii=False),escalation,int(architecture),
           reason,_now()))
        result["remediation_route_id"]=cur.lastrowid
        con.commit()
    return result

def review_root_cause(con,post_root_cause_id,decision,reviewer,reason):
    if decision not in ("CONFIRM","REJECT","HOLD"):
        raise ValueError("invalid decision")
    if not reviewer or not reason: raise ValueError("reviewer and reason required")
    con.execute("""INSERT INTO origin_threshold_post_reintegration_root_reviews(
      post_root_cause_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(post_root_cause_id,decision,reviewer,reason,_now()))
    con.commit()
    return {"post_root_cause_id":post_root_cause_id,"decision":decision,
            "reviewer":reviewer,"reason":reason}

def latest_route_for_scope(con,scope_id):
    r=con.execute("""SELECT rr.*
      FROM origin_threshold_post_reintegration_remediation_routes rr
      JOIN origin_threshold_post_reintegration_root_causes rc
        ON rc.post_root_cause_id=rr.post_root_cause_id
      JOIN origin_threshold_scope_reisolations ri ON ri.reisolation_id=rc.reisolation_id
      WHERE rc.scope_id=? AND ri.status='ACTIVE'
      ORDER BY rr.remediation_route_id DESC LIMIT 1""",(scope_id,)).fetchone()
    if not r: return None
    x=dict(r); x["blocked_remediation_types"]=json.loads(x.pop("blocked_remediation_types_json"))
    return x

def validate_remediation_for_scope(con,scope_id,remediation_row):
    route=latest_route_for_scope(con,scope_id)
    if not route:
        return {"accepted":True,"route":None,"reason":"no active post-reintegration remediation route"}
    rtype=remediation_row["remediation_type"]
    accepted=(rtype==route["required_remediation_type"] and rtype not in route["blocked_remediation_types"])
    reason=("matches required remediation route" if accepted else
            f"requires {route['required_remediation_type']}; blocked={route['blocked_remediation_types']}")
    prior=con.execute("""SELECT COUNT(*) n FROM origin_threshold_post_reintegration_remediation_attempts
                         WHERE remediation_type=? AND accepted_for_gate=0""",(rtype,)).fetchone()["n"]
    con.execute("""INSERT INTO origin_threshold_post_reintegration_remediation_attempts(
      remediation_route_id,remediation_id,remediation_type,matched_required_type,
      prior_same_type_failure_count,accepted_for_gate,reason,recorded_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (route["remediation_route_id"],remediation_row["remediation_id"],rtype,
       int(rtype==route["required_remediation_type"]),prior,int(accepted),reason,_now()))
    con.commit()
    return {"accepted":accepted,"route":route,"reason":reason}

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "root_causes":root_causes(con),
        "routes":remediation_routes(con)
    }
