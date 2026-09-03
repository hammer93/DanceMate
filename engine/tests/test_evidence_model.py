from src.evidence_model import build_field_state,determine_event_confidence,p0_validate

def test_expected_fee_does_not_become_verified():
    f=build_field_state("fee",recurring_value="13000")
    assert f.confidence=="EXPECTED" and f.expected_value=="13000" and f.verified_value is None

def test_event_verified_without_fee_verified():
    d=build_field_state("date",current_value="2026-08-27",same_occurrence_verified=True)
    v=build_field_state("venue",current_value="PISTA",same_occurrence_verified=True)
    f=build_field_state("fee",recurring_value="13000")
    ec=determine_event_confidence(date_state=d,venue_state=v,occurrence_confirmed=True,primary_or_equivalent=True,freshness_ok=True)
    assert ec=="VERIFIED"
    assert p0_validate(ec,[d,v,f])==[]

def test_expected_as_verified_p0():
    d=build_field_state("date",current_value="2026-08-27",same_occurrence_verified=True)
    v=build_field_state("venue",current_value="PISTA",same_occurrence_verified=True)
    f=build_field_state("fee",recurring_value="13000"); f.confidence="VERIFIED"
    errors=p0_validate("VERIFIED",[d,v,f])
    assert any(e["code"]=="FALSE_FIELD_VERIFIED" for e in errors)
