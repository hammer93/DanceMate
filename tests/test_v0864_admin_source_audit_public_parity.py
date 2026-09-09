"""v0.86.4 Admin Source Audit & Public Display Parity.

Two Timeline defects, fixed together because they share one root cause -
"확인 필요"/"시간 미확인" used to be free text baked into line 1, so any
new certainty signal had nowhere to live except more text:

  1. A real start/end time shown on line 1 could ALSO carry a "시간 미확인"
     tag right next to it (Section 4-6) - self-contradictory the moment a
     reader is shown a time and told in the same breath it is unknown.
  2. The "확인 필요" text badge (Section 7-11) is gone, replaced by a small
     "?" right after the event type, whose visibility reuses the engine's
     existing status vocabulary (Section 16-21) and is admin-configurable
     (Section 72-75) through a new, deliberately small settings table -
     investigated first (Section 21): no generic settings mechanism existed
     anywhere in this codebase to reuse instead.

The second half of this release reworks the Admin Source list into an
audit workbench (Section 24-92) and adds an Item Audit Detail comparing
Original/Acquired/Extracted/Public for one post (Section 40-53) - both
built to call the exact same `runtime.public` renderer the live Timeline
uses, never a second, parallel formatter (Section 69).
"""

from __future__ import annotations

import inspect
from datetime import datetime

import pytest

from runtime import admin, events_api, public, timeline_settings

_NOW = datetime.fromisoformat("2026-09-08T10:00:00+09:00")  # not in-progress for the fixture window


def _event(**overrides):
    base = {
        "id": 1, "name": "[부산] 이데알 탱고 까페 9/8 공지",
        "date": "2026-09-08",
        "start_time": "20:30", "end_time": "23:30", "ends_next_day": False,
        "time_confirmed": False,  # the post's own clock has no am/pm marker
        "event_type_label": "밀롱가",
        "region": "부산", "region_confirmed": True,
        "venue": {"name": None, "status": "ABSENT", "aliases": []},
        "fee": None, "dj": None,
        "status": "POSSIBLE", "status_label": "확인 필요", "cancelled": False,
        "source_link": {"url": None, "label": None},
        "last_checked": None,
    }
    base.update(overrides)
    return base


# === Group 1: Timeline Status (contradiction fix + "?" indicator) ==========

def test_start_and_end_time_shows_no_unknown_text():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert "20:30~23:30" in line1
    assert "시간 미확인" not in line1


def test_start_only_shows_no_unknown_text():
    event = _event(end_time=None)
    line1 = public._timeline_line1(event, now=_NOW)
    assert "20:30" in line1
    assert "시간 미확인" not in line1


def test_no_time_at_all_shows_non_contradictory_unknown_text():
    """No real value exists to contradict - the plain 미확인 span stays."""
    event = _event(start_time=None, end_time=None, time_confirmed=None)
    line1 = public._timeline_line1(event, now=_NOW)
    assert '<span class="unknown">시간 미확인</span>' in line1
    # exactly one occurrence: never doubled up with a second, contradicting tag
    assert line1.count("시간 미확인") == 1


def test_detail_page_when_line_has_the_same_fix():
    line = public._when_line(_event())
    assert "20:30" in line and "23:30" in line
    assert "시간 미확인" not in line


def test_verified_status_shows_no_question_mark():
    event = _event(status="VERIFIED", status_label="확인됨", time_confirmed=True)
    line1 = public._timeline_line1(event, now=_NOW)
    assert "confirm-flag" not in line1


def test_possible_status_shows_question_mark_by_default():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert 'class="confirm-flag"' in line1


def test_conflict_status_shows_question_mark():
    event = _event(status="CONFLICT", status_label="정보 충돌")
    line1 = public._timeline_line1(event, now=_NOW)
    assert 'class="confirm-flag"' in line1
    # CONFLICT's own warn badge is unrelated to the removed phrase and stays.
    assert '<span class="status warn">정보 충돌</span>' in line1


def test_unknown_status_shows_question_mark():
    event = _event(status="UNKNOWN", status_label="확인 필요")
    line1 = public._timeline_line1(event, now=_NOW)
    assert 'class="confirm-flag"' in line1


def test_settings_disabled_shows_no_question_mark_for_any_status():
    off = {"enabled": False, "statuses": timeline_settings.CONFIGURABLE_STATUSES}
    for status in ("POSSIBLE", "EXPECTED", "CONFLICT", "UNKNOWN"):
        event = _event(status=status, status_label="x")
        line1 = public._timeline_line1(event, now=_NOW, confirmation_settings=off)
        assert "confirm-flag" not in line1, status


def test_settings_configured_statuses_is_a_real_subset():
    only_conflict = {"enabled": True, "statuses": {"CONFLICT"}}
    possible = public._timeline_line1(_event(status="POSSIBLE"), now=_NOW,
                                      confirmation_settings=only_conflict)
    conflict = public._timeline_line1(_event(status="CONFLICT"), now=_NOW,
                                      confirmation_settings=only_conflict)
    assert "confirm-flag" not in possible
    assert "confirm-flag" in conflict


def test_verified_ignores_settings_entirely():
    """Section 73: VERIFIED has no column to switch back on - not even a
    settings dict that names it explicitly can turn the "?" on for it."""
    everything_on = {"enabled": True, "statuses": {"VERIFIED", "POSSIBLE", "EXPECTED",
                                                    "CONFLICT", "UNKNOWN"}}
    event = _event(status="VERIFIED", status_label="확인됨")
    line1 = public._timeline_line1(event, now=_NOW, confirmation_settings=everything_on)
    assert "confirm-flag" not in line1


def test_cancelled_shows_no_question_mark():
    event = _event(status="POSSIBLE", cancelled=True)
    line1 = public._timeline_line1(event, now=_NOW)
    assert "confirm-flag" not in line1


def test_completed_past_event_shows_no_question_mark_by_default():
    past = datetime.fromisoformat("2026-09-08T10:00:00+09:00")
    event = _event(date="2026-09-01", status="POSSIBLE")
    line1 = public._timeline_line1(event, now=past)
    assert "confirm-flag" not in line1


def test_question_mark_sits_immediately_after_the_event_type():
    line1 = public._timeline_line1(_event(), now=_NOW)
    type_pos = line1.index("밀롱가")
    flag_pos = line1.index('<span class="confirm-flag"')
    assert type_pos < flag_pos
    between = line1[type_pos + len("밀롱가"):flag_pos]
    assert between == " "


def test_old_confirmation_needed_text_badge_is_gone():
    """The exact phrase this release retires - not merely relocated."""
    for status in ("POSSIBLE", "UNKNOWN"):
        event = _event(status=status, status_label=events_api.STATUS_LABELS[status])
        line1 = public._timeline_line1(event, now=_NOW)
        assert "확인 필요" not in line1


def test_verified_badge_text_is_unaffected():
    """Only the "확인 필요" phrase was removed - VERIFIED's own badge stays."""
    event = _event(status="VERIFIED", status_label="확인됨", time_confirmed=True)
    line1 = public._timeline_line1(event, now=_NOW)
    assert '<span class="status ok" title=' in line1
    assert "확인됨" in line1


def test_confirm_flag_has_a_tooltip_and_aria_label():
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert 'title="원문 확인이 필요한 행사입니다."' in line1
    assert 'aria-label="원문 확인이 필요한 행사입니다."' in line1


def test_confirm_flag_css_is_small_and_not_a_bordered_badge():
    rule = public.STYLE.split(".confirm-flag {", 1)[1].split("}", 1)[0]
    assert "border" not in rule
    assert "background" not in rule


def test_missing_settings_defaults_to_engine_defaults_not_silently_off():
    """A caller that has not been updated to pass settings keeps today's
    behaviour rather than the indicator silently disappearing everywhere."""
    line1 = public._timeline_line1(_event(), now=_NOW, confirmation_settings=None)
    assert "confirm-flag" in line1


# === Group 2: Admin/Public parity ===========================================

def test_needs_confirmation_is_a_pure_function_with_no_db_access():
    params = inspect.signature(public._needs_confirmation).parameters
    assert not any(name in ("con", "cursor", "pg") for name in params)


def test_timeline_settings_module_has_no_admin_only_shadow_copy():
    """admin.py must read/write through `timeline_settings`, never keep its
    own parallel notion of the configurable statuses (Section 69)."""
    source = inspect.getsource(admin)
    assert "timeline_settings.get_settings(" in source
    assert "timeline_settings.set_settings(" in source
    assert "DEFAULT_CONFIRMATION_STATUSES" not in source


def test_admin_item_detail_calls_the_shared_public_renderer():
    """The Item Audit Detail's "(D) Public Display" column must call
    `runtime.public`'s own line1/line2/line3 - never a second formatter
    that could quietly drift from what a real reader sees (Section 69)."""
    source = inspect.getsource(admin.admin_source_item_detail)
    assert "public._timeline_line1(event" in source
    assert "public._timeline_line2(event" in source
    assert "public._timeline_line3(event" in source


def test_admin_module_defines_no_duplicate_timeline_formatter():
    source = inspect.getsource(admin)
    for banned in ("_timeline_line1", "_timeline_line2", "_timeline_line3",
                  "_needs_confirmation"):
        assert f"def {banned}" not in source


def test_line1_rendering_is_deterministic_given_the_same_inputs():
    """Same event + same settings -> byte-identical HTML, whether it is the
    live Timeline or an admin preview calling it a moment later."""
    settings_ = {"enabled": True, "statuses": {"POSSIBLE"}}
    first = public._timeline_line1(_event(), now=_NOW, confirmation_settings=settings_)
    second = public._timeline_line1(_event(), now=_NOW, confirmation_settings=settings_)
    assert first == second


# === Group 3: Source Audit Workbench / Item Audit Detail (needs Postgres) ==

@pytest.mark.postgres
def test_sources_page_is_wide(client_v0864, pg):
    body = _admin_get(client_v0864, "/admin/sources")
    assert '<body class="wide">' in body


@pytest.mark.postgres
def test_sources_page_shows_genre_filter_bar(client_v0864, pg):
    body = _admin_get(client_v0864, "/admin/sources")
    assert 'href="/admin/sources?genre=ALL"' in body
    assert 'href="/admin/sources?genre=UNKNOWN"' in body
    assert "장르 미확인" in body


@pytest.mark.postgres
def test_sources_page_genre_filter_marks_the_active_chip(client_v0864, pg):
    body = _admin_get(client_v0864, "/admin/sources?genre=UNKNOWN")
    assert '<a class="on" href="/admin/sources?genre=UNKNOWN">' in body


@pytest.mark.postgres
def test_sources_page_shows_source_tier(client_v0864, pg):
    body = _admin_get(client_v0864, "/admin/sources")
    assert 'class="tierbadge' in body
    assert any(label in body for label in ("공식", "홍보게시판", "일정모음"))


@pytest.mark.postgres
def test_sources_page_distinguishes_collector_from_public_url(client_v0864, pg):
    body = _admin_get(client_v0864, "/admin/sources")
    assert '<span class="lbl">Collector</span>' in body
    assert '<span class="lbl">Public</span>' in body


@pytest.mark.postgres
def test_sources_page_never_links_a_json_api_endpoint_as_the_public_url(client_v0864, pg):
    """TangoNOW's raw source_url is a Firestore REST document; Tango
    Calendar Korea's is an `/api/events/{uuid}` endpoint - neither must
    ever appear as an `href` (Section 25/85-87). Collector URLs are shown
    as plain text/`title`, never as a link, so this holds regardless of
    which sources happen to be seeded on this database."""
    import re

    body = _admin_get(client_v0864, "/admin/sources")
    for href in re.findall(r'href="([^"]*)"', body):
        assert "firestore.googleapis.com" not in href
        assert "/api/events/" not in href


@pytest.mark.postgres
def test_settings_page_shows_the_configurable_statuses(client_v0864, pg):
    body = _admin_get(client_v0864, "/admin/settings")
    for label in admin._STATUS_CHECKLIST_LABELS.values():
        assert label in body


def test_settings_page_has_no_checkbox_for_verified():
    assert "VERIFIED" not in admin._STATUS_CHECKLIST_LABELS


@pytest.mark.postgres
def test_settings_save_round_trips_and_is_reset_afterward(client_v0864, pg):
    from runtime import db
    from runtime.config import load_settings

    try:
        response = client_v0864.post(
            "/admin/settings/timeline-confirmation",
            data={"enabled": "1", "statuses": ["CONFLICT"]},
            auth=_AUTH, follow_redirects=False,
        )
        assert response.status_code == 303
        con = db.connect(load_settings(), autocommit=True)
        saved = timeline_settings.get_settings(con)
        assert saved == {"enabled": True, "statuses": {"CONFLICT"}}
    finally:
        con = db.connect(load_settings(), autocommit=True)
        timeline_settings.set_settings(
            con, enabled=True, statuses=set(timeline_settings.CONFIGURABLE_STATUSES))


@pytest.mark.postgres
def test_every_source_row_links_to_its_own_detail_page(client_v0864, pg):
    from runtime import sources as sources_module

    rows = sources_module.list_sources(pg, limit=1)
    if not rows:
        pytest.skip("no sources seeded on this database")
    source_id = rows[0]["source_id"]
    body = _admin_get(client_v0864, "/admin/sources")
    assert f'/admin/sources/{source_id}' in body


@pytest.mark.postgres
def test_source_detail_page_shows_the_audit_summary(client_v0864, pg):
    from runtime import sources as sources_module

    rows = sources_module.list_sources(pg, limit=1)
    if not rows:
        pytest.skip("no sources seeded on this database")
    body = _admin_get(client_v0864, f"/admin/sources/{rows[0]['source_id']}")
    assert "Source Audit Summary" in body
    for label in ("Items", "Events", "Date Missing", "Time Missing",
                  "Venue Missing", "Fee Missing", "DJ Missing"):
        assert label in body


@pytest.mark.postgres
def test_source_detail_recent_items_table_has_the_new_columns(client_v0864, pg):
    from runtime import sources as sources_module

    rows = sources_module.list_sources(pg, limit=1)
    if not rows:
        pytest.skip("no sources seeded on this database")
    body = _admin_get(client_v0864, f"/admin/sources/{rows[0]['source_id']}")
    for header in ("Canonical Event", "Public URL", "Review Hints"):
        assert header in body


@pytest.mark.postgres
def test_item_audit_detail_requires_auth(client_v0864):
    assert client_v0864.get("/admin/sources/1/items/1").status_code == 401


@pytest.mark.postgres
def test_item_audit_detail_404s_for_a_nonexistent_item(client_v0864, pg):
    from runtime import sources as sources_module

    rows = sources_module.list_sources(pg, limit=1)
    if not rows:
        pytest.skip("no sources seeded on this database")
    response = client_v0864.get(
        f"/admin/sources/{rows[0]['source_id']}/items/999999999", auth=_AUTH)
    assert response.status_code == 404


@pytest.mark.postgres
def test_item_audit_detail_shows_the_four_way_comparison(client_v0864, pg):
    from runtime import intake, sources as sources_module

    for row in sources_module.list_sources(pg, limit=200):
        items = intake.recent_items(pg, source_id=row["source_id"], limit=1)
        if items:
            body = _admin_get(
                client_v0864,
                f"/admin/sources/{row['source_id']}/items/{items[0]['source_item_id']}",
            )
            for label in ("(A) Original", "(B) Acquired", "(C) Extracted",
                         "(D) Public Display"):
                assert label in body
            return
    pytest.skip("no source has collected any items on this database")


@pytest.mark.postgres
def test_item_audit_detail_never_uses_dangerous_html_for_stored_text(client_v0864, pg):
    """Section 109: stored raw text is escaped, never trusted markup."""
    source = inspect.getsource(admin.admin_source_item_detail)
    assert "dangerouslySetInnerHTML" not in source
    assert "shown_text = (body_text or \"\")[:4000]" in source
    assert "E(shown_text)" in source


_AUTH = ("dancemate", "test-admin-password")


@pytest.fixture
def client_v0864(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", _AUTH[0])
    monkeypatch.setenv("ADMIN_PASSWORD", _AUTH[1])
    monkeypatch.setattr(app_module, "_settings", None)
    from fastapi.testclient import TestClient

    return TestClient(app_module.app, raise_server_exceptions=False)


def _admin_get(client, path: str) -> str:
    response = client.get(path, auth=_AUTH)
    assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text[:300]}"
    return response.text


# === Group 4: existing-behaviour regression =================================

def test_venue_after_region_regression():
    event = _event(venue={"name": "이데알 탱고 까페", "status": "RESOLVED", "aliases": []})
    line1 = public._timeline_line1(event, now=_NOW)
    assert line1.index("[부산]") < line1.index("이데알 탱고 까페")


def test_end_time_regression():
    assert "20:30~23:30" in public._timeline_line1(_event(), now=_NOW)


def test_conditional_fee_regression():
    event = _event(fee=8000, fee_display_text="8,000원 (22시 이후 5,000원)")
    assert "입장료: 8,000원 (22시 이후 5,000원)" in public._timeline_line2(event)


def test_dj_duplicate_regression():
    event = _event(name="Solo Tango 화요정모 (DJ 유진)", dj="유진")
    assert public._timeline_line2(event).count("유진") == 1


def test_address_regression():
    event = _event(venue={"name": "x", "status": "RESOLVED",
                         "address": "서울 마포구 동교로 193", "aliases": []})
    assert "마포구 동교로 193" in public._timeline_line2(event)


def test_naver_map_regression():
    event = _event(
        venue={"name": "x", "status": "RESOLVED",
              "address": "서울 마포구 동교로 193", "aliases": [],
              "map_url": events_api.build_naver_map_search_url("서울 마포구 동교로 193")},
        source_link={"url": "https://cafe.daum.net/latindance/73b/68727",
                    "label": "Solo Tango 화요정모 공지"},
    )
    line3 = public._timeline_line3(event, now=_NOW)
    assert "map.naver.com/p/search/" in line3


def test_positive_region_filter_regression():
    html = public._region_chips(
        "/events", None, [{"value": "서울", "label": "서울", "events": 3}], None, {})
    assert "서울 3" in html
    assert "부산" not in html


def test_calendar_week_window_regression():
    monday, sunday = events_api.week_window(0, now=_NOW)
    assert monday.weekday() == 0
    assert (sunday - monday).days == 6


@pytest.mark.postgres
def test_primary_representative_source_selection_regression(pg):
    from runtime import source_priority

    assert source_priority.tier_of("ORGANIZER") == "PRIMARY"


def test_miltang_and_tangonow_are_directory_tier_regression():
    from runtime import source_priority

    assert source_priority.tier_of("DIRECTORY") == "DIRECTORY"
    assert source_priority.tier_of("AGGREGATOR") == "DIRECTORY"
