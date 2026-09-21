"""v0.96.5 Production regression set: nights lost to a body that also teaches.

Measured on Production after v0.96.4's 0.92 re-extraction had fully converged
(1,180 stored bodies, 0 remaining, 0 failed), so none of this is a stale-
extraction artefact. A read-only pass over all 2,267 collected items found
one classification defect and one only:

  a post whose own *title* names a real night produced no candidate at all,
  because somewhere in its body a lesson is mentioned - the milonga's own
  warm-up ("7:30 오픈강습"), a beginners' round starting the same week
  ("72기 왕초급 강습이 시작됩니다"), a visiting couple's workshop ("금토일
  워크샵은 마감"), even an instructor's CV line ("20여년 강습경력").

``classify()`` reads every one of those as CLASS, and ``EVENT_CLASSIFICATIONS``
does not hold CLASS, so ``process_discovered_post()`` returns ``events=[]``.
Twelve real nights on Production as the runtime reads it, one of them still
upcoming today; six more of the same aggregator shape are rescued by the
same rule but already reach MILONGA through their collector's own
``known_event_type``, so they are held here as fixtures rather than counted
as losses (1304, 2103, 2123, 2132, 2272, 2805).

What makes this hard is the other direction, and both sides are here: a
lesson advert names the milonga it teaches you to dance at, in its own title,
next to its own date. ``RESCUED`` and ``STAYS_A_CLASS`` are the two sides of
exactly that line; ``AMBIGUOUS`` is the one post that sits on it.

Each entry is ``(ref, title, body, published)`` where ``ref`` is the
Production item it was taken from. Bodies keep the real *shape* - the label
order, the separators, the clock and date forms, the words that decide the
reading - and are trimmed of the long prose around them. Every personal name,
account number and contact is replaced; acquisition had already redacted the
phone numbers.
"""

# --- A. Real nights, lost to a lesson mentioned in the body ----------------
#
# Every one of these classified CLASS with zero candidates on Production at
# engine 0.92 and must classify as an event.

RESCUED = [
    # item 968 / 1264 / 1311 / 2103 / 2805 - one weekly series from an
    # aggregator's own listing page. The night is the whole post; the class
    # is the half-hour warm-up in the recurrence line.
    (
        "968",
        "milonga_tu",
        "2026년 9월 3일 시간: 20:00~00:00 장소: O Nada 지역: 서울 "
        "DJ: 시스루 주최: Mickey y Elfin 7:30 오픈강습",
        "2026-08-27",
    ),
    (
        "1264",
        "milonga_tu",
        "2026년 9월 10일 시간: 20:00~00:00 "
        "장소: O Nada (오나다) (서울 마포구 동교동 200-29 B1) 주최: Mickey y Elfin "
        "반복: 매주 목요일 7:30 오픈강습\n"
        "매주 목요일 저녁 8시부터 12시까지! 오나다 밀롱가에서 만나요 💃🕺\n"
        "원문 링크: https://www.instagram.com/milonga_tu/",
        None,
    ),
    # item 1976 / 2123 / 2132 / 2272 - a weekly afternoon milonga whose own
    # recurrence line names the workshop that runs the hour before it.
    (
        "1976",
        "Milonga Dorada",
        "2026년 9월 8일 시간: 15:00~17:00 장소: 탱고라이프 지역: 서울 DJ: 조르바 "
        "주최: 탱고라이프(국제 아르헨티나 탱고 아카데미) "
        "매주 화요일 | 14:00~15:00 워크숍 | 15:00~17:00 밀롱가",
        "2026-09-07",
    ),
    # item 1304 - the same shape again, a different studio.
    (
        "1304",
        "밀롱가 씨엠쁘레",
        "2026년 9월 16일 시간: 13:00~16:00 "
        "장소: Todotango (또도땅고) (서울시 강남구 신사동 637-15 대명빌딩 지하) "
        "반복: 매주 수요일 1-2시 워크샵, 2-4시 밀롱가",
        None,
    ),
    # item 2334 - the release's headline sample. A dated, timed, placed
    # Saturday night; the lesson is the club's new beginners' round, which
    # the post mentions because those beginners will be in the room.
    (
        "2334",
        "2026년 9월 19일 토요일 밀롱가 La Vida No.802 DJ 조앤",
        "저녁마다 선선한 바람이 불어 산책하기 정말 좋은 요즘이에요 😃\n"
        "이번주부터 밀롱가전에 72기 왕초급 강습이 시작됩니다. "
        "모르는 분이 밀롱가에 보인다면 환영의 인사 부탁드립니당.\n"
        "그리고 이번주는 생일밀롱가입니다. 🎂\n"
        "부산탱고 La Vida No.802\n"
        "날짜: 2026년 9월 19일 토요일\n시간: PM 07:30~11:30\n"
        "장소: 아미고스튜디오\nDJ : 조앤\n"
        "계좌: 하나은행 1[전화번호]07 [이름]\n문의: 매니저 [이름] [전화번호]",
        "2026-09-16",
    ),
    # item 3643 - the one still-upcoming loss. Names no date at all, only
    # "내일", and puts its own lesson and its own night on adjacent clocks.
    (
        "3643",
        "💢대전까미니또 초고급밀롱가",
        "🥳 내일은 행복한 월요일! 💢대전까미니또 초고급밀롱가💢 모두모두 함께해요 "
        "서로 따뜻한 마음으로~ 다정한 아브라소로~\n"
        "●수업 7시~7시50 💢밀롱가 8시~10시30 멋진음악ㅡ월광님\n"
        "💜선배님들 많이 와주세요 ❤️입문ㆍ초중급반 ㅡ편한마음으로 수업하러 오세요",
        "2026-09-20",
    ),
    # item 2045 - a practica, written out in the spelling v0.96.0 added.
    # Its class word is a call for volunteer DJs.
    (
        "2045",
        "[수쁘] 💕 2026.06.17 수요 쁘락띠까 💕",
        "[수쁘] 수요쁘락띠까\n"
        "◇시간 : 2026년 06월 17일 수요일 20:00 ~ 23:00\n"
        "◇ 장소 : 홍대 쏠땅 연습실\n◇입장료 : 3,000원(10시 이후 입장료 무료)\n"
        "◇쁘락지기 : [이름](133기) [이름](134기)\n◇수쁘 DJ : 133기 [이름]\n"
        "2026🎉 수쁘 OPEN DJ 모집합니다 🎉 향후 DJ하고 싶은데 연습이 필요하신 분, "
        "DJ 재능기부 해 주시고 싶으신분 댓글 남겨 주시면 감사하겠습니다",
        "2026-06-15",
    ),
    # item 3230 - a monthly milonga with a guest performance. Its class word
    # is one line saying the visiting couple's workshop is already full.
    (
        "3230",
        "[부산_탱고동호회]11월 월간가또 밀롱가는 11/7(금...",
        "2025년 Monthly Gato Milonga 시즌2!! 매달 첫째주 금욜에 아미고 스튜디오에서 열립니다!!\n"
        "일시: 2025년 11월 7일 금요일, 저녁 9시부터 밤 12시30분까지.\n"
        "장소: 아미고 Amigo Studio\nDJ: 알루 Alu (창원)\n입장료: 1.5만원\n"
        "공연: [이름] y [이름] (밤 10시30분 예정)\n금토일 워크샵은 마감 ☆ 문의: [전화번호]",
        "2025-11-06",
    ),
    # item 3243 / 3251 - a weekly practica whose *title* is truncated by the
    # board before the engine ever sees it, so the date in it is gone and the
    # body writes the week in words ("12월 둘째주"). What it does carry is a
    # clock, a labelled place, an admission fee and a named DJ.
    (
        "3243",
        "[부산_가또땅고] 스물다섯번째 수요 쁘롱가 with DJ...",
        "부산에서 요즘 핫한, 2시간이라 쉬지않고 달리게 되는, 모든 딴따가 2곡이라 "
        "애틋한 쁘롱가로 오셔요!!\n12월 둘째주 가또 수요 쁘롱가는 [이름] 님의 디징으로 함께 해요~♡\n"
        "9시 20분부터 입장 가능하셔유~♡♡♡\n"
        "☆ 입장료: 오천원 (개인음료 제공은 없지만 정수기 있고 주류 및 음료 제공됨)\n"
        "☆ 장소: 땅고 아미고 스튜디오 (서면 황제주차장 2층, 부산진구 부전로 34)\n"
        "[부산]금토일월화 해외댄서 워크샵 듣고 수욜은 가또 정규수업 and 쁘롱가까지!!",
        "2023-12-11",
    ),
    # item 625 - a guest couple's Sunday night. Its class word is the
    # workshop week the same couple is here to teach.
    (
        "625",
        "일요일 7시 파우스토&스테파니 그랜드밀롱가",
        "동영상에서만 만나던 그들! 이제 서울에서 만납니다!!!!\n"
        "신청은 요기 www.woc.today/fys\n"
        "Fausto & Stephanie Workshop (9.1-7)\n"
        "당일 현장결제도 가능합니다. 4인 이상은 테이블 예약 가능!!!",
        "2026-09-04",
    ),
    # item 2 - a club's own Saturday night. Its class word is the studio's
    # twenty-year teaching history, in the cafe boilerplate at the foot.
    (
        "2",
        "[대구✔️탱고카니발]💃9월 첫토의 낭만밀롱가로 초대합니다",
        "아직 여름의 잔류가 따끈한 9월의 어느날 줗은 친구들 모여 탱고 나누는 "
        "맛있는 파티 속에서\n다시 오지 않는 시간 2026.9.5.(sat) 7pm~10:30pm "
        "muse 낭만게릴라 fee 10000\n중구 동성로5길43 [대구탱고카니발]\n"
        "대구 탱고카니발 ... 대구의 레전드 탱고학원 입니다. 20여년 강습경력 /몸치갱신/자세교정까지",
        "2026-09-02",
    ),
]

# --- B. Lesson adverts that name the night they teach you to dance at ------
#
# These classify CLASS on Production and must keep classifying CLASS. They
# are the reason a bare "밀롱가 in the title" rule is not available.

STAYS_A_CLASS = [
    # item 205 - a Friday course. Names the milonga in its title, beside a
    # real start date, and still sells six lessons at a tuition price.
    (
        "205",
        "[금요특강] 26년 9월 18일 시작!! 밀롱가/땅고 실전패턴!!",
        "매주 금요일 만나는 스페한 클라스!! 수업때만 잘 따라와도~ 밀롱가에서 잘 놀 수 있다.\n"
        "매 6주마다 달라지는 커리큐럼~~\n"
        "((9월 18일 금요일부터 ~ 6회 수업(2달 과정)))\n"
        "📌금요일 8시: 실전 밀롱가 패턴\n📌금요일 9시 20분: 실전 땅고 패턴\n"
        "**** 휴강일 **** -26년 9월 25일 금요일 : 추석명절\n"
        "-26년 10월 30일 금요일 : 마스터 워크샵기간\n"
        "수강료 각 클라스 8만 8천원!! 📌풀팩 35만 2천원\n"
        "계좌번호: 부산은행 1[전화번호] 01 문의 [전화번호]",
        "2026-09-01",
    ),
    # item 3202 - a six-week course named after the night it prepares you
    # for. Its own title says 수업; its body prices the term and lists the
    # week-by-week curriculum.
    (
        "3202",
        "[부산_탱고수업]데이브y지브릴's 쁘롱가 적응 시퀀스...",
        "☆쁘롱가 적응을 위한 실전 시퀀스☆ 최대한 빠르게 소셜에 적응하기 위한 "
        "필수 시퀀스 위주의 수업을 진행합니다.\n"
        "3/15, 3/22, 3/29, 4/5, 4/12, 4/19 4:20-5:30 (70분)\n"
        "참가비용: 6주 10만원\n개강 후에는 환불이 어려운 점, 양해 부탁드립니다!!\n"
        "☆ 커리큘럼 ☆ 1주차: 축과 커넥션 그리고 아브라쏘 2주차: 히로의 역학\n"
        "Q. 부득이하게 결석하게 되면 보강이 가능한가요? A. 본 클래스는 6주간 이어지는 "
        "커리큘럼으로 진행되어 원칙적으로 개별 보강은 어렵습니다",
        "2026-02-18",
    ),
    # item 350 - a recap. Its title says 소셜, and says 영상 in the same
    # breath; is_non_event_notice() has refused this since v0.96.0.
    (
        "350",
        "#원주라틴원살사#4월1일#구미아르떼파티 소셜영상",
        "타조의 살사&바차타 스토리 : 네이버 블로그",
        "2023-04-02",
    ),
    # item 144 - a ticket bundle, priced and dated, for a weekend three
    # months away. _PRODUCT_SUFFIX has stripped "파티팩" since v0.79.
    (
        "144",
        "부산린디합위캔 BLW파티팩 오픈했어요🎉",
        "💙Busan Lindyhop Weekend💙 with [이름] & [이름] 와 함께하는 올 해 "
        "BLW (26년 5월 1-3일) 파티팩이(89,000원) 오픈 되었습니다! "
        "추첨을 통해 100프로 환불받을 수 있는 리플 이벤트 진행 중..!!\n"
        "✔신청링크 : https://linktr.ee/bslhw",
        "2026-02-09",
    ),
]

# --- C. The one post on the line -------------------------------------------
#
# A real AM milonga, dated and timed, whose title offers a free lesson an
# hour before it. Rescuing it means letting a title carry a class word,
# which is the one widening that could also rescue an advert. It classifies
# exactly as it did before v0.96.5 - CLASS, no candidate - and this entry
# exists so that stays a decision rather than an accident.

AMBIGUOUS = [
    (
        "256",
        "♥️9월 13일(SUN) 비비밀 AM 밀롱가 + 살바 무료강습🎁🥰",
        "🔥 9월에 두번째 일요일인13일에 비비밀 합니다‼️\n🔹️ 6:30-10:30pm 피스타🔹️\n"
        "♥️ 와인 무료제공\n♥️ 비비밀 음악 개편‼️ < 탱-AM-AM-AM-살-바 >\n"
        "살바도 궁금하신 분들을 위해 이번에는 6시 살바 무료강습을 선물로 "
        "준비했으니 꼭 일찍 오셔서 들으세요!\n선신청, 테이블 예약 ➡️ vivimil.com",
        "2026-09-04",
    ),
]
