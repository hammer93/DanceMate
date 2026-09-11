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


# v0.87.0: the user retired v0.86.4's status-driven "?" - it meant "unverified
# post" but sat after the event's kind and read as doubt about the kind
# ("밀롱가?" on a plain milonga). The "?" now means only that the kind could
# not be settled from the title's words; these tests hold that contract.

def _terms():
    from runtime import event_terms

    rows = [("밀롱가", ("MILONGA",)), ("쁘락", ("PRACTICA",)),
            ("쁘롱가", ("MILONGA", "PRACTICA"))]
    return [{"event_term_id": n, "genre_code": "TANGO", "term": t,
             "normalized_term": event_terms.normalize_term(t), "enabled": True,
             "formats": f} for n, (t, f) in enumerate(rows, 1)]


def test_no_engine_status_puts_a_question_mark_on_the_kind_any_more():
    for status in ("POSSIBLE", "EXPECTED", "CONFLICT", "UNKNOWN", "VERIFIED"):
        line1 = public._timeline_line1(_event(status=status, status_label="x"), now=_NOW)
        assert "kind-why" not in line1 and "confirm-flag" not in line1, status


def test_a_plain_milonga_is_settled_whatever_its_status():
    for status in ("POSSIBLE", "CONFLICT", "VERIFIED"):
        event = _event(name="금요일 밀롱가", event_type="MILONGA", genre="TANGO",
                       status=status, status_label="x")
        line1 = public._timeline_line1(event, now=_NOW, terms=_terms())
        assert '<span class="kind">밀롱가</span>' in line1, status
        assert "kind-why" not in line1, status


def test_conflict_status_keeps_its_own_badge():
    event = _event(status="CONFLICT", status_label="정보 충돌")
    line1 = public._timeline_line1(event, now=_NOW)
    # CONFLICT's own warn badge is unrelated to the retired "?" and stays.
    assert '<span class="status warn">정보 충돌</span>' in line1


def test_disagreeing_words_put_the_question_mark_right_after_the_kind():
    event = _event(name="밀롱가 & 쁘락", event_type="MILONGA", genre="TANGO")
    line1 = public._timeline_line1(event, now=_NOW, terms=_terms())
    kind_at = line1.index('<span class="kind">밀롱가 · 쁘락</span>')
    after = line1[kind_at + len('<span class="kind">밀롱가 · 쁘락</span>'):]
    assert after.startswith(' <button type="button" class="kind-why"')


def test_cancelled_and_past_events_follow_the_same_kind_rule():
    past = datetime.fromisoformat("2026-09-08T10:00:00+09:00")
    for event in (_event(name="금요일 밀롱가", event_type="MILONGA", genre="TANGO",
                         cancelled=True),
                  _event(name="금요일 밀롱가", event_type="MILONGA", genre="TANGO",
                         date="2026-09-01")):
        line1 = public._timeline_line1(event, now=past, terms=_terms())
        assert "kind-why" not in line1


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


def test_the_kind_question_mark_is_a_labelled_button_with_a_popover():
    event = _event(name="밀롱가 & 쁘락", event_type="MILONGA", genre="TANGO")
    line1 = public._timeline_line1(event, now=_NOW, terms=_terms())
    assert 'aria-label="행사 유형 판정 이유 보기"' in line1
    assert 'popovertarget="kind-why-1"' in line1
    assert 'id="kind-why-1" popover role="dialog"' in line1


def test_the_kind_question_mark_css_is_a_button_not_the_retired_flag():
    assert ".confirm-flag" not in public.STYLE
    rule = public.STYLE.split(".kind-why {", 1)[1].split("}", 1)[0]
    assert "cursor:pointer" in rule


def test_without_terminology_the_plain_label_shows_with_no_question_mark():
    """A caller that passes no terminology keeps the plain type label - the
    "?" never appears without the evidence that would justify it."""
    line1 = public._timeline_line1(_event(), now=_NOW)
    assert "밀롱가" in line1 and "kind-why" not in line1


# === Group 2: Admin/Public parity ===========================================

def test_the_kind_decision_is_a_pure_function_with_no_db_access():
    from runtime import event_terms

    params = inspect.signature(event_terms.classify_kind).parameters
    assert not any(name in ("con", "cursor", "pg") for name in params)


def test_admin_no_longer_reads_or_writes_the_retired_timeline_setting():
    """v0.87.0 retired the checklist - the console neither reads nor writes
    it, and keeps no shadow notion of configurable statuses either."""
    source = inspect.getsource(admin)
    assert "timeline_settings.get_settings(" not in source
    assert "timeline_settings.set_settings(" not in source
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
                  "_event_kind", "_kind_why", "_kind_html"):
        assert f"def {banned}" not in source


def test_line1_rendering_is_deterministic_given_the_same_inputs():
    """Same event + same settings -> byte-identical HTML, whether it is the
    live Timeline or an admin preview calling it a moment later."""
    event = _event(name="밀롱가 & 쁘락", event_type="MILONGA", genre="TANGO")
    first = public._timeline_line1(event, now=_NOW, terms=_terms())
    second = public._timeline_line1(event, now=_NOW, terms=_terms())
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
    """v0.86.5 merged the separate URL column into the Target cell and
    dropped the old "Collector"/"Public" text labels (Section 43: no
    redundant labels) - the distinction survives structurally instead,
    as two different links inside the same `.targetcell`."""
    body = _admin_get(client_v0864, "/admin/sources")
    assert 'class="targetcell"' in body
    assert 'class="target-public"' in body


@pytest.mark.postgres
def test_sources_page_never_links_a_json_api_endpoint_as_the_public_url(client_v0864, pg):
    """TangoNOW's raw source_url is a Firestore REST document; Tango
    Calendar Korea's is an `/api/events/{uuid}` endpoint - neither must
    ever be the target of a "원문보기" Public URL link (Section 25/85-87).

    The pre-existing "Open Source" button in the unrelated Target column
    (`_source_target()`, untouched this release) deliberately links the raw
    collector endpoint on purpose - that is what it is for, clearly labelled
    as the collector's own target, not a claim about a public page - so a
    blanket "no href anywhere on the page" scan would wrongly fail on it.
    This checks only the "원문보기" links this release actually added.
    """
    import re

    body = _admin_get(client_v0864, "/admin/sources")
    for href in re.findall(r'href="([^"]*)"[^>]*>원문보기', body):
        assert "firestore.googleapis.com" not in href
        assert "/api/events/" not in href


@pytest.mark.postgres
def test_settings_page_no_longer_shows_the_retired_checklist(client_v0864, pg):
    body = _admin_get(client_v0864, "/admin/settings")
    assert "사용자 Timeline 확인 표시" not in body
    assert 'name="statuses"' not in body
    assert '<h2 id="event-terms">' in body


def test_the_retired_checklist_labels_are_gone():
    assert not hasattr(admin, "_STATUS_CHECKLIST_LABELS")


@pytest.mark.postgres
def test_the_retired_save_route_is_gone_and_its_data_left_alone(client_v0864, pg):
    from runtime import db
    from runtime.config import load_settings

    with db.connect(load_settings(), autocommit=True) as con:
        before = timeline_settings.get_settings(con)
    response = client_v0864.post(
        "/admin/settings/timeline-confirmation",
        data={"enabled": "1", "statuses": ["CONFLICT"]},
        auth=_AUTH, follow_redirects=False,
    )
    assert response.status_code in (404, 405)
    with db.connect(load_settings(), autocommit=True) as con:
        assert timeline_settings.get_settings(con) == before


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
    """`_table()` renders no `<th>` row at all when a source has zero
    recent items (its own, pre-existing "empty" placeholder branch) - so
    this needs a source that has actually collected something, not just
    the alphabetically-first one, which a bare fresh database may not have."""
    from runtime import intake, sources as sources_module

    for row in sources_module.list_sources(pg, limit=200):
        if intake.recent_items(pg, source_id=row["source_id"], limit=1):
            body = _admin_get(client_v0864, f"/admin/sources/{row['source_id']}")
            for header in ("Canonical Event", "Public URL", "Review Hints"):
                assert header in body
            return
    pytest.skip("no source has collected any items on this database")


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


def test_source_level_api_list_endpoint_resolves_to_a_home_page():
    """Caught by this release's own production audit: Tango Calendar
    Korea's SOURCE-level url (`.../api/events`, the collector's list
    endpoint - no per-event id, so the two specific per-item patterns
    never match it) used to fall through unchanged, showing a JSON
    endpoint as "원문보기" on the Source Audit Workbench (Section 82-92)."""
    assert (events_api.resolve_public_source_url("https://tangocalendar.kr/api/events")
            == "https://tangocalendar.kr/")


def test_an_already_human_url_is_never_rewritten():
    for url in ("https://danceinfo.net/lessons?genre=all&category=all",
               "https://miltang.com/milongas"):
        assert events_api.resolve_public_source_url(url) == url


def test_miltang_and_tangonow_are_directory_tier_regression():
    from runtime import source_priority

    assert source_priority.tier_of("DIRECTORY") == "DIRECTORY"
    assert source_priority.tier_of("AGGREGATOR") == "DIRECTORY"
