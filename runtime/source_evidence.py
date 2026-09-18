"""Event Evidence Priority (v0.94.0): which of an Event's posts represents it.

Distinct from ``source_priority`` (the three reader-facing tiers a source's
``source_role`` maps to) and from ``sources.authority_level`` (what an
operator asserted about a source's relationship to its subject). Neither of
those alone says which *post* should stand for an Event once the same night
has been found by several sources - an organizer's own board, a promotion
board, a directory that re-lists everything. This module ranks one piece of
evidence, derived at read time from columns that already exist; nothing here
is stored as a new enum.

    PRIMARY_ORGANIZER    the organizer's/community's own post, from a source
                          the operator marked PRIMARY_ORGANIZER
    OFFICIAL_ORGANIZER   an organizer's/community's own account or board
                          whose authority has not (yet) been confirmed
    OFFICIAL_VENUE       the venue's own account or board
    COMMUNITY_PROMOTION  a promotion board, or any community post that its
                          own text/board marks as someone else's promotion
                          (``external_promotion``) - real, direct evidence
                          that a night exists, never the organizer speaking
    AGGREGATOR           a directory/aggregator that re-lists other sources
                          (Miltang, TangoNOW, ...) - coverage and fallback
    SEARCH_DISCOVERY     a search API snippet from an aggregate/search source

``external_promotion`` is a hard ceiling, not a tiebreak: a Busan cafe
sharing a Seoul organizer's night is COMMUNITY_PROMOTION however the cafe's
own source is configured, so the existing PRIMARY_ORGANIZER protections
(Region inheritance, structure trust) are never reached through a shared
post. An unrecognised role lands at the bottom - unknown evidence has not
earned the representative slot by default.
"""

from __future__ import annotations

PRIMARY_ORGANIZER = "PRIMARY_ORGANIZER"
OFFICIAL_ORGANIZER = "OFFICIAL_ORGANIZER"
OFFICIAL_VENUE = "OFFICIAL_VENUE"
COMMUNITY_PROMOTION = "COMMUNITY_PROMOTION"
AGGREGATOR = "AGGREGATOR"
SEARCH_DISCOVERY = "SEARCH_DISCOVERY"

CLASSES = (PRIMARY_ORGANIZER, OFFICIAL_ORGANIZER, OFFICIAL_VENUE, COMMUNITY_PROMOTION,
           AGGREGATOR, SEARCH_DISCOVERY)

LABELS = {
    PRIMARY_ORGANIZER: "주최 공식",
    OFFICIAL_ORGANIZER: "주최/동호회",
    OFFICIAL_VENUE: "장소 공식",
    COMMUNITY_PROMOTION: "홍보/공유",
    AGGREGATOR: "일정모음",
    SEARCH_DISCOVERY: "검색 결과",
}

_RANK = {cls: index for index, cls in enumerate(CLASSES)}

_ORGANIZER_ROLES = frozenset({"ORGANIZER", "COMMUNITY"})
_VENUE_ROLES = frozenset({"VENUE"})
_PROMOTION_ROLES = frozenset({"PROMOTION_BOARD"})
_LISTING_ROLES = frozenset({"DIRECTORY", "AGGREGATOR"})
# Platforms whose items are search-API snippets rather than a page of the
# source's own (runtime/collectors.py's engine-collector platforms).
_SEARCH_PLATFORMS = frozenset({"NAVER_BLOG", "NAVER_WEB", "NAVER_CAFE", "DAUM_CAFE"})


def classify(source_role: str | None, authority_level: str | None = None,
             platform: str | None = None, external_promotion: bool = False) -> str:
    """The evidence class of one post, from its source's columns."""
    role = (source_role or "").strip().upper()
    authority = (authority_level or "").strip().upper()
    if external_promotion and role in _ORGANIZER_ROLES | _VENUE_ROLES | _PROMOTION_ROLES:
        return COMMUNITY_PROMOTION
    if role in _ORGANIZER_ROLES:
        return PRIMARY_ORGANIZER if authority == "PRIMARY_ORGANIZER" else OFFICIAL_ORGANIZER
    if role in _VENUE_ROLES:
        return OFFICIAL_VENUE
    if role in _PROMOTION_ROLES:
        return COMMUNITY_PROMOTION
    if role in _LISTING_ROLES:
        return SEARCH_DISCOVERY if (platform or "").upper() in _SEARCH_PLATFORMS else AGGREGATOR
    return SEARCH_DISCOVERY


def rank(evidence_class: str) -> int:
    """Lower is more direct."""
    return _RANK.get(evidence_class, len(CLASSES))


def label_of(evidence_class: str) -> str:
    return LABELS.get(evidence_class, evidence_class)


def is_direct(evidence_class: str) -> bool:
    """Evidence from the night's own organizer or venue - what a reader
    should be sent to first when it exists."""
    return evidence_class in (PRIMARY_ORGANIZER, OFFICIAL_ORGANIZER, OFFICIAL_VENUE)
