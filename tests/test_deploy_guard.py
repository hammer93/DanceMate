"""Production compose-file guard (v0.82.6, "Deployment Guard").

v0.82.5's own release went fine; the incident was in how it was *deployed*.
A raw ``docker compose up -d``, run with no ``-f``, picked the repository
root's bundled-PostgreSQL ``docker-compose.yml`` instead of the board's real
``deploy/rockpro64/docker-compose.external-postgres.yml`` - a brand-new,
empty database silently took over the runtime/scheduler containers for a few
minutes before anyone noticed. No production data was lost (the real
``dancemate-postgres`` container, bind-mounted, was never touched), but
nothing in the repository would have *blocked* the wrong command from
running if the mistake had gone unnoticed longer.

These tests exercise ``runtime.deploy_guard`` as an isolated reproduction of
that incident: pass it the real local dev compose file (the one that was
accidentally selected) and it must FAIL; pass it the real production compose
file and it must PASS. Nothing here touches Docker or any live container -
these are the same static, file-shape checks `test_deployment_config.py`
already makes of `docker-compose.yml`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime import deploy_guard

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_COMPOSE = REPO_ROOT / deploy_guard.LOCAL_COMPOSE_PATH
PRODUCTION_COMPOSE = REPO_ROOT / deploy_guard.PRODUCTION_COMPOSE_PATH


# --- 1: production compose path is fixed, not guessed -----------------------

def test_the_production_compose_path_is_a_specific_file_not_a_pattern():
    assert deploy_guard.PRODUCTION_COMPOSE_PATH == (
        "deploy/rockpro64/docker-compose.external-postgres.yml"
    )


# --- 2: expected file exists -------------------------------------------------

def test_the_production_compose_file_exists():
    assert PRODUCTION_COMPOSE.is_file()


# --- 3: embedded postgres rejected ------------------------------------------

def test_the_real_production_compose_has_no_embedded_postgres():
    compose = deploy_guard.load_compose(PRODUCTION_COMPOSE)
    assert deploy_guard.check_no_embedded_postgres(compose)["status"] == "PASS"


def test_an_embedded_postgres_service_is_rejected():
    compose = {"services": {"postgres": {}, "runtime": {}, "scheduler": {}}}
    report = deploy_guard.check_no_embedded_postgres(compose)
    assert report["status"] == "FAIL"
    assert "postgres" in report["detail"]


# --- 5: the wrong compose file (this incident's actual mistake) is rejected -

def test_the_real_local_dev_compose_is_rejected_as_a_production_target():
    """This is the exact file the incident's raw `docker compose up -d`
    selected by accident - reproduced here without touching Docker."""
    report = deploy_guard.production_compose_report(LOCAL_COMPOSE)
    assert report["status"] == "FAIL"
    assert report["checks"]["no_embedded_postgres"]["status"] == "FAIL"


def test_the_real_production_compose_is_accepted():
    report = deploy_guard.production_compose_report(PRODUCTION_COMPOSE)
    assert report["status"] == "PASS"


def test_a_missing_compose_file_fails_rather_than_assuming():
    report = deploy_guard.production_compose_report(REPO_ROOT / "no-such-file.yml")
    assert report["status"] == "FAIL"
    assert "not found" in report["detail"]


def test_an_unparsable_compose_file_fails_rather_than_raising(tmp_path):
    bad = tmp_path / "broken.yml"
    bad.write_text("services: [this is not: valid: yaml", encoding="utf-8")
    report = deploy_guard.production_compose_report(bad)
    assert report["status"] == "FAIL"


# --- required services / project shape --------------------------------------

def test_exactly_runtime_and_scheduler_are_required():
    assert deploy_guard.check_required_services(
        {"services": {"runtime": {}, "scheduler": {}}}
    )["status"] == "PASS"
    assert deploy_guard.check_required_services(
        {"services": {"runtime": {}, "scheduler": {}, "caddy": {}}}
    )["status"] == "FAIL"


# --- external network / external postgres host -------------------------------

def test_an_internal_network_is_rejected():
    """No `external: true` means compose would create a fresh network of its
    own - exactly what isolated the runtime from the real database in the
    incident."""
    compose = {"services": {"runtime": {}, "scheduler": {}}, "networks": {"default": {}}}
    assert deploy_guard.check_external_network(compose)["status"] == "FAIL"


def test_an_external_network_is_accepted():
    compose = {
        "services": {"runtime": {}, "scheduler": {}},
        "networks": {"dancemate-net": {"external": True}},
    }
    assert deploy_guard.check_external_network(compose)["status"] == "PASS"


@pytest.mark.parametrize("host_value", ["postgres", "${POSTGRES_HOST:-postgres}"])
def test_the_bundled_postgres_alias_is_rejected_as_a_host(host_value):
    """`docker-compose.yml`'s own runtime service hardcodes POSTGRES_HOST to
    the literal string "postgres" - its own service alias. A production file
    must never resolve to that alias, since it is what a stray embedded
    postgres would answer to on its own network."""
    compose = {"services": {"runtime": {"environment": {"POSTGRES_HOST": host_value}}}}
    assert deploy_guard.check_external_postgres_host(compose)["status"] == "FAIL"


def test_a_named_external_container_host_is_accepted():
    compose = {"services": {"runtime": {"environment": {
        "POSTGRES_HOST": "${POSTGRES_HOST:-dancemate-postgres}",
    }}}}
    assert deploy_guard.check_external_postgres_host(compose)["status"] == "PASS"


# --- 8: version tag derived correctly ----------------------------------------

def test_expected_image_tag_is_derived_from_the_version_file(tmp_path):
    (tmp_path / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    assert deploy_guard.expected_image_tag(tmp_path) == "dancemate/runtime:9.9.9"


def test_expected_image_tag_matches_the_real_version_file():
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert deploy_guard.expected_image_tag() == f"dancemate/runtime:{version}"
