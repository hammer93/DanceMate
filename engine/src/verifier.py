ACCEPTABLE_SOURCE_ROLES = {"PRIMARY", "PRIMARY_VENUE", "SECONDARY"}

def verify(ev, source_role="SECONDARY"):
    ev.core_complete = bool(ev.date and ev.start_time and ev.end_time and ev.fee is not None)
    acceptable_source = source_role in ACCEPTABLE_SOURCE_ROLES
    ev.status = "VERIFIED" if (ev.core_complete and acceptable_source) else "POSSIBLE"
    return ev
