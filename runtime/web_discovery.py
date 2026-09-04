"""Discovery for WEB-platform sources: a community's own board, not a search API.

The Daum and Naver collectors call a provider's search endpoint, which already
returns a list of matching posts. A WEB source has no such endpoint - the
board's own list page is the only index there is, so this module fetches and
parses it exactly as a browser would, then hands each row on as a plain
RawPostRecord-shaped dict, the same shape `collectors._to_raw_item` already
turns into a runtime `RawItem`.

    board list page  ->  post rows (title, url, posted date)  ->  RawItem

The list page never carries the post body - only `runtime.acquisition.fetch()`,
run later against the URL discovered here, gets that. `published_at` is worth
capturing at discovery time even so: the extractor's year-inference (v0.80.2)
needs the post's own date, and the list page is where a WEB board actually
shows it, unlike the detail page's free-form text.

This module honours `robots.txt` the same way `runtime.acquisition` does - a
disallowed board is not fetched, full stop.
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import acquisition

USER_AGENT = acquisition.USER_AGENT
DEFAULT_TIMEOUT = acquisition.DEFAULT_TIMEOUT

# One row of a K-TANGO-style board list (a template shared by other Korean
# community sites built on the same "read.jsp" board software - the class
# names below are the template's, not this one site's):
#
#   <td class="tit" ... onclick="location.href='read.jsp?reqPageNo=1&no=10'">
#       <p class="mw100"> 2024 K-TANGO SF : 신청폼 </p>
#   </td>
#   <td><p>K-TANGO</p></td>
#   <td>2024-09-01</td>
_ROW = re.compile(
    r"href='(?P<href>[^']*\bno=(?P<no>\d+)[^']*)'.*?"
    r'class="mw100">\s*(?P<title>.*?)\s*</p>.*?'
    r"<td>\s*(?P<date>\d{4}-\d{2}-\d{2})",
    re.S,
)


class DiscoveryError(RuntimeError):
    """The board list could not be fetched or made no sense to parse."""


# A "공지"/"NEW" badge and its HTML comment marker both live inside the same
# <p class="mw100"> as the title on a pinned post - e.g.
# "<!-- property:공지 --> <span class="noti_icon">공지</span> 2025 K-TANGO CF
# 행사안내&등록 <!-- property:NEW --> <span class="new_icon gre">NEW</span>".
# Stripped here so a pinned post's title reads the same as any other post's.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _HTML_COMMENT.sub(" ", text)
    text = _TAG.sub(" ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _fetch_html(url: str, *, timeout: int, opener) -> str:
    if not acquisition.robots_allows(url):
        raise DiscoveryError(f"robots.txt disallows {url}")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
        },
    )
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read()
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def parse_list(raw_html: str, list_url: str) -> list[dict[str, Any]]:
    """Board rows on one already-fetched list page.

    Each dict has the fields `collectors._to_raw_item` reads off a
    RawPostRecord: `source_url`, `title`, `body`, `published_at`,
    `acquisition_quality`. `source_id`/`platform` are added by the caller,
    which knows which Source Master row this collection is for.
    """
    posts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for match in _ROW.finditer(raw_html):
        title = _clean(match.group("title"))
        if not title:
            continue
        detail_url = urllib.parse.urljoin(list_url, html.unescape(match.group("href")))
        if detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)
        posts.append(
            {
                "source_url": detail_url,
                "title": title,
                "body": "",
                "published_at": f"{match.group('date')}T00:00:00+00:00",
                "acquisition_quality": "METADATA_ONLY",
            }
        )
    return posts


def discover(
    list_url: str,
    *,
    source_id: str,
    platform: str = "WEB",
    timeout: int = DEFAULT_TIMEOUT,
    opener=None,
) -> list[dict[str, Any]]:
    """Rows on one board list page, tagged for a Source Master row.

    One page only, deliberately. A source with more history than fits on page
    one is a paging problem for a later collection to solve; a board polled on
    an interval is walked repeatedly, and nothing on page two is lost by
    waiting for it to reach page one - or for pagination to be added when a
    second WEB source actually needs it.
    """
    raw_html = _fetch_html(list_url, timeout=timeout, opener=opener)
    posts = parse_list(raw_html, list_url)
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
