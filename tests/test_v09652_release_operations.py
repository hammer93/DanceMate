"""v0.96.52 release operations: backup provenance, alert delivery, off-host copy.

* A backup names the commit that wrote its snapshot - the running image's
  label, else the running version's release tag, else UNKNOWN - and records
  the checkout's HEAD only as the candidate. v0.96.51's recovery showed the
  defect: a same-version redeploy before its tag labelled the pre-deploy
  backup with the commit being deployed.
* Every alert notice says what happened to it outside the board:
  NOT_CONFIGURED, DELIVERED or DELIVERY_FAILED (retried next run).
* The off-host copy is PENDING_CONFIGURATION until an operator names another
  host and a public key; a local destination is refused.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from runtime import backup_provenance as BP
from runtime import backup_state, ops_alerts

REPO = Path(__file__).resolve().parents[1]
BACKUP_SH = (REPO / "scripts" / "backup.sh").read_text(encoding="utf-8")
DEPLOY_SH = (REPO / "scripts" / "deploy-production.sh").read_text(encoding="utf-8")
OFFHOST_SH = (REPO / "scripts" / "offhost-backup.sh").read_text(encoding="utf-8")
MONITOR_SH = (REPO / "scripts" / "ops-monitor.sh").read_text(encoding="utf-8")
OLD = "1c012c31c7d1465dee86ca5b4811bd37e40175ee"
NEW = "06c46cb972ff61980b3415b995e95aa4fefaf284"
CANDIDATE = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
NOON = datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)


# --- backup provenance ----------------------------------------------------------------

def test_same_version_different_commit_pre_deploy_names_the_running_commit():
    """v0.96.51's recovery: running 1c012c3 (0.96.51, no tag yet), checkout
    06c46cb (also 0.96.51). The old rule wrote 06c46cb; the label says 1c012c3."""
    fields = BP.resolve(label=OLD, running_version="0.96.51", tag_commit="", head=NEW,
                        checkout_version="0.96.51", now=NOON)
    assert fields["RUNNING_COMMIT"] == OLD
    assert fields["RUNNING_COMMIT_SOURCE"] == BP.SOURCE_IMAGE_LABEL
    assert fields["CANDIDATE_COMMIT"] == NEW
    assert fields["SNAPSHOT_TIME_KST"] == "2026-10-23T12:00:00+09:00"


def test_an_unlabelled_untagged_running_image_is_unknown_never_head():
    fields = BP.resolve(label="unknown", running_version="0.96.51", tag_commit="",
                        head=NEW, checkout_version="0.96.51")
    assert fields["RUNNING_COMMIT"] == BP.UNKNOWN
    assert fields["RUNNING_COMMIT_SOURCE"] == BP.SOURCE_UNKNOWN
    assert fields["CANDIDATE_COMMIT"] == NEW


def test_an_unlabelled_image_of_a_tagged_release_uses_the_tag():
    """Images built before v0.96.52 carry no label: the running version's tag."""
    fields = BP.resolve(label="", running_version="0.96.51", tag_commit=NEW,
                        head=CANDIDATE, checkout_version="0.96.52")
    assert (fields["RUNNING_COMMIT"], fields["RUNNING_COMMIT_SOURCE"]) == \
        (NEW, BP.SOURCE_RELEASE_TAG)
    assert (fields["CANDIDATE_COMMIT"], fields["CANDIDATE_VERSION"]) == (CANDIDATE, "0.96.52")


def test_post_deploy_backup_names_the_new_commit_from_its_label():
    fields = BP.resolve(label=CANDIDATE, running_version="0.96.52", tag_commit="",
                        head=CANDIDATE, checkout_version="0.96.52")
    assert fields["RUNNING_COMMIT"] == fields["CANDIDATE_COMMIT"] == CANDIDATE


def test_a_rollback_backup_names_the_older_image_not_the_checkout():
    fields = BP.resolve(label=NEW, running_version="0.96.51", tag_commit=NEW,
                        head=CANDIDATE, checkout_version="0.96.52")
    assert fields["RUNNING_COMMIT"] == NEW and fields["CANDIDATE_COMMIT"] == CANDIDATE


def test_missing_git_metadata_is_unknown():
    """A checkout without .git (or git missing): no tag, no HEAD."""
    fields = BP.resolve(label="", running_version="0.96.52", tag_commit="", head="",
                        checkout_version="")
    assert fields["RUNNING_COMMIT"] == fields["CANDIDATE_COMMIT"] == BP.UNKNOWN
    assert fields["CANDIDATE_VERSION"] == BP.UNKNOWN


@pytest.mark.parametrize("junk", ["not-a-sha", "06c46cb", "x" * 40, "$(reboot)", "a;b"])
def test_junk_is_never_recorded_as_a_commit(junk):
    fields = BP.resolve(label=junk, running_version="0.96.52", tag_commit=junk, head=junk,
                        checkout_version="0.96.52; rm")
    assert fields["RUNNING_COMMIT"] == fields["CANDIDATE_COMMIT"] == BP.UNKNOWN
    assert fields["CANDIDATE_VERSION"] == BP.UNKNOWN


def test_the_command_prints_shell_safe_key_value_lines(capsys):
    assert BP.main(["--label", OLD, "--running-version", "0.96.51", "--head", NEW,
                    "--checkout-version", "0.96.51"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    keys = [line.split("=", 1)[0] for line in lines]
    assert keys == ["RUNNING_COMMIT", "RUNNING_COMMIT_SOURCE", "CANDIDATE_COMMIT",
                    "CANDIDATE_VERSION", "SNAPSHOT_TIME_KST"]
    for line in lines:
        assert all(c.isalnum() or c in "=_.:+-" for c in line), line


def test_backup_provenance_is_stdlib_only():
    import ast

    tree = ast.parse((REPO / "runtime" / "backup_provenance.py").read_text(encoding="utf-8"))
    imported = {(n.module or "").split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)} | {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
        for a in n.names}
    assert imported <= {"__future__", "argparse", "re", "datetime"}, imported


def test_backup_sh_never_takes_head_as_the_running_commit():
    assert "RUNTIME_COMMIT=\"$HEAD_COMMIT\"" not in BACKUP_SH
    assert "python3 -m runtime.backup_provenance" in BACKUP_SH
    assert 'org.opencontainers.image.revision' in BACKUP_SH
    for field in ('"product_commit": "$RUNNING_COMMIT"', '"running_commit_source"',
                  '"candidate_commit"', '"candidate_version"', '"snapshot_time_kst"'):
        assert field in BACKUP_SH, field


def test_the_image_is_labelled_with_the_commit_it_was_built_from():
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG DANCEMATE_COMMIT=unknown" in dockerfile
    assert "LABEL org.opencontainers.image.revision=$DANCEMATE_COMMIT" in dockerfile
    for compose in ("docker-compose.yml", "deploy/rockpro64/docker-compose.external-postgres.yml"):
        assert "DANCEMATE_COMMIT: ${DANCEMATE_COMMIT:-unknown}" in \
            (REPO / compose).read_text(encoding="utf-8"), compose
    assert 'DANCEMATE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"' in DEPLOY_SH
    assert "export DANCEMATE_COMMIT" in DEPLOY_SH
    # The build guard refuses an image whose label is not the checkout.
    assert '[[ "$BUILT_COMMIT" == "$DANCEMATE_COMMIT" ]]' in DEPLOY_SH
    assert DEPLOY_SH.index("export DANCEMATE_COMMIT") < DEPLOY_SH.index("compose build ||")


def test_old_and_new_manifests_both_read_as_complete(settings):
    """The status reader ignores provenance fields it does not know, and a
    manifest without them (every backup before v0.96.52) still passes."""
    for name, extra in (("dancemate-backup-20261023-020000", {}),
                        ("dancemate-backup-20261023-030000", {
                            "running_commit_source": "image-label",
                            "candidate_commit": CANDIDATE, "candidate_version": "0.96.52",
                            "snapshot_time_kst": "2026-10-23T12:00:00+09:00"})):
        target = settings.backup_dir / name
        target.mkdir()
        (target / "postgres.dump").write_bytes(b"dump")
        (target / "engine.sqlite3").write_bytes(b"sqlite")
        (target / "manifest.json").write_text(json.dumps({
            "product_commit": BP.UNKNOWN, "postgres": {"status": "ok", "bytes": 4},
            "engine_sqlite": {"status": "ok", "bytes": 6}, "complete": True, **extra}),
            encoding="utf-8")
        assert backup_state.inspect(target) is None, name


# --- alert delivery -----------------------------------------------------------------

def _notice(kind=ops_alerts.ALERT, key="BACKUP_FAILED"):
    return {"at_kst": "2026-10-23T12:00:00+09:00", "kind": kind, "key": key,
            "severity": ops_alerts.CRITICAL, "message": "backup FAIL",
            "since_kst": "2026-10-23T12:00:00+09:00"}


def test_no_channel_means_not_configured_and_pending_configuration():
    assert ops_alerts.delivery_status({}) == ops_alerts.DELIVERY_PENDING
    assert ops_alerts.deliver([_notice(), _notice(ops_alerts.RECOVERED)], None) == \
        [ops_alerts.NOT_CONFIGURED, ops_alerts.NOT_CONFIGURED]


@pytest.mark.parametrize("url,expected", [
    ("https://hooks.example/abc", ops_alerts.DELIVERY_CONFIGURED),
    ("http://127.0.0.1:9/hook", ops_alerts.DELIVERY_CONFIGURED),
    ("http://hooks.example/abc", ops_alerts.DELIVERY_INVALID),       # plain HTTP off-box
    ("ftp://hooks.example/abc", ops_alerts.DELIVERY_INVALID),
    ("hooks.example", ops_alerts.DELIVERY_INVALID),
])
def test_only_https_or_a_local_relay_is_accepted(url, expected):
    assert ops_alerts.delivery_status({ops_alerts.WEBHOOK_ENV: url}) == expected


def test_a_delivered_and_a_failed_notice_are_told_apart():
    sent = []

    def post(url, body):
        sent.append(json.loads(body))
        if len(sent) == 2:
            raise OSError("HTTP 500")

    outcomes = ops_alerts.deliver([_notice(), _notice(key="DISK_CRITICAL")],
                                  "https://hooks.example/x", post=post)
    assert outcomes == [ops_alerts.DELIVERED, ops_alerts.DELIVERY_FAILED]
    assert sent[0]["notice"]["key"] == "BACKUP_FAILED"
    assert "[DanceMate ALERT CRITICAL] BACKUP_FAILED" in sent[0]["text"]


class _Hook(BaseHTTPRequestHandler):
    received: list = []
    status = 200

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        type(self).received.append(json.loads(self.rfile.read(length)))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args):  # noqa: D401 - silence
        pass


@pytest.fixture
def hook():
    _Hook.received = []
    _Hook.status = 200
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/hook", _Hook
    server.shutdown()


def _status_file(tmp_path, backup="FAIL"):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({
        "status": backup, **{c: {"status": "PASS"} for c in
                             ("runtime", "database", "scheduler", "information", "storage")},
        "backup": {"status": backup, "reason": "BACKUP_PERMISSION_DENIED",
                   "detail": "synthetic"}}), encoding="utf-8")
    return str(path)


def _run(tmp_path, monkeypatch, url, backup):
    if url is None:
        monkeypatch.delenv(ops_alerts.WEBHOOK_ENV, raising=False)
    else:
        monkeypatch.setenv(ops_alerts.WEBHOOK_ENV, url)
    return ops_alerts.main(["--state", str(tmp_path / "state.json"),
                            "--log", str(tmp_path / "alerts.log"),
                            "--status-file", _status_file(tmp_path, backup),
                            "--runtime-running", "1", "--scheduler-count", "1",
                            "--disk-free-pct", "70"])


def _log(tmp_path):
    return [json.loads(line) for line in
            (tmp_path / "alerts.log").read_text(encoding="utf-8").splitlines()]


def test_detect_deliver_dedupe_recover_end_to_end(tmp_path, monkeypatch, hook, capsys):
    url, handler = hook
    assert _run(tmp_path, monkeypatch, url, "FAIL") == 1             # detected, delivered
    assert _run(tmp_path, monkeypatch, url, "FAIL") == 1             # deduplicated
    assert _run(tmp_path, monkeypatch, url, "PASS") == 0             # recovered, once
    log = _log(tmp_path)
    assert [(n["kind"], n["delivery"]) for n in log] == [
        (ops_alerts.ALERT, ops_alerts.DELIVERED), (ops_alerts.RECOVERED, ops_alerts.DELIVERED)]
    assert [m["notice"]["kind"] for m in handler.received] == [ops_alerts.ALERT,
                                                                ops_alerts.RECOVERED]
    out = capsys.readouterr().out
    assert url not in out and url not in (tmp_path / "alerts.log").read_text(encoding="utf-8")
    assert url not in (tmp_path / "state.json").read_text(encoding="utf-8")


def test_a_failed_delivery_is_queued_and_retried_next_run(tmp_path, monkeypatch, hook):
    url, handler = hook
    handler.status = 500
    _run(tmp_path, monkeypatch, url, "FAIL")
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert [n["key"] for n in state["undelivered"]] == ["BACKUP_FAILED"]
    assert _log(tmp_path)[-1]["delivery"] == ops_alerts.DELIVERY_FAILED
    handler.status = 200
    _run(tmp_path, monkeypatch, url, "FAIL")
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["undelivered"] == []
    retry = _log(tmp_path)[-1]
    assert (retry["kind"], retry["delivery"]) == ("DELIVERY_RETRY", ops_alerts.DELIVERED)


def test_without_a_channel_every_notice_says_not_configured(tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch, None, "FAIL")
    assert _log(tmp_path)[0]["delivery"] == ops_alerts.NOT_CONFIGURED
    assert "external delivery PENDING_CONFIGURATION" in capsys.readouterr().out
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["undelivered"] == [], "nothing is queued for a channel that does not exist"


def test_pending_conditions_are_listed_before_their_threshold():
    facts = {"runtime_running": True, "status": None, "scheduler_count": 1}
    assert ops_alerts.pending_conditions(facts, {}) == ["RUNTIME_UNAVAILABLE (0/2)"]


@pytest.mark.parametrize("facts,key", [
    ({"runtime_running": False, "status": None}, "RUNTIME_UNAVAILABLE"),
    ({"runtime_running": True, "status": {"database": {"status": "FAIL"}}}, "DATABASE_FAILED"),
    ({"runtime_running": True, "status": {"scheduler": {"status": "FAIL"}},
      "scheduler_count": 1}, "SCHEDULER_MISSING"),
    ({"runtime_running": True, "status": {"backup": {"status": "FAIL"}}}, "BACKUP_FAILED"),
    ({"runtime_running": True, "status": {}, "disk_free_pct": 5.0}, "DISK_CRITICAL"),
    ({"runtime_running": True, "status": {}, "sources": {"sources": {"not_collecting": [
        {"source_key": "SRC-W-002", "name": "TangoNOW", "state": "DEGRADED",
         "consecutive_failures": 2}]}}}, "SOURCE_DEGRADED:SRC-W-002"),
    ({"runtime_running": True, "status": {}, "sources": {"sources": {"not_collecting": [
        {"source_key": "SRC-W-005", "name": "Miltang", "state": "FAILED",
         "consecutive_failures": 3}]}}}, "SOURCE_FAILED:SRC-W-005"),
])
def test_every_monitored_failure_is_detected(facts, key):
    assert key in ops_alerts.conditions(facts)


def test_the_monitor_hands_the_webhook_over_in_the_environment_only():
    assert 'OPS_ALERT_WEBHOOK_URL="$(env_value OPS_ALERT_WEBHOOK_URL || true)"' in MONITOR_SH
    assert "--webhook" not in MONITOR_SH


# --- off-host backup -------------------------------------------------------------------

def _offhost(tmp_path, env_lines):
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    for name in ("offhost-backup.sh", "_common.sh"):
        shutil.copy(REPO / "scripts" / name, scripts / name)
    (tmp_path / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8",
                                   newline="\n")
    done = subprocess.run(["bash", str(scripts / "offhost-backup.sh"), "--check"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=60,
                          env={**os.environ, "GNUPGHOME": str(tmp_path / "gnupg")})
    return done.returncode, done.stdout + done.stderr


needs_bash = pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                                reason="needs a POSIX bash (on Windows `bash` may be WSL's)")


@needs_bash
def test_offhost_is_pending_configuration_by_default(tmp_path):
    code, out = _offhost(tmp_path, ["DANCEMATE_VERSION=0.96.52"])
    assert code == 3 and "PENDING_CONFIGURATION" in out


@needs_bash
@pytest.mark.parametrize("dest,why", [
    ("/srv/backups", "not off-host"),                         # a local folder
    ("../backups", "not off-host"),
    ("rsync://host/module", "not off-host"),
    ("hammer@localhost:/srv/x", "points at this machine"),
    ("hammer@127.0.0.1:/srv/x", "points at this machine"),
])
def test_a_destination_on_this_machine_is_refused(tmp_path, dest, why):
    code, out = _offhost(tmp_path, [f"OFFHOST_BACKUP_DEST={dest}",
                                    "OFFHOST_BACKUP_GPG_RECIPIENT=" + "A" * 40])
    assert code == 2 and "INVALID_CONFIGURATION" in out and why in out


@needs_bash
def test_nothing_leaves_unencrypted(tmp_path):
    code, out = _offhost(tmp_path, ["OFFHOST_BACKUP_DEST=backup@vault.example:/srv/dm"])
    assert code == 2 and "unencrypted" in out


def test_offhost_script_encrypts_verifies_and_never_counts_a_local_copy():
    for needle in ("gpg --batch --yes --trust-model always --recipient",
                   "--checksum --dry-run --itemize-changes",
                   "PENDING_CONFIGURATION", "a local path is not off-host",
                   "the PRIVATE key for", "offhost-last.json", 'record FAILED'):
        assert needle in OFFHOST_SH, needle
    assert "set -euo pipefail" in OFFHOST_SH
