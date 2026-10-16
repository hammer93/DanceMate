"""v0.96.35: a page that has not changed, read better than it was before.

The collector's judgement about an item - `known_event_type` since v0.82.5,
`source_category` since v0.96.10, `source_night_fallback` from this release -
is not content, so `RawItem.content_hash()` has never hashed it. That is right:
collecting the same post twice must be a duplicate, and a judgement is our
reading of the page rather than something the upstream edited.

But it has to be able to *change*. A collector that learns to recognise
something it used to miss produces a better record for a page whose text has
not moved at all, and before this `store_item()` returned DUPLICATE and left
the stored `raw` exactly as it was - so the improvement reached newly
discovered pages only, and the 68 TangoNOW share pages already collected would
have stayed unreadable forever.

The two ways out that were rejected, and why these tests exist to keep them
rejected: writing something into the body to shift its hash puts a word the
page never said in front of the extractor, and it re-keys every item in the
source to move a fact about some of them. And `ingest_state = PENDING` does
nothing at all, because `database.persist_raw_post()` keys a post on its own
URL and `engine_ingest.ingest_pending()` extracts only a new post - which is
why the item goes back to the *re-extract* queue instead.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime import acquisition, content_store, intake, sources

URL = "https://ktnow.kr/e/occ_fb4d4ec5d68dd186986b68e391cd3d1cc5cf5b3a786eb2646f086c1082f94ab1"
# Verbatim: source item 6216, SRC-W-002, collected 2026-10-13.
TITLE = "PISTA | The PISTA"
BODY = "2026년 10월 17일 시간: 19:00~23:00 DJ: Eddy 주최: PISTA"
EVIDENCE = "TangoNOW share page: one dated night 2026-10-17 19:00~23:00, DJ Eddy"


def _item(**raw_extra) -> intake.RawItem:
    """The share record as the collector hands it over, before and after."""
    raw = {
        "source_url": URL, "title": TITLE, "body": BODY, "platform": "WEB",
        "source_id": "SRC-W-002", "published_at": None,
        "acquisition_quality": "FETCHED_FULL",
    }
    raw.update(raw_extra)
    return intake.RawItem(external_id=URL, url=URL, title=TITLE, body=BODY,
                          published_at=None, raw=raw)


JUDGED = {"source_night_fallback": "SOCIAL", "night_evidence": EVIDENCE}


# --- the hash still ignores the judgement (pure) ----------------------------

def test_the_judgement_does_not_change_the_content_hash():
    """Otherwise re-collecting an unchanged page would not be a duplicate, and
    the whole source would re-key on the cycle after any collector change."""
    assert _item().content_hash() == _item(**JUDGED).content_hash()


def test_the_judgement_keys_are_the_named_ones_only():
    """A collector's record may legitimately carry volatile fields - a signed
    image URL, a discovery query - and none of those is a reason to re-read a
    post. So this is a declared list, not "did raw change at all"."""
    assert intake.JUDGEMENT_KEYS == (
        "known_event_type", "class_event_opt_in", "source_category",
        "source_night_fallback", "night_evidence")


def test_absent_and_null_are_different_answers():
    """A collector that has gone quiet about a judgement has changed its mind
    as much as one that has changed the value."""
    assert intake._judgement({}) != intake._judgement(
        {"source_night_fallback": None})
    assert intake._judgement({"a": 1}) == {}


def test_a_judgement_is_read_out_of_raw_json_as_well_as_a_dict():
    """`source_items.raw` comes back as a dict from jsonb, but a caller holding
    the text must not silently read as "no judgement at all"."""
    assert intake._judgement('{"source_night_fallback": "SOCIAL"}') == {
        "source_night_fallback": "SOCIAL"}
    assert intake._judgement("not json") == {}
    assert intake._judgement(None) == {}
    assert intake._judgement(7) == {}


# --- database-backed behaviour ---------------------------------------------

@pytest.fixture
def source(pg, unique):
    return sources.create_source(
        pg, source_key=f"SRC-W-{unique}", name="TangoNOW judgement test",
        platform="WEB", source_role="AGGREGATOR", queries=[],
        config={"parser": "tangonow_share_pages"},
    )


def _stored(pg, source):
    rows = intake.recent_items(pg, source_id=source["source_id"])
    assert len(rows) == 1, "a revision updates the row rather than adding one"
    return rows[0]


def _engine_version(pg, source_item_id):
    with pg.cursor() as cur:
        cur.execute("SELECT extracted_engine_version FROM source_item_content "
                    "WHERE source_item_id = %s", (source_item_id,))
        row = cur.fetchone()
        return row[0] if row else None


@pytest.fixture
def already_read(pg, source):
    """The state this release found: the page collected, ingested, and read by
    the running engine, with no judgement on it."""
    assert intake.store_item(pg, source["source_id"], _item()) == "NEW"
    item = _stored(pg, source)
    intake.mark_ingested(pg, item["source_item_id"])
    content_store.mark_extracted_engine_version(
        pg, item["source_item_id"], "1.13")
    return item["source_item_id"]


def test_a_new_judgement_on_an_unchanged_page_is_a_revision(pg, source, already_read):
    assert intake.store_item(pg, source["source_id"], _item(**JUDGED)) == "REVISED"


def test_the_judgement_is_stored_where_the_engine_reads_it(pg, source, already_read):
    """`engine_ingest._to_raw_post()` reads it off `raw`, the same way it has
    read `known_event_type` since v0.82.5."""
    intake.store_item(pg, source["source_id"], _item(**JUDGED))
    raw = _stored(pg, source)["raw"]
    assert raw["source_night_fallback"] == "SOCIAL"
    assert raw["night_evidence"] == EVIDENCE


def test_the_item_goes_back_to_the_re_extract_queue(pg, source, already_read):
    """The only route that can actually re-read an item we already hold."""
    assert _engine_version(pg, already_read) == "1.13"
    intake.store_item(pg, source["source_id"], _item(**JUDGED))
    assert _engine_version(pg, already_read) is None
    queued = content_store.needing_reprocess(pg, engine_version="1.14", limit=50)
    assert already_read in [row["source_item_id"] for row in queued]


def test_the_text_the_engine_reads_does_not_move(pg, source, already_read):
    """The whole reason this mechanism exists rather than a body edit: the
    engine re-reads exactly the text it read before, so it cannot produce a new
    date, time, venue or fee - only the classification it was refusing."""
    before = _stored(pg, source)
    intake.store_item(pg, source["source_id"], _item(**JUDGED))
    after = _stored(pg, source)
    for field in ("title", "body", "url", "published_at", "content_hash"):
        assert after[field] == before[field], field
    assert after["source_item_id"] == before["source_item_id"]


def test_the_settled_body_is_not_disturbed(pg, source, already_read):
    content = content_store.get(pg, already_read)
    assert content["extracted_text"] == BODY
    assert content["acquisition_status"] == acquisition.FETCHED_FULL
    intake.store_item(pg, source["source_id"], _item(**JUDGED))
    after = content_store.get(pg, already_read)
    assert after["extracted_text"] == BODY
    assert after["acquisition_status"] == acquisition.FETCHED_FULL


def test_collecting_the_same_judgement_again_is_a_duplicate(pg, source, already_read):
    """Idempotent, which is the difference between a fix and a churn: an
    unchanged page must not be re-read on every three-hourly cycle forever."""
    assert intake.store_item(pg, source["source_id"], _item(**JUDGED)) == "REVISED"
    content_store.mark_reprocessed(pg, already_read, engine_version="1.14")
    for _ in range(3):
        assert intake.store_item(
            pg, source["source_id"], _item(**JUDGED)) == "DUPLICATE"
    assert _engine_version(pg, already_read) == "1.14"


def test_a_page_with_no_judgement_either_way_is_still_a_duplicate(pg, source,
                                                                  already_read):
    """The 40 share pages the policy declines, and every item of every other
    source: nothing about them changes."""
    for _ in range(3):
        assert intake.store_item(
            pg, source["source_id"], _item()) == "DUPLICATE"
    assert _engine_version(pg, already_read) == "1.13"


def test_a_withdrawn_judgement_is_also_a_revision(pg, source, already_read):
    """If the provider stops stating a DJ, or an operator retires a venue, the
    page stops qualifying - and the item has to be re-read to lose the reading
    it was given, not keep it because nobody noticed."""
    intake.store_item(pg, source["source_id"], _item(**JUDGED))
    content_store.mark_reprocessed(pg, already_read, engine_version="1.14")
    assert intake.store_item(pg, source["source_id"], _item()) == "REVISED"
    assert "source_night_fallback" not in _stored(pg, source)["raw"]
    assert _engine_version(pg, already_read) is None


def test_an_edited_page_is_still_an_ordinary_revision(pg, source, already_read):
    """v0.74's own path, untouched: real content change, re-queued for ingest."""
    edited = intake.RawItem(
        external_id=URL, url=URL, title="PISTA | The PISTA (취소)", body=BODY,
        published_at=None, raw={"source_url": URL, "body": BODY,
                                "acquisition_quality": "FETCHED_FULL"})
    assert intake.store_item(pg, source["source_id"], edited) == "REVISED"
    assert _stored(pg, source)["ingest_state"] == intake.INGEST_PENDING


def test_a_judgement_revision_does_not_re_queue_ingest(pg, source, already_read):
    """Re-ingesting an item we already hold is a no-op - persist_raw_post()
    returns is_new=False and nothing is extracted - so moving the row back to
    PENDING would only make the ingest counters lie about work being done."""
    intake.store_item(pg, source["source_id"], _item(**JUDGED))
    assert _stored(pg, source)["ingest_state"] == intake.INGEST_DONE


def test_a_first_collection_carrying_a_judgement_is_simply_new(pg, source):
    """A page discovered after this release needs none of the above."""
    assert intake.store_item(pg, source["source_id"], _item(**JUDGED)) == "NEW"
    assert _stored(pg, source)["raw"]["source_night_fallback"] == "SOCIAL"


def test_an_item_that_was_never_read_is_left_alone(pg, source):
    """No content row, nothing to withdraw: the update must not raise."""
    assert intake.store_item(pg, source["source_id"], _item()) == "NEW"
    item = _stored(pg, source)
    with pg.cursor() as cur:
        cur.execute("DELETE FROM source_item_content WHERE source_item_id = %s",
                    (item["source_item_id"],))
    assert intake.store_item(pg, source["source_id"], _item(**JUDGED)) == "REVISED"


def test_an_older_judgement_key_behaves_the_same_way(pg, source, already_read):
    """Nothing here is specific to this release's key. A collector correcting
    `known_event_type` or `source_category` on an unchanged post gets the same
    re-read, which is the behaviour v0.96.10 silently did not have."""
    assert intake.store_item(
        pg, source["source_id"], _item(known_event_type="MILONGA")) == "REVISED"
    assert _engine_version(pg, already_read) is None
