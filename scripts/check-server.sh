#!/usr/bin/env bash
set -euo pipefail

# DanceMate - server health check.
#
# Prints the operator report and exits non-zero if any component FAILs:
#
#   DanceMate Server
#   Runtime ........ PASS
#   Database ....... PASS
#   Scheduler ...... PASS
#   Information .... PASS
#   Storage ........ PASS
#   Backup ......... PASS
#
# Every line comes from the running runtime's /status/summary endpoint, which
# measures the real component. Nothing here prints PASS without a measurement.
#
# The endpoint answers HTTP 503 *with a full report body* when a component
# FAILs; that is a successful check of an unhealthy server, not a transport
# failure. Only an unreachable runtime produces no report at all.
#
# Exit codes: 0 all PASS (or WARN), 1 a component FAILed, 2 runtime unreachable.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

URL="$(runtime_url)/status/summary"
ERR_FILE="$(mktemp)"
trap 'rm -f "$ERR_FILE"' EXIT

body=""
transport_error=""

if command -v curl >/dev/null 2>&1; then
  # Body and status code in one call; stderr kept out of the body.
  if raw="$(curl --silent --show-error --max-time 15 --write-out $'\n%{http_code}' "$URL" 2>"$ERR_FILE")"; then
    body="${raw%$'\n'*}"
  else
    transport_error="$(cat "$ERR_FILE")"
  fi
elif command -v wget >/dev/null 2>&1; then
  # --content-on-error keeps the 503 report instead of discarding it.
  if body="$(wget --quiet --timeout=15 --content-on-error --output-document=- "$URL" 2>"$ERR_FILE")"; then
    :
  else
    if [[ -z "$body" ]]; then
      transport_error="$(cat "$ERR_FILE")"
    fi
  fi
else
  die "neither curl nor wget is available to query $URL"
fi

if [[ "$body" != "DanceMate Server"* ]]; then
  printf 'DanceMate Server\n'
  printf 'Runtime ........ FAIL\n'
  printf '\nruntime NOT REACHABLE at %s\n' "$URL"
  [[ -n "$transport_error" ]] && printf 'detail: %s\n' "$transport_error"
  [[ -n "$body" ]] && printf 'unexpected body: %s\n' "$body"
  exit 2
fi

printf '%s\n' "$body"

if printf '%s' "$body" | grep -q 'FAIL'; then
  exit 1
fi
if printf '%s' "$body" | grep -q 'WARN'; then
  printf '\nsome components are in WARN; see %s/status for detail\n' "$(runtime_url)"
fi
exit 0
