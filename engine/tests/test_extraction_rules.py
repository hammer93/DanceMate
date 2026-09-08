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


# --- v0.82.5: consecutive parenthetical groups (bilingual name + address) --
#
# Found live: Miltang's own bilingual-name rendering ("Brand 한글이름" ->
# "Brand (한글이름)", v0.82.1's _split_bilingual_venue_name()) followed by a
# real street address reads as two adjacent parenthetical groups -
# "PosTango (포스탱고) (포항시 남구 중앙로 83, 3층)" - which the boundary
# rule used to read as "Name (alias)", then prose, silently dropping the
# address. The dropped text is also the only thing in the body naming the
# venue's actual region (see runtime.venue_resolution.guess_region_label()),
# so this alone made Pohang and Daegu's real, correctly-classified events
# fall back to "지역 미확인" even once classification (test_social_dance.py)
# was fixed.

@pytest.mark.parametrize("text,name", [
    ("장소: PosTango (포스탱고) (포항시 남구 중앙로 83, 3층 프스탱고) 반복: 매주 금요일",
     "PosTango (포스탱고) (포항시 남구 중앙로 83, 3층 프스탱고)"),
    ("장소: Tango Cafe Dia (탱고 카페 디아) (대구 북구 침산로 168 5층 507호) 주최: DoyaDoya",
     "Tango Cafe Dia (탱고 카페 디아) (대구 북구 침산로 168 5층 507호)"),
    # Two groups where the second is not an address at all (Ulsan's own real
    # body: the English name repeated in Korean, twice) - still both belong
    # to the venue, same rule, no address-shape check needed to get this
    # right.
    ("장소: Ulsan Tango Sociedad (울산탱고) (Ulsan Tango Sociedad 울산탱고) 주최: 울산탱고",
     "Ulsan Tango Sociedad (울산탱고) (Ulsan Tango Sociedad 울산탱고)"),
])
def test_consecutive_parenthetical_groups_both_belong_to_the_venue(text, name):
    assert rules.extract_venue(text).name == name


def test_a_bracket_after_one_group_still_ends_the_venue():
    """Unchanged from before this release: a group followed by something
    that is not another group is prose, exactly as
    test_venue_stops_where_the_address_or_next_field_begins already checks -
    this just pins the case where a real address-shaped second group is
    absent, so there is nothing for the new lookahead to find."""
    reading = rules.extract_venue("장소: 엔빠스(EnPaz Tango Studio) [ 테이블 예약 문의 ]")
    assert reading.name == "엔빠스(EnPaz Tango Studio)"


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


# --- v0.84.1: Korean 만원 notation, free admission, package-tier safety -----
#
# Found live: real Miltang/DanceInfo/TangoNOW posts fee-unknown in production
# (Section 5/6 of the v0.84.1 task) whose actual coverage gap turned out to be
# near-zero once every case was read - almost all of them (SOURCE_HAS_NO_FEE)
# genuinely never mention a price at all, because Miltang and TangoNOW are
# discovery directories, not the event's own page. These fixtures are the
# real shapes this release DOES improve: Korean 10,000-unit notation the
# parser could not read at all before, free admission (never recognised
# before this release, at any amount), and a real live post's own multi-tier
# package price ("10만원(2달, 8회), 6만원(1달, 4회), 당일 현장 2만원(1회)")
# that a naive 만원 reader would otherwise have wrongly attached to a single
# practica session as if it were that day's cover charge.

@pytest.mark.parametrize("text,amount,basis", [
    ("입장료 1만원", 10000, rules.BASIS_LABEL),
    ("참가비 2만원입니다", 20000, rules.BASIS_LABEL),
    ("회비 1.5만원", 15000, rules.BASIS_LABEL),
    ("밀롱가 : 2만원", 20000, rules.BASIS_EVENT_CONTEXT),
])
def test_korean_man_notation_is_read_as_ten_thousand_won(text, amount, basis):
    reading = rules.extract_fee(text, "MILONGA")
    assert (reading.amount, reading.basis) == (amount, basis)


@pytest.mark.parametrize("text", [
    "입장 무료",
    "무료 입장",
    "참가비 없음",
    "참가비: 무료",
    "입장료 무료",
    "Free admission",
    "free entry",
])
def test_free_admission_is_read_as_zero_won(text):
    reading = rules.extract_fee(text, "MILONGA")
    assert reading is not None
    assert reading.amount == 0


@pytest.mark.parametrize("text", [
    "행사장 무료주차 가능",           # parking, not admission
    "무료 음료 제공",                 # a drink, not admission
    "무료 셔틀버스 운행",             # a shuttle, not admission
])
def test_free_something_else_is_never_read_as_a_free_event(text):
    """Section 21/34: 'free parking' making the event itself read as free
    would be exactly the false VERIFIED risk this whole module exists to
    refuse."""
    assert rules.extract_fee(text, "MILONGA") is None


@pytest.mark.parametrize("text", [
    "무료주차 가능 입장료 13,000원",
    "입장료 13,000원 무료주차 가능",
    "무료 주차 가능 입장료 13,000원",
])
def test_a_nearby_free_parking_mention_does_not_suppress_the_real_fee(text):
    """v0.84.3 (found via a real K-TANGO-shaped poster): '주차' correctly
    disqualifies a parking fee ('주차장 최대 7,000원'), but '무료주차' is a
    bare fact with no amount of its own - it must not also blank out a
    genuine, clearly-labelled entry fee that just happens to sit nearby."""
    reading = rules.extract_fee(text, "MILONGA")
    assert reading is not None
    assert reading.amount == 13000


@pytest.mark.parametrize("text", [
    "주차장 추천(1일 최대 7,000원)",
    "주차비 3,000원",
])
def test_a_genuine_parking_fee_is_still_excluded(text):
    """Non-regression: the fix above narrows the exclusion to '무료주차'
    specifically - an actual parking price must still never be read as the
    event's own admission fee."""
    assert rules.extract_fee(text, "MILONGA") is None


def test_a_real_multi_tier_package_price_is_left_unpriced():
    """Real live post (a recurring guided practica): three genuine prices for
    three different commitments. Picking any one of them - even the
    single-visit walk-in tier - would still be choosing among three numbers
    the post itself never singled out as 'today's price' (Section 17/20)."""
    text = ("💰 참가비: 10만원(2달, 8회), 6만원(1달, 4회), "
            "당일 현장 2만원(1회) 상시 등록 가능")
    assert rules.extract_fee(text, "PRACTICA") is None


def test_advance_and_door_pricing_is_preserved_not_averaged_or_first():
    """Real live post (DanceInfo): '예매15,000/현매20,000' is two genuine
    prices for the same event. v0.84.1 refused to collapse them to one
    number and left the event unpriced entirely - honest, but Section 14 of
    v0.85.9 asks for better: 예매/현매 name a purchase channel exactly the
    way an explicit fee label names an amount, so both real numbers are
    keepable, and 'unpriced' is no longer the safest available answer once
    they can both be said at once."""
    text = "🎂디제이-네로 🎂예매15,000/현매20,000 🎂카뱅3333-21-5422369"
    reading = rules.extract_fee(text, "MILONGA")
    assert reading is not None
    # No single number is "the" fee - Section 2 forbids picking 15,000,
    # 20,000, or an average of the two.
    assert reading.amount is None
    assert reading.display == "예매 15,000원 · 현매 20,000원"


def test_member_and_non_member_pricing_is_preserved():
    """Same upgrade as advance/door pricing above, for 회원/비회원 (Section
    15): both real prices kept, neither silently dropped."""
    text = "회원 15,000원 / 비회원 20,000원"
    reading = rules.extract_fee(text, "MILONGA")
    assert reading is not None
    assert reading.amount is None
    assert reading.display == "회원 15,000원 · 비회원 20,000원"


def test_a_street_address_number_is_never_read_as_a_fee():
    """장소: 서울 마포구 잔다리로 48, 2층 - "48" is a building number, not a
    price, and gets nowhere near _MIN_UNSUFFIXED_DIGITS on its own; the real
    risk is a longer lot/building number reading as money once it is 4+
    digits, so this pins a realistic one."""
    assert rules.extract_fee(
        "장소: 서울 서초구 주흥길 1234 환희빌딩 2층", "MILONGA"
    ) is None


def test_extract_fee_has_no_memory_between_calls():
    """Section 27 (v0.84.1): recurrence must never carry a fee from one
    occurrence to the next. extract_fee() takes no state beyond the text
    handed to it for this exact reason - calling it once with a real fee
    must not leak into a later call for a different occurrence's text."""
    priced = rules.extract_fee("입장료 13,000원", "MILONGA")
    assert priced is not None
    unpriced = rules.extract_fee("밀롱가 23:30 시작", "MILONGA")
    assert unpriced is None


# --- v0.85.9: Korean 천원 notation, conditional fee display -----------------
#
# Found live: a real recurring milonga ("화정") whose weekly post has read
# 20:00-23:30 correctly for six straight weeks (parse_time_range already
# handled "오후 8시 ~ 11시 30분" before this release - untouched here) while
# its fee read unknown every single week, because "8천원" used a notation
# extract_fee() had no pattern for at all. The real root cause was a missing
# pattern, not an over-eager safety net discarding a successful read.

@pytest.mark.parametrize("text,amount,basis", [
    ("입장료 : 8천원", 8000, rules.BASIS_LABEL),
    ("참가비 5천원", 5000, rules.BASIS_LABEL),
    ("회비 1.5천원", 1500, rules.BASIS_LABEL),
    ("밀롱가 : 3천원", 3000, rules.BASIS_EVENT_CONTEXT),
])
def test_korean_cheon_notation_is_read_as_one_thousand_won(text, amount, basis):
    reading = rules.extract_fee(text, "MILONGA")
    assert (reading.amount, reading.basis) == (amount, basis)


@pytest.mark.parametrize("text", [
    "참가자 8천명 예상",   # a headcount, not money
    "이번이 8천번째 모임",  # an ordinal, not money
])
def test_bare_cheon_without_a_label_is_never_read_as_money(text):
    """Section 21: '8천' with no 원 is only money once a label says so
    (mirroring the existing unsuffixed-digit rule) - a headcount or an
    ordinal must never qualify just because a number precedes '천'."""
    assert rules.extract_fee(text, "MILONGA") is None


def test_bare_cheon_with_a_label_and_no_won_is_still_read_as_money():
    """Section 20: '8천' with no 원 suffix at all is real money once a fee
    label names it - the 천 marker itself is enough signal, unlike a plain
    digit run which still needs 4+ digits before a label is trusted."""
    reading = rules.extract_fee("입장료 8천", "MILONGA")
    assert reading is not None
    assert reading.amount == 8000


def test_conditional_fee_keeps_both_the_base_and_the_condition():
    """The exact real shape (Section 11-13): a base price plus a time-gated
    discount, immediately parenthesised after it. Both numbers are kept -
    never reduced to 8,000 alone (losing the discount) nor to unknown
    (losing a fee that is, in fact, fully known)."""
    reading = rules.extract_fee(
        "입장료 : 8천원 (10시 이후 5천원)", "MILONGA",
        known_start="20:00", known_end="23:30",
    )
    assert reading is not None
    assert reading.amount == 8000
    assert reading.display == "8,000원 (22시 이후 5,000원)"


def test_conditional_fee_hour_is_never_guessed_without_an_anchor():
    """Section 2: 오후/오전 시간 추측 금지. Without the event's own already-
    EXPLICIT start/end to anchor against, the condition's bare hour is kept
    exactly as written rather than invented as either AM or PM."""
    reading = rules.extract_fee("입장료 : 8천원 (10시 이후 5천원)", "MILONGA")
    assert reading is not None
    assert reading.amount == 8000
    assert reading.display == "8,000원 (10시 이후 5,000원)"


def test_conditional_fee_hour_is_not_resolved_when_it_cannot_fit_the_window():
    """A condition hour whose *both* 12-hour readings sit outside the
    event's own window is exactly as unresolved as having no window at all
    - Section 23's anchor only fires when it points to a single, sensible
    answer, never as a fallback guess."""
    reading = rules.extract_fee(
        "입장료 : 8천원 (10시 이후 5천원)", "MILONGA",
        known_start="01:00", known_end="02:00",
    )
    assert reading is not None
    assert reading.display == "8,000원 (10시 이후 5,000원)"


def test_fee_condition_time_is_never_confused_with_event_end_time():
    """Section 22/23 (very important): '10시 이후' inside the fee line is a
    fee condition, never a second reading of the event's own end time.
    parse_time_range() must not see it at all - only extract_fee() does."""
    text = "시간 : 오후 8시 ~ 11시 30분 입장료 : 8천원 (10시 이후 5천원)"
    reading = rules.parse_time_range(text, "MILONGA")
    assert (reading.start, reading.end) == ("20:00", "23:30")


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


def test_the_solo_tango_hwajeong_post_that_defined_v0_85_9():
    """The real production post this release exists for (v0.85.9, Section
    38) - SRC-D-003's own weekly 화정 announcement, post_id 606, captured
    verbatim from the engine's own raw_posts.body. Every week since this
    event started recurring, start/end read correctly (20:00-23:30, already
    handled before this release) while the fee read unknown, because '8천원'
    used a notation extract_fee() had no pattern for. '화정지기'/'화정도우미'
    (volunteer-role labels specific to this event) and the raffle mention
    must not leak into DJ/venue/fee/date, and the fee condition's '10시' must
    resolve to 22:00 by anchoring against this same post's own EXPLICIT
    20:00-23:30 window - never a blanket AM/PM guess."""
    candidate = extract_single(
        "[화정] 9월 8일 화정 공지 (DJ : 유진)",
        "SINCE 2000 화정 밀롱가에서 DJ 유진의 음악을 즐기며 화정에서 만날수 있는 "
        "탱고인들과의 교류를 즐겁게 만들어 볼까요~ 이번 화정은 빵 or 떡을 준비해 "
        "보겠습니다. 그리고 화정티켓 두장은 번호표 뽑기로 진행합니다^^ 뽑기하기전 "
        "귀가하신분은 뽑혀도 탈~~~락!! 날짜 : 9월 8일 화요일 시간 : 오후 8시 ~ 11시 "
        "30분 디제이 : 유진 장소 : Tango O nada 화정지기 : 에리카 이어링투 루나 "
        "화정도우미 : 라벤더,냥이,나빌레라 입장료 : 8천원 (10시 이후 5천원) "
        "이벤트 번호표 뽑기 진행 ❤️ 예약문의 : 댓글을 활용해 주세요 ❤️ 🎉 화정 "
        "생일빵 🎉 화정에서 생일빵을 진행합니다. 테이블 예약시 카페에 신청해 "
        "주세요. 솔땅 회원분들 그리고 품앗이님들 생일이나 벙개는 화정에서~!! 모두 "
        "함께 축하하고, 즐거운 밤이 되길 바래요~ ♡ 우리 모두의 화정을 위한 약속 "
        "세가지 ♡ ☞ 까베 매너 : 무례한 까베로 블랙리스트에 오르지 않도록 주의하기! "
        "☞ 론다 매너 : 음악이 흐른 후 론다에 입장하시고, 꼬르띠나가 시작되면 "
        "론다에서 나오기! ☞ 개인 위생 : 철저한 개인위생으로 사랑스런 파트너 지켜주기!",
        published="2026-09-06",
    )
    assert candidate.date == "2026-09-08"
    assert (candidate.start_time, candidate.end_time) == ("20:00", "23:30")
    assert candidate.dj == "유진"
    assert candidate.venue == "Tango O nada"
    assert candidate.fee == 8000
    assert candidate.fee_display_text == "8,000원 (22시 이후 5,000원)"
