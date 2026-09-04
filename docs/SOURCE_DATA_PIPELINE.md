# DanceMate Source Data Pipeline

This is the application/data-pipeline document. For OS, network, Docker,
PostgreSQL and Caddy on the ROCKPro64, see
`/opt/dancemate/docs/ROCKPRO64_SETUP.md` on the board (infrastructure only,
not tracked in this repository). This document is scoped to what happens once
a request reaches the DanceMate runtime container.

## 1. Data flow

```
Source (WEB board / Daum Cafe / Naver API Hub)
  -> Fetch (discovery: list page or search API)
  -> source_items (PostgreSQL, raw intake, deduplicated by content hash)
  -> Fetch (deep acquisition: the post's own URL)
  -> source_item_content (PostgreSQL, extracted article text, never raw HTML)
  -> RawPostRecord -> Information Engine (classify, extract, verify)
  -> event_candidates + evidences (Information Engine's own SQLite)
  -> events (PostgreSQL, normalized, review_state = PENDING)
  -> Human Verification queue (candidate_review_state)
```

Everything from `source_items` onward already existed before this document's
source (v0.75-v0.80.2, Daum Cafe + Naver API Hub). What v0.81 adds is a second
**discovery** path for sources that are a community's own board rather than a
search API - `runtime/web_discovery.py` - plus a small extension to
`runtime/acquisition.py`'s article extraction so a board-template page (not
just Daum's) yields a real article instead of navigation chrome. Nothing in
the Information Engine changed.

## 2. Source Adapter structure

Two discovery shapes exist, dispatched by `runtime/collectors.py` on
`sources.platform`:

- **Search-API platforms** (`DAUM_CAFE`, `NAVER_CAFE`, `NAVER_BLOG`,
  `NAVER_WEB`): the Information Engine's own collector classes
  (`engine/src/collectors/daum.py`, `naver.py`) call a provider's search
  endpoint and return matching posts directly. Needs a credential
  (`KAKAO_REST_API_KEY` or `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`).
- **`WEB`**: no search API exists, so `runtime/web_discovery.discover()`
  fetches the source's own board list page (`sources.config.board_urls`,
  one or more URLs) and parses its rows directly. No credential needed -
  `describe_capability("WEB")` always reports `live: True`.

Both shapes produce the same plain-dict shape (`source_id`, `platform`,
`source_url`, `title`, `body`, `published_at`, `acquisition_quality`), which
`collectors._to_raw_item()` turns into the same `RawItem` either way. Deep
acquisition, ingest, normalization and review never know which discovery
path a `source_item` came from.

No new abstraction layer was added on top of this - a third discovery shape
(if one is ever needed) gets its own `if platform == "..."` branch in
`_collect_live()`, the same way `WEB` was added, not a plugin registry.

## 3. Currently configured sources

| source_key | platform | name | role | board(s) |
|---|---|---|---|---|
| SRC-D-001, SRC-D-010..021 | DAUM_CAFE | 라틴속으로 등 | PROMOTION_BOARD / COMMUNITY | search query, pre-existing |
| SRC-N-001 | NAVER_BLOG | 소셜댄스 블로그 검색 | AGGREGATOR | search query, pre-existing |
| **SRC-W-001** | **WEB** | **K-TANGO** | **ORGANIZER** | `http://www.k-tango.net/cnf/festival02/index.jsp` |

K-TANGO is the Korea Tango Community & Festival organizing committee's own
site (Argentine Tango - the priority-1 genre). Its `/cnf/festival02/` board
posts its own festival/milonga announcements: real date, time, venue and fee
per post, plain server-rendered HTML, no login, no JavaScript rendering.

**Why this source**: `robots.txt` does not exist on `www.k-tango.net` (no
restriction declared for any crawler); its privacy policy (`/member/policy.jsp`)
governs member personal data, not automated reading of public board pages,
and contains no crawling restriction. The board publishes real, dated event
announcements with venue and fee - not a synthetic sample. HTTPS on this host
fails certificate validation on at least one client (Windows/schannel);
`config.board_urls` uses `http://` deliberately, which the site serves
without redirecting, so this is not a downgrade of anything the site itself
offers over HTTPS.

**Considered and set aside**: `ktnow.kr` (Tango NOW) - real event data exists
but only behind a React/Firebase client SDK, no server-rendered content and
no same-origin API (every path returns the same SPA shell); `onoffmix.com` -
robots.txt blocks every user agent except a named allowlist that a runtime
fetcher does not match; `allaboutswing.co.kr` - a real, robots-friendly site,
but its public boards are class-administration notices, not event
announcements with the fields this pipeline needs.

## 4. Raw storage

Unchanged from v0.76 - `runtime/acquisition.py` stores extracted article
text, never raw HTML (`source_item_content.extracted_text`), plus
`content_fetch_log` (host, HTTP status, outcome, duration) and
`source_items.raw` (the discovery-time payload, including the WEB board's
own posted date). A WEB source's `source_items.content_hash` and
`source_item_content.content_hash` work identically to a Daum/Naver item's -
`store_item()` does not know or care which discovery path produced the row.

### Extraction: a second, host-independent extraction method

`extract_article()` tries, in order: a `readEdit`-div template board
(`METHOD_TEMPLATE_BOARD`, new in v0.81) -> Daum's marker-text article region
(`METHOD_ARTICLE_REGION`) -> `og:description` -> the whole visible page.
`readTop`/`readEdit`/`readBottom` is a board template several small Korean
community sites share, not something specific to k-tango.net, so this check
is not host-gated - any future WEB source built on the same board software
gets a correct extraction with zero new code, the same way `og:description`
already works across arbitrary sites.

## 5. Event Candidate generation

Unchanged - the Information Engine's `classify()`/`extract_single()`/
`verify()` (`engine/src/classifier.py`, `extractor.py`, `verifier.py`) are
untouched. `classify()` looks for `밀롱가`/`milonga` or a social-with-its-own-
clock pattern (`소셜`/`파티`/`social`/`party` next to a time) - vocabulary
that already matches K-TANGO's own posts (they say "밀롱가" throughout).

## 6. Evidence

Unchanged - evidence lives in the Information Engine's own SQLite
`evidences` table, one row per extracted field per candidate, exactly as it
does for a Daum or Naver post. A WEB source's evidence is indistinguishable
in shape from any other source's; the engine does not know a `RawPostRecord`
came from a board scrape rather than a search API.

## 7. Duplicate handling

Unchanged - `event_duplicate_pairs`/`event_duplicate_decisions`
(`runtime/duplicates.py` - pre-existing) key on date/venue/name/time
similarity regardless of source platform. Not modified for this source.

## 8. Human Verification

Unchanged - `candidate_review_state.review_state` (`PENDING` /`APPROVED`/
`EDITED`/`REJECTED`/`DUPLICATE`/`CONFIRMED`), driven by `runtime/review.py`.
A K-TANGO-derived event reaches the same PENDING queue an operator already
reviews for Daum/Naver events, with the same `source_url`, evidence and
duplicate-candidate visibility.

Note on `engine_status`: the engine's `verify()` only marks an event
`VERIFIED` when `source_role in {PRIMARY, PRIMARY_VENUE, SECONDARY}` (engine
vocabulary). The runtime's `sources.source_role` vocabulary
(`ORGANIZER`/`COMMUNITY`/... - a pre-existing, separate vocabulary) is passed
through as-is and never matches, so **every** source in this deployment -
Daum, Naver, and now K-TANGO - lands its candidates at `POSSIBLE`, not
`VERIFIED`. This is existing, cross-source behaviour, not something this
source introduced; `review_state = PENDING` (the actual verification queue)
is unaffected either way.

## 9. Scheduler

K-TANGO is registered with `collection_interval_minutes = 240` (4 hours) -
a festival announcement board updates far less often than a search feed, and
one list-page fetch a run is enough to see anything new. `scheduler/intake_job.py`
is unmodified: `due_sources()`/`collect_source()` already select by
`enabled` + interval regardless of platform, and `WEB`'s `quota.provider_for()`
returns `None` (no paid-API budget applies), so a WEB source is never quota-
blocked. Deep acquisition (`scheduler/acquisition_job.py`) and ingest
(`scheduler/intake_job.py` -> `runtime/engine_ingest.py`) already ran per
`source_item` regardless of platform and needed no change.

A failing fetch does not propagate: `runtime/acquisition.py`'s existing
retry/backoff (`RETRY_SCHEDULE`, `MAX_ATTEMPTS`, `PERMANENT_ERRORS`) and
`collect_source()`'s per-source try/except (one source's exception is
recorded and the scheduler moves to the next) both applied to K-TANGO without
any change - the same code path an unreachable Daum post already exercises.

## 10. Execution

```bash
# One-off collection (bypasses the scheduler's interval check) - admin/CLI only
python -m runtime.collectors  # see runtime/collectors.py:test_source for
                                # the read-only [Test] path an operator uses
                                # before enabling a source

# What the scheduler itself calls, on interval:
scheduler/intake_job.py:run()       # discover -> source_items
scheduler/acquisition_job.py        # source_items -> source_item_content
scheduler/intake_job.py:ingest_pending()  # in runtime/engine_ingest.py
                                            # -> Information Engine -> events
```

## 11. Debugging

```sql
-- Has K-TANGO been collected from, and what did it find?
SELECT * FROM source_collection_runs
  WHERE source_id = (SELECT source_id FROM sources WHERE source_key='SRC-W-001')
  ORDER BY started_at DESC LIMIT 5;

-- Raw items discovered
SELECT source_item_id, title, url, published_at, ingest_state
  FROM source_items WHERE source_id =
  (SELECT source_id FROM sources WHERE source_key='SRC-W-001');

-- Deep acquisition outcome per item
SELECT c.acquisition_status, c.http_status, c.content_length, c.fetch_error
  FROM source_item_content c JOIN source_items i USING (source_item_id)
  WHERE i.source_id = (SELECT source_id FROM sources WHERE source_key='SRC-W-001');

-- Candidates this source produced, and where they sit for review
SELECT event_id, event_name, event_date, venue_text, fee, engine_status, review_state
  FROM events WHERE source_item_id IN
  (SELECT source_item_id FROM source_items WHERE source_id =
   (SELECT source_id FROM sources WHERE source_key='SRC-W-001'));
```

`runtime/collectors.test_source(settings, source)` is the read-only
equivalent of the admin [Test] button - reachability and a few sample titles,
never a write. It works for a WEB source exactly as it does for Daum/Naver.

## 12. End-to-end test results

See the v0.81 entry in `RELEASE_NOTES.md` for the actual run: sources
collected, items discovered, acquisition outcomes, candidates produced, and
the reboot/regression checks against the existing pipeline.

## 13. Known limitations

- **One board, one page.** `web_discovery.discover()` fetches only the list
  page's first page; K-TANGO's `/cnf/festival02/` board currently fits on one
  (10 posts spanning 2023-2025), so nothing is lost yet, but a source with
  more history will need pagination added to `web_discovery.py` before it can
  see its own backlog - deliberately deferred rather than built for a source
  that does not need it yet.
- **A pinned post's badge text stays in the title** (e.g. `공지 ... NEW`) -
  cosmetic, and the classifier only reads the body's event-signal words, not
  the title's badges.
- **`organizers` is not linked to `events`.** K-TANGO's posts are clearly
  organizer-published, but the runtime schema has no `events.organizer_id`
  column yet (a pre-existing gap noted, not introduced, by this source) - the
  `sources.source_role = ORGANIZER` classification is the only place that
  fact is currently recorded.
- **Engine `VERIFIED` is unreachable for any current source** (see §8) - a
  pre-existing cross-source characteristic, not specific to WEB or K-TANGO.

## 14. Next recommended steps

- A second WEB source, once one exists, is the real test of whether
  `web_discovery.py`'s row regex and `METHOD_TEMPLATE_BOARD`'s div markers
  generalize past K-TANGO, or need a per-site override the way Daum's
  marker text already is one.
- Pagination for `web_discovery.discover()`, once a WEB source has more
  history than one list page holds.
- `events.organizer_id`, so an ORGANIZER-role source's authority is visible
  on the event itself, not only on the source row.
