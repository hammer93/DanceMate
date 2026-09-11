# DanceMate Release Notes

## v0.88.1 Compact Venue and Source Directory Rows

Status: PASS, 2026-09-11.

Version split:

- Product Runtime: 0.88.1
- Information Engine: 0.85 (unchanged)

### Public Directory UI

- **장소 and 정보원 entries are compact single-line rows**: name · facts
  (region · address for a venue; platform · tier · region for a source) ·
  genre tags · link (지도 / 바로가기), one `<li class="dir-row">` per entry with
  no block element inside. The data behind them is unchanged - the same
  `directory.public_venues()` / `public_sources()` rows and fields as v0.88.0,
  so nothing new reaches the page (no notes, config, keys or collector
  settings).
- **Long content never breaks the layout.** The list clips to its own box, so
  the page never scrolls sideways. When a line is short of room the facts give
  way first (they only get the space left over), then the genre list (capped
  at 35%, shrinking three times faster than the name); the name keeps at least
  4.5em and may use up to 60% of the line; the link never shrinks. Anything cut
  ends in an ellipsis.
- **The full value stays reachable**: the name, the facts and the genre list
  each carry a `title` tooltip, and the text is whole in the DOM, so screen
  readers read all of it. A venue's map link searches its full address.
- Measured in headless Chrome with the 49 production venues and 16 sources at
  320 / 360 / 414 / 768 / 1280 px: no horizontal page overflow at any width,
  every row one line (42-43 px), every link inside its row, at least 72 px of
  every name visible (no venue name cut from 360 px up; no source name cut from
  414 px up).
- Unchanged: 동호회 and 게시판 keep their v0.88.0 cards; the shared genre filter
  (URL state, multi-select, disabled-genre normalization, tab changes) and
  the events view are untouched.

### Data

- No schema change; migration level stays 035.
- Existing Venue master data preserved. The Salsa/Swing venue import done
  earlier today (13 venues, 36 -> 49) is runtime master data written through
  the Admin CSV import contract with its audit trail - not a migration, and not
  part of this release.

### Verification

- Focused (`test_v0880_public_directory`, communities/notices, genre filter,
  public pages, v0.86.8 selector): runtime container, fresh PostgreSQL
  **266 passed, 0 failed, 2 skipped** (pre-existing KR-BUSAN seed condition);
  host 139 passed, 0 failed.
- Full suite, runtime container: development database **2162 passed, 2
  failed, 19 skipped** - the known pair (`test_existing_top3_sources_are_preserved`,
  `test_k_tango_is_preserved_untouched`); freshly created database 2161 passed,
  3 failed, 19 skipped - the same pair plus the known fresh-database
  `test_source_row_enable_disable_action_still_works` (SRC-D-003's seeded
  authority_level), identical to v0.88.0. Host 1565 passed, 0 failed.
  Engine: 809 passed, 0 failed.
- Migrations 001-035 on a freshly created database, no checksum drift.
- Local runtime smoke (read-only, DB fingerprints identical before/after): 19/19.

### Private Alpha Observation

Continues unchanged.

## v0.88.0 Public Directory Tabs, Communities, Sources and Notice Board

Status: PASS, 2026-09-11.

Version split:

- Product Runtime: 0.88.0
- Information Engine: 0.85 (unchanged)

### Public Navigation

- The first screen carries five tabs: **행사** (the events view exactly as it
  was, still the default - no `?tab=` at all) and the directory: **장소 /
  동호회 / 정보원 / 게시판**. A small tab row above everything else; on a narrow
  screen it scrolls sideways instead of wrapping or being cut off.
- **One shared genre filter.** Every tab reads the same v0.86.8 selector
  through the same functions (`_selected_genres`, `_genre_constraint`,
  `_genre_query`): multi-select, disabled or unknown genres in a link
  normalised away, one enabled genre means no selector, unticking everything
  is an answer. Each tab link carries the selection and nothing else.
- **URL state.** `?tab=venues&genres=TANGO` (or the canonical
  `genres=TANGO,SALSA&genres_set=1`) restores the same tab and the same
  genres on a reload or a shared link; a genre change submitted on a tab stays
  on that tab. An unknown `tab` value is the events view.
- The event search, the date tabs, the weekly calendar and the region filter
  are untouched.

### Venues

- Public venue list from the existing `venues` table and the v0.86.7
  `venue_genres` relation (genre FK, never a name match): name, region,
  address with a Naver Map link, genre tags. Enabled venues only; notes and
  coordinates are not selected.

### Communities

- New canonical master data `communities`, many-to-many to venues
  (`community_venues`) and genres (`community_genres`) by id - a renamed
  venue keeps every link.
- Admin **Communities** screen: list, add, edit (its own edit page, returning
  to the exact list view), enable/disable, and a two-step safe delete - only a
  disabled community can be deleted, and a delete removes the community and
  its own links, never a venue or a genre. Genre and venue multi-select;
  disabled genres/venues stay visible to the operator, marked.
- Public list: name, region, short description, venues, genres, homepage
  link. Disabled communities and the operator's notes never appear. Nothing
  is seeded - no real community names were given, so none are invented.

### Sources

- The existing `sources` table, reused as a public directory: name, platform,
  tier (공식 / 홍보게시판 / 일정모음), genre, region, and a link to the
  source's human page through the event pages' own resolver.
- **Never exposed:** config, queries, notes, status/detail, source keys,
  authority/access state. The query does not select them. A URL with a
  credential-shaped parameter (key, token, secret, serviceKey...), user:password,
  or an API host/`.json` endpoint is not linked. Sources have no public
  description column; `notes` is operator-only and stays hidden.
- Enabled sources only, most direct tier first.

### Board

- `boards` + `board_posts` + `board_post_genres`. One board is seeded:
  **NOTICE (공지사항)**. The shape is general - board type and write policy on
  the board, author kind and a reserved `author_user_id` on the post - so more
  boards and a member login are additions later. Neither is built.
- Admin **Notices** screen: list, add, edit, delete, status (게시 / 임시저장 /
  숨김), pin, genre scope. A second identical submit within two minutes is
  stored once.
- Public: pinned first, then newest; title, date (Seoul), a one-line summary,
  genre tags; a detail page at `/notices/{id}`. Only published posts; a draft,
  hidden post or garbage id is a 404. The body is plain text - escaped, line
  breaks kept, bare http(s) addresses linked - never rendered as HTML.

### Genre policy (fixed by tests)

- Every genre ticked narrows nothing; rows with no genre are listed too.
- A narrowed selection lists rows having one of the chosen genres. A venue,
  community or source with **no genre** is left out (its genre is unknown -
  "장르 미확인" - and listing it under Tango would be a guess); a note under the
  list says so.
- Nothing ticked lists nothing.
- **A notice with no genre is a global notice** and is listed under every
  selection, the empty one included.

### Terminology

- DanceMate's standard Korean label for **PRACTICA** is now **프락티카**
  (original term *Práctica*). The canonical code `PRACTICA` is unchanged.
  Changed in the label dictionaries, the Settings note ("쁘롱가는 밀롱가이자
  프락티카입니다"), reason lines ("제목에서 발견: "쁘락" (프락티카)") and code
  comments. A test keeps the old spelling out of `runtime/` entirely.
- Source terms are untouched: a Settings term or a title using a field
  spelling is still shown as written; only the canonical label underneath
  changed. Historical release-note entries are left as written.

### Admin security

Every new POST: return address limited to the screen's own list
(absolute, protocol-relative, backslash and other paths refused), the
console's submit guard, input and FK validation with a sentence instead of a
500 (a failed save shows the form again with what was typed), malformed ids a
404, everything escaped. Changes are written to `master_data_actions`
(`COMMUNITY` / `BOARD_POST`, new `CREATE` action). Genre and region deletes
now count communities and notices and refuse while they are used; a deleted
venue only drops out of its communities.

### Migration

`035_public_directory.sql`: communities, community_genres, community_venues,
boards (+ NOTICE seed), board_posts, board_post_genres; audit CHECK
constraints extended. Forward-only; no existing migration changed.

### Verification

- New: `test_v0880_public_directory.py` (tabs, URL state, genre contract,
  empty states, cards, notice rendering, link rules, the policy against real
  PostgreSQL rows, every tab against the migrated schema) and
  `test_v0880_communities_notices.py` (schema, CRUD rules, audit, safe
  delete, usage counts, the Admin routes end to end incl. open redirect,
  duplicate submit, malformed ids and XSS). The v0.86.7/v0.86.9/v0.87.0 tests
  that pinned the old label were rewritten to 프락티카; `test_migrations.py`
  lists 035.
- Migrations 001-035 on a freshly created database, no checksum drift; 034 ->
  035 on an existing one.
- Focused, runtime container, fresh PostgreSQL: **510 passed, 0 failed, 3
  skipped** (pre-existing KR-BUSAN seed condition).
- Full suite, runtime container: **2155 passed, 2 failed, 19 skipped** on the
  development database - the known pair (`test_existing_top3_sources_are_preserved`,
  `test_k_tango_is_preserved_untouched`), unchanged since v0.86.8. On a
  freshly created database: 2154 passed, 3 failed, 19 skipped - the same pair
  plus `test_source_row_enable_disable_action_still_works`, which picks the
  first source and on a fresh database meets SRC-D-003's seeded
  `authority_level = PRIMARY_COMMUNITY` (rejected by `sources.validate`); the
  v0.87.0 code fails it identically against the same database.
- Host: 1558 passed, 0 failed, 612 skipped. Engine: 809 passed.
- Local runtime smoke over HTTP (real UTF-8 forms through the Admin routes,
  every row created and deleted again): 33/33.

### Private Alpha Observation

Continues unchanged.

## v0.87.0 Event Kind Certainty + Venue Repeating Events

Status: PASS, 2026-09-11.

Version split:

- Product Runtime: 0.87.0
- Information Engine: 0.85 (unchanged - no classifier change this release)

### The "?" now means one thing

Until now the "?" beside an event's kind was v0.86.4's *unverified post*
signal (engine status POSSIBLE/EXPECTED/CONFLICT/UNKNOWN, switched per status
in Settings). Sitting right after the kind, it read as doubt about the kind -
"밀롱가?" on a plain milonga. By the user's decision it is retired: the "?"
now appears only when the event's **kind** could not be settled from its
title. VERIFIED/CONFLICT keep their own badges. The Settings checklist and its
save route are removed; the old table and its row are left in the database
untouched.

### Kind: the title's own word, the canonical type underneath

`event_terms.classify_kind()` settles an event's kind from the v0.86.9
terminology, in a fixed order:

1. **A matched Settings term** - shown as the word the title used ("쁘락",
   "Pronga", "밀롱가"), with its canonical formats kept underneath
   (PRACTICA; MILONGA + PRACTICA). Settled when one matched term covers all
   the evidence - "금요일 밀롱가" is 밀롱가, "쁘롱가" is MILONGA + PRACTICA, and
   "쁘롱가 & 밀롱가" is still 쁘롱가. **Unsettled** when the matched words point
   at different formats with no registered mixed term covering them
   ("밀롱가 & 쁘락"), or contradict the engine's own type (a milonga term on an
   event the engine filed as SOCIAL; the engine's MILONGA covers practicas,
   since it files every tango social that way).
2. The formats normalization stored, when no term matches now.
3. The engine's own type label - no word to go on, but a real type, no "?".
4. Nothing usable (e.g. CLASS/OTHER, or no type): the fallback label, with "?".

No term is written into the decision - every word comes from Settings.
**쁘락 -> PRACTICA** is added as a seed (migration 034), the one new term this
release defines; where it overlaps the longer 쁘락띠까, the longer term wins.

### The "?" explains itself

The "?" is a real `<button>` (`aria-label="행사 유형 판정 이유 보기"`) opening a
native HTML popover - no script, no framework; keyboard, Esc and a 닫기 button
all close it. Its lines are translated from the reason codes the decision
actually used (matched terms and their formats, disagreeing formats, no
registered mixed term, the engine's conflicting or unusable type) - never
composed on the page. A button may not sit inside a link, so only a card
whose kind carries a "?" switches to a stretched-link layout (the whole card
still opens the event); every other card's markup is unchanged. The event
detail page's 종류 row and the Admin Item Audit preview use the same renderer.

### Venue: repeating events shown once

`/admin/venues`' linked-events panel groups each venue's events by the
project's own title key (`normalization.name_key()` - NFKC, dates/weekday
words and decoration removed, never fuzzy: "Friday Milonga" and "Friday
Special Milonga" stay apart) and the weekday of the real event_date. Each
group shows its latest occurrence (date, start time, event_id) and a **회차**
count. The header keeps the raw total and names the grouping - "연결 행사 47건
· 반복 행사 6개" - and [연결 행사 N] on the row stays the raw linked count.
Grouping runs over every linked event before paging, so one weekly series can
never push another group off a page.

### Migration

`034_event_term_practica_alias.sql`: seeds 쁘락 -> PRACTICA for TANGO.
Idempotent; an operator's own 쁘락 row is left as it is. No schema change.

### Tests

New: `test_v0870_event_kind_and_venue_groups.py` (kind decisions and reasons,
popover and card markup, grouping, paging after grouping, the panel). The
v0.86.4-era tests that pinned the retired status "?" (`test_v0864`,
`test_v0866`, `test_v0867`, `test_v085`) were rewritten to the new contract,
not dropped; the v0.86.9 venue-panel tests now stub the full fetch the
grouping needs; `test_migrations.py` lists 034.

- Focused, runtime container, real PostgreSQL (new file plus v0864, v0866,
  v0867, v085, v0868, v0869 x2, genre_filter, master_edit, public_pages,
  migrations): **516 passed, 0 failed, 5 skipped** (pre-existing KR-BUSAN and
  no-collected-items data conditions).
- Full suite, runtime container: **2034 passed, 2 failed, 19 skipped** - the
  two failures are the known fresh-database pair
  (`test_existing_top3_sources_are_preserved`,
  `test_k_tango_is_preserved_untouched`, asserting board-only `SRC-W-001`),
  unchanged since v0.86.8. Host: 1496 passed, 0 failed, 553 skipped.
- Migrations: 001-034 on a freshly created database with no checksum drift;
  033 -> 034 on an existing one.
- Local runtime smoke over HTTP, events built through the real
  `normalize_candidate`: 30/30 (the two popover-quote checks confirmed in their HTML-escaped
  form, &quot;...&quot;, as a browser receives them) - only the "밀롱가 & 쁘락" card carries a "?", as a
  labelled button outside any link with its popover reasons; 목요 쁘락 shows
  쁘락, Friday Milonga shows Milonga, a title with no term shows the engine's
  label; the detail page; four weekly Friday Milongas as one row with 4회
  under "연결 행사 7건 · 반복 행사 4개"; the retired checklist and route gone.

### Private Alpha Observation

Continues unchanged.

## v0.86.9 Venue Linked Events + Event Terminology Settings

Status: PASS, 2026-09-11.

Version split:

- Product Runtime: 0.86.9
- Information Engine: 0.85 (the classifier gains one optional input - Settings
  words - and is otherwise unchanged; its own suite: 809 passed)

### Venue Linked Events

A venue row on `/admin/venues` now offers **[연결 행사 N]** beside
**[편집]**. Opening it lists that venue's events in a full-width row
directly under the venue - the same "one row opened in place" shape as the
v0.86.8 inline editor, on the same list view: page number, filters and any
open row editor all stay as they were, and the link lands on the panel.

- **Relation:** `events.venue_id`, the real foreign key the "Events using"
  count has always used - never a venue name. A renamed venue keeps every
  event; two venues that share a name never share events
  (`venue_resolution.venue_events()` / `count_venue_events()`).
- **Count:** the link shows the same number the panel totals.
- **Fields:** date and weekday, start (and end) time, title, genre, kind -
  "밀롱가 + 쁘렉" for a two-format night, else the event_type label - and the
  engine/review/listing state (hidden and merged events are listed and
  marked, since they still point at the venue). Links: the admin review page
  always, the public event page only when the public page would serve it
  (the same `_VISIBLE` predicate `events_api.get_event()` uses). Organizer is
  not shown: the schema has no event-to-organizer link, and none was
  invented for display.
- **Order:** upcoming soonest-first, then past most-recent-first; past rows
  are muted.
- **Paging:** 20 per page, its own `venue_events_page` parameter; only the
  one open venue's events are ever queried.
- **Empty state:** "연결된 행사가 없습니다."

### Event Terminology Settings

`/admin/settings` gets a **행사 용어 (Event Terminology)** section: the words
a scene uses for its events, mapped to the Event Formats DanceMate already
classifies by. Add, edit (the whole row, in place), enable/disable and
delete; each term has a genre scope and one or more canonical formats.

- **Canonical types reuse the existing vocabulary** - the Event Format set in
  `events_api` (MILONGA / PRACTICA / GENERAL / SOCIAL). No new enum.
- **Genre scope** is a foreign key to the existing genres master. The same
  word may mean different things in two genres.
- **Seeds** (TANGO), only what is settled: Milonga / 밀롱가 -> MILONGA;
  Practica / 쁘락띠까 -> PRACTICA; Pronga / 쁘롱가 -> MILONGA + PRACTICA.
  쁘렉틸롱가, organizer names and regional aliases are left for an operator.
- **Matching** (`runtime.event_terms`): NFKC, whitespace collapsed, lower
  case, never fuzzy. A Latin term must be a whole word ("practica" is not in
  "practical"); a Korean term may carry its particles ("쁘롱가에서").
  Overlapping matches keep the longest; separate matches all count. An
  unknown word maps to nothing - it is never forced into a format.
- **Validation:** empty term, a normalized duplicate in the same genre, no
  format, an unknown format or genre are each refused with a reason; a
  failed row save keeps the row open.
- **Classification:** the runtime hands the engine the enabled words that
  stand for a milonga or a practica (per source genre), and the classifier
  recognises them *in addition to* its built-in words - so "Friday Pronga" or
  "Practica Night" is now an event where before it was OTHER, while turning
  a Settings word off can never make a post the engine already recognised
  stop being an event. The engine's own `event_type` stays its existing
  single classification.
- **Storage:** normalization resolves each event's own title against the
  Settings and stores the canonical set in the new `events.event_formats`
  array - a Pronga is `{MILONGA, PRACTICA}`, never a single type and never
  a joined string. Existing events are not rewritten by the migration; the
  existing scheduled event-normalization fills the column in as it next
  rebuilds each event, from whatever the Settings say then.

### Deployment Maintenance

- **Scheduler duplicate guard:** v0.86.8's deploy found it counting
  schedulers by grepping `docker ps --format '{{.Command}}'`, which Docker
  truncates - it counted 0 with one running, so it could never fire. It now
  merges two signals that never read that column: the compose service label
  and the full `--no-trunc` command, de-duplicated by container id. It logs
  the count it found; 2+ stops the deploy.
- **Backup retention ownership:** two backup directories made by a root
  session could not be pruned by retention, which runs as the repository's
  owner. `scripts/backup.sh` run as root now hands itself to the owner
  instead of writing as root, and `scripts/fix-ownership.sh --backups [--yes]`
  reclaims exactly the foreign-owned `dancemate-backup-*` directories -
  deleting nothing, so retention alone still decides what is old enough to go.

### Migration

`033_event_terminology.sql`: `event_terms` (genre-scoped, unique per genre on
the normalized term), `event_term_formats` (the many-to-many term -> format
mapping), the six seeds, and `events.event_formats TEXT[]` added NULL.
Forward-only; no existing migration touched; no existing row rewritten.

### Compatibility

Public pages, the genre selector, v0.86.8's inline row editing (Genre, Region,
Organizer, Venue), return_to, row anchors, the submit guard and the Sources
editor are unchanged. Existing POST routes are unchanged; the Settings term
routes are new. `events.event_type` and every read of it are unchanged.

### Tests

New: `test_v0869_venue_events.py`, `test_v0869_event_terminology.py`,
`test_v0869_deploy_maintenance.py`; `test_migrations.py` lists 033.

- Focused, runtime container, real PostgreSQL (the three new files plus
  v0868, genre_filter, master_edit, migrations): **276 passed, 0 failed,
  3 skipped** (the pre-existing KR-BUSAN fixture).
- Full suite, runtime container: **1994 passed, 2 failed,
  19 skipped** - the two failures are the known fresh-database pair
  (`test_existing_top3_sources_are_preserved`,
  `test_k_tango_is_preserved_untouched`, asserting board-only `SRC-W-001`),
  unchanged since v0.86.8. Host: 1459 passed, 0 failed, 550 skipped.
- Migrations: 001-033 applied to a freshly created database with no
  checksum drift; 032 -> 033 applied on an existing one.
- Local runtime smoke over HTTP: 30/30 - venue panel order and kinds from
  events built through the real `normalize_candidate` (Pronga stored as
  MILONGA + PRACTICA), empty state, inline edit alongside the panel, all six
  seeded mappings, and Settings create / refused edit / duplicate / edit /
  delete.

### Private Alpha Observation

Continues unchanged.

## v0.86.8 Public Genre Selector + Admin Inline Row Editing

Status: PASS, 2026-09-11.

Version split:

- Product Runtime: 0.86.8
- Information Engine: 0.85 (unchanged - no classifier change, no schema
  change; one data-only migration, 032)

### Public Genre Selector

The first screen only asks questions it can answer. The style picker is
built from the genre master's own `enabled` flag and nothing else:

**Disabled genre filtering.** `_genre_options()` reads every genre row
and keeps the ones `_is_enabled()` says are live - a disabled genre
leaves the list entirely rather than rendering as a dead, greyed-out
chip. Nothing on the reader's side asks "is this the salsa one?"; flip
the flags in the master and the answer flips with them.

**Baseline forced-fill removed.** The real cause of Salsa and Swing
still showing after an admin disabled them: `_genre_options()` used to
top the list back up from `BASELINE_GENRES` for any of the three that
were missing, which is exactly what "disabled" makes them.
`BASELINE_GENRES` is now what it always claimed to be - a floor for an
*unreachable* master (a database hiccup must not silently remove the
filter), plus the chip ordering. A master that answers "these are
disabled" is not a hiccup and is obeyed.

**Selector shown only for 2+ enabled genres.** `_shows_selector()` is
`len(options) > 1`. A control whose only option is already the answer
is furniture occupying the whole width of the first screen's most
valuable row, so with one enabled genre `_genre_filter()` renders
nothing at all (and its auto-submit script is not shipped either).

**Single enabled genre applied automatically.** With no selector on
screen the enabled genre simply *is* the current genre - the event
query, the region chips, the week calendar and every link on the page
carry on unchanged.

**Zero enabled genres handled gracefully.** No selector, no constraint,
no crash: the page lists what there is.

**URL genre normalization.** What a link asks for is checked against
what the master currently enables, so a shared or bookmarked
`?genres=SALSA` cannot strand a reader on a filtered-to-nothing page
they have no control to undo. With no selector the enabled set is
applied regardless of the query string; with the selector up, unknown
codes are dropped and an ask that survives none of them falls back to
everything. Unticking every box by hand stays what it always was - an
answer, not a mistake to be corrected.

**Compact responsive width.** `.filters form.genres` is `inline-flex` +
`width:fit-content` with `min-width:min(100%, 12rem)` and
`max-width:100%`, so the control is as wide as its chips instead of as
wide as the screen - a floor and a ceiling rather than a fixed narrow
width that would clip a long genre name, and the chips still wrap
inside the box on a phone. Chip spacing, border radius and type are
untouched.

### Admin Master Data

**Inline row editing** on Genres, Regions, Organizers and Venues.
Clicking 편집 turns *that row* into inputs in place - every editable
column at once, the row's own `<form>` sitting outside the table and
joined to the cells by the HTML5 `form="..."` attribute (a form cannot
legally span `<td>`s, and this is also what lets the row's toggle,
delete and the venue's alias/genre sub-editors keep working beside it
without ever being nested inside it). Which row is open is a query
parameter (`?edit=GENRE:5`), not client-side state, so it survives the
redirect a POST has to end with. Editable fields with no column of
their own (Region's District, Organizer's and Venue's Notes) ride in
the neighbouring cell under their own small label rather than being
the one field the row editor leaves behind. State is a `<select>`, not
a checkbox: an unticked checkbox is not submitted at all, which would
read as "unchanged" and silently ignore an operator who meant to
disable the row.

**Page/search/filter/sort preservation.** `return_to` carries the list
URL the operator is actually looking at into the save, and
`_back_to_view()` hands it straight back - so finishing an edit never
resets the list to its first page, drops a genre/region filter or
loses a page number. The one-shot flash parameters are stripped on the
way in, so messages do not stack across saves.

**Row anchor restoration.** The redirect ends in `#row-GENRE-5`, so the
browser lands back on the row that was edited rather than at the top of
a long table.

**Safe return_to handling.** Only a path on this console is ever
followed: anything absolute, protocol-relative, backslashed or outside
`/admin` falls back to the entity's own list page.

**Duplicate submit guard.** One console-wide script drops a second
submit of a form already on its way and marks its buttons busy,
including the buttons attached by `form="..."` from outside. Progressive
enhancement only - with no JavaScript every form still submits exactly
as it always did.

**Failed saves keep the row open.** A rejected edit comes back with
`?edit=` intact and the error above the row, so the operator corrects it
where they are instead of the row closing as if the edit had gone
through.

### Admin Venues (final fix before push)

**Genre filter on one line.** The v0.86.7 `/admin/venues` filter bar was
written with the public stylesheet's class names (`.filters`, `.key`,
`label.chip`, `.apply`), none of which exist in the admin stylesheet - so
admin's own `label{display:block}` put every genre on its own line, and
`select{width:100%}` gave the region picker the full page width.
Admin-side flex rules for exactly those classes put `춤 종류 [Salsa]
[Swing] [Tango] [적용] [초기화]` on one line on a desktop, wrapping on a
narrow window or a longer genre list. CSS only: the markup, the
`?region=`/`?genres=` contract, Apply/Reset and the table are unchanged,
and the chips are still whatever the genre master returns.

**Synthetic seed Notes removed.** Eight studios created by migration 022
(the v0.82 cross-source alias seed - PISTA, EN PAZ Tango Studio, Tango
Andante, Tango O Nada, OCHO, La Ventana, Amigo Studio, Cafe de Tango)
opened in the editor with `v0.82 seed: known cross-source venue alias
group` in Notes - a note about the migration, not about the venue. 022
itself is left untouched: `runtime/migrate.py` checksums applied
migrations and reports drift, and migrations here are forward-only (as
031 was). New data-only migration 032 sets `notes = NULL` where the value
is exactly that string - whole-value equality, no pattern, never the
column - so an operator's own note on the same venues is left alone, and
a fresh database ends the chain with those notes empty. Verified on the
local stack: 8 rows cleared, a real note written afterwards survives a
re-run, and a second run matches nothing.

**Notes stays an editable field.** Empty is not absent: the venue row
editor still renders the Notes label and control with no value in it.
It is now a two-line `textarea` in the same cell - same width, so the
table does not grow - where a one-line input clipped the text.

### Compatibility

- Sources keeps its existing expanded editor (ten editable fields
  against seven dense columns - a row-wide swap would make that screen
  worse, not better); it gains `return_to` only, so its genre filter and
  page number now survive a save too.
- Existing POST endpoints preserved: `/admin/master-data/{type}/{id}/
  edit` and `/enabled` are the same routes with the same fields.
  `return_to` is optional, so a form that never sends one still lands on
  the entity's own list page exactly as before.
- No DB schema change: `genres.enabled` already existed and is only
  read. The one new migration, 032, is data-only (see Admin Venues).

### A defect this release's own container run caught

The three new route tests that must see their own writes were skipping
silently with `password authentication failed`: the fixture read only
`TEST_POSTGRES_*`, so the `env` fixture's deterministic fake password
stayed in place, and holding only the connection (not the context
manager `db.connect()` returns) let the generator be collected and the
connection closed out from under teardown. Both fixed; the three now
run for real, and the throwaway genre they create - disabled from the
moment it exists, so it can never reach a reader's first screen - is
verified deleted afterwards.

### Tests

61 new tests in `tests/test_v0868_genre_selector_inline_edit.py`
(selector width, disabled-genre exclusion, flag-not-name filtering,
one/zero enabled genre, URL normalization, whole-row edit mode, other
rows untouched, list-context preservation, cancel, failed save, submit
guard, return_to safety, no nested forms, the venue filter bar's
one-line layout, Notes provenance/cleanup/rendering) plus
`tests/test_genre_filter.py`'s disabled-genre contract narrowed to
"exactly the enabled ones, no baseline top-up", and
`tests/test_migrations.py` listing 032 in its expected discovery order.

Focused run in the runtime container against a real PostgreSQL
(`test_v0868_genre_selector_inline_edit.py`, `test_genre_filter.py`,
`test_master_edit.py`, `test_migrations.py`): **143 passed, 0 failed,
2 skipped** - the two
skips are the pre-existing `busan_name` fixture, since KR-BUSAN was
added through the admin console on the real board and no migration
seeds it into a fresh database.

Full suite in the container: **1861 passed, 2 failed, 18 skipped.**
Both failures are `test_miltang_source_migration.py` and
`test_tango_source_expansion_migration.py` asserting that source
`SRC-W-001` (K-Tango) already exists - a row migration 021's own header
notes was "added through the admin console at runtime", never by a
migration. Verified pre-existing and unrelated: the identical two
failures reproduce on unmodified v0.86.7 HEAD against the same fresh
database. Nothing in this release touches source seeding.

### Private Alpha Observation

Continues unchanged - the standing recurring observation job was never
touched by this release.

## v0.86.7 Admin Venue Filters + Genre/Region Management + Social Event Format

Status: PASS, 2026-09-09.

Version split:

- Product Runtime: 0.86.7
- Information Engine: 0.85 (unchanged - no classifier change)

### What changed

**Venue filters.** `/admin/venues` gets a region selector (exact
`venues.region_id` match, never a fuzzy region-name comparison) and a
multi-genre checkbox filter - OR across the genres chosen, AND with
region. Both live in the query string
(`?region=<code>&genres=<code>,<code>`), so a reload or a shared link
keeps the same view; a result count and a reset link are shown. The
AND/OR toggle UI some future release might want is deliberately out of
scope - OR is the only behaviour this release ships.

**Safe genre/region delete.** Every foreign key to `genres`/`regions`
across the schema (`organizers`, `sources`, `events`, `venue_genres`
for genres; `venues`, `organizers`, `sources`, `events` for regions)
was confirmed to carry no `ON DELETE CASCADE` - Postgres already
refuses a referenced delete on its own. `master_edit.delete_genre()`/
`delete_region()` add a friendly reference-count check in front of
that, in the same "refuse with a real count" shape `remove_alias()`
already established - no unlink/cascade escape hatch exists for either
one. TANGO/SALSA/SWING are protected unconditionally, reference count
or not.

**Social Event Format.** Investigated first, per this release's own
instruction not to duplicate an existing field: `events.event_type`
already carries almost exactly this vocabulary (MILONGA/PRACTICA/
SOCIAL/SOCIAL_WITH_CLASS/PARTY/CLASS/OTHER), already labelled in
Korean via `EVENT_TYPE_LABELS`, already surfaced on the public Timeline
and the Admin Source Audit's Extracted table. Fixed PRACTICA's label
(쁘락띠까 → 쁘렉, the word the scene actually uses) and added GENERAL
(제너럴) to the vocabulary - not yet emitted by the engine anywhere
(confirmed: no classifier code path assigns it), since this release is
taxonomy/UI only, no classifier change. `events_api.format_of()` is a
pure, read-only mapping down to the five Admin chip categories
(MILONGA/PRACTICA/GENERAL/SOCIAL/UNKNOWN) - no new write action was
added, since no genuinely repeated hybrid-format case ("쁘렉+소셜") was
found to justify one. Admin/Public parity holds by construction: one
dict feeds both the Timeline and the Admin chips.

### A real defect caught by this release's own staging run, before merge

`master_edit.delete_genre()`/`delete_region()` record their audit
entry through the existing `master_data_actions` table, like every
other master-data edit - but that table's `action` CHECK constraint had
never been extended for a genre/region actually being deleted (only
edited/enabled/disabled/aliased/imported/genre-tagged). Every delete
call raised a `CheckViolation` instead of the intended `EditError`.
Migration 031 extends the same constraint 018/020/028 already extended
for their own new action values. Verified against a freshly recreated
staging database after the fix: clean.

### Production audit (real data)

- 35 real venues: Seoul-only filter → 14 (region_id match confirmed on
  every row), Tango-only → 5, Seoul AND Tango → 5.
- Core genre protection verified against real usage: TANGO (5 venues,
  10 sources, 289 events), SALSA (9 sources, 17 events), SWING (9
  sources, 6 events) - all three correctly blocked regardless of these
  real counts.
- Seoul region delete attempt correctly blocked with real counts
  (14 venues, 9 sources, 189 events) - nothing was actually deleted at
  any point against production; only the blocked path was exercised.
- Real production `event_type` distribution today: MILONGA (277),
  SOCIAL_WITH_CLASS (46), SOCIAL (18) - no PRACTICA, GENERAL, or PARTY
  events exist live yet, so the corrected/new labels aren't visible on
  any real event today. Reported honestly rather than staged to match;
  the vocabulary is ready for whenever one appears.

### Tests

30 new tests in `tests/test_v0867_venue_filters_event_format.py`
(venue filter OR/AND semantics, genre/region delete blocking and core
protection, no-cascade verification, Event Format label mapping,
Admin/Public parity, regressions) plus one migration-discovery test
extended. Full suite in a freshly recreated isolated staging container
(after the migration fix): **1802 passed, 0 failed, 18 skipped.**

### Private Alpha Observation

Continues unchanged - the standing recurring observation job was never
touched by this release.

## v0.86.6 Open-ended Event Time Display

Status: PASS, 2026-09-09.

Version split:

- Product Runtime: 0.86.6
- Information Engine: 0.85 (unchanged - display-only, no extraction change)

### What changed

A post that names a start time and nothing else used to render as a
bare "20:00" on the Timeline - indistinguishable from a value that
simply ran out of room, with no signal an end time was ever
considered. DanceMate does not guess an end time (no default duration,
never `20:00~23:00` or `20:00~00:00` invented) - now the gap itself is
shown: `20:00~미정`. Built structured on `start_time`/`end_time`
themselves in `_timeline_clock()`/`_when_line()`, never a string
patched after rendering, so a real end time can never collide with the
open-ended case. A fully-unknown time (neither field present) is
unchanged - still `시간 미확인`, and a real value is never followed by
that phrase. The Admin Item Audit Detail's Extracted fields table now
shows `NULL (미정)` for an absent end time; its Public Display preview
inherits the new formatting automatically, since it calls the same
`runtime.public` renderer as the live Timeline - no second formatter.

### Real investigation before writing any code

Went in expecting to find today's Daegu "디디디" event (event_id
88425) rendering `21:00~`. It doesn't: both its own row and next
week's occurrence (88378) have `start_time=NULL, end_time=NULL` in
Postgres, matching their Miltang-sourced body exactly (which states no
time at all - a genuine source gap, not an engine defect). A full scan
of the live database found zero events anywhere with a start time and
no end time - the exact symptom described going in does not currently
exist in production. Reported honestly rather than forced to match:
this specific event's own display is unchanged by this release, but
the underlying policy (never guess an end time; never conflate
"start known, end unknown" with "nothing known") is still real and
necessary for whenever a future post gives a start and nothing else.

### Tests

23 new/changed tests in `tests/test_v0866_open_ended_time_display.py`
(structured start/end cases, no-time unchanged, never both 미정 and
시간 미확인 shown, midnight-cross unaffected, Admin/Public parity,
Admin Extracted NULL/미정 pairing, conditional-fee independence,
277498 multi-program regression) plus one v0.85.9-era test updated
because it pinned the exact old bare-start behaviour this release
deliberately changed. Full suite in the isolated staging container:
**1759 passed, 0 failed, 18 skipped.**

### Production audit (real data)

- Both real 디디디 occurrences confirmed unchanged (still `시간
  미확인`, matching their genuine no-time source data).
- 0 of 100 real upcoming events are currently start-only - confirmed
  live, consistent with the investigation above.
- 5 full-range events spot-checked live: no `미정` leak.
- Event 277498 (the known multi-program time case) unaffected: still
  `20:30~21:20`, no `미정`, no regression from this release's formatter
  change.

### Also applied this session: 13 new Salsa/Swing candidate sources

A researched CSV (`dancemate_sources_20260909_salsa_swing_expanded.csv`)
was applied through the existing Admin CSV import preview/confirm flow
- never raw SQL. Two data-quality issues in the file were caught before
import: a literal `"None"` string artifact in one URL cell, and 7 rows
using `authority_level=PRIMARY_COMMUNITY`, a value outside the system's
real enum. Rather than risk an unintended edit to any of the file's 20
pre-existing rows (one of which, SRC-D-003, already carries that exact
grandfathered value in production), the import was scoped to only the
13 genuinely new candidate rows, with the bad enum value corrected to
`UNKNOWN` - matching the convention every other COMMUNITY-role source
already uses. Result: 13 created, 0 updated, 0 unchanged - all new
sources start disabled, per established policy.

### Private Alpha Observation

Continues unchanged - the standing recurring observation job was never
touched by this release.

## v0.86.5 Admin Source Dense Layout

Status: PASS, 2026-09-09.

Version split:

- Product Runtime: 0.86.5
- Information Engine: 0.85 (unchanged)

### What changed

UI-only density pass over the Admin Source Audit Workbench's list view
(`/admin/sources`): thirteen columns down to seven. A separate "URL"
column merges into "Target" - `_source_target()`'s existing collector-
target display (a URL, or a query-driven source's search queries, with
its own "Open Source" debug button pointed at the raw collector value)
now sits above a resolved "↳ 원문보기 ↗" Public URL line, rather than
repeating the same value under a second "Collector" label the way the
old URL column did. Content Mode, collector capability (LIVE/SNAPSHOT),
Health, and Interval fold into one `.metacell`, at most three lines.
Genre/Region and Tier share a cell. The Decision-recording *form*
(select + reason input + button) moves into Actions behind its own
collapsed `<details>` - genuinely never "short metadata" - while the
current decision itself stays as a small, always-visible badge in
Status/Last Run. No DB migration, no engine change, no source-
collection-logic change, no Public Timeline change - purely how the
Sources list renders.

### A second real defect caught by this release's own tests, before merge

Writing the JSON-endpoint-as-public-link regression tests surfaced a
second, live gap of the same shape v0.86.4 fixed for Tango Calendar
Korea: TangoClass's own source-level url is a WordPress REST endpoint
(`https://tangoclass.co.kr/wp-json/wp/v2/posts?per_page=10`), which
never matched the v0.86.4 fallback's literal `/api/` path check.
Confirmed against the real, live value before writing the fix.
Extended `events_api.resolve_public_source_url()`'s generic fallback
to also catch `/wp-json/` paths - `https://tangoclass.co.kr/` now
resolves correctly, verified against all three DIRECTORY/PRIMARY
sources that previously needed this class of fallback (TangoNOW,
Tango Calendar Korea, TangoClass).

### Production audit (all 20 real sources, live data)

- Row compactness: every one of the 20 real sources' Target+Meta+Genre/
  Tier cells rendered 9-10 `<div>` lines - max/avg ratio 1.05, nowhere
  near a "4-5x taller than the rest" bloat case.
- Longest source name: "Tango Calendar Korea" (20 chars). Longest
  collector URL: TangoNOW's Firestore endpoint (106 chars, truncated by
  the existing `_truncate()` display logic, never expanding the column).
- Genre filter counts unchanged from v0.86.4: ALL 20 / TANGO 10 / SALSA
  3 / SWING 2 / 장르 미확인 5.
- All three named URL regressions (TangoNOW, Tango Calendar Korea,
  TangoClass) verified live: each source's Target cell keeps its "Open
  Source" collector-debug link (raw value, on purpose) alongside a
  correctly resolved Public URL - `ktnow.kr`, `tangocalendar.kr/`,
  `tangoclass.co.kr/` respectively, never the raw JSON/API endpoint.

### Tests

26 new/changed tests in `tests/test_v0865_admin_source_dense_layout.py`
(structural checks on the merged cells, genre-filter regressions, the
two named JSON-endpoint regressions, item-audit-detail reachability,
source row actions) plus one v0.86.4 test updated because it pinned the
exact old "Collector"/"Public" text-label structure this release
deliberately consolidated away. Full suite in the isolated staging
container: **1736 passed, 0 failed, 18 skipped.**

### Private Alpha Observation

Continues unchanged - the standing recurring observation job was never
touched by this release.

## v0.86.4 Admin Source Audit & Public Display Parity

Status: PASS, 2026-09-09.

Version split:

- Product Runtime: 0.86.4
- Information Engine: 0.85 (unchanged - no extraction algorithm touched)

### What changed

Two real Timeline defects, fixed together because they shared one root
cause: the old status/time vocabulary was baked into free text, so any
new certainty signal had nowhere to live except more text.

1. A real, shown clock value (`20:30~23:30`) could still carry its own
   contradicting `시간 미확인` tag right next to it, whenever the post's
   time was am/pm-ambiguous. Fixed on both the Timeline and the detail
   page: the value stands, unflagged; a genuinely absent time (no
   reading at all) still shows the honest, non-contradictory `시간
   미확인` placeholder it always did.
2. The `확인 필요` text badge is retired outright, replaced by a small
   "?" right after the event type (`밀롱가 ?`), with a tooltip. Its
   visibility reuses the engine's existing status vocabulary (POSSIBLE/
   EXPECTED/CONFLICT/UNKNOWN show it by default; VERIFIED is fixed off,
   never admin-togglable; CANCELLED/COMPLETED defer to their own
   existing UI) rather than inventing a new confidence score - none
   existed anywhere in this codebase to reuse instead. A new Admin
   Settings page (`/admin/settings`) lets an operator turn the whole
   thing off or narrow which statuses show it, backed by a new,
   deliberately small `timeline_confirmation_settings` table (migration
   030) - no generic admin-settings mechanism existed to reuse.

The Admin Source list is reworked from a plain CRUD table into an audit
workbench: a genre filter (ALL/TANGO/SALSA/SWING/장르 미확인 - a
source's own `genre_id` is a single nullable FK, so "multi-genre
bucket" does not apply to today's data model), a visible source tier
badge (PRIMARY/PROMOTION_BOARD/DIRECTORY), a wider desktop layout, and
a Collector-vs-Public URL column so an operator can tell a source's own
collection endpoint apart from the real page a reader would open. A
new per-item Item Audit Detail page
(`/admin/sources/{id}/items/{item_id}`) compares Original -> Acquired
-> Extracted -> Public Display for one post side by side - the Public
Display column calls `runtime.public`'s own `_timeline_line1/2/3`
directly, never a second formatter that could quietly drift from what a
real reader sees.

### A real defect caught by this release's own production audit

`_source_url_cell()`'s Public URL resolution reuses
`events_api.resolve_public_source_url()` - the same function the live
Timeline already uses per-item - but a SOURCE's own top-level `url` is
the collector's *list* endpoint, not a specific post. Tango Calendar
Korea's is `https://tangocalendar.kr/api/events` (no per-event id), which
matched neither of the function's existing per-item patterns and fell
through unchanged: a JSON endpoint would have been shown as "원문보기"
on the new Source Audit Workbench, exactly what Section 82-92 forbids.
Caught against real production data before merge, fixed with a generic
`/api/...` -> site-origin fallback (`https://tangocalendar.kr/`),
consistent with the function's existing "no per-event page exists, fall
back to the site itself" reasoning for TangoNOW's Firestore case.
Re-verified against all four DIRECTORY/AGGREGATOR sources' real stored
URLs afterward.

### Explicit non-goal: event 277498 stays unfixed

Event 277498 (a Daum Cafe post naming several distinct time slots
across one newsletter) is this release's own worked acceptance example
for the Item Audit Detail, not a bug to fix here. Original: the real
party runs 21:00-02:00(+1); a workshop sub-segment inside the same post
runs 20:30-21:20. Extracted and Public both read 20:30-21:20 - the
wrong sub-segment. The Item Audit Detail makes this immediately visible
side by side (exactly its purpose); the parser itself is untouched, per
this release's own scope decision. Confirmed still present, identically
shaped, during the Private Alpha Field Observation's Day 2 daily
check-in on the same day.

### Production audit (real data, before and after the fix above)

- 100 real upcoming events scanned for the time-text contradiction:
  0 found, in either direction. `확인 필요` text: 0 occurrences.
- All 312 currently-listed events are `POSSIBLE`; 0 are `VERIFIED`
  anywhere in the live database. The "?" indicator therefore shows on
  effectively every event today - an honest reflection of the engine's
  evidence gate never having promoted anything yet, not a defect
  introduced by this release. Flagged as this release's own Next
  Recommendation.
- Genre filter, live: ALL 20 / TANGO 10 / SALSA 3 / SWING 2 / 장르
  미확인 5 - real Salsa and Swing sources exist and are correctly
  bucketed; the 5-source UNKNOWN bucket matches the sources that
  genuinely carry no `genre_id`.
- Named-source audit summaries (Items / Events / gaps), real data:
  SRC-D-003 (Solo Tango, PRIMARY) 49 items / 28 events; SRC-W-002
  (TangoNOW, DIRECTORY) 78/38; SRC-W-003 (Tango Calendar Korea,
  DIRECTORY) 52/16; SRC-W-004 (DanceInfo, DIRECTORY) 20/2; SRC-W-005
  (Miltang, DIRECTORY) 172/159; SRC-W-006 (TangoClass, PRIMARY) 10/2.
  Miltang's fee/DJ gaps (159/159 and 154/159) are the largest in the
  dataset - a real completeness gap, not a rendering defect.
- 20 real events compared Admin-preview-vs-live-Timeline field by
  field: 0 differences (both call the identical `runtime.public`
  functions - this confirms the parity claim structurally, not by
  coincidence).
- Both today's real duplicate-fold groups (38596, 188132) were
  DIRECTORY-vs-DIRECTORY ties; no PRIMARY-vs-DIRECTORY case existed
  today to further stress representative selection.

### Tests

50 new tests in `tests/test_v0864_admin_source_audit_public_parity.py`
(Timeline Status, Admin/Public Parity, Source Audit Workbench/Item
Detail, Regression), plus 4 pre-existing tests updated because they
pinned the exact old behaviour this release deliberately changed (the
old contradicting time flag; the old `확인 필요` text badge) and one
migration-discovery test extended for the new migration file. Full
suite in the isolated staging container: **1710 passed, 0 failed, 17
skipped.**

An unrelated finding along the way: re-running the full suite twice
against one persistent staging Postgres (without recreating it between
runs) produced 4 unrelated failures in `tests/test_image_poster_ocr.py`
from committed rows left behind by tests that open their own autocommit
connections - confirmed as test-infrastructure cross-run pollution, not
a regression, by re-running once against a freshly recreated database.
Worth flagging for whoever wires this into repeatable CI.

### Private Alpha Observation

Continues unchanged - the standing recurring observation job was never
touched, deleted, or reset by this release. Its own Day 2 check-in (run
independently, same day) re-confirmed the 277498 pattern and found one
new, similarly-shaped case (event 140726, a different source and
genre) plus one new, distinct defect (a DJ named in the post's own text
but not extracted) - both logged for the observation's own separate
report, not fixed here.

## v0.86.3 Venue After Region

Status: PASS, 2026-09-09.

Version split:

- Product Runtime: 0.86.3
- Information Engine: 0.85 (unchanged - no engine code touched)

### What changed

Moves the resolved venue name from line 2 ("Venue · 행사명 (DJ) · 입장료 ·
주소", v0.86.2's own brief home for it) to line 1, right after the
region: `[서울] Tango O Nada · 오늘 20:00~23:30 밀롱가`. Line 2 reverts to
what v0.86.1 had - event title first, no venue prefix. UI-only: no DB
write, no migration, no engine change.

### A real defect caught by this release's own production audit

The first implementation made `.tl-1` a single-line flex row
(`display:flex; white-space:nowrap; overflow:hidden`) with the venue as
the only shrinkable child - the same shape line 3 already uses safely.
Running the production audit against real data broke that assumption
immediately: on several real events (Mi Vida tango studio, Ulsan Tango
Sociedad, Tango club Mi Noche), the *non-venue* tail alone - date + time
+ "시간 미확인" flag + event type + the "확인 필요" status badge, all
`flex-shrink:0` - measured ~430px, wider than any of the 360/390/430px
target viewports even before the venue name is considered. `overflow:
hidden` would have silently clipped that content rather than wrapping it.

Fixed before this ever reached staging or production: line 1 now stays
plain inline flow, exactly as it always was and exactly as line 2 still
is. Only the venue name gets a bounded width - the same `display:
inline-block; max-width; text-overflow:ellipsis` shape line 2's own
`.tl-2-addr` has used since v0.85.8 - so an unusually long venue name is
the one thing that can ellipsize; everything else wraps onto another
visual line instead of being clipped, the same guarantee line 2 has
always had.

### Duplicate-suppression helpers removed (investigated first)

v0.86.2's `_venue_prefix_html()` and `_title_already_announces_venue()`
existed to stop line 2 from showing "Tango O Nada · Tango O Nada 월나다".
Checked first whether either was used anywhere else (Section 8) - neither
was, outside line 2's own now-removed venue prefix and its own test
file. Line 1 has no competing "title" to duplicate against, so both were
deleted rather than left as dead code. A raw event title that happens to
already contain the venue's name is the original post's own text and is
never edited or filtered - only line 1's own venue span is new, and it
never touches that title.

`events_api.py` is untouched: the `venue_aliases` join and `venue.
aliases` API field added in v0.86.2 stay, since `public.py` no longer
consuming them for duplicate-checking doesn't mean nothing else might.

### Production audit (154 real upcoming events, live production data)

- Venue Known (resolved): 143/154 · Shown After Region: 143 · Missing (no
  venue evidence): 11 · Wrong: 0.
- 0 structural issues across all 154: exactly one `tl-1` div each, venue
  always between region and the date/time/type tail, never before region.
- All 5 required live samples confirmed exact-match on real production
  data: Solo Tango 화정 (`[서울] Tango O Nada · 9/8(화) 20:00~23:30
  밀롱가`), BUSAN TANGO FIRE (`[부산] 이데알 탱고 까페 · ...`), TANGO FIRE
  (`[서울] 라 벤따나 · ...`), 까사밀롱가 (`[서울] OCHO · ...`), Abrazo
  밀롱가 (`[서울] PISTA · ...`).

### Regressions confirmed unaffected

End time, conditional fee, DJ-duplicate suppression, address, source-link
human-readability, Naver map format, positive-region-filter, and week
window/calendar - all pinned by dedicated regression tests, all passing
against real Postgres.

### Tests

24 new/replaced (`tests/test_v0863_venue_after_region.py`, superseding
`test_v0862_timeline_venue_prefix.py` whose entire subject - line 2's
venue prefix - no longer exists), covering all 18 items the task spec
required plus regression pins. 1658 passed / 15 skipped / 0 failed
against real Postgres (staging), 1197 passed locally.

### Private Alpha Observation

The field-observation window that started with v0.86.2 continues
unbroken - this UI release does not reset it. Daily observation from
this point on reflects the new venue-in-line-1 layout.

### Next recommendation

None outstanding from this release's own scope. Continue the Private
Alpha field observation as planned; no further Timeline layout changes
are queued.

## v0.86.2 Timeline Venue Name Prefix

Status: PASS, 2026-09-09.

Version split:

- Product Runtime: 0.86.2
- Information Engine: 0.85 (unchanged - no engine code touched)

### What changed

Line 2 now leads with the resolved Venue Master name, ahead of the event
title: `Tango O Nada · [화정] 9월 8일 화정 공지 (DJ : 유진) · 입장료: 8,000원
(22시 이후 5,000원) · 마포구 동교로 193…`. Display-only - no event, venue,
or candidate row is written by this release, and Line 1/Line 3 are
untouched.

### Safety policy (Section 3-11)

Only a **RESOLVED** venue prefixes at all - an unresolved venue (raw text
read, not yet matched to the Venue Master) or an event with no venue
evidence keeps line 2 exactly as it rendered before this release. When
the event's own title already names the venue - by its resolved name or
any of its officially registered aliases - the prefix is suppressed
rather than shown twice ("Tango O Nada · Tango O Nada 월나다" never
happens). Duplicate detection reuses `master_data.normalize_alias()` (the
same NFKC/case-fold/punctuation-strip the alias table itself is matched
with) and a plain substring check - never fuzzy matching, never inferring
an alias nobody registered.

### Implementation

- `runtime/events_api.py`: `_SELECT` gains one additive `LEFT JOIN
  LATERAL` for the venue's own `venue_aliases`, aggregated in the same
  query as everything else - confirmed no N+1 (Section 31): the query
  already joined `venues` for the name, this adds only the alias list
  alongside it, once per query, not once per event. `present()` exposes
  it as `venue.aliases` (new, additive API field).
- `runtime/public.py`: `_venue_prefix_html()` (RESOLVED-only gate,
  duplicate/alias suppression) and `_title_already_announces_venue()`
  (the substring check). Styled to match `.ev-name`'s own font-weight -
  no badge, no new color.

### Production audit (148 real upcoming events, live production data)

- Venue Known (resolved): 137/148 · Prefix Shown: 125 · Duplicate
  Suppressed: 12 · Missing (no venue evidence): 11.
- All 12 duplicate-suppressed cases verified against the real
  `venue_aliases` table - every one backed by a genuinely registered
  alias (PISTA↔피스타, Tango Mio↔Mio, 아브라쏘↔abrazo, 청주탱고
  우르끼자↔urquiza, and others) - 0 false suppressions, 0 wrong prefixes.
- Structural check across all 148: 0 line2/line3 div-count issues, 0
  cases of the venue span appearing after the event title.
- Exact Section 49 acceptance target confirmed on the real Solo Tango 화정
  event (event_id 221245): `Tango O Nada · [화정] 9월 8일 화정 공지 (DJ :
  유진) · 입장료: 8,000원 (22시 이후 5,000원) · 마포구 동교로 193…`.
- 4 additional named live samples (BUSAN TANGO FIRE → 이데알 탱고 까페,
  TANGO FIRE → 라 벤따나, 까사밀롱가 → OCHO, plus the Solo Tango case
  above) - all correct, no duplicates, no wrong venue.

### Regressions confirmed unaffected

End time, conditional fee, DJ-duplicate suppression (including the
emoji-decorated-title case from v0.86.0), source-link human-readability,
Naver map format, positive-region-filter, and line 3's one-line structure
- all pinned by dedicated regression tests in this release's own test
file, all passing against real Postgres.

Two pre-existing tests needed updating for the new, intentional behavior
(not regressions in the tests' own original intent): `test_events_api.py
::test_an_unresolved_venue_says_so` (exact-dict-equality now includes the
additive `aliases: []` field) and `test_v0854_address_source_link.py
::test_venue_name_never_shown_as_address` (its real intent was always
"not inside the address span specifically" - the venue name now has a
second, legitimate reason to appear elsewhere on line 2).

### Tests

22 new (test_v0862_timeline_venue_prefix.py, covering all 20 items
Section 48 required plus 2 extra DJ-regression variants), 1656 passed /
15 skipped / 0 failed against real Postgres (staging), 1195 passed
locally. Engine: unchanged, not re-run (no engine code touched).

### Next recommendation

None of this release's own scope is left open. A future release could
consider display-only ellipsis on the venue span itself (Section 19
explicitly allows it) if a real production venue name is ever found wide
enough to matter - none was in this audit's 148 real events, so nothing
was added speculatively.

## v0.86.1 Time-dependent Test Stabilization

Status: PASS, 2026-09-09.

Test determinism maintenance release. No production event/source/
extraction semantics changed.

Version split:

- Product Runtime: 0.86.1
- Information Engine: 0.85 (unchanged - no engine code touched)

### The problem

`tests/test_v0852_source_depth.py` and `tests/test_tangocalendar_discovery.py`
both hardcoded a fixed calendar date whose test *intent* was "this event
must count as upcoming/current" - `source_ops.evidence_tiers()` filters
`event_date >= current_date` (Postgres, Asia/Seoul), and
`tangocalendar_discovery.parse_events()` has its own upcoming-only cutoff.
Once the real calendar passed 2026-09-08/09-05, both fixtures silently
became past data and every dependent assertion started failing (or, worse,
in two other files, silently stopped meaning anything) - forever, with
each passing day, not a flake.

### Baseline (reproduced before any fix)

- `test_v0852_source_depth.py::test_evidence_tiers_counts_a_primary_directory_pair_as_multi_tier`
  and `::test_evidence_tiers_folded_duplicate_still_counts_toward_multi_tier`:
  `assert before["multi_tier"] >= 1` → `assert 0 >= 1`. Root cause: fixture
  `event_date="2026-09-08"` vs. real `current_date` already past it.
- `test_tangocalendar_discovery.py::test_discover_tags_every_post_with_source_and_platform`
  and `::test_parse_list_reads_a_recorded_api_response_text`: `IndexError:
  list index out of range` on `posts[0]`. Root cause: `_event()`'s fixed
  `startDate="2026-09-06T05:00:00Z"` fell outside `parse_events()`'s own
  upcoming-only cutoff once real "today" passed it, and neither
  `discover()` nor `parse_list()` exposed a way to pin "today" the way
  `parse_events()` itself already could.

### Project-wide sweep

Every `test_*.py` in `tests/` and `engine/tests/` (158 files) checked for
the same pattern: a fixed date literal reaching a real-clock default
(`date.today()`, `datetime.now()` with no override, or a SQL
`current_date`/`now()` filter) instead of an explicit injected clock. Two
already-known files, plus two more the sweep itself found: silently
**vacuous** (not failing, just no longer testing anything) delta
assertions in `test_v0855_venue_address_coverage.py::test_calendar_count_unchanged_by_venue_link`
and `test_v0856_human_venue_verification.py::test_calendar_count_unchanged`
- both compared `events_api.search(when="upcoming")` totals before/after a
venue-link action, against a fixture pinned at `event_date="2026-09-05"`;
once that fell out of "upcoming" relative to the real clock, both
before/after totals excluded the fixture entirely and the delta assertion
(`0 == 0`) passed regardless of whether venue-linking actually worked.
Everything else in both directories was confirmed already safe (explicit
`now=`/`today=`/`on=`/`published=` injection, or dates that never reach a
real-clock comparison at all) - no other genuinely dangerous fixture found.

### Fixes

- `runtime/tangocalendar_discovery.py`: `parse_list()` and `discover()`
  now accept an optional `today: date | None = None`, forwarded to
  `parse_events()`'s own pre-existing parameter. Production never passes
  it (defaults to `None`, identical to `parse_events()` itself) - **zero
  behaviour change** for any real caller.
- `tests/test_v0852_source_depth.py`: hardcoded `"2026-09-08"` /
  `date(2026, 9, 8)` replaced throughout with `_BASE_DATE =
  events_api.today() + timedelta(days=14)` (the same "today in Seoul"
  helper production itself uses) and a matching Monday-Sunday week
  window. No assertion in the file ever cared about the literal date.
- `tests/test_tangocalendar_discovery.py`: the two affected tests now pin
  `today=TODAY` explicitly, the same way `test_base_event_parses_title_venue_fee`
  already did through `parse_events()` directly.
- `tests/test_v0855_venue_address_coverage.py` and
  `tests/test_v0856_human_venue_verification.py`: both `..._unchanged`
  tests now pin `now=` to a fixed moment before their own fixture's date,
  so the delta assertion is exercising real behaviour again - confirmed:
  venue-linking genuinely does leave the calendar count unchanged, no
  latent bug was hiding behind the vacuous pass.
- `tests/test_v0861_time_test_stabilization.py` (new): pins the date
  arithmetic all of the above relies on across a KST boundary matrix
  (00:00, 00:30, 08:59, 09:00, 23:59 - the dangerous 00:00-08:59 window
  where UTC still reads the previous day), Monday week-start, and a
  4-point today-simulation matrix (2026-09-08/09, 2026-12-31, 2027-01-01)
  including the year-boundary case.

No production code touched beyond the two purely-additive, default-`None`
`today=` parameters above. Source priority, Timeline rendering, and
extraction are all byte-for-byte unchanged this release.

### Validation

- Full runtime suite (staging, real Postgres): 1634 passed, 15 skipped,
  **0 failed** (previously 2 tangocalendar + 2 v0852 failures).
- Full runtime suite (local, no DB): 1173 passed, 470 skipped, 0 failed.
- Full engine suite: 809 passed, 0 failed (no engine code changed).
- Repeated runs: the 5 stabilized files ×5 against real Postgres, plus
  the DB-free files ×10 locally - 0 flakes across all 15 runs.
- No wall-clock sleeps anywhere in the new/changed tests - every clock is
  an explicit value passed to a parameter the function already accepted
  or was extended to accept.

### Next recommendation

None of the remaining fixed-future dates found by the sweep
(`"2027-01-15"` in `test_v0852_source_depth.py`'s directory-only isolation
fixture, and similar far-future literals elsewhere) are dangerous today,
but they will eventually need the same relative-date treatment as their
own "today" passes them - low priority, no action needed until then.

## v0.86.0 Private Alpha Field Validation

Status: PASS, 2026-09-09.

Version split:

- Product Runtime: 0.86.0
- Information Engine: 0.85 (extractor.py's DJ_RE changed - a real bump)

### What this release actually was

Not a feature release. A full-field audit of production's own Timeline as
a real user would see it - "실제 사용자가 첫 화면을 보고 오늘/내일/이번 주
어디서 춤출지 판단할 때 틀리거나 헷갈리거나 불편한 정보를 찾아 그것만
정확하게 수정한다" - and then only the confirmed real problems, nothing
invented to justify the release.

### Audit scope

Every one of production's 148 real upcoming events, read through the
actual `events_api`/`public` code paths (not a copy of the logic), across
every dimension the Timeline shows: Line 1 (region/date/time/type), Line
2 (title/DJ/fee/address), Line 3 (source/confirmation/map), every one of
the 53 real multi-tier (PRIMARY+DIRECTORY) duplicate groups, and a sample
of "fee unknown" events' raw source text.

### Confirmed defects (2, both DJ-related)

**1. DJ duplicate badge shown despite the title already naming the DJ**
(event_id 13693: "...5시30분🎉DJ네로🎉🎉", dj=`네로`). The v0.85.3
suppression logic only stripped a fixed list of stop characters (`)，、·`)
from the title-embedded name before comparing - a real emoji-decorated
title left "네로🎉🎉" instead of "네로", so it never matched and the
redundant "(DJ 네로)" badge showed anyway. `runtime/public.py` now strips
trailing decoration by Unicode category, mirroring
`extraction_rules._strip_decoration()`'s already-proven approach on the
engine side. Display-only; no stored data was wrong.

**2. A genuinely wrong stored DJ field** (event_id 32096, DanceInfo):
`dj` read as the literal string `"DJ"`. The real post's own structured
info box puts a bare "DJ" field label directly against a value that
itself starts with the word "DJ" ("...구글맵 DJ DJ 네로 강의..."), and the
single-label pattern captured the second "DJ" as the name instead of
"네로". `engine/src/extractor.py`'s `DJ_RE` now repeats the label match
before capturing, so both "DJ" occurrences are consumed as label and the
real name is reached. Corrected in production via a scoped, detect-only-
verified update to candidate_id 1440 alone (in place, preserving
candidate_id/event_id - never a full reprocess); every other field on
that candidate was confirmed byte-identical before and after.

### Everything else audited clean

- End time: 141/141 events with a known `end_time` showed it correctly
  on the Timeline (`20:00~23:30`) - v0.85.9's fix holding at full scale,
  not just the one sample checked then.
- Source priority: 0 representative-tier errors across all 53 real
  multi-tier (PRIMARY/PROMOTION_BOARD vs DIRECTORY) duplicate groups -
  Miltang/TangoNOW never won representative status over a PRIMARY.
- Address/map link: 0 mismatches (every address has a map link, every
  map-link-bearing event has an address) across 148 events.
- Source links: 0 JSON/API endpoints exposed across every active source
  sampled (SRC-D-003, Miltang, TangoNOW, Tango Calendar Korea,
  DanceInfo, and five Daum Cafe community boards).
- Line 3: 0 structural issues - always exactly one row.
- Long titles: the widest real title (~423px estimated at .92rem, a
  36-character Daum Cafe list-truncated title) does not break the
  3-line lock or push out fee/address - the existing `overflow-wrap:
  anywhere` (v0.85.8) already wraps it gracefully. No display fix
  needed; the v0.85.8-deferred "Long Title" concern is not a real defect
  in current production.
- Fee-missing: one "fee unknown" candidate's body mentioned "무료", but
  it described a free open dance *class*, not free admission to the
  paid social - `extract_fee()`'s existing narrow phrase-matching
  correctly declined to read it as the event's own fee. No real miss
  found; no new parser added.
- `review_hints.py`'s `_FEE_IN_TEXT` gap noted in v0.85.9: re-checked
  against this audit's own samples, no real missed-fee case surfaced it.
  Still deferred.
- Region positive-only filter, weekly calendar (past dates still
  queryable), venue_genres schema/admin, feedback flow (no auto-mutation
  confirmed by code): all regression-clean.

### Tests

809 engine (+3 new) / 1151 runtime local (+8 new), 0 new regressions.
Staged against real Postgres: 1610 passed, with 2 *additional* failures
in `test_v0852_source_depth.py` traced to that file's own hardcoded
`event_date="2026-09-08"` fixture now being in the past relative to
`current_date` in Asia/Seoul (`source_ops.evidence_tiers()` filters
`event_date >= current_date`; the fixture date doesn't move, the
calendar did) - confirmed unrelated to any v0.86.0 code change by direct
trace, not a regression. Noted honestly rather than hidden; not fixed
this release (test-fixture calendar hygiene, not a user-visible
production issue, is out of this release's own stated scope).

### Next recommendation

`test_v0852_source_depth.py`'s hardcoded 2026-09-08 fixture (and likely
other similarly-dated fixtures elsewhere in the suite) will keep failing
forever now that the calendar has passed it - worth a project-wide sweep
for `current_date`-dependent tests pinned to a fixed past date, as its
own small maintenance release rather than folded into a field-validation
pass.

## v0.85.9 Event Time Range + Conditional Fee Display

Status: PASS, 2026-09-08.

Version split:

- Product Runtime: 0.85.9
- Information Engine: 0.84 (extraction_rules.py, extractor.py, models.py,
  database.py all changed - a real bump, not a hold)

### The actual bug

Solo Tango's own weekly "화정" Tuesday milonga (SRC-D-003) read its
20:00-23:30 time range correctly every single week - `parse_time_range()`
already handled "오후 8시 ~ 11시 30분" correctly and needed no change this
release. Its fee, on the same post, every week: unknown. Root cause was not
an over-cautious multi-price safety net discarding a successful read, as
first assumed - `extract_fee()` had no pattern for Korean 천원 (thousand-won)
notation at all, so "8천원 (10시 이후 5천원)" was never even recognised as
an amount, let alone reduced to one number.

### The fix

**Korean 천원 notation** (`_CHEON_AMOUNT_RE`, mirroring the existing 만원
pattern): "8천원"/"5천원" now read as 8,000/5,000; bare "8천" (no 원) reads
as money only behind a fee label (Section 20/21) - "8천명"/"8천번" still
never qualify.

**Conditional fee display**: a trailing `(<hour>시 이후 <amount>)`
parenthetical immediately after a base fee amount is now read as a
condition, not a second unrelated number - `EventCandidate.fee` keeps the
base amount, a new `fee_display_text` field carries the full text
("8,000원 (22시 이후 5,000원)"). The condition's bare hour is resolved to a
real clock value only by anchoring against the event's *own* already-EXPLICIT
start/end window (10시 candidates are 10:00/22:00; only 22:00 falls inside
20:00-23:30) - never a blanket AM/PM guess (Section 2/23). Without a usable
anchor, the raw hour text is kept exactly as written rather than invented.

**Multi-option pricing preserved, not silently picked**: "예매 15,000원 /
현매 20,000원" and "회원 15,000원 / 비회원 20,000원" used to leave the event
unpriced entirely rather than guess which number was "the" fee (a real,
deliberate v0.84.1 safety net). This release keeps both real numbers instead
- `fee_display_text = "예매 15,000원 · 현매 20,000원"`, `fee` stays empty
since no single number is honestly "the" price.

**Timeline end time** (found during this release's own live acceptance
audit, not part of the original spec): the Timeline showed only
`start_time` even when the extractor already had a real `end_time` - the
detail page's own range display has existed for longer. `_timeline_clock()`
now shows `20:00~23:30` when an end time is known, bare `20:00` otherwise,
unchanged.

**New schema**: `event_candidates.fee_display_text` (engine SQLite, added
via the same idempotent `_add_column_if_missing` pattern v0.81.2 used for
`context_id`) and `events.fee_display_text` (Postgres, migration 029),
bridged through `normalize_candidate()`. No other schema, no new pricing
subsystem - the existing `fee` int and one new text column carry everything.

### Real production regression fixture

The exact real post (SRC-D-003, post_id 606, captured verbatim from
`raw_posts.body`) is now a permanent regression test
(`test_the_solo_tango_hwajeong_post_that_defined_v0_85_9`):
date=2026-09-08, start=20:00, end=23:30, dj=유진, venue=Tango O nada,
fee=8000, fee_display_text="8,000원 (22시 이후 5,000원)". "화정지기"/
"화정도우미" (event-specific volunteer-role labels) and the raffle-ticket
mention do not leak into DJ/venue/fee/date.

### Detect-only, then scoped apply

Applied the new parser to the real post in dry-run mode first (Section
40-41) and confirmed an exact match before writing anything. The scoped
apply then updated candidate_id 1847 **in place** (never delete+reinsert,
which would have AUTOINCREMENTed a new candidate_id and orphaned the
existing `events` row instead of updating it) - `event_id` stayed 221245
throughout. Only this one post was touched; `normalize_all()`/
`ingest_pending()`/`reprocess_acquired()` were never called.

### Live production audit (real Solo Tango 화정 event, 2026-09-08)

```
[서울] 오늘 20:00~23:30 밀롱가
[화정] 9월 8일 화정 공지 (DJ : 유진) · 입장료: 8,000원 (22시 이후 5,000원) · 마포구 동교로 193…
출처: Solo Tango 화요정모 공지 ↗ · 확인시간 · 지도보기↗
```

- Detail page: 20:00–23:30 / 요금 8,000원 (22시 이후 5,000원).
- Source priority unaffected (unchanged this release): representative
  stays SRC-D-003 (event_id 221245, `canonical_event_id` NULL); the
  Miltang duplicate (event_id 88436) points `canonical_event_id` at
  221245 - correctly non-representative.
- Calendar: exactly one card for this event on 2026-09-08 - 0 duplicates.
- venue_id 187 (Tango O Nada), address, and Naver map link unchanged.

### Tests

96 engine tests (13 new + 2 upgraded from "unpriced" to "preserved" per
Section 14/15) + 1143 runtime tests (17 new: 13 fee/timeline + 4
timeline-end-time), 0 new regressions. Full suites: 806 engine, 1600
runtime (staging, real Postgres) / 1143 (local) - 2 pre-existing
`test_tangocalendar_discovery.py` failures unchanged from baseline.

### Next recommendation

`_FEE_IN_TEXT` in `review_hints.py` (the admin "body mentions an amount
but nothing was extracted" hint) still only matches 3+ plain digits before
원 - it never caught 천원-notation misses before this release and still
won't catch a genuinely new gap the same way. Low priority: this release's
own fix removes the only known real-world case of it.

## v0.85.8 Timeline Three-Line Lock + Address Reposition

Status: PASS, 2026-09-08.

Version split:

- Product Runtime: 0.85.8
- Information Engine: 0.83 (unchanged)

### The actual bug

v0.85.7 built line 3 as one metadata row - 주소 · 출처: NAME ↗ ·
확인시간 · 지도보기↗ - and allowed a horizontal micro-scroll as its own
fallback for the rare case that row got too wide. In production that
"rare case" turned out to be the common case: combined with a real
address and a real source name, every one of the six representative
source names measured (TangoNOW, Miltang, Tango Calendar Korea, Solo
Tango 화요정모 공지, TangoClass 공식 사이트, DanceInfo) needed 425-534px
against a 308px 360-wide budget - the row visually broke across several
stacked lines instead of scrolling cleanly, exactly as reported.

### The fix

**Line 2** (행사명 (DJ) · 입장료 · 주소): the address moved here, after
the fee, in the same small/meta font-size and color line 3 has always
used (`.tl-2-addr`, `.78rem`, `var(--muted)`) - never the event name's
own bold/size. Ellipsized via a bounded `max-width`, never hiding the
name or fee; omitted entirely (not "주소 미확인") when there is none.

**Line 3** (출처: OOO ↗ · 확인시간 · 지도보기↗): address-free now, and
structurally unable to wrap or scroll - `white-space:nowrap;
overflow:hidden` on the row, with no `overflow-x:auto` fallback this
time (v0.85.7's own allowance is gone). The one thing permitted to give
way is the source's own name: CSS `text-overflow:ellipsis` via flex
`min-width:0` on `.src-name`, while the confirmation time and the map
link are `flex-shrink:0` (`.tl-fixed`) and never touched regardless of
how long the source name actually is. No `sources.short_name`/
`display_name` field exists (checked first, per Section 16's own
instruction) - CSS ellipsis on the real name, with the full name still
in the link's `title` attribute, is the sanctioned fallback (Section 19).

### Proof, not a guess

Section 47 explicitly forbids relying on a pure string-width estimate
for this release's own PASS. No headless-browser/DOM engine is available
in this environment (consistent with every prior release), so the proof
here comes from the CSS specification itself rather than empirical
measurement: `.tl-3`'s `overflow:hidden` with no scroll mechanism
anywhere in its rule, plus `flex-shrink:0` on everything except
`.src-name`, means the row's rendered width can never exceed its
container's `clientWidth` - for *any* source name length, not just the
ones measured. The arithmetic is supplementary due diligence on top of
that guarantee: the part of line 3 that never shrinks needs ~188-240px
(measured two ways: a synthetic worst case, and the actual longest real
production line 3 content), comfortably under every target viewport's
available width (308-378px at 360/390/430px) with 70-190px to spare.

### Live production audit (100 real upcoming events)

- 100/100 line 2 rows, 100/100 line 3 rows, every event still exactly 3
  structural rows (`<div class="tl-N">`).
- 93/100 line 2 rows carry an address segment (`tl-2-addr`); the other 7
  correctly have none - matches the address-known/unknown split exactly.
- 0/100 line 3 rows contain any address-shaped text - full separation
  confirmed.
- Live long-source-name example, address-free and single-line: `출처:
  Solo Tango 화요정모 공지 ↗ · 14시간 전 확인 · 지도보기↗`.
- 0 JSON/API source-link leakage (re-verified).
- Region chips unchanged from v0.85.7's own audit (전체 + 11
  positive-count regions, no zero-count region shown).
- `venue_genres`: 5 rows intact, untouched by this release.
- Event count: 159, unchanged.

### Tests

19 new tests (`tests/test_v0858_timeline_three_line_lock.py`), 6
existing test files updated (their assertions encoded the old
address-in-line-3 layout or the pre-class-attribute `<a href=` string
shape). Full suite: 1587 passed, 15 skipped, 2 pre-existing
`test_tangocalendar_discovery.py` failures (unchanged baseline) - zero
new regressions.

### Scope discipline

UI-only release: no schema change, no migration, no DB write, no engine
change, no source expansion, no change to the source-URL resolver, the
Naver map helper, venue genres, or region-count filtering beyond what
was already shipped in v0.85.4-v0.85.7.

## v0.85.7 Compact Timeline + Venue Dance Genres + Active Region Filter + Naver Map

Status: PASS, 2026-09-08.

Version split:

- Product Runtime: 0.85.7
- Information Engine: 0.83 (unchanged)

### Goal

Four requests in one release: keep the first screen denser rather than
letting it grow more lines, add a genuinely useful "지도보기" (map) link
without any map API, let a venue carry which dance genres it hosts, and
stop showing region filter chips for places with nothing in them right
now.

### Timeline line 3: the map link joins the line, not a new one

`주소 · 출처: OOO ↗ · 확인시간 · 지도보기↗` - address and the "출처 →
확인시간 → 지도보기" group are two flex items. The meta group never
splits apart internally: if it does not fit beside the address it wraps
whole onto its own row, and in the (now genuinely common, on a narrow
phone, with a long source name) case where even the meta group alone
exceeds the viewport, it becomes a horizontally-scrollable strip rather
than ever letting the page itself overflow. Address is what shrinks
first - it was already display-compacted by v0.85.4's own logic.
Confirmation wording made consistent ("N분/시간 전 확인" in every age
bucket now, not just the oldest one).

### Naver Map link - no API, no key, no stored URL

`events_api.build_naver_map_search_url()`: a pure, deterministic
transform of a venue's own full raw address into a Naver Maps *search*
URL (`https://map.naver.com/p/search/{encoded}?c=15.00,0,0,0,dh`) -
`urllib.parse.quote()`, nothing hand-rolled, no network call, nothing
written to the database. None/empty address -> no link, never a
fabricated one. Verified against the spec's own worked example
character-for-character.

### Region filter: only places with something in them

`_region_options()` now drops any region whose count under the *current*
window/genre selection is 0 - "전체" is unaffected, it is injected
separately and never filtered by any individual region's count. Region
counts themselves (`_facets_window`/`_unresolved_region_counts`) are now
also scoped by the currently-ticked genre chips, not just the date
window, so "Genre=Tango, this week" only ever offers regions that
actually have a Tango event that week.

### Venue Dance Genres - Venue Master only, human-confirmed only

New `venue_genres` join table (migration 028, mirrors `venue_aliases`'
own shape exactly) reusing the existing TANGO/SALSA/SWING genre master -
no new enum, no bulk backfill, no venue auto-assigned a genre from a
single event. Admin venue create/edit gets a multi-select checkbox
group; `master_edit.set_venue_genres()` diffs the checked set against
what is already confirmed and writes only the difference, each change
recorded in the existing `master_data_actions` audit trail (028 also
widens that table's own CHECK constraint to allow the two new actions -
caught by the staging full-suite run before it ever reached production).
`observed_venue_genres()` offers a read-only suggestion from a venue's
real event history for the admin screen to show beside the checkboxes -
never itself written.

Live-confirmed for 5 unambiguously-Tango-named real venues (Solo Tango,
Tango Andante, Tango O Nada, Todotango, Tango Brujo) through the actual
admin route, not a bypass script - each is the venue's own name stating
its genre directly, the same evidentiary bar this project's Human Venue
Review has used since v0.85.5.

### Line 2 title-clamp: deferred

The spec's own Section 54 explicitly permits dropping this if it carries
real regression risk against a working Line 2; it does (event
name/DJ/fee share one line's text flow, and a naive line-clamp risks
clipping the fee), so it stays out of this release. Line 3 was the
priority.

### Live production audit (100 real upcoming events)

- 93/100 show a map link, 7/100 correctly omit it (all 7 are exactly the
  "주소 미확인" rows - 0 events with an unknown address wrongly showing
  a map link).
- 33 distinct, correctly-formatted `map.naver.com/p/search/...
  ?c=15.00,0,0,0,dh` URLs found on the page.
- 0 raw JSON/API source-link leakage (re-verified, v0.85.4 regression).
- Region chips: exactly the positive-count regions shown (서울 94, 부산
  20, 대전 7, 대구 6, 광주 4, 진주 3, 청주 3, 울산 2, 창원 2, 포항 2,
  경기 1) plus "전체" - no zero-count region appeared.
- Discovered mid-audit: 5 venues this project's own v0.85.5/v0.85.6
  reports had flagged as "KEEP_OPEN, needs a human" (Ulsan Tango
  Sociedad, CON TANGO, Tango Mio, Bailamos Tango, 청주탱고 우르끼자) had
  since been resolved with real addresses through the live admin console
  by its own operator (`venue_resolution_actions`, reviewer `dancemate`,
  `CREATE_AND_LINK`) - independent of this release, the Human Venue
  Review workflow doing exactly its job.

### Mobile - honest finding, not just a pass/fail

DOM-geometry method (no headless-browser tool available in this
environment): the real longest production tl-3 content, checked at
360/390/430px. The address segment alone always fits easily (116-154px
needed vs 308-378px available). The "출처 → 확인 → 지도보기" meta
segment, now that it always includes the map link, commonly needs
395-411px for a real long source name - *more* than the available width
at every one of the three target viewports. This is not a layout bug:
Section 4's actual requirement (the group is never broken apart
mid-phrase) is met exactly as specified, and Section 8's requirement
(the page itself never overflows horizontally) is also met - both by the
same mechanism, a horizontal micro-scroll scoped to that one inline
strip. In practice the source name and part of the confirmation time are
visible without scrolling (they lead the string); reaching "지도보기"
on the narrowest phones with the longest source names can require a
small scroll gesture within that one row. Reported plainly rather than
claimed as a clean pass, per this project's own standing "no overclaiming"
practice.

### Tests

41 new tests (`tests/test_v0857_compact_map_venue_genres.py`): Venue
Dance Genres (12), Region Filter (9), Naver Map (11), Timeline (9). Full
suite: 1568 passed, 15 skipped, 2 pre-existing
`test_tangocalendar_discovery.py` failures (unchanged baseline) - zero
new regressions.

### Scope discipline

No map API, no Naver Maps API key, no .env change, no new source, no
engine change, no bulk venue-genre backfill, no address-coverage work
resumed (that stays v0.85.5/v0.85.6's own scope).

## v0.85.6 Human Venue Verification + Safe Address Completion

Status: PASS, 2026-09-08.

Version split:

- Product Runtime: 0.85.6
- Information Engine: 0.83 (unchanged)

### Goal

v0.85.5 correctly deferred two identity/address questions instead of
guessing: were CLUB PAN TANGO and 강남탱고 판 the same place, and what
was 실루엣 분당정자동's actual current address after investigation
turned up three conflicting candidates. This release does not try to
resolve either one automatically - it builds the evidence packet, pauses,
and applies only what a person actually confirms.

### Human review

Two evidence packets were presented; both were reviewed and answered
directly rather than assumed:

**CLUB PAN TANGO / 강남탱고 판** - confirmed as the same place, with the
address confirmed against Miltang's own listing (서울 서초구
강남대로595 경승빌딩 B1). Merged onto one new venue via
`create_and_link` + `link_existing` - 5 upcoming events improved (3 under
"CLUB PAN TANGO", 2 under "강남탱고 판").

**실루엣 분당정자동** - confirmed as 지파크프라자 5층 (정자동 23-1),
not the 정자일로 192 candidate found during investigation. A further,
unprompted correction identified that a third candidate found in
research - 느티로27 하나플라자빌딩 310호 - belongs to an entirely
different, unrelated business ("실루엣 댄스스포츠", a Salsa studio) -
exactly the same-name collision risk Section 34 of v0.85.5's own spec
exists to catch, confirmed by a real person rather than assumed away. The
new venue is named "실루엣 (분당정자동)", not bare "실루엣", specifically
to avoid future confusion with that other business - 1 upcoming event
improved.

Both writes are recorded in the existing venue-resolution audit trail
(`venue_resolution.history()`), reviewer tagged
`human-approved-v0.85.6-kimpro`.

### Human Review KPI

- Reviewed venues: 6 (CLUB PAN TANGO, 강남탱고 판, Mariposa, 아브라쏘,
  Tango Mio, 실루엣 분당정자동)
- Confirmed: 2 (CLUB PAN TANGO/강남탱고 판 as one decision, 실루엣)
- Linked: 1 (강남탱고 판 → the CLUB PAN TANGO venue)
- Created: 2 (CLUB PAN TANGO, 실루엣 (분당정자동))
- Kept Open: 3 (Mariposa, 아브라쏘, Tango Mio - single-DIRECTORY-source
  evidence only, no new corroboration this release, no human input
  volunteered - Section 9's own default)
- Rejected: 0
- Relocation Deferred: 0 (실루엣's relocation question was resolved by
  direct human confirmation, not deferred)

### Coverage

Before: 127/159 known (79.9%). After: 132/159 known (83.0%). This release
was scored on confirmed recovery, not a coverage target - the three
single-directory venues stay open exactly because no stronger evidence
exists yet, not because of an arbitrary cutoff.

### Safety

- Both addresses came from an explicit human answer, not an automated
  confidence score - `_address_conflict()`/`similar_venues()` were used
  only as pre-write sanity checks, never as the approval itself.
- The current schema's single `venues.address` field means a linked
  raw string's entire history (were it to have any) would take on the
  new address - documented and test-covered (Section 18/19), and neither
  of this release's two fixes actually has any pre-existing historical
  event under its exact raw string, so no retroactive distortion
  occurred in practice.
- A full PostgreSQL backup was taken immediately before either write.
- Wrong Address: 0. Wrong Date/Time/Venue/Region/Fee/DJ: 0. False
  VERIFIED: 0.

### Tests

15 new tests (`tests/test_v0856_human_venue_verification.py`)
characterizing the human-approval gate itself: no address is ever
written without a human-provided venue_id/address, two human-confirmed-
same-place names merge with both aliases registered, region conflicts
and disagreeing historical addresses still refuse to auto-merge. Full
suite: 1527 passed, 15 skipped, 2 pre-existing
`test_tangocalendar_discovery.py` failures (unchanged baseline) - zero
new regressions.

### Scope discipline

No new runtime code, no new source, no map integration, no schema
migration, no engine change, no mass venue-resolution expansion beyond
the two human-confirmed cases.

## v0.85.5 Venue Address Coverage Improvement

Status: PASS, 2026-09-08.

Version split:

- Product Runtime: 0.85.5
- Information Engine: 0.83 (unchanged)

### Goal

Reduce the "주소 미확인" rate on the first screen by backfilling only
venue addresses with real, checkable evidence behind them - never a
guess, never a copy from a same-named venue in a different city, never a
Search-snippet-only claim. No new source, no schema change, no mass
reprocess.

### Baseline

100 real upcoming events audited in v0.85.4 showed 81% known / 19%
unknown. A fresh, full-population snapshot for this release (all 159
upcoming Tango events, not a 100-sample) measured **124/159 known
(78.0%)** before any change.

### Where the gap actually was

Every one of the 35 unknown-address events turned out to have
`venue_id IS NULL` - **zero** were a case of "resolved venue, missing
address" (Section 20's own priority-1 bucket had no candidates at all,
an honest finding worth stating plainly). Classification of all 35:

| Bucket | Count | Meaning |
|---|---|---|
| RESOLVED_VENUE_ADDRESS_MISSING | 0 | none found |
| UNRESOLVED_VENUE (no address text) | 11 | venue never resolved, no address anywhere in the raw text |
| RAW_ADDRESS_PRESENT_NOT_LINKED | 11 | venue unresolved but its own raw text already carries a full address |
| SOURCE_HAS_ADDRESS_MASTER_MISSING | 0 | n/a to this dataset |
| NO_ADDRESS_EVIDENCE | 11 | no venue text at all |
| AMBIGUOUS_VENUE | 1 | 실루엣 분당정자동 - see below |
| OTHER | 1 | "강습 인원" - already dismissed as not-a-venue in a prior release |

**Recoverable Gap**: Unknown 35 / Recoverable (real address evidence
exists) 11 / Not Recoverable 24. Of the 11 Recoverable, 3 were resolved
this release; 8 stay deferred (see below) for lack of independent
corroboration - "recoverable" is not the same claim as "safe to apply
today."

### What this release used: existing infrastructure, not new code

`runtime/venue_resolution.py` already has a full, safe Human Venue
Review workflow (`link_existing`, `create_and_link`, `address_in`,
`address_from_context`, `similar_venues`, `_address_conflict`,
`record_action`/`history` for the audit trail) - built for exactly this
kind of decision and already used under human approval in earlier
releases. This release wrote **zero new runtime code**; it used that
existing machinery for two well-evidenced backfills.

### Two approved backfills

1. **홍대 솔로땅고 → Solo Tango (existing venue 4210)**. The organizer's
   own PRIMARY-tier Daum Cafe post (SRC-D-003) for event 222882 gave the
   full address "마포구 홍익로5길 57, 지하 1층" - identical (road, number,
   floor) to the already-resolved "Solo Tango" venue's own stored address.
   `link_existing()` - zero new address written, just the correct venue
   link. 1 event improved.
2. **Tango Brujo (new venue 4224)**. Miltang's directory listing gave
   "마포구 잔다리로 68 ymca빌딩 지하1층"; the studio's own official site
   (sites.google.com/view/tango-brujo/home) states, verbatim, "주소: 서울시
   마포구 잔다리로 68 YMCA빌딩 B1" - independent official confirmation of
   the same place. `create_and_link()`. 2 events improved.

### What was investigated and correctly deferred

Five more venues (Mariposa, 아브라쏘, Tango Mio, CLUB PAN TANGO/강남탱고
판, 실루엣 분당정자동) had address text in their raw posts, but:

- **Mariposa, 아브라쏘, Tango Mio**: Miltang (DIRECTORY tier) only, no
  independent source found despite a real search attempt.
- **CLUB PAN TANGO / 강남탱고 판**: a matching Facebook business page
  exists (confirming these two names are the same real place), but a
  direct fetch of the page itself could not confirm the address text
  (Facebook's static page serves no address content) - Section 16's
  "verify the actual page, not the search snippet" bar was not met.
- **실루엣 분당정자동**: investigation surfaced **three different**
  addresses across sources for this name (하나플라자빌딩 310호 → 느티로
  27 310호 → 지파크프라자 5층, and a fourth, unrelated "정자일로 192" for
  a same-named business) - a real relocation-and-possible-name-collision
  case, exactly what Section 34/35 exist to catch. DEFERRED, not applied.

Zero of these were written. Coverage improvement was capped by evidence,
not by effort.

### Coverage after

**127/159 known (79.9%)**, up from 124/159 (78.0%). Total upcoming count
unchanged at 159 (Section 42) - this was a venue-link correction, not a
new or merged event.

### Safety

- `venues.address` and `venue_id` are not part of any dedup/canonical key
  (`duplicates.py`'s own key is `venue:{venue_id}` or lowercased
  `venue_text` - confirmed in code before writing anything).
  `normalization.link_unresolved_venue()` only recomputes the specific
  updated events' own `identity_key`/`series_key` - no mass reprocess, no
  `normalize_all()`/`ingest_pending()`/`reprocess_acquired()` call.
- Both writes are recorded in the existing venue-resolution audit trail
  (`venue_resolution.history()`), reviewer tagged
  `claude-v0.85.5-address-coverage`, before/after JSON included.
- A full PostgreSQL backup was taken immediately before either write.
- Wrong Date/Time/Venue/Region/Fee/DJ: 0. False VERIFIED: 0. Wrong
  Address: 0 (both backfills independently confirmed against a second
  source before being applied).

### Tests

18 new tests (`tests/test_v0855_venue_address_coverage.py`) exercising
the existing venue-resolution safety functions under this release's exact
scenarios, plus v0.85.4 formatter/source-link/calendar-identity
regression checks against the new real address values. Full suite: 1512
passed, 15 skipped, 2 pre-existing `test_tangocalendar_discovery.py`
failures (unchanged baseline) - zero new regressions.

### Mobile

Same DOM-geometry method as v0.85.4 (no headless-browser tool available
in this environment): the two new real address strings, run through
Unicode East Asian Width classification against the deployed `.tl-3` CSS
at 360/390/430px. Worst case (Solo Tango's address, 437px needed) wraps
to 2 lines at every width.

### Scope discipline

No new source, no map integration, no OCHO/O Nada/PISTA/Andante/EN PAZ
re-research, no schema migration, no engine change.

## v0.85.4 Compact Timeline Address + Human-readable Source Link

Status: PASS, 2026-09-08.

Version split:

- Product Runtime: 0.85.4
- Information Engine: 0.83 (unchanged)

### Goal

Denser first-screen information: show a partial venue address directly in
the Timeline, fold the source row into one line with the address and the
confirmation time, and - the critical fix - make sure the source link a
reader taps always opens something a person can actually read, never a
collector's own JSON API endpoint. No new source research this release
(explicitly out of scope).

### Timeline line 3 redesigned: address + source + confirmation time, one row

`주소 · 출처: OOO ↗ · 확인시간` replaces the old source-and-time-only line.
`runtime.public._compact_address()` shortens a resolved `venues.address`
for display only: it drops the region prefix already shown on line 1
(including a metro city's own contracted "-시" form - found live and
fixed mid-release, see below) and keeps district + road + the first
street number, ellipsizing whatever comes after (floor, suite, building
name, station exit). The stored address itself is never touched. No
address at all renders as an honest "주소 미확인", never a guess, and a
venue's *name* is never shown in place of a real address.

### The real defect: two sources were exposing raw JSON as the source link

Auditing every active source's stored `source_url` against what actually
opens in a browser found two that were showing a reader their own
collector's API response instead of a page:

- **Tango Calendar Korea (SRC-W-003)** stored its own
  `/api/events/{uuid}` REST endpoint as the link - opening it in a
  browser shows raw JSON. The site's own `sitemap.xml` declares
  `{origin}/?eventId={uuid}` as the canonical per-event page for the same
  events (confirmed live: real UUIDs, `lastmod`/`changefreq`/`priority`
  entries), so `events_api.resolve_public_source_url()` rewrites to that
  shape - a pure string transform of already-stored data, no fetch.
- **TangoNOW (SRC-W-002)** stored a raw Firestore REST document URL.
  This module's own prior investigation (kept in
  `tangonow_discovery.py`'s docstring) already found ~80% of this
  source's own records carry no link field at all and `ktnow.kr`'s
  frontend is JS-only with no per-event route - there is no real human
  deep link to rewrite to, so the honest fallback is the source's own
  home page (`https://ktnow.kr/`).

Both are pattern-matched against the stored URL string only - no network
call at render time, no schema change, no backfill of existing rows.
SRC-D-001/003/010/011/012 (Daum Cafe), DanceInfo, Miltang, and TangoClass
were already storing their real human pages and needed no change -
TangoClass in particular was already correct despite this release's own
spec worrying it might not be (it stores WordPress's own `link` field,
not its collection API).

### A second real defect, found by inspection: platform label beat the source's own name

`events_api.source_label()` returned the generic `PLATFORM_LABELS` map
(e.g. "Daum Cafe") whenever the source's platform was a known key, even
when the source's own real name ("Solo Tango 화요정모 공지") was
available - every Daum Cafe source read as the same generic brand
regardless of which cafe post it actually was. Priority reversed: a
source's own name now always wins, the platform map is a last-resort
fallback for the rare row with no name at all.

### Found live, fixed mid-release: a second province-prefix gap

The initial production audit (100 real upcoming events) caught
`"부산시 부산진구 신천대로 62번길 62..."` not being trimmed -
`_PROVINCE_PREFIX` covered Seoul's contracted "-시" form (서울시) but not
the other five metro cities' own contracted forms (부산시/대구시/인천시/
광주시/대전시/울산시). Fixed and redeployed before tagging; re-audited
live to confirm.

### Live production audit (100 real upcoming events, all active sources)

- 81/100 show a real, compacted address; 19/100 honestly show "주소
  미확인" (all checked: genuinely no resolved venue address, never a
  suppressed real one).
- 0/100 show "출처 미확인" - every visible event has a resolvable
  source.
- 0 raw JSON/API URLs found anywhere on the page (`firestore.googleapis.com`,
  `/api/events/{uuid}` - both searched for directly, zero matches).
- Solo Tango 화요정모 공지 (SRC-D-003, PRIMARY-representative for its
  event) links to its own `cafe.daum.net` post - never the co-listed
  Miltang DIRECTORY link for the same event - unchanged representative-
  source selection, confirmed still holding under the new resolver.
- SRC-W-006 (TangoClass): the one current live event's source redirect
  (`/events/{id}/source`) returns `303 -> https://tangoclass.co.kr/...
  /2026/08/22/sep-class/` - confirmed live to be the real WordPress
  article, not JSON.

| Source | Displayed name | User-visible link | Result |
|---|---|---|---|
| SRC-D-003 Solo Tango | Solo Tango 화요정모 공지 | cafe.daum.net (own post) | PASS |
| SRC-W-002 TangoNOW | TangoNOW | ktnow.kr (home, no per-event page exists) | PASS |
| SRC-W-003 Tango Calendar Korea | Tango Calendar Korea | tangocalendar.kr/?eventId=... (rewritten) | PASS |
| SRC-W-004 DanceInfo | DanceInfo | danceinfo.net/lessons/{id} | PASS |
| SRC-W-005 Miltang | Miltang | miltang.com/milongas/{id} | PASS |
| SRC-W-006 TangoClass | TangoClass 공식 사이트 | tangoclass.co.kr (real article, JSON never exposed) | PASS |

### Mobile check

No headless-browser/screenshot tool is available in this environment, so
line-wrap risk was checked by DOM-geometry calculation instead: the
actual longest real line-3 and line-2 strings from the 100-event live
audit, run through Unicode East Asian Width classification against the
real deployed CSS (`.tl-3` font-size .78rem, `.8rem` padding; narrow-
viewport `main`/`li.event a` padding) at 360/390/430px. Worst real line 3
(65 characters, the Tango Calendar Korea example) wraps to 2 lines at
every width - well inside the "3-5 lines is a FAIL" bound. Line 2
(unchanged this release) can reach 2-3 lines on an emoji-heavy real
title, a pre-existing characteristic of the compact-timeline design
(each `tl-N` is one structural block, not a hard one-CSS-line
guarantee), not a regression from this release's own changes.

### Tests

28 new/rewritten tests (`tests/test_v0854_address_source_link.py`, plus
two `test_public_pages.py` assertions that encoded the old label
priority and one integration test for the same). Full suite against a
fresh staging Postgres: 1494 passed, 15 skipped, 2 pre-existing
`test_tangocalendar_discovery.py` failures (unchanged from the v0.85.3
baseline, unrelated to this release) - zero new regressions.

### Data quality

Wrong Date / Wrong Time / Wrong Venue / Wrong Region / Wrong Fee / Wrong
DJ: 0. False VERIFIED: 0. This release touches display/provenance code
only - no date, time, venue, region, fee, or DJ extraction path was
changed - and the live audit's 100-event sample surfaced no field
defects.

### Scope discipline

No new source added, no source research reopened (OCHO/O Nada/PISTA/
Andante/EN PAZ stay at v0.85.3's own conclusions). No migration, no
backfill: both URL fixes and the address formatter operate on
already-stored data at render time.

## v0.85.3 Direct Source Expansion Round 2 + DJ Display Fix

Status: honest zero-new-source research outcome, one real UX defect
fixed, 2026-09-08.

Version split:

- Product Runtime: 0.85.3
- Information Engine: 0.83 (unchanged)

### Goal

v0.85.2's own post-release audit ranked OCHO, Tango O Nada, PISTA, Tango
Andante, and EN PAZ as the highest-frequency remaining aggregator-only
organizer gaps (13-18 events each). This release re-verified every one
of them live before writing any code.

### Research: zero new sources (an accepted outcome)

- **OCHO / Tango O Nada**: cross-referenced against the curated 나무위키
  탱고학원 (tango academy) index - neither appears as an independent
  teaching academy with its own community board. Both are rented venues;
  the recurring events held there are organized by other communities
  that are either already registered (Solo Tango -> SRC-D-003) or
  private (Milonga Casa's own Facebook *group*, confirmed via 나무위키
  밀롱가 as 까사밀롱가's real organizer - login-required, REJECT,
  unchanged from v0.85.1's own finding for the same group).
- **PISTA**: a new lead this round (tangoinkorea Daum Cafe) redirects
  straight to `logins.daum.net` before any list content loads - fails
  the ADD_NOW gate immediately.
- **Tango Andante**: no independent site found beyond its already-known
  Facebook page (REFERENCE_ONLY, unchanged from v0.85.1).
- **EN PAZ**: no official homepage, cafe, blog, or even a distinct
  social page found at all - genuinely nothing to classify beyond REJECT.

`docs/tango_direct_source_candidates.csv` updated with six new
reverification rows (CAND-TANGO-031 through 036) - existing conclusions
preserved, not overwritten. Zero new sources is the honest result, not a
shortfall: Section 58/Section 57 of this release's own spec explicitly
treat this as an acceptable outcome when no candidate actually clears
the public/no-login/Terms-clear/current-event bar.

### A real UX defect fixed: DJ shown twice

Found live in v0.85.2's own post-release audit (event_id 221245,
SRC-D-003): a raw post title already spelling out "(DJ : 유진)" as free
text, plus the structured `dj` field the engine has always extracted,
rendered as two separate things - "...(DJ : 유진) (DJ 유진)".
`runtime.public._title_already_announces_dj()` now skips the display
badge only when it would repeat the title verbatim (label spacing/case/
colon/parens normalization only - no fuzzy name matching), so a
genuinely different DJ named in the title stays visible as a real
conflict signal rather than being silently hidden. Neither the raw
title text nor the stored `dj` field is ever modified - this is a
display-only fix, confirmed against the exact real production data that
first showed the bug.

### Coverage

Unchanged by this release's own actions (no new source, no reprocessing):
10/159 (6.3%), same as v0.85.2's own converged measurement - the small
denominator drift is normal event-count churn over time, not a
regression. Still one MULTI-TIER event (Solo Tango).

### Tests

12 new tests for the DJ-display fix (title-already-announces-dj in
several label spellings, no-mention shows the badge, a genuinely
different DJ is never hidden, raw title/data never mutated, plus
supporting unit tests for the detector itself and two timeline
regression checks). No new source-handling tests this release - no new
source code was added; the existing dedup/representative/conflict/
calendar/historical guarantees remain covered by v0.85.1/v0.85.2's own
test suites. Full Runtime suite on staging: 1466 passed, 15 skipped
(only the 2 pre-existing, unrelated `test_tangocalendar_discovery.py`
failures remain, same baseline as every prior release).

## v0.85.2 Direct Source Depth + Primary Evidence Convergence

Status: real live production representative-source flip confirmed
organically, pagination regression found and fixed, 2026-09-08.

Version split:

- Product Runtime: 0.85.2
- Information Engine: 0.83 (unchanged)

### Goal

Not new source count - making the two sources v0.85.1 already added
actually converge reliably: SRC-W-006 must not lose event posts to
pagination, and SRC-D-003's real events must keep winning representative
status over DIRECTORY duplicates the way the architecture already
promises.

### A real regression found and fixed: SRC-W-006 event-window collection

v0.85.1's `tangoclass_discovery.py` only ever asked for the single most
recent 10 posts. A live re-check roughly 30 minutes after the original
live-acceptance test found a real event post ("9월~10월 스페셜 원데이 클래스")
had already scrolled off that window - pushed out by two unrelated
educational-article posts published in between. `discover()` now pages
backward with three independent stop conditions - an empty page, a page
whose oldest post already predates `lookback_days` (default 30), or
WordPress's own `X-WP-TotalPages` header - plus a hard `max_pages`
ceiling (default 5) that applies regardless of what any of those say, so
a site that lies about (or omits) its own pagination headers can never
turn this into an unbounded crawl. Confirmed live against the real site:
the specific previously-missed post is now found (`MISS_CONFIRMED`), and
a forced 5-page/50-post crawl completed in 4.1s with 0 duplicate post
IDs across pages.

### Confirmed live: the representative-source flip actually happens

Production's own scheduler organically merged the real "Solo Tango
화요정모" event: Miltang's DIRECTORY-tier post (event_id 88436) folded
into SRC-D-003's own COMMUNITY/PRIMARY-tier post (event_id 221245) as
canonical - no manual intervention, just the existing dedup pipeline
doing what it was designed to do once the direct post's body finished
enriching. The DIRECTORY post's evidence stayed retained
(`duplicates.sources_of()` still returns both); the representative's own
`source_link` points at the real original post
(`cafe.daum.net/latindance/73b/68727`), not a directory link; freshness
reflects the direct source's own `collected_at`; DJ ("유진") is shown,
extracted from the direct post; fee stayed honestly unknown (the real
post states a two-tier "8,000원(22시 이후 5,000원)" fee, which the existing
v0.84.1 multi-tier-fee safety correctly declines to reduce to one
number); status stayed POSSIBLE, never auto-promoted to VERIFIED.

### New KPI: Multi-tier Evidence

`runtime.source_ops.evidence_tiers()` (Section 22/23) - for every visible
upcoming event, which tier(s) of evidence exist across it AND its folded
duplicates, not just the representative row's own tier. Wired into the
admin Source Priority panel. The Solo Tango event above is exactly what
this counts: one real event now carrying both PRIMARY and DIRECTORY
evidence - the concrete "directory discovery -> official confirmation"
convergence signal this whole effort has been working toward.

### New sources this release: 0

EL TANGO's board showed no current/near-upcoming milonga with full date/
time/venue this round (stays ADD_LATER). IGNOX's real "가을 숲 밀롱가" event
is genuine but Nov-dated, outside the Sept/Oct window this release
required for ADD_NOW (stays ADD_LATER/MONITOR). KCCTF (2026-10-03~05,
OFFICIAL_PRIMARY, robots ALLOW) has real live value but its site is
Next.js App Router with RSC streaming payloads (`self.__next_f.push(...)`),
not the `__NEXT_DATA__` JSON shape `danceinfo_discovery.py` already knows
how to read - confirmed live via the real page source. Building a
structurally-safe parser for that (Section 30's own explicit ban on
regex-scraping the raw stream) is real work disproportionate to one
annual festival; deferred rather than rushed. Zero new sources is an
accepted outcome this release (Section 31) - the actual goal (SRC-W-006/
SRC-D-003 convergence) was met without one.

### Coverage

Before: 5/153 (3%, v0.85.1's own baseline). Continued organic convergence
observed since: 6/154 -> 7/149 -> 10/158 (~6%) as SRC-D-003's remaining
post bodies finished enriching, entirely from the two v0.85.1 sources -
no new source contributed to this. Not a target number; reported honestly
as measured at deploy time.

### Tests

34 new tests: 12 WordPress pagination unit tests (page1/page2,
X-WP-TotalPages, max-pages bound, empty-page stop, duplicate-post-id
dedup, stale-page stop, event-context isolation, request-failure
propagation, regression guard for the original single-page behaviour) +
10 direct-convergence tests (re-anchored to the real production Solo
Tango scenario) + 3 evidence-tiers KPI tests, plus supporting fixture
tests. Full Runtime suite on staging: 1454 passed, 15 skipped (only the
2 pre-existing, unrelated `test_tangocalendar_discovery.py` failures
remain, same baseline as every prior release). Engine suite not
re-run - no `engine/` file changed.

## v0.85.1 Direct Source Coverage Expansion

Status: real live source research and re-verification, 2 sources added
(disabled-first, live-tested, gate-passed), 2026-09-08.

Version split:

- Product Runtime: 0.85.1
- Information Engine: 0.83 (unchanged - no `engine/` file touched)

### Goal

v0.85.0 measured Direct Source Coverage (PRIMARY + PROMOTION_BOARD share of
upcoming Tango) at 5/147 = 3%: nearly all upcoming coverage came from
re-aggregating services, not from a community's, organizer's, or studio's
own posting. This release moves from "Directory tells us the event exists"
toward "we hold the community's/organizer's own original post" for a real,
verified handful of cases - not a target number.

### Research

30 candidates investigated (`docs/tango_direct_source_candidates.csv`),
prioritizing v0.85.0's own Aggregator-only gap list (대전탱고/LaBoom, 부산탱고/
이데알, La Ventana, O Nada, Andante, EN PAZ, 탱고 클럽 오초) plus a broader
sweep of official homepages, Naver/Daum cafes, blogs, and Facebook pages.
Every ADD_NOW candidate was independently re-fetched live (not trusted from
the candidate list alone) before any registration.

Most of the gap list's own organizers turned out to require a login-gated
cafe detail page or sit behind Facebook's Terms (automated collection
prohibited) - classified `REFERENCE_ONLY`, not force-implemented. Two real,
public, no-login, robots-allowing, currently-active sources survived:

- **SRC-D-003** - Solo Tango's own 화요정모 (Tuesday regular meetup) notice
  board, a *different* board (73b) on the same 'latindance' Daum Cafe
  SRC-D-001/002 already read. Reuses the existing DAUM_CAFE/Kakao Cafe
  Search collector completely unchanged - only a new Source Master row
  scoped via `url_contains`. Live-verified real post: 9/8, 20:00-23:30,
  Tango O Nada, DJ 유진, 8,000원(22시 이후 5,000원) - the exact event
  behind v0.85.0's own "Solo Tango 화요정모" gap entry.
- **SRC-W-006** - TangoClass's own public WordPress REST API
  (`/wp-json/wp/v2/posts`), robots ALLOW except `/wp-admin/`, no login. New
  `runtime/tangoclass_discovery.py` parser - the list response already
  carries each post's full body, so there is no separate detail fetch
  (`FETCHED_FULL`, the same shape as Miltang's own milonga list).

SRC-F-001/SRC-F-002 (Tango Club Ocho, Tango O Nada's own Facebook pages)
were re-checked: still `enabled=false`, still no collectible `url` in their
own config (`access_state: ACCESS_LIMITED`, imported from
`engine/config/sources.json` with no real target). Facebook's own Terms
prohibit automated collection - confirmed again this release, left
`REFERENCE_ONLY`, not enabled.

Both new sources registered **disabled**, per this project's standing
practice: a migration registers a row, an operator tests then explicitly
enables it - never auto-activated.

### Live E2E audit (Section 37/38's Enable Gate) before enabling

Both sources' one-shot live test (the admin [Test] button function itself,
`collectors.test_source()` - writes nothing) passed on real data: SRC-D-003
found 49 real posts on the real board (Kakao Cafe Search API, via
production's own credential, in-memory only, no DB write); SRC-W-006 found
10 real posts via its own new parser.

Enabling SRC-W-006 on a genuinely fresh staging Postgres (the first time
this project has ever exercised a truly *empty* candidate store at the
moment the scheduler's `event-normalization` job runs) surfaced a real,
pre-existing bug: `normalization.normalize_all()`'s zero-candidates early
return omitted `unresolved_venues`/`pruned`, crashing the job with
`KeyError`. Not caused by the new sources - unreachable in every prior
release, since production always has hundreds of pending candidates by the
time this job runs. Fixed (both keys now always present) and covered by a
regression test. The real E2E run then completed cleanly: 10 collected ->
10 ingested -> 5 real event candidates -> 2 normalized events (the other 3
correctly skipped for having no explicit date - not fabricated), 0 errors.

### Tests

23 new tests: migration registration (2 sources, idempotent, existing
sources untouched), the 15 required release-gate behaviors (primary/
promotion-board ingestion, directory-duplicate recognition, PRIMARY-wins
representative source, DIRECTORY evidence retained after a merge, direct
source link, direct freshness, no fee/DJ inheritance across recurring
instances, a conflicting pair still stays CONFLICT regardless of source
tier, PRIMARY never implies VERIFIED, calendar counts a merge once,
historical events stay queryable, a disabled source is never selected for
collection, a failed live test never auto-enables), the `normalize_all()`
regression, plus `tangoclass_discovery.py`'s own 11 parser unit tests.
Full Runtime suite on staging: 1424 passed, 15 skipped (only the 2
pre-existing, unrelated `test_tangocalendar_discovery.py` failures present
on every prior release's baseline remain). Engine suite not re-run - no
`engine/` file changed.

### A second real bug found along the way

`.env.example` and both `docker-compose.yml`s' image-tag defaults had
drifted to `0.84.4` since v0.85.0's own version bump - nothing checks the
template against `VERSION`, the same class of gap `test_env_example_
engine_version_matches_the_default` already guards for `ENGINE_VERSION`.
Fixed alongside this release's own version bump (retroactively correcting
v0.85.0's oversight too).

## v0.85.0 Private Alpha Pilot: Compact Timeline + Weekly Calendar + Source Priority

Status: Private Alpha pilot release, real live production data verified,
2026-09-08.

Version split:

- Product Runtime: 0.85.0
- Information Engine: 0.83 (unchanged - no `engine/` file touched this
  release, confirmed via an empty `git diff main feature/... -- engine/`)

### Goal

A dancer opening the app should be able to see, within a few seconds, where
to dance today or this week. The event list moves from a large card per
event to a compact, 2-3 line, Twitter/X-timeline-style row, paired with a
Monday-start weekly calendar for at-a-glance day-by-day browsing.

### Compact Timeline

Every row is exactly two lines by default, a third line only when there is
a source link and/or a confirmation time to show:

1. `[지역] 날짜 시간 종류` - region always first, "오늘"/"내일"/`9/12(토)`
   date labels, "시간 미확인" when the time is not known (never blank), the
   event type translated to Korean.
2. `행사명 (DJ) 입장료: ..` - event name is the visual anchor; DJ appears in
   parens only when the Information Engine actually extracted one; fee is
   "무료" / "20,000원" / "미확인".
3. `출처: 이름 ↗ (확인시간)` - the source name IS the link to the original
   post (or the aggregator's own page when no direct original is known);
   confirmation time is derived from the real `source_items.collected_at`
   evidence timestamp, never a page-render time.

A past date's events keep rendering with a "종료" badge rather than
disappearing - history is never hidden by deleting it, only by the existing
upcoming-list filter not showing past dates by default.

### Weekly Calendar

A 7-day, Monday-start week strip above the timeline. Each day cell shows
weekday + day number + a real event count for that day (respecting the
current region/genre filter, and counting a duplicate-merged event once,
via the pre-existing `canonical_event_id IS NULL` visibility gate - no new
de-dup logic needed). Past days stay clickable and show their own real,
preserved historical events; today is marked; prev/next week navigation
never removes a day from view. Backed by one new `events_api.week_counts()`
query (a single grouped query, not seven per-day queries).

### DJ field

The Information Engine has always extracted a DJ name
(`extractor.DJ_RE`/`EventCandidate.dj`), but nothing downstream ever read
it: `runtime.candidates.list_candidates()`'s own SELECT never named the
column, so it was silently dropped before `normalize_candidate()` ever saw
it. Closed end-to-end this release (migration 026 adds `events.dj`,
`candidates.py`'s SELECT and `normalization.py`'s values dict both now
carry it through) - not a new extraction feature, a pipe that was already
there and is now connected.

### Source Priority (display/ranking only - not a new verification path)

`runtime/source_priority.py` derives a three-tier display ranking
(PRIMARY / PROMOTION_BOARD / DIRECTORY) from the existing
`sources.source_role` column - no new schema. PRIMARY = ORGANIZER, VENUE,
COMMUNITY roles (a community's or organizer's or studio's own posting);
PROMOTION_BOARD = the PROMOTION_BOARD role; DIRECTORY = DIRECTORY and
AGGREGATOR roles (Miltang, TangoNOW, Tango Calendar Korea, DanceInfo -
re-aggregating services, never excluded, only ranked last).

Used as a **tiebreak only**, never a primary key: in
`duplicates._canonical_of()` it is consulted after `completeness()`, so a
sparser-but-more-authoritative post can never suppress a richer aggregator
post's actual field data; in `events_api.search()`'s `ORDER BY` it is
consulted after date/time. Source priority never implies `VERIFIED` -
that stays governed entirely by the pre-existing, unrelated
`engine.verifier` evidence rules.

A real, deliberate divergence from this spec's own illustrative example:
the spec's Section 1 suggested classifying K-TANGO (SRC-W-001) as a
PROMOTION_BOARD-tier example. K-TANGO's real, already-recorded
`source_role` in production is `ORGANIZER` (`authority_level =
PRIMARY_ORGANIZER`), and its own `notes` field (set in an earlier release)
literally reads "Korea Tango Community and Festival organizing committee
board" - it is the tango festival organizing committee's own board, a
genuinely direct/primary source. The real database value was trusted over
the spec's illustrative guess, consistent with this project's standing
practice of verifying against real data rather than assuming.

### Minimal feedback

An event's detail page carries three buttons - "정보가 정확해요" /
"정보가 달라요" / "정보가 부족해요" - writing to a new, anonymous,
`event_id`-keyed `event_feedback` table. Deliberately separate from
`human_review_actions` (an operator's own audited correction log): this is
a public signal only, and by construction never mutates an event by
itself - only the existing, audited Human Review path can change data.

### Live production verification (2026-09-08, read-only)

- 147 upcoming visible events; by source tier: PRIMARY 4, PROMOTION_BOARD
  1, DIRECTORY 142 (of which AGGREGATOR 23, plain DIRECTORY 119) -
  **Direct Source Coverage = 5/147 = 3%**. This is the release's key
  finding: nearly all upcoming coverage today comes from re-aggregating
  services, not from community/organizer/studio postings directly.
- A real, tier-crossing representative-source example exists in
  production: event 13697 ("...밀롱가 La Vida No.800 DJ 로띠", role
  PROMOTION_BOARD) is already the live canonical/representative event over
  a DIRECTORY-tier duplicate (50824, "Milonga La Vida") folded into it.
  That specific merge decision predates this release's tiebreak change
  (made under the pre-existing completeness-only logic), but the real
  outcome already matches the new priority ordering, and the new tiebreak
  additionally makes this the enforced behavior going forward wherever
  completeness alone would otherwise tie.
- 8 real timeline rows and a real past-date (2026-09-07, 6 events)
  rendered correctly via the actual `public._timeline_line1/2/3`
  functions against real data - see the full acceptance report for exact
  samples.

### Tests

62 new tests (19 Timeline, 15 Calendar, 7 Source Priority, plus DJ-flow,
feedback, and `source_priority` unit tests) in
`tests/test_v085_timeline_calendar.py`; 3 pre-existing
`tests/test_public_pages.py` tests updated to match the intentional card
-> timeline redesign (source-link markup, no-link-when-nothing-to-show,
freshness wording) - each verified to preserve its original intent, not
weakened. Full Runtime suite on staging: 1397 passed, 15 skipped, 2 failed
(both pre-existing, unrelated `test_tangocalendar_discovery.py` failures
present on every prior release's baseline in this session). Engine suite
not re-run - no `engine/` file changed.

## v0.84.4 Image-aware Event Classification + OCR Evidence Promotion

Status: root-cause fix, generic (non-source-specific) design, real live
K-TANGO detect-only verification, 2026-09-07.

Version split:

- Product Runtime: 0.84.4
- Information Engine: 0.83 (up from 0.82) - `classifier.classify_with_
  image_evidence()` (new) and `live_pipeline.process_discovered_post()`
  (now calls it) changed.

### Goal

v0.84.3 closed the two structural gaps that discarded an image-only post's
poster before OCR ever got a chance at it, but left the actual classification
gate untouched: `process_discovered_post()` called `classify(title, body)`
- title and body alone - *before* ever looking at a post's `image_texts`.
An image-only post (empty body) always classified `OTHER` and returned
`events=[]`, regardless of how good its poster's OCR reading was. This
release closes that gate without redesigning the classifier or forcing
`image_texts` into it wholesale.

### Design

`classifier.classify_with_image_evidence()` is a second, stricter layer on
top of the unchanged `classify()`, engaged only when body text itself was
too thin to have decided anything:

- a text-rich post that already classifies as something other than `OTHER`
  is returned unchanged - an attached image is never consulted, let alone
  allowed to override a real, text-rich judgment;
- a body under 20 characters (mirroring `runtime.acquisition.
  MINIMUM_USEFUL_TEXT`) is what "too thin" means;
- an image must carry social/milonga context (not bare `CLASS`, not
  `OTHER`) **and** read a real date **and** (a start time or a
  LABEL-tagged venue) via the exact extractor every field-fill already
  trusts - a bare "밀롱가" with nothing else on the poster never promotes;
- a poster naming more than one distinct date (a multi-day schedule table)
  never promotes anything - which program the post even announces is not
  decidable from it, and no candidate is safer than a guessed one.

The runtime-side gate feeding it, `image_fallback.
gather_trusted_classification_texts()`, is a DB-read-only, stricter subset
of whatever `gather_image_texts()` already fetched/OCR'd: not classified
`LOGO` by `media_classifier.classify_media()`, and at least 20 characters.
It changes nothing about the existing, more permissive field-fallback path
(`extract_with_image_fallback()`'s `image_texts`) - only classification
gained a second input. Wired into both `ingest_pending()` and
`reprocess_acquired()`, so a genuinely image-only post is reachable from
either entry point.

The existing IMAGE_OCR-excludes-VERIFIED rule (v0.81.3) needed no change:
any event whose fields came entirely from a poster already carries
`IMAGE_OCR` evidence for date/time/fee, which `verifier._text_evidenced()`
already excludes from `core_complete` - so an image-classified event stays
`POSSIBLE` by the same structural rule, automatically, with nothing new to
verify.

### A real bug found along the way

`content_store.needing_reprocess()`'s query never selected the source
item's own discovery-time title at all. `source_item_content` happens to
carry its *own*, unrelated `title` column (the fetched page's own parsed
title - NULL for anything never fetched, most obviously a `FETCH_BLOCKED`
row), which Python's column-name dict-building let silently stand in for
it with no error. Every post `reprocess_acquired()` ever built therefore
had `title=""`, invisible before this release because `classify()` from
body text alone never needed the title to already hold a real value - it
becomes load-bearing the moment a poster's own keyword needs a title to
combine with. Fixed by selecting `i.title AS source_item_title` explicitly
and falling back to it in `_to_raw_post()`.

### Verification

- 22 new tests: the 8 required control fixtures (text-rich/image-only-
  real-event/image-only-class-ad/generic-poster-missing-signal/logo-only/
  unrelated-chrome/old-archive-flyer/multi-date-poster), `known_event_type`
  short-circuit, the title-fallback fix, the trusted-texts DB gate (LOGO
  exclusion, minimum length, real-poster inclusion), a synthetic 647-shaped
  recovery through `reprocess_acquired()`, and never-VERIFIED-alone.
- Full Runtime suite (board staging, isolated PostgreSQL): 1337 passed, the
  same 2 pre-existing unrelated failures (`test_tangocalendar_discovery`).
  Engine suite: 794 passed, 0 failures.
- **Live detect-only against all 10 real K-TANGO items** (read-only: cached
  OCR text plus one genuine, DB-write-free re-fetch for the one item with no
  cached attempt yet; full detail per item logged). Result: **zero new false
  candidates, zero wrong fills** - and an honest, per-item reason for every
  one of the four items this release still cannot recover:
  - **643**: a real multi-program festival schedule (`VIP 밀롱가 1/2/3`,
    a separate performance slot, several venues). A date resolves cleanly
    (only one date pattern appears), but the multi-signal gate correctly
    refuses anyway - the OCR'd times are all stranded by the table's own
    line-wrapping (no clean `HH:MM-HH:MM` reads), and no venue is
    LABEL-tagged. This is the gate protecting against exactly the
    multi-program risk Section 15 describes, just not via the explicit
    multi-date check (only one date happens to OCR cleanly here).
  - **647**: the item behind v0.84.3's own incident. Its poster's OCR is
    heavily garbled (stylised festival typography - `"S@CIl Ey YY & PES
    TI VAL"`, `"뚜벅뚜벅 축저"`) and contains no clean social/milonga
    keyword at all. A genuine OCR-quality limit, not a design gap; its
    existing event (21912) is preserved, not deleted, by v0.84.3's guard.
  - **648**: OCR is actually clean here (`"Tango special Performance ...
    2024.09.26 19:00 - 20:30"`) - but it is a stage performance, not a
    social-dance milonga, and correctly does not classify as one under
    this project's own MILONGA/SOCIAL/CLASS taxonomy. Not a recall miss;
    a correct exclusion.
  - **649**: its poster still exceeds the 5MB fetch cap (a real, deliberate
    safety limit, unweakened) - unchanged since v0.84.3's own inventory of
    this exact item.
  - 645/646 (real, already-existing events) and 642/644/650/651
    (real non-events) are all unaffected - confirmed byte-for-byte via the
    same detect-only pass.
- Because production currently has zero items eligible for reprocessing
  (`needing_reprocess()` returns empty system-wide, unchanged since
  v0.84.3's own final stable state), this deploy has **no immediate effect
  on any existing candidate or event** - confirmed, not merely expected.
  The benefit is the closed architecture gap itself, proven safe against
  real, messy, real-world OCR data, and reachable by any future post whose
  poster does carry the required clean, multi-signal evidence.

### Also fixed

`.env.example`'s `ENGINE_VERSION` had drifted to `0.81` through both
v0.84.2 and v0.84.3 (real `DEFAULT_ENGINE_VERSION` bumps neither release's
own version-bump step caught, since nothing checked the two against each
other). A production `.env` is hand-edited at deploy time regardless, so
production itself was never affected - but the checked-in template is what
every fresh `.env` starts from. Fixed, and a new test
(`test_env_example_engine_version_matches_the_default`) guards it from
drifting again.

## v0.84.3 Image-only Poster OCR Recovery + K-TANGO Evidence Extraction

Status:
Root-cause audit, generic fixes, and detect-only verification against the
real live K-TANGO site and the ROCKPro64 board's real production database,
2026-09-07. A real data-loss incident surfaced and was closed during
rollout (see "Incident during rollout" below) - production is stable as of
the final redeploy, verified across 3+ scheduler cycles.

Version split:

- Product Runtime: 0.84.3
- Information Engine: 0.82 (up from 0.81) - `extract_with_image_fallback()`
  and `extract_fee()` changed.

### Goal

v0.84.2 fixed K-TANGO's navigation-contamination bug but left 6 of its 10
posts `FETCH_BLOCKED` - most of them genuinely image-only posters with no
caption text. The existing v0.81.3 OCR fallback pipeline (image download
safety, Tesseract kor+eng, PII scrub, cache-by-hash, "OCR alone never
VERIFIED") was already sound; this release's job was to find out why it
never even reached these posts, and close that gap without redesigning the
pipeline itself.

### Root cause

Two structural gaps, not an OCR problem:

1. `runtime.acquisition.fetch()`'s `FETCH_BLOCKED` branch never populated
   `images` - a real poster's URL was discarded the moment the body came
   up empty, even though the already-downloaded HTML plainly contained it.
2. `content_store.needing_reprocess()` (the query the scheduler's
   `engine-reprocess` job selects from) only ever considered
   `FETCHED_FULL`/`PARTIAL` rows, so a `FETCH_BLOCKED` row that did carry a
   poster candidate would never be handed back for image-only recovery.

### Fix

- Added `extract_content_images()`: scopes image discovery to the same raw-
  HTML content boundary `extract_article()` already trusts (the
  `template_board` `.readEdit` region), rather than the whole page - a
  poster inside it is found, the site's own nav/logo/footer images (outside
  the boundary) never are. Called for every fetch outcome, including
  `FETCH_BLOCKED`.
- Widened `needing_reprocess()`'s `WHERE` clause with a narrow `OR` branch:
  a `FETCH_BLOCKED` row is now also eligible for reprocessing when its
  `poster_candidates` is non-empty. A blocked row with no poster (a
  genuinely empty post) stays excluded - nothing new to give the engine.
  Still the existing scheduled job, still bounded, no ad-hoc reprocess call
  anywhere.
- Engine: `extract_with_image_fallback()` gains **venue** as a fourth
  fallback field alongside date/time/fee, per this release's priority
  order - K-TANGO's real posters are exactly the case where the body is
  empty and only the poster names the venue. Venue was never part of
  `core_complete`, so this cannot affect VERIFIED eligibility.

### A real wrong-fill found and fixed during testing

Writing the venue fallback's regression tests surfaced two genuine, pre-
existing extraction bugs, both fixed here:

- **Free parking suppressed a real, unrelated fee.** `_NOT_A_FEE`'s bare
  "주차" disqualified any amount within 20 characters of it - correct for
  "주차장 최대 7,000원" (a real parking price), wrong for "무료주차 가능
  입장료 13,000원" (a free-parking *notice* sitting near a genuine, clearly
  labelled entry fee). Narrowed the exclusion to leave a real parking fee
  excluded without also blanking out an unrelated real one nearby.
- **A bare known-studio-name match is unsafe on OCR text.** `extract_venue()`'s
  three hardcoded studio-name fallbacks (a convenience for short body text)
  wrongly picked a venue out of K-TANGO's real "서울 밀롱가데이" poster - a
  schedule table naming ~15 participating studios across two days, one of
  which happened to be one of the three names. `extract_with_image_fallback()`
  now only trusts an *image's* venue reading when `extract_venue()` actually
  labelled it ("장소: ..."); body-text venue reading is unchanged.

### Verification

- **Real live image inventory** (all 6 `FETCH_BLOCKED` K-TANGO posts,
  read-only): 4 have a genuine attached poster fetchable under existing
  safety limits, 1 has no image in its content region at all (a truly
  empty post), 1 has a real poster exceeding the 5MB fetch cap (17MB - a
  real, deliberate safety limit this release does not weaken).
- **Detect-only against the real live site + real OCR**, all 4 fetchable
  posters: 2 (source_items 647, 648) yield a single, clean, correct date
  from unambiguous poster text ("2024.09.29", "2024.09.26") - both safe to
  apply. 1 (643) yields nothing at all - its poster is itself a multi-day
  schedule table dense enough that no field reads as a single clear value,
  a safe non-result. 1 (646, "서울 밀롱가데이") is the multi-studio listing
  above: after the venue fix, its venue correctly resolves to nothing, but
  its *time* still reads as one arbitrary participating studio's own slot -
  a real remaining risk building a "this is a multi-item listing" detector
  would be needed to fully close, which is out of this release's scope.
  **646 is excluded from this release's scoped production apply** (marked
  reprocessed without ever computing or storing that time), reported here
  rather than forced through.
- 22 new tests across both layers (20 from the initial pass, 2 added while
  closing the incident below): poster detection/scoping, chrome (logo/nav/
  footer) exclusion, image-less posts never OCR'd, `FETCH_BLOCKED` outcomes
  carrying their poster candidate, `needing_reprocess()`'s new eligibility
  (DB-integration, against real PostgreSQL), venue fallback fill/no-
  overwrite/conflict, the bare-known-name precision fix, the free-parking
  fix, multi-tier-fee ambiguity via image text, existing-source (Daum/
  DanceInfo/text-post K-TANGO) non-regression, the `reprocess_acquired()`
  preserve-not-delete guard, and its genuine field-recovery counterpart (a
  classifiable body missing only a fee, recovered from a poster).
- Full Runtime suite (board staging, isolated throwaway PostgreSQL): 1333
  passed, 2 pre-existing unrelated failures (`test_tangocalendar_discovery`,
  confirmed identical against an unmodified image before this change).
  Engine suite (unaffected by the post-merge fixes, which never touched
  `engine/`): 776 passed, 0 failures.

### Incident during rollout: `reprocess_acquired()` deleted a real event

Deploying the two structural fixes above and letting the scheduler's normal
`engine-reprocess` cycle run exposed a third, more serious, pre-existing bug
that neither fix had touched: `reprocess_acquired()` never wired
`image_texts` into `process_discovered_post()` at all (an `_extract_single`/
`_needs_fallback` import that was never actually used). Once
`needing_reprocess()` started selecting `FETCH_BLOCKED` rows with a poster,
this function re-extracted them with no image fallback, got zero events, and
hit its own unconditional "replace this post's candidates with whatever the
engine now makes of it" delete - silently wiping source_item 647's real,
previously-correct event.

Wiring `image_texts` into `reprocess_acquired()` the same way `ingest_pending()`
already had it turned out not to be enough by itself:
`process_discovered_post()` classifies from title+body alone, before it ever
looks at `image_texts`, and a `FETCH_BLOCKED` item's body is empty - so a
genuinely image-only post still classifies as `OTHER` and still produces
zero events, wiring or no wiring. Fixing that would mean changing what
`classify()` is allowed to see, which is out of this release's scope.

What is in scope, and what closes the incident at its root: zero events from
a `FETCH_BLOCKED` reprocess means "could not classify a blocked fetch," never
"the engine says this is no longer an event" - only the second claim should
ever trigger the delete. `reprocess_acquired()` now preserves existing
candidates instead of deleting them when a blocked re-fetch can't classify,
logged as `skipped_blocked` in the `engine-reprocess` job line. The existing
delete-and-replace path for a genuine rule correction (an actually-fetched,
non-blocked body that no longer classifies as an event) is untouched.

647's event was restored verbatim from the pre-deploy backup (all 29
columns, plus its engine-side `event_candidates`/`evidences` rows) rather
than re-derived, since its original value already had no OCR involvement.
Full K-TANGO audit and three clean `engine-reprocess` cycles after the guard
shipped confirm the system is back to a stable, `pending=0` state with no
further candidate loss.

### Net K-TANGO outcome: honest, not what was targeted

The two structural gaps this release set out to fix are fixed, tested, and
verified live. The incident above, and its restore, mean the specific
coverage win the "Verification" section above describes - 647 and 648 each
gaining a clean, single, poster-derived date - **did not survive into the
final production state** and was not reapplied. Every K-TANGO event now
live (645, 646, 647) still resolves its date from body text or
`published_at` fallback (`TEXT`/`EXPLICIT_YEAR`), not from OCR; no event
anywhere carries an `IMAGE_OCR` evidence type. 648 has no event at all,
matching its pre-release state.

This is consistent with this release's own stated priority - **Wrong Fill =
0 over coverage** - and no wrong value was ever shipped. But the honest
summary is: this release fixed the pipeline's structural bugs, fixed two
real extraction-precision bugs it surfaced along the way, and closed a real
data-loss bug it caused - all durable, real wins - while the K-TANGO
poster-OCR coverage gain itself did not make it to production. Reaching it
without touching `classify()`'s body-only gate remains a real limitation of
this pipeline, and is left as documented, scoped-out follow-up work rather
than forced through by an ad-hoc write.

The wiring fix is not wasted, though: it is the entire reason a post that
*can* classify from its own body - the original, more common v0.81.3 case,
still a real body missing only a field - now also gets image-fallback
recovery when caught by `reprocess_acquired()` and not just
`ingest_pending()`, which is what `engine/tests/test_image_fallback.py` and
`tests/test_image_poster_ocr.py`'s fee-recovery test verify.

### Also fixed

`.env.example` and both compose files' `DANCEMATE_VERSION` fallback were
still `0.84.1` after v0.84.2 bumped `VERSION` - a gap in that release's own
version-bump step, caught by a fresh full local suite run. Production was
unaffected (`deploy-production.sh`'s preflight guard already requires a
match before it will build); the tracked defaults are now correct.

## v0.84.2 K-TANGO Content Acquisition Repair + Source Health Recovery

Status:
Root-cause audit and generic extractor fix verified against the live
K-TANGO site and the ROCKPro64 board's real production database, 2026-09-07.

Version split:

- Product Runtime: 0.84.2
- Information Engine: 0.81 (unchanged) - no engine code touched.

### Goal

K-TANGO (SRC-W-001, the first WEB-platform source, registered v0.81) was
storing its site's own navigation menu as event bodies for a majority of its
posts. Re-collect K-TANGO's real content reliably against the site's current
structure, and stop navigation/menu text from ever being stored as a body.

### Root cause

`runtime.acquisition.extract_article()` correctly locates K-TANGO's real
`<div class="readEdit">...<div class="readBottom">` content boundary on every
page - the site's own template has not changed since v0.81's onboarding. But
when a post's real content is a poster image with no caption text, the
located segment's text falls below `MINIMUM_USEFUL_TEXT`, and the function
fell through every remaining marker check to a whole-page `visible_text()`
fallback - which includes the site's entire nav/header/footer chrome (an
unrelated, oddly dental-clinic-flavored leftover admin template the site was
built on). That whole-page text was long enough to be accepted and stored as
`FETCHED_FULL`.

Confirmed in production: **6 of K-TANGO's 10 live posts (60%)** were affected
- source_item_ids 643, 644, 646, 647, 648, 649, all via `visible_text`, all
~720-735 characters, all starting with the same site-menu boilerplate. Two of
these (646, 647) had already produced real `events` rows with a contaminated
body. Discovery itself was never the problem: all 10 real live posts were
already found and stored (`last_status='PASS'`); this was purely a content
extraction defect, not a stale site or a missed post.

### Fix

`extract_article()`: once the `template_board` boundary is found, never fall
through to the whole-page fallback - it can only ever re-grab that same
template's own chrome. A thin or empty scoped result is still returned under
`METHOD_TEMPLATE_BOARD`; `fetch()`'s existing FULL/PARTIAL/BLOCKED length
thresholds classify it downstream exactly as they classify any other thin
body (an image-only post with no caption becomes `FETCH_BLOCKED`, not a false
`FETCHED_FULL`).

Also added a generic chrome guard on the last-resort whole-page fallback
itself (digit-free, short-token-dominated text is refused as an article body)
so a WEB source with no known template still cannot have its own nav/menu
accepted as a real body. No `if source_id == ...` branching anywhere; both
changes live entirely inside the shared extraction abstraction.

### Verification

- **Detect-only against the real live site**, all 10 current K-TANGO posts:
  0 False Body Gate failures. The 6 previously-contaminated posts now
  correctly report `FETCH_BLOCKED` (their real `readEdit` content is
  genuinely empty/image-only); the 4 real-content posts (including the one
  with real date/venue/fee text) are unaffected.
- robots.txt: `http://www.k-tango.net/robots.txt` returns 404 (no
  restrictions); the registered source config already uses plain HTTP
  (`www.k-tango.net`'s HTTPS certificate is misconfigured for an unrelated
  domain - a real site-infrastructure issue, but not one this collector was
  ever exposed to, since `SRC-W-001`'s config already used `http://`).
- 15 new tests: board list parsing, detail link parsing (the site's title
  cells use `onclick`, not `<a href>` - already handled correctly),
  navigation/sidebar/footer exclusion, neighbouring-post isolation, Korean
  (and non-UTF-8-declared) charset handling, menu-only rejection, a
  short-real-post false-positive guard, duplicate-URL/pagination stability,
  and existing-source (Daum/DanceInfo) non-regression.

### Production repair and one-shot collection

Scoped repair (allow-listed to the 6 confirmed-contaminated source_item_ids,
guarded against running anywhere but the real production database, no
`normalize_all()`/`ingest_pending()`/`reprocess_acquired()` call anywhere in
the script per the v0.82.2 safety rule): re-fetched via
`scheduler.acquisition_job.reacquire()`, the same function the admin console
already uses. All 6 now correctly report `FETCH_BLOCKED` - their real content
is genuinely empty, so nothing false is stored in its place. The two
already-existing `events` built from these items (21912, 21913) were audited
directly: `venue_text`/`fee`/`start_time`/`end_time` were `None`/`ABSENT`
before and after - the contaminated body never actually fed a wrong field,
only occupied storage, so no event data changed and none needed to.

K-TANGO's own next scheduled collection (10-post board, `SRC-W-001`, running
production code): **10 discovered, 0 new, 0 revised, 10 duplicate** - fully
idempotent against the confirmed-real 10 live posts. Observed 5 consecutive
scheduler cycles after deploy: 0 errors, stable candidate/event counts, no
duplicate explosion, no requeue loop.
- Full Runtime suite (board staging, isolated throwaway PostgreSQL): 1316
  passed, 2 pre-existing unrelated failures (`test_tangocalendar_discovery`,
  confirmed identical against the unmodified v0.84.1 image before this
  change). Engine suite: 763 passed, 0 failures, Engine unchanged.

### Freshness conclusion

**A. ACTIVE_AND_FIXED.** The site is live and actively serving real content;
the collector already discovers everything real on it. The code defect is
fixed. Any remaining thin/blocked results reflect the site's own genuinely
image-only posts, not a bug - fee/venue OCR recovery for those posters is out
of this release's scope (Section 23/24), matching v0.84.1's own precedent of
not folding an unrelated extraction gap into a content-acquisition release.

## v0.84.1 Fee Extraction Coverage Improvement

Status:
Root-cause audit and safe generic fixes verified against the ROCKPro64
board's real production database, 2026-09-07.

Version split:

- Product Runtime: 0.84.1
- Information Engine: 0.81 (up from 0.80) - `extract_fee()` changed.

### Goal

Fee was the largest known gap after v0.84.0 (6% coverage, 7/119 upcoming
Tango events). Find where a real source actually has a price and the engine
is missing it, and raise coverage only there - never by guessing, never by
copying a price from another event or a previous occurrence.

### What the audit found

A full read of all 112 fee-unknown upcoming Tango events against their real
stored source text, cross-checked against `tangonow_discovery.py`'s own
Firestore field mapping:

- **107 events (96%) genuinely carry no price anywhere in their source.**
  Miltang (92) and TangoNOW (17, minus the 4/21 that already have a price
  because the collector already reads TangoNOW's own `price` Firestore
  field into the body when present) are discovery directories that point to
  an external event, not the event's own page - their listing template has
  no fee field to miss.
- **2 events are a real, single recurring practica's own 3-tier package
  price** ("10만원(2달, 8회), 6만원(1달, 4회), 당일 현장 2만원(1회)") - a
  genuine fee exists, but picking any one of the three tiers, including the
  single-visit walk-in price, would still be guessing which of three real
  numbers the post meant.
- **2 events (one in scope, one on an out-of-scope Daum source) are a real
  advance/door price** ("예매15,000/현매20,000") - genuine, but a case
  Section 17 explicitly forbids collapsing to one number.
- **1 event** used a content-acquisition fallback (`og_description`, a
  truncated SEO summary) instead of the real page body - a real gap, but in
  *content acquisition*, not fee parsing; noted as a follow-up rather than
  fixed here (Section 62: do not fold an unrelated extraction gap into this
  release).

**Recoverable gap via safe, generic means: 0 of 112.** This is the honest
finding this release's own instructions asked for, not a shortfall of
effort - Section 6 warned against picking a coverage target before knowing
the real denominator, and the real denominator turned out to be zero. A
detect-only run of the new parser against all 112 events' real stored text
confirms this empirically: 0 would newly resolve to a fee.

### Fixed anyway, because the absolute principles require it independent of today's data

- `extract_fee()` could not read Korean 10,000-unit notation at all
  ("2만원", "1.5만원") - now judged by the same label/event-context tiering
  as a plain "20,000원".
- Free admission was never recognised, at any amount - added a narrow
  phrase match ("입장 무료", "무료 입장", "참가비 없음", "무료 참가", a fee
  label immediately followed by "무료", "free admission"/"free entry") that
  cannot structurally match "무료주차"/"무료 음료" (the phrase always pairs
  무료 with admission itself, never an unrelated noun).
- Added a package/session-tier exclusion so the new 만원 reader does not
  wrongly attach a multi-month package price to a single practica listing -
  verified against the one real live post that has both a 만원 price and
  multiple tiers side by side; without the guard it would have picked
  100,000 for a single session.
- Found and fixed a real regression against the refactor's own intent along
  the way: a pre-existing test (a bare "밀롱가 2026" must never become a
  13,000-style fee) started passing as a fee once the digit-length gate was
  restructured per-amount-shape - the original code only ever accepted an
  unsuffixed number through a fee *label*, never through the event's own
  name, and that had to be preserved exactly, not just the digit count.

### Also in this release

`scripts/backup.sh` no longer aborts the whole backup when retention
pruning cannot remove one specific old directory - found live, again: two
backup directories from before the board's operator-only SSH policy remain
root-owned, hammer has no root to reclaim them, and deleting them is not
permitted. A cleanup failure now warns and moves on instead of reporting a
backup that actually succeeded as failed. (`BACKUP_RETENTION` was raised
again, 12 -> 16, as a stopgap for this release's own backup step, run
before the fix above was live in production; the fix itself is permanent.)

### Result

- Overall Fee Coverage: 7/119 (5.9%) -> 7/119 (5.9%), unchanged - no real
  production event qualified for a safe automatic fill.
- Recoverable Fee Coverage: 0/0 identified as safely recoverable.
- Wrong Fee: 0. No event's fee changed.
- No schema change, no new migration.
- Date/Time/Venue/Region/Source/Status coverage and the 포항/대구/청주/
  진주/광주 region counts unchanged - this release did not touch that code.

### Next recommendation

The two genuinely-ambiguous clusters (advance/door; package tiers) and the
one content-acquisition fallback are real, now-documented gaps outside what
a single-value `fee` column and a "never guess" parser can close - closing
them further would need either a schema change (Section 30 explicitly asked
not to build one this release) or a human-review path for ambiguous prices,
which does not exist today. Recommended as the next fee-related release's
starting point, once more real cases accumulate (Section 27: never resize
a threshold or a scorer off of n=1-2).

## v0.84.0 Tango Private Alpha Readiness

Status:
User-facing readiness audit and fixes verified against the ROCKPro64 board's
real production database, 2026-09-07. Engine code unchanged (0.80) - this
release does not touch Source pipelines, Engine extraction, or Venue Master
data; it audits and fixes the existing User FE (`runtime/public.py`,
`runtime/events_api.py`) against the Private Alpha spec.

Version split:

- Product Runtime: 0.84.0
- Information Engine: unchanged (0.80).

### Goal

Not new sources, not engine changes, not venue cleanup: whether a real dancer
can look at DanceMate and, within 30 seconds, decide where to go tonight
without being misled.

### What the audit found already built

`runtime/public.py` and `events_api.py` were already substantially aligned
with the spec: today/tomorrow/weekend/this_week/upcoming tabs, genre and
region filters with live counts, honest "미확인" fields for time/venue/fee/
region individually, source provenance with a link back to the original
post, KST-correct date math (tested against the UTC/Seoul midnight
boundary), and a footer that names itself an alpha. Nothing here was
rebuilt; this release patches the real gaps found against it.

### Real production data audit (2026-09-07)

`engine_status` has only ever been `POSSIBLE` (251) or `VERIFIED` (1),
across all of production history - `CANCELLED`, `CONFLICT`, `UPDATED`,
`COMPLETED`, and `EXPECTED` have never actually fired. This release still
has to handle all of them correctly (Section 40: real code paths, exercised
with synthetic DB rows via `candidate_status`, not claimed as live samples
that do not exist). Separately: 2026-09-07 is a Monday, and production has
zero upcoming events in any region or genre for *today* specifically - a
real characteristic of the current source set's Monday coverage, not a
defect, and the sharpest possible live test of the empty-state path.

### Fixes

- A fee of exactly 0 now renders "무료", not "0원" (Section 24) - a real
  defect, though not yet observed live (no free event exists in production
  today).
- `STATUS_LABELS["UPDATED"]` used to share `VERIFIED`'s own label
  ("확인됨"). Fixed to "변경됨" - conflating the two would let an event
  whose fee just changed read as evidence-confirmed. `COMPLETED` was
  missing outright and fell back to "확인 필요" (backwards for something
  already over); added as "종료".
- `search()` now excludes `COMPLETED` from the default result the same way
  it already excluded `CANCELLED` (`include_completed=True` to see it
  anyway), with the matching addition on `GET /api/events`.
- `CONFLICT` gets its own "warn" tone on the status badge - previously
  identical to a plain `POSSIBLE` badge, failing Section 14's "recognisable
  at a glance." The label text ("정보 충돌") already carries the meaning on
  its own; colour is additional, never the only signal (Section 43).
- `VERIFIED`'s badge now carries a `title` attribute with the one-line
  explanation Section 12 asks for, instead of nothing.
- "진행 중" is shown only when a post gave both a real start and end time
  and the current Seoul moment genuinely falls between them (Section 23) -
  including the after-midnight case, and never guessed from a bare start
  time the way `time_confirmed` already refuses to.
- Freshness ("N시간 전 확인") is now shown on the list card, not only the
  detail page (Section 8/9 - it was already computed, just not placed).
- A card with time, venue, and fee all unknown at once is now flagged
  "정보 적음" (Section 28), so three "미확인" tags do not read with the
  same visual weight as an event a poster actually filled in.
- Empty states on both `/` and `/events` now offer concrete next actions
  (내일 보기 / 이번 주 보기 / 지역 전체 보기, built from whatever filters
  are already active) instead of a dead end (Section 27) - the home page
  already had a partial version of this; `/events` had none at all.

### Tests

36 new tests (Sections 53/54): status labels and tones, in-progress
detection including the post-midnight case, freshness-on-card, thin-card
flagging, empty-state next actions, `CANCELLED`/`COMPLETED` default
exclusion, `CONFLICT` visibility, and a chronological-ranking-is-never-
reordered-by-status guard (v0.84.0 does not add a personal-fit score -
Section 31 - so this locks in that the existing pure date/time sort stays
that way).

### Result

- No schema change, no migration, no Engine change.
- Venue Master, Unresolved Venues queue, and region search counts
  (포항/대구/청주/진주/광주 = 2/2/2/2/2) unchanged before/after - this
  release does not touch that data.
- All 5 sources (SRC-W-001..005) unchanged, enabled.

## v0.83.2 OCHO Verification + Gwangju Region Completion

Status:
OCHO evidence reviewed and closed by the user; Gwangju region added and
backfilled against the ROCKPro64 board's real production database,
2026-09-06. Engine code unchanged (0.80) - this release touches only
`runtime/` (region resolution) and the region master; no scorer/algorithm
logic changed, so no engine version bump applies.

Version split:

- Product Runtime: 0.83.2
- Information Engine: unchanged (0.80).

### OCHO ("스튜디오 오초" vs Master venue "OCHO")

Evidence gathered, read-only, in priority order (source body, source URL,
address, organizer, existing aliases, a web check): OCHO's own aliases
already include the bare "오초" (a real prior human decision), which is the
strongest positive signal - stronger than the fuzzy scorer's own 0.5/LOW
verdict, a known short-token-containment gap this release deliberately does
not fix (Sections 1/8/9: no threshold change from a single case). Against
that, the unresolved row's actual post carries no address, only "지역:
서울" and an event title mentioning "홍대"; a web check for the instructors
named in the post ("헝얏 & 화이") returned an unverified claim pointing at
a *different* real DB candidate ("린댄스연습실", a genuine Hongdae-area
venue with its own address) with no primary-source confirmation either way.

Classified **INSUFFICIENT_EVIDENCE** - not because there is no evidence, but
because what exists points two different directions and neither is
confirmed. Reported to the user rather than guessed; the user's decision was
**KEEP OPEN, no write**. Recorded as calibration data
(`test_studio_ocho_short_token_calibration_fixture`) for a future scorer
release, not acted on now. Venue Master and OPEN queue counts are both
unchanged by this decision.

### Gwangju Metropolitan City region (KR-GWANGJU)

Real evidence: Mi Vida tango studio (created during v0.83.1's Human Venue
Review with `region_id=NULL`, since this region row did not exist yet) has
a real, currently-collected Miltang address - "광주 동구 중앙로 162-1
5층" - confirming a real Source/Event already needs this region, the same
bar every prior region row in this project was added against.

`_REGION_BY_ADMIN` already mapped "광주" to `KR-GWANGJU` before this
release (added when the code was written, with nowhere to resolve to
since). Adding the row without a guard would have immediately created a
live collision with Gyeonggi-do's own, unrelated 광주시 (Gwangju-si, which
has no gu-level districts at all) the next time an address starting with
"광주시" was collected. Guarded everywhere the mapping is used - new
`venue_resolution._safe_admin_head()` (feeds `suggest()`/`prefill()`'s
`region_hint`), `guess_region_label()`, `terms_for_label()` - to trust only
an explicit "광주광역시", or "광주" immediately naming one of the metro's
own five gu (동구/서구/남구/북구/광산구). A bare "광주시 ..." or bare "광주
<dong>..." with no gu stays unresolved rather than guessed, on either side
of the collision.

Migration 025 adds the region row. `master_data.backfill_venue_region()` (new)
carries a venue's newly-assigned region onto its already-resolved events -
`update_venue()` alone only touches the `venues` row, and nothing re-reads
it later - scoped to `region_id IS NULL` events only, so an
already-correctly-resolved event is never overwritten by a later region
change for an unrelated reason. Applied once, by hand, to Mi Vida.

### Result

- Venue Master: 24 -> 24 (unchanged; OCHO stayed KEEP OPEN)
- Unresolved Venues OPEN: 10 -> 10 (unchanged)
- Mi Vida tango studio: `region_id` NULL -> KR-GWANGJU, its 2 resolved
  events carried along in the same call
- `events_api.search(region="광주")` now returns Mi Vida's events with
  `region_confirmed=True` (previously guess-only, unreachable before this
  region existed)
- Existing Seoul/Busan/Cheongju/Jinju/Changwon/Pohang/Daegu/Ulsan region
  resolution unchanged - covered by existing tests plus new tests confirming
  a Gyeonggi-do "광주시" address is never misread as Gwangju Metro

## v0.83.1 Human Venue Review Pilot + Venue Master Expansion

Status:
Human-approved review pass executed against the ROCKPro64 board's real
production database, 2026-09-06. Engine code unchanged (0.80).

Version split:

- Product Runtime: 0.83.1
- Information Engine: unchanged (0.80) - confirmed via `git diff` against
  the prior merge commit showing no changes under `engine/`.

### Goal

Not a smarter algorithm: an operator-priority queue over the 27 OPEN
Unresolved Venues rows, and a genuine Venue Master expansion carried out
with the minimum human judgment actually required. No automatic Link or
Create decision was made by Claude; every write below was executed only
after the user answered three explicit questions.

### What was asked, and what was decided

1. **"El Tango (엘땅고)" / "EL TANGO" vs 데땅고 (부산)** - system suggestion
   was only MEDIUM/LOW on name similarity alone, with region and address
   both conflicting. User decision: **keep separate** - the two rows were
   folded into the CREATE NEW batch instead, as their own new venue (서울
   서초구 주흥길 12 환희빌딩 2층).
2. **"스튜디오 오초" vs OCHO (서울 마포)** - LOW score is a known
   short-token-containment scorer limitation (documented in v0.83.0, not
   corrected here - Section 15/27 forbid a threshold change on a single
   case). User decision: **defer** - left OPEN, no write.
3. **13 named CREATE NEW candidates** (clear name + real address + region,
   no Master match) - User decision: **approve all**.

### What was executed (all after approval, all transactional)

15 new venues created via `venue_resolution.create_and_link()`, each with
its raw text seeded as an alias so the exact same string resolves
automatically on the next collection. Two of the fifteen (이데알 탱고
까페, El Tango) had a second raw-text variant grouped onto the same
decision via `link_existing(add_alias=True)`, applied inside the same
transaction as the create so the pair lands together or not at all.

**Addendum, 2026-09-06 (post-release)**: the approved list named 13
candidates; Azucar (대전, 아수까) was not in the enumerated list the user
was shown, though it was built into the batch by the same objective
criteria (name + real address + region, no Master conflict) as the other
12 - a drafting gap when the question was condensed, not a substitution of
Claude's judgment for the user's. Flagged transparently in the original
report rather than left silent. The user reviewed this afterward and gave
explicit retroactive approval for Azucar as a CREATE NEW venue, with
instructions to keep the created venue and its links exactly as they stood
and make no further data changes. Recorded here as the Human Review
decision of record: **Azucar - approved (post-hoc), no further action
taken.**

### A real bug found and fixed along the way

`normalization.link_unresolved_venue()`'s alias-conflict handling caught the
Python-level exception on a duplicate alias but never rolled back to a
savepoint, so Postgres stayed in an aborted-transaction state and the very
next statement (marking the row LINKED) failed too. This is a pre-existing
defect in code shipped with v0.83.0's `link_existing()` - also reachable
from the plain Admin "link existing" action whenever the raw string already
happens to be one of the target venue's aliases - and it only surfaced now
because this release was the first time two rows for one new venue were
resolved together in one transaction (이데알 탱고 까페, El Tango). Fixed by
running the alias insert through `ignore_conflict=True` inside its own
savepoint; the 0.82 grouping-similarity threshold was untouched.

`venue_resolution.group_unresolved()` also only compared two rows' own
core-name similarity when *both* lacked a confident Venue Master
suggestion. "El Tango (엘땅고)" and "EL TANGO" - identical after
case-folding - had landed in different groups because only one of them had
enough context to reach a MEDIUM suggestion. Fixed without changing the
0.82 threshold: a row's own unrelated suggestion outcome no longer blocks
an already-confident match between the raw strings themselves.

### Result

- Venue Master: 9 -> 24 (+15)
- Unresolved Venues OPEN: 27 -> 10 (-17 rows: 15 primary + 2 grouped
  secondaries)
- events.venue_status UNRESOLVED: 59 -> 17, confirmed stable (not
  regrowing) across 2 live scheduler cycles post-write
- 포항/대구/청주/진주 region search counts unchanged at 2/2/2/2, now
  `region_confirmed=True` instead of a guess
- 광주 (Mi Vida tango studio) created with `region_id=None` - the region
  master has no Gwangju row yet; a real, disclosed gap, not a guess

## v0.83.0 Venue Resolution Operations + Human Review Acceleration

Status:
Fix and board acceptance completed against the ROCKPro64 board's real
production database, 2026-09-06. Engine code unchanged.

Version split:

- Product Runtime: 0.83.0
- Information Engine: unchanged (0.80) - this release touches only
  `runtime/` (Postgres-side venue resolution and its admin console); the
  Information Engine (`engine/`, its own SQLite store, independently
  versioned) was not modified at all, confirmed via `git diff` against
  the prior merge commit showing no changes under `engine/`.

### Goal

59 events (28 distinct raw venue strings) sat in the Unresolved Venues
queue with no ranking, no cross-string grouping, and no suggestion beyond
an alphabetical dropdown of all 9 registered venues - an operator had to
already know, from memory, which of 9 names a new string might be.

### What already existed (kept, not rebuilt)

`venue_resolution.similar_venues()` was deliberately exact-match only:
*"a warning an operator cannot check is a warning they learn to click
past."* This release does not reverse that - it adds a fuzzy layer
underneath it that is held to a stricter version of the same rule: never
auto-applied, and every suggestion always shows *why* (which field
matched, how closely) rather than a bare score.

### Fix

- `suggest_venue_links()`: top-3 ranked existing-venue candidates.
  `similar_venues()`'s own exact matches pass through unchanged as
  CONFIDENCE_HIGH (further capped to LOW if the region actively
  disagrees and no address backs the match - "same name, different
  region" branches must not be conflated). Everything else is
  `difflib.SequenceMatcher` name similarity against every registered
  name/alias, capped at MEDIUM even at a near-perfect score - fuzzy
  never reaches HIGH - and forced to LOW the moment an address or region
  conflicts.
- `group_unresolved()`: clusters queue entries that share a confident
  suggestion, or - when neither has one - whose own core names (address
  stripped) are near-identical, so "이데알 탱고 까페" and the same name
  with a full street address attached are reviewed together instead of
  twice.
- `group_link_existing()`: applies one Link Existing decision to an
  entire group, same per-string audit trail as doing it one at a time.
- `link_existing()` gained `add_alias=True` (opt-out), so an operator who
  knows a reading is ambiguous can link without teaching it to future
  collections.
- The Unresolved Venues admin page now shows each entry's top-3
  suggestions inline (confidence badge + reasoning, one-click, never
  pre-selected), a Group Apply preview/confirm flow, review order that
  puts entries with an upcoming event first, and an alias opt-out
  checkbox on the existing Link Existing form.
- Nothing added here writes anything on its own: suggestions and
  grouping are computed read-only on every page load.

### Live Acceptance (real production data, read-only, nothing linked)

All 27 currently-OPEN unresolved strings were run through
`suggest_venue_links()` against the real Venue Master (9 venues). Honest
finding: none of the 27 real unresolved strings actually duplicates an
existing master venue, so a "Top-1/Top-3 correct-match rate" has no true
positives to measure in this sample - what the sample does measure is
false-suggestion avoidance: 26/27 correctly produced no suggestion at
MEDIUM or better (16 NO_SUGGESTION, 10 correctly capped at LOW via an
address/region conflict); one case ("EL TANGO" against 데땅고/"detango",
0.86 similarity) reached MEDIUM on a coincidental shared "tango" root
between two plausibly different Spanish-article names ("El" vs "데" ->
"De") - flagged with its own reasoning, never auto-applied, and never
reaching HIGH, but a real, documented limitation of pure string
similarity worth refining later against a larger sample rather than
patched now on n=1. Grouping correctly clustered the one genuine
cross-row duplicate in the live queue ("이데알 탱고 까페" with and
without its address). Exact-match and fuzzy-match-with-conflict
behavior were additionally confirmed with synthetic fixtures exercising
true-positive cases the live 9-venue master doesn't currently contain.

### Tests

29 new tests (`tests/test_venue_suggestions.py`) plus 2 new routes added
to the existing venue-route auth-gate regression test. Runtime full
suite: 1265 passed, the same 2 pre-existing failures as every release
since v0.82.5 (confirmed unrelated).

## v0.82.8 SSH Operator Hardening + Direct Hammer Login

Status:
Fix and board acceptance completed against the ROCKPro64 board's real
production database, 2026-09-06. Engine code unchanged.

Version split:

- Product Runtime: 0.82.8
- Information Engine: unchanged (0.80).

### Remaining risk from v0.82.7

v0.82.7 made `hammer` the canonical git/deploy user and made
`scripts/deploy-production.sh`/`scripts/board-git.sh` refuse to be the
vector for root-owned drift - but the actual *login path* was still root
SSH followed by `sudo -u hammer` for every command. A root session stayed
the default habit, which is exactly what produced the root-owned-file
incidents in the first place.

### Fix

- `scripts/setup-board-operator.sh`: idempotent, public-key-only helper
  that adds a trusted key to `hammer`'s own `authorized_keys`. Never
  generates, reads or transmits a private key; never touches
  `sshd_config` - key provisioning and sshd policy stay two separate,
  separately-reviewed steps.
- `PermitRootLogin prohibit-password` applied via a drop-in
  (`/etc/ssh/sshd_config.d/90-dancemate-operator.conf`, tracked reference
  copy at `deploy/rockpro64/sshd-operator.conf`) - root password login is
  refused; root retains only its own existing key for OS/service-level
  emergency work. `PasswordAuthentication` was left untouched globally:
  disabling it needs console/local-access recovery verified first, which
  this release did not attempt.
- `deploy/rockpro64/README.md`: `ssh hammer@<board>` is now documented as
  the default login, not a fallback behind `sudo -u hammer`.

### Verification (before any sshd change)

Two independent, freshly-connected `hammer` SSH sessions (public key, not
a `sudo -u hammer` shell inside an existing root session) each confirmed:
`git status`/`log` clean with no `safe.directory` workaround needed,
`docker ps` without `sudo`, `scripts/deploy-production.sh --check`
preflighting clean against the real production database (read-only
identity check), and `sudo -l` correctly prompting for hammer's own
password (proving sudo access is configured, not merely present). Only
then was the sshd drop-in added, syntax-checked (`sshd -t`), and applied
with `systemctl reload` (never `restart`) - followed by a further fresh
`hammer` login and a confirmed-refused root password login attempt.

Root's own existing key (already in `/root/.ssh/authorized_keys` before
this release) was not independently re-tested, since this session never
held its private half - noted as an open item rather than assumed to
work.

### Tests

18 new tests (`tests/test_ssh_operator_hardening.py`) plus 2 new
parametrized cases from adding `setup-board-operator.sh` to the existing
operations-script hygiene checks; one existing ownership-guard test
adjusted to recognise `setup-board-operator.sh`'s legitimate
operator-home-scoped `chown` alongside the repository-scoped one every
other script uses. Runtime full suite: 1242 passed, the same 2
pre-existing failures as every release since v0.82.5 (confirmed
unrelated). Engine code unchanged this release (`engine-v0.80`).

## v0.82.7 Board Git Ownership Guard + Operator Safety

Status:
Fix and board acceptance completed against the ROCKPro64 board's real
production database, 2026-09-06. Engine code unchanged.

Version split:

- Product Runtime: 0.82.7
- Information Engine: unchanged (0.80).

### Remaining risk from v0.82.6

v0.82.6's own guard (`verify_repo_ownership`, `scripts/fix-ownership.sh`)
caught the *symptom* of 21 tracked files left root-owned on the board - the
result of `git fetch`/`git merge` typed directly over a root SSH session
during every prior release's "board sync" step, this one included. Nothing
stopped the habit itself: git and Docker both let root touch a
hammer-owned checkout without complaint, and whatever gets written then
belongs to root.

### Fix

- `runtime/ownership_guard.py`: pure decision logic (no filesystem access,
  no second real Unix user needed to test) behind the ownership/root
  checks, mirroring `deploy_guard.py`'s report-dict pattern.
- `scripts/board-git.sh`: the canonical way to run git against the board
  checkout from now on. Runs as its own owner directly, or silently
  delegates to `sudo -u <owner>` when invoked as anyone else (root
  included) - confirmed live: running it as root still leaves every
  touched file owned by `hammer`.
- `scripts/deploy-production.sh`: refuses outright to run as root, as the
  very first preflight step, before docker/backup/build are ever touched.
  Preflight order is now root/ownership -> git (clean tree, branch) ->
  version -> compose -> DB identity.
- `scripts/fix-ownership.sh` stays the deliberate exception: reclaiming a
  root-owned file requires root's own chown privilege, so it is documented
  as the cleanup/fallback path, never the routine one.
- `deploy/rockpro64/README.md` gained a "Canonical board workflow" section:
  SSH as `hammer` when possible; a root session may still do OS/service
  work, but repository commands go through `scripts/board-git.sh` /
  `sudo -u hammer scripts/deploy-production.sh`.

### Isolated reproduction (no production touched)

On a scratch clone (`hammer`-owned from the start, this time - the new
workflow used on itself): `scripts/deploy-production.sh --check` run as
root was BLOCKED before touching docker at all; the same command via
`sudo -u hammer` preflighted clean, including a real, read-only DB identity
check against the production database. A tracked file deliberately
`chown`'d to root reproduced `verify_repo_ownership`'s FAIL; `scripts/fix-
ownership.sh` (run as root, since only root can reclaim a root-owned file)
restored it to PASS.

### Tests

18 new tests (`tests/test_board_ownership_guard.py` plus a new parametrized
case from adding `board-git.sh` to the existing operations-script hygiene
checks). Runtime full suite: 1226 passed, the same 2 pre-existing failures
as v0.82.5/6 (confirmed unrelated). Engine code unchanged this release
(`engine-v0.80`, confirmed via `git diff` against the prior merge commit).

## v0.82.6 Deployment Guard + Production Compose Safety

Status:
Fix and board acceptance completed against the ROCKPro64 board's real
production database, 2026-09-06. Engine code unchanged.

Version split:

- Product Runtime: 0.82.6
- Information Engine: unchanged (0.80).

### Incident

During v0.82.5's own production deploy, a raw `docker compose up -d` - typed
directly on the board, no `-f` - was picked up by Docker's own default and
resolved to this repository's bundled-PostgreSQL `docker-compose.yml`
instead of the board's real `deploy/rockpro64/docker-compose.external-
postgres.yml`. A brand-new, empty PostgreSQL silently took over the
runtime/scheduler containers for a few minutes before it was noticed and
corrected. No production data was lost - the real, bind-mounted
`dancemate-postgres` container was never touched - but nothing in the
repository would have *blocked* the wrong command from running.

### Root cause

Docker itself has no concept of "the production compose file"; that
convention lived entirely in this project's own scripts
(`scripts/_common.sh`'s `DANCEMATE_COMPOSE_FILE`), and a command typed
directly on the board bypassed it. Production's own `.env` was already
configured correctly (`DANCEMATE_COMPOSE_FILE=deploy/rockpro64/docker-
compose.external-postgres.yml`) - the gap was that nothing stopped an
operator from not using it.

### Fix

- `runtime/deploy_guard.py`: static, dockerless checks of a compose file's
  own shape (no embedded `postgres` service, exactly `runtime`+`scheduler`,
  an external network, `POSTGRES_HOST` not resolving to the bundled
  `"postgres"` alias).
- `scripts/deploy-production.sh`: the only supported production entry point.
  Fixed compose file and pinned project name (never guessed from cwd), full
  preflight (compose shape, real-database identity via a read-only row
  count, no duplicate scheduler), then backup -> build -> recreate -> health
  gate, in that order - the running stack is never touched before a new
  image has actually built. `--check` runs the preflight only.
- `scripts/_common.sh`: `compose()` now pins the project name; new guard
  functions shared by any production-facing script.
- `docker-compose.yml` gained an explicit LOCAL/DEVELOPMENT-ONLY banner (it
  was previously titled "ROCKPro64 Staging Deployment", which is what made
  it a plausible-looking wrong answer). It is kept, not removed or renamed -
  local development and CI still need a self-contained stack.
- README.md and deploy/rockpro64/README.md: every documented command now
  goes through a script; no bare `docker compose ... up -d` remains in the
  procedure.

### Isolated reproduction (no production touched)

- Pointing `scripts/deploy-production.sh --check` at the local dev compose
  file (both explicitly and via a missing `DANCEMATE_COMPOSE_FILE`): BLOCKED
  before any `docker compose` command targeting it ever ran.
- Pointing it at the real production `.env`: preflight PASS, DB identity
  read `sources=18` rows from the real database (read-only), reported the
  currently-running image as the rollback candidate, made no changes.

### Tests

16 new unit tests (`tests/test_deploy_guard.py`) plus 3 new parametrized
cases from adding `deploy-production.sh` to the existing operations-script
hygiene checks (`tests/test_deployment_config.py`). Runtime full suite: 1208
passed, the same 2 pre-existing failures as v0.82.5 (confirmed unrelated -
historical Admin-CSV-seeded data absent from a fresh migration-only
database). Engine code is unchanged this release (`engine-v0.80`, confirmed
via `git diff` against the prior merge commit showing no changes under
`engine/`); rather than the full ~51-minute suite, an import check plus a
111-test smoke subset of the files most recently touched
(`test_social_dance.py`, `test_extraction_rules.py`, `test_live_pipeline.py`)
was run and passed.

## v0.82.5 Pohang/Daegu Candidate Extraction Gap Fix

Status:
Fix and board acceptance completed against the ROCKPro64 board's real
production database, 2026-09-06.

Version split:

- Product Runtime: 0.82.5
- Information Engine: 0.80 - engine code changed (see below).

### Root cause

Real Pohang and Daegu Miltang `/milongas` posts were structurally
well-formed (clear date/time/venue in the body) but produced zero
`event_candidates`. Traced end-to-end against real production data, not
assumed:

1. **EVENT_TYPE_CLASSIFICATION** (primary cause): `classifier.classify()`
   only recognises a milonga by keyword ("milonga"/"밀롱가"/"쁘롱"/"쁘락").
   Brand-name posts with no such word anywhere in title or body ("디디디",
   "바모스", and 45 others found live) classify as `OTHER`, so
   `live_pipeline.process_discovered_post()` returns zero events for them -
   even though the post came from Miltang's own `/milongas` board, whose
   page structure already guarantees the event type.
2. **VENUE_EXTRACTION** (compounding, affects region display once
   candidates exist): `extraction_rules._cut_at_boundary()` stopped at the
   first closing parenthesis, silently dropping a real street address when
   it appeared as a second, consecutive parenthetical group after a
   Miltang-rendered bilingual venue name (`"PosTango (포스탱고) (포항시 남구
   중앙로 83, 3층)"`). This is what made v0.82.4's region guess fall back to
   "지역 미확인" for exactly this shape.

### Fix

`classify()` already accepted a `known_event_type` parameter (documented as
admissible for "Source Registry / known series context") but no caller ever
set it. `RawPostRecord` gained the same field;
`miltang_discovery.discover()` now sets `known_event_type="MILONGA"` for
every `/milongas` record (keyed on the page's own existing `"milongas"` vs
`"notices"` prefix distinction - `/notices` is left unset and keeps being
read by its own text); `process_discovered_post()` threads it through to
`classify()`. `_cut_at_boundary()` now keeps extending across an
immediately-adjacent parenthetical group instead of stopping at the first
one; a group followed by anything else is still prose, unchanged. No
source_id, city, or venue-name branching anywhere in either fix.

### Before / After (real production data, scoped reprocess)

A detect-only scan across all 111 Miltang `/milongas` source_items (body has
DATE/TIME/PLACE structure, candidate count 0) found **47 affected posts**,
not just Pohang/Daegu - confirming the fix is genuinely generic. Scoped
reprocess (Miltang `/milongas` only, 47 explicit source_item_ids, never a
mass reprocess) plus one `normalize_all()` pass:

- Pohang: 0 -> 2 events (2026-09-11, 2026-09-18; venue/address/time all
  correct; `events_api.search(region="포항")` returns both, genuinely
  upcoming, dates not manipulated).
- Daegu: 0 -> 2 events (2026-09-09, 2026-09-16; venue/address correct, no
  time invented where the body had none; `events_api.search(region="대구")`
  returns both).
- All 47: exactly 1 event each, all `POSSIBLE` (never `VERIFIED` -
  Miltang/SECONDARY stays non-authoritative), all `review_state=PENDING`
  (Human Review untouched). Re-running the gap scan after the fix: 0
  affected.
- Total upcoming events: 87 -> 125. Region-unknown-upcoming: 29 -> 31
  (absolute count barely moved despite +38 genuinely new events; the ratio
  improved, 33%->25%) - the increase is explained by new events in cities
  `guess_region_label()`'s curated list does not cover, not by this fix
  degrading anything.

### Tests

16 new Engine tests (`test_social_dance.py`, `test_extraction_rules.py`,
`test_live_pipeline.py`): Pohang/Daegu candidate creation, date/time/venue
correctness, Cheongju/Jinju/Changwon control-group regression, multi-event
context safety and old-post year safety composed with the new hint,
class-only/performance-only still excluded without the hint, false-VERIFIED
impossible. Engine full suite: 745 passed (both locally and on the board).
Runtime full suite: 1189 passed, 2 pre-existing failures reproduced
identically on unmodified v0.82.4 against the same fresh database (real
data seeded historically via Admin CSV import, not by migrations - not a
v0.82.5 regression).

## v0.82.4 Regional Coverage + Source CSV Application + Tango Coverage Expansion

Status:
Fix and board acceptance completed against the ROCKPro64 board's real
production database, 2026-09-06.

Version split:

- Product Runtime: 0.82.4
- Information Engine: unchanged (0.79) - no engine code changed in this
  release.

### Regional coverage

Root cause: `events.region_id` comes only from a resolved venue's own
`region_id` - there is no other path. Real Miltang milongas in Cheongju,
Jinju, Changwon, Pohang, Ulsan, Daegu, Jeju and Seongnam/Bundang sat at
`region_id` NULL (an unresolved venue - nobody has resolved it into the
master yet, unrelated to this fix) and showed no region at all, for two
compounding reasons confirmed against the real data, not assumed: the
region master had only ever seeded Seoul/Busan/Daejeon even though
`runtime/venue_resolution.py`'s own address-parsing table already maps
every Korean province/metro name to a code (migration 024 registers the
seven this project has real evidence for), and four cities' real addresses
never carry their enclosing province name in the first place ("청주시
서원구...", not "충청북도 청주시...") - migration 024 also registers
Cheongju/Jinju/Changwon/Pohang as their own city-level regions, since a
reader finds "청주" more useful than "충북" anyway.

`venue_resolution.guess_region_label()` is the read-only, non-authoritative
display/filter fallback for the gap that remains until an operator resolves
a venue for real - never writes to `venues` or `events`, and never promotes
a raw string to a resolved venue (unchanged from this module's own existing
rule). Wired into the event card and detail page ("PISTA · 서울", "지역
미확인" rather than a blank field) and the region filter/facets, so
selecting "청주" now returns the two real Cheongju milongas instead of
zero. Measured on the real board: Tango upcoming events with no region
under the old region_id-only join: 41/87 (47%); with this release's
fallback: 29/87 (33%), and Cheongju/Jinju/Changwon/Ulsan/Gyeonggi are
visible and independently filterable for the first time. Pohang's and
Daegu's own real Miltang items exist but currently produce zero engine
candidates at all - a separate, out-of-scope extraction gap, not a region
problem; both are honestly reported as such rather than force-fit into a
region-only diagnosis.

Also, v0.82.3's own Next Recommendation: `runtime.collectors.content_mode()`
(derived from `config.parser`, no new stored field) now shows Discovery
Full / Non-HTML API / Detail Fetch / Generic Fetch / Search API on
`/admin/sources` and its detail page, alongside a source's own region/
coverage ("전국" for a null-region AGGREGATOR/DIRECTORY rather than a blank
badge - a source's own region never overwrites an event's own, unchanged).

### Source CSV application

`docs/tango_source_candidates.csv` (41 rows) and `docs/
tango_aggregator_analysis.csv` (Codex Source Discovery research) were
compared against the current Source Master. All four already-registered
Tango sources match a CSV `ADD_NOW` row. The seven Tangodori variants (also
`ADD_NOW`/`MONITOR`) are confirmed rejected on Terms grounds - unchanged
finding, `docs/tango_aggregator_analysis.csv`'s own analysis already found
its 2026-06-27 Terms update prohibits "scrape or abuse the APIs" regardless
of data quality. The one remaining `ADD_NOW` candidate,
2026 Chuncheon International Tango Festival (kcctf.org), was re-verified
live: robots `Allow: /`, Terms carry no scraping prohibition, and its
10/3-10/5 program is real and current - but its Day 2/3 schedule exists
only inside the page's Next.js App Router RSC streaming payload
(`self.__next_f.push(...)`), a materially more fragile format than the
single `__NEXT_DATA__` blob `danceinfo_discovery.py` already parses.
Building a collector for one annual, three-day event on that format was
judged out of scope for this release - a wrong date/time for a real
festival is a worse outcome than no coverage - so it is registered nowhere,
tracked instead as a documented, re-verified candidate in `docs/
tango_source_application.csv` and `docs/TANGO_SOURCE_DISCOVERY.md`'s new
status-update section. No new source was added this release; zero is an
honest count, not a shortfall against a target.

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
