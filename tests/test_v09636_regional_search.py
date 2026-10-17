"""v0.96.36 Part A - one region, one answer, however it is spelled.

Measured on Production (v0.96.35, 2026-10-17 12:00 KST, upcoming):

    ?region=KR-SEOUL   103        ?region=서울   125      서울 chip 103
    ?region=KR-DAEJEON   8        ?region=대전    11      대전 chip   8

Three readings of the same question, three rules:

  * the code reached only resolved events - `terms_for_label("KR-SEOUL")` is
    empty, so the unresolved-venue branch was skipped for the spelling the
    API documents;
  * the name added unresolved events by `venue_text ILIKE '%서울%'`, a
    substring, not the guess the reader is shown beside the event;
  * the chips asked only the curated city labels (청주, 진주 ...), so an
    unresolved Seoul address counted under ?region=서울 but never on the
    서울 chip.

All 28 events the name found and the code missed had a real administrative
address in their venue text ("(서울 마포구 월드컵북로6길 69 B1)"). The fix makes
one rule: a resolved event matches by its own region_id, an unresolved one
when `guess_region_label()` - now read from whole place-name tokens - is that
region's name. Nothing is written: a region read off an address is evidence
for a search, never a region_id or a venue.

`guess_region_label()` itself was substring containment: "황제주차빌딩" read as
제주 (25 Busan events, every one at 부산진구), "전남광주통합특별시" as 전남, and a
club's name "울산탱고" as 울산.
"""

from __future__ import annotations

from datetime import date

import pytest

from runtime import duplicates, events_api, master_data, normalization, public
from runtime import venue_resolution as vr

from conftest import register_venue


# --- guess_region_label(): administrative tokens only (pure) ---------------

@pytest.mark.parametrize("text,expected", [
    ("서울 마포구", "서울"),
    ("서울특별시 마포구", "서울"),
    ("부산시 부산진구", "부산"),
    ("부산광역시 부산진구", "부산"),
    ("대전시 유성구", "대전"),
    ("대전광역시 유성구", "대전"),
    ("충북 청주시", "청주"),
    ("경남 창원시 마산합포구", "창원"),
    ("경상남도 창원시 마산합포구 창동거리길 24-2", "창원"),
    ("대구 북구 침산로 168", "대구"),
    ("제주특별자치도 서귀포시 이어도로 989", "제주"),
    # A place name directly followed by the district it contains.
    ("Amigo Studio (부산진구 서면로68번길 41)", "부산"),
    ("러블리밀롱가 (실루엣 분당정자동 23-1 지파크프라자 5층)", "경기"),
    ("광주동구 중앙로 162-1", "광주"),
    # Real Production venue strings the old code could not or did not read.
    ("대전 땅고 오나다 (대전시 유성구 대학로76번안길 23 지하)", "대전"),
    ("여의도 서울마리나 (서울 영등포구 여의서로 160)", "서울"),
    ("La Vida Studio (라 비다 스튜디오) (서울시 서초구 방배천로 60 청도빌딩 B1F)", "서울"),
    ("Amigo (아미고) (부산시 부산진구 부전로 34 황제주차빌딩 2층)", "부산"),
    ("땅고 아미고 스튜디오 (서면 황제주차장 2층, 부산진구 부전로 34)", "부산"),
])
def test_an_administrative_address_names_its_region(text, expected):
    assert vr.guess_region_label(text) == expected


@pytest.mark.parametrize("text", [
    "황제주차빌딩",                       # 제주 inside a building's name
    "서면 황제주차장 2층",                 # ... and inside a car park's
    "전남광주통합특별시 서구 염화로 103",   # not 전남, not a district of 광주
    "Ulsan Tango Sociedad (울산탱고)",    # a club's name, not an address
    "청주탱고 우르끼자",                   # same
    "DLC 대전라틴클럽",                    # same
    "서울대입구역 2번 출구",                # a station named after the city
    "남산N서울타워",                       # a landmark's name
    "부산 출신 DJ의 밤 (서울 마포구)",       # two places, neither contains the other
    "광주 경안동 100-1",                   # Gyeonggi-do's 광주시 or the metro? unknown
    "스튜디오 어딘가",
    "",
])
def test_a_place_name_inside_another_word_is_not_a_region(text):
    assert vr.guess_region_label(text) is None


def test_a_brand_with_branches_in_two_cities_is_not_placed_by_its_name():
    """On TangoNOW brand and venue are many-to-many (A.B.Tango plays Andante
    and PISTA); a name alone never places a branch."""
    assert vr.guess_region_label("A.B.Tango 부산점") is None
    assert vr.guess_region_label("A.B.Tango (서울 마포구 잔다리로 48)") == "서울"


def test_every_spelling_the_guess_accepts_is_reachable_by_its_terms():
    """`terms_for_label()` narrows the rows `unresolved_event_ids()` reads, so
    a spelling with no term covering it would be guessed and never found -
    "경상남도" does not contain "경남"."""
    for form, label in vr._PLACE_TOKENS.items():
        assert any(term in form for term in vr.terms_for_label(label)), form
    for gu in vr._GWANGJU_METRO_GU:
        assert vr.guess_region_label(f"광주 {gu} 어딘가 1") == "광주"


# --- DB-backed: search, week counts and chips agree ------------------------

def _region(pg, code: str) -> dict:
    for row in master_data.list_regions(pg):
        if row["code"] == code:
            return row
    pytest.skip(f"{code} is not seeded; run the migrations first")


def _normalize(pg, unique: str, n: int, *, venue: str, day: str = "2026-11-07",
               name: str | None = None, start: str = "20:00") -> dict:
    return normalization.normalize_candidate(pg, {
        "candidate_id": int(f"7{unique[-5:]}{n:02d}"), "post_id": 1,
        "source_url": f"https://example.test/v09636-region/{unique}-{n}",
        "event_name": name or f"지역 검색 {n} {unique}",
        "event_type": "MILONGA", "event_date": day,
        "start_time": start, "end_time": "23:30", "end_day_offset": 0,
        "venue": venue, "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    })


def _ids(pg, unique: str, **kw) -> set[int]:
    found = events_api.search(pg, limit=100, **kw)["events"]
    return {e["id"] for e in found if unique in e["name"]}


@pytest.fixture
def corpus(pg, unique):
    """One of each kind of row a region filter has to answer for."""
    register_venue(pg, f"서울 스튜디오 {unique}", region_code="KR-SEOUL")
    register_venue(pg, f"아미고 {unique}", region_code="KR-BUSAN")
    rows = {
        "seoul_resolved": _normalize(pg, unique, 1, venue=f"서울 스튜디오 {unique}"),
        "seoul_address": _normalize(
            pg, unique, 2, venue=f"Tango Pasion {unique} (서울 마포구 월드컵북로6길 69 B1)"),
        "seoul_full": _normalize(
            pg, unique, 3, venue=f"La Vida {unique} (서울특별시 서초구 방배천로 60)"),
        # Resolved to Busan although its own name mentions Seoul: the
        # venue master's region wins over any string.
        "busan_resolved": _normalize(pg, unique, 4, venue=f"아미고 {unique}",
                                     name=f"서울에서 온 DJ 밀롱가 {unique}"),
        "busan_car_park": _normalize(
            pg, unique, 5, venue=f"아미고 {unique}x (서면 황제주차장 2층, 부산진구 부전로 34)"),
        "daejeon_address": _normalize(
            pg, unique, 6, venue=f"땅고 오나다 {unique} (대전시 유성구 대학로76번안길 23 지하)"),
        "brand_only": _normalize(pg, unique, 7, venue=f"울산탱고 {unique}"),
        "no_place": _normalize(pg, unique, 8, venue=f"스튜디오 {unique}"),
        "two_places": _normalize(pg, unique, 9, venue=f"부산 출신 {unique} (서울 마포구 1)"),
    }
    return {key: row["event_id"] for key, row in rows.items()}


PAIRS = [("KR-SEOUL", "서울"), ("KR-BUSAN", "부산"), ("KR-DAEJEON", "대전"),
         ("KR-DAEGU", "대구"), ("KR-JEJU", "제주"), ("KR-ULSAN", "울산")]


@pytest.mark.parametrize("code,label", PAIRS)
def test_the_code_and_the_name_return_the_same_events(pg, unique, corpus, code, label):
    """Three spellings of one master row: the code, the master's own name (the
    operator's to edit - a fresh seed calls KR-SEOUL "Seoul", Production calls
    it 서울) and the Korean label a reader is shown."""
    name = _region(pg, code)["name"]
    by_code = _ids(pg, unique, on="2026-11-07", region=code)
    assert _ids(pg, unique, on="2026-11-07", region=name) == by_code
    assert _ids(pg, unique, on="2026-11-07", region=label) == by_code
    assert _ids(pg, unique, on="2026-11-07", region=code.lower()) == by_code


def test_related_places_are_not_spellings_of_one_another(pg, unique):
    """창원 sits in 경남, but a filter for one is not a filter for the other:
    each master row answers for itself, and the guess files a 창원 address
    under 창원 - the more useful of the two, as it always has."""
    event = _normalize(pg, unique, 30, venue=f"박미 탱고 {unique} (경상남도 창원시 마산합포구 창동거리길 24-2)")
    assert event["region_id"] is None
    assert event["event_id"] in _ids(pg, unique, on="2026-11-07", region="KR-CHANGWON")
    assert event["event_id"] not in _ids(pg, unique, on="2026-11-07", region="KR-GYEONGNAM")


def test_each_region_returns_exactly_the_events_that_display_it(pg, unique, corpus):
    expected = {
        "KR-SEOUL": {"seoul_resolved", "seoul_address", "seoul_full"},
        "KR-BUSAN": {"busan_resolved", "busan_car_park"},
        "KR-DAEJEON": {"daejeon_address"},
        "KR-JEJU": set(),
        "KR-ULSAN": set(),
    }
    for code, keys in expected.items():
        assert _ids(pg, unique, on="2026-11-07", region=code) == {
            corpus[k] for k in keys}, code
    # The events with no evidence of a place are under no region at all.
    placed = set().union(*(
        _ids(pg, unique, on="2026-11-07", region=row["code"])
        for row in master_data.list_regions(pg)))
    assert {corpus["brand_only"], corpus["no_place"], corpus["two_places"]}.isdisjoint(placed)
    # ... and every served event's displayed region is the region it is
    # filed under, which is the invariant the filter now keeps.
    for event in events_api.search(pg, on="2026-11-07", limit=100)["events"]:
        if unique not in event["name"] or not event["region"]:
            continue
        assert event["id"] in _ids(pg, unique, on="2026-11-07", region=event["region"])


def test_nothing_is_written_by_a_search(pg, unique, corpus):
    with pg.cursor() as cur:
        cur.execute("SELECT event_id, region_id, venue_id, venue_status FROM events "
                    "WHERE event_id = ANY(%s) ORDER BY 1", (list(corpus.values()),))
        before = cur.fetchall()
        for code, label in PAIRS:
            events_api.search(pg, on="2026-11-07", region=code, limit=100)
            events_api.search(pg, on="2026-11-07", region=label, limit=100)
        cur.execute("SELECT event_id, region_id, venue_id, venue_status FROM events "
                    "WHERE event_id = ANY(%s) ORDER BY 1", (list(corpus.values()),))
        assert cur.fetchall() == before
    assert all(row[1] is None for row in before
               if row[0] in (corpus["seoul_address"], corpus["daejeon_address"]))


def test_week_counts_agree_for_the_code_and_the_name(pg, unique, corpus):
    day = date(2026, 11, 7)
    for code, label in PAIRS:
        assert (events_api.week_counts(pg, start=day, end=day, region=code)
                == events_api.week_counts(pg, start=day, end=day, region=label)), code


def test_a_chip_counts_what_its_filter_returns(pg, unique, corpus):
    """The chip for 서울 is a promise about ?region=서울 - the unresolved Seoul
    addresses included, which the old chip left out."""
    day = date(2026, 11, 7)
    facets = public._facets_window(pg, (day, day))
    chips = {row["value"]: row["events"] for row in facets["region_options"]}
    for row in master_data.list_regions(pg):
        if not row.get("city"):
            continue
        total = events_api.search(pg, on=day.isoformat(), region=row["code"], limit=1)["total"]
        assert chips.get(row["name"], 0) == total, row["code"]


def test_an_unknown_region_value_still_answers_nothing_rather_than_everything(pg, unique, corpus):
    assert _ids(pg, unique, on="2026-11-07", region="남극") == set()
    assert _ids(pg, unique, on="2026-11-07", region="KR-NOWHERE") == set()


def test_a_folded_duplicate_is_not_served_twice_under_a_region(pg, unique):
    register_venue(pg, f"EN PAZ {unique}", region_code="KR-SEOUL")
    _normalize(pg, unique, 20, venue=f"EN PAZ {unique}", name=f"비다미아 {unique}")
    _normalize(pg, unique, 21, venue=f"EN PAZ {unique}", name=f"비다미아 {unique}")
    duplicates.scan(pg, on=date(2026, 11, 7))
    for value in ("KR-SEOUL", "서울"):
        assert len(_ids(pg, unique, on="2026-11-07", region=value)) == 1
