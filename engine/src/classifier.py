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


def classify(title: str, body: str, known_event_type=None, event_terms=None) -> str:
    if known_event_type:
        # Source Registry / known series context is admissible evidence for type classification.
        return known_event_type
    text = f"{title} {body}".lower()
    class_words = ["lesson", "강습", "개강", "모집", "안무반", "공연반", "초중급",
                   "전문가반", "워크샵", "워크숍", "workshop"]
    milonga_words = ["milonga", "밀롱가", "쁘롱", "쁘락"]
    has_class = any(w in text for w in class_words)
    has_milonga = any(w in text for w in milonga_words)
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
