#!/usr/bin/env bash
# Shared helpers for the DanceMate operations scripts. Sourced, not executed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"
readonly COMPOSE_FILE
ENV_FILE="$REPO_ROOT/.env"
readonly ENV_FILE

log()  { printf '%s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*" >&2; }
die()  { printf 'ERROR %s\n' "$*" >&2; exit 1; }

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

# Read one key from .env without sourcing it (values are never executed).
env_value() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 1
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
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

compose() {
  docker compose --project-directory "$REPO_ROOT" -f "$COMPOSE_FILE" "$@"
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
