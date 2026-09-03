import json
from datetime import datetime, timezone, timedelta
import pytest

from src.database import init_db
from src.origin_threshold_recurrence_guard import (
    recurrence_signature,update_recurrence_profile,profiles,recurrence_events,
    record_effective_remediation,evaluate_remediation_effectiveness,
    remediation_effectiveness_history,remediation_type_stats,
    restrictions,grant_restriction_exception,restriction_exceptions,
    active_restrictions_requiring_exception,release_restriction,recurrence_status
)
from src.origin_threshold_promotion import create_candidate_from_latest_calibration

def _now():
    return datetime.now(timezone.utc).isoformat()

def _recovery_root(con,rid,rootid,root_type="THRESHOLD_BOUNDARY",
                   status="OPEN",source=None,platform=None,risk="BASELINE"):
    con.execute("""INSERT INTO origin_threshold_recovery_cases(
      recovery_case_id,promotion_id,candidate_id,failed_threshold,fallback_threshold,
      status,rollback_reason,required_shadow_outcomes,safe_shadow_outcome_count,
      opened_at,requalified_by,requalified_at,requalification_reason)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (rid,rid,rid,.89,.86,status,"test",5,0,_now(),
       "human" if status=="REQUALIFIED" else None,
       _now() if status=="REQUALIFIED" else None,
       "test requal" if status=="REQUALIFIED" else None))
    con.execute("""INSERT INTO origin_threshold_root_causes(
      root_cause_id,recovery_case_id,promotion_id,failure_class,root_cause_type,
      risk_band,dominant_source_id,dominant_platform,source_concentration,
      boundary_distance,repeated_root_cause_count,evidence_json,reasons_json,attributed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (rootid,rid,rid,"MISSED_SYNDICATION",root_type,risk,source,platform,
       1.0 if source else 0.0,.02 if root_type=="THRESHOLD_BOUNDARY" else .2,
       rootid,'{}','[]',_now()))
    con.commit()
    return update_recurrence_profile(con,rootid)

def _effective_remediation(con,rid,rootid,remid,rem_type="THRESHOLD_CHANGE",
                           submitted_at=None):
    submitted_at=submitted_at or _now()
    con.execute("""INSERT INTO origin_threshold_remediations(
      remediation_id,recovery_case_id,root_cause_id,remediation_type,
      remediation_ref,notes,submitted_by,submitted_at,status)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (remid,rid,rootid,rem_type,f"R-{remid}","fix","human",submitted_at,"EFFECTIVE"))
    con.commit()
    return record_effective_remediation(con,remid)

def _calibration(con,cal_id=100):
    con.execute("""INSERT INTO origin_inference_calibrations(
      calibration_id,policy_version,reviewed_cluster_count,
      confirmed_syndication_count,confirmed_independent_count,hold_count,
      precision,false_positive_rate,baseline_text_threshold,
      shadow_recommended_text_threshold,threshold_delta,
      recommendation_status,reasons_json,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cal_id,"v0.53",0,0,0,0,None,None,.86,.89,.03,
       "SHADOW_TIGHTEN",'["test"]',_now()))
    con.commit()

def _manual_restriction(con,signature="THRESHOLD_BOUNDARY|*|*"):
    con.execute("""INSERT INTO origin_threshold_recurrence_profiles(
      recurrence_profile_id,signature,root_cause_type,dominant_source_id,
      dominant_platform,recurrence_count,post_requalification_recurrence_count,
      failed_effective_remediation_count,risk_band,long_term_restricted,
      reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,signature,"THRESHOLD_BOUNDARY",None,None,3,2,2,"RESTRICTED",1,'[]',_now()))
    con.execute("""INSERT INTO origin_threshold_long_term_restrictions(
      restriction_id,recurrence_profile_id,signature,status,trigger_recovery_case_id,
      trigger_reason,recurrence_count,failed_effective_remediation_count,
      requires_human_exception,started_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (1,1,signature,"ACTIVE",3,"repeated",3,2,1,_now()))
    con.commit()

def test_first_root_cause_occurrence_is_baseline_without_restriction(tmp_path):
    con=init_db(tmp_path/"first.sqlite3")
    r=_recovery_root(con,1,1,status="OPEN")
    assert r["profile"]["recurrence_count"]==1
    assert r["profile"]["risk_band"]=="BASELINE"
    assert r["profile"]["long_term_restricted"]==0
    assert r["restriction"] is None
    con.close()

def test_second_post_requalification_occurrence_is_elevated(tmp_path):
    con=init_db(tmp_path/"second.sqlite3")
    _recovery_root(con,1,1,status="REQUALIFIED")
    _effective_remediation(con,1,1,1)
    r=_recovery_root(con,2,2,status="OPEN")
    assert r["profile"]["recurrence_count"]==2
    assert r["profile"]["post_requalification_recurrence_count"]==1
    assert r["profile"]["failed_effective_remediation_count"]==1
    assert r["profile"]["risk_band"]=="ELEVATED"
    assert r["restriction"] is None
    hist=remediation_effectiveness_history(con)
    assert hist[0]["status"]=="RECURRENCE_FAILED"
    assert hist[0]["subsequent_recovery_case_id"]==2
    con.close()

def test_third_recurrence_creates_long_term_restriction(tmp_path):
    con=init_db(tmp_path/"third.sqlite3")
    _recovery_root(con,1,1,status="REQUALIFIED")
    _effective_remediation(con,1,1,1)
    _recovery_root(con,2,2,status="REQUALIFIED")
    _effective_remediation(con,2,2,2)
    r=_recovery_root(con,3,3,status="OPEN")
    assert r["profile"]["recurrence_count"]==3
    assert r["profile"]["post_requalification_recurrence_count"]==2
    assert r["profile"]["failed_effective_remediation_count"]==2
    assert r["profile"]["risk_band"]=="RESTRICTED"
    assert r["profile"]["long_term_restricted"]==1
    assert r["restriction"]["status"]=="ACTIVE"
    assert len(restrictions(con))==1
    con.close()

def test_boundary_signature_ignores_incidental_source_platform(tmp_path):
    con=init_db(tmp_path/"signature.sqlite3")
    a={"root_cause_type":"THRESHOLD_BOUNDARY","dominant_source_id":"S1","dominant_platform":"FACEBOOK"}
    b={"root_cause_type":"THRESHOLD_BOUNDARY","dominant_source_id":"S2","dominant_platform":"NAVER_BLOG"}
    assert recurrence_signature(a)==recurrence_signature(b)=="THRESHOLD_BOUNDARY|*|*"
    con.close()

def test_source_concentration_signature_keeps_source_identity(tmp_path):
    con=init_db(tmp_path/"source-sig.sqlite3")
    a={"root_cause_type":"SOURCE_CONCENTRATION","dominant_source_id":"S1","dominant_platform":"FACEBOOK"}
    b={"root_cause_type":"SOURCE_CONCENTRATION","dominant_source_id":"S2","dominant_platform":"FACEBOOK"}
    assert recurrence_signature(a)=="SOURCE_CONCENTRATION|S1|*"
    assert recurrence_signature(a)!=recurrence_signature(b)
    con.close()

def test_effective_remediation_enters_pending_history(tmp_path):
    con=init_db(tmp_path/"pending.sqlite3")
    _recovery_root(con,1,1,status="REQUALIFIED")
    r=_effective_remediation(con,1,1,1,"THRESHOLD_CHANGE")
    assert r["status"]=="EFFECTIVE_PENDING"
    stats=remediation_type_stats(con)
    assert stats[0]["pending"]==1
    assert stats[0]["sustained_success_rate"] is None
    con.close()

def test_pending_remediation_becomes_sustained_after_no_recurrence_window(tmp_path):
    con=init_db(tmp_path/"sustained.sqlite3")
    _recovery_root(con,1,1,status="REQUALIFIED")
    old=(datetime.now(timezone.utc)-timedelta(days=40)).isoformat()
    _effective_remediation(con,1,1,1,"THRESHOLD_CHANGE",old)
    r=evaluate_remediation_effectiveness(con,min_sustained_days=30)
    assert r["sustained_marked_count"]==1
    hist=remediation_effectiveness_history(con)
    assert hist[0]["status"]=="SUSTAINED_EFFECTIVE"
    stats=remediation_type_stats(con)
    assert stats[0]["sustained_success_rate"]==1.0
    con.close()

def test_sustained_effective_can_later_be_marked_recurrence_failed(tmp_path):
    con=init_db(tmp_path/"late-failure.sqlite3")
    _recovery_root(con,1,1,status="REQUALIFIED")
    old=(datetime.now(timezone.utc)-timedelta(days=40)).isoformat()
    _effective_remediation(con,1,1,1,"THRESHOLD_CHANGE",old)
    evaluate_remediation_effectiveness(con,30)
    _recovery_root(con,2,2,status="OPEN")
    hist=remediation_effectiveness_history(con)
    assert hist[0]["status"]=="RECURRENCE_FAILED"
    assert hist[0]["subsequent_recovery_case_id"]==2
    stats=remediation_type_stats(con)
    assert stats[0]["recurrence_failed"]==1
    assert stats[0]["sustained_effective"]==0
    assert stats[0]["sustained_success_rate"]==0.0
    con.close()

def test_active_restriction_blocks_new_candidate_without_exception(tmp_path):
    con=init_db(tmp_path/"blocked.sqlite3")
    _manual_restriction(con)
    _calibration(con)
    with pytest.raises(ValueError,match="require explicit Human exception"):
        create_candidate_from_latest_calibration(con)
    con.close()

def test_approved_exception_is_one_time_and_consumed_by_candidate(tmp_path):
    con=init_db(tmp_path/"exception.sqlite3")
    _manual_restriction(con)
    _calibration(con,100)
    ex=grant_restriction_exception(con,1,"APPROVE","김프로","controlled retry")
    c=create_candidate_from_latest_calibration(con)
    assert ex["exception_id"] in c["consumed_restriction_exception_ids"]
    xs=restriction_exceptions(con)
    assert xs[0]["consumed_at"] is not None
    # New calibration/attempt is blocked again because the exception was one-time.
    con.execute("UPDATE origin_threshold_candidates SET status='RUNTIME_ROLLED_BACK'")
    _calibration(con,101)
    with pytest.raises(ValueError,match="require explicit Human exception"):
        create_candidate_from_latest_calibration(con)
    con.close()

def test_deny_or_hold_exception_never_unlocks_candidate(tmp_path):
    for decision in ("DENY","HOLD"):
        db=tmp_path/f"{decision}.sqlite3"
        con=init_db(db)
        _manual_restriction(con)
        _calibration(con)
        grant_restriction_exception(con,1,decision,"human","do not retry")
        with pytest.raises(ValueError,match="require explicit Human exception"):
            create_candidate_from_latest_calibration(con)
        con.close()

def test_human_release_clears_active_long_term_restriction(tmp_path):
    con=init_db(tmp_path/"release.sqlite3")
    _manual_restriction(con)
    r=release_restriction(con,1,"김프로","systemic issue fixed")
    assert r["status"]=="RELEASED"
    assert profiles(con)[0]["long_term_restricted"]==0
    assert active_restrictions_requiring_exception(con)==[]
    con.close()

def test_recurrence_event_links_previous_remediation(tmp_path):
    con=init_db(tmp_path/"event-link.sqlite3")
    _recovery_root(con,1,1,status="REQUALIFIED")
    _effective_remediation(con,1,1,11)
    _recovery_root(con,2,2,status="OPEN")
    ev=recurrence_events(con)[-1]
    assert ev["event_type"]=="RECURRENCE"
    assert ev["previous_recovery_case_id"]==1
    assert ev["previous_remediation_id"]==11
    con.close()

def test_recurrence_status_contains_profiles_restrictions_and_stats(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    _recovery_root(con,1,1,status="REQUALIFIED")
    _effective_remediation(con,1,1,1)
    s=recurrence_status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["profiles"])==1
    assert len(s["effectiveness_history"])==1
    assert s["remediation_type_stats"][0]["remediation_type"]=="THRESHOLD_CHANGE"
    con.close()

def test_two_post_requalification_recurrences_are_enough_for_restriction(tmp_path):
    con=init_db(tmp_path/"post-requal.sqlite3")
    _recovery_root(con,1,1,status="REQUALIFIED")
    # No remediation on first cycle.
    _recovery_root(con,2,2,status="REQUALIFIED")
    _recovery_root(con,3,3,status="OPEN")
    p=profiles(con)[0]
    assert p["post_requalification_recurrence_count"]==2
    assert p["long_term_restricted"]==1
    assert restrictions(con)[0]["status"]=="ACTIVE"
    con.close()
