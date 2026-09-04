# DanceMate

DanceMate는

> "오늘 춤추고 싶은 사람이
> DanceMate를 보고 실패 없이 갈 곳을 찾는 것"

을 목표로 하는 Dance Event Information Service다.

## 현재 상태

- Product Runtime: v0.77.2 (Venue Default Prefill + Safe Venue Delete)
  - deployed and verified on the ROCKPro64 on 2026-09-03
- Information Engine: v0.74 (`engine/`, 559 tests)
- Initial Server: ROCKPro64 (PINE64 v2.1 / RK3399 / ARM64 / Debian 13)
- Initial Region: Seoul
- Initial Genres:
  - Tango
  - Salsa
  - Swing

제품 버전과 Information Engine 버전은 서로 다르다. `VERSION`은 제품 런타임
버전이다. Engine은 v0.77에서 처음으로 추출 로직이 수정되어 v0.74가 되었다.
손대지 않은 import 상태는 `engine-v0.73-baseline` 태그에 남아 있다:

    git checkout engine-v0.73-baseline -- engine/src/extractor.py

## 현재 개발 우선순위

1. ~~Information Engine v0.73 baseline~~
2. ~~ROCKPro64 Persistent Runtime~~
3. ~~Real Source Data~~
4. ~~Human Verification~~
5. ~~DanceMate Alpha~~ (v0.77: search API + `/`, `/events`, `/events/{id}`)
6. Real User Feedback ← 다음

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
| `GET /health`     | cheap liveness probe: `{"status":"ok","version":"0.77.2"}`    |
| `GET /version`    | product runtime version vs Information Engine version         |
| `GET /status`     | six components; HTTP 503 if any FAILs                         |
| `GET /status/summary` | the dotted operator report used by `check-server.sh`      |
| `GET /resources`  | CPU load, memory, disk usage                                  |

### Alpha user surface (LAN only, no authentication)

| Endpoint | Purpose |
|---|---|
| `GET /` | 오늘 갈 수 있는 곳 |
| `GET /events?when=today\|tomorrow\|weekend\|this_week\|upcoming` | 목록 |
| `GET /events/{id}` | 상세 + 출처 원문 링크 |
| `GET /api/events` | 같은 검색의 JSON. `when` / `date` / `from` / `to` / `genre` / `region` / `status` |
| `GET /api/events/{id}` | 이벤트 하나와 그것을 언급한 모든 게시글 |

날짜는 Asia/Seoul 기준. LIVE로 수집된 것만 노출한다 — snapshot과 fixture는
콘솔에만 남고 사용자에게 가지 않는다.

### Admin console (LAN only, HTTP Basic)

`http://<board>:8080/admin` — Dashboard, Intake, Review, Events, Duplicates,
Sources, Venues, Organizers, Genres & Regions, Usage, System. Server-rendered;
credentials come from
`ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env`, and the console refuses every
request when no password is set. JSON equivalents live under `/api/admin/`.

Pages: Dashboard, Intake, Review, Events, Duplicates, Sources, Venues,
Organizers, Genres & Regions, Usage, System. Unresolved Venues sits under
Venues at `/admin/venues/unresolved`.

Unresolved Venues is where a venue string becomes a venue. Each queue entry
shows the post it came from with a line of surrounding text, and offers **Link
Existing**, **New Venue** and **Not a venue** on the spot — the New Venue form
opens inline, prefilled from the string, and Create & Link registers the venue,
aliases the raw string to it and resolves the waiting events in one
transaction. Nothing is registered automatically: a misread line must not
become a permanent master record. Every decision is audited with the reviewer,
the string, the action and how many events actually moved.

The form fills itself from the string and, when the string is only a name, from
the post behind it — an address written right after the venue's own name, or on
a labelled 주소 line, never one merely present somewhere in the body. The region
follows from the address. Every field stays editable and the form says where
each value came from.

A venue can be removed. `/admin/venues` shows how many events use each one; a
venue nothing references can be deleted, and one that events point at needs
**Unlink & Delete**, whose confirmation names the count first. Unlinking sends
those events back to the raw string they were read from and puts the string
back in the queue — the posts, the evidence, the events and every review stay
where they are. **Deactivate** takes a venue out of circulation without
unlinking anything.

The pipeline runs as five scheduler jobs: `source-intake` discovers posts
through a provider's search API, `content-acquisition` fetches the original
post behind each result, `engine-ingest` hands new items to the Information
Engine, `engine-reprocess` re-extracts items whose body arrived later, and
`event-normalization` builds the searchable event rows and then resolves
duplicates — one job so that order is guaranteed.

When the *extractor* changes rather than the content, `POST
/api/admin/events/reextract` re-runs the current engine over every post whose
body we already hold. Candidates a person has acted on are skipped.

An operator registers a source, presses **Test**, then **Enable**. The
scheduler collects only from enabled sources whose interval has elapsed
(minimum 10 minutes), stores the raw items deduplicated by content hash, and
hands them to the Information Engine. Live collection needs the platform's API
credentials in `.env`; without them a source can still be tested and collected
against the engine's recorded snapshots.

## Repository Structure

```
DanceMate/
├─ engine/            Information Engine v0.74 (src, tests, config, data)
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
