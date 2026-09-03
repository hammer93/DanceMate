#!/usr/bin/env bash
set -euo pipefail

# DanceMate - start the staging runtime.
#
# Validates the environment before touching Docker so a half-configured host
# fails loudly instead of leaving a partially started stack behind.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

log "DanceMate start-server"
log "repository  : $REPO_ROOT"
log "compose file: ${COMPOSE_FILE#"$REPO_ROOT/"}"

require_docker
if ! validate_env; then
  die ".env validation failed - fix the warnings above before starting"
fi
ensure_directories

require_compose_file
compose config --quiet || die "$COMPOSE_FILE is not valid"

log "starting postgres, runtime and scheduler ..."
compose up -d

log ""
compose ps

# Wait for the stack to become serviceable before returning. Without this a
# check-server.sh run immediately after start correctly reports the scheduler
# as FAIL, simply because the worker has not written its first heartbeat yet.
READY_TIMEOUT="${DANCEMATE_START_TIMEOUT:-180}"
log ""
log "waiting up to ${READY_TIMEOUT}s for the runtime and the first scheduler heartbeat ..."

deadline=$(( SECONDS + READY_TIMEOUT ))
ready=0
while (( SECONDS < deadline )); do
  if summary="$(curl --silent --max-time 5 "$(runtime_url)/status/summary" 2>/dev/null)"      && [[ "$summary" == "DanceMate Server"* ]]      && ! printf '%s' "$summary" | grep -q 'Scheduler .* FAIL'; then
    ready=1
    break
  fi
  sleep 5
done

log ""
if (( ready == 1 )); then
  log "stack is up."
else
  warn "the stack did not become fully ready within ${READY_TIMEOUT}s."
  warn "this is not necessarily fatal - run scripts/check-server.sh for detail."
fi
log "runtime API: $(runtime_url)/health"
log "check state: scripts/check-server.sh"
