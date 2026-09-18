"""v0.96.0 before/after fixture: ~100 synthetic direct-source posts.

Every post reproduces a *form* seen on a community, organizer or venue board
in Production (OSIK, 가또땅고, 비바스윙, 올어바웃스윙, and the Miltang-side
shapes they should reconcile with) - none is a stored copy of a real post,
and none carries a phone number, an account number or a person's name.

Each entry: (title, body, published_at, expectation)
    EVENT_UPCOMING  - a real announcement of a night on/after PUBLISHED
    EVENT_PAST      - a real announcement whose night is before PUBLISHED
    NON_EVENT       - a post that must never become an event

PUBLISHED is the fixture's "today": every post is dated on it, so "upcoming"
means the announced night is on or after 2026-09-14. Relative dates resolve
against it, never against the crawl clock.
"""

PUBLISHED = "2026-09-14"

EVENT_UPCOMING = "EVENT_UPCOMING"
EVENT_PAST = "EVENT_PAST"
NON_EVENT = "NON_EVENT"

POSTS = [
    # --- tango community (OSIK / 가또땅고 shapes) ------------------------------
    ("가또땅고 152번째 수요 밀롱가 09.16 with DJ 롭", "이데알 탱고 까페 저녁 8시부터", PUBLISHED, EVENT_UPCOMING),
    ("[부산_탱고동호회]가또땅고 Special Event 9월24일(목)", "장소: 이데알 탱고 까페 저녁 7시 회비 10,000원", PUBLISHED, EVENT_UPCOMING),
    ("[부산_가또땅고]월간가또 Monthly Gato Milonga 시즌2", "매월 둘째 토요일 19:00-23:00 이데알 탱고 까페", PUBLISHED, EVENT_UPCOMING),
    ("OSIK 정모 안내 9/19(토)", "장소: 스튜디오 오초 오후 7시 30분 시작 회원 무료", PUBLISHED, EVENT_UPCOMING),
    ("OSIK 프락티카 9월 20일 일요일", "오후 3시부터 6시까지 @ 오초 스튜디오", PUBLISHED, EVENT_UPCOMING),
    ("이번주 토요일 밀롱가", "저녁 8시 장소: 라 벤따나 DJ 미정", PUBLISHED, EVENT_UPCOMING),
    ("다음주 수요일 정모 밀롱가", "다음주 수요일 저녁 8시부터 @ 오초 입장료 10,000원", PUBLISHED, EVENT_UPCOMING),
    ("매주 화요일 정모 안내", "매주 화요일 저녁 8시부터 밀롱가 @ 오초", PUBLISHED, EVENT_UPCOMING),
    ("9월 셋째주 토요일 밀롱가 델 마르", "9월 셋째주 토요일 19:00 - 23:00 장소: 엘 불리 입장 15,000원", PUBLISHED, EVENT_UPCOMING),
    ("2026.09.26 토요일 밀롱가 라 루나", "20:00~24:00 장소: 라 루나 DJ 초청", PUBLISHED, EVENT_UPCOMING),
    ("2026-10-03 (토) 가을 밀롱가", "시간: 오후 7시 30분 ~ 11시 30분 장소: 피스타", PUBLISHED, EVENT_UPCOMING),
    ("10/2(금) 밀롱가 노체", "저녁 8시 시작 @ 노체 탱고바 입장료 12,000원", PUBLISHED, EVENT_UPCOMING),
    ("09/19 토요일 밀롱가", "7:30pm 시작 Venue: Studio Ocho", PUBLISHED, EVENT_UPCOMING),
    ("9.27 일요일 오후 프락티카", "14시부터 17시까지 장소: 오초 참가비 5,000원", PUBLISHED, EVENT_UPCOMING),
    ("밀롱가 델 솔 9월 21일 월요일", "19시 30분 시작 장소: 솔 스튜디오", PUBLISHED, EVENT_UPCOMING),
    ("원데이 오픈클래스 & 밀롱가 9/25(금)", "오픈클래스 19:00 밀롱가 20:00-23:00 @ 이데알 탱고 까페", PUBLISHED, EVENT_UPCOMING),
    ("게스트 DJ 나이트 9월 26일 토", "장소: 피스타 밤 8시부터 입장료 15,000원", PUBLISHED, EVENT_UPCOMING),
    ("추석 특별 밀롱가 10/4(일)", "저녁 7시 ~ 11시 장소: 라 벤따나 DJ 두 명", PUBLISHED, EVENT_UPCOMING),
    ("매월 마지막 금요일 밀롱가 루나", "매월 마지막 금요일 20:00-24:00 @ 루나 탱고바", PUBLISHED, EVENT_UPCOMING),
    ("매월 15일 정기 밀롱가", "매월 15일 저녁 8시 장소: 오초 스튜디오", PUBLISHED, EVENT_UPCOMING),
    ("9월 15일(화) 화요 프락티카", "오후 8시 장소: 오초", PUBLISHED, EVENT_UPCOMING),
    ("9/14(일) 오늘 밀롱가", "오늘 저녁 7시 장소: 피스타", PUBLISHED, EVENT_UPCOMING),
    ("9월 30일 수요일 밀롱가 라 비다", "19:30 @ 라 비다 입장료 13,000원", PUBLISHED, EVENT_UPCOMING),
    ("10월 10일 토요일 밀롱가 페스타", "오후 8시부터 새벽 1시까지 장소: 그랜드홀", PUBLISHED, EVENT_UPCOMING),
    ("Milonga Nocturna 9/27 Sun", "8pm start at Studio Ocho fee 10,000원", PUBLISHED, EVENT_UPCOMING),
    ("9월 마지막 주 토요일 밀롱가", "9월 마지막주 토요일 저녁 8시 장소: 엘 불리", PUBLISHED, EVENT_UPCOMING),
    ("OSIK 열탱즐탱 밀롱가 9/20", "이번주 일요일 오후 6시 @ 오초", PUBLISHED, EVENT_UPCOMING),
    ("가또땅고 수요 밀롱가 9/23 with DJ 리오", "저녁 8시 이데알 탱고 까페 회비 10,000원", PUBLISHED, EVENT_UPCOMING),
    ("밀롱가 데 라 노체 2026년 9월 19일", "20:00-23:30 장소: 노체 DJ 게스트", PUBLISHED, EVENT_UPCOMING),
    ("9월 18일 금요일 밀롱가", "8시부터 @ 피스타", PUBLISHED, EVENT_UPCOMING),
    # --- swing community (비바스윙 / 올어바웃스윙 shapes) ------------------------
    ("이번주 토요일 소셜 파티", "오후 7시 30분 시작 장소: 바운스블루", PUBLISHED, EVENT_UPCOMING),
    ("9월 소셜 일정 안내", "9/5 토 소셜 20:00 / 9/19 토 소셜 20:00 / 9/26 토 파티 20:00 @스튜디오 오초", PUBLISHED, EVENT_UPCOMING),
    ("비바스윙 토요 소셜 9/19", "저녁 8시 @ 신천 비바스윙 회원 무료", PUBLISHED, EVENT_UPCOMING),
    ("올어바웃스윙 99학기 개강 파티 9월 20일(일)", "오후 6시부터 장소: 올어바웃스윙 홀", PUBLISHED, EVENT_UPCOMING),
    ("발보아 소셜 나이트 9/25(금)", "20:00~23:00 @ 스윙홀 입장 7,000원", PUBLISHED, EVENT_UPCOMING),
    ("린디합 소셜 10/3 토", "저녁 7시 시작 장소: 홍대 스윙바", PUBLISHED, EVENT_UPCOMING),
    ("매주 금요일 소셜 안내", "매주 금요일 밤 9시부터 소셜 @ 비바스윙", PUBLISHED, EVENT_UPCOMING),
    ("2026.09.20 일요일 오후 소셜", "15:00-18:00 장소: 바운스블루 참가비 5,000원", PUBLISHED, EVENT_UPCOMING),
    ("9월 넷째주 토요일 파티", "9월 넷째주 토요일 저녁 8시 @ 올어바웃스윙 홀", PUBLISHED, EVENT_UPCOMING),
    ("할로윈 파티 10/31(토)", "저녁 8시 장소: 스윙홀 입장료 10,000원", PUBLISHED, EVENT_UPCOMING),
    ("Swing Social 9/26 Sat", "7:30pm at Bounce Blue cover 8,000원", PUBLISHED, EVENT_UPCOMING),
    ("추석 연휴 소셜 10/5(월)", "오후 5시 ~ 9시 장소: 비바스윙", PUBLISHED, EVENT_UPCOMING),
    ("매월 첫째 토요일 정기 소셜", "매월 첫째 토요일 20:00-23:00 @ 스윙홀", PUBLISHED, EVENT_UPCOMING),
    ("다음주 토요일 소셜 안내", "다음 주 토요일 저녁 8시 장소: 바운스블루", PUBLISHED, EVENT_UPCOMING),
    ("9/21 월요일 소셜", "20시 @ 홍대 스윙바", PUBLISHED, EVENT_UPCOMING),
    ("특별 소셜 나이트 9월 27일 일요일", "장소: 스윙홀 저녁 7시 게스트 DJ", PUBLISHED, EVENT_UPCOMING),
    ("바차타 나이트 10/2(금)", "장소: 라틴바 살루드 밤 9시부터 입장 10,000원", PUBLISHED, EVENT_UPCOMING),
    ("살사 소셜 파티 9/19(토)", "21:00-01:00 @ 살루드 입장료 10,000원", PUBLISHED, EVENT_UPCOMING),
    ("키좀바 소셜 9월 22일 화요일", "저녁 8시 30분 장소: 라틴바 살루드", PUBLISHED, EVENT_UPCOMING),
    ("10월 소셜 일정", "10/3 토 소셜 20:00 @ 스윙홀 / 10/10 토 소셜 20:00 @ 스윙홀 / 10/17 토 파티 20:00 @ 스윙홀", PUBLISHED, EVENT_UPCOMING),
    ("이번 주 금요일 소셜", "이번 주 금요일 저녁 8시 장소: 비바스윙", PUBLISHED, EVENT_UPCOMING),
    ("9/28(월) 발보아 파티", "오후 8시 @ 바운스블루", PUBLISHED, EVENT_UPCOMING),
    ("9.19 토 소셜", "20:00 @ 신천 비바스윙", PUBLISHED, EVENT_UPCOMING),
    ("2026-09-25 금요일 소셜", "저녁 8시부터 장소: 스윙홀", PUBLISHED, EVENT_UPCOMING),
    ("9월 19일 토요일 정모 파티", "장소: 올어바웃스윙 홀 저녁 7시", PUBLISHED, EVENT_UPCOMING),
    # --- past announcements (real events, already over) -----------------------
    ("가또땅고 149번째 수요 밀롱가 08.19 with DJ 롭", "이데알 탱고 까페 저녁 8시", PUBLISHED, EVENT_PAST),
    ("8/29 토요일 밀롱가", "20:00-23:00 장소: 피스타", PUBLISHED, EVENT_PAST),
    ("비바스윙 토요 소셜 9/5", "저녁 8시 @ 신천 비바스윙", PUBLISHED, EVENT_PAST),
    ("9월 첫째주 토요일 파티", "9월 첫째주 토요일 저녁 8시 장소: 스윙홀", PUBLISHED, EVENT_PAST),
    ("2026.08.30 일요일 프락티카", "오후 3시부터 @ 오초", PUBLISHED, EVENT_PAST),
    ("9/12(토) 소셜 파티", "오후 8시 장소: 바운스블루", PUBLISHED, EVENT_PAST),
    ("9월 6일 일요일 밀롱가", "19:00-23:00 장소: 라 벤따나", PUBLISHED, EVENT_PAST),
    # --- non-events: recaps ----------------------------------------------------
    ("스윙댄스동호회 올어바웃스윙 98학기 2주차 토요일 축하소셜 생일빵 라인댄스 영상", "2026.6.27", PUBLISHED, NON_EVENT),
    ("9/5 소셜 파티 후기", "지난 토요일 소셜 정말 즐거웠어요 다음에 또 만나요", PUBLISHED, NON_EVENT),
    ("8/19 수요 밀롱가 사진 모음", "이데알 탱고 까페에서 찍은 사진입니다", PUBLISHED, NON_EVENT),
    ("월간가또 시즌1 마지막 밀롱가 스케치 영상", "8/8 토요일 밀롱가 영상 올립니다", PUBLISHED, NON_EVENT),
    ("[리뷰] 9/12 소셜 DJ 셋리스트", "지난 소셜 20:00-23:00 셋리스트 공유", PUBLISHED, NON_EVENT),
    ("밀롱가 다녀왔어요", "9/12 토요일 피스타 밀롱가 다녀온 이야기", PUBLISHED, NON_EVENT),
    ("Swing Social Recap 9/5", "photos from Saturday's social at Bounce Blue", PUBLISHED, NON_EVENT),
    ("발보아 파티 하이라이트 영상", "9/12 발보아 파티 하이라이트 20:00", PUBLISHED, NON_EVENT),
    ("소셜 사진 정리 (9월 첫째주)", "장소: 스윙홀 9/5 소셜 사진", PUBLISHED, NON_EVENT),
    ("밀롱가 vlog 8월", "8/29 밀롱가 브이로그 장소: 피스타", PUBLISHED, NON_EVENT),
    # --- non-events: membership / admin / venue / instructor notices ----------
    ("동호회 가입 안내", "정모는 매주 화요일 저녁 8시 오초에서 진행합니다 가입 문의는 쪽지로", PUBLISHED, NON_EVENT),
    ("회비 안내 (9월)", "9월 회비는 9/20까지 입금 부탁드립니다 정모 참가는 회비 납부 후 가능합니다", PUBLISHED, NON_EVENT),
    ("스튜디오 대관 공지", "9/26(토) 20:00-23:00 대관으로 소셜 없습니다 장소: 스윙홀", PUBLISHED, NON_EVENT),
    ("강사 소개 - 9월 정규반", "매주 목요일 20:00 강습 담당 강사를 소개합니다 장소: 비바스윙", PUBLISHED, NON_EVENT),
    ("신입 회원 인사드립니다", "9/19 토요일 소셜에 처음 나가요 잘 부탁드립니다", PUBLISHED, NON_EVENT),
    ("9/19 밀롱가 신청 마감 안내", "9/19 밀롱가 신청이 마감되었습니다 장소: 피스타 저녁 8시", PUBLISHED, NON_EVENT),
    ("9/26 소셜 취소 안내", "9/26 토요일 20:00 소셜은 취소되었습니다 @ 스윙홀", PUBLISHED, NON_EVENT),
    ("환불 안내", "9/12 파티 참가비 환불은 9/20까지 신청해 주세요", PUBLISHED, NON_EVENT),
    ("동호회 소개", "OSIK은 홍대에서 매주 화요일 정모를 하는 탱고 동호회입니다 장소: 오초", PUBLISHED, NON_EVENT),
    ("운영진 모집", "9월 정모와 소셜 진행을 도울 운영진을 모집합니다", PUBLISHED, NON_EVENT),
    ("9월 정규 강습 소개", "매주 화요일 20:00-21:30 초급 강습 장소: 비바스윙 수강료 80,000원", PUBLISHED, NON_EVENT),
    ("린디합 초급(Level 2.) 8월 강습] 8/6(화) 개강: 화목반 @ 신천 비바스윙", "수강료 100,000원 4주", PUBLISHED, NON_EVENT),
    ("10월 정규반 모집", "10/6(화) 개강 20:00 장소: 오초 강습 8회 120,000원", PUBLISHED, NON_EVENT),
    ("발보아 워크샵 안내 10/10", "10/10 토 14:00-17:00 워크샵 수강료 60,000원 장소: 스윙홀", PUBLISHED, NON_EVENT),
    ("소셜 후기 이벤트 당첨자 발표", "9/12 소셜 후기 이벤트 당첨자를 발표합니다", PUBLISHED, NON_EVENT),
    ("주차 안내", "오초 스튜디오 주차는 건물 뒤편 공영주차장을 이용해 주세요", PUBLISHED, NON_EVENT),
    ("탱고 슈즈 공동구매", "9/20까지 신청 밀롱가 슈즈 할인 판매", PUBLISHED, NON_EVENT),
    ("9월 마니또 결과", "9/5 소셜에서 진행한 마니또 결과입니다", PUBLISHED, NON_EVENT),
    ("[설문] 정모 요일 투표", "정모를 화요일 저녁 8시에서 목요일로 옮길지 투표합니다 장소: 오초", PUBLISHED, NON_EVENT),
    ("Instagram 소셜 계정 안내", "@allaboutswing 팔로우 부탁드립니다 소셜 사진은 인스타에", PUBLISHED, NON_EVENT),
    ("스튜디오 오초 이전 안내", "10/1부터 오초 스튜디오가 이전합니다 새 주소는 추후 공지", PUBLISHED, NON_EVENT),
    ("공연반 모집 (11월 공연)", "11/14 공연을 위한 공연반을 모집합니다 매주 일요일 15:00 연습", PUBLISHED, NON_EVENT),
    ("밀롱가 에티켓 안내", "밀롱가에서 지켜야 할 까베세오와 딴다 예절을 정리했습니다", PUBLISHED, NON_EVENT),
    ("지난 학기 소셜 정리", "98학기 동안 진행한 소셜 12회를 정리했습니다 사진 포함", PUBLISHED, NON_EVENT),
    ("자기소개", "안녕하세요 탱고 시작한 지 두 달 된 회원입니다 정모에서 뵐게요", PUBLISHED, NON_EVENT),
    ("9월 경품 추첨 안내", "9월 소셜 참가자 대상 경품 추첨을 진행합니다", PUBLISHED, NON_EVENT),
    ("밀롱가 음악 추천", "밀롱가에서 자주 나오는 딴다 추천 목록", PUBLISHED, NON_EVENT),
    ("소셜 드레스코드 안내", "10/31 할로윈 파티 드레스코드 관련 문의가 많아 안내드립니다", PUBLISHED, NON_EVENT),
]
