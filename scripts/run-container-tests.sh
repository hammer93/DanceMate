#!/usr/bin/env bash
set -euo pipefail

# DanceMate - run the runtime test suite inside a container, against the
# board's real network and .env, without ever writing into the working tree
# as anyone but its own owner.
#
# Usage: scripts/run-container-tests.sh [IMAGE] [-- pytest args...]
#   IMAGE defaults to dancemate/runtime:<VERSION file>.
#
# Before v0.81.2 this was typed ad hoc as `docker run --user root ...` for
# every release, because the image's default `dancemate` user (uid 10001)
# cannot `pip install` its own test dependencies. Root writing into the
# bind-mounted repository is exactly what kept leaving root-owned
# .pytest_cache/__pycache__ behind, blocking the next `git checkout`/`pull`
# until someone ran a manual chown. This script runs as the repository's own
# owner instead (see container_run_as_repo_owner in _common.sh) and installs
# test dependencies with `pip install --user` into a disposable $HOME, so
# nothing written during the run can touch the tree as a different user.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

IMAGE="${1:-dancemate/runtime:$(cat "$REPO_ROOT/VERSION")}"
shift || true
if [[ "${1:-}" == "--" ]]; then shift; fi
PYTEST_ARGS=("$@")
[[ ${#PYTEST_ARGS[@]} -gt 0 ]] || PYTEST_ARGS=("tests/")

require_docker
verify_repo_ownership

NETWORK="${DANCEMATE_NETWORK:-dancemate-net}"

log "running container tests: image=$IMAGE network=$NETWORK args=${PYTEST_ARGS[*]}"

container_run_as_repo_owner "$IMAGE" \
  --network "$NETWORK" \
  --env-file "$ENV_FILE" \
  -e PYTHONIOENCODING=utf-8 \
  -e PYTHONPATH=/src \
  -- \
  sh -c "pip install --user -q pytest==8.3.4 httpx==0.28.1 pyyaml==6.0.2 >/dev/null 2>&1; python -m pytest -q ${PYTEST_ARGS[*]}"

verify_repo_ownership
log "container test run finished cleanly; working tree ownership unchanged."
