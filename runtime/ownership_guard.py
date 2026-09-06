"""Board git/file ownership guard (v0.82.7, "Board Git Ownership Guard").

v0.82.6 added `verify_repo_ownership` (in scripts/_common.sh) and
`scripts/fix-ownership.sh` after 21 tracked files on the board turned up
owned by root instead of the repository's own user, `hammer`. The guard
caught the *symptom*; this release addresses the *habit* that caused it:
git and deploy commands typed directly over a root SSH session, which git
and Docker both happily execute, leaving whatever they write owned by
root.

The actual enforcement lives in bash (`scripts/_common.sh`'s
`verify_repo_ownership`, `guard_not_root`, and the new
`scripts/board-git.sh`) because that is where the repository and the
current EUID are real, live things to inspect. What lives here is the pure
decision logic behind those checks - given an owner and a set of file
owners (or a EUID), what is the verdict - so it can be unit tested without
a second Linux user account, a live git checkout, or root access. Mirrors
`runtime/deploy_guard.py`'s own report-dict pattern.
"""

from __future__ import annotations

from typing import Any

# The one user repository work on the board should happen as. Not enforced
# as a hardcoded requirement everywhere (a developer's own laptop checkout
# legitimately has a different owner) - only where a check explicitly opts
# into "this must be hammer specifically", e.g. the board's own canonical
# checkout.
CANONICAL_BOARD_USER = "hammer"


def ownership_report(repo_owner: str, file_owners: dict[str, str]) -> dict[str, Any]:
    """Do every tracked file's owner match the repository directory's own
    owner? Mirrors scripts/_common.sh's verify_repo_ownership exactly, as a
    pure function: no filesystem access, so a test can hand it a fabricated
    owner map instead of needing a second real user account.
    """
    bad = {path: owner for path, owner in file_owners.items() if owner != repo_owner}
    if bad:
        return {
            "status": "FAIL",
            "detail": f"{len(bad)} tracked file(s) not owned by '{repo_owner}': {sorted(bad)}",
            "bad": bad,
        }
    return {
        "status": "PASS",
        "detail": f"all {len(file_owners)} tracked file(s) owned by '{repo_owner}'",
    }


def repo_owner_report(repo_owner: str, expected: str = CANONICAL_BOARD_USER) -> dict[str, Any]:
    """Is the checkout itself owned by the canonical board user? A repo
    self-consistently owned by root (every tracked file matching a root-
    owned directory) would pass `ownership_report` yet still be exactly
    the drift this release exists to prevent - this check is the other
    half."""
    if repo_owner != expected:
        return {
            "status": "FAIL",
            "detail": f"repository is owned by '{repo_owner}', expected '{expected}'",
        }
    return {"status": "PASS", "detail": f"repository is owned by '{expected}'"}


def not_root_report(euid: int) -> dict[str, Any]:
    """Root can do OS/service-level work; it must not run a script that
    touches this repository's tracked files, or whatever it writes is
    owned by root - the exact incident this release fixes. EUID 0 is
    root on every POSIX system this project targets; nothing here reads
    an actual username, since "root" is a UID convention, not a name
    convention (a system could rename the account)."""
    if euid == 0:
        return {
            "status": "FAIL",
            "detail": "running as root (euid 0) - repository-touching commands must run as the repository's own owner",
        }
    return {"status": "PASS", "detail": f"running as euid {euid}, not root"}


def board_ownership_report(
    repo_owner: str, file_owners: dict[str, str], euid: int,
    expected_owner: str = CANONICAL_BOARD_USER,
) -> dict[str, Any]:
    """Combined verdict: the three checks a deploy preflight runs together."""
    checks = {
        "not_root": not_root_report(euid),
        "repo_owner": repo_owner_report(repo_owner, expected_owner),
        "tracked_ownership": ownership_report(repo_owner, file_owners),
    }
    failed = {name: c for name, c in checks.items() if c["status"] != "PASS"}
    if failed:
        return {
            "status": "FAIL",
            "detail": "; ".join(f"{name}: {c['detail']}" for name, c in failed.items()),
            "checks": checks,
        }
    return {"status": "PASS", "detail": "root guard, repo owner and tracked ownership all clean", "checks": checks}
