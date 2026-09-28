"""v0.96.24, runtime side: what an Event looks like once a false poster venue
is gone, and how v0.96.23's fold rules read it.

The engine change is in ``engine/src/extractor._image_venue()``; these are the
consequences the runtime owns:

* a candidate with no venue normalises to ``venue_status = ABSENT``, not to a
  guessed place - "no venue" is what this project says when it does not know
  one, and it is the honest answer for the 61 Events that were showing a
  fee, a clock or OCR noise as their location;
* an Event with no place can neither be auto-merged nor flagged as a suspected
  duplicate, because v0.96.23 requires a place for both - so the two parties
  v0.96.23 separated stay separated, now for a stronger reason than an
  unresolved string nobody could check;
* a resolved venue is untouched, so every real cross-source duplicate still
  folds exactly as it did.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from runtime import duplicates, normalization
from conftest import register_venue

DAY = date(2026, 10, 3)


def _candidate(unique: str, suffix: str, **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://danceinfo.net/lessons/{unique}-{suffix}",
        "event_name": f"파티 {unique}-{suffix}",
        "event_type": "SOCIAL_WITH_CLASS",
        "event_date": DAY.isoformat(),
        "start_time": "21:00",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": None,
        "fee": 10000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    base.update(overrides)
    return base


def test_a_candidate_with_no_venue_says_absent_not_a_guess(pg, unique):
    """The Event keeps everything else it had; the location is simply not
    claimed. Nothing is invented to fill it."""
    stored = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    assert stored["venue_text"] is None
    assert stored["venue_id"] is None
    assert stored["venue_status"] == normalization.VENUE_ABSENT
    assert stored["start_time"] == time(21, 0)
    assert stored["fee"] == 10000
    assert stored["listing_state"] == "LISTED"


def test_two_parties_at_one_hour_with_no_place_are_neither_merged_nor_flagged(pg, unique):
    """The v0.96.23 target pair, as v0.96.24 leaves it. Both posters said
    "@ 스스 me1"; neither post said where it was. Two rows, no merge, and not
    even a question for a person - there is nothing about these two that looks
    like one event beyond the hour they share."""
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2"))

    duplicates.scan(pg, on=DAY)

    for stored in (first, second):
        event = normalization.get(pg, stored["event_id"])
        assert event["canonical_event_id"] is None
        assert event["listing_state"] == "LISTED"
    assert not [p for p in duplicates.open_pairs(pg)
                if p["event_id"] in (first["event_id"], second["event_id"])
                or p["other_event_id"] in (first["event_id"], second["event_id"])]


def test_the_false_venue_no_longer_makes_two_parties_look_alike(pg, unique):
    """The same pair as it was before this release: one unresolved string
    shared by both, which v0.96.23 already refused to merge but did record as
    an open question. With the string gone, the question goes too."""
    before = duplicates.classify(
        {"event_id": 1, "event_date": DAY, "start_time": time(21, 0),
         "venue_id": None, "venue_text": "스스 me1", "venue_status": "UNRESOLVED",
         "event_name": "A", "series_key": None, "duplicate_decided_by": None},
        {"event_id": 2, "event_date": DAY, "start_time": time(21, 0),
         "venue_id": None, "venue_text": "스스 me1", "venue_status": "UNRESOLVED",
         "event_name": "B", "series_key": None, "duplicate_decided_by": None},
    )
    assert before is not None and before["auto"] is False

    after = duplicates.classify(
        {"event_id": 1, "event_date": DAY, "start_time": time(21, 0),
         "venue_id": None, "venue_text": None, "venue_status": "ABSENT",
         "event_name": "A", "series_key": None, "duplicate_decided_by": None},
        {"event_id": 2, "event_date": DAY, "start_time": time(21, 0),
         "venue_id": None, "venue_text": None, "venue_status": "ABSENT",
         "event_name": "B", "series_key": None, "duplicate_decided_by": None},
    )
    assert after is None


def test_a_resolved_venue_duplicate_still_folds(pg, unique):
    """Nothing this release does reaches a real duplicate: those resolve their
    venue on both sides, which is the only thing v0.96.23 merges on."""
    register_venue(pg, f"스튜디오 {unique}")
    first = normalization.normalize_candidate(
        pg, _candidate(unique, "1", venue=f"스튜디오 {unique}"))
    second = normalization.normalize_candidate(
        pg, _candidate(unique, "2", venue=f"스튜디오 {unique}"))
    assert first["venue_status"] == "RESOLVED"

    duplicates.scan(pg, on=DAY)
    states = [normalization.get(pg, e["event_id"])["canonical_event_id"]
              for e in (first, second)]
    assert sum(1 for s in states if s is None) == 1
    assert sum(1 for s in states if s is not None) == 1


def test_an_event_that_loses_its_venue_keeps_its_id(pg, unique):
    """Re-extraction re-reads a one-candidate post into the same candidate_id
    (v0.96.0), so the Event a reader may have linked to survives losing a
    venue it should never have had."""
    register_venue(pg, f"스튜디오 {unique}")
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, "1", venue=f"스튜디오 {unique}"))
    assert stored["venue_id"] is not None

    again = normalization.normalize_candidate(pg, _candidate(unique, "1", venue=None))
    assert again["event_id"] == stored["event_id"]
    assert again["venue_id"] is None
    assert again["venue_status"] == normalization.VENUE_ABSENT


def test_a_region_read_off_the_venue_goes_with_it(pg, unique, seoul_id):
    """v0.96.24 accepts this: a region inferred from a venue we no longer claim
    is not a fact we still hold. Keeping a fabricated venue to keep its region
    would be the wrong trade - the region is only ever as good as the place it
    was read from."""
    from runtime import master_data

    venue = master_data.create_venue(pg, name=f"지역 스튜디오 {unique}", region_id=seoul_id)
    with_venue = normalization.normalize_candidate(
        pg, _candidate(unique, "1", venue=f"지역 스튜디오 {unique}"))
    assert with_venue["venue_id"] == venue["venue_id"]
    assert with_venue["region_id"] == seoul_id

    without = normalization.normalize_candidate(pg, _candidate(unique, "1", venue=None))
    assert without["region_id"] is None
