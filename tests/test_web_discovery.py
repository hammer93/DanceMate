"""Discovery for WEB-platform sources: parsing a board's own list page.

The fixture below is shaped like K-TANGO's `/cnf/festival02/index.jsp`: a
plain HTML table, one `<tr>` per post, a pinned post carrying a "공지"/"NEW"
badge inside the same cell as its title.
"""

from __future__ import annotations

import io

import pytest

from runtime import acquisition, web_discovery

LIST_URL = "http://www.k-tango.net/cnf/festival02/index.jsp"

LIST_PAGE = """<html><body>
<table><tbody>
<tr>
<td class="none1000">2</td>
<td class="tit" style='cursor:pointer;' onclick="location.href='read.jsp?reqPageNo=1&no=14'">
<p class="mw100">
<!-- property:공지 --> <span class="noti_icon">공지</span>
2025 K-TANGO CF 행사안내&등록
<!-- property:NEW --> <span class="new_icon gre">NEW</span>
</p>
</td>
<td><p>K-TANGO</p></td>
<td>2025-03-31</td>
</tr>
<tr>
<td class="none1000">1</td>
<td class="tit" style='cursor:pointer;' onclick="location.href='read.jsp?reqPageNo=1&no=10'">
<p class="mw100">
2024 K-TANGO SF : 신청폼
</p>
</td>
<td><p>K-TANGO</p></td>
<td>2024-09-01</td>
</tr>
</tbody></table>
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

def test_two_rows_are_parsed():
    posts = web_discovery.parse_list(LIST_PAGE, LIST_URL)
    assert len(posts) == 2


def test_a_pinned_posts_badge_markup_is_stripped_from_its_title():
    posts = web_discovery.parse_list(LIST_PAGE, LIST_URL)
    pinned = next(p for p in posts if "no=14" in p["source_url"])
    assert pinned["title"] == "공지 2025 K-TANGO CF 행사안내&등록 NEW"
    assert "<span" not in pinned["title"]
    assert "<!--" not in pinned["title"]


def test_the_detail_url_is_resolved_against_the_list_url():
    posts = web_discovery.parse_list(LIST_PAGE, LIST_URL)
    urls = {p["source_url"] for p in posts}
    assert "http://www.k-tango.net/cnf/festival02/read.jsp?reqPageNo=1&no=10" in urls
    assert "http://www.k-tango.net/cnf/festival02/read.jsp?reqPageNo=1&no=14" in urls


def test_the_posted_date_becomes_published_at():
    posts = web_discovery.parse_list(LIST_PAGE, LIST_URL)
    ordinary = next(p for p in posts if "no=10" in p["source_url"])
    assert ordinary["published_at"] == "2024-09-01T00:00:00+00:00"


def test_a_row_with_no_title_is_skipped():
    page = LIST_PAGE.replace(
        "2024 K-TANGO SF : 신청폼", ""
    )
    posts = web_discovery.parse_list(page, LIST_URL)
    assert all("no=10" not in p["source_url"] for p in posts)


def test_the_body_is_empty_and_the_quality_is_metadata_only():
    """The list page never carries the article - only acquisition.fetch() does."""
    posts = web_discovery.parse_list(LIST_PAGE, LIST_URL)
    for post in posts:
        assert post["body"] == ""
        assert post["acquisition_quality"] == "METADATA_ONLY"


# --- discovery (fetch + parse + tag) ------------------------------------------

def test_discover_tags_every_post_with_the_source(monkeypatch):
    monkeypatch.setattr(
        web_discovery, "_fetch_html", lambda url, *, timeout, opener: LIST_PAGE
    )
    posts = web_discovery.discover(LIST_URL, source_id="SRC-W-001")
    assert len(posts) == 2
    assert all(p["source_id"] == "SRC-W-001" for p in posts)
    assert all(p["platform"] == "WEB" for p in posts)


def test_discover_refuses_a_disallowed_list_page(monkeypatch):
    monkeypatch.setattr(acquisition, "robots_allows", lambda *a, **k: False)
    with pytest.raises(web_discovery.DiscoveryError):
        web_discovery.discover(LIST_URL, source_id="SRC-W-001")


def test_discover_fetches_with_the_shared_user_agent():
    captured = {}

    def open_url(request, timeout=None):
        captured["user_agent"] = request.headers.get("User-agent")
        return _Response(LIST_PAGE)

    web_discovery.discover(LIST_URL, source_id="SRC-W-001", opener=open_url)
    assert captured["user_agent"] == acquisition.USER_AGENT
