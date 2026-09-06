from .classifier import classify
from .extractor import extract_single, extract_with_image_fallback
from .verifier import verify
from .database import persist_events


# Post types that describe something a dancer can turn up to. CLASS and OTHER
# are not here: a lesson advert and a season-ticket notice are real posts and
# not events. SOCIAL_WITH_CLASS is, because a workshop weekend with a Saturday
# night party is a night out with a lesson attached, not a lesson.
EVENT_CLASSIFICATIONS = {
    "MILONGA", "MILONGA_WITH_CLASS", "SOCIAL", "SOCIAL_WITH_CLASS",
}


def process_discovered_post(con, post, source_role="SECONDARY", image_texts=None):
    """``image_texts`` (v0.81.3): already OCR'd, PII-redacted
    ``(image_ref, text)`` pairs the runtime fetched for this post, used only
    to fill a date/time/fee the body left missing - see
    extractor.extract_with_image_fallback().

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
    classification = classify(
        post.title, post.body,
        known_event_type=getattr(post, "known_event_type", None),
    )
    if classification not in EVENT_CLASSIFICATIONS:
        return {"classification": classification, "events": []}
    ev = extract_with_image_fallback(
        post.title, post.body, source_role=source_role,
        event_type=classification,
        published=getattr(post, "published_at", None),
        image_texts=image_texts,
    )
    verify(ev, source_role=source_role)
    # Search snippets are incomplete by definition. Never allow METADATA_ONLY to
    # independently become VERIFIED even if all three fields happen to appear.
    if post.acquisition_quality == "METADATA_ONLY" and ev.status == "VERIFIED":
        ev.status = "POSSIBLE"
    return {"classification": classification, "events": [ev]}
