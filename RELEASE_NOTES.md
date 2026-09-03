# DanceMate Release Notes

## v0.77 Extraction Quality Fix + Duplicate Resolution + Alpha Event Search

Status:
Deployed and verified on the ROCKPro64, 2026-09-03.

Version split:

- Product Runtime: 0.77
- Information Engine: **0.74** — the first version in which DanceMate modifies
  engine extraction logic. The imported PoC is tagged `engine-v0.73-baseline`
  and the change is tagged `engine-v0.74`; both are separate from the product
  tags so a reader can always get back to the untouched import:

      git checkout engine-v0.73-baseline -- engine/src/extractor.py

### Why this version exists

v0.76 fetched the post bodies and the extractor read more out of them. It also
started producing a value that is worse than a blank one. A post reading
`시간: PM 07:30~11:30` came out as `07:30`, twelve hours wrong. A missing time
makes an operator look it up; a wrong time sends a dancer to a locked door.

v0.76 could only flag it. v0.77 fixes it, and then does the two things that
were waiting on trustworthy fields: collapsing the same milonga posted four
times into one answer, and putting that answer in front of a dancer.

### PHASE A — time

The v0.73 pattern looked for a meridiem marker only *after* the clock, so a
leading one was invisible and the raw hour was kept. Reading rules moved to
`engine/src/extraction_rules.py`, tested against the exact strings that broke
them.

A marker before or after the clock, on either end or both. 오전/오후/AM/PM, and
the Korean time-of-day words limited to the hours where they actually assert
something — 밤 11시 is 23:00, 밤 12시 is not 12 PM, so 밤 stops counting as
evidence outside 6–11. A single marker resolves the other end by reading the
range forward: `PM 7:30~12:00` ends at midnight, not noon; `6:30-10:30pm`
starts at 18:30. Crossing midnight stays valid rather than being an error.

**Without a marker the clock is left exactly as written.** `5시30~9시30` stays
05:30 and is recorded as ABSENT evidence for a person to settle. A dance event
is not evidence that 7:30 means 19:30, and trading one wrong value for another
is not a fix.

Two posts turned out to price and schedule more than one thing — a 특강 before
the milonga, a paid 심야 패키지 after it — and their clock ranges were being
read as the event's own hours. Ranges belonging to another programme are now
skipped, so one post reads 21:00–01:00 (the milonga) instead of 19:30–20:45
(the class), and the other reports no time, which is what it actually says.

### PHASE B — venue

Label-based, and the label needs a colon: `위치와 카프레제 파스타` is a sentence
and `위치 🕗 시간: PM 8시` is a label with no value. Without that rule the false
positives would be worse than the 1-in-15 we started from. A bracketed address
stays with the name — `라 벤따나 (서울 마포구 잔다리로 48, 2층)` — and a following
one does not.

Extraction and resolution are kept apart. `venue_text` is the string the post
carried; `venue_id` is a Venue Master row a person stands behind. **Reading a
venue name never creates one.** An unrecognised string is UNRESOLVED and goes
to a queue at `/admin/venues/unresolved`, where linking it records it as an
alias and re-resolves every event waiting on it. A misread line must not become
a permanent master record.

### PHASE C — fee

Judged next to each amount rather than across a segment, because one real post
carries `입장료 13,000원` and, sentences later, `심야 밀롱가 3,000원 할인`.
Parking, discounts, packages and class prices are excluded; a milonga's fee is
the one a fee label or the word 밀롱가 names. `예매: 특강+밀롱가 38000원, 특강만
30000원, 밀롱가만 13000원` yields 13,000.

An unlabelled number never becomes a fee. The engine grants VERIFIED partly on
a fee being present, and an invented one passes that gate on evidence nobody
has.

### Measured on the board, 15 live candidates

Re-extracted from the stored bodies with engine v0.74. No new API calls: the
posts were already fetched in v0.76.

| | v0.73 | v0.74 |
|---|---|---|
| Date | 15/15 | 15/15 |
| Start / end time | 7/15 | **12/15** |
| Venue extracted | 1/15 | **10/15** |
| Fee | 1/15 | **3/15** |
| **Times wrong** | **7** | **0** |
| Values lost | — | **none** |

All seven v0.73 times were morning readings of evening milongas. Of the twelve
v0.74 times, eleven carry EXPLICIT meridiem evidence; the twelfth is the
unmarked `5시30분` post, recorded as ABSENT and flagged rather than converted.

Venue *resolution* is 0/15 and correctly so: the Venue Master has no venues
registered yet, so eight distinct strings — OCHO, PISTA, 아미고스튜디오,
Tango Andante, 라 벤따나, 엔빠스, 데땅고, Tango O Nada — are queued for a
decision. Extracted and resolved are different numbers and this release reports
both.

Engine test suite: 559 passed.

### PHASE D — normalization

`events` is the runtime's normalised view: one row per event on one date, which
is what a dancer looks for. Named `events` rather than `event_instances`
because the engine owns that table name and the hybrid-persistence rule refuses
a mirror of it.

`series_key` groups a weekly milonga's nights so a duplicate check can tell
"posted twice" from "on again next week", and never merges them.

Re-extraction issues new candidate ids rather than updating old ones, so an
engine version bump leaves every post with both its old candidate's event and
its new one. On the board that put 29 rows in front of a user for 15 real
events. Normalisation now prunes events whose candidate the engine no longer
holds — and prunes nothing when the engine store is unreadable, because "I
cannot see the candidates" must never be acted on as "there are none".

### PHASE E — duplicates

Auto-merge requires all three of same date, same place and same start time,
with the place a resolved venue or an identical string and the time present on
both sides. Everything short of that is an open pair for a person. No
embeddings, no clustering, no similarity score: a number nobody can check is
not a reason to merge two events. Different dates are never compared, so a
weekly series cannot collapse into one row.

The board produced exactly one ambiguous pair, and it is the case the caution
is for: 일루미밀롱가 at 14:00 and 허그밀롱가 at 19:00, same venue, same night.
An automatic merge would have deleted one of them from the answer.

Nothing is deleted. A duplicate keeps its row, its candidate and its source URL
and points at the canonical one, so the detail page still lists every post
behind an event. A person's verdict is final: the scan skips any event a human
has ruled on, in either direction.

### PHASE F — alpha search API

`GET /api/events` with `when=today|tomorrow|this_week|weekend|upcoming`, or a
date range, plus genre, region and status. `GET /api/events/{id}` adds every
post behind the event.

Dates are Asia/Seoul: at 23:00 KST a UTC-based "today" is already showing
tomorrow's list. "This week" means what is still ahead of you, not a calendar
week half of which has happened.

The API serves LIVE only. A replayed snapshot is how we test a parser; showing
one as a real Saturday night would be a lie told to someone making plans. So
provenance is stored per event and anything not traceable to a live collection
is excluded, along with duplicates and anything a person rejected. On the board
that is 15 of 26 rows.

### PHASE G — alpha user surface

`/`, `/events`, `/events/{id}`. No account, no map, no recommendations — those
need evidence we do not have, and shipping them now would make it harder to
find out what people actually use.

What it does insist on is not overstating anything:

- a null fee renders 요금 미확인, never 0원
- a venue read from a post but not recognised is shown with a 미확인 tag
- a clock the post did not qualify is shown with a 시간 미확인 tag — the value
  is what the post says, the tag is what that is worth
- a database outage is a 503 with a sentence, because an empty list would read
  as "nothing is on tonight"
- the footer says it is an alpha and that unconfirmed fields are left blank

### Operations

- New scheduler job `event-normalization`: normalise, then scan for duplicates.
  One job so the order is guaranteed.
- `POST /api/admin/events/reextract` re-runs the current engine over every post
  whose body we already hold. For an engine version bump: the stored candidates
  were extracted by the previous version and nothing about the article says so.
  Candidates a person has acted on are skipped, so it cannot overwrite a review.
- Console gains Events, Unresolved Venues and Duplicates — the last two being
  where automation stopped and handed over.
- Migrations 007–011. 009 and 010 exist because the first prune hit two
  self-references; the verdict is history and history is not deleted because
  its subject was.

### Verification

| | |
|---|---|
| Engine suite | 559 passed |
| Runtime suite, host | 385 passed, 127 skipped |
| Runtime suite, container | 504 passed, 8 skipped |
| Migrations on the board | 011 of 011 applied |
| `/version` | product 0.77, engine 0.74 |
| Alpha API | 4 upcoming events, all LIVE |
| Console | Events, Unresolved Venues, Duplicates all 200 |

### Known and deliberate

- Venue resolution is 0/15 until someone registers venues. The queue is the
  deliverable, not the resolution.
- `Entry fee 20,000 KRW` is not read — no observed post writes an amount that
  way, and inventing a currency rule for an unobserved form is how the PM bug
  happened.
- Fee is 3/15. Most posts genuinely do not state one, and the extractor no
  longer guesses at parking charges or class prices to inflate the number.

## v0.76 Deep Content Acquisition + Human Verification Console + Source Usage Monitoring

Status:
Deployed and verified on the ROCKPro64, 2026-09-03, host reboot included.

Version split:

- Product Runtime: 0.76
- Information Engine: 0.73 (unmodified - v0.76 adds no engine algorithm)

### Why this version exists

v0.75 collected 17 live items and produced 15 candidates, and almost none were
usable: Time missing from 10 of 10 sampled, Venue from 9, Fee from 10. The
cause was not extraction. A search API returns a snippet - the live intake
averaged 97 characters - and the times, venues and fees are in the post body,
which was never fetched. So v0.76 fetches the body first and builds the review
console on top of it, rather than the other way round.

### Deep Content Acquisition

Daum serves the desktop article URL as an iframe shell (1,646 bytes, 168
characters of CSS). The mobile host serves the same post as real HTML, and
robots.txt permits it - only `/_*` administrative paths are disallowed. Article
region extraction yields 434 characters on a live post against 190 from
og:description (which the site truncates mid-sentence) and 813 for the whole
page including chrome.

Measured on the board over the existing 17 live items plus 1 snapshot item:

| | |
|---|---|
| FETCHED_FULL | 17 |
| FETCHED_PARTIAL | 1 (thin body) |
| FETCH_BLOCKED / LOGIN_REQUIRED / FAILED | 0 |
| Average body | **97 to 492 characters** (max 1,026) |
| Method | article_region 17, visible_text 1 |
| Content fetches | 18, all successful, avg 305ms |

No login, CAPTCHA or access-control bypass, and no browser automation. Only
extracted text is stored, never raw HTML: total stored text is 8.4KB. Personal
data is removed before storage - 18 spans across 12 items (phone numbers, bank
accounts) - while fees and times survive, which the tests pin from both sides.

### Engine reprocessing: what improved, and what got worse

The engine is unmodified. Given the body instead of the snippet, its own
extractor produced, over the 15 live candidates:

| Field | Before | After |
|---|---|---|
| Event name | 15/15 | 15/15 |
| Date | 12/15 | **15/15** |
| Start time | 1/15 | **7/15** |
| End time | 1/15 | **7/15** |
| Venue | 1/15 | 1/15 |
| Fee | 1/15 | 1/15 |

On the same 10-item sample used in v0.75: Date 7/10 to **10/10**, Start 0/10 to
**5/10**, End 0/10 to **5/10**, Venue 1/10 unchanged, Fee 0/10 to 1/10.

**A wrong-value regression appeared.** A post reading `시간: PM 07:30~11:30`
came out as `07:30` - twelve hours early. A missing time makes an operator look
it up; a wrong time sends a dancer to a locked door, so this is worse than the
gap it replaced. The engine was not modified to fix it: rebuilding its time
parser is a v0.77 decision to make with this evidence in hand. What v0.76 does
is refuse to let the value pass silently - the review console compares each
extraction against the body it came from and warns the reviewer:

    WARN  Start reads 07:30, but the body marks 7 as afternoon/evening.
          This is probably 19:30 - check the body before approving.
    INFO  the body says 장소: 아미고스튜디오 but no venue was extracted

**Venue and Fee did not improve, and the reason was measured rather than
guessed**: of the candidates missing them, the value is present in the acquired
body for 5 venues and 2 fees - for example `밀롱가만 13000원`, which the v0.73
extractor does not recognise. That is an extraction gap, not an acquisition
gap, and it is the concrete input for v0.77.

**False VERIFIED: 0.** All 15 live candidates remain POSSIBLE. The engine gate
needs date, start, end and fee together, and no live post yielded all four.

### Human Verification Console

APPROVE / EDIT / REJECT / DUPLICATE / CONFIRM at `/admin/review`, recorded
alongside the engine status and never instead of it. **APPROVE does not grant
VERIFIED** - a test asserts the review module contains no reference to the
engine store at all. An EDIT keeps both the engine value and the correction.
Nothing is ever deleted, including rejections.

All five actions and their validation were exercised against a synthetic
candidate id and then removed. No judgement was made on a real dance event,
which is the operator decision to make.

### Source Usage Monitoring

`/admin/usage`, with two counters that are never added together:

| | |
|---|---|
| API requests today | KAKAO 6 (17 items, 0 new, 17 duplicate) |
| Content fetches today | 18, none of which cost provider quota |
| Kakao quota | 6 / 5000, **CONFIGURED** (our own budget) |
| Naver quota | 0 / 25000, **DOCUMENTED** (the published Naver limit) |
| Cost, every provider | **UNKNOWN** |

No provider is recorded as FREE and no cost renders as zero: an absent invoice
is not evidence of free. Naver remains AUTH_FAILED from v0.75 and is shown so.

### ROCKPro64 acceptance

Migrations 004-006 applied to the live database after a verified backup
(pg_restore 108 entries, SQLite integrity ok). Live data intact throughout:
18 source items, 5 collection runs, 15 candidates.

Restart and host reboot both preserved everything - acquisition results, usage
counters, review audit and candidates - with all four containers healthy in
about 20 seconds and no duplicate explosion (18 items, 18 distinct external
ids). The reboot needed a power cycle again, the RK3399 warm-reset behaviour
recorded in `deploy/rockpro64/NETWORK.md`.

Idle footprint after acquisition: runtime 50MB, scheduler 43MB, postgres 54MB;
database 9.2MB, container logs 4KB each, microSD 11%.

Tests: 338 pass on a developer host, 408 against a live PostgreSQL in the
runtime container.

### Not done in v0.76

- No engine algorithm change, and no new extraction rules.
- No OCR or poster image processing; poster URLs are recorded, nothing more.
- No automatic duplicate resolution - a person marks DUPLICATE, and v0.77 can
  build on that.
- Naver is still not connected (external credential condition).

Next:
v0.77 - the extraction failures above are the agenda: PM and 오후 time
handling, labelled venues, and unlabelled fees.

## v0.75 Admin Foundation + Basic Master Data + Real Source Intake

Status:
Live source intake VERIFIED on the ROCKPro64 with real Kakao credentials,
2026-09-03, host reboot included.

### Live Source Acceptance (2026-09-03, ROCKPro64)

**Kakao / Daum Cafe Search API — LIVE VERIFIED**

| | |
|---|---|
| Endpoint | `https://dapi.kakao.com/v2/search/cafe` |
| Auth | `Authorization: KakaoAK <key>`, `KAKAO_REST_API_KEY` from `.env` |
| Provider response | HTTP 200, `total_count` 23,316 for `밀롱가` |
| Live collection runs | 2 successful (`mode = live`) |
| Live items | 17 |
| Live Event Candidates | 15 |
| Duplicate handling | second run: 17 discovered, **0 new, 17 duplicate** |
| Scheduler interval | immediate re-tick reported `no source due` |
| Korean text | 18/18 titles contain Hangul in PostgreSQL (UTF8), 0 mangled |
| Provenance | every candidate resolves to a real `cafe.daum.net/latindance/5HTC/...` URL |
| False VERIFIED | **0** among live-collected posts |
| Quota accounting | KAKAO 12 requests recorded against the daily budget |

Source configuration had to be corrected first. The engine's shipped
`config/sources.json` gives `SRC-D-001` `url_contains: ["6uP", "5HTC"]`, and
`_matches_source` requires **every** token in the same URL. `6uP` is a stale
cafe id that no longer appears — real posts are at
`cafe.daum.net/latindance/5HTC/...` — so the filter could never match, and the
first live call returned 200 with 0 usable records. Corrected through the admin
API to `["latindance", "5HTC"]`; the engine was not modified.

**Naver Search API — BLOCKED, external credential condition**

`NAVER_CLIENT_ID` and `NAVER_CLIENT_SECRET` are set, and both Blog and Cafe
search return **HTTP 401**. This is not a code fault, and the API's own error
messages prove it:

| Request | Response |
|---|---|
| `X-Naver-Client-Id` + `X-Naver-Client-Secret` (what the code sends) | `errorCode 024`, `NID AUTH Result Invalid (1000)` |
| NCP APIGW headers instead | `errorCode 024`, `Not Exist Client ID` |
| no credential header at all | `errorCode 024`, `Not Exist Client ID` |

The distinct message for the first case shows the endpoint and header scheme
are correct and the credential itself was evaluated and rejected. The secret is
40 characters where a legacy Naver Open API secret is typically ~10, which
suggests the pair came from a different Naver product or an application that
has not added 검색 to its API list. Carried as a Remaining Risk.

**Data quality, 10 live candidates sampled against their source posts**

| Field | Correct | Wrong | Missing |
|---|---|---|---|
| Event name | 10 | 0 | 0 |
| Date | 7 | 0 | 3 |
| Start time | 0 | 0 | 10 |
| End time | 0 | 0 | 10 |
| Venue | 1 | 0 | 9 |
| Fee | 0 | 0 | 10 |
| Event type | 10 | 0 | 0 |
| Source URL | 10 | 0 | 0 |

All 17 live posts are `METADATA_ONLY` with an average body of 97 characters —
the search API returns a snippet, not the post. Times, venues and fees live in
the body, so the low yield is acquisition depth, not extraction failure. Of the
three missing dates, two posts genuinely carry no date in their title. One
start time (`5시30분`) was present and not extracted. Every candidate is
`POSSIBLE`; none was promoted on search discovery alone.

**Restart and host reboot — PASS, with one caveat about the board.**

`docker compose restart`: 18 items, 4 runs, 15 candidates preserved.

The host reboot needed a power cycle. `systemctl reboot` shut down cleanly and
the board then never came back up, staying unreachable for ~27 minutes until it
was power cycled. `journalctl --list-boots` records exactly one boot after the
shutdown — the power-cycled one — so it never reached a running kernel. That is
the RK3399 warm-reset behaviour, not a DanceMate fault: the filesystem came back
`clean` with no fsck and no I/O errors, and three earlier reboots on this board
recovered in about 15 seconds. Recorded in `deploy/rockpro64/NETWORK.md`, along
with the detail that this board's RTC does not retain time, so early boot
journal timestamps are misleading until NTP syncs.

Everything DanceMate owns survived it, with no manual start:

| | |
|---|---|
| Containers healthy after boot | 4 of 4, ~26s |
| `source_items` | 18 (17 live, 1 snapshot) |
| `source_collection_runs` | 4, provenance intact |
| Live Event Candidates | 15 |
| False VERIFIED among them | 0 |
| Korean text | 18/18 titles still Hangul in PostgreSQL |
| Provider quota | preserved across the reboot |
| Duplicate explosion | none: 18 items, 18 distinct external ids |
| Post-reboot live collection | ran immediately: 17 discovered, 0 new, 17 duplicate |
| `check-server.sh` | six PASS, exit 0 |

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
