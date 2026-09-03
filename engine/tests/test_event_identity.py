from src.event_identity import same_event_instance, normalize_venue

def test_event_identity_same_instance():
    a={"name":"더 피스타 밀롱가","event_date":"2026-08-22","venue":"PISTA"}
    b={"name":"THE PISTA MILONGA","event_date":"2026-08-22","venue":"더 피스타"}
    d=same_event_instance(a,b)
    assert d.match is True
    assert normalize_venue("더 피스타")=="pista"

def test_event_identity_date_mismatch_blocks_merge():
    a={"name":"화정 밀롱가","event_date":"2026-08-25","venue":"La Ventana"}
    b={"name":"화정 밀롱가","event_date":"2026-09-01","venue":"라벤따나"}
    d=same_event_instance(a,b)
    assert d.match is False and d.review_required is False
