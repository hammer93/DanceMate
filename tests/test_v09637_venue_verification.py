"""v0.96.37 Venue Human Verification & Safe Regional Coverage Recovery.

The decisions themselves (Link Existing, New Venue, Group Apply, Not a venue)
predate this release. What it adds is everything around them that an operator
needs to decide safely, and that the database needs to stay consistent:

* a read-only preview of every decision - the events it moves, their region,
  their identity keys, and what the next duplicates scan would fold - and a
  confirm that is accepted only with that preview's token;
* refusals the old code did not make: deciding an entry twice, linking a
  string to a venue in a city its own words exclude, registering a spelling
  another venue owns, half of a Group Apply;
* a link made without an alias that survives the next re-normalization;
* a Revert that takes one decision back without deleting a real venue;
* a queue ordered by what a dancer would see change.

Every write test runs on the rolled-back ``pg`` connection; the route tests
hand the app that same connection, so nothing here commits anywhere.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

import pytest

from runtime import (
    duplicates,
    events_api,
    master_data,
    normalization,
    venue_resolution,
)

DAEJEON_ONADA = "대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)"
PASION = "Tango Pasion (탱고 빠시온) (서울 마포구 월드컵북로6길 69 B1)"
LA_VIDA = "La Vida Studio (라 비다 스튜디오) (서울시 서초구 방배천로 60 청도빌딩 B1F)"


def _day(offset: int = 10) -> str:
    return (events_api.today() + timedelta(days=offset)).isoformat()


def _candidate(unique: str, suffix: str, **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/v37/{unique}-{suffix}",
        "event_name": f"검증 밀롱가 {unique}-{suffix}",
        "event_type": "MILONGA",
        "event_date": _day(),
        "start_time": "20:00",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"검증홀 {unique}",
        "fee": 15000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    base.update(overrides)
    return base


def _event(pg, unique, suffix, *, alias_candidates=None, **overrides) -> dict:
    return normalization.normalize_candidate(pg, _candidate(unique, suffix, **overrides),
                                             alias_candidates=alias_candidates)


def _entry(pg, text: str) -> dict:
    with pg.cursor() as cur:
        cur.execute("SELECT unresolved_venue_id FROM unresolved_venues "
                    "WHERE normalized_text = %s", (master_data.normalize_alias(text),))
        row = cur.fetchone()
    assert row, f"{text!r} is not queued"
    return normalization.unresolved_venue(pg, row[0])


def _region(pg, code: str) -> int:
    for region in master_data.list_regions(pg):
        if region["code"] == code:
            return region["region_id"]
    pytest.skip(f"{code} is not seeded")


def _venue(pg, name: str, code: str, **fields) -> dict:
    """The registered venue for this name, in this region.

    A freshly migrated database seeds some real studios (022) with no region;
    the board's Master has them in their city, and that is the case under test.
    """
    found = master_data.resolve_venue(pg, name)
    if found:
        if found.get("region_id") != _region(pg, code):
            found = master_data.update_venue(pg, found["venue_id"], region_id=_region(pg, code))
        return found
    return master_data.create_venue(pg, name=name, region_id=_region(pg, code), **fields)


def _fingerprint(pg) -> tuple:
    """Everything a venue decision could write, in one comparable value."""
    with pg.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM venues), (SELECT count(*) FROM venue_aliases), "
            "(SELECT count(*) FROM venue_resolution_actions), "
            "(SELECT md5(string_agg(unresolved_venue_id || state || "
            "   coalesce(resolved_venue_id::text, ''), ',' ORDER BY unresolved_venue_id)) "
            " FROM unresolved_venues), "
            "(SELECT md5(string_agg(event_id || ':' || coalesce(venue_id::text, '') || ':' "
            "   || coalesce(region_id::text, '') || ':' || venue_status || ':' "
            "   || identity_key || ':' || coalesce(canonical_event_id::text, ''), ',' "
            "   ORDER BY event_id)) FROM events)"
        )
        return cur.fetchone()


def _row(pg, event_id: int) -> dict:
    return normalization.get(pg, event_id)


def _ids(result: dict) -> set[int]:
    return {e["id"] for e in result["events"]}


@pytest.fixture
def onada(pg, unique):
    """The v0.96.32 pair: Daejeon's 땅고 오나다 and Seoul's Tango O Nada, one
    Friday night each, same hour."""
    seoul = _venue(pg, "Tango O Nada", "KR-SEOUL")
    seoul_event = _event(pg, unique, "1", venue="Tango O Nada",
                         event_name=f"오나다 금요밀롱가 {unique}")
    daejeon_event = _event(pg, unique, "2", venue=DAEJEON_ONADA,
                           event_name=f"대전 오나다 밀롱가 {unique}")
    return {"seoul": seoul, "seoul_event": seoul_event,
            "daejeon_event": daejeon_event, "entry": _entry(pg, DAEJEON_ONADA)}


# --- the queue ---------------------------------------------------------------

def test_the_queue_counts_upcoming_listed_events_once_each(pg, unique):
    text = f"예정홀 {unique}"
    _event(pg, unique, "1", venue=text)
    _event(pg, unique, "2", venue=text, event_date=_day(-30))           # past
    _event(pg, unique, "3", venue=text, provenance="UNKNOWN")           # not live
    entry = next(e for e in normalization.unresolved_venues(pg, limit=5000)
                 if e["venue_text"] == text)
    assert entry["event_count"] == 3
    assert entry["live_event_count"] == 2
    assert entry["upcoming_event_count"] == 1


def test_the_queue_puts_upcoming_impact_first(pg, unique):
    past_heavy = f"과거많음 {unique}"
    upcoming = f"다음주 {unique}"
    for n in range(4):
        _event(pg, unique, f"1{n}", venue=past_heavy, event_date=_day(-40 - n))
    _event(pg, unique, "20", venue=upcoming)
    order = [e["venue_text"] for e in normalization.unresolved_venues(pg, limit=5000)
             if e["venue_text"] in (past_heavy, upcoming)]
    assert order == [upcoming, past_heavy]


@pytest.mark.parametrize("raw,name,address", [
    (PASION, "Tango Pasion", "서울 마포구 월드컵북로6길 69 B1"),
    (LA_VIDA, "La Vida Studio", "서울시 서초구 방배천로 60 청도빌딩 B1F"),
    ("박미 탱고 (경상남도 창원시 마산합포구 창동거리길 24-2 (창동) 2층)", "박미 탱고",
     "경상남도 창원시 마산합포구 창동거리길 24-2 (창동) 2층"),
    (DAEJEON_ONADA, "대전 땅고 오나다", "대전시 유성구 대학로76번안길 23 지하"),
    ("라 벤따나 (서울 마포구 잔다리로 48, 2층)", "라 벤따나", "서울 마포구 잔다리로 48, 2층"),
])
def test_a_name_its_other_name_and_its_address_are_told_apart(raw, name, address):
    suggestion = venue_resolution.suggest(raw)
    assert suggestion["name"] == name
    assert suggestion["address"] == address
    assert raw in suggestion["aliases"]


def test_the_engines_bare_address_reading_is_not_offered_as_an_alias():
    """It goes in the address field: as a spelling of the venue it would
    answer for every other room in the building."""
    suggestion = venue_resolution.suggest(
        LA_VIDA, ["La Vida Studio", "라 비다 스튜디오", "서울시 서초구 방배천로 60 청도빌딩 B1F"])
    assert "서울시 서초구 방배천로 60 청도빌딩 B1F" not in suggestion["aliases"]
    assert suggestion["address"] == "서울시 서초구 방배천로 60 청도빌딩 B1F"
    assert LA_VIDA in suggestion["aliases"] and "라 비다 스튜디오" in suggestion["aliases"]
    # A raw string that is itself an address is still the raw string.
    assert venue_resolution.suggest("서초구 반포대로 30길 82 B1")["name"] == "서초구 반포대로 30길 82 B1"


def test_two_address_brackets_fill_in_neither():
    suggestion = venue_resolution.suggest("홀 (서울 마포구 a로 1) (부산 부산진구 b로 2)")
    assert suggestion["name"] == "홀"
    assert suggestion["address"] is None


@pytest.mark.parametrize("raw", ["엔빠스(EnPaz Tango Studio)", "OCHO", "a (b", "(서울 마포구 x로 1)"])
def test_a_bracket_that_is_not_an_address_is_never_one(raw):
    assert venue_resolution.suggest(raw)["address"] is None


@pytest.mark.parametrize("hint,code", [
    ("경상남도", "KR-GYEONGNAM"), ("경남", "KR-GYEONGNAM"), ("충청북도", "KR-CHUNGBUK"),
    ("전라남도", "KR-JEONNAM"), ("서울특별시", "KR-SEOUL"), ("부산", "KR-BUSAN"),
])
def test_a_provinces_full_name_selects_its_region(pg, hint, code):
    assert venue_resolution.suggested_region_id(pg, hint) == _region(pg, code)


def test_an_address_stops_before_the_bank_account():
    assert venue_resolution._trim_address(
        "제주시 노연로 110, 3층 카카오뱅크 3333-33-4203961 강명호") == "제주시 노연로 110, 3층"


def test_daejeon_onada_is_never_suggested_as_seouls_with_confidence(pg, onada):
    suggestion = venue_resolution.prefill(pg, onada["entry"])
    ranked = venue_resolution.suggest_venue_links(
        pg, name=suggestion["name"], address=suggestion["address"],
        raw_venue=DAEJEON_ONADA, region_id=suggestion["region_id"])
    seoul = [r for r in ranked if r["venue_id"] == onada["seoul"]["venue_id"]]
    assert all(r["confidence"] == venue_resolution.CONFIDENCE_LOW for r in seoul)
    assert suggestion["region_id"] == _region(pg, "KR-DAEJEON")


# --- previews write nothing --------------------------------------------------

def test_every_preview_is_read_only(pg, unique, onada):
    pasion = _event(pg, unique, "5", venue=PASION)
    target = _venue(pg, f"검증장소 {unique}", "KR-SEOUL")
    before = _fingerprint(pg)
    venue_resolution.preview_link(pg, unresolved_venue_id=_entry(pg, PASION)["unresolved_venue_id"],
                                  venue_id=target["venue_id"])
    venue_resolution.preview_create(pg, unresolved_venue_id=onada["entry"]["unresolved_venue_id"],
                                    name="대전 땅고 오나다", region_id=_region(pg, "KR-DAEJEON"),
                                    address="대전시 유성구 대학로76번안길 23 지하")
    venue_resolution.preview_group(pg, unresolved_venue_ids=[_entry(pg, PASION)["unresolved_venue_id"]],
                                   venue_id=target["venue_id"])
    venue_resolution.preview_revert(pg, unresolved_venue_id=_entry(pg, PASION)["unresolved_venue_id"])
    assert _fingerprint(pg) == before
    assert _row(pg, pasion["event_id"])["venue_status"] == normalization.VENUE_UNRESOLVED


def test_the_link_preview_shows_every_event_it_would_move(pg, unique):
    events = [_event(pg, unique, str(n), venue=PASION, event_date=_day(n)) for n in (3, 10, 17)]
    venue = _venue(pg, "Tango Pasion", "KR-SEOUL", address="서울 마포구 월드컵북로6길 69 B1")
    preview = venue_resolution.preview_link(
        pg, unresolved_venue_id=_entry(pg, PASION)["unresolved_venue_id"],
        venue_id=venue["venue_id"])
    assert preview["blockers"] == []
    assert [e["event_id"] for e in preview["events"]] == [e["event_id"] for e in events]
    assert all(e["proposed_region_code"] == "KR-SEOUL" for e in preview["events"])
    assert all(e["identity_changes"] for e in preview["events"])
    assert preview["summary"]["upcoming_visible"] == 3
    assert preview["alias_plan"][0]["status"] == "NEW"
    assert preview["evidence"]["posts"]


def test_the_create_preview_reports_region_address_and_duplicates(pg, unique, onada):
    preview = venue_resolution.preview_create(
        pg, unresolved_venue_id=onada["entry"]["unresolved_venue_id"],
        name="대전 땅고 오나다", region_id=_region(pg, "KR-DAEJEON"),
        address="대전시 유성구 대학로76번안길 23 지하")
    assert preview["blockers"] == []
    assert preview["venue"]["region_code"] == "KR-DAEJEON"
    assert [e["event_id"] for e in preview["events"]] == [onada["daejeon_event"]["event_id"]]
    # Seoul's Tango O Nada shares neither the name nor the address, so it is
    # not offered as the same place - and nothing folds with its night.
    assert all(m["venue_id"] != onada["seoul"]["venue_id"] for m in preview["duplicates"])
    assert all(o["other_event_id"] != onada["seoul_event"]["event_id"]
               for o in preview["canonical"])


# --- what a confirm refuses, writing nothing ---------------------------------

def test_daejeon_onada_cannot_be_linked_to_seouls_tango_o_nada(pg, onada):
    before = _fingerprint(pg)
    preview = venue_resolution.preview_link(
        pg, unresolved_venue_id=onada["entry"]["unresolved_venue_id"],
        venue_id=onada["seoul"]["venue_id"])
    assert any("different city" in b for b in preview["blockers"])
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.confirm_link(
            pg, unresolved_venue_id=onada["entry"]["unresolved_venue_id"],
            venue_id=onada["seoul"]["venue_id"], token=preview["token"])
    # The plain library call refuses it as well - not only the console.
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.link_existing(
            pg, unresolved_venue_id=onada["entry"]["unresolved_venue_id"],
            venue_id=onada["seoul"]["venue_id"])
    assert _fingerprint(pg) == before


def test_a_new_venue_in_the_wrong_city_is_refused(pg, onada):
    before = _fingerprint(pg)
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.create_and_link(
            pg, unresolved_venue_id=onada["entry"]["unresolved_venue_id"],
            name="대전 땅고 오나다", region_id=_region(pg, "KR-SEOUL"), force=True)
    assert _fingerprint(pg) == before


def test_a_confirm_without_its_preview_token_writes_nothing(pg, unique):
    _event(pg, unique, "1", venue=PASION)
    venue = _venue(pg, "Tango Pasion", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    before = _fingerprint(pg)
    for token in (None, "", "0" * 64):
        with pytest.raises(venue_resolution.StalePreview):
            venue_resolution.confirm_link(pg, unresolved_venue_id=uid,
                                          venue_id=venue["venue_id"], token=token)
    assert _fingerprint(pg) == before


def test_a_preview_goes_stale_when_a_new_post_waits_on_the_string(pg, unique):
    _event(pg, unique, "1", venue=PASION)
    venue = _venue(pg, "Tango Pasion", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"])
    _event(pg, unique, "2", venue=PASION, event_date=_day(17))   # arrives after the preview
    before = _fingerprint(pg)
    with pytest.raises(venue_resolution.StalePreview):
        venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                      token=preview["token"])
    assert _fingerprint(pg) == before


def test_a_token_for_one_venue_does_not_confirm_another(pg, unique):
    _event(pg, unique, "1", venue=PASION)
    right = _venue(pg, "Tango Pasion", "KR-SEOUL")
    other = _venue(pg, f"다른장소 {unique}", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=right["venue_id"])
    with pytest.raises(venue_resolution.StalePreview):
        venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=other["venue_id"],
                                      token=preview["token"])


def test_an_entry_is_decided_once(pg, unique):
    _event(pg, unique, "1", venue=PASION)
    first = _venue(pg, "Tango Pasion", "KR-SEOUL")
    second = _venue(pg, f"두번째 {unique}", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=first["venue_id"])
    venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=first["venue_id"],
                                  token=preview["token"], reviewer="tester")
    before = _fingerprint(pg)
    # The same confirm replayed, a second link, a New Venue and a dismiss: all refused.
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=first["venue_id"],
                                      token=preview["token"])
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.link_existing(pg, unresolved_venue_id=uid, venue_id=second["venue_id"])
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.create_and_link(pg, unresolved_venue_id=uid, name=f"또 {unique}",
                                         force=True)
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.dismiss(pg, unresolved_venue_id=uid)
    assert _fingerprint(pg) == before
    assert normalization.unresolved_venue(pg, uid)["resolved_venue_id"] == first["venue_id"]


def test_a_possible_duplicate_needs_an_answer_that_the_token_remembers(pg, unique):
    text = f"중복후보 {unique}"
    _event(pg, unique, "1", venue=text)
    existing = _venue(pg, f"중복후보 {unique}", "KR-SEOUL")
    master_data.remove_venue_alias(pg, next(
        a["venue_alias_id"] for a in master_data.venue_aliases(pg, existing["venue_id"])))
    uid = _entry(pg, text)["unresolved_venue_id"]
    # Same name, another city's branch: a question, not a refusal.
    busan = _region(pg, "KR-BUSAN")
    asked = venue_resolution.preview_create(pg, unresolved_venue_id=uid, name=text,
                                            region_id=busan)
    assert asked["duplicates"] and asked["blockers"]
    answered = venue_resolution.preview_create(pg, unresolved_venue_id=uid, name=text,
                                               region_id=busan, force=True)
    assert answered["blockers"] == [] and answered["token"] != asked["token"]
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.confirm_create(pg, unresolved_venue_id=uid, name=text,
                                        region_id=busan, token=asked["token"])
    result = venue_resolution.confirm_create(pg, unresolved_venue_id=uid, name=text,
                                             region_id=busan, force=True,
                                             token=answered["token"])
    assert result["venue"]["venue_id"] != existing["venue_id"]


def test_a_spelling_another_venue_owns_is_not_registered_to_this_one(pg, unique):
    owner = _venue(pg, f"주인장소 {unique}", "KR-BUSAN")
    text = f"별칭주인 {unique}"
    _event(pg, unique, "1", venue=f"{text} 서면")
    uid = _entry(pg, f"{text} 서면")["unresolved_venue_id"]
    preview = venue_resolution.preview_create(
        pg, unresolved_venue_id=uid, name=f"새장소 {unique}",
        region_id=_region(pg, "KR-BUSAN"), aliases=[f"주인장소 {unique}"])
    assert any("already belongs to" in b for b in preview["blockers"])
    owned = [a for a in preview["alias_plan"] if a["status"] == "OWNED_BY_OTHER_VENUE"]
    assert owned and owned[0]["owner_venue_id"] == owner["venue_id"]


def test_invalid_ids_change_nothing(pg, unique):
    _event(pg, unique, "1", venue=PASION)
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    before = _fingerprint(pg)
    with pytest.raises(LookupError):
        venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=987654321)
    with pytest.raises(LookupError):
        venue_resolution.preview_link(pg, unresolved_venue_id=987654321, venue_id=1)
    with pytest.raises(LookupError):
        venue_resolution.confirm_create(pg, unresolved_venue_id=987654321, name="x", token="t")
    assert _fingerprint(pg) == before


def test_a_failure_inside_the_confirm_leaves_no_partial_write(pg, unique, monkeypatch):
    _event(pg, unique, "1", venue=PASION)
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    seoul = _region(pg, "KR-SEOUL")
    preview = venue_resolution.preview_create(pg, unresolved_venue_id=uid, name="Tango Pasion",
                                              region_id=seoul, address="서울 마포구 월드컵북로6길 69 B1")
    before = _fingerprint(pg)

    def explode(*args, **kwargs):
        raise RuntimeError("the audit write failed")

    monkeypatch.setattr(venue_resolution, "record_action", explode)
    with pytest.raises(RuntimeError):
        venue_resolution.confirm_create(pg, unresolved_venue_id=uid, name="Tango Pasion",
                                        region_id=seoul, address="서울 마포구 월드컵북로6길 69 B1",
                                        token=preview["token"])
    assert _fingerprint(pg) == before


# --- an approved decision, end to end ----------------------------------------

def test_an_approved_daejeon_venue_reaches_the_daejeon_filter_and_not_seouls(pg, unique, onada):
    daejeon = _region(pg, "KR-DAEJEON")
    seoul_id = onada["seoul_event"]["event_id"]
    daejeon_id = onada["daejeon_event"]["event_id"]
    assert onada["daejeon_event"]["venue_id"] is None
    assert onada["daejeon_event"]["region_id"] is None
    before_identity = _row(pg, daejeon_id)["event_id"]

    preview = venue_resolution.preview_create(
        pg, unresolved_venue_id=onada["entry"]["unresolved_venue_id"],
        name="대전 땅고 오나다", region_id=daejeon, address="대전시 유성구 대학로76번안길 23 지하")
    result = venue_resolution.confirm_create(
        pg, unresolved_venue_id=onada["entry"]["unresolved_venue_id"], name="대전 땅고 오나다",
        region_id=daejeon, address="대전시 유성구 대학로76번안길 23 지하",
        token=preview["token"], reviewer="human-approved-tester")
    venue = result["venue"]
    after = _row(pg, daejeon_id)
    assert after["event_id"] == before_identity            # the same event, kept
    assert after["venue_id"] == venue["venue_id"]
    assert after["region_id"] == daejeon
    assert after["identity_key"] == normalization.identity_key(
        after["event_date"], normalization.venue_key(venue["venue_id"], DAEJEON_ONADA),
        after["start_time"])
    assert DAEJEON_ONADA in [a["alias"] for a in master_data.venue_aliases(pg, venue["venue_id"])]

    duplicates.scan(pg, on=after["event_date"])
    assert _row(pg, seoul_id)["canonical_event_id"] is None
    assert _row(pg, daejeon_id)["canonical_event_id"] is None
    day = after["event_date"]
    in_daejeon = _ids(events_api.search(pg, on=day, region="KR-DAEJEON"))
    in_daejeon_label = _ids(events_api.search(pg, on=day, region="대전"))
    in_seoul = _ids(events_api.search(pg, on=day, region="KR-SEOUL"))
    assert daejeon_id in in_daejeon and daejeon_id in in_daejeon_label
    assert daejeon_id not in in_seoul
    assert seoul_id in in_seoul and seoul_id not in in_daejeon
    assert in_daejeon == in_daejeon_label


def test_the_audit_row_says_who_what_and_which_preview(pg, unique):
    _event(pg, unique, "1", venue=PASION)
    venue = _venue(pg, "Tango Pasion", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"])
    result = venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                           token=preview["token"], reviewer="kim-pro")
    action = result["action"]
    assert action["reviewer"] == "kim-pro"
    assert action["action"] == venue_resolution.LINK_EXISTING
    assert action["unresolved_venue_id"] == uid
    assert action["after_json"]["preview_token"] == preview["token"][:16]
    assert action["after_json"]["event_ids"] == [e["event_id"] for e in preview["events"]]
    assert action["events_updated"] == len(preview["events"])


def test_the_preview_predicts_the_fold_the_scan_then_makes(pg, unique):
    """Two posts about one night at one place: a question while the place is
    unresolved, an automatic fold once a person has said what the place is."""
    first = _event(pg, unique, "1", venue=PASION)
    second = _event(pg, unique, "2", venue=PASION, source_url=f"https://x.test/{unique}-other")
    venue = _venue(pg, "Tango Pasion", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"])
    folds = [o for o in preview["canonical"] if o["outcome"] == "AUTO_FOLD"]
    assert len(folds) == 1
    assert {folds[0]["event_id"], folds[0]["other_event_id"]} == {first["event_id"], second["event_id"]}
    venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                  token=preview["token"])
    duplicates.scan(pg, on=_row(pg, first["event_id"])["event_date"])
    folded = [e for e in (first, second) if _row(pg, e["event_id"])["canonical_event_id"]]
    assert len(folded) == 1


def test_a_group_is_applied_whole_or_not_at_all(pg, unique, onada):
    a, b = f"그룹A {unique}", f"그룹B {unique}"
    _event(pg, unique, "5", venue=a)
    _event(pg, unique, "6", venue=b)
    venue = _venue(pg, f"그룹장소 {unique}", "KR-SEOUL")
    ids = [_entry(pg, a)["unresolved_venue_id"], _entry(pg, b)["unresolved_venue_id"],
           onada["entry"]["unresolved_venue_id"]]           # Daejeon cannot join a Seoul venue
    preview = venue_resolution.preview_group(pg, unresolved_venue_ids=ids, venue_id=venue["venue_id"])
    assert preview["blockers"]
    before = _fingerprint(pg)
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.confirm_group(pg, unresolved_venue_ids=ids, venue_id=venue["venue_id"],
                                       token=preview["token"])
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.group_link_existing(pg, unresolved_venue_ids=ids,
                                             venue_id=venue["venue_id"])
    assert _fingerprint(pg) == before

    good = ids[:2]
    preview = venue_resolution.preview_group(pg, unresolved_venue_ids=good, venue_id=venue["venue_id"])
    result = venue_resolution.confirm_group(pg, unresolved_venue_ids=good, venue_id=venue["venue_id"],
                                            token=preview["token"])
    assert result["linked_count"] == 2 and result["errors"] == []


def test_a_link_without_an_alias_survives_the_next_renormalization(pg, unique):
    text = f"별칭없이 {unique}"
    stored = _event(pg, unique, "1", venue=text)
    venue = _venue(pg, f"별칭없이장소 {unique}", "KR-SEOUL")
    uid = _entry(pg, text)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                            add_alias=False)
    venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                  add_alias=False, token=preview["token"])
    assert text not in [a["alias"] for a in master_data.venue_aliases(pg, venue["venue_id"])]
    # Re-read exactly as the scheduler would after any Venue Master change.
    again = normalization.normalize_candidate(pg, _candidate(unique, "1", venue=text))
    assert again["event_id"] == stored["event_id"]
    assert again["venue_id"] == venue["venue_id"]
    assert again["venue_status"] == normalization.VENUE_RESOLVED


def test_a_linked_decision_never_crosses_a_city(pg, onada, unique):
    """The decision read back by normalization obeys the same region rule as
    an alias, so even a stored wrong-city decision cannot place an event."""
    with pg.cursor() as cur:
        cur.execute("UPDATE unresolved_venues SET state = 'LINKED', resolved_venue_id = %s "
                    "WHERE unresolved_venue_id = %s",
                    (onada["seoul"]["venue_id"], onada["entry"]["unresolved_venue_id"]))
    resolution = normalization.resolve_venue(pg, DAEJEON_ONADA)
    assert resolution["venue_status"] == normalization.VENUE_UNRESOLVED


# --- taking a decision back --------------------------------------------------

def test_revert_puts_back_exactly_what_the_link_changed(pg, unique):
    first = _event(pg, unique, "1", venue=PASION)
    second = _event(pg, unique, "2", venue=PASION, source_url=f"https://x.test/{unique}-other")
    venue = _venue(pg, "Tango Pasion", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    original = {e["event_id"]: _row(pg, e["event_id"]) for e in (first, second)}
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"])
    venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                  token=preview["token"], reviewer="tester")
    duplicates.scan(pg, on=original[first["event_id"]]["event_date"])
    assert any(_row(pg, i)["canonical_event_id"] for i in original)

    back = venue_resolution.preview_revert(pg, unresolved_venue_id=uid)
    assert back["blockers"] == []
    assert back["summary"]["events"] == 2 and back["summary"]["released_folds"] == 1
    result = venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"],
                                              reviewer="tester")
    assert result["alias_removed"] == PASION
    for event_id, was in original.items():
        now = _row(pg, event_id)
        assert now["event_id"] == was["event_id"]
        assert now["venue_id"] is None and now["region_id"] is None
        assert now["venue_status"] == normalization.VENUE_UNRESOLVED
        assert now["identity_key"] == was["identity_key"]
        assert now["canonical_event_id"] is None
    assert normalization.unresolved_venue(pg, uid)["state"] == "OPEN"
    assert master_data.get_venue(pg, venue["venue_id"]) is not None   # the place stays
    trail = [a["action"] for a in venue_resolution.history(pg, limit=10)
             if a["unresolved_venue_id"] == uid]
    assert trail[:2] == [venue_resolution.DECISION_REVERT, venue_resolution.LINK_EXISTING]
    # And the next re-read agrees: the string resolves to nothing again.
    assert normalization.resolve_venue(pg, PASION)["venue_status"] == normalization.VENUE_UNRESOLVED


def test_a_revert_the_next_normalization_would_undo_is_refused(pg, unique):
    """Found on the Production clone: New Venue for La Vida registers the
    venue's own name, and the engine reads `La Vida Studio` beside the raw
    string - so taking only the raw string's alias away re-links every event
    on the next re-read."""
    readings = [LA_VIDA, "La Vida Studio", "라 비다 스튜디오"]
    stored = _event(pg, unique, "1", venue=LA_VIDA, alias_candidates=readings)
    uid = _entry(pg, LA_VIDA)["unresolved_venue_id"]
    seoul = _region(pg, "KR-SEOUL")
    preview = venue_resolution.preview_create(pg, unresolved_venue_id=uid, name="La Vida Studio",
                                              region_id=seoul)
    venue_resolution.confirm_create(pg, unresolved_venue_id=uid, name="La Vida Studio",
                                    region_id=seoul, token=preview["token"])
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=uid)
    assert any("would link these events again" in b for b in back["blockers"])
    before = _fingerprint(pg)
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"])
    assert _fingerprint(pg) == before
    # The way out it names: Unlink & Delete, which the next re-read agrees with.
    venue = _row(pg, stored["event_id"])["venue_id"]
    venue_resolution.delete_venue(pg, venue, unlink=True, reviewer="tester")
    again = normalization.normalize_candidate(pg, _candidate(unique, "1", venue=LA_VIDA),
                                              alias_candidates=readings)
    assert again["venue_status"] == normalization.VENUE_UNRESOLVED


def test_an_allowed_revert_survives_the_next_normalization(pg, unique):
    readings = [PASION, "Tango Pasion", "탱고 빠시온"]
    stored = _event(pg, unique, "1", venue=PASION, alias_candidates=readings)
    wrong = _venue(pg, f"엉뚱한 장소 {unique}", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=wrong["venue_id"])
    venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=wrong["venue_id"],
                                  token=preview["token"])
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=uid)
    assert back["blockers"] == []
    venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"])
    again = normalization.normalize_candidate(pg, _candidate(unique, "1", venue=PASION),
                                              alias_candidates=readings)
    assert again["event_id"] == stored["event_id"]
    assert again["venue_status"] == normalization.VENUE_UNRESOLVED
    assert again["identity_key"] == stored["identity_key"]


def test_revert_leaves_a_persons_merge_alone(pg, unique):
    first = _event(pg, unique, "1", venue=PASION)
    other = _event(pg, unique, "2", venue="Tango O Nada", start_time="21:00")
    venue = _venue(pg, "Tango Pasion", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"])
    venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                  token=preview["token"])
    duplicates.record_decision(pg, event_id=first["event_id"],
                               canonical_event_id=other["event_id"],
                               decision=duplicates.DUPLICATE, decided_by=duplicates.HUMAN,
                               rule="HUMAN_REVIEW", reason="a person said so")
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=uid)
    assert back["summary"]["released_folds"] == 0
    venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"])
    assert _row(pg, first["event_id"])["canonical_event_id"] == other["event_id"]


def test_revert_of_not_a_venue_reopens_the_entry_only(pg, unique):
    text = f"오판정 {unique}"
    stored = _event(pg, unique, "1", venue=text)
    uid = _entry(pg, text)["unresolved_venue_id"]
    venue_resolution.dismiss(pg, unresolved_venue_id=uid, reviewer="tester")
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=uid)
    assert back["blockers"] == [] and back["summary"]["events"] == 0
    venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"])
    assert normalization.unresolved_venue(pg, uid)["state"] == "OPEN"
    assert _row(pg, stored["event_id"])["venue_status"] == normalization.VENUE_UNRESOLVED


def test_revert_refuses_an_open_entry_and_a_venues_own_name(pg, unique):
    text = f"자기이름 {unique}"
    _event(pg, unique, "1", venue=text)
    uid = _entry(pg, text)["unresolved_venue_id"]
    assert venue_resolution.preview_revert(pg, unresolved_venue_id=uid)["blockers"]
    preview = venue_resolution.preview_create(pg, unresolved_venue_id=uid, name=text,
                                              region_id=_region(pg, "KR-SEOUL"))
    venue_resolution.confirm_create(pg, unresolved_venue_id=uid, name=text,
                                    region_id=_region(pg, "KR-SEOUL"), token=preview["token"])
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=uid)
    assert any("own name" in b for b in back["blockers"])
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"])


# --- the existing Master spellings stay as they were -------------------------

def test_ideal_and_amigo_hall_still_resolve_to_their_venues(pg):
    ideal = master_data.resolve_venue(pg, "이데알 탱고 까페")
    hall = master_data.resolve_venue(pg, "아미고 큰홀")
    studio = master_data.resolve_venue(pg, "아미고 스튜디오") or master_data.resolve_venue(
        pg, "Amigo Studio")
    if hall is None or studio is None:
        pytest.skip("the tango venue seed (022/045) is not in this database")
    assert hall["venue_id"] == studio["venue_id"]
    if ideal is not None:
        assert normalization.resolve_venue(pg, "이데알 탱고 까페")["venue_id"] == ideal["venue_id"]


# --- the console --------------------------------------------------------------

class _Shared:
    """The test's own connection, handed to the app; commit/rollback are the
    test's business, so here they do nothing."""

    def __init__(self, con):
        self._con = con

    def commit(self):
        pass

    def rollback(self):
        pass

    def __getattr__(self, name):
        return getattr(self._con, name)


@pytest.fixture
def console(pg, monkeypatch):
    from fastapi.testclient import TestClient

    from runtime import admin, db
    from runtime.app import app

    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")

    @contextmanager
    def shared(*args, **kwargs):
        yield _Shared(pg)

    monkeypatch.setattr(admin, "_connection", shared)
    monkeypatch.setattr(db, "connect", shared)
    client = TestClient(app)
    client.auth = ("tester", "test-only")
    return client


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


def test_every_new_venue_route_requires_authentication(client):
    for path in ("/admin/venues/unresolved/1/link/preview",
                 "/admin/venues/unresolved/1/create/preview",
                 "/admin/venues/unresolved/1/revert/preview",
                 "/admin/venues/unresolved/1/revert"):
        assert client.post(path).status_code in (401, 503), path


def test_the_console_previews_then_confirms_with_the_token(console, pg, unique):
    import re

    _event(pg, unique, "1", venue=PASION)
    venue = _venue(pg, "Tango Pasion", "KR-SEOUL")
    uid = _entry(pg, PASION)["unresolved_venue_id"]
    before = _fingerprint(pg)
    page = console.post(f"/admin/venues/unresolved/{uid}/link/preview",
                        data={"venue_id": str(venue["venue_id"]), "add_alias": "1"})
    assert page.status_code == 200
    assert "Confirm &amp; Link" in page.text and "바뀌는 Event" in page.text
    assert _fingerprint(pg) == before
    token = re.search(r'name="token" value="([0-9a-f]{64})"', page.text).group(1)

    forged = console.post(f"/admin/venues/unresolved/{uid}/link",
                          data={"venue_id": str(venue["venue_id"]), "add_alias": "1",
                                "token": "f" * 64}, follow_redirects=False)
    assert forged.status_code == 409
    assert _fingerprint(pg) == before

    done = console.post(f"/admin/venues/unresolved/{uid}/link",
                        data={"venue_id": str(venue["venue_id"]), "add_alias": "1",
                              "token": token}, follow_redirects=False)
    assert done.status_code in (302, 303)
    assert normalization.unresolved_venue(pg, uid)["state"] == "LINKED"


def test_the_console_shows_a_blocked_preview_without_a_confirm_button(console, pg, onada):
    page = console.post(
        f"/admin/venues/unresolved/{onada['entry']['unresolved_venue_id']}/link/preview",
        data={"venue_id": str(onada["seoul"]["venue_id"]), "add_alias": "1"})
    assert page.status_code == 409
    assert "승인할 수 없습니다" in page.text
    assert "Confirm &amp; Link" not in page.text


def test_the_queue_page_offers_previews_and_the_address_view(console, pg, unique):
    _event(pg, unique, "1", venue=PASION)
    _event(pg, unique, "2", venue=f"주소없음 {unique}")
    page = console.get("/admin/venues/unresolved?show=address")
    assert page.status_code == 200
    assert "Tango Pasion" in page.text
    assert f"주소없음 {unique}" not in page.text
    assert "/link/preview" in page.text and "/create/preview" in page.text
    assert "예정 노출 Event" in page.text
