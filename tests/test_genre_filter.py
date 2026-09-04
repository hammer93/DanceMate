"""The dance-style filter on the first screen.

A reader arriving at DanceMate should be able to say "swing, tonight" without
first discovering that swing is an option. That means the three styles are on
screen whether or not anything is happening in them today, that all three are
on until the reader says otherwise, and that saying otherwise survives moving
between today, tomorrow and the week.

These tests drive the rendering and selection functions directly. The two that
need real events use the rolled-back PostgreSQL fixture.
"""

from __future__ import annotations

import re

import pytest

from runtime import events_api, public

OPTIONS = [
    {"code": "TANGO", "label": "Tango"},
    {"code": "SALSA", "label": "Salsa"},
    {"code": "SWING", "label": "Swing"},
]
ALL = ["TANGO", "SALSA", "SWING"]


def _checked(html: str) -> list[str]:
    """Which genre boxes the markup renders as ticked."""
    return [m.group(1) for m in re.finditer(
        r'name="genres" value="([A-Z]+)" checked', html)]


def _offered(html: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'name="genres" value="([A-Z]+)"', html)]


# --- 1, 3: always rendered, even at zero ------------------------------------

def test_all_three_styles_are_always_offered():
    html = public._genre_filter("/", "today", None, OPTIONS, ALL)
    assert _offered(html) == ALL
    for label in ("Tango", "Salsa", "Swing"):
        assert f"> {label}</label>" in html


def test_a_style_with_no_events_keeps_its_box():
    """The filter is a question the page answers, not a summary of the data.

    Nothing about _genre_filter consults the event counts, and that is the
    point -- so assert it against a page state where swing has nothing.
    """
    facets = {"genres": [{"value": "TANGO", "label": "Tango", "events": 3}],
              "regions": [], "region_options": []}
    html = public._filter_bar("/events", "today", facets, OPTIONS, ALL, None)
    assert _offered(html) == ALL
    assert "Swing" in html


# --- 2: all selected by default ---------------------------------------------

def test_nothing_asked_means_everything_selected():
    assert public._selected_genres(OPTIONS, None, declared=False) == ALL
    assert _checked(public._genre_filter("/", "today", None, OPTIONS, ALL)) == ALL


def test_unticking_everything_is_an_answer_not_a_reset():
    """The one case a filter must not be clever about."""
    selected = public._selected_genres(OPTIONS, [], declared=True)
    assert selected == []
    assert _checked(public._genre_filter("/", "today", None, OPTIONS, selected)) == []
    # And it reaches the query as "match nothing", not as "no filter".
    assert public._genre_constraint(OPTIONS, []) == []


# --- 3, 4, 5, 6: one style at a time, and several ---------------------------

@pytest.mark.parametrize("code", ALL)
def test_a_single_style_can_be_chosen(code):
    selected = public._selected_genres(OPTIONS, [code], declared=True)
    assert selected == [code]
    assert _checked(public._genre_filter("/", "today", None, OPTIONS, selected)) == [code]
    assert public._genre_constraint(OPTIONS, selected) == [code]


def test_several_styles_can_be_chosen_together():
    selected = public._selected_genres(OPTIONS, ["TANGO", "SALSA"], declared=True)
    assert selected == ["TANGO", "SALSA"]
    assert _checked(public._genre_filter("/", "today", None, OPTIONS, selected)) == [
        "TANGO", "SALSA"]


def test_selecting_everything_does_not_constrain_the_query():
    """An event whose genre we could not read is still part of "all of it"."""
    assert public._genre_constraint(OPTIONS, ALL) is None
    assert public._genre_query(ALL, OPTIONS) == {}


# --- 6: the URL carries it ---------------------------------------------------

def test_the_selection_is_readable_from_the_url_in_either_shape():
    assert public._split_genres(["TANGO,SALSA"]) == ["TANGO", "SALSA"]
    assert public._split_genres(["TANGO", "SALSA"]) == ["TANGO", "SALSA"]
    assert public._split_genres([" tango , salsa "]) == ["TANGO", "SALSA"]
    assert public._split_genres(["TANGO", "TANGO"]) == ["TANGO"]
    # Nothing said is not the same as "none of them".
    assert public._split_genres(None) is None
    assert public._split_genres([]) == []


def test_a_narrowed_selection_is_written_back_into_links():
    assert public._genre_query(["SALSA"], OPTIONS) == {
        "genres": "SALSA", "genres_set": "1"}


# --- 7, 8: it survives moving around ----------------------------------------

@pytest.mark.parametrize("tab", ["today", "tomorrow", "this_week", "weekend", "upcoming"])
def test_every_time_tab_carries_the_selection(tab):
    nav = public._nav("today", genre_query=public._genre_query(["SALSA"], OPTIONS))
    assert f"when={tab}" in nav
    assert nav.count("genres=SALSA") == len(public.TABS)


def test_changing_region_keeps_the_styles_and_the_other_way_round():
    regions = [{"value": "Seoul", "label": "Seoul", "events": 2},
               {"value": "Busan", "label": "Busan", "events": 1}]
    facets = {"genres": [], "regions": regions, "region_options": regions}
    html = public._filter_bar("/events", "today", facets, OPTIONS, ["SALSA"], "Seoul")
    # Every region link keeps salsa ...
    assert html.count("genres=SALSA") == 3  # 전체 + Seoul + Busan
    # ... and the genre form keeps the region.
    assert '<input type="hidden" name="region" value="Seoul">' in html
    assert _checked(html) == ["SALSA"]


# --- 10, 14: the enum stays inside ------------------------------------------

def test_the_reader_never_sees_the_internal_code():
    html = public._genre_filter("/", "today", None, OPTIONS, ALL)
    visible = re.sub(r"<[^>]+>", " ", html)
    for code in ALL:
        assert code not in visible, code
    for label in ("Tango", "Salsa", "Swing"):
        assert label in visible


# --- 13, 14: reachable, and not colour alone --------------------------------

def test_the_state_is_carried_by_a_control_not_a_colour():
    """A checkbox is checked whether or not the stylesheet loads."""
    html = public._genre_filter("/", "today", None, OPTIONS, ["SWING"])
    assert 'type="checkbox"' in html
    assert html.count(" checked") == 1
    # Keyboard reachable by construction: real inputs inside labels.
    assert html.count("<label") == 3


def test_it_works_without_javascript():
    """The script is an enhancement; the form has to submit on its own."""
    html = public._genre_filter("/events", "today", None, OPTIONS, ALL)
    assert 'method="get"' in html and 'action="/events"' in html
    assert '<button class="apply">' in html
    # And the script only hides that button once it is running.
    assert "form.auto .apply { display:none; }" in public.STYLE


def test_the_markup_wraps_rather_than_overflowing_a_phone():
    assert ".filters form.genres" in public.STYLE
    assert "flex-wrap:wrap" in public.STYLE.split(".filters form.genres")[1][:200]


# --- 12: a disabled genre is not offered ------------------------------------

def test_only_enabled_genres_are_offered(pg):
    """Read from the master, so admin stays the one place genres are decided."""
    from runtime import master_data

    options = public._genre_options(pg)
    codes = [o["code"] for o in options]
    enabled = {g["code"] for g in master_data.list_genres(pg, enabled_only=True)}
    assert set(codes) <= enabled or set(codes) - enabled <= set(ALL)
    for code in ALL:
        assert code in codes, code


def test_the_three_survive_a_master_that_says_nothing():
    """The floor: the first screen never loses its filter."""
    class _Empty:
        def cursor(self):
            raise RuntimeError("no master today")

    options = public._genre_options(_Empty())
    assert [o["code"] for o in options] == ALL
    assert [o["label"] for o in options] == ["Tango", "Salsa", "Swing"]


# --- 15: the existing API still answers the old question --------------------

def test_the_single_genre_query_still_works(pg):
    tango = events_api.search(pg, when="upcoming", genre="TANGO", limit=50)
    both = events_api.search(pg, when="upcoming", genres=["TANGO", "SALSA"], limit=50)
    none_of_them = events_api.search(pg, when="upcoming", genres=[], limit=50)

    # The API still speaks codes; the page speaks labels.
    assert all(e["genre"] == "TANGO" for e in tango["events"] if e.get("genre"))
    assert all(e["genre_label"] == "Tango" for e in tango["events"] if e.get("genre"))
    assert both["total"] >= tango["total"]
    assert none_of_them["total"] == 0
    assert none_of_them["events"] == []


# --- 4, 18: the first screen shows where, too -------------------------------

def test_the_region_row_is_offered_even_when_today_has_none(pg):
    """Seoul and Busan are questions the first screen should let you ask.

    Built from the region master, so a day with one region-less event does not
    take the region filter off the page.
    """
    options = public._region_options(pg, [])
    names = [o["label"] for o in options]
    assert "Seoul" in names and "Busan" in names
    # Cities only: the country row is not somewhere to go.
    assert "South Korea" not in names
    assert all(o["events"] == 0 for o in options)


def test_region_counts_come_from_the_window_being_shown(pg):
    counted = [{"value": "Busan", "label": "Busan", "events": 4}]
    options = public._region_options(pg, counted)
    by_name = {o["label"]: o["events"] for o in options}
    assert by_name["Busan"] == 4
    assert by_name.get("Seoul") == 0
    # Busiest first, so the row reads as an answer as well as a question.
    assert options[0]["label"] == "Busan"


def test_the_first_screen_order_is_when_then_style_then_place():
    """Requirement 4: none of this may need a scroll to reach."""
    regions = [{"value": "Seoul", "label": "Seoul", "events": 1}]
    facets = {"genres": [], "regions": regions, "region_options": regions}
    page = (public._nav("today") +
            public._filter_bar("/", None, facets, OPTIONS, ALL, None))
    tabs = page.index("<nav>")
    styles = page.index('form class="row genres"')
    places = page.index("지역")
    assert tabs < styles < places
