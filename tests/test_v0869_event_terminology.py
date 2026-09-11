"""v0.86.9 Event Terminology Settings.

A scene's own words for its events - 밀롱가 / Milonga, 쁘락띠까 / Practica,
쁘롱가 / Pronga - mapped to the Event Formats DanceMate already classifies by.
One word can mean several formats: a Pronga is a milonga and a practica at
once, and that is stored as two formats, never one and never a joined string.

Covers the resolver (pure), its parity with the engine's restated copy, the
real engine classifier and pipeline with Settings words handed in, the
normalization step that stores the formats, the Settings storage and its
validation, the migration's seeds, and the Settings screen and routes.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import pytest

from runtime import admin, event_terms, events_api, master_admin

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "engine") not in sys.path:
    sys.path.insert(0, str(REPO / "engine"))

from src import classifier, live_pipeline  # noqa: E402  (the real engine)
from src.collectors.base import RawPostRecord  # noqa: E402

MILONGA, PRACTICA = events_api.EVENT_FORMAT_MILONGA, events_api.EVENT_FORMAT_PRACTICA
GENERAL, SOCIAL = events_api.EVENT_FORMAT_GENERAL, events_api.EVENT_FORMAT_SOCIAL


def term(display, formats, *, tid, enabled=True, genre_id=1):
    return {"event_term_id": tid, "genre_id": genre_id, "term": display,
            "normalized_term": event_terms.normalize_term(display), "enabled": enabled,
            "formats": event_terms.ordered_formats(formats)}


SEEDS = [
    term("Milonga", {MILONGA}, tid=1), term("밀롱가", {MILONGA}, tid=2),
    term("Practica", {PRACTICA}, tid=3), term("쁘락띠까", {PRACTICA}, tid=4),
    term("Pronga", {MILONGA, PRACTICA}, tid=5), term("쁘롱가", {MILONGA, PRACTICA}, tid=6),
]


def formats_of(text, terms=SEEDS):
    hit = event_terms.resolve_event_terms(text, terms)
    return set(hit["formats"]) if hit else None


# --- the required mappings ---------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Milonga", {MILONGA}),
    ("Saturday Milonga", {MILONGA}),
    ("밀롱가", {MILONGA}),
    ("토요일 밀롱가", {MILONGA}),
    ("Practica", {PRACTICA}),
    ("Practica Night", {PRACTICA}),
    ("쁘락띠까", {PRACTICA}),
    ("일요일 쁘락띠까", {PRACTICA}),
    ("Pronga", {MILONGA, PRACTICA}),
    ("Friday Pronga", {MILONGA, PRACTICA}),
    ("쁘롱가", {MILONGA, PRACTICA}),
    ("금요일 쁘롱가에서 만나요", {MILONGA, PRACTICA}),
])
def test_the_required_terms_resolve_to_their_formats(text, expected):
    assert formats_of(text) == expected


def test_pronga_is_two_formats_not_one():
    hit = event_terms.resolve_event_terms("Friday Pronga", SEEDS)
    assert hit["formats"] == (MILONGA, PRACTICA)
    assert hit["term"] == "Pronga"


# --- unknown, disabled, and nothing fuzzy ------------------------------------

@pytest.mark.parametrize("text", ["Tango Night", "쁘렉틸롱가 모임", "워크샵", "", None])
def test_an_unknown_word_is_not_forced_into_a_format(text):
    assert event_terms.resolve_event_terms(text, SEEDS) is None


def test_a_disabled_term_does_not_match():
    terms = [term("Pronga", {MILONGA, PRACTICA}, tid=5, enabled=False)]
    assert event_terms.resolve_event_terms("Friday Pronga", terms) is None


def test_a_term_with_no_formats_does_not_match():
    bare = dict(term("Pronga", {MILONGA}, tid=5))
    bare["formats"] = ()
    assert event_terms.resolve_event_terms("Friday Pronga", [bare]) is None


def test_case_and_whitespace_and_width_do_not_matter():
    assert formats_of("  friday   PRONGA ") == {MILONGA, PRACTICA}
    assert formats_of("ＰＲＯＮＧＡ") == {MILONGA, PRACTICA}     # full-width, NFKC


def test_a_latin_term_must_be_a_whole_word():
    assert formats_of("practical dance tips") is None
    assert formats_of("milongamania") is None
    assert formats_of("pre-milonga warmup") == {MILONGA}         # hyphen is a boundary


def test_a_korean_term_matches_with_its_particles_attached():
    assert formats_of("쁘락띠까는 매주") == {PRACTICA}


# --- ambiguity: a fixed, tested policy ------------------------------------------

def test_overlapping_matches_keep_the_longest():
    terms = [term("Pronga", {MILONGA, PRACTICA}, tid=5),
             term("Pronga Night", {SOCIAL}, tid=9)]
    hit = event_terms.resolve_event_terms("Friday Pronga Night", terms)
    assert hit["term"] == "Pronga Night"
    assert hit["formats"] == (SOCIAL,)


def test_separate_matches_all_count():
    hit = event_terms.resolve_event_terms("Milonga & Practica", SEEDS)
    assert hit["formats"] == (MILONGA, PRACTICA)
    assert hit["terms"] == ["Milonga", "Practica"]


def test_the_same_term_twice_counts_once():
    hit = event_terms.resolve_event_terms("Milonga after Milonga", SEEDS)
    assert hit["terms"] == ["Milonga"]


def test_equal_length_overlaps_resolve_the_same_way_every_time():
    terms = [term("ab cd", {MILONGA}, tid=2), term("cd ef", {PRACTICA}, tid=1)]
    first = event_terms.resolve_event_terms("ab cd ef", terms)
    again = event_terms.resolve_event_terms("ab cd ef", list(reversed(terms)))
    assert first == again
    assert first["term"] == "ab cd"            # same length: the earlier one wins


def test_formats_always_come_out_in_the_canonical_order():
    assert event_terms.ordered_formats({PRACTICA, MILONGA}) == (MILONGA, PRACTICA)
    assert event_terms.ordered_formats([SOCIAL, GENERAL, MILONGA]) == (MILONGA, GENERAL, SOCIAL)


def test_the_canonical_choices_are_the_existing_event_formats():
    assert set(event_terms.FORMAT_CHOICES) == set(events_api.EVENT_FORMAT_LABELS) - {
        events_api.EVENT_FORMAT_UNKNOWN}


# --- what the engine is handed --------------------------------------------------

def test_detection_terms_are_the_enabled_milonga_and_practica_words():
    terms = SEEDS + [term("Social Night", {SOCIAL}, tid=20),
                     term("Old Word", {MILONGA}, tid=21, enabled=False)]
    words = event_terms.detection_terms(terms)
    assert set(words) == {"milonga", "밀롱가", "practica", "쁘락띠까", "pronga", "쁘롱가"}


@pytest.mark.parametrize("text", ["  Friday   PRONGA ", "ＰＲＯＮＧＡ", "금요일\t쁘롱가", "MiLoNgA"])
def test_the_engine_normalizes_exactly_like_the_runtime(text):
    assert classifier.normalize_term_text(text) == event_terms.normalize_term(text)


@pytest.mark.parametrize("word, text", [
    ("pronga", "friday pronga"), ("practica", "practical tips"), ("milonga", "milongamania"),
    ("쁘락띠까", "쁘락띠까는 매주"), ("milonga", "pre-milonga"), ("pronga", ""),
])
def test_the_engine_matches_exactly_like_the_runtime(word, text):
    runtime_says = bool(event_terms.term_spans(word, event_terms.normalize_term(text)))
    assert classifier.term_occurs(word, classifier.normalize_term_text(text)) is runtime_says


# --- the real classifier and pipeline ---------------------------------------------

DETECT = event_terms.detection_terms(SEEDS)


@pytest.mark.parametrize("title, expected", [
    ("Friday Pronga", "MILONGA"),
    ("Saturday Milonga", "MILONGA"),
    ("Practica Night", "MILONGA"),
    ("금요일 쁘롱가", "MILONGA"),
])
def test_the_engine_recognises_a_settings_word_as_a_tango_social(title, expected):
    """The engine's own single classification stays its existing vocabulary -
    MILONGA is what it has always called a tango social, practicas included;
    the finer formats are the runtime's (next test)."""
    assert classifier.classify(title, "", event_terms=DETECT) == expected


@pytest.mark.parametrize("title, expected", [
    ("Friday Pronga", {MILONGA, PRACTICA}),
    ("Saturday Milonga", {MILONGA}),
    ("Practica Night", {PRACTICA}),
])
def test_the_runtime_resolves_the_formats_for_the_same_titles(title, expected):
    assert formats_of(title) == expected


def test_without_settings_words_the_engine_classifies_exactly_as_before():
    assert classifier.classify("Friday Pronga", "") == "OTHER"
    assert classifier.classify("Saturday Milonga", "") == "MILONGA"
    assert classifier.classify("쁘락 모임", "") == "MILONGA"


def test_settings_words_never_remove_a_built_in_one():
    assert classifier.classify("토요일 밀롱가", "", event_terms=()) == "MILONGA"
    assert classifier.classify("토요일 밀롱가", "", event_terms=("pronga",)) == "MILONGA"


def test_a_settings_word_never_turns_a_lesson_into_an_event():
    assert classifier.classify("쁘롱가 강습 모집", "", event_terms=DETECT) == "CLASS"


def test_an_unknown_word_stays_other_in_the_engine_too():
    assert classifier.classify("Tango Night", "", event_terms=DETECT) == "OTHER"


def test_the_image_evidence_path_passes_the_words_through():
    classification, _ = classifier.classify_with_image_evidence(
        "Friday Pronga", "", event_terms=DETECT)
    assert classification == "MILONGA"


def test_the_pipeline_hands_the_records_words_to_the_classifier(monkeypatch):
    seen = {}

    def _spy(title, body, **kwargs):
        seen.update(kwargs)
        return "OTHER", None

    monkeypatch.setattr(live_pipeline, "classify_with_image_evidence", _spy)
    post = RawPostRecord(source_id="S", platform="WEB", source_url="u", title="Friday Pronga",
                         body="", event_terms=("pronga",))
    assert live_pipeline.process_discovered_post(None, post)["events"] == []
    assert seen["event_terms"] == ("pronga",)


def test_a_record_without_words_is_the_record_it_always_was():
    post = RawPostRecord(source_id="S", platform="WEB", source_url="u", title="t", body="b")
    assert post.event_terms is None


def test_the_runtime_puts_the_words_on_the_record():
    from runtime import engine_ingest

    post = engine_ingest._to_raw_post(
        RawPostRecord, {"raw": {}, "url": "https://x", "title": "Friday Pronga",
                        "source_key": "S", "platform": "WEB"},
        None, event_terms=("pronga",))
    assert post.event_terms == ("pronga",)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *a, **k):
        return None

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)


def test_a_sources_genre_scopes_the_words_it_is_given(monkeypatch):
    from runtime import engine_ingest

    tango = [term("Pronga", {MILONGA, PRACTICA}, tid=5, genre_id=1)]
    salsa = [term("Social Salsa", {MILONGA}, tid=8, genre_id=2)]
    monkeypatch.setattr(event_terms, "terms_by_genre", lambda con: {1: tango, 2: salsa})
    lookup = engine_ingest._detection_terms_by_source(_Conn([(10, 1), (20, 2), (30, None)]))
    assert lookup(10) == ("pronga",)
    assert lookup(20) == ("social salsa",)
    assert set(lookup(30)) == {"pronga", "social salsa"}      # no genre: every genre's


def test_unreadable_terminology_leaves_classification_as_it_was(monkeypatch):
    from runtime import engine_ingest

    def _boom(con):
        raise RuntimeError("no table yet")

    monkeypatch.setattr(event_terms, "terms_by_genre", _boom)
    assert engine_ingest._detection_terms_by_source(_Conn([]))(10) is None


# --- normalization stores the formats -----------------------------------------------

def test_normalization_stores_both_formats_for_a_pronga():
    from runtime import normalization

    grouped = {1: SEEDS}
    assert normalization._event_formats(None, "Friday Pronga", 1, grouped) == [MILONGA, PRACTICA]
    assert normalization._event_formats(None, "Saturday Milonga", 1, grouped) == [MILONGA]
    assert normalization._event_formats(None, "Tango Night", 1, grouped) is None
    assert normalization._event_formats(None, "Friday Pronga", 2, grouped) is None   # other genre
    assert normalization._event_formats(None, "Friday Pronga", None, grouped) == [MILONGA, PRACTICA]


def test_a_terminology_failure_never_stops_an_event_being_built(monkeypatch):
    from runtime import normalization

    def _boom(con):
        raise RuntimeError("down")

    monkeypatch.setattr(event_terms, "terms_by_genre", _boom)
    assert normalization._event_formats(object(), "Friday Pronga", 1, None) is None


def test_the_kind_label_reads_the_stored_formats_first():
    assert events_api.event_kind_label("MILONGA", [PRACTICA, MILONGA]) == "밀롱가 + 프락티카"
    assert events_api.event_kind_label("MILONGA", None) == "밀롱가"
    assert events_api.event_kind_label("MILONGA", []) == "밀롱가"
    assert events_api.event_kind_label(None, None) == "미분류"


# --- the Settings screen, rendered -----------------------------------------------------

@pytest.fixture
def stub_settings(monkeypatch):
    from runtime import master_data, timeline_settings

    class _Settings:
        version = "0.86.9"
        engine_version = "0.85"
        env = "test"

    @contextlib.contextmanager
    def _connection():
        yield object()

    rows = [dict(t, genre_code="TANGO", genre_name="Tango") for t in SEEDS]
    monkeypatch.setattr(admin, "_settings", lambda: _Settings())
    monkeypatch.setattr(admin, "_connection", _connection)
    monkeypatch.setattr(timeline_settings, "get_settings",
                        lambda con: {"enabled": True, "statuses": set()})
    monkeypatch.setattr(event_terms, "list_terms", lambda con, **kw: rows)
    monkeypatch.setattr(master_data, "list_genres", lambda con, **kw: [
        {"genre_id": 1, "code": "TANGO", "name": "Tango", "enabled": True},
        {"genre_id": 2, "code": "SALSA", "name": "Salsa", "enabled": True}])
    return rows


def _settings_page(url):
    from starlette.requests import Request
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    req = Request({"type": "http", "method": "GET", "path": parts.path,
                   "query_string": parts.query.encode(), "headers": []})
    return admin.admin_settings_page(req, _="tester").body.decode()


def test_settings_has_a_terminology_section(stub_settings):
    """v0.87.0 retired the Timeline checklist that used to sit above it."""
    html = _settings_page("/admin/settings")
    assert "사용자 Timeline 확인 표시" not in html
    assert '<h2 id="event-terms">행사 용어 (Event Terminology)</h2>' in html


def test_a_dual_mapping_is_shown_as_two_formats(stub_settings):
    html = _settings_page("/admin/settings")
    row = html.split('id="row-TERM-5"', 1)[1].split("</tr>", 1)[0]
    assert "Pronga" in row
    assert "밀롱가 <code>MILONGA</code> + 프락티카 <code>PRACTICA</code>" in row


def test_editing_a_term_opens_the_whole_row_with_every_format_selectable(stub_settings):
    html = _settings_page("/admin/settings?edit=TERM:5")
    assert html.count('class="editing"') == 1
    row = html.split('id="row-TERM-5"', 1)[1].split("</tr>", 1)[0]
    for code in event_terms.FORMAT_CHOICES:
        assert f'name="formats" value="{code}" form="edit-TERM-5"' in row
    assert 'value="MILONGA" form="edit-TERM-5" checked' in row
    assert 'value="PRACTICA" form="edit-TERM-5" checked' in row
    assert 'value="SOCIAL" form="edit-TERM-5">' in row
    assert 'name="genre_id" form="edit-TERM-5"' in row
    assert 'name="enabled" form="edit-TERM-5"' in row
    assert 'action="/admin/settings/event-terms/5/edit"' in html
    assert "완료" in row and "취소" in row


def test_the_add_form_offers_every_genre_from_the_master(stub_settings):
    html = _settings_page("/admin/settings")
    add = html.split('action="/admin/settings/event-terms"', 1)[1].split("</form>", 1)[0]
    assert '<option value="1">Tango</option>' in add
    assert '<option value="2">Salsa</option>' in add
    assert add.count('name="formats"') == len(event_terms.FORMAT_CHOICES)


def test_the_existing_event_format_chips_were_not_replaced():
    """v0.86.9 added its own chip helper; the Item Audit's format chips are
    still the v0.86.7 function, fed by the same label dict."""
    assert admin._format_chips.__code__.co_varnames[0] == "event_type"
    assert "_term_format_chips" in dir(admin)


def test_a_term_save_returns_to_settings_on_the_row():
    target = master_admin._back_to_view("TERM", 5, "/admin/settings?edit=TERM%3A5",
                                        "ok").headers["location"]
    assert target.startswith("/admin/settings?") and "edit=" not in target
    assert target.endswith("#row-TERM-5")
    kept = master_admin._back_to_view("TERM", 5, "/admin/settings?edit=TERM%3A5",
                                      "bad", "bad", keep_editing=True).headers["location"]
    assert "edit=TERM%3A5" in kept
    assert master_admin._back_to_view("TERM", 5, "https://evil/", "x").headers[
        "location"].startswith("/admin/settings")


# --- storage, validation and seeds against a real database ------------------------------

def _genre(pg, code):
    from runtime import master_data

    found = next((g for g in master_data.list_genres(pg) if g["code"] == code), None)
    if found is None:
        pytest.skip(f"{code} not seeded")
    return found["genre_id"]


def test_the_migration_seeds_the_six_settled_terms(pg):
    tango = _genre(pg, "TANGO")
    seeded = {t["term"]: set(t["formats"]) for t in event_terms.list_terms(pg, genre_id=tango)}
    assert seeded["Milonga"] == {MILONGA}
    assert seeded["밀롱가"] == {MILONGA}
    assert seeded["Practica"] == {PRACTICA}
    assert seeded["쁘락띠까"] == {PRACTICA}
    assert seeded["Pronga"] == {MILONGA, PRACTICA}
    assert seeded["쁘롱가"] == {MILONGA, PRACTICA}


def test_a_dual_mapping_is_two_rows_not_a_joined_string(pg):
    with pg.cursor() as cur:
        cur.execute("SELECT f.event_format FROM event_term_formats f "
                    "JOIN event_terms t ON t.event_term_id = f.event_term_id "
                    "JOIN genres g ON g.genre_id = t.genre_id "
                    "WHERE g.code = 'TANGO' AND t.normalized_term = 'pronga' "
                    "ORDER BY f.event_format")
        assert [r[0] for r in cur.fetchall()] == [MILONGA, PRACTICA]
        cur.execute("SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'events' AND column_name = 'event_formats'")
        assert cur.fetchone()[0] == "ARRAY"


def test_nothing_unsettled_was_seeded(pg):
    tango = _genre(pg, "TANGO")
    normalized = {t["normalized_term"] for t in event_terms.list_terms(pg, genre_id=tango)}
    assert "쁘렉틸롱가" not in normalized
    assert "practilonga" not in normalized


def test_create_update_disable_and_delete(pg, unique):
    tango = _genre(pg, "TANGO")
    created = event_terms.create_term(pg, genre_id=tango, term=f"Test Term {unique}",
                                      formats=[PRACTICA, MILONGA])
    assert created["formats"] == (MILONGA, PRACTICA)
    assert created["enabled"] is True
    updated = event_terms.update_term(pg, created["event_term_id"], genre_id=tango,
                                      term=f"Test Term {unique}", formats=[SOCIAL],
                                      enabled=False)
    assert updated["formats"] == (SOCIAL,) and updated["enabled"] is False
    grouped = event_terms.terms_by_genre(pg)
    assert created["event_term_id"] not in {t["event_term_id"] for t in grouped.get(tango, [])}
    removed = event_terms.delete_term(pg, created["event_term_id"])
    assert removed["event_term_id"] == created["event_term_id"]
    assert event_terms.get_term(pg, created["event_term_id"]) is None
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_term_formats WHERE event_term_id = %s",
                    (created["event_term_id"],))
        assert cur.fetchone()[0] == 0


def test_a_normalized_duplicate_in_the_same_genre_is_refused(pg):
    tango = _genre(pg, "TANGO")
    with pytest.raises(event_terms.TermError, match="이미 있는 용어"):
        event_terms.create_term(pg, genre_id=tango, term="  PRONGA  ", formats=[MILONGA])


def test_the_same_word_in_another_genre_is_its_own_term(pg):
    salsa = _genre(pg, "SALSA")
    created = event_terms.create_term(pg, genre_id=salsa, term="Pronga", formats=[SOCIAL])
    assert created["genre_id"] == salsa and created["formats"] == (SOCIAL,)


@pytest.mark.parametrize("kwargs, message", [
    ({"term": "   ", "formats": [MILONGA]}, "용어를 입력"),
    ({"term": "Brand New", "formats": []}, "하나 이상"),
    ({"term": "Brand New", "formats": ["DISCO"]}, "알 수 없는 분류"),
])
def test_invalid_terms_are_refused_with_a_reason(pg, kwargs, message):
    tango = _genre(pg, "TANGO")
    with pytest.raises(event_terms.TermError, match=message):
        event_terms.create_term(pg, genre_id=tango, **kwargs)


def test_a_term_for_a_genre_that_does_not_exist_is_refused(pg):
    with pytest.raises(event_terms.TermError, match="존재하지 않는 장르"):
        event_terms.create_term(pg, genre_id=999999999, term="Ghost", formats=[MILONGA])


def test_an_update_may_keep_its_own_spelling(pg, unique):
    tango = _genre(pg, "TANGO")
    created = event_terms.create_term(pg, genre_id=tango, term=f"Keep {unique}",
                                      formats=[MILONGA])
    again = event_terms.update_term(pg, created["event_term_id"], genre_id=tango,
                                    term=f"KEEP {unique}", formats=[MILONGA], enabled=True)
    assert again["term"] == f"KEEP {unique}"


def test_normalization_writes_both_formats_into_a_real_event(pg, unique):
    from runtime import normalization

    stored = normalization.normalize_candidate(pg, {
        "candidate_id": int(f"87{unique}"), "event_name": "Friday Pronga",
        "event_date": "2026-10-02", "start_time": "20:00", "event_type": "MILONGA",
        "candidate_status": "POSSIBLE",
    })
    assert stored["event_type"] == "MILONGA"                  # the engine's own, untouched
    assert stored["event_formats"] == [MILONGA, PRACTICA]


# --- the routes, against a real database (committed, then removed) ----------------------

_REAL_POSTGRES = {
    key: os.environ.get(f"TEST_{key}") or os.environ.get(key)
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
                "POSTGRES_USER", "POSTGRES_PASSWORD")
}


@pytest.fixture
def route_client(env, monkeypatch):
    """A TestClient that reaches the real database, and removes every term it
    created - the routes commit, so the cleanup has to as well."""
    from fastapi.testclient import TestClient

    from runtime import app as app_module
    from runtime import db
    from runtime.config import load_settings

    if not _REAL_POSTGRES.get("POSTGRES_PASSWORD"):
        pytest.skip("no PostgreSQL credentials; run inside the runtime container")
    for key, value in _REAL_POSTGRES.items():
        if value:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")
    monkeypatch.setattr(app_module, "_settings", None)
    created: list[str] = []
    try:
        with db.connect(load_settings(), autocommit=True) as con:
            tango = next(g["genre_id"] for g in __import__("runtime.master_data",
                                                           fromlist=["x"]).list_genres(con)
                         if g["code"] == "TANGO")
    except db.DatabaseUnavailable as exc:  # pragma: no cover
        pytest.skip(f"no PostgreSQL reachable: {exc}")
    client = TestClient(app_module.app, raise_server_exceptions=False)
    yield client, tango, created
    with db.connect(load_settings(), autocommit=True) as con:
        with con.cursor() as cur:
            for word in created:
                cur.execute("DELETE FROM event_terms WHERE normalized_term = %s",
                            (event_terms.normalize_term(word),))


AUTH = ("tester", "test-only")


def test_the_settings_routes_create_edit_and_delete(route_client, unique):
    client, tango, created = route_client
    word = f"RouteTerm{unique}"
    created.append(word)
    r = client.post("/admin/settings/event-terms", auth=AUTH, follow_redirects=False,
                    data={"genre_id": str(tango), "term": word, "formats": ["MILONGA", "PRACTICA"],
                          "enabled": "1", "return_to": "/admin/settings"})
    assert r.status_code == 303 and "tone=ok" in r.headers["location"]
    term_id = int(r.headers["location"].rsplit("#row-TERM-", 1)[1])

    page = client.get("/admin/settings", auth=AUTH).text
    assert word in page

    bad = client.post(f"/admin/settings/event-terms/{term_id}/edit", auth=AUTH,
                      follow_redirects=False,
                      data={"genre_id": str(tango), "term": word, "enabled": "1",
                            "return_to": f"/admin/settings?edit=TERM%3A{term_id}"})
    assert "tone=bad" in bad.headers["location"]
    assert f"edit=TERM%3A{term_id}" in bad.headers["location"]       # row stays open

    ok = client.post(f"/admin/settings/event-terms/{term_id}/edit", auth=AUTH,
                     follow_redirects=False,
                     data={"genre_id": str(tango), "term": word, "formats": ["PRACTICA"],
                           "enabled": "0",
                           "return_to": f"/admin/settings?edit=TERM%3A{term_id}"})
    assert "tone=ok" in ok.headers["location"] and "edit=" not in ok.headers["location"]

    gone = client.post(f"/admin/settings/event-terms/{term_id}/delete", auth=AUTH,
                       follow_redirects=False, data={"return_to": "/admin/settings"})
    assert "tone=ok" in gone.headers["location"]


def test_the_duplicate_route_is_refused_and_says_why(route_client):
    client, tango, _ = route_client
    r = client.post("/admin/settings/event-terms", auth=AUTH, follow_redirects=False,
                    data={"genre_id": str(tango), "term": "pronga", "formats": ["MILONGA"],
                          "enabled": "1", "return_to": "/admin/settings"})
    assert r.status_code == 303 and "tone=bad" in r.headers["location"]


def test_the_routes_require_authentication():
    from fastapi.testclient import TestClient

    from runtime import app as app_module

    client = TestClient(app_module.app, raise_server_exceptions=False)
    for path in ("/admin/settings/event-terms", "/admin/settings/event-terms/1/edit",
                 "/admin/settings/event-terms/1/delete"):
        assert client.post(path).status_code in (401, 503), path
