#!/usr/bin/env bash
set -euo pipefail

# DanceMate - operations monitor (v0.96.51).
#
# One check, then exit. Meant for a systemd timer (deploy/rockpro64/systemd/
# dancemate-ops-monitor.timer, every 5 minutes), never a loop and never the
# collection scheduler: it reads, it does not run jobs or start containers.
#
# Facts gathered:
#   runtime container running      docker compose ps
#   scheduler container count      the deploy guard's own two-signal count
#   readiness                      GET /status        (JSON; NOT /health, which
#                                                      is liveness and stays 200
#                                                      with the database down)
#   source health                  GET /health/sources
#   job streaks / extraction       python -m runtime.ops_facts in the runtime
#   data disk free                 df on the backup directory's filesystem
#
# runtime/ops_alerts.py (host python3, standard library only) turns them into
# alerts with thresholds, de-duplication, a cooldown and recovery notices,
# appended to $OPS_DIR/alerts.log (JSON lines) and printed to the journal.
# No external channel is configured; none is assumed.
#
#   scripts/ops-monitor.sh            one check
#   scripts/ops-monitor.sh --status   print the open alerts and the last notices
#
# Exit codes: 0 no open critical alert, 1 an open critical alert.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
guard_not_root "$0"

LOG_DIR="$(env_value DANCEMATE_LOG_DIR || true)"
OPS_DIR="$(env_value DANCEMATE_OPS_DIR || true)"
if [[ -z "$OPS_DIR" ]]; then
  if [[ -n "$LOG_DIR" ]]; then OPS_DIR="$(dirname "$LOG_DIR")/ops"; else OPS_DIR="$REPO_ROOT/logs/ops"; fi
fi
[[ "$OPS_DIR" = /* ]] || OPS_DIR="$REPO_ROOT/${OPS_DIR#./}"
umask 077
mkdir -p "$OPS_DIR"
STATE="$OPS_DIR/monitor-state.json"
ALERTS="$OPS_DIR/alerts.log"

if [[ "${1:-}" == "--status" ]]; then
  log "state: $STATE"
  [[ -f "$STATE" ]] && cat "$STATE" || log "(no check has run yet)"
  log ""
  log "last notices ($ALERTS):"
  [[ -f "$ALERTS" ]] && tail -n 20 "$ALERTS" || log "(none)"
  exit 0
fi

exec 9>"$OPS_DIR/.monitor.lock"
flock -n 9 || { log "ops-monitor: another check is running - skipped"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

RUNNING=0
if [[ -n "$(compose ps -q --status running runtime 2>/dev/null || true)" ]]; then
  RUNNING=1
fi
SCHEDULERS="$(count_scheduler_containers)"

URL="$(runtime_url)"
# /status answers 503 *with* its JSON body when a component FAILs - that body
# is the finding. Only no body at all means unreachable.
curl --silent --max-time 15 --output "$WORK/status.json" "$URL/status" || rm -f "$WORK/status.json"
curl --silent --max-time 20 --output "$WORK/sources.json" "$URL/health/sources" || rm -f "$WORK/sources.json"
if (( RUNNING )); then
  timeout 60 docker exec -i "$(compose ps -q runtime | head -n 1)" python -m runtime.ops_facts \
    > "$WORK/db.json" 2>/dev/null || true
fi

BACKUP_DIR="$(env_value DANCEMATE_BACKUP_DIR || true)"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/backup}"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$REPO_ROOT/${BACKUP_DIR#./}"
FREE_ARGS=()
if FREE_PCT="$(df -P "$BACKUP_DIR" 2>/dev/null | awk 'NR==2 { gsub("%","",$5); print 100-$5 }')" \
   && [[ -n "$FREE_PCT" ]]; then
  FREE_ARGS=(--disk-free-pct "$FREE_PCT")
fi

cd "$REPO_ROOT"
# v0.96.52: an external channel, if one is configured in .env - handed over in
# the environment only (never on the command line, never logged).
OPS_ALERT_WEBHOOK_URL="$(env_value OPS_ALERT_WEBHOOK_URL || true)" python3 -m runtime.ops_alerts \
  --state "$STATE" --log "$ALERTS" \
  --status-file "$WORK/status.json" --sources-file "$WORK/sources.json" --db-file "$WORK/db.json" \
  --runtime-running "$RUNNING" --scheduler-count "$SCHEDULERS" "${FREE_ARGS[@]}"
