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

v0.96.37 put a preview in front of every decision (preview_link(),
preview_create(), preview_group(), preview_revert()) and made the decision
itself carry that preview's token, so what is written is exactly what the
operator was shown - or nothing at all.

`create_and_link` is one transaction on purpose. Creating the venue and then
failing to link it leaves a master record nobody asked for and a queue entry
that still looks untouched -- the operator would reasonably create it again.

Nothing here decides anything on its own. There is no rule that promotes a
string to a venue, and no threshold above which one is created automatically.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import unicodedata
from typing import Any

from . import master_data, normalization, venue_identity

CREATE_AND_LINK = "CREATE_AND_LINK"
LINK_EXISTING = "LINK_EXISTING"
NOT_A_VENUE = "NOT_A_VENUE"
# v0.96.37: a person takes back a LINK_EXISTING, CREATE_AND_LINK or
# NOT_A_VENUE decision. The decision's own row stays; this one says it was
# undone, by whom, and what it put back.
DECISION_REVERT = "DECISION_REVERT"

# Removing a venue: nothing referenced it, or the events go back to the raw
# string they were read from, or it stays and comes out of circulation.
VENUE_DELETE = "VENUE_DELETE"
VENUE_UNLINK_DELETE = "VENUE_UNLINK_DELETE"
VENUE_DEACTIVATE = "VENUE_DEACTIVATE"
VENUE_REACTIVATE = "VENUE_REACTIVATE"

RESOLUTION_ACTIONS = (CREATE_AND_LINK, LINK_EXISTING, NOT_A_VENUE)
REMOVAL_ACTIONS = (VENUE_DELETE, VENUE_UNLINK_DELETE, VENUE_DEACTIVATE, VENUE_REACTIVATE)
CORRECTION_ACTIONS = (DECISION_REVERT,)
ACTIONS = RESOLUTION_ACTIONS + REMOVAL_ACTIONS + CORRECTION_ACTIONS

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


# Gwangju Metropolitan City's own five gu - the only safe way to tell it apart
# from Gyeonggi-do's unrelated 광주시 (Gwangju-si), which has no gu-level
# districts at all (it sits directly under 읍/면/동). "광주" alone, or a bare
# "광주시", is genuinely ambiguous between the two and must never be guessed
# (v0.83.2 Section 14) - only an explicit "광주광역시", or "광주" immediately
# naming one of these five, is real evidence of the metro city.
_GWANGJU_METRO_GU = ("동구", "서구", "남구", "북구", "광산구")


class DuplicateVenue(Exception):
    """A venue that may already exist. Carries the candidates, not a verdict."""

    def __init__(self, matches: list[dict[str, Any]]):
        super().__init__("a similar venue is already registered")
        self.matches = matches


class DecisionRefused(Exception):
    """A decision the current state does not allow. Nothing was written.

    Unlike DuplicateVenue this is not a question: a queue entry somebody has
    already decided, a venue in a city the post's own words exclude, a spelling
    another venue already owns. Carries every reason, not just the first.
    """

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = list(reasons)


class StalePreview(DecisionRefused):
    """What would be written is no longer what the operator was shown."""


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

    head, groups = _trailing_groups(raw)
    split = bool(head) and bool(groups)
    if split:
        name = head
        # v0.96.37: a provider writes `Name (한글 이름) (주소)` - two brackets,
        # one of them an address that may hold a bracket of its own
        # (`(창원시 ... 24-2 (창동) 2층)`). Exactly one address-shaped bracket
        # is an address; two are a question the operator answers, so neither
        # is filled in. Every other bracket is another name for the place.
        addresses = [g for g in groups if looks_like_an_address(g)]
        if len(addresses) == 1:
            address = addresses[0]
        aliases.extend(g for g in groups if g not in addresses)

    for extra in [raw] + list(alias_candidates or []):
        extra = (extra or "").strip()
        # v0.96.37: the engine offers the bare address among its readings
        # (`서울시 서초구 방배천로 60 청도빌딩 B1F`). An address is the address
        # field's, not a spelling of the venue: as an alias it would answer for
        # every other room in the building. The raw string always stays.
        if extra != raw and looks_like_an_address(extra):
            continue
        if extra and extra not in aliases and extra != name:
            aliases.append(extra)

    return {
        "name": name,
        "address": address,
        "aliases": aliases,
        "region_hint": _safe_admin_head(address),
        # True when the split was inferred rather than read off a label. The
        # form says so, so nobody assumes it was verified.
        "split_inferred": split and name != raw,
    }


def _trailing_groups(raw: str) -> tuple[str, list[str]]:
    """The text before the brackets a string ends with, and each bracket's
    contents in order - nested brackets kept whole.

    `라 벤따나 (서울 마포구 잔다리로 48, 2층)` is one group; `Tango Pasion (탱고
    빠시온) (서울 마포구 월드컵북로6길 69 B1)` is two. A string whose brackets
    do not balance, or that has nothing before them, is not split at all.
    """
    rest = raw.rstrip()
    groups: list[str] = []
    while rest.endswith((")", "）")):
        depth = 0
        for at in range(len(rest) - 1, -1, -1):
            if rest[at] in ")）":
                depth += 1
            elif rest[at] in "(（":
                depth -= 1
                if depth == 0:
                    break
        else:
            return "", []
        if depth != 0:
            return "", []
        inner = rest[at + 1:-1].strip()
        if inner:
            groups.insert(0, inner)
        rest = rest[:at].rstrip()
    return rest.strip(), groups


def _safe_admin_head(address: str | None) -> str | None:
    """`_ADMIN_HEAD_RE`'s leading province/metro name, except a bare "광주"
    match is only trusted when the address itself backs it: an explicit
    "광주광역시", or "광주" immediately followed by one of the metro's own
    five gu. Anything else that starts with "광주" (a bare "광주시 ...", or
    "광주 <dong>..." with no gu at all) could just as easily be Gyeonggi-do's
    Gwangju-si, so it is left unresolved rather than guessed."""
    if not address:
        return None
    match = _ADMIN_HEAD_RE.match(address)
    if not match:
        return None
    head = match.group(1)
    if head != "광주":
        return head
    rest = address[match.end():].lstrip()
    if any(rest.startswith(gu) for gu in _GWANGJU_METRO_GU):
        return head
    return None


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


_PROVINCE_SHORT = {
    "경상남도": "경남", "경상북도": "경북", "충청남도": "충남", "충청북도": "충북",
    "전라남도": "전남", "전라북도": "전북",
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
    # v0.96.37: the full name of a province is not its first two syllables -
    # 경상남도 is 경남, not "경상" - so `경상남도 창원시 ...` selected nothing.
    mapped = _REGION_BY_ADMIN.get(_PROVINCE_SHORT.get(region_hint, region_hint[:2]))
    if mapped is None:
        return None
    code, english = mapped
    for region in master_data.list_regions(con):
        if region.get("code") == code:
            return region["region_id"]
        if (region.get("city") or "").lower() == english.lower():
            return region["region_id"]
    return None


# v0.82.4: curated city names confirmed, during that release's investigation,
# to appear directly in a real Miltang venue string with no enclosing
# province name at all - "청주시 서원구...", "진주시 평거로...", not
# "충청북도 청주시..." or "경상남도 진주시...". _REGION_BY_ADMIN /
# _ADMIN_HEAD_RE only ever match a *leading* province name, so these would
# stay unresolvable through suggested_region_id() even with their province
# registered. Every entry here was checked against a real, currently-
# collected source item - not a guess at what might exist elsewhere.
CURATED_CITY_HINTS: dict[str, str] = {
    "청주": "청주", "진주": "진주", "창원": "창원", "포항": "포항",
    "울산": "울산", "대구": "대구", "제주": "제주",
    "분당": "경기", "성남": "경기",
}


# v0.96.36: the place words guess_region_label() accepts, each as a *whole*
# token. Every spelling an address really uses for the same place - "서울",
# "서울시", "서울특별시" - and the curated cities above under their own label.
# A token is a run of Hangul, Latin letters and digits, so "황제주차빌딩" is one
# token and never reads as 제주, and "울산탱고" (a club's name) never reads as
# 울산: only a word that is a place name on its own, or a place name followed
# directly by the district it contains ("부산진구", "분당정자동"), is evidence.
# Bare "광주" is absent on purpose - see _GWANGJU_METRO_GU.
_PLACE_TOKENS: dict[str, str] = {
    "서울": "서울", "서울시": "서울", "서울특별시": "서울",
    "부산": "부산", "부산시": "부산", "부산광역시": "부산",
    "대구": "대구", "대구시": "대구", "대구광역시": "대구",
    "인천": "인천", "인천시": "인천", "인천광역시": "인천",
    "광주광역시": "광주",
    "대전": "대전", "대전시": "대전", "대전광역시": "대전",
    "울산": "울산", "울산시": "울산", "울산광역시": "울산",
    "세종": "세종", "세종시": "세종", "세종특별자치시": "세종",
    "경기": "경기", "경기도": "경기",
    "강원": "강원", "강원도": "강원", "강원특별자치도": "강원",
    "충북": "충북", "충청북도": "충북", "충남": "충남", "충청남도": "충남",
    "전북": "전북", "전라북도": "전북", "전북특별자치도": "전북",
    "전남": "전남", "전라남도": "전남",
    "경북": "경북", "경상북도": "경북", "경남": "경남", "경상남도": "경남",
    "제주": "제주", "제주도": "제주", "제주시": "제주", "제주특별자치도": "제주",
    "청주": "청주", "청주시": "청주", "진주": "진주", "진주시": "진주",
    "창원": "창원", "창원시": "창원", "포항": "포항", "포항시": "포항",
    "분당": "경기", "분당구": "경기", "성남": "경기", "성남시": "경기",
}
# The province a curated city sits in. A string naming both ("경남 창원시
# 마산합포구") names one place, and the city is the more useful label (the
# v0.82.4 rule); naming two places neither of which contains the other is
# not evidence of either.
_CITY_PROVINCE = {"청주": "충북", "진주": "경남", "창원": "경남", "포항": "경북"}
# The region master code each label stands for - the bridge from a label read
# off an address to the master row a filter or a chip is about. A code, not a
# name: the master's names are the operator's to edit (KR-SEOUL is seeded as
# "Seoul" and Production renamed it 서울), its codes are not. The metro and
# province codes are _REGION_BY_ADMIN's; the four cities are migration 024's
# own rows.
LABEL_REGION_CODES: dict[str, str] = {
    label: code for label, (code, _english) in _REGION_BY_ADMIN.items()
}
LABEL_REGION_CODES.update({
    "청주": "KR-CHEONGJU", "진주": "KR-JINJU",
    "창원": "KR-CHANGWON", "포항": "KR-POHANG",
})
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
# What may follow a place name inside the same token: the district it
# contains, never a building, a road or a club ("황제주차빌딩", "서울대입구역").
_GLUED_DISTRICT_RE = re.compile(r"[가-힣]{1,4}[구군동읍면]")
_PLACE_FORMS = sorted(_PLACE_TOKENS, key=len, reverse=True)


def _token_place(token: str, following: str | None) -> str | None:
    """The place one token names, or None."""
    if token in _PLACE_TOKENS:
        return _PLACE_TOKENS[token]
    if token == "광주":
        return "광주" if following in _GWANGJU_METRO_GU else None
    if token.startswith("광주") and token[2:] in _GWANGJU_METRO_GU:
        return "광주"
    for form in _PLACE_FORMS:
        if token.startswith(form) and _GLUED_DISTRICT_RE.fullmatch(token[len(form):]):
            return _PLACE_TOKENS[form]
    return None


def guess_region_label(raw_text: str | None) -> str | None:
    """A best-effort, read-only region label for a raw venue string whose
    venue is not yet resolved into the master (so `events.region_id` is
    NULL) - so a reader is not shown a blank region while an operator has
    not yet resolved the venue. Never authoritative and never persisted
    anywhere: once a venue is genuinely resolved, its own region_id's name
    always wins over this (events_api.present() only calls this as a
    fallback). Nothing here promotes a string to a resolved venue - that
    judgement still belongs to an operator, unchanged from this module's own
    rule.

    v0.96.36: read from whole place-name tokens (`_PLACE_TOKENS`), not by
    substring. Before, "황제주차빌딩" read as 제주 and "전남광주통합특별시" as
    전남, because `"제주" in text` cannot tell a place from the middle of a
    word. A curated city still beats the province it sits in (진주 over
    경남); two places neither of which contains the other answer None,
    because a string that names both is not evidence of either. Nothing
    recognisable answers None - UNKNOWN rather than a guess.
    """
    text = unicodedata.normalize("NFKC", raw_text or "")
    tokens = _TOKEN_RE.findall(text)
    found: set[str] = set()
    for index, token in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        place = _token_place(token, following)
        if place:
            found.add(place)
    found -= {_CITY_PROVINCE[city] for city in found if city in _CITY_PROVINCE}
    return found.pop() if len(found) == 1 else None


def terms_for_label(label: str) -> list[str]:
    """The raw substrings at least one of which any text `guess_region_label()`
    places in `label` must contain - the reverse of the table above, for a
    caller (the region filter, the chip counts) that needs to narrow the rows
    it reads before asking the guess itself (`unresolved_event_ids()`).

    v0.96.36: every spelling in `_PLACE_TOKENS`, minus the ones another
    spelling already covers - "경상남도" does not contain "경남", so both."""
    if label == "광주":
        # Bare "광주" would also pull in Gyeonggi-do's 광주시 by substring
        # match (callers wrap each of these in "%...%" and run it as ILIKE)
        # - so search only for the same safe evidence guess_region_label()
        # itself requires. The embedded "%" here is deliberate: wrapped again
        # by the caller it becomes "%광주%동구%", matching "광주 동구" and
        # "광주동구" alike.
        return ["광주광역시"] + [f"광주%{gu}" for gu in _GWANGJU_METRO_GU]
    forms = [form for form, mapped in _PLACE_TOKENS.items() if mapped == label]
    return [form for form in forms
            if not any(other != form and other in form for other in forms)]


def unresolved_event_ids(con, label: str) -> list[int]:
    """The events with no resolved region that `guess_region_label()` places
    in `label` - exactly the ones a reader is shown under that label.

    v0.96.36: the region filter and the chip counts both used to approximate
    the guess with `venue_text ILIKE '%term%'`, which is not the same rule:
    "%제주%" matches "황제주차빌딩", and the chips only ever asked for the
    curated city labels, so an unresolved Seoul address counted under
    ?region=서울 but not on the 서울 chip. The ILIKE survives only to narrow
    the rows read; the guess itself decides.
    """
    terms = terms_for_label(label)
    if not terms:
        return []
    ors = " OR ".join(["venue_text ILIKE %s"] * len(terms))
    with con.cursor() as cur:
        cur.execute(
            "SELECT event_id, venue_text FROM events "
            f"WHERE region_id IS NULL AND ({ors})",
            tuple(f"%{term}%" for term in terms),
        )
        return [row[0] for row in cur.fetchall()
                if guess_region_label(row[1]) == label]


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
                  venue_name: str | None = None, events_updated: int = 0,
                  before: dict[str, Any] | None = None,
                  after: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write one venue decision to the audit trail.

    ``venue_name`` is stored alongside the id because a delete action outlives
    the venue it names: "deleted 라 벤따나, 2 events unlinked" has to stay
    readable after 라 벤따나 is gone.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {', '.join(ACTIONS)}")
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO venue_resolution_actions (unresolved_venue_id, raw_venue, "
            "  action, venue_id, venue_name, reviewer, events_updated, "
            "  before_json, after_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING *",
            (unresolved_venue_id, raw_venue, action, venue_id, venue_name, reviewer,
             events_updated,
             json.dumps(before or {}, ensure_ascii=False, default=str),
             json.dumps(after or {}, ensure_ascii=False, default=str)),
        )
        names = [c.name for c in cur.description]
        return dict(zip(names, cur.fetchone()))


def history(con, *, limit: int = 50) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT a.*, coalesce(v.name, a.venue_name) AS resolved_venue_name "
            "FROM venue_resolution_actions a "
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
                    reviewer: str = "admin", force: bool = False,
                    event_ids: list[int] | None = None,
                    preview_token: str | None = None) -> dict[str, Any]:
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
        # v0.96.37: decided once. A second Create on the same entry (a double
        # click, a second tab, a stale page) made a second venue for it.
        entry = _lock_open_entry(con, unresolved_venue_id)
        conflict = _region_refusal(con, {"region_id": region_id}, entry, address)
        if conflict:
            raise DecisionRefused([conflict])
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
            add_alias=False, event_ids=event_ids,
        )
        recorded = record_action(
            con, action=CREATE_AND_LINK, raw_venue=raw_venue, reviewer=reviewer,
            unresolved_venue_id=unresolved_venue_id, venue_id=venue["venue_id"],
            venue_name=venue["name"], events_updated=linked["events_updated"],
            before={"venue_text": raw_venue, "venue_id": None, "state": entry["state"]},
            after={"venue_id": venue["venue_id"], "name": venue["name"],
                   "address": venue.get("address"), "region_id": region_id,
                   "event_ids": linked["event_ids"],
                   **({"preview_token": preview_token[:16]} if preview_token else {})},
        )

    return {
        "venue": venue,
        "events_updated": linked["events_updated"],
        "action": recorded,
    }


def link_existing(con, *, unresolved_venue_id: int, venue_id: int,
                  reviewer: str = "admin", add_alias: bool = True,
                  event_ids: list[int] | None = None,
                  preview_token: str | None = None) -> dict[str, Any]:
    """A person says this string is that venue. Same transaction discipline.

    ``add_alias`` (v0.83.0): the raw string is registered as an alias by
    default, exactly as before -- an operator who already knows this reading
    is ambiguous (it also matches a different venue closely enough to worry
    about) can say no instead, and the spelling is not added to the venue.

    v0.96.37: either way the decision itself is kept - normalization reads a
    LINKED queue entry as well as the aliases (normalization.resolve_venue), so
    a link without an alias no longer comes undone the next time every
    candidate is re-read. ``event_ids`` limits the write to the events a
    preview showed (see confirm_link()).
    """
    entry = normalization.unresolved_venue(con, unresolved_venue_id)
    if entry is None:
        raise LookupError(f"no unresolved venue {unresolved_venue_id}")
    venue = master_data.get_venue(con, venue_id)
    if venue is None:
        raise LookupError(f"no venue {venue_id}")

    with con.transaction():
        # v0.96.37: only an OPEN entry is decided, and only onto a venue the
        # post's own words do not exclude. A second link overwrote the first
        # one's resolved_venue_id without a trace; a link into the wrong city
        # was applied here and then silently undone by the next normalization,
        # whose resolve_venue() refuses exactly that match.
        entry = _lock_open_entry(con, unresolved_venue_id)
        conflict = _region_refusal(con, venue, entry)
        if conflict:
            raise DecisionRefused([conflict])
        linked = normalization.link_unresolved_venue(
            con, unresolved_venue_id, venue_id, reviewer=reviewer, add_alias=add_alias,
            event_ids=event_ids,
        )
        recorded = record_action(
            con, action=LINK_EXISTING, raw_venue=entry["venue_text"], reviewer=reviewer,
            unresolved_venue_id=unresolved_venue_id, venue_id=venue_id,
            venue_name=venue["name"], events_updated=linked["events_updated"],
            before={"venue_text": entry["venue_text"], "venue_id": None,
                    "state": entry["state"]},
            after={"venue_id": venue_id, "name": venue["name"],
                   "alias_registered": add_alias,
                   "event_ids": linked["event_ids"],
                   **({"preview_token": preview_token[:16]} if preview_token else {})},
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
        entry = _lock_open_entry(con, unresolved_venue_id)
        normalization.dismiss_unresolved_venue(con, unresolved_venue_id, reviewer=reviewer)
        recorded = record_action(
            con, action=NOT_A_VENUE, raw_venue=entry["venue_text"], reviewer=reviewer,
            unresolved_venue_id=unresolved_venue_id,
            before={"venue_text": entry["venue_text"], "state": entry["state"]},
            after={"state": "DISMISSED", "reason": reason},
        )
    return {"action": recorded}


# --- an address the post gives but the venue string does not -----------------

# Where an address stops. A post runs the address straight into the next field:
# "서울 마포구 월드컵북로6길 49 B1 📩 예약 / 문의 🐰 바니". Everything from the
# emoji on belongs to somebody else.
_ADDRESS_STOP_RE = re.compile(
    r"(?:예약|문의|주차|전화|연락|입장료|참가비|밀롱가|쁘락|시간|일시|DJ|디제이|"
    r"오거나이저|주최|계좌|링크|http)"
    # v0.96.37: a bank and its account follow the address with nothing in
    # between - `제주시 노연로 110, 3층 카카오뱅크 3333-33-...` - and the whole
    # bank word goes, not just its tail.
    r"|\S*(?:은행|뱅크)|예금주"
    r"|[\[\](){}【】]"
    r"|\d[\d,]{2,}\s*원"
    r"|[^\w\s가-힣.,\-()]"          # an emoji or ornament ends it
)

# The address itself: an administrative name, then a road or lot with a number,
# then whatever building and floor follow.
_ADDRESS_BODY_RE = re.compile(
    rf"(?:{_ADMIN})(?:특별시|광역시|특별자치시|특별자치도|도|시)?"
    r"\s+[^\n]{2,30}?(?:로|길|가|동)\s*\d[^\n]{0,40}"
)
_LABELLED_ADDRESS_RE = re.compile(
    r"(?:주소|오시는\s*곳|오시는\s*길|address)\s*[:：]\s*([^\n]{4,80})", re.I,
)

# How far after the venue name an address may sit and still be that venue's.
# "📍 홍대 PISTA 서울 마포구 월드컵북로6길 49 B1" is adjacent; an address in a
# different paragraph belongs to a different thing.
ADDRESS_NEAR = 12


def _trim_address(value: str) -> str | None:
    """Cut a candidate address where the post stops talking about the address."""
    value = (value or "").strip()
    stop = _ADDRESS_STOP_RE.search(value)
    if stop and stop.start() > 0:
        value = value[:stop.start()]
    value = value.strip(" ,.-·")
    return value if looks_like_an_address(value) and len(value) >= 8 else None


def address_in(body: str, venue_text: str) -> str | None:
    """The address this post gives for *this* venue, or nothing.

    Preferred: an address written immediately after the venue's own name, which
    is how the posts actually do it. Failing that, a labelled 주소: line.

    Never an address that merely appears somewhere in the post: one post can
    mention a venue, a parking lot and next week's other milonga, and filling
    the form with the wrong one is worse than leaving it blank.
    """
    if not body or not venue_text:
        return None

    for probe in (venue_text, re.split(r"[(（]", venue_text, maxsplit=1)[0].strip()):
        if not probe:
            continue
        for mention in re.finditer(re.escape(probe), body, re.I):
            window = body[mention.end():mention.end() + ADDRESS_NEAR + 90]
            match = _ADDRESS_BODY_RE.search(window)
            if match and match.start() <= ADDRESS_NEAR:
                trimmed = _trim_address(match.group(0))
                if trimmed:
                    return trimmed

    labelled = _LABELLED_ADDRESS_RE.search(body)
    if labelled:
        return _trim_address(labelled.group(1))
    return None


def address_from_context(con, venue_text: str, *, limit: int = 5) -> dict[str, Any] | None:
    """An address for this venue string, agreed on by the posts that mention it.

    Two posts giving two different addresses is not a stronger signal than one
    giving none: the form stays empty and the operator reads the posts, which
    are linked right there. Only an address every post agrees on is offered.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT c.extracted_text, e.source_url FROM events e "
            "JOIN source_item_content c ON c.source_item_id = e.source_item_id "
            "WHERE e.venue_status = 'UNRESOLVED' "
            "  AND lower(e.venue_text) = lower(%s) "
            "  AND c.extracted_text IS NOT NULL "
            "ORDER BY e.event_date DESC LIMIT %s",
            (venue_text, limit),
        )
        rows = cur.fetchall()

    found: dict[str, str] = {}
    for body, source_url in rows:
        address = address_in(body, venue_text)
        if address:
            found.setdefault(_normalized_address(address), address)
            if len(found) > 1:
                return None
    if not found:
        return None
    address = next(iter(found.values()))
    return {"address": address, "posts": len(rows)}


def prefill(con, entry: dict[str, Any]) -> dict[str, Any]:
    """Everything the New Venue form can fill in for one queue entry.

    The venue string is the first source and the posts are the second: many
    posts write the venue's name in the 장소 line and its address right after,
    so the address is there even when the extracted string is just a name.

    Nothing is filled in that the text does not say, and every field stays
    editable — the point is to stop retyping what is already on screen, not to
    decide anything on the operator's behalf.
    """
    raw = entry["venue_text"]
    suggestion = suggest(raw, list(entry.get("alias_candidates") or []))

    address_source = "raw string" if suggestion["address"] else None
    if not suggestion["address"]:
        from_posts = address_from_context(con, raw)
        if from_posts:
            suggestion["address"] = from_posts["address"]
            address_source = "the post"
            suggestion["region_hint"] = _safe_admin_head(from_posts["address"])

    suggestion["address_source"] = address_source
    suggestion["region_id"] = suggested_region_id(con, suggestion["region_hint"])
    return suggestion


# --- ranked suggestions (v0.83.0) --------------------------------------------
#
# similar_venues() stayed exact-match on purpose: "a warning an operator
# cannot check is a warning they learn to click past." That principle is still
# the constraint here, not something this section overrides -- the fix for a
# fuzzy match is not to hide the fuzziness, it is to always show which field
# matched and how closely, and to never let a fuzzy match reach the same
# HIGH confidence an exact one earns. HIGH stays reserved for similar_venues()
# itself; nothing fuzzy is ever labelled HIGH, and nothing here writes
# anything -- these are suggestions for the existing Link Existing action to
# pre-fill, never a fourth way to resolve a venue on their own.
#
# Two situations turn a plausible name match into a wrong one: the same brand
# operating in two different cities ("스튜디오 오초" could be any city's own
# 오초), and an address that actively names a different place. Both cap the
# result at LOW rather than raising it to MEDIUM -- confidence never comes
# from name similarity alone.

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

_CONFIDENCE_RANK = {CONFIDENCE_HIGH: 2, CONFIDENCE_MEDIUM: 1, CONFIDENCE_LOW: 0}

# Below this, two strings sharing a few characters is coincidence, not a
# candidate worth an operator's attention at all.
_NAME_LOW_THRESHOLD = 0.45
# At or above this, with no address/region conflict, the match is worth
# highlighting even though it is still not exact.
_NAME_MEDIUM_THRESHOLD = 0.72


def _name_similarity(a: str | None, b: str | None) -> float:
    """0.0-1.0, on the same normalised text similar_venues() already compares
    exactly -- this only adds a distance underneath that same key, never a
    second notion of what "the same text" means."""
    from difflib import SequenceMatcher

    left, right = master_data.normalize_alias(a or ""), master_data.normalize_alias(b or "")
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _address_conflict(a: str | None, b: str | None) -> bool:
    """True only when BOTH sides actually name a place and those places
    disagree -- a venue with no address on either side is not a conflict, it
    is simply unverifiable, and stays a name-only match."""
    left, right = _normalized_address(a), _normalized_address(b)
    if not left or not right:
        return False
    return left != right and left not in right and right not in left


def suggest_venue_links(con, *, name: str, address: str | None = None,
                        raw_venue: str | None = None,
                        region_id: int | None = None,
                        limit: int = 3) -> list[dict[str, Any]]:
    """Up to `limit` existing venues this unresolved string might already be,
    ranked by confidence and never applied here.

    The exact tier is exactly similar_venues()'s own rule, carried through
    unchanged as CONFIDENCE_HIGH. Everything else is a fuzzy name match,
    capped at MEDIUM even at a near-perfect score, and pushed down to LOW the
    moment an address or region actively disagrees -- so "two studios happen
    to share a name" reads as a warning on the suggestion itself, not as a
    silent wrong answer with a high score attached.
    """
    exact = similar_venues(con, name=name, address=address, raw_venue=raw_venue)
    exact_ids = {v["venue_id"] for v in exact}
    ranked: list[dict[str, Any]] = []
    for venue in exact:
        reasons = venue.get("match_reasons") or []
        # An exact name/alias match still names a *different* venue if the
        # region actively disagrees and nothing address-level backs it up --
        # a franchise's own Busan branch matching a Seoul search by name
        # alone is exactly spec item 12's "same name, different region",
        # not a settled duplicate. A matching address makes the mismatch
        # moot (or a data error), so that reason stays HIGH regardless.
        region_mismatch = bool(
            region_id and venue.get("region_id") and region_id != venue["region_id"]
        )
        if region_mismatch and "same address" not in reasons:
            ranked.append({**venue, "confidence": CONFIDENCE_LOW, "score": 1.0,
                          "match_reasons": [*reasons, "different region"]})
        else:
            ranked.append({**venue, "confidence": CONFIDENCE_HIGH, "score": 1.0})

    probe_texts = [t for t in (name, raw_venue) if t]
    for venue in master_data.list_venues(con):
        if venue["venue_id"] in exact_ids:
            continue
        best_score, best_against = 0.0, None
        for probe in probe_texts:
            for other in [venue["name"], *(venue.get("aliases") or [])]:
                score = _name_similarity(probe, other)
                if score > best_score:
                    best_score, best_against = score, other
        if best_score < _NAME_LOW_THRESHOLD:
            continue

        conflict = _address_conflict(address, venue.get("address"))
        region_mismatch = bool(
            region_id and venue.get("region_id") and region_id != venue["region_id"]
        )
        if best_score >= _NAME_MEDIUM_THRESHOLD and not conflict and not region_mismatch:
            confidence = CONFIDENCE_MEDIUM
        else:
            confidence = CONFIDENCE_LOW

        reasons = [f"name similar to {best_against!r} ({best_score:.2f})"]
        if conflict:
            reasons.append("address conflict")
        if region_mismatch:
            reasons.append("different region")
        ranked.append({**venue, "confidence": confidence, "score": round(best_score, 3),
                       "match_reasons": reasons})

    ranked.sort(key=lambda e: (_CONFIDENCE_RANK[e["confidence"]], e["score"]), reverse=True)
    return ranked[:limit]


def group_unresolved(pending: list[dict[str, Any]],
                     suggestions: dict[int, list[dict[str, Any]]]) -> list[list[int]]:
    """Cluster queue entries an operator would otherwise review one at a time
    for what looks like the same real place.

    Two rules, both deliberately conservative: entries whose top suggestion
    (at MEDIUM confidence or better) names the same existing venue belong
    together; entries with no confident existing match at all belong together
    only when their own raw strings are very close to each other (0.82+ --
    well above the MEDIUM threshold used against the Venue Master, because
    two unresolved strings with no master venue backing either of them have
    nothing else vouching for the match). Grouping only ever changes review
    order and offers Group Apply -- it never changes what Link/Create/Dismiss
    does to any single row, and a LOW-confidence suggestion never joins a
    group by itself.
    """
    by_id = {e["unresolved_venue_id"]: e for e in pending}
    ids = list(by_id)
    # The core name only, address/alias parenthetical stripped by suggest()'s
    # own bracket-parsing - comparing full raw strings directly penalises the
    # exact real case this exists for ("이데알 탱고 까페" next to the same name
    # plus a full street address is a long, low-ratio diff by length alone).
    core_name = {uid: suggest(entry["venue_text"])["name"] for uid, entry in by_id.items()}

    def top_venue(uid: int) -> int | None:
        top = suggestions.get(uid) or []
        if top and top[0]["confidence"] != CONFIDENCE_LOW:
            return top[0]["venue_id"]
        return None

    visited: set[int] = set()
    groups: list[list[int]] = []
    for seed in ids:
        if seed in visited:
            continue
        visited.add(seed)
        group = [seed]
        seed_venue = top_venue(seed)
        for other in ids:
            if other in visited:
                continue
            other_venue = top_venue(other)
            same_suggestion = seed_venue is not None and seed_venue == other_venue
            # v0.83.1: checked regardless of what each side's own Venue
            # Master suggestion came out to, not only when both are
            # unmatched - found live: "El Tango (엘땅고)" and "EL TANGO" are
            # the same raw text after case-folding (core-name similarity
            # 1.0) but one had enough evidence to reach a MEDIUM suggestion
            # and the other did not, so the two rows never joined a group
            # even though they are obviously one review question. This adds
            # no new threshold - 0.82 is unchanged - it only stops a row's
            # own unrelated suggestion outcome from blocking a match this
            # confident between the raw strings themselves.
            own_match = _name_similarity(core_name[seed], core_name[other]) >= 0.82
            if same_suggestion or own_match:
                group.append(other)
                visited.add(other)
        groups.append(group)
    return groups


def group_link_existing(con, *, unresolved_venue_ids: list[int], venue_id: int,
                        reviewer: str = "admin", add_alias: bool = True,
                        event_ids: dict[int, list[int]] | None = None,
                        preview_token: str | None = None) -> dict[str, Any]:
    """Apply one Link Existing decision to every row in a group.

    Each row still goes through link_existing() individually -- same audit
    row per string, same per-string alias registration -- Group Apply changes
    how many clicks this takes, never what gets recorded.

    v0.96.37: all or nothing. Until now a row that failed (already resolved
    by somebody else, or a venue in another city) was skipped and the rest
    applied, so the group that was written was not the group that was
    previewed. Now any failure rolls the whole group back and raises
    DecisionRefused with every row's reason; the operator previews again.
    """
    results = []
    errors = []
    with con.transaction():
        for unresolved_venue_id in sorted(set(unresolved_venue_ids)):
            try:
                results.append(link_existing(
                    con, unresolved_venue_id=unresolved_venue_id, venue_id=venue_id,
                    reviewer=reviewer, add_alias=add_alias,
                    event_ids=(None if event_ids is None
                               else event_ids.get(unresolved_venue_id, [])),
                    preview_token=preview_token,
                ))
            except (LookupError, DecisionRefused) as exc:
                errors.append({"unresolved_venue_id": unresolved_venue_id, "error": str(exc)})
        if errors:
            raise DecisionRefused(
                [f"#{e['unresolved_venue_id']}: {e['error']}" for e in errors])
    return {
        "venue": results[0]["venue"] if results else None,
        "events_updated": sum(r["events_updated"] for r in results),
        "linked_count": len(results),
        "errors": errors,
    }


# --- preview before any decision (v0.96.37) ---------------------------------
#
# Every decision above changes the Venue Master, the events waiting on a
# string, their region (and so the region filter) and their identity keys
# (and so what the next duplicates scan folds). Until v0.96.37 the operator
# saw none of that before pressing the button: Link Existing and New Venue
# applied on the click, and only Group Apply had a preview - a list of strings,
# not of what would change.
#
# So each decision now has a preview that reads exactly what the decision
# would write and writes nothing, and the decision is accepted only with that
# preview's token. The token is an HMAC over the preview's own facts - the
# entry's state, the venue, the aliases, every affected event as it stands -
# keyed with the admin credential, so it is also something another site
# cannot forge into a cross-site form post. Confirm recomputes the preview
# under a row lock; if anything moved in between (somebody else decided the
# entry, a new post started waiting on the string, an event was re-read), the
# tokens differ and nothing is written.

def _lock_open_entry(con, unresolved_venue_id: int) -> dict[str, Any]:
    """The queue entry, locked for this transaction, if it is still OPEN.

    LookupError when there is no such entry; DecisionRefused when somebody has
    already decided it. Two confirms racing on one entry serialise here, and
    the second finds it decided.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM unresolved_venues WHERE unresolved_venue_id = %s FOR UPDATE",
            (unresolved_venue_id,),
        )
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"no unresolved venue {unresolved_venue_id}")
    entry = dict(zip(names, row))
    if entry["state"] != "OPEN":
        raise DecisionRefused([
            f"#{unresolved_venue_id} is already {entry['state']} "
            f"(by {entry.get('resolved_by') or 'someone'}) - nothing changed"
        ])
    return entry


def _region_refusal(con, venue: dict[str, Any], entry: dict[str, Any],
                    *addresses: str | None) -> str | None:
    """Why this venue cannot be the place this string names, if it cannot.

    The same narrow rule normalization applies to every alias match
    (venue_identity.region_conflict): a venue in a metropolitan city the
    string's own words, or the address its posts agree on, exclude. A link
    normalization would refuse is a link that would be undone by the next
    re-read, so it is refused here, before it is written.
    """
    from_posts = address_from_context(con, entry["venue_text"])
    texts = [entry["venue_text"], *addresses,
             from_posts["address"] if from_posts else None]
    if not venue_identity.region_conflict(con, venue, *texts):
        return None
    region = master_data.get_region(con, venue["region_id"]) if venue.get("region_id") else None
    said = sorted(set().union(*(venue_identity.stated_metros(t) for t in texts if t)))
    return (
        f"'{entry['venue_text']}' names {', '.join(said)}, but the venue is in "
        f"{region['code'] if region else venue.get('region_id')} - "
        "a different city cannot be the same place"
    )


def _token_key() -> bytes:
    secret = os.environ.get("ADMIN_PASSWORD", "")
    return hashlib.sha256(("dancemate-venue-decision:" + secret).encode()).digest()


def preview_token(facts: dict[str, Any]) -> str:
    body = json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str)
    return hmac.new(_token_key(), body.encode("utf-8"), hashlib.sha256).hexdigest()


def _token_matches(given: str | None, expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given, expected)


def _waiting_events(con, venue_text: str) -> list[dict[str, Any]]:
    """The events a decision on this string would change, as they stand."""
    from . import events_api  # local: events_api imports this module

    with con.cursor() as cur:
        cur.execute(
            "SELECT e.event_id, e.event_date, e.event_name, e.event_type, "
            "       e.start_time, e.end_time, e.end_day_offset, e.venue_id, "
            "       e.venue_text, e.venue_status, e.region_id, r.code AS region_code, "
            "       e.identity_key, e.series_key, e.canonical_event_id, "
            "       e.duplicate_decided_by, e.review_state, e.listing_state, "
            "       e.provenance, e.source_url, e.source_item_id, "
            "       (" + events_api._VISIBLE + ") AS publicly_visible "
            "FROM events e LEFT JOIN regions r ON r.region_id = e.region_id "
            "WHERE e.venue_status = 'UNRESOLVED' AND lower(e.venue_text) = lower(%s) "
            "ORDER BY e.event_date, e.event_id",
            (venue_text,),
        )
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def _canonical_outlook(con, moved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the next duplicates scan would do with these events once moved.

    Asks duplicates.classify() itself - the rule the scan applies - of each
    moved event against every other event on its date that would then share
    its place, so the preview cannot disagree with the scan about which nights
    fold. A pair either side of which a person has already decided is skipped,
    as the scan skips it.
    """
    from . import duplicates  # local: duplicates is a heavier module

    if not moved:
        return []
    by_id = {e["event_id"]: e for e in moved}
    places = {e["venue_id"] for e in moved if e.get("venue_id") is not None}
    dates = sorted({e["event_date"] for e in moved})
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM events WHERE event_date = ANY(%s) "
            "AND review_state <> 'REJECTED' "
            "AND (venue_id = ANY(%s::bigint[]) OR event_id = ANY(%s::bigint[]))",
            (dates, list(places), list(by_id)),
        )
        names = [c.name for c in cur.description]
        peers = [dict(zip(names, row)) for row in cur.fetchall()]
    rows = [{**p, **by_id[p["event_id"]]} if p["event_id"] in by_id else p for p in peers]

    outlook = []
    seen: set[tuple[int, int]] = set()
    for event in moved:
        for other in rows:
            pair = tuple(sorted((event["event_id"], other["event_id"])))
            if other["event_id"] == event["event_id"] or pair in seen:
                continue
            seen.add(pair)
            finding = duplicates.classify(event, other)
            if finding is None:
                continue
            human = any(r.get("duplicate_decided_by") not in (None, duplicates.AUTO)
                        for r in (event, other))
            outlook.append({
                "event_id": event["event_id"], "other_event_id": other["event_id"],
                "other_event_name": other.get("event_name"),
                "rule": finding["rule"],
                "outcome": ("UNCHANGED (decided by a person)" if human
                            else "AUTO_FOLD" if finding["auto"] else "REVIEW_PAIR"),
            })
    return outlook


def _moved(events: list[dict[str, Any]], venue: dict[str, Any] | None,
           region_code: str | None) -> list[dict[str, Any]]:
    """The events as the decision would leave them, with what changed."""
    out = []
    for event in events:
        venue_id = venue["venue_id"] if venue and venue.get("venue_id") else None
        key = normalization.venue_key(venue_id, event["venue_text"]) if venue_id else None
        after_identity = (normalization.identity_key(event["event_date"], key,
                                                     event["start_time"])
                          if key else event["identity_key"])
        after_series = (normalization.series_key(key, event["event_date"], event["event_name"])
                        if key else event["series_key"])
        out.append({
            **event,
            "proposed_venue_id": venue_id,
            "proposed_region_id": venue.get("region_id") if venue else None,
            "proposed_region_code": region_code,
            "identity_key_after": after_identity,
            "series_key_after": after_series,
            "identity_changes": after_identity != event["identity_key"],
            "region_changes": (venue.get("region_id") if venue else None) != event["region_id"],
        })
    return out


def _alias_plan(con, texts: list[str], venue_id: int | None) -> list[dict[str, Any]]:
    """Each spelling a decision would register, and who owns it today."""
    plan = []
    seen: set[str] = set()
    for text in texts:
        normalized = master_data.normalize_alias(text or "")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        owner = master_data.resolve_venue(con, text)
        if owner is None:
            status = "NEW"
        elif venue_id is not None and owner["venue_id"] == venue_id:
            status = "ALREADY_THIS_VENUE"
        else:
            status = "OWNED_BY_OTHER_VENUE"
        plan.append({"alias": text.strip(), "normalized": normalized, "status": status,
                     "owner_venue_id": owner["venue_id"] if owner else None,
                     "owner_name": owner["name"] if owner else None})
    return plan


def _evidence(con, entry: dict[str, Any]) -> dict[str, Any]:
    from_posts = address_from_context(con, entry["venue_text"])
    return {
        "posts": context(con, entry["venue_text"], limit=5),
        "post_address": from_posts["address"] if from_posts else None,
        "suggestion": suggest(entry["venue_text"], list(entry.get("alias_candidates") or [])),
    }


def _summary(moved: list[dict[str, Any]], outlook: list[dict[str, Any]], today) -> dict[str, int]:
    return {
        "events": len(moved),
        "publicly_visible": sum(1 for e in moved if e["publicly_visible"]),
        "upcoming_visible": sum(1 for e in moved
                                if e["publicly_visible"] and e["event_date"] >= today),
        "region_changes": sum(1 for e in moved if e["region_changes"]),
        "identity_changes": sum(1 for e in moved if e["identity_changes"]),
        "predicted_auto_folds": sum(1 for o in outlook if o["outcome"] == "AUTO_FOLD"),
        "predicted_review_pairs": sum(1 for o in outlook if o["outcome"] == "REVIEW_PAIR"),
    }


def _event_facts(moved: list[dict[str, Any]]) -> list[list[Any]]:
    return [[e["event_id"], e["venue_id"], e["region_id"], e["identity_key"],
             e["canonical_event_id"], str(e["event_date"]), str(e["start_time"])]
            for e in moved]


def _region_code(con, region_id: int | None) -> str | None:
    region = master_data.get_region(con, region_id) if region_id else None
    return region["code"] if region else None


def preview_link(con, *, unresolved_venue_id: int, venue_id: int,
                 add_alias: bool = True) -> dict[str, Any]:
    """Everything Link Existing would change, and why it may not. Writes nothing."""
    from . import events_api

    entry = normalization.unresolved_venue(con, unresolved_venue_id)
    if entry is None:
        raise LookupError(f"no unresolved venue {unresolved_venue_id}")
    venue = master_data.get_venue(con, venue_id)
    if venue is None:
        raise LookupError(f"no venue {venue_id}")
    region_code = _region_code(con, venue.get("region_id"))

    blockers, warnings = [], []
    if entry["state"] != "OPEN":
        blockers.append(f"#{unresolved_venue_id} is already {entry['state']} - "
                        "a decided entry is corrected with Revert, not decided again")
    conflict = _region_refusal(con, venue, entry)
    if conflict:
        blockers.append(conflict)
    plan = _alias_plan(con, [entry["venue_text"]], venue_id) if add_alias else []
    for alias in plan:
        if alias["status"] == "OWNED_BY_OTHER_VENUE":
            blockers.append(f"the spelling '{alias['alias']}' already belongs to "
                            f"#{alias['owner_venue_id']} {alias['owner_name']}")
    if not venue.get("enabled", True):
        warnings.append(f"{venue['name']} is deactivated")
    evidence = _evidence(con, entry)
    address = evidence["post_address"] or evidence["suggestion"]["address"]
    if _address_conflict(address, venue.get("address")):
        warnings.append(f"the posts give '{address}', the venue's address is "
                        f"'{venue.get('address')}' - check they are the same place")

    events = [] if entry["state"] != "OPEN" else _waiting_events(con, entry["venue_text"])
    moved = _moved(events, venue, region_code)
    outlook = _canonical_outlook(con, [{**e, "venue_id": venue_id,
                                        "region_id": venue.get("region_id")} for e in moved])
    facts = {
        "action": LINK_EXISTING, "entry": [entry["unresolved_venue_id"], entry["state"],
                                           entry["venue_text"]],
        "venue": [venue["venue_id"], venue.get("region_id"), venue.get("enabled")],
        "add_alias": bool(add_alias), "aliases": plan, "events": _event_facts(moved),
    }
    return {
        "action": LINK_EXISTING, "entry": entry, "venue": {**venue, "region_code": region_code},
        "add_alias": bool(add_alias), "alias_plan": plan, "evidence": evidence,
        "events": moved, "canonical": outlook,
        "summary": _summary(moved, outlook, events_api.today()),
        "blockers": blockers, "warnings": warnings, "token": preview_token(facts),
    }


def preview_create(con, *, unresolved_venue_id: int, name: str,
                   region_id: int | None = None, address: str | None = None,
                   aliases: list[str] | None = None, notes: str | None = None,
                   force: bool = False) -> dict[str, Any]:
    """Everything New Venue would change, and why it may not. Writes nothing.

    A possible duplicate is a blocker until the operator says these are
    different places (``force``) - the same question create_and_link() asks -
    and the answer is part of the token, so it cannot be skipped by replaying
    a confirm.
    """
    from . import events_api, master_edit

    entry = normalization.unresolved_venue(con, unresolved_venue_id)
    if entry is None:
        raise LookupError(f"no unresolved venue {unresolved_venue_id}")
    name = (name or "").strip()
    address = (address or "").strip() or None
    alias_list = [a.strip() for a in (aliases or []) if a and a.strip()]
    region_code = _region_code(con, region_id)
    if region_id is not None and region_code is None:
        raise LookupError(f"no region {region_id}")

    blockers, warnings = [], []
    if not name:
        blockers.append("a venue name is required")
    if entry["state"] != "OPEN":
        blockers.append(f"#{unresolved_venue_id} is already {entry['state']} - "
                        "a decided entry is corrected with Revert, not decided again")
    if region_id is None:
        warnings.append("no region: these events will stay out of every region filter")
    conflict = _region_refusal(con, {"region_id": region_id}, entry, address)
    if conflict:
        blockers.append(conflict)
    mismatch = master_edit.region_conflict(con, address, region_id)
    if mismatch:
        warnings.append(mismatch)
    if not address:
        warnings.append("no address: nothing but the name will identify this place")
    matches = similar_venues(con, name=name, address=address, raw_venue=entry["venue_text"])
    if matches and not force:
        blockers.append("a similar venue is already registered - link it, or confirm "
                        "these are different places")
    elif matches:
        warnings.append("registered although similar venues exist (confirmed different)")
    plan = _alias_plan(con, [*alias_list, entry["venue_text"], name], None)
    for alias in plan:
        if alias["status"] == "OWNED_BY_OTHER_VENUE":
            blockers.append(f"the spelling '{alias['alias']}' already belongs to "
                            f"#{alias['owner_venue_id']} {alias['owner_name']}")

    proposed = {"venue_id": None, "name": name, "region_id": region_id,
                "region_code": region_code, "address": address,
                "notes": (notes or "").strip() or None}
    events = [] if entry["state"] != "OPEN" else _waiting_events(con, entry["venue_text"])
    # A new venue has no id yet; its events can only fold with each other.
    placeholder = {"venue_id": -1, "region_id": region_id}
    moved = _moved(events, placeholder, region_code)
    for event in moved:
        event["proposed_venue_id"] = None
    outlook = _canonical_outlook(con, [{**e, "venue_id": -1, "region_id": region_id}
                                       for e in moved])
    facts = {
        "action": CREATE_AND_LINK, "entry": [entry["unresolved_venue_id"], entry["state"],
                                             entry["venue_text"]],
        "venue": [name, region_id, address, proposed["notes"]], "force": bool(force),
        "aliases": plan, "matches": sorted(m["venue_id"] for m in matches),
        "events": _event_facts(moved),
    }
    return {
        "action": CREATE_AND_LINK, "entry": entry, "venue": proposed,
        "aliases": alias_list, "alias_plan": plan, "duplicates": matches,
        "force": bool(force), "evidence": _evidence(con, entry),
        "events": moved, "canonical": outlook,
        "summary": _summary(moved, outlook, events_api.today()),
        "blockers": blockers, "warnings": warnings, "token": preview_token(facts),
    }


def preview_group(con, *, unresolved_venue_ids: list[int], venue_id: int,
                  add_alias: bool = True) -> dict[str, Any]:
    """Group Apply's preview: each row's own preview, and one token for all."""
    rows = [preview_link(con, unresolved_venue_id=uid, venue_id=venue_id, add_alias=add_alias)
            for uid in sorted(set(unresolved_venue_ids))]
    blockers = [f"#{r['entry']['unresolved_venue_id']}: {b}" for r in rows for b in r["blockers"]]
    keys = {"events", "publicly_visible", "upcoming_visible", "region_changes",
            "identity_changes", "predicted_auto_folds", "predicted_review_pairs"}
    summary = {k: sum(r["summary"][k] for r in rows) for k in keys}
    return {
        "action": "GROUP_LINK", "venue": rows[0]["venue"] if rows else None,
        "rows": rows, "summary": summary, "blockers": blockers,
        "warnings": [w for r in rows for w in r["warnings"]],
        "token": preview_token({"action": "GROUP_LINK",
                                "rows": [r["token"] for r in rows]}),
    }


def confirm_link(con, *, unresolved_venue_id: int, venue_id: int, token: str | None,
                 add_alias: bool = True, reviewer: str = "admin") -> dict[str, Any]:
    """Link Existing, accepted only with the token its preview carried."""
    with con.transaction():
        _lock_entries(con, [unresolved_venue_id])
        preview = preview_link(con, unresolved_venue_id=unresolved_venue_id,
                               venue_id=venue_id, add_alias=add_alias)
        if preview["blockers"]:
            raise DecisionRefused(preview["blockers"])
        if not _token_matches(token, preview["token"]):
            raise StalePreview(["the preview is out of date - nothing changed; preview again"])
        return link_existing(
            con, unresolved_venue_id=unresolved_venue_id, venue_id=venue_id,
            reviewer=reviewer, add_alias=add_alias, preview_token=token,
            event_ids=[e["event_id"] for e in preview["events"]],
        )


def confirm_create(con, *, unresolved_venue_id: int, name: str, token: str | None,
                   region_id: int | None = None, address: str | None = None,
                   aliases: list[str] | None = None, notes: str | None = None,
                   force: bool = False, reviewer: str = "admin") -> dict[str, Any]:
    """New Venue, accepted only with the token its preview carried."""
    with con.transaction():
        _lock_entries(con, [unresolved_venue_id])
        preview = preview_create(con, unresolved_venue_id=unresolved_venue_id, name=name,
                                 region_id=region_id, address=address, aliases=aliases,
                                 notes=notes, force=force)
        if preview["blockers"]:
            raise DecisionRefused(preview["blockers"])
        if not _token_matches(token, preview["token"]):
            raise StalePreview(["the preview is out of date - nothing changed; preview again"])
        return create_and_link(
            con, unresolved_venue_id=unresolved_venue_id, name=name, region_id=region_id,
            address=address, notes=notes, aliases=aliases, reviewer=reviewer,
            force=True, preview_token=token,
            event_ids=[e["event_id"] for e in preview["events"]],
        )


def confirm_group(con, *, unresolved_venue_ids: list[int], venue_id: int,
                  token: str | None, add_alias: bool = True,
                  reviewer: str = "admin") -> dict[str, Any]:
    """Group Apply, all or nothing, accepted only with its preview's token."""
    with con.transaction():
        _lock_entries(con, unresolved_venue_ids)
        preview = preview_group(con, unresolved_venue_ids=unresolved_venue_ids,
                                venue_id=venue_id, add_alias=add_alias)
        if not preview["rows"]:
            raise DecisionRefused(["nothing to link"])
        if preview["blockers"]:
            raise DecisionRefused(preview["blockers"])
        if not _token_matches(token, preview["token"]):
            raise StalePreview(["the preview is out of date - nothing changed; preview again"])
        return group_link_existing(
            con, unresolved_venue_ids=unresolved_venue_ids, venue_id=venue_id,
            reviewer=reviewer, add_alias=add_alias, preview_token=token,
            event_ids={r["entry"]["unresolved_venue_id"]: [e["event_id"] for e in r["events"]]
                       for r in preview["rows"]},
        )


def _lock_entries(con, unresolved_venue_ids: list[int]) -> None:
    """Row locks on the entries a confirm is about to decide, in id order, so
    two confirms over overlapping groups cannot deadlock."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT unresolved_venue_id FROM unresolved_venues "
            "WHERE unresolved_venue_id = ANY(%s::bigint[]) "
            "ORDER BY unresolved_venue_id FOR UPDATE",
            (sorted(set(unresolved_venue_ids)),),
        )
        cur.fetchall()


# --- taking a decision back (v0.96.37) ---------------------------------------
#
# Before this, the only way to undo a wrong link was to delete the venue it
# went to - which, for a link onto the right venue's wrong neighbour, deletes
# a real place. A revert undoes one decision and nothing else: the string's
# own alias on that venue (and no other spelling), the events that decision
# moved back to the words their post used, the automatic folds those events
# were in, and the queue entry back to OPEN. Folds and verdicts a person made
# are left exactly as they are - automation releases what automation decided.
# The original decision's audit row stays; the revert adds its own.

def preview_revert(con, *, unresolved_venue_id: int) -> dict[str, Any]:
    """What reverting this decision would change, and why it may not."""
    from . import duplicates, events_api

    entry = normalization.unresolved_venue(con, unresolved_venue_id)
    if entry is None:
        raise LookupError(f"no unresolved venue {unresolved_venue_id}")
    blockers, warnings = [], []
    venue = None
    alias = None
    events: list[dict[str, Any]] = []
    if entry["state"] == "OPEN":
        blockers.append(f"#{unresolved_venue_id} is OPEN - there is no decision to revert")
    elif entry["state"] == "LINKED":
        venue = master_data.get_venue(con, entry["resolved_venue_id"]) \
            if entry.get("resolved_venue_id") else None
        if venue is None:
            blockers.append("the venue this entry was linked to no longer exists")
        else:
            alias = next((a for a in master_data.venue_aliases(con, venue["venue_id"])
                          if a["normalized_alias"] == entry["normalized_text"]), None)
            if master_data.normalize_alias(venue["name"]) == entry["normalized_text"]:
                blockers.append(
                    f"'{entry['venue_text']}' is {venue['name']}'s own name - edit or "
                    "delete the venue instead of reverting the link")
            with con.cursor() as cur:
                cur.execute(
                    "SELECT e.event_id, e.event_date, e.event_name, e.event_type, "
                    "       e.start_time, e.end_time, e.end_day_offset, e.venue_id, "
                    "       e.venue_text, e.region_id, r.code AS region_code, "
                    "       e.identity_key, e.series_key, e.canonical_event_id, "
                    "       e.duplicate_decided_by, e.listing_state, e.provenance, "
                    "       (" + events_api._VISIBLE + ") AS publicly_visible "
                    "FROM events e LEFT JOIN regions r ON r.region_id = e.region_id "
                    "WHERE e.venue_id = %s AND e.venue_text IS NOT NULL "
                    "ORDER BY e.event_date, e.event_id",
                    (venue["venue_id"],),
                )
                names = [c.name for c in cur.description]
                events = [dict(zip(names, row)) for row in cur.fetchall()
                          if master_data.normalize_alias(row[8]) == entry["normalized_text"]]
            # The other spellings this string was read beside. If one of them
            # still resolves to the venue once this alias is gone, the next
            # re-normalization links the events straight back - the revert
            # would be undone the way a link into the wrong city used to be.
            # So it is refused, saying which spelling to take off first (or,
            # for a venue that should not exist, Unlink & Delete).
            for other in entry.get("alias_candidates") or []:
                if master_data.normalize_alias(other) == entry["normalized_text"]:
                    continue
                found = master_data.resolve_venue(con, other)
                if (found and found["venue_id"] == venue["venue_id"]
                        and not venue_identity.region_conflict(con, found, entry["venue_text"],
                                                               other)):
                    blockers.append(
                        f"'{other}' is also a spelling of {venue['name']}, so the next "
                        "normalization would link these events again - remove that alias "
                        "first, or Unlink & Delete the venue if it should not exist")
    moved = []
    for event in events:
        key = normalization.venue_key(None, event["venue_text"])
        after = normalization.identity_key(event["event_date"], key, event["start_time"])
        moved.append({
            **event, "proposed_venue_id": None, "proposed_region_id": None,
            "proposed_region_code": None, "identity_key_after": after,
            "series_key_after": normalization.series_key(key, event["event_date"],
                                                         event["event_name"]),
            "identity_changes": after != event["identity_key"],
            "region_changes": event["region_id"] is not None,
        })
    ids = [e["event_id"] for e in moved]
    folds = []
    if ids:
        with con.cursor() as cur:
            cur.execute(
                "SELECT event_id, canonical_event_id, duplicate_decided_by FROM events "
                "WHERE canonical_event_id IS NOT NULL "
                "  AND (event_id = ANY(%s) OR canonical_event_id = ANY(%s)) "
                "ORDER BY event_id",
                (ids, ids),
            )
            for event_id, canonical, decided_by in cur.fetchall():
                folds.append({"event_id": event_id, "other_event_id": canonical,
                              "rule": decided_by,
                              "outcome": ("RELEASED" if decided_by == duplicates.AUTO
                                          else "UNCHANGED (decided by a person)")})
    today = events_api.today()
    summary = {
        "events": len(moved),
        "publicly_visible": sum(1 for e in moved if e["publicly_visible"]),
        "upcoming_visible": sum(1 for e in moved
                                if e["publicly_visible"] and e["event_date"] >= today),
        "region_changes": sum(1 for e in moved if e["region_changes"]),
        "identity_changes": sum(1 for e in moved if e["identity_changes"]),
        "released_folds": sum(1 for f in folds if f["outcome"] == "RELEASED"),
    }
    facts = {
        "action": DECISION_REVERT,
        "entry": [entry["unresolved_venue_id"], entry["state"], entry.get("resolved_venue_id")],
        "alias": alias["venue_alias_id"] if alias else None,
        "events": _event_facts(moved), "folds": folds,
    }
    return {
        "action": DECISION_REVERT, "entry": entry, "venue": venue, "alias": alias,
        "events": moved, "canonical": folds, "summary": summary,
        "blockers": blockers, "warnings": warnings, "token": preview_token(facts),
    }


def revert_decision(con, *, unresolved_venue_id: int, token: str | None,
                    reviewer: str = "admin") -> dict[str, Any]:
    """Undo one queue decision, exactly as its preview showed. One transaction."""
    with con.transaction():
        _lock_entries(con, [unresolved_venue_id])
        preview = preview_revert(con, unresolved_venue_id=unresolved_venue_id)
        if preview["blockers"]:
            raise DecisionRefused(preview["blockers"])
        if not _token_matches(token, preview["token"]):
            raise StalePreview(["the preview is out of date - nothing changed; preview again"])
        entry, venue, alias = preview["entry"], preview["venue"], preview["alias"]
        ids = [e["event_id"] for e in preview["events"]]
        released = 0
        if ids:
            with con.cursor() as cur:
                cur.execute(
                    "UPDATE events SET venue_id = NULL, region_id = NULL, "
                    "  venue_status = 'UNRESOLVED', updated_at = now() "
                    "WHERE event_id = ANY(%s)",
                    (ids,),
                )
            released = _release_automatic_duplicates(con, ids)
            for event_id in ids:
                normalization._refresh_keys(con, event_id)
        if alias is not None:
            master_data.remove_venue_alias(con, alias["venue_alias_id"])
        with con.cursor() as cur:
            cur.execute(
                "UPDATE unresolved_venues SET state = 'OPEN', resolved_venue_id = NULL, "
                "  resolved_by = NULL, resolved_at = NULL WHERE unresolved_venue_id = %s",
                (unresolved_venue_id,),
            )
        recorded = record_action(
            con, action=DECISION_REVERT, raw_venue=entry["venue_text"], reviewer=reviewer,
            unresolved_venue_id=unresolved_venue_id,
            venue_id=venue["venue_id"] if venue else None,
            venue_name=venue["name"] if venue else None, events_updated=len(ids),
            before={"state": entry["state"], "venue_id": entry.get("resolved_venue_id"),
                    "resolved_by": entry.get("resolved_by"),
                    "resolved_at": entry.get("resolved_at"),
                    "alias": alias["alias"] if alias else None, "event_ids": ids},
            after={"state": "OPEN", "venue_id": None, "alias_removed": bool(alias),
                   "automatic_merges_released": released,
                   "preview_token": (token or "")[:16]},
        )
    return {"events_updated": len(ids), "automatic_merges_released": released,
            "alias_removed": alias["alias"] if alias else None, "action": recorded}


def recent_decisions(con, *, limit: int = 20) -> list[dict[str, Any]]:
    """Decisions still standing on their queue entry - the ones Revert applies to."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (a.unresolved_venue_id) a.*, u.state AS entry_state, "
            "       coalesce(v.name, a.venue_name) AS resolved_venue_name "
            "FROM venue_resolution_actions a "
            "JOIN unresolved_venues u ON u.unresolved_venue_id = a.unresolved_venue_id "
            "LEFT JOIN venues v ON v.venue_id = a.venue_id "
            "WHERE a.action = ANY(%s) AND u.state <> 'OPEN' "
            "ORDER BY a.unresolved_venue_id, a.venue_action_id DESC",
            (list(RESOLUTION_ACTIONS),),
        )
        names = [c.name for c in cur.description]
        rows = [dict(zip(names, row)) for row in cur.fetchall()]
    rows.sort(key=lambda r: r["venue_action_id"], reverse=True)
    return rows[:limit]


# --- removing a venue -------------------------------------------------------
#
# A venue registered by mistake has to be removable, and removing it must not
# take anything real with it. What a venue *is* here is a link: the posts, the
# evidence, the candidates and the normalised events all exist without it and
# all survive it. So deletion undoes the link and stops.

class VenueInUse(Exception):
    """Deleting this would change events. Carries what would change."""

    def __init__(self, usage: dict[str, Any]):
        super().__init__("this venue is in use")
        self.usage = usage


def usage(con, venue_id: int) -> dict[str, Any]:
    """What currently depends on this venue.

    Read before offering any Delete button, so the operator is told "3 events
    use this" rather than finding out afterwards.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE venue_id = %s) AS events, "
            "       count(*) FILTER (WHERE venue_id = %s AND listing_state = 'LISTED' "
            "                          AND canonical_event_id IS NULL "
            "                          AND provenance = 'LIVE') AS listed_events "
            "FROM events",
            (venue_id, venue_id),
        )
        counts = dict(zip([c.name for c in cur.description], cur.fetchone()))
        cur.execute("SELECT count(*) FROM venue_aliases WHERE venue_id = %s", (venue_id,))
        counts["aliases"] = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM unresolved_venues WHERE resolved_venue_id = %s",
            (venue_id,),
        )
        counts["queue_entries"] = cur.fetchone()[0]
        cur.execute(
            "SELECT DISTINCT venue_text FROM events "
            "WHERE venue_id = %s AND venue_text IS NOT NULL",
            (venue_id,),
        )
        counts["venue_texts"] = [r[0] for r in cur.fetchall()]
    counts["in_use"] = bool(counts["events"] or counts["queue_entries"])
    return counts


def _unlink_events(con, venue_id: int) -> list[int]:
    """Send every event back to the string it was read from.

    ``venue_text`` is untouched -- it is what the post said, and the post has
    not changed. Only our claim to have recognised it goes away, so the reader
    sees the raw string marked unconfirmed again rather than losing the line.
    """
    with con.cursor() as cur:
        cur.execute(
            "UPDATE events SET venue_id = NULL, region_id = NULL, "
            "  venue_status = CASE WHEN venue_text IS NULL THEN 'ABSENT' "
            "                      ELSE 'UNRESOLVED' END, "
            "  updated_at = now() "
            "WHERE venue_id = %s RETURNING event_id",
            (venue_id,),
        )
        return [row[0] for row in cur.fetchall()]


def _requeue(con, venue_id: int, venue_texts: list[str]) -> int:
    """Put the strings back in the queue, so they can be decided again.

    This is why deleting a venue loses nothing: the alias rows go with the
    venue, but the string itself came from a post and is still on the events,
    so it can be asked about again.
    """
    restored = 0
    with con.cursor() as cur:
        cur.execute(
            "UPDATE unresolved_venues SET state = 'OPEN', resolved_venue_id = NULL, "
            "  resolved_by = NULL, resolved_at = NULL "
            "WHERE resolved_venue_id = %s RETURNING unresolved_venue_id",
            (venue_id,),
        )
        restored += len(cur.fetchall())
        for text in venue_texts:
            normalized = master_data.normalize_alias(text)
            if not normalized:
                continue
            cur.execute(
                "INSERT INTO unresolved_venues (venue_text, normalized_text, "
                "  alias_candidates, state) VALUES (%s, %s, %s::jsonb, 'OPEN') "
                "ON CONFLICT (normalized_text) DO UPDATE SET state = 'OPEN', "
                "  resolved_venue_id = NULL, resolved_by = NULL, resolved_at = NULL, "
                "  last_seen_at = now() "
                "RETURNING unresolved_venue_id",
                (text, normalized, json.dumps([text], ensure_ascii=False)),
            )
            if cur.fetchone():
                restored += 1
    return restored


def _release_automatic_duplicates(con, event_ids: list[int]) -> int:
    """Undo automatic merges that were based on the venue we just removed.

    The duplicate rules compare date, place and start time. Take the place away
    and a merge the rules made no longer follows from anything, so it is
    released and the next scan decides again on what is now true.

    A person's verdict is left exactly as it is. Automation released what
    automation decided; it does not get to overturn a human.
    """
    if not event_ids:
        return 0
    with con.cursor() as cur:
        cur.execute(
            "UPDATE events SET canonical_event_id = NULL, duplicate_decided_by = NULL, "
            "  listing_state = CASE WHEN review_state IN ('REJECTED', 'DUPLICATE') "
            "                       THEN 'HIDDEN' ELSE 'LISTED' END, updated_at = now() "
            "WHERE duplicate_decided_by = 'AUTO' "
            "  AND (event_id = ANY(%s) OR canonical_event_id = ANY(%s)) "
            "RETURNING event_id",
            (event_ids, event_ids),
        )
        return len(cur.fetchall())


def delete_venue(con, venue_id: int, *, reviewer: str = "admin",
                 unlink: bool = False) -> dict[str, Any]:
    """Remove a venue. Refuses to take anything else with it.

    Without ``unlink`` this only removes a venue nothing references, and raises
    VenueInUse otherwise -- with the counts, so the console can say "3 events
    use this" instead of deleting them out from under someone.

    With ``unlink`` the events go back to the raw strings they were read from,
    those strings go back in the queue, and the venue row goes. The posts, the
    evidence, the candidates, the events and every review stay exactly where
    they were.
    """
    venue = master_data.get_venue(con, venue_id)
    if venue is None:
        raise LookupError(f"no venue {venue_id}")
    current = usage(con, venue_id)
    if current["in_use"] and not unlink:
        raise VenueInUse(current)

    with con.transaction():
        unlinked = _unlink_events(con, venue_id) if current["events"] else []
        released = _release_automatic_duplicates(con, unlinked)
        requeued = _requeue(con, venue_id, current["venue_texts"])
        for event_id in unlinked:
            normalization._refresh_keys(con, event_id)
        with con.cursor() as cur:
            cur.execute("DELETE FROM venues WHERE venue_id = %s", (venue_id,))
        recorded = record_action(
            con,
            action=VENUE_UNLINK_DELETE if current["in_use"] else VENUE_DELETE,
            raw_venue=venue["name"], reviewer=reviewer, venue_id=venue_id,
            venue_name=venue["name"], events_updated=len(unlinked),
            before={"venue_id": venue_id, "name": venue["name"],
                    "address": venue.get("address"), "aliases": current["aliases"],
                    "events": current["events"]},
            after={"deleted": True, "events_unlinked": len(unlinked),
                   "strings_requeued": requeued,
                   "automatic_merges_released": released},
        )

    return {
        "venue": venue,
        "events_unlinked": len(unlinked),
        "strings_requeued": requeued,
        "automatic_merges_released": released,
        "action": recorded,
    }


def set_venue_enabled(con, venue_id: int, enabled: bool, *,
                      reviewer: str = "admin") -> dict[str, Any]:
    """Take a venue out of circulation without losing what it resolved.

    The gentler option when a venue is wrong for new work but right for the
    events already attached to it: nothing is unlinked and nothing is deleted.
    """
    venue = master_data.get_venue(con, venue_id)
    if venue is None:
        raise LookupError(f"no venue {venue_id}")
    with con.transaction():
        updated = master_data.update_venue(con, venue_id, enabled=enabled)
        recorded = record_action(
            con, action=VENUE_DEACTIVATE if not enabled else VENUE_REACTIVATE,
            raw_venue=venue["name"], reviewer=reviewer, venue_id=venue_id,
            venue_name=venue["name"],
            before={"enabled": venue["enabled"]}, after={"enabled": enabled},
        )
    return {"venue": updated, "action": recorded}


def venues_with_usage(
    con, *, region_id: int | None = None, genre_ids: "list[int] | None" = None,
    limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    """The venue list, each row carrying what depends on it."""
    venues = master_data.list_venues(
        con, region_id=region_id, genre_ids=genre_ids, limit=limit, offset=offset)
    if not venues:
        return []
    with con.cursor() as cur:
        cur.execute(
            "SELECT venue_id, count(*) AS events, "
            "       count(*) FILTER (WHERE listing_state = 'LISTED' "
            "                          AND canonical_event_id IS NULL "
            "                          AND provenance = 'LIVE') AS listed_events "
            "FROM events WHERE venue_id IS NOT NULL GROUP BY venue_id"
        )
        counts = {row[0]: {"events": row[1], "listed_events": row[2]}
                  for row in cur.fetchall()}
    for venue in venues:
        venue.update(counts.get(venue["venue_id"], {"events": 0, "listed_events": 0}))
        venue["in_use"] = bool(venue["events"])
    return venues


# v0.86.9: a venue's own events, listed where the venue is. Joined on
# events.venue_id - the real foreign key, the same one the "Events using"
# count above has always used - never on a venue name, so renaming a venue
# keeps every event it had.
VENUE_EVENTS_PAGE_SIZE = 20


def count_venue_events(con, venue_id: int) -> int:
    with con.cursor() as cur:
        cur.execute("SELECT count(*) FROM events WHERE venue_id = %s", (venue_id,))
        return cur.fetchone()[0]


def venue_events(con, venue_id: int, *, limit: int = VENUE_EVENTS_PAGE_SIZE,
                 offset: int = 0, today=None) -> list[dict[str, Any]]:
    """Upcoming first (soonest first), then past (most recent first).

    Every event the venue carries - hidden and merged ones too, marked as
    such - because this is the operator's view of what points at the venue,
    and the count beside the venue counts all of them.
    """
    from . import events_api  # local: events_api imports this module

    day = today or events_api.today()
    with con.cursor() as cur:
        cur.execute(
            "SELECT e.event_id, e.candidate_id, e.event_name, e.event_type, "
            "       e.event_formats, e.event_date, e.start_time, e.end_time, "
            "       e.end_day_offset, e.engine_status, e.review_state, "
            "       e.listing_state, e.canonical_event_id, e.provenance, "
            "       g.code AS genre_code, g.name AS genre_name, "
            "       (" + events_api._VISIBLE + ") AS publicly_visible "
            "FROM events e LEFT JOIN genres g ON g.genre_id = e.genre_id "
            "WHERE e.venue_id = %s "
            "ORDER BY (e.event_date < %s), "
            "         CASE WHEN e.event_date >= %s THEN e.event_date END, "
            "         e.event_date DESC, e.start_time NULLS LAST, e.event_id "
            "LIMIT %s OFFSET %s",
            (venue_id, day, day, limit, offset),
        )
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def venue_event_groups(con, venue_id: int, *, today=None) -> list[dict[str, Any]]:
    """A venue's events with each repeating event shown once (v0.87.0).

    Same venue (it is one venue's list), same title and same weekday of the
    real event_date make one group. "Same title" is the project's own
    normalization.name_key() - NFKC, dates/weekday words and decoration
    removed, the same key series_key() groups a weekly milonga by - never a
    fuzzy similarity: "Friday Milonga" and "Friday Special Milonga" stay two
    groups. A title that normalizes to nothing is never merged with anything.

    Each group is its latest occurrence (date, then start time, then
    event_id) with the number of events in it. Groups are ordered like the
    events used to be - upcoming soonest-first, then past most-recent-first -
    by that latest occurrence. Grouping happens over *every* linked event
    before any paging, so a repeating event can never push another group off
    a page.
    """
    from datetime import time as time_type

    from . import events_api, normalization  # local: both import this module's callers

    day = today or events_api.today()
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in venue_events(con, venue_id, limit=None, offset=0, today=day):
        key = normalization.name_key(row.get("event_name"))
        group = (row["event_date"].weekday(), key) if key else ("event", row["event_id"])
        grouped.setdefault(group, []).append(row)
    groups = []
    for members in grouped.values():
        latest = max(members, key=lambda r: (r["event_date"], r.get("start_time") or time_type.min,
                                             r["event_id"]))
        groups.append({**latest, "occurrences": len(members),
                       "first_date": min(r["event_date"] for r in members)})
    groups.sort(key=lambda g: (g["event_date"] < day, abs((g["event_date"] - day).days),
                               g.get("start_time") or time_type.min, g["event_id"]))
    return groups
