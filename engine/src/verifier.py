ACCEPTABLE_SOURCE_ROLES = {"PRIMARY", "PRIMARY_VENUE", "SECONDARY"}


def _text_evidenced(ev, field_name: str) -> bool:
    """True when `field_name` (date/time/fee) is backed by the post's own
    text, not only an image OCR fallback (v0.81.3).

    A poster image is a lower-confidence, secondary read even when OCR is
    accurate - confidence never buys VERIFIED. Every evidence row before
    v0.81.3 was TEXT by construction, so this is a no-op for anything that
    predates image fallback.
    """
    matches = [e for e in ev.evidences if e.field == field_name]
    return bool(matches) and matches[-1].evidence_type != "IMAGE_OCR"


def verify(ev, source_role="SECONDARY"):
    ev.core_complete = bool(
        ev.date and ev.start_time and ev.end_time and ev.fee is not None
        and _text_evidenced(ev, "date")
        and _text_evidenced(ev, "time")
        and _text_evidenced(ev, "fee")
    )
    acceptable_source = source_role in ACCEPTABLE_SOURCE_ROLES
    ev.status = "VERIFIED" if (ev.core_complete and acceptable_source) else "POSSIBLE"
    return ev
