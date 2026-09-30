#!/usr/bin/env bash
set -euo pipefail

# DanceMate - run the runtime test suite inside a container, against a
# disposable database it creates and drops itself, without ever writing into the
# working tree as anyone but its own owner.
#
# Usage: scripts/run-container-tests.sh [IMAGE] [--db NAME] [--keep-db]
#                                      [-- pytest args...]
#   IMAGE defaults to dancemate/runtime:<VERSION file>.
#   --db NAME   use this scratch database instead of a generated name.
#   --keep-db   do not drop it afterwards (for inspecting a failure).
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
#
# v0.96.28: and against a disposable database. This script used to pass
# `--env-file "$ENV_FILE"` and nothing else, so the only database it could ever
# target was the deployment's own - the suite commits through connections no
# fixture rolls back, and two releases paid for it (v0.96.14, v0.96.27). The
# second time the invocation even looked right: `POSTGRES_DB=ct_9627
# scripts/run-container-tests.sh` sets a variable in the *host* shell, which
# this script never forwarded. There was no argument to pass instead, so the
# correct thing was not merely hard, it was unsayable.
#
# Now the scratch database is this script's own business: it creates one,
# declares it disposable (see runtime/scratch_db_guard.py), migrates it, runs
# the suite against it and drops it on the way out, whether the suite passed,
# failed or was interrupted. The `-e POSTGRES_DB` override is placed *after*
# `--env-file` so it wins, and the suite verifies the database it actually
# reached rather than trusting that.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

IMAGE=""
SCRATCH_DB=""
KEEP_DB=0
PYTEST_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) SCRATCH_DB="${2:-}"; shift 2 || die "--db needs a database name" ;;
    --keep-db) KEEP_DB=1; shift ;;
    --) shift; PYTEST_ARGS=("$@"); break ;;
    *) [[ -n "$IMAGE" ]] && die "unexpected argument: $1"; IMAGE="$1"; shift ;;
  esac
done
IMAGE="${IMAGE:-dancemate/runtime:$(cat "$REPO_ROOT/VERSION")}"
[[ ${#PYTEST_ARGS[@]} -gt 0 ]] || PYTEST_ARGS=("tests/")
SCRATCH_DB="${SCRATCH_DB:-$(scratch_db_name)}"

require_docker
require_env_file
verify_repo_ownership

NETWORK="${DANCEMATE_NETWORK:-dancemate-net}"
PG_USER="$(env_value POSTGRES_USER || echo dancemate)"

guard_not_deployment_database "$SCRATCH_DB"
log "TEST DB TARGET: $SCRATCH_DB (deployment database: $(env_value POSTGRES_DB || echo '<unset>'))"

cleanup_scratch_db() {
  local status=$?
  if [[ "$KEEP_DB" -eq 1 ]]; then
    warn "--keep-db: leaving scratch database '$SCRATCH_DB' in place; drop it with"
    warn "  docker exec -i \$(docker ps -qf name=postgres) psql -U $PG_USER -d postgres -c 'DROP DATABASE $SCRATCH_DB'"
  else
    drop_scratch_db "$SCRATCH_DB" "$PG_USER"
  fi
  return "$status"
}
trap cleanup_scratch_db EXIT

create_scratch_db "$SCRATCH_DB" "$PG_USER"

log "migrating scratch database: $SCRATCH_DB"
container_run_as_repo_owner "$IMAGE" \
  --network "$NETWORK" \
  --env-file "$ENV_FILE" \
  -e "POSTGRES_DB=$SCRATCH_DB" \
  -e PYTHONIOENCODING=utf-8 \
  -e PYTHONPATH=/src \
  -- \
  python -m runtime.migrate >/dev/null \
  || die "could not migrate scratch database '$SCRATCH_DB'"

log "running container tests: image=$IMAGE network=$NETWORK db=$SCRATCH_DB args=${PYTEST_ARGS[*]}"

container_run_as_repo_owner "$IMAGE" \
  --network "$NETWORK" \
  --env-file "$ENV_FILE" \
  -e "POSTGRES_DB=$SCRATCH_DB" \
  -e PYTHONIOENCODING=utf-8 \
  -e PYTHONPATH=/src \
  -- \
  sh -c "pip install --user -q pytest==8.3.4 httpx==0.28.1 pyyaml==6.0.2 >/dev/null 2>&1; python -m pytest -q ${PYTEST_ARGS[*]}"

verify_repo_ownership
log "container test run finished cleanly; working tree ownership unchanged."
