import html
import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from .base import RawPostRecord

TAG_RE = re.compile(r"<[^>]+>")

class MissingNaverCredentials(RuntimeError):
    pass

class NaverCollectorError(RuntimeError):
    pass

def _clean(s):
    if not s:
        return ""
    return " ".join(TAG_RE.sub("", html.unescape(s)).split())

class NaverSearchCollector:
    def __init__(self, timeout_seconds=15, client_id=None, client_secret=None):
        self.timeout_seconds = timeout_seconds
        self.client_id = client_id or os.getenv("NAVER_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("NAVER_CLIENT_SECRET")

    def _require_credentials(self):
        if not self.client_id or not self.client_secret:
            raise MissingNaverCredentials("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET are not set")

    def _endpoint(self, kind):
        if kind == "blog":
            return "https://openapi.naver.com/v1/search/blog.json"
        if kind == "cafe":
            return "https://openapi.naver.com/v1/search/cafearticle.json"
        raise ValueError(f"Unsupported Naver search kind: {kind}")

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
                "X-Naver-Client-Id": self.client_id,
                "X-Naver-Client-Secret": self.client_secret,
                "Accept": "application/json",
                "User-Agent": "DanceMate-InformationEngine-PoC/0.5",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise NaverCollectorError(f"Naver HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise NaverCollectorError(f"Naver network error: {e.reason}") from e

        rows = []
        for item in payload.get("items", []):
            url = item.get("link") or ""
            title = _clean(item.get("title"))
            desc = _clean(item.get("description"))
            published = item.get("postdate")
            if published and len(published) == 8 and published.isdigit():
                published = f"{published[0:4]}-{published[4:6]}-{published[6:8]}"
            rows.append(RawPostRecord(
                source_id=source_id or ("SRC-N-001" if kind=="blog" else "SRC-N-002"),
                platform="NAVER_BLOG" if kind=="blog" else "NAVER_CAFE",
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
            platform="NAVER_BLOG" if kind=="blog" else "NAVER_CAFE",
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
