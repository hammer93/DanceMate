"""Public Sources tab genre filter (v0.91.0 PHASE 6, corrected).

Uses the real public query, `runtime.directory.public_sources()` - the one
the Sources tab actually calls - not merely `master_data.source_genres()`,
per the PHASE 6 review's explicit correction. `sources.create_source()` is
the real write path too, so this also exercises the create-time
`source_genres` sync fixed in this same pass.
"""

from __future__ import annotations

import pytest

from runtime import directory, master_data, sources


def _genre_id(pg, code: str) -> int:
    for g in master_data.list_genres(pg):
        if g["code"] == code:
            return g["genre_id"]
    pytest.skip(f"{code} genre is not seeded; run the migrations first")


def _source(pg, unique, suffix, **overrides):
    base = dict(
        source_key=f"SRC-T910-{unique}-{suffix}", name=f"T910 {suffix} {unique}",
        platform="WEB", source_role="COMMUNITY", enabled=True,
        url=f"https://example.test/{unique}-{suffix}",
    )
    base.update(overrides)
    return sources.create_source(pg, **base)


def _mine(rows, unique):
    return sorted(r["name"] for r in rows if unique in r["name"])


def test_a_salsa_only_source_appears_under_salsa_not_swing(pg, unique):
    _source(pg, unique, "salsa", genre_id=_genre_id(pg, "SALSA"))
    assert _mine(directory.public_sources(pg, ["SALSA"]), unique) == [f"T910 salsa {unique}"]
    assert _mine(directory.public_sources(pg, ["SWING"]), unique) == []


def test_a_source_with_an_explicit_secondary_genre_appears_under_both(pg, unique):
    source = _source(pg, unique, "multi", genre_id=_genre_id(pg, "SALSA"))
    master_data.add_source_genre(pg, source["source_id"], _genre_id(pg, "BACHATA"))
    assert _mine(directory.public_sources(pg, ["SALSA"]), unique) == [f"T910 multi {unique}"]
    assert _mine(directory.public_sources(pg, ["BACHATA"]), unique) == [f"T910 multi {unique}"]
    assert _mine(directory.public_sources(pg, ["SWING"]), unique) == []


def test_it_appears_exactly_once_under_the_secondary_genre_not_twice(pg, unique):
    source = _source(pg, unique, "once", genre_id=_genre_id(pg, "SALSA"))
    master_data.add_source_genre(pg, source["source_id"], _genre_id(pg, "BACHATA"))
    rows = [r for r in directory.public_sources(pg, ["BACHATA"]) if unique in r["name"]]
    assert len(rows) == 1


def test_a_source_with_three_explicit_genres_appears_under_all_three(pg, unique):
    """Real shape: Elmar's own community carries Bachata+Kizomba+Salsa+Tango."""
    source = _source(pg, unique, "triple", genre_id=_genre_id(pg, "SALSA"))
    master_data.add_source_genre(pg, source["source_id"], _genre_id(pg, "BACHATA"))
    master_data.add_source_genre(pg, source["source_id"], _genre_id(pg, "KIZOMBA"))
    for code in ("SALSA", "BACHATA", "KIZOMBA"):
        assert _mine(directory.public_sources(pg, [code]), unique) == [f"T910 triple {unique}"]


def test_a_disabled_source_never_appears_even_with_a_matching_secondary_genre(pg, unique):
    source = _source(pg, unique, "off", genre_id=_genre_id(pg, "SALSA"), enabled=False)
    master_data.add_source_genre(pg, source["source_id"], _genre_id(pg, "BACHATA"))
    assert _mine(directory.public_sources(pg, ["BACHATA"]), unique) == []


def test_no_filter_still_returns_the_source_once(pg, unique):
    source = _source(pg, unique, "unfiltered", genre_id=_genre_id(pg, "SALSA"))
    master_data.add_source_genre(pg, source["source_id"], _genre_id(pg, "BACHATA"))
    rows = [r for r in directory.public_sources(pg, None) if unique in r["name"]]
    assert len(rows) == 1
