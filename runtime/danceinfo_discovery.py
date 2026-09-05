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

    # Required-key validation, not `.get(...) or {}` silent fallbacks: a page
    # with a genuinely empty day (no lessons at all, a legitimate zero-result
    # day) must still have this shape. A missing key means the site's own
    # JSON structure changed underneath us, which must surface as a parser
    # error - a silently empty list here would read as "no Tango today"
    # instead of "this collector is broken", and nobody would notice either.
    if "props" not in data:
        raise DiscoveryError(f"__NEXT_DATA__ on {list_url} has no 'props' key - schema changed")
    if "pageProps" not in data["props"]:
        raise DiscoveryError(f"props on {list_url} has no 'pageProps' key - schema changed")
    page_props = data["props"]["pageProps"]
    if "initialDays" not in page_props:
        raise DiscoveryError(
            f"pageProps on {list_url} has no 'initialDays' key - schema changed"
        )
    days = page_props["initialDays"] or []
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


def _seoul_today():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _dated_url(base_url: str, day) -> str:
    """`base_url` with its `date` query param replaced (or added)."""
    parsed = urllib.parse.urlparse(base_url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query["date"] = day.isoformat()
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def discover(
    list_url: str, *, source_id: str, platform: str = "WEB",
    genre_name: str = TANGO_GENRE_NAME, timeout: int = DEFAULT_TIMEOUT, opener=None,
    days_ahead: int = 0,
) -> list[dict[str, Any]]:
    """Rows on one danceinfo.net date-list page, tagged for a Source Master
    row.

    ``days_ahead`` (v0.82.1): a date page shows only one day's lessons -
    confirmed directly, so widening the window means naming more pages, not
    a different parser. Rather than storing N static dated URLs that go
    stale as the calendar moves past them (this release's own known
    limitation from v0.82), a source can instead set ``config.days_ahead``
    and register a *single*, date-less ``board_urls`` entry - danceinfo.net
    itself computes "today" server-side for a date-less request (verified:
    its own `ssrDateKey` matched the real current date), so this collector
    then asks for "today" plus that many days ahead, computed fresh every
    collection cycle. 0 (the default) keeps the exact one-page-per-call
    behaviour every existing caller (including a source with static dated
    ``board_urls`` already registered) already relies on.
    """
    urls = [list_url]
    if days_ahead > 0:
        today = _seoul_today()
        from datetime import timedelta

        urls += [_dated_url(list_url, today + timedelta(days=n))
                 for n in range(1, days_ahead + 1)]

    posts: list[dict[str, Any]] = []
    for url in urls:
        raw_html = _fetch_html(url, timeout=timeout, opener=opener)
        posts.extend(parse_list(raw_html, url, genre_name=genre_name))
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
