"""Provider usage, quota and cost.

Answers one operator question: *how many times did we call an external API
today, and what did those calls actually get us?*

Two counters that must never be added together:

    API requests    calls to a provider's search API (Kakao, Naver) - quota
    content fetches HTTP GETs of an original post - no provider quota at all

Two honesty rules, both enforced here rather than left to the UI:

    A quota figure carries where it came from. Our own 5000/day budget is
    CONFIGURED, Naver's 25,000/day is DOCUMENTED, and anything else is UNKNOWN.
    None of them is presented as "the provider's real limit".

    Cost is never rendered as a number unless the pricing was verified.
    "No invoice has arrived" is not evidence of FREE, so an unverified provider
    reports UNKNOWN, not 0.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from . import db
from .config import Settings

# Which API name each platform's requests are counted against. One credential
# and one allowance is shared by both Naver search APIs, but the calls
# themselves are worth telling apart.
API_BY_PLATFORM = {
    "DAUM_CAFE": ("KAKAO", "daum_cafe_search"),
    "NAVER_BLOG": ("NAVER", "search_blog"),
    "NAVER_CAFE": ("NAVER", "search_cafearticle"),
}

PROVIDERS = ("KAKAO", "NAVER")

COST_UNKNOWN = "UNKNOWN"
QUOTA_UNKNOWN = "UNKNOWN"


def _rows(cur) -> list[dict[str, Any]]:
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _row(cur) -> dict[str, Any] | None:
    columns = [c.name for c in cur.description]
    row = cur.fetchone()
    return None if row is None else dict(zip(columns, row))


def api_for(platform: str) -> tuple[str, str] | None:
    return API_BY_PLATFORM.get(platform)


def record_api_requests(
    con, platform: str, *, requests: int = 1, success: int = 0, errors: int = 0,
    rate_limited: int = 0, auth_errors: int = 0, items: int = 0, new_items: int = 0,
    duplicate_items: int = 0, status: str | None = None, now: datetime | None = None,
) -> dict[str, Any] | None:
    """Add one collection's worth of API activity to today's aggregate.

    Aggregated per day rather than a row per request: a row per call would be a
    write amplifier on a 32GB microSD for a resolution nobody reads. The
    per-run detail already lives in source_collection_runs.
    """
    mapping = api_for(platform)
    if mapping is None:
        return None
    provider, api_name = mapping
    now = now or datetime.now(timezone.utc)

    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO provider_usage_daily (usage_date, provider, api_name, "
            "  request_count, success_count, error_count, rate_limit_count, "
            "  auth_error_count, item_count, new_item_count, duplicate_item_count, "
            "  last_status, last_request_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (usage_date, provider, api_name) DO UPDATE SET "
            "  request_count = provider_usage_daily.request_count + EXCLUDED.request_count, "
            "  success_count = provider_usage_daily.success_count + EXCLUDED.success_count, "
            "  error_count = provider_usage_daily.error_count + EXCLUDED.error_count, "
            "  rate_limit_count = provider_usage_daily.rate_limit_count + EXCLUDED.rate_limit_count, "
            "  auth_error_count = provider_usage_daily.auth_error_count + EXCLUDED.auth_error_count, "
            "  item_count = provider_usage_daily.item_count + EXCLUDED.item_count, "
            "  new_item_count = provider_usage_daily.new_item_count + EXCLUDED.new_item_count, "
            "  duplicate_item_count = provider_usage_daily.duplicate_item_count "
            "                         + EXCLUDED.duplicate_item_count, "
            "  last_status = EXCLUDED.last_status, "
            "  last_request_at = EXCLUDED.last_request_at, updated_at = now() "
            "RETURNING *",
            (now.date(), provider, api_name, requests, success, errors, rate_limited,
             auth_errors, items, new_items, duplicate_items, status, now),
        )
        return _row(cur)


def pricing(con) -> dict[tuple[str, str], dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute("SELECT * FROM provider_pricing_config")
        return {(r["provider"], r["api_name"]): r for r in _rows(cur)}


def estimated_cost(usage_row: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    """Cost for one day's usage of one API.

    Returns UNKNOWN unless the pricing was actually verified. A provider that
    merely has not billed us is not FREE.
    """
    if config is None:
        return {"status": "NOT_CONFIGURED", "amount": None, "currency": None}

    status = config.get("pricing_status") or COST_UNKNOWN
    if status == "FREE":
        return {"status": "FREE", "amount": 0, "currency": config.get("currency")}
    if status != "PAID":
        return {"status": status, "amount": None, "currency": config.get("currency")}

    unit_size = config.get("unit_size") or 0
    unit_price = config.get("unit_price")
    if not unit_size or unit_price is None:
        # PAID but we do not know the rate: still not a number we may show.
        return {"status": "PAID", "amount": None, "currency": config.get("currency")}

    billable = max(0, int(usage_row.get("request_count", 0)) - int(config.get("free_quota") or 0))
    units = -(-billable // unit_size)  # ceil
    return {
        "status": "PAID",
        "amount": float(unit_price) * units,
        "currency": config.get("currency"),
    }


def quota_view(usage_row: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    """The quota figure alongside where it came from."""
    if config is None or config.get("quota_limit") is None:
        return {"limit": None, "status": QUOTA_UNKNOWN, "used": usage_row.get("request_count", 0),
                "remaining": None, "source_url": None}
    limit = int(config["quota_limit"])
    used = int(usage_row.get("request_count", 0))
    return {
        "limit": limit,
        "status": config.get("quota_status") or QUOTA_UNKNOWN,
        "used": used,
        "remaining": max(0, limit - used),
        "source_url": config.get("quota_source_url"),
    }


def daily(con, *, on: date | None = None) -> list[dict[str, Any]]:
    """Per-API usage for one day, with quota and cost status attached."""
    on = on or datetime.now(timezone.utc).date()
    config = pricing(con)
    with con.cursor() as cur:
        cur.execute(
            "SELECT * FROM provider_usage_daily WHERE usage_date = %s "
            "ORDER BY provider, api_name",
            (on,),
        )
        rows = _rows(cur)

    # Show every configured API, including ones with no traffic today: "we did
    # not call Naver" is information.
    seen = {(r["provider"], r["api_name"]) for r in rows}
    for (provider, api_name), _ in config.items():
        if (provider, api_name) not in seen:
            rows.append({
                "usage_date": on, "provider": provider, "api_name": api_name,
                "request_count": 0, "success_count": 0, "error_count": 0,
                "rate_limit_count": 0, "auth_error_count": 0, "item_count": 0,
                "new_item_count": 0, "duplicate_item_count": 0,
                "last_status": None, "last_request_at": None,
            })

    for row in rows:
        key = (row["provider"], row["api_name"])
        row["quota"] = quota_view(row, config.get(key))
        row["cost"] = estimated_cost(row, config.get(key))
    return sorted(rows, key=lambda r: (r["provider"], r["api_name"]))


def month_to_date(con, *, on: date | None = None) -> dict[str, Any]:
    on = on or datetime.now(timezone.utc).date()
    start = on.replace(day=1)
    with con.cursor() as cur:
        cur.execute(
            "SELECT provider, sum(request_count) requests, sum(success_count) success, "
            "       sum(error_count) errors, sum(item_count) items, "
            "       sum(new_item_count) new_items, sum(duplicate_item_count) duplicates "
            "FROM provider_usage_daily WHERE usage_date >= %s AND usage_date <= %s "
            "GROUP BY provider ORDER BY provider",
            (start, on),
        )
        by_provider = _rows(cur)
    totals = {
        "requests": sum(int(r["requests"] or 0) for r in by_provider),
        "items": sum(int(r["items"] or 0) for r in by_provider),
        "new_items": sum(int(r["new_items"] or 0) for r in by_provider),
    }
    return {"from": start, "to": on, "by_provider": by_provider, "totals": totals}


def content_fetches(con, *, on: date | None = None) -> dict[str, Any]:
    """Original-post fetches. Counted apart from provider API requests."""
    on = on or datetime.now(timezone.utc).date()
    with con.cursor() as cur:
        cur.execute(
            "SELECT count(*) total, "
            "  count(*) FILTER (WHERE outcome LIKE 'FETCHED%%') succeeded, "
            "  coalesce(sum(text_length), 0) chars, "
            "  coalesce(avg(duration_ms), 0)::int avg_ms "
            "FROM content_fetch_log WHERE fetched_at::date = %s",
            (on,),
        )
        row = _row(cur)
        cur.execute(
            "SELECT host, count(*) fetches FROM content_fetch_log "
            "WHERE fetched_at::date = %s GROUP BY host ORDER BY 2 DESC",
            (on,),
        )
        row["by_host"] = _rows(cur)
    return row


def efficiency(con, *, on: date | None = None) -> dict[str, Any]:
    """What each API request actually bought.

    Ratios only, no scoring: the point is to notice when calls stop producing
    anything, not to rank sources.
    """
    on = on or datetime.now(timezone.utc).date()
    with con.cursor() as cur:
        cur.execute(
            "SELECT coalesce(sum(request_count), 0), coalesce(sum(new_item_count), 0) "
            "FROM provider_usage_daily WHERE usage_date = %s",
            (on,),
        )
        requests, new_items = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM source_items WHERE collected_at::date = %s", (on,)
        )
        items_today = cur.fetchone()[0]

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 3) if denominator else None

    return {
        "api_requests": int(requests),
        "new_items": int(new_items),
        "items_collected": int(items_today),
        "new_items_per_request": ratio(int(new_items), int(requests)),
    }


def snapshot(settings: Settings) -> dict[str, Any]:
    """Everything the usage page needs. Never raises."""
    try:
        with db.connect(settings, autocommit=True) as con:
            return {
                "available": True,
                "today": daily(con),
                "month_to_date": month_to_date(con),
                "content_fetches": content_fetches(con),
                "efficiency": efficiency(con),
            }
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "detail": str(exc)}
