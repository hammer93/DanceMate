import pytest

from src.database import init_db
from src.origin_threshold_recommendation_versioning import register_version,versions
from src.origin_threshold_recommendation_challenge import create_challenge
from src.origin_threshold_recommendation_supersede_guard import (
    evaluate_fallback,execute_fallback,evaluations,fallbacks,events,status
)
from src.origin_threshold_recommendation_policy import _ensure_state,observe_runtime_verdict
from src.origin_threshold_recommendation_recovery import cases

ROOT="SOURCE_LOCAL_RECURRENCE"
CTX="SOURCE|SRC-A|FACEBOOK|RULE|*|ALT0"

def _rec():
    return {
        "selected_steps":["DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"],
        "source":"CONTEXT_COMPARATIVE_RANKING",
        "comparative_score":.8,
        "context_signature":CTX
    }

def _profile(con,vid,*,decisive=5,production=5,helpful=4,harmful=0,
             survival=60.0,safety=None,memory=None,context=CTX):
    if safety is None:
        safety="UNSAFE" if harmful else "SAFE"
    if memory is None:
        memory="VERSION_ROLLBACK_EVIDENCE" if harmful else "VERSION_PRODUCTION_PROVEN"
    con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_version_profiles(
      algorithm_version_id,root_cause_type,context_signature,total_runtime_count,
      decisive_runtime_count,canary_runtime_count,production_runtime_count,
      helpful_count,harmful_count,neutral_count,rollback_count,helpful_rate,
      harmful_rate,median_survival_days,confidence_band,safety_band,
      promotion_memory_status,reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (vid,ROOT,context,decisive,decisive,0,production,helpful,harmful,
       max(0,decisive-helpful-harmful),harmful,
       helpful/decisive if decisive else None,harmful/decisive if decisive else None,
       survival,"ESTABLISHED" if decisive>=5 else "EMERGING",
       safety,memory,'[]',"2026-09-02T00:00:00+00:00"))
    con.commit()

def _setup(con,*,fallback_safe=True,context=CTX,parent=True):
    old=register_version(
        con,ROOT,"alg-v1","engineer",code_ref="v1",config_ref="v1",status="SUPERSEDED")
    new=register_version(
        con,ROOT,"alg-v2","engineer",
        parent_algorithm_version_id=old["algorithm_version_id"] if parent else None,
        code_ref="v2",config_ref="v2",status="PROMOTED")
    if fallback_safe:
        _profile(con,old["algorithm_version_id"],context=context)
    _ensure_state(con,ROOT)
    con.execute("""UPDATE origin_threshold_recommendation_policy_states
                   SET mode='PROMOTED' WHERE root_cause_type=?""",(ROOT,))
    con.commit()
    c=create_challenge(con,1,ROOT,context,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    return old,new,c

def test_safe_superseded_version_is_ready_for_fallback(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    old,new,c=_setup(con)
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL",persist=True)
    assert ev["status"]=="READY_FOR_AUTOMATIC_VERSION_FALLBACK"
    assert ev["fallback_algorithm_version_id"]==old["algorithm_version_id"]
    assert ev["action"]=="FALLBACK_TO_SUPERSEDED_VERSION"
    con.close()

def test_no_superseded_version_blocks_fallback(tmp_path):
    con=init_db(tmp_path/"none.sqlite3")
    new=register_version(con,ROOT,"alg-v2","engineer",code_ref="v2",config_ref="v2",status="PROMOTED")
    _ensure_state(con,ROOT)
    con.execute("UPDATE origin_threshold_recommendation_policy_states SET mode='PROMOTED' WHERE root_cause_type=?",(ROOT,))
    con.commit()
    c=create_challenge(con,1,ROOT,CTX,_rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert ev["action"]=="DETERMINISTIC_BASELINE_ROLLBACK"
    con.close()

def test_missing_comparable_context_blocks_fallback(tmp_path):
    con=init_db(tmp_path/"ctx.sqlite3")
    old,new,c=_setup(con,fallback_safe=False)
    _profile(con,old["algorithm_version_id"],context="PLATFORM|*|NAVER|RULE|*|ALT1")
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert any("comparable profile" in r for r in ev["reasons"])
    con.close()

def test_harmful_old_version_blocks_fallback(tmp_path):
    con=init_db(tmp_path/"harm.sqlite3")
    old,new,c=_setup(con,fallback_safe=False)
    _profile(con,old["algorithm_version_id"],helpful=3,harmful=1,safety="UNSAFE")
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert any("unsafe/harmful" in r for r in ev["reasons"])
    con.close()

def test_low_old_version_sample_blocks_fallback(tmp_path):
    con=init_db(tmp_path/"low.sqlite3")
    old,new,c=_setup(con,fallback_safe=False)
    _profile(con,old["algorithm_version_id"],decisive=2,production=2,helpful=2,survival=60)
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert any("fallback decisive" in r for r in ev["reasons"])
    con.close()

def test_short_survival_blocks_fallback(tmp_path):
    con=init_db(tmp_path/"survival.sqlite3")
    old,new,c=_setup(con,fallback_safe=False)
    _profile(con,old["algorithm_version_id"],survival=10.0)
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert any("median survival" in r for r in ev["reasons"])
    con.close()

def test_unproven_memory_blocks_fallback(tmp_path):
    con=init_db(tmp_path/"memory.sqlite3")
    old,new,c=_setup(con,fallback_safe=False)
    _profile(con,old["algorithm_version_id"],memory="VERSION_WARMING")
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert any("promotion memory" in r for r in ev["reasons"])
    con.close()

def test_non_harmful_verdict_never_triggers_fallback(tmp_path):
    con=init_db(tmp_path/"nonharm.sqlite3")
    old,new,c=_setup(con)
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HELPFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    con.close()

def test_execute_fallback_promotes_old_and_fails_new(tmp_path):
    con=init_db(tmp_path/"execute.sqlite3")
    old,new,c=_setup(con)
    r=execute_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert r["executed"] is True
    vs={v["version_label"]:v for v in versions(con,ROOT)}
    assert vs["alg-v1"]["status"]=="PROMOTED"
    assert vs["alg-v2"]["status"]=="FAILED"
    assert len(fallbacks(con,ROOT))==1
    con.close()

def test_execute_fallback_keeps_policy_promoted(tmp_path):
    con=init_db(tmp_path/"policy.sqlite3")
    old,new,c=_setup(con)
    r=execute_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    st=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_states
                      WHERE root_cause_type=?""",(ROOT,)).fetchone()
    assert r["policy_mode"]=="PROMOTED"
    assert st["mode"]=="PROMOTED"
    con.close()

def test_execute_fallback_opens_recovery_for_failed_new_version(tmp_path):
    con=init_db(tmp_path/"recovery.sqlite3")
    old,new,c=_setup(con)
    r=execute_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    cs=cases(con,ROOT)
    assert len(cs)==1
    link=con.execute("""SELECT * FROM origin_threshold_recommendation_recovery_version_links
                        WHERE policy_recovery_case_id=?""",
                     (cs[0]["policy_recovery_case_id"],)).fetchone()
    assert link["failed_algorithm_version_id"]==new["algorithm_version_id"]
    assert r["recovery_case_id"]==cs[0]["policy_recovery_case_id"]
    con.close()

def test_observe_runtime_verdict_uses_version_fallback_before_baseline(tmp_path):
    con=init_db(tmp_path/"observe.sqlite3")
    old,new,c=_setup(con)
    st=observe_runtime_verdict(con,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert st["mode"]=="PROMOTED"
    assert st["version_fallback"]["executed"] is True
    vs={v["version_label"]:v for v in versions(con,ROOT)}
    assert vs["alg-v1"]["status"]=="PROMOTED"
    assert vs["alg-v2"]["status"]=="FAILED"
    con.close()

def test_unsafe_fallback_causes_existing_baseline_rollback(tmp_path):
    con=init_db(tmp_path/"baseline.sqlite3")
    old,new,c=_setup(con,fallback_safe=False)
    _profile(con,old["algorithm_version_id"],helpful=3,harmful=1,safety="UNSAFE")
    st=observe_runtime_verdict(con,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    assert st["mode"]=="ROLLED_BACK"
    assert st["rollback_reason"]
    con.close()

def test_third_or_later_rollback_cannot_auto_fallback(tmp_path):
    con=init_db(tmp_path/"third.sqlite3")
    old,new,c=_setup(con)
    # Two prior recovery cases make this the third failure generation.
    for n in (1,2):
        con.execute("""INSERT INTO origin_threshold_recommendation_policy_recovery_cases(
          root_cause_type,rollback_number,failure_type,status,rollback_reason,opened_at)
          VALUES(?,?,?,?,?,?)""",
          (ROOT,n,"RUNTIME_HARMFUL_RECOMMENDATION","OPEN",f"old-{n}",
           "2026-09-01T00:00:00+00:00"))
    con.commit()
    ev=evaluate_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL",persist=False)
    assert ev["status"]=="FALLBACK_BLOCKED"
    assert any("third-or-later" in r for r in ev["reasons"])
    con.close()

def test_status_persists_guard_fallback_and_events(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    old,new,c=_setup(con)
    execute_fallback(con,ROOT,c["challenge_id"],"RECOMMENDATION_HARMFUL")
    s=status(con)
    assert s["policy_version"]=="v0.73"
    assert len(s["evaluations"])==1
    assert len(s["fallbacks"])==1
    assert len(s["events"])==1
    con.close()
