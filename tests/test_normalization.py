"""Event normalization: engine candidates become searchable event instances."""

from __future__ import annotations

from datetime import date, time

import pytest

from runtime import normalization, review


# --- keys -------------------------------------------------------------------

def test_name_key_strips_the_date_out_of_a_title():
    """The same weekly milonga is titled with a different date every week."""
    assert (normalization.name_key("💜9/5(토) THE PISTA MILONGA")
            == normalization.name_key("9/12(토) THE PISTA MILONGA"))
    assert (normalization.name_key("9월 12일 로라밀롱가 버블 버블")
            == normalization.name_key("로라밀롱가 버블 버블"))


def test_name_key_keeps_different_events_apart():
    assert normalization.name_key("더 피스타 밀롱가") != normalization.name_key("로라밀롱가")


def test_a_resolved_venue_compares_by_id_and_an_unresolved_one_by_text():
    """Two spellings of one studio are the same place once someone has said so.

    Two unrecognised strings are not: we have no grounds to call them equal.
    """
    assert normalization.venue_key(7, "PISTA") == normalization.venue_key(7, "피스타")
    assert normalization.venue_key(None, "PISTA") != normalization.venue_key(None, "피스타")
    assert normalization.venue_key(None, "  PISTA ") == normalization.venue_key(None, "pista")
    assert normalization.venue_key(None, None) is None


def test_identity_key_is_date_place_and_start_time():
    key = normalization.identity_key(date(2026, 9, 5), "venue:7", time(19, 30))
    assert key == "2026-09-05|venue:7|19:30"


def test_identity_key_records_what_is_missing_rather_than_omitting_it():
    """Two events that both lack a time must not collide with each other by
    accident of formatting."""
    assert normalization.identity_key(date(2026, 9, 5), None, None) == "2026-09-05|-|-"


def test_series_key_groups_recurrences_without_merging_them():
    first = normalization.series_key("venue:7", date(2026, 9, 5), "9/5(토) 더 피스타 밀롱가")
    second = normalization.series_key("venue:7", date(2026, 9, 12), "9/12(토) 더 피스타 밀롱가")
    assert first == second
    # ... while the instances stay distinct, because the date is not in the key.
    assert (normalization.identity_key(date(2026, 9, 5), "venue:7", time(20, 0))
            != normalization.identity_key(date(2026, 9, 12), "venue:7", time(20, 0)))


def test_series_key_needs_both_a_place_and_a_name():
    assert normalization.series_key(None, date(2026, 9, 5), "밀롱가") is None
    assert normalization.series_key("venue:7", date(2026, 9, 5), "") is None


def test_a_weekday_change_is_a_different_series():
    saturday = normalization.series_key("venue:7", date(2026, 9, 5), "밀롱가")
    sunday = normalization.series_key("venue:7", date(2026, 9, 6), "밀롱가")
    assert saturday != sunday


# --- SQL --------------------------------------------------------------------

def _candidate(unique: str, **overrides):
    base = {
        "candidate_id": int(unique[-6:]),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/test/{unique}",
        "event_name": "테스트 밀롱가",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": "아미고스튜디오",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
    }
    base.update(overrides)
    return base


def test_a_candidate_without_a_date_is_not_an_event_instance(pg, unique):
    """A post we could not place on a calendar stays in review rather than
    becoming a row with a made-up day."""
    stored = normalization.normalize_candidate(pg, _candidate(unique, event_date=None))
    assert stored is None


def test_an_unrecognised_venue_is_unresolved_and_queued(pg, unique):
    venue_text = f"미등록 스튜디오 {unique}"
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, venue=venue_text),
    )
    assert stored["venue_status"] == normalization.VENUE_UNRESOLVED
    assert stored["venue_id"] is None
    assert stored["venue_text"] == venue_text

    queued = [v for v in normalization.unresolved_venues(pg)
              if v["venue_text"] == venue_text]
    assert len(queued) == 1


def test_normalizing_never_creates_a_venue(pg, unique):
    """A typo must not become a permanent master record."""
    from runtime import master_data

    before = len(master_data.list_venues(pg))
    normalization.normalize_candidate(pg, _candidate(unique, venue=f"오타 스튜디오 {unique}"))
    assert len(master_data.list_venues(pg)) == before


def test_a_known_alias_resolves_to_the_venue(pg, unique, seoul_id):
    from runtime import master_data

    venue = master_data.create_venue(pg, name=f"엔빠스 {unique}", region_id=seoul_id)
    master_data.add_venue_alias(pg, venue_id=venue["venue_id"], alias=f"EnPaz {unique}")

    stored = normalization.normalize_candidate(
        pg, _candidate(unique, venue=f"EnPaz {unique}"),
    )
    assert stored["venue_status"] == normalization.VENUE_RESOLVED
    assert stored["venue_id"] == venue["venue_id"]
    assert stored["region_id"] == seoul_id


def test_the_bracketed_form_resolves_through_the_alias_candidates(pg, unique, seoul_id):
    """The extractor keeps 엔빠스(EnPaz Tango Studio) whole and offers its parts."""
    from runtime import master_data

    venue = master_data.create_venue(pg, name=f"엔빠스 {unique}", region_id=seoul_id)
    master_data.add_venue_alias(pg, venue_id=venue["venue_id"], alias=f"엔빠스 {unique}")

    stored = normalization.normalize_candidate(
        pg,
        _candidate(unique, venue=f"엔빠스 {unique}(EnPaz Tango Studio)"),
        alias_candidates=[f"엔빠스 {unique}(EnPaz Tango Studio)",
                          f"엔빠스 {unique}", "EnPaz Tango Studio"],
    )
    assert stored["venue_status"] == normalization.VENUE_RESOLVED
    assert stored["venue_id"] == venue["venue_id"]


def test_linking_an_unresolved_venue_updates_the_events_that_were_waiting(pg, unique, seoul_id):
    from runtime import master_data

    venue_text = f"미등록 스튜디오 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    assert stored["venue_status"] == normalization.VENUE_UNRESOLVED

    venue = master_data.create_venue(pg, name=f"실제 스튜디오 {unique}", region_id=seoul_id)
    entry = next(v for v in normalization.unresolved_venues(pg)
                 if v["venue_text"] == venue_text)

    result = normalization.link_unresolved_venue(
        pg, entry["unresolved_venue_id"], venue["venue_id"],
    )
    assert result["events_updated"] == 1

    updated = normalization.get(pg, stored["event_id"])
    assert updated["venue_status"] == normalization.VENUE_RESOLVED
    assert updated["venue_id"] == venue["venue_id"]
    # The identity key contains the venue, so it has to have been rebuilt.
    assert updated["identity_key"] != stored["identity_key"]
    assert f"venue:{venue['venue_id']}" in updated["identity_key"]


def test_linking_records_the_string_as_an_alias_so_it_resolves_next_time(pg, unique, seoul_id):
    from runtime import master_data

    venue_text = f"미등록 스튜디오 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    venue = master_data.create_venue(pg, name=f"실제 스튜디오 {unique}", region_id=seoul_id)
    entry = next(v for v in normalization.unresolved_venues(pg)
                 if v["venue_text"] == venue_text)
    normalization.link_unresolved_venue(pg, entry["unresolved_venue_id"], venue["venue_id"])

    assert master_data.resolve_venue(pg, venue_text)["venue_id"] == venue["venue_id"]


def test_normalizing_the_same_candidate_twice_updates_one_row(pg, unique):
    first = normalization.normalize_candidate(pg, _candidate(unique))
    second = normalization.normalize_candidate(pg, _candidate(unique, fee=15000))
    assert first["event_id"] == second["event_id"]
    assert second["fee"] == 15000


def test_a_human_correction_wins_and_is_recorded_as_such(pg, unique):
    """EDIT keeps both readings. The event carries the corrected one and says
    which fields a person changed."""
    stored = normalization.normalize_candidate(
        pg, _candidate(unique),
        review_state={
            "review_state": "EDITED",
            "corrected_json": {"start_time": "20:00", "venue": "라 벤따나"},
        },
    )
    assert stored["start_time"] == time(20, 0)
    assert stored["venue_text"] == "라 벤따나"
    assert set(stored["field_origin"]) == {"start_time", "venue"}
    assert stored["field_origin"]["start_time"] == "HUMAN"


def test_a_rejected_candidate_is_never_listed(pg, unique):
    stored = normalization.normalize_candidate(
        pg, _candidate(unique), review_state={"review_state": "REJECTED"},
    )
    assert stored["listing_state"] == normalization.HIDDEN


def test_approval_does_not_grant_verified(pg, unique):
    """The engine's evidence gate is the only thing that sets VERIFIED."""
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, candidate_status="POSSIBLE"),
        review_state={"review_state": "APPROVED"},
    )
    assert stored["engine_status"] == "POSSIBLE"
    assert stored["review_state"] == "APPROVED"


@pytest.mark.parametrize("action", [review.APPROVE, review.CONFIRM])
def test_review_states_that_keep_an_event_listed(pg, unique, action):
    stored = normalization.normalize_candidate(
        pg, _candidate(unique),
        review_state={"review_state": review.STATE_BY_ACTION[action]},
    )
    assert stored["listing_state"] == normalization.LISTED


def test_an_untraceable_candidate_is_not_live(pg, unique):
    """Provenance defaults to UNKNOWN, and the alpha surface serves LIVE only."""
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    assert stored["provenance"] == normalization.PROVENANCE_UNKNOWN
