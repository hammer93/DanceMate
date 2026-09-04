"""Ownership hardening for the deploy scripts (v0.81.2, Phase D).

The working tree kept accumulating root-owned tracked files after board test
runs (an ad hoc `docker run --user root ... -v $REPO:/src ...` pattern used
to install and run pytest), each time silently blocking the next
`git checkout`/`pull` until someone ran a manual `chown -R`. Two things are
verified here: that the deploy script now guards against this before it can
bite the next deploy, and that the new container-runner helper actually
builds a correct `docker run` invocation - a broken argument split would
silently run the wrong command rather than raise anything in bash.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON = REPO_ROOT / "scripts" / "_common.sh"
START_SERVER = REPO_ROOT / "scripts" / "start-server.sh"
RUN_CONTAINER_TESTS = REPO_ROOT / "scripts" / "run-container-tests.sh"
FIX_OWNERSHIP = REPO_ROOT / "scripts" / "fix-ownership.sh"


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("no bash available to exercise the shell helpers")
    return found


# --- static: the guard is actually wired in, and stays narrow -------------

def test_start_server_runs_the_ownership_guard_before_bringing_the_stack_up():
    text = START_SERVER.read_text(encoding="utf-8")
    assert "verify_repo_ownership" in text
    assert text.index("verify_repo_ownership") < text.index("compose up -d")


def _code_lines(path: Path) -> str:
    """A script's text with comment lines stripped, so a check for what a
    script *does* is not fooled by a comment describing what it deliberately
    does not do."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )


def test_only_the_approved_fallback_script_runs_a_recursive_chown():
    for path in (REPO_ROOT / "scripts").glob("*.sh"):
        if "chown -R" in _code_lines(path):
            assert path.name == "fix-ownership.sh", (
                f"{path.name} runs a recursive chown - only fix-ownership.sh, "
                "the approved narrow fallback, should"
            )


def test_the_narrow_fallback_scopes_chown_to_the_repo_root_only():
    text = FIX_OWNERSHIP.read_text(encoding="utf-8")
    assert 'chown -R "${owner_uid}:${owner_gid}" "$REPO_ROOT"' in text


def test_no_script_installs_test_dependencies_as_root():
    """The exact pattern that caused the recurring root-owned files."""
    for path in (REPO_ROOT / "scripts").glob("*.sh"):
        assert "--user root" not in _code_lines(path), \
            f"{path.name} still runs a container as root"


# --- behavioural: the guard passes on a normally-owned tree ----------------

def test_verify_repo_ownership_passes_on_a_normally_owned_tree(tmp_path):
    bash = _bash()
    (tmp_path / "scripts").mkdir()
    shutil.copy(COMMON, tmp_path / "scripts" / "_common.sh")
    (tmp_path / "file.txt").write_text("hi", encoding="utf-8")

    subprocess.run([bash, "-c", "git init -q && git -c user.email=t@t -c user.name=t "
                    "add file.txt && git -c user.email=t@t -c user.name=t commit -q -m x"],
                    cwd=tmp_path, check=True, capture_output=True, text=True)

    result = subprocess.run(
        [bash, "-c", 'source scripts/_common.sh; verify_repo_ownership && echo GUARD_OK'],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "GUARD_OK" in result.stdout


# --- behavioural: the container helper builds a correct docker invocation --

def test_container_run_as_repo_owner_places_image_and_command_correctly(tmp_path):
    """A stub `docker` on PATH echoes its argv; this pins the shape a broken
    opts/command split would silently scramble - image right after every
    docker option, the `sh -c ...` command last, and no stray `--` token."""
    bash = _bash()
    (tmp_path / "scripts").mkdir()
    shutil.copy(COMMON, tmp_path / "scripts" / "_common.sh")
    (tmp_path / "file.txt").write_text("hi", encoding="utf-8")
    subprocess.run([bash, "-c", "git init -q"], cwd=tmp_path, check=True, capture_output=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text("#!/usr/bin/env bash\nfor a in \"$@\"; do printf '%s\\n' \"$a\"; done\n",
                     encoding="utf-8")
    stub.chmod(0o755)

    script = (
        'export PATH="$PWD/bin:$PATH"; source scripts/_common.sh; '
        'container_run_as_repo_owner myimage --network net -e X=1 -- sh -c "echo hi"'
    )
    result = subprocess.run([bash, "-c", script], cwd=tmp_path,
                             capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    argv = result.stdout.splitlines()

    assert "--" not in argv, "the opts/command separator must not reach docker itself"
    image_at = argv.index("myimage")
    assert argv[image_at - 2:image_at] == ["-e", "X=1"], "options must precede the image"
    assert argv[image_at + 1:] == ["sh", "-c", "echo hi"], "the command must follow the image"
    assert "--network" in argv[:image_at] and "net" in argv[:image_at]
