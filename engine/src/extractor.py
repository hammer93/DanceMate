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


def _resolve_date_match(m: "re.Match", published):
    """One date pattern match, resolved to (date_iso_or_None, provenance).

    Isolated from `_norm_date` so the same per-match resolution can run on
    every date match a multi-program post carries (`_context_segments`), not
    only the first one `_norm_date` itself stops at.
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
    return (resolved.isoformat() if resolved else None), provenance


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
        resolved, provenance = _resolve_date_match(m, published)
        return resolved, m.group(0), provenance
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
    return found


def _context_segments(text: str, published):
    """(context_id, start, end, date_iso) for each program the text names.

    One entry, `context_id=None` spanning the whole text, when there is only
    one date value in the post (or none) - which is "no segmentation", the
    behaviour every post had before this. Two or more distinct dates create
    one segment per date, split at the midpoint between consecutive date
    matches so text naming a program *before* its own date heading (the
    common "장소: OOO 일시: 9/5" order) still lands in that program's segment.
    """
    resolved = []
    for m in _all_date_matches(text):
        date_iso, _ = _resolve_date_match(m, published)
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

    segments = []
    for i, (m, date_iso) in enumerate(boundaries):
        start = 0 if i == 0 else (boundaries[i - 1][0].end() + m.start()) // 2
        end = (len(text) if i + 1 == len(boundaries)
               else (m.end() + boundaries[i + 1][0].start()) // 2)
        segments.append((f"ctx{i + 1}", max(0, start), min(len(text), end), date_iso))
    return segments


def _select_context(segments, text: str, event_type: str | None):
    """Which segment is the announced event, and whether that was ambiguous.

    A segment "is" the event when its own span names this event_type's word
    (밀롱가/소셜/파티/...) - the same word classify() used to call the whole
    post this event_type in the first place. Exactly one segment matching is
    unambiguous. Zero or more than one means the post does not clearly say
    which program the classification was about; the caller falls back to the
    first segment (never invents a merged value) and is told to flag it.
    """
    if len(segments) == 1:
        return segments[0], False
    words = extraction_rules.EVENT_WORDS.get((event_type or "").upper())
    if not words:
        return segments[0], True
    matching = [s for s in segments if re.search(words, text[s[1]:s[2]], re.I)]
    if len(matching) == 1:
        return matching[0], False
    return segments[0], True


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

    published_date = _as_date(published)
    segments = _context_segments(text, published_date)
    (context_id, seg_start, seg_end, seg_date), ambiguous = _select_context(
        segments, text, ev.event_type
    )
    # Single segment (the overwhelming majority of posts, and every post
    # tested before this release) spans the whole text - date/time/venue/fee
    # extraction below is then byte-for-byte the same call it always was.
    scope = text[seg_start:seg_end]

    if context_id is None:
        date, raw, inference = _norm_date(text, published=published_date)
    else:
        # Already resolved while segmenting - re-running _norm_date on just
        # this segment's text would find the same date, but the match object
        # (and its raw text) is already in hand from segmentation.
        date, raw, inference = seg_date, None, EXPLICIT_YEAR if seg_date else None
        if seg_date:
            for m in _all_date_matches(scope):
                candidate, _ = _resolve_date_match(m, published_date)
                if candidate == seg_date:
                    raw = m.group(0)
                    break
    if date:
        ev.date = date
        ev.evidences.append(Evidence(
            "date", date, raw or date, source_role=source_role,
            inference=inference, context_id=context_id,
        ))
    elif raw:
        # A date was written and we could not place it in a year. Say so, so
        # the missing date reads as a refusal rather than as nothing found.
        ev.evidences.append(Evidence(
            "date", None, raw, source_role=source_role, inference=inference,
            context_id=context_id,
        ))

    reading = extraction_rules.parse_time_range(scope, ev.event_type)
    if reading:
        ev.start_time = reading.start
        ev.end_time = reading.end
        ev.end_day_offset = reading.end_day_offset
        ev.evidences.append(Evidence(
            "time", reading.as_dict(), reading.raw, source_role=source_role,
            inference=reading.meridiem_evidence, context_id=context_id,
        ))

    fee = extraction_rules.extract_fee(scope, ev.event_type)
    if fee:
        ev.fee = fee.amount
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
_FALLBACK_FIELDS = ("date", "time", "fee")


def _field_value(ev, key: str):
    if key == "date":
        return ev.date
    if key == "time":
        return ev.start_time
    return ev.fee


def needs_image_fallback(ev) -> bool:
    """The section-5 gate: only a body missing date, start_time or fee is
    worth the cost of fetching and OCR-ing an image at all."""
    return ev.date is None or ev.start_time is None or ev.fee is None


def _missing_fallback_fields(ev) -> set[str]:
    return {key for key in _FALLBACK_FIELDS if _field_value(ev, key) is None}


def extract_with_image_fallback(title: str, body: str, source_role="SECONDARY",
                                name_hint=None, event_type=None, published=None,
                                image_texts=None):
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
                        event_type=event_type, published=published)
    if not image_texts or not needs_image_fallback(ev):
        return ev

    missing = _missing_fallback_fields(ev)
    for image_ref, image_text in image_texts:
        if not image_text:
            continue
        sub = extract_single(title, image_text, source_role=source_role,
                             event_type=ev.event_type, published=published)

        contributes = {
            key for key in missing
            if _field_value(sub, key) is not None
        }
        conflicts = [
            (key, _field_value(ev, key), _field_value(sub, key))
            for key in _FALLBACK_FIELDS
            if key not in missing
            and _field_value(ev, key) is not None
            and _field_value(sub, key) is not None
            and _field_value(ev, key) != _field_value(sub, key)
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
            elif key == "fee":
                ev.fee = sub.fee
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
