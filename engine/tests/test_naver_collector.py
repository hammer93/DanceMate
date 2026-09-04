from pathlib import Path
from src.collectors.naver import (API_HUB_BASE, ENDPOINTS, MissingNaverCredentials,
                                  NaverSearchCollector, load_naver_snapshot)

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


# --- NAVER API HUB, not the legacy Search API -------------------------------

def test_the_collector_talks_to_api_hub_and_never_the_legacy_host():
    """A different host and different headers. Mixing them authenticates nothing."""
    import inspect

    from src.collectors import naver

    source = inspect.getsource(naver)
    assert "naverapihub.apigw.ntruss.com" in source
    for legacy in ("openapi.naver.com", "X-Naver-Client-Id", "X-Naver-Client-Secret"):
        assert legacy not in source, legacy


def test_each_kind_maps_to_an_api_hub_search_path():
    collector = NaverSearchCollector(client_id="id", client_secret="secret")
    assert collector._endpoint("blog") == API_HUB_BASE + "/search/v1/blog"
    assert collector._endpoint("cafe") == API_HUB_BASE + "/search/v1/cafearticle"
    assert collector._endpoint("web") == API_HUB_BASE + "/search/v1/webkr"


def test_an_unserved_search_is_refused_by_name():
    """news and local answer 401 for these credentials; do not offer them."""
    collector = NaverSearchCollector(client_id="id", client_secret="secret")
    for kind in ("news", "local", "doc"):
        assert kind not in ENDPOINTS
        try:
            collector._endpoint(kind)
            assert False, kind
        except ValueError as exc:
            assert kind in str(exc)


def test_the_request_carries_the_gateway_headers(monkeypatch):
    """The one thing that actually had to change. Assert it on the request."""
    import json
    import urllib.request

    sent = {}

    class _Response:
        def read(self):
            return json.dumps({"items": []}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _fake_urlopen(request, timeout=None):
        sent["url"] = request.full_url
        sent["headers"] = dict(request.headers)
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    NaverSearchCollector(client_id="an-id", client_secret="a-secret").search(
        "밀롱가", kind="blog", display=3)

    # urllib title-cases header names.
    headers = {k.lower(): v for k, v in sent["headers"].items()}
    assert headers["x-ncp-apigw-api-key-id"] == "an-id"
    assert headers["x-ncp-apigw-api-key"] == "a-secret"
    assert "x-naver-client-id" not in headers
    assert "x-naver-client-secret" not in headers
    assert sent["url"].startswith(API_HUB_BASE + "/search/v1/blog?")
