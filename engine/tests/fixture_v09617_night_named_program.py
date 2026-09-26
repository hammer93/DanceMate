"""v0.96.17: a dated program that calls itself NIGHT / 나이트.

A schedule post that details each of its days names the night on each day's own
line, and one venue's regular Saturday is written `LATIN NIGHT` and nothing
else. 홍턴's 추석 run lists four days - 바차타 파티, 키좀바 파티, 살사데이, and
"추석 이벤트 LATIN NIGHT ... DJ RICKY와 함께하는 신나는 토요일 밤 ... 오픈
오후 9시" - and only the fourth failed to name itself in a word the
dated-program vocabulary knew. Production held that four-night run as **one**
event, and on the wrong hour: 19:00, which is the 23rd's first workshop, priced
20,000원, which is the 23rd's ticket.

**The vocabulary is added in one place only.** `DATED_PROGRAM_WORDS` is a third
mapping beside `EVENT_WORDS` and `EVENT_CONTEXT_WORDS`, read by
`extract_schedule()` and `extract_day_list()` and nothing else. `EVENT_WORDS`
still answers its four other questions untouched - which clock range is the
event's time, which lone clock is its start, which price is its fee, and which
segment of an ambiguous post is the reviewed candidate. Measured over the whole
stored corpus, widening `EVENT_WORDS` globally happens to change the same single
item today; the four behaviours it also governs would be permanently looser for
no measured gain.

**What actually protects the negatives is not the pattern, and the tests say
so.** Measured over all 2,489 stored items, 19 carry a word-boundary NIGHT or a
나이트:

* 342 `DJ MAX 살사나이트 IN 원주 … 후기` - a recap. Classifies OTHER.
* 2417 `방콕 탱고 밀롱가, 나이트 호텔과헤밍웨이 레스토랑` - a travel blog, and
  `나이트 호텔` is the name of a **hotel**. The pattern matches that string; what
  keeps it out is that the post carries no date at all.
* 3778 `MAX NIGHT Free Salsa On1 Class` - filed EVENT by the source and still a
  free class. Classifies CLASS.
* 3803 `LATIN NIGHTS` - body is `BACHATA WORKSHOP - 8:00 PM 9:00 PM`.
  Classifies CLASS, and `NIGHTS` is outside the word boundary anyway.
* the remaining 14 already hold their events, because they also say 소셜, 파티,
  Social or 정모.

That is why the broad alternative was rejected: adding the same words to the
classifier's own night vocabulary turns 3778 and 3803 from CLASS into events -
two false positives - and buys nothing, because 홍턴's miss was never a
classification miss.

Each entry is ``(ref, title, body, expected)`` where ``ref`` is the danceinfo
lesson id where there is one, or the Production ``source_item_id`` otherwise.
Bodies are the real stored text unless a comment says the entry is constructed.
"""

SOCIAL = "SOCIAL_WITH_CLASS"

# --- A. the run this release restores --------------------------------------

# Verified against the live payload on 2026-09-27: eventDays is still
# 2026-09-23,2026-09-24,2026-09-25,2026-09-26 and every one of those four days
# has its own programme in the body. Three of them already named themselves
# 파티 / 살사데이; the 26th says LATIN NIGHT.
HONGTURN = (
    4324,
    "홍턴 추석 연휴 수~토요일 스페셜 이벤트!",
    "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25,2026-09-26 "
    "일정정보 7:00 PM, 8:00 PM 장소 홍턴 DJ DJ 쿵 강의 소개 "
    "🌕 홍턴 추석 연휴 수~토요일 스페셜 이벤트! 🍁 "
    "이번 추석 연휴, 홍턴에서 살사·바차타·키좀바와 함께 특별한 4일을 즐겨보세요! "
    "💗 9월 23일(수) | 홍턴 바차타 파티 바차타 4 : 살사 2 "
    "오후 7시 제니 y 뚜부 — 바로 활용 가능한 센슈얼바차타 응용패턴 "
    "오후 8시 뽀대용수 y 밀라 — 최신트렌드 바차타 패턴 소셜 오픈 오후 9시 / DJ 쿵 "
    "워크샵 2개+소셜 20,000원(예매) / 25,000원(현매) 소셜 12,000원 "
    "🌙 9월 24일(목) | 추석 올 키좀바 파티 키좀바의 매력에 빠지는 특별한 밤! "
    "오후 6시 재좀바 & 샤나 — 키좀바의 매력 "
    "오후 7시 스타샷 y 수정 — THE AXIS & 3 CONNECTIONS 클럽 오픈 오후 8시 "
    "DJ BLD & DJ 나리 워크샵+소셜 20,000원 / 소셜 12,000원 "
    "🔥 9월 25일(금) | 추석 살사데이 라틴으로 더 풍성한 한가위! "
    "오후 7시 핸슨 — 핸슨살사 샤이닝 샤인~ 핸슨과 함께 빛나는 샤인 "
    "오후 8시 백호 y 몽 — Salsa shine with music 클럽 오픈 오후 9시 / DJ 헤이즐 "
    "워크샵+소셜 20,000원 / 소셜 12,000원 "
    "🎉 9월 26일(토) | 추석 이벤트 LATIN NIGHT "
    "살사 ON1·ON2, 바차타, 메렝게, 레게톤, 클럽뮤직, 라인댄스, 차차까지! "
    "DJ RICKY와 함께하는 신나는 토요일 밤 🎧 오픈 오후 9시 "
    "“뻔한 토요일은 가라!” 춤신춤왕들의 성지, 홍턴 오픈! "
    "토요일 라틴펍 홍턴에서 연휴의 마지막을 신나게 즐겨보세요. "
    "📍 홍턴 라틴클럽 | 마포구 동교로 207 현우빌딩 B1",
)
HONGTURN_DATES = {"2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26"}
# The 26th's own line says 오픈 오후 9시 and carries no price. Before this
# release the single candidate took the 23rd's first workshop hour and the
# 23rd's ticket, so both of these are corrections, not new readings.
HONGTURN_26_START = "21:00"
HONGTURN_26_FEE = None

# Both spellings of the same thing, on the same shape. Constructed - the corpus
# writes `LATIN NIGHT` in Latin script and `바차타나이트` as a compound, and
# these put each of those where a dated programme names itself.
NIGHT_NAMED_PROGRAMS = [
    (
        "LATIN NIGHT, Latin script",
        "홍대 주말 라틴",
        "2026-11-06 전체일정 2026-11-06,2026-11-07 일정정보 9:00 PM 장소 홍턴 "
        "강의 소개 11월 6일(금) | 금요 LATIN NIGHT 오픈 오후 9시 DJ 쿵 "
        "11월 7일(토) | 토요 LATIN NIGHT 오픈 오후 9시 DJ RICKY",
        {"2026-11-06", "2026-11-07"},
    ),
    (
        "나이트 as a Korean compound",
        "라틴크루즈 주말 안내",
        "2026-11-06 전체일정 2026-11-06,2026-11-07 일정정보 9:00 PM 장소 야만 "
        "강의 소개 11월 6일(금) 금요 바차타나이트 오픈 오후 9시 "
        "11월 7일(토) 토요 바차타나이트 오픈 오후 9시",
        {"2026-11-06", "2026-11-07"},
    ),
    (
        "lower and mixed case",
        "Weekend Latin",
        "2026-11-06 전체일정 2026-11-06,2026-11-07 일정정보 9:00 PM 장소 강턴 "
        "강의 소개 11월 6일(금) Friday latin night open 9 PM "
        "11월 7일(토) Saturday Latin Night open 9 PM",
        {"2026-11-06", "2026-11-07"},
    ),
]

# --- B. the word must be the word -----------------------------------------
#
# Every one of these strings is in the stored corpus. None of them is a dated
# programme naming itself, and the boundary on the Latin half is what keeps
# them out. `party` already matched `#MidsummerNightLatinTangoParty` before
# this release, so that one is listed as matching for a reason that is not ours.
NOT_THE_WORD = [
    ("midnight", "fee before midnight on October 15", False),
    ("a hashtag run together", "#everysaturdaynightmilonga #seoulmilonga", False),
    ("the plural, whose only instance is a workshop body", "LATIN NIGHTS", False),
    ("nightlife, which §6 forbids and the corpus never writes", "nightlife", False),
]
ALREADY_MATCHED_BY_PARTY = "#MidsummerNightLatinTangoParty"

# The Korean half carries no boundary, because Korean compounds have none.
# 바차타나이트 and 살사나이트 are how a night is written - and the same
# permissiveness matches a Bangkok hotel, which is why the tests check what
# really keeps that post out.
KOREAN_COMPOUNDS = ["바차타나이트", "살사나이트", "라틴 나이트"]
KOREAN_FALSE_FRIEND = "나이트 호텔"

# --- C. the negatives, with the mechanism that actually stops each ---------

# A recap of a night that already happened. The body is the blog's own title
# and nothing else, which is the whole post: no date, no programme.
RECAP = (
    342,
    "DJ MAX 살사나이트 IN 원주 │원주살사 노리터 후기, 음악과 사람들이 ....",
    "이네스(Ines)의 Salsa & the city : 네이버 블로그",
)
# A travel blog. `나이트 호텔` is a hotel in Bangkok. The vocabulary matches
# that string; what keeps the post out is that it names no day.
TRAVEL = (
    2417,
    "방콕 탱고 밀롱가, 나이트 호텔과헤밍웨이 레스토랑",
    "B급 부부 세계여행 : 네이버 블로그",
)
# Filed EVENT by danceinfo and still a class: one day, a free lesson. Both the
# single date and the classification keep it out, and the broad alternative
# broke the second of those.
FREE_CLASS_NIGHT = (
    3778,
    "MAX NIGHT Free Salsa On1 Class",
    "2026-09-24 전체일정 2026-09-24 일정정보 매주 목요일 8PM - 11PM 장소 라틴 "
    "DJ MAX 강의 소개 추석연휴를 맞아 MAX NIGHT Free Salsa On1 Class를 개최합니다. "
    "무료 수업으로 초급 수준의 댄서들을 대상으로 합니다. "
    "Join us for MAX NIGHT Free Salsa On1 Class to celebrate the start of "
    "the Chuseok holiday.",
)
# v0.96.13's own hard gate, unchanged since. A 4주 course over five Wednesdays,
# filed 강습, whose body does contain 쏘셜 - and must stay a class.
LARGO = (
    4432,
    "Largo Special KIZOMBA",
    "2026-09-29 전체일정 2026-09-29,2026-10-02,2026-10-09,2026-10-16,2026-10-23 "
    "일정정보 매주 수요일, 4주 17:10~20:00 강의 소개 레이디 집중 케어반, "
    "레이디&팔로우 모두 따라쇼, 어드밴스 뮤컬, 풋워크/바디 컨트롤, "
    "쏘셜 스킬/뮤지커리티 클래스, 커플 할인",
)
# Somebody else's nights. Real body, real shape, and it names no NIGHT -
# **no roundup in the whole corpus does**, so the combination below it is
# constructed rather than measured, and is here to pin the intent.
ROUNDUP = (
    1576,
    "비 수도권 주요 일정",
    "2026-09-24 전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
    "강의 소개 -출처 전국방 주소 https://invite.kakao.com/tc/K07BipdWQF "
    "20260902 부산 지역 정모 현황 수정되었습니다. "
    "20260916 대전 오아시스 9월14일(월) 정모 추가 (월/토, 주 2회) #파티일정 #심슨",
)
# Constructed from that shape: a roundup that lists another club's NIGHT. No
# such post exists in the corpus today; this fixes the reading before one does.
ROUNDUP_NAMING_ANOTHER_CLUBS_NIGHT = (
    "비 수도권 주요 일정",
    "2026-11-06 전체일정 2026-11-06,2026-11-07 강의 소개 지역 정모 현황 "
    "11월 6일(금) 부산 클럽야만 BACHATA NIGHT "
    "11월 7일(토) 대구 바바루 LATIN NIGHT #파티일정 #심슨",
)
# Constructed from LARGO's shape: a course whose blurb happens to mention a
# night. The course wording is what refuses it, not the vocabulary.
COURSE_MENTIONING_A_NIGHT = (
    "라틴 4주 과정",
    "2026-11-04 전체일정 2026-11-04,2026-11-11,2026-11-18,2026-11-25 "
    "일정정보 매주 수요일, 4주 19:00~21:00 장소 탑 강의 소개 "
    "4주 과정으로 진행합니다. 수료 후에는 금요 LATIN NIGHT 에서 바로 춰보세요!",
)

# --- D. what v0.96.16 protects, which this release must not move -----------

# 하바나 lists five days and calls one of them closed. A day whose own line
# names no night is still not a night, whatever vocabulary is added.
HAVANA_CLOSED = (
    4755,
    "클럽 하바나 추석 연휴 공지",
    "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
    "일정정보 20:30 - 21:30 장소 하바나 강의 소개 춤추는 놀이터 하바나에서 "
    "추석 연휴를 맞아 소셜파티를 개최합니다. "
    "9월 23일(수) 미니 소셜 파티 20:30 ~ 21:30 바차타 무료 오픈강습 "
    "9월 24일(목) 하루 쉬어갑니다. "
    "9월 25일(금) ~ 27일(일) 정상 영업! 추석 연휴에도 하바나는 문 열어놓을게요.",
)
HAVANA_CLOSED_DAY = "2026-09-24"

# LATIN EVERLATN gives two of its four days nothing but a workshop. Adding
# NIGHT to the dated-programme vocabulary must not reach them either.
WORKSHOP_ONLY = (
    2942,
    "추석 연휴 워크샵 - LATIN EVERLATN",
    "2026-09-24 전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
    "일정정보 7:00-10:00 p.m. 장소 라틴 강의 소개 "
    "추석 연휴를 맞아 다양한 춤 종류의 워크샵과 파티가 열립니다. "
    "- 09/25(금) 7:00-8:00 p.m.: Salsa 워크샵 "
    "- 09/26(토) 7:00-9:00 p.m.: Salsa 워크샵 "
    "- 09/27(일) 7:00-8:00 p.m.: Bachata 워크샵, 9:00-10:00 p.m.: Kizomba 파티",
)
WORKSHOP_ONLY_DAYS = {"2026-09-25", "2026-09-26"}

# A poster is not a day's own line. 엘마르's poster reads `ELMAR LATIN NIGHT`
# (real stored OCR, item 221) - and a poster may never be what makes a listed
# day qualify as a night.
POSTER_SAYING_NIGHT = [(
    "https://img.example.invalid/elmar.png",
    "ELMAR LATIN NIGHT  엘마르에서  MUSIC | DANCE | DRINK | VIBES",
)]
POSTER_DAY_LIST_BODY = (
    "엘마르 주말 안내",
    "2026-11-06 전체일정 2026-11-06,2026-11-07 일정정보 9:00 PM 장소 엘마르 "
    "강의 소개 11월 6일(금) 금요 오픈강습 11월 7일(토) 토요 워크샵",
)
