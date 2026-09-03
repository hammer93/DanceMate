import pytest

from src.database import init_db
from src.origin_threshold_recommendation_versioning import (
    register_version,versions,mark_status
)
from src.origin_threshold_recommendation_version_promotion import (
    evaluate_gate,human_review,promotion_ready,gates,comparisons,reviews,status
)
from src.origin_threshold_recommendation_policy import (
    _ensure_state,final_policy_review
)

ROOT="SOURCE_LOCAL_RECURRENCE"
CTX="SOURCE|SRC-A|FACEBOOK|RULE|*|ALT0"

def _profile(con,vid,*,canary=3,production=0,helpful=3,harmful=0,
             neutral=0,survival=90.0,context=CTX,safety=None):
    decisive=canary+production
    if safety is None:
        safety="UNSAFE" if harmful else ("SAFE" if decisive>=3 and helpful>=2 else "WATCH")
    memory=("VERSION_ROLLBACK_EVIDENCE" if harmful else
            "VERSION_PRODUCTION_PROVEN" if production>=5 and helpful>=3 else
            "VERSION_CANARY_PROVEN" if canary>=3 and helpful>=2 else
            "VERSION_WARMING")
    con.execute("""INSERT OR REPLACE INTO origin_threshold_recommendation_algorithm_version_profiles(
      algorithm_version_id,root_cause_type,context_signature,total_runtime_count,
      decisive_runtime_count,canary_runtime_count,production_runtime_count,
      helpful_count,harmful_count,neutral_count,rollback_count,helpful_rate,
      harmful_rate,median_survival_days,confidence_band,safety_band,
      promotion_memory_status,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (vid,ROOT,context,decisive,decisive,canary,production,helpful,harmful,neutral,
       harmful,helpful/decisive if decisive else None,harmful/decisive if decisive else None,
       survival,"ESTABLISHED" if decisive>=5 else "EMERGING" if decisive>=3 else "LOW_DATA",
       safety,memory,'[]',"2026-09-02T00:00:00+00:00"))
    con.commit()

def _version(con,label,status="CANARY"):
    return register_version(
        con,ROOT,label,"engineer",code_ref=label+"-code",
        config_ref=label+"-cfg",status=status)

def test_no_version_profile_is_not_promotable(tmp_path):
    con=init_db(tmp_path/"no.sqlite3")
    v=_version(con,"alg-v2")
    g=evaluate_gate(con,v["algorithm_version_id"],persist=False)
    assert g["status"]=="NO_VERSION_PROFILE"
    assert g["supersede_allowed"] is False
    con.close()

def test_harmful_candidate_version_is_blocked(tmp_path):
    con=init_db(tmp_path/"harm.sqlite3")
    v=_version(con,"alg-v2")
    _profile(con,v["algorithm_version_id"],helpful=2,harmful=1)
    g=evaluate_gate(con,v["algorithm_version_id"],persist=False)
    assert g["status"]=="BLOCKED"
    assert any("harmful" in r for r in g["reasons"])
    con.close()

def test_canary_below_three_is_blocked(tmp_path):
    con=init_db(tmp_path/"small.sqlite3")
    v=_version(con,"alg-v2")
    _profile(con,v["algorithm_version_id"],canary=2,helpful=2)
    g=evaluate_gate(con,v["algorithm_version_id"],persist=False)
    assert g["status"]=="BLOCKED"
    con.close()

def test_canary_proven_without_incumbent_is_ready_for_human_promotion(tmp_path):
    con=init_db(tmp_path/"first.sqlite3")
    v=_version(con,"alg-v2")
    _profile(con,v["algorithm_version_id"],canary=3,helpful=3)
    g=evaluate_gate(con,v["algorithm_version_id"],persist=True)
    assert g["status"]=="READY_FOR_HUMAN_PROMOTION"
    assert g["incumbent_algorithm_version_id"] is None
    assert g["candidate_score"]>=.45
    con.close()

def test_human_promotion_review_is_required(tmp_path):
    con=init_db(tmp_path/"human.sqlite3")
    v=_version(con,"alg-v2")
    _profile(con,v["algorithm_version_id"],canary=3,helpful=3)
    r=promotion_ready(con,v["algorithm_version_id"])
    assert r["ready"] is False
    human_review(con,v["algorithm_version_id"],"PROMOTE","owner","version evidence passed")
    r=promotion_ready(con,v["algorithm_version_id"])
    assert r["ready"] is True
    con.close()

def test_equal_candidate_and_incumbent_keeps_current_version(tmp_path):
    con=init_db(tmp_path/"equal.sqlite3")
    incumbent=_version(con,"alg-v1","PROMOTED")
    candidate=_version(con,"alg-v2","CANARY")
    _profile(con,incumbent["algorithm_version_id"],production=5,canary=0,helpful=5)
    _profile(con,candidate["algorithm_version_id"],canary=5,helpful=5)
    g=evaluate_gate(con,candidate["algorithm_version_id"],persist=True)
    assert g["status"]=="KEEP_CURRENT_VERSION"
    assert g["score_margin"]<.10
    assert len(comparisons(con,candidate["algorithm_version_id"]))==1
    con.close()

def test_candidate_with_clear_margin_is_ready_for_supersede_review(tmp_path):
    con=init_db(tmp_path/"margin.sqlite3")
    incumbent=_version(con,"alg-v1","PROMOTED")
    candidate=_version(con,"alg-v2","CANARY")
    _profile(con,incumbent["algorithm_version_id"],production=3,canary=0,helpful=3,survival=30)
    _profile(con,candidate["algorithm_version_id"],canary=5,helpful=5,survival=90)
    g=evaluate_gate(con,candidate["algorithm_version_id"],persist=True)
    assert g["status"]=="READY_FOR_SUPERSEDE_REVIEW"
    assert g["score_margin"]>=.10
    assert g["supersede_allowed"] is True
    con.close()

def test_incumbent_without_matching_context_is_conservative_hold(tmp_path):
    con=init_db(tmp_path/"context.sqlite3")
    incumbent=_version(con,"alg-v1","PROMOTED")
    candidate=_version(con,"alg-v2","CANARY")
    _profile(con,incumbent["algorithm_version_id"],production=5,canary=0,helpful=5,
             context="PLATFORM|*|NAVER|RULE|*|ALT1")
    _profile(con,candidate["algorithm_version_id"],canary=5,helpful=5,context=CTX)
    g=evaluate_gate(con,candidate["algorithm_version_id"],persist=False)
    assert g["status"]=="KEEP_CURRENT_VERSION"
    assert any("comparable" in r for r in g["reasons"])
    con.close()

def test_incumbent_low_comparable_sample_is_kept(tmp_path):
    con=init_db(tmp_path/"inc-low.sqlite3")
    incumbent=_version(con,"alg-v1","PROMOTED")
    candidate=_version(con,"alg-v2","CANARY")
    _profile(con,incumbent["algorithm_version_id"],production=2,canary=0,helpful=2)
    _profile(con,candidate["algorithm_version_id"],canary=5,helpful=5)
    g=evaluate_gate(con,candidate["algorithm_version_id"],persist=False)
    assert g["status"]=="KEEP_CURRENT_VERSION"
    assert any("conservative hold" in r for r in g["reasons"])
    con.close()

def test_unsafe_incumbent_can_be_superseded_by_safe_candidate(tmp_path):
    con=init_db(tmp_path/"unsafe-inc.sqlite3")
    incumbent=_version(con,"alg-v1","PROMOTED")
    candidate=_version(con,"alg-v2","CANARY")
    _profile(con,incumbent["algorithm_version_id"],production=5,canary=0,
             helpful=3,harmful=1,survival=20)
    _profile(con,candidate["algorithm_version_id"],canary=3,helpful=3,survival=90)
    g=evaluate_gate(con,candidate["algorithm_version_id"],persist=False)
    assert g["status"]=="READY_FOR_SUPERSEDE_REVIEW"
    assert g["supersede_allowed"] is True
    con.close()

def test_human_promote_cannot_override_keep_current_gate(tmp_path):
    con=init_db(tmp_path/"override.sqlite3")
    incumbent=_version(con,"alg-v1","PROMOTED")
    candidate=_version(con,"alg-v2","CANARY")
    _profile(con,incumbent["algorithm_version_id"],production=5,canary=0,helpful=5)
    _profile(con,candidate["algorithm_version_id"],canary=5,helpful=5)
    with pytest.raises(ValueError,match="not ready"):
        human_review(con,candidate["algorithm_version_id"],"PROMOTE","owner","force promote")
    con.close()

def test_failed_algorithm_version_can_never_pass_gate(tmp_path):
    con=init_db(tmp_path/"failed.sqlite3")
    v=_version(con,"alg-v2","CANARY")
    _profile(con,v["algorithm_version_id"],canary=5,helpful=5)
    mark_status(con,v["algorithm_version_id"],"FAILED","guard","runtime failure")
    g=evaluate_gate(con,v["algorithm_version_id"],persist=False)
    assert g["status"]=="BLOCKED"
    con.close()

def test_final_policy_promotion_requires_explicit_version_review(tmp_path):
    con=init_db(tmp_path/"final-gate.sqlite3")
    v=_version(con,"alg-v2","CANARY")
    _profile(con,v["algorithm_version_id"],canary=3,helpful=3)
    st=_ensure_state(con,ROOT)
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
                   SET mode='READY_FOR_PROMOTION' WHERE root_cause_type=?""",(ROOT,))
    con.commit()
    with pytest.raises(ValueError,match="version-aware promotion gate"):
        final_policy_review(con,ROOT,"PROMOTE","policy-owner","policy canary passed")
    con.close()

def test_final_policy_promotion_supersedes_incumbent_only_after_version_gate(tmp_path):
    con=init_db(tmp_path/"supersede.sqlite3")
    incumbent=_version(con,"alg-v1","PROMOTED")
    candidate=_version(con,"alg-v2","CANARY")
    _profile(con,incumbent["algorithm_version_id"],production=3,canary=0,helpful=3,survival=25)
    _profile(con,candidate["algorithm_version_id"],canary=5,helpful=5,survival=90)
    # Make current_version resolve candidate CANARY through a candidate link not required:
    con.execute("""INSERT INTO origin_threshold_recommendation_policy_states(
      root_cause_type,mode,canary_max_assignments,updated_at)
      VALUES(?,?,?,?)""",(ROOT,"READY_FOR_PROMOTION",3,"2026-09-02T00:00:00+00:00"))
    con.execute("""INSERT INTO origin_threshold_recommendation_policy_candidates(
      root_cause_type,quality_profile_id,runtime_decisive_count,helpful_rate,harmful_rate,
      acceptance_rate,baseline_selected_count,status,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",(ROOT,1,5,.8,0,.8,1,"READY_FOR_POLICY_REVIEW",'[]',
                                      "2026-09-02T00:00:00+00:00"))
    cid=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.execute("UPDATE origin_threshold_recommendation_policy_states SET candidate_id=? WHERE root_cause_type=?",(cid,ROOT))
    con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_lineage(
      algorithm_version_id,root_cause_type,entity_type,entity_id,relation_type,created_at)
      VALUES(?,?,?,?,?,?)""",(candidate["algorithm_version_id"],ROOT,"POLICY_CANDIDATE",cid,
                              "CANDIDATE_FOR","2026-09-02T00:00:00+00:00"))
    con.commit()
    human_review(con,candidate["algorithm_version_id"],"PROMOTE","version-owner","candidate clearly superior")
    st=final_policy_review(con,ROOT,"PROMOTE","policy-owner","version gate approved")
    vs={v["version_label"]:v for v in versions(con,ROOT)}
    assert st["mode"]=="PROMOTED"
    assert vs["alg-v1"]["status"]=="SUPERSEDED"
    assert vs["alg-v2"]["status"]=="PROMOTED"
    con.close()

def test_status_persists_gate_comparison_review_and_events(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    incumbent=_version(con,"alg-v1","PROMOTED")
    candidate=_version(con,"alg-v2","CANARY")
    _profile(con,incumbent["algorithm_version_id"],production=3,canary=0,helpful=3,survival=20)
    _profile(con,candidate["algorithm_version_id"],canary=5,helpful=5,survival=90)
    human_review(con,candidate["algorithm_version_id"],"PROMOTE","owner","superior")
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["gates"])>=1
    assert len(s["comparisons"])>=1
    assert len(s["reviews"])==1
    assert len(s["events"])==1
    con.close()
