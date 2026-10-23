"""The database side of an operations check, as one JSON line (v0.96.51).

``scripts/ops-monitor.sh`` runs this inside the runtime container
(``python -m runtime.ops_facts``) and hands the result to
``runtime.ops_alerts`` on the host. Read-only: one connection, marked read
only, rolled back. What it reads is what `/status` does not say - how many
times in a row each scheduled job has failed, and whether extraction or
normalization is stuck - because a job that fails every tick still leaves the
scheduler's heartbeat fresh.

It never runs a job, never starts a scheduler and never writes.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import config, content_store, db

#: How far back a job's streak is counted. A job failing for longer than this
#: is reported at this many - "at least" is all an alert needs.
STREAK_WINDOW = 50


def job_streaks(con) -> dict[str, int]:
    """Per job name: how many of its newest runs in a row did not PASS."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT job_name, status FROM ("
            "  SELECT job_name, status, row_number() OVER (PARTITION BY job_name "
            "    ORDER BY started_at DESC) AS rn FROM job_runs"
            ") ranked WHERE rn <= %s ORDER BY job_name, rn", (STREAK_WINDOW,))
        rows = cur.fetchall()
    streaks: dict[str, int] = {}
    broken: set[str] = set()
    for job, status in rows:
        streaks.setdefault(job, 0)
        if job in broken:
            continue
        if (status or "").upper() == "PASS":
            broken.add(job)
        else:
            streaks[job] += 1
    return streaks


def collect(settings) -> dict[str, Any]:
    from . import normalization  # noqa: PLC0415 - heavier import, only when asked

    with db.connect(settings) as con:
        con.read_only = True
        try:
            facts = {
                "job_failure_streaks": job_streaks(con),
                "reextract": content_store.reprocess_backlog(con, settings.engine_version),
            }
            backlog = normalization.backlog(settings, con=con)
            facts["normalization"] = {"pending": backlog.get("pending"),
                                      "failed": backlog.get("failed")}
        finally:
            con.rollback()
    return facts


def main() -> int:
    try:
        facts = collect(config.load_settings())
    except Exception as exc:                 # noqa: BLE001 - reported, not raised
        print(json.dumps({"error": type(exc).__name__}))
        return 1
    print(json.dumps(facts, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
