#!/usr/bin/env bash
set -euo pipefail

# DanceMate - copy the newest backup off this machine, encrypted (v0.96.52).
#
# Every backup scripts/backup.sh makes lives on the board's own SD card, next
# to the database it protects: one lost card loses both. This script sends the
# newest complete backup somewhere else - and only somewhere else. Nothing is
# configured by default, and nothing is assumed: until an operator chooses a
# destination and an encryption key, the status is PENDING_CONFIGURATION and
# the script copies nothing.
#
# Configuration (.env, all required except where noted):
#   OFFHOST_BACKUP_DEST           rsync destination ON ANOTHER HOST,
#                                 user@host:/path (a local path is refused:
#                                 another folder on this card is not off-host)
#   OFFHOST_BACKUP_GPG_RECIPIENT  fingerprint of a PUBLIC key in the backup
#                                 owner's keyring; every file is encrypted to
#                                 it before it leaves. The private key must
#                                 not be on this board.
#   OFFHOST_BACKUP_RETENTION      backups kept at the destination (default 14)
#   OFFHOST_BACKUP_RSH            remote shell for rsync (default
#                                 "ssh -o BatchMode=yes")
#
# Usage:
#   scripts/offhost-backup.sh --check   configuration status only; copies
#                                       nothing. Exit 0 READY, 3
#                                       PENDING_CONFIGURATION, 2 INVALID.
#   scripts/offhost-backup.sh           encrypt, send, verify, prune remote
#
# What a run does:
#   1. picks the newest backup whose manifest says complete;
#   2. encrypts each file to the recipient (gpg, public key) in a private
#      temporary directory - plaintext never leaves the board;
#   3. writes OFFHOST.json beside them: the backup's name and the SHA-256 of
#      each encrypted file (no data, no secret);
#   4. rsyncs the directory to DEST/<name>/;
#   5. verifies with a checksum comparison against what arrived - a copy that
#      does not compare is a failure;
#   6. keeps the newest OFFHOST_BACKUP_RETENTION backups at the destination.
# The result (OK / FAILED, when, which backup) goes to
# $(dirname DANCEMATE_LOG_DIR)/ops/offhost-last.json and the journal. Any
# failure exits non-zero and changes nothing at the destination's older copies.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

CHECK_ONLY=0
case "${1:-}" in
  --check) CHECK_ONLY=1 ;;
  "") ;;
  -h|--help) print_header_comment "${BASH_SOURCE[0]}"; exit 0 ;;
  *) die "unknown argument: $1 (only --check is supported)" ;;
esac

DEST="$(env_value OFFHOST_BACKUP_DEST || true)"
RECIPIENT="$(env_value OFFHOST_BACKUP_GPG_RECIPIENT || true)"
RETENTION="$(env_value OFFHOST_BACKUP_RETENTION || true)"
RETENTION="${RETENTION:-14}"
RSH="$(env_value OFFHOST_BACKUP_RSH || true)"
RSH="${RSH:-ssh -o BatchMode=yes}"

status() { printf 'OFFHOST_BACKUP: %s\n' "$*"; }

# --- configuration ----------------------------------------------------------
if [[ -z "$DEST" && -z "$RECIPIENT" ]]; then
  status "PENDING_CONFIGURATION - no destination and no encryption key are configured (OFFHOST_BACKUP_DEST, OFFHOST_BACKUP_GPG_RECIPIENT)"
  exit 3
fi
invalid() { status "INVALID_CONFIGURATION - $*"; exit 2; }
[[ -n "$DEST" ]] || invalid "OFFHOST_BACKUP_DEST is not set"
[[ -n "$RECIPIENT" ]] || invalid "OFFHOST_BACKUP_GPG_RECIPIENT is not set - nothing leaves this board unencrypted"
# user@host:/path or host:/path - a host part before the colon, an absolute
# path after it. Anything else (a local path, rsync://, a bare folder) is not
# a copy to another machine.
[[ "$DEST" != *://* && "$DEST" =~ ^([A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+:/[^[:space:]]*$ ]] \
  || invalid "OFFHOST_BACKUP_DEST must be user@host:/absolute/path on another host (a local path is not off-host)"
DEST_HOST="${DEST%%:*}"
DEST_PATH="${DEST#*:}"
case "${DEST_HOST#*@}" in
  localhost|127.*|::1) invalid "OFFHOST_BACKUP_DEST points at this machine" ;;
esac
[[ "$RETENTION" =~ ^[0-9]+$ && "$RETENTION" -ge 1 ]] || invalid "OFFHOST_BACKUP_RETENTION must be >= 1"
[[ "$RECIPIENT" =~ ^[0-9A-Fa-f]{16,40}$ ]] \
  || invalid "OFFHOST_BACKUP_GPG_RECIPIENT must be a key fingerprint (hex)"
command -v gpg >/dev/null 2>&1 || invalid "gpg is not installed"
command -v rsync >/dev/null 2>&1 || invalid "rsync is not installed"
gpg --batch --list-keys "$RECIPIENT" >/dev/null 2>&1 \
  || invalid "no public key $RECIPIENT in $(id -un)'s keyring"
if gpg --batch --list-secret-keys "$RECIPIENT" >/dev/null 2>&1; then
  invalid "the PRIVATE key for $RECIPIENT is on this board - a stolen card would carry the key with the backups; keep only the public key here"
fi

if (( CHECK_ONLY )); then
  status "READY - destination ${DEST_HOST}:${DEST_PATH}, encrypted to ${RECIPIENT}, keeping ${RETENTION}"
  exit 0
fi

# --- run --------------------------------------------------------------------
guard_not_root "$0"
BACKUP_DIR="$(env_value DANCEMATE_BACKUP_DIR || true)"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backup}"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$REPO_ROOT/${BACKUP_DIR#./}"
LOG_DIR="$(env_value DANCEMATE_LOG_DIR || true)"
OPS_DIR="$(dirname "${LOG_DIR:-$REPO_ROOT/logs/runtime}")/ops"
mkdir -p "$OPS_DIR"
RESULT="$OPS_DIR/offhost-last.json"

NAME=""
while read -r candidate; do
  if grep -q '"complete": true' "$BACKUP_DIR/$candidate/manifest.json" 2>/dev/null; then
    NAME="$candidate"
    break
  fi
done < <(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'dancemate-backup-*' -printf '%f\n' | sort -r)

record() {   # record OK|FAILED detail
  local apostrophe="'" detail
  detail="${2//\"/$apostrophe}"
  printf '{"at_kst": "%s", "result": "%s", "backup": "%s", "destination_host": "%s", "detail": "%s"}\n' \
    "$(TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S+09:00)" "$1" "${NAME:-}" "$DEST_HOST" "$detail" > "$RESULT.tmp"
  mv -f "$RESULT.tmp" "$RESULT"
}
fail() { record FAILED "$*"; status "FAILED - $*"; exit 1; }

[[ -n "$NAME" ]] || fail "no complete backup under $BACKUP_DIR"
WORK="$(mktemp -d)"
chmod 0700 "$WORK"
trap 'rm -rf "$WORK"' EXIT
mkdir "$WORK/$NAME"
log "off-host copy of $NAME -> ${DEST_HOST}:${DEST_PATH}/$NAME"

for part in "$BACKUP_DIR/$NAME"/*; do
  [[ -f "$part" ]] || continue
  gpg --batch --yes --trust-model always --recipient "$RECIPIENT" \
      --output "$WORK/$NAME/$(basename "$part").gpg" --encrypt "$part" \
    || fail "encrypting $(basename "$part") failed"
done
{
  printf '{\n  "backup": "%s",\n  "encrypted_to": "%s",\n  "files": {' "$NAME" "$RECIPIENT"
  first=1
  for enc in "$WORK/$NAME"/*.gpg; do
    (( first )) || printf ','
    first=0
    printf '\n    "%s": "%s"' "$(basename "$enc")" "$(sha256sum "$enc" | cut -d' ' -f1)"
  done
  printf '\n  }\n}\n'
} > "$WORK/$NAME/OFFHOST.json"

# shellcheck disable=SC2086 # RSH is a command line by design
$RSH "$DEST_HOST" "mkdir -p '$DEST_PATH'" || fail "cannot create $DEST_PATH on $DEST_HOST"
RSYNC_MODES=(--chmod=D0700,F0600)
rsync -a "${RSYNC_MODES[@]}" -e "$RSH" "$WORK/$NAME/" "$DEST_HOST:$DEST_PATH/$NAME/" \
  || fail "rsync to $DEST_HOST failed"
# Verified only if a full checksum comparison finds nothing left to send -
# with the same modes as the send, or every file would differ in mode alone.
DIFF="$(rsync -a "${RSYNC_MODES[@]}" --checksum --dry-run --itemize-changes -e "$RSH" \
          "$WORK/$NAME/" "$DEST_HOST:$DEST_PATH/$NAME/" 2>&1)" \
  || fail "verification against $DEST_HOST failed"
[[ -z "$DIFF" ]] || fail "the copy at $DEST_HOST does not match: $(printf '%s' "$DIFF" | head -n 3 | tr '\n' ' ')"

# Remote retention: newest first by name (names are timestamps).
# shellcheck disable=SC2086
REMOTE="$($RSH "$DEST_HOST" "ls -1 '$DEST_PATH'" 2>/dev/null | grep '^dancemate-backup-' | sort -r || true)"
pruned=0
while read -r old; do
  [[ -n "$old" ]] || continue
  # shellcheck disable=SC2086
  $RSH "$DEST_HOST" "rm -rf -- '$DEST_PATH/$old'" && pruned=$((pruned + 1)) \
    || warn "could not prune $old at $DEST_HOST"
done < <(printf '%s\n' "$REMOTE" | tail -n +"$((RETENTION + 1))")

record OK "sent, verified by checksum, pruned $pruned"
status "OK - $NAME sent to $DEST_HOST, verified, $pruned old copy(ies) pruned"
