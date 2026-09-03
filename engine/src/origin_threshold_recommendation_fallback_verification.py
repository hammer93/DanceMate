import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"
MAX_OBSERVATIONS=5
MIN_HELPFUL_FOR_STABLE=4
MAX_AUTOMATIC_FALLBACKS_PER_PAIR=1

def _now():
    return datetime.now(timezone.utc).isoformat()

def pair_signature(failing_algorithm_version_id,fallback_algorithm_version_id):
    return f"{int(failing_algorithm_version_id)}->{int(fallback_algorithm_version_id)}"

def _event(con,generation_id,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_verification_events(
      fallback_verification_generation_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (generation_id,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def pair_profiles(con):
    return [dict(r) for r in con.execute(
        """SELECT * FROM origin_threshold_recommendation_fallback_pair_profiles
           ORDER BY fallback_pair_profile_id""").fetchall()]

def pair_profile(con,failing_id,fallback_id):
    sig=pair_signature(failing_id,fallback_id)
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_pair_profiles
                     WHERE pair_signature=?""",(sig,)).fetchone()
    return dict(r) if r else None

def automatic_fallback_allowed(con,failing_id,fallback_id):
    p=pair_profile(con,failing_id,fallback_id)
    if not p:
        return {"allowed":True,"reason":"pair has no previous automatic fallback"}
    if p["anti_ping_pong_blocked"]:
        return {"allowed":False,"reason":"version pair is anti-ping-pong blocked","profile":p}
    if p["executed_fallback_count"]>=MAX_AUTOMATIC_FALLBACKS_PER_PAIR:
        return {"allowed":False,"reason":"automatic fallback limit reached for version pair","profile":p}
    return {"allowed":True,"reason":"pair remains within automatic fallback limit","profile":p}

def _refresh_pair(con,root,failing_id,fallback_id,*,executed_delta=0,failed_delta=0,stable_delta=0):
    sig=pair_signature(failing_id,fallback_id)
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_pair_profiles
                     WHERE pair_signature=?""",(sig,)).fetchone()
    if not r:
        executed=executed_delta
        failed=failed_delta
        stable=stable_delta
        blocked=int(executed>=MAX_AUTOMATIC_FALLBACKS_PER_PAIR or failed>0)
        con.execute("""INSERT INTO origin_threshold_recommendation_fallback_pair_profiles(
          root_cause_type,pair_signature,failing_algorithm_version_id,fallback_algorithm_version_id,
          executed_fallback_count,failed_verification_count,stable_verification_count,
          anti_ping_pong_blocked,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (root,sig,failing_id,fallback_id,executed,failed,stable,blocked,_now()))
    else:
        executed=r["executed_fallback_count"]+executed_delta
        failed=r["failed_verification_count"]+failed_delta
        stable=r["stable_verification_count"]+stable_delta
        blocked=int(executed>=MAX_AUTOMATIC_FALLBACKS_PER_PAIR or failed>0)
        con.execute("""UPDATE origin_threshold_recommendation_fallback_pair_profiles
          SET executed_fallback_count=?,failed_verification_count=?,
              stable_verification_count=?,anti_ping_pong_blocked=?,updated_at=?
          WHERE pair_signature=?""",
          (executed,failed,stable,blocked,_now(),sig))
    con.commit()
    return pair_profile(con,failing_id,fallback_id)

def open_generation(con,version_fallback_id,root_cause_type,failing_id,fallback_id):
    existing=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_verification_generations
      WHERE version_fallback_id=?""",(version_fallback_id,)).fetchone()
    if existing:
        return dict(existing)
    sig=pair_signature(failing_id,fallback_id)
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_verification_generations(
      version_fallback_id,root_cause_type,failing_algorithm_version_id,
      fallback_algorithm_version_id,pair_signature,status,max_observations,opened_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (version_fallback_id,root_cause_type,failing_id,fallback_id,sig,
       "ACTIVE",MAX_OBSERVATIONS,_now()))
    con.commit()
    _refresh_pair(con,root_cause_type,failing_id,fallback_id,executed_delta=1)
    _event(con,cur.lastrowid,"FALLBACK_VERIFICATION_OPENED","fallback-verification-engine",
           {"pair_signature":sig,"max_observations":MAX_OBSERVATIONS})
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_verification_generations
                              WHERE fallback_verification_generation_id=?""",(cur.lastrowid,)).fetchone())

def generations(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_verification_generations"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY fallback_verification_generation_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def active_generation(con,root_cause_type):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_verification_generations
      WHERE root_cause_type=? AND status='ACTIVE'
      ORDER BY fallback_verification_generation_id DESC LIMIT 1""",(root_cause_type,)).fetchone()
    return dict(r) if r else None

def observe(con,root_cause_type,challenge_id,verdict):
    g=active_generation(con,root_cause_type)
    if not g:
        return {"handled":False}
    # Only verify runtime from the currently restored fallback algorithm.
    alg=con.execute("""SELECT l.algorithm_version_id FROM origin_threshold_recommendation_algorithm_lineage l
      WHERE l.entity_type='CHALLENGE' AND l.entity_id=? AND l.relation_type='EVALUATED_BY'
      ORDER BY l.algorithm_lineage_id DESC LIMIT 1""",(challenge_id,)).fetchone()
    if not alg or alg["algorithm_version_id"]!=g["fallback_algorithm_version_id"]:
        return {"handled":False,"generation":g}
    if verdict not in ("RECOMMENDATION_HELPFUL","RECOMMENDATION_HARMFUL",
                       "RUNTIME_SUCCESS_SHADOW_MIXED","RUNTIME_FAILURE_INCONCLUSIVE","NEUTRAL"):
        return {"handled":False,"generation":g}
    existing=con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_verification_observations
      WHERE fallback_verification_generation_id=? AND challenge_id=?""",
      (g["fallback_verification_generation_id"],challenge_id)).fetchone()
    if existing:
        return {"handled":True,"duplicate":True,"generation":g}

    normalized=("HELPFUL" if verdict=="RECOMMENDATION_HELPFUL"
                else "HARMFUL" if verdict=="RECOMMENDATION_HARMFUL"
                else "NEUTRAL")
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_verification_observations(
      fallback_verification_generation_id,challenge_id,verdict,observed_at)
      VALUES(?,?,?,?)""",(g["fallback_verification_generation_id"],challenge_id,normalized,_now()))
    col={"HELPFUL":"helpful_count","HARMFUL":"harmful_count","NEUTRAL":"neutral_count"}[normalized]
    con.execute(f"""UPDATE origin_threshold_recommendation_fallback_verification_generations
      SET observation_count=observation_count+1,{col}={col}+1
      WHERE fallback_verification_generation_id=?""",(g["fallback_verification_generation_id"],))
    con.commit()
    g=dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_verification_generations
      WHERE fallback_verification_generation_id=?""",(g["fallback_verification_generation_id"],)).fetchone())

    if g["harmful_count"]>0:
        status="FAILED"
        force_baseline=True
        con.execute("""UPDATE origin_threshold_recommendation_fallback_verification_generations
          SET status='FAILED',completed_at=? WHERE fallback_verification_generation_id=?""",
          (_now(),g["fallback_verification_generation_id"]))
        con.commit()
        _refresh_pair(con,root_cause_type,g["failing_algorithm_version_id"],
                      g["fallback_algorithm_version_id"],failed_delta=1)
        _event(con,g["fallback_verification_generation_id"],"FALLBACK_VERIFICATION_FAILED",
               "fallback-verification-engine",{"challenge_id":challenge_id,"verdict":verdict})
        from .origin_threshold_recommendation_fallback_family import record_verification
        record_verification(con,root_cause_type,g["failing_algorithm_version_id"],
                            g["fallback_algorithm_version_id"],"FAILED")
    elif g["observation_count"]>=g["max_observations"]:
        force_baseline=False
        if g["helpful_count"]>=MIN_HELPFUL_FOR_STABLE:
            status="STABLE"
            _refresh_pair(con,root_cause_type,g["failing_algorithm_version_id"],
                          g["fallback_algorithm_version_id"],stable_delta=1)
        else:
            status="WATCH"
        con.execute("""UPDATE origin_threshold_recommendation_fallback_verification_generations
          SET status=?,completed_at=? WHERE fallback_verification_generation_id=?""",
          (status,_now(),g["fallback_verification_generation_id"]))
        con.commit()
        _event(con,g["fallback_verification_generation_id"],
               "FALLBACK_VERIFICATION_"+status,
               "fallback-verification-engine",
               {"helpful":g["helpful_count"],"neutral":g["neutral_count"]})
        from .origin_threshold_recommendation_fallback_family import record_verification
        record_verification(con,root_cause_type,g["failing_algorithm_version_id"],
                            g["fallback_algorithm_version_id"],status)
    else:
        status="ACTIVE"
        force_baseline=False

    latest=dict(con.execute("""SELECT * FROM origin_threshold_recommendation_fallback_verification_generations
      WHERE fallback_verification_generation_id=?""",(g["fallback_verification_generation_id"],)).fetchone())
    return {"handled":True,"status":status,"force_baseline":force_baseline,
            "generation":latest}

def observations(con,generation_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_verification_observations"""
    params=()
    if generation_id is not None:
        sql+=" WHERE fallback_verification_generation_id=?"; params=(generation_id,)
    sql+=" ORDER BY fallback_verification_observation_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def events(con,generation_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_fallback_verification_events"""
    params=()
    if generation_id is not None:
        sql+=" WHERE fallback_verification_generation_id=?"; params=(generation_id,)
    sql+=" ORDER BY fallback_verification_event_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "generations":generations(con),
        "observations":observations(con),
        "pair_profiles":pair_profiles(con),
        "events":events(con),
    }
