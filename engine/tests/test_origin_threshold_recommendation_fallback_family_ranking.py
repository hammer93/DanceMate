import pytest

from src.database import init_db
from src.origin_threshold_recommendation_fallback_family_ranking import (
    rank_case,recommend_case,review_selection,rankings,recommendations,
    selection_reviews,selection_allows,status
)
from src.origin_threshold_recommendation_fallback_family_recovery import add_remediation

ROOT="SOURCE_LOCAL_RECURRENCE"
FAM="1=>2"

def _current_case(con,family=FAM):
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_profiles(
      root_cause_type,family_root_algorithm_version_id,fallback_target_algorithm_version_id,
      family_signature,executed_fallback_count,distinct_failing_version_count,
      stable_verification_count,watch_verification_count,failed_verification_count,
      circuit_state,architecture_review_required,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ROOT,1,2,family,2,2,0,0,0,"OPEN",1,'[]',"2026-09-03T00:00:00+00:00"))
    pid=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_recovery_cases(
      fallback_family_profile_id,root_cause_type,family_signature,recovery_number,status,
      canary_max_fallbacks,canary_used_fallbacks,opened_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (pid,ROOT,family,1,"OPEN",1,0,"2026-09-03T00:00:00+00:00"))
    cid=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.commit()
    return cid

def _history(con,rem_ref,*,family=FAM,root=ROOT,attempts=2,sustained=2,failed=0,
             avg_days=None,confidence="EMERGING",band=None,rem_type="FAMILY_ARCHITECTURE_FIX"):
    if band is None:
        band="AVOID" if failed>=2 else "WATCH" if failed else "PREFERRED" if sustained>=2 else "LEARNING"
    decisive=sustained+failed
    success=(sustained/decisive) if decisive else None
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_remediation_effectiveness_profiles(
      family_signature,remediation_type,remediation_ref,attempt_count,active_count,
      sustained_success_count,recurrence_failure_count,success_rate,
      avg_days_to_family_recurrence,confidence_band,effectiveness_band,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (family,rem_type,rem_ref,attempts,max(0,attempts-decisive),sustained,failed,
       success,avg_days,confidence,band,'[]',"2026-09-03T00:00:00+00:00"))
    # Ranking uses generation lineage to recover Root Cause for each historical profile.
    con.execute("""INSERT INTO origin_threshold_recommendation_fallback_family_generation_outcomes(
      family_recovery_case_id,fallback_family_profile_id,root_cause_type,family_signature,
      candidate_algorithm_version_id,remediation_type,remediation_ref,status,stabilized_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (1000+con.execute("SELECT COUNT(*) n FROM origin_threshold_recommendation_fallback_family_generation_outcomes").fetchone()["n"],
       999,root,family,777,rem_type,rem_ref,
       "SUSTAINED_SUCCESS" if sustained else "RECURRENCE_FAILED",
       "2026-07-01T00:00:00+00:00"))
    con.commit()

def test_exact_family_context_similarity_is_one(tmp_path):
    con=init_db(tmp_path/"exact.sqlite3")
    cid=_current_case(con)
    _history(con,"A")
    r=rank_case(con,cid,persist=False)[0]
    assert r["context_similarity"]==1.0
    con.close()

def test_same_root_cross_family_is_lower_similarity(tmp_path):
    con=init_db(tmp_path/"cross.sqlite3")
    cid=_current_case(con)
    _history(con,"A",family="9=>10")
    r=rank_case(con,cid,persist=False)[0]
    assert r["context_similarity"]==0.65
    con.close()

def test_different_root_cause_history_is_excluded(tmp_path):
    con=init_db(tmp_path/"root.sqlite3")
    cid=_current_case(con)
    _history(con,"A",family="9=>10",root="THRESHOLD_RECURRENCE")
    assert rank_case(con,cid,persist=False)==[]
    con.close()

def test_one_of_one_success_is_low_data_not_preferred(tmp_path):
    con=init_db(tmp_path/"one.sqlite3")
    cid=_current_case(con)
    _history(con,"A",attempts=1,sustained=1,confidence="LOW_DATA",band="LEARNING")
    r=rank_case(con,cid,persist=False)[0]
    assert r["rank_state"]=="LOW_DATA"
    con.close()

def test_two_sustained_exact_family_can_be_preferred(tmp_path):
    con=init_db(tmp_path/"preferred.sqlite3")
    cid=_current_case(con)
    _history(con,"A",attempts=2,sustained=2)
    r=rank_case(con,cid,persist=False)[0]
    assert r["rank_state"]=="PREFERRED"
    assert r["conservative_score"]>=.50
    con.close()

def test_large_clean_history_outranks_small_perfect_history(tmp_path):
    con=init_db(tmp_path/"sample.sqlite3")
    cid=_current_case(con)
    _history(con,"SMALL",attempts=2,sustained=2)
    _history(con,"LARGE",attempts=20,sustained=20,confidence="ESTABLISHED")
    rr=rank_case(con,cid,persist=False)
    assert rr[0]["remediation_ref"]=="LARGE"
    assert rr[0]["conservative_score"]>rr[1]["conservative_score"]
    con.close()

def test_longer_failure_survival_scores_better_than_early_recurrence(tmp_path):
    con=init_db(tmp_path/"survival.sqlite3")
    cid=_current_case(con)
    _history(con,"EARLY",attempts=3,sustained=2,failed=1,avg_days=5,band="WATCH")
    _history(con,"LATE",attempts=3,sustained=2,failed=1,avg_days=80,band="WATCH")
    rr=rank_case(con,cid,persist=False)
    by={r["remediation_ref"]:r for r in rr}
    assert by["LATE"]["survival_score"]>by["EARLY"]["survival_score"]
    assert by["LATE"]["conservative_score"]>by["EARLY"]["conservative_score"]
    con.close()

def test_avoid_remediation_is_ranked_but_not_safe_recommendation(tmp_path):
    con=init_db(tmp_path/"avoid.sqlite3")
    cid=_current_case(con)
    _history(con,"BAD",attempts=4,sustained=2,failed=2,confidence="ESTABLISHED",band="AVOID")
    rec=recommend_case(con,cid,persist=True)
    assert rec["rankings"][0]["rank_state"]=="AVOID"
    assert rec["status"]=="NO_SAFE_MEMORY"
    assert rec["recommended_remediation_ref"] is None
    con.close()

def test_preferred_memory_is_shadow_only_and_requires_human_selection(tmp_path):
    con=init_db(tmp_path/"shadow.sqlite3")
    cid=_current_case(con)
    _history(con,"GOOD",attempts=5,sustained=5,confidence="ESTABLISHED")
    rec=recommend_case(con,cid,persist=True)
    assert rec["status"]=="SHADOW_PREFERRED"
    assert rec["source"]=="EFFECTIVENESS_MEMORY_SHADOW"
    assert rec["human_selection_required"] is True
    assert rec["recommended_remediation_ref"]=="GOOD"
    con.close()

def test_small_margin_does_not_get_shadow_preferred(tmp_path):
    con=init_db(tmp_path/"margin.sqlite3")
    cid=_current_case(con)
    _history(con,"A",attempts=5,sustained=5,confidence="ESTABLISHED")
    _history(con,"B",attempts=5,sustained=5,confidence="ESTABLISHED")
    rec=recommend_case(con,cid,persist=False)
    assert rec["score_margin"]==pytest.approx(0.0)
    assert rec["status"]=="LOW_DATA_OR_SMALL_MARGIN"
    con.close()

def test_recommendation_never_auto_submits_remediation(tmp_path):
    con=init_db(tmp_path/"noauto.sqlite3")
    cid=_current_case(con)
    _history(con,"GOOD",attempts=5,sustained=5,confidence="ESTABLISHED")
    recommend_case(con,cid,persist=True)
    n=con.execute("""SELECT COUNT(*) n FROM origin_threshold_recommendation_fallback_family_recovery_remediations
                     WHERE family_recovery_case_id=?""",(cid,)).fetchone()["n"]
    assert n==0
    con.close()

def test_human_can_select_non_avoid_ranked_remediation(tmp_path):
    con=init_db(tmp_path/"select.sqlite3")
    cid=_current_case(con)
    _history(con,"GOOD",attempts=5,sustained=5,confidence="ESTABLISHED")
    rec=recommend_case(con,cid,persist=True)
    rid=rankings(con,cid)[0]["family_remediation_ranking_id"]
    sel=review_selection(con,cid,"SELECT","chief","best conservative evidence",rid)
    assert sel["selected_remediation_ref"]=="GOOD"
    assert len(selection_reviews(con,cid))==1
    con.close()

def test_human_cannot_select_avoid_remediation(tmp_path):
    con=init_db(tmp_path/"selectbad.sqlite3")
    cid=_current_case(con)
    _history(con,"BAD",attempts=4,sustained=2,failed=2,confidence="ESTABLISHED",band="AVOID")
    recommend_case(con,cid,persist=True)
    rid=rankings(con,cid)[0]["family_remediation_ranking_id"]
    with pytest.raises(ValueError,match="AVOID"):
        review_selection(con,cid,"SELECT","chief","try bad",rid)
    con.close()

def test_historical_remediation_reuse_requires_human_selection(tmp_path):
    con=init_db(tmp_path/"gate.sqlite3")
    cid=_current_case(con)
    _history(con,"GOOD",attempts=5,sustained=5,confidence="ESTABLISHED")
    recommend_case(con,cid,persist=True)
    with pytest.raises(ValueError,match="Human Architecture Selection"):
        add_remediation(con,cid,"FAMILY_ARCHITECTURE_FIX","GOOD","eng","reuse")
    con.close()

def test_selected_historical_remediation_can_be_submitted(tmp_path):
    con=init_db(tmp_path/"allow.sqlite3")
    cid=_current_case(con)
    _history(con,"GOOD",attempts=5,sustained=5,confidence="ESTABLISHED")
    recommend_case(con,cid,persist=True)
    rid=rankings(con,cid)[0]["family_remediation_ranking_id"]
    review_selection(con,cid,"SELECT","chief","selected after architecture review",rid)
    rem=add_remediation(con,cid,"FAMILY_ARCHITECTURE_FIX","GOOD","eng","reuse")
    assert rem["remediation_ref"]=="GOOD"
    assert selection_allows(con,cid,"FAMILY_ARCHITECTURE_FIX","GOOD")["allowed"] is True
    con.close()

def test_status_exposes_rankings_recommendations_reviews_and_events(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    cid=_current_case(con)
    _history(con,"GOOD",attempts=5,sustained=5,confidence="ESTABLISHED")
    recommend_case(con,cid,persist=True)
    rid=rankings(con,cid)[0]["family_remediation_ranking_id"]
    review_selection(con,cid,"SELECT","chief","select",rid)
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["rankings"])==1
    assert len(s["recommendations"])==1
    assert len(s["selection_reviews"])==1
    assert len(s["events"])>=2
    con.close()
