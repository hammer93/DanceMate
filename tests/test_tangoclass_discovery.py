"""Discovery for tangoclass.co.kr (v0.85.1): a WordPress REST API
(`/wp-json/wp/v2/posts`) that already returns full post bodies as JSON.

v0.85.2 adds event-window pagination (module docstring in
tangoclass_discovery.py has the full reasoning): a live re-check found a
real event post had scrolled off the single most-recent-10 page within 30
minutes, pushed out by two unrelated article posts. discover() now pages
backward with three independent stop conditions - an empty page, a page
whose oldest post already predates `lookback_days`, or `X-WP-TotalPages` -
plus a hard `max_pages` ceiling that applies regardless of what any of
those say.
"""

from __future__ import annotations

import io
import json

import pytest

from runtime import tangoclass_discovery as tc

LIST_URL = "https://tangoclass.co.kr/wp-json/wp/v2/posts?per_page=10"

_POSTS = [
    {
        "id": 101,
        "date": "2026-09-07T10:00:00",
        "link": "https://tangoclass.co.kr/2026/09/07/guide-practica/",
        "title": {"rendered": "9월~10월 홍대/신사 가이드 쉬라버떼까"},
        "content": {
            "rendered": "<p>Studio Ocho(홍대) 일요일 15:00-17:30, "
                        "Club Pang Tango(신사) 수요일 20:00-22:30. 회당 15,000원.</p>"
        },
    },
    {
        "id": 102,
        "date": "2026-08-19T09:00:00",
        "link": "https://tangoclass.co.kr/2026/08/19/cabeceo/",
        "title": {"rendered": "까베세오 예절 안내"},
        "content": {"rendered": "<p>탱고 사교 예절에 관한 글입니다.</p>"},
    },
    {
        "id": 103,
        "date": "2026-08-01T09:00:00",
        "link": "https://tangoclass.co.kr/2026/08/01/blank/",
        "title": {"rendered": ""},
        "content": {"rendered": "<p>제목 없는 글</p>"},
    },
]


def _payload(posts=None) -> str:
    return json.dumps(_POSTS if posts is None else posts, ensure_ascii=False)


def _post(post_id, date, title):
    return {
        "id": post_id, "date": date,
        "link": f"https://tangoclass.co.kr/p/{post_id}/",
        "title": {"rendered": title},
        "content": {"rendered": f"<p>{title} 본문</p>"},
    }


# --- parse_list(): unchanged single-page parsing ----------------------------

def test_every_post_is_returned_including_non_event_ones():
    """No genre/topic filter here - unlike danceinfo.net this organizer
    posts about tango only, and a non-event post simply produces no
    candidate downstream (the existing classifier's job, not discovery's)."""
    posts = tc.parse_list(_payload(), LIST_URL)
    assert len(posts) == 2  # the two titled posts; the blank-title one is skipped


def test_title_and_body_are_stripped_of_html():
    posts = tc.parse_list(_payload(), LIST_URL)
    guide = next(p for p in posts if "가이드" in p["title"])
    assert "<p>" not in guide["body"]
    assert "Studio Ocho" in guide["body"]
    assert "15,000원" in guide["body"]


def test_source_url_is_the_post_link():
    posts = tc.parse_list(_payload(), LIST_URL)
    guide = next(p for p in posts if "가이드" in p["title"])
    assert guide["source_url"] == "https://tangoclass.co.kr/2026/09/07/guide-practica/"


def test_wp_post_id_is_carried_for_identity():
    """Section 13: WordPress's own numeric post id, not just the URL, is the
    stable identity discover() dedups on across pages."""
    posts = tc.parse_list(_payload(), LIST_URL)
    guide = next(p for p in posts if "가이드" in p["title"])
    assert guide["wp_post_id"] == 101


def test_published_at_is_the_real_wordpress_date():
    """Unlike danceinfo.net's list JSON, WordPress's own `date` field really
    is when the post was published, not a claimed event date - safe to pass
    straight through."""
    posts = tc.parse_list(_payload(), LIST_URL)
    guide = next(p for p in posts if "가이드" in p["title"])
    assert guide["published_at"] == "2026-09-07T10:00:00"


def test_body_is_already_full_not_metadata_only():
    """The REST API already returns the complete body - no separate detail
    fetch needed, the same as Miltang's own milonga list."""
    posts = tc.parse_list(_payload(), LIST_URL)
    assert all(p["acquisition_quality"] == "FETCHED_FULL" for p in posts)


def test_a_blank_title_post_is_skipped():
    posts = tc.parse_list(_payload(), LIST_URL)
    ids = [p["source_url"] for p in posts]
    assert "https://tangoclass.co.kr/2026/08/01/blank/" not in ids


def test_a_non_array_response_raises_discovery_error():
    with pytest.raises(tc.DiscoveryError):
        tc.parse_list('{"error": "not found"}', LIST_URL)


def test_malformed_json_raises_discovery_error():
    with pytest.raises(tc.DiscoveryError):
        tc.parse_list("{not json", LIST_URL)


def test_a_post_missing_required_keys_raises_a_schema_error():
    broken = json.dumps([{"id": 1, "title": {"rendered": "x"}}])  # no link/content
    with pytest.raises(tc.DiscoveryError):
        tc.parse_list(broken, LIST_URL)


def test_an_empty_array_is_a_legitimate_empty_result_not_an_error():
    assert tc.parse_list("[]", LIST_URL) == []


# --- discover(): fetch + tag (single page) ----------------------------------

class _Resp(io.BytesIO):
    def __init__(self, body: str, total_pages=None):
        super().__init__(body.encode("utf-8"))
        self.headers = _Headers(total_pages)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class _Headers:
    def __init__(self, total_pages=None):
        self._total_pages = total_pages

    def get_content_charset(self):
        return "utf-8"

    def get(self, name, default=None):
        if name == "X-WP-TotalPages" and self._total_pages is not None:
            return str(self._total_pages)
        return default


def test_discover_tags_every_post_with_source_and_platform(monkeypatch):
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    opener = lambda request, timeout=None: _Resp(_payload(), total_pages=1)
    posts = tc.discover(LIST_URL, source_id=7, opener=opener)
    assert len(posts) == 2
    assert all(p["source_id"] == 7 and p["platform"] == "WEB" for p in posts)


def test_discover_honours_robots_disallow(monkeypatch):
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: False)
    with pytest.raises(tc.DiscoveryError):
        tc.discover(LIST_URL, source_id=7, opener=lambda *a, **kw: _Resp(_payload(), total_pages=1))


# --- event-window pagination (v0.85.2, Sections 4-13) -----------------------

from datetime import datetime  # noqa: E402


def _paged_opener(pages, total_pages=None, calls=None):
    """pages: {page_number: [post_dict, ...]}. Missing page -> empty list."""
    def opener(request, timeout=None):
        if calls is not None:
            calls.append(request.full_url)
        import urllib.parse
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(request.full_url).query))
        page = int(query.get("page", "1"))
        body = json.dumps(pages.get(page, []), ensure_ascii=False)
        return _Resp(body, total_pages=total_pages)
    return opener


def test_page1_is_fetched_first(monkeypatch):
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    page1 = [_post(1, "2026-09-07T10:00:00", "최근 글")]
    calls = []
    opener = _paged_opener({1: page1}, total_pages=1, calls=calls)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=30)
    assert len(posts) == 1
    assert "page=1" in calls[0]


def test_page2_is_fetched_when_page1_is_still_within_the_lookback_window(monkeypatch):
    """Section 5: real pagination, not just a page-1-only read."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    page1 = [_post(i, "2026-09-05T10:00:00", f"글{i}") for i in range(1, 11)]
    page2 = [_post(i, "2026-08-20T10:00:00", f"글{i}") for i in range(11, 21)]
    calls = []
    opener = _paged_opener({1: page1, 2: page2}, total_pages=9, calls=calls)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=30, max_pages=5)
    assert len(posts) == 20
    assert any("page=2" in c for c in calls)


def test_x_wp_total_pages_stops_pagination(monkeypatch):
    """Section 5/9: X-WP-TotalPages honoured as a stop signal even when the
    lookback window would otherwise keep going."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    page1 = [_post(i, "2026-09-05T10:00:00", f"글{i}") for i in range(1, 11)]
    calls = []
    opener = _paged_opener({1: page1}, total_pages=1, calls=calls)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=365, max_pages=5)
    assert len(posts) == 10
    assert not any("page=2" in c for c in calls)


def test_max_pages_is_a_hard_bound_even_with_a_generous_lookback(monkeypatch):
    """Section 6: max_pages applies regardless of TotalPages or lookback -
    a site that lies about (or omits) X-WP-TotalPages must not cause an
    unbounded crawl."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    pages = {n: [_post(n * 10 + i, "2026-09-05T10:00:00", f"p{n}-{i}") for i in range(10)]
             for n in range(1, 20)}
    calls = []
    opener = _paged_opener(pages, total_pages=None, calls=calls)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=3650, max_pages=3)
    assert len(posts) == 30
    assert len(calls) == 3


def test_an_empty_page_stops_pagination(monkeypatch):
    """Section 7: a genuinely empty page is a legitimate stop, not an error."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    page1 = [_post(1, "2026-09-05T10:00:00", "글1")]
    calls = []
    opener = _paged_opener({1: page1}, total_pages=None, calls=calls)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=3650, max_pages=5)
    assert len(posts) == 1
    assert len(calls) == 2  # page 1 (real), page 2 (empty -> stop)


def test_a_duplicate_post_id_across_pages_is_deduplicated(monkeypatch):
    """Section 12: idempotency - the same WordPress post id appearing on two
    fetches (e.g. a new post pushing everything down mid-crawl) counts once."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    page1 = [_post(5, "2026-09-05T10:00:00", "글5")]
    page2 = [_post(5, "2026-09-05T10:00:00", "글5"), _post(6, "2026-08-20T10:00:00", "글6")]
    calls = []
    opener = _paged_opener({1: page1, 2: page2}, total_pages=2, calls=calls)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=365, max_pages=5)
    assert len(posts) == 2
    assert {p["wp_post_id"] for p in posts} == {5, 6}


def test_an_old_post_beyond_the_lookback_window_still_stops_further_pages(monkeypatch):
    """Section 4/8: once a page's oldest post predates the lookback window,
    later pages can only be older still - stop rather than reading them."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    page1 = [_post(1, "2026-07-01T10:00:00", "오래된 글")]  # > 30 days old
    calls = []
    opener = _paged_opener({1: page1, 2: [_post(2, "2026-06-01T10:00:00", "더 오래된 글")]},
                            total_pages=5, calls=calls)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=30, max_pages=5)
    assert len(posts) == 1  # page1's post is still returned (event date != publish date)
    assert not any("page=2" in c for c in calls)


def test_a_recent_event_post_within_the_window_is_detected(monkeypatch):
    """Section 8/10 - the concrete regression this release fixes: an event
    post that would have scrolled off a page-1-only fetch is still found
    once the lookback window covers the page it landed on."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    # 12 unrelated articles push the one real event post to page 2.
    page1 = [_post(i, "2026-09-06T10:00:00", f"안내글{i}") for i in range(1, 11)]
    page2 = [_post(11, "2026-08-22T10:00:00", "9월 클래스 안내"),
             _post(12, "2026-08-21T10:00:00", "다른 안내글")]
    calls = []
    opener = _paged_opener({1: page1, 2: page2}, total_pages=2, calls=calls)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=30, max_pages=5)
    titles = {p["title"] for p in posts}
    assert "9월 클래스 안내" in titles


def test_a_request_failure_on_a_later_page_propagates_not_swallowed(monkeypatch):
    """Section 46.10: a genuine fetch failure must surface as an error, not
    be silently treated as an empty-page stop (which would hide a real
    outage as 'nothing new today')."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    page1 = [_post(i, "2026-09-05T10:00:00", f"글{i}") for i in range(1, 11)]

    def opener(request, timeout=None):
        import urllib.parse
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(request.full_url).query))
        if query.get("page") == "2":
            raise OSError("simulated network failure")
        return _Resp(json.dumps(page1, ensure_ascii=False), total_pages=5)

    with pytest.raises(OSError):
        tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=365, max_pages=5)


def test_event_context_is_not_mixed_across_posts_on_different_pages(monkeypatch):
    """Section 46.11: each post keeps its own title/body/url independent of
    which page it was found on - pagination must never merge or bleed
    fields between posts."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    page1 = [_post(1, "2026-09-05T10:00:00", "페이지1 글")]
    page2 = [_post(2, "2026-08-20T10:00:00", "페이지2 글")]
    opener = _paged_opener({1: page1, 2: page2}, total_pages=2)
    posts = tc.discover(LIST_URL, source_id=1, opener=opener, now=now, lookback_days=365, max_pages=5)
    by_id = {p["wp_post_id"]: p for p in posts}
    assert by_id[1]["title"] == "페이지1 글"
    assert by_id[1]["source_url"] == "https://tangoclass.co.kr/p/1/"
    assert by_id[2]["title"] == "페이지2 글"
    assert by_id[2]["source_url"] == "https://tangoclass.co.kr/p/2/"


def test_current_single_page_behaviour_is_unchanged_when_lookback_excludes_page2(monkeypatch):
    """Section 46.12: a regression guard - the original v0.85.1 single-page
    behaviour (small lookback, everything on page 1) still works exactly as
    before pagination was added."""
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    now = datetime(2026, 9, 8)
    opener = lambda request, timeout=None: _Resp(_payload(), total_pages=1)
    posts = tc.discover(LIST_URL, source_id=7, opener=opener, now=now)
    assert len(posts) == 2
