"""Board git ownership guard (v0.82.7, "Board Git Ownership Guard").

v0.82.6 added verify_repo_ownership after 21 tracked files on the board
turned up owned by root - the result of `git fetch`/`git merge` typed
directly over a root SSH session during earlier releases' "board sync"
steps, every one of them. That guard caught the symptom after the fact;
this release stops the habit at the door: scripts/deploy-production.sh and
scripts/board-git.sh both refuse to touch the repository as root at all.

`runtime.ownership_guard` holds the pure decision logic (no filesystem, no
second real user account needed) so these properties are testable on any
machine, including this Windows dev host where "a file owned by a
different Unix uid" is not a thing that exists to construct. The scripts
themselves are checked the same way test_deployment_config.py already
checks every other operations script: by reading their own text for the
properties that must hold.
"""

from __future__ import annotations

from pathlib import Path

from runtime import ownership_guard as og

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


# --- 1/2: tracked ownership ---------------------------------------------------

def test_correct_owner_passes():
    report = og.ownership_report("hammer", {"a.py": "hammer", "b.sh": "hammer"})
    assert report["status"] == "PASS"


def test_a_wrong_tracked_owner_fails():
    report = og.ownership_report("hammer", {"a.py": "hammer", "b.sh": "root"})
    assert report["status"] == "FAIL"
    assert "b.sh" in report["bad"]


def test_the_real_incident_shape_is_caught():
    """21 of 422 tracked files were root-owned - reproduced at the same
    scale, not just a single file, to prove the check does not stop at the
    first mismatch."""
    owners = {f"file{i}.py": "hammer" for i in range(401)}
    owners.update({f"root-file{i}.py": "root" for i in range(21)})
    report = og.ownership_report("hammer", owners)
    assert report["status"] == "FAIL"
    assert len(report["bad"]) == 21


# --- 3: wrong repo owner -----------------------------------------------------

def test_correct_repo_owner_passes():
    assert og.repo_owner_report("hammer")["status"] == "PASS"


def test_a_wrong_repo_owner_fails_even_if_self_consistent():
    """A checkout entirely owned by root (every tracked file matching a
    root-owned directory) would pass ownership_report - this is the other
    half of the check, catching that the owner itself is not the canonical
    board user."""
    assert og.repo_owner_report("root")["status"] == "FAIL"


# --- 4/5: root execution blocked, hammer execution passes -------------------

def test_root_execution_is_blocked():
    report = og.not_root_report(0)
    assert report["status"] == "FAIL"
    assert "root" in report["detail"]


def test_non_root_execution_passes():
    assert og.not_root_report(1000)["status"] == "PASS"


# --- combined report ----------------------------------------------------------

def test_combined_report_passes_only_when_all_three_do():
    good = og.board_ownership_report("hammer", {"a.py": "hammer"}, euid=1000)
    assert good["status"] == "PASS"

    root_run = og.board_ownership_report("hammer", {"a.py": "hammer"}, euid=0)
    assert root_run["status"] == "FAIL"
    assert root_run["checks"]["not_root"]["status"] == "FAIL"

    drifted = og.board_ownership_report("hammer", {"a.py": "root"}, euid=1000)
    assert drifted["status"] == "FAIL"
    assert drifted["checks"]["tracked_ownership"]["status"] == "FAIL"

    wrong_owner = og.board_ownership_report("root", {"a.py": "root"}, euid=1000)
    assert wrong_owner["status"] == "FAIL"
    assert wrong_owner["checks"]["repo_owner"]["status"] == "FAIL"


# --- 6: deploy wrapper calls the ownership preflight -------------------------

def test_deploy_wrapper_refuses_root_before_touching_anything():
    text = (SCRIPTS / "deploy-production.sh").read_text(encoding="utf-8")
    assert "guard_not_root" in text
    assert "verify_repo_ownership" in text
    # guard_not_root must run before any docker/backup/build step, not after.
    root_guard_pos = text.index("guard_not_root")
    backup_pos = text.index('log "=== backup ===')
    assert root_guard_pos < backup_pos


def test_board_git_wrapper_never_runs_git_as_root_silently():
    text = (SCRIPTS / "board-git.sh").read_text(encoding="utf-8")
    assert "sudo -u" in text
    assert "repo_owner" in text


# --- 7/9: fix-ownership.sh stays scoped to the repository --------------------

def test_fix_ownership_only_chowns_the_repo_root():
    text = (SCRIPTS / "fix-ownership.sh").read_text(encoding="utf-8")
    assert 'chown -R "${owner_uid}:${owner_gid}" "$REPO_ROOT"' in text
    # never a bare-root or wildcard target alongside the real one
    for forbidden in ('chown -R / ', "chown -R /'", 'chown -R "/"', "chown -R /*"):
        assert forbidden not in text


def test_no_operations_script_chowns_outside_the_repository():
    """Only an actual `chown` invocation matters here - a prose mention
    inside a warn/die message (e.g. "see fix-ownership.sh for the approved
    narrow chown fallback") is not a command and must not trip this.

    scripts/setup-board-operator.sh (v0.82.8) is the one legitimate second
    scope: it provisions a *different* user's own `~/.ssh`, never this
    repository, so its chown targets that user's home instead of REPO_ROOT.
    """
    HOME_SCOPED = {"setup-board-operator.sh": ("SSH_DIR", "AUTH_KEYS", "OPERATOR_USER")}
    for script in SCRIPTS.glob("*.sh"):
        text = script.read_text(encoding="utf-8")
        allowed_extra = HOME_SCOPED.get(script.name, ())
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("chown"):
                continue
            assert (
                "REPO_ROOT" in line or "repo_owner" in line or "owner_uid" in line
                or any(token in line for token in allowed_extra)
            ), f"{script.name}: chown line not scoped to the repository: {line!r}"


# --- 8: no broad permission grants -------------------------------------------

def test_no_script_grants_777_or_recursive_world_write():
    for script in SCRIPTS.glob("*.sh"):
        text = script.read_text(encoding="utf-8")
        assert "777" not in text, f"{script.name} contains a 777 permission grant"
        assert "chmod -R" not in text, f"{script.name} contains a recursive chmod"


# --- 10: container tests preserve ownership ----------------------------------

def test_container_tests_run_as_the_repository_owner_not_root():
    text = (SCRIPTS / "run-container-tests.sh").read_text(encoding="utf-8")
    assert "container_run_as_repo_owner" in text
    assert text.count("verify_repo_ownership") >= 2, (
        "run-container-tests.sh should verify ownership both before and after the container run"
    )


def test_container_run_as_repo_owner_passes_an_explicit_uid_gid():
    text = (SCRIPTS / "_common.sh").read_text(encoding="utf-8")
    assert '--user "${owner_uid}:${owner_gid}"' in text
