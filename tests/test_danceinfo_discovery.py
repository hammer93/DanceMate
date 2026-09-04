"""Discovery for danceinfo.net (v0.82): a Next.js listing whose event data
is embedded as JSON (__NEXT_DATA__) rather than laid out as HTML rows.
"""

from __future__ import annotations

import io
import json

import pytest

from runtime import danceinfo_discovery as di

LIST_URL = "https://danceinfo.net/lessons?date=2026-09-12&genre=all&category=all&location=all"

# Shaped like the real page's own hydration payload - just the fields this
# module reads, not a captured copy of the real (much larger) page.
_NEXT_DATA = {
    "props": {
        "pageProps": {
            "initialDays": [
                {
                    "date": "2026-09-12",
                    "lessons": [
                        {
                            "contentIdx": 2401,
                            "genreName": "탱고",
                            "title": "러블리밀롱가 7주년 파티안내",
                            "date": "2026-09-12",
                            "location": "경기남부",
                        },
                        {
                            "contentIdx": 9001,
                            "genreName": "살사",
                            "title": "살사 소셜파티",
                            "date": "2026-09-12",
                            "location": "서울",
                        },
                        {
                            "contentIdx": 9002,
                            "genreName": "탱고",
                            "title": "",  # blank title: must be skipped
                            "date": "2026-09-12",
                            "location": "서울",
                        },
                    ],
                }
            ]
        }
    }
}


def _page(next_data: dict) -> str:
    return (
        "<html><head></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
        "</body></html>"
    )


def test_only_tango_listings_are_returned():
    posts = di.parse_list(_page(_NEXT_DATA), LIST_URL)
    assert len(posts) == 1
    assert posts[0]["title"] == "러블리밀롱가 7주년 파티안내"


def test_the_detail_url_is_built_from_content_idx():
    posts = di.parse_list(_page(_NEXT_DATA), LIST_URL)
    assert posts[0]["source_url"] == "https://danceinfo.net/lessons/2401"


def test_a_blank_title_is_skipped_even_if_tango():
    posts = di.parse_list(_page(_NEXT_DATA), LIST_URL)
    ids = [p["source_url"] for p in posts]
    assert "https://danceinfo.net/lessons/9002" not in ids


def test_published_at_is_left_none_not_backfilled_from_the_event_date():
    """The list JSON's 'date' is the EVENT's date, not a post timestamp -
    using it as published_at would make the yearless-date safety check
    circular instead of independent."""
    posts = di.parse_list(_page(_NEXT_DATA), LIST_URL)
    assert posts[0]["published_at"] is None


def test_a_page_with_no_next_data_raises_discovery_error():
    with pytest.raises(di.DiscoveryError):
        di.parse_list("<html><body>nothing here</body></html>", LIST_URL)


def test_malformed_next_data_json_raises_discovery_error():
    broken = '<script id="__NEXT_DATA__" type="application/json">{not json}</script>'
    with pytest.raises(di.DiscoveryError):
        di.parse_list(broken, LIST_URL)


def test_duplicate_content_ids_are_deduplicated():
    dupe = {
        "props": {"pageProps": {"initialDays": [
            {"date": "2026-09-12", "lessons": [
                {"contentIdx": 1, "genreName": "탱고", "title": "A", "date": "2026-09-12"},
                {"contentIdx": 1, "genreName": "탱고", "title": "A again", "date": "2026-09-12"},
            ]},
        ]}}
    }
    posts = di.parse_list(_page(dupe), LIST_URL)
    assert len(posts) == 1


def test_a_different_genre_filter_selects_a_different_genre():
    posts = di.parse_list(_page(_NEXT_DATA), LIST_URL, genre_name="살사")
    assert len(posts) == 1
    assert posts[0]["title"] == "살사 소셜파티"


# --- discover(): fetch + tag ---------------------------------------------------

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
    monkeypatch.setattr(di.acquisition, "robots_allows", lambda url, **kw: True)
    opener = lambda request, timeout=None: _Resp(_page(_NEXT_DATA))
    posts = di.discover(LIST_URL, source_id=42, opener=opener)
    assert len(posts) == 1
    assert posts[0]["source_id"] == 42
    assert posts[0]["platform"] == "WEB"


def test_discover_honours_robots_disallow(monkeypatch):
    monkeypatch.setattr(di.acquisition, "robots_allows", lambda url, **kw: False)
    with pytest.raises(di.DiscoveryError):
        di.discover(LIST_URL, source_id=42, opener=lambda *a, **kw: _Resp(_page(_NEXT_DATA)))
