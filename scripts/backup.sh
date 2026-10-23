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
#
# v0.96.51 (scheduled backups - deploy/rockpro64/systemd/dancemate-backup.timer):
#   * A failed or unverified backup no longer looks like a backup. Until now a
#     failed pg_dump still left a `postgres.dump` (empty or partial) under a
#     `dancemate-backup-*` name, which /status counted as complete and which
#     retention counted as one of the N kept - so failures could prune the
#     last good backups. Now each part is verified (pg_restore --list, sqlite
#     integrity_check, non-empty), and a backup that is not complete is
#     renamed `failed-dancemate-backup-*`: outside the naming contract, never
#     the latest, never counted, and retention does not run after it.
#   * One backup at a time (flock): the timer and a deploy's backup gate wait
#     for each other instead of interleaving.
#   * Too little free space (BACKUP_MIN_FREE_MB, default 1024) fails before
#     anything is written.
#   * The manifest records each file's size and SHA-256.
#
# v0.96.51 recovery (who may read a backup):
#   The runtime container reads this directory through its bind mount as uid
#   10001 - "other" to the backup owner - to answer /status. v0.96.51 first
#   shipped with every backup 0700/0600 (umask 077), the runtime could not
#   stat a part, /status answered HTTP 500 and the deploy's health gate
#   failed. The runtime never needs a dump's *contents*, only its size and
#   the manifest, so the modes are now set explicitly instead of left to a
#   umask: the dumps stay 0600 (private to the backup owner - tighter than
#   the 0664 every backup before v0.96.51 had), the backup directory is 0711
#   (enter, not list) and manifest.json is 0644. The root stays listable
#   (0755: names only). Before a backup is renamed into the naming contract
#   it is read through the runtime container itself - the identity /status
#   uses - and a backup the runtime cannot read is a failed backup.
#   A backup is written as `.inprogress-<name>` and renamed when complete, so
#   the backup being written is never the latest one /status looks at.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

# v0.86.9: a backup directory belongs to the repository's own user. The two
# root-owned directories v0.86.8's deploy could not prune were made by this
# script run in a root session; retention runs as that same user and cannot
# remove what root created. Run as root, this hands itself to the owner (the
# same arrangement scripts/board-git.sh uses) instead of writing as root.
if [[ "$(id -u)" -eq 0 && "$(repo_owner)" != "root" ]]; then
  command -v sudo >/dev/null 2>&1 \
    || die "running as root and sudo is not available - run scripts/backup.sh as $(repo_owner)"
  log "running as root: handing the backup to the repository owner '$(repo_owner)'"
  exec sudo -u "$(repo_owner)" "$REPO_ROOT/scripts/backup.sh" "$@"
fi

require_docker
require_env_file
require_compose_file
umask 077

BACKUP_DIR="$(env_value DANCEMATE_BACKUP_DIR || true)"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backup}"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$REPO_ROOT/${BACKUP_DIR#./}"

RETENTION="$(env_value BACKUP_RETENTION || true)"
RETENTION="${RETENTION:-7}"
[[ "$RETENTION" =~ ^[0-9]+$ && "$RETENTION" -ge 1 ]] || die "BACKUP_RETENTION must be >= 1"

PG_DB="$(env_value POSTGRES_DB || echo dancemate)"
PG_USER="$(env_value POSTGRES_USER || echo dancemate)"
ENGINE_DB_FILENAME="dancemate_ie_poc_v0.73.sqlite3"

MIN_FREE_MB="$(env_value BACKUP_MIN_FREE_MB || true)"
MIN_FREE_MB="${MIN_FREE_MB:-1024}"
[[ "$MIN_FREE_MB" =~ ^[0-9]+$ ]] || die "BACKUP_MIN_FREE_MB must be a number of megabytes"

if [[ ! -d "$BACKUP_DIR" ]]; then
  mkdir -p "$BACKUP_DIR"
  chmod 0755 "$BACKUP_DIR"     # the runtime lists backup names; contents stay private
fi
exec 8>"$BACKUP_DIR/.backup.lock"
flock -w 900 8 || die "another backup has held $BACKUP_DIR/.backup.lock for 15 minutes - refusing to run alongside it"

# Holding the lock, any `.inprogress-*` left here is from a run that was
# killed before its EXIT trap could run: it is not a backup, it is evidence.
for stale in "$BACKUP_DIR"/.inprogress-dancemate-backup-*; do
  [[ -d "$stale" ]] || continue
  mv -- "$stale" "$BACKUP_DIR/failed-${stale##*/.inprogress-}" 2>/dev/null \
    && warn "an interrupted backup was left behind - kept as failed-${stale##*/.inprogress-}" || true
done

FREE_MB="$(df -Pm "$BACKUP_DIR" | awk 'NR==2 { print $4 }')"
if [[ -z "$FREE_MB" || "$FREE_MB" -lt "$MIN_FREE_MB" ]]; then
  die "only ${FREE_MB:-?} MB free under $BACKUP_DIR (BACKUP_MIN_FREE_MB=$MIN_FREE_MB) - no backup written, nothing pruned"
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)"
NAME="dancemate-backup-$STAMP"
FINAL="$BACKUP_DIR/$NAME"
TARGET="$BACKUP_DIR/.inprogress-$NAME"
mkdir -p "$TARGET"

# Anything that ends this script before the backup is complete and verified
# moves it out of the naming contract, so nothing ever counts it as a backup.
COMPLETE=0
mark_failed() {
  if (( ! COMPLETE )) && [[ -d "$TARGET" ]]; then
    mv -- "$TARGET" "$BACKUP_DIR/failed-$NAME" 2>/dev/null || true
    warn "backup NOT complete - kept for inspection as $BACKUP_DIR/failed-$NAME (not a backup)"
  fi
}
trap mark_failed EXIT

log "DanceMate backup -> $TARGET"

# --- PostgreSQL -------------------------------------------------------------
log "  pg_dump ($PG_DB) ..."
if pg_run pg_dump -U "$PG_USER" -d "$PG_DB" --format=custom \
     > "$TARGET/postgres.dump" 2>"$TARGET/postgres.err"; then
  rm -f "$TARGET/postgres.err"
  PG_STATUS=ok
  # The archive must read back: its table of contents lists every object.
  if [[ ! -s "$TARGET/postgres.dump" ]] \
     || ! pg_run pg_restore --list < "$TARGET/postgres.dump" > /dev/null 2>"$TARGET/postgres.err"; then
    PG_STATUS=failed
    warn "pg_dump wrote an archive that does not read back; see $TARGET/postgres.err"
  else
    rm -f "$TARGET/postgres.err"
  fi
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
  INTEGRITY="$(compose exec -T runtime python -c '
import sqlite3, sys, tempfile
with tempfile.NamedTemporaryFile(suffix=".sqlite3") as handle:
    handle.write(sys.stdin.buffer.read())
    handle.flush()
    con = sqlite3.connect(handle.name)
    print(con.execute("PRAGMA integrity_check").fetchone()[0])
    con.close()
' < "$TARGET/engine.sqlite3" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
  if [[ ! -s "$TARGET/engine.sqlite3" || "$INTEGRITY" != "ok" ]]; then
    ENGINE_STATUS=failed
    warn "engine sqlite copy failed its integrity check (${INTEGRITY:-no answer})"
  fi
else
  ENGINE_STATUS=failed
  warn "engine sqlite backup failed; see $TARGET/engine.err"
  warn "(a fresh deployment has no engine database until the first engine run)"
fi

# --- manifest ---------------------------------------------------------------
RUNTIME_VERSION="$(compose exec -T runtime cat /app/VERSION 2>/dev/null | tr -d '\r\n' || true)"
MIGRATION_HEAD="$(pg_run psql -U "$PG_USER" -d "$PG_DB" -At -c 'SELECT max(version) FROM schema_migrations' 2>/dev/null | tr -d '\r\n' || true)"
# v0.96.52: which commit wrote this snapshot. The checkout can already be at
# the NEW release when deploy-production.sh takes its pre-deploy backup, and
# the running image is still the OLD one - so the checkout's HEAD is only the
# *candidate*. The running commit is the running container's image label
# (set at build time by deploy-production.sh), else the release tag of the
# running version (images built before v0.96.52 carry no label), else
# UNKNOWN. Until v0.96.52 a same-version redeploy before its tag fell back to
# HEAD and labelled the pre-deploy backup with the commit being deployed.
RUNTIME_CONTAINER="$(compose ps -q runtime 2>/dev/null | head -n 1 || true)"
IMAGE_LABEL=""
if [[ -n "$RUNTIME_CONTAINER" ]]; then
  IMAGE_LABEL="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$RUNTIME_CONTAINER" 2>/dev/null | tr -d '\r\n' || true)"
fi
TAG_COMMIT=""
[[ -n "$RUNTIME_VERSION" ]] \
  && TAG_COMMIT="$(git -C "$REPO_ROOT" rev-list -n1 "v$RUNTIME_VERSION" 2>/dev/null || true)"
CHECKOUT_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
RUNNING_COMMIT=UNKNOWN RUNNING_COMMIT_SOURCE=unknown CANDIDATE_COMMIT=UNKNOWN
CANDIDATE_VERSION=UNKNOWN SNAPSHOT_TIME_KST=UNKNOWN
if PROVENANCE="$(cd "$REPO_ROOT" && python3 -m runtime.backup_provenance \
      --label "$IMAGE_LABEL" --running-version "$RUNTIME_VERSION" --tag-commit "$TAG_COMMIT" \
      --head "$CHECKOUT_HEAD" --checkout-version "$(cat "$REPO_ROOT/VERSION" 2>/dev/null)" 2>/dev/null)"; then
  while IFS='=' read -r key value; do
    case "$key" in
      RUNNING_COMMIT|RUNNING_COMMIT_SOURCE|CANDIDATE_COMMIT|CANDIDATE_VERSION|SNAPSHOT_TIME_KST)
        [[ "$value" =~ ^[0-9A-Za-z.:+-]+$ ]] && printf -v "$key" '%s' "$value" ;;
    esac
  done <<<"$PROVENANCE"
else
  warn "backup provenance helper unavailable (python3) - commits recorded as UNKNOWN"
fi
if [[ -z "$RUNTIME_VERSION" || -z "$MIGRATION_HEAD" ]]; then
  warn "backup metadata incomplete: runtime=$RUNTIME_VERSION migration=$MIGRATION_HEAD"
  warn "refusing a manifest that could mislabel the actual snapshot"
  exit 1
fi
[[ "$RUNNING_COMMIT" != UNKNOWN ]] \
  || warn "the running commit cannot be established (no image label, no v$RUNTIME_VERSION tag) - recorded as UNKNOWN"
file_size() { [[ -f "$1" ]] && stat -c '%s' "$1" || echo 0; }
file_sha() { [[ -f "$1" ]] && sha256sum "$1" | cut -d' ' -f1 || echo ""; }
cat > "$TARGET/manifest.json" <<JSON
{
  "name": "$NAME",
  "created_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "product_runtime_version": "$RUNTIME_VERSION",
  "product_commit": "$RUNNING_COMMIT",
  "running_commit_source": "$RUNNING_COMMIT_SOURCE",
  "candidate_commit": "$CANDIDATE_COMMIT",
  "candidate_version": "$CANDIDATE_VERSION",
  "snapshot_time_kst": "$SNAPSHOT_TIME_KST",
  "migration_head": "$MIGRATION_HEAD",
  "postgres": {"database": "$PG_DB", "status": "$PG_STATUS", "file": "postgres.dump",
               "bytes": $(file_size "$TARGET/postgres.dump"), "sha256": "$(file_sha "$TARGET/postgres.dump")"},
  "engine_sqlite": {"filename": "$ENGINE_DB_FILENAME", "status": "$ENGINE_STATUS", "file": "engine.sqlite3",
                    "bytes": $(file_size "$TARGET/engine.sqlite3"), "sha256": "$(file_sha "$TARGET/engine.sqlite3")"},
  "complete": $([[ "$PG_STATUS" == ok && "$ENGINE_STATUS" == ok ]] && echo true || echo false)
}
JSON

if [[ "$PG_STATUS" != ok || "$ENGINE_STATUS" != ok ]]; then
  warn "backup is INCOMPLETE: postgres=$PG_STATUS engine=$ENGINE_STATUS"
  warn "retention skipped: no older backup is pruned after a failed one"
  exit 1
fi

# --- access: what /status needs, and no more --------------------------------
chmod 0600 "$TARGET/postgres.dump" "$TARGET/engine.sqlite3"
chmod 0644 "$TARGET/manifest.json"
chmod 0711 "$TARGET"
# Read it back as the runtime reads it: inside the runtime container, as its
# own user, through its own mount. This is the check v0.96.51's first deploy
# lacked - a /tmp run on the host cannot see what uid 10001 sees.
ACCESS="$(compose exec -T runtime python - "${TARGET##*/}" 2>&1 <<'PY' | tr -d '\r' | tail -n 1 || true
import json
import os
import sys
from pathlib import Path

backup = Path(os.environ.get("DANCEMATE_BACKUP_DIR", "/var/backups/dancemate")) / sys.argv[1]
try:
    for name in ("postgres.dump", "engine.sqlite3"):
        if backup.joinpath(name).stat().st_size == 0:
            raise SystemExit(f"empty {name}")
    manifest = json.loads(backup.joinpath("manifest.json").read_text(encoding="utf-8"))
    if manifest.get("complete") is not True:
        raise SystemExit("manifest not complete")
except OSError as exc:
    raise SystemExit(f"{type(exc).__name__} on {Path(exc.filename or '?').name}")
private = not os.access(backup / "postgres.dump", os.R_OK)
print(f"ok uid={os.getuid()} dump_private={private}")
PY
)"
if [[ "$ACCESS" != ok* ]]; then
  warn "the runtime container cannot read this backup as /status will (${ACCESS:-no answer})"
  warn "retention skipped: a backup the runtime cannot see would make /status FAIL"
  exit 1
fi
log "  runtime access: $ACCESS"
[[ "$ACCESS" == *dump_private=True* ]] \
  || warn "the runtime container can read postgres.dump itself - the dumps should be private to $(id -un)"

mv -- "$TARGET" "$FINAL"
TARGET="$FINAL"
COMPLETE=1

# --- retention --------------------------------------------------------------
#
# Best-effort housekeeping: a backup that succeeded a moment ago must not be
# reported as failed because deleting an OLD one didn't work. This happens
# for real when a directory here is owned by someone else (root, from before
# the board's operator-only SSH policy) - hammer can list it but cannot write
# to it, so `rm -rf` fails partway through. That is a cleanup problem, not a
# backup problem, and cannot be escalated from here (no root); it is surfaced
# as a warning naming the exact directory so an operator can run
# scripts/fix-ownership.sh (or otherwise reclaim it) in a root session, and
# pruning moves on to whatever it CAN remove instead of aborting outright.
mapfile -t ALL < <(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'dancemate-backup-*' -printf '%f\n' | sort -r)
if (( ${#ALL[@]} > RETENTION )); then
  for old in "${ALL[@]:RETENTION}"; do
    log "  pruning old backup: $old"
    prune_err="$BACKUP_DIR/.prune.err.$$"
    if ! rm -rf -- "${BACKUP_DIR:?}/$old" 2>"$prune_err"; then
      warn "could not fully remove $old (likely owned by another user) - left in place, run scripts/fix-ownership.sh as root ('sudo scripts/fix-ownership.sh --backups --yes' reclaims just the backup directories; the next backup then prunes them)"
      cat "$prune_err" >&2 2>/dev/null || true
    fi
    rm -f "$prune_err" 2>/dev/null || true
  done
fi

# Failed attempts are evidence for a while, not forever: the newest 5 stay.
mapfile -t FAILED < <(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'failed-dancemate-backup-*' -printf '%f\n' | sort -r)
if (( ${#FAILED[@]} > 5 )); then
  for old in "${FAILED[@]:5}"; do
    rm -rf -- "${BACKUP_DIR:?}/$old" 2>/dev/null || warn "could not remove failed attempt $old"
  done
fi

log ""
log "backup complete: $TARGET"
log "retained: $(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'dancemate-backup-*' | wc -l) of max $RETENTION"
