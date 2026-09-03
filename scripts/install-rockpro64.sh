#!/usr/bin/env bash
set -euo pipefail

# DanceMate - ROCKPro64 host preparation.
#
# Target: PINE64 ROCKPro64 v2.1 / RK3399 / ARM64 / Armbian 26.8.3
#         (Debian 13 Trixie, kernel 6.18.x), 4GB RAM, 32GB microSD, LAN only.
#
# This script PREPARES a host. It never pipes a remote installer into a shell
# and it never installs Docker on its own: if Docker is missing it prints the
# distribution's documented commands and stops, so the operator stays in
# control of what lands on the board.
#
# Usage:
#   scripts/install-rockpro64.sh            # check the host and report
#   scripts/install-rockpro64.sh --prepare  # also create directories and .env

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PREPARE=0
for arg in "$@"; do
  case "$arg" in
    --prepare) PREPARE=1 ;;
    -h|--help) print_header_comment "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

FAILURES=0
pass() { printf '  PASS  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
info() { printf '  ..    %s\n' "$*"; }

log "DanceMate ROCKPro64 host check"
log ""

log "architecture"
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) pass "$ARCH (ARM64 target)" ;;
  x86_64)        info "$ARCH - not the ROCKPro64 target; continuing for a dev host" ;;
  *)             fail "$ARCH is not a supported architecture" ;;
esac

log "operating system"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  OS_NAME="$(. /etc/os-release && printf '%s %s' "${NAME:-?}" "${VERSION_ID:-?}")"
  case "$OS_NAME" in
    Debian*13*|*Trixie*|*trixie*) pass "$OS_NAME" ;;
    *)                            info "$OS_NAME - expected Debian 13 (Trixie)" ;;
  esac
  info "kernel $(uname -r)"
else
  fail "/etc/os-release not readable - cannot identify the OS"
fi

log "memory and storage"
if [[ -r /proc/meminfo ]]; then
  MEM_MB=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1024 ))
  if (( MEM_MB >= 3500 )); then pass "${MEM_MB}MB RAM"; else fail "${MEM_MB}MB RAM (4GB expected)"; fi
else
  info "cannot read /proc/meminfo"
fi
ROOT_FREE_GB=$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)
if (( ROOT_FREE_GB >= 8 )); then pass "${ROOT_FREE_GB}GB free on /"; else fail "${ROOT_FREE_GB}GB free on / (>= 8GB recommended)"; fi

log "docker"
if command -v docker >/dev/null 2>&1; then
  pass "docker $(docker --version | awk '{print $3}' | tr -d ,)"
  if docker compose version >/dev/null 2>&1; then
    pass "compose plugin $(docker compose version --short 2>/dev/null || echo present)"
  else
    fail "the 'docker compose' plugin is missing (docker-compose v1 is not supported)"
    log "        install with: sudo apt-get install -y docker-compose-plugin"
  fi
  if docker info >/dev/null 2>&1; then
    pass "docker daemon reachable as $(id -un)"
  else
    fail "docker daemon not reachable as $(id -un)"
    log "        add the user to the docker group: sudo usermod -aG docker $(id -un) && newgrp docker"
  fi
else
  fail "docker is not installed"
  log ""
  log "  Install Docker Engine on Debian 13 (arm64) with the official repository:"
  log "    sudo apt-get update"
  log "    sudo apt-get install -y ca-certificates curl"
  log "    sudo install -m 0755 -d /etc/apt/keyrings"
  log "    sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc"
  log "    sudo chmod a+r /etc/apt/keyrings/docker.asc"
  log "    echo \"deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian trixie stable\" | sudo tee /etc/apt/sources.list.d/docker.list"
  log "    sudo apt-get update"
  log "    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin"
  log ""
  log "  This script deliberately does not run those commands for you."
fi

log "configuration"
if [[ -f "$ENV_FILE" ]]; then
  if validate_env; then pass ".env present and valid"; else fail ".env has the problems listed above"; fi
else
  fail ".env not found at $ENV_FILE"
fi

log "directories"
for key in ENGINE_DATA_DIR DANCEMATE_DATA_DIR DANCEMATE_LOG_DIR DANCEMATE_BACKUP_DIR; do
  dir="$(env_value "$key" || true)"
  if [[ -z "$dir" ]]; then info "$key not set in .env"; continue; fi
  [[ "$dir" = /* ]] || dir="$REPO_ROOT/${dir#./}"
  if [[ -d "$dir" && -w "$dir" ]]; then
    pass "$key -> $dir"
  elif (( PREPARE )); then
    mkdir -p "$dir" && pass "$key -> $dir (created)" || fail "$key -> cannot create $dir"
  else
    fail "$key -> $dir missing or not writable (re-run with --prepare)"
  fi
done

if (( PREPARE )) && [[ ! -f "$ENV_FILE" ]]; then
  cp "$REPO_ROOT/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  log ""
  log "created $ENV_FILE from .env.example (mode 600)."
  log "Set a real POSTGRES_PASSWORD before starting, e.g.:"
  log "  openssl rand -base64 24"
fi

log ""
log "network policy reminder: LAN only. No WAN port forwarding to ${DANCEMATE_PORT:-8080}."
log ""
if (( FAILURES == 0 )); then
  log "host check: PASS - run scripts/start-server.sh next"
  exit 0
fi
log "host check: $FAILURES problem(s) found - resolve them before deploying"
exit 1
