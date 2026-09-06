"""Production compose-file guards (v0.82.6, "Deployment Guard").

v0.82.5 shipped correctly, then a raw ``docker compose up -d`` - run without
``-f`` - picked the repository-root ``docker-compose.yml`` (its own bundled
PostgreSQL) instead of the board's real
``deploy/rockpro64/docker-compose.external-postgres.yml``. Docker itself has
no concept of "the production compose file"; that convention lives entirely
in this project's own scripts (``scripts/_common.sh``'s ``DANCEMATE_COMPOSE_
FILE``), and a command typed directly on the board bypassed it.

These are *static* checks, the same kind ``target.dockerfile_arm64_report()``
already makes: they read a compose file's own YAML and judge its shape,
without a Docker daemon and without touching anything live. That is
deliberate - it is what makes them the same check whether they run in a unit
test, in ``scripts/deploy-production.sh --check``, or as the last gate before
that script ever calls ``docker compose up``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import REPO_ROOT

# The one compose file this project ships for the ROCKPro64. Anything else
# handed to scripts/deploy-production.sh is refused, never guessed.
PRODUCTION_COMPOSE_PATH = "deploy/rockpro64/docker-compose.external-postgres.yml"

# The bundled-PostgreSQL development stack. Never the production target - see
# production_compose_report()'s own embedded-postgres check.
LOCAL_COMPOSE_PATH = "docker-compose.yml"

REQUIRED_PRODUCTION_SERVICES = frozenset({"runtime", "scheduler"})


def load_compose(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def check_no_embedded_postgres(compose: dict[str, Any]) -> dict[str, Any]:
    """A production compose file must never define its own ``postgres``
    service - the board's real PostgreSQL is an existing external container
    (compose project "database"), and starting a second one is exactly the
    v0.82.5 incident: a brand-new, empty database silently taking traffic."""
    services = set((compose.get("services") or {}).keys())
    if "postgres" in services:
        return {
            "status": "FAIL",
            "detail": f"compose defines its own postgres service: {sorted(services)}",
        }
    return {"status": "PASS", "detail": "no embedded postgres service", "services": sorted(services)}


def check_required_services(compose: dict[str, Any]) -> dict[str, Any]:
    services = set((compose.get("services") or {}).keys())
    if services != set(REQUIRED_PRODUCTION_SERVICES):
        return {
            "status": "FAIL",
            "detail": f"expected exactly {sorted(REQUIRED_PRODUCTION_SERVICES)}, found {sorted(services)}",
        }
    return {"status": "PASS", "detail": "runtime + scheduler only"}


def check_external_network(compose: dict[str, Any]) -> dict[str, Any]:
    """The production file must join an *existing* network (the board's own
    ``dancemate-net``, shared with the real postgres/caddy containers) rather
    than let compose create a fresh one - a fresh network is what silently
    isolated the runtime from the real database in the incident."""
    networks = compose.get("networks") or {}
    external = {name: spec for name, spec in networks.items() if isinstance(spec, dict) and spec.get("external")}
    if not external:
        return {
            "status": "FAIL",
            "detail": f"no external network declared; networks={list(networks)}",
        }
    return {"status": "PASS", "detail": f"external network(s): {sorted(external)}"}


def check_external_postgres_host(compose: dict[str, Any]) -> dict[str, Any]:
    """Every service must point POSTGRES_HOST at the board's existing
    container by name, not the bundled stack's own ``postgres`` service
    alias - that literal string is what a fresh embedded postgres would
    otherwise resolve to on its own network."""
    services = compose.get("services") or {}
    bad = []
    for name, service in services.items():
        env = (service or {}).get("environment") or {}
        host = env.get("POSTGRES_HOST")
        if host is None:
            continue
        host_str = str(host)
        if host_str in ("postgres", "${POSTGRES_HOST:-postgres}"):
            bad.append((name, host_str))
    if bad:
        return {"status": "FAIL", "detail": f"POSTGRES_HOST resolves to the bundled alias: {bad}"}
    return {"status": "PASS", "detail": "POSTGRES_HOST does not resolve to the bundled alias"}


def production_compose_report(path: Path | None = None) -> dict[str, Any]:
    """Full static verdict for one compose file as *the* production target.

    PASS only when every sub-check PASSes. A file that does not even exist,
    or does not parse, FAILs rather than raising - the deploy wrapper's
    preflight reports this exactly like any other blocked check.
    """
    path = path or (REPO_ROOT / PRODUCTION_COMPOSE_PATH)
    if not path.is_file():
        return {"status": "FAIL", "detail": f"compose file not found: {path}", "checks": {}}
    try:
        compose = load_compose(path)
    except yaml.YAMLError as exc:
        return {"status": "FAIL", "detail": f"compose file does not parse: {exc}", "checks": {}}

    checks = {
        "no_embedded_postgres": check_no_embedded_postgres(compose),
        "required_services": check_required_services(compose),
        "external_network": check_external_network(compose),
        "external_postgres_host": check_external_postgres_host(compose),
    }
    failed = {name: c for name, c in checks.items() if c["status"] != "PASS"}
    if failed:
        return {
            "status": "FAIL",
            "detail": "; ".join(f"{name}: {c['detail']}" for name, c in failed.items()),
            "checks": checks,
        }
    return {"status": "PASS", "detail": f"{path} is a valid production compose file", "checks": checks}


def expected_image_tag(repo_root: Path | None = None) -> str:
    """``dancemate/runtime:<VERSION>`` - the tag a production deploy must
    build and run, derived from the same file the release process bumps, so
    a script can never launch a mismatched tag by manual typo."""
    root = repo_root or REPO_ROOT
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    return f"dancemate/runtime:{version}"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", type=Path, default=None)
    args = parser.parse_args(argv)

    report = production_compose_report(args.compose_file)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
