"""Duplicate Resolution: rules only, conservative merges, human decisions final."""

from __future__ import annotations

from datetime import date, time

import pytest

from runtime import duplicates, normalization


def _event(event_id, **overrides):
    base = {
        "event_id": event_id,
        "event_date": date(2026, 9, 5),
        "start_time": time(19, 30),
        "venue_id": 7,
        "venue_text": "아미고스튜디오",
        "venue_status": "RESOLVED",
        "end_time": time(23, 30),
        "fee": 13000,
        "engine_status": "POSSIBLE",
        "review_state": "PENDING",
        "series_key": "venue:7|5|밀롱가",
        "duplicate_decided_by": None,
    }
    base.update(overrides)
    return base


# --- the rules --------------------------------------------------------------

def test_same_date_venue_and_time_is_the_only_automatic_merge():
    finding = duplicates.classify(_event(1), _event(2))
    assert finding["rule"] == duplicates.RULE_SAME_DATE_VENUE_TIME
    assert finding["auto"] is True


def test_the_same_venue_at_a_different_time_goes_to_a_person():
    """Two milongas can share a studio on one night. Merging them would delete
    one of them from the answer."""
    finding = duplicates.classify(_event(1), _event(2, start_time=time(22, 0)))
    assert finding["rule"] == duplicates.RULE_VENUE_TIME_DIFFERS
    assert finding["auto"] is False


def test_a_missing_time_is_never_treated_as_a_match():
    finding = duplicates.classify(_event(1), _event(2, start_time=None))
    assert finding["auto"] is False


def test_two_dates_are_never_duplicates_however_alike():
    """A weekly milonga produces near-identical rows every week. They are
    different nights and a dancer needs both."""
    assert duplicates.classify(_event(1), _event(2, event_date=date(2026, 9, 12))) is None


def test_two_unresolved_venue_strings_only_match_when_identical():
    unknown = {"venue_id": None, "venue_status": "UNRESOLVED"}
    same = duplicates.classify(
        _event(1, venue_text="미등록 스튜디오", **unknown),
        _event(2, venue_text="미등록 스튜디오", **unknown),
    )
    assert same["auto"] is True

    different = duplicates.classify(
        _event(1, venue_text="스튜디오 가", **unknown),
        _event(2, venue_text="스튜디오 나", **unknown),
    )
    # Same date, same time, same series -- suspicious, not settled.
    assert different is not None and different["auto"] is False


def test_events_with_no_place_at_all_are_not_compared_by_place():
    nowhere = {"venue_id": None, "venue_text": None, "venue_status": "ABSENT"}
    finding = duplicates.classify(_event(1, **nowhere), _event(2, **nowhere))
    assert finding is not None
    assert finding["rule"] == duplicates.RULE_TIME_NAME_VENUE_DIFFERS
    assert finding["auto"] is False


def test_unrelated_events_on_one_night_are_not_a_pair():
    other = _event(2, venue_id=99, venue_text="다른 곳", start_time=time(21, 0),
                   series_key="venue:99|5|다른밀롱가")
    assert duplicates.classify(_event(1), other) is None


# --- which row survives -----------------------------------------------------

def test_the_more_complete_event_becomes_canonical():
    poor = _event(1, venue_id=None, venue_status="UNRESOLVED", fee=None, end_time=None)
    rich = _event(2)
    assert duplicates.completeness(rich) > duplicates.completeness(poor)


def test_a_reviewed_event_outranks_an_unreviewed_one():
    reviewed = _event(1, review_state="CONFIRMED")
    plain = _event(2)
    assert duplicates.completeness(reviewed) > duplicates.completeness(plain)


def test_equally_complete_events_break_the_tie_on_the_oldest_id():
    """Deterministic: the same input must always produce the same canonical row."""
    canonical, duplicate = duplicates._canonical_of(_event(9), _event(4))
    assert canonical["event_id"] == 4
    assert duplicate["event_id"] == 9


# --- SQL --------------------------------------------------------------------

def _candidate(unique: str, suffix: str, **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/test/{unique}-{suffix}",
        "event_name": f"테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"스튜디오 {unique}",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
    }
    base.update(overrides)
    return base


def test_three_posts_of_one_milonga_become_one_listed_event(pg, unique):
    stored = [
        normalization.normalize_candidate(pg, _candidate(unique, str(n)))
        for n in (1, 2, 3)
    ]
    result = duplicates.scan(pg, on=date(2026, 9, 5))
    assert result["auto_merged"] >= 2

    ids = [e["event_id"] for e in stored]
    remaining = [
        normalization.get(pg, event_id) for event_id in ids
    ]
    canonical = [e for e in remaining if e["canonical_event_id"] is None]
    assert len(canonical) == 1
    assert all(e["listing_state"] == "HIDDEN"
               for e in remaining if e["canonical_event_id"] is not None)


def test_a_merge_keeps_every_source(pg, unique):
    """Merging is only acceptable because nothing is lost by it."""
    stored = [
        normalization.normalize_candidate(pg, _candidate(unique, str(n)))
        for n in (1, 2)
    ]
    duplicates.scan(pg, on=date(2026, 9, 5))
    canonical = next(
        e for e in (normalization.get(pg, s["event_id"]) for s in stored)
        if e["canonical_event_id"] is None
    )
    sources = duplicates.sources_of(pg, canonical["event_id"])
    assert len(sources) == 2
    assert {s["source_url"] for s in sources} == {s["source_url"] for s in stored}
    assert sum(1 for s in sources if s["is_canonical"]) == 1


def test_an_ambiguous_pair_is_left_for_a_person(pg, unique):
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2", start_time="22:00"))
    duplicates.scan(pg, on=date(2026, 9, 5))

    # Asserted about these two events rather than the scan's totals: the same
    # database carries live events and a scheduler that scans them, so a global
    # counter says nothing about what happened here.
    for event in (first, second):
        assert normalization.get(pg, event["event_id"])["canonical_event_id"] is None

    pairs = [p for p in duplicates.open_pairs(pg)
             if p["venue_text"] == f"스튜디오 {unique}"]
    assert len(pairs) == 1
    assert pairs[0]["differs"] == ["start_time"]


def test_a_person_can_merge_a_pair_the_rules_would_not(pg, unique):
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    normalization.normalize_candidate(pg, _candidate(unique, "2", start_time="22:00"))
    duplicates.scan(pg, on=date(2026, 9, 5))
    pair = next(p for p in duplicates.open_pairs(pg)
                if p["venue_text"] == f"스튜디오 {unique}")

    outcome = duplicates.resolve_pair(
        pg, pair["pair_id"], decision=duplicates.DUPLICATE,
        canonical_event_id=first["event_id"], reviewer="tester",
    )
    assert outcome["canonical_event_id"] == first["event_id"]
    assert normalization.get(pg, first["event_id"])["canonical_event_id"] is None


def test_automation_never_overturns_a_human_decision(pg, unique):
    """A person said these two are different events. Re-running the scan must
    not merge them on the next tick."""
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2", start_time="22:00"))
    duplicates.scan(pg, on=date(2026, 9, 5))
    pair = next(p for p in duplicates.open_pairs(pg)
                if p["venue_text"] == f"스튜디오 {unique}")
    duplicates.resolve_pair(pg, pair["pair_id"], decision=duplicates.DISTINCT,
                            reviewer="tester")

    # Make them look identical to the rules -- exactly the case that would
    # otherwise auto-merge.
    normalization.normalize_candidate(pg, _candidate(unique, "2"))
    duplicates.scan(pg, on=date(2026, 9, 5))

    for event_id in (first["event_id"], second["event_id"]):
        event = normalization.get(pg, event_id)
        assert event["canonical_event_id"] is None
        assert event["duplicate_decided_by"] == duplicates.HUMAN


def test_every_verdict_is_recorded_with_who_made_it(pg, unique):
    normalization.normalize_candidate(pg, _candidate(unique, "1"))
    normalization.normalize_candidate(pg, _candidate(unique, "2"))
    duplicates.scan(pg, on=date(2026, 9, 5))
    with pg.cursor() as cur:
        cur.execute(
            "SELECT decided_by, rule FROM event_duplicate_decisions "
            "ORDER BY decision_id DESC LIMIT 1"
        )
        decided_by, rule = cur.fetchone()
    assert decided_by == duplicates.AUTO
    assert rule == duplicates.RULE_SAME_DATE_VENUE_TIME


def test_rerunning_the_scan_is_idempotent(pg, unique):
    stored = [normalization.normalize_candidate(pg, _candidate(unique, n)) for n in "12"]
    first = duplicates.scan(pg, on=date(2026, 9, 5))
    assert first["auto_merged"] >= 1
    merged = [normalization.get(pg, e["event_id"])["canonical_event_id"] for e in stored]
    assert sum(1 for m in merged if m is not None) == 1

    # A second pass has nothing left to decide -- here or anywhere else on the
    # day, which is what makes the scheduler safe to run on a timer.
    assert duplicates.scan(pg, on=date(2026, 9, 5))["auto_merged"] == 0


def test_resolve_pair_rejects_an_unknown_decision(pg, unique):
    normalization.normalize_candidate(pg, _candidate(unique, "1"))
    normalization.normalize_candidate(pg, _candidate(unique, "2", start_time="22:00"))
    duplicates.scan(pg, on=date(2026, 9, 5))
    pair = next(p for p in duplicates.open_pairs(pg)
                if p["venue_text"] == f"스튜디오 {unique}")
    with pytest.raises(ValueError):
        duplicates.resolve_pair(pg, pair["pair_id"], decision="MAYBE")


def test_the_listed_count_is_what_a_user_would_be_shown(pg, unique):
    """Not every LISTED row: a fixture-derived event is listed in the table and
    served to nobody."""
    from runtime import events_api

    normalization.normalize_candidate(
        pg, _candidate(unique, "1", provenance=normalization.PROVENANCE_LIVE),
    )
    normalization.normalize_candidate(
        pg, _candidate(unique, "2", venue=f"다른 곳 {unique}", start_time="22:00",
                       provenance=normalization.PROVENANCE_UNKNOWN),
    )
    counted = duplicates.metrics(pg)["listed"]
    served = events_api.search(pg, date_from="2000-01-01", date_to="2100-01-01",
                               limit=events_api.MAX_LIMIT)["total"]
    assert counted == served
