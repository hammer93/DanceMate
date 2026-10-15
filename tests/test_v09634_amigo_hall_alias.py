"""v0.96.34 migration 045: the room spelling of a venue already registered.

Nine of the nights v0.96.33 recovered are written `아미고 큰홀`, the big hall of
a studio this Master has held since before v0.82 - as venue 180 on this
project's own board, as "Amigo Studio" on a database seeded only by
022_tango_venue_aliases.sql. `normalize_alias()` is exact by design, so the
hall resolved to nothing and nine real Busan milongas carried a place nobody
could place.

The migration adds one spelling to the venue that already owns a spelling of
that name, which is how 022 identifies its own groups. Everything here runs
against the `pg` fixture, rolled back at teardown, with the SQL applied the way
test_tango_source_expansion_migration.py applies 021/022 - directly on the
fixture's own connection, never committed.
"""

from __future__ import annotations

import pytest

from runtime import migrate, normalization


def _apply(pg, *versions: str) -> None:
    all_migrations = migrate.discover()
    for version in versions:
        migration = next(m for m in all_migrations
                         if m.name.startswith(f"{version}_"))
        with pg.cursor() as cur:
            cur.execute(migration.sql)


def _hall_rows(pg) -> list[int]:
    with pg.cursor() as cur:
        cur.execute("SELECT venue_id FROM venue_aliases "
                    "WHERE normalized_alias = '아미고큰홀' ORDER BY venue_id")
        return [r[0] for r in cur.fetchall()]


@pytest.fixture
def studio(pg):
    """The venue id this Master already holds a spelling of, with the state
    this migration changes put back.

    The scratch database is built by running every migration, 045 included,
    so its effect is already present before any test starts; removing the one
    row it writes (inside the fixture's own rolled-back transaction) is the
    only way to test what it does.
    """
    with pg.cursor() as cur:
        cur.execute("SELECT venue_id FROM venue_aliases "
                    "WHERE normalized_alias = '아미고스튜디오'")
        row = cur.fetchone()
        if row is None:
            pytest.skip("this database holds no spelling of 아미고스튜디오")
        cur.execute("DELETE FROM venue_aliases "
                    "WHERE normalized_alias = '아미고큰홀'")
    return row[0]


def test_the_hall_resolved_nothing_before_it(pg, studio):
    assert normalization.resolve_venue(pg, "아미고 큰홀")["venue_id"] is None


def test_the_hall_resolves_to_the_studio_that_holds_it(pg, studio):
    _apply(pg, "045")
    assert _hall_rows(pg) == [studio]
    resolved = normalization.resolve_venue(pg, "아미고 큰홀")
    assert resolved["venue_id"] == studio
    assert resolved["venue_status"] == "RESOLVED"


def test_no_venue_is_created_and_no_region_moves(pg, studio):
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venues")
        before = cur.fetchone()[0]
        cur.execute("SELECT region_id FROM venues WHERE venue_id = %s",
                    (studio,))
        region = cur.fetchone()[0]
    _apply(pg, "045")
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venues")
        assert cur.fetchone()[0] == before
        cur.execute("SELECT region_id FROM venues WHERE venue_id = %s",
                    (studio,))
        assert cur.fetchone()[0] == region


def test_applying_it_twice_changes_nothing(pg, studio):
    _apply(pg, "045", "045")
    assert _hall_rows(pg) == [studio]


def test_it_is_a_no_op_where_that_studio_is_not_registered(pg, studio):
    with pg.cursor() as cur:
        cur.execute("DELETE FROM venue_aliases "
                    "WHERE normalized_alias = '아미고스튜디오'")
    _apply(pg, "045")
    assert _hall_rows(pg) == []


def test_the_small_hall_is_deliberately_not_claimed(pg, studio):
    _apply(pg, "045")
    assert normalization.resolve_venue(pg, "아미고 작은홀")["venue_id"] is None
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venue_aliases "
                    "WHERE normalized_alias = '아미고작은홀'")
        assert cur.fetchone()[0] == 0


def test_it_never_takes_a_spelling_another_venue_already_owns(pg, studio):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO venues (name) VALUES ('다른 곳') RETURNING venue_id")
        other = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO venue_aliases (venue_id, alias, normalized_alias) "
            "VALUES (%s, '아미고 큰홀', '아미고큰홀')", (other,))
    _apply(pg, "045")
    assert _hall_rows(pg) == [other]


def test_a_hall_is_not_read_as_a_venue_on_its_own(pg, studio):
    # The Master's unit is the venue, and v0.96.26's `_ROOM_ONLY_RE` already
    # refuses a bare room: this migration adds a qualified spelling, not a
    # room name that could belong to any building.
    _apply(pg, "045")
    assert normalization.resolve_venue(pg, "큰홀")["venue_id"] is None
