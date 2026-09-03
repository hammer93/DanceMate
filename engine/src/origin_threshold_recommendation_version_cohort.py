import json
import statistics
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MIN_VERSION_DECISIVE=3
MIN_VERSION_HELPFUL=2

def _now():
    return datetime.now(timezone.utc).isoformat()

def _version_for_challenge(con,challenge_id):
    r=con.execute("""SELECT v.* FROM origin_threshold_recommendation_algorithm_lineage l
      JOIN origin_threshold_recommendation_algorithm_versions v
        ON v.algorithm_version_id=l.algorithm_version_id
      WHERE l.entity_type='CHALLENGE' AND l.entity_id=? AND l.relation_type='EVALUATED_BY'
      ORDER BY l.algorithm_lineage_id DESC LIMIT 1""",(challenge_id,)).fetchone()
    return dict(r) if r else None

def _challenge(con,challenge_id):
    r=con.execute("""SELECT * FROM origin_threshold_architecture_recommendation_challenges
                     WHERE challenge_id=?""",(challenge_id,)).fetchone()
    return dict(r) if r else None

def _phase(version_status):
    if version_status=="CANARY":
        return "CANARY"
    if version_status=="PROMOTED":
        return "PRODUCTION"
    return "SHADOW"

def register_runtime(con,challenge_runtime_result_id):
    rr=con.execute("""SELECT * FROM origin_threshold_architecture_challenge_runtime_results
      WHERE challenge_runtime_result_id=?""",(challenge_runtime_result_id,)).fetchone()
    if not rr:
        raise ValueError("challenge runtime result not found")
    existing=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_runtime_cohorts
      WHERE challenge_runtime_result_id=?""",(challenge_runtime_result_id,)).fetchone()
    if existing:
        return dict(existing)
    ch=_challenge(con,rr["challenge_id"])
    alg=_version_for_challenge(con,rr["challenge_id"])
    if not ch or not alg:
        return None
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_runtime_cohorts(
      algorithm_version_id,root_cause_type,challenge_id,challenge_runtime_result_id,
      architecture_runtime_outcome_id,context_signature,runtime_phase,selected_side,
      runtime_status,counterfactual_verdict,days_to_reisolation,started_at,finalized_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (alg["algorithm_version_id"],ch["root_cause_type"],rr["challenge_id"],
       challenge_runtime_result_id,rr["architecture_runtime_outcome_id"],
       ch["context_signature"],_phase(alg["status"]),rr["selected_side"],
       rr["runtime_status"],rr["counterfactual_verdict"],rr["days_to_reisolation"],
       _now(),rr["finalized_at"]))
    con.commit()
    refresh_profile(con,alg["algorithm_version_id"],ch["context_signature"])
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_runtime_cohorts
                              WHERE algorithm_runtime_cohort_id=?""",(cur.lastrowid,)).fetchone())

def finalize_runtime(con,challenge_runtime_result_id):
    rr=con.execute("""SELECT * FROM origin_threshold_architecture_challenge_runtime_results
      WHERE challenge_runtime_result_id=?""",(challenge_runtime_result_id,)).fetchone()
    if not rr:
        raise ValueError("challenge runtime result not found")
    row=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_runtime_cohorts
      WHERE challenge_runtime_result_id=?""",(challenge_runtime_result_id,)).fetchone()
    if not row:
        created=register_runtime(con,challenge_runtime_result_id)
        if not created:
            return None
        row=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_runtime_cohorts
          WHERE challenge_runtime_result_id=?""",(challenge_runtime_result_id,)).fetchone()
    con.execute("""UPDATE origin_threshold_recommendation_algorithm_runtime_cohorts
      SET runtime_status=?,counterfactual_verdict=?,days_to_reisolation=?,finalized_at=?
      WHERE challenge_runtime_result_id=?""",
      (rr["runtime_status"],rr["counterfactual_verdict"],rr["days_to_reisolation"],
       rr["finalized_at"] or _now(),challenge_runtime_result_id))
    con.commit()
    refresh_profile(con,row["algorithm_version_id"],row["context_signature"])
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_runtime_cohorts
      WHERE challenge_runtime_result_id=?""",(challenge_runtime_result_id,)).fetchone())

def cohorts(con,algorithm_version_id=None,context_signature=None):
    sql="""SELECT * FROM origin_threshold_recommendation_algorithm_runtime_cohorts WHERE 1=1"""
    params=[]
    if algorithm_version_id is not None:
        sql+=" AND algorithm_version_id=?"; params.append(algorithm_version_id)
    if context_signature is not None:
        sql+=" AND context_signature=?"; params.append(context_signature)
    sql+=" ORDER BY algorithm_runtime_cohort_id"
    return [dict(r) for r in con.execute(sql,tuple(params)).fetchall()]

def _profile_rows(con,algorithm_version_id,context_signature):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recommendation_algorithm_runtime_cohorts
           WHERE algorithm_version_id=? AND context_signature=?""",
        (algorithm_version_id,context_signature)).fetchall()]

def refresh_profile(con,algorithm_version_id,context_signature):
    rows=_profile_rows(con,algorithm_version_id,context_signature)
    if not rows:
        return None
    root=rows[0]["root_cause_type"]
    decisive=[r for r in rows if r["runtime_status"] in ("SUSTAINED_SUCCESS","RECURRENCE_FAILED")]
    helpful=sum(r["counterfactual_verdict"]=="RECOMMENDATION_HELPFUL" for r in decisive)
    harmful=sum(r["counterfactual_verdict"]=="RECOMMENDATION_HARMFUL" for r in decisive)
    neutral=len(decisive)-helpful-harmful
    canary=sum(r["runtime_phase"]=="CANARY" for r in decisive)
    production=sum(r["runtime_phase"]=="PRODUCTION" for r in decisive)
    rollbacks=sum(r["runtime_status"]=="RECURRENCE_FAILED" for r in decisive)
    helpful_rate=(helpful/len(decisive)) if decisive else None
    harmful_rate=(harmful/len(decisive)) if decisive else None
    survival=[]
    for r in decisive:
        if r["runtime_status"]=="SUSTAINED_SUCCESS":
            survival.append(90.0)
        elif r["days_to_reisolation"] is not None:
            survival.append(float(r["days_to_reisolation"]))
    median_survival=statistics.median(survival) if survival else None
    n=len(decisive)
    if n<3: confidence="LOW_DATA"
    elif n<5: confidence="EMERGING"
    else: confidence="ESTABLISHED"
    if harmful>0:
        safety="UNSAFE"
    elif n>=MIN_VERSION_DECISIVE and helpful>=MIN_VERSION_HELPFUL:
        safety="SAFE"
    else:
        safety="WATCH"
    if harmful>0:
        memory_status="VERSION_ROLLBACK_EVIDENCE"
    elif canary>=3 and helpful>=2:
        memory_status="VERSION_CANARY_PROVEN"
    elif production>=5 and helpful>=3:
        memory_status="VERSION_PRODUCTION_PROVEN"
    else:
        memory_status="VERSION_WARMING"
    reasons=[
        f"decisive={n}",f"canary={canary}",f"production={production}",
        f"helpful={helpful}",f"harmful={harmful}",f"neutral={neutral}",
        f"rollbacks={rollbacks}",f"confidence={confidence}",f"safety={safety}"
    ]
    existing=con.execute("""SELECT algorithm_version_profile_id
      FROM origin_threshold_recommendation_algorithm_version_profiles
      WHERE algorithm_version_id=? AND context_signature=?""",
      (algorithm_version_id,context_signature)).fetchone()
    vals=(len(rows),n,canary,production,helpful,harmful,neutral,rollbacks,
          helpful_rate,harmful_rate,median_survival,confidence,safety,memory_status,
          json.dumps(reasons,ensure_ascii=False),_now())
    if existing:
        con.execute("""UPDATE origin_threshold_recommendation_algorithm_version_profiles
          SET total_runtime_count=?,decisive_runtime_count=?,canary_runtime_count=?,
              production_runtime_count=?,helpful_count=?,harmful_count=?,neutral_count=?,
              rollback_count=?,helpful_rate=?,harmful_rate=?,median_survival_days=?,
              confidence_band=?,safety_band=?,promotion_memory_status=?,
              reasons_json=?,updated_at=?
          WHERE algorithm_version_profile_id=?""",vals+(existing["algorithm_version_profile_id"],))
    else:
        con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_version_profiles(
          algorithm_version_id,root_cause_type,context_signature,total_runtime_count,
          decisive_runtime_count,canary_runtime_count,production_runtime_count,
          helpful_count,harmful_count,neutral_count,rollback_count,helpful_rate,
          harmful_rate,median_survival_days,confidence_band,safety_band,
          promotion_memory_status,reasons_json,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (algorithm_version_id,root,context_signature)+vals)
    con.commit()
    return profile(con,algorithm_version_id,context_signature)

def profile(con,algorithm_version_id,context_signature):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_version_profiles
      WHERE algorithm_version_id=? AND context_signature=?""",
      (algorithm_version_id,context_signature)).fetchone()
    if not r: return None
    x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); return x

def profiles(con,algorithm_version_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_algorithm_version_profiles"""
    params=()
    if algorithm_version_id is not None:
        sql+=" WHERE algorithm_version_id=?"; params=(algorithm_version_id,)
    sql+=" ORDER BY algorithm_version_profile_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def evaluate_version(con,algorithm_version_id,context_signature,persist=True):
    p=refresh_profile(con,algorithm_version_id,context_signature)
    if not p:
        return {"policy_version":POLICY_VERSION,"algorithm_version_id":algorithm_version_id,
                "context_signature":context_signature,"status":"NO_DATA","reasons":["no runtime cohort"]}
    reasons=[]
    if p["harmful_count"]>0:
        status="BLOCKED"
        reasons.append("version has harmful runtime evidence")
    elif p["canary_runtime_count"]>=3 and p["helpful_count"]>=2:
        status="READY_FOR_VERSION_PROMOTION"
    elif p["production_runtime_count"]>=5 and p["helpful_count"]>=3:
        status="PRODUCTION_PROVEN"
    else:
        status="WARMING"
        reasons.append("insufficient version-level runtime evidence")
    result={
        "policy_version":POLICY_VERSION,
        "algorithm_version_id":algorithm_version_id,
        "root_cause_type":p["root_cause_type"],
        "context_signature":context_signature,
        "decisive_runtime_count":p["decisive_runtime_count"],
        "canary_runtime_count":p["canary_runtime_count"],
        "production_runtime_count":p["production_runtime_count"],
        "helpful_count":p["helpful_count"],
        "harmful_count":p["harmful_count"],
        "neutral_count":p["neutral_count"],
        "helpful_rate":p["helpful_rate"],
        "harmful_rate":p["harmful_rate"],
        "median_survival_days":p["median_survival_days"],
        "status":status,"reasons":reasons
    }
    if persist:
        con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_version_evaluations(
          algorithm_version_id,root_cause_type,context_signature,decisive_runtime_count,
          canary_runtime_count,production_runtime_count,helpful_count,harmful_count,
          neutral_count,helpful_rate,harmful_rate,median_survival_days,status,
          reasons_json,evaluated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (algorithm_version_id,p["root_cause_type"],context_signature,
           p["decisive_runtime_count"],p["canary_runtime_count"],p["production_runtime_count"],
           p["helpful_count"],p["harmful_count"],p["neutral_count"],p["helpful_rate"],
           p["harmful_rate"],p["median_survival_days"],status,
           json.dumps(reasons,ensure_ascii=False),_now()))
        con.commit()
    return result

def evaluations(con,algorithm_version_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_algorithm_version_evaluations"""
    params=()
    if algorithm_version_id is not None:
        sql+=" WHERE algorithm_version_id=?"; params=(algorithm_version_id,)
    sql+=" ORDER BY algorithm_version_evaluation_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "cohorts":cohorts(con),
        "profiles":profiles(con),
        "evaluations":evaluations(con),
    }
