"""v0.96.53 - OPS-05: a container of the scheduler image is not a scheduler.

`docker compose build` writes the service label into the image it builds, so
dancemate/runtime:0.96.52 itself carries com.docker.compose.service=scheduler
and every container anyone runs from it inherits that label. The official test
runner's migrate-and-pytest container was counted as a second scheduler and
ops-monitor raised SCHEDULER_DUPLICATE (CRITICAL) from 19:43 to 20:34 on
2026-10-23 with one scheduler running. Compose writes two more labels when it
creates a service replica - container-number and oneoff=False - and an image
never carries them, so the label signal now requires both; the command signal
is unchanged and still finds a scheduler started any other way.

The decision is held three ways: the Python mirror (`deploy_guard`), the bash
itself against a stub `docker` that answers from a list of containers, and the
alert policy those counts feed (`ops_alerts`), which is unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runtime import deploy_guard, ops_alerts

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"

IMAGE_LABELS = {  # what dancemate/runtime:0.96.52 carries, as inspected on the board
    "com.docker.compose.project": "dancemate",
    "com.docker.compose.service": "scheduler",
    "com.docker.compose.version": "5.5.0",
    "org.opencontainers.image.revision": "4a31e78130051286870bf10b5b20bafe04a6c9ee",
}


def replica(cid, service="scheduler", project="dancemate", oneoff="False", command=None):
    labels = dict(IMAGE_LABELS, **{
        "com.docker.compose.project": project,
        "com.docker.compose.service": service,
        "com.docker.compose.container-number": "1",
        "com.docker.compose.oneoff": oneoff,
    })
    cmd = command or ("/usr/local/bin/docker-entrypoint.sh python -m "
                      + ("scheduler" if service == "scheduler" else "runtime"))
    return {"id": cid, "labels": labels, "command": cmd, "running": True}


def adhoc(cid, command):
    """`docker run <image> ...`: the image's labels and nothing compose adds."""
    return {"id": cid, "labels": dict(IMAGE_LABELS), "command": command, "running": True}


A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64

RUNNER = adhoc(C, "/usr/local/bin/docker-entrypoint.sh sh -c 'python -m runtime.migrate && "
                  "python -m pytest -q tests'")

SCENARIOS = {
    "one production scheduler": ([replica(A), replica(B, service="runtime")], 1),
    "one scheduler + the official test runner": (
        [replica(A), replica(B, service="runtime"), RUNNER], 1),
    "one scheduler + an ad-hoc migrate container": (
        [replica(A), adhoc(D, "/usr/local/bin/docker-entrypoint.sh python -m runtime.migrate")], 1),
    "one scheduler + a compose one-off on the scheduler service": (
        [replica(A), replica(D, oneoff="True",
                             command="/usr/local/bin/docker-entrypoint.sh python -m runtime.migrate")],
        1),
    "two production schedulers": ([replica(A), replica(D)], 2),
    "a second stack under another project": ([replica(A), replica(D, project="dm-other")], 2),
    "a scheduler started by hand from the image": (
        [replica(A), adhoc(D, "/usr/local/bin/docker-entrypoint.sh python -m scheduler")], 2),
    "no scheduler": ([replica(B, service="runtime"), RUNNER], 0),
    "a stopped old scheduler beside its replacement": (
        [dict(replica(A), running=False), replica(D)], 1),
    "both old and new running during a replacement": ([replica(A), replica(D)], 2),
}


def _python_count(containers):
    running = [c for c in containers if c["running"]]
    ids = [c["id"] for c in running if deploy_guard.is_scheduler_container(c["labels"], c["command"])]
    return deploy_guard.scheduler_count_report(ids, [])["count"]


# --- the decision, in Python -------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_python_mirror_counts_each_scenario(name):
    containers, expected = SCENARIOS[name]
    assert _python_count(containers) == expected


def test_the_image_label_alone_is_not_a_scheduler():
    assert not deploy_guard.is_scheduler_container(IMAGE_LABELS, "python -m pytest")
    assert deploy_guard.is_scheduler_container(IMAGE_LABELS, "python -m scheduler")


def test_the_script_and_the_python_agree_on_the_replica_labels():
    text = (SCRIPTS / "_common.sh").read_text(encoding="utf-8")
    assert f'SCHEDULER_REPLICA_LABEL="{deploy_guard.SCHEDULER_REPLICA_LABEL}"' in text
    assert f'SCHEDULER_NOT_ONEOFF_LABEL="{deploy_guard.SCHEDULER_NOT_ONEOFF_LABEL}"' in text
    guard = text.split("scheduler_container_ids() {", 1)[1].split("\n}", 1)[0]
    for label in ("$SCHEDULER_SERVICE_LABEL", "$SCHEDULER_REPLICA_LABEL",
                  "$SCHEDULER_NOT_ONEOFF_LABEL"):
        assert f'--filter "label={label}"' in guard
    # The command signal is still there, unchanged.
    assert "awk -v want=\"$SCHEDULER_COMMAND\"" in guard


# --- the alert policy those counts feed --------------------------------------------

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
HEALTHY = {"status": {"overall": "PASS"}, "runtime_running": True}


def _facts(count):
    return dict(HEALTHY, scheduler_count=count)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_each_scenario_raises_exactly_the_alert_it_should(name):
    containers, expected = SCENARIOS[name]
    found = ops_alerts.conditions(_facts(_python_count(containers)))
    if expected > 1:
        assert found["SCHEDULER_DUPLICATE"]["severity"] == ops_alerts.CRITICAL
    else:
        assert "SCHEDULER_DUPLICATE" not in found
    assert ("SCHEDULER_MISSING" in found) == (expected == 0)


def test_the_test_runner_window_raises_nothing_any_more():
    """The 2026-10-23 19:43-20:34 window, tick by tick."""
    containers, _ = SCENARIOS["one scheduler + the official test runner"]
    state: dict = {}
    for minute in range(0, 55, 5):
        notices, state = ops_alerts.evaluate(_facts(_python_count(containers)), state,
                                             NOW + timedelta(minutes=minute))
        assert not [n for n in notices if n["key"].startswith("SCHEDULER")]


def test_a_real_duplicate_alerts_at_once_reminds_after_six_hours_and_recovers_once():
    duplicate = _facts(_python_count(SCENARIOS["two production schedulers"][0]))
    notices, state = ops_alerts.evaluate(duplicate, {}, NOW)
    assert [(n["kind"], n["key"], n["severity"]) for n in notices] == [
        (ops_alerts.ALERT, "SCHEDULER_DUPLICATE", ops_alerts.CRITICAL)]
    for minute in range(5, 360, 5):
        notices, state = ops_alerts.evaluate(duplicate, state, NOW + timedelta(minutes=minute))
        assert notices == []
    notices, state = ops_alerts.evaluate(duplicate, state, NOW + timedelta(hours=6))
    assert [n["kind"] for n in notices] == [ops_alerts.REMINDER]
    healthy = _facts(1)
    notices, state = ops_alerts.evaluate(healthy, state, NOW + timedelta(hours=6, minutes=5))
    assert [n["kind"] for n in notices] == [ops_alerts.RECOVERED]
    notices, state = ops_alerts.evaluate(healthy, state, NOW + timedelta(hours=6, minutes=10))
    assert notices == []


def test_no_scheduler_is_still_critical_after_its_threshold():
    state: dict = {}
    kinds = []
    for minute in (0, 5):
        notices, state = ops_alerts.evaluate(_facts(0), state, NOW + timedelta(minutes=minute))
        kinds += [(n["kind"], n["key"], n["severity"]) for n in notices]
    assert kinds == [(ops_alerts.ALERT, "SCHEDULER_MISSING", ops_alerts.CRITICAL)]


# --- the bash itself, against a stub docker ----------------------------------------

STUB = r'''#!/usr/bin/env python3
"""docker ps, answered from $STUB_CONTAINERS (running containers only)."""
import json, os, sys
args = sys.argv[1:]
if not args or args[0] != "ps":
    sys.exit(0)
containers = [c for c in json.loads(os.environ.get("STUB_CONTAINERS", "[]")) if c["running"]]
filters, fmt, quiet, i = [], None, False, 1
while i < len(args):
    a = args[i]
    if a == "--filter":
        filters.append(args[i + 1]); i += 2; continue
    if a == "--format":
        fmt = args[i + 1]; i += 2; continue
    if a == "-q":
        quiet = True
    i += 1
def keep(c):
    for f in filters:
        kind, _, spec = f.partition("=")
        key, _, value = spec.partition("=")
        if kind != "label" or key not in c["labels"] or (value and c["labels"][key] != value):
            return False
    return True
for c in filter(keep, containers):
    if quiet:
        print(c["id"])
    elif fmt == "{{.ID}} {{.Command}}":
        print(c["id"][:12], '"' + c["command"] + '"')
'''


@pytest.fixture
def stub_bash(tmp_path):
    if sys.platform == "win32" or shutil.which("bash") is None or shutil.which("python3") is None:
        pytest.skip("needs a POSIX bash (runs inside the runtime container)")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)

    def run(snippet: str, containers):
        env = dict(os.environ, PATH=f"{bindir}:{os.environ.get('PATH', '')}",
                   STUB_CONTAINERS=json.dumps(containers))
        return subprocess.run(["bash", "-c", f"source scripts/_common.sh; {snippet}"],
                              cwd=REPO, env=env, capture_output=True, text=True)

    return run


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_bash_counts_each_scenario(stub_bash, name):
    containers, expected = SCENARIOS[name]
    result = stub_bash("count_scheduler_containers", containers)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)


def test_the_deploy_guard_still_stops_a_real_duplicate(stub_bash):
    ok = stub_bash("guard_no_duplicate_scheduler",
                   SCENARIOS["one scheduler + the official test runner"][0])
    assert ok.returncode == 0, ok.stderr
    assert "scheduler guard: 1 scheduler container(s) running" in ok.stdout
    two = stub_bash("guard_no_duplicate_scheduler", SCENARIOS["two production schedulers"][0])
    assert two.returncode != 0
    assert "duplicate scheduler guard failed: 2" in two.stderr
