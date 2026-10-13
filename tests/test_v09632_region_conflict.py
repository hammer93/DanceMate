"""v0.96.32: an alias is a name, and a name can belong to two places.

`Tango O Nada` names a basement in 서울 마포구 and also one in 대전 유성구.
Only the Seoul one is in the Venue Master, with `땅고 오나다`, `오나다` and
`탱고 오나다` among its aliases - and in October 2026 those answered for the
Daejeon one too. Two Daejeon milongas (Bobby Millonga 10-16, 찐밀 10-17) were
listed in Seoul, and because they then shared a date, a venue id and an hour
with the real Seoul milongas of those nights (Milonga Bulgeum, 토나다), the
duplicate rules folded the Seoul ones away as copies of the Daejeon ones. Four
events wrong, two of them invisible.

The reading that let it happen is fixed in `engine/src` (the city word at the
head of the post's own `장소` field is no longer thrown away). These are the
two runtime guards behind it, so the same shape of mistake cannot arrive
through some other alias:

    a name match whose venue sits in a metropolis the post's own words
    exclude is not that venue           `normalization.resolve_venue`

    two events that share a venue id and still name metropolitan cities that
    exclude each other are not merged automatically   `duplicates.classify`

Both are deliberately narrow. Only metropolitan cities are compared, because
a metropolis contains no other first-level unit and is contained by none, so
two different ones cannot both be right - while 창원 lies inside 경남 and 포항
inside 경북, and this project registers those cities as regions of their own.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from runtime import duplicates, master_data, normalization, venue_identity

DAY = date(2026, 10, 16)
SEOUL_PLACE = "O Nada (오나다) (서울 마포구 동교동 200-29 B1)"
DAEJEON_PLACE = "대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)"


# --- T1: which cities a text's own words name -------------------------------

@pytest.mark.parametrize("text,expected", [
    (DAEJEON_PLACE, {"KR-DAEJEON"}),
    (SEOUL_PLACE, {"KR-SEOUL"}),
    ("대전광역시 유성구 문화원로6번길 1 지하1층 리트모", {"KR-DAEJEON"}),
    ("서울특별시 강남구 삼성로 634", {"KR-SEOUL"}),
    ("부산 일빠(부산 부산진구 신천대로62번길 38 4층)", {"KR-BUSAN"}),
    # No metropolis named at all.
    ("Tango O Nada", set()),
    ("진주 탱고피플 (진주시 평거로7 3층)", set()),
    ("Tango club Mi Noche (경남 창원시 마산합포구 가포로25 지하1층)", set()),
    ("StudioAura (청주시 서원구 사창동 474-3, 3F)", set()),
    # A word that merely contains a city name is not that city.
    ("동광주역 앞", set()),
    ("서울대입구 2번 출구", set()),
])
def test_stated_metros_reads_only_what_the_words_say(text, expected):
    assert venue_identity.stated_metros(text) == expected


@pytest.mark.parametrize("left,right,contradict", [
    (DAEJEON_PLACE, SEOUL_PLACE, True),
    (SEOUL_PLACE, DAEJEON_PLACE, True),
    # One of them says nothing: no contradiction, nothing to go on.
    ("Tango O Nada", SEOUL_PLACE, False),
    (DAEJEON_PLACE, "Tango O Nada", False),
    # The same city, written differently.
    ("서울 마포구 동교로 193", "서울특별시 마포구 동교동 200-29", False),
    # A guest DJ's home city beside the venue's own: they overlap, so one of
    # the two named cities is this event's.
    ("서울 마포구 동교동 200-29 (부산 게스트 DJ)", SEOUL_PLACE, False),
    # A province against a city region is a hierarchy question, not a
    # contradiction - and is never asked here.
    ("경남 창원시 마산합포구 가포로25", "진주 탱고피플 (진주시 평거로7 3층)", False),
])
def test_texts_contradict_only_on_mutually_exclusive_cities(left, right,
                                                            contradict):
    assert venue_identity.texts_contradict(left, right) is contradict


# --- T2: the duplicate rules ------------------------------------------------

def _event(event_id, **overrides):
    base = {
        "event_id": event_id,
        "event_date": DAY,
        "start_time": time(21, 0),
        "end_time": time(2, 0),
        "venue_id": 187,
        "venue_text": SEOUL_PLACE,
        "venue_status": "RESOLVED",
        "event_name": "Milonga Bulgeum",
        "fee": None,
        "dj": None,
        "engine_status": "POSSIBLE",
        "review_state": "PENDING",
        "series_key": None,
        "duplicate_decided_by": None,
    }
    base.update(overrides)
    return base


def test_the_two_october_16_milongas_are_not_merged():
    """T2. Production's own pair, as it stood before this release."""
    seoul = _event(1614360)
    daejeon = _event(1614352, event_name="Bobby Millonga",
                     venue_text=DAEJEON_PLACE)
    finding = duplicates.classify(seoul, daejeon)
    assert finding is not None
    assert finding["auto"] is False
    assert finding["rule"] == duplicates.RULE_REGION_CONFLICT
    assert finding["differs"] == ["stated_region"]


def test_the_october_17_pair_is_not_merged_either():
    seoul = _event(1614343, event_date=date(2026, 10, 17),
                   event_name="토나다", end_time=time(3, 0))
    daejeon = _event(1614335, event_date=date(2026, 10, 17),
                     event_name="찐밀", venue_text=DAEJEON_PLACE)
    finding = duplicates.classify(seoul, daejeon)
    assert finding["auto"] is False
    assert finding["rule"] == duplicates.RULE_REGION_CONFLICT


def test_a_real_duplicate_at_one_venue_is_still_merged():
    """The rule this release must not weaken: one night, two posts."""
    miltang = _event(1614402, event_name="무초밀롱가", venue_id=186,
                     venue_text="Ocho (오초) (서울 마포구 월드컵북로2길 57 지하1층)")
    calendar = _event(1614326, event_name="무초밀롱가", venue_id=186,
                      venue_text="탱고 클럽 오초")
    finding = duplicates.classify(miltang, calendar)
    assert finding["auto"] is True
    assert finding["rule"] == duplicates.RULE_SAME_DATE_VENUE_TIME


def test_two_spellings_of_one_city_still_merge():
    left = _event(1, venue_text="서울 마포구 동교로 193 지하1층")
    right = _event(2, venue_text="서울특별시 마포구 동교동 200-29 B1")
    assert duplicates.classify(left, right)["auto"] is True


def test_a_silent_venue_text_does_not_block_a_merge():
    """`Tango O Nada` names no city; that is not evidence of a conflict."""
    left = _event(1, venue_text="Tango O Nada")
    right = _event(2, venue_text=SEOUL_PLACE)
    assert duplicates.classify(left, right)["auto"] is True


def test_the_unresolved_venue_rule_is_untouched():
    """v0.96.23's rule still fires before anything about regions."""
    left = _event(1603334, venue_id=None, venue_status="UNRESOLVED",
                  venue_text="스스 me1")
    right = _event(1603338, venue_id=None, venue_status="UNRESOLVED",
                   venue_text="스스 me1")
    assert duplicates.classify(left, right)["rule"] == (
        duplicates.RULE_UNRESOLVED_VENUE_TIME)


def test_different_dates_are_still_never_compared():
    left = _event(1)
    right = _event(2, event_date=date(2026, 10, 23), venue_text=DAEJEON_PLACE)
    assert duplicates.classify(left, right) is None


def test_a_conflict_at_different_hours_still_asks_about_the_hour():
    left = _event(1)
    right = _event(2, start_time=time(20, 0), venue_text=DAEJEON_PLACE)
    assert duplicates.classify(left, right)["rule"] == (
        duplicates.RULE_VENUE_TIME_DIFFERS)


# --- T3: venue resolution, against the real Venue Master --------------------

def test_the_daejeon_reading_does_not_resolve_to_the_seoul_venue(pg):
    """T3. The whole point: `대전 땅고 오나다` is not Seoul's `Tango O Nada`."""
    resolution = normalization.resolve_venue(
        pg, DAEJEON_PLACE,
        ["대전 땅고 오나다", "대전시 유성구 대학로76번안길 23 지하"])
    assert resolution["venue_status"] == normalization.VENUE_UNRESOLVED
    assert resolution["venue_id"] is None


def test_the_seoul_reading_still_resolves(pg):
    resolution = normalization.resolve_venue(
        pg, SEOUL_PLACE, [SEOUL_PLACE, "O Nada", "오나다",
                          "서울 마포구 동교동 200-29 B1"])
    assert resolution["venue_status"] == normalization.VENUE_RESOLVED
    venue = master_data.get_venue(pg, resolution["venue_id"])
    assert "nada" in venue["name"].lower()


def test_a_seoul_alias_is_refused_for_a_daejeon_address(pg, unique):
    """A hand-made collision, so the guard is tested and not just the corpus.

    The alias is real and correct for its own venue; what is refused is
    answering with it for a reading whose own words say another city.
    """
    seoul = master_data.create_venue(
        pg, name=f"Collision Hall {unique}",
        region_id=_region(pg, "KR-SEOUL"), address="서울 마포구 어딘가 1")
    master_data.add_venue_alias(pg, venue_id=seoul["venue_id"],
                               alias=f"충돌홀{unique}")
    same_city = normalization.resolve_venue(
        pg, f"충돌홀{unique} (서울 마포구 어딘가 1)", [f"충돌홀{unique}"])
    assert same_city["venue_id"] == seoul["venue_id"]
    other_city = normalization.resolve_venue(
        pg, f"충돌홀{unique} (대전 유성구 어딘가 1)", [f"충돌홀{unique}"])
    assert other_city["venue_status"] == normalization.VENUE_UNRESOLVED


def test_a_venue_outside_the_metropolises_is_never_refused(pg, unique):
    """창원 is inside 경남; comparing those would reject a correct venue."""
    changwon = master_data.create_venue(
        pg, name=f"Mi Noche {unique}", region_id=_region(pg, "KR-CHANGWON"),
        address="경남 창원시 마산합포구 가포로25 지하1층")
    master_data.add_venue_alias(pg, venue_id=changwon["venue_id"],
                               alias=f"미노체{unique}")
    resolution = normalization.resolve_venue(
        pg, f"미노체{unique} (경남 창원시 마산합포구 가포로25 지하1층)",
        [f"미노체{unique}"])
    assert resolution["venue_id"] == changwon["venue_id"]


def _region(con, code: str) -> int:
    for region in master_data.list_regions(con):
        if region["code"] == code:
            return region["region_id"]
    pytest.skip(f"{code} is not seeded; run the migrations first")
