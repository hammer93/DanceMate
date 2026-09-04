"""Editing master data from the console, safely and on the record.

Every entity the operator registers -- a genre, a region, a venue, an
organizer, a source -- eventually needs correcting, and until now correcting
one meant editing the database by hand. This is the layer that lets the console
do it without becoming a way to break things quietly.

Four rules hold across all five entities:

    **Identity is not editable.** A rename keeps the same id, so the events,
    sources and filters pointing at a row keep pointing at it. Codes -- TANGO,
    KR-SEOUL -- are how everything else refers to a row, so they are read-only
    rather than merely discouraged.

    **A rejected edit is a message, not a 500.** Validation failures come back
    as text an operator can act on.

    **Nothing changes silently.** Only fields that actually differ are written,
    and what differed is recorded with who changed it.

    **Editing is not deleting.** The safe-delete rules from v0.77.2 are
    untouched; nothing here removes a row.
"""

from __future__ import annotations

import json
from typing import Any

from . import master_data, sources

GENRE = "GENRE"
REGION = "REGION"
VENUE = "VENUE"
ORGANIZER = "ORGANIZER"
SOURCE = "SOURCE"

ENTITIES = (GENRE, REGION, VENUE, ORGANIZER, SOURCE)

EDIT = "EDIT"
ENABLE = "ENABLE"
DISABLE = "DISABLE"
ALIAS_ADD = "ALIAS_ADD"
ALIAS_REMOVE = "ALIAS_REMOVE"

# Fields the console may change, per entity. A code is absent from every list
# on purpose: see the module docstring.
EDITABLE = {
    GENRE: ("name", "enabled"),
    REGION: ("name", "country", "city", "district", "enabled"),
    VENUE: ("name", "region_id", "address", "notes", "enabled"),
    ORGANIZER: ("name", "genre_id", "region_id", "contact_url", "notes", "enabled"),
    SOURCE: ("name", "platform", "source_role", "url", "genre_id", "region_id",
             "authority_level", "collection_interval_minutes", "notes", "enabled"),
}

# Never rendered into a form and never accepted from one. Provider credentials
# live in .env and nowhere else; a console that can show them is a console that
# can leak them.
NEVER_EDITABLE = ("source_key", "code", "config", "created_at",
                  "last_collected_at", "last_status", "last_detail")


class EditError(ValueError):
    """The edit cannot be applied as asked. The message is for an operator."""


def _getter(entity_type: str):
    return {
        GENRE: master_data.get_genre,
        REGION: master_data.get_region,
        VENUE: master_data.get_venue,
        ORGANIZER: master_data.get_organizer,
        SOURCE: sources.get_source,
    }[entity_type]


def _updater(entity_type: str):
    return {
        GENRE: master_data.update_genre,
        REGION: master_data.update_region,
        VENUE: master_data.update_venue,
        ORGANIZER: master_data.update_organizer,
        SOURCE: sources.update_source,
    }[entity_type]


def _id_field(entity_type: str) -> str:
    return {
        GENRE: "genre_id", REGION: "region_id", VENUE: "venue_id",
        ORGANIZER: "organizer_id", SOURCE: "source_id",
    }[entity_type]


def _name_of(row: dict[str, Any]) -> str | None:
    return row.get("name")


def changed_fields(before: dict[str, Any], wanted: dict[str, Any],
                   editable: tuple[str, ...]) -> dict[str, Any]:
    """The subset of ``wanted`` that is both allowed and actually different.

    Comparing first means an operator who opens a form and saves it unchanged
    writes nothing and records nothing, which keeps the audit trail worth
    reading.
    """
    changes: dict[str, Any] = {}
    for field in editable:
        if field not in wanted:
            continue
        new = wanted[field]
        old = before.get(field)
        if isinstance(new, str):
            new = new.strip() or None
        if isinstance(old, str):
            old = old.strip() or None
        if new != old:
            changes[field] = wanted[field]
    return changes


def record(con, *, entity_type: str, entity_id: int, action: str, reviewer: str,
           entity_name: str | None = None, before: dict[str, Any] | None = None,
           after: dict[str, Any] | None = None,
           detail: str | None = None) -> dict[str, Any]:
    """Write one master-data change to the audit trail."""
    if entity_type not in ENTITIES:
        raise EditError(f"unknown entity {entity_type!r}")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO master_data_actions (entity_type, entity_id, entity_name, "
            "  action, reviewer, before_json, after_json, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) RETURNING *",
            (entity_type, entity_id, entity_name, action, reviewer,
             json.dumps(before or {}, ensure_ascii=False, default=str),
             json.dumps(after or {}, ensure_ascii=False, default=str), detail),
        )
        names = [c.name for c in cur.description]
        return dict(zip(names, cur.fetchone()))


def apply_edit(con, entity_type: str, entity_id: int, wanted: dict[str, Any], *,
               reviewer: str = "admin", action: str = EDIT) -> dict[str, Any]:
    """Apply an edit to one master row, keeping its identity and its relations.

    The row's id never changes, so events, sources and filters pointing at it
    keep pointing at it -- renaming 라 벤따나 to La Ventana leaves both of its
    events exactly where they were.
    """
    if entity_type not in ENTITIES:
        raise EditError(f"unknown entity {entity_type!r}")
    before = _getter(entity_type)(con, entity_id)
    if before is None:
        raise EditError(f"no {entity_type.lower()} {entity_id}")

    rejected = [f for f in wanted if f in NEVER_EDITABLE]
    if rejected:
        raise EditError(
            f"{', '.join(rejected)} cannot be changed here — it is how other "
            "records refer to this one"
        )

    changes = changed_fields(before, wanted, EDITABLE[entity_type])
    if not changes:
        return {"entity": before, "changed": {}, "action": None}

    with con.transaction():
        try:
            after = _updater(entity_type)(con, entity_id, **changes)
        except sources.SourceValidationError as exc:
            raise EditError(str(exc)) from None
        except ValueError as exc:
            raise EditError(str(exc)) from None
        except Exception as exc:  # a unique index, a bad foreign key
            raise EditError(_readable(exc)) from None
        if after is None:
            raise EditError(f"no {entity_type.lower()} {entity_id}")

        recorded = record(
            con, entity_type=entity_type, entity_id=entity_id, action=action,
            reviewer=reviewer, entity_name=_name_of(after),
            before={k: before.get(k) for k in changes},
            after={k: after.get(k) for k in changes},
        )
    return {"entity": after, "changed": changes, "action": recorded}


def _readable(exc: Exception) -> str:
    """Turn a database error into something an operator can act on."""
    text = str(exc)
    if "venues_region_name_key" in text:
        return "그 지역에 같은 이름의 장소가 이미 있습니다"
    if "organizers_name_region_key" in text:
        return "그 지역에 같은 이름의 주최자가 이미 있습니다"
    if "genres_code_key" in text or "regions_code_key" in text:
        return "그 code는 이미 사용 중입니다"
    if "sources_source_key" in text:
        return "그 source key는 이미 사용 중입니다"
    if "violates foreign key" in text:
        return "선택한 지역 또는 장르가 존재하지 않습니다"
    return text.strip().splitlines()[0]


def set_enabled(con, entity_type: str, entity_id: int, enabled: bool, *,
                reviewer: str = "admin") -> dict[str, Any]:
    """Turn a master row on or off. Nothing is unlinked and nothing is deleted.

    Recorded as ENABLE or DISABLE rather than as an edit that happened to touch
    the enabled column, so "who turned this off" is one query.
    """
    return apply_edit(
        con, entity_type, entity_id, {"enabled": enabled},
        reviewer=reviewer, action=ENABLE if enabled else DISABLE,
    )


# --- venue aliases ----------------------------------------------------------

def add_alias(con, venue_id: int, alias: str, *,
              reviewer: str = "admin") -> dict[str, Any]:
    """Teach a venue one more spelling."""
    venue = master_data.get_venue(con, venue_id)
    if venue is None:
        raise EditError(f"no venue {venue_id}")
    alias = (alias or "").strip()
    if not alias:
        raise EditError("alias cannot be empty")
    with con.transaction():
        try:
            created = master_data.add_venue_alias(con, venue_id, alias)
        except ValueError as exc:
            raise EditError(str(exc)) from None
        except Exception:
            raise EditError(
                f"'{alias}' 는 이미 다른 장소의 alias 입니다"
            ) from None
        record(
            con, entity_type=VENUE, entity_id=venue_id, action=ALIAS_ADD,
            reviewer=reviewer, entity_name=venue["name"],
            after={"alias": alias}, detail=f"added alias {alias}",
        )
    return {"alias": created, "venue": venue}


def remove_alias(con, venue_alias_id: int, *, reviewer: str = "admin",
                 force: bool = False) -> dict[str, Any]:
    """Drop one spelling.

    An alias that events currently reach the venue through is doing work:
    removing it means the next collection stops recognising that spelling and
    the string goes back to the unresolved queue. That may be exactly what the
    operator wants, so it is a question, not a refusal.
    """
    alias = master_data.get_venue_alias(con, venue_alias_id)
    if alias is None:
        raise EditError(f"no alias {venue_alias_id}")
    venue = master_data.get_venue(con, alias["venue_id"])
    in_use = master_data.venue_alias_usage(con, alias["venue_id"]).get(venue_alias_id, 0)
    if in_use and not force:
        raise EditError(
            f"'{alias['alias']}' 로 연결된 Event가 {in_use}건 있습니다 — "
            "확인 후 다시 시도하세요"
        )
    with con.transaction():
        master_data.remove_venue_alias(con, venue_alias_id)
        record(
            con, entity_type=VENUE, entity_id=alias["venue_id"], action=ALIAS_REMOVE,
            reviewer=reviewer, entity_name=venue["name"] if venue else None,
            before={"alias": alias["alias"]}, detail=f"removed alias {alias['alias']}",
        )
    return {"alias": alias, "events_affected": in_use}


def history(con, *, entity_type: str | None = None, entity_id: int | None = None,
            limit: int = 50) -> list[dict[str, Any]]:
    where, params = [], []
    if entity_type:
        where.append("entity_type = %s")
        params.append(entity_type)
    if entity_id is not None:
        where.append("entity_id = %s")
        params.append(entity_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with con.cursor() as cur:
        cur.execute(
            f"SELECT * FROM master_data_actions {clause} "
            "ORDER BY master_action_id DESC LIMIT %s",
            (*params, limit),
        )
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def region_conflict(con, address: str | None, region_id: int | None) -> str | None:
    """A warning when the address names one region and the form selects another.

    Reported, never applied. An operator may well know that a venue's postal
    address and the region it belongs to differ, and silently overwriting their
    choice would make the region filter wrong in a way nobody could see.
    """
    if not address or region_id is None:
        return None
    from . import venue_resolution  # local: this module is imported by it

    head = venue_resolution._ADMIN_HEAD_RE.match(address.strip())
    if not head:
        return None
    suggested = venue_resolution.suggested_region_id(con, head.group(1))
    if suggested is None or suggested == region_id:
        return None
    chosen = master_data.get_region(con, region_id)
    named = master_data.get_region(con, suggested)
    return (
        f"주소는 {head.group(1)}({named['name'] if named else suggested})를 가리키는데 "
        f"지역은 {chosen['name'] if chosen else region_id}로 선택되어 있습니다. "
        "의도한 것이면 그대로 저장하세요."
    )
