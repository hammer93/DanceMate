"""Per-provider daily request accounting.

Naver documents a 25,000 calls/day limit on its Search APIs (recorded in the
engine's own settings.json), and Kakao applies its own quota. A scheduler that
only looks at each source's interval has no idea how many calls it has already
spent across every source sharing one key, so this counts them per provider per
UTC day and refuses once the budget is gone.

Deliberately small: one row per provider per day in runtime_state, no separate
table, no token bucket, no background timer. The goal is "do not burn the day's
quota by accident", not a rate-limiting framework.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from . import db
from .config import Settings

STATE_PREFIX = "quota."

# Provider budgets. Conservative: a fraction of the documented ceiling, so a
# misconfigured interval cannot spend the whole day's allowance before anyone
# notices. Raise deliberately once real usage is understood.
DAILY_BUDGET = {
    "KAKAO": 5000,
    "NAVER": 5000,
}

PROVIDER_BY_PLATFORM = {
    "DAUM_CAFE": "KAKAO",
    "NAVER_CAFE": "NAVER",
    "NAVER_BLOG": "NAVER",
}


class QuotaExceeded(RuntimeError):
    """The provider's budget for today is spent."""


def provider_for(platform: str) -> str | None:
    return PROVIDER_BY_PLATFORM.get(platform)


def budget_for(provider: str) -> int:
    return DAILY_BUDGET.get(provider, 0)


def _key(provider: str, day: date) -> str:
    return f"{STATE_PREFIX}{provider}.{day.isoformat()}"


def _read(con, provider: str, day: date) -> dict[str, Any]:
    with con.cursor() as cur:
        cur.execute(
            "SELECT state_value FROM runtime_state WHERE state_key = %s",
            (_key(provider, day),),
        )
        row = cur.fetchone()
    if row is None:
        return {"provider": provider, "day": day.isoformat(), "requests": 0,
                "last_request_at": None, "last_error": None}
    return json.loads(row[0])


def _write(con, provider: str, day: date, state: dict[str, Any]) -> None:
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO runtime_state (state_key, state_value, updated_at) "
            "VALUES (%s, %s, now()) "
            "ON CONFLICT (state_key) DO UPDATE "
            "SET state_value = EXCLUDED.state_value, updated_at = now()",
            (_key(provider, day), json.dumps(state, ensure_ascii=False)),
        )


def usage(con, provider: str, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    state = _read(con, provider, now.date())
    budget = budget_for(provider)
    state["budget"] = budget
    state["remaining"] = max(0, budget - int(state.get("requests", 0)))
    return state


def check(con, platform: str, *, cost: int = 1, now: datetime | None = None) -> None:
    """Raise QuotaExceeded if this platform has no budget left today."""
    provider = provider_for(platform)
    if provider is None:
        return
    current = usage(con, provider, now=now)
    if current["remaining"] < cost:
        raise QuotaExceeded(
            f"{provider} daily budget spent: "
            f"{current['requests']}/{current['budget']} requests used today"
        )


def record(
    con, platform: str, *, requests: int = 1, error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Account for requests actually issued to a provider."""
    provider = provider_for(platform)
    if provider is None:
        return {}
    now = now or datetime.now(timezone.utc)
    state = _read(con, provider, now.date())
    state["requests"] = int(state.get("requests", 0)) + max(0, requests)
    state["last_request_at"] = now.isoformat()
    if error is not None:
        state["last_error"] = error[:300]
    _write(con, provider, now.date(), state)
    return usage(con, provider, now=now)


def expected_request_count(source: dict[str, Any]) -> int:
    """How many upstream calls collecting this source will cost.

    The Daum collector issues one search per query; the Naver collector does the
    same. A source with six queries costs six calls, not one - which is exactly
    the arithmetic a naive interval check misses.
    """
    queries = source.get("queries") or []
    if isinstance(queries, str):
        queries = json.loads(queries)
    return max(1, len(queries))


def snapshot(settings: Settings) -> dict[str, Any]:
    """Quota state for the admin dashboard. Never raises."""
    try:
        with db.connect(settings, autocommit=True) as con:
            return {
                provider: usage(con, provider)
                for provider in sorted(DAILY_BUDGET)
            }
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc)}
