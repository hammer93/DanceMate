from pathlib import Path
from src.acquirers.snapshot_generic import SnapshotGenericPostAcquirer

ROOT=Path(__file__).resolve().parents[1]

def test_naver_snapshot_full_and_body_only():
    a=SnapshotGenericPostAcquirer(ROOT/"data"/"acquisition_snapshots",{
      "https://a/full":"naver-blog-full.html",
      "https://a/body":"naver-cafe-body-only.html",
      "https://a/block":"naver-blocked.html",
    })
    f=a.acquire(post_id=1,source_id="SRC-N-001",url="https://a/full")
    assert f.status=="FULL" and len(f.poster_candidates)>=1
    b=a.acquire(post_id=2,source_id="SRC-N-002",url="https://a/body")
    assert b.status=="BODY_ONLY"
    x=a.acquire(post_id=3,source_id="SRC-N-001",url="https://a/block")
    assert x.status=="PARTIAL" and x.error_code=="BODY_UNAVAILABLE"
