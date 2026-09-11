#!/usr/bin/env bash
set -euo pipefail

# DanceMate - the approved narrow fallback for a working tree left with
# foreign-owned tracked files.
#
# verify_repo_ownership (in _common.sh, run by start-server.sh and
# run-container-tests.sh) FAILs loudly the moment this happens rather than
# letting it silently break the next `git checkout`/`pull`. The right fix is
# always to find and correct *why* something wrote as a different user (see
# container_run_as_repo_owner's comment in _common.sh for the root cause this
# project has hit before) - this script is only for clearing an
# already-broken tree so work can continue, scoped strictly to the
# repository path, never a broader system chown.
#
# v0.82.7: this is the one repository-touching script that deliberately does
# NOT refuse to run as root (unlike scripts/deploy-production.sh's own
# guard_not_root) - reclaiming a file that a previous mistake left root-owned
# requires root's own chown privilege; a non-root user cannot take ownership
# away from root. Run it as root (or `sudo`) specifically to clean up a
# root-owned drift; scripts/board-git.sh and scripts/deploy-production.sh
# existing is what should make root-owned drift stop recurring in the first
# place, so this script is the fallback, not the routine.
#
# Usage: scripts/fix-ownership.sh [--yes]
#        scripts/fix-ownership.sh --backups [--yes]
#   Without --yes, prints what would change and exits without touching
#   anything.
#
# --backups (v0.86.9): reclaim backup directories a root session created, so
#   scripts/backup.sh's own retention (which runs as the repository owner) can
#   prune them when their turn comes. Scoped to `dancemate-backup-*`
#   directories directly under DANCEMATE_BACKUP_DIR that are NOT already owned
#   by the repository owner - never the backup directory itself, never
#   anything else in it, and it deletes nothing: which backups are old enough
#   to go is still decided by retention alone.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

owner_uid="$(stat -c '%u' "$REPO_ROOT")"
owner_gid="$(stat -c '%g' "$REPO_ROOT")"
owner_name="$(stat -c '%U' "$REPO_ROOT")"
owner_group="$(stat -c '%G' "$REPO_ROOT")"

if [[ "${1:-}" == "--backups" ]]; then
  apply=0
  [[ "${2:-}" == "--yes" ]] && apply=1
  backup_dir="$(env_value DANCEMATE_BACKUP_DIR || true)"
  backup_dir="${backup_dir:-$REPO_ROOT/backup}"
  [[ "$backup_dir" = /* ]] || backup_dir="$REPO_ROOT/${backup_dir#./}"
  [[ -d "$backup_dir" ]] || die "no backup directory: $backup_dir"
  mapfile -t foreign < <(
    find "$backup_dir" -mindepth 1 -maxdepth 1 -type d -name 'dancemate-backup-*' \
      -not -uid "$owner_uid" -printf '%f\n' 2>/dev/null | sort
  )
  if [[ ${#foreign[@]} -eq 0 ]]; then
    log "no foreign-owned backup directories under $backup_dir - nothing to do."
    exit 0
  fi
  log "${#foreign[@]} backup director(ies) under $backup_dir not owned by ${owner_name}:${owner_group}:"
  for name in "${foreign[@]}"; do
    log "  $name  (owner $(stat -c '%U:%G' "$backup_dir/$name"))"
  done
  if (( apply != 1 )); then
    log ""
    log "dry run only - re-run as root: scripts/fix-ownership.sh --backups --yes"
    exit 0
  fi
  [[ "$(id -u)" -eq 0 ]] || die "--backups --yes must run as root: only root can take a directory back from root"
  for name in "${foreign[@]}"; do
    chown -R "${owner_uid}:${owner_gid}" -- "$backup_dir/$name"
  done
  log "reclaimed ${#foreign[@]} backup director(ies) for ${owner_name}. Nothing was deleted -"
  log "scripts/backup.sh's retention decides which backups are old enough to prune."
  exit 0
fi

mapfile -t bad < <(
  git -C "$REPO_ROOT" ls-files -z 2>/dev/null \
    | xargs -0 -I{} find "$REPO_ROOT/{}" -maxdepth 0 -not -uid "$owner_uid" \
        -printf '%p\n' 2>/dev/null
)

if [[ ${#bad[@]} -eq 0 ]]; then
  log "no foreign-owned tracked files under $REPO_ROOT - nothing to do."
  exit 0
fi

log "${#bad[@]} tracked file(s) not owned by ${owner_name}:${owner_group} (uid $owner_uid):"
printf '  %s\n' "${bad[@]}"

if [[ "${1:-}" != "--yes" ]]; then
  log ""
  log "dry run only - re-run as: scripts/fix-ownership.sh --yes"
  exit 0
fi

log ""
log "chown -R ${owner_name}:${owner_group} \"$REPO_ROOT\" (scoped to the repository path only)"
chown -R "${owner_uid}:${owner_gid}" "$REPO_ROOT"
verify_repo_ownership
log "ownership fixed."
