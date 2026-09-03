#!/usr/bin/env bash
set -euo pipefail

# DanceMate - backup.
#
# Produces one timestamped directory under $DANCEMATE_BACKUP_DIR:
#
#   dancemate-backup-YYYYmmdd-HHMMSS/
#     postgres.dump    pg_dump custom format (runtime state)
#     engine.sqlite3   Information Engine store
#     manifest.json    what was captured, and from where
#
# The SQLite file is copied with sqlite3's backup API, never with cp: the
# engine may hold an open connection, and a raw copy taken mid-transaction can
# restore as a corrupt database.
#
# Container paths are resolved INSIDE the container from ENGINE_DATA_DIR rather
# than passed in as arguments - on a Windows dev host, MSYS rewrites an
# /app/... argument into a C:\... path before docker ever sees it.
#
# Retention keeps the newest N backups (BACKUP_RETENTION, default 7).
# Exit status is non-zero if either component of the backup failed.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

require_docker
require_env_file

BACKUP_DIR="$(env_value DANCEMATE_BACKUP_DIR || true)"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backup}"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$REPO_ROOT/${BACKUP_DIR#./}"

RETENTION="$(env_value BACKUP_RETENTION || true)"
RETENTION="${RETENTION:-7}"
[[ "$RETENTION" =~ ^[0-9]+$ && "$RETENTION" -ge 1 ]] || die "BACKUP_RETENTION must be >= 1"

PG_DB="$(env_value POSTGRES_DB || echo dancemate)"
PG_USER="$(env_value POSTGRES_USER || echo dancemate)"
ENGINE_DB_FILENAME="dancemate_ie_poc_v0.73.sqlite3"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
NAME="dancemate-backup-$STAMP"
TARGET="$BACKUP_DIR/$NAME"
mkdir -p "$TARGET"

log "DanceMate backup -> $TARGET"

# --- PostgreSQL -------------------------------------------------------------
log "  pg_dump ($PG_DB) ..."
if compose exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" --format=custom \
     > "$TARGET/postgres.dump" 2>"$TARGET/postgres.err"; then
  rm -f "$TARGET/postgres.err"
  PG_STATUS=ok
else
  PG_STATUS=failed
  warn "pg_dump failed; see $TARGET/postgres.err"
fi

# --- Information Engine SQLite ---------------------------------------------
log "  engine sqlite online backup ..."
if compose exec -T runtime python - > "$TARGET/engine.sqlite3" 2>"$TARGET/engine.err" <<'PY'
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

data_dir = Path(os.environ.get("ENGINE_DATA_DIR", "/app/engine/data"))
source = data_dir / "dancemate_ie_poc_v0.73.sqlite3"
if not source.is_file():
    print(f"engine database not present yet: {source}", file=sys.stderr)
    raise SystemExit(3)

with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as handle:
    tmp = Path(handle.name)
src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
dst = sqlite3.connect(tmp)
with dst:
    src.backup(dst)
dst.close()
src.close()
sys.stdout.buffer.write(tmp.read_bytes())
tmp.unlink()
PY
then
  rm -f "$TARGET/engine.err"
  ENGINE_STATUS=ok
else
  ENGINE_STATUS=failed
  warn "engine sqlite backup failed; see $TARGET/engine.err"
  warn "(a fresh deployment has no engine database until the first engine run)"
fi

# --- manifest ---------------------------------------------------------------
cat > "$TARGET/manifest.json" <<JSON
{
  "name": "$NAME",
  "created_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "product_runtime_version": "$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo unknown)",
  "postgres": {"database": "$PG_DB", "status": "$PG_STATUS", "file": "postgres.dump"},
  "engine_sqlite": {"filename": "$ENGINE_DB_FILENAME", "status": "$ENGINE_STATUS", "file": "engine.sqlite3"}
}
JSON

if [[ "$PG_STATUS" != ok || "$ENGINE_STATUS" != ok ]]; then
  warn "backup is INCOMPLETE: postgres=$PG_STATUS engine=$ENGINE_STATUS"
fi

# --- retention --------------------------------------------------------------
mapfile -t ALL < <(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'dancemate-backup-*' -printf '%f\n' | sort -r)
if (( ${#ALL[@]} > RETENTION )); then
  for old in "${ALL[@]:RETENTION}"; do
    log "  pruning old backup: $old"
    rm -rf -- "${BACKUP_DIR:?}/$old"
  done
fi

log ""
log "backup complete: $TARGET"
log "retained: $(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'dancemate-backup-*' | wc -l) of max $RETENTION"
[[ "$PG_STATUS" == ok && "$ENGINE_STATUS" == ok ]]
