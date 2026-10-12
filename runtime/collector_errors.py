"""Classify what a live collector failure actually was.

The Information Engine's collectors raise a single error type per provider with
the HTTP status in the message. That is fine for the engine, but an operator
looking at the Sources page needs to tell "my key is wrong" from "I am being
rate limited" from "the network blipped" - the three call for completely
different responses, and only one of them is worth retrying soon.

Nothing here parses provider payloads; it reads the status the collector
already reported. No secret is ever included in a classified message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Operator-facing kinds, recorded in source_errors.kind and sources.last_status.
AUTH_FAILED = "AUTH_FAILED"
# v0.96.31: 403 is not 401. A credential being rejected and a public endpoint
# refusing anonymous reads call for opposite responses - one is "check the key
# in .env", the other is "this source has closed its public access and no key
# of ours can fix it". TangoNOW's Firestore answered 403 for 133 consecutive
# runs while being reported as an unclassified, retryable failure.
ACCESS_DENIED = "ACCESS_DENIED"
# The collector read part of its window and not the rest - recorded against
# the source so a partial window is never mistaken for a whole one.
PARTIAL_COLLECTION = "PARTIAL_COLLECTION"
RATE_LIMITED = "RATE_LIMITED"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
NETWORK = "NETWORK"
BAD_RESPONSE = "BAD_RESPONSE"
CREDENTIALS_MISSING = "CREDENTIALS_MISSING"
UNKNOWN = "UNKNOWN"

# Whether it is worth the scheduler trying again on its next tick.
# ACCESS_DENIED and AUTH_FAILED are deliberately absent: retrying a refusal on
# the next tick changes nothing and buries the real state. Reopening is an
# operator decision, or a slow re-check - see `sources.is_due()`.
RETRYABLE = frozenset({RATE_LIMITED, NETWORK, BAD_RESPONSE, UNKNOWN})

# v0.96.31: the lead-ins a collector actually writes. Until this release only
# "HTTP 403"/"HTTP: 403" was recognised, so `TangoNOW Firestore returned 403
# for ...` carried its status in plain sight and was read as no status at all -
# which is how a withdrawn public-read rule became "UNKNOWN: unclassified
# collector failure", retried every tick for three weeks. Deliberately a
# closed list of lead-ins rather than any bare three digits: a venue address
# ("월드컵북로6길 403") or a record count must never read as an HTTP status.
_HTTP_STATUS = re.compile(
    r"\b(?:HTTP(?:\s+Error)?|returned|responded(?:\s+with)?|status(?:_code)?|code)"
    r"\s*[:=]?\s*(\d{3})\b",
    re.IGNORECASE,
)

_ADVICE = {
    AUTH_FAILED: "the provider rejected the credential - check the key in .env",
    ACCESS_DENIED: "the provider refuses this request - its public access may "
                   "have been withdrawn, and no credential of ours changes that",
    PARTIAL_COLLECTION: "only part of this source's window could be read",
    RATE_LIMITED: "the provider is throttling - the interval may be too short",
    QUOTA_EXCEEDED: "the provider's quota for this window is spent",
    NETWORK: "the provider could not be reached",
    BAD_RESPONSE: "the provider answered with something unparseable",
    CREDENTIALS_MISSING: "no credential is configured for this platform",
    UNKNOWN: "unclassified collector failure",
}


@dataclass(frozen=True)
class Classified:
    kind: str
    status_code: int | None
    detail: str
    retryable: bool

    @property
    def advice(self) -> str:
        return _ADVICE.get(self.kind, _ADVICE[UNKNOWN])

    def summary(self) -> str:
        code = f" (HTTP {self.status_code})" if self.status_code else ""
        return f"{self.kind}{code}: {self.advice}"


def status_code(message: str) -> int | None:
    """The HTTP status a collector's message states, or None.

    Only a recognised lead-in counts, and only a status a server can
    actually send - so "returned 403" is a status and a three-digit house
    number is not.
    """
    for match in _HTTP_STATUS.finditer(message or ""):
        code = int(match.group(1))
        if 100 <= code <= 599:
            return code
    return None


def _structured_status(error: BaseException | str) -> int | None:
    """A status the raiser attached to the exception itself.

    Preferred over reading it back out of prose: the collector knew the
    number. `urllib.error.HTTPError` already carries `.code`, and our own
    discovery errors may carry `.status_code` (v0.96.31).
    """
    for attr in ("status_code", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    return None


def classify(error: BaseException | str) -> Classified:
    """Map a collector failure onto an operator-facing kind."""
    message = str(error)
    name = type(error).__name__ if isinstance(error, BaseException) else ""
    code = _structured_status(error) or status_code(message)
    lowered = message.lower()

    if name in ("MissingApiKey", "MissingNaverCredentials") or "not set" in lowered:
        kind = CREDENTIALS_MISSING
    elif code == 401:
        kind = AUTH_FAILED
    elif code == 403:
        kind = ACCESS_DENIED
    elif code == 429:
        kind = RATE_LIMITED
    elif code is not None and 500 <= code <= 599:
        kind = NETWORK
    elif "network error" in lowered or "timed out" in lowered or "timeout" in lowered:
        kind = NETWORK
    elif isinstance(error, (TimeoutError, ConnectionError)):
        kind = NETWORK
    elif isinstance(error, (ValueError, KeyError, TypeError)) or "json" in lowered:
        # A malformed body reaches us as a decode error from the collector.
        kind = BAD_RESPONSE
    else:
        kind = UNKNOWN

    # Never let a message that might carry a key reach the operator UI or logs.
    return Classified(
        kind=kind,
        status_code=code,
        detail=redact(message)[:400],
        retryable=kind in RETRYABLE,
    )


# Anything that looks like a credential, whatever produced it.
_SECRET_PATTERNS = (
    re.compile(r"(KakaoAK)\s+\S+", re.IGNORECASE),
    re.compile(r"(X-Naver-Client-(?:Id|Secret))\s*[:=]\s*\S+", re.IGNORECASE),
    # NAVER API HUB sends the key in an NCP gateway header. Nothing echoes it
    # back today, but a redaction list that lags the code is how one gets out.
    re.compile(r"(X-NCP-APIGW-API-KEY(?:-ID)?)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"((?:api[_-]?key|client[_-]?secret|client[_-]?id|token))\s*[:=]\s*\S+",
               re.IGNORECASE),
)


def redact(message: str) -> str:
    """Strip anything credential-shaped out of a message before it is stored."""
    cleaned = message or ""
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub(r"\1 <redacted>", cleaned)
    return cleaned
