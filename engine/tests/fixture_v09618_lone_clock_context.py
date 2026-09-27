"""v0.96.18: an event's start time after somebody else's clock range.

`parse_start_time()` reads the hour a night begins when the post writes one
clock and no range of its own. Two things in it were deciding by position and
by presence rather than by what a word is actually near, and both were losing
an hour the post states in plain text.

**The veto was absolute.** `_is_other_programme()` asks "is there a class word
within sixteen characters", which is the right question for a *range* - a range
beside 워크샵 is the workshop's hours - and the wrong one for a lone clock in a
body that lists both. BABARU writes::

    일정정보 PM 8:00~9:00 (워크샵), PM 9:00 START (소셜)

The 워크샵 belongs to the range *before* the 9:00, four characters away; 소셜 -
the word that does qualify it - sits one character after. Every candidate was
vetoed, `parse_start_time()` returned None, and the 21:00 the post states could
only come from a poster. Production carried 20:00 on all three of BABARU's
nights: the workshop hour, read off its poster.

**And position outranked evidence.** Where several lone clocks all sit near the
event's own word, the first by position won. 홍턴's 9/23 line::

    9월 23일(수) | 홍턴 바차타 파티 오후 7시 제니 y 뚜부 오후 8시 뽀대용수 y
    밀라 소셜 오픈 오후 9시 / DJ 쿵

The day's 파티 heading is near all three clocks, so the night was advertised at
오후 7시 - the first workshop - when the post says it opens at 9.

**A third thing had to be added rather than removed.** Weighing distance lets a
clock through that the absolute veto had been catching by accident: the *tail of
a range*. BAYA writes `8:00-9:00 워크샵, 9:00-1:00 소셜` and the 소셜 is nearest
to the `1:00`, so the social read as starting at 01:00. LATIN EVERLATN's
`9:00-10:00 p.m.: Kizomba 파티` read 22:00 the same way. A clock written as one
end of a range is never an independent start, and that is now explicit.

What is deliberately unchanged: the range guard at the top of the function (a
post that states a range of its own is `parse_time_range()`'s to read, which is
strictly better evidence than a lone clock - measured over the whole stored
corpus, deleting it changes nothing), `_is_other_programme()` itself, and every
rule that decides what a range is for.

Measured over all 2,504 stored items: four posts change - 2 None->time, 5
time->time, 0 time->None, no date, cardinality or classification change
anywhere.
"""

SOCIAL = "SOCIAL_WITH_CLASS"
MILONGA = "MILONGA_WITH_CLASS"

# --- A. an event clock the post states, after somebody else's range --------
#
# (label, body, event_type, expected start)
RECOVERED = [
    (
        "BABARU: workshop range, then the social's own start",
        "일정정보 PM 8:00~9:00 (워크샵), PM 9:00 START (소셜) 장소 바바루",
        SOCIAL, "21:00",
    ),
    (
        "the same, stripped to its shape",
        "PM 8:00~9:00 워크샵 PM 9:00 START 소셜",
        SOCIAL, "21:00",
    ),
    (
        "two unrelated ranges, then the party's own opening",
        "초급 워크샵 오후 7시~8시 공연 오후 8시~8시30분 LATIN PARTY OPEN 오후 9시",
        SOCIAL, "21:00",
    ),
    (
        "홍턴 9/23: three clocks near the day's own 파티, one of them an opening",
        "9월 23일(수) | 홍턴 바차타 파티 바차타 4 : 살사 2 오후 7시 제니 y 뚜부 "
        "오후 8시 뽀대용수 y 밀라 소셜 오픈 오후 9시 / DJ 쿵 워크샵 2개+소셜 20,000원",
        SOCIAL, "21:00",
    ),
    (
        "강턴: the party's own hour stated before its workshop's range",
        "9월 25일(금) PM9:00~ 추석맞이금요소셜파티 워크샵 : PM8:00~9:00 "
        "끌루이 & 달라's 살사 샤인 & 패턴",
        SOCIAL, "21:00",
    ),
    (
        "a lone event clock and nothing else",
        "토요 소셜 오후 9시 START",
        SOCIAL, "21:00",
    ),
    (
        "the event clock first, the unrelated range later in the sentence",
        "밀롱가는 오후 8시에 오픈합니다. 끝나고 이어지는 특강은 오후 10시~11시입니다.",
        MILONGA, "20:00",
    ),
]

# A bare clock stays literal. `9:00 START` carries no meridiem, so it is 09:00
# and flagged ambiguous - this release recovers clocks, it does not start
# guessing PM for them. (label, body, expected start, expected ambiguous)
NO_MERIDIEM_STAYS_LITERAL = [
    ("START suffix, no marker", "워크샵 7:00~8:00 소셜 9:00 START", "09:00", True),
    ("open suffix, no marker",  "워크샵 7:00~8:00 social 9:00 open", "09:00", True),
]

# --- B. spelling variants of the same statement ----------------------------
#
# The same sentence written the ways Production writes it. Each must give the
# same hour, so a recovery cannot depend on one notation.
OPENING_VARIANTS = [
    ("Korean 오후 + 오픈 prefix",   "워크샵 7시~8시 소셜 오픈 오후 9시", "21:00"),
    ("Korean 오후 + 시작 prefix",   "워크샵 7시~8시 소셜 시작 오후 9시", "21:00"),
    ("Korean 부터 suffix",          "워크샵 7시~8시 소셜 오후 9시부터", "21:00"),
    ("PM before the clock",         "워크샵 7:00~8:00 소셜 PM 9:00", "21:00"),
    ("pm after the clock",          "워크샵 7:00~8:00 소셜 9:00pm", "21:00"),
    ("uppercase START suffix",      "워크샵 7:00~8:00 소셜 PM 9:00 START", "21:00"),
    ("lowercase open suffix",       "워크샵 7:00~8:00 social 9:00pm open", "21:00"),
    ("24-hour clock, no marker",    "워크샵 19:00~20:00 소셜 21:00", "21:00"),
    ("a line break between them",   "워크샵 7:00~8:00\n소셜 오픈 오후 9시", "21:00"),
    ("a bullet between them",       "워크샵 7:00~8:00 · 소셜 오픈 오후 9시", "21:00"),
    ("a slash between them",        "워크샵 7:00~8:00 / 소셜 오픈 오후 9시", "21:00"),
]

# The event's own word varies too; the rule must not be salsa-specific.
EVENT_CONTEXTS = [
    ("소셜",    SOCIAL, "21:00"),
    ("파티",    SOCIAL, "21:00"),
    ("social",  SOCIAL, "21:00"),
    ("party",   SOCIAL, "21:00"),
    ("밀롱가",  MILONGA, "21:00"),
    ("milonga", MILONGA, "21:00"),
]
EVENT_CONTEXT_BODY = "워크샵 7:00~8:00 {word} 오픈 오후 9시"

# --- C. what must keep giving nothing -------------------------------------
REFUSED = [
    (
        "a workshop and nothing else: no social start to find",
        "살사 워크샵 오후 7시~9시", SOCIAL,
    ),
    (
        "a class and nothing else",
        "바차타 정규 클래스 19:00~20:30", SOCIAL,
    ),
    (
        "clocks with no event context at all",
        "접수 오후 3시 마감", SOCIAL,
    ),
    (
        "a deadline is not a start",
        "소셜 신청 오후 9시까지", SOCIAL,
    ),
    (
        "the tail of the event's own range is when it ends, not when it starts",
        "일정정보 8:00-9:00 워크샵, 9:00-1:00 소셜 장소 바야", SOCIAL,
    ),
    (
        "LATIN EVERLATN: the party's range read as a lone 22:00",
        "09/27(일) 7:00-8:00 p.m.: Bachata 워크샵, 8:00-9:00 p.m.: Bachata 워크샵, "
        "9:00-10:00 p.m.: Kizomba 파티", SOCIAL,
    ),
    (
        "a class word nearer than the event word still vetoes",
        "소셜 안내 오후 7시 워크샵", SOCIAL,
    ),
    (
        # A limitation, not a win: the milonga does open at 8, but 특강 is five
        # characters after the clock and 밀롱가 seven before it, so the nearer
        # word decides against the event. Unchanged by this release - None
        # before and None after - and pinned so the trade is visible.
        "the nearer word decides even when it is the wrong one",
        "밀롱가 오픈 오후 8시 이후 특강 오후 10시~11시", MILONGA,
    ),
]

# --- D. the range guard, and the reading it defers to ---------------------
#
# A post that states a range of its own is read by `parse_time_range()`. The
# lone-clock rule must not race it, and the range it picks must still be the
# event's own - not the first one in the body.
RANGE_STILL_WINS = [
    (
        "three ranges, the social's own is the last",
        "15:00-16:30 발스윙 중고급 16:45-18:15 쉐그 초급 20:00-22:30 소셜",
        SOCIAL, "20:00", "22:30",
    ),
    (
        "the class range first, the milonga's second",
        "8:00~9:10pm 무료 특강 (아미고) [쁘롱가] 9:15~11:15pm",
        MILONGA, "21:15", "23:15",
    ),
]

# --- E. v0.96.17 N3: another event named in passing -----------------------
#
# Carried over from v0.96.17, which verified this by hand and shipped without a
# fixture. A post may name somebody else's night, or its own future one, and
# neither becomes a programme of the day it is describing.
N3_REAL = (
    3822,
    "Sunday Night Salsa Bachata Together",
    "2026-09-27 전체일정 2026-09-27 일정정보 8시 30분 ~ 11시 30분 장소 리트모 "
    "DJ 하이디 강의 소개 추석 연휴 마지막 날🍂 "
    "🎧 Special DJ 하이디와 함께하는 Sunday Night Social 음비: 살사 3! 바차타 4 "
    "그리고 다가오는 10월 24일 SNS 4주년 파티까지❤️ 이번 일요일부터 함께 달려요! "
    "9월 27일 8시 30분 ~ 11시 30분 입장료 10,000원 장소: 리트모",
)
N3_REAL_DATES = {"2026-09-27"}

# Constructed: a two-day run whose blurb points at another club's NIGHT on a
# third day. No corpus post does this yet.
N3_OTHER_CLUB = (
    "강턴 주말 안내",
    "2026-11-06 전체일정 2026-11-06,2026-11-07 일정정보 9:00 PM 장소 강턴 "
    "강의 소개 11월 6일(금) 금요 오픈강습 원준 & 세이샤 "
    "11월 7일(토) 토요 워크샵 백호 y 몽 "
    "그리고 다가오는 11월 20일 홍턴 LATIN NIGHT 에서도 만나요!",
)

# --- F. the case this release does not fix -------------------------------
#
# 가또땅고 3199. Its milonga's own range is `9:00pm-12:30am 밀롱가`, and
# `_is_other_programme()` rejects it because 오픈특강 sits within sixteen
# characters before it - the *range* side of the same defect, which this release
# deliberately leaves alone. Before, the reading was 00:30, the milonga's end;
# now it is 22:30, the performance's hour. Both are wrong and the truth is
# 21:00. Pinned so the next release has somewhere to start, and so nobody reads
# 22:00-something as a fix.
UNFIXED_RANGE_SIDE = (
    3199,
    "[부산_탱고동호회]가또땅고 3월 첫째주 열탱즐탱 일정 안내",
    "3/6(금) 월간가또 7:50-8:50pm 오픈특강 with 샤론y태희 9:00pm-12:30am 밀롱가 "
    "(밤 10시30분 샤론y태희 공연)",
)
UNFIXED_TRUTH = "21:00"
