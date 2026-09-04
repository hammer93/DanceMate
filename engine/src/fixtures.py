FIXTURES = {
    "PISTA": {
        "source_role": "SECONDARY",
        "known_event_type": "MILONGA",
        "title": "💜8/22(토) THE PISTA MILONGA - DJ Hernan",
        "published": "2026-08-18",
        "body": "2026-08-22 토요일 19:00-23:00 입장료 13,000원 홍대 PISTA DJ Hernan",
        "expected": {"classification":"MILONGA","status":"VERIFIED","count":1,
                     "date":"2026-08-22","start":"19:00","end":"23:00","fee":13000}
    },
    "ONADA": {
        "source_role": "PRIMARY",
        "known_event_type": "MILONGA",
        "title": "Tango O Nada (땅고 오나다) 2026.08.07 Friday",
        "published": "2026-08-01",
        "body": "09:00 pm to 02:00 am DJ 태양",
        "expected": {"classification":"MILONGA","status":"POSSIBLE","count":1,
                     "date":"2026-08-07","start":"21:00","end":"02:00","fee":None}
    },
    "OCHO": {
        "source_role": "PRIMARY_VENUE",
        "known_event_type": "MILONGA",
        "title": "OCHO weekly Schedule 8.24~8.30",
        "published": "2026-08-20",
        "body": "8/24 무초밀롱가 20:00-24:00; 8/25 까사밀롱가 20:00-24:00; 8/26 수달려용밀롱가 20:00-24:00; 8/27 서울밀롱가 20:00-24:30; 8/28 그리셀밀롱가 20:00-02:00; 8/29 토이프밀롱가 20:00-02:00; 8/30 일루미밀롱가 14:00-18:00; 8/30 허그밀롱가 19:00-23:00",
        "expected": {"classification":"MILONGA","status":"POSSIBLE","count":8}
    },
    "LESSON": {
        "source_role": "SECONDARY",
        "title": "Special Milonga Lesson개설 (9월17일 개강)",
        "published": "2026-09-01",
        "body": "8주 강습 모집",
        "expected": {"classification":"CLASS","status":"EXCLUDED","count":0}
    }
}
