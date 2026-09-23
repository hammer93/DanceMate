"""v0.96.11 Production regression set: somebody's month abroad, on display
as Korean dance nights.

A post can carry a date, a time and every dance word in the language and
still not be an announcement. ``is_non_event_notice()`` has refused a
heading that calls itself a recap since v0.96.0 and one that calls itself an
administrative notice since the same release; three more shapes reach a
reader through the gap between them.

Measured read-only on Production 0ee6a9d / 0.96.10 / engine 0.96, fully
converged (re-extract current 2,351, outdated 0, stalled 0, failed 0;
normalization remaining 0, FAILED 0; 738 events, 661 visible, 143 public
upcoming), over all 2,351 collected items, each classified the way the
runtime classifies it - its own ``known_event_type`` and
``source_category``, its source's Settings event terms, and the title and
body ``engine_ingest._to_raw_post()`` would hand the engine.

**One of the eight is upcoming**: item 2034, dated 2026-10-01, a note whose
whole subject is that its writer has come home from two months in Vietnam.

**The three shapes, and why each is written the way it is.**

* **A trip counts its own days.** "🇦🇷아르헨티나 29일차 (9월 2일ㆍ수)" is day
  29 of a month in Buenos Aires; the date in the bracket is the day being
  written about, not a day anyone can turn up to. Never admitted on the
  number alone - a multi-day event could count its days too - so the arm
  steps aside whenever the same heading names a night.
* **Somebody says where they have been.** 귀국했, beside the 다녀왔 that has
  been in the recap half since v0.96.0, and conjugated for the same reason:
  the bare noun would also take "귀국 환영 밀롱가", which is a night for the
  person who came home.
* **A club asks for sponsorship.** "협찬 공지의 건" is a solicitation with a
  deadline, in the same family as the 가입 안내 / 신청 마감 / 경품 / 추첨
  already in the administrative half. The shape, not the word: "협찬사 감사
  파티" is a night thanking its sponsors.

**Two measured tokens were deliberately left out**, and ``STILL_PROSE``
below holds what that costs. See the test module for the evidence.

Each entry is ``(ref, title)``. These arms read the title and nothing else,
so no body is stored for them; titles are kept exactly as Production stores
them, truncation and all, because a truncated title is what the classifier
actually reads.
"""

# --- A. A trip counting its own days --------------------------------------
#
# Seven titles in the stored corpus, six of them carrying a visible events
# row dated across August and September 2026 - Korean dates, for days spent
# in Argentina. The seventh (item 204) already produced no event and is here
# so the rule is asserted on the whole family rather than only on the part
# that happened to break through.
TRIP_DIARY = [
    (198, "🇦🇷아르헨티나 29일차 (9월 2일ㆍ수)"),
    (200, "🇦🇷아르헨티나 27일차(8월 31일ㆍ월)"),
    (201, "🇦🇷아르헨티나 26일차 (8월 30일ㆍ일)"),
    (202, "🇦🇷아르헨티나 25일차 (8월 30일ㆍ토)"),
    (203, "🇦🇷아르헨티나 24일차 (8월 28일ㆍ금)"),
    (204, "🇦🇷아르헨티나 21일차 (8월25일ㆍ화)"),
    (1922, "🇦🇷 아르헨티나 30일차 ·(9월 3일 목요일)ㆍ9월5..."),
]

# --- B. Somebody saying where they have been ------------------------------
#
# The hard gate. Public upcoming on Production when this was measured, dated
# 2026-10-01 because the body mentions a Saigon tango marathon the writer
# went to, not one anybody here can attend.
CAME_HOME = [
    (2034, "초급발표회 준비로 베트남에서 귀국했습니다"),
]

# --- C. A club asking for sponsorship -------------------------------------
CALLS_FOR_SPONSORSHIP = [
    (2009, "「우리SAI 142기 초급발표회 협찬 공지의 건"),
]

# --- D. What a bare-noun token would take with it -------------------------
#
# Every title here is a real night, and every one of them would be refused
# outright by a token this release considered and rejected. They are the
# reason 풍경 and 어나운스 are not in the guard: 102 of Production's 143
# public upcoming events carry a heading that is a bare name with no digits
# in it - "cabeceo", "이뚜밀", "La Noche", "Sueño Dulce" - and 81 of those
# are events only because their collector's own prior says so, a prior this
# guard is asked *above* since v0.96.8. A bare noun in here does not merely
# risk a false refusal; it overrules the one signal that knows better.
BARE_NAME_NIGHTS = [
    (2795, "디디디"),
    (2804, "cabeceo"),
    (2806, "Sueño Dulce"),
    (2810, "이뚜밀"),
    (2808, "La Noche"),
]

# --- E. Left unfixed, on purpose ------------------------------------------
#
# Four of the sixteen prose false positives the v0.96.11 audit counted. No
# arm in this release reaches them and none should be invented to:
#
#   3194  "[2026.03.25] 쁘롱가 풍경"    - 풍경 is a scenery noun and a
#         plausible name for a night; the corpus uses it inside a cultural
#         event's own proper name ("문화의 숲길 - 풍경")
#   3160  "... 주년파티 뮬매 어나운스"  - 어나운스 is what this scene calls
#         the announcement segment *of* a milonga; item 4, a real La Vida
#         night, announces its own "매니저님 어나운스 타임에 무료입장권 및
#         와인 추첨 이벤트가 있습니다"
#   3161  "...4주년 생일파티 포토s"      - 포토 takes 포토파티, a real party
#   3214  "...3주년 생일파티, 축하해주셔서" - no measured title signal at all
#
# Each is past-dated and none is on public display as somewhere to go
# tonight. A release that removed them would have to guess.
STILL_PROSE = [
    (3194, "[2026.03.25] 쁘롱가 풍경"),
    (3160, "흥분해서 제대로 전달 못한, 주년파티 뮬매 어나운스..."),
    (3161, "탱고동호회]2026.8.16.가또땅고 4주년 생일파티 포토s..."),
    (3214, "[부산_가또땅고]2025년 3주년 생일파티, 축하해주셔서..."),
]

# --- F. Shapes the trip-day arm must step aside for -----------------------
#
# No festival in the stored corpus numbers a day this way - all 34 festival
# and marathon titles use the festival's own name, a date range or a
# countdown - so these are written rather than taken from Production, and
# they are the whole reason the arm asks a second question.
A_DAY_OF_SOMETHING_REAL = [
    "춘천탱고마라톤 2일차 밀롱가",
    "BSBF 2일차 소셜 파티",
    "부산 페스티벌 3일차 정모",
    "K-TANGO 1일차 그랜드 밀롱가",
]

# Headings the two new words must not take, for the same reason the words
# are conjugated and phrased the way they are.
NOT_TAKEN_BY_THE_NEW_WORDS = [
    "귀국 환영 밀롱가",
    "우노 귀국 파티 10월 1일",
    "협찬사 감사 파티",
    "협찬해주신 분들과 함께하는 정모",
]
