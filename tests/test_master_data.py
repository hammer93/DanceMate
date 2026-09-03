"""Master data: genres, regions, venues (with aliases) and organizers.

These run against a real PostgreSQL when one is reachable, and skip otherwise -
the logic being tested is SQL, so a mock would only assert that the mock works.
`docker compose up -d postgres` is enough to run them.
"""

from __future__ import annotations

import pytest

from runtime import master_data

pytestmark = pytest.mark.postgres


# --- alias normalisation (pure, always runs) --------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("La Ventana", "laventana"),
        ("la  ventana", "laventana"),
        ("LA-VENTANA!", "laventana"),
        ("라벤타나", "라벤타나"),
        ("라 벤타나", "라벤타나"),
        ("  Ocho  ", "ocho"),
    ],
)
def test_alias_normalisation_folds_case_spacing_and_punctuation(raw, expected):
    assert master_data.normalize_alias(raw) == expected


def test_alias_normalisation_folds_full_width_forms():
    """Korean sources mix half-width and full-width Latin; NFKC settles it."""
    assert master_data.normalize_alias("Ｏｃｈｏ") == master_data.normalize_alias("Ocho")


def test_alias_normalisation_of_punctuation_only_is_empty():
    assert master_data.normalize_alias("!!!  ---") == ""


# --- genres -----------------------------------------------------------------

def test_genre_seed_contains_the_three_launch_genres(pg):
    codes = {g["code"] for g in master_data.list_genres(pg)}
    assert {"TANGO", "SALSA", "SWING"} <= codes


def test_genres_are_seeded_enabled(pg):
    for genre in master_data.list_genres(pg):
        if genre["code"] in ("TANGO", "SALSA", "SWING"):
            assert genre["enabled"] is True


def test_genre_can_be_added_and_disabled_rather_than_deleted(pg, unique):
    code = f"TEST{unique}"
    created = master_data.create_genre(pg, code=code.lower(), name="Test Genre")
    assert created["code"] == code  # normalised to upper case
    assert created["enabled"] is True

    disabled = master_data.set_genre_enabled(pg, created["genre_id"], False)
    assert disabled["enabled"] is False
    # still present, just not enabled
    assert code in {g["code"] for g in master_data.list_genres(pg)}
    assert code not in {g["code"] for g in master_data.list_genres(pg, enabled_only=True)}


def test_genre_requires_code_and_name(pg):
    with pytest.raises(ValueError):
        master_data.create_genre(pg, code="", name="No Code")


# --- regions ----------------------------------------------------------------

def test_seoul_is_seeded(pg):
    regions = {r["code"]: r for r in master_data.list_regions(pg)}
    assert "KR-SEOUL" in regions
    assert regions["KR-SEOUL"]["city"] == "Seoul"
    assert regions["KR-SEOUL"]["country"] == "South Korea"


def test_region_supports_country_city_district(pg, unique):
    created = master_data.create_region(
        pg, code=f"KR-TEST{unique}", country="South Korea",
        city="Busan", district="Haeundae", name=f"Test {unique}",
    )
    assert created["city"] == "Busan"
    assert created["district"] == "Haeundae"


# --- venues -----------------------------------------------------------------

def test_venue_create_and_update(pg, unique, seoul_id):
    venue = master_data.create_venue(
        pg, name=f"Studio {unique}", region_id=seoul_id, address="Seoul",
    )
    assert venue["enabled"] is True

    updated = master_data.update_venue(
        pg, venue["venue_id"], address="Gangnam, Seoul", notes="second floor"
    )
    assert updated["address"] == "Gangnam, Seoul"
    assert updated["notes"] == "second floor"


def test_venue_is_disabled_not_deleted(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"Closing {unique}", region_id=seoul_id)
    master_data.update_venue(pg, venue["venue_id"], enabled=False)
    listed = {v["venue_id"] for v in master_data.list_venues(pg)}
    enabled = {v["venue_id"] for v in master_data.list_venues(pg, enabled_only=True)}
    assert venue["venue_id"] in listed
    assert venue["venue_id"] not in enabled


def test_venue_aliases_resolve_to_one_venue(pg, unique, seoul_id):
    """The point of aliases: three spellings, one place."""
    name = f"La Ventana {unique}"
    venue = master_data.create_venue(
        pg, name=name, region_id=seoul_id,
        aliases=[f"라벤타나{unique}", f"벤타나{unique}"],
    )
    for spelling in (name, name.upper(), f"라 벤타나{unique}", f"벤타나 {unique}"):
        resolved = master_data.resolve_venue(pg, spelling)
        assert resolved is not None, spelling
        assert resolved["venue_id"] == venue["venue_id"], spelling


def test_venue_name_is_registered_as_an_alias(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"Ocho {unique}", region_id=seoul_id)
    aliases = {a["alias"] for a in master_data.venue_aliases(pg, venue["venue_id"])}
    assert f"Ocho {unique}" in aliases


def test_unknown_venue_text_resolves_to_nothing_rather_than_guessing(pg):
    assert master_data.resolve_venue(pg, "no such venue at all 12345") is None
    assert master_data.resolve_venue(pg, "   ") is None


def test_alias_that_normalises_to_nothing_is_rejected(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"Punct {unique}", region_id=seoul_id)
    with pytest.raises(ValueError):
        master_data.add_venue_alias(pg, venue["venue_id"], "!!!")


def test_venue_requires_a_name(pg):
    with pytest.raises(ValueError):
        master_data.create_venue(pg, name="   ")


# --- organizers -------------------------------------------------------------

def test_organizer_create_and_update(pg, unique, seoul_id):
    organizer = master_data.create_organizer(
        pg, name=f"Milonga Crew {unique}", region_id=seoul_id,
        contact_url="https://example.invalid/crew",
    )
    assert organizer["enabled"] is True

    updated = master_data.update_organizer(
        pg, organizer["organizer_id"], notes="runs Friday milongas"
    )
    assert updated["notes"] == "runs Friday milongas"


def test_organizer_is_disabled_not_deleted(pg, unique, seoul_id):
    organizer = master_data.create_organizer(
        pg, name=f"Retired {unique}", region_id=seoul_id
    )
    master_data.update_organizer(pg, organizer["organizer_id"], enabled=False)
    listed = {o["organizer_id"] for o in master_data.list_organizers(pg)}
    enabled = {o["organizer_id"] for o in master_data.list_organizers(pg, enabled_only=True)}
    assert organizer["organizer_id"] in listed
    assert organizer["organizer_id"] not in enabled


def test_organizer_requires_a_name(pg):
    with pytest.raises(ValueError):
        master_data.create_organizer(pg, name="")
