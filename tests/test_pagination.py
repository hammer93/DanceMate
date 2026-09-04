"""Shared admin-list paging: 50 rows a page, a safe page number always."""

from __future__ import annotations

from runtime import pagination


# --- total_pages / resolve_page ----------------------------------------------

def test_exactly_fifty_rows_is_one_page():
    assert pagination.total_pages(50) == 1


def test_fifty_one_rows_is_two_pages():
    assert pagination.total_pages(51) == 2


def test_zero_rows_is_still_page_one_of_one():
    assert pagination.total_pages(0) == 1


def test_page_zero_is_corrected_to_one():
    assert pagination.resolve_page(0, total=200) == 1


def test_page_negative_is_corrected_to_one():
    assert pagination.resolve_page(-1, total=200) == 1


def test_page_non_numeric_is_corrected_to_one():
    assert pagination.resolve_page("abc", total=200) == 1
    assert pagination.resolve_page(None, total=200) == 1


def test_page_past_the_end_is_corrected_to_the_last_page():
    # 268 rows / 50 per page = page 6 is the last one (rows 251-268)
    assert pagination.resolve_page(99999, total=268) == 6


def test_a_normal_page_number_passes_through_unchanged():
    assert pagination.resolve_page(3, total=268) == 3
    assert pagination.resolve_page("3", total=268) == 3


# --- sql_offset ---------------------------------------------------------------

def test_offset_for_page_one_is_zero():
    assert pagination.sql_offset(1) == 0


def test_offset_for_page_two_is_the_page_size():
    assert pagination.sql_offset(2) == pagination.PAGE_SIZE == 50


def test_offset_for_page_six_is_five_pages_in():
    assert pagination.sql_offset(6) == 250


# --- nav() ---------------------------------------------------------------------

def test_nav_shows_the_total_and_the_visible_range():
    html = pagination.nav("/admin/events", {}, 2, 268)
    assert "Total 268" in html
    assert "51" in html and "100" in html  # showing 51-100


def test_nav_previous_is_disabled_on_page_one():
    html = pagination.nav("/admin/events", {}, 1, 268)
    assert '<span class="pager-link off">Previous</span>' in html
    assert 'href="/admin/events?page=2">Next</a>' in html


def test_nav_next_is_disabled_on_the_last_page():
    html = pagination.nav("/admin/events", {}, 6, 268)
    assert '<span class="pager-link off">Next</span>' in html
    assert 'page=5">Previous</a>' in html


def test_nav_preserves_other_query_params():
    html = pagination.nav(
        "/admin/intake", {"status": "FETCHED_FULL", "source_id": "3"}, 2, 120
    )
    assert "status=FETCHED_FULL" in html
    assert "source_id=3" in html
    assert "page=1" in html  # Previous
    assert "page=3" in html  # Next


def test_nav_uses_a_custom_page_param_without_colliding():
    """/admin/master has two independent lists on one page."""
    html = pagination.nav(
        "/admin/master", {"region_page": 2}, 1, 60, page_param="genre_page"
    )
    assert "genre_page=2" in html  # the Next link, to genre page 2
    assert "region_page=2" in html  # the other list's page is preserved


def test_nav_omits_empty_query_values():
    html = pagination.nav("/admin/intake", {"status": "", "source_id": None}, 1, 10)
    assert "status=" not in html
    assert "source_id=" not in html


def test_nav_on_an_empty_list_reads_total_zero():
    html = pagination.nav("/admin/venues", {}, 1, 0)
    assert "Total 0" in html
    assert "Page 1 / 1" in html
