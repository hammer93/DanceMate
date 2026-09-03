import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _decode_json(v):
    try:
        return json.loads(v) if v else []
    except Exception:
        return []

def scopes(con,active_only=False):
    sql="""SELECT * FROM origin_threshold_restriction_scopes"""
    if active_only:
        sql+=" WHERE status='ACTIVE'"
    sql+=" ORDER BY scope_id"
    return [dict(r) for r in con.execute(sql).fetchall()]

def scope_routes(con):
    out=[]
    for r in con.execute("""SELECT * FROM origin_threshold_scope_route_evaluations
                            ORDER BY scope_route_id""").fetchall():
        x=dict(r)
        for k in ("candidate_source_ids_json","blocked_source_ids_json",
                  "safe_source_ids_json","selected_source_ids_json","reasons_json"):
            x[k[:-5] if k.endswith("_json") else k]=_decode_json(x.pop(k))
        out.append(x)
    return out

def _restriction(con,restriction_id):
    r=con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                     WHERE restriction_id=?""",(restriction_id,)).fetchone()
    if not r: raise ValueError("restriction not found")
    return dict(r)

def _profile(con,profile_id):
    r=con.execute("""SELECT * FROM origin_threshold_recurrence_profiles
                     WHERE recurrence_profile_id=?""",(profile_id,)).fetchone()
    if not r: raise ValueError("recurrence profile not found")
    return dict(r)

def derive_scope_for_restriction(con,restriction_id):
    existing=con.execute("""SELECT * FROM origin_threshold_restriction_scopes
      WHERE restriction_id=? ORDER BY scope_id DESC LIMIT 1""",(restriction_id,)).fetchone()
    if existing:
        return dict(existing)

    restriction=_restriction(con,restriction_id)
    profile=_profile(con,restriction["recurrence_profile_id"])
    root=profile["root_cause_type"]
    source=profile["dominant_source_id"]
    platform=profile["dominant_platform"]

    # Conservative isolation:
    # - algorithmic threshold boundary cannot be safely localized -> GLOBAL_THRESHOLD
    # - source concentration -> isolate that source only
    # - independence/syndication model with identified source -> isolate source
    # - otherwise if platform is known -> platform
    # - unresolved -> global threshold
    if root=="THRESHOLD_BOUNDARY":
        scope_type="GLOBAL_THRESHOLD"; source_id=None; platform_id=None
        reason="algorithmic threshold-boundary recurrence cannot be isolated to one evidence source"
    elif root=="SOURCE_CONCENTRATION" and source:
        scope_type="SOURCE"; source_id=source; platform_id=None
        reason=f"recurrence is concentrated on source {source}"
    elif root=="SOURCE_INDEPENDENCE_OR_SYNDICATION_MODEL" and source:
        scope_type="SOURCE"; source_id=source; platform_id=None
        reason=f"independence/syndication recurrence is tied to source {source}"
    elif platform and platform!="UNKNOWN":
        scope_type="PLATFORM"; source_id=None; platform_id=platform
        reason=f"recurrence is isolated to platform {platform}"
    else:
        scope_type="GLOBAL_THRESHOLD"; source_id=None; platform_id=None
        reason="root cause scope is unresolved; fail closed at global threshold scope"

    cur=con.execute("""INSERT INTO origin_threshold_restriction_scopes(
      restriction_id,scope_type,source_id,platform,rule_key,status,
      production_action,shadow_learning_enabled,reason,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (restriction_id,scope_type,source_id,platform_id,None,"ACTIVE",
       "BASE_ONLY_SHADOW_RESTRICTED" if scope_type!="GLOBAL_THRESHOLD"
       else "GLOBAL_PROMOTION_RESTRICTED",
       1,reason,_now()))
    sid=cur.lastrowid
    con.execute("""INSERT INTO origin_threshold_scope_events(
      scope_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (sid,"SCOPE_DERIVED","scope-isolation",
       json.dumps({"restriction_id":restriction_id,"scope_type":scope_type,
                   "source_id":source_id,"platform":platform_id},
                  ensure_ascii=False),_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                              WHERE scope_id=?""",(sid,)).fetchone())

def derive_all_active_scopes(con):
    created=[]
    rows=con.execute("""SELECT restriction_id FROM origin_threshold_long_term_restrictions
                        WHERE status='ACTIVE' ORDER BY restriction_id""").fetchall()
    for r in rows:
        created.append(derive_scope_for_restriction(con,r["restriction_id"]))
    return created

def _source_platform(con,source_id):
    r=con.execute("""SELECT platform FROM sources WHERE source_id=?""",(source_id,)).fetchone()
    return (r["platform"] if r and r["platform"] else "UNKNOWN")

def match_active_scope(con,source_id,rule_key=None):
    platform=_source_platform(con,source_id)
    matched=[]
    for s in scopes(con,active_only=True):
        st=s["scope_type"]
        if st=="GLOBAL_THRESHOLD":
            continue
        if st=="SOURCE" and s["source_id"]==source_id:
            matched.append(s)
        elif st=="PLATFORM" and s["platform"]==platform:
            matched.append(s)
        elif st=="RULE" and s["rule_key"]==rule_key:
            matched.append(s)
        elif st=="SOURCE_RULE" and s["source_id"]==source_id and s["rule_key"]==rule_key:
            matched.append(s)
    return matched

def source_production_allowed(con,source_id,rule_key=None,event_instance_id=None):
    matched=match_active_scope(con,source_id,rule_key)
    if not matched:
        return {
            "allowed":True,"source_id":source_id,"rule_key":rule_key,
            "matched_scope_ids":[],"production_action":"ALLOW",
            "reintegration_canary_id":None
        }

    # Scoped reintegration canary permits only explicitly assigned Events.
    if event_instance_id is not None:
        from .origin_threshold_scope_reintegration import assignment_policy
        for s in matched:
            p=assignment_policy(con,s["scope_id"],event_instance_id)
            if p["allowed"]:
                return {
                    "allowed":True,"source_id":source_id,"rule_key":rule_key,
                    "matched_scope_ids":[x["scope_id"] for x in matched],
                    "production_action":"REINTEGRATION_CANARY",
                    "reintegration_canary_id":p["canary_id"],
                    "reintegration_assignment_id":p.get("assignment_id")
                }

    return {
        "allowed":False,"source_id":source_id,"rule_key":rule_key,
        "matched_scope_ids":[x["scope_id"] for x in matched],
        "production_action":"BASE_ONLY_SHADOW_RESTRICTED",
        "reintegration_canary_id":None
    }

def global_restrictions_requiring_exception(con):
    derive_all_active_scopes(con)
    rows=[]
    for s in scopes(con,active_only=True):
        if s["scope_type"]!="GLOBAL_THRESHOLD":
            continue
        r=_restriction(con,s["restriction_id"])
        approved=con.execute("""SELECT * FROM origin_threshold_restriction_exceptions
          WHERE restriction_id=? AND decision='APPROVE' AND consumed_at IS NULL
          ORDER BY exception_id DESC LIMIT 1""",(r["restriction_id"],)).fetchone()
        r["scope_id"]=s["scope_id"]
        r["scope_type"]=s["scope_type"]
        r["has_unconsumed_exception"]=bool(approved)
        r["exception_id"]=approved["exception_id"] if approved else None
        rows.append(r)
    return rows

def scoped_restrictions(con):
    derive_all_active_scopes(con)
    return [s for s in scopes(con,active_only=True) if s["scope_type"]!="GLOBAL_THRESHOLD"]

def evaluate_safe_alternative_path(con,*,event_instance_id,rule_key,trigger_source_id,
                                   candidate_source_ids,selected_source_ids=None):
    selected_source_ids=list(selected_source_ids or [])
    candidate_source_ids=list(dict.fromkeys(candidate_source_ids))
    blocked=[]
    safe=[]
    reasons=[]
    for sid in candidate_source_ids:
        p=source_production_allowed(con,sid,rule_key)
        if p["allowed"]:
            safe.append(sid)
        else:
            blocked.append(sid)
            reasons.append(
                f"source {sid} is isolated from Production by scope(s) {p['matched_scope_ids']}")

    selected=[sid for sid in selected_source_ids if sid in safe]
    if selected:
        status="SAFE_ALTERNATIVE_SELECTED"
        recommendation="ALLOW_EXISTING_SAFE_ROUTE"
        preserved=True
    elif len(safe)>=2:
        status="SAFE_ALTERNATIVE_AVAILABLE"
        recommendation="RECOMPUTE_ROUTE_WITH_SAFE_SOURCES"
        preserved=True
    elif len(safe)==1:
        status="DEGRADED_POSSIBLE"
        recommendation="POSSIBLE_ONLY_WITH_SINGLE_SAFE_SOURCE"
        preserved=False
    else:
        status="NO_SAFE_ALTERNATIVE"
        recommendation="UNKNOWN_OR_SHADOW_ONLY"
        preserved=False

    if blocked:
        reasons.append("restricted evidence remains available for Shadow learning but cannot support Production verification")
    if safe:
        reasons.append(f"{len(safe)} non-restricted source(s) remain available")

    cur=con.execute("""INSERT INTO origin_threshold_scope_route_evaluations(
      event_instance_id,rule_key,trigger_source_id,candidate_source_ids_json,
      blocked_source_ids_json,safe_source_ids_json,selected_source_ids_json,
      route_status,production_recommendation,coverage_preserved,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (event_instance_id,rule_key,trigger_source_id,
       json.dumps(candidate_source_ids,ensure_ascii=False),
       json.dumps(blocked,ensure_ascii=False),
       json.dumps(safe,ensure_ascii=False),
       json.dumps(selected,ensure_ascii=False),
       status,recommendation,int(preserved),json.dumps(reasons,ensure_ascii=False),_now()))
    rid=cur.lastrowid
    con.execute("""INSERT INTO origin_threshold_scope_events(
      scope_route_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (rid,"SAFE_ALTERNATIVE_EVALUATED","scope-isolation",
       json.dumps({"status":status,"blocked":blocked,"safe":safe},ensure_ascii=False),_now()))
    con.commit()
    return {
        "policy_version":POLICY_VERSION,
        "scope_route_id":rid,
        "event_instance_id":event_instance_id,
        "rule_key":rule_key,
        "trigger_source_id":trigger_source_id,
        "candidate_source_ids":candidate_source_ids,
        "blocked_source_ids":blocked,
        "safe_source_ids":safe,
        "selected_source_ids":selected,
        "route_status":status,
        "production_recommendation":recommendation,
        "coverage_preserved":preserved,
        "reasons":reasons
    }


def override_scope(con,restriction_id,scope_type,reviewer,reason,
                   source_id=None,platform=None,rule_key=None):
    scope_type=scope_type.upper()
    allowed={"GLOBAL_THRESHOLD","SOURCE","PLATFORM","RULE","SOURCE_RULE"}
    if scope_type not in allowed:
        raise ValueError("invalid scope_type")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    if scope_type in ("SOURCE","SOURCE_RULE") and not source_id:
        raise ValueError("source_id required for SOURCE/SOURCE_RULE scope")
    if scope_type=="PLATFORM" and not platform:
        raise ValueError("platform required for PLATFORM scope")
    if scope_type in ("RULE","SOURCE_RULE") and not rule_key:
        raise ValueError("rule_key required for RULE/SOURCE_RULE scope")
    _restriction(con,restriction_id)

    # Human override supersedes prior ACTIVE scope(s) for the same restriction.
    old=con.execute("""SELECT scope_id FROM origin_threshold_restriction_scopes
                       WHERE restriction_id=? AND status='ACTIVE'""",
                    (restriction_id,)).fetchall()
    for r in old:
        con.execute("""UPDATE origin_threshold_restriction_scopes
                       SET status='SUPERSEDED',released_at=? WHERE scope_id=?""",
                    (_now(),r["scope_id"]))
        con.execute("""INSERT INTO origin_threshold_scope_events(
          scope_id,event_type,actor,detail_json,created_at)
          VALUES(?,?,?,?,?)""",
          (r["scope_id"],"SCOPE_SUPERSEDED",reviewer,
           json.dumps({"reason":reason},ensure_ascii=False),_now()))

    cur=con.execute("""INSERT INTO origin_threshold_restriction_scopes(
      restriction_id,scope_type,source_id,platform,rule_key,status,
      production_action,shadow_learning_enabled,reason,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (restriction_id,scope_type,source_id,platform,rule_key,"ACTIVE",
       "GLOBAL_PROMOTION_RESTRICTED" if scope_type=="GLOBAL_THRESHOLD"
       else "BASE_ONLY_SHADOW_RESTRICTED",
       1,reason,_now()))
    sid=cur.lastrowid
    con.execute("""INSERT INTO origin_threshold_scope_events(
      scope_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (sid,"HUMAN_SCOPE_OVERRIDE",reviewer,
       json.dumps({"restriction_id":restriction_id,"scope_type":scope_type,
                   "source_id":source_id,"platform":platform,"rule_key":rule_key,
                   "reason":reason},ensure_ascii=False),_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                              WHERE scope_id=?""",(sid,)).fetchone())

def release_scope(con,scope_id,released_by,reason):
    if not released_by or not reason:
        raise ValueError("released_by and reason required")
    r=con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                     WHERE scope_id=?""",(scope_id,)).fetchone()
    if not r: raise ValueError("scope not found")
    if r["status"]!="ACTIVE":
        raise ValueError("scope is not active")
    con.execute("""UPDATE origin_threshold_restriction_scopes
                   SET status='RELEASED',released_at=? WHERE scope_id=?""",
                (_now(),scope_id))
    con.execute("""INSERT INTO origin_threshold_scope_events(
      scope_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (scope_id,"SCOPE_RELEASED",released_by,
       json.dumps({"reason":reason},ensure_ascii=False),_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_restriction_scopes
                              WHERE scope_id=?""",(scope_id,)).fetchone())

def scope_status(con):
    derive_all_active_scopes(con)
    return {
        "policy_version":POLICY_VERSION,
        "active_scopes":scopes(con,active_only=True),
        "global_restrictions":global_restrictions_requiring_exception(con),
        "scoped_restrictions":scoped_restrictions(con),
        "route_evaluations":scope_routes(con)
    }
