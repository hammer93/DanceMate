"""v0.96.40: four Production posters whose OCR text was read into a wrong clock.

Each text is `source_item_image.ocr_text` exactly as stored (already
PII-redacted by the runtime), and each answer was read off the poster image
itself by eye, not off the OCR. The items, their posters and what each one
prints:

* 643  - K-TANGO CF 2025 timetable: 05.08 "PM 20:00 - PM 24:00", and three more
         days of programmes in the same table; the table's rows are lost.
* 3809 - 오아시스 한가위 소셜: 시간 "오후 9시~1시", 입장료 "10,000원" on the next row.
* 5601 - 오아시스 월요소셜: "오후 9시 – 12시"; a stray "9" two OCR lines below.
* 5859 - 진주 라틴 피루나 17주년: "저녁 9시~ 3시"; a "5" on the next OCR line.
"""

POSTERS = {
    643: {
        "title": '공지 2025 K-TANGO CF 일정표 NEW',
        "event_type": 'MILONGA',
        "image": 'http://www.k-tango.net/upload/editor/1743398786601_79.png',
        "ocr_text": 'i\n\n05.08         한강플로팅아일랜드\n목요일         라이브밀롱가: 무 무드        PM 20:00 -\n\nDAY1         (with Tango Bardo)\n\n반포 솔빛섬\nPM 24:00        무드서울\n\n:00 -       서울시니\n코리아유니크베뉴투         M2000 | UUs\n\nPM 20:00 -        서울 시내\n\n=        미로\nK-TANGO 밀롱가데이      PM 24:00 | 탱고스튜디오\n\nVIP 밀롱가1         PM 23:30 -\nwith Tango Bardo         AM 03:00\n\nK-TANGO              PM 19:00 -\n스페셜 퍼포먼스            PM 21:00\n\nVIP 밀롱가 2           PM 23:30 -\nwith Tango Bardo         AM 03:00\n\n강탱고축제             PM 14:00 -\n|계인의 축제           PM 21:00\n\nVIP 밀롱가 3           PM 23:30 -\nwith Tango Bardo         AM 03:00\n\n*밀롱가 참여는 티켓\n*행사 일정은 주최측의 사정으로 인해 변경,취',
    },
    3809: {
        "title": '오아시스 한가위 소셜',
        "event_type": 'SOCIAL',
        "image": 'https://danceinfo.net/_next/image?url=https%3A%2F%2Fimg.danceinfo.net%2Fposters%2F4654%2F1789663697891-a2fdb48f-08f4-4f43-a83f-bb7830f7bc37.png&w=3840&q=75',
        "ocr_text": '오아시스 한가위 소셜\n+ 9S 26일(토요일) +\n66\n\n대저 이시드 E\n\n대전에 aI] AJ =\n\n로   환영 팝니:\n\n=.\n고\n\nvt\nrz\n+\n\n99\n\n: 대전 서구 괴정동 426-3 3층\n\n: 오후 9시~1시\n 10,0002) (온통대전 캐쉬백 가맹점)\n\n  카카오톡 shoorran\n\n|  살사:바차타 3:4 (탄력조정)\n\n@821@|10@|1021@\n\n:  DJ MIN               ~\n\n^',
    },
    5601: {
        "title": '10월 5일 오아시스 월요소셜',
        "event_type": 'SOCIAL',
        "image": 'https://danceinfo.net/_next/image?url=https%3A%2F%2Fimg.danceinfo.net%2Fposters%2F5231%2F1790939534831-ea275ba2-d4e6-4005-af28-3354e0676b2b.png&w=3840&q=75',
        "ocr_text": '* SPECIAL GUEST\n\naz|\n\n———— with ——————\n\nOASIS LATIN ACADEMY\n\n102 52\n\n오후 9시 - 12시\n\n9\n\n오아시스 라틴학원\n대전 서구 괴정동 426-3, 3충\n\n입장료 10,000원\n온통대전 가맹점\n\n6,\n\nDJ MIN\nSalsa : Bachata 3 : 4\n음악 비율 탄력 조정\n\n문의\n7}7}2= shoorran',
    },
    5859: {
        "title": '진주 라틴피루나 17주년파티 Latin Night in Juya',
        "event_type": 'SOCIAL',
        "image": 'https://danceinfo.net/_next/image?url=https%3A%2F%2Fimg.danceinfo.net%2Fposters%2F4282%2F1788865959558-a923f04b-2379-4808-b76f-9dd7683dd7bf.png&w=3840&q=75',
        "ocr_text": '진주 라틴 피루나 1/주년 Oe\n\n2026년 10월 14일 토요일 저녁 9시~ 3시\n\n5                                                                  PHOTO 이작\n들        연 10시30분\n:   a      :   24       뉴~라이징스타 뚜부&제니        드레스코드 레드 ㅣ\n4200.09        윗샵:센슈얼바차타응용패턴 ㅣ... ,,     |\n\n:          아우 이 | aM ate | 음악비율살/바33\n\nMy td     > Jacky 9 Loci, 고      저녁 8시~9시       BEEBE\n\n8 10,000원 * 예매 15,000원 * 현매 20,000원\n22124 1[전화번호]26      문의 (졸리)            진주 라틴 피루나\n최*혁 (지역 Hd 입금)     [전화번호] ㅣ (진주시 상봉동1039-지하1증)',
    },
}
