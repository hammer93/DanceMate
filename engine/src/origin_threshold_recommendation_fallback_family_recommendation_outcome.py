import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _event(con,outcome_id,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recommendation_outcome_events(
      family_recommendation_outcome_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (outcome_id,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def outcomes(con,family_signature=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_recommendation_outcomes"""
    params=()
    if family_signature:
        sql+=" WHERE family_signature=?"; params=(family_signature,)
    sql+=" ORDER BY family_recommendation_outcome_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def outcome_for_generation(con,generation_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recommendation_outcomes
      WHERE family_generation_outcome_id=?""",(generation_id,)).fetchone()
    if not r: return None
    x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); return x

def _latest_recommendation(con,case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_recommendations
      WHERE family_recovery_case_id=? ORDER BY family_remediation_recommendation_id DESC LIMIT 1""",
      (case_id,)).fetchone()
    return dict(r) if r else None

def _latest_selection(con,case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_selection_reviews
      WHERE family_recovery_case_id=? ORDER BY family_remediation_selection_review_id DESC LIMIT 1""",
      (case_id,)).fetchone()
    return dict(r) if r else None

def _ranking_score(con,case_id,rem_type,rem_ref):
    if not rem_type or not rem_ref:
        return None
    r=con.execute("""SELECT conservative_score FROM origin_threshold_recommendation_fallback_family_remediation_rankings
      WHERE family_recovery_case_id=? AND remediation_type=? AND remediation_ref=?
      ORDER BY family_remediation_ranking_id DESC LIMIT 1""",
      (case_id,rem_type,rem_ref)).fetchone()
    return float(r["conservative_score"]) if r else None

def register_generation(con,generation_id):
    existing=outcome_for_generation(con,generation_id)
    if existing:
        return existing
    g=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE family_generation_outcome_id=?""",(generation_id,)).fetchone()
    if not g:
        raise ValueError("family generation outcome not found")
    g=dict(g)
    rec=_latest_recommendation(con,g["family_recovery_case_id"])
    sel=_latest_selection(con,g["family_recovery_case_id"])
    recommended_type=rec["recommended_remediation_type"] if rec else None
    recommended_ref=rec["recommended_remediation_ref"] if rec else None
    recommended_score=float(rec["recommended_score"]) if rec and rec["recommended_score"] is not None else None
    selected_type=sel["selected_remediation_type"] if sel else None
    selected_ref=sel["selected_remediation_ref"] if sel else None

    # If selection audit is absent, the actual EFFECTIVE remediation used by the generation
    # still becomes the selected/implemented path, but acceptance remains false.
    if not selected_type:
        selected_type=g["remediation_type"]
        selected_ref=g["remediation_ref"]
    selected_score=_ranking_score(con,g["family_recovery_case_id"],selected_type,selected_ref)

    accepted=bool(recommended_type and recommended_ref
                  and selected_type==recommended_type and selected_ref==recommended_ref)
    override=bool(rec and recommended_ref and selected_ref and selected_ref!=recommended_ref)
    reasons=[
        "generation stabilized; runtime recommendation outcome is pending",
        f"recommendation_accepted={accepted}",
        f"human_override={override}",
    ]
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recommendation_outcomes(
      family_recovery_case_id,family_signature,family_remediation_recommendation_id,
      family_remediation_selection_review_id,family_generation_outcome_id,
      recommended_remediation_type,recommended_remediation_ref,recommended_score,
      selected_remediation_type,selected_remediation_ref,selected_score,
      recommendation_accepted,human_override,generation_status,outcome_class,
      selection_regret_score,reasons_json,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (g["family_recovery_case_id"],g["family_signature"],
       rec["family_remediation_recommendation_id"] if rec else None,
       sel["family_remediation_selection_review_id"] if sel else None,
       generation_id,recommended_type,recommended_ref,recommended_score,
       selected_type,selected_ref,selected_score,
       int(accepted),int(override),g["status"],"STABILIZED_PENDING",
       0.0,json.dumps(reasons,ensure_ascii=False),_now(),_now()))
    con.commit()
    oid=cur.lastrowid
    _event(con,oid,"RECOMMENDATION_OUTCOME_REGISTERED","recommendation-outcome-engine",
           {"family_generation_outcome_id":generation_id,
            "recommendation_accepted":accepted,"human_override":override})
    refresh_profile(con,g["family_signature"])
    return outcome_for_generation(con,generation_id)

def resolve_generation(con,generation_id,generation_status):
    out=outcome_for_generation(con,generation_id)
    if not out:
        out=register_generation(con,generation_id)
    if generation_status not in ("SUSTAINED_SUCCESS","RECURRENCE_FAILED"):
        return out

    accepted=bool(out["recommendation_accepted"])
    override=bool(out["human_override"])
    success=generation_status=="SUSTAINED_SUCCESS"
    if accepted and success:
        outcome_class="RECOMMENDATION_HELPFUL"
    elif accepted and not success:
        outcome_class="RECOMMENDATION_HARMFUL"
    elif override and success:
        outcome_class="HUMAN_OVERRIDE_SUCCESS"
    elif override and not success:
        outcome_class="HUMAN_OVERRIDE_FAILURE"
    elif success:
        outcome_class="MANUAL_SELECTION_SUCCESS"
    else:
        outcome_class="MANUAL_SELECTION_FAILURE"

    regret=0.0
    if not success and out["recommended_score"] is not None and out["selected_score"] is not None:
        regret=max(0.0,float(out["recommended_score"])-float(out["selected_score"]))

    reasons=[
        f"generation_status={generation_status}",
        f"outcome_class={outcome_class}",
        f"selection_regret_score={regret:.3f}",
    ]
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recommendation_outcomes
      SET generation_status=?,outcome_class=?,selection_regret_score=?,
          resolved_at=?,reasons_json=?,updated_at=?
      WHERE family_recommendation_outcome_id=?""",
      (generation_status,outcome_class,regret,_now(),
       json.dumps(reasons,ensure_ascii=False),_now(),
       out["family_recommendation_outcome_id"]))
    con.commit()
    _event(con,out["family_recommendation_outcome_id"],"RECOMMENDATION_OUTCOME_RESOLVED",
           "recommendation-outcome-engine",
           {"generation_status":generation_status,"outcome_class":outcome_class,
            "selection_regret_score":regret})
    refresh_profile(con,out["family_signature"])
    return outcome_for_generation(con,generation_id)

def refresh_profile(con,family_signature):
    rows=outcomes(con,family_signature)
    recommendation_count=sum(1 for r in rows if r["family_remediation_recommendation_id"] is not None)
    human_selection_count=sum(1 for r in rows if r["family_remediation_selection_review_id"] is not None)
    acceptance=sum(int(r["recommendation_accepted"]) for r in rows)
    overrides=sum(int(r["human_override"]) for r in rows)
    resolved=[r for r in rows if r["generation_status"] in ("SUSTAINED_SUCCESS","RECURRENCE_FAILED")]
    helpful=sum(r["outcome_class"]=="RECOMMENDATION_HELPFUL" for r in resolved)
    harmful=sum(r["outcome_class"]=="RECOMMENDATION_HARMFUL" for r in resolved)
    override_success=sum(r["outcome_class"]=="HUMAN_OVERRIDE_SUCCESS" for r in resolved)
    override_failure=sum(r["outcome_class"]=="HUMAN_OVERRIDE_FAILURE" for r in resolved)
    acceptance_rate=(acceptance/recommendation_count) if recommendation_count else None
    rec_decisive=helpful+harmful
    helpful_rate=(helpful/rec_decisive) if rec_decisive else None
    override_decisive=override_success+override_failure
    override_rate=(override_success/override_decisive) if override_decisive else None
    regrets=[float(r["selection_regret_score"] or 0.0) for r in resolved]
    avg_regret=(sum(regrets)/len(regrets)) if regrets else 0.0

    if len(resolved)<3:
        calibration="LOW_DATA"
    elif harmful==0 and helpful>=2 and avg_regret<=0.05:
        calibration="WELL_CALIBRATED"
    elif harmful>=2 or avg_regret>=0.10:
        calibration="MISALIGNED"
    else:
        calibration="LEARNING"

    reasons=[
        f"recommendations={recommendation_count}",
        f"acceptance={acceptance}",
        f"overrides={overrides}",
        f"resolved={len(resolved)}",
        f"recommendation_helpful={helpful}",
        f"recommendation_harmful={harmful}",
        f"override_success={override_success}",
        f"override_failure={override_failure}",
        f"avg_selection_regret={avg_regret:.3f}",
        f"calibration={calibration}",
    ]
    existing=con.execute("""SELECT family_recommendation_effectiveness_profile_id
      FROM origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles
      WHERE family_signature=?""",(family_signature,)).fetchone()
    vals=(recommendation_count,human_selection_count,acceptance,overrides,len(resolved),
          helpful,harmful,override_success,override_failure,acceptance_rate,helpful_rate,
          override_rate,avg_regret,calibration,json.dumps(reasons,ensure_ascii=False),_now())
    if existing:
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles
          SET recommendation_count=?,human_selection_count=?,acceptance_count=?,override_count=?,
              resolved_count=?,recommendation_helpful_count=?,recommendation_harmful_count=?,
              override_success_count=?,override_failure_count=?,acceptance_rate=?,
              recommendation_helpful_rate=?,override_success_rate=?,avg_selection_regret=?,
              calibration_band=?,reasons_json=?,updated_at=?
          WHERE family_recommendation_effectiveness_profile_id=?""",
          vals+(existing["family_recommendation_effectiveness_profile_id"],))
    else:
        con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles(
          family_signature,recommendation_count,human_selection_count,acceptance_count,override_count,
          resolved_count,recommendation_helpful_count,recommendation_harmful_count,
          override_success_count,override_failure_count,acceptance_rate,recommendation_helpful_rate,
          override_success_rate,avg_selection_regret,calibration_band,reasons_json,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(family_signature,)+vals)
    con.commit()
    return effectiveness_profile(con,family_signature)

def effectiveness_profile(con,family_signature):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles
      WHERE family_signature=?""",(family_signature,)).fetchone()
    if not r: return None
    x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); return x

def effectiveness_profiles(con):
    out=[]
    for r in con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles
      ORDER BY family_recommendation_effectiveness_profile_id""").fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def events(con,outcome_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_recommendation_outcome_events"""
    params=()
    if outcome_id is not None:
        sql+=" WHERE family_recommendation_outcome_id=?"; params=(outcome_id,)
    sql+=" ORDER BY family_recommendation_outcome_event_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "outcomes":outcomes(con),
        "effectiveness_profiles":effectiveness_profiles(con),
        "events":events(con),
    }
