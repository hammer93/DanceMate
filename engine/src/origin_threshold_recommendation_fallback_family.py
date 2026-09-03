import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MAX_FAMILY_AUTOMATIC_FALLBACKS=2

def _now():
    return datetime.now(timezone.utc).isoformat()

def _version(con,version_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
                     WHERE algorithm_version_id=?""",(version_id,)).fetchone()
    return dict(r) if r else None

def family_root_id(con,version_id):
    seen=set()
    cur=_version(con,version_id)
    if not cur:
        return None
    while cur and cur.get("parent_algorithm_version_id") and cur["algorithm_version_id"] not in seen:
        seen.add(cur["algorithm_version_id"])
        parent=_version(con,cur["parent_algorithm_version_id"])
        if not parent:
            break
        cur=parent
    return cur["algorithm_version_id"] if cur else version_id

def family_signature(con,failing_id,fallback_target_id):
    root=family_root_id(con,failing_id) or failing_id
    return f"{int(root)}=>{int(fallback_target_id)}"

def profiles(con):
    out=[]
    for r in con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_profiles
                            ORDER BY fallback_family_profile_id""").fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def profile(con,failing_id,fallback_target_id):
    sig=family_signature(con,failing_id,fallback_target_id)
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_profiles
                     WHERE family_signature=?""",(sig,)).fetchone()
    if not r: return None
    x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); return x

def _event(con,profile_id,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_events(
      fallback_family_profile_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (profile_id,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def _recompute(con,root_cause_type,failing_id,fallback_target_id):
    sig=family_signature(con,failing_id,fallback_target_id)
    root=family_root_id(con,failing_id) or failing_id
    existing_row=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_profiles
      WHERE family_signature=?""",(sig,)).fetchone()
    existing=dict(existing_row) if existing_row else None

    # A successfully stabilized re-arm starts a new circuit generation for thresholding,
    # while lifetime counters remain preserved in the profile.
    boundary=None
    active_rearm=None
    if existing:
        c=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_cases
          WHERE fallback_family_profile_id=?
          ORDER BY family_recovery_case_id DESC LIMIT 1""",
          (existing["fallback_family_profile_id"],)).fetchone()
        if c:
            c=dict(c)
            if c["status"]=="STABLE" and c["stabilized_at"]:
                boundary=c["stabilized_at"]
            if c["status"] in ("REARMED_CANARY","CANARY_ACTIVE"):
                active_rearm=c

    fallback_rows=con.execute("""SELECT * FROM origin_threshold_recommendation_version_fallbacks
      WHERE root_cause_type=? AND fallback_algorithm_version_id=? AND status='EXECUTED'
      ORDER BY version_fallback_id""",(root_cause_type,fallback_target_id)).fetchall()
    family_fallbacks=[]
    scoped_fallbacks=[]
    for r in fallback_rows:
        r=dict(r)
        if family_root_id(con,r["failing_algorithm_version_id"])==root:
            family_fallbacks.append(r)
            if boundary is None or r["executed_at"]>boundary:
                scoped_fallbacks.append(r)
    executed=len(family_fallbacks)
    distinct=len({r["failing_algorithm_version_id"] for r in family_fallbacks})
    scoped_executed=len(scoped_fallbacks)
    scoped_distinct=len({r["failing_algorithm_version_id"] for r in scoped_fallbacks})

    gen_rows=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_verification_generations
      WHERE root_cause_type=? AND fallback_algorithm_version_id=?""",
      (root_cause_type,fallback_target_id)).fetchall()
    stable=watch=failed=0
    scoped_failed=0
    for g in gen_rows:
        g=dict(g)
        if family_root_id(con,g["failing_algorithm_version_id"])!=root:
            continue
        stable += g["status"]=="STABLE"
        watch += g["status"]=="WATCH"
        failed += g["status"]=="FAILED"
        stamp=g["completed_at"] or g["opened_at"]
        if g["status"]=="FAILED" and (boundary is None or stamp>boundary):
            scoped_failed += 1

    reasons=[]
    if scoped_failed>0:
        reasons.append(f"family fallback verification failed {scoped_failed} time(s) in current circuit generation")
    if scoped_executed>=MAX_FAMILY_AUTOMATIC_FALLBACKS:
        reasons.append(
            f"family automatic fallback count {scoped_executed} reached limit {MAX_FAMILY_AUTOMATIC_FALLBACKS}")
    if scoped_distinct>=MAX_FAMILY_AUTOMATIC_FALLBACKS:
        reasons.append(
            f"distinct failing versions {scoped_distinct} reached family threshold {MAX_FAMILY_AUTOMATIC_FALLBACKS}")

    if active_rearm:
        state="ARMED"
        architecture=0
        reasons=["Human-approved limited family re-arm canary"]
    else:
        state="OPEN" if reasons else "CLOSED"
        architecture=int(state=="OPEN")

    vals=(root_cause_type,root,fallback_target_id,sig,executed,distinct,stable,watch,failed,
          state,architecture,json.dumps(reasons,ensure_ascii=False),_now())
    if existing:
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_profiles
          SET root_cause_type=?,family_root_algorithm_version_id=?,
              fallback_target_algorithm_version_id=?,family_signature=?,
              executed_fallback_count=?,distinct_failing_version_count=?,
              stable_verification_count=?,watch_verification_count=?,
              failed_verification_count=?,circuit_state=?,architecture_review_required=?,
              reasons_json=?,updated_at=?
          WHERE fallback_family_profile_id=?""",vals+(existing["fallback_family_profile_id"],))
        pid=existing["fallback_family_profile_id"]
    else:
        cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_profiles(
          root_cause_type,family_root_algorithm_version_id,fallback_target_algorithm_version_id,
          family_signature,executed_fallback_count,distinct_failing_version_count,
          stable_verification_count,watch_verification_count,failed_verification_count,
          circuit_state,architecture_review_required,reasons_json,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",vals)
        pid=cur.lastrowid
    con.commit()

    if state=="OPEN":
        from .origin_threshold_recommendation_fallback_family_memory import mark_recurrence
        mark_recurrence(con,pid,_now())
        from .origin_threshold_recommendation_fallback_family_recovery import ensure_open_case
        ensure_open_case(con,pid)
    return profile(con,failing_id,fallback_target_id)

def record_fallback(con,root_cause_type,failing_id,fallback_target_id):
    p=_recompute(con,root_cause_type,failing_id,fallback_target_id)
    if p["circuit_state"]=="ARMED":
        from .origin_threshold_recommendation_fallback_family_recovery import mark_rearm_fallback_used
        mark_rearm_fallback_used(con,p["fallback_family_profile_id"],failing_id)
        p=_recompute(con,root_cause_type,failing_id,fallback_target_id)
    _event(con,p["fallback_family_profile_id"],"FAMILY_FALLBACK_RECORDED",
           "fallback-family-engine",
           {"failing_algorithm_version_id":failing_id,
            "fallback_target_algorithm_version_id":fallback_target_id,
            "executed_fallback_count":p["executed_fallback_count"],
            "circuit_state":p["circuit_state"]})
    return p

def record_verification(con,root_cause_type,failing_id,fallback_target_id,status):
    p=_recompute(con,root_cause_type,failing_id,fallback_target_id)
    if p["circuit_state"]=="ARMED":
        from .origin_threshold_recommendation_fallback_family_recovery import finalize_canary
        finalized=finalize_canary(
            con,p["fallback_family_profile_id"],failing_id,status)
        if finalized:
            p=profile(con,failing_id,fallback_target_id)
    _event(con,p["fallback_family_profile_id"],"FAMILY_VERIFICATION_"+status,
           "fallback-family-engine",
           {"status":status,"circuit_state":p["circuit_state"]})
    return p

def automatic_fallback_allowed(con,root_cause_type,failing_id,fallback_target_id):
    p=_recompute(con,root_cause_type,failing_id,fallback_target_id)
    if p["circuit_state"]=="OPEN":
        return {
            "allowed":False,
            "reason":"version family circuit breaker is OPEN",
            "profile":p
        }
    if p["circuit_state"]=="ARMED":
        from .origin_threshold_recommendation_fallback_family_recovery import rearm_permission
        perm=rearm_permission(con,p["fallback_family_profile_id"],failing_id)
        return {
            "allowed":bool(perm["allowed"]),
            "reason":perm["reason"],
            "profile":p,
            "rearm_permission":perm
        }
    return {
        "allowed":True,
        "reason":"version family circuit breaker is CLOSED",
        "profile":p
    }

def reviews(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recommendation_fallback_family_reviews
           ORDER BY fallback_family_review_id""").fetchall()]

def review(con,fallback_family_profile_id,decision,reviewer,reason):
    if decision not in ("ACKNOWLEDGE_ARCHITECTURE_REVIEW","HOLD","REJECT"):
        raise ValueError("invalid family review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    p=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_profiles
      WHERE fallback_family_profile_id=?""",(fallback_family_profile_id,)).fetchone()
    if not p:
        raise ValueError("fallback family profile not found")
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_reviews(
      fallback_family_profile_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(fallback_family_profile_id,decision,reviewer,reason,_now()))
    con.commit()
    _event(con,fallback_family_profile_id,"FAMILY_HUMAN_REVIEW",reviewer,
           {"decision":decision,"reason":reason})
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_reviews
      ORDER BY fallback_family_review_id DESC LIMIT 1""").fetchone())

def events(con):
    out=[]
    for r in con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_events
                            ORDER BY fallback_family_event_id""").fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "profiles":profiles(con),
        "reviews":reviews(con),
        "events":events(con),
    }
