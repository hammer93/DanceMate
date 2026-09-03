# DanceMate - ROCKPro64 Deployment

## Target

- PINE64 ROCKPro64 v2.1
- RK3399
- ARM64 / aarch64
- RAM 4GB
- microSD 32GB
- Armbian 26.8.3
- Debian 13 Trixie
- Kernel 6.18.x

## Deployment Policy

- LAN only
- No public Internet exposure
- Automatic recovery after host reboot
- SD card write minimization
- Persistent data
- Backup required
- Health check required

## v0.74 Acceptance

1. Host boot
2. DanceMate auto-start
3. PostgreSQL connection
4. Information Engine start
5. API Health
6. Scheduler
7. Test data processing
8. Recommendation Memory persistence
9. Host reboot
10. Memory restored
11. Runtime Outcome preserved
12. Processing continues

## Architecture

```
ROCKPro64 (Debian 13, arm64)
└─ docker compose
   ├─ postgres    postgres:16-alpine   runtime state only
   ├─ runtime     dancemate/runtime    API + migrations   :8080
   └─ scheduler   dancemate/runtime    periodic worker
                  (runtime and scheduler share one image)

   volumes
   ├─ dancemate-postgres-data   named volume  -> /var/lib/postgresql/data
   ├─ $ENGINE_DATA_DIR          bind mount    -> /app/engine/data
   ├─ $DANCEMATE_DATA_DIR       bind mount    -> /var/lib/dancemate
   ├─ $DANCEMATE_LOG_DIR        bind mount    -> /var/log/dancemate
   └─ $DANCEMATE_BACKUP_DIR     bind mount    -> /var/backups/dancemate
```

### Hybrid persistence

v0.74 deliberately does **not** migrate the Information Engine to PostgreSQL.

| Store      | Owner                     | Contents                                             |
|------------|---------------------------|------------------------------------------------------|
| PostgreSQL | DanceMate Runtime         | `runtime_state`, `scheduler_heartbeat`, `job_runs`    |
| SQLite     | Information Engine v0.73  | everything the engine already persists, unchanged     |

The engine resolves its database path from its own package root
(`engine/src/main.py` → `db_path()` → `<engine root>/data/dancemate_ie_poc_v0.73.sqlite3`).
Persistence is therefore provided by mounting a volume over `/app/engine/data`
rather than by patching engine source. That mount would otherwise hide the
fixture and snapshot files the engine ships, so `scripts/docker-entrypoint.sh`
seeds any missing fixture back into the volume on start. Seeding never
overwrites an existing file, so the live database and operator data are safe.

### SD card write minimization

- container logs capped at `max-size: 10m`, `max-file: 3` on every service
- uvicorn access logging disabled (`access_log=False`)
- scheduler heartbeat is floored at 30s in code and defaults to 60s
- jobs run on a separate, slower cycle (`SCHEDULER_JOB_INTERVAL_SECONDS`, 300s)
- health polling writes nothing to any database: `/status` reads only
- `job_runs` gets one row per job run, not per tick
- backup retention prunes to the newest `BACKUP_RETENTION` (default 7)

## Network policy

**LAN firewall required. No WAN port forwarding.**

The runtime API has no authentication: it is a staging admin surface, not a
public API. PostgreSQL is not published to the host at all (`expose`, not
`ports`). Once the board's address is fixed, narrow the runtime binding:

```
DANCEMATE_BIND_ADDRESS=192.168.0.10
```

## Deployment procedure

```bash
# on the ROCKPro64
git clone https://github.com/hammer93/DanceMate.git
cd DanceMate
git checkout feature/v0.74-rockpro-runtime

scripts/install-rockpro64.sh --prepare   # host check + directories + .env
$EDITOR .env                             # set a real POSTGRES_PASSWORD
                                         #   openssl rand -base64 24

docker compose build                     # builds natively for arm64
scripts/start-server.sh
scripts/check-server.sh
```

### Auto-start after host reboot

Every service is `restart: unless-stopped`, so the Docker daemon brings the
stack back after a reboot. Confirm the daemon itself starts at boot:

```bash
sudo systemctl enable docker
```

No separate systemd unit is needed for DanceMate.

## Operations

| Task            | Command                                             |
|-----------------|-----------------------------------------------------|
| start           | `scripts/start-server.sh`                            |
| stop            | `scripts/stop-server.sh` (never removes volumes)     |
| health          | `scripts/check-server.sh` (exit 0 / 1 / 2)           |
| backup          | `scripts/backup.sh`                                  |
| list backups    | `scripts/restore.sh --list`                          |
| restore         | `scripts/restore.sh <name> --yes`                    |
| logs            | `docker compose logs -f runtime scheduler`           |

## Verification status as of v0.74

Verified on an amd64 development host with Docker:

- image build, `docker compose config`, full stack up and healthy
- `/health`, `/version`, `/status`, `/status/summary`, `/resources`
- migration runner applies `001_initial_runtime` once and is idempotent on restart
- scheduler heartbeat and `job_runs` rows written to PostgreSQL
- engine fixture batch processed (`Fixture Gate: PASS 4/4`), SQLite created
- state survives `docker compose restart` **and** full container recreation
- backup produces a valid `postgres.dump` and a readable `engine.sqlite3`
- restore round trip replaces runtime state and keeps a pre-restore copy
- `check-server.sh` reports all six components PASS, exit 0

Statically verified for ARM64:

- the image builds for `linux/arm64` via buildx
- base images are official multi-arch tags; no x86 pins in the build

**Not verified yet** (requires the real board):

- execution on ROCKPro64 hardware
- host reboot and automatic recovery
- microSD write behaviour over time
- 4GB RAM headroom under sustained load
