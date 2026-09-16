"""Public Daum Cafe board-list discovery for a configured Community Source.

The Cafe's server-rendered list embeds article metadata in ``articles.push``.
Only the newest page and a bounded lookback are read. Detail acquisition stays
in the existing source-item pipeline; a blocked detail is never bypassed.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from datetime import date, timedelta
from typing import Any

from .web_discovery import DiscoveryError, _fetch_html

_ARTICLE = re.compile(r"articles\.push\(\{(?P<fields>.*?)\}\);", re.S)
_FIELD = lambda name: re.compile(rf"\b{name}:\s*'((?:\\.|[^'])*)'")
_ESCAPED_UNICODE = re.compile(r"\\u([0-9a-fA-F]{4})")
_DATE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})$")
_EVENT_DAY = re.compile(r"(?:20\d{2}[./-]|\d{2}년)?\s*\d{1,2}\s*(?:월|[./-])\s*\d{1,2}\s*일?")
_OWN_SOCIAL = re.compile(r"정모|정기모임|벙개|소셜|파티|party|social", re.I)
_CLASS = re.compile(r"강습|개강|워크숍|워크샵|오픈클래스|workshop|lesson", re.I)
_EXTERNAL_AD = re.compile(
    r"외부\s*홍보|타\s*동호회|다른\s*동호회|타\s*학원|외부\s*강사|"
    r"제휴\s*홍보|홍보합니다|공유합니다", re.I
)
_GENRE_WORDS = {
    "SALSA": re.compile(r"살사|salsa", re.I),
    "BACHATA": re.compile(r"바차타|bachata", re.I),
    "KIZOMBA": re.compile(r"키좀바|kizomba", re.I),
    "SWING": re.compile(r"스윙|swing", re.I),
    "TANGO": re.compile(r"탱고|땅고|tango", re.I),
}


def _decode(value: str) -> str:
    value = _ESCAPED_UNICODE.sub(lambda m: chr(int(m.group(1), 16)), value)
    value = value.replace(r"\/", "/").replace(r"\'", "'").replace("\\\\", "\\")
    value = re.sub(r"<[^>]*>", " ", html.unescape(value))
    return re.sub(r"\s+", " ", value).strip()


def parse_list(raw_html: str, list_url: str, *, cafe_url: str,
               lookback_days: int = 60, today: date | None = None,
               community_id: int | None = None, board_type: str = "EVENT_PRIMARY",
               board_name: str = "", genre_code: str = "SALSA") -> list[dict[str, Any]]:
    """Parse only ordinary rows, not pinned notices that can be years old."""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(list_url).query)
    grpid = (query.get("grpid") or [None])[0]
    fldid = (query.get("fldid") or [None])[0]
    cafe = urllib.parse.urlparse(cafe_url)
    code = cafe.path.strip("/").split("/")[0]
    if not grpid or not fldid or not code or cafe.netloc != "cafe.daum.net":
        raise DiscoveryError("Daum board requires public grpid/fldid and cafe URL")
    if not 1 <= lookback_days <= 90:
        raise DiscoveryError("lookback_days must be between 1 and 90")
    cutoff = (today or date.today()) - timedelta(days=lookback_days)
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for article in _ARTICLE.finditer(raw_html):
        fields = article.group("fields")
        values = {}
        for key in ("dataid", "grpid", "fldid", "title", "created"):
            match = _FIELD(key).search(fields)
            if match:
                values[key] = _decode(match.group(1))
        if values.get("grpid") != grpid or values.get("fldid") != fldid:
            continue
        number = values.get("dataid", "")
        title = values.get("title", "")
        stamp = _DATE.match(values.get("created", ""))
        if not number.isdigit() or not title or not stamp:
            continue
        primary = _GENRE_WORDS.get(genre_code)
        named_elsewhere = any(pattern.search(title) for code, pattern in
                              _GENRE_WORDS.items() if code != genre_code)
        if primary and named_elsewhere and not primary.search(title):
            # A Bachata-only class on a Salsa Community's mixed board does
            # not inherit SALSA just because the Source is Salsa-primary.
            continue
        try:
            published = date(2000 + int(stamp[1]), int(stamp[2]), int(stamp[3]))
        except ValueError:
            continue
        if published < cutoff or published > (today or date.today()) + timedelta(days=1):
            continue
        url = f"https://cafe.daum.net/{code}/{fldid}/{number}"
        if url in seen:
            continue
        seen.add(url)
        posts.append({
            "source_url": url,
            "title": title,
            "body": "",
            "published_at": f"{published.isoformat()}T00:00:00+09:00",
            "acquisition_quality": "METADATA_ONLY",
            "cafe_name": code,
            "board_url": list_url,
            "board_name": board_name,
            "board_type": board_type,
            "external_promotion": bool(_EXTERNAL_AD.search(f"{board_name} {title}")),
            "community_id": community_id,
            "external_article_id": f"{grpid}:{fldid}:{number}",
            # A dedicated official event board is Source Registry context,
            # but never turn an unrelated post into an Event on that alone.
            "known_event_type": "CLASS" if board_type == "CLASS_PRIMARY" else (
                "SOCIAL_WITH_CLASS" if _CLASS.search(title) else "SOCIAL"
            ) if (board_type == "EVENT_PRIMARY" and _OWN_SOCIAL.search(title)
                  and _EVENT_DAY.search(title) and "파티" not in title) else None,
            "class_event_opt_in": board_type == "CLASS_PRIMARY" and bool(_CLASS.search(title)),
        })
    if "articles.push" not in raw_html:
        raise DiscoveryError(f"no server-rendered article rows at {list_url}")
    return posts


def discover(list_url: str, *, source_id: str, cafe_url: str,
             lookback_days: int = 60, community_id: int | None = None,
             board_type: str = "EVENT_PRIMARY", board_name: str = "",
             genre_code: str = "SALSA", timeout: int = 15, opener=None,
             today: date | None = None
             ) -> list[dict[str, Any]]:
    raw = _fetch_html(list_url, timeout=timeout, opener=opener)
    posts = parse_list(raw, list_url, cafe_url=cafe_url,
                       lookback_days=lookback_days, today=today,
                       community_id=community_id, board_type=board_type,
                       board_name=board_name, genre_code=genre_code)
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = "DAUM_CAFE"
    return posts
