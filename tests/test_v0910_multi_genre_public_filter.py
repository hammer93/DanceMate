"""Public genre filter over a multi-genre event (v0.91.0 PHASE 6, corrected).

PHASE 6 review: the original SALSA+BACHATA+KIZOMBA fixture used
event_type="MILONGA" (primary TANGO) and only ever checked TANGO/BACHATA/
KIZOMBA - it proved the EXISTS-vs-JOIN mechanism but never a genuine SALSA
(or SWING) primary. `_genre_source_item()` below is the real, established
source-fallback pattern (tests/test_quality_and_ux.py's own
test_a_social_takes_its_genre_from_the_community_that_posted_it) - a real
Source registered with a real primary genre_id, a real source_items row, and
event_type="SOCIAL" (not in normalization.GENRE_BY_EVENT_TYPE) so
_genre_id() actually falls through to the source lookup, the same code path
production uses for every non-Tango event today.
"""

from __future__ import annotations

from datetime import date

from runtime import events_api, master_data, normalization, sources


def _genre_id(pg, code: str):
    return next(g["genre_id"] for g in master_data.list_genres(pg) if g["code"] == code)


def _genre_source_item(pg, unique: str, genre_code: str) -> int:
    """A real Source registered with a real primary genre, and one real
    source_items row posted by it - what normalize_candidate()'s source
    fallback actually reads to resolve a non-Tango event's genre."""
    source = sources.create_source(
        pg, source_key=f"SRC-T910-{genre_code}-{unique}",
        name=f"{genre_code} 커뮤니티 {unique}", platform="DAUM_CAFE",
        source_role="COMMUNITY", url=f"https://cafe.daum.net/{genre_code.lower()}{unique}",
        genre_id=_genre_id(pg, genre_code), queries=[f"{genre_code} 소셜"],
    )
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, title, content_hash) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING source_item_id",
            (source["source_id"], f"item-{unique}",
             f"https://cafe.daum.net/{genre_code.lower()}{unique}/1", "소셜 공지", f"h-{unique}"),
        )
        return cur.fetchone()[0]


def _live(pg, unique, suffix, *, genre_hints=None, source_item_id=None, **overrides):
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_item_id": source_item_id,
        "source_url": f"https://cafe.daum.net/multigenre/{unique}-{suffix}",
        "event_name": f"멀티장르 테스트 {unique}",
        "event_type": "SOCIAL" if source_item_id is not None else "MILONGA",
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


def _mine(result, unique):
    return [e for e in result["events"] if unique in (e["name"] or "")]


# --- mechanism pins (TANGO/MILONGA: no Source setup needed) ------------------
#
# These prove the EXISTS-vs-JOIN plumbing itself (once-only, no duplication,
# no cross-contamination) fast and without extra fixture cost - the genuine
# Salsa/Swing primary tests below are what actually prove genre correctness.

def test_a_multi_genre_event_appears_under_its_primary_genre(pg, unique):
    _live(pg, unique, "1", genre_hints=["BACHATA"])
    found = _mine(events_api.search(pg, on="2026-09-05", genre="TANGO", limit=100), unique)
    assert len(found) == 1


def test_a_multi_genre_event_also_appears_under_its_secondary_genre(pg, unique):
    _live(pg, unique, "1", genre_hints=["BACHATA"])
    found = _mine(events_api.search(pg, on="2026-09-05", genre="BACHATA", limit=100), unique)
    assert len(found) == 1


def test_it_appears_exactly_once_under_the_secondary_genre_not_twice(pg, unique):
    _live(pg, unique, "1", genre_hints=["BACHATA"])
    found = _mine(events_api.search(pg, on="2026-09-05", genre="BACHATA", limit=100), unique)
    assert len(found) == 1


def test_a_single_genre_event_is_unaffected(pg, unique):
    """No genre_hints at all - behaves exactly as before migration 040."""
    _live(pg, unique, "1")
    assert len(_mine(events_api.search(pg, on="2026-09-05", genre="TANGO", limit=100), unique)) == 1
    assert _mine(events_api.search(pg, on="2026-09-05", genre="SALSA", limit=100), unique) == []


def test_the_multi_genre_checkbox_filter_also_sees_the_secondary_genre(pg, unique):
    _live(pg, unique, "1", genre_hints=["BACHATA"])
    found = _mine(
        events_api.search(pg, on="2026-09-05", genres=["SALSA", "BACHATA"], limit=100), unique,
    )
    assert len(found) == 1


def test_week_counts_also_counts_the_event_once_under_each_genre(pg, unique):
    _live(pg, unique, "1", genre_hints=["BACHATA"])
    tango_counts = events_api.week_counts(
        pg, start=date(2026, 9, 5), end=date(2026, 9, 5), genre="TANGO",
    )
    bachata_counts = events_api.week_counts(
        pg, start=date(2026, 9, 5), end=date(2026, 9, 5), genre="BACHATA",
    )
    assert tango_counts.get("2026-09-05", 0) >= 1
    assert bachata_counts.get("2026-09-05", 0) >= 1


# --- genuine SALSA / SWING primaries (PHASE 6 review's explicit correction) --

def test_a_genuine_salsa_primary_event_appears_under_salsa_bachata_and_kizomba(pg, unique):
    """Real production shape: SRC-D-020 Elmar is a registered-Salsa source
    whose own post explicitly also names Bachata; the community layer
    (community_genres) already carries Kizomba too. This event's *primary*
    genre is genuinely Salsa (resolved via the real source-fallback path,
    not the MILONGA/TANGO shortcut), with Bachata and Kizomba as explicit
    hints - not inferred, not a coincidence of TANGO's own fixed mapping."""
    item_id = _genre_source_item(pg, unique, "SALSA")
    _live(pg, unique, "1", source_item_id=item_id, genre_hints=["BACHATA", "KIZOMBA"])
    for code in ("SALSA", "BACHATA", "KIZOMBA"):
        found = _mine(events_api.search(pg, on="2026-09-05", genre=code, limit=100), unique)
        assert len(found) == 1, code


def test_a_genuine_salsa_primary_event_never_appears_under_swing(pg, unique):
    item_id = _genre_source_item(pg, unique, "SALSA")
    _live(pg, unique, "1", source_item_id=item_id, genre_hints=["BACHATA", "KIZOMBA"])
    assert _mine(events_api.search(pg, on="2026-09-05", genre="SWING", limit=100), unique) == []


def test_a_genuine_swing_primary_event_with_balboa_appears_under_both(pg, unique):
    """Real production shape: SRC-D-012 Swing Factory's own community row
    (community_id=14) carries Swing+Balboa."""
    item_id = _genre_source_item(pg, unique, "SWING")
    _live(pg, unique, "2", source_item_id=item_id, genre_hints=["BALBOA"],
          venue=f"스튜디오스윙 {unique}")
    for code in ("SWING", "BALBOA"):
        found = _mine(events_api.search(pg, on="2026-09-05", genre=code, limit=100), unique)
        assert len(found) == 1, code


def test_a_genuine_swing_balboa_event_never_appears_under_salsa(pg, unique):
    item_id = _genre_source_item(pg, unique, "SWING")
    _live(pg, unique, "2", source_item_id=item_id, genre_hints=["BALBOA"],
          venue=f"스튜디오스윙 {unique}")
    assert _mine(events_api.search(pg, on="2026-09-05", genre="SALSA", limit=100), unique) == []


def test_the_salsa_and_swing_events_each_appear_exactly_once_under_their_own_primary(pg, unique):
    salsa_item = _genre_source_item(pg, unique, "SALSA")
    swing_item = _genre_source_item(pg, unique, "SWING")
    _live(pg, unique, "1", source_item_id=salsa_item, genre_hints=["BACHATA"])
    _live(pg, unique, "2", source_item_id=swing_item, genre_hints=["BALBOA"],
          venue=f"스튜디오스윙 {unique}")
    assert len(_mine(events_api.search(pg, on="2026-09-05", genre="SALSA", limit=100), unique)) == 1
    assert len(_mine(events_api.search(pg, on="2026-09-05", genre="SWING", limit=100), unique)) == 1
