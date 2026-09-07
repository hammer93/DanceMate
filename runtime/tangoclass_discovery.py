"""Discovery for tangoclass.co.kr (v0.85.1 Direct Source Coverage Expansion):
a WordPress site whose own REST API (`/wp-json/wp/v2/posts`) already returns
every post as structured JSON, including the full HTML body
(`content.rendered`) - a different shape again from both `web_discovery.py`'s
HTML board rows and `danceinfo_discovery.py`'s `__NEXT_DATA__` payload, kept
as its own small module for the same reason those two are separate (Section
34/35: verify before generalizing).

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
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from . import acquisition

USER_AGENT = acquisition.USER_AGENT
DEFAULT_TIMEOUT = acquisition.DEFAULT_TIMEOUT

_TAG_RE = re.compile(r"<[^>]+>")


class DiscoveryError(RuntimeError):
    """The list page could not be fetched or made no sense to parse."""


def _clean(value: str | None) -> str:
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", _TAG_RE.sub("", value)).strip()


def _fetch_text(url: str, *, timeout: int, opener) -> str:
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
    return body.decode(charset, errors="replace")


def parse_list(raw_json_text: str, list_url: str) -> list[dict[str, Any]]:
    """Posts on one already-fetched `wp-json/wp/v2/posts` response.

    Shaped like `web_discovery.parse_list()`'s output - the fields
    `collectors._to_raw_item` reads off a RawPostRecord-shaped dict:
    `source_url`, `title`, `body`, `published_at`, `acquisition_quality`.

    ``published_at`` is WordPress's own `date` field - when the post was
    actually published, not a claimed event date, so it is safe input to the
    yearless-date safety check the way it is meant to be used.
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
            "source_url": post["link"],
            "title": title,
            "body": _clean((post.get("content") or {}).get("rendered")),
            "published_at": post.get("date") or None,
            "acquisition_quality": "FETCHED_FULL",
        })
    return posts


def discover(
    list_url: str, *, source_id: str, platform: str = "WEB",
    timeout: int = DEFAULT_TIMEOUT, opener=None,
) -> list[dict[str, Any]]:
    """Rows on one tangoclass.co.kr `wp-json/wp/v2/posts` page, tagged for a
    Source Master row."""
    raw_text = _fetch_text(list_url, timeout=timeout, opener=opener)
    posts = parse_list(raw_text, list_url)
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
