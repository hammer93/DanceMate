"""v0.96.42 - a source page revised after the engine read it is read again.

The defect, as found on Production 9a038e9 (v0.96.41): `intake.store_item()`
noticed an edited page, stored it and set `ingest_state = PENDING` - and
nothing ever read it. `ingest_pending()` re-ingests through
`database.persist_raw_post()`, which keys a post on its URL and returns
`is_new = False`, so nothing is extracted; `needing_reprocess()`'s
body-arrived branch never fires because `settle_full_body()` stamps
`reprocessed_at` on the revision itself; and the row still reads the running
engine version. Item 6234's re-collected title waited for the next engine
bump, and on 2026-10-19 four more revisions were waiting the same way (6388
gained a DJ, 6503 a longer title, 6325 a new fee, 6510 a corrected DJ).

Every test here drives the pipeline the scheduler runs - `intake.store_item()`
(the collector's record, built by the real TangoNOW and Miltang parsers where
the case is theirs), then one tick in the scheduler's own job order:
engine-ingest, engine-reprocess (`reconcile_unsigned()` then
`reprocess_acquired()`), event-normalization (`normalize_all()` then
`duplicates.scan()`). The engine is the real one, its store a per-test SQLite
file, and every runtime connection is the `pg` fixture's own transaction, so
nothing is committed. ENGINE_VERSION never moves: these are revisions, not a
bump.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from runtime import (
    acquisition,
    collectors,
    content_store,
    db,
    duplicates,
    engine_ingest,
    intake,
    miltang_discovery,
    normalization,
    sources,
    tangonow_discovery,
)
from tests.conftest import register_venue
from tests.fixture_v09641_festivals import MILTANG_NOTICES

SHARE = "https://ktnow.kr/e/"


# --- the pipeline -------------------------------------------------------------

def _share_page(ld: dict) -> str:
    return ('<!doctype html><html><head><script type="application/ld+json">'
            + json.dumps(ld, ensure_ascii=False) + "</script></head><body></body></html>")


def _night(name: str, day: str, start: str, end: str, *, end_day: str | None = None,
           place: str | None = None, dj: str = "Dada", org: str = "PISTA") -> dict:
    """A TangoNOW share page's JSON-LD, shaped like the v0.96.35 captures."""
    ld = {
        "@context": "https://schema.org", "@type": "Event", "name": name,
        "description": f"{day} · {start}~{end} · DJ {dj}",
        "startDate": f"{day}T{start}:00+09:00",
        "endDate": f"{end_day or day}T{end}:00+09:00",
        "eventStatus": "https://schema.org/EventScheduled",
        "organizer": {"@type": "Organization", "name": org},
    }
    if place:
        ld["location"] = {"@type": "Place", "name": place}
    return ld


def _notice_page(notice: dict) -> str:
    """tests/test_v09641_festival_collectors.py's Miltang template."""
    rows = [f"<div><dt>DATE</dt><dd>{notice['date_row']}</dd></div>"]
    for label, key in (("TIME", "time_row"), ("PLACE", "place_row"), ("ORG", "org_row")):
        if notice.get(key):
            rows.append(f"<div><dt>{label}</dt><dd>{notice[key]}</dd></div>")
    description = (
        '<h3 class="text-xs font-bold text-brand tracking-widest">DESCRIPTION</h3>'
        f'<div class="text-sm ql-content">{notice["description"]}</div>'
        if notice.get("description") else "")
    return ("<!DOCTYPE html><html><head><title>x</title></head><body>"
            '<script type="application/ld+json">'
            + json.dumps(notice["ld"], ensure_ascii=False) + "</script>"
            + f"<h2>{notice['ld']['name']}</h2><dl>{''.join(rows)}</dl>{description}"
            "</body></html>")


class Pipe:
    def __init__(self, pg, settings, source, unique):
        self.pg, self.settings, self.unique = pg, settings, unique
        self.source_id = source["source_id"]
        self.source_key = source["source_key"]
        self.last: dict = {}
        # A live collection run, as the scheduler records one: what makes the
        # Events it produces LIVE, which is what public search lists.
        with pg.cursor() as cur:
            cur.execute("INSERT INTO source_collection_runs (source_id, mode, status) "
                        "VALUES (%s, 'live', 'PASS') RETURNING collection_run_id",
                        (self.source_id,))
            self.run_id = cur.fetchone()[0]

    # collection
    def item(self, record: dict) -> intake.RawItem:
        record = dict(record, source_id=self.source_key, platform="WEB")
        return collectors._to_raw_item(record)

    def collect(self, record: dict) -> str:
        return intake.store_item(self.pg, self.source_id, self.item(record),
                                 collection_run_id=self.run_id)

    def share(self, ld: dict, n: int = 1) -> dict:
        return tangonow_discovery.parse_share_page(
            _share_page(ld), f"{SHARE}occ_v42_{self.unique}_{n}")

    def notice(self, notice: dict, n: int) -> dict:
        url = f"https://miltang.com/notices/{n}{self.unique}"
        return miltang_discovery.parse_detail(_notice_page(notice), url)

    def _db_clock(self) -> None:
        """settle_full_body() and record_outcome() stamp fetched_at with the
        Python clock; every other stamp is the database's now(), which inside
        this one test transaction is the transaction's *start*. Left alone,
        each fetch would read as later than every pass that follows it - the
        reverse of what autocommit connections see in Production - so the
        Python stamps are put on the database clock first."""
        with self.pg.cursor() as cur:
            cur.execute(
                "UPDATE source_item_content c SET "
                "  fetched_at = LEAST(c.fetched_at, now()), "
                "  reprocessed_at = LEAST(c.reprocessed_at, now()), "
                "  last_attempt_at = LEAST(c.last_attempt_at, now()), "
                "  first_attempt_at = LEAST(c.first_attempt_at, now()) "
                "FROM source_items i WHERE i.source_item_id = c.source_item_id "
                "  AND i.source_id = %s", (self.source_id,))

    # one scheduler tick, in jobs.REGISTRY's sorted order
    def tick(self) -> dict:
        self._db_clock()
        self.last = {
            "ingest": engine_ingest.ingest_pending(self.settings),
            "reconcile": engine_ingest.reconcile_unsigned(self.settings),
            "reprocess": engine_ingest.reprocess_acquired(self.settings, limit=500),
            "normalize": normalization.normalize_all(self.settings, limit=None),
        }
        duplicates.scan(self.pg)
        return self.last

    # reading
    def item_id(self, url: str) -> int:
        with self.pg.cursor() as cur:
            cur.execute("SELECT source_item_id FROM source_items "
                        "WHERE source_id = %s AND url = %s", (self.source_id, url))
            return cur.fetchone()[0]

    def events(self, item_id: int) -> list[dict]:
        with self.pg.cursor() as cur:
            cur.execute("SELECT * FROM events WHERE source_item_id = %s "
                        "ORDER BY event_date, start_time NULLS FIRST, event_id", (item_id,))
            names = [c.name for c in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]

    def event(self, item_id: int) -> dict:
        found = self.events(item_id)
        assert len(found) == 1, found
        return found[0]

    def content(self, item_id: int) -> dict:
        return content_store.get(self.pg, item_id)

    def queued(self, item_id: int) -> bool:
        return item_id in {r["source_item_id"] for r in content_store.needing_reprocess(
            self.pg, limit=1000, engine_version=self.settings.engine_version)}

    def candidate_ids(self, item_id: int) -> list[int]:
        with self.pg.cursor() as cur:
            cur.execute("SELECT candidate_id FROM events WHERE source_item_id = %s "
                        "ORDER BY candidate_id", (item_id,))
            return [r[0] for r in cur.fetchall()]

    def raw_post(self, url: str):
        import sqlite3

        from runtime import engine_adapter

        con = sqlite3.connect(engine_adapter.engine_db_path(self.settings))
        con.row_factory = sqlite3.Row
        try:
            return con.execute("SELECT * FROM raw_posts WHERE source_url = ?", (url,)).fetchone()
        finally:
            con.close()


@pytest.fixture
def pipe(pg, monkeypatch, unique):
    from runtime.config import load_settings

    @contextmanager
    def _connect(_settings, **_kwargs):
        yield pg

    monkeypatch.setattr(db, "connect", _connect)
    settings = load_settings()
    source = sources.create_source(
        pg, source_key=f"SRC-V42-{unique}", name=f"v0.96.42 test {unique}",
        platform="WEB", source_role="DIRECTORY", queries=[], config={}, enabled=False,
    )
    return Pipe(pg, settings, source, unique)


def _first(pipe: Pipe, record: dict) -> int:
    assert pipe.collect(record) == "NEW"
    pipe.tick()
    return pipe.item_id(record["source_url"])


# --- item 6234, the regression the release exists for -----------------------

OLD_6234 = dict(name="PISTA | The PISTA", day="2026-10-24", start="19:00", end="23:00",
                dj="Dada")
NEW_6234 = dict(name="PISTA | PISTA Champion Celebration", day="2026-10-24",
                start="19:00", end="23:00", dj="헨리", place="PISTA")


def test_item_6234_revised_page_reaches_its_event_without_an_engine_bump(pipe):
    """The two revisions are the real ones: the share page as captured on
    2026-10-13 (v0.96.35's fixture) and as re-collected on 2026-10-18, whose
    body the parser rebuilds byte for byte as Production stores it."""
    engine_version = pipe.settings.engine_version
    old = pipe.share(_night(**OLD_6234))
    item_id = _first(pipe, old)
    before = pipe.event(item_id)
    assert before["event_name"] == "PISTA | The PISTA"
    assert before["venue_text"] is None and before["dj"] == "Dada"

    new = pipe.share(_night(**NEW_6234))
    assert new["body"] == "2026년 10월 24일 시간: 19:00~23:00 장소: PISTA DJ: 헨리 주최: PISTA"
    assert pipe.collect(new) == "REVISED"
    assert pipe.queued(item_id)

    pipe.tick()

    after = pipe.event(item_id)
    assert after["event_id"] == before["event_id"]
    assert after["candidate_id"] == before["candidate_id"]
    assert after["event_name"] == "PISTA | PISTA Champion Celebration"
    assert after["venue_text"] == "PISTA" and after["dj"] == "헨리"
    assert (str(after["start_time"]), str(after["end_time"])) == ("19:00:00", "23:00:00")
    assert pipe.settings.engine_version == engine_version
    assert not pipe.queued(item_id)
    content = pipe.content(item_id)
    assert content["extraction_outcome"] == content_store.OUTCOME_EXTRACTED
    assert content["applied_engine_version"] == engine_version
    # The engine's own stored post is the one it read, title included.
    assert pipe.raw_post(new["source_url"])["title"] == "PISTA | PISTA Champion Celebration"


def test_the_engine_version_is_not_bumped_by_this_release():
    from runtime.config import DEFAULT_ENGINE_VERSION
    from runtime.normalization import NORMALIZATION_VERSION

    assert DEFAULT_ENGINE_VERSION == "1.18"  # v0.96.56: time-role bump
    assert NORMALIZATION_VERSION == "3"


# --- what is a revision -------------------------------------------------------

def test_a_title_only_revision_is_detected_and_read(pipe):
    item_id = _first(pipe, pipe.share(_night("Sunday Milonga | Ocho", "2026-11-08",
                                             "18:00", "22:00")))
    assert pipe.event(item_id)["event_name"] == "Sunday Milonga | Ocho"
    assert pipe.collect(pipe.share(_night("Sunday Special Milonga | Ocho", "2026-11-08",
                                          "18:00", "22:00"))) == "REVISED"
    pipe.tick()
    assert pipe.event(item_id)["event_name"] == "Sunday Special Milonga | Ocho"


def test_a_time_revision_moves_the_clock_and_the_overnight_flag(pipe):
    item_id = _first(pipe, pipe.share(_night("Friday | Ocho", "2026-11-07", "20:00", "23:00")))
    before = pipe.event(item_id)
    assert (str(before["start_time"]), str(before["end_time"]), before["end_day_offset"]) \
        == ("20:00:00", "23:00:00", 0)
    assert pipe.collect(pipe.share(_night("Friday | Ocho", "2026-11-07", "21:00", "00:00",
                                          end_day="2026-11-08"))) == "REVISED"
    pipe.tick()
    after = pipe.event(item_id)
    assert after["event_id"] == before["event_id"]
    assert (str(after["start_time"]), str(after["end_time"]), after["end_day_offset"]) \
        == ("21:00:00", "00:00:00", 1)
    assert after["time_evidence"] == before["time_evidence"]


def test_a_venue_revision_moves_the_venue_within_the_venue_master(pipe):
    first = register_venue(pipe.pg, f"Hall A {pipe.unique}")
    second = register_venue(pipe.pg, f"Hall B {pipe.unique}")
    item_id = _first(pipe, pipe.share(_night("Milonga | X", "2026-11-09", "19:00", "23:00",
                                             place=first["name"])))
    assert pipe.event(item_id)["venue_id"] == first["venue_id"]
    with pipe.pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venues")
        venues = cur.fetchone()[0]
    pipe.collect(pipe.share(_night("Milonga | X", "2026-11-09", "19:00", "23:00",
                                   place=second["name"])))
    pipe.tick()
    after = pipe.event(item_id)
    assert after["venue_id"] == second["venue_id"]
    assert after["venue_text"] == second["name"]
    with pipe.pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venues")
        assert cur.fetchone()[0] == venues


def test_a_body_revision_of_a_fetched_article_source_is_read(pipe):
    """The non-settled shape (Daum, 6503): the collector's title and snippet
    change, the fetched article is what the engine reads, and the item is
    read again with both."""
    url = f"https://cafe.daum.test/{pipe.unique}/1"
    record = {"source_url": url, "title": "[화정] 10월 20일 화정 공지",
              "body": "화정 밀롱가 공지", "acquisition_quality": "METADATA_ONLY"}
    assert pipe.collect(record) == "NEW"
    item_id = pipe.item_id(url)
    content_store.record_outcome(pipe.pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
        fetched_url=url, text="밀롱가 2026.10.20 20:00-23:30 장소: 스튜디오 오초 회비 10,000원"))
    pipe.tick()
    assert pipe.event(item_id)["event_name"] == "[화정] 10월 20일 화정 공지"
    revised = dict(record, title="[화정] 10월 20일 화정 공지 (DJ : 바비), 솔땅인만...")
    assert pipe.collect(revised) == "REVISED"
    pipe.tick()
    assert pipe.event(item_id)["event_name"] == "[화정] 10월 20일 화정 공지 (DJ : 바비), 솔땅인만..."


def test_a_festival_start_revision_moves_the_period_and_search(pipe):
    """Miltang notice 15 as captured, then with its start moved a day (a
    synthetic revision of the real record)."""
    from runtime import events_api

    notice = MILTANG_NOTICES["https://miltang.com/notices/15"]
    item_id = _first(pipe, pipe.notice(notice, 15))
    before = pipe.event(item_id)
    assert (str(before["event_date"]), str(before["end_date"])) == ("2026-11-11", "2026-11-16")
    moved = json.loads(json.dumps(notice))
    moved["ld"]["startDate"] = "2026-11-12"
    moved["date_row"] = moved["date_row"].replace("11(", "12(", 1)
    assert pipe.collect(pipe.notice(moved, 15)) == "REVISED"
    pipe.tick()
    after = pipe.event(item_id)
    assert after["event_id"] == before["event_id"]
    assert (str(after["event_date"]), str(after["end_date"])) == ("2026-11-12", "2026-11-16")
    assert after["start_time"] is None
    from datetime import date

    def found(day):
        return after["event_id"] in {e["id"] for e in events_api.search(
            pipe.pg, on=date.fromisoformat(day), include_past=True, limit=100)["events"]}
    assert not found("2026-11-11") and found("2026-11-12") and found("2026-11-16"), {
        k: after[k] for k in ("listing_state", "engine_status", "canonical_event_id",
                              "review_state", "provenance", "event_type")}


def test_a_festival_end_revision_carried_by_the_judgement_alone_is_read(pipe):
    """The page text is unchanged and only the stated period moves: v0.96.35's
    judgement branch, which this release keeps exactly as it was."""
    notice = MILTANG_NOTICES["https://miltang.com/notices/15"]
    item_id = _first(pipe, pipe.notice(notice, 15))
    shorter = json.loads(json.dumps(notice))
    shorter["ld"]["endDate"] = "2026-11-15"
    record = pipe.notice(shorter, 15)
    assert record["event_period"] == {"start": "2026-11-11", "end": "2026-11-15"}
    assert pipe.collect(record) == "REVISED"
    pipe.tick()
    assert str(pipe.event(item_id)["end_date"]) == "2026-11-15"


def test_a_removed_programme_row_retires_only_its_own_night(pipe):
    """Miltang notice 20 (KSTW 포항) states two nights; the revision drops one.
    The festival keeps its Event; the remaining night keeps its date, clock
    and place; the dropped one is gone."""
    notice = MILTANG_NOTICES["https://miltang.com/notices/20"]
    item_id = _first(pipe, pipe.notice(notice, 20))
    before = {(e["event_type"], str(e["event_date"])): e for e in pipe.events(item_id)}
    assert ("MILONGA", "2026-11-21") in before and ("MILONGA", "2026-11-20") in before
    fewer = json.loads(json.dumps(notice))
    lines = fewer["description"].split("</p>")
    fewer["description"] = "</p>".join(l for l in lines if "SEOUL GRAND" not in l)
    assert pipe.collect(pipe.notice(fewer, 20)) == "REVISED"
    pipe.tick()
    after = {(e["event_type"], str(e["event_date"])): e for e in pipe.events(item_id)}
    assert ("MILONGA", "2026-11-21") not in after
    welcome = after[("MILONGA", "2026-11-20")]
    old = before[("MILONGA", "2026-11-20")]
    assert (welcome["start_time"], welcome["end_time"], welcome["end_day_offset"],
            welcome["venue_id"]) == (old["start_time"], old["end_time"],
                                     old["end_day_offset"], old["venue_id"])
    assert [e for e in after.values() if e["event_type"] == "FESTIVAL"]


def test_content_and_judgement_revised_together_is_one_re_extraction(pipe):
    item_id = _first(pipe, pipe.share(_night("Milonga | Y", "2026-11-10", "19:00", "23:00")))
    revised = pipe.share(_night("Milonga | Y (Special)", "2026-11-10", "19:00", "23:00"))
    revised["known_event_type"] = "MILONGA"
    assert pipe.collect(revised) == "REVISED"
    pipe.tick()
    assert pipe.last["reprocess"]["reprocessed"] == 1
    assert not pipe.queued(item_id)


# --- what is not a revision --------------------------------------------------

def test_collecting_the_same_page_again_reads_nothing_again(pipe):
    record = pipe.share(_night("Milonga | Z", "2026-11-11", "19:00", "23:00"))
    item_id = _first(pipe, record)
    content = pipe.content(item_id)
    candidates = pipe.candidate_ids(item_id)
    for _ in range(3):
        assert pipe.collect(record) == "DUPLICATE"
        assert not pipe.queued(item_id)
        pipe.tick()
        assert pipe.last["reprocess"]["reprocessed"] == 0
    assert pipe.content(item_id)["reprocessed_at"] == content["reprocessed_at"]
    assert pipe.content(item_id)["extracted_input_signature"] == \
        content["extracted_input_signature"]
    assert pipe.candidate_ids(item_id) == candidates
    assert len(pipe.events(item_id)) == 1


def test_a_revision_read_once_is_not_read_again(pipe):
    item_id = _first(pipe, pipe.share(_night("A | B", "2026-11-12", "19:00", "23:00")))
    revised = pipe.share(_night("A | B C", "2026-11-12", "19:00", "23:00"))
    pipe.collect(revised)
    pipe.tick()
    assert pipe.last["reprocess"]["reprocessed"] == 1
    assert pipe.collect(revised) == "DUPLICATE"
    pipe.tick()
    assert pipe.last["reprocess"]["reprocessed"] == 0
    assert len(pipe.events(item_id)) == 1


def test_collection_and_fetch_metadata_alone_is_not_a_revision(pipe):
    """last_checked, collection time, run id, retry counts, fetch timing."""
    item_id = _first(pipe, pipe.share(_night("A | M", "2026-11-13", "19:00", "23:00")))
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_items SET collected_at = now() + interval '1 hour', "
                    "  collection_run_id = NULL WHERE source_item_id = %s", (item_id,))
        cur.execute("UPDATE source_item_content SET last_attempt_at = now(), "
                    "  attempt_count = attempt_count + 5, next_attempt_at = now(), "
                    "  http_status = 304 WHERE source_item_id = %s", (item_id,))
        cur.execute("UPDATE sources SET last_collected_at = now() WHERE source_id = %s",
                    (pipe.source_id,))
    assert not pipe.queued(item_id)
    pipe.tick()
    assert pipe.last["reprocess"]["reprocessed"] == 0


def test_the_signature_ignores_volatile_poster_urls(pipe):
    item_id = _first(pipe, pipe.share(_night("A | P", "2026-11-14", "19:00", "23:00")))
    before = content_store.input_signature(pipe.pg, item_id)
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET poster_candidates = %s::jsonb, "
                    "  image_count = 1 WHERE source_item_id = %s",
                    (json.dumps([{"url": "https://img.test/x.jpg?sig=1"}]), item_id))
    assert content_store.input_signature(pipe.pg, item_id) == before


# --- ordering, concurrency, failure -------------------------------------------

def test_two_revisions_before_a_tick_end_on_the_latest(pipe):
    item_id = _first(pipe, pipe.share(_night("Rev | A", "2026-11-15", "19:00", "23:00")))
    pipe.collect(pipe.share(_night("Rev | B", "2026-11-15", "20:00", "23:00")))
    pipe.collect(pipe.share(_night("Rev | C", "2026-11-15", "21:00", "23:30")))
    pipe.tick()
    after = pipe.event(item_id)
    assert after["event_name"] == "Rev | C" and str(after["start_time"]) == "21:00:00"
    assert pipe.last["reprocess"]["reprocessed"] == 1


def _intercept_engine(monkeypatch, before_extract):
    """Run ``before_extract(post)`` inside the engine call of the next pass."""
    real = engine_ingest._engine

    def wrapped(settings):
        engine_db, RawPostRecord, process, extract_single, needs = real(settings)

        def process_discovered_post(con, post, *args, **kwargs):
            before_extract(post)
            return process(con, post, *args, **kwargs)
        return engine_db, RawPostRecord, process_discovered_post, extract_single, needs

    monkeypatch.setattr(engine_ingest, "_engine", wrapped)


def test_a_revision_arriving_mid_pass_is_not_lost_or_overwritten(pipe, monkeypatch):
    """Revision B is being re-read when revision C is stored. B's pass must not
    stamp C as read, and C must be what the Event says in the end."""
    item_id = _first(pipe, pipe.share(_night("Race | A", "2026-11-16", "19:00", "23:00")))
    pipe.collect(pipe.share(_night("Race | B", "2026-11-16", "20:00", "23:00")))
    stored = {"done": False}

    def store_c(post):
        if not stored["done"] and post.title == "Race | B":
            stored["done"] = True
            pipe.collect(pipe.share(_night("Race | C", "2026-11-16", "21:00", "23:30")))

    _intercept_engine(monkeypatch, store_c)
    pipe.tick()
    assert stored["done"]
    assert pipe.event(item_id)["event_name"] == "Race | B"
    assert pipe.queued(item_id), "C was stored after B was selected: still revised since read"
    monkeypatch.undo()
    monkeypatch.setattr(db, "connect", _yield(pipe.pg))
    pipe.tick()
    after = pipe.event(item_id)
    assert after["event_name"] == "Race | C" and str(after["start_time"]) == "21:00:00"
    assert not pipe.queued(item_id)


def _yield(pg):
    @contextmanager
    def _connect(_settings, **_kwargs):
        yield pg
    return _connect


def test_a_revision_whose_request_fails_is_not_stored_without_it(pipe, monkeypatch):
    """Revision write and re-extract request are one transaction: a failure
    leaves the old record, so the next collection is still a revision."""
    record = pipe.share(_night("Atomic | A", "2026-11-17", "19:00", "23:00"))
    item_id = _first(pipe, record)
    revised = pipe.share(_night("Atomic | B", "2026-11-17", "19:00", "23:00"))

    def boom(*_a, **_k):
        raise RuntimeError("invalidation failed")
    monkeypatch.setattr(content_store, "mark_needs_reextract", boom)
    with pytest.raises(RuntimeError):
        pipe.collect(revised)
    with pipe.pg.cursor() as cur:
        cur.execute("SELECT title FROM source_items WHERE source_item_id = %s", (item_id,))
        assert cur.fetchone()[0] == "Atomic | A"
    monkeypatch.undo()
    monkeypatch.setattr(db, "connect", _yield(pipe.pg))
    assert pipe.collect(revised) == "REVISED"
    pipe.tick()
    assert pipe.event(item_id)["event_name"] == "Atomic | B"


def test_a_lost_request_is_still_found_by_the_signature(pipe):
    """Were the explicit request ever lost (the shape v0.96.41 left 6388 in),
    the recorded signature still says the input moved."""
    item_id = _first(pipe, pipe.share(_night("Lost | A", "2026-11-18", "19:00", "23:00")))
    pipe.collect(pipe.share(_night("Lost | B", "2026-11-18", "19:00", "23:00")))
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET extracted_engine_version = %s "
                    "WHERE source_item_id = %s", (pipe.settings.engine_version, item_id))
    assert pipe.queued(item_id)
    assert content_store.reprocess_backlog(
        pipe.pg, pipe.settings.engine_version)["revised_since_read"] >= 1
    pipe.tick()
    assert pipe.event(item_id)["event_name"] == "Lost | B"


@pytest.mark.parametrize("where", ["engine", "raw_store"])
def test_a_failed_re_read_is_retried_and_never_stamped_current(pipe, monkeypatch, where):
    item_id = _first(pipe, pipe.share(_night("Fail | A", "2026-11-19", "19:00", "23:00")))
    pipe.collect(pipe.share(_night("Fail | B", "2026-11-19", "19:00", "23:00")))
    failures = {"n": 0}

    def fail_once(*_a, **_k):
        failures["n"] += 1
        if failures["n"] == 1:
            raise RuntimeError(f"{where} failed")
    if where == "engine":
        _intercept_engine(monkeypatch, fail_once)
    else:
        real = engine_ingest._refresh_raw_post

        def refresh(*a, **k):
            fail_once()
            return real(*a, **k)
        monkeypatch.setattr(engine_ingest, "_refresh_raw_post", refresh)
    pipe.tick()
    assert pipe.last["reprocess"]["failed"] == 1
    assert pipe.event(item_id)["event_name"] == "Fail | A"
    assert pipe.queued(item_id)
    fresh = engine_ingest.freshness(pipe.settings, pipe.pg, item_id)
    assert fresh["state"] == content_store.REEXTRACTION_PENDING
    pipe.tick()
    assert pipe.event(item_id)["event_name"] == "Fail | B"
    assert pipe.content(item_id)["reprocess_attempts"] == 0


def test_a_re_read_that_keeps_failing_stops_and_says_so(pipe, monkeypatch):
    item_id = _first(pipe, pipe.share(_night("Stall | A", "2026-11-20", "19:00", "23:00")))
    pipe.collect(pipe.share(_night("Stall | B", "2026-11-20", "19:00", "23:00")))

    def always(*_a, **_k):
        raise RuntimeError("broken")
    _intercept_engine(monkeypatch, always)
    for _ in range(content_store.MAX_REPROCESS_ATTEMPTS + 1):
        pipe.tick()
    assert not pipe.queued(item_id)
    fresh = engine_ingest.freshness(pipe.settings, pipe.pg, item_id)
    assert fresh["state"] == content_store.REEXTRACTION_FAILED
    assert content_store.reprocess_backlog(
        pipe.pg, pipe.settings.engine_version)["stalled"] >= 1
    assert pipe.content(item_id)["extraction_outcome"] == content_store.OUTCOME_EXTRACTED
    assert pipe.event(item_id)["event_name"] == "Stall | A"


def test_a_normalization_failure_is_retried_on_the_next_tick(pipe, monkeypatch):
    item_id = _first(pipe, pipe.share(_night("Norm | A", "2026-11-21", "19:00", "23:00")))
    pipe.collect(pipe.share(_night("Norm | B", "2026-11-21", "19:00", "23:00")))
    real = normalization.normalize_candidate
    calls = {"n": 0}

    def once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("normalization failed")
        return real(*a, **k)
    monkeypatch.setattr(normalization, "normalize_candidate", once)
    pipe.tick()
    assert pipe.last["normalize"]["failed"] == 1
    assert pipe.event(item_id)["event_name"] == "Norm | A"
    pipe.tick()
    assert pipe.event(item_id)["event_name"] == "Norm | B"


# --- protections ----------------------------------------------------------------

def _blocked_after_a_body(pipe, unique_n: int):
    """Fetched once, refused afterwards: the K-TANGO 643 shape."""
    url = f"https://k-tango.test/{pipe.unique}/{unique_n}"
    record = {"source_url": url, "title": "공지 K-TANGO 밀롱가",
              "body": "K-TANGO 공지", "acquisition_quality": "METADATA_ONLY"}
    pipe.collect(record)
    item_id = pipe.item_id(url)
    content_store.record_outcome(pipe.pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
        fetched_url=url,
        text="K-TANGO 밀롱가 2026.11.22 20:00-23:00 장소: 스튜디오 오초 회비 10,000원 많이 오세요"))
    pipe.tick()
    content_store.record_outcome(pipe.pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE, fetched_url=url))
    return item_id, record


def test_a_blocked_item_whose_body_is_gone_is_protected_and_shown_as_not_applied(pipe):
    item_id, record = _blocked_after_a_body(pipe, 1)
    before = pipe.event(item_id)
    assert pipe.collect(dict(record, title="공지 K-TANGO 밀롱가 (수정)")) == "REVISED"
    pipe.tick()
    assert pipe.event(item_id) == before
    content = pipe.content(item_id)
    assert content["extraction_outcome"] == content_store.OUTCOME_PRESERVED_BODY_LOST
    assert not pipe.queued(item_id), "protected is a finished state, never a loop"
    fresh = engine_ingest.freshness(pipe.settings, pipe.pg, item_id)
    assert fresh["state"] == content_store.ENGINE_UPDATE_NOT_APPLIED
    assert fresh["basis"] == content_store.BASIS_RECORDED
    assert content_store.FLAG_SOURCE_FETCH_BLOCKED in fresh["flags"]
    assert content_store.FLAG_REVIEW_RECOMMENDED in fresh["flags"]
    pipe.tick()
    assert pipe.last["reprocess"]["reprocessed"] == 0


def test_a_blocked_from_the_start_item_is_current_not_a_warning(pipe):
    url = f"https://blocked.test/{pipe.unique}/1"
    record = {"source_url": url, "title": "11월 23일 밀롱가 20:00-23:00 장소: 스튜디오 오초",
              "body": "11월 23일 밀롱가 20:00-23:00 장소: 스튜디오 오초",
              "acquisition_quality": "METADATA_ONLY"}
    pipe.collect(record)
    item_id = pipe.item_id(url)
    content_store.record_outcome(pipe.pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE, fetched_url=url))
    pipe.tick()
    fresh = engine_ingest.freshness(pipe.settings, pipe.pg, item_id)
    assert fresh["state"] == content_store.EXTRACTION_CURRENT
    assert content_store.FLAG_REVIEW_RECOMMENDED not in fresh["flags"]


def test_a_reviewed_candidate_is_kept_through_a_revision(pipe):
    item_id = _first(pipe, pipe.share(_night("Reviewed | A", "2026-11-24", "19:00", "23:00")))
    before = pipe.event(item_id)
    with pipe.pg.cursor() as cur:
        cur.execute("INSERT INTO human_review_actions (candidate_id, source_item_id, action) "
                    "VALUES (%s, %s, 'EDIT')", (before["candidate_id"], item_id))
    pipe.collect(pipe.share(_night("Reviewed | B", "2026-11-24", "21:00", "23:00")))
    pipe.tick()
    assert pipe.event(item_id)["event_name"] == "Reviewed | A"
    assert pipe.content(item_id)["extraction_outcome"] == content_store.OUTCOME_KEPT_HUMAN_REVIEWED
    assert engine_ingest.freshness(pipe.settings, pipe.pg, item_id)["state"] == \
        content_store.HUMAN_DECISION_KEPT
    assert not pipe.queued(item_id)


@pytest.mark.parametrize("decision", [duplicates.DUPLICATE, duplicates.DISTINCT])
def test_a_human_duplicate_verdict_survives_a_revision(pipe, decision):
    a = _first(pipe, pipe.share(_night("Pair | A", "2026-11-25", "19:00", "23:00"), n=1))
    b = _first(pipe, pipe.share(_night("Pair | A2", "2026-11-25", "19:00", "23:00"), n=2))
    ea, eb = pipe.event(a), pipe.event(b)
    duplicates.record_decision(
        pipe.pg, event_id=ea["event_id"],
        canonical_event_id=eb["event_id"] if decision == duplicates.DUPLICATE else None,
        decision=decision, decided_by=duplicates.HUMAN, rule="TEST", reviewer="tester")
    kept = pipe.event(a)
    pipe.collect(pipe.share(_night("Pair | A (rev)", "2026-11-25", "19:00", "23:00"), n=1))
    pipe.tick()
    after = pipe.event(a)
    assert after["event_id"] == ea["event_id"]
    assert after["event_name"] == "Pair | A (rev)"
    assert (after["canonical_event_id"], after["listing_state"]) == \
        (kept["canonical_event_id"], kept["listing_state"])
    with pipe.pg.cursor() as cur:
        cur.execute("SELECT decided_by, decision FROM event_duplicate_decisions "
                    "WHERE event_id = %s ORDER BY decision_id DESC LIMIT 1", (ea["event_id"],))
        assert cur.fetchone() == (duplicates.HUMAN, decision)


def test_an_approved_venue_alias_still_resolves_after_a_revision(pipe):
    venue = register_venue(pipe.pg, f"Approved Hall {pipe.unique}")
    item_id = _first(pipe, pipe.share(_night("V | A", "2026-11-26", "19:00", "23:00",
                                             place=venue["name"])))
    pipe.collect(pipe.share(_night("V | A (rev)", "2026-11-26", "19:30", "23:00",
                                   place=venue["name"])))
    pipe.tick()
    after = pipe.event(item_id)
    assert after["venue_id"] == venue["venue_id"] and after["venue_status"] == "RESOLVED"


# --- rows finished before v0.96.42 ---------------------------------------------

def _as_legacy(pipe, item_id):
    """What every Production row looks like right after migration 050."""
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET extracted_input_signature = NULL, "
                    "  extraction_outcome = NULL, applied_engine_version = NULL "
                    "WHERE source_item_id = %s", (item_id,))


def test_an_unchanged_legacy_row_is_signed_and_not_re_read(pipe):
    item_id = _first(pipe, pipe.share(_night("Legacy | A", "2026-11-27", "19:00", "23:00")))
    _as_legacy(pipe, item_id)
    pipe.tick()
    assert pipe.last["reconcile"]["signed"] >= 1
    assert pipe.last["reprocess"]["reprocessed"] == 0
    assert pipe.content(item_id)["extracted_input_signature"] == \
        content_store.input_signature(pipe.pg, item_id)


def test_a_legacy_row_revised_under_v0_96_41_is_found_and_read(pipe):
    """6388's shape: the revision is stored, settle_full_body() stamped it,
    and the row still reads the running engine - v0.96.41's end state."""
    item_id = _first(pipe, pipe.share(_night("La Ventana | 라비오스", "2026-10-23", "20:00",
                                             "00:00", end_day="2026-10-24", dj="x")))
    _as_legacy(pipe, item_id)
    revised = pipe.share(_night("La Ventana | 라비오스", "2026-10-23", "20:00", "00:00",
                                end_day="2026-10-24", dj="민트"))
    pipe.collect(revised)
    with pipe.pg.cursor() as cur:  # undo the request v0.96.41 never made
        cur.execute("UPDATE source_item_content SET extracted_engine_version = %s "
                    "WHERE source_item_id = %s", (pipe.settings.engine_version, item_id))
    assert not pipe.queued(item_id)
    pipe.tick()
    assert item_id in pipe.last["reconcile"]["requeued_ids"]
    assert pipe.event(item_id)["dj"] == "민트"


def test_a_legacy_title_already_read_after_its_revision_only_fixes_the_raw_store(pipe):
    """44 Production rows: re-extracted after their title revision (by the 1.16
    bump), the engine's raw store just never kept the new title."""
    record = pipe.share(_night("Title | New", "2026-11-28", "19:00", "23:00"))
    item_id = _first(pipe, record)
    _as_legacy(pipe, item_id)
    import sqlite3

    from runtime import engine_adapter
    con = sqlite3.connect(engine_adapter.engine_db_path(pipe.settings))
    con.execute("UPDATE raw_posts SET title = 'Title | Old' WHERE source_url = ?",
                (record["source_url"],))
    con.commit()
    con.close()
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_items SET collected_at = now() - interval '1 day' "
                    "WHERE source_item_id = %s", (item_id,))
        cur.execute("UPDATE source_item_content SET reprocessed_at = now() "
                    "WHERE source_item_id = %s", (item_id,))
    pipe.tick()
    assert pipe.last["reconcile"]["raw_title_refreshed"] == 1
    assert pipe.last["reprocess"]["reprocessed"] == 0
    assert pipe.raw_post(record["source_url"])["title"] == "Title | New"


def test_a_legacy_title_revised_after_its_last_read_is_read(pipe):
    """6503's shape: the title moved after the last pass."""
    record = pipe.share(_night("Title2 | Old", "2026-11-29", "19:00", "23:00"))
    item_id = _first(pipe, record)
    _as_legacy(pipe, item_id)
    revised = pipe.share(_night("Title2 | New", "2026-11-29", "19:00", "23:00"))
    pipe.collect(revised)
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET extracted_engine_version = %s, "
                    "  reprocessed_at = now() - interval '1 day' WHERE source_item_id = %s",
                    (pipe.settings.engine_version, item_id))
    pipe.tick()
    assert item_id in pipe.last["reconcile"]["requeued_ids"]
    assert pipe.event(item_id)["event_name"] == "Title2 | New"


# --- the freshness diagnostic ----------------------------------------------------

V = "1.16"


@pytest.mark.parametrize("row, kwargs, state", [
    ({"acquisition_status": "FETCHED_FULL", "extracted_engine_version": V,
      "extraction_outcome": "EXTRACTED", "applied_engine_version": V},
     {}, content_store.EXTRACTION_CURRENT),
    ({"acquisition_status": "FETCHED_FULL", "extracted_engine_version": None},
     {}, content_store.REEXTRACTION_PENDING),
    ({"acquisition_status": "FETCHED_FULL", "extracted_engine_version": V,
      "extraction_outcome": "EXTRACTED"},
     {"revised_since_read": True}, content_store.REEXTRACTION_PENDING),
    ({"acquisition_status": "FETCHED_FULL", "extracted_engine_version": "1.15",
      "reprocess_attempts": 3, "reprocess_error": "boom"},
     {}, content_store.REEXTRACTION_FAILED),
    ({"acquisition_status": "FETCH_BLOCKED", "extracted_engine_version": V},
     {"body_lost": False, "used_image_ocr": False}, content_store.EXTRACTION_CURRENT),
    ({"acquisition_status": "FETCH_BLOCKED", "extracted_engine_version": V},
     {"body_lost": True, "used_image_ocr": True}, content_store.ENGINE_UPDATE_NOT_APPLIED),
    ({"acquisition_status": "FETCH_BLOCKED", "extracted_engine_version": V,
      "extraction_outcome": "PRESERVED_IMAGE_EVIDENCE_LOST"},
     {}, content_store.ENGINE_UPDATE_NOT_APPLIED),
    ({"acquisition_status": "FETCH_BLOCKED", "extracted_engine_version": V},
     {"body_lost": False, "used_image_ocr": True}, content_store.REEXTRACTION_NOT_VERIFIED),
    ({"acquisition_status": "FETCH_BLOCKED", "extracted_engine_version": V},
     {}, content_store.REEXTRACTION_NOT_VERIFIED),
    ({"acquisition_status": "FETCHED_FULL", "extracted_engine_version": V},
     {"reviewed": True}, content_store.HUMAN_DECISION_KEPT),
])
def test_freshness_states(row, kwargs, state):
    args = {"readable": True, "revised_since_read": False, **kwargs}
    fresh = content_store.extraction_freshness(row, V, **args)
    assert fresh["state"] == state
    if not row.get("applied_engine_version"):
        assert fresh["last_applied_engine_version"] == content_store.UNKNOWN


def test_freshness_of_nothing_readable():
    fresh = content_store.extraction_freshness({"acquisition_status": "METADATA_ONLY"}, V,
                                               readable=False, revised_since_read=False)
    assert fresh["state"] == content_store.NOT_EXTRACTED


def test_an_ordinary_blocked_item_never_gets_a_warning_flag():
    fresh = content_store.extraction_freshness(
        {"acquisition_status": "FETCH_BLOCKED", "extracted_engine_version": V}, V,
        readable=True, revised_since_read=False, body_lost=False, used_image_ocr=False,
        has_events=True)
    assert fresh["state"] == content_store.EXTRACTION_CURRENT
    assert fresh["flags"] == [content_store.FLAG_SOURCE_FETCH_BLOCKED]


def test_an_unknown_outcome_is_refused():
    with pytest.raises(ValueError):
        content_store.mark_reprocessed(None, 1, outcome="APPLIED_PROBABLY")


# --- the console ------------------------------------------------------------------

@pytest.fixture
def client(pipe, monkeypatch):
    from starlette.testclient import TestClient

    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", "dancemate")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(app_module, "_settings", None)
    test_client = TestClient(app_module.app, raise_server_exceptions=False)
    test_client.auth = ("dancemate", "test-admin-password")
    return test_client


def test_the_intake_page_and_api_show_the_same_freshness(pipe, client):
    item_id, record = _blocked_after_a_body(pipe, 2)
    pipe.collect(dict(record, title="공지 K-TANGO 밀롱가 (수정)"))
    pipe.tick()
    page = client.get(f"/admin/intake/{item_id}")
    assert page.status_code == 200
    assert "Extraction freshness" in page.text
    assert content_store.ENGINE_UPDATE_NOT_APPLIED in page.text
    assert "Review recommended" in page.text
    api = client.get(f"/api/admin/intake/{item_id}")
    assert api.status_code == 200
    assert api.json()["freshness"]["state"] == content_store.ENGINE_UPDATE_NOT_APPLIED
    listed = client.get("/admin/intake?extraction=NOT_APPLIED")
    assert listed.status_code == 200 and f"/admin/intake/{item_id}" in listed.text
    assert client.get("/admin/intake?extraction=DROP%20TABLE").status_code == 200


def test_the_diagnostic_writes_nothing(pipe, client):
    item_id = _first(pipe, pipe.share(_night("RO | A", "2026-11-30", "19:00", "23:00")))
    before = pipe.content(item_id)
    assert client.get(f"/admin/intake/{item_id}").status_code == 200
    assert client.get(f"/api/admin/intake/{item_id}").status_code == 200
    assert pipe.content(item_id) == before
