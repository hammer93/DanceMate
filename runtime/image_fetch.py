"""Safe fetch and selection of a post's attached images (v0.81.3).

`runtime.acquisition` already discovers a post's image URLs (`extract_images()`,
scoped to the whole raw page) while fetching its body. Nothing in this
project fetches the images themselves yet, and image bytes come from
whatever a source's post happens to link to - a strictly more dangerous
target than the post URL itself, which at least came from a known collector.
Every fetch here is bounded (size, type, redirect count) and every host is
checked against private/loopback/link-local ranges before *and after*
following a redirect, since a redirect is the server's own choice, made
after this module already approved the first hop.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# --- selection ---------------------------------------------------------------

MAX_IMAGES_PER_ITEM = 5
MIN_WIDTH = 200
MIN_HEIGHT = 100

# Never touch a chat icon or a share-button sprite embedded in the page.
_SKIP_URL_HINTS = ("emoji", "emoticon", "icon", "sprite", "pixel", "spacer",
                    "avatar", "profile", "button", "banner_ad")


def select_candidate_urls(urls: list[str], *, limit: int = MAX_IMAGES_PER_ITEM) -> list[str]:
    """Which of a post's discovered image URLs are worth fetching at all.

    Cheap, URL-only filtering - no network access yet. `extract_images()`
    scans the whole raw page, so nav/share-button/tracking images are common
    in the input; a real classification (`engine.media_classifier`, size,
    OCR result) only happens after the fetch this function gates.
    """
    seen: list[str] = []
    for url in urls:
        if not url or not url.lower().startswith(("http://", "https://")):
            continue
        lowered = url.lower()
        if any(hint in lowered for hint in _SKIP_URL_HINTS):
            continue
        if url not in seen:
            seen.append(url)
        if len(seen) >= limit:
            break
    return seen


# --- SSRF guard ---------------------------------------------------------------

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 5


class UnsafeImageURL(ValueError):
    """The URL (or one of its redirects) targets a non-public address."""


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def resolve_safe(url: str, *, resolver=None) -> str:
    """The URL's own hostname, if - and only if - every address it resolves
    to is a public one. Raises UnsafeImageURL otherwise.

    A hostname resolving to more than one address (round-robin DNS, or a
    server answering split A/AAAA records) must have *all* of them public:
    one private address among several is still a route inward.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeImageURL(f"scheme not allowed: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeImageURL("no host in URL")

    getaddrinfo = resolver or socket.getaddrinfo
    try:
        infos = getaddrinfo(host, None)
    except OSError as exc:
        raise UnsafeImageURL(f"cannot resolve {host!r}: {exc}") from exc
    if not infos:
        raise UnsafeImageURL(f"no address for {host!r}")

    for info in infos:
        raw_addr = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_addr.split("%")[0])
        except ValueError:
            raise UnsafeImageURL(f"unparseable address {raw_addr!r}") from None
        if not _is_public_ip(ip):
            raise UnsafeImageURL(f"{host!r} resolves to a non-public address {ip}")
    return host


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates every redirect hop, and refuses past MAX_REDIRECTS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        count = getattr(req, "_dancemate_redirects", 0) + 1
        if count > MAX_REDIRECTS:
            raise UnsafeImageURL(f"too many redirects (> {MAX_REDIRECTS})")
        resolve_safe(newurl)
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            new_req._dancemate_redirects = count
        return new_req


# --- fetch --------------------------------------------------------------------

MAX_IMAGE_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; DanceMate/0.81; +LAN staging; image fetch)"

SUPPORTED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

# Enough leading bytes to tell real image formats apart from anything else a
# server might serve at a URL that merely *looks* like an image (an HTML
# login page at a `.jpg` path is the common failure this catches).
_MAGIC_BYTES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),  # WEBP: RIFF....WEBP - confirmed after read below
)


def _sniff_content_type(head: bytes) -> str | None:
    for magic, content_type in _MAGIC_BYTES:
        if head.startswith(magic):
            if content_type == "image/webp" and head[8:12] != b"WEBP":
                continue
            return content_type
    return None


@dataclass
class ImageFetchResult:
    url: str
    status: str  # FETCHED | UNSAFE_URL | FETCH_FAILED | UNSUPPORTED_TYPE | TOO_LARGE
    content_type: str | None = None
    data: bytes = b""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "FETCHED"


def _normalize_url(url: str) -> str:
    """Percent-encode a URL's path/query for transport, without double-
    encoding anything already percent-encoded.

    Found live: real K-TANGO upload filenames contain literal spaces and
    Korean characters ("1724737931402_582. KTSF 스페셜공연 국문포스터.jpg"),
    which `extract_images()` carries through unencoded (real HTML routinely
    does, and browsers accept it) - urllib.request does not, and raises
    before any of this module's own safety checks even run.
    """
    parts = urllib.parse.urlsplit(url)
    safe = "%/:@!$&'()*+,;="  # reserved/sub-delim chars, and '%' so an
    # already-encoded byte like "%EA" is not re-encoded into "%25EA".
    path = urllib.parse.quote(parts.path, safe=safe)
    query = urllib.parse.quote(parts.query, safe=safe + "?")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def fetch_image(url: str, *, opener=None, resolver=None,
                max_bytes: int = MAX_IMAGE_BYTES) -> ImageFetchResult:
    """One image, bounded by size/type/redirect/host safety. Never raises."""
    url = _normalize_url(url)
    try:
        resolve_safe(url, resolver=resolver)
    except UnsafeImageURL as exc:
        return ImageFetchResult(url=url, status="UNSAFE_URL", error=str(exc))

    build_opener = opener or (
        lambda: urllib.request.build_opener(_SafeRedirectHandler)
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"}, method="GET",
    )
    try:
        with build_opener().open(request, timeout=FETCH_TIMEOUT) as response:
            declared_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    return ImageFetchResult(
                        url=url, status="TOO_LARGE",
                        error=f"exceeded {max_bytes} bytes",
                    )
                chunks.append(chunk)
    except UnsafeImageURL as exc:
        return ImageFetchResult(url=url, status="UNSAFE_URL", error=str(exc))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return ImageFetchResult(url=url, status="FETCH_FAILED", error=f"{type(exc).__name__}: {exc}")

    data = b"".join(chunks)
    sniffed = _sniff_content_type(data[:16])
    if sniffed is None or sniffed not in SUPPORTED_CONTENT_TYPES:
        return ImageFetchResult(
            url=url, status="UNSUPPORTED_TYPE",
            content_type=declared_type or sniffed,
            error=f"not a supported image (declared {declared_type!r}, sniffed {sniffed!r})",
        )
    return ImageFetchResult(url=url, status="FETCHED", content_type=sniffed, data=data)
