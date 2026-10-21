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

import hashlib
import hmac
import json
import time
from datetime import date
from typing import Any

from . import source_evidence, source_priority, venue_identity

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
# v0.96.32: date, clock and venue id all agree, and the two posts still name
# metropolitan cities that exclude each other - so the id is answering for two
# places and a person has to say which.
RULE_REGION_CONFLICT = "SAME_DATE_VENUE_TIME_REGION_CONFLICT"
# v0.96.41: two calendars' records of one festival - the same first day at the
# same resolved place, neither stating a clock because a festival has none.
RULE_SAME_DATE_VENUE_FESTIVAL = "SAME_DATE_VENUE_FESTIVAL"
# ... and two festivals starting the same day whose places do not settle it -
# a question for a person, never a merge.
RULE_SAME_DATE_FESTIVAL_PLACE_DIFFERS = "SAME_DATE_FESTIVAL_PLACE_DIFFERS"
#: The engine type of a festival, marathon or tango week (v0.96.41).
FESTIVAL = "FESTIVAL"
# v0.96.23: an automatic merge the rules would no longer make, released.
RULE_STALE_AUTO_MERGE = "STALE_AUTO_MERGE"
# A person's answer on the Duplicates page, and (v0.96.40) a person taking
# one back.
RULE_HUMAN_REVIEW = "HUMAN_REVIEW"
RULE_HUMAN_REVERT = "HUMAN_REVERT"
REVERT = "REVERT"

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
    """The hour this event starts at, or None when nothing says.

    v0.96.29: `str(None)[:5]` is `"None"`, a perfectly truthy string, so two
    events with no start time at all read as agreeing on one - and
    `classify()` below then returned `SAME_DATE_VENUE_TIME`, auto-merging on
    date and venue alone while claiming `start_time` among the things that
    matched. Nothing had matched; neither event had an hour.

    It had never fired: a fold needs both places *resolved* (v0.96.23), and no
    pair of time-less events at one resolved venue on one date existed in
    Production - 0 of them. v0.96.29 is what would have created the first,
    because reading a post's own `placeName` resolves the venue on 53 events
    that had none. With the missing hour reported as missing, such a pair
    falls to `RULE_VENUE_TIME_DIFFERS` instead: a question for a person, which
    is what this module does with everything it cannot settle outright.
    """
    value = event.get("start_time")
    if value is None:
        return None
    return value.strftime("%H:%M") if hasattr(value, "strftime") else (str(value)[:5] or None)


def classify(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """What, if anything, these two events have in common.

    Returns None when they are simply different events -- including the case
    that matters most for a weekly milonga: two instances of one series on two
    dates are not duplicates, however identical everything else looks.
    """
    if left["event_date"] != right["event_date"]:
        return None
    festivals = [_is_festival(left), _is_festival(right)]
    if any(festivals):
        return _classify_festivals(left, right) if all(festivals) else None

    left_place, right_place = _place(left), _place(right)
    left_clock, right_clock = _clock(left), _clock(right)
    same_place = bool(left_place) and left_place == right_place
    same_clock = bool(left_clock) and left_clock == right_clock

    if same_place and same_clock:
        if venue_identity.texts_contradict(left.get("venue_text"),
                                           right.get("venue_text")):
            # v0.96.32: one venue id, and the two posts name metropolitan
            # cities that exclude each other. A resolved venue is normally the
            # strongest thing these rules have - somebody matched that string
            # to a place - but it is still a name match, and a name can answer
            # for two places: an alias of Seoul's `Tango O Nada` answered for
            # `대전 땅고 오나다`, and this rule then folded the real Seoul
            # milonga sharing that Friday hour away as its duplicate. The
            # events' own words outrank the id they happen to share, and what
            # they settle is only that this is not automatic.
            return {
                "rule": RULE_REGION_CONFLICT,
                "auto": False,
                "matched": ["event_date", "venue", "start_time"],
                "differs": ["stated_region"],
            }
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


def _is_festival(event: dict[str, Any]) -> bool:
    return (event.get("event_type") or "").upper() == FESTIVAL


def _classify_festivals(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """Two festivals on the same first day (v0.96.41).

    A festival is never a duplicate of a night: the welcome milonga of a tango
    week shares its first day and its room, and is one of the things the
    festival is made of. Two festivals are the same one when they start the
    same day at the same *resolved* place - the clock the night rules need is
    exactly what a festival never has, so it is not asked. Everything else the
    night rules hold to is: an unresolved name is a question for a person, and
    so are two records naming cities that exclude each other - and so are two
    festivals starting the same day whose places do not match or are not
    known: TangoNOW names KOREA SPECIAL TANGO WEEK's place `포항 posTango ·
    서울 OCHO`, which resolves to nothing, and Miltang's notice names PosTango.
    """
    left_place, right_place = _place(left), _place(right)
    if not left_place or left_place != right_place:
        return {"rule": RULE_SAME_DATE_FESTIVAL_PLACE_DIFFERS, "auto": False,
                "matched": ["event_date", "event_type"], "differs": ["venue"]}
    if venue_identity.texts_contradict(left.get("venue_text"), right.get("venue_text")):
        return {"rule": RULE_REGION_CONFLICT, "auto": False,
                "matched": ["event_date", "venue"], "differs": ["stated_region"]}
    if _place_is_known(left) and _place_is_known(right):
        return {"rule": RULE_SAME_DATE_VENUE_FESTIVAL, "auto": True,
                "matched": ["event_date", "venue", "event_type"], "differs": []}
    return {"rule": RULE_UNRESOLVED_VENUE_TIME, "auto": False,
            "matched": ["event_date", "venue_text", "event_type"],
            "differs": ["venue_status"]}


def _decided_by_human(event: dict[str, Any]) -> bool:
    return (event.get("duplicate_decided_by") or "").upper() == HUMAN


def record_decision(con, *, event_id: int, canonical_event_id: int | None,
                    decision: str, decided_by: str, rule: str,
                    reason: str | None = None, reviewer: str | None = None,
                    pair_id: int | None = None) -> dict[str, Any]:
    """Write one duplicate verdict and update the event to match it.

    ``pair_id`` (v0.96.40) is the Duplicates-page question a person's verdict
    answers, so a revert can put that question back.
    """
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO event_duplicate_decisions (event_id, canonical_event_id, "
            "  decision, decided_by, rule, reason, reviewer, pair_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (event_id, canonical_event_id, decision, decided_by, rule, reason, reviewer,
             pair_id),
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


def _pair_is_new(con, left_id: int, right_id: int) -> bool:
    """Whether `_record_pair()` would record this pair (a dry run asks)."""
    low, high = sorted((left_id, right_id))
    with con.cursor() as cur:
        cur.execute("SELECT 1 FROM event_duplicate_pairs WHERE event_id = %s "
                    "AND other_event_id = %s", (low, high))
        return cur.fetchone() is None


def _release_stale_auto_merges(con, events: list[dict[str, Any]], *,
                               actions: list[list[Any]] | None = None,
                               apply: bool = True) -> list[int]:
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

    ``apply=False`` (v0.96.40) decides exactly the same way and writes
    nothing; each release is appended to ``actions`` either way.
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
        if apply:
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
        if actions is not None:
            actions.append(["RELEASE", event["event_id"], canonical_id, RULE_STALE_AUTO_MERGE])
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
        if apply:
            reconcile_primary_source(con, canonical_id)
        released.append(event["event_id"])
    return released


def scan(con, *, on: date | None = None, limit_days: int | None = None,
         dry_run: bool = False,
         overrides: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compare events sharing a date and act on what the rules can settle.

    Only events on the same day are ever compared, so the scan stays cheap and
    a weekly series can never collapse into one row.

    v0.96.23: the pass begins by releasing automatic merges the rules would no
    longer make (``_release_stale_auto_merges``), so a corrected rule reaches
    rows that were folded under the old one instead of only new arrivals.

    v0.96.40: every merge, release and new pair is also returned as
    ``actions``. ``dry_run=True`` makes the same decisions and writes nothing,
    and ``overrides`` replaces columns of the rows it reads - which is how a
    duplicate-verdict revert previews what the scan does once the verdict is
    gone, and then checks that the real scan did exactly that.
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

    for event in events:
        event.update((overrides or {}).get(event["event_id"]) or {})

    by_date: dict[Any, list[dict[str, Any]]] = {}
    for event in events:
        by_date.setdefault(event["event_date"], []).append(event)

    actions: list[list[Any]] = []
    # Before anything is compared: a merge the rules would not make today is
    # released, so what follows decides on the rows as they actually are.
    released = _release_stale_auto_merges(con, events, actions=actions, apply=not dry_run)

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
                    if not dry_run:
                        record_decision(
                            con,
                            event_id=duplicate["event_id"],
                            canonical_event_id=canonical["event_id"],
                            decision=DUPLICATE,
                            decided_by=AUTO,
                            rule=finding["rule"],
                            reason="same date, same venue and same start time",
                        )
                    actions.append(["MERGE", duplicate["event_id"], canonical["event_id"],
                                    finding["rule"]])
                    resolved.add(duplicate["event_id"])
                    merged += 1
                    if duplicate["event_id"] == left["event_id"]:
                        break
                elif (_pair_is_new(con, left["event_id"], right["event_id"]) if dry_run
                      else _record_pair(con, left["event_id"], right["event_id"], finding)):
                    actions.append(["PAIR", *sorted((left["event_id"], right["event_id"])),
                                    finding["rule"]])
                    flagged += 1

    return {"events": len(events), "compared": compared,
            "auto_merged": merged, "flagged_for_review": flagged,
            "released": len(released), "actions": actions}


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
        cur.execute("SELECT * FROM event_duplicate_pairs WHERE pair_id = %s FOR UPDATE",
                    (pair_id,))
        pair = _row(cur)
    if pair is None:
        raise LookupError(f"no duplicate pair {pair_id}")
    # v0.96.45: a pair is answered once. A second answer - a stale page, a
    # double click - would stack a verdict on one nobody has withdrawn; taking
    # a verdict back is the revert's job (it reopens the pair).
    if pair["state"] != OPEN:
        raise ValueError(f"pair {pair_id} is already {pair['state']}; revert that verdict "
                         "first to answer it again")

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
            decision=DUPLICATE, decided_by=HUMAN, rule=RULE_HUMAN_REVIEW,
            reason=reason, reviewer=reviewer, pair_id=pair_id,
        )
        new_state = MERGED
    else:
        for event_id in members:
            record_decision(
                con, event_id=event_id, canonical_event_id=None, decision=DISTINCT,
                decided_by=HUMAN, rule=RULE_HUMAN_REVIEW, reason=reason, reviewer=reviewer,
                pair_id=pair_id,
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


# --- a person's answer, previewed and signed (v0.96.46) ----------------------------
#
# Until v0.96.46 a Same event / Different events answer was applied straight
# from the Duplicates page's buttons: nothing tied it to the pair, events and
# verdicts the operator had looked at, and the pair lock it took was released
# at once (the console's connection autocommits). Now the buttons open a
# preview of exactly what the answer would change, signed for that action,
# that pair, that reviewer and a digest of what it rests on; the confirm
# locks the pair and its events, recomputes the preview and applies it only
# if the token still holds. A revert, a later verdict, a re-extraction or a
# source revision changes the digest, so a preview taken before any of them
# confirms nothing.

RESOLVE_TOKEN_PURPOSE = "duplicate-resolve"


def _resolve_action(decision: str) -> str:
    if decision == DUPLICATE:
        return MERGE_VERDICT
    if decision == DISTINCT:
        return KEEP_SEPARATE_VERDICT
    raise ValueError(f"decision must be {DUPLICATE} or {DISTINCT}, got {decision!r}")


# Why an answer cannot be recorded (v0.96.47). Each refusal carries one of
# these beside its message, so the Duplicates queue, the preview and the
# confirm all say the same thing for the same reason.
REASON_ALREADY_RESOLVED = "PAIR_ALREADY_RESOLVED"
REASON_TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
REASON_CANONICAL_CHANGED = "CANONICAL_RELATION_CHANGED"
REASON_SAME_GROUP = "ALREADY_SAME_GROUP"
REASON_DATE_CONFLICT = "DATE_CONFLICT"
REASON_REGION_CONFLICT = "REGION_CONFLICT"
REASON_FESTIVAL_PROGRAMME = "FESTIVAL_PROGRAMME"
REASON_GROUP_CHAIN = "GROUP_CHAIN"
REASON_KEEP_NOT_IN_PAIR = "KEEP_NOT_IN_PAIR"
# Not refusals: what the rules say about the pair's events as they read now.
REASON_NO_CURRENT_MATCH = "NO_CURRENT_MATCH"
REASON_RULES_WOULD_MERGE = "RULES_WOULD_MERGE"


def resolve_blockers(pair: dict[str, Any], members: dict[int, dict[str, Any]], *,
                     decision: str, canonical_event_id: int | None = None
                     ) -> tuple[list[tuple[str, str]], int | None, int | None]:
    """Why answering ``pair`` with ``decision`` may not be recorded, as
    ``([(reason, message)], kept, folded)``. Pure: ``members`` are the pair's
    events as ``_members()`` reads them (a missing one is absent).

    The one place the guards live (v0.96.47): ``preview_resolve`` - and so the
    confirm, which recomputes the preview under its locks - and the queue's
    per-action eligibility all call this, so the page never offers an answer
    the confirm would refuse.
    """
    pair_id = pair["pair_id"]
    member_ids = sorted((pair["event_id"], pair["other_event_id"]))
    refusals: list[tuple[str, str]] = []
    if pair["state"] != OPEN:
        refusals.append((REASON_ALREADY_RESOLVED,
                         f"pair #{pair_id} is already {pair['state']} "
                         f"({pair.get('resolved_by') or '-'}); revert that verdict first to "
                         "answer it again"))
    for missing in sorted(set(member_ids) - set(members)):
        refusals.append((REASON_TARGET_NOT_FOUND,
                         f"event #{missing} no longer exists (re-extracted or pruned)"))
    canonical_id = duplicate_id = None
    if not refusals:
        if len({m["event_date"] for m in members.values()}) != 1:
            refusals.append((REASON_DATE_CONFLICT,
                             "the two events are on different dates - a merge across dates is "
                             "never offered here; see Conflicts / Evidence"))
        for event in members.values():
            # Different events may split the rules' fold of one member into
            # the other (the preview shows the unfold); any other existing
            # fold would be moved or undone by an answer about this pair.
            if event["canonical_event_id"] is None or (
                    decision == DISTINCT and event["canonical_event_id"] in members
                    and event["duplicate_decided_by"] != HUMAN):
                continue
            reason = (REASON_SAME_GROUP if event["canonical_event_id"] in members
                      and event["duplicate_decided_by"] != HUMAN else REASON_CANONICAL_CHANGED)
            refusals.append((reason, f"event #{event['event_id']} is already merged into "
                                     f"#{event['canonical_event_id']} - settle that first"))
    if not refusals and decision == DUPLICATE:
        left, right = (members[i] for i in member_ids)
        # v0.96.47: what no rule would ever call one event is not one a single
        # click may make one. A festival and one of its nights share a day and
        # often a room; two regions are two places whatever a venue id says.
        if _is_festival(left) != _is_festival(right):
            refusals.append((REASON_FESTIVAL_PROGRAMME,
                             "one of the two is a festival and the other is not - a festival "
                             "is never merged with a night of its programme"))
        regions = {m["region_id"] for m in members.values()}
        if None not in regions and len(regions) > 1:
            refusals.append((REASON_REGION_CONFLICT,
                             "the two events are in different regions (" +
                             " / ".join(str(r) for r in sorted(regions)) +
                             ") - a merge across regions is never offered"))
        elif venue_identity.texts_contradict(left.get("venue_text"), right.get("venue_text")):
            refusals.append((REASON_REGION_CONFLICT,
                             "the two posts name cities that exclude each other - a merge "
                             "across regions is never offered"))
    if not refusals and decision == DUPLICATE:
        if canonical_event_id is None:
            canonical_event_id = _canonical_of(*members.values())[0]["event_id"]
        if canonical_event_id not in members:
            refusals.append((REASON_KEEP_NOT_IN_PAIR,
                             f"the event kept has to be one of the pair (#{member_ids[0]} or "
                             f"#{member_ids[1]}), not #{canonical_event_id}"))
        else:
            canonical_id = canonical_event_id
            duplicate_id = member_ids[0] if member_ids[1] == canonical_id else member_ids[1]
            if int(members[duplicate_id]["folded_count"] or 0) > 0:
                refusals.append((REASON_GROUP_CHAIN,
                                 f"event #{duplicate_id} already heads "
                                 f"{members[duplicate_id]['folded_count']} folded post(s) - "
                                 "keep it instead, or the group would form a chain"))
    return refusals, canonical_id, duplicate_id


def preview_resolve(con, pair_id: int, *, decision: str, canonical_event_id: int | None = None,
                    reviewer: str = "admin") -> dict[str, Any]:
    """What answering this pair would change, and why it may not. Writes nothing."""
    from . import decision_contract  # noqa: PLC0415

    action = _resolve_action(decision)
    with con.cursor() as cur:
        cur.execute("SELECT pair_id, event_id, other_event_id, rule, matched, differs, state, "
                    "  resolved_by, resolved_at FROM event_duplicate_pairs WHERE pair_id = %s",
                    (pair_id,))
        pair = _row(cur)
    if pair is None:
        raise LookupError(f"no duplicate pair {pair_id}")
    member_ids = sorted((pair["event_id"], pair["other_event_id"]))
    members = _members(con, member_ids)
    refusals, canonical_id, duplicate_id = resolve_blockers(
        pair, members, decision=decision, canonical_event_id=canonical_event_id)
    blockers = [message for _, message in refusals]
    reasons = [reason for reason, _ in refusals]
    code = decision_contract.ALREADY_RESOLVED if REASON_ALREADY_RESOLVED in reasons else None
    with con.cursor() as cur:
        cur.execute("SELECT max(decision_id), count(*) FROM event_duplicate_decisions "
                    "WHERE event_id = ANY(%s) OR canonical_event_id = ANY(%s)",
                    (member_ids, member_ids))
        last_decision, decision_count = cur.fetchone()
        items = sorted({m["source_item_id"] for m in members.values()
                        if m.get("source_item_id") is not None})
        cur.execute("SELECT i.source_item_id, i.content_hash, c.content_hash, "
                    "  c.extracted_input_signature FROM source_items i "
                    "LEFT JOIN source_item_content c USING (source_item_id) "
                    "WHERE i.source_item_id = ANY(%s) ORDER BY i.source_item_id", (items,))
        sources = [list(r) for r in cur.fetchall()]
    outlook = []
    for event_id in member_ids:
        before = members.get(event_id)
        if before is None:
            continue
        after = dict(before)
        if not blockers:
            if decision == DUPLICATE and event_id == duplicate_id:
                after.update(canonical_event_id=canonical_id, duplicate_decided_by=HUMAN)
            elif decision == DISTINCT:
                after.update(canonical_event_id=None, duplicate_decided_by=HUMAN)
            after["listing_state"] = _listing_for(after)
        outlook.append({
            "event_id": event_id, "event_date": before["event_date"],
            "event_name": before["event_name"], "start_time": before["start_time"],
            "venue_text": before["venue_text"],
            "canonical_before": before["canonical_event_id"],
            "canonical_after": after["canonical_event_id"],
            "decided_by_before": before["duplicate_decided_by"],
            "decided_by_after": after["duplicate_decided_by"],
            "listing_before": before["listing_state"], "listing_after": after["listing_state"],
            "public_before": _visible(before), "public_after": _visible(after),
        })
    facts = {
        "action": action,
        "pair": [pair["pair_id"], pair["event_id"], pair["other_event_id"], pair["rule"],
                 pair["state"]],
        "keep": canonical_id,
        "fold": duplicate_id,
        "members": [[m["event_id"], str(m["event_date"]), str(m["start_time"]), m["venue_id"],
                     m["venue_text"], m["region_id"], m["identity_key"],
                     m["canonical_event_id"], m["duplicate_decided_by"], m["listing_state"],
                     m["review_state"], m["source_item_id"], m["primary_source_item_id"],
                     int(m["folded_count"] or 0)] for m in members.values()],
        "decisions": [last_decision, decision_count],
        "sources": sources,
        "outlook": [[o["event_id"], o["canonical_after"], o["decided_by_after"],
                     o["listing_after"]] for o in outlook],
    }
    return {
        "action": action, "decision": decision, "pair": pair, "members": list(members.values()),
        "canonical_event_id": canonical_id, "duplicate_event_id": duplicate_id,
        "outlook": outlook, "blockers": blockers, "reasons": reasons,
        "status": code or (decision_contract.DECISION_REFUSED if blockers else "SAFE"),
        "facts": facts,
        "token": (None if blockers else decision_contract.preview_token(
            RESOLVE_TOKEN_PURPOSE, action=action, subject=pair_id, facts=facts,
            reviewer=reviewer)),
    }


def confirm_resolve(con, pair_id: int, *, decision: str, token: str | None,
                    canonical_event_id: int | None = None, reviewer: str = "admin",
                    reason: str | None = None) -> dict[str, Any]:
    """Answer a pair exactly as its preview showed. One transaction.

    The pair, then its two events (id order, as the revert takes them), are
    locked; the preview is recomputed under the lock; the token must be for
    this action, this pair and this reviewer, unexpired, and its digest must
    match what is there now. Raises decision_contract.DecisionRefused with
    nothing written otherwise - a second, concurrent answer waits on the
    pair's lock and then finds it answered.
    """
    from . import decision_contract  # noqa: PLC0415

    action = _resolve_action(decision)
    refused = decision_contract.preview_refusal(token, RESOLVE_TOKEN_PURPOSE, action=action,
                                                subject=pair_id, facts=None, reviewer=reviewer)
    if refused is not None:
        raise refused
    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute("SELECT event_id, other_event_id FROM event_duplicate_pairs "
                            "WHERE pair_id = %s FOR UPDATE", (pair_id,))
                found = cur.fetchone()
                if found is None:
                    raise LookupError(f"no duplicate pair {pair_id}")
            _members(con, sorted(found), lock=True)
            preview = preview_resolve(con, pair_id, decision=decision,
                                      canonical_event_id=canonical_event_id, reviewer=reviewer)
            if preview["blockers"]:
                raise decision_contract.DecisionRefused(
                    preview["status"], preview["blockers"][0], preview["blockers"])
            refused = decision_contract.preview_refusal(
                token, RESOLVE_TOKEN_PURPOSE, action=action, subject=pair_id,
                facts=preview["facts"], reviewer=reviewer)
            if refused is not None:
                raise refused
            result = resolve_pair(con, pair_id, decision=decision,
                                  canonical_event_id=preview["canonical_event_id"],
                                  reviewer=reviewer, reason=reason)
            after = _members(con, sorted(found))
            for expected in preview["outlook"]:
                now = after[expected["event_id"]]
                if (now["canonical_event_id"], now["duplicate_decided_by"],
                        now["listing_state"]) != (expected["canonical_after"],
                                                  expected["decided_by_after"],
                                                  expected["listing_after"]):
                    raise decision_contract.DecisionRefused(
                        decision_contract.STALE_PREVIEW,
                        f"event #{expected['event_id']} did not end up as the preview showed "
                        "- nothing was recorded; preview again")
    except (decision_contract.DecisionRefused, LookupError):
        raise
    except Exception as exc:
        if decision_contract.concurrent(exc):
            raise decision_contract.DecisionRefused(
                decision_contract.CONCURRENT_DECISION,
                "another decision on these events was being recorded at the same time; "
                "nothing was recorded - preview again") from exc
        raise
    return {**result, "action": action, "outlook": preview["outlook"],
            "duplicate_event_id": preview["duplicate_event_id"]}


# --- taking a person's verdict back (v0.96.40) --------------------------------
#
# A Same event / Different events answer was final: nothing undid it, and the
# scan never re-asks a pair a person settled. A revert withdraws one such
# verdict and nothing else. It does not split two posts of one night by force:
# with the verdict gone the duplicate rules decide again, in the same
# transaction, exactly as the scheduler's next scan would - so a pair the rules
# merge by themselves is merged again, by the rules, and says so. The verdict's
# own rows stay in event_duplicate_decisions; the revert adds a REVERT row per
# verdict row, naming it. A verdict something later depends on is not undone
# around: a later verdict a person gave on either event, or a representative
# post a person chose for the group, blocks the revert until that is undone.

MERGE_VERDICT = "MERGE"
KEEP_SEPARATE_VERDICT = "KEEP_SEPARATE"
REVERT_ACTION = "DUPLICATE_DECISION_REVERT"
REVERT_BLOCKED_DEPENDENCY = "REVERT_BLOCKED_DEPENDENCY"
REVERT_TOKEN_TTL_SECONDS = 2 * 3600

_MEMBER_COLUMNS = (
    "e.event_id, e.event_date, e.event_name, e.start_time, e.venue_id, e.venue_text, "
    "e.region_id, e.identity_key, e.series_key, e.event_type, e.canonical_event_id, "
    "e.duplicate_decided_by, e.listing_state, e.review_state, e.provenance, "
    "e.source_item_id, e.primary_source_item_id, e.primary_source_decided_by"
)


class RevertRefused(Exception):
    """This verdict cannot be taken back as things stand. Nothing was written."""

    def __init__(self, reasons: list[str], code: str = "REVERT_REFUSED"):
        super().__init__("; ".join(reasons))
        self.reasons = reasons
        self.code = code


class StaleRevertPreview(RevertRefused):
    """What the revert would do is no longer what the operator was shown."""

    def __init__(self, reasons: list[str]):
        super().__init__(reasons, code="REVERT_STALE_PREVIEW")


def _listing_for(event: dict[str, Any]) -> str:
    """listing_state as every writer derives it (v0.96.39's invariant)."""
    if event.get("canonical_event_id") is not None:
        return "HIDDEN"
    if (event.get("review_state") or "").upper() in ("REJECTED", "DUPLICATE"):
        return "HIDDEN"
    return "LISTED"


def _visible(event: dict[str, Any]) -> bool:
    """events_api._VISIBLE, for a row held in memory."""
    return (event.get("provenance") == "LIVE" and event.get("listing_state") == "LISTED"
            and event.get("canonical_event_id") is None)


def _revert_signature(facts: dict[str, Any], reviewer: str, issued: int) -> str:
    from . import admin_csrf  # noqa: PLC0415 - keeps the scheduler import graph as it was

    body = json.dumps({"facts": facts, "reviewer": reviewer, "issued": issued},
                      sort_keys=True, ensure_ascii=False, default=str)
    return hmac.new(admin_csrf.signing_key("duplicate-decision"), body.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def revert_token(facts: dict[str, Any], *, reviewer: str = "admin",
                 now: float | None = None) -> str:
    """Binds a confirm to the preview a reviewer was shown (v0.96.38's contract,
    under a key of its own so no other preview's token is accepted)."""
    issued = int(time.time() if now is None else now)
    return f"{issued}.{_revert_signature(facts, reviewer, issued)}"


def _revert_token_matches(given: str | None, facts: dict[str, Any], reviewer: str,
                          now: float | None = None) -> bool:
    issued, _, signature = (given or "").partition(".")
    if not issued.isdigit() or not signature:
        return False
    age = (time.time() if now is None else now) - int(issued)
    if age > REVERT_TOKEN_TTL_SECONDS or age < -300:
        return False
    return hmac.compare_digest(signature, _revert_signature(facts, reviewer, int(issued)))


def _decision_row(con, decision_id: int, *, lock: bool = False) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM event_duplicate_decisions WHERE decision_id = %s"
                    + (" FOR UPDATE" if lock else ""), (decision_id,))
        return _row(cur)


def _verdict(con, original: dict[str, Any]) -> tuple[list[dict[str, Any]], dict | None]:
    """The rows one person's answer wrote, and the Duplicates-page pair it answered.

    A Same-event answer writes one row (on the post folded away), a
    Different-events answer one per post. Rows written since v0.96.40 carry
    their pair_id; an older answer is found through its pair's two event ids.
    """
    with con.cursor() as cur:
        pair = None
        if original.get("pair_id") is not None:
            cur.execute("SELECT * FROM event_duplicate_pairs WHERE pair_id = %s",
                        (original["pair_id"],))
            pair = _row(cur)
        elif original["decision"] == DUPLICATE and original.get("canonical_event_id"):
            low, high = sorted((original["event_id"], original["canonical_event_id"]))
            cur.execute("SELECT * FROM event_duplicate_pairs WHERE event_id = %s "
                        "AND other_event_id = %s", (low, high))
            pair = _row(cur)
        else:
            cur.execute("SELECT * FROM event_duplicate_pairs WHERE state = %s "
                        "AND %s IN (event_id, other_event_id) ORDER BY pair_id",
                        (DISTINCT, original["event_id"]))
            found = _rows(cur)
            pair = found[0] if len(found) == 1 else None
        rows = [original]
        if original["decision"] == DISTINCT and pair is not None:
            other = (pair["other_event_id"] if pair["event_id"] == original["event_id"]
                     else pair["event_id"])
            cur.execute(
                "SELECT * FROM event_duplicate_decisions WHERE event_id = %s "
                "  AND decision = %s AND decided_by = %s AND rule = %s "
                "  AND pair_id IS NOT DISTINCT FROM %s::bigint "
                "ORDER BY abs(decision_id - %s) LIMIT 1",
                (other, DISTINCT, HUMAN, RULE_HUMAN_REVIEW, original.get("pair_id"),
                 original["decision_id"]),
            )
            sibling = _row(cur)
            if sibling is not None:
                rows.append(sibling)
        return sorted(rows, key=lambda r: r["decision_id"]), pair


def _reverted_ids(con, ids: list[int]) -> set[int]:
    with con.cursor() as cur:
        cur.execute("SELECT reverts_decision_id FROM event_duplicate_decisions "
                    "WHERE reverts_decision_id = ANY(%s)", (ids,))
        return {r[0] for r in cur.fetchall()}


def _standing_human_verdicts(con, event_id: int, excluding: list[int]) -> list[int]:
    """A person's other verdicts on this event that have not been taken back."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT d.decision_id FROM event_duplicate_decisions d "
            "WHERE d.event_id = %s AND d.decided_by = %s AND d.decision IN (%s, %s) "
            "  AND NOT (d.decision_id = ANY(%s)) "
            "  AND NOT EXISTS (SELECT 1 FROM event_duplicate_decisions r "
            "                  WHERE r.reverts_decision_id = d.decision_id) "
            "ORDER BY d.decision_id",
            (event_id, HUMAN, DUPLICATE, DISTINCT, excluding),
        )
        return [r[0] for r in cur.fetchall()]


def _members(con, ids: list[int], *, lock: bool = False) -> dict[int, dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT " + _MEMBER_COLUMNS + ", "
            "  (SELECT count(*) FROM events d WHERE d.canonical_event_id = e.event_id) "
            "    AS folded_count "
            "FROM events e WHERE e.event_id = ANY(%s) ORDER BY e.event_id"
            + (" FOR UPDATE OF e" if lock else ""), (ids,))
        return {r["event_id"]: r for r in _rows(cur)}


def _later_dependencies(con, rows: list[dict[str, Any]], member_ids: list[int],
                        members: dict[int, dict[str, Any]]) -> list[str]:
    """Later decisions a person took that rest on this verdict standing."""
    reasons = []
    last = max(r["decision_id"] for r in rows)
    with con.cursor() as cur:
        cur.execute(
            "SELECT d.decision_id, d.event_id, d.canonical_event_id, d.decision, d.reviewer, "
            "       d.created_at FROM event_duplicate_decisions d "
            "WHERE d.decision_id > %s AND d.decided_by = %s AND d.decision <> %s "
            "  AND (d.event_id = ANY(%s) OR d.canonical_event_id = ANY(%s)) "
            "  AND NOT EXISTS (SELECT 1 FROM event_duplicate_decisions r "
            "                  WHERE r.reverts_decision_id = d.decision_id) "
            "ORDER BY d.decision_id",
            (last, HUMAN, REVERT, member_ids, member_ids),
        )
        for later in _rows(cur):
            reasons.append(
                f"decision #{later['decision_id']} ({later['decision']}, "
                f"{later['reviewer'] or '-'}, {str(later['created_at'])[:16]}) on event "
                f"#{later['event_id']} came after this one - revert it first")
    for event in members.values():
        if event.get("primary_source_decided_by") != HUMAN:
            continue
        chosen = event.get("primary_source_item_id")
        owners = [m["event_id"] for m in members.values()
                  if m["source_item_id"] == chosen and m["event_id"] != event["event_id"]]
        if owners:
            reasons.append(
                f"a person chose event #{owners[0]}'s post as #{event['event_id']}'s "
                "representative source, which rests on this merge - reset it on the "
                "event's Sources page first")
    return reasons


def preview_revert(con, *, decision_id: int, reviewer: str = "admin") -> dict[str, Any]:
    """What taking this verdict back would change, and why it may not. Writes nothing.

    The expected outcome is the duplicate scan's own: the verdict's events with
    the verdict removed are handed to ``scan(dry_run=True)`` for their date, and
    its actions - a merge the rules make by themselves, a pair back on the
    Duplicates page, or nothing - are what the confirm will do and check.
    """
    original = _decision_row(con, decision_id)
    if original is None:
        raise LookupError(f"no duplicate decision {decision_id}")
    blockers: list[str] = []
    warnings: list[str] = []
    code = None
    if original["decision"] == REVERT:
        blockers.append(f"#{decision_id} is itself a revert - there is no verdict to take back")
    elif original["decided_by"] != HUMAN or original["rule"] != RULE_HUMAN_REVIEW:
        blockers.append(f"#{decision_id} was decided by the rules ({original['rule']}), not by "
                        "a person - the next scan already re-asks it")
    rows, pair = _verdict(con, original) if not blockers else ([original], None)
    kind = MERGE_VERDICT if original["decision"] == DUPLICATE else KEEP_SEPARATE_VERDICT
    ids = [r["decision_id"] for r in rows]
    if not blockers and _reverted_ids(con, ids):
        blockers.append(f"#{decision_id} has already been reverted")
        code = "REVERT_ALREADY_APPLIED"
    if not blockers and kind == KEEP_SEPARATE_VERDICT and len(rows) != 2:
        blockers.append(f"the other half of Different-events verdict #{decision_id} is not "
                        "in the trail, so it cannot be taken back as one answer")
    member_ids = sorted({r["event_id"] for r in rows}
                        | ({original["canonical_event_id"]}
                           if kind == MERGE_VERDICT and original["canonical_event_id"] else set()))
    members = _members(con, member_ids)
    for missing in sorted(set(member_ids) - set(members)):
        blockers.append(f"event #{missing} no longer exists (re-extracted or pruned) - "
                        "the verdict's subject is gone")
    duplicate_id = original["event_id"]
    canonical_id = original["canonical_event_id"] if kind == MERGE_VERDICT else None
    if not blockers:
        if kind == MERGE_VERDICT:
            current = members[duplicate_id]
            if (current["canonical_event_id"] != canonical_id
                    or current["duplicate_decided_by"] != HUMAN):
                blockers.append(
                    f"event #{duplicate_id} is no longer merged into #{canonical_id} by this "
                    f"verdict (now: {current['canonical_event_id'] or 'not merged'}, "
                    f"{current['duplicate_decided_by'] or 'no verdict'}) - the merge no longer stands")
            if members[canonical_id]["canonical_event_id"] is not None:
                blockers.append(f"event #{canonical_id} has itself been merged into "
                                f"#{members[canonical_id]['canonical_event_id']} since")
        else:
            for event_id in member_ids:
                current = members[event_id]
                if (current["canonical_event_id"] is not None
                        or current["duplicate_decided_by"] != HUMAN):
                    blockers.append(f"event #{event_id} is no longer kept separate by this "
                                    "verdict - the verdict no longer stands")
    if not blockers:
        dependencies = _later_dependencies(con, rows, member_ids, members)
        if dependencies:
            blockers.extend(dependencies)
            code = REVERT_BLOCKED_DEPENDENCY
    code = code or ("REVERT_REFUSED" if blockers else "REVERT_SAFE")

    # The events with the verdict removed: unfolded, and no longer marked as a
    # person's unless another standing verdict of a person's still covers them.
    overrides: dict[int, dict[str, Any]] = {}
    changes = []
    if not blockers:
        for event_id in member_ids:
            event = members[event_id]
            if kind == MERGE_VERDICT and event_id != duplicate_id:
                overrides[event_id] = {
                    "folded_count": max(0, int(event["folded_count"] or 0) - 1)}
                continue
            keep = _standing_human_verdicts(con, event_id, ids)
            if keep:
                warnings.append(f"event #{event_id} keeps a person's earlier verdict "
                                + ", ".join(f"#{k}" for k in keep)
                                + ", so the rules still leave it alone")
            after = {**event, "canonical_event_id": None,
                     "duplicate_decided_by": HUMAN if keep else None}
            after["listing_state"] = _listing_for(after)
            overrides[event_id] = {"canonical_event_id": None,
                                   "duplicate_decided_by": after["duplicate_decided_by"],
                                   "listing_state": after["listing_state"]}
            changes.append(event_id)
    dates = sorted({m["event_date"] for m in members.values()})
    planned: list[list[Any]] = []
    if not blockers:
        for day in dates:
            planned.extend(scan(con, on=day, dry_run=True, overrides=overrides)["actions"])
    # Each touched event's state before and after: the reversal, then the scan.
    touched = sorted(set(member_ids) | {a[1] for a in planned} | {a[2] for a in planned})
    now_rows = _members(con, touched)
    outlook = []
    for event_id in touched:
        before = now_rows.get(event_id)
        if before is None:
            continue
        after = {**before, **{k: v for k, v in (overrides.get(event_id) or {}).items()
                              if k != "folded_count"}}
        for action in planned:
            if action[0] == "MERGE" and action[1] == event_id:
                after.update(canonical_event_id=action[2], duplicate_decided_by=AUTO)
            elif action[0] == "RELEASE" and action[1] == event_id:
                after.update(canonical_event_id=None, duplicate_decided_by=AUTO)
        after["listing_state"] = _listing_for(after)
        outlook.append({
            "event_id": event_id, "event_date": before["event_date"],
            "event_name": before["event_name"], "start_time": before["start_time"],
            "venue_text": before["venue_text"], "identity_key": before["identity_key"],
            "canonical_before": before["canonical_event_id"],
            "canonical_after": after["canonical_event_id"],
            "decided_by_before": before["duplicate_decided_by"],
            "decided_by_after": after["duplicate_decided_by"],
            "listing_before": before["listing_state"], "listing_after": after["listing_state"],
            "public_before": _visible(before), "public_after": _visible(after),
        })
    remerged = [a for a in planned if a[0] == "MERGE" and set(a[1:3]) <= set(member_ids)]
    if remerged:
        warnings.append("the duplicate rules merge these posts by themselves once the verdict "
                        "is gone (" + remerged[0][3] + ") - the revert withdraws the person's "
                        "verdict, it does not split one night into two")
    unrelated = [a for a in planned if not ({a[1], a[2]} & set(member_ids))]
    if unrelated:
        warnings.append(f"the scan for this date also makes {len(unrelated)} change(s) it would "
                        "make anyway on its next run - they are listed below")
    summary = {
        "events": len(changes),
        "publicly_visible": sum(1 for o in outlook if o["public_before"]),
        "public_after": sum(1 for o in outlook if o["public_after"]),
        "public_changes": sum(1 for o in outlook if o["public_before"] != o["public_after"]),
        "identity_changes": 0,
        "canonical_changes": sum(1 for o in outlook
                                 if o["canonical_before"] != o["canonical_after"]),
        "scan_actions": len(planned),
    }
    facts = {
        "action": REVERT_ACTION,
        "decisions": ids,
        "kind": kind,
        "pair": [pair["pair_id"], pair["state"]] if pair else None,
        "members": [[m["event_id"], m["canonical_event_id"], m["duplicate_decided_by"],
                     m["listing_state"], m["identity_key"], m["venue_id"], m["region_id"],
                     str(m["event_date"]), str(m["start_time"])]
                    for m in members.values()],
        "overrides": {str(k): v for k, v in sorted(overrides.items())},
        "planned": planned,
    }
    return {
        "action": REVERT_ACTION, "decision": original, "verdict_rows": rows, "kind": kind,
        "pair": pair, "members": list(members.values()), "outlook": outlook,
        "planned": planned, "summary": summary, "blockers": blockers,
        "warnings": warnings, "status": code, "facts": facts,
        "token": revert_token(facts, reviewer=reviewer),
    }


def revert_decision(con, *, decision_id: int, token: str | None,
                    reviewer: str = "admin", reason: str | None = None) -> dict[str, Any]:
    """Take one person's verdict back, exactly as its preview showed. One transaction.

    The verdict's rows, its pair and its events are locked; the preview is
    recomputed under the lock and must match the token. The events are put
    back as they read without the verdict, the pair goes back to the
    Duplicates page, the date is scanned as the scheduler would scan it, and
    the scan has to have done what the preview said - otherwise everything is
    rolled back. The REVERT rows are written last, with both states in them.
    """
    with con.transaction():
        original = _decision_row(con, decision_id, lock=True)
        if original is None:
            raise LookupError(f"no duplicate decision {decision_id}")
        rows, pair = _verdict(con, original)
        ids = [r["decision_id"] for r in rows]
        with con.cursor() as cur:
            cur.execute("SELECT decision_id FROM event_duplicate_decisions "
                        "WHERE decision_id = ANY(%s) ORDER BY decision_id FOR UPDATE", (ids,))
            if pair is not None:
                cur.execute("SELECT pair_id FROM event_duplicate_pairs WHERE pair_id = %s "
                            "FOR UPDATE", (pair["pair_id"],))
        member_ids = sorted({r["event_id"] for r in rows}
                            | ({original["canonical_event_id"]}
                               if original["decision"] == DUPLICATE
                               and original["canonical_event_id"] else set()))
        _members(con, member_ids, lock=True)
        preview = preview_revert(con, decision_id=decision_id, reviewer=reviewer)
        if preview["blockers"]:
            raise RevertRefused(preview["blockers"], code=preview["status"])
        if not _revert_token_matches(token, preview["facts"], reviewer):
            raise StaleRevertPreview(["the preview is out of date or was not issued for this "
                                      "revert - nothing changed; preview again"])
        before = {m["event_id"]: m for m in preview["members"]}
        with con.cursor() as cur:
            for key, change in preview["facts"]["overrides"].items():
                if "canonical_event_id" not in change:
                    continue
                cur.execute(
                    "UPDATE events SET canonical_event_id = NULL, duplicate_decided_by = %s, "
                    "  listing_state = %s, updated_at = now() WHERE event_id = %s",
                    (change["duplicate_decided_by"], change["listing_state"], int(key)),
                )
            if pair is not None:
                cur.execute("UPDATE event_duplicate_pairs SET state = %s, resolved_by = NULL, "
                            "  resolved_at = NULL WHERE pair_id = %s",
                            (OPEN, pair["pair_id"]))
        for event_id in member_ids:
            reconcile_primary_source(con, event_id)
        done = []
        for day in sorted({m["event_date"] for m in preview["members"]}):
            done.extend(scan(con, on=day)["actions"])
        if done != preview["planned"]:
            raise StaleRevertPreview([
                "the duplicate scan did not do what the preview showed "
                f"(expected {preview['planned']}, got {done}) - nothing changed; preview again"])
        after = _members(con, member_ids)
        recorded = []
        with con.cursor() as cur:
            for row in rows:
                cur.execute(
                    "INSERT INTO event_duplicate_decisions (event_id, canonical_event_id, "
                    "  decision, decided_by, rule, reason, reviewer, pair_id, "
                    "  reverts_decision_id, before_json, after_json) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) "
                    "RETURNING *",
                    (row["event_id"], row["canonical_event_id"], REVERT, HUMAN,
                     RULE_HUMAN_REVERT, (reason or "").strip() or None, reviewer,
                     pair["pair_id"] if pair else row.get("pair_id"), row["decision_id"],
                     json.dumps({
                         "verdict": preview["kind"],
                         "original_decision": {
                             "decision_id": row["decision_id"], "decision": row["decision"],
                             "reviewer": row["reviewer"], "created_at": row["created_at"],
                             "reason": row["reason"]},
                         "pair": ([pair["pair_id"], pair["state"]] if pair else None),
                         "events": [{k: before[i][k] for k in (
                             "event_id", "canonical_event_id", "duplicate_decided_by",
                             "listing_state", "identity_key", "series_key")}
                             for i in member_ids],
                     }, default=str),
                     json.dumps({
                         "pair": ([pair["pair_id"], OPEN] if pair else None),
                         "events": [{k: after[i][k] for k in (
                             "event_id", "canonical_event_id", "duplicate_decided_by",
                             "listing_state", "identity_key", "series_key")}
                             for i in member_ids],
                         "dependent_decisions": [],
                         "reconciliation": done,
                         "derived_by": "duplicates.scan for the verdict's date",
                         "preview_token": (token or "")[:16],
                     }, default=str)),
                )
                recorded.append(_row(cur))
    return {"reverted": ids, "kind": preview["kind"], "revert_decisions": recorded,
            "reconciliation": done, "pair_id": pair["pair_id"] if pair else None,
            "events": member_ids}


def recent_human_verdicts(con, *, limit: int = 20) -> list[dict[str, Any]]:
    """A person's verdicts that still stand - the ones Revert applies to.

    One line per answer: a Different-events answer wrote a row per post, and
    only the first is listed.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT d.*, a.event_name, a.event_date, c.event_name AS canonical_event_name "
            "FROM event_duplicate_decisions d "
            "LEFT JOIN events a ON a.event_id = d.event_id "
            "LEFT JOIN events c ON c.event_id = d.canonical_event_id "
            "WHERE d.decided_by = %s AND d.rule = %s AND d.decision IN (%s, %s) "
            "  AND NOT EXISTS (SELECT 1 FROM event_duplicate_decisions r "
            "                  WHERE r.reverts_decision_id = d.decision_id) "
            "ORDER BY d.decision_id DESC LIMIT %s",
            (HUMAN, RULE_HUMAN_REVIEW, DUPLICATE, DISTINCT, limit * 2),
        )
        rows = _rows(cur)
    seen: set[Any] = set()
    out = []
    for row in sorted(rows, key=lambda r: r["decision_id"]):
        key = (row["pair_id"], row["decision"]) if row["pair_id"] else row["decision_id"]
        if row["decision"] == DISTINCT and key in seen:
            continue
        seen.add(key)
        out.append(row)
    return sorted(out, key=lambda r: r["decision_id"], reverse=True)[:limit]


# --- the queue: what each pair is now, and what can be done with it (v0.96.47) ------
#
# A pair's stored state (OPEN / MERGED / DISTINCT) only ever changes by a
# person's answer or its revert, and that stays so: nothing here writes. But
# an OPEN row is not the same thing as a question waiting on somebody. The
# scan keeps folding events after it has parked a pair, so one member can end
# up inside another group (the question has moved to that group's own pair),
# or both inside one (the rules settled it), and a re-extraction can leave two
# events no rule would pair any more. Every pair is assessed from the rows as
# they are now: its lifecycle status, and per answer whether the confirm would
# take it - by the same `resolve_blockers()` the preview and the confirm use.

QUEUE_ACTIONABLE = "ACTIONABLE"
QUEUE_STALE = "STALE"
QUEUE_SUPERSEDED = "SUPERSEDED"
QUEUE_RULES = "RESOLVED_BY_RULES"
QUEUE_PERSON = "RESOLVED_BY_PERSON"
QUEUE_INVALID = "INVALID_TARGET"
QUEUE_BLOCKED = "BLOCKED"
QUEUE_STATUSES = (QUEUE_ACTIONABLE, QUEUE_STALE, QUEUE_SUPERSEDED, QUEUE_RULES, QUEUE_PERSON,
                  QUEUE_INVALID, QUEUE_BLOCKED)

#: What the operator can usefully do next, per status.
QUEUE_GUIDANCE = {
    QUEUE_ACTIONABLE: "open a preview of an available answer",
    QUEUE_STALE: "the rules no longer pair these events as they read now - re-check the "
                 "current evidence before answering",
    QUEUE_SUPERSEDED: "a member is folded into another event - answer the group's own pair",
    QUEUE_RULES: "the rules already fold both into one group - nothing to answer unless that "
                 "fold is wrong (Different events splits it)",
    QUEUE_PERSON: "a person answered this - see the decision history (Revert reopens it)",
    QUEUE_INVALID: "an event of this pair no longer exists - check the data relationship",
    QUEUE_BLOCKED: "no answer can be recorded as things stand - see the reasons",
}


def _member_rows(con, ids: list[int]) -> dict[int, dict[str, Any]]:
    """`_members()` for many events, plus every canonical row they fold into."""
    found = _members(con, ids) if ids else {}
    pending = {e["canonical_event_id"] for e in found.values()
               if e["canonical_event_id"] is not None} - set(found)
    for _ in range(8):      # a fold graph has no chains; this is only a bound
        if not pending:
            break
        found.update(_members(con, sorted(pending)))
        pending = {e["canonical_event_id"] for e in found.values()
                   if e["canonical_event_id"] is not None} - set(found)
    return found


def _root_of(event_id: int, rows: dict[int, dict[str, Any]]) -> int:
    seen: set[int] = set()
    current = event_id
    while current not in seen and current in rows:
        seen.add(current)
        parent = rows[current]["canonical_event_id"]
        if parent is None:
            return current
        current = parent
    return current


def answer_options(pair: dict[str, Any]) -> list[tuple[str, int | None]]:
    """Every answer the Duplicates page can give a pair: (decision, kept)."""
    low, high = sorted((pair["event_id"], pair["other_event_id"]))
    return [(DUPLICATE, low), (DUPLICATE, high), (DISTINCT, None)]


def assess_pair(pair: dict[str, Any], rows: dict[int, dict[str, Any]],
                pair_index: dict[tuple[int, int], dict[str, Any]]) -> dict[str, Any]:
    """One pair's queue status, reasons and per-answer eligibility. Pure."""
    member_ids = sorted((pair["event_id"], pair["other_event_id"]))
    members = {i: rows[i] for i in member_ids if i in rows}
    answers = []
    for decision, keep in answer_options(pair):
        refusals, _, _ = resolve_blockers(pair, members, decision=decision,
                                          canonical_event_id=keep)
        answers.append({"action": _resolve_action(decision), "decision": decision,
                        "keep": keep, "available": not refusals,
                        "reasons": [r for r, _ in refusals],
                        "messages": [m for _, m in refusals]})
    available = [a for a in answers if a["available"]]
    refused = sorted({r for a in answers for r in a["reasons"]})

    current = None
    roots = [_root_of(i, rows) if i in rows else None for i in member_ids]
    successor = None
    notes: list[str] = []
    if pair["state"] != OPEN:
        status, primary = QUEUE_PERSON, REASON_ALREADY_RESOLVED
    elif len(members) < 2:
        status, primary = QUEUE_INVALID, REASON_TARGET_NOT_FOUND
    else:
        folded = [m for m in members.values() if m["canonical_event_id"] is not None]
        human_fold = any(m["duplicate_decided_by"] == HUMAN for m in folded)
        if folded and roots[0] == roots[1]:
            status = QUEUE_SUPERSEDED if human_fold else QUEUE_RULES
            primary = REASON_CANONICAL_CHANGED if human_fold else REASON_SAME_GROUP
        elif folded:
            status, primary = QUEUE_SUPERSEDED, REASON_CANONICAL_CHANGED
            successor = pair_index.get(tuple(sorted(roots)))
        else:
            current = classify(*members.values())
            if current is None:
                status, primary = QUEUE_STALE, REASON_NO_CURRENT_MATCH
            elif current["auto"]:
                status, primary = QUEUE_STALE, REASON_RULES_WOULD_MERGE
            elif available:
                status, primary = QUEUE_ACTIONABLE, None
            else:
                status, primary = QUEUE_BLOCKED, (refused[0] if refused else None)
        if current is None and status == QUEUE_STALE:
            notes.append("no duplicate rule pairs these two events any more")
    reasons = sorted(set(refused) | ({primary} if primary else set()))
    if status != QUEUE_ACTIONABLE and primary is None:
        primary = reasons[0] if reasons else None
    return {
        "pair_id": pair["pair_id"], "event_id": member_ids[0], "other_event_id": member_ids[1],
        "rule": pair["rule"], "state": pair["state"],
        "resolved_by": pair.get("resolved_by"), "resolved_at": pair.get("resolved_at"),
        "created_at": pair.get("created_at"),
        "event_date": next((m["event_date"] for m in members.values()), None),
        "current_rule": current["rule"] if current else None,
        "status": status, "primary_reason": primary, "reasons": reasons,
        "guidance": QUEUE_GUIDANCE[status], "notes": notes,
        "roots": roots,
        "successor_pair_id": successor["pair_id"] if successor else None,
        "successor_state": successor["state"] if successor else None,
        "answers": answers, "available": [a["action"] + (f":{a['keep']}" if a["keep"] else "")
                                          for a in available],
    }


def queue(con) -> list[dict[str, Any]]:
    """Every duplicate pair, assessed (`assess_pair`), date then pair order. Reads only."""
    with con.cursor() as cur:
        cur.execute("SELECT pair_id, event_id, other_event_id, rule, matched, differs, state, "
                    "  resolved_by, resolved_at, created_at FROM event_duplicate_pairs "
                    "ORDER BY pair_id")
        pairs = _rows(cur)
    ids = sorted({p["event_id"] for p in pairs} | {p["other_event_id"] for p in pairs})
    rows = _member_rows(con, ids)
    index: dict[tuple[int, int], dict[str, Any]] = {}
    for p in pairs:
        index.setdefault(tuple(sorted((p["event_id"], p["other_event_id"]))), p)
    assessed = [assess_pair(p, rows, index) for p in pairs]
    for item, pair in zip(assessed, pairs):
        item["matched"], item["differs"] = pair["matched"], pair["differs"]
        item["members"] = [rows[i] for i in (item["event_id"], item["other_event_id"])
                           if i in rows]
    return sorted(assessed, key=lambda a: (str(a["event_date"] or ""), a["pair_id"]))


def _standing_verdicts_by_pair(con) -> tuple[dict[int, list[dict]], set[int]]:
    """A person's verdicts not taken back, by the pair they answered, and the
    events carrying such a verdict without a pair (answers older than v0.96.40)."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT d.decision_id, d.event_id, d.decision, d.pair_id "
            "FROM event_duplicate_decisions d "
            "WHERE d.decided_by = %s AND d.rule = %s AND d.decision IN (%s, %s) "
            "  AND NOT EXISTS (SELECT 1 FROM event_duplicate_decisions r "
            "                  WHERE r.reverts_decision_id = d.decision_id)",
            (HUMAN, RULE_HUMAN_REVIEW, DUPLICATE, DISTINCT))
        found = _rows(cur)
    by_pair: dict[int, list[dict]] = {}
    unpaired: set[int] = set()
    for row in found:
        if row["pair_id"] is None:
            unpaired.add(row["event_id"])
        else:
            by_pair.setdefault(row["pair_id"], []).append(row)
    return by_pair, unpaired


def queue_integrity(con, assessed: list[dict[str, Any]]) -> dict[str, int]:
    """The queue's hard gates, each a count that must be 0 (v0.96.47)."""
    seen: dict[tuple[int, int], int] = {}
    with con.cursor() as cur:
        cur.execute("SELECT event_id, other_event_id FROM event_duplicate_pairs")
        stored = cur.fetchall()
    for low, high in stored:
        key = tuple(sorted((low, high)))
        seen[key] = seen.get(key, 0) + 1
    by_pair, unpaired = _standing_verdicts_by_pair(con)
    wrong_human = 0
    for item in assessed:
        standing = by_pair.get(item["pair_id"], [])
        decisions = {r["decision"] for r in standing}
        legacy = bool({item["event_id"], item["other_event_id"]} & unpaired)
        if item["state"] == OPEN:
            wrong_human += bool(standing)
        elif item["state"] == MERGED:
            wrong_human += not (decisions == {DUPLICATE} or (not standing and legacy))
        elif item["state"] == DISTINCT:
            wrong_human += not ((decisions == {DISTINCT} and len(standing) == 2)
                                or (not standing and legacy))
        else:
            wrong_human += 1
    actionable = [a for a in assessed if a["status"] == QUEUE_ACTIONABLE]
    return {
        "UNCLASSIFIED_DUPLICATE_PAIR": sum(1 for a in assessed
                                           if a["status"] not in QUEUE_STATUSES),
        "DUPLICATE_QUEUE_ENTRY": (sum(n - 1 for n in seen.values())
                                  + sum(1 for low, high in stored if low >= high)),
        "RESOLVED_MARKED_ACTIONABLE": sum(1 for a in actionable if a["state"] != OPEN),
        "INVALID_TARGET_MARKED_ACTIONABLE": sum(1 for a in actionable if len(a["members"]) < 2),
        "ACTIONABLE_WITHOUT_SAFE_PREVIEW": sum(1 for a in actionable if not a["available"]),
        "MISSING_PAIR_REASON": sum(1 for a in assessed
                                   if a["status"] != QUEUE_ACTIONABLE and not a["primary_reason"]),
        "INCORRECT_HUMAN_DECISION_STATE": wrong_human,
    }


def queue_counts(assessed: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in QUEUE_STATUSES}
    for item in assessed:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    counts["TOTAL"] = len(assessed)
    counts["OPEN"] = sum(1 for a in assessed if a["state"] == OPEN)
    return counts

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
