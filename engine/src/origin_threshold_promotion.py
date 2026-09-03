import json
from datetime import datetime, timezone

POLICY_VERSION="v0.62"
BASELINE_THRESHOLD=0.86
MIN_SHADOW_DECISIVE_REVIEWS=7
DEFAULT_CANARY_MAX_ASSIGNMENTS=3

def _now():
    return datetime.now(timezone.utc).isoformat()

def _json(v):
    try:
        return json.loads(v) if v else []
    except Exception:
        return []

def _latest_human_outcomes(con):
    rows=con.execute("""SELECT c.cluster_id,c.event_instance_id,c.status,c.member_count,
                              r.decision,r.reviewed_at
      FROM cross_post_clusters c
      JOIN origin_inference_reviews r ON r.cluster_id=c.cluster_id
      JOIN (
        SELECT cluster_id,MAX(review_id) review_id
        FROM origin_inference_reviews GROUP BY cluster_id
      ) latest ON latest.review_id=r.review_id
      WHERE r.decision IN ('CONFIRM_SYNDICATION','CONFIRM_INDEPENDENT')
      ORDER BY r.review_id""").fetchall()
    out=[]
    for r in rows:
        ms=con.execute("""SELECT MAX(text_similarity) max_sim
                          FROM cross_post_cluster_members
                          WHERE cluster_id=?""",(r["cluster_id"],)).fetchone()
        ev=con.execute("""SELECT status FROM event_instances
                          WHERE event_instance_id=?""",(r["event_instance_id"],)).fetchone()
        out.append({
            "cluster_id":r["cluster_id"],
            "event_instance_id":r["event_instance_id"],
            "decision":r["decision"],
            "max_text_similarity":float(ms["max_sim"] or 0),
            "event_status":ev["status"] if ev else None
        })
    return out

def _metrics_for_threshold(rows,threshold):
    tp=fp=fn=tn=critical_fn=0
    for r in rows:
        predicted = r["max_text_similarity"] >= float(threshold)
        actual = r["decision"]=="CONFIRM_SYNDICATION"
        if predicted and actual: tp+=1
        elif predicted and not actual: fp+=1
        elif not predicted and actual:
            fn+=1
            if r.get("event_status")=="VERIFIED":
                critical_fn+=1
        else: tn+=1
    precision=(tp/(tp+fp)) if tp+fp else None
    recall=(tp/(tp+fn)) if tp+fn else None
    fpr=(fp/(fp+tn)) if fp+tn else 0.0
    return {
        "tp":tp,"fp":fp,"fn":fn,"tn":tn,
        "precision":precision,"recall":recall,
        "false_positive_rate":fpr,
        "missed_syndication_count":fn,
        "critical_missed_syndication_count":critical_fn
    }

def _candidate_row(con,candidate_id):
    r=con.execute("""SELECT * FROM origin_threshold_candidates
                     WHERE candidate_id=?""",(candidate_id,)).fetchone()
    if not r: raise ValueError("threshold candidate not found")
    x=dict(r); x["reasons"]=_json(x.pop("reasons_json"))
    return x

def candidates(con):
    rows=con.execute("""SELECT * FROM origin_threshold_candidates
                       ORDER BY candidate_id""").fetchall()
    out=[]
    for r in rows:
        x=dict(r); x["reasons"]=_json(x.pop("reasons_json"))
        out.append(x)
    return out

def create_candidate_from_latest_calibration(con):
    unresolved=con.execute("""SELECT recovery_case_id,status
      FROM origin_threshold_recovery_cases
      WHERE status<>'REQUALIFIED'
      ORDER BY recovery_case_id DESC LIMIT 1""").fetchone()
    if unresolved:
        raise ValueError(
            f"runtime recovery case {unresolved['recovery_case_id']} requires Human requalification before a new threshold candidate")
    cal=con.execute("""SELECT * FROM origin_inference_calibrations
                       ORDER BY calibration_id DESC LIMIT 1""").fetchone()
    if not cal:
        raise ValueError("origin calibration is required before threshold candidate creation")
    if cal["recommendation_status"] not in ("SHADOW_TIGHTEN","SHADOW_RELAX"):
        raise ValueError("latest calibration does not recommend a candidate threshold")
    existing=con.execute("""SELECT candidate_id,status FROM origin_threshold_candidates
                            WHERE calibration_id=?""",(cal["calibration_id"],)).fetchone()
    if existing:
        if existing["status"]=="RUNTIME_ROLLED_BACK":
            raise ValueError(
                "runtime-rolled-back threshold candidate cannot be reused; run a new calibration after Human requalification")
        return _candidate_row(con,existing["candidate_id"])

    # Long-term recurrence restrictions survive Recovery requalification.
    # Each new promotion attempt needs an explicit one-time Human exception.
    from .origin_threshold_recurrence_guard import consume_exception_for_candidate
    consumed_exception_ids=consume_exception_for_candidate(con)

    base=float(cal["baseline_text_threshold"])
    cand=float(cal["shadow_recommended_text_threshold"])
    rows=_latest_human_outcomes(con)
    bm=_metrics_for_threshold(rows,base)
    cm=_metrics_for_threshold(rows,cand)
    decisive=len(rows)
    direction="TIGHTEN" if cand>base else "RELAX"

    reasons=[]
    gate="BLOCKED"
    if decisive < MIN_SHADOW_DECISIVE_REVIEWS:
        reasons.append(
            f"need >= {MIN_SHADOW_DECISIVE_REVIEWS} decisive Human outcomes for promotion gate; have {decisive}")
    else:
        safe=True
        if direction=="TIGHTEN":
            # Tightening may reduce false positives, but must not add missed
            # syndications, especially on VERIFIED events.
            if cm["false_positive_rate"] > bm["false_positive_rate"] + 1e-12:
                safe=False; reasons.append("candidate does not improve false-positive rate")
            if cm["missed_syndication_count"] > bm["missed_syndication_count"]:
                safe=False; reasons.append("candidate adds missed syndication outcomes")
        else:
            # Relaxing may improve recall but must not add false positives.
            if cm["missed_syndication_count"] > bm["missed_syndication_count"]:
                safe=False; reasons.append("candidate worsens missed syndication outcomes")
            if cm["false_positive_rate"] > bm["false_positive_rate"] + 1e-12:
                safe=False; reasons.append("candidate adds false-positive outcomes")
        if cm["critical_missed_syndication_count"]>0:
            safe=False; reasons.append("candidate has critical missed syndication on VERIFIED event")
        if safe:
            gate="READY_FOR_HUMAN_REVIEW"
            reasons.append("historical Human outcomes satisfy Shadow promotion safety gate")
        elif not reasons:
            reasons.append("candidate failed Shadow comparison gate")

    cur=con.execute("""INSERT INTO origin_threshold_candidates(
      calibration_id,baseline_threshold,candidate_threshold,direction,status,
      shadow_gate_status,decisive_review_count,base_precision,candidate_precision,
      base_false_positive_rate,candidate_false_positive_rate,
      base_missed_syndication_count,candidate_missed_syndication_count,
      critical_missed_syndication_count,reasons_json,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cal["calibration_id"],base,cand,direction,"SHADOW",gate,decisive,
       bm["precision"],cm["precision"],bm["false_positive_rate"],
       cm["false_positive_rate"],bm["missed_syndication_count"],
       cm["missed_syndication_count"],cm["critical_missed_syndication_count"],
       json.dumps(reasons,ensure_ascii=False),_now(),_now()))
    cid=cur.lastrowid
    con.execute("""INSERT INTO origin_threshold_events(
      candidate_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (cid,"CANDIDATE_CREATED","origin-threshold-promotion",
       json.dumps({"shadow_gate_status":gate,"direction":direction},ensure_ascii=False),_now()))
    con.commit()
    result=_candidate_row(con,cid)
    result["consumed_restriction_exception_ids"]=consumed_exception_ids
    return result

def review_candidate(con,candidate_id,decision,reviewer,reason):
    if decision not in ("APPROVE_CANARY","REJECT","HOLD"):
        raise ValueError("invalid threshold review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason are required")
    c=_candidate_row(con,candidate_id)
    if decision=="APPROVE_CANARY" and c["shadow_gate_status"]!="READY_FOR_HUMAN_REVIEW":
        raise ValueError("candidate is not ready for Human canary approval")
    con.execute("""INSERT INTO origin_threshold_reviews(
      candidate_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(candidate_id,decision,reviewer,reason,_now()))
    status={"APPROVE_CANARY":"CANARY_APPROVED","REJECT":"REJECTED","HOLD":"HOLD"}[decision]
    con.execute("""UPDATE origin_threshold_candidates SET status=?,updated_at=?
                   WHERE candidate_id=?""",(status,_now(),candidate_id))
    con.execute("""INSERT INTO origin_threshold_events(
      candidate_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (candidate_id,f"HUMAN_{decision}",reviewer,
       json.dumps({"reason":reason},ensure_ascii=False),_now()))
    con.commit()
    return _candidate_row(con,candidate_id)

def start_canary(con,candidate_id,approved_by,max_assignments=DEFAULT_CANARY_MAX_ASSIGNMENTS):
    if not approved_by: raise ValueError("approved_by is required")
    if int(max_assignments)<1 or int(max_assignments)>10:
        raise ValueError("max_assignments must be 1..10")
    c=_candidate_row(con,candidate_id)
    if c["status"]!="CANARY_APPROVED":
        raise ValueError("candidate requires APPROVE_CANARY Human review")
    active=con.execute("""SELECT canary_id FROM origin_threshold_canaries
                          WHERE status='ACTIVE' LIMIT 1""").fetchone()
    if active:
        raise ValueError("another origin threshold canary is already active")
    cur=con.execute("""INSERT INTO origin_threshold_canaries(
      candidate_id,status,max_assignments,assigned_count,
      confirmed_syndication_count,confirmed_independent_count,hold_count,
      missed_syndication_count,critical_missed_syndication_count,
      approved_by,started_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
      (candidate_id,"ACTIVE",int(max_assignments),0,0,0,0,0,0,approved_by,_now()))
    canary_id=cur.lastrowid
    con.execute("""UPDATE origin_threshold_candidates SET status='CANARY_ACTIVE',
                   updated_at=? WHERE candidate_id=?""",(_now(),candidate_id))
    con.execute("""INSERT INTO origin_threshold_events(
      candidate_id,canary_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (candidate_id,canary_id,"CANARY_STARTED",approved_by,
       json.dumps({"max_assignments":int(max_assignments)},ensure_ascii=False),_now()))
    con.commit()
    return canary(con,canary_id)

def canary(con,canary_id):
    r=con.execute("""SELECT * FROM origin_threshold_canaries
                     WHERE canary_id=?""",(canary_id,)).fetchone()
    if not r: raise ValueError("canary not found")
    x=dict(r)
    x["assignments"]=[dict(a) for a in con.execute(
        """SELECT * FROM origin_threshold_canary_assignments
           WHERE canary_id=? ORDER BY assignment_id""",(canary_id,)).fetchall()]
    return x

def canaries(con):
    rows=con.execute("""SELECT canary_id FROM origin_threshold_canaries
                       ORDER BY canary_id""").fetchall()
    return [canary(con,r["canary_id"]) for r in rows]

def active_full_threshold(con,baseline=BASELINE_THRESHOLD):
    r=con.execute("""SELECT * FROM origin_threshold_promotions
                     WHERE status='ACTIVE' ORDER BY promotion_id DESC LIMIT 1""").fetchone()
    return float(r["production_threshold"]) if r else float(baseline)

def effective_threshold(con,event_instance_id,baseline=BASELINE_THRESHOLD):
    # Full promotion is the normal production value. A Human-approved canary
    # gets a bounded number of explicit Event assignments.
    base=active_full_threshold(con,baseline)
    ca=con.execute("""SELECT c.*,tc.baseline_threshold,tc.candidate_threshold
      FROM origin_threshold_canaries c
      JOIN origin_threshold_candidates tc ON tc.candidate_id=c.candidate_id
      WHERE c.status='ACTIVE' ORDER BY c.canary_id DESC LIMIT 1""").fetchone()
    if not ca:
        return {"threshold":base,"mode":"BASE_OR_FULL","canary_id":None}

    existing=con.execute("""SELECT * FROM origin_threshold_canary_assignments
      WHERE canary_id=? AND event_instance_id=?""",
      (ca["canary_id"],event_instance_id)).fetchone()
    if existing:
        return {
            "threshold":float(existing["candidate_threshold"]),
            "mode":"CANARY","canary_id":ca["canary_id"]
        }

    if int(ca["assigned_count"])>=int(ca["max_assignments"]):
        return {"threshold":base,"mode":"BASE_OR_FULL","canary_id":None}

    con.execute("""INSERT INTO origin_threshold_canary_assignments(
      canary_id,event_instance_id,baseline_threshold,candidate_threshold,assigned_at)
      VALUES(?,?,?,?,?)""",
      (ca["canary_id"],event_instance_id,float(ca["baseline_threshold"]),
       float(ca["candidate_threshold"]),_now()))
    con.execute("""UPDATE origin_threshold_canaries SET assigned_count=assigned_count+1
                   WHERE canary_id=?""",(ca["canary_id"],))
    con.execute("""INSERT INTO origin_threshold_events(
      candidate_id,canary_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (ca["candidate_id"],ca["canary_id"],"CANARY_ASSIGNED",
       "origin-threshold-runtime",
       json.dumps({"event_instance_id":event_instance_id,
                   "candidate_threshold":float(ca["candidate_threshold"])},
                  ensure_ascii=False),_now()))
    con.commit()
    return {
        "threshold":float(ca["candidate_threshold"]),
        "mode":"CANARY","canary_id":ca["canary_id"]
    }

def _rollback_canary(con,canary_id,reason,actor="origin-threshold-runtime"):
    ca=canary(con,canary_id)
    if ca["status"]!="ACTIVE":
        return ca
    con.execute("""UPDATE origin_threshold_canaries
      SET status='ROLLED_BACK',rollback_reason=?,rolled_back_at=?
      WHERE canary_id=?""",(reason,_now(),canary_id))
    con.execute("""UPDATE origin_threshold_candidates SET status='CANARY_ROLLED_BACK',
                   updated_at=? WHERE candidate_id=?""",
                (_now(),ca["candidate_id"]))
    con.execute("""INSERT INTO origin_threshold_events(
      candidate_id,canary_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (ca["candidate_id"],canary_id,"CANARY_AUTO_ROLLBACK",actor,
       json.dumps({"reason":reason},ensure_ascii=False),_now()))
    con.commit()
    return canary(con,canary_id)

def record_canary_outcome(
    con,event_instance_id,cluster_id,decision,critical=False):
    a=con.execute("""SELECT a.*,c.status canary_status,c.candidate_id,c.max_assignments
      FROM origin_threshold_canary_assignments a
      JOIN origin_threshold_canaries c ON c.canary_id=a.canary_id
      WHERE a.event_instance_id=?
      ORDER BY a.assignment_id DESC LIMIT 1""",(event_instance_id,)).fetchone()
    if not a or a["outcome"] is not None:
        return None
    if decision not in (
        "CONFIRM_SYNDICATION","CONFIRM_INDEPENDENT","HOLD","MISSED_SYNDICATION"):
        return None
    con.execute("""UPDATE origin_threshold_canary_assignments
      SET outcome=?,outcome_cluster_id=?,outcome_at=?
      WHERE assignment_id=?""",(decision,cluster_id,_now(),a["assignment_id"]))
    if decision=="MISSED_SYNDICATION":
        con.execute("""UPDATE origin_threshold_canaries
          SET missed_syndication_count=missed_syndication_count+1,
              critical_missed_syndication_count=critical_missed_syndication_count+?
          WHERE canary_id=?""",(1 if critical else 0,a["canary_id"]))
    else:
        col={
            "CONFIRM_SYNDICATION":"confirmed_syndication_count",
            "CONFIRM_INDEPENDENT":"confirmed_independent_count",
            "HOLD":"hold_count"
        }[decision]
        con.execute(f"""UPDATE origin_threshold_canaries
                        SET {col}={col}+1 WHERE canary_id=?""",(a["canary_id"],))
    con.commit()

    # Fail-closed: a Human-confirmed false positive or any missed syndication
    # during the bounded canary immediately restores the Base/previous Full threshold.
    if decision=="CONFIRM_INDEPENDENT":
        return _rollback_canary(
            con,a["canary_id"],
            "Human review found false-positive Cross-Post during threshold canary")
    if decision=="MISSED_SYNDICATION":
        return _rollback_canary(
            con,a["canary_id"],
            "Human review found missed syndication during threshold canary"
            + (" on critical/VERIFIED event" if critical else ""))

    ca=canary(con,a["canary_id"])
    completed=sum(x["outcome"] is not None for x in ca["assignments"])
    # HOLD is not a safe outcome, so it cannot complete a promotion canary.
    safe_confirmed=int(ca["confirmed_syndication_count"])
    if (ca["status"]=="ACTIVE"
        and completed>=int(ca["max_assignments"])
        and safe_confirmed>=int(ca["max_assignments"])):
        con.execute("""UPDATE origin_threshold_canaries
          SET status='READY_FOR_FINAL_REVIEW',completed_at=?
          WHERE canary_id=?""",(_now(),a["canary_id"]))
        con.execute("""UPDATE origin_threshold_candidates
          SET status='CANARY_READY_FOR_FINAL_REVIEW',updated_at=?
          WHERE candidate_id=?""",(_now(),a["candidate_id"]))
        con.execute("""INSERT INTO origin_threshold_events(
          candidate_id,canary_id,event_type,actor,detail_json,created_at)
          VALUES(?,?,?,?,?,?)""",
          (a["candidate_id"],a["canary_id"],"CANARY_COMPLETED",
           "origin-threshold-runtime",
           json.dumps({"completed_safe_outcomes":safe_confirmed},
                      ensure_ascii=False),_now()))
        con.commit()
    return canary(con,a["canary_id"])

def promote_candidate(con,candidate_id,reviewer,reason):
    if not reviewer or not reason:
        raise ValueError("reviewer and reason are required")
    c=_candidate_row(con,candidate_id)
    ca=con.execute("""SELECT * FROM origin_threshold_canaries
      WHERE candidate_id=? ORDER BY canary_id DESC LIMIT 1""",(candidate_id,)).fetchone()
    if not ca or ca["status"]!="READY_FOR_FINAL_REVIEW":
        raise ValueError("successful completed canary is required before Full promotion")
    if int(ca["confirmed_independent_count"])>0:
        raise ValueError("canary contains false-positive outcome")
    decisive=int(ca["confirmed_syndication_count"])
    if decisive < int(ca["max_assignments"]):
        raise ValueError("all canary assignments require confirmed safe outcomes")
    con.execute("""UPDATE origin_threshold_promotions
                   SET status='SUPERSEDED'
                   WHERE status='ACTIVE'""")
    cur=con.execute("""INSERT INTO origin_threshold_promotions(
      candidate_id,canary_id,status,production_threshold,approved_by,reason,promoted_at)
      VALUES(?,?,?,?,?,?,?)""",
      (candidate_id,ca["canary_id"],"ACTIVE",float(c["candidate_threshold"]),
       reviewer,reason,_now()))
    pid=cur.lastrowid
    con.execute("""UPDATE origin_threshold_candidates
                   SET status='FULL_PROMOTED',updated_at=?
                   WHERE candidate_id=?""",(_now(),candidate_id))
    con.execute("""INSERT INTO origin_threshold_events(
      candidate_id,canary_id,promotion_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?,?)""",
      (candidate_id,ca["canary_id"],pid,"FULL_PROMOTED",reviewer,
       json.dumps({"production_threshold":float(c["candidate_threshold"]),
                   "reason":reason},ensure_ascii=False),_now()))
    con.commit()
    return promotion(con,pid)

def promotion(con,promotion_id):
    r=con.execute("""SELECT * FROM origin_threshold_promotions
                     WHERE promotion_id=?""",(promotion_id,)).fetchone()
    if not r: raise ValueError("promotion not found")
    return dict(r)

def promotions(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_promotions ORDER BY promotion_id""").fetchall()]

def rollback_promotion(con,promotion_id,reviewer,reason):
    if not reviewer or not reason:
        raise ValueError("reviewer and reason are required")
    p=promotion(con,promotion_id)
    if p["status"]!="ACTIVE":
        raise ValueError("only ACTIVE promotion can be rolled back")
    con.execute("""UPDATE origin_threshold_promotions
                   SET status='ROLLED_BACK',rolled_back_at=?,rollback_reason=?
                   WHERE promotion_id=?""",(_now(),reason,promotion_id))
    con.execute("""INSERT INTO origin_threshold_events(
      candidate_id,canary_id,promotion_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?,?)""",
      (p["candidate_id"],p["canary_id"],promotion_id,"FULL_ROLLBACK",reviewer,
       json.dumps({"reason":reason},ensure_ascii=False),_now()))
    con.commit()
    return promotion(con,promotion_id)

def runtime_status(con):
    active_canary=con.execute("""SELECT canary_id FROM origin_threshold_canaries
                                WHERE status='ACTIVE' ORDER BY canary_id DESC LIMIT 1""").fetchone()
    active_promo=con.execute("""SELECT promotion_id,production_threshold
      FROM origin_threshold_promotions WHERE status='ACTIVE'
      ORDER BY promotion_id DESC LIMIT 1""").fetchone()
    return {
        "policy_version":POLICY_VERSION,
        "base_threshold":BASELINE_THRESHOLD,
        "active_canary":canary(con,active_canary["canary_id"]) if active_canary else None,
        "active_full_promotion":dict(active_promo) if active_promo else None,
        "effective_full_threshold":
            float(active_promo["production_threshold"]) if active_promo else BASELINE_THRESHOLD
    }
