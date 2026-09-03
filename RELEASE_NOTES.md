# DanceMate Release Notes

## v0.75 Admin Foundation + Basic Master Data + Real Source Intake

Status:
In development on `feature/v0.75-admin-source-intake`. Not merged, not tagged.

Version split:

- Product Runtime: 0.75
- Information Engine: 0.73 (unchanged - v0.75 adds no engine algorithm feature)

Included:

- **Admin console** at `/admin`, server-rendered from the standard library.
  No template engine, no SPA, no build step: the runtime's dependency list
  gains one 30KB package (`python-multipart`, needed by FastAPI to read the
  console's HTML forms). Pages: Dashboard, Sources, Venues, Organizers,
  Candidates, Genres & Regions.
- **Admin authentication**: HTTP Basic from `ADMIN_USERNAME` / `ADMIN_PASSWORD`
  in `.env`. With no password set the console refuses every request rather
  than falling open. `/health` stays unauthenticated so container healthchecks
  keep working.
- **Master data** (`002_master_data.sql`): genres, regions, venues with
  aliases, organizers. Rows are disabled, never deleted. Venue aliases
  normalise through NFKC + case/punctuation folding so "La Ventana",
  "라벤타나" and "벤타나" resolve to one venue.
- **Source Master** (`003_source_intake.sql`): platform, role, authority,
  queries, per-source collection interval, enable/disable, last status. A
  source is collected from only when an operator has enabled it **and** its
  interval has elapsed; the interval floor is 10 minutes, enforced by a CHECK
  constraint and by validation.
- **Raw intake persistence**: `source_collection_runs`, `source_items`,
  `source_errors`. Deduplication on `(source_id, external_id)` with a content
  hash, so re-collecting an unchanged post is a duplicate and an edited one is
  a revision that goes back into the ingest queue.
- **Collector adapter**: no new collector was written. The engine's existing
  Kakao Daum Cafe and Naver Blog/Cafe collectors are what runs, live when
  credentials are present and against the engine's recorded snapshots when
  they are not. `[Test]` reports which, and writes nothing.
- **Engine ingest adapter**: `source_items` -> the engine's own
  `persist_raw_post` / `process_discovered_post` / `persist_events`. Engine
  source and engine schema unchanged.
- **Scheduler integration**: two new jobs, `source-intake` and `engine-ingest`,
  alongside the v0.74 self-checks.
- **Seed**: the three launch genres, South Korea and Seoul. The engine's own
  `config/sources.json` is imported into the Source Master - real, evidence-
  backed sources rather than invented ones - and every imported source arrives
  **disabled**. No venue or organizer is invented.
- 41 new tests (282 total against a live PostgreSQL).

Verified end to end on a development host with Docker:

- migrations 001-003 apply once and are idempotent on restart
- seed produces 3 genres, 2 regions and 6 disabled sources from the engine config
- admin console: anonymous and wrong credentials rejected (401), locked console
  rejects (503), all six pages and all seven API routes answer 200 authenticated
- enabling `SRC-D-001` then running the pipeline: `source-intake` collected 1
  item, `engine-ingest` produced 1 Event Candidate, visible on /admin/candidates
- an incomplete source is refused at enable time through both `set_enabled` and
  the PATCH API

Not done in v0.75, deliberately:

- **No real source is connected.** The engine's live collectors need
  `KAKAO_REST_API_KEY` (Kakao Developers) or `NAVER_CLIENT_ID` /
  `NAVER_CLIENT_SECRET` (Naver Developers). Neither is provisioned, on the
  development host or on the board, so live collection has never run. The whole
  pipeline was exercised against the engine's recorded API snapshots instead -
  real parsing code, offline data. **REAL SOURCE NOT CONNECTED.**

  The scheduler no longer papers over this. It refuses to collect a source
  whose credentials are missing rather than falling back to the snapshot
  fixtures, the admin `[Test]` button reports `PASS_SNAPSHOT` rather than
  `PASS`, and the dashboard counts live and snapshot items separately. As of
  this writing the board reads **Live items 0, live collection runs 0**, which
  is the true state.

Added while preparing for live acceptance:

- **Provenance guard**: the scheduler never substitutes recorded snapshot data
  for a live collection. Snapshot intake is opt-in per source
  (`config.snapshot_intake_allowed`), off by default, and every such run is
  recorded with `mode = 'snapshot'` and a `SNAPSHOT` status.
- **Error classification** (`runtime/collector_errors.py`): a collector failure
  is resolved to AUTH_FAILED / RATE_LIMITED / NETWORK / BAD_RESPONSE /
  CREDENTIALS_MISSING with the HTTP status and whether it is worth retrying, so
  "my key is wrong" is distinguishable from "I am being throttled". Messages
  are redacted before storage so no credential can reach `source_errors` or the
  console.
- **Provider quota accounting** (`runtime/quota.py`): requests are counted per
  provider per UTC day against a conservative budget, checked before any call.
  A source with six queries costs six calls, which a per-source interval check
  alone does not see. Both Naver platforms share one budget because they share
  one credential.
- No Human Verification workflow. The Candidates page is read-only and cannot
  grant VERIFIED; APPROVE / EDIT / REJECT / DUPLICATE / CONFIRM is v0.76.
- No Facebook collector: its access restrictions make it a poor first source,
  and the engine's own source list already marks those entries ACCESS_LIMITED.
- No Information Engine algorithm change.

Next:
v0.76 Human Verification Console.

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
