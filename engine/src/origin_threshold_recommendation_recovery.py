import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _requirements(rollback_number):
    if rollback_number<=1:
        return {"decisive":5,"helpful":4,"long_term":False,"architecture":False}
    if rollback_number==2:
        return {"decisive":8,"helpful":7,"long_term":False,"architecture":False}
    return {"decisive":12,"helpful":11,"long_term":True,"architecture":True}

def _case(con,case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_recovery_cases
                     WHERE policy_recovery_case_id=?""",(case_id,)).fetchone()
    if not r: raise ValueError("policy recovery case not found")
    return dict(r)

def cases(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_recommendation_policy_recovery_cases"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY policy_recovery_case_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def _event(con,case_id,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_policy_recovery_events(
      policy_recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (case_id,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def attribute_failure(rollback_reason,verdict=None):
    text=(rollback_reason or "").lower()
    if verdict=="RECOMMENDATION_HARMFUL" or "harmful recommendation" in text:
        return "RUNTIME_HARMFUL_RECOMMENDATION"
    if "context" in text or "ranking" in text:
        return "CONTEXT_RANKING_REGRESSION"
    if "acceptance" in text:
        return "HUMAN_ACCEPTANCE_MISALIGNMENT"
    if "shadow" in text:
        return "SHADOW_CHALLENGE_MODEL_REGRESSION"
    return "UNRESOLVED_RECOMMENDATION_POLICY_FAILURE"

def open_recovery_case(con,root_cause_type,rollback_reason,trigger_challenge_id=None,
                       trigger_policy_event_id=None,verdict=None):
    count=con.execute("""SELECT COUNT(*) n FROM origin_threshold_recommendation_policy_recovery_cases
                         WHERE root_cause_type=?""",(root_cause_type,)).fetchone()["n"]
    number=int(count)+1
    failure=attribute_failure(rollback_reason,verdict)
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_policy_recovery_cases(
      root_cause_type,rollback_number,trigger_policy_event_id,trigger_challenge_id,
      failure_type,status,rollback_reason,opened_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (root_cause_type,number,trigger_policy_event_id,trigger_challenge_id,
       failure,"OPEN",rollback_reason,_now()))
    case_id=cur.lastrowid
    con.commit()
    req=_requirements(number)
    if req["long_term"]:
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
          SET mode='LONG_TERM_SHADOW_ONLY',updated_at=? WHERE root_cause_type=?""",
          (_now(),root_cause_type))
        con.commit()
    _event(con,case_id,"RECOVERY_OPENED","policy-recovery-engine",
           {"rollback_number":number,"failure_type":failure,
            "long_term_shadow_only":req["long_term"]})
    return _case(con,case_id)

def add_remediation(con,case_id,remediation_type,remediation_ref,submitted_by,notes):
    if not remediation_type or not remediation_ref or not submitted_by:
        raise ValueError("remediation_type, remediation_ref, submitted_by required")
    c=_case(con,case_id)
    if c["status"] not in ("OPEN","REMEDIATION_SUBMITTED","WARMING"):
        raise ValueError("recovery case is not accepting remediation")
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_policy_recovery_remediations(
      policy_recovery_case_id,remediation_type,remediation_ref,status,
      submitted_by,notes,submitted_at)
      VALUES(?,?,?,?,?,?,?)""",
      (case_id,remediation_type,remediation_ref,"SUBMITTED",submitted_by,notes or "",_now()))
    con.execute("""UPDATE origin_threshold_recommendation_policy_recovery_cases
                   SET status='REMEDIATION_SUBMITTED' WHERE policy_recovery_case_id=?""",(case_id,))
    con.commit()
    _event(con,case_id,"REMEDIATION_SUBMITTED",submitted_by,
           {"remediation_type":remediation_type,"remediation_ref":remediation_ref})
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_policy_recovery_remediations
                              WHERE policy_recovery_remediation_id=?""",(cur.lastrowid,)).fetchone())

def review_remediation(con,remediation_id,decision,reviewer,reason):
    if decision not in ("EFFECTIVE","INEFFECTIVE","HOLD"):
        raise ValueError("invalid remediation decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_recovery_remediations
                     WHERE policy_recovery_remediation_id=?""",(remediation_id,)).fetchone()
    if not r: raise ValueError("recovery remediation not found")
    con.execute("""UPDATE origin_threshold_recommendation_policy_recovery_remediations
      SET status=?,effective_by=?,effective_at=? WHERE policy_recovery_remediation_id=?""",
      (decision,reviewer,_now(),remediation_id))
    con.commit()
    _event(con,r["policy_recovery_case_id"],"REMEDIATION_REVIEWED",reviewer,
           {"remediation_id":remediation_id,"decision":decision,"reason":reason})
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_policy_recovery_remediations
                              WHERE policy_recovery_remediation_id=?""",(remediation_id,)).fetchone())

def add_evidence(con,case_id,challenge_id,verdict,human_confirmed,notes=""):
    if verdict not in ("RECOMMENDATION_HELPFUL","RECOMMENDATION_HARMFUL","NEUTRAL"):
        raise ValueError("invalid recovery evidence verdict")
    c=_case(con,case_id)
    if c["status"] in ("REQUALIFIED","REJECTED"):
        raise ValueError("recovery case is closed")
    con.execute("""INSERT INTO origin_threshold_recommendation_policy_recovery_evidence(
      policy_recovery_case_id,challenge_id,verdict,human_confirmed,notes,observed_at)
      VALUES(?,?,?,?,?,?)""",
      (case_id,challenge_id,verdict,int(bool(human_confirmed)),notes or "",_now()))
    con.commit()
    return evaluate(con,case_id,persist=True)

def evaluate(con,case_id,persist=True):
    c=_case(con,case_id)
    req=_requirements(c["rollback_number"])
    rows=[dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recommendation_policy_recovery_evidence
           WHERE policy_recovery_case_id=? ORDER BY policy_recovery_evidence_id""",
        (case_id,)).fetchall()]
    decisive=[r for r in rows if r["human_confirmed"]]
    helpful=sum(r["verdict"]=="RECOMMENDATION_HELPFUL" for r in decisive)
    harmful=sum(r["verdict"]=="RECOMMENDATION_HARMFUL" for r in decisive)
    neutral=sum(r["verdict"]=="NEUTRAL" for r in decisive)
    distinct=len({r["challenge_id"] for r in decisive})
    rem=con.execute("""SELECT 1 FROM origin_threshold_recommendation_policy_recovery_remediations
                       WHERE policy_recovery_case_id=? AND status='EFFECTIVE'
                       ORDER BY policy_recovery_remediation_id DESC LIMIT 1""",(case_id,)).fetchone()
    remediation=bool(rem)
    from .origin_threshold_recommendation_versioning import recovery_successor_ready
    successor_check=recovery_successor_ready(con,case_id)
    reasons=[]
    if not remediation:
        reasons.append("fresh EFFECTIVE recommendation algorithm remediation required")
    if not successor_check["ready"]:
        reasons.append("new algorithm version lineage required: "+successor_check["reason"])
    if len(decisive)<req["decisive"]:
        reasons.append(f"fresh decisive Shadow challenges {len(decisive)}/{req['decisive']}")
    if helpful<req["helpful"]:
        reasons.append(f"fresh helpful outcomes {helpful}/{req['helpful']}")
    if harmful>0:
        reasons.append(f"harmful outcomes must be 0; have {harmful}")
    if distinct<req["decisive"]:
        reasons.append(f"distinct fresh challenges {distinct}/{req['decisive']}")
    if req["long_term"]:
        reasons.append("third-or-later rollback requires architecture review / explicit Human exception")
    if harmful>0:
        status="BLOCKED"
    elif not reasons:
        status="READY_FOR_RECANARY"
        con.execute("""UPDATE origin_threshold_recommendation_policy_recovery_cases
                       SET status='READY_FOR_RECANARY',ready_at=? WHERE policy_recovery_case_id=?""",
                    (_now(),case_id))
        con.commit()
    else:
        status="WARMING"
        if c["status"] not in ("REMEDIATION_SUBMITTED",):
            con.execute("""UPDATE origin_threshold_recommendation_policy_recovery_cases
                           SET status='WARMING' WHERE policy_recovery_case_id=?""",(case_id,))
            con.commit()
    result={
        "policy_version":POLICY_VERSION,"policy_recovery_case_id":case_id,
        "rollback_number":c["rollback_number"],"failure_type":c["failure_type"],
        "decisive_count":len(decisive),"helpful_count":helpful,
        "harmful_count":harmful,"neutral_count":neutral,
        "distinct_challenge_count":distinct,
        "required_decisive_count":req["decisive"],
        "required_helpful_count":req["helpful"],
        "remediation_effective":remediation,
        "successor_version_ready":successor_check["ready"],
        "successor_version_check":successor_check,
        "long_term_shadow_only":req["long_term"],
        "architecture_review_required":req["architecture"],
        "status":status,"reasons":reasons
    }
    if persist:
        cur=con.execute("""INSERT INTO origin_threshold_recommendation_policy_recovery_evaluations(
          policy_recovery_case_id,rollback_number,decisive_count,helpful_count,harmful_count,
          neutral_count,distinct_challenge_count,required_decisive_count,required_helpful_count,
          remediation_effective,long_term_shadow_only,architecture_review_required,status,
          reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (case_id,c["rollback_number"],len(decisive),helpful,harmful,neutral,distinct,
           req["decisive"],req["helpful"],int(remediation),int(req["long_term"]),
           int(req["architecture"]),status,json.dumps(reasons,ensure_ascii=False),_now()))
        result["policy_recovery_evaluation_id"]=cur.lastrowid
        con.commit()
    return result

def review_recanary(con,case_id,decision,reviewer,reason,canary_max=3,architecture_exception=False):
    if decision not in ("APPROVE_RECANARY","REJECT","HOLD"):
        raise ValueError("invalid recovery review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    ev=evaluate(con,case_id,persist=True)
    c=_case(con,case_id)
    req=_requirements(c["rollback_number"])
    if decision=="APPROVE_RECANARY":
        if req["long_term"] and not architecture_exception:
            raise ValueError("architecture_exception required after third rollback")
        if not ev["successor_version_ready"]:
            raise ValueError("new Human-approved successor algorithm version is required before re-canary")
        if ev["status"]!="READY_FOR_RECANARY":
            if not (req["long_term"] and architecture_exception and
                    ev["harmful_count"]==0 and ev["remediation_effective"] and
                    ev["successor_version_ready"] and
                    ev["decisive_count"]>=req["decisive"] and
                    ev["helpful_count"]>=req["helpful"]):
                raise ValueError("recovery case is not ready for re-canary")
        if canary_max<1 or canary_max>10:
            raise ValueError("canary_max must be 1..10")
        from .origin_threshold_recommendation_versioning import (
            recovery_links,mark_status
        )
        vlink=recovery_links(con,case_id)[0]
        mark_status(con,vlink["successor_algorithm_version_id"],"CANARY",reviewer,
                    "Human approved rollback recovery re-canary")
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
          SET mode='CANARY',canary_max_assignments=?,
              canary_assigned_count=0,canary_helpful_count=0,
              canary_harmful_count=0,canary_neutral_count=0,
              rollback_reason=NULL,updated_at=?
          WHERE root_cause_type=?""",(canary_max,_now(),c["root_cause_type"]))
        con.execute("""UPDATE origin_threshold_recommendation_policy_recovery_cases
                       SET status='RECANARY_APPROVED',requalified_at=? WHERE policy_recovery_case_id=?""",
                    (_now(),case_id))
    elif decision=="REJECT":
        con.execute("""UPDATE origin_threshold_recommendation_policy_recovery_cases
                       SET status='REJECTED' WHERE policy_recovery_case_id=?""",(case_id,))
    con.execute("""INSERT INTO origin_threshold_recommendation_policy_recovery_reviews(
      policy_recovery_case_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(case_id,decision,reviewer,reason,_now()))
    con.commit()
    _event(con,case_id,"RECOVERY_REVIEW",reviewer,
           {"decision":decision,"reason":reason,
            "architecture_exception":bool(architecture_exception)})
    return {"case":_case(con,case_id),"evaluation":ev}

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "cases":cases(con)
    }
