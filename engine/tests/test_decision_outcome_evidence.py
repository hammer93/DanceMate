from datetime import datetime, timezone

from src.database import init_db,decision_quality_rows
from src.decision_outcome_evidence import (
    scan_automatic_evidence,record_visit_feedback_evidence,
    confirm_evidence,evidence_list,confirmation_history
)

GOAL="FIELD_QUALITY"

def _event(con,status="VERIFIED"):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO event_instances(
        identity_key,normalized_name,event_date,normalized_venue,status,
        source_count,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        ("evt-test","Test Milonga","2026-08-31","Test Hall",status,1,now,now))
    con.commit()
    return cur.lastrowid

def test_refresh_critical_miss_creates_pending_candidate_once(tmp_path):
    con=init_db(tmp_path/"scan.sqlite3")
    eid=_event(con,"CANCELLED")
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO event_refresh_checks(
        event_instance_id,checked_at,scheduled_event_date,hours_before_start,
        status_before,status_after,change_detected,cancellation_detected,
        critical_miss,source_id,notes)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (eid,now,"2026-08-31",2.0,"VERIFIED","CANCELLED",1,1,1,"SRC-X","late cancel"))
    con.commit()

    first=scan_automatic_evidence(con,GOAL)
    second=scan_automatic_evidence(con,GOAL)

    assert first["created_count"]==1
    assert second["created_count"]==0
    rows=evidence_list(con,"PENDING",GOAL)
    assert len(rows)==1
    assert rows[0]["proposed_critical_error_type"]=="CANCELLATION_MISS"
    assert rows[0]["proposed_outcome"]=="FAILURE"
    con.close()

def test_confirmed_critical_evidence_creates_decision_quality_observation(tmp_path):
    con=init_db(tmp_path/"confirm.sqlite3")
    eid=_event(con)
    ev=record_visit_feedback_evidence(
        con,event_instance_id=eid,feedback="ARRIVED_NO_EVENT",
        goal_profile=GOAL,note="현장 도착했으나 행사 없음")
    assert ev["status"]=="PENDING"
    assert len(decision_quality_rows(con,GOAL))==0

    result=confirm_evidence(
        con,evidence_id=ev["evidence_id"],decision="CONFIRM",
        reviewer="김프로",reason="현장 확인")
    assert result["status"]=="CONFIRMED"
    rows=decision_quality_rows(con,GOAL)
    assert len(rows)==1
    assert rows[0]["decision_outcome"]=="FAILURE"
    assert rows[0]["critical_error_type"]=="FALSE_VERIFIED"
    assert rows[0]["event_id"]==eid
    con.close()

def test_reject_does_not_create_decision_quality_observation(tmp_path):
    con=init_db(tmp_path/"reject.sqlite3")
    eid=_event(con)
    ev=record_visit_feedback_evidence(
        con,event_instance_id=eid,feedback="CANCELLED_BEFORE_VISIT",
        goal_profile=GOAL,note="전달 오류 가능")
    result=confirm_evidence(
        con,evidence_id=ev["evidence_id"],decision="REJECT",
        reviewer="operator",reason="오탐")
    assert result["status"]=="REJECTED"
    assert len(decision_quality_rows(con,GOAL))==0
    assert confirmation_history(con,ev["evidence_id"])[-1]["decision"]=="REJECT"
    con.close()

def test_hold_can_later_be_confirmed(tmp_path):
    con=init_db(tmp_path/"hold.sqlite3")
    eid=_event(con)
    ev=record_visit_feedback_evidence(
        con,event_instance_id=eid,feedback="VISITED_HELD",goal_profile=GOAL)
    held=confirm_evidence(
        con,evidence_id=ev["evidence_id"],decision="HOLD",
        reviewer="operator",reason="추가 확인")
    assert held["status"]=="HOLD"

    confirmed=confirm_evidence(
        con,evidence_id=ev["evidence_id"],decision="CONFIRM",
        reviewer="김프로",reason="방문 확인")
    assert confirmed["status"]=="CONFIRMED"
    rows=decision_quality_rows(con,GOAL)
    assert rows[-1]["decision_outcome"]=="SUCCESS"
    assert rows[-1]["event_truth"]=="EVENT_OCCURRED"
    con.close()

def test_human_review_correction_is_automatically_discovered(tmp_path):
    con=init_db(tmp_path/"review.sqlite3")
    eid=_event(con)
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO human_review_actions(
        action_uuid,review_type,target_id,event_instance_id,field_name,recovery_id,
        action,actor,reason,old_value_json,new_value_json,evidence_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("act-test","EVENT",eid,eid,None,None,"REJECT","operator",
         "잘못된 행사","{}","{}","{}",now))
    con.commit()

    scan=scan_automatic_evidence(con,GOAL)
    assert scan["created_count"]==1
    row=evidence_list(con,"PENDING",GOAL)[0]
    assert row["evidence_type"]=="HUMAN_REVIEW_CORRECTION"
    assert row["source_kind"]=="HUMAN_REVIEW"
    con.close()
