from pathlib import Path
from src.acquirers.daum_post import extract_article_payload
from src.acquirers.snapshot import SnapshotDaumPostAcquirer

ROOT=Path(__file__).resolve().parents[1]

def test_extract_full_body_and_poster():
    html=(ROOT/"data"/"acquisition_snapshots"/"daum-full-pista.html").read_text(encoding="utf-8")
    text,images,posters=extract_article_payload(html,"https://snapshot.local/daum/pista")
    assert "입장료 13,000원" in text
    assert "19:00-23:00" in text
    assert len(images)==1 and len(posters)==1
    assert posters[0].endswith("pista-poster.jpg")

def test_snapshot_acquirer_partial_shell():
    acq=SnapshotDaumPostAcquirer(ROOT/"data"/"acquisition_snapshots",
        {"https://x/login":"daum-partial-login-shell.html"})
    r=acq.acquire(post_id=1,source_id="SRC-D-001",url="https://x/login")
    assert r.status=="PARTIAL"
    assert r.error_code=="BODY_UNAVAILABLE"
