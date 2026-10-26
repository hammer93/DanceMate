"""v0.96.56 fixtures: the posts behind P1-1 of the public launch audit.

Each REAL_* text is a stored Production body (source_item_content.extracted_text,
read from the 2026-10-26 04:33 KST scheduled backup), cut to the passages the
extraction reads. Telephone numbers, messenger links and handles, e-mail
addresses, bank accounts and the band members' names are removed; nothing else
is reworded.

* REAL_DDP_SWING - item 6377, https://cafe.daum.net/sweetyswing/5LOM/34387,
  published 2026-10-15. Stored as 1620084 at 08:00-08:40 - one row of its
  timetable ("8:00 ~ 8:40 - Live set 1"); its own "일시" says 7:00-10:00PM.
* REAL_PHU_QUOC - item 6807, https://danceinfo.net/lessons/1211. Stored as
  1629705-1629709 (10/29-11/02), each starting at 05:00 - the hour its
  "Social Parties until 05:00 AM" end. The post states no start.
* REAL_BACHATA_CLASS - item 6971, https://danceinfo.net/lessons/5941. Stored
  as 1629819 at 07:00-08:00; the body writes no 오전/오후 (the evening is on
  the poster only, in OCR that cannot be placed row by row).
* REAL_LATIN_HALLOWEEN - item 6853, https://danceinfo.net/lessons/5627.
  Stored as 1629732 at 09:30; "소셜 9시 30분부터" writes no 오전/오후.
* REAL_DULCE_PRACTICA - item 6921, https://miltang.com/milongas/882, and
  REAL_SUNDAY_PRACTICA - item 6919, https://miltang.com/milongas/1772. Real
  Sunday-morning practicas (1629770, 1629772) at 11:00.
* REAL_MILONGA_TU - item 1264, https://miltang.com/milongas/896. States its
  20:00~00:00 twice, once as "저녁 8시부터 12시까지".
"""

DDP_PUBLISHED = "2026-10-15T03:28:22+00:00"

REAL_DDP_SWING = (
    '[11/4 수] 밖에서 춤추자~!! "스윙팍 동대문 DDP에서...',
    '[야외스윙] "DDPlay X 스윙팍 with 스윙제리 𝘿𝘿𝙋𝙡𝙖𝙮 𝙎𝙬𝙞𝙣𝙜 in the Park 𝙬𝙞𝙩𝙝 𝙎𝙬𝙞𝙣𝙜𝙚𝙧𝙞𝙚" \u200b "가을날 스윙팍 동대문 DDP에서 함께합니다." \u200b *비가 와도 진행합니다.(비를 피할 수 있는 공간입니다.)* \u200b *퇴근 후 참여 가능한 오후 7시부터 시작합니다.* \u200b *\'스윙제리\' 라이브 밴드와 스윙댄스 동호회 - \'스윙키즈\', \'스윙타운\', \'스윙팝\',\'박쥐스윙\' 의 댄서들이 함께 합니다. 물론 누구난 함께 할 수 있는 열린스윙입니다.* \u200b 라이브 음악과 함께 분위기 좋은 야외에서 스윙댄스를 즐겨봅시다. \u200b 빠가 아닌 오픈된 장소에서 스윙을 즐기는 또다른 기쁨을 함께 나눴으면 하고, \u200b 여기에 스윙의 즐거움을 좀더 많은 분들께 알릴 수 있는 기회가 되었으면 하고자 자리를 마련했습니다. \u200b A Free Outdoor Swing Party with Live Big Band Music Enjoy without worries, rain or shine. Open to Everyone! \u200b ■ 일시 : 2026.11.4.수.7:00-10:00PM ■ 장소 : DDP 어울림광장 (동대문역사문화공원역 1번 출구, DDP B2 지하2층) \u200b ■ 참여 : 누구나 무료!(스윙댄스 모르는 친구도 데려올 수 있음) \u200b ⏰ Time Table \u200b .7:00 ~ 7:40 - 스윙댄스 오픈 클래스 .7:40 ~ 8:00 - 스윙 댄스 공연 & DJ 소셜 .8:00 ~ 8:40 - Live set 1 "Swingerie" .8:40 ~ 9:00 - 스윙 댄스 공연 & DJ 소셜 .9:00 ~ 9:40 - Live set 2 "Swingerie" .9:40 ~ 10:00 - DJ 소셜 \u200b 📍 Location DDP Oullim Square (Exit 1, Dongdaemun History & Culture Park Station – B2 Basement Level 2, DDP) \u200b 🎶 Live Music by SWINGERIE 4-piece Swing Band – Vocals, Keyboard, Double Bass, Drums \u200b 💃 Swing Dance Social No experience needed! Bring your friends, join the fun, and dance the night away. \u200b 🎉 Free Entry – Everyone Welcome! (Donations appreciated – see link below) \u200b ',
)

REAL_PHU_QUOC = (
    'PHU QUOC SUMMER LATIN FESTIVAL 2026',
    '2026-10-29 전체일정 2026-10-29,2026-10-30,2026-10-31,2026-11-01,2026-11-02 일정정보 5일간 장소 PHU QUOC 강의 소개 👉 PROMO CODE : NINA 🌞 PHU QUOC SUMMER LATIN FESTIVAL 2026 📅 29 Oct – 02 Nov 2026 | 5th Edition 💥 WHAT TO EXPECT AT PSLF 2026 ⭐ World-Class Shows ⭐ Workshops with Top International Artists ⭐ Exclusive & Limited Master Classes ⭐ Professional Bootcamps 🎉 Social Parties until 05:00 AM 🌅 Sunset Beach Party 🎃 Halloween Party 🕺💃 Welcome Party Thursday ( Phu Quoc island ) 🎧 After Party Monday (in Ho Chi Minh City, Saigon Only) 📣 3 PARTY ROOMS – ONE INCREDIBLE VENUE 💜 Room 1 – 100% Bachata ❤️ Room 2 – 100% Salsa On 1 / On2 / Mambo ❤️ Room 3 - 100% Cuban Timba 📍 NEW VENUE: SEASHELLS HOTEL & SPA PHU QUOC PHU QUOC ISLAND, VIETNAM. Prime Location – Everything Around You --- PHU QUOC SUMMER LATIN FESTIVAL 2026 - 5th Edition - World-Class Shows - Workshops with Top International Artists - Exclusive & Limited Master Classes - Professional Bootcamps - Social Parties until 05:00 AM ',
)

REAL_BACHATA_CLASS = (
    '바차타 화요일 시즌5 이벤트 클래스',
    '2026-10-27 전체일정 2026-10-27 일정정보 10월 27일 화요일 3주차 1교시 7:00~8:00, 2교시 8:00~9:00, 3교시 9:00~10:00 장소 라틴 강의 소개 에버라틴 바차타 백화점 시즌5 이벤트 클래스. 4주 과정으로 1·2·3교시 모두 수강할 수 있으며, 수업별 신청도 가능합니다. 1교시: 몽구·라플, 류지의 최신 트렌디 패턴과 원리 및 팔로잉·스타일링 2교시: 그레이·로렌, 센바와 멜로디컬 인플루언스 스타일 기본 원리 3교시: 아만다·스카·와플 등 강사진의 퓨전 바차타, 베이직·무브·스타일링, 트렌디 패턴 및 바차주크 응용 ',
)

REAL_LATIN_HALLOWEEN = (
    '라틴 할로윈 코스튬 페스티벌',
    '2026-10-30 전체일정 2026-10-30,2026-10-31,2026-11-01 일정정보 소셜 9시 30분부터 장소 라틴 DJ 몽구 강의 소개 라틴 할로윈 코스튬 페스티벌! TOP 3 왕중왕전 상금이 걸린 이벤트로 누구나 참여 가능합니다. 10월 30일 할로윈 웰컴파티, 10월 31일 할로윈 메인파티 코스튬 1차 예선, 11월 1일 할로윈 피날레파티로 진행됩니다. 상금 및 출전 정보는 포스터를 참고하세요. ',
)

REAL_DULCE_PRACTICA = (
    '둘리 가이드 쁘락띠까',
    '2026년 11월 1일 시간: 11:00~14:00 장소: El Tango (엘땅고) (서울 서초구 주흥길 12 환희빌딩 2층) 주최: 둘쎄 y LEO 반복: 매주 일요일 PRACTICE MAKES PERFECT! 둘리 가이드 쁘락은 이런 분들께 추천드립니다. ✅ 도대체 뭘 연습해야되는지 모르겠는 분 ✅ 인텐시브하게 제대로 연습하고 싶으신 분 ✅ 연습하고 싶은데 연습 파트너가 없는 분 ✅ 내가 잘 하고 있는 지 체크 받고 싶은 분 ✅ 탱고에 대한 궁금증이 많은 분 ✅ 새로운 피구라를 배우고 싶으신 분 ✅ 일요일 오전을 보람차게 보내고 싶으신 분 📌 프로그램 👉 11:00 – 12:20 (80분) 가이드 쁘락 (자율연습 + Q&A) 👉 12:20 – 12:40 (20분) 미니 피구라 클래스 (LV.3-4) 👉 12:40 – 14:00 (80분) 가이드 쁘락 (자율연습 + Q&A) ※ 연습 중 피드백 가능 💰 참가비: 10만원(2달, 8회), 6만원(1달, 4회), 당일 현장 2만원(1회) 상시 등록 가능 ',
)

REAL_SUNDAY_PRACTICA = (
    'SUNDAY PRACTICA',
    '2026년 11월 1일 시간: 11:00~13:00 장소: Ocho (오초) (서울 마포구 월드컵북로2길 57 지하1층) 반복: 매주 일요일 [SUNDAY PRACTICA] 매주 일요일, 나를 더 알아가는 시간. “썬데이쁘락” 입니다.♥️ ⭐️올레벨 베이직 가이드 트레이닝+자율쁘락으로 당신의 탱고를 더 견고하고 안정되고 편안하게 ⭐️ 비기너분들부터, 밀롱가에 적응했지만 지속적으로 정비가 필요하다 느끼셨던 분들, 그리고 체계적이고 틀이 잘 잡힌 베이직을 원하는 다양한 분들의 니즈를 충족하는 가이드 트레이닝. 시간이 지날수록 빛을 낼거에요! 같이 한시간 달려봅시다. ••• ⏰ 11시부터 한시간 가량의 가이드 트레이닝. 걷기와 오초, 그 안에서 이루어지는 축이동의 메커니즘에 대해 생각해보기. 단순>복잡>단순 의 꼬리물기인 베이직, 정답은 연습뿐! ⏰ 자율 쁘락 시간. (60‘) 그동안 수업에서 다뤘던 동작과 그 원리를 몸에 체득하고 수정해요. 외부에서 오신 분들도 자유롭게 연습 가능하십니다😃 스튜디오 오초',
)

REAL_MILONGA_TU = (
    'milonga_tu',
    '2026년 9월 10일 시간: 20:00~00:00 장소: O Nada (오나다) (서울 마포구 동교동 200-29 B1) 주최: Mickey y Elfin 반복: 매주 목요일 7:30 오픈강습 --------------------------------------------- 좋은 음악, 좋은 사람들, 그리고 밤이 깊어질수록 더욱 즐거워지는 탱고의 시간 ✨ —————————————————————————— Milonga for you ❤️ 오직 당신만을 위한 밀롱가!! —————————————————————————— 매주 목요일 저녁 8시부터 12시까지! 오나다 밀롱가에서 만나요 💃🕺',
)

