"""Turning a venue string somebody wrote into a venue somebody stands behind.

The extractor reads `장소: 라 벤따나 (서울 마포구 잔다리로 48, 2층)` off a post and
stops there, because deciding that string names a real place is a judgement.
This module is the machinery behind that judgement -- everything except the
judgement itself.

Three things an operator needs before they can decide, and one after:

    what the post actually said       context()
    whether we already know the place  similar_venues()
    a sensible starting form           suggest()
    all of it applied at once          create_and_link()

`create_and_link` is one transaction on purpose. Creating the venue and then
failing to link it leaves a master record nobody asked for and a queue entry
that still looks untouched -- the operator would reasonably create it again.

Nothing here decides anything on its own. There is no rule that promotes a
string to a venue, and no threshold above which one is created automatically.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from . import master_data, normalization

CREATE_AND_LINK = "CREATE_AND_LINK"
LINK_EXISTING = "LINK_EXISTING"
NOT_A_VENUE = "NOT_A_VENUE"

ACTIONS = (CREATE_AND_LINK, LINK_EXISTING, NOT_A_VENUE)

# How much of the post to show around the venue string. Enough to tell
# "장소: OCHO" from "일루미밀롱가 @ OCHO", not enough to paste the article into
# a table cell.
CONTEXT_BEFORE = 40
CONTEXT_AFTER = 60

# Korea's first-level administrative names, as they appear at the start of an
# address. Used to recognise an address, never to invent one.
_ADMIN = (
    "서울특별시|서울|부산광역시|부산|대구광역시|대구|인천광역시|인천|"
    "광주광역시|광주|대전광역시|대전|울산광역시|울산|세종특별자치시|세종|"
    "경기도|경기|강원특별자치도|강원도|강원|충청북도|충북|충청남도|충남|"
    "전라북도|전북|전라남도|전남|경상북도|경북|경상남도|경남|"
    "제주특별자치도|제주"
)
_ADDRESS_START_RE = re.compile(rf"^\s*(?:{_ADMIN})\b")
# A road-name or lot-number address without its province: "마포구 잔다리로 48".
_ROAD_RE = re.compile(r"(?:[가-힣A-Za-z0-9]+(?:로|길|가|동|읍|면|리))\s*\d")
_ADMIN_HEAD_RE = re.compile(rf"^\s*({_ADMIN})")

_PARENTHETICAL_RE = re.compile(r"^(?P<head>[^(（]*)[(（](?P<inner>[^)）]*)[)）]\s*$")


class DuplicateVenue(Exception):
    """A venue that may already exist. Carries the candidates, not a verdict."""

    def __init__(self, matches: list[dict[str, Any]]):
        super().__init__("a similar venue is already registered")
        self.matches = matches


def looks_like_an_address(text: str) -> bool:
    """True when this reads as a postal address rather than a name.

    Deliberately narrow: an administrative name at the front, or a road with a
    number on it. "EnPaz Tango Studio" is neither, and putting it in the
    address field would be worse than leaving the field empty.
    """
    value = (text or "").strip()
    if not value:
        return False
    return bool(_ADDRESS_START_RE.search(value) or _ROAD_RE.search(value))


def suggest(raw_venue: str, alias_candidates: list[str] | None = None) -> dict[str, Any]:
    """A starting point for the New Venue form. Every field stays editable.

    ``라 벤따나 (서울 마포구 잔다리로 48, 2층)`` splits into a name and an address
    because the bracket contains an address. ``엔빠스(EnPaz Tango Studio)`` does
    not: the bracket is another name for the same place, so it becomes an alias
    and the address stays empty rather than being filled with a guess.

    The raw string is always among the aliases -- resolving it next time is the
    entire reason the operator is here.
    """
    raw = (raw_venue or "").strip()
    name, address = raw, None
    aliases: list[str] = []

    match = _PARENTHETICAL_RE.match(raw)
    if match:
        head = match.group("head").strip()
        inner = match.group("inner").strip()
        if head and looks_like_an_address(inner):
            name, address = head, inner
        elif head and inner:
            name = head
            aliases.append(inner)

    for extra in [raw] + list(alias_candidates or []):
        extra = (extra or "").strip()
        if extra and extra not in aliases and extra != name:
            aliases.append(extra)

    return {
        "name": name,
        "address": address,
        "aliases": aliases,
        "region_hint": _ADMIN_HEAD_RE.match(address).group(1) if address and
                       _ADMIN_HEAD_RE.match(address) else None,
        # True when the split was inferred rather than read off a label. The
        # form says so, so nobody assumes it was verified.
        "split_inferred": bool(match) and name != raw,
    }


# Addresses are written in Korean and the region master is seeded in English,
# so the two need an explicit bridge. A lookup table rather than a
# transliteration: 서울 is Seoul because that is what the seed calls it, not
# because a rule derived it.
_REGION_BY_ADMIN = {
    "서울": ("KR-SEOUL", "Seoul"), "부산": ("KR-BUSAN", "Busan"),
    "대구": ("KR-DAEGU", "Daegu"), "인천": ("KR-INCHEON", "Incheon"),
    "광주": ("KR-GWANGJU", "Gwangju"), "대전": ("KR-DAEJEON", "Daejeon"),
    "울산": ("KR-ULSAN", "Ulsan"), "세종": ("KR-SEJONG", "Sejong"),
    "경기": ("KR-GYEONGGI", "Gyeonggi"), "강원": ("KR-GANGWON", "Gangwon"),
    "충북": ("KR-CHUNGBUK", "Chungbuk"), "충남": ("KR-CHUNGNAM", "Chungnam"),
    "전북": ("KR-JEONBUK", "Jeonbuk"), "전남": ("KR-JEONNAM", "Jeonnam"),
    "경북": ("KR-GYEONGBUK", "Gyeongbuk"), "경남": ("KR-GYEONGNAM", "Gyeongnam"),
    "제주": ("KR-JEJU", "Jeju"),
}


def suggested_region_id(con, region_hint: str | None) -> int | None:
    """The registered region an address names, if one is registered.

    No hint, or a region nobody has registered, means no selection. Defaulting
    every venue to Seoul because most of them are would quietly file a Busan
    milonga under Seoul, and the region filter would then lie to a dancer in
    either city.
    """
    if not region_hint:
        return None
    mapped = _REGION_BY_ADMIN.get(region_hint[:2])
    if mapped is None:
        return None
    code, english = mapped
    for region in master_data.list_regions(con):
        if region.get("code") == code:
            return region["region_id"]
        if (region.get("city") or "").lower() == english.lower():
            return region["region_id"]
    return None


def _normalized_address(value: str | None) -> str:
    folded = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"[\s,.\-]+", "", folded)


def similar_venues(con, *, name: str, address: str | None = None,
                   raw_venue: str | None = None) -> list[dict[str, Any]]:
    """Venues this might already be, with the reason each one matched.

    Exact matches only -- normalised name, a registered alias, or the same
    address. No fuzzy scoring: a warning an operator cannot check is a warning
    they learn to click past.
    """
    wanted: dict[str, list[str]] = {}
    for value, label in ((name, "name"), (raw_venue or "", "raw string")):
        key = master_data.normalize_alias(value)
        if key:
            # The name and the raw string are often identical. That is one
            # match for two reasons, not one reason overwriting the other.
            wanted.setdefault(key, []).append(label)
    address_key = _normalized_address(address)

    found: dict[int, dict[str, Any]] = {}
    for venue in master_data.list_venues(con):
        reasons = []
        for label in wanted.get(master_data.normalize_alias(venue["name"]), []):
            reasons.append(f"same {label}")
        for alias in venue.get("aliases") or []:
            if master_data.normalize_alias(alias) in wanted:
                reasons.append(f"registered alias {alias!r}")
                break
        if address_key and _normalized_address(venue.get("address")) == address_key:
            reasons.append("same address")
        if reasons:
            entry = dict(venue)
            entry["match_reasons"] = reasons
            found[venue["venue_id"]] = entry
    return list(found.values())


def record_action(con, *, action: str, raw_venue: str, reviewer: str,
                  unresolved_venue_id: int | None = None, venue_id: int | None = None,
                  events_updated: int = 0, before: dict[str, Any] | None = None,
                  after: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write one venue decision to the audit trail."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {', '.join(ACTIONS)}")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO venue_resolution_actions (unresolved_venue_id, raw_venue, "
            "  action, venue_id, reviewer, events_updated, before_json, after_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING *",
            (unresolved_venue_id, raw_venue, action, venue_id, reviewer, events_updated,
             json.dumps(before or {}, ensure_ascii=False, default=str),
             json.dumps(after or {}, ensure_ascii=False, default=str)),
        )
        names = [c.name for c in cur.description]
        return dict(zip(names, cur.fetchone()))


def history(con, *, limit: int = 50) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT a.*, v.name AS venue_name FROM venue_resolution_actions a "
            "LEFT JOIN venues v ON v.venue_id = a.venue_id "
            "ORDER BY a.venue_action_id DESC LIMIT %s",
            (limit,),
        )
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


# --- what the post actually said --------------------------------------------

def _snippet(body: str | None, needle: str) -> str | None:
    """A short window of the post around the venue string.

    Enough to tell `장소: OCHO` from `일루미밀롱가 @ OCHO`, which is exactly the
    question an operator is here to answer. Not enough to paste an article into
    a table cell.
    """
    if not body or not needle:
        return None
    haystack = body.lower()
    at = haystack.find(needle.lower())
    if at < 0:
        # The stored venue was trimmed out of a longer line; fall back to its
        # first word so a partial match still lands near the right place.
        head = needle.split()[0].lower() if needle.split() else ""
        at = haystack.find(head) if head else -1
        if at < 0:
            return None
    start = max(0, at - CONTEXT_BEFORE)
    end = min(len(body), at + len(needle) + CONTEXT_AFTER)
    text = re.sub(r"\s+", " ", body[start:end]).strip()
    return ("… " if start else "") + text + (" …" if end < len(body) else "")


def context(con, venue_text: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """The events waiting on this string, each with its post and a snippet.

    Answers the question the queue cannot: is OCHO a venue, or the name of the
    event? Only a person reading the post can tell, so this puts the post in
    front of them.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT e.event_id, e.event_name, e.event_date, e.source_url, "
            "       e.source_item_id, c.extracted_text "
            "FROM events e "
            "LEFT JOIN source_item_content c ON c.source_item_id = e.source_item_id "
            "WHERE e.venue_status = 'UNRESOLVED' AND lower(e.venue_text) = lower(%s) "
            "ORDER BY e.event_date DESC, e.event_id LIMIT %s",
            (venue_text, limit),
        )
        names = [c.name for c in cur.description]
        rows = [dict(zip(names, row)) for row in cur.fetchall()]

    for row in rows:
        row["snippet"] = _snippet(row.pop("extracted_text", None), venue_text)
    return rows


# --- the decisions ----------------------------------------------------------

def create_and_link(con, *, unresolved_venue_id: int, name: str,
                    region_id: int | None = None, address: str | None = None,
                    notes: str | None = None, aliases: list[str] | None = None,
                    reviewer: str = "admin", force: bool = False) -> dict[str, Any]:
    """Create the venue, alias the raw string to it, and resolve what was waiting.

    One transaction. Creating the venue and then failing to link it would leave
    a master record nobody asked for beside a queue entry that still looks
    untouched -- and the operator would reasonably create it again.

    The three writes run inside one ``con.transaction()`` block, which is a real
    transaction on an autocommit connection and a savepoint inside a larger one.
    Either way they land together or not at all. Committing is the caller's --
    a module that rolls back a connection it was handed would discard whatever
    else the caller had in flight.

    Raises DuplicateVenue when the venue may already exist. That is a question
    for the operator, not a refusal -- pass force=True once they have answered it.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("venue name is required")

    entry = normalization.unresolved_venue(con, unresolved_venue_id)
    if entry is None:
        raise LookupError(f"no unresolved venue {unresolved_venue_id}")
    raw_venue = entry["venue_text"]

    if not force:
        # Read-only, and nothing has been written yet: this raises without
        # touching the transaction.
        matches = similar_venues(con, name=name, address=address, raw_venue=raw_venue)
        if matches:
            raise DuplicateVenue(matches)

    with con.transaction():
        venue = master_data.create_venue(
            con, name=name, region_id=region_id,
            address=(address or "").strip() or None,
            notes=(notes or "").strip() or None,
            aliases=[a for a in (aliases or []) if a and a.strip()],
        )
        # The raw string is the whole point: it has to resolve next time.
        master_data.add_venue_alias(con, venue["venue_id"], raw_venue, ignore_conflict=True)
        linked = normalization.link_unresolved_venue(
            con, unresolved_venue_id, venue["venue_id"], reviewer=reviewer,
            add_alias=False,
        )
        recorded = record_action(
            con, action=CREATE_AND_LINK, raw_venue=raw_venue, reviewer=reviewer,
            unresolved_venue_id=unresolved_venue_id, venue_id=venue["venue_id"],
            events_updated=linked["events_updated"],
            before={"venue_text": raw_venue, "venue_id": None, "state": entry["state"]},
            after={"venue_id": venue["venue_id"], "name": venue["name"],
                   "address": venue.get("address"), "region_id": region_id},
        )

    return {
        "venue": venue,
        "events_updated": linked["events_updated"],
        "action": recorded,
    }


def link_existing(con, *, unresolved_venue_id: int, venue_id: int,
                  reviewer: str = "admin") -> dict[str, Any]:
    """A person says this string is that venue. Same transaction discipline."""
    entry = normalization.unresolved_venue(con, unresolved_venue_id)
    if entry is None:
        raise LookupError(f"no unresolved venue {unresolved_venue_id}")
    venue = master_data.get_venue(con, venue_id)
    if venue is None:
        raise LookupError(f"no venue {venue_id}")

    with con.transaction():
        linked = normalization.link_unresolved_venue(
            con, unresolved_venue_id, venue_id, reviewer=reviewer,
        )
        recorded = record_action(
            con, action=LINK_EXISTING, raw_venue=entry["venue_text"], reviewer=reviewer,
            unresolved_venue_id=unresolved_venue_id, venue_id=venue_id,
            events_updated=linked["events_updated"],
            before={"venue_text": entry["venue_text"], "venue_id": None,
                    "state": entry["state"]},
            after={"venue_id": venue_id, "name": venue["name"]},
        )

    return {"venue": venue, "events_updated": linked["events_updated"], "action": recorded}


def dismiss(con, *, unresolved_venue_id: int, reviewer: str = "admin",
            reason: str | None = None) -> dict[str, Any]:
    """Not a venue: a room number, a landmark, an event name, a misread line.

    The queue entry is marked, not deleted, and neither the events nor the posts
    it came from are touched. The string stops being asked about; the evidence
    that produced it stays exactly where it was.
    """
    entry = normalization.unresolved_venue(con, unresolved_venue_id)
    if entry is None:
        raise LookupError(f"no unresolved venue {unresolved_venue_id}")
    with con.transaction():
        normalization.dismiss_unresolved_venue(con, unresolved_venue_id, reviewer=reviewer)
        recorded = record_action(
            con, action=NOT_A_VENUE, raw_venue=entry["venue_text"], reviewer=reviewer,
            unresolved_venue_id=unresolved_venue_id,
            before={"venue_text": entry["venue_text"], "state": entry["state"]},
            after={"state": "DISMISSED", "reason": reason},
        )
    return {"action": recorded}
