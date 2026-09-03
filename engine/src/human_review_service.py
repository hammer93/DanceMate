import json
from .database import (
    create_human_review_action,upsert_human_review_state,get_human_review_state
)
from .evidence_model import p0_validate
from .database import get_event_field_states

VALID_ACTIONS={"APPROVE","MODIFY","REJECT","HOLD"}

def event_review_key(event_instance_id):
    return f"EVENT:{event_instance_id}"

def field_review_key(event_instance_id,field_name):
    return f"FIELD:{event_instance_id}:{field_name}"

def recovery_review_key(recovery_id):
    return f"RECOVERY:{recovery_id}"

def _state_for_action(action):
    return {
        "APPROVE":"APPROVED",
        "MODIFY":"MODIFIED",
        "REJECT":"REJECTED",
        "HOLD":"HELD",
    }[action]

def _event_snapshot(con,event_instance_id):
    r=con.execute("SELECT * FROM event_instances WHERE event_instance_id=?",(event_instance_id,)).fetchone()
    return dict(r) if r else None

def _field_snapshot(con,event_instance_id,field_name):
    r=con.execute("""SELECT * FROM event_field_states
                     WHERE event_instance_id=? AND field_name=?""",
                  (event_instance_id,field_name)).fetchone()
    return dict(r) if r else None

def _recovery_snapshot(con,recovery_id):
    r=con.execute("SELECT * FROM recovery_queue WHERE recovery_id=?",(recovery_id,)).fetchone()
    return dict(r) if r else None

def review_event(con, *, event_instance_id, action, actor="operator",
                 reason=None, new_status=None, evidence=None):
    action=action.upper()
    if action not in VALID_ACTIONS:
        raise ValueError("invalid action")
    old=_event_snapshot(con,event_instance_id)
    if not old:
        raise KeyError("event not found")

    new=dict(old)
    if action=="MODIFY":
        if not new_status:
            raise ValueError("new_status required for MODIFY")
        con.execute("UPDATE event_instances SET status=? WHERE event_instance_id=?",
                    (new_status,event_instance_id))
        con.commit()
        new=_event_snapshot(con,event_instance_id)
    elif action=="REJECT":
        con.execute("UPDATE event_instances SET status='CANCELLED' WHERE event_instance_id=?",
                    (event_instance_id,))
        con.commit()
        new=_event_snapshot(con,event_instance_id)
    elif action=="APPROVE":
        # Approval does not fabricate confidence; it acknowledges current machine state.
        new=_event_snapshot(con,event_instance_id)
    elif action=="HOLD":
        new=_event_snapshot(con,event_instance_id)

    aid,auuid=create_human_review_action(
        con,review_type="EVENT",target_id=event_instance_id,event_instance_id=event_instance_id,
        action=action,actor=actor,reason=reason,old_value=old,new_value=new,evidence=evidence
    )
    upsert_human_review_state(
        con,review_key=event_review_key(event_instance_id),review_type="EVENT",
        target_id=event_instance_id,event_instance_id=event_instance_id,
        state=_state_for_action(action),last_action_id=aid
    )
    return {"action_id":aid,"action_uuid":auuid,"state":_state_for_action(action),
            "old":old,"new":new}

def review_field(con, *, event_instance_id, field_name, action, actor="operator",
                 reason=None, new_value=None, new_confidence=None, evidence=None):
    action=action.upper()
    if action not in VALID_ACTIONS:
        raise ValueError("invalid action")
    old=_field_snapshot(con,event_instance_id,field_name)
    if not old:
        raise KeyError("field not found")
    new=dict(old)

    if action=="MODIFY":
        if new_value is None and new_confidence is None:
            raise ValueError("new_value or new_confidence required")
        confidence=new_confidence or old["confidence"]
        verified_value=old["verified_value"]
        expected_value=old["expected_value"]
        value=new_value if new_value is not None else old["value"]

        # Manual VERIFIED is allowed only with evidence recorded in audit.
        if confidence=="VERIFIED":
            if not evidence:
                raise ValueError("evidence required for manual VERIFIED")
            verified_value=str(value) if value is not None else None
        elif confidence=="EXPECTED":
            expected_value=str(value) if value is not None else expected_value
            verified_value=None
        elif confidence in {"UNKNOWN","INFERRED","CONFLICT"}:
            if confidence!="INFERRED":
                verified_value=None

        con.execute("""UPDATE event_field_states SET
            value=?,confidence=?,expected_value=?,verified_value=?,source_scope='HUMAN_REVIEW',
            updated_at=datetime('now')
            WHERE event_instance_id=? AND field_name=?""",
            (str(value) if value is not None else None,confidence,
             expected_value,verified_value,event_instance_id,field_name))
        con.commit()
        new=_field_snapshot(con,event_instance_id,field_name)
    elif action=="REJECT":
        con.execute("""UPDATE event_field_states SET
            value=NULL,confidence='UNKNOWN',verified_value=NULL,source_scope='HUMAN_REVIEW',
            updated_at=datetime('now')
            WHERE event_instance_id=? AND field_name=?""",
            (event_instance_id,field_name))
        con.commit()
        new=_field_snapshot(con,event_instance_id,field_name)
    elif action in {"APPROVE","HOLD"}:
        new=_field_snapshot(con,event_instance_id,field_name)

    aid,auuid=create_human_review_action(
        con,review_type="FIELD",target_id=event_instance_id,event_instance_id=event_instance_id,
        field_name=field_name,action=action,actor=actor,reason=reason,
        old_value=old,new_value=new,evidence=evidence
    )
    upsert_human_review_state(
        con,review_key=field_review_key(event_instance_id,field_name),review_type="FIELD",
        target_id=event_instance_id,event_instance_id=event_instance_id,field_name=field_name,
        state=_state_for_action(action),last_action_id=aid
    )
    return {"action_id":aid,"action_uuid":auuid,"state":_state_for_action(action),
            "old":old,"new":new}

def review_recovery(con, *, recovery_id, action, actor="operator",
                    reason=None, evidence=None):
    action=action.upper()
    if action not in VALID_ACTIONS:
        raise ValueError("invalid action")
    old=_recovery_snapshot(con,recovery_id)
    if not old:
        raise KeyError("recovery not found")

    if action=="APPROVE":
        new_state="RESOLVED"
    elif action=="REJECT":
        new_state="REJECTED"
    elif action=="HOLD":
        new_state="HELD"
    else:
        new_state=old["state"]

    if action!="MODIFY":
        con.execute("""UPDATE recovery_queue SET state=?,updated_at=datetime('now')
                       WHERE recovery_id=?""",(new_state,recovery_id))
        con.commit()
    new=_recovery_snapshot(con,recovery_id)

    aid,auuid=create_human_review_action(
        con,review_type="RECOVERY",target_id=recovery_id,recovery_id=recovery_id,
        action=action,actor=actor,reason=reason,old_value=old,new_value=new,evidence=evidence
    )
    upsert_human_review_state(
        con,review_key=recovery_review_key(recovery_id),review_type="RECOVERY",
        target_id=recovery_id,recovery_id=recovery_id,state=_state_for_action(action),
        last_action_id=aid
    )
    return {"action_id":aid,"action_uuid":auuid,"state":_state_for_action(action),
            "old":old,"new":new}

def validate_event_after_review(con,event_instance_id):
    event=con.execute("SELECT * FROM event_instances WHERE event_instance_id=?",(event_instance_id,)).fetchone()
    fields=[dict(x) for x in get_event_field_states(con,event_instance_id)]
    if not event:
        return []
    class Obj:
        pass
    fs=[]
    for f in fields:
        o=Obj()
        for k,v in f.items(): setattr(o,k,v)
        fs.append(o)
    return p0_validate(event["status"],fs)
