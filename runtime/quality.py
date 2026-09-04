"""How good is the data we would show a dancer tonight?

The console has always been able to say how many things it collected. That is
not the same question. A hundred events with no times is worse than fifteen
with times, and until now nothing on the screen said so.

Two distinctions this module refuses to blur:

    **Missing is not wrong.** A blank fee is a fee we do not have. A 07:30 on
    an evening milonga is a time we do have and got backwards. Missing is
    counted and shown as 미확인; wrong is a P0 with its own alert, because it
    sends someone to a locked door.

    **Extracted is not resolved.** Reading `아미고스튜디오` off a post and
    recognising it as a venue somebody registered are different achievements,
    and reporting them as one number hides which half is failing.

Every count here is over the events a user could actually be shown: live,
canonical, not rejected. Counting fixtures would flatter the numbers while
telling us nothing about tonight.
"""

from __future__ import annotations

from typing import Any

# The condition the alpha search itself uses. Quality is measured over exactly
# what a reader can reach, so the dashboard and the site cannot drift apart.
LISTED = (
    "provenance = 'LIVE' AND listing_state = 'LISTED' AND canonical_event_id IS NULL"
)
# The same condition for queries that alias the events table.
LISTED_E = (
    "e.provenance = 'LIVE' AND e.listing_state = 'LISTED' "
    "AND e.canonical_event_id IS NULL"
)

# A start time before noon on an event whose post said afternoon or evening.
# Engine v0.74 records the meridiem evidence it had, so this is a lookup, not a
# guess: EXPLICIT means the post said so, ABSENT means it did not.
WRONG_TIME_SQL = (
    "start_time < TIME '12:00' AND time_evidence = 'EXPLICIT' "
    "AND event_type IN ('MILONGA', 'PRACTICA')"
)


def _row(cur) -> dict[str, Any]:
    return dict(zip([c.name for c in cur.description], cur.fetchone()))


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def completeness(con, *, upcoming_only: bool = False) -> dict[str, Any]:
    """Field-by-field completeness over the events a user can reach.

    ``upcoming_only`` narrows it to today onward, which is the number that
    matters operationally -- last month's missing fee is not worth anyone's
    afternoon.
    """
    window = " AND event_date >= current_date" if upcoming_only else ""
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS events, "
            "  count(*) FILTER (WHERE event_date IS NOT NULL) AS date_known, "
            "  count(*) FILTER (WHERE start_time IS NOT NULL) AS time_known, "
            "  count(*) FILTER (WHERE start_time IS NOT NULL "
            "                     AND time_evidence = 'ABSENT') AS time_unconfirmed, "
            "  count(*) FILTER (WHERE venue_text IS NOT NULL) AS venue_extracted, "
            "  count(*) FILTER (WHERE venue_status = 'RESOLVED') AS venue_resolved, "
            "  count(*) FILTER (WHERE fee IS NOT NULL) AS fee_known, "
            "  count(*) FILTER (WHERE region_id IS NOT NULL) AS region_known, "
            "  count(*) FILTER (WHERE engine_status = 'VERIFIED') AS verified, "
            "  count(*) FILTER (WHERE review_state <> 'PENDING') AS human_reviewed, "
            f"  count(*) FILTER (WHERE {WRONG_TIME_SQL}) AS wrong_time "
            f"FROM events WHERE {LISTED}{window}"
        )
        found = _row(cur)

    events = found["events"] or 0
    found["missing"] = {
        "date": events - found["date_known"],
        "time": events - found["time_known"],
        "venue": events - found["venue_extracted"],
        "venue_resolution": events - found["venue_resolved"],
        "fee": events - found["fee_known"],
        "region": events - found["region_known"],
    }
    # Named apart from everything above. A wrong value is not a gap.
    found["wrong"] = {"time": found["wrong_time"]}
    found["upcoming_only"] = upcoming_only
    return found


def percentage(part: int, whole: int) -> int | None:
    """Rounded percent, or None when there is nothing to divide by.

    None rather than 0: "no events" and "none of the events" read the same as a
    zero and mean opposite things.
    """
    return None if not whole else round(100 * part / whole)


def by_region(con) -> list[dict[str, Any]]:
    """Listed events per region, including the ones with no region at all."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT coalesce(r.name, '(지역 미확인)') AS region, r.code AS region_code, "
            "       count(*) AS events, "
            "       count(*) FILTER (WHERE e.event_date >= current_date) AS upcoming "
            "FROM events e LEFT JOIN regions r ON r.region_id = e.region_id "
            f"WHERE {LISTED_E} "
            "GROUP BY 1, 2 ORDER BY events DESC"
        )
        return _rows(cur)


def by_genre(con) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT coalesce(g.code, '(장르 미확인)') AS genre, count(*) AS events, "
            "       count(*) FILTER (WHERE e.event_date >= current_date) AS upcoming "
            "FROM events e LEFT JOIN genres g ON g.genre_id = e.genre_id "
            f"WHERE {LISTED_E} "
            "GROUP BY 1 ORDER BY events DESC"
        )
        return _rows(cur)


def wrong_values(con, *, limit: int = 20) -> list[dict[str, Any]]:
    """Events whose value contradicts the post it came from.

    Only one rule so far, and it is the one v0.77 was written for: a milonga
    starting before noon whose post carried an explicit PM marker. If this list
    is ever non-empty the extractor has regressed, which is a release blocker
    rather than a backlog item.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_name, event_date, start_time, end_time, "
            "       venue_text, source_url, 'PM_READ_AS_AM' AS rule "
            f"FROM events WHERE {LISTED} AND {WRONG_TIME_SQL} "
            "ORDER BY event_date DESC LIMIT %s",
            (limit,),
        )
        return _rows(cur)


def freshness(con) -> dict[str, Any]:
    """How recently the posts behind upcoming events were last collected.

    A dancer deciding tonight is relying on something we read at some point;
    when that was is part of the answer.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS upcoming, "
            "  count(*) FILTER (WHERE i.collected_at > now() - interval '24 hours') "
            "    AS checked_24h, "
            "  count(*) FILTER (WHERE i.collected_at IS NULL) AS never_traced, "
            "  max(i.collected_at) AS newest "
            "FROM events e LEFT JOIN source_items i ON i.source_item_id = e.source_item_id "
            "WHERE e.provenance = 'LIVE' AND e.listing_state = 'LISTED' "
            "  AND e.canonical_event_id IS NULL AND e.event_date >= current_date"
        )
        return _row(cur)


def snapshot(con) -> dict[str, Any]:
    """Everything the quality panel needs, in one read."""
    overall = completeness(con)
    upcoming = completeness(con, upcoming_only=True)
    return {
        "all": overall,
        "upcoming": upcoming,
        "by_region": by_region(con),
        "by_genre": by_genre(con),
        "wrong": wrong_values(con),
        "freshness": freshness(con),
    }


def upcoming_buckets(con) -> dict[str, int]:
    """How many listed events fall in each window a reader actually asks for.

    Excludes CANCELLED the same way events_api.search()'s default does - a
    cancelled event dated today is still LISTED (that stays true so a reader
    holding the link is told it is off, not 404'd) but is not "a place to
    dance tonight", so it must not appear in a count meant to answer that
    question either. Before this, a bucket counting CANCELLED-but-LISTED rows
    could exceed what search() actually served for the same window - not
    noise, a real predicate mismatch, visible only once a real event on the
    live board was ever marked CANCELLED for a listed today/tomorrow date.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT "
            "  count(*) FILTER (WHERE event_date = current_date) AS today, "
            "  count(*) FILTER (WHERE event_date = current_date + 1) AS tomorrow, "
            "  count(*) FILTER (WHERE event_date BETWEEN current_date "
            "                     AND current_date + 7) AS this_week, "
            "  count(*) FILTER (WHERE event_date >= current_date) AS upcoming, "
            "  count(*) FILTER (WHERE event_date < current_date) AS past "
            f"FROM events WHERE {LISTED} AND engine_status <> 'CANCELLED'"
        )
        return _row(cur)


def coverage_matrix(con, *, upcoming_only: bool = True) -> dict[str, Any]:
    """Genre against region, over what a reader can reach.

    The empty cells are the point. "Salsa in Busan: 0" is a coverage gap that
    no total can show, and it is the shape of the next release's work.
    """
    window = " AND e.event_date >= current_date" if upcoming_only else ""
    with con.cursor() as cur:
        cur.execute(
            "SELECT coalesce(g.code, '(장르 미확인)') AS genre, "
            "       coalesce(r.name, '(지역 미확인)') AS region, count(*) AS events "
            "FROM events e "
            "LEFT JOIN genres g ON g.genre_id = e.genre_id "
            "LEFT JOIN regions r ON r.region_id = e.region_id "
            f"WHERE {LISTED_E}{window} GROUP BY 1, 2",
            (),
        )
        cells = _rows(cur)
        cur.execute("SELECT code, name FROM genres WHERE enabled ORDER BY code")
        genres = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT name FROM regions WHERE enabled AND city IS NOT NULL ORDER BY name"
        )
        regions = [row[0] for row in cur.fetchall()]

    grid = {g: {r: 0 for r in regions} for g in genres}
    extra_regions: list[str] = []
    for cell in cells:
        genre, region = cell["genre"], cell["region"]
        grid.setdefault(genre, {r: 0 for r in regions})
        if region not in regions and region not in extra_regions:
            extra_regions.append(region)
        grid[genre][region] = cell["events"]
    return {
        "genres": sorted(grid),
        "regions": regions + extra_regions,
        "grid": grid,
        "upcoming_only": upcoming_only,
    }
