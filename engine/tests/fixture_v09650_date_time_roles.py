"""v0.96.50 fixtures: the posts behind DATA-01, DATA-02 and DATA-04.

Each REAL_* text is a stored Production body (source_item_content.extracted_text,
read 2026-10-23 05:38 KST from the pg_dump of that time), cut to the passages
the extraction reads. Bank accounts, account holders' names and e-mail
addresses are removed; nothing else is reworded.

* REAL_NEOSWING_PERFORMANCE - item 6155, https://cafe.daum.net/neoswing/EBv/1735,
  published 2026-10-12. Stored as three events: 1629134 (10/25), 1629133 (10/20)
  and 1629132 (10/22). The party is 10/25; 10/20 and 10/22 are deadlines.
* REAL_NEOSWING_TICKETS - item 6153, https://cafe.daum.net/neoswing/EBv/1737,
  published 2026-10-12. Stored as 1629137 (10/25) and 1629136 (10/22, the
  pre-sale and refund deadline).
* REAL_NEOSWING_HELPERS - item 6154, https://cafe.daum.net/neoswing/EBv/1736.
  Stored as 1614511 (10/25), correctly; its 10/23 is the volunteer sign-up
  deadline and its 오후 3시 the volunteers' call time.
* REAL_TIMEBAR - item 6826, https://cafe.daum.net/sweetyswing/5lqO/1797,
  published 2026-10-22. Stored as 1629719 at 20:15-22:15, the DJ's set; the
  social opens at 19:30.
* REAL_LUXURY_PARTY - item 6644, https://danceinfo.net/lessons/5798 (no
  published date). Stored as 1629611 with no time; its only clock is "PM 9".
* REAL_IMSALSA - item 6646, https://danceinfo.net/lessons/5795. Stored as
  1629615 with no time: its own field says 오후 8시 (the class) and the body
  오후 9시 (the social). Which one a 정모 "starts" at is not something the text
  settles, so it stays unknown.
"""

NEOSWING_PUBLISHED = "2026-10-12T00:00:00+09:00"

REAL_NEOSWING_PERFORMANCE = (
    "[141기]졸업파티 공연 신청 안내",
    "안녕하세요. 네오스윙 운영진입니다. :) 10/25(일) 141기 졸업파티에서 자리를 빛내 주실 "
    "공연팀을 모집합니다! 졸업파티 공연 신청과 관련하여 아래 STEP 1, 2, 3를 참고해 주세요. "
    "*. 리허설 당일에 리허설 순서를 정하지 않습니다. 사전에 정할 예정입니다. *. 리허설 순서를 "
    "정해야 하는 관계로 공연 신청 마감이 빨라집니다. *. 일정이 빡빡한 관계로 각 마감 시한을 주의 "
    "깊게 봐주시기 바랍니다. [STEP 1] 공연 신청 댓글 작성 : ~ 10/20(화) 1. 신청 대상 : 지터벅, "
    "린디합 입문, 린디합 초중급 등 강습 및 축하공연 등 * 리허설 및 본 공연 시작 시간은 추후 "
    "재안내 드릴 예정입니다. 2. 신청 방법 : 댓글로 공연 내용 및 지원금을 받을 계좌번호 기재 "
    "3. 신청 기한 : 2026년 10월 20일(화) 23시 59분까지 * 댓글 수정은 신청 기한 이후에도 "
    "가능합니다. * 졸업파티 포스터 시간표의 빠른 제작과 공지를 위해 8월 18일(화) 이후에는 "
    "공연신청을 받지 않습니다. 4. 인원 변동이 발생할 경우 신청한 댓글의 대댓글로 수정해 주시고, "
    "반드시 운영진에게 알려주시기 바랍니다. [STEP 2] 공연 음악 전송 : ~10/22(목) 졸업공연 "
    "음악의 경우, 바로 실행할 수 있는 음원(파일) 형태로 저장하여 아래 이메일로 전송 "
    "[STEP 3] 연습실 후기 작성 및 공연지원금 수령 : ~ 11/ 1(일) 1. 지원금액 (1) 정규강습 "
    "졸업공연팀 - 기본 인당 5,000원 지원 2. 지원금 지급 시기 - 공연 지원금은 졸업파티 이후에 "
    "지원됩니다. 142기 강습 시작 전 - 11/ 1(일)까지 올려주시길 바랍니다!",
)

REAL_NEOSWING_TICKETS = (
    "[141기] 졸업파티 입장티켓 사전 구매 안내",
    "안녕하세요. 네오스윙 운영진입니다. 10월 25일(일)에 있을 141기 졸업파티 입장 티켓 사전 구매 "
    "신청을 받습니다. 사전 신청 마감은 10월 22일 목요일 23시까지이며, 마감 기한까지 입금하지 "
    "않으신 분들은 자동으로 현장납부처리 예정입니다. 자세한 내용은 아래를 참고해주세요. "
    "▶ 141기 졸업공연 입장료 1. 사전신청 : 22,000원(빠입장료 13,000원 + 전체 뒤풀이 9,000원) "
    "2. 현장납부 : 27,000원 3. 지인(비스윙댄서) : 3,000원 (현장 구매만 가능) 4. 생일자 빠 "
    "입장료 무료 : 10/19 ~ 10/25 생일자 빠 입장 무료 (전체 뒤풀이 비용은 내셔야 합니다) "
    "▶ 특이사항 1. 141기 졸업파티는 졸업 공연 + 전체 뒤풀이 통합 형태로 진행됩니다. "
    "* 졸공파티 환불 기간 : 10월 22일(목) 23시까지(환불게시판에 작성해주세요.) ▶ 참고사항 "
    "1. 타임테이블 ❌예상 타임라인이므로 현장 상황에 따라 변동될 수 있습니다.❌ - 15:00 리허설 "
    "- 17:00 재입장 - 17:30 졸업 공연 시작 - 19:00 졸업 공연 마무리 - 19:00 소셜 & 뒤풀이 시작 "
    "- 21:00 종료 2. 드레스코드 : ~핼러윈~",
)

REAL_NEOSWING_HELPERS = (
    "[141기] 졸업 파티 도우미 모집",
    "안녕하세요. 네오스윙 운영진입니다. 10월 25일에 열리는 141기 졸업파티 행사 진행을 도와주실 "
    "도우미 여러분을 모집합니다. 1. 지원방법 본 게시글에 공개 댓글 2. 모집기간 2026년 10월 "
    "23일(금)까지 분야별 신청(선착순 마감) 3. 제공혜택 졸파 당일 무료입장 + 빠티켓 1장 "
    "4. 모집분야 - 영상촬영 도우미 : 3명 * 활동시간 : 졸업공연 당일 오후 3시 ~ 졸업공연 행사 "
    "종료까지 (전체 뒤풀이 해당 안됨)",
)

REAL_TIMEBAR = (
    "■ 스윙타임빠 (10월 24,25일) 토,일 소셜 공지",
    "■ 스윙타임빠 (10월 24,25일) 토,일 소셜 공지 - 토요일 저녁 7시30분부터 소셜이 진행 됩니다. "
    "DJ '가츠' PM 8:15~10:15 - 일요일 저녁 7시30분부터 소셜이 진행 됩니다. 1부 DJ '메이져' "
    "PM 7:30~9:00 2부 DJ '메이져' 9:00~10:30 ■ 타임빠소셜 실시간 스트리밍 서비스 안내 수, "
    "일요일 소셜은 스윙프렌즈 유튜브채널에서 실시간으로 현장을 보실수 있습니다.",
)
TIMEBAR_PUBLISHED = "2026-10-22T13:13:16.000+09:00"

REAL_LUXURY_PARTY = (
    "Salsa Basis Luxury Party",
    "2026-10-23 전체일정 2026-10-23 일정정보 PM 9 장소 홍턴 DJ 헤이즐 강의 소개 협찬 남성잡지 "
    "맥심 DRESS CODE - LUXURY + GOLD 입장료 : 12,000원 (예매기한 10/21까지) 예매 필수, "
    "다음카페 댓글",
)

REAL_IMSALSA = (
    "아임살사 정모",
    "2026-10-23 전체일정 2026-10-23 일정정보 오후 8시 장소 EDM 댄스스튜디오 DJ Willy 강의 소개 "
    "(스타)10월 23일 금요일! 아임살사 정모 (효과)파티 같은 정모 안산의 살사 아지트, 아임살사에서 "
    "만나요(효과) 오후 8시 | 살사 정규강습 Lv3 다크써클 & 에스떼 🕘 **오후 9시 | 소셜타임 "
    "🎧 Special DJ Willy ✔ 정모 입장 10,000원 (음료 포함) ✔ 강습 참여 5,000원 (음료 별도) "
    "📍 장소 안산시 상록구 샘골로 180, 지하 2호 EDM 댄스스튜디오 (아임살사)",
)
