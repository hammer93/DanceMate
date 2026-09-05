"""Discovery for TangoNOW (v0.82 Tango Source Expansion): a public Firestore
REST registry, not a website - `ktnow.kr`'s own frontend is JS-only and holds
no event data, but its Firestore project serves complete event documents to
an unauthenticated GET (verified directly; `firestore.googleapis.com`'s own
robots.txt is a 404, and the app host `ktnow.kr` disallows only `/admin/`).

Firestore's `documents.list` already returns full Document objects - date,
time, venue, price, DJ, organizer, poster, everything - so there is no
separate network round trip needed per record the way danceinfo.net's SSR
detail page is a genuinely later fetch. `fetch_document()` below still
implements the documented single-document detail endpoint
(`.../documents/events/{document_id}`) for the cases that need it (a
targeted re-check of one record), but ordinary discovery reads everything
it needs from the list response directly.

Kept as its own small module rather than folded into `danceinfo_discovery.py`
or `web_discovery.py`: a typed-value JSON registry, a JSON API with occurrence
overrides, and an HTML board are three different data shapes, and forcing
one parser to branch on all three would be the "unnecessary abstraction"
these modules already avoid (see danceinfo_discovery.py's own docstring).

Body synthesis: because this source hands over structured fields directly
(not free text), `_synthesize_body()` renders them as a plain Korean-labelled
paragraph the engine's *existing* extraction rules already know how to read
(`장소: X`, `입장료 N원`, `DJ: X`, a plain 24-hour `HH:MM~HH:MM` time range)
rather than inventing a second, structured ingestion path around
`engine_ingest.py`'s single `extract_single(title, body, ...)` entry point.
This is the same choice DanceInfo's OCR fallback made in v0.81.3: feed the
one text pipeline that already exists, don't build a parallel one.

v0.82.1: the time range is rendered as a bare 24-hour value, not an
explicit am/pm marker - see `format_time_range()`'s own docstring for why
an explicit marker turned out to invent certainty a real record did not
have (found live, and confirmed to be exactly what flagged a genuine
WRONG_TIME_SQL case).
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

from . import acquisition

USER_AGENT = acquisition.USER_AGENT
DEFAULT_TIMEOUT = acquisition.DEFAULT_TIMEOUT

# Safety limits against a runaway or misbehaving pagination loop (Section 2):
# the live registry was observed at ~77 variable-size batches for 3,639
# documents, so this leaves real headroom without being unbounded.
MAX_PAGES = 200
MAX_RECORDS = 20_000

_ARCHIVED_STATUSES = {"archived", "cancelled", "canceled", "취소", "archive"}


class DiscoveryError(RuntimeError):
    """The Firestore list/document endpoint could not be fetched or made no
    sense to parse - including a 401/403 from a public-rule change, which is
    reported here rather than silently treated as zero results."""


# --- Firestore typed-value conversion ---------------------------------------

def _typed_value(value: dict[str, Any] | None) -> Any:
    """One Firestore `Value` object -> a plain Python value.

    https://firestore.googleapis.com/$discovery/rest - every field on a
    Document is wrapped as `{"<type>Value": ...}`; this is the exhaustive
    list of wrapper kinds Firestore's REST API emits.
    """
    if not value:
        return None
    if "stringValue" in value:
        return value["stringValue"]
    if "integerValue" in value:
        try:
            return int(value["integerValue"])
        except (TypeError, ValueError):
            return value["integerValue"]
    if "doubleValue" in value:
        return value["doubleValue"]
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "timestampValue" in value:
        return value["timestampValue"]
    if "nullValue" in value:
        return None
    if "arrayValue" in value:
        return [_typed_value(v) for v in (value["arrayValue"].get("values") or [])]
    if "mapValue" in value:
        return {
            key: _typed_value(v) for key, v in (value["mapValue"].get("fields") or {}).items()
        }
    if "geoPointValue" in value:
        return value["geoPointValue"]
    if "referenceValue" in value:
        return value["referenceValue"]
    return None


def _document_id(document: dict[str, Any]) -> str | None:
    """The last path segment of a Firestore `Document.name`."""
    name = document.get("name") or ""
    return name.rsplit("/", 1)[-1] or None


def document_fields(document: dict[str, Any]) -> dict[str, Any]:
    """A Firestore Document's `fields` map, converted to a plain dict."""
    return {
        key: _typed_value(value) for key, value in (document.get("fields") or {}).items()
    }


# --- time normalisation ------------------------------------------------------

def _parse_clock(text: str) -> tuple[int, int] | None:
    text = text.strip()
    if ":" not in text:
        return None
    h, _, m = text.partition(":")
    try:
        return int(h), int(m)
    except ValueError:
        return None


def format_time_range(raw_time: str | None) -> str | None:
    """TangoNOW's own `"14:00-18:00"` / `"21:00-03:00"` / `"20:30-28:30"`
    (overnight, hour >= 24) folded to a plain 24-hour `"HH:MM~HH:MM"` - the
    engine's own `parse_time_range()` already reads a bare 24-hour range
    correctly with no marker at all (its `_readings()` calls a range
    unambiguous exactly when the start hour is NOT in 1-12, the same rule
    covering "23:30 – 04:30" and "20:00 ~ 00:30" with zero markers).

    v0.82.1, found live: an earlier version of this function rendered every
    range as an explicit "H:MM am/pm to H:MM am/pm" - which is *inventing*
    certainty the source never gave. A real TangoNOW record's own
    `"09:00~26:00"` is honestly ambiguous (is the event's start really
    09:00, or is that a data-entry quirk for what should read as evening?);
    forcing "9:00 am" onto it got the record flagged as WRONG_TIME_SQL
    (start before noon, evidence EXPLICIT) - a real detection working
    correctly against a real, over-confident rendering. Passing the raw
    24-hour value straight through - true to what the source actually
    said, no more - lets the engine's own honesty rule decide: an
    unambiguous 24-hour range (e.g. 14:00-18:00) still resolves cleanly,
    and a genuinely ambiguous one is left EVIDENCE_ABSENT/ambiguous=True for
    a person to confirm, exactly the "missing over wrong" this project
    already commits to everywhere else.
    """
    if not raw_time or not isinstance(raw_time, str):
        return None
    for sep in ("-", "~", "–", "—"):
        if sep in raw_time:
            start_raw, _, end_raw = raw_time.partition(sep)
            break
    else:
        return None
    start = _parse_clock(start_raw)
    end = _parse_clock(end_raw)
    if start is None or end is None:
        return None
    h1, m1 = start
    h2, m2 = end
    return f"{h1 % 24:02d}:{m1:02d}~{h2 % 24:02d}:{m2:02d}"


def _format_date_kr(raw_date: str | None) -> str | None:
    """`"2026-09-06"` -> `"2026년 9월 6일"` - explicit-year form
    `extractor.DATE_PATTERNS` resolves without needing `published`."""
    if not raw_date:
        return None
    try:
        d = date.fromisoformat(str(raw_date)[:10])
    except ValueError:
        return None
    return f"{d.year}년 {d.month}월 {d.day}일"


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# --- body synthesis -----------------------------------------------------------

def _first(fields: dict[str, Any], *names: str) -> Any:
    """The first present, non-empty field among several possible names.

    v0.82.1: confirmed directly against a live Firestore response (300
    documents), replacing the earlier "가능한 범위에서 매핑" guesses. Every
    name below is a field this project's own request actually returned;
    none is a spelling nobody has seen. `region`/`regionLarge`/`regionSmall`
    genuinely all three exist on real documents (city/subregion breakdown),
    which is why that one field alone keeps a multi-name fallback.
    """
    for name in names:
        value = fields.get(name)
        if value not in (None, ""):
            return value
    return None


def _synthesize_body(fields: dict[str, Any]) -> str:
    """A plain Korean-labelled paragraph from TangoNOW's structured fields,
    in the label shapes `engine.extraction_rules`/`extractor` already read
    (colon-labelled venue, `입장료 N원`, `DJ: X`, a plain 24-hour time range)."""
    parts: list[str] = []

    event_date = _format_date_kr(_first(fields, "date"))
    if event_date:
        parts.append(event_date)

    time_expr = format_time_range(_first(fields, "time"))
    if time_expr:
        parts.append(f"시간: {time_expr}")

    venue = _first(fields, "place")
    if venue:
        parts.append(f"장소: {venue}")

    region = _first(fields, "region", "regionLarge", "regionSmall")
    if region:
        parts.append(f"지역: {region}")

    dj = _first(fields, "dj")
    if dj:
        parts.append(f"DJ: {dj}")

    organizer = _first(fields, "org")
    if organizer:
        parts.append(f"주최: {organizer}")

    price = _first(fields, "price")
    if price not in (None, ""):
        try:
            amount = int(price)
            parts.append(f"입장료 {amount}원")
        except (TypeError, ValueError):
            # A non-numeric price string (e.g. "무료", "문의") is real
            # information but not something FEE_RE can read as an amount -
            # keep it as plain text rather than drop it.
            parts.append(f"입장료: {price}")

    description = _first(fields, "description")
    if description:
        parts.append(str(description))

    return " ".join(parts)


# --- fetching -----------------------------------------------------------------

def _fetch_json(url: str, *, timeout: int, opener) -> dict[str, Any]:
    if not acquisition.robots_allows(url):
        raise DiscoveryError(f"robots.txt disallows {url}")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read()
    except urllib.error.HTTPError as exc:
        # A public-rule change (Section 2) reads as 401/403, not a network
        # blip - reported as a distinct, named source error rather than the
        # generic network-failure path other statuses fall into.
        if exc.code in (401, 403):
            raise DiscoveryError(
                f"TangoNOW Firestore returned {exc.code} for {url} - "
                "public read rules may have changed"
            ) from exc
        raise DiscoveryError(f"HTTP {exc.code} fetching {url}") from exc
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    import json as _json

    try:
        return _json.loads(text)
    except _json.JSONDecodeError as exc:
        raise DiscoveryError(f"{url} did not return valid JSON: {exc}") from exc


def _detail_url(document: dict[str, Any], list_url: str) -> str:
    """The document's own resource name, resolved to an absolute
    `.../v1/projects/.../documents/events/{id}` URL - Firestore's `name`
    field is already that full resource path (e.g.
    `projects/ktangoguide/databases/(default)/documents/events/{id}`),
    just missing the `https://firestore.googleapis.com/v1/` REST prefix."""
    name = document.get("name") or ""
    if name.startswith("http"):
        return name
    origin = urllib.parse.urlparse(list_url)
    return f"{origin.scheme}://{origin.netloc}/v1/{name}"


def fetch_document(
    project: str, document_id: str, *, collection: str = "events",
    timeout: int = DEFAULT_TIMEOUT, opener=None,
) -> dict[str, Any]:
    """One document by id, via the documented detail endpoint
    (Section: `.../documents/events/{document_id}`) - a targeted re-fetch,
    not part of ordinary discovery (the list response already carries every
    field a document has)."""
    url = (
        f"https://firestore.googleapis.com/v1/projects/{project}/databases/"
        f"(default)/documents/{collection}/{document_id}"
    )
    return _fetch_json(url, timeout=timeout, opener=opener)


def parse_list(raw_text: str, list_url: str) -> list[dict[str, Any]]:
    """`collectors._collect_snapshot()`'s generic WEB entry point: a raw,
    already-fetched response body (here, one Firestore list page's JSON
    text, e.g. a recorded fixture) -> RawPostRecord-shaped dicts. Kept as a
    thin wrapper around `parse_documents()` purely so a snapshot/fixture
    dry-run for this source works through the exact same dispatch every
    other WEB source already uses, rather than a special case per source.
    """
    import json as _json

    try:
        payload = _json.loads(raw_text)
    except _json.JSONDecodeError as exc:
        raise DiscoveryError(f"{list_url} snapshot is not valid JSON: {exc}") from exc
    documents = payload.get("documents") or []
    return parse_documents(documents, list_url)


def parse_documents(
    documents: list[dict[str, Any]], list_url: str,
) -> list[dict[str, Any]]:
    """Firestore `Document` objects -> RawPostRecord-shaped dicts.

    A record with no explicit date is dropped outright (Section 2: "명시적인
    date가 없는 record는 event 후보로 만들지 않는다") rather than handed on
    for the engine to fail to date on its own - the difference between "we
    chose not to guess" and "we tried and found nothing" matters for an
    always-past-heavy registry like this one (3,599/3,639 sampled documents
    were before the collection cutoff).
    """
    posts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for document in documents:
        document_id = _document_id(document)
        # A repeated page (Section 2's repeated-nextPageToken defence lets a
        # page through once more before it gives up) must not double-count
        # the same document - collectors.py's own cross-source_url dedup only
        # runs across separate board_urls/discover() calls, not within the
        # multiple Firestore pages a single discover() call already walks.
        if document_id is not None:
            if document_id in seen_ids:
                continue
            seen_ids.add(document_id)

        fields = document_fields(document)
        status = str(_first(fields, "status") or "").strip().lower()
        if status in _ARCHIVED_STATUSES:
            continue
        if bool(fields.get("archived")) or bool(fields.get("cancelled")):
            continue

        raw_date = _first(fields, "date")
        if not raw_date or not _format_date_kr(raw_date):
            continue

        title = str(_first(fields, "title") or "").strip()
        if not title:
            continue

        document_id = _document_id(document)
        source_url = _detail_url(document, list_url) if document_id else list_url

        published = _parse_iso(_first(fields, "updatedAt", "createdAt"))
        posts.append({
            "source_url": source_url,
            "title": title,
            "body": _synthesize_body(fields),
            "published_at": published.isoformat() if published else None,
            # Body is fully populated from the structured API response
            # already - there is no later HTML fetch for this source the way
            # DanceInfo's is, so METADATA_ONLY (meaning "body arrives later")
            # would misdescribe it.
            "acquisition_quality": "FETCHED_FULL",
        })
    return posts


def discover(
    list_url: str, *, source_id: str, platform: str = "WEB",
    timeout: int = DEFAULT_TIMEOUT, opener=None,
) -> list[dict[str, Any]]:
    """Every non-archived, dated Tango event on the registry, walking
    `nextPageToken` until Firestore stops returning one (Section 2).

    Guarded against a runaway pagination loop by `MAX_PAGES`, `MAX_RECORDS`,
    and repeated-token detection (a token seen twice means the server is
    looping, not progressing) - three independent, cheap checks rather than
    trusting the upstream to always terminate cleanly.
    """
    all_documents: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    page_token: str | None = None

    for _ in range(MAX_PAGES):
        url = list_url
        if page_token:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}pageToken={urllib.parse.quote(page_token)}"
        payload = _fetch_json(url, timeout=timeout, opener=opener)
        documents = payload.get("documents") or []
        all_documents.extend(documents)
        if len(all_documents) > MAX_RECORDS:
            break

        page_token = payload.get("nextPageToken")
        if not page_token:
            break
        if page_token in seen_tokens:
            # The server is repeating a token rather than progressing -
            # stop rather than loop forever on what we already have.
            break
        seen_tokens.add(page_token)
    else:
        # MAX_PAGES exhausted without nextPageToken running out - proceed
        # with what was collected rather than raise; a very large but
        # finite registry is not a parser failure.
        pass

    posts = parse_documents(all_documents, list_url)
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts


# --- eventsBundle (v0.83: prepared, not activated) ---------------------------
#
# ktnow.kr's current live frontend does not read Firestore directly - it
# calls this Cloud Function, which reshapes the same Firestore-backed data
# into one flat JSON response (no per-page round trip, no typed-value
# unwrapping). Confirmed directly against a live response before writing
# this (Section 3: "eventsBundle이 요청 수와 과거 데이터량을 줄이는 데 실제로
# 유리한지 확인한다"):
#
#   - One request returns everything the frontend needs (345 `main` + 28
#     `archived` + 83 `brands`, ~560 KB) where the existing Firestore path
#     may walk many separate `documents.list` pages to reach the same `main`
#     set, most of it already-archived history first (a live Firestore
#     sample was ~94% archived).
#   - The response is server-cached (`Cache-Control: public, max-age=300,
#     s-maxage=600`), so a repeat request inside that window costs the
#     origin nothing extra.
#
# But a live sample also showed real schema heterogeneity the discovery
# report's own clean field list did not surface: `main` mixes at least
# three different date-field conventions across records (`date` alone on
# ~97% of records, `start_date`/`end_date` on a multi-day-festival minority,
# and a third, differently-cased `startDate`/`endDate` pair on a smaller
# minority still), and `normalizedTime` - listed as an observed field - was
# null on every one of the 345 sampled records, never populated.
# `source_url` provenance is also weaker than Firestore's: only ~20% of
# records carry any `link`/`sourceLink` value at all.
#
# Given SRC-W-002 is already live on real board data (this task's own #1
# priority is stabilising it, not migrating it), an internal,
# non-contractual Cloud Function endpoint with this much internal
# heterogeneity is not something to switch a stable source onto without a
# monitoring period first. So this section stops short of wiring
# `parse_bundle()`/`discover_bundle()` into `collectors.py`'s dispatch
# table - the registered SRC-W-002 row's `config.parser` stays
# `tangonow_firestore`, unchanged. These two functions exist, are tested
# against a fixture shaped like the real response, and are ready to be
# wired in later (see docs/TANGO_SOURCE_IMPLEMENTATION.md for the exact
# small addition that would take).

BUNDLE_URL = "https://asia-northeast3-ktangoguide.cloudfunctions.net/eventsBundle?days=14"


def _bundle_date(record: dict[str, Any]) -> Any:
    """The first explicit date this record actually carries, honouring all
    three conventions observed live - `date` (the vast majority), then
    `start_date`/`startDate` (the multi-day-festival minorities). Never
    invents one: a record with none of these is skipped by the caller."""
    for name in ("date", "start_date", "startDate"):
        value = record.get(name)
        if value:
            return value
    return None


def _synthesize_bundle_body(record: dict[str, Any]) -> str:
    """Same Korean-labelled convention as `_synthesize_body()` (Firestore
    path), adapted for the bundle's flat, already-plain-JSON record shape -
    no Firestore typed-value unwrapping needed here."""
    parts: list[str] = []

    event_date = _format_date_kr(_bundle_date(record))
    if event_date:
        parts.append(event_date)

    time_expr = format_time_range(record.get("time"))
    if time_expr:
        parts.append(f"시간: {time_expr}")

    venue = record.get("place")
    if venue:
        parts.append(f"장소: {venue}")

    region = record.get("region") or record.get("regionLarge") or record.get("regionSmall")
    if region:
        parts.append(f"지역: {region}")

    dj = record.get("dj")
    if dj:
        parts.append(f"DJ: {dj}")

    organizer = record.get("org") or record.get("host")
    if organizer:
        parts.append(f"주최: {organizer}")

    price = record.get("price")
    if price not in (None, ""):
        try:
            amount = int(price)
            parts.append(f"입장료 {amount}원")
        except (TypeError, ValueError):
            parts.append(f"입장료: {price}")

    description = record.get("description")
    if description:
        parts.append(str(description))

    return " ".join(parts)


def _parse_bundle_payload(payload: Any, bundle_url: str) -> list[dict[str, Any]]:
    """`main` records -> RawPostRecord-shaped dicts. `archived` is never
    read: those records are already excluded by the bundle's own backend,
    the same "archived/cancelled record는 upcoming candidate에서 제외"
    outcome the Firestore path enforces itself by checking `status`."""
    if not isinstance(payload, dict) or not isinstance(payload.get("main"), list):
        raise DiscoveryError(
            f"{bundle_url} has no 'main' array - bundle schema changed"
        )

    posts: list[dict[str, Any]] = []
    for record in payload["main"]:
        if not isinstance(record, dict):
            continue
        status = str(record.get("status") or "").strip().lower()
        if status in _ARCHIVED_STATUSES:
            continue

        title = str(record.get("title") or "").strip()
        if not title:
            continue

        raw_date = _bundle_date(record)
        if not raw_date or not _format_date_kr(raw_date):
            continue

        source_url = record.get("sourceLink") or record.get("link")
        if not source_url:
            # ~80% of sampled records carry neither field - a real,
            # documented gap in this endpoint's own provenance, not
            # something to paper over with a link that would resolve to
            # nothing (Section 6/7's own KTNow finding: a generic
            # `/?mode=event` route cannot recover one specific document).
            record_id = record.get("id")
            source_url = f"{bundle_url}#{record_id}" if record_id else bundle_url

        published = _parse_iso(record.get("updatedAt") or record.get("createdAt"))
        posts.append({
            "source_url": source_url,
            "title": title,
            "body": _synthesize_bundle_body(record),
            "published_at": published.isoformat() if published else None,
            "acquisition_quality": "FETCHED_FULL",
        })
    return posts


def parse_bundle(raw_text: str, bundle_url: str = BUNDLE_URL) -> list[dict[str, Any]]:
    """`collectors._collect_snapshot()`'s generic WEB entry point for the
    bundle shape, mirroring `parse_list()`'s role for the Firestore path.

    Schema-drift guard: `main` must actually be present and be a list - a
    response that has lost that shape must surface as a `DiscoveryError`,
    not silently parse to zero events.
    """
    import json as _json

    try:
        payload = _json.loads(raw_text)
    except _json.JSONDecodeError as exc:
        raise DiscoveryError(f"{bundle_url} is not valid JSON: {exc}") from exc
    return _parse_bundle_payload(payload, bundle_url)


def discover_bundle(
    bundle_url: str = BUNDLE_URL, *, source_id: str, platform: str = "WEB",
    timeout: int = DEFAULT_TIMEOUT, opener=None,
) -> list[dict[str, Any]]:
    """One `eventsBundle` request -> RawPostRecord-shaped dicts.

    Not wired into `collectors.py`'s dispatch table yet - see this module's
    own "eventsBundle" section docstring above for why.
    """
    payload = _fetch_json(bundle_url, timeout=timeout, opener=opener)
    posts = _parse_bundle_payload(payload, bundle_url)
    for post in posts:
        post["source_id"] = source_id
        post["platform"] = platform
    return posts
