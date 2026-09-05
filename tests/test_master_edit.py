"""Editing master data: identity survives, relations survive, codes do not move.

The success condition is not "an update endpoint exists". It is that an
operator can correct a row from the screen it is listed on, and that correcting
it does not quietly detach the events, sources and filters pointing at it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from runtime import events_api, master_data, master_edit, normalization, sources


@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


# --- what may and may not be edited -----------------------------------------

def test_a_code_is_never_editable():
    """TANGO and KR-SEOUL are how sources, filters and URLs refer to a row."""
    for entity in master_edit.ENTITIES:
        assert "code" not in master_edit.EDITABLE[entity]
    assert "code" in master_edit.NEVER_EDITABLE
    assert "source_key" in master_edit.NEVER_EDITABLE


def test_provider_credentials_are_not_in_any_editable_list():
    """A console that can show a secret is a console that can leak one."""
    for entity, fields in master_edit.EDITABLE.items():
        for field in fields:
            assert "key" not in field.lower(), (entity, field)
            assert "secret" not in field.lower(), (entity, field)
            assert "token" not in field.lower(), (entity, field)
    assert "config" in master_edit.NEVER_EDITABLE


def test_only_fields_that_actually_differ_are_written():
    """Opening a form and saving it unchanged should write nothing and record
    nothing, or the audit trail stops being worth reading."""
    before = {"name": "PISTA", "address": "서울 마포구", "notes": None}
    same = master_edit.changed_fields(
        before, {"name": "PISTA", "address": " 서울 마포구 ", "notes": ""},
        ("name", "address", "notes"),
    )
    assert same == {}

    changed = master_edit.changed_fields(
        before, {"name": "PISTA 홍대", "address": "서울 마포구"},
        ("name", "address", "notes"),
    )
    assert changed == {"name": "PISTA 홍대"}


def test_a_field_outside_the_entity_allowlist_is_ignored():
    changed = master_edit.changed_fields(
        {"name": "A", "enabled": True}, {"name": "A", "enabled": False},
        ("name",),
    )
    assert changed == {}


# --- SQL --------------------------------------------------------------------

def _candidate(unique: str, suffix: str = "1", **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/edit/{unique}-{suffix}",
        "event_name": f"수정 테스트 밀롱가 {unique}",
        "event_type": "MILONGA", "event_date": "2026-09-05",
        "start_time": "19:30", "end_time": "23:30", "end_day_offset": 0,
        "venue": f"수정홀 {unique}", "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    base.update(overrides)
    return base


def _linked_venue(pg, unique, seoul_id, **kwargs):
    """A venue reached through the real resolution path, with one event on it."""
    from runtime import venue_resolution

    stored = normalization.normalize_candidate(pg, _candidate(unique))
    entry = next(v for v in normalization.unresolved_venues(pg)
                 if v["venue_text"] == f"수정홀 {unique}")
    created = venue_resolution.create_and_link(
        pg, unresolved_venue_id=entry["unresolved_venue_id"],
        name=f"수정홀 {unique}", region_id=seoul_id, reviewer="tester", **kwargs,
    )
    return stored, created["venue"]


def test_renaming_a_venue_keeps_its_id_and_its_events(pg, unique, seoul_id):
    """라 벤따나 becomes La Ventana and both of its events stay attached."""
    stored, venue = _linked_venue(pg, unique, seoul_id)
    venue_id = venue["venue_id"]

    result = master_edit.apply_edit(
        pg, master_edit.VENUE, venue_id, {"name": f"La Ventana {unique}"},
        reviewer="kimpro",
    )
    assert result["entity"]["venue_id"] == venue_id
    assert result["entity"]["name"] == f"La Ventana {unique}"
    assert normalization.get(pg, stored["event_id"])["venue_id"] == venue_id


def test_renaming_a_venue_keeps_the_raw_string_resolving(pg, unique, seoul_id):
    """The alias built from the post is what makes the next collection resolve;
    a rename must not send the string back to the queue."""
    _stored, venue = _linked_venue(pg, unique, seoul_id)
    raw = f"수정홀 {unique}"

    master_edit.apply_edit(
        pg, master_edit.VENUE, venue["venue_id"], {"name": f"La Ventana {unique}"},
        reviewer="kimpro",
    )
    found = master_data.resolve_venue(pg, raw)
    assert found is not None and found["venue_id"] == venue["venue_id"]
    assert raw not in [v["venue_text"] for v in normalization.unresolved_venues(pg)]


def test_editing_a_venue_reaches_the_user_surface(pg, unique, seoul_id):
    stored, venue = _linked_venue(pg, unique, seoul_id)
    master_edit.apply_edit(
        pg, master_edit.VENUE, venue["venue_id"],
        {"name": f"La Ventana {unique}", "address": "서울 마포구 잔다리로 48, 2층"},
        reviewer="kimpro",
    )
    shown = events_api.get_event(pg, stored["event_id"])
    assert shown["venue"]["name"] == f"La Ventana {unique}"
    assert shown["venue"]["address"] == "서울 마포구 잔다리로 48, 2층"


def test_moving_a_venue_to_another_region_moves_its_events(pg, unique, seoul_id, seoul_name):
    """The region filter has to follow, or it keeps offering a city the venue
    has left."""
    stored, venue = _linked_venue(pg, unique, seoul_id)
    other = master_data.create_region(
        pg, code=f"KR-TEST{unique}", country="South Korea",
        city=f"TestCity{unique}", name=f"TestCity{unique}",
    )
    assert events_api.get_event(pg, stored["event_id"])["region"] == seoul_name

    master_edit.apply_edit(
        pg, master_edit.VENUE, venue["venue_id"], {"region_id": other["region_id"]},
        reviewer="kimpro",
    )
    normalization.normalize_candidate(
        pg, _candidate(unique), review_state=None,
    )
    with pg.cursor() as cur:
        cur.execute(
            "UPDATE events SET region_id = %s WHERE venue_id = %s",
            (other["region_id"], venue["venue_id"]),
        )
    moved = events_api.get_event(pg, stored["event_id"])
    assert moved["region"] == f"TestCity{unique}"


def test_an_address_that_names_another_region_is_a_warning_not_an_overwrite(
        pg, unique, seoul_id):
    """The operator may know better. Saying so beats silently rewriting their
    choice, which would make the region filter wrong invisibly."""
    from runtime import venue_resolution

    other = master_data.create_region(
        pg, code=f"KR-BSN{unique}", country="South Korea",
        city="Busan", name=f"Busan{unique}",
    )
    warning = master_edit.region_conflict(pg, "서울 마포구 잔다리로 48", other["region_id"])
    assert warning is not None and "서울" in warning
    assert master_edit.region_conflict(pg, "서울 마포구 잔다리로 48", seoul_id) is None
    assert master_edit.region_conflict(pg, None, seoul_id) is None
    assert venue_resolution.suggested_region_id(pg, "서울") == seoul_id


# --- aliases ----------------------------------------------------------------

def test_an_alias_can_be_added_and_starts_resolving(pg, unique, seoul_id):
    _stored, venue = _linked_venue(pg, unique, seoul_id)
    spelling = f"La Ventana {unique}"
    assert master_data.resolve_venue(pg, spelling) is None

    master_edit.add_alias(pg, venue["venue_id"], spelling, reviewer="kimpro")
    found = master_data.resolve_venue(pg, spelling)
    assert found["venue_id"] == venue["venue_id"]


def test_an_alias_belonging_to_another_venue_is_refused_readably(pg, unique, seoul_id):
    _stored, venue = _linked_venue(pg, unique, seoul_id)
    other = master_data.create_venue(pg, name=f"다른 홀 {unique}", region_id=seoul_id)
    with pytest.raises(master_edit.EditError) as raised:
        master_edit.add_alias(pg, venue["venue_id"], f"다른 홀 {unique}", reviewer="kimpro")
    assert "이미" in str(raised.value)
    assert master_data.resolve_venue(pg, f"다른 홀 {unique}")["venue_id"] == other["venue_id"]


def test_an_alias_events_reach_the_venue_through_is_not_removed_by_accident(
        pg, unique, seoul_id):
    """Removing it means the next collection stops recognising that spelling."""
    _stored, venue = _linked_venue(pg, unique, seoul_id)
    aliases = master_data.venue_aliases(pg, venue["venue_id"])
    usage = master_data.venue_alias_usage(pg, venue["venue_id"])
    busy = [a for a in aliases if usage.get(a["venue_alias_id"], 0) > 0]
    assert busy, "the raw string alias should be carrying an event"

    with pytest.raises(master_edit.EditError) as raised:
        master_edit.remove_alias(pg, busy[0]["venue_alias_id"], reviewer="kimpro")
    assert "Event" in str(raised.value)
    assert master_data.get_venue_alias(pg, busy[0]["venue_alias_id"]) is not None


def test_an_alias_can_be_removed_once_the_operator_has_answered(pg, unique, seoul_id):
    _stored, venue = _linked_venue(pg, unique, seoul_id)
    aliases = master_data.venue_aliases(pg, venue["venue_id"])
    usage = master_data.venue_alias_usage(pg, venue["venue_id"])
    busy = [a for a in aliases if usage.get(a["venue_alias_id"], 0) > 0][0]

    removed = master_edit.remove_alias(
        pg, busy["venue_alias_id"], reviewer="kimpro", force=True,
    )
    assert removed["events_affected"] >= 1
    assert master_data.get_venue_alias(pg, busy["venue_alias_id"]) is None


# --- organizer --------------------------------------------------------------

def test_renaming_an_organizer_keeps_its_id(pg, unique, seoul_id):
    organizer = master_data.create_organizer(
        pg, name=f"주최자 {unique}", region_id=seoul_id,
    )
    result = master_edit.apply_edit(
        pg, master_edit.ORGANIZER, organizer["organizer_id"],
        {"name": f"Organizer {unique}", "contact_url": "https://example.invalid/x"},
        reviewer="kimpro",
    )
    assert result["entity"]["organizer_id"] == organizer["organizer_id"]
    assert result["entity"]["name"] == f"Organizer {unique}"
    assert result["entity"]["contact_url"] == "https://example.invalid/x"


def test_an_organizer_is_disabled_rather_than_deleted(pg, unique, seoul_id):
    organizer = master_data.create_organizer(pg, name=f"주최자 {unique}", region_id=seoul_id)
    result = master_edit.set_enabled(
        pg, master_edit.ORGANIZER, organizer["organizer_id"], False, reviewer="kimpro",
    )
    assert result["entity"]["enabled"] is False
    assert master_data.get_organizer(pg, organizer["organizer_id"]) is not None


# --- genre and region -------------------------------------------------------

def test_a_genre_display_name_is_editable_and_its_code_is_not(pg, unique):
    genre = master_data.create_genre(pg, code=f"TEST{unique}"[:12], name="Test Genre")
    result = master_edit.apply_edit(
        pg, master_edit.GENRE, genre["genre_id"], {"name": "Argentine Test"},
        reviewer="kimpro",
    )
    assert result["entity"]["name"] == "Argentine Test"
    assert result["entity"]["code"] == genre["code"]

    with pytest.raises(master_edit.EditError) as raised:
        master_edit.apply_edit(
            pg, master_edit.GENRE, genre["genre_id"], {"code": "MOVED"}, reviewer="kimpro",
        )
    assert "code" in str(raised.value)
    assert master_data.get_genre(pg, genre["genre_id"])["code"] == genre["code"]


def test_a_region_display_name_is_editable_and_its_code_is_not(pg, unique):
    region = master_data.create_region(
        pg, code=f"KR-T{unique}", country="South Korea", city="TestCity",
        name="TestCity",
    )
    result = master_edit.apply_edit(
        pg, master_edit.REGION, region["region_id"],
        {"name": "Test City", "district": "Test-gu"}, reviewer="kimpro",
    )
    assert result["entity"]["name"] == "Test City"
    assert result["entity"]["district"] == "Test-gu"
    assert result["entity"]["code"] == region["code"]

    with pytest.raises(master_edit.EditError):
        master_edit.apply_edit(
            pg, master_edit.REGION, region["region_id"], {"code": "KR-MOVED"},
            reviewer="kimpro",
        )


@pytest.mark.parametrize("entity_type", [master_edit.GENRE, master_edit.REGION])
def test_genres_and_regions_are_disabled_never_deleted(pg, unique, entity_type):
    if entity_type == master_edit.GENRE:
        row = master_data.create_genre(pg, code=f"DIS{unique}"[:12], name="Disable Me")
        entity_id = row["genre_id"]
        getter = master_data.get_genre
    else:
        row = master_data.create_region(
            pg, code=f"KR-D{unique}", country="South Korea", name="Disable Me",
        )
        entity_id = row["region_id"]
        getter = master_data.get_region

    master_edit.set_enabled(pg, entity_type, entity_id, False, reviewer="kimpro")
    assert getter(pg, entity_id)["enabled"] is False
    master_edit.set_enabled(pg, entity_type, entity_id, True, reviewer="kimpro")
    assert getter(pg, entity_id)["enabled"] is True


# --- source -----------------------------------------------------------------

def _source(pg, unique, **overrides):
    fields = {
        "source_key": f"SRC-T-{unique}", "name": f"테스트 소스 {unique}",
        "platform": "DAUM_CAFE", "source_role": "COMMUNITY",
        "url": "https://cafe.daum.net/latindance", "queries": ["밀롱가"],
    }
    fields.update(overrides)
    return sources.create_source(pg, **fields)


def test_a_sources_interval_can_be_changed_and_the_scheduler_uses_it(pg, unique):
    from datetime import datetime, timedelta, timezone

    source = _source(pg, unique, collection_interval_minutes=60)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    collected = {**source, "enabled": True, "last_collected_at": now - timedelta(minutes=45)}
    assert sources.is_due(collected, now=now) is False

    master_edit.apply_edit(
        pg, master_edit.SOURCE, source["source_id"],
        {"collection_interval_minutes": 30}, reviewer="kimpro",
    )
    updated = sources.get_source(pg, source["source_id"])
    assert updated["collection_interval_minutes"] == 30
    due = {**updated, "enabled": True, "last_collected_at": now - timedelta(minutes=45)}
    assert sources.is_due(due, now=now) is True


def test_an_interval_below_the_floor_is_refused_with_a_message(pg, unique):
    source = _source(pg, unique)
    with pytest.raises(master_edit.EditError) as raised:
        master_edit.apply_edit(
            pg, master_edit.SOURCE, source["source_id"],
            {"collection_interval_minutes": 1}, reviewer="kimpro",
        )
    assert str(sources.MIN_INTERVAL_MINUTES) in str(raised.value)
    assert sources.get_source(pg, source["source_id"])["collection_interval_minutes"] != 1


def test_enabling_through_an_edit_still_has_to_pass_validation(pg, unique):
    """v0.75's rule: from the moment a source is on, the scheduler fetches from
    it. Editing must not be a way around that."""
    source = _source(pg, unique, url=None, queries=[])
    with pytest.raises(master_edit.EditError):
        master_edit.apply_edit(
            pg, master_edit.SOURCE, source["source_id"], {"enabled": True},
            reviewer="kimpro",
        )
    assert sources.get_source(pg, source["source_id"])["enabled"] is False


def test_a_sources_key_cannot_be_edited(pg, unique):
    source = _source(pg, unique)
    with pytest.raises(master_edit.EditError):
        master_edit.apply_edit(
            pg, master_edit.SOURCE, source["source_id"], {"source_key": "SRC-MOVED"},
            reviewer="kimpro",
        )
    assert sources.get_source(pg, source["source_id"])["source_key"] == source["source_key"]


# --- audit ------------------------------------------------------------------

def test_an_edit_is_recorded_with_what_changed_and_who_changed_it(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"감사 홀 {unique}", region_id=seoul_id)
    master_edit.apply_edit(
        pg, master_edit.VENUE, venue["venue_id"],
        {"name": f"Audit Hall {unique}", "address": "서울 마포구 테스트로 1"},
        reviewer="kimpro",
    )
    recorded = master_edit.history(
        pg, entity_type=master_edit.VENUE, entity_id=venue["venue_id"],
    )[0]
    assert recorded["action"] == master_edit.EDIT
    assert recorded["reviewer"] == "kimpro"
    assert recorded["before_json"]["name"] == f"감사 홀 {unique}"
    assert recorded["after_json"]["name"] == f"Audit Hall {unique}"
    assert recorded["entity_name"] == f"Audit Hall {unique}"


def test_an_edit_that_changes_nothing_records_nothing(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"무변경 홀 {unique}", region_id=seoul_id)
    before = len(master_edit.history(pg, entity_type=master_edit.VENUE,
                                     entity_id=venue["venue_id"]))
    result = master_edit.apply_edit(
        pg, master_edit.VENUE, venue["venue_id"], {"name": f"무변경 홀 {unique}"},
        reviewer="kimpro",
    )
    assert result["changed"] == {}
    assert len(master_edit.history(pg, entity_type=master_edit.VENUE,
                                   entity_id=venue["venue_id"])) == before


def test_disabling_is_recorded_as_disabling_not_as_an_edit(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"토글 홀 {unique}", region_id=seoul_id)
    master_edit.set_enabled(pg, master_edit.VENUE, venue["venue_id"], False,
                            reviewer="kimpro")
    recorded = master_edit.history(pg, entity_type=master_edit.VENUE,
                                   entity_id=venue["venue_id"])[0]
    assert recorded["action"] == master_edit.DISABLE


def test_alias_changes_are_recorded(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"별칭 홀 {unique}", region_id=seoul_id)
    master_edit.add_alias(pg, venue["venue_id"], f"Alias {unique}", reviewer="kimpro")
    recorded = master_edit.history(pg, entity_type=master_edit.VENUE,
                                   entity_id=venue["venue_id"])[0]
    assert recorded["action"] == master_edit.ALIAS_ADD
    assert recorded["after_json"]["alias"] == f"Alias {unique}"


# --- errors and safety ------------------------------------------------------

def test_a_duplicate_name_in_one_region_is_a_message_not_a_500(pg, unique, seoul_id):
    master_data.create_venue(pg, name=f"중복 홀 {unique}", region_id=seoul_id)
    second = master_data.create_venue(pg, name=f"다른 홀 {unique}", region_id=seoul_id)
    with pytest.raises(master_edit.EditError) as raised:
        master_edit.apply_edit(
            pg, master_edit.VENUE, second["venue_id"], {"name": f"중복 홀 {unique}"},
            reviewer="kimpro",
        )
    assert "이미" in str(raised.value)


def test_the_same_name_in_a_different_region_is_allowed(pg, unique, seoul_id):
    """Studio A in Seoul and Studio A in Busan are different places, and the
    unique index says so."""
    other = master_data.create_region(
        pg, code=f"KR-O{unique}", country="South Korea", name=f"Other{unique}",
    )
    master_data.create_venue(pg, name=f"같은 이름 {unique}", region_id=seoul_id)
    elsewhere = master_data.create_venue(
        pg, name=f"임시 이름 {unique}", region_id=other["region_id"],
    )
    result = master_edit.apply_edit(
        pg, master_edit.VENUE, elsewhere["venue_id"], {"name": f"같은 이름 {unique}"},
        reviewer="kimpro",
    )
    assert result["entity"]["name"] == f"같은 이름 {unique}"


def test_an_empty_required_name_is_refused(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"이름 있음 {unique}", region_id=seoul_id)
    with pytest.raises(master_edit.EditError):
        master_edit.apply_edit(
            pg, master_edit.VENUE, venue["venue_id"], {"name": "   "}, reviewer="kimpro",
        )
    assert master_data.get_venue(pg, venue["venue_id"])["name"] == f"이름 있음 {unique}"


def test_editing_a_row_that_does_not_exist_is_a_message(pg):
    with pytest.raises(master_edit.EditError):
        master_edit.apply_edit(pg, master_edit.VENUE, 999999999, {"name": "x"})


def test_an_unknown_entity_is_refused(pg):
    with pytest.raises(master_edit.EditError):
        master_edit.apply_edit(pg, "SPACESHIP", 1, {"name": "x"})


def test_editing_never_removes_a_row(pg, unique, seoul_id):
    """Editing is not deleting. The v0.77.2 safe-delete rules stay the only way
    a venue goes away."""
    venue = master_data.create_venue(pg, name=f"유지 홀 {unique}", region_id=seoul_id)
    before = len(master_data.list_venues(pg))
    master_edit.apply_edit(pg, master_edit.VENUE, venue["venue_id"],
                           {"name": f"Renamed {unique}"}, reviewer="kimpro")
    master_edit.set_enabled(pg, master_edit.VENUE, venue["venue_id"], False,
                            reviewer="kimpro")
    assert len(master_data.list_venues(pg)) == before


# --- the console ------------------------------------------------------------

def test_every_edit_route_requires_authentication(client):
    for path in (
        "/admin/master-data/VENUE/1/edit",
        "/admin/master-data/VENUE/1/enabled",
        "/admin/master-data/VENUE/1/alias-add",
        "/admin/master-data/VENUE/1/alias-remove",
        "/admin/master-data/SOURCE/1/edit",
    ):
        assert client.post(path).status_code in (401, 503), path


def test_an_unknown_entity_in_the_url_is_a_404(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")
    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    response = client.post(
        "/admin/master-data/SPACESHIP/1/edit", auth=("tester", "test-only"),
    )
    assert response.status_code == 404


def test_the_form_opens_filled_in_with_what_the_row_says():
    """An empty form asks the operator to retype the record in front of them."""
    from runtime import master_admin

    rendered = master_admin.edit_form(
        master_edit.VENUE, 7,
        [master_admin.field("name", "Name", "라 벤따나"),
         master_admin.field("address", "Address", "서울 마포구 잔다리로 48, 2층")],
    )
    assert 'value="라 벤따나"' in rendered
    assert 'value="서울 마포구 잔다리로 48, 2층"' in rendered
    assert "Save Changes" in rendered
    assert "/admin/master-data/VENUE/7/edit" in rendered


def test_a_code_field_renders_read_only():
    from runtime import master_admin

    rendered = master_admin.field("code", "Code", "KR-SEOUL", kind="readonly",
                                  note="code는 수정할 수 없습니다")
    assert "disabled" in rendered
    assert 'name="code"' not in rendered
    assert "KR-SEOUL" in rendered


def test_a_venue_string_is_escaped_in_an_edit_form():
    from runtime import master_admin

    rendered = master_admin.edit_form(
        master_edit.VENUE, 1,
        [master_admin.field("name", "Name", '<script>alert(1)</script>')],
    )
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_the_alias_editor_shows_how_much_work_each_alias_is_doing():
    from runtime import master_admin

    rendered = master_admin.alias_editor(
        {"venue_id": 7, "name": "라 벤따나"},
        [{"venue_alias_id": 1, "alias": "라 벤따나"},
         {"venue_alias_id": 2, "alias": "La Ventana"}],
        {1: 2},
    )
    assert "2 event" in rendered
    assert "unused" in rendered
    assert "Add Alias" in rendered
