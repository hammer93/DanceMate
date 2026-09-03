import json
from src.database import init_db,create_backlog_item,backlog_row,insert_adaptive_weight_observation
from src.goal_weighting import (
    backlog_goal_defaults,recompute_adaptive_profile,get_effective_weights
)

def test_backlog_stores_explicit_goal(tmp_path):
    con=init_db(tmp_path/"g.sqlite3")
    profile,weights=backlog_goal_defaults(component="EVIDENCE/FEE",field_name="fee")
    bid,_=create_backlog_item(
        con,source_id="SRC-X",field_name="fee",title="fee",priority="P1",
        sample_confidence="LOW",goal_profile=profile,goal_weights=weights)
    row=backlog_row(con,bid)
    assert row["goal_profile"]=="FIELD_QUALITY"
    assert json.loads(row["goal_weights_json"])["correction_rate"]==3.0
    con.close()

def test_adaptive_does_not_activate_before_ten(tmp_path):
    con=init_db(tmp_path/"a.sqlite3")
    for i in range(3):
        insert_adaptive_weight_observation(
            con,goal_profile="FIELD_QUALITY",metric_name="correction_rate",
            change_id=i+1,verdict="IMPROVED",delta=-0.2,
            direction_score=1.0,evidence_strength=1.0)
    r=recompute_adaptive_profile(con,"FIELD_QUALITY")
    assert r["sample_count"]==3
    assert r["adaptive_weights"]["correction_rate"]>3.0
    effective,mode=get_effective_weights(con,"FIELD_QUALITY")
    assert mode=="BASE_UNTIL_10_SAMPLES"
    assert effective["correction_rate"]==3.0
    con.close()

def test_adaptive_activates_at_ten(tmp_path):
    con=init_db(tmp_path/"a10.sqlite3")
    for i in range(10):
        insert_adaptive_weight_observation(
            con,goal_profile="SOURCE_ACCESS",metric_name="access_failure_rate",
            change_id=i+1,verdict="IMPROVED",delta=-0.1,
            direction_score=1.0,evidence_strength=1.0)
    recompute_adaptive_profile(con,"SOURCE_ACCESS")
    effective,mode=get_effective_weights(con,"SOURCE_ACCESS")
    assert mode=="ADAPTIVE"
    assert effective["access_failure_rate"]>3.0
    con.close()
