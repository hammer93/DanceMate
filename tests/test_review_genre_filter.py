"""Review-queue genre filter (v0.82, spec Section 42-43).

The review queue lives in the engine's own SQLite file, which knows a post
only by source_key (raw_posts.source_id, TEXT) - genre is a Postgres concept
(sources.genre_id). `runtime.sources.source_keys_for_genre()` is the bridge:
resolve "which source_keys are TANGO" once against Postgres, the same shape
`review.reviewed_candidate_ids()` already provides for `reviewed_ids`.

candidates.query(source_keys=...)'s own filtering correctness is proven at
the SQLite level in test_review_pagination.py; this file covers the
Postgres-side resolver and the route wiring (filter bar / dashboard quick
link / page not crashing) that sits on top of it.
"""

from __future__ import annotations

import pytest

from runtime import sources

CREDENTIALS = ("dancemate", "test-admin-password")


def _genre_id(pg, code: str) -> int:
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = %s", (code,))
        row = cur.fetchone()
    if row is None:
        pytest.skip(f"{code} genre is not seeded; run the migrations first")
    return row[0]


def _make_source(pg, unique, *, genre_code: str, suffix: str):
    return sources.create_source(
        pg, source_key=f"SRC-GENRE-{unique}-{suffix}", name=f"genre test {unique} {suffix}",
        platform="WEB", source_role="COMMUNITY", url="https://example.test/board",
        genre_id=_genre_id(pg, genre_code), enabled=True,
    )


# --- source_keys_for_genre: real Postgres ------------------------------------

def test_resolves_only_the_matching_genres_sources(pg, unique):
    tango = _make_source(pg, unique, genre_code="TANGO", suffix="tango")
    salsa = _make_source(pg, unique, genre_code="SALSA", suffix="salsa")

    tango_keys = sources.source_keys_for_genre(pg, "TANGO")
    assert tango["source_key"] in tango_keys
    assert salsa["source_key"] not in tango_keys


def test_an_unknown_genre_code_resolves_to_an_empty_list(pg, unique):
    _make_source(pg, unique, genre_code="TANGO", suffix="tango")
    assert sources.source_keys_for_genre(pg, "NOT-A-REAL-GENRE") == []


# --- route wiring: real Postgres, through the app ----------------------------

@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", CREDENTIALS[0])
    monkeypatch.setenv("ADMIN_PASSWORD", CREDENTIALS[1])
    monkeypatch.setattr(app_module, "_settings", None)
    from fastapi.testclient import TestClient

    return TestClient(app_module.app, raise_server_exceptions=False)


def test_review_page_accepts_a_genre_filter_without_erroring(client, pg, unique):
    _make_source(pg, unique, genre_code="TANGO", suffix="tango")
    response = client.get("/admin/review?filter=upcoming&genre=TANGO", auth=CREDENTIALS)
    assert response.status_code == 200


def test_review_page_filter_bar_preserves_the_genre_across_tabs(client, pg, unique):
    _make_source(pg, unique, genre_code="TANGO", suffix="tango")
    response = client.get("/admin/review?filter=upcoming&genre=TANGO", auth=CREDENTIALS)
    assert "genre=TANGO" in response.text


def test_review_page_with_an_unknown_genre_shows_zero_not_an_error(client, pg):
    response = client.get("/admin/review?filter=upcoming&genre=NOT-A-REAL-GENRE", auth=CREDENTIALS)
    assert response.status_code == 200


def test_dashboard_offers_a_tango_review_quick_link(client, pg):
    response = client.get("/admin", auth=CREDENTIALS)
    assert response.status_code == 200
    assert "/admin/review?filter=upcoming&genre=TANGO" in response.text
