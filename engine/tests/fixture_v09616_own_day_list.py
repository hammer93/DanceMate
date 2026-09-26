"""v0.96.16 Production regression set: the post's own day-list field.

danceinfo.net publishes one row per (content, date) for every day a listing
runs. 부에나's 추석 party is five rows - ``idx`` 27718 through 27722, one per
day of 2026-09-23..27 - and the site's date page for each of those days
carries it, so somebody browsing on the 26th sees it. The field
``acquisition.danceinfo_payload_body()`` writes as ``전체일정`` is that day
set; ``일정정보`` is one schedule string belonging to the whole post. Verified
read-only against the live ``__NEXT_DATA__`` payload on 2026-09-26: there is
no per-date schedule in it at all.

``extract_schedule()`` reads a schedule post as a run of *date headings*, each
introducing its own program. Applied to this field that is the wrong shape,
and it fails the same way every time: every day but the last gets the segment
``"2026-09-25,"``, which names no event and is dropped, while the last day's
segment swallows the whole ``일정정보`` + description block. ``matching`` never
reaches two, the post falls through to the single-candidate path, and it is
filed on the **last** day of its own run. 부에나's five-night party was one
event, on 9/27.

**The shape alone proves nothing, and that is why this file is mostly
negatives.** Measured over the live corpus on 2026-09-26, the bare pattern -
two or more dates, no per-date prose, one shared schedule - is right **one
time in seven**. The other six are a Barcelona congress, a Geneva festival,
a 6주과정 집중반, a 월간 스케줄 roundup, a workshop weekend and a recurring
Tuesday class day. Group B is each of the families that must stay out, with
the reading that keeps it out.

Two more measured negatives, both about *not trading anything away*:

* 수원쿠바 (group C) lists four days and gives each its own line, and its own
  9/26 line carries no clock - the ``토요일 8:00 PM`` that times it sits in
  the shared block. Expanding it would swap one night somebody can turn up
  to for three they only know the date of, so the post is left alone. That is
  v0.96.15's guard 3, applied per day.
* LATIN EVERLATN (group B) lists four days and gives two of them nothing but
  ``Salsa 워크샵``. A day's own words beat the shared block, and a day whose
  own words name no night is not a night.

Each entry is ``(ref, title, body, expected_dates)`` where ``ref`` is the
danceinfo lesson id (the ``/lessons/<N>`` path, which is what the release
notes number these posts by) and ``expected_dates`` is the set of days the
post must produce, or ``None`` for "this route must refuse it". Bodies are
the real stored or live payload text, trimmed of surrounding prose; contact
numbers are replaced.
"""

SOCIAL = "SOCIAL_WITH_CLASS"

# --- A. The day-list field read as the days the post runs ------------------
#
# Each of these held exactly one Production event before this release, on one
# arbitrary day of its own run. Each writes its days in its own 전체일정
# field, and none of them singles out a day in prose in a way that contradicts
# the shared block.
OWN_DAY_LIST_RUNS = [
    (
        # Five nights, no per-day prose at all: the description talks about the
        # holiday, not about a day ("춤이 있는 특별한 연휴"). The site itself
        # publishes five dated rows (idx 27718..27722) and lists the post on
        # each of those five date pages. Stored as 2026-09-27 alone.
        4771,
        "추석연휴 CHUSEOK SPECIAL PARTY",
        "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
        "일정정보 PM 9:00 ~ 밤샘 장소 부에나 DJ 띰띰이, 띰띰이, 카르디 "
        "강의 소개 춤추는 즐거움이 추석연휴 CHUSEOK SPECIAL PARTY "
        "춤이 있는 특별한 연휴, 부에나에서 만나요 좋은 사람들과 가득한 더 특별한 시간 "
        "추석, 부에나에서! 부에나에서 추석 연휴를 맞아 파티가 열립니다. "
        "DJ 띰띰이가 시간을 맞춰 음악을 선보이며, 살사와 바차타 무료 오픈강습도 "
        "진행됩니다. 이벤트로 보틀 20% 할인도 진행됩니다. "
        "부에나가 100% 지원하는 강습비가 있으니 많은 참여 부탁드립니다.",
        {"2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"},
    ),
    (
        # Three nights running the same programme, which the post says twice -
        # once as its field and once as bare prose tokens, "9/23수 · 9/25금 ·
        # 9/26토 BABARU에서 살사 · 바차타와 함께". That second writing is the
        # list again, not three descriptions: the sentence after the last token
        # is about all three days. Its own poster states WORKSHOP PM 8:00~9:00
        # and SOCIAL PM 9:00 START under each of the three dates.
        #
        # This is the payload body. The stored body was the superseded
        # `danceinfo_region` one, whose 전체일정 is yearless and which carries a
        # `수강료` label the payload has no field for - and that label alone is
        # course evidence, so condition 3 refused the post until it was
        # re-acquired. The two halves of this release need each other.
        4063,
        "BABARU 소셜 OPEN!",
        "2026-09-23 전체일정 2026-09-23,2026-09-25,2026-09-26 "
        "일정정보 PM 8:00~9:00 (워크샵), PM 9:00 START (소셜) 장소 바바루 "
        "DJ 길거리, 실버, 로미 강의 소개 소중한 사람들과 함께하는 특별한 3일! "
        "바바루에서 즐거운 추억을 만드세요! 초보부터 고수까지 모두 환영합니다. "
        "3일간 특별한 추억을! 황금연휴, 바바루에서 최고의 시간을 보내세요! "
        "🌕 이번 추석연휴, 대구에서 제대로 놀아봐요! "
        "9/23수 · 9/25금 · 9/26토 BABARU에서 살사 · 바차타와 함께 알차게 준비했습니다 "
        "🎟 FULL PACKAGE 얼리버드 40,000원 정상 패키지 50,000원 "
        "개별 이용 시 총 60,000원",
        {"2026-09-23", "2026-09-25", "2026-09-26"},
    ),
    (
        # Two Tuesdays of the same recurring 소셜데이, both matching the
        # schedule's own "화요일 PM 7:00~9:10". Filed 출빠정보/정모 - a night
        # the venue repeats, not a course: no 주 과정, no 회차, no 개강.
        4286,
        "수원 쿠바라틴 살사 바차타 소셜데이",
        "2026-09-22 전체일정 2026-09-22,2026-10-06 일정정보 화요일 PM 7:00~9:10 "
        "장소 쿠바빠 강의 소개 살사 바차타 초중급 강사: 아이로스 & 유정 "
        "살사 초중급 PM 7:00~8:00 바차타 초중급 PM 8:00~9:00 "
        "원데이클래스·소셜·대관 문의 초보자부터 경험자까지 누구나 환영!",
        {"2026-09-22", "2026-10-06"},
    ),
]


# --- B. Same shape, not a run of nights ------------------------------------
#
# Every one of these carries a 전체일정 field with two or more days and is
# filed by the source as an EVENT. Each is asserted against the route
# *directly*, with a night classification forced, so the refusal is the
# route's own and not a side effect of how `classify()` happens to read the
# post today.
NOT_A_RUN_OF_NIGHTS = [
    (
        # One continuous congress in Barcelona, four days. No 일정정보 at all,
        # so nothing establishes an hour on any of those days - and four
        # nightly parties is not what "2 TO 5 OCT" means.
        3132,
        "DANCE BACHATA CONGRESS",
        "2026-10-02 전체일정 2026-10-02,2026-10-03,2026-10-04,2026-10-05 "
        "장소 BARCELONA 강의 소개 DANCE BACHATA CONGRESS Life 2 TO 5 OCT. 2026 "
        "BUY YOUR FULL PASS WORLDTICKETS.ES go&dance "
        "HOTEL DON ANGEL CARRER DEL PLA DE LA TORRE 14 - SANTA SUSANNA BARCELONA",
        None,
    ),
    (
        # One continuous festival in Geneva, five days. "SOCIAL WORLD CUP"
        # does contain the word this event type is named by, which is exactly
        # why the shared block also has to carry hours before a day may lean
        # on it. It carries none.
        4057,
        "BACHATAGENEVA FESTIVAL",
        "2026-10-08 전체일정 2026-10-08,2026-10-09,2026-10-10,2026-10-11,2026-10-12 "
        "장소 제네바 DJ DJ Pablo g, DJ Love me 강의 소개 "
        "두명의 제네바 소셜월드컵 오거나이저 Dj Pablo g , dj love me가 직접 진행합니다. "
        "THE FESTIVAL OF NATIONS BACHATAGENEVA FESTIVAL.COM SOCIAL WORLD CUP "
        "THE BEST BACHATA SOCIAL COMPETITION IN THE WORLD",
        None,
    ),
    (
        # A course, and the only thing saying so is "6주과정" in the schedule
        # field. Six Tuesdays, filed 출빠정보/정모/강습, and it classifies as a
        # night on text alone. Condition 3 is what stops six nights.
        3622,
        "바차타 기본다지기소셜집중반",
        "2026-08-25 전체일정 2026-08-25,2026-09-01,2026-09-08,2026-09-15,"
        "2026-09-22,2026-09-29 일정정보 6주과정 매주화요일20시~21시 30분연습추가 "
        "장소 탑 강의 소개 바차타 기본기와 몸만들기와 베이직30분 "
        "유행트렌드를 반곡으로 무한반복!! 수업후 강사님과 30분연습 "
        "화요반도 성황리에 개강!! 이번주 토요일개강합니다 .",
        None,
    ),
    (
        # A month's worth of Thursdays at one venue, each a different theme
        # (드레스코드 블랙, 한글날 파티, 할로윈 워크 DAY 1). A roundup of a
        # venue's own nights is not one night repeated, and "매주 목요일" is
        # what says so.
        4850,
        "10월 스케줄♥️",
        "2026-10-01 전체일정 2026-10-01,2026-10-08,2026-10-15,2026-10-22,2026-10-29 "
        "일정정보 매주 목요일 장소 바야 강의 소개 춤으로 만나는 10월의 특별한 밤 "
        "특별한 워크샵과 함께하는 10월의 시작! 드레스코드 블랙, 더 특별한 밤 "
        "한글날 파티, 섹시 ♡ 생일빵 공식 뒷폴이까지! "
        "할로윈 워크 DAY 1. 가장 특별하고 짜릿한 밤! 오늘도, 바야에서 춤추자",
        None,
    ),
    (
        # Somebody else's nights: a four-day listing of other cities' regular
        # 정모, with no schedule of its own. Nothing here is an event at 강쏠
        # or anywhere the post itself runs.
        1576,
        "비 수도권 주요 일정",
        "2026-09-24 전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
        "강의 소개 -출처 전국방 주소 https://invite.kakao.com/tc/K07BipdWQF "
        "*보다 빠른 실시간 소통 밎 다양한 정보를 원하는 분들은 오픈채팅에 입장해보세요. "
        "20260902 부산 지역 정모 현황 수정되었습니다. "
        "20260916 대전 오아시스 9월14일(월) 정모 추가 (월/토, 주 2회) #파티일정 #심슨",
        None,
    ),
    (
        # A bar saying it is open. Four days, an hour ("아침 6시까지"), and the
        # word 파티 in passing - and still not four parties. Every one of those
        # four days is a day the post writes on its own, and none of those
        # lines names a night; what they name is 정상영업.
        4824,
        "NEW.SOL BAR 추석 영업안내",
        "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25,2026-09-26 "
        "일정정보 아침 6시까지 장소 강쏠 강의 소개 NEW.SOL BAR 추석 영업안내 "
        "9월 23일 (수요일) 9월 24일 (목요일) 9월 25일 (금요일) 9월 26일 (토요일) "
        "아침 6시까지 정상영업합니다! 새롬이 핫한 솔바 매니저 "
        "먹고 마시고 춤추고 썬업할때까지!! 연휴 크레이지 파티 즐기고 "
        "청결. 친절. 최고의 음향으로 여러분의 귀한 연휴를 책임지겠습니다!!",
        None,
    ),
]


# --- C2. A post whose only night is one of its listed days -----------------

# LATIN EVERLATN lists four days. Two of them are a workshop and nothing else
# ("09/25(금) 7:00-8:00 p.m.: Salsa 워크샵"), so a day's own words keep them
# out. The 24th it says nothing about, and the 27th - the day that really does
# hold a party, "9:00-10:00 p.m.: Kizomba 파티" - is a line narrow enough that
# the clock beside the event's word carries no meridiem, so its hours are not
# published. That leaves an expansion whose 27th has no start time while the
# post already reads as a timed 9/27, and condition 5 declines it: the post
# keeps the single night it has.
LATIN_EVERLATN = (
    2942,
    "추석 연휴 워크샵 - LATIN EVERLATN",
    "2026-09-24 전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
    "일정정보 7:00-10:00 p.m. 장소 라틴 강의 소개 안녕하세요. 강남 라틴클럽입니다 "
    "추석연휴 \"특별 워크샵\" 선물셋트를 준비했습니다 "
    "추석 연휴를 맞아 다양한 춤 종류의 워크샵과 파티가 열립니다. "
    "- 09/25(금) 7:00-8:00 p.m.: Salsa 워크샵 "
    "- 09/26(토) 7:00-9:00 p.m.: Salsa 워크샵 "
    "- 09/27(일) 7:00-8:00 p.m.: Bachata 워크샵, 8:00-9:00 p.m.: Bachata 워크샵, "
    "9:00-10:00 p.m.: Kizomba 파티",
)
LATIN_EVERLATN_WORKSHOP_ONLY_DAYS = {"2026-09-25", "2026-09-26"}


# --- C. A day the post closes, and a night whose hours it would cost -------

# 하바나 lists five days in its field and writes "9월 24일(목) 하루
# 쉬어갑니다" about one of them, then "9월 25일(금) ~ 27일(일) 정상 영업" about
# three more. It already expands through `extract_schedule()`, so this route
# never sees it - but the parser has to be right about it regardless, because
# nothing guarantees the other route keeps winning. No new vocabulary is
# involved: a closed day simply fails the test that its own line must name the
# night, and so does a span that only says the doors are open.
HAVANA = (
    4755,
    "클럽 하바나 추석 연휴 공지",
    "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25,2026-09-26,2026-09-27 "
    "일정정보 20:30 - 21:30 장소 하바나 강의 소개 춤추는 놀이터 하바나에서 "
    "추석 연휴를 맞아 소셜파티를 개최합니다. 연휴 시작은 하바나에서! "
    "9월 23일(수) 미니 소셜 파티 20:30 ~ 21:30 바차타 무료 오픈강습 "
    "21:30 ~ 미니 소셜 파티 → 연휴 전날 밤, 가볍게 와서 춤추고 놀아요! "
    "9월 24일(목) 하루 쉬어갑니다. "
    "9월 25일(금) ~ 27일(일) 정상 영업! 추석 연휴에도 하바나는 문 열어놓을게요. "
    "이번 추석도 좋은 음악 + 좋은 사람 + 좋은 시간 하바나에서 함께해요.",
)
HAVANA_CLOSED_DAY = "2026-09-24"
HAVANA_OPEN_ONLY_DAYS = {"2026-09-25", "2026-09-26", "2026-09-27"}

# 수원쿠바 lists four days and gives each one its own line. Its 9/26 line is
# "9월 26일 추석 소셜" - a night, with no clock - while the 8:00 PM that dates
# it is in the shared block. Expanding it keeps the day and loses the hour, so
# condition 5 declines the whole expansion and the post stays exactly as it
# is. Its 9/19 line is 오픈강습 and would be dropped either way.
SUWON_CUBA = (
    4581,
    "수원쿠바 라틴댄스 소셜",
    "2026-09-12 전체일정 2026-09-12,2026-09-19,2026-09-22,2026-09-26 "
    "일정정보 토요일 8:00 PM - 11:00 PM 장소 쿠바빠 강의 소개 "
    "이번 주 토요일 수원쿠바에서 원더 줄리아쌤 키좀바 따라쇼 & 오픈강습 있습니다 "
    "함께라서 더 즐거운 시간! 9월 12일 토요 소셜 Salsa, Bachata, 키좀바 따라쇼 "
    "9월 19일 토요 오픈강습 원더 & 줄리아 Kizomba "
    "9월 22일 화요 바차타 한곡반 Bachatav 수료식 시즌 12 소셜 "
    "9월 26일 추석 소셜 9월도 수원쿠바에서 신나게!",
)
SUWON_CUBA_CURRENT = ("2026-09-26", "20:00")

# Its poster is titled 9월 19일 and reads "소셜 PM 8:00 ~ 11:00" - one day's
# hours. Real stored OCR text from Production's own source_item_image row for
# this item, trimmed; it is here to prove one day's poster never times
# another day.
SUWON_CUBA_POSTER = [(
    "https://img.danceinfo.net/posters/4581/poster.png",
    "가 ㅅ위쿠바에서 만나 이종바 따라쇼 9월 19일 원더 & 줄리아 PM 9:00 ~ 소셜 "
    "PM 8:00 ~ 11:00 바차타",
)]


# --- D. What the field itself parses to ------------------------------------
#
# (label, text, expected_days). The rendered-page form is yearless, which is
# why the 19 posts still holding a `danceinfo_region` body could not use this
# route at all until they were re-acquired.
DAY_LIST_FIELD_FORMS = [
    (
        "the payload form: full ISO days, comma packed",
        "2026-09-23 전체일정 2026-09-23,2026-09-24,2026-09-25 일정정보 PM 9:00",
        {"2026-09-23", "2026-09-24", "2026-09-25"},
    ),
    (
        "the rendered form: yearless, against the one year the post states",
        "2026년 9월 23일 (수) 전체일정 09/23 (수) , 09/25 (금) , 09/26 (토) "
        "일정정보 PM 8:00",
        {"2026-09-23", "2026-09-25", "2026-09-26"},
    ),
    (
        "yearless with no year anywhere in the post: no day list at all",
        "전체일정 09/23 (수) , 09/25 (금) 일정정보 PM 8:00",
        set(),
    ),
    (
        "yearless with two different years stated: refused rather than guessed",
        "2026-01-04 그리고 2027-02-05 전체일정 09/23 (수) , 09/25 (금)",
        set(),
    ),
    (
        "no field: the post never wrote a day list",
        "9월 23일 소셜 파티 PM 9:00 장소 부에나",
        set(),
    ),
]

# The label is written by the acquisition layer, never by a person, so a post
# that merely lists dates in prose has no day-list field and cannot reach this
# route however many dates it names.
NO_FIELD_JUST_PROSE = (
    "9월 소셜 안내",
    "9월 23일, 9월 25일, 9월 26일에 소셜 파티가 있습니다. PM 9:00 장소 바바루",
)

# BABARU's own poster, verbatim from Production's `source_item_image` row
# (image_index 1, OCR_SUCCESS, media_class EVENT_POSTER, already marked as
# this item's fallback). It states the same WORKSHOP PM 8:00 ~ 9:00 and
# SOCIAL PM 9:00 START under each of the three dates, which is what makes
# the 20:00 Production already shows belong to every day of the run rather
# than to one of them.
#
# Not paraphrased, and not trimmed. A body-only harness got BABARU wrong
# precisely because it modelled this poster as a single start time instead
# of reading it, and a hand-written stand-in parses differently from a real
# OCR - the smudges (`PM 9:00. START`, the column whitespace) are the part
# that matters.
BABARU_POSTER = [(
    'https://danceinfo.net/_next/image?url=https%3A%2F%2Fimg.danceinfo.net%2Fposters%2F4063%2F1788346413515-c7b44ced-90cd-4edb-ad53-e01e623b28fe.png&w=3840&q=75',
    '소중한 사람들과 함께하\n바바루에서 즐거운 추억을 만드세요!\n\nS&S 9월 23일(수) SPS 9월 25일(금) SIPS 9월 26일(토) &\n\nWORKSHOP              WORKSHOP              WORKSHOP\nPM 8:00 ~ 9:00                         PM 8:00 ~ 9:00                         PM 8:00 ~ 9:00\n파스 & 루키        라르고 & 임생로랑      뽀대용수 & 엘라\n살사                  바차타                 바차타\n\n 길거리 실 로미\n\nSOCIAL                   SOCIAL                   SOCIAL\nPM 9:00. START                          PM 9:00 START                          PM 9:00 START\n\n서스\n\n4\n입장료 10,000원\n\n입장료 10,000원\n\n12 패키지\n\n(워크샵 1회 + 소셜)\n\n20,0002\n소셜 입장권\n\n(소셜만 참여)\n\nxz =)\n3일 풀패스\n(워크샵 3회 + 소셜 3일)\n\n우\n(    ]            10,0002\n워크샵은 누구나 참여 가능!                 Age 모든 레벨 환영!                   3일간 특별한 추억을!\n초보부터 고수까지                              좋은 음악과 분위기,    황금연휴, 바바루에서\n모두 환영합니다.                                  그리고 멋진 사람들과 함께!                      최고의 시간을 보내세요!\n\n95-6464(오투 | [이 @babaru_latinclub',
)]
