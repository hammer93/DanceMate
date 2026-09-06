#!/usr/bin/env bash
set -euo pipefail

# DanceMate - run a git command against this checkout as its own owner,
# regardless of which user actually invoked this script (v0.82.7,
# "Board Git Ownership Guard").
#
# Incident: 21 tracked files on the ROCKPro64 board turned up owned by root
# instead of the repository's own user, `hammer` - the result of `git
# fetch`/`git merge` typed directly over a root SSH session during earlier
# releases' "board sync" steps. git happily lets root touch a hammer-owned
# checkout; whatever it writes then belongs to root.
#
# This is the canonical way to run git against the board checkout from now
# on: `scripts/board-git.sh fetch --tags origin`, `scripts/board-git.sh
# merge --ff-only origin/main`, etc. Already running as the repository's own
# owner just runs git directly; running as anyone else (root included) hands
# the command to `sudo -u <owner>` instead of guessing or refusing.
#
# Usage: scripts/board-git.sh <git arguments...>

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

[[ $# -gt 0 ]] || die "usage: scripts/board-git.sh <git arguments...>"

OWNER="$(repo_owner)"

if [[ "$(id -un)" == "$OWNER" ]]; then
  exec git -C "$REPO_ROOT" "$@"
fi

command -v sudo >/dev/null 2>&1 \
  || die "not running as '$OWNER' and 'sudo' is not available to become it - log in as $OWNER directly"
exec sudo -u "$OWNER" git -C "$REPO_ROOT" "$@"
