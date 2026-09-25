"""v0.96.14 Production regression set: a night read as the workshop inside it.

The mirror image of v0.96.10. That release taught ``sold_as_a_course()`` to
read danceinfo.net's own per-item category when the site says 강습, so a
social named in a course's heading stops selling a night. Nothing ever read
the category when the site says 출빠정보 / 파티 / 정모 - *a night to turn up
to* - and a post that also ran a workshop went on being judged by the
workshop alone.

Measured read-only on Production e131945 / 0.96.13 / engine 0.98, fully
converged, over all 2,468 collected items, each classified the way the
runtime classifies it - its own ``known_event_type``, its source's Settings
event terms, and the title and body ``engine_ingest._to_raw_post()`` would
hand the engine. Every body below was also re-fetched live from
danceinfo.net on 2026-09-25 and reads the same way on the live page.

**Of the 52 listings danceinfo.net files under a night category, eleven
classified CLASS and produced no candidate at all.** Seven of the eleven are
real nights that also teach, and five of those seven are still upcoming.
They are ``NIGHTS_THE_SOURCE_FILED_AS_NIGHTS`` below.

**The other four are not nights, and the naming test alone separates three
of them.** "니르바나&썬 바차타 무료 오픈강습" and "MAX NIGHT Free Salsa On1
Class" are the class by itself - the second one free, in a practice studio,
not in the club - and "LATIN NIGHTS" is a body holding one 8-9PM workshop
and nothing else. None of the three names a social or a party anywhere. The
fourth, "10월 스케줄♥️", is a month of Thursdays at one venue with no day
and no clock of its own, and it is refused by the logistics half.

**The category is a reason to look, never a verdict.** Two listings filed
출빠정보 are correctly not events at all - 비 수도권 주요 일정 is a roundup
of other clubs' schedules and NEW.SOL BAR 추석 영업안내 is opening hours -
and both stay OTHER. They are ``FILED_AS_A_NIGHT_AND_STILL_NOT_AN_EVENT``,
and they are the reason the reading is one of three conditions rather than
the answer on its own.

**What a cruder rule costs, measured before this one was written.** "The
post names a social and a DJ and a clock" reads four of the seven and also
takes nine weekly-schedule roundups from three other sources - a Busan tango
community's "[부산_탱고동호회]가또땅고 7월 넷째주" and a Seoul salsa
community's "[8월 넷째주 공지]", each listing three or four different nights
at different venues on different days, none of which has one date to be
given. Requiring the source's own filing keeps every one of them out,
because no other collector carries a category at all.

Each entry is ``(ref, title, body)`` where ``ref`` is the Production item it
was taken from. Bodies keep the real *shape* - danceinfo.net's own label
order (``<date> 전체일정 <dates> 일정정보 <schedule> 장소 <venue> DJ <dj>
강의 소개 <prose>``), the separators, the clock and date forms, and the
words that decide the reading - and are trimmed of the long prose around
them. Contact numbers and account numbers are replaced.
"""

# --- A. Nights the source filed as nights, on posts that also teach --------
#
# All seven classify CLASS at engine 0.98 and hold no events row. Each names
# a social, a party or the club's own 정모; each carries a specific day and a
# clock. Five are still upcoming.
NIGHTS_THE_SOURCE_FILED_AS_NIGHTS = [
    (
        # 파티(페스티발)/출빠정보. Four nights of parties with a workshop on
        # each; the DJ and the venue are the site's own fields.
        3766,
        "보니따에서 보내는 추석연휴",
        "2026-09-24 전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
        "일정정보 매일 2시간 워크샵 및 파티 7-8시, 8-9시 장소 보니따 "
        "DJ DJ 깔리드 강의 소개 보니따에서 보내는 추석연휴!! "
        "🔥살사&바차타 국내 탑강사들의 워크샵은 덤!! "
        "🎁워크샵 8시간+ 4일파티 + 음료 = 가성비 풀패스 10만원!! ➡️ 9만원 "
        "9/24 목 - 코코&무신, 바차타 워크샵 2시간 + 파티+ 1drink "
        "9/25 금 - 용수&팅커벨, 바차타 워크샵 2시간 + 파티+ 1drink",
    ),
    (
        # 파티(페스티발)/출빠정보/오픈강습. The club's four nights are what
        # the workshop price bundles admission to - "4일 파티 입장료
        # 48.000원" - and the last slot on the last day is a party.
        3769,
        "추석 연휴 워크샵 - LATIN EVERLATN",
        "2026년 9월 24일 (목) 전체일정 09/24 (목) , 09/25 (금) , 09/26 (토) , "
        "09/27 (일) 일정정보 7:00-10:00 p.m. 장소 라틴 강의 소개 안녕하세요. "
        "강남 라틴클럽입니다 추석연휴 \"특별 워크샵\" 선물셋트를 준비했습니다 "
        "(4일 파티 입장료 48.000원빼면 하루 3천원도 안되는 가격에 이 모든 "
        "수업을??) 추석 연휴를 맞아 다양한 춤 종류의 워크샵과 파티가 열립니다. "
        "- 09/25(금) 7:00-8:00 p.m.: Salsa 워크샵 "
        "- 09/27(일) 8:00-9:00 p.m.: Bachata 워크샵, 9:00-10:00 p.m.: "
        "Kizomba 파티",
    ),
    (
        # 출빠정보. The social has hours of its own after the free class -
        # and _SOCIAL_BY_CLOCK cannot see them, because "미니" sits between
        # the clock and the word.
        3772,
        "클럽 하바나 추석 연휴 공지",
        "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25,2026-09-26,"
        "2026-09-27 일정정보 20:30 - 21:30 장소 하바나 강의 소개 춤추는 "
        "놀이터 하바나에서 추석 연휴를 맞아 소셜파티를 개최합니다. "
        "9월 23일(수) 🎉 미니 소셜 파티 🕣 20:30 ~ 21:30 바차타 무료 오픈강습 "
        "🕤 21:30 ~ 미니 소셜 파티 9월 24일(목) 🌙 하루 쉬어갑니다. "
        "9월 25일(금) ~ 27일(일) 🍷 정상 영업! Club HAVANA Since 1995",
    ),
    (
        # 출빠정보. Two workshops, then the club's own door at 9PM and a
        # priced party - and still CLASS, because neither price nor door is
        # written in the shape party_evidence_bundle() reads.
        3775,
        "THURSDAY BONITA 추석연휴시작!",
        "2026-09-24 전체일정 2026-09-24 일정정보 추석 연휴 시작 19:00 - 23:30 "
        "장소 보니따 DJ 깔리드 강의 소개 목보니 with DJ 깔리드 THURSDAY "
        "BONITA 워크샵(1) 7-8PM 코코&무신 Bachata 워크샵 8-9PM 끌루이&달라 "
        "Salsa 예매 2만원/2hr워크샵+파티+음료 DJ 길거리 소셜 모픈 : 9PM WITH "
        "BONITA 메인홀>> 바차타 3 살사 3 파티만! 예매 11,000 헌매15,000 "
        "2개 워크샵+파티입장료+홀딩+1drink",
    ),
    (
        # 파티(페스티발)/출빠정보/오픈강습. The site labels its price field
        # 수강료 whatever the price is: here it is the door price of a party.
        3820,
        "루에다 홈커밍 데이",
        "2026년 9월 27일 (일) 일정정보 워크샵 2만원 (파티포함) 9시~12시 "
        "장소 루에다 DJ 유니크 강의 소개 춤으로 다시 만나는 홈커밍 데이. "
        "연휴 마지막날도 루에다에서! 좋은 사람들과 더 특별한 파티. "
        "Good Music, Good People, Laten Vibes. 연락처 [전화번호] "
        "수강료 현매 1만원, 바틀 2만원 할인",
    ),
    (
        # 출빠정보/정모. Two free classes, then the 정모 itself 6시~9시.
        3869,
        "더크루 일요정모 - 바차타, 살사 무료특강",
        "2026-09-27 전체일정 2026-09-27 일정정보 매주 일요일 4:00 ~ 5:50 "
        "장소 더크루 DJ DJIAX 강의 소개 더크루 일요정모에서 바차타와 살사 "
        "무료특강을 진행합니다. 정모 후에는 뒷풀이도 있습니다. "
        "🌈 일요 정모 참석시 계좌로 정모비 1만원을 닉네임으로 입금을 미리 "
        "하시고 입장시 닉네임을 명단에 적고 입장해 주세요. "
        "🍀바차타 4시 ~ 4시 50분 무료 강습 🍀살사 5시 ~ 5시 50분 무료 "
        "올레벨 유니크 살사 강습. 🍀 정모 6시~9시 까지 음악이 나오며",
    ),
    (
        # 출빠정보/정모/오픈강습. One hour of class, then two hours of the
        # night - written 쇼셜, which is not a word SOCIAL_WORDS holds. The
        # 정모 in the heading is what reads this one.
        3872,
        "강북살사 정모&바차타특강",
        "2026-10-02 전체일정 2026-10-02 일정정보 PM 7:00-8:00, PM 8:00-9:40, "
        "PM 9:40-10:30 장소 국제댄스스포츠 DJ 헤르만 강의 소개 바차타 무료 "
        "강습 (초승달샘 & 은비샘) 쇼셜 (바차타 3 : 살사 3) 쇼셜(바차타 4 : "
        "살사 3) 회비 입금 계좌: 카카오뱅크 [계좌번호] (예금주: 망고)",
    ),
]


# --- B. Filed as a night, and still a course ------------------------------
#
# The other four of the eleven. Three name no night at all; the fourth names
# one and carries none of a night's logistics.
FILED_AS_A_NIGHT_BUT_A_COURSE = [
    (
        # The open class by itself. The club's DJ is a field on the page; the
        # post announces nothing but the lesson.
        3776,
        "니르바나&썬 바차타 무료 오픈강습",
        "2026-09-24 전체일정 2026-09-24 일정정보 8시~9시 장소 부에나 "
        "DJ 카르디 강의 소개 실전에서 바로 사용하는 바차타 패턴을 배울 수 "
        "있는 무료 오픈강습이 열립니다.",
    ),
    (
        # A free weekly beginner class, in a practice studio near the club.
        # "MAX NIGHT" is the club's night in the title and "DJ MAX" is the
        # instructor's name - both are why the notice bundle fires on this
        # post, and why the notice bundle is not what reads group A.
        3778,
        "MAX NIGHT Free Salsa On1 Class",
        "2026-09-24 전체일정 2026-09-24 일정정보 매주 목요일 8PM - 11PM "
        "장소 라틴 DJ MAX 강의 소개 추석연휴를 맞아 MAX NIGHT Free Salsa On1 "
        "Class를 개최합니다. 무료 수업으로 초급 수준의 댄서들을 대상으로 "
        "합니다. • 날짜 : 9월24일 (매주 목요일) • 시간 : 저녁 8시 ~ 8시 50분 "
        "• 수업료 : 무료 • 장소 : 에버라틴 A연습실 세아빌딩 3층 "
        "• 인스트럭터 : DJ MAX & Ines • 대상 : 초급(Level 1)",
    ),
    (
        # The title says NIGHTS; the body is one workshop hour.
        3803,
        "LATIN NIGHTS",
        "2026년 9월 26일 (토) 일정정보 8:00 PM - 9:00 PM 장소 홍턴 강의 소개 "
        "BACHATA WORKSHOP - 8:00 PM 9:00 PM - FEE 10,000 KRW - Great Music - "
        "Let's Dance - This Chuseok! ✨ 9/26(토) 바차타 워크샵 8PM 알콩 y "
        "제시카 수강료 10,000 KRW",
    ),
    (
        # A month of Thursdays at one venue. It names a party and a night in
        # prose and gives neither a day of its own nor a clock, which is
        # exactly what the logistics half is for: five dates and no time is
        # not one night anybody can be sent to.
        3857,
        "10월 스케줄♥️",
        "2026-10-01 전체일정 2026-10-01,2026-10-08,2026-10-15,2026-10-22,"
        "2026-10-29 일정정보 매주 목요일 장소 바야 강의 소개 춤으로 만나는 "
        "10월의 특별한 밤 특별한 워크샵과 함께하는 10월의 시작! 드레스코드 "
        "블랙, 더 특별한 밤 한글날 파티, 섹시 ♡ 생일빵 공식 뒷폴이까지! "
        "할로윈 워크 DAY 1. 오늘도, 바야에서 춤추자",
    ),
]


# --- C. Filed as a night, and not an event at all -------------------------
#
# Both are OTHER today and stay OTHER. Neither carries a word from
# ``class_words``, so neither even enters the branch the new reading lives
# in - but they are asserted here because they are the measured proof that
# the source's own category cannot be the answer on its own.
FILED_AS_A_NIGHT_AND_STILL_NOT_AN_EVENT = [
    (
        3771,
        "비 수도권 주요 일정",
        "2026-09-24 전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
        "강의 소개 -출처 전국방 주소 -출처 경기방 주소 20260902 부산 지역 "
        "정모 현황 수정되었습니다. 20260916 대전 오아시스 9월14일(월) 정모 "
        "추가 (월/토, 주 2회) #파티일정 #부산 #광주 #제주 #대전 #대구",
    ),
    (
        3777,
        "NEW.SOL BAR 추석 영업안내",
        "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25,2026-09-26 "
        "일정정보 아침 6시까지 장소 강쏠 강의 소개 NEW.SOL BAR 추석 영업안내 "
        "9월 23일 (수요일) 9월 24일 (목요일) 9월 25일 (금요일) 9월 26일 "
        "(토요일) 아침 6시까지 정상영업합니다! 연휴 크레이지 파티 즐기고",
    ),
]


# --- D. Courses the source filed as courses -------------------------------
#
# v0.96.13's own fixture, item 3840, plus the four listings filed 강습 whose
# bodies name the venue's DJ - the four a "names a social and a DJ" rule
# would have taken. Every one of them is a numbered course sold by the week.
SOURCE_FILED_AS_A_COURSE = [
    (
        # v0.96.13's hard gate: a four-week Wednesday kizomba course whose
        # own timetable supplies the day and the clock, and whose heading
        # word is the adjective "Special".
        3840,
        "Largo Special KIZOMBA",
        "2026-09-29 전체일정 2026-09-29,2026-10-02,2026-10-09,2026-10-16,"
        "2026-10-23 일정정보 매주 수요일, 4주 17:10~20:00 강의 소개 레이디 "
        "집중 케어반, 어드밴스 뮤컬, 풋워크/바디 컨트롤, 쏘셜 스킬/뮤지커리티 "
        "클래스, 커플 할인, 문의는 [전화번호]",
    ),
    (
        # The venue's own Friday social is a line in a course timetable.
        3784,
        "UNO 일산살사우노",
        "2026-09-02 전체일정 2026-09-02,2026-09-03,2026-09-04,2026-09-06 "
        "일정정보 매주 목요일 6강 8시 ~ 9시 20분 장소 우노 DJ DJ 던칸 바4:살3 "
        "강의 소개 목요일 살사퀀 뮤즈샘 살사베이직 · 턴트레이닝 "
        "PM 8시~11시 금요정모소셜",
    ),
    (
        3826,
        "SS 라틴 댄스 클래스",
        "2026-09-06 전체일정 2026-09-06,2026-09-13,2026-09-20,2026-09-27 "
        "일정정보 매주 일요일, 6주간 수업 16:00 - 18:10 장소 카디즈 스튜디오 "
        "DJ 유리 강의 소개 Sweet and Shy 라틴 클래스 - 살사 준중급, 바차타 "
        "레이디, 할로원파티 공연반 - 특별 혜택! 일요일 소셜 입장료 1만원 "
        "지원! - 수강료 안내, 할인 안내",
    ),
    (
        3849,
        "정통이지라틴",
        "2026-09-09 전체일정 2026-09-09,2026-09-16,2026-09-23,2026-09-30 "
        "일정정보 매주 수요일, 6주 과정 8:30~9:30 장소 라틴 DJ DJ Musicality "
        "강의 소개 🎯1교시 선녀 풋웍 라인댄스 7:30~8:20 🎯2교시 가리온 y선녀 "
        "Sensual Bachata Musicality 반곡반 8:30~9:30 1교시 6주 60,000원 "
        "2교시 6주 120,000원 🍁9/9~10/14(6주) 🍁10/21 발표",
    ),
    (
        # "DJ 없음" - the site's DJ field saying there is no DJ.
        3856,
        "정통이지라틴 풋웍 라인댄스",
        "2026-09-09 전체일정 2026-09-09,2026-09-16,2026-09-23,2026-09-30 "
        "일정정보 매주 토요일, 6주 완성 7:30~8:20 장소 라틴 DJ DJ 없음 "
        "강의 소개 선녀 풋웍 라인댄스 리듬감&발재간 능력치 올리기 딱 제격인 "
        "수업 10/21 발표회(선택사항) 7:30~8:20 6주간 총 4곡 매시간 복습",
    ),
    (
        # A six-week course priced at 159,000원 that names a 소셜성향반 and
        # a 소셜반 among its twelve subjects.
        3831,
        "월라틴 강습 프로젝트 7",
        "2026-09-28 전체일정 2026-09-28,2026-10-12,2026-10-19,2026-10-26 "
        "일정정보 6주 과정 매주 월요일 6시20분-9시15분 장소 라틴 강의 소개 "
        "MONDAY LATIN 월라틴 강습 프로젝트 7 9월 28일 월요일 대개강 / 6주 "
        "📌 강습 안내 6주 자유 이용권: 159,000원 한 과목 수강: 99,000원 "
        "🕕 1교시 18:20 ~ 19:15 🕖 2교시 19:20 ~ 20:15 칸 & 아만다 선바 "
        "소셜성향반 🕗 3교시 20:20 ~ 21:15 스패로우 & 벨라 무중력 선바 소셜반",
    ),
    (
        # "입장료 별도", "수업 후 연습소셜" - a four-week course at 5만원.
        3827,
        "살사 & 바차타 초중급클리닉반",
        "2026-09-06 전체일정 2026-09-06,2026-09-13,2026-09-20,2026-09-27 "
        "일정정보 오후 5시~6시 장소 홍턴 강의 소개 살사 & 바차타 초중급 "
        "클리닉반 - 시간: 오후 5시~6시 - 장소 : 홍턴 지하2층 B룸 - 금액: "
        "4주 5만원 - 입장료 별도 - 수업 후 연습소셜 진행",
    ),
]


# --- E. The weekly roundups a text-only rule takes ------------------------
#
# Three other sources, none of which carries a category. Each lists three or
# four different nights, at different venues, on different days, beside the
# week's courses; each names a social, a DJ and a clock. All are CLASS today
# and hold no events row, and there is no one date any of them could be
# given. They are the measured cost of the rule that was rejected.
WEEKLY_ROUNDUPS = [
    (
        231,
        "[8월 첫째 주]40도 폭염을 이기는 우리의 춤 열정! 🔥💦",
        "1️⃣ 8/5(오늘!) 수보니따: 원준&아만다 바차타 공연반 절찬리 추가 모집 "
        "중! ✨ [수업 소식] 바차타 공연반 (8~9 PM) 소셜 오픈: 밤 9시부터 "
        "DJ 셀리 님과 함께 달립니다! (살사 3 : 바차타 3) 포트럭 파티: "
        "2️⃣ 8/7(금) 홍턴 정모: 불금은 오직 춤으로 승부! 'Only Social' "
        "소셜 오픈: 밤 9시",
    ),
    (
        3175,
        "[부산_탱고동호회]가또땅고 7월 넷째주 이열치열...",
        "7/20(월)_8:00~11:00pm 군무 전체 연습 (일빠) 7/22(수)_8:00~9:10pm "
        "① 소고귀ⓨ애비's 한곡완성반 3주차 (미오) ② 좐슨ⓨ버드's 초중급 6주차 "
        "(아미고 큰홀) [포트럭 쁘롱가] 9:15~11:15pm (DJ 롭로이) "
        "7/23(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica "
        "7/26(일)_아미고 큰홀 ① 3:20-4:30pm 좐슨y버드's 밀롱가 6주차 "
        "#부산소셜 #부산소셜댄스 #소셜댄스",
    ),
    (
        168,
        "★★★ 부에나 이번 주 주말 일정 - 주말이 기다려지는...",
        "❤ 9/4 금요일 불금 소셜데이~ DJ : 카르디 시간 : PM 9:00 ~ AM 5:00 "
        "아톰&선녀 바차타 무료 오픈강습 : 8시~9시 "
        "---------------------------------------- ❤ 9/5 토요일",
    ),
]
