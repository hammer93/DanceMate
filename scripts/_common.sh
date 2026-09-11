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

# Pinned so every wrapper-driven invocation names containers/networks the same
# way regardless of the invoking shell's cwd (compose's own default is the
# project directory's basename, which is what produced the correctly-named
# "dancemate-runtime-1" even for the v0.82.5 incident's wrong compose file -
# pinning does not by itself catch a wrong -f, but it does mean a wrapper run
# from a different directory can never silently start a differently-named,
# harder-to-notice parallel stack).
COMPOSE_PROJECT="$(env_value DANCEMATE_COMPOSE_PROJECT || true)"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-dancemate}"
readonly COMPOSE_PROJECT

compose() {
  docker compose --project-directory "$REPO_ROOT" -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" "$@"
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

# --- board git/operator guards (v0.82.7) ------------------------------------
#
# v0.82.6's verify_repo_ownership caught the *symptom* of 21 tracked files
# left root-owned - it did not stop it from happening again, because nothing
# stopped a root SSH session from running `git fetch`/`git merge` directly.
# git and Docker both happily let root touch a hammer-owned checkout; what
# gets written is then owned by root, exactly like the incident. These
# guards refuse that at the door instead of relying on a cleanup script
# running afterward.

# The repository directory's own owner - whatever user legitimately owns
# the checkout is correct by definition, on the board or anywhere else
# (same principle verify_repo_ownership already uses for the uid check).
repo_owner() {
  stat -c '%U' "$REPO_ROOT"
}

# Refuses to let a repository-touching script run as root. Root remains free
# to do OS/service-level work (installing packages, managing sshd, editing
# /etc/fstab) - anything that reads or writes *this checkout* must run as
# its own owner, or whatever it writes ends up owned by root the moment
# `sudo`/root SSH is used instead of the repository's own user.
guard_not_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    local owner script
    owner="$(repo_owner)"
    script="${1:-$0}"
    die "$(cat <<EOF
refusing to run as root: $script touches $REPO_ROOT, owned by '$owner'.
Re-run as that user instead:
  sudo -u $owner $script
(or scripts/board-git.sh for a bare git command). Root SSH sessions may
still do OS/service-level work - just not this.
EOF
)"
  fi
}

# A deploy builds and ships whatever is actually checked out - an uncommitted
# local edit would go into the image invisibly, and a non-main branch is
# never what this project's release process expects to be running in
# production. Branch mismatch only warns (a deliberate hotfix branch is a
# real thing); an unclean tree dies outright.
guard_git_clean_and_branch() {
  local dirty branch
  dirty="$(git -C "$REPO_ROOT" status --porcelain=v1 --untracked-files=no 2>/dev/null || true)"
  if [[ -n "$dirty" ]]; then
    warn "working tree has uncommitted changes to tracked files:"
    printf '%s\n' "$dirty" | sed 's/^/  /' >&2
    die "refusing to deploy an uncommitted working tree - commit, stash, or discard first"
  fi
  branch="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '(unknown)')"
  if [[ "$branch" != "main" ]]; then
    warn "deploying from branch '$branch', not 'main' - confirm this is intentional"
  fi
  log "git: clean, branch=$branch"
}

# --- production deployment guards (v0.82.6) ---------------------------------
#
# v0.82.5 was deployed correctly, then a raw `docker compose up -d` - typed
# directly on the board, no `-f` - picked this repository's own bundled-
# PostgreSQL docker-compose.yml instead of the ROCKPro64's real
# deploy/rockpro64/docker-compose.external-postgres.yml. A brand-new, empty
# database silently took over the runtime/scheduler containers for a few
# minutes. No data was lost (the real, bind-mounted postgres container was
# never touched), but nothing here would have *blocked* it. These guards are
# scripts/deploy-production.sh's own preflight, kept in _common.sh so any
# other production-facing script can call the same checks rather than a
# second, drifting copy.

# The compose file resolved to the exact production target - not "some file
# that happens not to define its own postgres", the one specific path this
# project ships for the ROCKPro64. Comparing paths after resolving both to
# absolute avoids a false failure from a relative vs. absolute .env value.
require_production_compose_file() {
  local expected
  expected="$REPO_ROOT/deploy/rockpro64/docker-compose.external-postgres.yml"
  [[ -f "$expected" ]] || die "production compose file not found: $expected"
  [[ "$COMPOSE_FILE" == "$expected" ]] || die "$(cat <<EOF
production compose guard failed: this deploy targets
  $expected
but DANCEMATE_COMPOSE_FILE in .env currently resolves to
  $COMPOSE_FILE
Fix .env, or pass the right one - this script never guesses.
EOF
)"
}

# The resolved config (after .env interpolation, not just the raw YAML) must
# define exactly runtime + scheduler, with no embedded postgres service. This
# is the check that would have blocked the incident outright: the file that
# was picked by accident defines a `postgres` service and fails this
# immediately, before anything is ever brought up.
guard_production_compose_shape() {
  local services
  services="$(compose config --services 2>/dev/null | sort)"
  [[ -n "$services" ]] || die "production compose guard failed: 'docker compose config --services' returned nothing for $COMPOSE_FILE"
  if grep -qx 'postgres' <<<"$services"; then
    die "production compose guard failed: $COMPOSE_FILE defines its own 'postgres' service - production reuses the board's existing PostgreSQL, it never starts a second one"
  fi
  if [[ "$services" != $'runtime\nscheduler' ]]; then
    die "production compose guard failed: expected exactly 'runtime' and 'scheduler' services, found: $(tr '\n' ' ' <<<"$services")"
  fi
}

# Read-only: proves the PostgreSQL this deploy is about to point at is the
# real, populated production database, not an empty one a wrong compose file
# would have just created (that emptiness is exactly what made the incident
# hard to notice immediately - the runtime came up "healthy" against a
# database with no tables' worth of real data).
#
# Deliberately distinct from a fresh install: a brand-new ROCKPro64 setup
# legitimately has an empty `sources` table on its very first deploy, so this
# guard is for scripts/deploy-production.sh's upgrade path only - a first
# install follows deploy/rockpro64/README.md's own procedure
# (scripts/install-rockpro64.sh), which never calls this.
guard_db_identity() {
  local pg_db pg_user count
  pg_db="$(env_value POSTGRES_DB || echo dancemate)"
  pg_user="$(env_value POSTGRES_USER || echo dancemate)"
  if ! count="$(pg_run psql -U "$pg_user" -d "$pg_db" -tAc 'SELECT count(*) FROM sources' 2>/dev/null)"; then
    die "DB identity guard failed: could not query 'sources' on database '$pg_db' - is POSTGRES_HOST/DANCEMATE_POSTGRES_CONTAINER pointed at the real production PostgreSQL?"
  fi
  count="$(tr -d '[:space:]' <<<"$count")"
  if [[ -z "$count" || "$count" -eq 0 ]]; then
    die "DB identity guard failed: database '$pg_db' has 0 rows in 'sources' - this looks like a fresh/empty database, not production's. If this genuinely is a first install, use scripts/install-rockpro64.sh instead of scripts/deploy-production.sh."
  fi
  log "DB identity: database='$pg_db' sources=$count row(s) - looks like the real production database"
}

# At most one of each. A second scheduler is the specific failure mode
# Section 22 calls out: two workers ticking the same jobs against the same
# database. Counts by container *command*, not by name, so it also catches a
# stray container from a different compose project/name.
# v0.86.9: which running containers are a DanceMate scheduler.
#
# v0.86.8's deploy found the old count reading `docker ps --format
# '{{.Command}}'`, which Docker truncates ("/usr/local/bin/dock..."), so
# grepping it for "python -m scheduler" counted 0 with a scheduler plainly
# running - a duplicate guard that could never fire. Two independent signals
# now, merged by container id (first 12 characters, as `docker ps` prints
# them):
#   - the compose service label every compose-started scheduler carries,
#     whatever project it was started under (a second stack from the wrong
#     compose file - the v0.82.5 incident's shape - carries it too);
#   - the full, untruncated command, for a scheduler started any other way.
# runtime/deploy_guard.py's scheduler_count_report() is the same decision in
# Python, which is what the tests hold this to.
SCHEDULER_SERVICE_LABEL="com.docker.compose.service=scheduler"
SCHEDULER_COMMAND="python -m scheduler"

scheduler_container_ids() {
  {
    docker ps -q --no-trunc --filter "label=$SCHEDULER_SERVICE_LABEL" 2>/dev/null || true
    docker ps --no-trunc --format '{{.ID}} {{.Command}}' 2>/dev/null \
      | awk -v want="$SCHEDULER_COMMAND" 'index($0, want) { print $1 }' || true
  } | cut -c1-12 | sed '/^$/d' | sort -u
}

count_scheduler_containers() {
  scheduler_container_ids | wc -l | tr -d ' '
}

guard_no_duplicate_scheduler() {
  local count
  count="$(count_scheduler_containers)"
  log "scheduler guard: $count scheduler container(s) running"
  if (( count > 1 )); then
    warn "more than one scheduler container is running:"
    docker ps --no-trunc --format '  {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}' \
      | grep -F -f <(scheduler_container_ids) >&2 || true
    die "duplicate scheduler guard failed: $count scheduler containers are running (expected at most 1)"
  fi
}

# Exactly one of each *for this project*, checked right after a deploy. Catches
# the incident's own aftermath shape: a leftover container with the same name
# under a different project, or compose having started more replicas than
# expected.
guard_single_runtime_and_scheduler() {
  local runtime_count scheduler_count
  runtime_count="$(compose ps -q runtime 2>/dev/null | wc -l)"
  scheduler_count="$(compose ps -q scheduler 2>/dev/null | wc -l)"
  [[ "$runtime_count" -eq 1 ]] || die "expected exactly 1 runtime container under project '$COMPOSE_PROJECT', found $runtime_count"
  [[ "$scheduler_count" -eq 1 ]] || die "expected exactly 1 scheduler container under project '$COMPOSE_PROJECT', found $scheduler_count"
  guard_no_duplicate_scheduler
}

# A compose file with no `external: true` network creates its own default
# network named "<project>_default" - seeing one exist is a signal that some
# earlier run (by mistake, exactly like the incident) brought up the bundled
# stack under this project name. Warns rather than removing anything: an
# unexpected network might be holding a container with real data, and this
# guard's job is to make an operator look, not to delete on its behalf.
warn_stray_default_network() {
  local net="${COMPOSE_PROJECT}_default"
  if docker network inspect "$net" >/dev/null 2>&1; then
    warn "network '$net' exists - this is what a compose file WITHOUT an external network (e.g. the bundled docker-compose.yml) creates under this project name."
    warn "if this project has never intentionally used the bundled stack, investigate before continuing:"
    warn "  docker network inspect $net"
    warn "  docker ps --filter network=$net"
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
