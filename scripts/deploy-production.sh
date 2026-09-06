#!/usr/bin/env bash
set -euo pipefail

# DanceMate - production deploy (v0.82.7, "Board Git Ownership Guard").
#
# THE ONLY SUPPORTED WAY to bring up or update the ROCKPro64's production
# stack. Never run `docker compose up -d` directly on the board, and never
# run this script itself as root (see the root guard below).
#
# Incident, v0.82.5: a raw `docker compose up -d`, typed with no `-f`, picked
# this repository's bundled-PostgreSQL docker-compose.yml instead of
# deploy/rockpro64/docker-compose.external-postgres.yml. A brand-new, empty
# database silently took over the runtime/scheduler containers for a few
# minutes before anyone noticed - no data was lost (the real, bind-mounted
# postgres container was never touched), but nothing blocked the command from
# running. v0.82.6 fixed that: the compose file, the project name and every
# guard below are fixed in code, not left to whatever the invoking shell's
# cwd or muscle memory happens to produce.
#
# Incident, ongoing habit: v0.82.6's own board sync (`git fetch`/`git merge`)
# was typed over a root SSH session, same as every prior release - it left 21
# tracked files owned by root instead of the repository's own user, `hammer`.
# git and Docker both happily let root touch a hammer-owned checkout; this
# script now refuses to run as root at all (see guard_not_root), and
# scripts/board-git.sh is the canonical way to run git against this checkout
# regardless of which user is logged in.
#
# Usage:
#   scripts/deploy-production.sh            full deploy
#   scripts/deploy-production.sh --check    preflight only - no build, no
#                                            backup, no container touched
#
# Deploy order: preflight (root/ownership -> git -> version -> compose -> DB
# identity) -> backup -> build -> verify image -> controlled recreate ->
# health gate -> post-deploy guards. A step never runs if the one before it
# failed; in particular the running stack is never touched until a new image
# has actually built successfully (spec item 28).
#
# This script never removes a volume or prunes one - no destructive compose
# flag, no direct volume command - see stop-server.sh for the same rule. A
# failed deploy leaves the previous containers' data exactly as it was;
# rolling back code is a human decision (see the "rollback candidate" image
# tag this script prints), rolling back schema/data never happens here.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    -h|--help) print_header_comment "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown argument: $arg (only --check is supported)" ;;
  esac
done

log "DanceMate production deploy"
log "repository   : $REPO_ROOT"
log "compose file : ${COMPOSE_FILE#"$REPO_ROOT/"}"
log "project      : $COMPOSE_PROJECT"

# --- preflight ---------------------------------------------------------------
log ""
log "=== preflight ==="

guard_not_root "$0"
log "operator: $(id -un) (repository owner: $(repo_owner))"
require_docker
verify_repo_ownership
guard_git_clean_and_branch
if ! validate_env; then
  die ".env validation failed - fix the warnings above before deploying"
fi
require_production_compose_file
require_compose_file
compose config --quiet || die "$COMPOSE_FILE is not valid"
guard_production_compose_shape
guard_db_identity
guard_no_duplicate_scheduler
warn_stray_default_network

EXPECTED_VERSION="$(cat "$REPO_ROOT/VERSION")"
EXPECTED_IMAGE="dancemate/runtime:${EXPECTED_VERSION}"
CONFIGURED_VERSION="$(env_value DANCEMATE_VERSION || true)"
if [[ -n "$CONFIGURED_VERSION" && "$CONFIGURED_VERSION" != "$EXPECTED_VERSION" ]]; then
  die "version mismatch: VERSION file says '$EXPECTED_VERSION' but .env's DANCEMATE_VERSION='$CONFIGURED_VERSION' - update .env before deploying, so the image this script builds is the image .env says should be running"
fi
log "target version: $EXPECTED_VERSION -> $EXPECTED_IMAGE"

PREVIOUS_CONTAINER="$(compose ps -q runtime 2>/dev/null | head -n1 || true)"
PREVIOUS_IMAGE=""
if [[ -n "$PREVIOUS_CONTAINER" ]]; then
  PREVIOUS_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$PREVIOUS_CONTAINER" 2>/dev/null || true)"
fi
if [[ -n "$PREVIOUS_IMAGE" ]]; then
  log "currently running image: $PREVIOUS_IMAGE (rollback candidate if this deploy fails)"
else
  log "no runtime container currently running under project '$COMPOSE_PROJECT'"
fi

log ""
log "preflight PASS"

if (( CHECK_ONLY )); then
  log ""
  log "--check: preflight only, no changes made."
  exit 0
fi

# --- backup gate --------------------------------------------------------------
log ""
log "=== backup ==="
"$REPO_ROOT/scripts/backup.sh" || die "backup failed - refusing to deploy without a fresh backup. Fix the backup failure and re-run."

# --- build guard: the running stack is never touched before this succeeds ----
log ""
log "=== build ==="
compose build || die "image build failed - the currently running stack is untouched"
BUILT_ID="$(docker image inspect --format '{{.Id}}' "$EXPECTED_IMAGE" 2>/dev/null || true)"
[[ -n "$BUILT_ID" ]] || die "build guard failed: $EXPECTED_IMAGE does not exist after 'compose build' - check the image tag in $COMPOSE_FILE against .env's DANCEMATE_VERSION"
log "built: $EXPECTED_IMAGE ($BUILT_ID)"

# --- controlled recreate -------------------------------------------------------
log ""
log "=== deploy ==="
compose up -d
guard_single_runtime_and_scheduler

# --- health gate ----------------------------------------------------------------
log ""
log "=== waiting for health ==="
READY_TIMEOUT="${DANCEMATE_START_TIMEOUT:-180}"
deadline=$(( SECONDS + READY_TIMEOUT ))
ready=0
summary=""
while (( SECONDS < deadline )); do
  if summary="$(curl --silent --max-time 5 "$(runtime_url)/status/summary" 2>/dev/null)" \
     && [[ "$summary" == "DanceMate Server"* ]] \
     && ! grep -q 'FAIL' <<<"$summary"; then
    ready=1
    break
  fi
  sleep 5
done
if (( ready != 1 )); then
  warn "runtime did not report all-PASS within ${READY_TIMEOUT}s:"
  [[ -n "$summary" ]] && printf '%s\n' "$summary" >&2
  die "health gate failed - rollback candidate: ${PREVIOUS_IMAGE:-none recorded}. Investigate with '$(basename "$COMPOSE_FILE")' logs before retrying; this script does not roll back automatically."
fi

if compose logs runtime 2>/dev/null | grep -qi 'migration.*fail\|FAILED.*migration'; then
  die "health gate failed: a migration failure was logged - a healthy-looking runtime with a failed migration is not a successful deploy. Rollback candidate: ${PREVIOUS_IMAGE:-none recorded}"
fi

# --- post-deploy ----------------------------------------------------------------
log ""
log "=== post-deploy ==="
guard_single_runtime_and_scheduler
"$REPO_ROOT/scripts/check-server.sh"

log ""
log "deploy complete: $EXPECTED_IMAGE"
[[ -n "$PREVIOUS_IMAGE" && "$PREVIOUS_IMAGE" != "$EXPECTED_IMAGE" ]] \
  && log "previous image (rollback candidate): $PREVIOUS_IMAGE"
log "health: scripts/check-server.sh"
