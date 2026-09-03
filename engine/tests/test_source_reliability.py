import pytest

from src.database import (
    init_db,upsert_decision_evidence_cluster,persist_root_cause_attribution,
    persist_source_reliability_observation
)
from src.source_reliability import (
    recompute_all_profiles,reliability_profiles,reliability_observations,
    record_success,evaluate_verification_policy,verification_decisions,
    start_canary,rollback_canary,canaries,canary_events
)

SOURCE="SRC-D-001"
RULE="CANCELLATION_REFRESH_WINDOW"

def _critical_attribution(con, *, cluster_key, source_id=SOURCE, rule_key=RULE):
    cid,_=upsert_decision_evidence_cluster(
        con,cluster_key=cluster_key,event_instance_id=1,
        goal_profile="FIELD_QUALITY",proposed_event_truth="CANCELLED",
        critical_error_type="CANCELLATION_MISS",status="CONFIRMED_CASE",
        severity="CRITICAL",evidence_count=1,independent_source_count=1,
        confirmed_count=1,rejected_count=0,resolution_confidence="HUMAN_CONFIRMED",
        resolved_outcome="FAILURE",resolved_by="HUMAN_CONFIRMATION")
    aid=persist_root_cause_attribution(
        con,cluster_id=cid,category="FRESHNESS_DETECTION_MISS",
        component="EVENT_LIFECYCLE",source_kind="EVENT_REFRESH_CHECK",
        source_id=source_id,rule_key=rule_key,confidence="HIGH",
        status="CONFIRMED_ATTRIBUTION",rationale=["confirmed miss"],
        attributed_by="tester")
    return cid,aid

def test_one_confirmed_critical_failure_moves_profile_to_watch(tmp_path):
    con=init_db(tmp_path/"watch.sqlite3")
    _critical_attribution(con,cluster_key="1|CANCELLED|CANCELLATION_MISS")
    r=recompute_all_profiles(con)
    assert r["derived"]["created_count"]==1
    p=reliability_profiles(con,SOURCE)[0]
    assert p["score"]==pytest.approx(.80)
    assert p["band"]=="WATCH"
    assert p["critical_failure_count"]==1
    con.close()

def test_two_confirmed_critical_failures_move_profile_to_degraded(tmp_path):
    con=init_db(tmp_path/"degraded.sqlite3")
    _critical_attribution(con,cluster_key="1|CANCELLED|CANCELLATION_MISS")
    _critical_attribution(con,cluster_key="2|CANCELLED|CANCELLATION_MISS")
    recompute_all_profiles(con)
    p=reliability_profiles(con,SOURCE)[0]
    assert p["score"]==pytest.approx(.60)
    assert p["band"]=="DEGRADED"
    con.close()

def test_unattributable_source_does_not_penalize_any_source(tmp_path):
    con=init_db(tmp_path/"unattributed.sqlite3")
    _critical_attribution(
        con,cluster_key="1|EVENT_DID_NOT_OCCUR|FALSE_VERIFIED",
        source_id=None,rule_key="VERIFIED_EVENT_EXISTENCE")
    r=recompute_all_profiles(con)
    assert r["profile_count"]==0
    assert r["derived"]["created_count"]==0
    assert r["derived"]["skipped"][0]["reason"]=="source_or_rule_not_attributable"
    con.close()

def test_success_recovery_is_slow_and_idempotent(tmp_path):
    con=init_db(tmp_path/"recovery.sqlite3")
    _critical_attribution(con,cluster_key="1|CANCELLED|CANCELLATION_MISS")
    recompute_all_profiles(con)
    for i in range(4):
        record_success(
            con,source_id=SOURCE,rule_key=RULE,
            observation_key=f"success-{i}",rationale=["held/verified correctly"])
    # duplicate does not add extra recovery
    duplicate=record_success(
        con,source_id=SOURCE,rule_key=RULE,
        observation_key="success-3",rationale=["duplicate"])
    assert duplicate["created"] is False
    p=reliability_profiles(con,SOURCE)[0]
    assert p["score"]==pytest.approx(.90)
    assert p["band"]=="TRUSTED"
    assert p["success_count"]==4
    con.close()

def test_watch_policy_is_shadow_only_by_default(tmp_path):
    con=init_db(tmp_path/"shadow.sqlite3")
    _critical_attribution(con,cluster_key="1|CANCELLED|CANCELLATION_MISS")
    recompute_all_profiles(con)

    r=evaluate_verification_policy(
        con,decision_key="shadow-1",event_instance_id=100,
        source_id=SOURCE,rule_key=RULE,base_eligible=True,
        independent_source_count=1,human_confirmed=False,
        existing_verified=False)
    assert r["reliability_band"]=="WATCH"
    assert r["shadow_action"]=="REQUIRE_CORROBORATION"
    assert r["production_action"]=="ALLOW_VERIFIED"
    assert r["production_mode"]=="BASE_WITH_SHADOW"
    con.close()

def test_existing_verified_event_is_never_downgraded(tmp_path):
    con=init_db(tmp_path/"existing.sqlite3")
    _critical_attribution(con,cluster_key="1|CANCELLED|CANCELLATION_MISS")
    _critical_attribution(con,cluster_key="2|CANCELLED|CANCELLATION_MISS")
    recompute_all_profiles(con)

    r=evaluate_verification_policy(
        con,decision_key="existing-1",event_instance_id=101,
        source_id=SOURCE,rule_key=RULE,base_eligible=True,
        independent_source_count=1,human_confirmed=False,
        existing_verified=True)
    assert r["reliability_band"]=="DEGRADED"
    assert r["shadow_action"]=="KEEP_EXISTING_VERIFIED"
    assert r["production_action"]=="KEEP_EXISTING_VERIFIED"
    assert r["production_mode"]=="NO_RETROACTIVE_CHANGE"
    con.close()

def test_canary_requires_shadow_history_and_human_approval_then_applies_policy(tmp_path):
    con=init_db(tmp_path/"canary.sqlite3")
    _critical_attribution(con,cluster_key="1|CANCELLED|CANCELLATION_MISS")
    recompute_all_profiles(con)

    with pytest.raises(ValueError):
        start_canary(
            con,source_id=SOURCE,rule_key=RULE,
            max_decisions=2,approved_by="김프로")

    for i in range(3):
        evaluate_verification_policy(
            con,decision_key=f"shadow-{i}",event_instance_id=200+i,
            source_id=SOURCE,rule_key=RULE,base_eligible=True,
            independent_source_count=1,human_confirmed=False)

    c=start_canary(
        con,source_id=SOURCE,rule_key=RULE,
        max_decisions=2,approved_by="김프로")
    assert c["created"] is True

    d=evaluate_verification_policy(
        con,decision_key="canary-1",event_instance_id=300,
        source_id=SOURCE,rule_key=RULE,base_eligible=True,
        independent_source_count=1,human_confirmed=False)
    assert d["production_mode"]=="CANARY"
    assert d["production_action"]=="REQUIRE_CORROBORATION"
    assert canaries(con)[0]["used_decisions"]==1
    con.close()

def test_degraded_canary_requires_human_and_two_sources_and_can_rollback(tmp_path):
    con=init_db(tmp_path/"degraded_canary.sqlite3")
    _critical_attribution(con,cluster_key="1|CANCELLED|CANCELLATION_MISS")
    _critical_attribution(con,cluster_key="2|CANCELLED|CANCELLATION_MISS")
    recompute_all_profiles(con)

    for i in range(3):
        evaluate_verification_policy(
            con,decision_key=f"shadow-d-{i}",event_instance_id=400+i,
            source_id=SOURCE,rule_key=RULE,base_eligible=True,
            independent_source_count=1,human_confirmed=False)
    c=start_canary(
        con,source_id=SOURCE,rule_key=RULE,max_decisions=3,approved_by="김프로")

    blocked=evaluate_verification_policy(
        con,decision_key="degraded-blocked",event_instance_id=500,
        source_id=SOURCE,rule_key=RULE,base_eligible=True,
        independent_source_count=2,human_confirmed=False)
    assert blocked["production_action"]=="REQUIRE_HUMAN_AND_CORROBORATION"

    allowed=evaluate_verification_policy(
        con,decision_key="degraded-allowed",event_instance_id=501,
        source_id=SOURCE,rule_key=RULE,base_eligible=True,
        independent_source_count=2,human_confirmed=True)
    assert allowed["production_action"]=="ALLOW_VERIFIED"

    rollback_canary(
        con,canary_id=c["canary_id"],actor="김프로",reason="canary validation complete")
    assert canaries(con)[0]["status"]=="ROLLED_BACK"
    assert any(e["event_type"]=="ROLLBACK" for e in canary_events(con,c["canary_id"]))
    con.close()
