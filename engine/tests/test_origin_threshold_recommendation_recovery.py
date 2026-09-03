import pytest

from src.database import init_db
from src.origin_threshold_recommendation_policy import (
    _ensure_state, manual_rollback, review_candidate, evaluate_candidate
)
from src.origin_threshold_recommendation_recovery import (
    cases, attribute_failure, add_remediation, review_remediation,
    add_evidence, evaluate, review_recanary, status
)

ROOT="SOURCE_LOCAL_RECURRENCE"

def _quality_profile(con):
    con.execute("""INSERT INTO origin_threshold_architecture_recommendation_quality_profiles(
      root_cause_type,challenge_count,accepted_count,baseline_selected_count,hold_count,
      runtime_decisive_count,recommendation_helpful_count,recommendation_harmful_count,
      recommendation_neutral_count,acceptance_rate,helpful_rate,harmful_rate,
      confidence_band,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ROOT,5,4,1,0,5,4,0,1,.8,.8,0.0,"ESTABLISHED","2026-09-02T00:00:00+00:00"))
    con.commit()

def _rollback(con,reason="harmful recommendation runtime verdict"):
    _ensure_state(con,ROOT)
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
                   SET mode='PROMOTED' WHERE root_cause_type=?""",(ROOT,))
    con.commit()
    return manual_rollback(con,ROOT,"owner",reason)

def _effective_remediation(con,case_id):
    r=add_remediation(con,case_id,"RANKING_LOGIC_FIX",f"ALG-{case_id}","engineer","fix")
    reviewed=review_remediation(con,r["policy_recovery_remediation_id"],
                                "EFFECTIVE","reviewer","verified")
    from src.origin_threshold_recommendation_versioning import (
        propose_successor,approve_successor
    )
    propose_successor(
        con,case_id,f"alg-recovery-{case_id}","engineer",
        r["policy_recovery_remediation_id"],"new version after rollback",
        code_ref=f"code-{case_id}",config_ref=f"config-{case_id}")
    approve_successor(con,case_id,"reviewer","new algorithm version verified")
    return reviewed

def _evidence(con,case_id,n,helpful, harmful=0):
    for i in range(n):
        if i < helpful:
            verdict="RECOMMENDATION_HELPFUL"
        elif i < helpful+harmful:
            verdict="RECOMMENDATION_HARMFUL"
        else:
            verdict="NEUTRAL"
        add_evidence(con,case_id,1000+i,verdict,True,"fresh challenge")

def test_failure_attribution_for_harmful_runtime():
    assert attribute_failure("harmful recommendation runtime verdict",
                             "RECOMMENDATION_HARMFUL")=="RUNTIME_HARMFUL_RECOMMENDATION"

def test_rollback_opens_recovery_case(tmp_path):
    con=init_db(tmp_path/"open.sqlite3")
    st=_rollback(con)
    assert st["mode"]=="ROLLED_BACK"
    cs=cases(con,ROOT)
    assert len(cs)==1
    assert cs[0]["rollback_number"]==1
    assert cs[0]["failure_type"]=="UNRESOLVED_RECOMMENDATION_POLICY_FAILURE" or cs[0]["failure_type"]=="RUNTIME_HARMFUL_RECOMMENDATION"
    con.close()

def test_direct_candidate_canary_bypass_is_blocked_after_rollback(tmp_path):
    con=init_db(tmp_path/"bypass.sqlite3")
    _quality_profile(con)
    _rollback(con)
    c=evaluate_candidate(con,ROOT,persist=True)
    assert c["status"]=="READY_FOR_POLICY_REVIEW"
    with pytest.raises(ValueError,match="rollback recovery"):
        review_candidate(con,c["policy_candidate_id"],"APPROVE_CANARY",
                         "owner","should be blocked",3)
    con.close()

def test_first_rollback_requires_5_decisive_4_helpful(tmp_path):
    con=init_db(tmp_path/"req1.sqlite3")
    _rollback(con)
    case_id=cases(con,ROOT)[0]["policy_recovery_case_id"]
    _effective_remediation(con,case_id)
    _evidence(con,case_id,4,4)
    ev=evaluate(con,case_id,persist=False)
    assert ev["required_decisive_count"]==5
    assert ev["required_helpful_count"]==4
    assert ev["status"]=="WARMING"
    con.close()

def test_first_rollback_reaches_ready_for_recanary(tmp_path):
    con=init_db(tmp_path/"ready1.sqlite3")
    _rollback(con)
    case_id=cases(con,ROOT)[0]["policy_recovery_case_id"]
    _effective_remediation(con,case_id)
    _evidence(con,case_id,5,4)
    ev=evaluate(con,case_id,persist=False)
    assert ev["status"]=="READY_FOR_RECANARY"
    assert ev["harmful_count"]==0
    con.close()

def test_harmful_fresh_shadow_blocks_recovery(tmp_path):
    con=init_db(tmp_path/"harmful.sqlite3")
    _rollback(con)
    case_id=cases(con,ROOT)[0]["policy_recovery_case_id"]
    _effective_remediation(con,case_id)
    _evidence(con,case_id,5,4,harmful=1)
    ev=evaluate(con,case_id,persist=False)
    assert ev["status"]=="BLOCKED"
    assert ev["harmful_count"]==1
    con.close()

def test_effective_remediation_is_required(tmp_path):
    con=init_db(tmp_path/"rem.sqlite3")
    _rollback(con)
    case_id=cases(con,ROOT)[0]["policy_recovery_case_id"]
    _evidence(con,case_id,5,5)
    ev=evaluate(con,case_id,persist=False)
    assert ev["remediation_effective"] is False
    assert ev["status"]=="WARMING"
    con.close()

def test_human_recanary_approval_restores_canary_mode(tmp_path):
    con=init_db(tmp_path/"recanary.sqlite3")
    _rollback(con)
    case_id=cases(con,ROOT)[0]["policy_recovery_case_id"]
    _effective_remediation(con,case_id)
    _evidence(con,case_id,5,5)
    r=review_recanary(con,case_id,"APPROVE_RECANARY","owner","fresh evidence passed",3)
    assert r["case"]["status"]=="RECANARY_APPROVED"
    st=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_states
                      WHERE root_cause_type=?""",(ROOT,)).fetchone()
    assert st["mode"]=="CANARY"
    assert st["canary_assigned_count"]==0
    con.close()

def test_second_rollback_has_stronger_8_7_requirements(tmp_path):
    con=init_db(tmp_path/"second.sqlite3")
    _rollback(con,"first failure")
    # synthetic recovery and re-promotion, then rollback again
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
                   SET mode='PROMOTED' WHERE root_cause_type=?""",(ROOT,))
    con.commit()
    manual_rollback(con,ROOT,"owner","second failure")
    cs=cases(con,ROOT)
    assert len(cs)==2
    ev=evaluate(con,cs[-1]["policy_recovery_case_id"],persist=False)
    assert ev["rollback_number"]==2
    assert ev["required_decisive_count"]==8
    assert ev["required_helpful_count"]==7
    con.close()

def test_third_rollback_enters_long_term_shadow_only(tmp_path):
    con=init_db(tmp_path/"third.sqlite3")
    for n in range(3):
        _ensure_state(con,ROOT)
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
                       SET mode='PROMOTED' WHERE root_cause_type=?""",(ROOT,))
        con.commit()
        manual_rollback(con,ROOT,"owner",f"failure {n+1}")
    st=con.execute("""SELECT mode FROM origin_threshold_recommendation_policy_states
                      WHERE root_cause_type=?""",(ROOT,)).fetchone()
    assert st["mode"]=="LONG_TERM_SHADOW_ONLY"
    ev=evaluate(con,cases(con,ROOT)[-1]["policy_recovery_case_id"],persist=False)
    assert ev["required_decisive_count"]==12
    assert ev["required_helpful_count"]==11
    assert ev["architecture_review_required"] is True
    con.close()

def test_third_rollback_requires_architecture_exception_for_recanary(tmp_path):
    con=init_db(tmp_path/"arch.sqlite3")
    for n in range(3):
        _ensure_state(con,ROOT)
        con.execute("""UPDATE origin_threshold_recommendation_policy_states
                       SET mode='PROMOTED' WHERE root_cause_type=?""",(ROOT,))
        con.commit()
        manual_rollback(con,ROOT,"owner",f"failure {n+1}")
    case_id=cases(con,ROOT)[-1]["policy_recovery_case_id"]
    _effective_remediation(con,case_id)
    _evidence(con,case_id,12,12)
    with pytest.raises(ValueError,match="architecture_exception"):
        review_recanary(con,case_id,"APPROVE_RECANARY","chief","needs exception",3)
    r=review_recanary(con,case_id,"APPROVE_RECANARY","chief",
                      "architecture exception approved",3,architecture_exception=True)
    assert r["case"]["status"]=="RECANARY_APPROVED"
    con.close()

def test_recovery_evidence_must_be_unique_per_challenge(tmp_path):
    con=init_db(tmp_path/"unique.sqlite3")
    _rollback(con)
    case_id=cases(con,ROOT)[0]["policy_recovery_case_id"]
    add_evidence(con,case_id,1,"RECOMMENDATION_HELPFUL",True)
    with pytest.raises(Exception):
        add_evidence(con,case_id,1,"RECOMMENDATION_HELPFUL",True)
    con.close()

def test_ineffective_remediation_does_not_unlock(tmp_path):
    con=init_db(tmp_path/"ineff.sqlite3")
    _rollback(con)
    case_id=cases(con,ROOT)[0]["policy_recovery_case_id"]
    r=add_remediation(con,case_id,"RANKING_LOGIC_FIX","ALG-X","engineer","attempt")
    review_remediation(con,r["policy_recovery_remediation_id"],
                       "INEFFECTIVE","reviewer","failed")
    _evidence(con,case_id,5,5)
    ev=evaluate(con,case_id,persist=False)
    assert ev["remediation_effective"] is False
    con.close()

def test_recovery_status_exposes_cases(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    _rollback(con)
    st=status(con)
    assert st["policy_version"]=="v0.73"
    assert len(st["cases"])==1
    con.close()

def test_recovery_review_is_audited(tmp_path):
    con=init_db(tmp_path/"audit.sqlite3")
    _rollback(con)
    case_id=cases(con,ROOT)[0]["policy_recovery_case_id"]
    _effective_remediation(con,case_id)
    _evidence(con,case_id,5,5)
    review_recanary(con,case_id,"APPROVE_RECANARY","owner","approved",2)
    row=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_recovery_reviews""").fetchone()
    assert row["decision"]=="APPROVE_RECANARY"
    assert row["reviewer"]=="owner"
    con.close()
