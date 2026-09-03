from src.database import init_db,persist_adaptive_shadow_verdict
from src.rolling_shadow_stability import (
    evaluate_rolling_shadow_stability,promotion_candidates
)

W={
    "correction_rate":3.0,
    "field_coverage_rate":2.0,
    "known_field_rate":1.5,
    "access_failure_rate":0.5,
    "source_yield_rate":0.5,
    "recovery_success_rate":0.5
}

def _shadow(con,idx,base="IMPROVED",shadow="IMPROVED",goal="FIELD_QUALITY"):
    persist_adaptive_shadow_verdict(
        con,change_id=idx,
        baseline_daily_run_id=f"b-{idx}",
        post_daily_run_id=f"p-{idx}",
        goal_profile=goal,
        base_verdict=base,shadow_verdict=shadow,
        base_weighted_score=1.0 if base=="IMPROVED" else -1.0,
        shadow_weighted_score=1.0 if shadow=="IMPROVED" else -1.0,
        agrees=(base==shadow),adaptive_sample_count=max(0,idx-1),
        base_weights=W,shadow_weights=W,reasons=[]
    )

def test_rolling_observes_before_minimum_samples(tmp_path):
    con=init_db(tmp_path/"observe.sqlite3")
    for i in range(1,11):
        _shadow(con,i)
    r=evaluate_rolling_shadow_stability(con,"FIELD_QUALITY")
    assert r["status"]=="OBSERVING"
    assert r["total_samples"]==10
    assert r["windows"]["7"]["status"]=="STABLE"
    assert r["windows"]["14"]["status"]=="OBSERVING"
    assert r["promotion_candidate"] is None
    con.close()

def test_twenty_safe_samples_create_human_approval_candidate(tmp_path):
    con=init_db(tmp_path/"candidate.sqlite3")
    for i in range(1,21):
        _shadow(con,i,"IMPROVED","IMPROVED")
    r=evaluate_rolling_shadow_stability(con,"FIELD_QUALITY")
    assert r["status"]=="ELIGIBLE"
    assert r["windows"]["7"]["status"]=="STABLE"
    assert r["windows"]["14"]["status"]=="STABLE"
    assert r["windows"]["30"]["status"]=="OBSERVING"
    assert r["promotion_candidate"]["status"]=="CANDIDATE"
    assert r["promotion_candidate"]["human_approval_required"] is True

    # Re-evaluation must not create duplicate active candidate.
    r2=evaluate_rolling_shadow_stability(con,"FIELD_QUALITY")
    assert r2["promotion_candidate"]["created"] is False
    pcs=promotion_candidates(con,"FIELD_QUALITY")
    assert len(pcs)==1
    assert pcs[0]["status"]=="CANDIDATE"
    con.close()

def test_eligible_to_blocked_downgrade_revokes_candidate(tmp_path):
    con=init_db(tmp_path/"downgrade.sqlite3")
    for i in range(1,21):
        _shadow(con,i,"REGRESSED","REGRESSED")
    first=evaluate_rolling_shadow_stability(con,"FIELD_QUALITY")
    assert first["status"]=="ELIGIBLE"
    assert first["promotion_candidate"]["status"]=="CANDIDATE"

    # New highest-risk false optimism.
    _shadow(con,21,"REGRESSED","IMPROVED")
    second=evaluate_rolling_shadow_stability(con,"FIELD_QUALITY")
    assert second["status"]=="BLOCKED"
    assert second["downgrade_detected"] is True
    assert second["windows"]["7"]["status"]=="BLOCKED"
    assert second["promotion_candidate"]["status"]=="REVOKED"

    pcs=promotion_candidates(con,"FIELD_QUALITY")
    assert len(pcs)==1
    assert pcs[0]["status"]=="REVOKED"
    con.close()

def test_recent_conservative_disagreement_prevents_rolling_eligibility(tmp_path):
    con=init_db(tmp_path/"recent.sqlite3")
    # Start with 20 perfect safe samples and establish ELIGIBLE history.
    for i in range(1,21):
        _shadow(con,i,"IMPROVED","IMPROVED")
    assert evaluate_rolling_shadow_stability(con,"FIELD_QUALITY")["status"]=="ELIGIBLE"

    # Add 7 conservative disagreements. They do not trigger unsafe optimism,
    # but the recent window is unstable and cumulative agreement falls below 90%.
    for i in range(21,28):
        _shadow(con,i,"IMPROVED","REGRESSED")
    r=evaluate_rolling_shadow_stability(con,"FIELD_QUALITY")
    assert r["status"]=="OBSERVING"
    assert r["windows"]["7"]["agreement_rate"]==0.0
    assert r["windows"]["7"]["status"]=="OBSERVING"
    assert r["downgrade_detected"] is False
    con.close()

def test_thirty_sample_window_becomes_required_when_available(tmp_path):
    con=init_db(tmp_path/"thirty.sqlite3")
    for i in range(1,31):
        base="REGRESSED" if i%2 else "IMPROVED"
        _shadow(con,i,base,base)
    r=evaluate_rolling_shadow_stability(con,"FIELD_QUALITY")
    assert r["status"]=="ELIGIBLE"
    assert r["windows"]["30"]["sample_count"]==30
    assert r["windows"]["30"]["status"]=="STABLE"
    con.close()
