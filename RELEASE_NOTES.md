# DanceMate Release Notes

## v0.74 Persistent Runtime + ROCKPro64 Staging Deployment

Status:
Deployment Candidate. Verified on an amd64 development host with Docker.
NOT yet deployed to, or verified on, ROCKPro64 hardware.

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

NOT verified (requires the real board):

- execution on ROCKPro64 hardware
- host reboot and automatic recovery
- microSD write behaviour over time
- 4GB RAM headroom under sustained load

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
