"""Boards and their posts (v0.88.0).

One board exists today: 공지사항 (``NOTICE``, seeded by migration 035). The
tables are the general shape - a post belongs to a board, and records what
kind of author wrote it - so a second board or a member login is an addition
later, not a reshaping. Only the admin console writes posts now.

A post is scoped to genres many-to-many (``board_post_genres``). A post with
no genre is a **global notice** and is shown under every genre selection
(see ``directory``'s genre policy).

A post's body is plain text. The public page escapes it, keeps its line
breaks and links bare http(s) addresses - it is never interpreted as HTML.
"""

from __future__ import annotations

from typing import Any

from . import master_edit
from .directory import (
    DirectoryError, as_bool, clean_line, clean_text, parse_ids, require_existing,
)

NOTICE = "NOTICE"

PUBLISHED = "PUBLISHED"
DRAFT = "DRAFT"
HIDDEN = "HIDDEN"
STATUSES = (PUBLISHED, DRAFT, HIDDEN)
STATUS_LABELS = {PUBLISHED: "게시", DRAFT: "임시저장", HIDDEN: "숨김"}

AUTHOR_ADMIN = "ADMIN"

TITLE_MAX = 200
BODY_MAX = 20000

# The same title and body sent to the same board again this soon is a second
# click, not a second notice. The console's submit guard stops most of these
# in the browser; this stops the rest.
DUPLICATE_WINDOW_SECONDS = 120

FIELDS = ("title", "body", "status", "pinned", "genre_ids")


class DuplicatePost(DirectoryError):
    def __init__(self, post_id: int):
        super().__init__("같은 제목과 본문의 공지가 방금 등록되었습니다 - 한 번만 저장했습니다")
        self.post_id = post_id


_SELECT = (
    "SELECT p.*, b.code AS board_code, "
    "  ARRAY(SELECT bpg.genre_id FROM board_post_genres bpg "
    "        WHERE bpg.post_id = p.post_id ORDER BY bpg.genre_id) AS genre_ids "
    "FROM board_posts p JOIN boards b ON b.board_id = p.board_id"
)


def _fetch(con, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(sql, params)
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def get_board(con, code: str = NOTICE) -> dict[str, Any] | None:
    rows = _fetch(con, "SELECT * FROM boards WHERE code = %s", (code,))
    return rows[0] if rows else None


def list_posts(con, board_code: str = NOTICE) -> list[dict[str, Any]]:
    """Every post of the board, whatever its status - the console's view."""
    return _fetch(
        con,
        _SELECT + " WHERE b.code = %s ORDER BY p.pinned DESC, "
        "COALESCE(p.published_at, p.created_at) DESC, p.post_id DESC",
        (board_code,),
    )


def get_post(con, post_id: int, board_code: str = NOTICE) -> dict[str, Any] | None:
    rows = _fetch(con, _SELECT + " WHERE p.post_id = %s AND b.code = %s",
                  (post_id, board_code))
    return rows[0] if rows else None


def _validated(con, fields: dict[str, Any]) -> dict[str, Any]:
    status = str(fields.get("status") or PUBLISHED).strip().upper()
    if status not in STATUSES:
        raise DirectoryError(f"상태: {', '.join(STATUSES)} 중 하나여야 합니다")
    data = {
        "title": clean_line(fields.get("title"), what="제목", max_len=TITLE_MAX,
                            required=True),
        "body": clean_text(fields.get("body"), what="본문", max_len=BODY_MAX) or "",
        "status": status,
        "pinned": as_bool(fields.get("pinned", False)),
        "genre_ids": sorted(parse_ids(fields.get("genre_ids"), what="장르")),
    }
    require_existing(con, "genres", data["genre_ids"], what="장르")
    return data


def _set_genres(con, post_id: int, genre_ids: list[int]) -> None:
    with con.cursor() as cur:
        cur.execute("DELETE FROM board_post_genres WHERE post_id = %s", (post_id,))
        for genre_id in genre_ids:
            cur.execute("INSERT INTO board_post_genres (post_id, genre_id) VALUES (%s, %s)",
                        (post_id, genre_id))


def _audit(data: dict[str, Any]) -> dict[str, Any]:
    """What the audit trail keeps of a post: everything but the body's text,
    whose length stands in for it (a notice can run to 20,000 characters)."""
    kept = {k: v for k, v in data.items() if k != "body"}
    if "body" in data:
        kept["body_chars"] = len(data["body"] or "")
    return kept


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {"title": row["title"], "body": row["body"] or "", "status": row["status"],
            "pinned": bool(row["pinned"]), "genre_ids": sorted(row.get("genre_ids") or [])}


def _require(con, post_id: int, board_code: str) -> dict[str, Any]:
    row = get_post(con, post_id, board_code)
    if row is None:
        raise DirectoryError(f"게시글 {post_id}을(를) 찾을 수 없습니다")
    return row


def create_post(con, fields: dict[str, Any], *, board_code: str = NOTICE,
                reviewer: str = "admin") -> dict[str, Any]:
    board = get_board(con, board_code)
    if board is None:
        raise DirectoryError(f"게시판 {board_code}이(가) 없습니다")
    data = _validated(con, fields)
    with con.cursor() as cur:
        cur.execute(
            "SELECT post_id FROM board_posts WHERE board_id = %s AND title = %s "
            "AND body = %s AND created_at > now() - make_interval(secs => %s) "
            "ORDER BY post_id DESC LIMIT 1",
            (board["board_id"], data["title"], data["body"], DUPLICATE_WINDOW_SECONDS),
        )
        again = cur.fetchone()
    if again:
        raise DuplicatePost(again[0])
    with con.transaction():
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO board_posts (board_id, title, body, status, pinned, "
                "  author_kind, author_name, published_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, "
                "  CASE WHEN %s = 'PUBLISHED' THEN now() END) RETURNING post_id",
                (board["board_id"], data["title"], data["body"], data["status"],
                 data["pinned"], AUTHOR_ADMIN, reviewer, data["status"]),
            )
            post_id = cur.fetchone()[0]
        _set_genres(con, post_id, data["genre_ids"])
        master_edit.record(
            con, entity_type=master_edit.BOARD_POST, entity_id=post_id,
            action=master_edit.CREATE, reviewer=reviewer, entity_name=data["title"],
            after=_audit(data), detail=f"created {board_code} post",
        )
    return get_post(con, post_id, board_code)


def update_post(con, post_id: int, fields: dict[str, Any], *, board_code: str = NOTICE,
                reviewer: str = "admin") -> dict[str, Any]:
    """The first time a post is published it gets its date; later saves keep it."""
    before = _require(con, post_id, board_code)
    data = _validated(con, fields)
    old = snapshot(before)
    changed = [key for key in FIELDS if old[key] != data[key]]
    if not changed:
        return {"post": before, "changed": []}
    with con.transaction():
        with con.cursor() as cur:
            cur.execute(
                "UPDATE board_posts SET title = %s, body = %s, status = %s, pinned = %s, "
                "  published_at = CASE WHEN %s = 'PUBLISHED' AND published_at IS NULL "
                "                      THEN now() ELSE published_at END, "
                "  updated_at = now() WHERE post_id = %s",
                (data["title"], data["body"], data["status"], data["pinned"],
                 data["status"], post_id),
            )
        _set_genres(con, post_id, data["genre_ids"])
        master_edit.record(
            con, entity_type=master_edit.BOARD_POST, entity_id=post_id,
            action=master_edit.EDIT, reviewer=reviewer, entity_name=data["title"],
            before=_audit({k: old[k] for k in changed}),
            after=_audit({k: data[k] for k in changed}),
        )
    return {"post": get_post(con, post_id, board_code), "changed": changed}


def delete_post(con, post_id: int, *, board_code: str = NOTICE,
                reviewer: str = "admin") -> dict[str, Any]:
    """The post and its genre links; nothing else refers to a post."""
    before = _require(con, post_id, board_code)
    with con.transaction():
        with con.cursor() as cur:
            cur.execute("DELETE FROM board_posts WHERE post_id = %s", (post_id,))
        master_edit.record(
            con, entity_type=master_edit.BOARD_POST, entity_id=post_id,
            action=master_edit.DELETE, reviewer=reviewer, entity_name=before["title"],
            before=_audit(snapshot(before)), detail=f"deleted {board_code} post",
        )
    return {"post": before}
