import re
import unicodedata
# Tango names its social event; the other scenes call theirs a 소셜 or a 파티.
# Only these four words, because these are the ones the collected posts use.
SOCIAL_WORDS = ["소셜", "social", "파티", "party"]

# A clock, not a duration: "8:15" and "7시30분" are times, "10시간" is a length.
_CLOCK = r"(?:\d{1,2}\s*:\s*\d{2}|\d{1,2}\s*시(?!간))"
_SOCIAL = "|".join(SOCIAL_WORDS)
# What may sit between a social and its clock: spacing, list marks, and the
# particles Korean puts there. Anything else -- a word, a label -- means the
# clock belongs to something else.
_JOIN = r"[\s\-–—~:·,.()\[\]]|부터|까지|에|은|는|이|가"

# A social written next to its own time, in either order:
#   "20:00-22:30 소셜"      the clock, then the name
#   "7시30분부터 소셜이"      the clock, a particle, then the name
_SOCIAL_BY_CLOCK = re.compile(
    rf"(?:{_CLOCK})(?:{_JOIN}){{0,6}}(?:{_SOCIAL})"
    rf"|(?:{_SOCIAL})(?:{_JOIN}){{0,6}}(?:{_CLOCK})",
    re.I,
)

# 파티팩 is a ticket bundle and 정기권 is a season ticket. Neither is a party,
# and both appear in the collected posts.
_PRODUCT_SUFFIX = re.compile(rf"(?:{_SOCIAL})\s*(?:팩|권)", re.I)

# v0.91.0 PHASE 4: a real production post (SRC-D-011 item 2079) is a workshop
# night that also sells a separate, cheaper social-only ticket -- "워크샵+
# 소셜 20,000원 / 소셜 12,000원" -- and names when its own door opens --
# "클럽 오픈 오후 8시". social_evidence()'s clock-adjacency rule (above) is
# deliberately strict and stays exactly as it is; this is a second, narrower
# kind of evidence entirely: nobody prices admission to a thing they are only
# mentioning in passing. It is checked only for a post that already has a
# class word (see classify()) and only tips a CLASS into SOCIAL_WITH_CLASS
# when all three of the following hold together, so a lesson notice that
# happens to use one of these words alone never qualifies:
#
#   1. the post names a specific day (not just a month, never a bare weekday
#      or "매주 토요일" -- open-ended recurrence stays unmaterialized, same
#      rule extractor.py's own date gate already enforces downstream);
#   2. its own door/event opens -- "클럽 오픈", "도어 오픈", "파티 오픈" --
#      never a bare "오픈" alone, which is also how a lesson round opens
#      ("시즌 오픈", "강습 오픈", item 2225's own shape: "일요일 강습 오픈"
#      / "새 시즌 오픈합니다" -- neither names a club, a door or a party, so
#      neither matches);
#   3. a social/party word sits directly in front of its own price -- an
#      admission fee for the social itself, not a season ticket six words
#      later ("소셜의 입장을 할 수 있는 정기권입니다 ... 6만원" fails this
#      the same way it fails social_evidence(), by the same tight distance).
#
# A generic lesson advert that merely mentions a social afterwards (item
# 2225: "수업 후 쌤들과 소셜 및 정모 있어요", no price, no door, no "오픈"
# naming a club or a party) matches none of the three and stays CLASS.

# Restated from extractor.DATE_PATTERNS (Section: date extraction) rather
# than imported -- this package is stdlib-only and does not import
# extractor.py at module scope (see classify_with_image_evidence()'s own
# comment on the one lazy import it does need). Only used as a gate for "does
# this post name a specific day", never to resolve or anchor one -- that
# stays extractor.py's job, and it can still refuse the candidate afterwards
# if the date turns out unresolvable.
_EXPLICIT_DAY_DATE_RE = re.compile(
    r"20\d{2}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*일?"
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|(?<!\d)\d{1,2}[./]\d{1,2}(?!\d)"
)

# "클럽 오픈", "도어 오픈", "파티 오픈" -- an event's own door, never a bare
# "오픈" on its own, which is exactly how a lesson round or a new season
# opens too ("시즌 오픈", "강습 오픈", "모집 오픈").
_DOOR_OPEN_RE = re.compile(r"(?:클럽|도어|door|파티)\s*(?:가\s*)?오픈|open\s*door", re.I)

# A social/party word immediately pricing itself -- "소셜 20,000원", "파티
# 12,000원" -- not a season ticket or a bundle mentioned sentences later
# (_PRODUCT_SUFFIX already strips the bundle/season-ticket suffix forms
# before this ever runs, same as social_evidence()).
_SOCIAL_PRICED_RE = re.compile(
    rf"(?:{_SOCIAL})(?:{_JOIN}){{0,3}}[0-9][0-9,]*\s*(?:원|만\s*원)", re.I
)


def party_evidence_bundle(title: str, body: str) -> bool:
    """A stronger, narrower kind of social evidence than social_evidence().

    True only when a specific day, a named door/event opening, and a price
    tied directly to the social/party word all appear together -- see the
    comment above for why each piece is required and what it excludes.
    """
    heading = _PRODUCT_SUFFIX.sub(" ", (title or "").lower())
    text = _PRODUCT_SUFFIX.sub(" ", (body or "").lower())
    whole = f"{heading} {text}"
    return bool(
        _EXPLICIT_DAY_DATE_RE.search(whole)
        and _DOOR_OPEN_RE.search(whole)
        and _SOCIAL_PRICED_RE.search(whole)
    )


def social_evidence(title: str, body: str) -> bool:
    """Does this post *announce* a social, or merely mention one?

    The difference decides whether a lesson advert becomes a night out, and the
    collected posts make it plain. A social is announced in the title --
    ``스윙타임빠 (9월 2일) 수 소셜 공지`` -- or written next to its own clock --
    ``20:00-22:30 소셜``, ``7시30분부터 소셜이 진행 됩니다``.

    It is merely mentioned in ``소셜에서 쓰는 동작들`` inside a lesson blurb, in
    ``소셜의 입장을 할 수 있는 정기권`` on a season ticket, in ``파티팩`` on a
    ticket bundle, and in ``졸업파티 강습 일정: 매주 오후 4시`` where the clock
    on the page belongs to the lessons.

    Six of the twenty-three swing posts we hold say 소셜 or 파티 without
    announcing one. A bare keyword match would turn every one of them into an
    event, which is worse than the zero events we had.
    """
    heading = _PRODUCT_SUFFIX.sub(" ", (title or "").lower())
    if any(word in heading for word in SOCIAL_WORDS):
        return True
    text = _PRODUCT_SUFFIX.sub(" ", (body or "").lower())
    return bool(_SOCIAL_BY_CLOCK.search(text))


# v0.86.9: the words an operator adds in Settings (runtime.event_terms)
# reach this detection as ``event_terms`` - already normalized, already
# restricted to terms that stand for a milonga or a practica. They ADD to the
# built-in words in classify(); they never remove one, so switching a Settings
# term off can never make a post recognised yesterday stop being an event.
# The normalization and the matching rule are restated from
# runtime/event_terms.py (this package is stdlib-only and never imports
# runtime - the same arrangement as MIN_TEXT_FOR_IMAGE_TRUST below);
# tests/test_v0869_event_terminology.py holds the two to the same answers.
_TERM_SPACE = re.compile(r"\s+")


def normalize_term_text(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    return _TERM_SPACE.sub(" ", folded).strip().lower()


def term_occurs(normalized_term: str, normalized_text: str) -> bool:
    """A Latin-script term must stand alone as a word ("practica" is not in
    "practical"); a Korean one may sit inside a run, as its particles do."""
    if not normalized_term or not normalized_text:
        return False
    escaped = re.escape(normalized_term)
    if normalized_term.isascii():
        return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", normalized_text) is not None
    return normalized_term in normalized_text


# v0.96.0: a community board is mostly not announcements. A recap of last
# week's social ("축하소셜 스케치 영상", "정모 사진 후기"), a membership or
# fee notice, a venue-booking note, an instructor introduction, a
# registration-closed notice - these carry the very words that announce a
# night (소셜, 정모, 밀롱가) and used to become events dated in the past, or
# not at all. Judged on the title only: a real announcement's title does not
# call itself a recap, and a body may legitimately say "지난 파티 영상 참고".
# v0.96.11 added 귀국했 beside 다녀왔, and the conjugation is the whole point:
# "초급발표회 준비로 베트남에서 귀국했습니다" is somebody telling you where
# they have been, while "귀국 환영 밀롱가" is a night for the same person.
# The bare noun would take both; the past tense can only be the first.
_RECAP_TITLE_RE = re.compile(
    r"영상|동영상|후기|사진|스케치|리뷰|다녀왔|귀국했|되돌아|지난|recap|vlog|photo|video|"
    r"하이라이트|highlight",
    re.I,
)
_ADMIN_NOTICE_TITLE_RE = re.compile(
    r"가입\s*안내|가입\s*문의|가입방법|회비|회원비|대관|강사\s*소개|자기\s*소개|인사드립니다|"
    r"조직도|환불|신청\s*마감|마감\s*안내|마감되었|취소\s*안내|취소\s*및|휴강|마니또|운영진\s*모집|"
    r"설문|투표|경품|추첨|판매|할인|공동구매|공구|계정|에티켓|예절|매너|추천|드레스코드|"
    r"이전\s*안내|주차\s*안내|협찬\s*(?:공지|안내|모집|신청)",
    re.I,
)
# A community's own night announced with a word that is not a scene word -
# "Special Event 9월24일", "이번 달 정모", "게스트 DJ 나이트" - counts only
# when the post also names a specific day and either a clock or a place:
# an announcement carries logistics, a mention does not.
_NOTICE_WORDS_RE = re.compile(r"정모|행사|event|특별|스페셜|special|게스트|guest|나이트|night", re.I)
_NOTICE_CLOCK_RE = re.compile(_CLOCK, re.I)
_NOTICE_PLACE_RE = re.compile(r"(?:장소|위치|venue|place|location)\s*[:：]|[@＠]\s*\S{2,}", re.I)

# v0.96.11: a trip numbers its days, and the number is not a night's.
# "🇦🇷아르헨티나 29일차 (9월 2일ㆍ수)" is day 29 of a month in Buenos Aires -
# the date in the bracket is the day being written *about*, not a day anyone
# can turn up to - and six of those were on public display as Korean events
# dated across August and September.
#
# Never admitted on the number alone, because a multi-day event could count
# its days the same way ("2일차 밀롱가"). The arm below steps aside the moment
# the same title names a night, in the vocabulary classify() already reads one
# by. Measured first: of the 34 festival and marathon titles the stored corpus
# holds, not one numbers a day like this, so the guard costs nothing today and
# is there for the first one that does.
_TRIP_DAY_TITLE_RE = re.compile(r"\d+\s*일\s*차")


def _title_names_a_night_at_all(title: str, event_terms=None) -> bool:
    """Any night vocabulary in the heading, across every scene.

    The union of what the three readings below already use - the milonga
    words (and the operator's Settings terms) via title_names_a_night(), the
    social words social_evidence() reads a heading by, and the non-scene
    notice words notice_evidence_bundle() accepts. Deliberately generous:
    this is only ever asked in order to *decline* to refuse a post.
    """
    heading = title or ""
    if any(word in heading.lower() for word in SOCIAL_WORDS):
        return True
    if _NOTICE_WORDS_RE.search(heading):
        return True
    return title_names_a_night(heading, event_terms)


def is_non_event_notice(title: str, event_terms=None) -> bool:
    """A title that says the post is a recap or an administrative notice.

    v0.96.8 added exactly one word to the administrative half, 휴강 - a
    community saying its regular round is *off* this week. It is in the same
    family as the 취소 안내 / 취소 및 already there, and it is the one thing
    the Daum board collector's own title test cannot see: that test asks
    whether the heading names the club's own night on a specific day
    ("26년9월25일(금) 수라댄 금요정모 휴강" answers yes to both) and has no
    way to notice that the sentence goes on to cancel it. Measured on the
    whole Production corpus, this word changes 3 posts and exactly one of
    them carries an events row - item 3635, the cancelled Friday round that
    was on public display as somewhere to dance. No other cancellation
    vocabulary is admitted here; 폐강/변경/연기 were deliberately left out
    until they have the same evidence behind them.

    v0.96.11 added two words and one arm. The words go where they belong -
    귀국했 in the recap half beside 다녀왔, 협찬 공지/안내/모집/신청 in the
    administrative half beside 가입 안내 and 신청 마감 - and both are written
    as a conjugation and a phrase rather than as bare nouns, because "귀국
    환영 밀롱가" and "협찬사 감사 파티" are nights.

    The arm is the trip diary, and it is the first thing here that asks a
    second question before it refuses: see _TRIP_DAY_TITLE_RE. ``event_terms``
    is optional and only that arm reads it, so every caller that passes a
    title alone behaves exactly as it did.

    **Two measured words were deliberately left out**: 풍경 and 어나운스 each
    take exactly one stored false positive and nothing legitimate today, and
    that is not enough to admit a bare noun *here*. This function is asked
    above the collector's own prior, and 102 of Production's 143 public
    upcoming events have a heading that is a bare name with no digits in it
    ("cabeceo", "이뚜밀", "La Noche"); 81 of them are events only because that
    prior says so. A bare noun in this guard does not risk a false refusal, it
    overrules the one signal that knows better. 어나운스 is besides what this
    scene calls the announcement segment *of* a milonga.
    """
    heading = title or ""
    if _RECAP_TITLE_RE.search(heading) or _ADMIN_NOTICE_TITLE_RE.search(heading):
        return True
    # The third arm, and the only one that asks a second question before it
    # refuses - see _TRIP_DAY_TITLE_RE's own comment for why the number on
    # its own is not enough.
    return bool(
        _TRIP_DAY_TITLE_RE.search(heading)
        and not _title_names_a_night_at_all(heading, event_terms)
    )


def notice_evidence_bundle(title: str, body: str) -> bool:
    """An event announced with a non-scene word, backed by a day and by a
    clock or a place - never the word alone."""
    if not _NOTICE_WORDS_RE.search(title or ""):
        return False
    whole = f"{title or ''} {body or ''}"
    return bool(
        _EXPLICIT_DAY_DATE_RE.search(whole)
        and (_NOTICE_CLOCK_RE.search(whole) or _NOTICE_PLACE_RE.search(whole))
    )


# v0.96.0: the practica, in its standard spellings (PRACTICA / 프락티카 /
# Práctica), is the same kind of tango night the existing "쁘락" already
# counted - a community that writes it out in full was being read as OTHER.
# v0.96.5 lifted this out of classify()'s body so announced_night_evidence()
# below asks "does the title name a night" with the very same vocabulary the
# type decision uses; the list itself is unchanged.
MILONGA_WORDS = ["milonga", "밀롱가", "쁘롱", "쁘락", "프락티카", "practica",
                 "práctica", "쁘락띠까"]

# v0.96.5: a night announced in the title of a post whose body also teaches.
#
# social_evidence() has let a title do exactly this for the other scenes
# since v0.79 - a 소셜 or 파티 in the heading *is* the announcement, and the
# has_class branch below defers to it. The milonga family never had that
# rule, so twelve Production posts whose titles name a real night
# ("2026년 9월 19일 토요일 밀롱가 La Vida No.802", "💢대전까미니또
# 초고급밀롱가", "스물다섯번째 수요 쁘롱가 with DJ 웅이_12월 13일(수)")
# were read as CLASS and produced no candidate at all, because somewhere in
# the body a lesson is mentioned: the milonga's own warm-up ("7:30
# 오픈강습"), the club's beginners' round starting the same week ("이번주부터
# 72기 왕초급 강습이 시작됩니다"), a visiting couple's workshop ("금토일
# 워크샵은 마감"), even an instructor's CV line ("20여년 강습경력"). Half
# of them were still in the future when they were collected; one still is.
#
# The milonga family cannot simply be given social_evidence()'s title rule,
# because a lesson advert names the milonga it teaches you to dance at:
#
#   "[금요특강] 26년 9월 18일 시작!! 밀롱가/땅고 실전패턴!!"   (item 205)
#   "[부산_탱고수업]데이브y지브릴's 쁘롱가 적응 시퀀스..."      (item 3202)
#
# Both carry the night's word and a date in the title, and a bare keyword
# rule would sell either as a night out. So the title has to clear three
# separate tests, not one:
#
#   1. it names a night AND does not call itself a lesson. Both adverts
#      above say so in their own heading - "특강", "탱고수업" - and not
#      one of the twelve real announcements says anything of the kind.
#      This is the *title*, deliberately: a body may mention a class (that
#      is the entire false negative), a title that sells one is selling one.
#   2. the post carries no course evidence anywhere - a fee for tuition, a
#      curriculum, a week number, a term opening. Item 205 has "수강료",
#      "커리큐럼", "6회 수업(2달 과정)"; item 3202 has "참가비용: 6주
#      10만원", "커리큘럼", "1주차", "개강". No real announcement has any of
#      it. This is the second, independent layer: an advert whose heading
#      happens not to say "수업" is still caught here.
#   3. the post carries a night's logistics: a clock, backed by a day, a
#      place, an admission fee or a DJ - the same "an announcement carries
#      logistics, a mention does not" test notice_evidence_bundle() already
#      applies to the other scenes. Two real posts carry no day at all and
#      still announce plainly: item 3643 says only "내일은 행복한 월요일"
#      (which the extractor resolves; the classifier must not demand it),
#      and items 3243/3251 put the week in words - "12월 둘째주" - behind a
#      "☆ 입장료", a "☆ 장소" and a named DJ. For the first of those, the
#      night written directly beside its own clock ("💢밀롱가 8시~10시30")
#      stands alone as the tie, exactly as social_evidence()'s
#      _SOCIAL_BY_CLOCK already reads one.
#
# A title carrying a class word is left alone on purpose, even when the
# lesson is plainly the free extra rather than the product ("비비밀 AM
# 밀롱가 + 살바 무료강습", item 256): that post is genuinely ambiguous, and
# widening the rule to rescue it is the one change that could also rescue an
# advert. It classifies exactly as it did before this rule existed.
_MILONGA = "|".join(MILONGA_WORDS)

# The milonga family's twin of _SOCIAL_BY_CLOCK, same shape, same joins: a
# night written next to its own clock, in either order.
_MILONGA_BY_CLOCK = re.compile(
    rf"(?:{_CLOCK})(?:{_JOIN}){{0,6}}(?:{_MILONGA})"
    rf"|(?:{_MILONGA})(?:{_JOIN}){{0,6}}(?:{_CLOCK})",
    re.I,
)

# What a *title* says when the post is selling the lesson itself. Latin
# terms need their own word boundaries - a "Milonga Clásica" is not a class.
# v0.96.7 added 클라스, the spelling one Production board writes its courses
# in ("밀롱가집중 클라스", "음악수업 푸글리에쎄 클라스"), and gave this
# expression a second reader: classify()'s own education branch, below.
# v0.96.10 added 배우기, how a studio advertises the thing itself rather than
# the course ("수원 서울 남부에서 탱고 배우기", "강남 바차타 라틴댄스 배우기
# 좋은 곳"). Measured on the whole stored corpus before it was written: nine
# items carry it in their title, exactly one of them holds an events row, and
# that row is one of this release's own false positives - the other eight are
# already non-events and stay that way.
_TITLE_SELLS_A_CLASS_RE = re.compile(
    r"강습|수업|강좌|특강|개강|레슨|세미나|클래스|클라스|워크샵|워크숍|커리큘럼|커리큐럼|배우기|"
    r"[초중고]급반|입문반|기초반|안무반|공연반|전문가반|모집|"
    r"(?<![a-z])(?:class|lesson|workshop|seminar)(?![a-z])",
    re.I,
)

# What a course looks like anywhere in the post: tuition, a curriculum, a
# numbered week, a term that opens or closes. A night charges admission
# ("입장료 5,000원") and never any of this.
#
# v0.96.10 added one alternative, the exact twin of the "N주 N만원" already
# here: a block of sessions priced as a block ("일 3회(10/11·18·25) ... 3회
# 12만원 / 1회 4만원", item 3746). A night prices its own door - "입장료
# 12,000원" - and never sells attendance N sessions at a time. Measured on
# the whole stored corpus before it was written: it matches no post that
# carries a genuine event row.
_COURSE_EVIDENCE_RE = re.compile(
    r"수강료|수강\s*신청|수강생|커리큘럼|커리큐럼|개강|종강|"
    r"\d+\s*주\s*차|\d+\s*회\s*차|"
    r"\d+\s*주\s*(?:과정|코스)|\d+\s*회\s*수업|"
    r"\d+\s*주\s*[0-9][0-9,]*\s*만?\s*원|\d+\s*회\s*[0-9][0-9,]*\s*만\s*원",
    re.I,
)

# A word that sells training and is *not*, on its own, a lesson: a real
# night is written this way too. Item 2367 - "[방배 금요쁘락] 5/22 Dani's
# 라비다 쁘락띠까 바디 트레이닝 & 가이드 쁘락" - is a Friday practica, and
# putting 트레이닝 into _TITLE_SELLS_A_CLASS_RE above was measured and
# rejected for exactly that reason: it costs that event and four others of
# the same shape. It is admitted only bundled with course evidence, never
# alone - see sold_as_a_course().
_TITLE_TRAINS_RE = re.compile(r"트레이닝|training", re.I)

# What a SOURCE says about one of its own posts, when it keeps a category
# per item and the runtime can read it off the page's own structured data
# rather than guessing from prose. Two values only, because only two
# answers change anything here: the source calls this a night, or it calls
# it a course. Anything else it might say is None - including a category
# that sits between the two, which must go on classifying exactly as it did.
SOURCE_CATEGORY_EVENT = "EVENT"
SOURCE_CATEGORY_CLASS = "CLASS"


# What a night charges at its own door, and who plays it. Neither is a
# price list or a line-up on its own - both are only ever read together
# with a clock, below.
_ADMISSION_RE = re.compile(r"입장\s*료|입장\s*비|admission", re.I)
_DJ_LINE_RE = re.compile(r"(?<![a-z])dj(?![a-z])|디제이|디징", re.I)


def title_names_a_night(title: str, event_terms=None) -> bool:
    """Does this post's own *title* name a milonga/practica?

    The built-in words plus whatever the operator's Settings terminology adds
    for this source's genre, matched the same way ``has_milonga`` matches them
    in the body (v0.86.9). Lifted out of announced_night_evidence() in v0.96.7
    so the education branch below asks the question with exactly the same
    vocabulary.
    """
    heading = title or ""
    if any(word in heading.lower() for word in MILONGA_WORDS):
        return True
    if not event_terms:
        return False
    folded = normalize_term_text(heading)
    return any(term_occurs(t, folded) for t in event_terms)


def announced_night_evidence(title: str, body: str, event_terms=None) -> bool:
    """Does this post's own *title* announce a milonga/practica night?

    True only when all three of the tests in the comment above hold: the
    title names a night without selling a lesson, no course evidence appears
    anywhere in the post, and the post carries a night's logistics.
    """
    heading = title or ""
    if not title_names_a_night(heading, event_terms):
        return False
    if _TITLE_SELLS_A_CLASS_RE.search(heading):
        return False
    whole = f"{heading} {body or ''}"
    if _COURSE_EVIDENCE_RE.search(whole):
        return False
    if _MILONGA_BY_CLOCK.search(whole):
        return True
    if not _NOTICE_CLOCK_RE.search(whole):
        return False
    return bool(
        _EXPLICIT_DAY_DATE_RE.search(whole)
        or _NOTICE_PLACE_RE.search(whole)
        or _ADMISSION_RE.search(whole)
        or _DJ_LINE_RE.search(whole)
    )


def sold_as_a_course(title: str, body: str, *, source_category=None,
                     event_terms=None) -> bool:
    """Is this post selling enrolment in a course rather than announcing a
    night?

    v0.96.10. The milonga family has had a version of this question since
    v0.96.5 - announced_night_evidence() refuses a post whose own heading
    sells a lesson, and v0.96.7 gave classify() its own education branch on
    the same test. The social family never had one: social_evidence()
    returns True the moment a 소셜 or a 파티 appears in the heading, or beside
    a clock anywhere in the body, and the has_class branch defers to it. Ten
    Production posts reach a reader through that gap, four of them while the
    date they carry is still in the future, which is the whole difference
    between a dirty archive and someone turning up to a paid six-week course
    expecting a night out.

    Three independent readings say "course", and each brings a different
    answer to what a social word in the heading means:

    * **the source filed it under one.** danceinfo.net keeps a category on
      every listing it publishes and the collector now carries it
      (``source_category``). When the site itself says 강습, a social word in
      the title is the *subject being taught* - "살사 소셜 트레이닝", "살사
      소셜패턴", "위드라틴 살사 진짜소셜 시즌8" are three real Production
      false positives and all three are lessons about dancing at a social.
      Nothing in the text separates them from "서울살사위크 소셜이벤트" or
      "[월간 슬로우 소셜파티_SlowJam 12월12일]", which are real; the source
      already had. So this reading, and only this one, outranks the heading.
    * **the post's own title sells a lesson**, the test v0.96.5/v0.96.7
      already trust. Here a social named in that same title still wins, so
      "금요소셜데이 ... 챔피온 칸쌤 특강" and "포토파티 ... 무료 오픈강습"
      go on being nights that teach. What is left is the venue's standing
      slot written into a course timetable - "⏰매주 토요일: 16:00~18:00
      (소셜타임 18:00~22:00)" on a 강습 신청 post - which is a fact about the
      hall, not an announcement.
    * **the title trains and the post prices a block of sessions.**
      _TITLE_TRAINS_RE on its own is not admissible (see its own comment);
      together with course evidence it reads item 3746, "대회실전 트레이닝",
      sold as "3회 12만원 / 1회 4만원".

    Whichever reading brought us here, a night this post announces *in its
    own right* still wins, by the same three tests the other scenes are
    already read with and no new one: notice_evidence_bundle() (a night
    named with a non-scene word, backed by a day and a clock or a place -
    this is what keeps "🌊BAL&SHAG 스페셜 워크샵 in 대전" and its two dated
    socials), party_evidence_bundle() (a door and a price on a named day),
    and a night named in the title beside its own clock.
    """
    heading = title or ""
    whole = f"{heading} {body or ''}"
    by_source = source_category == SOURCE_CATEGORY_CLASS
    by_title = bool(_TITLE_SELLS_A_CLASS_RE.search(heading))
    by_training = bool(
        _TITLE_TRAINS_RE.search(heading) and _COURSE_EVIDENCE_RE.search(whole)
    )
    if not (by_source or by_title or by_training):
        return False
    if notice_evidence_bundle(title, body) or party_evidence_bundle(title, body):
        return False
    if title_names_a_night(title, event_terms) and _MILONGA_BY_CLOCK.search(whole):
        return False
    if by_source:
        return True
    return not any(
        word in _PRODUCT_SUFFIX.sub(" ", heading.lower()) for word in SOCIAL_WORDS
    )


def classify(title: str, body: str, known_event_type=None, event_terms=None,
             source_category=None) -> str:
    # v0.96.8: the recap/administrative guard is asked *before* the collector's
    # own answer, and it is the only thing that may overrule it.
    #
    # `known_event_type` is a collector saying "the page structure I read this
    # off already guarantees the kind of night this is" - a dedicated event
    # board, a milonga listing page. It is a strong prior and it stays one:
    # 324 of Production's 851 events exist only because of it, 56 of them
    # still upcoming, so nothing here weakens or removes it. But it answers
    # *which kind of event* a post announces, and it was being read as though
    # it also answered *whether the post announces one at all* - a question
    # its own evidence (which board the post sits on) cannot decide, because
    # the recap and the announcement sit on the same board.
    #
    # Returning it first meant this function ended before the guard on the
    # next line was ever reached, so every rule underneath - this one, the
    # v0.96.5 night rule, the v0.96.7 education branch - was dead for the 452
    # Production items that carry the prior. What that cost, measured on the
    # whole stored corpus: 126 events that are a club's own archive of a night
    # that already happened ("정기모임 영상 #01", "살사정모 (23/07/31) 영상
    # #13", "금요정모 사진") or, in item 3635's case, a Friday round the post
    # exists to say is *off* - all of it on public display as somewhere to go
    # dancing. The guard already recognised every one of them; it simply never
    # ran. Putting it first corrects all 126 and loses no legitimate event and
    # no upcoming one, because a title that declares itself a recap or an
    # administrative notice is not an announcement whatever board it came from.
    #
    # Deliberately the *only* rule placed above the prior. Everything below
    # still defers to it exactly as before: a collector that knows the night
    # is a milonga is still trusted over any keyword reading of the body.
    if is_non_event_notice(title, event_terms):
        return "OTHER"
    if known_event_type:
        # Source Registry / known series context is admissible evidence for type classification.
        return known_event_type
    text = f"{title} {body}".lower()
    class_words = ["lesson", "강습", "개강", "모집", "안무반", "공연반", "초중급",
                   "전문가반", "워크샵", "워크숍", "workshop"]
    has_class = any(w in text for w in class_words)
    has_milonga = any(w in text for w in MILONGA_WORDS)
    if not has_milonga and event_terms:
        folded = normalize_term_text(f"{title} {body}")
        has_milonga = any(term_occurs(t, folded) for t in event_terms)
    # A post that announces a social and also teaches a class is both. Reading
    # it as a class only -- which is what happened before -- loses the social,
    # and a workshop weekend with a Saturday night party is exactly the shape
    # these posts take.
    has_social = social_evidence(title, body)
    # v0.96.10: ... and a post that is selling the course itself says so in
    # ways social_evidence() cannot see - the source's own category, its own
    # heading, a block of sessions priced as a block. Asked once here and
    # read by both branches below; it never promotes anything, it only
    # declines to let a mentioned social carry a lesson advert.
    course = sold_as_a_course(title, body, source_category=source_category,
                              event_terms=event_terms)

    if has_class:
        # The tango rule is left exactly as it was. "Special Milonga Lesson
        # 개설" mentions a milonga and is a lesson; only an open class attached
        # to a milonga has ever counted as the milonga. v0.96.0: the Korean
        # spellings of that same open class ("오픈클래스", "원데이 클래스 후
        # 밀롱가") count the same way - a one-off open lesson attached to the
        # night, not a course.
        if has_milonga and ("open class" in text or "오픈클래스" in text
                            or "오픈 클래스" in text or "원데이" in text):
            return "MILONGA_WITH_CLASS"
        # The same discipline for the other scenes: mentioning a social is not
        # announcing one, and social_evidence is what tells them apart.
        # v0.96.10: and when the post is selling the course itself, a social
        # it merely carries is not the announcement either - see
        # sold_as_a_course() for the three readings and what still outranks
        # all of them.
        if has_social and not course:
            return "SOCIAL_WITH_CLASS"
        # A second, narrower kind of evidence social_evidence() cannot see:
        # a priced admission to the social itself, on a post that also names
        # its own door opening and a specific day (party_evidence_bundle()'s
        # own comment has the real post and the two real negatives this was
        # built against). Still SOCIAL_WITH_CLASS, the same canonical type
        # social_evidence() would have produced -- no new type is invented.
        if party_evidence_bundle(title, body):
            return "SOCIAL_WITH_CLASS"
        # v0.96.5: the milonga family's own missing version of the rule
        # social_evidence() has always given the other scenes - a night
        # announced in the post's own title, on a post that also teaches.
        # Checked last, so every judgment above it is reached exactly as
        # before and only a post that was about to be called CLASS can be
        # read again (announced_night_evidence()'s own comment has the real
        # Production posts, and the two real lesson adverts, this was built
        # against). Still MILONGA_WITH_CLASS, the canonical type the open-
        # class rule above already produces for a night with a lesson on it.
        if announced_night_evidence(title, body, event_terms=event_terms):
            return "MILONGA_WITH_CLASS"
        return "CLASS"
    # v0.96.7: a lesson advert whose own title sells the lesson in words
    # `class_words` above never carried - 수업, 특강, 클래스, 클라스, 강좌,
    # 레슨.
    #
    # `class_words` is the list that decides whether a post is judged as a
    # class at all, and it knows 강습 and 워크샵 but none of the education
    # vocabulary a studio actually advertises in. A course written only in
    # those words therefore never reached the branch above; it fell through
    # to the milonga/social keyword test below and became a plain MILONGA or
    # SOCIAL, because a lesson advert names the night it teaches you to dance
    # at ("밀롱가 & 발스" on the last line of a six-week syllabus, "Milonga
    # Autumn Edition" over a three-week rhythm course). 121 Production posts
    # use one of those words and classify as an event today; 82 produced a
    # real events row, and about 29 of those are lesson adverts, course
    # schedules or personal notes on public display as dance nights.
    #
    # Simply adding those words to `class_words` was measured and rejected:
    # it corrects 19 of the 29, changes 131 classifications in all and
    # destroys 6 genuine events (one of them still upcoming), because the
    # branch above then reads them with rules
    # built for a different question - the open-class rule promotes item 977's
    # "원데이 클래스" course to MILONGA_WITH_CLASS on the strength of the word
    # 원데이 alone, and item 3127's real night ("가또땅고 Special Event
    # 9월24일 한가위밀롱가", 20:00-24:00, DJ 스톤, 참가비 12,000원) is judged
    # by announced_night_evidence(), which its title does not satisfy because
    # the night is announced as a "Special Event" rather than in a scene word.
    #
    # So this is its own branch, reached only after every judgment above has
    # been made exactly as it was, and it asks the structural question the
    # Production evidence actually separates on rather than a vocabulary one.
    # A title education word appears on 62% of the false positives and 8% of
    # the genuine events; a night announced with no lesson sold in its own
    # heading (notice_evidence_bundle(), announced_night_evidence()) appears
    # on 45% of the genuine events and none of the false positives. Both
    # 977 ("토욜 스페셜 원데이 클래스") and 3127 carry a day, a place and
    # notice_evidence_bundle() - the one thing that tells them apart is
    # whether the post's own title is selling a lesson, which is exactly the
    # test v0.96.5 already trusts to keep a lesson advert out of the milonga
    # family (_TITLE_SELLS_A_CLASS_RE, and see announced_night_evidence()'s
    # own comment for why it is the *title* and never the body).
    #
    # What still beats it, by the same rules the branch above uses: a social
    # or a party announced in this post's own title or written beside its own
    # clock, and a priced door on a named day. A night out that teaches
    # ("바사라 25주년 빅파티 감사특강", "금요소셜데이 ... 칸쌤 특강",
    # "드림발 8주년 파티 & 특강") says so in its heading and stays an event.
    # The open-class promotion above is deliberately *not* repeated here as
    # a word test: "원데이"/"오픈클래스" read as a one-off lesson attached to
    # a night only for a post already judged to be about a night, and item
    # 977's whole title is "토욜 스페셜 원데이 클래스".
    #
    # What takes its place is the structure behind it, and it is the whole
    # difference between a
    # night named *inside* a course ("3주 완성! 밀롱가 리듬 클래스" - 밀롱가
    # is what the six weeks are about) and a night the same heading announces
    # alongside the class ("원데이 오픈클래스 & 밀롱가 9/25(금)", whose body
    # reads "오픈클래스 19:00 / 밀롱가 20:00-23:00"): whether the night has
    # hours of its own. That is not a new idea either - it is _MILONGA_BY_CLOCK,
    # the tie announced_night_evidence() already accepts on its own, and
    # social_evidence() has read a social beside its own clock since v0.79. A
    # course names no hours but the ones it teaches in; item 977's syllabus
    # carries no clock at all. Both halves are required, so the 자율쁘락 slot
    # inside a class timetable ("8:10-8:40 자율쁘락 8:40-9:50 수업", item
    # 3271, whose title is "Lady Leaders Class") rescues nothing.
    if _TITLE_SELLS_A_CLASS_RE.search(title or ""):
        if has_social and not course:
            return "SOCIAL_WITH_CLASS"
        if party_evidence_bundle(title, body):
            return "SOCIAL_WITH_CLASS"
        announces_its_own_night = (
            title_names_a_night(title, event_terms)
            and _MILONGA_BY_CLOCK.search(f"{title or ''} {body or ''}")
        )
        if not announces_its_own_night:
            return "CLASS"
    elif course:
        # v0.96.10: the two readings the branch above cannot reach, because
        # neither is written in the post's own heading - the source's own
        # category, and a title that trains over a block of sessions priced
        # as a block. Everything that outranks them has already been asked
        # inside sold_as_a_course(); what is left is a course.
        return "CLASS"
    if has_milonga:
        return "MILONGA"
    if has_social:
        return "SOCIAL"
    if notice_evidence_bundle(title, body):
        return "SOCIAL"
    return "OTHER"


# Posts a keyword alone is trusted to promote from OTHER. Never CLASS: a
# lesson/workshop advert with no social evidence anywhere (body or poster)
# must never become a milonga/social event just because its poster also
# happens to say "밀롱가" in a schedule footer.
_SOCIAL_CONTEXT_CLASSIFICATIONS = {
    "MILONGA", "SOCIAL", "MILONGA_WITH_CLASS", "SOCIAL_WITH_CLASS",
}

# Mirrors runtime.acquisition.MINIMUM_USEFUL_TEXT (v0.76) - the engine
# package is stdlib-only and does not import runtime, so the threshold is
# restated here rather than shared. Below this, a body or an image reading
# is "too thin to mean anything," not "empty by coincidence."
MIN_TEXT_FOR_IMAGE_TRUST = 20


def classify_with_image_evidence(title: str, body: str, trusted_image_texts=None,
                                 known_event_type=None, published=None,
                                 event_terms=None, source_category=None):
    """classify(), then - only when the body itself was too thin to decide -
    a second, stricter look at each trusted poster OCR text (v0.84.4).

    Returns ``(classification, image_ref)`` - ``image_ref`` is the URL of the
    poster that decided it, or ``None`` when the body alone (or nothing)
    decided it, so a caller can record where a classification came from.

    ``trusted_image_texts`` is a list of ``(image_ref, ocr_text)`` pairs the
    runtime has *already* restricted to what v0.84.4's own gate calls
    trustworthy for classification: inside the post's own content boundary,
    a real poster candidate, OCR succeeded, at least `MIN_TEXT_FOR_IMAGE_TRUST`
    characters, and not classified as a logo/nav asset. This function adds a
    second, independent layer on top of that: even a trusted image is not
    enough by itself:

    * The body must actually have been too thin to judge - a long, text-rich
      post that keyword-classifies as OTHER stays OTHER; an attached image
      never overrides a real, text-rich judgment (Section 12).
    * A single keyword is not enough - the image must classify as carrying
      social/milonga context (not bare CLASS, not OTHER) *and* separately
      read a date *and* (a start time or a LABEL-tagged venue) via the same
      extractor every field-fill already trusts (Section 9). "밀롱가" on its
      own, with no date or time or venue anywhere on the poster, is not
      treated as an event announcement.
    * A poster naming more than one distinct date (a multi-day schedule
      table, a multi-studio listing) never promotes a classification - which
      program the post is even about is not decidable, so no candidate is
      safer than a guessed one (Section 15).

    The first image that clears every gate wins; none of this ever changes
    an already-decided (non-OTHER) classification.
    """
    classification = classify(title, body, known_event_type=known_event_type,
                              event_terms=event_terms,
                              source_category=source_category)
    if classification != "OTHER":
        return classification, None
    if known_event_type:
        return classification, None
    if len((body or "").strip()) >= MIN_TEXT_FOR_IMAGE_TRUST:
        return classification, None
    if not trusted_image_texts:
        return classification, None

    # Imported here, not at module scope - extractor.py has no reason to
    # import classifier.py, and this keeps that one-directional.
    from .extractor import _as_date, _context_segments

    published_date = _as_date(published)
    for image_ref, image_text in trusted_image_texts:
        if not image_text or len(image_text.strip()) < MIN_TEXT_FOR_IMAGE_TRUST:
            continue
        image_classification = classify(title, image_text, event_terms=event_terms,
                                        source_category=source_category)
        if image_classification not in _SOCIAL_CONTEXT_CLASSIFICATIONS:
            continue
        # More than one distinct date on this one poster - a multi-event
        # listing. Which program the post even announces is not decidable
        # from this image; try the next one rather than guess.
        segments = _context_segments(f"{title} {image_text}", published_date)
        if len(segments) > 1:
            continue
        sub = _extract_signal(title, image_text, image_classification, published_date)
        has_date = sub.date is not None
        has_time = sub.start_time is not None
        has_labelled_venue = any(
            e.field == "venue" and (e.inference or "").startswith("LABEL:")
            for e in sub.evidences
        )
        if has_date and (has_time or has_labelled_venue):
            return image_classification, image_ref

    return classification, None


def _extract_signal(title, image_text, event_type, published_date):
    from .extractor import extract_single

    return extract_single(title, image_text, event_type=event_type, published=published_date)


# v0.91.0 PHASE 4/5: real production posts name more than one genre in their
# own text (SRC-D-020 item 2100: "인천 살사&바차타 엘마르"; SRC-D-011 item
# 2225: "살사 바차타 강남 라틴 댄스 동호회") while ``events.genre_id`` is a
# single FK and the posting source is registered under only one genre - the
# second genre has nowhere to be recorded today. This is deliberately
# word-specific, one dedicated term per genre, never the family name: "라틴"
# means "Latin", not Bachata or Kizomba specifically, and a post that only
# ever says "스윙" is not Balboa evidence just because Balboa is a kind of
# swing dance - see test_a_bare_swing_word_is_never_a_balboa_hint.
GENRE_HINT_WORDS = {
    "BACHATA": ("바차타", "bachata"),
    "KIZOMBA": ("키좀바", "kizomba"),
    "BALBOA": ("발보아", "balboa"),
}


def detect_genre_hints(title: str, body: str) -> set[str]:
    """Which other genres (by code) this post's own text names, if any.

    extract_single() turns each hit into a real "genre_hint" Evidence on the
    candidate - the engine's evidences table already stores any field name,
    so this needed no schema change to be a genuine, persisted, queryable
    finding rather than a detector whose output nobody reads. Storing it
    against a *second* events.genre_id is a separate, larger change (see the
    PHASE 4 report's migration-040 recommendation) this function does not
    attempt.
    """
    text = f"{title or ''} {body or ''}".lower()
    return {
        code for code, words in GENRE_HINT_WORDS.items()
        if any(word in text for word in words)
    }
