import pytest
from datetime import datetime, timezone

from src.database import init_db
from src.origin_threshold_runtime_guard import (
    observe_runtime_outcome,recovery_cases,add_recovery_shadow_outcome,
    requalify_recovery
)
from src.origin_threshold_recovery_root_cause import (
    root_causes,requirements,adaptive_requalification_status,
    submit_remediation,review_remediation,review_root_cause,
    attribute_root_cause,build_adaptive_requirement
)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _seed_source(con,sid,platform):
    con.execute("""INSERT OR IGNORE INTO sources(
      source_id,platform,source_role,name,status,authority_level,access_state)
      VALUES(?,?,?,?,?,?,?)""",
      (sid,platform,"COMMUNITY",sid,"ACTIVE","SECONDARY","PUBLIC"))

def _candidate_promotion(con,pid=1,cid=1,threshold=.89):
    con.execute("""INSERT INTO origin_threshold_candidates(
      candidate_id,calibration_id,baseline_threshold,candidate_threshold,direction,
      status,shadow_gate_status,decisive_review_count,base_precision,
      candidate_precision,base_false_positive_rate,candidate_false_positive_rate,
      base_missed_syndication_count,candidate_missed_syndication_count,
      critical_missed_syndication_count,reasons_json,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cid,cid,.86,threshold,"TIGHTEN","FULL_PROMOTED",
       "READY_FOR_HUMAN_REVIEW",7,.7,.9,.3,.1,0,0,0,'[]',_now(),_now()))
    con.execute("""INSERT INTO origin_threshold_promotions(
      promotion_id,candidate_id,canary_id,status,production_threshold,
      approved_by,reason,promoted_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (pid,cid,None,"ACTIVE",threshold,"human","safe canary",_now()))
    con.commit()

def _event_cluster(con,eid,cid,sources):
    con.execute("""INSERT OR IGNORE INTO event_instances(
      event_instance_id,identity_key,normalized_name,event_date,normalized_venue,
      status,source_count,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (eid,f"E-{eid}",f"Event {eid}","2026-09-10","Venue","POSSIBLE",
       len(sources),_now(),_now()))
    con.execute("""INSERT OR IGNORE INTO cross_post_clusters(
      cluster_id,event_instance_id,cluster_key,status,likely_origin_source_id,
      confidence,member_count,reasons_json,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (cid,eid,f"C-{cid}","AUTO_SUSPECTED_SYNDICATION",
       sources[0][0],"MEDIUM",len(sources),'[]',_now(),_now()))
    for i,(sid,platform) in enumerate(sources):
        _seed_source(con,sid,platform)
        con.execute("""INSERT OR IGNORE INTO cross_post_cluster_members(
          cluster_id,source_id,published_at,text_similarity,same_poster,
          same_link_origin,origin_score,signals_json)
          VALUES(?,?,?,?,?,?,?,?)""",
          (cid,sid,_now(),.87,0,0,1.0-i*.1,'[]'))
    con.commit()

def _critical_failure(con):
    _candidate_promotion(con)
    # Tightened .89 misses true syndication at .87; Base .86 would catch it.
    r=observe_runtime_outcome(
        con,event_instance_id=1,cluster_id=None,
        human_outcome="CONFIRM_SYNDICATION",max_text_similarity=.87,
        event_status="VERIFIED",critical=True)
    assert r["rollback"]["rolled_back"] is True
    return recovery_cases(con)[0]["recovery_case_id"]

def _coverage_safe_outcomes(con,rid,count=12):
    source_sets=[
        [("S1","FACEBOOK"),("S2","NAVER_BLOG")],
        [("S3","DAUM_CAFE"),("S4","FACEBOOK")],
    ]
    for i in range(count):
        eid=100+i; cid=1000+i
        _event_cluster(con,eid,cid,source_sets[i%2])
        add_recovery_shadow_outcome(con,rid,eid,"SAFE")

def test_auto_rollback_creates_root_cause_and_adaptive_requirement(tmp_path):
    con=init_db(tmp_path/"auto.sqlite3")
    rid=_critical_failure(con)
    rcs=root_causes(con,rid); req=requirements(con,rid)
    assert len(rcs)==1 and len(req)==1
    assert rcs[0]["failure_class"]=="MISSED_SYNDICATION"
    assert rcs[0]["root_cause_type"]=="THRESHOLD_BOUNDARY"
    assert rcs[0]["risk_band"]=="RESTRICTED"
    assert req[0]["required_safe_shadow_outcomes"]==12
    assert req[0]["required_distinct_sources"]==4
    assert req[0]["required_distinct_platforms"]==2
    con.close()

def test_boundary_distance_is_auditable(tmp_path):
    con=init_db(tmp_path/"boundary.sqlite3")
    rid=_critical_failure(con)
    rc=root_causes(con,rid)[0]
    assert rc["boundary_distance"]==pytest.approx(.02)
    assert rc["evidence"]["critical_regression_count"]==1
    con.close()

def test_restricted_gate_not_ready_with_safe_count_only(tmp_path):
    con=init_db(tmp_path/"count-only.sqlite3")
    rid=_critical_failure(con)
    _coverage_safe_outcomes(con,rid,12)
    s=adaptive_requalification_status(con,rid)
    assert s["observed_safe_outcomes"]==12
    assert s["checks"]["distinct_sources"] is True
    assert s["checks"]["distinct_platforms"] is True
    assert s["checks"]["remediation"] is False
    assert s["checks"]["human_root_cause_confirmed"] is False
    assert s["status"]=="NOT_READY"
    con.close()

def test_effective_remediation_and_human_root_cause_review_required(tmp_path):
    con=init_db(tmp_path/"remediation.sqlite3")
    rid=_critical_failure(con)
    _coverage_safe_outcomes(con,rid,12)
    rc=root_causes(con,rid)[0]
    rem=submit_remediation(
        con,rid,"THRESHOLD_CHANGE","engineer",
        "candidate threshold logic adjusted","CHANGE-52")
    review_root_cause(con,rc["root_cause_id"],"CONFIRM","reviewer","boundary miss confirmed")
    s=adaptive_requalification_status(con,rid)
    assert s["checks"]["human_root_cause_confirmed"] is True
    assert s["checks"]["remediation"] is False
    review_remediation(
        con,rem["remediation_id"],"EFFECTIVE","reviewer",
        "12 Shadow outcomes show no recurrence")
    s=adaptive_requalification_status(con,rid)
    assert s["checks"]["remediation"] is True
    assert s["status"]=="READY_FOR_ADAPTIVE_REQUALIFICATION"
    con.close()

def test_ineffective_remediation_never_satisfies_gate(tmp_path):
    con=init_db(tmp_path/"ineffective.sqlite3")
    rid=_critical_failure(con)
    _coverage_safe_outcomes(con,rid,12)
    rc=root_causes(con,rid)[0]
    rem=submit_remediation(con,rid,"THRESHOLD_CHANGE","engineer","trial fix")
    review_root_cause(con,rc["root_cause_id"],"CONFIRM","reviewer","confirmed")
    review_remediation(con,rem["remediation_id"],"INEFFECTIVE","reviewer","regression reproduced")
    s=adaptive_requalification_status(con,rid)
    assert s["checks"]["remediation"] is False
    assert s["status"]=="NOT_READY"
    con.close()

def test_full_adaptive_gate_allows_human_requalification(tmp_path):
    con=init_db(tmp_path/"full.sqlite3")
    rid=_critical_failure(con)
    _coverage_safe_outcomes(con,rid,12)
    rc=root_causes(con,rid)[0]
    rem=submit_remediation(con,rid,"THRESHOLD_CHANGE","engineer","fix threshold boundary")
    review_root_cause(con,rc["root_cause_id"],"CONFIRM","reviewer","confirmed")
    review_remediation(con,rem["remediation_id"],"EFFECTIVE","reviewer","safe Shadow coverage")
    s=adaptive_requalification_status(con,rid)
    assert s["status"]=="READY_FOR_ADAPTIVE_REQUALIFICATION"
    r=requalify_recovery(con,rid,"reviewer","root cause fixed and adaptive gate passed")
    assert r["status"]=="REQUALIFIED"
    con.close()

def test_source_and_platform_coverage_are_real_not_raw_count(tmp_path):
    con=init_db(tmp_path/"coverage.sqlite3")
    rid=_critical_failure(con)
    # 12 outcomes but always same two source IDs / one platform.
    for i in range(12):
        eid=300+i; cid=3000+i
        _event_cluster(con,eid,cid,[("S1","FACEBOOK"),("S2","FACEBOOK")])
        add_recovery_shadow_outcome(con,rid,eid,"SAFE")
    rc=root_causes(con,rid)[0]
    rem=submit_remediation(con,rid,"THRESHOLD_CHANGE","engineer","fix")
    review_root_cause(con,rc["root_cause_id"],"CONFIRM","reviewer","confirmed")
    review_remediation(con,rem["remediation_id"],"EFFECTIVE","reviewer","local safe")
    s=adaptive_requalification_status(con,rid)
    assert s["observed_distinct_sources"]==2
    assert s["observed_distinct_platforms"]==1
    assert s["checks"]["distinct_sources"] is False
    assert s["checks"]["distinct_platforms"] is False
    con.close()

def test_repeated_root_cause_escalates_requirement(tmp_path):
    con=init_db(tmp_path/"repeat.sqlite3")
    # Create two manual recovery/root-cause cycles with same deterministic cause.
    _candidate_promotion(con,1,1,.89)
    observe_runtime_outcome(
        con,event_instance_id=1,human_outcome="CONFIRM_SYNDICATION",
        max_text_similarity=.87,event_status="POSSIBLE",critical=False)
    # Need second regression to trigger rolling rollback; use another at .87 after fillers.
    for eid,sim in [(2,.95),(3,.95),(4,.95),(5,.87)]:
        observe_runtime_outcome(
            con,event_instance_id=eid,human_outcome="CONFIRM_SYNDICATION",
            max_text_similarity=sim,event_status="POSSIBLE")
    rid1=recovery_cases(con)[0]["recovery_case_id"]
    assert root_causes(con,rid1)[0]["root_cause_type"]=="THRESHOLD_BOUNDARY"

    # Manually create a second Recovery Case tied to another historical promotion and regressions.
    _candidate_promotion(con,2,2,.89)
    con.execute("""INSERT INTO origin_threshold_runtime_observations(
      promotion_id,event_instance_id,cluster_id,human_outcome,max_text_similarity,
      event_status,critical,base_threshold,promoted_threshold,
      base_predicted_syndication,promoted_predicted_syndication,
      base_correct,promoted_correct,counterfactual_class,observed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (2,50,None,"CONFIRM_SYNDICATION",.87,"POSSIBLE",0,.86,.89,1,0,1,0,
       "PROMOTION_REGRESSION",_now()))
    con.execute("""UPDATE origin_threshold_promotions SET status='ROLLED_BACK'
                   WHERE promotion_id=2""")
    con.execute("""INSERT INTO origin_threshold_recovery_cases(
      promotion_id,candidate_id,failed_threshold,fallback_threshold,status,
      rollback_reason,required_shadow_outcomes,safe_shadow_outcome_count,opened_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (2,2,.89,.86,"OPEN","repeat",5,0,_now()))
    rid2=con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.commit()
    rc2=attribute_root_cause(con,rid2,persist=True)
    req2=build_adaptive_requirement(con,rid2,persist=True)
    assert rc2["repeated_root_cause_count"]>=2
    assert req2["recurrence_penalty"]>=1
    assert req2["required_safe_shadow_outcomes"]>=10
    con.close()

def test_root_cause_review_reject_does_not_satisfy_gate(tmp_path):
    con=init_db(tmp_path/"reject.sqlite3")
    rid=_critical_failure(con)
    _coverage_safe_outcomes(con,rid,12)
    rc=root_causes(con,rid)[0]
    rem=submit_remediation(con,rid,"THRESHOLD_CHANGE","engineer","fix")
    review_remediation(con,rem["remediation_id"],"EFFECTIVE","reviewer","safe")
    review_root_cause(con,rc["root_cause_id"],"REJECT","reviewer","wrong attribution")
    s=adaptive_requalification_status(con,rid)
    assert s["checks"]["human_root_cause_confirmed"] is False
    con.close()

def test_requirement_persists_audit_reasons(tmp_path):
    con=init_db(tmp_path/"audit.sqlite3")
    rid=_critical_failure(con)
    req=requirements(con,rid)[0]
    assert req["risk_band"]=="RESTRICTED"
    assert req["reasons"]
    assert "documented remediation" in " ".join(req["reasons"])
    con.close()
