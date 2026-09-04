"""Deployment configuration guards (spec items 12, 14, 15).

These are static assertions about the files an operator will carry to the
ROCKPro64. They prove the configuration is right; they do not prove the stack
has been run on ARM64 hardware.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from runtime import target

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
OPERATIONS_SCRIPTS = [
    "install-rockpro64.sh",
    "start-server.sh",
    "stop-server.sh",
    "check-server.sh",
    "backup.sh",
    "restore.sh",
]


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")


# --- ARM64 (spec item 12) ---------------------------------------------------

def test_dockerfile_is_statically_arm64_compatible():
    report = target.dockerfile_arm64_report()
    assert report["status"] == "PASS", report["detail"]


def test_base_images_are_pinned_to_a_multiarch_tag(dockerfile):
    assert target.FROM_LINE.findall(dockerfile) == ["python:3.12-slim"]


def test_engine_python_floor_is_respected_by_the_base_image(dockerfile):
    """Engine v0.73 evaluates `str | None` annotations at import: needs >= 3.10."""
    match = re.search(r"FROM python:(\d+)\.(\d+)", dockerfile)
    assert match, "runtime image must be built on an official python tag"
    assert (int(match.group(1)), int(match.group(2))) >= (3, 10)


def test_arm64_helper_recognises_the_deployment_target():
    assert "aarch64" in target.TARGET_ARCHITECTURES
    assert "arm64" in target.TARGET_ARCHITECTURES
    assert target.current_architecture() == target.current_architecture().lower()


def test_x86_pin_is_detected(tmp_path):
    pinned = tmp_path / "Dockerfile"
    pinned.write_text("FROM python:3.12-slim\nRUN dpkg --add-architecture amd64\n", encoding="utf-8")
    assert target.dockerfile_arm64_report(pinned)["status"] == "FAIL"


def test_missing_dockerfile_is_reported_not_assumed(tmp_path):
    assert target.dockerfile_arm64_report(tmp_path / "nope")["status"] == "FAIL"


# --- restart safety (spec item 14) ------------------------------------------

def test_every_service_restarts_after_a_host_reboot(compose):
    for name, service in compose["services"].items():
        assert service.get("restart") == "unless-stopped", f"{name} has no restart policy"


def test_exactly_three_services_are_defined(compose):
    assert sorted(compose["services"]) == ["postgres", "runtime", "scheduler"]


def test_runtime_and_scheduler_share_one_image(compose):
    assert compose["services"]["runtime"]["image"] == compose["services"]["scheduler"]["image"]


def test_postgres_has_a_healthcheck_and_dependants_wait_for_it(compose):
    assert "healthcheck" in compose["services"]["postgres"]
    for dependant in ("runtime", "scheduler"):
        condition = compose["services"][dependant]["depends_on"]["postgres"]["condition"]
        assert condition == "service_healthy"


def test_scheduler_waits_for_the_runtime_so_migrations_do_not_race(compose):
    condition = compose["services"]["scheduler"]["depends_on"]["runtime"]["condition"]
    assert condition == "service_healthy"


def test_persistent_state_is_mounted_not_left_in_the_container(compose):
    postgres_mounts = compose["services"]["postgres"]["volumes"]
    assert any("/var/lib/postgresql/data" in m for m in postgres_mounts)
    for service in ("runtime", "scheduler"):
        mounts = compose["services"][service]["volumes"]
        assert any(m.endswith(":/app/engine/data") for m in mounts), service


def test_container_logs_are_size_capped_for_the_microsd(compose):
    for name, service in compose["services"].items():
        options = service.get("logging", {}).get("options", {})
        assert options.get("max-size"), f"{name} has no log max-size"
        assert options.get("max-file"), f"{name} has no log max-file"


def test_postgres_is_not_published_on_the_host(compose):
    assert "ports" not in compose["services"]["postgres"]


def test_the_runtime_port_binding_is_configurable_for_lan_only(compose):
    ports = compose["services"]["runtime"]["ports"]
    assert ports == ["${DANCEMATE_BIND_ADDRESS:-0.0.0.0}:${DANCEMATE_PORT:-8080}:8080"]


def test_scheduler_gets_time_to_drain_on_stop(compose):
    assert compose["services"]["scheduler"]["stop_grace_period"] == "45s"


def test_container_paths_are_pinned_and_not_taken_from_the_env_file(compose):
    for service in ("runtime", "scheduler"):
        environment = compose["services"][service]["environment"]
        assert environment["ENGINE_DATA_DIR"] == "/app/engine/data"
        assert environment["ENGINE_ROOT"] == "/app/engine"


# --- destructive-command guards (spec item 15) ------------------------------

def test_stop_script_never_removes_volumes():
    text = (SCRIPTS / "stop-server.sh").read_text(encoding="utf-8")
    assert "down -v" not in text
    assert "--volumes" not in text
    assert "compose down" in text


@pytest.mark.parametrize("script", OPERATIONS_SCRIPTS)
def test_no_operations_script_removes_volumes_or_prunes(script):
    text = (SCRIPTS / script).read_text(encoding="utf-8")
    for forbidden in ("down -v", "volume rm", "volume prune", "system prune"):
        assert forbidden not in text, f"{script} contains {forbidden!r}"


def test_restore_requires_an_explicit_confirmation():
    text = (SCRIPTS / "restore.sh").read_text(encoding="utf-8")
    assert "--yes" in text
    assert "DRY RUN" in text
    assert "no backup named" in text


def test_restore_takes_a_pre_restore_safety_copy():
    assert "pre-restore" in (SCRIPTS / "restore.sh").read_text(encoding="utf-8")


def test_installer_does_not_pipe_a_remote_script_into_a_shell():
    text = (SCRIPTS / "install-rockpro64.sh").read_text(encoding="utf-8")
    assert not re.search(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b", text)


# --- script hygiene ---------------------------------------------------------

@pytest.mark.parametrize("script", OPERATIONS_SCRIPTS)
def test_scripts_are_strict_bash(script):
    text = (SCRIPTS / script).read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")


def _require_git():
    """git is absent inside the runtime image; these checks belong to the repo."""
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git is not available here")
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not running from a git checkout")


@pytest.mark.parametrize("script", OPERATIONS_SCRIPTS + ["docker-entrypoint.sh"])
def test_scripts_are_executable_in_git(script):
    """git records mode 100755; the Windows working tree cannot be trusted."""
    _require_git()
    out = subprocess.run(
        ["git", "ls-files", "-s", f"scripts/{script}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out, f"scripts/{script} is not tracked by git"
    assert out.split()[0] == "100755", f"scripts/{script} is not executable in git: {out}"


@pytest.mark.parametrize("script", OPERATIONS_SCRIPTS + ["docker-entrypoint.sh", "_common.sh"])
def test_scripts_have_lf_endings_for_the_linux_target(script):
    assert b"\r\n" not in (SCRIPTS / script).read_bytes()


# --- environment template ---------------------------------------------------

def test_env_example_carries_no_real_secret():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=CHANGE_ME" in text
    assert "DANCEMATE_VERSION=0.77.3" in text


def test_env_is_git_ignored_but_the_template_is_not():
    _require_git()

    def ignored(path: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT).returncode == 0

    assert ignored(".env")
    assert not ignored(".env.example")


def test_version_file_tracks_the_product_runtime_not_the_engine():
    assert (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.77.3"


# --- listen address vs published address ------------------------------------

def test_container_listen_address_is_pinned_to_all_interfaces(compose):
    """A container has no LAN address: binding the host's IP inside it fails.

    Regression: DANCEMATE_BIND_ADDRESS was used both as the host publish
    interface and as uvicorn's listen address, so narrowing the published port
    to the board's wired IP made the runtime crash-loop with
    "could not bind on any address out of [('192.168.1.100', 8080)]".
    """
    for service in ("runtime", "scheduler"):
        assert compose["services"][service]["environment"]["DANCEMATE_HOST"] == "0.0.0.0"


def test_runtime_listens_on_dancemate_host_not_the_publish_address():
    source = (REPO_ROOT / "runtime" / "__main__.py").read_text(encoding="utf-8")
    assert "settings.listen_address" in source
    assert "bind_address" not in source

    config = (REPO_ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert 'listen_address=_env("DANCEMATE_HOST", "0.0.0.0")' in config
    assert "DANCEMATE_BIND_ADDRESS" not in config.split("@dataclass")[1], (
        "the application must not read the host publish address"
    )


def test_settings_expose_only_the_listen_address(env, monkeypatch):
    from runtime.config import Settings, load_settings

    monkeypatch.setenv("DANCEMATE_BIND_ADDRESS", "192.168.0.10")
    monkeypatch.setenv("DANCEMATE_HOST", "0.0.0.0")
    settings = load_settings()
    assert settings.listen_address == "0.0.0.0"
    assert not hasattr(settings, "bind_address")
    assert "bind_address" not in Settings.__dataclass_fields__


def test_blank_listen_address_falls_back_to_all_interfaces(env, monkeypatch):
    """An empty value must never leave the server with nothing to bind to."""
    from runtime.config import load_settings

    monkeypatch.setenv("DANCEMATE_HOST", "")
    assert load_settings().listen_address == "0.0.0.0"
