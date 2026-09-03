from src.event_identity import normalize_event_name, same_event_instance

def test_identity_ignores_date_rendering_in_title():
    assert normalize_event_name("8/22 더 피스타 밀롱가") == "pista"
    assert normalize_event_name("8월 22일 더 피스타 밀롱가") == "pista"

    a={"name":"8/22 더 피스타 밀롱가","event_date":"2026-08-22","venue":"PISTA"}
    b={"name":"8월 22일 더 피스타 밀롱가","event_date":"2026-08-22","venue":"더 피스타"}
    assert same_event_instance(a,b).match is True
