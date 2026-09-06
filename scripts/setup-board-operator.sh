#!/usr/bin/env bash
set -euo pipefail

# DanceMate - provision an operator's public key for direct hammer SSH
# login (v0.82.8, "SSH Operator Hardening").
#
# hammer is the canonical repository/git/deploy user on the board (see
# deploy/rockpro64/README.md's "Canonical board workflow"). Before this
# script existed, reaching the board meant a root SSH session followed by
# `sudo -u hammer` for every repository command - convenient, but it made a
# root session the default habit, which is exactly how v0.82.6/v0.82.7's
# root-owned-file incidents happened. This script's only job is getting a
# trusted public key into hammer's own authorized_keys so a *direct* hammer
# login is possible in the first place.
#
# SAFETY:
#   - Public key only. This script never generates, reads, transmits or
#     otherwise handles a private key. Bring your own keypair (e.g.
#     `ssh-keygen -t ed25519`) and pass only the .pub line.
#   - Idempotent: adding the same key twice is a no-op, not a duplicate line.
#   - Scoped strictly to hammer's own home directory - never touches any
#     other account, never a system-wide permission change.
#   - Must run as root (or via sudo): creating *another* user's ~/.ssh with
#     the correct ownership is exactly the kind of one-time OS/service-level
#     bootstrap root remains for for (see scripts/fix-ownership.sh's own
#     header for the same reasoning about reclaiming a root-owned file) -
#     this script does not carry deploy-production.sh's guard_not_root for
#     that reason.
#   - Never disables or changes root SSH access, PermitRootLogin, or
#     PasswordAuthentication - provisioning a key and tightening sshd_config
#     are deliberately kept as two separate, separately-reviewed steps.
#
# Usage:
#   scripts/setup-board-operator.sh --public-key '<ssh-ed25519 AAAA... comment>' [--check]
#   scripts/setup-board-operator.sh --public-key-file /path/to/id_ed25519.pub [--check]
#
#   --check   print what would change, touch nothing.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

OPERATOR_USER="${DANCEMATE_OPERATOR_USER:-hammer}"
CHECK_ONLY=0
PUBLIC_KEY=""
PUBLIC_KEY_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-key) PUBLIC_KEY="${2:-}"; shift 2 ;;
    --public-key-file) PUBLIC_KEY_FILE="${2:-}"; shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    -h|--help) print_header_comment "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

if [[ -n "$PUBLIC_KEY_FILE" ]]; then
  [[ -f "$PUBLIC_KEY_FILE" ]] || die "no such file: $PUBLIC_KEY_FILE"
  PUBLIC_KEY="$(cat "$PUBLIC_KEY_FILE")"
fi
[[ -n "$PUBLIC_KEY" ]] || die "usage: scripts/setup-board-operator.sh --public-key '<ssh-... AAAA... comment>' [--check]  (or --public-key-file PATH)"

# A public key line is "type base64data [comment]" - never a private key,
# which starts with "-----BEGIN". Refuse to proceed rather than guess if
# something that looks like a private key was pasted in by mistake.
case "$PUBLIC_KEY" in
  ssh-*|ecdsa-*)
    ;;
  *)
    die "does not look like a public key line (expected it to start with e.g. 'ssh-ed25519'): refusing to write it to authorized_keys"
    ;;
esac

id "$OPERATOR_USER" >/dev/null 2>&1 || die "no such user: $OPERATOR_USER"
HOME_DIR="$(getent passwd "$OPERATOR_USER" | cut -d: -f6)"
[[ -n "$HOME_DIR" && -d "$HOME_DIR" ]] || die "cannot resolve a home directory for $OPERATOR_USER"
SSH_DIR="$HOME_DIR/.ssh"
AUTH_KEYS="$SSH_DIR/authorized_keys"

log "operator user : $OPERATOR_USER"
log "ssh directory : $SSH_DIR"
log "authorized_keys: $AUTH_KEYS"

already_present=0
if [[ -f "$AUTH_KEYS" ]] && grep -qxF "$PUBLIC_KEY" "$AUTH_KEYS" 2>/dev/null; then
  already_present=1
fi

if (( already_present )); then
  log "key already present in $AUTH_KEYS - nothing to do."
  exit 0
fi

if (( CHECK_ONLY )); then
  log "--check: would create/update $SSH_DIR (700) and $AUTH_KEYS (600, owner $OPERATOR_USER), then append the given key."
  exit 0
fi

install -d -o "$OPERATOR_USER" -g "$OPERATOR_USER" -m 700 "$SSH_DIR"
touch "$AUTH_KEYS"
chown "$OPERATOR_USER:$OPERATOR_USER" "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"
printf '%s\n' "$PUBLIC_KEY" >> "$AUTH_KEYS"
chown "$OPERATOR_USER:$OPERATOR_USER" "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

log "key added. Verify with a NEW, independent SSH connection before relying on it:"
log "  ssh $OPERATOR_USER@<board-address>"
log "This script never changes root SSH access - that is a separate, deliberate decision."
