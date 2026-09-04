import re
from . import extraction_rules
from .models import EventCandidate, Evidence

DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})"),
    re.compile(r"(?P<y>20\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<y>\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<m>\d{1,2})[./](?P<d>\d{1,2})"),
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


def _norm_date(text: str, default_year=2026):
    for p in DATE_PATTERNS:
        m = p.search(text)
        if m:
            gd = m.groupdict()
            raw_y = gd.get("y")
            if raw_y:
                y = int(raw_y)
                if len(raw_y) == 2:
                    y += 2000
                inference = None
            else:
                y = int(default_year)
                inference = "YEAR_FROM_CONTEXT"
            mo, d = int(gd["m"]), int(gd["d"])
            return f"{y:04d}-{mo:02d}-{d:02d}", m.group(0), inference
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
                   event_type=None):
    """One event read out of one post.

    ``event_type`` is the classifier's verdict. It decides which words the time
    and fee rules look beside: a milonga's fee sits next to 밀롱가, a swing
    social's next to 소셜. Left out, everything behaves as it did before.
    """
    text = f"{title} {body}"
    name = name_hint or re.sub(r"\s+", " ", title).strip()
    ev = EventCandidate(name=name, event_type=event_type or "MILONGA")

    date, raw, inference = _norm_date(text)
    if date:
        ev.date = date
        ev.evidences.append(Evidence("date", date, raw, source_role=source_role, inference=inference))

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


def extract_ocho_weekly(title: str, body: str):
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
        )
        out.append(ev)
    return out
