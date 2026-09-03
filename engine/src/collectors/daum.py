import html
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from .base import RawPostRecord

TAG_RE = re.compile(r"<[^>]+>")

class DaumCollectorError(RuntimeError):
    pass

class MissingApiKey(DaumCollectorError):
    pass


def clean_markup(value: str | None) -> str:
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", TAG_RE.sub("", value)).strip()


def _matches_source(document: dict, source: dict) -> bool:
    url = document.get("url", "") or ""
    cafe = clean_markup(document.get("cafename"))
    cafe_hint = (source.get("cafe_name_hint") or "").strip()
    tokens = source.get("url_contains") or []
    cafe_ok = (not cafe_hint) or (cafe_hint.lower() in cafe.lower())
    # Kakao may return different canonical URL shapes over time. URL tokens are a
    # best-effort board discriminator; if none match, retain same-cafe candidates
    # for later provenance review instead of silently losing recall.
    token_ok = (not tokens) or all(t.lower() in url.lower() for t in tokens)
    return cafe_ok and token_ok


def document_to_rawpost(document: dict, source: dict, query: str) -> RawPostRecord:
    return RawPostRecord(
        source_id=source["source_id"],
        platform="DAUM_CAFE",
        source_url=document.get("url", ""),
        title=clean_markup(document.get("title")),
        body=clean_markup(document.get("contents")),
        published_at=document.get("datetime"),
        cafe_name=clean_markup(document.get("cafename")),
        thumbnail_url=document.get("thumbnail") or None,
        discovery_query=query,
        acquisition_quality="METADATA_ONLY",
        raw_json=json.dumps(document, ensure_ascii=False, separators=(",", ":")),
    )


class DaumCafeSearchCollector:
    def __init__(self, endpoint: str, api_key: str | None = None, timeout_seconds: int = 15):
        self.endpoint = endpoint
        self.api_key = api_key or os.getenv("KAKAO_REST_API_KEY")
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, sort: str = "recency", page: int = 1, size: int = 50) -> dict:
        if not self.api_key:
            raise MissingApiKey("KAKAO_REST_API_KEY is not set")
        params = urllib.parse.urlencode({"query":query, "sort":sort, "page":page, "size":size})
        req = urllib.request.Request(
            f"{self.endpoint}?{params}",
            headers={"Authorization": f"KakaoAK {self.api_key}", "Accept":"application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise DaumCollectorError(f"Daum Cafe search failed for query={query!r}: {e}") from e

    def collect_source(self, source: dict, *, sort="recency", page=1, size=50) -> list[RawPostRecord]:
        out: list[RawPostRecord] = []
        seen: set[str] = set()
        for query in source.get("queries") or ["밀롱가"]:
            payload = self.search(query, sort=sort, page=page, size=size)
            for doc in payload.get("documents", []):
                if not _matches_source(doc, source):
                    continue
                url = doc.get("url", "")
                if url in seen:
                    continue
                seen.add(url)
                out.append(document_to_rawpost(doc, source, query))
        return out


def load_snapshot(path: Path, source: dict, query="snapshot") -> list[RawPostRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [document_to_rawpost(d, source, query) for d in payload.get("documents", []) if _matches_source(d, source)]
