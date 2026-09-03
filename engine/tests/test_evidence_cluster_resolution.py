from datetime import datetime, timezone

import pytest

from src.database import (
    init_db,upsert_decision_outcome_evidence,decision_quality_rows,
    backlog_row,update_backlog_status,decision_evidence_cluster_row
)
from src.decision_outcome_evidence import confirm_evidence
from src.evidence_cluster_resolution import (
    resolve_clusters,cluster_list,attribute_root_causes,root_cause_list,
    sync_root_cause_backlog,closure_check,close_cluster,closure_history
)

GOAL="FIELD_QUALITY"

def _evidence(con, *, key,event_id,source="USER_FEEDBACK",
              critical="FALSE_VERIFIED",truth="EVENT_DID_NOT_OCCUR",
              outcome="FAILURE",confidence="HIGH"):
    eid,_=upsert_decision_outcome_evidence(
        con,evidence_key=key,event_instance_id=event_id,change_id=None,
        goal_profile=GOAL,evidence_type="ARRIVED_NO_EVENT",
        proposed_outcome=outcome,proposed_event_truth=truth,
        proposed_critical_error_type=critical,source_kind=source,
        source_ref=key,confidence=confidence,user_impact=1.0,
        core_relevance=1.0,evidence={"key":key})
    return eid

def test_two_pending_sources_form_open_cluster_not_resolved(tmp_path):
    con=init_db(tmp_path/"pending.sqlite3")
    _evidence(con,key="a",event_id=1,source="USER_FEEDBACK")
    _evidence(con,key="b",event_id=1,source="EVENT_REVISION")
    r=resolve_clusters(con)
    assert r["cluster_count"]==1
    c=cluster_list(con)[0]
    assert c["status"]=="OPEN"
    assert c["independent_source_count"]==2
    assert c["resolution_confidence"]=="HIGH_CORROBORATED_PENDING"
    assert c["resolved_outcome"] is None
    con.close()

def test_human_confirmation_resolves_cluster_and_attributes_false_verified(tmp_path):
    con=init_db(tmp_path/"confirmed.sqlite3")
    eid=_evidence(con,key="confirmed",event_id=11)
    result=confirm_evidence(
        con,evidence_id=eid,decision="CONFIRM",
        reviewer="김프로",reason="현장 도착 후 행사 없음")
    assert result["status"]=="CONFIRMED"
    clusters=cluster_list(con)
    assert len(clusters)==1
    c=clusters[0]
    assert c["status"]=="CONFIRMED_CASE"
    assert c["severity"]=="CRITICAL"
    assert c["resolved_outcome"]=="FAILURE"
    attrs=root_cause_list(con,c["cluster_id"])
    assert len(attrs)==1
    assert attrs[0]["category"]=="VERIFICATION_FALSE_POSITIVE"
    assert attrs[0]["component"]=="VERIFICATION_GATE"
    assert attrs[0]["status"]=="CONFIRMED_ATTRIBUTION"
    assert len(decision_quality_rows(con,GOAL))==1
    con.close()

def test_repeated_confirmed_critical_root_cause_creates_one_backlog(tmp_path):
    con=init_db(tmp_path/"backlog.sqlite3")
    for event_id in (21,22):
        eid=_evidence(con,key=f"fv-{event_id}",event_id=event_id)
        confirm_evidence(
            con,evidence_id=eid,decision="CONFIRM",
            reviewer="operator",reason="confirmed field report")

    sync=sync_root_cause_backlog(con,actor="root-cause-engine")
    attrs=root_cause_list(con)
    backlog_ids={a["backlog_id"] for a in attrs if a["backlog_id"]}
    assert len(backlog_ids)==1
    bid=next(iter(backlog_ids))
    b=backlog_row(con,bid)
    assert b["priority"]=="P1"
    assert b["field_name"]=="event_status"
    assert "VERIFICATION_FALSE_POSITIVE" in b["title"]
    assert any(x.get("backlog_id")==bid for x in sync["linked"])
    con.close()

def test_single_critical_root_cause_does_not_create_backlog_yet(tmp_path):
    con=init_db(tmp_path/"single.sqlite3")
    eid=_evidence(con,key="single",event_id=31)
    confirm_evidence(
        con,evidence_id=eid,decision="CONFIRM",
        reviewer="operator",reason="confirmed")
    r=sync_root_cause_backlog(con)
    assert not [a for a in root_cause_list(con) if a["backlog_id"]]
    assert any(x.get("reason")=="repeat_threshold_not_met" for x in r["skipped"])
    con.close()

def test_critical_closure_blocked_until_remediation_verified_then_human_close(tmp_path):
    con=init_db(tmp_path/"closure.sqlite3")
    for event_id in (41,42):
        eid=_evidence(con,key=f"closure-{event_id}",event_id=event_id)
        confirm_evidence(
            con,evidence_id=eid,decision="CONFIRM",
            reviewer="operator",reason="confirmed")

    sync_root_cause_backlog(con)
    clusters=cluster_list(con)
    c=clusters[0]
    attrs=root_cause_list(con,c["cluster_id"])
    bid=attrs[0]["backlog_id"]
    assert bid is not None

    blocked=closure_check(con,c["cluster_id"],actor="gate")
    assert blocked["status"]=="BLOCKED"
    assert blocked["open_backlog_count"]==1

    update_backlog_status(
        con,bid,to_status="VERIFIED",actor="tester",note="regression verified")
    ready=closure_check(con,c["cluster_id"],actor="gate")
    assert ready["status"]=="READY_FOR_CLOSURE"

    closed=close_cluster(
        con,c["cluster_id"],actor="김프로",reason="재발방지 검증 완료")
    assert closed["closure_status"]=="CLOSED"
    assert decision_evidence_cluster_row(con,c["cluster_id"])["closure_status"]=="CLOSED"
    assert len(closure_history(con,c["cluster_id"]))>=3
    con.close()

def test_cluster_cannot_close_when_not_ready(tmp_path):
    con=init_db(tmp_path/"notready.sqlite3")
    _evidence(con,key="open",event_id=51)
    resolve_clusters(con)
    c=cluster_list(con)[0]
    with pytest.raises(ValueError):
        close_cluster(con,c["cluster_id"],actor="operator")
    con.close()

def test_attribution_is_idempotent(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3")
    eid=_evidence(con,key="idem",event_id=61)
    confirm_evidence(
        con,evidence_id=eid,decision="CONFIRM",
        reviewer="operator",reason="confirmed")
    attribute_root_causes(con)
    attribute_root_causes(con)
    assert len(root_cause_list(con))==1
    con.close()
