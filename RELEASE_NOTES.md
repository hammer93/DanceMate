# DanceMate Release Notes

## v0.74 Persistent Runtime + ROCKPro64 Staging Deployment

Status:
DEPLOYED AND VERIFIED on the ROCKPro64 (PINE64 v2.1 / RK3399 / aarch64,
Armbian 26.8.3 / Debian 13.6, kernel 6.18.44), 2026-09-03.
Runtime root /opt/dancemate/app/DanceMate, LAN only at 192.168.1.100:8080.

Version split:

- Product Runtime: 0.74
- Information Engine: 0.73 (imported unchanged, see below)

Included:

- ARM64 Linux runtime image (`python:3.12-slim`, no compiler toolchain needed;
  one image serves both the runtime API and the scheduler worker)
- Docker Compose stack: `postgres` + `runtime` + `scheduler`, PostgreSQL
  healthcheck, ordered startup, `restart: unless-stopped`
- PostgreSQL runtime persistence: `runtime_state`, `scheduler_heartbeat`,
  `job_runs`, plus a forward-only migration runner with checksummed
  `schema_migrations`
- Scheduler: single-process periodic worker, heartbeat floored at 30s,
  job history, graceful SIGTERM/SIGINT shutdown
- Runtime API (LAN only, unauthenticated): `/health`, `/version`, `/status`,
  `/status/summary`, `/resources`
- Health / Status: six components (Runtime, Database, Scheduler, Information,
  Storage, Backup) each PASS / WARN / FAIL; `/status` answers 503 on FAIL
- Information Engine adapter: import check, persistence-path check and a
  read-only CLI smoke command; engine source is not modified
- Engine persistent SQLite via a volume over `/app/engine/data`, with an
  entrypoint that re-seeds the engine's fixture files without overwriting data
- Backup: `pg_dump` custom format plus a SQLite online-backup snapshot,
  timestamped directories, manifest, retention (default 7)
- Restore: explicit backup name required, dry run by default, `--yes` to apply,
  scheduler stopped during the restore, pre-restore safety copy
- Log rotation: `max-size: 10m` / `max-file: 3` on every service, uvicorn
  access logging disabled
- Resource check: CPU load, memory and disk with 75% / 95% warning bands
- Deployment scripts: `install-rockpro64.sh` (host readiness; never pipes a
  remote installer into a shell), `start-server.sh`, `stop-server.sh`
  (never `down -v`), `check-server.sh`, `backup.sh`, `restore.sh`
- 133 product runtime tests

Information Engine v0.73 baseline:

- imported from `Backup/DanceMate-InformationEngine-PoC-v0.73.zip` into
  `engine/`, byte-identical to the archive, tagged `v0.73`
- 559 tests collected, 559 passed (CPython 3.11 on the host, and re-run inside
  the Python 3.12 runtime image)
- no Windows-specific code, no `subprocess`, no absolute paths: standard
  library only, Python >= 3.10 (PEP 604 annotations)

Deliberately NOT done in v0.74:

- no Information Engine algorithm changes; v0.74 is a runtime/deployment version
- no PostgreSQL migration of the engine's own database (hybrid persistence)
- no real Dance Event source collectors (v0.75)
- no Human Verification Console (v0.76)
- no Kubernetes, Redis, Kafka, Celery or service mesh

Verified on the development host:

- `docker compose config` valid; stack starts and reports healthy
- migration applied once, then `applied=[]` on every restart
- scheduler heartbeat and job history written to PostgreSQL
- one engine fixture batch processed: `Fixture Gate: PASS (4/4)`
- runtime state and the engine SQLite store survive `docker compose restart`
  and full container recreation
- backup produces a valid PostgreSQL dump and a readable engine database
- restore replaces runtime state and keeps a pre-restore copy
- `check-server.sh`: six PASS, exit 0; exit 1 on a component FAIL;
  exit 2 when the runtime is unreachable
- image builds for `linux/arm64` via buildx

### ROCKPro64 Acceptance (2026-09-03)

Deployment shape: the board already ran a `dancemate-postgres` container on
the `dancemate-net` network, so v0.74 was deployed with
`deploy/rockpro64/docker-compose.external-postgres.yml` - runtime + scheduler
only, against that existing database. The board's existing caddy and postgres
compose projects were left untouched throughout.

ROCKPro64 Runtime:
VERIFIED - image built natively on aarch64, runtime and scheduler healthy

Host Reboot:
PASS - two full `systemctl reboot` cycles; all four containers back within
~15s of boot with no manual start, `docker.service` enabled + restart:
unless-stopped

PostgreSQL Persistence:
PASS - job_runs rows written before the reboot (ids 1-8) still present after,
with new rows appended; schema_migrations unchanged, `applied=[]` on restart

Information Engine Persistence:
PASS - engine SQLite kept the same inode, size and mtime across both reboots;
Recommendation Runtime Outcome ROCKPRO-ACCEPTANCE-001 still
RECOMMENDATION_HELPFUL afterwards

Runtime Outcome Persistence:
PASS - v0.73 Recommendation Runtime Outcome and Selection Effectiveness
records verified present after each reboot

Scheduler Recovery:
PASS - scheduler restarted automatically and wrote a fresh heartbeat
(distinguishable from the pre-reboot beat by timestamp); heartbeat 60s,
job cycle 300s

Post-Reboot Processing:
PASS - engine fixture re-run `Fixture Gate: PASS (4/4)`, plus new markers
ROCKPRO-ACCEPTANCE-002 (after reboot 1) and -003 (after reboot 2)

Backup:
PASS - `pg_restore --list` reads the dump (custom format, 22 TOC entries);
`PRAGMA integrity_check` on the SQLite copy returns ok with 196 tables and the
outcome row present; no credential appears in any backup artifact

API:
PASS - /health, /version, /status, /status/summary reachable from the board
and from a LAN client; published on 192.168.1.100:8080 only, not on the
board's WiFi address and not on loopback

Health Check:
PASS - `check-server.sh` reports all six components PASS, exit 0

Resource usage on the board (idle, all four containers):
runtime 59MB, scheduler 42MB, postgres 51MB, caddy 49MB of 3.8GB;
microSD 10% used; container logs capped 10m x 3 at both daemon and service level

Problems found and fixed during deployment (each fixed in the repository, then
redeployed and re-verified - never patched on the board):

1. DANCEMATE_BIND_ADDRESS was used both as the host publish interface and as
   uvicorn's in-container listen address. Narrowing it to the board's LAN IP
   crash-looped the runtime with "could not bind on any address". Split into
   DANCEMATE_BIND_ADDRESS (host) and DANCEMATE_HOST (container, pinned to
   0.0.0.0 by both compose files).
2. check-server.sh probed 127.0.0.1 unconditionally, which no longer listens
   once the binding is narrowed. The probe host now follows the binding.
3. The acceptance tool was excluded from the image by .dockerignore and had no
   COPY in the Dockerfile.
4. The acceptance tool hardcoded family_recovery_case_id = 1, so a second
   marker hit a UNIQUE constraint. It now allocates the next free id.

NOT verified even now:

- long-term microSD write behaviour (only a few hours of runtime observed)
- 4GB RAM headroom under sustained real load (no real source data yet)
- behaviour on the final wired LAN once the board moves off the temporary
  direct-attach segment documented in the board's own ROCKPRO64_SETUP.md

Next:
v0.75 Real Source Intake (Daum Cafe / Naver Cafe / Naver Blog collectors),
after the ROCKPro64 staging deployment and reboot acceptance are signed off.

## v0.73 Repository Baseline

Status:
Repository skeleton initialized.

Included:
- Product repository structure
- ROCKPro64 deployment directory
- Runtime/Collector/Scheduler/Admin placeholders
- Git ignore rules
- Environment template
- Operations script placeholders

Not Included Yet:
- Information Engine source import
- PostgreSQL
- Runtime API
- Scheduler implementation
- ROCKPro64 deployment
- Real Event Collectors

Next:
v0.74 Persistent Runtime + ROCKPro64 Staging Deployment
