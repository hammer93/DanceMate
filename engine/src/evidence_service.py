from .evidence_model import build_field_state,determine_event_confidence,p0_validate
from .database import upsert_event_field_state,get_event_field_states

def apply_evidence_model(con, *, event_instance_id, date_value, venue_value,
                         time_value=None, fee_verified=None, fee_expected=None,
                         occurrence_confirmed=False, primary_or_equivalent=False,
                         freshness_ok=True, cancellation=False, conflict=False,
                         source_scope="DAY1"):
    states=[
        build_field_state("date",current_value=date_value,same_occurrence_verified=bool(date_value),source_scope=source_scope),
        build_field_state("venue",current_value=venue_value,same_occurrence_verified=bool(venue_value),source_scope=source_scope),
        build_field_state("start_time",current_value=time_value,same_occurrence_verified=bool(time_value),source_scope=source_scope),
        build_field_state("fee",current_value=fee_verified,same_occurrence_verified=fee_verified is not None,
                          recurring_value=fee_expected,source_scope=source_scope),
    ]
    by={x.field_name:x for x in states}
    event_conf=determine_event_confidence(
        date_state=by["date"],venue_state=by["venue"],
        occurrence_confirmed=occurrence_confirmed,primary_or_equivalent=primary_or_equivalent,
        cancellation=cancellation,conflict=conflict,freshness_ok=freshness_ok
    )
    for fs in states:
        upsert_event_field_state(con,event_instance_id=event_instance_id,field_name=fs.field_name,
            value=fs.value,confidence=fs.confidence,evidence_ids=fs.evidence_ids,
            expected_value=fs.expected_value,verified_value=fs.verified_value,source_scope=fs.source_scope)
    con.execute("UPDATE event_instances SET status=? WHERE event_instance_id=?",(event_conf,event_instance_id))
    con.commit()
    return {"event_confidence":event_conf,
            "fields":{f.field_name:{"value":f.value,"confidence":f.confidence,
                                    "expected_value":f.expected_value,"verified_value":f.verified_value} for f in states},
            "p0_errors":p0_validate(event_conf,states)}

def read_evidence_model(con,event_instance_id):
    e=con.execute("SELECT * FROM event_instances WHERE event_instance_id=?",(event_instance_id,)).fetchone()
    return {"event":dict(e) if e else None,"fields":[dict(r) for r in get_event_field_states(con,event_instance_id)]}
