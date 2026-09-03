import pytest
from src.database import init_db
from src.origin_threshold_recommendation_fallback_family_recommendation_outcome import (
    register_generation,resolve_generation,outcomes,effectiveness_profiles,status
)

FAM="1=>2"

def _base(con,*,recommended="GOOD",selected="GOOD",rec_score=.8,sel_score=.8,selection=True):
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_recommendations(
      family_recovery_case_id,family_signature,source,status,recommended_remediation_type,
      recommended_remediation_ref,recommended_score,score_margin,human_selection_required,
      reasons_json,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
      (1,FAM,"EFFECTIVENESS_MEMORY_SHADOW","SHADOW_PREFERRED",
       "FAMILY_ARCHITECTURE_FIX",recommended,rec_score,.2,1,'[]',
       "2026-09-03T00:00:00+00:00"))
    rec_id=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_rankings(
      family_recovery_case_id,family_signature,historical_family_signature,
      remediation_type,remediation_ref,context_similarity,attempt_count,decisive_count,
      sustained_success_count,recurrence_failure_count,wilson_lower_bound,survival_score,
      evidence_score,recurrence_penalty,conservative_score,confidence_band,
      effectiveness_band,rank_state,rank_position,reasons_json,ranked_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,FAM,FAM,"FAMILY_ARCHITECTURE_FIX",selected,1,5,5,5,0,.56,1,1,0,sel_score,
       "ESTABLISHED","PREFERRED","PREFERRED",1,'[]',"2026-09-03T00:00:00+00:00"))
    rank_id=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    sel_id=None
    if selection:
        con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_selection_reviews(
          family_recovery_case_id,family_remediation_recommendation_id,
          family_remediation_ranking_id,decision,selected_remediation_type,
          selected_remediation_ref,reviewer,reason,reviewed_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (1,rec_id,rank_id,"SELECT","FAMILY_ARCHITECTURE_FIX",selected,
           "chief","selected","2026-09-03T00:00:00+00:00"))
        sel_id=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_generation_outcomes(
      family_recovery_case_id,fallback_family_profile_id,root_cause_type,family_signature,
      candidate_algorithm_version_id,remediation_type,remediation_ref,status,stabilized_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (1,1,"SOURCE_LOCAL_RECURRENCE",FAM,10,
       "FAMILY_ARCHITECTURE_FIX",selected,"ACTIVE","2026-09-03T00:00:00+00:00"))
    gen_id=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.commit()
    return gen_id

def test_register_generation_pending(tmp_path):
    con=init_db(tmp_path/"a.sqlite3")
    gid=_base(con)
    o=register_generation(con,gid)
    assert o["outcome_class"]=="STABILIZED_PENDING"
    assert o["recommendation_accepted"]==1
    con.close()

def test_registration_idempotent(tmp_path):
    con=init_db(tmp_path/"b.sqlite3")
    gid=_base(con)
    a=register_generation(con,gid); b=register_generation(con,gid)
    assert a["family_recommendation_outcome_id"]==b["family_recommendation_outcome_id"]
    con.close()

def test_accepted_sustained_is_helpful(tmp_path):
    con=init_db(tmp_path/"c.sqlite3")
    gid=_base(con)
    register_generation(con,gid)
    o=resolve_generation(con,gid,"SUSTAINED_SUCCESS")
    assert o["outcome_class"]=="RECOMMENDATION_HELPFUL"
    con.close()

def test_accepted_recurrence_is_harmful(tmp_path):
    con=init_db(tmp_path/"d.sqlite3")
    gid=_base(con)
    register_generation(con,gid)
    o=resolve_generation(con,gid,"RECURRENCE_FAILED")
    assert o["outcome_class"]=="RECOMMENDATION_HARMFUL"
    con.close()

def test_override_success(tmp_path):
    con=init_db(tmp_path/"e.sqlite3")
    gid=_base(con,recommended="GOOD",selected="ALT",rec_score=.8,sel_score=.6)
    o=resolve_generation(con,gid,"SUSTAINED_SUCCESS")
    assert o["human_override"]==1
    assert o["outcome_class"]=="HUMAN_OVERRIDE_SUCCESS"
    con.close()

def test_override_failure(tmp_path):
    con=init_db(tmp_path/"f.sqlite3")
    gid=_base(con,recommended="GOOD",selected="ALT",rec_score=.8,sel_score=.6)
    o=resolve_generation(con,gid,"RECURRENCE_FAILED")
    assert o["outcome_class"]=="HUMAN_OVERRIDE_FAILURE"
    assert o["selection_regret_score"]==pytest.approx(.2)
    con.close()

def test_manual_without_selection_success(tmp_path):
    con=init_db(tmp_path/"g.sqlite3")
    gid=_base(con,recommended="GOOD",selected="ALT",selection=False)
    o=resolve_generation(con,gid,"SUSTAINED_SUCCESS")
    assert o["outcome_class"]=="HUMAN_OVERRIDE_SUCCESS"
    con.close()

def test_profile_acceptance_rate(tmp_path):
    con=init_db(tmp_path/"h.sqlite3")
    gid=_base(con)
    resolve_generation(con,gid,"SUSTAINED_SUCCESS")
    p=effectiveness_profiles(con)[0]
    assert p["acceptance_rate"]==1.0
    assert p["recommendation_helpful_rate"]==1.0
    con.close()

def test_profile_override_success_rate(tmp_path):
    con=init_db(tmp_path/"i.sqlite3")
    gid=_base(con,recommended="GOOD",selected="ALT")
    resolve_generation(con,gid,"SUSTAINED_SUCCESS")
    p=effectiveness_profiles(con)[0]
    assert p["override_success_rate"]==1.0
    con.close()

def test_low_data_calibration(tmp_path):
    con=init_db(tmp_path/"j.sqlite3")
    gid=_base(con)
    resolve_generation(con,gid,"SUSTAINED_SUCCESS")
    assert effectiveness_profiles(con)[0]["calibration_band"]=="LOW_DATA"
    con.close()

def test_three_clean_helpful_is_well_calibrated(tmp_path):
    con=init_db(tmp_path/"k.sqlite3")
    # direct resolved rows for compact aggregate test
    for case in (1,2,3):
        con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recommendation_outcomes(
          family_recovery_case_id,family_signature,family_generation_outcome_id,
          recommendation_accepted,human_override,generation_status,outcome_class,
          selection_regret_score,reasons_json,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
          (case,FAM,case,1,0,"SUSTAINED_SUCCESS","RECOMMENDATION_HELPFUL",0,'[]',
           "2026-09-03T00:00:00+00:00","2026-09-03T00:00:00+00:00"))
    from src.origin_threshold_recommendation_fallback_family_recommendation_outcome import refresh_profile
    p=refresh_profile(con,FAM)
    assert p["calibration_band"]=="WELL_CALIBRATED"
    con.close()

def test_repeated_harmful_is_misaligned(tmp_path):
    con=init_db(tmp_path/"l.sqlite3")
    for case in (1,2,3):
        cls="RECOMMENDATION_HARMFUL" if case<3 else "RECOMMENDATION_HELPFUL"
        status="RECURRENCE_FAILED" if case<3 else "SUSTAINED_SUCCESS"
        con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recommendation_outcomes(
          family_recovery_case_id,family_signature,family_generation_outcome_id,
          recommendation_accepted,human_override,generation_status,outcome_class,
          selection_regret_score,reasons_json,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
          (case,FAM,case,1,0,status,cls,0,'[]',
           "2026-09-03T00:00:00+00:00","2026-09-03T00:00:00+00:00"))
    from src.origin_threshold_recommendation_fallback_family_recommendation_outcome import refresh_profile
    assert refresh_profile(con,FAM)["calibration_band"]=="MISALIGNED"
    con.close()

def test_outcome_resolved_at_set(tmp_path):
    con=init_db(tmp_path/"m.sqlite3")
    gid=_base(con)
    o=resolve_generation(con,gid,"SUSTAINED_SUCCESS")
    assert o["resolved_at"]
    con.close()

def test_outcomes_filter_by_family(tmp_path):
    con=init_db(tmp_path/"n.sqlite3")
    gid=_base(con)
    register_generation(con,gid)
    assert len(outcomes(con,FAM))==1
    assert len(outcomes(con,"x=>y"))==0
    con.close()

def test_status_audit(tmp_path):
    con=init_db(tmp_path/"o.sqlite3")
    gid=_base(con)
    resolve_generation(con,gid,"SUSTAINED_SUCCESS")
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["outcomes"])==1
    assert len(s["effectiveness_profiles"])==1
    assert len(s["events"])>=2
    con.close()
