"""Warnings for a human reviewer, derived by comparing extraction to the body.

Deep acquisition found the body, and the v0.73 extractor read more out of it —
dates went from 12/15 to 15/15 and times from 1/15 to 7/15. It also introduced
a failure mode that did not exist when everything was missing: a post reading
``시간: PM 07:30~11:30`` came out as ``07:30``, twelve hours wrong. A time that
is merely absent makes an operator look it up; a time that is wrong sends a
dancer to a locked door.

These hints do not correct anything and do not touch the Information Engine.
They compare what the engine extracted against the text it extracted from and
tell the reviewer where to look. Fixing the extractor is a v0.77 decision made
with this evidence in hand; flagging it is what v0.76 can honestly do today.
"""

from __future__ import annotations

import re
from typing import Any

SEVERITY_WARN = "WARN"
SEVERITY_INFO = "INFO"

# "PM 07:30", "오후 7시 30분", "저녁 7시" — an afternoon/evening marker sitting
# just before a clock time.
_PM_BEFORE_TIME = re.compile(
    r"(PM|pm|오후|저녁|밤)\s*[^\d]{0,4}(\d{1,2})\s*[:시]\s*(\d{0,2})"
)
_FEE_IN_TEXT = re.compile(r"[0-9][0-9,]{2,}\s*원")
_VENUE_LABEL = re.compile(r"(장소|위치)\s*[:：]\s*(\S{2,25})")


def _hour_of(value: Any) -> int | None:
    if not value:
        return None
    match = re.match(r"\s*(\d{1,2})", str(value))
    return int(match.group(1)) if match else None


def afternoon_marked_times(text: str) -> list[int]:
    """Hours the body explicitly marks as afternoon or evening."""
    hours = []
    for marker, hour, _minute in _PM_BEFORE_TIME.findall(text or ""):
        try:
            hours.append(int(hour))
        except ValueError:
            continue
    return hours


def hints(candidate: dict[str, Any], body: str | None) -> list[dict[str, str]]:
    """What a reviewer should check on this candidate. Never modifies anything."""
    found: list[dict[str, str]] = []
    if not body:
        return found

    # --- a morning time where the body says afternoon ------------------------
    marked = set(afternoon_marked_times(body))
    for field, label in (("start_time", "Start"), ("end_time", "End")):
        hour = _hour_of(candidate.get(field))
        if hour is None or hour >= 12:
            continue
        if hour in marked:
            found.append({
                "field": field,
                "severity": SEVERITY_WARN,
                "message": (
                    f"{label} reads {candidate[field]}, but the body marks "
                    f"{hour} o'clock as afternoon/evening. This is probably "
                    f"{hour + 12:02d}:{str(candidate[field])[3:5] or '00'} — "
                    "check the body before approving."
                ),
            })

    # --- a value present in the body that never reached the candidate --------
    if not candidate.get("fee") and _FEE_IN_TEXT.search(body):
        amounts = _FEE_IN_TEXT.findall(body)[:3]
        found.append({
            "field": "fee",
            "severity": SEVERITY_INFO,
            "message": f"the body mentions {', '.join(amounts)} but no fee was extracted",
        })

    if not candidate.get("venue"):
        match = _VENUE_LABEL.search(body)
        if match:
            found.append({
                "field": "venue",
                "severity": SEVERITY_INFO,
                "message": f"the body says {match.group(1)}: {match.group(2)} "
                           "but no venue was extracted",
            })

    return found


def summarise(all_hints: dict[int, list[dict[str, str]]]) -> dict[str, int]:
    """Counts for the review queue and the dashboard."""
    warn = sum(
        1 for hint_list in all_hints.values()
        for hint in hint_list if hint["severity"] == SEVERITY_WARN
    )
    info = sum(
        1 for hint_list in all_hints.values()
        for hint in hint_list if hint["severity"] == SEVERITY_INFO
    )
    return {
        "candidates_with_hints": sum(1 for h in all_hints.values() if h),
        "warnings": warn,
        "suggestions": info,
    }
