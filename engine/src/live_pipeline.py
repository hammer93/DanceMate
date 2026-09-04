from .classifier import classify
from .extractor import extract_single
from .verifier import verify
from .database import persist_events


# Post types that describe something a dancer can turn up to. CLASS and OTHER
# are not here: a lesson advert and a season-ticket notice are real posts and
# not events. SOCIAL_WITH_CLASS is, because a workshop weekend with a Saturday
# night party is a night out with a lesson attached, not a lesson.
EVENT_CLASSIFICATIONS = {
    "MILONGA", "MILONGA_WITH_CLASS", "SOCIAL", "SOCIAL_WITH_CLASS",
}


def process_discovered_post(con, post, source_role="SECONDARY"):
    classification = classify(post.title, post.body)
    if classification not in EVENT_CLASSIFICATIONS:
        return {"classification": classification, "events": []}
    ev = extract_single(post.title, post.body, source_role=source_role,
                        event_type=classification,
                        published=getattr(post, "published_at", None))
    verify(ev, source_role=source_role)
    # Search snippets are incomplete by definition. Never allow METADATA_ONLY to
    # independently become VERIFIED even if all three fields happen to appear.
    if post.acquisition_quality == "METADATA_ONLY" and ev.status == "VERIFIED":
        ev.status = "POSSIBLE"
    return {"classification": classification, "events": [ev]}
