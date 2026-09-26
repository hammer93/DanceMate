import re
from . import extraction_rules
from . import classifier
from .models import EventCandidate, Evidence

DATE_PATTERNS = [
    # v0.91.0 PHASE 7: an explicit year sitting beside a "m.d-d"/"m/d-d" day
    # range - "BAL&HOP 2026 - 9.18-20", found live. Checked before the plain
    # y.m.d pattern below (which requires no space around its separators and
    # so never matches this shape) and before the bare "m.d" fallback,
    # because a year that is genuinely written down is real evidence and
    # must win over anchoring the range's bare first day against whatever
    # published_at/crawl time happens to be - the exact fragility a page
    # revisited in a later real year (2027 still showing "2026" in its own
    # title) would otherwise hit. Resolves via the same EXPLICIT_YEAR path
    # every other year-bearing pattern already uses (_resolve_date_match) -
    # no new provenance value, no new field.
    re.compile(
        r"(?P<y>20\d{2})[\s\-–—]+(?P<m>\d{1,2})[./](?P<d>\d{1,2})"
        r"\s*-\s*\d{1,2}(?!\d)"
    ),
    re.compile(r"(?P<y>20\d{2})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})"),
    # Cafe notices often abbreviate the year: "26.9.16.정모". Keep the
    # left boundary so a longer four-digit year is never chopped in half.
    re.compile(r"(?<!\d)(?P<y>\d{2})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})(?!\d)"),
    re.compile(r"(?P<y>20\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<y>\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    # v0.92.0: a month naming more than one of its days at once - "9월 19,20일",
    # "10월 1일 & 3일", "9월 19~20일". Written that way by a community whose
    # weekend runs on both days, and read as *no date at all* before this:
    # the plain "M월 D일" above needs the 일 directly after its day, which
    # "19,20일" does not have, and the bare "m/d" fallback below needs a "."
    # or "/" separator. Production carried four of these, all one weekly
    # series (스윙타임빠 8/29, 9/5, 9/12, 9/19), each a real social nobody
    # could place on a calendar.
    #
    # `event_date` is the FIRST day named, exactly as the existing "9.18-20"
    # range already resolves (PHASE 5): `events` holds one date, and
    # inventing a second event out of a list the post never separated into
    # programmes would be guessing. The other days are flagged on the
    # evidence trail as MULTI_DAY_EVENT, the same way that range is, so a
    # person sees the real span.
    #
    # Deliberately checked AFTER the plain "M월 D일": `_norm_date()` tries
    # patterns in order and searches the whole post with each, so a pattern
    # placed earlier beats every later one *wherever it sits in the text*.
    # Ordering this one first would let a list further down the body ("9월
    # 26,27일 워크샵") outrank the title's own "9월 19일". Nothing is lost by
    # going second: a list the plain pattern can read at all ("9월 19일, 20일")
    # resolves to the same first day either way.
    re.compile(
        r"(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일?\s*[,，·&~\-]\s*\d{1,2}\s*일"
    ),
    # Bounded on both sides, or it reads a date out of the middle of a longer
    # number. "2010.12" -- a recording date in a post about a tango camp --
    # matched as 10.12 and became an event this October.
    re.compile(r"(?<!\d)(?P<m>\d{1,2})[./](?P<d>\d{1,2})(?!\d)"),
]

# v0.91.0 PHASE 5: "9.18-20"/"9/18-20" -- a same-month day range, real shape
# (BAL&HOP 2026's own page title). Only ever used to *flag* a multi-day span
# on the evidence trail (see below); `event_date` itself still comes from
# DATE_PATTERNS above and is always just the range's first day.
_DAY_RANGE_RE = re.compile(r"(?<!\d)\d{1,2}[./]\d{1,2}\s*-\s*\d{1,2}(?!\d)")
# v0.92.0: the Korean way of writing that same span - "9월 19,20일",
# "10월 1일 & 3일". Flagged identically (MULTI_DAY_EVENT on the first day),
# for the same reason: the post names days this schema holds one of.
_KOREAN_DAY_LIST_RE = re.compile(
    r"\d{1,2}\s*월\s*\d{1,2}\s*일?\s*[,，·&~\-]\s*\d{1,2}\s*일"
)

# Kept for callers that still reference it. Time reading itself moved to
# extraction_rules.parse_time_range, which also handles a meridiem marker
# placed *before* the clock -- "PM 07:30~11:30", which this pattern read as
# 07:30 and got twelve hours wrong.
TIME_RE = re.compile(
    r"(?P<h1>\d{1,2}):(?P<m1>\d{2})\s*(?P<ap1>am|pm)?\s*(?:-|~|to)\s*"
    r"(?P<h2>\d{1,2}):(?P<m2>\d{2})\s*(?P<ap2>am|pm)?",
    re.I,
)
FEE_RE = re.compile(r"(?:입장료|fee\s*:?)\s*([0-9][0-9,]*)\s*원?", re.I)
# The label repeats (`+`, not one match) because a real page can carry it
# twice in a row: "...구글맵 DJ DJ 네로 강의..." (DanceInfo's own field-label
# "DJ" sitting directly against a value that itself starts with the word
# "DJ" - v0.86.0, found live on event_id 32096, dj had literally read as
# the string "DJ"). A single `DJ\s*[:.]?\s*` stopped at the first "DJ" and
# captured the second one as the name; repeating the label consumes both
# and reaches the real "네로".
DJ_RE = re.compile(r"(?:DJ\s*[:.]?\s*)+([A-Za-z가-힣._]+)", re.I)


def _as_date(value):
    """Whatever the caller had -- a date, a datetime, an ISO string -- as a date."""
    from datetime import date as _date, datetime as _datetime

    if value is None or isinstance(value, _date) and not isinstance(value, _datetime):
        return value
    if isinstance(value, _datetime):
        return value.date()
    try:
        return _datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return _date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# Where a date's year came from. Recorded on the evidence row, because "the
# post said 2026" and "we assumed 2026" are not the same claim and a reader
# deciding where to go tonight is relying on the difference.
EXPLICIT_YEAR = "EXPLICIT_YEAR"          # the post wrote the year
SOURCE_YEAR = "SOURCE_YEAR"              # taken from when the post was written
CURRENT_YEAR_INFERRED = "CURRENT_YEAR_INFERRED"  # see _norm_date; not reachable
UNKNOWN_YEAR = "UNKNOWN_YEAR"            # no year, and nothing to infer it from
SOURCE_RELATIVE_DATE = "SOURCE_RELATIVE_DATE"
SOURCE_WEEKLY_BOUNDED = "SOURCE_WEEKLY_BOUNDED"
# v0.96.0: "매월 둘째 토요일" / "매월 15일" resolved to the one occurrence
# nearest after the post, exactly as 매주 is: never a projected series.
SOURCE_MONTHLY_BOUNDED = "SOURCE_MONTHLY_BOUNDED"

_WEEKDAY = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_RELATIVE = re.compile(
    r"(?P<week>이번주|이번\s*주|다음주|다음\s*주|이번|매주)\s*(?P<day>[월화수목금토일])요일"
    r"|(?P<simple>오늘|내일)")
_ORDINAL = {"첫째": 1, "첫": 1, "둘째": 2, "두번째": 2, "셋째": 3, "세번째": 3, "넷째": 4,
            "네번째": 4, "다섯째": 5, "마지막": -1}
_ORDINAL_WORDS = "|".join(sorted(_ORDINAL, key=len, reverse=True))
_MONTHLY_WEEKDAY_RE = re.compile(
    rf"매월\s*(?P<ord>{_ORDINAL_WORDS})\s*(?:주)?\s*(?P<day>[월화수목금토일])요일")
_MONTHLY_DAY_RE = re.compile(r"매월\s*(?P<d>\d{1,2})\s*일")
# "9월 둘째주 토요일", "10월 마지막 주 금요일" - a named month's nth weekday.
_MONTH_ORDINAL_RE = re.compile(
    rf"(?P<m>\d{{1,2}})\s*월\s*(?P<ord>{_ORDINAL_WORDS})\s*(?:주)?\s*(?P<day>[월화수목금토일])요일")
MAX_DAYS_MONTHLY_AHEAD = 45


def _nth_weekday(year: int, month: int, ordinal: int, weekday: int):
    """The nth (1-based; -1 = last) given weekday of a month, or None."""
    import calendar
    from datetime import date as _date

    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1)
            if _date(year, month, d).weekday() == weekday]
    try:
        return _date(year, month, days[ordinal - 1] if ordinal > 0 else days[-1])
    except IndexError:
        return None


def _monthly_date(text, published):
    """"매월 둘째 토요일" / "매월 15일": the next occurrence on or after the
    post, within MAX_DAYS_MONTHLY_AHEAD. Needs the post's own date."""
    from datetime import date as _date, timedelta

    if published is None:
        return None, None, None
    match = _MONTHLY_WEEKDAY_RE.search(text)
    candidates = []
    if match:
        ordinal, weekday = _ORDINAL[match.group("ord")], _WEEKDAY[match.group("day")]
        for offset in (0, 1, 2):
            month_index = published.month - 1 + offset
            year, month = published.year + month_index // 12, month_index % 12 + 1
            day = _nth_weekday(year, month, ordinal, weekday)
            if day is not None:
                candidates.append(day)
    else:
        match = _MONTHLY_DAY_RE.search(text)
        if not match:
            return None, None, None
        dom = int(match.group("d"))
        for offset in (0, 1, 2):
            month_index = published.month - 1 + offset
            year, month = published.year + month_index // 12, month_index % 12 + 1
            try:
                candidates.append(_date(year, month, dom))
            except ValueError:
                continue
    upcoming = [d for d in candidates if d >= published]
    if not upcoming or (upcoming[0] - published).days > MAX_DAYS_MONTHLY_AHEAD:
        return None, match.group(0), SOURCE_MONTHLY_BOUNDED
    return upcoming[0].isoformat(), match.group(0), SOURCE_MONTHLY_BOUNDED


def _month_ordinal_date(text, published):
    """"9월 둘째주 토요일": the named month's nth weekday, in the year that
    lands nearest the post - the same closest-year rule a bare 9/25 uses."""
    if published is None:
        return None, None, None
    match = _MONTH_ORDINAL_RE.search(text)
    if not match:
        return None, None, None
    month, ordinal, weekday = int(match.group("m")), _ORDINAL[match.group("ord")], _WEEKDAY[match.group("day")]
    if not 1 <= month <= 12:
        return None, None, None
    best = None
    for year in (published.year - 1, published.year, published.year + 1):
        day = _nth_weekday(year, month, ordinal, weekday)
        if day is None:
            continue
        distance = abs((day - published).days)
        if best is None or distance < best[0]:
            best = (distance, day)
    if best is None or best[0] > MAX_DAYS_FROM_POST:
        return None, match.group(0), UNKNOWN_YEAR
    return best[1].isoformat(), match.group(0), SOURCE_YEAR


def _relative_date(text, published):
    """One relative date from the post's timestamp, never the crawl clock.

    A weekly notice yields at most *one* dated occurrence in the week it was
    posted; a fresh notice next week is new evidence. No months-long series
    is projected from an undated/static community advert.
    """
    from datetime import timedelta

    if published is None:
        return None, None, None
    match = _RELATIVE.search(text)
    if not match:
        return None, None, None
    if match.group("simple"):
        day = published + timedelta(days=1 if match.group("simple") == "내일" else 0)
        return day.isoformat(), match.group(0), SOURCE_RELATIVE_DATE
    target = _WEEKDAY[match.group("day")]
    week = re.sub(r"\s+", "", match.group("week"))  # "다음 주" == "다음주"
    if week == "이번주":
        day = published - timedelta(days=published.weekday()) + timedelta(days=target)
        if day < published:
            return None, match.group(0), SOURCE_RELATIVE_DATE
    elif week == "다음주":
        day = published - timedelta(days=published.weekday()) + timedelta(days=7 + target)
    else:
        day = published + timedelta(days=(target - published.weekday()) % 7)
    if (day - published).days > 13:
        return None, match.group(0), SOURCE_RELATIVE_DATE
    provenance = SOURCE_WEEKLY_BOUNDED if week == "매주" else SOURCE_RELATIVE_DATE
    return day.isoformat(), match.group(0), provenance

# How far from the post its event may fall before we stop believing the year.
#
# Measured on the live board, 2026-09-04, over every extracted event whose post
# carried a date: the healthy band runs from 13 days before the post to 22 days
# after, and the next cluster is at 369 days -- posts whose month/day had the
# wrong year attached. 200 sits in the empty gap between the two, an order of
# magnitude clear of real announcements and well short of a year's error. It is
# a threshold on the data rather than a guess, and it is checked by a test that
# names both edges.
MAX_DAYS_FROM_POST = 200


def _yearless_date(month: int, day: int, published):
    """Pick the year for a bare 9/25, or refuse to.

    A post announces something near the time it was written. So try the year
    before, the year of, and the year after the post, and keep whichever lands
    closest to it -- which is what makes 1/3 written on 2025-12-28 mean January
    2026 without a special rule for December, and what stops a 2011 post from
    being read as this year's.
    """
    from datetime import date as _date

    if published is None:
        return None, UNKNOWN_YEAR

    best = None
    for year in (published.year - 1, published.year, published.year + 1):
        try:
            candidate = _date(year, month, day)
        except ValueError:
            continue  # 2/29 in a year that has no 29th
        distance = abs((candidate - published).days)
        if best is None or distance < best[0]:
            best = (distance, candidate)

    if best is None or best[0] > MAX_DAYS_FROM_POST:
        # Every year we could pick puts the event implausibly far from the post
        # that announced it. Missing a date is recoverable; a wrong one sends
        # somebody out on the wrong night.
        return None, UNKNOWN_YEAR
    return best[1], SOURCE_YEAR


def _resolve_date_match(m: "re.Match", published, own_dates=None):
    """One date pattern match, resolved to (date_iso_or_None, provenance).

    Isolated from `_norm_date` so the same per-match resolution can run on
    every date match a multi-program post carries (`_context_segments`), not
    only the first one `_norm_date` itself stops at.

    ``own_dates`` (v0.96.15) is the set of dates this same post already wrote
    with a year of its own (`own_explicit_dates`). It is read only when there
    is no ``published`` to anchor against and only for a day the post has
    already listed in full, so it never invents a year - it matches the
    post's prose back to the post's own date list. Passed by
    `extract_schedule()` alone; every other caller leaves it None and
    resolves exactly as before.
    """
    from datetime import date as _date

    gd = m.groupdict()
    raw_y = gd.get("y")
    mo, d = int(gd["m"]), int(gd["d"])
    if raw_y:
        y = int(raw_y)
        if len(raw_y) == 2:
            y += 2000
        try:
            _date(y, mo, d)
        except ValueError:
            return None, UNKNOWN_YEAR
        return f"{y:04d}-{mo:02d}-{d:02d}", EXPLICIT_YEAR
    resolved, provenance = _yearless_date(mo, d, published)
    if resolved is None and published is None and own_dates:
        # Exactly one of the post's own stated days, or none: two different
        # years with the same month and day in one post is not a match this
        # may guess between.
        same = [o for o in own_dates
                if int(o[5:7]) == mo and int(o[8:10]) == d]
        if len(same) == 1:
            return same[0], EXPLICIT_YEAR
    return (resolved.isoformat() if resolved else None), provenance


def _norm_date(text: str, published=None, default_year=None, own_dates=None):
    """The event's date, and where its year came from.

    ``published`` is the date the post was written. Without it a bare 9/25
    cannot be resolved, and this returns nothing rather than attaching the
    current year -- which is how a post from 2024 became an event this week.

    ``default_year`` is accepted only so older callers keep working; when it is
    given it stands in for the post's date, as those callers intended.

    ``own_dates`` (v0.96.15) is forwarded to `_resolve_date_match` and reaches
    here only from `extract_schedule()`'s per-program read - see that
    function and `own_explicit_dates()`.
    """
    from datetime import date as _date

    published = _as_date(published)
    if published is None and default_year:
        published = _date(int(default_year), 7, 1)  # mid-year: no month bias

    for p in DATE_PATTERNS:
        m = p.search(text)
        if not m:
            continue
        resolved, provenance = _resolve_date_match(m, published, own_dates)
        return resolved, m.group(0), provenance
    # v0.96.0: the ways a community names a day without writing one -
    # a month's nth weekday, this/next/every week's weekday, every month's
    # nth weekday or day - each anchored on the post's own date, never the
    # crawl clock, and each yielding at most one occurrence.
    for reader in (_month_ordinal_date, _relative_date, _monthly_date):
        resolved, raw, provenance = reader(text, published)
        if raw:
            return resolved, raw, provenance
    return None, None, None


# --- event context segmentation (v0.81.2) ------------------------------------
#
# A post can announce more than one program under one title - a festival
# weekend, a performance-then-milonga night, K-TANGO's own multi-day
# schedules. extract_single() used to read date/time/venue/fee off the whole
# post as one flat string; parse_time_range() and extract_fee() already guard
# against picking a *different* program's clock or price (their event_type
# proximity windowing), but _norm_date() and extract_venue() did not, and
# nothing stopped a date that IS a different program's from pairing with a
# time or venue that already correctly avoided it - the actual failure
# observed on K-TANGO's board post: the extractor's date always wins
# first-match, regardless of which program's time/venue the rest of the
# function went on to pick.
#
# The fix does not attempt to parse "the" post into several events. It finds
# where the post changes which date it is talking about, decides - narrowly,
# by the same event_type-name proximity parse_time_range already trusts -
# which one program the classification (MILONGA/SOCIAL/...) was actually
# about, and then extracts date/time/venue/fee from *that program's own text
# only*. A single-program post (the overwhelming majority, and every post
# tested before this release) has exactly one segment spanning the whole
# text, so nothing about it changes.

def _all_date_matches(text: str) -> list["re.Match"]:
    """Every date this text names, earliest first, not just the first pattern
    to match. Overlapping matches from a later, looser pattern (the bare
    "m/d" fallback) are dropped in favour of the earlier, more specific one
    that already covers the same span - the same specificity order
    DATE_PATTERNS already tries in, just not stopping at the first hit."""
    found: list[re.Match] = []
    covered: list[tuple[int, int]] = []
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in covered):
                continue
            found.append(m)
            covered.append((m.start(), m.end()))
    found.sort(key=lambda m: m.start())
    return [m for m in found if not _is_a_price(text, m)]


# v0.96.15: a price written with a decimal point is not a date. The bare
# "m.d" fallback above is bounded on both sides by digits, which is what
# stops it reading one out of "2010.12" - but "1.5만원" has no digit on
# either side and is exactly the shape it was built for. Production writes
# admission and workshop prices that way constantly ("예매 1.5만원 / 현매
# 2만원", "입장료 1.2만원", "3.5만원/2hr워크샵"): 28 occurrences across 21
# items, every one of them a price and not one of them a date.
#
# Harmless until v0.96.15 and not harmless after it. A yearless date only
# resolves against something that supplies the year, and the posts these
# prices sit in carry no `published_at`, so every one of them resolved to
# nothing. This release gives a post a way to date its own yearless days
# (see `own_explicit_dates`), and a price would have been dated with them -
# "1.5만원" on a 2026 post reading as 5 January 2027. Measured against the
# whole stored corpus, the guard changes no existing extraction at all: it
# only refuses a reading nothing was using.
_PRICE_TAIL = re.compile(r"\s*만\s*원")
_BARE_MD = re.compile(r"^\d{1,2}[./]\d{1,2}$")


def _is_a_price(text: str, m: "re.Match") -> bool:
    if m.groupdict().get("y") or not _BARE_MD.match(m.group(0)):
        return False
    return _PRICE_TAIL.match(text, m.end()) is not None


def own_explicit_dates(text: str) -> set:
    """Every date this post writes down *with a year of its own*.

    v0.96.15. Not an inference and not a guess about when the post was
    written - only what it says. Used to let the same post's own yearless
    days ("9/25", "9월 26일") be read as the days it already listed in full
    ("2026-09-25", "09/25 (금)" under a "2026년 9월 24일" heading), and for
    nothing else.
    """
    out = set()
    for m in _all_date_matches(text):
        if not m.groupdict().get("y"):
            continue
        iso, _ = _resolve_date_match(m, None)
        if iso:
            out.add(iso)
    return out


# --- segment boundaries (v0.96.2) -------------------------------------------
#
# v0.81.2 split consecutive programs at the character midpoint between their
# two dates. Production (가또땅고, "9월 둘째주 열탱즐탱 일정", item 3132) showed
# what that does to a flat schedule line: "9/14(월) 8:00~11:00pm 군무 연습
# (이데알) 9/16(수)_..." was cut inside the clock - "8:00~11:00" | "pm ..." -
# and the first program read as 08:00-11:00 with no meridiem, a past morning
# candidate for a night that never existed. A boundary is now placed at an
# explicit structural anchor and never inside a token:
#
#   1. the heading run that introduces the next date - a bullet / list
#      marker / bracket heading / date label, optionally with a few plain
#      words (the program's name) between it and the date ("2. 밤 밀롱가
#      9월 6일", "☆9/18(금)", "[행사] 9/20", "일시: 9/5"), or the start of
#      the line the date heads;
#   2. else, when the text has line structure, the last paragraph break in
#      the gap, else the last line break;
#   3. else - one flat line and nothing marking where the next program
#      starts - the next date itself: in a schedule a program's own words
#      follow its date, so everything up to the next date stays with the
#      program that owns it. No midpoint, no position arithmetic.
#
# Rule 3 is deliberately the "keep, never mix" side of the trade: a name
# written before its own date in unstructured prose may land with the
# previous program (a missing venue), but a clock is never cut in half and a
# later program's time never pairs with an earlier program's date.

_MARKER_TAIL = re.compile(
    r"(?:(?:^|(?<=\s))\d{1,2}[.)]"                      # "1." / "2)"
    r"|[•·▪◾■●▶►◆◇☆★※✔✅🔹🔸📌]"                         # bullets
    r"|[①-⑳]"                                            # circled numbers
    r"|(?:^|(?<=\s))[-–—]"                               # dash bullet
    r"|\[[^\[\]\n]{1,30}\])"                              # "[행사]" heading
    r"\s*$"
)
_DATE_LABEL_TAIL = re.compile(r"(?:일시|일자|날짜|date|when)\s*[:：]?\s*$", re.I)
_PLAIN_WORD_TAIL = re.compile(r"(?:^|(?<=\s))[^\s\d:：]+\s*$")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_HEADING_WORDS_MAX = 4


def _boundary_before(text: str, gap_start: int, date_start: int) -> int:
    """Where the program headed by the date at ``date_start`` begins."""
    j = date_start
    words = 0
    label_start = None  # a date label ("일시:") always travels with its date
    while True:
        while j > gap_start and text[j - 1] in " \t　":
            j -= 1
        if j <= gap_start:
            # Nothing but whitespace (or a date label) between the two
            # dates: the next program starts right after the previous date.
            # Plain words alone are the previous program's, not a heading.
            if words == 0:
                return gap_start
            break
        if text[j - 1] == "\n":
            return j - 1
        tail = text[gap_start:j]
        marker = _MARKER_TAIL.search(tail)
        if marker:
            return gap_start + marker.start()
        label = _DATE_LABEL_TAIL.search(tail)
        if label:
            j = label_start = gap_start + label.start()
            continue
        word = _PLAIN_WORD_TAIL.search(tail)
        if word and words < _HEADING_WORDS_MAX:
            words += 1
            j = gap_start + word.start()
            continue
        break
    if label_start is not None:
        return label_start
    gap = text[gap_start:date_start]
    breaks = list(_PARAGRAPH_BREAK.finditer(gap))
    if breaks:
        return gap_start + breaks[-1].start()
    newline = gap.rfind("\n")
    if newline >= 0:
        return gap_start + newline
    return date_start


def _context_segments(text: str, published, own_dates=None):
    """(context_id, start, end, date_iso) for each program the text names.

    One entry, `context_id=None` spanning the whole text, when there is only
    one date value in the post (or none) - which is "no segmentation", the
    behaviour every post had before this. Two or more distinct dates create
    one segment per date, each ending where the next program's own heading
    begins (`_boundary_before`) - never inside a date or clock token.
    """
    resolved = []
    for m in _all_date_matches(text):
        date_iso, _ = _resolve_date_match(m, published, own_dates)
        if date_iso:
            resolved.append((m, date_iso))

    distinct = {date_iso for _, date_iso in resolved}
    if len(distinct) < 2:
        return [(None, 0, len(text), next(iter(distinct), None))]

    # Collapse consecutive matches that repeat the same program's date (a
    # date mentioned twice in one program's own paragraph) into one boundary.
    boundaries = []
    current = None
    for m, date_iso in resolved:
        if date_iso != current:
            boundaries.append((m, date_iso))
            current = date_iso

    starts = [0]
    for i in range(1, len(boundaries)):
        starts.append(_boundary_before(text, boundaries[i - 1][0].end(), boundaries[i][0].start()))
    segments = []
    for i, (m, date_iso) in enumerate(boundaries):
        end = len(text) if i + 1 == len(boundaries) else starts[i + 1]
        segments.append((f"ctx{i + 1}", starts[i], end, date_iso))
    return segments


# v0.96.2: what a segment carries, for choosing the reviewed candidate of an
# ambiguous multi-program post. A clock in any of the forms the time rules
# read; a place in any of the forms the venue rules read.
_CLOCK_CUE_RE = re.compile(r"\d{1,2}\s*(?::\s*\d{2}|시(?!간)|[ap]\.?m)", re.I)
_PLACE_CUE_RE = re.compile(r"(?:장소|위치|venue|place|location)\s*[:：]|(?:^|\s)[@＠]\s*\S{2,}", re.I)


def _representative(segments, text: str, event_type: str | None, event_terms=None):
    """The segment that stands for an ambiguous multi-program post (v0.96.2).

    v0.81.2 fell back to the first segment, which on a weekly schedule is
    the first program of the week - a rehearsal, a class - not the night the
    post was classified as. The fallback now prefers, in order: a segment
    that names the event in the classifier's own vocabulary (or the source's
    own event terms) *and* carries a clock; one that names it; one with a
    clock; one with a place; else the first. Ties go to the earlier segment.
    The result is still flagged MULTI_EVENT_CONTEXT by the caller - this
    picks a better segment for a person to review, it never removes the
    review.
    """
    words = extraction_rules.EVENT_CONTEXT_WORDS.get((event_type or "").upper())
    terms = tuple(t for t in (event_terms or ()) if t)

    def names_event(span: str) -> bool:
        if words and re.search(words, span, re.I):
            return True
        if terms:
            folded = classifier.normalize_term_text(span)
            return any(classifier.term_occurs(t, folded) for t in terms)
        return False

    def rank(indexed):
        index, segment = indexed
        span = text[segment[1]:segment[2]]
        named = names_event(span)
        clock = bool(_CLOCK_CUE_RE.search(span))
        place = bool(_PLACE_CUE_RE.search(span))
        return (named and clock, named, clock, place, -index)

    return max(enumerate(segments), key=rank)[1]


def _select_context(segments, text: str, event_type: str | None, event_terms=None):
    """Which segment is the announced event, and whether that was ambiguous.

    A segment "is" the event when its own span names this event_type's word
    (밀롱가/소셜/파티/...) - the same word classify() used to call the whole
    post this event_type in the first place. Exactly one segment matching is
    unambiguous. Zero or more than one means the post does not clearly say
    which program the classification was about; the caller falls back to
    one segment (`_representative`, v0.96.2 - never a merged value) and is
    told to flag it.
    """
    if len(segments) == 1:
        return segments[0], False
    words = extraction_rules.EVENT_WORDS.get((event_type or "").upper())
    if words:
        matching = [s for s in segments if re.search(words, text[s[1]:s[2]], re.I)]
        if len(matching) == 1:
            return matching[0], False
    return _representative(segments, text, event_type, event_terms), True


def _convert_hour(h: int, ap: str | None):
    ap = (ap or "").lower()
    if h == 24:
        return 0, 1
    if ap == "am":
        return (0 if h == 12 else h), 0
    if ap == "pm":
        return (h if h == 12 else h + 12), 0
    return h, 0


def _norm_time(text: str, event_type: str | None = None):
    """Backwards-compatible shim: (start, end, end_day_offset, raw)."""
    reading = extraction_rules.parse_time_range(text, event_type)
    if reading is None:
        return None, None, 0, None
    return reading.start, reading.end, reading.end_day_offset, reading.raw


def extract_single(title: str, body: str, source_role="SECONDARY", name_hint=None,
                   event_type=None, published=None, event_terms=None,
                   own_dates=None):
    """One event read out of one post.

    ``event_type`` is the classifier's verdict. It decides which words the time
    and fee rules look beside: a milonga's fee sits next to 밀롱가, a swing
    social's next to 소셜. Left out, everything behaves as it did before.

    ``published`` is when the post was written. A post says "9/25" and means
    the 25th of September near the time it was writing; without knowing when
    that was, the day cannot be placed in a year and no date is claimed.

    ``event_terms`` (v0.96.2) are the source's own words for its night, the
    same ones classify() accepted; they only help choose which program of an
    ambiguous multi-program post is reviewed, never what is read from it.

    ``own_dates`` (v0.96.15) is passed by `extract_schedule()` alone, so that
    one program's own slice of a schedule post can read the yearless day that
    heads it against the day list the whole post already wrote out. Left out -
    which is every other caller - nothing about date resolution changes.
    """
    text = f"{title} {body}"
    name = name_hint or re.sub(r"\s+", " ", title).strip()
    ev = EventCandidate(name=name, event_type=event_type or "MILONGA")

    published_date = _as_date(published)
    segments = _context_segments(text, published_date, own_dates)
    (context_id, seg_start, seg_end, seg_date), ambiguous = _select_context(
        segments, text, ev.event_type, event_terms
    )
    # Single segment (the overwhelming majority of posts, and every post
    # tested before this release) spans the whole text - date/time/venue/fee
    # extraction below is then byte-for-byte the same call it always was.
    scope = text[seg_start:seg_end]

    if context_id is None:
        date, raw, inference = _norm_date(text, published=published_date,
                                          own_dates=own_dates)
    else:
        # Already resolved while segmenting - re-running _norm_date on just
        # this segment's text would find the same date, but the match object
        # (and its raw text) is already in hand from segmentation.
        date, raw, inference = seg_date, None, EXPLICIT_YEAR if seg_date else None
        if seg_date:
            for m in _all_date_matches(scope):
                candidate, _ = _resolve_date_match(m, published_date, own_dates)
                if candidate == seg_date:
                    raw = m.group(0)
                    break
    if date:
        ev.date = date
        ev.evidences.append(Evidence(
            "date", date, raw or date, source_role=source_role,
            inference=inference, context_id=context_id,
        ))
        # "9.18-20"/"9/18-20": a festival naming more days than the single
        # `event_date` column can hold (PHASE 5: `events` has no end-date
        # contract yet). Never expanded into extra events or a guessed end
        # date - flagged the same way an ambiguous multi-program post already
        # is (MULTI_EVENT_CONTEXT), so a human sees the real span rather than
        # a silently-truncated single day.
        range_match = _DAY_RANGE_RE.search(text) or _KOREAN_DAY_LIST_RE.search(text)
        if range_match:
            ev.evidences.append(Evidence(
                "context", "MULTI_DAY_EVENT", range_match.group(0),
                source_role=source_role, inference="DATE_RANGE_START_ONLY",
                context_id=context_id,
            ))
    elif raw:
        # A date was written and we could not place it in a year. Say so, so
        # the missing date reads as a refusal rather than as nothing found.
        ev.evidences.append(Evidence(
            "date", None, raw, source_role=source_role, inference=inference,
            context_id=context_id,
        ))

    reading = extraction_rules.parse_time_range(scope, ev.event_type)
    if reading is None:
        # v0.96.0: a start with no end ("저녁 7시", "8시부터") - see
        # extraction_rules.parse_start_time for what marks a lone clock as a
        # start rather than a deadline.
        reading = extraction_rules.parse_start_time(scope, ev.event_type)
    if reading:
        ev.start_time = reading.start
        ev.end_time = reading.end
        ev.end_day_offset = reading.end_day_offset
        ev.evidences.append(Evidence(
            "time", reading.as_dict(), reading.raw, source_role=source_role,
            inference=reading.meridiem_evidence, context_id=context_id,
        ))

    # A fee condition's own bare hour ("10시 이후") is only ever resolved
    # against a time range the extractor is already certain of (Section 23):
    # an uncertain event time must never turn into a guessed fee condition.
    known_start = known_end = None
    if reading and reading.meridiem_evidence == extraction_rules.EVIDENCE_EXPLICIT \
            and not reading.ambiguous:
        known_start, known_end = reading.start, reading.end

    fee = extraction_rules.extract_fee(
        scope, ev.event_type, known_start=known_start, known_end=known_end,
    )
    if fee:
        ev.fee = fee.amount
        ev.fee_display_text = fee.display
        ev.evidences.append(Evidence(
            "fee", fee.amount, fee.segment, source_role=source_role,
            inference=fee.basis, context_id=context_id,
        ))

    dm = DJ_RE.search(scope)
    if dm:
        ev.dj = dm.group(1)
        ev.evidences.append(Evidence(
            "dj", ev.dj, dm.group(0), source_role=source_role, context_id=context_id,
        ))

    if ambiguous:
        # More than one program, and no single one of them clearly matched
        # what this post was classified as. Whatever was extracted came from
        # the first segment only (never a merge across segments) - this is
        # the signal admin_pages surfaces as a review warning so a person
        # decides which program is meant, rather than the system guessing.
        ev.evidences.append(Evidence(
            "context", "MULTI_EVENT_CONTEXT",
            scope[:160], source_role=source_role, context_id=context_id,
        ))

    # A dated class with a named dance in its title is that class, not every
    # style mentioned in the Community's generic introductory paragraph.
    # Parties/festivals can still name additional styles in their body.
    class_title_genre = (event_type == "CLASS" and re.search(
        r"살사|salsa|바차타|bachata|키좀바|kizomba|발보아|balboa|"
        r"스윙|swing|탱고|땅고|tango", title, re.I
    ))
    genre_body = "" if class_title_genre else body
    for code in sorted(classifier.detect_genre_hints(title, genre_body)):
        ev.evidences.append(Evidence(
            "genre_hint", code, f"{title} {body}"[:160],
            source_role=source_role, inference="SECONDARY_GENRE_WORD",
            context_id=context_id,
        ))

    # A labelled venue is what the post actually says; the known names below
    # are a fallback for posts that name the place without labelling it.
    # Nothing here registers a venue: resolving this string against the Venue
    # Master is a separate, human-supervised step.
    place = extraction_rules.extract_venue(scope)
    if place:
        ev.venue = place.name
        ev.evidences.append(Evidence(
            "venue", {"name": place.name, "alias_candidates": place.alias_candidates},
            place.raw, source_role=source_role, inference=f"LABEL:{place.label}",
            context_id=context_id,
        ))
        return ev

    up = scope.upper()
    if "PISTA" in up:
        ev.venue = "PISTA"
        ev.evidences.append(Evidence(
            "venue", "PISTA", "PISTA", source_role=source_role, context_id=context_id,
        ))
    elif "OCHO" in up:
        ev.venue = "OCHO"
        ev.evidences.append(Evidence(
            "venue", "OCHO", "OCHO", source_role=source_role, context_id=context_id,
        ))
    elif "O NADA" in up or "오나다" in scope:
        ev.venue = "Tango O Nada"
        ev.evidences.append(Evidence(
            "venue", "Tango O Nada", "O Nada/오나다", source_role=source_role,
            context_id=context_id,
        ))
    return ev


# --- schedule posts (v0.96.0) -------------------------------------------
#
# "9월 소셜 일정: 9/5 소셜 / 9/12 파티 / 9/19 정모" - one post, several
# nights. v0.81.2's segmentation already finds every dated program in such a
# post and extract_single() deliberately reads only one of them, flagging
# MULTI_EVENT_CONTEXT for a person. That stays the rule for any post that
# merely *mentions* several dates. A schedule post is narrower: its title
# says it is a schedule/notice, at least two of its segments each name this
# event type's own word beside their own date, and every such date sits in a
# plausible announcement window around the post. Only then does one post
# become one candidate per dated program - each read by extract_single() on
# its own segment, so no value is ever merged across programs.

_SCHEDULE_TITLE_RE = re.compile(r"일정|스케줄|schedule|안내|공지|calendar", re.I)
SCHEDULE_ITEM = "SCHEDULE_ITEM"
SCHEDULE_DAYS_BEFORE = 7
SCHEDULE_DAYS_AHEAD = 70


def _own_day_list_qualifies(title, body, text, matching, expanded, own_dates,
                            event_type, published_date, source_role) -> bool:
    """The three extra tests the date-list route must pass (v0.96.15).

    A title that calls itself a schedule is a statement of intent; a list of
    days is not, so a post that only has the list has to clear more. Each of
    these was measured against the whole stored corpus - see
    `extract_schedule()`'s own comment for the post each one is there for.
    """
    dates = {seg_date for _, _, _, seg_date in matching}
    # 1. every program day is one the post itself wrote with a year.
    if not dates <= set(own_dates or ()):
        return False
    # 2. a course lists its sessions in exactly this shape. The words are
    #    the classifier's own - the same ones sold_as_a_course() reads.
    if classifier._COURSE_EVIDENCE_RE.search(text):
        return False
    # 3. the day this post is already read as has to survive the expansion -
    #    and with what it already said. An expansion that keeps the day but
    #    drops its start time trades a night somebody could turn up to for
    #    one they only know the date of (item 3810, "수원쿠바 라틴댄스 소셜":
    #    its own 9/26 line carries no clock, and the 8:00 PM the post states
    #    once at the top belongs to the whole run, not to that one day).
    current = extract_single(title, body, source_role=source_role,
                             event_type=event_type, published=published_date)
    if current.date not in dates:
        return False
    if current.start_time is None:
        return True
    kept = next(e for e in expanded if e.date == current.date)
    return kept.start_time is not None


def extract_schedule(title: str, body: str, source_role="SECONDARY", event_type=None,
                     published=None):
    """One candidate per dated program of a schedule post, or None when the
    post is not one (single date, programs that do not each name the event,
    or dates outside the announcement window).

    **v0.96.15: a post reaches here two ways, not one.**

    The first is unchanged since v0.96.0 - the post's own title says it is a
    schedule (일정 / 스케줄 / 안내 / 공지 / schedule / calendar).

    The second is the structure that word was always standing in for: **the
    post wrote its own list of days, with years, and then detailed each of
    them.** A holiday run announces itself as "전체일정 2026-09-24,
    2026-09-25, 2026-09-26, 2026-09-27" and then gives each of those days its
    own line, and none of its titles says 일정 - "보니따에서 보내는 추석연휴",
    "BACHATA, SALSA, SOCIAL PARTY", "홍턴 추석 연휴 수~토요일 스페셜
    이벤트!". Eight of the nine listings missing from one day's Production
    results were this shape, every one of them already holding a real event
    on one arbitrary day of its own run.

    That route is deliberately narrower than the title one, because a title
    is a statement of intent and a date list is not:

    * **every program date must be one the post itself wrote with a year.**
      A yearless day resolved from the post's own list (`own_explicit_dates`)
      is the post matching its own prose to its own header; a yearless day
      that is *not* in that list is a mention of something else and stays
      unread. This is what keeps "그리고 다가오는 10월 24일 SNS 4주년
      파티까지" - a forward reference on a single-day post - from becoming an
      October event.
    * **no course evidence anywhere.** A four-week course lists its session
      dates in exactly this shape ("전체일정 2026-09-17,2026-10-01,
      2026-10-08,2026-10-15", "4주 과정 매주 목요일 8시") and must never
      become four nights. Read with the classifier's own
      `_COURSE_EVIDENCE_RE`, the same words `sold_as_a_course()` reads.
    * **the day the post is already read as must survive.** If the expansion
      does not contain the date `extract_single()` gives this post today,
      the post is left exactly as it is rather than trading one real night
      for others: 홍턴's own 9/26 LATIN NIGHT names no 소셜 and no 파티 in
      its own line, so that post keeps its single 9/26 candidate instead of
      being rewritten into 9/23-25.

    A post whose title *does* say schedule is judged exactly as before, with
    none of these three extra tests - v0.96.0's contract is not narrowed.
    """
    from datetime import date as _date, timedelta

    text = f"{title} {body}"
    published_date = _as_date(published)
    by_title = bool(_SCHEDULE_TITLE_RE.search(title or ""))
    # Only a post with no publication date of its own needs (or may use) its
    # own date list to read its own yearless days.
    own_dates = own_explicit_dates(text) if published_date is None else set()
    if not by_title and len(own_dates) < 2:
        return None
    words = extraction_rules.DATED_PROGRAM_WORDS.get((event_type or "").upper())
    if not words:
        return None
    # A schedule lists each program *after* its date ("10/3 토 소셜 20:00 @
    # 스윙홀 / 10/10 ..."), so a program's segment runs from its date to the
    # next one - not to the midpoint _context_segments uses for prose, which
    # would cut "20:00" in half. The title is shared by every segment; only
    # the body's own words say which programs are this event type.
    title_end = len(title or "") + 1
    matches = [m for m in _all_date_matches(text) if m.start() >= title_end]
    if len(matches) < 2:
        return None
    low = high = None
    if published_date is not None:
        low = published_date - timedelta(days=SCHEDULE_DAYS_BEFORE)
        high = published_date + timedelta(days=SCHEDULE_DAYS_AHEAD)
    # v0.96.15: a post can write the same day twice - once in a sentence
    # summarising the week ("9월 27일 일요일에는 월간 무차살사:소셜 파티가
    # 예정되어 있습니다") and once as that day's own block ("☑9월 27일(일)
    # PM9:00~ 월간 무차살사:소셜 ... 🎧DJ 리키"). Taking the first one by
    # position took the summary and threw the hours away, which turned an
    # event that already had a start time into one with none. A day's own
    # block is the one that carries its clock, so that is the one kept;
    # position only breaks a tie. Nothing else about the selection changes -
    # a post that names each day once behaves exactly as it did.
    by_date = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        seg_date, _ = _resolve_date_match(match, published_date, own_dates)
        if not seg_date:
            continue
        own = text[start:end]
        if not re.search(words, own, re.I):
            continue
        if low is not None and not (low <= _date.fromisoformat(seg_date) <= high):
            continue  # a program outside the announcement window is not read
        has_clock = bool(_CLOCK_CUE_RE.search(own))
        kept = by_date.get(seg_date)
        if kept is None or (has_clock and not kept[0]):
            by_date[seg_date] = (has_clock, start, end)
    matching = []
    for seg_date, (_clock, start, end) in sorted(by_date.items(), key=lambda kv: kv[1][1]):
        matching.append((f"sched{len(matching) + 1}", start, end, seg_date))
    if len(matching) < 2:
        return None
    out = []
    for context_id, start, end, seg_date in matching:
        scope = text[max(start, title_end):end]
        ev = extract_single(title, scope, source_role=source_role,
                            name_hint=f"{re.sub(r'\s+', ' ', title).strip()} {seg_date[5:].replace('-', '/')}",
                            event_type=event_type, published=published_date,
                            own_dates=own_dates)
        if ev.date != seg_date:
            return None
        for e in ev.evidences:
            e.context_id = context_id
        ev.evidences.append(Evidence(
            "context", SCHEDULE_ITEM, scope[:160], source_role=source_role, context_id=context_id,
        ))
        out.append(ev)
    if not by_title and not _own_day_list_qualifies(
            title, body, text, matching, out, own_dates, event_type,
            published_date, source_role):
        return None
    return out


# --- the post's own day-list field (v0.96.16) ------------------------------
#
# danceinfo.net publishes one row per (content, date) for every day a listing
# runs: 부에나's 추석 party is idx 27718..27722, one per day of
# 2026-09-23..27, and that site's date page for each of those days carries it.
# The field `acquisition.danceinfo_payload_body()` writes as `전체일정` is that
# day set, and `일정정보` is one schedule string belonging to the whole post -
# the payload carries no per-date schedule at all.
#
# `extract_schedule()` above reads a schedule post as a run of *date
# headings*, each introducing its own program. Applied to this field that is
# the wrong shape, and it fails in a specific, measured way: every day but the
# last gets the segment `"2026-09-25,"`, which names no event and is dropped,
# while the last day's segment swallows the whole `일정정보` + description
# block. So `matching` never reaches two, the post falls through to
# `extract_single()`, and it is filed on the **last** day of its own run -
# 부에나's five-night party stored once, on 9/27.
#
# This is deliberately not the "one shared schedule, therefore every date"
# inference. Measured over the live corpus, that bare shape - two or more
# dates, no per-date prose, one shared schedule - is right **one time in
# seven**: a Barcelona congress, a Geneva festival, a 6주과정 집중반 and a
# 월간 스케줄 roundup all have it too. What makes reading the field safe is not
# the shape but the five conditions below, each of which exists for a post
# that breaks without it.
#
# The route is additive: it runs only where `extract_schedule()` produced
# nothing, so every post that already expands - including the ones carrying no
# source category at all, which condition 1 would refuse - is untouched.

_DAY_TOKEN = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})"
# What may sit between two days of the list, and nothing else: the weekday the
# rendered page prints in brackets, a comma, whitespace. Bounded this tightly
# so the capture stops at the next field label instead of running into it -
# `일` of `일정정보` is a weekday character and a looser class eats it.
_DAY_GAP = r"(?:\s*(?:\([월화수목금토일]\))?\s*,?\s*)"
_DAY_LIST_FIELD = re.compile(
    rf"전체일정\s*({_DAY_TOKEN}{_DAY_GAP}(?:{_DAY_TOKEN}{_DAY_GAP})*)"
)
DAY_LIST_ITEM = "DAY_LIST_ITEM"
DAY_LIST_TIME_AMBIGUOUS = "DAY_LIST_TIME_AMBIGUOUS"

# A day written as part of a span ("9월 25일(금) ~ 27일(일) 정상 영업") has that
# span's words as its own evidence. Used *only* to decide which segment a day
# belongs to - never to invent a day - so it can only ever refuse one.
_PROSE_RANGE = re.compile(
    r"(?P<m1>\d{1,2})\s*월\s*(?P<d1>\d{1,2})\s*일\s*(?:\([^)\n]{1,6}\))?"
    r"\s*[~\-–—]\s*"
    r"(?:(?P<m2>\d{1,2})\s*월\s*)?(?P<d2>\d{1,2})\s*일"
)


def own_day_list(text: str):
    """The days the post's own `전체일정` field lists, and where that field ends.

    ``(frozenset_of_iso_days, end_offset)``, or ``(frozenset(), None)`` when
    the post has no such field. A field written yearless - the rendered-page
    form, `09/23 (수) , 09/25 (금)` - resolves against the single year the post
    states elsewhere, and is refused outright when the post states none or
    states more than one, because then the list names no year at all.
    """
    from datetime import date as _date

    match = _DAY_LIST_FIELD.search(text or "")
    if match is None:
        return frozenset(), None
    tokens = re.findall(_DAY_TOKEN, match.group(1))
    days = {token for token in tokens if len(token) == 10}
    yearless = [token for token in tokens if len(token) != 10]
    if yearless:
        years = {day[:4] for day in days} or {
            day[:4] for day in own_explicit_dates(text)
        }
        if len(years) != 1:
            return frozenset(), None
        year = int(next(iter(years)))
        for token in yearless:
            month, day = token.split("/")
            try:
                days.add(_date(year, int(month), int(day)).isoformat())
            except ValueError:
                return frozenset(), None
    return frozenset(days), match.end(1)


def _span_day(match, month_group, day_group, days, fallback_month=None):
    """One end of a prose span, as a day of the post's own list."""
    month = match.group(month_group) or fallback_month
    if not month:
        return None
    wanted = (int(month), int(match.group(day_group)))
    for day in days:
        parts = day.split("-")
        if (int(parts[1]), int(parts[2])) == wanted:
            return day
    return None


# Between two days of a restated list there is a weekday letter and
# punctuation and nothing else. BABARU writes its run twice - once as the
# field, once as "9/23수 · 9/25금 · 9/26토 BABARU에서 살사 · 바차타와 함께
# 알차게 준비했습니다" - and the sentence that follows the last of them is
# about all three days, not about the 26th.
_LIST_RUN_GAP = re.compile(r"^[\s,./·\-–—()\[\]월화수목금토일]*$")


def _restated_days(text: str, days, matches) -> set:
    """Days the post only writes again as a list, never describes on their own.

    A run of two or more consecutive day mentions with nothing but separators
    between them is the day list restated in prose. None of its members -
    including the last, whose sentence belongs to the whole run - carries
    evidence about one day, so each falls to the shared block instead.
    """
    resolved = [(m, _resolve_date_match(m, None, days)[0]) for m in matches]
    restated: set = set()
    run: list = []
    for index, (match, day) in enumerate(resolved):
        if day is None:
            run = []
            continue
        if run:
            previous_end = resolved[index - 1][0].end()
            if not _LIST_RUN_GAP.match(text[previous_end:match.start()]):
                run = []
        run.append(day)
        if len(run) >= 2:
            restated.update(run)
    return restated


def _prose_segments(text: str, prose_from: int, days, matches):
    """Each listed day mapped to the post's own words about that day.

    A day the post never writes about is absent from the result - it has no
    evidence of its own, and condition 4 has nothing to judge. A day written
    twice keeps the mention carrying a clock, the same tie-break
    `extract_schedule()` already makes and for the same reason.
    """
    segments: dict = {}

    def offer(day, span, has_clock):
        if day not in days:
            return
        kept = segments.get(day)
        if kept is None or (has_clock and not kept[1]):
            segments[day] = (span, has_clock)

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        day, _ = _resolve_date_match(match, None, days)
        if day:
            span = text[start:end]
            offer(day, span, bool(_CLOCK_CUE_RE.search(span)))
    for match in _PROSE_RANGE.finditer(text[prose_from:]):
        start = prose_from + match.start()
        end = min([m.start() for m in matches if m.start() > start] or [len(text)])
        span = text[start:end]
        has_clock = bool(_CLOCK_CUE_RE.search(span))
        first = _span_day(match, "m1", "d1", days)
        last = _span_day(match, "m2", "d2", days, fallback_month=match.group("m1"))
        if first and last and first <= last:
            for day in days:
                if first <= day <= last:
                    offer(day, span, has_clock)
    return segments


def _drop_guessed_morning(ev, source_role):
    """A morning start nothing marked as one is not a night's start time.

    One day's own line can be narrow enough that the only clock beside the
    event's own word has no meridiem - LATIN EVERLATN's 9/27 reads
    "7:00-8:00 p.m.: Bachata 워크샵 ... 9:00-10:00 p.m.: Kizomba 파티" and a
    scope that small resolves the bare 7:00 to 07:00. A 7am party is worse
    than a party whose hours nobody claims to know, so the observation is
    kept as evidence and the time is not published - the same trade
    `extract_with_image_fallback()` already makes for an OCR'd clock
    (IMAGE_TIME_AMBIGUOUS), for the same reason.
    """
    if ev.start_time is None or ev.start_time >= "12:00":
        return
    evidence = next((e for e in ev.evidences if e.field == "time"), None)
    details = evidence.value if evidence else None
    if isinstance(details, dict) and details.get("meridiem_evidence") ==             extraction_rules.EVIDENCE_EXPLICIT:
        return
    ev.evidences.append(Evidence(
        "context", DAY_LIST_TIME_AMBIGUOUS,
        evidence.raw_text if evidence else str(ev.start_time),
        source_role=source_role,
    ))
    ev.start_time = None
    ev.end_time = None
    ev.evidences = [e for e in ev.evidences if e.field != "time"]


def _scope_states(scope: str, day: str, days) -> bool:
    """Does this scope already say which day it is about?"""
    return any(_resolve_date_match(m, None, days)[0] == day
               for m in _all_date_matches(scope))


def extract_day_list(title: str, body: str, source_role="SECONDARY",
                     event_type=None, source_category=None, published=None,
                     current=None, image_texts=None):
    """One candidate per day of the post's own `전체일정` field, or None.

    Called only where `extract_schedule()` returned nothing. ``current`` is the
    single event the post reads as today, images included; condition 5 refuses
    the whole expansion rather than trade any of it away.

    The five conditions, each measured against a post that needs it:

    1. **The source files this as an event.** Without it the same rule adds 65
       candidates over the stored corpus, of which 45 are course sessions -
       nine posts collected before the category was carried, every one a
       weekly 과정 (오스틴 & 카이닝 nine Wednesdays, 스타일링 작품반 eight
       Fridays). danceinfo files those as 강습; the category is the only signal
       that separates them from a night, and - as `classify()` already
       insists - it must never promote on its own either.
    2. **The days come from the post's own field**, not from prose that happens
       to list dates. The label is written by the acquisition layer, so it
       cannot appear by accident.
    3. **No course evidence anywhere** - `_COURSE_EVIDENCE_RE`, the
       classifier's own words. 바차타 기본다지기소셜집중반 is filed
       출빠정보/정모/강습, classifies as a night, lists six Tuesdays and says
       `6주과정`. That word is the only thing between it and six nights.
    4. **A day's own words beat the shared block, and a day whose own words do
       not name the night is not a night.** This is the whole safety argument.
       하바나 lists 2026-09-24 in its field and writes "9월 24일(목) 하루
       쉬어갑니다"; LATIN EVERLATN lists four days and gives two of them
       nothing but "Salsa 워크샵"; 수원쿠바 lists a day whose line is
       "오픈강습". The site's day list is publisher-entered and says nothing
       about what happens on a day - the post's own sentence does.
    5. **Nothing the post already shows is traded away.** The day it reads as
       today must survive, and with its start time. 수원쿠바's own 9/26 line
       carries no clock while the `토요일 8:00 PM` that times it sits in the
       shared block, so expanding that post would swap one night somebody can
       turn up to for three they only know the date of. It is left alone.
    """
    if (source_category or "").upper() != "EVENT":
        return None
    words = extraction_rules.DATED_PROGRAM_WORDS.get((event_type or "").upper())
    if not words:
        return None
    text = f"{title} {body}"
    days, field_end = own_day_list(text)
    if field_end is None or len(days) < 2:
        return None
    if classifier._COURSE_EVIDENCE_RE.search(text):
        return None
    published_date = _as_date(published)
    prose_from = max(field_end, len(title or "") + 1)
    matches = [m for m in _all_date_matches(text) if m.start() >= prose_from]
    segments = _prose_segments(text, prose_from, days, matches)
    for day in _restated_days(text, days, matches):
        segments.pop(day, None)
    # The shared block is what the post says before it starts talking about
    # individual days: its `일정정보`, `장소`, `DJ` and the opening of its
    # description. A day the post never singles out is described by this and
    # by nothing else.
    shared = text[prose_from:min([m.start() for m in matches] or [len(text)])]
    # A day the post never singles out is read from the shared block, so that
    # block has to be a night with hours - the same day-and-a-clock pair
    # `classifier.night_event_bundle()` has required of this source since
    # v0.96.14, and the same event-word test `extract_schedule()` applies to
    # every segment it keeps. Without it a multi-day listing with no per-day
    # prose and no schedule at all expands on its day list alone: DANCE
    # BACHATA CONGRESS (four days in Barcelona, no 일정정보) and
    # BACHATAGENEVA FESTIVAL (five days, none either) are single continuous
    # events that the classifier reads as OTHER today, and neither may become
    # four or five nightly parties if it ever stops doing so.
    shared_is_a_night = bool(re.search(words, shared, re.I)) and         bool(_CLOCK_CUE_RE.search(shared))
    out = []
    for day in sorted(days):
        own = segments.get(day)
        if own is not None and not re.search(words, own[0], re.I):
            continue
        if own is None and not shared_is_a_night:
            continue
        scope = own[0] if own is not None else shared
        # A poster is evidence about the post, so it may fill a day the post
        # describes only through that shared block. A day the post singled out
        # has evidence of its own, and a clock that line left out is the
        # post's own silence about that day - not licence to borrow another
        # day's hours. 수원쿠바's poster is titled 9월 19일 and reads
        # "소셜 PM 8:00 ~ 11:00"; letting it time that post's Tuesday 9/22 is
        # exactly the cross-date mixing v0.81.2 forbids inside one body.
        day_images = None if own is not None else image_texts
        # A schedule segment always opens with the date it is about, and
        # `extract_single()` reads the day off its own scope. The shared block
        # does not - the field it follows is where the days are written, and a
        # day covered by a span ("9월 25일 ~ 27일") is not at the front of it
        # either. Name the day at the head of the scope in exactly those
        # cases, and never where the scope already resolves to it, because a
        # second date in a segment that has one is a second program.
        if not _scope_states(scope, day, days):
            scope = f"{day} {scope}"
        context_id = f"day{len(out) + 1}"
        ev = extract_with_image_fallback(
            title, scope, source_role=source_role,
            name_hint=f"{re.sub(r'\s+', ' ', title or '').strip()} "
                      f"{day[5:].replace('-', '/')}",
            event_type=event_type, published=published_date,
            image_texts=day_images,
            own_dates=set(days) | {day},
        )
        if ev.date != day:
            # The scope resolved to a different day than the one it is there
            # to describe. Nothing here is confident enough to overrule that.
            return None
        _drop_guessed_morning(ev, source_role)
        for evidence in ev.evidences:
            evidence.context_id = context_id
        ev.evidences.append(Evidence(
            "context", DAY_LIST_ITEM, scope[:160],
            source_role=source_role, context_id=context_id,
        ))
        out.append(ev)
    if len(out) < 2:
        return None
    if current is not None:
        kept = next((e for e in out if e.date == current.date), None)
        if kept is None:
            return None
        if current.start_time is not None and kept.start_time is None:
            return None
    return out


# --- image text fallback (v0.81.3) -------------------------------------
#
# A poster image attached to a post often carries the date/time/fee the body
# text never mentions. This module does no fetching or OCR itself - the
# runtime layer already has plain OCR'd, PII-redacted strings by the time
# they reach here - it only decides how they may fill a gap without ever
# overwriting what the body already said, reusing extract_single() itself
# (and therefore v0.81.2's Event Context Safety segmentation) to read each
# image exactly as if it were a second post body.

IMAGE_OCR = "IMAGE_OCR"

# "time" stands for the start_time/end_time pair, which extract_single()
# already reads and records as one Evidence row - splitting it into two
# fallback fields would just produce two evidence rows for the same reading.
#
# v0.84.3: "venue" joins the same fallback set, at the same priority as any
# of the others - a poster is exactly as likely to be the only place a venue
# is named as it is for a date, time or fee. Nothing about resolving that
# string against the Venue Master changes: extract_venue()'s own comment
# above ("resolving this string ... is a separate, human-supervised step")
# applies identically whether the string came from body text or an image.
_FALLBACK_FIELDS = ("date", "time", "venue", "fee")


def _field_value(ev, key: str):
    if key == "date":
        return ev.date
    if key == "time":
        return ev.start_time
    if key == "venue":
        return ev.venue
    return ev.fee


def needs_image_fallback(ev) -> bool:
    """The section-5 gate: only a body missing date, start_time, venue or fee
    is worth the cost of fetching and OCR-ing an image at all."""
    return ev.date is None or ev.start_time is None or ev.venue is None or ev.fee is None


def _image_venue(sub):
    """v0.84.3: a poster's own venue only counts as fallback evidence when
    extract_venue() actually labelled it ("장소: ...") - never the bare
    known-studio-name shortcut (PISTA/OCHO/오나다).

    Found on a real K-TANGO poster: a multi-venue schedule table (~15
    studios across two days) happened to name "오나다" as one of many
    unrelated rows, and the bare-substring fallback picked it out as *the*
    event's venue - paired with a time read off an entirely different row.
    A short, curated post body rarely mentions an unrelated studio in
    passing; a dense OCR'd poster does, so the same shortcut that is safe
    on body text is not safe here. Body-text venue reading is unaffected -
    this only narrows what an *image* is trusted to contribute.
    """
    if sub.venue is None:
        return None
    evidence = next((e for e in sub.evidences if e.field == "venue"), None)
    if evidence is None or not (evidence.inference or "").startswith("LABEL:"):
        return None
    return sub.venue


def _missing_fallback_fields(ev) -> set[str]:
    return {key for key in _FALLBACK_FIELDS if _field_value(ev, key) is None}


def extract_with_image_fallback(title: str, body: str, source_role="SECONDARY",
                                name_hint=None, event_type=None, published=None,
                                image_texts=None, event_terms=None, own_dates=None):
    """extract_single(), then fill date/time/fee gaps from image OCR text.

    ``image_texts`` is a list of ``(image_ref, ocr_text)`` pairs, already
    fetched, OCR'd and PII-redacted by the runtime, in priority order. Each
    image is read as its own self-contained context via extract_single()
    (title unchanged, body=that image's OCR text) - the first image that
    contributes anything to a still-missing field wins outright, and no
    other image is consulted afterwards, so a date read off image 1 can
    never pair with a fee read off image 2 (the same "never combine
    different contexts" rule v0.81.2 applies within one post's own text).

    A field the body already has is never replaced - if an image disagrees
    with it, that is recorded as a MULTI_EVENT_CONTEXT-style conflict
    evidence (IMAGE_EVIDENCE_CONFLICT) instead, and the body's own value
    stands.
    """
    ev = extract_single(title, body, source_role=source_role, name_hint=name_hint,
                        event_type=event_type, published=published, event_terms=event_terms,
                        own_dates=own_dates)
    if not image_texts or not needs_image_fallback(ev):
        return ev

    missing = _missing_fallback_fields(ev)
    for image_ref, image_text in image_texts:
        if not image_text:
            continue
        sub = extract_single(title, image_text, source_role=source_role,
                             event_type=ev.event_type, published=published,
                             event_terms=event_terms)
        time_evidence = next((e for e in sub.evidences if e.field == "time"), None)
        time_details = time_evidence.value if time_evidence else None
        image_time_ambiguous = (sub.start_time is not None and
                                (not isinstance(time_details, dict) or
                                 bool(time_details.get("ambiguous", True))))
        if image_time_ambiguous and "time" in missing:
            # The OCR may have read 9:10 correctly, but without a meridiem
            # it cannot decide 09:10 versus 21:10. Keep the raw observation
            # for human review; never advertise a guessed morning start.
            ev.evidences.append(Evidence(
                "context", "IMAGE_TIME_AMBIGUOUS",
                time_evidence.raw_text if time_evidence else str(sub.start_time),
                evidence_type=IMAGE_OCR, source_role=source_role,
                inference=image_ref,
            ))

        def _sub_value(key):
            if key == "time" and image_time_ambiguous:
                return None
            return _image_venue(sub) if key == "venue" else _field_value(sub, key)

        contributes = {
            key for key in missing
            if _sub_value(key) is not None
        }
        conflicts = [
            (key, _field_value(ev, key), _sub_value(key))
            for key in _FALLBACK_FIELDS
            if key not in missing
            and _field_value(ev, key) is not None
            and _sub_value(key) is not None
            and _field_value(ev, key) != _sub_value(key)
        ]

        if not contributes and not conflicts:
            continue

        for key in contributes:
            if key == "date":
                ev.date = sub.date
                raw = next((e.raw_text for e in sub.evidences if e.field == "date"), sub.date)
                ev.evidences.append(Evidence(
                    "date", sub.date, raw, evidence_type=IMAGE_OCR,
                    source_role=source_role, inference=image_ref,
                ))
            elif key == "time":
                ev.start_time = sub.start_time
                ev.end_time = sub.end_time
                ev.end_day_offset = sub.end_day_offset
                time_evidence = next((e for e in sub.evidences if e.field == "time"), None)
                ev.evidences.append(Evidence(
                    "time",
                    time_evidence.value if time_evidence else
                    {"start": sub.start_time, "end": sub.end_time,
                     "end_day_offset": sub.end_day_offset},
                    time_evidence.raw_text if time_evidence else str(sub.start_time),
                    evidence_type=IMAGE_OCR, source_role=source_role, inference=image_ref,
                ))
            elif key == "venue":
                ev.venue = sub.venue
                venue_evidence = next((e for e in sub.evidences if e.field == "venue"), None)
                ev.evidences.append(Evidence(
                    "venue", venue_evidence.value if venue_evidence else sub.venue,
                    venue_evidence.raw_text if venue_evidence else sub.venue,
                    evidence_type=IMAGE_OCR, source_role=source_role, inference=image_ref,
                ))
            elif key == "fee":
                ev.fee = sub.fee
                ev.fee_display_text = sub.fee_display_text
                raw = next((e.raw_text for e in sub.evidences if e.field == "fee"), str(sub.fee))
                ev.evidences.append(Evidence(
                    "fee", sub.fee, raw, evidence_type=IMAGE_OCR,
                    source_role=source_role, inference=image_ref,
                ))

        for key, body_value, image_value in conflicts:
            ev.evidences.append(Evidence(
                "context", "IMAGE_EVIDENCE_CONFLICT",
                f"{key}: body={body_value!r} image={image_value!r}",
                evidence_type=IMAGE_OCR, source_role=source_role, inference=image_ref,
            ))

        if contributes:
            missing -= contributes
            break  # the first useful image wins; never blend in a second one

    return ev


def extract_ocho_weekly(title: str, body: str, published=None):
    """A week's schedule in one post. Every line is yearless, so every line
    needs the post's own date for the same reason a single event does."""
    out = []
    for part in [p.strip() for p in body.split(";") if p.strip()]:
        dm = re.match(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})\s+(?P<name>.+?)\s+(?P<time>\d{1,2}:\d{2}-\d{1,2}:\d{2})$", part)
        if not dm:
            continue
        ev = extract_single(
            dm.group("name"),
            f"{dm.group('m')}/{dm.group('d')} {dm.group('time')} OCHO",
            source_role="PRIMARY_VENUE",
            name_hint=dm.group("name"),
            published=published,
        )
        out.append(ev)
    return out
