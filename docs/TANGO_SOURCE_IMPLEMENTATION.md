# Tango Source Expansion — Implementation Notes (v0.82, TOP 3 IMMEDIATE)

This records what was actually built for the three sources recommended by
`docs/TANGO_SOURCE_DISCOVERY.md`'s TOP 3 IMMEDIATE (Section 12/15). That
report and `docs/tango_source_candidates.csv` are the research originals and
are not rewritten here; this is the implementation-side record referenced by
this task's Section 9.

## SRC-W-002 — TangoNOW

| | |
|---|---|
| Exact target | `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300` |
| Detail pattern | `.../documents/events/{document_id}` (implemented as `tangonow_discovery.fetch_document()`, not part of ordinary discovery — see below) |
| robots | `firestore.googleapis.com/robots.txt` is a 404 (treated as no restriction); the app host `ktnow.kr` disallows only `/admin/`. Neither collection target is touched by that disallow. |
| Login | None. Public Firestore read rule. |
| Method | JSON API (Firestore REST `documents.list`), not SSR. |
| Pagination | `nextPageToken`, walked fully inside one `discover()` call. Bounded by `MAX_PAGES` (200), `MAX_RECORDS` (20,000), and repeated-token detection — a token seen twice stops the walk rather than looping. |
| Module | `runtime/tangonow_discovery.py`; dispatched via `config.parser = "tangonow_firestore"`. |
| Body | The Firestore list response already returns full documents — no separate HTML fetch happens for this source. `parse_documents()` synthesizes a plain Korean-labelled body (`장소:`, `입장료 N원`, `DJ:`, explicit `H:MM am/pm to H:MM am/pm` time) straight from the typed fields, so the engine's existing `extract_single()` reads it exactly like any other post. |
| Genre | The source is Tango-specific by construction (TangoNOW is a Tango-only registry) — no in-collector genre filter is applied. |
| Known limitations | Field names could not be confirmed against a live response during this task (no live collection was performed); `_first()` tries the likely spellings the discovery report described ("가능한 범위에서 매핑") rather than one confirmed schema. A public Firebase rule change would surface as a `DiscoveryError` naming 401/403 explicitly, not a silent empty result. |
| OCR fallback | Unchanged, reused as-is. A record with only a poster and thin text still produces a candidate (not dropped) — v0.81.3's image OCR fallback path is what would fill it in later, exactly as for any other source. |

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
`authority_level` (`AGGREGATOR`/`SECONDARY` for these three, matching the
values registered in migration 021) is visible to an operator on the Sources
page for any case that needs a human's judgement instead.

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
