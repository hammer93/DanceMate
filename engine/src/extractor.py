import re
from .models import EventCandidate, Evidence

DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})"),
    re.compile(r"(?P<y>20\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<y>\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"(?P<m>\d{1,2})[./](?P<d>\d{1,2})"),
]
# Handles: 19:00-23:00, 09:00 pm to 02:00 am, 8:00PM-12:00AM
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


def _norm_time(text: str):
    m = TIME_RE.search(text)
    if not m:
        return None, None, 0, None
    h1, m1 = int(m.group("h1")), int(m.group("m1"))
    h2, m2 = int(m.group("h2")), int(m.group("m2"))
    h1, off1 = _convert_hour(h1, m.group("ap1"))
    h2, off2 = _convert_hour(h2, m.group("ap2"))
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        return None, None, 0, None
    start = f"{h1:02d}:{m1:02d}"
    end = f"{h2:02d}:{m2:02d}"
    offset = off2
    if offset == 0 and (h2, m2) <= (h1, m1):
        offset = 1
    return start, end, offset, m.group(0)


def extract_single(title: str, body: str, source_role="SECONDARY", name_hint=None):
    text = f"{title} {body}"
    name = name_hint or re.sub(r"\s+", " ", title).strip()
    ev = EventCandidate(name=name, event_type="MILONGA")

    date, raw, inference = _norm_date(text)
    if date:
        ev.date = date
        ev.evidences.append(Evidence("date", date, raw, source_role=source_role, inference=inference))

    s, e, offset, rawt = _norm_time(text)
    if s:
        ev.start_time, ev.end_time, ev.end_day_offset = s, e, offset
        ev.evidences.append(Evidence("time", {"start": s, "end": e, "end_day_offset": offset}, rawt, source_role=source_role))

    fm = FEE_RE.search(text)
    if fm:
        fee = int(fm.group(1).replace(",", ""))
        ev.fee = fee
        ev.evidences.append(Evidence("fee", fee, fm.group(0), source_role=source_role))

    dm = DJ_RE.search(text)
    if dm:
        ev.dj = dm.group(1)
        ev.evidences.append(Evidence("dj", ev.dj, dm.group(0), source_role=source_role))

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
