"""Time, venue and fee reading rules (Information Engine v0.74).

Every string here reproduces a *form* seen in a real collected post. None of
them is a stored copy of a post: no phone numbers, no account numbers, no full
bodies. The form is what the rule has to survive; the rest is someone's data.

The case this file exists for is the first one.
"""

import pytest

from src import extraction_rules as rules
from src.extractor import extract_single


# --- PHASE A: time ----------------------------------------------------------

@pytest.mark.parametrize("text,start,end,offset", [
    # The v0.76 defect: the marker sits before the clock and was ignored.
    ("시간: PM 07:30~11:30", "19:30", "23:30", 0),
    ("PM 7:30~12:00", "19:30", "00:00", 1),
    ("Pm5:30~9:30", "17:30", "21:30", 0),
    ("pm5:30~9:30", "17:30", "21:30", 0),
    # Marker after the clock, on one end or both.
    ("6:30-10:30pm", "18:30", "22:30", 0),
    ("7pm~10:30pm", "19:00", "22:30", 0),
    ("09:00 pm to 02:00 am", "21:00", "02:00", 1),
    ("8:00PM-12:00AM", "20:00", "00:00", 1),
    # Korean markers and Korean clocks, including an en dash separator.
    ("시간 : 오후 7시 ~ 11시", "19:00", "23:00", 0),
    ("시간 : 오후6시 - 10시", "18:00", "22:00", 0),
    ("시간: PM 8시 – 12시", "20:00", "00:00", 1),
    ("오전 10시 ~ 오후 1시", "10:00", "13:00", 0),
])
def test_explicit_meridiem_is_applied(text, start, end, offset):
    reading = rules.parse_time_range(text)
    assert (reading.start, reading.end, reading.end_day_offset) == (start, end, offset)
    assert reading.meridiem_evidence == rules.EVIDENCE_EXPLICIT
    assert reading.ambiguous is False


@pytest.mark.parametrize("text,start,end", [
    ("7:30 ~ 11:30", "07:30", "11:30"),
    ("9/12(토)5시30~9시30", "05:30", "09:30"),
])
def test_without_a_marker_the_clock_is_left_alone(text, start, end):
    """A dance event is not evidence that 7:30 means 19:30.

    The reading stays as written and is reported as ambiguous so a person
    decides. Guessing here would trade one wrong value for another.
    """
    reading = rules.parse_time_range(text)
    assert (reading.start, reading.end) == (start, end)
    assert reading.meridiem_evidence == rules.EVIDENCE_ABSENT
    assert reading.ambiguous is True


@pytest.mark.parametrize("text,start,end,offset", [
    ("23:30 – 04:30", "23:30", "04:30", 1),   # crossing midnight is not an error
    ("19:00–23:00", "19:00", "23:00", 0),
    ("20:00 ~ 00:30", "20:00", "00:30", 1),
])
def test_twenty_four_hour_clocks_pass_through(text, start, end, offset):
    reading = rules.parse_time_range(text)
    assert (reading.start, reading.end, reading.end_day_offset) == (start, end, offset)
    assert reading.meridiem_evidence == rules.EVIDENCE_ABSENT
    assert reading.ambiguous is False


@pytest.mark.parametrize("text,expected", [
    ("밤 11시 ~ 3시", ("23:00", "03:00")),      # 밤 means evening at 11
    ("밤 12시 ~ 4시", ("12:00", "04:00")),      # 밤 12시 is not 12 PM: no assertion
    ("저녁 7시 - 11시", ("19:00", "23:00")),
    ("새벽 1시~5시", ("01:00", "05:00")),
    ("낮 12시-4시", ("12:00", "16:00")),
])
def test_korean_time_of_day_words_only_apply_where_they_are_unambiguous(text, expected):
    reading = rules.parse_time_range(text)
    assert (reading.start, reading.end) == expected


@pytest.mark.parametrize("text", [
    "심야 밀롱가 패키지 23:30 – 04:30 사전결제 20,000원",
    "7:30-8:45pm 지노&유니 특강",
    "워크샵 2:00-4:00pm",
])
def test_another_programmes_hours_are_not_the_events_hours(text):
    """A class before the milonga and a paid late-night package after it both
    carry clock ranges. Reading either as the event's own hours is the same
    class of error as reading PM as AM."""
    assert rules.parse_time_range(text) is None


def test_the_events_own_range_is_still_found_alongside_another_programme():
    text = ('8월 22일 토요일 7:30-8:45pm 지노&유니 특강 "밀롱게로스의 비밀"(올레벨) '
            '9pm-1am 밀롱가 헨떼 아미가')
    reading = rules.parse_time_range(text)
    assert (reading.start, reading.end, reading.end_day_offset) == ("21:00", "01:00", 1)


def test_no_range_means_no_time():
    assert rules.parse_time_range("입장료 13,000원 10시 이후 입장") is None
    assert rules.parse_time_range("이번 일요일에 만나요") is None


def test_when_no_reading_names_the_event_type_an_explicit_marker_wins():
    """danceinfo.net's own shape (v0.82): the same event's time is repeated
    once plainly in a structured summary line and once with an explicit
    AM/PM marker in the free-text body, neither one near the event-type
    word. The plain repetition earlier in the text is exactly the reading
    ambiguous=True exists to warn about - it must not win just for being
    first, once a confirmed reading of the same event exists."""
    text = "일정정보 5:30~9:30 장소 분당 실루엣 파티안내 Pm5:30~9:30 예매15,000원"
    reading = rules.parse_time_range(text)
    assert (reading.start, reading.end) == ("17:30", "21:30")
    assert reading.meridiem_evidence == rules.EVIDENCE_EXPLICIT
    assert reading.ambiguous is False


def test_when_every_reading_is_ambiguous_the_first_one_is_still_used():
    """No confirmed reading to prefer: falls back to position, same as
    before this release - never silently drops a time just because it
    cannot be confirmed."""
    text = "1부 5:30~9:30 2부 10:00~11:00"
    reading = rules.parse_time_range(text)
    assert (reading.start, reading.end) == ("05:30", "09:30")
    assert reading.ambiguous is True


# --- PHASE B: venue ---------------------------------------------------------

@pytest.mark.parametrize("text,name", [
    ("장소: 아미고스튜디오 DJ : 로띠", "아미고스튜디오"),
    ("Venue : Tango Andante 🔸️Reservation", "Tango Andante"),
    ("장소 : #데땅고 🌊 ♦︎ 오거나이저: TANGO RnD", "데땅고"),
    ("📍 장소: 홍대 PISTA 서울 마포구 월드컵북로6길 49 B1", "홍대 PISTA"),
    ("Location: Club Troilo", "Club Troilo"),
])
def test_labelled_venue_is_read_and_trimmed(text, name):
    assert rules.extract_venue(text).name == name


@pytest.mark.parametrize("text,name", [
    # A bracketed address belongs to the venue; a following one does not.
    ("장소: 라 벤따나 (서울 마포구 잔다리로 48, 2층) 맛있는",
     "라 벤따나 (서울 마포구 잔다리로 48, 2층)"),
    ("장소 : 엔빠스(EnPaz Tango Studio) 서울특별시 서초구 반포대로30길 82",
     "엔빠스(EnPaz Tango Studio)"),
    ("장소: 엔빠스(EnPaz Tango Studio) [ 테이블 예약 문의 ]",
     "엔빠스(EnPaz Tango Studio)"),
])
def test_venue_stops_where_the_address_or_next_field_begins(text, name):
    assert rules.extract_venue(text).name == name


@pytest.mark.parametrize("text", [
    "위치와 카프레제 파스타, 그리고 DJ 웅이님의 음악과 함께",   # 위치 as an ordinary word
    "위치 🕗 시간: PM 8시 – 12시 🎧 DJ: 웅이",              # a label with no value
    "강남 교대역 '엔빠스' 밀롱가 안내입니다",                   # named but not labelled
])
def test_a_label_needs_a_colon_and_a_value(text):
    """Without this rule the false-positive rate is worse than the 1-in-15 we
    started from: 위치와 … reads as a venue called 와 카프레제 파스타."""
    assert rules.extract_venue(text) is None


def test_alias_candidates_expose_the_parts_worth_matching():
    reading = rules.extract_venue("장소: 엔빠스(EnPaz Tango Studio) 서울특별시")
    assert reading.alias_candidates == [
        "엔빠스(EnPaz Tango Studio)", "엔빠스", "EnPaz Tango Studio",
    ]


def test_extraction_does_not_resolve_or_register_a_venue():
    """Reading the string is all this layer does. Deciding that 아미고스튜디오
    is a known venue -- or creating it -- is a separate, supervised step."""
    reading = rules.extract_venue("장소: 아미고스튜디오")
    assert not hasattr(reading, "venue_id")
    assert set(vars(reading)) == {"name", "raw", "label", "alias_candidates"}


# --- PHASE C: fee -----------------------------------------------------------

@pytest.mark.parametrize("text,amount,basis", [
    ("💰 입장료 13,000원", 13000, rules.BASIS_LABEL),
    ("참가비 15000원", 15000, rules.BASIS_LABEL),
    ("낭만게릴라 fee 10000 탱친 여러분", 10000, rules.BASIS_LABEL),
    ("우서빌딩 지하 1층 밀롱가 : 13,000원", 13000, rules.BASIS_EVENT_CONTEXT),
    ("예매: 특강+밀롱가 38000원, 특강만 30000원, 밀롱가만 13000원",
     13000, rules.BASIS_EVENT_CONTEXT),
])
def test_fee_is_read_from_a_label_or_from_the_events_own_name(text, amount, basis):
    reading = rules.extract_fee(text, "MILONGA")
    assert (reading.amount, reading.basis) == (amount, basis)


@pytest.mark.parametrize("text", [
    "국채보상공원 공영주차장 추천(1일 최대 7,000원) 큰길 건너",  # parking
    "더 피스타 밀롱가 참여자 심야 밀롱가 3,000원 할인",          # a discount
    "심야 밀롱가 패키지 사전결제 20,000원",                    # a separate package
    "특강만 30000원",                                       # a class
    "1.3 정도 생각하세요",                                   # not a price at all
    "입장료 1만원",                                          # not a digit amount
    "문의 010-1234-5678",                                   # a phone number
])
def test_money_that_is_not_this_events_fee_is_left_alone(text):
    assert rules.extract_fee(text, "MILONGA") is None


def test_a_discount_further_down_the_post_does_not_kill_the_entry_fee():
    """Judged near each amount, not across the whole segment. One real post
    carries 입장료 13,000원 and, sentences later, 심야 밀롱가 3,000원 할인."""
    text = ("주전부리 💰 입장료 13,000원 🎟 10시 이후 입장 시 무료 입장권 1장 제공 "
            "🌙 심야 밀롱가 패키지 23:30 – 04:30 사전결제 20,000원 "
            "👉 참여자 심야 밀롱가 3,000원 할인")
    reading = rules.extract_fee(text, "MILONGA")
    assert (reading.amount, reading.basis) == (13000, rules.BASIS_LABEL)


def test_an_unlabelled_number_never_becomes_a_fee():
    """The engine grants VERIFIED partly on a fee being present. An invented
    fee is how a candidate passes that gate on evidence nobody has."""
    assert rules.extract_fee("밀롱가 23:30 시작 우서빌딩 지하 1층", "MILONGA") is None
    assert rules.extract_fee("밀롱가 2026", "MILONGA") is None


# --- the whole post ---------------------------------------------------------

def test_the_post_that_defined_this_release():
    """v0.73 read this as 07:30-11:30, no venue, no fee."""
    candidate = extract_single(
        "밀롱가 안내",
        "9월 5일 토요일 시간: PM 07:30~11:30 장소: 아미고스튜디오 DJ : 로띠 입장료 13,000원",
        published="2026-09-01",
    )
    assert candidate.date == "2026-09-05"
    assert (candidate.start_time, candidate.end_time) == ("19:30", "23:30")
    assert candidate.end_day_offset == 0
    assert candidate.venue == "아미고스튜디오"
    assert candidate.fee == 13000
    time_evidence = next(e for e in candidate.evidences if e.field == "time")
    assert time_evidence.inference == rules.EVIDENCE_EXPLICIT
    assert "PM 07:30~11:30" in time_evidence.raw_text
