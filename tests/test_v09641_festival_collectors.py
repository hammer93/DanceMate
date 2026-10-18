"""v0.96.41 - the two structured calendars say which of their records is a festival.

TangoNOW's share pages and Miltang's notices publish festivals, marathons and
tango weeks as the same schema.org `Event` record as a milonga, and the engine
read every one of them as nothing: no night word, no clock, so OTHER. Neither
source carries a category, so the collector answers from the record's own
structure and its own name (`runtime/festival_evidence.py`):

* a date and no clock of its own;
* a name announcing a festival, marathon, tango week, weekend or encuentro;
* a name announcing no other format (a workshop tour, a seminar, a show).

The period travels only when the record states its end. Every one of the 12
live TangoNOW date-only pages states a start and no end; all of Miltang's
notices state both.

Fixtures: `tests/fixture_v09641_festivals.py`, captured from the live pages.
"""

from __future__ import annotations

import json

import pytest

from runtime import festival_evidence, intake, miltang_discovery, tangonow_discovery
from tests.fixture_v09641_festivals import MILTANG_NOTICES, TANGONOW_DATE_ONLY

KEYS = {"source_event_format", "event_period", "festival_evidence"}


def _share_page(event: dict) -> str:
    return ('<!doctype html><html><head><script type="application/ld+json">'
            + json.dumps(event, ensure_ascii=False)
            + "</script></head><body></body></html>")


def _notice_page(notice: dict) -> str:
    """A Miltang detail page with the rows its template renders."""
    rows = [f"<div><dt>DATE</dt><dd>{notice['date_row']}</dd></div>"]
    for label, key in (("TIME", "time_row"), ("PLACE", "place_row"), ("ORG", "org_row")):
        if notice.get(key):
            rows.append(f"<div><dt>{label}</dt><dd>{notice[key]}</dd></div>")
    description = (
        '<h3 class="text-xs font-bold text-brand tracking-widest">DESCRIPTION</h3>'
        f'<div class="text-sm ql-content">{notice["description"]}</div>'
        if notice.get("description") else "")
    return ("<!DOCTYPE html><html><head><title>x</title></head><body>"
            '<script type="application/ld+json">'
            + json.dumps(notice["ld"], ensure_ascii=False) + "</script>"
            + f"<h2>{notice['ld']['name']}</h2><dl>{''.join(rows)}</dl>{description}"
            "</body></html>")


def _share(name: str) -> dict:
    found = [(url, ld) for url, ld in TANGONOW_DATE_ONLY.items() if ld["name"] == name]
    assert len(found) == 1, name
    url, ld = found[0]
    return tangonow_discovery.parse_share_page(_share_page(ld), url)


def _notice(number: int) -> dict:
    url = f"https://miltang.com/notices/{number}"
    return miltang_discovery.parse_detail(_notice_page(MILTANG_NOTICES[url]), url)


# --- TangoNOW: twelve date-only pages ---------------------------------------

TANGONOW_FESTIVALS = {
    "BUSAN TANGO FESTIVAL": "2026-10-21",
    "제1회 마산 가고파 국화 탱고 마라톤": "2026-10-31",
    "SEOUL TANGO WEEK 2026": "2026-11-12",
    "KOREA SPECIAL TANGO WEEK 2026": "2026-11-18",
    "엘 불린 땅고 | 2027 서울 땅고 페스티발": "2027-04-29",
    "2027 GUNSAN SUNSET TANGO MARATHON": "2027-05-21",
    "Busan Tango Weekend El Mar": "2027-09-02",
}
#: Date-only too, and not festivals by their own names. `The Best Tangueros
#: Seoul` also restates a 13:00 clock in its description.
TANGONOW_NOT_FESTIVALS = [
    "The Best Tangueros Seoul", "RoyBeDDong in BUSAN",
    "posTango | CRAB MILONGA - POSTANGO 22nd ANNIVERSARY", "서라벌 밀롱게로스",
    "Jeju Summ Milonga",
]


def test_the_fixture_is_the_whole_live_date_only_set():
    assert len(TANGONOW_DATE_ONLY) == 12
    assert set(TANGONOW_FESTIVALS) | set(TANGONOW_NOT_FESTIVALS) == {
        ld["name"] for ld in TANGONOW_DATE_ONLY.values()}
    assert not any(ld.get("endDate") for ld in TANGONOW_DATE_ONLY.values())


@pytest.mark.parametrize("name,start", sorted(TANGONOW_FESTIVALS.items()))
def test_a_tangonow_festival_page_says_so_and_states_only_its_start(name, start):
    record = _share(name)
    assert record["source_event_format"] == "FESTIVAL"
    # No page states its end, so none is claimed.
    assert record["event_period"] == {"start": start}
    assert "TangoNOW share page" in record["festival_evidence"]
    # The body is the page's own facts, untouched by the judgement.
    assert "FESTIVAL" not in record["body"] and "페스티벌" not in record["body"].replace(
        name, "")


@pytest.mark.parametrize("name", TANGONOW_NOT_FESTIVALS)
def test_a_tangonow_page_that_is_not_a_festival_carries_no_judgement(name):
    record = _share(name)
    assert not KEYS & set(record)


def test_a_clocked_night_is_never_a_festival_even_if_its_name_says_so():
    page = dict(TANGONOW_DATE_ONLY[next(u for u, ld in TANGONOW_DATE_ONLY.items()
                                        if ld["name"] == "BUSAN TANGO FESTIVAL")])
    page["startDate"] = "2026-10-21T20:00:00+09:00"
    page["endDate"] = "2026-10-22T01:00:00+09:00"
    record = tangonow_discovery.parse_share_page(_share_page(page), "https://ktnow.kr/e/x")
    assert not KEYS & set(record)


def test_the_movie_night_is_still_nothing():
    """The v0.96.35 refusal: a screening at a tango venue is not a night, and
    it is not a festival either."""
    page = {"@type": "Event", "name": "Club Troilo | 트로일로 무비 나잇!!!",
            "startDate": "2026-10-17", "eventStatus": "https://schema.org/EventScheduled",
            "location": {"@type": "Place", "name": "Club Troilo"}}
    record = tangonow_discovery.parse_share_page(_share_page(page), "https://ktnow.kr/e/y")
    assert not KEYS & set(record) and "source_night_fallback" not in record


def test_a_cancelled_festival_page_is_no_record_at_all():
    page = dict(next(ld for ld in TANGONOW_DATE_ONLY.values()
                     if ld["name"] == "SEOUL TANGO WEEK 2026"))
    for status in ("EventCancelled", "EventPostponed"):
        page["eventStatus"] = f"https://schema.org/{status}"
        assert tangonow_discovery.parse_share_page(_share_page(page), "u") is None


def test_the_same_page_twice_gives_the_same_record():
    for name in TANGONOW_FESTIVALS:
        assert json.dumps(_share(name), sort_keys=True, ensure_ascii=False) == \
            json.dumps(_share(name), sort_keys=True, ensure_ascii=False)


# --- Miltang: notices ---------------------------------------------------------

MILTANG_FESTIVALS = {
    12: ("BUSAN TANGO FESTIVAL", {"start": "2026-10-21", "end": "2026-10-29"}),
    14: ("제1회 마산 가고파 국화 탱고 마라톤", {"start": "2026-10-31", "end": "2026-11-01"}),
    15: ("2026 Seoul Tango Week", {"start": "2026-11-11", "end": "2026-11-16"}),
    19: ("KOREA SPECIAL TANGO WEEK 2026 (홍대)", {"start": "2026-11-21", "end": "2026-11-24"}),
    20: ("KOREA SPECIAL TANGO WEEK 2026 (포항)", {"start": "2026-11-18", "end": "2026-11-21"}),
}
#: 16 is a seminar and show, 10 a teacher couple's two-week visit, 11 and 13
#: name no festival, and 4 names a milonga and states its own clocks.
MILTANG_NOT_FESTIVALS = [4, 10, 11, 13, 16]


@pytest.mark.parametrize("number", sorted(MILTANG_FESTIVALS))
def test_a_miltang_festival_notice_carries_its_own_period(number):
    name, period = MILTANG_FESTIVALS[number]
    record = _notice(number)
    assert record["title"] == name
    assert record["source_event_format"] == "FESTIVAL"
    assert record["event_period"] == period
    assert "Miltang notice" in record["festival_evidence"]


@pytest.mark.parametrize("number", MILTANG_NOT_FESTIVALS)
def test_a_miltang_notice_that_is_not_a_festival_carries_no_judgement(number):
    assert not KEYS & set(_notice(number))


def test_a_milonga_board_page_is_never_asked():
    """`/milongas` is a board of nights; the judgement is a notice's only."""
    url = "https://miltang.com/milongas/999"
    record = miltang_discovery.parse_detail(
        _notice_page(MILTANG_NOTICES["https://miltang.com/notices/12"]), url)
    assert not KEYS & set(record)


def test_the_collector_changes_nothing_else_about_the_record():
    """Title and body exactly as the collector wrote them before (captured from
    Production's v0.96.40 run of the same pages): the judgement is beside the
    page's text, so collecting it does not re-key the item."""
    bodies = {
        12: "2026년 10월 21일 장소: Detango (데땅고) (부산광역시 부산진구 서면로68번길 41) "
            "DE TANGO 17th Anniversary",
        20: "2026년 11월 18일 장소: PosTango (포스탱고) (포항시 남구 중앙로 83, 3층 프스탱고) "
            "주최: 부산탱고협동조합 협찬 | 부산 탱고 마라톤 [포항] 11/18~11/20 워크숍 & 이벤트 "
            "POHANG WELCOME MILONGA — 11/20(금) 20:00~01:00 [서울] 11/21~11/24 워크숍 & 이벤트 "
            "SEOUL GRAND MILONGA @Ocho — 11/21(토) 21:00~02:00",
    }
    # The fixture carries no LINK row, so the bodies end before `원문 링크:`.
    for number, body in bodies.items():
        assert _notice(number)["body"] == body


# --- the policy itself --------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("BUSAN TANGO FESTIVAL", True),
    ("춘천 국제탱고 페스티벌", True),
    ("2027 서울 땅고 페스티발", True),
    ("제1회 마산 가고파 국화 탱고 마라톤", True),
    ("2026 Seoul Tango Week", True),
    ("Busan Tango Weekend El Mar", True),
    ("Belgrade Tango Encuentro", True),
    ("Chicho Frumboli & Juana Sepulveda  Tango Seminar & Show", False),
    ("Stephanie Fesneau Fausto Carpino Seoul workshop", False),
    ("Tango Festival Workshop Series", False),
    ("Club Troilo | 트로일로 무비 나잇!!!", False),
    ("Tango Festival 취소 안내", False),
    ("JEJU Summ Milonga", False),
    ("Estrellas", False),
    ("Weekly Milonga", False),
])
def test_what_a_name_must_say(name, expected):
    assert festival_evidence.names_a_festival(name) is expected


def test_a_period_is_carried_only_when_it_is_one():
    judge = festival_evidence.judgement
    ok = judge("BUSAN TANGO FESTIVAL", "2026-10-21", "2026-10-29",
               states_a_clock=False, source="t")
    assert ok["event_period"] == {"start": "2026-10-21", "end": "2026-10-29"}
    for end in ("2026-10-21", "2026-10-20", "2026-12-25", "not a date", None, ""):
        assert judge("BUSAN TANGO FESTIVAL", "2026-10-21", end, states_a_clock=False,
                     source="t")["event_period"] == {"start": "2026-10-21"}, end
    assert judge("BUSAN TANGO FESTIVAL", "2026-10-21T20:00:00+09:00", None,
                 states_a_clock=False, source="t")["event_period"] == {"start": "2026-10-21"}
    assert judge("BUSAN TANGO FESTIVAL", None, None, states_a_clock=False, source="t") is None
    assert judge("BUSAN TANGO FESTIVAL", "2026-10-21", None, states_a_clock=True,
                 source="t") is None


def test_the_judgement_reaches_the_record_the_engine_reads():
    """Both keys intake re-stores on and the raw post mapping carries."""
    assert KEYS <= set(intake.JUDGEMENT_KEYS)
    from runtime import engine_ingest

    class Record:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    record = _notice(12)
    post = engine_ingest._to_raw_post(
        Record, {"raw": record, "title": record["title"], "source_id": "S",
                 "platform": "WEB", "url": record["source_url"]},
        {"body": record["body"], "acquisition_quality": "FETCHED_FULL"})
    assert post.source_event_format == "FESTIVAL"
    assert post.event_period == {"start": "2026-10-21", "end": "2026-10-29"}


# --- the judgement reaches an item already collected (database) -------------

@pytest.fixture
def notice_source(pg, unique):
    from runtime import sources

    return sources.create_source(
        pg, source_key=f"SRC-W-{unique}", name="Miltang festival judgement test",
        platform="WEB", source_role="DIRECTORY", queries=[],
        config={"parser": "miltang"},
    )


def _raw_item(record: dict) -> intake.RawItem:
    raw = dict(record, source_id="SRC-W-005", platform="WEB")
    return intake.RawItem(external_id=record["source_url"], url=record["source_url"],
                          title=record["title"], body=record["body"],
                          published_at=None, raw=raw)


def test_an_unchanged_notice_that_is_now_judged_a_festival_is_a_revision(pg, notice_source):
    """The page's text has not moved, so only the judgement can carry the
    period to the item collected before this release - and collecting the
    same judgement again is a duplicate, so it happens once."""
    judged = _notice(12)
    plain = {k: v for k, v in judged.items() if k not in KEYS}
    source_id = notice_source["source_id"]
    assert intake.store_item(pg, source_id, _raw_item(plain)) == "NEW"
    assert intake.store_item(pg, source_id, _raw_item(judged)) == "REVISED"
    assert intake.store_item(pg, source_id, _raw_item(judged)) == "DUPLICATE"
    [row] = intake.recent_items(pg, source_id=source_id)
    assert row["raw"]["event_period"] == {"start": "2026-10-21", "end": "2026-10-29"}
    assert row["raw"]["source_event_format"] == "FESTIVAL"
