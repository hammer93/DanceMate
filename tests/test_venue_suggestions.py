"""Venue Resolution Operations (v0.83.0): ranked suggestions, grouping, and
Group Apply on top of the existing Unresolved Venues queue.

similar_venues() stayed exact-match on purpose ("a warning an operator cannot
check is a warning they learn to click past" - venue_resolution.py's own
docstring). These tests exist to hold that constraint even as fuzzy scoring
is added underneath it: HIGH stays reserved for an exact match, a fuzzy
match never reaches it no matter how close the score, and an address or
region conflict caps a fuzzy match at LOW regardless of name similarity.
Nothing here ever links or creates anything on its own - every suggestion is
read-only until an operator calls the existing link_existing()/
create_and_link() themselves.
"""

from __future__ import annotations

from runtime import master_data, normalization, venue_resolution


def _candidate(unique: str, suffix: str = "1", **overrides):
    base = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/venue/{unique}-{suffix}",
        "event_name": f"장소 제안 테스트 {unique}",
        "event_type": "MILONGA",
        "event_date": "2026-09-05",
        "start_time": "19:30",
        "end_time": "23:30",
        "end_day_offset": 0,
        "venue": f"테스트홀 {unique}",
        "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    base.update(overrides)
    return base


def _queued(con, venue_text: str) -> dict:
    return next(v for v in normalization.unresolved_venues(con)
                if v["venue_text"] == venue_text)


# --- confidence tiers: pure functions, no DB ---------------------------------

def test_identical_names_score_a_perfect_similarity():
    assert venue_resolution._name_similarity("OCHO", "OCHO") == 1.0


def test_unrelated_names_score_low():
    assert venue_resolution._name_similarity("OCHO", "PISTA") < venue_resolution._NAME_LOW_THRESHOLD


def test_no_address_on_either_side_is_not_a_conflict():
    assert venue_resolution._address_conflict(None, None) is False
    assert venue_resolution._address_conflict("서울 마포구 잔다리로 48", None) is False


def test_two_different_real_addresses_conflict():
    assert venue_resolution._address_conflict(
        "서울 마포구 잔다리로 48", "부산 부산진구 서면로68번길 38",
    ) is True


def test_the_same_address_written_differently_does_not_conflict():
    assert venue_resolution._address_conflict(
        "서울 마포구 잔다리로 48, 2층", "서울 마포구 잔다리로 48 2층",
    ) is False


# --- exact alias suggestion (HIGH) -------------------------------------------

def test_an_exact_alias_is_suggested_at_high_confidence(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"오초 {unique}", region_id=seoul_id)
    master_data.add_venue_alias(pg, venue["venue_id"], f"탱고 클럽 오초 {unique}")

    ranked = venue_resolution.suggest_venue_links(
        pg, name=f"탱고 클럽 오초 {unique}", raw_venue=f"탱고 클럽 오초 {unique}",
    )
    assert ranked[0]["venue_id"] == venue["venue_id"]
    assert ranked[0]["confidence"] == venue_resolution.CONFIDENCE_HIGH


# --- bilingual / fuzzy name suggestion (MEDIUM, never HIGH) ------------------

def test_a_bilingual_variant_is_suggested_at_medium_not_high(pg, unique, seoul_id):
    """"스튜디오 오초" against a venue already aliased "오초" - close enough to
    flag, not close enough (and not exact) to treat as settled."""
    venue = master_data.create_venue(pg, name=f"OCHO {unique}", region_id=seoul_id)
    master_data.add_venue_alias(pg, venue["venue_id"], f"오초 {unique}")

    ranked = venue_resolution.suggest_venue_links(pg, name=f"스튜디오 오초 {unique}")
    assert ranked, "expected at least one fuzzy suggestion"
    top = ranked[0]
    assert top["venue_id"] == venue["venue_id"]
    assert top["confidence"] == venue_resolution.CONFIDENCE_MEDIUM


def test_a_near_perfect_fuzzy_score_still_never_reaches_high(pg, unique, seoul_id):
    venue = master_data.create_venue(pg, name=f"라벤따나스튜디오 {unique}", region_id=seoul_id)
    ranked = venue_resolution.suggest_venue_links(pg, name=f"라벤따나스튜디오{unique}살짝다름")
    assert ranked
    assert ranked[0]["confidence"] != venue_resolution.CONFIDENCE_HIGH


# --- same name, different region: separated, not conflated -------------------

def test_the_same_name_in_a_different_region_is_capped_at_low(pg, unique, seoul_id):
    # A second region created here rather than assuming e.g. KR-BUSAN is
    # pre-seeded: on a bare migrated database only KR-SEOUL is (the same
    # reason this project's own fixtures special-case seoul_id) - any other
    # region visible in real production got there via a later admin action,
    # not a migration.
    other_region = master_data.create_region(
        pg, code=f"KR-TEST{unique}", country="KR", name=f"테스트지역 {unique}",
    )
    venue = master_data.create_venue(
        pg, name=f"공용스튜디오 {unique}", region_id=other_region["region_id"],
    )
    ranked = venue_resolution.suggest_venue_links(
        pg, name=f"공용스튜디오 {unique}", region_id=seoul_id,
    )
    assert ranked
    match = next(r for r in ranked if r["venue_id"] == venue["venue_id"])
    assert match["confidence"] == venue_resolution.CONFIDENCE_LOW
    assert "different region" in match["match_reasons"]


# --- address conflict lowers confidence --------------------------------------

def test_an_address_conflict_caps_a_fuzzy_match_at_low(pg, unique, seoul_id):
    venue = master_data.create_venue(
        pg, name=f"땅고랩 {unique}", region_id=seoul_id,
        address="서울 마포구 잔다리로 48",
    )
    ranked = venue_resolution.suggest_venue_links(
        pg, name=f"땅고랩스튜디오{unique}", address="부산 부산진구 서면로68번길 38",
    )
    assert ranked
    match = next(r for r in ranked if r["venue_id"] == venue["venue_id"])
    assert match["confidence"] == venue_resolution.CONFIDENCE_LOW
    assert "address conflict" in match["match_reasons"]


# --- no false auto-link / read-only ------------------------------------------

def test_suggesting_never_writes_anything(pg, unique, seoul_id):
    venue_text = f"테스트홀 {unique}"
    event = normalization.normalize_candidate(pg, _candidate(unique))
    entry = _queued(pg, venue_text)
    master_data.create_venue(pg, name=f"비슷한이름 {unique}", region_id=seoul_id)

    venue_resolution.suggest_venue_links(pg, name=venue_text, raw_venue=venue_text)

    after = normalization.unresolved_venue(pg, entry["unresolved_venue_id"])
    assert after["state"] == "OPEN"
    assert after["resolved_venue_id"] is None
    unchanged = normalization.get(pg, event["event_id"])
    assert unchanged["venue_status"] == normalization.VENUE_UNRESOLVED
    assert unchanged["venue_id"] is None


def test_human_review_state_is_untouched_by_suggesting_or_grouping(pg, unique, seoul_id):
    venue_text_a = f"클러스터장소 {unique}"
    venue_text_b = f"클러스터장소별칭 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1", venue=venue_text_a))
    normalization.normalize_candidate(pg, _candidate(unique, "2", venue=venue_text_b))
    pending = normalization.unresolved_venues(pg)
    relevant = [e for e in pending if unique in e["venue_text"]]
    suggestions = {
        e["unresolved_venue_id"]: venue_resolution.suggest_venue_links(
            pg, name=e["venue_text"], raw_venue=e["venue_text"],
        )
        for e in relevant
    }

    venue_resolution.group_unresolved(relevant, suggestions)

    for entry in relevant:
        row = normalization.unresolved_venue(pg, entry["unresolved_venue_id"])
        assert row["state"] == "OPEN"


# --- grouping ------------------------------------------------------------

def test_two_unmatched_strings_close_to_each_other_are_grouped():
    pending = [
        {"unresolved_venue_id": 1, "venue_text": "이데알 탱고 까페"},
        {"unresolved_venue_id": 2, "venue_text": "이데알 탱고 까페 (부산 부산진구 신천대로 62번길 62)"},
        {"unresolved_venue_id": 3, "venue_text": "전혀 다른 이름의 장소"},
    ]
    suggestions = {1: [], 2: [], 3: []}
    groups = venue_resolution.group_unresolved(pending, suggestions)
    ids_by_group = [sorted(g) for g in groups]
    assert [1, 2] in ids_by_group
    assert [3] in ids_by_group


def test_entries_sharing_a_confident_suggestion_are_grouped():
    pending = [
        {"unresolved_venue_id": 10, "venue_text": "A"},
        {"unresolved_venue_id": 11, "venue_text": "B"},
    ]
    suggestions = {
        10: [{"venue_id": 99, "confidence": venue_resolution.CONFIDENCE_HIGH}],
        11: [{"venue_id": 99, "confidence": venue_resolution.CONFIDENCE_MEDIUM}],
    }
    groups = venue_resolution.group_unresolved(pending, suggestions)
    assert sorted(groups[0]) == [10, 11]


def test_the_same_raw_text_groups_even_when_only_one_side_has_a_confident_suggestion():
    """Found live (v0.83.1): "El Tango (엘땅고)" and "EL TANGO" are the same
    text after case-folding, but one queue row had enough context to reach a
    MEDIUM suggestion against 데땅고 and the other did not - own_match must
    not require both sides to be equally unmatched."""
    pending = [
        {"unresolved_venue_id": 30, "venue_text": "El Tango (엘땅고)"},
        {"unresolved_venue_id": 31, "venue_text": "EL TANGO"},
    ]
    suggestions = {
        30: [{"venue_id": 185, "confidence": venue_resolution.CONFIDENCE_LOW}],
        31: [{"venue_id": 185, "confidence": venue_resolution.CONFIDENCE_MEDIUM}],
    }
    groups = venue_resolution.group_unresolved(pending, suggestions)
    assert sorted(groups[0]) == [30, 31]


def test_a_low_confidence_suggestion_does_not_group_entries_together():
    pending = [
        {"unresolved_venue_id": 20, "venue_text": "OCHO"},
        {"unresolved_venue_id": 21, "venue_text": "라벤따나"},
    ]
    suggestions = {
        20: [{"venue_id": 5, "confidence": venue_resolution.CONFIDENCE_LOW}],
        21: [{"venue_id": 5, "confidence": venue_resolution.CONFIDENCE_LOW}],
    }
    groups = venue_resolution.group_unresolved(pending, suggestions)
    assert sorted(sorted(g) for g in groups) == [[20], [21]]


# --- Group Apply --------------------------------------------------------------

def test_group_apply_links_every_row_in_the_group_to_one_venue(pg, unique, seoul_id):
    venue_text_a = f"그룹적용A {unique}"
    venue_text_b = f"그룹적용B {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1", venue=venue_text_a))
    normalization.normalize_candidate(pg, _candidate(unique, "2", venue=venue_text_b))
    entry_a = _queued(pg, venue_text_a)
    entry_b = _queued(pg, venue_text_b)
    venue = master_data.create_venue(pg, name=f"그룹적용 장소 {unique}", region_id=seoul_id)

    result = venue_resolution.group_link_existing(
        pg, unresolved_venue_ids=[entry_a["unresolved_venue_id"], entry_b["unresolved_venue_id"]],
        venue_id=venue["venue_id"], reviewer="tester",
    )
    assert result["linked_count"] == 2
    assert result["events_updated"] == 2
    assert not result["errors"]

    # _queued() reads normalization.unresolved_venues()'s default OPEN-only
    # listing, which now correctly excludes these - fetch by id instead.
    for uid in (entry_a["unresolved_venue_id"], entry_b["unresolved_venue_id"]):
        row = normalization.unresolved_venue(pg, uid)
        assert row["state"] == "LINKED"
        assert row["resolved_venue_id"] == venue["venue_id"]


def test_group_apply_records_one_audit_row_per_string(pg, unique, seoul_id):
    venue_text_a = f"그룹감사A {unique}"
    venue_text_b = f"그룹감사B {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, "1", venue=venue_text_a))
    normalization.normalize_candidate(pg, _candidate(unique, "2", venue=venue_text_b))
    entry_a = _queued(pg, venue_text_a)
    entry_b = _queued(pg, venue_text_b)
    venue = master_data.create_venue(pg, name=f"그룹감사 장소 {unique}", region_id=seoul_id)

    venue_resolution.group_link_existing(
        pg, unresolved_venue_ids=[entry_a["unresolved_venue_id"], entry_b["unresolved_venue_id"]],
        venue_id=venue["venue_id"], reviewer="tester",
    )
    history = venue_resolution.history(pg)
    recorded = [a for a in history if a["raw_venue"] in (venue_text_a, venue_text_b)]
    assert len(recorded) == 2
    assert all(a["action"] == venue_resolution.LINK_EXISTING for a in recorded)


# --- alias dedup / opt-out ----------------------------------------------------

def test_link_existing_can_skip_registering_the_alias(pg, unique, seoul_id):
    venue_text = f"별칭생략 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    venue = master_data.create_venue(pg, name=f"별칭생략 장소 {unique}", region_id=seoul_id)

    venue_resolution.link_existing(
        pg, unresolved_venue_id=entry["unresolved_venue_id"], venue_id=venue["venue_id"],
        reviewer="tester", add_alias=False,
    )
    aliases = [a["alias"] for a in master_data.venue_aliases(pg, venue["venue_id"])]
    assert venue_text not in aliases


def test_link_existing_still_adds_the_alias_by_default(pg, unique, seoul_id):
    venue_text = f"별칭기본 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    entry = _queued(pg, venue_text)
    venue = master_data.create_venue(pg, name=f"별칭기본 장소 {unique}", region_id=seoul_id)

    venue_resolution.link_existing(
        pg, unresolved_venue_id=entry["unresolved_venue_id"], venue_id=venue["venue_id"],
        reviewer="tester",
    )
    aliases = [a["alias"] for a in master_data.venue_aliases(pg, venue["venue_id"])]
    assert venue_text in aliases


# --- region propagation --------------------------------------------------------

def test_group_apply_propagates_the_venues_region_to_every_linked_event(pg, unique, seoul_id):
    venue_text_a = f"지역전파A {unique}"
    venue_text_b = f"지역전파B {unique}"
    first = normalization.normalize_candidate(pg, _candidate(unique, "1", venue=venue_text_a))
    second = normalization.normalize_candidate(pg, _candidate(unique, "2", venue=venue_text_b))
    entry_a = _queued(pg, venue_text_a)
    entry_b = _queued(pg, venue_text_b)
    venue = master_data.create_venue(pg, name=f"지역전파 장소 {unique}", region_id=seoul_id)

    venue_resolution.group_link_existing(
        pg, unresolved_venue_ids=[entry_a["unresolved_venue_id"], entry_b["unresolved_venue_id"]],
        venue_id=venue["venue_id"], reviewer="tester",
    )
    for event in (first, second):
        updated = normalization.get(pg, event["event_id"])
        assert updated["region_id"] == seoul_id
        assert updated["venue_status"] == normalization.VENUE_RESOLVED


# --- admin rendering: no auto-select, badges show, group UI conditional -----

def test_suggestion_block_never_preselects_a_venue():
    from runtime import events_admin

    ranked = [
        {"venue_id": 1, "name": "OCHO", "confidence": venue_resolution.CONFIDENCE_HIGH,
         "match_reasons": ["same name"]},
    ]
    html = events_admin._link_suggestions_block(42, ranked)
    assert "selected" not in html
    assert 'value="1"' in html  # the venue id, in a hidden field the operator still has to submit
    assert "<button" in html


def test_suggestion_block_is_empty_when_there_are_no_candidates():
    from runtime import events_admin

    assert events_admin._link_suggestions_block(42, []) == ""


def test_group_apply_block_only_appears_when_not_alone():
    from runtime import events_admin

    assert events_admin._group_apply_block(1, [1], []) == ""
    rendered = events_admin._group_apply_block(1, [1, 2], [])
    assert "Group Apply" not in rendered or "group-link" in rendered
    assert "/admin/venues/unresolved/group-link/preview" in rendered


# --- v0.83.2: "스튜디오 오초" vs "OCHO" calibration fixture ------------------
#
# Found live (v0.83.0/v0.83.1): a real Unresolved Venues row, "스튜디오 오초",
# scores LOW against the real Master venue "OCHO" (whose own aliases already
# include the bare "오초") purely because SequenceMatcher penalises the
# length mismatch between "스튜디오오초" and "오초" more than it credits the
# fully-contained short token. This is recorded as calibration data, not
# fixed - v0.83.2 Section 8/9 forbid changing the threshold on this single
# case. A future release may consider a "core token fully contained in the
# candidate name" bonus once several more true/false-positive cases like
# this one exist; until then this test exists to notice, loudly, if the
# score for this exact pair ever drifts for an unrelated reason.

def test_studio_ocho_short_token_calibration_fixture():
    score = venue_resolution._name_similarity("스튜디오오초", "오초")
    assert score < venue_resolution._NAME_MEDIUM_THRESHOLD, (
        "스튜디오 오초 vs OCHO's own '오초' alias no longer scores below MEDIUM - "
        "the known short-token-containment gap this fixture tracks may have "
        "closed (or moved) by accident. If the scorer genuinely changed on "
        "purpose, this fixture should be updated as part of that change, not "
        "silently broken by it."
    )


def test_v0832_did_not_move_the_fuzzy_thresholds():
    """Sections 1/8/9: no threshold change this release, from either OCHO
    calibration data or anything else. Pinning the actual constants, not
    just behaviour, so any accidental edit fails loudly here first."""
    assert venue_resolution._NAME_MEDIUM_THRESHOLD == 0.72
    assert venue_resolution._NAME_LOW_THRESHOLD == 0.45


# --- v0.83.2: relinking an already-resolved raw string is a safe no-op ------

def test_relinking_the_same_raw_text_twice_does_not_duplicate_the_alias(pg, unique, seoul_id):
    """Whatever a human decides for "스튜디오 오초" (or any future case), the
    same raw text reappearing - a duplicate post, a retried admin click, a
    fresh collection cycle before the alias is visible - must resolve to the
    same venue without erroring or registering a second alias row. Generic
    coverage, independent of which venue OCHO's review actually lands on."""
    from runtime import master_data

    venue_text = f"스튜디오 오초 {unique}"
    normalization.normalize_candidate(pg, _candidate(unique, venue=venue_text))
    venue = master_data.create_venue(pg, name=f"OCHO {unique}", region_id=seoul_id)
    entry = _queued(pg, venue_text)

    first = normalization.link_unresolved_venue(pg, entry["unresolved_venue_id"], venue["venue_id"])
    assert first["events_updated"] == 1

    # Re-running the exact same link (idempotent retry) must not raise and
    # must not register a second alias for the same normalised text.
    second = normalization.link_unresolved_venue(pg, entry["unresolved_venue_id"], venue["venue_id"])
    assert second["events_updated"] == 0  # nothing left UNRESOLVED to re-link

    aliases = [a["alias"] for a in master_data.venue_aliases(pg, venue["venue_id"])]
    assert aliases.count(venue_text) == 1
