"""Re-checking an article DanceMate already fetched (v0.96.43).

A fetched article body used to be settled for good. `acquisition.SETTLED`
holds FETCHED_FULL/FETCHED_PARTIAL, `next_attempt_at()` returns None for
them, and `content_store.due_for_acquisition()` only ever selects
`acquisition.RETRYABLE` statuses - so once a Daum post or a danceinfo.net
lesson page had been read, nothing asked the server for it again. The
discovery record could still move (a search title or snippet re-collected as
REVISED, which v0.96.42 re-reads), but the article body the engine actually
reads stayed the one first fetched. A publisher who moved 20:00 to 21:00 in
the post body was never seen, and v0.96.42's input signature could not help:
it compares the *stored* input, and the new one was never stored.

This module re-checks a bounded set of those articles and, when the article
text itself has changed, stores the new body and asks for one re-extraction
through v0.96.42's own queue (`content_store.mark_needs_reextract()` plus the
input signature the new content_hash moves). Nothing else is new: the engine
re-read, candidate update, normalization and duplicate scan are the ones
every revision already goes through.

What is re-checked (`ELIGIBLE`), and why only that:

  * a body this runtime fetched itself and still holds - FETCHED_FULL or
    FETCHED_PARTIAL. A FETCH_BLOCKED item is never selected: its refusal is
    the source's answer, and the ordinary acquisition retry schedule already
    re-asks it politely (v0.96.9). A discovery-synthesized body (TangoNOW,
    Tango Calendar Korea, Miltang) is re-read by its own collector on every
    cycle, and a generic re-fetch is exactly what degraded 85 Miltang items
    in v0.82.2;
  * whose text came from an adapter's own content scope - the template
    board's `.readEdit`, Daum's article region, danceinfo's payload or
    labelled region, a page's og:description. A whole-page `visible_text`
    body has no scope: its hash moves with every recommended-post list, view
    count and ad, so a re-check could not tell an edit from page furniture.
    That excludes every Naver blog body stored today (474 of them, all the
    iframe shell's visible text), which is also where blog.naver.com's
    robots.txt states that automated retrieval for AI training or retrieval
    is prohibited - those pages are not re-visited at all;
  * from an enabled source;
  * and still relevant: it feeds an Event that has not ended (upcoming, or a
    multi-day event still running), or it was first fetched within
    `RECENT_DAYS` (a new post is the one most likely to be corrected).
    An article about a past event is never re-visited.

How often (`due`): every 24 h while its event is within `NEAR_EVENT_DAYS`
(or running), every 72 h otherwise; sooner when the discovery record was
re-collected after the last check (the aggregator noticed *something*), but
never more than once per `SIGNAL_MIN_SPACING`. After a failure, an explicit
backoff (`refresh_next_at`) replaces the interval.

How much: `MAX_REFRESHES_PER_TICK` per scheduler tick, `HOST_DAILY_BUDGET`
per host per 24 h counted from `content_fetch_log` (purpose REFRESH), the
acquisition module's own politeness delay between requests, a host that
answered 429 left alone for `RATE_LIMIT_PAUSE`. Conditional headers are sent
when a server gave validators; measured 2026-10-20, danceinfo.net sends an
ETag but answers `If-None-Match` with 200, and m.cafe.daum.net and tistory
send none, so a 304 is honoured when it comes and never assumed.

What a check can conclude (`refresh_outcome`):

  * UNCHANGED / NOT_MODIFIED - the article text hashes the same (or the server
    said 304). Only `refresh_checked_at` moves; `fetched_at`, the body, the
    title and the input signature do not, so nothing is re-extracted.
  * REVISED - the text changed under the same adapter method. The new body
    replaces the old one and the item is re-queued, in one transaction, and
    only if the row still holds the body this check compared against
    (otherwise SUPERSEDED: a newer write won, and this response is dropped).
  * a failure - FAILED, RATE_LIMITED, NOT_FOUND, FORBIDDEN, ROBOTS_DISALLOWED,
    REFUSED (unsafe address, a redirect off the article's own host or down to
    http, an oversized page), BODY_UNAVAILABLE, ADAPTER_MISMATCH (the page now
    reads through a different method, so the two texts are not comparable).
    The stored body, its status and its Event are left exactly as they were;
    only the attempt is recorded. A failed check never reads as current.
    FORBIDDEN and ROBOTS_DISALLOWED stop re-checks for good - no login,
    CAPTCHA or access control is worked around - and NOT_FOUND stops after
    `NOT_FOUND_LIMIT` in a row.
"""

from __future__ import annotations

import email.utils
import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from . import acquisition, content_store, image_fetch

log = logging.getLogger("dancemate.article_refresh")

# --- policy --------------------------------------------------------------------

#: Adapter methods whose text is the article's own scope (see module doc).
SCOPED_METHODS = (
    acquisition.METHOD_TEMPLATE_BOARD,
    acquisition.METHOD_ARTICLE_REGION,
    acquisition.METHOD_DANCEINFO_PAYLOAD,
    acquisition.METHOD_DANCEINFO,
    acquisition.METHOD_OG_DESCRIPTION,
)
FETCHED = (acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL)

NEAR_EVENT_DAYS = 14
RECENT_DAYS = 7
INTERVAL_NEAR = timedelta(hours=24)
INTERVAL_FAR = timedelta(hours=72)
SIGNAL_MIN_SPACING = timedelta(hours=12)

MAX_REFRESHES_PER_TICK = 2
HOST_DAILY_BUDGET = 40
RATE_LIMIT_PAUSE = timedelta(hours=1)
MAX_ARTICLE_BYTES = 3 * 1024 * 1024

BACKOFF_BASE = timedelta(hours=1)
BACKOFF_CAP = timedelta(days=7)
NOT_FOUND_WAIT = timedelta(hours=24)
NOT_FOUND_LIMIT = 2

# --- outcomes (migration 051's check) -------------------------------------------

UNCHANGED = "UNCHANGED"
NOT_MODIFIED = "NOT_MODIFIED"
REVISED = "REVISED"
SUPERSEDED = "SUPERSEDED"
FAILED = "FAILED"
RATE_LIMITED = "RATE_LIMITED"
NOT_FOUND = "NOT_FOUND"
FORBIDDEN = "FORBIDDEN"
ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
REFUSED = "REFUSED"
ADAPTER_MISMATCH = "ADAPTER_MISMATCH"
BODY_UNAVAILABLE = "BODY_UNAVAILABLE"

SUCCESSES = (UNCHANGED, NOT_MODIFIED, REVISED)
FAILURES = (FAILED, RATE_LIMITED, NOT_FOUND, FORBIDDEN, ROBOTS_DISALLOWED, REFUSED,
            ADAPTER_MISMATCH, BODY_UNAVAILABLE)
#: No further automatic re-check after these.
STOPPING = (FORBIDDEN, ROBOTS_DISALLOWED)

# --- states shown to an operator (derived, never stored) ------------------------

NOT_ELIGIBLE = "NOT_ELIGIBLE"
ARTICLE_CURRENT = "ARTICLE_CURRENT"
ARTICLE_REFRESH_DUE = "ARTICLE_REFRESH_DUE"
ARTICLE_REFRESH_PENDING = "ARTICLE_REFRESH_PENDING"
ARTICLE_REFRESH_FAILED = "ARTICLE_REFRESH_FAILED"
ARTICLE_CHANGED_REEXTRACTION_PENDING = "ARTICLE_CHANGED_REEXTRACTION_PENDING"
SOURCE_FETCH_BLOCKED = content_store.FLAG_SOURCE_FETCH_BLOCKED
STATES = (NOT_ELIGIBLE, ARTICLE_CURRENT, ARTICLE_REFRESH_DUE, ARTICLE_REFRESH_PENDING,
          ARTICLE_REFRESH_FAILED, ARTICLE_CHANGED_REEXTRACTION_PENDING, SOURCE_FETCH_BLOCKED)

# --- SQL ------------------------------------------------------------------------

_TODAY = "(now() AT TIME ZONE 'Asia/Seoul')::date"

# `rel.next_event_date`: the earliest date of an Event this item feeds (as
# its source or its primary source) that has not ended yet - an upcoming one,
# or a multi-day one still running; NULL when there is none. One aggregate
# over events, hash-joined, rather than a per-row subquery: the OR of the two
# columns defeats any index, and the per-row form cost ~0.4 s a tick on a
# copy of Production even before the board's slower storage.
_RELEVANCE = (
    "LEFT JOIN (SELECT item_id, min(event_date) AS next_event_date FROM ("
    "  SELECT source_item_id AS item_id, event_date FROM events "
    "   WHERE COALESCE(end_date, event_date) >= " + _TODAY + " "
    "  UNION ALL SELECT primary_source_item_id, event_date FROM events "
    "   WHERE primary_source_item_id IS NOT NULL "
    "     AND COALESCE(end_date, event_date) >= " + _TODAY + ") x "
    " GROUP BY item_id) rel ON rel.item_id = c.source_item_id "
)

_FROM = (
    "FROM source_item_content c "
    "JOIN source_items i ON i.source_item_id = c.source_item_id "
    "JOIN sources s ON s.source_id = i.source_id "
)

# Shape of the article: what kind of body this is, independent of time.
_ARTICLE = (
    "c.acquisition_status = ANY(%(fetched)s) AND c.extracted_text IS NOT NULL "
    "AND c.acquisition_method = ANY(%(scoped)s) AND c.fetched_url IS NOT NULL "
    "AND NOT (COALESCE(s.config->>'parser', '') = ANY(%(api_parsers)s))"
)

_STOPPED = (
    "(COALESCE(c.refresh_outcome, '') = ANY(%(stopping)s) "
    " OR (COALESCE(c.refresh_outcome, '') = %(not_found)s "
    "     AND c.refresh_failures >= %(not_found_limit)s))"
)

# The selection's own columns. `signal`: the discovery record was stored
# again after the last time anyone asked the server for this article.
_COLUMNS = (
    "c.*, i.url, i.collected_at AS source_collected_at, s.source_key, s.enabled AS source_enabled, "
    "rel.next_event_date, "
    "(rel.next_event_date IS NOT NULL AND rel.next_event_date <= "
    + _TODAY + " + %(near_days)s) AS near_event, "
    "(i.collected_at > COALESCE(GREATEST(c.refresh_attempted_at, c.last_attempt_at), "
    "  '-infinity'::timestamptz)) AS signal "
)

_RELEVANT = "(rel.next_event_date IS NOT NULL OR c.first_attempt_at >= now() - %(recent)s)"

_INTERVAL = ("(CASE WHEN rel.next_event_date IS NOT NULL AND rel.next_event_date <= "
             + _TODAY + " + %(near_days)s THEN %(near)s ELSE %(far)s END)")

_DUE = (
    "(CASE WHEN c.refresh_next_at IS NOT NULL THEN c.refresh_next_at <= now() "
    " ELSE GREATEST(c.fetched_at, c.refresh_checked_at) <= now() - " + _INTERVAL + " "
    "   OR (i.collected_at > COALESCE(GREATEST(c.refresh_attempted_at, c.last_attempt_at), "
    "        '-infinity'::timestamptz) "
    "       AND GREATEST(c.fetched_at, c.refresh_attempted_at) <= now() - %(spacing)s) END)"
)

_PRIORITY = (
    "(CASE WHEN rel.next_event_date IS NOT NULL AND rel.next_event_date <= "
    + _TODAY + " + %(near_days)s THEN 1 "
    " WHEN i.collected_at > COALESCE(GREATEST(c.refresh_attempted_at, c.last_attempt_at), "
    "      '-infinity'::timestamptz) THEN 2 "
    " WHEN rel.next_event_date IS NOT NULL THEN 3 ELSE 4 END)"
)

#: Everything the refresh may select: the article shape, an enabled source,
#: still relevant, and not stopped.
ELIGIBLE = "(" + _ARTICLE + " AND s.enabled AND " + _RELEVANT + " AND NOT " + _STOPPED + ")"


def _params() -> dict[str, Any]:
    return {
        "fetched": list(FETCHED),
        "scoped": list(SCOPED_METHODS),
        "api_parsers": list(acquisition.NON_HTML_API_PARSERS),
        "stopping": list(STOPPING),
        "not_found": NOT_FOUND,
        "not_found_limit": NOT_FOUND_LIMIT,
        "near_days": NEAR_EVENT_DAYS,
        "recent": timedelta(days=RECENT_DAYS),
        "near": INTERVAL_NEAR,
        "far": INTERVAL_FAR,
        "spacing": SIGNAL_MIN_SPACING,
    }


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def due_articles(con, *, limit: int = 50) -> list[dict[str, Any]]:
    """Eligible articles whose re-check is due, most urgent first."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT " + _COLUMNS + ", " + _PRIORITY + " AS priority " + _FROM +
            _RELEVANCE +
            "WHERE " + ELIGIBLE + " AND " + _DUE + " "
            "ORDER BY priority, GREATEST(c.fetched_at, c.refresh_checked_at) NULLS FIRST, "
            "  c.source_item_id LIMIT %(limit)s",
            {**_params(), "limit": limit},
        )
        return _rows(cur)


def host_of(url: str | None) -> str:
    return urllib.parse.urlparse(url or "").netloc.lower()


def host_usage(con, *, now: datetime | None = None) -> tuple[dict[str, int], set[str]]:
    """Re-checks per host in the last 24 h, and the hosts paused by a recent 429."""
    now = now or datetime.now(timezone.utc)
    with con.cursor() as cur:
        cur.execute(
            "SELECT host, count(*), "
            "  bool_or(refresh_result = %s AND fetched_at > %s) "
            "FROM content_fetch_log WHERE purpose = 'REFRESH' AND fetched_at > %s "
            "GROUP BY host",
            (RATE_LIMITED, now - RATE_LIMIT_PAUSE, now - timedelta(hours=24)),
        )
        rows = cur.fetchall()
    return {r[0]: int(r[1]) for r in rows}, {r[0] for r in rows if r[2]}


# --- the guarded fetch ----------------------------------------------------------


class _RefreshRedirectHandler(image_fetch._SafeRedirectHandler):
    """Every hop re-validated: still the article's own host, never down to
    http, allowed by robots.txt, and (the image fetcher's own check) a public
    address within MAX_REDIRECTS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlparse(req.full_url)
        new = urllib.parse.urlparse(urllib.parse.urljoin(req.full_url, newurl))
        if (new.hostname or "").lower() != (old.hostname or "").lower():
            raise acquisition.FetchRefused(
                "CROSS_HOST_REDIRECT", f"redirect off the article's host to {new.hostname}")
        if old.scheme == "https" and new.scheme != "https":
            raise acquisition.FetchRefused("DOWNGRADE_REDIRECT", "redirect from https to http")
        if not acquisition.robots_allows(new.geturl()):
            raise acquisition.FetchRefused(
                "ROBOTS_DISALLOWED", f"robots.txt disallows the redirect to {new.geturl()}")
        try:
            return super().redirect_request(req, fp, code, msg, headers, newurl)
        except image_fetch.UnsafeImageURL as exc:
            raise acquisition.FetchRefused("UNSAFE_ADDRESS", str(exc)) from None


class _Bounded:
    """A response whose body may not exceed ``limit`` bytes."""

    def __init__(self, response, limit: int):
        self._response, self._limit = response, limit
        self.status = getattr(response, "status", 200)
        self.headers = response.headers

    def geturl(self):
        return self._response.geturl()

    def read(self, *_args):
        declared = self.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > self._limit:
            raise acquisition.FetchRefused(
                "RESPONSE_TOO_LARGE", f"declared {declared} bytes, limit {self._limit}")
        body = self._response.read(self._limit + 1)
        if len(body) > self._limit:
            raise acquisition.FetchRefused(
                "RESPONSE_TOO_LARGE", f"more than {self._limit} bytes")
        return body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._response.close()
        return False


_OPENER = urllib.request.build_opener(_RefreshRedirectHandler)


def guarded_open(request, timeout=None):
    """`acquisition.fetch()`'s opener for a re-check."""
    try:
        image_fetch.resolve_safe(request.full_url)
    except image_fetch.UnsafeImageURL as exc:
        raise acquisition.FetchRefused("UNSAFE_ADDRESS", str(exc)) from None
    return _Bounded(_OPENER.open(request, timeout=timeout), MAX_ARTICLE_BYTES)


def fetch_article(url: str, headers: dict[str, str]) -> acquisition.AcquisitionOutcome:
    return acquisition.fetch(url, opener=guarded_open, headers=headers)


# --- one re-check ---------------------------------------------------------------


def classify(row: dict[str, Any], outcome: acquisition.AcquisitionOutcome) -> str:
    """What this response says about the stored article."""
    if outcome.status == acquisition.NOT_MODIFIED:
        return NOT_MODIFIED
    if outcome.status in FETCHED:
        if outcome.method != row.get("acquisition_method"):
            return ADAPTER_MISMATCH
        if outcome.content_hash == row.get("content_hash"):
            return UNCHANGED
        return REVISED
    if outcome.error_code == "ROBOTS_DISALLOWED":
        return ROBOTS_DISALLOWED
    if outcome.status == acquisition.LOGIN_REQUIRED or outcome.http_status in (401, 403):
        return FORBIDDEN
    if outcome.http_status == 429:
        return RATE_LIMITED
    if outcome.http_status in (404, 410):
        return NOT_FOUND
    if outcome.status == acquisition.FETCH_BLOCKED and outcome.error_code not in (
            None, "BODY_UNAVAILABLE", "BLOCKED", "NOT_FOUND"):
        return REFUSED
    if outcome.error_code == "BODY_UNAVAILABLE":
        return BODY_UNAVAILABLE
    return FAILED


def _retry_after(value: str | None, now: datetime) -> timedelta | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return timedelta(seconds=int(value))
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when - now


def backoff(result: str, failures: int, retry_after: str | None, now: datetime) -> datetime | None:
    """When a failed re-check may be tried again; None once it has stopped."""
    if result in STOPPING or (result == NOT_FOUND and failures >= NOT_FOUND_LIMIT):
        return None
    if result == NOT_FOUND:
        return now + NOT_FOUND_WAIT
    delay = min(BACKOFF_BASE * (2 ** max(failures - 1, 0)), BACKOFF_CAP)
    if result == RATE_LIMITED:
        asked = _retry_after(retry_after, now)
        if asked is not None:
            delay = max(delay, min(asked, BACKOFF_CAP))
    return now + delay


def _log(cur, row: dict[str, Any], outcome, result: str) -> None:
    cur.execute(
        "INSERT INTO content_fetch_log (source_item_id, host, http_status, outcome, "
        "  text_length, duration_ms, purpose, refresh_result) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'REFRESH', %s)",
        (row["source_item_id"], host_of(outcome.fetched_url or row.get("fetched_url")) or "unknown",
         outcome.http_status, outcome.status, outcome.content_length, outcome.duration_ms,
         result),
    )


def refresh_one(con, row: dict[str, Any], *, fetcher=None,
                now: datetime | None = None) -> str:
    """Re-check one article (a `due_articles()` row). Returns its outcome."""
    fetcher = fetcher or fetch_article
    validators = {}
    if row.get("refresh_etag"):
        validators["If-None-Match"] = row["refresh_etag"]
    if row.get("refresh_last_modified"):
        validators["If-Modified-Since"] = row["refresh_last_modified"]
    outcome = fetcher(row["fetched_url"], validators)
    # Every stamp below is the database's now(), the clock reprocessed_at and
    # the queue are read against; `now` only anchors an HTTP-date Retry-After.
    now = now or datetime.now(timezone.utc)
    result = classify(row, outcome)
    key = {"id": row["source_item_id"], "hash": row.get("content_hash"),
           "status": row.get("acquisition_status")}

    with con.transaction(), con.cursor() as cur:
        if result in (UNCHANGED, NOT_MODIFIED):
            cur.execute(
                "UPDATE source_item_content SET refresh_attempted_at = now(), "
                "  refresh_checked_at = now(), refresh_outcome = %(result)s, "
                "  refresh_failures = 0, refresh_next_at = NULL, refresh_error = NULL, "
                "  refresh_etag = COALESCE(%(etag)s, refresh_etag), "
                "  refresh_last_modified = COALESCE(%(lm)s, refresh_last_modified) "
                "WHERE source_item_id = %(id)s AND content_hash IS NOT DISTINCT FROM %(hash)s "
                "  AND acquisition_status = %(status)s",
                {**key, "result": result, "etag": outcome.etag,
                 "lm": outcome.last_modified},
            )
            if cur.rowcount == 0:
                result = SUPERSEDED
        elif result == REVISED:
            # Only over the body this check compared against: if anything
            # stored a newer one meanwhile, this response is the older one.
            cur.execute(
                "UPDATE source_item_content SET "
                "  acquisition_status = %(new_status)s, extracted_text = %(text)s, "
                "  content_length = %(length)s, previous_content_hash = content_hash, "
                "  content_hash = %(new_hash)s, title = %(title)s, canonical_url = %(canonical)s, "
                "  http_status = %(http)s, content_type = %(ctype)s, "
                "  image_count = %(images)s, poster_candidates = %(posters)s::jsonb, "
                "  redacted_spans = %(redacted)s, fetched_at = now(), updated_at = now(), "
                "  refresh_attempted_at = now(), refresh_checked_at = now(), "
                "  refresh_revised_at = now(), refresh_outcome = %(result)s, "
                "  refresh_failures = 0, refresh_next_at = NULL, refresh_error = NULL, "
                "  refresh_etag = %(etag)s, refresh_last_modified = %(lm)s "
                "WHERE source_item_id = %(id)s AND content_hash IS NOT DISTINCT FROM %(hash)s "
                "  AND acquisition_status = %(status)s",
                {**key, "result": result, "new_status": outcome.status,
                 "text": outcome.text, "length": outcome.content_length,
                 "new_hash": outcome.content_hash, "title": outcome.title,
                 "canonical": outcome.canonical_url, "http": outcome.http_status,
                 "ctype": outcome.content_type, "images": len(outcome.images),
                 "posters": json.dumps(outcome.images[:10]), "redacted": outcome.redacted_spans,
                 "etag": outcome.etag, "lm": outcome.last_modified},
            )
            if cur.rowcount == 0:
                result = SUPERSEDED
            else:
                content_store.mark_needs_reextract(con, row["source_item_id"])
        if result == SUPERSEDED:
            cur.execute(
                "UPDATE source_item_content SET refresh_attempted_at = now(), "
                "  refresh_outcome = %s WHERE source_item_id = %s",
                (SUPERSEDED, row["source_item_id"]))
        elif result in FAILURES:
            failures = int(row.get("refresh_failures") or 0) + 1
            retry = backoff(result, failures, outcome.retry_after, now)
            cur.execute(
                "UPDATE source_item_content SET refresh_attempted_at = now(), "
                "  refresh_outcome = %s, refresh_failures = %s, "
                "  refresh_next_at = now() + %s::interval, refresh_error = %s "
                "WHERE source_item_id = %s",
                (result, failures, (retry - now) if retry else None,
                 ((outcome.error or outcome.error_code or result)[:500]),
                 row["source_item_id"]),
            )
        _log(cur, row, outcome, result)
    return result


def run(con, *, max_refreshes: int = MAX_REFRESHES_PER_TICK, fetcher=None,
        sleep=time.sleep) -> dict[str, Any]:
    """One tick's re-checks, within the per-tick and per-host budgets."""
    counts: dict[str, Any] = {"due": 0, "attempted": 0, "deferred_by_budget": 0,
                              "revised_ids": []}
    due = due_articles(con, limit=max(50, max_refreshes * 10))
    counts["due"] = len(due)
    used, paused = host_usage(con)
    for row in due:
        if counts["attempted"] >= max_refreshes:
            break
        host = host_of(row["fetched_url"])
        if host in paused or used.get(host, 0) >= HOST_DAILY_BUDGET:
            counts["deferred_by_budget"] += 1
            continue
        if counts["attempted"]:
            sleep(acquisition.MIN_DELAY_SECONDS)
        result = refresh_one(con, row, fetcher=fetcher)
        counts["attempted"] += 1
        counts[result] = counts.get(result, 0) + 1
        used[host] = used.get(host, 0) + 1
        if result == REVISED:
            counts["revised_ids"].append(row["source_item_id"])
        if result == RATE_LIMITED:
            paused.add(host)
        log.info("refresh item=%s host=%s %s", row["source_item_id"], host, result)
    return counts


def describe(counts: dict[str, Any]) -> str:
    """One clause for the content-acquisition job's detail line."""
    parts = [f"refresh {counts['attempted']}/{counts['due']} due"]
    for key in SUCCESSES + (SUPERSEDED,) + FAILURES:
        if counts.get(key):
            parts.append(f"{key.lower()}={counts[key]}")
    if counts.get("deferred_by_budget"):
        parts.append(f"deferred={counts['deferred_by_budget']}")
    if counts.get("revised_ids"):
        parts.append(f"revised_ids={counts['revised_ids']}")
    return " ".join(parts)


# --- what an operator sees ------------------------------------------------------


def inspect(con, source_item_id: int) -> dict[str, Any] | None:
    """The database facts `state()` needs about one item; None without a content row."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT " + _COLUMNS + ", "
            "  (" + _ARTICLE + ") AS article_shape, "
            "  (" + ELIGIBLE + ") AS eligible, "
            "  (" + ELIGIBLE + " AND " + _DUE + ") AS due, "
            "  (" + _STOPPED + ") AS stopped, "
            "  GREATEST(c.fetched_at, c.refresh_checked_at) + " + _INTERVAL + " AS next_due_at, "
            "  COALESCE(" + content_store._REVISED_SINCE_READ + ", false) AS revised_since_read "
            + _FROM +
            _RELEVANCE +
            "WHERE c.source_item_id = %(id)s",
            {**_params(), **content_store._signature_params(), "id": source_item_id},
        )
        found = _rows(cur)
    if not found:
        return None
    row = found[0]
    used, paused = host_usage(con)
    host = host_of(row.get("fetched_url"))
    row["host"] = host
    row["host_used_24h"] = used.get(host, 0)
    row["host_paused"] = host in paused
    return row


def _ineligible_reason(row: dict[str, Any]) -> str:
    if row.get("acquisition_status") not in FETCHED or not row.get("extracted_text"):
        return "no fetched article body is held"
    if row.get("acquisition_method") == acquisition.METHOD_DISCOVERY_SYNTHESIZED:
        return "its collector re-reads this body on every collection"
    if row.get("acquisition_method") not in SCOPED_METHODS:
        return (f"whole-page text ({row.get('acquisition_method')}): no adapter scope "
                "to tell an edit from page furniture")
    if not row.get("article_shape"):
        return "the source's API record is not an HTML article"
    if not row.get("source_enabled"):
        return "source disabled"
    if row.get("stopped"):
        return f"stopped after {row.get('refresh_outcome')}"
    return f"no event that has not ended, and first fetched more than {RECENT_DAYS} days ago"


def state(row: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    """One item's article freshness (an `inspect()` row), for the intake page."""
    row = row or {}
    now = now or datetime.now(timezone.utc)
    stopped = bool(row.get("stopped"))
    failures = int(row.get("refresh_failures") or 0)
    revised_at = row.get("refresh_revised_at")
    reread_after = (row.get("reprocessed_at") is not None and revised_at is not None
                    and row["reprocessed_at"] >= revised_at)
    if row.get("acquisition_status") == acquisition.FETCH_BLOCKED:
        name, reason = SOURCE_FETCH_BLOCKED, (
            "the source refused the body; the acquisition retry schedule re-asks it, "
            "never a re-check")
    elif revised_at is not None and (row.get("revised_since_read") or not reread_after
                                     or row.get("extracted_engine_version") is None):
        name, reason = ARTICLE_CHANGED_REEXTRACTION_PENDING, (
            f"article text revised at {str(revised_at)[:19]}; waiting for the engine re-read")
    elif failures and (row.get("refresh_outcome") in FAILURES):
        name = ARTICLE_REFRESH_FAILED
        reason = (f"last re-check {row.get('refresh_outcome')}"
                  f" ({failures} in a row): {row.get('refresh_error') or '-'}; "
                  + ("no further automatic re-check" if stopped else
                     f"next try {str(row.get('refresh_next_at'))[:19]}")
                  + "; freshness unknown, the stored body is kept")
    elif not row.get("eligible"):
        name, reason = NOT_ELIGIBLE, _ineligible_reason(row)
    elif row.get("due"):
        held = row.get("host_paused") or row.get("host_used_24h", 0) >= HOST_DAILY_BUDGET
        name = ARTICLE_REFRESH_PENDING if held else ARTICLE_REFRESH_DUE
        reason = ("due, held back by the host budget or a 429 pause" if held
                  else "due; the next scheduler tick re-checks it")
    else:
        name, reason = ARTICLE_CURRENT, (
            f"last read {str(row.get('refresh_checked_at') or row.get('fetched_at'))[:19]}, "
            f"next re-check after {str(row.get('next_due_at'))[:19]}")
    return {
        "state": name,
        "reason": reason,
        "eligible": bool(row.get("eligible")),
        "host": row.get("host"),
        "host_used_24h": row.get("host_used_24h"),
        "host_daily_budget": HOST_DAILY_BUDGET,
        "next_event_date": row.get("next_event_date"),
        "next_due_at": None if not row.get("eligible") else row.get("next_due_at"),
        "fetched_at": row.get("fetched_at"),
        "refresh_attempted_at": row.get("refresh_attempted_at"),
        "refresh_checked_at": row.get("refresh_checked_at"),
        "refresh_outcome": row.get("refresh_outcome"),
        "refresh_failures": failures,
        "refresh_next_at": row.get("refresh_next_at"),
        "refresh_error": row.get("refresh_error"),
        "refresh_revised_at": revised_at,
        "conditional_get": bool(row.get("refresh_etag") or row.get("refresh_last_modified")),
        "stopped": stopped,
    }


def summary(con) -> dict[str, Any]:
    """The operator's counts (Part G 27), from the content rows and the log."""
    params = _params()
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE " + ELIGIBLE + "), "
            "  count(*) FILTER (WHERE " + ELIGIBLE + " AND " + _DUE + "), "
            "  count(*) FILTER (WHERE c.refresh_revised_at IS NOT NULL), "
            "  count(*) FILTER (WHERE c.refresh_revised_at IS NOT NULL "
            "     AND c.reprocessed_at >= c.refresh_revised_at "
            "     AND c.extracted_engine_version IS NOT NULL), "
            "  count(*) FILTER (WHERE " + _ARTICLE + " AND " + _STOPPED + "), "
            "  count(*) FILTER (WHERE c.acquisition_status = ANY(%(fetched)s) "
            "     AND c.acquisition_method <> ALL(%(scoped)s) "
            "     AND c.acquisition_method <> %(synth)s), "
            "  count(*) FILTER (WHERE c.acquisition_status = %(blocked)s) "
            + _FROM +
            _RELEVANCE,
            {**params, "synth": acquisition.METHOD_DISCOVERY_SYNTHESIZED,
             "blocked": acquisition.FETCH_BLOCKED},
        )
        (eligible, due, revised_items, reextracted, stopped, whole_page,
         blocked) = cur.fetchone()
        cur.execute(
            "SELECT refresh_result, count(*) FILTER (WHERE fetched_at > now() - interval '24 hours'), "
            "  count(*) FROM content_fetch_log WHERE purpose = 'REFRESH' GROUP BY 1")
        by_result = {r[0]: {"24h": int(r[1]), "all": int(r[2])} for r in cur.fetchall()}
        cur.execute(
            "SELECT host, count(*) FROM content_fetch_log WHERE purpose = 'REFRESH' "
            "  AND fetched_at > now() - interval '24 hours' GROUP BY 1 ORDER BY 2 DESC")
        hosts = {r[0]: int(r[1]) for r in cur.fetchall()}
        cur.execute(
            "SELECT count(*) FROM source_item_content c "
            "JOIN source_items i ON i.source_item_id = c.source_item_id "
            "WHERE " + content_store.EXTRACTION_FILTERS["REVIEW"],
            content_store.review_filter_params())
        review_recommended = cur.fetchone()[0]

    def window(keys, span):
        return sum(by_result.get(k, {}).get(span, 0) for k in keys)

    revised_24h = window((REVISED,), "24h")
    return {
        "eligible_full_articles": int(eligible),
        "refresh_due": int(due),
        "refresh_attempted_24h": window(by_result.keys(), "24h"),
        "refresh_attempted_all": window(by_result.keys(), "all"),
        "refresh_succeeded_24h": window(SUCCESSES, "24h"),
        "not_modified_24h": window((NOT_MODIFIED,), "24h"),
        "unchanged_24h": window((UNCHANGED,), "24h"),
        "relevant_content_revised_24h": revised_24h,
        "relevant_content_revised_all": window((REVISED,), "all"),
        "reextraction_requested_24h": revised_24h,
        "revised_items": int(revised_items),
        "reextraction_completed": int(reextracted),
        "refresh_failed_24h": window(FAILURES, "24h"),
        "superseded_24h": window((SUPERSEDED,), "24h"),
        "stopped": int(stopped),
        "excluded_whole_page_text": int(whole_page),
        "fetch_blocked": int(blocked),
        "human_review_recommended": int(review_recommended),
        "by_result": by_result,
        "hosts_24h": hosts,
        "host_daily_budget": HOST_DAILY_BUDGET,
        "max_refreshes_per_tick": MAX_REFRESHES_PER_TICK,
    }
