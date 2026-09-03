#!/usr/bin/env bash
set -euo pipefail

# DanceMate - start the staging runtime.
#
# Validates the environment before touching Docker so a half-configured host
# fails loudly instead of leaving a partially started stack behind.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

log "DanceMate start-server"
log "repository: $REPO_ROOT"

require_docker
if ! validate_env; then
  die ".env validation failed - fix the warnings above before starting"
fi
ensure_directories

[[ -f "$COMPOSE_FILE" ]] || die "docker-compose.yml not found at $COMPOSE_FILE"
compose config --quiet || die "docker-compose.yml is not valid"

log "starting postgres, runtime and scheduler ..."
compose up -d

log ""
compose ps
log ""
log "runtime API: $(runtime_url)/health"
log "check state: scripts/check-server.sh"
