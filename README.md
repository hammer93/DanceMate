# DanceMate

DanceMate는

> "오늘 춤추고 싶은 사람이
> DanceMate를 보고 실패 없이 갈 곳을 찾는 것"

을 목표로 하는 Dance Event Information Service다.

## 현재 상태

- Product Runtime: v0.74 (Persistent Runtime + ROCKPro64 Staging Deployment)
  - deployed and verified on the ROCKPro64 on 2026-09-03, host reboot included
- Information Engine: v0.73 (`engine/`, 559 tests)
- Initial Server: ROCKPro64 (PINE64 v2.1 / RK3399 / ARM64 / Debian 13)
- Initial Region: Seoul
- Initial Genres:
  - Tango
  - Salsa
  - Swing

제품 버전과 Information Engine 버전은 서로 다르다.
`VERSION`은 제품 런타임 버전이고, engine은 v0.73 baseline 그대로다.

## 현재 개발 우선순위

1. Information Engine v0.73 baseline
2. ROCKPro64 Persistent Runtime
3. Real Source Data
4. Human Verification
5. DanceMate Alpha
6. Real User Feedback

## 초기 Alpha 범위

Search
→ Event List
→ Event Detail

## Architecture

```
docker compose
├─ postgres    postgres:16-alpine    runtime state / scheduler heartbeat / job history
├─ runtime     dancemate/runtime     API + migration runner            :8080
└─ scheduler   dancemate/runtime     periodic worker (same image)
```

**Hybrid persistence.** The DanceMate Runtime uses PostgreSQL. The Information
Engine keeps its existing SQLite store, unchanged - v0.74 does not migrate the
engine's database. See `deploy/rockpro64/README.md` for why and how.

### Runtime API (LAN only, no authentication)

| Endpoint          | Purpose                                                      |
|-------------------|--------------------------------------------------------------|
| `GET /health`     | cheap liveness probe: `{"status":"ok","version":"0.74"}`      |
| `GET /version`    | product runtime version vs Information Engine version         |
| `GET /status`     | six components; HTTP 503 if any FAILs                         |
| `GET /status/summary` | the dotted operator report used by `check-server.sh`      |
| `GET /resources`  | CPU load, memory, disk usage                                  |

## Repository Structure

```
DanceMate/
├─ engine/            Information Engine v0.73 baseline (src, tests, config, data)
├─ runtime/           DanceMate Runtime: API, config, migrations, health, adapters
├─ scheduler/         periodic worker and job registry
├─ collector/         Dance Event Source intake (v0.75)
├─ admin/             Human Verification Console (v0.76)
├─ migrations/runtime/ numbered PostgreSQL migrations
├─ scripts/           install / start / stop / check / backup / restore
├─ deploy/rockpro64/  ROCKPro64 architecture, policy and deployment procedure
├─ tests/             product runtime test suite
├─ data/ logs/ backup/ runtime data (git-ignored, .gitkeep only)
├─ Dockerfile         ARM64-capable runtime image
├─ docker-compose.yml postgres + runtime + scheduler
├─ .env.example       environment template (no secrets)
└─ VERSION            product runtime version
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

pytest                       # product runtime tests (133)
cd engine && pytest          # Information Engine regression (559)
```

## Staging (ROCKPro64 target)

The board reuses its existing PostgreSQL, so it selects a different compose
file through `.env` (`DANCEMATE_COMPOSE_FILE`). See
`deploy/rockpro64/README.md` for the full procedure.

```bash
cp .env.example .env
$EDITOR .env                 # set POSTGRES_PASSWORD: openssl rand -base64 24

scripts/install-rockpro64.sh # host readiness check (--prepare to create dirs)
docker compose build
scripts/start-server.sh      # start postgres + runtime + scheduler
scripts/check-server.sh      # exit 0 all PASS, 1 a component FAILed, 2 unreachable
scripts/stop-server.sh       # stop; never removes volumes
```

Health output:

```
DanceMate Server
Runtime ........ PASS
Database ....... PASS
Scheduler ...... PASS
Information .... PASS
Storage ........ PASS
Backup ......... PASS
```

## Backup and Restore

```bash
scripts/backup.sh                              # timestamped backup, retention 7
scripts/restore.sh --list
scripts/restore.sh dancemate-backup-YYYYmmdd-HHMMSS         # dry run, changes nothing
scripts/restore.sh dancemate-backup-YYYYmmdd-HHMMSS --yes   # apply
```

A backup contains `postgres.dump` (pg_dump custom format), `engine.sqlite3`
(taken with SQLite's online backup API, safe against a live engine connection)
and `manifest.json`. Restore stops the scheduler, takes a pre-restore safety
copy, then applies the named backup.

## Data persistence

| Path                          | Container                  | Survives                       |
|-------------------------------|----------------------------|--------------------------------|
| `dancemate-postgres-data`     | `/var/lib/postgresql/data` | restart, recreation, reboot    |
| `$ENGINE_DATA_DIR`            | `/app/engine/data`         | restart, recreation, reboot    |
| `$DANCEMATE_DATA_DIR`         | `/var/lib/dancemate`       | restart, recreation, reboot    |
| `$DANCEMATE_LOG_DIR`          | `/var/log/dancemate`       | restart, recreation, reboot    |
| `$DANCEMATE_BACKUP_DIR`       | `/var/backups/dancemate`   | restart, recreation, reboot    |

`stop-server.sh` never passes `-v` to `docker compose down`, so stopping the
stack never removes any of them.

## Network policy

**LAN firewall required. No WAN port forwarding.** The runtime API is an
unauthenticated staging admin surface. PostgreSQL is never published to the
host. Set `DANCEMATE_BIND_ADDRESS` to the board's LAN address in production
staging.
