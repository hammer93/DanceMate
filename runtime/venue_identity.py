"""Whether two statements about a place can be about the same place.

A venue's identity is not its name. `Tango O Nada` names a basement in 서울
마포구 and also one in 대전 유성구, and in October 2026 an alias for the first
answered for the second: two Daejeon milongas were listed in Seoul, and the
real Seoul milongas sharing their hour were folded away as duplicates of them.

The reading that caused it is fixed where it was made (the engine kept reading
past the city word in the post's own `장소` field). This module is the second
line: a *name* match that the places' own words contradict is refused, so the
same shape of mistake cannot reach a user through some other alias.

What counts as a contradiction is deliberately the narrowest thing that is
always true. A metropolitan city contains no other first-level unit and is
contained by none, so two different ones named in two statements cannot both
be right. Provinces are not here: 창원 lies inside 경남 and 포항 inside 경북,
and this project registers those cities as regions of their own - comparing a
province word against a city region would read a correct venue as a conflict.
Nothing here assigns a region; it only ever declines to assert one.
"""

from __future__ import annotations

import re
from typing import Any

#: The metropolitan cities, by the region code this project gives each one.
#: 세종 carries no registered region yet; keeping its word here costs nothing
#: and means a Sejong address already contradicts a Seoul venue.
METRO_CODES: dict[str, str] = {
    "KR-SEOUL": "서울",
    "KR-BUSAN": "부산",
    "KR-DAEGU": "대구",
    "KR-INCHEON": "인천",
    "KR-GWANGJU": "광주",
    "KR-DAEJEON": "대전",
    "KR-ULSAN": "울산",
    "KR-SEJONG": "세종",
}

# The word, optionally in its full administrative form ("대전광역시"), as its
# own token: `동광주` and `광주요` are not the city, and `서울대입구` is a
# subway station. A following administrative suffix is part of the word.
_METRO_RE = re.compile(
    "(?<![가-힣])(?:" + "|".join(METRO_CODES.values()) + r")(?:특별시|광역시|특별자치시|시)?"
    r"(?![가-힣])"
)
_WORD_TO_CODE = {word: code for code, word in METRO_CODES.items()}


def stated_metros(text: str | None) -> set[str]:
    """The metropolitan cities this text's own words name, as region codes."""
    found = set()
    for match in _METRO_RE.finditer(text or ""):
        word = re.sub(r"(?:특별시|광역시|특별자치시|시)$", "", match.group(0))
        code = _WORD_TO_CODE.get(word)
        if code:
            found.add(code)
    return found


def texts_contradict(left: str | None, right: str | None) -> bool:
    """Whether two place statements name metropolitan cities that exclude
    each other.

    False whenever either says nothing, and false when they overlap at all: a
    post naming a guest DJ's home city beside its own venue names two, and one
    of them is this event's.
    """
    one, other = stated_metros(left), stated_metros(right)
    if not one or not other:
        return False
    return not (one & other)


def region_conflict(con, venue: dict[str, Any], *texts: str | None) -> bool:
    """Whether a matched venue sits in a metropolis the post's words exclude.

    ``venue`` is a Venue Master row. Only a venue whose own region is a
    metropolis can conflict: for anything else there is no statement to
    contradict that would not be a guess about administrative hierarchy.
    """
    region_id = venue.get("region_id")
    if region_id is None:
        return False
    with con.cursor() as cur:
        cur.execute("SELECT code FROM regions WHERE region_id = %s", (region_id,))
        row = cur.fetchone()
    code = row[0] if row else None
    if code not in METRO_CODES:
        return False
    said: set[str] = set()
    for text in texts:
        said |= stated_metros(text)
    return bool(said) and code not in said
