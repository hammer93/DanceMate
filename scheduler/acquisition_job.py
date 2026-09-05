"""Scheduler job: fetch the original posts behind collected search results.

Runs between `source-intake` (discovery) and `engine-ingest` (extraction):

    source-intake -> content-acquisition -> engine-ingest

Bounded and polite by construction. A tick fetches a small number of posts,
waits between requests, honours each item's retry backoff, and never touches a
URL whose status has settled. On a 4GB board with a 32GB microSD, the wrong
default here would be hundreds of concurrent fetches.

A content fetch is not a provider API call. These do not consume the Kakao or
Naver quota and are counted separately, in `content_fetch_log`.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime import acquisition, content_store, db
from runtime.config import Settings

log = logging.getLogger("dancemate.scheduler.acquisition")

# One tick's budget. Small on purpose: the queue drains over several ticks
# rather than hammering a community site in one burst.
MAX_FETCHES_PER_TICK = 5


def run(settings: Settings, *, max_fetches: int = MAX_FETCHES_PER_TICK,
        sleep=time.sleep) -> str:
    """Fetch due items. Returns a one-line summary for job_runs.detail."""
    counts: dict[str, int] = {}
    total_chars = 0

    with db.connect(settings, autocommit=True) as con:
        # Anything collected but never queued becomes queued - see
        # content_store.newly_collected()'s own docstring for why a
        # NON_HTML_API_PARSERS source is excluded from that regardless of
        # its content state.
        newly = content_store.newly_collected(con)
        for source_item_id in newly:
            content_store.ensure_row(con, source_item_id)
        queued = content_store.mark_pending(con, newly)

        due = content_store.due_for_acquisition(con, limit=max_fetches)
        if not due:
            return f"nothing due (queued {queued})"

        for index, item in enumerate(due):
            if index:
                # Politeness delay between requests to the same community site.
                sleep(acquisition.MIN_DELAY_SECONDS)
            existing = content_store.get(con, item["source_item_id"])
            outcome = acquisition.fetch(item["url"])
            changed = content_store.content_changed(existing, outcome)
            content_store.record_outcome(con, item["source_item_id"], outcome)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            total_chars += outcome.content_length
            log.info(
                "acquire item=%s %s method=%s chars=%s changed=%s %s",
                item["source_item_id"], outcome.status, outcome.method,
                outcome.content_length, changed, outcome.error or "",
            )

    fetched = counts.get(acquisition.FETCHED_FULL, 0)
    partial = counts.get(acquisition.FETCHED_PARTIAL, 0)
    average = total_chars // max(1, sum(counts.values()))
    summary = (
        f"fetched {fetched} full, {partial} partial of {sum(counts.values())} "
        f"(avg {average} chars)"
    )
    other = {k: v for k, v in counts.items()
             if k not in (acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL)}
    if other:
        summary += f", {other}"
    if queued:
        summary += f", queued {queued}"
    return summary


def reacquire(settings: Settings, source_item_ids: list[int]) -> dict[str, Any]:
    """Force a re-fetch of specific items, ignoring their settled status.

    Used by the admin console and by the operator re-running acquisition over
    the existing live items. Still rate limited.
    """
    results: list[dict[str, Any]] = []
    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT source_item_id, url FROM source_items "
                "WHERE source_item_id = ANY(%s) AND url IS NOT NULL "
                "ORDER BY source_item_id",
                (source_item_ids,),
            )
            items = cur.fetchall()
        for index, (source_item_id, url) in enumerate(items):
            if index:
                time.sleep(acquisition.MIN_DELAY_SECONDS)
            outcome = acquisition.fetch(url)
            content_store.record_outcome(con, source_item_id, outcome)
            results.append({
                "source_item_id": source_item_id,
                "status": outcome.status,
                "method": outcome.method,
                "chars": outcome.content_length,
                "error": outcome.error,
            })
    return {"count": len(results), "results": results}
