import json
import math
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MIN_CANARY_RUNTIME=3
MIN_CANARY_HELPFUL=2
MIN_CANDIDATE_SCORE=0.45
MIN_SUPERSEDE_MARGIN=0.10
MIN_COMPARABLE_DECISIVE=3

def _now():
    return datetime.now(timezone.utc).isoformat()

def _wilson_lower(successes,n,z=1.96):
    if n<=0:
        return 0.0
    phat=successes/n
    denom=1+z*z/n
    center=phat+z*z/(2*n)
    adj=z*math.sqrt((phat*(1-phat)+z*z/(4*n))/n)
    return max(0.0,(center-adj)/denom)

def _score(profile):
    n=int(profile["decisive_runtime_count"] or 0)
    helpful=int(profile["helpful_count"] or 0)
    harmful=int(profile["harmful_count"] or 0)
    wilson=_wilson_lower(helpful,n)
    survival=float(profile["median_survival_days"] or 0.0)
    survival_score=min(survival/90.0,1.0)
    evidence=min(n/5.0,1.0)
    harmful_penalty=min(harmful*0.30,0.60)
    score=wilson*0.55 + survival_score*0.20 + evidence*0.25 - harmful_penalty
    return max(0.0,min(1.0,score)),wilson

def _version(con,version_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
                     WHERE algorithm_version_id=?""",(version_id,)).fetchone()
    if not r:
        raise ValueError("algorithm version not found")
    return dict(r)

def _profiles(con,version_id):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recommendation_algorithm_version_profiles
           WHERE algorithm_version_id=? ORDER BY algorithm_version_profile_id""",
        (version_id,)).fetchall()]

def _promoted_incumbent(con,root,exclude_version_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
      WHERE root_cause_type=? AND status='PROMOTED' AND algorithm_version_id<>?
      ORDER BY algorithm_version_id DESC LIMIT 1""",(root,exclude_version_id)).fetchone()
    return dict(r) if r else None

def _event(con,version_id,root,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_version_promotion_events(
      algorithm_version_id,root_cause_type,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (version_id,root,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def comparisons(con,candidate_version_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_version_supersede_comparisons"""
    params=()
    if candidate_version_id is not None:
        sql+=" WHERE candidate_algorithm_version_id=?"; params=(candidate_version_id,)
    sql+=" ORDER BY supersede_comparison_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def gates(con,algorithm_version_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_version_promotion_gates"""
    params=()
    if algorithm_version_id is not None:
        sql+=" WHERE algorithm_version_id=?"; params=(algorithm_version_id,)
    sql+=" ORDER BY version_promotion_gate_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def reviews(con,algorithm_version_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_version_promotion_reviews"""
    params=()
    if algorithm_version_id is not None:
        sql+=" WHERE algorithm_version_id=?"; params=(algorithm_version_id,)
    sql+=" ORDER BY version_promotion_review_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def events(con,algorithm_version_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_version_promotion_events"""
    params=()
    if algorithm_version_id is not None:
        sql+=" WHERE algorithm_version_id=?"; params=(algorithm_version_id,)
    sql+=" ORDER BY version_promotion_event_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def _best_candidate_profile(profiles):
    eligible=[
        p for p in profiles
        if int(p["canary_runtime_count"] or 0)>=MIN_CANARY_RUNTIME
        and int(p["helpful_count"] or 0)>=MIN_CANARY_HELPFUL
        and int(p["harmful_count"] or 0)==0
        and p["safety_band"]=="SAFE"
    ]
    if not eligible:
        return None
    return max(eligible,key=lambda p:(_score(p)[0],p["decisive_runtime_count"]))

def evaluate_gate(con,algorithm_version_id,persist=True):
    v=_version(con,algorithm_version_id)
    ps=_profiles(con,algorithm_version_id)
    reasons=[]
    if v["status"]=="FAILED":
        reasons.append("failed algorithm version cannot be promoted")
    if not ps:
        result={
            "policy_version":POLICY_VERSION,"algorithm_version_id":algorithm_version_id,
            "root_cause_type":v["root_cause_type"],"status":"NO_VERSION_PROFILE",
            "supersede_allowed":False,"reasons":["version runtime profile does not exist"]
        }
        return _persist_gate(con,result,None,None,None,None,persist)
    if any(int(p["harmful_count"] or 0)>0 for p in ps):
        reasons.append("candidate version has harmful runtime evidence")
    selected=_best_candidate_profile(ps)
    if selected is None:
        reasons.append(
            f"candidate requires Canary >= {MIN_CANARY_RUNTIME}, Helpful >= {MIN_CANARY_HELPFUL}, Harmful = 0")
    if reasons:
        result={
            "policy_version":POLICY_VERSION,"algorithm_version_id":algorithm_version_id,
            "root_cause_type":v["root_cause_type"],
            "selected_context_signature":selected["context_signature"] if selected else None,
            "candidate_score":_score(selected)[0] if selected else None,
            "status":"BLOCKED","supersede_allowed":False,"reasons":reasons
        }
        return _persist_gate(con,result,selected,None,None,None,persist)

    candidate_score,candidate_wilson=_score(selected)
    if candidate_score<MIN_CANDIDATE_SCORE:
        result={
            "policy_version":POLICY_VERSION,"algorithm_version_id":algorithm_version_id,
            "root_cause_type":v["root_cause_type"],
            "selected_context_signature":selected["context_signature"],
            "candidate_score":candidate_score,
            "status":"WARMING","supersede_allowed":False,
            "reasons":[f"candidate score {candidate_score:.3f} < {MIN_CANDIDATE_SCORE:.3f}"]
        }
        return _persist_gate(con,result,selected,None,None,None,persist)

    incumbent=_promoted_incumbent(con,v["root_cause_type"],algorithm_version_id)
    if not incumbent:
        result={
            "policy_version":POLICY_VERSION,"algorithm_version_id":algorithm_version_id,
            "root_cause_type":v["root_cause_type"],
            "selected_context_signature":selected["context_signature"],
            "incumbent_algorithm_version_id":None,
            "candidate_score":candidate_score,"incumbent_score":None,
            "score_margin":None,"status":"READY_FOR_HUMAN_PROMOTION",
            "supersede_allowed":True,
            "reasons":["candidate version is Canary-proven and no incumbent PROMOTED version exists"]
        }
        return _persist_gate(con,result,selected,None,None,None,persist)

    incumbent_profile=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_version_profiles
      WHERE algorithm_version_id=? AND context_signature=?""",
      (incumbent["algorithm_version_id"],selected["context_signature"])).fetchone()
    if not incumbent_profile:
        result={
            "policy_version":POLICY_VERSION,"algorithm_version_id":algorithm_version_id,
            "root_cause_type":v["root_cause_type"],
            "selected_context_signature":selected["context_signature"],
            "incumbent_algorithm_version_id":incumbent["algorithm_version_id"],
            "candidate_score":candidate_score,"incumbent_score":None,"score_margin":None,
            "status":"KEEP_CURRENT_VERSION","supersede_allowed":False,
            "reasons":["incumbent lacks comparable runtime evidence in candidate context"]
        }
        return _persist_gate(con,result,selected,incumbent,None,None,persist)

    incumbent_profile=dict(incumbent_profile)
    incumbent_score,incumbent_wilson=_score(incumbent_profile)
    margin=candidate_score-incumbent_score
    comp_reasons=[
        f"candidate_score={candidate_score:.3f}",
        f"incumbent_score={incumbent_score:.3f}",
        f"margin={margin:.3f}",
        f"candidate_wilson={candidate_wilson:.3f}",
        f"incumbent_wilson={incumbent_wilson:.3f}",
    ]
    incumbent_unsafe=int(incumbent_profile["harmful_count"] or 0)>0 or incumbent_profile["safety_band"]=="UNSAFE"
    candidate_n=int(selected["decisive_runtime_count"] or 0)
    incumbent_n=int(incumbent_profile["decisive_runtime_count"] or 0)

    if incumbent_unsafe:
        status="READY_FOR_SUPERSEDE_REVIEW"
        allowed=True
        comp_reasons.append("incumbent has unsafe/harmful version evidence")
    elif incumbent_n<MIN_COMPARABLE_DECISIVE:
        status="KEEP_CURRENT_VERSION"
        allowed=False
        comp_reasons.append(
            f"incumbent comparable decisive {incumbent_n}/{MIN_COMPARABLE_DECISIVE}; conservative hold")
    elif margin>=MIN_SUPERSEDE_MARGIN:
        status="READY_FOR_SUPERSEDE_REVIEW"
        allowed=True
        comp_reasons.append(
            f"candidate advantage {margin:.3f} >= {MIN_SUPERSEDE_MARGIN:.3f}")
    else:
        status="KEEP_CURRENT_VERSION"
        allowed=False
        comp_reasons.append(
            f"candidate advantage {margin:.3f} < {MIN_SUPERSEDE_MARGIN:.3f}")

    if persist:
        con.execute("""INSERT INTO origin_threshold_recommendation_version_supersede_comparisons(
          candidate_algorithm_version_id,incumbent_algorithm_version_id,root_cause_type,
          context_signature,candidate_decisive_count,incumbent_decisive_count,
          candidate_wilson_lower,incumbent_wilson_lower,candidate_median_survival_days,
          incumbent_median_survival_days,candidate_score,incumbent_score,score_margin,
          status,reasons_json,compared_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (algorithm_version_id,incumbent["algorithm_version_id"],v["root_cause_type"],
           selected["context_signature"],candidate_n,incumbent_n,candidate_wilson,
           incumbent_wilson,selected["median_survival_days"],
           incumbent_profile["median_survival_days"],candidate_score,incumbent_score,
           margin,status,json.dumps(comp_reasons,ensure_ascii=False),_now()))
        con.commit()

    result={
        "policy_version":POLICY_VERSION,"algorithm_version_id":algorithm_version_id,
        "root_cause_type":v["root_cause_type"],
        "selected_context_signature":selected["context_signature"],
        "incumbent_algorithm_version_id":incumbent["algorithm_version_id"],
        "candidate_score":candidate_score,"incumbent_score":incumbent_score,
        "score_margin":margin,"status":status,"supersede_allowed":allowed,
        "reasons":comp_reasons
    }
    return _persist_gate(con,result,selected,incumbent,incumbent_profile,margin,persist)

def _persist_gate(con,result,selected,incumbent,incumbent_profile,margin,persist):
    if not persist:
        return result
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_version_promotion_gates(
      algorithm_version_id,root_cause_type,selected_context_signature,
      incumbent_algorithm_version_id,candidate_score,incumbent_score,score_margin,
      candidate_decisive_count,candidate_canary_count,candidate_helpful_count,
      candidate_harmful_count,status,supersede_allowed,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (result["algorithm_version_id"],result["root_cause_type"],
       result.get("selected_context_signature"),
       result.get("incumbent_algorithm_version_id"),
       result.get("candidate_score"),result.get("incumbent_score"),result.get("score_margin"),
       int(selected["decisive_runtime_count"] or 0) if selected else 0,
       int(selected["canary_runtime_count"] or 0) if selected else 0,
       int(selected["helpful_count"] or 0) if selected else 0,
       int(selected["harmful_count"] or 0) if selected else 0,
       result["status"],int(bool(result.get("supersede_allowed"))),
       json.dumps(result.get("reasons") or [],ensure_ascii=False),_now()))
    result["version_promotion_gate_id"]=cur.lastrowid
    con.commit()
    return result

def human_review(con,algorithm_version_id,decision,reviewer,reason):
    if decision not in ("PROMOTE","KEEP_CURRENT","HOLD","REJECT"):
        raise ValueError("invalid version promotion review decision")
    if not reviewer or not reason:
        raise ValueError("reviewer and reason required")
    gate=evaluate_gate(con,algorithm_version_id,persist=True)
    if decision=="PROMOTE" and gate["status"] not in (
        "READY_FOR_HUMAN_PROMOTION","READY_FOR_SUPERSEDE_REVIEW"):
        raise ValueError("version promotion gate is not ready")
    con.execute("""INSERT INTO origin_threshold_recommendation_version_promotion_reviews(
      algorithm_version_id,version_promotion_gate_id,decision,reviewer,reason,
      incumbent_algorithm_version_id,reviewed_at)
      VALUES(?,?,?,?,?,?,?)""",
      (algorithm_version_id,gate["version_promotion_gate_id"],decision,reviewer,
       reason,gate.get("incumbent_algorithm_version_id"),_now()))
    con.commit()
    _event(con,algorithm_version_id,gate["root_cause_type"],"VERSION_PROMOTION_REVIEW",
           reviewer,{"decision":decision,"reason":reason,"gate_status":gate["status"]})
    return {"gate":gate,"decision":decision}

def latest_approved_review(con,algorithm_version_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_version_promotion_reviews
      WHERE algorithm_version_id=? AND decision='PROMOTE'
      ORDER BY version_promotion_review_id DESC LIMIT 1""",(algorithm_version_id,)).fetchone()
    return dict(r) if r else None

def promotion_ready(con,algorithm_version_id):
    gate=evaluate_gate(con,algorithm_version_id,persist=True)
    review=latest_approved_review(con,algorithm_version_id)
    ready=gate["status"] in ("READY_FOR_HUMAN_PROMOTION","READY_FOR_SUPERSEDE_REVIEW") and bool(review)
    return {"ready":ready,"gate":gate,"review":review}

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "gates":gates(con),
        "comparisons":comparisons(con),
        "reviews":reviews(con),
        "events":events(con),
    }
