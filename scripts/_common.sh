#!/usr/bin/env bash
# Shared helpers for the DanceMate operations scripts. Sourced, not executed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
ENV_FILE="$REPO_ROOT/.env"
readonly ENV_FILE

log()  { printf '%s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*" >&2; }
die()  { printf 'ERROR %s\n' "$*" >&2; exit 1; }

# Read one key from .env without sourcing it (values are never executed).
env_value() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 1
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

# Which compose file describes this deployment.
#   default                       docker-compose.yml - bundled PostgreSQL
#   DANCEMATE_COMPOSE_FILE=...    e.g. the ROCKPro64 external-PostgreSQL file
#
# The path is relative to the repository root. Compose is always invoked with
# the repository root as the project directory so that .env, the build context
# and the bind mounts resolve the same way whichever file is selected.
compose_file() {
  local configured
  configured="$(env_value DANCEMATE_COMPOSE_FILE || true)"
  configured="${configured:-docker-compose.yml}"
  [[ "$configured" = /* ]] || configured="$REPO_ROOT/$configured"
  printf '%s' "$configured"
}

COMPOSE_FILE="$(compose_file)"
readonly COMPOSE_FILE

compose() {
  docker compose --project-directory "$REPO_ROOT" -f "$COMPOSE_FILE" "$@"
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH"
  docker compose version >/dev/null 2>&1 \
    || die "the 'docker compose' plugin is not available (docker-compose v1 is not supported)"
  docker info >/dev/null 2>&1 \
    || die "the Docker daemon is not reachable; is it running and is this user in the docker group?"
}

require_env_file() {
  [[ -f "$ENV_FILE" ]] \
    || die ".env not found at $ENV_FILE - copy .env.example and fill it in"
}

require_compose_file() {
  [[ -f "$COMPOSE_FILE" ]] \
    || die "compose file not found: $COMPOSE_FILE (check DANCEMATE_COMPOSE_FILE in .env)"
}

validate_env() {
  require_env_file
  local problems=0 password
  password="$(env_value POSTGRES_PASSWORD || true)"
  if [[ -z "$password" ]]; then
    warn "POSTGRES_PASSWORD is not set in .env"; problems=$((problems + 1))
  elif [[ "$password" == "CHANGE_ME" ]]; then
    warn "POSTGRES_PASSWORD is still the .env.example placeholder"; problems=$((problems + 1))
  fi
  for key in POSTGRES_DB POSTGRES_USER DANCEMATE_PORT; do
    if [[ -z "$(env_value "$key" || true)" ]]; then
      warn "$key is not set in .env"; problems=$((problems + 1))
    fi
  done
  return "$problems"
}

# Host directories the compose bind mounts need. Values in .env are host paths.
ensure_directories() {
  local dir
  for key in ENGINE_DATA_DIR DANCEMATE_DATA_DIR DANCEMATE_LOG_DIR DANCEMATE_BACKUP_DIR; do
    dir="$(env_value "$key" || true)"
    [[ -n "$dir" ]] || continue
    [[ "$dir" = /* ]] || dir="$REPO_ROOT/${dir#./}"
    mkdir -p "$dir" || die "cannot create $key directory: $dir"
  done
}

# Resolve the PostgreSQL container.
#
# With the bundled stack it is this project's own `postgres` service. On the
# ROCKPro64 the database is an existing container outside this compose project,
# named by DANCEMATE_POSTGRES_CONTAINER in .env. Backup and restore go through
# here so they work identically either way.
postgres_container() {
  local id name
  id="$(compose ps -q postgres 2>/dev/null | head -n 1 || true)"
  if [[ -n "$id" ]]; then
    printf '%s' "$id"
    return 0
  fi
  name="$(env_value DANCEMATE_POSTGRES_CONTAINER || true)"
  [[ -n "$name" ]] || return 1
  docker inspect --format '{{.Id}}' "$name" >/dev/null 2>&1 || return 1
  printf '%s' "$name"
}

# Run a command inside the PostgreSQL container with stdin/stdout attached.
pg_run() {
  local container
  container="$(postgres_container)" \
    || die "no PostgreSQL container found: neither a 'postgres' service in $(basename "$COMPOSE_FILE") nor DANCEMATE_POSTGRES_CONTAINER in .env"
  docker exec -i "$container" "$@"
}

# Where the health probes should talk to the runtime.
#
# When DANCEMATE_BIND_ADDRESS narrows the published port to one LAN interface
# (the ROCKPro64 binds to its wired address), loopback is no longer listening,
# so probing 127.0.0.1 would report a healthy server as unreachable. Override
# explicitly with DANCEMATE_HEALTH_HOST if the checks run from elsewhere.
runtime_url() {
  local host port
  port="$(env_value DANCEMATE_PORT || true)"
  port="${port:-8080}"
  host="$(env_value DANCEMATE_HEALTH_HOST || true)"
  if [[ -z "$host" ]]; then
    host="$(env_value DANCEMATE_BIND_ADDRESS || true)"
    case "$host" in
      ""|0.0.0.0|"::"|"[::]"|"*") host="127.0.0.1" ;;
    esac
  fi
  printf 'http://%s:%s' "$host" "$port"
}

# Run a command inside a runtime image container, writing into the bind-
# mounted repository *as the repository's own owner* rather than as root.
#
# v0.81.2: the working tree kept accumulating root-owned tracked files after
# board test runs, repeatedly blocking the next `git checkout`/`pull` until
# someone ran `chown -R` by hand. The cause was this exact kind of command
# being run with `--user root` so an ad hoc `pip install` (needed because the
# image's default `dancemate` user, uid 10001, cannot write into its own
# site-packages) had root write the whole bind mount, including .pytest_cache
# and __pycache__, as root. Running as the repository owner's own uid:gid
# instead means anything the container writes into /src already has the
# right owner - nothing to fix afterwards. `HOME=/tmp` gives `pip install
# --user` (no root needed) a writable, disposable target inside the
# container's own filesystem, never the bind mount.
# Usage: container_run_as_repo_owner IMAGE [docker-run options...] -- CMD...
# The `--` is required even with no extra options, so the split between
# docker's own flags and the container's command is never ambiguous.
container_run_as_repo_owner() {
  local image="$1"; shift
  local owner_uid owner_gid
  owner_uid="$(stat -c '%u' "$REPO_ROOT")"
  owner_gid="$(stat -c '%g' "$REPO_ROOT")"
  local opts=() cmd=() in_cmd=0 arg
  for arg in "$@"; do
    if [[ "$in_cmd" -eq 1 ]]; then
      cmd+=("$arg")
    elif [[ "$arg" == "--" ]]; then
      in_cmd=1
    else
      opts+=("$arg")
    fi
  done
  docker run --rm \
    --user "${owner_uid}:${owner_gid}" \
    -e HOME=/tmp \
    -v "$REPO_ROOT:/src" -w /src \
    "${opts[@]}" \
    "$image" \
    "${cmd[@]}"
}

# FAILs loudly if any file git tracks is not owned by the repository's own
# user - the guard a deploy script runs after touching the tree, so a stray
# root-owned (or otherwise foreign-owned) file blocks *this* deploy with a
# clear cause instead of silently breaking the next `git pull`.
#
# The expected owner is read from the repository directory itself, not a
# hardcoded username: whatever legitimately owns the checkout is correct by
# definition, on this host or any other.
verify_repo_ownership() {
  local expected_uid bad
  expected_uid="$(stat -c '%u' "$REPO_ROOT")"
  bad="$(
    git -C "$REPO_ROOT" ls-files -z 2>/dev/null \
      | xargs -0 -I{} find "$REPO_ROOT/{}" -maxdepth 0 -not -uid "$expected_uid" \
          -printf '%u:%g %p\n' 2>/dev/null
  )"
  if [[ -n "$bad" ]]; then
    warn "tracked files not owned by this repository's own user (uid $expected_uid):"
    printf '%s\n' "$bad" | sed 's/^/  /' >&2
    die "ownership guard failed - fix the step that wrote these as a different user (see scripts/fix-ownership.sh for the approved narrow chown fallback)"
  fi
}

# Print a script's leading comment block as its usage text. Stops at the first
# line that is not a comment, so usage can never bleed into the code below it.
print_header_comment() {
  awk '
    NR<=2                { next }
    /^#/                 { sub(/^# ?/, ""); print; next }
    /^[[:space:]]*$/     { if (started) print ""; next }
                         { exit }
  ' started=0 "$1"
}
