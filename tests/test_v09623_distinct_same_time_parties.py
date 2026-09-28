"""v0.96.23: two different parties at the same hour are two events.

Production, 2026-10-03, 21:00, both read from DanceInfo::

    event 1603334  모두의 라틴 바차타 워크숍 및 살사 파티   장소 광주 J 라틴
    event 1603338  검단 라틴솔 동호회 10월 미니파티        장소 단춤 (인천 검단)

300km apart, different DJs (버퍼링 / 바밤바), different end times, different
fees, two separate DanceInfo listings (/lessons/4641 and /lessons/4202) - and
one folded under the other, so half of that Saturday's choice was shown to
nobody. The same thing happened on 2026-09-25 to a Gangnam party ("명절 메인
심야 파티!", 클럽 라틴) and a Daegu one ("BABARU 소셜 OPEN!", 바바루).

Both pairs agreed on the one field the merge rule needs and cannot check: a
venue string. Neither event's venue was ever resolved. DanceInfo attached one
poster's Instagram handle to eighteen listings and the OCR read it as
``@ 스스 me1``, so eighteen events in eight cities all claimed the same
unresolved venue.

The rule that broke is narrow and so is the fix: an automatic merge needs a
*resolved* place. Identical unresolved words are still enough to ask a person
about (they usually are the same milonga), never enough to hide an event. A
resolved venue is untouched - every one of the 64 real duplicate groups in
Production at the time of this release resolved its venue on every member,
and none of them changes.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from runtime import duplicates, master_data, normalization

DAY = date(2026, 10, 3)


def _event(event_id, **overrides):
    base = {
        "event_id": event_id,
        "event_date": DAY,
        "start_time": time(21, 0),
        "end_time": time(23, 30),
        "venue_id": None,
        "venue_text": "스스 me1",
        "venue_status": "UNRESOLVED",
        "event_name": "파티",
        "fee": None,
        "dj": None,
        "engine_status": "POSSIBLE",
        "review_state": "PENDING",
        "series_key": None,
        "duplicate_decided_by": None,
    }
    base.update(overrides)
    return base


# --- T1: the target pair ----------------------------------------------------

def test_two_parties_sharing_only_an_unresolved_venue_string_are_not_merged():
    """T1. The Gwangju party and the Incheon party, as Production stored them."""
    gwangju = _event(1603334, event_name="모두의 라틴 바차타 워크숍 및 살사 파티",
                     end_time=time(1, 0), dj="버퍼링",
                     series_key="text:스스me1|5|모두의라틴바차타워크숍및살사파티")
    incheon = _event(1603338, event_name="검단 라틴솔 동호회 10월 미니파티",
                     fee=10000, dj="바밤바",
                     series_key="text:스스me1|5|검단라틴솔동호회10월미니파티")
    finding = duplicates.classify(gwangju, incheon)
    assert finding is not None
    assert finding["auto"] is False
    assert finding["rule"] == duplicates.RULE_UNRESOLVED_VENUE_TIME


def test_the_gangnam_and_daegu_parties_are_not_merged_either():
    """T1 (second Production case, 2026-09-25 21:00)."""
    gangnam = _event(1600293, event_date=date(2026, 9, 25), end_time=None,
                     event_name="명절 메인 심야 파티!", dj="어텐션")
    daegu = _event(1607998, event_date=date(2026, 9, 25), end_time=None,
                   event_name="BABARU 소셜 OPEN! 09/25", fee=40000, dj="길거리")
    finding = duplicates.classify(gangnam, daegu)
    assert finding is not None and finding["auto"] is False


# --- T2-T6: what still merges, and what still does not ----------------------

def test_a_resolved_venue_at_the_same_hour_still_merges():
    """T2. The only automatic merge there has ever been, unchanged: same date,
    same *resolved* venue, same start time - the shape of every real
    cross-source duplicate in Production."""
    left = _event(1, venue_id=186, venue_text="Ocho (오초)", venue_status="RESOLVED")
    right = _event(2, venue_id=186, venue_text="탱고 클럽 오초", venue_status="RESOLVED",
                   dj="나초", fee=13000)
    finding = duplicates.classify(left, right)
    assert finding["rule"] == duplicates.RULE_SAME_DATE_VENUE_TIME
    assert finding["auto"] is True


def test_two_spellings_of_one_resolved_venue_still_merge():
    """T3. Miltang writes "Ocho (오초) (서울 마포구 ...)", TangoNOW writes "OCHO",
    Tango Calendar writes "탱고 클럽 오초". One venue_id, one event."""
    for text in ("Ocho (오초) (서울 마포구 월드컵북로2길 57 지하1층)", "OCHO", "탱고 클럽 오초"):
        finding = duplicates.classify(
            _event(1, venue_id=186, venue_text="Ocho (오초)", venue_status="RESOLVED"),
            _event(2, venue_id=186, venue_text=text, venue_status="RESOLVED"),
        )
        assert finding["auto"] is True, text


def test_one_resolved_venue_and_one_unknown_is_still_not_a_merge():
    """T4. The pre-existing contract, unchanged: a place known on one side
    only was never the same place, and still is not."""
    finding = duplicates.classify(
        _event(1, venue_id=186, venue_text="OCHO", venue_status="RESOLVED"),
        _event(2),
    )
    assert finding is None or finding["auto"] is False


def test_different_resolved_venues_at_the_same_hour_are_unrelated():
    """T6. Two studios, one night, one clock: not a pair at all."""
    finding = duplicates.classify(
        _event(1, venue_id=186, venue_text="OCHO", venue_status="RESOLVED"),
        _event(2, venue_id=187, venue_text="O Nada", venue_status="RESOLVED"),
    )
    assert finding is None


# --- T7-T9: discriminators this release deliberately does not use -----------

def test_differing_titles_alone_never_split_a_resolved_duplicate():
    """T7. 24 of the 66 Production fold groups carry two different titles for
    one night - "Milonga La Vida" and "[부산탱고] 2026년 9월 5일 토요일 밀롱가
    La Vida No...", "orange" and "9/22(화) 오렌지밀 y 허그". Splitting on title
    inequality would have broken 25 real duplicates to fix 2 false ones."""
    finding = duplicates.classify(
        _event(1, venue_id=182, venue_status="RESOLVED", event_name="라비오스"),
        _event(2, venue_id=182, venue_status="RESOLVED",
               event_name="이번주 금요일(9/11) 라비오스 밀롱가"),
    )
    assert finding["auto"] is True


def test_a_differing_dj_alone_never_splits_a_resolved_duplicate():
    """T7/T5. DJ extraction reads particles ("는") and disagrees across sources
    for one real milonga (Milonga Julie: 배영성 / 계명성). It is not evidence of
    two events."""
    finding = duplicates.classify(
        _event(1, venue_id=181, venue_status="RESOLVED", dj="배영성"),
        _event(2, venue_id=181, venue_status="RESOLVED", dj="계명성"),
    )
    assert finding["auto"] is True


def test_two_listings_from_one_source_still_merge_on_a_resolved_venue():
    """T8/T9. A source listing one night twice is ordinary - Miltang has
    "milonga cabeceo" under two ids, the Daum board posted one 로라밀롱가 twice.
    Two different source-native ids are not evidence of two events, so nothing
    here looks at where a row came from."""
    finding = duplicates.classify(
        _event(1, venue_id=181, venue_status="RESOLVED", event_name="milonga cabeceo"),
        _event(2, venue_id=181, venue_status="RESOLVED", event_name="cabeceo"),
    )
    assert finding["auto"] is True


def test_a_differing_end_time_alone_never_splits_a_resolved_duplicate():
    """T7. 아수까 일요 밀롱가 ends 22:30 on Miltang and 22:20 on TangoNOW; 서울밀롱가
    ends 23:00 and 00:30. The start time is what the rule has always used."""
    finding = duplicates.classify(
        _event(1, venue_id=4215, venue_status="RESOLVED", end_time=time(22, 30)),
        _event(2, venue_id=4215, venue_status="RESOLVED", end_time=time(22, 20)),
    )
    assert finding["auto"] is True


# --- the fold graph follows the current rules -------------------------------

@pytest.fixture
def studio(pg, unique, seoul_id):
    return master_data.create_venue(pg, name=f"스튜디오 {unique}", region_id=seoul_id)


def _candidate(unique: str, suffix: str, **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://danceinfo.net/lessons/{unique}-{suffix}",
        "event_name": f"파티 {unique}-{suffix}",
        "event_type": "SOCIAL_WITH_CLASS",
        "event_date": "2026-10-03",
        "start_time": "21:00",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"스튜디오 {unique}",
        "fee": 10000,
        "candidate_status": "POSSIBLE",
    }
    base.update(overrides)
    return base


def test_both_parties_stay_visible_through_the_whole_pipeline(pg, unique):
    """End to end on an unresolved venue: two candidates, two listed events,
    and one open question for a person rather than a silent merge."""
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2"))
    assert first["venue_status"] == "UNRESOLVED"

    duplicates.scan(pg, on=DAY)

    for stored in (first, second):
        event = normalization.get(pg, stored["event_id"])
        assert event["canonical_event_id"] is None
        assert event["listing_state"] == "LISTED"

    pairs = [p for p in duplicates.open_pairs(pg)
             if p["venue_text"] == f"스튜디오 {unique}"]
    assert len(pairs) == 1
    assert pairs[0]["rule"] == duplicates.RULE_UNRESOLVED_VENUE_TIME


def test_a_merge_the_rules_would_no_longer_make_is_released(pg, unique, studio):
    """The fix has to reach rows already folded under the old rule, through
    the product's own scan - not a hand-written UPDATE. So: merge two events
    on a resolved venue, take the resolution away the way the Venue Master
    would, and the next scan releases what no longer follows from anything."""
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2"))
    duplicates.scan(pg, on=DAY)

    folded = [normalization.get(pg, e["event_id"]) for e in (first, second)]
    hidden = next(e for e in folded if e["canonical_event_id"] is not None)
    canonical_id = hidden["canonical_event_id"]

    with pg.cursor() as cur:
        cur.execute(
            "UPDATE events SET venue_id = NULL, venue_status = 'UNRESOLVED' "
            "WHERE event_id = ANY(%s)",
            ([first["event_id"], second["event_id"]],),
        )

    result = duplicates.scan(pg, on=DAY)
    assert result["released"] >= 1
    assert normalization.get(pg, hidden["event_id"])["canonical_event_id"] is None
    assert normalization.get(pg, hidden["event_id"])["listing_state"] == "LISTED"
    assert normalization.get(pg, canonical_id)["canonical_event_id"] is None


def test_releasing_never_overturns_a_person(pg, unique, studio):
    """A merge a human made is not automation's to release, whatever the rules
    would say about the pair now."""
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2",
                                                              start_time="22:00"))
    duplicates.scan(pg, on=DAY)
    pair = next(p for p in duplicates.open_pairs(pg)
                if p["venue_text"] == f"스튜디오 {unique}")
    duplicates.resolve_pair(pg, pair["pair_id"], decision=duplicates.DUPLICATE,
                            canonical_event_id=first["event_id"], reviewer="tester")

    duplicates.scan(pg, on=DAY)
    merged = normalization.get(pg, second["event_id"])
    assert merged["canonical_event_id"] == first["event_id"]
    assert merged["duplicate_decided_by"] == duplicates.HUMAN


def test_a_still_valid_merge_survives_every_rescan(pg, unique, studio):
    """The release pass must not churn: a fold the rules still make is
    re-asked on every tick and answered the same way."""
    first = normalization.normalize_candidate(pg, _candidate(unique, "1"))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2"))
    duplicates.scan(pg, on=DAY)
    before = [normalization.get(pg, e["event_id"])["canonical_event_id"]
              for e in (first, second)]

    for _ in range(2):
        duplicates.scan(pg, on=DAY)

    after = [normalization.get(pg, e["event_id"])["canonical_event_id"]
             for e in (first, second)]
    assert after == before

    # Asserted about these two rows rather than the scan's totals: the same
    # database carries other events, and a global counter says nothing about
    # what happened here.
    with pg.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM event_duplicate_decisions "
            "WHERE rule = %s AND event_id = ANY(%s)",
            (duplicates.RULE_STALE_AUTO_MERGE,
             [first["event_id"], second["event_id"]]),
        )
        assert cur.fetchone()[0] == 0
