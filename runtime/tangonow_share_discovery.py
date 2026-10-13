"""Discovery for TangoNOW through the crawl surface its operator publishes.

The Firestore registry `tangonow_discovery` was built on stopped answering on
2026-09-25 (HTTP 403, the public read rule withdrawn), and ktnow.kr's
robots.txt had two weeks earlier asked crawlers to leave the full event bundle
alone. What the same robots.txt keeps open, in as many words, is the share
pages and the sitemap that lists them - and those pages render a complete
schema.org `Event` server-side, for exactly this purpose.

One module per source *shape*, which is the convention the other discovery
modules state in their own docstrings: a sitemap-then-page crawl is not the
paginated typed-value JSON walk `tangonow_discovery.discover()` is, even
though both read the same provider's data. The reading itself lives beside
that provider's other parsing in `tangonow_discovery`; this module is the
`discover()` entry point `collectors._collect_web()` calls, so the sitemap URL
is an ordinary `config.board_urls` entry like every other WEB source's.
"""

from __future__ import annotations

from typing import Any

from . import tangonow_discovery

DiscoveryError = tangonow_discovery.DiscoveryError
SITEMAP_URL = tangonow_discovery.SITEMAP_URL
CRAWL_DELAY = tangonow_discovery.CRAWL_DELAY


def discover(
    board_url: str = SITEMAP_URL, *, source_id: str, platform: str = "WEB",
    timeout: int = tangonow_discovery.DEFAULT_TIMEOUT, opener=None,
    problems: list[str] | None = None, **kwargs: Any,
) -> list[dict[str, Any]]:
    """Every event the sitemap at ``board_url`` points at.

    ``problems`` carries the share pages that could not be read, the way
    v0.96.31 made Miltang report the days it could not read: one unreadable
    page no longer costs the other fifty-seven.
    """
    return tangonow_discovery.discover_share_pages(
        board_url or SITEMAP_URL, source_id=source_id, platform=platform,
        timeout=timeout, opener=opener, problems=problems, **kwargs,
    )
