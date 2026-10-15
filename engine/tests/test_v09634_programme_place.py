# -*- coding: utf-8 -*-
"""v0.96.34: where each recovered programme is held, and what its hour is worth.

v0.96.33 recovered 15 nights out of 가또땅고's weekly notices. Not one of them
carried a place: `extract_programmes()` asked `extract_venue()` for the day's
whole segment, and this board labels no place at all - it writes each
programme's room in the bracket beside its DJ, or in the day's own header.
Meanwhile the day's *classes* write their rooms in their own brackets -
`(미오)`, `(아미고 작은홀)`, `(일빠)` - so "a place somewhere in this day" would
have handed the milonga a classroom. Every rule here is anchored to one
programme for that reason.

The second half is about evidence rather than extraction: an hour written
`14:00` carries no PM marker and never needed one, and the engine already
records that as `ambiguous: False` beside the marker verdict. Only the marker
was ever read, so 659 of 711 ABSENT Events were reported as a time nobody had
confirmed. Every body quoted here is a real stored body
(cafe.daum.net/GatotangO, miltang.com).
"""

from datetime import date

import pytest

from src import extraction_rules
from src.extractor import extract_programmes

# --- real bodies ------------------------------------------------------------

GATO_5906_TITLE = "[부산_탱고동호회]가또땅고 10월 셋째주 일정_순천 빅..."
GATO_5906 = (
    "https://m.cafe.daum.net/GatotangO/Qbxu/957?svc=cafeapp "
    "[부산_탱고동호회]2026 순천 Big Bilonga 공동구매 및 버스 신청 안내 "
    "2026 Suncheon Big milonga ESTRELLAS 2026 순천 빅 밀롱가 ESTRELLAS "
    "매년 가을 땅고계의 추석이라 불리며 m.cafe.daum.net "
    "10/12(월) 8:00~11:00pm 군무 연습 "
    "10/14(수)_8:00~9:10pm ① 소고귀ⓨ애비's 넥스트스텝 4주차 (아미고 큰홀) "
    "② 데이브ⓨ지브릴's 초중급2 4주차 (일빠) "
    "③ 펠릭스ⓨ듀니's 초급심화 1주차 종강(미오) "
    "[가또땅고 쁘롱가] 9:15~11:15pm (DJ , 아미고 큰홀) "
    "10/15(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica 18일(일) 휴강 "
    "☆2026 순천 빅밀롱가 고고☆ 17일(토) 오전 8시 부산 서면 솔라리아 호텔 출발"
)

GATO_5691_TITLE = "[부산_탱고동호회]가또땅고 10월 둘째주 일정_금 와인..."
GATO_5691 = (
    "일욜 수업 없는 분들은, 놀러오셔요!!♡ 10/5(월) 8:00~11:00pm 군무 연습 쉼 "
    "10/7(수)_8:00~9:10pm ① 소고귀ⓨ애비's 넥스트스텝 3주차 (아미고 큰홀) "
    "② 데이브ⓨ지브릴's 초중급2 3주차 (일빠) "
    "③ 펠릭스ⓨ듀니's 초급입문 6주차 종강(미오) "
    "[가또땅고 쁘롱가] 9:15~11:15pm (DJ 비스트, 아미고 큰홀) "
    "10/8(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica "
    "10/9(금)_아미고 \"26-1기's 와인밀롱가\" 오후 4:00~7:00pm (DJ 데이브) "
    "10/10(토)_이데알 \"월간가또 밀롱가\" 7:00~11:00pm (DJ 정용이) "
    "☆☆☆소닉y블랑's 공연, 밤 9시☆☆☆ "
    "10/11(일)_일빠 ① 3:00-4:00pm 수지's \"땅게라 클라스\" 2주차 문의: 뮬란"
)

GATO_3192_TITLE = "[부산_탱고동호회]가또땅고 4월 둘째주 열탱즐탱 일정 안내"
GATO_3192 = (
    "4/6(월) 공연단 새 안무 자율연습 7:40-9:40pm_일빠 "
    "4/8(수)_8:00~9:10pm ① 소고귀ⓨ애비's 너튜브 시퀀스 1주차 (미오) "
    "② 지브릴's 땅게라 클라스 1주차 (아미고 작은홀) "
    "③ 좐슨ⓨ버드's 초급 1주차 (아미고 큰홀) "
    "[포트럭 쁘롱가] 9:15~11:15pm (DJ 찬비) "
    "4/9(목)_아미고 큰홀☆쁘락띠까(연습모임)☆ 8:00-8:20 가이드 with 소닉 "
    "4/10(금) 월간가또 밀롱가_아미고 큰홀 8:30pm-12:30am 밀롱가 (DJ 스톤) "
    "☆마라비샤 땅고웨어 및 슈즈 오픈마켓☆"
)

PUBLISHED_5906 = date(2026, 10, 10)
PUBLISHED_5691 = date(2026, 10, 4)
PUBLISHED_3192 = date(2026, 4, 5)


def programmes(title, body, published):
    out = extract_programmes(title, body, published=published)
    return {(ev.date, ev.start_time): ev for ev in (out or [])}


def venue_evidence(ev):
    return next((e for e in ev.evidences if e.field == "venue"), None)


def time_evidence(ev):
    return next((e for e in ev.evidences if e.field == "time"), None)


# --- the place a programme writes for itself --------------------------------


def test_the_milonga_takes_the_room_in_its_own_brackets():
    found = programmes(GATO_5906_TITLE, GATO_5906, PUBLISHED_5906)
    ev = found[("2026-10-14", "21:15")]
    assert ev.venue == "아미고 큰홀"
    assert venue_evidence(ev).raw_text == "(DJ , 아미고 큰홀)"


def test_the_practica_takes_the_room_in_its_days_header():
    found = programmes(GATO_5906_TITLE, GATO_5906, PUBLISHED_5906)
    ev = found[("2026-10-15", "20:00")]
    assert ev.venue == "아미고 큰홀"
    assert venue_evidence(ev).inference.endswith(
        extraction_rules.VENUE_LABEL_DAY_HEADER)


def test_the_dj_in_the_same_brackets_is_not_the_place():
    found = programmes(GATO_5691_TITLE, GATO_5691, PUBLISHED_5691)
    ev = found[("2026-10-07", "21:15")]
    assert ev.venue == "아미고 큰홀"
    assert "비스트" not in (ev.venue or "")


def test_a_bracket_naming_only_a_dj_leaves_the_place_absent():
    found = programmes(GATO_3192_TITLE, GATO_3192, PUBLISHED_3192)
    ev = found[("2026-04-08", "21:15")]
    assert ev.venue is None
    assert venue_evidence(ev) is None


def test_the_classes_three_rooms_are_never_lent_to_the_milonga():
    # The Wednesday segment holds (아미고 큰홀), (일빠) and (미오) for three
    # lessons. The night that follows them states its own room and takes that
    # one; on 3192 it states none and takes none.
    found = programmes(GATO_3192_TITLE, GATO_3192, PUBLISHED_3192)
    assert found[("2026-04-08", "21:15")].venue is None
    found = programmes(GATO_5691_TITLE, GATO_5691, PUBLISHED_5691)
    assert found[("2026-10-07", "21:15")].venue == "아미고 큰홀"


def test_a_quoted_programme_name_marks_the_token_before_it_as_the_place():
    found = programmes(GATO_5691_TITLE, GATO_5691, PUBLISHED_5691)
    assert found[("2026-10-09", "16:00")].venue == "아미고"
    assert found[("2026-10-10", "19:00")].venue == "이데알"


def test_each_day_keeps_its_own_place():
    found = programmes(GATO_5691_TITLE, GATO_5691, PUBLISHED_5691)
    assert found[("2026-10-09", "16:00")].venue == "아미고"
    assert found[("2026-10-10", "19:00")].venue == "이데알"
    assert found[("2026-10-08", "20:00")].venue == "아미고 큰홀"


def test_a_header_place_reaches_the_night_written_after_it():
    found = programmes(GATO_3192_TITLE, GATO_3192, PUBLISHED_3192)
    ev = found[("2026-04-10", "20:30")]
    assert ev.venue == "아미고 큰홀"


def test_a_labelled_field_still_wins_over_both_shortcuts():
    body = GATO_5906.replace(
        "[가또땅고 쁘롱가] 9:15~11:15pm (DJ , 아미고 큰홀)",
        "장소: 이데알 탱고 까페 [가또땅고 쁘롱가] 9:15~11:15pm (DJ , 아미고 큰홀)")
    found = programmes(GATO_5906_TITLE, body, PUBLISHED_5906)
    assert found[("2026-10-14", "21:15")].venue == "이데알 탱고 까페"


@pytest.mark.parametrize("bracket", [
    "(DJ 스톤)",
    "(70분)",
    "(예매X, 현장 결재)",
    "(DJ 스톤, 입장료 1만원)",
    "(문의: 뮬란, 오거나이저: 수지)",
    "(DJ 스톤, 큰홀)",
    "(DJ 스톤, 선배님은 쉽니다)",
])
def test_a_bracket_that_names_no_place_gives_none(bracket):
    body = GATO_5906.replace("(DJ , 아미고 큰홀)", bracket)
    found = programmes(GATO_5906_TITLE, body, PUBLISHED_5906)
    assert found[("2026-10-14", "21:15")].venue is None


@pytest.mark.parametrize("header", [
    "10/15(목)_할로윈 파티 8:00-11:00pm 자율연습 Practica",
    "10/15(목)_8:00-11:00pm 자율연습 Practica",
    "10/15(목)_초급심화 4주차 8:00-11:00pm 자율연습 Practica",
])
def test_a_header_that_names_no_place_gives_none(header):
    body = GATO_5906.replace(
        "10/15(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica", header)
    found = programmes(GATO_5906_TITLE, body, PUBLISHED_5906)
    ev = found.get(("2026-10-15", "20:00"))
    assert ev is not None
    assert ev.venue is None


def test_the_organisers_own_name_is_not_a_venue():
    # 가또땅고 동호회 팀 is who runs the night and names no room: more than one
    # word, and not one of them a venue word.
    body = GATO_5906.replace("(DJ , 아미고 큰홀)", "(DJ , 가또땅고 동호회 팀)")
    found = programmes(GATO_5906_TITLE, body, PUBLISHED_5906)
    assert found[("2026-10-14", "21:15")].venue is None


def test_the_day_before_the_header_rule_is_still_read_by_v0960s_own_rule():
    # A space where this board writes "_" is the shape v0.96.0 already reads
    # ("<name ending in a venue word> <clock>"), and it keeps reading it: this
    # release adds the separator, it does not take the existing form away.
    body = GATO_5906.replace(
        "10/15(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica",
        "10/15(목) 아미고 큰홀 8:00-11:00pm 자율연습 Practica")
    found = programmes(GATO_5906_TITLE, body, PUBLISHED_5906)
    ev = found[("2026-10-15", "20:00")]
    assert ev.venue == "아미고 큰홀"
    assert venue_evidence(ev).inference.endswith(
        extraction_rules.VENUE_LABEL_SUFFIX)


def test_a_room_word_on_its_own_is_not_a_place():
    assert extraction_rules.programme_place("x 9:15pm (DJ 롭로이, 큰홀)",
                                            2, 8, "쁘롱가") is None
    assert extraction_rules.programme_place("x 9:15pm (DJ 롭로이, 지하1층)",
                                            2, 8, "쁘롱가") is None


def test_the_place_is_offered_to_the_venue_master_by_its_own_spellings():
    found = programmes(GATO_5906_TITLE, GATO_5906, PUBLISHED_5906)
    evidence = venue_evidence(found[("2026-10-14", "21:15")])
    assert evidence.value["alias_candidates"][0] == "아미고 큰홀"


def test_the_shortcut_labels_are_not_trusted_on_a_poster():
    assert extraction_rules.VENUE_LABEL_PROGRAMME \
        in extraction_rules.VENUE_SHORTCUT_LABELS
    assert extraction_rules.VENUE_LABEL_DAY_HEADER \
        in extraction_rules.VENUE_SHORTCUT_LABELS


# --- v0.96.33's results must not move ---------------------------------------


def test_every_date_and_hour_v09633_recovered_is_unchanged():
    found = programmes(GATO_5906_TITLE, GATO_5906, PUBLISHED_5906)
    assert sorted(found) == [("2026-10-14", "21:15"), ("2026-10-15", "20:00")]
    assert found[("2026-10-14", "21:15")].end_time == "23:15"
    assert found[("2026-10-14", "21:15")].event_type == "MILONGA"
    assert found[("2026-10-15", "20:00")].end_time == "23:00"
    assert found[("2026-10-15", "20:00")].event_type == "PRACTICA"
    found = programmes(GATO_5691_TITLE, GATO_5691, PUBLISHED_5691)
    assert sorted(found) == [("2026-10-07", "21:15"), ("2026-10-08", "20:00"),
                             ("2026-10-09", "16:00"), ("2026-10-10", "19:00")]


def test_a_cancelled_sunday_and_a_festival_link_still_make_no_event():
    found = programmes(GATO_5906_TITLE, GATO_5906, PUBLISHED_5906)
    assert all("휴강" not in ev.name for ev in found.values())
    assert all("순천" not in (ev.venue or "") for ev in found.values())
    assert not any(ev.date == "2026-10-18" for ev in found.values())


# --- the hour's own evidence -------------------------------------------------


def test_a_programme_carries_the_same_time_evidence_as_every_other_route():
    found = programmes(GATO_5906_TITLE, GATO_5906, PUBLISHED_5906)
    for ev in found.values():
        evidence = time_evidence(ev)
        assert evidence is not None
        assert evidence.inference == extraction_rules.EVIDENCE_EXPLICIT
        assert evidence.value["ambiguous"] is False
        assert evidence.value["start"] == ev.start_time


@pytest.mark.parametrize("text,evidence,ambiguous", [
    # The hour has only one reading: 14 o'clock is not 2 in the morning.
    ("일시: 2026년 10월 18일 시간: 14:00~18:00", "ABSENT", False),
    ("일시: 10월 31일(토) 20:00 ~ 02:00", "ABSENT", False),
    ("19:30~23:30", "ABSENT", False),
    # The hour could be either half of the day and nothing says which.
    ("9:15~11:15", "ABSENT", True),
    ("8:00-8:20", "ABSENT", True),
    ("7:00~11:00", "ABSENT", True),
    # The post said which half.
    ("9:15~11:15pm", "EXPLICIT", False),
    ("오후 4:00~7:00pm", "EXPLICIT", False),
])
def test_the_engine_already_knows_which_hours_need_no_marker(text, evidence,
                                                             ambiguous):
    reading = extraction_rules.parse_time_range(text)
    assert reading is not None
    assert reading.meridiem_evidence == evidence
    assert reading.ambiguous is ambiguous
    assert reading.as_dict()["ambiguous"] is ambiguous
