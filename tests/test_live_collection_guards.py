"""Guards around live collection: provenance, error classification, quota.

The rule these exist to defend: **the scheduler must never store recorded
snapshot data as though it had been collected.** An earlier version fell back
to the engine's fixtures whenever credentials were absent, which filled
source_items with offline sample data indistinguishable from real intake. That
is the difference between "we have no live source yet" and "we appear to have
one", and only the first is true today.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime import collector_errors, collectors, quota
from scheduler import intake_job


def _source(**overrides):
    payload = {
        "source_id": 1,
        "source_key": "SRC-D-001",
        "name": "Test board",
        "platform": "DAUM_CAFE",
        "source_role": "PROMOTION_BOARD",
        "authority_level": "SECONDARY",
        "enabled": True,
        "url": None,
        "queries": ["밀롱가", "서울 밀롱가"],
        "config": {},
    }
    payload.update(overrides)
    return payload


# --- the scheduler never silently substitutes snapshot data -----------------

def test_without_credentials_the_scheduler_refuses_to_collect(monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    mode, reason = intake_job.choose_mode(_source())
    assert mode is None, "a credential-less source must not be collected at all"
    assert "KAKAO_REST_API_KEY" in reason
    assert "Refusing to store snapshot data" in reason


def test_with_credentials_the_scheduler_collects_live(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-key")
    mode, reason = intake_job.choose_mode(_source())
    assert mode == collectors.MODE_LIVE
    assert "live" in reason


def test_snapshot_intake_is_opt_in_per_source(monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    opted_in = _source(config={"snapshot_intake_allowed": True})
    mode, reason = intake_job.choose_mode(opted_in)
    assert mode == collectors.MODE_SNAPSHOT
    assert "NOT live data" in reason


def test_snapshot_opt_in_is_off_by_default():
    assert intake_job.snapshot_intake_allowed(_source()) is False
    assert intake_job.snapshot_intake_allowed(_source(config={})) is False
    assert intake_job.snapshot_intake_allowed(
        _source(config='{"snapshot_intake_allowed": true}')
    ) is True


def test_an_unsupported_platform_is_not_collected(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-key")
    mode, reason = intake_job.choose_mode(_source(platform="FACEBOOK"))
    assert mode is None
    assert "no collector" in reason


def test_snapshot_runs_are_labelled_so_no_count_can_be_mistaken():
    """A snapshot run reports SNAPSHOT, never PASS."""
    assert intake_job.STATUS_SNAPSHOT == "SNAPSHOT"
    assert intake_job.STATUS_PASS != intake_job.STATUS_SNAPSHOT


# --- error classification ---------------------------------------------------

@pytest.mark.parametrize(
    "message,expected",
    [
        ("Naver HTTP 401: Unauthorized", collector_errors.AUTH_FAILED),
        ("Naver HTTP 403: Forbidden", collector_errors.AUTH_FAILED),
        ("Naver HTTP 429: Too Many Requests", collector_errors.RATE_LIMITED),
        ("Naver HTTP 500: Internal Server Error", collector_errors.NETWORK),
        ("Naver HTTP 503: Service Unavailable", collector_errors.NETWORK),
        ("Naver network error: [Errno -3] Temporary failure", collector_errors.NETWORK),
        ("Daum Cafe search failed for query='x': timed out", collector_errors.NETWORK),
        ("KAKAO_REST_API_KEY is not set", collector_errors.CREDENTIALS_MISSING),
    ],
)
def test_collector_failures_are_classified_for_the_operator(message, expected):
    assert collector_errors.classify(message).kind == expected


def test_a_malformed_body_is_a_bad_response():
    error = ValueError("Expecting value: line 1 column 1 (char 0)")
    assert collector_errors.classify(error).kind == collector_errors.BAD_RESPONSE


def test_a_timeout_object_is_a_network_failure():
    assert collector_errors.classify(TimeoutError("timed out")).kind == collector_errors.NETWORK


def test_rate_limits_and_outages_are_retryable_but_a_bad_key_is_not():
    assert collector_errors.classify("HTTP 429: slow down").retryable is True
    assert collector_errors.classify("HTTP 503: down").retryable is True
    assert collector_errors.classify("HTTP 401: Unauthorized").retryable is False
    assert collector_errors.classify("KAKAO_REST_API_KEY is not set").retryable is False


def test_the_http_status_is_reported_alongside_the_kind():
    classified = collector_errors.classify("Naver HTTP 429: Too Many Requests")
    assert classified.status_code == 429
    assert "429" in classified.summary()
    assert "throttling" in classified.advice


@pytest.mark.parametrize(
    "message",
    [
        "Authorization: KakaoAK EXAMPLE-NOT-A-REAL-KEY",
        "X-Naver-Client-Secret: EXAMPLE-NOT-A-REAL-SECRET",
        "api_key=EXAMPLE-NOT-A-REAL-KEY",
        "client_secret: EXAMPLE-NOT-A-REAL-SECRET2",
    ],
)
def test_credentials_never_survive_into_a_stored_message(message):
    """A failure message must not smuggle the key into source_errors or the UI."""
    redacted = collector_errors.redact(message)
    assert "<redacted>" in redacted
    for secret in ("EXAMPLE-NOT-A-REAL-KEY", "EXAMPLE-NOT-A-REAL-SECRET", "EXAMPLE-NOT-A-REAL-SECRET2"):
        assert secret not in redacted


def test_classification_redacts_too():
    classified = collector_errors.classify("failed with KakaoAK EXAMPLE-NOT-A-REAL-KEY")
    assert "EXAMPLE-NOT-A-REAL-KEY" not in classified.detail


# --- quota accounting -------------------------------------------------------

def test_platforms_map_onto_their_provider():
    assert quota.provider_for("DAUM_CAFE") == "KAKAO"
    assert quota.provider_for("NAVER_BLOG") == "NAVER"
    assert quota.provider_for("NAVER_CAFE") == "NAVER"
    assert quota.provider_for("FACEBOOK") is None


def test_a_multi_query_source_costs_one_call_per_query():
    """The arithmetic a naive interval check misses."""
    assert quota.expected_request_count(_source()) == 2
    assert quota.expected_request_count(_source(queries=["a", "b", "c", "d", "e", "f"])) == 6
    assert quota.expected_request_count(_source(queries=[])) == 1
    assert quota.expected_request_count(_source(queries='["a","b"]')) == 2


def test_both_naver_platforms_share_one_budget():
    """One credential, one quota - counting them separately would overspend."""
    assert quota.provider_for("NAVER_BLOG") == quota.provider_for("NAVER_CAFE")


def test_quota_starts_empty_and_counts_up(pg):
    provider = "KAKAO"
    before = quota.usage(pg, provider)
    quota.record(pg, "DAUM_CAFE", requests=3)
    after = quota.usage(pg, provider)
    assert after["requests"] == before["requests"] + 3
    assert after["remaining"] == after["budget"] - after["requests"]
    assert after["last_request_at"] is not None


def test_quota_check_passes_while_budget_remains(pg):
    quota.check(pg, "DAUM_CAFE", cost=1)


def test_quota_check_refuses_once_the_budget_is_spent(pg):
    quota.record(pg, "DAUM_CAFE", requests=quota.budget_for("KAKAO"))
    with pytest.raises(quota.QuotaExceeded, match="daily budget spent"):
        quota.check(pg, "DAUM_CAFE", cost=1)


def test_quota_is_per_day(pg):
    today = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    tomorrow = today + timedelta(days=1)
    quota.record(pg, "DAUM_CAFE", requests=10, now=today)
    assert quota.usage(pg, "KAKAO", now=today)["requests"] == 10
    assert quota.usage(pg, "KAKAO", now=tomorrow)["requests"] == 0


def test_an_unmetered_platform_is_never_blocked(pg):
    quota.check(pg, "FACEBOOK", cost=10_000)
    assert quota.record(pg, "FACEBOOK", requests=10) == {}


def test_a_failed_request_still_costs_quota(pg):
    """The provider counted the call whether or not it answered usefully."""
    before = quota.usage(pg, "NAVER")["requests"]
    quota.record(pg, "NAVER_BLOG", requests=2, error=collector_errors.RATE_LIMITED)
    after = quota.usage(pg, "NAVER")
    assert after["requests"] == before + 2
    assert after["last_error"] == collector_errors.RATE_LIMITED


# --- intake provenance ------------------------------------------------------

def test_summary_separates_live_items_from_snapshot_items(pg):
    from runtime import intake

    summary = intake.summary(pg)
    for key in ("live_items", "snapshot_items", "live_runs", "source_items"):
        assert key in summary, key
    assert summary["live_items"] + summary["snapshot_items"] <= summary["source_items"]


def test_a_snapshot_test_never_reports_a_plain_pass(engine_settings, monkeypatch):
    """"PASS" beside a snapshot run would read as "the credential works"."""
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    report = collectors.test_source(engine_settings, _source())
    assert report["mode"] == collectors.MODE_SNAPSHOT
    assert report["status"] == "PASS_SNAPSHOT"
    assert report["missing_credentials"] == ["KAKAO_REST_API_KEY"]


def test_the_admin_test_button_spells_out_that_snapshot_is_not_live():
    from pathlib import Path

    admin = (Path(__file__).resolve().parents[1] / "runtime" / "admin.py").read_text(
        encoding="utf-8"
    )
    assert "SNAPSHOT, NOT LIVE" in admin
    assert "the scheduler will skip this source" in admin


# --- diagnosing an empty live result ----------------------------------------

def test_an_empty_live_result_is_diagnosed_not_reported_as_a_plain_pass(monkeypatch, settings):
    """The confusing case: credential fine, provider answered, filter matched 0.

    Reporting that as PASS sends an operator hunting for a credential problem
    that does not exist. Found on the board: the engine's shipped config carries
    url_contains ["6uP", "5HTC"], and since the filter requires EVERY token in
    the same URL - and "6uP" is a stale cafe id that no longer appears - it
    could never match anything.
    """
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-key")

    empty = collectors.CollectionResult(mode=collectors.MODE_LIVE, items=[], detail="live: 0")
    monkeypatch.setattr(collectors, "collect", lambda *a, **k: empty)
    monkeypatch.setattr(
        collectors, "_diagnose_empty_live",
        lambda *a, **k: {
            "provider_results": 30,
            "matched_by_filter": 0,
            "diagnosis": "filter matched 0 of 30",
        },
    )
    report = collectors.test_source(settings, _source())
    assert report["status"] == "PASS_NO_MATCH"
    assert report["provider_results"] == 30
    assert report["matched_by_filter"] == 0


def test_a_genuinely_empty_provider_result_is_not_a_filter_problem(monkeypatch, settings):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-key")
    empty = collectors.CollectionResult(mode=collectors.MODE_LIVE, items=[], detail="live: 0")
    monkeypatch.setattr(collectors, "collect", lambda *a, **k: empty)
    monkeypatch.setattr(
        collectors, "_diagnose_empty_live",
        lambda *a, **k: {"provider_results": 0, "diagnosis": "no result for the query"},
    )
    report = collectors.test_source(settings, _source())
    assert report["status"] == "PASS", "an empty upstream is not a misconfiguration"


def test_multi_token_url_filters_need_every_token_in_one_url():
    """The engine's semantics, pinned so the seed comment cannot drift from it."""
    import sys

    from runtime.config import REPO_ROOT

    sys.path.insert(0, str(REPO_ROOT / "engine"))
    from src.collectors.daum import _matches_source  # noqa: PLC0415

    document = {"url": "https://cafe.daum.net/latindance/5HTC/22276",
                "cafename": "라틴속으로 - 탱고 -"}
    source_all_present = {"cafe_name_hint": "라틴속으로", "url_contains": ["latindance", "5HTC"]}
    source_stale_token = {"cafe_name_hint": "라틴속으로", "url_contains": ["6uP", "5HTC"]}

    assert _matches_source(document, source_all_present) is True
    assert _matches_source(document, source_stale_token) is False, (
        "a token that cannot appear makes the whole filter unsatisfiable"
    )


def test_the_test_button_classifies_a_failure_the_same_way_the_scheduler_does(
    monkeypatch, settings
):
    """Observed on the board: [Test] said "NaverCollectorError: Naver HTTP 401"
    while the Sources list said AUTH_FAILED. One vocabulary, not two."""
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")

    def boom(*args, **kwargs):
        raise RuntimeError("Naver HTTP 401: Unauthorized")

    monkeypatch.setattr(collectors, "collect", boom)
    report = collectors.test_source(settings, _source(platform="NAVER_BLOG"))
    assert report["status"] == collector_errors.AUTH_FAILED
    assert report["http_status"] == 401
    assert report["retryable"] is False
    assert "check the key" in report["detail"]


def test_a_rate_limited_test_is_reported_as_retryable(monkeypatch, settings):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "key")

    def boom(*args, **kwargs):
        raise RuntimeError("Daum HTTP 429: Too Many Requests")

    monkeypatch.setattr(collectors, "collect", boom)
    report = collectors.test_source(settings, _source())
    assert report["status"] == collector_errors.RATE_LIMITED
    assert report["retryable"] is True
