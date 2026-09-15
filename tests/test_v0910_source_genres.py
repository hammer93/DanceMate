"""Source multi-genre relation (v0.91.0 PHASE 6, migration 040; corrected).

Authoritative contract: `source_genres` holds every genre a source is
associated with, *including* the compatibility primary in
`sources.genre_id` - the same invariant migration 040's own backfill
establishes for every pre-existing row. `sources.create_source()` and
`update_source()` keep it true going forward; `master_edit.set_source_genres()`
force-includes the current primary in whatever set an admin submits, so the
primary relation can never disappear through that path - changing what the
primary *is* stays `update_source(genre_id=...)`'s job.

Real motivation: SRC-D-020 (Elmar)'s own community row (community_id=6,
already real production data) carries Bachata+Kizomba+Salsa+Tango, but the
Source row itself is registered Salsa-only. This lets an admin register that
same multi-genre scope on the Source directly, without changing what
`sources.genre_id` means to every existing reader.
"""

from __future__ import annotations

import pytest

from runtime import master_data, master_edit, sources


def _genre_id(pg, code: str) -> int:
    for g in master_data.list_genres(pg):
        if g["code"] == code:
            return g["genre_id"]
    pytest.skip(f"{code} genre is not seeded; run the migrations first")


def _source(pg, unique: str, **overrides):
    base = dict(
        source_key=f"SRC-TEST-{unique}", name=f"테스트 소스 {unique}",
        platform="DAUM_CAFE", source_role="COMMUNITY",
        url=f"https://cafe.daum.net/test{unique}",
        genre_id=None, enabled=False,
    )
    base.update(overrides)
    return sources.create_source(pg, **base)


def _codes(pg, source_id):
    return {g["genre_code"] for g in master_data.source_genres(pg, source_id)}


# --- create/update keep source_genres in sync with the primary --------------

def test_a_new_source_with_a_primary_genre_has_it_in_source_genres(pg, unique):
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    assert _codes(pg, source["source_id"]) == {"SALSA"}


def test_a_new_source_with_no_primary_genre_has_no_source_genres_row(pg, unique):
    source = _source(pg, unique, genre_id=None)
    assert _codes(pg, source["source_id"]) == set()


def test_changing_the_primary_via_update_source_adds_the_new_one(pg, unique):
    """update_source(genre_id=...) is the one supported way to change what
    the primary *is* - the new primary must appear in source_genres too."""
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    sources.update_source(pg, source["source_id"], genre_id=_genre_id(pg, "SWING"))
    assert _codes(pg, source["source_id"]) == {"SALSA", "SWING"}


def test_changing_the_primary_never_deletes_other_explicit_genres(pg, unique):
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    master_edit.set_source_genres(pg, source["source_id"], [_genre_id(pg, "BACHATA")])
    sources.update_source(pg, source["source_id"], genre_id=_genre_id(pg, "SWING"))
    assert _codes(pg, source["source_id"]) == {"SALSA", "BACHATA", "SWING"}


def test_an_unrelated_update_does_not_touch_source_genres(pg, unique):
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    sources.update_source(pg, source["source_id"], name=f"이름변경 {unique}")
    assert _codes(pg, source["source_id"]) == {"SALSA"}


# --- set_source_genres: the primary can never disappear ----------------------

def test_registering_an_extra_genre_leaves_the_primary_present(pg, unique):
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    bachata_id = _genre_id(pg, "BACHATA")
    result = master_edit.set_source_genres(pg, source["source_id"], [bachata_id])
    assert result["added"] == ["BACHATA"]
    refreshed = sources.get_source(pg, source["source_id"])
    assert refreshed["genre_id"] == _genre_id(pg, "SALSA")
    assert _codes(pg, source["source_id"]) == {"SALSA", "BACHATA"}


def test_registering_bachata_and_kizomba_together(pg, unique):
    """Real shape: Elmar's own community carries Bachata+Kizomba+Salsa+Tango."""
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    ids = [_genre_id(pg, "BACHATA"), _genre_id(pg, "KIZOMBA")]
    master_edit.set_source_genres(pg, source["source_id"], ids)
    assert _codes(pg, source["source_id"]) == {"SALSA", "BACHATA", "KIZOMBA"}


def test_submitting_a_set_that_omits_the_primary_still_keeps_it(pg, unique):
    """The one gap PHASE 6's review caught: an admin form that only ever
    submits the *additional* genres (or a stale form missing the primary
    checkbox) must never be read as "remove the primary"."""
    salsa_id = _genre_id(pg, "SALSA")
    source = _source(pg, unique, genre_id=salsa_id)
    result = master_edit.set_source_genres(pg, source["source_id"], [_genre_id(pg, "BACHATA")])
    assert "SALSA" not in result["removed"]
    assert salsa_id in {row["genre_id"] for row in master_data.source_genres(pg, source["source_id"])}


def test_duplicate_genre_registration_is_a_no_op(pg, unique):
    source = _source(pg, unique, genre_id=None)
    bachata_id = _genre_id(pg, "BACHATA")
    master_data.add_source_genre(pg, source["source_id"], bachata_id)
    master_data.add_source_genre(pg, source["source_id"], bachata_id)
    assert len(master_data.source_genres(pg, source["source_id"])) == 1


def test_an_invalid_genre_is_rejected_and_the_primary_survives(pg, unique):
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    with pytest.raises(master_edit.EditError):
        master_edit.set_source_genres(pg, source["source_id"], [999999999])
    assert _codes(pg, source["source_id"]) == {"SALSA"}


def test_a_later_edit_diffs_against_what_is_already_registered(pg, unique):
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    master_edit.set_source_genres(pg, source["source_id"], [_genre_id(pg, "BACHATA")])
    result = master_edit.set_source_genres(
        pg, source["source_id"], [_genre_id(pg, "KIZOMBA")], reviewer="tester",
    )
    assert result["added"] == ["KIZOMBA"]
    assert result["removed"] == ["BACHATA"]
    # SALSA (the primary) was in both the old and new wanted set - neither
    # added nor removed, but never gone.
    assert "SALSA" not in result["added"] and "SALSA" not in result["removed"]
    assert _codes(pg, source["source_id"]) == {"SALSA", "KIZOMBA"}


def test_removing_a_source_genre_leaves_the_source_and_its_events_untouched(pg, unique):
    source = _source(pg, unique, genre_id=_genre_id(pg, "SALSA"))
    bachata_id = _genre_id(pg, "BACHATA")
    master_data.add_source_genre(pg, source["source_id"], bachata_id)
    master_data.remove_source_genre(pg, source["source_id"], bachata_id)
    assert _codes(pg, source["source_id"]) == {"SALSA"}
    assert sources.get_source(pg, source["source_id"]) is not None


def test_genre_usage_counts_source_genres_separately_from_the_primary_column(pg, unique):
    salsa_id = _genre_id(pg, "SALSA")
    bachata_id = _genre_id(pg, "BACHATA")
    source = _source(pg, unique, genre_id=salsa_id)
    master_data.add_source_genre(pg, source["source_id"], bachata_id)
    salsa_usage = master_data.genre_usage(pg, salsa_id)
    bachata_usage = master_data.genre_usage(pg, bachata_id)
    assert salsa_usage["sources"] >= 1
    assert bachata_usage["source_genres"] >= 1


def test_a_genre_only_referenced_via_source_genres_still_blocks_deletion(pg, unique):
    genre = master_data.create_genre(pg, code=f"V0910SG{unique}"[:16].upper(),
                                     name=f"테스트장르 {unique}")
    source = _source(pg, unique, genre_id=None)
    master_data.add_source_genre(pg, source["source_id"], genre["genre_id"])
    with pytest.raises(master_edit.EditError, match="SourceGenre"):
        master_edit.delete_genre(pg, genre["genre_id"])


def test_deleting_a_genre_that_is_only_the_primary_is_still_blocked_via_source_genres(pg, unique):
    """Under the corrected contract the primary is *also* a source_genres
    row, so the existing `usage["sources"]` check and the new
    `usage["source_genres"]` check would both fire - neither must be lost,
    and deletion stays blocked either way."""
    genre = master_data.create_genre(pg, code=f"V0910SP{unique}"[:16].upper(),
                                     name=f"테스트기본장르 {unique}")
    _source(pg, unique, genre_id=genre["genre_id"])
    with pytest.raises(master_edit.EditError):
        master_edit.delete_genre(pg, genre["genre_id"])
