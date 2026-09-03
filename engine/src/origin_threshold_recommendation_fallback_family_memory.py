import json
import statistics
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
SUSTAINED_MIN_OBSERVATIONS=20
SUSTAINED_MIN_DAYS=30

def _now():
    return datetime.now(timezone.utc).isoformat()

def _parse(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts)

def _event(con,outcome_id,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_generation_events(
      family_generation_outcome_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (outcome_id,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def outcomes(con,family_signature=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes"""
    params=()
    if family_signature:
        sql+=" WHERE family_signature=?"; params=(family_signature,)
    sql+=" ORDER BY family_generation_outcome_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def outcome_for_case(con,case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE family_recovery_case_id=?""",(case_id,)).fetchone()
    return dict(r) if r else None

def _latest_effective_remediation(con,case_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_remediations
      WHERE family_recovery_case_id=? AND status='EFFECTIVE'
      ORDER BY family_recovery_remediation_id DESC LIMIT 1""",(case_id,)).fetchone()
    return dict(r) if r else None

def register_stabilized_generation(con,case_id):
    existing=outcome_for_case(con,case_id)
    if existing:
        return existing
    c=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_recovery_cases
      WHERE family_recovery_case_id=?""",(case_id,)).fetchone()
    if not c:
        raise ValueError("family recovery case not found")
    c=dict(c)
    if c["status"]!="STABLE" or not c["stabilized_at"]:
        raise ValueError("family recovery case is not stabilized")
    if not c["candidate_algorithm_version_id"]:
        raise ValueError("stabilized family recovery lacks candidate algorithm version")
    rem=_latest_effective_remediation(con,case_id)
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_generation_outcomes(
      family_recovery_case_id,fallback_family_profile_id,root_cause_type,family_signature,
      candidate_algorithm_version_id,family_recovery_remediation_id,remediation_type,
      remediation_ref,status,stabilized_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (case_id,c["fallback_family_profile_id"],c["root_cause_type"],c["family_signature"],
       c["candidate_algorithm_version_id"],
       rem["family_recovery_remediation_id"] if rem else None,
       rem["remediation_type"] if rem else "UNRESOLVED",
       rem["remediation_ref"] if rem else "UNRESOLVED",
       "ACTIVE",c["stabilized_at"]))
    con.commit()
    out=dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE family_generation_outcome_id=?""",(cur.lastrowid,)).fetchone())
    _event(con,out["family_generation_outcome_id"],"FAMILY_GENERATION_ACTIVE",
           "family-generation-memory",
           {"family_recovery_case_id":case_id,
            "candidate_algorithm_version_id":c["candidate_algorithm_version_id"],
            "remediation_type":out["remediation_type"],
            "remediation_ref":out["remediation_ref"]})
    refresh_effectiveness(con,out["family_signature"],out["remediation_type"],out["remediation_ref"])
    from .origin_threshold_recommendation_fallback_family_recommendation_outcome import register_generation
    register_generation(con,out["family_generation_outcome_id"])
    return out

def active_outcome_for_root(con,root_cause_type):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE root_cause_type=? AND status='ACTIVE'
      ORDER BY family_generation_outcome_id DESC LIMIT 1""",(root_cause_type,)).fetchone()
    return dict(r) if r else None

def observe_runtime(con,root_cause_type,challenge_id,verdict,observed_at=None):
    out=active_outcome_for_root(con,root_cause_type)
    if not out:
        return {"handled":False}
    alg=con.execute("""SELECT algorithm_version_id FROM origin_threshold_recommendation_algorithm_lineage
      WHERE entity_type='CHALLENGE' AND entity_id=? AND relation_type='EVALUATED_BY'
      ORDER BY algorithm_lineage_id DESC LIMIT 1""",(challenge_id,)).fetchone()
    if not alg or alg["algorithm_version_id"]!=out["candidate_algorithm_version_id"]:
        return {"handled":False,"outcome":out}
    ts=observed_at or _now()
    harmful=verdict=="RECOMMENDATION_HARMFUL"
    healthy=not harmful
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_generation_outcomes
      SET first_observed_at=COALESCE(first_observed_at,?),last_observed_at=?,
          observation_count=observation_count+1,
          healthy_observation_count=healthy_observation_count+?,
          harmful_observation_count=harmful_observation_count+?
      WHERE family_generation_outcome_id=?""",
      (ts,ts,int(healthy),int(harmful),out["family_generation_outcome_id"]))
    con.commit()
    _event(con,out["family_generation_outcome_id"],"FAMILY_GENERATION_RUNTIME_OBSERVED",
           "family-generation-memory",
           {"challenge_id":challenge_id,"verdict":verdict,"observed_at":ts})
    refreshed=dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE family_generation_outcome_id=?""",(out["family_generation_outcome_id"],)).fetchone())
    return {"handled":True,"outcome":refreshed}

def evaluate_sustained(con,family_generation_outcome_id,now=None):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE family_generation_outcome_id=?""",(family_generation_outcome_id,)).fetchone()
    if not r:
        raise ValueError("family generation outcome not found")
    out=dict(r)
    if out["status"]!="ACTIVE":
        return out
    now_dt=_parse(now) if isinstance(now,str) else (now or datetime.now(timezone.utc))
    stabilized=_parse(out["stabilized_at"])
    days=max(0.0,(now_dt-stabilized).total_seconds()/86400.0)
    if (out["observation_count"]>=SUSTAINED_MIN_OBSERVATIONS
        and out["harmful_observation_count"]==0
        and days>=SUSTAINED_MIN_DAYS):
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_generation_outcomes
          SET status='SUSTAINED_SUCCESS',finalized_at=? WHERE family_generation_outcome_id=?""",
          (_now(),family_generation_outcome_id))
        con.commit()
        _event(con,family_generation_outcome_id,"FAMILY_GENERATION_SUSTAINED_SUCCESS",
               "family-generation-memory",
               {"observation_count":out["observation_count"],"days":days})
        out=dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
          WHERE family_generation_outcome_id=?""",(family_generation_outcome_id,)).fetchone())
        refresh_effectiveness(con,out["family_signature"],out["remediation_type"],out["remediation_ref"])
        from .origin_threshold_recommendation_fallback_family_recommendation_outcome import resolve_generation
        resolve_generation(con,family_generation_outcome_id,"SUSTAINED_SUCCESS")
    return out

def mark_recurrence(con,fallback_family_profile_id,opened_at=None):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE fallback_family_profile_id=? AND status IN ('ACTIVE','SUSTAINED_SUCCESS')
      ORDER BY family_generation_outcome_id DESC LIMIT 1""",(fallback_family_profile_id,)).fetchone()
    if not r:
        return None
    out=dict(r)
    when=opened_at or _now()
    stabilized=_parse(out["stabilized_at"])
    opened=_parse(when)
    days=max(0.0,(opened-stabilized).total_seconds()/86400.0)
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_generation_outcomes
      SET status='RECURRENCE_FAILED',next_circuit_opened_at=?,days_to_family_recurrence=?,
          finalized_at=? WHERE family_generation_outcome_id=?""",
      (when,days,_now(),out["family_generation_outcome_id"]))
    con.commit()
    _event(con,out["family_generation_outcome_id"],"FAMILY_GENERATION_RECURRENCE_FAILED",
           "family-generation-memory",
           {"next_circuit_opened_at":when,"days_to_family_recurrence":days})
    out=dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE family_generation_outcome_id=?""",(out["family_generation_outcome_id"],)).fetchone())
    refresh_effectiveness(con,out["family_signature"],out["remediation_type"],out["remediation_ref"])
    from .origin_threshold_recommendation_fallback_family_recommendation_outcome import resolve_generation
    resolve_generation(con,out["family_generation_outcome_id"],"RECURRENCE_FAILED")
    return out

def refresh_effectiveness(con,family_signature,remediation_type,remediation_ref):
    rows=[dict(r) for r in con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_outcomes
      WHERE family_signature=? AND remediation_type=? AND remediation_ref=?""",
      (family_signature,remediation_type,remediation_ref)).fetchall()]
    attempts=len(rows)
    active=sum(r["status"]=="ACTIVE" for r in rows)
    sustained=sum(r["status"]=="SUSTAINED_SUCCESS" for r in rows)
    failed=sum(r["status"]=="RECURRENCE_FAILED" for r in rows)
    decisive=sustained+failed
    success_rate=(sustained/decisive) if decisive else None
    recurrence_days=[float(r["days_to_family_recurrence"]) for r in rows
                     if r["status"]=="RECURRENCE_FAILED" and r["days_to_family_recurrence"] is not None]
    avg_days=(sum(recurrence_days)/len(recurrence_days)) if recurrence_days else None
    if attempts<2 or decisive<1:
        confidence="LOW_DATA"
    elif attempts<4:
        confidence="EMERGING"
    else:
        confidence="ESTABLISHED"
    if failed>=2:
        band="AVOID"
    elif sustained>=2 and failed==0:
        band="PREFERRED"
    elif failed>=1:
        band="WATCH"
    else:
        band="LEARNING"
    reasons=[
        f"attempts={attempts}",f"active={active}",f"sustained={sustained}",
        f"recurrence_failures={failed}",f"confidence={confidence}",f"band={band}"
    ]
    existing=con.execute("""SELECT family_remediation_effectiveness_profile_id
      FROM origin_threshold_recommendation_fallback_family_remediation_effectiveness_profiles
      WHERE family_signature=? AND remediation_type=? AND remediation_ref=?""",
      (family_signature,remediation_type,remediation_ref)).fetchone()
    vals=(attempts,active,sustained,failed,success_rate,avg_days,confidence,band,
          json.dumps(reasons,ensure_ascii=False),_now())
    if existing:
        con.execute("""UPDATE origin_threshold_recommendation_fallback_family_remediation_effectiveness_profiles
          SET attempt_count=?,active_count=?,sustained_success_count=?,
              recurrence_failure_count=?,success_rate=?,avg_days_to_family_recurrence=?,
              confidence_band=?,effectiveness_band=?,reasons_json=?,updated_at=?
          WHERE family_remediation_effectiveness_profile_id=?""",
          vals+(existing["family_remediation_effectiveness_profile_id"],))
    else:
        con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_effectiveness_profiles(
          family_signature,remediation_type,remediation_ref,attempt_count,active_count,
          sustained_success_count,recurrence_failure_count,success_rate,
          avg_days_to_family_recurrence,confidence_band,effectiveness_band,reasons_json,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (family_signature,remediation_type,remediation_ref)+vals)
    con.commit()
    return effectiveness_profile(con,family_signature,remediation_type,remediation_ref)

def effectiveness_profile(con,family_signature,remediation_type,remediation_ref):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_effectiveness_profiles
      WHERE family_signature=? AND remediation_type=? AND remediation_ref=?""",
      (family_signature,remediation_type,remediation_ref)).fetchone()
    if not r: return None
    x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); return x

def effectiveness_profiles(con):
    out=[]
    for r in con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_family_remediation_effectiveness_profiles
      ORDER BY family_remediation_effectiveness_profile_id""").fetchall():
        x=dict(r); x["reasons"]=json.loads(x.pop("reasons_json")); out.append(x)
    return out

def remediation_allowed(con,family_signature,remediation_type,remediation_ref):
    p=effectiveness_profile(con,family_signature,remediation_type,remediation_ref)
    if p and p["effectiveness_band"]=="AVOID":
        return {"allowed":False,"reason":"same family remediation has repeated recurrence failures","profile":p}
    return {"allowed":True,"reason":"remediation is not blocked by family effectiveness memory","profile":p}

def events(con,outcome_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_family_generation_events"""
    params=()
    if outcome_id is not None:
        sql+=" WHERE family_generation_outcome_id=?"; params=(outcome_id,)
    sql+=" ORDER BY family_generation_event_id"
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
