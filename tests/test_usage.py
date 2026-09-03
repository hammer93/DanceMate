"""Provider usage, quota and cost.

Two honesty rules under test:

  * a quota figure always carries where it came from, and
  * cost is never a number unless the pricing was actually verified.

"No invoice has arrived" is not evidence of FREE, and a self-imposed budget is
not the provider's published limit.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from runtime import usage


# --- mapping (pure) ---------------------------------------------------------

def test_each_platform_maps_to_a_provider_api():
    assert usage.api_for("DAUM_CAFE") == ("KAKAO", "daum_cafe_search")
    assert usage.api_for("NAVER_BLOG") == ("NAVER", "search_blog")
    assert usage.api_for("NAVER_CAFE") == ("NAVER", "search_cafearticle")


def test_a_platform_with_no_provider_api_is_not_counted():
    assert usage.api_for("WEB") is None
    assert usage.api_for("FACEBOOK") is None


# --- cost honesty (pure) ----------------------------------------------------

def test_an_unconfigured_provider_costs_nothing_known():
    result = usage.estimated_cost({"request_count": 500}, None)
    assert result["status"] == "NOT_CONFIGURED"
    assert result["amount"] is None, "an unknown price must never render as a number"


def test_unknown_pricing_never_reports_zero():
    """The rule: absence of an invoice is not evidence of FREE."""
    result = usage.estimated_cost({"request_count": 5000}, {"pricing_status": "UNKNOWN"})
    assert result["status"] == "UNKNOWN"
    assert result["amount"] is None
    assert result["amount"] != 0


def test_paid_without_a_rate_is_still_not_a_number():
    result = usage.estimated_cost(
        {"request_count": 100}, {"pricing_status": "PAID", "unit_size": None, "unit_price": None}
    )
    assert result["status"] == "PAID"
    assert result["amount"] is None


def test_free_is_only_reported_when_it_was_declared_free():
    result = usage.estimated_cost({"request_count": 100}, {"pricing_status": "FREE"})
    assert result["status"] == "FREE"
    assert result["amount"] == 0


def test_a_verified_paid_rate_is_calculated_over_the_free_allowance():
    config = {"pricing_status": "PAID", "free_quota": 100, "unit_size": 1000,
              "unit_price": 2.5, "currency": "KRW"}
    result = usage.estimated_cost({"request_count": 2100}, config)
    # 2100 - 100 free = 2000 billable = 2 units of 1000
    assert result["amount"] == pytest.approx(5.0)
    assert result["currency"] == "KRW"


# --- quota provenance (pure) ------------------------------------------------

def test_a_quota_with_no_configuration_is_unknown():
    view = usage.quota_view({"request_count": 12}, None)
    assert view["status"] == "UNKNOWN"
    assert view["limit"] is None
    assert view["used"] == 12


def test_a_quota_carries_where_the_figure_came_from():
    configured = usage.quota_view(
        {"request_count": 12}, {"quota_limit": 5000, "quota_status": "CONFIGURED"}
    )
    assert configured["status"] == "CONFIGURED"
    assert configured["remaining"] == 4988

    documented = usage.quota_view(
        {"request_count": 3}, {"quota_limit": 25000, "quota_status": "DOCUMENTED"}
    )
    assert documented["status"] == "DOCUMENTED"


def test_remaining_never_goes_negative():
    view = usage.quota_view({"request_count": 6000}, {"quota_limit": 5000,
                                                     "quota_status": "CONFIGURED"})
    assert view["remaining"] == 0


# --- database-backed --------------------------------------------------------

TODAY = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)


def test_the_seeded_pricing_never_claims_free(pg):
    config = usage.pricing(pg)
    assert config, "migration 006 should have seeded the providers"
    for (provider, api), row in config.items():
        assert row["pricing_status"] != "FREE", (
            f"{provider}/{api} must not be recorded as FREE without verification"
        )


def test_kakao_budget_is_configured_not_documented(pg):
    """5000/day is our own budget, not a published Kakao limit."""
    config = usage.pricing(pg)
    assert config[("KAKAO", "daum_cafe_search")]["quota_status"] == "CONFIGURED"


def test_naver_quota_is_documented(pg):
    """25,000/day comes from Naver's published Search API documentation."""
    config = usage.pricing(pg)
    assert config[("NAVER", "search_blog")]["quota_status"] == "DOCUMENTED"
    assert config[("NAVER", "search_blog")]["quota_limit"] == 25000


def test_requests_are_counted_per_provider_api(pg):
    before = {
        (r["provider"], r["api_name"]): r["request_count"]
        for r in usage.daily(pg, on=TODAY.date())
    }
    usage.record_api_requests(pg, "DAUM_CAFE", requests=6, success=6, items=17,
                              new_items=17, status="PASS", now=TODAY)
    after = {
        (r["provider"], r["api_name"]): r for r in usage.daily(pg, on=TODAY.date())
    }
    row = after[("KAKAO", "daum_cafe_search")]
    assert row["request_count"] == before.get(("KAKAO", "daum_cafe_search"), 0) + 6
    assert row["success_count"] >= 6
    assert row["item_count"] >= 17
    assert row["new_item_count"] >= 17


def test_errors_and_auth_failures_are_counted_separately(pg):
    usage.record_api_requests(pg, "NAVER_BLOG", requests=3, errors=3, auth_errors=3,
                              status="AUTH_FAILED", now=TODAY)
    row = next(r for r in usage.daily(pg, on=TODAY.date())
               if (r["provider"], r["api_name"]) == ("NAVER", "search_blog"))
    assert row["error_count"] >= 3
    assert row["auth_error_count"] >= 3
    assert row["success_count"] == 0
    assert row["last_status"] == "AUTH_FAILED"


def test_rate_limits_are_counted(pg):
    usage.record_api_requests(pg, "DAUM_CAFE", requests=1, errors=1, rate_limited=1,
                              status="RATE_LIMITED", now=TODAY)
    row = next(r for r in usage.daily(pg, on=TODAY.date())
               if r["api_name"] == "daum_cafe_search")
    assert row["rate_limit_count"] >= 1


def test_duplicates_are_counted_apart_from_new_items(pg):
    usage.record_api_requests(pg, "DAUM_CAFE", requests=6, success=6, items=17,
                              new_items=0, duplicate_items=17, status="PASS", now=TODAY)
    row = next(r for r in usage.daily(pg, on=TODAY.date())
               if r["api_name"] == "daum_cafe_search")
    assert row["duplicate_item_count"] >= 17


def test_providers_are_kept_apart(pg):
    usage.record_api_requests(pg, "DAUM_CAFE", requests=5, success=5, now=TODAY)
    usage.record_api_requests(pg, "NAVER_BLOG", requests=2, errors=2, now=TODAY)
    rows = {(r["provider"], r["api_name"]): r for r in usage.daily(pg, on=TODAY.date())}
    assert rows[("KAKAO", "daum_cafe_search")]["success_count"] >= 5
    assert rows[("NAVER", "search_blog")]["error_count"] >= 2


def test_usage_is_aggregated_per_day(pg):
    other_day = TODAY + timedelta(days=1)
    usage.record_api_requests(pg, "DAUM_CAFE", requests=4, now=TODAY)
    usage.record_api_requests(pg, "DAUM_CAFE", requests=7, now=other_day)
    today_row = next(r for r in usage.daily(pg, on=TODAY.date())
                     if r["api_name"] == "daum_cafe_search")
    other_row = next(r for r in usage.daily(pg, on=other_day.date())
                     if r["api_name"] == "daum_cafe_search")
    assert today_row["request_count"] >= 4
    assert other_row["request_count"] == 7


def test_an_untouched_provider_still_appears_with_zero(pg):
    """"We did not call Naver today" is information worth showing."""
    rows = {(r["provider"], r["api_name"]) for r in usage.daily(pg, on=date(2030, 1, 1))}
    assert ("NAVER", "search_blog") in rows
    assert ("KAKAO", "daum_cafe_search") in rows


def test_month_to_date_sums_the_month(pg):
    usage.record_api_requests(pg, "DAUM_CAFE", requests=3, items=5, new_items=5, now=TODAY)
    usage.record_api_requests(pg, "DAUM_CAFE", requests=4, items=6, new_items=2,
                              now=TODAY + timedelta(days=2))
    mtd = usage.month_to_date(pg, on=(TODAY + timedelta(days=2)).date())
    kakao = next(r for r in mtd["by_provider"] if r["provider"] == "KAKAO")
    assert int(kakao["requests"]) >= 7
    assert mtd["totals"]["requests"] >= 7
    assert mtd["from"] == TODAY.date().replace(day=1)


def test_content_fetches_are_not_provider_api_requests(pg):
    """Fetching an original post costs no Kakao or Naver quota."""
    fetches = usage.content_fetches(pg)
    assert set(fetches) >= {"total", "succeeded", "chars", "by_host"}
    api_rows = usage.daily(pg)
    assert all("host" not in row for row in api_rows), (
        "content fetches must not appear in the provider API table"
    )


def test_efficiency_reports_ratios_not_scores(pg):
    result = usage.efficiency(pg, on=TODAY.date())
    assert set(result) == {"api_requests", "new_items", "items_collected",
                           "new_items_per_request"}


def test_efficiency_divides_by_zero_safely(pg):
    result = usage.efficiency(pg, on=date(2030, 1, 2))
    assert result["api_requests"] == 0
    assert result["new_items_per_request"] is None


def test_snapshot_carries_everything_the_page_needs(pg):
    # Settings built after the pg fixture restored the real credentials:
    # snapshot() opens its own connection.
    from runtime.config import load_settings

    snapshot = usage.snapshot(load_settings())
    assert snapshot["available"] is True
    assert set(snapshot) >= {"today", "month_to_date", "content_fetches", "efficiency"}
