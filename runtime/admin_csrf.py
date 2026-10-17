"""Cross-site request protection for the admin console (v0.96.38).

HTTP Basic (`admin_auth`) says *who* is asking. It cannot say whether the
operator meant to ask: a browser that has the console's credential cached
attaches it to every request for this origin, including a form another page
submits to it. Until v0.96.38 only the venue decision confirms carried
anything a third-party page could not produce (their preview token). This
module is the second contract, kept apart from the first, for every state
changing admin request:

* **Same origin.** A browser names the page a request came from (`Origin`,
  `Sec-Fetch-Site`, `Referer`). If it names another site, the request is
  refused before its token is even read.
* **A request token.** Every POST form the console renders carries a hidden
  `csrf_token`; a script sends it as `X-CSRF-Token` (fetched from
  `GET /api/admin/csrf-token`). The token is an HMAC over the authenticated
  user, the one path it may be posted to, and when it was issued; it expires
  after `TOKEN_TTL_SECONDS`. A token for one action does not open another,
  and it never travels in a URL.

Authentication still comes first and is never replaced by this: `protect()`
depends on `require_admin`, so a request without the credential is a 401
whatever token it carries, and a token without the credential opens nothing.

The venue decision tokens (`venue_resolution.preview_token`) are a third,
different thing - they bind a confirm to the exact facts its preview showed -
and are signed with their own derived key.

Signing keys. `ADMIN_TOKEN_SECRET` when set, else `ADMIN_PASSWORD`; each use
derives its own key from it (`signing_key(purpose)`), so no token is ever
signed with the credential itself and none can be used to recover it.
Rotating either value invalidates every outstanding token at once - an open
page then fails its next post with "reload the page", and nothing else.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from html import escape, unescape
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from .admin_auth import _expected, require_admin

FIELD = "csrf_token"
HEADER = "X-CSRF-Token"
TOKEN_TTL_SECONDS = 12 * 3600
# A token issued this far in the future is refused: a clock that went
# backwards must not mint tokens that outlive their TTL.
CLOCK_SKEW_SECONDS = 300
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_VERSION = "v1"


def signing_key(purpose: str) -> bytes:
    """A key for one kind of token, derived from the configured secret."""
    secret = os.environ.get("ADMIN_TOKEN_SECRET") or os.environ.get("ADMIN_PASSWORD", "")
    return hmac.new(secret.encode("utf-8"), f"dancemate-admin:{purpose}".encode(),
                    hashlib.sha256).digest()


def _signature(user: str, path: str, issued: int) -> str:
    message = f"{_VERSION}|{user}|{path}|{issued}".encode("utf-8")
    return hmac.new(signing_key("csrf"), message, hashlib.sha256).hexdigest()


def issue(path: str, *, user: str | None = None, now: float | None = None) -> str:
    """A token for posting to `path` (no query string) as `user`."""
    user = _expected()[0] if user is None else user
    issued = int(time.time() if now is None else now)
    return f"{_VERSION}.{issued}.{_signature(user, path, issued)}"


def refusal(token: str | None, *, path: str, user: str,
            now: float | None = None) -> str | None:
    """Why this token does not authorise posting to `path`, or None."""
    if not token:
        return "missing request token"
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _VERSION or not parts[1].isdigit():
        return "malformed request token"
    issued = int(parts[1])
    if not hmac.compare_digest(parts[2], _signature(user, path, issued)):
        return "request token does not match this action"
    current = time.time() if now is None else now
    if issued > current + CLOCK_SKEW_SECONDS:
        return "request token issued in the future"
    if current - issued > TOKEN_TTL_SECONDS:
        return "request token expired - reload the page"
    return None


def _netloc(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return parts.netloc.lower() if parts.scheme in ("http", "https") else ""


def origin_refusal(request: Request) -> str | None:
    """Why the browser says this request came from another site, or None.

    A client that names no origin at all (a script, curl) is not refused
    here; it still needs a token, which only an authenticated read yields.
    """
    host = (request.headers.get("host") or "").lower()
    fetch_site = (request.headers.get("sec-fetch-site") or "").lower()
    if fetch_site and fetch_site not in ("same-origin", "none"):
        return f"cross-site request ({fetch_site})"
    origin = request.headers.get("origin")
    if origin is not None:
        if _netloc(origin) != host:
            return "request from another origin"
        return None
    referer = request.headers.get("referer")
    if referer is not None and _netloc(referer) != host:
        return "request referred by another origin"
    return None


async def protect(request: Request, user: str = Depends(require_admin)) -> None:
    """Router dependency: refuse a state-changing request that is cross-site
    or carries no valid token for its own path. Authentication runs first."""
    if request.method.upper() in SAFE_METHODS:
        return
    reason = origin_refusal(request)
    if reason is None:
        token = request.headers.get(HEADER)
        if not token:
            content_type = request.headers.get("content-type", "")
            if content_type.startswith(("application/x-www-form-urlencoded",
                                        "multipart/form-data")):
                value = (await request.form()).get(FIELD)
                token = value if isinstance(value, str) else None
        reason = refusal(token, path=request.url.path, user=user)
    if reason:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"refused: {reason} - nothing changed")


# --- putting the token into the console's own forms --------------------------

_FORM_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_METHOD_RE = re.compile(r"""\bmethod\s*=\s*["']?post\b""", re.IGNORECASE)
_ACTION_RE = re.compile(r"""\baction\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def inject(page: str, *, now: float | None = None) -> str:
    """Add a hidden token, bound to its own action, to every POST form."""

    def add(match: re.Match) -> str:
        tag = match.group(0)
        if not _METHOD_RE.search(tag):
            return tag
        action = _ACTION_RE.search(tag)
        if action is None:
            return tag
        path = urlsplit(unescape(action.group(1) or action.group(2) or "")).path
        if not path.startswith("/"):
            return tag
        return (f'{tag}<input type="hidden" name="{FIELD}" '
                f'value="{escape(issue(path, now=now))}">')

    return _FORM_RE.sub(add, page)


# --- a token for a script ------------------------------------------------------

api = APIRouter(prefix="/api/admin", tags=["admin"])


@api.get("/csrf-token")
def api_csrf_token(path: str = Query(..., max_length=512),
                   user: str = Depends(require_admin)) -> dict:
    """A request token for one admin path, for a client that posts without
    the console's forms (`scripts/apply-board-sources.py`). The token is in
    the body, never the URL; another site cannot read this response."""
    path = urlsplit(path).path
    if not (path.startswith("/admin/") or path.startswith("/api/admin/")):
        raise HTTPException(status_code=400, detail="path must be an admin path")
    return {"path": path, "header": HEADER, "token": issue(path, user=user),
            "expires_in": TOKEN_TTL_SECONDS}
