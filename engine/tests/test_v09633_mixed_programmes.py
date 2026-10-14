# -*- coding: utf-8 -*-
"""v0.96.33: a week of classes with a night in it, and a time that stays home.

Two defects, and the corpus says they are not one defect:

    `live_pipeline` returned before any extractor ran whenever a post did not
    classify as an event. 가또땅고 publishes its whole week in one post - three
    Wednesday classes, then its own 쁘롱가 after them, a Thursday practica -
    and the post is a CLASS, which is true of the post and false of the 쁘롱가.
    Ten such posts are stored and not one produced an Event.

    `parse_time_range()` fell back to "the first reading carrying an am/pm
    marker" when nothing named the event type nearby. miltang.com renders
    Luminoso's Sunday milonga as `시간: 14:00~18:00` and then carries that
    organiser's whole weekly roundup as prose, where the Monday line's
    `7:30 PM – 11:30 PM` is the first marked reading - so seven Sunday events
    were stored as starting four and a half hours after they had finished.

One is a routing gate in `live_pipeline`, the other an evidence priority in
`extraction_rules`; neither change touches the other's code. Every body quoted
here is a real stored body (cafe.daum.net/GatotangO, miltang.com,
cafe.daum.net/sdamu, cafe.daum.net/clubelmar).
"""

from datetime import date

import pytest

from src import extraction_rules
from src.extractor import extract_programmes, extract_schedule, extract_single
from src.live_pipeline import EVENT_CLASSIFICATIONS

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
    "10/15(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica "
    "18일(일) 휴강 "
    "☆2026 순천 빅밀롱가 고고☆ 17일(토) 오전 8시 부산 서면 솔라리아 호텔 출발"
)
GATO_5906_PUBLISHED = date(2026, 10, 11)

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
    "10/11(일)_일빠 ① 3:00-4:00pm 수지's \"땅게라 클라스\" 2주차 "
    "② 4:10-5:20pm 소똥y수지's \"실전 중급\" 2주차 문의: 뮬란"
)
GATO_5691_PUBLISHED = date(2026, 10, 4)

# item 3178: its Thursday is written `7 /2(목)`, which the date matcher cannot
# read - so its practica has no date this post wrote, and is not claimed.
GATO_3178_TITLE = "[부산_탱고동호회]가또땅고 7월 첫째주 열탱즐탱 일정..."
GATO_3178 = (
    "6/30(월)_8:00~11:00pm 군무 전체 연습 (일빠) "
    "7/1(수)_8:00~9:10pm ① 소고귀ⓨ애비's 한곡완성반 1주차 (미오) "
    "② 지브릴's 솔로 트레이닝 1주차 (아미고 작은홀) "
    "③ 좐슨ⓨ버드's 초중급 3주차 (아미고 큰홀) "
    "[포트럭 쁘롱가] 9:15~11:15pm (DJ 데이브) "
    "7 /2(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica "
    "7 /5(일)_아미고 큰홀 ① 3:20-4:30pm 좐슨y버드's \"밀롱가 집중\" 4주차 "
    "② 4:40-5:50pm 소닉y블랑's \"땅고 중급 콤비네이션\" 3주차"
)
GATO_3178_PUBLISHED = date(2026, 6, 29)

# item 3157: its Wednesday is a typo, `8/126(수)`.
GATO_3157_TITLE = "[부산_탱고동호회]가또땅고 8월 넷째주 일정 안내..."
GATO_3157 = (
    "8/24(월) 8:00~11:00pm 군무 전체 연습 "
    "8/126(수)_8:00~9:10pm ① 좐슨ⓨ버드's 데뷰땅뜨 한곡완성반 5주차 (미오) "
    "② 펠릭스ⓨ듀니's 초급입문 1주차 (아미고 작은홀) "
    "[스페셜 밀롱가] 8:30~11:30pm (DJ MichaelTan, 아미고 큰홀) "
    "⚠️ 8/27(목)_ 쁘락 없음 ⚠️"
)
GATO_3157_PUBLISHED = date(2026, 8, 23)

LUMINOSO_SUNDAY = (
    "2026년 10월 18일 시간: 14:00~18:00 장소: Ocho (오초) "
    "(서울 마포구 월드컵북로2길 57 지하1층) 주최: Tress 반복: 매주 일요일 "
    "루미노소와 함께하는 한 주의 탱고 일정입니다. 월요일 밤의 따뜻한 만남부터, "
    "일요일 오후의 여유로운 춤, 그리고 매달 첫 번째 금요일의 특별한 밤까지. "
    "🖤 Monday Milonga 📍 En Paz 🕢 7:30 PM – 11:30 PM "
    "🌸 Sunday Milonga 📍 Tango Club Ocho 🕑 2:00 PM – 6:00 PM "
    "🦁 Luminoso Friday Milonga 📍 Andante 🕗 8:00 PM – 1:00 AM "
    "🧸 Luminoso Practica 📍 Studio Ocho 🕒 Every Wednesday & Friday "
    "3:00 PM – 6:00 PM"
)
LUMINOSO_MONDAY = (
    "2026년 10월 19일 시간: 19:30~23:30 장소: EN PAZ (엔빠스) "
    "(서초구 반포대로 30길 82 우서빌딩 B1. 엔빠스) 주최: Trees 반복: 매주 월요일 "
    "🖤 Monday Milonga 📍 En Paz 🕢 7:30 PM – 11:30 PM "
    "🌸 Sunday Milonga 📍 Tango Club Ocho 🕑 2:00 PM – 6:00 PM"
)
HALLOWEEN = (
    "🎃 2026 SDA X 라속 연합 HALLOWEEN PARTY 🎃 350~400명 규모의 대형 할로윈 "
    "파티가 찾아옵니다! 📌 파티 개요 일시: 2026년 10월 31일(토) 20:00 ~ 02:00 "
    "장소: 홍턴 (지하 1층 & 지하 2층) 오픈 강습: 주크 (꼬냥 & 인디) "
    "👻 할로윈 특별 이벤트 (지하 2층) 전문 분장사 운영: 오후 5시 ~ 8시 "
    "(코스튬 미준비자 현장 참여 OK!) 소셜 플로어 운영: 메인홀 9시 오픈"
)
# 엘마르's own poster labels the *workshop's* hour, not the social's.
ELMAR_POSTER = (
    "ELMAR LATIN NIGHT\n엘마르에서\nMUSIC | DANCE | DRINK | VIBES\n"
    "특별한 금요일 밤을 즐기자! Bh\nFRIDAY ©\n\nSOCIAL DAY\n"
    "© PM 9:00 ~ 11:30\nHDs 낼름\n\n 정모비 1만원 (1음료\n"
    "AS 뒤풀이 11시부터\n 포함)\n\nac Sas :\n\n"
    ": © 시간: PM 8:00 ~ 9:00\n> (we) 강습비 : 1만원 (정모비 별도)\n"
    ": QQ 소셜 타임 특강자 우선홀딩\n칸썸이 드디어 인천에!!\n"
    "SPECIAL\nLESSON        ®\n주제 : 최신 트렌디 센바 바차타"
)
GATO_TWO_NOTATIONS = (
    "두둥 ~ 8월 26일 수요일 * 날짜 : 08월 26일 수요일 "
    "* 일시 : 08시30분 - 11시30분 * 구성 : 4곡 1 Tanda "
    "* 장소 : 아미고 스튜디오(부산 서면 황제주차장2층) * D J : 마이클 탄 "
    "Wednesday, August 26th Time: 8:30 PM – 11:30 PM"
)


def _programmes(title, body, published):
    out = extract_programmes(title, body, published=published)
    return [(ev.date, ev.start_time, ev.end_time, ev.event_type) for ev in out or []]


# --- T1: the week with a night in it ---------------------------------------

def test_item_5906_yields_its_pronga_and_its_practica():
    """§35. The two programmes this post announces and nothing else."""
    assert _programmes(GATO_5906_TITLE, GATO_5906, GATO_5906_PUBLISHED) == [
        ("2026-10-14", "21:15", "23:15", "MILONGA"),
        ("2026-10-15", "20:00", "23:00", "PRACTICA"),
    ]


def test_item_5691_yields_all_four_of_its_nights():
    assert _programmes(GATO_5691_TITLE, GATO_5691, GATO_5691_PUBLISHED) == [
        ("2026-10-07", "21:15", "23:15", "MILONGA"),
        ("2026-10-08", "20:00", "23:00", "PRACTICA"),
        ("2026-10-09", "16:00", "19:00", "MILONGA"),
        ("2026-10-10", "19:00", "23:00", "MILONGA"),
    ]


def test_no_class_in_either_post_becomes_an_event():
    for title, body, published in (
            (GATO_5906_TITLE, GATO_5906, GATO_5906_PUBLISHED),
            (GATO_5691_TITLE, GATO_5691, GATO_5691_PUBLISHED)):
        for _d, start, _e, _t in _programmes(title, body, published):
            # Every class in these posts runs at 8:00pm or in the afternoon
            # behind a level and a week number; none of those hours is claimed.
            assert start not in ("20:00", "15:00", "16:10") or _t == "PRACTICA"


def test_a_cancelled_day_announces_nothing():
    assert all(d != "2026-10-18" for d, *_rest in _programmes(
        GATO_5906_TITLE, GATO_5906, GATO_5906_PUBLISHED))


def test_a_promotional_festival_mention_is_not_a_programme():
    """The 순천 빅밀롱가 link at the top of item 5906, and its bus times."""
    programmes = _programmes(GATO_5906_TITLE, GATO_5906, GATO_5906_PUBLISHED)
    assert all(start != "08:00" for _d, start, *_rest in programmes)
    assert len(programmes) == 2


def test_a_day_the_post_wrote_unreadably_is_not_dated_by_its_neighbour():
    """item 3178 writes its Thursday `7 /2(목)`; the practica is not claimed."""
    assert _programmes(GATO_3178_TITLE, GATO_3178, GATO_3178_PUBLISHED) == [
        ("2026-07-01", "21:15", "23:15", "MILONGA"),
    ]


def test_a_typo_in_a_day_header_costs_that_day_its_programme():
    """item 3157 writes `8/126(수)`; its 스페셜 밀롱가 is left unread rather
    than dated to the Monday above it."""
    assert _programmes(GATO_3157_TITLE, GATO_3157, GATO_3157_PUBLISHED) == []


def test_two_programmes_on_one_date_keep_their_own_hours():
    """§8/§14: the Wednesday class runs at 20:00 and the 쁘롱가 at 21:15."""
    programmes = _programmes(GATO_5906_TITLE, GATO_5906, GATO_5906_PUBLISHED)
    wednesday = [p for p in programmes if p[0] == "2026-10-14"]
    assert wednesday == [("2026-10-14", "21:15", "23:15", "MILONGA")]


def test_no_programme_borrows_the_next_days_hour():
    """§9: 10/14's programme does not take 10/15's clock, or the reverse."""
    programmes = _programmes(GATO_5906_TITLE, GATO_5906, GATO_5906_PUBLISHED)
    assert dict((d, s) for d, s, _e, _t in programmes) == {
        "2026-10-14": "21:15", "2026-10-15": "20:00"}


# --- T2: what the route refuses --------------------------------------------

@pytest.mark.parametrize("head,expected", [
    ("가또땅고 쁘롱가", True),
    ("포트럭 쁘롱가", True),
    ("자율연습 Practica", True),
    ("월간가또 밀롱가", True),
    ("스페셜 밀롱가", True),
    # A class is named by a level and a week number.
    ("넥스트스텝 4주차", False),
    ("초중급2 4주차", False),
    ("초급심화 1주차 종강", False),
    ("땅게라 클라스", False),
    ("밀롱가 집중 4주차", False),
    # A cancellation is not a night.
    ("휴강", False),
    ("쁘락 없음", False),
    # A field list is not a name.
    ("- D J : 스톤 Stone - 밀롱가 참가비 : 12,000원", False),
    # A quotation inside a head is quoting something else.
    ("좐슨y버드's \"밀롱가 집중\" 휴강", False),
    # Prose that merely mentions a milonga names no programme.
    ("밀롱가를 즐기기 위한 강습", False),
    ("밀롱가 음악 이해 수업", False),
    ("지난주 밀롱가 후기", False),
])
def test_a_head_is_a_name_or_it_is_nothing(head, expected):
    assert extraction_rules.head_names_a_programme(head) is expected


@pytest.mark.parametrize("head,kind", [
    ("가또땅고 쁘롱가", "MILONGA"),
    ("월간가또 밀롱가", "MILONGA"),
    ("자율연습 Practica", "PRACTICA"),
    ("쁘락띠까 (연습모임)", "PRACTICA"),
    ("금요 소셜데이", "SOCIAL"),
    ("할로윈 파티", "PARTY"),
    ("군무 연습", None),
])
def test_a_head_names_its_own_kind(head, kind):
    assert extraction_rules.programme_type(head) == kind


def test_a_post_whose_title_is_not_a_schedule_takes_no_route():
    assert extract_programmes(
        "가또땅고 155th 수요쁘롱가 with DJ BEAST",
        "10/7(수) [가또땅고 쁘롱가] 9:15~11:15pm 10/8(목) 8:00-11:00pm Practica",
        published=date(2026, 10, 2)) is None


def test_a_single_dated_post_takes_no_route():
    assert extract_programmes(
        "가또땅고 일정 안내",
        "10/7(수) [가또땅고 쁘롱가] 9:15~11:15pm",
        published=date(2026, 10, 2)) is None


def test_an_unmarked_hour_is_not_claimed():
    """item 3192's 쁘락띠까 writes `8:00-8:20` with no meridiem anywhere."""
    programmes = _programmes(
        "가또땅고 4월 둘째주 일정 안내",
        "4/8(수)_8:00~9:10pm ① 초급 1주차 [포트럭 쁘롱가] 9:15~11:15pm (DJ 찬비) "
        "4/9(목)_아미고 큰홀☆쁘락띠까(연습모임)☆ 8:00-8:20 가이드 with 소닉 "
        "8:20-11:00 자율연습 ",
        date(2026, 4, 5))
    assert programmes == [("2026-04-08", "21:15", "23:15", "MILONGA")]


def test_the_classification_vocabulary_is_untouched():
    """The route is additive: no post type was added to the event set."""
    assert EVENT_CLASSIFICATIONS == {
        "MILONGA", "MILONGA_WITH_CLASS", "SOCIAL", "SOCIAL_WITH_CLASS"}


def test_extract_schedule_still_declines_these_posts():
    """The existing route is unchanged; the new one is why they read at all."""
    for event_type in ("MILONGA", "PRACTICA", "CLASS", "SOCIAL"):
        assert extract_schedule(GATO_5906_TITLE, GATO_5906,
                                event_type=event_type,
                                published=GATO_5906_PUBLISHED) is None


# --- T3: a time that stays with its own programme --------------------------

def test_the_sunday_milonga_keeps_its_own_hours():
    """§11/§43-B. Its field says 14:00~18:00; the Monday line says 19:30."""
    reading = extraction_rules.parse_time_range(LUMINOSO_SUNDAY, "MILONGA")
    assert (reading.start, reading.end) == ("14:00", "18:00")


def test_the_monday_milonga_keeps_its_own_hours_too():
    reading = extraction_rules.parse_time_range(LUMINOSO_MONDAY, "MILONGA")
    assert (reading.start, reading.end) == ("19:30", "23:30")


def test_neither_luminoso_night_takes_the_others_clock():
    sunday = extraction_rules.parse_time_range(LUMINOSO_SUNDAY, "MILONGA")
    monday = extraction_rules.parse_time_range(LUMINOSO_MONDAY, "MILONGA")
    assert sunday.start != monday.start


def test_the_party_keeps_its_own_hours_and_not_the_makeup_stalls():
    reading = extraction_rules.parse_time_range(HALLOWEEN, "SOCIAL_WITH_CLASS")
    assert (reading.start, reading.end, reading.end_day_offset) == (
        "20:00", "02:00", 1)


def test_a_label_deeper_in_the_body_does_not_outrank_a_leading_reading():
    """엘마르's poster labels the workshop's hour; the social's has no label."""
    reading = extraction_rules.parse_time_range(ELMAR_POSTER, "SOCIAL_WITH_CLASS")
    assert (reading.start, reading.end) == ("21:00", "23:30")


def test_the_marked_notation_still_wins_inside_the_labelled_set():
    """가또 labels its own hour twice; `8:30 PM` is the right reading of both."""
    reading = extraction_rules.parse_time_range(GATO_TWO_NOTATIONS, "MILONGA")
    assert (reading.start, reading.end) == ("20:30", "23:30")


def test_a_named_range_still_beats_a_labelled_one():
    """v0.96.19's rule is first: the social runs at 20:00, not at 15:00."""
    body = ("워크샵 안내 시간: 15:00-16:30 발스윙 중고급 16:45-18:15 쉐그 초급 "
            "20:00-22:30 소셜")
    reading = extraction_rules.parse_time_range(body, "SOCIAL")
    assert reading.start == "20:00"


@pytest.mark.parametrize("body,event_type,expected", [
    # A bare clock with no meridiem anywhere is still left as written.
    ("시간: 5시30~9시30 밀롱가", "MILONGA", "05:30"),
    # A labelled range crossing midnight keeps its offset.
    ("일시: 21:00 ~ 01:00 장소: 홍턴 밀롱가", "MILONGA", "21:00"),
    # No label at all: today's behaviour, unchanged.
    ("밤 9시~11시 밀롱가", "MILONGA", "21:00"),
])
def test_the_bare_clock_contract_is_not_reverted(body, event_type, expected):
    reading = extraction_rules.parse_time_range(body, event_type)
    assert reading is not None and reading.start == expected


def test_a_single_event_post_is_unchanged():
    """item 5598, the one that already worked."""
    body = ("10월 7일 수요일 가또땅고 155th 수요쁘롱가 "
            "* 일시 : 밤 9시15분 - 11시15분 "
            "* 장소 : 아미고 스튜디오 (부산진구 서면 황제주차장, 부산진구 부전로 34) "
            "* D J : 비스트")
    ev = extract_single("가또땅고 155th 수요쁘롱가 with DJ BEAST", body,
                        event_type="MILONGA", published=date(2026, 10, 2))
    assert (ev.start_time, ev.end_time) == ("21:15", "23:15")
