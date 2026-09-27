"""v0.96.19: which programme a clock *range* belongs to.

v0.96.18 taught `parse_start_time()` to weigh the nearest class word against
the nearest event word instead of letting any class word within sixteen
characters veto a lone clock. It deliberately left the range side alone, and
pinned 가또땅고 3199 as the proof that the same defect was still there::

    3/6(금) 월간가또 7:50-8:50pm 오픈특강 with 샤론y태희 9:00pm-12:30am 밀롱가
    (밤 10시30분 샤론y태희 공연)

The milonga states its own hours. `_is_other_programme()` threw them away
because 오픈특강 - the class that ends ten minutes before it - sits within
sixteen characters *before* the range, so the only clocks left to read were the
performance's, and the post read 22:30.

The range side is not the lone-clock side with the numbers changed. There are
1,508 range candidates in the stored bodies and 891 more in the stored poster
OCR; 205 of them are rejected today, and a naive nearest-word comparison would
admit eight - six rightly and two wrongly. So two rules come with it:

**A word that heads another clock is not naming this range.** Item 4449 writes
`워크샵 : 양 & 베키 · PM 7:00~8:00 소셜 시작 : PM 8:00`. The 소셜 is nearest the
workshop's range and would hand it the workshop's hours - but the 소셜 is
labelling the `PM 8:00` that follows it, and the post's 20:00 is correct.

**A class word written after a range is that range's own label.** The PISTA
poster writes `심야밀롱가(11:30 p.m-4:30 a.m) 패키지`: 밀롱가 one character
before the range, 패키지 two after. Distance alone hands the late-night
package's hours to the milonga. Direction decides instead - a class word before
a range trails the previous item and may be outranked; one after it still owns
the range, however near the event's word is. The event's own word may sit on
either side, because Korean posts label a range as often before
(`소셜 오후 9시~11시`) as after (`9:00pm-12:30am 밀롱가`).

And where several ranges are named, the event's word must name the one it names
*most closely*: taking the first by position gave a 공연 its hours.

Measured with a `git stash` baseline over all 2,516 stored items through a
harness that replays Production's own poster OCR: three posts change, all
time->time, and no None->time, time->None, date, cardinality, classification,
venue or fee change anywhere. KET regression 0.
"""

SOCIAL = "SOCIAL_WITH_CLASS"
MILONGA = "MILONGA_WITH_CLASS"

# --- A. ranges the event states that a class word was taking -------------
#
# (label, body, event_type, start, end)
ATTRIBUTED = [
    (
        "3199: the milonga's range, after the class that ends before it",
        "3/6(금) 월간가또 7:50-8:50pm 오픈특강 with 샤론y태희 9:00pm-12:30am 밀롱가 "
        "(밤 10시30분 샤론y태희 공연)",
        MILONGA, "21:00", "00:30",
    ),
    (
        "3735: a daytime milonga that read as 1am before this release",
        "- 12:00pm ~ 12:50pm 기제르모 & 록산나의 한곡완성반 (별도 등록) "
        "- 1:00pm ~ 1:50pm 미선 특강 - 2:00pm ~ 4:00pm 밀롱가 씨엠쁘레",
        MILONGA, "14:00", "16:00",
    ),
    (
        "the class range first, the social's own second",
        "살사 초급 특강 오후 7시~8시 소셜 오후 9시~11시",
        SOCIAL, "21:00", "23:00",
    ),
    (
        "three programmes, the party's is the last",
        "바차타 클래스 오후 6시~7시 공연 오후 8시~8시30분 LATIN PARTY 오후 9시~12시",
        SOCIAL, "21:00", "00:00",
    ),
    (
        "4415: the party's own range, labelled with a colon",
        "바차타 워크숍과 살사 워크숍. 에어쌤의 멋진 샤인패턴 워크숍. "
        "파티 시간: P.M 9:00 - A.M 1:00.",
        SOCIAL, "21:00", "01:00",
    ),
]

# The event's word labels its range as often before it as after it, and the
# rule must not prefer one side. (label, body, expected start)
EITHER_SIDE = [
    ("the event word before its range", "특강 오후 7시~8시 소셜 오후 9시~11시", "21:00"),
    ("the event word after its range", "특강 오후 7시~8시, 9:00pm~11:00pm 소셜", "21:00"),
    ("with a colon", "특강 오후 7시~8시 소셜: 오후 9시~11시", "21:00"),
    ("with a line break", "특강 오후 7시~8시\n소셜 오후 9시~11시", "21:00"),
    ("English, before", "workshop 7:00~8:00 pm, party 9:00~11:00 pm", "21:00"),
    ("English, after", "workshop 7:00~8:00 pm, 9:00~11:00 pm party", "21:00"),
]

# Not specific to one scene's word.
EVENT_WORDS_TRIED = [
    ("소셜", SOCIAL), ("파티", SOCIAL), ("social", SOCIAL), ("party", SOCIAL),
    ("밀롱가", MILONGA), ("milonga", MILONGA),
]
EVENT_WORD_BODY = "워크샵 오후 7시~8시 {word} 오후 9시~11시"

# --- B. ranges that must stay another programme's ------------------------
#
# (label, body, event_type)
STILL_ANOTHER_PROGRAMMES = [
    (
        "a workshop and nothing else",
        "초급 살사 워크샵 오후 7시~9시", SOCIAL,
    ),
    (
        "a regular class timetable",
        "바차타 정규 클래스 19:00~20:30", SOCIAL,
    ),
    (
        "a tie cannot say whose it is",
        "소셜 워크샵 오후 7시~8시", SOCIAL,
    ),
    (
        "the class word is the nearer one",
        "소셜 안내 특강 오후 7시~8시", SOCIAL,
    ),
    (
        # 4449. The 소셜 is nearest the workshop's range and is labelling the
        # PM 8:00 after it. Reading the workshop's hours here would overwrite a
        # correct 20:00 with 19:00.
        "4449: the nearest event word heads the next clock, not this range",
        "워크샵 : 양 & 베키 · PM 7:00~8:00 소셜 시작 : PM 8:00 DJ 린넨", SOCIAL,
    ),
    (
        # The PISTA poster's own wording. 밀롱가 is nearer the range than
        # 패키지 is, and the hours are still the package's.
        "PISTA poster: a class word after the range still owns it",
        "*10시 이후 입장시, 무료 입장권 1장제공 *심야밀롱가(11:30 p.m-4:30 a.m) "
        "패키지 사전결제 ) 20,0008!", MILONGA,
    ),
    (
        "the PISTA body says the same thing in its own words",
        "🎟 10시 이후 입장 시 무료 입장권 1장 제공 🌙 심야 밀롱가 패키지 "
        "23:30 – 04:30 사전결제 20,000원", MILONGA,
    ),
]

# --- C. admitted, and then refused for a different reason ---------------
#
# Three of the six ranges the rule admits carry no meridiem at all. Advertising
# a morning for a night is worse than advertising nothing, so `_readings()`
# refuses them - the same trade v0.96.18 made for a guessed morning start.
# (label, body, event_type)
UNMARKED_MORNING_REFUSED = [
    ("3820 루에다: 9시~12시 with no meridiem anywhere",
     "일정정보 워크샵 2만원 (파티포함) 9시~12시 장소 루에다 DJ 유니크", SOCIAL),
    ("3768 BAYA: 9:00-1:00 with no meridiem anywhere",
     "일정정보 8:00-9:00 워크샵, 9:00-1:00 소셜 장소 바야", SOCIAL),
]

# A range no class word ever objected to keeps its literal morning reading,
# exactly as before - this release must not start refusing those.
UNVETOED_MORNING_KEPT = ("아침 연습 소셜 9시~12시", SOCIAL, "09:00", "12:00")

# --- D. v0.96.18's lone-clock behaviour, unmoved -------------------------
#
# `parse_start_time()` calls `_readings()` without a vocabulary, so its guard
# means exactly what it meant: a post that states a range of its own is
# `parse_time_range()`'s to read.
LONE_CLOCK_UNMOVED = [
    ("BABARU", "일정정보 PM 8:00~9:00 (워크샵), PM 9:00 START (소셜) 장소 바바루",
     SOCIAL, "21:00"),
    ("홍턴 9/23",
     "9월 23일(수) | 홍턴 바차타 파티 바차타 4 : 살사 2 오후 7시 제니 y 뚜부 "
     "오후 8시 뽀대용수 y 밀라 소셜 오픈 오후 9시 / DJ 쿵 워크샵 2개+소셜 20,000원",
     SOCIAL, "21:00"),
    ("강턴 9/25", "9월 25일(금) PM9:00~ 추석맞이금요소셜파티 워크샵 : PM8:00~9:00 "
     "끌루이 & 달라's 살사 샤인 & 패턴", SOCIAL, "21:00"),
]

# The range-tail refusals v0.96.18 added. A range becoming readable must not
# make its tail a start.
RANGE_TAIL_STILL_REFUSED = [
    "일정정보 8:00-9:00 워크샵, 9:00-1:00 소셜 장소 바야",
    "09/27(일) 7:00-8:00 p.m.: Bachata 워크샵, 8:00-9:00 p.m.: Bachata 워크샵, "
    "9:00-10:00 p.m.: Kizomba 파티",
]

# --- E. ranges that were already read, and must not move -----------------
UNCHANGED_RANGES = [
    ("three ranges, the social's own is the last",
     "15:00-16:30 발스윙 중고급 16:45-18:15 쉐그 초급 20:00-22:30 소셜",
     SOCIAL, "20:00", "22:30"),
    ("the class range first, the milonga's second",
     "8:00~9:10pm 무료 특강 (아미고) [쁘롱가] 9:15~11:15pm",
     MILONGA, "21:15", "23:15"),
    ("a plain social range",
     "소셜 20:00-22:30", SOCIAL, "20:00", "22:30"),
]

# --- F. the case this release does not fix ------------------------------
#
# 3199's sibling post, 가또땅고's 2월 일빠. 2/22 is a day of four classes and no
# milonga at all, and the post is classified MILONGA_WITH_CLASS, so a range is
# read off a class timetable either way. It read 탱고 집중 준중급's 3:05-4:15pm
# and now reads 밀롱가 올레벨 종강's 4:20-5:20pm - the line that says 밀롱가,
# which is why it moves, and still a class. The fix belongs on the
# classification side and is out of scope here; pinned so the state is visible.
STILL_A_CLASS_TIMETABLE = (
    3201,
    "♡매주 수욜 8시 초급 원데이클라스!!♡ 2/22(일)_일빠 "
    "① 소고귀ⓨ애비's 발스 올레벨 종강 (2:00-3:00pm) "
    "② 소고귀ⓨ애비's 탱고 집중 준중급 종강 (3:05-4:15pm) "
    "③ 좐슨ⓨ버드s 밀롱가 올레벨 종강 (4:20-5:20pm) "
    "④ 데이브ⓨ지브릴's 악단별 안무 풋워크 종강 (5:30-6:40pm)",
    MILONGA, "16:20", "17:20",
)

# --- G. pre-existing limitations, unchanged and pinned -------------------
#
# Neither is an attribution question, and both read the same before and after.
#
# `_RANGE_RE` swallows a following range's meridiem into its own match, so the
# second range of "특강 오후 7시~8시 오후 9시~11시 소셜" is left as a bare
# "9시~11시" and refused as an unmarked morning. Written with its own marker
# ("9:00pm~11:00pm") the same sentence reads 21:00 - the EITHER_SIDE entry above.
MERIDIEM_SWALLOWED = ("특강 오후 7시~8시 오후 9시~11시 소셜", SOCIAL)

# LATIN EVERLATN 3769's party hours come from its 일정정보 field, not from the
# programme line: read on its own, that line's "9:00-10:00 p.m.: Kizomba 파티"
# is a range whose class word is nearer, and it gives nothing. The stored
# 19:00-22:00 is unaffected either way.
EVERLATN_PROGRAMME_LINE = (
    "09/27(일) 7:00-8:00 p.m.: Bachata 워크샵, 8:00-9:00 p.m.: Bachata 워크샵, "
    "9:00-10:00 p.m.: Kizomba 파티", SOCIAL)
