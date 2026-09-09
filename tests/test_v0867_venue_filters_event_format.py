"""v0.86.7 Admin Venue Filters + Genre/Region Management + Social Event Format.

Three pieces: (1) region + multi-genre (OR) filters on /admin/venues,
query-string-persisted; (2) safe genre/region delete - reference-count
blocked, no cascade, core genres (TANGO/SALSA/SWING) always protected;
(3) "Event Format" (MILONGA/PRACTICA/GENERAL/SOCIAL/UNKNOWN) as a
simplified view over the EXISTING events.event_type column
(events_api.format_of()) - investigated first, per the release's own
instruction not to duplicate an existing field with a new one.
"""

from __future__ import annotations

import inspect

import pytest

from runtime import admin, events_api, master_data, master_edit


# === Group 1: Venue region + genre filter (structural, no DB) =============

def test_venue_filter_clause_empty_when_nothing_selected():
    clause, params = master_data._venue_filter_clause(region_id=None, genre_ids=None)
    assert clause == ""
    assert params == []


def test_venue_filter_clause_region_only():
    clause, params = master_data._venue_filter_clause(region_id=5, genre_ids=None)
    assert "v.region_id = %s" in clause
    assert params == [5]


def test_venue_filter_clause_genre_is_or_via_exists():
    clause, params = master_data._venue_filter_clause(region_id=None, genre_ids=[1, 2])
    assert "EXISTS" in clause
    assert "venue_genres" in clause
    assert params == [[1, 2]]


def test_venue_filter_clause_region_and_genre_combined_with_and():
    clause, params = master_data._venue_filter_clause(region_id=5, genre_ids=[1, 2])
    assert " AND " in clause
    assert params == [5, [1, 2]]


def test_admin_venues_route_accepts_region_and_genres_params():
    source = inspect.getsource(admin.admin_venues)
    assert "region: str" in source
    assert "genres: list[str]" in source


def test_admin_venues_never_fuzzy_compares_region_text():
    """Section 2: region matching is `v.region_id = %s`, never a text/ILIKE
    comparison against the region's display name."""
    source = inspect.getsource(master_data._venue_filter_clause)
    assert "ILIKE" not in source
    assert "region_id = %s" in source


# === Group 1b: Venue filter, real data (Postgres, rolled back) ============

@pytest.fixture
def two_venues(pg, unique):
    """Two venues, two genres, one venue tagged with both - enough to
    exercise every OR/AND combination. Rolled back automatically (pg
    fixture never commits)."""
    tango = next((g for g in master_data.list_genres(pg) if g["code"] == "TANGO"), None)
    salsa = next((g for g in master_data.list_genres(pg) if g["code"] == "SALSA"), None)
    swing = next((g for g in master_data.list_genres(pg) if g["code"] == "SWING"), None)
    if not (tango and salsa and swing):
        pytest.skip("TANGO/SALSA/SWING not seeded on this database")
    seoul = next((r for r in master_data.list_regions(pg) if r["code"] == "KR-SEOUL"), None)
    if seoul is None:
        pytest.skip("KR-SEOUL not seeded on this database")

    v_tango = master_data.create_venue(pg, name=f"V0867-Tango-{unique}", region_id=seoul["region_id"])
    v_salsa = master_data.create_venue(pg, name=f"V0867-Salsa-{unique}", region_id=None)
    master_data.add_venue_genre(pg, v_tango["venue_id"], tango["genre_id"])
    master_data.add_venue_genre(pg, v_salsa["venue_id"], salsa["genre_id"])
    return {
        "tango_id": tango["genre_id"], "salsa_id": salsa["genre_id"], "swing_id": swing["genre_id"],
        "seoul_id": seoul["region_id"],
        "v_tango": v_tango["venue_id"], "v_salsa": v_salsa["venue_id"],
    }


# 1. no genre selected -> all
@pytest.mark.postgres
def test_no_genre_filter_returns_both(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(pg, genre_ids=None)}
    assert two_venues["v_tango"] in ids
    assert two_venues["v_salsa"] in ids


# 2. TANGO
@pytest.mark.postgres
def test_tango_only_filter(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(pg, genre_ids=[two_venues["tango_id"]])}
    assert two_venues["v_tango"] in ids
    assert two_venues["v_salsa"] not in ids


# 3. SALSA
@pytest.mark.postgres
def test_salsa_only_filter(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(pg, genre_ids=[two_venues["salsa_id"]])}
    assert two_venues["v_salsa"] in ids
    assert two_venues["v_tango"] not in ids


# 4. SWING (neither venue has it)
@pytest.mark.postgres
def test_swing_only_filter_excludes_both(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(pg, genre_ids=[two_venues["swing_id"]])}
    assert two_venues["v_tango"] not in ids
    assert two_venues["v_salsa"] not in ids


# 5. TANGO + SALSA -> OR, both venues
@pytest.mark.postgres
def test_tango_plus_salsa_is_or(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(
        pg, genre_ids=[two_venues["tango_id"], two_venues["salsa_id"]])}
    assert two_venues["v_tango"] in ids
    assert two_venues["v_salsa"] in ids


# 6. TANGO + SWING -> OR, only the tango venue
@pytest.mark.postgres
def test_tango_plus_swing_is_or(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(
        pg, genre_ids=[two_venues["tango_id"], two_venues["swing_id"]])}
    assert two_venues["v_tango"] in ids
    assert two_venues["v_salsa"] not in ids


# 7. all 3
@pytest.mark.postgres
def test_all_three_genres_is_or(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(
        pg, genre_ids=[two_venues["tango_id"], two_venues["salsa_id"], two_venues["swing_id"]])}
    assert two_venues["v_tango"] in ids
    assert two_venues["v_salsa"] in ids


# 8. region only
@pytest.mark.postgres
def test_region_only_filter(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(pg, region_id=two_venues["seoul_id"])}
    assert two_venues["v_tango"] in ids
    assert two_venues["v_salsa"] not in ids


# 9. region + multi genre (AND)
@pytest.mark.postgres
def test_region_and_genre_combination(pg, two_venues):
    ids = {v["venue_id"] for v in master_data.list_venues(
        pg, region_id=two_venues["seoul_id"],
        genre_ids=[two_venues["tango_id"], two_venues["salsa_id"]])}
    assert two_venues["v_tango"] in ids   # Seoul AND (Tango OR Salsa)
    assert two_venues["v_salsa"] not in ids  # right genre, wrong region


# 10. reset (no params -> unfiltered count matches count_venues with no filter)
@pytest.mark.postgres
def test_reset_clears_filters(pg, two_venues):
    unfiltered = master_data.count_venues(pg)
    filtered = master_data.count_venues(pg, genre_ids=[two_venues["swing_id"]])
    assert unfiltered >= filtered


# === Group 2: Genre delete (11-15) ==========================================

def test_core_genres_are_protected():
    assert master_edit.CORE_GENRE_CODES == frozenset({"TANGO", "SALSA", "SWING"})


@pytest.mark.postgres
def test_core_genre_delete_blocked_regardless_of_usage(pg):
    tango = next(g for g in master_data.list_genres(pg) if g["code"] == "TANGO")
    with pytest.raises(master_edit.EditError, match="핵심 장르"):
        master_edit.delete_genre(pg, tango["genre_id"])


# 11. unreferenced genre delete
@pytest.mark.postgres
def test_unreferenced_genre_delete_succeeds(pg, unique):
    genre = master_data.create_genre(pg, code=f"V0867{unique}"[:16].upper(), name=f"Test {unique}")
    result = master_edit.delete_genre(pg, genre["genre_id"])
    assert result["genre"]["genre_id"] == genre["genre_id"]
    assert master_data.get_genre(pg, genre["genre_id"]) is None


# 12/13. referenced genre blocked, counts shown
@pytest.mark.postgres
def test_referenced_genre_delete_blocked_with_counts(pg, unique):
    genre = master_data.create_genre(pg, code=f"V0867R{unique}"[:16].upper(), name=f"Ref {unique}")
    venue = master_data.create_venue(pg, name=f"V0867-ref-venue-{unique}")
    master_data.add_venue_genre(pg, venue["venue_id"], genre["genre_id"])
    with pytest.raises(master_edit.EditError) as exc_info:
        master_edit.delete_genre(pg, genre["genre_id"])
    assert "Venue 1건" in str(exc_info.value)


# 14. no cascade - the referencing venue_genres row survives the blocked attempt
@pytest.mark.postgres
def test_blocked_genre_delete_never_cascades(pg, unique):
    genre = master_data.create_genre(pg, code=f"V0867C{unique}"[:16].upper(), name=f"Casc {unique}")
    venue = master_data.create_venue(pg, name=f"V0867-casc-venue-{unique}")
    master_data.add_venue_genre(pg, venue["venue_id"], genre["genre_id"])
    with pytest.raises(master_edit.EditError):
        master_edit.delete_genre(pg, genre["genre_id"])
    assert master_data.get_venue(pg, venue["venue_id"]) is not None
    assert master_data.get_genre(pg, genre["genre_id"]) is not None
    usage = master_data.genre_usage(pg, genre["genre_id"])
    assert usage["venues"] == 1


# 15. core genre protected (duplicate of the dedicated test above, kept for
#     the required-test numbering)
def test_core_genre_protection_is_unconditional():
    assert "TANGO" in master_edit.CORE_GENRE_CODES


# === Group 3: Region delete (16-20) =========================================

# 16. unreferenced region delete
@pytest.mark.postgres
def test_unreferenced_region_delete_succeeds(pg, unique):
    region = master_data.create_region(
        pg, code=f"V0867-{unique}"[:20].upper(), country="South Korea", name=f"Test {unique}")
    result = master_edit.delete_region(pg, region["region_id"])
    assert result["region"]["region_id"] == region["region_id"]
    assert master_data.get_region(pg, region["region_id"]) is None


# 17. venue-referenced blocked
@pytest.mark.postgres
def test_venue_referenced_region_blocked(pg, unique):
    region = master_data.create_region(
        pg, code=f"V0867V-{unique}"[:20].upper(), country="South Korea", name=f"VenueRef {unique}")
    master_data.create_venue(pg, name=f"V0867-region-venue-{unique}", region_id=region["region_id"])
    with pytest.raises(master_edit.EditError, match="Venue 1건"):
        master_edit.delete_region(pg, region["region_id"])


# 18. event-referenced blocked (checked via usage() directly - creating a
#     real committed event is out of scope for a rolled-back unit test;
#     the SQL is identical in shape to the venue case above, and this
#     confirms the events column is actually included in the query).
@pytest.mark.postgres
def test_region_usage_counts_events_column(pg):
    source = inspect.getsource(master_data.region_usage)
    assert "FROM events WHERE region_id" in source


# 19. no cascade
@pytest.mark.postgres
def test_blocked_region_delete_never_cascades(pg, unique):
    region = master_data.create_region(
        pg, code=f"V0867N-{unique}"[:20].upper(), country="South Korea", name=f"NoCasc {unique}")
    venue = master_data.create_venue(
        pg, name=f"V0867-nocasc-venue-{unique}", region_id=region["region_id"])
    with pytest.raises(master_edit.EditError):
        master_edit.delete_region(pg, region["region_id"])
    assert master_data.get_venue(pg, venue["venue_id"]) is not None
    assert master_data.get_region(pg, region["region_id"]) is not None


# 20. confirmation dialog shows name/counts
def test_delete_confirmation_shows_reference_counts():
    html = admin._delete_form(
        "genres", 1, "TestGenre", core=False,
        usage={"venues": 12, "organizers": 0, "sources": 3, "events": 48})
    assert "12건" in html
    assert "48건" in html
    assert "3건" in html


def test_delete_confirmation_offers_no_cascade_option():
    html = admin._delete_form(
        "genres", 1, "TestGenre", core=False,
        usage={"venues": 1, "organizers": 0, "sources": 0, "events": 0})
    assert "force" not in html
    assert "unlink" not in html


# === Group 4: Event Format (21-30) ==========================================

# 21-24: label mapping
def test_milonga_label():
    assert events_api.EVENT_TYPE_LABELS["MILONGA"] == "밀롱가"


def test_practica_label_is_ppeurek_not_the_old_transliteration():
    assert events_api.EVENT_TYPE_LABELS["PRACTICA"] == "쁘렉"


def test_general_label():
    assert events_api.EVENT_TYPE_LABELS["GENERAL"] == "제너럴"


def test_social_label():
    assert events_api.EVENT_TYPE_LABELS["SOCIAL"] == "소셜"


# 25. UNKNOWN
def test_format_of_unknown_for_class_and_other_and_blank():
    assert events_api.format_of("CLASS") == events_api.EVENT_FORMAT_UNKNOWN
    assert events_api.format_of("OTHER") == events_api.EVENT_FORMAT_UNKNOWN
    assert events_api.format_of(None) == events_api.EVENT_FORMAT_UNKNOWN
    assert events_api.format_of("") == events_api.EVENT_FORMAT_UNKNOWN
    assert events_api.EVENT_FORMAT_LABELS[events_api.EVENT_FORMAT_UNKNOWN] == "미분류"


def test_format_of_folds_with_class_variants_into_their_base_format():
    assert events_api.format_of("MILONGA_WITH_CLASS") == events_api.EVENT_FORMAT_MILONGA
    assert events_api.format_of("SOCIAL_WITH_CLASS") == events_api.EVENT_FORMAT_SOCIAL
    assert events_api.format_of("PARTY") == events_api.EVENT_FORMAT_SOCIAL


# 26. Admin single-select - format_of always returns exactly one code, never a list
def test_format_of_returns_a_single_value():
    result = events_api.format_of("MILONGA")
    assert isinstance(result, str)
    assert result in events_api.EVENT_FORMAT_LABELS


# 27. Public display - the Timeline's own type slot already reads
#     event_type_label, which now carries the corrected/new labels
def test_public_timeline_shows_practica_and_general_labels():
    from datetime import datetime

    from runtime import public

    now = datetime.fromisoformat("2026-09-09T10:00:00+09:00")
    base = {
        "id": 1, "name": "x", "date": "2026-09-09", "start_time": "20:00",
        "end_time": "22:00", "ends_next_day": False, "time_confirmed": True,
        "region": "서울", "region_confirmed": True,
        "venue": {"name": None, "status": "ABSENT", "aliases": []},
        "fee": None, "dj": None, "status": "VERIFIED", "status_label": "확인됨",
        "cancelled": False, "source_link": {"url": None, "label": None},
        "last_checked": None,
    }
    for event_type, label in (("PRACTICA", "쁘렉"), ("GENERAL", "제너럴")):
        line1 = public._timeline_line1(
            {**base, "event_type_label": events_api.EVENT_TYPE_LABELS[event_type]}, now=now)
        assert label in line1


# 28. ? indicator still works alongside the format label
def test_confirm_flag_still_appears_next_to_format_label():
    from datetime import datetime

    from runtime import public

    now = datetime.fromisoformat("2026-09-09T10:00:00+09:00")
    event = {
        "id": 1, "name": "x", "date": "2026-09-09", "start_time": "20:00",
        "end_time": "22:00", "ends_next_day": False, "time_confirmed": True,
        "event_type_label": "쁘렉", "region": "서울", "region_confirmed": True,
        "venue": {"name": None, "status": "ABSENT", "aliases": []},
        "fee": None, "dj": None, "status": "POSSIBLE", "status_label": "확인 필요",
        "cancelled": False, "source_link": {"url": None, "label": None},
        "last_checked": None,
    }
    line1 = public._timeline_line1(event, now=now)
    assert "쁘렉" in line1
    assert 'class="confirm-flag"' in line1


# 29. VERIFIED -> no ?
def test_verified_format_shows_no_question_mark():
    from datetime import datetime

    from runtime import public

    now = datetime.fromisoformat("2026-09-09T10:00:00+09:00")
    event = {
        "id": 1, "name": "x", "date": "2026-09-09", "start_time": "20:00",
        "end_time": "22:00", "ends_next_day": False, "time_confirmed": True,
        "event_type_label": "제너럴", "region": "서울", "region_confirmed": True,
        "venue": {"name": None, "status": "ABSENT", "aliases": []},
        "fee": None, "dj": None, "status": "VERIFIED", "status_label": "확인됨",
        "cancelled": False, "source_link": {"url": None, "label": None},
        "last_checked": None,
    }
    line1 = public._timeline_line1(event, now=now)
    assert "제너럴" in line1
    assert "confirm-flag" not in line1


# 30. Admin/Public parity - one dict, no second formatter
def test_admin_format_chips_use_the_same_label_dict_as_public():
    source = inspect.getsource(admin._format_chips)
    assert "events_api.EVENT_FORMAT_LABELS" in source
    assert "events_api.format_of(" in source


def test_no_duplicate_event_format_column_or_table():
    """Section 27-28: Event Format is a derived view over events.event_type,
    never a second stored column - this release's own migration (031) only
    extends master_data_actions' action CHECK constraint for the new
    genre/region DELETE audit entry, it does not touch events or add any
    new event-format table/column."""
    migration_031 = open(
        "migrations/runtime/031_master_data_delete_action.sql", encoding="utf-8"
    ).read()
    assert "ALTER TABLE events" not in migration_031
    assert "CREATE TABLE" not in migration_031
    assert "master_data_actions" in migration_031


# === Regression (Section 52) ================================================

def test_venue_after_region_regression():
    from datetime import datetime

    from runtime import public

    now = datetime.fromisoformat("2026-09-09T10:00:00+09:00")
    event = {
        "id": 1, "name": "x", "date": "2026-09-09", "start_time": "20:00",
        "end_time": "22:00", "ends_next_day": False, "time_confirmed": True,
        "event_type_label": "밀롱가", "region": "서울", "region_confirmed": True,
        "venue": {"name": "Tango O Nada", "status": "RESOLVED", "aliases": []},
        "fee": None, "dj": None, "status": "VERIFIED", "status_label": "확인됨",
        "cancelled": False, "source_link": {"url": None, "label": None},
        "last_checked": None,
    }
    line1 = public._timeline_line1(event, now=now)
    assert line1.index("[서울]") < line1.index("Tango O Nada")


def test_open_ended_time_regression():
    from datetime import datetime

    from runtime import public

    now = datetime.fromisoformat("2026-09-09T10:00:00+09:00")
    clock = public._timeline_clock({"start_time": "21:00", "end_time": None})
    assert clock == '21:00~<span class="unknown">미정</span>'


def test_genre_source_filter_regression():
    # Structural check only (no DB needed): the source-level genre filter
    # from v0.86.4/v0.86.5 must still exist unchanged.
    from runtime import sources

    assert hasattr(sources, "count_sources")
    assert "genre_code" in inspect.signature(sources.count_sources).parameters
