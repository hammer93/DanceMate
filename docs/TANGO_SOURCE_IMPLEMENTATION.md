# Tango Source Expansion — Implementation Notes (v0.82 TOP 3 IMMEDIATE + v0.83 Source Application)

This records what was actually built: first the three sources recommended by
`docs/TANGO_SOURCE_DISCOVERY.md`'s TOP 3 IMMEDIATE (Section 12/15), then
(v0.83) TangoNOW stabilization + Miltang (`SRC-W-005`) per
`docs/MILTANG_TANGODORI_SOURCE_ANALYSIS.md`. Those reports and
`docs/tango_source_candidates.csv` are the research originals and are not
rewritten here; this is the implementation-side record.

## SRC-W-002 — TangoNOW

| | |
|---|---|
| Exact target | `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300` |
| Detail pattern | `.../documents/events/{document_id}` (implemented as `tangonow_discovery.fetch_document()`, not part of ordinary discovery — see below) |
| robots | `firestore.googleapis.com/robots.txt` is a 404 (treated as no restriction); the app host `ktnow.kr` disallows only `/admin/`. Neither collection target is touched by that disallow. |
| Login | None. Public Firestore read rule. |
| Method | JSON API (Firestore REST `documents.list`), not SSR. |
| Pagination | `nextPageToken`, walked fully inside one `discover()` call. Bounded by `MAX_PAGES` (200), `MAX_RECORDS` (20,000), and repeated-token detection — a token seen twice stops the walk rather than looping. |
| Module | `runtime/tangonow_discovery.py`; dispatched via `config.parser = "tangonow_firestore"` (unchanged and still the live default — see "eventsBundle" below). |
| Body | The Firestore list response already returns full documents — no separate HTML fetch happens for this source. `parse_documents()` synthesizes a plain Korean-labelled body (`장소:`, `입장료 N원`, `DJ:`, a bare 24-hour `HH:MM~HH:MM` time range) straight from the typed fields, so the engine's existing extraction rules read it exactly like any other post. |
| Field names | Confirmed directly against a live 300-document response (v0.82.1): `title, date, time, place, region/regionLarge/regionSmall, dj, org, price, status, archived, createdAt/updatedAt`. `_first()` no longer tries unconfirmed spellings — every name it looks for is one this project's own request actually returned. |
| Time rendering | v0.82.1: a bare 24-hour range, no am/pm marker. An earlier version rendered every range as an explicit "H:MM am/pm to H:MM am/pm", which invented certainty the source never gave — a real record's own `"09:00~26:00"` got flagged as a genuine WRONG_TIME_SQL case (start before noon, evidence EXPLICIT) because of exactly that. Passing the raw value through lets the engine's own honesty rule decide: unambiguous when the start hour is not 1-12, left `ambiguous`/`EVIDENCE_ABSENT` for a person otherwise. |
| Genre | The source is Tango-specific by construction (TangoNOW is a Tango-only registry) — no in-collector genre filter is applied. |
| Known limitations | A public Firebase rule change surfaces as a `DiscoveryError` naming 401/403 explicitly, not a silent empty result. Separately (not specific to this source): the engine's own `persist_raw_post()` does not update an already-stored raw post's body on a later re-collection of the same URL, so a body-affecting parser fix here only reaches events collected fresh afterward, not ones already ingested under the old body — a structural gap in `engine_ingest.py`'s dedup-by-URL design, out of scope to fix generally in this task. |
| OCR fallback | Unchanged, reused as-is. A record with only a poster and thin text still produces a candidate (not dropped) — v0.81.3's image OCR fallback path is what would fill it in later, exactly as for any other source. |

### eventsBundle (v0.83: prepared, not activated)

`ktnow.kr`'s current live frontend does not call Firestore directly — it
calls `https://asia-northeast3-ktangoguide.cloudfunctions.net/eventsBundle
?days=14`, a Cloud Function returning one flat JSON response
(`main`/`archived`/`brands`). Confirmed directly against a live request
before deciding anything:

- **In favour of switching**: one request returns everything the frontend
  needs (345 `main` + 28 `archived` + 83 `brands`, ~560 KB) where the
  existing Firestore path may walk many separate `documents.list` pages to
  reach the same `main` set, most of it already-archived history first (a
  live Firestore sample was ~94% archived). The response is also
  server-cached (`Cache-Control: public, max-age=300, s-maxage=600`).
- **Against switching now**: a live sample showed real schema
  heterogeneity the discovery report's own clean field list did not
  surface — `main` mixes at least three different date-field conventions
  across records (`date` alone on ~97%, `start_date`/`end_date` on a
  multi-day-festival minority, a third, differently-cased
  `startDate`/`endDate` pair on a smaller minority still), `normalizedTime`
  was null on every one of the 345 sampled records, and only ~20% of
  records carry any `link`/`sourceLink` value at all.

**Decision**: `parse_bundle()`/`discover_bundle()` are implemented in
`runtime/tangonow_discovery.py` and tested against a fixture shaped like
the real response, but **not wired into `runtime/collectors.py`'s dispatch
table**. SRC-W-002's registered `config.parser` stays `tangonow_firestore`,
unchanged — this source is already live in production, and an internal,
non-contractual Cloud Function endpoint with this much internal
heterogeneity is not something to switch a stable source onto without a
monitoring period first.

**To activate later**, once that monitoring has happened: add
`WEB_PARSER_TANGONOW_BUNDLE = "tangonow_bundle"` to `collectors.py`,
route it to `tangonow_discovery` in `_web_discovery_module()`, then have an
operator edit SRC-W-002's `config.parser` to `"tangonow_bundle"` and its
`url`/`config.board_urls` to the bundle URL above — no other code change.

## SRC-W-003 — Tango Calendar Korea

| | |
|---|---|
| Exact target | `https://tangocalendar.kr/api/events` |
| Detail pattern | `/api/events/{uuid}` (implemented as `tangocalendar_discovery.fetch_event_detail()`, not part of ordinary discovery) |
| robots | `ALLOW`. |
| Login | None. |
| Method | JSON API, unpaged array as of this release. `parse_events()` validates the response is actually a list and raises `DiscoveryError` naming the schema assumption if it ever becomes a paginated wrapper instead. |
| Pagination | None currently (the API is a single unpaged array); guarded explicitly rather than assumed. |
| Module | `runtime/tangocalendar_discovery.py`; dispatched via `config.parser = "tangocalendar_json"`. |
| Body | Same reasoning as TangoNOW: the list response already carries every field, so body is synthesized directly, UTC timestamps converted to Asia/Seoul before rendering. |
| Occurrence overrides | An event's `occurrenceOverrides` field is treated as exception(s) to *that record's own* occurrence — override values win over the base wherever the override actually supplies one; `isCancelled=true` (on the base or the override) excludes the occurrence entirely. This does not expand an `rrule` into multiple future dates — the API already materializes each dated instance as its own array entry (the report's own "746 base record" count), so nothing here invents an occurrence the API did not already return in some form. |
| Cutoff | Applied first, before occurrence merging or body synthesis — with 96%+ of the raw array already in the past per the discovery report, filtering by date before doing any other per-record work matters. |
| Known limitations | `entranceFee` is preserved as visible text even when non-numeric (e.g. "문의"), rather than dropped or coerced — `FEE_RE` will not read a non-numeric fee as an amount, by design. |
| OCR fallback | Unchanged, reused as-is; not expected to be needed (this source has no posters). |

## SRC-W-004 — DanceInfo (already shipped in v0.82's first merge; hardened this task)

| | |
|---|---|
| Exact target | `https://danceinfo.net/lessons?genre=all&category=all&location=all` (date-less — recomputes "today" server-side on every fetch) plus per-date pages for the rest of the collection window |
| Detail pattern | `/lessons/{numeric_id}` |
| robots | `PARTIAL` — `/lessons` allowed, `/api/` disallowed. Only `/lessons` is ever used; the disallowed `/api/` is never called. |
| Login | None. |
| Method | SSR HTML — the list page embeds a Next.js `__NEXT_DATA__` JSON hydration payload; the detail page is ordinary server-rendered HTML read through `runtime/acquisition.py`'s existing marker-pair extraction (`행사일` … `다가오는 추천`). |
| Pagination | Date-parameterized list pages named individually in `config.board_urls`; no token-based pagination. |
| Module | `runtime/danceinfo_discovery.py`; dispatched via `config.parser = "danceinfo_json"`. |
| Tango-only filtering | `parse_list(..., genre_name="탱고")` — a lesson whose own `genreName` is not exactly `"탱고"` is dropped at discovery; nothing downstream ever sees a non-Tango danceinfo.net listing. Salsa/Bachata/Kizomba/Zouk and mixed-genre listings are excluded the same way — by requiring the site's own per-lesson genre label to equal Tango exactly, not by inferring genre from title text. |
| Schema validation (this task) | `parse_list()` now requires `props`, `props.pageProps` and `pageProps.initialDays` to actually be present, raising `DiscoveryError` if any is missing. Previously a missing key silently fell back to an empty list — indistinguishable from "no Tango today". A genuinely empty day (the key present, zero lessons) still returns `[]` without error. |
| Known limitations | Venue/fee text on this site's detail pages does not match `extract_venue()` (needs a colon-labelled value) or `extract_fee()` (needs `입장료`/event-context) — left as missing rather than risk regressing Daum/Naver/K-TANGO extraction quality. `board_urls` beyond the date-less "today" URL are static dates and need periodic manual refresh. |
| OCR fallback | Unchanged, reused as-is; never forced. |

## SRC-W-005 — Miltang (v0.83, `docs/MILTANG_TANGODORI_SOURCE_ANALYSIS.md`)

| | |
|---|---|
| Role | **SECONDARY/DIRECTORY**, never PRIMARY — several sampled Miltang records republish KTNow's own public data (image path `storage/imports/ktnow_...`, matching title/date/venue/source link), confirmed in the analysis doc. |
| Exact targets | `https://miltang.com/milongas` (day-scoped) and `https://miltang.com/notices` (unpaged) |
| Detail pattern | `/milongas/{id}`, `/notices/{id}` |
| robots | `PARTIAL` — blocks only `/admin`, `/more`, `/requests`, `/nickname`, `/auth/`; both collection targets (and their `week`/`date`/`region_id` params) are explicitly allowed by the site's own robots.txt comment. |
| Terms | `/terms` and `/privacy` both 404 — no public license found either way; kept low-frequency (360-minute interval) and truthful `User-Agent` as the safety margin instead. |
| Login | None. |
| Method | SSR HTML both stages. List pages carry no JSON-LD (confirmed live); detail pages carry one `Schema.org Event` block plus a plain `<dl>` of DATE/TIME/PLACE/[ORG]/LINK rows. |
| List scoping | `/milongas` needs **both** `week=` (that day's Monday) **and** `date=` together — confirmed live that `date=` alone silently falls back to the current week's Monday instead of erroring. `discover()` re-reads each fetched page's own displayed date and raises `DiscoveryError` on a mismatch, rather than trusting the URL. `/notices` is unpaged and not date-scoped at all. |
| Module | `runtime/miltang_discovery.py`; dispatched via `config.parser = "miltang_ssr"`. `config.days_ahead = 13` (14-day window) widens `/milongas` only — the same mechanism `danceinfo_json` already uses, extended in `collectors.py`'s dispatch gate. |
| Body | JSON-LD parsed first (name/startDate/[endDate]/location/[organizer]); TIME, LINK and the recurrence badge always come from the `<dl>`/badge markup — confirmed live that JSON-LD never carries TIME. Rendered in the same Korean-labelled convention every other source here uses. |
| Bilingual venue names | Miltang names a venue as one space-joined `"Brand 한글이름"` string (`"PISTA 피스타"`, confirmed live) — migration 022's own aliases always register the two spellings *separately*. `_split_bilingual_venue_name()` renders it as `"Brand (한글이름)"` instead, so the engine's existing `extract_venue()` (which already splits a parenthesised group into its own alias candidate) resolves either spelling through the existing table — found necessary only after a real dedup test (reading the venue through the actual `extract_venue()`, not a hand-typed expectation) failed to resolve the un-split form at all. |
| Original links | Every LINK-row URL is preserved in the body (`원문 링크: ...`), but `source_url` is always this module's own Miltang detail URL — never one of those links, even when the only one present is a bare Facebook/Instagram profile or Daum Cafe root (`_is_profile_or_root_link()` classifies for documentation/testing; nothing here promotes any of them regardless). |
| `published_at` | Always `None` — neither `created_at` nor `updated_at` is present anywhere on a detail page (confirmed live); never guessed from the sitemap's own `lastmod` (page freshness, not a record timestamp). |
| Known limitations | No cancellation flag was observed on any sampled record (`eventStatus` was always `EventScheduled`) — a genuinely cancelled Miltang milonga is not currently detected as such. `/milongas`'s day-scoping means a recurring ("매주") series only ever exposes its own next/current occurrence, not every future date it will recur on — the list stage already dedups a repeated detail id across days for this reason. |
| Dedup | No new dedup module (Section 5) — the *existing* `venue_aliases` + `duplicates.classify()` pipeline collapses a KTNow/Miltang pair once both resolve to the same `venue_id`; `duplicates.completeness()`'s existing tie-break (not a new authority-ordering rule) decides which survives as canonical when they merge. |
| Enabled by default | **No.** Registered disabled (migration `023_miltang_source.sql`) — an operator Tests it, then explicitly enables it. |

## Tangodori — not implemented

Per `docs/MILTANG_TANGODORI_SOURCE_ANALYSIS.md` Section 4/7/8: Tangodori's
own Terms (updated 2026-06-27) explicitly prohibit "scrape or abuse the
APIs", regardless of what robots.txt or the technical accessibility of its
Nuxt `_payload.json` route might suggest. No collector, no Source row, no
payload-shape reverse-engineering was attempted. **Do not implement without
the operator's written permission or an official feed.**

## Duplicate resolution across all three (and existing sources)

No new dedup module was added. Two pre-existing pieces already do everything
Section 5 asked for:

- `runtime/normalization.py`'s `resolve_venue()` already resolves every new
  candidate's raw venue text against `venue_aliases`, for every source,
  automatically, at normalization time.
- `runtime/duplicates.py`'s `classify()`/`scan()` already auto-merges two
  events sharing the same date, start time and `venue_id`
  (`RULE_SAME_DATE_VENUE_TIME`), and flags a partial match for a human
  otherwise. Nothing is deleted — a duplicate keeps its own row and points at
  the canonical event (`canonical_event_id`); `duplicates.sources_of()`
  still returns every source behind a merged event.

The only thing genuinely missing for these eight well-known venues was the
alias rows themselves. Migration `022_tango_venue_aliases.sql` seeds them —
PISTA/피스타, EN PAZ/엔빠스/탱고 엔빠스 스튜디오, Tango Andante/안단테, Tango
O Nada/오나다, OCHO/오초, La Ventana/라벤따나, Amigo/아미고/아미고스튜디오,
Cafe de Tango/데땅고 — into the *existing* `venues`/`venue_aliases` tables.

Source precedence (`OFFICIAL_VENUE/FESTIVAL/ORGANIZER` > `TangoNOW primary
registry` > `Tango Calendar Korea` > `DanceInfo` > existing secondary
directories/mirrors, per the discovery report's own Section 10 table) is not
separately encoded: `duplicates.completeness()`'s existing tie-break
(resolved venue, populated time/fee, engine/review state) already decides
which of two auto-merged rows survives as canonical, and a source's own
`authority_level` (`AGGREGATOR`/`SECONDARY` for the three in migration 021,
`SECONDARY` for Miltang in migration 023) is visible to an operator on the
Sources page for any case that needs a human's judgement instead.

**Real-world finding while building this**: this project's own board already
had independently-registered venues for `아미고스튜디오`/`아미고` (venue_id
180), `엔빠스` (184) and `데땅고` (185) from real prior usage, created before
this migration existed. An early version of migration 022 always inserted
its own canonical English name regardless, which would have created a
second, competing venue for the same real place. The final migration looks
up whether any spelling in a group already resolves to a real venue first,
and only attaches the group's remaining spellings to that venue — found and
fixed by running the dedup integration tests directly against the real
board data (rolled back, never committed) before finalizing the migration.

**Real-world finding while building Miltang (v0.83)**: the same kind of
"tested against real data, not a hand-typed expectation" check caught a
second, different problem — Miltang's own venue-name convention
(`"PISTA 피스타"`, one space-joined string) does not normalize to either of
migration 022's separately-registered spellings (`"PISTA"`, `"피스타"`), so
every Miltang candidate resolved as `VENUE_UNRESOLVED` until
`_split_bilingual_venue_name()` was added — see the SRC-W-005 table above.
