"""v0.96.27: a marked range whose first clock is a bare hour.

Four Production Events advertised an hour the post does not state:

    [화정] 정글밀롱가        "시간: pm 8~11:30"          stored 11:30
    안산 라소클 1토 파티!     "20시~06시" + "2부24시~06시"  stored 00:00
    위드라틴 살사 초중급      "저녁 9시" x2 + "10시부터"    stored 10:00
    살사 준중급             "뉴욕바 소셜 9:00 ~ 00:00"    stored 09:00

The brief that opened v0.96.27 named the first of these: ``11:30`` is not when
that milonga begins, it is when it **ends**. ``_CLOCK``'s bare-hour form
required the meridiem marker to follow the digits (``7pm``), and Production
writes it in front at least as often (``pm 8``, ``오후 8``, ``밤 10``), so
``_RANGE_RE`` found no range at all in ``pm 8~11:30`` - and the lone-clock rule
took the only clock left, the range's end.

Each of the other three is the same sentence read a different way: the post
states its evening hour and a weaker reading won. A numbered later set's clock
(``2부24시~06시``) beat the night's own; an unmarked ``10시부터`` beat an
explicit ``저녁 9시`` because it sat nearer the word 소셜; and an unmarked
``9:00`` was read as morning although the ``00:00`` it runs to can only be
midnight.

Nothing here promotes an hour to the evening for being a dance. The negative
fixtures below are the measured cost of each rule: every daytime range in the
stored corpus, the fee and headcount ranges a widened grammar would otherwise
swallow, and the shapes v0.96.18/19 already settled.
"""

from __future__ import annotations

import pytest

from src import extraction_rules


def _range(text: str, event_type: str | None = None):
    r = extraction_rules.parse_time_range(text, event_type)
    return None if r is None else (r.start, r.end)


def _start(text: str, event_type: str | None = None):
    s = extraction_rules.parse_start_time(text, event_type)
    return None if s is None else s.start


def _time(text: str, event_type: str | None = None):
    """What the extractor stores: the range, else the lone start."""
    r = extraction_rules.parse_time_range(text, event_type)
    return r if r is not None else extraction_rules.parse_start_time(text, event_type)


# --- the four Production cases ----------------------------------------------

def test_화정_pm_8_to_1130_is_a_range_not_a_1130_start():
    """item 4443, weekly. The defect that opened this release."""
    body = ("날짜: 9월 29일 화요일 시간: pm 8~11:30 DJ : 에이브 "
            "장소: Tango O nada Fee : 8,000원 (10시~ 5,000원)")
    assert _range(body, "MILONGA") == ("20:00", "23:30")
    assert _start(body, "MILONGA") is None, "a range is read by parse_time_range"
    reading = _time(body, "MILONGA")
    assert reading.meridiem_evidence == extraction_rules.EVIDENCE_EXPLICIT
    assert reading.ambiguous is False


def test_안산_a_numbered_later_set_does_not_own_the_nights_start():
    """item 4496. "2부24시~06시" sits two characters before the word 파티, so
    proximity handed it the night; the night's own line says 20시~06시."""
    body = ("-CRAZY MAX: ALL NIGHT 🚨20시~06시까지 썬업 진행!! 다른 도시에서 파티 "
            "참석 대환영! ⏰ 타임테이블 20~21시: 로건&BK 바차타 파트너십 오픈강습 "
            "21시~: 스페셜 DJ MAX 소셜 타임! 1부(바차타3 살사2)🎶 2부24시~06시 "
            "라틴펍&파티룸 음비 DJ마음대로!)")
    assert _range(body, "SOCIAL_WITH_CLASS") == ("20:00", "06:00")


def test_위드라틴_an_unmarked_morning_does_not_outrank_an_explicit_evening():
    """item 2267. 소셜 sits beside the unmarked "10시부터"; 저녁 9시 does not."""
    body = ("일정정보 매주 목요일 저녁 9시 장소 뉴욕바 강의 소개 그날 배워 그날추는 "
            "쉬운 살사 CBL부터 전혜다른 진짜 On2 절대 모르면 안되는 초중급 패턴 "
            "매주 목요일 저녁 9시 강남역 뉴욕바에서 진행됩니다. 참여 조건: 살사 "
            "3개월 이상 초중급 레벨 소셜은 10시부터 라틴바로 이동합니다.")
    assert _start(body, "SOCIAL_WITH_CLASS") == "21:00"
    assert _time(body, "SOCIAL_WITH_CLASS").meridiem_evidence == \
        extraction_rules.EVIDENCE_EXPLICIT


def test_살사준중급_a_range_running_to_midnight_did_not_start_in_the_morning():
    """item 2802. 00:00 has one meaning, so the 9:00 before it has one too."""
    body = ("일정정보 매주 토요일, 4주 (추석 휴강) 7:00 ~ 7:50 PM 장소 강남 봄바람 "
            "연습실 강의 소개 베이직과 바디무브먼트 정교화 대상: 초중급 이수하신 "
            "분들 컴온! 뉴욕바 소셜 9:00 ~ 00:00 신청은 이쪽에서!")
    assert _range(body, "SOCIAL_WITH_CLASS") == ("21:00", "00:00")
    assert _time(body, "SOCIAL_WITH_CLASS").meridiem_evidence == \
        extraction_rules.EVIDENCE_PROPAGATED


# --- the bare-hour grammar, exactly the shapes the corpus writes -------------

@pytest.mark.parametrize("text, expected", [
    ("시간: pm 8~11:30", ("20:00", "23:30")),
    ("시간: PM 8-11:30", ("20:00", "23:30")),
    ("시간: 오후 8~11:30", ("20:00", "23:30")),
    ("일정정보 4주 화요일 오후 8~9시30분", ("20:00", "21:30")),      # item 2236
    ("오후 8~9시", ("20:00", "21:00")),                          # item 3858
    ("최종 리허설 : 밤 10~12시 (솔땅)", ("22:00", "00:00")),          # item 2032
    ("2026.08.21 & / PM 8~12", ("20:00", "00:00")),             # item 12
    ("화요일 10월 27 (PM 8-10 /수원)", ("20:00", "22:00")),         # item 4451
    ("일정정보 PM8~9 장소 제이엔터", ("20:00", "21:00")),              # item 4436
    ("매주 토요일 4주 PM 5~6:30", ("17:00", "18:30")),              # item 2248
    ("오후 3~4시 장소 로건BK", ("15:00", "16:00")),                  # item 3620
    ("7월 4일(토) 오후 1~3시 (솔땅)", ("13:00", "15:00")),            # item 2041
])
def test_a_marked_bare_hour_head_is_read_as_a_range(text, expected):
    assert _range(text) == expected


@pytest.mark.parametrize("text", [
    "시간: pm 8:00~11:30",
    "시간: pm 8시~11시30분",
    "시간: PM 07:30~11:30",
    "6:30-10:30pm",
    "PM 8시 – 12시",
])
def test_the_range_forms_that_already_worked_are_untouched(text):
    assert _range(text) is not None


# --- a bare number is only a clock when the range names a half of the day ----

@pytest.mark.parametrize("text", [
    "입장료 8~9만원 예매",
    "선착순 3~4명 모집",
    "시즌 2026~2027 일정",
    "1~2주 과정입니다",
    "9월 8~9일 워크샵",
    "레벨 2~3 대상",
    "8~9 만원",
])
def test_an_unmarked_number_range_is_not_a_clock_range(text):
    assert _range(text) is None
    assert _start(text) is None


def test_a_marker_the_hour_is_outside_does_not_admit_a_bare_range():
    """`밤` means PM only for 6..11 (`_MERIDIEM_WORDS`), so it asserts nothing
    about a 3, and "밤 3~4" stays what it is: not a clock range."""
    assert _range("밤 3~4 인원") is None


@pytest.mark.parametrize("text, before", [
    # The three posts that measured the leading-marker rule. Each would gain a
    # range from a trailing-only marker, and each would gain the wrong one.
    ("일정정보 워크샵(1): 7-8PM, 워크샵(2): 8-9PM, 소셜 모픈: 9PM 장소 보니따", "21:00"),
    ("일정정보 3시간 수업, 1시간 수업 및 리허설 12-3PM, 6-7PM 강의 소개", "19:00"),
    ("주최: 마르코, 제이콥 탱3-발3-밀3-AM3", None),
])
def test_a_trailing_only_marker_does_not_admit_a_bare_hour_head(text, before):
    """item 3824's social opens at 9PM, not when 워크샵(2) runs; item 2256's
    "6-7PM" is a class slot; and 마제밀's "탱3-발3-밀3-AM3" is a music ratio."""
    assert _range(text, "SOCIAL_WITH_CLASS") is None
    assert _start(text, "SOCIAL_WITH_CLASS") == before


def test_a_bare_hour_that_is_part_of_a_date_is_not_a_clock():
    """item 883 writes an application window, not a class: "오전 9시부터
    7.13.(월) 18:00까지 접수 기간". The 7 belongs to July."""
    assert _range("내일(18일) 오전 9시부터 7.13.(월) 18:00까지 접수 기간") is None


@pytest.mark.parametrize("text, event_type, still_reads", [
    # item 4480: 2만 CC of free beer, not two in the morning.
    ("[대박 이벤트] 밤 9시부터 2만 CC가 소진될 때까지 FREE BEER", "SOCIAL", "21:00"),
    # item 3140: a 70-minute class, not a range ending at 70 o'clock.
    ("시간: 매주 수요일 오후8시부터 70분 수업 대상: 땅고 초중급", "CLASS", None),
])
def test_a_bare_hour_is_not_admitted_across_a_particle(text, event_type, still_reads):
    """`부터` and `에서` join clocks, but they are also ordinary particles. These
    are the only two places in the stored corpus where a bare endpoint is reached
    through one, and both are wrong - so the lone-clock reading stands instead."""
    assert _range(text, event_type) is None
    assert _start(text, event_type) == still_reads


def test_a_particle_between_two_real_clocks_still_makes_a_range():
    assert _range("8시부터 11시") == ("08:00", "11:00")
    assert _range("저녁 7시부터 11시까지", "MILONGA") == ("19:00", "23:00")


def test_a_bare_endpoint_naming_no_hour_is_not_a_range_and_masks_nothing():
    """`70` parses as no hour, so the shape is not a range - and it must not
    become a span that hides the clock inside it either."""
    assert _range("오후8시부터 70분") is None
    assert _start("오후 8시부터 70분 진행", "SOCIAL") == "20:00"


def test_an_hour_somebody_is_approximating_is_not_a_schedule():
    """item 3261 is a diary entry. Measured over all 3,237 stored texts, a clock
    carries an approximation word exactly twice, and both are this sentence."""
    body = "아침부터 시작된 격무에 오후 3~4시쯤에 이미 피곤해서 눈이 풀릴정도였는데"
    assert _range(body) is None
    assert _start(body) is None
    assert _start("오후 3시쯤 도착했다") is None


def test_a_range_whose_end_names_no_hour_is_still_a_range():
    """item 3239 writes "21:00-25:00"; no hour 25 exists, so no reading is
    yielded - but the 21:00 is that range's head, not an independent start, and
    the post's own poster supplies the end."""
    assert _range("일정: 9월 21일(토) 21:00-25:00 장소: Tango Mio", "MILONGA") is None
    assert _start("일정: 9월 21일(토) 21:00-25:00 장소: Tango Mio", "MILONGA") is None


def test_a_fee_range_never_masks_a_real_clock():
    """`parse_start_time()` skips clocks that sit inside a range. The widened
    grammar must not let "8~9만원" swallow the night's own hour."""
    assert _start("입장료 8~9만원 · 저녁 9시 시작", "SOCIAL") == "21:00"


# --- midnight and 24:00 semantics, unchanged ---------------------------------

@pytest.mark.parametrize("text, expected", [
    ("시간 24시~06시", ("00:00", "06:00")),
    ("🚨20시~06시까지 썬업 진행!!", ("20:00", "06:00")),
    ("시간 22:00~02:00", ("22:00", "02:00")),
    ("시간 23:30 – 04:30", ("23:30", "04:30")),
    ("PM 8시 – 12시", ("20:00", "00:00")),
])
def test_overnight_semantics_are_unchanged(text, expected):
    assert _range(text) == expected


def test_the_day_offset_of_an_overnight_end_is_still_one():
    r = extraction_rules.parse_time_range("시간 22:00~02:00")
    assert r.end_day_offset == 1
    midnight = extraction_rules.parse_time_range("컴온! 소셜 9:00 ~ 00:00", "SOCIAL")
    assert midnight.end_day_offset == 1


# --- daytime must survive ----------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("시간: 9:00~12:00 장소: X", ("09:00", "12:00")),
    ("2026년 10월 4일 시간: 11:00~14:00", ("11:00", "14:00")),
    ("운영 시간/ 08:00~19:00", ("08:00", "19:00")),
    ("일정정보 매주 일요일 11:00 ~ 13:00, 8주 과정", ("11:00", "13:00")),
    ("일정정보 매주 토요일 8주 11:30-13:00", ("11:30", "13:00")),
    ("오전 10시~12시 연습", ("10:00", "12:00")),
    ("시간: 14:00~16:00", ("14:00", "16:00")),
    ("시간: 15:00~17:00 장소: Tango Life", ("15:00", "17:00")),
    ("2026년 10월 3일 시간: 14:00~18:00", ("14:00", "18:00")),
])
def test_a_daytime_range_is_never_moved_into_the_evening(text, expected):
    assert _range(text) == expected


@pytest.mark.parametrize("text", [
    "시간: 9:00~12:00 장소: X",
    "2026년 10월 4일 시간: 11:00~14:00",
    "운영 시간/ 08:00~19:00",
])
def test_an_unmoved_reading_keeps_the_evidence_it_had(text):
    """Reading backwards from an unambiguous end lands on the hour as written
    for every daytime range in the corpus, and there nothing was learned: the
    reading stays ABSENT and ambiguous, so v0.96.19's guard against admitting a
    guessed morning keeps its meaning."""
    r = extraction_rules.parse_time_range(text)
    assert r.meridiem_evidence == extraction_rules.EVIDENCE_ABSENT
    assert r.ambiguous is True


# --- what earlier releases settled -------------------------------------------

def test_the_babaru_shape_v09618_fixed_is_still_right():
    body = ("워크샵 : 양 & 베키 · PM 7:00~8:00 소셜 시작 : PM 8:00 DJ 린넨 · MC 선녀")
    assert _start(body, "SOCIAL_WITH_CLASS") == "20:00"
    assert _range(body, "SOCIAL_WITH_CLASS") is None


def test_the_first_set_still_owns_the_nights_start():
    """`1부` is deliberately not a later-set label."""
    assert _range("🎧 DOUBLE DJ PARTY 1부 21:00~22:30 DJ ETHAN", "PARTY") \
        == ("21:00", "22:30")


@pytest.mark.parametrize("text, expected", [
    ("🎧 DOUBLE DJ PARTY 1부 21:00~22:30 DJ ETHAN 2부 22:30~24:00 DJ SEAN",
     ("21:00", "22:30")),
    ("PM 9:00 ~ AM 00:00 🎧 1부 9:00~10:30 DJ 에단 🎧 2부 10:30~12:00 DJ 션",
     ("21:00", "00:00")),
    ("1부 5:30~9:30 2부 10:00~11:00", ("05:30", "09:30")),
])
def test_a_later_sets_label_only_speaks_for_the_clock_after_it(text, expected):
    """The label is positional, unlike a class word. Asking it symmetrically made
    "1부 5:30~9:30 2부 10:00~11:00" lose both readings, because the 2부 heading
    the second range fell inside the first range's window."""
    assert _range(text, "PARTY") == expected


def test_a_word_ending_in_부_is_not_a_later_set_label():
    """`2부터` is a particle, not a second set, so the range after it stands."""
    assert _range("신청은 2부터 오후 8~9시 소셜", "SOCIAL") == ("20:00", "21:00")
    assert _range("2부 오후 8~9시 소셜", "SOCIAL") is None


def test_a_class_range_before_the_event_range_still_loses_v09619():
    assert _range("오픈특강 with 샤론y태희 9:00pm-12:30am 밀롱가", "MILONGA") \
        == ("21:00", "00:30")


def test_a_late_night_package_still_keeps_its_own_hours_v09619():
    assert _range("심야밀롱가(11:30 p.m-4:30 a.m) 패키지", "MILONGA") is None


def test_a_workshop_weekend_still_gives_the_social_its_own_range():
    body = ("- 15:00-16:30 발스윙 중고급 - 16:45-18:15 쉐그 초급 "
            "- 20:00-22:30 소셜")
    assert _range(body, "SOCIAL") == ("20:00", "22:30")


def test_a_bare_unmarked_clock_is_still_not_a_start_v0960():
    assert _start("8시 마감") is None
    assert _start("행사 8시") is None


def test_an_explicit_lone_start_is_still_read_v0960():
    assert _start("저녁 7시 30분 시작", "MILONGA") == "19:30"
    assert _start("7:30pm", "MILONGA") == "19:30"
    assert _start("19:30", "MILONGA") == "19:30"


def test_a_marker_less_start_is_still_reported_as_written_v0960():
    """`부터` marks "8시부터" as a start rather than a deadline; it does not say
    which half of the day, and this release does not start guessing."""
    reading = extraction_rules.parse_start_time("8시부터 밀롱가", "MILONGA")
    assert (reading.start, reading.meridiem_evidence, reading.ambiguous) == \
        ("08:00", extraction_rules.EVIDENCE_ABSENT, True)
