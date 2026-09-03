import pytest
from datetime import datetime, timezone, timedelta

from src.database import init_db
from src.origin_confidence_calibration import (
    calibration_metrics,shadow_threshold_recommendation,evaluate_calibration,
    calibration_history,build_review_queue,priority_history
)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _event(con,eid,status="POSSIBLE",days=10):
    d=(datetime.now(timezone.utc).date()+timedelta(days=days)).isoformat()
    con.execute("""INSERT INTO event_instances(
      event_instance_id,identity_key,normalized_name,event_date,normalized_venue,
      status,source_count,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (eid,f"E-{eid}",f"Event {eid}",d,"Venue",status,2,_now(),_now()))
    con.commit()

def _cluster(con,cid,eid,status="AUTO_SUSPECTED_SYNDICATION",
             confidence="MEDIUM",member_count=2,sim=.90,
             same_poster=0,same_link=0):
    con.execute("""INSERT INTO cross_post_clusters(
      cluster_id,event_instance_id,cluster_key,status,likely_origin_source_id,
      confidence,member_count,reasons_json,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (cid,eid,f"C-{cid}",status,"SRC-A",confidence,member_count,
       '["test"]',_now(),_now()))
    for i in range(member_count):
        con.execute("""INSERT INTO cross_post_cluster_members(
          cluster_id,source_id,published_at,text_similarity,same_poster,
          same_link_origin,origin_score,signals_json)
          VALUES(?,?,?,?,?,?,?,?)""",
          (cid,f"SRC-{cid}-{i}",_now(),sim,
           int(same_poster),int(same_link),1.0-i*.1,'[]'))
    con.commit()

def _review(con,cid,decision):
    con.execute("""INSERT INTO origin_inference_reviews(
      cluster_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(cid,decision,"tester","ground truth",_now()))
    con.commit()

def test_calibration_needs_five_decisive_reviews(tmp_path):
    con=init_db(tmp_path/"few.sqlite3")
    for i in range(4):
        _review(con,i+1,"CONFIRM_SYNDICATION")
    r=evaluate_calibration(con,persist=False)
    assert r["decisive_review_count"]==4
    assert r["precision"]==1.0
    assert r["recommendation_status"]=="INSUFFICIENT_EVIDENCE"
    assert r["shadow_recommended_text_threshold"]==.86
    assert r["automatic_production_change"] is False
    con.close()

def test_high_false_positive_rate_recommends_shadow_tighten(tmp_path):
    con=init_db(tmp_path/"tighten.sqlite3")
    # 3 confirmed syndication / 2 independent = 40% false positives
    for cid,decision in enumerate(
        ["CONFIRM_SYNDICATION"]*3+["CONFIRM_INDEPENDENT"]*2,1):
        _review(con,cid,decision)
    r=evaluate_calibration(con,persist=True)
    assert r["precision"]==pytest.approx(.6)
    assert r["false_positive_rate"]==pytest.approx(.4)
    assert r["recommendation_status"]=="SHADOW_TIGHTEN"
    assert r["shadow_recommended_text_threshold"]==pytest.approx(.89)
    assert r["threshold_delta"]==pytest.approx(.03)
    assert len(calibration_history(con))==1
    con.close()

def test_high_precision_recommends_only_small_shadow_relax(tmp_path):
    con=init_db(tmp_path/"relax.sqlite3")
    for cid in range(1,11):
        _review(con,cid,"CONFIRM_SYNDICATION")
    r=evaluate_calibration(con,persist=False)
    assert r["precision"]==1.0
    assert r["false_positive_rate"]==0.0
    assert r["recommendation_status"]=="SHADOW_RELAX"
    assert r["shadow_recommended_text_threshold"]==pytest.approx(.85)
    assert r["automatic_production_change"] is False
    con.close()

def test_mixed_outcomes_hold_threshold(tmp_path):
    con=init_db(tmp_path/"hold.sqlite3")
    for cid,decision in enumerate(
        ["CONFIRM_SYNDICATION"]*4+["CONFIRM_INDEPENDENT"],1):
        _review(con,cid,decision)
    r=evaluate_calibration(con,persist=False)
    assert r["false_positive_rate"]==pytest.approx(.2)
    assert r["recommendation_status"]=="SHADOW_HOLD"
    assert r["shadow_recommended_text_threshold"]==.86
    con.close()

def test_latest_human_review_per_cluster_is_used(tmp_path):
    con=init_db(tmp_path/"latest.sqlite3")
    _review(con,1,"HOLD")
    _review(con,1,"CONFIRM_INDEPENDENT")
    _review(con,2,"CONFIRM_SYNDICATION")
    m=calibration_metrics(con)
    assert m["reviewed_cluster_count"]==2
    assert m["confirmed_independent_count"]==1
    assert m["confirmed_syndication_count"]==1
    assert m["hold_count"]==0
    con.close()

def test_review_queue_prioritizes_verified_route_impact_cluster(tmp_path):
    con=init_db(tmp_path/"queue.sqlite3")
    _event(con,101,status="VERIFIED",days=1)
    _event(con,102,status="POSSIBLE",days=20)
    _cluster(con,1,101,confidence="HIGH",member_count=3,sim=.98,
             same_poster=1,same_link=1)
    _cluster(con,2,102,confidence="MEDIUM",member_count=2,sim=.87)

    con.execute("""INSERT INTO alternative_route_evaluations(
      trigger_decision_id,event_instance_id,quarantined_source_id,rule_key,
      candidate_decision_ids_json,selected_decision_ids_json,
      independence_groups_json,human_confirmed_route,safe_candidate_count,
      independent_group_count,route_status,production_recommendation,
      coverage_preserved,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (1,101,"Q","RULE","[]","[]","[]",0,2,2,
       "ROUTED_VERIFIED","ALLOW_VERIFIED_VIA_ALTERNATIVE_ROUTE",1,"[]",_now()))
    con.commit()

    q=build_review_queue(con,persist=True)
    assert q["pending_cluster_count"]==2
    assert q["items"][0]["cluster_id"]==1
    assert q["items"][0]["priority_score"]>q["items"][1]["priority_score"]
    assert q["items"][0]["priority_band"]=="P1"
    assert q["items"][0]["route_impact_count"]==1
    assert len(priority_history(con))==2
    con.close()

def test_confirmed_clusters_are_removed_from_pending_queue(tmp_path):
    con=init_db(tmp_path/"pending.sqlite3")
    _event(con,201); _event(con,202)
    _cluster(con,1,201,status="CONFIRMED_SYNDICATION")
    _cluster(con,2,202,status="AUTO_SUSPECTED_SYNDICATION")
    q=build_review_queue(con,persist=False)
    assert q["pending_cluster_count"]==1
    assert q["items"][0]["cluster_id"]==2
    con.close()

def test_priority_band_is_deterministic_and_bounded(tmp_path):
    con=init_db(tmp_path/"band.sqlite3")
    _event(con,301,status="VERIFIED",days=0)
    _cluster(con,1,301,confidence="HIGH",member_count=8,sim=1.0,
             same_poster=1,same_link=1)
    q=build_review_queue(con,persist=False)
    x=q["items"][0]
    assert 0<=x["priority_score"]<=100
    assert x["priority_band"]=="P1"
    con.close()

def test_hold_reviews_do_not_count_as_precision_ground_truth(tmp_path):
    con=init_db(tmp_path/"hold-metric.sqlite3")
    for cid in range(1,8):
        _review(con,cid,"HOLD")
    m=calibration_metrics(con)
    assert m["reviewed_cluster_count"]==7
    assert m["decisive_review_count"]==0
    assert m["precision"] is None
    assert m["false_positive_rate"] is None
    con.close()

def test_threshold_bounds_are_enforced(tmp_path):
    con=init_db(tmp_path/"bounds.sqlite3")
    metrics={
        "decisive_review_count":10,
        "false_positive_rate":.5,
        "precision":.5
    }
    hi=shadow_threshold_recommendation(metrics,baseline=.94)
    assert hi["shadow_recommended_text_threshold"]==.95

    metrics2={
        "decisive_review_count":10,
        "false_positive_rate":0.0,
        "precision":1.0
    }
    lo=shadow_threshold_recommendation(metrics2,baseline=.80)
    assert lo["shadow_recommended_text_threshold"]==.80
    con.close()
