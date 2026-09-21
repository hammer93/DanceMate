"""v0.96.4 - the dates a title names and the engine could not read
(Information Engine 0.92).

Measured on Production after v0.96.3 finished re-extracting all 1,179 stored
bodies under engine 0.91, so none of this is a stale-extraction artefact:

* 193 items carry a date in their title. 114 produce a dated candidate.
* Exactly **4** lose the date at the reader, and all four are the same
  written form and the same weekly series - "■ 스윙타임빠 (9월 19,20일) 토,일
  소셜 공지" (items 131, 623, 2113, 2800). A month that names two of its own
  days at once matched no pattern at all: the plain "M월 D일" needs the 일
  directly after its day, and "19,20일" does not have it; the bare "m/d"
  fallback needs a "." or "/" separator.
* The remaining 75 are refused by the *classifier*, not the date reader -
  a separate bottleneck this release deliberately does not touch (see the
  release report; most are genuinely lesson adverts, recaps and notices).

Giving that post a date exposed a second, real defect in the same item, which
this release therefore also fixes: its candidate took 09:00-10:30 - a morning
clock on an evening social - because the *streaming notice's* own section
heading ("■ 타임빠소셜 실시간 스트리밍") sat within sixteen characters of the
2부 set's marker-less clock and so qualified it as the social's own. The
window a word may qualify a clock through now stops at a structural break,
exactly as the window that *disqualifies* one already did.

Nothing here relaxes an existing refusal: a bare weekday, an unresolvable
year, a lesson advert and a season-ticket notice all behave exactly as
before.
"""

from datetime import date

import pytest

from src import extraction_rules as rules
from src.collectors.base import RawPostRecord
from src.extractor import _norm_date, extract_single
from src.live_pipeline import process_discovered_post

P = date(2026, 9, 17)

# Production item 2800, verbatim (body flattened to one line by acquisition,
# phone numbers already redacted - there were none).
TIMEBBA_TITLE = "■ 스윙타임빠 (9월 19,20일) 토,일 소셜 공지"
TIMEBBA_BODY = (
    "■ 스윙타임빠 (9월 19,20일) 토,일 소셜 공지 - 토요일 저녁 7시30분부터 소셜이 진행 됩니다. "
    "DJ '파인' PM 8:15~10:15 - 일요일 저녁 7시30분부터 소셜이 진행 됩니다. 1부 DJ '조커' "
    "PM 7:30~9:00 2부 DJ '조커' 9:00~10:30 ■ 타임빠소셜 실시간 스트리밍 서비스 안내 "
    "수, 일요일 소셜은 스윙프렌즈 유튜브채널에서 실시간으로 현장을 보실수 있습니다. "
    "바로가기 : https://youtube.com/@Swingfriendslive"
)

# Production item 2334, verbatim.
LAVIDA_TITLE = "2026년 9월 19일 토요일 밀롱가 La Vida No.802 DJ 조앤"
LAVIDA_BODY = (
    "이번주부터 밀롱가전에 72기 왕초급 강습이 시작됩니다. 모르는 분이 밀롱가에 보인다면 "
    "환영의 인사 부탁드립니당. 그리고 이번주는 생일밀롱가입니다. 부산탱고 La Vida No.802 "
    "날짜: 2026년 9월 19일 토요일 시간: PM 07:30~11:30 장소: 아미고스튜디오 DJ : 조앤"
)


class Dummy:
    pass


def _post(title, body, published=P, **kw):
    return RawPostRecord(
        source_id="SRC-D-010", platform="WEB", source_url="https://x.test/p",
        title=title, body=body, published_at=published,
        acquisition_quality="BODY_ONLY", **kw)


def _context(ev, value):
    return [e for e in ev.evidences if e.field == "context" and e.value == value]


# === T1. an explicit year in the title ======================================

def test_a_title_that_writes_its_own_year_is_read_as_that_day():
    """Production item 2334. The date reader was never the problem here and
    must not become one: it reads the title's own date, with the year the
    post actually wrote, and takes the clock and place from the body."""
    ev = extract_single(LAVIDA_TITLE, LAVIDA_BODY, event_type="MILONGA", published=P)
    assert ev.date == "2026-09-19"
    assert (ev.start_time, ev.end_time) == ("19:30", "23:30")
    assert ev.venue == "아미고스튜디오"
    assert _norm_date(LAVIDA_TITLE, published=P)[2] == "EXPLICIT_YEAR"


# === T2. a month naming two of its days ====================================

def test_a_two_day_title_is_read_as_its_first_day_and_flagged_as_a_span():
    """Production item 2800, the whole reason for this release.

    One candidate on the first day named, plus MULTI_DAY_EVENT - the same
    answer the existing "9.18-20" range already gives, because `events`
    holds one date and the post never separated the two days into
    programmes of its own. No new event model, no invented second event.
    """
    ev = extract_single(TIMEBBA_TITLE, TIMEBBA_BODY, event_type="SOCIAL", published=P)
    assert ev.date == "2026-09-19"
    span = _context(ev, "MULTI_DAY_EVENT")
    assert span and "19,20" in span[0].raw_text.replace(" ", "")


def test_the_whole_post_still_becomes_exactly_one_candidate():
    result = process_discovered_post(Dummy(), _post(TIMEBBA_TITLE, TIMEBBA_BODY), "COMMUNITY")
    assert result["classification"] == "SOCIAL"
    assert len(result["events"]) == 1
    assert result["events"][0].date == "2026-09-19"


@pytest.mark.parametrize("text, expected", [
    ("스윙타임빠 (9월 19,20일) 토,일 소셜", "2026-09-19"),
    ("스윙타임빠 (9월 19, 20일) 소셜", "2026-09-19"),
    ("[10월 1일 & 3일] 정기 소셜", "2026-10-01"),
    ("밀롱가 9월 19~20일", "2026-09-19"),
    ("밀롱가 9월 19·20일", "2026-09-19"),
])
def test_the_day_list_forms_a_community_actually_writes(text, expected):
    assert _norm_date(text, published=P)[0] == expected


@pytest.mark.parametrize("text", [
    "9월~10월 스페셜 원데이 클래스",   # two months, no day
    "20~30은 이런 수업입니다",          # not a date at all
    "회비 9월 1, 000원",                # a price, not a day list
    "9월 소셜 일정",                    # a month alone
])
def test_things_that_look_like_a_day_list_and_are_not(text):
    assert _norm_date(text, published=P)[0] is None


# === T3. a title's numbers are never a clock ===============================

def test_a_title_date_does_not_become_a_time():
    """"9월 19,20일" carries four digits and two separators. None of them is
    a clock, and a post whose body names no time must still have none."""
    ev = extract_single(TIMEBBA_TITLE, "", event_type="SOCIAL", published=P)
    assert ev.date == "2026-09-19"
    assert ev.start_time is None and ev.end_time is None
    assert rules.parse_time_range(TIMEBBA_TITLE, "SOCIAL") is None
    assert rules.parse_start_time(TIMEBBA_TITLE, "SOCIAL") is None


def test_the_evening_social_is_not_read_as_a_morning_one():
    """The second defect in item 2800: a section heading on the far side of
    a "■" claimed the 2부 set's marker-less 9:00 clock, and an evening
    social was published as 09:00-10:30. The post's own explicit PM reading
    wins instead."""
    ev = extract_single(TIMEBBA_TITLE, TIMEBBA_BODY, event_type="SOCIAL", published=P)
    assert ev.start_time == "20:15" and ev.end_time == "22:15"


# === T4. the body's own date still wins where it always did ================

def test_a_day_list_further_down_the_body_never_outranks_the_title_date():
    """`_norm_date()` searches the whole post with each pattern in turn, so a
    pattern placed too early wins *wherever* it sits. This one is ordered
    after the plain "M월 D일" precisely so the title keeps its own day."""
    title = "9월 19일 밀롱가"
    body = "다음 행사 안내: 9월 26,27일 워크샵도 예정되어 있습니다."
    assert _norm_date(f"{title} {body}", published=P)[0] == "2026-09-19"
    ev = extract_single(title, body, event_type="MILONGA", published=P)
    assert ev.date == "2026-09-19"


def test_an_explicit_year_in_the_body_still_beats_a_bare_day_list():
    text = "소셜 안내 9월 19,20일 / 자세한 일정은 2026.10.03 공지 참고"
    assert _norm_date(text, published=P)[0] == "2026-10-03"


# === T5. the year safety rules are untouched ===============================

def test_a_day_list_with_nothing_to_anchor_its_year_claims_no_date():
    """UNKNOWN_YEAR stays a refusal: without the post's own date there is
    nothing to place "9월 19,20일" in, and guessing the current year is what
    turned a 2024 post into this week's event."""
    resolved, raw, provenance = _norm_date("스윙타임빠 (9월 19,20일) 소셜", published=None)
    assert resolved is None
    assert raw and provenance == "UNKNOWN_YEAR"


def test_a_day_list_takes_its_year_from_the_post_not_the_clock():
    resolved, _raw, provenance = _norm_date("(1월 3,4일) 소셜", published=date(2025, 12, 28))
    assert resolved == "2026-01-03"
    assert provenance == "SOURCE_YEAR"


# === T6. no unrelated date leaks into the candidate ========================

def test_a_multi_programme_post_keeps_reading_its_own_programme():
    """The v0.96.2 shape (Production item 3132), unchanged: the reviewed
    programme is the one naming the night, and its own clock survives the
    section-break rule this release widened."""
    title = "[부산_탱고동호회]가또땅고 9월 둘째주 열탱즐탱 일정"
    body = ("9/14(월) 8:00~11:00pm 군무 연습 (이데알) 9/16(수)_8:00~9:10pm ① 무료 일일 특강 "
            "[가또땅고 쁘롱가] 9:15~11:15pm (DJ 알루, 아미고 큰홀)")
    ev = extract_single(title, body, event_type="MILONGA_WITH_CLASS",
                        published=date(2026, 9, 14))
    assert ev.date == "2026-09-16"
    assert (ev.start_time, ev.end_time) == ("21:15", "23:15")
    assert _context(ev, "MULTI_EVENT_CONTEXT")


def test_a_lesson_advert_that_lists_two_days_is_still_a_lesson():
    """Production item 2296's shape. A day list is a date form, never a
    reason to call a registration notice a night out."""
    result = process_discovered_post(
        Dummy(),
        _post("[10월1일 & 3일 개강] 142기 신규 모집: 살사&바차타 통합 초급반", "수강생을 모집합니다."),
        "COMMUNITY")
    assert result["classification"] == "CLASS"
    assert result["events"] == []


# === T7. the documented time readings, unchanged ===========================

@pytest.mark.parametrize("text, event_type, expected", [
    ("시간: PM 07:30~11:30", "MILONGA", ("19:30", "23:30")),
    ("Pm5:30~9:30", "MILONGA", ("17:30", "21:30")),
    ("6:30-10:30pm", "MILONGA", ("18:30", "22:30")),
    ("7pm~10:30pm", "MILONGA", ("19:00", "22:30")),
    ("오후 7시 ~ 11시", "MILONGA", ("19:00", "23:00")),
    ("PM 8시 – 12시", "MILONGA", ("20:00", "00:00")),
    ("23:30 – 04:30", "MILONGA", ("23:30", "04:30")),
    ("- 15:00-16:30 발스윙 중고급\n- 16:45-18:15 쉐그 초급\n- 20:00-22:30 소셜",
     "SOCIAL", ("20:00", "22:30")),
])
def test_existing_time_readings_are_unchanged(text, event_type, expected):
    reading = rules.parse_time_range(text, event_type)
    assert (reading.start, reading.end) == expected


def test_a_class_before_the_milonga_is_still_not_the_milongas_clock():
    reading = rules.parse_time_range(
        "7:30-8:45pm 지노&유니 특강 / 밀롱가 9:00-11:30pm", "MILONGA")
    assert (reading.start, reading.end) == ("21:00", "23:30")
