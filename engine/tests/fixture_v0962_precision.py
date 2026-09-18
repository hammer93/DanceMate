"""v0.96.2 before/after fixture: the two Production misreads and their kin.

v0.96.0 went to Production and a read-only pass over 182 fetched
direct-source bodies found exactly two kinds of wrong reading, both here in
their real structure:

* an "@" that is a person or an account, read as the venue - "루 @ 선배님 은
  밀롱가에 살다시피 하신다 했다" (a nickname addressing a senior; item 2020),
  "인스타그램 DM: @intothelatinittl º 카카오톡 ID: ..." (a contact line;
  item 2296);
* a flat weekly schedule ("9월 둘째주 열탱즐탱 일정", item 3132) whose first
  program was cut inside its own clock - "8:00~11:00" | "pm" - and read as a
  08:00-11:00 morning rehearsal, when the post's milonga was 9/16 9:15-11:15pm.

The schedule body is the Production text as acquired (one flat line, links
kept, the phone number already redacted by acquisition); the messenger ID
that followed the Instagram handle is replaced, since it is a person's
contact, not part of the shape. Everything else is a *form*, not a copy.

Each AT_* entry: (text, expected venue name or None).
Each MULTI_PROGRAM entry: (title, body, published, event_type, expected
(date, start, end), flagged) - every one stays a single candidate; `flagged`
says whether it is ambiguous (MULTI_EVENT_CONTEXT) or one program alone
names the night.
"""

from datetime import date

# --- A. "@" that is not a place ---------------------------------------------

AT_NOT_A_VENUE = [
    # Production item 2020: a nickname, then "@ 선배님" - a person.
    "루 @ 선배님 은 밀롱가에 살다시피 하신다 했다",
    "@ 선배님 은 이번 행사에 꼭 오세요",
    # Production item 2296: a contact line - an Instagram handle, then a
    # messenger ID (replaced) - read as "intothelatinittl º 카카오톡".
    "📞 문의 º 인스타그램 DM: @intothelatinittl º 카카오톡 ID: latin_manager (매니저)",
    "문의 @intothelatinittl º 카카오톡",
    "문의 : 인스타그램 @intothelatinittl 카 카 오 톡 latin_manager 스파이더맨(매니저)",
    "@ 형님 감사합니다",
    "@ 회원님들 안녕하세요",
    "@ 쌤 감사합니다",
    "@ 강사님 께 문의",
    "@dance_account 인스타 팔로우",
    "인스타 @swing_daily 팔로우",
    "카카오톡 ID: @홍길동",
    "@test@example.com",
    "@ 이번주는 쉽니다",
    "@ 메인홀",
    "at 8pm",
]

# --- B. "@" that is a place (name expected) --------------------------------

AT_VENUE = [
    ("9월 24일 저녁 8시\n@오초", "오초"),
    ("9월 16일 9:15-11:15pm\n@ 아미고 스튜디오", "아미고 스튜디오"),
    ("매주 화요일 저녁 8시부터 밀롱가 @ 오초", "오초"),
    ("20:00 @스튜디오 오초", "스튜디오 오초"),
    ("저녁 8시 @ 신천 비바스윙", "신천 비바스윙"),
    ("@ 이데알 탱고 까페 19:00", "이데알 탱고 까페"),
    ("19:30 @ 라 비다 입장료 13,000원", "라 비다"),
    ("매월 마지막 금요일 20:00-24:00 @ 루나 탱고바", "루나 탱고바"),
    ("20시 @ 홍대 스윙바", "홍대 스윙바"),
    ("@ 올어바웃스윙 홀 오후 6시", "올어바웃스윙 홀"),
    ("8pm at Studio Ocho", "Studio Ocho"),
    ("@ 아미고 큰홀 9:15-11:15pm", "아미고 큰홀"),
    ("오후 3시부터 6시까지 @ 오초 스튜디오", "오초 스튜디오"),
    ("21:00-01:00 @ 살루드 입장료 10,000원", "살루드"),
    ("@ 오초 에서 만나요", "오초"),
]

# --- C. multi-program posts --------------------------------------------------

# Production item 3132, published 2026-09-13, as acquired (flat, links kept).
GATO_WEEKLY_TITLE = "[부산_탱고동호회]가또땅고 9월 둘째주 열탱즐탱 일정..."
GATO_WEEKLY_BODY = (
    "9/14(월) 8:00~11:00pm 군무 연습 (이데알) 9/16(수)_8:00~9:10pm ① 무료 일일 특강 "
    "소고귀ⓨ애비's 좁은공간 테크닉 (아미고 큰홀) ② 펠릭스ⓨ듀니's 초급입문 4주차 (미오) "
    "[가또땅고 쁘롱가] 9:15~11:15pm (DJ 알루, 아미고 큰홀) "
    "https://m.cafe.daum.net/GatotangO/UvT8/245?svc=cafeapp 가또땅고 152번째 수요뿌롱가 with DJ chanbee "
    "여기를 눌러 링크를 확인하세요 m.cafe.daum.net "
    "9/17(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica (초급 원데이클라스) "
    "☆9/18(금) 창원 헨땅 정모 벙개☆ ☆9/19(토)다리엔소컵 대회 in 서울☆ ☆9/23(수) 8시 개강☆ "
    "1. 데이브y지브릴's \"초중급2\" 2. 소고귀y애비's \"넥스트 스텝 트레이닝\" "
    "https://m.cafe.daum.net/GatotangO/Tw3F/137?svc=cafeapp [부산 가또땅고] 초중급2 클래스 6주과정 개강 및 신청안내 "
    "안녕하세요. 데이브, 지브릴입니다.이번 9월23일부터 6주간 초중급2 클래스를 운영합니다. "
    "땅고 중급으로 나아갈 수 있는 기초와 원리 등을 풍부하게 준비했습니다.또한 유용한 시퀀스들도 많이 m.cafe.daum.net "
    "https://m.cafe.daum.net/GatotangO/Qbxu/979?svc=cafeapp [부산_탱고동호회]가또땅고 무료 특강 +정규 클라스 + 스페셜 집중 워크샵까지!! "
    "슬프게도 훌리안 y 나탈리아 부산 일정이 모두 취소되어.. 죄송스런 마음에 9/16(수) 무료 특강을 준비했습니다. "
    "많은 분들이 오셔서 소고귀y애비 두 분의 특강도 듣고 쁘롱가도 함께 즐겨주시기 m.cafe.daum.net 문의: [전화번호] (뮬란)"
)
GATO_WEEKLY_PUBLISHED = date(2026, 9, 13)

# The same week written with line structure (the shape the task describes).
WEEKLY_LINES_TITLE = "9월 둘째주 열탱즐탱 일정"
WEEKLY_LINES_BODY = """9/14 (월) 군무 연습
8시-11시 아미고 스튜디오
연습 참여 부탁드립니다

9/16 (수) 특강
오후 8시 초급 특강
장소: 아미고 스튜디오

[가또땅고 쁘롱가]
9:15-11:15pm
@ 아미고 스튜디오
DJ 하나"""

MULTI_PROGRAM = [
    (GATO_WEEKLY_TITLE, GATO_WEEKLY_BODY, GATO_WEEKLY_PUBLISHED, "MILONGA_WITH_CLASS",
     ("2026-09-16", "21:15", "23:15"), True),
    (WEEKLY_LINES_TITLE, WEEKLY_LINES_BODY, GATO_WEEKLY_PUBLISHED, "MILONGA",
     ("2026-09-16", "21:15", "23:15"), True),
    # A flat line where the old midpoint fell inside the first program's clock.
    ("9월 셋째주 열탱즐탱 일정",
     "9/21(월) 8:00~11:00pm 군무 연습 (이데알) 9/23(수) 8:00~9:10pm 무료 특강 (아미고) [쁘롱가] 9:15~11:15pm (아미고 큰홀)",
     date(2026, 9, 20), "MILONGA", ("2026-09-23", "21:15", "23:15"), True),
    # ...and one where it fell inside the second program's clock. Only one
    # program says 밀롱가, so this one is not ambiguous - but v0.96.1 still
    # read 09:15 with no end off the cut token.
    ("주간 일정 안내",
     "9/21(월) 연습 9/23(수) 밀롱가 9:15~11:15pm 아미고 스튜디오 신청은 9/22 까지 문의 9/25 이후",
     date(2026, 9, 20), "MILONGA", ("2026-09-23", "21:15", "23:15"), False),
    # A rehearsal first, the night second, both with pm clocks and no scene word in the night's own words.
    ("10월 첫째주 일정",
     "10/5(월) 8:00~11:00pm 군무 연습 (이데알) 10/7(수) 쁘롱가 9:15~11:15pm (아미고 큰홀) 10/9(금) 8시 개강",
     date(2026, 10, 4), "MILONGA", ("2026-10-07", "21:15", "23:15"), True),
]

# --- D. pm / am preservation -------------------------------------------------

TIME_FORMS = [
    ("9:15-11:15pm", "21:15", "23:15"),
    ("9:15pm-11:15pm", "21:15", "23:15"),
    ("7:30pm", "19:30", None),
    ("8pm", "20:00", None),
    ("8시pm", "20:00", None),
    ("저녁 8시", "20:00", None),
    ("8:00~11:00pm", "20:00", "23:00"),
    ("오후 7시 ~ 11시", "19:00", "23:00"),
    ("19:00-22:00", "19:00", "22:00"),
]
