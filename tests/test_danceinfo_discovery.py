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


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("props"),
    lambda d: d["props"].pop("pageProps"),
    lambda d: d["props"]["pageProps"].pop("initialDays"),
])
def test_a_restructured_page_raises_a_schema_error_not_an_empty_success(mutate):
    """A missing key is the site's own JSON shape changing underneath us, not
    a legitimately empty day - it must surface as a parser error so nobody
    mistakes 'this collector broke' for 'no Tango today'."""
    import copy

    payload = copy.deepcopy(_NEXT_DATA)
    mutate(payload)
    with pytest.raises(di.DiscoveryError):
        di.parse_list(_page(payload), LIST_URL)


def test_a_day_with_zero_lessons_is_a_legitimate_empty_result_not_an_error():
    empty_day = {"props": {"pageProps": {"initialDays": [
        {"date": "2026-09-12", "lessons": []},
    ]}}}
    assert di.parse_list(_page(empty_day), LIST_URL) == []


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


# --- days_ahead: self-widening a single date-less URL (v0.82.1) -------------
#
# A source's board_urls needing periodic manual refresh (v0.82's own known
# limitation) is solved here without any new scraping framework: a date-less
# request already gets "today" computed server-side by danceinfo.net itself
# (confirmed live), so this collector only has to compute "today + N" fresh
# on every call rather than store N dated URLs that go stale.

DATELESS_URL = "https://danceinfo.net/lessons?genre=all&category=all&location=all"


def test_days_ahead_zero_requests_only_the_given_url(monkeypatch):
    monkeypatch.setattr(di.acquisition, "robots_allows", lambda url, **kw: True)
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        return _Resp(_page(_NEXT_DATA))

    di.discover(DATELESS_URL, source_id=1, opener=opener)
    assert calls == [DATELESS_URL]


def test_days_ahead_n_requests_today_plus_n_dated_pages(monkeypatch):
    monkeypatch.setattr(di.acquisition, "robots_allows", lambda url, **kw: True)
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        return _Resp(_page({"props": {"pageProps": {"initialDays": []}}}))

    di.discover(DATELESS_URL, source_id=1, opener=opener, days_ahead=3)
    assert len(calls) == 4  # the date-less URL itself, plus +1/+2/+3 days
    assert calls[0] == DATELESS_URL
    from datetime import timedelta

    today = di._seoul_today()
    for offset, call in enumerate(calls[1:], start=1):
        assert f"date={(today + timedelta(days=offset)).isoformat()}" in call


def test_days_ahead_results_from_every_page_are_combined(monkeypatch):
    monkeypatch.setattr(di.acquisition, "robots_allows", lambda url, **kw: True)
    pages = [_NEXT_DATA, {
        "props": {"pageProps": {"initialDays": [{
            "date": "2099-01-02", "lessons": [
                {"contentIdx": 5001, "genreName": "탱고", "title": "내일 밀롱가",
                 "date": "2099-01-02"},
            ],
        }]}}
    }]
    calls = {"n": 0}

    def opener(request, timeout=None):
        page = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return _Resp(_page(page))

    posts = di.discover(DATELESS_URL, source_id=1, opener=opener, days_ahead=1)
    titles = {p["title"] for p in posts}
    assert "러블리밀롱가 7주년 파티안내" in titles  # from the date-less page
    assert "내일 밀롱가" in titles                    # from the +1 day page
