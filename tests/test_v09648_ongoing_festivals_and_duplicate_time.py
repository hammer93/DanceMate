"""v0.96.48: a festival that is on is not over, and a past pair is not a closed one.

Part A. Miltang's `parse_detail(today=)` dropped a notice whose first day had
gone, even when its own period said it ran on: BUSAN TANGO FESTIVAL
(2026-10-21 ~ 2026-10-29, `/notices/12`) left discovery at Seoul midnight on
its second day, and with it any edit its organiser made while it ran (the
notice is `discovery_synthesized`, which only a re-collection refreshes). The
cutoff now asks the record's last day when the v0.96.41 festival judgement
carries a stated end, and its first day otherwise.

Part B. The Duplicates queue gains a timing - on now, upcoming, past, end
unknown - as a filter beside the lifecycle one, and every pair is ordered by
it. Timing never changes what a pair may be answered with.

Part C. A valid preview token proves who is answering, not that two posts are
one event. A pair no rule proposes any more, whose posts name different
places, is refused a merge (`PLACE_CONFLICT`); every assessed pair says what
its evidence supports (`merge_readiness`) and, when STALE, what moved.

The Miltang fixtures are the live pages captured 2026-10-19
(`tests/fixture_v09641_festivals.py`); dates that must move with the clock are
shifted copies of them. Everything date-dependent pins its Seoul day.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, timedelta

import pytest

from runtime import decision_contract as DC
from runtime import duplicates, events_api, miltang_discovery
from tests.fixture_v09641_festivals import MILTANG_NOTICES
from tests.test_miltang_discovery import _Resp
from tests.test_v09639_evidence_and_listing import (  # noqa: F401 - fixtures
    _event, _id, run_normalization, settings, store, venue)
from tests.test_v09640_duplicate_revert import (  # noqa: F401 - fixtures
    _verdict_id, console, two_clocks)
from tests.test_v09641_event_period import _ingest, _kr
from tests.test_v09641_festival_collectors import _notice_page

BUSAN = "https://miltang.com/notices/12"
MASAN = "https://miltang.com/notices/14"
STW = "https://miltang.com/notices/15"
KSTW_HONGDAE = "https://miltang.com/notices/19"
KSTW_POHANG = "https://miltang.com/notices/20"


def _parse(url: str, today: date | None, notice: dict | None = None) -> dict | None:
    return miltang_discovery.parse_detail(_notice_page(notice or MILTANG_NOTICES[url]), url,
                                          today=today)


def _shifted(url: str, first: date, last: date | None, *, place: str | None = None) -> dict:
    """The captured notice with its own period moved to ``first`` ~ ``last``."""
    notice = copy.deepcopy(MILTANG_NOTICES[url])
    notice["ld"]["startDate"] = first.isoformat()
    if last is None:
        notice["ld"].pop("endDate", None)
        notice["date_row"] = f"{first:%Y. %m. %d}"
    else:
        notice["ld"]["endDate"] = last.isoformat()
        notice["date_row"] = f"{first:%Y. %m. %d} ~ {last:%Y. %m. %d}"
    if place:
        notice["ld"]["location"]["name"] = place
    return notice


# --- Part A: the collector's cutoff ------------------------------------------------

@pytest.mark.parametrize("today,kept", [
    (date(2026, 10, 20), True),    # upcoming
    (date(2026, 10, 21), True),    # first day
    (date(2026, 10, 22), True),    # on: the day it used to vanish
    (date(2026, 10, 28), True),
    (date(2026, 10, 29), True),    # last day, inclusive
    (date(2026, 10, 30), False),   # over
])
def test_busan_tango_festival_is_collected_on_every_day_it_is_on(today, kept):
    record = _parse(BUSAN, today)
    assert (record is not None) == kept
    if kept:
        assert record["event_period"] == {"start": "2026-10-21", "end": "2026-10-29"}
        assert record["source_event_format"] == "FESTIVAL"


def test_a_running_festival_is_the_same_record_whatever_the_day():
    """Re-collecting it mid-run stores nothing new and asks for no re-extraction:
    the record does not depend on the day it was read."""
    baseline = _parse(BUSAN, None)
    for day in (date(2026, 10, 20), date(2026, 10, 22), date(2026, 10, 29)):
        assert _parse(BUSAN, day) == baseline


@pytest.mark.parametrize("url,first,last", [
    (MASAN, "2026-10-31", "2026-11-01"),
    (STW, "2026-11-11", "2026-11-16"),
    (KSTW_POHANG, "2026-11-18", "2026-11-21"),
    (KSTW_HONGDAE, "2026-11-21", "2026-11-24"),
])
def test_the_captured_festivals_keep_their_own_period_and_end_on_its_last_day(url, first,
                                                                             last):
    first_day, last_day = date.fromisoformat(first), date.fromisoformat(last)
    for day in (first_day - timedelta(days=1), first_day, first_day + timedelta(days=1),
                last_day):
        record = _parse(url, day)
        assert record is not None, day
        assert record["event_period"] == {"start": first, "end": last}
    assert _parse(url, last_day + timedelta(days=1)) is None


@pytest.mark.parametrize("url,on", [
    # A workshop tour and a seminar & show state periods too; neither is a
    # festival, so nothing is carried and the first-day cutoff stands.
    ("https://miltang.com/notices/10", date(2026, 10, 15)),
    ("https://miltang.com/notices/16", date(2026, 10, 23)),
])
def test_a_period_on_a_record_that_is_not_a_festival_recovers_nothing(url, on):
    assert "event_period" not in _parse(url, None)
    assert _parse(url, on) is None


def test_a_festival_past_its_last_day_stays_out():
    assert _parse("https://miltang.com/notices/4", date(2026, 10, 22)) is None


def test_a_festival_with_no_stated_end_is_given_none():
    first = date(2026, 10, 21)
    notice = _shifted(BUSAN, first, None)
    on_its_day = _parse(BUSAN, first, notice)
    assert on_its_day["event_period"] == {"start": "2026-10-21"}
    assert _parse(BUSAN, first + timedelta(days=1), notice) is None, \
        "no length is assumed for a festival that states none"


def test_a_single_day_record_keeps_the_existing_cutoff():
    record = copy.deepcopy(MILTANG_NOTICES[BUSAN])
    record["ld"]["name"] = "Friday Milonga"          # not a festival name: no period
    assert _parse(BUSAN, date(2026, 10, 21), record) is not None
    assert _parse(BUSAN, date(2026, 10, 22), record) is None


def test_no_start_time_is_invented_for_a_running_festival():
    record = _parse(BUSAN, date(2026, 10, 22))
    assert "시간:" not in record["body"]
    assert record["body"].startswith("2026년 10월 21일 ")


def test_discovery_hands_on_a_running_festival_and_drops_a_finished_one(monkeypatch):
    monkeypatch.setattr(miltang_discovery.acquisition, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(miltang_discovery, "_seoul_today", lambda: date(2026, 10, 22))
    pages = {u: _notice_page(MILTANG_NOTICES[u]) for u in
             (BUSAN, MASAN, "https://miltang.com/notices/4", "https://miltang.com/notices/11")}

    def opener(request, timeout=None):
        if request.full_url in pages:
            return _Resp(pages[request.full_url])
        return _Resp("<html><body>" + "".join(
            f'<a href="/notices/{u.rsplit("/", 1)[1]}">x</a>' for u in pages) + "</body></html>")

    posts = miltang_discovery.discover("https://miltang.com/notices", source_id="SRC-W-005",
                                       opener=opener)
    assert {p["source_url"] for p in posts} == {BUSAN, MASAN}


# --- Part A, end to end: collector -> engine -> normalization -> search ------------

def test_a_running_festival_collected_today_is_found_today(pg, store, run_normalization, unique,
                                                           venue):
    today = events_api.today()
    first, last = today - timedelta(days=1), today + timedelta(days=7)
    notice = _shifted(BUSAN, first, last, place=venue["name"])
    record = _parse(BUSAN, today, notice)
    assert record is not None, "began yesterday, on today: still collected"
    [cid] = _ingest(store, _id(unique, 1), title=f"{record['title']} {unique}",
                    body=record["body"], period=record["event_period"])
    run_normalization()
    row = _event(pg, cid)
    assert (row["event_type"], row["event_date"], row["end_date"], row["start_time"]) == (
        "FESTIVAL", first, last, None)
    for query in ({"when": "today"}, {"when": "tomorrow"}, {"when": "upcoming"}, {},
                  {"date_from": today, "date_to": today + timedelta(days=7)}):
        found = events_api.search(pg, limit=events_api.MAX_LIMIT, **query)["events"]
        assert row["event_id"] in {e["id"] for e in found}, query
    gone = events_api.search(pg, on=last + timedelta(days=1), limit=events_api.MAX_LIMIT)
    assert row["event_id"] not in {e["id"] for e in gone["events"]}


@pytest.fixture
def festival_and_nights(pg, store, run_normalization, unique, venue):
    """A festival that began yesterday, a night of it last night, one to come."""
    today = events_api.today()
    first, last = today - timedelta(days=1), today + timedelta(days=5)
    [festival] = _ingest(store, _id(unique, 2), title=f"Busan Tango Festival {unique}",
                         body=f"{_kr(first)} 장소: {venue['name']} 주최: x",
                         period={"start": first.isoformat(), "end": last.isoformat()})
    past_night = store.add(_id(unique, 3), name=f"Welcome Milonga {unique}",
                           day=first.isoformat(), start="21:00", end="02:00",
                           venue=venue["name"])
    next_night = store.add(_id(unique, 4), name=f"Gala Milonga {unique}",
                           day=(today + timedelta(days=2)).isoformat(), start="21:00",
                           end="02:00", venue=venue["name"])
    run_normalization()
    duplicates.scan(pg, on=first)
    duplicates.scan(pg, on=today + timedelta(days=2))
    return {"today": today, "first": first, "last": last, "festival": _event(pg, festival),
            "past": _event(pg, past_night), "next": _event(pg, next_night)}


def test_a_running_festivals_nights_keep_their_own_date_and_time(pg, festival_and_nights):
    case = festival_and_nights
    festival, past, upcoming = case["festival"], case["past"], case["next"]
    assert (festival["event_date"], festival["end_date"]) == (case["first"], case["last"])
    assert (upcoming["event_date"], str(upcoming["start_time"])[:5], upcoming["end_date"]) == (
        case["today"] + timedelta(days=2), "21:00", None), "the festival's end is not copied"
    assert past["end_date"] is None
    listed = {e["id"] for e in events_api.search(pg, limit=events_api.MAX_LIMIT)["events"]}
    assert festival["event_id"] in listed and upcoming["event_id"] in listed
    assert past["event_id"] not in listed, "last night's milonga is not upcoming"


def test_a_festival_is_never_merged_with_a_night_of_it(pg, festival_and_nights):
    case = festival_and_nights
    festival, past = case["festival"], case["past"]
    for event in (festival, past):
        assert _event_row(pg, event["event_id"])["canonical_event_id"] is None
    assert duplicates.classify(festival, past) is None
    rows = duplicates._members(pg, [festival["event_id"], past["event_id"]])
    pair = {"pair_id": 0, "event_id": min(rows), "other_event_id": max(rows),
            "rule": duplicates.RULE_VENUE_TIME_DIFFERS, "state": duplicates.OPEN}
    refusals, _, _ = duplicates.resolve_blockers(pair, rows, decision=duplicates.DUPLICATE)
    assert duplicates.REASON_FESTIVAL_PROGRAMME in [r for r, _ in refusals]


def _event_row(pg, event_id):
    with pg.cursor() as cur:
        cur.execute("SELECT canonical_event_id, listing_state FROM events WHERE event_id = %s",
                    (event_id,))
        canonical, listing = cur.fetchone()
    return {"canonical_event_id": canonical, "listing_state": listing}


# --- Part B: timing, in memory ------------------------------------------------------

TODAY = date(2026, 10, 22)


def _ev(event_id, day=TODAY, **kw):
    row = {"event_id": event_id, "event_date": day, "end_date": None, "period_end": None,
           # v0.96.52: one night's name, two independent sources - the positive
           # evidence a merge now needs (`duplicates.merge_evidence`).
           "event_name": "Milonga Luz", "source_id": event_id,
           "start_time": "20:00", "venue_id": 7,
           "venue_text": "Hall", "region_id": 1, "identity_key": f"k{event_id}",
           "series_key": None, "event_type": "MILONGA", "canonical_event_id": None,
           "duplicate_decided_by": None, "listing_state": "LISTED", "review_state": "PENDING",
           "provenance": "LIVE", "source_item_id": event_id * 10,
           "primary_source_item_id": None, "primary_source_decided_by": None,
           "folded_count": 0}
    row.update(kw)
    return row


def _pair(pair_id=1, low=10, high=20, state="OPEN", matched=("event_date", "venue")):
    return {"pair_id": pair_id, "event_id": low, "other_event_id": high,
            "rule": duplicates.RULE_VENUE_TIME_DIFFERS, "state": state,
            "matched": list(matched), "resolved_by": None if state == "OPEN" else "tester",
            "resolved_at": None, "created_at": None}


def _assess(rows, pair=None, pairs=(), today=TODAY):
    pair = pair or _pair()
    index = {tuple(sorted((p["event_id"], p["other_event_id"]))): p for p in (pair, *pairs)}
    return duplicates.assess_pair(pair, {r["event_id"]: r for r in rows}, index, today)


@pytest.mark.parametrize("today,expected", [
    (date(2026, 10, 20), duplicates.TIME_UPCOMING),
    (date(2026, 10, 21), duplicates.TIME_ONGOING),
    (date(2026, 10, 22), duplicates.TIME_ONGOING),
    (date(2026, 10, 28), duplicates.TIME_ONGOING),
    (date(2026, 10, 29), duplicates.TIME_ONGOING),
    (date(2026, 10, 30), duplicates.TIME_PAST),
])
def test_a_stated_period_is_on_through_its_last_day(today, expected):
    festival = _ev(1, date(2026, 10, 21), event_type="FESTIVAL", end_date=date(2026, 10, 29),
                   period_end=date(2026, 10, 29))
    assert duplicates.event_timing(festival, {1: festival}, today) == expected


def test_a_single_day_event_is_past_the_day_after():
    night = _ev(1, date(2026, 10, 21))
    assert duplicates.event_timing(night, {1: night}, date(2026, 10, 21)) == \
        duplicates.TIME_ONGOING
    assert duplicates.event_timing(night, {1: night}, date(2026, 10, 22)) == duplicates.TIME_PAST


def test_a_started_festival_with_no_stated_end_is_not_called_past():
    festival = _ev(1, date(2026, 10, 12), event_type="FESTIVAL")
    assert duplicates.event_timing(festival, {1: festival}, TODAY) == duplicates.TIME_UNKNOWN
    assert duplicates.event_timing(festival, {1: festival}, date(2026, 10, 12)) == \
        duplicates.TIME_ONGOING, "its first day is a day it is certainly on"
    assert duplicates.event_timing(festival, {1: festival}, date(2026, 10, 11)) == \
        duplicates.TIME_UPCOMING


def test_a_fold_shares_its_groups_period():
    """TangoNOW dates BUSAN by its first day; the Miltang row it folds into
    carries the period."""
    root = _ev(30, date(2026, 10, 21), event_type="FESTIVAL", end_date=date(2026, 10, 29),
               period_end=date(2026, 10, 29), folded_count=1)
    fold = _ev(20, date(2026, 10, 21), event_type="FESTIVAL", canonical_event_id=30,
               duplicate_decided_by="AUTO", listing_state="HIDDEN")
    rows = {30: root, 20: fold}
    assert duplicates.event_timing(fold, rows, TODAY) == duplicates.TIME_ONGOING


@pytest.mark.parametrize("left,right,expected", [
    (date(2026, 10, 1), date(2026, 10, 1), duplicates.TIME_PAST),
    (date(2026, 10, 1), date(2026, 10, 30), duplicates.TIME_UPCOMING),
    (date(2026, 10, 22), date(2026, 10, 30), duplicates.TIME_ONGOING),
])
def test_a_pair_is_past_only_when_both_events_are(left, right, expected):
    found = _assess([_ev(10, left), _ev(20, right, start_time="21:00")])
    assert found["timing"] == expected


def test_a_pair_with_a_festival_of_unknown_end_is_not_historical():
    found = _assess([_ev(10, date(2026, 10, 12), event_type="FESTIVAL"),
                     _ev(20, date(2026, 10, 12), event_type="FESTIVAL", venue_id=8)])
    assert found["timing"] == duplicates.TIME_UNKNOWN


def test_a_pair_across_a_running_period_is_ongoing():
    found = _assess([
        _ev(10, date(2026, 10, 21), event_type="FESTIVAL", end_date=date(2026, 10, 29),
            period_end=date(2026, 10, 29)),
        _ev(20, date(2026, 10, 21), event_type="FESTIVAL", venue_id=8)])
    assert found["timing"] == duplicates.TIME_ONGOING


def test_timing_changes_nothing_a_pair_may_be_answered_with():
    rows = [_ev(10, date(2026, 9, 1)), _ev(20, date(2026, 9, 1), start_time="21:00")]
    past = _assess(rows)
    soon = _assess([dict(r, event_date=date(2026, 11, 1)) for r in rows])
    assert (past["timing"], soon["timing"]) == (duplicates.TIME_PAST, duplicates.TIME_UPCOMING)
    assert past["status"] == soon["status"] == duplicates.QUEUE_ACTIONABLE
    assert past["available"] == soon["available"] == ["MERGE:10", "MERGE:20", "KEEP_SEPARATE"]


def test_a_resolved_past_pair_is_not_actionable():
    found = _assess([_ev(10, date(2026, 9, 1)), _ev(20, date(2026, 9, 1), start_time="21:00")],
                    pair=_pair(state=duplicates.DISTINCT))
    assert found["status"] == duplicates.QUEUE_PERSON and found["available"] == []


def test_a_superseded_pair_keeps_its_root_pair_link_whatever_its_timing():
    rows = [_ev(10, date(2026, 9, 1)),
            _ev(20, date(2026, 9, 1), start_time="21:00", canonical_event_id=30,
                duplicate_decided_by="AUTO", listing_state="HIDDEN"),
            _ev(30, date(2026, 9, 1), start_time="21:00", folded_count=1)]
    found = _assess(rows, pairs=[_pair(pair_id=2, low=10, high=30)])
    assert found["timing"] == duplicates.TIME_PAST
    assert found["status"] == duplicates.QUEUE_SUPERSEDED
    assert (found["successor_pair_id"], found["available"]) == (2, [])


def test_the_queue_orders_on_now_then_soon_before_the_past():
    def item(status, timing):
        return {"status": status, "timing": timing}
    order = [item(duplicates.QUEUE_ACTIONABLE, duplicates.TIME_ONGOING),
             item(duplicates.QUEUE_ACTIONABLE, duplicates.TIME_UPCOMING),
             item(duplicates.QUEUE_ACTIONABLE, duplicates.TIME_UNKNOWN),
             item(duplicates.QUEUE_STALE, duplicates.TIME_UPCOMING),
             item(duplicates.QUEUE_ACTIONABLE, duplicates.TIME_PAST),
             item(duplicates.QUEUE_STALE, duplicates.TIME_PAST),
             item(duplicates.QUEUE_SUPERSEDED, duplicates.TIME_ONGOING)]
    ranks = [duplicates.queue_priority(i) for i in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)


# --- Part C: STALE readiness, in memory --------------------------------------------

def test_stale_with_one_place_missing_is_insufficient_and_offers_no_merge():
    """v0.96.48 kept the merge open on such a pair ("insufficient but
    answerable"); v0.96.52 offers only what positive evidence supports - the
    place is now unknown and the starts differ, so only Different events."""
    found = _assess([_ev(10), _ev(20, start_time="21:00", venue_id=None, venue_text=None)])
    assert (found["status"], found["primary_reason"]) == (duplicates.QUEUE_STALE,
                                                         duplicates.REASON_NO_CURRENT_MATCH)
    assert found["merge_readiness"] == duplicates.EVIDENCE_INSUFFICIENT
    assert found["available"] == ["KEEP_SEPARATE"]
    assert found["readiness"] == duplicates.READINESS_STALE
    assert found["stale_causes"] == [duplicates.STALE_VENUE_CHANGED]


def test_stale_because_the_rules_would_merge_is_supported():
    found = _assess([_ev(10), _ev(20)])        # same resolved place and clock now
    assert (found["status"], found["primary_reason"]) == (duplicates.QUEUE_STALE,
                                                         duplicates.REASON_RULES_WOULD_MERGE)
    assert found["merge_readiness"] == duplicates.EVIDENCE_SUPPORTS
    assert found["stale_causes"] == [duplicates.STALE_NOW_AUTOMATIC]


def test_stale_across_dates_contradicts_a_merge():
    found = _assess([_ev(10, date(2026, 9, 12)), _ev(20, date(2026, 9, 11), start_time="22:00",
                                                     venue_id=None, venue_text=None)])
    assert found["merge_readiness"] == duplicates.EVIDENCE_CONTRADICTS
    assert found["available"] == [], "no answer is recorded across dates (v0.96.47)"
    assert duplicates.STALE_DATE_CHANGED in found["stale_causes"]


def test_stale_across_regions_contradicts_a_merge():
    found = _assess([_ev(10), _ev(20, start_time="21:00", venue_id=None, venue_text=None,
                                  region_id=2)])
    assert found["merge_readiness"] == duplicates.EVIDENCE_CONTRADICTS
    assert found["available"] == ["KEEP_SEPARATE"]
    assert duplicates.STALE_REGION_CHANGED in found["stale_causes"]


def test_stale_after_each_post_got_its_own_place_refuses_the_merge():
    """Production's 24: re-extraction gave each post its own venue; nothing but
    the date is shared."""
    found = _assess([_ev(10, venue_id=None, venue_text="분당 실루엣", start_time="04:30"),
                     _ev(20, venue_id=None, venue_text="구)엘마르", start_time="16:00")])
    assert found["status"] == duplicates.QUEUE_STALE
    assert found["merge_readiness"] == duplicates.EVIDENCE_CONTRADICTS
    assert found["available"] == ["KEEP_SEPARATE"]
    merge = [a for a in found["answers"] if a["decision"] == duplicates.DUPLICATE]
    assert all(a["reasons"] == [duplicates.REASON_PLACE_CONFLICT] for a in merge)
    assert found["stale_causes"] == [duplicates.STALE_VENUE_CHANGED]


def test_the_protected_distinct_pair_cannot_be_merged():
    """1603334 / 1603338: one Saturday 21:00, two venues, two parties."""
    found = _assess([_ev(10, venue_id=None, venue_text="광주 J 라틴", start_time="21:00",
                         region_id=None),
                     _ev(20, venue_id=None, venue_text="단춤", start_time="21:00",
                         region_id=None)],
                    pair=_pair(matched=("event_date", "start_time", "venue_text")))
    assert found["merge_readiness"] == duplicates.EVIDENCE_CONTRADICTS
    assert found["available"] == ["KEEP_SEPARATE"]


def test_stale_after_a_type_change_refuses_the_merge():
    found = _assess([_ev(10), _ev(20, start_time="21:00", event_type="FESTIVAL")])
    assert found["merge_readiness"] == duplicates.EVIDENCE_CONTRADICTS
    assert duplicates.STALE_EVENT_TYPE_CHANGED in found["stale_causes"]
    merge = [a for a in found["answers"] if a["decision"] == duplicates.DUPLICATE]
    assert all(duplicates.REASON_FESTIVAL_PROGRAMME in a["reasons"] for a in merge)


def test_a_rule_that_still_asks_across_venues_is_untouched():
    """Same series, same clock, another room: the rules still ask (the pair
    stays ACTIONABLE, Different events answerable). v0.96.52: two different
    resolved venues are no positive evidence of one night, so the merge waits
    for the sources."""
    found = _assess([_ev(10, series_key="s1"), _ev(20, series_key="s1", venue_id=8,
                                                   venue_text="Other hall")])
    assert found["status"] == duplicates.QUEUE_ACTIONABLE
    assert found["merge_readiness"] == duplicates.EVIDENCE_INSUFFICIENT
    assert found["readiness"] == duplicates.READINESS_NEEDS_EVIDENCE
    assert found["available"] == ["KEEP_SEPARATE"]
    assert "two different resolved venues" in found["evidence_missing"]


# --- Part C, the real route ---------------------------------------------------------

def _item(pg, pair_id):
    return next(a for a in duplicates.queue(pg) if a["pair_id"] == pair_id)


def test_an_insufficient_stale_pair_answers_through_the_signed_preview(pg, two_clocks):
    case = two_clocks
    pair_id, keep = case["pair"]["pair_id"], case["a"]["event_id"]
    old = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                     canonical_event_id=keep, reviewer="tester")["token"]
    with pg.cursor() as cur:      # re-extracted: the other post no longer says where
        cur.execute("UPDATE events SET venue_id = NULL, venue_text = NULL, "
                    "  venue_status = 'ABSENT' WHERE event_id = %s", (case["b"]["event_id"],))
    item = _item(pg, pair_id)
    assert item["status"] == duplicates.QUEUE_STALE
    assert item["merge_readiness"] == duplicates.EVIDENCE_INSUFFICIENT
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=old, reviewer="tester")
    # v0.96.52: what refuses the old merge token now is the recomputed preview
    # itself - the pair no longer carries same-event evidence.
    assert refused.value.code == DC.DECISION_REFUSED
    assert _verdict_id(pg, case["b"]["event_id"]) is None
    # v0.96.52: an insufficient pair offers no merge at all - the preview
    # issues no token - and Different events is answered through the signed
    # preview, whose basis stays mandatory.
    fresh = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=keep, reviewer="tester")
    assert fresh["token"] is None
    assert fresh["reasons"] == [duplicates.REASON_INSUFFICIENT_SAME_EVENT_EVIDENCE]
    separate = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                          reviewer="tester")
    assert separate["token"] and separate["reasons"] == []
    with pytest.raises(DC.DecisionRefused) as refused:     # the basis stays mandatory
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                   token=separate["token"], reviewer="someone else")
    assert refused.value.code == DC.INVALID_PREVIEW_TOKEN


def test_a_place_conflict_is_refused_the_same_way_by_queue_preview_and_confirm(pg, two_clocks):
    case = two_clocks
    pair_id, keep = case["pair"]["pair_id"], case["a"]["event_id"]
    token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=keep, reviewer="tester")["token"]
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET venue_id = NULL, venue_text = 'Somewhere else', "
                    "  venue_status = 'UNRESOLVED' WHERE event_id = %s",
                    (case["b"]["event_id"],))
    item = _item(pg, pair_id)
    assert item["merge_readiness"] == duplicates.EVIDENCE_CONTRADICTS
    assert item["available"] == ["KEEP_SEPARATE"]
    preview = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                         canonical_event_id=keep, reviewer="tester")
    assert preview["token"] is None and preview["reasons"] == [duplicates.REASON_PLACE_CONFLICT]
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=keep, token=token, reviewer="tester")
    assert refused.value.code == DC.DECISION_REFUSED
    separate = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                          reviewer="tester")
    assert separate["token"], "Different events stays answerable"
    assert duplicates.queue_integrity(pg, duplicates.queue(pg))["UNSAFE_STALE_MERGE_READY"] == 0


def _hashes(pg):
    out = {}
    with pg.cursor() as cur:
        for table in ("event_duplicate_pairs", "event_duplicate_decisions", "events",
                      "human_review_actions", "venues", "venue_aliases"):
            cur.execute(f"SELECT * FROM {table} ORDER BY 1")
            out[table] = hashlib.sha256(json.dumps(cur.fetchall(), default=str)
                                        .encode()).hexdigest()
    return out


def test_reading_the_queue_and_its_pages_writes_nothing(pg, two_clocks, console):
    before = _hashes(pg)
    duplicates.queue_integrity(pg, duplicates.queue(pg))
    for path in ("/admin/duplicates", "/admin/duplicates?view=all&time=past",
                 "/admin/duplicates?view=stale&time=upcoming",
                 f"/admin/duplicates/{two_clocks['pair']['pair_id']}",
                 "/api/admin/duplicates/queue?time=ONGOING"):
        assert console.get(path).status_code == 200, path
    assert _hashes(pg) == before


def test_a_past_pair_is_never_answered_by_the_scan(pg, two_clocks):
    case = two_clocks
    duplicates.scan(pg, on=case["day"])
    item = _item(pg, case["pair"]["pair_id"])
    assert item["state"] == duplicates.OPEN
    assert _verdict_id(pg, case["a"]["event_id"]) is None


def test_the_page_combines_the_lifecycle_and_time_filters(pg, two_clocks, console):
    pair_id = two_clocks["pair"]["pair_id"]
    timing = _item(pg, pair_id)["timing"]
    key = {duplicates.TIME_ONGOING: "ongoing", duplicates.TIME_UPCOMING: "upcoming",
           duplicates.TIME_PAST: "past", duplicates.TIME_UNKNOWN: "unknown"}[timing]
    other = "past" if key != "past" else "upcoming"
    here = console.get(f"/admin/duplicates?view=actionable&time={key}").text
    there = console.get(f"/admin/duplicates?view=actionable&time={other}").text
    assert f"/admin/duplicates/{pair_id}\"" in here
    assert f"/admin/duplicates/{pair_id}\"" not in there
    assert "Lifecycle:" in here and "Time:" in here
    api = console.get(f"/api/admin/duplicates/queue?time={timing}").json()
    assert pair_id in {p["pair_id"] for p in api["pairs"]}
    assert all(p["timing"] == timing for p in api["pairs"])
    assert "token" not in json.dumps(api)


def test_the_queue_gates_hold(pg, two_clocks):
    gates = duplicates.queue_integrity(pg, duplicates.queue(pg))
    assert gates and all(v == 0 for v in gates.values()), gates
