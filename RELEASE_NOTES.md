# DanceMate Release Notes

## v0.82.3 Non-HTML Source Acquisition Bypass + Source Pipeline Hardening

Status:
Fix and board acceptance completed against the ROCKPro64 board's real
production database, 2026-09-05.

Version split:

- Product Runtime: 0.82.3
- Information Engine: unchanged (0.79) - no engine code changed in this
  release; the full Engine test suite was still run for integration
  regression coverage.

### What this closes

v0.82.2 fixed the data-loss bug (a discovery-synthesized body silently
degraded by the generic acquisition queue), but left a smaller structural
gap: its `settle_full_body()` guarantee is tied to content quality, so a
TangoNOW/Tango Calendar Korea item whose body was too short to settle still
fell back to the ordinary queue - and their `source_url` is a JSON API
endpoint that will never serve HTML, so that fetch was never "waiting for
content," it was a wasted request structurally guaranteed to end in
`UNSUPPORTED_CONTENT_TYPE`. Confirmed via `content_fetch_log`: 64 such
wasted fetches against TangoNOW's Firestore endpoint, 27 against Tango
Calendar Korea's API, all pre-dating this release.

### Fix

`runtime.acquisition.NON_HTML_API_PARSERS`, keyed on the source's own
`config.parser` (no `source_id` branching), excludes a matching item from
the generic acquisition queue in two places: `content_store
.newly_collected()` (a new function, extracted from
`scheduler/acquisition_job.py`'s own inline query so it is directly
testable) so it is never queued in the first place, and `content_store
.due_for_acquisition()` so a historical queued row is never fetched either.
Miltang and DanceInfo are deliberately not in this set - Miltang's own
detail pages are real HTML, and DanceInfo's title-only list stage still
needs its real detail fetch, both confirmed unaffected. See
`docs/TANGO_SOURCE_IMPLEMENTATION.md`'s "v0.82.3 fix" section for the full
mechanism and the board validation numbers (a live four-source controlled
collection showed zero new queue entries for TangoNOW/Tango Calendar Korea
and DanceInfo's detail fetch working exactly as before).

## v0.82.2 FETCHED_FULL Content Settlement + Reprocess Safety

Status:
Fix, scoped board recovery and re-observation completed against the
ROCKPro64 board's real production database, 2026-09-05.

Version split:

- Product Runtime: 0.82.2
- Information Engine: unchanged (0.79) - no engine code changed in this
  release; the full Engine test suite was still run for integration
  regression coverage.

### Root cause

A source whose discovery module already synthesizes a complete event body at
discovery time (TangoNOW, Tango Calendar Korea, Miltang — not DanceInfo,
which is title-only at list stage) never marked `source_item_content` as
settled. The generic content-acquisition queue then read "no content row
yet" as "needs fetching," queued the item, and a routine re-fetch through
`runtime/acquisition.py`'s generic extractor (no source-specific rule) could
silently replace the already-correct body with the site's own generic
`og:description` tagline. `engine_reprocess` read that date-less tagline as a
genuine revision, re-extracted nothing useful from it, and its own
"replace this post's candidates with whatever the extractor now makes of the
body" rule then deleted the previously-correct event. Confirmed live: within
about 90 minutes of enabling, Miltang's listed events fell from 50 to 8, and
by the time this release's recovery began, to 0.

### Fix

`runtime/content_store.settle_full_body()`, called from
`runtime/intake.store_item()`, settles `source_item_content` as
`FETCHED_FULL`/`discovery_synthesized` immediately whenever discovery already
hands the item a usable `FETCHED_FULL` body — before it can ever reach the
generic acquisition queue. One generic code path, no per-source branch;
confirmed to correctly leave DanceInfo's title-only list stage alone (it
still gets a real detail fetch) and to never settle an empty, blank or
too-short body. Miltang's `/notices` endpoint separately gained the same
optional historical-cutoff parameter `tangocalendar_discovery` already uses,
narrowing only new candidate creation. See
`docs/TANGO_SOURCE_IMPLEMENTATION.md`'s "v0.82.2 fix" section for the full
mechanism, the scoped board recovery (Miltang: 0 → 57 listed events, 56
upcoming; SRC-W-002/003/004 confirmed undamaged and unchanged throughout),
and the re-observation numbers across four post-recovery cycles (zero
erosion, venue resolve rate 54% vs the original 52%, false `VERIFIED` = 0,
Human Review non-interference confirmed).

## v0.82.1 Miltang Live Source Acceptance + Venue Alias Compatibility

Status:
Live-accepted against the ROCKPro64 board's real staging database, 2026-09-05.

Version split:

- Product Runtime: 0.82.1
- Information Engine: unchanged (see the deployed image's own `/status` for
  the exact version) - no engine code changed in this release.

### SRC-W-005 - Miltang

A new SECONDARY/DIRECTORY source, `runtime/miltang_discovery.py`, reading
`https://miltang.com/milongas` (day-scoped, 14-day window) and
`https://miltang.com/notices` (unpaged). JSON-LD is read first; TIME, the
original LINK list and the recurrence label always come from the page's own
`<dl>` rows, since JSON-LD never carries a time-of-day. `source_url` is
always Miltang's own detail page - never one of the Facebook/Instagram/Kakao/
Daum Cafe links a record's LINK row carries, even when that is the only link
present.

Registered disabled by default (migration `023_miltang_source.sql`); see
`docs/TANGO_SOURCE_IMPLEMENTATION.md`'s own "SRC-W-005" and "Live Acceptance"
sections for the full field mapping and the one controlled one-shot
collection's measured numbers (108 discovered, 50 listed events, 52% venue
resolve rate, 3 auto-merged KTNow duplicates out of 50, zero wrong date/time/
venue, zero false `VERIFIED`, zero Claude-made review decisions).

**Venue alias compatibility fix**: Miltang names a venue as one space-joined
`"Brand 한글이름"` string (`"PISTA 피스타"`) where the existing venue alias
seed (migration 022) always registered the two spellings separately - found
by a dedup test that reads the venue through the real engine `extract_venue()`
rather than a hand-typed expectation. Rendered as `"Brand (한글이름)"`
instead, which the engine's own existing parenthetical-splitting already
resolves through the unmodified alias table - no new venue was created, no
shared extraction/resolution code was touched.

**Known limitation carried forward, not fixed in this release**: Miltang
exposes no structured cancellation flag (`eventStatus` was always
`EventScheduled` on every sampled record). A cancelled milonga is not
detected as such; this stays `UNKNOWN` rather than being guessed at from free
text. Separately, a shared, pre-existing scheduler behaviour (the generic
content-acquisition queue re-fetching an already-fully-synthesized body and
occasionally replacing it with the site's own generic tagline before engine
ingest) can silently drop a small fraction of items - a coverage gap, never a
wrong-data one - and already exists for the sources live before this release.

### TangoNOW (SRC-W-002) - unchanged

Still `config.parser = tangonow_firestore`. The site's own `eventsBundle`
Cloud Function was investigated live (one request replaces many paginated
Firestore calls) but is not wired into `collectors.py`'s dispatch table this
release: a live sample showed real schema heterogeneity - three different
date-field conventions mixed in one response array, `normalizedTime` null on
every sampled record, and roughly 80% of records with no usable source link
at all - that a source already live in production should not be switched
onto without a monitoring period first. `parse_bundle()`/`discover_bundle()`
exist and are tested, ready to wire in later.

### Tangodori - not implemented

Its own Terms (updated 2026-06-27) prohibit "scrape or abuse the APIs". No
collector, no Source row, no reverse-engineering of its route payload shape
was attempted, regardless of what robots.txt or technical accessibility might
suggest.

## v0.81.0 Real Source Data Pipeline - Alpha

Status:
Deployed and verified on the ROCKPro64, 2026-09-05.

Version split:

- Product Runtime: 0.81.0
- Information Engine: 0.76, unchanged - this release adds a discovery path,
  not a new engine capability.

### Why this version exists

Every source DanceMate has collected from until now was a search API: Daum
Cafe, Naver Blog/Cafe/Web. A source with real event data but no search API -
a community's own board - had no way in. This release adds one: `WEB`, a
platform that scrapes a board's own list page instead of calling a provider.

`runtime/web_discovery.py` is the new module - fetch the list page, parse its
rows (title, detail URL, posted date), robots.txt honoured exactly as deep
acquisition already honours it. `runtime/acquisition.py` gained one more
article-extraction method (`METHOD_TEMPLATE_BOARD`, a `readEdit`-div board
template several small Korean community sites share) alongside the existing
Daum-marker/og:description/whole-page chain. `runtime/collectors.py` gained a
`WEB` branch in `_collect_live`/`_collect_snapshot`, no engine collector
involved and no credential required. Nothing in `engine/` changed.

### The first WEB source is real, not a fixture

**SRC-W-001, K-TANGO** (`www.k-tango.net`) - the Korea Tango Community &
Festival organizing committee's own board, chosen for the same reasons a
source is chosen for this product: public without login, `robots.txt`
declares no restriction, the board's own posts carry real date/time/venue/fee
in plain server-rendered HTML with no JavaScript rendering required. Two
other real candidates were checked and set aside before this one - `ktnow.kr`
(Tango NOW) is a real tango-schedule site but its data exists only behind a
React/Firebase client SDK with no server-rendered content or same-origin API;
`onoffmix.com`'s `robots.txt` blocks every crawler except a named allowlist a
runtime fetcher does not match. See `docs/SOURCE_DATA_PIPELINE.md` for the
full comparison.

Run against the live site on 2026-09-05:

```
discovery:   10 posts found on /cnf/festival02/, all 10 new
acquisition: 9 FETCHED_FULL, 1 FETCHED_PARTIAL (avg 610 chars/post)
ingest:      9 ingested, 0 failed, 3 event candidates produced
```

The three candidates - two K-TANGO SF 2024 festival announcements and one
with `venue_text = "연세대학교 대강당"` (Yonsei University's main hall)
extracted straight from the post body - all landed at `engine_status =
POSSIBLE`, `review_state = PENDING`, with real `source_url`s pointing back
at the actual board posts. That is this release's success bar: a real public
source's event data, discovered without a search API, stored in PostgreSQL
with its evidence and provenance intact, waiting in the same Human
Verification queue every other source's candidates already sit in.

One extraction limitation showed up honestly rather than being hidden: a
K-TANGO post that lists five separate sub-events in one bulletin (a
performance, a venue tour, three milongas, each with its own date/time/venue/
fee) is not something the engine's single-event extractor was built to split
apart, so the candidate it produced took one event's date but a different
listed time. This is an existing engine characteristic meeting a new kind of
source text, not a regression this release introduced, and it is exactly what
Human Verification exists to catch - the candidate is `PENDING`, not silently
accepted.

### What did not change

`sources`, `source_items`, `source_item_content`, `content_fetch_log`,
`candidate_review_state`, `events` - every table this release writes to
already existed for Daum/Naver. Deep acquisition's retry/backoff/quota
handling, the scheduler's per-source failure isolation, and the Information
Engine's classify/extract/verify pipeline are all untouched; a WEB source
exercises exactly the same code a Daum or Naver source already exercises
from `source_items` onward. `runtime/tests` (747 passed / 9 skipped on the
board, plus the 135 collector/acquisition/source tests specific to this
change) and the existing Daum/Naver sources' collection results (unchanged:
still `PASS`, still producing their own items) confirm it.

Two pre-existing test failures were observed and are not from this change:
`test_freshness_reads_as_time_ago_while_it_is_recent` (a clock-relative
assertion, unrelated to source collection) and
`test_the_dashboard_buckets_match_what_the_search_returns` (asserts a global
event count against the live staging database, which now legitimately holds
more events than when that test was written - the exact pitfall
`memory/dancemate-board-test-run.md` already documents about staging-DB test
isolation). Neither touches `runtime/collectors.py`, `web_discovery.py`, or
`acquisition.py`.

### Known limitations

- One board, one list page - `web_discovery.py` does not paginate yet.
  K-TANGO's board fits on one page today (10 posts, 2023-2025); a future WEB
  source with more history will need pagination added.
- `events.organizer_id` does not exist, so K-TANGO's `ORGANIZER` role is
  recorded on the source, not the event.
- Engine `VERIFIED` status is unreachable for any current source (runtime
  `source_role` vocabulary never matches the engine's `ACCEPTABLE_SOURCE_ROLES`)
  - a pre-existing cross-source characteristic, not introduced here.
- Warm reboot hang on the ROCKPro64 remains open; out of scope for this
  release (infrastructure, not the data pipeline).

### Next recommended step

A second WEB source is the real test of whether `web_discovery.py`'s row
parser and `METHOD_TEMPLATE_BOARD` generalize past K-TANGO's board software,
or need a per-site override the way Daum's marker text already is one.

## v0.80.2 Date Inference Safety + Blocked Fetch Retry + Full Green Regression

Status:
Deployed and verified on the ROCKPro64, 2026-09-04.

Version split:

- Product Runtime: 0.80.2
- Information Engine: **0.76** — third version in which DanceMate modifies
  engine logic. `engine-v0.75` is untouched.

### Why this version exists

Three defects, no new features. A post from 2024 was showing as an event this
week; 47 items that had been refused once were never going to be asked again;
and one engine test needed a writable checkout, so the board could not report
a clean run.

### The year of a date has to come from somewhere

`_norm_date` attached a hardcoded 2026 to any date written without a year. So
"9/25" in a blog post from September 2024 became the 25th of September 2026,
and DanceMate would have sent somebody out on the wrong night for an event
that happened two years ago.

The year now comes from when the post was written — the nearest of the year
before it, of it, and after it. That single rule is what makes "1/3" written on
28 December mean January without a special case for December, and what keeps a
2011 post in 2011. An explicit year in the text always wins, in both
directions: a 2024 post announcing 2026 is announcing 2026, and a 2026 post
about 2024-09-25 means 2024.

With no post date there is nothing to reason from, so no date is claimed.
**Missing is recoverable; wrong is the failure this service exists to
prevent.** That costs nothing today: all 264 source items on the board carry a
published date.

`MAX_DAYS_FROM_POST` is 200, measured rather than picked. On the board, real
announcements land between 13 days before their post and 22 days after; the
wrong-year cluster starts at 369. 200 sits in the empty gap, and a test pins
it there.

The provenance goes on the evidence row, which already had a column for it:
EXPLICIT_YEAR, SOURCE_YEAR, UNKNOWN_YEAR. A date we read but could not place
is recorded with a null value, so the console shows a refusal rather than a
post nobody looked at.

### Two more things the audit turned up

Fixing the year rule removed one of the three wrong events. Finding the other
two meant looking at every listed event against the date of its post.

**A four-digit year was being chewed into a month and a day.** "수빈 y 제이나
서울 탱고캠프 전야제 밀롱가 공연 2010.12 곡명 : El amanecer" is a post about a
performance, and 2010.12 is when the music was recorded. The loose month/day
pattern matched the `10.12` inside it. The pattern is now bounded on both
sides. The year rule alone would only have moved this to 2011; it was a
separate bug wearing the same symptom.

**The post's date was being dropped on re-extraction.** Both acquisition
pipelines rebuild a record from the stored row when a body finally arrives,
and neither copied `published_at`. Every post whose body we successfully
fetched came back through the new rule with nothing to place its dates in a
year. `raw_posts` had held the column all along.

A forced re-read also now reaches items we only ever had a search snippet for.
It used to filter on the two fetched statuses, which is right when the body
changed and wrong when the extractor did — and the 2011 post was
FETCH_BLOCKED, so the one item that most needed re-reading could not be
reached.

### Result of the re-read

265 stored posts re-extracted, no external calls. Upcoming events with a date
more than 300 days from their post: **2 before, 0 after.**

### A page that refused us once was never asked again

FETCH_BLOCKED was in neither the settled set nor the retryable one. It read as
caution and behaved as amnesia. Underneath it were two separate mistakes:
blocked items were not selected for retry at all, and BODY_UNAVAILABLE — the
code on every one of those items — was not a known retry class, so it fell
through to the network default and was scheduled fifteen minutes out. A
fifteen-minute promise nothing ever kept.

Blocked items now come back after a day, then three, then weekly, indefinitely:
about fifty requests a year, cheap enough to keep the door open and the only
way a source coming back is ever noticed. Recovery needs no special case — the
row stores whatever the last attempt produced.

What does **not** come back: a login wall stays settled, because asking again
changes nothing and looks like an attack; robots.txt and an unsupported
content type are never retried at all; a 404 keeps its two attempts.

Retries carry up to 20% forward jitter, and migration 017 spread the existing
backlog across the following day rather than making all of them due the moment
this deployed. On the board: 70 blocked rows, every one scheduled, none
unscheduled, at most 7 in any hour, 1 due immediately.

Migration 017 also adds `last_attempt_at`. `fetched_at` records only success,
so nothing answered "did we even try?" — which is the question an operator
asks of a source that yields nothing.

### The engine can now report a clean run

`run_daily` takes a `report_dir`; production still defaults to the
repository's `data/reports`. The test points it at `tmp_path` and asserts the
run stays out of the checkout. As a side effect the engine suite no longer
dirties `engine/data` on every run.

### Verified on the board

- Runtime suite in the container, repository mounted read-only:
  **734 passed, 9 skipped, 0 failed**
- Engine suite, same mount: see the final report
- `check-server.sh`: 6/6 PASS
- NAVER API HUB blog / cafearticle / webkr: 200
- Memory 576Mi of 3.8Gi; disk 12% of 30G

## v0.80 Private Alpha Readiness + Real Human Review + Upcoming Event Quality

Status:
Deployed and verified on the ROCKPro64, 2026-09-04.

Version split:

- Product Runtime: 0.80
- Information Engine: 0.75 — unchanged. No extraction or classification rule
  moved in this release.

### Why this version exists

Not to extract anything new. To answer one question: can 김프로 open DanceMate
and decide where to dance tonight, without being misled?

Everything here follows from that. The dashboard opens on tonight instead of
totals. The review queue is ordered by how soon an event happens instead of
when it was collected. A source carries the decision somebody made about it,
separately from what the fetcher observes. And three counters say whether any
of it was used.

### The console now opens on the morning's question

`/admin` led with sources registered and items ever collected. Both true,
neither the thing an operator needs at 9am. It now opens on 오늘 / 내일 /
이번 주 / 검토 대기, with the five filters that lead somewhere, and the totals
have moved down under Collection where they belong.

Below that, coverage as genre against region, over upcoming events only. The
zeroes are the point: SALSA in Busan is 0, and no total shows that. It is the
shape of the next release's work, and it is not filled in by inventing sources.

### The review queue is about what is coming

The queue was ordered by collection time, which buries tonight's event under
last week's. It now sorts by how soon the event is and how much is missing, and
the default filter is 앞으로 rather than everything ever collected. Every
action carries Save & Next, so reviewing eight events is one pass, not eight
trips back to a list.

### A decision about a source is not an observation about it

"This cafe serves bodies only to a logged-in reader" is something the fetcher
learns every hour. "Replace it" is a judgement made once, and the console had
nowhere to put it. Sources now carry ACTIVE / KEEP / REPLACE / DISABLE /
MONITOR with a reason and a date, and a recommendation is offered beside it
with the counts behind it.

Nothing is applied automatically. Recording REPLACE does not stop collection,
and no source was disabled by this release.

Two decisions were recorded on 2026-09-04:

- **오살사 살사댄스 종합정보** — REPLACE. 21 items collected, 0 bodies read,
  and two other salsa sources are readable.
- **스윙팩토리 부산 스윙댄스** — KEEP, against a REPLACE recommendation. Its
  22 items are equally unreadable, but the recommendation counts alternatives
  by genre and ignores region: the "alternative" is 스위티스윙, which is not in
  Busan. **The recommendation is genre-blind, and this is the case that shows
  it.** A human overrode it, which is what the column is for.

### Three counters, no identifiers

List view, detail view, source click. A date and a count, and for detail views
an event id. No IP address, no session, no user identifier, no column that
could hold one. The source link goes through a redirect that validates the
destination against that event's own sources — a foreign URL is refused with
400 — so "they left to read the post" is countable. That is the one signal
worth having: a detail view says the card was interesting, a source click says
the card was not enough.

### Fixes found by actually opening the pages

- **A recorded source decision reached nothing.** `/admin/sources/{id}/{action}`
  was registered first and matches the same path as `.../decision`, so every
  Record button resolved to the catch-all, which 404s on an action it does not
  know. The form looked fine and saved nothing. Starlette matches in
  registration order; the specific route now comes first, with a test that
  asserts the order rather than the symptom.
- **The detail page said the same thing twice.** 종류 and 상태 both rendered
  the kind-of-event badge, and inside a `<dd>` the badges are plain inline
  siblings rather than flex children, so they touched: `소셜 (강습 포함)확인
  필요`.
- **A test needed a writable checkout.** `py_compile` writes the `.pyc` beside
  the source unless told otherwise, so it failed the moment the repo was
  mounted read-only — which is how the suite runs on the board.

### What is honest about the times

Three of the seven upcoming events show a clock with 시간 미확인 beside it:
`07:00`, `08:00`, `05:30`. All three almost certainly mean the evening, and
none of the three posts wrote 오후 or PM anywhere. The rule from v0.77 stands:
a dance event is not a reason to turn 7:30 into 19:30. The reading is shown
with the caveat, and those posts sit at the top of the review queue where a
person can settle them.

### Known limits, stated rather than fixed

- **A blocked body is never re-fetched.** `FETCH_BLOCKED` is in neither
  `SETTLED` nor `RETRYABLE`, so those 47 items are not retried at all — safer
  than the one-day backoff, but it also means a community that fixes its
  settings next week goes unnoticed. The stored `next_attempt_at` suggests a
  15-minute retry that never happens.
- **The source recommendation ignores region**, as 스윙팩토리 shows above.
- **Human review of live events: 0.** The queue is ordered, the actions work,
  and no live event was approved by Claude. All five actions are verified
  against synthetic candidates on a rolled-back connection, never through the
  live route.

### Added after the first cut: the styles are always on screen

The genre chips were built from whatever had events in the window, which
meant a reader could filter by swing only on a day swing already appeared.
That is backwards. "Is there any swing on tonight?" is a question the page
should answer with an empty list, not by removing the question.

Tango, Salsa and Swing are now fixed on the first screen, under the day tabs
and above the region row, read from the enabled genre master with those three
as a floor. All three start ticked. Unticking all of them means no events --
not a silent reset to everything.

Real checkboxes rather than styled links: the state lives in the control, so
it survives a reader who cannot see the colour, answers to the keyboard, and
works with the script missing. The submit button is what makes that true; the
script hides it and submits on change for everyone else.

The selection rides in the URL as `?genres=TANGO,SALSA`, through every day tab
and every region link, so a refresh keeps it and a link carries it.
`?genre=TANGO` still means what it always did, and the JSON API still answers
in codes -- `genre_label` was added beside it so pages can say Tango where they
used to say TANGO.

The region row moved to the same footing for the same reason: it was built
from the events on screen, so a day whose only event had no region left the
first screen with no region filter at all.

### Also in this release: NAVER API HUB authentication

`NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` are API HUB credentials and were
being sent to the legacy Search API host with legacy headers, which
authenticates nothing there. Every Naver source had been sitting at
AUTH_FAILED because of it.

The collector now talks only to `naverapihub.apigw.ntruss.com` with
`X-NCP-APIGW-API-KEY-ID` and `X-NCP-APIGW-API-KEY`. No legacy host or header
remains anywhere, and the two schemes are never mixed. The variable names are
unchanged, so no deployed `.env` had to move.

Probed against the gateway rather than guessed from documentation: blog,
cafearticle and webkr answer 200 with the same payload shape as before; news
and local answer 401 for these credentials and doc is 404, so none of those
three is offered. webkr had no runtime platform, hence `NAVER_WEB` and
migration 016 -- a platform that can be registered, not a source that
collects.

One blog source went AUTH_FAILED to PASS end to end: 153 source_items, 24
candidates, 8 events.

**And it surfaced a real problem.** A post published 2024-09-26 became an
event dated 2026-09-25: the body wrote "9/25" and the current year was
attached to it. That source serves posts back to 2011. The engine rules were
not changed to paper over it -- a year inferred years after the post is not
evidence, and what to do about it is a judgement, not a patch to slip into a
release. The event sits in the review queue.

### Verified on the board

- Full runtime suite in the container, repo mounted: **682 passed, 9 skipped**
- `check-server.sh`: 6/6 PASS
- Memory 634Mi used of 3.8Gi; disk 13% of 30G; containers under 64MiB each

## v0.79 Social Dance Event Classification + Coverage Recovery + Review Calibration

Status:
Deployed and verified on the ROCKPro64, 2026-09-04.

Version split:

- Product Runtime: 0.79
- Information Engine: **0.75** — second version in which DanceMate modifies
  engine logic. `engine-v0.74` is untouched and remains the baseline.

### Why this version exists

v0.78 added swing and salsa communities and got zero events from them, and
named the reason: `live_pipeline` drops every post the classifier calls CLASS
or OTHER, and the classifier knew exactly four event words, all tango.

### The hard half was never finding socials

It was not finding them where they are not.

The twenty-three swing posts collected on 2026-09-04 were read and labelled
before a line was changed: 2 socials, 2 mixed programmes, 12 lesson adverts, 2
sales notices, 1 performance timetable, 4 multi-day festivals left UNKNOWN
because whether they are a night out is a genuine judgement call.

**Six of those twenty-three say 소셜 or 파티 without announcing one.** Three
lesson blurbs explaining where you will use what you learn — `소셜에서 쓰는
동작들` — a season ticket that admits you to socials, a `파티팩` ticket bundle,
and a `졸업파티` sitting beside the lesson timetable's clock. A keyword match
turns every one of them into an event, which is worse than the zero we had.

So a social counts as announced when it is in the title, or written next to its
own clock with nothing but spacing and particles between:

    ■ 스윙타임빠 (9월 2일) 수 소셜 공지        title
    7시30분부터 소셜이 진행 됩니다              clock, particle, name
    20:00-22:30 소셜                        clock, name

`파티팩` and `정기권` are products. `10시간` is a length, not a time, so a
festival boasting about ten hours of social does not qualify on that alone.

Against the labelled twenty-three: **4 wanted, 4 found, 0 missed, 0 false
positives.**

### A post that teaches and then dances is both

Reading it as a class only is what lost the swing events. `SOCIAL_WITH_CLASS`
keeps the social, and the time rules keep the social's own hours. A workshop
weekend lists three ranges:

    - 15:00-16:30 발스윙 중고급
    - 16:45-18:15 쉐그 초급
    - 20:00-22:30 소셜

and the event runs at 20:00. Taking the first range would send someone to a
class they did not sign up for, which is the same class of error as reading PM
as AM.

### Coverage

Two of v0.78's five new cafes serve articles only to a logged-in reader, so two
public salsa cafes the same search returns were registered instead. Both are
readable.

| | v0.78 | v0.79 |
|---|---|---|
| Active sources | 6 | **8** |
| Source items | 97 | **110** (109 live) |
| Listed events | 23 | **33** |
| Tango | 23 | 22 |
| **Salsa** | **0** | **8** |
| **Swing** | **0** | **3** |
| Wrong times | 0 | **0** |
| False VERIFIED | 0 | **0** |

Kakao: 39 requests today, 156 items, 92 new. Month 135 requests against a
5,000/day CONFIGURED budget.

Every genre now has at least one upcoming event: Tango 6, Salsa 1, Swing 1.

### Tango moved by one, and it moved the right way

v0.78 listed 23 tango events and v0.79 lists 22. Compared post by post against
the v0.74 classifier over all 27 tango-source bodies, exactly one changed:

    [금요특강] 26년 9월 18일 시작!! 밀롱가/땅고 실전패턴!!
    "매주 금요일 만나는 클라스!! 수업때만 잘 따라와도~"

MILONGA to CLASS, because 워크샵 joined the class vocabulary and the body
contains it. It is a weekly lesson course that mentions 밀롱가 a dozen times,
and v0.78 was listing it as a tango event. One false positive removed, not one
event lost — but it is a change and it is named rather than folded into a total.

### Two defects, both caught by things that exist to catch them

**The engine's own gate1 replay caught a false positive I introduced.** Adding
the social branch, I also generalised the tango one: any class post mentioning
a milonga became MILONGA_WITH_CLASS. The fixture `Special Milonga Lesson개설
(9월17일 개강)` must produce no event and produced one. v0.74 required both a
class word and the phrase `open class`, and was right to. Restored exactly, and
verified case by case against the v0.74 classifier: identical on every tango
input.

**Re-extraction could not remove a candidate, only replace it.**
`reprocess_acquired` deleted a post's old candidates only when the new
extraction produced some, so a post that stopped being an event kept the
candidate it used to have — and the counter reported the stale one as if
nothing had changed. That makes a rule correction unable to take effect: the
engine says "this is a lesson" and the event it used to be sits there,
normalised and listed, forever. It is how five candidates survived the fix
above. Candidates a person has reviewed are still never touched.

**A filter chip promised what its page would not show.** Chips were counted
over everything from today onward while the page lists a window; a swing social
three months out put "Swing 1" beside a page returning nothing. Both read the
same dates now.

### Blocked sources

Login is not bypassed and no credential was touched.

| Source | Items | Readable | Events | State | Recommendation |
|---|---|---|---|---|---|
| 오살사 살사댄스 종합정보 | 21 | **0** | 0 | FETCH_BLOCKED | **REPLACE** — 인천살사 엘마르 and SDA cover salsa and are readable |
| 스윙팩토리 부산 스윙댄스 | 22 | **0** | 0 | FETCH_BLOCKED | **KEEP_BLOCKED** — the only Busan swing community found; costs one search call every three hours |
| 전국 밀롱가 정보 블로그 (Naver) | 0 | 0 | 0 | AUTH_FAILED | unchanged, shown plainly |

All 47 blocked items carry a backoff, so nothing is re-fetched in a loop.
Neither source was disabled: that is 김프로's call, and a community that fixes
its settings next week should not have been dropped this week.

### The reader gets words, not enums

`MILONGA` and `SOCIAL` are the engine's distinction, because tango names its
social event and the other scenes do not. A reader needs what they are turning
up to, so the page shows 밀롱가 / 소셜 / 소셜 (강습 포함) beside 확인 필요, and
the genre chips read Tango / Salsa / Swing with counts that match the page.

A social's genre comes from the community that posted it: the extractor can
tell a milonga is tango and cannot tell a 소셜 is swing. That stays a hint —
an event whose type names its genre still resolves from what it is.

### Review queue

Ordering was checked against the live queue rather than asserted. The top of
`/admin/review` is today's salsa social with no time, then tomorrow's events
missing a time, then those missing a venue. Filter counts: 시간 미확인 15,
장소 미확인 30, 요금 미확인 45, 충돌 0, 전체 51.

Human review is still 0. Nothing here approves a live candidate on 김프로's
behalf.

### Verification

| | |
|---|---|
| Engine suite | 646 passed (gate1 included) |
| Runtime suite, host | 452 passed, 207 skipped |
| Runtime suite, container | 649 passed, 9 skipped |
| Golden dataset | 4/4 found, 0 missed, 0 false positives |
| Migrations | 014, unchanged — no schema was needed |
| `/version` | product 0.79, engine 0.75 |
| Health | 6/6 PASS |
| Resources | 494Mi of 3.8Gi RAM, 12% of 30G disk, DB 11MB |
| Backup before starting | md5 match, dump-complete marker, sqlite integrity ok |

### Known and deliberate

- Salsa's 8 events and swing's 3 are mostly not upcoming; one of each is. The
  communities post about past nights as well as future ones.
- Venue resolution is 10/33 and fee 4/33. The new communities write differently
  from the tango boards the extractor was tuned on, and no rule was added on a
  pattern that had not been measured.
- Four multi-day festivals stayed UNKNOWN and produce no events. Whether a
  three-day workshop weekend is a night out is a judgement, not a rule.

## v0.78 Real Event Coverage + Alpha Event Quality + Admin/User UX Polish

Status:
Deployed and verified on the ROCKPro64, 2026-09-04.

Version split:

- Product Runtime: 0.78
- Information Engine: 0.74 (unchanged)

### Why this version exists

The pipeline worked and almost nothing was in it. One source, eighteen items,
fifteen events, and a console that could say how much it had collected but not
how good any of it was.

### Coverage: 18 items to 97

A live probe on 2026-09-04 asked the Daum cafe search four questions and
counted what came back: 100 documents from a dozen dance communities across the
country, of which the single source's `url_contains` filter kept **five**. The
filter was pinned to one board, and everything else — tango in 대전, 대구,
청주, 홍대, salsa at 오살사 and 엘마르, swing at 스위티스윙 and 스윙팩토리 —
was discarded on the way in.

Five of those communities are now their own sources, one per cafe, each with
the cafe's own address read from the posts it returned rather than guessed.
One source per community keeps provenance honest and lets an operator tune or
disable them one at a time.

| | before | after |
|---|---|---|
| Active sources | 1 | **6** |
| Source items | 18 | **97** (96 live) |
| Bodies fetched | 18 | **50** |
| Listed events | 15 | **23** |
| **Wrong times** | **0** | **0** |
| **False VERIFIED** | **0** | **0** |

Kakao usage for the whole expansion: 29 requests today, 127 items, 79 new. The
month stands at 125 requests against a 5,000/day CONFIGURED budget.

### Two things the new data made visible

**Two of the five cafes serve their articles only to a logged-in reader.**
43 items collected, 43 blocked, zero readable. Nothing is auto-disabled — a
community that fixes its settings next week should not have been dropped this
week — but the Sources page now shows items beside how many of them we could
actually read. "21 items" reads like a working source; "21 items, 0 readable"
is the same source and a different decision.

**An event's genre came only from the extractor's event type**, so a milonga
was tango and everything else was nothing. The genre now falls back to the
community the post came from, because a swing cafe posts swing events and that
is evidence rather than a guess. Without either, it stays empty.

### Salsa and swing are blocked in the engine, not in the sources

Worth stating precisely, because it is the next release's headline and it was
measured rather than assumed. `src/live_pipeline.py` drops every post the
classifier calls CLASS or OTHER, and `src/classifier.py` recognises exactly
four event words: `milonga`, `밀롱가`, `쁘롱`, `쁘락`. A swing social announced
as `■ 스윙타임빠 (9월 2일) 수 소셜 공지` is OTHER; one mentioning 강습 is CLASS.
Either way it never becomes a candidate.

So 스위티스윙 contributed 23 readable bodies and zero events, and every event
on the site is still tango. Fixing that means giving the engine a social-dance
event type — an engine 0.75 change with its own extraction measurement, not
something to slip into a UX release.

### Region: Seoul and Busan now tell each other apart

There was no route, HTML or JSON, to create a region at all. Seoul arrived in a
migration and nothing else could be added, so the two Busan venues 김프로
registered on 2026-09-04 were filed under the country-level South Korea row.

An Add Region form now sits beside Add Genre. Busan was registered, the two
venues whose addresses start 부산 were corrected through the normal Edit route
with an audit row each, and their four events followed:

    /api/events?region=Seoul   -> 2 upcoming, all Seoul
    /api/events?region=Busan   -> 1 upcoming, Busan

No bleed in either direction. Exactly two venues were changed; the other six
already matched their addresses, which was checked rather than assumed.

### The dashboard says how good the data is

Date, time, venue extracted, venue resolved, fee, region and human review, all
measured over the events a reader can actually reach — the alpha search's own
condition, so the panel and the site cannot drift apart. Every gap links to the
review filter that shows it.

Missing and wrong are counted apart and always will be. A blank fee is a fee we
do not have; a 07:30 on an evening milonga is a time we have and got backwards.
Engine v0.74 records the meridiem evidence it had, so a morning start on an
EXPLICIT PM marker is a regression with its own alert, while an unmarked 5시30
read as 05:30 is unconfirmed and not counted as wrong.

Measured on the board after the expansion, over 23 listed events:

| | |
|---|---|
| Date | 23/23 (100%) |
| Time | 18/23 (78%), 8 of them unconfirmed |
| Venue extracted | 10/23 (43%) |
| Venue resolved | 10/23 (43%) |
| Fee | 3/23 (13%) |
| Region | 10/23 (43%) |
| **Wrong critical fields** | **0** |
| **VERIFIED** | **0** |

Venue and fee dropped as a share because the new communities write differently
from the one the extractor was tuned on. The counts went up; the percentages
went down; both are true and both are on the screen.

### The review queue sorts by what matters

A value contradicting its post, then tonight and tomorrow, then a missing time,
then venue, then fee, then by date. A sort key, not a model — and tonight
outranks a more incomplete event three weeks out, because DanceMate exists to
answer where to dance tonight. Filters for pending, today, conflict, unknown
time, unknown venue, unknown fee and reviewed, each with its count rendered so
an empty one is visible before it is clicked.

### The site stops handing readers the engine's vocabulary

VERIFIED does not mean true, it means the evidence gate passed, and neither
phrase belongs on a page someone reads on the way out the door. Statuses are
확인됨 / 확인 필요 / 예정 / 정보 충돌 / 취소, and a human review shows as
관리자 확인 — worded apart on purpose, so an approval never looks like proof.

Also new: when we last read the post behind an event, with a 재확인 필요 nudge
when an event is tonight and what we know is a day old. Past events are out of
the default list. Cancelled ones are out of the list but keep their page —
someone holding the link deserves to be told it is off, not shown a 404. Genre
and region chips appear only where there is more than one thing to choose,
because offering a filter that returns nothing claims events exist that do not.
And the layout survives a phone.

### One defect the acceptance run caught

Inserting the review filters above `admin_review` left the route decorator
attached to the helper below it, so `GET /admin/review` resolved to a function
taking a row and answered 422 asking for a request body. The page had been
broken since the filters went in and the suite could not see it, because
nothing asserted which function serves which path. Two tests now do.

### Security

The admin password was rotated on the board before any other work: a new
40-character value, `.env` at mode 600, the previous file kept as a dated
backup. Anonymous still 401, wrong password 401, new credentials 200. The value
was not printed, logged, committed or written to any report — the incident that
prompted the rotation was exactly that leak.

### Verification

| | |
|---|---|
| Runtime suite, host | 449 passed, 205 skipped |
| Runtime suite, container | 645 passed, 9 skipped |
| Migrations | 014, unchanged — no schema was needed |
| `/version` | product 0.78, engine 0.74 |
| Health | 6/6 PASS |
| Resources after expansion | 488Mi of 3.8Gi RAM, 12% of 30G disk, DB 11MB, logs 8K |
| Backup before starting | md5 match on the engine store, dump-complete marker, sqlite integrity ok |

### Known and deliberate

- Salsa and swing coverage is zero events, and the reason is in the engine, not
  the sources. Named above with the file and the four words responsible.
- Naver is still AUTH_FAILED and was not touched. No credential was changed and
  the console keeps showing the state plainly.
- Fee is 3/23. Most of these posts genuinely do not state one, and no rule was
  added on a pattern that had not been measured.
- Two blocked sources are left enabled and visible rather than removed.

## v0.77.3 Admin Master Data Edit & Management UX

Status:
Deployed and verified on the ROCKPro64, 2026-09-04.

Version split:

- Product Runtime: 0.77.3
- Information Engine: 0.74 (unchanged — this release touches no extraction)

### Why this version exists

Registering master data from the console worked. Correcting it afterwards did
not. Venues had no Edit at all; genres could only be toggled; regions had
nothing; organizers had nothing; sources could only be changed through a JSON
PATCH. The way to fix a typo was to open the database.

### One editing pattern, five entities

Genres, regions, venues, organizers and sources are different things, but the
operator's question is the same each time — *this row is slightly wrong, let me
fix it* — so they share one form, one route shape and one set of rules.

The form opens inline where the row is listed and arrives filled in with what
the row says. An empty form asks someone to retype the record in front of them.
Cancel is closing the block: nothing was sent, so nothing has to be undone.

What the pattern refuses to do matters more than what it does.

**Identity does not move.** A rename keeps the same id, so 라 벤따나 can become
La Ventana with its events still attached and the raw string still resolving
through its alias — the unresolved queue does not reopen.

**Codes are read-only, not merely discouraged.** `TANGO` and `KR-SEOUL` are how
sources, filters and bookmarked URLs find a row; renaming one breaks every
reference silently. Source keys likewise, since the Information Engine's config
matches on them. They are rendered, disabled, so an operator can see the value
without being invited to change it.

**Provider credentials appear nowhere.** Not in any editable list, not in the
config blob, not rendered. A console that can show a secret is a console that
can leak one.

**Enabling through an edit clears the same bar as the Enable button**, so
editing is not a way around v0.75's rule that a source the scheduler will fetch
from has to validate first. An interval change is picked up by the next due
calculation.

**A rejected edit is a sentence, not a 500.** A duplicate name in one region,
an interval under the floor, an empty required field, a bad foreign key — each
comes back as something an operator can act on. The same name in a *different*
region is allowed, because the unique index allows it: Studio A in Seoul and
Studio A in Busan are different places.

**Only fields that actually differ are written.** Open a form, save it
unchanged, and nothing is written and nothing is recorded.

### Venue aliases

The edit form lists a venue's spellings with how many events currently reach it
through each one. Removing a busy alias means that spelling stops resolving and
returns to the unresolved queue, so it asks first — a question, not a refusal.

### Address and region disagreement

An address naming a different region than the one selected is reported, never
applied. The operator may know better, and silently rewriting their choice
would make the region filter wrong in a way nobody could see.

### Audit

Migration 014 records every master-data change: entity, id, name kept verbatim,
action, reviewer, and the fields that changed. Kept separate from
venue_resolution_actions, which answers a different question — that table is
about strings read from posts, this one about the master rows themselves.
Disabling is recorded as DISABLE, not as an edit that happened to touch the
enabled column, so "who turned this off" is one query.

### Three defects, all found by the container run

The host suite passed and the board's did not, three times over, and each was
real:

**A blank name could be saved.** `update_venue` and `update_organizer` accepted
a whitespace-only name, so an edit could rename a venue into something no list
can display. `create_venue` has always refused that; an edit had no reason not
to.

**The value compared was not the value stored.** `changed_fields` trimmed
before comparing but handed on the raw string, so `"  PISTA  "` was written
with its spaces and an all-whitespace name reached the database looking
non-empty.

**A create-and-link audit row lost its venue name.** Only the delete paths were
passing `venue_name`, so the row recording a link would have gone nameless the
moment that venue was removed.

A fourth was a test of mine, worth writing down: it built a source with
`source_role="SECONDARY"`. That is the Information Engine's vocabulary. The
runtime's roles are COMMUNITY, PROMOTION_BOARD, VENUE, ORGANIZER, DIRECTORY and
AGGREGATOR, and the two are not interchangeable.

### What the board looked like

Between the last release and this one, 김프로 resolved all eight waiting venue
strings — the audit trail shows eight CREATE_AND_LINK actions on 2026-09-04
between 01:02 and 01:12, with addresses no extractor produced (`부산진구 부전로
34`, `서울시 마포구 양화로 12길 24 선진빌딩 B1`) because a person knew them.

| | |
|---|---|
| Venues registered | 8 |
| Live events with a resolved venue | **10 of 15** |
| Unresolved queue | 0 |

아미고스튜디오 and 데땅고 are Busan addresses filed under the country-level
region, because Busan is not registered as a region yet. That is the honest
outcome of a region list that has only Seoul in it.

The check that noticed this change first read as test data leaking into the
staging database. Reading the audit trail before touching anything is what
distinguished an operator's afternoon of work from a mess to clean up.

### Verification

| | |
|---|---|
| Runtime suite, host | 423 passed, 194 skipped |
| Runtime suite, container | 607 passed, 9 skipped |
| Migrations on the board | 014 of 014 applied |
| `/version` | product 0.77.3, engine 0.74 |
| Health | 6/6 PASS |
| Console pages | venues, organizers, sources, master all 200 with Edit |
| Synthetic end-to-end | PASS, data removed |
| Live data after every run | 15 live events, 8 venues, 0 organizers |

Browser acceptance against the real board: 8 Edit forms on Venues prefilled with
the real names, addresses and regions; 6 on Sources with `SRC-D-001` and friends
read-only and the interval editable; 5 on Genres & Regions with `TANGO` and
`KR-SEOUL` read-only. No credential-shaped string appears on any of them.

The synthetic run walked one venue and one organizer through the real HTTP
routes: created and linked → renamed and re-addressed, with the event still
attached and the raw string still resolving → alias added and resolving →
region changed, and the event dropped out of `?region=Seoul` → organizer
renamed and disabled → safe delete still working afterwards. Then removed, with
live counts checked.

### Known and deliberate

- The Human Review screen shows the venue string as extracted from the post,
  not the master venue's name. That is not stale data — a reviewer is checking
  extraction against the post, and the raw string is the thing being checked.
- Enable/disable stays a separate button rather than a checkbox in the edit
  form. An unchecked checkbox is simply absent from a form submission, which
  would read as "unchanged" and silently ignore the operator.
- Genres, regions and organizers still have no delete. They are disabled, and
  events already tagged with one still have to resolve.

## v0.77.2 Venue Default Prefill + Safe Venue Delete

Status:
Deployed and verified on the ROCKPro64, 2026-09-04.

Version split:

- Product Runtime: 0.77.2
- Information Engine: 0.74 (unchanged — this release touches no extraction)

### Why this version exists

Two complaints about the screen v0.77.1 built, both fair.

**The form asked for what was already on screen.** `라 벤따나` was fine: its
address sits inside the extracted string, so v0.77.1 already split it. `PISTA`
and `엔빠스` were not. Their posts carry `서울 마포구 월드컵북로6길 49 B1` and
`서울특별시 서초구 반포대로30길 82 우서빌딩 지하 1층`, and the form left Address
empty, because it only ever looked at the extracted string.

**A venue registered by mistake could not be removed.** There was no way back
from a wrong Create & Link except editing the database.

### Prefill now reads the post, not just the string

The address has to be written immediately after the venue's own name — which is
how these posts do it — or on a labelled `주소` line. Never merely present
somewhere in the body: one post mentions a venue, a car park and next week's
other milonga, and filling the form with the wrong one is worse than leaving it
blank. Two posts disagreeing offer neither; two answers is not a stronger
signal than none, and both posts are linked on the same screen.

An address ends where the post stops talking about it. `서울 마포구 월드컵북로6길
49 B1 📩 예약 / 문의` stops at the emoji; `반포대로30길 82 우서빌딩 지하 1층
밀롱가 : 13,000원` keeps the building and the floor but not the fee.

The region follows from the address, through the same Korean-to-English lookup
v0.77.1 added. The form says which fields it filled and where each came from,
and every one stays editable.

Measured against the eight strings actually waiting on the board:

| Raw string | Name | Address | Region | From |
|---|---|---|---|---|
| 라 벤따나 (서울 마포구 잔다리로 48, 2층) | 라 벤따나 | 서울 마포구 잔다리로 48, 2층 | Seoul | raw string |
| PISTA | PISTA | 서울 마포구 월드컵북로6길 49 B1 | Seoul | **the post** |
| 엔빠스(EnPaz Tango Studio) | 엔빠스 | 서울특별시 서초구 반포대로30길 82 우서빌딩 지하 1층 | Seoul | **the post** |
| 아미고스튜디오 | 아미고스튜디오 | — | — | — |
| Tango Andante | Tango Andante | — | — | — |
| 데땅고 | 데땅고 | — | — | — |
| OCHO | OCHO | — | — | — |
| Tango O Nada | Tango O Nada | — | — | — |

The five blanks are blank because no post behind them contains an address. That
was checked rather than assumed.

### A venue can be removed, and removing it takes nothing with it

A venue here is a link. The posts, the evidence, the candidates and the events
all exist without one and all survive one, so deletion undoes the link and
stops.

`/admin/venues` shows how many events use each row. A venue nothing references
can be deleted outright. One that events point at cannot be deleted by the same
click: the confirmation names the count first, because finding out afterwards
is not a confirmation.

**Unlink & Delete** sends those events back to the raw string they were read
from — `venue_text` untouched, status back to UNRESOLVED, region cleared — puts
the string back in the queue so it can be decided again, and then removes the
venue. On the user surface the line returns to the raw string marked 미확인
rather than disappearing.

**Deactivate** is the gentler option, for a venue that is wrong for new work
but right for what is already attached to it: nothing unlinked, nothing
deleted, just out of circulation.

Automatic merges based on that venue are released, because the duplicate rules
merged on date, place and time and the place is gone; the next scan decides
again on what is now true. A person's duplicate verdict is left exactly as it
is — automation releases what automation decided.

Migration 013 makes the audit survive its subject, the same lesson as 010: the
`venue_id` foreign key blanked itself on delete and then failed the table's own
rule that a linking action must name a venue. The column is now a plain id with
the name stored beside it, so "deleted 라 벤따나, 2 events unlinked" stays
readable after 라 벤따나 is gone.

### One unrelated defect, found today

`test_quota_is_per_day` asserted that KAKAO's usage on 2026-09-04 was exactly
10 after recording 10. That held only while the hardcoded date was in the
future. This morning it arrived, the scheduler had already spent six real
requests against it, and the test read 16. The invariant it is actually about —
recording against one day leaves every other day alone — is a delta, and the
test beside it already measured that way. It would have broken today with or
without this release.

### Verification

| | |
|---|---|
| Runtime suite, host | 413 passed, 164 skipped |
| Runtime suite, container | 568 passed, 9 skipped |
| Migrations on the board | 013 of 013 applied |
| `/version` | product 0.77.2, engine 0.74 |
| Health | 6/6 PASS |
| Console pages | /admin/venues, unresolved, events, duplicates all 200 |
| Synthetic end-to-end | PASS, data removed |
| Live data after every run | 15 live events, 8 open queue entries, 0 venues |

The synthetic run walked `TEST DELETE ALPHA` through the real HTTP routes:
queued unresolved → Create & Link → venue on the user surface with its region →
plain Delete **refused** while events used it → Unlink & Delete → event back to
its raw string with its source, date and fee intact, region gone, string
requeued, alias no longer resolving, audit row still naming the deleted venue.
Then removed, with live counts checked before and after.

### Known and deliberate

- Venue resolution is still 0/15, and the eight live strings are untouched.
  Two of them now come with an address the operator does not have to type.
- No Undo button. Unlink & Delete already returns an event to exactly the state
  a wrong link took it from, which is the same outcome an undo would produce;
  a second path to it would be more code and one more thing to get wrong.
- The venue dropdown is still a plain `<select>`. Filtering can wait for a list
  long enough to need it.

## v0.77.1 Venue Resolution Admin UX Patch

Status:
Deployed and verified on the ROCKPro64, 2026-09-03.

Version split:

- Product Runtime: 0.77.1
- Information Engine: 0.74 (unchanged — this release touches no extraction)

### Why this version exists

v0.77 built the Unresolved Venues queue and left it unusable. It could link a
string to an existing venue and nothing else, and the Venue Master was empty,
so the dropdown was empty too. The one screen built for this job could not do
it: the operator had to leave for `/admin/venues`, create a venue from memory,
and come back to a queue whose context they had just lost. On the board that
was all eight waiting strings.

The success condition here is not "venue creation exists". It is that with an
empty Venue Master, one screen is enough to read the post, create the venue,
link the string and watch the waiting events resolve.

### The queue is now a decision screen

Each entry is a card carrying what it takes to decide:

- **the post it came from**, linked, with a line of surrounding text. `OCHO`
  could be a studio or the name of the event, and only the post says which.
- **Link Existing, New Venue and Not a venue side by side.** None of them
  buried — with no venues registered, the empty dropdown is replaced by a
  banner that points at New Venue rather than a silently useless select.

### The form is prefilled, and says when it guessed

`라 벤따나 (서울 마포구 잔다리로 48, 2층)` splits into a name and an address,
because the bracket holds an address. `엔빠스(EnPaz Tango Studio)` does not: the
bracket is another name for the same place, so it becomes an alias and the
address field stays empty rather than being filled with a guess. When the split
was inferred the form says so.

A region is preselected only when the address names one. Korean addresses and
an English region master needed an explicit bridge, so there is a lookup table;
an unregistered region still selects nothing. Defaulting everything to Seoul
because most of it is Seoul would file a Busan milonga under Seoul, and the
region filter would then lie to a dancer in either city.

The raw string is always registered as an alias, which is the entire point:
the next collection resolves it without anyone being asked again.

### Create & Link is one transaction

Creating the venue and then failing to link it would leave a master record
nobody asked for beside a queue entry that still looks untouched — and the
operator would reasonably create it again. The three writes run in one
`con.transaction()`, and the route owns the commit.

### It asks before creating a second row for the same place

Exact matches on normalised name, registered alias and normalised address are
offered as "you may already have this", each with Link Existing beside it and
Create Anyway below. A warning, not a refusal: two studios can share a name.
No fuzzy scoring — a warning nobody can check is one they learn to click past.

### Not a venue asks first

The string stops being asked about; the events and the posts behind it are not
touched. A reason can be recorded and is kept.

### Every venue decision is audited

Migration 012 records reviewer, raw string, action, venue, how many events
actually moved, and before/after. Kept out of `human_review_actions`
deliberately: that table records a verdict about one candidate, and
"아미고스튜디오 is that studio" is one decision settling three events at once.

### What the board showed

Eight strings waiting, and they are not equal. `OCHO` had eight waiting events
and every one came from a PoC fixture — no source link, no context, nothing to
read, because there is no live post. It sat in the queue looking exactly like
`라 벤따나`, which has two live posts and a readable address.

The queue now counts live events separately, orders by them, and marks a string
no live post ever produced. Nothing is hidden; the screen just stops spending
attention as though every row were worth the same.

| String | Events waiting | Live |
|---|---|---|
| 아미고스튜디오 | 3 | 3 |
| Tango Andante | 2 | 2 |
| 라 벤따나 (서울 마포구 잔다리로 48, 2층) | 2 | 2 |
| PISTA | 2 | 1 |
| 엔빠스(EnPaz Tango Studio) | 1 | 1 |
| 데땅고 | 1 | 1 |
| OCHO | 8 | **0** |
| Tango O Nada | 1 | **0** |

None of these were decided. The live queue is김프로's to judge and was left
exactly as found.

### Three defects only a real database could show

The container run failed where the host run passed, and all three were real:

**`create_and_link` called `con.rollback()` on a connection it was handed.**
That discards whatever else the caller had in flight. The writes now run in
`con.transaction()` — a real transaction on an autocommit connection, a
savepoint inside a larger one — and committing went back to the route.

The same bug had already committed test rows into the staging database: 17
venues, 19 queue entries and 19 audit rows. Removed after checking that no
event referenced any of them, and that the eight live queue entries and 15 live
events were untouched. A full suite run afterwards left the database clean,
which is the proof the fix works.

**A duplicate matching on both the name and the raw string reported one
reason**, because the two were folded into a dict key that overwrote itself.

**An address reading 서울 selected no region**: addresses are Korean, the region
master is seeded in English, and nothing bridged them.

Two tests were also asserting on the duplicate scan's global counters, which
say nothing on a database that also carries live events and a scheduler that
scans them. They now assert about the events they created.

### Verification

| | |
|---|---|
| Runtime suite, host | 404 passed, 147 skipped |
| Runtime suite, container | 543 passed, 8 skipped |
| Migrations on the board | 012 of 012 applied |
| `/version` | product 0.77.1, engine 0.74 |
| Health | 6/6 PASS |
| Synthetic end-to-end | PASS, data removed |
| Live data after all runs | 15 live events, 8 open queue entries, 0 venues |

Synthetic acceptance walked `TEST VENUE ALPHA` through the real HTTP route:
queued unresolved → Create & Link → alias registered → event resolved → venue,
address and region on `/events/{id}` → returned by `?region=Seoul` → audit row
written. Then removed, with live counts checked before and after.

### Known and deliberate

- Venue resolution is still 0/15. The eight decisions are김프로's, and this
  release exists to make them possible, not to make them.
- The existing-venue dropdown is a plain `<select>`. With a handful of venues
  that is the right amount of machinery; filtering can wait for a list long
  enough to need it.
- No JavaScript framework. The inline form and the confirmation are `<details>`
  blocks that work with scripting off.

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
