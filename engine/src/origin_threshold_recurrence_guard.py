import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
LONG_TERM_RECURRENCE_THRESHOLD=3
FAILED_EFFECTIVE_REMEDIATION_THRESHOLD=2

def _now():
    return datetime.now(timezone.utc).isoformat()

def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None

def recurrence_signature(root_cause):
    root=root_cause["root_cause_type"]
    source=root_cause.get("dominant_source_id") or "*"
    platform=root_cause.get("dominant_platform") or "*"
    # Threshold-boundary failures are primarily algorithmic. Do not fragment
    # recurrence history by incidental source/platform unless attribution itself
    # says the failure is source-oriented.
    if root=="THRESHOLD_BOUNDARY":
        source=platform="*"
    elif root=="SOURCE_CONCENTRATION":
        platform="*"
    return f"{root}|{source}|{platform}"

def _root_row(con,root_cause_id):
    r=con.execute("""SELECT * FROM origin_threshold_root_causes
                     WHERE root_cause_id=?""",(root_cause_id,)).fetchone()
    if not r: raise ValueError("root cause not found")
    return dict(r)

def _recovery(con,recovery_case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recovery_cases
                     WHERE recovery_case_id=?""",(recovery_case_id,)).fetchone()
    if not r: raise ValueError("recovery case not found")
    return dict(r)

def _profile(con,signature):
    r=con.execute("""SELECT * FROM origin_threshold_recurrence_profiles
                     WHERE signature=?""",(signature,)).fetchone()
    if not r: return None
    x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json"))
    return x

def profiles(con):
    out=[]
    for r in con.execute("""SELECT * FROM origin_threshold_recurrence_profiles
                            ORDER BY recurrence_profile_id""").fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def _previous_matching_root(con,signature,current_root_cause_id):
    rows=con.execute("""SELECT * FROM origin_threshold_root_causes
                       WHERE root_cause_id<>?
                       ORDER BY root_cause_id DESC""",(current_root_cause_id,)).fetchall()
    for r in rows:
        x=dict(r)
        if recurrence_signature(x)==signature:
            return x
    return None

def _effective_remediation_for_recovery(con,recovery_case_id):
    return con.execute("""SELECT * FROM origin_threshold_remediations
      WHERE recovery_case_id=? AND status='EFFECTIVE'
      ORDER BY remediation_id DESC LIMIT 1""",(recovery_case_id,)).fetchone()

def _mark_effective_remediation_recurrence(con,remediation,subsequent_recovery_case_id):
    row=con.execute("""SELECT * FROM origin_threshold_remediation_effectiveness
      WHERE remediation_id=? ORDER BY effectiveness_id DESC LIMIT 1""",
      (remediation["remediation_id"],)).fetchone()
    submitted=_parse_time(remediation["submitted_at"])
    now=datetime.now(timezone.utc)
    days=((now-submitted).total_seconds()/86400.0) if submitted else None
    evidence={
        "subsequent_recovery_case_id":subsequent_recovery_case_id,
        "recurrence_after_human_effective_judgment":True
    }
    if row:
        con.execute("""UPDATE origin_threshold_remediation_effectiveness
          SET status='RECURRENCE_FAILED',subsequent_recovery_case_id=?,
              days_to_recurrence=?,evidence_json=?,evaluated_at=?
          WHERE effectiveness_id=?""",
          (subsequent_recovery_case_id,days,json.dumps(evidence,ensure_ascii=False),
           _now(),row["effectiveness_id"]))
    else:
        rc=_recovery(con,remediation["recovery_case_id"])
        root=con.execute("""SELECT root_cause_type FROM origin_threshold_root_causes
          WHERE recovery_case_id=? ORDER BY root_cause_id DESC LIMIT 1""",
          (remediation["recovery_case_id"],)).fetchone()
        con.execute("""INSERT INTO origin_threshold_remediation_effectiveness(
          remediation_id,recovery_case_id,root_cause_type,remediation_type,status,
          subsequent_recovery_case_id,days_to_recurrence,evidence_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (remediation["remediation_id"],remediation["recovery_case_id"],
           root["root_cause_type"] if root else "UNRESOLVED",
           remediation["remediation_type"],"RECURRENCE_FAILED",
           subsequent_recovery_case_id,days,json.dumps(evidence,ensure_ascii=False),_now()))

def record_effective_remediation(con,remediation_id):
    remediation=con.execute("""SELECT * FROM origin_threshold_remediations
      WHERE remediation_id=?""",(remediation_id,)).fetchone()
    if not remediation: raise ValueError("remediation not found")
    if remediation["status"]!="EFFECTIVE":
        raise ValueError("only EFFECTIVE remediation can enter effectiveness history")
    existing=con.execute("""SELECT * FROM origin_threshold_remediation_effectiveness
      WHERE remediation_id=? ORDER BY effectiveness_id DESC LIMIT 1""",
      (remediation_id,)).fetchone()
    if existing:
        return dict(existing)
    root=con.execute("""SELECT root_cause_type FROM origin_threshold_root_causes
      WHERE recovery_case_id=? ORDER BY root_cause_id DESC LIMIT 1""",
      (remediation["recovery_case_id"],)).fetchone()
    cur=con.execute("""INSERT INTO origin_threshold_remediation_effectiveness(
      remediation_id,recovery_case_id,root_cause_type,remediation_type,status,
      subsequent_recovery_case_id,days_to_recurrence,evidence_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (remediation_id,remediation["recovery_case_id"],
       root["root_cause_type"] if root else "UNRESOLVED",
       remediation["remediation_type"],"EFFECTIVE_PENDING",None,None,
       json.dumps({"human_effective_judgment":True},ensure_ascii=False),_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_remediation_effectiveness
                              WHERE effectiveness_id=?""",(cur.lastrowid,)).fetchone())

def evaluate_remediation_effectiveness(con,min_sustained_days=30):
    now=datetime.now(timezone.utc)
    changed=[]
    rows=con.execute("""SELECT e.*,r.submitted_at
      FROM origin_threshold_remediation_effectiveness e
      JOIN origin_threshold_remediations r ON r.remediation_id=e.remediation_id
      WHERE e.status='EFFECTIVE_PENDING'""").fetchall()
    for r in rows:
        submitted=_parse_time(r["submitted_at"])
        if not submitted: continue
        days=(now-submitted).total_seconds()/86400.0
        if days>=float(min_sustained_days):
            evidence=json.loads(r["evidence_json"])
            evidence.update({"sustained_days":days,"minimum_days":float(min_sustained_days)})
            con.execute("""UPDATE origin_threshold_remediation_effectiveness
              SET status='SUSTAINED_EFFECTIVE',days_to_recurrence=NULL,
                  evidence_json=?,evaluated_at=? WHERE effectiveness_id=?""",
              (json.dumps(evidence,ensure_ascii=False),_now(),r["effectiveness_id"]))
            changed.append(r["effectiveness_id"])
    con.commit()
    return {"policy_version":POLICY_VERSION,"min_sustained_days":float(min_sustained_days),
            "sustained_marked_count":len(changed),"effectiveness_ids":changed}

def remediation_effectiveness_history(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_remediation_effectiveness
           ORDER BY effectiveness_id""").fetchall()]

def remediation_type_stats(con):
    rows=con.execute("""SELECT remediation_type,
      COUNT(*) total,
      SUM(CASE WHEN status='SUSTAINED_EFFECTIVE' THEN 1 ELSE 0 END) sustained,
      SUM(CASE WHEN status='RECURRENCE_FAILED' THEN 1 ELSE 0 END) recurrence_failed,
      SUM(CASE WHEN status='EFFECTIVE_PENDING' THEN 1 ELSE 0 END) pending
      FROM origin_threshold_remediation_effectiveness
      GROUP BY remediation_type ORDER BY remediation_type""").fetchall()
    out=[]
    for r in rows:
        decisive=int(r["sustained"] or 0)+int(r["recurrence_failed"] or 0)
        out.append({
            "remediation_type":r["remediation_type"],
            "total":int(r["total"]),
            "sustained_effective":int(r["sustained"] or 0),
            "recurrence_failed":int(r["recurrence_failed"] or 0),
            "pending":int(r["pending"] or 0),
            "sustained_success_rate":
                (int(r["sustained"] or 0)/decisive) if decisive else None
        })
    return out

def _active_restriction(con,signature):
    r=con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
      WHERE signature=? AND status='ACTIVE'
      ORDER BY restriction_id DESC LIMIT 1""",(signature,)).fetchone()
    return dict(r) if r else None

def restrictions(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_long_term_restrictions
           ORDER BY restriction_id""").fetchall()]

def _ensure_restriction(con,profile,trigger_recovery_case_id,reason):
    existing=_active_restriction(con,profile["signature"])
    if existing:
        from .origin_threshold_scope_isolation import derive_scope_for_restriction
        derive_scope_for_restriction(con,existing["restriction_id"])
        return existing
    cur=con.execute("""INSERT INTO origin_threshold_long_term_restrictions(
      recurrence_profile_id,signature,status,trigger_recovery_case_id,trigger_reason,
      recurrence_count,failed_effective_remediation_count,requires_human_exception,
      started_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (profile["recurrence_profile_id"],profile["signature"],"ACTIVE",
       trigger_recovery_case_id,reason,profile["recurrence_count"],
       profile["failed_effective_remediation_count"],1,_now()))
    restriction=dict(con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                              WHERE restriction_id=?""",(cur.lastrowid,)).fetchone())
    from .origin_threshold_scope_isolation import derive_scope_for_restriction
    derive_scope_for_restriction(con,restriction["restriction_id"])
    return restriction

def update_recurrence_profile(con,root_cause_id):
    root=_root_row(con,root_cause_id)
    signature=recurrence_signature(root)
    previous=_previous_matching_root(con,signature,root_cause_id)

    post_requal=0
    previous_remediation=None
    if previous:
        prev_rc=_recovery(con,previous["recovery_case_id"])
        if prev_rc["status"]=="REQUALIFIED":
            post_requal=1
            previous_remediation=_effective_remediation_for_recovery(
                con,previous["recovery_case_id"])
            if previous_remediation:
                _mark_effective_remediation_recurrence(
                    con,previous_remediation,root["recovery_case_id"])

    existing=_profile(con,signature)
    recurrence_count=(existing["recurrence_count"] if existing else 0)+1
    post_requal_count=(existing["post_requalification_recurrence_count"] if existing else 0)+post_requal

    failed_effective=con.execute("""SELECT COUNT(*) n
      FROM origin_threshold_remediation_effectiveness e
      JOIN origin_threshold_root_causes rc ON rc.recovery_case_id=e.recovery_case_id
      WHERE e.status='RECURRENCE_FAILED'""").fetchone()["n"]
    # Count only remediations whose recovery root maps to this signature.
    failed_effective=0
    eff_rows=con.execute("""SELECT e.*,rc.* FROM origin_threshold_remediation_effectiveness e
      JOIN origin_threshold_root_causes rc ON rc.recovery_case_id=e.recovery_case_id
      WHERE e.status='RECURRENCE_FAILED'""").fetchall()
    for er in eff_rows:
        if recurrence_signature(dict(er))==signature:
            failed_effective+=1

    if (recurrence_count>=LONG_TERM_RECURRENCE_THRESHOLD
        or failed_effective>=FAILED_EFFECTIVE_REMEDIATION_THRESHOLD
        or post_requal_count>=2):
        risk="RESTRICTED"; restricted=1
    elif recurrence_count>=2 or failed_effective>=1 or post_requal_count>=1:
        risk="ELEVATED"; restricted=0
    else:
        risk="BASELINE"; restricted=0

    reasons=[
        f"recurrence count={recurrence_count}",
        f"post-requalification recurrence count={post_requal_count}",
        f"failed EFFECTIVE remediation count={failed_effective}"
    ]
    if restricted:
        reasons.append("long-term restriction threshold reached")

    if existing:
        con.execute("""UPDATE origin_threshold_recurrence_profiles
          SET recurrence_count=?,post_requalification_recurrence_count=?,
              failed_effective_remediation_count=?,risk_band=?,
              long_term_restricted=?,reasons_json=?,updated_at=?
          WHERE recurrence_profile_id=?""",
          (recurrence_count,post_requal_count,failed_effective,risk,restricted,
           json.dumps(reasons,ensure_ascii=False),_now(),
           existing["recurrence_profile_id"]))
        pid=existing["recurrence_profile_id"]
    else:
        cur=con.execute("""INSERT INTO origin_threshold_recurrence_profiles(
          signature,root_cause_type,dominant_source_id,dominant_platform,
          recurrence_count,post_requalification_recurrence_count,
          failed_effective_remediation_count,risk_band,long_term_restricted,
          reasons_json,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
          (signature,root["root_cause_type"],root.get("dominant_source_id"),
           root.get("dominant_platform"),recurrence_count,post_requal_count,
           failed_effective,risk,restricted,json.dumps(reasons,ensure_ascii=False),_now()))
        pid=cur.lastrowid

    event_type="FIRST_OCCURRENCE" if recurrence_count==1 else "RECURRENCE"
    con.execute("""INSERT INTO origin_threshold_recurrence_events(
      recurrence_profile_id,recovery_case_id,root_cause_id,event_type,
      previous_recovery_case_id,previous_remediation_id,detail_json,created_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (pid,root["recovery_case_id"],root_cause_id,event_type,
       previous["recovery_case_id"] if previous else None,
       previous_remediation["remediation_id"] if previous_remediation else None,
       json.dumps({"risk_band":risk,"signature":signature,
                   "post_requalification_recurrence":bool(post_requal)},
                  ensure_ascii=False),_now()))

    con.commit()
    profile=_profile(con,signature)
    restriction=None
    if restricted:
        restriction=_ensure_restriction(
            con,profile,root["recovery_case_id"],
            "repeated root cause / failed effective remediation requires Human exception before another promotion attempt")
        con.commit()
    return {"policy_version":POLICY_VERSION,"profile":profile,
            "restriction":restriction}

def recurrence_events(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recurrence_events
           ORDER BY recurrence_event_id""").fetchall()]

def grant_restriction_exception(con,restriction_id,decision,approved_by,reason):
    if decision not in ("APPROVE","DENY","HOLD"):
        raise ValueError("invalid restriction exception decision")
    if not approved_by or not reason:
        raise ValueError("approved_by and reason required")
    r=con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                     WHERE restriction_id=?""",(restriction_id,)).fetchone()
    if not r: raise ValueError("restriction not found")
    if r["status"]!="ACTIVE":
        raise ValueError("restriction is not active")
    cur=con.execute("""INSERT INTO origin_threshold_restriction_exceptions(
      restriction_id,decision,approved_by,reason,created_at)
      VALUES(?,?,?,?,?)""",(restriction_id,decision,approved_by,reason,_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_restriction_exceptions
                              WHERE exception_id=?""",(cur.lastrowid,)).fetchone())

def restriction_exceptions(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_restriction_exceptions
           ORDER BY exception_id""").fetchall()]

def active_restrictions_requiring_exception(con):
    out=[]
    for r in con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                            WHERE status='ACTIVE'
                            ORDER BY restriction_id""").fetchall():
        approved=con.execute("""SELECT * FROM origin_threshold_restriction_exceptions
          WHERE restriction_id=? AND decision='APPROVE' AND consumed_at IS NULL
          ORDER BY exception_id DESC LIMIT 1""",(r["restriction_id"],)).fetchone()
        x=dict(r); x["has_unconsumed_exception"]=bool(approved)
        x["exception_id"]=approved["exception_id"] if approved else None
        out.append(x)
    return out

def consume_exception_for_candidate(con):
    # v0.54 isolates Source/Platform-scoped recurrences instead of globally
    # stopping safe policy paths. Only GLOBAL_THRESHOLD restrictions require
    # a one-time Human exception before creating a new threshold Candidate.
    from .origin_threshold_scope_isolation import global_restrictions_requiring_exception
    blocked=[]
    consumable=[]
    for r in global_restrictions_requiring_exception(con):
        if not r["has_unconsumed_exception"]:
            blocked.append(r)
        else:
            consumable.append(r)
    if blocked:
        ids=",".join(str(x["restriction_id"]) for x in blocked)
        raise ValueError(
            f"active global threshold restriction(s) {ids} require explicit Human exception before a new candidate")
    for r in consumable:
        con.execute("""UPDATE origin_threshold_restriction_exceptions
                       SET consumed_at=? WHERE exception_id=?""",
                    (_now(),r["exception_id"]))
    if consumable: con.commit()
    return [r["exception_id"] for r in consumable]

def release_restriction(con,restriction_id,released_by,reason):
    if not released_by or not reason:
        raise ValueError("released_by and reason required")
    r=con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                     WHERE restriction_id=?""",(restriction_id,)).fetchone()
    if not r: raise ValueError("restriction not found")
    if r["status"]!="ACTIVE":
        raise ValueError("restriction is not active")
    con.execute("""UPDATE origin_threshold_long_term_restrictions
      SET status='RELEASED',released_at=?,released_by=?,release_reason=?
      WHERE restriction_id=?""",(_now(),released_by,reason,restriction_id))
    con.execute("""UPDATE origin_threshold_recurrence_profiles
      SET long_term_restricted=0,updated_at=?
      WHERE recurrence_profile_id=?""",(_now(),r["recurrence_profile_id"]))
    con.execute("""UPDATE origin_threshold_restriction_scopes
      SET status='RELEASED',released_at=?
      WHERE restriction_id=? AND status='ACTIVE'""",(_now(),restriction_id))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_long_term_restrictions
                              WHERE restriction_id=?""",(restriction_id,)).fetchone())

def recurrence_status(con):
    return {
        "policy_version":POLICY_VERSION,
        "profiles":profiles(con),
        "restrictions":active_restrictions_requiring_exception(con),
        "remediation_type_stats":remediation_type_stats(con),
        "effectiveness_history":remediation_effectiveness_history(con)
    }
