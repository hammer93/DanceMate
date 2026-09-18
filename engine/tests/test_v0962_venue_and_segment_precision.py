"""v0.96.2 direct-source venue and schedule precision (Information Engine 0.90;
0.91 adds the attached-particle person rule, see test_v0962_person_mentions.py).

Two real misreads from the v0.96.0 Production verification, fixed without
loosening anything:

* "@" followed by a person or an account is not a venue ("루 @ 선배님 은 ...",
  "인스타그램 DM: @intothelatinittl º 카카오톡 ID: ..."), while "@오초" and
  "@ 아미고 스튜디오" still are;
* a multi-program post is segmented at structural anchors, never inside a
  clock ("8:00~11:00pm" was cut to "8:00~11:00" | "pm" and read as morning),
  and the reviewed candidate of an ambiguous post is the program that names
  the night and carries a clock - still flagged MULTI_EVENT_CONTEXT.

The before/after section compares the fixture in fixture_v0962_precision.py
against the counts the v0.96.1 engine (Information Engine 0.89) produced on
it, captured by running the same measurement with `engine/src` stashed.
"""

from datetime import date

import pytest

from fixture_v0962_precision import (
    AT_NOT_A_VENUE,
    AT_VENUE,
    GATO_WEEKLY_BODY,
    GATO_WEEKLY_PUBLISHED,
    GATO_WEEKLY_TITLE,
    MULTI_PROGRAM,
    TIME_FORMS,
    WEEKLY_LINES_BODY,
    WEEKLY_LINES_TITLE,
)
from src import extraction_rules as rules
from src.collectors.base import RawPostRecord
from src.extractor import _boundary_before, _context_segments, extract_schedule, extract_single
from src.live_pipeline import process_discovered_post

P = date(2026, 9, 14)


class Dummy:
    pass


def _post(title, body, published=P, **kw):
    return RawPostRecord(
        source_id="SRC-X-001", platform="DAUM_CAFE", source_url="https://x.test/p",
        title=title, body=body, published_at=published, acquisition_quality="BODY_ONLY", **kw)


# === 1. "@" that is a person or an account ===================================

def test_fixture_a_a_person_addressed_with_at_is_not_a_venue():
    assert rules.extract_venue("@ 선배님 은 이번 행사에 꼭 오세요") is None
    # Production item 2020's own shape: nickname, "@", honorific, particle.
    assert rules.extract_venue("루 @ 선배님 은 밀롱가에 살다시피 하신다 했다") is None


def test_fixture_b_a_handle_in_a_contact_line_is_not_a_venue():
    assert rules.extract_venue("문의 @intothelatinittl º 카카오톡") is None
    assert rules.extract_venue(
        "📞 문의 º 인스타그램 DM: @intothelatinittl º 카카오톡 ID: latin_manager (매니저)") is None


@pytest.mark.parametrize("text", AT_NOT_A_VENUE)
def test_people_handles_accounts_prose_and_bare_rooms_are_not_venues(text):
    assert rules.extract_venue(text) is None


def test_the_rules_are_grammar_not_a_name_list():
    # Any 님-honorific, not a dictionary: a word the list never saw.
    assert rules.extract_venue("@ 총무님 감사합니다") is None
    # Any ASCII handle followed by a non-Latin token.
    assert rules.extract_venue("@some_other_handle º 인스타") is None
    # A detached particle ends the name; the place before it survives.
    assert rules.extract_venue("@ 오초 에서 만나요").name == "오초"
    # A Latin name that continues in Latin is a place, not a handle.
    assert rules.extract_venue("@Studio Ocho 7:30pm").name == "Studio Ocho"


# === 2. "@" that is a place: no regression ==================================

def test_fixture_c_a_short_korean_at_venue_is_still_read():
    ev = extract_single("9월 24일 정모", "9월 24일 저녁 8시\n@오초", event_type="SOCIAL", published=P)
    assert (ev.date, ev.start_time, ev.end_time, ev.venue) == ("2026-09-24", "20:00", None, "오초")
    venue = next(e for e in ev.evidences if e.field == "venue")
    assert venue.inference == "LABEL:@"


def test_fixture_d_a_long_korean_at_venue_keeps_its_pm_time():
    ev = extract_single("9월 16일 밀롱가", "9월 16일 9:15-11:15pm\n@ 아미고 스튜디오",
                        event_type="MILONGA", published=P)
    assert (ev.date, ev.start_time, ev.end_time, ev.venue) == ("2026-09-16", "21:15", "23:15", "아미고 스튜디오")


@pytest.mark.parametrize("text, expected", AT_VENUE)
def test_every_real_at_venue_form_is_still_read(text, expected):
    reading = rules.extract_venue(text)
    assert reading is not None, text
    assert reading.name == expected


def test_a_bare_room_word_is_refused_but_a_named_hall_is_not():
    assert rules.extract_venue("메인홀 20:00") is None
    assert rules.extract_venue("20:00 안쪽홀") is None
    assert rules.extract_venue("@ 큰홀") is None
    assert rules.extract_venue("아미고 큰홀 9:15pm").name == "아미고 큰홀"
    assert rules.extract_venue("@ 올어바웃스윙 홀").name == "올어바웃스윙 홀"


# === 3. pm / am preservation ==============================================

@pytest.mark.parametrize("text, start, end", TIME_FORMS)
def test_every_meridiem_form_reads_as_before(text, start, end):
    reading = rules.parse_time_range(text) or rules.parse_start_time(text)
    assert reading is not None
    assert (reading.start, reading.end) == (start, end)
    if any(mark in text.lower() for mark in ("pm", "저녁", "오후")):
        assert reading.meridiem_evidence == rules.EVIDENCE_EXPLICIT


@pytest.mark.parametrize("text", ["9:15-11:15pm", "8:00~11:00pm", "19:00", "9:15pm", "20:00-23:00",
                                  "2026.09.24", "9/24", "9월 24일"])
def test_a_boundary_never_falls_inside_a_date_or_clock_token(text):
    # The token sits right where the old midpoint would have cut it. A date
    # token is itself a program heading, so it opens a segment of its own;
    # either way no segment boundary may fall strictly inside it.
    full = f"일정 9/14(월) {text} 군무 연습 (이데알) 9/16(수) 특강"
    segments = _context_segments(full, P)
    assert len(segments) >= 2
    span = (full.index(text, 10), full.index(text, 10) + len(text))
    for _, start, end, _ in segments:
        assert not (start < span[0] < end < span[1]) and not (span[0] < start < span[1]), (text, segments)
    assert any(full[start:end].lstrip().startswith("9/16") for _, start, end, _ in segments)


# === 4. multi-program posts ================================================

def test_fixture_e_production_weekly_schedule_keeps_pm_and_picks_the_night():
    """Item 3132 as acquired: v0.96.1 read 9/14 08:00-11:00 (the rehearsal,
    cut inside its own clock). The post's milonga is 9/16 9:15-11:15pm."""
    ev = extract_single(GATO_WEEKLY_TITLE, GATO_WEEKLY_BODY, event_type="MILONGA_WITH_CLASS",
                        published=GATO_WEEKLY_PUBLISHED)
    assert (ev.date, ev.start_time, ev.end_time) == ("2026-09-16", "21:15", "23:15")
    time_evidence = next(e for e in ev.evidences if e.field == "time")
    assert time_evidence.inference == rules.EVIDENCE_EXPLICIT
    assert time_evidence.raw_text == "9:15~11:15pm"
    # Still one candidate for a person: the N:M contract is untouched.
    assert any(e.field == "context" and e.value == "MULTI_EVENT_CONTEXT" for e in ev.evidences)
    assert extract_schedule(GATO_WEEKLY_TITLE, GATO_WEEKLY_BODY, event_type="MILONGA_WITH_CLASS",
                            published=GATO_WEEKLY_PUBLISHED) is None
    result = process_discovered_post(Dummy(), _post(GATO_WEEKLY_TITLE, GATO_WEEKLY_BODY,
                                                    published=GATO_WEEKLY_PUBLISHED), "PRIMARY_COMMUNITY")
    assert result["classification"] == "MILONGA_WITH_CLASS"
    assert [(e.date, e.start_time, e.end_time) for e in result["events"]] == [("2026-09-16", "21:15", "23:15")]


def test_fixture_e_the_same_week_with_line_structure():
    ev = extract_single(WEEKLY_LINES_TITLE, WEEKLY_LINES_BODY, event_type="MILONGA",
                        published=GATO_WEEKLY_PUBLISHED)
    assert (ev.date, ev.start_time, ev.end_time, ev.venue) == ("2026-09-16", "21:15", "23:15", "아미고 스튜디오")
    assert any(e.field == "context" and e.value == "MULTI_EVENT_CONTEXT" for e in ev.evidences)
    # Every value came from the one segment - nothing crossed programs.
    assert len({e.context_id for e in ev.evidences if e.field in ("date", "time", "venue")}) == 1


@pytest.mark.parametrize("title, body, published, event_type, expected, flagged", MULTI_PROGRAM)
def test_no_multi_program_post_yields_a_fabricated_morning_or_a_lost_pm(
        title, body, published, event_type, expected, flagged):
    ev = extract_single(title, body, event_type=event_type, published=published)
    assert (ev.date, ev.start_time, ev.end_time) == expected
    assert any(e.field == "context" and e.value == "MULTI_EVENT_CONTEXT" for e in ev.evidences) is flagged


def test_the_segment_boundary_prefers_structural_anchors():
    # A bullet / list marker / bracket heading / date label that introduces
    # the next date starts its segment - the program's name goes with it.
    text = "1. 워크샵 9월 5일 15:00 장소: A 2. 밤 밀롱가 9월 6일 20:00"
    cut = _boundary_before(text, text.index("9월 5일") + 5, text.index("9월 6일"))
    assert text[cut:].startswith("2. 밤 밀롱가")
    text = "☆9/18(금) 창원 정모 벙개☆ ☆9/19(토) 대회☆"
    cut = _boundary_before(text, text.index("9/18") + 4, text.index("9/19"))
    assert text[cut:].startswith("☆9/19")
    text = "9/14 연습 20:00 [행사] 9/16 20:00"
    cut = _boundary_before(text, 4, text.index("9/16"))
    assert text[cut:].startswith("[행사]")
    text = "9/14 연습 20:00 일시: 9/16 20:00"
    cut = _boundary_before(text, 4, text.index("9/16"))
    assert text[cut:].startswith("일시:")
    # A line the date heads starts its segment; otherwise the last paragraph break.
    text = "9/14 연습\n20:00 아미고\n\n[쁘롱가]\n9/16 21:15"
    cut = _boundary_before(text, 4, text.index("9/16"))
    assert text[cut:] == "\n9/16 21:15"
    text = "9/14 연습\n20:00 아미고\n\n다음 특강 9/16 21:15"
    cut = _boundary_before(text, 4, text.index("9/16"))
    assert text[cut:] == "\n다음 특강 9/16 21:15"
    text = "9/14 연습\n20:00 아미고\n\n다음 주 화요일 저녁 특강은 9/16 21:15 부터"
    cut = _boundary_before(text, 4, text.index("9/16"))
    assert text[cut:] == "\n\n다음 주 화요일 저녁 특강은 9/16 21:15 부터"
    # A flat line with no anchor: the next program starts at its own date.
    text = "9/14(월) 8:00~11:00pm 군무 연습 (이데알) 9/16(수) 특강"
    cut = _boundary_before(text, 4, text.index("9/16"))
    assert text[:cut] == "9/14(월) 8:00~11:00pm 군무 연습 (이데알) "


def test_the_representative_segment_names_the_night_and_carries_a_clock():
    # No strict 밀롱가 word anywhere: v0.96.1 took the first program.
    ev = extract_single("10월 첫째주 일정",
                        "10/5(월) 8:00~11:00pm 군무 연습 (이데알) 10/7(수) 쁘롱가 9:15~11:15pm (아미고 큰홀) 10/9(금) 8시 개강",
                        event_type="MILONGA", published=date(2026, 10, 4))
    assert (ev.date, ev.start_time, ev.end_time) == ("2026-10-07", "21:15", "23:15")
    assert any(e.field == "context" and e.value == "MULTI_EVENT_CONTEXT" for e in ev.evidences)


def test_a_sources_own_event_term_guides_the_representative_segment():
    body = "9/21(월) 8:00~11:00pm 군무 연습 9/23(수) 열탱즐탱 9:15~11:15pm 아미고 스튜디오"
    plain = extract_single("주간 일정", body, event_type="MILONGA", published=date(2026, 9, 20))
    with_term = extract_single("주간 일정", body, event_type="MILONGA", published=date(2026, 9, 20),
                               event_terms=("열탱즐탱",))
    assert plain.date == "2026-09-21"        # nothing names the night: first program with a clock
    assert with_term.date == "2026-09-23"    # the source's own word does
    assert (with_term.start_time, with_term.end_time) == ("21:15", "23:15")
    assert any(e.value == "MULTI_EVENT_CONTEXT" for e in with_term.evidences if e.field == "context")


def test_a_class_word_across_a_bracket_heading_does_not_disown_the_nights_clock():
    reading = rules.parse_time_range("8:00~9:10pm 무료 특강 (아미고) [쁘롱가] 9:15~11:15pm (아미고 큰홀)", "MILONGA")
    assert (reading.start, reading.end) == ("21:15", "23:15")
    # ...while a class word on the same side still does.
    assert rules.parse_time_range("7:30-8:45pm 지노&유니 특강", "MILONGA") is None


# === 5. fixture F: schedule expansion is unchanged ==========================

def test_fixture_f_a_real_schedule_post_still_expands_to_n_candidates():
    post = _post("10월 소셜 일정",
                 "10/3 토 소셜 20:00 @ 스윙홀 / 10/10 토 소셜 20:00 @ 스윙홀 / 10/17 토 파티 20:00 @ 스윙홀")
    result = process_discovered_post(Dummy(), post, "PRIMARY_ORGANIZER")
    got = [(ev.date, ev.start_time, ev.venue) for ev in result["events"]]
    assert got == [("2026-10-03", "20:00", "스윙홀"), ("2026-10-10", "20:00", "스윙홀"),
                   ("2026-10-17", "20:00", "스윙홀")]
    for ev in result["events"]:
        assert any(e.field == "context" and e.value == "SCHEDULE_ITEM" for e in ev.evidences)


@pytest.mark.parametrize("title, body", [
    ("9/19 밀롱가", "9/19 저녁 8시 밀롱가 다음 밀롱가는 9/26 입니다"),
    ("9월 일정 안내", "9/19 소셜 20:00 / 9/26 강습 20:00"),
    ("9월 일정", "9/19 20:00 / 9/26 20:00"),
])
def test_the_expansion_criterion_is_not_loosened(title, body):
    assert extract_schedule(title, body, event_type="SOCIAL", published=P) is None
    assert len(process_discovered_post(Dummy(), _post(title, body), "PRIMARY_ORGANIZER")["events"]) <= 1


# === 6. before / after ======================================================

# What the v0.96.1 engine (Information Engine 0.89) made of exactly this
# fixture, captured with `engine/src` stashed. Hard-coded on purpose.
BEFORE = {
    "at_false_positives": 11, "at_valid_recall": 14,
    "multi_program_wrong": 5, "multi_program_fabricated_morning": 5, "pm_lost_in_segments": 5,
    "time_forms_ok": 9,
}


def _measure():
    counts = {key: 0 for key in BEFORE}
    for text in AT_NOT_A_VENUE:
        counts["at_false_positives"] += rules.extract_venue(text) is not None
    for text, expected in AT_VENUE:
        reading = rules.extract_venue(text)
        counts["at_valid_recall"] += reading is not None and reading.name == expected
    for title, body, published, event_type, expected, _flagged in MULTI_PROGRAM:
        ev = extract_single(title, body, event_type=event_type, published=published)
        counts["multi_program_wrong"] += (ev.date, ev.start_time, ev.end_time) != expected
        counts["multi_program_fabricated_morning"] += bool(ev.start_time and ev.start_time < "12:00")
        time_evidence = next((e for e in ev.evidences if e.field == "time"), None)
        counts["pm_lost_in_segments"] += bool(
            time_evidence and "pm" in body.lower() and time_evidence.inference != rules.EVIDENCE_EXPLICIT)
    for text, start, end in TIME_FORMS:
        reading = rules.parse_time_range(text) or rules.parse_start_time(text)
        counts["time_forms_ok"] += bool(reading and (reading.start, reading.end) == (start, end))
    return counts


def test_after_has_no_false_venue_no_wrong_program_and_full_recall():
    after = _measure()
    assert after["at_false_positives"] == 0 < BEFORE["at_false_positives"]
    assert after["at_valid_recall"] == len(AT_VENUE) > BEFORE["at_valid_recall"]
    assert after["multi_program_wrong"] == 0 < BEFORE["multi_program_wrong"]
    assert after["multi_program_fabricated_morning"] == 0 < BEFORE["multi_program_fabricated_morning"]
    assert after["pm_lost_in_segments"] == 0 < BEFORE["pm_lost_in_segments"]
    assert after["time_forms_ok"] == len(TIME_FORMS) == BEFORE["time_forms_ok"]
