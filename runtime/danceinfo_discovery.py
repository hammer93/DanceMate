"""Discovery for danceinfo.net (v0.82 Tango Source Expansion): a Next.js
listing whose event data is embedded as JSON on the page
(`__NEXT_DATA__`, the framework's own SSR hydration payload) rather than
laid out as HTML board rows - a different discovery shape from
`web_discovery.py`'s K-TANGO-style board scraping, kept as its own small
module rather than forced into that module's HTML-row regex (Section 34/35:
verify before generalizing, and a genuinely different data shape is not a
config tweak away from the existing one).

Only the list page is JSON; the detail page (fetched later by
`runtime.acquisition.fetch()`, unchanged) is ordinary server-rendered HTML -
danceinfo.net's own article-region marker pair was added to acquisition.py
for it, the same way K-TANGO's and Daum's own marker pairs already are.

The site lists every genre on one page (bachata, salsa, tango, kizomba...);
filtering to Tango happens here, at discovery, the same place a search
query filters a Naver/Daum source - nothing downstream ever sees a
non-Tango danceinfo.net listing.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from . import acquisition

USER_AGENT = acquisition.USER_AGENT
DEFAULT_TIMEOUT = acquisition.DEFAULT_TIMEOUT

TANGO_GENRE_NAME = "탱고"

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


class DiscoveryError(RuntimeError):
    """The list page could not be fetched or made no sense to parse."""


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


def parse_list(
    raw_html: str, list_url: str, *, genre_name: str = TANGO_GENRE_NAME,
) -> list[dict[str, Any]]:
    """Lessons on one already-fetched list page, filtered to one genre.

    Shaped like `web_discovery.parse_list()`'s output - the fields
    `collectors._to_raw_item` reads off a RawPostRecord-shaped dict:
    `source_url`, `title`, `body`, `published_at`, `acquisition_quality`.

    ``published_at`` is deliberately left None: the list JSON's own "date"
    is the *event's* date, not when the listing was posted, and there is no
    separate publish timestamp here. Feeding an event's own claimed date
    back in as its "published_at" would make the yearless-date safety check
    (engine/src/extractor.py's `_yearless_date`) circular rather than an
    independent check - and danceinfo.net's dates are explicit-year in the
    body text regardless ("2026년 9월 12일"), so nothing here actually needs
    it to resolve a bare month/day.
    """
    match = _NEXT_DATA.search(raw_html)
    if not match:
        raise DiscoveryError(f"no __NEXT_DATA__ payload found on {list_url}")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"__NEXT_DATA__ on {list_url} is not valid JSON: {exc}") from exc

    days = ((data.get("props") or {}).get("pageProps") or {}).get("initialDays") or []
    posts: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    for day in days:
        for lesson in day.get("lessons") or []:
            if lesson.get("genreName") != genre_name:
                continue
            content_id = lesson.get("contentIdx")
            if content_id is None or content_id in seen_ids:
                continue
            seen_ids.add(content_id)
            title = (lesson.get("title") or "").strip()
            if not title:
                continue
            detail_url = urllib.parse.urljoin(list_url, f"/lessons/{content_id}")
            posts.append({
                "source_url": detail_url,
                "title": title,
                "body": "",
                "published_at": None,
                "acquisition_quality": "METADATA_ONLY",
            })
    return posts


def discover(
    list_url: str, *, source_id: str, platform: str = "WEB",
    genre_name: str = TANGO_GENRE_NAME, timeout: int = DEFAULT_TIMEOUT, opener=None,
) -> list[dict[str, Any]]:
    """Rows on one danceinfo.net date-list page, tagged for a Source Master
    row. One date's page only, deliberately, the same "add pagination when a
    source actually needs it" rule `web_discovery.discover()` follows -
    the source's own `config.board_urls` names each date page to poll.
    """
    raw_html = _fetch_html(list_url, timeout=timeout, opener=opener)
    posts = parse_list(raw_html, list_url, genre_name=genre_name)
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
