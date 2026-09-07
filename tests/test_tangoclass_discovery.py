"""Discovery for tangoclass.co.kr (v0.85.1): a WordPress REST API
(`/wp-json/wp/v2/posts`) that already returns full post bodies as JSON.
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


# --- discover(): fetch + tag ------------------------------------------------

class _Resp(io.BytesIO):
    def __init__(self, body: str):
        super().__init__(body.encode("utf-8"))
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class _Headers:
    def get_content_charset(self):
        return "utf-8"


def test_discover_tags_every_post_with_source_and_platform(monkeypatch):
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: True)
    opener = lambda request, timeout=None: _Resp(_payload())
    posts = tc.discover(LIST_URL, source_id=7, opener=opener)
    assert len(posts) == 2
    assert all(p["source_id"] == 7 and p["platform"] == "WEB" for p in posts)


def test_discover_honours_robots_disallow(monkeypatch):
    monkeypatch.setattr(tc.acquisition, "robots_allows", lambda url, **kw: False)
    with pytest.raises(tc.DiscoveryError):
        tc.discover(LIST_URL, source_id=7, opener=lambda *a, **kw: _Resp(_payload()))
