"""v0.96.51: two programmes of one room are not offered as one event.

A venue on one date often runs several things - a 14:00 practica, a 20:00
milonga, a 23:30 late night - each its own listing with its own name. The
rules pair them (same place, two clocks) as a question, and until v0.96.51
the Duplicates page offered "Same event" on every one: 145 of Production's 152
answerable pairs on 2026-10-23 were exactly this.

Only one finding now refuses the merge (`EXPLICIT_DISTINCT_PROGRAMMES`): the
*same* listing source (a WEB aggregator or directory) publishing the two as
its own separate single-event listings, under unrelated names, at two stated
starts. Everything short of that stays a person's question - marked
"needs more evidence" when only the place and the date are shared - and a
real duplicate across sources is answered exactly as before.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from runtime import decision_contract as DC
from runtime import duplicates
from tests.test_v09639_evidence_and_listing import (  # noqa: F401 - fixtures
    _event, _id, run_normalization, settings, store, venue)
from tests.test_v09640_duplicate_revert import (  # noqa: F401 - fixtures
    _day, _pair_of, _verdict_id, console)

TODAY = date(2026, 10, 23)


def _ev(event_id, **kw):
    row = {"event_id": event_id, "event_date": TODAY, "end_date": None, "period_end": None,
           "event_name": f"Night {event_id}", "start_time": "20:00", "venue_id": 186,
           "venue_text": "Ocho", "region_id": 1, "identity_key": f"k{event_id}",
           "series_key": None, "event_type": "MILONGA", "canonical_event_id": None,
           "duplicate_decided_by": None, "listing_state": "LISTED", "review_state": "PENDING",
           "provenance": "LIVE", "source_item_id": event_id * 10,
           "primary_source_item_id": None, "primary_source_decided_by": None,
           "folded_count": 0, "source_id": 5, "source_platform": "WEB",
           "source_role": "DIRECTORY", "item_event_count": 1}
    row.update(kw)
    return row


def _pair(low=10, high=20, state="OPEN", rule=duplicates.RULE_VENUE_TIME_DIFFERS):
    return {"pair_id": 1, "event_id": low, "other_event_id": high, "rule": rule,
            "state": state, "matched": ["event_date", "venue"],
            "resolved_by": None if state == "OPEN" else "operator", "resolved_at": None,
            "created_at": None}


def _assess(left, right, pair=None):
    pair = pair or _pair(left["event_id"], right["event_id"])
    rows = {left["event_id"]: left, right["event_id"]: right}
    index = {(pair["event_id"], pair["other_event_id"]): pair}
    return duplicates.assess_pair(pair, rows, index, TODAY)


def _merge_reasons(item):
    return {r for a in item["answers"] if a["decision"] == duplicates.DUPLICATE
            for r in a["reasons"]}


# --- the identity model, in memory --------------------------------------------------

def test_one_directory_two_listings_two_names_two_starts_refuses_the_merge():
    """Production #510732: Miltang lists 로까밀롱가 20:00 and 토이프밀롱가 14:00 at Ocho."""
    left = _ev(10, event_name="로까밀롱가", start_time="20:00")
    right = _ev(20, event_name="토이프밀롱가", start_time="14:00")
    assert duplicates.programme_identity(left, right)["identity"] == \
        duplicates.IDENTITY_DIFFERENT_PROGRAMME
    item = _assess(left, right)
    assert item["status"] == duplicates.QUEUE_ACTIONABLE
    assert item["available"] == ["KEEP_SEPARATE"], "Different events stays a person's answer"
    assert _merge_reasons(item) == {duplicates.REASON_EXPLICIT_DISTINCT_PROGRAMMES}
    assert item["merge_readiness"] == duplicates.EVIDENCE_CONTRADICTS
    assert item["programme_identity"] == duplicates.IDENTITY_DIFFERENT_PROGRAMME
    assert any("items 100 / 200" in e for e in item["programme_evidence"])


def test_a_lesson_and_a_milonga_read_out_of_one_post_are_a_persons_question():
    """One post, two programmes: whether they are one event's parts or two
    events is the post's to say, not a rule's - nothing is refused."""
    left = _ev(10, event_name="초급 강습", start_time="19:00", source_item_id=77,
               item_event_count=2)
    right = _ev(20, event_name="Milonga Bulgeum", start_time="20:00", source_item_id=77,
                item_event_count=2)
    item = _assess(left, right)
    assert item["programme_identity"] == duplicates.IDENTITY_INSUFFICIENT
    assert item["merge_readiness"] == duplicates.EVIDENCE_INSUFFICIENT
    assert item["available"] == ["MERGE:10", "MERGE:20", "KEEP_SEPARATE"]


def test_one_milonga_posted_by_two_independent_sources_stays_mergeable():
    left = _ev(10, event_name="Milonga ON", start_time="19:00", source_id=2,
               source_role="AGGREGATOR")
    right = _ev(20, event_name="Milonga ON", start_time="20:00", source_id=5)
    item = _assess(left, right)
    assert item["programme_identity"] == duplicates.IDENTITY_POSSIBLY_SAME
    assert item["merge_readiness"] == duplicates.EVIDENCE_SUPPORTS
    assert item["available"] == ["MERGE:10", "MERGE:20", "KEEP_SEPARATE"]


def test_two_sources_unrelated_names_need_more_evidence_but_are_not_refused():
    """Production #510733: Tango Calendar's Milonga Hiro 19:00 and Miltang's
    Alonga 14:00 at Andante - nothing but the room and the day in common, and
    no single source saying they are two."""
    left = _ev(10, event_name="Milonga Hiro", start_time="19:00", source_id=3)
    right = _ev(20, event_name="Alonga", start_time="14:00", source_id=5)
    item = _assess(left, right)
    assert item["programme_identity"] == duplicates.IDENTITY_INSUFFICIENT
    assert item["merge_readiness"] == duplicates.EVIDENCE_INSUFFICIENT
    assert "MERGE:10" in item["available"]


def test_one_directory_relisting_one_night_stays_mergeable():
    """Production #557905: the same 평일 낮쁘락 listed twice by Miltang."""
    left = _ev(10, event_name="평일 낮쁘락", start_time="15:00")
    right = _ev(20, event_name="평일 낮쁘락", start_time="16:00")
    item = _assess(left, right)
    assert item["programme_identity"] == duplicates.IDENTITY_POSSIBLY_SAME
    assert "MERGE:10" in item["available"]


def test_a_community_board_is_not_a_listing_source():
    """Two members of one cafe may post one party under two names."""
    left = _ev(10, event_name="Bliss 3rd Anniversary", start_time="19:00",
               source_platform="DAUM_CAFE", source_role="COMMUNITY")
    right = _ev(20, event_name="Fall party", start_time="21:00",
                source_platform="DAUM_CAFE", source_role="COMMUNITY")
    assert duplicates.programme_identity(left, right)["identity"] == \
        duplicates.IDENTITY_INSUFFICIENT
    assert "MERGE:10" in _assess(left, right)["available"]


@pytest.mark.parametrize("left_name,right_name", [
    ("Salsa Bachata🍂 FALL IN TOGETHER", "Fall In Together"),     # Production #639521
    ("Andante | Milonga Julie", "Andante | Julie milonga"),
    ("그리셀밀롱가", "그리셀 밀롱가"),
    ("강턴 주간일정 10/13", "강턴 주간일정"),
])
def test_names_that_may_be_one_nights_are_never_explicitly_distinct(left_name, right_name):
    left = _ev(10, event_name=left_name, start_time="19:00")
    right = _ev(20, event_name=right_name, start_time="20:00")
    assert duplicates.programme_identity(left, right)["identity"] == \
        duplicates.IDENTITY_POSSIBLY_SAME


@pytest.mark.parametrize("left_name,right_name", [
    ("토이프밀롱가", "로까밀롱가"),
    ("피스타 낮 쁘락티카", "자율 쁘락티카"),            # only the kind of night shared
    ("Andante | Alonga", "La melodia | La Melodia"),     # TangoNOW "<venue> | <night>"
    ("The PISTA", "심야 밀롱가"),
])
def test_names_sharing_only_the_kind_of_night_are_unrelated(left_name, right_name):
    left = _ev(10, event_name=left_name, start_time="14:00")
    right = _ev(20, event_name=right_name, start_time="19:00")
    assert duplicates.programme_identity(left, right)["identity"] == \
        duplicates.IDENTITY_DIFFERENT_PROGRAMME


def test_a_missing_start_is_not_a_stated_difference():
    left = _ev(10, event_name="토이프밀롱가", start_time=None)
    right = _ev(20, event_name="로까밀롱가", start_time="20:00")
    found = duplicates.programme_identity(left, right)
    assert found["identity"] == duplicates.IDENTITY_INSUFFICIENT
    assert "not stated" in found["evidence"][0]


def test_twelve_hours_apart_may_be_one_clock_read_twice():
    """Production #197455: 09:00 beside 21:00 - "9시" read with and without 오후."""
    left = _ev(10, event_name="RUEDA CHUSEOK PARTY", start_time="09:00")
    right = _ev(20, event_name="명절 메인 심야 파티!", start_time="21:00")
    assert duplicates.programme_identity(left, right)["identity"] != \
        duplicates.IDENTITY_DIFFERENT_PROGRAMME


def test_a_festival_and_its_night_stay_refused_as_before():
    left = _ev(10, event_name="SEOUL TANGO WEEK", event_type="FESTIVAL", start_time=None)
    right = _ev(20, event_name="Welcome milonga", start_time="20:00")
    item = _assess(left, right)
    assert item["programme_identity"] == duplicates.IDENTITY_FESTIVAL_PROGRAMME
    assert duplicates.REASON_FESTIVAL_PROGRAMME in _merge_reasons(item)


def test_two_regions_stay_refused_as_before():
    left = _ev(10, event_name="Milonga ON", region_id=1, source_id=2)
    right = _ev(20, event_name="Milonga ON", region_id=2, start_time="21:00")
    item = _assess(left, right)
    assert duplicates.REASON_REGION_CONFLICT in _merge_reasons(item)
    assert item["merge_readiness"] == duplicates.EVIDENCE_CONTRADICTS


def test_a_resolved_pair_offers_nothing_without_a_revert():
    left = _ev(10, event_name="토이프밀롱가", start_time="14:00")
    right = _ev(20, event_name="토이프밀롱가", start_time="15:00")
    item = _assess(left, right, _pair(state=duplicates.DISTINCT))
    assert item["status"] == duplicates.QUEUE_PERSON and item["available"] == []


def test_the_same_clock_at_an_unresolved_place_is_possibly_one_night():
    """Production #805256: HOLA TANGO 18:30 posted twice, place not resolved."""
    left = _ev(10, event_name="HOLA TANGO | Hola milonga", start_time="18:30",
               venue_id=None, venue_text="The Grounds")
    right = _ev(20, event_name="HOLA TANGO | Hola milonga", start_time="18:30",
                venue_id=None, venue_text="The Grounds")
    item = _assess(left, right, _pair(rule=duplicates.RULE_UNRESOLVED_VENUE_TIME))
    assert item["programme_identity"] == duplicates.IDENTITY_POSSIBLY_SAME
    assert item["merge_readiness"] == duplicates.EVIDENCE_SUPPORTS
    assert "MERGE:10" in item["available"]


# --- the real route: preview, confirm, revert ---------------------------------------

def _set_role(pg, store_source_key_like, role):
    with pg.cursor() as cur:
        cur.execute("UPDATE sources SET source_role = %s WHERE source_key LIKE %s",
                    (role, store_source_key_like))


@pytest.fixture
def two_programmes(pg, store, run_normalization, unique, venue):
    """One directory, one room, one date: an afternoon practica and a night milonga."""
    _set_role(pg, f"SRC-V09639-{unique}", "DIRECTORY")
    day = _day(5)
    ids = [store.add(_id(unique, 60), name=f"토이프밀롱가 {unique[:3]}a", day=day,
                     start="14:00", end="18:00", venue=venue["name"]),
           store.add(_id(unique, 61), name="로까밀롱가", day=day, start="20:00",
                     end="02:00", venue=venue["name"])]
    run_normalization()
    duplicates.scan(pg, on=day)
    a, b = _event(pg, ids[0]), _event(pg, ids[1])
    assert a["source_item_id"] and b["source_item_id"] and \
        a["source_item_id"] != b["source_item_id"]
    pair = _pair_of(pg, a["event_id"], b["event_id"])
    assert pair["rule"] == duplicates.RULE_VENUE_TIME_DIFFERS and pair["state"] == "OPEN"
    return {"day": day, "a": a, "b": b, "pair": pair}


def _item(pg, pair_id):
    return next(x for x in duplicates.queue(pg) if x["pair_id"] == pair_id)


def test_queue_preview_and_confirm_refuse_the_same_merge(pg, two_programmes):
    case = two_programmes
    pair_id, keep = case["pair"]["pair_id"], case["a"]["event_id"]
    item = _item(pg, pair_id)
    assert item["status"] == duplicates.QUEUE_ACTIONABLE
    assert item["available"] == ["KEEP_SEPARATE"]
    preview = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                         canonical_event_id=keep, reviewer="tester")
    assert preview["token"] is None
    assert preview["reasons"] == [duplicates.REASON_EXPLICIT_DISTINCT_PROGRAMMES]
    # A token signed for Different events cannot be spent on Same event.
    keep_token = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                            reviewer="tester")["token"]
    assert keep_token
    for token in (None, "forged.token", keep_token):
        with pytest.raises(DC.DecisionRefused):
            duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=keep, token=token,
                                       reviewer="tester")
    assert _verdict_id(pg, case["b"]["event_id"]) is None
    assert _pair_of(pg, case["a"]["event_id"], case["b"]["event_id"])["state"] == "OPEN"
    gates = duplicates.queue_integrity(pg, duplicates.queue(pg))
    assert all(v == 0 for v in gates.values()), gates


def test_the_console_offers_only_different_events(console, pg, two_programmes):
    case = two_programmes
    pair_id = case["pair"]["pair_id"]
    page = console.get(f"/admin/duplicates/{pair_id}")
    assert page.status_code == 200
    assert duplicates.IDENTITY_DIFFERENT_PROGRAMME in page.text
    assert f'value="keep_{case["a"]["event_id"]}"' not in page.text
    assert 'value="distinct"' in page.text
    refused = console.post(f"/admin/duplicates/{pair_id}/preview",
                           data={"action": f"keep_{case['a']['event_id']}"})
    assert duplicates.REASON_EXPLICIT_DISTINCT_PROGRAMMES in refused.text
    assert not re.search(r'name="token" value="[^"]+"', refused.text)
    queue = console.get("/api/admin/duplicates/queue").json()
    found = next(p for p in queue["pairs"] if p["pair_id"] == pair_id)
    assert found["programme_identity"] == duplicates.IDENTITY_DIFFERENT_PROGRAMME
    assert found["available"] == ["KEEP_SEPARATE"]


def test_a_real_duplicate_across_sources_merges_reverts_and_needs_a_new_preview(
        pg, store, run_normalization, unique, venue):
    """The same milonga from two sources at two stated clocks: the merge is
    the person's to give, exactly as before v0.96.51."""
    from runtime import sources

    _set_role(pg, f"SRC-V09639-{unique}", "DIRECTORY")
    day = _day(6)
    ids = [store.add(_id(unique, 70), name="Milonga Julie", day=day, start="19:00",
                     venue=venue["name"]),
           store.add(_id(unique, 71), name="Andante | Milonga Julie", day=day, start="20:00",
                     venue=venue["name"])]
    run_normalization()
    duplicates.scan(pg, on=day)
    a, b = _event(pg, ids[0]), _event(pg, ids[1])
    other = sources.create_source(pg, source_key=f"SRC-V09651-{unique}",
                                  name=f"v0.96.51 other {unique}", platform="WEB",
                                  source_role="AGGREGATOR", url="https://example.test/o",
                                  enabled=False)
    with pg.cursor() as cur:
        cur.execute("UPDATE source_items SET source_id = %s WHERE source_item_id = %s",
                    (other["source_id"], b["source_item_id"]))
    pair = _pair_of(pg, a["event_id"], b["event_id"])
    item = _item(pg, pair["pair_id"])
    assert item["programme_identity"] == duplicates.IDENTITY_POSSIBLY_SAME
    assert item["merge_readiness"] == duplicates.EVIDENCE_SUPPORTS
    preview = duplicates.preview_resolve(pg, pair["pair_id"], decision=duplicates.DUPLICATE,
                                         canonical_event_id=a["event_id"], reviewer="tester")
    assert preview["reasons"] == [] and preview["token"]
    done = duplicates.confirm_resolve(pg, pair["pair_id"], decision=duplicates.DUPLICATE,
                                      canonical_event_id=a["event_id"],
                                      token=preview["token"], reviewer="tester")
    assert done["state"] == duplicates.MERGED
    verdict = _verdict_id(pg, b["event_id"])
    assert verdict is not None
    # Answered once: the same token, or a second answer, records nothing more.
    with pytest.raises(DC.DecisionRefused):
        duplicates.confirm_resolve(pg, pair["pair_id"], decision=duplicates.DUPLICATE,
                                   canonical_event_id=a["event_id"],
                                   token=preview["token"], reviewer="tester")
    revert = duplicates.preview_revert(pg, decision_id=verdict, reviewer="tester")
    assert revert["blockers"] == []
    duplicates.revert_decision(pg, decision_id=verdict, token=revert["token"],
                               reviewer="tester", reason="test")
    assert _pair_of(pg, a["event_id"], b["event_id"])["state"] == "OPEN"
    with pytest.raises(DC.DecisionRefused) as stale:
        duplicates.confirm_resolve(pg, pair["pair_id"], decision=duplicates.DUPLICATE,
                                   canonical_event_id=a["event_id"],
                                   token=preview["token"], reviewer="tester")
    assert stale.value.code == DC.STALE_PREVIEW
    fresh = duplicates.preview_resolve(pg, pair["pair_id"], decision=duplicates.DUPLICATE,
                                       canonical_event_id=a["event_id"], reviewer="tester")
    assert fresh["token"] and fresh["token"] != preview["token"]
