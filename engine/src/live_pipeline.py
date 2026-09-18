from .classifier import classify_with_image_evidence
from .extractor import DATE_PATTERNS, extract_schedule, extract_single, extract_with_image_fallback
from .verifier import verify
from .database import persist_events


# Post types that describe something a dancer can turn up to. CLASS and OTHER
# are not here: a lesson advert and a season-ticket notice are real posts and
# not events. SOCIAL_WITH_CLASS is, because a workshop weekend with a Saturday
# night party is a night out with a lesson attached, not a lesson.
EVENT_CLASSIFICATIONS = {
    "MILONGA", "MILONGA_WITH_CLASS", "SOCIAL", "SOCIAL_WITH_CLASS",
}


def _dated_class_instance(post) -> bool:
    """An actual lesson date, not a registration/payment deadline."""
    import re

    title = post.title or ""
    body = post.body or ""
    if re.search(r"강습|개강|클래스|워크숍|워크샵|lesson|workshop", title, re.I):
        if any(pattern.search(title) for pattern in DATE_PATTERNS) and not re.search(
            r"신청|입금|마감", title
        ):
            return True
    for match in re.finditer(r"(?:수업|강습)?\s*일정\s*[:：]|개강일\s*[:：]|수업일\s*[:：]",
                              body):
        segment = body[match.end():match.end() + 90]
        if any(pattern.search(segment) for pattern in DATE_PATTERNS):
            return True
    return False


def process_discovered_post(con, post, source_role="SECONDARY", image_texts=None,
                            trusted_classification_texts=None):
    """``image_texts`` (v0.81.3): already OCR'd, PII-redacted
    ``(image_ref, text)`` pairs the runtime fetched for this post, used only
    to fill a date/time/fee the body left missing - see
    extractor.extract_with_image_fallback(). Never consulted for
    classification itself.

    ``trusted_classification_texts`` (v0.84.4): a - usually much smaller -
    subset of the same images, already restricted by the runtime to what its
    own gate calls trustworthy for *classification*: real poster candidates
    that OCR'd successfully, are not a logo/nav asset, and carry enough text
    to mean something. classify_with_image_evidence() applies its own,
    independent, stricter checks on top of that (Section 9's multi-signal
    requirement, Section 12's text-rich-stays-unchanged rule, Section 15's
    multi-event refusal) before ever letting one promote a classification -
    see its own docstring. An image-only post that fails every one of those
    checks classifies exactly as it did before this parameter existed.

    ``post.known_event_type`` (v0.80, RawPostRecord): admissible when the
    collector's own page/section structure already guarantees the event
    type - classify()'s own docstring already calls this "Source Registry /
    known series context", it was just never wired up from here. A brand
    name with no descriptive word in it ("디디디", "바모스") reads as OTHER
    by keyword alone even though it came from a site's own dedicated
    milonga-listing page; a collector that actually knows better can set
    this on the RawPostRecord it hands in, skipping the guess entirely.
    Defaults to None on RawPostRecord, which is exactly today's keyword-
    guessing behaviour - unchanged for every post that does not set it.
    """
    classification, image_evidence_ref = classify_with_image_evidence(
        post.title, post.body,
        trusted_image_texts=trusted_classification_texts,
        known_event_type=getattr(post, "known_event_type", None),
        published=getattr(post, "published_at", None),
        event_terms=getattr(post, "event_terms", None),
    )
    class_instance = (classification == "CLASS"
                      and getattr(post, "class_event_opt_in", False)
                      and _dated_class_instance(post))
    if classification not in EVENT_CLASSIFICATIONS and not class_instance:
        return {"classification": classification, "events": []}
    # v0.96.0: a schedule post ("9월 소셜 일정: 9/5 ... 9/12 ... 9/19") is one
    # candidate per dated program; anything less clear-cut stays one
    # candidate with MULTI_EVENT_CONTEXT for a person, exactly as before.
    scheduled = extract_schedule(
        post.title, post.body, source_role=source_role, event_type=classification,
        published=getattr(post, "published_at", None),
    ) if not class_instance else None
    if scheduled:
        for ev in scheduled:
            verify(ev, source_role=source_role)
            if post.acquisition_quality == "METADATA_ONLY" and ev.status == "VERIFIED":
                ev.status = "POSSIBLE"
        return {"classification": classification, "events": scheduled}
    ev = extract_with_image_fallback(
        post.title, post.body, source_role=source_role,
        event_type=classification,
        published=getattr(post, "published_at", None),
        image_texts=image_texts,
    )
    if image_evidence_ref:
        from .models import Evidence
        from .extractor import IMAGE_OCR

        ev.evidences.append(Evidence(
            "context", "IMAGE_CLASSIFICATION_USED", image_evidence_ref,
            evidence_type=IMAGE_OCR, source_role=source_role,
            inference=image_evidence_ref,
        ))
    verify(ev, source_role=source_role)
    # Search snippets are incomplete by definition. Never allow METADATA_ONLY to
    # independently become VERIFIED even if all three fields happen to appear.
    if post.acquisition_quality == "METADATA_ONLY" and ev.status == "VERIFIED":
        ev.status = "POSSIBLE"
    return {"classification": classification, "events": [ev]}
