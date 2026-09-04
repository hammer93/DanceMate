"""Shared paging for admin list pages.

Every admin list before v0.81.1 used a hardcoded `LIMIT N` with no `OFFSET`
and no way to see anything past it — the 201st event, the 51st venue, simply
never rendered. One helper here, reused by every list route: a page is 50
rows, `page` is a 1-based query-string param, and a page number that makes no
sense (0, negative, non-numeric, or past the last page) is corrected rather
than turned into a 500 or an empty-looking screen.
"""

from __future__ import annotations

import html
from urllib.parse import urlencode

PAGE_SIZE = 50

E = html.escape


def total_pages(total: int, *, page_size: int = PAGE_SIZE) -> int:
    """At least 1, so an empty list still reads as "page 1 of 1", not "of 0"."""
    if total <= 0:
        return 1
    return -(-total // page_size)  # ceiling division


def resolve_page(raw_page, total: int, *, page_size: int = PAGE_SIZE) -> int:
    """A safe 1-based page number: never below 1, never past the last page."""
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1
    return min(page, total_pages(total, page_size=page_size))


def sql_offset(page: int, *, page_size: int = PAGE_SIZE) -> int:
    return (page - 1) * page_size


def nav(
    base_path: str,
    query: dict,
    page: int,
    total: int,
    *,
    page_size: int = PAGE_SIZE,
    page_param: str = "page",
) -> str:
    """Previous / Page X of Y / Next, preserving every other query param.

    `query` is the *filter/search/sort* state of the current request, minus
    the page param itself — a page link is built by copying it and setting
    `page_param`. `page_param` lets two independent lists share one page
    (e.g. Genres and Regions on `/admin/master`) without colliding on `?page=`.
    """
    last = total_pages(total, page_size=page_size)

    def link(target_page: int, label: str, *, disabled: bool) -> str:
        if disabled:
            return f'<span class="pager-link off">{E(label)}</span>'
        params = {k: v for k, v in query.items() if v not in (None, "")}
        params[page_param] = target_page
        return f'<a class="pager-link" href="{base_path}?{urlencode(params)}">{E(label)}</a>'

    if total <= 0:
        range_text = "Total 0"
    else:
        start = sql_offset(page, page_size=page_size) + 1
        end = min(sql_offset(page, page_size=page_size) + page_size, total)
        range_text = f"Total {total} &middot; Showing {start}–{end}"

    return (
        '<div class="pager">'
        f'<span class="pager-count">{range_text}</span>'
        '<span class="pager-nav">'
        + link(page - 1, "Previous", disabled=page <= 1)
        + f'<span class="pager-status">Page {page} / {last}</span>'
        + link(page + 1, "Next", disabled=page >= last)
        + "</span></div>"
    )
