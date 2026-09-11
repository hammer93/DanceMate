"""v0.86.9 deployment maintenance: the two defects v0.86.8's deploy surfaced.

1. **Scheduler duplicate guard.** It counted schedulers by grepping `docker ps
   --format '{{.Command}}'`, which Docker truncates ("/usr/local/bin/dock..."),
   so it counted 0 with one scheduler plainly running - a guard that could
   never fire. It now merges two signals that never read that column: the
   compose service label, and the full `--no-trunc` command.

2. **Backup retention ownership.** Two backup directories made by a root
   session could not be pruned by retention, which runs as the repository's
   own user. backup.sh now refuses to write as root (it hands itself to the
   owner), and `fix-ownership.sh --backups` reclaims exactly the foreign-owned
   backup directories - deleting nothing, so retention alone still decides
   which backups are old enough to go.

The decisions are tested as pure functions; the bash itself is run against a
stub `docker` where a POSIX bash is available (the runtime container), and
its text is checked for the properties that must hold everywhere - the same
split tests/test_board_ownership_guard.py already uses.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from runtime import backup_state, deploy_guard

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
FULL = "a" * 64
OTHER = "b" * 64


def _read(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


# --- scheduler guard: the decision --------------------------------------------------

def test_no_scheduler_is_not_a_failure_the_deploy_starts_one():
    report = deploy_guard.scheduler_count_report([], [])
    assert report["count"] == 0 and report["status"] == "PASS"


def test_one_scheduler_seen_by_both_signals_counts_once():
    report = deploy_guard.scheduler_count_report([FULL], [FULL[:12]])
    assert report["count"] == 1 and report["status"] == "PASS"


def test_two_schedulers_fail():
    report = deploy_guard.scheduler_count_report([FULL, OTHER], [])
    assert report["count"] == 2 and report["status"] == "FAIL"


def test_the_v0868_shape_counts_one_not_zero():
    """The command column was truncated, so the command signal saw nothing -
    the label alone must still find the running scheduler."""
    report = deploy_guard.scheduler_count_report([FULL], [])
    assert report["count"] == 1


def test_a_scheduler_started_outside_compose_is_still_counted():
    report = deploy_guard.scheduler_count_report([], [OTHER])
    assert report["count"] == 1


def test_the_script_and_the_python_agree_on_what_a_scheduler_is():
    text = _read("_common.sh")
    assert f'SCHEDULER_SERVICE_LABEL="{deploy_guard.SCHEDULER_SERVICE_LABEL}"' in text
    assert f'SCHEDULER_COMMAND="{deploy_guard.SCHEDULER_COMMAND}"' in text


def test_the_guard_never_reads_the_truncated_command_column():
    text = _read("_common.sh")
    guard = text.split("scheduler_container_ids() {", 1)[1].split("\n}", 1)[0]
    assert "--no-trunc" in guard
    assert 'label=$SCHEDULER_SERVICE_LABEL' in guard
    assert "docker ps --format '{{.Command}}' | grep -c" not in text


def test_the_guard_reports_what_it_counted():
    body = _read("_common.sh").split("guard_no_duplicate_scheduler() {", 1)[1].split("\n}", 1)[0]
    assert 'log "scheduler guard: $count scheduler container(s) running"' in body
    assert "(( count > 1 ))" in body


def test_the_deploy_still_runs_the_guard_before_and_after():
    text = _read("deploy-production.sh")
    assert "guard_no_duplicate_scheduler" in text.split("=== backup ===")[0]
    assert text.count("guard_single_runtime_and_scheduler") >= 2


# --- scheduler guard: the bash itself, against a stub docker ----------------------

STUB = r"""#!/usr/bin/env bash
if [[ "$1" == "ps" ]]; then
  case "$*" in
    *label=com.docker.compose.service=scheduler*) printf '%b' "${STUB_LABEL_IDS:-}" ;;
    *"{{.ID}} {{.Command}}"*) printf '%b' "${STUB_CMD_LINES:-}" ;;
    *) printf '%b' "${STUB_OTHER:-}" ;;
  esac
fi
exit 0
"""


@pytest.fixture
def stub_bash(tmp_path):
    if sys.platform == "win32" or shutil.which("bash") is None:
        pytest.skip("needs a POSIX bash (runs inside the runtime container)")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)

    def run(snippet: str, **env):
        full_env = dict(os.environ, PATH=f"{bindir}:{os.environ.get('PATH', '')}", **env)
        return subprocess.run(["bash", "-c", f'source scripts/_common.sh; {snippet}'],
                              cwd=REPO, env=full_env, capture_output=True, text=True)

    return run


@pytest.mark.parametrize("label, cmd, expected", [
    ("", "", "0"),
    (f"{FULL}\\n", f"{FULL} \"/usr/local/bin/docker-entrypoint.sh python -m scheduler\"\\n", "1"),
    (f"{FULL}\\n", f"{FULL} \"/usr/local/bin/dock…\"\\n", "1"),           # the v0.86.8 shape
    ("", f"{OTHER} \"python -m scheduler\"\\n", "1"),                       # started by hand
    (f"{FULL}\\n{OTHER}\\n", "", "2"),
])
def test_the_bash_counts_schedulers(stub_bash, label, cmd, expected):
    result = stub_bash("count_scheduler_containers", STUB_LABEL_IDS=label, STUB_CMD_LINES=cmd)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_the_bash_guard_passes_one_and_stops_two(stub_bash):
    one = stub_bash("guard_no_duplicate_scheduler", STUB_LABEL_IDS=f"{FULL}\\n")
    assert one.returncode == 0, one.stderr
    assert "scheduler guard: 1 scheduler container(s) running" in one.stdout
    two = stub_bash("guard_no_duplicate_scheduler", STUB_LABEL_IDS=f"{FULL}\\n{OTHER}\\n")
    assert two.returncode != 0
    assert "duplicate scheduler guard failed: 2" in two.stderr


# --- backup ownership: the decisions -------------------------------------------------

BOARD = {
    "dancemate-backup-20260906-001551": "root",
    "dancemate-backup-20260906-052110": "root",
    "dancemate-backup-20260908-050611": "hammer",
    "dancemate-backup-20260909-023358": "hammer",
    "dancemate-backup-20260909-060424": "hammer",
    "dancemate-backup-20260909-110503": "hammer",
    "dancemate-backup-20260910-010000": "hammer",
    "dancemate-backup-20260911-015706": "hammer",
    "dancemate-backup-20260911-020000": "hammer",
    "notes.txt": "root",
}


def test_retention_keeps_the_newest_whoever_owns_them():
    kept, pruned = backup_state.retention_split(BOARD, 7)
    assert kept[0] == "dancemate-backup-20260911-020000"
    assert len(kept) == 7
    assert pruned == ["dancemate-backup-20260906-052110", "dancemate-backup-20260906-001551"]
    assert "notes.txt" not in kept + pruned


def test_a_foreign_owned_backup_inside_the_window_is_still_kept():
    owners = dict(BOARD, **{"dancemate-backup-20260911-020000": "root"})
    kept, _ = backup_state.retention_split(owners, 7)
    assert "dancemate-backup-20260911-020000" in kept


def test_only_foreign_owned_backup_directories_are_reclaimed():
    assert backup_state.foreign_owned(BOARD, "hammer") == [
        "dancemate-backup-20260906-001551", "dancemate-backup-20260906-052110"]


def test_nothing_to_reclaim_when_everything_is_the_owners():
    owners = {name: "hammer" for name in BOARD if name.startswith("dancemate-backup-")}
    assert backup_state.foreign_owned(owners, "hammer") == []


def test_retention_refuses_a_window_of_zero():
    with pytest.raises(ValueError):
        backup_state.retention_split(BOARD, 0)


def test_the_python_decision_matches_the_scripts_own_retention():
    text = _read("backup.sh")
    assert "-name 'dancemate-backup-*' -printf '%f\\n' | sort -r" in text
    assert '"${ALL[@]:RETENTION}"' in text


# --- backup ownership: the scripts ----------------------------------------------------

def test_backup_hands_itself_to_the_owner_before_writing_anything():
    text = _read("backup.sh")
    handoff = text.index('exec sudo -u "$(repo_owner)" "$REPO_ROOT/scripts/backup.sh"')
    assert handoff < text.index('mkdir -p "$TARGET"')
    assert handoff < text.index("require_docker")
    assert '[[ "$(id -u)" -eq 0 && "$(repo_owner)" != "root" ]]' in text


def test_a_failed_prune_is_still_a_warning_and_names_the_fix():
    text = _read("backup.sh")
    assert "could not fully remove $old" in text
    assert "sudo scripts/fix-ownership.sh --backups --yes" in text


def _backups_block() -> str:
    text = _read("fix-ownership.sh")
    return text.split('if [[ "${1:-}" == "--backups" ]]; then', 1)[1].split("\nfi\n", 1)[0]


def test_reclaim_is_scoped_to_foreign_owned_backup_directories():
    block = _backups_block()
    assert "-mindepth 1 -maxdepth 1 -type d -name 'dancemate-backup-*'" in block
    assert '-not -uid "$owner_uid"' in block
    assert 'chown -R "${owner_uid}:${owner_gid}" -- "$backup_dir/$name"' in block
    assert not re.search(r'chown[^\n]*"\$backup_dir"\s*$', block, re.M)


def test_reclaim_deletes_nothing_and_is_a_dry_run_by_default():
    block = _backups_block()
    assert "rm " not in block and "rm -" not in block
    assert "apply=0" in block and '[[ "${2:-}" == "--yes" ]] && apply=1' in block
    assert block.index("dry run only") < block.index("chown -R")


def test_reclaim_needs_root_to_apply():
    assert '[[ "$(id -u)" -eq 0 ]] || die "--backups --yes must run as root' in _backups_block()


def test_the_tracked_files_mode_is_unchanged():
    text = _read("fix-ownership.sh")
    assert 'chown -R "${owner_uid}:${owner_gid}" "$REPO_ROOT"' in text
    assert "verify_repo_ownership" in text
