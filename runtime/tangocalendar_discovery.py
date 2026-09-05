"""Discovery for Tango Calendar Korea (v0.82 Tango Source Expansion): a
public JSON API, not a website - the frontend at tangocalendar.kr is a JS
shell, but `/api/events` (an unpaged array) and `/api/events/{uuid}` are both
public, robots-allowed, and structurally complete (date, time, venue, fee,
created/updated).

Like `tangonow_discovery.py`, the list response already carries every field
a record has, so ordinary discovery reads it directly; `fetch_event_detail()`
below still implements the documented `/api/events/{uuid}` endpoint for a
targeted single-event re-check. Body text is synthesized from the structured
fields the same way, for the same reason: `engine_ingest.py` has one text
extraction entry point (`extractor.extract_single`), and this reuses it
rather than adding a second, structured one.

The list is described as "unpaged" (a bare JSON array) as of this release;
`parse_events()` validates that shape explicitly rather than assuming it, so
a future pagination wrapper (`{"items": [...], "cursor": ...}`) fails loudly
instead of being silently misread as zero events.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import acquisition

USER_AGENT = acquisition.USER_AGENT
DEFAULT_TIMEOUT = acquisition.DEFAULT_TIMEOUT

SEOUL = ZoneInfo("Asia/Seoul")

# How far back a "base record" may still be worth carrying past the initial
# cutoff filter. 0 keeps only events dated today (Seoul) or later - this is
# an upcoming-events collector, not an archive.
_CUTOFF_GRACE_DAYS = 0


class DiscoveryError(RuntimeError):
    """The API could not be fetched, or its response was not the shape this
    collector understands - including a schema change (pagination added)
    that must fail loudly rather than silently read as zero events."""


# --- time / date helpers ------------------------------------------------------

def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_seoul(value: Any) -> datetime | None:
    """A UTC (or otherwise tz-aware) timestamp, converted to Asia/Seoul -
    Korean event times must be read and shown in Seoul local time, never the
    API's own UTC, per this project's existing timezone policy
    (`runtime.quality._seoul_today()` and friends)."""
    parsed = _parse_iso(value)
    return parsed.astimezone(SEOUL) if parsed else None


def format_time_range(start: datetime | None, end: datetime | None) -> str | None:
    """Two Seoul-local datetimes -> a plain 24-hour `"HH:MM~HH:MM"` - the
    engine's own `parse_time_range()` already reads a bare 24-hour range
    correctly with no marker at all (unambiguous exactly when the start
    hour is NOT in 1-12).

    v0.82.1, found live: rendering this as an explicit "H:MM am/pm to H:MM
    am/pm" invents certainty this project does not actually have - a real
    TangoNOW record's own `"09:00~26:00"` is honestly ambiguous (is the
    event's start really 09:00, or a data-entry quirk?), and forcing an
    explicit AM/PM marker onto it got flagged by WRONG_TIME_SQL (start
    before noon, evidence EXPLICIT) - a real detection working correctly
    against a real, over-confident rendering (see tangonow_discovery.py's
    identical fix for the full account). Passing the true 24-hour value
    straight through lets the engine's own honesty rule decide: unambiguous
    ranges still resolve cleanly, and genuinely ambiguous ones stay
    EVIDENCE_ABSENT/ambiguous=True for a person to confirm.
    """
    if start is None or end is None:
        return None
    return f"{start.hour % 24:02d}:{start.minute:02d}~{end.hour % 24:02d}:{end.minute:02d}"


def _format_date_kr(value: datetime | None) -> str | None:
    if value is None:
        return None
    return f"{value.year}년 {value.month}월 {value.day}일"


# --- record shaping -----------------------------------------------------------

def _combine_date_and_time(base_value: Any, occurrence_date: Any) -> str | None:
    """v0.82.1, confirmed against a live response: an override's own
    `startDate`/`endDate` is only present for 76 of 151 sampled override
    entries. The other 75 carry only `occurrenceDate` - the real hour/minute
    for that occurrence is the base event's own, applied to the override's
    date. Without this, every such override silently inherited the BASE
    event's date instead of its own (found live: the first sampled weekly
    series' 7 earlier occurrences all collapsed onto its most recent date).
    """
    base_dt = _parse_iso(base_value)
    occ_dt = _parse_iso(occurrence_date)
    if base_dt is None or occ_dt is None:
        return None
    return base_dt.replace(year=occ_dt.year, month=occ_dt.month, day=occ_dt.day).isoformat()


def _merge_override(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Override fields win over the base event's own fields wherever the
    override actually supplies a value (Section 3: "override에 값이 있으면
    base event보다 우선한다") - a `None`/absent override field leaves the
    base's value in place rather than blanking it.

    An override naming only `occurrenceDate` (its own `startDate`/`endDate`
    left null) gets the base's time-of-day combined with that date first -
    see `_combine_date_and_time()` - so the merge below still only ever
    prefers a value the override actually supplied, not a fabricated one.
    """
    override = dict(override)
    occurrence_date = override.get("occurrenceDate")
    if occurrence_date and override.get("startDate") is None:
        combined = _combine_date_and_time(base.get("startDate"), occurrence_date)
        if combined:
            override["startDate"] = combined
    if occurrence_date and override.get("endDate") is None:
        combined = _combine_date_and_time(base.get("endDate"), occurrence_date)
        if combined:
            override["endDate"] = combined

    merged = dict(base)
    for key, value in override.items():
        if value is not None:
            merged[key] = value
    return merged


def _is_cancelled(record: dict[str, Any]) -> bool:
    return bool(record.get("isCancelled") or record.get("cancelled"))


def _occurrences(event: dict[str, Any]) -> list[dict[str, Any]]:
    """One event record's own occurrence(s) - itself, or itself merged with
    each of its `occurrenceOverrides` entries, cancelled ones dropped.

    `occurrenceOverrides` is treated as exceptions to *this* record's own
    date (not a general recurrence expansion - the API already materializes
    each dated instance as its own top-level array entry, per the report's
    "746 base record" count), so this never invents an occurrence the API
    did not already return in some form.
    """
    overrides = event.get("occurrenceOverrides")
    if not overrides:
        return [] if _is_cancelled(event) else [event]

    if isinstance(overrides, dict):
        overrides = [overrides]

    occurrences: list[dict[str, Any]] = []
    for override in overrides:
        if not isinstance(override, dict):
            continue
        merged = _merge_override(event, override)
        if _is_cancelled(merged):
            continue
        occurrences.append(merged)
    return occurrences


def _entrance_fee_text(value: Any) -> str | None:
    """Preserved losslessly (Section 3: "entranceFee가 문자열이어도 원문을
    손실 없이 저장한다") - rendered as `FEE_RE`'s `입장료 N원` shape only
    when it is actually numeric; a non-numeric fee ("문의", "무료") is kept
    as visible text instead of being coerced or dropped."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return f"입장료 {int(value)}원"
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits and digits == text.replace(",", ""):
        return f"입장료 {digits}원"
    return f"입장료: {text}"


def _synthesize_body(record: dict[str, Any], start: datetime | None, end: datetime | None) -> str:
    parts: list[str] = []

    event_date = _format_date_kr(start)
    if event_date:
        parts.append(event_date)

    time_expr = format_time_range(start, end)
    if time_expr:
        parts.append(f"시간: {time_expr}")

    venue = record.get("venue")
    if venue:
        parts.append(f"장소: {venue}")

    dj = record.get("djName") or record.get("dj")
    if dj:
        parts.append(f"DJ: {dj}")

    # v0.82.1, confirmed against a live response: there is no single
    # "organizer name" field - only contact channels (organizerFacebook/
    # organizerKakaoId/organizerOther/organizerPhone). None of extract_single()'s
    # rules read a "주최:" label anyway (only date/time/venue/fee/DJ), so this
    # is informational only; organizerOther is the one free-text field among
    # them and is used when present rather than guessing at a name field that
    # does not exist.
    organizer = record.get("organizerOther")
    if organizer:
        parts.append(f"주최: {organizer}")

    fee_text = _entrance_fee_text(record.get("entranceFee"))
    if fee_text:
        parts.append(fee_text)

    description = record.get("description")
    if description:
        parts.append(str(description))

    return " ".join(parts)


def parse_list(raw_text: str, list_url: str) -> list[dict[str, Any]]:
    """`collectors._collect_snapshot()`'s generic WEB entry point: a raw,
    already-fetched response body (here, the `/api/events` JSON text, e.g. a
    recorded fixture) -> RawPostRecord-shaped dicts. A thin wrapper around
    `parse_events()` so a snapshot/fixture dry-run for this source goes
    through the same dispatch every other WEB source already uses.
    """
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"{list_url} snapshot is not valid JSON: {exc}") from exc
    return parse_events(payload, list_url)


def parse_events(
    payload: Any, list_url: str, *, today: date | None = None,
) -> list[dict[str, Any]]:
    """The public `/api/events` array -> RawPostRecord-shaped dicts,
    upcoming-only.

    The date cutoff runs first, before occurrence merging or body synthesis -
    Section 3's "과거 전체 데이터를 OCR 또는 상세 조회 대상으로 보내지
    않는다": with 96%+ of the raw array already in the past, doing the
    (slightly) more expensive per-record work before filtering would cost
    real time for records that are discarded anyway.
    """
    if not isinstance(payload, list):
        raise DiscoveryError(
            f"{list_url} returned {type(payload).__name__}, not an array - "
            "this collector assumes an unpaged JSON list; if the API now "
            "paginates, this must be updated rather than silently misread"
        )

    cutoff = today or datetime.now(SEOUL).date()
    posts: list[dict[str, Any]] = []
    for event in payload:
        if not isinstance(event, dict):
            continue
        for occurrence in _occurrences(event):
            start = _to_seoul(occurrence.get("startDate"))
            if start is None:
                continue
            if start.date() < cutoff - timedelta(days=_CUTOFF_GRACE_DAYS):
                continue
            end = _to_seoul(occurrence.get("endDate"))

            title = str(occurrence.get("title") or "").strip()
            if not title:
                continue

            event_id = occurrence.get("id")
            source_url = (
                f"{list_url.rstrip('/').rsplit('/api/', 1)[0]}/api/events/{event_id}"
                if event_id else list_url
            )

            published = _to_seoul(occurrence.get("updatedAt") or occurrence.get("createdAt"))
            posts.append({
                "source_url": source_url,
                "title": title,
                "body": _synthesize_body(occurrence, start, end),
                "published_at": published.isoformat() if published else None,
                # The list response already carries every field a record
                # has - there is no later HTML fetch for this source.
                "acquisition_quality": "FETCHED_FULL",
            })
    return posts


# --- fetching -----------------------------------------------------------------

def _fetch_json(url: str, *, timeout: int, opener) -> Any:
    if not acquisition.robots_allows(url):
        raise DiscoveryError(f"robots.txt disallows {url}")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise DiscoveryError(f"HTTP {exc.code} fetching {url}") from exc
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"{url} did not return valid JSON: {exc}") from exc


def fetch_event_detail(
    base_url: str, event_id: str, *, timeout: int = DEFAULT_TIMEOUT, opener=None,
) -> dict[str, Any]:
    """One event by id, via the documented `/api/events/{uuid}` detail
    endpoint - a targeted re-fetch; ordinary discovery reads the list
    response directly since it already carries every field."""
    url = f"{base_url.rstrip('/')}/api/events/{event_id}"
    return _fetch_json(url, timeout=timeout, opener=opener)


def discover(
    list_url: str, *, source_id: str, platform: str = "WEB",
    timeout: int = DEFAULT_TIMEOUT, opener=None,
) -> list[dict[str, Any]]:
    """Every upcoming, non-cancelled Tango Calendar Korea event."""
    payload = _fetch_json(list_url, timeout=timeout, opener=opener)
    posts = parse_events(payload, list_url)
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
