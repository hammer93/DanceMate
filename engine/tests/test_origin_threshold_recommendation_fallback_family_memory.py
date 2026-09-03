from datetime import datetime, timezone, timedelta
import pytest

from src.database import init_db
from src.origin_threshold_recommendation_versioning import register_version
from src.origin_threshold_recommendation_challenge import create_challenge
from src.origin_threshold_recommendation_fallback_family_memory import (
    register_stabilized_generation,outcomes,observe_runtime,evaluate_sustained,
    mark_recurrence,refresh_effectiveness,effectiveness_profiles,
    remediation_allowed,status
)
from src.origin_threshold_recommendation_fallback_family_recovery import (
    add_remediation,review_remediation
)

ROOT="SOURCE_LOCAL_RECURRENCE"
CTX="SOURCE|SRC-A|FACEBOOK|RULE|*|ALT0"

def _rec():
    return {
        "selected_steps":["DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"],
        "source":"CONTEXT_COMPARATIVE_RANKING",
        "comparative_score":.8,
        "context_signature":CTX
    }

def _setup_stable(con,case_no=1,rem_ref="FAM-71-A",rem_type="FAMILY_ARCHITECTURE_FIX"):
    rootv=register_version(con,ROOT,f"root-{case_no}","eng",
                           code_ref=f"root-{case_no}",config_ref=f"root-{case_no}",
                           status="SUPERSEDED")
    cand=register_version(con,ROOT,f"cand-{case_no}","eng",
                          parent_algorithm_version_id=rootv["algorithm_version_id"],
                          code_ref=f"cand-{case_no}",config_ref=f"cand-{case_no}",
                          status="PROMOTED")
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_profiles(
      root_cause_type,family_root_algorithm_version_id,fallback_target_algorithm_version_id,
      family_signature,executed_fallback_count,distinct_failing_version_count,
      stable_verification_count,watch_verification_count,failed_verification_count,
      circuit_state,architecture_review_required,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ROOT,rootv["algorithm_version_id"],rootv["algorithm_version_id"],
       f"{rootv['algorithm_version_id']}=>{rootv['algorithm_version_id']}",
       0,0,1,0,0,"CLOSED",0,'[]',"2026-09-03T00:00:00+00:00"))
    pid=cur.lastrowid
    opened="2026-08-01T00:00:00+00:00"
    stabilized="2026-08-02T00:00:00+00:00"
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_cases(
      fallback_family_profile_id,root_cause_type,family_signature,recovery_number,status,
      candidate_algorithm_version_id,canary_max_fallbacks,canary_used_fallbacks,
      opened_at,ready_at,rearmed_at,stabilized_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (pid,ROOT,f"{rootv['algorithm_version_id']}=>{rootv['algorithm_version_id']}",
       case_no,"STABLE",cand["algorithm_version_id"],1,1,
       opened,opened,opened,stabilized))
    case_id=cur.lastrowid
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_remediations(
      family_recovery_case_id,remediation_type,remediation_ref,status,submitted_by,
      notes,submitted_at,reviewed_by,reviewed_at,review_reason)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (case_id,rem_type,rem_ref,"EFFECTIVE","eng","fix",opened,
       "chief",opened,"verified"))
    rem_id=cur.lastrowid
    con.commit()
    out=register_stabilized_generation(con,case_id)
    return {
        "root":rootv,"candidate":cand,"profile_id":pid,"case_id":case_id,
        "remediation_id":rem_id,"outcome":out
    }

def _challenge(con,scope):
    return create_challenge(con,scope,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])

def test_stable_case_registers_active_generation(tmp_path):
    con=init_db(tmp_path/"active.sqlite3")
    x=_setup_stable(con)
    assert x["outcome"]["status"]=="ACTIVE"
    assert x["outcome"]["family_recovery_case_id"]==x["case_id"]
    con.close()

def test_generation_registration_is_idempotent(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3")
    x=_setup_stable(con)
    y=register_stabilized_generation(con,x["case_id"])
    assert y["family_generation_outcome_id"]==x["outcome"]["family_generation_outcome_id"]
    assert len(outcomes(con))==1
    con.close()

def test_generation_links_effective_remediation(tmp_path):
    con=init_db(tmp_path/"rem.sqlite3")
    x=_setup_stable(con,rem_ref="ARCH-71")
    out=x["outcome"]
    assert out["family_recovery_remediation_id"]==x["remediation_id"]
    assert out["remediation_ref"]=="ARCH-71"
    con.close()

def test_healthy_runtime_observation_is_counted(tmp_path):
    con=init_db(tmp_path/"healthy.sqlite3")
    x=_setup_stable(con)
    c=_challenge(con,1)
    r=observe_runtime(con,ROOT,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    assert r["handled"] is True
    assert r["outcome"]["observation_count"]==1
    assert r["outcome"]["healthy_observation_count"]==1
    assert r["outcome"]["harmful_observation_count"]==0
    con.close()

def test_harmful_runtime_observation_is_counted(tmp_path):
    con=init_db(tmp_path/"harm.sqlite3")
    x=_setup_stable(con)
    c=_challenge(con,1)
    r=observe_runtime(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert r["outcome"]["harmful_observation_count"]==1
    con.close()

def test_other_algorithm_challenge_is_not_generation_evidence(tmp_path):
    con=init_db(tmp_path/"other.sqlite3")
    x=_setup_stable(con)
    register_version(con,ROOT,"other","eng",code_ref="other",config_ref="other",status="PROMOTED")
    c=_challenge(con,1)
    r=observe_runtime(con,ROOT,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    assert r["handled"] is False
    con.close()

def test_twenty_observations_before_30_days_stays_active(tmp_path):
    con=init_db(tmp_path/"early.sqlite3")
    x=_setup_stable(con)
    oid=x["outcome"]["family_generation_outcome_id"]
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_generation_outcomes
      SET observation_count=20,healthy_observation_count=20,harmful_observation_count=0,
          stabilized_at='2026-09-01T00:00:00+00:00' WHERE family_generation_outcome_id=?""",(oid,))
    con.commit()
    out=evaluate_sustained(con,oid,datetime(2026,9,3,tzinfo=timezone.utc))
    assert out["status"]=="ACTIVE"
    con.close()

def test_twenty_healthy_observations_after_30_days_becomes_sustained(tmp_path):
    con=init_db(tmp_path/"sustain.sqlite3")
    x=_setup_stable(con)
    oid=x["outcome"]["family_generation_outcome_id"]
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_generation_outcomes
      SET observation_count=20,healthy_observation_count=20,harmful_observation_count=0,
          stabilized_at='2026-07-01T00:00:00+00:00' WHERE family_generation_outcome_id=?""",(oid,))
    con.commit()
    out=evaluate_sustained(con,oid,datetime(2026,9,3,tzinfo=timezone.utc))
    assert out["status"]=="SUSTAINED_SUCCESS"
    assert out["finalized_at"]
    con.close()

def test_harmful_observation_blocks_sustained_success(tmp_path):
    con=init_db(tmp_path/"blocked.sqlite3")
    x=_setup_stable(con)
    oid=x["outcome"]["family_generation_outcome_id"]
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_generation_outcomes
      SET observation_count=20,healthy_observation_count=19,harmful_observation_count=1,
          stabilized_at='2026-07-01T00:00:00+00:00' WHERE family_generation_outcome_id=?""",(oid,))
    con.commit()
    out=evaluate_sustained(con,oid,datetime(2026,9,3,tzinfo=timezone.utc))
    assert out["status"]=="ACTIVE"
    con.close()

def test_next_circuit_open_marks_recurrence_and_days(tmp_path):
    con=init_db(tmp_path/"recurrence.sqlite3")
    x=_setup_stable(con)
    out=mark_recurrence(con,x["profile_id"],"2026-08-12T00:00:00+00:00")
    assert out["status"]=="RECURRENCE_FAILED"
    assert out["days_to_family_recurrence"]==10.0
    assert out["next_circuit_opened_at"]=="2026-08-12T00:00:00+00:00"
    con.close()

def test_two_sustained_attempts_make_remediation_preferred(tmp_path):
    con=init_db(tmp_path/"preferred.sqlite3")
    # Directly create two outcomes under the same family/remediation signature.
    x=_setup_stable(con,1,"SAME")
    fam=x["outcome"]["family_signature"]
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_generation_outcomes
                   SET status='SUSTAINED_SUCCESS',finalized_at='2026-09-01T00:00:00+00:00'
                   WHERE family_generation_outcome_id=?""",(x["outcome"]["family_generation_outcome_id"],))
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_generation_outcomes(
      family_recovery_case_id,fallback_family_profile_id,root_cause_type,family_signature,
      candidate_algorithm_version_id,remediation_type,remediation_ref,status,stabilized_at,finalized_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (999,x["profile_id"],ROOT,fam,x["candidate"]["algorithm_version_id"],
       "FAMILY_ARCHITECTURE_FIX","SAME","SUSTAINED_SUCCESS",
       "2026-07-01T00:00:00+00:00","2026-09-01T00:00:00+00:00"))
    con.commit()
    p=refresh_effectiveness(con,fam,"FAMILY_ARCHITECTURE_FIX","SAME")
    assert p["sustained_success_count"]==2
    assert p["effectiveness_band"]=="PREFERRED"
    con.close()

def test_one_recurrence_marks_remediation_watch(tmp_path):
    con=init_db(tmp_path/"watch.sqlite3")
    x=_setup_stable(con,1,"WATCH")
    mark_recurrence(con,x["profile_id"],"2026-08-12T00:00:00+00:00")
    p=refresh_effectiveness(con,x["outcome"]["family_signature"],
                            "FAMILY_ARCHITECTURE_FIX","WATCH")
    assert p["recurrence_failure_count"]==1
    assert p["effectiveness_band"]=="WATCH"
    con.close()

def test_two_recurrences_mark_same_remediation_avoid(tmp_path):
    con=init_db(tmp_path/"avoid.sqlite3")
    x=_setup_stable(con,1,"BAD")
    fam=x["outcome"]["family_signature"]
    con.execute("""UPDATE origin_threshold_recommendation_fallback_family_generation_outcomes
      SET status='RECURRENCE_FAILED',days_to_family_recurrence=5,finalized_at='2026-08-07T00:00:00+00:00'
      WHERE family_generation_outcome_id=?""",(x["outcome"]["family_generation_outcome_id"],))
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_generation_outcomes(
      family_recovery_case_id,fallback_family_profile_id,root_cause_type,family_signature,
      candidate_algorithm_version_id,remediation_type,remediation_ref,status,stabilized_at,
      next_circuit_opened_at,days_to_family_recurrence,finalized_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (998,x["profile_id"],ROOT,fam,x["candidate"]["algorithm_version_id"],
       "FAMILY_ARCHITECTURE_FIX","BAD","RECURRENCE_FAILED",
       "2026-08-10T00:00:00+00:00","2026-08-18T00:00:00+00:00",8,
       "2026-08-18T00:00:00+00:00"))
    con.commit()
    p=refresh_effectiveness(con,fam,"FAMILY_ARCHITECTURE_FIX","BAD")
    assert p["recurrence_failure_count"]==2
    assert p["effectiveness_band"]=="AVOID"
    assert remediation_allowed(con,fam,"FAMILY_ARCHITECTURE_FIX","BAD")["allowed"] is False
    con.close()

def test_avoid_remediation_cannot_be_reapproved_effective(tmp_path):
    con=init_db(tmp_path/"reject-rem.sqlite3")
    x=_setup_stable(con,1,"BAD2")
    fam=x["outcome"]["family_signature"]
    for case_id in (900,901):
        con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_generation_outcomes(
          family_recovery_case_id,fallback_family_profile_id,root_cause_type,family_signature,
          candidate_algorithm_version_id,remediation_type,remediation_ref,status,stabilized_at,
          days_to_family_recurrence,finalized_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
          (case_id,x["profile_id"],ROOT,fam,x["candidate"]["algorithm_version_id"],
           "FAMILY_ARCHITECTURE_FIX","BAD2","RECURRENCE_FAILED",
           "2026-07-01T00:00:00+00:00",4,
           "2026-07-05T00:00:00+00:00"))
    refresh_effectiveness(con,fam,"FAMILY_ARCHITECTURE_FIX","BAD2")
    # New open recovery case under same family.
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_cases(
      fallback_family_profile_id,root_cause_type,family_signature,recovery_number,status,
      opened_at,canary_max_fallbacks,canary_used_fallbacks)
      VALUES(?,?,?,?,?,?,?,?)""",
      (x["profile_id"],ROOT,fam,2,"OPEN","2026-09-03T00:00:00+00:00",1,0))
    cid=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.commit()
    rem=add_remediation(con,cid,"FAMILY_ARCHITECTURE_FIX","BAD2","eng","retry")
    with pytest.raises(ValueError,match="AVOID"):
        review_remediation(con,rem["family_recovery_remediation_id"],
                           "EFFECTIVE","chief","retry same failed remediation")
    con.close()

def test_status_exposes_generation_effectiveness_and_events(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    x=_setup_stable(con)
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["outcomes"])==1
    assert len(s["effectiveness_profiles"])==1
    assert len(s["events"])>=1
    con.close()
