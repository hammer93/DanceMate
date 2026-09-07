"""Source Priority (v0.85.0): which source a reader should trust most.

Not a new field, not a new enum stored anywhere - derived, at read time,
from the ``sources.source_role`` column that has existed since v0.75
(``migrations/runtime/003_source_intake.sql``). Three tiers, in the order
Private Alpha wants a representative source picked:

    PRIMARY          the thing itself, talking about itself: an organiser's
                      own account (ORGANIZER), a venue's own account
                      (VENUE), or a dance community's own board about its
                      own events (COMMUNITY).
    PROMOTION_BOARD   a bulletin board that carries other groups'
                      announcements (PROMOTION_BOARD) - a real, useful
                      middle tier, not a fallback.
    DIRECTORY         a listing that has recompiled other sources' events
                      (DIRECTORY, AGGREGATOR) - real coverage, never hidden,
                      never the tiebreak winner over a more direct source.

This is a display/ranking signal only. It has no bearing on
``engine.verifier.ACCEPTABLE_SOURCE_ROLES`` or VERIFIED status (Section 8) -
those stay exactly as strict as they already are, and an unmapped or unknown
role is a deliberately safe DIRECTORY, never PRIMARY: a role we do not
recognise has not earned a reader's trust by default.
"""

from __future__ import annotations

PRIMARY = "PRIMARY"
PROMOTION_BOARD = "PROMOTION_BOARD"
DIRECTORY = "DIRECTORY"

TIERS = (PRIMARY, PROMOTION_BOARD, DIRECTORY)

# A person's-worth label for a reader, never the internal enum itself
# (Section 25: badges stay small and few).
TIER_LABELS = {
    PRIMARY: "공식",
    PROMOTION_BOARD: "홍보게시판",
    DIRECTORY: "일정모음",
}

_RANK = {tier: index for index, tier in enumerate(TIERS)}

# sources.source_role values (runtime/sources.py's SOURCE_ROLES), grouped by
# what they mean about the source's relationship to the event, not by
# guessing at any one source's reputation.
_PRIMARY_ROLES = {"ORGANIZER", "VENUE", "COMMUNITY"}
_PROMOTION_ROLES = {"PROMOTION_BOARD"}
# DIRECTORY, AGGREGATOR, and anything unrecognised all land here - the safe
# default tier when a role does not clearly claim to be the event's own
# source.
_DIRECTORY_ROLES = {"DIRECTORY", "AGGREGATOR"}


def tier_of(source_role: str | None) -> str:
    """The priority tier for a ``sources.source_role`` value."""
    role = (source_role or "").strip().upper()
    if role in _PRIMARY_ROLES:
        return PRIMARY
    if role in _PROMOTION_ROLES:
        return PROMOTION_BOARD
    return DIRECTORY


def rank(source_role: str | None) -> int:
    """Lower is more direct - sortable, e.g. ``ORDER BY``-style tiebreaks."""
    return _RANK[tier_of(source_role)]


def label_of(source_role: str | None) -> str:
    return TIER_LABELS[tier_of(source_role)]
