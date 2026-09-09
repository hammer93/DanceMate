"""v0.86.5 Admin Source Dense Layout.

The Source Audit Workbench's list view (v0.86.4) spent thirteen columns on
information most of which is a handful of words: a separate "URL" column
next to "Target", and one column each for Content Mode, Health, Interval
and Decision. This release consolidates them - seven columns instead of
thirteen, most of the reclaimed width handed to Source and Target (the two
columns whose content can genuinely run long) - without deleting any of the
information those old columns showed. UI-only: no migration, no engine
change, no source-collection-logic change, no Public Timeline change.
"""

from __future__ import annotations

import inspect

import pytest

from runtime import admin, collectors, source_priority

_AUTH = ("dancemate", "test-admin-password")


@pytest.fixture
def client_v0865(env, monkeypatch):
    from fastapi.testclient import TestClient

    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", _AUTH[0])
    monkeypatch.setenv("ADMIN_PASSWORD", _AUTH[1])
    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


def _admin_get(client, path: str) -> str:
    response = client.get(path, auth=_AUTH)
    assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text[:300]}"
    return response.text


def _source(**overrides):
    base = {
        "source_id": 1, "source_key": "SRC-D-003", "name": "Solo Tango 화요정모 공지",
        "platform": "DAUM_CAFE", "source_role": "COMMUNITY",
        "authority_level": "SECONDARY", "url": None, "queries": ["밀롱가"],
        "genre_id": None, "region_id": None, "config": {},
        "collection_interval_minutes": 60, "enabled": True, "notes": None,
    }
    base.update(overrides)
    return base


# === structural / pure-function tests (no DB) ===============================

def _headers_literal(source_text: str) -> str:
    """The exact header list literal passed to `_table(...)` in
    `admin_sources()`, isolated from unrelated strings elsewhere in the
    function (e.g. the edit form's own `"URL"` field label)."""
    start = source_text.index("_table(")
    return source_text[start:source_text.index("table_rows,", start)]


# 1. separate URL column removed
def test_separate_url_column_removed_from_headers():
    headers = _headers_literal(inspect.getsource(admin.admin_sources))
    assert '"URL"' not in headers
    assert '"Content Mode"' not in headers
    assert '"Interval"' not in headers
    assert '"Decision"' not in headers


# 7/8/9. content/mode, health, interval share one cell
def test_meta_cell_holds_content_mode_health_and_interval():
    source = _source(platform="WEB", config={"parser": "board"})
    capability = collectors.describe_capability("WEB")
    html = admin._source_meta_cell(source, "ACTIVE", capability)
    assert 'class="metacell"' in html
    assert "ACTIVE" in html
    assert "60m" in html


# 10. metadata is at most 3 logical lines
def test_meta_cell_is_at_most_three_logical_lines():
    source = _source(platform="WEB", config={"parser": "board"})
    capability = collectors.describe_capability("WEB")
    html = admin._source_meta_cell(source, "ACTIVE", capability)
    assert html.count("<div>") == 3


# 2/3. target cell contains both a collector target and a public link
def test_target_cell_contains_collector_and_public():
    source = _source(platform="WEB", url="https://tangocalendar.kr/api/events")
    html = admin._source_target_and_public(source)
    assert 'class="targetcell"' in html
    assert "tangocalendar.kr" in html  # the collector's own target text
    assert 'class="target-public"' in html


# 4. public URL is clickable
def test_public_link_is_a_real_anchor_with_safe_target():
    html = admin._public_link_html("https://miltang.com/milongas")
    assert '<a class="target-public"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


# 5. collector and public differ correctly (JSON collector -> resolved public)
def test_collector_and_public_differ_for_an_api_source():
    html = admin._source_target_and_public(
        _source(platform="WEB", url="https://tangocalendar.kr/api/events"))
    assert "tangocalendar.kr/api/events" in html
    # the public link's href is the resolved origin, not the raw API path
    assert 'href="https://tangocalendar.kr/"' in html


# 6. URL hover shows the full URL
def test_target_and_public_links_carry_full_url_in_title():
    import html as html_module

    long_url = "https://miltang.com/milongas?really=long&query=string"
    html = admin._public_link_html(long_url)
    assert f'title="{html_module.escape(long_url)}"' in html


# 11. activity stays compact
def test_activity_cell_is_compact():
    html = admin._source_yield({"items": 172, "fetched": 168, "events": 159}, {})
    assert html.count('<div class="note">') <= 1


# 12. status/last-run cell is compact
def test_status_cell_is_at_most_three_logical_lines():
    html = admin._source_status_cell(1, {}, {}, {})
    assert html.count("<div>") == 3


# 13. source id/platform sit compactly under the name
def test_source_cell_shows_key_and_platform_in_one_note_line():
    # A pure string check against the exact shape the row-builder produces -
    # source_key and platform assembled into one <div class="note"> line.
    source = inspect.getsource(admin.admin_sources)
    assert '<code>{E(source["source_key"])}</code> · ' in source
    assert '{E(source["platform"])}' in source


# 14. genre/tier visible in one cell
def test_genre_tier_cell_shows_both():
    html = admin._source_genre_tier_cell(
        '<span class="badge muted">TANGO</span>', "PRIMARY", "공식")
    assert "TANGO" in html
    assert 'class="tierbadge primary"' in html
    assert "공식" in html


# 20/21. tier badges
def test_primary_tier_badge_class():
    assert source_priority.tier_of("ORGANIZER") == "PRIMARY"


def test_directory_tier_badge_class():
    assert source_priority.tier_of("DIRECTORY") == "DIRECTORY"


# 22/23. JSON-endpoint-as-public-link regressions, at the unit level.
# The pre-existing "Open Source" button (`_source_target()`, untouched)
# deliberately links the raw collector endpoint on purpose - a debug
# convenience, clearly a different link than "원문보기" - so these check
# only the actual Public URL link's own href, not every href in the cell.
def test_tangocalendar_json_endpoint_never_becomes_the_public_link():
    html = admin._source_target_and_public(
        _source(platform="WEB", url="https://tangocalendar.kr/api/events"))
    public_href = html.split('class="target-public"', 1)[1]
    assert "/api/events" not in public_href.split(">", 1)[0]


def test_tangoclass_wp_json_endpoint_never_becomes_the_public_link():
    """Real, live gap this release's own tests caught before merge:
    TangoClass's SOURCE-level url is `.../wp-json/wp/v2/posts?per_page=10`
    (confirmed against production) - "wp-json" never contained the literal
    "/api/" the v0.86.4 fallback matched, so it fell through unchanged.
    Fixed in `events_api.resolve_public_source_url()`'s generic fallback.
    """
    html = admin._public_link_html("https://tangoclass.co.kr/wp-json/wp/v2/posts?per_page=10")
    assert "wp-json" not in html
    assert 'href="https://tangoclass.co.kr/"' in html


# 25. the decision-recording action still exists, just moved
def test_decision_form_moved_into_actions_not_deleted():
    source = inspect.getsource(admin.admin_sources)
    assert "_source_decision_form(" in source
    assert "_source_decision(" not in source  # the old, single combined function is gone
    form_html = admin._source_decision_form(
        {"source_id": 1, "operational_decision": None, "recommended": "LIVE",
         "recommendation_reason": "test"})
    assert "<details>" in form_html
    assert 'action="/admin/sources/1/decision"' in form_html


def test_decision_badge_shown_without_expanding_anything():
    badge = admin._source_decision_badge(
        {"source_id": 1, "operational_decision": "LIVE"})
    assert "<details>" not in badge
    assert "LIVE" in badge


# === DB-backed tests (skip locally, run in staging/production) =============

@pytest.mark.postgres
def test_sources_table_uses_seven_columns(client_v0865, pg):
    body = _admin_get(client_v0865, "/admin/sources")
    assert 'class="sources-dense"' in body
    for header in ("Source", "Genre / Tier", "Target", "Meta", "Activity",
                  "Status / Last Run", "Actions"):
        assert f"<th>{header}</th>" in body


def test_sources_headers_no_longer_include_removed_columns():
    # Pure structural check, safe without DB: the removed headers must not
    # appear anywhere in the route's own literal header list.
    source = inspect.getsource(admin.admin_sources)
    for removed in ("Platform / Genre / Region", "Last Success / Error",
                   "Items / readable"):
        assert removed not in source


@pytest.mark.postgres
def test_genre_filter_all_regression(client_v0865, pg):
    body = _admin_get(client_v0865, "/admin/sources?genre=ALL")
    assert '<a class="on" href="/admin/sources?genre=ALL">' in body


@pytest.mark.postgres
def test_genre_filter_tango_regression(client_v0865, pg):
    body = _admin_get(client_v0865, "/admin/sources?genre=TANGO")
    assert '<a class="on" href="/admin/sources?genre=TANGO">' in body


@pytest.mark.postgres
def test_genre_filter_salsa_regression(client_v0865, pg):
    body = _admin_get(client_v0865, "/admin/sources?genre=SALSA")
    assert '<a class="on" href="/admin/sources?genre=SALSA">' in body


@pytest.mark.postgres
def test_genre_filter_swing_regression(client_v0865, pg):
    body = _admin_get(client_v0865, "/admin/sources?genre=SWING")
    assert '<a class="on" href="/admin/sources?genre=SWING">' in body


@pytest.mark.postgres
def test_genre_filter_unknown_regression(client_v0865, pg):
    body = _admin_get(client_v0865, "/admin/sources?genre=UNKNOWN")
    assert '<a class="on" href="/admin/sources?genre=UNKNOWN">' in body


@pytest.mark.postgres
def test_item_audit_detail_still_reachable(client_v0865, pg):
    from runtime import intake
    from runtime import sources as sources_module

    for row in sources_module.list_sources(pg, limit=200):
        items = intake.recent_items(pg, source_id=row["source_id"], limit=1)
        if items:
            body = _admin_get(
                client_v0865,
                f"/admin/sources/{row['source_id']}/items/{items[0]['source_item_id']}",
            )
            for label in ("(A) Original", "(B) Acquired", "(C) Extracted",
                         "(D) Public Display"):
                assert label in body
            return
    pytest.skip("no source has collected any items on this database")


@pytest.mark.postgres
def test_source_row_enable_disable_action_still_works(client_v0865, pg):
    from runtime import sources as sources_module

    rows = sources_module.list_sources(pg, limit=1)
    if not rows:
        pytest.skip("no sources seeded on this database")
    source_id = rows[0]["source_id"]
    was_enabled = rows[0]["enabled"]
    toggle = "disable" if was_enabled else "enable"
    response = client_v0865.post(
        f"/admin/sources/{source_id}/{toggle}", auth=_AUTH, follow_redirects=False)
    assert response.status_code == 303
    # restore original state so this test never permanently flips a real source
    restore = "enable" if was_enabled else "disable"
    client_v0865.post(f"/admin/sources/{source_id}/{restore}", auth=_AUTH,
                      follow_redirects=False)


@pytest.mark.postgres
def test_no_row_is_dramatically_taller_than_the_others(client_v0865, pg):
    """Acceptance proxy for Section 22-23/53: a real regression here would
    be one cell emitting far more `<div>`/`<br>` line-breaks than any
    other row's corresponding cell, not just "some rows differ slightly".
    """
    body = _admin_get(client_v0865, "/admin/sources")
    row_bodies = body.split("<tbody>", 1)[1].split("</tbody>", 1)[0].split("<tr>")[1:]
    if len(row_bodies) < 2:
        pytest.skip("fewer than 2 sources seeded on this database")
    line_counts = [row.count("<div>") + row.count("<br>") for row in row_bodies]
    assert max(line_counts) <= 3 * (sum(line_counts) / len(line_counts) + 1)
