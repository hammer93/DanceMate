from src.source_state import derive_source_state,source_can_verify_event,source_requires_recovery

def test_primary_access_limited():
    a,x=derive_source_state(source_role="PRIMARY_VENUE",acquisition_status="FAILED",http_status=403,body_available=False)
    assert a=="PRIMARY_VENUE" and x=="ACCESS_LIMITED"
    assert source_can_verify_event(a,x) is False
    assert source_requires_recovery(a,x) is True

def test_primary_open_can_verify():
    a,x=derive_source_state(source_role="PRIMARY",acquisition_status="FULL",http_status=200,body_available=True)
    assert a=="PRIMARY_ORGANIZER" and x=="OPEN"
    assert source_can_verify_event(a,x) is True

def test_aggregator_open_not_primary_verifier():
    a,x=derive_source_state(source_role="AGGREGATOR",acquisition_status="FULL",http_status=200,body_available=True)
    assert a=="AGGREGATOR" and x=="OPEN"
    assert source_can_verify_event(a,x) is False
