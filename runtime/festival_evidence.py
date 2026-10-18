"""Whether a structured tango-calendar record is a festival (v0.96.41).

TangoNOW's share pages and Miltang's notices publish festivals, marathons and
tango weeks beside their milongas, as the same schema.org `Event` record. The
engine read every one of them as nothing: the record names no night word and
states no clock, so the classifier answered OTHER and no candidate was ever
made. Measured on the live pages (2026-10-19): 12 of TangoNOW's 40 share pages
state a date and no clock, and every one of Miltang's 16 notices states a
`startDate` and an `endDate` - TangoNOW states no `endDate` on any of them.

What a record has to say for the collector to call it a festival, all of it in
the record's own structure and its own name:

* **a date and no clock of its own.** A festival is not one night, and a page
  that gives one start time is describing a night; that is v0.96.35's
  question, not this one.
* **a name announcing a festival format** - festival, marathon, tango week,
  weekend, encuentro. Not the source's word for it: neither source carries a
  category, and `@type: Event` is true of a milonga too.
* **a name announcing no other format.** A refusal list, for the notices that
  are a teacher couple's workshop tour, a seminar and show, or a screening:
  `Chicho Frumboli & Juana Sepulveda Tango Seminar & Show` is one of the 16.

The period is passed on only when the record states its end itself, after its
start and within `MAX_PERIOD_DAYS`. A record with a start date and no end is
a festival that starts that day and nothing more is claimed about it.

Returns the judgement keys a collector puts in its record, or None. Never a
reading of the body: the engine still reads the date and the place from the
record's own text, and decides what to do with the judgement.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

#: What the engine is told the record is. The only value it accepts.
FESTIVAL = "FESTIVAL"

#: Longer than any festival either source lists (the longest live notice is a
#: 14-day workshop tour, the longest festival 9 days), shorter than a season.
MAX_PERIOD_DAYS = 31

_FESTIVAL_NAME_RE = re.compile(
    r"페스티벌|페스티발|축제|마라톤|탱고\s*위크|땅고\s*위크|엔쿠엔트로|위켄드"
    r"|\bfestival\b|\bfestivals\b|\bmarathon\b|\btango\s+week\b|\bencuentro\b"
    r"|\bweekend\b",
    re.I)

_NOT_A_FESTIVAL_RE = re.compile(
    r"워크숍|워크샵|세미나|강습|수업|클래스|클라스|레슨|공연|콘서트|무비|영화|상영"
    r"|대회|선발전|모집|후기|취소|연기"
    r"|\bworkshops?\b|\bseminars?\b|\bclass(?:es)?\b|\blessons?\b|\bshow\b"
    r"|\bconcert\b|\bmovie\b|\bscreening\b|\bcompetition\b|\bchampionship\b"
    r"|\bcancel+ed\b|\bpostponed\b",
    re.I)

_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _iso_date(value: Any) -> date | None:
    match = _ISO_DATE_RE.match(str(value or "").strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def names_a_festival(name: Any) -> bool:
    """Whether a record's own name announces a festival and nothing else."""
    text = str(name or "")
    return bool(_FESTIVAL_NAME_RE.search(text)) and not _NOT_A_FESTIVAL_RE.search(text)


def judgement(name: Any, start: Any, end: Any = None, *,
              states_a_clock: bool, source: str) -> dict[str, Any] | None:
    """The judgement keys for one record, or None when it is not a festival.

    ``start``/``end`` are the record's own structured dates (ISO, a clock
    allowed after the date), ``states_a_clock`` whether the record gives a
    time of its own anywhere, and ``source`` the provider's name for the
    provenance sentence.
    """
    if states_a_clock or not names_a_festival(name):
        return None
    first = _iso_date(start)
    if first is None:
        return None
    last = _iso_date(end)
    if last is not None and not 0 < (last - first).days <= MAX_PERIOD_DAYS:
        last = None
    period = {"start": first.isoformat()}
    if last is not None:
        period["end"] = last.isoformat()
    span = f"{first.isoformat()}~{last.isoformat()}" if last else f"from {first.isoformat()}"
    return {
        "source_event_format": FESTIVAL,
        "event_period": period,
        "festival_evidence": (f"{source}: a dated record ({span}) with no clock "
                              f"of its own, named as a festival"),
    }
