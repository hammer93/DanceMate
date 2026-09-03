import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MIN_DECISIVE=8
MIN_HELPFUL=7
CANARY_MAX_FALLBACKS=1

def _now():
    return datetime.now(timezone.utc).isoformat()

def _family_profile(con,profile_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_profiles
                     WHERE fallback_family_profile_id=?""",(profile_id,)).fetchone()
    if not r:
        raise ValueError("fallback family profile not found")
    return dict(r)

def _case(con,case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_cases
                     WHERE family_recovery_case_id=?""",(case_id,)).fetchone()
    if not r:
        raise ValueError("family recovery case not found")
    return dict(r)

def _event(con,case_id,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_events(
      family_recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (case_id,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def cases(con,fallback_family_profile_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_cases"""
    params=()
    if fallback_family_profile_id is not None:
        sql+=" WHERE fallback_family_profile_id=?"; params=(fallback_family_profile_id,)
    sql+=" ORDER BY family_recovery_case_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def latest_case(con,profile_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_cases
      WHERE fallback_family_profile_id=? ORDER BY family_recovery_case_id DESC LIMIT 1""",
      (profile_id,)).fetchone()
    return dict(r) if r else None

def ensure_open_case(con,profile_id):
    p=_family_profile(con,profile_id)
    c=latest_case(con,profile_id)
    if c and c["status"] in (
        "OPEN","REMEDIATION_SUBMITTED","CANDIDATE_SET","WARMING",
        "READY_FOR_HUMAN_REARM","REARMED_CANARY","CANARY_ACTIVE"):
        return c
    n=con.execute("""SELECT COUNT(*) n FROM origin_threshold_recommendation_fallback_family_recovery_cases
                     WHERE fallback_family_profile_id=?""",(profile_id,)).fetchone()["n"]+1
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_cases(
      fallback_family_profile_id,root_cause_type,family_signature,recovery_number,
      status,canary_max_fallbacks,opened_at)
      VALUES(?,?,?,?,?,?,?)""",
      (profile_id,p["root_cause_type"],p["family_signature"],n,
       "OPEN",CANARY_MAX_FALLBACKS,_now()))
    con.commit()
    _event(con,cur.lastrowid,"FAMILY_RECOVERY_OPENED","family-recovery-engine",
           {"recovery_number":n,"family_signature":p["family_signature"]})
    from .origin_threshold_recommendation_fallback_family_ranking import recommend_case
    recommend_case(con,cur.lastrowid,persist=True)
    return _case(con,cur.lastrowid)

def add_remediation(con,case_id,remediation_type,remediation_ref,submitted_by,notes=""):
    c=_case(con,case_id)
    if c["status"] not in ("OPEN","REMEDIATION_SUBMITTED","CANDIDATE_SET","WARMING"):
        raise ValueError("family recovery case is not accepting remediation")
    from .origin_threshold_recommendation_fallback_family_ranking import selection_allows
    selection=selection_allows(con,case_id,remediation_type,remediation_ref)
    if not selection["allowed"]:
        raise ValueError(selection["reason"])
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_remediations(
      family_recovery_case_id,remediation_type,remediation_ref,status,
      submitted_by,notes,submitted_at)
      VALUES(?,?,?,?,?,?,?)""",
      (case_id,remediation_type,remediation_ref,"SUBMITTED",
       submitted_by,notes or "",_now()))
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
                   SET status='REMEDIATION_SUBMITTED' WHERE family_recovery_case_id=?""",(case_id,))
    con.commit()
    _event(con,case_id,"FAMILY_REMEDIATION_SUBMITTED",submitted_by,
           {"remediation_type":remediation_type,"remediation_ref":remediation_ref})
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_remediations
                              WHERE family_recovery_remediation_id=?""",(cur.lastrowid,)).fetchone())

def review_remediation(con,remediation_id,decision,reviewer,reason):
    if decision not in ("EFFECTIVE","INEFFECTIVE","HOLD"):
        raise ValueError("invalid remediation review decision")
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_remediations
                     WHERE family_recovery_remediation_id=?""",(remediation_id,)).fetchone()
    if not r:
        raise ValueError("family recovery remediation not found")
    if decision=="EFFECTIVE":
        c=_case(con,r["family_recovery_case_id"])
        from .origin_threshold_recommendation_fallback_family_memory import remediation_allowed
        allowed=remediation_allowed(
            con,c["family_signature"],r["remediation_type"],r["remediation_ref"])
        if not allowed["allowed"]:
            raise ValueError("family remediation is AVOID in effectiveness memory")
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_remediations
      SET status=?,reviewed_by=?,reviewed_at=?,review_reason=?
      WHERE family_recovery_remediation_id=?""",
      (decision,reviewer,_now(),reason,remediation_id))
    con.commit()
    _event(con,r["family_recovery_case_id"],"FAMILY_REMEDIATION_REVIEWED",reviewer,
           {"remediation_id":remediation_id,"decision":decision,"reason":reason})
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_remediations
                              WHERE family_recovery_remediation_id=?""",(remediation_id,)).fetchone())

def set_candidate_version(con,case_id,algorithm_version_id,actor,reason):
    c=_case(con,case_id)
    p=_family_profile(con,c["fallback_family_profile_id"])
    v=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
                     WHERE algorithm_version_id=?""",(algorithm_version_id,)).fetchone()
    if not v:
        raise ValueError("candidate algorithm version not found")
    v=dict(v)
    if v["root_cause_type"]!=c["root_cause_type"]:
        raise ValueError("candidate version root cause mismatch")
    from .origin_threshold_recommendation_fallback_family import family_root_id
    if family_root_id(con,algorithm_version_id)!=p["family_root_algorithm_version_id"]:
        raise ValueError("candidate version is not in the affected family")
    if algorithm_version_id==p["fallback_target_algorithm_version_id"]:
        raise ValueError("fallback target itself cannot be the fresh recovery candidate")
    if v["status"] not in ("DRAFT","SHADOW","CANARY"):
        raise ValueError("fresh family candidate must be DRAFT/SHADOW/CANARY")
    if v["created_at"] < c["opened_at"]:
        raise ValueError("candidate version must be created after family recovery opened")
    seen=con.execute("""SELECT 1 FROM origin_threshold_recommendation_version_fallbacks
      WHERE root_cause_type=? AND failing_algorithm_version_id=? LIMIT 1""",
      (c["root_cause_type"],algorithm_version_id)).fetchone()
    if seen:
        raise ValueError("previously failing version cannot be reused as fresh family candidate")
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
      SET candidate_algorithm_version_id=?,status='CANDIDATE_SET'
      WHERE family_recovery_case_id=?""",(algorithm_version_id,case_id))
    con.commit()
    _event(con,case_id,"FAMILY_CANDIDATE_VERSION_SET",actor,
           {"algorithm_version_id":algorithm_version_id,"reason":reason})
    return _case(con,case_id)

def add_evidence(con,case_id,challenge_id,verdict,human_confirmed,notes=""):
    if verdict not in ("RECOMMENDATION_HELPFUL","RECOMMENDATION_HARMFUL","NEUTRAL"):
        raise ValueError("invalid family recovery evidence verdict")
    c=_case(con,case_id)
    if not c["candidate_algorithm_version_id"]:
        raise ValueError("fresh candidate algorithm version must be set first")
    alg=con.execute("""SELECT algorithm_version_id FROM origin_threshold_recommendation_algorithm_lineage
      WHERE entity_type='CHALLENGE' AND entity_id=? AND relation_type='EVALUATED_BY'
      ORDER BY algorithm_lineage_id DESC LIMIT 1""",(challenge_id,)).fetchone()
    if not alg or alg["algorithm_version_id"]!=c["candidate_algorithm_version_id"]:
        raise ValueError("recovery evidence challenge must belong to fresh candidate version")
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_evidence(
      family_recovery_case_id,challenge_id,candidate_algorithm_version_id,
      verdict,human_confirmed,notes,observed_at)
      VALUES(?,?,?,?,?,?,?)""",
      (case_id,challenge_id,c["candidate_algorithm_version_id"],
       verdict,int(bool(human_confirmed)),notes or "",_now()))
    con.commit()
    return evaluate(con,case_id,persist=True)

def _architecture_review_confirmed(con,c):
    r=con.execute("""SELECT 1 FROM origin_threshold_recommendation_fallback_family_reviews
      WHERE fallback_family_profile_id=? AND decision='ACKNOWLEDGE_ARCHITECTURE_REVIEW'
        AND reviewed_at>=?
      ORDER BY fallback_family_review_id DESC LIMIT 1""",
      (c["fallback_family_profile_id"],c["opened_at"])).fetchone()
    return bool(r)

def evaluate(con,case_id,persist=True):
    c=_case(con,case_id)
    remediation=bool(con.execute("""SELECT 1 FROM origin_threshold_recommendation_fallback_family_recovery_remediations
      WHERE family_recovery_case_id=? AND status='EFFECTIVE' AND reviewed_at>=?
      ORDER BY family_recovery_remediation_id DESC LIMIT 1""",
      (case_id,c["opened_at"])).fetchone())
    architecture=_architecture_review_confirmed(con,c)
    candidate_ready=bool(c["candidate_algorithm_version_id"])
    rows=[dict(r) for r in con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_evidence
      WHERE family_recovery_case_id=? ORDER BY family_recovery_evidence_id""",(case_id,)).fetchall()]
    decisive=[r for r in rows if r["human_confirmed"]]
    helpful=sum(r["verdict"]=="RECOMMENDATION_HELPFUL" for r in decisive)
    harmful=sum(r["verdict"]=="RECOMMENDATION_HARMFUL" for r in decisive)
    neutral=sum(r["verdict"]=="NEUTRAL" for r in decisive)
    distinct=len({r["challenge_id"] for r in decisive})
    reasons=[]
    if not architecture:
        reasons.append("fresh Human Architecture Review acknowledgement required")
    if not remediation:
        reasons.append("fresh EFFECTIVE family-level remediation required")
    if not candidate_ready:
        reasons.append("fresh candidate algorithm version required")
    if len(decisive)<MIN_DECISIVE:
        reasons.append(f"fresh decisive evidence {len(decisive)}/{MIN_DECISIVE}")
    if helpful<MIN_HELPFUL:
        reasons.append(f"fresh helpful evidence {helpful}/{MIN_HELPFUL}")
    if harmful>0:
        reasons.append(f"harmful evidence must be 0; have {harmful}")
    if distinct<MIN_DECISIVE:
        reasons.append(f"distinct fresh challenges {distinct}/{MIN_DECISIVE}")

    if harmful>0:
        status="BLOCKED"
    elif not reasons:
        status="READY_FOR_HUMAN_REARM"
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
          SET status='READY_FOR_HUMAN_REARM',ready_at=? WHERE family_recovery_case_id=?""",
          (_now(),case_id))
        con.commit()
    else:
        status="WARMING"
        if c["status"] not in ("REMEDIATION_SUBMITTED","CANDIDATE_SET"):
            con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
              SET status='WARMING' WHERE family_recovery_case_id=?""",(case_id,))
            con.commit()

    result={
        "policy_version":POLICY_VERSION,
        "family_recovery_case_id":case_id,
        "architecture_review_confirmed":architecture,
        "remediation_effective":remediation,
        "candidate_version_ready":candidate_ready,
        "candidate_algorithm_version_id":c["candidate_algorithm_version_id"],
        "decisive_count":len(decisive),"helpful_count":helpful,
        "harmful_count":harmful,"neutral_count":neutral,
        "distinct_challenge_count":distinct,
        "required_decisive_count":MIN_DECISIVE,
        "required_helpful_count":MIN_HELPFUL,
        "status":status,"reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_evaluations(
          family_recovery_case_id,architecture_review_confirmed,remediation_effective,
          candidate_version_ready,decisive_count,helpful_count,harmful_count,
          neutral_count,distinct_challenge_count,status,reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (case_id,int(architecture),int(remediation),int(candidate_ready),
           len(decisive),helpful,harmful,neutral,distinct,status,
           json.dumps(reasons,ensure_ascii=False),_now()))
        result["family_recovery_evaluation_id"]=cur.lastrowid
        con.commit()
    return result

def human_rearm_review(con,case_id,decision,reviewer,reason):
    if decision not in ("APPROVE_REARM","HOLD","REJECT"):
        raise ValueError("invalid family re-arm review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    ev=evaluate(con,case_id,persist=True)
    c=_case(con,case_id)
    p=_family_profile(con,c["fallback_family_profile_id"])
    if decision=="APPROVE_REARM":
        if ev["status"]!="READY_FOR_HUMAN_REARM":
            raise ValueError("family recovery is not ready for re-arm")
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_profiles
          SET circuit_state='ARMED',architecture_review_required=0,
              reasons_json=?,updated_at=?
          WHERE fallback_family_profile_id=?""",
          (json.dumps(["Human-approved limited family re-arm canary"],ensure_ascii=False),
           _now(),p["fallback_family_profile_id"]))
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
          SET status='REARMED_CANARY',rearmed_at=?,canary_used_fallbacks=0
          WHERE family_recovery_case_id=?""",(_now(),case_id))
        # Re-open normal shadow qualification; this does not promote anything.
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
          SET mode='SHADOW_ONLY',updated_at=? WHERE root_cause_type=?""",
          (_now(),c["root_cause_type"]))
    elif decision=="REJECT":
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
          SET status='REJECTED' WHERE family_recovery_case_id=?""",(case_id,))
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_reviews(
      family_recovery_case_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(case_id,decision,reviewer,reason,_now()))
    con.commit()
    _event(con,case_id,"FAMILY_REARM_REVIEW",reviewer,
           {"decision":decision,"reason":reason})
    return {"case":_case(con,case_id),"evaluation":ev,
            "family_profile":_family_profile(con,c["fallback_family_profile_id"])}

def rearm_permission(con,profile_id,failing_version_id):
    c=latest_case(con,profile_id)
    if not c or c["status"] not in ("REARMED_CANARY","CANARY_ACTIVE"):
        return {"allowed":False,"reason":"family circuit is not in a Human-approved re-arm canary"}
    if c["candidate_algorithm_version_id"]!=failing_version_id:
        return {"allowed":False,"reason":"only the approved fresh family candidate may use re-arm fallback"}
    if c["canary_used_fallbacks"]>=c["canary_max_fallbacks"]:
        return {"allowed":False,"reason":"limited family re-arm fallback allowance is exhausted"}
    return {"allowed":True,"reason":"approved limited family re-arm canary","case":c}

def mark_rearm_fallback_used(con,profile_id,failing_version_id):
    perm=rearm_permission(con,profile_id,failing_version_id)
    if not perm["allowed"]:
        return perm
    c=perm["case"]
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
      SET canary_used_fallbacks=canary_used_fallbacks+1,status='CANARY_ACTIVE'
      WHERE family_recovery_case_id=?""",(c["family_recovery_case_id"],))
    con.commit()
    _event(con,c["family_recovery_case_id"],"FAMILY_REARM_CANARY_FALLBACK_USED",
           "family-recovery-engine",{"failing_algorithm_version_id":failing_version_id})
    return {"allowed":True,"case":_case(con,c["family_recovery_case_id"])}

def finalize_canary(con,profile_id,failing_version_id,verification_status):
    c=latest_case(con,profile_id)
    if not c or c["status"]!="CANARY_ACTIVE" or c["candidate_algorithm_version_id"]!=failing_version_id:
        return None
    if verification_status=="STABLE":
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
          SET status='STABLE',stabilized_at=? WHERE family_recovery_case_id=?""",
          (_now(),c["family_recovery_case_id"]))
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_profiles
          SET circuit_state='CLOSED',architecture_review_required=0,
              reasons_json=?,updated_at=?
          WHERE fallback_family_profile_id=?""",
          (json.dumps(["family re-arm canary stabilized"],ensure_ascii=False),
           _now(),profile_id))
    elif verification_status in ("WATCH","FAILED"):
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recovery_cases
          SET status='FAILED' WHERE family_recovery_case_id=?""",(c["family_recovery_case_id"],))
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_profiles
          SET circuit_state='OPEN',architecture_review_required=1,
              reasons_json=?,updated_at=?
          WHERE fallback_family_profile_id=?""",
          (json.dumps([f"family re-arm canary ended {verification_status}"],ensure_ascii=False),
           _now(),profile_id))
    con.commit()
    if verification_status=="STABLE":
        from .origin_threshold_recommendation_fallback_family_memory import register_stabilized_generation
        register_stabilized_generation(con,c["family_recovery_case_id"])
    _event(con,c["family_recovery_case_id"],"FAMILY_REARM_CANARY_"+verification_status,
           "family-recovery-engine",{})
    return {"case":_case(con,c["family_recovery_case_id"]),
            "family_profile":_family_profile(con,profile_id)}

def remediations(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_remediations"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_recovery_remediation_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def evidence(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_evidence"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_recovery_evidence_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def evaluations(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_evaluations"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_recovery_evaluation_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def reviews(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_reviews"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_recovery_review_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def events(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_events"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_recovery_event_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "cases":cases(con),
        "remediations":remediations(con),
        "evidence":evidence(con),
        "evaluations":evaluations(con),
        "reviews":reviews(con),
        "events":events(con),
    }
