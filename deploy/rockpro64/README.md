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

## Deployment shape on this board

The board already runs its own infrastructure, documented in
`/opt/dancemate/docs/ROCKPRO64_SETUP.md`: a `dancemate-postgres` container
(compose project "database", data bind-mounted at `/opt/dancemate/data/postgres`)
and a `dancemate-caddy` reverse proxy, both on the external `dancemate-net`
network. v0.74 reuses that PostgreSQL rather than starting a second one on a
4GB board, so the deployment uses:

    deploy/rockpro64/docker-compose.external-postgres.yml

which brings up runtime + scheduler only. `.env` selects it:

    DANCEMATE_COMPOSE_FILE=deploy/rockpro64/docker-compose.external-postgres.yml
    DANCEMATE_POSTGRES_CONTAINER=dancemate-postgres
    POSTGRES_HOST=dancemate-postgres

The repository-root `docker-compose.yml` remains the self-contained stack for
development hosts. The board's existing compose projects are never touched.

### Runtime root

    /opt/dancemate/app/DanceMate

`/opt/dancemate/app` is the location the board's own setup document reserves
for the application. Runtime directories, owned by the container user (uid
10001) so the bind mounts are writable:

    /opt/dancemate/data/engine      -> /app/engine/data
    /opt/dancemate/data/runtime     -> /var/lib/dancemate
    /opt/dancemate/logs/runtime     -> /var/log/dancemate
    /opt/dancemate/backup/runtime   -> /var/backups/dancemate

### Two addresses, not one

    DANCEMATE_BIND_ADDRESS=192.168.1.100   host interface the port is published on
    DANCEMATE_HOST=0.0.0.0                 address the server listens on in the container

A container has no LAN address of its own. Putting the board's IP in
DANCEMATE_HOST makes uvicorn fail with "could not bind on any address"; both
compose files pin it to 0.0.0.0 so this cannot be got wrong. The health scripts
follow DANCEMATE_BIND_ADDRESS, because loopback stops listening once the
binding is narrowed.

## Deployment procedure

```bash
# on the ROCKPro64
sudo -u hammer git clone https://github.com/hammer93/DanceMate.git     /opt/dancemate/app/DanceMate
cd /opt/dancemate/app/DanceMate
git checkout feature/v0.74-rockpro-runtime

# runtime directories, writable by the container user
for d in data/engine data/runtime logs/runtime backup/runtime; do
  sudo install -d -o 10001 -g 10001 -m 755 "/opt/dancemate/$d"
done

cp .env.example .env && chmod 600 .env
$EDITOR .env      # set DANCEMATE_COMPOSE_FILE, DANCEMATE_POSTGRES_CONTAINER,
                  # DANCEMATE_BIND_ADDRESS and the PostgreSQL credentials
                  # (reuse /opt/dancemate/docker/database/.env)

scripts/install-rockpro64.sh             # host readiness check
docker compose --project-directory .   -f deploy/rockpro64/docker-compose.external-postgres.yml build
scripts/start-server.sh                  # waits for the first heartbeat
scripts/check-server.sh                  # expect six PASS, exit 0
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

## Connecting the first live source

Blocked on credentials as of 2026-09-03. Everything else is in place and
verified; only the keys are missing.

### 1. Obtain one credential

| Platform | Where | Variable(s) |
|---|---|---|
| `DAUM_CAFE` | Kakao Developers -> my application -> REST API key | `KAKAO_REST_API_KEY` |
| `NAVER_BLOG`, `NAVER_CAFE` | Naver Developers -> application -> Search API | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` |

Start with one. Kakao is the shorter path: one key, and `SRC-D-001` already
carries six real search queries imported from the engine's own config.

### 2. Put it on the board only

```bash
ssh root@192.168.1.100
nano /opt/dancemate/app/DanceMate/.env      # mode 600, git-ignored
```

Never commit it, never paste it into a terminal that is being logged.
`.env.example` carries the variable names and nothing else.

### 3. Restart and confirm the runtime sees it

```bash
cd /opt/dancemate/app/DanceMate
docker compose --project-directory .   -f deploy/rockpro64/docker-compose.external-postgres.yml up -d
```

No volume is removed by this; it recreates the two containers only.

### 4. Test before enabling

In the admin console, Sources -> **Test** on `SRC-D-001`. What the result means:

| Result | Meaning |
|---|---|
| `PASS` + `mode: live` | the key works and the provider answered - proceed |
| `PASS_SNAPSHOT` | the key is still missing; this ran against a recorded fixture |
| `AUTH_FAILED` | the provider rejected the key |
| `RATE_LIMITED` | the provider is throttling |

### 5. Enable exactly one source

Then watch the scheduler. `source-intake` runs on its cycle; the source is due
immediately the first time and every 60 minutes after. Success looks like:

```
live 1/1 due sources, N new, 0 revised
```

The dashboard's **Live items** counter is the one that matters -
**Snapshot items** is counted separately and is not live data.

### What will not happen without a key

The scheduler skips a credential-less source rather than collecting fixtures:

```
live 0/1 due sources, 0 new, 0 revised, skipped ['SRC-D-001']
sources.last_status = SKIPPED
sources.last_detail = no live collection: KAKAO_REST_API_KEY not configured.
                      Refusing to store snapshot data as if it were collected
```

That is the correct behaviour, not a fault to work around.

## Verification status

### Verified on the ROCKPro64, 2026-09-03

Board as measured: PINE64 ROCKPro64 v2.1, aarch64, 3.8GiB RAM, microSD
29.5GB (10% used), Armbian 26.8.3 / Debian 13.6, kernel 6.18.44,
Docker 29.7.2 + Compose v5.5.0, timezone Asia/Seoul, NTP synchronized.

- image built natively on aarch64; runtime and scheduler healthy
- PostgreSQL reached over `dancemate-net`; migration `001_initial_runtime`
  applied once, `applied=[]` on every subsequent start
- scheduler heartbeat and `job_runs` written; heartbeat 60s, jobs 300s
- Information Engine v0.73 imported and its fixture gate re-run on the board:
  `Fixture Gate: PASS (4/4)`
- `/health`, `/version`, `/status`, `/status/summary` answered on
  192.168.1.100:8080 from the board **and** from a LAN client; not answering on
  the board's WiFi address, and not on loopback
- backup verified with `pg_restore --list` and `PRAGMA integrity_check`
- container restart and full container recreation preserved every record
- **two host reboots**: all four containers back within ~15s of boot with no
  manual start; PostgreSQL rows, engine SQLite (same inode) and the v0.73
  Recommendation Runtime Outcome all intact afterwards
- new processing after each reboot (markers ROCKPRO-ACCEPTANCE-002 and -003)
- `check-server.sh`: six PASS, exit 0
- idle footprint: runtime 59MB, scheduler 42MB, postgres 51MB, caddy 49MB

### Still not verified

- long-term microSD write behaviour; only a few hours of runtime were observed
- 4GB RAM headroom under sustained real load - there is no real source data
  until v0.75
- behaviour on the final wired LAN. The board's own setup document records
  192.168.1.0/24 as a temporary direct-attach segment with no gateway, with
  internet arriving over WiFi; moving to the real router will need the binding
  and `DANCEMATE_BIND_ADDRESS` revisited
