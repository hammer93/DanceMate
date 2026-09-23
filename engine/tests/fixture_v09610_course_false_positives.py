"""v0.96.10 Production regression set: courses on display as dance nights.

The social family's version of the question v0.96.5 and v0.96.7 already
answered for the milonga family. ``social_evidence()`` returns True the
moment a 소셜 or a 파티 appears in the heading, or beside a clock anywhere in
the body, and ``classify()``'s CLASS branch defers to it without ever asking
whether the post is selling the course itself - the check
``announced_night_evidence()`` has made since v0.96.5. Ten Production items
reach a reader through that gap.

Measured read-only on Production fe212b2 / 0.96.9 / engine 0.95, fully
converged (re-extract outdated 0, failed 0; normalization remaining 0,
FAILED 0; 741 events, 664 visible, 162 public upcoming), over all 2,345
collected items, each classified the way the runtime classifies it - its own
``known_event_type``, its source's Settings event terms, and the title and
body ``engine_ingest._to_raw_post()`` would hand the engine.

**Two of the ten are upcoming right now**, which is the whole difference
between a dirty archive and someone paying for a six-week course expecting a
night out: item 186 ("Lv3.린디베이직💚 강습 신청", 2026-09-26) and item 3746
("대회실전 트레이닝", 2026-10-11, sold as "3회 12만원 / 1회 4만원").

**Why text alone cannot do it, and what does.** Three of these - "오스틴 &
카이닝의 살사 소셜 트레이닝", "위드라틴 살사 진짜소셜 시즌8", "살사
소셜패턴" - name a social in their own titles and are lessons *about*
dancing at one. Nothing in their text separates them from "서울살사위크
소셜이벤트" or "[월간 슬로우 소셜파티_SlowJam 12월12일]", which are real
nights; every rule that catches the first three was measured to cost at least
one of the second. danceinfo.net had already sorted them - it files every
listing under a category of its own and the collector was dropping it. That
is ``SOURCE_FILED_AS_A_COURSE`` below, and it is the only reading admitted to
outrank a social named in a heading.

The other seven are separated by the post's own title plus the logistics
tests already in the classifier - ``notice_evidence_bundle()``,
``party_evidence_bundle()``, a night named in the title beside its own clock.

``NIGHTS_THAT_TEACH`` is the casualty set a cruder rule produces, and every
member of it is asserted untouched. It is not decoration: a
"title sells a lesson AND course evidence anywhere" veto - the obvious
symmetric port of the milonga family's rule - was simulated first and
catches one of these ten while destroying item 136, whose own body carries
커리큘럼 and whose two dated socials are the reason it is an event at all.

Each entry is ``(ref, title, body)`` where ``ref`` is the Production item it
was taken from. Bodies keep the real *shape* - the label order, the
separators, the clock and date forms, the words that decide the reading -
and are trimmed of the long prose around them, truncation marks and all,
because a truncated body is what the classifier actually reads. Contact
numbers are replaced.
"""

# --- A. Courses the source itself has already filed as courses -------------
#
# danceinfo.net's own category, carried by the collector since v0.96.10 as
# RawPostRecord.source_category. Every one of these three classifies as an
# event at engine 0.95 and holds a visible Production events row; all three
# name a social in their own title, and all three are lessons.
#
# Their bodies are the site's own og:description - the category is in there
# as prose ("· 살사 · 강습 ·"), which is exactly why reading it back out of
# the text was measured and rejected: on the 70 stored danceinfo items that
# recovery agrees with the site's own answer 67 times, is blind twice and is
# WRONG once (item 872, filed 강습, whose description reads 출빠정보/정모).
# A structural signal recovered from prose 96% of the time is the Naver
# known_event_type mistake wearing different clothes.
SOURCE_FILED_AS_A_COURSE = [
    (
        2240,
        "오스틴 & 카이닝의 살사 소셜 트레이닝",
        "오스틴 & 카이닝의 살사 소셜 트레이닝 · 오스틴 & 카이닝 · 2026-08-12 · "
        "살사 · 강습 · 보니따 · 소셜연마반 오스틴 & 카이닝의 살사 소셜 트레이닝 "
        "매주 2시간 시즌10 : 8월12일 ~ 9월4일 4주 집중과정 시즌11: 9월9일 ~ 10월…",
    ),
    (
        2242,
        "위드라틴 살사 진짜소셜 시즌8 대한민국 패턴 탑10",
        "위드라틴 살사 진짜소셜 시즌8 대한민국 패턴 탑10 · 유부장 & 나나 · "
        "2026-09-17 · 살사 · 강습 · 뉴욕바 · 위드라틴 살사 진짜소셜 시즌8 지금 "
        "강남에서 가장 핫한 그 살사 CBL부터 전혀다른 진짜 On2 위드라틴 진짜소셜 "
        "Day 뉴욕 현지 느낌 그대…",
    ),
    (
        2257,
        "살사 소셜패턴",
        "살사 소셜패턴 · 보라 & 앤써니 · 2026-09-19 · 살사 · 강습 · 서울(홍대) · "
        "9월19일부터 10월31일까지 매주 토요일 5주간 진행되는 살사 강습입니다. "
        "장소는 추후 공지 예정이며, 수업비는 9만원이며, 선입금 시 할인…",
    ),
]

# --- B. Courses whose own title sells the course ---------------------------
#
# No source category here - a Daum community cafe and a tango calendar. What
# is left is the post's own heading, and a social that appears only beside a
# clock in the body: "⏰매주 토요일: 16:00~18:00 (소셜타임 18:00~22:00)" is
# the hall's standing Saturday slot written into a course timetable, not an
# announcement. Items 186/187/196 are three of the twenty-three posts their
# source has ever published and the only three that became events; a fourth
# of the identical shape ("LV1. 지터벅 82기 신청 모집", item 188) never did,
# because its search snippet happened not to reach the parenthesis.
TITLE_SELLS_THE_COURSE = [
    (
        186,
        "Lv3.린디베이직💚 강습 신청",
        "대상: Lv.2 린디입문 과정 이수자 또는 스윙경력 4개월 이상 ✅ 강사 소개 "
        "🕺리더강사...5, 9/26) ⏰매주 토요일: 16:00~18:00 (소셜타임 18:00~22:00) "
        "📍장소: 강습 인원...",
    ),
    (
        187,
        "Lv4.린디플러스💚 강습신청",
        "대상: Lv.3 린디베이직 과정 이수자 또는 스윙경력 6개월 이상 ✅ 강사 소개 "
        "🕺리더강사...매주 토요일: 16:00~18:00 (소셜타임 18:00~22:00) 📍 장소: "
        "미정, 강습 인원...",
    ),
    (
        196,
        "LV1.지터벅(왕초보반) 81기 모집🌱",
        "조금 다른 리듬이 필요한 사람, 이번엔 스윙댄스 어때요? 처음이어도 "
        "괜찮습니다...8월 1일 (6주간) ⏰ 매주 토요일: 16:00~18:00 "
        "(소셜타임 18:00~22:00) 📍 장소...",
    ),
    (
        2385,
        "수원 서울 남부에서 탱고 배우기(26.04.03)",
        "수업: 탱고 실전패턴 시간: 16:00 ~ 17:00 수업: 밀롱가 특강 시간: 17:00 ~ "
        "23:00 [서울 방배] 장소: 라비다 스튜디오(서초구 방배천로 60, 지하1층 "
        "라비다 스튜디오) 문의: 010 **** **** 수업...",
    ),
]

# --- C. A title that trains, over a block of sessions priced as a block ----
#
# "트레이닝" is not admissible on its own and the test below proves it: item
# 2367 is a real Friday practica written in the same word. What separates
# them is that this one sells three sessions for 120,000 won and names a
# dated block; the practica sells nothing.
TRAINS_OVER_A_PRICED_BLOCK = [
    (
        3746,
        "대회실전 트레이닝",
        "2026년 10월 11일 시간: 15:00~18:00 장소: 탱고빠시온 지역: 서울 "
        "입장료: 3회 12만원 / 1회 4만원 일 3회(10/11·18·25) 3:00~6:00PM · "
        "빠시온 · 대회·밀롱가 실전 시뮬레이션 · ①첫 곡 안정 워킹·다이내믹 "
        "회전·파트너 에너지 교환 ②둘째 곡 표현·다이내믹·좁은 공간 피겨 "
        "③즉흥·공간 제어·시퀀스 정리·전체 복습·개별 피드백 ④실제 대회/밀롱가 "
        "3곡 리허설 · 문의 페메 or 010 **** ****",
    ),
]

# --- D. Nights that teach, and must stay nights ----------------------------
#
# Each one carries class evidence a cruder rule would refuse on. Items 221
# and 136 are the real boundary: both sell a lesson in their own heading and
# both are nights. (Item 256 sells one too and is deliberately *not* a night
# - it has its own set, LEFT_ON_THE_LINE, below.)
#
#   221  a social named in the title outranks the 특강 beside it
#   136  a workshop weekend whose two socials are dated, timed and in a
#        named hall - notice_evidence_bundle() reads that, and it is the
#        one thing keeping it apart from item 186's parenthesis
#   2303 a 포토파티 with a free open class attached
#   145  a monthly slow social party that prices its own 수강료 for the
#        40-minute workshop inside it
#   2255 the 오픈강습 boundary: danceinfo files it under a category this
#        release deliberately does not map, so it classifies as it always has
NIGHTS_THAT_TEACH = [
    (
        221,
        "금요소셜데이♡챔피온 칸쌤 특강♡인천살사엘마르 금요...",
        "금요소셜데이♡인천살사엘마르 금요정모 8월28일♡ 금요일에는 엘마르 "
        "소셜데이! 특별히 이번주에는 챔피언 칸쌤의 특강이 있는 날입니다. 잘생긴 "
        "칸쌤과 함께 특강부터 소셜 + 뒤풀이까지 즐거운 엘마르하세요♡ 모두 함께 "
        "만나요^^",
        "SOCIAL_WITH_CLASS",
    ),
    (
        136,
        "🌊BAL&SHAG 스페셜 워크샵 in 대전",
        "🌊BAL&SHAG 스페셜 워크샵 in 대전 소셜에서 바로 써먹을 수 있는 무브를 "
        "기본 커리큘럼으로 하여, 단순한 패턴 암기가 아닌 리딩과 팔로잉의 원리를 "
        "다룹니다. ✳️ 강사: 랭보&홍지 ✳️ 일정 8/8 (토) - 15:00-16:30 발스윙 "
        "중고급 - 16:45-18:15 쉐그 초급 - 20:00-22:30 소셜 8/9 (일) - "
        "13:00-14:30 슬로우발 - 14:45-16:15 쉐그 초중급 - 16:30-19:00 소셜 "
        "✳️ 장소: 대전 스윙잇 댄스홀 ✳️ 강습 난이도 - 발스윙: 동호회 중급 "
        "강습 이수자 수강 가능",
        "SOCIAL_WITH_CLASS",
    ),
    (
        2303,
        "🌈인천 살사 바차타 엘마르🌈8월 포토파티/8월 22일(토)/"
        "추이y하비비쌤의 무료 오픈강습",
        "",
        "SOCIAL_WITH_CLASS",
    ),
    (
        3715,
        "추석 연휴 전야제! SDA & 올라틴 미니 파티 🌕 정모는...",
        "안녕하세요~ 남반장입니다!!! 이번 주 수요일은 추석 전야제로 엄청나게 핫할 "
        "예정입니다! 스페셜 특강: 저녁 8시부터 9시까지 살사 특강이 진행됩니다. "
        "소셜 오픈 및 막강 DJ 진: 밤 9시부터 메인홀이 바차타 3, 살사 3 비율로 "
        "오픈됩니다. 2️⃣ 9/25(금) 홍턴: 추석 이벤트 릴레이 워크샵: 저녁 7시 "
        "'핸슨살사 샤이닝 샤인', 저녁 8시 'Salsa shine with music' 수업이 "
        "릴레이로 준비되어 있습니다. 소셜 오픈: 밤 9시부터 마루가 개방되며",
        "SOCIAL_WITH_CLASS",
    ),
    (
        2079,
        "홍턴 추석 이벤트",
        "클럽 오픈 오후 8시 DJ BLD & DJ 나리 워크샵+소셜 20,000원 / 소셜 "
        "12,000원 🔥 9월 25일(금) | 추석 살사데이 라틴으로 더 풍성한 한가위! "
        "오후 7시 핸슨 — 핸슨살사...",
        "SOCIAL_WITH_CLASS",
    ),
    (
        3643,
        "💢대전까미니또 초고급밀롱가",
        "🥳 내일은 행복한 월요일! 💢대전까미니또 초고급밀롱가💢 모두모두 "
        "함께해요 ●수업 7시~7시50 💢밀롱가 8시~10시30 멋진음악ㅡ월광님 "
        "💜선배님들 많이 와주세요 ❤️입문ㆍ초중급반 ㅡ편한마음으로 수업하러 "
        "오세요",
        "MILONGA_WITH_CLASS",
    ),
    (
        145,
        "[월간 슬로우 소셜파티_SlowJam 12월12일]",
        "[월간 슬로우 소셜파티_SlowJam 12월12일] 분위기는 파티처럼, 입장료는 "
        "그대로! 🎧 3인 3색 DJ 라인업 >> 40분 집중 워크샵 시간: 22:20-23:00 "
        "주제: Slow & Blue 신청: 얼리버드 신청시 or 현장 수강료: 소셜시 5,000/ "
        "강습만 10,000 ■When? 12월12일(금) 23-02시 ■Where? 스윙타임 (현납 "
        "11,000원 // 얼리버드 신청 별도)",
        "SOCIAL_WITH_CLASS",
    ),
]

# The post v0.96.5 deliberately left on the line, and this release leaves
# there too: a real, dated, timed night whose own *title* offers a free
# lesson an hour before it. Reading it would mean letting a title say 강습
# and still announce - the one widening that could also rescue an advert. It
# is in the protection set because it must not MOVE, in either direction.
LEFT_ON_THE_LINE = [
    (
        256,
        "♥️9월 13일(SUN) 비비밀 AM 밀롱가 + 살바 무료강습🎁🥰",
        "🔥 9월에 두번째 일요일인13일에 비비밀 합니다‼️ 🔹️ 6:30-10:30pm "
        "피스타🔹️ ♥️ 와인 무료제공 살바도 궁금하신 분들을 위해 이번에는 6시 "
        "살바 무료강습을 선물로 준비했으니 꼭 일찍 오셔서 들으세요!",
        "CLASS",
    ),
]

# A real Friday practica written in the same word item 3746 is - the reason
# 트레이닝 is never admitted on its own. It sells nothing and prices nothing.
TRAINS_BUT_IS_A_NIGHT = [
    (
        2367,
        "[방배 금요쁘락] 5/22 Dani's 라비다 쁘락띠까 바디 트레이닝 & 가이드 ....",
        "사당 방배 탱고피플 : 네이버 블로그",
        "MILONGA",
    ),
]

# --- E. Listings danceinfo files as nights, which must stay nights ---------
#
# "출빠정보/강습" is a night that also teaches and stays a night; both of the
# danceinfo events that were public upcoming when this was measured are in
# that category. The compound label is why the mapping reads the site's own
# numeric key and never a substring of the name.
SOURCE_FILED_AS_A_NIGHT = [
    (
        3734,
        "서울살사위크 소셜이벤트",
        "서울살사위크 소셜이벤트 · 제이오 & 핸슨 · 2026-09-30 · 살사 · "
        "출빠정보/강습 · 강턴 · 9월 30일부터 10월 3일까지, 4일간의 소셜이벤트 "
        "서울살사위크가 열립니다. 아시아 최정상의 디제이분들과 함께합니다!! "
        "4일간의 소셜, 6개…",
        "SOCIAL_WITH_CLASS",
    ),
    (
        3735,
        "매주 수요일 1시~4시 편안한 분위기의 낮 밀롱가",
        "매주 수요일 1시~4시 편안한 분위기의 낮 밀롱가 · 2026-09-23 · 탱고 · "
        "출빠정보/강습 · 또도땅고 · 또도땅고에서 매주 수요일 1시~4시 편안한 "
        "분위기의 낮 밀롱가 “씨엠쁘레“ milonga siempre 가 진행됩니다. 늘 같은 "
        "자리에서, 새…",
        "MILONGA_WITH_CLASS",
    ),
]

# The 오픈강습 boundary, left exactly where it was. danceinfo maps this to
# no reading at all (see danceinfo_discovery._CATEGORY_BY_IDX), so the post
# classifies by its own text, and its text names a 파티 in the heading.
OPEN_CLASS_BOUNDARY = [
    (
        2255,
        "바사라 25주년 빅파티 감사특강",
        "바사라 25주년 빅파티 감사특강 · 바사라 & Valentina · 2026-09-12 · "
        "살사 · 오픈강습 · 홍턴 · 안녕하세요~! 바사라입니다~! 8.29/30 일 양일간 "
        "여러분이 보여주신 사랑과 성원에 조금이라도 보답하고자, 감사특강을 "
        "준비했습니다~! 핫하…",
        "SOCIAL_WITH_CLASS",
    ),
]

# --- F. Named in the brief and NOT fixed here, on purpose -----------------
#
# Item 2909's classification without a prior is already CLASS; it holds an
# events row only because its Naver source hands every item it collects a
# source-level known_event_type, which classify() returns before any of this
# release's rules are reached. That is the Naver structure-trust defect the
# v0.96.10 audit measured and deliberately did not select - 81 false
# positives, every one of them past-dated, none upcoming - and correcting it
# here would mean weakening a prior that 119 of Production's 162 public
# upcoming events depend on. The item is held here so the day that prior is
# fixed, this one is already asserted.
NOT_FIXED_HERE = [
    (
        2909,
        "부산살사+부산바차타=라라라살사] G-YA 트레이닝 클래스 (1월 8일 개강)",
        "라라라 정모에서 여러분들의 가슴을 설래게 했던 지야 선생님의 공연 "
        "여러분들도 함께 하실 수 있습니다!!! 2025년 1월 8일 (수요일) 첫 개강!!! "
        "춤 동작들을 넘어선 지야쌤의 춤에 대한 가치관과 음악에 대한 존중까지...",
        "SOCIAL",  # what the prior makes it
        "CLASS",   # what the text alone says, before and after this release
    ),
]
