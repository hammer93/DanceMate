import json

from .database import (
    active_preventive_quarantine,
    persist_alternative_route_evaluation,
    alternative_route_evaluation_rows,
    persist_alternative_route_event,
    alternative_route_event_rows,
    persist_verification_continuity_snapshot,
    verification_continuity_snapshot_rows
)

POLICY_VERSION="v0.62"
SAFE_ROUTE_STATUSES={"ROUTED_VERIFIED"}
UNSAFE_ACTIONS={"BASE_NOT_ELIGIBLE","QUARANTINE_HOLD"}

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        for f in ("candidate_decision_ids_json","selected_decision_ids_json",
                  "independence_groups_json","reasons_json","detail_json"):
            if f in x and x.get(f):
                try: x[f]=json.loads(x[f])
                except Exception: pass
        out.append(x)
    return out

def _source_meta(con,source_id):
    row=con.execute("""SELECT source_id,platform,source_role,authority_level,status
                       FROM sources WHERE source_id=?""",(source_id,)).fetchone()
    if not row:
        return {
            "source_id":source_id,"platform":"UNKNOWN","source_role":"UNKNOWN",
            "authority_level":"UNKNOWN","status":"UNKNOWN",
            "independence_group":"UNKNOWN"
        }
    x=dict(row)
    platform=(x.get("platform") or "UNKNOWN").upper()
    x["independence_group"]=platform if platform!="UNKNOWN" else "UNKNOWN"
    return x

def _candidate_rows(con,event_instance_id,rule_key,quarantined_source_id):
    rows=con.execute("""SELECT * FROM preventive_verification_decisions
      WHERE event_instance_id=? AND rule_key=? AND source_id<>?
      ORDER BY decision_id""",
      (event_instance_id,rule_key,quarantined_source_id)).fetchall()
    out=[]
    for r in rows:
        x=dict(r)
        if not bool(x["base_eligible"]):
            continue
        if x["production_action"] in UNSAFE_ACTIONS:
            continue
        if active_preventive_quarantine(con,x["source_id"],rule_key):
            continue
        meta=_source_meta(con,x["source_id"])
        if meta["status"] not in {"ACTIVE","UNKNOWN"}:
            continue
        from .origin_threshold_scope_isolation import source_production_allowed
        scoped=source_production_allowed(con,x["source_id"],rule_key,event_instance_id)
        x["scope_policy"]=scoped
        if not scoped["allowed"]:
            # Restricted source remains in upstream discovery/shadow evidence,
            # but cannot become a Production corroborator.
            continue
        x["source_meta"]=meta
        out.append(x)
    return out


def _all_base_candidate_source_ids(con,event_instance_id,rule_key,quarantined_source_id):
    rows=con.execute("""SELECT * FROM preventive_verification_decisions
      WHERE event_instance_id=? AND rule_key=? AND source_id<>?
      ORDER BY decision_id""",
      (event_instance_id,rule_key,quarantined_source_id)).fetchall()
    latest={}
    for r in rows:
        x=dict(r)
        if not bool(x["base_eligible"]) or x["production_action"] in UNSAFE_ACTIONS:
            continue
        if active_preventive_quarantine(con,x["source_id"],rule_key):
            continue
        meta=_source_meta(con,x["source_id"])
        if meta["status"] not in {"ACTIVE","UNKNOWN"}:
            continue
        latest[x["source_id"]]=x
    return list(latest.keys())

def plan_alternative_route(con, *, event_instance_id,quarantined_source_id,rule_key):
    all_candidate_source_ids=_all_base_candidate_source_ids(
        con,event_instance_id,rule_key,quarantined_source_id)
    candidates=_candidate_rows(
        con,event_instance_id,rule_key,quarantined_source_id)

    # Keep newest decision per source so repeated observations cannot create
    # artificial corroboration.
    latest={}
    for c in candidates:
        latest[c["source_id"]]=c
    candidates=list(latest.values())

    human=[c for c in candidates if bool(c["human_confirmed"])]
    source_ids=[c["source_id"] for c in candidates]

    from .source_independence_graph import independent_groups
    graph=independent_groups(
        con,event_instance_id=event_instance_id,source_ids=source_ids)
    independent_ids=graph["independent_source_ids"]
    independent_count=graph["independent_count"]

    selected=[]
    human_route=False
    status="NO_SAFE_ROUTE"
    recommendation="UNKNOWN"
    preserved=False
    reasons=[]

    if human:
        best=sorted(
            human,key=lambda c:(float(c["reliability_score"]),c["decision_id"]),
            reverse=True)[0]
        selected=[best]
        human_route=True
        status="ROUTED_VERIFIED"
        recommendation="ALLOW_VERIFIED_VIA_ALTERNATIVE_ROUTE"
        preserved=True
        reasons.append(
            f"human-confirmed alternative source {best['source_id']} is available")
    elif independent_count>=2:
        pool=[c for c in candidates if c["source_id"] in independent_ids]
        selected=sorted(
            pool,key=lambda c:(float(c["reliability_score"]),c["decision_id"]),
            reverse=True)[:2]
        status="ROUTED_VERIFIED"
        recommendation="ALLOW_VERIFIED_VIA_ALTERNATIVE_ROUTE"
        preserved=True
        reasons.append(
            f"{independent_count} sources are proven independent by Source Independence Graph")
    elif candidates:
        selected=sorted(
            candidates,key=lambda c:(float(c["reliability_score"]),c["decision_id"]),
            reverse=True)[:1]
        status="ROUTED_POSSIBLE"
        recommendation="POSSIBLE_VIA_ALTERNATIVE_ROUTE"
        reasons.append(
            "alternative evidence exists but independence graph cannot prove two independent origins")
    else:
        status="NO_SAFE_ROUTE"
        recommendation="UNKNOWN"
        reasons.append(
            "no non-quarantined Base-eligible alternative source is available")

    if candidates and independent_count<2 and not human:
        pair_statuses=[
            x["independence_status"] for x in graph["pair_evaluations"]
        ]
        if "NOT_INDEPENDENT" in pair_statuses:
            reasons.append("related/syndicated evidence was blocked from double-counting")
        if "UNKNOWN" in pair_statuses or len(candidates)==1:
            reasons.append("unknown independence is never promoted to corroboration")

    from .origin_threshold_scope_isolation import evaluate_safe_alternative_path
    scope_route=evaluate_safe_alternative_path(
        con,event_instance_id=event_instance_id,rule_key=rule_key,
        trigger_source_id=quarantined_source_id,
        candidate_source_ids=all_candidate_source_ids,
        selected_source_ids=[c["source_id"] for c in selected])

    # If the normal route selected only safe evidence, preserve its conclusion.
    # If scope isolation removed all/some evidence, the normal route has already
    # been recomputed from filtered candidates and therefore fails closed.
    blocked_by_scope=scope_route["blocked_source_ids"]
    if blocked_by_scope:
        reasons.append(
            f"scope isolation excluded {len(blocked_by_scope)} restricted source(s) from Production corroboration")
        if scope_route["safe_source_ids"]:
            reasons.append("safe non-restricted evidence path remains active")
        else:
            reasons.append("no safe non-restricted alternative evidence remains")

    return {
        "policy_version":POLICY_VERSION,
        "event_instance_id":event_instance_id,
        "quarantined_source_id":quarantined_source_id,
        "rule_key":rule_key,
        "candidate_decision_ids":[c["decision_id"] for c in candidates],
        "candidate_source_ids":[c["source_id"] for c in candidates],
        "selected_decision_ids":[c["decision_id"] for c in selected],
        "selected_source_ids":[c["source_id"] for c in selected],
        "independence_groups":independent_ids,
        "independence_pair_evaluations":graph["pair_evaluations"],
        "human_confirmed_route":human_route,
        "safe_candidate_count":len(candidates),
        "independent_group_count":independent_count,
        "route_status":status,
        "production_recommendation":recommendation,
        "coverage_preserved":preserved,
        "scope_route_id":scope_route["scope_route_id"],
        "scope_blocked_source_ids":blocked_by_scope,
        "scope_safe_source_ids":scope_route["safe_source_ids"],
        "scope_route_status":scope_route["route_status"],
        "reasons":reasons
    }

def persist_route_plan(con, *, trigger_decision_id,plan):
    eid=persist_alternative_route_evaluation(
        con,trigger_decision_id=trigger_decision_id,
        event_instance_id=plan["event_instance_id"],
        quarantined_source_id=plan["quarantined_source_id"],
        rule_key=plan["rule_key"],
        candidate_decision_ids=plan["candidate_decision_ids"],
        selected_decision_ids=plan["selected_decision_ids"],
        independence_groups=plan["independence_groups"],
        human_confirmed_route=plan["human_confirmed_route"],
        safe_candidate_count=plan["safe_candidate_count"],
        independent_group_count=plan["independent_group_count"],
        route_status=plan["route_status"],
        production_recommendation=plan["production_recommendation"],
        coverage_preserved=plan["coverage_preserved"],
        reasons=plan["reasons"])
    persist_alternative_route_event(
        con,route_evaluation_id=eid,event_type="ROUTE_EVALUATED",
        actor="alternative-source-router",
        detail={
            "route_status":plan["route_status"],
            "selected_source_ids":plan["selected_source_ids"],
            "coverage_preserved":plan["coverage_preserved"]
        })
    x=dict(plan)
    x["route_evaluation_id"]=eid
    return x

def evaluate_and_persist_route(
    con, *, trigger_decision_id,event_instance_id,quarantined_source_id,rule_key):
    plan=plan_alternative_route(
        con,event_instance_id=event_instance_id,
        quarantined_source_id=quarantined_source_id,rule_key=rule_key)
    return persist_route_plan(con,trigger_decision_id=trigger_decision_id,plan=plan)

def continuity_metrics(con,source_id=None,rule_key=None,persist=True):
    where=["1=1"]; params=[]
    if source_id:
        where.append("quarantined_source_id=?"); params.append(source_id)
    if rule_key:
        where.append("rule_key=?"); params.append(rule_key)
    rows=con.execute(
        """SELECT * FROM alternative_route_evaluations WHERE """
        +" AND ".join(where)+" ORDER BY route_evaluation_id",params).fetchall()

    # Latest evaluation per trigger decision only.
    latest={}
    for r in rows:
        key=r["trigger_decision_id"] or f"route:{r['route_evaluation_id']}"
        latest[key]=r
    vals=list(latest.values())
    n=len(vals)
    routed=sum(r["route_status"]=="ROUTED_VERIFIED" for r in vals)
    possible=sum(r["route_status"]=="ROUTED_POSSIBLE" for r in vals)
    no_route=sum(r["route_status"]=="NO_SAFE_ROUTE" for r in vals)
    rate=(routed/n) if n else None
    result={
        "quarantined_decision_count":n,
        "routed_verified_count":routed,
        "degraded_possible_count":possible,
        "no_safe_route_count":no_route,
        "coverage_preservation_rate":rate
    }
    if persist and source_id and rule_key:
        sid=persist_verification_continuity_snapshot(
            con,source_id=source_id,rule_key=rule_key,
            quarantined_decision_count=n,routed_verified_count=routed,
            degraded_possible_count=possible,no_safe_route_count=no_route,
            coverage_preservation_rate=rate)
        result["continuity_snapshot_id"]=sid
    return result

def route_evaluations(con,event_instance_id=None):
    return _decode(alternative_route_evaluation_rows(con,event_instance_id))

def route_events(con,route_evaluation_id=None):
    return _decode(alternative_route_event_rows(con,route_evaluation_id))

def continuity_snapshots(con,source_id=None):
    return [dict(r) for r in verification_continuity_snapshot_rows(con,source_id)]


def evaluate_active_route_continuity(con):
    rows=con.execute("""SELECT source_id,rule_key FROM preventive_quarantines
                       WHERE status='ACTIVE' ORDER BY quarantine_id""").fetchall()
    results=[]
    seen=set()
    for r in rows:
        key=(r["source_id"],r["rule_key"])
        if key in seen:
            continue
        seen.add(key)
        m=continuity_metrics(
            con,source_id=r["source_id"],rule_key=r["rule_key"],persist=True)
        m["source_id"]=r["source_id"]; m["rule_key"]=r["rule_key"]
        results.append(m)
    return {"policy_version":POLICY_VERSION,
            "active_quarantined_source_rule_count":len(results),
            "continuity":results}
