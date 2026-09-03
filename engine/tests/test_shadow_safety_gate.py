from src.database import init_db,persist_adaptive_shadow_verdict
from src.shadow_safety_gate import evaluate_shadow_safety,shadow_safety_status

BASE_WEIGHTS={
    "correction_rate":3.0,
    "field_coverage_rate":2.0,
    "known_field_rate":1.5,
    "access_failure_rate":0.5,
    "source_yield_rate":0.5,
    "recovery_success_rate":0.5
}

def _shadow(con, idx, base, shadow, goal="FIELD_QUALITY"):
    persist_adaptive_shadow_verdict(
        con,change_id=idx,
        baseline_daily_run_id=f"b-{idx}",
        post_daily_run_id=f"p-{idx}",
        goal_profile=goal,
        base_verdict=base,
        shadow_verdict=shadow,
        base_weighted_score=0.0,
        shadow_weighted_score=0.0,
        agrees=(base==shadow),
        adaptive_sample_count=max(0,idx-1),
        base_weights=BASE_WEIGHTS,
        shadow_weights=BASE_WEIGHTS,
        reasons=[]
    )

def test_safety_observing_when_sample_count_low(tmp_path):
    con=init_db(tmp_path/"low.sqlite3")
    for i in range(1,6):
        _shadow(con,i,"IMPROVED","IMPROVED")
    r=shadow_safety_status(con,"FIELD_QUALITY")
    assert r["status"]=="OBSERVING"
    assert r["total"]==5
    assert r["agreement_rate"]==1.0
    assert r["unsafe_improved"]==0
    con.close()

def test_safety_eligible_after_twenty_safe_high_agreement_samples(tmp_path):
    con=init_db(tmp_path/"eligible.sqlite3")
    for i in range(1,21):
        base="IMPROVED" if i%2 else "REGRESSED"
        _shadow(con,i,base,base)
    r=evaluate_shadow_safety(con,"FIELD_QUALITY")
    assert r["status"]=="ELIGIBLE"
    assert r["total"]==20
    assert r["agreement_rate"]==1.0
    assert r["critical_false_improved"]==0
    assert r["unsafe_improved"]==0
    assert r["automatic_promotion"] is False
    con.close()

def test_critical_false_improved_blocks_even_with_high_agreement(tmp_path):
    con=init_db(tmp_path/"critical.sqlite3")
    for i in range(1,20):
        _shadow(con,i,"REGRESSED","REGRESSED")
    _shadow(con,20,"REGRESSED","IMPROVED")
    r=evaluate_shadow_safety(con,"FIELD_QUALITY")
    assert r["agreement_rate"]==0.95
    assert r["critical_false_improved"]==1
    assert r["unsafe_improved"]==1
    assert r["status"]=="BLOCKED"
    assert r["confusion_matrix"]["REGRESSED"]["IMPROVED"]==1
    con.close()

def test_inconclusive_to_improved_is_unsafe_and_blocks(tmp_path):
    con=init_db(tmp_path/"unsafe.sqlite3")
    for i in range(1,20):
        _shadow(con,i,"INCONCLUSIVE","INCONCLUSIVE")
    _shadow(con,20,"INCONCLUSIVE","IMPROVED")
    r=evaluate_shadow_safety(con,"FIELD_QUALITY")
    assert r["critical_false_improved"]==0
    assert r["unsafe_improved"]==1
    assert r["status"]=="BLOCKED"
    assert r["confusion_matrix"]["INCONCLUSIVE"]["IMPROVED"]==1
    con.close()

def test_conservative_false_regressed_is_tracked_not_critical(tmp_path):
    con=init_db(tmp_path/"conservative.sqlite3")
    for i in range(1,20):
        _shadow(con,i,"IMPROVED","IMPROVED")
    _shadow(con,20,"IMPROVED","REGRESSED")
    r=evaluate_shadow_safety(con,"FIELD_QUALITY")
    assert r["conservative_false_regressed"]==1
    assert r["unsafe_improved"]==0
    # 95% agreement and no unsafe optimism -> eligible.
    assert r["status"]=="ELIGIBLE"
    assert r["confusion_matrix"]["IMPROVED"]["REGRESSED"]==1
    con.close()
