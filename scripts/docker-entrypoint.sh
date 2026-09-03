#!/usr/bin/env bash
set -euo pipefail

# DanceMate container entrypoint.
#
# The Information Engine resolves its SQLite path from its own package root
# (engine/data/dancemate_ie_poc_v0.73.sqlite3, hardcoded in src/main.py). To
# make that persistent without patching engine source, a volume is mounted over
# /app/engine/data - which also hides the fixture/snapshot files the engine
# ships. This entrypoint seeds any missing fixture back into the volume on
# start, then execs the requested process.
#
# Seeding never overwrites an existing file, so operator data and the live
# SQLite database are left untouched.

SEED_DIR="${ENGINE_SEED_DIR:-/opt/dancemate/engine-data-seed}"
DATA_DIR="${ENGINE_CONTAINER_DATA_DIR:-/app/engine/data}"

if [[ -d "$SEED_DIR" ]]; then
  mkdir -p "$DATA_DIR"
  # -n: never clobber; -r: whole tree; preserves the engine fixture layout.
  cp -rn "$SEED_DIR/." "$DATA_DIR/" 2>/dev/null || true
  echo "entrypoint: engine data seeded into $DATA_DIR"
else
  echo "entrypoint: no seed directory at $SEED_DIR, skipping engine data seed"
fi

mkdir -p "${DANCEMATE_LOG_DIR:-/var/log/dancemate}" "${DANCEMATE_DATA_DIR:-/var/lib/dancemate}" || true

exec "$@"
