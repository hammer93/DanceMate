"""Cross-source event conflicts: one festival, two sources, two different dates.

The duplicate rules (``duplicates``) only ever compare events that share a
date, which is what keeps a weekly milonga from collapsing into one row. Their
cost is a blind spot for festivals: two calendars recording one tango week
under two different first days are never compared at all. Found on
Production at v0.96.43: Miltang records ``2026 Seoul Tango Week`` as
2026-11-11 ~ 2026-11-16 at El Tango, and TangoNOW records ``SEOUL TANGO WEEK
2026`` from 2026-11-12 at ``ELTANGO · Seoul Tango Academy``, a place nothing
has resolved. Both are listed. They may be one festival - an opening day and a
first public night, a moved date, a registration day - or two; nothing stored
settles it.

This module finds such pairs and lays out what each source said. It decides
nothing and writes nothing: there is no table, no verdict and no merge. A
pair here is a fact that needs a person, never a conclusion - which is also
why it is not offered to the Duplicates page's MERGE. That merge keeps the
canonical row's dates and hides the other row, so for two records whose dates
disagree it would choose a date by row age, not by evidence.

Only FESTIVAL rows are compared (v0.96.41: a festival, marathon or tango week
with a stated period and no clock). A night is never a candidate, and a
festival is never paired with a night: the welcome milonga of a tango week
shares its room and its first day and is one of the things the week is made
of. A weekly milonga's rows a day apart are different nights, which is the
reason the duplicate rules never compare dates in the first place.

A pair needs all of:

* two FESTIVAL rows from two different sources, neither rejected;
* the same name once case, punctuation, word order and year are set aside -
  every other word, including a qualifier such as ``(포항)`` or ``(홍대)``,
  must match, so two programmes of one series are not one festival and a
  title that merely shares words is not a match;
* the same year when both names state one (two editions are two festivals);
* periods no more than ``MAX_GAP_DAYS`` apart (a period without a stated end
  is its first day);
* no stated region or place naming cities that exclude each other, and the
  same genre when both carry one;
* and an actual disagreement: different first days, or two stated last days
  that differ. Two records that agree on their first day are the duplicate
  rules' to settle, and they do.

Rows are bucketed by that name before any pair is formed, so the work is
linear in the number of festival rows plus the pairs inside one name.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from . import events_api, venue_identity

FESTIVAL = "FESTIVAL"
MAX_GAP_DAYS = 3

# What differs, as facts. A pair carries every one that applies.
DATE_CONFLICT = "DATE_CONFLICT"
DATE_RANGE_CONFLICT = "DATE_RANGE_CONFLICT"
VENUE_CONFLICT = "VENUE_CONFLICT"
VENUE_UNRESOLVED = "VENUE_UNRESOLVED"
SOURCE_EVIDENCE_CONFLICT = "SOURCE_EVIDENCE_CONFLICT"

# How far the stored evidence goes - never further than "possibly".
POSSIBLE_SAME_EVENT = "POSSIBLE_SAME_EVENT"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
UNKNOWN = "UNKNOWN"

PRIORITY_HIGH = "HIGH"      # both rows are shown to readers now
PRIORITY_MEDIUM = "MEDIUM"  # not ended, at most one of them shown
PRIORITY_LOW = "LOW"        # over

MERGE_NOT_OFFERED = (
    "The Duplicates MERGE keeps the canonical row's dates and hides the other "
    "row, so for two records whose dates disagree it would pick a date by row "
    "age instead of evidence. It is not offered for this pair.")
KEEP_SEPARATE_NOTE = (
    "Both rows are already listed separately; that is what keeping them apart "
    "looks like, and nothing needs recording for it.")
FOLLOW_UP = (
    "Confirm the dates with the organiser or each source's own page. When a "
    "source corrects its record, the source revision path (v0.96.42) re-reads "
    "it on the next collection. A date that only a person can settle is "
    "corrected through Review EDIT on that event's candidate, which is "
    "audited in human_review_actions.")

_YEAR = re.compile(r"^(19|20)\d\d$")
_WORD = re.compile(r"\w+", re.UNICODE)


def name_key(name: str | None) -> tuple[tuple[str, ...], frozenset[str]]:
    """(the name's words without years, sorted; the years it states).

    ``2026 Seoul Tango Week`` and ``SEOUL TANGO WEEK 2026`` share one key;
    ``KOREA SPECIAL TANGO WEEK 2026 (포항)`` keeps ``포항`` and does not share
    a key with the ``(홍대)`` programme or with the series name alone.
    """
    text = unicodedata.normalize("NFKC", name or "").lower()
    words, years = [], set()
    for word in _WORD.findall(text.replace("_", " ")):
        bare = word.removesuffix("년")
        if _YEAR.match(bare):
            years.add(bare)
        else:
            words.append(word)
    return tuple(sorted(words)), frozenset(years)


def _as_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def period(event: dict[str, Any]) -> tuple[date, date]:
    """First and last day, the last being the first when no end is stated."""
    first = _as_date(event["event_date"])
    last = _as_date(event.get("last_day") or event.get("end_date")) or first
    return first, max(first, last)


def gap_days(left: dict[str, Any], right: dict[str, Any]) -> int:
    (a0, a1), (b0, b1) = period(left), period(right)
    return max(0, (b0 - a1).days, (a0 - b1).days)


def _stated_period(event: dict[str, Any]) -> dict[str, Any] | None:
    raw = event.get("source_period")
    return raw if isinstance(raw, dict) and raw.get("start") else None


def classify(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """The conflict between two festival rows, or None when they are not a pair.

    Pure: works on the dicts ``find()`` builds and on plain test dicts.
    """
    if any((e.get("event_type") or "").upper() != FESTIVAL for e in (left, right)):
        return None
    if any((e.get("review_state") or "").upper() == "REJECTED" for e in (left, right)):
        return None
    if left.get("source_id") is None or right.get("source_id") is None \
            or left["source_id"] == right["source_id"]:
        return None
    (left_words, left_years), (right_words, right_years) = (
        name_key(left.get("event_name")), name_key(right.get("event_name")))
    if not left_words or left_words != right_words:
        return None
    if left_years and right_years and left_years != right_years:
        return None
    for stated, other in ((left_years, right), (right_years, left)):
        if stated and str(period(other)[0].year) not in stated \
                and str(period(other)[1].year) not in stated:
            return None
    if gap_days(left, right) > MAX_GAP_DAYS:
        return None
    if left.get("region_id") is not None and right.get("region_id") is not None \
            and left["region_id"] != right["region_id"]:
        return None
    if venue_identity.texts_contradict(left.get("venue_text"), right.get("venue_text")):
        return None
    if left.get("genre_id") is not None and right.get("genre_id") is not None \
            and left["genre_id"] != right["genre_id"]:
        return None

    conflicts: list[str] = []
    left_first, right_first = _as_date(left["event_date"]), _as_date(right["event_date"])
    left_end, right_end = _as_date(left.get("end_date")), _as_date(right.get("end_date"))
    if left_first != right_first:
        conflicts.append(DATE_CONFLICT)
    if left_end is not None and right_end is not None and left_end != right_end:
        conflicts.append(DATE_RANGE_CONFLICT)
    if not conflicts:
        return None  # the same first day: the duplicate rules' to settle
    stated = [_stated_period(e) for e in (left, right)]
    if all(stated) and (stated[0]["start"] != stated[1]["start"]
                        or (stated[0].get("end") and stated[1].get("end")
                            and stated[0]["end"] != stated[1]["end"])):
        # The sources' own structured records disagree - not a misreading here.
        conflicts.append(SOURCE_EVIDENCE_CONFLICT)
    venues = (left.get("venue_id"), right.get("venue_id"))
    if venues[0] is not None and venues[1] is not None:
        venue = "SAME_RESOLVED_VENUE" if venues[0] == venues[1] else VENUE_CONFLICT
    else:
        venue = VENUE_UNRESOLVED
    if venue != "SAME_RESOLVED_VENUE":
        conflicts.append(venue)

    overlapping = gap_days(left, right) == 0
    assessment = (POSSIBLE_SAME_EVENT if overlapping and venue != VENUE_CONFLICT
                  else INSUFFICIENT_EVIDENCE)
    return {
        "conflicts": conflicts,
        "venue": venue,
        "assessment": assessment,
        "review": HUMAN_REVIEW_REQUIRED,
        "gap_days": gap_days(left, right),
        "matched": ["event_type", "name", "years"] + (["venue_id"] if venue ==
                                                       "SAME_RESOLVED_VENUE" else []),
    }


# --- reading the rows ---------------------------------------------------------

_SELECT = (
    "SELECT e.event_id, e.candidate_id, e.event_name, e.event_type, e.event_date, "
    "  e.end_date, " + events_api.LAST_DAY + " AS last_day, e.start_time, e.end_time, "
    "  e.venue_id, e.venue_text, e.venue_status, e.region_id, e.genre_id, "
    "  e.canonical_event_id, e.listing_state, e.review_state, e.provenance, "
    "  e.duplicate_decided_by, e.source_item_id, e.primary_source_item_id, e.source_url, "
    "  e.normalized_at, "
    "  v.name AS venue_name, r.code AS region_code, r.name AS region_name, "
    "  i.source_id, i.url AS item_url, i.title AS item_title, i.collected_at, "
    "  i.raw -> 'event_period' AS source_period, i.raw ->> 'festival_evidence' "
    "    AS festival_evidence, "
    "  s.source_key, s.name AS source_name, "
    "  c.reprocessed_at, c.acquisition_status, "
    "  (SELECT count(*) FROM events f WHERE f.canonical_event_id = e.event_id) AS folded "
    "FROM events e "
    "LEFT JOIN venues v ON v.venue_id = e.venue_id "
    "LEFT JOIN regions r ON r.region_id = e.region_id "
    "LEFT JOIN source_items i ON i.source_item_id = e.source_item_id "
    "LEFT JOIN sources s ON s.source_id = i.source_id "
    "LEFT JOIN source_item_content c ON c.source_item_id = e.source_item_id "
)


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _festivals(con, *, ids: list[int] | None = None) -> list[dict[str, Any]]:
    where = "e.event_type = %s AND e.review_state <> 'REJECTED'"
    params: list[Any] = [FESTIVAL]
    if ids is not None:
        where += " AND e.event_id = ANY(%s)"
        params.append(ids)
    with con.cursor() as cur:
        cur.execute(_SELECT + "WHERE " + where + " ORDER BY e.event_date, e.event_id",
                    tuple(params))
        return _rows(cur)


def _public(event: dict[str, Any], today: date) -> bool:
    """events_api's _VISIBLE plus "not over yet" - what a reader is shown."""
    return (event.get("provenance") == "LIVE" and event.get("listing_state") == "LISTED"
            and event.get("canonical_event_id") is None and period(event)[1] >= today)


def _priority(left: dict[str, Any], right: dict[str, Any], today: date) -> str:
    if max(period(left)[1], period(right)[1]) < today:
        return PRIORITY_LOW
    if _public(left, today) and _public(right, today):
        return PRIORITY_HIGH
    return PRIORITY_MEDIUM


def find(con, *, today: date | None = None) -> list[dict[str, Any]]:
    """Every conflict pair among the festival rows. Reads only.

    A row folded into another is compared as part of its group's canonical
    row (whose last day already counts the folded rows' periods), except
    that a fold whose own stated period disagrees with its canonical's is
    itself a pair: the merge stands, and the disagreement is still shown.
    """
    today = today or events_api.today()
    rows = _festivals(con)
    by_id = {r["event_id"]: r for r in rows}
    buckets: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        if row["canonical_event_id"] is None:
            buckets.setdefault(name_key(row["event_name"])[0], []).append(row)
    found: list[dict[str, Any]] = []
    for members in buckets.values():
        for index, left in enumerate(members):
            for right in members[index + 1:]:
                finding = classify(left, right)
                if finding:
                    found.append(_pair(left, right, finding, today))
    for row in rows:
        head = by_id.get(row["canonical_event_id"]) if row["canonical_event_id"] else None
        if head is None:
            continue
        own = dict(head, last_day=head.get("end_date"))
        finding = classify(own, dict(row, last_day=row.get("end_date")))
        if finding:
            found.append(_pair(head, row, finding, today))
    order = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}
    found.sort(key=lambda p: (order[p["priority"]], str(p["left"]["event_date"]),
                              p["left"]["event_id"], p["right"]["event_id"]))
    return found


def _pair(left: dict[str, Any], right: dict[str, Any], finding: dict[str, Any],
          today: date) -> dict[str, Any]:
    left, right = sorted((left, right), key=lambda e: e["event_id"])
    folded = right.get("canonical_event_id") == left["event_id"] \
        or left.get("canonical_event_id") == right["event_id"]
    return {
        "key": f"{left['event_id']}-{right['event_id']}",
        "left": left,
        "right": right,
        "priority": _priority(left, right, today),
        "already_folded": folded,
        **finding,
    }


def summary(con, *, today: date | None = None) -> dict[str, Any]:
    pairs = find(con, today=today)
    return {
        "candidates": len(pairs),
        "by_priority": {p: sum(1 for x in pairs if x["priority"] == p)
                        for p in (PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW)},
        "possible_same_event": sum(1 for x in pairs if x["assessment"] == POSSIBLE_SAME_EVENT),
        "insufficient_evidence": sum(1 for x in pairs
                                     if x["assessment"] == INSUFFICIENT_EVIDENCE),
    }


# --- one pair, laid out for a person -----------------------------------------

COMPARED_FIELDS = (
    ("Event name", "event_name"),
    ("Type", "event_type"),
    ("First day", "event_date"),
    ("Last day (stated)", "end_date"),
    ("Start time", "start_time"),
    ("End time", "end_time"),
    ("Venue", "venue"),
    ("Region", "region_code"),
    ("Source", "source_name"),
    ("Canonical", "canonical"),
    ("Listing", "listing_state"),
)


def _value(event: dict[str, Any], field: str) -> str:
    if field == "venue":
        if event.get("venue_id") is not None:
            return f"{event.get('venue_name') or '-'} (venue {event['venue_id']})"
        return f"{event.get('venue_text') or UNKNOWN} (unresolved)" \
            if event.get("venue_text") else UNKNOWN
    if field == "canonical":
        if event.get("canonical_event_id"):
            return f"folded into #{event['canonical_event_id']}"
        return f"canonical, {int(event.get('folded') or 0)} folded"
    value = event.get(field)
    if value is None or value == "":
        return UNKNOWN
    if hasattr(value, "strftime") and field.endswith("_time"):
        return value.strftime("%H:%M")
    return str(value)


def _evidence(event: dict[str, Any]) -> dict[str, Any]:
    """What the source itself stated, as stored. Missing is UNKNOWN, never filled."""
    stated = _stated_period(event) or {}
    return {
        "source_item_id": event.get("source_item_id"),
        "source_key": event.get("source_key") or UNKNOWN,
        "source_name": event.get("source_name") or UNKNOWN,
        "source_url": events_api.valid_public_url(event.get("item_url")
                                                  or event.get("source_url")) or UNKNOWN,
        "original_title": event.get("item_title") or UNKNOWN,
        "date_evidence": {
            "stated_start": stated.get("start") or UNKNOWN,
            "stated_end": stated.get("end") or UNKNOWN,
            "note": event.get("festival_evidence") or UNKNOWN,
        },
        "venue_evidence": event.get("venue_text") or UNKNOWN,
        "last_collected_at": event.get("collected_at"),
        "last_extracted_at": event.get("reprocessed_at"),
        "acquisition_status": event.get("acquisition_status") or UNKNOWN,
    }


def _related(con, event_ids: list[int], item_ids: list[int]) -> list[dict[str, Any]]:
    """Programme rows built from either post, and rows folded into either event."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT e.event_id, e.event_name, e.event_type, e.event_date, e.start_time, "
            "  e.venue_text, e.canonical_event_id, e.listing_state, e.source_item_id "
            "FROM events e WHERE (e.source_item_id = ANY(%s) OR e.canonical_event_id = ANY(%s)) "
            "  AND NOT e.event_id = ANY(%s) ORDER BY e.event_date, e.event_id",
            (item_ids, event_ids, event_ids))
        return _rows(cur)


def compare(con, left_id: int, right_id: int, *, today: date | None = None
            ) -> dict[str, Any] | None:
    """One pair side by side, with what merging or keeping apart would mean.

    None when the two are not a conflict pair (or do not exist), so a
    hand-typed URL can never present two unrelated events as a question.
    """
    today = today or events_api.today()
    if left_id == right_id:
        return None
    rows = {r["event_id"]: r for r in _festivals(con, ids=[left_id, right_id])}
    if len(rows) != 2:
        return None
    left, right = rows[min(left_id, right_id)], rows[max(left_id, right_id)]
    pair = next((p for p in find(con, today=today)
                 if {p["left"]["event_id"], p["right"]["event_id"]} == {left_id, right_id}),
                None)
    if pair is None:
        return None
    fields = [
        {"label": label, "left": _value(left, key), "right": _value(right, key),
         "differs": _value(left, key) != _value(right, key)}
        for label, key in COMPARED_FIELDS
    ]
    public = {e["event_id"]: _public(e, today) for e in (left, right)}
    keeps = left if left["event_id"] < right["event_id"] else right
    other = right if keeps is left else left
    return {
        **pair,
        "fields": fields,
        "evidence": {left["event_id"]: _evidence(left), right["event_id"]: _evidence(right)},
        "public_now": public,
        "related": _related(con, [left_id, right_id],
                            [i for i in (left.get("source_item_id"),
                                         right.get("source_item_id")) if i is not None]),
        "if_merged": (
            f"#{other['event_id']} would be hidden and #{keeps['event_id']} shown with its "
            f"own dates ({period(keeps)[0]} ~ {period(keeps)[1]}); "
            f"{other.get('source_name') or 'the other source'}'s first day "
            f"{other['event_date']} would no longer be shown anywhere."),
        "if_separate": (
            "Both rows stay listed as they are"
            + (": a reader currently sees two entries for what may be one festival."
               if all(public.values()) else ".")),
        "merge_offered": False,
        "merge_note": MERGE_NOT_OFFERED,
        "keep_separate_note": KEEP_SEPARATE_NOTE,
        "follow_up": FOLLOW_UP,
        "unresolved": [c for c in pair["conflicts"]],
    }
