"""Genre-aware search query profiles for direct sources (v0.95.0).

A NAVER_CAFE / DAUM_CAFE source collects through a provider's search API,
so what it finds is bounded by the words it searches for. v0.94.0 proposed
every community source with the same three suffixes (정모 / 파티 / 공지),
which is far narrower than how Korean dance communities actually title
their posts: a tango cafe announces a 밀롱가 or a 프락티카, a swing cafe a
소셜, a salsa cafe a 바차타 나이트 - and an organizer's own class notice is
an 오픈클래스 or a 원데이. Every profile below is a list of those words per
canonical genre code; a genre the profiles do not know falls back to the
generic community vocabulary rather than to nothing.

The profile is the *default* a proposal starts from. ``sources.queries`` is
the per-source list an operator can edit on the Sources screen, and
``queries_for(..., extra=...)`` merges an operator's own words in front of
the profile, deduplicated, so a source-specific term never has to be typed
into code. Every query is anchored on the community's own distinctive name
(``core_name``) - "OSIK 밀롱가", not a bare "밀롱가" that would pull every
cafe on Naver through the boundary filter - and the list is capped so one
collection never costs more than ``MAX_QUERIES`` provider calls.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# Per-genre words, most characteristic first. Kept short on purpose: each
# entry is one provider call per collection.
QUERY_PROFILES: dict[str, tuple[str, ...]] = {
    "TANGO": ("밀롱가", "프락티카", "탱고", "정모", "워크샵", "클래스", "번개"),
    "SALSA": ("살사", "파티", "정모", "바차타", "소셜", "클래스", "강습", "번개"),
    "BACHATA": ("바차타", "살사", "파티", "소셜", "정모", "클래스", "강습"),
    "SWING": ("스윙", "소셜", "파티", "정모", "린디합", "발보아", "클래스", "강습"),
    "BALBOA": ("발보아", "스윙", "소셜", "파티", "정모", "클래스"),
    "KIZOMBA": ("키좀바", "파티", "소셜", "정모", "클래스", "강습"),
}
# What every dance community calls its own gatherings, genre or no genre.
DEFAULT_PROFILE: tuple[str, ...] = ("정모", "파티", "공지", "모임", "소셜", "클래스")

MAX_QUERIES = 8
QUERY_MAX_LEN = 40

# Words that say nothing about *which* community this is.
_GENERIC_WORDS = ("동호회", "모임", "커뮤니티", "동아리", "카페", "클럽", "club", "cafe", "댄스",
                  "dance", "공식", "정식", "소셜", "social", "korea", "코리아", "한국", "스튜디오",
                  "홈페이지", "게시판", "초보", "20-30대", "2030")
# Cities with their own Region row, whose names never reach REGION_HINTS
# (community_discovery keeps those for province-level resolution).
_CITY_WORDS = ("청주", "진주", "창원", "포항", "울산", "대구", "제주", "인천", "부산", "대전",
               "광주", "세종", "전주", "여수", "천안", "수원", "성남", "일산", "홍대", "강남")
_BRACKETED = re.compile(r"[\[\(【][^\]\)】]*[\]\)】]")
_EDGE = re.compile(r"^[\W_]+|[\W_]+$")


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").split()).lower()


def profile_for(genre_code: str | None) -> tuple[str, ...]:
    """The words for a canonical genre code; the generic set for any other."""
    return QUERY_PROFILES.get((genre_code or "").strip().upper(), DEFAULT_PROFILE)


def core_name(name: str | None) -> str | None:
    """The part of a community's name that identifies it: region, genre and
    'club' words stripped ("홍대 탱고 동호회 OSIK" -> "OSIK", "진주 라틴 피루나
    댄스" -> "라틴 피루나"). None when nothing distinctive is left - a name
    made only of generic words anchors no query."""
    from . import community_discovery as cd  # noqa: PLC0415 - word lists live there

    if not name:
        return None
    text = _BRACKETED.sub(" ", unicodedata.normalize("NFKC", name))
    words: list[str] = list(_GENERIC_WORDS) + list(_CITY_WORDS)
    words += [w for ws in cd.GENRE_WORDS.values() for w in ws]
    words += [w for ws in cd.REGION_HINTS.values() for w in ws]
    for word in sorted(set(words), key=len, reverse=True):
        text = re.sub(re.escape(word), " ", text, flags=re.IGNORECASE)
    core = " ".join(_EDGE.sub("", part) for part in text.split() if _EDGE.sub("", part))
    core = " ".join(core.split())
    return core if len(core) >= 2 else None


def queries_for(genre_code: str | None, *, name: str | None = None,
                region_name: str | None = None, extra: Iterable[str] = (),
                limit: int = MAX_QUERIES) -> list[str]:
    """The search queries a source should run, in priority order.

    Anchored on the community's own name when one is known (the cafe/URL
    boundary keeps precision; the name keeps recall on that cafe's posts).
    Without a name - a region-wide search source - the region name prefixes
    each genre word instead. Operator ``extra`` words come first and are
    never dropped by the cap; duplicates (after NFKC/case/space
    normalisation) collapse to their first occurrence.
    """
    anchor = core_name(name) if name else None
    terms = profile_for(genre_code)
    ordered: list[str] = [str(q).strip() for q in extra if str(q).strip()]
    if anchor:
        ordered.append(anchor)
        ordered += [f"{anchor} {term}" for term in terms]
    elif region_name:
        ordered += [f"{region_name.strip()} {term}" for term in terms]
    else:
        ordered += list(terms)
    out: list[str] = []
    seen: set[str] = set()
    for query in ordered:
        query = " ".join(query.split())[:QUERY_MAX_LEN]
        key = normalize(query)
        if key and key not in seen:
            seen.add(key)
            out.append(query)
    kept_extra = len([q for q in extra if str(q).strip()])
    return out[:max(limit, min(kept_extra, len(out)))]


def merge_queries(existing: Iterable[str], proposed: Iterable[str],
                  limit: int = MAX_QUERIES) -> list[str]:
    """An operator's current list first, then the profile's additions -
    nothing the operator wrote is removed."""
    current = [str(q).strip() for q in existing if str(q).strip()]
    merged = list(current)
    seen = {normalize(q) for q in current}
    for query in proposed:
        key = normalize(query)
        if key and key not in seen:
            seen.add(key)
            merged.append(query)
    return merged[:max(limit, len(current))]
