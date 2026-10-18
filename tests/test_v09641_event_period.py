"""v0.96.41 - a festival on the calendar: its date, its period, and no time.

The engine reads a structured calendar's festival as one candidate for the
period (its first day, its last day only when the record states one, no time)
plus one candidate per night its own text dates and clocks. This is what the
rest of DanceMate does with them:

* `events.end_date` (migration 049) carries the stated last day - NULL for
  every one-day event and for a festival whose record states no end;
* every public date question asks "is it on that day" over the period
  (`events_api.LAST_DAY`), so an event without a period answers exactly as
  before, and a festival is found on each day its record says it runs;
* a festival is never folded into a night, and two calendars' records of one
  festival fold on their first day and resolved place;
* nothing anywhere reads a NULL time as 00:00.

Everything runs the real route: the engine's own `process_discovered_post()`
and `database.persist_events()` into a throwaway engine store, then
`normalize_all()`, `duplicates.scan()` and `events_api.search()` against the
real tables inside the `pg` fixture's rolled-back transaction.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta

import psycopg
import pytest

from runtime import duplicates, event_terms, events_api, normalization, public
from runtime.config import REPO_ROOT
from tests.test_v09639_evidence_and_listing import (  # noqa: F401 - fixtures
    _consistent,
    _event,
    _id,
    _snapshot,
    run_normalization,
    settings,
    store,
    venue,
)

if str(REPO_ROOT / "engine") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "engine"))


def _kr(day: date) -> str:
    return f"{day.year}년 {day.month}월 {day.day}일"


def _ingest(store, candidate_id: int, *, title: str, body: str, period: dict | None,
            fmt: str | None = "FESTIVAL") -> list[int]:
    """One record through the engine's own route into the throwaway store."""
    from src import database
    from src.collectors.base import RawPostRecord
    from src.live_pipeline import process_discovered_post

    url = f"https://example.test/v09641/{candidate_id}"
    post = RawPostRecord(source_id="SRC", platform="WEB", source_url=url, title=title,
                         body=body, acquisition_quality="FETCHED_FULL",
                         source_event_format=fmt if period is not None else None,
                         event_period=period)
    result = process_discovered_post(None, post)
    con = sqlite3.connect(store.path)
    con.row_factory = sqlite3.Row
    try:
        con.execute("INSERT INTO raw_posts VALUES (?,?,?,?,?,?,?)",
                    (candidate_id, "SRC", url, title, body, "2026-10-19T00:00:00", "cafe"))
        before = {r[0] for r in con.execute("SELECT candidate_id FROM event_candidates")}
        database.persist_events(con, candidate_id, result["events"])
        con.commit()
        ids = [r[0] for r in con.execute("SELECT candidate_id FROM event_candidates "
                                          "ORDER BY candidate_id") if r[0] not in before]
    finally:
        con.close()
    store.register(url, title)
    return ids


def _visible(pg, **query) -> list[dict]:
    return events_api.search(pg, limit=events_api.MAX_LIMIT, **query)["events"]


def _ids(events) -> set[int]:
    return {e["id"] for e in events}


@pytest.fixture
def today() -> date:
    return events_api.today()


# --- a date and nothing else -------------------------------------------------

def test_a_date_only_festival_is_a_date_and_no_time(pg, store, run_normalization, unique,
                                                    venue, today):
    day = today + timedelta(days=9)
    [cid] = _ingest(store, _id(unique, 1), title=f"Busan Tango Festival {unique}",
                    body=f"{_kr(day)} 장소: {venue['name']} 주최: Lucas",
                    period={"start": day.isoformat()})
    run_normalization()
    row = _event(pg, cid)
    assert (row["event_type"], row["event_date"], row["start_time"], row["end_time"],
            row["end_date"], row["time_evidence"], row["end_day_offset"]) == (
        "FESTIVAL", day, None, None, None, None, 0)
    assert row["venue_id"] == venue["venue_id"] and row["listing_state"] == "LISTED"

    [served] = [e for e in _visible(pg, on=day) if e["id"] == row["event_id"]]
    assert served["start_time"] is None and served["end_time"] is None
    assert served["time_confirmed"] is None and served["end_date"] is None
    assert served["event_type_label"] == "페스티벌"
    # Its start, and nothing about later days.
    assert row["event_id"] not in _ids(_visible(pg, on=day + timedelta(days=1)))
    card = public._when_line(served)
    assert "시간 미확인" in card and "00:00" not in card


def test_no_time_is_ever_shown_as_midnight(pg, store, run_normalization, unique, venue,
                                           today):
    day = today + timedelta(days=9)
    [cid] = _ingest(store, _id(unique, 2), title=f"Seoul Tango Week {unique}",
                    body=f"{_kr(day)} 장소: {venue['name']} 주최: x",
                    period={"start": day.isoformat()})
    run_normalization()
    [served] = [e for e in _visible(pg, on=day) if e["id"] == _event(pg, cid)["event_id"]]
    for html in (public._when_line(served), public._timeline_clock(served)):
        assert "00:00" not in html and "종일" not in html


# --- a stated period ---------------------------------------------------------

@pytest.fixture
def running(pg, store, run_normalization, unique, venue, today):
    """A festival that began two days ago and ends in three."""
    first, last = today - timedelta(days=2), today + timedelta(days=3)
    [cid] = _ingest(store, _id(unique, 3), title=f"Busan Tango Festival {unique}",
                    body=f"{_kr(first)} 장소: {venue['name']} 주최: Lucas",
                    period={"start": first.isoformat(), "end": last.isoformat()})
    run_normalization()
    row = _event(pg, cid)
    assert (row["event_date"], row["end_date"]) == (first, last)
    return {"row": row, "first": first, "last": last}


def test_a_running_festival_is_found_on_every_day_it_is_on(pg, running, today):
    event_id, first, last = running["row"]["event_id"], running["first"], running["last"]
    day = first
    while day <= last:
        assert event_id in _ids(_visible(pg, on=day, include_past=True)), day
        day += timedelta(days=1)
    assert event_id not in _ids(_visible(pg, on=last + timedelta(days=1)))
    assert event_id not in _ids(_visible(pg, on=first - timedelta(days=1), include_past=True))


@pytest.mark.parametrize("query", [
    {"when": "today"}, {"when": "tomorrow"}, {"when": "this_week"}, {"when": "upcoming"},
    {}, {"days": 7}, {"days": 14}, {"days": 30},
])
def test_the_windows_find_a_running_festival(pg, running, today, query):
    """TODAY, TOMORROW, this week, upcoming, the default list and D7/D14/D30
    all overlap a period that began before today - which a first-day-only
    reading would call over."""
    if "days" in query:
        query = {"date_from": today, "date_to": today + timedelta(days=query["days"])}
    found = _visible(pg, **query)
    assert running["row"]["event_id"] in _ids(found)
    [served] = [e for e in found if e["id"] == running["row"]["event_id"]]
    assert served["end_date"] == running["last"].isoformat()


def test_a_date_range_query_overlaps_the_period(pg, running):
    event_id, first, last = running["row"]["event_id"], running["first"], running["last"]
    assert event_id in _ids(_visible(pg, date_from=last, date_to=last + timedelta(days=7)))
    assert event_id in _ids(_visible(pg, date_from=first - timedelta(days=5), date_to=first,
                                     include_past=True))
    assert event_id not in _ids(_visible(pg, date_from=last + timedelta(days=1),
                                         date_to=last + timedelta(days=9)))


def test_the_calendar_counts_it_on_each_day_its_search_returns_it(pg, running):
    first, last = running["first"], running["last"]
    counts = events_api.week_counts(pg, start=first - timedelta(days=1),
                                    end=last + timedelta(days=1))
    for iso, count in counts.items():
        expected = events_api.search(pg, on=date.fromisoformat(iso), include_past=True,
                                     limit=events_api.MAX_LIMIT)["total"]
        assert count == expected, iso


def test_a_chip_still_counts_what_its_page_lists(pg, running):
    """v0.96.36's promise: the region chip for a window is that window's total."""
    window = (running["first"] + timedelta(days=1), running["last"])
    facets = public._facets_window(pg, window)
    listed = events_api.search(pg, date_from=window[0], date_to=window[1], limit=events_api.MAX_LIMIT)
    region = running["row"]["region_id"]
    with pg.cursor() as cur:
        cur.execute("SELECT name FROM regions WHERE region_id = %s", (region,))
        name = cur.fetchone()[0]
    chip = next(r["events"] for r in facets["regions"] if r["label"] == name)
    assert chip == sum(1 for e in listed["events"] if e.get("region") == name)


def test_a_past_period_is_past_once_its_last_day_is(pg, store, run_normalization, unique,
                                                    venue, today):
    first, last = today - timedelta(days=6), today - timedelta(days=1)
    [cid] = _ingest(store, _id(unique, 4), title=f"Old Tango Marathon {unique}",
                    body=f"{_kr(first)} 장소: {venue['name']} 주최: x",
                    period={"start": first.isoformat(), "end": last.isoformat()})
    run_normalization()
    event_id = _event(pg, cid)["event_id"]
    assert event_id not in _ids(_visible(pg))
    [served] = [e for e in _visible(pg, on=last, include_past=True) if e["id"] == event_id]
    assert public._is_past(served)


def test_a_one_day_event_answers_exactly_as_before(pg, store, run_normalization, unique,
                                                   venue, today):
    """No end_date, no fold: LAST_DAY is event_date."""
    day = today + timedelta(days=4)
    cid = store.add(_id(unique, 5), name=f"Friday Milonga {unique}", day=day.isoformat(),
                    start="20:00", end="23:00", venue=venue["name"])
    run_normalization()
    row = _event(pg, cid)
    assert row["end_date"] is None
    assert row["event_id"] in _ids(_visible(pg, on=day))
    for other in (day - timedelta(days=1), day + timedelta(days=1)):
        assert row["event_id"] not in _ids(_visible(pg, on=other))
    [served] = [e for e in _visible(pg, on=day) if e["id"] == row["event_id"]]
    assert served["end_date"] is None and served["start_time"] == "20:00"


# --- folds --------------------------------------------------------------------

@pytest.fixture
def two_calendars(pg, store, run_normalization, unique, venue, today):
    """TangoNOW dates it by its start, Miltang by its whole period."""
    first, last = today + timedelta(days=12), today + timedelta(days=20)
    [share] = _ingest(store, _id(unique, 6), title=f"BUSAN TANGO FESTIVAL {unique}",
                      body=f"{_kr(first)} 장소: {venue['name']} 주최: Lucas",
                      period={"start": first.isoformat()})
    [notice] = _ingest(store, _id(unique, 7), title=f"BUSAN TANGO FESTIVAL {unique}",
                       body=f"{_kr(first)} 장소: {venue['name']} (서울 마포구 월드컵북로 1) "
                            "원문 링크: https://x.test",
                       period={"start": first.isoformat(), "end": last.isoformat()})
    run_normalization()
    return {"ids": [share, notice], "first": first, "last": last}


def test_two_calendars_records_of_one_festival_are_one_event(pg, two_calendars):
    found = duplicates.scan(pg, on=two_calendars["first"])
    assert found["auto_merged"] == 1
    share, notice = (_event(pg, c) for c in two_calendars["ids"])
    folded = [e for e in (share, notice) if e["canonical_event_id"]]
    assert len(folded) == 1 and folded[0]["listing_state"] == "HIDDEN"
    with pg.cursor() as cur:
        cur.execute("SELECT rule, decided_by FROM event_duplicate_decisions "
                    "WHERE event_id = %s", (folded[0]["event_id"],))
        assert cur.fetchall() == [(duplicates.RULE_SAME_DATE_VENUE_FESTIVAL, "AUTO")]
    served = [e for e in _visible(pg, on=two_calendars["first"])
              if e["id"] in (share["event_id"], notice["event_id"])]
    assert len(served) == 1
    # The period is Miltang's to give, whichever record is canonical.
    assert served[0]["end_date"] == two_calendars["last"].isoformat()
    mid = two_calendars["first"] + timedelta(days=4)
    assert served[0]["id"] in _ids(_visible(pg, on=mid))


def test_normalize_and_scan_settle(pg, two_calendars, run_normalization):
    duplicates.scan(pg, on=two_calendars["first"])
    settled = _snapshot(pg, two_calendars["ids"])
    for _ in range(2):
        run_normalization.again()
        found = duplicates.scan(pg, on=two_calendars["first"])
        assert found["auto_merged"] == 0 and found["released"] == 0
        assert _snapshot(pg, two_calendars["ids"]) == settled
        _consistent(pg, two_calendars["ids"])


def test_a_festival_is_never_folded_into_a_night(pg, store, run_normalization, unique,
                                                 venue, today):
    """Its welcome milonga shares its first day and its room."""
    day = today + timedelta(days=14)
    [festival] = _ingest(store, _id(unique, 8), title=f"Tango Week {unique}",
                         body=f"{_kr(day)} 장소: {venue['name']} 주최: x",
                         period={"start": day.isoformat()})
    night = store.add(_id(unique, 9), name=f"Milonga {unique}", day=day.isoformat(),
                      start=None, venue=venue["name"])
    run_normalization()
    found = duplicates.scan(pg, on=day)
    assert found["auto_merged"] == 0
    ids = [_event(pg, c)["event_id"] for c in (festival, night)]
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_duplicate_pairs WHERE event_id = ANY(%s) "
                    "OR other_event_id = ANY(%s)", (ids, ids))
        assert cur.fetchone()[0] == 0
    assert set(ids) <= _ids(_visible(pg, on=day))


def test_a_festivals_own_night_folds_with_another_post_of_that_night(
        pg, store, run_normalization, unique, venue, today):
    first, last = today + timedelta(days=15), today + timedelta(days=17)
    night = first + timedelta(days=1)
    body = (f"{_kr(first)} 장소: {venue['name']} 주최: x "
            f"GALA MILONGA — {night.month}/{night.day}(토) 21:00~02:00")
    festival_ids = _ingest(store, _id(unique, 10), title=f"Tango Festival {unique}",
                           body=body, period={"start": first.isoformat(),
                                              "end": last.isoformat()})
    assert len(festival_ids) == 2
    other = store.add(_id(unique, 11), name=f"Gala {unique}", day=night.isoformat(),
                      start="21:00", end="02:00", offset=1, venue=venue["name"])
    run_normalization()
    gala = _event(pg, festival_ids[1])
    assert (gala["event_type"], gala["event_date"], str(gala["start_time"])[:5],
            str(gala["end_time"])[:5], gala["end_day_offset"], gala["end_date"]) == (
        "MILONGA", night, "21:00", "02:00", 1, None)
    assert duplicates.scan(pg, on=night)["auto_merged"] == 1
    assert {_event(pg, c)["canonical_event_id"] is not None
            for c in (festival_ids[1], other)} == {True, False}


# --- the column itself --------------------------------------------------------

def test_the_column_only_holds_a_period(pg, running):
    event_id = running["row"]["event_id"]
    for bad in ("event_date", "event_date - 1", "event_date + 32"):
        with pytest.raises(psycopg.errors.CheckViolation):
            with pg.transaction():
                with pg.cursor() as cur:
                    cur.execute(f"UPDATE events SET end_date = {bad} WHERE event_id = %s",
                                (event_id,))


def test_a_corrected_date_past_the_end_drops_the_end():
    first = date(2026, 10, 21)
    assert normalization._end_date({"end_date": "2026-10-29"}, first) == date(2026, 10, 29)
    for value in ("2026-10-21", "2026-10-20", "2026-12-01", None, "x"):
        assert normalization._end_date({"end_date": value}, first) is None


def test_a_festival_is_named_as_one_whatever_its_title_says():
    kind = event_terms.classify_kind(
        "부산 밀롱가 마라톤",
        [{"term": "밀롱가", "normalized_term": "밀롱가", "enabled": True,
          "formats": ["MILONGA"]}],
        event_type="FESTIVAL")
    assert kind["display"] == "페스티벌" and kind["uncertain"] is False


def test_two_festivals_on_one_day_whose_places_differ_are_a_question(
        pg, store, run_normalization, unique, venue, today):
    """KOREA SPECIAL TANGO WEEK: TangoNOW's place `포항 posTango · 서울 OCHO`
    resolves to nothing and Miltang's names the room. Not a merge - a pair
    for a person."""
    day = today + timedelta(days=21)
    [left] = _ingest(store, _id(unique, 12), title=f"KOREA SPECIAL TANGO WEEK {unique}",
                     body=f"{_kr(day)} 장소: 포항 어딘가 {unique} · 서울 어딘가 주최: x",
                     period={"start": day.isoformat()})
    [right, *_] = _ingest(store, _id(unique, 13), title=f"KOREA SPECIAL TANGO WEEK (포항) {unique}",
                          body=f"{_kr(day)} 장소: {venue['name']} 주최: x",
                          period={"start": day.isoformat(),
                                  "end": (day + timedelta(days=3)).isoformat()})
    run_normalization()
    found = duplicates.scan(pg, on=day)
    assert found["auto_merged"] == 0 and found["flagged_for_review"] == 1
    a, b = _event(pg, left), _event(pg, right)
    with pg.cursor() as cur:
        cur.execute("SELECT rule, state FROM event_duplicate_pairs WHERE event_id = %s "
                    "AND other_event_id = %s",
                    tuple(sorted((a["event_id"], b["event_id"]))))
        assert cur.fetchall() == [(duplicates.RULE_SAME_DATE_FESTIVAL_PLACE_DIFFERS, "OPEN")]
    assert a["canonical_event_id"] is None and b["canonical_event_id"] is None
