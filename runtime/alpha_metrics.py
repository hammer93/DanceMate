"""Did anyone look at tonight's list, and did they open anything?

That is the whole question. A private alpha with a handful of people does not
need to know who, when, how often, or from where — and answering those would
mean storing people.

So there is no identifier here. No IP, no session, no cookie, no user agent,
no referrer. Three counters and a timestamp:

    EVENT_LIST_VIEW     somebody loaded a list
    EVENT_DETAIL_VIEW   somebody opened one event
    SOURCE_LINK_CLICK   somebody went to read the original post

The third is the one worth having. A detail view says the card was interesting
enough to tap; a source click says the extraction was not enough and they went
to the post. That is a quality signal about DanceMate, not about a person.

Recording never blocks a page. A metrics table that can 500 a reader's evening
is worse than no metrics.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from . import db
from .config import Settings

log = logging.getLogger("dancemate.alpha_metrics")

EVENT_LIST_VIEW = "EVENT_LIST_VIEW"
EVENT_DETAIL_VIEW = "EVENT_DETAIL_VIEW"
SOURCE_LINK_CLICK = "SOURCE_LINK_CLICK"

KINDS = (EVENT_LIST_VIEW, EVENT_DETAIL_VIEW, SOURCE_LINK_CLICK)

LABELS = {
    EVENT_LIST_VIEW: "목록 열람",
    EVENT_DETAIL_VIEW: "상세 열람",
    SOURCE_LINK_CLICK: "원문 이동",
}


def record(settings: Settings, kind: str, *, event_id: int | None = None) -> bool:
    """Count one view. Returns whether it was counted; never raises.

    A page that cannot be measured still has to render. Every failure here --
    the database being down, the table not existing yet, an unknown kind -- is
    logged and swallowed.
    """
    if kind not in KINDS:
        log.warning("ignoring unknown alpha view kind %r", kind)
        return False
    try:
        with db.connect(settings, autocommit=True) as con, con.cursor() as cur:
            cur.execute(
                "INSERT INTO alpha_view_log (kind, event_id) VALUES (%s, %s)",
                (kind, event_id),
            )
        return True
    except Exception as exc:  # pragma: no cover - defensive by design
        log.debug("alpha view not recorded: %s", exc)
        return False


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def summary(con, *, days: int = 7) -> dict[str, Any]:
    """Counts for today and for the last week, plus what was opened most.

    Deliberately not a funnel percentage. With single-digit numbers a ratio is
    noise wearing a suit.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT kind, "
            "  count(*) FILTER (WHERE occurred_at::date = current_date) AS today, "
            "  count(*) FILTER (WHERE occurred_at > now() - make_interval(days => %s)) "
            "    AS recent "
            "FROM alpha_view_log GROUP BY kind",
            (days,),
        )
        by_kind = {r["kind"]: r for r in _rows(cur)}
        cur.execute(
            "SELECT l.event_id, e.event_name, e.event_date, count(*) AS views "
            "FROM alpha_view_log l "
            "LEFT JOIN events e ON e.event_id = l.event_id "
            "WHERE l.kind = %s AND l.occurred_at > now() - make_interval(days => %s) "
            "GROUP BY 1, 2, 3 ORDER BY views DESC LIMIT 5",
            (EVENT_DETAIL_VIEW, days),
        )
        opened = _rows(cur)

    return {
        "days": days,
        "counts": {
            kind: {
                "today": by_kind.get(kind, {}).get("today", 0),
                "recent": by_kind.get(kind, {}).get("recent", 0),
            }
            for kind in KINDS
        },
        "most_opened": opened,
    }


def snapshot(settings: Settings, *, days: int = 7) -> dict[str, Any]:
    """Everything the console panel needs. Never raises."""
    try:
        with db.connect(settings, autocommit=True) as con:
            return {"available": True, **summary(con, days=days)}
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "detail": str(exc)}
