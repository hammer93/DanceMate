import json
import pytest
from datetime import datetime, timezone

from src.database import init_db
from src.origin_threshold_promotion import (
    create_candidate_from_latest_calibration,candidates,review_candidate,
    start_canary,canary,effective_threshold,record_canary_outcome,
    promote_candidate,promotions,rollback_promotion,runtime_status
)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _event(con,eid,status="POSSIBLE"):
    con.execute("""INSERT INTO event_instances(
      event_instance_id,identity_key,normalized_name,event_date,normalized_venue,
      status,source_count,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (eid,f"E-{eid}",f"Event {eid}","2026-09-10","Venue",status,2,_now(),_now()))
    con.commit()

def _reviewed_cluster(con,cid,eid,decision,sim,status="POSSIBLE"):
    _event(con,eid,status)
    con.execute("""INSERT INTO cross_post_clusters(
      cluster_id,event_instance_id,cluster_key,status,likely_origin_source_id,
      confidence,member_count,reasons_json,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (cid,eid,f"C-{cid}",
       "CONFIRMED_SYNDICATION" if decision=="CONFIRM_SYNDICATION"
       else "CONFIRMED_INDEPENDENT",
       "SRC-A","MEDIUM",2,'[]',_now(),_now()))
    for i in range(2):
        con.execute("""INSERT INTO cross_post_cluster_members(
          cluster_id,source_id,published_at,text_similarity,same_poster,
          same_link_origin,origin_score,signals_json)
          VALUES(?,?,?,?,?,?,?,?)""",
          (cid,f"S-{cid}-{i}",_now(),sim,0,0,1.0-i*.1,'[]'))
    con.execute("""INSERT INTO origin_inference_reviews(
      cluster_id,decision,reviewer,reason,reviewed_at)
      VALUES(?,?,?,?,?)""",(cid,decision,"human","ground truth",_now()))
    con.commit()

def _calibration(con,cal_id=1,base=.86,cand=.89,status="SHADOW_TIGHTEN"):
    con.execute("""INSERT INTO origin_inference_calibrations(
      calibration_id,policy_version,reviewed_cluster_count,
      confirmed_syndication_count,confirmed_independent_count,hold_count,
      precision,false_positive_rate,baseline_text_threshold,
      shadow_recommended_text_threshold,threshold_delta,
      recommendation_status,reasons_json,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cal_id,"v0.49",7,5,2,0,.714,.286,base,cand,cand-base,
       status,'["test"]',_now()))
    con.commit()

def _ready_tighten_candidate(con):
    # Baseline .86 falsely flags 2 independent cases at .87.
    # Candidate .89 removes those FPs while retaining 5 true syndications at .95.
    for i in range(1,6):
        _reviewed_cluster(con,i,100+i,"CONFIRM_SYNDICATION",.95)
    for i in range(6,8):
        _reviewed_cluster(con,i,100+i,"CONFIRM_INDEPENDENT",.87)
    _calibration(con)
    return create_candidate_from_latest_calibration(con)

def _approved_canary(con,max_assignments=3):
    c=_ready_tighten_candidate(con)
    review_candidate(
        con,c["candidate_id"],"APPROVE_CANARY","reviewer","safe shadow comparison")
    return c,start_canary(
        con,c["candidate_id"],"reviewer",max_assignments=max_assignments)

def test_candidate_requires_seven_decisive_human_outcomes(tmp_path):
    con=init_db(tmp_path/"min.sqlite3")
    for i in range(1,4):
        _reviewed_cluster(con,i,100+i,"CONFIRM_SYNDICATION",.95)
    for i in range(4,6):
        _reviewed_cluster(con,i,100+i,"CONFIRM_INDEPENDENT",.87)
    _calibration(con)
    c=create_candidate_from_latest_calibration(con)
    assert c["decisive_review_count"]==5
    assert c["shadow_gate_status"]=="BLOCKED"
    assert c["status"]=="SHADOW"
    con.close()

def test_tighten_candidate_ready_when_fp_improves_without_new_miss(tmp_path):
    con=init_db(tmp_path/"ready.sqlite3")
    c=_ready_tighten_candidate(con)
    assert c["direction"]=="TIGHTEN"
    assert c["shadow_gate_status"]=="READY_FOR_HUMAN_REVIEW"
    assert c["base_false_positive_rate"]>c["candidate_false_positive_rate"]
    assert c["candidate_missed_syndication_count"]==0
    assert c["critical_missed_syndication_count"]==0
    con.close()

def test_tighten_candidate_blocked_when_it_adds_missed_syndication(tmp_path):
    con=init_db(tmp_path/"miss.sqlite3")
    # One true syndication sits between .86 and .89: candidate would miss it.
    for i,sim in enumerate([.95,.95,.95,.95,.87],1):
        _reviewed_cluster(con,i,200+i,"CONFIRM_SYNDICATION",sim)
    for i in range(6,8):
        _reviewed_cluster(con,i,200+i,"CONFIRM_INDEPENDENT",.87)
    _calibration(con)
    c=create_candidate_from_latest_calibration(con)
    assert c["shadow_gate_status"]=="BLOCKED"
    assert c["candidate_missed_syndication_count"]==1
    assert any("missed syndication" in r for r in c["reasons"])
    con.close()

def test_canary_requires_explicit_human_approval(tmp_path):
    con=init_db(tmp_path/"approval.sqlite3")
    c=_ready_tighten_candidate(con)
    with pytest.raises(ValueError):
        start_canary(con,c["candidate_id"],"operator",3)
    review_candidate(con,c["candidate_id"],"APPROVE_CANARY",
                     "operator","approve bounded canary")
    ca=start_canary(con,c["candidate_id"],"operator",3)
    assert ca["status"]=="ACTIVE"
    assert ca["max_assignments"]==3
    con.close()

def test_canary_assignment_is_bounded_and_uses_candidate_threshold(tmp_path):
    con=init_db(tmp_path/"bounded.sqlite3")
    c,ca=_approved_canary(con,3)
    for eid in (501,502,503):
        eff=effective_threshold(con,eid)
        assert eff["mode"]=="CANARY"
        assert eff["threshold"]==pytest.approx(.89)
        assert eff["canary_id"]==ca["canary_id"]
    fourth=effective_threshold(con,504)
    assert fourth["mode"]=="BASE_OR_FULL"
    assert fourth["threshold"]==pytest.approx(.86)
    assert canary(con,ca["canary_id"])["assigned_count"]==3
    con.close()

def test_false_positive_canary_outcome_auto_rolls_back(tmp_path):
    con=init_db(tmp_path/"fp-rollback.sqlite3")
    c,ca=_approved_canary(con,3)
    effective_threshold(con,601)
    out=record_canary_outcome(
        con,601,9001,"CONFIRM_INDEPENDENT")
    assert out["status"]=="ROLLED_BACK"
    assert out["confirmed_independent_count"]==1
    assert "false-positive" in out["rollback_reason"]
    eff=effective_threshold(con,602)
    assert eff["threshold"]==pytest.approx(.86)
    assert eff["mode"]=="BASE_OR_FULL"
    con.close()

def test_missed_syndication_canary_outcome_auto_rolls_back_fail_closed(tmp_path):
    con=init_db(tmp_path/"miss-rollback.sqlite3")
    c,ca=_approved_canary(con,3)
    effective_threshold(con,701)
    out=record_canary_outcome(
        con,701,None,"MISSED_SYNDICATION",critical=True)
    assert out["status"]=="ROLLED_BACK"
    assert out["missed_syndication_count"]==1
    assert out["critical_missed_syndication_count"]==1
    assert "critical" in out["rollback_reason"]
    con.close()

def test_three_safe_canary_outcomes_become_ready_for_final_review(tmp_path):
    con=init_db(tmp_path/"safe-canary.sqlite3")
    c,ca=_approved_canary(con,3)
    for i,eid in enumerate((801,802,803),1):
        effective_threshold(con,eid)
        out=record_canary_outcome(
            con,eid,9100+i,"CONFIRM_SYNDICATION")
    assert out["status"]=="READY_FOR_FINAL_REVIEW"
    assert out["confirmed_syndication_count"]==3
    assert out["confirmed_independent_count"]==0
    con.close()

def test_hold_outcome_cannot_complete_promotion_canary(tmp_path):
    con=init_db(tmp_path/"hold-canary.sqlite3")
    c,ca=_approved_canary(con,3)
    for eid,outcome in zip((811,812,813),
                           ("CONFIRM_SYNDICATION","CONFIRM_SYNDICATION","HOLD")):
        effective_threshold(con,eid)
        out=record_canary_outcome(con,eid,9200+eid,outcome)
    assert out["status"]=="ACTIVE"
    assert out["hold_count"]==1
    with pytest.raises(ValueError):
        promote_candidate(con,c["candidate_id"],"reviewer","not ready")
    con.close()

def test_full_promotion_requires_successful_canary_and_human_review(tmp_path):
    con=init_db(tmp_path/"promotion.sqlite3")
    c,ca=_approved_canary(con,3)
    for i,eid in enumerate((901,902,903),1):
        effective_threshold(con,eid)
        record_canary_outcome(con,eid,9300+i,"CONFIRM_SYNDICATION")
    p=promote_candidate(
        con,c["candidate_id"],"final-reviewer","canary outcomes all safe")
    assert p["status"]=="ACTIVE"
    assert p["production_threshold"]==pytest.approx(.89)
    rs=runtime_status(con)
    assert rs["effective_full_threshold"]==pytest.approx(.89)
    assert rs["active_full_promotion"]["promotion_id"]==p["promotion_id"]
    con.close()

def test_full_promotion_rollback_restores_base_threshold(tmp_path):
    con=init_db(tmp_path/"full-rollback.sqlite3")
    c,ca=_approved_canary(con,1)
    effective_threshold(con,1001)
    record_canary_outcome(con,1001,9401,"CONFIRM_SYNDICATION")
    p=promote_candidate(
        con,c["candidate_id"],"reviewer","safe one-assignment test canary")
    assert runtime_status(con)["effective_full_threshold"]==pytest.approx(.89)
    rb=rollback_promotion(
        con,p["promotion_id"],"reviewer","post-promotion anomaly")
    assert rb["status"]=="ROLLED_BACK"
    assert runtime_status(con)["effective_full_threshold"]==pytest.approx(.86)
    con.close()

def test_candidate_creation_is_idempotent_per_calibration(tmp_path):
    con=init_db(tmp_path/"idempotent.sqlite3")
    c1=_ready_tighten_candidate(con)
    c2=create_candidate_from_latest_calibration(con)
    assert c1["candidate_id"]==c2["candidate_id"]
    assert len(candidates(con))==1
    con.close()

def test_no_automatic_full_promotion_from_shadow_or_canary(tmp_path):
    con=init_db(tmp_path/"no-auto.sqlite3")
    c=_ready_tighten_candidate(con)
    assert promotions(con)==[]
    review_candidate(con,c["candidate_id"],"APPROVE_CANARY",
                     "reviewer","bounded test only")
    start_canary(con,c["candidate_id"],"reviewer",1)
    assert promotions(con)==[]
    assert runtime_status(con)["effective_full_threshold"]==pytest.approx(.86)
    con.close()
