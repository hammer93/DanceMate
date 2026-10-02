"""v0.96.29: carry the place a post states in its own field.

danceinfo.net hydrates its lesson pages from a structured payload, and
``acquisition.danceinfo_payload_body()`` writes those fields out as the page
lays them out::

    <date> 전체일정 … 일정정보 … 장소 … DJ … 강의 소개 …

with no colon after any label, because none of them is a colon in the payload.
``extraction_rules._VENUE_LABEL_RE`` requires one, and v0.96.2 gave it that rule
for a good reason - "위치와 카프레제 파스타" and "위치 🕗 시간: PM 8시" were
becoming venues. So the site states a clean ``placeName`` and we drop it: over
the visible upcoming list that was 44 Events with no place at all and 13
carrying something worse than the post's own field - OCR fragments, a city where
the post names the room, "Hotel" where the post names 천안 턴(TURN).

Making the renderer write "장소:" instead was measured and rejected in v0.96.26
(213 of 237 item venues moved and 8 dates with them). What is read here is the
*field*, bounded on both sides by the payload's own closed label set, which is
why these tests hold the engine's restated labels equal to the ones acquisition
actually renders.

Measured over all 1,640 stored bodies before this release: 287 carry the field,
97 distinct names, every value 20 characters or shorter, 282 a clean venue name,
3 a bare city, 2 a landmark-style address, 0 advertising, 0 prose leak; 장소
never twice in one structured region; and **none of the 1,803 stored OCR texts**
matches the shape, which is what keeps v0.96.24's contract intact without a
second gate.
"""

from __future__ import annotations

import sys

import pytest

from runtime import acquisition
from runtime.config import REPO_ROOT

# The engine package is reached the way `runtime.engine_ingest._engine()`
# reaches it - by path insertion, because the two suites are separate packages.
if str(REPO_ROOT / "engine") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "engine"))


def _rules():
    from src import extraction_rules

    return extraction_rules


def _venue(text: str):
    reading = _rules().extract_venue(text)
    return None if reading is None else reading.name


def _label(text: str):
    reading = _rules().extract_venue(text)
    return None if reading is None else reading.label


def _payload(place: str | None = "라소클", *, schedule="9시부터", dj=None,
             description=None, dates="2026-10-03") -> str:
    """A body shaped exactly as `danceinfo_payload_body()` renders one."""
    parts = ["2026-10-03"]
    for label, value in (("전체일정", dates), ("일정정보", schedule),
                         ("장소", place), ("DJ", dj), ("강의 소개", description)):
        if value in (None, "", [], {}):
            continue
        parts.append(f"{label} {value}")
    return " ".join(parts)


# --- the two sides of the contract agree ------------------------------------

def test_the_engine_restates_the_labels_acquisition_actually_renders():
    """`src` and `runtime` never import each other, the same way
    `classifier.MIN_TEXT_FOR_IMAGE_TRUST` restates acquisition's own minimum.
    This is what holds the restatement honest."""
    rendered = tuple(label for label, _key in acquisition._DANCEINFO_FIELDS)
    assert _rules().PAYLOAD_FIELD_LABELS == rendered
    assert _rules().PAYLOAD_PLACE_LABEL in rendered
    assert _rules().PAYLOAD_PROSE_LABEL == rendered[-1], \
        "the description must stay last; the structured region ends where it begins"


def test_the_place_label_maps_to_the_payloads_own_key():
    fields = dict(acquisition._DANCEINFO_FIELDS)
    assert fields[_rules().PAYLOAD_PLACE_LABEL] == "placeName"


# --- the field boundary -----------------------------------------------------

@pytest.mark.parametrize("body, expected", [
    (_payload("라소클", description="..."), "라소클"),                       # next = 강의 소개
    (_payload("EDM 댄스스튜디오", dates="2026-10-02"), "EDM 댄스스튜디오"),
    (_payload("분당 실루엣", description="단계별로 배우고"), "분당 실루엣"),
    (_payload("천안 턴(TURN)", dj="MAX", description="x"), "천안 턴(TURN)"),  # next = DJ
    (_payload("오아시스"), "오아시스"),                                        # last field
    (_payload("강턴", dj="GGONS, HIRO", description="강턴에서 만나요!"), "강턴"),
])
def test_the_field_value_ends_at_the_next_field(body, expected):
    assert _venue(body) == expected
    assert _label(body) == _rules().VENUE_LABEL_PAYLOAD_FIELD


def test_a_value_the_corpus_writes_with_its_own_address_is_kept():
    """Two of the 287 are landmark-shaped. The field is what the site states,
    and nothing here trims by length - see the module docstring."""
    assert _venue(_payload("테헤란로 14길 25", description="x")) == "테헤란로 14길 25"
    assert _venue(_payload("수유역 6번출구 근처", description="x")) == "수유역 6번출구 근처"


def test_a_bracketed_part_is_offered_to_the_venue_master_as_well():
    reading = _rules().extract_venue(_payload("천안 턴(TURN)", description="x"))
    assert reading.alias_candidates[0] == "천안 턴(TURN)"
    assert "천안 턴" in reading.alias_candidates
    assert "TURN" in reading.alias_candidates


# --- what the field must not do ---------------------------------------------

def test_an_absent_place_reads_as_no_venue():
    """Acquisition omits a field the payload does not carry, rather than
    writing an empty label - its own comment says why. Measured: 0 payload
    bodies carry a bare 장소 label."""
    assert _venue(_payload(None, dj="MAX", description="x")) is None
    assert _rules().payload_place_field(_payload(None, description="x")) is None


def test_the_label_of_the_next_field_is_never_the_value():
    """A hole the corpus does not currently contain, closed anyway: the next
    label may sit at the very start of the value with no space in front."""
    assert _rules().payload_place_field(
        "2026-10-03 전체일정 2026-10-03 일정정보 9시 장소 DJ MAX 강의 소개 x") is None


def test_a_place_written_inside_the_description_is_not_the_field():
    """The description is free prose and three stored bodies write a
    "장소 : …" of their own inside it. The structured region ends before it."""
    body = _payload(None, description="수업 안내 장소 : 정일빌딩4F 에버라틴 연습실")
    assert _rules().payload_place_field(body) is None


def test_prose_that_merely_says_장소_is_not_a_payload_field():
    for text in ("오늘 장소 라소클 에서 만나요",
                 "모임 장소 추후 공지",
                 "장소 미정입니다"):
        assert _rules().payload_place_field(text) is None, text


def test_a_body_that_says_일정정보_far_down_is_not_a_payload_rendering():
    """The opening field has to be at the head, which is what stops an ordinary
    post that happens to use the word from being read as a field list."""
    text = "x" * 200 + " 일정정보 9시 장소 라소클 강의 소개 y"
    assert _rules().payload_place_field(text) is None


def test_a_word_merely_ending_in_장소_is_not_the_label():
    assert _rules().payload_place_field(
        "2026-10-03 전체일정 2026-10-03 일정정보 9시 행사장소 라소클 강의 소개 x") is None


# --- the generic venue parser is untouched ----------------------------------

def test_a_colon_label_still_works_and_still_needs_its_colon():
    assert _venue("장소: 아미고스튜디오 DJ : 로띠") == "아미고스튜디오"
    assert _venue("위치와 카프레제 파스타") is None
    assert _venue("위치 🕗 시간: PM 8시") is None


def test_the_v0962_at_and_suffix_readings_are_unchanged():
    assert _venue("9월 24일 저녁 8시 @오초") == "오초"
    assert _venue("@allaboutswing 팔로우 부탁드립니다") is None
    assert _venue("아미고 스튜디오 9:15pm") == "아미고 스튜디오"
    assert _venue("인스타그램 DM: @intothelatinittl") is None


def test_the_v09626_boundaries_are_unchanged():
    assert _venue("장소: 일영 마당뜰 펜션 협찬 품목: 주류") == "일영 마당뜰 펜션"
    assert _venue("장소: 홍턴 지하 2층 💰 수강료 및 할인 혜택") == "홍턴 지하 2층"
    assert _venue("00:00 장소 카디즈 스튜디오") == "카디즈 스튜디오"


def test_an_unlabelled_ocr_reading_is_still_refused_v09624():
    """None of the 1,803 stored OCR texts matches the payload shape, so the
    field branch cannot reach one - and the image path's own gate stands."""
    from src.extractor import extract_with_image_fallback

    ev = extract_with_image_fallback(
        "무차살사소셜", "9/20(토) 21:00~01:00", event_type="SOCIAL",
        published="2026-09-01",
        image_texts=[("img1", "무차살사소셜 @ 스스 me1 입장료 10,000원")])
    assert ev.venue is None


def test_an_ocr_text_shaped_like_a_poster_is_not_a_payload_field():
    assert _rules().payload_place_field("PM 8:00\n장소 라소클\nDJ MAX") is None


# --- the Production cases this release exists for ---------------------------

@pytest.mark.parametrize("body, expected", [
    # item 4496: the Event carried the address, the field names the club.
    (_payload("라소클", schedule="9시부터",
              description="-CRAZY MAX: ALL NIGHT 🚨20시~06시까지"), "라소클"),
    # item 4414: the Event carried "Hotel" from a poster.
    (_payload("천안 턴(TURN)", schedule="PM 9:00", description="춤추는 J 토끼파티"),
     "천안 턴(TURN)"),
    # item 3602: the Event carried "실루엣/정자역4.5출구".
    (_payload("분당 실루엣", schedule="6시", description="둘쎄 밀롱가"), "분당 실루엣"),
    # item 5510: the Event carried OCR noise from a poster.
    (_payload("강턴", schedule="PM 8:00", dj="GGONS, HIRO",
              description="SEOUL SALSA WEEK가 4일간 진행됩니다"), "강턴"),
    # item 5526: the Event carried "소셜타임 장소 EDM 댄스스튜디오" via the
    # suffix shortcut, which swallowed the words in front of the name.
    (_payload("EDM 댄스스튜디오", schedule="8시", description="아임살사 생일자 축하 정모"),
     "EDM 댄스스튜디오"),
])
def test_the_measured_production_cases(body, expected):
    assert _venue(body) == expected


def test_the_field_outranks_a_poster_reading_on_the_same_post():
    """A place the site put in its own field is stronger evidence than a
    reading guessed out of an image of that post."""
    from src.extractor import extract_with_image_fallback

    ev = extract_with_image_fallback(
        "SEOUL SALSA WEEK",
        _payload("강턴", schedule="PM 8:00", description="강턴에서 만나요"),
        event_type="SOCIAL", published="2026-10-01",
        image_texts=[("img1", "장소: BEL | BRA ZUR 역심로3길17-5심영빌지 1층")])
    assert ev.venue == "강턴"


# --- the fold a resolved venue would otherwise have created ------------------
#
# `duplicates._clock()` reported a missing start time as the string "None",
# which is truthy and equal to itself, so two events with no hour at all read as
# agreeing on one and `classify()` auto-merged them on date and venue alone -
# while naming `start_time` among the things that matched. It had never fired: a
# fold needs both places *resolved*, and Production held 0 pairs of time-less
# events at one resolved venue on one date. Reading a post's own `placeName`
# resolves the venue on 53 events that had none, and the 보니따 추석 pair
# (events 1600306 and 1612030, both 2026-09-26, both no hour) is the one it
# would have created.

from datetime import time as _time

from runtime import duplicates


def _ev(**kw):
    base = {"event_date": "2026-09-26", "start_time": None,
            "venue_id": 4248, "venue_text": "보니따"}
    base.update(kw)
    return base


def test_a_missing_start_time_is_reported_as_missing():
    assert duplicates._clock(_ev()) is None
    assert duplicates._clock(_ev(start_time=_time(21, 0))) == "21:00"
    assert duplicates._clock(_ev(start_time="21:00:00")) == "21:00"


def test_two_events_with_no_hour_are_a_question_not_a_merge():
    verdict = duplicates.classify(_ev(), _ev())
    assert verdict["auto"] is False
    assert verdict["rule"] == duplicates.RULE_VENUE_TIME_DIFFERS
    assert "start_time" in verdict["differs"]
    assert "start_time" not in verdict["matched"]


def test_an_hour_on_one_side_only_is_still_a_question():
    verdict = duplicates.classify(_ev(start_time=_time(21, 0)), _ev())
    assert verdict["auto"] is False
    assert "start_time" in verdict["differs"]


def test_two_events_that_do_agree_on_the_hour_still_fold():
    verdict = duplicates.classify(_ev(start_time=_time(21, 0)),
                                  _ev(start_time=_time(21, 0)))
    assert verdict["auto"] is True
    assert verdict["rule"] == duplicates.RULE_SAME_DATE_VENUE_TIME
    assert "start_time" in verdict["matched"]


def test_the_v09623_unresolved_pair_rule_is_unchanged():
    """Same hour, same venue *words*, neither resolved: still a question."""
    left = _ev(start_time=_time(21, 0), venue_id=None, venue_text="스스 me1")
    verdict = duplicates.classify(left, dict(left))
    assert verdict["auto"] is False
    assert verdict["rule"] == duplicates.RULE_UNRESOLVED_VENUE_TIME
