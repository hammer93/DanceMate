#!/usr/bin/env bash
set -euo pipefail

# DanceMate - stop the staging runtime.
#
# SAFETY: this never passes -v to `docker compose down`. Persistent volumes
# (PostgreSQL, the Information Engine SQLite store, logs and backups) survive a
# stop by design; removing them is a separate, deliberate operator action.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

log "DanceMate stop-server"
require_docker
[[ -f "$COMPOSE_FILE" ]] || die "docker-compose.yml not found at $COMPOSE_FILE"

# stop first so the scheduler drains its current tick within stop_grace_period
compose stop
compose down

log ""
log "stopped. Persistent data was NOT removed:"
log "  postgres volume : dancemate-postgres-data"
log "  engine sqlite   : $(env_value ENGINE_DATA_DIR || echo '(see .env ENGINE_DATA_DIR)')"
log "  backups         : $(env_value DANCEMATE_BACKUP_DIR || echo '(see .env DANCEMATE_BACKUP_DIR)')"
