"""Evidence review cases: one place to see what is known before a person acts.

v0.96.44 found the two kinds of question a person has to settle by hand -
a festival two sources date differently (``event_conflicts``) and a protected
source whose stored Event the running engine never re-read
(``content_store.protected_review``) - and listed them on two pages. Neither
said how far the stored evidence actually goes, or which of the existing
decisions it would support. This module puts both kinds into one read-only
shape, a *case*:

* what is stored now (the Event rows, their candidates, whether a reader sees
  them);
* what the sources themselves said, field by field, as an evidence state -
  confirmed, conflicting, missing, unavailable - never filled in;
* and, separately, the *decision readiness* of each existing action
  (Review EDIT/CONFIRM, the Duplicates MERGE, a venue link): whether the
  evidence supports taking it, and why not.

Evidence confidence and decision readiness are kept apart on purpose. Two
titles that match are evidence; they do not make a MERGE ready. A poster
that contains 20:00 is evidence; it does not make 20:00 the Event's start
until a person has seen that the clock belongs to that Event's programme.
``READY_FOR_EXISTING_REVIEW`` therefore never means "approved": it means a
person can open the existing, audited Review page and decide there.

Nothing here writes. There is no case table: a case is derived each time from
the rows it describes, so its id is the thing it is about - ``conflict-A-B``
(the two event ids, smaller first, whichever order they are asked in) or
``source-N`` (the source item) - and it follows the rows through source
revisions and re-extraction. A case a person has already decided says so
and is not asked again.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from . import content_store, event_conflicts, events_api

UNKNOWN = "UNKNOWN"

# What kind of question a case is. A case carries every type that applies.
CROSS_SOURCE_CONFLICT = "CROSS_SOURCE_CONFLICT"
SOURCE_EVIDENCE_INSUFFICIENT = "SOURCE_EVIDENCE_INSUFFICIENT"
EXTRACTION_NOT_APPLIED = "EXTRACTION_NOT_APPLIED"
TIME_EVIDENCE_CONFLICT = "TIME_EVIDENCE_CONFLICT"
VENUE_EVIDENCE_CONFLICT = "VENUE_EVIDENCE_CONFLICT"
DATE_EVIDENCE_CONFLICT = "DATE_EVIDENCE_CONFLICT"

# Where a case stands. HUMAN_DECISION_RECORDED is the one that is no longer
# open: a person has acted on it, and that decision stands.
REVIEW_REQUIRED = "REVIEW_REQUIRED"
NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
READY_FOR_EXISTING_REVIEW = "READY_FOR_EXISTING_REVIEW"
NO_CORRECTION_RECOMMENDED = "NO_CORRECTION_RECOMMENDED"
CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
BLOCKED_BY_SAFETY_POLICY = "BLOCKED_BY_SAFETY_POLICY"
HUMAN_DECISION_RECORDED = "HUMAN_DECISION_RECORDED"
OPEN_STATUSES = (REVIEW_REQUIRED, NEEDS_MORE_EVIDENCE, READY_FOR_EXISTING_REVIEW,
                 CONFLICT_UNRESOLVED)

# How far one field's evidence goes.
EVIDENCE_CONFIRMED = "EVIDENCE_CONFIRMED"
EVIDENCE_CONFLICTING = "EVIDENCE_CONFLICTING"
EVIDENCE_MISSING = "EVIDENCE_MISSING"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
EXISTING_VALUE_SUPPORTED = "EXISTING_VALUE_SUPPORTED"
HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
NOT_APPLICABLE = "NOT_APPLICABLE"

# The stored start time against the poster's own clocks.
TIME_MATCHES_EVIDENCE = "STORED_TIME_MATCHES_EVIDENCE"
TIME_POTENTIAL_CONFLICT = "POTENTIAL_POSTER_TIME_CONFLICT"
TIME_EVIDENCE_INSUFFICIENT = "TIME_EVIDENCE_INSUFFICIENT"
TIME_EVIDENCE_NOT_READ = "TIME_EVIDENCE_NOT_READ"
TIME_NOT_STORED = "TIME_NOT_STORED"

# Whose clock a poster clock is.
OWNERSHIP_NOT_VERIFIED = "NOT_YET_VERIFIED"
OWNERSHIP_SINGLE_PROGRAMME = "SINGLE_DATE_SINGLE_PROGRAMME_POSTER"

# Whether the evidence supports taking one existing action.
NOT_READY = "NOT_READY"
NOT_RECOMMENDED = "NOT_RECOMMENDED"
AVAILABLE = "AVAILABLE"
NOT_OFFERED = "NOT_OFFERED"
NO_ACTION_NEEDED = "NO_ACTION_NEEDED"
BLOCKED = BLOCKED_BY_SAFETY_POLICY

PRIORITY_HIGH = event_conflicts.PRIORITY_HIGH
PRIORITY_MEDIUM = event_conflicts.PRIORITY_MEDIUM
PRIORITY_LOW = event_conflicts.PRIORITY_LOW
_PRIORITY_ORDER = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}
_STATUS_ORDER = {s: i for i, s in enumerate((
    CONFLICT_UNRESOLVED, REVIEW_REQUIRED, READY_FOR_EXISTING_REVIEW, NEEDS_MORE_EVIDENCE,
    NO_CORRECTION_RECOMMENDED, BLOCKED_BY_SAFETY_POLICY, HUMAN_DECISION_RECORDED))}

OCR_ORDER_NOTE = (
    "OCR reading order is not the poster's layout: a clock printed beside one "
    "date can be read out next to another.")


# --- reading a poster's clocks and dates --------------------------------------
#
# Deliberately plain: this reads what the stored OCR text says so a person can
# compare it with the Event, it never fills a field. Its errors must only ever
# make a verdict weaker - a misread date adds a date, and more dates mean an
# ownership that cannot be shown, never a match that was not there.

_CLOCK = re.compile(
    r"(?:(?P<half>pm|am|오후|오전)\s*)?(?<!\d)(?P<h>\d{1,2})\s*[:：]\s*(?P<m>[0-5]\d)(?!\d)",
    re.IGNORECASE)
_DATE = re.compile(
    r"(?<!\d)(?:(?P<y>20\d\d)\s*[.\-/년]\s*)?(?P<mo>\d{1,2})\s*(?:[./]|월\s*)\s*"
    r"(?P<d>\d{1,2})(?!\d)")
_DAY_MARKER = re.compile(r"\bDAY\s*\d", re.IGNORECASE)


def poster_clocks(text: str | None) -> list[dict[str, Any]]:
    """Every clock in an OCR text, in reading order, as 24-hour minutes.

    ``24:00`` is kept as 24:00: it closes a night and is never a start
    (v0.96.40), so it is marked ``end_of_night`` rather than read as 00:00.
    """
    found = []
    for match in _CLOCK.finditer(unicodedata.normalize("NFKC", text or "")):
        hour, minute = int(match["h"]), int(match["m"])
        half = (match["half"] or "").lower()
        if hour > 24 or (hour == 24 and minute):
            continue
        if half in ("pm", "오후") and hour < 12:
            hour += 12
        elif half in ("am", "오전") and hour == 12:
            hour = 0
        found.append({"pos": match.start(), "minutes": hour * 60 + minute,
                      "clock": f"{hour:02d}:{minute:02d}", "end_of_night": hour == 24})
    return found


def poster_dates(text: str | None) -> list[dict[str, Any]]:
    """Every month/day an OCR text states, in reading order."""
    found = []
    for match in _DATE.finditer(unicodedata.normalize("NFKC", text or "")):
        month, day = int(match["mo"]), int(match["d"])
        if 1 <= month <= 12 and 1 <= day <= 31:
            found.append({"pos": match.start(), "year": int(match["y"]) if match["y"] else None,
                          "month": month, "day": day})
    return found


def _clock_text(value: Any) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)[:5]


def _minutes(clock: str) -> int:
    hour, minute = clock.split(":")
    return int(hour) * 60 + int(minute)


def time_evidence(event: dict[str, Any], ocr_texts: list[str]) -> dict[str, Any]:
    """The stored start time beside what the item's posters say. Pure.

    ``STORED_TIME_MATCHES_EVIDENCE`` only when the poster states one date -
    the event's - no ``DAY n`` schedule, and the stored start is its earliest
    clock: then the poster has one programme day and the stored value is its
    start. ``POTENTIAL_POSTER_TIME_CONFLICT`` when the poster states clocks
    and none of them can be the stored start. ``TIME_EVIDENCE_INSUFFICIENT``
    when the stored clock is on the poster but the poster is a schedule of
    several dates or programmes, so whose clock it is cannot be read from the
    text. A potential value is offered only as the first clock after the
    event's date in reading order, and its ownership stays unverified unless
    the poster has a single date and a single programme clock.
    """
    stored = _clock_text(event.get("start_time"))
    texts = [t for t in ocr_texts if t and t.strip()]
    first = event.get("event_date")
    first = date.fromisoformat(str(first)[:10]) if first else None
    joined = "\n".join(texts)
    clocks = poster_clocks(joined)
    dates = poster_dates(joined)
    distinct_dates = sorted({(d["month"], d["day"]) for d in dates})
    starts = sorted({c["clock"] for c in clocks if not c["end_of_night"]
                     and c["minutes"] >= 6 * 60})
    event_day = (first.month, first.day) if first else None
    date_mentions = [d for d in dates if (d["month"], d["day"]) == event_day
                     and d["year"] in (None, first.year)]
    schedule = bool(_DAY_MARKER.search(joined))
    out: dict[str, Any] = {
        "stored_start": stored or UNKNOWN,
        "stored_end": _clock_text(event.get("end_time")) or UNKNOWN,
        "stored_time_evidence": event.get("time_evidence") or UNKNOWN,
        "posters_read": len(texts),
        "poster_dates": [f"{m:02d}-{d:02d}" for m, d in distinct_dates],
        "poster_clocks": starts,
        "event_date_on_poster": bool(date_mentions),
        "multi_day_schedule_marker": schedule,
        "potential": None,
        "ownership": OWNERSHIP_NOT_VERIFIED,
    }
    if not texts:
        return {**out, "verdict": TIME_EVIDENCE_NOT_READ, "state": SOURCE_UNAVAILABLE,
                "explanation": "No poster text was read for this item, so nothing stored "
                               "can confirm or contradict the time."}
    if out["event_date_on_poster"]:
        out["date_state"] = EVIDENCE_CONFIRMED
    elif distinct_dates:
        out["date_state"] = EVIDENCE_CONFLICTING
    else:
        out["date_state"] = EVIDENCE_MISSING
    if stored is None:
        return {**out, "verdict": TIME_NOT_STORED, "state": NOT_APPLICABLE,
                "explanation": "The Event stores no start time; there is nothing to verify."}
    if not clocks:
        return {**out, "verdict": TIME_EVIDENCE_INSUFFICIENT, "state": EVIDENCE_MISSING,
                "explanation": f"The poster text states no clock, so {stored} can be "
                               "neither confirmed nor contradicted by it. That is not "
                               "evidence that the event had no time."}
    single_day = distinct_dates == [event_day] and not schedule
    on_poster = [c for c in clocks if c["clock"] == stored and not c["end_of_night"]]
    only_as_end = stored == "00:00" and any(c["end_of_night"] for c in clocks)
    if on_poster:
        if single_day and starts and starts[0] == stored:
            return {**out, "verdict": TIME_MATCHES_EVIDENCE, "state": EXISTING_VALUE_SUPPORTED,
                    "ownership": OWNERSHIP_SINGLE_PROGRAMME if len(starts) == 1
                    else "SINGLE_DATE_POSTER_EARLIEST_CLOCK",
                    "explanation": f"The poster states one date ({first}) and {stored} is its "
                                   "earliest clock: the stored start matches the poster."}
        reasons = []
        if len(distinct_dates) > 1:
            reasons.append(f"the poster states {len(distinct_dates)} dates "
                           f"({', '.join(out['poster_dates'])})")
        if schedule:
            reasons.append("the poster is a DAY-numbered schedule")
        if not out["event_date_on_poster"]:
            reasons.append(f"the event's date {first} is not on the poster")
        if not reasons and starts and starts[0] != stored:
            reasons.append(f"{stored} is not the poster's earliest clock ({starts[0]})")
        return {**out, "verdict": TIME_EVIDENCE_INSUFFICIENT, "state": EVIDENCE_MISSING,
                "explanation": f"{stored} appears on the poster, but "
                               + "; ".join(reasons or ["its programme is not stated"])
                               + f", so which programme it belongs to is not shown. "
                               + OCR_ORDER_NOTE}
    # The stored clock is not one of the poster's starts.
    after = [c for c in clocks if not c["end_of_night"] and date_mentions
             and c["pos"] > date_mentions[0]["pos"]]
    potential = after[0]["clock"] if after else None
    ownership = (OWNERSHIP_SINGLE_PROGRAMME if single_day and len(starts) == 1
                 and potential == starts[0] else OWNERSHIP_NOT_VERIFIED)
    lead = (f"{stored} appears on the poster only as 24:00, the end of a night, which is "
            "never a start" if only_as_end else f"{stored} is not one of the poster's clocks")
    return {**out, "verdict": TIME_POTENTIAL_CONFLICT, "state": EVIDENCE_CONFLICTING,
            "potential": potential, "ownership": ownership,
            "explanation": lead + (
                f"; the first clock after {first} in reading order is {potential}"
                if potential else "") + (
                f". The poster states {len(starts)} clocks "
                f"({', '.join(starts)})" if len(starts) > 1 else "") + (
                "" if ownership == OWNERSHIP_SINGLE_PROGRAMME
                else ", so whether that clock is this Event's start needs a person. "
                + OCR_ORDER_NOTE)}


# --- protected source cases ---------------------------------------------------

def _ocr_texts(con, source_item_id: int) -> list[str]:
    with con.cursor() as cur:
        cur.execute("SELECT ocr_text FROM source_item_image WHERE source_item_id = %s "
                    "AND ocr_text IS NOT NULL AND ocr_text <> '' ORDER BY image_index",
                    (source_item_id,))
        return [r[0] for r in cur.fetchall()]


def _review_history(con, candidate_ids: list[int], source_item_id: int | None
                    ) -> list[dict[str, Any]]:
    if not candidate_ids and source_item_id is None:
        return []
    with con.cursor() as cur:
        cur.execute(
            "SELECT review_action_id, candidate_id, action, reviewer, reason, created_at "
            "FROM human_review_actions WHERE candidate_id = ANY(%s) OR source_item_id = %s "
            "ORDER BY created_at, review_action_id", (candidate_ids, source_item_id))
        names = [c.name for c in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


def _event_readiness(verdict: str, ownership: str) -> dict[str, dict[str, str]]:
    """What the time evidence supports, per existing Review action."""
    if verdict == TIME_MATCHES_EVIDENCE:
        return {
            "EDIT_TIME": {"readiness": NOT_RECOMMENDED,
                          "why": "the stored start matches the poster"},
            "CONFIRM": {"readiness": AVAILABLE,
                        "why": "optional: records that the stored values stand. Keeping "
                               "them needs no action at all."},
        }
    if verdict == TIME_POTENTIAL_CONFLICT:
        if ownership == OWNERSHIP_SINGLE_PROGRAMME:
            return {
                "EDIT_TIME": {"readiness": AVAILABLE,
                              "why": "the poster has one date and one programme clock; a "
                                     "person checks the image and decides in Review EDIT"},
                "CONFIRM": {"readiness": NOT_RECOMMENDED,
                            "why": "the stored start conflicts with the poster"},
            }
        return {
            "EDIT_TIME": {"readiness": NOT_READY,
                          "why": "a person must first confirm from the poster image which "
                                 "programme this Event is; the clock's ownership is not "
                                 "verified"},
            "CONFIRM": {"readiness": NOT_RECOMMENDED,
                        "why": "the stored start conflicts with the poster"},
        }
    return {
        "EDIT_TIME": {"readiness": NOT_READY,
                      "why": "no stored evidence settles a different value; do not clear "
                             "the stored time for lack of evidence"},
        "CONFIRM": {"readiness": NOT_RECOMMENDED,
                    "why": "it would record an unverified value as checked"},
    }


def protected_case(con, settings, source_item_id: int, *, today: date | None = None
                   ) -> dict[str, Any] | None:
    """The case for one protected (or otherwise not-re-read) source item."""
    from . import engine_ingest  # local: engine_ingest imports the engine lazily

    today = today or events_api.today()
    detail = content_store.detail(con, source_item_id)
    if detail is None:
        return None
    fresh = engine_ingest.freshness(settings, con, source_item_id) or {}
    review = content_store.protected_review(con, source_item_id, fresh)
    if not review["events"] and not review["review_recommended"]:
        return None
    texts = _ocr_texts(con, source_item_id)
    candidate_ids = sorted({*review["candidate_ids"],
                            *(e["candidate_id"] for e in review["events"]
                              if e.get("candidate_id"))})
    history = _review_history(con, candidate_ids, source_item_id)
    content = detail.get("content") or {}
    blocked = content.get("acquisition_status") == "FETCH_BLOCKED"
    not_applied = fresh.get("state") == content_store.ENGINE_UPDATE_NOT_APPLIED

    events = []
    for event in review["events"]:
        evidence = time_evidence(event, texts)
        events.append({
            "event_id": event["event_id"],
            "candidate_id": event.get("candidate_id"),
            "event_name": event.get("event_name"),
            "event_date": event.get("event_date"),
            "end_date": event.get("end_date"),
            "start_time": _clock_text(event.get("start_time")),
            "end_time": _clock_text(event.get("end_time")),
            "end_day_offset": event.get("end_day_offset"),
            "venue_text": event.get("venue_text") or UNKNOWN,
            "venue_id": event.get("venue_id"),
            "listing_state": event.get("listing_state"),
            "canonical_event_id": event.get("canonical_event_id"),
            "public_now": event["public_now"],
            "not_ended": bool(event.get("not_ended")),
            "time": evidence,
            "readiness": _event_readiness(evidence["verdict"], evidence["ownership"]),
        })

    types = []
    if not_applied:
        types.append(EXTRACTION_NOT_APPLIED)
    verdicts = {e["time"]["verdict"] for e in events}
    if TIME_POTENTIAL_CONFLICT in verdicts:
        types.append(TIME_EVIDENCE_CONFLICT)
    if verdicts & {TIME_EVIDENCE_INSUFFICIENT, TIME_EVIDENCE_NOT_READ}:
        types.append(SOURCE_EVIDENCE_INSUFFICIENT)
    if any(e["time"].get("date_state") == EVIDENCE_CONFLICTING for e in events):
        types.append(DATE_EVIDENCE_CONFLICT)

    if history:
        status = HUMAN_DECISION_RECORDED
    elif not events:
        status = NEEDS_MORE_EVIDENCE
    elif TIME_POTENTIAL_CONFLICT in verdicts:
        status = (READY_FOR_EXISTING_REVIEW
                  if all(e["readiness"]["EDIT_TIME"]["readiness"] == AVAILABLE
                         for e in events if e["time"]["verdict"] == TIME_POTENTIAL_CONFLICT)
                  else REVIEW_REQUIRED)
    elif verdicts <= {TIME_MATCHES_EVIDENCE, TIME_NOT_STORED} and \
            TIME_MATCHES_EVIDENCE in verdicts:
        status = NO_CORRECTION_RECOMMENDED
    else:
        status = NEEDS_MORE_EVIDENCE

    reasons = []
    if any(e["public_now"] for e in events):
        reasons.append("shown to readers now")
    if any(e["not_ended"] for e in events):
        reasons.append("upcoming")
    if TIME_POTENTIAL_CONFLICT in verdicts:
        reasons.append("stored time conflicts with the poster")
    if status in (HUMAN_DECISION_RECORDED, NO_CORRECTION_RECOMMENDED):
        priority = PRIORITY_LOW
    elif any(e["public_now"] for e in events):
        priority = PRIORITY_HIGH
    elif any(e["not_ended"] for e in events) or (
            TIME_POTENTIAL_CONFLICT in verdicts
            and any(e["listing_state"] == "LISTED" for e in events)):
        priority = PRIORITY_MEDIUM
    else:
        priority = PRIORITY_LOW
    if not reasons:
        reasons.append("past events, not shown to readers")

    actions = [{"action": f"Review candidate {cid}", "href": f"/admin/review/{cid}",
                "kind": "existing review (EDIT / CONFIRM, audited)"}
               for cid in candidate_ids]
    actions.append({"action": f"Source item {source_item_id} diagnostics",
                    "href": f"/admin/intake/{source_item_id}", "kind": "read only"})
    actions += [{"action": f"Event #{e['event_id']} sources",
                 "href": f"/admin/events/{e['event_id']}/sources", "kind": "read only"}
                for e in events]
    blocked_actions = []
    if blocked:
        blocked_actions.append({
            "action": "Re-fetch the source", "readiness": BLOCKED,
            "why": "the source is FETCH_BLOCKED; this review never fetches it"})
    if not_applied:
        blocked_actions.append({
            "action": "Re-extract with the running engine", "readiness": BLOCKED,
            "why": "the held input is less than what the Event was read from; "
                   "re-reading it could only lose fields (v0.96.42)"})

    return {
        "case_id": f"source-{source_item_id}",
        "kind": "PROTECTED_SOURCE",
        "types": types,
        "status": status,
        "priority": priority,
        "priority_reasons": reasons,
        "title": detail.get("title") or UNKNOWN,
        "source_item_ids": [source_item_id],
        "event_ids": [e["event_id"] for e in events],
        "candidate_ids": candidate_ids,
        "public_now": sum(1 for e in events if e["public_now"]),
        "source": {
            "source_item_id": source_item_id,
            "source_name": detail.get("source_name") or UNKNOWN,
            "source_url": events_api.valid_public_url(detail.get("url")) or UNKNOWN,
            "acquisition_status": content.get("acquisition_status") or UNKNOWN,
            "freshness": fresh.get("state") or UNKNOWN,
            "flags": list(fresh.get("flags") or []),
            "posters_read": len(texts),
            "article_text_held": review["evidence"]["article_text_held"],
        },
        "events": events,
        "unverifiable": review["unverifiable"],
        "human_history": history,
        "available_actions": actions,
        "blocked_actions": blocked_actions,
        "facts_kept_apart": [
            "Poster contains a time != Event time confirmed",
            "Engine version current != latest engine logic applied"
            + (" (this item: ENGINE_UPDATE_NOT_APPLIED)" if not_applied else ""),
            "Review case listed != human decision approved",
        ],
    }


# --- cross-source conflict cases ----------------------------------------------

_PART_SPLIT = re.compile(r"\s*(?:·|/|,|\||&| and | 및 )\s*")


def _plain(text: str | None) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text or "").lower())


def venue_parts(text: str | None, known: list[str]) -> list[dict[str, Any]]:
    """The names a raw venue string lists, each beside what it resembles.

    A resemblance is spelling only (case, spaces and punctuation set aside).
    It never links a row: ``ELTANGO`` resembling ``El Tango`` is a question
    for the Venue Master, and the other name may be a second room or the
    organiser.
    """
    parts = [p for p in _PART_SPLIT.split(text or "") if p.strip()]
    plain_known = {_plain(k): k for k in known if k}
    return [{"text": p, "resembles": plain_known.get(_plain(p)),
             "role": UNKNOWN} for p in parts]


def _human_pair_decision(con, low: int, high: int) -> list[dict[str, Any]]:
    """Standing human duplicate verdicts that settle this exact pair."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT d.decision_id, d.event_id, d.canonical_event_id, d.decision, d.reviewer, "
            "  d.created_at FROM event_duplicate_decisions d "
            "LEFT JOIN event_duplicate_pairs p ON p.pair_id = d.pair_id "
            "WHERE d.decided_by = 'HUMAN' AND d.decision <> 'REVERT' "
            "  AND ((d.event_id = %s AND d.canonical_event_id = %s) "
            "    OR (d.event_id = %s AND d.canonical_event_id = %s) "
            "    OR (p.event_id = %s AND p.other_event_id = %s)) "
            "  AND NOT EXISTS (SELECT 1 FROM event_duplicate_decisions r "
            "                  WHERE r.reverts_decision_id = d.decision_id) "
            "ORDER BY d.decision_id", (low, high, high, low, low, high))
        names = [c.name for c in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


def _revisions(con, item_ids: list[int]) -> dict[int, dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT c.source_item_id, c.refresh_revised_at, c.refresh_outcome, "
            "  (SELECT count(*) FROM content_fetch_log f WHERE f.source_item_id = "
            "   c.source_item_id AND f.refresh_result = 'REVISED') "
            "FROM source_item_content c WHERE c.source_item_id = ANY(%s)", (item_ids,))
        return {r[0]: {"last_revised_at": r[1], "last_refresh": r[2] or UNKNOWN,
                       "revisions_recorded": int(r[3])} for r in cur.fetchall()}


def _questions(found: dict[str, Any], revisions: dict[int, dict[str, Any]]
               ) -> list[dict[str, str]]:
    left, right = found["left"], found["right"]
    ev = found["evidence"]
    out = []
    for event in (left, right):
        stated = ev[event["event_id"]]["date_evidence"]
        out.append({
            "question": f"Is {event['event_date']} the whole festival's first day "
                        f"({event.get('source_name') or 'source'})?",
            "evidence": f"the source's own record states {stated['stated_start']} ~ "
                        f"{stated['stated_end']}",
            "answer": UNKNOWN})
    for event in (left, right):
        if ev[event["event_id"]]["date_evidence"]["stated_end"] == UNKNOWN:
            out.append({
                "question": f"Did {event.get('source_name') or 'a source'} leave out the "
                            "festival's full period?",
                "evidence": "it states a first day and no last day",
                "answer": UNKNOWN})
    out.append({
        "question": "Is the later first day one programme of the festival (an opening "
                    "night, a registration day)?",
        "evidence": "no stored record names a programme for either first day",
        "answer": UNKNOWN})
    out.append({
        "question": "Are these two different editions or occurrences?",
        "evidence": f"both state the same year; the periods are {found['gap_days']} day(s) "
                    "apart",
        "answer": UNKNOWN})
    for event in (left, right):
        rev = revisions.get(event.get("source_item_id")) or {}
        out.append({
            "question": f"Has {event.get('source_name') or 'the source'}'s record been "
                        "revised?",
            "evidence": (f"{rev['revisions_recorded']} revision(s) recorded, last re-check "
                         f"{rev['last_refresh']}" if rev else "no refresh record"),
            "answer": "YES" if rev.get("revisions_recorded") else UNKNOWN})
    matched = found["matched"]
    independent = [m for m in matched if m not in ("event_type", "name", "years")]
    out.append({
        "question": "Is there independent evidence that both are one event?",
        "evidence": ("matched on " + ", ".join(matched) + " and an overlapping period only"
                     if not independent else "matched on " + ", ".join(matched)),
        "answer": "YES" if independent else "NONE_STORED"})
    return out


def conflict_case(con, left_id: int, right_id: int, *, today: date | None = None
                  ) -> dict[str, Any] | None:
    """The case for one cross-source conflict pair, or None when it is not one."""
    found = event_conflicts.compare(con, left_id, right_id, today=today)
    if found is None:
        return None
    left, right = found["left"], found["right"]
    low, high = left["event_id"], right["event_id"]
    decisions = _human_pair_decision(con, low, high)
    item_ids = [i for i in (left.get("source_item_id"), right.get("source_item_id"))
                if i is not None]
    revisions = _revisions(con, item_ids)
    candidate_ids = [c for c in (left.get("candidate_id"), right.get("candidate_id"))
                     if c is not None]
    history = _review_history(con, candidate_ids, None)

    known_names = []
    if any(e.get("venue_id") for e in (left, right)):
        with con.cursor() as cur:
            cur.execute("SELECT v.name FROM venues v WHERE v.venue_id = ANY(%s) UNION "
                        "SELECT a.alias FROM venue_aliases a WHERE a.venue_id = ANY(%s)",
                        ([e["venue_id"] for e in (left, right) if e.get("venue_id")],) * 2)
            known_names = [r[0] for r in cur.fetchall()]
    venues = {}
    for event in (left, right):
        resolved = (f"{event.get('venue_name') or UNKNOWN} (venue {event['venue_id']})"
                    if event.get("venue_id") else "UNRESOLVED")
        parts = venue_parts(event.get("venue_text"), known_names) \
            if not event.get("venue_id") else []
        venues[event["event_id"]] = {
            "raw_venue_text": event.get("venue_text") or UNKNOWN,
            "resolved_venue": resolved,
            "other_mentioned": [p for p in parts] if len(parts) > 1 else [],
            "evidence_source": f"{event.get('source_name') or UNKNOWN}'s own record",
            "verification_status": event.get("venue_status") or UNKNOWN,
        }

    conflicts = found["conflicts"]
    types = [CROSS_SOURCE_CONFLICT]
    if {event_conflicts.DATE_CONFLICT, event_conflicts.DATE_RANGE_CONFLICT} & set(conflicts):
        types.append(DATE_EVIDENCE_CONFLICT)
    if {event_conflicts.VENUE_CONFLICT, event_conflicts.VENUE_UNRESOLVED} & set(conflicts):
        types.append(VENUE_EVIDENCE_CONFLICT)
    blockers = [c for c in conflicts if c in (
        event_conflicts.DATE_CONFLICT, event_conflicts.DATE_RANGE_CONFLICT,
        event_conflicts.SOURCE_EVIDENCE_CONFLICT, event_conflicts.VENUE_CONFLICT,
        event_conflicts.VENUE_UNRESOLVED)]
    readiness = {
        "MERGE": {"readiness": NOT_READY if not decisions else NOT_OFFERED,
                  "merge_ready": False,
                  "why": ("unresolved: " + ", ".join(blockers) + ". "
                          + event_conflicts.MERGE_NOT_OFFERED)},
        "KEEP_SEPARATE": {"readiness": NO_ACTION_NEEDED,
                          "why": event_conflicts.KEEP_SEPARATE_NOTE},
        "DATE_CORRECTION": {"readiness": NOT_READY,
                            "why": "no stored evidence settles which first day is right; "
                                   "a date only a person can settle goes through Review "
                                   "EDIT on that event's candidate"},
        "VENUE_LINK": {"readiness": NOT_READY if any(not e.get("venue_id")
                                                     for e in (left, right))
                       else NOT_APPLICABLE,
                       "why": "the unresolved text names more than one place or "
                              "organisation; a resemblance is not a link, and linking "
                              "goes through the Venue review with its own preview"},
    }
    status = HUMAN_DECISION_RECORDED if decisions else CONFLICT_UNRESOLVED
    reasons = []
    if all(found["public_now"].values()):
        reasons.append("both rows shown to readers now")
    elif any(found["public_now"].values()):
        reasons.append("one row shown to readers now")
    if max(event_conflicts.period(e)[1] for e in (left, right)) >= \
            (today or events_api.today()):
        reasons.append("upcoming")
    reasons += [c for c in blockers]
    actions = [{"action": "Compare the two events", "href":
                f"/admin/conflicts/{low}/{high}", "kind": "read only"}]
    actions += [{"action": f"Event #{e['event_id']} sources",
                 "href": f"/admin/events/{e['event_id']}/sources", "kind": "read only"}
                for e in (left, right)]
    actions += [{"action": f"Review candidate {cid}", "href": f"/admin/review/{cid}",
                 "kind": "existing review (EDIT / CONFIRM, audited)"}
                for cid in candidate_ids]
    actions += [{"action": f"Source item {i} diagnostics", "href": f"/admin/intake/{i}",
                 "kind": "read only"} for i in item_ids]
    if any(not e.get("venue_id") for e in (left, right)):
        actions.append({"action": "Unresolved venues", "href": "/admin/venues/unresolved",
                        "kind": "existing venue review (preview, then confirm)"})

    return {
        "case_id": f"conflict-{low}-{high}",
        "kind": "CROSS_SOURCE",
        "types": types,
        "status": status,
        "priority": PRIORITY_LOW if decisions else found["priority"],
        "priority_reasons": reasons,
        "title": left.get("event_name") or UNKNOWN,
        "source_item_ids": item_ids,
        "event_ids": [low, high],
        "candidate_ids": candidate_ids,
        "public_now": sum(1 for v in found["public_now"].values() if v),
        "assessment": found["assessment"],
        "conflicts": conflicts,
        "evidence_confidence": [found["assessment"]] + (
            [] if decisions else [NEEDS_MORE_EVIDENCE]),
        "fields": found["fields"],
        "evidence": found["evidence"],
        "venues": venues,
        "questions": _questions(found, revisions),
        "revisions": revisions,
        "related": found["related"],
        "if_merged": found["if_merged"],
        "if_separate": found["if_separate"],
        "human_decisions": decisions,
        "human_history": history,
        "readiness": readiness,
        "available_actions": actions,
        "blocked_actions": [],
        "facts_kept_apart": [
            "Same name != same event",
            "Review case listed != human decision approved",
            "A venue name that resembles another != the same venue",
        ],
    }


# --- every case ---------------------------------------------------------------

def summary_of(case: dict[str, Any]) -> dict[str, Any]:
    return {k: case[k] for k in ("case_id", "kind", "types", "status", "priority",
                                 "priority_reasons", "title", "event_ids",
                                 "source_item_ids", "candidate_ids", "public_now")}


def all_cases(con, settings, *, today: date | None = None) -> list[dict[str, Any]]:
    """Every case, full detail, most urgent first. Reads only."""
    today = today or events_api.today()
    found = []
    for pair in event_conflicts.find(con, today=today):
        case = conflict_case(con, pair["left"]["event_id"], pair["right"]["event_id"],
                             today=today)
        if case is not None:
            found.append(case)
    rows = content_store.listing(con, extraction="REVIEW",
                                 engine_version=settings.engine_version)
    for row in rows:
        case = protected_case(con, settings, row["source_item_id"], today=today)
        if case is not None:
            found.append(case)
    found.sort(key=lambda c: (_PRIORITY_ORDER[c["priority"]], _STATUS_ORDER[c["status"]],
                              c["case_id"]))
    return found


def cases(con, settings, *, today: date | None = None) -> list[dict[str, Any]]:
    return [summary_of(c) for c in all_cases(con, settings, today=today)]


FLAG_REVIEW = content_store.FLAG_REVIEW_RECOMMENDED
_CASE_ID = re.compile(r"^(?:conflict-(\d{1,18})-(\d{1,18})|source-(\d{1,18}))$")


def parse_case_id(case_id: str) -> tuple[str, tuple[int, ...]] | None:
    match = _CASE_ID.match(case_id or "")
    if not match:
        return None
    if match.group(3):
        return "source", (int(match.group(3)),)
    return "conflict", tuple(sorted((int(match.group(1)), int(match.group(2)))))


def case(con, settings, case_id: str, *, today: date | None = None) -> dict[str, Any] | None:
    """One case by id, or None. ``conflict-B-A`` is the same case as ``conflict-A-B``.

    A source item is a case only while it is a protected review item or a
    person has decided it - an arbitrary item id is not presented as a
    question.
    """
    parsed = parse_case_id(case_id)
    if parsed is None:
        return None
    kind, ids = parsed
    if kind == "conflict":
        return conflict_case(con, ids[0], ids[1], today=today)
    found = protected_case(con, settings, ids[0], today=today)
    if found is None:
        return None
    if FLAG_REVIEW not in found["source"]["flags"] and found["status"] != \
            HUMAN_DECISION_RECORDED:
        return None
    return found



def metrics(all_found: list[dict[str, Any]]) -> dict[str, int]:
    """The release report's counts, from a list of full cases."""
    def count(pred):
        return sum(1 for c in all_found if pred(c))
    return {
        "total": len(all_found),
        "cross_source": count(lambda c: c["kind"] == "CROSS_SOURCE"),
        "protected_source": count(lambda c: c["kind"] == "PROTECTED_SOURCE"),
        "evidence_sufficient": count(lambda c: c["status"] in (
            NO_CORRECTION_RECOMMENDED, READY_FOR_EXISTING_REVIEW)),
        "needs_more_evidence": count(lambda c: c["status"] in (
            NEEDS_MORE_EVIDENCE, REVIEW_REQUIRED, CONFLICT_UNRESOLVED)),
        "no_correction_recommended": count(lambda c: c["status"] == NO_CORRECTION_RECOMMENDED),
        "human_decision_recorded": count(lambda c: c["status"] == HUMAN_DECISION_RECORDED),
        "open": count(lambda c: c["status"] in OPEN_STATUSES),
    }
