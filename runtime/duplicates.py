"""Duplicate Resolution: the same milonga posted four times, shown once.

A venue posts it, the organiser posts it, two dancers post it. Four rows for
one Saturday night is a worse answer than one row -- and one row for two
different milongas is worse than four.

So the rules are deterministic and narrow. Auto-merge needs all three of:

    the same date, the same place, and the same start time

with the place being a *resolved* Venue Master row and the time actually
present on both sides. Anything less specific -- same venue but two hours
apart, same time but one venue unknown, same words for a venue nothing has
resolved -- is an open question recorded for a person. There is no similarity
score and no clustering: a number nobody can check is not a reason to merge
two events.

v0.96.23 (distinct same-time parties): an identical *unresolved* venue string
used to count as the same place, and it is not one. DanceInfo attached a
single poster's Instagram handle -- OCR'd as "@ 스스 me1" -- to eighteen
listings, so a Gwangju party and an Incheon party at 21:00 on the same
Saturday read as the same venue and one of them was folded away from every
reader. The date and the clock were never able to tell two parties apart on
their own; the place was the third thing, and words nobody has resolved to a
place are not it. Such a pair now goes to a person (``RULE_UNRESOLVED_VENUE_TIME``)
instead of being merged -- it is not evidence the events differ either, since
two posts about one milonga often spell an unresolved venue identically.
Nothing about a resolved venue changed, and each scan now re-asks its own
automatic merges so a corrected rule reaches rows already folded under the
old one (``_release_stale_auto_merges``).

Nothing is deleted. A duplicate keeps its row, its candidate, its source URL,
and points at the canonical event, so "which posts said this?" still has an
answer afterwards.

A person's decision is final. Automation skips any event a human has ruled on,
in either direction, and re-running the scan never revisits it.

v0.94.0 (Event Source Evidence): which row is canonical and which post
represents the event are two different questions now. The canonical row is
the most complete one, then the oldest - the incumbent keeps its id when a
later post of the same night arrives. The representative is
``events.primary_source_item_id``, elected across the whole group (canonical
plus every folded duplicate) by ``source_evidence`` priority, so an
organizer's own post found after a directory listing becomes what a reader is
sent to without the directory row losing its id or its place as retained
evidence. A HUMAN choice of representative outlasts every later scan.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from . import source_evidence, source_priority

AUTO = "AUTO"
HUMAN = "HUMAN"

DUPLICATE = "DUPLICATE"
DISTINCT = "DISTINCT"

# Auto-merge: every identifying field agrees and none of them is missing.
RULE_SAME_DATE_VENUE_TIME = "SAME_DATE_VENUE_TIME"
# For a person: enough agrees to be suspicious, not enough to act.
RULE_VENUE_TIME_DIFFERS = "SAME_DATE_VENUE_TIME_DIFFERS"
RULE_TIME_NAME_VENUE_DIFFERS = "SAME_DATE_TIME_NAME_VENUE_DIFFERS"
# v0.96.23: the date and the clock agree and both posts write the same venue
# words, but neither of those words has been resolved to a place.
RULE_UNRESOLVED_VENUE_TIME = "SAME_DATE_UNRESOLVED_VENUE_TIME"
# v0.96.23: an automatic merge the rules would no longer make, released.
RULE_STALE_AUTO_MERGE = "STALE_AUTO_MERGE"

OPEN = "OPEN"
MERGED = "MERGED"


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _row(cur) -> dict[str, Any] | None:
    names = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(names, row))


def completeness(event: dict[str, Any]) -> int:
    """How much of an event this row actually carries.

    A tiebreak within one evidence class when the representative source is
    elected (``reconcile_primary_source``), and a number the Admin shows
    beside each post. v0.94.0: it no longer decides which row is canonical -
    an Event's id is identity, not a prize for the fullest post - and it was
    never a reason to merge.
    """
    score = 0
    if event.get("venue_status") == "RESOLVED":
        score += 3
    elif event.get("venue_text"):
        score += 1
    if event.get("start_time"):
        score += 1
    if event.get("end_time"):
        score += 1
    if event.get("fee") is not None:
        score += 1
    if (event.get("engine_status") or "").upper() == "VERIFIED":
        score += 1
    if (event.get("review_state") or "").upper() in ("APPROVED", "CONFIRMED", "EDITED"):
        score += 2
    return score


def _canonical_of(left: dict[str, Any], right: dict[str, Any]) -> tuple[dict, dict]:
    """(canonical, duplicate). Identity only, never quality: the row that
    already heads a group (``folded_count`` > 0, when the caller joined it
    in), else the older ``event_id`` - the id that existed first.

    v0.94.0 (stable Event identity): an Event's id is the one thing a later
    discovery must not change. Source directness (the v0.85.0 tiebreak) and
    field completeness (the v0.77 rule) both used to decide which *row*
    survived, so an organizer's fuller post arriving after a directory
    listing took over the listing's row and its public id. Neither is a
    reason any more: directness elects the representative *source*
    (``reconcile_primary_source``) and completeness is what a folded post
    lends the canonical row through ``events_api``'s NULL-only fill - both
    across the whole group, both without moving the id. ``event_id`` is a
    BIGSERIAL, so "older" is exactly "existed first"; a row that already
    has duplicates folded under it is kept as the root so no chain forms.
    """
    ranked = sorted((left, right),
                    key=lambda e: (-(int(e.get("folded_count") or 0) > 0), e["event_id"]))
    return ranked[0], ranked[1]


def _place(event: dict[str, Any]) -> str | None:
    if event.get("venue_id") is not None:
        return f"venue:{event['venue_id']}"
    text = (event.get("venue_text") or "").strip().lower()
    return f"text:{text}" if text else None


def _place_is_known(event: dict[str, Any]) -> bool:
    """Whether we actually know where this event is.

    A resolved Venue Master row is knowledge: somebody matched that string to
    a place, and every other spelling of it resolves to the same id. An
    unresolved string is only the words a post used. Two posts using the same
    words is not the same fact as two posts naming the same place - the words
    may not be a place at all.
    """
    return event.get("venue_id") is not None


def _clock(event: dict[str, Any]) -> str | None:
    value = event.get("start_time")
    return value.strftime("%H:%M") if hasattr(value, "strftime") else (str(value)[:5] or None)


def classify(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """What, if anything, these two events have in common.

    Returns None when they are simply different events -- including the case
    that matters most for a weekly milonga: two instances of one series on two
    dates are not duplicates, however identical everything else looks.
    """
    if left["event_date"] != right["event_date"]:
        return None

    left_place, right_place = _place(left), _place(right)
    left_clock, right_clock = _clock(left), _clock(right)
    same_place = bool(left_place) and left_place == right_place
    same_clock = bool(left_clock) and left_clock == right_clock

    if same_place and same_clock:
        if _place_is_known(left) and _place_is_known(right):
            return {
                "rule": RULE_SAME_DATE_VENUE_TIME,
                "auto": True,
                "matched": ["event_date", "venue", "start_time"],
                "differs": [],
            }
        # v0.96.23: same night, same clock, same venue *words* - and nothing
        # knows what place those words are. Found on two real parties 300km
        # apart: DanceInfo attached one poster's Instagram handle, OCR'd as
        # "@ 스스 me1", to eighteen listings, so a Gwangju party and an
        # Incheon party read as the same unresolved venue at 21:00 on the
        # same Saturday and one of them stopped being shown to anybody.
        #
        # The place is the whole reason two posts about one night may be
        # collapsed: date and clock alone cannot tell two parties apart,
        # which is why this rule has always needed all three. An unresolved
        # string is not the third thing. It is not evidence the events are
        # different either - two posts about one milonga often spell its
        # venue identically without it ever being resolved - so this is a
        # question for a person, which is what the rules already do with
        # everything they cannot settle outright, and not a merge.
        return {
            "rule": RULE_UNRESOLVED_VENUE_TIME,
            "auto": False,
            "matched": ["event_date", "start_time", "venue_text"],
            "differs": ["venue_status"],
        }
    if same_place:
        return {
            "rule": RULE_VENUE_TIME_DIFFERS,
            "auto": False,
            "matched": ["event_date", "venue"],
            "differs": ["start_time"],
        }
    if same_clock and left.get("series_key") and left["series_key"] == right.get("series_key"):
        return {
            "rule": RULE_TIME_NAME_VENUE_DIFFERS,
            "auto": False,
            "matched": ["event_date", "start_time", "series_key"],
            "differs": ["venue"],
        }
    return None


def _decided_by_human(event: dict[str, Any]) -> bool:
    return (event.get("duplicate_decided_by") or "").upper() == HUMAN


def record_decision(con, *, event_id: int, canonical_event_id: int | None,
                    decision: str, decided_by: str, rule: str,
                    reason: str | None = None, reviewer: str | None = None) -> dict[str, Any]:
    """Write one duplicate verdict and update the event to match it."""
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO event_duplicate_decisions (event_id, canonical_event_id, "
            "  decision, decided_by, rule, reason, reviewer) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (event_id, canonical_event_id, decision, decided_by, rule, reason, reviewer),
        )
        recorded = _row(cur)
        if decision == DUPLICATE:
            if canonical_event_id is not None:
                # v0.91.0 PHASE 6 (corrected): the losing row's own explicit
                # genre relations (event_genres) would otherwise become
                # unreachable the moment it is hidden - nothing queries a
                # HIDDEN/non-canonical row's genres again. Union them onto
                # the survivor before hiding it, origin preserved - never
                # inferred, only ever copied from a relation that already
                # existed. HUMAN must dominate AUTO on conflict, in either
                # direction: a HUMAN-confirmed genre is a real, confirmed
                # fact regardless of which side of the merge it came from,
                # and merging must never quietly downgrade one survivor's
                # already-HUMAN row back to AUTO just because the loser only
                # had it as AUTO (the WHERE guard below is what stops that -
                # it only fires when the loser's copy is HUMAN and the
                # survivor's existing row is still AUTO).
                cur.execute(
                    "INSERT INTO event_genres (event_id, genre_id, origin) "
                    "SELECT %s, genre_id, origin FROM event_genres WHERE event_id = %s "
                    "ON CONFLICT (event_id, genre_id) DO UPDATE SET origin = 'HUMAN' "
                    "WHERE event_genres.origin = 'AUTO' AND EXCLUDED.origin = 'HUMAN'",
                    (canonical_event_id, event_id),
                )
            cur.execute(
                "UPDATE events SET canonical_event_id = %s, duplicate_decided_by = %s, "
                "  listing_state = 'HIDDEN', updated_at = now() WHERE event_id = %s",
                (canonical_event_id, decided_by, event_id),
            )
        else:
            cur.execute(
                "UPDATE events SET canonical_event_id = NULL, duplicate_decided_by = %s, "
                "  listing_state = CASE WHEN review_state IN ('REJECTED', 'DUPLICATE') "
                "                       THEN 'HIDDEN' ELSE 'LISTED' END, "
                "  updated_at = now() WHERE event_id = %s",
                (decided_by, event_id),
            )
    # v0.94.0: the group just changed shape, so its representative source is
    # re-elected - for the survivor after a merge, and for a row that has
    # just been ruled DISTINCT (its own post is once again all it has).
    if decision == DUPLICATE and canonical_event_id is not None:
        reconcile_primary_source(con, canonical_event_id)
    else:
        reconcile_primary_source(con, event_id)
    return recorded


def _record_pair(con, left_id: int, right_id: int, finding: dict[str, Any]) -> bool:
    """Park an ambiguous pair for a person. Returns True if it is new."""
    low, high = sorted((left_id, right_id))
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO event_duplicate_pairs (event_id, other_event_id, rule, "
            "  matched, differs) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb) "
            "ON CONFLICT (event_id, other_event_id) DO NOTHING RETURNING pair_id",
            (low, high, finding["rule"],
             json.dumps(finding["matched"]), json.dumps(finding["differs"])),
        )
        return cur.fetchone() is not None


def _release_stale_auto_merges(con, events: list[dict[str, Any]]) -> list[int]:
    """Undo automatic merges the rules would no longer make.

    The fold graph is meant to be what the rules say about the rows as they
    are now, plus whatever a person has decided. Without this it is instead a
    record of what the rules said on the day each merge happened: correcting a
    rule changes nothing that has already been folded, and the event a wrong
    merge hid stays hidden for as long as the row lives.

    So each automatic merge is re-asked, once per scan, and released when the
    answer has changed - exactly what ``venue_resolution`` already does when
    the venue a merge rested on is taken away, and for the same reason: a
    merge that no longer follows from anything is not a merge.

    A person's verdict is never re-asked. A canonical row outside this scan's
    own window is not judged either, because the pair cannot be compared
    without it; the next unwindowed scan reaches it.
    """
    by_id = {e["event_id"]: e for e in events}
    released: list[int] = []
    for event in events:
        canonical_id = event.get("canonical_event_id")
        if canonical_id is None or _decided_by_human(event):
            continue
        canonical = by_id.get(canonical_id)
        if canonical is None:
            continue
        finding = classify(canonical, event)
        if finding is not None and finding["auto"]:
            continue
        record_decision(
            con,
            event_id=event["event_id"],
            canonical_event_id=None,
            decision=DISTINCT,
            decided_by=AUTO,
            rule=RULE_STALE_AUTO_MERGE,
            reason=("the rules no longer merge this pair: "
                    + (finding["rule"] if finding else "nothing matches")),
        )
        event["canonical_event_id"] = None
        event["duplicate_decided_by"] = AUTO
        event["listing_state"] = (
            "HIDDEN" if (event.get("review_state") or "").upper() in ("REJECTED", "DUPLICATE")
            else "LISTED"
        )
        # The group it left is one member smaller: its representative post is
        # re-elected, and _canonical_of() must not still believe it heads a
        # group it no longer does.
        canonical["folded_count"] = max(0, int(canonical.get("folded_count") or 0) - 1)
        reconcile_primary_source(con, canonical_id)
        released.append(event["event_id"])
    return released


def scan(con, *, on: date | None = None, limit_days: int | None = None) -> dict[str, Any]:
    """Compare events sharing a date and act on what the rules can settle.

    Only events on the same day are ever compared, so the scan stays cheap and
    a weekly series can never collapse into one row.

    v0.96.23: the pass begins by releasing automatic merges the rules would no
    longer make (``_release_stale_auto_merges``), so a corrected rule reaches
    rows that were folded under the old one instead of only new arrivals.
    """
    where = ["e.review_state <> 'REJECTED'"]
    params: list[Any] = []
    if on is not None:
        where.append("e.event_date = %s")
        params.append(on)
    elif limit_days is not None:
        where.append("e.event_date >= current_date - %s")
        params.append(limit_days)

    with con.cursor() as cur:
        cur.execute(
            # source_role is joined for the Admin's and the tests' benefit
            # (a left join: an event whose source row has since gone missing
            # still gets compared); folded_count tells _canonical_of() which
            # side already heads a group, so an established root is never
            # folded under a newcomer (v0.94.0).
            "SELECT e.*, src.source_role AS source_role, "
            "       (SELECT count(*) FROM events d WHERE d.canonical_event_id = e.event_id) "
            "         AS folded_count "
            "FROM events e "
            "LEFT JOIN source_items si ON si.source_item_id = e.source_item_id "
            "LEFT JOIN sources src ON src.source_id = si.source_id "
            "WHERE " + " AND ".join(where) +
            " ORDER BY e.event_date, e.event_id",
            tuple(params),
        )
        events = _rows(cur)

    by_date: dict[Any, list[dict[str, Any]]] = {}
    for event in events:
        by_date.setdefault(event["event_date"], []).append(event)

    # Before anything is compared: a merge the rules would not make today is
    # released, so what follows decides on the rows as they actually are.
    released = _release_stale_auto_merges(con, events)

    merged = 0
    flagged = 0
    compared = 0
    # An event already merged away is not compared again: three posts of one
    # milonga produce one canonical row, not a chain.
    resolved: set[int] = {
        e["event_id"] for e in events if e.get("canonical_event_id") is not None
    }

    for day_events in by_date.values():
        for index, left in enumerate(day_events):
            if left["event_id"] in resolved:
                continue
            for right in day_events[index + 1:]:
                if right["event_id"] in resolved:
                    continue
                compared += 1
                finding = classify(left, right)
                if finding is None:
                    continue
                if _decided_by_human(left) or _decided_by_human(right):
                    # A person has already ruled on one of these. Automation
                    # does not get a second opinion.
                    continue
                if finding["auto"]:
                    canonical, duplicate = _canonical_of(left, right)
                    record_decision(
                        con,
                        event_id=duplicate["event_id"],
                        canonical_event_id=canonical["event_id"],
                        decision=DUPLICATE,
                        decided_by=AUTO,
                        rule=finding["rule"],
                        reason="same date, same venue and same start time",
                    )
                    resolved.add(duplicate["event_id"])
                    merged += 1
                    if duplicate["event_id"] == left["event_id"]:
                        break
                elif _record_pair(con, left["event_id"], right["event_id"], finding):
                    flagged += 1

    return {"events": len(events), "compared": compared,
            "auto_merged": merged, "flagged_for_review": flagged,
            "released": len(released)}


def open_pairs(con, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Pairs waiting on a person, with both events attached."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT p.*, "
            "  a.event_name AS event_name, a.event_date AS event_date, "
            "  a.start_time AS start_time, a.venue_text AS venue_text, "
            "  a.venue_status AS venue_status, a.source_url AS source_url, "
            "  b.event_name AS other_event_name, b.start_time AS other_start_time, "
            "  b.venue_text AS other_venue_text, b.venue_status AS other_venue_status, "
            "  b.source_url AS other_source_url "
            "FROM event_duplicate_pairs p "
            "JOIN events a ON a.event_id = p.event_id "
            "JOIN events b ON b.event_id = p.other_event_id "
            "WHERE p.state = 'OPEN' ORDER BY a.event_date, p.pair_id LIMIT %s OFFSET %s",
            (limit, offset),
        )
        return _rows(cur)


def count_open_pairs(con) -> int:
    with con.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_duplicate_pairs WHERE state = 'OPEN'")
        return cur.fetchone()[0]


def resolve_pair(con, pair_id: int, *, decision: str, reviewer: str = "admin",
                 canonical_event_id: int | None = None,
                 reason: str | None = None) -> dict[str, Any]:
    """A person settles an open pair. This overrides and outlasts automation."""
    if decision not in (DUPLICATE, DISTINCT):
        raise ValueError(f"decision must be {DUPLICATE} or {DISTINCT}, got {decision!r}")
    with con.cursor() as cur:
        cur.execute("SELECT * FROM event_duplicate_pairs WHERE pair_id = %s", (pair_id,))
        pair = _row(cur)
    if pair is None:
        raise LookupError(f"no duplicate pair {pair_id}")

    members = (pair["event_id"], pair["other_event_id"])
    if decision == DUPLICATE:
        if canonical_event_id is None:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT e.*, src.source_role AS source_role, "
                    "       (SELECT count(*) FROM events d "
                    "        WHERE d.canonical_event_id = e.event_id) AS folded_count "
                    "FROM events e "
                    "LEFT JOIN source_items si ON si.source_item_id = e.source_item_id "
                    "LEFT JOIN sources src ON src.source_id = si.source_id "
                    "WHERE e.event_id = ANY(%s)", (list(members),))
                left, right = _rows(cur)
            canonical_event_id = _canonical_of(left, right)[0]["event_id"]
        if canonical_event_id not in members:
            raise ValueError("the canonical event has to be one of the pair")
        duplicate_id = members[0] if members[1] == canonical_event_id else members[1]
        record_decision(
            con, event_id=duplicate_id, canonical_event_id=canonical_event_id,
            decision=DUPLICATE, decided_by=HUMAN, rule="HUMAN_REVIEW",
            reason=reason, reviewer=reviewer,
        )
        new_state = MERGED
    else:
        for event_id in members:
            record_decision(
                con, event_id=event_id, canonical_event_id=None, decision=DISTINCT,
                decided_by=HUMAN, rule="HUMAN_REVIEW", reason=reason, reviewer=reviewer,
            )
        new_state = DISTINCT

    with con.cursor() as cur:
        cur.execute(
            "UPDATE event_duplicate_pairs SET state = %s, resolved_by = %s, "
            "  resolved_at = now() WHERE pair_id = %s",
            (new_state, reviewer, pair_id),
        )
    return {"pair_id": pair_id, "state": new_state,
            "canonical_event_id": canonical_event_id}


# --- source evidence (v0.94.0) ----------------------------------------------

_EVIDENCE_SELECT = (
    "SELECT e.event_id, e.candidate_id, e.source_item_id, e.source_url, e.event_name, "
    "       e.event_date, e.start_time, e.end_time, e.fee, e.dj, e.venue_id, e.venue_text, "
    "       e.venue_status, e.engine_status, e.review_state, e.canonical_event_id, "
    "       e.primary_source_item_id, e.primary_source_decided_by, e.primary_source_reason, "
    "       si.url AS item_url, si.collected_at, "
    "       (COALESCE(si.raw->>'external_promotion', 'false') = 'true') AS external_promotion, "
    "       src.source_id, src.source_key, src.name AS source_name, "
    "       src.platform AS source_platform, src.source_role, src.authority_level "
    "FROM events e "
    "LEFT JOIN source_items si ON si.source_item_id = e.source_item_id "
    "LEFT JOIN sources src ON src.source_id = si.source_id "
)


def canonical_id_of(con, event_id: int) -> int | None:
    """The row a reader is shown for ``event_id`` - itself, or the canonical
    row it was folded under. None when the event does not exist."""
    seen: set[int] = set()
    current = event_id
    with con.cursor() as cur:
        while current not in seen:
            seen.add(current)
            cur.execute("SELECT canonical_event_id FROM events WHERE event_id = %s", (current,))
            row = cur.fetchone()
            if row is None:
                return None if current == event_id else current
            if row[0] is None:
                return current
            current = row[0]
    return current


def _annotate(member: dict[str, Any]) -> dict[str, Any]:
    member["evidence_class"] = source_evidence.classify(
        member.get("source_role"), member.get("authority_level"),
        member.get("source_platform"), bool(member.get("external_promotion")),
    )
    member["evidence_rank"] = source_evidence.rank(member["evidence_class"])
    member["evidence_label"] = source_evidence.label_of(member["evidence_class"])
    member["source_tier"] = source_priority.tier_of(member.get("source_role"))
    member["source_tier_label"] = source_priority.label_of(member.get("source_role"))
    member["completeness"] = completeness(member)
    return member


def effective_primary_item(canonical: dict[str, Any]) -> int | None:
    """The source_item that represents a canonical row: its elected primary,
    or - the default that predates v0.94.0 - its own."""
    return canonical.get("primary_source_item_id") or canonical.get("source_item_id")


def evidence_of(con, event_id: int) -> list[dict[str, Any]]:
    """Every post behind an event - the canonical row's own and each folded
    duplicate's - classified by evidence priority, the representative first.

    Resolves ``event_id`` to its canonical row, so asking about a folded
    duplicate answers for the event a reader actually sees.
    """
    canonical_id = canonical_id_of(con, event_id)
    if canonical_id is None:
        return []
    with con.cursor() as cur:
        cur.execute(
            _EVIDENCE_SELECT + "WHERE e.event_id = %s OR e.canonical_event_id = %s "
            "ORDER BY (e.event_id = %s) DESC, e.event_id",
            (canonical_id, canonical_id, canonical_id),
        )
        members = [_annotate(m) for m in _rows(cur)]
    if not members:
        return []
    head = members[0]
    primary_item = effective_primary_item(head)
    for member in members:
        member["is_canonical"] = member["event_id"] == canonical_id
        member["is_primary"] = (member.get("source_item_id") is not None
                                and member["source_item_id"] == primary_item)
        member["decided_by"] = head.get("primary_source_decided_by")
        member["primary_reason"] = head.get("primary_source_reason")
    members.sort(key=lambda m: (not m["is_primary"], m["evidence_rank"], -m["completeness"],
                                m["event_id"]))
    return members


def _place_and_clock_agree(head: dict[str, Any], member: dict[str, Any]) -> bool:
    """A post may only represent an event whose own place and time it does not
    contradict. Missing on either side is not a contradiction; a person merged
    those, and the merge stands - but the representative stays conservative."""
    if head.get("event_date") != member.get("event_date"):
        return False
    head_place, member_place = _place(head), _place(member)
    if head_place and member_place and head_place != member_place:
        return False
    head_clock, member_clock = _clock(head), _clock(member)
    if head_clock and member_clock and head_clock != member_clock:
        return False
    return True


def _record_primary(con, event_id: int, *, source_item_id: int | None, previous: int | None,
                    evidence_class: str | None, decided_by: str, reason: str,
                    reviewer: str | None = None) -> None:
    with con.cursor() as cur:
        cur.execute(
            "UPDATE events SET primary_source_item_id = %s, primary_source_decided_by = %s, "
            "  primary_source_reason = %s, primary_source_updated_at = now(), "
            "  updated_at = now() WHERE event_id = %s",
            (source_item_id, decided_by, reason, event_id),
        )
        cur.execute(
            "INSERT INTO event_primary_source_history (event_id, source_item_id, "
            "  previous_source_item_id, evidence_class, decided_by, reason, reviewer) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (event_id, source_item_id, previous, evidence_class, decided_by, reason, reviewer),
        )


def reconcile_primary_source(con, event_id: int) -> dict[str, Any]:
    """Elect the representative post for an event's whole duplicate group.

    Rules, in order:

    * a HUMAN choice is kept as long as its post is still in the group;
    * only a post that agrees with the canonical row's own date, place and
      time is eligible (``_place_and_clock_agree``) - a directory listing and
      an organizer's post a person merged despite a differing time never
      quietly hands the badge to the one that disagrees;
    * the current representative is replaced only by a *strictly* more
      direct class (``source_evidence.rank``) - never re-shuffled between
      posts of the same class, so the badge does not churn;
    * within a class, the more complete post, then the older item, wins.

    Returns ``{"event_id", "changed", "primary_source_item_id",
    "evidence_class", "reason"}``. Never raises for an unknown event.
    """
    members = evidence_of(con, event_id)
    if not members:
        return {"event_id": event_id, "changed": False, "primary_source_item_id": None,
                "evidence_class": None, "reason": "no such event"}
    head = members[0] if members[0]["is_canonical"] else next(m for m in members if m["is_canonical"])
    canonical_id = head["event_id"]
    current_item = effective_primary_item(head)
    current = next((m for m in members if m.get("source_item_id") == current_item), None)

    if head.get("primary_source_decided_by") == HUMAN and current is not None:
        return {"event_id": canonical_id, "changed": False,
                "primary_source_item_id": current_item,
                "evidence_class": current["evidence_class"], "reason": "human decision kept"}

    eligible = [m for m in members
                if m.get("source_item_id") is not None and _place_and_clock_agree(head, m)]
    if not eligible:
        return {"event_id": canonical_id, "changed": False, "primary_source_item_id": current_item,
                "evidence_class": current["evidence_class"] if current else None,
                "reason": "no eligible evidence"}
    best = min(eligible, key=lambda m: (m["evidence_rank"], -m["completeness"],
                                        m["source_item_id"]))

    if current is not None and current in eligible and best["evidence_rank"] >= current["evidence_rank"]:
        return {"event_id": canonical_id, "changed": False, "primary_source_item_id": current_item,
                "evidence_class": current["evidence_class"],
                "reason": "current representative is at least as direct"}
    if current is not None and current not in eligible and best is current:
        return {"event_id": canonical_id, "changed": False, "primary_source_item_id": current_item,
                "evidence_class": current["evidence_class"], "reason": "no eligible replacement"}
    if best["source_item_id"] == current_item and head.get("primary_source_item_id") is None:
        # The row's own post is already the best evidence: nothing to store.
        return {"event_id": canonical_id, "changed": False, "primary_source_item_id": current_item,
                "evidence_class": best["evidence_class"], "reason": "own post is the best evidence"}

    conflicts = [m for m in members if m.get("source_item_id") is not None and m not in eligible]
    reason = (f"{best['evidence_label']} ({best['evidence_class']}) from "
              f"{best.get('source_name') or best.get('source_key') or 'unknown source'}")
    if current is not None and current is not best:
        reason += f" over {current['evidence_label']} ({current['evidence_class']})"
    if conflicts:
        reason += f"; {len(conflicts)} post(s) skipped for a differing place/time"
    stored = None if best["event_id"] == canonical_id else best["source_item_id"]
    _record_primary(con, canonical_id, source_item_id=stored, previous=current_item,
                    evidence_class=best["evidence_class"], decided_by=AUTO, reason=reason)
    return {"event_id": canonical_id, "changed": True,
            "primary_source_item_id": best["source_item_id"],
            "evidence_class": best["evidence_class"], "reason": reason}


def set_primary_source(con, event_id: int, source_item_id: int, *, reviewer: str = "admin",
                       reason: str | None = None) -> dict[str, Any]:
    """A person names the representative post. Final until reset."""
    members = evidence_of(con, event_id)
    if not members:
        raise LookupError(f"no event {event_id}")
    head = next(m for m in members if m["is_canonical"])
    chosen = next((m for m in members if m.get("source_item_id") == source_item_id), None)
    if chosen is None:
        raise ValueError("the representative has to be one of this event's own posts")
    previous = effective_primary_item(head)
    note = reason or f"chosen by {reviewer}: {chosen['evidence_label']} ({chosen['evidence_class']})"
    _record_primary(con, head["event_id"], source_item_id=source_item_id, previous=previous,
                    evidence_class=chosen["evidence_class"], decided_by=HUMAN, reason=note,
                    reviewer=reviewer)
    return {"event_id": head["event_id"], "primary_source_item_id": source_item_id,
            "evidence_class": chosen["evidence_class"], "decided_by": HUMAN}


def reset_primary_source(con, event_id: int, *, reviewer: str = "admin") -> dict[str, Any]:
    """Hand the choice back to the rules: clear a HUMAN pick, then re-elect."""
    canonical_id = canonical_id_of(con, event_id)
    if canonical_id is None:
        raise LookupError(f"no event {event_id}")
    with con.cursor() as cur:
        cur.execute("SELECT primary_source_item_id, source_item_id FROM events WHERE event_id = %s",
                    (canonical_id,))
        explicit, own = cur.fetchone()
    _record_primary(con, canonical_id, source_item_id=None, previous=explicit or own,
                    evidence_class=None, decided_by=AUTO,
                    reason=f"reset to automatic selection by {reviewer}", reviewer=reviewer)
    return reconcile_primary_source(con, canonical_id)


def primary_source_history(con, event_id: int) -> list[dict[str, Any]]:
    canonical_id = canonical_id_of(con, event_id)
    if canonical_id is None:
        return []
    with con.cursor() as cur:
        cur.execute(
            "SELECT h.*, si.url AS item_url, src.name AS source_name "
            "FROM event_primary_source_history h "
            "LEFT JOIN source_items si ON si.source_item_id = h.source_item_id "
            "LEFT JOIN sources src ON src.source_id = si.source_id "
            "WHERE h.event_id = %s ORDER BY h.history_id DESC",
            (canonical_id,),
        )
        return _rows(cur)


def sources_of(con, event_id: int) -> list[dict[str, Any]]:
    """Every post behind an event, its own and its duplicates'.

    This is what merging costs nothing: the canonical row is what a reader
    sees, and all of the provenance is still here. v0.94.0: each post also
    says which evidence class it is and whether it is the representative.
    """
    members = evidence_of(con, event_id)
    return [
        {
            "event_id": m["event_id"], "candidate_id": m["candidate_id"],
            "source_item_id": m["source_item_id"], "source_url": m["source_url"],
            "event_name": m["event_name"], "venue_text": m["venue_text"],
            "start_time": m["start_time"], "fee": m["fee"], "engine_status": m["engine_status"],
            "review_state": m["review_state"], "is_canonical": m["is_canonical"],
            "is_primary": m["is_primary"], "evidence_class": m["evidence_class"],
            "evidence_label": m["evidence_label"], "source_name": m.get("source_name"),
            "source_tier": m["source_tier"], "source_tier_label": m["source_tier_label"],
            "external_promotion": bool(m.get("external_promotion")),
        }
        for m in members
    ]


def metrics(con) -> dict[str, Any]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE canonical_event_id IS NOT NULL) AS duplicates, "
            "       count(*) FILTER (WHERE canonical_event_id IS NOT NULL "
            "                          AND duplicate_decided_by = 'AUTO') AS auto_merged, "
            "       count(*) FILTER (WHERE duplicate_decided_by = 'HUMAN') AS human_decided, "
            # What a user would actually be shown: live, canonical and listed.
            # Counting every LISTED row here would have claimed 26 on a board
            # showing 15.
            "       count(*) FILTER (WHERE listing_state = 'LISTED' "
            "                          AND canonical_event_id IS NULL "
            "                          AND provenance = 'LIVE') AS listed "
            "FROM events"
        )
        summary = _row(cur)
        cur.execute("SELECT count(*) FROM event_duplicate_pairs WHERE state = 'OPEN'")
        summary["open_pairs"] = cur.fetchone()[0]
    return summary
