import pytest

from src.database import init_db,create_preventive_quarantine
from src.source_reliability import evaluate_verification_policy
from src.alternative_source_routing import (
    plan_alternative_route,route_evaluations,route_events,
    continuity_metrics
)
from src.source_independence_graph import register_relationship

Q="SRC-Q46"; R="VERIFIED_EVENT_EXISTENCE"

def _source(con,sid,platform,role="SECONDARY",authority="SECONDARY"):
    con.execute("""INSERT OR REPLACE INTO sources(
      source_id,platform,source_role,name,status,authority_level,access_state)
      VALUES(?,?,?,?,?,?,?)""",
      (sid,platform,role,sid,"ACTIVE",authority,"OPEN"))
    con.commit()

def _setup_quarantine(con):
    _source(con,Q,"FACEBOOK","PRIMARY","PRIMARY_ORGANIZER")
    qid,_=create_preventive_quarantine(
        con,source_id=Q,rule_key=R,trigger_recovery_case_id=1,
        trigger_reason="synthetic recurrence",metadata={"test":True})
    return qid

def _decision(con,key,event,sid,platform,*,human=False,base=True):
    _source(con,sid,platform)
    return evaluate_verification_policy(
        con,decision_key=key,event_instance_id=event,source_id=sid,rule_key=R,
        base_eligible=base,independent_source_count=1,
        human_confirmed=human,existing_verified=False)

def test_two_independent_platforms_preserve_verified_continuity(tmp_path):
    con=init_db(tmp_path/"route2.sqlite3")
    _setup_quarantine(con)
    _decision(con,"alt-n",101,"SRC-N46","NAVER_BLOG")
    _decision(con,"alt-d",101,"SRC-D46","DAUM_CAFE")
    register_relationship(
        con,source_id_a="SRC-N46",source_id_b="SRC-D46",
        relationship_type="INDEPENDENT",reviewed_by="test",
        reason="independent operators")
    q=evaluate_verification_policy(
        con,decision_key="q-route",event_instance_id=101,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)
    assert q["production_mode"]=="ALTERNATIVE_ROUTE"
    assert q["production_action"]=="ALLOW_VERIFIED_VIA_ALTERNATIVE_ROUTE"
    route=q["alternative_route"]
    assert route["route_status"]=="ROUTED_VERIFIED"
    assert route["independent_group_count"]==2
    assert route["coverage_preserved"] is True
    assert set(route["selected_source_ids"])=={"SRC-N46","SRC-D46"}
    con.close()

def test_single_nonhuman_alternative_degrades_to_possible(tmp_path):
    con=init_db(tmp_path/"possible.sqlite3")
    _setup_quarantine(con)
    _decision(con,"alt-one",102,"SRC-N46","NAVER_BLOG")
    q=evaluate_verification_policy(
        con,decision_key="q-possible",event_instance_id=102,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)
    assert q["production_mode"]=="ALTERNATIVE_ROUTE"
    assert q["production_action"]=="POSSIBLE_VIA_ALTERNATIVE_ROUTE"
    assert q["alternative_route"]["route_status"]=="ROUTED_POSSIBLE"
    assert q["alternative_route"]["coverage_preserved"] is False
    con.close()

def test_single_human_confirmed_alternative_is_safe_route(tmp_path):
    con=init_db(tmp_path/"human.sqlite3")
    _setup_quarantine(con)
    _decision(con,"alt-human",103,"SRC-H46","NAVER_CAFE",human=True)
    q=evaluate_verification_policy(
        con,decision_key="q-human",event_instance_id=103,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)
    assert q["production_action"]=="ALLOW_VERIFIED_VIA_ALTERNATIVE_ROUTE"
    assert q["alternative_route"]["human_confirmed_route"] is True
    assert q["alternative_route"]["route_status"]=="ROUTED_VERIFIED"
    con.close()

def test_no_safe_route_fails_closed_to_quarantine_hold_and_unknown_plan(tmp_path):
    con=init_db(tmp_path/"none.sqlite3")
    _setup_quarantine(con)
    q=evaluate_verification_policy(
        con,decision_key="q-none",event_instance_id=104,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)
    assert q["production_mode"]=="QUARANTINE_SHADOW"
    assert q["production_action"]=="QUARANTINE_HOLD"
    assert q["alternative_route"]["route_status"]=="NO_SAFE_ROUTE"
    assert q["alternative_route"]["production_recommendation"]=="UNKNOWN"
    con.close()

def test_same_platform_sources_do_not_fake_independence(tmp_path):
    con=init_db(tmp_path/"same-platform.sqlite3")
    _setup_quarantine(con)
    _decision(con,"same-a",105,"SRC-N-A","NAVER_BLOG")
    _decision(con,"same-b",105,"SRC-N-B","NAVER_BLOG")
    p=plan_alternative_route(
        con,event_instance_id=105,quarantined_source_id=Q,rule_key=R)
    assert p["safe_candidate_count"]==2
    assert p["independent_group_count"]==0
    assert p["route_status"]=="ROUTED_POSSIBLE"
    con.close()

def test_unknown_independence_never_counts_as_independent(tmp_path):
    con=init_db(tmp_path/"unknown.sqlite3")
    _setup_quarantine(con)
    # No source rows: evaluate decisions first creates no source metadata.
    d1=evaluate_verification_policy(
        con,decision_key="unk-a",event_instance_id=106,source_id="UNK-A",rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)
    d2=evaluate_verification_policy(
        con,decision_key="unk-b",event_instance_id=106,source_id="UNK-B",rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)
    p=plan_alternative_route(
        con,event_instance_id=106,quarantined_source_id=Q,rule_key=R)
    assert p["safe_candidate_count"]==2
    assert p["independent_group_count"]==0
    assert p["route_status"]=="ROUTED_POSSIBLE"
    con.close()

def test_quarantined_candidate_source_is_excluded(tmp_path):
    con=init_db(tmp_path/"exclude-q.sqlite3")
    _setup_quarantine(con)
    _decision(con,"good-alt",107,"SRC-GOOD","NAVER_BLOG")
    _decision(con,"bad-alt-pre",107,"SRC-BAD","DAUM_CAFE")
    create_preventive_quarantine(
        con,source_id="SRC-BAD",rule_key=R,trigger_recovery_case_id=2,
        trigger_reason="bad alternative",metadata={})
    p=plan_alternative_route(
        con,event_instance_id=107,quarantined_source_id=Q,rule_key=R)
    assert p["candidate_source_ids"]==["SRC-GOOD"]
    assert p["route_status"]=="ROUTED_POSSIBLE"
    con.close()

def test_route_audit_and_continuity_metrics_are_persisted(tmp_path):
    con=init_db(tmp_path/"metrics.sqlite3")
    _setup_quarantine(con)

    _decision(con,"m1-a",201,"SRC-M1A","NAVER_BLOG")
    _decision(con,"m1-b",201,"SRC-M1B","DAUM_CAFE")
    register_relationship(
        con,source_id_a="SRC-M1A",source_id_b="SRC-M1B",
        relationship_type="INDEPENDENT",reviewed_by="test",
        reason="independent operators")
    evaluate_verification_policy(
        con,decision_key="m1-q",event_instance_id=201,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)

    _decision(con,"m2-a",202,"SRC-M2A","NAVER_BLOG")
    evaluate_verification_policy(
        con,decision_key="m2-q",event_instance_id=202,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)

    evaluate_verification_policy(
        con,decision_key="m3-q",event_instance_id=203,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)

    rows=route_evaluations(con)
    assert len(rows)==3
    assert len(route_events(con))==3

    m=continuity_metrics(con,source_id=Q,rule_key=R,persist=True)
    assert m["quarantined_decision_count"]==3
    assert m["routed_verified_count"]==1
    assert m["degraded_possible_count"]==1
    assert m["no_safe_route_count"]==1
    assert m["coverage_preservation_rate"]==pytest.approx(1/3)
    assert m["continuity_snapshot_id"]>0
    con.close()

def test_existing_verified_invariant_still_wins(tmp_path):
    con=init_db(tmp_path/"existing.sqlite3")
    _setup_quarantine(con)
    _decision(con,"ex-a",301,"SRC-EX-A","NAVER_BLOG")
    _decision(con,"ex-b",301,"SRC-EX-B","DAUM_CAFE")
    q=evaluate_verification_policy(
        con,decision_key="ex-q",event_instance_id=301,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False,
        existing_verified=True)
    assert q["production_mode"]=="NO_RETROACTIVE_CHANGE"
    assert q["production_action"]=="KEEP_EXISTING_VERIFIED"
    assert q["alternative_route"] is None
    con.close()
