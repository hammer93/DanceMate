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
(`장소: X`, `입장료 N원`, `DJ: X`, explicit `H:MM am to H:MM am` time markers)
rather than inventing a second, structured ingestion path around
`engine_ingest.py`'s single `extract_single(title, body, ...)` entry point.
This is the same choice DanceInfo's OCR fallback made in v0.81.3: feed the
one text pipeline that already exists, don't build a parallel one.
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

def _to_12h(hour: int, minute: int) -> tuple[int, int, str]:
    """A 24h (possibly >=24, for an overnight `28:30`-style hour) hour/minute
    pair, folded to a 0-23 clock and rendered as (hour12, minute, am/pm)."""
    hour = hour % 24
    ap = "am" if hour < 12 else "pm"
    hour12 = hour % 12
    if hour12 == 0:
        hour12 = 12
    return hour12, minute, ap


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
    (overnight, hour >= 24) into the one time expression the engine's
    `parse_time_range()` is proven to read as EVIDENCE_EXPLICIT regardless of
    which side crosses noon or midnight: `"H:MM am to H:MM am"` (matching
    `extraction_rules`'s own `"09:00 pm to 02:00 am"` test case) - because the
    real hour is already known exactly, this is a faithful rendering of a
    fact, not a guessed marker.
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
    h1, m1, ap1 = _to_12h(*start)
    h2, m2, ap2 = _to_12h(*end)
    return f"{h1}:{m1:02d} {ap1} to {h2}:{m2:02d} {ap2}"


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
    (colon-labelled venue, `입장료 N원`, `DJ: X`, explicit am/pm time)."""
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
