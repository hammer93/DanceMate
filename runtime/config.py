"""Environment-driven configuration for the DanceMate runtime and scheduler.

Every value has a safe default so the module imports (and the unit tests run)
without any environment set up. Nothing here reads a secret from disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Product runtime version. Deliberately distinct from the Information Engine
# version: the Information Engine is versioned by its own extraction
# behaviour. v0.74 is the first version DanceMate modified (time, venue and
# fee reading); the untouched import is tagged engine-v0.73-baseline.
PRODUCT_VERSION = "0.96.27"
# v0.82 bumped this for parse_time_range()'s fallback-ordering fix (prefer an
# EVIDENCE_EXPLICIT reading over an ambiguous one - see extraction_rules.py) -
# a real change to what the engine reads, not just new Source rows.
# v0.84.1 bumped it again for extract_fee(): Korean 만원 notation, free
# admission, and a package/session-tier exclusion guard - see
# extraction_rules.py.
# v0.84.3 bumped it again: extract_with_image_fallback() gained venue as a
# fourth fallback field alongside date/time/fee, and extract_fee()'s
# _NOT_A_FEE narrowed "주차" so "무료주차" no longer disqualifies a real,
# nearby, clearly-labelled fee.
# v0.84.4 bumped it again: classify_with_image_evidence() (classifier.py)
# and process_discovered_post()'s call to it (live_pipeline.py) - an
# image-only post can now be classified from a trusted poster reading, not
# just title+body, closing the gap that made v0.84.3's own OCR fallback
# unreachable for a genuinely empty-body post.
# v0.91.0 bumped it again: extractor.DATE_PATTERNS gained a year-plus-range
# reading (extract_single() now also emits MULTI_DAY_EVENT/genre_hint
# evidence), extraction_rules.extract_venue() gained the truncated-label
# guard, and classifier.py gained party_evidence_bundle() and
# detect_genre_hints() - all real changes to what the engine reads, not
# just new Source rows.
# v0.96.0 bumped this to 0.89: classifier.py gained the recap/administrative
# non-event gate and the notice evidence bundle, extractor.py monthly and
# nth-weekday dates plus schedule-post expansion, extraction_rules.py the
# single start clock and unlabelled venue forms - what the engine reads changed.
# v0.96.2 bumped this to 0.90: extraction_rules.extract_venue() refuses a
# person/account/room "@" (grammar rules, no name list), extractor segments a
# multi-program post at structural anchors instead of the character midpoint
# (a clock is never cut in half) and picks the reviewed segment of an
# ambiguous post by the classifier's own vocabulary; parse_time_range()'s
# other-programme window stops at a bracket heading / line break. What the
# engine reads changed, so by the same rule every earlier bump followed.
# v0.96.3 deliberately does NOT bump this: it adds the operational path for
# re-reading stored bodies with whatever engine version is running
# (`extracted_engine_version`, migration 042), and changes nothing about what
# the engine reads. Bumping it would have made every row stale for no reason
# and, worse, thrown away the 0.91 baseline the re-extract is measured
# against.
# v0.96.2 (release-blocker fix, product version unchanged) bumped this to
# 0.91: extract_venue() now reads an honorific with an attached particle
# ("선배님은", "선배님께서") as a person and a multi-word "@" value with a
# finite predicate on any word as prose - Production item 2020's second
# mention had slipped through 0.90's detached-particle / last-token rules.
# v0.96.4 bumps this to 0.92: extractor.DATE_PATTERNS reads a month that
# names two of its own days ("9월 19,20일" - four Production items, all one
# weekly social series, previously dateless), flagging the span with the same
# MULTI_DAY_EVENT evidence the existing "9.18-20" range uses; and
# extraction_rules._near_window() stops the window a word may *qualify* a
# clock through at a structural break, exactly as the window that
# disqualifies one already did, so a section heading can no longer claim a
# neighbouring programme's clock. What the engine reads changed, so the
# version does. v0.96.3's incremental re-extract needs nothing else: every
# stored body is stale against 0.92 by definition and the scheduler works
# through them 25 at a time.
# v0.96.5 bumps this to 0.93: classifier.classify() reads a night announced
# in a post's own title through a body that also teaches - the rule
# social_evidence() has given the other scenes since v0.79, which the milonga
# family never had, and which cannot simply be copied because a lesson
# advert names the milonga it teaches you to dance at. Twelve Production
# items stop being CLASS-with-no-candidate; sweeping all 2,267 collected
# items changes those twelve and nothing else in either direction. What
# the engine reads out of a stored body changed, so the version does, and
# v0.96.3's incremental pass re-reads every row against 0.93 with no
# migration and no cursor hack.
# v0.96.7 bumps this to 0.94: classifier.classify() reads a post whose own
# title sells a lesson in the education vocabulary `class_words` never
# carried (수업, 특강, 클래스, 클라스, 강좌, 레슨) as a class rather than as
# the night it teaches you to dance at. Sweeping all 2,298 collected items
# changes 61: 18 stop being events (every one a lesson advert, a course
# syllabus, a recap or a guitar-school post - 0 genuine nights, 0 upcoming
# nights), 6 become SOCIAL_WITH_CLASS instead of SOCIAL (still events, now
# naming the lesson they carry) and 37 become CLASS instead of OTHER. What
# the engine reads out of a stored body changed, so the version does, and
# v0.96.3's incremental pass re-reads every row against 0.94 with no
# migration and no cursor hack.
# v0.96.8 bumps this to 0.95: classifier.classify() asks its recap/
# administrative guard before the collector's own `known_event_type`, so a
# post whose title says it is a club's archive of a night already danced
# ("정기모임 영상 #01", "금요정모 사진") or a notice that the night is off
# ("금요정모 휴강" - the one word the guard gained) is read as OTHER even on
# a dedicated event board. Sweeping all 2,327 collected items changes 154
# classifications; 126 stop being events, every one an archive post or a
# cancellation, one of them still upcoming (item 3635). 0 genuine nights and
# 0 genuine upcoming nights are lost, and nothing becomes an event that was
# not one. What the engine reads out of a stored title changed, so the
# version does, and v0.96.3's incremental pass re-reads every row against
# 0.95 with no migration and no cursor hack.
# v0.96.10 bumps this to 0.96: classifier.classify() asks whether a post is
# selling the course itself before it lets a social it merely carries make it
# a night - the check announced_night_evidence() has made for the milonga
# family since v0.96.5, which the social family never had. Three readings say
# "course": the source's own per-item category (danceinfo.net publishes one
# and the collector now carries it instead of discarding it), the post's own
# title, and a title that trains over a block of sessions priced as a block.
# A night the post announces in its own right still wins, by the same
# logistics bundles the other scenes are already read with. Sweeping all
# 2,345 collected items changes 8 classifications with the stored rows as
# they are and 12 once the category is flowing; 5 and 8 respectively stop
# being events, every one of them a lesson advert, a course timetable or a
# priced training block - 0 genuine nights and 0 genuine upcoming nights are
# lost, and nothing becomes an event that was not one. Two of the corrected
# rows were on public display as upcoming (items 186 and 3746). What the
# engine reads out of a stored title and body changed, so the version does,
# and v0.96.3's incremental pass re-reads every row against 0.96 with no
# migration and no cursor hack.
# v0.96.11 bumps this to 0.97: classifier.is_non_event_notice() recognises
# three more things a heading can say that are not an announcement - a trip
# counting its own days ("아르헨티나 29일차"), somebody saying where they have
# been ("베트남에서 귀국했습니다"), and a call for sponsorship ("협찬 공지의
# 건"). The first is never admitted on the number alone: a multi-day event
# could count its days too, so that arm steps aside whenever the same title
# names a night. Sweeping all 2,351 collected items changes 9
# classifications; 8 stop being events, every one a travel diary, a personal
# note or a solicitation - 0 genuine nights and 0 genuine upcoming nights are
# lost, and nothing becomes an event that was not one. One of the corrected
# rows was on public display as upcoming (item 2034). Two further measured
# tokens (풍경, 어나운스) were deliberately left out: 102 of Production's 143
# upcoming events carry a bare brand-name title, so a bare-noun token can
# delete a night outright - and this guard is asked above the collector's own
# prior. What the engine reads out of a stored title changed, so the version
# does, and v0.96.3's incremental pass re-reads every row against 0.97 with
# no migration and no cursor hack.
# v0.96.12 deliberately does NOT bump this. The defect it fixes is in
# danceinfo_discovery.parse_list(), which decides whether a listing is ever
# collected at all - a discovery filter, not a reading of a stored title or
# body. Nothing the engine extracts from an item it already holds changes, so
# re-extracting those items would re-derive exactly what is stored; the
# listings this release recovers were never stored to re-read. They arrive
# through an ordinary collection cycle instead.
# v0.96.13's own change is in acquisition, not the engine: it changes which
# text a danceinfo.net page yields to `acquisition.extract_article()`, so the
# items it affects need a re-acquisition (the Admin path that already exists)
# rather than a re-extraction. But reading those posts whole reached one rule
# that had never been reachable on a truncated body, and that rule IS in the
# engine: sold_as_a_course() let notice_evidence_bundle() overturn the
# source's own 강습 filing, and a four-week course's own timetable supplies
# exactly the day and clock that bundle asks for ("Largo Special KIZOMBA",
# live in Production as a SOCIAL on 23 October). Restricting that escape is a
# change in what the engine reads out of a stored body, so this bumps to 0.98
# and v0.96.3's incremental pass re-reads every row against it. Swept over all
# 2,467 stored items the restriction changes exactly one classification - that
# course, back to CLASS - and nothing else.
# v0.96.14 bumps to 0.99, and this one is a plain engine change: classify()
# reads the source's own per-item category in the direction it never read it.
# sold_as_a_course() has honoured danceinfo.net's 강습 filing since v0.96.10,
# but nothing read the same field when the site says 출빠정보 / 파티 / 정모 -
# a night to turn up to - so a post that also ran a workshop was judged by
# the workshop alone. Eleven of the 52 night-filed listings classified CLASS
# and produced no candidate; seven of them are real nights that also teach
# (night_event_bundle()'s own comment lists all seven and the four courses
# it must not take). Swept over all 2,468 stored items the new reading
# changes exactly those seven classifications, every one CLASS ->
# SOCIAL_WITH_CLASS: no event is lost, no post filed as a course moves, no
# OTHER becomes an event, and the 680 items carrying a collector's
# known_event_type are untouched. v0.96.3's incremental pass re-reads every
# stored row against it.
# v0.96.15 bumps to 1.00, and it is a change in how a stored body is read:
# extractor.extract_schedule() now also reaches a post that wrote its own
# list of days with years and then detailed each of them, and a yearless day
# inside such a post resolves against that list. A club opening for a holiday
# ("전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27") was stored as one
# event on one arbitrary day of its run - eight of the nine listings missing
# from one day's Production results were that shape, every one of them
# already holding a real event on the wrong day. Swept over all 2,472 stored
# items the change moves five posts, each from one candidate to several, and
# loses no date anywhere: no event removed, no event type changed, no other
# post read differently. v0.96.3's incremental pass re-reads every stored row
# against it.
# v0.96.16 bumps to 1.01, and it is again a change in how a stored body is
# read: extractor.extract_day_list() reads danceinfo.net's own `전체일정`
# field as the days the post runs, where extract_schedule() had been reading
# its comma-packed days as a run of date headings. Every day but the last then
# got an empty segment and was dropped, while the last swallowed the whole
# `일정정보` + description block, so a five-night holiday party was stored once,
# on the last day of its own run. Measured with a harness that calls
# process_discovered_post() itself and rebuilds Production's own image_texts
# from its stored source_item_image rows: over all 2,483 items the change moves
# six posts, adds 10 dates and removes 2 - both already past - and loses no
# start time, no classification and nothing upcoming. v0.96.3's incremental
# pass re-reads every stored row against it.
# v0.96.17 bumps to 1.02 for one word. A schedule post that details each of
# its days names the night on each day's own line, and one venue's regular
# Saturday is written `LATIN NIGHT` and nothing else - 홍턴's 추석 run listed
# four days and only the fourth failed to name itself in a word the
# dated-programme vocabulary knew, so the whole run collapsed to one candidate
# on the wrong hour and another day's price. `extraction_rules`
# .DATED_PROGRAM_WORDS is a third mapping read by extract_schedule() and
# extract_day_list() alone; EVENT_WORDS still answers its four other questions
# untouched (which clock range is the event's time, which lone clock its start,
# which price its fee, which segment of an ambiguous post is reviewed) - a post
# with two programmes, one LATIN NIGHT and one 소셜, would otherwise read the
# NIGHT's 19:00 instead of the social's 21:00. Measured over all 2,489 stored
# items with a harness that replays Production's own poster OCR: one item
# changes, 1 -> 4 candidates, 3 dates added, none removed, no classification
# moved. The broad alternative changes two items and both are false positives.
# v0.96.18 bumps to 1.03: `extraction_rules.parse_start_time()` now weighs how
# near a class word is against how near the event's own word is, instead of
# letting any class word within sixteen characters veto a lone clock outright,
# and ranks a clock the post says the event *opens* at above one that merely
# sits beside the event's name. BABARU's "PM 8:00~9:00 (워크샵), PM 9:00 START
# (소셜)" had the workshop's word four characters before the social's own start
# and the social's one character after, so every candidate was vetoed and the
# 21:00 could only come from a poster; 홍턴's 9/23 put its 파티 heading beside
# three clocks and advertised the first workshop's 19:00 instead of the 21:00 it
# opens at. Weighing distance also let through the tail of a range, so a clock
# written as one end of a range is now explicitly never an independent start
# ("9:00-1:00 소셜" is not a social starting at 01:00). Measured over all 2,504
# stored items against a git-stash baseline: four posts change - 2 None->time,
# 5 time->time, 0 time->None - with no date, cardinality or classification
# change anywhere. v0.96.3's incremental pass re-reads every stored row.
# v0.96.19 bumps to 1.04: `extraction_rules.parse_time_range()` asks the same
# question of a clock *range* that v0.96.18 asked of a lone clock - is the class
# word really nearer than the event's own word - instead of letting any class
# word within sixteen characters veto the range outright. 가또땅고's "오픈특강
# with 샤론y태희 9:00pm-12:30am 밀롱가" had the milonga's own hours thrown away
# by the class that ends ten minutes before them, so the post advertised the
# performance's 22:30; 또도땅고's daytime milonga read 01:00 instead of the
# "2:00pm ~ 4:00pm 밀롱가 씨엠쁘레" it states. A range's blast radius is far
# larger than a lone clock's - 1,508 candidates in the stored bodies and 891
# more in the stored poster OCR, 205 of them rejected today - so two rules come
# with it: an event word that runs straight into another clock is naming that
# clock and not this range ("소셜 시작 : PM 8:00"), and a class word written
# *after* a range is that range's own label and still owns it however near the
# event's word is (the PISTA poster's "심야밀롱가(11:30 p.m-4:30 a.m) 패키지" is
# the package's hours, not the milonga's). Each closes exactly one false
# positive: without them a naive nearest-word comparison admits 8 of the 205
# rather than 6. Where several ranges are named, the nearest-named one now wins
# rather than the first by position. Measured over all 2,516 stored items
# against a git-stash baseline: three posts change, all time->time, with no
# None->time, time->None, date, cardinality, classification, venue or fee change
# anywhere and KET regression 0. v0.96.3's incremental pass re-reads every
# stored row.
# v0.96.20 does NOT bump the engine: it is a Source Registry round. Three public
# Daum Cafe event boards were verified live and registered through
# `scripts/apply-board-sources.py`'s existing admission gate, and one class
# board was registered disabled. No extraction, classification, date, time,
# venue, fee, identity or duplicate rule changed - so every stored row's
# extraction is still the 1.04 reading, and re-stamping 2,516 rows to a new
# number would claim a re-read that never happened. What the round found instead
# is an access wall: all 8 registered NAVER_CAFE sources are ROBOTS_DISALLOWED
# (814 stored items, 0 usable bodies, which is where 346 of Swing's 406
# collected items go), several Daum boards answer 200 with BODY_UNAVAILABLE
# because they are members-only, and latindancekorea.com serves its whole event
# calendar only from a route its own robots.txt marks Disallow. Those are
# recorded as BLOCKED, not worked around.
# v0.96.21 bumps to 1.05: `extractor.DATE_PATTERNS` now reads an English month
# naming a range of its own days - "Oct 8-11, 2026", "October 8-11, 2026",
# "Oct. 8 - 11, 2026". Every one of the eight patterns before it was numeric
# ("2026.10.08", "9.18-20", "10/8") or Korean ("10월 8일", "9월 19,20일"), so a
# page writing its dates for an English-reading audience produced no date at
# all: SEOUL lindyfest 2026's own page says "DATE Oct 8-11, 2026" and stored
# nothing, despite being robots-permitted with its whole body fetching. The
# reading follows v0.91.0 PHASE 5's existing multi-day contract exactly -
# `event_date` is the range's FIRST day and the span is flagged MULTI_DAY_EVENT
# with inference DATE_RANGE_START_ONLY, because `events` has no end-date column
# - so no new contract, no event per day, no invented end date. Both ends are
# calendar-validated and a backwards range is refused ("Oct 11-8, 2026",
# "Feb 29-30, 2026" read as a date that could not be placed); a day outside
# 1..31 does not match at all, leaving a later pattern free to read a real date
# from the same text. Measured over all 2,535 stored items and 1,589 stored OCR
# texts first: 20 English month tokens in 16 items, 27 in 21 OCR texts, and zero
# same-month day ranges - and a git-stash baseline diff over the whole corpus
# changed 0 source_items, so this bump re-reads every stored row and is expected
# to move none of them. v0.96.3's incremental pass does that re-read.
# v0.96.22 does NOT bump the engine, and the reason was checked rather than
# assumed: robots.txt evaluation lives entirely in `runtime.acquisition` /
# `runtime.robots`, the Information Engine imports neither, and no extraction,
# classification, date, time, venue, fee, identity or duplicate rule changed. A
# stored row's extraction is still the 1.05 reading, so re-stamping 2,543 rows
# would claim a re-read that never happened. What changed is which URLs this
# project is willing to request: `urllib.robotparser` answers by file order and
# cannot express a wildcard, which let one registered source's filtered query
# page be fetched although its robots.txt disallows it twice. Measured over all
# 1,148 URLs acquisition requests, the corrected reading changes exactly one
# decision, and changes it to BLOCK - nothing becomes newly permitted.
#
# v0.96.23 does NOT bump the engine either, checked the same way. The whole
# change is in `runtime.duplicates` (the canonical/fold resolver) plus the line
# `scheduler.jobs` prints: an automatic merge now needs a *resolved* place, and
# each scan re-asks the automatic merges it has already made. The Information
# Engine has no notion of `canonical_event_id`, `venue_status` or the Venue
# Master - it emits a venue *string*, and whether that string is a place is
# decided here, by `normalization.resolve_venue()` against `venue_aliases`. No
# extraction, classification, date, time, venue, fee or identity_key rule
# changed, so every stored row's reading is still the 1.05 reading and
# re-stamping 2,543 rows would claim a re-read that never happened. Nor is a
# re-extract needed to converge: the fold graph is rebuilt by the ordinary
# `event-normalization` job, which has always ended in `duplicates.scan()`.
# v0.96.24 DOES bump the engine, and this is what the bump re-reads. A poster
# may fill a venue the body never named (v0.84.3), narrowed there to "only if
# the poster labelled it" - and written as a prefix test on the evidence
# string, which two readings that are not labels answered to as well
# ("LABEL:@", "LABEL:SUFFIX"). Measured over every venue reading the 1.05
# engine had taken off a Production poster: 65 readings, 50 from the "@"
# shortcut, and 49 of those 50 were not places - fees, clocks, session counts,
# contact lines, genre words, taglines, OCR noise. Re-reading the corpus under
# 1.06 removes the venue from 61 Events and changes nothing else about them;
# the offline harness (base vs patched over all 537 posts with poster OCR)
# moved date/start/end/fee on 7, every one reviewed, and the canonical graph
# by zero rows. Extraction semantics changed, so the stamp has to change:
# a row still marked 1.05 would claim a reading this engine no longer makes.
#
# v0.96.25 does NOT bump the engine, and the reason was checked rather than
# assumed: the change is which images an acquisition fetch stores as a post's
# own (`acquisition.danceinfo_own_images`, consulted by
# `extract_content_images`), and the extractor reads exactly what it read
# before from whatever it is handed. No extraction, classification, date,
# time, venue, fee or identity rule changed, so a row's 1.06 stamp is still
# true of how it was read. What changes is the *input*: a re-acquired
# danceinfo item gets a new `fetched_at`, which is branch (1) of
# `content_store.needing_reprocess()` - so the ordinary `engine-reprocess`
# job re-reads exactly the items whose poster list actually changed, under
# the same engine 1.06, with no version bump and no forced pass.
#
# v0.96.26 bumps the engine: `extraction_rules` now reads where a labelled venue
# name ends. Three narrow additions, each measured against every venue string
# Production holds *before* it was made - two fee labels the list was missing
# (`수강료`, `강습료`), five section headings that never appear inside a correct
# venue (`협찬`, `경품`, `후원`, `타임테이블`, `드레스코드`), and a pictograph
# boundary once the name has started - plus a guard that stops the
# "<name>스튜디오" shortcut from swallowing the label word itself
# ("장소 카디즈 스튜디오" -> "카디즈 스튜디오"). `주차` was the one candidate
# disqualified outright: it sits inside four *resolved* venues. Measured over all
# 2,580 stored posts, re-read with the patched engine beside the running one: 20
# changed, every one of them the venue and nothing else - 0 posts moved a date, a
# time, a fee or a type - and 0 resolved venues lost. Extraction semantics
# changed, so the stamp has to change with them.
#
# v0.96.27 -> 1.08. A clock range whose first endpoint is written as a bare hour
# with the meridiem marker in front of it - "시간: pm 8~11:30", 화정's weekly
# notice - was no range at all to `_RANGE_RE`, and the lone-clock rule then took
# the only clock it could read: the range's **end**. An 8pm milonga was
# advertised at 11:30 in the morning. With the grammar taught that shape, three
# more readings follow from evidence the posts already carried - a numbered later
# set's hours are not the night's ("2부24시~06시"), an unmarked morning never
# outranks an explicit evening ("저녁 9시" x2 against "10시부터"), and a range
# running to a midnight that can only be midnight did not start at nine in the
# morning ("소셜 9:00 ~ 00:00"). Measured over all 2,615 stored posts, re-read
# with the candidate engine beside the running one: 19 changed, every one of them
# the time and nothing else - 0 posts moved a date, a fee, a venue, a type or a
# candidate count - 0 readings lost, and 0 new wrong times. Extraction semantics
# changed, so the stamp changes with them.
DEFAULT_ENGINE_VERSION = "1.08"

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# DANCEMATE_HOST and DANCEMATE_BIND_ADDRESS are NOT the same thing:
#
#   DANCEMATE_HOST          the address the server listens on INSIDE the
#                           container. Almost always 0.0.0.0 - a container has
#                           no LAN address of its own, so binding the host's
#                           LAN IP here fails with "could not bind on any
#                           address".
#   DANCEMATE_BIND_ADDRESS  the HOST interface Docker publishes the port on.
#                           Compose and the health scripts read it; the
#                           application never does.


@dataclass(frozen=True)
class Settings:
    env: str
    version: str
    engine_version: str

    listen_address: str
    port: int

    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str

    engine_root: Path
    engine_data_dir: Path
    data_dir: Path
    log_dir: Path
    backup_dir: Path

    scheduler_heartbeat_seconds: int
    scheduler_job_interval_seconds: int

    storage_warn_percent: int
    storage_critical_percent: int
    backup_retention: int
    backup_max_age_hours: int

    @property
    def dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} "
            f"password={self.postgres_password}"
        )

    @property
    def safe_dsn(self) -> str:
        """DSN with the password removed - safe to log or return over HTTP."""
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user}"
        )


def load_settings() -> Settings:
    engine_root = Path(_env("ENGINE_ROOT", str(REPO_ROOT / "engine")))
    return Settings(
        env=_env("DANCEMATE_ENV", "staging"),
        version=_env("DANCEMATE_VERSION", PRODUCT_VERSION),
        engine_version=_env("ENGINE_VERSION", DEFAULT_ENGINE_VERSION),
        listen_address=_env("DANCEMATE_HOST", "0.0.0.0"),
        port=_env_int("DANCEMATE_PORT", 8080),
        postgres_host=_env("POSTGRES_HOST", "postgres"),
        postgres_port=_env_int("POSTGRES_PORT", 5432),
        postgres_db=_env("POSTGRES_DB", "dancemate"),
        postgres_user=_env("POSTGRES_USER", "dancemate"),
        postgres_password=_env("POSTGRES_PASSWORD", ""),
        engine_root=engine_root,
        engine_data_dir=Path(_env("ENGINE_DATA_DIR", str(engine_root / "data"))),
        data_dir=Path(_env("DANCEMATE_DATA_DIR", str(REPO_ROOT / "data"))),
        log_dir=Path(_env("DANCEMATE_LOG_DIR", str(REPO_ROOT / "logs"))),
        backup_dir=Path(_env("DANCEMATE_BACKUP_DIR", str(REPO_ROOT / "backup"))),
        scheduler_heartbeat_seconds=_env_int("SCHEDULER_HEARTBEAT_SECONDS", 60),
        scheduler_job_interval_seconds=_env_int("SCHEDULER_JOB_INTERVAL_SECONDS", 300),
        storage_warn_percent=_env_int("STORAGE_WARN_PERCENT", 75),
        storage_critical_percent=_env_int("STORAGE_CRITICAL_PERCENT", 95),
        backup_retention=_env_int("BACKUP_RETENTION", 7),
        backup_max_age_hours=_env_int("BACKUP_MAX_AGE_HOURS", 48),
    )


def validate(settings: Settings) -> list[str]:
    """Return a list of configuration problems. Empty list means valid."""
    problems: list[str] = []
    if not settings.postgres_password:
        problems.append("POSTGRES_PASSWORD is empty")
    if settings.postgres_password == "CHANGE_ME":
        problems.append("POSTGRES_PASSWORD is still the .env.example placeholder")
    if not 1 <= settings.port <= 65535:
        problems.append(f"DANCEMATE_PORT out of range: {settings.port}")
    if settings.scheduler_heartbeat_seconds < 30:
        problems.append(
            "SCHEDULER_HEARTBEAT_SECONDS below 30 - too much SD card write pressure"
        )
    if not 1 <= settings.storage_warn_percent < settings.storage_critical_percent <= 100:
        problems.append("STORAGE_WARN_PERCENT/STORAGE_CRITICAL_PERCENT are inconsistent")
    if settings.backup_retention < 1:
        problems.append("BACKUP_RETENTION must be at least 1")
    return problems
