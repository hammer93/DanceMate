"""Backup naming, retention and freshness (spec items 8, 9)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime import backup_state


def make(backup_dir, name, *, complete=True):
    target = backup_dir / name
    target.mkdir()
    if complete:
        (target / backup_state.POSTGRES_DUMP).write_bytes(b"dump")
        (target / backup_state.ENGINE_SQLITE).write_bytes(b"sqlite")
    return target


def test_backup_name_is_timestamped_and_round_trips():
    moment = datetime(2026, 9, 3, 10, 15, 0, tzinfo=timezone.utc)
    name = backup_state.backup_name(moment)
    assert name == "dancemate-backup-20260903-101500"
    assert backup_state.parse_backup_name(name) == moment


@pytest.mark.parametrize(
    "name",
    ["backup-20260903-101500", "dancemate-backup-2026-09-03", "dancemate-backup-20261303-101500", "notes"],
)
def test_foreign_directory_names_are_ignored(name):
    assert backup_state.parse_backup_name(name) is None


def test_listing_is_newest_first_and_skips_files(env):
    backup_dir = env / "backup"
    for stamp in ("20260901-000000", "20260903-000000", "20260902-000000"):
        make(backup_dir, f"dancemate-backup-{stamp}")
    (backup_dir / "README.txt").write_text("not a backup", encoding="utf-8")
    make(backup_dir, "pre-restore-20260903-000000")

    names = [e.name for e in backup_state.list_backups(backup_dir)]
    assert names == [
        "dancemate-backup-20260903-000000",
        "dancemate-backup-20260902-000000",
        "dancemate-backup-20260901-000000",
    ]


def test_missing_backup_directory_lists_nothing(tmp_path):
    assert backup_state.list_backups(tmp_path / "absent") == []


def test_retention_keeps_the_newest_n_and_names_the_oldest_first(env):
    backup_dir = env / "backup"
    for day in range(1, 11):
        make(backup_dir, f"dancemate-backup-202609{day:02d}-000000")
    doomed = backup_state.prune(backup_dir, 7)
    assert doomed == [
        "dancemate-backup-20260901-000000",
        "dancemate-backup-20260902-000000",
        "dancemate-backup-20260903-000000",
    ]


def test_retention_deletes_nothing_when_under_the_limit(env):
    backup_dir = env / "backup"
    make(backup_dir, "dancemate-backup-20260903-000000")
    assert backup_state.prune(backup_dir, 7) == []


def test_retention_below_one_is_refused(env):
    with pytest.raises(ValueError):
        backup_state.prune(env / "backup", 0)


def test_status_fails_when_no_backup_exists(settings):
    report = backup_state.status(settings)
    assert report["status"] == "FAIL"
    assert report["count"] == 0


def test_status_fails_on_an_incomplete_backup(settings, env):
    make(env / "backup", "dancemate-backup-20260903-000000", complete=False)
    now = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)
    report = backup_state.status(settings, now=now)
    assert report["status"] == "FAIL"
    assert backup_state.POSTGRES_DUMP in report["detail"]


def test_status_passes_on_a_recent_complete_backup(settings, env):
    make(env / "backup", "dancemate-backup-20260903-000000")
    now = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
    report = backup_state.status(settings, now=now)
    assert report["status"] == "PASS"
    assert report["latest_age_hours"] == 6.0


def test_status_warns_on_a_stale_backup(settings, env):
    make(env / "backup", "dancemate-backup-20260901-000000")
    now = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
    report = backup_state.status(settings, now=now)
    assert report["status"] == "WARN"
    assert "old" in report["detail"]


def test_backup_script_and_module_agree_on_the_naming_contract(repo_root):
    script = (repo_root / "scripts" / "backup.sh").read_text(encoding="utf-8")
    assert "dancemate-backup-$STAMP" in script
    assert backup_state.POSTGRES_DUMP in script
    assert backup_state.ENGINE_SQLITE in script
    # the timestamp format must match backup_name()
    assert "date -u +%Y%m%d-%H%M%S" in script
