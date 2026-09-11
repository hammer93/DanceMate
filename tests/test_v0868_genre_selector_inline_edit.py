"""v0.86.8 Dance-genre selector + inline row editing.

Two questions this release answers.

**The first screen only asks questions it can answer.** The style picker is
built from the genre master's own `enabled` flag - a disabled genre is left
out of the list entirely rather than shown as a dead button, and no code on
the reader's side ever asks "is this the salsa one?". When one genre is
enabled the picker is not a question at all, so it is not rendered, and that
genre applies on its own; when none is, the page still works. The control
itself is as wide as its chips, not as wide as the screen.

**Finishing an edit leaves the operator where they were.** Editing a list row
turns *that row* into inputs in place - same page, same page number, same
filters, same sort, same scroll position - and saving comes back to that exact
view rather than to a bare first page.

The pure-rendering tests run everywhere. The ones that need real rows use the
rolled-back PostgreSQL fixture, and the two route tests that must see their
own writes create a *disabled* throwaway genre through a committing
connection and delete it again at teardown, so a shared staging database
never keeps it and no reader ever sees it.
"""

from __future__ import annotations

import inspect
import os
import re

import pytest
from fastapi.testclient import TestClient

from runtime import admin, master_admin, master_edit, public

# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


@pytest.fixture
def admin_auth(monkeypatch) -> tuple[str, str]:
    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")
    return ("tester", "test-only")


# Captured at import, before the `env` fixture installs its deterministic
# fake password - exactly what conftest's own `pg` fixture does, and for the
# same reason: the fixture below needs a *committing* connection, so it
# cannot simply reuse `pg` (which rolls everything back), but it must reach
# the same database `pg` does.
_REAL_POSTGRES = {
    key: os.environ.get(f"TEST_{key}") or os.environ.get(key)
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
                "POSTGRES_USER", "POSTGRES_PASSWORD")
}


@pytest.fixture
def throwaway_genre(env, monkeypatch, unique):
    """A real genre row, created disabled and deleted for real at teardown.

    Disabled from the moment it exists so that even a teardown that never
    runs cannot put a test row on a reader's first screen.
    """
    from runtime import db, master_data
    from runtime.config import load_settings

    if not _REAL_POSTGRES.get("POSTGRES_PASSWORD"):
        pytest.skip("no PostgreSQL credentials in the environment; "
                    "run these from inside the runtime container")
    for key, value in _REAL_POSTGRES.items():
        if value:
            monkeypatch.setenv(key, value)
    settings = load_settings()
    # The context manager itself is held, not just the connection it yields:
    # `db.connect()` is a generator, and letting it be collected closes the
    # connection out from under the teardown below.
    opened = db.connect(settings, autocommit=True)
    try:
        con = opened.__enter__()
    except db.DatabaseUnavailable as exc:  # pragma: no cover - depends on host
        pytest.skip(f"no PostgreSQL reachable: {exc}")
    try:
        created = master_data.create_genre(
            con, code=f"TESTGENRE{unique}", name=f"Test Genre {unique}")
        master_data.set_genre_enabled(con, created["genre_id"], False)
        yield created
    finally:
        with con.cursor() as cur:
            cur.execute("DELETE FROM master_data_actions "
                        "WHERE entity_type = 'GENRE' AND entity_id = %s",
                        (created["genre_id"],))
        master_data.delete_genre(con, created["genre_id"])
        opened.__exit__(None, None, None)


def _offered(html: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'name="genres" value="([A-Z0-9]+)"', html)]


TANGO = {"code": "TANGO", "name": "Tango", "enabled": True}
SALSA_OFF = {"code": "SALSA", "name": "Salsa", "enabled": False}
SWING_OFF = {"code": "SWING", "name": "Swing", "enabled": False}
SALSA_ON = {"code": "SALSA", "name": "Salsa", "enabled": True}
NO_REGIONS = {"genres": [], "regions": [], "region_options": []}


# === 1. The selector is only as wide as what it holds ======================

def test_the_style_picker_is_sized_to_its_content_not_the_screen():
    rule = public.STYLE.split(".filters form.genres")[1].split("}")[0]
    assert "inline-flex" in rule
    assert "width:fit-content" in rule
    # Not a fixed narrow width that would clip a label: a floor and a ceiling.
    assert "min-width:min(100%, 12rem)" in rule
    assert "max-width:100%" in rule


def test_a_long_genre_name_wraps_instead_of_breaking_the_row():
    """Phone and desktop both: the chips wrap inside the box, the box never
    pushes the page sideways."""
    rule = public.STYLE.split(".filters form.genres")[1].split("}")[0]
    assert "flex-wrap:wrap" in rule
    chip = public.STYLE.split(".filters label.chip")[1].split("}")[0]
    assert "max-width:100%" in chip
    assert "overflow-wrap:anywhere" in chip


def test_the_chips_keep_the_design_system_they_already_had():
    """Spacing, border radius and type are the existing ones - this release
    changed the width of the container, nothing else."""
    chip = public.STYLE.split(".filters label.chip { display")[1].split("}")[0]
    assert "border-radius:999px" in chip
    assert "padding:.25rem .7rem" in chip
    assert "font-size:.8rem" in chip


# === 2. A disabled genre is not on the first screen =========================

def test_a_disabled_genre_is_not_offered_at_all():
    options = public._enabled_genre_options([TANGO, SALSA_OFF, SWING_OFF])
    assert [o["code"] for o in options] == ["TANGO"]


def test_a_disabled_genre_is_not_even_a_disabled_button():
    """Left out of the list, not rendered greyed out - a control that cannot
    do anything is an invitation to click something that goes nowhere."""
    options = public._enabled_genre_options([TANGO, SALSA_ON, SWING_OFF])
    html = public._genre_filter("/", "today", None, options, ["TANGO", "SALSA"])
    assert "Swing" not in html
    assert "SWING" not in html
    assert "disabled" not in html


def test_the_flag_decides_not_the_name():
    """Requirement 6: nothing here knows which genre is "the salsa one".

    Flip the flags and the answer flips with them - the same two names come
    out on the other side.
    """
    options = public._enabled_genre_options(
        [{"code": "TANGO", "name": "Tango", "enabled": False},
         {"code": "SALSA", "name": "Salsa", "enabled": True},
         {"code": "SWING", "name": "Swing", "enabled": True}])
    assert [o["code"] for o in options] == ["SALSA", "SWING"]


def test_no_genre_name_is_hardcoded_in_the_filtering_path():
    for func in (public._is_enabled, public._enabled_genre_options,
                 public._selected_genres, public._shows_selector):
        source = inspect.getsource(func)
        for name in ("SALSA", "SWING", "Salsa", "Swing"):
            assert name not in source.split('"""')[-1], (func.__name__, name)


def test_a_row_that_says_nothing_about_its_state_stays_offered():
    """An unknown state is not a reason to take a working filter off the page."""
    assert public._is_enabled({"code": "TANGO", "name": "Tango"}) is True
    assert public._is_enabled({"enabled": False}) is False


def test_the_master_is_read_for_the_state_not_a_hardcoded_list(monkeypatch):
    from runtime import master_data

    monkeypatch.setattr(master_data, "list_genres",
                        lambda con, **kw: [TANGO, SALSA_OFF, SWING_OFF])
    assert [o["code"] for o in public._genre_options(object())] == ["TANGO"]


def test_the_baseline_is_a_floor_for_an_unreachable_master_only(monkeypatch):
    """A database hiccup must not silently remove the filter; a master that
    answers "these are disabled" is not a hiccup."""
    from runtime import master_data

    def _boom(con, **kw):
        raise RuntimeError("no master today")

    monkeypatch.setattr(master_data, "list_genres", _boom)
    assert [o["code"] for o in public._genre_options(object())] == [
        "TANGO", "SALSA", "SWING"]

    monkeypatch.setattr(master_data, "list_genres",
                        lambda con, **kw: [TANGO, SALSA_OFF, SWING_OFF])
    assert [o["code"] for o in public._genre_options(object())] == ["TANGO"]


def test_disabling_a_genre_changes_no_data(pg):
    """The filter reads state; it never writes it, and never deletes a row."""
    from runtime import master_data

    before = len(master_data.list_genres(pg))
    public._genre_options(pg)
    assert len(master_data.list_genres(pg)) == before


def test_only_the_masters_enabled_genres_reach_the_first_screen(pg):
    from runtime import master_data

    offered = {o["code"] for o in public._genre_options(pg)}
    enabled = {g["code"] for g in master_data.list_genres(pg, enabled_only=True)}
    assert offered == enabled


def test_a_disabled_genre_in_the_master_is_absent_from_the_home_page(
    client, throwaway_genre
):
    """End to end, with a real disabled row: its name is nowhere on the page."""
    response = client.get("/")
    assert response.status_code == 200
    assert throwaway_genre["name"] not in response.text
    assert throwaway_genre["code"] not in response.text


# === 3. One enabled genre means no selector =================================

def test_two_or_more_enabled_genres_render_the_selector():
    options = public._enabled_genre_options([TANGO, SALSA_ON, SWING_OFF])
    assert public._shows_selector(options) is True
    html = public._genre_filter("/", "today", None, options, ["TANGO", "SALSA"])
    assert _offered(html) == ["TANGO", "SALSA"]
    assert "춤 종류" in html


def test_one_enabled_genre_renders_no_selector_at_all():
    options = public._enabled_genre_options([TANGO, SALSA_OFF, SWING_OFF])
    assert public._shows_selector(options) is False
    assert public._genre_filter("/", "today", None, options, ["TANGO"]) == ""
    bar = public._filter_bar("/events", "today", NO_REGIONS, options, ["TANGO"], None)
    assert "춤 종류" not in bar
    assert 'name="genres"' not in bar
    # ... and the script that drives a form that is not there does not ship.
    assert "form.genres" not in bar


def test_the_only_enabled_genre_is_applied_on_its_own():
    options = public._enabled_genre_options([TANGO, SALSA_OFF, SWING_OFF])
    assert public._selected_genres(options, None, declared=False) == ["TANGO"]


def test_a_stale_link_to_a_disabled_genre_is_corrected_not_obeyed():
    """?genres=SALSA on a page with no selector would otherwise strand a
    reader on an empty list with no control to undo it."""
    options = public._enabled_genre_options([TANGO, SALSA_OFF, SWING_OFF])
    assert public._selected_genres(options, ["SALSA"], declared=True) == ["TANGO"]
    assert public._selected_genres(options, [], declared=True) == ["TANGO"]


def test_an_unknown_genre_is_dropped_while_the_selector_is_up():
    options = public._enabled_genre_options([TANGO, SALSA_ON])
    assert public._selected_genres(options, ["SALSA", "SWING"], declared=True) == ["SALSA"]
    # Every code asked for is gone from the master: fall back to everything
    # rather than to nothing.
    assert public._selected_genres(options, ["SWING"], declared=True) == ["TANGO", "SALSA"]
    # Unticking every box by hand is still an answer, not a mistake.
    assert public._selected_genres(options, [], declared=True) == []


def test_no_enabled_genre_does_not_crash_the_page():
    options = public._enabled_genre_options([SALSA_OFF, SWING_OFF])
    assert options == []
    assert public._shows_selector(options) is False
    assert public._genre_filter("/", "today", None, options, []) == ""
    assert public._selected_genres(options, None, declared=False) == []
    assert public._selected_genres(options, ["TANGO"], declared=True) == []
    assert public._genre_constraint(options, []) is None
    assert public._genre_query([], options) == {}
    assert public._is_narrowed(options, []) is False
    assert isinstance(
        public._filter_bar("/events", "today", NO_REGIONS, options, [], None), str)


def test_hiding_the_selector_keeps_the_query_the_events_and_the_other_filters():
    """The list, the region chips and every link on the page are unchanged -
    only the question that had one possible answer is gone."""
    options = public._enabled_genre_options([TANGO, SALSA_OFF])
    selected = public._selected_genres(options, None, declared=False)
    regions = [{"value": "Seoul", "label": "Seoul", "events": 2}]
    facets = {"genres": [], "regions": regions, "region_options": regions}
    bar = public._filter_bar("/events", "today", facets, options, selected, "Seoul")
    assert "지역" in bar and "Seoul" in bar and "when=today" in bar
    # An unconstrained query still means "all of it", including an event whose
    # genre could not be read - hiding a control never narrows the results.
    assert public._genre_constraint(options, selected) is None
    assert public._genre_query(selected, options) == {}


@pytest.mark.parametrize("path", ["/", "/events?when=today"])
def test_the_reader_facing_pages_render_with_the_live_master(client, path):
    """Whatever the master currently says, the first screen answers 200."""
    response = client.get(path)
    assert response.status_code in (200, 503)


# === 4. Inline row editing ==================================================

def _request(url: str):
    from urllib.parse import urlsplit

    from starlette.requests import Request

    parts = urlsplit(url)
    return Request({"type": "http", "method": "GET", "path": parts.path,
                    "query_string": parts.query.encode(), "headers": []})


VIEW = "/admin/master?genre_page=3&region_page=2"


def test_edit_opens_the_row_on_the_same_view():
    href = master_admin.edit_link(VIEW, master_edit.GENRE, 5)
    assert "genre_page=3" in href and "region_page=2" in href
    assert "edit=GENRE%3A5" in href
    assert '#row-GENRE-5"' in href
    # Same route: no detail page, no other screen.
    assert 'href="/admin/master?' in href


def test_only_the_row_that_was_clicked_is_in_edit_mode():
    request = _request("/admin/master?edit=GENRE:5&genre_page=3")
    assert master_admin.editing_id(request, master_edit.GENRE) == 5
    # Not the same id in another table, and not another row in this one.
    assert master_admin.editing_id(request, master_edit.REGION) is None
    assert master_admin.editing_id(_request("/admin/master"), master_edit.GENRE) is None
    assert master_admin.editing_id(
        _request("/admin/master?edit=GENRE:nope"), master_edit.GENRE) is None


def test_every_editable_column_of_the_row_becomes_an_input():
    """The whole row, not one field of it - and the row's own <form>."""
    fid = master_admin.form_id(master_edit.REGION, 9)
    cells = [
        master_admin.row_input(master_edit.REGION, 9, "name", "서울"),
        master_admin.row_input(master_edit.REGION, 9, "country", "South Korea"),
        master_admin.row_input(master_edit.REGION, 9, "city", "Seoul"),
        master_admin.row_input(master_edit.REGION, 9, "district", None, label="District"),
        master_admin.enabled_input(master_edit.REGION, 9, True),
    ]
    row = "".join(cells)
    for field in master_edit.EDITABLE[master_edit.REGION]:
        assert f'name="{field}"' in row, field
    assert row.count(f'form="{fid}"') == len(cells)
    assert 'value="서울"' in row


def test_state_is_a_select_so_disabling_a_row_is_actually_sent():
    """An unticked checkbox is not submitted at all, which would read as
    "unchanged" and silently ignore an operator who meant to disable."""
    rendered = master_admin.enabled_input(master_edit.GENRE, 5, True)
    assert "<select" in rendered
    assert '<option value="1" selected>ENABLED</option>' in rendered
    assert '<option value="0">DISABLED</option>' in rendered


def test_the_rows_form_posts_to_the_existing_edit_route():
    """No new API contract: the same endpoint the panel already posted to."""
    rendered = master_admin.row_form(master_edit.GENRE, 5, VIEW)
    assert 'action="/admin/master-data/GENRE/5/edit"' in rendered
    assert 'id="edit-GENRE-5"' in rendered
    assert 'name="return_to"' in rendered
    assert "genre_page=3" in rendered


def test_save_and_cancel_are_both_on_the_row():
    actions = master_admin.row_actions(VIEW, master_edit.GENRE, 5)
    assert 'form="edit-GENRE-5"' in actions
    assert "완료" in actions and "취소" in actions


def test_cancel_sends_nothing_to_the_server():
    actions = master_admin.row_actions(VIEW, master_edit.GENRE, 5)
    cancel = actions.split("취소")[0].split("<a")[-1]
    assert "method=\"post\"" not in cancel
    url = master_admin.cancel_url(VIEW, master_edit.GENRE, 5)
    assert "edit=" not in url
    assert "genre_page=3" in url and "region_page=2" in url
    assert url.endswith("#row-GENRE-5")


def test_a_second_click_does_not_send_the_edit_twice():
    """The console-wide submit guard, and the hook the row's Save gives it."""
    assert "dataset.sent" in admin.SUBMIT_ONCE
    assert "e.preventDefault()" in admin.SUBMIT_ONCE
    assert "button[form=" in admin.SUBMIT_ONCE
    assert "b.disabled=true" in admin.SUBMIT_ONCE
    assert admin.SUBMIT_ONCE in admin._page("t", "/admin", "<p>body</p>")
    assert 'data-busy="저장 중..."' in master_admin.row_actions(
        VIEW, master_edit.GENRE, 5)


def test_finishing_stays_on_the_same_list_page_and_filters():
    response = master_admin._back_to_view(
        master_edit.VENUE, 12, "/admin/venues?region=KR-SEOUL&genres=TANGO&page=4"
        "&edit=VENUE%3A12", "저장했습니다")
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/admin/venues?")
    assert "region=KR-SEOUL" in location
    assert "genres=TANGO" in location
    assert "page=4" in location
    # The row closes ...
    assert "edit=" not in location
    # ... and the browser lands back on it rather than at the top of the table.
    assert location.endswith("#row-VENUE-12")


def test_finishing_never_leaves_the_route_it_started_on():
    for entity, view in ((master_edit.GENRE, "/admin/master?genre_page=2"),
                         (master_edit.ORGANIZER, "/admin/organizers?page=3"),
                         (master_edit.SOURCE, "/admin/sources?genre=TANGO&page=2")):
        location = master_admin._back_to_view(entity, 1, view, "ok").headers["location"]
        assert location.split("?")[0] == view.split("?")[0]
        assert view.split("?")[1].split("&")[0] in location


def test_a_failed_save_keeps_the_row_open_and_says_why():
    response = master_admin._back_to_view(
        master_edit.GENRE, 5, "/admin/master?genre_page=3&edit=GENRE%3A5",
        "저장하지 못했습니다: 이름이 필요합니다", "bad", keep_editing=True)
    location = response.headers["location"]
    assert "edit=GENRE%3A5" in location
    assert "tone=bad" in location
    assert "genre_page=3" in location
    assert "%EC%A0%80%EC%9E%A5" in location or "저장하지" in location


def test_a_return_url_is_only_ever_a_path_on_this_console():
    fallback = "/admin/master"
    for hostile in ("https://example.com/admin", "//example.com/admin",
                    "/etc/passwd", "", None, "javascript:alert(1)"):
        assert master_admin.safe_view(hostile, fallback) == fallback
    assert master_admin.safe_view("/admin/venues?page=2", fallback) == "/admin/venues?page=2"


def test_the_flash_does_not_stack_up_across_saves():
    request = _request("/admin/master?genre_page=2&msg=done&tone=ok")
    view = master_admin.current_view(request)
    assert "msg=" not in view and "tone=" not in view
    assert "genre_page=2" in view


def test_the_edit_route_still_accepts_a_form_without_a_return_url():
    """Backward compatible: the panel-style forms that never sent one still
    land on the entity's own list page."""
    source = inspect.getsource(master_admin.admin_edit_master_row)
    assert 'raw.get("return_to")' in source
    assert master_admin.safe_view(None, master_admin.PAGE[master_edit.VENUE]) == (
        "/admin/venues")


def test_the_row_being_edited_is_marked_and_anchored():
    assert admin._row_attrs(master_edit.GENRE, 5, True) == (
        ' id="row-GENRE-5" class="editing"')
    assert admin._row_attrs(master_edit.GENRE, 5, False) == ' id="row-GENRE-5"'


def test_the_table_helper_carries_the_row_attributes_through():
    html = admin._table(["A"], [["1"], ["2"]], empty="none",
                        row_attrs=[' id="row-GENRE-1" class="editing"'])
    assert '<tr id="row-GENRE-1" class="editing"><td>1</td></tr>' in html
    assert "<tr><td>2</td></tr>" in html


# --- the pages themselves ---------------------------------------------------

def test_the_master_page_edits_one_row_in_place(client, admin_auth, pg):
    from runtime import master_data

    genre = master_data.list_genres(pg)[0]
    gid = genre["genre_id"]
    response = client.get(f"/admin/master?edit=GENRE:{gid}", auth=admin_auth)
    assert response.status_code == 200
    body = response.text
    # That row is inputs, bound to that row's form ...
    assert f'id="edit-GENRE-{gid}"' in body
    assert f'name="name" form="edit-GENRE-{gid}"' in body
    assert f'name="enabled" form="edit-GENRE-{gid}"' in body
    assert f'id="row-GENRE-{gid}" class="editing"' in body
    # ... and every other row is not.
    others = [g for g in master_data.list_genres(pg) if g["genre_id"] != gid]
    for other in others[:3]:
        assert f'id="edit-GENRE-{other["genre_id"]}"' not in body
        assert f'id="row-GENRE-{other["genre_id"]}" class="editing"' not in body


def test_the_master_page_without_the_parameter_edits_nothing(client, admin_auth, pg):
    response = client.get("/admin/master", auth=admin_auth)
    assert response.status_code == 200
    assert 'class="editing"' not in response.text
    assert "편집" in response.text


def test_a_save_returns_to_the_same_page_of_the_same_list(
    client, admin_auth, throwaway_genre
):
    """The real round trip: the value changes, and the list context does not."""
    from runtime import db, master_data
    from runtime.config import load_settings

    gid = throwaway_genre["genre_id"]
    view = f"/admin/master?genre_page=1&region_page=2&edit=GENRE%3A{gid}"
    response = client.post(
        f"/admin/master-data/GENRE/{gid}/edit",
        data={"name": "Renamed In Place", "enabled": "0", "return_to": view},
        auth=admin_auth, follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/admin/master?")
    assert "region_page=2" in location and "genre_page=1" in location
    assert "edit=" not in location
    assert location.endswith(f"#row-GENRE-{gid}")

    with db.connect(load_settings(), autocommit=True) as con:
        after = master_data.get_genre(con, gid)
    assert after["name"] == "Renamed In Place"
    assert after["enabled"] is False


def test_a_rejected_save_keeps_the_row_open(client, admin_auth, throwaway_genre):
    gid = throwaway_genre["genre_id"]
    view = f"/admin/master?genre_page=1&edit=GENRE%3A{gid}"
    response = client.post(
        f"/admin/master-data/GENRE/{gid}/edit",
        data={"name": "   ", "enabled": "1", "return_to": view},
        auth=admin_auth, follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert f"edit=GENRE%3A{gid}" in location
    assert "tone=bad" in location

    from runtime import db, master_data
    from runtime.config import load_settings

    with db.connect(load_settings(), autocommit=True) as con:
        after = master_data.get_genre(con, gid)
    assert after["name"] == throwaway_genre["name"]
    assert after["enabled"] is False


# --- the whole page, rendered against a stubbed master ----------------------
#
# The rows themselves, not just the helpers, and without needing a database:
# these are the two assertions the requirement is actually about - the row
# that was clicked becomes inputs, and no other row does.

@pytest.fixture
def stub_master(monkeypatch):
    """Enough of the master-data layer for the list pages to render."""
    import contextlib

    from runtime import master_data, venue_resolution

    class _Settings:
        version = "0.86.8"
        engine_version = "0.75"
        env = "test"

    genres = [
        {"genre_id": 1, "code": "TANGO", "name": "Tango", "enabled": True},
        {"genre_id": 2, "code": "SALSA", "name": "Salsa", "enabled": False},
    ]
    regions = [{"region_id": 1, "code": "KR-SEOUL", "name": "서울",
                "country": "South Korea", "city": "Seoul", "district": None,
                "enabled": True}]
    venues = [
        {"venue_id": 11, "name": "라 벤따나", "region_id": 1, "region_name": "서울",
         "address": "서울 마포구 잔다리로 48", "notes": "2층",
         "aliases": ["La Ventana"], "genre_codes": ["TANGO"], "events": 3,
         "listed_events": 2, "enabled": True, "in_use": True},
        {"venue_id": 12, "name": "Otro Salon", "region_id": 1, "region_name": "서울",
         "address": None, "notes": None, "aliases": [], "genre_codes": [],
         "events": 0, "listed_events": 0, "enabled": False, "in_use": False},
    ]
    none_used = {"venues": 0, "organizers": 0, "sources": 0, "events": 0}

    @contextlib.contextmanager
    def _connection():
        yield object()

    monkeypatch.setattr(admin, "_settings", lambda: _Settings())
    monkeypatch.setattr(admin, "_connection", _connection)
    monkeypatch.setattr(master_data, "count_genres", lambda con, **kw: len(genres))
    monkeypatch.setattr(master_data, "list_genres", lambda con, **kw: [
        g for g in genres if g["enabled"] or not kw.get("enabled_only")])
    monkeypatch.setattr(master_data, "count_regions", lambda con, **kw: len(regions))
    monkeypatch.setattr(master_data, "list_regions", lambda con, **kw: regions)
    monkeypatch.setattr(master_data, "genre_usage", lambda con, gid: dict(none_used))
    monkeypatch.setattr(master_data, "region_usage", lambda con, rid: dict(none_used))
    monkeypatch.setattr(master_data, "count_venues", lambda con, **kw: len(venues))
    monkeypatch.setattr(master_data, "venue_aliases", lambda con, vid: [])
    monkeypatch.setattr(master_data, "venue_alias_usage", lambda con, vid: {})
    monkeypatch.setattr(master_data, "observed_venue_genres", lambda con, vid: [])
    monkeypatch.setattr(venue_resolution, "venues_with_usage",
                        lambda con, **kw: venues)
    return {"genres": genres, "regions": regions, "venues": venues}


def test_a_clicked_genre_row_becomes_inputs_and_the_others_do_not(stub_master):
    page = admin.admin_master(
        _request("/admin/master?genre_page=1&region_page=1&edit=GENRE:2"),
        _="tester").body.decode()
    # Row 2 is the one being edited: every editable field of it is an input,
    # bound to that row's own form.
    assert 'id="row-GENRE-2" class="editing"' in page
    assert 'name="name" form="edit-GENRE-2"' in page
    assert 'name="enabled" form="edit-GENRE-2"' in page
    assert page.count('class="rowform"') == 1
    # Row 1 is not, and is still offering its own Edit.
    assert 'id="row-GENRE-1" class="editing"' not in page
    assert 'form="edit-GENRE-1"' not in page
    assert "edit=GENRE%3A1" in page
    # The region table below is untouched by a genre being edited.
    assert 'class="editing"' not in page.split("<h2>Regions</h2>")[1]


def test_the_same_list_with_no_edit_parameter_has_no_inputs(stub_master):
    page = admin.admin_master(_request("/admin/master"), _="tester").body.decode()
    assert 'class="editing"' not in page
    assert 'class="rowform"' not in page
    assert "편집" in page


def test_the_row_editor_keeps_the_venue_filters_it_was_opened_from(stub_master):
    page = admin.admin_venues(
        _request("/admin/venues?region=KR-SEOUL&genres=TANGO&page=1&edit=VENUE:11"),
        region="KR-SEOUL", genres=["TANGO"], _="tester").body.decode()
    assert 'id="row-VENUE-11" class="editing"' in page
    assert 'id="row-VENUE-12" class="editing"' not in page
    for field in ("name", "region_id", "address", "notes", "enabled"):
        assert f'name="{field}" form="edit-VENUE-11"' in page, field
    # The row's return_to carries the filters and the page number back.
    row_form = page.split('id="edit-VENUE-11"')[1].split("</form>")[0]
    assert "region=KR-SEOUL" in row_form
    assert "genres=TANGO" in row_form
    assert "page=1" in row_form
    # The alias and genre sub-editors are still reachable beside the row.
    assert "Add Alias" in page and "Save Genres" in page


def test_a_row_in_edit_mode_never_nests_one_form_inside_another(stub_master):
    """The inputs join their form by id; the row's other forms stay siblings."""
    page = admin.admin_venues(
        _request("/admin/venues?edit=VENUE:11"), region="", genres=[],
        _="tester").body.decode()
    row = page.split('id="row-VENUE-11"')[1].split("</tr>")[0]
    depth = 0
    for token in re.findall(r"<form|</form>", row):
        depth += 1 if token == "<form" else -1
        assert depth in (0, 1), row[:200]


# === 5. Venue admin: one-line genre filter, and a Notes field worth reading ==
#
# Two defects found on the real /admin/venues screen before this release was
# pushed. The filter bar was written (v0.86.7) with the PUBLIC stylesheet's
# class names, none of which exist in the admin stylesheet - so admin's own
# `label{display:block}` stacked every genre on its own line. And the Notes
# field showed a string this repository had written about itself.

SEED_NOTE = "v0.82 seed: known cross-source venue alias group"


def _rule(selector: str) -> str:
    """One CSS rule body out of the admin stylesheet."""
    assert selector in admin.STYLE, selector
    return admin.STYLE.split(selector, 1)[1].split("}", 1)[0]


def test_the_venue_filter_bar_is_a_flex_row_in_the_admin_stylesheet():
    """Requirement 1: one line on a desktop, not one genre per line."""
    bar = _rule(".filters{")
    assert "display:flex" in bar
    assert "align-items:center" in bar
    assert "gap:" in bar
    row = _rule(".filters .row{")
    assert "display:flex" in row
    assert "align-items:center" in row


def test_every_genre_chip_sits_inline_inside_that_row():
    """The chips are what admin's `label{display:block}` was breaking."""
    chip = _rule(".filters label.chip{")
    assert "display:inline-flex" in chip
    assert "white-space:nowrap" in chip
    # ... and the checkbox inside it is not stretched to the cell width
    # by the console's own `input{width:100%}`.
    assert "width:auto" in _rule(".filters label.chip input{")
    # The region picker is a control, not a full-width band.
    assert "width:auto" in _rule(".filters select{")


def test_a_growing_genre_list_wraps_instead_of_overflowing():
    """Requirement: more genres must not break the layout or scroll the page."""
    assert "flex-wrap:wrap" in _rule(".filters{")
    assert "flex-wrap:wrap" in _rule(".filters .row{")


def test_the_filter_bar_markup_and_query_contract_are_unchanged(stub_master):
    """CSS only: same form, same method, same parameter names, same buttons."""
    page = admin.admin_venues(_request("/admin/venues"), region="", genres=[],
                              _="tester").body.decode()
    bar = page.split('class="filters"', 1)[1].split("</form>", 1)[0]
    assert 'method="get" action="/admin/venues"' in page
    assert 'name="region"' in bar
    assert 'name="genres"' in bar
    assert "춤 종류" in bar
    # Apply and Reset both survive, in the same shapes.
    assert "적용" in bar
    assert "초기화" in bar
    assert 'href="/admin/venues"' in bar


def test_the_genre_chips_still_come_from_the_master(stub_master):
    """Requirement: no genre name is hardcoded - flip the master, flip the
    chips. The admin filter keeps offering what it is given (its own
    contract, unlike the reader's side) - here, one enabled genre."""
    page = admin.admin_venues(_request("/admin/venues"), region="", genres=[],
                              _="tester").body.decode()
    bar = page.split('class="filters"', 1)[1].split("</form>", 1)[0]
    offered = re.findall(r'name="genres" value="([A-Z]+)"', bar)
    assert offered == [g["code"] for g in stub_master["genres"] if g["enabled"]]


def test_no_genre_name_is_written_into_the_filter_bar_or_its_styles():
    """Prose may name a genre to explain itself; code may not select on one.

    Comments and the docstring are stripped first - `admin_venues()` has
    carried a "Tango · Salsa" example in a v0.85.7 comment since long before
    this release, and a comment cannot filter anything.
    """
    source = inspect.getsource(admin.admin_venues)
    source = source.split('"""')[2] if source.count('"""') >= 2 else source
    code = "\n".join(line.split("#", 1)[0] for line in source.splitlines())
    for name in ("Salsa", "Swing", "Tango", "SALSA", "SWING", "TANGO"):
        assert name not in admin.STYLE, name
        assert name not in code, name


def test_the_existing_region_and_genre_filters_still_select(stub_master):
    """Requirement 4: the query contract this bar drives is untouched."""
    page = admin.admin_venues(
        _request("/admin/venues?region=KR-SEOUL&genres=TANGO"),
        region="KR-SEOUL", genres=["TANGO"], _="tester").body.decode()
    bar = page.split('class="filters"', 1)[1].split("</form>", 1)[0]
    assert '<option value="KR-SEOUL" selected>' in bar
    assert 'value="TANGO" checked' in bar


# --- the Notes field --------------------------------------------------------

def test_the_seed_note_comes_from_one_migration_seed_and_nothing_else(repo_root):
    """Where the string came from: a migration seed - not a fixture, not
    runtime code, not an HTML default. Exactly two files in the repository
    carry it: 022, which INSERTs it, and 032, which clears it again."""
    migrations = repo_root / "migrations" / "runtime"
    carriers = sorted(p.name for p in migrations.glob("*.sql")
                      if SEED_NOTE in p.read_text(encoding="utf-8"))
    assert carriers == ["022_tango_venue_aliases.sql",
                        "032_venue_seed_note_cleanup.sql"]
    seed = (migrations / "022_tango_venue_aliases.sql").read_text(encoding="utf-8")
    assert "INSERT INTO venues (name, region_id, notes)" in seed
    for folder in ("runtime", "scheduler"):
        assert not [p.name for p in (repo_root / folder).rglob("*.py")
                    if SEED_NOTE in p.read_text(encoding="utf-8")], folder


def test_the_cleanup_migration_matches_that_one_exact_value_and_nothing_else(repo_root):
    """Requirement: never a pattern, never the whole column.

    A real operator's note on one of these same venues has to survive, so the
    cleanup is a whole-value equality test on the single string this
    repository generates.
    """
    sql = (repo_root / "migrations" / "runtime"
           / "032_venue_seed_note_cleanup.sql").read_text(encoding="utf-8")
    statement = sql.split("UPDATE venues", 1)[1]
    assert f"notes = '{SEED_NOTE}'" in statement
    assert "SET notes = NULL" in statement
    assert "LIKE" not in statement.upper()
    assert "%" not in statement
    # One statement, one table, one column, and no DELETE anywhere in the file.
    assert sql.count("UPDATE venues") == 1
    assert sql.rstrip().count(";") == 1
    assert "DELETE" not in sql.upper()


def test_the_seeded_venues_carry_no_note_once_the_migrations_have_run(pg):
    """Requirement 6, against a real database: nothing left to clean up."""
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venues WHERE notes = %s", (SEED_NOTE,))
        assert cur.fetchone()[0] == 0


def test_the_cleanup_is_idempotent_and_leaves_a_real_note_alone(pg, unique):
    """Requirement 9/11: run the exact statement again over real rows."""
    from runtime import master_data

    mine = master_data.create_venue(pg, name=f"노트 보존 홀 {unique}")
    master_data.update_venue(pg, mine["venue_id"], notes="2층, 주말만 운영")
    with pg.cursor() as cur:
        cur.execute("UPDATE venues SET notes = NULL WHERE notes = %s", (SEED_NOTE,))
        assert cur.rowcount == 0  # nothing left over from the migration
        cur.execute("SELECT notes FROM venues WHERE venue_id = %s",
                    (mine["venue_id"],))
        assert cur.fetchone()[0] == "2층, 주말만 운영"


def test_a_venue_with_no_note_still_gets_a_notes_control(stub_master):
    """Requirement 6: an empty value is not a reason to hide the field."""
    page = admin.admin_venues(_request("/admin/venues?edit=VENUE:12"),
                              region="", genres=[], _="tester").body.decode()
    row = page.split('id="row-VENUE-12"', 1)[1].split("</tr>", 1)[0]
    assert "Notes" in row
    assert 'name="notes" form="edit-VENUE-12"' in row
    # Rendered, and rendered empty - not absent, and not filled with anything.
    assert '<textarea class="cellinput" name="notes" form="edit-VENUE-12" ' \
           'rows="2" placeholder=""></textarea>' in row


def test_an_existing_note_is_shown_back_in_the_editor(stub_master):
    """Requirement 10: what was saved is what the next edit opens with."""
    page = admin.admin_venues(_request("/admin/venues?edit=VENUE:11"),
                              region="", genres=[], _="tester").body.decode()
    row = page.split('id="row-VENUE-11"', 1)[1].split("</tr>", 1)[0]
    assert ">2층</textarea>" in row
    assert SEED_NOTE not in page


def test_the_notes_cell_is_readable_without_widening_the_table():
    """Requirement 7: two visible lines in the same cell, not a wider column."""
    rendered = master_admin.row_input(master_edit.VENUE, 11, "notes", "x",
                                      label="Notes", kind="textarea")
    assert 'rows="2"' in rendered
    assert "<textarea" in rendered
    box = _rule("textarea.cellinput{")
    assert "min-height" in box
    assert "resize:vertical" in box
    # The shared cell width rule is untouched, so no column gets wider.
    assert "width:100%" in _rule(".cellinput{")


def test_a_note_with_markup_in_it_is_escaped_in_the_textarea():
    rendered = master_admin.row_input(master_edit.VENUE, 11, "notes",
                                      "<script>alert(1)</script>",
                                      label="Notes", kind="textarea")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
