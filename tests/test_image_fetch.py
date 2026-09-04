"""Safe image fetch and selection (v0.81.3).

Image bytes come from whatever a source's post happens to link to - a
strictly more dangerous target than the post URL itself. Every fetch is
bounded: SSRF (private/loopback/link-local addresses, scheme, redirect
depth), size, and a real magic-byte check so a login page served at a `.jpg`
path is never treated as one.
"""

from __future__ import annotations

import io

import pytest

from runtime import image_fetch


# --- SSRF guard ---------------------------------------------------------------

def _resolver_for(*addrs):
    def resolver(host, port):
        return [(None, None, None, None, (addr, 0)) for addr in addrs]
    return resolver


@pytest.mark.parametrize("addr", [
    "127.0.0.1", "10.0.0.5", "172.16.0.5", "192.168.1.100",
    "169.254.1.1", "0.0.0.0", "::1", "fc00::1", "fe80::1",
])
def test_private_and_loopback_addresses_are_rejected(addr):
    with pytest.raises(image_fetch.UnsafeImageURL):
        image_fetch.resolve_safe("https://evil.test/x.jpg", resolver=_resolver_for(addr))


def test_a_public_address_is_accepted():
    host = image_fetch.resolve_safe("https://cdn.example.test/x.jpg",
                                     resolver=_resolver_for("93.184.216.34"))
    assert host == "cdn.example.test"


def test_one_private_address_among_several_public_ones_is_still_rejected():
    """Round-robin DNS answering with a mix of addresses - one private
    address is still a route inward, whatever else it also resolves to."""
    with pytest.raises(image_fetch.UnsafeImageURL):
        image_fetch.resolve_safe(
            "https://mixed.test/x.jpg",
            resolver=_resolver_for("93.184.216.34", "10.0.0.1"),
        )


@pytest.mark.parametrize("url", ["ftp://example.test/x.jpg", "file:///etc/passwd",
                                  "javascript:alert(1)"])
def test_non_http_schemes_are_rejected(url):
    with pytest.raises(image_fetch.UnsafeImageURL):
        image_fetch.resolve_safe(url, resolver=_resolver_for("93.184.216.34"))


def test_unresolvable_host_is_rejected_not_silently_allowed():
    def resolver(host, port):
        raise OSError("nodename nor servname provided")
    with pytest.raises(image_fetch.UnsafeImageURL):
        image_fetch.resolve_safe("https://nowhere.test/x.jpg", resolver=resolver)


# --- fetch: size, type, magic bytes -------------------------------------------

class _Resp(io.BytesIO):
    def __init__(self, body: bytes, *, content_type="image/jpeg"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}
        self.headers_get = lambda k, d="": self.headers.get(k, d)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class _FakeHeaders(dict):
    def get(self, key, default=""):
        return super().get(key, default)


def _opener_for(body: bytes, *, content_type="image/jpeg"):
    class _R(io.BytesIO):
        def __init__(self):
            super().__init__(body)
            self.headers = _FakeHeaders({"Content-Type": content_type})

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    class _Opener:
        def open(self, request, timeout=None):
            return _R()

    return lambda: _Opener()


JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 100
PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
WEBP_MAGIC = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100


@pytest.fixture(autouse=True)
def _safe_resolver(monkeypatch):
    monkeypatch.setattr(image_fetch.socket, "getaddrinfo", _resolver_for("93.184.216.34"))


# --- URL normalization (found live: unencoded Korean/space filenames) -------

def test_a_url_with_spaces_and_korean_characters_is_percent_encoded():
    """Found live on K-TANGO: a real upload filename with a literal space and
    Korean text, which urllib.request rejects outright unless normalized."""
    raw = "http://www.k-tango.net/upload/editor/1724737931402_582. KTSF 스페셜공연 국문포스터.jpg"
    normalized = image_fetch._normalize_url(raw)
    assert " " not in normalized
    assert "스페셜공연" not in normalized  # encoded, not stripped
    assert normalized.startswith("http://www.k-tango.net/upload/editor/1724737931402_582.")


def test_normalization_does_not_double_encode_an_already_encoded_url():
    already = "https://cdn.example.test/path/%EA%B0%80.jpg"
    assert image_fetch._normalize_url(already) == already


def test_a_previously_unfetchable_real_url_now_fetches(monkeypatch):
    monkeypatch.setattr(image_fetch.socket, "getaddrinfo", _resolver_for("93.184.216.34"))
    raw = "http://www.k-tango.net/upload/editor/1724737931402_582. KTSF 스페셜공연 국문포스터.jpg"
    result = image_fetch.fetch_image(raw, opener=_opener_for(JPEG_MAGIC))
    assert result.ok


def test_a_real_jpeg_is_fetched_successfully():
    result = image_fetch.fetch_image(
        "https://cdn.example.test/poster.jpg", opener=_opener_for(JPEG_MAGIC),
    )
    assert result.ok
    assert result.content_type == "image/jpeg"
    assert result.data == JPEG_MAGIC


def test_a_real_png_is_fetched_successfully():
    result = image_fetch.fetch_image(
        "https://cdn.example.test/poster.png", opener=_opener_for(PNG_MAGIC),
    )
    assert result.ok
    assert result.content_type == "image/png"


def test_a_real_webp_is_fetched_successfully():
    result = image_fetch.fetch_image(
        "https://cdn.example.test/poster.webp", opener=_opener_for(WEBP_MAGIC),
    )
    assert result.ok
    assert result.content_type == "image/webp"


def test_an_html_login_page_served_at_a_jpg_path_is_rejected():
    html = b"<html><body>login required</body></html>"
    result = image_fetch.fetch_image(
        "https://cdn.example.test/poster.jpg", opener=_opener_for(html),
    )
    assert result.status == "UNSUPPORTED_TYPE"


def test_an_oversized_image_is_rejected_before_fully_buffering():
    huge = JPEG_MAGIC + b"\x00" * (image_fetch.MAX_IMAGE_BYTES)
    result = image_fetch.fetch_image(
        "https://cdn.example.test/poster.jpg", opener=_opener_for(huge),
        max_bytes=1024,
    )
    assert result.status == "TOO_LARGE"


def test_an_unsafe_url_never_reaches_the_opener():
    called = []

    def opener():
        called.append(True)
        raise AssertionError("should never be called for an unsafe URL")

    result = image_fetch.fetch_image("ftp://cdn.example.test/x.jpg", opener=opener)
    assert result.status == "UNSAFE_URL"
    assert not called


# --- selection -----------------------------------------------------------------

def test_selection_caps_at_the_configured_limit():
    urls = [f"https://cdn.example.test/{i}.jpg" for i in range(10)]
    assert len(image_fetch.select_candidate_urls(urls, limit=3)) == 3


def test_selection_drops_known_non_poster_hints():
    urls = [
        "https://cdn.example.test/poster.jpg",
        "https://cdn.example.test/emoji_smile.png",
        "https://cdn.example.test/profile_avatar.png",
        "https://cdn.example.test/tracking_pixel.gif",
    ]
    selected = image_fetch.select_candidate_urls(urls)
    assert selected == ["https://cdn.example.test/poster.jpg"]


def test_selection_deduplicates():
    urls = ["https://cdn.example.test/a.jpg", "https://cdn.example.test/a.jpg"]
    assert image_fetch.select_candidate_urls(urls) == ["https://cdn.example.test/a.jpg"]


def test_selection_skips_non_http_urls():
    urls = ["data:image/png;base64,abcd", "https://cdn.example.test/a.jpg"]
    assert image_fetch.select_candidate_urls(urls) == ["https://cdn.example.test/a.jpg"]
