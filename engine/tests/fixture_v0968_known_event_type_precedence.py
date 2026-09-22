"""v0.96.8 Production regression set: a club's archive on display as tonight.

``classify()`` returned the collector's ``known_event_type`` on its very
first line, before the recap/administrative guard on the line below it had
ever been asked. That prior says *which kind of night* a board announces - a
dedicated event board, a milonga listing page - and it is a good answer to
that question. It was being read as though it also answered *whether the
post announces a night at all*, which the evidence behind it (which board
the post sits on) cannot decide: the recap and the announcement are posted
to the same board by the same people.

Measured read-only on Production 42fd488 / 0.96.7 / engine 0.94, with the
0.94 re-extraction fully converged, over all 2,327 collected items, each
classified the way the runtime classifies it (its own ``known_event_type``,
its source's Settings event terms). 452 items carry the prior and 126 of the
events they produced are not announcements at all: a club's own video and
photo archive of a night already danced, and one notice that the night is
off. Every one of them was already recognised by ``is_non_event_notice()``;
the function simply returned before reaching it.

**Why the prior is not removed, weakened, or re-run through the classifier.**
324 of Production's 851 events exist only because of it and 56 of those are
still upcoming - the whole milonga listing directory (SRC-W-005, 195 events,
51 upcoming, 0 false positives) and every Naver community board's real
announcement among them. ``KEPT_BY_THE_PRIOR`` below is that set and every
member of it must still classify exactly as it did. The change is a
precedence change and nothing else: one existing guard moved above the
prior, and the prior otherwise untouched.

**The one word added.** 휴강 - a community saying its regular round is off
this week - joined the administrative half of the guard beside the 취소 안내
/ 취소 및 already there. Item 3635 is why: the Daum board collector's own
title test asks whether the heading names the club's own night on a specific
day, and "26년9월25일(금) 수라댄 금요정모 휴강" answers yes to both, with no
way to notice that the sentence goes on to cancel it. That word changes 3
posts in the whole corpus and exactly one of them carries an events row -
3635, the cancelled Friday round on public display as somewhere to dance.
No other cancellation vocabulary is admitted; see ``CANCELLED_BUT_NO_EVENT``
for the two that change classification and produce nothing either way.

Each entry is ``(ref, title, body, published, ket)`` where ``ref`` is the
Production item it was taken from and ``ket`` its real ``known_event_type``.
``KEPT_BY_THE_PRIOR`` carries one more field, ``without_prior`` - what the
classifier reads for that post when the prior is taken away, measured rather
than asserted. It needs no ``expected`` field: for a post the guard does not
recognise, the prior *is* the expected answer, which is the whole contract.

Bodies keep the real shape - the label order, the separators, the clock and
date forms, the hashtag tails that are all a Naver archive post has - and
are trimmed of the long prose around them. Personal names and contacts are
replaced; acquisition had already redacted the phone numbers. Titles are
kept as Production stores them, truncation and all, because a truncated
title is what the classifier actually reads.
"""

# --- A. The prior overruled: archives and a cancellation -------------------
#
# Every one of these is an ``events`` row on Production at engine 0.94 and
# must not be one. Each title is already matched by ``is_non_event_notice()``
# today; only the precedence kept them events.

CORRECTED_BY_PRECEDENCE = [
    # item 3635 - the release's reason. A Daum EVENT_PRIMARY board, a title
    # naming the club's own Friday round on a specific day, and the post
    # exists to say it is not happening. LISTED and upcoming when measured.
    (
        "3635",
        "26년9월25일(금) 수라댄 금요정모 휴강",
        "26년9월25일(금) 수라댄 금요정모 휴강 - ▒ 공지합니다 - [수라댄] 수원살사 "
        "바차타 동호회 수원라틴댄스사랑방 CAFE ▒ 공지합니다 앱으로보기 "
        "26년9월25일(금) 수라댄 금요정모 휴강 작성자 카이 | 작성시간 26.09.19 | "
        "조회수 14 목록 댓글 0",
        "2026-09-19T00:00:00+09:00",
        "SOCIAL",
    ),
    # item 2989 - SRC-N-016, the Naver board that produced 100 events from
    # 100 items. A video of a class taught at a gathering that happened.
    (
        "2989",
        "2026/08/14 대전라틴아카데미( DLC ) 정기모임 영상 #01 샤샤 바차타수업",
        "#대전라틴아카데미 (DLC) 키워드 #대전살사 #대전바차타 #대전라틴아카데미 "
        "#DLC #대전라틴댄스 #대전동호회 #대전파티 #대전살사클럽 #대전취미댄스",
        None,
        "SOCIAL",
    ),
    # item 3003 - the same board, the same night, the twenty-sixth clip of
    # it. Twenty-odd rows like this per gathering is how 100/100 happens.
    (
        "3003",
        "2025/03/21 대전라틴아카데미( DLC ) 정기모임 영상 #26 이글&윤슬 살사소셜",
        "#대전라틴아카데미 (DLC) 키워드 #대전살사 #대전바차타 #대전라틴아카데미 "
        "#DLC #대전라틴댄스 #대전동호회 #대전파티 #대전살사클럽 #대전취미댄스",
        None,
        "SOCIAL",
    ),
    # item 2716 - SRC-N-013. A blocked Naver fetch: the title is the whole
    # of what the engine has, which is exactly why the title guard is the
    # right place for this and a body rule would have been useless.
    (
        "2716",
        "전주라틴크루즈 생일자정모 (24/04/01) 영상 #14 라이더&너랑나랑 살사소셜",
        "",
        None,
        "SOCIAL",
    ),
    # item 2736 - the same board, a recap of an event inside the gathering.
    (
        "2736",
        "전주 라틴크루즈 살사정모 (23/07/31) 영상 #14 사생결단 이벤트 (풀버젼)",
        "",
        None,
        "SOCIAL",
    ),
    # A photo archive rather than a video one: the other half of
    # _RECAP_TITLE_RE, on the same kind of board. Shape taken from
    # SRC-N-012's 2022 albums, which post the same gathering four or five
    # times over.
    (
        "2645",
        "2022/11/9일 수요일 진주 라틴 피루나 정모 진주 졸리 작가님 사진 마지막 사....",
        "#진주취미 #진주동호회 #진주바차타 #진주라틴댄스 #진주살사 #진주댄스 "
        "#진주댄스동호회 #사천취미 #진주살사댄스 #라틴피루나",
        None,
        "SOCIAL",
    ),
]

# Two more posts the 휴강 word changes. Neither has an ``events`` row on
# Production, before or after, so neither is a loss - but 3564 is the shape
# to watch: it cancels the week's classes in the same heading that announces
# the round. It produces nothing today because the extractor never resolved
# a date for it, not because the classifier kept it.
CANCELLED_BUT_NO_EVENT = [
    (
        "3347",
        "설 연휴 휴강 안내] 왕초보반, 린디합 클래스",
        "스윙댄스, 린디합, 지터벅, 라인댄스, 발보아, 스윙댄스패턴, 린디합패턴, "
        "지터벅패턴, 스윙댄스강습을 체계적으로 알려드리는 동호회입니다 "
        "저희 동호회는...",
        None,
        None,
    ),
    (
        "3564",
        "★★추석주 수업휴강&제너럴정모 일정안내★★",
        "연휴기간 정모일정 안내드립니다^^ ▶ 9/10(화) 장소: 경성홀 오후 7:30~8:00 "
        "올어스 1주년기념라인강습 8:00부터 소셜 쭈욱~~ 입장료 7,000원 "
        "▶9/14 토요일 한가위포트럭파티 With 경품추첨 풍성한...",
        None,
        None,
    ),
]

# --- B. What the prior must still protect ----------------------------------
#
# Each must come out of ``classify()`` exactly as it does at engine 0.94.
#
# The last field is what the classifier reads *without* the prior, measured
# rather than assumed - eight of these ten lose their type entirely, which is
# the 324 Production events (56 upcoming) that would go if the feature were
# deleted instead of reordered. Two do not, and they are kept in the set on
# purpose: item 2779 spells 소셜 in its own body and item 2295's prior agrees
# with the keyword reading, so neither would notice the prior going away. A
# protection set that quietly contained only the easy cases would be worth
# nothing, so which is which is written down.

KEPT_BY_THE_PRIOR = [
    # --- the milonga listing directory: 195 events, 51 upcoming, 0 false
    # positives. Brand names with no scene word in them ("orange", "디디디",
    # "바모스") are precisely what the prior exists for.
    (
        "2070",
        "orange",
        "2026년 9월 22일 시간: 19:30~00:00 장소: Andante (안단테) "
        "(서울시 마포구 양화로 12길 24 선진빌딩 B1(합정역 3번 출구)) "
        "주최: Gaea 반복: 매주 화요일",
        None,
        "MILONGA",
        "OTHER",
    ),
    (
        "2103",
        "milonga_tu",
        "2026년 9월 24일 시간: 20:00~00:00 장소: O Nada (오나다) "
        "(서울 마포구 동교동 200-29 B1) 주최: Mickey y Elfin 반복: 매주 목요일 "
        "7:30 오픈강습",
        None,
        "MILONGA",
        "MILONGA_WITH_CLASS",
    ),
    # --- the Daum boards, whose own title test is the strong one. 3636 is
    # 3635's twin: same board, same week, same author, and it is on.
    (
        "3636",
        "26년9월23일(수) 수라댄 수요정모 공지",
        "26년9월23일(수) 수라댄 수요정모 공지 - ▒ 공지합니다 - [수라댄] 수원살사 "
        "바차타 동호회 수원라틴댄스사랑방 CAFE ▒ 공지합니다 앱으로보기 "
        "26년9월23일(수) 수라댄 수요정모 공지 작성자 카이 | 작성시간 26.09.19 | "
        "조회수 13 목록 댓글 0",
        "2026-09-19T00:00:00+09:00",
        "SOCIAL",
        "OTHER",
    ),
    (
        "2305",
        "살사아미고스 26.9.9.정모",
        "확연히 다가온 가을의 9월정모 두번째! 이번정모는 공식 출bar 정모입니다. "
        "더크루bar에서 우리회원들이 라인댄스 공연이 있습니다. "
        "7:00~7:20 라인댄스 7:20~8:00 살사 오픈강습 8:00~8:30 센슈얼 바차타 "
        "오픈강습 8:30~ 다함께 뒷정리후 출bar",
        "2026-09-06T00:00:00+09:00",
        "SOCIAL",
        "CLASS",
    ),
    (
        "2312",
        "2026-9-19(토) 살사왓 토요정모 ＞ 쿠바쿠바",
        "",
        "2026-09-15T00:00:00+09:00",
        "SOCIAL",
        "OTHER",
    ),
    # --- the Naver boards' real announcements. All five items that were
    # still in the future when they were collected were genuine; these are
    # three of them, and they are exactly as title-only as the archive rows
    # above, which is why only the recap words may separate them.
    (
        "2698",
        "2026년 9월 16일 수요일 라틴 피루나 정모 안내",
        "요즘 핫하기로 소문난 피루나 정모에 여러분 많이 놀러오세요~^^ 기다립니다~ "
        "#진주취미 #진주동호회 #진주바차타 #진주라틴댄스 #진주살사 #라틴피루나",
        None,
        "SOCIAL",
        "OTHER",
    ),
    (
        "2779",
        "20260917 전주라틴크루즈 바차타나이트 공지",
        "전주라틴크루즈 바차타 소셜 BACHATA NIGHT 좋은 음악과 좋은 사람들, "
        "그리고 특별한 바차타의 밤! 9월 17일 목요일 ⏰ PM 9:00 ~ 11:30 DJ 실버 "
        "음악비율｜바차타 4 : 살사 2 특별 이벤트｜바차타 한곡반 수료식",
        None,
        "SOCIAL",
        "SOCIAL",
    ),
    (
        "3674",
        "2026년9월23일 빅정모(추석전 고향에서~)",
        "9월23일 진주 라틴 피루나에서 빅정모를 진행합니다. 고향에 오시는분들 "
        "많은 참석바랍니다. #진주취미 #진주동호회 #진주바차타 #진주라틴댄스 "
        "#라틴피루나",
        None,
        "SOCIAL",
        "OTHER",
    ),
    (
        "2816",
        "BSBF 10주년 ✅️ 2026.10.9-11 부산 살사 바차타 페스티벌",
        "BSBF 주년 The New Wave ✨️ 패스신청 https://forms.gle/example "
        "바차타레이디 부트캠프 행사단톡방 https://open.kakao.com/o/example "
        "2026.10.9-11",
        None,
        "SOCIAL",
        "OTHER",
    ),
    # --- the dated class board (CLASS_PRIMARY, class_event_opt_in). Its
    # prior is CLASS, not an event class at all, and the four Events it
    # produces come from the opt-in path rather than from classify().
    (
        "2295",
        "[10월_강습 공지] ✨살사 기초완성반 (토요반) - 쿠식&천여지쌤✨",
        "동호회 “라틴속으로” 는 살사와 바차타를 함께 즐길 수 있는 분들을 만나기 "
        "위해 다양한 살사·바차타 강습을 합리적인 비용으로 개설하고 있습니다. "
        "이번에 안내드릴 수업은 살사 기초완성반 입니다. 개강 10월 3일(토) "
        "매주 토요일 오후 2시 수강료 12만원",
        "2026-09-09T00:00:00+09:00",
        "CLASS",
        "CLASS",
    ),
]

# --- C. Nothing changes for a post without the prior -----------------------
#
# The guard already ran first for every one of these, so v0.96.8 cannot
# touch them. They are the v0.96.5 and v0.96.7 release regressions, carried
# forward: the nights those releases rescued and the lesson adverts they
# stopped promoting.

NO_PRIOR_UNCHANGED = [
    # v0.96.5's rescues - a night announced in a title through a body that
    # also teaches. Still MILONGA_WITH_CLASS.
    (
        "2334",
        "2026년 9월 19일 토요일 밀롱가 La Vida No.802 DJ 조앤",
        "9월 19일 토요일 밀롱가 La Vida No.802 오후 7시 30분 오픈강습, "
        "8시 밀롱가 시작 장소: 부산 서면 라비다 입장료 15,000원 DJ 조앤",
        "2026-09-16T00:00:00+09:00",
        "MILONGA_WITH_CLASS",
    ),
    (
        "3643",
        "💢대전까미니또 초고급밀롱가",
        "💢밀롱가 8시~10시30 내일은 행복한 월요일 이번주부터 왕초급 강습이 "
        "시작됩니다",
        "2026-09-20T00:00:00+09:00",
        "MILONGA_WITH_CLASS",
    ),
    # v0.96.7's rescue - a real night the word-list simulation destroyed.
    (
        "3127",
        "[부산_탱고동호회]가또땅고 Special Event 9월24일(목...",
        "9월 24일 목요일, 가또땅고 \"한가위밀롱가\"가 열립니다. "
        "디제이는 부산 대표 스톤님!! * 일정 : 9월 24일 목요일 8시pm - 12시am "
        "* 장소 : 부산 * 참가비 12,000원",
        "2026-09-17T00:00:00+09:00",
        "MILONGA",
    ),
    # v0.96.7's corrections - lesson adverts that must stay CLASS and
    # produce nothing.
    (
        "977",
        "토욜 스페셜 원데이 클래스",
        "2026년 9월 5일 장소: 서울시 마포구 동교동 152-14 지하 1층 지역: 서울 "
        "9월 5일 – 다양한 바시코 9월 12일 – 아브라소의 비밀 : 팔과 어깨 "
        "10월 31일 – 밀롱가 & 발스",
        "2026-09-01",
        "CLASS",
    ),
    (
        "3202",
        "[부산_탱고수업]데이브y지브릴's 쁘롱가 적응 시퀀스...",
        "☆쁘롱가 적응을 위한 실전 시퀀스☆ 최대한 빠르게 소셜에 적응하기 위한 "
        "필수 시퀀스 위주의 수업을 진행합니다. 3/15, 3/22, 3/29, 4/5, 4/12, 4/19 "
        "4:20-5:30 (70분) 참가비용: 6주 10만원 커리큘럼 1주차",
        "2026-02-18",
        "CLASS",
    ),
    (
        "205",
        "[금요특강] 26년 9월 18일 시작!! 밀롱가/땅고 실전패턴!!",
        "매주 금요일 만나는 스페셜한 클라스!! 수업때만 잘 따라와도~ 밀롱가에서 "
        "잘 놀 수 있다. 수강료 6회 수업(2달 과정) 커리큐럼",
        "2026-09-01",
        "CLASS",
    ),
    (
        "256",
        "♥️9월 13일(SUN) 비비밀 AM 밀롱가 + 살바 무료강습🎁🥰",
        "🔥 9월에 두번째 일요일인 13일에 비비밀 합니다‼️ 🔹️ 6:30-10:30pm 피스타🔹️ "
        "와인 무료제공",
        "2026-09-04",
        "CLASS",
    ),
    # A night written beside its own clock, with no prior at all.
    (
        "2800",
        "■ 스윙타임빠 (9월 19,20일) 토,일 소셜 공지",
        "■ 스윙타임빠 (9월 19,20일) 토,일 소셜 공지 - 토요일 저녁 7시30분부터 "
        "소셜이 진행 됩니다. DJ '파인' PM 8:15~10:15",
        "2026-09-17",
        "SOCIAL",
    ),
]
