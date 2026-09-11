"""The public directory under the first screen's tabs (v0.88.0).

장소, 동호회, 정보원 and 게시판 are four lists a reader browses under the same
genre choice the event list uses (``public._selected_genres()`` and
``public._genre_constraint()``). This module is the read side of all four,
plus the small input rules the two new admin screens share.

**Genre policy.** One rule for every tab, fixed by
``tests/test_v0880_public_directory.py``:

* ``genre_codes is None`` - every enabled genre is ticked, or there is no
  choice to offer. Nothing is narrowed, and rows with no genre are listed
  too, exactly as the event list keeps events whose genre could not be read.
* a list of codes - a row is listed when any one of its genres is in it. A
  venue, community or source with **no genre** is left out: its genre is
  unknown (the Sources screen calls it "장르 미확인"), and listing it under
  "Tango" would be a guess.
* an empty list - the reader unticked everything - lists nothing.
* **Notices are the one exception, on purpose.** A notice written with no
  genre is a *global* notice: the operator chose to address everyone, so it
  is listed under every selection, the empty one included.

**What a source shows.** Its name, platform, tier, genre and region, and a
link to its human page - nothing else. The query below never selects the
collector's own settings (config, queries, notes, status, keys). The link
goes through the same resolver the event pages use, and a URL that carries
anything credential-shaped, or is an API endpoint rather than a page, is not
linked at all.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Sequence

from . import events_api, source_priority

NOTICE_BOARD = "NOTICE"

# How a source's platform reads to a dancer, not the internal enum.
PLATFORM_LABELS = {
    "DAUM_CAFE": "다음 카페",
    "NAVER_CAFE": "네이버 카페",
    "NAVER_BLOG": "네이버 블로그",
    "NAVER_WEB": "네이버 검색",
    "FACEBOOK": "Facebook",
    "WEB": "웹사이트",
    "DIRECTORY": "일정 사이트",
}
PLATFORM_FALLBACK = "기타"


class DirectoryError(ValueError):
    """An operator's input that cannot be saved, said in words."""


# --- input rules shared by the admin screens ---------------------------------

# Every C0 control except tab, line feed and carriage return, plus DEL. A NUL
# cannot even be stored in a Postgres TEXT column.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ID = re.compile(r"[1-9][0-9]{0,17}")


def clean_line(value: Any, *, what: str, max_len: int,
               required: bool = False) -> str | None:
    """One line of text: control characters dropped, whitespace collapsed."""
    text = " ".join(_CONTROL.sub("", str(value or "")).split())
    if not text:
        if required:
            raise DirectoryError(f"{what}: 필수 항목입니다")
        return None
    if len(text) > max_len:
        raise DirectoryError(f"{what}: {max_len}자 이하로 입력하세요")
    return text


def clean_text(value: Any, *, what: str, max_len: int) -> str | None:
    """Several lines of text: line breaks kept, other control characters dropped."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text).strip()
    if not text:
        return None
    if len(text) > max_len:
        raise DirectoryError(f"{what}: {max_len}자 이하로 입력하세요")
    return text


def clean_url(value: Any, *, what: str = "홈페이지 URL", max_len: int = 500) -> str | None:
    """An optional link a reader will be sent to: a real web page or nothing."""
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > max_len:
        raise DirectoryError(f"{what}: {max_len}자 이하로 입력하세요")
    if _CONTROL.search(text) or any(ch.isspace() for ch in text):
        raise DirectoryError(f"{what}: 공백이나 제어 문자를 넣을 수 없습니다")
    if events_api.valid_public_url(text) is None:
        raise DirectoryError(f"{what}: http:// 또는 https:// 로 시작하는 주소만 쓸 수 있습니다")
    if public_link(text) is None:
        raise DirectoryError(f"{what}: 계정 정보나 키가 들어 있는 주소는 저장할 수 없습니다")
    return text


def as_bool(value: Any) -> bool:
    """A form's "1"/"0" (or a real bool) as a bool. Anything unrecognised is False."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "on", "yes")


def parse_id(value: Any, *, what: str) -> int | None:
    """A positive whole-number id, or None for an empty field. Anything else
    is an error with a sentence, never a 500."""
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    if not _ID.fullmatch(text):
        raise DirectoryError(f"{what}: 올바른 ID가 아닙니다")
    return int(text)


def parse_ids(values: Any, *, what: str) -> list[int]:
    """Several ids (a multi-select), each checked, duplicates dropped, order kept."""
    if values is None or isinstance(values, (str, int)):
        values = [] if values is None else [values]
    ids: list[int] = []
    for value in values:
        number = parse_id(value, what=what)
        if number is not None and number not in ids:
            ids.append(number)
    return ids


# Only these tables, so the table name below is never anything a request sent.
_ID_TABLES = {"genres": "genre_id", "venues": "venue_id", "regions": "region_id"}


def require_existing(con, table: str, ids: Sequence[int], *, what: str) -> None:
    """Every id names a real row - checked before writing, so the operator is
    told which one is wrong instead of meeting a foreign-key error."""
    if not ids:
        return
    key = _ID_TABLES[table]
    with con.cursor() as cur:
        cur.execute(f"SELECT {key} FROM {table} WHERE {key} = ANY(%s)", (list(ids),))
        found = {row[0] for row in cur.fetchall()}
    missing = [i for i in ids if i not in found]
    if missing:
        raise DirectoryError(
            f"{what}: 존재하지 않는 항목입니다 (ID {', '.join(str(i) for i in missing[:5])})")


# --- links ---------------------------------------------------------------------

# Query parameter names that carry a secret rather than point at a page.
_SECRET_PARAMS = frozenset({
    "key", "apikey", "api_key", "access_key", "access_token", "token", "auth",
    "auth_token", "secret", "client_secret", "client_id", "password", "passwd",
    "pwd", "sig", "signature", "session", "sessionid", "sid",
})
# serviceKey, apiKey, x_token ... - a name ending like this is a credential.
_SECRET_SUFFIXES = ("key", "token", "secret", "password", "passwd")
# Hosts that only ever serve machines. A source pointing at one is collected
# through an API; there is no page there for a reader.
_API_HOSTS = frozenset({"openapi.naver.com", "firestore.googleapis.com",
                        "graph.facebook.com"})


def public_link(url: str | None) -> str | None:
    """``url`` when it is a page a reader may be sent to, else None.

    http(s) only (``events_api.valid_public_url()``), no user:password in
    it, no credential-shaped query parameter, and not an API endpoint.
    """
    safe = events_api.valid_public_url(url)
    if not safe:
        return None
    try:
        parts = urllib.parse.urlsplit(safe)
        host = (parts.hostname or "").lower()
        if parts.username or parts.password:
            return None
    except ValueError:
        return None
    if host in _API_HOSTS or parts.path.lower().endswith((".json", ".xml")):
        return None
    for name, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        key = name.strip().lower().replace("-", "_")
        if key in _SECRET_PARAMS or key.endswith(_SECRET_SUFFIXES):
            return None
    return safe


def public_source_link(url: str | None) -> str | None:
    """A source's human page: the event pages' own resolver, then the rules above."""
    return public_link(events_api.resolve_public_source_url(url))


# --- the four lists ------------------------------------------------------------

def _rows(con, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(sql, list(params))
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def _nothing_ticked(genre_codes: Sequence[str] | None) -> bool:
    return genre_codes is not None and not list(genre_codes)


def public_venues(con, genre_codes: Sequence[str] | None) -> list[dict[str, Any]]:
    """Enabled venues, narrowed through ``venue_genres`` (the v0.86.7 relation)."""
    if _nothing_ticked(genre_codes):
        return []
    sql = (
        "SELECT v.venue_id, v.name, v.address, r.name AS region_name, "
        "  ARRAY(SELECT g.code FROM venue_genres vg JOIN genres g ON g.genre_id = vg.genre_id "
        "        WHERE vg.venue_id = v.venue_id ORDER BY g.code) AS genre_codes "
        "FROM venues v LEFT JOIN regions r ON r.region_id = v.region_id "
        "WHERE v.enabled"
    )
    params: list[Any] = []
    if genre_codes is not None:
        sql += (" AND EXISTS (SELECT 1 FROM venue_genres vg JOIN genres g "
                "ON g.genre_id = vg.genre_id WHERE vg.venue_id = v.venue_id "
                "AND g.code = ANY(%s))")
        params.append(list(genre_codes))
    sql += " ORDER BY r.name NULLS LAST, lower(v.name), v.venue_id"
    return _rows(con, sql, params)


def public_communities(con, genre_codes: Sequence[str] | None) -> list[dict[str, Any]]:
    """Enabled communities with their enabled venues. The operator's notes
    are not selected."""
    if _nothing_ticked(genre_codes):
        return []
    sql = (
        "SELECT c.community_id, c.name, c.description, c.homepage_url, "
        "  r.name AS region_name, "
        "  ARRAY(SELECT g.code FROM community_genres cg JOIN genres g "
        "        ON g.genre_id = cg.genre_id WHERE cg.community_id = c.community_id "
        "        ORDER BY g.code) AS genre_codes, "
        "  ARRAY(SELECT v.name FROM community_venues cv JOIN venues v "
        "        ON v.venue_id = cv.venue_id WHERE cv.community_id = c.community_id "
        "        AND v.enabled ORDER BY lower(v.name)) AS venue_names "
        "FROM communities c LEFT JOIN regions r ON r.region_id = c.region_id "
        "WHERE c.enabled"
    )
    params: list[Any] = []
    if genre_codes is not None:
        sql += (" AND EXISTS (SELECT 1 FROM community_genres cg JOIN genres g "
                "ON g.genre_id = cg.genre_id WHERE cg.community_id = c.community_id "
                "AND g.code = ANY(%s))")
        params.append(list(genre_codes))
    sql += " ORDER BY lower(c.name), c.community_id"
    rows = _rows(con, sql, params)
    for row in rows:
        row["homepage_url"] = public_link(row.get("homepage_url"))
    return rows


def public_sources(con, genre_codes: Sequence[str] | None) -> list[dict[str, Any]]:
    """Enabled sources as a reader may see them: the most direct tier first."""
    if _nothing_ticked(genre_codes):
        return []
    sql = (
        "SELECT s.name, s.platform, s.source_role, s.url, "
        "  g.code AS genre_code, r.name AS region_name "
        "FROM sources s "
        "LEFT JOIN genres g ON g.genre_id = s.genre_id "
        "LEFT JOIN regions r ON r.region_id = s.region_id "
        "WHERE s.enabled"
    )
    params: list[Any] = []
    if genre_codes is not None:
        sql += " AND g.code = ANY(%s)"
        params.append(list(genre_codes))
    sql += " ORDER BY lower(s.name), s.source_id"
    shown = []
    for row in _rows(con, sql, params):
        role = row["source_role"]
        shown.append({
            "name": row["name"],
            "platform_label": PLATFORM_LABELS.get(row["platform"], PLATFORM_FALLBACK),
            "tier": source_priority.tier_of(role),
            "tier_label": source_priority.label_of(role),
            "genre_code": row["genre_code"],
            "region_name": row["region_name"],
            "public_url": public_source_link(row["url"]),
        })
    order = {tier: n for n, tier in enumerate(source_priority.TIERS)}
    shown.sort(key=lambda s: order[s["tier"]])  # stable: names stay A-Z within a tier
    return shown


def _notice_filter(genre_codes: Sequence[str] | None, params: list[Any]) -> str:
    if genre_codes is None:
        return ""
    params.append(list(genre_codes))
    # A notice with no genre rows is for everyone.
    return (" AND (NOT EXISTS (SELECT 1 FROM board_post_genres bpg "
            "WHERE bpg.post_id = p.post_id) "
            "OR EXISTS (SELECT 1 FROM board_post_genres bpg JOIN genres g "
            "ON g.genre_id = bpg.genre_id WHERE bpg.post_id = p.post_id "
            "AND g.code = ANY(%s)))")


_NOTICE_COLUMNS = (
    "SELECT p.post_id, p.title, p.pinned, p.published_at, "
    "  ARRAY(SELECT g.code FROM board_post_genres bpg JOIN genres g "
    "        ON g.genre_id = bpg.genre_id WHERE bpg.post_id = p.post_id "
    "        ORDER BY g.code) AS genre_codes"
)


def public_notices(con, genre_codes: Sequence[str] | None, *,
                   board_code: str = NOTICE_BOARD, limit: int = 100) -> list[dict[str, Any]]:
    """Published posts of an enabled board: pinned first, then newest."""
    from . import boards

    params: list[Any] = [board_code, boards.PUBLISHED]
    sql = (_NOTICE_COLUMNS
           # The start of the body for a one-line summary; the page shortens it.
           + ", left(p.body, 300) AS excerpt"
           + " FROM board_posts p JOIN boards b ON b.board_id = p.board_id "
           "WHERE b.code = %s AND b.enabled AND p.status = %s")
    sql += _notice_filter(genre_codes, params)
    sql += " ORDER BY p.pinned DESC, p.published_at DESC, p.post_id DESC LIMIT %s"
    params.append(int(limit))
    return _rows(con, sql, params)


def public_notice(con, post_id: int, *,
                  board_code: str = NOTICE_BOARD) -> dict[str, Any] | None:
    """One published post, or None - a draft or hidden post does not exist
    as far as a reader is concerned."""
    from . import boards

    rows = _rows(
        con,
        _NOTICE_COLUMNS + ", p.body FROM board_posts p JOIN boards b "
        "ON b.board_id = p.board_id WHERE p.post_id = %s AND b.code = %s "
        "AND b.enabled AND p.status = %s",
        [post_id, board_code, boards.PUBLISHED],
    )
    return rows[0] if rows else None
