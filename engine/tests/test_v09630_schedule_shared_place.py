"""v0.96.30: a dated program keeps the place its own post states in its field.

danceinfo renders a lesson page's payload as the page lays it out, and the
place is one of those fields:

    2026-09-30 전체일정 2026-09-30,...,2026-10-03 일정정보 8시(50분), ... 장소 강턴
    DJ DJ분 강의 소개 9월 30일부터 10월 3일까지, 4일간의 소셜이벤트 ...

v0.96.29 taught `extract_venue()` to read that field, and the post as a whole
reads as 강턴 today. But a multi-day announcement does not stay one candidate:
`extract_schedule()` gives each dated program its own scope, running from that
program's date to the next one - and the structured header sits *before* the
first date, so it lands in no program's scope at all. Every night of the run
then reads as nowhere.

Measured over the stored corpus at v0.96.29: twelve posts expand through this
route, eight of them carry a structured place field, and **all eight lose it on
at least one program** - 19 Events. Which program keeps it is pure accident of
position: the last date of the post's own `전체일정` list owns the segment that
happens to contain the header, so 보니따's 추석 run keeps 보니따 on 09-27 and
loses it on 09-24, 09-25 and 09-26.

`extract_day_list()`, the other expansion route, was the initial suspect and is
not the defect: all five posts that take it keep the field on every day.

Two rules, and the second is the one with teeth:

* a program that named no venue of its own takes the field;
* **a program that named one keeps it.** The field is a fallback for an empty
  venue and never a correction of a full one.

And the field is the only admissible fallback - not a name guessed from prose,
not an unlabelled poster reading, not a city token, not the title.
"""

from __future__ import annotations

from src import extraction_rules
from src.extractor import extract_schedule, extract_single

SOCIAL = "SOCIAL_WITH_CLASS"


def _venues(candidates):
    return {c.date: c.venue for c in candidates or ()}


def _venue_evidence(candidate):
    return next((e for e in candidate.evidences if e.field == "venue"), None)


# A payload rendering in the shape `acquisition.danceinfo_payload_body()`
# writes: the post's own date, its day list, its one schedule string, its
# place, its DJs, and last its free-text description.
def _payload(dates, schedule, place, dj, prose):
    head = f"{dates[0]} 전체일정 {','.join(dates)} 일정정보 {schedule}"
    if place:
        head += f" 장소 {place}"
    if dj:
        head += f" DJ {dj}"
    return f"{head} 강의 소개 {prose}"


# --- T1: the field reaches every program that named no venue ---------------

def test_a_program_with_no_venue_of_its_own_takes_the_field():
    body = _payload(
        ["2026-10-01", "2026-10-02", "2026-10-03"],
        "PM 8:00~9:00, PM 9:00~", "강턴", "DJ 어텐션",
        "10월 1일 목요일부터 3일간 소셜파티가 열립니다. "
        "10월 1일(목) PM9:00~ 목요소셜파티 "
        "10월 2일(금) PM9:00~ 금요소셜파티 "
        "10월 3일(토) PM9:00~ 토요소셜파티",
    )
    got = extract_schedule("강턴 주간일정", body, event_type=SOCIAL)
    assert _venues(got) == {
        "2026-10-01": "강턴", "2026-10-02": "강턴", "2026-10-03": "강턴",
    }


def test_the_inherited_venue_is_recorded_as_the_payload_field_reading():
    """Same evidence v0.96.29 records, not a second, weaker kind."""
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", "강턴", None,
        "10월 1일(목) PM9:00~ 목요소셜파티 10월 2일(금) PM9:00~ 금요소셜파티",
    )
    got = extract_schedule("강턴 주간일정", body, event_type=SOCIAL)
    for candidate in got:
        evidence = _venue_evidence(candidate)
        assert evidence is not None
        assert evidence.inference == "LABEL:" + extraction_rules.VENUE_LABEL_PAYLOAD_FIELD
        assert evidence.value["name"] == "강턴"
        assert "강턴" in evidence.value["alias_candidates"]
        assert evidence.raw_text.startswith(extraction_rules.PAYLOAD_PLACE_LABEL)


def test_the_whole_post_already_read_as_that_place_before_this_release():
    """The place was never missing from the post - only from its programs."""
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", "강턴", None,
        "10월 1일(목) PM9:00~ 목요소셜파티 10월 2일(금) PM9:00~ 금요소셜파티",
    )
    assert extract_single("강턴 주간일정", body, event_type=SOCIAL).venue == "강턴"


# --- T2: a program's own venue always wins ---------------------------------

def test_a_programs_own_venue_is_never_replaced_by_the_field():
    """The whole safety argument. A day that names a place keeps it."""
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", "강턴", None,
        "10월 1일(목) PM9:00~ 목요소셜파티 장소: 홍턴 DJ 바밤바 "
        "10월 2일(금) PM9:00~ 금요소셜파티",
    )
    got = _venues(extract_schedule("강남턴 주간일정", body, event_type=SOCIAL))
    assert got["2026-10-01"] == "홍턴", "the day's own label must survive"


def test_a_post_naming_two_places_inherits_nothing():
    """One field cannot be handed to a program the post put elsewhere."""
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", "강턴", None,
        "10월 1일(목) PM9:00~ 목요소셜파티 장소: 홍턴 DJ 바밤바 "
        "10월 2일(금) PM9:00~ 금요소셜파티",
    )
    got = _venues(extract_schedule("강남턴 주간일정", body, event_type=SOCIAL))
    assert got["2026-10-02"] is None, "a contradicted field is not a fallback"


def test_a_day_that_names_the_same_place_is_left_exactly_as_it_read_it():
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", "강턴", None,
        "10월 1일(목) PM9:00~ 목요소셜파티 장소: 강턴 "
        "10월 2일(금) PM9:00~ 금요소셜파티",
    )
    got = extract_schedule("강남턴 주간일정", body, event_type=SOCIAL)
    assert _venues(got) == {"2026-10-01": "강턴", "2026-10-02": "강턴"}
    own = next(c for c in got if c.date == "2026-10-01")
    assert _venue_evidence(own).inference == "LABEL:장소", \
        "the day read it itself; that is what the evidence must say"


# --- T3: prose that is not a payload rendering is no fallback --------------

def test_a_schedule_post_that_is_not_a_payload_rendering_inherits_nothing():
    """Every other source's schedule post. `extract_schedule()` is shared."""
    body = ("9월 소셜 일정 안내입니다. 장소는 아래를 확인해주세요. "
            "10월 1일(목) PM9:00~ 목요소셜파티 "
            "10월 2일(금) PM9:00~ 금요소셜파티")
    got = _venues(extract_schedule("10월 소셜 일정", body, event_type=SOCIAL))
    assert got == {"2026-10-01": None, "2026-10-02": None} or all(
        v is None for v in got.values()), got


def test_a_body_that_merely_says_the_word_장소_is_no_field():
    body = ("10월 행사 일정 안내 장소 공지는 추후 안내드립니다 "
            "10월 1일(목) PM9:00~ 목요소셜파티 "
            "10월 2일(금) PM9:00~ 금요소셜파티")
    assert extraction_rules.payload_place_reading(body) is None
    got = _venues(extract_schedule("10월 소셜 일정", body, event_type=SOCIAL))
    assert all(v is None for v in got.values()), got


def test_a_place_inside_the_description_field_is_not_the_place_field():
    """v0.96.29's boundary: the structured region ends at 강의 소개."""
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", None, None,
        "장소 : 홍턴 에서 모십니다 "
        "10월 1일(목) PM9:00~ 목요소셜파티 10월 2일(금) PM9:00~ 금요소셜파티",
    )
    assert extraction_rules.payload_place_field(body) is None
    got = _venues(extract_schedule("10월 소셜 일정", body, event_type=SOCIAL))
    assert got.get("2026-10-02") is None


# --- T4: no field, no fallback ---------------------------------------------

def test_a_payload_post_with_no_place_field_keeps_its_programs_place_less():
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", None, "DJ 어텐션",
        "10월 1일(목) PM9:00~ 목요소셜파티 10월 2일(금) PM9:00~ 금요소셜파티",
    )
    assert extraction_rules.payload_place_reading(body) is None
    got = _venues(extract_schedule("10월 소셜 일정", body, event_type=SOCIAL))
    assert all(v is None for v in got.values()), got


def test_a_one_character_field_value_is_still_refused():
    """v0.96.29's own minimum, inherited with the reader."""
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", "탑", None,
        "10월 1일(목) PM9:00~ 목요소셜파티 10월 2일(금) PM9:00~ 금요소셜파티",
    )
    assert extraction_rules.payload_place_reading(body) is None
    got = _venues(extract_schedule("10월 소셜 일정", body, event_type=SOCIAL))
    assert all(v is None for v in got.values()), got


# --- T5: an OCR text never becomes a shared place -------------------------

def test_an_ocr_shaped_text_is_not_a_payload_rendering():
    """v0.96.24's contract: no unlabelled image reading becomes a venue.
    Measured at v0.96.29: 0 of 1,803 stored OCR texts match the payload shape.
    """
    ocr = ("SALSA BACHATA SOCIAL 장소 강턴 10월 1일 목요일 PM 9:00 "
           "10월 2일 금요일 PM 9:00 입장료 10000원")
    assert extraction_rules.payload_place_reading(ocr) is None
    got = _venues(extract_schedule("주간일정", ocr, event_type=SOCIAL))
    assert all(v is None for v in (got or {}).values()), got


# --- the measured Production posts ----------------------------------------
#
# Bodies as the v0.96.30 audit printed them from Production, truncated by that
# print at 1100 characters.

ITEM_3734 = (
    "서울살사위크 소셜이벤트",
    "2026-09-30 전체일정 2026-09-30,2026-10-01,2026-10-02,2026-10-03 일정정보 "
    "8시(50분), 8시50분, 8시50분, 4시(50분), 5시(50분), 6시(50분) 장소 강턴 DJ DJ분 "
    "강의 소개 9월 30일부터 10월 3일까지, 4일간의 소셜이벤트 서울살사위크가 열립니다. "
    "아시아 최정상의 디제이분들과 함께합니다!! 4일간의 소셜, 6개의 워크샵을 즐길 수 있는 "
    "풀패스가 얼리버드 가격 6만원으로 구매가능합니다^^ 관심있으신 분들은 저에게 개인톡 "
    "부탁드립니다! (풀패스 외 나머지패스는 현장판매입니다) 워크샵 프로그램 "
    "9월 30일 (수) 제이오 워크샵 8시(50분) - 아프로 쿠반 with 살사 "
    "10월 1일 (목) 핸슨&화라 워크샵 8시50분) -소셜에서의 파트너워크 팁, 클리닉 "
    "10월 2일 (금) 워크샵 끌루이&달라 워크샵 8시50분) -소셜에서의 파트너워크 팁, 클리닉 "
    "10월 3일 (토) WEEK 백호&몽 워크샵 4시(50분) - 소셜에서의 파트너워크 팁, 클리닉 "
    "백호&몽&지야 워크샵 5시(50분) -소셜에서 파트너와 함께 할 수 있는 샤인 "
    "지야 워크샵 6시(50분) - CBL 원리와 응용 \"워크샵 장소는 모두 강턴입니다",
)

ITEM_3766 = (
    "보니따에서 보내는 추석연휴",
    "2026-09-24 전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27 일정정보 "
    "매일 2시간 워크샵 및 파티 7-8시, 8-9시 장소 보니따 DJ DJ 깔리드 강의 소개 "
    "보니따에서 보내는 추석연휴!! 제네바 바차타 소셜 월드컵 챔피언 제렘&제이드 "
    "바차주크 스타일을 물 흐르듯 바차타 소셜에 녹여내는 스타일을 보여줍니다!! "
    "디제이 깔리드 이제 다 알죠! 음악에 음질까지 어나더!! "
    "살사&바차타 국내 탑강사들의 워크샵은 덤!! "
    "워크샵 8시간+ 4일파티 + 음료 = 가성비 풀패스 10만원!! 9만원 (선착순 남10 여10) "
    "요일/닉네임 (or 풀패스 닉네임) 입금만하면 신청완료!!!! "
    "9/24 목 - 코코&무신, 바차타 워크샵 2시간 + 파티+ 1drink "
    "9/25 금 - 용수&팅커벨, 바차타 워크샵 2시간 + 파티+ 1drink - 끌루이&달라, 살사 "
    "워크샵 2시간 + 파티+ 1drink "
    "9/26 토 - 시니&세라, 살사 - 원궁&요니, 바차타 워크샵 2시간 + 파티+ 1drink "
    "9/27일 발 - 니르바나&썬, 바차타 워크샵 2시간 + 파티+ 1drink "
    "그리고 가장 중요한 가격! 15커플 한정, 풀패스 10만원 하루만 와도 가성비, "
    "이틀 이상 온다면 초가성비!",
)

ITEM_3792 = (
    "BACHATA, SALSA, SOCIAL PARTY",
    "2026-09-22 전체일정 2026-09-22,2026-09-23,2026-09-25,2026-09-26,2026-09-27 "
    "일정정보 PM 8:00~9:00, PM 9:00~ 장소 강턴 DJ 어텐션, 헤이즐, 린넨, 리키 강의 소개 "
    "9월 22일 화요일에는 바차타프로젝트 Ep.2가 열리며, 9월 23일 수요일과 9월 25일 "
    "금요일에는 특별한 시간과 워크샵이 진행됩니다. 9월 26일 토요일에는 토요소셜파티가 "
    "열리고, 9월 27일 일요일에는 월간 무차살사:소셜 파티가 예정되어 있습니다. "
    "9월 22일(화) PM9:00~ 강턴 바차타프로젝트 Ep.2 오픈강습 : 원준 & 세이샤 "
    "PM8:00~9:00 색다른 바차타를 배우다 Showtime: PM10:30~ 도미니꼬레아노스 (by 손나리) "
    "DJ 어텐션 음악비율 B5 : S2 "
    "9월 23일(수) PM9:00~ 추석맞이 수요소셜파티 워크샵 : PM8:00~9:00 백호 & 몽 "
    "살사 샤인 & 패턴 나의 춤에 스타일을 더하다 DJ 헤이즐 음악비율 S4 : B2 "
    "9월 24일(목) 강턴휴무 "
    "9월 25일(금) PM9:00~ 추석맞이금요소셜파티 워크샵 : PM8:00~9:00 끌루이 & 달라's "
    "살사 샤인 & 패턴 움직임이 달라지면, 춤이 달라진다 No Show Only Social "
    "DJ 린넨 음악비율 : S4 : B2 "
    "9월 26일(토) PM9:00~ 추석맞이토요소셜파티 워크샵 : P.M8:00~9:00 백호 & 몽 's "
    "살사샤인 & 패턴 디테일이 만드는 춤의 차이 No Show Only Social "
    "DJ 헤이즐 음악비율 : S4 : B2 "
    "9월 27일(일) PM9:00~ 월간 무차살사:소셜 추석맞이 특별한 파티 ",
)


def test_item_3734_every_program_of_the_서울살사위크_run_is_at_강턴():
    """The one Event that was still upcoming when this release was chosen.
    The post's last line even says so: "워크샵 장소는 모두 강턴입니다".
    """
    title, body = ITEM_3734
    assert extraction_rules.payload_place_field(body) == "강턴"
    got = _venues(extract_schedule(title, body, event_type=SOCIAL))
    assert got == {
        "2026-10-01": "강턴", "2026-10-02": "강턴", "2026-10-03": "강턴",
    }


def test_item_3766_the_보니따_run_keeps_its_own_day_and_fills_the_rest():
    title, body = ITEM_3766
    assert extraction_rules.payload_place_field(body) == "보니따"
    got = _venues(extract_schedule(title, body, event_type=SOCIAL))
    assert got == {
        "2026-09-24": "보니따", "2026-09-25": "보니따",
        "2026-09-26": "보니따", "2026-09-27": "보니따",
    }


def test_item_3792_all_four_dated_programs_are_at_강턴():
    title, body = ITEM_3792
    assert extraction_rules.payload_place_field(body) == "강턴"
    got = extract_schedule(title, body, event_type=SOCIAL)
    assert _venues(got) == {
        "2026-09-23": "강턴", "2026-09-25": "강턴",
        "2026-09-26": "강턴", "2026-09-27": "강턴",
    }
    assert {c.start_time for c in got} == {"21:00"}, "the hours must not move"


# --- nothing but the venue may move ---------------------------------------

def test_inheritance_moves_no_other_field():
    title, body = ITEM_3792
    got = extract_schedule(title, body, event_type=SOCIAL)
    assert [(c.date, c.start_time, c.end_time, c.fee, c.event_type) for c in got] == [
        ("2026-09-23", "21:00", None, None, SOCIAL),
        ("2026-09-25", "21:00", None, None, SOCIAL),
        ("2026-09-26", "21:00", None, None, SOCIAL),
        ("2026-09-27", "21:00", None, None, SOCIAL),
    ]


def test_inheritance_changes_no_candidate_count():
    """Whether a post expands at all is decided before any place is carried."""
    title, body = ITEM_3734
    assert len(extract_schedule(title, body, event_type=SOCIAL)) == 3


# --- v0.96.29's own reader is reused, not re-implemented -------------------

def test_the_schedule_route_and_extract_venue_read_the_same_field():
    body = _payload(
        ["2026-10-01", "2026-10-02"], "PM 9:00~", "라소클", None,
        "10월 1일(목) PM9:00~ 목요소셜파티 10월 2일(금) PM9:00~ 금요소셜파티",
    )
    whole = extraction_rules.extract_venue(body)
    shared = extraction_rules.payload_place_reading(body)
    assert whole is not None and shared is not None
    assert (whole.name, whole.label, whole.raw) == (shared.name, shared.label, shared.raw)
    assert whole.alias_candidates == shared.alias_candidates
