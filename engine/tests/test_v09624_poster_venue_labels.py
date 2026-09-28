"""v0.96.24: a poster may name this event's venue, but only if it labels it.

v0.84.3 gave an image the right to fill a missing venue and narrowed that right
to "the poster labelled it" - never a name the shape of the text was taken for a
label. The narrowing was written as ``inference.startswith("LABEL:")``, and two
readings that are not labels at all answer to that prefix too:
``extract_venue()`` reports the "@ name" shortcut as ``LABEL:@`` and the
"<name>스튜디오 20:00" shortcut as ``LABEL:SUFFIX``.

What that let through, measured over every venue reading the running engine had
taken off a Production poster (65 readings): **50 came from the "@" shortcut,
and 49 of those were not places.** They were fees ("@ 정모비 1만원"), clocks
("@ x 수요일 9Al ~ 1041"), session counts ("@ 월요일 | 8회 12/21"), contact
lines ("@® 카카오 ziazia | 문4"), genre words ("@ 바차타"), taglines
("@ + we. SALSA ㆍ BACHATA «+ LATIN SOCIAL"), team names ("@&메릴린 부캠팀")
and plain OCR noise ("@ we BS", "@® cruiser A zh", "at = see 출 o").

None of them is a social handle. That matters, because it names the real
mechanism: OCR turns a poster's decoration into "@". A bullet, a ®, a ©, a
stray + all come back as that character, and ``_AT_VENUE_RE`` then reads the
words after it as a place name. A human-written body carries no such
decoration, which is why v0.96.2's own "@" venues ("@ 오초", "@Studio Ocho")
stay exactly as they were - this narrows only what an *image* is trusted for.

The one reading in fifty that was a real place came off a weekly-schedule
poster (가또땅고, `cafe.daum.net/GatotangO/Qbxu/966`) whose own body lists three
venues running at the same hour that night - 미오, 아미고 큰홀, 아미고 작은홀.
"@ 아미고 스튜디오" was right about one of three, which is not the same as
being right, and is the multi-venue listing case v0.84.3 exists for.
"""

from __future__ import annotations

import pytest

from src import extraction_rules as rules
from src.extractor import IMAGE_OCR, extract_with_image_fallback

PUBLISHED = "2026-09-01"


def _venue_evidence(ev):
    return [e for e in ev.evidences if e.field == "venue"]


# --- T1-T3, T10: what a poster may no longer contribute ----------------------

@pytest.mark.parametrize("ocr", [
    "무차살사소셜 @스스me1 입장료 10,000원",              # T1: no space
    "무차살사소셜 @ 스스 me1 입장료 10,000원",            # T2: a space
    "무차살사소셜 @ 정모비 1만원 * 9월 20일",              # a fee
    "무차살사소셜 @ x 수요일 9Al ~ 1041 - 9월 20일",       # a clock
    "무차살사소셜 @ 월요일 | 8회 12/21 9월 20일",          # a session count
    "무차살사소셜 @® 카카오 ziazia | 문4 9월 20일",        # a contact line
    "무차살사소셜 @ 바차타 9월 20일",                      # a genre word
    "무차살사소셜 @ + we. SALSA ㆍ BACHATA 9월 20일",      # a tagline
    "무차살사소셜 @&메릴린 부캠팀 9월 20일",               # a team
    "무차살사소셜 @ we BS 9월 20일",                       # OCR noise
    "무차살사소셜 at = see 출 o 9월 20일",                  # OCR noise, "at" form
])
def test_an_unlabelled_poster_reading_is_not_this_events_venue(ocr):
    """T1/T2/T10. Every shape found on a real Production poster."""
    ev = extract_with_image_fallback(
        "무차살사소셜", "9/20(토) 21:00~01:00",
        event_type="SOCIAL", published=PUBLISHED, image_texts=[("img1", ocr)],
    )
    assert ev.venue is None
    assert not [e for e in _venue_evidence(ev) if e.evidence_type == IMAGE_OCR]


def test_a_social_handle_on_a_poster_is_not_a_venue_either():
    """T3. v0.96.2's own account guards already refuse this shape on body
    text; an image never reaches them now, one layer earlier."""
    ev = extract_with_image_fallback(
        "무차살사소셜", "9/20(토) 21:00~01:00",
        event_type="SOCIAL", published=PUBLISHED,
        image_texts=[("img1", "무차살사소셜 인스타그램 DM @allaboutswing 팔로우 부탁드립니다")],
    )
    assert ev.venue is None


def test_a_suffix_shaped_poster_reading_is_refused_too():
    """The other label that is not a label: "<name>스튜디오 <clock>". Found on
    a real poster ("8시 SEBO STUDIO") whose own body times the event three
    hours earlier, so the poster is describing a different row."""
    ev = extract_with_image_fallback(
        "BODY MOVEMENT TRAINING", "9/20(토) 07:00~",
        event_type="SOCIAL", published=PUBLISHED,
        image_texts=[("img1", "BODY MOVEMENT TRAINING 8시 SEBO STUDIO")],
    )
    assert ev.venue is None


# --- T6, T7: what a poster may still contribute ------------------------------

@pytest.mark.parametrize("labelled, expected", [
    ("장소: 라밀롱가 스튜디오", "라밀롱가 스튜디오"),                 # T6
    ("장소 : Pista", "Pista"),
    ("Venue: Tango Andante", "Tango Andante"),                       # T7
    ("Location: Club Ocho", "Club Ocho"),
    ("주소 : 까미니또 (대전 유성 계룡로66번길 5)", "까미니또 (대전 유성 계룡로66번길 5)"),
])
def test_a_labelled_poster_venue_is_still_read(labelled, expected):
    ev = extract_with_image_fallback(
        "탱고 이벤트", "9/5(토) 19:30-23:30 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", f"탱고 이벤트 {labelled}")],
    )
    assert ev.venue == expected
    assert [e for e in _venue_evidence(ev) if e.evidence_type == IMAGE_OCR]


# --- T4, T5, T13: body text is untouched -------------------------------------

@pytest.mark.parametrize("body, expected", [
    ("9월 24일 저녁 8시 @오초", "오초"),                              # T4
    ("9월 16일 9:15-11:15pm @ 아미고 스튜디오", "아미고 스튜디오"),     # T5
    ("9월 24일 저녁 8시 @Studio Ocho", "Studio Ocho"),
    ("9월 24일 저녁 8시 @ 오초 에서 만나요", "오초"),
])
def test_an_at_venue_in_body_text_is_unchanged(body, expected):
    """T4/T5. The "@" branch is safe on a curated body and stays there - this
    release narrows the image path only."""
    reading = rules.extract_venue(body)
    assert reading is not None and reading.name == expected
    assert reading.label == rules.VENUE_LABEL_AT


def test_the_v0962_account_fixtures_still_refuse_a_handle_in_body_text():
    """T13. v0.96.2's own guards, unchanged."""
    assert rules.extract_venue("@allaboutswing 팔로우 부탁드립니다") is None
    assert rules.extract_venue("@some_other_handle º 인스타") is None
    assert rules.extract_venue("인스타그램 DM: @intothelatinittl") is None


def test_a_suffix_venue_in_body_text_is_unchanged():
    reading = rules.extract_venue("아미고 스튜디오 9:15pm")
    assert reading is not None and reading.name == "아미고 스튜디오"
    assert reading.label == rules.VENUE_LABEL_SUFFIX


# --- T8, T9: the body always wins ---------------------------------------------

def test_a_body_venue_beats_a_false_poster_reading():
    """T9. Unchanged from v0.84.3, restated because the fix touches this path:
    a venue the body states is never replaced by an image."""
    ev = extract_with_image_fallback(
        "탱고 이벤트", "9/5(토) 19:30-23:30 장소: 라밀롱가 스튜디오",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "탱고 이벤트 @ 스스 me1 입장료 13,000원")],
    )
    assert ev.venue == "라밀롱가 스튜디오"
    assert ev.fee == 13000


def test_a_body_at_venue_also_beats_a_false_poster_reading():
    """T8. The body's own "@" reading is still trusted, and still wins."""
    ev = extract_with_image_fallback(
        "정모", "9월 24일 저녁 8시 @오초",
        event_type="SOCIAL", published=PUBLISHED,
        image_texts=[("img1", "정모 @ 정모비 1만원 * 입장료 13,000원")],
    )
    assert ev.venue == "오초"


def test_a_false_poster_reading_no_longer_conflicts_with_the_body():
    """A conflict row for a reading that was never a venue told a reviewer
    nothing. It is gone with the reading; a *labelled* disagreement still
    records one (v0.84.3's own contract)."""
    noise = extract_with_image_fallback(
        "탱고 이벤트", "9/5(토) 19:30-23:30 장소: 라밀롱가 스튜디오",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "탱고 이벤트 @ 스스 me1 입장료 13,000원")],
    )
    assert not [e for e in noise.evidences
                if e.value == "IMAGE_EVIDENCE_CONFLICT" and "venue" in (e.raw_text or "")]

    labelled = extract_with_image_fallback(
        "탱고 이벤트", "9/5(토) 19:30-23:30 장소: 라밀롱가 스튜디오",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "탱고 이벤트 장소: 다른곳 입장료 13,000원")],
    )
    assert [e for e in labelled.evidences
            if e.value == "IMAGE_EVIDENCE_CONFLICT" and "venue" in (e.raw_text or "")]


# --- the shared poster (§31) ---------------------------------------------------

def test_one_poster_cannot_hand_the_same_false_venue_to_unrelated_posts():
    """Production shape: DanceInfo's detail pages carry the post's own poster
    plus a carousel of other events', and one of those carousel posters
    (`posters/4588/...`) reached 39 different items. Its OCR "@ 스스 me1" became
    the venue of eighteen of them - a Gwangju party, an Incheon party, a
    Gangnam one, a Daegu one. Whatever else that poster is doing on those
    pages, it may not name their venue.

    The carousel itself is a separate defect and this release does not fix it:
    a *labelled* reading off a foreign poster would still be adopted. What is
    fixed is that an unlabelled one cannot be."""
    shared = ("@ 스스 me1 살사 바차타 파티 소셜 21:00 START "
              "DJ 라인업은 카페에서 확인해주세요")
    for title, body in [
        ("모두의 라틴 바차타 워크숍 및 살사 파티", "10/3(토) 21:00~01:00 광주"),
        ("검단 라틴솔 동호회 10월 미니파티", "10/3(토) 오후 9시~11:30 인천 검단"),
        ("명절 메인 심야 파티!", "9/25(금) 21:00 서울 강남"),
        ("BABARU 소셜 OPEN!", "9/25(금) 21:00 대구"),
    ]:
        ev = extract_with_image_fallback(
            title, body, event_type="SOCIAL", published=PUBLISHED,
            image_texts=[("shared-poster", shared)],
        )
        assert ev.venue is None, title


# --- the gate itself ----------------------------------------------------------

def test_the_shortcut_labels_are_named_where_both_sides_can_see_them():
    """The gate reads a label back out of an evidence string, so the two
    values that are not labels are declared once rather than spelled twice."""
    assert rules.VENUE_LABEL_AT in rules.VENUE_SHORTCUT_LABELS
    assert rules.VENUE_LABEL_SUFFIX in rules.VENUE_SHORTCUT_LABELS
    assert "장소" not in rules.VENUE_SHORTCUT_LABELS
