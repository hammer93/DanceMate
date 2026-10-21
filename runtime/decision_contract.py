"""The contract every human decision is accepted under (v0.96.46).

Authentication (`admin_auth`) says who is asking and the request token
(`admin_csrf`) says the console's own page asked. Neither says *what the
operator was looking at*. v0.96.45 bound the Review forms to a fingerprint of
the candidate they showed, but a post without one - the JSON API, a page
opened before the deploy - was still applied, and a Duplicates answer was
bound to nothing but the pair being OPEN. Two contracts close that:

* **A decision basis** (Review EDIT / CONFIRM / APPROVE / REJECT / DUPLICATE).
  `review_basis()` fingerprints what a reviewer is shown for one candidate:
  the engine's values for it, its review state, the Events built from it and
  the content the source items behind them hold (body and poster text, by
  hash - never a fetch time, so a re-check that found nothing new
  invalidates nothing). `record_review()` is the only way the console
  records a review action: inside one transaction it takes the candidate's
  lock, locks its Events, recomputes the basis and refuses a missing,
  malformed or different one before anything is written. A decision changes
  the review state, so the same basis cannot be accepted twice.

* **A signed decision preview** (Duplicates MERGE / KEEP_SEPARATE). A preview
  token names its action and subject in the clear and signs them with the
  reviewer, when it was issued and a digest of everything the decision rests
  on. `preview_refusal()` tells a missing, forged, expired, other-action,
  other-subject or out-of-date token apart, so the operator is told which.

Neither contract is optional and neither has a bypass. Signing keys come
from `admin_csrf.signing_key()`, one derived key per purpose; nothing secret
is in a basis, and no token or key is ever logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any

# --- refusals -------------------------------------------------------------------

MISSING_BASIS = "MISSING_BASIS"
INVALID_BASIS = "INVALID_BASIS"
STALE_REVIEW_STATE = "STALE_REVIEW_STATE"
MISSING_PREVIEW_TOKEN = "MISSING_PREVIEW_TOKEN"
INVALID_PREVIEW_TOKEN = "INVALID_PREVIEW_TOKEN"
EXPIRED_PREVIEW = "EXPIRED_PREVIEW"
WRONG_ACTION_TOKEN = "WRONG_ACTION_TOKEN"
WRONG_SUBJECT_TOKEN = "WRONG_SUBJECT_TOKEN"
STALE_PREVIEW = "STALE_PREVIEW"
ALREADY_RESOLVED = "ALREADY_RESOLVED"
DECISION_REFUSED = "DECISION_REFUSED"
CONCURRENT_DECISION = "CONCURRENT_DECISION"
REVIEWER_MISMATCH = "REVIEWER_MISMATCH"

# 422: the request does not carry what the contract asks for. 409: it did,
# but the state it was made against is not the state there is now.
STATUS = {
    MISSING_BASIS: 422,
    INVALID_BASIS: 422,
    STALE_REVIEW_STATE: 409,
    MISSING_PREVIEW_TOKEN: 422,
    INVALID_PREVIEW_TOKEN: 422,
    EXPIRED_PREVIEW: 409,
    WRONG_ACTION_TOKEN: 422,
    WRONG_SUBJECT_TOKEN: 422,
    STALE_PREVIEW: 409,
    ALREADY_RESOLVED: 409,
    DECISION_REFUSED: 409,
    CONCURRENT_DECISION: 409,
    REVIEWER_MISMATCH: 422,
}


class DecisionRefused(Exception):
    """The decision was not recorded. Nothing was written."""

    def __init__(self, code: str, message: str, reasons: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reasons = reasons or [message]
        self.status = STATUS.get(code, 409)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "reasons": self.reasons,
                "recorded": False}


def concurrent(exc: Exception) -> bool:
    """A deadlock or serialization failure PostgreSQL resolved by aborting us."""
    return getattr(exc, "sqlstate", None) in ("40P01", "40001")


# --- the Review decision basis -----------------------------------------------------

BASIS_VERSION = 2
BASIS_RE = re.compile(r"^[0-9a-f]{32}$")

# Candidate fields a reviewer is shown and decides on. A change in any of them
# means the page the decision was made on is not the candidate there is now.
_CANDIDATE_FIELDS = ("event_name", "event_date", "start_time", "end_time", "venue", "fee",
                     "fee_display_text", "event_type", "candidate_status", "post_id")

# A per-candidate transaction lock, so two reviewers of one candidate are
# serialised even before it has a candidate_review_state row to lock.
_REVIEW_LOCK_NAMESPACE = 0x4D52 << 40


def _candidate_facts(settings, candidate_id: int) -> dict[str, Any]:
    from . import candidates  # noqa: PLC0415 - the engine store is the console's only

    row = candidates.get(settings, candidate_id)
    if row is None:
        return {}
    return {k: row.get(k) for k in _CANDIDATE_FIELDS}


def _review_facts(con, settings, candidate_id: int,
                  current: dict[str, Any] | None) -> dict[str, Any]:
    from . import review  # noqa: PLC0415

    current = current if current is not None else review.state(con, candidate_id)
    with con.cursor() as cur:
        cur.execute(
            "SELECT event_id, source_item_id, primary_source_item_id, event_date, end_date, "
            "  start_time, end_time, venue_text, venue_id, fee, listing_state, "
            "  canonical_event_id, review_state FROM events "
            "WHERE candidate_id = %s ORDER BY event_id", (candidate_id,))
        events = [list(r) for r in cur.fetchall()]
        items = sorted({i for e in events for i in (e[1], e[2]) if i is not None})
        sources: list[list[Any]] = []
        if items:
            cur.execute(
                "SELECT i.source_item_id, i.content_hash, c.content_hash, "
                "  c.acquisition_status, c.extracted_input_signature FROM source_items i "
                "LEFT JOIN source_item_content c USING (source_item_id) "
                "WHERE i.source_item_id = ANY(%s) ORDER BY i.source_item_id", (items,))
            sources = [list(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT source_item_id, image_index, content_hash, md5(COALESCE(ocr_text, '')) "
                "FROM source_item_image WHERE source_item_id = ANY(%s) "
                "ORDER BY source_item_id, image_index, source_item_image_id", (items,))
            sources.extend(["image", *r] for r in cur.fetchall())
    return {
        "v": BASIS_VERSION,
        "candidate_id": candidate_id,
        "candidate": _candidate_facts(settings, candidate_id),
        "review": [current.get("review_state"), current.get("last_action"),
                   current.get("action_count"), current.get("corrected_json") or {},
                   current.get("duplicate_of_candidate_id")],
        "events": events,
        "sources": sources,
    }


def review_basis(con, settings, candidate_id: int,
                 current: dict[str, Any] | None = None) -> str:
    """The fingerprint of what a reviewer is shown for one candidate."""
    facts = _review_facts(con, settings, candidate_id, current)
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


def basis_refusal(given: str | None, current: str) -> DecisionRefused | None:
    given = (given or "").strip()
    if not given:
        return DecisionRefused(MISSING_BASIS, "this decision carries no basis - open the "
                               "candidate's Review page (or GET /api/admin/review/{id}) and "
                               "act from what it shows; nothing was recorded")
    if not BASIS_RE.match(given):
        return DecisionRefused(INVALID_BASIS, "the decision basis is not one this console "
                               "issued; nothing was recorded")
    if not hmac.compare_digest(given, current):
        return DecisionRefused(STALE_REVIEW_STATE, "This candidate changed after the page was "
                               "opened (its values, its Event, its source or its review "
                               "state); nothing was recorded. Review the current values and "
                               "act again.")
    return None


def record_review(con, settings, *, candidate_id: int, action: str, basis: str | None,
                  reviewer: str, before: dict[str, Any] | None = None,
                  after: dict[str, Any] | None = None, reason: str | None = None,
                  duplicate_of_candidate_id: int | None = None) -> dict[str, Any]:
    """Record one review action, only against the basis it was decided on.

    Lock the candidate, lock its Events, read the state as it is now, compare
    the basis, check the action, write the action and the review state - all
    in one transaction, so a second reviewer (or the same form twice) waits
    and then finds a different basis.
    """
    from . import review  # noqa: PLC0415

    try:
        with con.transaction():
            with con.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)",
                            (_REVIEW_LOCK_NAMESPACE + int(candidate_id),))
                cur.execute("SELECT event_id FROM events WHERE candidate_id = %s "
                            "ORDER BY event_id FOR UPDATE", (candidate_id,))
            refused = basis_refusal(basis, review_basis(con, settings, candidate_id))
            if refused is not None:
                raise refused
            try:
                return review.record(
                    con, candidate_id=candidate_id, action=action, reviewer=reviewer,
                    before=before, after=after, reason=reason,
                    duplicate_of_candidate_id=duplicate_of_candidate_id)
            except review.ReviewError as exc:
                raise DecisionRefused(DECISION_REFUSED, str(exc)) from exc
    except DecisionRefused:
        raise
    except Exception as exc:
        if concurrent(exc):
            raise DecisionRefused(CONCURRENT_DECISION, "another decision on this candidate was "
                                  "being recorded at the same time; nothing was recorded - "
                                  "reload and act again") from exc
        raise


# --- signed decision previews ---------------------------------------------------------

TOKEN_VERSION = "p1"
PREVIEW_TOKEN_TTL_SECONDS = 2 * 3600
CLOCK_SKEW_SECONDS = 300
_TOKEN_RE = re.compile(r"^p1\.(\d{1,12})\.([A-Z_]{1,32})\.(\d{1,18})\.([0-9a-f]{32})\."
                       r"([0-9a-f]{64})$")


def facts_digest(facts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


def _signature(purpose: str, issued: int, action: str, subject: int, digest: str,
               reviewer: str) -> str:
    from . import admin_csrf  # noqa: PLC0415 - keeps the scheduler import graph as it was

    message = f"{TOKEN_VERSION}|{issued}|{action}|{subject}|{digest}|{reviewer}"
    return hmac.new(admin_csrf.signing_key(purpose), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def preview_token(purpose: str, *, action: str, subject: int, facts: dict[str, Any],
                  reviewer: str, now: float | None = None) -> str:
    """A token binding one confirm to one preview: its action, subject, facts,
    reviewer and issue time. Only the signature makes it worth anything."""
    issued = int(time.time() if now is None else now)
    digest = facts_digest(facts)
    return (f"{TOKEN_VERSION}.{issued}.{action}.{int(subject)}.{digest}."
            f"{_signature(purpose, issued, action, int(subject), digest, reviewer)}")


def preview_refusal(given: str | None, purpose: str, *, action: str, subject: int,
                    facts: dict[str, Any] | None, reviewer: str,
                    now: float | None = None,
                    ttl: int = PREVIEW_TOKEN_TTL_SECONDS) -> DecisionRefused | None:
    """Why this token does not authorise this decision, or None.

    ``facts`` None checks everything but the digest (the caller has refusals
    of its own to report first, and compares the facts after).
    """
    given = (given or "").strip()
    if not given:
        return DecisionRefused(MISSING_PREVIEW_TOKEN, "this decision needs its preview - open "
                               "the preview and confirm from there; nothing was recorded")
    match = _TOKEN_RE.match(given)
    if match is None:
        return DecisionRefused(INVALID_PREVIEW_TOKEN, "the preview token is not one this "
                               "console issued; nothing was recorded")
    issued, t_action, t_subject, digest, signature = match.groups()
    expected = _signature(purpose, int(issued), t_action, int(t_subject), digest, reviewer)
    if not hmac.compare_digest(signature, expected):
        return DecisionRefused(INVALID_PREVIEW_TOKEN, "the preview token's signature does not "
                               "hold for this reviewer; nothing was recorded")
    current = time.time() if now is None else now
    if int(issued) > current + CLOCK_SKEW_SECONDS:
        return DecisionRefused(INVALID_PREVIEW_TOKEN, "the preview token was issued in the "
                               "future; nothing was recorded")
    if current - int(issued) > ttl:
        return DecisionRefused(EXPIRED_PREVIEW, "the preview has expired - preview again; "
                               "nothing was recorded")
    if t_action != action:
        return DecisionRefused(WRONG_ACTION_TOKEN, f"the preview was for {t_action}, not "
                               f"{action}; nothing was recorded")
    if int(t_subject) != int(subject):
        return DecisionRefused(WRONG_SUBJECT_TOKEN, f"the preview was for #{t_subject}, not "
                               f"#{subject}; nothing was recorded")
    if facts is not None and not hmac.compare_digest(digest, facts_digest(facts)):
        return DecisionRefused(STALE_PREVIEW, "what this decision would change is no longer "
                               "what the preview showed (the events, their sources or a "
                               "person's verdict changed) - preview again; nothing was "
                               "recorded")
    return None
