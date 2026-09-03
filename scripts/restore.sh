#!/usr/bin/env bash
set -euo pipefail

# DanceMate - restore.
#
# SAFETY MODEL
#   * the backup to restore must be named explicitly; no "latest" guessing
#   * nothing is written without --yes
#   * without --yes the script prints exactly what it WOULD overwrite, then exits
#   * a partial backup is refused outright
#   * the scheduler is stopped first, so nothing writes during the restore
#   * a pre-restore safety copy of PostgreSQL and the engine store is taken
#     before anything is overwritten
#
# Usage:
#   scripts/restore.sh --list
#   scripts/restore.sh dancemate-backup-20260903-101500            # dry run
#   scripts/restore.sh dancemate-backup-20260903-101500 --yes      # apply

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

BACKUP_DIR="$(env_value DANCEMATE_BACKUP_DIR || true)"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backup}"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$REPO_ROOT/${BACKUP_DIR#./}"

ENGINE_DB_FILENAME="dancemate_ie_poc_v0.73.sqlite3"
# Displayed only. The real path is resolved inside the container from
# ENGINE_DATA_DIR - see the note in backup.sh about MSYS path rewriting.
ENGINE_DB_DISPLAY="\${ENGINE_DATA_DIR}/$ENGINE_DB_FILENAME"

usage() {
  print_header_comment "${BASH_SOURCE[0]}"
  exit "${1:-0}"
}

list_backups() {
  log "backups under $BACKUP_DIR:"
  find "$BACKUP_DIR" -maxdepth 1 -type d -name 'dancemate-backup-*' -printf '  %f\n' 2>/dev/null | sort -r
}

BACKUP_NAME=""
CONFIRMED=0
for arg in "$@"; do
  case "$arg" in
    --list)    list_backups; exit 0 ;;
    --yes)     CONFIRMED=1 ;;
    -h|--help) usage 0 ;;
    -*)        die "unknown option: $arg" ;;
    *)         [[ -z "$BACKUP_NAME" ]] || die "only one backup may be named"; BACKUP_NAME="$arg" ;;
  esac
done

[[ -n "$BACKUP_NAME" ]] || { warn "no backup named"; list_backups; usage 2; }

SOURCE="$BACKUP_DIR/$BACKUP_NAME"
[[ -d "$SOURCE" ]] || die "no such backup: $SOURCE (try --list)"
[[ -s "$SOURCE/postgres.dump" ]] \
  || die "$BACKUP_NAME has no usable postgres.dump - refusing to restore a partial backup"
[[ -s "$SOURCE/engine.sqlite3" ]] \
  || die "$BACKUP_NAME has no usable engine.sqlite3 - refusing to restore a partial backup"

require_docker
require_env_file
PG_DB="$(env_value POSTGRES_DB || echo dancemate)"
PG_USER="$(env_value POSTGRES_USER || echo dancemate)"

log "restore source : $SOURCE"
if [[ -f "$SOURCE/manifest.json" ]]; then
  log "manifest:"
  sed 's/^/  /' "$SOURCE/manifest.json"
fi
log ""
log "this WILL OVERWRITE:"
log "  PostgreSQL database '$PG_DB' (existing runtime state is replaced)"
log "  Information Engine store $ENGINE_DB_DISPLAY"

if (( CONFIRMED == 0 )); then
  log ""
  log "DRY RUN - nothing was changed."
  log "re-run with --yes to apply:"
  log "  scripts/restore.sh $BACKUP_NAME --yes"
  exit 0
fi

# Stop the scheduler first: it writes to both stores on every tick.
log ""
log "stopping the scheduler so nothing writes during the restore ..."
compose stop scheduler

SAFETY="$BACKUP_DIR/pre-restore-$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$SAFETY"
log "taking a pre-restore safety copy into $SAFETY ..."
compose exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" --format=custom \
  > "$SAFETY/postgres.dump" || warn "pre-restore pg_dump failed (continuing)"
compose exec -T runtime sh -c 'cat "${ENGINE_DATA_DIR:-/app/engine/data}/dancemate_ie_poc_v0.73.sqlite3" 2>/dev/null || true' \
  > "$SAFETY/engine.sqlite3" || warn "pre-restore engine copy failed (continuing)"

log "restoring PostgreSQL ..."
compose exec -T postgres pg_restore -U "$PG_USER" -d "$PG_DB" --clean --if-exists \
  < "$SOURCE/postgres.dump"

log "restoring the Information Engine store ..."
compose exec -T runtime sh -c 'cat > "${ENGINE_DATA_DIR:-/app/engine/data}/dancemate_ie_poc_v0.73.sqlite3"' \
  < "$SOURCE/engine.sqlite3"

log "restarting the scheduler ..."
compose start scheduler

log ""
log "restore complete from $BACKUP_NAME"
log "pre-restore copy kept at $SAFETY"
log "verify with: scripts/check-server.sh"
