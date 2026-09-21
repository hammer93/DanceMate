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
_RECAP_TITLE_RE = re.compile(
    r"영상|동영상|후기|사진|스케치|리뷰|다녀왔|되돌아|지난|recap|vlog|photo|video|하이라이트|highlight",
    re.I,
)
_ADMIN_NOTICE_TITLE_RE = re.compile(
    r"가입\s*안내|가입\s*문의|가입방법|회비|회원비|대관|강사\s*소개|자기\s*소개|인사드립니다|"
    r"조직도|환불|신청\s*마감|마감\s*안내|마감되었|취소\s*안내|취소\s*및|마니또|운영진\s*모집|"
    r"설문|투표|경품|추첨|판매|할인|공동구매|공구|계정|에티켓|예절|매너|추천|드레스코드|"
    r"이전\s*안내|주차\s*안내",
    re.I,
)
# A community's own night announced with a word that is not a scene word -
# "Special Event 9월24일", "이번 달 정모", "게스트 DJ 나이트" - counts only
# when the post also names a specific day and either a clock or a place:
# an announcement carries logistics, a mention does not.
_NOTICE_WORDS_RE = re.compile(r"정모|행사|event|특별|스페셜|special|게스트|guest|나이트|night", re.I)
_NOTICE_CLOCK_RE = re.compile(_CLOCK, re.I)
_NOTICE_PLACE_RE = re.compile(r"(?:장소|위치|venue|place|location)\s*[:：]|[@＠]\s*\S{2,}", re.I)


def is_non_event_notice(title: str) -> bool:
    """A title that says the post is a recap or an administrative notice."""
    heading = title or ""
    return bool(_RECAP_TITLE_RE.search(heading) or _ADMIN_NOTICE_TITLE_RE.search(heading))


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
_TITLE_SELLS_A_CLASS_RE = re.compile(
    r"강습|수업|강좌|특강|개강|레슨|세미나|클래스|워크샵|워크숍|커리큘럼|커리큐럼|"
    r"[초중고]급반|입문반|기초반|안무반|공연반|전문가반|모집|"
    r"(?<![a-z])(?:class|lesson|workshop|seminar)(?![a-z])",
    re.I,
)

# What a course looks like anywhere in the post: tuition, a curriculum, a
# numbered week, a term that opens or closes. A night charges admission
# ("입장료 5,000원") and never any of this.
_COURSE_EVIDENCE_RE = re.compile(
    r"수강료|수강\s*신청|수강생|커리큘럼|커리큐럼|개강|종강|"
    r"\d+\s*주\s*차|\d+\s*회\s*차|"
    r"\d+\s*주\s*(?:과정|코스)|\d+\s*회\s*수업|\d+\s*주\s*[0-9][0-9,]*\s*만?\s*원",
    re.I,
)

# What a night charges at its own door, and who plays it. Neither is a
# price list or a line-up on its own - both are only ever read together
# with a clock, below.
_ADMISSION_RE = re.compile(r"입장\s*료|입장\s*비|admission", re.I)
_DJ_LINE_RE = re.compile(r"(?<![a-z])dj(?![a-z])|디제이|디징", re.I)


def announced_night_evidence(title: str, body: str, event_terms=None) -> bool:
    """Does this post's own *title* announce a milonga/practica night?

    True only when all three of the tests in the comment above hold: the
    title names a night without selling a lesson, no course evidence appears
    anywhere in the post, and the post carries a night's logistics.
    """
    heading = title or ""
    names_a_night = any(word in heading.lower() for word in MILONGA_WORDS)
    if not names_a_night and event_terms:
        folded = normalize_term_text(heading)
        names_a_night = any(term_occurs(t, folded) for t in event_terms)
    if not names_a_night:
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


def classify(title: str, body: str, known_event_type=None, event_terms=None) -> str:
    if known_event_type:
        # Source Registry / known series context is admissible evidence for type classification.
        return known_event_type
    if is_non_event_notice(title):
        return "OTHER"
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
        if has_social:
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
                                 event_terms=None):
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
                              event_terms=event_terms)
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
        image_classification = classify(title, image_text, event_terms=event_terms)
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
