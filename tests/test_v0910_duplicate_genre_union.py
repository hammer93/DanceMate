"""Merging a duplicate must not lose its explicit genres (v0.91.0 PHASE 6).

A losing (non-canonical, HIDDEN) event's own event_genres rows become
unreachable to any public query the moment it is merged - nothing queries a
non-canonical row's genres again. record_decision() unions them onto the
survivor before hiding the loser, origin preserved, never guessing a new one.
"""

from __future__ import annotations

from runtime import duplicates, normalization


def _live(pg, unique, suffix, *, genre_hints=None, **overrides):
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/dupgenre/{unique}-{suffix}",
        "event_name": f"중복장르 테스트 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"스튜디오 {unique}",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    candidate.update(overrides)
    return normalization.normalize_candidate(pg, candidate, genre_hints=genre_hints)


def _genres(pg, event_id):
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id, origin FROM event_genres WHERE event_id = %s", (event_id,))
        return dict(cur.fetchall())


def test_merging_a_duplicate_unions_its_secondary_genre_onto_the_survivor(pg, unique):
    survivor = _live(pg, unique, "1")
    loser = _live(pg, unique, "2", genre_hints=["BACHATA"], venue=f"스튜디오 {unique}")

    duplicates.record_decision(
        pg, event_id=loser["event_id"], canonical_event_id=survivor["event_id"],
        decision=duplicates.DUPLICATE, decided_by=duplicates.AUTO,
        rule=duplicates.RULE_SAME_DATE_VENUE_TIME,
    )

    survivor_genres = _genres(pg, survivor["event_id"])
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'BACHATA'")
        bachata_id = cur.fetchone()[0]
    assert bachata_id in survivor_genres


def test_a_human_confirmed_genre_on_the_loser_transfers_as_human(pg, unique):
    survivor = _live(pg, unique, "1")
    loser = _live(pg, unique, "2", venue=f"스튜디오 {unique}")
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'KIZOMBA'")
        kizomba_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO event_genres (event_id, genre_id, origin) VALUES (%s, %s, 'HUMAN')",
            (loser["event_id"], kizomba_id),
        )

    duplicates.record_decision(
        pg, event_id=loser["event_id"], canonical_event_id=survivor["event_id"],
        decision=duplicates.DUPLICATE, decided_by=duplicates.AUTO,
        rule=duplicates.RULE_SAME_DATE_VENUE_TIME,
    )

    assert _genres(pg, survivor["event_id"]).get(kizomba_id) == "HUMAN"


def test_a_human_row_on_the_loser_upgrades_the_survivors_matching_auto_row(pg, unique):
    """The conflict path: both rows already have the same genre, survivor's
    is AUTO, loser's is HUMAN - HUMAN must win, in this direction."""
    survivor = _live(pg, unique, "1", genre_hints=["BACHATA"])
    loser = _live(pg, unique, "2", genre_hints=["BACHATA"], venue=f"스튜디오 {unique}")
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'BACHATA'")
        bachata_id = cur.fetchone()[0]
        cur.execute(
            "UPDATE event_genres SET origin = 'HUMAN' WHERE event_id = %s AND genre_id = %s",
            (loser["event_id"], bachata_id),
        )
    assert _genres(pg, survivor["event_id"])[bachata_id] == "AUTO"  # before the merge

    duplicates.record_decision(
        pg, event_id=loser["event_id"], canonical_event_id=survivor["event_id"],
        decision=duplicates.DUPLICATE, decided_by=duplicates.AUTO,
        rule=duplicates.RULE_SAME_DATE_VENUE_TIME,
    )

    assert _genres(pg, survivor["event_id"])[bachata_id] == "HUMAN"


def test_a_human_row_on_the_survivor_is_never_downgraded_by_the_losers_auto_row(pg, unique):
    """The reverse direction: survivor's own row is already HUMAN, the
    loser's matching row is only AUTO - the survivor's HUMAN row must
    survive the merge unchanged, never downgraded back to AUTO."""
    survivor = _live(pg, unique, "1", genre_hints=["BACHATA"])
    loser = _live(pg, unique, "2", genre_hints=["BACHATA"], venue=f"스튜디오 {unique}")
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'BACHATA'")
        bachata_id = cur.fetchone()[0]
        cur.execute(
            "UPDATE event_genres SET origin = 'HUMAN' WHERE event_id = %s AND genre_id = %s",
            (survivor["event_id"], bachata_id),
        )

    duplicates.record_decision(
        pg, event_id=loser["event_id"], canonical_event_id=survivor["event_id"],
        decision=duplicates.DUPLICATE, decided_by=duplicates.AUTO,
        rule=duplicates.RULE_SAME_DATE_VENUE_TIME,
    )

    assert _genres(pg, survivor["event_id"])[bachata_id] == "HUMAN"


def test_the_losers_own_genres_are_not_deleted_only_copied(pg, unique):
    survivor = _live(pg, unique, "1")
    loser = _live(pg, unique, "2", genre_hints=["BACHATA"], venue=f"스튜디오 {unique}")

    duplicates.record_decision(
        pg, event_id=loser["event_id"], canonical_event_id=survivor["event_id"],
        decision=duplicates.DUPLICATE, decided_by=duplicates.AUTO,
        rule=duplicates.RULE_SAME_DATE_VENUE_TIME,
    )

    assert _genres(pg, loser["event_id"])  # still present, just unreachable publicly


def test_marking_distinct_never_touches_event_genres(pg, unique):
    """The DISTINCT path (not DUPLICATE) has nothing to union - two real,
    different events keep their own genres untouched."""
    left = _live(pg, unique, "1", genre_hints=["BACHATA"])
    right = _live(pg, unique, "2", venue=f"스튜디오 {unique}")
    before = _genres(pg, right["event_id"])

    duplicates.record_decision(
        pg, event_id=right["event_id"], canonical_event_id=None,
        decision=duplicates.DISTINCT, decided_by=duplicates.AUTO,
        rule=duplicates.RULE_VENUE_TIME_DIFFERS,
    )

    assert _genres(pg, right["event_id"]) == before
