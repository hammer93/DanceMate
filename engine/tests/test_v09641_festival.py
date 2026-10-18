"""v0.96.41 - a festival is a period, and the nights it dates are its own.

A structured tango calendar files a record as a festival when the record is
dated, states no clock of its own and names itself a festival, marathon or
tango week (runtime/festival_evidence.py). The engine:

* classifies it FESTIVAL from that judgement, below the one guard above
  `known_event_type`, and never from a word in the text;
* makes one candidate for the period: its first day (and only if the record's
  own text writes that date), its last day only when the record states one,
  its labelled place, and no time, fee or DJ - a period has no one clock;
* makes one candidate per night the record's own text dates and clocks
  (`NAME [@Place] — m/d(요일) HH:MM~HH:MM`), each owning its date, clock and
  place, and only inside the record's own period.

REAL fixtures are the stored bodies of Production source items (verbatim);
SYNTHETIC ones are written here to isolate one rule and say so.
"""

from __future__ import annotations

import pytest

from src import classifier
from src.collectors.base import RawPostRecord
from src.extractor import FESTIVAL, extract_festival, extract_festival_programmes
from src.live_pipeline import process_discovered_post

# REAL: Miltang notice 20 (source item 6107), and notice 19 (item 6108).
KSTW_POHANG = (
    "2026년 11월 18일 장소: PosTango (포스탱고) (포항시 남구 중앙로 83, 3층 프스탱고) "
    "주최: 부산탱고협동조합 협찬 | 부산 탱고 마라톤 [포항] 11/18~11/20 워크숍 & 이벤트 "
    "POHANG WELCOME MILONGA — 11/20(금) 20:00~01:00 [서울] 11/21~11/24 워크숍 & 이벤트 "
    "SEOUL GRAND MILONGA @Ocho — 11/21(토) 21:00~02:00 원문 링크: https://www.facebook.com/ocho.tango.5")
KSTW_HONGDAE = (
    "2026년 11월 21일 장소: Ocho (오초) (서울 마포구 월드컵북로2길 57 지하1층) "
    "주최: 부산탱고협동조합 협찬 | 부산 탱고 마라톤 [포항] 11/18~11/20 워크숍 & 이벤트 "
    "POHANG WELCOME MILONGA — 11/20(금) 20:00~01:00 [서울] 11/21~11/24 워크숍 & 이벤트 "
    "SEOUL GRAND MILONGA @Ocho — 11/21(토) 21:00~02:00 원문 링크: https://www.facebook.com/ocho.tango.5")
# REAL: TangoNOW share pages, items 6245 and 6226.
KSTW_SHARE = "2026년 11월 18일 장소: 포항 posTango · 서울 OCHO 주최: 부산탱고협동조합"
BUSAN_SHARE = "2026년 10월 21일 장소: 데땅고 주최: Lucas Carrizo, Maria Paula Tejeda"
# REAL: Miltang notice 12 (item 1338).
BUSAN_NOTICE = ("2026년 10월 21일 장소: Detango (데땅고) (부산광역시 부산진구 서면로68번길 41) "
                "DE TANGO 17th Anniversary 원문 링크: https://www.facebook.com/share/p/1ANKLmedXp/")
# REAL: Miltang notice 14 (item 1340), and its poster's own rows as OCR read them.
MASAN_NOTICE = ("2026년 10월 31일 장소: Tango club Mi Noche (경남 창원시 마산합포구 가포로25 지하1층) "
                "주최: ISABELLE & SENS 원문 링크: https://www.facebook.com/share/1GcpFkAHqW/")
MASAN_ROWS = ("M1: 10. 31. 16:00 -18:00 (DJ =A)\nM2 : 10. 31. 20:00-24:00 (DJ 톨로!)\n"
              "M3 = 11. 01, 14:00-18:00 (DJ 미자렐)")

POHANG_PERIOD = {"start": "2026-11-18", "end": "2026-11-21"}
HONGDAE_PERIOD = {"start": "2026-11-21", "end": "2026-11-24"}


def _post(title, body, period=None, fmt="FESTIVAL", **extra):
    return RawPostRecord(source_id="SRC-W-005", platform="WEB", source_url="https://x.test/1",
                         title=title, body=body, acquisition_quality="FETCHED_FULL",
                         source_event_format=fmt if period is not None else None,
                         event_period=period, **extra)


def _run(post):
    return process_discovered_post(None, post)


def _row(ev):
    return (ev.event_type, ev.date, ev.start_time, ev.end_time, ev.end_day_offset, ev.venue)


# --- classification ---------------------------------------------------------

def test_the_judgement_is_what_makes_a_festival():
    assert classifier.classify("KOREA SPECIAL TANGO WEEK 2026", KSTW_SHARE,
                               source_event_format="FESTIVAL") == "FESTIVAL"


def test_without_the_judgement_nothing_changes():
    """The words still read what they read before: SOCIAL off "SPECIAL" for
    the share page, CLASS off the 워크숍 for the notice, OTHER for the rest."""
    assert classifier.classify("KOREA SPECIAL TANGO WEEK 2026", KSTW_SHARE) == "SOCIAL"
    assert classifier.classify("KOREA SPECIAL TANGO WEEK 2026 (포항)", KSTW_POHANG) == "CLASS"
    assert classifier.classify("BUSAN TANGO FESTIVAL", BUSAN_SHARE) == "OTHER"
    for title, body in (("KOREA SPECIAL TANGO WEEK 2026", KSTW_SHARE),
                        ("BUSAN TANGO FESTIVAL", BUSAN_SHARE)):
        assert _run(_post(title, body))["classification"] != FESTIVAL


@pytest.mark.parametrize("value", ["MILONGA", "SOCIAL", "CLASS", "festival", ["FESTIVAL"],
                                   {"x": 1}, 7])
def test_a_collector_cannot_inject_any_other_type(value):
    assert classifier.classify("BUSAN TANGO FESTIVAL", BUSAN_SHARE,
                               source_event_format=value) == "OTHER"


def test_a_recap_is_still_refused_first():
    """`is_non_event_notice()` stays the one rule above every prior."""
    assert classifier.classify("BUSAN TANGO FESTIVAL 후기 사진", BUSAN_SHARE,
                               source_event_format="FESTIVAL") == "OTHER"


def test_a_milonga_board_prior_still_wins():
    assert classifier.classify("Milonga Marathon", "x", known_event_type="MILONGA",
                               source_event_format="FESTIVAL") == "MILONGA"


# --- the festival candidate --------------------------------------------------

def test_a_date_only_festival_is_its_date_and_nothing_more():
    """TangoNOW states the start and no end: one day is claimed, no time."""
    events = _run(_post("BUSAN TANGO FESTIVAL", BUSAN_SHARE, {"start": "2026-10-21"}))["events"]
    assert [_row(e) for e in events] == [(FESTIVAL, "2026-10-21", None, None, 0, "데땅고")]
    festival = events[0]
    assert festival.fee is None and festival.dj is None
    assert not [e for e in festival.evidences if e.field in ("end_date", "time", "fee")]
    assert festival.status == "POSSIBLE"


def test_an_explicit_period_is_recorded_as_its_last_day():
    events = _run(_post("BUSAN TANGO FESTIVAL", BUSAN_NOTICE,
                        {"start": "2026-10-21", "end": "2026-10-29"}))["events"]
    assert len(events) == 1
    ends = [(e.value, e.inference) for e in events[0].evidences if e.field == "end_date"]
    assert ends == [("2026-10-29", "FESTIVAL_PERIOD")]
    assert events[0].venue.startswith("Detango")


def test_a_period_has_no_clock_even_when_its_text_has_one():
    """`extract_single()` reads 20:00~01:00 off KSTW's notice - its welcome
    milonga's hours. The festival claims none of them."""
    festival = _run(_post("KOREA SPECIAL TANGO WEEK 2026 (포항)", KSTW_POHANG,
                          POHANG_PERIOD))["events"][0]
    assert festival.event_type == FESTIVAL
    assert (festival.start_time, festival.end_time, festival.end_day_offset) == (None, None, 0)
    assert [e.value for e in festival.evidences if e.field == "context"] == [
        "FESTIVAL_NO_SINGLE_CLOCK"]


def test_a_judgement_its_text_does_not_bear_out_produces_nothing():
    """The record says the 21st and the body the 22nd: no choice is made."""
    assert _run(_post("BUSAN TANGO FESTIVAL", BUSAN_SHARE.replace("21일", "22일"),
                      {"start": "2026-10-21"}))["events"] == []
    assert _run(_post("BUSAN TANGO FESTIVAL", BUSAN_SHARE, {"start": "garbage"}))["events"] == []
    assert _run(_post("BUSAN TANGO FESTIVAL", BUSAN_SHARE, {}))["events"] == []


@pytest.mark.parametrize("end", ["2026-10-21", "2026-10-20", "2026-12-25", "x"])
def test_a_last_day_that_is_not_a_period_is_not_recorded(end):
    events = _run(_post("BUSAN TANGO FESTIVAL", BUSAN_SHARE,
                        {"start": "2026-10-21", "end": end}))["events"]
    assert len(events) == 1 and not [e for e in events[0].evidences if e.field == "end_date"]


def test_a_two_city_festival_keeps_the_place_its_text_labels_first():
    """`포항 posTango · 서울 OCHO`: read exactly as any post's 장소 field is."""
    events = _run(_post("KOREA SPECIAL TANGO WEEK 2026", KSTW_SHARE,
                        {"start": "2026-11-18"}))["events"]
    assert [_row(e) for e in events] == [(FESTIVAL, "2026-11-18", None, None, 0,
                                          "포항 posTango")]


# --- the nights it dates -----------------------------------------------------

def test_each_night_owns_its_date_clock_and_place():
    """The 포항 notice: its welcome milonga at its own room, and the Seoul
    grand milonga at the Ocho its own row names - never the 포항 room."""
    events = _run(_post("KOREA SPECIAL TANGO WEEK 2026 (포항)", KSTW_POHANG,
                        POHANG_PERIOD))["events"]
    pohang = "PosTango (포스탱고) (포항시 남구 중앙로 83, 3층 프스탱고)"
    assert [_row(e) for e in events] == [
        (FESTIVAL, "2026-11-18", None, None, 0, pohang),
        ("MILONGA", "2026-11-20", "20:00", "01:00", 1, pohang),
        ("MILONGA", "2026-11-21", "21:00", "02:00", 1, "Ocho"),
    ]
    assert events[1].name.endswith("POHANG WELCOME MILONGA")
    assert events[2].name.endswith("SEOUL GRAND MILONGA")
    for night in events[1:]:
        assert [e.value for e in night.evidences if e.field == "context"] == [
            "FESTIVAL_PROGRAMME"]
        assert {e.context_id for e in night.evidences} == {night.evidences[0].context_id}


def test_a_night_outside_the_records_own_period_is_not_its_to_announce():
    """The 홍대 notice (11/21~24) repeats the 포항 week's 11/20 milonga."""
    events = _run(_post("KOREA SPECIAL TANGO WEEK 2026 (홍대)", KSTW_HONGDAE,
                        HONGDAE_PERIOD))["events"]
    assert [_row(e) for e in events] == [
        (FESTIVAL, "2026-11-21", None, None, 0, "Ocho (오초) (서울 마포구 월드컵북로2길 57 지하1층)"),
        ("MILONGA", "2026-11-21", "21:00", "02:00", 1, "Ocho"),
    ]


def test_a_record_with_no_stated_end_dates_no_nights():
    """Without a period a yearless `11/20` cannot be placed."""
    events = _run(_post("KOREA SPECIAL TANGO WEEK 2026 (포항)", KSTW_POHANG,
                        {"start": "2026-11-18"}))["events"]
    assert [e.event_type for e in events] == [FESTIVAL]


def test_a_night_under_another_citys_header_is_not_handed_the_records_room():
    """SYNTHETIC: the Seoul row without its own `@Ocho` must not inherit the
    Pohang notice's PosTango."""
    body = KSTW_POHANG.replace(" @Ocho", "")
    events = _run(_post("KOREA SPECIAL TANGO WEEK 2026 (포항)", body, POHANG_PERIOD))["events"]
    seoul = [e for e in events if e.date == "2026-11-21"]
    assert [_row(e) for e in seoul] == [("MILONGA", "2026-11-21", "21:00", "02:00", 1, None)]


def test_two_nights_at_one_venue_and_a_practica():
    """SYNTHETIC: one venue, two nights, and a practica named as one."""
    body = ("2027년 5월 21일 장소: Pasion Hall 주최: Seoul Tango "
            "WELCOME MILONGA — 5/21(금) 20:00~01:00 GALA MILONGA — 5/22(토) 21:00~02:00 "
            "SUNDAY PRACTICA — 5/23(일) 15:00~18:00")
    events = _run(_post("Seoul Tango Festival", body,
                        {"start": "2027-05-21", "end": "2027-05-23"}))["events"]
    assert [_row(e) for e in events] == [
        (FESTIVAL, "2027-05-21", None, None, 0, "Pasion Hall"),
        ("MILONGA", "2027-05-21", "20:00", "01:00", 1, "Pasion Hall"),
        ("MILONGA", "2027-05-22", "21:00", "02:00", 1, "Pasion Hall"),
        ("PRACTICA", "2027-05-23", "15:00", "18:00", 0, "Pasion Hall"),
    ]


def test_a_period_across_new_year_places_each_row_in_its_own_year():
    body = "2026년 12월 30일 장소: Pasion Hall 주최: Seoul Tango NEW YEAR MILONGA — 1/1(금) 20:00~02:00"
    events = _run(_post("Winter Tango Marathon", body,
                        {"start": "2026-12-30", "end": "2027-01-02"}))["events"]
    assert [e.date for e in events] == ["2026-12-30", "2027-01-01"]


@pytest.mark.parametrize("row", [
    # a workshop is not a night
    "TANGO WORKSHOP — 5/22(토) 14:00~16:00",
    # a cancelled night announces nothing
    "GALA MILONGA 취소 — 5/22(토) 21:00~02:00",
    # a clock that could be morning
    "GALA MILONGA — 5/22(토) 9:00~11:00",
    # a row that names no night (the Masan poster's shape)
    "M2 — 5/22(토) 20:00~24:00",
    # a day the period does not contain
    "GALA MILONGA — 6/22(토) 21:00~02:00",
    # a date that does not exist
    "GALA MILONGA — 2/30(토) 21:00~02:00",
])
def test_rows_that_are_not_a_night_of_this_festival(row):
    """SYNTHETIC, one refusal each."""
    body = f"2027년 5월 21일 장소: Pasion Hall 주최: Seoul Tango {row}"
    events = _run(_post("Seoul Tango Festival", body,
                        {"start": "2027-05-21", "end": "2027-05-23"}))["events"]
    assert [e.event_type for e in events] == [FESTIVAL]


def test_the_masan_marathon_is_one_festival_and_no_invented_nights():
    """Its poster's sessions (`M1: 10. 31. 16:00 -18:00 (DJ ..)`) name no
    night, so the record is the marathon and nothing else."""
    events = _run(_post("제1회 마산 가고파 국화 탱고 마라톤", f"{MASAN_NOTICE}\n{MASAN_ROWS}",
                        {"start": "2026-10-31", "end": "2026-11-01"}))["events"]
    assert [_row(e) for e in events] == [
        (FESTIVAL, "2026-10-31", None, None, 0,
         "Tango club Mi Noche (경남 창원시 마산합포구 가포로25 지하1층)")]


def test_one_night_read_twice_is_one_night():
    body = (KSTW_POHANG + " SEOUL GRAND MILONGA @Ocho — 11/21(토) 21:00~02:00")
    events = _run(_post("KOREA SPECIAL TANGO WEEK 2026 (포항)", body, POHANG_PERIOD))["events"]
    assert [e.date for e in events] == ["2026-11-18", "2026-11-20", "2026-11-21"]


def test_the_programme_reader_needs_a_period():
    from datetime import date

    festival = extract_festival("x", "2026년 11월 18일", {"start": "2026-11-18"})[0]
    assert extract_festival_programmes("x", KSTW_POHANG, date(2026, 11, 18), None,
                                       festival) is None


def test_the_route_is_deterministic():
    post = _post("KOREA SPECIAL TANGO WEEK 2026 (포항)", KSTW_POHANG, POHANG_PERIOD)
    first = [e.to_dict() for e in _run(post)["events"]]
    second = [e.to_dict() for e in _run(post)["events"]]
    assert first == second


def test_a_page_acquired_as_text_states_its_date_its_own_way():
    """REAL: source item 6250's acquired page text (FETCHED_PARTIAL) is what
    the re-read sees, not the synthesized body - and it writes the record's
    start as `2027-05-21(금)`. The same date in another form counts; another
    date does not."""
    text = ("2027 GUNSAN SUNSET TANGO MARATHON 2027 GUNSAN SUNSET TANGO MARATHON "
            "2027-05-21(금) · 군산 Tango NOW에서 상세 정보 보기")
    events = _run(_post("2027 GUNSAN SUNSET TANGO MARATHON", text,
                        {"start": "2027-05-21"}))["events"]
    assert [(e.event_type, e.date, e.start_time) for e in events] == [
        (FESTIVAL, "2027-05-21", None)]
    assert _run(_post("2027 GUNSAN SUNSET TANGO MARATHON", text,
                      {"start": "2027-05-22"}))["events"] == []
