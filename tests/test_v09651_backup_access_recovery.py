"""v0.96.51 recovery: backup access and an isolated Backup status.

The first v0.96.51 deploy made its backup 0700/0600 (umask 077). The runtime
reads the backup directory through its bind mount as another user, so
`Path.is_file()` raised PermissionError, the exception escaped
health.collect() and /status answered HTTP 500 - Database, Scheduler and
Information could not be read either. These tests hold the corrected
contract: a backup the runtime cannot read is Backup FAIL with a reason, the
other components are still measured, the endpoint still says FAIL (503) and
check-server / the deploy gate still fail on it.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runtime import backup_state, health, ops_alerts

REPO = Path(__file__).resolve().parents[1]
BACKUP_SH = (REPO / "scripts" / "backup.sh").read_text(encoding="utf-8")


def make(backup_dir: Path, name: str, *, manifest: dict | None | str = "auto",
         dump: bytes = b"dump", sqlite: bytes = b"sqlite") -> Path:
    target = backup_dir / name
    target.mkdir()
    (target / backup_state.POSTGRES_DUMP).write_bytes(dump)
    (target / backup_state.ENGINE_SQLITE).write_bytes(sqlite)
    if manifest == "auto":
        manifest = {
            "postgres": {"status": "ok", "bytes": len(dump)},
            "engine_sqlite": {"status": "ok", "bytes": len(sqlite)},
            "complete": True,
        }
    if isinstance(manifest, dict):
        (target / backup_state.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    elif isinstance(manifest, str):
        (target / backup_state.MANIFEST).write_text(manifest, encoding="utf-8")
    return target


def recent(hours: float = 1) -> str:
    return backup_state.backup_name(datetime.now(timezone.utc) - timedelta(hours=hours))


def deny(monkeypatch, *, name: str, method: str = "stat"):
    """Make one path raise EACCES the way a 0700 directory owned by another
    user does for the runtime (works for any test user, root included)."""
    original = getattr(Path, method)

    def guarded(self, *args, **kwargs):
        if self.name == name:
            raise PermissionError(13, "Permission denied", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, method, guarded)


# --- Backup component: every failure is a FAIL with a reason, never a raise ----

def test_unreadable_backup_part_is_backup_fail_not_an_exception(settings, monkeypatch):
    make(settings.backup_dir, recent())
    deny(monkeypatch, name=backup_state.POSTGRES_DUMP)
    result = backup_state.status(settings)
    assert result["status"] == "FAIL"
    assert result["reason"] == backup_state.REASON_PERMISSION_DENIED
    assert "postgres.dump" in result["detail"] and "permission denied" in result["detail"]


def test_unreadable_manifest_is_permission_denied(settings, monkeypatch):
    make(settings.backup_dir, recent())
    deny(monkeypatch, name=backup_state.MANIFEST, method="read_text")
    result = backup_state.status(settings)
    assert (result["status"], result["reason"]) == ("FAIL", backup_state.REASON_PERMISSION_DENIED)


def test_unreadable_backup_directory_is_backup_fail(settings, monkeypatch):
    def refuse(_path):
        raise PermissionError(13, "Permission denied", str(settings.backup_dir))

    monkeypatch.setattr(backup_state, "list_backups", refuse)
    result = backup_state.status(settings)
    assert (result["status"], result["reason"]) == ("FAIL", backup_state.REASON_PERMISSION_DENIED)
    assert result["count"] == 0


@pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs POSIX modes enforced against a non-root user")
def test_a_real_mode_000_backup_directory_is_backup_fail(settings):
    target = make(settings.backup_dir, recent())
    target.chmod(0)
    try:
        result = backup_state.status(settings)
    finally:
        target.chmod(0o700)
    assert (result["status"], result["reason"]) == ("FAIL", backup_state.REASON_PERMISSION_DENIED)


def test_absent_backup_directory_is_backup_fail(settings):
    shutil.rmtree(settings.backup_dir)
    result = backup_state.status(settings)
    assert (result["status"], result["reason"]) == ("FAIL", backup_state.REASON_NONE)


@pytest.mark.parametrize("kwargs,reason", [
    ({"dump": b""}, backup_state.REASON_PART_EMPTY),
    ({"manifest": "{not json"}, backup_state.REASON_MANIFEST_UNREADABLE),
    ({"manifest": {"postgres": {"status": "failed"}, "engine_sqlite": {"status": "ok"}}},
     backup_state.REASON_RECORDED_FAILED),
    ({"manifest": {"postgres": {"status": "ok"}, "engine_sqlite": {"status": "ok"}, "complete": False}},
     backup_state.REASON_RECORDED_INCOMPLETE),
    # Cut short after it was written (or corrupted on disk): the size the
    # manifest recorded no longer matches - read from metadata, not contents.
    ({"manifest": {"postgres": {"status": "ok", "bytes": 999}, "engine_sqlite": {"status": "ok", "bytes": 6}},
      "dump": b"dump"}, backup_state.REASON_SIZE_MISMATCH),
])
def test_each_incomplete_backup_has_its_own_reason(settings, kwargs, reason):
    make(settings.backup_dir, recent(), **kwargs)
    result = backup_state.status(settings)
    assert (result["status"], result["reason"]) == ("FAIL", reason)


def test_missing_part_is_part_missing(settings):
    target = make(settings.backup_dir, recent())
    (target / backup_state.ENGINE_SQLITE).unlink()
    result = backup_state.status(settings)
    assert (result["status"], result["reason"]) == ("FAIL", backup_state.REASON_PART_MISSING)


def test_stale_backup_is_warn_with_a_reason(settings):
    make(settings.backup_dir, recent(hours=settings.backup_max_age_hours + 2))
    result = backup_state.status(settings)
    assert (result["status"], result["reason"]) == ("WARN", backup_state.REASON_STALE)


def test_a_healthy_backup_has_no_reason(settings):
    make(settings.backup_dir, recent())
    result = backup_state.status(settings)
    assert result["status"] == "PASS" and "reason" not in result


# --- legacy and new layouts ----------------------------------------------------

def test_legacy_backup_manifest_without_sizes_still_passes(settings):
    """Backups made before v0.96.51 recorded status but no bytes/sha256."""
    make(settings.backup_dir, recent(), manifest={
        "name": "x", "postgres": {"database": "dancemate", "status": "ok", "file": "postgres.dump"},
        "engine_sqlite": {"status": "ok", "file": "engine.sqlite3"}})
    assert backup_state.status(settings)["status"] == "PASS"


def test_legacy_backup_without_a_manifest_still_passes(settings):
    make(settings.backup_dir, recent(), manifest=None)
    assert backup_state.status(settings)["status"] == "PASS"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_new_layout_needs_no_read_permission_on_the_dumps(settings):
    """0711 directory, 0600 dumps, 0644 manifest: /status reads only metadata.
    A dump that cannot be opened is no obstacle, because it is never opened."""
    target = make(settings.backup_dir, recent())
    for name in (backup_state.POSTGRES_DUMP, backup_state.ENGINE_SQLITE):
        (target / name).chmod(0o600)
    (target / backup_state.MANIFEST).chmod(0o644)
    target.chmod(0o711)
    assert backup_state.status(settings)["status"] == "PASS"


def test_status_never_opens_a_dump(settings, monkeypatch):
    make(settings.backup_dir, recent())
    deny(monkeypatch, name=backup_state.POSTGRES_DUMP, method="open")
    deny(monkeypatch, name=backup_state.POSTGRES_DUMP, method="read_bytes")
    assert backup_state.status(settings)["status"] == "PASS"


# --- a backup being written ------------------------------------------------------

def test_backup_in_progress_is_never_the_latest(settings):
    make(settings.backup_dir, recent(hours=3))
    staging = settings.backup_dir / (backup_state.IN_PROGRESS_PREFIX + recent(hours=0))
    staging.mkdir()
    (staging / backup_state.POSTGRES_DUMP).write_bytes(b"part")       # half written
    result = backup_state.status(settings)
    assert result["status"] == "PASS"
    assert result["latest"].startswith("dancemate-backup-")
    assert result["in_progress"] == [staging.name[len(backup_state.IN_PROGRESS_PREFIX):]]


def test_failed_attempts_are_never_the_latest(settings):
    make(settings.backup_dir, recent(hours=3))
    make(settings.backup_dir, "failed-" + recent(hours=0), dump=b"")
    assert backup_state.status(settings)["status"] == "PASS"


# --- /status: the other components survive a failing probe -----------------------

@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


def test_collect_isolates_a_raising_probe(settings, monkeypatch):
    def boom(_settings):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(backup_state, "status", boom)
    result = health.collect(settings)
    assert set(result) == set(health.COMPONENTS)
    assert result["backup"] == {"status": "FAIL", "reason": "PROBE_ERROR",
                                "detail": "the backup probe raised PermissionError"}
    assert result["runtime"]["status"] == "PASS"       # still measured
    assert "available" in result["database"] or result["database"]["status"] in {"PASS", "FAIL"}


def test_status_endpoint_answers_structured_fail_on_unreadable_backup(client, settings, monkeypatch):
    make(settings.backup_dir, recent())
    deny(monkeypatch, name=backup_state.POSTGRES_DUMP)
    response = client.get("/status")
    assert response.status_code == 503                 # structured, and still not "healthy"
    body = response.json()
    assert body["status"] == "FAIL"
    assert body["backup"]["status"] == "FAIL"
    assert body["backup"]["reason"] == "BACKUP_PERMISSION_DENIED"
    for component in health.COMPONENTS:
        assert body[component]["status"] in {"PASS", "WARN", "FAIL"}
    assert body["runtime"]["status"] == "PASS"


def test_status_summary_reports_backup_fail_on_unreadable_backup(client, settings, monkeypatch):
    make(settings.backup_dir, recent())
    deny(monkeypatch, name=backup_state.POSTGRES_DUMP)
    response = client.get("/status/summary")
    assert response.status_code == 503
    assert "Backup ......... FAIL" in response.text.splitlines()


def test_status_endpoint_survives_a_raising_probe(client, monkeypatch):
    def boom(_settings):
        raise RuntimeError("probe bug")

    monkeypatch.setattr(backup_state, "status", boom)
    response = client.get("/status")
    assert response.status_code == 503
    assert response.json()["backup"]["reason"] == "PROBE_ERROR"
    assert "probe bug" not in response.text            # no exception text in the payload


# --- check-server and the deploy gate still fail on Backup FAIL ------------------

BACKUP_FAIL_REPORT = ("DanceMate Server\nRuntime ........ PASS\nDatabase ....... PASS\n"
                      "Scheduler ...... PASS\nInformation .... PASS\nStorage ........ PASS\n"
                      "Backup ......... FAIL\n")


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="needs a POSIX bash (on Windows `bash` may be WSL's)")
@pytest.mark.parametrize("report,code", [(BACKUP_FAIL_REPORT, 1),
                                         (BACKUP_FAIL_REPORT.replace("FAIL", "PASS"), 0)])
def test_check_server_exits_nonzero_on_backup_fail(tmp_path, report, code):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("check-server.sh", "_common.sh"):
        shutil.copy(REPO / "scripts" / name, scripts / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "report.txt").write_text(report, encoding="utf-8", newline="\n")
    curl = bin_dir / "curl"
    curl.write_text('#!/usr/bin/env bash\ncat "$(dirname "$0")/../report.txt"\n'
                    "printf '\\n503'\n", encoding="utf-8", newline="\n")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
    done = subprocess.run(["bash", str(scripts / "check-server.sh")], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == code, done.stdout + done.stderr
    assert "Backup ........." in done.stdout


def test_deploy_health_gate_requires_no_fail_line():
    deploy = (REPO / "scripts" / "deploy-production.sh").read_text(encoding="utf-8")
    assert "! grep -q 'FAIL' <<<\"$summary\"" in deploy
    assert '"$REPO_ROOT/scripts/check-server.sh"' in deploy


def test_monitor_alerts_on_backup_permission_denied():
    facts = {"status": {"http": 503, "status": "FAIL", "backup": {
        "status": "FAIL", "reason": "BACKUP_PERMISSION_DENIED",
        "detail": "dancemate-backup-x postgres.dump cannot be read by the runtime (permission denied)"}},
        "runtime_running": True, "scheduler_count": 1}
    keys = set(ops_alerts.conditions(facts))
    assert "BACKUP_FAILED" in keys


# --- backup.sh: explicit, least-privilege modes and a reader check ---------------

@pytest.mark.parametrize("needle", [
    "umask 077",                                             # private by default
    'chmod 0600 "$TARGET/postgres.dump" "$TARGET/engine.sqlite3"',
    'chmod 0644 "$TARGET/manifest.json"',
    'chmod 0711 "$TARGET"',
    'chmod 0755 "$BACKUP_DIR"',
    'TARGET="$BACKUP_DIR/.inprogress-$NAME"',
    'mv -- "$TARGET" "$FINAL"',
    "compose exec -T runtime python - \"${TARGET##*/}\"",
    "the runtime container cannot read this backup as /status will",
    "an interrupted backup was left behind",
])
def test_backup_sh_sets_access_explicitly_and_checks_the_runtime_reader(needle):
    assert needle in BACKUP_SH


def test_backup_sh_never_widens_access_to_the_dumps():
    for forbidden in ("chmod -R", "777", "chmod 0664", "chmod 0666", "chmod 0644 \"$TARGET/postgres", "a+r", "o+r"):
        assert forbidden not in BACKUP_SH, forbidden


def test_backup_sh_renames_into_the_contract_only_after_the_reader_check():
    reader = BACKUP_SH.index("the runtime container cannot read this backup")
    rename = BACKUP_SH.index('mv -- "$TARGET" "$FINAL"')
    complete = BACKUP_SH.index("COMPLETE=1")
    retention = BACKUP_SH.index("# --- retention")
    assert reader < rename < complete < retention


def test_staging_prefix_agrees_between_script_and_module():
    assert backup_state.IN_PROGRESS_PREFIX == ".inprogress-"
    assert ".inprogress-dancemate-backup-*" in BACKUP_SH


# --- timers: one of each, and neither runs collection ------------------------------

SYSTEMD = REPO / "deploy" / "rockpro64" / "systemd"


def test_exactly_one_backup_timer_and_one_monitor_timer():
    timers = sorted(p.name for p in SYSTEMD.glob("*.timer"))
    assert timers == ["dancemate-backup.timer", "dancemate-ops-monitor.timer"]


@pytest.mark.parametrize("unit", ["dancemate-backup.service", "dancemate-ops-monitor.service"])
def test_units_run_as_the_owner_and_never_start_collection(unit):
    text = (SYSTEMD / unit).read_text(encoding="utf-8")
    assert "User=hammer" in text and "Type=oneshot" in text
    for forbidden in ("compose up", "scheduler", "normaliz", "run_once"):
        assert forbidden not in text.split("[Service]", 1)[1].lower(), forbidden
