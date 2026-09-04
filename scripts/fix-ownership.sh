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
# Usage: scripts/fix-ownership.sh [--yes]
#   Without --yes, prints what would change and exits without touching
#   anything.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

owner_uid="$(stat -c '%u' "$REPO_ROOT")"
owner_gid="$(stat -c '%g' "$REPO_ROOT")"
owner_name="$(stat -c '%U' "$REPO_ROOT")"
owner_group="$(stat -c '%G' "$REPO_ROOT")"

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
