"""Admin authentication for the LAN staging console.

Deliberately small: HTTP Basic against one credential pair from `.env`. The
console is LAN-only and single-operator, so OAuth would be cost without
benefit. What matters is that the admin surface is not simply open to every
device on the LAN.

Set in `.env`:

    ADMIN_USERNAME=dancemate
    ADMIN_PASSWORD=<generated>

With no password configured the console refuses every request rather than
falling open - a missing credential must not silently disable the lock.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_security = HTTPBasic(auto_error=False)

UNCONFIGURED_DETAIL = (
    "admin console is locked: ADMIN_PASSWORD is not set in .env"
)


def configured() -> bool:
    return bool(os.environ.get("ADMIN_PASSWORD"))


def _expected() -> tuple[str, str]:
    return os.environ.get("ADMIN_USERNAME", "dancemate"), os.environ.get("ADMIN_PASSWORD", "")


def check(username: str | None, password: str | None) -> bool:
    """Constant-time credential comparison. False when unconfigured."""
    expected_user, expected_password = _expected()
    if not expected_password:
        return False
    user_ok = secrets.compare_digest((username or ""), expected_user)
    password_ok = secrets.compare_digest((password or ""), expected_password)
    return user_ok and password_ok


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> str:
    """FastAPI dependency: the admin username, or an HTTP error."""
    if not configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNCONFIGURED_DETAIL,
        )
    if credentials is None or not check(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid admin credentials",
            headers={"WWW-Authenticate": 'Basic realm="DanceMate Admin"'},
        )
    return credentials.username
