"""v0.96.15 Production regression set: a run of nights collapsed to one day.

A club that opens for a holiday writes its own list of days and then gives
each of them a line. danceinfo.net renders that list as a field of its own -
``전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27`` - and the post's
prose then details each day. Production stored one event for the whole run,
on one arbitrary day of it, and the other days were simply not there.

Measured read-only on Production 25cd038 / 0.96.14 / engine 0.99, fully
converged, over all 2,472 collected items, and re-checked against the live
danceinfo.net pages on 2026-09-25. Of the nine listings missing from that
day's Salsa/Bachata results, **eight already held a real, visible event** -
on the wrong day of a multi-day run. One was a classifier miss.

**Two things were in the way, and both are in here.**

*The days could not be read.* danceinfo.net deliberately publishes no
``published_at`` (danceinfo_discovery's own comment: the list JSON's date is
the *event's* date, not the posting date, and feeding it back would make the
yearless-date check circular). Without one, every yearless day in the body -
``9/25``, ``9월 26일`` - resolved to nothing, so the only dates the extractor
could see were the ISO ones in the header, packed comma-to-comma with no
program text between them. The last of those swallowed the whole body, which
is precisely why 보니따's four-day run was stored as 9/27.

*And the expansion was gated on the title.* ``extract_schedule()`` has
produced one candidate per dated program since v0.96.0, but only for a post
whose own title says 일정 / 스케줄 / 안내 / 공지. None of these say any of
them.

**The negatives are the point of the file.** A four-week course lists its
session dates in exactly the same shape; a community's weekly roundup lists
three nights at three venues; a raffle-results post lists the milongas whose
draws it is announcing; a single-day post mentions a party a month away. Each
of those is here, with the reading that keeps it out.

Each entry is ``(ref, title, body, published, expected_dates)`` where ``ref``
is the Production item it was taken from and ``expected_dates`` is the set of
dates the post must produce - ``None`` meaning "not a schedule: whatever the
single-candidate path already gives". Bodies keep the real shape -
danceinfo.net's own label order, the separators, the clock and date forms -
trimmed of the prose around them. Contact numbers and accounts are replaced.
"""

# --- A. Runs of nights the post itself lists and then details --------------
#
# Every one of these holds exactly one Production event today, on one day of
# its own run. Each writes its days out with a year in its own header, and
# each gives those days their own lines.
MULTI_DAY_RUNS = [
    (
        # 4 nights, each with its own instructor pair and party. The clock
        # ("파티 7-8시, 8-9시") is stated once for the whole run, which is why
        # the per-day candidates carry no start time and must not be required
        # to. Stored as 2026-09-27 alone before this release.
        3766,
        "보니따에서 보내는 추석연휴",
        "2026-09-24 전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
        "일정정보 매일 2시간 워크샵 및 파티 7-8시, 8-9시 장소 보니따 "
        "DJ DJ 깔리드 강의 소개 보니따에서 보내는 추석연휴!! "
        "🎁워크샵 8시간+ 4일파티 + 음료 = 가성비 풀패스 10만원!! "
        "9/24 목 - 코코&무신, 바차타 워크샵 2시간 + 파티+ 1drink "
        "9/25 금 - 용수&팅커벨, 바차타 워크샵 2시간 + 파티+ 1drink "
        "9/26 토 - 시니&세라, 살사 - 원궁&요니, 바차타 워크샵 2시간 + 파티+ 1drink "
        "9/27일 발 - 니르바나&썬, 바차타 워크샵 2시간 + 파티+ 1drink",
        None,
        {"2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"},
    ),
    (
        # The 휴무 day is in the site's own 전체일정 and is not a night: its
        # line says so and names nothing. Nothing about 휴무 is read as a
        # word - the day simply does not name the event, which is the test
        # extract_schedule() has always applied.
        3772,
        "클럽 하바나 추석 연휴 공지",
        "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25,2026-09-26,"
        "2026-09-27 일정정보 20:30 - 21:30 장소 하바나 강의 소개 춤추는 "
        "놀이터 하바나에서 추석 연휴를 맞아 소셜파티를 개최합니다. "
        "9월 23일(수) 🎉 미니 소셜 파티 🕣 20:30 ~ 21:30 바차타 무료 오픈강습 "
        "🕤 21:30 ~ 미니 소셜 파티 9월 24일(목) 🌙 하루 쉬어갑니다. "
        "9월 25일(금) ~ 27일(일) 🍷 정상 영업! 추석 연휴에도 하바나는 문 "
        "열어놓을게요. Club HAVANA Since 1995",
        None,
        {"2026-09-23", "2026-09-27"},
    ),
    (
        # Three nights, each with its own PARTY line, clock and DJ.
        3788,
        "부산 루에다 추석 연휴 일정",
        "2026-09-25 전체일정 2026-09-25,2026-09-26,2026-09-27 일정정보 "
        "금요일 21:00 - 24:00 장소 루에다 DJ 키튼 강의 소개 추석을 맞아 "
        "함께하는 루에다 홈파티. 9.25 FRI — 9.27 SUN 3일 동안 루에다에서 "
        "춤추자! ❤️ 9/25 금요일 PARTY 21:00–02:00｜루에다 4층 🎧 DJ 키튼 "
        "🔥 SPECIAL WORKSHOP 팍찐쌤 살사 스타일링 20:00–21:00 워크샵 2만원 "
        "(파티 포함) 파티 현매 1만원 🧡 9/26 토요일 PARTY 21:00–02:00｜"
        "루에다 2층 🎧 DJ 꼰스 워크샵 2만원 (파티 포함) 파티 예매 1.5만원 "
        "💙 9/27 일요일 PARTY 21:00–24:00｜루에다 2층 🎧 DJ 유니크",
        None,
        {"2026-09-25", "2026-09-26", "2026-09-27"},
    ),
    (
        # The other 휴무: the site leaves 9/24 out of 전체일정 *and* the body
        # says 강턴휴무. Also the post that writes each day twice - once in a
        # summary sentence with no clock, once as its own block with one -
        # which is why the block is the segment kept.
        3792,
        "BACHATA, SALSA, SOCIAL PARTY",
        "2026-09-22 전체일정 2026-09-22,2026-09-23,2026-09-25,2026-09-26,"
        "2026-09-27 일정정보 PM 8:00~9:00, PM 9:00~ 장소 강턴 "
        "DJ 어텐션, 헤이즐, 린넨, 리키 강의 소개 9월 26일 토요일에는 "
        "토요소셜파티가 열리고, 9월 27일 일요일에는 월간 무차살사:소셜 "
        "파티가 예정되어 있습니다. ☑9월 22일(화) PM9:00~ 강턴 "
        "바차타프로젝트 Ep.2 오픈강습 : 원준 & 세이샤 PM8:00~9:00 "
        "— ☑9월 23일(수) PM9:00~ 추석맞이 수요소셜파티 워크샵 : "
        "PM8:00~9:00 백호 & 몽 살사 샤인 & 패턴 🎧DJ 헤이즐 "
        "— ☑9월 24일(목) 강턴휴무 — ☑9월 25일(금) PM9:00~ "
        "추석맞이금요소셜파티 워크샵 : PM8:00~9:00 끌루이 & 달라's 살사 "
        "— ☑9월 26일(토) PM9:00~ 추석맞이토요소셜파티 워크샵 : "
        "P.M8:00~9:00 백호 & 몽 's 살사샤인 🎧DJ 헤이즐 "
        "— ☑9월 27일(일) PM9:00~ 월간 무차살사:소셜 추석맞이 특별한 파티 "
        "워크샵 : PM8:00~9:00 민용 & 세라 살사샤인 🎧DJ 리키",
        None,
        {"2026-09-23", "2026-09-25", "2026-09-26", "2026-09-27"},
    ),
    (
        # Four days of a salsa week; 9/30's own line names only a workshop, so
        # it is not one of them. A day being in the header is not enough.
        3734,
        "서울살사위크 소셜이벤트",
        "2026-09-30 전체일정 2026-09-30,2026-10-01,2026-10-02,2026-10-03 "
        "일정정보 8시(50분), 8시50분, 8시50분 장소 강턴 DJ DJ분 강의 소개 "
        "9월 30일부터 10월 3일까지, 4일간의 소셜이벤트 서울살사위크가 "
        "열립니다. 워크샵 프로그램 9월 30일 (수) 제이오 워크샵 8시(50분) - "
        "아프로 쿠반 with 살사 10월 1일 (목) 핸슨&화라 워크샵 8시50분) -"
        "소셜에서의 파트너워크 팁, 클리닉 10월 2일 (금) 워크샵 끌루이&달라 "
        "워크샵 8시50분) -소셜에서의 파트너워크 팁 10월 3일 (토) WEEK "
        "백호&몽 워크샵 4시(50분) - 소셜에서의 파트너워크 팁, 클리닉",
        None,
        {"2026-10-01", "2026-10-02", "2026-10-03"},
    ),
]


# --- B. The same shape, and not a run of nights ----------------------------
#
# ``expected`` is None: each of these must go on producing exactly what the
# single-candidate path already produces for it.
NOT_A_RUN_OF_NIGHTS = [
    (
        # N1. A four-week course. Its 전체일정 is its session list and its
        # body prices the course ("4주 과정", "개강"). Four Thursdays are not
        # four nights.
        2242,
        "위드라틴 살사 진짜소셜 시즌8 대한민국 패턴 탑10",
        "2026-09-17 전체일정 2026-09-17,2026-10-01,2026-10-08,2026-10-15 "
        "일정정보 4주 과정 매주 목요일 8시 장소 뉴욕바 강의 소개 위드라틴 "
        "살사 진짜소셜 시즌8 (이번 시즌은 추석연휴로 4주만 진행) "
        "9.17일(목) 저녁 8시 개강 언제? 매주 목요일 저녁 8시 어디? 강남역 "
        "뉴욕바 정모? 10시 라틴빠 이동 소셜 정모",
        None,
        None,
    ),
    (
        # N2. A community's week: three nights, three venues, three days -
        # and no date list of the post's own. The days here resolve from a
        # real published_at, which is exactly the case this release does not
        # touch.
        2068,
        "[9월 둘째주] 쉴 틈 없는 파티와 아기린 생일빵! 🔥",
        "9/9(내일!) 수보니따: 아시아 바차타 파라다이스 Farewell Party! "
        "소셜 오픈: 밤 9시부터 DJ 셀리 님과 함께! (살사 3 : 바차타 3) "
        "9/11(금) 홍턴 정모: 보라초스 공연 & 아기린 생일빵! 소셜 오픈: "
        "밤 9시부터 오픈! 9/12(토) 토토보니따 벙개: 주말의 피크! "
        "소셜 오픈: 저녁 8시 메인홀 (살사 3 : 바차타 3)",
        "2026-09-08",
        None,
    ),
    (
        # A raffle-results post. It names three milongas and a winner each,
        # carries no clock and no date list of its own, and announces
        # nothing anyone can turn up to.
        3133,
        "[부산_가또땅고]월간가또 Monthly Gato Milonga 시즌2...",
        "9/15(화) 화밀 당첨: 아가페 9/19(토) 글로벌프렌즈 밀롱가 당첨: "
        "모스카토 9/25(토) 추석밀롱가 당첨: 포레스트 크리스틴's 10만원 "
        "찬조, 클로버&우디's 10만원 찬조...",
        "2026-09-13",
        None,
    ),
    (
        # N5-adjacent. One day in the header, and a party a month away
        # mentioned in passing. A day the post never listed is not a program
        # of it.
        3822,
        "Sunday Night Salsa Bachata Together",
        "2026-09-27 전체일정 2026-09-27 일정정보 8시 30분 ~ 11시 30분 "
        "장소 리트모 DJ 하이디 강의 소개 추석 연휴 마지막 날🍂 "
        "🎧 Special DJ 하이디와 함께하는 Sunday Night Social 음비: 살사 3! "
        "바차타 4 그리고 다가오는 10월 24일 SNS 4주년 파티까지❤️ "
        "9월 27일 8시 30분 ~ 11시 30분 입장료 10,000원 장소: 리트모",
        None,
        None,
    ),
    # 홍턴 3767 used to sit here, and v0.96.17 moved it out rather than this
    # file being wrong: guard 3 kept that post because its own 9/26 line named
    # a LATIN NIGHT and neither 소셜 nor 파티, so the day it was already read as
    # would not have survived the expansion. v0.96.17 gave the dated-programme
    # vocabulary that exact word, so the 26th now survives and the run is read
    # as the four nights it is - see tests/test_v09617_night_named_program.py.
    # The guard itself is still exercised below, by the half of it that is
    # about losing a *time* rather than a day.
    (
        # And the time must survive with it. 수원쿠바's own 9/26 line carries
        # no clock; the 8:00 PM it states once at the top belongs to the run.
        3810,
        "수원쿠바 라틴댄스 소셜",
        "2026-09-12 전체일정 2026-09-12,2026-09-19,2026-09-22,2026-09-26 "
        "일정정보 토요일 8:00 PM - 11:00 PM 장소 쿠바빠 강의 소개 "
        "💃 이번 주 토요일 수원쿠바에서 💃 원더 줄리아쌤 키좀바 따라쇼 & "
        "오픈강습 있습니다 함께라서 더 즐거운 시간! "
        "9월 12일 토요 소셜 Salsa, Bachata, 키좀바 따라쇼 "
        "9월 19일 토요 오픈강습 원더 & 줄리아 Kizomba "
        "9월 22일 화요 바차타 한곡반 수료식 시즌 12 소셜 "
        "9월 26일 추석 소셜 9월도 수원쿠바에서 신나게!",
        None,
        None,
    ),
]


# --- C. Prices that are not dates -----------------------------------------
#
# Every occurrence of the shape in the stored corpus: 28 of them across 21
# items, and not one is a date. Harmless before this release (nothing could
# supply the year) and not harmless after it.
PRICES_NOT_DATES = [
    "티 켓 예 매: 142기 2만원 / 선배기수 1.5만원 / 현장구매 2만원",
    "목요일 [워크샵+파티] 예매:3.9만원 / 현매:4.5만원",
    "입장료: 1.2만원 공연: 진y창현",
    "파티 예매 1.5만원｜현매 2만원",
    "3.5만원/2hr워크샵+홀딩+파티+음료",
]
