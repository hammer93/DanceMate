import re
from . import extraction_rules
from .models import EventCandidate, Evidence

DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})"),
    re.compile(r"(?P<y>20\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<y>\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    # Bounded on both sides, or it reads a date out of the middle of a longer
    # number. "2010.12" -- a recording date in a post about a tango camp --
    # matched as 10.12 and became an event this October.
    re.compile(r"(?<!\d)(?P<m>\d{1,2})[./](?P<d>\d{1,2})(?!\d)"),
]
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
DJ_RE = re.compile(r"DJ\s*[:.]?\s*([A-Za-z가-힣._]+)", re.I)


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


def _norm_date(text: str, published=None, default_year=None):
    """The event's date, and where its year came from.

    ``published`` is the date the post was written. Without it a bare 9/25
    cannot be resolved, and this returns nothing rather than attaching the
    current year -- which is how a post from 2024 became an event this week.

    ``default_year`` is accepted only so older callers keep working; when it is
    given it stands in for the post's date, as those callers intended.
    """
    from datetime import date as _date

    published = _as_date(published)
    if published is None and default_year:
        published = _date(int(default_year), 7, 1)  # mid-year: no month bias

    for p in DATE_PATTERNS:
        m = p.search(text)
        if not m:
            continue
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
                return None, m.group(0), UNKNOWN_YEAR
            return f"{y:04d}-{mo:02d}-{d:02d}", m.group(0), EXPLICIT_YEAR
        resolved, provenance = _yearless_date(mo, d, published)
        if resolved is None:
            return None, m.group(0), provenance
        return resolved.isoformat(), m.group(0), provenance
    return None, None, None


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
                   event_type=None, published=None):
    """One event read out of one post.

    ``event_type`` is the classifier's verdict. It decides which words the time
    and fee rules look beside: a milonga's fee sits next to 밀롱가, a swing
    social's next to 소셜. Left out, everything behaves as it did before.

    ``published`` is when the post was written. A post says "9/25" and means
    the 25th of September near the time it was writing; without knowing when
    that was, the day cannot be placed in a year and no date is claimed.
    """
    text = f"{title} {body}"
    name = name_hint or re.sub(r"\s+", " ", title).strip()
    ev = EventCandidate(name=name, event_type=event_type or "MILONGA")

    date, raw, inference = _norm_date(text, published=_as_date(published))
    if date:
        ev.date = date
        ev.evidences.append(Evidence("date", date, raw, source_role=source_role, inference=inference))
    elif raw:
        # A date was written and we could not place it in a year. Say so, so
        # the missing date reads as a refusal rather than as nothing found.
        ev.evidences.append(
            Evidence("date", None, raw, source_role=source_role, inference=inference))

    reading = extraction_rules.parse_time_range(text, ev.event_type)
    if reading:
        ev.start_time = reading.start
        ev.end_time = reading.end
        ev.end_day_offset = reading.end_day_offset
        ev.evidences.append(Evidence(
            "time", reading.as_dict(), reading.raw, source_role=source_role,
            inference=reading.meridiem_evidence,
        ))

    fee = extraction_rules.extract_fee(text, ev.event_type)
    if fee:
        ev.fee = fee.amount
        ev.evidences.append(Evidence(
            "fee", fee.amount, fee.segment, source_role=source_role, inference=fee.basis,
        ))

    dm = DJ_RE.search(text)
    if dm:
        ev.dj = dm.group(1)
        ev.evidences.append(Evidence("dj", ev.dj, dm.group(0), source_role=source_role))

    # A labelled venue is what the post actually says; the known names below
    # are a fallback for posts that name the place without labelling it.
    # Nothing here registers a venue: resolving this string against the Venue
    # Master is a separate, human-supervised step.
    place = extraction_rules.extract_venue(text)
    if place:
        ev.venue = place.name
        ev.evidences.append(Evidence(
            "venue", {"name": place.name, "alias_candidates": place.alias_candidates},
            place.raw, source_role=source_role, inference=f"LABEL:{place.label}",
        ))
        return ev

    up = text.upper()
    if "PISTA" in up:
        ev.venue = "PISTA"
        ev.evidences.append(Evidence("venue", "PISTA", "PISTA", source_role=source_role))
    elif "OCHO" in up:
        ev.venue = "OCHO"
        ev.evidences.append(Evidence("venue", "OCHO", "OCHO", source_role=source_role))
    elif "O NADA" in up or "오나다" in text:
        ev.venue = "Tango O Nada"
        ev.evidences.append(Evidence("venue", "Tango O Nada", "O Nada/오나다", source_role=source_role))
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
