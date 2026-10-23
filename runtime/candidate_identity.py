"""Which re-extracted candidate is which existing one (v0.96.53).

Events are keyed on the engine's candidate_id (`normalization.normalize_candidate`
upserts ON CONFLICT (candidate_id)), so an Event keeps its id exactly as long
as its candidate does. v0.96.0 re-read a post *into the candidate it already
had* only in the one-before/one-after shape; every other post had its
candidates deleted and inserted afresh. On the v0.96.52 ENGINE 1.17 probe that
gave 99 Events new ids, and 95 of them were the same programme on the same
date under the same title: a festival's five days, a club's four Chuseok
nights, re-read and re-numbered.

This module pairs a post's stored candidates with the ones the engine has just
produced, by what the programme *is* - never by its position in either list:

    EXACT     date, title, type, start, end and venue all unchanged
    REVISED   same date, and the same title or the same type and start clock,
              with the other fields corrected

Each tier only pairs one stored candidate with one new candidate. A key shared
by more than one on either side is not guessed at: those candidates take no
part in any later tier, the stored ones are retired and the new ones get new
ids - exactly the pre-v0.96.53 behaviour, now counted as AMBIGUOUS (one stored,
several new) or CONFLICTING (several stored, one new) instead of hidden. A
date change is never a match here; a programme that moved day is a different
programme until a person says otherwise. (The one-before/one-after shape keeps
its v0.96.0 contract and is handled by the caller before this is reached.)

Pure function of its inputs: the same two lists give the same pairing in any
order, so a retry or a re-run cannot move an identity.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable

from .normalization import name_key

MATCH_EXACT = "MATCH_EXACT"
MATCH_REVISED = "MATCH_STABLE_WITH_REVISIONS"
NEW_EVENT = "NEW_EVENT"
REMOVED = "EXPLICITLY_REMOVED"
AMBIGUOUS = "AMBIGUOUS_IDENTITY"
CONFLICTING = "CONFLICTING_IDENTITY"


def _clock(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:5] or None


def _text(value: Any) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def _fields(date: Any, name: Any, event_type: Any, start: Any, end: Any,
            venue: Any) -> dict[str, Any]:
    return {
        "date": str(date)[:10] if date else None,
        "stem": name_key(name) or None,
        "type": _text(event_type),
        "start": _clock(start),
        "end": _clock(end),
        "venue": _text(venue),
    }


def stored_fields(row: Any) -> dict[str, Any]:
    """An `event_candidates` row (mapping or sqlite3.Row)."""
    return _fields(row["event_date"], row["name"], row["event_type"],
                   row["start_time"], row["end_time"], row["venue"])


def extracted_fields(ev: Any) -> dict[str, Any]:
    """An engine EventCandidate as `process_discovered_post()` returns it."""
    return _fields(getattr(ev, "date", None), getattr(ev, "name", None),
                   getattr(ev, "event_type", None), getattr(ev, "start_time", None),
                   getattr(ev, "end_time", None), getattr(ev, "venue", None))


def _key(*names: str, require: tuple[str, ...] = ()) -> Callable[[dict], tuple | None]:
    def key(f: dict) -> tuple | None:
        if f["date"] is None or any(f[n] is None for n in require):
            return None
        return tuple(f[n] for n in names)
    return key


# Finest first. Every tier keeps the date: see the module docstring.
TIERS: tuple[tuple[str, Callable[[dict], tuple | None]], ...] = (
    (MATCH_EXACT, _key("date", "stem", "type", "start", "end", "venue")),
    (MATCH_REVISED, _key("date", "stem", "type", "start", require=("stem",))),
    (MATCH_REVISED, _key("date", "stem", "type", require=("stem",))),
    (MATCH_REVISED, _key("date", "stem", require=("stem",))),
    (MATCH_REVISED, _key("date", "type", "start", require=("start",))),
)


def match(stored: Iterable[tuple[int, dict]], extracted: Iterable[dict]) -> dict[str, Any]:
    """Pair stored candidates with newly extracted ones.

    ``stored`` is ``(candidate_id, fields)``; ``extracted`` is a list of fields
    in the engine's order. Returns ``pairs`` as ``{new_index: candidate_id}``,
    ``kinds`` for every pair, the unpaired ``new`` indexes and ``removed``
    candidate ids, and per-outcome ``counts``.
    """
    old = {int(cid): f for cid, f in stored}
    new = dict(enumerate(extracted))
    pairs: dict[int, int] = {}
    kinds: dict[int, str] = {}
    held_old: dict[int, str] = {}
    held_new: dict[int, str] = {}

    for kind, key in TIERS:
        groups: dict[tuple, tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
        for cid, f in old.items():
            if cid not in pairs.values() and cid not in held_old:
                k = key(f)
                if k is not None:
                    groups[k][0].append(cid)
        for idx, f in new.items():
            if idx not in pairs and idx not in held_new:
                k = key(f)
                if k is not None:
                    groups[k][1].append(idx)
        for olds, news in groups.values():
            if not olds or not news:
                continue
            if len(olds) == 1 and len(news) == 1:
                pairs[news[0]] = olds[0]
                kinds[news[0]] = kind
                continue
            verdict = CONFLICTING if len(news) == 1 else AMBIGUOUS
            for cid in olds:
                held_old[cid] = verdict
            for idx in news:
                held_new[idx] = verdict

    paired_old = set(pairs.values())
    new_only = sorted(i for i in new if i not in pairs)
    removed = sorted(c for c in old if c not in paired_old)
    counts = {MATCH_EXACT: 0, MATCH_REVISED: 0, NEW_EVENT: 0, REMOVED: 0,
              AMBIGUOUS: 0, CONFLICTING: 0}
    for kind in kinds.values():
        counts[kind] += 1
    for idx in new_only:
        counts[held_new.get(idx, NEW_EVENT)] += 1
    for cid in removed:
        if cid not in held_old:
            counts[REMOVED] += 1
    return {"pairs": pairs, "kinds": kinds, "new": new_only, "removed": removed,
            "held": {"old": held_old, "new": held_new}, "counts": counts}
