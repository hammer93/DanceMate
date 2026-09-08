"""v0.85.9 Event Time Range + Conditional Fee Display.

Grounded in a real production failure: Solo Tango's weekly "화정" Tuesday
milonga (SRC-D-003) read its clean 20:00-23:30 time range correctly every
week (untouched this release - extraction_rules.parse_time_range() already
handled it) while its fee read unknown every week, because "8천원 (10시 이후
5천원)" used a Korean notation and a conditional-discount shape
engine.src.extraction_rules.extract_fee() had no support for at all
(engine/tests/test_extraction_rules.py carries the parser-level fixtures).

This file covers the runtime side: the new column travelling from the
engine's event_candidates through normalize_candidate() into events, and
onto the Timeline/Detail pages - plus the regression surface Section 29-35
of the task requires untouched: source-priority representative selection
and v0.85.8's three-line timeline lock, now carrying a longer conditional
fee string in line 2.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from runtime import duplicates, events_api, public


_NOW = datetime.fromisoformat("2026-09-08T21:00:00+09:00")


def _event(**overrides):
    base = {
        "id": 1, "name": "[화정] 9월 8일 화정 공지 (DJ : 유진)",
        "date": "2026-09-08",
        "start_time": "20:00", "end_time": "23:30", "ends_next_day": False,
        "time_confirmed": True, "event_type_label": "밀롱가",
        "region": "서울", "region_confirmed": True,
        "venue": {"name": "Tango O nada", "status": "RESOLVED",
                  "address": "서울 마포구 동교로 193 지하1층",
                  "map_url": events_api.build_naver_map_search_url(
                      "서울 마포구 동교로 193 지하1층")},
        "fee": 8000, "fee_display_text": "8,000원 (22시 이후 5,000원)",
        "dj": "유진",
        "status": "POSSIBLE", "status_label": "확인 필요", "cancelled": False,
        "source_link": {"url": "https://cafe.daum.net/latindance/73b/68727",
                        "label": "Solo Tango 화요정모 공지"},
        "last_checked": (_NOW - timedelta(hours=1)).isoformat(),
    }
    base.update(overrides)
    return base


# --- Timeline / Detail rendering --------------------------------------------

def test_timeline_shows_the_conditional_fee_text_not_the_bare_amount():
    line2 = public._timeline_line2(_event())
    assert "입장료: 8,000원 (22시 이후 5,000원)" in line2
    assert "미확인" not in line2


def test_timeline_falls_back_to_plain_amount_without_display_text():
    """A single-price event never got a fee_display_text in the first
    place (extract_fee() only sets it for a conditional/multi-option
    reading) - the plain "13,000원" formatting from before this release
    must still be exactly what renders."""
    event = _event(fee=13000, fee_display_text=None)
    line2 = public._timeline_line2(event)
    assert "입장료: 13,000원" in line2


def test_detail_page_fee_row_shows_the_conditional_text():
    line = public._fee_line(_event())
    assert line == "8,000원 (22시 이후 5,000원)"


def test_detail_page_fee_row_falls_back_to_plain_amount():
    line = public._fee_line(_event(fee=13000, fee_display_text=None))
    assert line == "13,000원"


def test_detail_page_fee_row_still_shows_unknown_when_truly_unknown():
    line = public._fee_line(_event(fee=None, fee_display_text=None))
    assert "미확인" in line


def test_events_api_present_exposes_fee_display_text():
    presented = events_api.present({
        "event_id": 1, "event_name": "화정", "event_date": date(2026, 9, 8),
        "start_time": time(20, 0), "end_time": time(23, 30), "end_day_offset": 0,
        "venue_status": "RESOLVED", "venue_name": "Tango O nada",
        "venue_address": "서울 마포구 동교로 193", "venue_id": 187,
        "fee": 8000, "fee_display_text": "8,000원 (22시 이후 5,000원)",
        "dj": "유진", "event_type": "MILONGA", "engine_status": "POSSIBLE",
        "review_state": "PENDING", "listing_state": "LISTED",
    })
    assert presented["fee"] == 8000
    assert presented["fee_display_text"] == "8,000원 (22시 이후 5,000원)"


# --- v0.85.8's three-line lock, now with a longer fee segment --------------
#
# Section 34-35: line 2's priority when space is tight is name > fee >
# address (address ellipsizes first, unchanged from v0.85.8) and the
# conditional fee text must never itself be truncated in a way that loses
# its meaning. The markup already guarantees this structurally: only
# `.tl-2-addr` carries the ellipsis/overflow-hidden treatment (v0.85.8's
# own lock) - the fee segment sits in plain, unwrapped text, so it is
# physically impossible for the same CSS rule that ellipsizes the address
# to also truncate the fee.

def test_conditional_fee_text_is_never_inside_an_ellipsizing_span():
    line2 = public._timeline_line2(_event())
    fee_segment = line2.split("입장료:")[1].split("<span")[0]
    assert "text-overflow" not in fee_segment
    assert "tl-2-addr" not in fee_segment


def test_address_still_ellipsizes_first_when_fee_text_is_long():
    line2 = public._timeline_line2(_event())
    assert 'class="tl-2-addr"' in line2
    # The full conditional fee text is present and unbroken - Section 35
    # forbids losing its meaning to a mid-string cut.
    assert "8,000원 (22시 이후 5,000원)" in line2


def test_line2_ordering_is_name_dj_fee_address():
    line2 = public._timeline_line2(_event())
    fee_index = line2.index("입장료")
    addr_index = line2.index("동교로")
    dj_index = line2.index("유진")
    assert dj_index < fee_index < addr_index


# --- source priority regression (Section 29-32) -----------------------------
#
# source_priority.py and duplicates._canonical_of() are unchanged this
# release. These pin that a PRIMARY organiser's own post (now carrying a
# real fee_display_text where it used to carry an unpriced/None fee) still
# outranks a DIRECTORY aggregator's folded copy of the same event, exactly
# as it did before this release touched anything fee-related.

def test_primary_stays_representative_over_miltang_directory():
    primary = {
        "event_id": 221245, "event_date": date(2026, 9, 8), "start_time": time(20, 0),
        "end_time": time(23, 30), "venue_id": 187, "venue_status": "RESOLVED",
        "fee": 8000, "fee_display_text": "8,000원 (22시 이후 5,000원)",
        "engine_status": "POSSIBLE", "review_state": "PENDING",
        "source_role": "ORGANIZER",
    }
    miltang = dict(primary, event_id=88436, source_role="AGGREGATOR",
                   fee=None, fee_display_text=None)
    canonical, duplicate = duplicates._canonical_of(primary, miltang)
    assert canonical["event_id"] == 221245
    assert duplicate["event_id"] == 88436


def test_primary_stays_representative_over_tangonow_directory():
    primary = {
        "event_id": 221245, "event_date": date(2026, 9, 8), "start_time": time(20, 0),
        "end_time": time(23, 30), "venue_id": 187, "venue_status": "RESOLVED",
        "fee": 8000, "fee_display_text": "8,000원 (22시 이후 5,000원)",
        "engine_status": "POSSIBLE", "review_state": "PENDING",
        "source_role": "ORGANIZER",
    }
    tangonow = dict(primary, event_id=99001, source_role="DIRECTORY",
                    fee=None, fee_display_text=None)
    canonical, duplicate = duplicates._canonical_of(primary, tangonow)
    assert canonical["event_id"] == 221245
    assert duplicate["event_id"] == 99001


def test_promotion_board_beats_miltang_and_tangonow():
    board = {
        "event_id": 1, "event_date": date(2026, 9, 8), "start_time": time(20, 0),
        "end_time": time(23, 30), "venue_id": 187, "venue_status": "RESOLVED",
        "fee": 8000, "fee_display_text": "8,000원 (22시 이후 5,000원)",
        "engine_status": "POSSIBLE", "review_state": "PENDING",
        "source_role": "PROMOTION_BOARD",
    }
    for other_role in ("AGGREGATOR", "DIRECTORY"):
        other = dict(board, event_id=2, source_role=other_role)
        canonical, duplicate = duplicates._canonical_of(board, other)
        assert canonical["event_id"] == 1
        assert duplicate["event_id"] == 2


def test_priority_does_not_silently_override_a_conflicting_field():
    """Section 32: representative-source selection and conflict semantics
    are separate concerns. _canonical_of() picks *one row* to display; it
    does not fabricate, merge or overwrite a field on the loser to match
    the winner. The DIRECTORY row's own (different) fee stays exactly what
    it was in its own dict - nothing here mutates it."""
    primary = {
        "event_id": 1, "event_date": date(2026, 9, 8), "start_time": time(20, 0),
        "end_time": time(23, 30), "venue_id": 187, "venue_status": "RESOLVED",
        "fee": 8000, "fee_display_text": "8,000원 (22시 이후 5,000원)",
        "engine_status": "POSSIBLE", "review_state": "PENDING",
        "source_role": "ORGANIZER",
    }
    conflicting = dict(primary, event_id=2, source_role="DIRECTORY",
                       fee=99999, fee_display_text=None)
    canonical, duplicate = duplicates._canonical_of(primary, conflicting)
    assert canonical["event_id"] == 1
    assert duplicate["fee"] == 99999
