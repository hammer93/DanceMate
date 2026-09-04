import html
import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from .base import RawPostRecord

TAG_RE = re.compile(r"<[^>]+>")

# NAVER API HUB. Not the legacy Naver Developers Search API: a different host
# and different authentication headers, and the two must never be mixed --
# legacy headers authenticate nothing here, and the gateway answers 401 without
# saying which half was wrong.
#
# The response payload has the same shape the legacy API returned
# (lastBuildDate/total/start/display/items), so everything below the request
# itself is unchanged.
API_HUB_BASE = "https://naverapihub.apigw.ntruss.com"

# Verified live against the gateway on 2026-09-04: these three answer 200.
# news and local answer 401 for these credentials and doc does not exist, so
# none of the three is offered here.
ENDPOINTS = {
    "blog": "/search/v1/blog",
    "cafe": "/search/v1/cafearticle",
    "web": "/search/v1/webkr",
}

PLATFORM_BY_KIND = {
    "blog": "NAVER_BLOG",
    "cafe": "NAVER_CAFE",
    "web": "NAVER_WEB",
}

DEFAULT_SOURCE_ID_BY_KIND = {
    "blog": "SRC-N-001",
    "cafe": "SRC-N-002",
    "web": "SRC-N-003",
}


class MissingNaverCredentials(RuntimeError):
    pass

class NaverCollectorError(RuntimeError):
    pass

def _gateway_detail(error):
    """The gateway's own explanation, if it sent one. Never the request."""
    try:
        body = error.read().decode("utf-8", "replace")[:300]
    except Exception:
        return ""
    if not body.strip():
        return ""
    try:
        parsed = json.loads(body)
    except ValueError:
        return " - " + " ".join(body.split())
    message = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(message, dict):
        message = message.get("message") or message.get("errorCode")
    return f" - {message}" if message else ""


def _clean(s):
    if not s:
        return ""
    return " ".join(TAG_RE.sub("", html.unescape(s)).split())

class NaverSearchCollector:
    """NAVER API HUB Search.

    The credentials keep their old environment variable names for
    compatibility, but they are API HUB keys and are sent the way API HUB
    expects them: X-NCP-APIGW-API-KEY-ID and X-NCP-APIGW-API-KEY.
    """

    def __init__(self, timeout_seconds=15, client_id=None, client_secret=None,
                 base_url=None):
        self.timeout_seconds = timeout_seconds
        # Named for the old API, issued by API HUB. Renaming them would break
        # every deployed .env for no gain.
        self.client_id = client_id or os.getenv("NAVER_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("NAVER_CLIENT_SECRET")
        self.base_url = (base_url or os.getenv("NAVER_API_HUB_BASE")
                         or API_HUB_BASE).rstrip("/")

    def _require_credentials(self):
        if not self.client_id or not self.client_secret:
            raise MissingNaverCredentials("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET are not set")

    def _endpoint(self, kind):
        try:
            return f"{self.base_url}{ENDPOINTS[kind]}"
        except KeyError:
            raise ValueError(
                f"Unsupported Naver search kind: {kind}; "
                f"API HUB serves {', '.join(sorted(ENDPOINTS))}"
            ) from None

    def search(self, query, *, kind="blog", display=100, start=1, sort="date", source_id=None):
        self._require_credentials()
        params = urllib.parse.urlencode({
            "query": query,
            "display": display,
            "start": start,
            "sort": sort,
        })
        req = urllib.request.Request(
            f"{self._endpoint(kind)}?{params}",
            headers={
                "X-NCP-APIGW-API-KEY-ID": self.client_id,
                "X-NCP-APIGW-API-KEY": self.client_secret,
                "Accept": "application/json",
                "User-Agent": "DanceMate-InformationEngine/0.75 (+LAN staging)",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # The gateway explains itself in the body. It never echoes the
            # request headers back, so this cannot carry a credential.
            raise NaverCollectorError(
                f"Naver API HUB HTTP {e.code}: {e.reason}{_gateway_detail(e)}"
            ) from e
        except urllib.error.URLError as e:
            raise NaverCollectorError(f"Naver API HUB network error: {e.reason}") from e

        rows = []
        for item in payload.get("items", []):
            url = item.get("link") or ""
            title = _clean(item.get("title"))
            desc = _clean(item.get("description"))
            published = item.get("postdate")
            if published and len(published) == 8 and published.isdigit():
                published = f"{published[0:4]}-{published[4:6]}-{published[6:8]}"
            rows.append(RawPostRecord(
                source_id=source_id or DEFAULT_SOURCE_ID_BY_KIND.get(kind, "SRC-N-002"),
                platform=PLATFORM_BY_KIND.get(kind, "NAVER_CAFE"),
                source_url=url,
                title=title,
                body=desc,
                published_at=published,
                cafe_name=_clean(item.get("bloggername") or item.get("cafename") or ""),
                discovery_query=query,
                acquisition_quality="METADATA_ONLY",
                raw_json=json.dumps(item,ensure_ascii=False),
            ))
        return rows

def load_naver_snapshot(path, *, kind, source_id, query="snapshot"):
    payload=json.loads(open(path,encoding="utf-8").read())
    rows=[]
    for item in payload.get("items",[]):
        published=item.get("postdate")
        if published and len(published)==8 and published.isdigit():
            published=f"{published[0:4]}-{published[4:6]}-{published[6:8]}"
        rows.append(RawPostRecord(
            source_id=source_id,
            platform=PLATFORM_BY_KIND.get(kind, "NAVER_CAFE"),
            source_url=item.get("link") or "",
            title=_clean(item.get("title")),
            body=_clean(item.get("description")),
            published_at=published,
            cafe_name=_clean(item.get("bloggername") or item.get("cafename") or ""),
            discovery_query=query,
            acquisition_quality="METADATA_ONLY",
            raw_json=json.dumps(item,ensure_ascii=False)
        ))
    return rows
