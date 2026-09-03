AUTHORITY_LEVELS={"PRIMARY_ORGANIZER","PRIMARY_VENUE","SECONDARY","AGGREGATOR","COMMUNITY","UNKNOWN"}
ACCESS_STATES={"OPEN","ACCESS_LIMITED","LOGIN_REQUIRED","BLOCKED","FAILED","UNKNOWN"}

def derive_source_state(*, source_role, acquisition_status=None, http_status=None, body_available=True):
    role=(source_role or "").upper()
    if role in {"PRIMARY","PRIMARY_ORGANIZER"}:
        authority="PRIMARY_ORGANIZER"
    elif role in {"PRIMARY_VENUE","VENUE"}:
        authority="PRIMARY_VENUE"
    elif role=="AGGREGATOR":
        authority="AGGREGATOR"
    elif role=="COMMUNITY":
        authority="COMMUNITY"
    elif role=="SECONDARY":
        authority="SECONDARY"
    else:
        authority="UNKNOWN"

    if http_status in (401,403):
        access="ACCESS_LIMITED"
    elif acquisition_status=="FAILED":
        access="FAILED"
    elif acquisition_status=="PARTIAL" or not body_available:
        access="LOGIN_REQUIRED"
    elif acquisition_status in {"FULL","BODY_ONLY"}:
        access="OPEN"
    else:
        access="UNKNOWN"
    return authority,access

def source_can_verify_event(authority_level, access_state):
    return authority_level in {"PRIMARY_ORGANIZER","PRIMARY_VENUE"} and access_state=="OPEN"

def source_requires_recovery(authority_level, access_state):
    return authority_level in {"PRIMARY_ORGANIZER","PRIMARY_VENUE"} and access_state in {
        "ACCESS_LIMITED","LOGIN_REQUIRED","BLOCKED","FAILED"
    }
