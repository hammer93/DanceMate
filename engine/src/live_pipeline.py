from .classifier import classify
from .extractor import extract_single
from .verifier import verify
from .database import persist_events


def process_discovered_post(con, post, source_role="SECONDARY"):
    classification = classify(post.title, post.body)
    if classification in {"CLASS", "OTHER"}:
        return {"classification": classification, "events": []}
    ev = extract_single(post.title, post.body, source_role=source_role)
    verify(ev, source_role=source_role)
    # Search snippets are incomplete by definition. Never allow METADATA_ONLY to
    # independently become VERIFIED even if all three fields happen to appear.
    if post.acquisition_quality == "METADATA_ONLY" and ev.status == "VERIFIED":
        ev.status = "POSSIBLE"
    return {"classification": classification, "events": [ev]}
