from src.collectors.base import RawPostRecord
from src.live_pipeline import process_discovered_post

class Dummy: pass

def test_metadata_only_never_self_verifies():
    post=RawPostRecord(
        source_id="SRC-D-001", platform="DAUM_CAFE", source_url="https://example.invalid/1",
        title="8/22 더 피스타 밀롱가", body="19:00-23:00 입장료 13,000원 PISTA",
        published_at="2026-08-18", acquisition_quality="METADATA_ONLY")
    r=process_discovered_post(Dummy(),post,"SECONDARY")
    assert r["events"][0].core_complete is True
    assert r["events"][0].status=="POSSIBLE"
