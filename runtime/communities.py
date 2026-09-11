"""Communities (동호회) - canonical master data (v0.88.0).

A community is a real group of dancers: a club, a society, a regular crew.
It belongs to one region (optional), dances one or more genres and meets at
one or more venues - both many-to-many (``community_genres``,
``community_venues``). Only an operator creates one, in the console; nothing
is seeded or inferred from collected posts.

Every change is written to the same ``master_data_actions`` audit trail the
other master screens use. Deleting is deliberately two steps: a community is
disabled first (it leaves the public page at once) and only a disabled one
can be deleted. A delete removes the community and its own genre/venue links
- never a venue, a genre or anything else.
"""

from __future__ import annotations

from typing import Any

from . import master_edit
from .directory import (
    DirectoryError, as_bool, clean_line, clean_text, clean_url, parse_id, parse_ids,
    require_existing,
)

NAME_MAX = 120
DESCRIPTION_MAX = 1000
NOTES_MAX = 2000

# The fields an edit compares, in the order the audit trail lists them.
FIELDS = ("name", "region_id", "description", "homepage_url", "notes", "enabled",
          "genre_ids", "venue_ids")

_SELECT = (
    "SELECT c.*, r.name AS region_name, "
    "  ARRAY(SELECT cg.genre_id FROM community_genres cg "
    "        WHERE cg.community_id = c.community_id ORDER BY cg.genre_id) AS genre_ids, "
    "  ARRAY(SELECT cv.venue_id FROM community_venues cv "
    "        WHERE cv.community_id = c.community_id ORDER BY cv.venue_id) AS venue_ids "
    "FROM communities c LEFT JOIN regions r ON r.region_id = c.region_id"
)


def _fetch(con, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(sql, params)
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def list_communities(con, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = _SELECT + (" WHERE c.enabled" if enabled_only else "")
    return _fetch(con, sql + " ORDER BY lower(c.name), c.community_id")


def get_community(con, community_id: int) -> dict[str, Any] | None:
    rows = _fetch(con, _SELECT + " WHERE c.community_id = %s", (community_id,))
    return rows[0] if rows else None


def _validated(con, fields: dict[str, Any]) -> dict[str, Any]:
    """Every field checked before anything is written, ids included."""
    data = {
        "name": clean_line(fields.get("name"), what="이름", max_len=NAME_MAX, required=True),
        "region_id": parse_id(fields.get("region_id"), what="지역"),
        "description": clean_text(fields.get("description"), what="소개",
                                  max_len=DESCRIPTION_MAX),
        "homepage_url": clean_url(fields.get("homepage_url")),
        "notes": clean_text(fields.get("notes"), what="운영 메모", max_len=NOTES_MAX),
        "enabled": as_bool(fields.get("enabled", True)),
        "genre_ids": sorted(parse_ids(fields.get("genre_ids"), what="장르")),
        "venue_ids": sorted(parse_ids(fields.get("venue_ids"), what="장소")),
    }
    if data["region_id"] is not None:
        require_existing(con, "regions", [data["region_id"]], what="지역")
    require_existing(con, "genres", data["genre_ids"], what="장르")
    require_existing(con, "venues", data["venue_ids"], what="장소")
    return data


def _name_taken(con, name: str, exclude_id: int | None = None) -> bool:
    with con.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM communities WHERE lower(btrim(name)) = lower(btrim(%s)) "
            "AND community_id <> %s",
            (name, exclude_id if exclude_id is not None else -1),
        )
        return cur.fetchone() is not None


def _set_links(con, community_id: int, genre_ids: list[int], venue_ids: list[int]) -> None:
    with con.cursor() as cur:
        cur.execute("DELETE FROM community_genres WHERE community_id = %s", (community_id,))
        cur.execute("DELETE FROM community_venues WHERE community_id = %s", (community_id,))
        for genre_id in genre_ids:
            cur.execute("INSERT INTO community_genres (community_id, genre_id) "
                        "VALUES (%s, %s)", (community_id, genre_id))
        for venue_id in venue_ids:
            cur.execute("INSERT INTO community_venues (community_id, venue_id) "
                        "VALUES (%s, %s)", (community_id, venue_id))


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """A row in the shape ``_validated()`` returns, so the two compare field by field."""
    return {
        "name": row["name"], "region_id": row["region_id"],
        "description": row["description"], "homepage_url": row["homepage_url"],
        "notes": row["notes"], "enabled": bool(row["enabled"]),
        "genre_ids": sorted(row.get("genre_ids") or []),
        "venue_ids": sorted(row.get("venue_ids") or []),
    }


def _require(con, community_id: int) -> dict[str, Any]:
    row = get_community(con, community_id)
    if row is None:
        raise DirectoryError(f"동호회 {community_id}을(를) 찾을 수 없습니다")
    return row


def create_community(con, fields: dict[str, Any], *, reviewer: str = "admin") -> dict[str, Any]:
    data = _validated(con, fields)
    if _name_taken(con, data["name"]):
        raise DirectoryError(f"같은 이름의 동호회가 이미 있습니다: {data['name']}")
    with con.transaction():
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO communities (name, region_id, description, homepage_url, "
                "  notes, enabled) VALUES (%s, %s, %s, %s, %s, %s) RETURNING community_id",
                (data["name"], data["region_id"], data["description"],
                 data["homepage_url"], data["notes"], data["enabled"]),
            )
            community_id = cur.fetchone()[0]
        _set_links(con, community_id, data["genre_ids"], data["venue_ids"])
        master_edit.record(
            con, entity_type=master_edit.COMMUNITY, entity_id=community_id,
            action=master_edit.CREATE, reviewer=reviewer, entity_name=data["name"],
            after=data, detail="created community",
        )
    return get_community(con, community_id)


def update_community(con, community_id: int, fields: dict[str, Any], *,
                     reviewer: str = "admin") -> dict[str, Any]:
    """Replace every field and both link sets; record only what changed."""
    before = _require(con, community_id)
    data = _validated(con, fields)
    if _name_taken(con, data["name"], community_id):
        raise DirectoryError(f"같은 이름의 동호회가 이미 있습니다: {data['name']}")
    old = snapshot(before)
    changed = [key for key in FIELDS if old[key] != data[key]]
    if not changed:
        return {"community": before, "changed": []}
    with con.transaction():
        with con.cursor() as cur:
            cur.execute(
                "UPDATE communities SET name = %s, region_id = %s, description = %s, "
                "  homepage_url = %s, notes = %s, enabled = %s, updated_at = now() "
                "WHERE community_id = %s",
                (data["name"], data["region_id"], data["description"],
                 data["homepage_url"], data["notes"], data["enabled"], community_id),
            )
        _set_links(con, community_id, data["genre_ids"], data["venue_ids"])
        master_edit.record(
            con, entity_type=master_edit.COMMUNITY, entity_id=community_id,
            action=master_edit.EDIT, reviewer=reviewer, entity_name=data["name"],
            before={k: old[k] for k in changed}, after={k: data[k] for k in changed},
        )
    return {"community": get_community(con, community_id), "changed": changed}


def set_community_enabled(con, community_id: int, enabled: bool, *,
                          reviewer: str = "admin") -> dict[str, Any]:
    before = _require(con, community_id)
    if bool(before["enabled"]) == bool(enabled):
        return {"community": before, "changed": False}
    with con.transaction():
        with con.cursor() as cur:
            cur.execute("UPDATE communities SET enabled = %s, updated_at = now() "
                        "WHERE community_id = %s", (bool(enabled), community_id))
        master_edit.record(
            con, entity_type=master_edit.COMMUNITY, entity_id=community_id,
            action=master_edit.ENABLE if enabled else master_edit.DISABLE,
            reviewer=reviewer, entity_name=before["name"],
            before={"enabled": bool(before["enabled"])}, after={"enabled": bool(enabled)},
        )
    return {"community": get_community(con, community_id), "changed": True}


def delete_community(con, community_id: int, *, reviewer: str = "admin") -> dict[str, Any]:
    """Only a disabled community, and only its own row and links."""
    before = _require(con, community_id)
    if before["enabled"]:
        raise DirectoryError(
            f"{before['name']}은(는) 활성 상태라 삭제할 수 없습니다 - 먼저 비활성화하세요")
    with con.transaction():
        with con.cursor() as cur:
            cur.execute("DELETE FROM communities WHERE community_id = %s", (community_id,))
        master_edit.record(
            con, entity_type=master_edit.COMMUNITY, entity_id=community_id,
            action=master_edit.DELETE, reviewer=reviewer, entity_name=before["name"],
            before=snapshot(before), detail="deleted community (links removed with it)",
        )
    return {"community": before}
