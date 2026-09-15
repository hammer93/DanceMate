"""Discovery for BAL&HOP (발앤합, v0.91.0 PHASE 5): a single-page PRIMARY_ORGANIZER
Swing/Balboa festival site, not a board of many posts.

Confirmed live (raw HTTP GET, robots.txt absent -> allowed by
`acquisition.robots_allows()`'s own "on any doubt, allow" rule): the page is a
Next.js App Router build whose real schedule/lineup content streams in via
`self.__next_f.push(...)` React Server Components payloads - an undocumented,
per-deployment format (the asset URLs carry a build hash) with no JSON-LD and
no `__NEXT_DATA__`/versioned API anywhere on the page. This module never reads
that payload; parsing it would be exactly the "reverse-engineer an opaque
flight blob" this project's acquisition layer refuses to depend on.

What *is* stable, plain, server-rendered HTML on every fetch (confirmed live):
the `<title>` tag and the `og:description`/`description` meta tags. The title
happens to already carry both the event name and its date range in one place -
"BAL&HOP 2026 - 9.18-20" - which is the only field this module trusts for a
date. No day-level end date is claimed: `runtime.normalization`/`events` has
no end-date column (see the PHASE 5 report), so only the range's start day is
ever resolved; the full "9.18-20" text is preserved verbatim in the title so
a reviewer sees the real span, and a MULTI_DAY_EVENT evidence names it too
(extractor.py).

`published_at` is left `None` - this page carries no post-level timestamp of
its own, and unlike a genuinely dateless bare "9.18", the title also carries
its own explicit year ("2026") right next to the range. PHASE 7 first "fixed"
the missing-anchor problem by setting `published_at` to the crawl time - but
that reads the year off *when this happened to be fetched*, not off what the
page actually says, which is exactly backwards for an evergreen page: revisit
it in 2027 while it still shows "BAL&HOP 2026", and crawl-time anchoring
would silently relabel 2026's own festival as 2027's. The real, narrower fix
is `extractor.DATE_PATTERNS`' own new year-plus-range pattern, which reads
"2026" directly out of the title next to "9.18-20" and resolves it as
EXPLICIT_YEAR - no anchor needed, so there is nothing here to fake a
publication time for.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any

from . import acquisition

USER_AGENT = acquisition.USER_AGENT
DEFAULT_TIMEOUT = acquisition.DEFAULT_TIMEOUT

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
_DESCRIPTION_RE = re.compile(
    r'<meta\s+(?:property|name)=["\'](?:og:description|description)["\']\s+content=["\'](.*?)["\']',
    re.I,
)
_TAG_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|#39);")
_ENTITY_MAP = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "#39": "'"}


def _unescape(text: str) -> str:
    return _TAG_ENTITY_RE.sub(lambda m: _ENTITY_MAP[m.group(1)], text)


class DiscoveryError(RuntimeError):
    pass


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


def parse_page(raw_html: str, page_url: str) -> list[dict[str, Any]]:
    """The one listing this single-purpose organizer page names, if it names one.

    Never more than one record - this is not a board with rows to walk, it is
    one festival's own page. No `<title>` is not a page worth registering as a
    post at all.
    """
    title_match = _TITLE_RE.search(raw_html)
    if not title_match:
        return []
    title = _unescape(title_match.group(1)).strip()
    if not title:
        return []
    desc_match = _DESCRIPTION_RE.search(raw_html)
    body = _unescape(desc_match.group(1)).strip() if desc_match else ""
    return [
        {
            "source_url": page_url,
            "title": title,
            "body": body,
            # v0.91.0 PHASE 7 (corrected twice): no per-post publish date
            # exists on an organizer's own evergreen page. First left None,
            # which produced UNKNOWN_YEAR/no date at all for a bare "9.18"
            # with nothing to anchor it. Then "fixed" by anchoring to the
            # crawl time - which resolves a year, but the wrong one the
            # moment this evergreen page is fetched in a later real year
            # while its own title still says "2026" (see the module
            # docstring). The real fix is extractor.DATE_PATTERNS' new
            # year-plus-range pattern reading "2026" straight out of this
            # title, which needs no anchor at all - so this stays the
            # honest `None` a page with no true publication timestamp
            # actually has.
            "published_at": None,
            "acquisition_quality": "FETCHED_PARTIAL",
            # v0.91.0 PHASE 7: found live - without this the real
            # runtime.engine_ingest pipeline (classify_with_image_evidence(),
            # no keyword override) reads this page's thin title/description
            # as OTHER and produces zero candidates, same as classifier.py's
            # own documented Daegu/Pohang brand-name gap (miltang_discovery.py
            # sets this for exactly the same reason: a page whose entire
            # purpose is announcing one kind of event, with no descriptive
            # keyword classify() can find). This is admissible evidence
            # (live_pipeline.py's own docstring: "Source Registry / known
            # series context") because the page's own dedicated single-
            # purpose structure - not the "BAL" brand abbreviation, and not
            # inferred Balboa - already says what kind of page this is; see
            # the module docstring for what it does NOT claim (no literal
            # Balboa text on this page).
            "known_event_type": "SOCIAL",
        }
    ]


def discover(
    list_url: str,
    *,
    source_id: str,
    platform: str = "WEB",
    timeout: int = DEFAULT_TIMEOUT,
    opener=None,
) -> list[dict[str, Any]]:
    raw_html = _fetch_html(list_url, timeout=timeout, opener=opener)
    posts = parse_page(raw_html, list_url)
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
