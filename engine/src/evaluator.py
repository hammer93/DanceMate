from .fixtures import FIXTURES
from .classifier import classify
from .extractor import extract_single, extract_ocho_weekly
from .verifier import verify

SOURCE_IDS = {"PISTA":"SRC-D-001","ONADA":"SRC-F-002","OCHO":"SRC-F-001","LESSON":"SRC-D-001"}

def process_fixture(key, fx):
    c = classify(fx["title"], fx["body"], fx.get("known_event_type"))
    if c == "CLASS":
        return c, []
    published = fx.get("published")
    events = (
        extract_ocho_weekly(fx["title"], fx["body"], published=published)
        if key == "OCHO"
        else [extract_single(fx["title"], fx["body"],
                             source_role=fx.get("source_role", "SECONDARY"),
                             published=published)]
    )
    for ev in events:
        verify(ev, source_role=fx.get("source_role","SECONDARY"))
    return c, events


def run_gate1_replay():
    results=[]
    for key, fx in FIXTURES.items():
        c, events = process_fixture(key, fx)
        exp=fx["expected"]
        ok = c == exp["classification"] and len(events)==exp["count"]
        if events and "status" in exp:
            ok = ok and all(ev.status==exp["status"] for ev in events)
        if key in {"PISTA","ONADA"} and events:
            ev=events[0]
            ok = ok and ev.date==exp["date"] and ev.start_time==exp["start"] and ev.end_time==exp["end"] and ev.fee==exp["fee"]
        results.append({"fixture":key,"classification":c,"events":[e.to_dict() for e in events],"pass":ok})
    return results
