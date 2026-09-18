"""v0.96.0 direct-source event extraction yield (Information Engine 0.89).

What a community, organizer or venue board actually writes - "저녁 7시" for
a start, "@오초" for a place, "매월 둘째 토요일" for a date, "Special Event
9월24일" for a night with no scene word, one "9월 소셜 일정" post for three
nights, and a recap that carries every word of an announcement - and what
the engine has to make of each. Every string reproduces a *form* seen on
OSIK, 가또땅고, 비바스윙 or 올어바웃스윙 in Production; none is a stored copy
of a real post and none carries a person's data.

The before/after section at the end runs the ~100-post fixture through the
live pipeline and compares with the counts the v0.95.0 engine produced on
the same fixture (captured by running it with `engine/src` stashed). The
claim is narrow and checked both ways: more real announcements become
dated, upcoming, timed and placed candidates, and no non-event does.
"""

import re
from datetime import date

import pytest

from fixture_v0960_direct_posts import EVENT_PAST, EVENT_UPCOMING, NON_EVENT, POSTS, PUBLISHED
from src import extraction_rules as rules
from src.classifier import classify, is_non_event_notice, notice_evidence_bundle
from src.collectors.base import RawPostRecord
from src.extractor import (
    SOURCE_MONTHLY_BOUNDED,
    SOURCE_RELATIVE_DATE,
    SOURCE_YEAR,
    UNKNOWN_YEAR,
    _norm_date,
    extract_schedule,
    extract_single,
)
from src.live_pipeline import EVENT_CLASSIFICATIONS, process_discovered_post

P = date(2026, 9, 14)  # a Monday


class Dummy:
    pass


def _post(title, body, published=PUBLISHED, quality="BODY_ONLY", **kw):
    return RawPostRecord(
        source_id="SRC-X-001", platform="DAUM_CAFE", source_url="https://x.test/p",
        title=title, body=body, published_at=published, acquisition_quality=quality, **kw)


# === 1. classification: events announced without a scene word ===============

@pytest.mark.parametrize("title, body, expected", [
    ("[부산_탱고동호회]가또땅고 Special Event 9월24일(목)", "장소: 이데알 탱고 까페 저녁 7시", "SOCIAL"),
    ("OSIK 정모 안내 9/19(토)", "장소: 스튜디오 오초 오후 7시 30분 시작", "SOCIAL"),
    ("게스트 DJ 나이트 9월 26일 토", "장소: 피스타 밤 8시부터", "SOCIAL"),
    ("이번 달 정모 9/20", "@ 오초 저녁 8시", "SOCIAL"),
    # The standard practica spellings are the tango night the old "쁘락" was.
    ("OSIK 프락티카 9월 20일 일요일", "오후 3시부터 6시까지 @ 오초 스튜디오", "MILONGA"),
    ("Practica 9/27 Sun", "3pm at Studio Ocho", "MILONGA"),
    # A one-off open class beside the milonga is the milonga, not a course.
    ("원데이 오픈클래스 & 밀롱가 9/25(금)", "오픈클래스 19:00 밀롱가 20:00-23:00", "MILONGA"),
    # ...and with a course word present, the Korean open class counts like
    # "open class" already did: the night, with its lesson attached.
    ("밀롱가 & 원데이 워크샵 9/25(금)", "워크샵 19:00 밀롱가 20:00-23:00", "MILONGA_WITH_CLASS"),
])
def test_an_announcement_without_a_scene_word_still_reads_as_the_night(title, body, expected):
    assert classify(title, body) == expected


@pytest.mark.parametrize("title, body", [
    # The notice word alone is never enough - no day.
    ("정모 안내", "매주 화요일 저녁 8시 오초에서 만나요"),
    # A day but nothing that says where or when.
    ("Special Event 9월24일", "자세한 내용은 추후 공지"),
    # A day and a clock, but the word is only in the body.
    ("공지", "9/24 정모 저녁 7시"),
])
def test_the_notice_bundle_needs_the_word_a_day_and_a_clock_or_place(title, body):
    assert not notice_evidence_bundle(title, body)
    assert classify(title, body) == "OTHER"


# === 2. classification: non-events that carry the announcement's words ======

NEGATIVES = [
    ("스윙댄스동호회 올어바웃스윙 98학기 2주차 토요일 축하소셜 생일빵 라인댄스 영상", "2026.6.27"),
    ("9/5 소셜 파티 후기", "지난 토요일 소셜 정말 즐거웠어요"),
    ("8/19 수요 밀롱가 사진 모음", "이데알 탱고 까페에서 찍은 사진입니다"),
    ("월간가또 시즌1 마지막 밀롱가 스케치 영상", "8/8 토요일 밀롱가 영상 올립니다"),
    ("[리뷰] 9/12 소셜 DJ 셋리스트", "지난 소셜 20:00-23:00 셋리스트 공유"),
    ("동호회 가입 안내", "정모는 매주 화요일 저녁 8시 오초에서 진행합니다"),
    ("회비 안내 (9월)", "9월 회비는 9/20까지 입금 부탁드립니다 정모 참가는 회비 납부 후"),
    ("스튜디오 대관 공지", "9/26(토) 20:00-23:00 대관으로 소셜 없습니다 장소: 스윙홀"),
    ("강사 소개 - 9월 정규반", "매주 목요일 20:00 강습 담당 강사를 소개합니다 장소: 비바스윙"),
    ("신입 회원 인사드립니다", "9/19 토요일 소셜에 처음 나가요"),
    ("9/19 밀롱가 신청 마감 안내", "9/19 밀롱가 신청이 마감되었습니다 장소: 피스타 저녁 8시"),
    ("9/26 소셜 취소 안내", "9/26 토요일 20:00 소셜은 취소되었습니다 @ 스윙홀"),
    ("지난 학기 소셜 정리", "98학기 동안 진행한 소셜 12회를 정리했습니다"),
    ("소셜 드레스코드 안내", "10/31 할로윈 파티 드레스코드 관련 문의가 많아 안내드립니다"),
    ("탱고 슈즈 공동구매", "9/20까지 신청 밀롱가 슈즈 할인 판매"),
    ("Swing Social Recap 9/5", "photos from Saturday's social at Bounce Blue"),
]


@pytest.mark.parametrize("title, body", NEGATIVES)
def test_recaps_and_administrative_notices_are_not_events(title, body):
    assert is_non_event_notice(title)
    assert classify(title, body) == "OTHER"
    assert process_discovered_post(Dummy(), _post(title, body), "PRIMARY_ORGANIZER")["events"] == []


def test_the_non_event_gate_reads_the_title_only():
    # A real announcement whose body points at last time's video stays an event.
    title, body = "9/19 토요일 밀롱가", "지난 밀롱가 영상 참고하세요 저녁 8시 장소: 피스타"
    assert not is_non_event_notice(title)
    assert classify(title, body) == "MILONGA"


def test_the_class_word_list_is_unchanged():
    assert classify("린디합 초급 8월 강습] 8/6(화) 개강: 화목반 @ 신천 비바스윙", "") == "CLASS"
    assert classify("Special Milonga Lesson 개설", "매주 수요일 8시") == "CLASS"


# === 3. dates ==============================================================

@pytest.mark.parametrize("text, expected, provenance", [
    ("9/24 밀롱가", "2026-09-24", SOURCE_YEAR),
    ("09/24 밀롱가", "2026-09-24", SOURCE_YEAR),
    ("9월 24일 밀롱가", "2026-09-24", SOURCE_YEAR),
    ("9월24일 밀롱가", "2026-09-24", SOURCE_YEAR),
    ("9.24 밀롱가", "2026-09-24", SOURCE_YEAR),
    ("2026.09.24 밀롱가", "2026-09-24", "EXPLICIT_YEAR"),
    ("2026-09-24 밀롱가", "2026-09-24", "EXPLICIT_YEAR"),
    ("9/24(목) 밀롱가", "2026-09-24", SOURCE_YEAR),
    ("9월 24일 목요일 밀롱가", "2026-09-24", SOURCE_YEAR),
    ("이번주 토요일 밀롱가", "2026-09-19", SOURCE_RELATIVE_DATE),
    ("이번 주 토요일 밀롱가", "2026-09-19", SOURCE_RELATIVE_DATE),
    ("다음주 수요일 밀롱가", "2026-09-23", SOURCE_RELATIVE_DATE),
    ("다음 주 수요일 밀롱가", "2026-09-23", SOURCE_RELATIVE_DATE),
    ("매주 화요일 밀롱가", "2026-09-15", "SOURCE_WEEKLY_BOUNDED"),
    # v0.96.0: a named month's nth weekday - the closest-year rule, SOURCE_YEAR.
    ("9월 셋째주 토요일 밀롱가", "2026-09-19", SOURCE_YEAR),
    ("9월 마지막 주 토요일 밀롱가", "2026-09-26", SOURCE_YEAR),
    ("10월 첫째 금요일 밀롱가", "2026-10-02", SOURCE_YEAR),
    # v0.96.0: every month's nth weekday / day - the single next occurrence.
    ("매월 둘째 토요일 밀롱가", "2026-10-10", SOURCE_MONTHLY_BOUNDED),  # 9/12 has passed
    ("매월 셋째 토요일 밀롱가", "2026-09-19", SOURCE_MONTHLY_BOUNDED),
    ("매월 마지막 금요일 밀롱가", "2026-09-25", SOURCE_MONTHLY_BOUNDED),
    ("매월 15일 밀롱가", "2026-09-15", SOURCE_MONTHLY_BOUNDED),
    ("매월 1일 밀롱가", "2026-10-01", SOURCE_MONTHLY_BOUNDED),
])
def test_every_date_form_resolves_against_the_posts_own_date(text, expected, provenance):
    resolved, raw, inference = _norm_date(text, published=P)
    assert (resolved, inference) == (expected, provenance)
    assert raw


def test_a_monthly_recurrence_is_one_occurrence_never_a_series():
    ev = extract_single("[부산_가또땅고]월간가또 Monthly Gato Milonga 시즌2",
                        "매월 둘째 토요일 19:00-23:00 이데알 탱고 까페",
                        event_type="MILONGA", published=P)
    assert (ev.date, ev.start_time, ev.end_time) == ("2026-10-10", "19:00", "23:00")
    assert ev.venue == "이데알 탱고 까페"


@pytest.mark.parametrize("text", [
    "이번주 토요일 밀롱가", "다음주 수요일 밀롱가", "매주 화요일 밀롱가",
    "매월 둘째 토요일 밀롱가", "9월 셋째주 토요일 밀롱가", "오늘 밀롱가",
])
def test_without_a_published_date_no_relative_form_is_ever_dated(text):
    resolved, _raw, _inference = _norm_date(text, published=None)
    assert resolved is None


def test_a_monthly_occurrence_too_far_ahead_is_not_projected():
    # Published on the 1st, "매월 마지막 ..." of a 31-day month is 30 days
    # away - inside the window; MAX_DAYS_MONTHLY_AHEAD bounds it, not a guess.
    resolved, _raw, inference = _norm_date("매월 30일 밀롱가", published=date(2026, 9, 14))
    assert (resolved, inference) == ("2026-09-30", SOURCE_MONTHLY_BOUNDED)


def test_a_naver_metadata_only_item_without_a_published_date_yields_no_dated_candidate():
    post = _post("OSIK 원데이 클래스! 금요일 8:30~9:20pm(초급 정모)", "", published=None,
                 quality="METADATA_ONLY")
    result = process_discovered_post(Dummy(), post, "PRIMARY_ORGANIZER")
    assert all(ev.date is None for ev in result["events"])
    for ev in result["events"]:
        assert ev.status != "VERIFIED"


# === 4. times ==============================================================

@pytest.mark.parametrize("text, start, end", [
    ("저녁 7시 밀롱가", "19:00", None),
    ("오후 7시 30분 시작", "19:30", None),
    ("7:30pm start", "19:30", None),
    ("19:30 밀롱가", "19:30", None),
    ("19시 밀롱가", "19:00", None),
    ("20시 소셜", "20:00", None),
    ("8시부터 밀롱가", "08:00", None),   # no meridiem: literal, flagged ambiguous
    ("밤 9시부터 소셜", "21:00", None),
])
def test_a_lone_start_clock_is_a_start_with_no_end(text, start, end):
    reading = rules.parse_start_time(text)
    assert reading is not None
    assert (reading.start, reading.end) == (start, end)


def test_a_bare_hour_without_a_start_marker_is_ambiguous_and_left_alone():
    assert rules.parse_start_time("8시 밀롱가") is None
    assert rules.parse_start_time("8시 마감") is None
    assert rules.parse_start_time("9시까지 신청") is None


def test_two_different_lone_clocks_for_two_different_things_are_not_guessed():
    # The v0.91.0 salsa shape: a club-open clock and a second program's clock.
    assert rules.parse_start_time("클럽 오픈 오후 8시 DJ BLD & DJ 나리 / 추석 살사데이 라틴으로 오후 7시 핸슨",
                                  "SOCIAL_WITH_CLASS") is None
    # The same two clocks, one of them beside the event's own word: that one.
    assert rules.parse_start_time("클럽 오픈 오후 8시 DJ BLD & DJ 나리 웜업 / 소셜 오후 9시 시작",
                                  "SOCIAL").start == "21:00"


def test_a_literal_start_clock_is_flagged_ambiguous_an_explicit_one_is_not():
    assert rules.parse_start_time("8시부터 밀롱가").ambiguous is True
    assert rules.parse_start_time("저녁 8시부터 밀롱가").ambiguous is False
    assert rules.parse_start_time("20:00 밀롱가").ambiguous is False


@pytest.mark.parametrize("text, start, end", [
    ("7시~10시", "07:00", "10:00"),
    ("저녁 7시~10시", "19:00", "22:00"),
    ("19:00-22:00", "19:00", "22:00"),
    ("8시부터 11시까지", "08:00", "11:00"),
])
def test_a_range_still_wins_over_the_single_clock_rule(text, start, end):
    ev = extract_single("9/19 밀롱가", text, event_type="MILONGA", published=P)
    assert (ev.start_time, ev.end_time) == (start, end)


def test_the_single_clock_reaches_the_candidate_through_extract_single():
    ev = extract_single("이번주 토요일 소셜 파티", "오후 7시 30분 시작 장소: 바운스블루",
                        event_type="SOCIAL", published=P)
    assert (ev.date, ev.start_time, ev.end_time, ev.venue) == ("2026-09-19", "19:30", None, "바운스블루")
    time_evidence = next(e for e in ev.evidences if e.field == "time")
    assert time_evidence.value["end"] is None


# === 5. venues =============================================================

@pytest.mark.parametrize("text, name, label", [
    ("장소: 이데알 탱고 까페 저녁 7시", "이데알 탱고 까페", "장소"),
    ("Venue: Studio Ocho 7:30pm", "Studio Ocho", "Venue"),
    ("매주 화요일 저녁 8시부터 밀롱가 @ 오초", "오초", "@"),
    ("20:00 @스튜디오 오초", "스튜디오 오초", "@"),
    ("저녁 8시 @ 신천 비바스윙 회원 무료", "신천 비바스윙 회원 무료", "@"),
    ("8pm start at Studio Ocho fee 10,000원", "Studio Ocho fee", "@"),
    ("이데알 탱고 까페 저녁 8시부터", "이데알 탱고 까페", "SUFFIX"),
    ("20시 홍대 스윙바 20:00", "홍대 스윙바", "SUFFIX"),
])
def test_unlabelled_venue_forms_are_read(text, name, label):
    reading = rules.extract_venue(text)
    assert reading is not None
    assert reading.label == label
    assert reading.name.startswith(name.split(" ")[0])
    assert reading.name == name or name.startswith(reading.name)


@pytest.mark.parametrize("text", [
    "@allaboutswing 팔로우 부탁드립니다 소셜 사진은 인스타에",
    "문의는 tango@example.com",
    "스튜디오 대관 안내",
    "카페 추천 부탁드립니다",
    "at 8pm",
])
def test_handles_addresses_and_bare_suffix_words_are_not_venues(text):
    assert rules.extract_venue(text) is None


def test_a_clock_after_the_labelled_venue_ends_the_name():
    ev = extract_single("[부산_탱고동호회]가또땅고 Special Event 9월24일(목)",
                        "장소: 이데알 탱고 까페 저녁 7시 회비 10,000원",
                        event_type="SOCIAL", published=P)
    assert (ev.date, ev.start_time, ev.end_time) == ("2026-09-24", "19:00", None)
    assert ev.venue == "이데알 탱고 까페"
    assert ev.fee == 10000


# === 6. schedule posts =====================================================

def test_a_schedule_post_becomes_one_candidate_per_dated_program():
    post = _post("10월 소셜 일정",
                 "10/3 토 소셜 20:00 @ 스윙홀 / 10/10 토 소셜 20:00 @ 스윙홀 / 10/17 토 파티 20:00 @ 스윙홀")
    result = process_discovered_post(Dummy(), post, "PRIMARY_ORGANIZER")
    assert result["classification"] == "SOCIAL"
    got = [(ev.date, ev.start_time, ev.venue) for ev in result["events"]]
    assert got == [("2026-10-03", "20:00", "스윙홀"), ("2026-10-10", "20:00", "스윙홀"),
                   ("2026-10-17", "20:00", "스윙홀")]
    for ev in result["events"]:
        assert any(e.field == "context" and e.value == "SCHEDULE_ITEM" for e in ev.evidences)
        assert ev.name.endswith(ev.date[5:].replace("-", "/"))


def test_a_program_outside_the_announcement_window_is_left_out_not_fatal():
    events = extract_schedule("9월 소셜 일정 안내",
                              "9/5 토 소셜 20:00 / 9/19 토 소셜 20:00 / 9/26 토 파티 20:00 @스튜디오 오초",
                              event_type="SOCIAL", published=P)
    assert [ev.date for ev in events] == ["2026-09-19", "2026-09-26"]


@pytest.mark.parametrize("title, body", [
    # No schedule title: a prose post naming two dates stays one candidate.
    ("9/19 밀롱가", "9/19 저녁 8시 밀롱가 다음 밀롱가는 9/26 입니다"),
    # A schedule title but only one program names the event.
    ("9월 일정 안내", "9/19 소셜 20:00 / 9/26 강습 20:00"),
    # A schedule title, two dates, but neither program names the event type.
    ("9월 일정", "9/19 20:00 / 9/26 20:00"),
])
def test_anything_less_clear_cut_stays_one_candidate_for_a_person(title, body):
    assert extract_schedule(title, body, event_type="SOCIAL", published=P) is None
    post = _post(title, body)
    result = process_discovered_post(Dummy(), post, "PRIMARY_ORGANIZER")
    assert len(result["events"]) <= 1


def test_a_schedule_never_needs_the_crawl_clock():
    # No published date: a yearless "10/3" cannot be resolved (the existing
    # UNKNOWN_YEAR rule), so there is no schedule to expand - never a guess.
    assert extract_schedule("10월 소셜 일정", "10/3 소셜 20:00 / 10/10 소셜 20:00",
                            event_type="SOCIAL", published=None) is None
    # Explicit years need no anchor at all.
    events = extract_schedule("소셜 일정", "2026-10-03 소셜 20:00 / 2026-10-10 소셜 20:00",
                              event_type="SOCIAL", published=None)
    assert [ev.date for ev in events] == ["2026-10-03", "2026-10-10"]


# === 7. per-source tuning through event_terms ===============================

def test_a_sources_own_night_word_reaches_classification_through_event_terms():
    assert classify("OSIK 열탱즐탱 9/20", "오후 3시 @ 오초") == "OTHER"
    assert classify("OSIK 열탱즐탱 9/20", "오후 3시 @ 오초", event_terms=("열탱즐탱",)) == "MILONGA"


# === 8. before / after on the ~100-post fixture ============================

# What the v0.95.0 engine (Information Engine 0.88) made of exactly this
# fixture, captured by running it with `engine/src` stashed. Hard-coded on
# purpose: the comparison must not drift with the engine under test.
BEFORE = {
    "true_event_posts": 54, "false_positive_posts": 19, "positive_posts_missed": 8,
    "upcoming_true": 39, "with_time": 16, "with_venue": 32,
}


def _measure():
    today = date.fromisoformat(PUBLISHED)
    counts = {"true_event_posts": 0, "false_positive_posts": 0, "positive_posts_missed": 0,
              "upcoming_true": 0, "with_time": 0, "with_venue": 0, "candidates": 0}
    for index, (title, body, published, expect) in enumerate(POSTS):
        post = RawPostRecord(source_id="SRC-X", platform="DAUM_CAFE",
                             source_url=f"https://x.test/{index}", title=title, body=body,
                             published_at=published, acquisition_quality="BODY_ONLY")
        events = process_discovered_post(Dummy(), post, "PRIMARY_ORGANIZER")["events"]
        if events and expect == NON_EVENT:
            counts["false_positive_posts"] += 1
        elif events:
            counts["true_event_posts"] += 1
        elif expect != NON_EVENT:
            counts["positive_posts_missed"] += 1
        for ev in events:
            counts["candidates"] += 1
            if expect != NON_EVENT and ev.date and date.fromisoformat(ev.date) >= today:
                counts["upcoming_true"] += 1
            if expect != NON_EVENT and ev.start_time:
                counts["with_time"] += 1
            if expect != NON_EVENT and ev.venue:
                counts["with_venue"] += 1
    return counts


def test_the_fixture_is_the_size_and_shape_the_release_claims():
    assert len(POSTS) >= 100
    expectations = [p[3] for p in POSTS]
    assert expectations.count(NON_EVENT) >= 30
    assert expectations.count(EVENT_UPCOMING) >= 50
    assert expectations.count(EVENT_PAST) >= 5
    # Practica posts use the standard spellings only (PRACTICA / 프락티카 / Práctica).
    practica = [p for p in POSTS if re.search(r"practica|práctica|프락티카", f"{p[0]} {p[1]}", re.I)]
    assert len(practica) >= 3


def test_after_reads_more_real_nights_and_no_non_event_than_before():
    after = _measure()
    # Recall: every real announcement now yields a candidate...
    assert after["positive_posts_missed"] == 0 < BEFORE["positive_posts_missed"]
    assert after["true_event_posts"] > BEFORE["true_event_posts"]
    # ...more of them upcoming, timed and placed...
    assert after["upcoming_true"] > BEFORE["upcoming_true"]
    assert after["with_time"] > BEFORE["with_time"]
    assert after["with_venue"] > BEFORE["with_venue"]
    # ...and precision went up, not down: no non-event becomes an event.
    assert after["false_positive_posts"] == 0 < BEFORE["false_positive_posts"]


def test_every_fixture_positive_is_dated_on_the_right_side_of_its_post():
    today = date.fromisoformat(PUBLISHED)
    for index, (title, body, published, expect) in enumerate(POSTS):
        if expect == NON_EVENT:
            continue
        post = RawPostRecord(source_id="SRC-X", platform="DAUM_CAFE",
                             source_url=f"https://x.test/{index}", title=title, body=body,
                             published_at=published, acquisition_quality="BODY_ONLY")
        result = process_discovered_post(Dummy(), post, "PRIMARY_ORGANIZER")
        assert result["classification"] in EVENT_CLASSIFICATIONS, title
        for ev in result["events"]:
            assert ev.date, title
            if expect == EVENT_UPCOMING:
                assert date.fromisoformat(ev.date) >= today, title
            else:
                assert date.fromisoformat(ev.date) < today, title
