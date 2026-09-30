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
from dataclasses import dataclass, field, replace

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

# v0.96.27: an endpoint written as a bare hour. "시간: pm 8~11:30" - 화정's
# weekly notice - states a whole range, and `_CLOCK` could not read its head:
# the bare-hour form above requires the marker to *follow* the digits ("7pm"),
# and Production writes it in front at least as often ("pm 8", "오후 8", "밤 10").
# With no range to read, `parse_start_time()` took the only clock `_CLOCK` did
# match - the range's **end** - and advertised an 8pm milonga at 11:30 in the
# morning. Twelve and a half hours off, on a night that happens every week.
#
# A bare number is only a clock when the range *opens* by saying which half of
# the day it means, so the grammar admits it here and `_range_is_readable()`
# refuses it unless a meridiem marker sits on the first endpoint. Without that
# refusal "입장료 8~9만원", "3~4명" and "2026~2027" all become clock ranges.
#
# The marker has to be on the **first** endpoint, not merely somewhere in the
# range, and that was measured rather than assumed. Admitting a trailing-only
# marker ("8-9PM", "12-3PM", "3-AM3") reads four more Production posts, and it
# also reads three it must not: 보니따's "워크샵(2): 8-9PM, 소셜 모픈: 9PM"
# (item 3824) would advertise the workshop instead of the 21:00 the social opens
# at, the bootcamp's "12-3PM, 6-7PM" (item 2256) the same way, and 마제밀's music
# ratio "탱3-발3-밀3-AM3" (item 942) becomes a range at three in the morning.
# A leading marker is what the shapes this release exists for actually write -
# "pm 8~11:30", "오후 8~9시30분", "밤 10~12시", "PM 5~6:30" - and it is the half
# of the grammar that cannot be confused with a fee, a ratio or a headcount.
#
# The head form also has to be joined to its other end by a *symbol*. Written as
# a validation step instead, a bare number in front of a particle consumed the
# match and hid the real range behind it: in "신청은 2부터 오후 8~9시 소셜" the
# regex took "2부터 오후 8", failed it, and never offered "오후 8~9시" at all.
# Grammar decides, so the engine backtracks and finds the range.
_BARE = r"\d{1,2}(?![\d.])"
_SYMBOL_SEP = r"\s*(?:~+|-+|–|—)"
_CLOCK_OR_BARE_HEAD = rf"(?:{_CLOCK}|{_BARE}(?=\s*{_MARKER}?{_SYMBOL_SEP}))"
_CLOCK_OR_BARE_TAIL = rf"(?:{_CLOCK}|{_BARE})"

_RANGE_RE = re.compile(
    rf"(?P<lead1>{_MARKER})?\s*(?P<t1>{_CLOCK_OR_BARE_HEAD})\s*(?P<trail1>{_MARKER})?"
    rf"{_SEP}"
    rf"(?P<lead2>{_MARKER})?\s*(?P<t2>{_CLOCK_OR_BARE_TAIL})\s*(?P<trail2>{_MARKER})?",
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


def _is_bare_hour(token: str) -> bool:
    """A range endpoint written as digits alone - "8" in "pm 8~11:30"."""
    return _BARE_HOUR_RE.match((token or "").strip()) is not None


def _range_markers(match) -> tuple[str | None, str | None]:
    """The half-of-day each endpoint of a range asserts, if it asserts one."""
    first = _clock_parts(match.group("t1"))
    second = _clock_parts(match.group("t2"))
    if first is None or second is None:
        return None, None
    mark1 = (_meridiem(match.group("lead1"), first[0])
             or _meridiem(match.group("trail1"), first[0]))
    mark2 = (_meridiem(match.group("lead2"), second[0])
             or _meridiem(match.group("trail2"), second[0]))
    return mark1, mark2


# A separator that is also an ordinary Korean particle. "8시부터 11시" is a
# range; "밤 9시부터 2만 CC가 소진될 때까지" is a beer promotion and
# "오후8시부터 70분 수업" is a duration. Both are the only two places in the
# stored corpus where a bare endpoint is reached through one of these words, and
# both are wrong, so a bare endpoint is not admitted across them at all.
_WORD_SEP_RE = re.compile(r"부터|에서")


def _range_is_readable(match) -> bool:
    """Is this `_RANGE_RE` match a clock range at all?

    v0.96.27: an endpoint written as a bare hour counts as a clock only when the
    range's *first* endpoint carries a meridiem marker, both endpoints name an
    hour, and the two are joined by a symbol rather than a particle - see
    `_CLOCK_OR_BARE_HEAD` and `_WORD_SEP_RE` for the five Production posts that
    measured those three conditions.
    """
    if not (_is_bare_hour(match.group("t1")) or _is_bare_hour(match.group("t2"))):
        return True
    first = _clock_parts(match.group("t1"))
    second = _clock_parts(match.group("t2"))
    if first is None or second is None:
        return False
    if _WORD_SEP_RE.search(match.string[match.end("t1"):match.start("t2")]):
        return False
    return bool(_meridiem(match.group("lead1"), first[0])
                or _meridiem(match.group("trail1"), first[0]))


def _range_spans(text: str) -> list[tuple[int, int]]:
    """Where a clock range sits, for the clocks `parse_start_time()` must skip.

    Shape, not readability: "9월 21일(토) 21:00-25:00" names no hour 25, so
    `_readings()` yields nothing for it - but the 21:00 is still the head of a
    range somebody wrote, not an independent start, and taking it as one loses
    the end the post's own poster supplies (item 3239). Only the endpoints
    v0.96.27 newly admitted are filtered here, so this keeps exactly the meaning
    it had when it was `_RANGE_RE.finditer()` alone.
    """
    return [m.span() for m in _RANGE_RE.finditer(text or "") if _range_is_readable(m)]


@dataclass
class TimeReading:
    start: str
    # None for a post that names only when the night starts (v0.96.0:
    # "저녁 7시", "8시부터", "7:30pm 시작") - a real start with no claimed end.
    end: "str | None"
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

# v0.96.27: the numbered later set. A night that splits into sets writes each
# one's hours, and the second set's are not when the night begins: 안산 라소클
# (item 4496) says "🚨20시~06시까지" and then "2부24시~06시 라틴펍&파티룸", and
# the 파티 two characters after that range pulled it in, storing a party that
# opens at 20:00 as opening at midnight.
#
# Unlike a class word, this label is positional: Production writes 특강 and
# 워크샵 on either side of the clock they own, but "2부" always sits in front of
# the hours it names. Putting it in `_OTHER_PROGRAMME_TIME` - which searches
# symmetrically - made "1부 5:30~9:30 2부 10:00~11:00" lose *both* readings,
# because the 2부 heading the second range fell inside the first range's window.
# So it is asked as its own question, of the text in front only, and nothing but
# non-digit words may stand between the label and its clock.
#
# `1부` is deliberately left out: the first set begins when the night does, and
# its clock is the one to keep. All four occurrences in the stored corpus want
# that answer - 4538's "1부 21:00~22:30 … 2부 22:30~24:00 … 소셜 21:00~24:00",
# 3770's "PM 9:00 ~ AM 00:00 … 1부 9:00~10:30 … 2부 10:30~12:00", 230's
# "1부 (9~11 PM) … 2부 (11 PM~2 AM)" and 4496's own line.
_LATER_SET_LABEL_RE = re.compile(r"[2-9]\s*부(?![가-힣])[^\d]{0,12}$")


def _is_a_later_sets_clock(text: str, match: "re.Match") -> bool:
    """Is this range labelled as a second or later set of the same night?"""
    return bool(_LATER_SET_LABEL_RE.search(text[max(0, match.start() - 20):match.start()]))


# v0.96.27: an hour somebody is approximating is being narrated, not scheduled.
# 가또땅고's item 3261 is a diary entry - "아침부터 시작된 격무에 오후 3~4시쯤에
# 이미 피곤해서" - and reading it gave a milonga an afternoon it never claimed.
# Measured over all 3,237 stored bodies and OCR texts, a clock reading carries
# one of these words exactly twice, and both are that one sentence.
_APPROXIMATE_AFTER_RE = re.compile(r"^\s*(?:시|분)?\s*(?:쯤|무렵|경에|께)")


def _is_approximate(text: str, end: int) -> bool:
    """Does the text right after a clock call it an approximation?"""
    return bool(_APPROXIMATE_AFTER_RE.match(text[end:end + 6]))


_TIME_NEAR_BEFORE = 16
_TIME_NEAR_AFTER = 16
# v0.96.2: a class word on the other side of a structural break - a line
# break, a bracket heading, a "/" or "|" list separator - belongs to the
# item on that side, not to this clock. "8:00~9:10pm 무료 특강 (아미고) [쁘롱가]
# 9:15~11:15pm": the 특강 sits 12 characters before the milonga's own range,
# but a "[...]" heading stands between them. Bullets are deliberately not a
# break: "8:00~9:10pm ① 무료 일일 특강" (Production) numbers the items *of*
# that clock's slot, so the word after the bullet still qualifies it.
#
# v0.92.0: a section marker ("■", "▣", "◆", "●", "▶", "★") is a break for
# the same reason a "[" heading is - it starts a new section of the post,
# not another item of this clock's slot. Production item 2800 is the case:
# "... 2부 DJ '조커' 9:00~10:30 ■ 타임빠소셜 실시간 스트리밍 서비스 안내".
# The streaming notice's own heading put the word 소셜 within sixteen
# characters of the 2부 set's marker-less clock, so that reading - 09:00,
# an ambiguous morning hour on an evening social - was preferred over the
# same post's explicit "PM 8:15~10:15". Numbering marks (①②, -, ·) stay out
# of this set: they qualify items of a slot, exactly as before.
_PROGRAMME_BREAK = re.compile(r"[\n\[\]/|■▣◆●▶★【】]")


def _near_window(text: str, start: int, end: int) -> str:
    """The text close enough to a clock to say what that clock is for.

    v0.92.0: one definition, used by every rule that reads a word beside a
    clock. `_is_other_programme()` already stopped at a structural break;
    `parse_time_range()`/`parse_start_time()`'s own event-word windows did
    not, so a heading on the far side of a break could still claim a clock
    that was never its own (Production item 2800 - see `_PROGRAMME_BREAK`).
    A word that qualifies a clock and a word that disqualifies one should
    reach exactly as far as each other.
    """
    before = text[max(0, start - _TIME_NEAR_BEFORE):start]
    after = text[end:end + _TIME_NEAR_AFTER]
    breaks = list(_PROGRAMME_BREAK.finditer(before))
    if breaks:
        before = before[breaks[-1].end():]
    cut = _PROGRAMME_BREAK.search(after)
    if cut:
        after = after[:cut.start()]
    return before + after


def _window_span(text: str, start: int, end: int) -> tuple[int, int]:
    """The span of `text` that `_near_window()` reads, as absolute offsets.

    v0.96.19. `_near_window()` returns the before-part and the after-part
    concatenated with the clock removed, so a position in its output cannot be
    mapped back to the text - and the rules below need to look at what follows a
    word, which may be past the window's own end. This reaches exactly as far as
    `_near_window()` does, both structural breaks included, and hands back
    offsets into the text itself.
    """
    lo = max(0, start - _TIME_NEAR_BEFORE)
    before = text[lo:start]
    breaks = list(_PROGRAMME_BREAK.finditer(before))
    if breaks:
        lo += breaks[-1].end()
    after = text[end:end + _TIME_NEAR_AFTER]
    cut = _PROGRAMME_BREAK.search(after)
    return lo, end + (cut.start() if cut else len(after))


def _nearest_near_clock(text: str, pattern, start: int, end: int, skip=None):
    """``(distance, match)`` for the pattern match nearest this clock, or None.

    v0.96.19. Distance is to the nearer edge of the clock, so a word touching it
    scores 0 from either side.
    """
    lo, hi = _window_span(text, start, end)
    best = None
    for match in pattern.finditer(text, lo, hi):
        if match.start() >= start and match.end() <= end:
            continue                      # part of the clock, not a word by it
        if skip is not None and skip(match):
            continue
        gap = ((start - match.end()) if match.end() <= start
               else (match.start() - end))
        gap = max(0, gap)
        if best is None or gap < best[0]:
            best = (gap, match)
    return best


# v0.96.19: a clock, with whatever introduces it, immediately after a word.
# An event word that runs straight into a clock is naming *that* clock, so it
# says nothing about a different range sitting beside it - which is how
# Production writes both "소셜 시작 : PM 8:00" (item 4449, where the 소셜 sits
# nearest the workshop's range and owns the 8 PM after it) and
# "특강 7시~8시 소셜 9시~11시". When the clock it runs into *is* the range being
# judged, the word is that range's own label and must keep naming it - item
# 4415's "파티 시간: P.M 9:00 - A.M 1:00".
_FOLLOWED_BY_CLOCK = re.compile(
    r"(?:[^\S\n]|[·|,()\[\]–—-]){0,3}"
    r"(?:[^\s:：]{0,6}[^\S\n]{0,2}[:：])?[^\S\n]{0,3}"
    r"(?:오전|오후|AM|PM|a\.m|p\.m)?[^\S\n]{0,2}"
    r"(?P<clock>\d{1,2})[:시：]",
    re.I,
)


def _names_another_clock(text: str, word: "re.Match",
                         start: int, end: int) -> bool:
    """Whether this word is naming a clock other than the range at start..end."""
    run = _FOLLOWED_BY_CLOCK.match(text, word.end())
    if run is None:
        return False
    return not (start <= run.start("clock") < end)


def _is_other_programme(text: str, match: re.Match) -> bool:
    """True when this range belongs to something priced apart from the event."""
    return bool(_OTHER_PROGRAMME_TIME.search(
        _near_window(text, match.start(), match.end())))


def _range_belongs_to_other_programme(text: str, match: "re.Match",
                                      words: str | None) -> bool:
    """Whether a clock *range* is another programme's, judged by what is nearest.

    v0.96.19, and the same question v0.96.18 asked of a lone clock - but asked
    of a range, where the blast radius is 1,508 candidates rather than a handful,
    so it carries two rules the lone-clock side does not need.

    Measured over the whole stored corpus - 1,508 range candidates in 891 post
    bodies plus 891 more in 1,550 stored poster OCR texts. 205 of them are
    rejected today (175 in bodies, 30 in OCR). Comparing distances alone would
    admit 8: six are the event's own hours, sitting after somebody else's range
    with the event's word beside them - 가또땅고's "오픈특강 with 샤론y태희
    9:00pm-12:30am 밀롱가", 또도땅고's "미선 특강 - 2:00pm ~ 4:00pm 밀롱가
    씨엠쁘레", 대전까미니또's "●수업 7시~7시50 💢밀롱가 8시~10시30" - and two
    are not. Each needed its own reason, and with both, exactly the six are
    admitted:

    * item 4449's range is the workshop's, labelled as such, and the 소셜 that
      sits nearest it owns the *next* clock - see `_FOLLOWED_BY_CLOCK`.
    * the PISTA poster's "심야밀롱가(11:30 p.m-4:30 a.m) 패키지" is the
      late-night package's hours, not the milonga's - the direction rule below.

    Of the six, three change what a post stores: 3199 and 3735 gain the hours
    their bodies state, and 4415 already read 21:00 from another sentence. The
    other three carry no meridiem, so `_readings()` refuses them a few lines
    further down rather than advertise a morning.

    ``words`` is the event type's own vocabulary. Without it - which is how
    `parse_start_time()`'s guard calls `_readings()` - this is exactly the
    absolute veto it has always been, so that guard's meaning does not move.
    """
    start, end = match.span()
    other = _nearest_near_clock(text, _OTHER_PROGRAMME_TIME, start, end)
    if other is None:
        return False
    if not words:
        return True
    event = _nearest_near_clock(
        text, re.compile(words, re.I), start, end,
        skip=lambda found: _names_another_clock(text, found, start, end))
    if event is None:
        return True
    # Which side the class word sits on decides whether distance may speak at
    # all. Every range in the corpus that a class word wrongly vetoed has the
    # class word *before* it, trailing the previous item -
    # "오픈특강 with 샤론y태희 9:00pm-12:30am 밀롱가",
    # "미선 특강 - 2:00pm ~ 4:00pm 밀롱가 씨엠쁘레" - and there a nearer event
    # word may take the range back. A class word written *after* a range is that
    # range's own trailing label and still owns it however near the event word
    # is: the PISTA poster writes "심야밀롱가(11:30 p.m-4:30 a.m) 패키지", where
    # 밀롱가 is one character before the range and 패키지 two after it, so
    # distance alone would hand the late-night package's hours to the milonga -
    # exactly the reading `_OTHER_PROGRAMME_TIME` exists to stop. The event's own
    # word may sit on either side, because Korean posts label a range as often
    # before ("소셜 오후 9시~11시") as after ("9:00pm-12:30am 밀롱가").
    if other[1].end() > start:
        return True
    # A tie cannot say which programme owns the clock, so it stays rejected.
    return other[0] <= event[0]


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
    words = _EVENT_WORDS.get((event_type or "").upper())
    readings = [r for r in _readings(text or "", words)]
    if not readings:
        return None
    if words:
        # v0.96.19: among the ranges the event's own word names, the one it
        # names *most closely*. Taking the first by position handed a
        # performance its hours - "바차타 클래스 오후 6시~7시 공연 오후
        # 8시~8시30분 LATIN PARTY 오후 9시~12시" put the PARTY inside the
        # 공연 range's window, and the 공연 range came first. A word that
        # heads another range is skipped here for the same reason it is
        # skipped when deciding whether a range was somebody else's at all.
        pattern = re.compile(words, re.I)
        named = []
        for reading, start, end in readings:
            hit = _nearest_near_clock(
                text or "", pattern, start, end,
                skip=lambda found, s=start, e=end: _names_another_clock(
                    text or "", found, s, e))
            if hit is not None:
                named.append((hit[0], reading))
        if named:
            return min(named, key=lambda pair: pair[0])[1]
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


# v0.96.0: a start time with no end. Community notices very often write only
# when the night begins - "저녁 7시", "오후 7시 30분 시작", "8시부터 밀롱가",
# "7:30pm", "19:30" - and _RANGE_RE (two clocks) never sees them, so the
# candidate had no time at all. A lone clock is accepted only when something
# marks it as a *start*: a meridiem word, a 부터/시작/from/open suffix, or
# the unambiguous hh:mm form. A bare "8시" with none of those stays out - it
# is as likely a deadline ("8시 마감") as a start.
_SINGLE_CLOCK_RE = re.compile(
    rf"(?P<lead>{_MARKER})?\s*(?P<t>{_CLOCK})\s*(?P<trail>{_MARKER})?"
    r"\s*(?P<start>부터|시작|start|from|오픈|open)?",
    re.I,
)
_NOT_A_START_AFTER = re.compile(r"^\s*(?:마감|까지|전|이전|until|by)", re.I)

# v0.96.18: a word right before the clock saying the event opens then. The
# suffix form ("9시부터", "9:00 START") is already the `start` group of
# _SINGLE_CLOCK_RE; Production writes the prefix form at least as often -
# "소셜 오픈 오후 9시", "클럽 오픈 오후 8시". Used only to rank one qualified
# candidate above another, never to admit a clock that nothing qualified.
_OPENS_BEFORE = re.compile(r"(?:오픈|시작|open|start|부터)[\s:.\-]*$", re.I)


def _naming_distance(window: str, pattern, clock_start: int, clock_end: int):
    """How far the nearest match of ``pattern`` sits from the clock itself.

    Distance from the clock, not from the window's edge: a word four
    characters before a clock says more about it than one twelve characters
    after, and `_near_window()` alone cannot tell them apart.
    """
    best = None
    for match in pattern.finditer(window):
        start, end = match.span()
        if end <= clock_start:
            gap = clock_start - end
        elif start >= clock_end:
            gap = start - clock_end
        else:
            gap = 0
        if best is None or gap < best:
            best = gap
    return best


def _belongs_to_other_programme(body: str, match: "re.Match", words: str | None) -> bool:
    """Whether a *lone* clock is another programme's, judged by what is nearest.

    `_is_other_programme()` is an absolute veto over a symmetric window, which
    is right for a range - a range beside a class word is that class's hours -
    but wrong for a lone clock in a body that lists both. Production writes
    "PM 8:00~9:00 (워크샵), PM 9:00 START (소셜)": the 워크샵 belongs to the
    range *before* the 9:00, and 소셜 - the word that does qualify it - sits
    immediately after. The absolute veto read the workshop's word and dropped
    the social's own start, so the 21:00 the post states in plain text was
    never recovered and only a poster could supply an hour.

    So for a lone clock the nearer word decides, and a tie still goes to the
    other programme. A clock nothing qualifies is unchanged: with no event
    word in the window at all, any class word beside it still vetoes it, which
    is what keeps "살사 워크샵 오후 7시~9시" from acquiring a social's start.
    """
    window = _near_window(body, match.start(), match.end())
    clock_start = min(_TIME_NEAR_BEFORE, match.start())
    clock_end = clock_start + (match.end() - match.start())
    other = _naming_distance(window, _OTHER_PROGRAMME_TIME, clock_start, clock_end)
    if other is None:
        return False
    if not words:
        return True
    event = _naming_distance(window, re.compile(words, re.I), clock_start, clock_end)
    return event is None or other <= event


def parse_start_time(text: str, event_type: str | None = None) -> TimeReading | None:
    """The night's start when the text names one clock and no range of its own.

    v0.96.18: a class word near a lone clock is weighed against the event's own
    word rather than vetoing it outright, and a clock the post says the event
    *opens* at outranks one that merely sits near the event's name. Two
    Production shapes needed it, and both were losing the hour the post states
    in plain text:

    * "PM 8:00~9:00 (워크샵), PM 9:00 START (소셜)" - BABARU. The workshop's
      word belongs to the range before the 9:00; 소셜 is immediately after it.
      The absolute veto dropped every candidate and the 21:00 came only from a
      poster, or not at all.
    * "오후 7시 제니 y 뚜부 … 오후 8시 뽀대용수 y 밀라 소셜 오픈 오후 9시" -
      홍턴 9/23. Three lone clocks, all near the day's own 파티 heading, so the
      first by position won and the night was advertised at the first
      workshop's hour instead of the 21:00 it opens at.

    Unchanged: the range guard above (a post that states a range of its own is
    read by `parse_time_range()`, which is strictly better evidence than a lone
    clock - deleting the guard was measured over the whole stored corpus and
    changes nothing, so it stays), `_is_other_programme()` itself, and every
    rule that decides what a *range* is for.
    """
    body = text or ""
    if any(True for _ in _readings(body)):
        return None
    words = _EVENT_WORDS.get((event_type or "").upper())
    # A clock written as one end of a range is never an independent start:
    # the tail of "9:00-1:00 소셜" is when the social stops, and the head of
    # "9:00pm-12:30am 밀롱가" is already `parse_time_range()`'s to read.
    ranges = _range_spans(body)
    found = []
    for match in _SINGLE_CLOCK_RE.finditer(body):
        parts = _clock_parts(match.group("t"))
        if parts is None:
            continue
        if any(lo <= match.start("t") and match.end("t") <= hi for lo, hi in ranges):
            continue
        if _belongs_to_other_programme(body, match, words):
            continue
        after = body[match.end():match.end() + 6]
        if _NOT_A_START_AFTER.match(after):
            continue
        if _is_approximate(body, match.end("t")):
            continue
        marker = (_meridiem(match.group("lead"), parts[0])
                  or _meridiem(match.group("trail"), parts[0]))
        hhmm = _HHMM_RE.fullmatch(match.group("t").replace(" ", ""))
        # "20시" / "19시 30분": an hour past twelve is already a 24-hour clock.
        if not marker and not match.group("start") and not hhmm and parts[0] < 13:
            continue
        if marker:
            start_abs = _apply(*parts, marker)
            evidence, ambiguous = EVIDENCE_EXPLICIT, False
        else:
            start_abs = _literal(*parts)
            evidence = EVIDENCE_ABSENT
            ambiguous = 1 <= parts[0] <= 12
        before = body[max(0, match.start() - _TIME_NEAR_BEFORE):match.start()]
        opens = bool(match.group("start")) or bool(_OPENS_BEFORE.search(before))
        found.append((TimeReading(
            start=_fmt(start_abs), end=None, end_day_offset=0,
            raw=re.sub(r"\s+", " ", match.group(0)).strip(),
            meridiem_evidence=evidence, ambiguous=ambiguous,
        ), match.start(), match.end(), opens))
    if not found:
        return None

    def select(candidates):
        if not candidates:
            return None
        if words:
            named = [f for f in candidates
                     if re.search(words, _near_window(body, f[1], f[2]), re.I)]
            if named:
                # v0.96.18: among the clocks the event's own word qualifies, the
                # one the post says it *opens* at is the start. Several can
                # qualify at once - a day's "파티" heading sits beside its
                # workshop hours as well as its own - and taking the first by
                # position advertised the workshop. Position still breaks a tie
                # between two openings.
                opening = [f for f in named if f[3]]
                return (opening or named)[0][0]
        # Two different lone clocks for two different things ("클럽 오픈 오후
        # 8시 ... 오후 7시 핸슨") and neither beside the event's word: which one
        # is the start is anyone's guess, and this rule does not guess.
        if len({r[0].start for r in candidates}) > 1:
            return None
        explicit = next((r for r in candidates
                         if r[0].meridiem_evidence == EVIDENCE_EXPLICIT), None)
        return (explicit or candidates[0])[0]

    chosen = select(found)
    if chosen is None:
        # v0.96.27: the rule below reorders preferences; it never overturns a
        # refusal. item 883 writes "오전 9시부터 7.13.(월) 18:00까지 접수 기간" -
        # an application window - and the class's own hours are on its poster.
        # Dropping the post's other readings would leave that 09:00 standing
        # alone and let it win, which is the guess the refusal above exists to
        # avoid.
        return None
    # v0.96.27: a marker-less morning reading never outranks an explicit one.
    # 위드라틴 (item 2267) states "매주 목요일 저녁 9시" twice and then says the
    # social *moves* at "10시부터"; the 10시 sits beside the word 소셜 and the
    # 저녁 9시 does not, so proximity handed the night 10:00 - ten in the
    # morning, from a clock that carries no marker at all. Proximity decides
    # between readings of equal evidence, not against better evidence, which is
    # the same trade `_readings()` makes for a range and v0.96.18 made for a
    # clock a class word sat beside.
    if not any(f[0].meridiem_evidence == EVIDENCE_EXPLICIT for f in found):
        return chosen
    stronger = [f for f in found if not (f[0].ambiguous and int(f[0].start[:2]) < 12)]
    return select(stronger) or chosen


def _readings(text: str, words: str | None = None):
    """Every clock range in the text that is not another programme's.

    v0.96.19: ``words`` is the event type's own vocabulary. Given it, a range
    beside a class word is weighed against the event's word rather than vetoed
    outright - see `_range_belongs_to_other_programme()`. Left out, which is how
    `parse_start_time()`'s guard calls this, every range is judged exactly as
    before, so that guard's meaning does not move.
    """
    for match in _RANGE_RE.finditer(text or ""):
        first = _clock_parts(match.group("t1"))
        second = _clock_parts(match.group("t2"))
        if first is None or second is None:
            continue
        if not _range_is_readable(match):
            continue
        if _is_a_later_sets_clock(text, match) or _is_approximate(text, match.end()):
            continue
        vetoed = _is_other_programme(text, match)
        if vetoed and _range_belongs_to_other_programme(text, match, words):
            continue
        mark1, mark2 = _range_markers(match)

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
        elif len(_candidates(*second)) == 1 and len(_candidates(*first)) > 1:
            # v0.96.27: no marker, but one endpoint has only one possible
            # meaning - a 24-hour hour, or midnight. That endpoint is evidence
            # for the other one, read the same way `_resolve_other()` already
            # reads the unmarked half of a marked range: backwards in time from
            # a known end. "뉴욕바 소셜 9:00 ~ 00:00" (item 2802) was stored as
            # 09:00-00:00, a fifteen-hour morning social; the 00:00 can only be
            # midnight, and the 9:00 before it can only be 21:00.
            #
            # This is not a promotion to the evening. Measured over all 38
            # occurrences of the shape in the stored corpus, it changes exactly
            # that one reading: "11:00~14:00", "12:40 – 14:00", "11:30-13:00",
            # "12:00-13:20", "08:00~19:00" and the rest all resolve backwards to
            # the very hour they are written as, because their end comes before
            # the afternoon reading of their start.
            end_abs = _literal(*second)
            start_abs = _resolve_other(end_abs or 1440, *first, "start")
            if start_abs == _literal(*first):
                # Reading backwards landed on the hour as written, so nothing
                # was learned and nothing is claimed: this stays the unmarked
                # reading it has always been, including for v0.96.19's guard
                # against admitting a guessed morning.
                evidence, ambiguous = EVIDENCE_ABSENT, 1 <= first[0] <= 12
            else:
                evidence, ambiguous = EVIDENCE_PROPAGATED, False
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
        # v0.96.19: a range admitted only by weighing context must not be an
        # unmarked morning. 루에다's 일정정보 reads "워크샵 2만원 (파티포함)
        # 9시~12시" with no meridiem anywhere, so those hours resolve literally
        # to 09:00-12:00 - and telling somebody to turn up at 9am for a night is
        # worse than telling them nothing, which is what that post says today.
        # The same trade v0.96.18 made for a guessed morning start. A range the
        # absolute veto never objected to is untouched by this.
        if vetoed and ambiguous and start_abs < 12 * 60:
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
#
# v0.96.26 adds five section headings, and only five. Each was checked against
# every venue string Production holds that is correct today (114 distinct, 77 of
# them resolved to the Venue Master): a heading is usable only if it never
# appears inside one. Measured over 1,462 stored bodies and 1,675 stored OCR
# texts, counting occurrences within 140 characters after a venue label:
#
#     협찬        3 after a label   0 inside a resolved venue
#     경품        2                 0
#     후원        1                 0
#     타임테이블    1                 0
#     드레스코드   14                 0
#     수강료      17                 0
#     강습료       3                 0
#
# `수강료`/`강습료` are the two fee labels the list was missing - `입장료`,
# `참가비`, `회비` and `요금` were already there - and they are what ends
# "장소: 분당 실루엣 - 수강료 25만원 춤을 잘 추는 것보다…" at the venue.
#
# `주차` was the one candidate disqualified outright: 23 occurrences after a
# label, but it sits inside four *resolved* venues ("…황제주차빌딩 2층",
# "…서면 황제주차장…"), so a venue whose address names a car park would lose it.
# `파티`, `소셜`, `무료`, `특강`, `이벤트`, `안내`, `공지`, `신청`, `할인` and
# `모집` were left out for the opposite reason: each is common after a label but
# no longer has a case to fix here, and a rule nobody can point at a defect for
# is a rule whose cost nobody measured.
_VENUE_STOP_RE = re.compile(
    r"(?:DJ|디제이|시간|일시|날짜|입장료|참가비|회비|요금|수강료|강습료|계좌|문의|예약|예매|"
    r"오거나이저|주최|주관|협찬|경품|후원|타임\s*테이블|타임\s*라인|드레스\s*코드|"
    r"Organizer|Reservation|Contact|Fee|Time\s*Table|Time|Date|Price)"
    r"\s*[:：]?"
    r"|[\[\]【】]"
    r"|\d[\d,]{2,}\s*원"          # a price starts the fee field, not the name
    r"|[가-힣A-Za-z]{2,10}\s*[:：]"   # any other labelled field
    # v0.96.0: "장소: 이데알 탱고 까페 저녁 7시" / "@오초 19:30" - a clock or a
    # date after the name is the next fact, not part of the name.
    r"|(?:오전|오후|저녁|밤|낮|새벽)\s*\d"
    r"|\d{1,2}\s*(?::\s*\d{2}|시(?!장)|/\s*\d|월\s*\d)",
    re.I,
)

# The same field names `_VENUE_LABEL_RE` reads, as a leading whole word - what
# `_drop_leading_label()` removes when the suffix shortcut swallowed one.
_LEADING_VENUE_LABEL_RE = re.compile(
    r"^(?:장소|위치|오시는\s*곳|오시는\s*길|주소|Venue|Location|Place|Address)"
    r"\s*[:：]?\s+", re.I,
)

# An administrative address after the venue name is the address, not the name.
_ADDRESS_START_RE = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별자치시|특별자치도|특별시|광역시|시|도)?\s"
)

_TRIM_LEAD = "#＃@＠:：-–—·•*✦♦◆■●▶>《<「【 \t"

# v0.96.26: a pictograph after the name is the next section, not more of the
# name. Measured over every venue string Production holds: exactly two emoji
# appear inside one, the cake and the bottle, and both are inside the single
# string this release is here to cut ("...민속공원로 85, B1 [cake]파티음식 맛집!
# [bottle]외부 술·반입 환영! [clock] 타임테이블 20"). Against that, 200+
# pictographs appear within 140 characters after a venue label across the stored
# corpus - hearts, stars, party poppers, phones, pins, money bags - every one of
# them opening a decoration or a new field.
#
# Only *after* the name has started: a label's value routinely opens with one
# ("장소: [pin] 아미고"), and `_strip_decoration()` is what removes those. That
# is what `seen_name` tracks in `_cut_at_boundary()` - a character that is
# neither trim-lead ornament nor pictograph has been passed.
_PICTOGRAPH_RE = re.compile(
    "[🀀-🫿←-⯿☀-➿️〰〽]"
)

# A search snippet that stops mid-sentence marks it with a trailing "..."/"…"
# -- there was more text, the API just did not send it. Real production case:
# SRC-D-012 item 186, "📍장소: 강습 인원..." -- the venue label happened to sit
# right before the cut, and what survived ("강습 인원", "class headcount") is
# a fragment of a later sentence, not a place. A truncated value at the very
# end of the snippet is never trustworthy enough to call a venue.
_TRUNCATED_TAIL_RE = re.compile(r"(?:\.\.\.|…)\s*$")


@dataclass
class VenueReading:
    name: str
    raw: str
    label: str
    #: Strings worth trying against the Venue Master aliases, best first.
    alias_candidates: list[str] = field(default_factory=list)


# What ``VenueReading.label`` says when the post never wrote a field name and
# the *shape* of the sentence was read as one instead: "@ 오초", "아미고
# 스튜디오 9:15pm". Both are real forms a person writes, and both stay - on
# body text. Named here because one caller has to tell them apart from a
# genuine "장소:" label: see ``extractor._image_venue()``.
VENUE_LABEL_AT = "@"
VENUE_LABEL_SUFFIX = "SUFFIX"
VENUE_SHORTCUT_LABELS = frozenset({VENUE_LABEL_AT, VENUE_LABEL_SUFFIX})


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


def _drop_leading_label(value: str) -> str:
    """Drop a venue label the suffix shortcut swallowed as the name's first word.

    ``_SUFFIX_VENUE_RE`` allows up to three words before the "…스튜디오" suffix,
    which is what lets "with DJ 롭 이데알 탱고 까페" find its venue - and what let
    a *label* in, on two real Production posts whose body wrote the field with no
    colon at all::

        "00:00 장소 카디즈 스튜디오"  ->  "장소 카디즈 스튜디오"
        "19:00 장소 R스튜디오"       ->  "장소 R스튜디오"

    Only a leading, whole-word label is dropped, and only when something is left
    after it: a place *named* with one of these words keeps it (this never
    matches "장소" alone), and no Korean venue is called "장소 X".
    """
    stripped = value.strip()
    match = _LEADING_VENUE_LABEL_RE.match(stripped)
    if match is None:
        return value
    remainder = stripped[match.end():]
    return remainder if len(remainder.strip()) >= 2 else value


def _cut_at_boundary(value: str) -> str:
    """Trim a labelled value down to the venue name itself.

    Square brackets are a boundary, not a nesting level -- ``엔빠스(EnPaz Tango
    Studio) [ 테이블`` ends at the ``[``. Round brackets do nest, because the
    address in ``라 벤따나 (서울 마포구 잔다리로 48, 2층)`` belongs to the venue.
    Once such a group closes, the name is over -- unless another one starts
    right where it left off (only whitespace between them): a rendered
    bilingual name followed by its own street address reads as two adjacent
    groups, e.g. ``PosTango (포스탱고) (포항시 남구 중앙로 83, 3층)`` -- and
    dropping the second one silently lost the only text that names the
    venue's actual region (v0.82.5, found live: 47 of 108 real Miltang
    milongas classified as a non-event for an unrelated reason, but this
    boundary rule cost every one of the ones sharing this exact rendering
    its address regardless of classification). Whatever follows a group that
    is not immediately another group is prose, same as before.
    """
    depth = 0
    index = 0
    length = len(value)
    seen_name = False
    while index < length:
        char = value[index]
        if char in "(（":
            depth += 1
            index += 1
            continue
        if char in ")）":
            depth -= 1
            if depth <= 0:
                end = index + 1
                look = end
                while look < length and value[look] in " \t":
                    look += 1
                if look < length and value[look] in "(（":
                    index = end
                    continue
                return value[:end]
            index += 1
            continue
        if depth:
            index += 1
            continue
        matched = False
        for pattern in (_VENUE_STOP_RE, _ADDRESS_START_RE):
            if pattern.match(value, index):
                matched = True
                break
        if matched:
            return value[:index]
        if seen_name and _PICTOGRAPH_RE.match(value, index):
            return value[:index]
        if char not in _TRIM_LEAD and not _PICTOGRAPH_RE.match(value, index):
            seen_name = True
        index += 1
    return value


# v0.96.0: "@ 신천 비바스윙", "@스튜디오 오초", "at OCHO" - the way a
# community writes where without a label. Same boundary rules as a labelled
# value; a handle-looking token (an e-mail, "@instagram") is not a place.
_AT_VENUE_RE = re.compile(
    r"(?:^|(?<=[\s(（\[]))(?:[@＠]|\bat\s)\s*(?P<value>[^\n@＠#,()（）\[\]]{2,60})", re.I,
)
_HANDLE_LIKE = re.compile(r"^[A-Za-z0-9_.]+$")
# "@allaboutswing 팔로우 부탁드립니다" - an ASCII handle followed by Korean
# prose is an account, not a place; "@Studio Ocho" (Latin on Latin) is one.
_HANDLE_THEN_KOREAN = re.compile(r"^[A-Za-z0-9_.]{3,}\s+[가-힣]")
# v0.96.2: the same handle followed by anything that is not a Latin word -
# "@intothelatinittl º 카카오톡 ID: ..." (found in Production: an Instagram
# handle in a contact line, read as the venue "intothelatinittl º 카카오톡").
# An account name has no spaces; a Latin place name continues in Latin.
_HANDLE_THEN_NON_LATIN = re.compile(r"^[A-Za-z0-9_.]{3,}(?:\s+(?![A-Za-z])|$)")
# v0.96.2: an @ inside a contact line is an account whatever script the
# token is in - "인스타그램 DM: @...", "카카오톡 ID: @...". Judged on the few
# characters before the @ and on the value itself; 문의 alone is not here,
# because "문의" also precedes real logistics and the handle shape above
# already refuses "문의 @handle".
_ACCOUNT_CONTEXT = re.compile(
    r"카카오톡|카톡|인스타|instagram|insta\b|\bDM\b|\bID\b|아이디|계정|팔로우|follow|"
    r"텔레그램|telegram|페이스북|facebook|유튜브|youtube|트위터|twitter|틱톡|tiktok|"
    r"이메일|e-?mail|메일",
    re.I,
)
_ACCOUNT_CONTEXT_BEFORE = 12
# v0.96.2: "루 @ 선배님 은 밀롱가에 살다시피 하신다 했다" (found in Production:
# a nickname followed by "@ 선배님", read as the venue "선배님 은 ..."). A
# place name is never followed by a detached particle, so the name ends at
# the first one ("오초 에서 만나요" -> "오초"); what is left is then judged
# by its shape: a Korean honorific (any token ending in 님, or a kinship /
# teacher word) is a person, and a token ending in a sentence predicate is
# prose. No list of real venues is consulted.
_DETACHED_PARTICLE = re.compile(
    r"\s+(?:은|는|이|가|을|를|도|의|에|에서|께서|과|와|로|으로|한테|에게|께)(?=\s|$)")
# Engine 0.91: the same body's second mention was "루 @ 선배님은 지금까지
# 묵묵부답이다… 기다림에 지친 142기" - the particle attached to the honorific
# ("선배님은"), which the detached-particle cut never sees, and the
# predicate in the middle of the value, which a last-token check never
# sees. A person mention is PERSON + optional plural + optional attached
# particle as one token ("선배님", "선배님은", "선배님께서", "회원님들을");
# a longer proper noun that merely starts with an honorific ("선배님카페",
# "대표님스튜디오") is not one, because nothing in the particle list follows
# the honorific. No venue names, no sentence fragments, are listed.
_PERSON_BASE = r"(?:\S*님|형|누나|언니|오빠|쌤|선생|강사|대표|회원|여러분|친구들?|분들?)"
_ATTACHED_PARTICLE = r"(?:께서|에게|한테|에서|으로|은|는|이|가|을|를|도|과|와|께|로|의|에)"
_PERSON_TOKEN = re.compile(rf"^{_PERSON_BASE}들?{_ATTACHED_PARTICLE}?(?=\s|$)")
# A finite sentence ending on the LAST token ("이번주는 쉽니다", "형님 감사합니다").
_PREDICATE_END = re.compile(
    r"(?:니다|했다|하신다|한다|세요|해요|어요|아요|네요|겠죠|죠)[.!?…]*$")
# A finite sentence ending on ANY token of a multi-word value ("선배님은
# 지금까지 묵묵부답이다… 기다림에 지친 142기", "형님이 오셨습니다 감사"): a
# place name has no verb in the middle. Checked only when the value has
# more than one word, so a one-word name that happens to end in 이다/있다
# is still judged by the narrower last-token rule above.
_PREDICATE_WORD = re.compile(
    r"(?:이다|입니다|였다|했다|합니다|한다|된다|됩니다|있다|있습니다|없다|없습니다|"
    r"왔다|왔습니다|니다|세요|해요|어요|아요|네요|죠)[.!?…]*$")
# v0.96.2: a bare room word is a room in some venue, not a venue - "메인홀",
# "안쪽홀", "큰홀", "2홀" were unresolved venue noise in Production. Only the
# generic size/position words are refused; "아미고 큰홀" / "세뇨홀" still
# name something and are left to the Venue Master.
_ROOM_ONLY_RE = re.compile(
    r"^(?:(?:메인|안쪽|바깥쪽|바깥|큰|작은|소|대|지하|\d+층?|[A-Za-z])\s*홀"
    r"|(?:main|big|small|large)\s*hall)$",
    re.I,
)


def _looks_like_account(text: str, match: re.Match, name: str) -> bool:
    """An @-token that is an account or a handle, not a place (v0.96.2)."""
    if _HANDLE_LIKE.match(name) or _HANDLE_THEN_NON_LATIN.match(name):
        return True
    before = text[max(0, match.start() - _ACCOUNT_CONTEXT_BEFORE):match.start()]
    return bool(_ACCOUNT_CONTEXT.search(before) or _ACCOUNT_CONTEXT.search(name))


def _looks_like_person_or_prose(name: str) -> bool:
    """"선배님", "선배님은 …", "형님 감사합니다", "이번주는 쉽니다": not a place
    (v0.96.2; attached particle and mid-value predicate since engine 0.91)."""
    if _PERSON_TOKEN.match(name):
        return True
    words = name.split()
    if not words:
        return False
    if len(words) > 1 and any(_PREDICATE_WORD.search(word) for word in words):
        return True
    return bool(_PREDICATE_END.search(words[-1]))
# v0.96.0: an unlabelled name that ends in a venue word - "이데알 탱고 까페
# 저녁 8시", "홍대 스윙바 20:00" - read only when nothing labels a venue and
# the name sits right before the night's clock, so the suffix alone
# ("스튜디오 대관", "카페 추천") never makes a place.
_SUFFIX_VENUE_RE = re.compile(
    r"(?:^|(?<=[\s:：]))"
    r"(?P<value>(?:[가-힣A-Za-z][가-힣A-Za-z]{0,12}\s){0,3}"
    r"[가-힣A-Za-z]*(?:스튜디오|까페|카페|탱고바|스윙바|라틴바|살사바|홀|Studio|Cafe|Hall))"
    rf"\s*(?:{_MARKER}\s*)?(?:\d{{1,2}}\s*(?::\s*\d{{2}}|시))",
    re.I,
)
_SUFFIX_VENUE_NOT_ALONE = re.compile(r"^(?:스튜디오|까페|카페|홀|Studio|Cafe|Hall)$", re.I)
_NAME_OWNER_BEFORE = re.compile(r"(?:DJ|디제이|with|by|feat\.?)\s*$", re.I)
# The same name right *after* the clock: "19:00-23:00 이데알 탱고 까페".
_SUFFIX_VENUE_AFTER_CLOCK_RE = re.compile(
    r"\d{1,2}\s*(?::\s*\d{2}|시(?:\s*\d{1,2}\s*분?)?)\s*(?:[ap]\.?m\.?)?(?:부터|시작)?\s+"
    r"(?P<value>(?:[가-힣A-Za-z][가-힣A-Za-z]{0,12}\s){0,3}"
    r"[가-힣A-Za-z]*(?:스튜디오|까페|카페|탱고바|스윙바|라틴바|살사바|홀|Studio|Cafe|Hall))"
    r"(?=\s|$|[,.!)])",
    re.I,
)


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
        raw_value = match.group("value")
        remainder = (text or "")[match.end("value"):]
        if not remainder.strip() and _TRUNCATED_TAIL_RE.search(raw_value):
            continue
        name = _strip_decoration(_cut_at_boundary(raw_value))
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
    for match in _AT_VENUE_RE.finditer(text or ""):
        value = match.group("value")
        if _HANDLE_THEN_KOREAN.match(value.strip()):
            continue
        name = _strip_decoration(_cut_at_boundary(value))
        # "(...)" already cut by the boundary; a trailing clock/date is prose.
        name = re.split(r"\s+\d{1,2}\s*[:시/.]", name, maxsplit=1)[0].strip()
        # v0.96.2: the name ends where a detached particle starts the sentence.
        name = _DETACHED_PARTICLE.split(name, maxsplit=1)[0].strip()
        if len(name) < 2 or _looks_like_account(text or "", match, name):
            continue
        if re.search(r"\.(?:com|net|kr|co)\b", name, re.I):
            continue
        if _looks_like_person_or_prose(name) or _ROOM_ONLY_RE.match(name):
            continue
        return VenueReading(
            name=name,
            raw=re.sub(r"\s+", " ", match.group(0))[:120].strip(),
            label=VENUE_LABEL_AT,
            alias_candidates=[name],
        )
    for pattern in (_SUFFIX_VENUE_RE, _SUFFIX_VENUE_AFTER_CLOCK_RE):
        match = next((m for m in pattern.finditer(text or "")
                      if len(_strip_decoration(m.group("value"))) >= 2
                      and not _SUFFIX_VENUE_NOT_ALONE.match(_strip_decoration(m.group("value")))
                      and not _ROOM_ONLY_RE.match(_strip_decoration(m.group("value")))),
                     None)
        if match is None:
            continue
        # "with DJ 롭 이데알 탱고 까페": the DJ's name is the word before the
        # venue, not its first word. Drop leading words that belong to a
        # DJ/with/by phrase until the name stands on its own.
        value, position = match.group("value"), match.start("value")
        while " " in value.strip():
            if not _NAME_OWNER_BEFORE.search((text or "")[:position]):
                break
            step = re.match(r"\S+\s+", value)
            if not step:
                break
            value, position = value[step.end():], position + step.end()
        name = _strip_decoration(_drop_leading_label(value))
        if len(name) < 2 or _SUFFIX_VENUE_NOT_ALONE.match(name) or _ROOM_ONLY_RE.match(name):
            continue
        return VenueReading(
            name=name,
            raw=re.sub(r"\s+", " ", match.group(0))[:120].strip(),
            label=VENUE_LABEL_SUFFIX,
            alias_candidates=[name],
        )
    return None


# --- fee --------------------------------------------------------------------

# The 원 suffix is optional only behind an explicit fee label: "fee 10000" is
# real and v0.73 read it correctly. Without both a label and four digits, a
# bare number is a date, a floor or a phone number.
_AMOUNT_RE = re.compile(r"(?P<amount>[0-9][0-9,]*)\s*(?P<won>원)?")
_MIN_UNSUFFIXED_DIGITS = 4

# "2만원", "1.5만원": Korean 10,000-unit notation. Kept a separate pattern
# from _AMOUNT_RE rather than folded in, because the value needs a x10,000
# conversion _AMOUNT_RE's plain digit matches never do - conflating the two
# would risk misreading a plain "20,000" as "2" if the patterns overlapped.
_MAN_AMOUNT_RE = re.compile(r"(?P<man>[0-9]+(?:\.[0-9]+)?)\s*만\s*(?P<won>원)")

# "8천원", "5천원", bare "8천": Korean 1,000-unit notation - v0.85.9's own
# missing piece, found on a real recurring milonga ("입장료 : 8천원 (10시 이후
# 5천원)") whose fee had read as unknown every week since it never used plain
# digits or 만원. 원 is optional the same way _AMOUNT_RE's is (Section 20's
# bare "8천"), gated back to fee-only meaning by the same label requirement
# extract_fee() already applies to any unsuffixed number - "8천명"/"8천번"
# carry no fee label nearby and so never qualify (Section 21).
_CHEON_AMOUNT_RE = re.compile(r"(?P<cheon>[0-9]+(?:\.[0-9]+)?)\s*천\s*(?P<won>원)?")

# A price sitting next to its own session/membership count is a package or
# membership rate, not the fee for showing up to *this* one listing -
# "10만원(2달, 8회)" is a two-month, eight-visit price. v0.84.1: found live
# on a recurring practica whose post lists three such tiers (2-month,
# 1-month, single-visit) side by side; picking any one of them - even the
# single-visit tier - would still be guessing which of three real numbers
# the reader meant, so the whole post is left unpriced rather than reducing
# a genuine multi-tier price to one arbitrary number (Section 17/20).
_PACKAGE_RE = re.compile(r"\d\s*(?:달|개월)|\d\s*회(?:\)|권|\s|$)")

# "무료", "Free", "입장 무료", "참가비 없음": explicit phrases only, never a
# bare "무료" floating in unrelated prose (a raffle prize, a free shuttle) -
# each of these names admission itself, the same way a fee label names an
# amount. "무료주차"/"무료 음료" structurally cannot match any of these: the
# phrase always pairs 무료 with admission/participation, never with what
# follows an unrelated noun.
_FREE_RE = re.compile(
    r"입장\s*무료|무료\s*입장|참가비\s*없음|무료\s*참가|"
    r"(?:입장료|참가비|회비|이용료)\s*[:：]?\s*무료|"
    r"free\s*(?:admission|entry)?\b",
    re.I,
)

# Split on line and list boundaries. A comma between digits is a thousands
# separator, so "38000원, 특강만" splits but "13,000" does not.
_SEGMENT_RE = re.compile(r"[\n;]|,(?=\s)|(?<=원)\s*,|[·•▪◾]")

# Money in the same breath as one of these is not the entry fee.
#
# "주차" alone disqualifies a nearby amount as a parking fee ("주차장 최대
# 7,000원") - but "무료주차"/"무료 주차" (parking is free, a bare fact with
# no amount of its own) is common enough on a real poster to land within
# _NEAR_BEFORE of a genuine, clearly-labelled entry fee ("무료주차 가능
# 입장료 13,000원"), which must not disqualify that fee just because the
# word "주차" happens to be nearby (v0.84.3: found via a real K-TANGO-shaped
# poster). The lookbehind excludes exactly that phrase and nothing else -
# "주차비"/"주차장"/a bare "주차" next to a real number still disqualify.
_NOT_A_FEE = re.compile(
    r"(?<!무료)(?<!무료 )주차|할인|적립|보증금|벌금|예금|계좌|송금|환불|후원|기부|상품권", re.I
)

# Explicit fee labels.
_FEE_LABEL = re.compile(
    r"(?:입장료|입장\s*비|참가비|참가\s*비용|회비|이용료|관람료|티켓|예매가|엔트리|"
    r"entry\s*fee|entrance|admission|fee|price|cover)\s*[:：]?\s*$",
    re.I,
)

# A price change tied to a time of night, immediately trailing the base
# amount it modifies: "8천원 (10시 이후 5천원)". Section 11-19's whole point --
# a single post naming two real prices under one condition must keep both,
# never collapse to "8,000원" alone (losing the discount) nor to "미확인"
# (losing a fee we do in fact know). Scoped tightly to "(<hour>시 이후 <amount>)"
# immediately after a matched fee so it can never latch onto an unrelated
# parenthetical elsewhere in the post.
_CONDITION_RE = re.compile(
    r"\s*\(\s*(?P<hour>\d{1,2})\s*시\s*이후\s*"
    r"(?:(?P<cheon>[0-9]+(?:\.[0-9]+)?)\s*천\s*원"
    r"|(?P<man>[0-9]+(?:\.[0-9]+)?)\s*만\s*원"
    r"|(?P<amount>[0-9][0-9,]*)\s*원)\s*\)"
)

# A short word naming which of several genuinely different prices an amount
# belongs to - "예매 15,000원 / 현매 20,000원" (Section 14) or "회원 10,000원 /
# 비회원 15,000원" (Section 15). Deliberately a small, real-word list rather
# than "any word before a price": an unrecognised pairing falls back to the
# still-safe "가격 옵션 있음" rather than inventing a label.
_OPTION_WORD_RE = re.compile(
    r"(사전예매|얼리버드|예매|현매|현장|도어|당일|회원|비회원|멤버|비멤버|학생|일반)"
    r"\s*[:：]?\s*$"
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
# v0.96.2: the same question asked with the classifier's own vocabulary -
# the spellings classify() already accepts as "this post is a milonga /
# social" (쁘롱가, 쁘락, practica; 정모 for a community's own night). Used
# only to pick which program of an *ambiguous* multi-program post stands
# as the one reviewed candidate (extractor._select_context); the strict
# EVENT_WORDS above still decide time/fee proximity and schedule expansion.
EVENT_CONTEXT_WORDS = {
    "MILONGA": r"밀롱가|milonga|쁘롱|쁘락|프락티카|practica|práctica",
    "MILONGA_WITH_CLASS": r"밀롱가|milonga|쁘롱|쁘락|프락티카|practica|práctica",
    "PRACTICA": r"쁘락띠까|쁘락|프락티카|practica|práctica",
    "CLASS": _EVENT_WORDS["CLASS"],
    "PARTY": r"파티|party",
    "SOCIAL": r"소셜|social|파티|party|정모",
    "SOCIAL_WITH_CLASS": r"소셜|social|파티|party|정모",
}
# v0.96.17: what a *dated program* may call itself. A schedule post that
# details each of its days names the night on each day's own line, and one
# venue's regular Saturday is written `LATIN NIGHT` and nothing else - 홍턴's
# 추석 run lists four days as 바차타 파티 / 키좀바 파티 / 살사데이 / "추석
# 이벤트 LATIN NIGHT ... DJ RICKY와 함께하는 신나는 토요일 밤 ... 오픈 오후
# 9시", and only the fourth failed to name itself in a word EVENT_WORDS knows.
#
# Deliberately a third mapping rather than a wider EVENT_WORDS, because that
# constant answers four other questions and widening it would answer all of
# them differently for one question's benefit: which clock range is the
# event's time (`_pick_reading`), which lone clock is its start
# (`parse_start_time`), which price is its fee (`extract_fee`'s
# EVENT_CONTEXT tier), and which segment of an ambiguous post is the reviewed
# candidate (`extractor._select_context`). Measured over the whole stored
# corpus, widening EVENT_WORDS globally happens to change the same single
# item today - but the four behaviours it also governs would be permanently
# looser for no measured gain, so the reading stays where the evidence is.
#
# `\bnight\b` and not a substring: the corpus writes `midnight`,
# `#everysaturdaynightmilonga`, `#MidsummerNightLatinTangoParty` and one
# `LATIN NIGHTS`, and none of those is a dated program naming itself. The
# boundary matches all 15 real occurrences (`LATIN NIGHT 살사`, `All~Night
# SALSA Party`) and skips all five of those. The Korean half carries no
# boundary because Korean compounds have none - `바차타나이트`, `살사나이트`
# are how a night is written - and no NIGHT anywhere in the corpus, body or
# poster, is glued straight onto a hangul syllable.
#
# CLASS is deliberately absent: a class is not a night, and a course that
# happens to be held in the evening must not read its own sessions as one.
_NIGHT_NAMED = r"\bnight\b|나이트"
DATED_PROGRAM_WORDS = {
    key: (value if key == "CLASS" else f"{value}|{_NIGHT_NAMED}")
    for key, value in _EVENT_WORDS.items()
}

# Priced separately from the event and easy to mistake for it.
_OTHER_PROGRAMME = re.compile(r"특강|수업|레슨|클래스|워크샵|워크숍|세미나|class|lesson|workshop", re.I)

# How far either side of an amount we look for words that qualify it.
_NEAR_BEFORE = 20
_NEAR_AFTER = 8

BASIS_LABEL = "LABEL"
BASIS_EVENT_CONTEXT = "EVENT_CONTEXT"


@dataclass
class FeeReading:
    #: None for a genuine multiple-option fee (Section 14/15) where no single
    #: number is "the" price - never an arbitrary pick among real options.
    #: Populated with the base amount for a conditional fee (Section 11-13),
    #: since a conditional reading does have one real starting price.
    amount: int | None
    raw: str
    #: LABEL when a fee label named it, EVENT_CONTEXT when the event name did.
    basis: str
    segment: str
    #: Full rendered text for a reading that means more than a plain number -
    #: a conditional discount or a set of named options (Section 18). None
    #: for an ordinary single price, where the caller's own "13,000원"
    #: formatting from ``amount`` already says everything there is to say.
    display: str | None = None


def _segments(text: str) -> list[str]:
    return [part.strip() for part in _SEGMENT_RE.split(text or "") if part and part.strip()]


def _resolve_condition_clock(hour: int, known_start: str | None,
                              known_end: str | None) -> str | None:
    """"22시"-style text for a fee condition's bare hour, anchored to the
    event's own already-EXPLICIT time range - never a blanket AM/PM guess
    (Section 2/23). A post that puts "10시 이후" inside its own 20:00-23:30
    event only makes sense as 22:00: 10:00 would be two hours before the
    party even starts. Resolved only when exactly one of the two 12-hour
    readings actually falls inside that window; otherwise the raw hour is
    kept as written (Section 40's fallback) and nothing is invented.
    """
    if not known_start or not known_end:
        return None
    try:
        s_h, s_m = (int(p) for p in known_start.split(":"))
        e_h, e_m = (int(p) for p in known_end.split(":"))
    except (ValueError, AttributeError):
        return None
    start_min = s_h * 60 + s_m
    end_min = e_h * 60 + e_m
    if end_min < start_min:
        end_min += 1440
    in_range = [c for c in _candidates(hour, 0) if start_min <= c <= end_min]
    if len(in_range) != 1:
        return None
    h, m = divmod(in_range[0] % 1440, 60)
    return f"{h:02d}시" if m == 0 else f"{h:02d}:{m:02d}"


def _condition_amount(match: re.Match) -> int:
    if match.group("cheon"):
        return int(round(float(match.group("cheon")) * 1000))
    if match.group("man"):
        return int(round(float(match.group("man")) * 10000))
    return int(match.group("amount").replace(",", ""))


def extract_fee(text: str, event_type: str = "MILONGA", *,
                 known_start: str | None = None,
                 known_end: str | None = None) -> FeeReading | None:
    """The fee for *this* event, or nothing.

    A post lists several amounts and only some are the price of getting in.
    Observed and covered::

        💰 입장료 13,000원                    -> 13000, labelled
        밀롱가 : 13,000원                     -> 13000, named by the event
        밀롱가만 13000원                       -> 13000, named by the event
        특강+밀롱가 38000원 / 특강만 30000원     -> skipped, a class package
        주차장 추천(1일 최대 7,000원)            -> skipped, parking
        심야 밀롱가 3,000원 할인                 -> skipped, a discount
        8천원 (10시 이후 5천원)                 -> 8000, conditional display
        예매 15,000원 / 현매 20,000원           -> None, multi-option display

    ``known_start``/``known_end`` are the event's own already-EXPLICIT
    "HH:MM" start/end (Section 23) -- the only anchor a fee condition's bare
    hour is ever resolved against; omit them and the condition keeps its raw
    hour text rather than guessing a half of day.

    Returns None rather than the first number it can find. An invented fee
    makes a candidate look complete enough to be VERIFIED, which is the one
    thing that must never happen on evidence we do not have.
    """
    event_words = _EVENT_WORDS.get((event_type or "").upper())
    is_class_event = bool(re.search(_EVENT_WORDS["CLASS"], event_type or "", re.I))
    best: tuple[int, int, FeeReading, re.Match, str] | None = None
    # Every LABEL-tier reading seen, regardless of whether it wins `best` --
    # the only way to notice a *second*, genuinely different, equally-labelled
    # price (Section 14/15) instead of silently picking the first one.
    label_readings: list[tuple[int, int, str, str | None]] = []  # (order, amount, before, opt)

    def _tier(before: str) -> tuple[int, str] | None:
        """LABEL if a fee label named it, EVENT_CONTEXT if the event's own
        name did, or None if neither -- shared by every amount shape below
        so a plain 13,000원 and a 만원-notation 1.3만원 are judged the same
        way."""
        if _FEE_LABEL.search(before):
            return 1, BASIS_LABEL
        if _OPTION_WORD_RE.search(before):
            # 예매/현매/회원/비회원/... name what the price is *for* the same
            # way an explicit fee label does (Section 14/15) - not a lesser
            # signal, just a different word for the same thing.
            return 1, BASIS_LABEL
        if event_words and re.search(rf"(?:{event_words})[^0-9]{{0,8}}$", before, re.I):
            return 2, BASIS_EVENT_CONTEXT
        return None

    def _disqualified(before: str, near: str) -> bool:
        if _NOT_A_FEE.search(near) or _PACKAGE_RE.search(near):
            return True
        # A class price sitting in a milonga post is the class's price.
        return bool(
            event_words and not is_class_event
            and _OTHER_PROGRAMME.search(before[-_NEAR_BEFORE:])
        )

    def _consider(order: int, segment: str, match: re.Match, amount: int,
                  raw: str, require_won_or_label: bool = False,
                  min_unsuffixed_digits: int = _MIN_UNSUFFIXED_DIGITS) -> None:
        nonlocal best
        if amount <= 0:
            return
        before = segment[:match.start()]
        # Judge each amount by the words next to *it*. Scanning the whole
        # segment loses real fees: one post carries "입장료 13,000원" and,
        # sentences later, "심야 밀롱가 3,000원 할인" -- the discount must
        # disqualify itself, not the entry fee.
        near = before[-_NEAR_BEFORE:] + segment[match.end():match.end() + _NEAR_AFTER]
        if _disqualified(before, near):
            return
        # An option word ("예매"/"현매"/"회원"/"비회원"/...) names what the
        # price is for the same way an explicit fee label does (Section
        # 14/15) - "예매15,000" with no 원 at all is still real money once
        # something says whose price it is.
        labelled = bool(_FEE_LABEL.search(before)) or bool(_OPTION_WORD_RE.search(before))
        if require_won_or_label:
            # No 원 on the number itself: only a *label* makes it money at
            # all (never the event's own name - "밀롱가 2026" is a year, not
            # a fee, however many digits it has). A plain digit run also
            # needs to read as real money (4+ digits: "1.3" in "1.3 정도
            # 생각하세요" must not pass); "8천" already carries its own
            # thousands marker, so a single digit is enough once a label is
            # there (Section 20) - callers pick the right floor.
            digits = re.sub(r"[^0-9]", "", raw)
            if not labelled or len(digits) < min_unsuffixed_digits:
                return
        tier = _tier(before)
        if tier is None:
            return
        reading = FeeReading(
            amount=amount,
            raw=re.sub(r"\s+", " ", raw).strip(),
            basis=tier[1],
            segment=re.sub(r"\s+", " ", segment)[:120].strip(),
        )
        if tier[1] == BASIS_LABEL:
            label_readings.append((order, amount, before, _option_word(before)))
        if best is None or (tier[0], order) < (best[0], best[1]):
            best = (tier[0], order, reading, match, segment)

    def _option_word(before: str) -> str | None:
        m = _OPTION_WORD_RE.search(before)
        return m.group(1) if m else None

    for order, segment in enumerate(_segments(text)):
        for match in _AMOUNT_RE.finditer(segment):
            amount = int(match.group("amount").replace(",", ""))
            # A bare digit run with no 원 is accepted only when a label named
            # it AND it reads as real money (4+ digits) - "1.3" in "1.3 정도
            # 생각하세요" must never pass just because something calls it a fee.
            _consider(order, segment, match, amount, match.group(0),
                      require_won_or_label=not match.group("won"))
        for match in _MAN_AMOUNT_RE.finditer(segment):
            amount = int(round(float(match.group("man")) * 10000))
            _consider(order, segment, match, amount, match.group(0))
        for match in _CHEON_AMOUNT_RE.finditer(segment):
            amount = int(round(float(match.group("cheon")) * 1000))
            _consider(order, segment, match, amount, match.group(0),
                      require_won_or_label=not match.group("won"),
                      min_unsuffixed_digits=1)
        for match in _FREE_RE.finditer(segment):
            # Free admission is a real amount (0), but _consider() treats
            # amount<=0 as "nothing found" - that guard exists to keep a
            # stray zero out of the numeric path, so free gets its own
            # handling here rather than reusing it.
            before = segment[:match.start()]
            near = before[-_NEAR_BEFORE:] + segment[match.end():match.end() + _NEAR_AFTER]
            if _disqualified(before, near):
                continue
            tier = _tier(before) or (1, BASIS_LABEL)
            reading = FeeReading(
                amount=0, raw=re.sub(r"\s+", " ", match.group(0)).strip(),
                basis=tier[1], segment=re.sub(r"\s+", " ", segment)[:120].strip(),
            )
            if best is None or (tier[0], order) < (best[0], best[1]):
                best = (tier[0], order, reading, match, segment)

    if best is None:
        return None

    # Multiple genuinely different label-anchored amounts: no single number
    # is "the" fee, so keep amount empty and say what the choices actually
    # are rather than arbitrarily picking one (Section 2/14/15).
    distinct_amounts = sorted({amount for _, amount, _, _ in label_readings})
    if len(distinct_amounts) >= 2:
        ordered: list[tuple[str | None, int]] = []
        seen: set[int] = set()
        for order, amount, before, opt in sorted(label_readings, key=lambda r: r[0]):
            if amount in seen:
                continue
            seen.add(amount)
            ordered.append((opt, amount))
        if all(opt for opt, _ in ordered):
            display = " · ".join(f"{opt} {amount:,}원" for opt, amount in ordered)
        else:
            display = "가격 옵션 있음"
        _, _, reading0, _, segment0 = best
        return FeeReading(
            amount=None, raw=display, basis=BASIS_LABEL,
            segment=segment0, display=display,
        )

    _, _, reading, match, segment = best
    cond = _CONDITION_RE.match(segment, match.end())
    if cond:
        hour = int(cond.group("hour"))
        cond_amount = _condition_amount(cond)
        resolved = _resolve_condition_clock(hour, known_start, known_end)
        hour_text = resolved if resolved else f"{hour}시"
        display = f"{reading.amount:,}원 ({hour_text} 이후 {cond_amount:,}원)"
        reading = replace(reading, display=display)
    return reading
