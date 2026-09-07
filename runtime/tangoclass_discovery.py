"""Discovery for tangoclass.co.kr (v0.85.1 Direct Source Coverage Expansion,
event-window pagination added v0.85.2): a WordPress site whose own REST API
(`/wp-json/wp/v2/posts`) already returns every post as structured JSON,
including the full HTML body (`content.rendered`) - a different shape again
from both `web_discovery.py`'s HTML board rows and `danceinfo_discovery.py`'s
`__NEXT_DATA__` payload, kept as its own small module for the same reason
those two are separate (Section 34/35: verify before generalizing).

Because the REST API already returns the full post body, there is no
separate detail fetch here - every post is tagged FETCHED_FULL directly at
discovery, the same as Miltang's own milonga list (`miltang_discovery.py`).
Nothing downstream needs an acquisition.py marker pair for this source.

The organizer teaches and posts about tango only - unlike danceinfo.net,
there is no other genre mixed into this feed, so discovery passes every post
through unfiltered and lets the existing engine classifier (`classify()`)
decide which ones are actual milonga/event announcements; a post with no
date/venue signal simply produces no candidate, the same as any other
source's non-event posts already do.

v0.85.2's own real bug: the first release only ever asked for the single
most-recent 10 posts. A live re-check 30 minutes later showed a real event
post ("9월~10월 스페셜 원데이 클래스") had already scrolled off that window -
pushed out by two unrelated educational-article posts published in between.
This module now pages backward from the newest post until either a page's
oldest post is older than ``lookback_days`` (Section 4: recent-past-few-days
window, not a publish-date-narrow one - an event's own date can be weeks
after its post's publish date, so this only bounds how far back we look for
NEW posts, never how far in the future an event may fall), or a genuinely
empty page is returned, or ``max_pages`` is hit (Section 6: no unbounded
crawl regardless of what the site claims). WordPress's own `X-WP-TotalPages`
response header is honoured as an earlier stop signal when present, but
never trusted as the ONLY bound - a site that lies about it, or omits it,
must not turn this into an unbounded loop.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

from . import acquisition

USER_AGENT = acquisition.USER_AGENT
DEFAULT_TIMEOUT = acquisition.DEFAULT_TIMEOUT

# "최근 과거 며칠" (Section 4) - wide enough that a slow week of posts is
# still fully covered, narrow enough that this never turns into a deep
# archive crawl. A single WEB source's config can override it.
DEFAULT_LOOKBACK_DAYS = 30
# Section 6: an absolute page-count ceiling, independent of anything the
# site's own X-WP-TotalPages header claims.
DEFAULT_MAX_PAGES = 5
DEFAULT_PER_PAGE = 10

_TAG_RE = re.compile(r"<[^>]+>")


class DiscoveryError(RuntimeError):
    """The list page could not be fetched or made no sense to parse."""


def _clean(value: str | None) -> str:
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", _TAG_RE.sub("", value)).strip()


def _fetch_page(url: str, *, timeout: int, opener) -> tuple[str, int | None]:
    """One page's raw JSON text, plus X-WP-TotalPages if the response sent
    it (None otherwise - callers must not require it)."""
    if not acquisition.robots_allows(url):
        raise DiscoveryError(f"robots.txt disallows {url}")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read()
        total_pages_raw = response.headers.get("X-WP-TotalPages")
    total_pages = None
    if total_pages_raw is not None:
        try:
            total_pages = int(total_pages_raw)
        except (TypeError, ValueError):
            total_pages = None
    return body.decode(charset, errors="replace"), total_pages


def parse_list(raw_json_text: str, list_url: str) -> list[dict[str, Any]]:
    """Posts on one already-fetched `wp-json/wp/v2/posts` response.

    Shaped like `web_discovery.parse_list()`'s output - the fields
    `collectors._to_raw_item` reads off a RawPostRecord-shaped dict:
    `source_url`, `title`, `body`, `published_at`, `acquisition_quality`.

    ``published_at`` is WordPress's own `date` field - when the post was
    actually published, not a claimed event date, so it is safe input to the
    yearless-date safety check the way it is meant to be used, and to this
    module's own lookback stop condition.

    An empty array is a legitimate "no posts on this page" result (used by
    ``discover()`` as one of its stop conditions), not an error.
    """
    try:
        payload = json.loads(raw_json_text)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"{list_url} is not valid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise DiscoveryError(
            f"{list_url} did not return a JSON array - schema changed or this is an error payload"
        )

    posts: list[dict[str, Any]] = []
    for post in payload:
        if "link" not in post or "title" not in post or "content" not in post:
            raise DiscoveryError(
                f"a post on {list_url} is missing link/title/content - schema changed"
            )
        title = _clean((post.get("title") or {}).get("rendered"))
        if not title:
            continue
        posts.append({
            # WordPress's own numeric post id - the stable identity Section
            # 13 asks for. `source_url` (the canonical link) is what
            # downstream dedup/storage actually keys on; wp_post_id travels
            # alongside it only so a caller paging across requests can
            # de-duplicate before that point too (Section 12).
            "wp_post_id": post.get("id"),
            "source_url": post["link"],
            "title": title,
            "body": _clean((post.get("content") or {}).get("rendered")),
            "published_at": post.get("date") or None,
            "acquisition_quality": "FETCHED_FULL",
        })
    return posts


def _paged_url(list_url: str, page: int) -> str:
    parsed = urllib.parse.urlparse(list_url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query.setdefault("per_page", str(DEFAULT_PER_PAGE))
    query["page"] = str(page)
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def discover(
    list_url: str, *, source_id: str, platform: str = "WEB",
    timeout: int = DEFAULT_TIMEOUT, opener=None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS, max_pages: int = DEFAULT_MAX_PAGES,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Every post on tangoclass.co.kr newer than ``lookback_days``, tagged
    for a Source Master row.

    Pages backward from the newest post (WordPress's own default order)
    until the first of these stop conditions:

    - a page comes back empty (genuinely no more posts);
    - the OLDEST post on a page (the last one, given newest-first order) is
      older than ``lookback_days`` - later pages can only be older still;
    - ``page > X-WP-TotalPages``, when the site sent that header;
    - ``max_pages`` reached regardless of the above (Section 6's hard bound -
      this is the one that still applies even if a site's TotalPages header
      is missing, wrong, or absurdly large).

    Posts are de-duplicated by WordPress post id across pages (Section 12) -
    belt-and-suspenders against a site whose pagination overlaps under
    concurrent edits; `collectors._collect_web()`'s own `source_url` de-dupe
    already covers the common case, this covers the id-stable one too.
    """
    cutoff = (now or datetime.now()) - timedelta(days=lookback_days)
    seen_ids: set[Any] = set()
    posts: list[dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        raw_text, total_pages = _fetch_page(_paged_url(list_url, page), timeout=timeout, opener=opener)
        page_posts = parse_list(raw_text, list_url)
        if not page_posts:
            break
        for post in page_posts:
            post_id = post.get("wp_post_id")
            if post_id is not None and post_id in seen_ids:
                continue
            if post_id is not None:
                seen_ids.add(post_id)
            posts.append(post)

        oldest_on_page = page_posts[-1].get("published_at")
        page_is_stale = bool(oldest_on_page) and oldest_on_page < cutoff.isoformat()
        page_is_last = total_pages is not None and page >= total_pages
        if page_is_stale or page_is_last:
            break
        page += 1

    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
