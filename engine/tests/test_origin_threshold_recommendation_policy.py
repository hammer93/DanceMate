import pytest

from src.database import init_db
from src.origin_threshold_recommendation_challenge import create_challenge
from src.origin_threshold_recommendation_versioning import current_version
from src.origin_threshold_recommendation_version_promotion import human_review as version_human_review
from src.origin_threshold_recommendation_policy import (
    evaluate_candidate,review_candidate,states,maybe_assign_canary,
    resolve_selection,observe_runtime_verdict,final_policy_review,
    manual_rollback,assignments,status
)

ROOT="SOURCE_LOCAL_RECURRENCE"
REC=["DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"]
BASE=["COLLECTOR_FIX","DATA_QUALITY_FIX"]

def _profile(con,decisive=5,helpful=4,harmful=0,accepted=4,baseline=1,hold=0,confidence="ESTABLISHED"):
    total=max(decisive,1)
    con.execute("""INSERT INTO origin_threshold_architecture_recommendation_quality_profiles(
      root_cause_type,challenge_count,accepted_count,baseline_selected_count,hold_count,
      runtime_decisive_count,recommendation_helpful_count,recommendation_harmful_count,
      recommendation_neutral_count,acceptance_rate,helpful_rate,harmful_rate,
      confidence_band,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ROOT,accepted+baseline+hold,accepted,baseline,hold,decisive,helpful,harmful,
       max(0,decisive-helpful-harmful),
       accepted/(accepted+baseline) if accepted+baseline else None,
       helpful/total,harmful/total,confidence,"2026-09-02T00:00:00+00:00"))
    con.commit()

def _rec():
    return {
        "selected_steps":REC,"source":"CONTEXT_COMPARATIVE_RANKING",
        "comparative_score":.82,"context_signature":"CTX"
    }

def _challenge(con,scope):
    return create_challenge(con,scope,ROOT,"CTX",_rec(),BASE)

def _candidate_ready(con):
    c=evaluate_candidate(con,ROOT,persist=True)
    assert c["status"]=="READY_FOR_POLICY_REVIEW"
    return c

def _start_canary(con,maxn=3):
    c=_candidate_ready(con)
    return review_candidate(
        con,c["policy_candidate_id"],"APPROVE_CANARY",
        "policy-owner","quality thresholds passed",maxn)

def _version_promotion_ready(con):
    v=current_version(con,ROOT)
    con.execute("""INSERT OR REPLACE INTO origin_threshold_recommendation_algorithm_version_profiles(
      algorithm_version_id,root_cause_type,context_signature,total_runtime_count,
      decisive_runtime_count,canary_runtime_count,production_runtime_count,
      helpful_count,harmful_count,neutral_count,rollback_count,helpful_rate,
      harmful_rate,median_survival_days,confidence_band,safety_band,
      promotion_memory_status,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (v["algorithm_version_id"],ROOT,"CTX",3,3,3,0,3,0,0,0,1.0,0.0,90.0,
       "EMERGING","SAFE","VERSION_CANARY_PROVEN",'[]',"2026-09-02T00:00:00+00:00"))
    con.commit()
    version_human_review(
        con,v["algorithm_version_id"],"PROMOTE","version-owner",
        "version canary evidence passed")

def test_no_profile_is_not_eligible(tmp_path):
    con=init_db(tmp_path/"no.sqlite3")
    r=evaluate_candidate(con,ROOT,persist=False)
    assert r["status"]=="NO_PROFILE"
    assert r["eligible"] is False
    con.close()

def test_low_data_profile_is_warming(tmp_path):
    con=init_db(tmp_path/"low.sqlite3")
    _profile(con,decisive=2,helpful=2,accepted=2,baseline=0,confidence="LOW_DATA")
    r=evaluate_candidate(con,ROOT,persist=True)
    assert r["status"]=="WARMING"
    assert r["eligible"] is False
    con.close()

def test_established_helpful_profile_is_ready(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    _profile(con)
    r=evaluate_candidate(con,ROOT,persist=True)
    assert r["eligible"] is True
    assert r["helpful_rate"]>=.60
    assert r["harmful_rate"]<=.10
    con.close()

def test_harmful_rate_blocks_candidate(tmp_path):
    con=init_db(tmp_path/"harm.sqlite3")
    _profile(con,decisive=5,helpful=3,harmful=1)
    r=evaluate_candidate(con,ROOT,persist=False)
    assert r["eligible"] is False
    assert any("harmful rate" in x for x in r["reasons"])
    con.close()

def test_low_acceptance_blocks_candidate(tmp_path):
    con=init_db(tmp_path/"accept.sqlite3")
    _profile(con,decisive=5,helpful=4,harmful=0,accepted=2,baseline=3)
    r=evaluate_candidate(con,ROOT,persist=False)
    assert r["eligible"] is False
    assert any("acceptance rate" in x for x in r["reasons"])
    con.close()

def test_canary_review_requires_ready_candidate(tmp_path):
    con=init_db(tmp_path/"review.sqlite3")
    _profile(con,decisive=2,helpful=2,accepted=2,baseline=0,confidence="LOW_DATA")
    c=evaluate_candidate(con,ROOT,persist=True)
    with pytest.raises(ValueError,match="not ready"):
        review_candidate(con,c["policy_candidate_id"],"APPROVE_CANARY",
                         "owner","too early",3)
    con.close()

def test_shadow_only_defaults_to_deterministic_baseline(tmp_path):
    con=init_db(tmp_path/"shadow.sqlite3")
    c=_challenge(con,1)
    r=resolve_selection(con,ROOT,c["challenge_id"],REC,BASE,None)
    assert r["policy_mode"]=="SHADOW_ONLY"
    assert r["selected_side"]=="BASELINE"
    assert r["steps"]==BASE
    con.close()

def test_canary_assignment_selects_recommendation(tmp_path):
    con=init_db(tmp_path/"canary.sqlite3")
    _profile(con); _start_canary(con,3)
    c=_challenge(con,1)
    r=resolve_selection(con,ROOT,c["challenge_id"],REC,BASE,None)
    assert r["policy_mode"]=="CANARY"
    assert r["selected_side"]=="RECOMMENDATION"
    assert len(assignments(con,ROOT))==1
    con.close()

def test_canary_assignment_is_bounded_and_fourth_uses_baseline(tmp_path):
    con=init_db(tmp_path/"cap.sqlite3")
    _profile(con); _start_canary(con,3)
    sides=[]
    for scope in range(1,5):
        c=_challenge(con,scope)
        sides.append(resolve_selection(con,ROOT,c["challenge_id"],REC,BASE,None)["selected_side"])
    assert sides==["RECOMMENDATION","RECOMMENDATION","RECOMMENDATION","BASELINE"]
    assert len(assignments(con,ROOT))==3
    con.close()

def test_three_helpful_canary_results_become_ready_for_promotion(tmp_path):
    con=init_db(tmp_path/"ready-promote.sqlite3")
    _profile(con); _start_canary(con,3)
    for scope in range(1,4):
        c=_challenge(con,scope)
        resolve_selection(con,ROOT,c["challenge_id"],REC,BASE,None)
        st=observe_runtime_verdict(con,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    assert st["mode"]=="READY_FOR_PROMOTION"
    assert st["canary_helpful_count"]==3
    con.close()

def test_two_helpful_one_neutral_can_pass_canary(tmp_path):
    con=init_db(tmp_path/"neutral.sqlite3")
    _profile(con); _start_canary(con,3)
    verdicts=["RECOMMENDATION_HELPFUL","RUNTIME_SUCCESS_SHADOW_MIXED","RECOMMENDATION_HELPFUL"]
    for scope,v in enumerate(verdicts,1):
        c=_challenge(con,scope)
        resolve_selection(con,ROOT,c["challenge_id"],REC,BASE,None)
        st=observe_runtime_verdict(con,c["challenge_id"],v)
    assert st["mode"]=="READY_FOR_PROMOTION"
    assert st["canary_helpful_count"]==2
    assert st["canary_neutral_count"]==1
    con.close()

def test_harmful_canary_result_immediately_rolls_back(tmp_path):
    con=init_db(tmp_path/"canary-rollback.sqlite3")
    _profile(con); _start_canary(con,3)
    c=_challenge(con,1)
    resolve_selection(con,ROOT,c["challenge_id"],REC,BASE,None)
    st=observe_runtime_verdict(con,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert st["mode"]=="ROLLED_BACK"
    assert st["canary_harmful_count"]==1
    assert st["rollback_reason"]
    con.close()

def test_human_final_review_required_before_promotion(tmp_path):
    con=init_db(tmp_path/"human-final.sqlite3")
    _profile(con); _start_canary(con,1)
    c=_challenge(con,1)
    resolve_selection(con,ROOT,c["challenge_id"],REC,BASE,None)
    # max=1 means one helpful is sufficient because min helpful is capped by max.
    st=observe_runtime_verdict(con,c["challenge_id"],"RECOMMENDATION_HELPFUL")
    assert st["mode"]=="READY_FOR_PROMOTION"
    _version_promotion_ready(con)
    st=final_policy_review(con,ROOT,"PROMOTE","policy-owner","canary passed")
    assert st["mode"]=="PROMOTED"
    assert st["promoted_at"]
    con.close()

def test_promoted_policy_defaults_to_recommendation(tmp_path):
    con=init_db(tmp_path/"promoted.sqlite3")
    _profile(con); _start_canary(con,1)
    c1=_challenge(con,1)
    resolve_selection(con,ROOT,c1["challenge_id"],REC,BASE,None)
    observe_runtime_verdict(con,c1["challenge_id"],"RECOMMENDATION_HELPFUL")
    _version_promotion_ready(con)
    final_policy_review(con,ROOT,"PROMOTE","owner","promote")
    c2=_challenge(con,2)
    r=resolve_selection(con,ROOT,c2["challenge_id"],REC,BASE,None)
    assert r["policy_mode"]=="PROMOTED"
    assert r["selection_source"]=="PROMOTED_DEFAULT"
    assert r["selected_side"]=="RECOMMENDATION"
    con.close()

def test_harmful_promoted_runtime_immediately_rolls_back(tmp_path):
    con=init_db(tmp_path/"promoted-rollback.sqlite3")
    _profile(con); _start_canary(con,1)
    c1=_challenge(con,1)
    resolve_selection(con,ROOT,c1["challenge_id"],REC,BASE,None)
    observe_runtime_verdict(con,c1["challenge_id"],"RECOMMENDATION_HELPFUL")
    _version_promotion_ready(con)
    final_policy_review(con,ROOT,"PROMOTE","owner","promote")
    c2=_challenge(con,2)
    resolve_selection(con,ROOT,c2["challenge_id"],REC,BASE,None)
    st=observe_runtime_verdict(con,c2["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert st["mode"]=="ROLLED_BACK"
    c3=_challenge(con,3)
    r=resolve_selection(con,ROOT,c3["challenge_id"],REC,BASE,None)
    assert r["selected_side"]=="BASELINE"
    assert r["policy_mode"]=="ROLLED_BACK"
    con.close()

def test_manual_rollback_forces_baseline(tmp_path):
    con=init_db(tmp_path/"manual.sqlite3")
    _profile(con); _start_canary(con,1)
    c1=_challenge(con,1)
    resolve_selection(con,ROOT,c1["challenge_id"],REC,BASE,None)
    observe_runtime_verdict(con,c1["challenge_id"],"RECOMMENDATION_HELPFUL")
    _version_promotion_ready(con)
    final_policy_review(con,ROOT,"PROMOTE","owner","promote")
    st=manual_rollback(con,ROOT,"owner","operator safety rollback")
    assert st["mode"]=="ROLLED_BACK"
    c2=_challenge(con,2)
    assert resolve_selection(con,ROOT,c2["challenge_id"],REC,BASE,None)["selected_side"]=="BASELINE"
    con.close()

def test_policy_status_has_state_candidate_assignment_and_events(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    _profile(con); _start_canary(con,1)
    c=_challenge(con,1)
    resolve_selection(con,ROOT,c["challenge_id"],REC,BASE,None)
    st=status(con)
    assert st["policy_version"]=="v0.73"
    assert len(st["states"])==1
    assert len(st["candidates"])==1
    assert len(st["assignments"])==1
    assert len(st["events"])>=2
    con.close()
