from dataclasses import dataclass

EVENT_CONFIDENCE={"DISCOVERED","POSSIBLE","HIGH_CONFIDENCE","VERIFIED","CANCELLED","CONFLICT"}
FIELD_CONFIDENCE={"VERIFIED","EXPECTED","INFERRED","CONFLICT","UNKNOWN"}

@dataclass
class FieldState:
    field_name:str
    value:str|None
    confidence:str
    expected_value:str|None=None
    verified_value:str|None=None
    source_scope:str|None=None
    evidence_ids:list|None=None

def build_field_state(field_name, *, current_value=None, same_occurrence_verified=False,
                      recurring_value=None, inferred_value=None, conflict=False,
                      source_scope=None, evidence_ids=None):
    if conflict:
        return FieldState(field_name,current_value,"CONFLICT",recurring_value,None,source_scope,evidence_ids or [])
    if same_occurrence_verified and current_value is not None:
        return FieldState(field_name,current_value,"VERIFIED",recurring_value,current_value,source_scope,evidence_ids or [])
    if recurring_value is not None:
        return FieldState(field_name,recurring_value,"EXPECTED",recurring_value,None,source_scope,evidence_ids or [])
    if inferred_value is not None:
        return FieldState(field_name,inferred_value,"INFERRED",None,None,source_scope,evidence_ids or [])
    return FieldState(field_name,current_value,"UNKNOWN",recurring_value,None,source_scope,evidence_ids or [])

def determine_event_confidence(*, date_state, venue_state, occurrence_confirmed=False,
                               primary_or_equivalent=False, cancellation=False,
                               conflict=False, freshness_ok=True):
    if cancellation: return "CANCELLED"
    if conflict: return "CONFLICT"
    if occurrence_confirmed and primary_or_equivalent and freshness_ok and \
       date_state.confidence=="VERIFIED" and venue_state.confidence=="VERIFIED":
        return "VERIFIED"
    if occurrence_confirmed and date_state.confidence=="VERIFIED" and venue_state.confidence=="VERIFIED":
        return "HIGH_CONFIDENCE"
    if date_state.confidence=="VERIFIED" or venue_state.confidence=="VERIFIED":
        return "POSSIBLE"
    return "DISCOVERED"

def p0_validate(event_confidence, field_states):
    errors=[]
    by={f.field_name:f for f in field_states}
    for fs in field_states:
        if fs.confidence=="VERIFIED" and fs.verified_value is None:
            errors.append({"code":"FALSE_FIELD_VERIFIED","field":fs.field_name})
        if fs.confidence=="VERIFIED" and fs.expected_value is not None and fs.verified_value is None:
            errors.append({"code":"EXPECTED_AS_VERIFIED","field":fs.field_name})
    if event_confidence=="VERIFIED":
        for required in ("date","venue"):
            fs=by.get(required)
            if fs is None or fs.confidence!="VERIFIED":
                errors.append({"code":"FALSE_EVENT_VERIFIED","field":required})
    return errors
