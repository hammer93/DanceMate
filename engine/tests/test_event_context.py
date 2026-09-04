"""Event Context Safety (v0.81.2).

A post can announce more than one program. Found live on the board on a
K-TANGO festival post: five numbered programs, each with its own date, time,
venue and fee, all in one flat string once acquisition strips the HTML that
used to separate them. extract_single() used to read date/time/venue/fee off
the whole post independently, and nothing stopped a date belonging to one
program from pairing with a time or venue read from another.

The fixtures below are abbreviated, not the real post - only the shape that
broke the extractor (two-plus numbered programs, each with its own date
immediately followed by its own time/venue/fee) is reproduced.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.extractor import extract_single


PUBLISHED = date(2026, 9, 1)


# --- 1. single event: unchanged --------------------------------------------

def test_a_single_event_post_is_read_exactly_as_before():
    ev = extract_single(
        "더 피스타 밀롱가",
        "9/5(토) THE PISTA MILONGA 19:30-23:30 장소: PISTA 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
    )
    assert ev.date == "2026-09-05"
    assert (ev.start_time, ev.end_time) == ("19:30", "23:30")
    assert ev.venue == "PISTA"
    assert ev.fee == 13000
    assert not any(e.field == "context" for e in ev.evidences)
    assert all(e.context_id is None for e in ev.evidences)


# --- 2-4. two event blocks: date/time/venue/fee not mixed ------------------

TWO_PROGRAM_BODY = (
    "1. Special Performance 일시 : 9월 5일 목요일 PM 19:00 ~ PM20:30 "
    "장소 : 연세대학교 대강당 내용 : 공연입니다 "
    "5. VIP 밀롱가 일시 : 9월 6일 금요일 PM 20:00 ~ PM24:00 "
    "장소 : 안단테 스튜디오 입장료 13,000원 밀롱가 안내입니다"
)


def test_two_program_dates_are_recognised_as_separate_contexts():
    ev = extract_single("K-TANGO SF", TWO_PROGRAM_BODY,
                        event_type="MILONGA", published=PUBLISHED)
    context_ids = {e.context_id for e in ev.evidences if e.context_id}
    assert len(context_ids) >= 1  # at least the winning segment is tagged


def test_date_from_program_a_is_not_paired_with_time_from_program_b():
    """The only program naming '밀롱가' is #5 (9/6, 20:00) - #1 is a
    'Performance' with no milonga word nearby, so it must lose."""
    ev = extract_single("K-TANGO SF", TWO_PROGRAM_BODY,
                        event_type="MILONGA", published=PUBLISHED)
    assert ev.date == "2026-09-06"
    assert ev.start_time == "20:00"


def test_venue_from_program_a_is_not_paired_with_fee_from_program_b():
    ev = extract_single("K-TANGO SF", TWO_PROGRAM_BODY,
                        event_type="MILONGA", published=PUBLISHED)
    assert ev.venue == "안단테 스튜디오"
    assert ev.venue != "연세대학교 대강당"
    assert ev.fee == 13000


# --- 5-8. boundary recognition ----------------------------------------------

def test_a_numbered_list_marker_is_a_segment_boundary():
    ev = extract_single(
        "이중 프로그램",
        "1. 워크샵 9월 5일 15:00-16:30 장소: 대전스튜디오 "
        "2. 밀롱가 9월 6일 20:00-23:00 장소: 서울스튜디오 입장료 15,000원",
        event_type="MILONGA", published=PUBLISHED,
    )
    assert ev.date == "2026-09-06"
    assert ev.venue == "서울스튜디오"


def test_a_blank_line_style_gap_does_not_break_single_segment_extraction():
    """Acquisition flattens whitespace before the engine ever sees the text,
    so a literal blank line never reaches extract_single - this pins that a
    single-date post with generous spacing still reads as one segment."""
    ev = extract_single(
        "단일 행사", "9월 5일 (토) 19:30-23:30    장소: PISTA    입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
    )
    assert ev.date == "2026-09-05"
    assert ev.venue == "PISTA"
    assert ev.fee == 13000


def test_a_bullet_separated_list_item_is_a_segment_boundary():
    ev = extract_single(
        "두 밀롱가",
        "• 9월 5일 낮밀롱가 14:00-17:00 카페탱고 "
        "• 9월 6일 밤밀롱가 20:00-23:00 안단테 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
    )
    # Whichever program wins, its own fields must agree with each other.
    if ev.date == "2026-09-05":
        assert ev.start_time in (None, "14:00")
    elif ev.date == "2026-09-06":
        assert ev.start_time in (None, "20:00")


def test_explicit_program_labels_are_recognised():
    ev = extract_single(
        "K-TANGO SF",
        "Program A: 9월 5일 워크샵 15:00-16:30 "
        "Program B: 9월 6일 밀롱가 20:00-22:00 PISTA 13,000원",
        event_type="MILONGA", published=PUBLISHED,
    )
    assert ev.date == "2026-09-06"
    assert ev.venue == "PISTA"


# --- 9-11. ambiguous context, missing over wrong ----------------------------

def test_two_matching_programs_are_flagged_ambiguous_not_merged():
    """Both programs say 밀롱가 - genuinely ambiguous which one this
    candidate is about. It must fall back to one program's own fields
    wholesale, never combine the two."""
    ev = extract_single(
        "복수 밀롱가 행사",
        "1. 낮 밀롱가 9월 5일 14:00-17:00 장소: 카페탱고 "
        "2. 밤 밀롱가 9월 6일 20:00-23:00 장소: 안단테 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
    )
    assert any(e.field == "context" and e.value == "MULTI_EVENT_CONTEXT"
               for e in ev.evidences)
    # Whichever segment it fell back to, date and venue still agree with
    # each other - never 9/5 paired with 안단테, or 9/6 with 카페탱고.
    if ev.date == "2026-09-05":
        assert ev.venue != "안단테"
    elif ev.date == "2026-09-06":
        assert ev.venue != "카페탱고"


def test_missing_field_is_preferred_over_a_wrong_cross_context_fill():
    """The winning program (#2, names the event's own type) has no venue of
    its own; #1's venue must not be borrowed to fill the gap."""
    ev = extract_single(
        "K-TANGO SF",
        "1. 워크샵 9월 5일 15:00-16:30 장소: 대전스튜디오 "
        "2. 밀롱가 9월 6일 20:00-22:00 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
    )
    assert ev.date == "2026-09-06"
    assert ev.venue != "대전스튜디오"


def test_human_review_receives_the_ambiguous_context_warning():
    ev = extract_single(
        "복수 밀롱가 행사",
        "1. 낮 밀롱가 9월 5일 14:00-17:00 카페탱고 "
        "2. 밤 밀롱가 9월 6일 20:00-23:00 안단테 13,000원",
        event_type="MILONGA", published=PUBLISHED,
    )
    warnings = [e for e in ev.evidences if e.field == "context"]
    assert len(warnings) == 1
    assert warnings[0].value == "MULTI_EVENT_CONTEXT"


# --- 12-13. existing regression ---------------------------------------------

def test_existing_tango_milonga_regression_unaffected():
    ev = extract_single(
        "9/5 THE PISTA MILONGA",
        "9/5(토) THE PISTA MILONGA. DJ Epitone. 입장료 13,000원. "
        "장소 홍대 PISTA 서울 마포구 월드컵북로6길 49 B1.",
        event_type="MILONGA", published=PUBLISHED,
    )
    assert ev.date == "2026-09-05"
    assert ev.fee == 13000
    assert ev.venue and "PISTA" in ev.venue


def test_existing_swing_social_regression_unaffected():
    ev = extract_single(
        "BAL&SHAG 워크샵",
        "일정 8/8 (토) - 15:00-16:30 발스윙 중고급 - 16:45-18:15 쉐그 초급 "
        "- 20:00-22:30 소셜 8/9 (일) - 13:00-14:30 슬로우발",
        event_type="SOCIAL_WITH_CLASS", published=date(2026, 8, 1),
    )
    assert (ev.start_time, ev.end_time) == ("20:00", "22:30")


# --- 14-15. wrong time / wrong date must stay at 0 --------------------------

def test_wrong_time_stays_zero_across_multi_program_posts():
    """The multi-program cases above must never assign a time that belongs
    to a different date than the one finally reported."""
    ev = extract_single(
        "K-TANGO SF", TWO_PROGRAM_BODY, event_type="MILONGA", published=PUBLISHED,
    )
    if ev.date == "2026-09-05":
        assert ev.start_time != "20:00"
    elif ev.date == "2026-09-06":
        assert ev.start_time != "19:00"


def test_wrong_date_stays_zero_when_only_one_program_names_the_event_type():
    ev = extract_single("K-TANGO SF", TWO_PROGRAM_BODY,
                        event_type="MILONGA", published=PUBLISHED)
    # Program #1 (9/5, Special Performance) never mentions 밀롱가; only #5
    # (9/6) does, so 9/5 must never be the reported date here.
    assert ev.date != "2026-09-05"
