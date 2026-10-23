"""v0.96.51: scheduled backups that cannot pass for good ones, and alerts that
are said once.

Part A. A backup is complete only when both parts are present, non-empty and
recorded ok (`backup_state.incomplete_reason`). A failed pg_dump used to leave
an empty `postgres.dump` that /status counted as complete, under a name that
retention counted as one of the N kept. `scripts/backup.sh` now verifies each
part, renames an incomplete backup out of the naming contract, skips retention
after a failure, takes a lock and refuses to start on a full disk.

Part B. `runtime.ops_alerts` turns one check's facts into notices: a condition
must hold for its threshold, an open alert repeats at most once per cooldown,
recovery is said once, and readiness comes from /status - never /health. No
external channel is configured, and the module says so.

Part C. The board's systemd units: a daily backup and a five-minute check, as
the repository owner, neither of them the collection scheduler.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runtime import backup_state, ops_alerts

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)


# --- Part A: what counts as a backup ------------------------------------------------

def _backup(tmp_path, *, pg=b"PGDMP", engine=b"SQLite format 3", manifest=None):
    path = tmp_path / "dancemate-backup-20261023-030000"
    path.mkdir()
    if pg is not None:
        (path / backup_state.POSTGRES_DUMP).write_bytes(pg)
    if engine is not None:
        (path / backup_state.ENGINE_SQLITE).write_bytes(engine)
    if manifest is not None:
        (path / backup_state.MANIFEST).write_text(
            manifest if isinstance(manifest, str) else json.dumps(manifest), encoding="utf-8")
    return path


def _manifest(pg="ok", engine="ok", complete=True):
    return {"postgres": {"status": pg}, "engine_sqlite": {"status": engine},
            "complete": complete}


def test_a_verified_backup_is_complete(tmp_path):
    assert backup_state.incomplete_reason(_backup(tmp_path, manifest=_manifest())) is None


def test_a_backup_without_a_manifest_is_judged_by_its_files(tmp_path):
    """Backups written before v0.96.51 carry the same manifest; a missing
    one is judged by the parts alone, as before."""
    assert backup_state.is_complete(_backup(tmp_path))


@pytest.mark.parametrize("kwargs,reason", [
    ({"pg": b""}, "empty postgres.dump"),
    ({"engine": None}, "missing engine.sqlite3"),
    ({"manifest": _manifest(pg="failed", complete=False)}, "postgres.dump as failed"),
    ({"manifest": _manifest(engine="failed", complete=False)}, "engine.sqlite3 as failed"),
    ({"manifest": "{not json"}, "unreadable manifest.json"),
    ({"manifest": _manifest(complete=False)}, "recorded incomplete"),
])
def test_a_failed_backup_is_not_counted_complete(tmp_path, kwargs, reason):
    """The old test was `is_file()`: an empty dump beside a manifest saying
    failed read PASS."""
    found = backup_state.incomplete_reason(_backup(tmp_path, **kwargs))
    assert found is not None and reason in found


def test_status_names_why_the_latest_backup_is_not_one(tmp_path, monkeypatch):
    from runtime.config import load_settings

    monkeypatch.setenv("DANCEMATE_BACKUP_DIR", str(tmp_path))
    _backup(tmp_path, pg=b"", manifest=_manifest(pg="failed", complete=False))
    report = backup_state.status(load_settings(), now=NOW)
    assert report["status"] == "FAIL" and "postgres.dump" in report["detail"]


def test_a_failed_attempt_is_outside_the_naming_contract():
    assert backup_state.parse_backup_name("failed-dancemate-backup-20261023-030000") is None
    kept, pruned = backup_state.retention_split(
        ["failed-dancemate-backup-20261023-030000", "dancemate-backup-20261022-030000"], 1)
    assert kept == ["dancemate-backup-20261022-030000"] and pruned == []


BACKUP_SH = (REPO / "scripts" / "backup.sh").read_text(encoding="utf-8")


@pytest.mark.parametrize("needle", [
    "umask 077",
    'flock -w 900 8',
    "BACKUP_MIN_FREE_MB",
    "pg_restore --list",
    "PRAGMA integrity_check",
    'mv -- "$TARGET" "$BACKUP_DIR/failed-$NAME"',
    "trap mark_failed EXIT",
    "retention skipped: no older backup is pruned after a failed one",
    '"sha256"',
])
def test_backup_sh_verifies_locks_and_keeps_failures_out(needle):
    assert needle in BACKUP_SH


def test_backup_sh_prunes_only_after_a_complete_backup():
    """Retention is reached only past the failure exit, so a failed run can
    never remove the last good backups."""
    failure_exit = BACKUP_SH.index("retention skipped")
    complete = BACKUP_SH.index("COMPLETE=1")
    retention = BACKUP_SH.index("# --- retention")
    assert failure_exit < complete < retention


def test_the_disk_check_runs_before_anything_is_written():
    assert BACKUP_SH.index("FREE_MB=") < BACKUP_SH.index('mkdir -p "$TARGET"')


# --- Part B: alerts -----------------------------------------------------------------

def _status(**components):
    base = {name: {"status": "PASS"} for name in
            ("runtime", "database", "scheduler", "information", "storage", "backup")}
    for name, value in components.items():
        base[name] = {"status": value, "detail": f"{name} {value}"}
    return {"status": "PASS", **base}


def _facts(**kw):
    facts = {"runtime_running": True, "status": _status(), "sources": {"sources": {}},
             "db": {"job_failure_streaks": {}, "reextract": {"stalled": 0},
                    "normalization": {"failed": 0}},
             "scheduler_count": 1, "disk_free_pct": 70.0}
    facts.update(kw)
    return facts


def _run(facts_seq, state=None, start=NOW, step=timedelta(minutes=5)):
    state = state or {}
    seen = []
    for i, facts in enumerate(facts_seq):
        notices, state = ops_alerts.evaluate(facts, state, start + step * i)
        seen.append(notices)
    return seen, state


def test_a_healthy_check_says_nothing():
    seen, state = _run([_facts()] * 3)
    assert seen == [[], [], []] and state["alerts"] == {}


def test_a_database_failure_alerts_after_two_checks_and_recovers_once():
    """Readiness, not liveness: /health stays 200 with the database down."""
    down = _facts(status=_status(database="FAIL"))
    seen, state = _run([down, down, down, _facts(), _facts()])
    kinds = [[(n["kind"], n["key"]) for n in notices] for notices in seen]
    assert kinds == [[], [("ALERT", "DATABASE_FAILED")], [],
                     [("RECOVERED", "DATABASE_FAILED")], []]
    assert seen[1][0]["severity"] == ops_alerts.CRITICAL
    assert seen[1][0]["at_kst"].endswith("+09:00")


def test_an_open_alert_repeats_once_per_cooldown_not_every_check():
    down = _facts(runtime_running=False, status=None)
    checks = int(timedelta(hours=13) / timedelta(minutes=5))
    seen, _ = _run([down] * checks)
    said = [n["kind"] for notices in seen for n in notices]
    assert said.count("ALERT") == 1
    assert said.count("REMINDER") == 2       # at +6h and +12h, never every 5 minutes


def test_a_duplicate_scheduler_is_critical_at_once():
    seen, _ = _run([_facts(scheduler_count=2)])
    assert [(n["key"], n["severity"]) for n in seen[0]] == [
        ("SCHEDULER_DUPLICATE", ops_alerts.CRITICAL)]


def test_a_missing_scheduler_needs_two_checks():
    """A deploy recreates the container; one check between is not an outage."""
    seen, _ = _run([_facts(scheduler_count=0), _facts()])
    assert seen == [[], []]


def _source(key, state, streak):
    return {"sources": {"not_collecting": [{"source_key": key, "name": "TangoNOW",
                                            "state": state, "consecutive_failures": streak}]}}


def test_one_failed_collection_of_an_outside_site_is_not_an_alert():
    """2026-10-23: TangoNOW answered HTTP 500 for one run and was fine on the next."""
    once = _facts(sources=_source("SRC-W-002", "DEGRADED", 1))
    seen, _ = _run([once] * 12 + [_facts()])
    assert all(notices == [] for notices in seen)


def test_repeated_source_failures_alert_as_a_source_problem_not_an_outage():
    twice = _facts(sources=_source("SRC-W-002", "DEGRADED", 2))
    seen, _ = _run([twice, twice, _facts()])
    assert [(n["kind"], n["key"], n["severity"]) for n in seen[0]] == [
        ("ALERT", "SOURCE_DEGRADED:SRC-W-002", ops_alerts.WARNING)]
    assert seen[1] == [] and seen[2][0]["kind"] == "RECOVERED"


def test_backup_disk_jobs_and_extraction_are_watched():
    facts = _facts(status=_status(backup="FAIL"), disk_free_pct=4.0,
                   db={"job_failure_streaks": {"source-collection": 3, "engine-reprocess": 2},
                       "reextract": {"stalled": 1}, "normalization": {"failed": 0}})
    seen, _ = _run([facts, facts, facts])
    keys = {n["key"] for notices in seen for n in notices}
    assert keys == {"BACKUP_FAILED", "DISK_CRITICAL", "JOB_FAILED:source-collection",
                    "EXTRACTION_FAILING"}


def test_external_delivery_is_reported_pending_not_assumed():
    assert ops_alerts.delivery_status({"ANYTHING": "x"}) == ops_alerts.DELIVERY_PENDING


def test_the_command_writes_the_log_and_state_and_exits_on_critical(tmp_path):
    state, log = tmp_path / "state.json", tmp_path / "alerts.log"
    status = tmp_path / "status.json"
    status.write_text(json.dumps(_status(database="FAIL")), encoding="utf-8")
    args = ["--state", str(state), "--log", str(log), "--status-file", str(status),
            "--runtime-running", "1", "--scheduler-count", "1", "--disk-free-pct", "50"]
    assert ops_alerts.main(args) == 0          # first sighting: below threshold
    assert ops_alerts.main(args) == 1          # second: an open critical alert
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [x["key"] for x in lines] == ["DATABASE_FAILED"]
    assert json.loads(state.read_text(encoding="utf-8"))["alerts"]["DATABASE_FAILED"]["open"]


def test_ops_alerts_needs_only_the_standard_library():
    """It runs with the host's python3 exactly when the runtime may be down."""
    import ast

    tree = ast.parse((REPO / "runtime" / "ops_alerts.py").read_text(encoding="utf-8"))
    modules = {alias.name.split(".")[0] for node in ast.walk(tree)
               if isinstance(node, ast.Import) for alias in node.names}
    modules |= {node.module.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    # v0.96.52: urllib (standard library) posts to the optional webhook.
    assert modules <= {"__future__", "argparse", "json", "os", "sys", "datetime", "typing",
                       "urllib"}


MONITOR_SH = (REPO / "scripts" / "ops-monitor.sh").read_text(encoding="utf-8")


def test_the_monitor_reads_readiness_and_never_starts_anything():
    assert '"$URL/status"' in MONITOR_SH and '"$URL/health/sources"' in MONITOR_SH
    assert '"$URL/health"' not in MONITOR_SH
    for verb in ("compose up", "compose start", "compose restart", "docker run",
                 "python -m scheduler"):
        assert verb not in MONITOR_SH
    assert "guard_not_root" in MONITOR_SH and "flock -n 9" in MONITOR_SH


# --- Part C: the board's units ------------------------------------------------------

UNITS = REPO / "deploy" / "rockpro64" / "systemd"


def _unit(name):
    return (UNITS / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("service,script", [
    ("dancemate-backup.service", "scripts/backup.sh"),
    ("dancemate-ops-monitor.service", "scripts/ops-monitor.sh"),
])
def test_each_service_runs_one_script_as_the_repository_owner(service, script):
    text = _unit(service)
    assert "User=hammer" in text and "Type=oneshot" in text
    assert f"ExecStart=/opt/dancemate/app/DanceMate/{script}" in text
    assert "scheduler" not in text.split("[Service]")[1].lower()


def test_the_backup_runs_daily_and_catches_up_and_the_check_every_five_minutes():
    backup = _unit("dancemate-backup.timer")
    assert "OnCalendar=*-*-* 04:30:00" in backup and "Persistent=true" in backup
    monitor = _unit("dancemate-ops-monitor.timer")
    assert "OnUnitActiveSec=5min" in monitor
