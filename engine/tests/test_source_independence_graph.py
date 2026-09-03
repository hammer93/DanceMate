import pytest

from src.database import init_db,create_preventive_quarantine
from src.source_reliability import evaluate_verification_policy
from src.source_independence_graph import (
    register_relationship,register_fingerprint,evaluate_pair,
    independent_groups,relationships,fingerprints,independence_history
)

R="VERIFIED_EVENT_EXISTENCE"; Q="SRC-Q47"

def _source(con,sid,platform):
    con.execute("""INSERT OR REPLACE INTO sources(
      source_id,platform,source_role,name,status,authority_level,access_state)
      VALUES(?,?,?,?,?,?,?)""",
      (sid,platform,"SECONDARY",sid,"ACTIVE","SECONDARY","OPEN"))
    con.commit()

def _q(con):
    _source(con,Q,"FACEBOOK")
    create_preventive_quarantine(
        con,source_id=Q,rule_key=R,trigger_recovery_case_id=1,
        trigger_reason="test",metadata={})

def _d(con,key,event,sid,platform,human=False):
    _source(con,sid,platform)
    return evaluate_verification_policy(
        con,decision_key=key,event_instance_id=event,source_id=sid,rule_key=R,
        base_eligible=True,independent_source_count=1,
        human_confirmed=human,existing_verified=False)

def test_different_platforms_alone_are_not_proven_independent(tmp_path):
    con=init_db(tmp_path/"platform-alone.sqlite3")
    _source(con,"A","NAVER_BLOG"); _source(con,"B","DAUM_CAFE")
    r=evaluate_pair(con,event_instance_id=1,source_id_a="A",source_id_b="B")
    assert r["independence_status"]=="UNKNOWN"
    assert r["relationship_type"]=="UNKNOWN"
    con.close()

def test_human_reviewed_independent_edge_proves_independence(tmp_path):
    con=init_db(tmp_path/"explicit-independent.sqlite3")
    register_relationship(
        con,source_id_a="A",source_id_b="B",
        relationship_type="INDEPENDENT",confidence="HIGH",
        reviewed_by="김프로",reason="different operators and original evidence")
    r=evaluate_pair(con,event_instance_id=2,source_id_a="A",source_id_b="B")
    assert r["independence_status"]=="INDEPENDENT"
    assert r["relationship_type"]=="INDEPENDENT"
    assert relationships(con)[0]["reviewed_by"]=="김프로"
    con.close()

def test_exact_content_fingerprint_detects_syndication(tmp_path):
    con=init_db(tmp_path/"content-syndication.sqlite3")
    register_fingerprint(con,event_instance_id=3,source_id="A",
                         content="8월 31일 OCHO 20:00 입장료 13000원")
    register_fingerprint(con,event_instance_id=3,source_id="B",
                         content="8월 31일 OCHO 20:00 입장료 13000원")
    r=evaluate_pair(con,event_instance_id=3,source_id_a="A",source_id_b="B")
    assert r["relationship_type"]=="SYNDICATED"
    assert r["independence_status"]=="NOT_INDEPENDENT"
    assert "EXACT_CONTENT_FINGERPRINT" in r["syndication_signals"]
    con.close()

def test_syndication_signal_overrides_prior_independent_edge(tmp_path):
    con=init_db(tmp_path/"override.sqlite3")
    register_relationship(con,source_id_a="A",source_id_b="B",
                          relationship_type="INDEPENDENT",reviewed_by="김프로",
                          reason="normally independent operators")
    register_fingerprint(con,event_instance_id=4,source_id="A",
                         content="same copied announcement")
    register_fingerprint(con,event_instance_id=4,source_id="B",
                         content="same copied announcement")
    r=evaluate_pair(con,event_instance_id=4,source_id_a="A",source_id_b="B")
    assert r["relationship_type"]=="SYNDICATED"
    assert r["independence_status"]=="NOT_INDEPENDENT"
    con.close()

def test_same_poster_alone_is_related_not_syndicated(tmp_path):
    con=init_db(tmp_path/"poster.sqlite3")
    register_fingerprint(con,event_instance_id=5,source_id="A",
                         content="venue announcement A",poster_hash="POSTER-X")
    register_fingerprint(con,event_instance_id=5,source_id="B",
                         content="organizer wording B",poster_hash="POSTER-X")
    r=evaluate_pair(con,event_instance_id=5,source_id_a="A",source_id_b="B")
    assert r["relationship_type"]=="RELATED"
    assert r["independence_status"]=="NOT_INDEPENDENT"
    assert "EXACT_POSTER_FINGERPRINT" in r["syndication_signals"]
    con.close()

def test_explicit_origin_link_is_syndicated(tmp_path):
    con=init_db(tmp_path/"origin.sqlite3")
    register_fingerprint(con,event_instance_id=6,source_id="A",
                         content="original",origin_source_id="A")
    register_fingerprint(con,event_instance_id=6,source_id="B",
                         content="rewritten copy",origin_source_id="A")
    r=evaluate_pair(con,event_instance_id=6,source_id_a="A",source_id_b="B")
    assert r["relationship_type"]=="SYNDICATED"
    assert "DIRECT_ORIGIN_LINK" in r["syndication_signals"]
    con.close()

def test_independence_graph_does_not_assume_transitivity(tmp_path):
    con=init_db(tmp_path/"nontransitive.sqlite3")
    register_relationship(con,source_id_a="A",source_id_b="B",
                          relationship_type="INDEPENDENT",reviewed_by="r")
    register_relationship(con,source_id_a="B",source_id_b="C",
                          relationship_type="INDEPENDENT",reviewed_by="r")
    g=independent_groups(con,event_instance_id=7,source_ids=["A","B","C"])
    assert g["independent_count"]==2
    assert len(g["independent_source_ids"])==2
    # A-C remains UNKNOWN, so all three can never become a corroboration clique.
    ac=[x for x in g["pair_evaluations"]
        if set((x["source_id_a"],x["source_id_b"]))=={"A","C"}][0]
    assert ac["independence_status"]=="UNKNOWN"
    con.close()

def test_route_blocks_fake_two_source_corroboration_from_copied_content(tmp_path):
    con=init_db(tmp_path/"route-block.sqlite3")
    _q(con)
    _d(con,"a",80,"A","NAVER_BLOG")
    _d(con,"b",80,"B","DAUM_CAFE")
    register_relationship(con,source_id_a="A",source_id_b="B",
                          relationship_type="INDEPENDENT",reviewed_by="r",
                          reason="normally separate")
    register_fingerprint(con,event_instance_id=80,source_id="A",
                         content="copied current notice")
    register_fingerprint(con,event_instance_id=80,source_id="B",
                         content="copied current notice")
    q=evaluate_verification_policy(
        con,decision_key="q",event_instance_id=80,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)
    assert q["production_action"]=="POSSIBLE_VIA_ALTERNATIVE_ROUTE"
    assert q["alternative_route"]["route_status"]=="ROUTED_POSSIBLE"
    assert q["alternative_route"]["independent_group_count"]<2
    assert any("double-counting" in x for x in q["reasons"])
    con.close()

def test_route_allows_two_graph_proven_independent_sources(tmp_path):
    con=init_db(tmp_path/"route-allow.sqlite3")
    _q(con)
    _d(con,"a",81,"A","NAVER_BLOG")
    _d(con,"b",81,"B","DAUM_CAFE")
    register_relationship(con,source_id_a="A",source_id_b="B",
                          relationship_type="INDEPENDENT",reviewed_by="김프로",
                          reason="independent original reporting")
    q=evaluate_verification_policy(
        con,decision_key="q2",event_instance_id=81,source_id=Q,rule_key=R,
        base_eligible=True,independent_source_count=1,human_confirmed=False)
    assert q["production_action"]=="ALLOW_VERIFIED_VIA_ALTERNATIVE_ROUTE"
    assert q["alternative_route"]["route_status"]=="ROUTED_VERIFIED"
    assert q["alternative_route"]["independent_group_count"]==2
    con.close()

def test_independence_and_fingerprint_audit_are_persisted(tmp_path):
    con=init_db(tmp_path/"audit.sqlite3")
    register_relationship(con,source_id_a="A",source_id_b="B",
                          relationship_type="RELATED",confidence="MEDIUM",
                          provenance="HUMAN_REVIEW",reviewed_by="reviewer",
                          reason="same organizer family")
    register_fingerprint(con,event_instance_id=90,source_id="A",
                         content="notice a",canonical_url="https://x.example/a?utm=1")
    register_fingerprint(con,event_instance_id=90,source_id="B",
                         content="notice b",canonical_url="https://y.example/b")
    evaluate_pair(con,event_instance_id=90,source_id_a="A",source_id_b="B")
    assert len(relationships(con))==1
    assert len(fingerprints(con,90))==2
    hist=independence_history(con,90)
    assert len(hist)==1
    assert hist[0]["independence_status"]=="NOT_INDEPENDENT"
    con.close()
