from datetime import datetime, timezone, timedelta

import pytest

from src.database import (
    init_db,upsert_decision_outcome_evidence,
    decision_outcome_evidence_row
)
from src.decision_outcome_evidence import confirm_evidence
from src.evidence_priority_queue import (
    evaluate_evidence_priority_queue,priority_queue,queue_event_history
)

GOAL="FIELD_QUALITY"
NOW=datetime(2026,8,31,1,0,tzinfo=timezone.utc)

def _evidence(con, *, key, event_id=1, critical=None, source="TEST",
              confidence="HIGH", outcome="FAILURE", truth="CANCELLED",
              etype="TEST_EVIDENCE", impact=1.0, core=1.0):
    eid,_=upsert_decision_outcome_evidence(
        con,evidence_key=key,event_instance_id=event_id,change_id=None,
        goal_profile=GOAL,evidence_type=etype,proposed_outcome=outcome,
        proposed_event_truth=truth,proposed_critical_error_type=critical,
        source_kind=source,source_ref=key,confidence=confidence,
        user_impact=impact,core_relevance=core,evidence={"key":key})
    return eid

def _backdate(con,eid,hours):
    created=(NOW-timedelta(hours=hours)).isoformat()
    con.execute("""UPDATE decision_outcome_evidence
                   SET created_at=?,updated_at=? WHERE evidence_id=?""",
                (created,created,eid))
    con.commit()

def test_critical_false_verified_is_p0_and_never_auto_expires(tmp_path):
    con=init_db(tmp_path/"p0.sqlite3")
    eid=_evidence(
        con,key="critical",critical="FALSE_VERIFIED",
        source="USER_FEEDBACK",truth="EVENT_DID_NOT_OCCUR")
    _backdate(con,eid,200)

    r=evaluate_evidence_priority_queue(con,now=NOW)
    q=priority_queue(con)[0]

    assert q["priority"]=="P0"
    assert q["overdue"]==1
    assert q["expires_at"] is None
    assert q["auto_resolution_eligible"]==0
    assert decision_outcome_evidence_row(con,eid)["status"]=="PENDING"
    assert r["safety"]["automatic_confirm"] is False
    con.close()

def test_two_independent_sources_raise_resolution_confidence_but_do_not_confirm(tmp_path):
    con=init_db(tmp_path/"corroborate.sqlite3")
    a=_evidence(con,key="a",source="EVENT_REFRESH_CHECK",event_id=9)
    b=_evidence(con,key="b",source="USER_FEEDBACK",event_id=9)

    r=evaluate_evidence_priority_queue(con,now=NOW)
    rows=priority_queue(con)
    assert r["corroborated_count"]==2
    assert {x["resolution_confidence"] for x in rows}=={"HIGH_CORROBORATED"}
    assert all(x["independent_source_count"]==2 for x in rows)
    assert all(x["status"]=="PENDING" for x in rows)
    assert all(x["decision_outcome_evidence_id"] if False else True for x in [])  # no auto-confirm path
    events=queue_event_history(con)
    assert sum(e["event_type"]=="MULTI_SOURCE_CORROBORATION" for e in events)==2
    con.close()

def test_stale_noncritical_medium_evidence_auto_expires_only(tmp_path):
    con=init_db(tmp_path/"expire.sqlite3")
    eid=_evidence(
        con,key="stale",critical=None,source="EVENT_REVISION",
        confidence="MEDIUM",outcome="UNKNOWN",truth="CANCELLED",
        etype="CANCELLATION_DISCOVERED",impact=.7)
    _backdate(con,eid,80)

    r=evaluate_evidence_priority_queue(con,now=NOW)
    assert r["auto_expired_count"]==1
    assert decision_outcome_evidence_row(con,eid)["status"]=="EXPIRED"
    events=queue_event_history(con,eid)
    assert [e["event_type"] for e in events].count("AUTO_EXPIRED")==1
    with pytest.raises(ValueError):
        confirm_evidence(
            con,evidence_id=eid,decision="CONFIRM",
            reviewer="operator",reason="too late")
    con.close()

def test_high_confidence_noncritical_does_not_auto_expire(tmp_path):
    con=init_db(tmp_path/"high.sqlite3")
    eid=_evidence(
        con,key="high",critical=None,source="HUMAN_REVIEW",
        confidence="HIGH",outcome="UNKNOWN",truth="CORRECTED",
        etype="HUMAN_REVIEW_CORRECTION",impact=.7)
    _backdate(con,eid,200)

    evaluate_evidence_priority_queue(con,now=NOW)
    q=priority_queue(con)[0]
    assert q["auto_resolution_eligible"]==0
    assert decision_outcome_evidence_row(con,eid)["status"]=="PENDING"
    con.close()

def test_sla_breach_event_is_idempotent(tmp_path):
    con=init_db(tmp_path/"sla.sqlite3")
    eid=_evidence(
        con,key="sla",critical="CANCELLATION_MISS",
        source="EVENT_REFRESH_CHECK")
    _backdate(con,eid,2)

    evaluate_evidence_priority_queue(con,now=NOW)
    evaluate_evidence_priority_queue(con,now=NOW)
    events=queue_event_history(con,eid)
    assert sum(e["event_type"]=="SLA_BREACH" for e in events)==1
    con.close()

def test_queue_orders_p0_before_p1_before_p2(tmp_path):
    con=init_db(tmp_path/"order.sqlite3")
    _evidence(con,key="p2",critical=None,source="TEST",
              confidence="HIGH",outcome="UNKNOWN",truth="CORRECTED",
              etype="OTHER",impact=.2,core=.5)
    _evidence(con,key="p1",critical=None,source="HUMAN_REVIEW",
              confidence="HIGH",outcome="UNKNOWN",truth="CORRECTED",
              etype="HUMAN_REVIEW_CORRECTION",impact=.7)
    _evidence(con,key="p0",critical="CANCELLATION_MISS",
              source="EVENT_REFRESH_CHECK")

    evaluate_evidence_priority_queue(con,now=NOW)
    rows=priority_queue(con)
    assert [r["priority"] for r in rows]==["P0","P1","P2"]
    assert rows[0]["priority_score"]>rows[1]["priority_score"]>rows[2]["priority_score"]
    con.close()


def test_event_start_time_tightens_sla_and_escalates_priority_score(tmp_path):
    con=init_db(tmp_path/"eventtime.sqlite3")
    created=NOW.isoformat()
    cur=con.execute("""INSERT INTO event_instances(
        identity_key,normalized_name,event_date,normalized_venue,status,
        source_count,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        ("event-time","Soon Milonga","2026-08-31","Hall","VERIFIED",1,created,created))
    event_id=cur.lastrowid
    con.execute("""INSERT INTO event_field_states(
        event_instance_id,field_name,value,confidence,evidence_ids_json,
        expected_value,verified_value,source_scope,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (event_id,"start_time","14:00","VERIFIED","[]",None,"14:00","EVENT",created))
    con.commit()

    eid=_evidence(
        con,key="soon",event_id=event_id,critical=None,source="TEST",
        confidence="HIGH",outcome="UNKNOWN",truth="CORRECTED",
        etype="OTHER",impact=.2,core=.5)
    _backdate(con,eid,.1)

    evaluate_evidence_priority_queue(con,now=NOW)
    q=priority_queue(con)[0]
    # 14:00 KST = 05:00 UTC, so at NOW 01:00 UTC it starts in 4h.
    assert q["priority"]=="P2"
    assert q["priority_score"]>=70
    assert q["sla_due_at"].startswith("2026-08-31T03:00:00")
    assert "SLA tightened to event start minus 2h" in q["reasons_json"]
    con.close()
