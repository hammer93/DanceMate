"""v0.96.7 Production regression set: lesson adverts on display as dance nights.

The opposite direction to v0.96.5's. ``classify()``'s ``class_words`` decides
whether a post is judged as a class at all, and it knows 강습, 개강, 모집 and
워크샵 - but not 수업, 특강, 클래스, 클라스, 강좌 or 레슨, which is what a
studio actually advertises in. A course written only in those words never
reached the CLASS branch; it fell through to the milonga/social keyword test
and became a plain MILONGA or SOCIAL, because a lesson advert names the night
it teaches you to dance at - "밀롱가 & 발스" on the last line of a six-week
syllabus, "Milonga Autumn Edition" over a three-week rhythm course, "밀롱가
집중 클라스" in a title.

Measured read-only on Production f147af7 / 0.96.6 / engine 0.93, with the
0.93 re-extraction fully converged, over all 2,298 collected items, each
classified the way the runtime classifies it (its own ``known_event_type``,
its source's Settings event terms). 121 items carry one of those words and
classify as an event today; 82 of them produced a real ``events`` row.

The fix cannot be the six words added to ``class_words``. That was simulated
first and rejected: it corrects 19 of the misreadings and destroys 40 further
classifications, six of them genuine nights and one of those still upcoming -
``LOST_TO_A_WORD_LIST`` below is that set, and every one of them must be
untouched. What separates them is not vocabulary but structure: both item 977
("토욜 스페셜 원데이 클래스", a six-week syllabus) and item 3127 (가또땅고's
한가위밀롱가, 20:00-24:00, DJ, 참가비 12,000원) carry a day, a place and
``notice_evidence_bundle()``. The one thing that tells them apart is whether
the post's own *title* is selling a lesson.

Each entry is ``(ref, title, body, published)`` where ``ref`` is the
Production item it was taken from. Bodies keep the real *shape* - the label
order, the separators, the clock and date forms, the words that decide the
reading - and are trimmed of the long prose around them. Every personal name,
account number and contact is replaced; acquisition had already redacted the
phone numbers. Titles are kept as Production stores them, truncation and all,
because a truncated title is what the classifier actually reads.
"""

# --- A. Lesson adverts, course schedules and notes read as nights ----------
#
# Every one of these classifies as an event at engine 0.93 and must not.
# The thirteen with a Production ``events`` row are marked; the rest produced
# a candidate that never dated, which is the same defect one step earlier.

CORRECTED = [
    # item 977 (events row, STILL UPCOMING) and item 2051 (events row, still
    # upcoming), the same six-week Saturday course collected from two
    # sources. The "event" was the syllabus's last line - 10월 31일, the week
    # the course happens to teach 밀롱가 & 발스. No clock, no venue, no night.
    (
        "977",
        "토욜 스페셜 원데이 클래스",
        "2026년 9월 5일 장소: 서울시 마포구 동교동 152-14 지하 1층 지역: 서울 "
        "9월 5일 – 다양한 바시코 9월 12일 – 아브라소의 비밀 : 팔과 어깨 "
        "9월 19일 – 바이벤을 이용한 공간의 활용법 10월 3일 – 회전을 만드는 바디 테크닉 "
        "10월 17일 – 히로와 볼레오의 응용 10월 31일 – 밀롱가 & 발스",
        "2026-09-01",
    ),
    (
        "2051",
        "9월~10월 스페셜 원데이 클래스",
        "강사 프로필 수업 안내 9월-10월에는 해외 일정으로 인해 토요일 수업을 총 6회만 "
        "진행합니다. 그래서 매 수업마다 특별한 테마를 하나씩 준비했습니다. "
        "장소 : 홍대 연습실 서울시 마포구 동교동 152-14 지하 1층 "
        "토요반 • 5pm-6:30pm 수업 • 6:30pm-7pm 연습 시간 "
        "실라부스 9월 5일 – 다양한 바시코 9월 12일 – 아브라소의 비밀 : 팔과 어깨 "
        "9월 19일 – 바이벤을 이용한 공간의 활용법 10월 3일 – 회전을 만드는 바디 테크닉 "
        "10월 17일 – 히로와 볼레오의 응용 10월 31일 – 밀롱가 & 발스 "
        "비용 6회 160,000원, 원데이 30,000원 "
        "일요일 고급반 • 매주 일요일 6pm-8pm 비용 5회 180,000원, 원데이 40,000원 "
        "수업 신청 방법 아래의 입금 계좌로 입금하신 후 다음 양식을 작성해 보내주시면 됩니다. "
        "수업 취소 및 환불 규정 입금 계좌 – [계좌번호] 예금주 : [이름]",
        "2026-08-30",
    ),
    # item 1968 (events row). The night is the course's own name.
    (
        "1968",
        "3주 완성! 밀롱가 리듬 클래스",
        "2026년 9월 14일 시간: 20:00~22:00 장소: Bailamos Tango 지역: 서울 "
        "주최: 엘토리토 & 엘리 "
        "Milonga Autumn Edition vol.1 — 3주 완성 밀롱가 리듬 클래스 "
        "(9/14·21·28, 월 3회). 밀롱가 리사부터 뜨라스삐에까지 — 단순히 스텝을 외우는 "
        "것이 아니라 리듬의 변화를 느끼며 자유롭게 전환하는 것이 목표. "
        "이런 분께: 밀롱가가 어렵게 느껴지는 분 · 밀롱가 리듬을 제대로 배우고 싶은 분. "
        "신청·문의는 링크로.",
        "2026-09-08",
    ),
    # items 2005 / 2012 / 2031 / 2046 (events rows) - one studio's monthly
    # 특강 series. A curriculum, a week number, tuition, a bank transfer;
    # the only night in any of them is the one the syllabus teaches.
    (
        "2005",
        "✨️6월의 목요특강✨️마라맛 비밀레시피~😋탱고의 확장...",
        "6월의 매주 목요일에는 솔로땅고 특강수업에서 처음으로 '누에보' 수업을 "
        "열게되었습니다. 특강 수강 신청서 ⬆️ "
        "💎 특강 커리큘럼 <쫄지마! 누에보> 기초~중상급 까지 올레벨 수업 "
        "1주차 : 6월 4일 꼴까다가 뭐에요? 2주차 : 6월 11일 볼까다의 활용 "
        "3주차 : 6월 18일 알고나면 너무쉬운 사까다 4주차 : 6월 25일 간초를 하면? "
        "💎 특강수업 시간 매주 목요일 솔땅연습실 pm 8시~8:30 수업전쁘락 "
        "pm 8:30 ~ 10시 수업(90분) "
        "💎 수업비 안내 수업비 ▶️ 10만원 고정커플 등록시 각 오천원할인 "
        "💎 입금계좌 [계좌번호] 입금명:목특강+닉네임 필수!",
        "2026-05-20",
    ),
    (
        "2012",
        '🎶9월의 토요특강은 "바질&엘린 🪗악단별 바리아시옹~표현...',
        "매주 토요일마다 진행되는 9월의 솔땅특강은 정말 긴~시간을 기다린 최고의 댄서 "
        "두분쌤의 특별한 4주수업이 준비되어 있습니다. "
        "⚜️9월의 토요특강! 악단별 바리아시옹🎶 표현하기! "
        "docs.google.com 수강신청서 필수 제출 ⬆️ "
        "⚜️ 커리큘럼 🪗 악단별 바리아시옹 1주차 8/29 chique (뿌글리에세) "
        "2주차 9/5 Buscandote (프레세도) "
        "⚜️ 수업일정및 시간 ( 4주 2시간씩 특강진행 ) 8월29 9월5.12.19. 매주 토요일♡ "
        "쁘락 pm 1시~ 1:30 수업 pm 1:30~ 3시 ⚜️ 수업비 : 10만원",
        "2026-05-12",
    ),
    (
        "2031",
        '⚜️9월의 목요특강 Tango is " Victor Cho 땅조 " 챔피언...',
        "2026 가을에는 솔로땅고 목요특강 에서 얼마전 치뤘던 두개의 대회에서도 우수한 "
        "성적을 거두신 한국 땅고씬의 살아있는 전설을 모셨습니다. "
        "걷기.안기.무브 그리고, 론다의 즉흥성을 강화하는 피겨의 자율성~ "
        "⚜️ 수상 경력 2024마닐라탱고 챔피언십(필리핀) 챔피언 🏆 탱고 데 피스타, 발스, "
        "밀롱가. 2026 아시아 탱고챔피언십 밀롱가, 발스 챔피언 🏆 피스타 2위 "
        "docs.google.com ⬆️⬆️ 신청서 제출 필수 ⬆️⬆️ "
        "💫 커리큘럼 \"좋은 춤은 화려한 기술이 아니라, 올바른 원리에서 나옵니다\" "
        "( 4주 2시간씩 특강진행 ) 8월 27 9월3.10.17일 매주 목요일♡ "
        "쁘락 pm 8시~ 8:30 수업 pm 8:30~ 10시",
        "2026-03-10",
    ),
    (
        "2046",
        '6월의 일요특강 "일요 기본기반..바르게 서고~편하게...',
        "지난 4,5월의 너무 좋은 내용으로 \"일요일 땅고기본기반\"을 잘 이끌어주신 "
        "두분의 뒤를 이어서 6월의 2주간. 7월의 1주 일요일은 매니저 &총무 가 수업을 "
        "하게 되었습니다 (3주간의 Tango clinic) "
        "1주차:정렬 - 축 몸의 기본구조를 다시 세우고 흔들리지 않는 개인축 만들기 "
        "2주차:분리 - 컨트롤 3주차:통합-자기 컨트롤 워킹과 회전을 연결하고 "
        "☆특강 날짜및 시간 매주 일요일 3주간 3시간씩 6월 14,21일 7월5일 pm 2시~5시 "
        "솔로트레이닝+ 안고,걷기+ 땅고기본기 수업 2시간 + 가이드쁘락 1시간",
        "2026-06-01",
    ),
    # item 3187 (events row) - a six-week course whose subject is the milonga.
    # "클라스" is the spelling this board uses; 클래스 alone would miss it.
    (
        "3187",
        "[부산_가또땅고]일요반_좐슨y버드's 밀롱가집중 클라스...",
        "이번 밀롱가집중 클라스에서는 밀롱가등의 빠른 리듬에서 리딩과 팔로우가 왜 "
        "힘들어지는지 알아보고 해법을 찾아보겠습니다 "
        "1주차- 아브라쏘,인텐션,상체의 움직임 2주차 - 리바운드 3주차 - 더블스탭 "
        "4주차 - 뜨라스삐에 5주차 - 오치또&볼레오 6주차 - 회전동작 "
        "장소 : 아미고 일정 6/7 3:20~4:30 6/14 3:20~4:30 6/21 휴강 6/28 3:20~4:30 "
        "6주 과정 개별 or 커플 등록 (커플등록시 고정파트너) 정원 10커플 예정 선착순 마감 "
        "⭐️ 참가비: 1인 10만원 ⭐️ 참가신청 기간 : 5/28(목) - 6/4(목) "
        "🌱수업 문의🌱 [전화번호]",
        "2026-05-25",
    ),
    # items 3271 / 3272 (events rows) - an eight-week course, twice.
    (
        "3271",
        "[부산_가또땅고]Lady Leaders Class_리딩을 배우고픈...",
        "\"리딩을 배우고픈 땅게라들을 위한 수업, 레이디 리더스 클래스\" 초급 8주를 "
        "마쳤습니다. 8월 20일 화요일 부터 초급심화 8주 과정 이 이어집니다!! "
        "☆초급심화 8주☆ 8/20, 8/27, 9/3, 9/10, 추석 휴강, 9/24, 10/1, 10/8, 10/15 "
        "☆초급심화 커리큘럼☆ 1주차 -편안한 아브라소와 리딩을 위한 테크닉 "
        "2주차 -오초를 통한 피봇 테크닉 8주차 -스페샬 시퀀스 "
        "8:10-8:40 자율쁘락 8:40-9:50 수업 (70분) "
        "♧ 수강료: 8주 8만원 ♧ 신청방법: 댓글 or 카카오톡 (문의 [전화번호]) "
        "[계좌번호] 카카오뱅크 (가또땅고운영계좌)",
        "2024-08-15",
    ),
    (
        "3272",
        "[부산_가또땅고]Lady Leaders Class_리딩을 배우고픈...",
        "6월 11일(화)부터 미오에서는 \"리딩을 배우고픈 땅게라들을 위한 수업, "
        "레이디 리더스 클래스 \"가 열립니다. 6/11, 6/8, 6/25, 7/2, 7/9, 7/6, 7/23, "
        "7/30 (8주 초급) 8/6, 8/20, 8/27, 9/3, 9/10, 9/24, 10/1, 10/8 (8주 초급심화) "
        "8:30-8:40 몸풀기 8:40-9:50 수업 9:50-10:30 자율쁘락 "
        "♧ 수강료: 8주 8만원 ♧ 신청방법: 댓글 or 카카오톡 (문의 [전화번호]) "
        "[계좌번호] 카카오뱅크 (가또땅고운영계좌)",
        "2024-06-05",
    ),
    # item 3273 (events row) - the same course announced in a snippet.
    (
        "3273",
        "화욜은 레이디 리더스 클래스, 13일부터 목욜 쁘락으로...",
        "일정이 남았구요. 6월 13일(목)부터는, 가또 정규 쁘락이 목요일(장소: 아미고) "
        "로...위한 수업, 레이디 리더스 클래스\"가 열립니다. 6/11, 6/8, 6/25, 7/2, 7/9...",
        "2024-06-10",
    ),
    # item 3180 (events row) - a one-off special class with a fee and a room,
    # which is a class, not a night: nothing here opens a door.
    (
        "3180",
        "[부산_가또땅고] 음악수업 푸글리에쎄 클라스",
        "[EVENT] 가또땅고 음악특강_푸글리에쎄 편 (올레벨) 🎶 음악특강 🎶 "
        "💥 뿌글리에세 악단의 역사와 히트곡 설명 💥 음악을 어떻게 '몸으로 표현'할 것인가 "
        "일시: 6월 21일(일) 3:00-4:30pm 장소: 서면 미오 Mio 참가비: 오천원 (₩5,000) "
        "현장 결제, USB지참 이벤트: 음악특강 시리즈 4회 올출시 월간가또 밀롱가 입장권 제공. "
        "신청: 댓글 or 갠톡 ([전화번호])",
        "2026-06-14",
    ),
    # item 3117 (events row) - a note written after a practica night, whose
    # title happens to name the one-day class that ran inside it.
    (
        "3117",
        "OSIK 쁘락타임 속 원데이 클래스! 그리고 2시까지 불태웠다고 한다2025.2.14",
        "이 날 막판 2시까지 남은 최종 멤버에서 홍보/영업 부장, 제조부장(소믈리에), "
        "리액션부장(사람1) 선출되었습니다 ㅎㅎㅎ",
        "2025-02-15",
    ),
    # Items with no Production events row - the same misreading one step
    # earlier, and the plainest cases of it.
    (
        "2347",
        "서울 아르헨티나 탱고 수업 | 20년 경험 앙헬탱고 전문 교육 아카데....",
        "서울 아르헨티나 탱고 수업 | 20년 경험 앙헬탱고 전문 교육... 표현 "
        "밀롱가에서 자연스럽게 춤추는 방법 앙헬탱고 정규 수업은 동작을... "
        "#아르헨티나탱고 #서울탱고 #탱고수업 #탱고배우기...",
        None,
    ),
    (
        "2374",
        "탱고 수업>, -[이름]-",
        "이미 탱고를 사랑하는 이들에게 다 선물하였다고. 하하하하핫 >.서울에서 올 등기가 "
        "없는데 이게 무슨... 원하는 걸로 선택해!\" 나의 첫 탱고수업, 뮌헨의 "
        "밀롱가(탱고 춤의 장)에서 달리 먹는 마음으로...",
        None,
    ),
    # Not a dance post at all: a guitar school teaching Cardoso's *Milonga*.
    (
        "2416",
        "[창원기타레슨] [창원 베를린 기타 학원] Milonga (춤곡) / Jorge Cardoso (....",
        "베를린 기타 전문학원 : 네이버 블로그",
        None,
    ),
    # item 2405 (events row) - a weekly guided practica sold as lesson-like
    # in its own heading, on a blocked fetch that never served a body. It
    # sits on the line and is listed here, not under AMBIGUOUS, because the
    # rule does move it; its one Production event is long past.
    (
        "2405",
        "연습인데도 수업 같고,수업인데도 부담 없는 앙헬&로레나의 월요 쁘....",
        "월요일 밤, 탱고가 가장 깊어지는 시간 앙헬 & 로레나 월요... "
        "장소 : 서울 마포구 동교로25길 49, B1 폴레폴레 스튜디오 * 힐캡을 준비해... "
        "② 8시 ~ 8시 20분 20분간 오늘의 피겨 & 시퀀스 밀롱가에서 바로 써먹을...",
        None,
    ),
]


# --- B. Real nights a word list would have destroyed -----------------------
#
# Every one of these classifies as an event today, is a genuine night (or a
# genuine festival), and turns into CLASS the moment 수업/특강/클래스/강좌/
# 레슨/수강료 are added to ``class_words``. Item 3127 was still upcoming when
# this was measured. They must be untouched.

LOST_TO_A_WORD_LIST = [
    # item 3127 - the release's own regression. A night announced as a
    # "Special Event" rather than in a scene word, so
    # announced_night_evidence() cannot see it; the class evidence is the
    # free 오픈특강 that runs before the door. Its title sells no lesson.
    (
        "3127",
        "[부산_탱고동호회]가또땅고 Special Event 9월24일(목...",
        "두둥~ 추석 연휴가 시작하는 첫날!! 9월 24일 목요일, 가또땅고 \"한가위밀롱가\"가 "
        "열립니다. 가또땅고 강사진들이 공동 오거나이징하여 춤 추기 좋은 분위기를 "
        "선사할게요~ 디제이는 부산 대표 핫핫 스톤님!!♡ "
        "* 일정 : 9월 24일 목요일 8시pm - 12시am "
        "* 장소 : 이데알 스튜디오 (700비어 서면일번가점 3층) * D J : 스톤 Stone "
        "* 밀롱가 참가비 : 12,000원 "
        "한가위 밀롱가 전에 다니엘y아이리스's 오픈특강(볼레오/간쵸)도 있으니까 많관부~♡ "
        "* 오픈특강 강사: 다니엘 킴 y 아이리스 * 오픈특강 참가비 : 12,000원 (현장결재) "
        "* 오픈특강 주제: 간쵸 + 볼레오 "
        "#가또땅고 #부산서면탱고 #부산수요일밀롱가 #부산탱고수업 #부산탱고배우기",
        "2026-09-20",
    ),
    # items 3134 / 3150 - the weekly 쁘롱가, priced at its own door, with its
    # own DJ. The class words are in the hashtag footer every post carries.
    (
        "3134",
        "가또땅고 152번째 수요뿌롱가 with DJ ALU",
        "☆☆☆오천원의 행복☆☆☆ 9월16일은 NEW 운영팀이 진행하는 3rd 쁘롱가!! "
        "모든 딴따가 2곡씩(마지막 3딴은 3곡씩)~ 입장료: 오천원 "
        "일시: 9월 16일 9:15-11:15pm DJ: ALU "
        "장소: 아미고 스튜디오 (부산진구 서면 황제주차장, 부산진구 부전로 34) "
        "9시 15분부터 입장 가능하셔유~♡♡♡ ☆ 문의: [전화번호] "
        "#탱고 #가또땅고 #부산탱고동호회 #부산탱고수업 #부산탱고배우기 #서면탱고수업",
        "2026-09-13",
    ),
    (
        "3150",
        "가또땅고 150번째 수요 뿌롱가 with DJ SUNSET",
        "부산에서 요즘 제일 핫한, 2시간이라 쉬지않고 달리게 되는, 모든 딴따가 2곡이라 "
        "애틋한 쁘롱가로 오셔요!! ☆ 입장료: 오천원 "
        "☆ 장소: 땅고 아미고 스튜디오 (서면 황제주차장 2층, 부산진구 부전로 34) "
        "* 날짜 : 09월 02일 수요일 * 일시 : 09시15분 ~ 11시15분 * D J : SUNSET "
        "* 금액 : 5000원 "
        "#탱고 #가또땅고 #부산탱고동호회 #부산탱고수업 #부산탱고배우기 #서면탱고수업",
        "2026-08-30",
    ),
    # item 2048 - a two-day championship, whose categories are named 밀롱가.
    (
        "2048",
        "D'ARIENZO CUP Korean round",
        "2026년 9월 19일 장소: PISTA (서울시 마포구 월드컵북로6길 49, B1) 지역: 서울 "
        "주최: 서커스아트컴퍼니 모빌 D'ARIENZO CUP 한국전 "
        "📅 2026년 9월 19일(토) ~ 20일(일) 신청 링크 "
        "올해는 탱고, 밀롱가, 발스, 시니어, 뉴스타 커플, 잭앤질 일반, 뉴스타 잭앤질까지 "
        "다양한 카테고리로 진행됩니다. 오랜 경험을 가진 댄서부터 첫 대회에 도전하는 "
        "참가자까지, 누구나 자신만의 탱고를 자신 있게 선보일 수 있도록 무대를 "
        "준비했습니다.",
        "2026-09-05",
    ),
    # item 3208 - a week's whole timetable: classes by the hour AND the night.
    (
        "3208",
        "[부산_탱고동호회]가또땅고 7월 마지막주 열탱즐탱...",
        "7/27(월)_8:00~11:00pm 군무 전체 연습 (일빠) "
        "7/29(수)_8:00~9:10pm ① 소고귀ⓨ애비's 한곡완성반 4주차 (미오) "
        "② 좐슨ⓨ버드's 데뷰땅뜨 한곡완성반 1주차 (아미고 큰홀) "
        "[포트럭 쁘롱가] 9:15~11:15pm (DJ 사라) "
        "7/30(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica "
        "8월 일요일 수업 휴강 노올자요~~~♡ 문의: [전화번호]",
        "2026-07-26",
    ),
    # item 3185 - a club weekend away, priced, dated and placed.
    (
        "3185",
        "[EVENT]가또땅고 2026 청춘 여름 엠티🌊🦀바다로 떠나자...",
        "작년 봄, 대학생 엠티 시즌에 우리도 떠났던 송정 엠티!! 올해도 봄에 갈 수 있을 "
        "줄 알았는데 수업도 대회도 바빠서 일정 잡기가 어려운겁니다! "
        "🐚☀️🌊가또 청춘 여름 엠티 🌊☀️🐚 📅 일시 : 7월 18일(토)~19일(일) 1박2일 "
        "🛤 장소 : 송정 펜션&민박 부산 해운대구 송정중앙로 40-4 "
        "▶ 회비 : 50,000원 (오만원) ▶ 입금계좌 : [계좌번호] "
        "신청방법 : 입금후 댓글에 닉네임/땅게라or로/숙박or당일여부/전화번호/입금완료",
        "2026-07-01",
    ),
]


# --- C. Nights that teach, and keep their heading -------------------------
#
# A night out that also sells a lesson says so in its own title, and the
# social/party rules classify()'s CLASS branch already applies keep every one
# of them an event. These carry the education vocabulary in the *title* and
# must still classify as an event - this is what stops the new rule being a
# word list of its own.

A_NIGHT_THAT_TEACHES = [
    # item 2255 - a party's thank-you special class. 파티 in the title.
    (
        "2255",
        "바사라 25주년 빅파티 감사특강",
        "바사라 25주년 빅파티 감사특강 · 2026-09-12 · 살사 · 오픈강습 · 홍턴 · "
        "8.29/30 일 양일간 여러분이 보여주신 사랑과 성원에 조금이라도 보답하고자, "
        "감사특강을 준비했습니다~!",
        "2026-09-05",
        "SOCIAL_WITH_CLASS",
    ),
    # items 457 / 464 - an anniversary party with a special class.
    (
        "457",
        "(활동) 드림발 8주년 파티 & 특강(2025.03.01 토) - 서울 신림 커플댄스 ....",
        "건강하고즐거운모임,서울 신림 커플댄스 드림발,블랑 : 네이버 블로그",
        "2025-02-20",
        "SOCIAL_WITH_CLASS",
    ),
    # item 221 - a weekly social night whose guest teaches first.
    (
        "221",
        "금요소셜데이♡챔피온 칸쌤 특강♡인천살사엘마르 금요...",
        "금요소셜데이♡인천살사엘마르 금요정모 8월28일♡ 금요일에는 엘마르 소셜데이! "
        "특별히 이번주에는 챔피언 칸쌤의 특강이 있는 날입니다. "
        "잘생긴 칸쌤과 함께 특강부터 소셜 + 뒤풀이까지 즐거운 엘마르하세요♡",
        "2026-08-25",
        "SOCIAL_WITH_CLASS",
    ),
    # item 165 - a party sold as "workshop then social".
    (
        "165",
        "💥8.16 홍턴 핫썸머 바차타파티💥",
        "🔥 [핫썸머 바차타파티] 워크숍 듣고 실전 소셜까지 완벽 마스터! 🔥 "
        "파티만 즐기기엔 아쉬웠던 분들 주목! 최고의 강진이 준비한 바차타 알짜배기 "
        "특강 듣고 바로 소셜...",
        "2026-08-10",
        "SOCIAL_WITH_CLASS",
    ),
]


# --- D. Real nights whose body is full of course words --------------------
#
# The other half of the line: no education word in the title at all, and a
# body that says 수강료, 강의 소개 or 특강 anyway. None of these may move.

A_NIGHT_THAT_PRICES_ITSELF = [
    # item 882 - a milonga's seventh birthday. The aggregator's own template
    # files the door price under the label 수강료.
    (
        "882",
        "🩷러블리밀롱가 7주년 파티안내🩷",
        "2026년 9월 12일 (토) 일정정보 5:30~9:30 장소 분당 실루엣 DJ DJ 네로 "
        "강의 소개 🩷러블리밀롱가 7주년 파티안내🩷 "
        "♡9. 12 (토) Pm5:30~9:30♡ 웃음과 설렘이 가득한 밤, 소중한 사람들과 함께 "
        "러블리밀롱가의 7주년을 축하해 주세요. 🎉🥻오픈마켓🥻🎉 🎁🎁 경품추첨 🎁🎁 "
        "🎂9월12일(토)pm5:30~9:30 🎂디제이-네로 🎂예매15,000/현매20,000 "
        "🎂실루엣-분당 정자동 연락처 [전화번호] 수강료 예매15,000/현매20,000",
        "2026-09-05",
    ),
    # item 11 - a milonga, a performance and a graduation, with a paid
    # 특강 in front of it and three separate ticket prices.
    (
        "11",
        "연서 공연과 함께하는 밀롱가 🇦🇷헨떼 아미가 코리아...",
        "⭐지노&유니 홍대 특강 + 공연 + 클럽 트로일로 8기 수료식⭐ "
        "ℹ️ 예매 안내 ✔ 8월 22일 토요일 7:30-8:45pm 지노&유니 특강 (올레벨) "
        "9pm-1am 밀롱가 헨떼 아미가+클럽 트로일로 8기 수료식 "
        "✔ 클럽 트로일로 (서울 마포구 연남로9, B1) ✔ DJ🎧 Suri Bae (Seoul) "
        "✔ 예매: 특강+밀롱가 38000원, 특강만 30000원, 밀롱가만 13000원",
        "2026-08-15",
    ),
    # item 145 - a monthly slow social whose own 40-minute workshop is priced
    # under the label 수강료, beside the door price.
    (
        "145",
        "[월간 슬로우 소셜파티_SlowJam 12월12일]",
        "[월간 슬로우 소셜파티_SlowJam 12월12일] 분위기는 파티처럼, 입장료는 그대로! "
        "🎧 3인 3색 DJ 라인업 >> 40분 집중 워크샵 시간: 22:20-23:00 "
        "주제: Slow & Blues Step by step "
        "신청: 얼리버드 신청시 or 현장 수강료: 소셜시 5,000/ 강습만 10,000 "
        "■When? 12월12일(금) 23-02시 ■Where? 스윙타임 (현납 11,000원)",
        "2025-12-01",
    ),
]


# --- E. Posts on the line, which must classify exactly as they did --------
#
# Weekly timetables, a paid guided practica, a festival's registration form:
# genuinely both things at once, or genuinely undecidable. This release does
# not move them in either direction.

UNCHANGED = [
    # item 3132 - v0.96.5's own protection sample: a week's timetable.
    (
        "3132",
        "[부산_탱고동호회]가또땅고 9월 둘째주 열탱즐탱 일정...",
        "9/14(월) 8:00~11:00pm 군무 연습 (이데알) "
        "9/16(수)_8:00~9:10pm ① 무료 일일 특강 소고귀ⓨ애비's 좁은공간 테크닉 (아미고 큰홀) "
        "② 펠릭스ⓨ듀니's 초급입문 4주차 (미오) "
        "[가또땅고 쁘롱가] 9:15~11:15pm (DJ 알루, 아미고 큰홀) "
        "9/17(목)_아미고 큰홀 8:00-11:00pm 자율연습 Practica (초급 원데이클라스) "
        "☆9/23(수) 8시 개강☆ 1. 데이브y지브릴's \"초중급2\" 문의: [전화번호]",
        "2026-09-13",
        "MILONGA_WITH_CLASS",
    ),
    # item 1246 - a paid, weekly, guided practica with a mini class inside it.
    (
        "1246",
        "둘리 가이드 쁘락띠까",
        "2026년 9월 6일 시간: 11:00~14:00 장소: El Tango (엘땅고) (서울 서초구) "
        "주최: 둘쎄 y LEO 반복: 매주 일요일 PRACTICE MAKES PERFECT! "
        "📌 프로그램 👉 11:00 – 12:20 (80분) 가이드 쁘락 (자율연습 + Q&A) "
        "👉 12:20 – 12:40 (20분) 미니 피구라 클래스 (LV.3-4) "
        "👉 12:40 – 14:00 (80분) 가이드 쁘락 (자율연습 + Q&A) "
        "💰 참가비: 10만원(2달, 8회), 6만원(1달, 4회), 당일 현장 2만원(1회) "
        "🏦 계좌번호: [계좌번호]",
        "2026-09-01",
        "MILONGA",
    ),
    # item 3265 - a week's timetable written as a list of course weeks.
    (
        "3265",
        "[3월 셋째주 가또땅또양성소 일정]",
        "3/17(월)_일빠 월쁘락(7:30~9:30pm) "
        "3/19(수)_아미고&미오&샾 8:00~9:20pm ①소닉ⓨ블랑 실전밀롱게로 4주차 (아미고 큰홀) "
        "②데이브ⓨ지브릴 뮤지컬리티 4주차 (미오) ③둠둠ⓨ페퍼 초급 종강 (샾) "
        "④ [뿌롱가] 9:30~11:30pm "
        "3/23(일)_맘보 ① 애ⓨ지 땅게라 클래스 리뷰 종강 (1:30~2:30pm) "
        "② 소고귀's 레이디 리더스 한곡완성 5주차 (2:40~3:40pm) ☆ 문의: [전화번호]",
        "2025-03-16",
        "MILONGA",
    ),
    # item 645 - a festival's registration form, four programmes in one post.
    (
        "645",
        "2024 K-TANGO SF : 신청폼",
        "* 페스티벌 신청기간 : ~ 09월 09일 23:59까지 "
        "1. Special Performance 일시 : 2024년 09월 26일 목요일 PM 19:00 ~ PM20:30 "
        "장소 : 연세대학교 대강당 "
        "3. 서울밀롱가 DAY / 사전신청금액 20,000 일시 : 2024년 09월 27일 금요일 "
        "PM 17:00~PM24:00 장소 : 서울밀롱가지정장소 "
        "4. 한강탱고축제 일시 : 2024년 09월 29일 일요일 PM16:00~PM21:00 "
        "장소 : 서울 반포 한강공원 수변무대 내용 : 탱고동호회 공연",
        "2024-09-01",
        "MILONGA",
    ),
]
