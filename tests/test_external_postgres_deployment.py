"""The ROCKPro64 external-PostgreSQL deployment shape.

The board already runs a `dancemate-postgres` container on the `dancemate-net`
network, so its deployment brings up runtime + scheduler only. These tests keep
that second compose file honest and in step with the bundled one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED = REPO_ROOT / "docker-compose.yml"
EXTERNAL = REPO_ROOT / "deploy" / "rockpro64" / "docker-compose.external-postgres.yml"
COMMON = REPO_ROOT / "scripts" / "_common.sh"


@pytest.fixture(scope="module")
def external() -> dict:
    return yaml.safe_load(EXTERNAL.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bundled() -> dict:
    return yaml.safe_load(BUNDLED.read_text(encoding="utf-8"))


def test_external_compose_exists():
    assert EXTERNAL.is_file()


def test_external_compose_runs_runtime_and_scheduler_only(external):
    assert sorted(external["services"]) == ["runtime", "scheduler"]


def test_external_compose_defines_no_postgres_service(external):
    assert "postgres" not in external["services"]
    assert "volumes" not in external, "the board's PostgreSQL owns its own storage"


def test_external_compose_joins_the_existing_network(external):
    network = external["networks"]["dancemate-net"]
    assert network["external"] is True
    assert network["name"] == "${DANCEMATE_NETWORK:-dancemate-net}"
    for service in ("runtime", "scheduler"):
        assert external["services"][service]["networks"] == ["dancemate-net"]


def test_external_compose_points_at_the_existing_container(external):
    for service in ("runtime", "scheduler"):
        env = external["services"][service]["environment"]
        assert env["POSTGRES_HOST"] == "${POSTGRES_HOST:-dancemate-postgres}"


def test_external_compose_keeps_the_container_paths_pinned(external):
    for service in ("runtime", "scheduler"):
        env = external["services"][service]["environment"]
        assert env["ENGINE_ROOT"] == "/app/engine"
        assert env["ENGINE_DATA_DIR"] == "/app/engine/data"


def test_both_compose_files_agree_on_image_and_commands(bundled, external):
    for service in ("runtime", "scheduler"):
        assert external["services"][service]["image"] == bundled["services"][service]["image"]
        assert external["services"][service]["command"] == bundled["services"][service]["command"]


def test_both_compose_files_agree_on_restart_and_logging(bundled, external):
    for service in ("runtime", "scheduler"):
        assert external["services"][service]["restart"] == "unless-stopped"
        options = external["services"][service]["logging"]["options"]
        assert options == bundled["services"][service]["logging"]["options"]


def test_external_compose_persists_the_engine_store(external):
    for service in ("runtime", "scheduler"):
        mounts = external["services"][service]["volumes"]
        assert any(m.endswith(":/app/engine/data") for m in mounts), service


def test_external_compose_keeps_the_scheduler_behind_the_runtime(external):
    condition = external["services"]["scheduler"]["depends_on"]["runtime"]["condition"]
    assert condition == "service_healthy"
    assert external["services"]["scheduler"]["stop_grace_period"] == "45s"


def test_external_compose_binding_stays_configurable_for_lan_only(external):
    ports = external["services"]["runtime"]["ports"]
    assert ports == ["${DANCEMATE_BIND_ADDRESS:-0.0.0.0}:${DANCEMATE_PORT:-8080}:8080"]


# --- script wiring ----------------------------------------------------------

def test_scripts_select_the_compose_file_from_the_environment():
    text = COMMON.read_text(encoding="utf-8")
    assert "DANCEMATE_COMPOSE_FILE" in text
    assert 'configured="${configured:-docker-compose.yml}"' in text


def test_compose_always_runs_from_the_repository_root():
    """Relative paths in either compose file must resolve the same way."""
    text = COMMON.read_text(encoding="utf-8")
    assert '--project-directory "$REPO_ROOT"' in text


def test_postgres_container_falls_back_to_the_configured_name():
    text = COMMON.read_text(encoding="utf-8")
    assert "DANCEMATE_POSTGRES_CONTAINER" in text
    assert "compose ps -q postgres" in text


def test_backup_and_restore_go_through_pg_run():
    """So they work against a bundled or an external PostgreSQL alike."""
    for name in ("backup.sh", "restore.sh"):
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "compose exec -T postgres" not in text, name
        assert "pg_run pg_" in text, name


def test_env_example_documents_the_deployment_shape():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DANCEMATE_COMPOSE_FILE=docker-compose.yml" in text
    assert "deploy/rockpro64/docker-compose.external-postgres.yml" in text
    assert re.search(r"^#DANCEMATE_POSTGRES_CONTAINER=", text, re.MULTILINE)


def test_no_operations_script_removes_volumes_in_either_mode():
    for path in (REPO_ROOT / "scripts").glob("*.sh"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("down -v", "volume rm", "volume prune", "system prune"):
            assert forbidden not in text, f"{path.name} contains {forbidden!r}"


def test_start_script_waits_for_the_first_scheduler_heartbeat():
    """Otherwise check-server.sh right after a start reports a false FAIL."""
    text = (REPO_ROOT / "scripts" / "start-server.sh").read_text(encoding="utf-8")
    assert "DANCEMATE_START_TIMEOUT" in text
    assert "Scheduler .* FAIL" in text
    assert "did not become fully ready" in text


def _bash() -> str:
    """A bash that can actually run the scripts.

    On Windows the bare name resolves to WSL's bash, which has no interpreter
    inside the distro on this machine; Git Bash is the one that matters here.
    """
    import shutil
    import subprocess

    candidates = [shutil.which("bash"), r"C:\Program Files\Gitinash.exe"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "echo ok"], capture_output=True, text=True, timeout=30
            )
        except OSError:
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "ok":
            return candidate
    pytest.skip("no working bash available to exercise the shell helpers")


def _runtime_url(tmp_path: Path, env_lines: list[str]) -> str:
    """Actually run _common.sh's runtime_url() against a throwaway .env."""
    import shutil
    import subprocess

    bash = _bash()
    (tmp_path / "scripts").mkdir(exist_ok=True)
    shutil.copy(COMMON, tmp_path / "scripts" / "_common.sh")
    (tmp_path / ".env").write_text(
        "".join(line + chr(10) for line in env_lines), encoding="utf-8"
    )
    result = subprocess.run(
        [bash, "-c", 'source "$1/scripts/_common.sh"; runtime_url', "_", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize(
    "bind,expected",
    [
        ("0.0.0.0", "http://127.0.0.1:8080"),
        ("::", "http://127.0.0.1:8080"),
        ("192.168.0.10", "http://192.168.0.10:8080"),
    ],
)
def test_health_probe_follows_the_bind_address(tmp_path, bind, expected):
    """Binding to one LAN address stops loopback listening; the probe follows."""
    env = [f"DANCEMATE_BIND_ADDRESS={bind}", "DANCEMATE_PORT=8080"]
    assert _runtime_url(tmp_path, env) == expected


def test_health_probe_can_be_overridden_explicitly(tmp_path):
    env = [
        "DANCEMATE_BIND_ADDRESS=192.168.0.10",
        "DANCEMATE_PORT=9000",
        "DANCEMATE_HEALTH_HOST=10.0.0.5",
    ]
    assert _runtime_url(tmp_path, env) == "http://10.0.0.5:9000"


def test_health_probe_defaults_without_any_binding_configured(tmp_path):
    assert _runtime_url(tmp_path, ["DANCEMATE_PORT=8080"]) == "http://127.0.0.1:8080"


def test_env_example_documents_the_health_host():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "#DANCEMATE_HEALTH_HOST=127.0.0.1" in text


# --- acceptance tooling -----------------------------------------------------

ACCEPTANCE = REPO_ROOT / "deploy" / "rockpro64" / "acceptance_marker.py"


def test_acceptance_marker_tool_is_importable_and_compiles():
    import py_compile

    py_compile.compile(str(ACCEPTANCE), doraise=True)


def test_acceptance_marker_writes_to_both_stores():
    text = ACCEPTANCE.read_text(encoding="utf-8")
    # PostgreSQL through the runtime's own API, not raw SQL
    assert "db.set_runtime_state(" in text
    assert "db.get_runtime_state(" in text
    # SQLite through the engine's own service functions
    assert "register_generation" in text
    assert "resolve_generation" in text


def test_acceptance_marker_does_not_modify_engine_source():
    """It may seed upstream rows, but must not touch engine files or schema."""
    text = ACCEPTANCE.read_text(encoding="utf-8")
    for forbidden in ("DROP TABLE", "ALTER TABLE", "DELETE FROM", "open(", "write_text"):
        assert forbidden not in text, forbidden


def test_acceptance_marker_verify_reports_failure_not_success():
    text = ACCEPTANCE.read_text(encoding="utf-8")
    assert 'if args.action == "verify" and not result.get("ok"):' in text
    assert "return 1" in text
