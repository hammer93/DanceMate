"""Deterministic reading rules for time, venue and fee.

Split out of ``extractor.py`` so the imported PoC file keeps a small diff and
so each rule can be tested against the exact strings that broke it.

Every rule here obeys one discipline: **assert only what the text says.**

The v0.73 extractor read ``시간: PM 07:30~11:30`` as ``07:30`` because its
pattern only looked for a meridiem marker *after* the clock. Twelve hours off
is worse than blank -- it sends a dancer to a locked door. Fixing that must not
be traded for the opposite error, so the marker is required evidence: a bare
``5시30~9시30`` stays 05:30 and is reported as AMBIGUOUS for a person to settle.
We never promote a time to the evening merely because dances happen at night.

The strings in the docstrings below are the real ones observed on the board.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# --- meridiem ---------------------------------------------------------------

MERIDIEM_AM = "AM"
MERIDIEM_PM = "PM"

EVIDENCE_EXPLICIT = "EXPLICIT"
EVIDENCE_PROPAGATED = "PROPAGATED"
EVIDENCE_ABSENT = "ABSENT"

# Markers that carry a half-of-day meaning on their own. 새벽 is deliberately
# AM and 밤 is deliberately PM; both are how the posts actually use them.
# marker -> (half of day, hours it may be applied to; None means any hour).
# 오전/오후/AM/PM name a half of the day outright. The Korean time-of-day words
# do not: 밤 11시 is 23:00 but 밤 1시 is 01:00, so applying PM across the board
# would manufacture the very kind of wrong value this release exists to remove.
# Outside its own hours a word simply stops counting as evidence.
_MERIDIEM_WORDS = {
    "am": (MERIDIEM_AM, None), "a.m.": (MERIDIEM_AM, None), "오전": (MERIDIEM_AM, None),
    "pm": (MERIDIEM_PM, None), "p.m.": (MERIDIEM_PM, None), "오후": (MERIDIEM_PM, None),
    "새벽": (MERIDIEM_AM, {12, 1, 2, 3, 4, 5}),
    "저녁": (MERIDIEM_PM, {4, 5, 6, 7, 8, 9, 10, 11}),
    "밤": (MERIDIEM_PM, {6, 7, 8, 9, 10, 11}),
    "낮": (MERIDIEM_PM, {11, 12, 1, 2, 3, 4, 5}),
}
_MARKER = r"(?:[ap]\.?m\.?|오전|오후|저녁|밤|낮|새벽)"

# 7:30 | 07:30 | 7시30분 | 8시 | 5시30
_CLOCK = (
    r"(?:\d{1,2}\s*:\s*\d{2}"          # 19:00, 07:30
    r"|\d{1,2}\s*시(?:\s*\d{1,2}\s*분?)?"  # 8시, 7시30분, 5시30
    r"|\d{1,2}(?=\s*[ap]\.?m\.?))"      # 7pm -- bare hour, marker attached
)
# ~ - – — to 부터 에서 . An en dash is what "PM 8시 – 12시" actually uses.
_SEP = r"\s*(?:~+|-+|–|—|to|부터|에서)\s*"

_RANGE_RE = re.compile(
    rf"(?P<lead1>{_MARKER})?\s*(?P<t1>{_CLOCK})\s*(?P<trail1>{_MARKER})?"
    rf"{_SEP}"
    rf"(?P<lead2>{_MARKER})?\s*(?P<t2>{_CLOCK})\s*(?P<trail2>{_MARKER})?",
    re.I,
)

_HHMM_RE = re.compile(r"(?P<h>\d{1,2})\s*:\s*(?P<m>\d{2})")
_KOREAN_CLOCK_RE = re.compile(r"(?P<h>\d{1,2})\s*시(?:\s*(?P<m>\d{1,2})\s*분?)?")


def _meridiem(token: str | None, hour: int | None = None) -> str | None:
    """The half of day this marker asserts for ``hour``, if it asserts one."""
    if not token:
        return None
    key = token.strip().lower().replace(" ", "")
    found = _MERIDIEM_WORDS.get(key) or _MERIDIEM_WORDS.get(key.replace(".", ""))
    if found is None:
        return None
    meaning, applicable = found
    if applicable is not None and hour is not None and hour not in applicable:
        return None
    return meaning


def _clock_parts(token: str) -> tuple[int, int] | None:
    token = token.strip()
    match = (_HHMM_RE.match(token) or _KOREAN_CLOCK_RE.match(token)
             or _BARE_HOUR_RE.match(token))
    if not match:
        return None
    hour = int(match.group("h"))
    minute = int(match.groupdict().get("m") or 0)
    if minute > 59 or hour > 24:
        return None
    return hour, minute


def _candidates(hour: int, minute: int) -> list[int]:
    """Absolute minutes this clock reading could mean, earliest first.

    A 24-hour reading has exactly one meaning; 1..12 has two. ``24:00`` is
    midnight ending the day, which the PoC already treated as +1 day.
    """
    if hour == 24:
        return [1440 + minute] if minute == 0 else [1440 + minute]
    if hour == 0 or hour > 12:
        return [hour * 60 + minute]
    return sorted({(hour % 12) * 60 + minute, (hour % 12 + 12) * 60 + minute})


def _apply(hour: int, minute: int, marker: str) -> int:
    if hour == 24:
        return 1440 + minute
    base = hour % 12
    if marker == MERIDIEM_PM:
        base += 12
    return base * 60 + minute


_BARE_HOUR_RE = re.compile(r"^(?P<h>\d{1,2})$")


@dataclass
class TimeReading:
    start: str
    end: str
    end_day_offset: int
    raw: str
    #: EXPLICIT when the text carried a PM/오후/저녁 marker, ABSENT when it did not.
    meridiem_evidence: str = EVIDENCE_ABSENT
    #: True when the reading could equally be 12 hours later and nothing says so.
    ambiguous: bool = False

    def as_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "end_day_offset": self.end_day_offset,
            "meridiem_evidence": self.meridiem_evidence,
            "ambiguous": self.ambiguous,
        }


def _resolve_other(anchor: int, hour: int, minute: int, side: str) -> int:
    """Read the unmarked half of a range relative to the marked half.

    ``PM 7:30~12:00`` has one marker. The end is not noon -- it is the next
    12:00 to occur after 19:30, i.e. midnight. Likewise ``6:30-10:30pm`` runs
    from the 6:30 immediately before 22:30. This is reading the range forward
    in time, not guessing which half of the day a lone clock belongs to.
    """
    options = _candidates(hour, minute)
    if side == "end":
        forward = [c for c in options if c > anchor]
        return min(forward) if forward else min(c + 1440 for c in options)
    backward = [c for c in options if c <= anchor]
    if backward:
        return max(backward)
    shifted = [c - 1440 for c in options if c - 1440 >= 0]
    return max(shifted) if shifted else min(options)


def _literal(hour: int, minute: int) -> int:
    return (1440 if hour == 24 else hour * 60) + minute


def _fmt(absolute: int) -> str:
    absolute %= 1440
    return f"{absolute // 60:02d}:{absolute % 60:02d}"


# A post can price and schedule more than one thing. A class before the
# milonga, a paid late-night package after it -- their clock ranges sit in the
# same body. "심야 밀롱가 패키지 23:30 – 04:30" and "7:30-8:45pm 지노&유니 특강"
# are both real, and both were read as the milonga's own hours.
_OTHER_PROGRAMME_TIME = re.compile(
    r"특강|수업|레슨|클래스|워크샵|워크숍|세미나|패키지|애프터|뒤풀이|뒷풀이|"
    r"class|lesson|workshop|after\s*party",
    re.I,
)
_TIME_NEAR_BEFORE = 16
_TIME_NEAR_AFTER = 16


def _is_other_programme(text: str, match: re.Match) -> bool:
    """True when this range belongs to something priced apart from the event."""
    window = (text[max(0, match.start() - _TIME_NEAR_BEFORE):match.start()]
              + text[match.end():match.end() + _TIME_NEAR_AFTER])
    return bool(_OTHER_PROGRAMME_TIME.search(window))


def parse_time_range(text: str, event_type: str | None = None) -> TimeReading | None:
    """The clock range this event runs at, normalised to 24 hours.

    Observed and covered::

        시간: PM 07:30~11:30   -> 19:30-23:30   marker before the clock
        Pm5:30~9:30            -> 17:30-21:30   no space
        6:30-10:30pm           -> 18:30-22:30   marker only on the end
        7pm~10:30pm            -> 19:00-22:30   marker on both
        오후 7시 ~ 11시         -> 19:00-23:00   Korean marker, Korean clock
        PM 8시 – 12시           -> 20:00-00:00+1 en dash, end crosses midnight
        23:30 – 04:30          -> 23:30-04:30+1 no marker, already 24 hour
        5시30~9시30             -> 05:30-09:30   no marker: left alone, ambiguous

    When ``event_type`` names something, a range written beside that name wins.
    A workshop weekend lists three ranges::

        - 15:00-16:30 발스윙 중고급
        - 16:45-18:15 쉐그 초급
        - 20:00-22:30 소셜

    and the social runs at 20:00, not at 15:00. Taking the first range would
    send someone to a class they did not sign up for, which is the same class
    of error as reading PM as AM.
    """
    readings = [r for r in _readings(text or "")]
    if not readings:
        return None
    words = _EVENT_WORDS.get((event_type or "").upper())
    if words:
        for reading, start, end in readings:
            window = ((text or "")[max(0, start - _TIME_NEAR_BEFORE):start]
                      + (text or "")[end:end + _TIME_NEAR_AFTER])
            if re.search(words, window, re.I):
                return reading
    # No reading named the event type nearby (or none was given): the same
    # post can still repeat its own time, once plainly and once with an
    # explicit AM/PM marker (a structured summary line and a free-text body
    # saying the same thing, danceinfo.net's own shape) - preferring
    # whichever repetition actually carries the marker is strictly safer
    # than the first one found by position, since a plain "5:30~9:30"
    # earlier in the text is exactly the reading `ambiguous=True` exists to
    # warn about, not one to prefer over a confirmed match of the same
    # event's own time.
    explicit = next((r for r in readings if r[0].meridiem_evidence == EVIDENCE_EXPLICIT), None)
    if explicit:
        return explicit[0]
    return readings[0][0]


def _readings(text: str):
    """Every clock range in the text that is not another programme's."""
    for match in _RANGE_RE.finditer(text or ""):
        first = _clock_parts(match.group("t1"))
        second = _clock_parts(match.group("t2"))
        if first is None or second is None:
            continue
        if _is_other_programme(text, match):
            continue
        mark1 = (_meridiem(match.group("lead1"), first[0])
                 or _meridiem(match.group("trail1"), first[0]))
        mark2 = (_meridiem(match.group("lead2"), second[0])
                 or _meridiem(match.group("trail2"), second[0]))

        if mark1 and mark2:
            start_abs = _apply(*first, mark1)
            end_abs = _apply(*second, mark2)
            evidence, ambiguous = EVIDENCE_EXPLICIT, False
        elif mark1:
            start_abs = _apply(*first, mark1)
            end_abs = _resolve_other(start_abs, *second, "end")
            evidence, ambiguous = EVIDENCE_EXPLICIT, False
        elif mark2:
            end_abs = _apply(*second, mark2)
            start_abs = _resolve_other(end_abs, *first, "start")
            evidence, ambiguous = EVIDENCE_EXPLICIT, False
        else:
            # No marker anywhere. Report exactly what is written. A dance event
            # is not evidence that 7:30 means 19:30.
            start_abs = _literal(*first)
            end_abs = _literal(*second)
            evidence = EVIDENCE_ABSENT
            ambiguous = 1 <= first[0] <= 12

        if end_abs <= start_abs:
            end_abs += 1440
        if end_abs - start_abs > 1440:
            continue
        yield (
            TimeReading(
                start=_fmt(start_abs),
                end=_fmt(end_abs),
                end_day_offset=end_abs // 1440,
                raw=re.sub(r"\s+", " ", match.group(0)).strip(),
                meridiem_evidence=evidence,
                ambiguous=ambiguous,
            ),
            match.start(),
            match.end(),
        )


# --- venue ------------------------------------------------------------------

# A label must be followed by a colon. Without that rule "위치와 카프레제 파스타"
# and "위치 🕗 시간: PM 8시" -- both real -- become venues, which is worse than
# the 1-in-15 we started with.
_VENUE_LABEL_RE = re.compile(
    r"(?P<label>장소|위치|오시는\s*곳|오시는\s*길|주소|Venue|Location|Place|Address)"
    r"\s*[:：]\s*(?P<value>[^\n]{2,80})",
    re.I,
)

# Where the venue stops and the next field begins. Matched only outside
# parentheses, so "라 벤따나 (서울 마포구 잔다리로 48, 2층)" keeps its address.
_VENUE_STOP_RE = re.compile(
    r"(?:DJ|디제이|시간|일시|날짜|입장료|참가비|회비|요금|계좌|문의|예약|예매|"
    r"오거나이저|주최|주관|Organizer|Reservation|Contact|Fee|Time|Date|Price)"
    r"\s*[:：]?"
    r"|[\[\]【】]"
    r"|\d[\d,]{2,}\s*원"          # a price starts the fee field, not the name
    r"|[가-힣A-Za-z]{2,10}\s*[:：]",  # any other labelled field
    re.I,
)

# An administrative address after the venue name is the address, not the name.
_ADDRESS_START_RE = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별자치시|특별자치도|특별시|광역시|시|도)?\s"
)

_TRIM_LEAD = "#＃@＠:：-–—·•*✦♦◆■●▶>《<「【 \t"


@dataclass
class VenueReading:
    name: str
    raw: str
    label: str
    #: Strings worth trying against the Venue Master aliases, best first.
    alias_candidates: list[str] = field(default_factory=list)


def _strip_decoration(value: str) -> str:
    """Drop emoji and ornaments around a name, keep the name and its brackets."""
    value = value.strip().lstrip(_TRIM_LEAD).strip()
    while value:
        char = value[-1]
        if char == ")":
            break
        if unicodedata.category(char)[0] in ("S", "P", "Z", "M", "C"):
            value = value[:-1]
            continue
        break
    return value.strip()


def _cut_at_boundary(value: str) -> str:
    """Trim a labelled value down to the venue name itself.

    Square brackets are a boundary, not a nesting level -- ``엔빠스(EnPaz Tango
    Studio) [ 테이블`` ends at the ``[``. Round brackets do nest, because the
    address in ``라 벤따나 (서울 마포구 잔다리로 48, 2층)`` belongs to the venue.
    Once such a group closes, the name is over: whatever follows is prose.
    """
    depth = 0
    for index, char in enumerate(value):
        if char in "(（":
            depth += 1
            continue
        if char in ")）":
            depth -= 1
            if depth <= 0:
                return value[:index + 1]
            continue
        if depth:
            continue
        for pattern in (_VENUE_STOP_RE, _ADDRESS_START_RE):
            if pattern.match(value, index):
                return value[:index]
    return value


def extract_venue(text: str) -> VenueReading | None:
    """The labelled venue in ``text``, if the text labels one.

    Observed and covered::

        장소: 아미고스튜디오 DJ : 로띠            -> 아미고스튜디오
        장소: 엔빠스(EnPaz Tango Studio) 서울특별시 -> 엔빠스(EnPaz Tango Studio)
        장소: 라 벤따나 (서울 마포구 잔다리로 48, 2층) -> kept whole, the address is in brackets
        장소 : #데땅고 🌊 ♦︎ 오거나이저:            -> 데땅고
        Venue : Tango Andante 🔸️Reservation   -> Tango Andante
        위치와 카프레제 파스타                     -> None, no colon
    """
    for match in _VENUE_LABEL_RE.finditer(text or ""):
        name = _strip_decoration(_cut_at_boundary(match.group("value")))
        if len(name) < 2:
            continue
        candidates = [name]
        head = re.split(r"[(（]", name, maxsplit=1)[0].strip()
        inner = re.findall(r"[(（]([^)）]{2,40})[)）]", name)
        for extra in [head] + inner:
            extra = _strip_decoration(extra)
            if len(extra) >= 2 and extra not in candidates:
                candidates.append(extra)
        return VenueReading(
            name=name,
            raw=re.sub(r"\s+", " ", match.group(0))[:120].strip(),
            label=match.group("label"),
            alias_candidates=candidates,
        )
    return None


# --- fee --------------------------------------------------------------------

# The 원 suffix is optional only behind an explicit fee label: "fee 10000" is
# real and v0.73 read it correctly. Without both a label and four digits, a
# bare number is a date, a floor or a phone number.
_AMOUNT_RE = re.compile(r"(?P<amount>[0-9][0-9,]*)\s*(?P<won>원)?")
_MIN_UNSUFFIXED_DIGITS = 4

# Split on line and list boundaries. A comma between digits is a thousands
# separator, so "38000원, 특강만" splits but "13,000" does not.
_SEGMENT_RE = re.compile(r"[\n;]|,(?=\s)|(?<=원)\s*,|[·•▪◾]")

# Money in the same breath as one of these is not the entry fee.
_NOT_A_FEE = re.compile(r"주차|할인|적립|보증금|벌금|예금|계좌|송금|환불|후원|기부|상품권", re.I)

# Explicit fee labels.
_FEE_LABEL = re.compile(
    r"(?:입장료|입장\s*비|참가비|참가\s*비용|회비|이용료|관람료|티켓|예매가|엔트리|"
    r"entry\s*fee|entrance|admission|fee|price|cover)\s*[:：]?\s*$",
    re.I,
)

# What the event itself is called, per event type. A milonga's fee is the one
# next to the word 밀롱가; a swing social's is the one next to 소셜.
_EVENT_WORDS = {
    "MILONGA": r"밀롱가|milonga",
    "MILONGA_WITH_CLASS": r"밀롱가|milonga",
    "PRACTICA": r"쁘락띠까|프락티카|practica",
    "CLASS": r"특강|수업|레슨|클래스|워크샵|워크숍|class|lesson|workshop",
    "PARTY": r"파티|party",
    # The other scenes' name for the same thing.
    "SOCIAL": r"소셜|social|파티|party",
    "SOCIAL_WITH_CLASS": r"소셜|social|파티|party",
}
# Public alias: extractor.py's context segmentation (v0.81.2) needs the same
# "what is this event actually called" words to decide which program in a
# multi-program post the classification was about.
EVENT_WORDS = _EVENT_WORDS
# Priced separately from the event and easy to mistake for it.
_OTHER_PROGRAMME = re.compile(r"특강|수업|레슨|클래스|워크샵|워크숍|세미나|class|lesson|workshop", re.I)

# How far either side of an amount we look for words that qualify it.
_NEAR_BEFORE = 20
_NEAR_AFTER = 8

BASIS_LABEL = "LABEL"
BASIS_EVENT_CONTEXT = "EVENT_CONTEXT"


@dataclass
class FeeReading:
    amount: int
    raw: str
    #: LABEL when a fee label named it, EVENT_CONTEXT when the event name did.
    basis: str
    segment: str


def _segments(text: str) -> list[str]:
    return [part.strip() for part in _SEGMENT_RE.split(text or "") if part and part.strip()]


def extract_fee(text: str, event_type: str = "MILONGA") -> FeeReading | None:
    """The fee for *this* event, or nothing.

    A post lists several amounts and only some are the price of getting in.
    Observed and covered::

        💰 입장료 13,000원                    -> 13000, labelled
        밀롱가 : 13,000원                     -> 13000, named by the event
        밀롱가만 13000원                       -> 13000, named by the event
        특강+밀롱가 38000원 / 특강만 30000원     -> skipped, a class package
        주차장 추천(1일 최대 7,000원)            -> skipped, parking
        심야 밀롱가 3,000원 할인                 -> skipped, a discount

    Returns None rather than the first number it can find. An invented fee
    makes a candidate look complete enough to be VERIFIED, which is the one
    thing that must never happen on evidence we do not have.
    """
    event_words = _EVENT_WORDS.get((event_type or "").upper())
    is_class_event = bool(re.search(_EVENT_WORDS["CLASS"], event_type or "", re.I))
    best: tuple[int, int, FeeReading] | None = None

    for order, segment in enumerate(_segments(text)):
        for match in _AMOUNT_RE.finditer(segment):
            amount = int(match.group("amount").replace(",", ""))
            if amount <= 0:
                continue
            before = segment[:match.start()]
            # Judge each amount by the words next to *it*. Scanning the whole
            # segment loses real fees: one post carries "입장료 13,000원" and,
            # sentences later, "심야 밀롱가 3,000원 할인" -- the discount must
            # disqualify itself, not the entry fee.
            near = before[-_NEAR_BEFORE:] + segment[match.end():match.end() + _NEAR_AFTER]
            if _NOT_A_FEE.search(near):
                continue
            # A class price sitting in a milonga post is the class's price.
            if event_words and not is_class_event and _OTHER_PROGRAMME.search(
                before[-_NEAR_BEFORE:]
            ):
                continue
            labelled = bool(_FEE_LABEL.search(before))
            if not match.group("won"):
                digits = match.group("amount").replace(",", "")
                if not labelled or len(digits) < _MIN_UNSUFFIXED_DIGITS:
                    continue
            if labelled:
                tier, basis = 1, BASIS_LABEL
            elif event_words and re.search(
                rf"(?:{event_words})[^0-9]{{0,8}}$", before, re.I
            ):
                tier, basis = 2, BASIS_EVENT_CONTEXT
            else:
                continue
            reading = FeeReading(
                amount=amount,
                raw=re.sub(r"\s+", " ", match.group(0)).strip(),
                basis=basis,
                segment=re.sub(r"\s+", " ", segment)[:120].strip(),
            )
            if best is None or (tier, order) < (best[0], best[1]):
                best = (tier, order, reading)
    return best[2] if best else None
