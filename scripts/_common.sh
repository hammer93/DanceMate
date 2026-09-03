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

runtime_url() {
  local port
  port="$(env_value DANCEMATE_PORT || true)"
  printf 'http://127.0.0.1:%s' "${port:-8080}"
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
