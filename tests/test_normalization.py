"""Event normalization: engine candidates become searchable event instances."""

from __future__ import annotations

from datetime import date, time

import pytest

from runtime import normalization, review


# --- keys -------------------------------------------------------------------

def test_name_key_strips_the_date_out_of_a_title():
    """The same weekly milonga is titled with a different date every week."""
    assert (normalization.name_key("💜9/5(토) THE PISTA MILONGA")
            == normalization.name_key("9/12(토) THE PISTA MILONGA"))
    assert (normalization.name_key("9월 12일 로라밀롱가 버블 버블")
            == normalization.name_key("로라밀롱가 버블 버블"))


def test_name_key_keeps_different_events_apart():
    assert normalization.name_key("더 피스타 밀롱가") != normalization.name_key("로라밀롱가")


def test_a_resolved_venue_compares_by_id_and_an_unresolved_one_by_text():
    """Two spellings of one studio are the same place once someone has said so.

    Two unrecognised strings are not: we have no grounds to call them equal.
    """
    assert normalization.venue_key(7, "PISTA") == normalization.venue_key(7, "피스타")
    assert normalization.venue_key(None, "PISTA") != normalization.venue_key(None, "피스타")
    assert normalization.venue_key(None, "  PISTA ") == normalization.venue_key(None, "pista")
    assert normalization.venue_key(None, None) is None


def test_identity_key_is_date_place_and_start_time():
    key = normalization.identity_key(date(2026, 9, 5), "venue:7", time(19, 30))
    assert key == "2026-09-05|venue:7|19:30"


def test_identity_key_records_what_is_missing_rather_than_omitting_it():
    """Two events that both lack a time must not collide with each other by
    accident of formatting."""
    assert normalization.identity_key(date(2026, 9, 5), None, None) == "2026-09-05|-|-"


def test_series_key_groups_recurrences_without_merging_them():
    first = normalization.series_key("venue:7", date(2026, 9, 5), "9/5(토) 더 피스타 밀롱가")
    second = normalization.series_key("venue:7", date(2026, 9, 12), "9/12(토) 더 피스타 밀롱가")
    assert first == second
    # ... while the instances stay distinct, because the date is not in the key.
    assert (normalization.identity_key(date(2026, 9, 5), "venue:7", time(20, 0))
            != normalization.identity_key(date(2026, 9, 12), "venue:7", time(20, 0)))


def test_series_key_needs_both_a_place_and_a_name():
    assert normalization.series_key(None, date(2026, 9, 5), "밀롱가") is None
    assert normalization.series_key("venue:7", date(2026, 9, 5), "") is None


def test_a_weekday_change_is_a_different_series():
    saturday = normalization.series_key("venue:7", date(2026, 9, 5), "밀롱가")
    sunday = normalization.series_key("venue:7", date(2026, 9, 6), "밀롱가")
    assert saturday != sunday


# --- SQL --------------------------------------------------------------------

def _candidate(unique: str, **overrides):
    base = {
        "candidate_id": int(unique[-6:]),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/test/{unique}",
        "event_name": "테스트 밀롱가",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": "아미고스튜디오",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
    }
    base.update(overrides)
    return base


def _salsa_board_item(pg, unique: str, title: str, body: str) -> int:
    from runtime import intake, sources

    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'SALSA'")
        salsa_id = cur.fetchone()[0]
    source = sources.create_source(
        pg, source_key=f"test-board-{unique}", name="test public Salsa board",
        platform="DAUM_CAFE", source_role="COMMUNITY",
        url=f"https://cafe.daum.net/test/{unique}", genre_id=salsa_id,
        authority_level="PRIMARY_ORGANIZER",
        config={"parser": "daum_cafe_board", "board_type": "EVENT_PRIMARY"},
    )
    external_id = f"article-{unique}"
    assert intake.store_item(
        pg, source["source_id"], intake.RawItem(
            external_id=external_id, url=f"https://cafe.daum.net/test/{unique}/1",
            title=title, body=body,
            raw={"acquisition_quality": "FETCHED_FULL"},
        ),
    ) == "NEW"
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id FROM source_items WHERE source_id=%s AND external_id=%s",
                    (source["source_id"], external_id))
        return cur.fetchone()[0]


def _naver_board_item(pg, unique: str, *, authority: str) -> int:
    from runtime import intake, sources

    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'SALSA'")
        salsa_id = cur.fetchone()[0]
        cur.execute("SELECT region_id FROM regions WHERE code = 'KR-SEOUL'")
        seoul_id = cur.fetchone()[0]
    source = sources.create_source(
        pg, source_key=f"test-naver-board-{authority}-{unique}",
        name=f"test Naver board {authority} {unique}", platform="NAVER_CAFE",
        source_role="COMMUNITY", url=f"https://cafe.naver.com/test{unique}",
        genre_id=salsa_id, region_id=seoul_id, authority_level=authority,
        queries=["살사 정모"], config={
            "board_type": "EVENT_PRIMARY", "cafe_name_hint": "테스트 살사",
            "url_contains": [f"test{unique}"],
        },
    )
    assert intake.store_item(
        pg, source["source_id"], intake.RawItem(
            external_id=f"naver-{authority}-{unique}",
            url=f"https://cafe.naver.com/test{unique}/1",
            title="서울 살사 정모", body="2026년 9월 20일 살사 정모",
            raw={"acquisition_quality": "METADATA_ONLY"},
        ),
    ) == "NEW"
    with pg.cursor() as cur:
        cur.execute("SELECT source_item_id FROM source_items WHERE source_id=%s",
                    (source["source_id"],))
        return cur.fetchone()[0]


def test_tightly_bounded_official_naver_board_can_supply_its_region(pg, unique, seoul_id):
    item_id = _naver_board_item(pg, unique, authority="PRIMARY_ORGANIZER")
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, source_item_id=item_id, event_type="SOCIAL",
                       event_name="서울 살사 정모", venue=None),
    )
    assert stored["venue_status"] == normalization.VENUE_ABSENT
    assert stored["region_id"] == seoul_id


def test_secondary_naver_search_never_supplies_its_source_region(pg, unique):
    item_id = _naver_board_item(pg, unique, authority="SECONDARY")
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, source_item_id=item_id, event_type="SOCIAL",
                       event_name="서울 살사 정모", venue=None),
    )
    assert stored["region_id"] is None


def test_board_source_salsa_does_not_make_bachata_only_article_salsa(pg, unique):
    item_id = _salsa_board_item(
        pg, unique, "Best Latin Amigos gathering",
        "7:20 Merengue; 8:00 Bachata social. No other named dance.",
    )
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, source_item_id=item_id, event_type="SOCIAL",
                       event_name="Best Latin Amigos gathering"),
        genre_hints=["BACHATA"],
    )
    with pg.cursor() as cur:
        cur.execute("SELECT g.code FROM event_genres eg JOIN genres g ON g.genre_id=eg.genre_id "
                    "WHERE eg.event_id=%s", (stored["event_id"],))
        codes = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT code FROM genres WHERE genre_id=%s", (stored["genre_id"],))
        primary = cur.fetchone()[0]
    assert primary == "BACHATA"
    assert codes == {"BACHATA"}


def test_board_salsa_bachata_article_keeps_both_explicit_genres(pg, unique):
    item_id = _salsa_board_item(pg, unique, "Salsa+Bachata party",
                                "Dated Salsa and Bachata party")
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, source_item_id=item_id, event_type="SOCIAL"),
        genre_hints=["BACHATA"],
    )
    with pg.cursor() as cur:
        cur.execute("SELECT g.code FROM event_genres eg JOIN genres g ON g.genre_id=eg.genre_id "
                    "WHERE eg.event_id=%s", (stored["event_id"],))
        codes = {row[0] for row in cur.fetchall()}
    assert codes == {"SALSA", "BACHATA"}


def test_daum_mobile_chrome_does_not_copy_community_genres_to_event(pg, unique):
    item_id = _salsa_board_item(
        pg, unique, "Wednesday gathering",
        "[Community Salsa Bachata] 앱으로보기 목록 댓글쓰기",
    )
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, source_item_id=item_id, event_type="SOCIAL"),
        genre_hints=["BACHATA"],
    )
    assert stored["genre_id"] is None
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_genres WHERE event_id=%s", (stored["event_id"],))
        assert cur.fetchone()[0] == 0


def test_actual_board_poster_names_salsa_despite_mobile_chrome(pg, unique):
    item_id = _salsa_board_item(
        pg, unique, "Wednesday gathering",
        "[Community Salsa Bachata] 앱으로보기 목록 댓글쓰기",
    )
    with pg.cursor() as cur:
        cur.execute("INSERT INTO source_item_image (source_item_id,image_url,ocr_text) "
                    "VALUES (%s,%s,%s)",
                    (item_id, f"https://example.com/poster/{unique}.png",
                     "Salsa 3 : Bachata 3, 2026-09-18"))
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, source_item_id=item_id, event_type="SOCIAL"),
        genre_hints=["BACHATA"],
    )
    with pg.cursor() as cur:
        cur.execute("SELECT g.code FROM event_genres eg JOIN genres g ON g.genre_id=eg.genre_id "
                    "WHERE eg.event_id=%s", (stored["event_id"],))
        codes = {row[0] for row in cur.fetchall()}
    assert codes == {"SALSA", "BACHATA"}


def test_ambiguous_board_clock_is_not_advertised_as_morning(pg, unique):
    item_id = _salsa_board_item(pg, unique, "Salsa social",
                                "7:20~8:00 Salsa social; no AM/PM")
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, source_item_id=item_id, event_type="SOCIAL",
                       start_time="07:20", end_time="08:00",
                       time_evidence="TEXT"),
        time_ambiguous=True,
    )
    assert stored["start_time"] is None
    assert stored["end_time"] is None
    assert stored["time_evidence"] is None
    corrected = normalization.normalize_candidate(
        pg, _candidate(unique, source_item_id=item_id, event_type="SOCIAL",
                       start_time="07:20", end_time="08:00"),
        time_ambiguous=True,
        review_state={"review_state": "EDITED",
                      "corrected_json": {"start_time": "21:20", "end_time": "22:00"}},
    )
    assert corrected["start_time"].isoformat() == "21:20:00"
    assert corrected["time_evidence"] == "HUMAN"


def test_a_candidate_without_a_date_is_not_an_event_instance(pg, unique):
    """A post we could not place on a calendar stays in review rather than
    becoming a row with a made-up day."""
    stored = normalization.normalize_candidate(pg, _candidate(unique, event_date=None))
    assert stored is None


def test_reviewed_blank_ocr_clock_is_not_recorded_as_human_time(pg, unique):
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, start_time="09:10", end_time="12:00",
                       time_evidence="IMAGE_OCR"),
        review_state={
            "review_state": "EDITED",
            "corrected_json": {"start_time": None, "end_time": None},
        },
    )
    assert stored["start_time"] is None
    assert stored["end_time"] is None
    assert stored["time_evidence"] is None
    assert stored["field_origin"]["start_time"] == "HUMAN"


def test_an_unrecognised_venue_is_unresolved_and_queued(pg, unique):
    venue_text = f"미등록 스튜디오 {unique}"
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, venue=venue_text),
    )
    assert stored["venue_status"] == normalization.VENUE_UNRESOLVED
    assert stored["venue_id"] is None
    assert stored["venue_text"] == venue_text

    queued = [v for v in normalization.unresolved_venues(pg)
              if v["venue_text"] == venue_text]
    assert len(queued) == 1


def test_normalizing_never_creates_a_venue(pg, unique):
    """A typo must not become a permanent master record."""
    from runtime import master_data

    before = len(master_data.list_venues(pg))
    normalization.normalize_candidate(pg, _candidate(unique, venue=f"오타 스튜디오 {unique}"))
    assert len(master_data.list_venues(pg)) == before


def test_a_known_alias_resolves_to_the_venue(pg, unique, seoul_id):
    from runtime import master_data

    venue = master_data.create_venue(pg, name=f"엔빠스 {unique}", region_id=seoul_id)
    master_data.add_venue_alias(pg, venue_id=venue["venue_id"], alias=f"EnPaz {unique}")

    stored = normalization.normalize_candidate(
        pg, _candidate(unique, venue=f"EnPaz {unique}"),
    )
    assert stored["venue_status"] == normalization.VENUE_RESOLVED
    assert stored["venue_id"] == venue["venue_id"]
    assert stored["region_id"] == seoul_id


def test_the_bracketed_form_resolves_through_the_alias_candidates(pg, unique, seoul_id):
    """The extractor keeps 엔빠스(EnPaz Tango Studio) whole and offers its parts."""
    from runtime import master_data

    # create_venue registers the venue's own name as an alias, so this venue is
    # findable by "엔빠스 {unique}" and by nothing else.
    venue = master_data.create_venue(pg, name=f"엔빠스 {unique}", region_id=seoul_id)

    stored = normalization.normalize_candidate(
        pg,
        _candidate(unique, venue=f"엔빠스 {unique}(EnPaz Tango Studio)"),
        alias_candidates=[f"엔빠스 {unique}(EnPaz Tango Studio)",
                          f"엔빠스 {unique}", "EnPaz Tango Studio"],
    )
    assert stored["venue_status"] == normalization.VENUE_RESOLVED
    assert stored["venue_id"] == venue["venue_id"]


def test_linking_an_unresolved_venue_updates_the_events_that_were_waiting(pg, unique, seoul_id):
    from runtime import master_data

    venue_text = f"미등록 스튜디오 {unique}"
    stored = normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    assert stored["venue_status"] == normalization.VENUE_UNRESOLVED

    venue = master_data.create_venue(pg, name=f"실제 스튜디오 {unique}", region_id=seoul_id)
    entry = next(v for v in normalization.unresolved_venues(pg)
                 if v["venue_text"] == venue_text)

    result = normalization.link_unresolved_venue(
        pg, entry["unresolved_venue_id"], venue["venue_id"],
    )
    assert result["events_updated"] == 1

    updated = normalization.get(pg, stored["event_id"])
    assert updated["venue_status"] == normalization.VENUE_RESOLVED
    assert updated["venue_id"] == venue["venue_id"]
    # The identity key contains the venue, so it has to have been rebuilt.
    assert updated["identity_key"] != stored["identity_key"]
    assert f"venue:{venue['venue_id']}" in updated["identity_key"]


def test_linking_records_the_string_as_an_alias_so_it_resolves_next_time(pg, unique, seoul_id):
    from runtime import master_data

    venue_text = f"미등록 스튜디오 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    venue = master_data.create_venue(pg, name=f"실제 스튜디오 {unique}", region_id=seoul_id)
    entry = next(v for v in normalization.unresolved_venues(pg)
                 if v["venue_text"] == venue_text)
    normalization.link_unresolved_venue(pg, entry["unresolved_venue_id"], venue["venue_id"])

    assert master_data.resolve_venue(pg, venue_text)["venue_id"] == venue["venue_id"]


def test_linking_a_raw_text_that_already_matches_a_seeded_alias_still_resolves(pg, unique, seoul_id):
    """Found live (v0.83.1): grouping two unresolved rows for one new venue -
    "El Tango (엘땅고)" (create_and_link, seeds the venue's own name as an
    alias) and "EL TANGO" (link_existing right after) - normalise to the same
    alias. The duplicate alias insert must not poison the transaction the
    UPDATE below it runs in, or the second row never resolves."""
    from runtime import master_data

    venue_name = f"El Tango {unique}"
    venue_text = venue_name  # normalises identically to the venue's own name
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    venue = master_data.create_venue(pg, name=venue_name, region_id=seoul_id)
    entry = next(v for v in normalization.unresolved_venues(pg)
                 if v["venue_text"] == venue_text)

    result = normalization.link_unresolved_venue(
        pg, entry["unresolved_venue_id"], venue["venue_id"],
    )
    assert result["events_updated"] == 1

    linked_entry = normalization.unresolved_venue(pg, entry["unresolved_venue_id"])
    assert linked_entry["state"] == "LINKED"


def test_the_primary_genre_gets_an_event_genres_row(pg, unique):
    """v0.91.0 PHASE 6: normalize_candidate() always maintains a real
    event_genres row for the primary genre, not just events.genre_id -
    that's what lets a genre-filtered query use one relation for both the
    primary and any secondary genres."""
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    assert stored["genre_id"] is not None
    with pg.cursor() as cur:
        cur.execute(
            "SELECT genre_id, origin FROM event_genres WHERE event_id = %s",
            (stored["event_id"],),
        )
        rows = cur.fetchall()
    assert (stored["genre_id"], "AUTO") in rows


def test_a_genre_hint_adds_a_secondary_event_genres_row(pg, unique):
    """Real shape: SRC-D-020 item 2100's own title names Salsa and Bachata -
    the primary stays whatever the source/event_type says, and the hint adds
    a second, real, queryable relation alongside it."""
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'BACHATA'")
        bachata_id = cur.fetchone()[0]
    stored = normalization.normalize_candidate(
        pg, _candidate(unique), genre_hints=["BACHATA"],
    )
    with pg.cursor() as cur:
        cur.execute(
            "SELECT genre_id, origin FROM event_genres WHERE event_id = %s",
            (stored["event_id"],),
        )
        rows = dict(cur.fetchall())
    assert rows.get(bachata_id) == "AUTO"
    assert rows.get(stored["genre_id"]) == "AUTO"


def test_a_stale_hint_is_removed_on_reprocess(pg, unique):
    """A reprocessed post whose fuller text no longer names a second genre
    must not leave a false relation behind - PHASE 6's explicit "no stale
    hints" requirement."""
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'BACHATA'")
        bachata_id = cur.fetchone()[0]
    stored = normalization.normalize_candidate(
        pg, _candidate(unique), genre_hints=["BACHATA"],
    )
    with pg.cursor() as cur:
        cur.execute(
            "SELECT genre_id FROM event_genres WHERE event_id = %s AND origin = 'AUTO'",
            (stored["event_id"],),
        )
        assert bachata_id in {r[0] for r in cur.fetchall()}

    normalization.normalize_candidate(pg, _candidate(unique), genre_hints=None)
    with pg.cursor() as cur:
        cur.execute(
            "SELECT genre_id FROM event_genres WHERE event_id = %s AND origin = 'AUTO'",
            (stored["event_id"],),
        )
        remaining = {r[0] for r in cur.fetchall()}
    assert bachata_id not in remaining
    assert stored["genre_id"] in remaining


def test_a_human_confirmed_genre_survives_a_reprocess_with_different_hints(pg, unique):
    """The one thing a reprocess must never delete: a HUMAN-origin row,
    regardless of what the engine's own hints say this time."""
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = 'KIZOMBA'")
        kizomba_id = cur.fetchone()[0]
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO event_genres (event_id, genre_id, origin) VALUES (%s, %s, 'HUMAN')",
            (stored["event_id"], kizomba_id),
        )

    normalization.normalize_candidate(pg, _candidate(unique), genre_hints=["BACHATA"])
    with pg.cursor() as cur:
        cur.execute(
            "SELECT genre_id, origin FROM event_genres WHERE event_id = %s",
            (stored["event_id"],),
        )
        rows = dict(cur.fetchall())
    assert rows.get(kizomba_id) == "HUMAN"


def test_latin_alone_is_never_a_stored_genre_hint(pg, unique):
    """detect_genre_hints() itself already refuses this (engine/tests), but
    this pins the write side too: nothing calls normalize_candidate() with a
    fabricated hint for a post that only says "라틴"."""
    stored = normalization.normalize_candidate(
        pg, _candidate(unique), genre_hints=[],
    )
    with pg.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM event_genres WHERE event_id = %s AND origin = 'AUTO'",
            (stored["event_id"],),
        )
        count = cur.fetchone()[0]
    assert count == 1  # only the primary


def test_normalizing_the_same_candidate_twice_updates_one_row(pg, unique):
    first = normalization.normalize_candidate(pg, _candidate(unique))
    second = normalization.normalize_candidate(pg, _candidate(unique, fee=15000))
    assert first["event_id"] == second["event_id"]
    assert second["fee"] == 15000


def test_a_human_correction_wins_and_is_recorded_as_such(pg, unique):
    """EDIT keeps both readings. The event carries the corrected one and says
    which fields a person changed."""
    stored = normalization.normalize_candidate(
        pg, _candidate(unique),
        review_state={
            "review_state": "EDITED",
            "corrected_json": {"start_time": "20:00", "venue": "라 벤따나"},
        },
    )
    assert stored["start_time"] == time(20, 0)
    assert stored["venue_text"] == "라 벤따나"
    assert set(stored["field_origin"]) == {"start_time", "venue"}
    assert stored["field_origin"]["start_time"] == "HUMAN"


def test_a_rejected_candidate_is_never_listed(pg, unique):
    stored = normalization.normalize_candidate(
        pg, _candidate(unique), review_state={"review_state": "REJECTED"},
    )
    assert stored["listing_state"] == normalization.HIDDEN


def test_approval_does_not_grant_verified(pg, unique):
    """The engine's evidence gate is the only thing that sets VERIFIED."""
    stored = normalization.normalize_candidate(
        pg, _candidate(unique, candidate_status="POSSIBLE"),
        review_state={"review_state": "APPROVED"},
    )
    assert stored["engine_status"] == "POSSIBLE"
    assert stored["review_state"] == "APPROVED"


@pytest.mark.parametrize("action", [review.APPROVE, review.CONFIRM])
def test_review_states_that_keep_an_event_listed(pg, unique, action):
    stored = normalization.normalize_candidate(
        pg, _candidate(unique),
        review_state={"review_state": review.STATE_BY_ACTION[action]},
    )
    assert stored["listing_state"] == normalization.LISTED


def test_an_untraceable_candidate_is_not_live(pg, unique):
    """Provenance defaults to UNKNOWN, and the alpha surface serves LIVE only."""
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    assert stored["provenance"] == normalization.PROVENANCE_UNKNOWN


def test_events_whose_candidate_is_gone_are_pruned(pg, unique):
    """Re-extraction issues new candidate ids rather than updating old ones.

    Without pruning, an engine version bump leaves every post with both its old
    event and its new one -- and the duplicate rules cannot merge them, because
    the whole point of the new extraction is that the values differ.
    """
    stale = normalization.normalize_candidate(pg, _candidate(unique))
    survivor = normalization.normalize_candidate(
        pg, _candidate(unique, candidate_id=int(unique[-6:]) + 1),
    )
    removed = normalization._prune_orphans(pg, {survivor["candidate_id"]})
    assert removed >= 1
    assert normalization.get(pg, stale["event_id"]) is None
    assert normalization.get(pg, survivor["event_id"]) is not None


def test_an_unreadable_engine_store_prunes_nothing(pg, unique):
    """"I cannot see the candidates" must never be acted on as "there are none"."""
    stored = normalization.normalize_candidate(pg, _candidate(unique))
    assert normalization._prune_orphans(pg, None) == 0
    assert normalization._prune_orphans(pg, set()) == 0
    assert normalization.get(pg, stored["event_id"]) is not None


def test_seeing_a_venue_string_again_does_not_inflate_its_count(pg, unique):
    """Normalising the same candidate twice is not the venue turning up twice."""
    venue_text = f"미등록 스튜디오 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = next(v for v in normalization.unresolved_venues(pg)
                 if v["venue_text"] == venue_text)
    assert entry["occurrence_count"] == 1
    assert entry["event_count"] == 1
