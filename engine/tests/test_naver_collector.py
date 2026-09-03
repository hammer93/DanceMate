from pathlib import Path
from src.collectors.naver import load_naver_snapshot, NaverSearchCollector, MissingNaverCredentials

ROOT=Path(__file__).resolve().parents[1]

def test_naver_blog_snapshot_normalizes_html_and_date():
    rows=load_naver_snapshot(ROOT/"data"/"collector_snapshots"/"naver-blog-sample.json",
        kind="blog",source_id="SRC-N-001",query="밀롱가")
    assert len(rows)==2
    assert "<b>" not in rows[0].title
    assert rows[0].published_at=="2026-08-21"
    assert rows[0].platform=="NAVER_BLOG"

def test_naver_cafe_snapshot():
    rows=load_naver_snapshot(ROOT/"data"/"collector_snapshots"/"naver-cafe-sample.json",
        kind="cafe",source_id="SRC-N-002",query="밀롱가")
    assert len(rows)==1
    assert rows[0].platform=="NAVER_CAFE"

def test_live_collector_requires_credentials(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID",raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET",raising=False)
    c=NaverSearchCollector(client_id=None,client_secret=None)
    try:
        c.search("밀롱가",kind="blog")
        assert False
    except MissingNaverCredentials:
        pass
