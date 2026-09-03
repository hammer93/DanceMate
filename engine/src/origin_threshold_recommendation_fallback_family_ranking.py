import json
import math
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MIN_PREFERRED_ATTEMPTS=2
MIN_PREFERRED_SUSTAINED=2
MIN_PREFERRED_SCORE=0.50
MIN_PREFERRED_MARGIN=0.10

def _now():
    return datetime.now(timezone.utc).isoformat()

def _wilson_lower(successes,n,z=1.96):
    if n<=0:
        return 0.0
    phat=successes/n
    denom=1.0+z*z/n
    center=phat+z*z/(2*n)
    adj=z*math.sqrt((phat*(1-phat)+z*z/(4*n))/n)
    return max(0.0,(center-adj)/denom)

def _case(con,case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_cases
                     WHERE family_recovery_case_id=?""",(case_id,)).fetchone()
    if not r:
        raise ValueError("family recovery case not found")
    return dict(r)

def _event(con,case_id,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_ranking_events(
      family_recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (case_id,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def rankings(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_rankings"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_recovery_case_id,rank_position,family_remediation_ranking_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def recommendations(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_recommendations"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_remediation_recommendation_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def selection_reviews(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_selection_reviews"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_remediation_selection_review_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def events(con,case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_ranking_events"""
    params=()
    if case_id is not None:
        sql+=" WHERE family_recovery_case_id=?"; params=(case_id,)
    sql+=" ORDER BY family_remediation_ranking_event_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def _profile_root(con,profile):
    r=con.execute("""SELECT root_cause_type FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE family_signature=? AND remediation_type=? AND remediation_ref=?
      ORDER BY family_generation_outcome_id DESC LIMIT 1""",
      (profile["family_signature"],profile["remediation_type"],profile["remediation_ref"])).fetchone()
    return r["root_cause_type"] if r else None

def _survival_score(profile):
    sustained=int(profile["sustained_success_count"] or 0)
    failed=int(profile["recurrence_failure_count"] or 0)
    if sustained and not failed:
        return 1.0
    avg=profile["avg_days_to_family_recurrence"]
    if avg is None:
        return 0.5 if sustained else 0.0
    return min(max(float(avg)/90.0,0.0),1.0)

def _score_profile(current_case,profile):
    decisive=int(profile["sustained_success_count"] or 0)+int(profile["recurrence_failure_count"] or 0)
    sustained=int(profile["sustained_success_count"] or 0)
    failed=int(profile["recurrence_failure_count"] or 0)
    attempts=int(profile["attempt_count"] or 0)
    wilson=_wilson_lower(sustained,decisive)
    survival=_survival_score(profile)
    evidence=min(attempts/5.0,1.0)
    context_similarity=1.0 if profile["family_signature"]==current_case["family_signature"] else 0.65
    recurrence_penalty=min(failed*0.20,0.60)
    score=(wilson*0.40 + survival*0.20 + evidence*0.20 +
           context_similarity*0.20 - recurrence_penalty)
    score=max(0.0,min(1.0,score))
    if profile["effectiveness_band"]=="AVOID" or failed>=2:
        state="AVOID"
    elif decisive<1 or attempts<2:
        state="LOW_DATA"
    elif (profile["family_signature"]==current_case["family_signature"]
          and sustained>=MIN_PREFERRED_SUSTAINED and failed==0
          and attempts>=MIN_PREFERRED_ATTEMPTS and score>=MIN_PREFERRED_SCORE):
        state="PREFERRED"
    elif failed>0:
        state="WATCH"
    else:
        state="LEARNING"
    reasons=[
        f"context_similarity={context_similarity:.2f}",
        f"attempts={attempts}",
        f"decisive={decisive}",
        f"sustained={sustained}",
        f"recurrence_failures={failed}",
        f"wilson_lower={wilson:.3f}",
        f"survival_score={survival:.3f}",
        f"evidence_score={evidence:.3f}",
        f"recurrence_penalty={recurrence_penalty:.3f}",
        f"conservative_score={score:.3f}",
        f"state={state}",
    ]
    return {
        "historical_family_signature":profile["family_signature"],
        "remediation_type":profile["remediation_type"],
        "remediation_ref":profile["remediation_ref"],
        "context_similarity":context_similarity,
        "attempt_count":attempts,
        "decisive_count":decisive,
        "sustained_success_count":sustained,
        "recurrence_failure_count":failed,
        "wilson_lower_bound":wilson,
        "survival_score":survival,
        "evidence_score":evidence,
        "recurrence_penalty":recurrence_penalty,
        "conservative_score":score,
        "confidence_band":profile["confidence_band"],
        "effectiveness_band":profile["effectiveness_band"],
        "rank_state":state,
        "reasons":reasons,
    }

def _candidate_profiles(con,c):
    rows=[dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_effectiveness_profiles
           ORDER BY family_remediation_effectiveness_profile_id""").fetchall()]
    eligible=[]
    for p in rows:
        root=_profile_root(con,p)
        if root==c["root_cause_type"]:
            eligible.append(p)
    return eligible

def rank_case(con,case_id,persist=True):
    c=_case(con,case_id)
    scored=[_score_profile(c,p) for p in _candidate_profiles(con,c)]
    # Keep the strongest historical context for each exact remediation identity.
    best={}
    for s in scored:
        key=(s["remediation_type"],s["remediation_ref"])
        prev=best.get(key)
        if prev is None or (s["conservative_score"],s["context_similarity"],s["attempt_count"]) > (
            prev["conservative_score"],prev["context_similarity"],prev["attempt_count"]):
            best[key]=s
    scored=list(best.values())
    scored.sort(key=lambda x:(
        x["rank_state"]!="AVOID",
        x["conservative_score"],
        x["context_similarity"],
        x["attempt_count"]),reverse=True)
    for i,s in enumerate(scored,1):
        s["rank_position"]=i

    if persist:
        con.execute("""DELETE FROM origin_threshold_recommendation_fallback_family_remediation_rankings
                       WHERE family_recovery_case_id=?""",(case_id,))
        for s in scored:
            con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_rankings(
              family_recovery_case_id,family_signature,historical_family_signature,
              remediation_type,remediation_ref,context_similarity,attempt_count,decisive_count,
              sustained_success_count,recurrence_failure_count,wilson_lower_bound,survival_score,
              evidence_score,recurrence_penalty,conservative_score,confidence_band,
              effectiveness_band,rank_state,rank_position,reasons_json,ranked_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (case_id,c["family_signature"],s["historical_family_signature"],
               s["remediation_type"],s["remediation_ref"],s["context_similarity"],
               s["attempt_count"],s["decisive_count"],s["sustained_success_count"],
               s["recurrence_failure_count"],s["wilson_lower_bound"],s["survival_score"],
               s["evidence_score"],s["recurrence_penalty"],s["conservative_score"],
               s["confidence_band"],s["effectiveness_band"],s["rank_state"],
               s["rank_position"],json.dumps(s["reasons"],ensure_ascii=False),_now()))
        con.commit()
        _event(con,case_id,"FAMILY_REMEDIATION_RANKED","family-ranking-engine",
               {"candidate_count":len(scored)})
        return rankings(con,case_id)
    return scored

def recommend_case(con,case_id,persist=True):
    ranked=rank_case(con,case_id,persist=persist)
    c=_case(con,case_id)
    safe=[r for r in ranked if r["rank_state"]!="AVOID"]
    preferred=[r for r in safe if r["rank_state"]=="PREFERRED"]
    top=safe[0] if safe else None
    second=safe[1] if len(safe)>1 else None
    margin=(top["conservative_score"]-second["conservative_score"]) if top and second else (
        top["conservative_score"] if top else None)

    if preferred and top and top["rank_state"]=="PREFERRED" and (
        second is None or margin>=MIN_PREFERRED_MARGIN):
        source="EFFECTIVENESS_MEMORY_SHADOW"
        status="SHADOW_PREFERRED"
        selected=top
        reasons=[
            "exact-family remediation has conservative PREFERRED evidence",
            f"score={top['conservative_score']:.3f}",
            f"margin={margin:.3f}",
            "Human Architecture Selection is required before reuse",
        ]
    elif top:
        source="EFFECTIVENESS_MEMORY_SHADOW"
        status="LOW_DATA_OR_SMALL_MARGIN"
        selected=top
        reasons=[
            "historical remediation candidates exist but evidence/margin is insufficient for preferred status",
            "deterministic/new architecture remediation remains the default",
            "ranking is shadow-only",
        ]
    else:
        source="DETERMINISTIC_FALLBACK"
        status="NO_SAFE_MEMORY"
        selected=None
        reasons=[
            "no safe historical remediation candidate is available",
            "use a new/deterministic architecture remediation",
        ]

    result={
        "policy_version":POLICY_VERSION,
        "family_recovery_case_id":case_id,
        "family_signature":c["family_signature"],
        "source":source,
        "status":status,
        "recommended_remediation_type":selected["remediation_type"] if selected else None,
        "recommended_remediation_ref":selected["remediation_ref"] if selected else None,
        "recommended_score":selected["conservative_score"] if selected else None,
        "score_margin":margin,
        "human_selection_required":bool(selected),
        "reasons":reasons,
        "rankings":ranked,
    }
    if persist:
        con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_recommendations(
          family_recovery_case_id,family_signature,selected_ranking_id,source,status,
          recommended_remediation_type,recommended_remediation_ref,recommended_score,
          score_margin,human_selection_required,reasons_json,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (case_id,c["family_signature"],
           top["family_remediation_ranking_id"] if top and "family_remediation_ranking_id" in top else None,
           source,status,result["recommended_remediation_type"],
           result["recommended_remediation_ref"],result["recommended_score"],
           margin,int(bool(selected)),json.dumps(reasons,ensure_ascii=False),_now()))
        rid=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        con.commit()
        result["family_remediation_recommendation_id"]=rid
        _event(con,case_id,"FAMILY_REMEDIATION_RECOMMENDED","family-ranking-engine",
               {"recommendation_id":rid,"source":source,"status":status,
                "remediation_type":result["recommended_remediation_type"],
                "remediation_ref":result["recommended_remediation_ref"]})
    return result

def latest_recommendation(con,case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_recommendations
      WHERE family_recovery_case_id=?
      ORDER BY family_remediation_recommendation_id DESC LIMIT 1""",(case_id,)).fetchone()
    if not r:
        return None
    x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); return x

def review_selection(con,case_id,decision,reviewer,reason,ranking_id=None):
    if decision not in ("SELECT","USE_DETERMINISTIC","HOLD","REJECT"):
        raise ValueError("invalid remediation selection decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    rec=latest_recommendation(con,case_id)
    if not rec:
        rec_result=recommend_case(con,case_id,persist=True)
        rec=latest_recommendation(con,case_id)
    selected_type=selected_ref=None
    if decision=="SELECT":
        if ranking_id is None:
            raise ValueError("ranking_id is required for SELECT")
        row=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_rankings
          WHERE family_remediation_ranking_id=? AND family_recovery_case_id=?""",
          (ranking_id,case_id)).fetchone()
        if not row:
            raise ValueError("family remediation ranking not found for recovery case")
        row=dict(row)
        if row["rank_state"]=="AVOID" or row["effectiveness_band"]=="AVOID":
            raise ValueError("AVOID remediation cannot be selected")
        selected_type=row["remediation_type"]; selected_ref=row["remediation_ref"]
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_selection_reviews(
      family_recovery_case_id,family_remediation_recommendation_id,
      family_remediation_ranking_id,decision,selected_remediation_type,
      selected_remediation_ref,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (case_id,rec["family_remediation_recommendation_id"],ranking_id,decision,
       selected_type,selected_ref,reviewer,reason,_now()))
    con.commit()
    _event(con,case_id,"FAMILY_REMEDIATION_HUMAN_SELECTION",reviewer,
           {"decision":decision,"ranking_id":ranking_id,
            "selected_remediation_type":selected_type,
            "selected_remediation_ref":selected_ref,"reason":reason})
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_selection_reviews
      WHERE family_remediation_selection_review_id=?""",(cur.lastrowid,)).fetchone())

def selection_allows(con,case_id,remediation_type,remediation_ref):
    rec=latest_recommendation(con,case_id)
    if not rec:
        return {"allowed":True,"reason":"no historical remediation recommendation exists"}
    # Only memory reuse needs explicit architecture selection. Novel remediation remains a manual path.
    historical=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_rankings
      WHERE family_recovery_case_id=? AND remediation_type=? AND remediation_ref=?
      ORDER BY family_remediation_ranking_id DESC LIMIT 1""",
      (case_id,remediation_type,remediation_ref)).fetchone()
    if not historical:
        return {"allowed":True,"reason":"new remediation is not a historical memory reuse"}
    if historical["rank_state"]=="AVOID":
        return {"allowed":False,"reason":"AVOID historical remediation cannot be reused"}
    sel=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_selection_reviews
      WHERE family_recovery_case_id=? AND decision='SELECT'
        AND selected_remediation_type=? AND selected_remediation_ref=?
      ORDER BY family_remediation_selection_review_id DESC LIMIT 1""",
      (case_id,remediation_type,remediation_ref)).fetchone()
    if not sel:
        return {"allowed":False,"reason":"Human Architecture Selection is required for historical remediation reuse"}
    return {"allowed":True,"reason":"historical remediation was explicitly selected by Human Architecture Review",
            "selection_review":dict(sel)}

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "rankings":rankings(con),
        "recommendations":recommendations(con),
        "selection_reviews":selection_reviews(con),
        "events":events(con),
    }
