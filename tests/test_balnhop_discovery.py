"""Discovery for BAL&HOP (v0.91.0 PHASE 5): a single organizer page, not a board.

The fixture below reproduces the *shape* of the real, live page (confirmed by
a real HTTP GET this phase, robots.txt absent so allowed): a plain `<title>`
and `og:description`/`description` meta tags are the only stable, server-
rendered content - the real schedule streams in via an undocumented Next.js
flight payload this module deliberately never touches.
"""

from __future__ import annotations

import io

import pytest

from runtime import acquisition, balnhop_discovery, collectors

PAGE_URL = "https://balnhop.kr/ko"

PAGE = """<!DOCTYPE html><html><head>
<title>BAL&amp;HOP 2026 - 9.18-20</title>
<meta name="description" content="All style swing dance festival in Korea"/>
<meta property="og:title" content="BAL&amp;HOP 2026 - 9.18-20"/>
<meta property="og:description" content="All style swing dance festival in Korea"/>
<meta property="og:site_name" content="BAL&amp;HOP"/>
</head><body>
<div hidden><!--$--><!--/$--></div>
<script>self.__next_f.push([1,"...opaque flight payload, never parsed..."])</script>
</body></html>"""


class _Response(io.BytesIO):
    def __init__(self, body: str):
        super().__init__(body.encode("utf-8"))
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class _Headers:
    def get_content_charset(self):
        return "utf-8"


@pytest.fixture(autouse=True)
def allow_robots(monkeypatch):
    monkeypatch.setattr(acquisition, "robots_allows", lambda *a, **k: True)


# --- parsing -----------------------------------------------------------------

def test_the_title_and_description_are_read():
    posts = balnhop_discovery.parse_page(PAGE, PAGE_URL)
    assert len(posts) == 1
    assert posts[0]["title"] == "BAL&HOP 2026 - 9.18-20"
    assert posts[0]["body"] == "All style swing dance festival in Korea"
    assert posts[0]["source_url"] == PAGE_URL


def test_html_entities_in_the_title_are_unescaped():
    posts = balnhop_discovery.parse_page(PAGE, PAGE_URL)
    assert "&amp;" not in posts[0]["title"]
    assert posts[0]["title"].startswith("BAL&HOP")


def test_no_flight_payload_content_ever_reaches_the_body():
    """The opaque `self.__next_f.push(...)` script is real content on the
    live page - this module must never read it, on purpose (see the module
    docstring)."""
    posts = balnhop_discovery.parse_page(PAGE, PAGE_URL)
    assert "__next_f" not in posts[0]["body"]
    assert "flight payload" not in posts[0]["body"]


def test_a_page_with_no_title_yields_nothing():
    posts = balnhop_discovery.parse_page("<html><body>no title here</body></html>", PAGE_URL)
    assert posts == []


def test_published_at_stays_unset():
    """v0.91.0 PHASE 7 (corrected twice): this evergreen page has no true
    publication timestamp. An earlier version of this fix anchored a bare
    "9.18" against the crawl time instead - which reads the year off *when
    the page happened to be fetched*, not off what the page says, and would
    silently relabel 2026's own festival as 2027's the next time this same
    page is crawled while still showing "BAL&HOP 2026" in its title. The
    real fix is extractor.DATE_PATTERNS' own year-plus-range pattern (see
    test_v0910_swing_funnel_evidence.py), which reads "2026" directly out of
    the title and needs no anchor - so there is nothing here to fake a
    publication time for."""
    posts = balnhop_discovery.parse_page(PAGE, PAGE_URL)
    assert posts[0]["published_at"] is None


# --- discover() ---------------------------------------------------------------

def test_discover_tags_the_post_with_the_source(monkeypatch):
    monkeypatch.setattr(
        balnhop_discovery, "_fetch_html", lambda url, *, timeout, opener: PAGE
    )
    posts = balnhop_discovery.discover(PAGE_URL, source_id="SRC-W-TEST-BALNHOP")
    assert len(posts) == 1
    assert posts[0]["source_id"] == "SRC-W-TEST-BALNHOP"
    assert posts[0]["platform"] == "WEB"


def test_discover_refuses_a_disallowed_page(monkeypatch):
    monkeypatch.setattr(acquisition, "robots_allows", lambda *a, **k: False)
    with pytest.raises(balnhop_discovery.DiscoveryError):
        balnhop_discovery.discover(PAGE_URL, source_id="SRC-W-TEST-BALNHOP")


def test_discover_fetches_with_the_shared_user_agent():
    captured = {}

    def open_url(request, timeout=None):
        captured["user_agent"] = request.headers.get("User-agent")
        return _Response(PAGE)

    balnhop_discovery.discover(PAGE_URL, source_id="SRC-W-TEST-BALNHOP", opener=open_url)
    assert captured["user_agent"] == acquisition.USER_AGENT


# --- parser registry -----------------------------------------------------

def test_the_balnhop_parser_is_registered_in_the_web_source_dispatch():
    module = collectors._web_discovery_module(collectors.WEB_PARSER_BALNHOP)
    assert module is balnhop_discovery
