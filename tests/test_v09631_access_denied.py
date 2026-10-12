"""v0.96.31: a refusal is not an unclassified failure, and 403 is not 401.

TangoNOW's Firestore answered `403` from 2026-09-25 onward - its public read
rule had been withdrawn - and the collector said so in plain words:

    TangoNOW Firestore returned 403 for https://firestore.../events?... -
    public read rules may have changed

`collector_errors.status_code()` looked for `\\bHTTP[ :]?(\\d{3})\\b`, found
no "HTTP" in that sentence, and reported no status at all. So a permanent
refusal classified as `UNKNOWN`, which is in `RETRYABLE`, and the scheduler
asked again 133 times in three weeks while the Sources page showed nothing
wrong.

Two fixes, and the first is the one that matters: the raiser now attaches the
status as a number, so a collector that knows it got a 403 is never re-read
out of prose. The message path is widened as a fallback, because an upstream
we do not control will phrase it however it likes.

And 403 gets its own kind. "Check the key in .env" is the wrong instruction
for a public endpoint that has no key, and acting on it wastes the one person
who could notice the real thing.
"""

from __future__ import annotations

import urllib.error

import pytest

from runtime import collector_errors as ce


# --- the status, structurally ----------------------------------------------

def test_an_httperror_carries_its_own_status():
    error = urllib.error.HTTPError("https://x", 403, "Forbidden", {}, None)
    classified = ce.classify(error)
    assert classified.status_code == 403
    assert classified.kind == ce.ACCESS_DENIED


def test_a_discovery_error_may_attach_the_status():
    class DiscoveryError(RuntimeError):
        pass

    error = DiscoveryError("the provider said no")
    error.status_code = 403
    assert ce.classify(error).kind == ce.ACCESS_DENIED


def test_the_structured_status_wins_over_the_sentence():
    """A message mentioning another number must not overrule the truth."""
    class DiscoveryError(RuntimeError):
        pass

    error = DiscoveryError("HTTP 500 while retrying")
    error.status_code = 403
    assert ce.classify(error).status_code == 403


# --- the status, from the message ------------------------------------------

@pytest.mark.parametrize("message,expected", [
    ("TangoNOW Firestore returned 403 for https://x - public read rules may "
     "have changed", 403),
    ("HTTP 403: Forbidden", 403),
    ("HTTP: 403", 403),
    ("HTTP Error 500: Internal Server Error", 500),
    ("status 403", 403),
    ("status_code=403", 403),
    ("responded with 429", 429),
    ("code: 401", 401),
    ("Naver HTTP 401: Unauthorized", 401),
])
def test_a_stated_status_is_read(message, expected):
    assert ce.status_code(message) == expected


@pytest.mark.parametrize("message", [
    "장소: 이데알 탱고 까페 (부산시 부산진구 신천대로 62번길 403 3층)",
    "collected 404 records from the board",
    "miltang.com/milongas has no readable day header - list page shape changed",
    "",
])
def test_a_bare_number_is_not_a_status(message):
    """A venue's street number and a record count are not HTTP statuses."""
    assert ce.status_code(message) is None


def test_an_impossible_status_is_not_a_status():
    assert ce.status_code("returned 999") is None


# --- what each one means ---------------------------------------------------

@pytest.mark.parametrize("message,kind,retryable", [
    ("TangoNOW Firestore returned 403 for https://x", ce.ACCESS_DENIED, False),
    ("Naver HTTP 401: Unauthorized", ce.AUTH_FAILED, False),
    ("HTTP 429 Too Many Requests", ce.RATE_LIMITED, True),
    ("HTTP Error 500: Internal Server Error", ce.NETWORK, True),
    ("Naver API HUB network error: timed out", ce.NETWORK, True),
    ("no live collection: KAKAO_REST_API_KEY not set", ce.CREDENTIALS_MISSING, False),
    ("has no readable day header - list page shape changed", ce.UNKNOWN, True),
])
def test_each_failure_gets_its_own_kind(message, kind, retryable):
    classified = ce.classify(message)
    assert classified.kind == kind
    assert classified.retryable is retryable


def test_a_refusal_is_never_retryable():
    assert ce.ACCESS_DENIED not in ce.RETRYABLE
    assert ce.AUTH_FAILED not in ce.RETRYABLE


def test_a_rate_limit_is_not_a_refusal():
    """429 reopens on its own; 403 does not. Treating them alike either
    hammers a throttled provider or gives up on a temporary one."""
    assert ce.classify("HTTP 429").kind == ce.RATE_LIMITED
    assert ce.classify("HTTP 429").retryable is True


def test_403_advice_does_not_send_an_operator_after_a_key():
    advice = ce.classify("returned 403").advice
    assert "credential" not in advice.lower() or "no credential" in advice.lower()
    assert "public access" in advice


def test_a_malformed_body_is_still_a_bad_response():
    assert ce.classify(ValueError("Expecting value: line 1 column 1")).kind == \
        ce.BAD_RESPONSE


def test_a_secret_is_never_echoed_back():
    classified = ce.classify("HTTP 403 for X-Naver-Client-Secret: abcdef123456")
    assert "abcdef123456" not in classified.detail


# --- the collector that raises it ------------------------------------------

def test_tangonow_attaches_the_status_it_got():
    from runtime import tangonow_discovery as tn

    class _Opener:
        def __call__(self, request, timeout=None):      # noqa: ARG002
            raise urllib.error.HTTPError(
                "https://firestore.googleapis.com/v1/x", 403, "Forbidden", {}, None)

    with pytest.raises(tn.DiscoveryError) as caught:
        tn._fetch_json("https://firestore.googleapis.com/v1/x", timeout=5,
                       opener=_Opener())
    assert getattr(caught.value, "status_code", None) == 403
    assert ce.classify(caught.value).kind == ce.ACCESS_DENIED
    assert ce.classify(caught.value).retryable is False


# --- and the scheduler stops asking ---------------------------------------

def test_a_refused_source_is_rechecked_slowly_not_every_tick():
    from datetime import datetime, timedelta, timezone

    from runtime import sources

    refused = {
        "enabled": True,
        "collection_interval_minutes": 60,
        "last_status": ce.ACCESS_DENIED,
        "last_collected_at": datetime.now(timezone.utc) - timedelta(hours=2),
    }
    assert sources.is_due(refused) is False, \
        "two hours after a 403 is not the moment to ask again"
    refused["last_collected_at"] = (
        datetime.now(timezone.utc)
        - timedelta(minutes=sources.REFUSED_RECHECK_MINUTES + 1))
    assert sources.is_due(refused) is True, \
        "a withdrawn rule can be restored; the check must not stop forever"


def test_a_working_source_keeps_its_own_interval():
    from datetime import datetime, timedelta, timezone

    from runtime import sources

    healthy = {
        "enabled": True,
        "collection_interval_minutes": 60,
        "last_status": "PASS",
        "last_collected_at": datetime.now(timezone.utc) - timedelta(hours=2),
    }
    assert sources.is_due(healthy) is True
