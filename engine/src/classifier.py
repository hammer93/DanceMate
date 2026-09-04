import re
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


def classify(title: str, body: str, known_event_type=None) -> str:
    if known_event_type:
        # Source Registry / known series context is admissible evidence for type classification.
        return known_event_type
    text = f"{title} {body}".lower()
    class_words = ["lesson", "강습", "개강", "모집", "안무반", "공연반", "초중급",
                   "전문가반", "워크샵", "워크숍", "workshop"]
    milonga_words = ["milonga", "밀롱가", "쁘롱", "쁘락"]
    has_class = any(w in text for w in class_words)
    has_milonga = any(w in text for w in milonga_words)
    # A post that announces a social and also teaches a class is both. Reading
    # it as a class only -- which is what happened before -- loses the social,
    # and a workshop weekend with a Saturday night party is exactly the shape
    # these posts take.
    has_social = social_evidence(title, body)

    if has_class:
        # The tango rule is left exactly as it was. "Special Milonga Lesson
        # 개설" mentions a milonga and is a lesson; only an open class attached
        # to a milonga has ever counted as the milonga.
        if "open class" in text and has_milonga:
            return "MILONGA_WITH_CLASS"
        # The same discipline for the other scenes: mentioning a social is not
        # announcing one, and social_evidence is what tells them apart.
        if has_social:
            return "SOCIAL_WITH_CLASS"
        return "CLASS"
    if has_milonga:
        return "MILONGA"
    if has_social:
        return "SOCIAL"
    return "OTHER"
