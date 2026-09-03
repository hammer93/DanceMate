"""Deep content acquisition: fetch the original post, not the search snippet.

A search API is a discovery layer. The v0.75 live intake averaged 97 characters
per item, which is why Time, Venue and Fee were missing from nearly every
candidate — the values are in the post body, and the body was never fetched.

    Search discovery -> source_item -> original URL -> acquisition
      -> extracted text -> engine extraction -> candidate

Two things this module does not do:

  * **No login, CAPTCHA or access-control bypass.** Only representations the
    site serves publicly are used, and `robots.txt` is honoured.
  * **No raw HTML hoarding.** Only the extracted article text is stored: raw
    pages are mostly chrome, carry copyright weight, and would wear the microSD
    for no extraction benefit.

Daum's desktop article URL is an iframe shell (~168 characters of CSS). The
mobile host serves the same post as real HTML, and `robots.txt` permits it —
that is the representation this fetches.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# --- statuses ---------------------------------------------------------------
# Reused verbatim by the admin console and the scheduler. FETCHED_FULL means the
# article body was actually obtained; nothing else may claim it.
METADATA_ONLY = "METADATA_ONLY"
FETCH_PENDING = "FETCH_PENDING"
FETCHED_FULL = "FETCHED_FULL"
FETCHED_PARTIAL = "FETCHED_PARTIAL"
FETCH_BLOCKED = "FETCH_BLOCKED"
FETCH_FAILED = "FETCH_FAILED"
LOGIN_REQUIRED = "LOGIN_REQUIRED"
UNSUPPORTED = "UNSUPPORTED"

SETTLED = frozenset({FETCHED_FULL, FETCHED_PARTIAL, LOGIN_REQUIRED, UNSUPPORTED})
RETRYABLE = frozenset({FETCH_PENDING, FETCH_FAILED})

# Text at or above this is treated as a real article body rather than a shell.
FULL_TEXT_THRESHOLD = 120
# Below this there is effectively nothing but page furniture.
MINIMUM_USEFUL_TEXT = 20

USER_AGENT = "Mozilla/5.0 (compatible; DanceMate/0.76; +LAN staging; contact=operator)"

# Politeness. The board is one client; there is no reason to be quick about it.
MIN_DELAY_SECONDS = 1.5
DEFAULT_TIMEOUT = 20

# Retry policy. Deliberately coarse - four rules, not a framework.
RETRY_BACKOFF = {
    "NETWORK": timedelta(minutes=15),
    "SERVER_ERROR": timedelta(minutes=30),
    "NOT_FOUND": timedelta(hours=12),
    "BLOCKED": timedelta(days=1),
}
MAX_ATTEMPTS = {
    "NETWORK": 5,
    "SERVER_ERROR": 5,
    "NOT_FOUND": 2,
    "BLOCKED": 2,
}


# --- personal data ----------------------------------------------------------
# Community event posts carry organiser phone numbers and bank account details.
# DanceMate needs date, time, venue and fee; it does not need those, and it must
# not accumulate them in a staging database or render them in a console.
_PHONE = re.compile(r"0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4}")
_ACCOUNT = re.compile(r"\b\d{10,16}\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_REDACTIONS = (
    (_PHONE, "[전화번호]"),
    (_ACCOUNT, "[계좌번호]"),
    (_EMAIL, "[이메일]"),
)


def redact_personal_data(text: str) -> tuple[str, int]:
    """Remove phone numbers, bank accounts and emails. Returns (text, count).

    Fees like "13,000원" survive because they carry a separator and a unit;
    a bare 10-16 digit run does not.
    """
    if not text:
        return "", 0
    removed = 0
    cleaned = text
    for pattern, placeholder in _REDACTIONS:
        cleaned, n = pattern.subn(placeholder, cleaned)
        removed += n
    return cleaned, removed


# --- representation selection ----------------------------------------------

@dataclass(frozen=True)
class Representation:
    """A publicly served form of the same post."""

    url: str
    reason: str


def representations(url: str) -> list[Representation]:
    """Public representations to try, best first.

    Daum's desktop page is an iframe shell; the mobile host serves the article.
    Anything else is fetched as given.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    options: list[Representation] = []
    if host == "cafe.daum.net":
        options.append(
            Representation(
                url=urllib.parse.urlunparse(parsed._replace(netloc="m.cafe.daum.net")),
                reason="daum desktop page is an iframe shell; the mobile host serves the article",
            )
        )
    options.append(Representation(url=url, reason="as discovered"))
    return options


# --- article extraction -----------------------------------------------------

_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

# Markers bracketing the article body on Daum's mobile page. Between the font
# size control and the search footer is the post itself; everything outside is
# navigation, comment UI and site chrome.
_ARTICLE_START = "글자크기 크게 가"
_ARTICLE_END = "다음검색"

_OG_DESCRIPTION = re.compile(
    r"<meta[^>]+property=[\"']og:description[\"'][^>]*content=[\"']([^\"']*)", re.I
)
_OG_TITLE = re.compile(
    r"<meta[^>]+property=[\"']og:title[\"'][^>]*content=[\"']([^\"']*)", re.I
)
_IMG_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)", re.I)

METHOD_ARTICLE_REGION = "article_region"
METHOD_OG_DESCRIPTION = "og_description"
METHOD_VISIBLE_TEXT = "visible_text"
METHOD_NONE = "none"


def visible_text(raw_html: str) -> str:
    stripped = _SCRIPT_OR_STYLE.sub(" ", raw_html)
    stripped = _TAG.sub(" ", stripped)
    return _WHITESPACE.sub(" ", html.unescape(stripped)).strip()


def extract_article(raw_html: str) -> tuple[str, str]:
    """Pull the article body out of a page. Returns (text, method).

    Tried in order of how much of the real post each yields, measured on the
    live Daum pages: article region 434 chars, og:description 190 (truncated
    mid-sentence by the site), whole visible page 813 including chrome.
    """
    text = visible_text(raw_html)

    start = text.find(_ARTICLE_START)
    end = text.find(_ARTICLE_END, start + 1 if start >= 0 else 0)
    if start >= 0 and end > start:
        body = text[start + len(_ARTICLE_START):end].strip()
        if len(body) >= MINIMUM_USEFUL_TEXT:
            return body, METHOD_ARTICLE_REGION

    match = _OG_DESCRIPTION.search(raw_html)
    if match:
        body = _WHITESPACE.sub(" ", html.unescape(match.group(1))).strip()
        if len(body) >= MINIMUM_USEFUL_TEXT:
            return body, METHOD_OG_DESCRIPTION

    if len(text) >= MINIMUM_USEFUL_TEXT:
        return text, METHOD_VISIBLE_TEXT
    return text, METHOD_NONE


def extract_title(raw_html: str) -> str | None:
    match = _OG_TITLE.search(raw_html)
    return html.unescape(match.group(1)).strip() if match else None


def extract_images(raw_html: str, base_url: str) -> list[str]:
    seen: list[str] = []
    for src in _IMG_SRC.findall(raw_html):
        absolute = urllib.parse.urljoin(base_url, html.unescape(src))
        if absolute not in seen:
            seen.append(absolute)
    return seen


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# --- robots -----------------------------------------------------------------

_ROBOTS_CACHE: dict[str, Any] = {}


def robots_allows(url: str, *, user_agent: str = "DanceMate") -> bool:
    """Honour robots.txt. On any doubt, allow - but never on an explicit Disallow."""
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    parser = _ROBOTS_CACHE.get(origin)
    if parser is None:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            parser.read()
        except Exception:
            # An unreachable robots.txt is not a prohibition.
            _ROBOTS_CACHE[origin] = False
            return True
        _ROBOTS_CACHE[origin] = parser
    if parser is False:
        return True
    try:
        return bool(parser.can_fetch(user_agent, url))
    except Exception:
        return True


# --- fetching ---------------------------------------------------------------

@dataclass
class AcquisitionOutcome:
    status: str
    method: str = METHOD_NONE
    fetched_url: str | None = None
    canonical_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    title: str | None = None
    text: str = ""
    images: list[str] = field(default_factory=list)
    redacted_spans: int = 0
    error_code: str | None = None
    error: str | None = None
    duration_ms: int = 0

    @property
    def content_length(self) -> int:
        return len(self.text)

    @property
    def content_hash(self) -> str | None:
        return content_hash(self.text) if self.text else None

    @property
    def retry_class(self) -> str | None:
        return {
            FETCH_FAILED: "NETWORK",
            FETCH_BLOCKED: "BLOCKED",
        }.get(self.status)


def _classify_http_error(code: int) -> tuple[str, str]:
    if code in (401, 403):
        return LOGIN_REQUIRED, "BLOCKED"
    if code == 404:
        return FETCH_BLOCKED, "NOT_FOUND"
    if code == 429:
        return FETCH_BLOCKED, "BLOCKED"
    if 500 <= code <= 599:
        return FETCH_FAILED, "SERVER_ERROR"
    return FETCH_FAILED, "NETWORK"


def fetch(url: str, *, timeout: int = DEFAULT_TIMEOUT, opener=None) -> AcquisitionOutcome:
    """Fetch one post and extract its article body. Never raises.

    Tries each public representation in turn. A representation that fails or
    yields no article is not the post failing - the next form gets a go - but
    the last one's outcome is what gets reported.
    """
    started = time.monotonic()
    options = representations(url)
    open_url = opener or urllib.request.urlopen
    last: AcquisitionOutcome | None = None

    for index, representation in enumerate(options):
        is_last = index == len(options) - 1
        target = representation.url

        if not robots_allows(target):
            last = AcquisitionOutcome(
                status=FETCH_BLOCKED, fetched_url=target,
                error_code="ROBOTS_DISALLOWED",
                error=f"robots.txt disallows {target}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            # A disallowed URL is a decision, not a transport failure: respect
            # it immediately rather than trying another form of the same page.
            return last

        request = urllib.request.Request(
            target,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
            },
            method="GET",
        )
        try:
            with open_url(request, timeout=timeout) as response:
                status_code = getattr(response, "status", 200)
                content_type = response.headers.get("Content-Type", "")
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read()
                final_url = response.geturl()
        except urllib.error.HTTPError as exc:
            status, retry = _classify_http_error(exc.code)
            last = AcquisitionOutcome(
                status=status, fetched_url=target, http_status=exc.code,
                error_code=retry, error=f"HTTP {exc.code}: {exc.reason}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            continue
        except Exception as exc:
            last = AcquisitionOutcome(
                status=FETCH_FAILED, fetched_url=target,
                error_code="NETWORK", error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            continue

        try:
            raw = body.decode(charset, errors="replace")
        except LookupError:
            raw = body.decode("utf-8", errors="replace")

        if "html" not in content_type.lower() and "<html" not in raw[:500].lower():
            last = AcquisitionOutcome(
                status=UNSUPPORTED, fetched_url=target, http_status=status_code,
                content_type=content_type, error_code="UNSUPPORTED_CONTENT_TYPE",
                error=f"not HTML: {content_type}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            continue

        text, method = extract_article(raw)
        text, redacted = redact_personal_data(text)
        duration = int((time.monotonic() - started) * 1000)

        if len(text) >= FULL_TEXT_THRESHOLD:
            return AcquisitionOutcome(
                status=FETCHED_FULL, method=method, fetched_url=target,
                canonical_url=final_url, http_status=status_code,
                content_type=content_type, title=extract_title(raw), text=text,
                images=extract_images(raw, final_url), redacted_spans=redacted,
                duration_ms=duration,
            )

        if len(text) >= MINIMUM_USEFUL_TEXT:
            last = AcquisitionOutcome(
                status=FETCHED_PARTIAL, method=method, fetched_url=target,
                canonical_url=final_url, http_status=status_code,
                content_type=content_type, title=extract_title(raw), text=text,
                images=extract_images(raw, final_url), redacted_spans=redacted,
                error_code="THIN_BODY",
                error=f"only {len(text)} characters of text",
                duration_ms=duration,
            )
        else:
            # A page that served no article - Daum's desktop shell looks like
            # this. Never FETCHED_FULL, whatever the HTTP status said.
            candidate = AcquisitionOutcome(
                status=FETCH_BLOCKED, method=METHOD_NONE, fetched_url=target,
                canonical_url=final_url, http_status=status_code,
                content_type=content_type, error_code="BODY_UNAVAILABLE",
                error="page fetched but no article body was served",
                duration_ms=duration,
            )
            # Prefer a thin body over no body when reporting the final outcome.
            if last is None or last.status != FETCHED_PARTIAL:
                last = candidate
        if is_last:
            break

    if last is not None:
        return last
    return AcquisitionOutcome(
        status=FETCH_FAILED, error_code="NETWORK", error="no representation could be fetched",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def next_attempt_at(
    status: str, error_code: str | None, attempt_count: int, *, now: datetime | None = None
) -> datetime | None:
    """When may this be retried? None means never automatically.

    A settled outcome is not retried, an exhausted one is not retried, and a
    blocked page waits a day rather than being attacked every tick.
    """
    if status in SETTLED:
        return None
    retry_class = error_code if error_code in RETRY_BACKOFF else "NETWORK"
    if attempt_count >= MAX_ATTEMPTS.get(retry_class, 3):
        return None
    now = now or datetime.now(timezone.utc)
    return now + RETRY_BACKOFF[retry_class]
