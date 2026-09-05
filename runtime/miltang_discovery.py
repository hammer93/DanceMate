"""Discovery for Miltang (밀땅, v0.83): a SECONDARY/DIRECTORY Tango source,
never PRIMARY - `docs/MILTANG_TANGODORI_SOURCE_ANALYSIS.md` found several
Miltang records whose image path is `storage/imports/ktnow_...` and whose
title/date/venue/source link match KTNow's own public data exactly, meaning
some of what Miltang shows is itself a republish of KTNow, not an
independent observation. `runtime.normalization.resolve_venue()` and
`runtime.duplicates.classify()` (unchanged, reused as-is - Section 5's own
"no new dedup module" instruction) already collapse a KTNow/Miltang pair
that resolves to the same venue/date/time onto one canonical event; nothing
here decides that, it only registers as a low-authority SECONDARY source so
the existing tie-break in `duplicates.completeness()` can favour a more
complete/authoritative row when one exists.

Two genuinely different page shapes, both SSR HTML (confirmed live, no
JSON-LD on either list page, one `application/ld+json` block per detail
page):

  * `/milongas` - a single day's cards, scoped by BOTH `week=` (the Monday
    of that week) and `date=` (the specific day) query params together.
    Confirmed live: `date=` alone, without a matching `week=`, silently
    falls back to the CURRENT week's Monday instead of erroring - exactly
    the kind of silent-wrong-day behaviour this project never accepts, so
    `discover()` re-reads each fetched page's own displayed date and raises
    `DiscoveryError` if it does not match what was actually requested,
    rather than trusting the URL alone.
  * `/notices` - every notice on one unpaginated page, no date scoping.

Detail pages (`/milongas/{id}`, `/notices/{id}`) carry a `Schema.org Event`
JSON-LD block (name/startDate/[endDate]/location/[organizer]) plus a
plain-language `<dl>` of DATE/TIME/PLACE/[ORG]/LINK rows - confirmed live,
TIME is never present in the JSON-LD (JSON-LD `startDate` is date-only), so
TIME always comes from the HTML row, JSON-LD is preferred for everything
else it actually has. `created_at`/`updated_at` are not present anywhere on
a detail page (confirmed live) - `published_at` is always left `None`
here, never guessed from the sitemap's own `lastmod` (page freshness, not a
record timestamp).

Kept as its own independent module (matching every other source's own
reasoning in this project) rather than folded into `web_discovery.py` or
`danceinfo_discovery.py`: neither HTML-board rows nor a Next.js hydration
payload is what this site actually serves.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any

from . import acquisition

USER_AGENT = acquisition.USER_AGENT
DEFAULT_TIMEOUT = acquisition.DEFAULT_TIMEOUT

BASE_URL = "https://miltang.com"

# Safety limits (Section 2/9): a per-day list page observed ~11 milonga
# cards live; a 14-day window with heavy weekly-recurrence overlap (the same
# numeric id reappears every week its series runs, deduped before any
# detail fetch happens) realistically fetches far fewer than this, but the
# cap exists for the same reason TangoNOW's MAX_RECORDS does - a runaway or
# misbehaving response must not turn into an unbounded fetch loop.
MAX_DETAIL_FETCHES = 150
MAX_DAYS_AHEAD = 30


class DiscoveryError(RuntimeError):
    """A list or detail page could not be fetched, or rendered a shape this
    parser does not recognise - including a list page silently landing on
    the wrong day, which is reported here rather than collected under the
    wrong date label."""


# --- fetching -----------------------------------------------------------------

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
    try:
        with open_url(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise DiscoveryError(f"HTTP {exc.code} fetching {url}") from exc
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


# --- date/time helpers (deliberately local - see module docstring) ----------

def _seoul_today() -> date:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _dated_milonga_url(base_url: str, day: date) -> str:
    """`base_url` with `week` (that day's Monday) and `date` set together.

    Confirmed live: the list controller needs both - `date=` alone falls
    back to the current week's Monday rather than the requested day.
    """
    parsed = urllib.parse.urlparse(base_url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query["week"] = _monday_of(day).isoformat()
    query["date"] = day.isoformat()
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


_PAGE_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")


def _extract_page_date(raw_html_text: str) -> date | None:
    """The day this fetched `/milongas` page actually claims to show, read
    from its own visible header - the ground truth `discover()` checks the
    requested date against, not the URL it sent."""
    match = _PAGE_DATE_RE.search(raw_html_text)
    if not match:
        return None
    year, month, day_num = (int(g) for g in match.groups())
    try:
        return date(year, month, day_num)
    except ValueError:
        return None


def _format_date_kr(raw_date: Any) -> str | None:
    if not raw_date:
        return None
    try:
        d = date.fromisoformat(str(raw_date)[:10])
    except ValueError:
        return None
    return f"{d.year}년 {d.month}월 {d.day}일"


_DL_DATE_RE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})")


def _parse_dl_date(text: str) -> str | None:
    """Fallback for when JSON-LD is missing/malformed: the `<dl>` DATE
    row's own `"2026. 9. 5(토)"` (or a `"... ~ ..."` range - only the first,
    start, date is read; nothing here treats a range's end as a distinct
    occurrence)."""
    match = _DL_DATE_RE.search(text)
    if not match:
        return None
    year, month, day_num = (int(g) for g in match.groups())
    try:
        return date(year, month, day_num).isoformat()
    except ValueError:
        return None


def _parse_clock(text: str) -> tuple[int, int] | None:
    text = text.strip()
    if ":" not in text:
        return None
    h, _, m = text.partition(":")
    try:
        return int(h), int(m)
    except ValueError:
        return None


def format_time_range(raw_time: str | None) -> str | None:
    """Miltang's own `"19:00~23:00"` / `"23:30~28:30"` (overnight) folded to
    a plain 24-hour `"HH:MM~HH:MM"` - same reasoning and same shape as
    `tangonow_discovery.format_time_range()`: no am/pm marker is invented,
    so the engine's own honesty rule (ambiguous when the start hour is
    1-12 with no other evidence) still applies. Kept as this module's own
    copy rather than imported from a sibling source module - the same
    "small independent modules" choice every discovery module here makes."""
    if not raw_time or not isinstance(raw_time, str):
        return None
    for sep in ("-", "~", "–", "—"):
        if sep in raw_time:
            start_raw, _, end_raw = raw_time.partition(sep)
            break
    else:
        return None
    start = _parse_clock(start_raw)
    end = _parse_clock(end_raw)
    if start is None or end is None:
        return None
    h1, m1 = start
    h2, m2 = end
    return f"{h1 % 24:02d}:{m1:02d}~{h2 % 24:02d}:{m2:02d}"


# --- HTML field extraction ----------------------------------------------------

def _visible(segment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", segment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


_LD_JSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)


def _extract_json_ld(raw_html_text: str) -> dict[str, Any] | None:
    """The detail page's own `Schema.org Event` block, if present and
    parseable - absence or malformed JSON is not fatal, `parse_detail()`
    falls back to the `<dl>` fields either way."""
    match = _LD_JSON_RE.search(raw_html_text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and isinstance(data.get("@graph"), list):
        candidates = data["@graph"]
    elif isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        return data
    else:
        return None
    for node in candidates:
        if isinstance(node, dict) and node.get("@type") == "Event":
            return node
    return None


def _dt_dd_segment(raw_html_text: str, label: str) -> str | None:
    """The raw (unstripped) `<dd>` content following a `<dt>LABEL</dt>` -
    Miltang's own template for DATE/TIME/PLACE/ORG/LINK rows, confirmed
    live on both `/milongas/{id}` and `/notices/{id}` detail pages."""
    pattern = re.compile(
        r"<dt[^>]*>\s*" + re.escape(label) + r"\s*</dt>\s*<dd[^>]*>(.*?)</dd>", re.S,
    )
    match = pattern.search(raw_html_text)
    return match.group(1) if match else None


def _place_name_and_address(segment: str) -> tuple[str | None, str | None]:
    name_match = re.search(r'<p class="font-bold">(.*?)</p>', segment, re.S)
    addr_match = re.search(r'<p class="text-fg3 text-xs[^"]*">(.*?)</p>', segment, re.S)
    name = _visible(name_match.group(1)) if name_match else None
    address = _visible(addr_match.group(1)) if addr_match else None
    return (name or None, address or None)


def _link_urls(segment: str) -> list[str]:
    """Every original LINK on the detail page, in order - a milonga's LINK
    row can hold several contact channels at once (confirmed live: kakao
    open chat + Facebook + Instagram on the same record), not just one."""
    return [html.unescape(u) for u in re.findall(r'<a\s+href="([^"]+)"', segment)]


# Heuristic only (Section 5/6): a profile/root link (a Facebook/Instagram
# profile, a Daum Cafe root, a bare Kakao open-chat channel) is contact
# provenance, not one specific post about this event - never promoted to
# `source_url` regardless of this classification (source_url is always this
# module's own Miltang detail URL; see `parse_detail()`), but worth telling
# apart from a genuine post-level link (e.g. `facebook.com/share/p/...`) for
# provenance quality.
_PROFILE_ROOT_RE = re.compile(
    r"^https?://(?:www\.)?"
    r"(?:facebook\.com/(?!share/|groups/[^/]+/posts/)[^/?#]+/?$"
    r"|instagram\.com/[^/?#]+/?$"
    r"|cafe\.daum\.net/[^/?#]+/?$"
    r"|open\.kakao\.com/o/[^/?#]+/?$)",
)


def _is_profile_or_root_link(url: str) -> bool:
    return bool(_PROFILE_ROOT_RE.match(url or ""))


_BADGE_RE = re.compile(
    r'<span class="inline-block text-xs font-bold text-brand-deep bg-brand-tint '
    r'px-2\.5 py-1 rounded">(.*?)</span>', re.S,
)
_RECURRENCE_WORD_RE = re.compile(r"매주|첫째주|둘째주|셋째주|넷째주|마지막주")


def _recurrence_label(raw_html_text: str) -> str | None:
    """The badge just above the title - a recurrence label on a milonga
    ("매주 토요일", "첫째주"), a plain type tag on a notice ("행사"). Only
    the recurrence-shaped case is surfaced; a notice's type tag adds
    nothing extra (its own JSON-LD `@type` already says `Event`)."""
    match = _BADGE_RE.search(raw_html_text)
    if not match:
        return None
    text = _visible(match.group(1))
    return text if text and _RECURRENCE_WORD_RE.search(text) else None


_TITLE_RE = re.compile(r'<h2 class="text-2xl font-bold text-fg1[^"]*">(.*?)</h2>', re.S)
_DESCRIPTION_RE = re.compile(
    r'<h3 class="text-xs font-bold text-brand tracking-widest">DESCRIPTION</h3>\s*'
    r'<div class="[^"]*">(.*?)</div>', re.S,
)


def parse_detail(raw_html_text: str, detail_url: str) -> dict[str, Any] | None:
    """One `/milongas/{id}` or `/notices/{id}` detail page -> a
    RawPostRecord-shaped dict, or None if it has no usable title/date at all
    (never guessed - Section 4, items 7-9)."""
    ld = _extract_json_ld(raw_html_text) or {}

    title = str(ld.get("name") or "").strip()
    if not title:
        match = _TITLE_RE.search(raw_html_text)
        title = _visible(match.group(1)) if match else ""
    if not title:
        return None

    raw_date = ld.get("startDate")
    if not raw_date:
        date_segment = _dt_dd_segment(raw_html_text, "DATE")
        raw_date = _parse_dl_date(_visible(date_segment)) if date_segment else None
    event_date = _format_date_kr(raw_date)
    if not event_date:
        return None

    time_segment = _dt_dd_segment(raw_html_text, "TIME")
    time_expr = format_time_range(_visible(time_segment)) if time_segment else None

    location = ld.get("location") if isinstance(ld.get("location"), dict) else {}
    venue = str(location.get("name") or "").strip() or None
    address = None
    if isinstance(location.get("address"), dict):
        address = str(location["address"].get("streetAddress") or "").strip() or None
    place_segment = _dt_dd_segment(raw_html_text, "PLACE")
    if place_segment:
        html_venue, html_address = _place_name_and_address(place_segment)
        venue = venue or html_venue
        address = address or html_address

    organizer = None
    if isinstance(ld.get("organizer"), dict):
        organizer = str(ld["organizer"].get("name") or "").strip() or None
    if not organizer:
        org_segment = _dt_dd_segment(raw_html_text, "ORG")
        organizer = _visible(org_segment) if org_segment else None
        organizer = organizer or None

    link_segment = _dt_dd_segment(raw_html_text, "LINK")
    links = _link_urls(link_segment) if link_segment else []

    recurrence = _recurrence_label(raw_html_text)

    description_match = _DESCRIPTION_RE.search(raw_html_text)
    description = _visible(description_match.group(1)) if description_match else None

    parts = [event_date]
    if time_expr:
        parts.append(f"시간: {time_expr}")
    if venue:
        venue_part = f"장소: {venue}"
        if address:
            venue_part += f" ({address})"
        parts.append(venue_part)
    if organizer:
        parts.append(f"주최: {organizer}")
    if recurrence:
        parts.append(f"반복: {recurrence}")
    if description:
        parts.append(description)
    if links:
        parts.append("원문 링크: " + ", ".join(links))

    return {
        "source_url": detail_url,
        "title": title,
        "body": " ".join(parts),
        "published_at": None,
        "acquisition_quality": "FETCHED_FULL",
    }


# --- list pages: detail-URL discovery only ------------------------------------

def _extract_detail_urls(raw_html_text: str, list_url: str, path_prefix: str) -> list[str]:
    pattern = re.compile(r'href="(/' + re.escape(path_prefix) + r'/\d+)"')
    seen: set[str] = set()
    urls: list[str] = []
    for match in pattern.finditer(raw_html_text):
        absolute = urllib.parse.urljoin(list_url, match.group(1))
        if absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)
    return urls


def _list_path_prefix(list_url: str) -> str | None:
    path = urllib.parse.urlparse(list_url).path
    if "/notices" in path:
        return "notices"
    if "/milongas" in path:
        return "milongas"
    return None


def parse_list(raw_html_text: str, list_url: str) -> list[dict[str, Any]]:
    """`collectors._collect_snapshot()`'s generic WEB entry point: detail
    URLs only, tagged METADATA_ONLY - the same role `danceinfo_discovery
    .parse_list()` plays for its own two-stage (list -> detail) source.
    Full field data only comes from `parse_detail()`/`discover()`, which is
    what a fixture wanting real body content should call directly."""
    prefix = _list_path_prefix(list_url)
    if prefix is None:
        raise DiscoveryError(f"{list_url} is not a recognised Miltang list URL")
    posts: list[dict[str, Any]] = []
    for url in _extract_detail_urls(raw_html_text, list_url, prefix):
        posts.append({
            "source_url": url,
            "title": "",
            "body": "",
            "published_at": None,
            "acquisition_quality": "METADATA_ONLY",
        })
    return posts


def discover(
    list_url: str, *, source_id: str, platform: str = "WEB",
    timeout: int = DEFAULT_TIMEOUT, opener=None, days_ahead: int = 0,
) -> list[dict[str, Any]]:
    """Every milonga/notice detail Miltang links from `list_url`'s own
    board, fully parsed (Section 4's parser responsibilities are carried out
    here, not deferred to a later acquisition step - unlike DanceInfo's
    split, this source's detail page needs JSON-LD + `<dl>` parsing no
    generic later fetch would know how to do).

    `days_ahead` only widens a `/milongas` list (each day requested with
    its own matching `week=`+`date=`, Section 9's "날짜별 요청 수를 줄이는
    구조" - none exists here beyond requesting one day at a time, since the
    list itself is day-scoped, confirmed live); a `/notices` list_url is
    fetched once regardless, since notices are not date-scoped at all.
    """
    prefix = _list_path_prefix(list_url)
    if prefix is None:
        raise DiscoveryError(f"{list_url} is not a recognised Miltang list URL")

    detail_urls: list[str] = []
    seen: set[str] = set()

    if prefix == "notices":
        raw = _fetch_html(list_url, timeout=timeout, opener=opener)
        for url in _extract_detail_urls(raw, list_url, "notices"):
            if url not in seen:
                seen.add(url)
                detail_urls.append(url)
    else:
        span = max(0, min(days_ahead, MAX_DAYS_AHEAD))
        today = _seoul_today()
        for offset in range(span + 1):
            day = today + timedelta(days=offset)
            dated_url = _dated_milonga_url(list_url, day)
            raw = _fetch_html(dated_url, timeout=timeout, opener=opener)
            page_date = _extract_page_date(raw)
            if page_date is None:
                raise DiscoveryError(
                    f"{dated_url} has no readable day header - list page shape changed"
                )
            if page_date != day:
                raise DiscoveryError(
                    f"{dated_url} rendered {page_date.isoformat()} instead of the "
                    f"requested {day.isoformat()} - date-navigation shape changed"
                )
            for url in _extract_detail_urls(raw, dated_url, "milongas"):
                if url not in seen:
                    seen.add(url)
                    detail_urls.append(url)

    detail_urls = detail_urls[:MAX_DETAIL_FETCHES]
    posts: list[dict[str, Any]] = []
    for detail_url in detail_urls:
        raw_detail = _fetch_html(detail_url, timeout=timeout, opener=opener)
        post = parse_detail(raw_detail, detail_url)
        if post is not None:
            posts.append(post)

    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
