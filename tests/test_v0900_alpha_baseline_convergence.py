"""v0.90.0 Alpha Readiness & Baseline Convergence: migration 039.

A fresh 001-038 install and real Production had quietly diverged: three
Regions (KR-BUSAN/KR-DAEJEON/KR-INCHEON) and three Genres (BACHATA/BALBOA/
KIZOMBA) that Production only ever got by hand through the Admin console,
and one Source (SRC-W-001 "K-TANGO") that predates this project's own
migrations, were never captured in any migration. Migration 039 converges a
fresh install onto that same baseline - and, separately, corrects SRC-D-003's
migration-027-seeded authority_level ('PRIMARY_COMMUNITY', a value outside
runtime/sources.py's own AUTHORITY_LEVELS domain) to 'UNKNOWN', the same fix
this project's v0.87.0 release already applied to every other row that had
the same bad value.

Every test here runs only against the `pg` fixture (rolled back at teardown,
never committed) and applies 039's own SQL text directly on `pg`'s
connection - the same pattern test_tango_source_expansion_migration.py and
test_miltang_source_migration.py already use - so nothing here ever touches
a real database permanently, regardless of whether the target database was
migrated through 039 already.
"""

from __future__ import annotations

import pytest

from runtime import community_discovery, master_data, migrate, sources


def _migration(version: str):
    return next(m for m in migrate.discover() if m.name.startswith(f"{version}_"))


def _apply(pg, *versions: str) -> None:
    for version in versions:
        with pg.cursor() as cur:
            cur.execute(_migration(version).sql)


# --- the migration seeds exactly what it says it does ------------------------

def test_039_seeds_the_three_baseline_regions(pg):
    _apply(pg, "039")
    regions = {r["code"]: r for r in master_data.list_regions(pg)}
    expected = {
        "KR-BUSAN": "부산",
        "KR-DAEJEON": "대전",
        "KR-INCHEON": "인천",
    }
    for code, name in expected.items():
        assert code in regions, code
        assert regions[code]["name"] == name
        assert regions[code]["country"] == "South Korea"


def test_039_seeds_the_three_baseline_genres(pg):
    _apply(pg, "039")
    genres = {g["code"]: g for g in master_data.list_genres(pg)}
    for code, name in (("BACHATA", "Bachata"), ("BALBOA", "Balboa"), ("KIZOMBA", "Kizomba")):
        assert code in genres, code
        assert genres[code]["name"] == name


def test_039_seeds_k_tango_with_productions_own_values(pg):
    _apply(pg, "039")
    row = sources.get_source_by_key(pg, "SRC-W-001")
    assert row is not None
    assert row["name"] == "K-TANGO"
    assert row["platform"] == "WEB"
    assert row["source_role"] == "ORGANIZER"
    assert row["url"] == "http://www.k-tango.net/"
    assert row["genre_id"] is None
    assert row["region_id"] is None
    assert row["authority_level"] == "PRIMARY_ORGANIZER"
    assert row["queries"] == []
    assert row["config"] == {
        "board_urls": ["http://www.k-tango.net/cnf/festival02/index.jsp"]
    }
    assert row["enabled"] is True
    assert row["collection_interval_minutes"] == 240


def test_039_corrects_d003s_invalid_legacy_authority(pg):
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE sources SET authority_level = 'PRIMARY_COMMUNITY' "
            "WHERE source_key = 'SRC-D-003'"
        )
    _apply(pg, "039")
    row = sources.get_source_by_key(pg, "SRC-D-003")
    assert row is not None
    assert row["authority_level"] == "UNKNOWN"
    assert row["authority_level"] in sources.AUTHORITY_LEVELS


# --- idempotence ---------------------------------------------------------------

def test_039_is_idempotent(pg):
    _apply(pg, "039")

    def _counts():
        with pg.cursor() as cur:
            cur.execute("SELECT count(*) FROM regions")
            regions_n = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM genres")
            genres_n = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM sources")
            sources_n = cur.fetchone()[0]
            cur.execute("SELECT updated_at FROM sources WHERE source_key = 'SRC-D-003'")
            d003_updated_at = cur.fetchone()[0]
        return regions_n, genres_n, sources_n, d003_updated_at

    before = _counts()
    _apply(pg, "039")
    after = _counts()
    assert after == before


# --- ON CONFLICT DO NOTHING preserves whatever an operator already has -------

def test_operator_added_region_survives_039_untouched(pg):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO regions (code, country, city, name) VALUES "
            "('KR-BUSAN', 'South Korea', 'Busan', 'Operator Named This Busan') "
            "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING region_id, name, enabled"
        )
        region_id, name_before, enabled_before = cur.fetchone()

    _apply(pg, "039")

    regions = {r["code"]: r for r in master_data.list_regions(pg)}
    assert regions["KR-BUSAN"]["region_id"] == region_id
    assert regions["KR-BUSAN"]["name"] == name_before == "Operator Named This Busan"
    assert regions["KR-BUSAN"]["enabled"] == enabled_before


def test_operator_added_genre_survives_039_untouched(pg):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO genres (code, name) VALUES "
            "('BACHATA', 'Operator Named This Bachata') "
            "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING genre_id, name"
        )
        genre_id, name_before = cur.fetchone()

    _apply(pg, "039")

    genres = {g["code"]: g for g in master_data.list_genres(pg)}
    assert genres["BACHATA"]["genre_id"] == genre_id
    assert genres["BACHATA"]["name"] == name_before == "Operator Named This Bachata"


def test_operator_added_k_tango_survives_039_untouched(pg):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (source_key, name, platform, source_role, "
            "authority_level, queries, config, enabled, collection_interval_minutes) "
            "VALUES ('SRC-W-001', 'Operator Renamed K-TANGO', 'WEB', 'ORGANIZER', "
            "'PRIMARY_ORGANIZER', '[]'::jsonb, '{}'::jsonb, FALSE, 999) "
            "ON CONFLICT (source_key) DO UPDATE SET "
            "  name = EXCLUDED.name, enabled = EXCLUDED.enabled, "
            "  collection_interval_minutes = EXCLUDED.collection_interval_minutes "
            "RETURNING source_id, name, enabled, collection_interval_minutes"
        )
        source_id, name_before, enabled_before, interval_before = cur.fetchone()

    _apply(pg, "039")

    row = sources.get_source_by_key(pg, "SRC-W-001")
    assert row["source_id"] == source_id
    assert row["name"] == name_before == "Operator Renamed K-TANGO"
    assert row["enabled"] == enabled_before is False
    assert row["collection_interval_minutes"] == interval_before == 999


def test_authority_correction_is_scoped_to_d003_only(pg):
    """Any other row - valid or invalid - is untouched by 039's UPDATE."""
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (source_key, name, platform, source_role, "
            "authority_level, queries, config, enabled, collection_interval_minutes) "
            "VALUES ('SRC-TEST-OTHER-LEGACY', 'Some Other Legacy Row', 'WEB', "
            "'ORGANIZER', 'PRIMARY_COMMUNITY', '[]'::jsonb, '{}'::jsonb, FALSE, 60)"
        )
    valid_before = sources.get_source_by_key(pg, "SRC-W-006")
    assert valid_before is not None and valid_before["authority_level"] == "PRIMARY_ORGANIZER"

    _apply(pg, "039")

    other_row = sources.get_source_by_key(pg, "SRC-TEST-OTHER-LEGACY")
    assert other_row["authority_level"] == "PRIMARY_COMMUNITY"
    valid_after = sources.get_source_by_key(pg, "SRC-W-006")
    assert valid_after["authority_level"] == "PRIMARY_ORGANIZER"


# --- the current Community Discovery vocabulary is fully seedable ------------

def test_discovery_target_genres_all_exist_after_039(pg):
    _apply(pg, "039")
    genre_codes = {g["code"] for g in master_data.list_genres(pg)}
    for code in community_discovery.TARGET_GENRES:
        assert code in genre_codes, code


def test_discovery_region_query_codes_all_exist_after_039(pg):
    _apply(pg, "039")
    region_codes = {r["code"] for r in master_data.list_regions(pg)}
    for code in community_discovery.REGION_QUERY_CODES:
        assert code in region_codes, code


# --- master-data only: no runtime-generated row is seeded --------------------

def test_039_seeds_only_master_data_tables():
    sql = _migration("039").sql
    for table in (
        "venues", "events", "communities", "community_venues", "community_genres",
        "board_posts", "boards",
        "community_discovery_items", "community_discovery_queries",
        "community_discovery_runs", "organizers",
    ):
        assert f"INSERT INTO {table}" not in sql, table
    # Exactly the three master tables this migration is scoped to.
    inserted_tables = {
        line.split("INSERT INTO", 1)[1].strip().split()[0]
        for line in sql.splitlines() if "INSERT INTO" in line
    }
    assert inserted_tables == {"regions", "genres", "sources"}
