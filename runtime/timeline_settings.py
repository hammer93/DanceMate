"""Admin-configurable visibility for the Timeline's "?" confirmation indicator.

v0.86.4 (Section 16-21, 72-75): the indicator reuses the Information Engine's
existing status vocabulary (POSSIBLE/EXPECTED/CONFLICT/UNKNOWN) rather than a
new confidence score - none exists anywhere in the codebase to reuse instead.
VERIFIED is not a column here at all: Section 73 explicitly discourages ever
letting VERIFIED show "?", so there is no way to configure it back on.
CANCELLED/COMPLETED are handled by existing UI (the cancellation banner, the
"종료" badge) before this is ever consulted, so they are not columns either.

A single row (id=1): this is one site-wide toggle, not per-source or
per-genre configuration - no new settings-storage mechanism existed anywhere
in the codebase to reuse (investigated first, per Section 21), so this is
deliberately the smallest table that could support the required enum-based
checklist rather than a generic key-value settings store nothing else needs
yet.
"""

from __future__ import annotations

from typing import Any

# The only statuses an admin can toggle. Order matches the checklist the
# Admin Settings page renders.
CONFIGURABLE_STATUSES = ("POSSIBLE", "EXPECTED", "CONFLICT", "UNKNOWN")

_COLUMN_BY_STATUS = {
    "POSSIBLE": "show_for_possible",
    "EXPECTED": "show_for_expected",
    "CONFLICT": "show_for_conflict",
    "UNKNOWN": "show_for_unknown",
}


def get_settings(con) -> dict[str, Any]:
    """`{"enabled": bool, "statuses": set[str]}` - one query, no per-event
    lookup (Section 107-112: callers fetch this once per request and thread
    it through, never inside a per-event render function)."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT enabled, show_for_possible, show_for_expected, "
            "       show_for_conflict, show_for_unknown "
            "FROM timeline_confirmation_settings WHERE id = 1"
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover - the seed row always exists
        return {"enabled": True, "statuses": set(CONFIGURABLE_STATUSES)}
    enabled, possible, expected, conflict, unknown = row
    flags = {"POSSIBLE": possible, "EXPECTED": expected,
             "CONFLICT": conflict, "UNKNOWN": unknown}
    return {"enabled": bool(enabled),
            "statuses": {code for code in CONFIGURABLE_STATUSES if flags[code]}}


def set_settings(con, *, enabled: bool, statuses: set[str]) -> None:
    """Persists the admin's choice. `statuses` outside CONFIGURABLE_STATUSES
    is silently ignored - there is no column for VERIFIED to switch off, so
    nothing but the four real toggles can ever be written."""
    with con.cursor() as cur:
        cur.execute(
            "UPDATE timeline_confirmation_settings SET "
            "  enabled = %s, show_for_possible = %s, show_for_expected = %s, "
            "  show_for_conflict = %s, show_for_unknown = %s, updated_at = now() "
            "WHERE id = 1",
            (
                enabled,
                "POSSIBLE" in statuses,
                "EXPECTED" in statuses,
                "CONFLICT" in statuses,
                "UNKNOWN" in statuses,
            ),
        )
